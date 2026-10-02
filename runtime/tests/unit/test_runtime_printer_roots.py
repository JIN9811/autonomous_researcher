"""Printer factories retain provenance while binding default source and stores."""
from dataclasses import fields, replace
from pathlib import Path
import json
import inspect
from copy import deepcopy
import yaml
import zipfile
import hashlib
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from utils.runtime_paths import RuntimePaths
from device_bridges.printer_fleet.providers.prusa import PrusaBridgeConfig, PrinterAgenticWorkflow, PrusaSlicerRunner
from device_bridges.printer_fleet.bridge import BambuBridgeConfig, BambuStudioSlicerRunner, PrinterDeviceBridgeManager, PrinterProfile
from mcp_tools.printer_tools import register_printer_tools
from mcp_tools.tool_registry import ToolRegistry


@pytest.fixture
def paths(tmp_path):
    return RuntimePaths(**{f.name: tmp_path / f.name for f in fields(RuntimePaths)})


@pytest.mark.parametrize('explicit', [None, 'custom/place', '/tmp/external-place'])
def test_printer_parser_defaults_and_explicit_bases(paths, explicit):
    raw = {} if explicit is None else {k: explicit for k in ('executable_path', 'output_dir')}
    printer = {'slicer': raw, 'bambu': {'slicer': raw}}
    if explicit is not None:
        printer.update(connection_memory_path=explicit, autoejection_memory_path=explicit,
                       profiles={'custom': {'connection_memory_path': explicit}})
    prusa = PrusaBridgeConfig.from_devices_config({'printer': printer}, paths=paths)
    fleet = BambuBridgeConfig.from_devices_config({'printer': printer}, paths=paths)
    if explicit is None:
        assert prusa.connection_memory_path == paths.memory_root / 'prusa_connection.json'
        assert fleet.connection_memory_path == paths.memory_root / 'printer_fleet.json'
        assert fleet.autoejection_memory_path == paths.memory_root / 'bambu_autoejection.json'
        assert fleet.profiles['prusa_mk4s_lab_01'].connection_memory_path == paths.memory_root / 'prusa_connection.json'
        assert fleet.default_profile.connection_memory_path == paths.memory_root / 'bambu_connection.json'
        assert PrusaSlicerRunner(prusa.slicer, paths=paths)._executable() == str(paths.runtime_root / 'install/prusaslicer/prusa-slicer-docker')
        assert Path(prusa.slicer.output_dir) == paths.artifact_root / 'gcode'
        resolved = fleet.slicer.resolved_payload(paths=paths)
        assert resolved['checked'][0]['path'] == str(paths.runtime_root / 'install/bambustudio/bambu-studio-wrapper')
        assert resolved['output_dir'] == str(paths.artifact_root / 'bambu_sliced')
    else:
        expected = Path(explicit) if Path(explicit).is_absolute() else paths.repository_root / explicit
        assert prusa.connection_memory_path == fleet.connection_memory_path == fleet.autoejection_memory_path == expected
        assert fleet.default_profile.connection_memory_path == expected
        assert PrusaSlicerRunner(prusa.slicer, paths=paths)._executable() == str(expected)
        assert fleet.slicer.resolved_payload(paths=paths)['output_dir'] == str(expected)
    assert prusa.paths is fleet.paths is paths
    assert not paths.repository_root.exists() and not paths.runtime_root.exists()


def test_printer_registration_binds_both_owners_and_independent_stores(paths):
    for binding in (paths, replace(paths, memory_root=paths.memory_root / 'second')):
        registry = ToolRegistry()
        register_printer_tools(registry, {}, paths=binding)
        owners = inspect.getclosurevars(registry._tools['printer.prepare']).nonlocals
        workflow = owners['prusa_workflow']
        manager = owners['bridge_manager']
        assert workflow.paths is workflow.slicer.paths is manager.paths is binding
        assert workflow.connection_memory.path == binding.memory_root / 'prusa_connection.json'
        assert manager.bed_clear_memory().path == binding.memory_root / 'bambu_bed_clear_evidence.json'
        manifest = manager._write_bambu_workspace_manifest(run_id='one', payload={'value': 1})
        assert Path(manifest) == binding.run_root / 'one/workspace/printer/bambu_autoejection_manifest.json'
        assert json.loads(Path(manifest).read_text())['value'] == 1


@pytest.mark.parametrize('factory', [PrusaBridgeConfig.from_devices_config, BambuBridgeConfig.from_devices_config, PrinterDeviceBridgeManager.from_devices_config])
def test_printer_rejects_conflicting_repository_before_side_effects(paths, factory):
    with pytest.raises(ValueError, match='repo_root'):
        factory({}, repo_root=paths.runtime_root, paths=paths)
    assert not paths.memory_root.exists()


def test_printer_direct_profile_default_and_legacy(paths):
    profile = PrinterProfile.from_dict('custom', {}, repo_root=paths.repository_root, paths=paths)
    assert profile.connection_memory_path == paths.memory_root / 'bambu_connection.json'
    legacy = PrusaBridgeConfig.from_devices_config({}, repo_root=paths.repository_root)
    workflow = PrinterAgenticWorkflow(legacy, repo_root=paths.repository_root)
    assert workflow.slicer._executable() == str(paths.repository_root / 'install/prusaslicer/prusa-slicer-docker')


def test_bambu_generated_outputs_and_memory_defaults_are_bound(paths):
    manager = PrinterDeviceBridgeManager.from_devices_config({}, paths=paths)
    manager.save_autoejection_config({'enabled': True, 'provider': 'bambu_gcode_patch'})
    source = paths.repository_root / 'input.gcode'
    source.parent.mkdir()
    source.write_text('G90\nG1 X20 Y30 Z0.2 E0.02\nG1 X50 Y70 Z12 E1.5\nM104 S0\nM140 S0\nM84\n')
    for result in (
        manager.patch_bambu_autoejection_artifact(source_path=source, specimen_id='one'),
        manager.build_standalone_bambu_autoejection_artifact(),
        manager.build_bambu_autoejection_sweep_test_artifact(),
        manager.patch_bambu_ejection_only_artifact(source_path=source, specimen_id='only'),
    ):
        assert result['ok'], result
        artifact = Path(result['patched_artifact_path'])
        assert artifact.is_relative_to(paths.artifact_root / 'bambu_autoejection')
        assert artifact.is_file()
    status = manager.autoejection_status()['runtime_paths']
    assert status['artifact_dir'] == str(paths.artifact_root / 'bambu_autoejection')
    assert status['validation_summary_path'] == str(paths.run_root / 'manual_bambu_validation')
    assert not (paths.repository_root / 'artifacts').exists()
    assert not paths.runtime_root.exists()


def test_printer_shipped_omissions_flat_equivalence_and_explicit_retention(paths):
    shipped = yaml.safe_load((Path(__file__).resolve().parents[2] / 'configs/devices.yaml').read_text())
    old = deepcopy(shipped)
    printer = old['devices']['printer']
    printer['profiles']['bambulab_x2d_lab_01']['connection_memory_path'] = 'memory/bambu_connection.json'
    printer['slicer'].update(executable_path='install/prusaslicer/prusa-slicer-docker', output_dir='artifacts/gcode')
    printer['bambu']['slicer'].update(executable_path='install/bambustudio/bambu-studio-wrapper', output_dir='artifacts/bambu_sliced')
    flat = replace(paths, runtime_root=paths.repository_root, memory_root=paths.repository_root / 'memory', artifact_root=paths.repository_root / 'artifacts')
    for parser in (PrusaBridgeConfig.from_devices_config, BambuBridgeConfig.from_devices_config):
        before = parser(old, paths=flat)
        after = parser(shipped, paths=flat)
        assert before.connection_memory_path == after.connection_memory_path == paths.repository_root / 'memory/printer_fleet.json'
        assert before.slicer.enabled == after.slicer.enabled
        for key in ('executable_path', 'output_dir'):
            old_path = Path(getattr(before.slicer, key))
            if not old_path.is_absolute():
                old_path = flat.repository_root / old_path
            assert Path(getattr(after.slicer, key)) == old_path
        before.slicer = replace(before.slicer, executable_path=str(flat.repository_root / before.slicer.executable_path),
                                output_dir=str(flat.repository_root / before.slicer.output_dir))
        assert before == after
        split = parser(shipped, paths=paths)
        assert split.connection_memory_path == paths.repository_root / 'memory/printer_fleet.json'
        assert Path(split.slicer.executable_path).is_relative_to(paths.runtime_root)
        assert Path(split.slicer.output_dir).is_relative_to(paths.artifact_root)
        explicit = parser(old, paths=paths)
        assert not Path(explicit.slicer.executable_path).is_absolute()
        if isinstance(explicit, PrusaBridgeConfig):
            assert PrusaSlicerRunner(explicit.slicer)._executable() == str(paths.repository_root / 'install/prusaslicer/prusa-slicer-docker')
        else:
            assert explicit.slicer.resolved_payload()['output_dir'] == str(paths.repository_root / 'artifacts/bambu_sliced')
    fleet = BambuBridgeConfig.from_devices_config(shipped, paths=paths)
    assert fleet.profiles['bambulab_x2d_lab_01'].connection_memory_path == paths.memory_root / 'bambu_connection.json'
    assert fleet.profiles['prusa_mk4s_lab_01'].connection_memory_path == paths.repository_root / 'memory/prusa_connection.json'


def test_bootstrap_supplies_printer_binding(paths, monkeypatch):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    guide = paths.system_root / 'project/Project_guide.txt'
    guide.parent.mkdir(parents=True)
    guide.write_text('Synthetic software-only fixture.')
    monkeypatch.setattr(bootstrap, '_load_configs', lambda paths: {'system': {'system': {}}, 'models': {}, 'devices': {'devices': {}}, 'lerobot': {}})
    monkeypatch.setattr(bootstrap, '_build_backend', lambda *a, **kw: MockLLMBackend())
    actual = bootstrap.register_printer_tools
    seen = []
    def capture(*args, **kwargs):
        seen.append(kwargs.get('paths'))
        return actual(*args, **kwargs)
    monkeypatch.setattr(bootstrap, 'register_printer_tools', capture)
    bootstrap.load_runtime(paths=paths)
    assert seen == [paths]


def test_bambu_http_export_and_material_url_resolver_share_bound_store(paths):
    from utils.bambu_material_priority import material_artifact_path
    manager = PrinterDeviceBridgeManager.from_devices_config({}, paths=paths)
    source = paths.repository_root / 'input.gcode.3mf'
    source.parent.mkdir()
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('Metadata/plate_1.gcode', 'G90\nG1 X20 Y30 E1\n')
    result = manager._prepare_bambu_http_artifact_route(artifact_path='input.gcode.3mf', connection={},
        payload={'public_base_url': 'http://192.0.2.1:8000'}, plate_id=1,
        expected_artifact_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    assert result['ok'], result
    exported = Path(result['artifact']['export_path'])
    assert exported.is_relative_to(paths.artifact_root / 'bambu_http_exports')
    assert exported.read_bytes() == source.read_bytes()
    assert result['artifact']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert material_artifact_path(result['artifact_url'], paths.repository_root, paths=paths) == exported
    assert material_artifact_path('input.gcode.3mf', paths.repository_root, paths=paths) == source
    assert material_artifact_path('/external/operator.3mf', paths.repository_root, paths=paths) == Path('/external/operator.3mf')
    assert material_artifact_path('http://fixture/printer-artifacts/bambu/%2e%2e/private', paths.repository_root, paths=paths) is None


def test_bound_slicer_config_carries_binding_and_rejects_cross_binding(paths):
    prusa = PrusaBridgeConfig.from_devices_config({}, paths=paths)
    fleet = BambuBridgeConfig.from_devices_config({}, paths=paths)
    for runner, config in ((PrusaSlicerRunner, prusa.slicer), (BambuStudioSlicerRunner, fleet.slicer)):
        assert runner(config).repo_root == paths.repository_root
        with pytest.raises(ValueError, match='paths'):
            runner(config, paths=replace(paths, memory_root=paths.memory_root / 'other'))


def test_bound_profile_memory_controls_calibration_and_postprocessing(paths):
    paths.memory_root.mkdir()
    (paths.memory_root / 'prusa_print_profile.json').write_text(json.dumps({
            'bed_leveling_enabled': False, 'flow_calibration_enabled': False, 'early_layer_speed_mm_s': 27}))
    manager = PrinterDeviceBridgeManager.from_devices_config({}, paths=paths)
    assert manager._bambu_project_file_calibration_flags({}) == {'bed_leveling': False, 'flow_cali': False}
    runner = BambuStudioSlicerRunner(manager.config.slicer)
    assert runner._print_start_settings()['early_layer_speed_mm_s'] == 27


def test_prusa_generated_ejection_keeps_identical_gcode_and_virtual_gates(paths):
    from device_bridges.printer_fleet.providers.prusa import PrusaLinkClient
    raw = {'printer': {'ejection': {'enabled': True, 'method': 'bed_sweep', 'max_feedrate_mm_min': 25000,
        'max_bed_temp_c': 40}}}
    bodies = []
    for binding in (paths, replace(paths, artifact_root=paths.repository_root / 'artifacts')):
        config = PrusaBridgeConfig.from_devices_config(raw, paths=binding)
        workflow = PrinterAgenticWorkflow(config)
        client = PrusaLinkClient(config=config, connection={}, transport='virtual')
        result = workflow._handle_ejection({}, client=client, storage='usb', allow_physical=False)
        assert result['status'] == 'virtual_ack' and result['attempts'] == 1, result
        ejection = binding.artifact_root / 'gcode/ejection.gcode'
        assert ejection.is_file()
        standalone = workflow.run_autoejection_test({'runtime_mode': 'test', 'start_immediately': False})
        assert standalone['ok'] and standalone['prusalink']['transport'] == 'virtual'
        assert Path(standalone['ejection_gcode_path']) == binding.artifact_root / 'gcode/autoeject-test-center.gcode'
        bodies.append((ejection.read_bytes(), Path(standalone['ejection_gcode_path']).read_bytes(), standalone['resolved']))
    assert bodies[0] == bodies[1]


def test_fake_slicer_launches_keep_nonpath_arguments_and_external_precedence(paths, monkeypatch):
    from device_bridges.printer_fleet import bridge
    from device_bridges.printer_fleet.providers import prusa
    for root, relative in ((paths.runtime_root, 'install/prusaslicer/prusa-slicer-docker'),
                           (paths.runtime_root, 'install/bambustudio/bambu-studio-wrapper')):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('unused fake executable')
        target.chmod(0o755)
    source = paths.repository_root / 'sample.stl'
    source.parent.mkdir()
    source.write_text('solid test\nendsolid test\n')
    captured = []
    def fake_run(argv, **kwargs):
        captured.append((argv, kwargs))
        if '--output' in argv:
            Path(argv[argv.index('--output') + 1]).write_text('G90\nM84\n')
        else:
            output = Path(argv[argv.index('--outputdir') + 1]) / argv[argv.index('--export-3mf') + 1]
            with zipfile.ZipFile(output, 'w') as archive:
                archive.writestr('Metadata/plate_1.gcode', 'G90\nG1 X20 Y30 Z0.2 E1\n')
        return SimpleNamespace(returncode=0, stdout='synthetic', stderr='')
    monkeypatch.setattr(prusa.subprocess, 'run', fake_run)
    monkeypatch.setattr(bridge.shutil, 'which', lambda name: None)
    cfg = PrusaBridgeConfig.from_devices_config({'printer': {'slicer': {'enabled': True, 'timeout_sec': 17,
        'profile_map': {'operator': 'custom/profile.ini'},
        'command_template': ['{executable}', '--export-gcode', '--load', '{profile_path}', '--output', '{output_path}', '{stl_path}']}}}, paths=paths)
    runner = PrusaSlicerRunner(cfg.slicer)
    result = runner.slice(source, specimen_id='one', simulate=False, slicer_profile_hint='operator')
    assert result['ok']
    argv, kwargs = captured.pop()
    assert argv == [str(paths.runtime_root / 'install/prusaslicer/prusa-slicer-docker'), '--export-gcode',
        '--load', str(paths.repository_root / 'custom/profile.ini'), '--output', str(paths.artifact_root / 'gcode/one.gcode'), str(source),
        '--layer-height=0.2', '--first-layer-height=0.2', '--bed-temperature=60', '--first-layer-bed-temperature=60',
        '--first-layer-speed=10', '--skirts=0', '--brim-width=0', '--raft-layers=0']
    assert kwargs == {'stdout': prusa.subprocess.PIPE, 'stderr': prusa.subprocess.PIPE, 'text': True, 'timeout': 17, 'check': False}
    monkeypatch.setenv('PRUSA_SLICER_EXECUTABLE', '/external/prusa')
    assert runner._executable() == '/external/prusa'
    config = BambuBridgeConfig.from_devices_config({'printer': {'bambu': {'slicer': {'enabled': True, 'timeout_sec': 19, 'auto_no_skirt_profile': False}}}}, paths=paths)
    result = BambuStudioSlicerRunner(config.slicer).slice('sample.stl', specimen_id='two', auto_orient=False)
    assert result['ok'], result
    argv, kwargs = captured.pop()
    assert argv == [str(paths.runtime_root / 'install/bambustudio/bambu-studio-wrapper'), '--slice', '0', '--arrange', '1', '--ensure-on-bed',
        '--outputdir', str(paths.artifact_root / 'bambu_sliced/two'), '--export-3mf', 'two.gcode.3mf', '--debug', '2', str(source)]
    assert kwargs == {'check': False, 'capture_output': True, 'text': True, 'timeout': 19.0}
    external = paths.workspace_root / 'external-bambu'
    external.parent.mkdir()
    external.write_text('unused')
    external.chmod(0o755)
    monkeypatch.setenv('BAMBU_STUDIO_EXECUTABLE', str(external))
    resolved = config.slicer.resolved_payload()
    assert resolved['source'] == 'env' and resolved['resolved_executable_path'] == str(external)


def test_bound_material_priority_and_saved_material_are_used_without_probe(paths):
    paths.memory_root.mkdir()
    (paths.memory_root / 'bambu_material_priority.json').write_text(json.dumps({'enabled': True, 'slots': ['0:2']}))
    (paths.memory_root / 'prusa_print_profile.json').write_text(json.dumps({'material': 'PETG'}))
    manager = PrinterDeviceBridgeManager.from_devices_config({}, paths=paths)
    report = {'received_at': datetime.now(timezone.utc).isoformat(), 'materials': {'tray_exist_bits': 4, 'slots': [
        {'ams_id': '0', 'tray_id': '2', 'tray_type': 'PETG', 'remain_percent': 73}]}}
    result = manager.resolve_material_selection({}, normalized_report=report)
    assert result['ok'] and result['enabled'] and result['slot_id'] == '0:2', result
    assert result['ams_mapping'] == [2] and result['use_ams'] is True
    assert not paths.repository_root.exists() and not paths.runtime_root.exists()
