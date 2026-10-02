"""Bridge bindings keep source, private stores and explicit operator paths separate."""
from dataclasses import fields, replace
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import os

import yaml

import pytest

from utils.runtime_paths import RuntimePaths
from mcp_tools.tool_registry import ToolRegistry
from mcp_tools.utm_tools import register_utm_tools, run_utm_protocol
from mcp_tools.pinn_tools import register_pinn_tools
from device_bridges.windows_pyautogui.tools import register_equipment_tools
from device_bridges.windows_pyautogui.bridge import WindowsPyAutoGUIBridgeConfig
from device_bridges.camera_vision.specimen_pose_tracker import SpecimenPoseTrackerConfig, get_specimen_pose_tracker_bridge
from device_bridges.camera_vision.utm_runtime_bridge import UTMCameraConfig, UTMCameraProfile, UTMRuntimeConfig, UTMRuntimeProcessManager, get_utm_runtime_manager


@pytest.fixture
def paths(tmp_path):
    return RuntimePaths(**{f.name: tmp_path / f.name for f in fields(RuntimePaths)})


def test_direct_utm_binding_writes_identical_csv_outside_source(paths):
    registry = ToolRegistry()
    register_utm_tools(registry, paths.repository_root, paths=paths)
    payload = {"run_id": "sample", "specimen_id": "one", "mode": "test"}
    actual = registry.call("utm.run_protocol", payload)
    legacy = run_utm_protocol(payload, repo_root=paths.repository_root)
    output = Path(actual["result_file"])
    assert output.parent == paths.artifact_root / "equipment/sample/utm"
    assert output.read_bytes() == Path(legacy["result_file"]).read_bytes()
    assert len(output.read_text().splitlines()) == 97
    assert actual["data_integrity"]["sha256"] == legacy["data_integrity"]["sha256"]
    assert not paths.runtime_root.exists()


@pytest.mark.parametrize("explicit", [None, "custom/place", "/tmp/operator-place"])
def test_pose_equipment_pinn_defaults_and_explicit_paths(paths, explicit):
    overrides = {} if explicit is None else {k: explicit for k in ("script_path", "log_dir", "artifact_dir")}
    pose = SpecimenPoseTrackerConfig.from_devices_config({"specimen_pose_tracker": overrides}, repo_root=paths.repository_root, paths=paths)
    equipment_raw = {} if explicit is None else {k: explicit for k in ("artifact_dir", "connection_memory_path", "utm_profile_memory_path")}
    equipment = WindowsPyAutoGUIBridgeConfig.from_devices_config({"equipment": {"windows_pyautogui": equipment_raw}}, repo_root=paths.repository_root, paths=paths)
    pinn = register_pinn_tools(ToolRegistry(), {"pinn": {} if explicit is None else {"artifact_dir": explicit}}, repo_root=paths.repository_root, paths=paths)
    if explicit is None:
        assert pose.script_path == paths.runtime_root / "scripts/vision/run_specimen_pose_snapshot.sh"
        assert pose.log_dir == paths.artifact_root / "specimen_pose_tracker"
        assert pose.artifact_dir == paths.run_root
        assert equipment.artifact_dir == paths.artifact_root / "equipment"
        assert equipment.connection_memory_path == paths.memory_root / "windows_pyautogui_connection.json"
        assert equipment.utm_profile_memory_path == paths.memory_root / "equipment_utm_profile.json"
        assert pinn.config.artifact_dir == paths.artifact_root / "pinn"
    else:
        expected = Path(explicit) if Path(explicit).is_absolute() else paths.repository_root / explicit
        assert pose.script_path == pose.log_dir == pose.artifact_dir == expected
        assert equipment.artifact_dir == equipment.connection_memory_path == equipment.utm_profile_memory_path == expected
        assert pinn.config.artifact_dir == expected
    assert not paths.runtime_root.exists()


def test_equipment_registration_uses_bound_runtime_service(paths):
    registry = ToolRegistry()
    bridge = register_equipment_tools(registry, {}, repo_root=paths.repository_root, paths=paths)
    assert bridge.config.artifact_dir == paths.artifact_root / "equipment"
    runtime = registry.resource("equipment_runtime")
    assert runtime.root == paths.memory_root / "equipment_runtime"
    assert not paths.repository_root.exists()
    assert not paths.runtime_root.exists()


def test_camera_nested_defaults_persist_only_in_bound_memory(paths):
    config = UTMRuntimeConfig.from_devices_config({}, repo_root=paths.repository_root, paths=paths)
    camera = config.camera_config
    assert config.paths is camera.paths is paths
    assert config.log_dir == paths.artifact_root / "utm_runtime"
    assert camera.memory_path == paths.memory_root / "device_bridge/utm_camera_config.json"
    saved = camera.save_update({"width": 800})
    calibration = paths.memory_root / "device_bridge/calibration/utm_camera_default_cam.yaml"
    assert saved["config"]["active_profile"]["camera_info_url"] == f"file://{calibration}"
    assert calibration.is_file() and camera.memory_path.is_file()
    assert not paths.repository_root.exists() and not paths.runtime_root.exists()


def test_camera_explicit_relative_paths_keep_distinct_legacy_bases(paths, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    camera = UTMCameraConfig.load(repo_root=paths.repository_root, memory_path="local-camera.json", paths=paths)
    assert camera.memory_path == Path("local-camera.json")
    for raw, expected in [("calibration/cam.yaml", paths.repository_root / "calibration/cam.yaml"), ("/tmp/external/cam.yaml", Path("/tmp/external/cam.yaml"))]:
        profile = UTMCameraProfile(calibration_file=raw)
        assert profile.calibration_path(repo_root=paths.repository_root, paths=paths) == expected


def test_utm_fallback_and_singleton_keep_memory_identity(paths):
    first = get_utm_runtime_manager({}, repo_root=paths.repository_root, paths=paths)
    other = replace(paths, memory_root=paths.memory_root.parent / "other-memory")
    second = get_utm_runtime_manager({}, repo_root=other.repository_root, paths=other)
    assert second is not first
    assert get_utm_runtime_manager({}, repo_root=other.repository_root, paths=other) is second
    fallback = UTMRuntimeProcessManager(replace(first.config, camera_config=None))
    assert fallback.camera_config()["memory_path"] == str(paths.memory_root / "device_bridge/utm_camera_config.json")
    assert fallback._repo_root() == paths.repository_root


@pytest.mark.parametrize("factory", [
    lambda p, r: register_utm_tools(ToolRegistry(), r, paths=p),
    lambda p, r: register_pinn_tools(ToolRegistry(), {}, repo_root=r, paths=p),
    lambda p, r: register_equipment_tools(ToolRegistry(), {}, repo_root=r, paths=p),
    lambda p, r: get_specimen_pose_tracker_bridge({}, repo_root=r, paths=p),
    lambda p, r: get_utm_runtime_manager({}, repo_root=r, paths=p),
    lambda p, r: UTMCameraConfig.load(repo_root=r, paths=p),
])
def test_contradictory_roots_fail_before_store_access(paths, factory):
    with pytest.raises(ValueError, match="repo_root"):
        factory(paths, paths.repository_root / "contradiction")
    assert not paths.memory_root.exists() and not paths.artifact_root.exists()


def test_utm_optional_repository_distinguishes_omitted_and_explicit(paths, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert get_utm_runtime_manager().config.camera_config.repo_root == Path(".")
    assert get_utm_runtime_manager(paths=paths).config.camera_config.repo_root == paths.repository_root
    with pytest.raises(ValueError, match="repo_root"):
        get_utm_runtime_manager(repo_root=".", paths=paths)
    paths.repository_root.mkdir()
    monkeypatch.chdir(paths.repository_root)
    camera = get_utm_runtime_manager(repo_root=".", paths=paths).config.camera_config
    assert camera.repo_root.resolve() == paths.repository_root
    assert UTMCameraProfile(calibration_file="custom.yaml").calibration_path(repo_root=camera.repo_root, paths=paths).resolve() == paths.repository_root / "custom.yaml"


def test_shipped_omissions_preserve_flat_values_and_select_split_defaults(paths):
    shipped = yaml.safe_load((Path(__file__).resolve().parents[2] / "configs/devices.yaml").read_text())
    restored = deepcopy(shipped)
    devices = restored["devices"]
    devices["specimen_pose_tracker"].update(script_path="scripts/vision/run_specimen_pose_snapshot.sh", log_dir="artifacts/specimen_pose_tracker", artifact_dir="runs")
    devices["utm_vision_runtime"]["log_dir"] = "artifacts/utm_runtime"
    devices["equipment"]["windows_pyautogui"].update(artifact_dir="artifacts/equipment", connection_memory_path="memory/windows_pyautogui_connection.json", utm_profile_memory_path="memory/equipment_utm_profile.json")
    flat = replace(paths, runtime_root=paths.repository_root, artifact_root=paths.repository_root / "artifacts", memory_root=paths.repository_root / "memory", run_root=paths.repository_root / "runs")
    for parser in (SpecimenPoseTrackerConfig.from_devices_config, WindowsPyAutoGUIBridgeConfig.from_devices_config):
        assert parser(shipped, repo_root=flat.repository_root, paths=flat) == parser(restored, repo_root=flat.repository_root, paths=flat)
    old_utm = UTMRuntimeConfig.from_devices_config(restored, repo_root=flat.repository_root, paths=flat)
    assert UTMRuntimeConfig.from_devices_config(shipped, repo_root=flat.repository_root, paths=flat) == old_utm
    pose = SpecimenPoseTrackerConfig.from_devices_config(shipped, repo_root=paths.repository_root, paths=paths)
    equipment = WindowsPyAutoGUIBridgeConfig.from_devices_config(shipped, repo_root=paths.repository_root, paths=paths)
    utm = UTMRuntimeConfig.from_devices_config(shipped, repo_root=paths.repository_root, paths=paths)
    assert (pose.script_path, pose.log_dir, pose.artifact_dir) == (paths.runtime_root / "scripts/vision/run_specimen_pose_snapshot.sh", paths.artifact_root / "specimen_pose_tracker", paths.run_root)
    assert (equipment.artifact_dir, equipment.connection_memory_path, equipment.utm_profile_memory_path) == (paths.artifact_root / "equipment", paths.memory_root / "windows_pyautogui_connection.json", paths.memory_root / "equipment_utm_profile.json")
    assert utm.log_dir == paths.artifact_root / "utm_runtime"
    assert utm.workspace_root == old_utm.workspace_root == Path("/home/jin/external_repos/UTM")
    assert utm.script_path == old_utm.script_path == Path("/home/jin/external_repos/UTM/scripts/start_utm_vision_stack.sh")
    assert utm.environment == old_utm.environment
    assert replace(pose, script_path=flat.repository_root / "scripts/vision/run_specimen_pose_snapshot.sh", log_dir=flat.artifact_root / "specimen_pose_tracker", artifact_dir=flat.run_root) == SpecimenPoseTrackerConfig.from_devices_config(restored, repo_root=flat.repository_root)
    # Explicit strings remain operator overrides even when spelled like an old
    # shipped default: the resolver must never remap them by value equality.
    explicit_pose = SpecimenPoseTrackerConfig.from_devices_config(restored, repo_root=paths.repository_root, paths=paths)
    explicit_equipment = WindowsPyAutoGUIBridgeConfig.from_devices_config(restored, repo_root=paths.repository_root, paths=paths)
    explicit_utm = UTMRuntimeConfig.from_devices_config(restored, repo_root=paths.repository_root, paths=paths)
    assert (explicit_pose.script_path, explicit_pose.log_dir, explicit_pose.artifact_dir) == (paths.repository_root / "scripts/vision/run_specimen_pose_snapshot.sh", paths.repository_root / "artifacts/specimen_pose_tracker", paths.repository_root / "runs")
    assert (explicit_equipment.artifact_dir, explicit_equipment.connection_memory_path, explicit_equipment.utm_profile_memory_path) == (paths.repository_root / "artifacts/equipment", paths.repository_root / "memory/windows_pyautogui_connection.json", paths.repository_root / "memory/equipment_utm_profile.json")
    assert explicit_utm.log_dir == paths.repository_root / "artifacts/utm_runtime"


def test_bootstrap_passes_identical_binding_to_bridge_graph(paths, monkeypatch):
    from app import bootstrap
    from backends.mock_llm import MockLLMBackend
    guide = paths.system_root / "project/Project_guide.txt"
    guide.parent.mkdir(parents=True)
    guide.write_text("Synthetic software-only binding fixture.")
    config = {"system": {"system": {}}, "models": {}, "devices": {"devices": {}}, "lerobot": {}}
    monkeypatch.setattr(bootstrap, "_load_configs", lambda paths: config)
    monkeypatch.setattr(bootstrap, "_build_backend", lambda *a, **kw: MockLLMBackend())
    seen = []
    for name in ("register_utm_tools", "get_utm_runtime_manager", "get_specimen_pose_tracker_bridge", "register_equipment_tools", "register_pinn_tools"):
        original = getattr(bootstrap, name)
        def capture(*args, _original=original, **kwargs):
            seen.append(kwargs.get("paths"))
            return _original(*args, **kwargs)
        monkeypatch.setattr(bootstrap, name, capture)
    controller = bootstrap.load_runtime(paths=paths)
    assert len(seen) == 5 and all(binding is paths for binding in seen)
    assert controller._deps.paths is paths
    assert config["devices"] == {"devices": {}}


def test_utm_remote_stream_passes_binding_not_protocol_metadata(paths, monkeypatch):
    from utils import vision_monitor_stream
    config = UTMRuntimeConfig.from_devices_config({}, repo_root=paths.repository_root, paths=paths)
    manager = UTMRuntimeProcessManager(config)
    monkeypatch.setattr(manager, "status", lambda: {"status": "running"})
    captured = []
    class Worker:
        process = SimpleNamespace(poll=lambda: None)
        def control(self, payload):
            captured.append(payload)
            return {"source_id": "synthetic"}
        def url(self, suffix):
            return "http://fixture/" + suffix
    def monitor(kind, config, *, paths=None):
        assert kind == "video" and config == {}
        captured.append(paths)
        return Worker()
    monkeypatch.setattr(vision_monitor_stream, "monitor_process", monitor)
    assert manager.frame_stream_url(fps=17, quality=83) == "http://fixture/vision/synthetic/stream.mjpeg"
    assert captured[0] is paths
    payload = captured[1]
    assert payload["operation"] == "vision_register"
    assert set(payload["config"]) == {"key", "command", "cwd", "topic", "target_fps", "jpeg_quality"}
    assert payload["config"]["cwd"] == str(config.workspace_root)
    assert payload["config"]["target_fps"] == 17 and payload["config"]["jpeg_quality"] == 83


def test_bound_pose_launch_preserves_command_env_and_script_parent(paths, monkeypatch):
    from device_bridges.camera_vision import specimen_pose_tracker as pose_module
    raw = {"specimen_pose_tracker": {"d455f_serial": "fixture-serial", "max_runtime_sec": 6.0, "pose_confidence_threshold": 0.81, "rsusb_pythonpath": "/external/rsusb", "rsusb_library_path": "/external/lib", "extra_setup_paths": ["/external/setup.bash"]}}
    bridge = get_specimen_pose_tracker_bridge(raw, repo_root=paths.repository_root, paths=paths)
    bridge.config.script_path.parent.mkdir(parents=True)
    bridge.config.script_path.write_text("# synthetic fixture, never executed\n")
    before = {p.relative_to(paths.runtime_root): p.read_bytes() for p in paths.runtime_root.rglob("*") if p.is_file()}
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok":true,"pose":{"confidence":0.9}}', stderr="")
    monkeypatch.setattr(pose_module.subprocess, "run", run)
    request = {"mode": "live", "specimen_id": "fake"}
    result = bridge.snapshot(request)
    assert result["ok"]
    command, kwargs = calls[0]
    assert command == [str(bridge.config.script_path), json.dumps(request, ensure_ascii=True)]
    assert kwargs["cwd"] == str(paths.runtime_root / "scripts/vision")
    assert kwargs["timeout"] == 6.0
    assert kwargs["env"]["ATR_SPECIMEN_POSE_THRESHOLD"] == "0.81"
    assert kwargs["env"]["PYTHONPATH"] == "/external/rsusb" + os.pathsep + os.environ.get("PYTHONPATH", "")
    assert kwargs["env"]["LD_LIBRARY_PATH"] == "/external/lib" + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")
    assert Path(result["log_path"]).parent == paths.artifact_root / "specimen_pose_tracker"
    assert before == {p.relative_to(paths.runtime_root): p.read_bytes() for p in paths.runtime_root.rglob("*") if p.is_file()}


def test_bound_utm_calibration_launch_keeps_external_workspace_and_argv(paths, monkeypatch):
    from device_bridges.camera_vision import utm_runtime_bridge as utm
    raw = {"utm_vision_runtime": {"workspace_root": "/external/UTM", "script_path": "scripts/custom.sh", "environment": {"UNCHANGED": "value"}}}
    config = UTMRuntimeConfig.from_devices_config(raw, repo_root=paths.repository_root, paths=paths)
    assert config.script_path == Path("/external/UTM/scripts/custom.sh")
    manager = UTMRuntimeProcessManager(config)
    preview = manager.calibration_command()
    calls = []
    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(utm.subprocess, "Popen", popen)
    result = manager.start_calibration()
    assert result["status"] == "running"
    command, kwargs = calls[0]
    assert command == preview["command"]
    assert kwargs["cwd"] == "/external/UTM"
    assert kwargs["env"] == {**os.environ, "PYTHONUNBUFFERED": os.environ.get("PYTHONUNBUFFERED", "1")}
    assert kwargs["start_new_session"] is True
    assert Path(result["log_path"]).parent == paths.artifact_root / "utm_runtime"
    assert Path(result["calibration_file"]) == paths.memory_root / "device_bridge/calibration/utm_camera_default_cam.yaml"
    assert not paths.repository_root.exists() and not paths.runtime_root.exists()


def test_manager_accepts_matching_binding_and_rejects_conflicts_before_effects(paths):
    config = UTMRuntimeConfig.from_devices_config({}, repo_root=paths.repository_root, paths=paths)
    manager = UTMRuntimeProcessManager(config, paths=paths)
    assert manager.config.paths is manager.config.camera_config.paths is paths
    other = replace(paths, memory_root=paths.memory_root.parent / "other-memory")
    with pytest.raises(ValueError, match="paths"):
        UTMRuntimeProcessManager(config, paths=other)
    bare = UTMRuntimeConfig(Path("/external/UTM"), Path("/external/script.sh"), Path("/external/logs"))
    injected = UTMRuntimeProcessManager(bare, paths=paths)
    assert injected.config.paths is paths
    assert (injected.config.workspace_root, injected.config.script_path, injected.config.log_dir) == (bare.workspace_root, bare.script_path, bare.log_dir)
    assert not paths.memory_root.exists() and not paths.artifact_root.exists()
    assert injected.camera_config()["memory_path"] == str(paths.memory_root / "device_bridge/utm_camera_config.json")


def test_legacy_camera_cache_distinguishes_resolved_relative_roots(tmp_path, monkeypatch):
    first_dir, second_dir = tmp_path / "one", tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    raw = {"utm_vision_runtime": {"log_dir": "/tmp/shared-log"}}
    monkeypatch.chdir(first_dir)
    first = get_utm_runtime_manager(raw)
    monkeypatch.chdir(second_dir)
    assert get_utm_runtime_manager(raw) is not first


def test_registered_equipment_writes_simulated_artifacts_and_runtime_records_to_named_roots(paths):
    registry = ToolRegistry()
    register_equipment_tools(registry, {}, paths=paths)
    result = registry.call("equipment.pyautogui.screenshot", {"runtime_mode": "test", "run_id": "fixture"})
    assert result["ok"]
    screenshots = list((paths.artifact_root / "equipment/fixture/screenshots").glob("*.png"))
    assert len(screenshots) == 1 and screenshots[0].read_bytes().startswith(b"\x89PNG")
    runtime = registry.resource("equipment_runtime")
    execution = runtime.begin(sequence_id="one", run_id="fixture", experiment_id="experiment", specimen_id="specimen", profile_id="profile", mode="test", worker={"worker_id": "synthetic"}, execution_ref={"type": "program", "program_id": "fixture"})
    assert (paths.memory_root / "equipment_runtime/executions" / execution["execution_id"] / "state.json").is_file()
    assert registry.call("equipment.runtime.get", {"execution_id": execution["execution_id"]})["execution"] == execution
    assert not paths.repository_root.exists() and not paths.runtime_root.exists()


def test_direct_utm_bound_live_file_remains_cwd_relative(paths, tmp_path, monkeypatch):
    source = run_utm_protocol({"mode": "test"}, paths=paths)
    monkeypatch.chdir(Path(source["result_file"]).parent)
    filename = Path(source["result_file"]).name
    result = run_utm_protocol({"mode": "live", "direct_backend_configured": True, "result_file": filename}, paths=paths)
    assert result["ok"] and result["result_file"] == filename
    assert result["data_integrity"]["sha256"] == source["data_integrity"]["sha256"]
