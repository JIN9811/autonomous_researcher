"""App bridge composition uses its existing frozen binding, not ambient roots."""
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from utils.runtime_paths import RuntimePaths


@pytest.fixture
def paths(tmp_path):
    return RuntimePaths(**{f.name: tmp_path / f.name for f in fields(RuntimePaths)})


def test_app_lazy_factories_retain_binding(paths, monkeypatch):
    from app import main
    monkeypatch.setattr(main, 'RUNTIME_PATHS', paths)
    monkeypatch.setattr(main, 'load_all_configs', lambda source: {'devices': {}} if source == paths.runtime_root / 'configs' else pytest.fail(str(source)))
    monkeypatch.setattr(main, '_utm_runtime_manager', None)
    monkeypatch.setattr(main, '_specimen_pose_tracker', None)
    equipment = main._equipment_bridge()
    assert equipment.config.artifact_dir == paths.artifact_root / 'equipment'
    workflow = main._printer_workflow()
    assert workflow.paths is paths
    assert workflow.connection_memory.path == paths.memory_root / 'prusa_connection.json'
    manager = main._printer_bridge_manager()
    assert manager.paths is paths
    assert main._utm_runtime_bridge().config.camera_config.paths is paths
    assert main._specimen_pose_tracker_bridge().config.artifact_dir == paths.run_root


def test_app_equipment_proof_writer_and_reader_share_store(paths, monkeypatch):
    from app import main
    monkeypatch.setattr(main, 'RUNTIME_PATHS', paths)
    package = main._persist_windows_utm_proof_package({'run_id': 'bound-fixture', 'proof_ready': False})
    target = Path(package['package_artifact']['path'])
    assert target.is_relative_to(paths.artifact_root / 'equipment/bound-fixture/utm')
    assert main._latest_windows_utm_proof_package_path() == target
    loaded, info = main._load_windows_utm_proof_package_for_verify(str(target), use_current=False)
    assert loaded['run_id'] == 'bound-fixture', info
    assert json.loads(target.read_text())['proof_ready'] is False
    assert not paths.runtime_root.exists() and not paths.repository_root.exists()


@pytest.mark.asyncio
async def test_app_printer_priority_and_proof_template_stores(paths, monkeypatch):
    from app import main
    from device_bridges.printer_fleet.bridge import PrinterDeviceBridgeManager
    from utils.bambu_material_priority import save_priority
    monkeypatch.setattr(main, 'RUNTIME_PATHS', paths)
    manager = PrinterDeviceBridgeManager.from_devices_config({}, paths=paths)
    monkeypatch.setattr(main, '_printer_bridge_manager', lambda: manager)
    async def emit(**kwargs):
        return None
    monkeypatch.setattr(main.controller, 'emit_workspace_result', emit)
    save_priority({'enabled': True, 'slots': ['0:1']}, path=paths.memory_root / 'bambu_material_priority.json')
    assert (await main.get_printer_material_priority())['priority']['slots'] == ['0:1']
    result = await main.post_printer_bambu_autoejection_proof_template(main.PrinterBambuAutoejectionProofTemplateRequest())
    assert result['ok'], result
    assert list((paths.artifact_root / 'printer/manual/bambu').glob('*.json'))
    assert not paths.runtime_root.exists() and not paths.repository_root.exists()


def test_manipulation_helpers_read_the_selected_memory(paths):
    from agents.manipulation.agent import ManipulationAgent
    from orchestrator.state import OrchestratorState
    from utils.manipulation_profile import save_manipulation_agent_profile
    save_manipulation_agent_profile({'profile_id': 'bound-profile'}, paths=paths)
    agent = ManipulationAgent()
    state = OrchestratorState(run_id='fixture', experiment_id='fixture')
    assert agent._spec(state, paths=paths)['profile_id'] == 'bound-profile'
