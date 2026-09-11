"""Existing full controller cycle with isolated files and physical-I/O tripwires."""
from pathlib import Path
import asyncio
from contextlib import suppress
import shutil
import socket
import subprocess

import pytest
import yaml


@pytest.mark.asyncio
async def test_guardian_preserves_two_virtual_controller_cycles(tmp_path, monkeypatch):
    from app.bootstrap import load_runtime
    from agents.design_agent import DesignAgent
    from agents.guardian_agent import GuardianAgent
    from backends.mock_llm import MockLLMBackend
    from device_bridges.lerobot_bridge import LeRobotBridge
    from orchestrator.state import Mode, Stage
    from utils.agent_artifact_archive import list_executions
    from utils import paths

    root = Path(__file__).resolve().parents[2]
    for folder in ('configs', 'graphs', 'docs/project'):
        shutil.copytree(root / folder, tmp_path / folder)
    # Explicit simulator configuration; the checked-in default has autoejection
    # disabled and correctly blocks a fabrication-complete claim.
    devices_path = tmp_path / 'configs/devices.yaml'
    devices = yaml.safe_load(devices_path.read_text())
    devices['devices']['printer']['autoejection']['enabled'] = True
    devices_path.write_text(yaml.safe_dump(devices, sort_keys=False))
    monkeypatch.setattr(paths, 'project_root', lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('AUTONOMOUS_USE_REAL_LLM_IN_TEST', '0')
    monkeypatch.setenv('AUTONOMOUS_ALLOW_MOCK_FALLBACK', '1')
    monkeypatch.setenv('AUTONOMOUS_BACKEND', 'vllm')
    monkeypatch.setenv('NEMOCLAW_AUTO_START_PROXY', '0')
    for name in ('OPENAI_API_KEY', 'TAVILY_API_KEY', 'SERPER_API_KEY'):
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError('Virtual cycle attempted network/native process execution')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    controllers = []

    def offline_runtime():
        controller = load_runtime()
        controllers.append(controller)
        ctx = controller._deps.agent_context
        backend = MockLLMBackend()
        ctx.primary_backend = ctx.fallback_backend = backend
        ctx.primary_backends = {key: backend for key in ctx.primary_backends}
        ctx.fallback_backends = {key: backend for key in ctx.fallback_backends}
        ctx.tools.register('vision.utm_runtime.start', lambda payload: {
            'ok': True, 'tool': 'vision.utm_runtime.start',
            'status': 'virtual_bridge_selected', 'observer_mode': 'virtual_utm_bridge',
            'simulated': True, 'actuation_performed': False, 'request': dict(payload),
        })
        return controller

    original_finalize = DesignAgent._finalize_design_payload

    def virtual_design(self, *args, **kwargs):
        result = original_finalize(self, *args, **kwargs)
        result['experiment_spec']['execution_policy'] = {
            'manipulation': 'virtual', 'vision': 'virtual', 'lab_equipment': 'virtual'}
        return result

    def virtual_placement(_bridge, session):
        session_id = session.get('session_id') or 'virtual-rollout'
        packet = {'schema': 'atr.robot_joint_telemetry.v1', 'type': 'joint_sample',
            'session_id': session_id, 'sequence': 2,
            'actual_source': {'source': 'virtual_controller_fixture'},
            'target_source': {'source': 'virtual_controller_fixture'},
            'motion_state': {key: {'base_state': 'home', 'gripper_state': 'idle',
                'home_gate': {'passed': True}} for key in ('measured', 'policy')}}
        return {'joint_telemetry': {'schema': 'atr.robot_joint_telemetry.v1', 'status': 'available',
                    'session_id': session_id, 'log_path': 'virtual://guardian-cycle', 'packet': packet},
                'post_place_interlock': {'schema': 'post_place_interlock.v1', 'session_id': session_id,
                    'ungrasping_seen': True, 'ungrasping_sequence': 1, 'measured_base_state': 'home',
                    'measured_gripper_state': 'idle', 'home_gate_passed': True,
                    'home_after_ungrasping': True, 'ready_for_utm_snapshot': True, 'latest_sequence': 2}}

    monkeypatch.setattr(DesignAgent, '_finalize_design_payload', virtual_design)
    monkeypatch.setattr(LeRobotBridge, '_rollout_joint_telemetry_contract', virtual_placement)
    monkeypatch.setattr(GuardianAgent, 'TEST_LOOP_CYCLE_LIMIT', 2)
    controller = offline_runtime()

    async def run_two_cycles():
        assert (await controller.start(mode=Mode.TEST, goal='Guardian virtual loop regression'))['ok']
        while True:
            snapshot = controller.snapshot()
            assert not snapshot['state']['is_paused'], snapshot['state']['run_metadata'].get('guardian')
            stage = snapshot['state']['stage']
            assert stage != Stage.ERROR.value, snapshot['state'].get('error_message')
            if stage == Stage.COMPLETE.value:
                break
            await asyncio.sleep(.1)
        assert snapshot['state']['loop_count'] == 2
        metadata = snapshot['state']['run_metadata']
        assert metadata['utm_clear_execution']['success'] is True
        assert metadata['utm_clear_execution']['simulated'] is True
        assert metadata['guardian']['action'] == 'safe_stop'
        run_dir = Path(snapshot['logs']['json']).parent
        expected = {'design_agent', 'specimen_agent', 'vision_agent', 'manipulation_agent',
                    'equipment_agent', 'analysis_agent', 'knowledge_agent', 'bo_agent', 'guardian_agent'}
        for loop in range(2):
            entries = list_executions(run_dir, loop_index=loop)
            assert expected <= {entry['agent'] for entry in entries if entry['status'] == 'completed'}
            assert all((run_dir / entry['result_path']).is_file() for entry in entries)

    # The graph, agents and lifecycle assertions are real. Only external
    # acquisition/model boundaries above are virtual; native/network I/O fails.
    try:
        await asyncio.wait_for(run_two_cycles(), 120)
    finally:
        for controller in controllers:
            task = getattr(controller, '_run_task', None)
            if task is not None and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
