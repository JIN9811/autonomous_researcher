"""Explicit low-level, non-actuating fixtures for real orchestration owners."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest


@pytest.fixture
def numeric_archive_guard(tmp_path, monkeypatch):
    """Isolate the existing numeric/archive regressions before owner execution."""
    from scripts.orchestrator_verification_guard import VerificationGuard
    with VerificationGuard() as guard:
        guard.allowed_tools.update({"cae.run_static_analysis", "experiment.benchmark", "experiment.evaluate", "source.query"})
        import agents.analysis_agent as analysis
        original_resolve = analysis.resolve_path
        monkeypatch.setattr(analysis, "resolve_path", lambda p: tmp_path / str(p) if str(p).startswith(("runs", "memory", "artifacts", "output")) else original_resolve(p))
        from agents.analysis_runtime import AnalysisRuntimeService
        monkeypatch.setattr(AnalysisRuntimeService, "resume", lambda *a, **k: False)
        yield guard
        assert guard.physical_call_count == 0 and guard.denied == [], guard.denied


async def confirm_original_teleop_api(controller, monkeypatch, guard, pending):
    """Actual popup handlers and registry; only transport state is simulated."""
    import app.bootstrap as bootstrap
    monkeypatch.setattr(bootstrap, "load_runtime", lambda: controller)
    from app import main
    from fastapi import HTTPException
    import pytest
    monkeypatch.setattr(main, "controller", controller)
    session = {"ok": True, "workflow": "teleoperate", "status": "TELEOP_ACTIVE",
        "session_id": "controlled-teleop", "port_released": False, "camera_returned_to_vision": False}
    def status(payload):
        assert payload["session_id"] == session["session_id"]
        guard.simulated_boundary_requests.append({"tool": "lerobot.teleoperate.status", "payload": deepcopy(payload)})
        return deepcopy(session)
    async def transport(name, payload, **kwargs):
        assert name in {"lerobot.teleoperate.start", "lerobot.teleoperate.stop"}
        guard.simulated_boundary_requests.append({"tool": name, "payload": deepcopy(payload)})
        if name.endswith("start"):
            assert payload["handoff_token"] == pending["handoff_token"] and payload["handoff_run_id"] == pending["run_id"]
        else:
            assert payload["session_id"] == session["session_id"]
            session.update(status="STOPPED", port_released=True, camera_returned_to_vision=True,
                teleop_stopped_at=datetime.now(timezone.utc).isoformat())
        return deepcopy(session)
    monkeypatch.setattr(main, "_call_lerobot_backend_tool", transport)
    monkeypatch.setattr(main, "_lerobot_bridge", lambda: SimpleNamespace(teleoperate_status=status))
    await main.post_lerobot_teleoperate_start(main.LeRobotAPIRequest(mode="live", runtime_mode="live",
        handoff_token=pending["handoff_token"], handoff_run_id=pending["run_id"]))
    request = main.OperatorTeleopHandoffConfirmRequest(handoff_token=pending["handoff_token"],
        teleop_session_id=session["session_id"], confirmed_by="controlled_operator")
    with pytest.raises(HTTPException, match="TELEOP_SESSION_ACTIVE"):
        await main.confirm_operator_teleop_handoff(pending["run_id"], request)
    await main.post_lerobot_teleoperate_stop(main.LeRobotAPIRequest(mode="live", runtime_mode="live",
        session_id=session["session_id"]))
    result = await main.confirm_operator_teleop_handoff(pending["run_id"], request)
    assert result["status"] == "operator_confirmed"


def printer_io(controller, monkeypatch, tmp_path, guard):
    """Keep real printer preparation/slicing/patching; simulate only transport/process."""
    import subprocess
    import zipfile
    import time
    import app.controller as controller_module
    from device_bridges.bambu_bridge import (PrinterDeviceBridgeManager, BambuConnectionMemory,
        BambuLiveProbe, BambuMqttReportClient, BambuFtpsClient)
    from mcp_tools.printer_tools import register_printer_tools
    root = tmp_path / "printer"
    root.mkdir()
    monkeypatch.setenv("ATR_BAMBU_PUBLIC_BASE_URL", "http://192.0.2.80:7860")
    executable = root / "controlled-slicer"
    executable.write_text("Not executable: the scoped process fixture must intercept this file.")
    executable.chmod(0o700)
    config = {"devices": {"printer": {"mode": "test", "default_profile_id": "bambulab_x2d_lab_01",
        "allow_automatic_fallback": False, "connection_memory_path": str(root / "fleet.json"),
        "profiles": {"bambulab_x2d_lab_01": {"provider": "bambulab_x2d", "enabled": True,
            "connection_memory_path": str(root / "connection.json")}},
        "bambu": {"mqtt": {"timeout_sec": .1}, "video": {"enabled": False},
            "slicer": {"enabled": True, "executable_path": str(executable), "output_dir": str(root / "sliced")}}}}}
    manager = PrinterDeviceBridgeManager.from_devices_config(config, repo_root=root)
    BambuConnectionMemory(manager.config.default_profile.connection_memory_path).save_from_payload({
        "host": "192.0.2.42", "serial": "CONTROLLED-PRINTER", "lan_mode_confirmed": True,
        "developer_mode_confirmed": True,
        "auth": {"mode": "lan_access_code", "username": "fixture", "access_code": "synthetic-not-a-key"}})
    manager.save_autoejection_config({"enabled": True, "provider": "bambu_gcode_patch",
        "push_direction": "center", "object_size_mm": [30, 30, 30]})
    calls, published = [], []
    def record(name, payload):
        event = {"tool": name, "payload": deepcopy(payload)}
        # No credentials are needed for transport evidence.
        event["payload"].pop("access_code", None)
        calls.append(event)
        guard.simulated_boundary_requests.append(event)
    def probe(self, host, port, timeout_sec):
        record("printer.tls_probe", {"host": host, "port": port})
        return {"ok": True, "port": port}
    def snapshot(self, **kwargs):
        record("printer.mqtt_snapshot", {"force_refresh": kwargs.get("force_refresh")})
        return {"ok": True, "received_at": time.time(), "report": {"print": {
            "gcode_state": "FINISH" if published else "IDLE", "mc_percent": 100 if published else 0,
            "bed_temper": 29, "ipcam": {"liveview_preview": True},
            "subtask_name": published[-1] if published else ""}}}
    def publish(self, **kwargs):
        record("printer.publish_project_file", kwargs)
        command = kwargs.get("payload", {}).get("print", {})
        published.append(str(command.get("subtask_name") or command.get("param") or ""))
        return {"ok": True, "status": "published", "published": True, "will_publish": True,
            "sequence_id": f"controlled-publish-{len(published)}", "topic": kwargs.get("topic")}
    def storage(self, **kwargs):
        record("printer.ftps_probe", kwargs)
        return {"ok": True, "selected_remote_dir": "cache", "storage": "ftps", "readable": True}
    def upload(self, **kwargs):
        record("printer.ftps_upload", kwargs)
        return {"ok": True, "status": "uploaded", "remote_path": kwargs["remote_path"],
            "sha256": hashlib.sha256(Path(kwargs["local_path"]).read_bytes()).hexdigest()}
    monkeypatch.setattr(BambuLiveProbe, "probe_tls_port", probe)
    monkeypatch.setattr(BambuMqttReportClient, "read_snapshot", snapshot)
    monkeypatch.setattr(BambuMqttReportClient, "publish_project_file_command", publish)
    monkeypatch.setattr(BambuFtpsClient, "probe_storage", storage)
    monkeypatch.setattr(BambuFtpsClient, "probe_upload_paths", storage)
    monkeypatch.setattr(BambuFtpsClient, "upload_file", upload)
    original_run = subprocess.run
    def slice_process(command, **kwargs):
        if not isinstance(command, list) or command[0] != str(executable):
            return original_run(command, **kwargs)
        assert "--slice" in command and "--export-3mf" in command
        record("printer.slicer_process", {"command": command})
        output = Path(command[command.index("--outputdir") + 1])
        output.mkdir(parents=True, exist_ok=True)
        target = output / command[command.index("--export-3mf") + 1]
        cx, cy = 125.0, 125.0
        if "--load-assemble-list" in command:
            import trimesh
            assembly = json.loads(Path(command[command.index("--load-assemble-list") + 1]).read_text())
            obj = assembly["plates"][0]["objects"][0]
            mesh = trimesh.load_mesh(obj["path"])
            center = mesh.bounds.mean(axis=0)
            cx, cy = center[0] + obj["pos_x"][0], center[1] + obj["pos_y"][0]
        gcode = "\n".join(["G90", "M82", "G92 E0", f"G1 X{cx-15} Y{cy-15} Z0.2 E0.1 F1200",
            f"G1 X{cx+15} Y{cy-15} Z0.2 E0.2 F1200", f"G1 X{cx+15} Y{cy+15} Z15 E0.3 F1200",
            f"G1 X{cx-15} Y{cy+15} Z30 E0.4 F1200", "M84", "M73 P100 R0"])
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("Metadata/plate_1.gcode", gcode)
            archive.writestr("3D/3dmodel.model", "<model />")
        return subprocess.CompletedProcess(command, 0, "controlled slicer output", "")
    monkeypatch.setattr(subprocess, "run", slice_process)
    monkeypatch.setattr(controller_module, "load_all_configs", lambda *a, **k: deepcopy(config))
    register_printer_tools(controller._deps.agent_context.tools, config, repo_root=root)
    return {"calls": calls, "root": root, "published": published}


def equipment_io(controller, monkeypatch, tmp_path, guard):
    from agents.equipment_agent import LabEquipmentAgent
    from mcp_tools.equipment_tools import register_equipment_tools
    from utils.equipment_utm_skills import stage_utm_skill_packages, bind_deployed_utm_skills, UTM_SKILL_BINDINGS
    from utils.equipment_skill_runtime import EquipmentSkillRegistry, canonical_sha256
    tools = controller._deps.agent_context.tools
    root = tmp_path / "equipment"
    root.mkdir(parents=True)
    (root / "profile.json").write_text(json.dumps({"robot_entry_clearance_mm": 150.0}))
    flow = root / "flows.json"
    skills = root / "skills"
    monkeypatch.setattr(LabEquipmentAgent, "_RUNTIME_ROOT", root / "runtime")
    monkeypatch.setattr(LabEquipmentAgent, "_SKILL_FLOW_PATH", flow)
    monkeypatch.setattr(LabEquipmentAgent, "_WORKSPACE_SETTINGS_PATH", root / "settings.json")
    register_equipment_tools(tools, {"devices": {"equipment": {"mode": "simulator",
        "windows_pyautogui": {"connection_memory_path": str(root / "connection.json"),
            "artifact_dir": str(root / "artifacts"), "utm_profile_memory_path": str(root / "profile.json")}}}}, repo_root=root)
    packages = stage_utm_skill_packages(registry_root=skills,
        reference_root=Path(__file__).resolve().parents[2] / "references/trapeziumx_v_equipment_agent")
    registry = EquipmentSkillRegistry(skills)
    guard.allowed_tools.update({"equipment.pyautogui.register_program", "equipment.pyautogui.run",
        "vision.equipment_cross_check", "equipment.pyautogui.screenshot"})
    screenshot_callback = tools._tools["equipment.pyautogui.screenshot"]
    def screenshot(payload):
        assert payload["runtime_mode"] == "test"
        guard.simulated_boundary_requests.append({"tool": "equipment.pyautogui.screenshot", "payload": deepcopy(payload)})
        return screenshot_callback(payload)
    tools.register("equipment.pyautogui.screenshot", screenshot)
    programs = {}
    blocks = {value[0]: key for key, value in UTM_SKILL_BINDINGS.items()}
    for package in packages:
        manifest = package["manifest"]
        for program in package["programs"]:
            assert tools.call("equipment.pyautogui.register_program", {"runtime_mode": "test", "program": program})["ok"]
            programs[program["program_id"]] = (manifest["skill_id"], manifest["version"])
        registry.mark_deployed(manifest["skill_id"], manifest["version"], bridge_id="simulator",
            deployment_sha256=canonical_sha256(package["programs"]))
    bind_deployed_utm_skills(registry_root=skills, flow_path=flow)
    original = tools._tools["equipment.pyautogui.run"]
    calls, saved = [], {}
    def worker(payload):
        assert programs[payload["program_id"]] == (payload["equipment_skill_id"], payload["equipment_skill_version"])
        assert payload["run_id"] == controller._state.run_id
        assert payload["experiment_id"] == controller._state.experiment_id
        assert payload["runtime_mode"] == "test"
        calls.append(deepcopy(payload))
        guard.simulated_boundary_requests.append({"tool": "equipment.pyautogui.run", "payload": deepcopy(payload)})
        result = original(payload)
        assert result["ok"], result
        block = blocks[payload["equipment_skill_id"]]
        result.update(fixture_provenance="controlled_worker_response", cross_checks={
            "screen_started": True, "physical_motion_started": False, "save_completed": block == "save_raw_data",
            "data_file_created": block in {"save_raw_data", "validate_raw_data"},
            "data_parse_probe_ok": block in {"save_raw_data", "validate_raw_data"},
            "save_export_responsibility_ok": True})
        if block == "save_raw_data":
            context = payload["export_context"]
            saved["context"] = deepcopy(context)
            assert all(str(context[key]).replace("-", "").isalnum() for key in ("session_id", "specimen_id"))
            filename = (f"{context['mode']}_{context['session_id']}_{context['specimen_id']}_"
                f"loop-{context['loop_index']:04d}_rep-{context['repeat_index']:04d}.csv")
            csv = root / filename
            values = [0, 80, 180, 310, 430, 520, 500, 455, 390, 340, 300]
            data = "time_s,force_N,displacement_mm\n" + "".join(f"{i / 2},{force},{i / 2}\n" for i, force in enumerate(values))
            csv.write_text(data)
            saved.update(path=str(csv), sha=hashlib.sha256(csv.read_bytes()).hexdigest(), windows="C:/exports/" + filename)
        if block in {"save_raw_data", "validate_raw_data"}:
            artifact = {"kind": "utm_csv", "artifact_id": "controlled-export", "windows_path": saved["windows"],
                "local_path": saved["path"], "linux_path": saved["path"], "run_id": payload["run_id"],
                "specimen_id": saved["context"]["specimen_id"], "sha256": saved["sha"], "pulled_to_linux": True,
                "local_parse_ok": True, "row_count_probe": 11,
                "columns_probe": ["time_s", "force_N", "displacement_mm"], "stable_for_sec": 2}
            result.update(run_id=payload["run_id"], specimen_id=saved["context"]["specimen_id"],
                result_file=saved["path"], utm_csv_path=saved["path"], output_artifacts=[artifact],
                data_acquisition={**deepcopy(artifact), "status": "pulled_to_linux"})
        if block == "restore_robot_clearance":
            from PIL import Image
            screenshot = root / "clearance.png"
            Image.new("RGB", (8, 8)).save(screenshot)
            windows = "C:/exports/clearance.png"
            result["step_trace"] = [{"step": f"{i}_WAIT_UNTIL_IMAGE", "status": "ok", "detail": detail}
                for i, detail in enumerate(("target_inter_jig_distance_150_mm via image", "entry_height_150_mm via image", "next_test_ready_loaded via image"))]
            result["step_trace"].append({"step": "SCREENSHOT_ROBOT_CLEARANCE_RESTORED", "status": "ok", "detail": windows})
            result["output_artifacts"] = [{"kind": "screen_png", "windows_path": windows,
                "pulled_to_linux": True, "local_path": str(screenshot)}]
        return result
    tools.register("equipment.pyautogui.run", worker)
    def cross_check(payload):
        guard.simulated_boundary_requests.append({"tool": "vision.equipment_cross_check", "payload": deepcopy(payload)})
        assert len(payload["checks"]) == 1
        result = {**payload["checks"][0], "ok": True, "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "virtualized": True, "observer_mode": "controlled_worker", "source": "controlled_observation"}
        return {"ok": True, "results": [result], "virtualized": True, "observer_mode": "controlled_worker"}
    tools.register("vision.equipment_cross_check", cross_check)
    return {"skills": str(skills), "calls": calls, "saved": saved, "programs": programs}
