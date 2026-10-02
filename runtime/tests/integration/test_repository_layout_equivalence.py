"""Identical synthetic route/store/controller contract on pinned before/after exports."""
from copy import deepcopy
import asyncio
import hashlib
import json
from pathlib import Path


def test_paired_rollback_and_replay_preserve_original_evidence():
    from tools.repository_layout.fixture_server import fixture_application, fixture_evidence
    from fastapi.testclient import TestClient
    from orchestrator.state import Mode, Stage
    with fixture_application('import_only', isolated_authoring=True) as (main, guard, lifecycle):
        client = TestClient(main.app)
        roots = main._layout_fixture_evidence['roots']
        source = Path(roots['runtime_root'])
        original_files = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in (source / 'graphs').rglob('*') if p.is_file()}
        module_file = main.RUNTIME_MODULE_ROOT / 'design/module.yaml'
        original_bytes = module_file.read_bytes()
        payload = client.get('/api/modules/design').json()['module']
        assert payload['module']['id'] == 'design'
        def save(value, activate):
            response = client.put('/api/modules/design', json={'module': value, 'activate': activate,
                'reason': 'synthetic-layout-equivalence', 'author': 'fixture'})
            assert response.status_code == 200 and response.json()['ok'], response.text
            assert response.json()['activated'] is activate
            return response.json()['version']
        version = save(payload, False)
        assert module_file.read_bytes() == original_bytes
        version_file = Path(version['path'])
        assert version_file.is_relative_to(Path(roots['memory_root']))
        original_version = version_file.read_bytes()
        changed = deepcopy(payload)
        changed['module']['label'] = 'Synthetic changed label'
        save(changed, True)
        changed_bytes = module_file.read_bytes()
        assert changed_bytes != original_bytes
        version_document = client.get('/api/modules/design/versions/' + version['version_id']).json()['version']['module']
        assert version_document['metadata']['module_id'] == 'design'
        restored = {'module': version_document['module']}
        assert restored == payload
        # Reading, drafting, validation and a non-activating save cannot roll back active bytes.
        assert module_file.read_bytes() == changed_bytes
        validated = client.post('/api/modules/design/validate', json={'module': restored, 'activate': False})
        assert validated.status_code == 200 and validated.json()['ok'], validated.text
        assert module_file.read_bytes() == changed_bytes
        save(restored, False)
        assert module_file.read_bytes() == changed_bytes
        save(restored, True)
        assert client.get('/api/modules/design').json()['module'] == payload
        assert version_file.read_bytes() == original_version

        controller = main.controller
        trace = [{'event_id': 'synthetic-recorded-event', 'event_type': 'node.completed',
                  'payload': {'fixture': 'supplied_trace_not_historical_run'}}]
        controller._last_completed_trace = deepcopy(trace)
        recorded = []
        broadcast = controller._broadcast_event
        async def observe(event):
            recorded.append(deepcopy(event))
            return await broadcast(event)
        controller._broadcast_event = observe
        async def replay():
            result = await controller.start(mode=Mode.REPLAY)
            assert result['ok'], result
            await asyncio.wait_for(controller._run_task, timeout=5)
        asyncio.run(replay())
        assert controller._state.stage == Stage.COMPLETE and controller._state.mode == Mode.REPLAY
        assert controller._state.agent_status == {}
        assert controller._last_completed_trace == trace
        assert 'experimental_setup_snapshot' not in controller._state.run_metadata
        assert [e['event_type'] for e in recorded if e.get('event_type', '').startswith('replay')] == [
            'replay_event', 'replay_complete']
        for relative, digest in original_files.items():
            assert hashlib.sha256((source / relative).read_bytes()).hexdigest() == digest
        evidence = fixture_evidence(main, guard, lifecycle)
        assert not evidence['unexpected_effects'] and not evidence['outside_imports']
        assert evidence['effects']['model_calls'] == 0
        lookalikes = {str(Path(roots['repository_root']) / 'memory'), str(source / 'memory')}
        assert not any(any(Path(write).is_relative_to(root) for root in lookalikes) for write in evidence['writes'])
        print(json.dumps({'schema': 'atr.layout_equivalence.v1', 'scenario': 'module-rollback-and-replay-v1',
            'contract': {'module_id': 'design', 'rollback_requires_explicit_save': True,
                         'original_module_sha256': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                         'replay_events': ['replay_event', 'replay_complete'], 'owner_calls': 0},
            'original_version_sha256': hashlib.sha256(original_version).hexdigest(),
            'source_hashes': original_files, **evidence}, sort_keys=True))
