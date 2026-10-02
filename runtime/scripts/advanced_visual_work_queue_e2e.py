from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.equipment_skill_runtime import EquipmentSkillRegistry


POINTER_ACTIONS = {"move_to", "click", "drag_to"}
EXPECTED_RESULT: dict[str, object] = {
    "specimen_id": "specimen-beta",
    "method": "Compression",
    "evidence_enabled": True,
    "load_limit": 12.5,
}


def assert_image_only_programs(programs: list[dict[str, object]]) -> None:
    sequence = [
        dict(action)
        for program in programs
        for action in list(program.get("sequence") or [])
        if isinstance(action, dict)
    ]
    for index, action in enumerate(sequence, start=1):
        if action.get("action") not in POINTER_ACTIONS:
            continue
        if "x" in action or "y" in action or action.get("coordinate_fallback") is True:
            raise AssertionError(f"executable coordinate at action {index}")
        if not action.get("image_candidates"):
            raise AssertionError(f"missing image candidates at action {index}")
    drag_actions = [item for item in sequence if item.get("action") == "drag_to"]
    if len(drag_actions) != 1:
        raise AssertionError("exactly one visual drag is required")


def _normalized_csv_result(row: dict[str, str]) -> dict[str, object]:
    evidence = str(row.get("evidence_enabled") or "").strip().lower()
    if evidence not in {"true", "false"}:
        raise AssertionError("CSV output contains invalid evidence_enabled")
    try:
        load_limit = float(str(row.get("load_limit") or "").strip())
    except ValueError as exc:
        raise AssertionError("CSV output contains invalid load_limit") from exc
    return {
        "specimen_id": str(row.get("specimen_id") or ""),
        "method": str(row.get("method") or ""),
        "evidence_enabled": evidence == "true",
        "load_limit": load_limit,
    }


def validate_exported_artifacts(
    json_path: Path,
    csv_path: Path,
    expected: dict[str, object],
) -> dict[str, object]:
    try:
        json_result = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssertionError("JSON output is missing or invalid") from exc
    if json_result != expected:
        raise AssertionError(f"JSON output does not match expected result: {json_result!r}")
    try:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise AssertionError("CSV output is missing") from exc
    if len(rows) != 1:
        raise AssertionError(f"CSV output must contain exactly one row, got {len(rows)}")
    csv_result = _normalized_csv_result(rows[0])
    if csv_result != expected:
        raise AssertionError(f"CSV output does not match expected result: {csv_result!r}")
    return {"ok": True, "csv_rows": 1, "result": json_result}


def validate_png(path: Path) -> dict[str, object]:
    try:
        if path.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise AssertionError("PNG signature is invalid")
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
    except (OSError, ValueError) as exc:
        raise AssertionError(f"PNG artifact is invalid: {path}") from exc
    if width < 1 or height < 1:
        raise AssertionError(f"PNG artifact is empty: {path}")
    return {"path": str(path), "width": width, "height": height}


def validate_missing_target_result(
    result: dict[str, object],
    *,
    export_paths: Iterable[Path],
) -> dict[str, object]:
    if result.get("ok") is not False or result.get("failure_code") != "UI_LOCATOR_NOT_FOUND":
        raise AssertionError("missing target did not fail with UI_LOCATOR_NOT_FOUND")
    blocked = [
        dict(item)
        for item in list(result.get("trace") or [])
        if isinstance(item, dict) and item.get("status") == "blocked"
    ]
    if not blocked:
        raise AssertionError("missing target result has no blocked trace step")
    evidence = [Path(str(path)) for path in list(result.get("failure_artifacts") or [])]
    if not evidence:
        raise AssertionError("missing target result has no PNG evidence")
    validated_evidence = [validate_png(path) for path in evidence]
    unexpected_exports = [str(path) for path in export_paths if Path(path).exists()]
    if unexpected_exports:
        raise AssertionError(f"missing target created an unexpected export: {unexpected_exports}")
    return {
        "blocked_as_expected": True,
        "failure_code": "UI_LOCATOR_NOT_FOUND",
        "blocked_step": str(blocked[0].get("step") or ""),
        "evidence": validated_evidence,
    }


def build_bridge_command(
    *,
    run_root: Path,
    bridge_port: int,
    token: str,
    python_executable: str | None = None,
) -> list[str]:
    if int(bridge_port) == 7860:
        raise ValueError("port 7860 belongs to the main ATR server and is forbidden for this E2E runner")
    if not 1 <= int(bridge_port) <= 65535:
        raise ValueError("bridge port must be in 1..65535")
    bridge = ROOT / "Pyautogui_server_for_window" / "bridge" / "windows_pyautogui_bridge_server.py"
    return [
        python_executable or sys.executable,
        str(bridge),
        "--host",
        "127.0.0.1",
        "--port",
        str(int(bridge_port)),
        "--token",
        str(token),
        "--platform",
        "linux",
        "--artifact-dir",
        str(run_root / "bridge" / "artifacts"),
        "--reference-dir",
        str(run_root / "bridge" / "references"),
        "--utm-export-dir",
        str(run_root / "bridge" / "utm_exports"),
        "--program-dir",
        str(run_root / "bridge" / "programs"),
        "--recording-dir",
        str(run_root / "recordings"),
    ]


def normalize_execute_failure(result: dict[str, object]) -> dict[str, object]:
    normalized = dict(result)
    normalized["trace"] = list(result.get("step_trace") or result.get("trace") or [])
    paths: list[str] = []
    for artifact in list(result.get("output_artifacts") or []):
        if not isinstance(artifact, dict) or str(artifact.get("kind") or "") not in {"screen_png", "screenshot"}:
            continue
        path = str(artifact.get("windows_path") or artifact.get("path") or "").strip()
        if path:
            paths.append(path)
    direct = result.get("failure_artifact")
    if isinstance(direct, dict):
        path = str(direct.get("windows_path") or direct.get("path") or "").strip()
        if path:
            paths.append(path)
    normalized["failure_artifacts"] = list(dict.fromkeys(paths))
    return normalized


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"unable to read JSON state: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON state must be an object: {path}")
    return payload


def _wait_until(predicate: Any, *, timeout_s: float, label: str, interval_s: float = 0.1) -> Any:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:
            last_error = exc
        time.sleep(interval_s)
    detail = f"; last_error={last_error}" if last_error else ""
    raise TimeoutError(f"timed out waiting for {label}{detail}")


def _wait_status(status_path: Path, state: str, *, timeout_s: float = 15.0) -> dict[str, object]:
    def ready() -> dict[str, object] | None:
        payload = _read_json(status_path)
        return payload if payload.get("state") == state else None

    return _wait_until(ready, timeout_s=timeout_s, label=f"demo state={state}")


def _http_json(
    base_url: str,
    path: str,
    *,
    token: str,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    timeout_s: float = 30.0,
) -> dict[str, object]:
    data = json.dumps(payload, ensure_ascii=True).encode("utf-8") if payload is not None else None
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-Bridge-Token": token},
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8"))
        except Exception as parse_error:
            raise RuntimeError(f"HTTP {exc.code} from {path}") from parse_error
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"bridge request failed: {method} {path}: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"bridge response was not an object: {method} {path}")
    return result


def _capture_png(pyautogui: Any, path: Path) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    pyautogui.screenshot().save(path)
    return validate_png(path)


def _clear_exports(output_root: Path) -> tuple[Path, Path]:
    paths = (output_root / "advanced_queue_result.json", output_root / "advanced_queue_result.csv")
    for path in paths:
        if path.exists():
            path.unlink()
    return paths


def _reset_demo(mode_path: Path, status_path: Path, mode: str) -> dict[str, object]:
    mode_path.parent.mkdir(parents=True, exist_ok=True)
    current_token = mode_path.read_text(encoding="utf-8").strip() if mode_path.exists() else ""
    candidates = (f"{mode}_reset", f"{mode}-reset")
    token = candidates[1] if current_token == candidates[0] else candidates[0]
    mode_path.write_text(token + "\n", encoding="utf-8")

    def ready() -> dict[str, object] | None:
        payload = _read_json(status_path)
        return payload if payload.get("state") == "waiting" and payload.get("mode") == mode else None

    return _wait_until(ready, timeout_s=15.0, label=f"demo reset mode={mode}")


def _sleep_transition(seconds: float = 0.85) -> None:
    # These pauses are intentionally recorded and compiled as bounded waits.
    time.sleep(seconds)


def _recording_click(pyautogui: Any, x: int, y: int) -> None:
    """Create a real pre-click pointer frame for image-first recording."""
    pyautogui.moveTo(int(x), int(y), duration=0.12)
    pyautogui.click()


def _drive_recording_workflow(
    pyautogui: Any,
    *,
    base_url: str,
    token: str,
    status_path: Path,
    evidence_root: Path,
) -> dict[str, object]:
    pyautogui.PAUSE = 0.12
    pyautogui.FAILSAFE = True

    # Allow the bridge's pynput listeners to enter their running state before
    # the first semantic pointer event.
    _sleep_transition()
    _recording_click(pyautogui, 232, 209)
    _sleep_transition()
    _recording_click(pyautogui, 580, 385)
    _sleep_transition()

    pyautogui.moveTo(329, 420, duration=0.2)
    pyautogui.dragTo(830, 410, duration=0.65, button="left")
    _sleep_transition()

    _recording_click(pyautogui, 703, 519)
    _sleep_transition()
    _recording_click(pyautogui, 671, 421)
    pyautogui.press("home")
    pyautogui.press("enter")
    _recording_click(pyautogui, 671, 516)
    pyautogui.press("home")
    pyautogui.press("delete", presses=32, interval=0.01)
    pyautogui.write("12.5", interval=0.08)
    _recording_click(pyautogui, 671, 588)
    _recording_click(pyautogui, 671, 676)
    _sleep_transition()

    _recording_click(pyautogui, 956, 519)
    _wait_status(status_path, "validation_failed")
    checkpoint = _http_json(
        base_url,
        "/recordings/checkpoint",
        token=token,
        method="POST",
        payload={"label": "bounded recovery required"},
    )
    if not checkpoint.get("ok"):
        raise RuntimeError(f"recovery checkpoint failed: {checkpoint}")
    _capture_png(pyautogui, evidence_root / "recorded_validation_failed.png")
    _sleep_transition()

    _recording_click(pyautogui, 600, 617)
    _sleep_transition()
    _recording_click(pyautogui, 671, 588)
    _recording_click(pyautogui, 671, 676)
    _sleep_transition()
    _recording_click(pyautogui, 956, 519)
    completed = _wait_status(status_path, "completed")
    _capture_png(pyautogui, evidence_root / "recorded_completed.png")
    _sleep_transition()

    _recording_click(pyautogui, 975, 682)
    _sleep_transition()
    _recording_click(pyautogui, 563, 367)
    _recording_click(pyautogui, 859, 367)
    _recording_click(pyautogui, 711, 478)
    pyautogui.press("home")
    pyautogui.press("delete", presses=64, interval=0.01)
    pyautogui.write("advanced_queue_result", interval=0.04)
    _recording_click(pyautogui, 711, 585)
    exported = _wait_status(status_path, "exported")
    _capture_png(pyautogui, evidence_root / "recorded_exported.png")
    return {"completed": completed, "exported": exported}


def _register_programs(base_url: str, token: str, programs: list[dict[str, object]]) -> None:
    for program in programs:
        response = _http_json(base_url, "/programs/register", token=token, method="POST", payload=program)
        if not response.get("ok"):
            raise RuntimeError(f"program registration failed: {response}")


def _execute_programs(
    base_url: str,
    token: str,
    program_ids: Iterable[str],
    *,
    scenario: str,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    results: list[dict[str, object]] = []
    failure: dict[str, object] | None = None
    for index, program_id in enumerate(program_ids, start=1):
        response = _http_json(
            base_url,
            "/execute",
            token=token,
            method="POST",
            payload={
                "sequence_id": f"advanced-queue-{scenario}-{index:03d}-{time.time_ns()}",
                "run_id": f"advanced-queue-{scenario}",
                "specimen_id": "specimen-beta",
                "program_id": str(program_id),
            },
            timeout_s=120.0,
        )
        results.append(response)
        if not response.get("ok"):
            failure = response
            break
    return results, failure


def _start_process(command: list[str], *, env: dict[str, str], cwd: Path, log_path: Path) -> tuple[subprocess.Popen[bytes], Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab", buffering=0)
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return process, handle


def _stop_children(children: list[tuple[subprocess.Popen[bytes], Any]]) -> None:
    for process, _handle in reversed(children):
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5.0
    for process, handle in reversed(children):
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        handle.close()


def _load_or_create_skill(
    *,
    recording: dict[str, object] | None,
    version: str,
    reuse_skill: bool,
) -> tuple[EquipmentSkillRegistry, dict[str, object], bool]:
    registry = EquipmentSkillRegistry(ROOT / "memory" / "equipment_skills")
    package_dir = registry.root / "advanced_visual_work_queue_demo" / version
    if package_dir.exists():
        if not reuse_skill:
            raise RuntimeError(
                f"immutable Skill package already exists: {package_dir}; pass --reuse-skill or choose --version"
            )
        package = registry.get("advanced_visual_work_queue_demo", version)
        if package["manifest"].get("lifecycle") not in {"validated", "deployed"}:
            raise RuntimeError(f"existing Skill package is not validated: {package_dir}")
        return registry, package, False
    if reuse_skill:
        raise RuntimeError(f"requested reusable Skill package does not exist: {package_dir}")
    if recording is None:
        raise RuntimeError("a saved recording is required to create a new Skill")
    clean_recording = dict(recording)
    clean_recording.pop("ok", None)
    registry.create_draft(
        recording=clean_recording,
        skill_id="advanced_visual_work_queue_demo",
        version=version,
        target_profile="advanced_visual_work_queue",
        model_snapshot={"provider": "deterministic", "model": "operator_recording", "reasoning": "not_required"},
    )
    compiled = registry.compile("advanced_visual_work_queue_demo", version)
    validated = registry.validate("advanced_visual_work_queue_demo", version)
    if validated.get("ok") is not True:
        raise RuntimeError(f"Skill validation failed: {validated}")
    validated_package = validated.get("package")
    if not isinstance(validated_package, dict):
        raise RuntimeError("Skill validation response omitted the validated package")
    return registry, validated_package, True


def run_scenario(
    *,
    run_root: Path,
    display: str,
    bridge_port: int,
    scenario: str = "all",
    version: str = "1.0.0",
    reuse_skill: bool = False,
) -> dict[str, object]:
    if int(bridge_port) == 7860:
        raise ValueError("port 7860 belongs to the main ATR server")
    run_root = Path(run_root).expanduser().resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    runtime_root = run_root / "demo_runtime"
    output_root = runtime_root / "output"
    status_path = runtime_root / "status.json"
    mode_path = runtime_root / "mode.txt"
    evidence_root = run_root / "evidence"
    logs_root = run_root / "logs"
    for directory in (output_root, evidence_root, logs_root):
        directory.mkdir(parents=True, exist_ok=True)
    token = "advanced-queue-isolated-token"
    base_url = f"http://127.0.0.1:{int(bridge_port)}"
    env = os.environ.copy()
    env.update(
        {
            "DISPLAY": display,
            "XDG_SESSION_TYPE": "x11",
            "ATR_PYAUTOGUI_BRIDGE_PLATFORM": "linux",
            "ATR_ADVANCED_QUEUE_ROOT": str(runtime_root),
        }
    )
    # PyAutoGUI binds to DISPLAY at import time; the driver must share the
    # isolated X server with the bridge and demo rather than the operator UI.
    os.environ["DISPLAY"] = display
    os.environ["XDG_SESSION_TYPE"] = "x11"
    mode_path.parent.mkdir(parents=True, exist_ok=True)
    mode_path.write_text("initial_reset\n", encoding="utf-8")
    children: list[tuple[subprocess.Popen[bytes], Any]] = []
    summary: dict[str, object] = {
        "schema": "atr.advanced_visual_work_queue_e2e.v1",
        "scenario": scenario,
        "version": version,
        "run_root": str(run_root),
        "display": display,
        "bridge_port": int(bridge_port),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        xvfb, xvfb_log = _start_process(
            ["Xvfb", display, "-screen", "0", "1920x1080x24", "-nolisten", "tcp"],
            env=env,
            cwd=ROOT,
            log_path=logs_root / "xvfb.log",
        )
        children.append((xvfb, xvfb_log))
        _wait_until(lambda: Path(f"/tmp/.X11-unix/X{display.lstrip(':')}").exists(), timeout_s=8.0, label="Xvfb socket")

        bridge_command = build_bridge_command(
            run_root=run_root,
            bridge_port=bridge_port,
            token=token,
            python_executable=sys.executable,
        )
        bridge, bridge_log = _start_process(
            bridge_command,
            env=env,
            cwd=ROOT,
            log_path=logs_root / "bridge.log",
        )
        children.append((bridge, bridge_log))
        _wait_until(
            lambda: _http_json(base_url, "/health", token=token).get("ok"),
            timeout_s=20.0,
            label="isolated bridge health",
        )

        demo_command = [sys.executable, str(ROOT / "Pyautogui_server_for_window" / "demo" / "advanced_visual_work_queue.py")]
        demo, demo_log = _start_process(demo_command, env=env, cwd=ROOT, log_path=logs_root / "demo.log")
        children.append((demo, demo_log))
        _wait_status(status_path, "waiting", timeout_s=15.0)

        # Import only after DISPLAY is fixed for this process.
        import pyautogui  # type: ignore

        recording: dict[str, object] | None = None
        created = False
        if not reuse_skill:
            _clear_exports(output_root)
            _capture_png(pyautogui, evidence_root / "recorded_before.png")
            started = _http_json(
                base_url,
                "/recordings/start",
                token=token,
                method="POST",
                payload={
                    "name": "Advanced visual work queue",
                    "target_app": "ATR Advanced Visual Work Queue",
                    "target_window": "ATR Advanced Visual Work Queue",
                    "image_tracking": True,
                    "coordinate_fallback": False,
                },
            )
            if not started.get("ok"):
                raise RuntimeError(f"recording start failed: {started}")
            _drive_recording_workflow(
                pyautogui,
                base_url=base_url,
                token=token,
                status_path=status_path,
                evidence_root=evidence_root,
            )
            stopped = _http_json(base_url, "/recordings/stop", token=token, method="POST", payload={})
            if not stopped.get("ok"):
                raise RuntimeError(f"recording stop failed: {stopped}")
            recording_id = str(stopped.get("recording_id") or "")
            recording = _http_json(
                base_url,
                f"/recordings/{recording_id}/save",
                token=token,
                method="POST",
                payload={},
            )
            if not recording.get("ok") or recording.get("status") != "saved":
                raise RuntimeError(f"recording save failed: {recording}")
            recorded_status = _read_json(status_path)
            if recorded_status.get("analysis_attempts") != 2 or recorded_status.get("recovery_count") != 1:
                raise AssertionError(f"bounded recovery contract failed: {recorded_status}")
            if recorded_status.get("state") != "exported":
                raise AssertionError(f"recorded workflow did not export: {recorded_status}")
            summary["recording"] = {
                "recorded": True,
                "recording_id": recording_id,
                "event_count": len(list(recording.get("events") or [])),
                "checkpoint_count": len(list(recording.get("checkpoints") or [])),
                "analysis_attempts": 2,
                "recovery_count": 1,
            }

        registry, package, created = _load_or_create_skill(
            recording=recording,
            version=version,
            reuse_skill=reuse_skill,
        )
        programs = [dict(item) for item in list(package.get("programs") or []) if isinstance(item, dict)]
        assert_image_only_programs(programs)
        _register_programs(base_url, token, programs)
        program_ids = [str(item) for item in list(package["workflow"].get("program_ids") or [])]
        summary["skill"] = {
            "created": created,
            "compiled": bool(programs),
            "validated": package["manifest"].get("lifecycle") in {"validated", "deployed"},
            "package_path": str(registry.root / "advanced_visual_work_queue_demo" / version),
            "program_ids": program_ids,
        }

        if scenario in {"all", "shifted-reordered"}:
            _reset_demo(mode_path, status_path, "shifted_reordered")
            json_path, csv_path = _clear_exports(output_root)
            before = _capture_png(pyautogui, evidence_root / "shifted_reordered_before.png")
            results, failure = _execute_programs(base_url, token, program_ids, scenario="shifted-reordered")
            if failure is not None:
                raise AssertionError(f"shifted/reordered replay failed: {failure}")
            replay_status = _wait_status(status_path, "exported", timeout_s=30.0)
            after = _capture_png(pyautogui, evidence_root / "shifted_reordered_exported.png")
            artifacts = validate_exported_artifacts(json_path, csv_path, EXPECTED_RESULT)
            if replay_status.get("analysis_attempts") != 2 or replay_status.get("recovery_count") != 1:
                raise AssertionError(f"shifted replay violated bounded recovery: {replay_status}")
            summary["shifted_reordered"] = {
                "ok": True,
                "execution_count": len(results),
                "analysis_attempts": 2,
                "recovery_count": 1,
                "artifacts": artifacts,
                "evidence": [before, after],
            }

        if scenario in {"all", "missing-target"}:
            _reset_demo(mode_path, status_path, "missing_target")
            json_path, csv_path = _clear_exports(output_root)
            results, failure = _execute_programs(base_url, token, program_ids, scenario="missing-target")
            if failure is None:
                raise AssertionError(f"missing target replay unexpectedly succeeded: {results}")
            normalized = normalize_execute_failure(failure)
            missing = validate_missing_target_result(normalized, export_paths=[json_path, csv_path])
            missing_status = _read_json(status_path)
            if list(missing_status.get("queue") or []) or missing_status.get("analysis_attempts") != 0:
                raise AssertionError(f"missing target replay mutated workflow state: {missing_status}")
            summary["missing_target"] = {**missing, "queue": [], "analysis_attempts": 0}

        test_result = {
            "ok": True,
            "status": "verified",
            "scenario": scenario,
            "shifted_reordered": summary.get("shifted_reordered", {}),
            "missing_target": summary.get("missing_target", {}),
        }
        registry.record_test("advanced_visual_work_queue_demo", version, test_result)
        summary["ok"] = True
        summary["completed_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(run_root / "e2e_summary.json", summary)
        return summary
    except Exception as exc:
        summary["ok"] = False
        summary["error"] = f"{exc.__class__.__name__}: {exc}"
        summary["completed_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_json(run_root / "e2e_summary.json", summary)
        raise
    finally:
        _stop_children(children)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record, compile, and replay the advanced visual work queue Skill.")
    parser.add_argument("--scenario", choices=("all", "shifted-reordered", "missing-target"), default="all")
    parser.add_argument("--display", default=":99")
    parser.add_argument("--bridge-port", type=int, default=8878)
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--reuse-skill", action="store_true")
    parser.add_argument("--run-root", type=Path, default=ROOT / "runs" / "equipment_skill_advanced_queue_e2e")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = run_scenario(
        run_root=args.run_root,
        display=args.display,
        bridge_port=args.bridge_port,
        scenario=args.scenario,
        version=args.version,
        reuse_skill=args.reuse_skill,
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
