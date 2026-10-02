import hashlib
import json
from pathlib import Path

import pytest

from utils.artifact_preservation import AGENTS, digest, preserve_execution, preserve_run
from utils.agent_artifact_archive import resolve_artifact_reference


def execution(tmp_path, agent='analysis', data=None, loop=1, status='completed'):
    run = tmp_path / 'runs/run-evidence'
    directory = run / f'runtime/loops/loop-{loop:06d}/{agent}_agent/attempt-000001'
    directory.mkdir(parents=True)
    manifest = dict(schema='atr.agent_artifact_execution.v1', run_id=run.name, agent=agent+'_agent',
                    loop_index=loop-1, loop_number=loop, execution_id='saved-execution',
                    status=status, artifacts=[], specimen_id='specimen-owned')
    (directory / 'input.json').write_text('{}')
    (directory / 'events.jsonl').write_text('{}\n')
    (directory / 'result.json').write_text(json.dumps({'data': data or {'decision': {'status':'accepted'}}}))
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    return run, directory, manifest


@pytest.mark.parametrize('agent', AGENTS)
def test_all_agent_evidence_retains_result_and_exact_scope(tmp_path, agent):
    run, directory, _ = execution(tmp_path, agent, {'handoff': {'note': 'unchanged'}, 'decision': {'value': 3}})
    before = {p.name:digest(p) for p in directory.iterdir() if p.is_file()}
    result = preserve_execution(run, directory/'manifest.json')
    assert result['agent'] == agent+'_agent' and result['loop_index'] == 0
    assert result['result_components'] == ['decision', 'handoff']
    assert result['actuation_performed'] is False
    assert {p.name:digest(p) for p in directory.iterdir() if p.is_file()} == before
    assert {x['role'] for x in result['retained']} == {'input.json', 'result.json', 'events.jsonl', 'manifest.json'}


def test_curves_use_frozen_canonical_csv_and_do_not_modify_metrics(tmp_path):
    run, directory, manifest = execution(tmp_path)
    files = directory/'files'; files.mkdir()
    canonical = files/'snapshot_canonical_curve.csv'
    canonical.write_text('displacement_mm,force_N,strain,stress_MPa\n0,0,0,0\n15,100,0.5,0.111\n')
    manifest['artifacts'] = [{'source_path':str(run/'analysis/canonical_curve.csv'), 'path':str(canonical.relative_to(run)),
                              'sha256':digest(canonical), 'status':'copied'}]
    (directory/'manifest.json').write_text(json.dumps(manifest))
    original = digest(directory/'result.json')
    report = preserve_execution(run,directory/'manifest.json')
    assert {Path(x['path']).name for x in report['generated']} == {'force_displacement.png','force_displacement.svg','stress_strain.png','stress_strain.svg'}
    assert report['sources'][0]['sha256'] == digest(canonical)
    assert digest(directory/'result.json') == original
    assert report == preserve_execution(run,directory/'manifest.json')
    assert (directory/'preserved/force_displacement.png').read_bytes().startswith(b'\x89PNG')


def test_local_url_backfill_preserves_source_and_never_uses_latest_image(tmp_path):
    run, directory, _ = execution(tmp_path,'vision',{'preview_url':'/api/runs/run-evidence/artifact-file/vision/saved.png',
        'raw_path':'/tmp/atr_lerobot_latest_frame/top_color.png', 'unsafe_url':'/api/runs/other/artifact-file/secrets.png'})
    image=run/'vision/saved.png'; image.parent.mkdir(); image.write_bytes(b'historical-image')
    result=preserve_execution(run,directory/'manifest.json')
    assert len(result['generated'])==1
    assert (run/result['generated'][0]['path']).read_bytes()==b'historical-image'
    assert any(x['status']=='historical_source_unavailable' for x in result['gaps'])


def test_reference_resolver_rejects_cross_run_and_traversal(tmp_path):
    run=(tmp_path/'runs/r').resolve()
    for url in ['/api/runs/other/artifact-file/a.png','/api/runs/r/artifact-file/../../../secret.png',
                '/api/runs/r/artifact-file/%2e%2e/%2e%2e/secret.png','https://example.test/a.png']:
        assert resolve_artifact_reference(url,tmp_path,run) is None
    assert resolve_artifact_reference('/api/runs/r/artifact-file/a.png?download=1',tmp_path,run)==run/'a.png'


def test_wrong_identity_and_output_symlink_rejected(tmp_path):
    run,directory,manifest=execution(tmp_path,'guardian')
    outside=tmp_path/'outside';outside.mkdir()
    (directory/'preserved').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):preserve_execution(run,directory/'manifest.json')
    assert not list(outside.iterdir())
    (directory/'preserved').unlink()
    manifest['loop_index']=8
    (directory/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):preserve_execution(run,directory/'manifest.json')


def test_recording_is_not_completed_or_rendered(tmp_path):
    run,directory,_=execution(tmp_path,'specimen',status='running')
    assert preserve_execution(run,directory/'manifest.json')['status']=='recording'
    assert not (directory/'preserved').exists()


def test_manipulation_prefers_reclassified_display_artifacts_and_refreshes_receipt(tmp_path):
    run, directory, _ = execution(tmp_path, 'manipulation')
    stream = directory / 'streams/s'
    stream.mkdir(parents=True)
    (stream / 'session.json').write_text('{"session_id":"s","status":"STOPPED"}')
    (stream / 'policy_tracking.png').write_bytes(b'old graph')
    revised = stream / 'grasp_display_v5'
    revised.mkdir()
    for name in ['policy_tracking.png', 'policy_tracking_summary.json', 'grasp_outcomes.json']:
        (revised / name).write_bytes(b'new derived evidence')
    receipt = preserve_execution(run, directory / 'manifest.json')
    paths = {item['path'] for item in receipt['generated']}
    assert len(paths) == 3
    assert all('/grasp_display_v5/' in path for path in paths)
    (revised / 'policy_tracking_summary.json').write_text('{"task_progress":{"success_count":2}}')
    refreshed = preserve_execution(run, directory / 'manifest.json')
    summary = next(item for item in refreshed['generated'] if item['path'].endswith('policy_tracking_summary.json'))
    assert summary['sha256'] == digest(revised / 'policy_tracking_summary.json')


def test_missing_canonical_is_explicit_not_synthetic(tmp_path):
    run,directory,_=execution(tmp_path)
    result=preserve_execution(run,directory/'manifest.json')
    assert result['status']=='needs_attention'
    assert not result['generated']
    report=preserve_run(run)
    assert set(report['agents'])==set(AGENTS)
    assert report['agents']['analysis']['gaps']==1


def test_saved_design_candidates_and_constraints_export_without_reassessment(tmp_path):
    candidate={'candidate_id':'saved-a','status':'selected','cell_size_mm':7,'wall_thickness_mm':.9,
               'design_evaluation':{'constraint_margins':[{'constraint':'minimum_wall','status':'unmeasured','actual':None}]}}
    run,directory,_=execution(tmp_path,'design',{'candidate_ledger':[candidate]})
    result=preserve_execution(run,directory/'manifest.json')
    assert len(result['generated'])==4
    assert json.loads((directory/'preserved/constraint_checks.json').read_text())[0]['actual'] is None


def test_live_archive_copies_own_api_url(tmp_path):
    import asyncio
    from tests.unit.test_agent_artifact_archive import state
    from utils.agent_artifact_archive import AgentArtifactExecution
    async def capture():
        image=tmp_path/'runs/run-archive/vision/frame.png'
        image.parent.mkdir(parents=True);image.write_bytes(b'frame-at-capture')
        archive=AgentArtifactExecution(tmp_path/'runs',state(),'vision_agent')
        archive.capture({'image_url':'/api/runs/run-archive/artifact-file/vision/frame.png'})
        copied=archive.manifest['artifacts'][0]
        assert copied['status']=='copied'
        assert (archive.run_dir/copied['path']).read_bytes()==b'frame-at-capture'
    asyncio.run(capture())


def test_lhs_and_bo_saved_surfaces_export_under_original_loop_not_iteration(tmp_path):
    from tests.unit.test_bo_visualization_artifacts import _visualization
    from tests.unit.test_lhs_design_visualization_artifacts import _payload
    bo, lhs = _visualization(), _payload()
    bo['run_id'] = lhs['run_id'] = 'run-evidence'
    run, directory, _ = execution(tmp_path, 'bo', {'bo_result': {'visualization':bo, 'lhs_visualization':lhs}}, loop=2)
    result = preserve_execution(run,directory/'manifest.json')
    assert not result['gaps']
    assert len(result['generated']) == 7
    assert all('/loop-000002/bo_agent/' in x['path'] for x in result['generated'])
    assert result['loop_index']==1


def test_background_service_preserves_without_running_agent_or_device(tmp_path):
    import time
    from utils.artifact_preservation import PreservationService
    run, directory, _ = execution(tmp_path, 'guardian')
    service = PreservationService()
    try:
        service.offer(run)
        deadline = time.monotonic()+15
        while service.pending and time.monotonic()<deadline:
            time.sleep(.05)
        assert not service.pending
        assert (directory/'preserved/evidence_index.json').is_file()
        assert json.loads((run/'artifact_coverage.json').read_text())['actuation_performed'] is False
    finally:
        service.close()
