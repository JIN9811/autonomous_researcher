"""Resume an already-started printer job, never submit a second print.

Checkpoints are explicit, local, integrity-checked operator recovery artifacts.
The one-cycle boundary belongs to this recovery request, not experiment defaults.
"""
from collections import deque
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from app.run_recovery import run_directory


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_boundary(snapshot, planning, run_id):
    state = snapshot['state']
    if snapshot.get('is_running') or planning.get('is_planning_busy') or state['run_id'] != run_id:
        raise ValueError('Recovery requires the exact inactive run')
    if state['stage'] not in {'vision', 'specimen', 'error'}:
        raise ValueError('Not a printer completion boundary')
    if any(state.get(key) for key in ('stop_requested', 'safe_stop_requested', 'emergency_stop_requested')):
        raise ValueError('Safety recovery is required first')
    metadata = state.get('run_metadata') or {}
    if metadata.get('active_safety_sources'):
        raise ValueError('Active safety source')
    messages = planning.get('messages') or []
    if not messages or messages[-1].get('ok') is not False or 'printer completion wait timed out:' not in messages[-1].get('content', ''):
        raise ValueError('Latest handoff did not fail at printer completion wait')
    specimen = metadata.get('specimen_result') or {}
    spec = state.get('current_experiment_spec') or {}
    if not spec.get('specimen_id') or specimen.get('specimen_id') != spec['specimen_id']:
        raise ValueError('Specimen identity mismatch')
    post = (specimen.get('print_result') or {}).get('post_publish_status') or {}
    if not post.get('task_id') or str(post.get('status')).lower() not in {'running', 'started', 'printing'}:
        raise ValueError('No bound started printer task')
    if specimen.get('printer_completion_verified'):
        raise ValueError('Printer completion already consumed')
    return state, specimen, str(post['task_id'])


def save_checkpoint(snapshot, planning, root, run_id):
    state, specimen, task_id = validate_boundary(snapshot, planning, run_id)
    run = run_directory(root, run_id)
    transcript = Path(planning['transcript_path']).resolve()
    if transcript.parent != run or transcript.name != 'live_planning_transcript.jsonl':
        raise ValueError('Transcript must belong to this run')
    # Full durable agent output must agree with the live execution identity.
    result_path = run / f"runtime/loops/loop-{state['loop_count'] + 1:06d}/specimen_agent/attempt-000001/result.json"
    result = json.loads(result_path.read_text())['data']['specimen_result']
    if result.get('specimen_id') != specimen['specimen_id'] or str(result['print_result']['post_publish_status'].get('task_id')) != task_id:
        raise ValueError('Archived printer execution differs')
    artifact = Path(result['slicer_result']['sliced_artifact_path']).resolve()
    folder = run / 'recovery'
    folder.mkdir(exist_ok=True, mode=0o700)
    path = folder / 'printer_wait.json'
    if path.exists():
        raise ValueError('Printer recovery checkpoint already exists; preserve it')
    payload = {'schema':'printer_wait_recovery.v1','run_id':run_id,'snapshot':snapshot,'planning':planning,
               'task_id':task_id,'result_path':str(result_path),'result_sha256':digest(result_path),
               'artifact_path':str(artifact),'artifact_sha256':digest(artifact),
               'transcript_path':str(transcript),'transcript_sha256':digest(transcript),
               'stop_after_this_cycle':True}
    encoded = json.dumps(payload, ensure_ascii=False)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps({'sha256':hashlib.sha256(encoded.encode()).hexdigest(),'payload_json':encoded}, ensure_ascii=False))
    path.chmod(0o600)
    return {'checkpoint':str(path),'run_id':run_id,'task_id':task_id,'sha256':digest(path)}


def load_checkpoint(root, run_id):
    path = run_directory(root, run_id) / 'recovery/printer_wait.json'
    envelope = json.loads(path.read_text())
    if hashlib.sha256(envelope['payload_json'].encode()).hexdigest() != envelope['sha256']:
        raise ValueError('Printer checkpoint integrity mismatch')
    saved = json.loads(envelope['payload_json'])
    validate_boundary(saved['snapshot'], saved['planning'], run_id)
    for name in ('result', 'artifact'):
        if digest(saved[f'{name}_path']) != saved[f'{name}_sha256']:
            raise ValueError(f'{name} changed since checkpoint')
    return saved


def restore_checkpoint(controller, run_id):
    from orchestrator.state import OrchestratorState, Stage
    from orchestrator.experimental_setup import SetupStore
    from logging_system.logger_factory import build_logger_bundle
    from app.controller import PLANNING_TRANSCRIPT_MEMORY_LIMIT
    if controller.snapshot().get('is_running') or controller._planning_request_lock.locked() or controller._state.stage != Stage.IDLE:
        raise ValueError('Restore requires a fresh inactive server')
    if controller._active_safety_sources() or any(getattr(controller._state, key) for key in
            ('stop_requested','safe_stop_requested','emergency_stop_requested')):
        raise ValueError('Safety recovery required before restore')
    saved = load_checkpoint(controller._deps.run_root, run_id)
    transcript = Path(saved['transcript_path'])
    if transcript.resolve().parent != run_directory(controller._deps.run_root, run_id) or digest(transcript) != saved['transcript_sha256']:
        raise ValueError('Transcript changed since checkpoint')
    restored = OrchestratorState.model_validate(saved['snapshot']['state'])
    # Preserve the full durable owner payload rather than a compact UI projection.
    result = json.loads(Path(saved['result_path']).read_text())['data']['specimen_result']
    restored.run_metadata['specimen_result'] = result
    restored.run_metadata['printer_wait_recovery'] = {'status':'ready','task_id':saved['task_id'],
        'run_id':run_id,'loop_id':restored.loop_count,'specimen_id':result['specimen_id'],
        'stop_after_this_cycle':True}
    restored.is_paused = True
    session_id = saved['planning']['planning_session_id']
    setup_store = SetupStore(transcript.parent, session_id)
    messages = deque(maxlen=PLANNING_TRANSCRIPT_MEMORY_LIMIT)
    total = 0
    with transcript.open() as stream:
        for line in stream:
            if line.strip():
                messages.append(json.loads(line)); total += 1
    bundle = build_logger_bundle(run_id=run_id, run_root=controller._deps.run_root, logging_config=controller._deps.logging_config)
    controller._state = restored
    controller._logger_bundle = bundle
    controller._planning_session_id = session_id
    controller._canonical_planning_transcript_path = transcript
    controller._experimental_setup_store = setup_store
    controller._experimental_setup_session = session_id
    controller._planning_messages = list(messages)
    controller._planning_message_total = total
    controller._planning_bootstrapped = True
    return {'ok':True,'status':'restored_awaiting_resume','run_id':run_id,'task_id':saved['task_id'],'actuation_performed':False}


async def resume_printer_wait(controller):
    import asyncio
    from orchestrator.state import Stage
    async with controller._error_resume_lock:
        state = controller._state
        record = state.run_metadata.get('printer_wait_recovery') or {}
        if record.get('status') == 'running' and controller._planning_handoff_active():
            return {'ok':True,'status':'already_resuming'}
        if (record.get('status') != 'ready' or controller.snapshot().get('is_running')
                or controller._planning_request_lock.locked() or record.get('run_id') != state.run_id
                or record.get('loop_id') != state.loop_count or record.get('specimen_id') != state.current_experiment_spec.get('specimen_id')):
            return {'ok':False,'status':'blocked','message':'Printer recovery is not at the saved inactive boundary'}
        if controller._active_safety_sources() or any(getattr(state, key) for key in
                ('stop_requested','safe_stop_requested','emergency_stop_requested')):
            return {'ok':False,'status':'blocked','message':'Safety recovery required first'}
        rejection = await controller._plc_service_start_rejection()
        if rejection:
            return rejection
        specimen = state.run_metadata['specimen_result']
        spec = deepcopy(state.current_experiment_spec)
        fresh = await controller._read_specimen_printer_completion_status()
        classified = controller._classify_specimen_printer_completion_status(fresh, started_seen=True,
            expected_job_names=controller._expected_specimen_printer_job_names(spec, specimen))
        if str(classified.get('task_id')) != record['task_id'] or classified.get('status') not in {'running','complete'}:
            return {'ok':False,'status':'blocked','message':'Current printer job does not match saved execution','observed':classified}
        record['status'] = 'running'
        state.is_paused = False
        state.stage = Stage.SPECIMEN

        async def continue_existing_job():
            try:
                completion = await controller._await_specimen_printer_completion_before_vision(spec, specimen)
                if not completion or completion.get('task_id') != record['task_id']:
                    raise ValueError('Printer completion identity is not verified')
                updated = controller._apply_printer_completion_wait_to_specimen(specimen, completion)
                state.run_metadata['specimen_result'] = updated
                for key in ('fabrication_report','specimen_fabricated'):
                    if isinstance(updated.get(key), dict):
                        state.run_metadata[key] = updated[key]
                state.run_metadata['specimen_fabrication_report'] = updated.get('fabrication_report', {})
                controller._write_planning_artifacts(spec, specimen_result=updated)
                next_stage = controller._planning_tail_start_stage() or Stage.COMPLETE
                await controller._record_planning_orchestrator_transition(from_stage=Stage.SPECIMEN,to_stage=next_stage,payload=updated)
                await controller._record_planning_orchestrator_followup(stage=Stage.SPECIMEN,trigger='post_stage',payload=updated,next_stage=next_stage)
                record['status'] = 'tail_running'
                if record.get('stop_after_this_cycle'):
                    result = await controller._run_planning_loop_tail(spec, cycle_index=record['loop_id']+1,
                        total_cycles=controller._planning_cycle_limit(spec), resume_stage=next_stage)
                else:
                    context = state.run_metadata.get('_planning_resume_context') or {}
                    result = await controller._run_planning_cycle_series(first_spec=spec,
                        design_constraints=context.get('design_constraints') or spec.get('constraints') or {},
                        start_cycle=record['loop_id']+1, resume_tail_stage=next_stage)
                # A successful function return with a Guardian safe-stop is not
                # a successfully completed experiment cycle.
                failed_owner = any(getattr(owner, 'success', None) is False and
                    getattr(owner, 'run_id', None) == state.run_id and
                    getattr(owner, 'loop_id', None) == record['loop_id']
                    for owner in getattr(state, 'agent_status', {}).values())
                finished = result.get('ok') and result.get('decision') in {'continue','stop','complete'} and not failed_owner
                record.update(status='cycle_finished' if finished else 'needs_attention', result=result)
                # This task never invokes the next Design/Specimen stage.
                if record.get('stop_after_this_cycle'):
                    state.is_paused = True
                await controller._emit_control_event('printer_recovery.cycle_boundary','Recovered cycle returned; next cycle not started',
                    {'run_id':state.run_id,'recovery':dict(record),'one_cycle_only':bool(record.get('stop_after_this_cycle'))})
                return result
            except Exception as exc:
                record.update(status='failed',error=f'{type(exc).__name__}: {exc}')
                state.is_paused = True
                await controller._append_planning_message({'role':'system','ok':False,'content':record['error']},
                    event_type='printer_recovery.failed',level='ERROR',message='Printer recovery stopped; no print resubmission')
                return {'ok':False,'message':record['error']}

        controller._set_planning_handoff_task(asyncio.create_task(continue_existing_job()))
        return {'ok':True,'status':'resuming_existing_printer_job','run_id':state.run_id,'task_id':record['task_id'],'one_cycle_only':bool(record.get('stop_after_this_cycle'))}


if __name__ == '__main__':
    import argparse
    from urllib.request import urlopen
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id')
    parser.add_argument('--url', default='http://127.0.0.1:7860')
    args = parser.parse_args()
    def get(path):
        with urlopen(args.url + path, timeout=20) as response:
            return json.load(response)
    snapshot, planning = get('/api/state'), get('/api/planning/session')
    current = get('/api/state')
    if current['state']['current_experiment_spec'] != snapshot['state']['current_experiment_spec'] or current['state']['run_id'] != args.run_id or current.get('is_running'):
        raise ValueError('Run moved while capturing checkpoint')
    print(json.dumps(save_checkpoint(snapshot, planning, Path('runs'), args.run_id)))
