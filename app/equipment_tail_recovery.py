"""Explicit same-run recovery of a cancelled, unstarted Equipment tail.

No device calls here. Previously executed manual Skills are imported only with
pinned successful receipts and the exact cycle CSV. Dispatch remains owned by
the ordinary planning tail, Equipment agent, and Guardian.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from app.run_recovery import run_directory

ROOT = Path(__file__).resolve().parents[1]
ADOPT = (("await_auto_return", "utm_await_auto_return", "1.0.9"),
         ("save_raw_data", "utm_save_raw_data", "1.0.11"),
         ("validate_raw_data", "utm_validate_raw_data", "1.0.7"))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def boundary(state, record):
    identity = record['identity']
    loop = int(identity['sequence_id'].split('stacked-loop-', 1)[1].split('-', 1)[0])
    if (identity['run_id'] != state.run_id or identity['experiment_id'] != state.experiment_id
            or identity['specimen_id'] != state.current_experiment_spec.get('specimen_id')
            or state.loop_count not in (loop, loop + 1)):
        raise ValueError('Equipment tail identity/cycle mismatch')
    result = record.get('workflow_result') or {}
    data = result.get('data') or {}
    execution = data.get('equipment_skill_flow_execution') or {}
    if (record.get('lifecycle') != 'ESCALATED'
            or data.get('failure_code') != 'EQUIPMENT_WORKFLOW_SCOPE_CHANGED'
            or execution.get('failure_code') != 'EQUIPMENT_AGENTIC_RUN_CANCELLED'
            or record['checkpoint'].get('next_index') != 3):
        raise ValueError('Only the proven pre-Height-return cancellation is supported')
    last = (execution.get('transitions') or [{}])[-1]
    completed = [x['block_id'] for x in record['checkpoint']['transitions']
                 if x.get('phase') == 'skill' and x.get('success') is True]
    if (last.get('block_id') != 'await_auto_return' or last.get('outcome') != 'cancelled'
            or completed != ['prepare_next_specimen', 'start_test', 'monitor_contact_and_run']):
        raise ValueError('Ambiguous or already executed tail')
    if any(getattr(state, key) for key in ('stop_requested', 'safe_stop_requested', 'emergency_stop_requested')):
        raise ValueError('Safety controls prohibit tail recovery')
    if state.run_metadata.get('active_safety_sources'):
        raise ValueError('Active safety source prohibits tail recovery')
    return loop


def read_request(root, run_id):
    directory = run_directory(root, run_id) / 'recovery'
    envelope = json.loads((directory / 'equipment_tail_request.json').read_text())
    raw = envelope['payload_json']
    if hashlib.sha256(raw.encode()).hexdigest() != envelope['sha256']:
        raise ValueError('Tail request integrity mismatch')
    request = json.loads(raw)
    if request.get('run_id') != run_id or request.get('requested_by') != 'operator':
        raise ValueError('Tail request identity mismatch')
    for path, sha in request['evidence_hashes'].items():
        if digest(path) != sha:
            raise ValueError('Tail evidence changed: ' + path)
    return request


def validate(state, request, flow):
    from agents.equipment.agent import LabEquipmentAgent
    from agents.equipment.workflow import _describe
    source = json.loads(Path(request['source_path']).read_text())
    loop = boundary(state, source)
    if loop != request['loop_id']:
        raise ValueError('Tail cycle changed')
    if _describe(LabEquipmentAgent(), state, flow) != request['description']:
        raise ValueError('Equipment Skill Flow or deployed programs changed')
    if state.current_experiment_spec != request['experiment_spec']:
        raise ValueError('Experiment settings changed')
    return source


def unstarted_tail(controller, request):
    """A prior Guardian pre-gate refusal is retryable; a started EQP is not."""
    marker = controller._state.run_metadata.get('equipment_tail_recovery') or {}
    if marker.get('status') != 'returned' or (marker.get('result') or {}).get('decision') != 'stop':
        return False
    sequence = f"stacked-loop-{request['loop_id']}-tail-{request['source_execution_id']}"
    directory = ROOT / 'memory/equipment_runtime/workflow_decisions/executions'
    for path in directory.glob('*/state.json'):
        identity = json.loads(path.read_text()).get('identity') or {}
        if identity.get('run_id') == request['run_id'] and identity.get('sequence_id') == sequence:
            return False
    return True


def reconcile_printer_observation(state, health):
    """Recovery uses the same identity/freshness/manual-latch rules as Guardian."""
    from utils.hardware_alert_lifecycle import reconcile
    return reconcile(state, health)


def prepare_request(snapshot, root, execution_id):
    """Offline preparation only; immutable evidence is pinned before Restore."""
    from orchestrator.state import OrchestratorState
    from agents.equipment.agent import LabEquipmentAgent
    from agents.equipment.workflow import _describe
    from utils.equipment_agentic_task import bind_cycle_csv_artifact
    from utils.equipment_skill_flow import EquipmentSkillFlowStore
    state = OrchestratorState.model_validate(snapshot['state'])
    if snapshot.get('is_running') or state.stage.value not in ('complete', 'error'):
        raise ValueError('Tail must be inactive')
    source_path = ROOT / 'memory/equipment_runtime/workflow_decisions/executions' / execution_id / 'state.json'
    if source_path.parent.parent != ROOT / 'memory/equipment_runtime/workflow_decisions/executions':
        raise ValueError('Invalid execution ID')
    source = json.loads(source_path.read_text())
    loop = boundary(state, source)
    run = run_directory(root, state.run_id)
    directory = run / 'recovery'
    if (directory / 'equipment_tail.claim').exists():
        raise ValueError('Tail recovery already dispatched')
    archive_paths = sorted(run.glob('runtime/loops/loop-*/equipment_agent/attempt-*/result.json'))
    archive = archive_paths[-1]
    if json.loads(archive.read_text())['data']['equipment_workflow_execution_id'] != execution_id:
        raise ValueError('A newer Equipment attempt exists')
    flow = EquipmentSkillFlowStore(LabEquipmentAgent._SKILL_FLOW_PATH).get('utm_windows_v1')
    checkpoint = deepcopy(source['checkpoint'])
    hashes = {str(source_path): digest(source_path), str(archive): digest(archive)}
    export_context = {'mode': 'live', 'session_id': state.active_session_id,
        'specimen_id': state.current_experiment_spec['specimen_id'], 'loop_index': loop + 1, 'repeat_index': 1}
    saved_artifact = None
    for index, (block, skill, version) in enumerate(ADOPT, 3):
        if flow['blocks'][index]['id'] != block or flow['blocks'][index]['skill'] != {'skill_id': skill, 'skill_version': version}:
            raise ValueError('Adoption block order changed')
        manifest = ROOT / 'memory/equipment_skills' / skill / version / 'manifest.json'
        receipt = json.loads(manifest.read_text())['last_test']
        if (receipt.get('ok') is not True or receipt.get('runtime_mode') != 'live'
                or receipt.get('tested_at', '') <= source['updated_at']
                or len(receipt.get('program_results', [])) != 1):
            raise ValueError('No fresh successful receipt for ' + block)
        raw = deepcopy(receipt['program_results'][0])
        if raw.get('ok') is not True or raw.get('program_id') != f'{skill}_{version.replace(".", "_")}_segment_001':
            raise ValueError('Skill receipt/program mismatch')
        proof_path = directory / f'equipment_tail_{block}.json'
        # Never mutate deployed Skill receipts; copy exact evidence into this run.
        encoded = json.dumps(receipt, ensure_ascii=False, indent=2)
        if proof_path.exists() and proof_path.read_text() != encoded:
            raise ValueError('Pinned Skill receipt changed')
        if not proof_path.exists():
            proof_path.write_text(encoded)
        hashes[str(proof_path)] = digest(proof_path)
        evidence = {'adopted_receipt': str(proof_path), 'adopted_receipt_sha256': hashes[str(proof_path)]}
        for artifact in raw.get('output_artifacts') or []:
            path = artifact.get('local_path') or artifact.get('path')
            if path:
                if digest(path) != artifact.get('sha256'):
                    raise ValueError('Skill artifact changed')
                hashes[path] = digest(path)
        if block != 'await_auto_return':
            raw = bind_cycle_csv_artifact(raw, run_id=state.run_id, export_context=export_context)
            artifacts = [x for x in raw.get('output_artifacts', []) if x.get('kind') == 'utm_csv']
            if len(artifacts) != 1:
                raise ValueError('Exactly one cycle CSV is required')
            artifact = artifacts[0]
            if (artifact.get('run_id') != state.run_id or artifact.get('specimen_id') != export_context['specimen_id']
                    or artifact.get('local_parse_ok', artifact.get('parse_ok')) is not True
                    or not artifact.get('row_count_probe') or not artifact.get('pulled_to_linux')):
                raise ValueError('CSV does not prove this cycle')
            if saved_artifact and any(artifact.get(k) != saved_artifact.get(k) for k in ('windows_path', 'sha256')):
                raise ValueError('Validation is for a different CSV')
            evidence.update({k: artifact.get(k) for k in ('artifact_id', 'run_id', 'specimen_id', 'linux_path',
                'windows_path', 'sha256', 'row_count_probe', 'columns_probe', 'stable_for_sec')})
            evidence.update(artifact_kind='utm_csv', data_parse_probe_ok=True, write_complete=True,
                raw_csv_path=artifact['windows_path'])
            checkpoint['run_context'].update(evidence)
            if block == 'save_raw_data':
                saved_artifact = artifact
                checkpoint['saved_csv_result'] = raw
        checkpoint['transitions'].append({'block_id': block, 'node_id': block + '.skill',
            'phase': 'skill', 'kind': 'skill', 'skill_id': skill, 'skill_version': version,
            'outcome': 'completed', 'success': True, 'target': flow['blocks'][index + 1]['id'],
            'summary': 'Adopted verified explicit recovery Skill receipt; not re-executed',
            'timestamp': receipt['tested_at'], 'evidence': evidence})
    checkpoint['next_index'] = 6
    request = {'schema': 'equipment_tail_recovery.v1', 'requested_by': 'operator',
        'run_id': state.run_id, 'loop_id': loop, 'source_execution_id': execution_id,
        'source_path': str(source_path), 'evidence_hashes': hashes, 'checkpoint': checkpoint,
        'experiment_spec': deepcopy(state.current_experiment_spec),
        'description': _describe(LabEquipmentAgent(), state, flow), 'one_cycle_only': True}
    encoded = json.dumps(request, ensure_ascii=False)
    path = directory / 'equipment_tail_request.json'
    with path.open('x') as stream:
        json.dump({'payload_json': encoded, 'sha256': hashlib.sha256(encoded.encode()).hexdigest()}, stream)
    return {'request_path': str(path), 'next_block': flow['blocks'][6]['id'], 'loop_id': loop}


def restore(controller, run_id):
    from orchestrator.state import Stage
    request = read_request(controller._deps.run_root, run_id)
    state = controller._state
    if state.run_id != run_id or not state.is_paused or controller._planning_request_lock.locked():
        raise ValueError('Restore requires this paused inactive run')
    validate(state, request, request['description']['flow'])
    retry_unstarted = unstarted_tail(controller, request)
    if (run_directory(controller._deps.run_root, run_id) / 'recovery/equipment_tail.claim').exists() and not retry_unstarted:
        raise ValueError('Equipment tail was already dispatched')
    before = run_directory(controller._deps.run_root, run_id) / 'recovery/before_equipment_tail.json'
    if not before.exists():
        before.write_text(json.dumps(controller.snapshot(), ensure_ascii=False, default=str))
    health = controller._deps.agent_context.tools.call('printer.prepare', {
        'runtime_mode':'live', 'health_only':True, 'status_only':True, 'skip_ftps_probe':True})
    for alert in reconcile_printer_observation(state, health):
        controller._append_guardian_event({'type':'hardware_observation_resolved', **alert})
    state.loop_count = request['loop_id']
    state.stage = Stage.ERROR
    state.run_metadata.pop('equipment_selection_retry', None)
    state.run_metadata['equipment_tail_recovery'] = {'status': 'ready', 'loop_id': request['loop_id'],
        'source_execution_id': request['source_execution_id'], 'one_cycle_only': True,
        'retry_unstarted':retry_unstarted}
    return {'ok': True, 'status': 'restored_awaiting_resume', 'run_id': run_id,
        'resume_stage': 'equipment', 'next_block': 'advance_without_save', 'actuation_performed': False}


async def continue_tail(controller, first_spec, start_cycle):
    """The original orchestration tail, not a standalone device executor."""
    from orchestrator.state import Stage
    state = controller._state
    request = read_request(controller._deps.run_root, state.run_id)
    validate(state, request, request['description']['flow'])
    if start_cycle != request['loop_id'] + 1 or first_spec != request['experiment_spec']:
        raise ValueError('Planning tail cycle/specimen changed')
    path = run_directory(controller._deps.run_root, state.run_id) / 'recovery/equipment_tail.claim'
    recovery = state.run_metadata['equipment_tail_recovery']
    if path.exists() and recovery.get('retry_unstarted'):
        marker = deepcopy(recovery)
        # Recheck absence of a dispatch receipt immediately before the retry.
        recovery.update(status='returned', result={'decision':'stop'})
        allowed = unstarted_tail(controller, request)
        recovery.clear()
        recovery.update(marker)
        if not allowed:
            raise ValueError('EQP already started; refusing pre-gate retry')
        with path.open('a') as stream:
            stream.write('\n' + json.dumps({'retry':'guardian_pre_gate_only','start_cycle':start_cycle}))
    else:
        with path.open('x') as stream:
            json.dump({'source_execution_id': request['source_execution_id'], 'start_cycle': start_cycle}, stream)
    recovery['status'] = 'running'
    try:
        result = await controller._run_planning_loop_tail(first_spec, cycle_index=start_cycle,
            total_cycles=controller._planning_cycle_limit(first_spec), resume_stage=Stage.EQUIPMENT)
        recovery.update(status='returned', result=result)
        return result
    finally:
        state.is_paused = True
        await controller._emit_control_event('equipment_tail_recovery.returned',
            'Original loop tail returned; next fabrication not dispatched', dict(recovery))


if __name__ == '__main__':
    import argparse
    from urllib.request import urlopen
    parser = argparse.ArgumentParser()
    parser.add_argument('--execution-id', required=True)
    args = parser.parse_args()
    with urlopen('http://127.0.0.1:7860/api/state', timeout=20) as response:
        snapshot = json.load(response)
    print(json.dumps(prepare_request(snapshot, ROOT / 'runs', args.execution_id)))
