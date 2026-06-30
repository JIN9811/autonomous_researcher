"""Isaac Sim extension that hosts the ATR ROBOTIS OMX mirror receiver in-process."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

RED_SPECIMEN_BLOCK_PATH = "/World/Workspace/RedSpecimenBlock"
MM_TO_M = 0.001
DEFAULT_PENDING_SPECIMEN_POSE_PATH = "/tmp/atr_specimen_pose_pending/latest_specimen_pose_payload.json"
DEFAULT_ACTIVE_ROBOT_CAM_REQUEST_PATH = "/tmp/atr_active_robot_cam_request/request.json"

try:
    import omni.ext  # type: ignore
except Exception:  # pragma: no cover - exercised outside Isaac by unit tests
    class _BaseExtension:
        pass
else:
    _BaseExtension = omni.ext.IExt  # type: ignore[name-defined]


def _repo_root_from_extension() -> Path:
    """Find the autonomous_researcher repo root from this extension path."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "sim" / "robotis_omx" / "tools" / "isaac_omx_mirror_server.py").exists():
            return parent
    # extension.py -> mirror -> omx -> atr -> atr.omx.mirror -> extensions -> robotis_omx -> sim -> repo
    return here.parents[7]


def _settings() -> Any | None:
    try:
        import carb.settings  # type: ignore

        return carb.settings.get_settings()
    except Exception:
        return None


def _setting_string(settings: Any | None, key: str, default: str) -> str:
    if settings is None:
        return default
    try:
        value = settings.get_as_string(key)
    except Exception:
        try:
            value = settings.get(key)
        except Exception:
            value = None
    text = str(value or "").strip()
    return text or default


def _setting_int(settings: Any | None, key: str, default: int) -> int:
    if settings is None:
        return default
    try:
        value = settings.get_as_int(key)
    except Exception:
        try:
            value = settings.get(key)
        except Exception:
            value = None
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _setting_float(settings: Any | None, key: str, default: float) -> float:
    if settings is None:
        return default
    try:
        value = settings.get(key)
    except Exception:
        value = None
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _setting_bool(settings: Any | None, key: str, default: bool) -> bool:
    if settings is None:
        return default
    try:
        value = settings.get_as_bool(key)
    except Exception:
        try:
            value = settings.get(key)
        except Exception:
            value = None
    if value is None:
        return default
    return bool(value)


def _payload_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _log_info(message: str) -> None:
    try:
        import carb  # type: ignore

        carb.log_info(message)
    except Exception:
        print(message)


def _log_error(message: str) -> None:
    try:
        import carb  # type: ignore

        carb.log_error(message)
    except Exception:
        print(message)


def _log_warn(message: str) -> None:
    try:
        import carb  # type: ignore

        carb.log_warn(message)
    except Exception:
        print(message)


def _prim_is_valid(prim: Any) -> bool:
    if prim is None:
        return False
    checker = getattr(prim, "IsValid", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    return True


def _float_from_pose(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_yaw_deg(value: float) -> float:
    yaw = ((float(value) + 180.0) % 360.0) - 180.0
    if math.isclose(yaw, -180.0):
        return 180.0
    return yaw


def _specimen_yaw_deg_from_pose(pose: dict[str, Any]) -> float | None:
    orientation = pose.get("orientation_deg") if isinstance(pose.get("orientation_deg"), dict) else {}
    for value in (orientation.get("yaw"), orientation.get("yaw_deg"), pose.get("yaw_deg")):
        yaw = _float_from_pose(value)
        if yaw is not None:
            return _normalize_yaw_deg(yaw)
    return None


def _xform_op_name(op: Any) -> str:
    getter = getattr(op, "GetOpName", None)
    if callable(getter):
        return str(getter())
    return ""


def _rotate_z_before_scale_order(ops: list[Any], rotate_op: Any) -> list[Any]:
    ordered: list[Any] = []
    inserted = False
    for op in ops:
        name = _xform_op_name(op)
        if name == "xformOp:rotateZ":
            continue
        if name == "xformOp:scale" and not inserted:
            ordered.append(rotate_op)
            inserted = True
        ordered.append(op)
    if not inserted:
        ordered.append(rotate_op)
    return ordered


def _apply_specimen_yaw_to_prim(prim: Any, yaw_deg: float | None) -> dict[str, Any]:
    if yaw_deg is None:
        return {"applied": False}
    yaw = _normalize_yaw_deg(float(yaw_deg))
    try:
        from pxr import UsdGeom  # type: ignore

        xformable = UsdGeom.Xformable(prim)
        ops = list(xformable.GetOrderedXformOps())
        rotate_op = next((op for op in ops if _xform_op_name(op) == "xformOp:rotateZ"), None)
        if rotate_op is None:
            rotate_op = xformable.AddRotateZOp(precision=UsdGeom.XformOp.PrecisionDouble)
            ops = list(xformable.GetOrderedXformOps())
        rotate_op.Set(yaw)
        ordered_ops = _rotate_z_before_scale_order(ops, rotate_op)
        xformable.SetXformOpOrder(ordered_ops)
    except Exception as exc:
        return {
            "applied": False,
            "failure_code": "SPECIMEN_ROTATE_Z_OP_ERROR",
            "message": f"큐브 yaw 적용 실패: {exc.__class__.__name__}: {exc}",
        }
    return {"applied": True, "yaw": yaw, "xformOpOrder": [_xform_op_name(op) for op in ordered_ops]}


def _apply_specimen_pose_snapshot_to_stage(
    stage: Any,
    snapshot: dict[str, Any],
    red_cube_path: str = RED_SPECIMEN_BLOCK_PATH,
) -> dict[str, Any]:
    if not bool(snapshot.get("ok")):
        code = str(snapshot.get("failure_code") or "SPECIMEN_POSE_FAILED")
        detail = str(snapshot.get("message") or "No red specimen pose was returned.")
        return {
            "ok": False,
            "status": "snapshot_failed",
            "failure_code": code,
            "message": f"큐브가 제 위치에 없거나 검출되지 않았습니다: {code}: {detail}",
        }

    pose = snapshot.get("pose") if isinstance(snapshot.get("pose"), dict) else {}
    world_mm = pose.get("position_isaac_world_mm") if isinstance(pose.get("position_isaac_world_mm"), dict) else {}
    x_mm = _float_from_pose(world_mm.get("x"))
    y_mm = _float_from_pose(world_mm.get("y"))
    z_mm = _float_from_pose(world_mm.get("z"))
    if x_mm is None or y_mm is None or z_mm is None:
        return {
            "ok": False,
            "status": "pose_invalid",
            "failure_code": "SPECIMEN_POSE_INVALID",
            "message": "큐브 위치 JSON에 position_isaac_world_mm x/y/z가 없습니다.",
        }

    try:
        prim = stage.GetPrimAtPath(red_cube_path)
    except Exception as exc:
        return {
            "ok": False,
            "status": "stage_error",
            "failure_code": "SPECIMEN_STAGE_ERROR",
            "message": f"큐브 위치 적용 중 stage 오류: {exc.__class__.__name__}",
        }
    if not _prim_is_valid(prim):
        return {
            "ok": False,
            "status": "cube_missing",
            "failure_code": "SPECIMEN_CUBE_PRIM_MISSING",
            "message": f"Isaac stage에서 {red_cube_path} 큐브 prim을 찾지 못했습니다.",
        }

    translate_m = (x_mm * MM_TO_M, y_mm * MM_TO_M, z_mm * MM_TO_M)
    attr = None
    try:
        attr = prim.GetAttribute("xformOp:translate")
    except Exception:
        attr = None
    if attr is None:
        try:
            attr = prim.CreateAttribute("xformOp:translate", "double3")
        except Exception as exc:
            return {
                "ok": False,
                "status": "attribute_error",
                "failure_code": "SPECIMEN_TRANSLATE_ATTR_ERROR",
                "message": f"큐브 translate attribute 생성 실패: {exc.__class__.__name__}",
            }
    try:
        attr.Set(translate_m)
    except Exception as exc:
        return {
            "ok": False,
            "status": "attribute_error",
            "failure_code": "SPECIMEN_TRANSLATE_SET_ERROR",
            "message": f"큐브 위치 적용 실패: {exc.__class__.__name__}",
        }
    yaw_deg = _specimen_yaw_deg_from_pose(pose)
    yaw_result = _apply_specimen_yaw_to_prim(prim, yaw_deg)
    if yaw_deg is not None and not bool(yaw_result.get("applied")):
        return {
            "ok": False,
            "status": "attribute_error",
            "failure_code": str(yaw_result.get("failure_code") or "SPECIMEN_ROTATE_Z_OP_ERROR"),
            "message": str(yaw_result.get("message") or "큐브 yaw 적용 실패"),
        }

    result = {
        "ok": True,
        "status": "applied",
        "red_cube_path": red_cube_path,
        "translate_m": [translate_m[0], translate_m[1], translate_m[2]],
        "snapshot_path": str(pose.get("raw_pose_json_path") or ""),
    }
    if yaw_result.get("applied"):
        result["orientation_deg"] = {"yaw": yaw_result["yaw"]}
        result["xformOpOrder"] = yaw_result.get("xformOpOrder", [])
    return result


def _apply_specimen_transform_to_stage(
    stage: Any,
    translate_m: list[float] | tuple[float, float, float],
    red_cube_path: str,
    yaw_deg: float | None = None,
) -> dict[str, Any]:
    try:
        prim = stage.GetPrimAtPath(red_cube_path)
    except Exception as exc:
        return {
            "ok": False,
            "status": "stage_error",
            "failure_code": "SPECIMEN_STAGE_ERROR",
            "message": f"큐브 위치 재적용 중 stage 오류: {exc.__class__.__name__}",
        }
    if not _prim_is_valid(prim):
        return {
            "ok": False,
            "status": "cube_missing",
            "failure_code": "SPECIMEN_CUBE_PRIM_MISSING",
            "message": f"Isaac stage에서 {red_cube_path} 큐브 prim을 찾지 못했습니다.",
        }
    attr = prim.GetAttribute("xformOp:translate")
    if attr is None:
        attr = prim.CreateAttribute("xformOp:translate", "double3")
    try:
        translate = (float(translate_m[0]), float(translate_m[1]), float(translate_m[2]))
        attr.Set(translate)
    except Exception as exc:
        return {
            "ok": False,
            "status": "attribute_error",
            "failure_code": "SPECIMEN_TRANSLATE_SET_ERROR",
            "message": f"큐브 위치 재적용 실패: {exc.__class__.__name__}",
        }
    yaw_result = _apply_specimen_yaw_to_prim(prim, yaw_deg)
    if yaw_deg is not None and not bool(yaw_result.get("applied")):
        return {
            "ok": False,
            "status": "attribute_error",
            "failure_code": str(yaw_result.get("failure_code") or "SPECIMEN_ROTATE_Z_OP_ERROR"),
            "message": str(yaw_result.get("message") or "큐브 yaw 재적용 실패"),
        }
    result = {"ok": True, "status": "reapplied", "red_cube_path": red_cube_path, "translate_m": [translate[0], translate[1], translate[2]]}
    if yaw_result.get("applied"):
        result["orientation_deg"] = {"yaw": yaw_result["yaw"]}
        result["xformOpOrder"] = yaw_result.get("xformOpOrder", [])
    return result


def _apply_specimen_translate_to_stage(stage: Any, translate_m: list[float] | tuple[float, float, float], red_cube_path: str) -> dict[str, Any]:
    return _apply_specimen_transform_to_stage(stage, translate_m, red_cube_path)


def _json_object_from_stdout(stdout: str) -> dict[str, Any] | None:
    for line in reversed(str(stdout or "").splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _run_specimen_pose_snapshot(
    repo_root: Path,
    script_path: Path,
    payload: dict[str, Any],
    *,
    timeout_sec: float,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if not script_path.exists():
        return {
            "ok": False,
            "failure_code": "SPECIMEN_POSE_SCRIPT_MISSING",
            "message": f"Specimen pose snapshot script is missing: {script_path}",
        }
    cmd = [str(script_path), json.dumps(payload, ensure_ascii=True)]
    try:
        completed = runner(
            cmd,
            cwd=str(repo_root),
            text=True,
            capture_output=True,
            timeout=max(float(timeout_sec), 0.5),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "failure_code": "SPECIMEN_POSE_TIMEOUT",
            "message": f"Specimen pose snapshot timed out after {timeout_sec:.1f}s.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "failure_code": "SPECIMEN_POSE_SNAPSHOT_ERROR",
            "message": f"Specimen pose snapshot failed: {exc.__class__.__name__}: {exc}",
        }

    snapshot = _json_object_from_stdout(str(completed.stdout or ""))
    if snapshot is None:
        return {
            "ok": False,
            "failure_code": "SPECIMEN_POSE_OUTPUT_INVALID",
            "message": "Specimen pose snapshot did not return a JSON object.",
            "returncode": int(completed.returncode),
            "stderr": str(completed.stderr or ""),
        }
    snapshot.setdefault("returncode", int(completed.returncode))
    if completed.returncode != 0 and bool(snapshot.get("ok")):
        snapshot["ok"] = False
        snapshot["failure_code"] = "SPECIMEN_POSE_PROCESS_FAILED"
        snapshot["message"] = str(snapshot.get("message") or f"snapshot process exited with returncode={completed.returncode}")
    return snapshot


def _pending_specimen_pose_path(payload: dict[str, Any]) -> Path:
    return Path(
        str(
            payload.get("pending_pose_path")
            or payload.get("specimen_pose_pending_path")
            or DEFAULT_PENDING_SPECIMEN_POSE_PATH
        )
    ).expanduser()


def _active_robot_cam_request_path(payload: dict[str, Any]) -> Path:
    return Path(str(payload.get("active_robot_cam_request_path") or DEFAULT_ACTIVE_ROBOT_CAM_REQUEST_PATH)).expanduser()


def _load_pending_specimen_pose_snapshot(payload: dict[str, Any]) -> dict[str, Any] | None:
    path = _pending_specimen_pose_path(payload)
    if not path.is_file():
        return None
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _log_warn(f"ATR OMX mirror pending specimen pose invalid: {path}: {exc.__class__.__name__}: {exc}")
        _discard_pending_specimen_pose_path(path)
        return None
    if not isinstance(snapshot, dict):
        _discard_pending_specimen_pose_path(path)
        return None
    pose = snapshot.get("pose")
    if isinstance(pose, dict):
        pose.setdefault("raw_pose_json_path", str(path))
    snapshot.setdefault("pending_pose_path", str(path))
    return snapshot


def _consume_pending_specimen_pose(payload: dict[str, Any]) -> None:
    if not _payload_bool(payload, "consume_pending_pose", True):
        return
    try:
        _pending_specimen_pose_path(payload).unlink(missing_ok=True)
    except Exception as exc:
        _log_warn(f"ATR OMX mirror pending specimen pose consume failed: {exc.__class__.__name__}: {exc}")


def _discard_pending_specimen_pose_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception as exc:
        _log_warn(f"ATR OMX mirror pending specimen pose discard failed: {exc.__class__.__name__}: {exc}")


def _request_active_robot_cam_capture(payload: dict[str, Any], *, reason: str) -> dict[str, Any]:
    request_path = _active_robot_cam_request_path(payload)
    pending_path = _pending_specimen_pose_path(payload)
    timeout_s = float(payload.get("active_robot_cam_wait_timeout_s") or 12.0)
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_id = str(time.time_ns())
    requested_at = time.time()
    request = {
        "schema": "atr_active_robot_cam_request.v1",
        "request_id": request_id,
        "reason": reason,
        "pending_pose_path": str(pending_path),
        "requested_at": requested_at,
        "expires_at": requested_at + max(timeout_s, 0.0),
    }
    tmp_path = request_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(request, ensure_ascii=True, indent=2), encoding="utf-8")
    tmp_path.replace(request_path)
    deadline = time.monotonic() + max(timeout_s, 0.0)
    while time.monotonic() <= deadline:
        if pending_path.is_file():
            return {
                "ok": True,
                "status": "active_robot_cam_pending_ready",
                "request_path": str(request_path),
                "pending_pose_path": str(pending_path),
            }
        time.sleep(0.1)
    try:
        current = json.loads(request_path.read_text(encoding="utf-8")) if request_path.is_file() else {}
    except Exception:
        current = {}
    if not isinstance(current, dict) or str(current.get("request_id") or "") == request_id:
        try:
            request_path.unlink(missing_ok=True)
        except Exception:
            pass
    return {
        "ok": False,
        "status": "active_robot_cam_capture_requested",
        "failure_code": "ACTIVE_ROBOT_CAM_PENDING_TIMEOUT",
        "message": f"Active Robot Cam request was written but pending pose did not appear within {timeout_s:g}s.",
        "request_path": str(request_path),
        "pending_pose_path": str(pending_path),
    }


def _current_gui_stage() -> Any | None:
    try:
        import omni.usd  # type: ignore

        context = omni.usd.get_context()
        if context is None:
            return None
        return context.get_stage()
    except Exception:
        return None


def _run_and_apply_specimen_pose_snapshot(
    repo_root: Path,
    script_path: Path,
    payload: dict[str, Any],
    *,
    timeout_sec: float,
    red_cube_path: str,
) -> dict[str, Any]:
    stage = _current_gui_stage()
    if stage is None:
        return {
            "ok": False,
            "status": "stage_unavailable",
            "failure_code": "SPECIMEN_STAGE_UNAVAILABLE",
            "message": "Isaac GUI stage가 없어 REDCUBE 위치를 갱신하지 못했습니다.",
        }
    pending_snapshot = _load_pending_specimen_pose_snapshot(payload)
    if pending_snapshot is not None:
        pending_result = _apply_specimen_pose_snapshot_to_stage(stage, pending_snapshot, red_cube_path)
        if bool(pending_result.get("ok")):
            _consume_pending_specimen_pose(payload)
            return pending_result
        _log_warn(f"ATR OMX mirror pending specimen pose warning: {pending_result.get('message') or pending_result}")
        if str(pending_result.get("failure_code") or "") == "SPECIMEN_POSE_INVALID":
            _consume_pending_specimen_pose(payload)
    if _payload_bool(payload, "active_robot_cam_trigger", False):
        request_result = _request_active_robot_cam_capture(
            payload,
            reason=str(payload.get("active_robot_cam_trigger_reason") or "isaac_timeline"),
        )
        if not bool(request_result.get("ok")):
            return request_result
        pending_snapshot = _load_pending_specimen_pose_snapshot(payload)
        if pending_snapshot is not None:
            pending_result = _apply_specimen_pose_snapshot_to_stage(stage, pending_snapshot, red_cube_path)
            if bool(pending_result.get("ok")):
                _consume_pending_specimen_pose(payload)
                return pending_result
            _log_warn(f"ATR OMX mirror active-cam pending specimen pose warning: {pending_result.get('message') or pending_result}")
    snapshot = _run_specimen_pose_snapshot(repo_root, script_path, payload, timeout_sec=timeout_sec)
    return _apply_specimen_pose_snapshot_to_stage(stage, snapshot, red_cube_path)


def _open_gui_stage(scene_path: Path) -> str:
    """Ask Isaac's GUI USD context to open the mirror scene."""
    try:
        import omni.usd  # type: ignore

        context = omni.usd.get_context()
        if context is None:
            return "skipped:no_usd_context"
        result = context.open_stage(str(scene_path))
        return f"requested:{result}"
    except Exception as exc:
        return f"failed:{exc.__class__.__name__}: {exc}"


def _play_timeline() -> str:
    """Start Isaac's timeline so authored physics and drives are stepped."""
    try:
        import omni.timeline  # type: ignore

        timeline = omni.timeline.get_timeline_interface()
        if timeline is None:
            return "skipped:no_timeline"
        try:
            tcps = float(timeline.get_time_codes_per_second())
        except Exception:
            tcps = 60.0
        if not math.isfinite(tcps) or tcps <= 0:
            tcps = 60.0
        min_span_s = max(1.0 / tcps, 0.1)
        try:
            start_time = float(timeline.get_start_time())
        except Exception:
            start_time = 0.0
        try:
            end_time = float(timeline.get_end_time())
        except Exception:
            end_time = start_time
        if not math.isfinite(start_time):
            start_time = 0.0
        if not math.isfinite(end_time):
            end_time = start_time
        if end_time <= start_time + min_span_s:
            end_time = start_time + max(3600.0, min_span_s)
            try:
                timeline.set_end_time(end_time)
            except Exception:
                pass
        try:
            current_time = float(timeline.get_current_time())
        except Exception:
            current_time = start_time
        if not math.isfinite(current_time):
            current_time = start_time
        if current_time < start_time or current_time >= end_time - min_span_s:
            try:
                timeline.set_current_time(start_time)
            except Exception:
                pass
            current_time = start_time
        try:
            timeline.set_auto_update(True)
        except Exception:
            pass
        try:
            timeline.set_looping(True)
        except Exception:
            pass
        timeline.play()
        commit = getattr(timeline, "commit", None)
        if callable(commit):
            try:
                commit()
            except Exception:
                pass
        try:
            playing = bool(timeline.is_playing())
        except Exception:
            playing = True
        try:
            stopped = bool(timeline.is_stopped())
        except Exception:
            stopped = False
        try:
            auto_update = bool(timeline.is_auto_updating())
        except Exception:
            auto_update = True
        return (
            f"playing:{playing};stopped:{stopped};auto_update:{auto_update};"
            f"start:{start_time:.3f};end:{end_time:.3f};current:{current_time:.3f}"
        )
    except Exception as exc:
        return f"failed:{exc.__class__.__name__}: {exc}"


def install_delayed_timeline_play_subscription(
    delay_ticks: int,
    *,
    before_play: Callable[[], dict[str, Any]] | None = None,
) -> Any:
    """Start Isaac's timeline from an update callback after Kit has settled."""
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        stream = app.get_update_event_stream()
        remaining = max(1, int(delay_ticks))
        done = False

        def _on_update(_event: Any) -> None:
            nonlocal remaining, done
            if done:
                return
            remaining -= 1
            if remaining > 0:
                return
            done = True
            if before_play is not None:
                try:
                    before_play_status = before_play()
                except Exception as exc:
                    before_play_status = {
                        "ok": False,
                        "status": "before_play_error",
                        "message": f"Specimen pose before-play hook failed: {exc.__class__.__name__}: {exc}",
                    }
                if bool(before_play_status.get("ok")):
                    _log_info(f"ATR OMX mirror specimen pose status={before_play_status}")
                else:
                    _log_warn(f"ATR OMX mirror specimen pose warning: {before_play_status.get('message') or before_play_status}")
            timeline_status = _play_timeline()
            _log_info(f"ATR OMX mirror delayed timeline status={timeline_status}")

        return stream.create_subscription_to_pop(_on_update, name="atr-isaac-omx-mirror-delayed-play")
    except Exception as exc:
        _log_error(f"ATR OMX mirror delayed timeline subscription failed: {exc.__class__.__name__}: {exc}")
        return None


def install_delayed_update_callback(delay_ticks: int, callback: Callable[[], None], *, name: str) -> Any:
    """Run a callback after a fixed number of Kit update ticks."""
    try:
        import omni.kit.app  # type: ignore

        app = omni.kit.app.get_app()
        stream = app.get_update_event_stream()
        remaining = max(1, int(delay_ticks))
        done = False

        def _on_update(_event: Any) -> None:
            nonlocal remaining, done
            if done:
                return
            remaining -= 1
            if remaining > 0:
                return
            done = True
            callback()

        return stream.create_subscription_to_pop(_on_update, name=name)
    except Exception as exc:
        _log_error(f"ATR OMX mirror delayed callback subscription failed: {exc.__class__.__name__}: {exc}")
        return None


def install_timeline_play_specimen_pose_subscription(
    *,
    before_play: Callable[[], dict[str, Any]] | None = None,
    skip_next_play: Callable[[], bool] | None = None,
    red_cube_path: str = RED_SPECIMEN_BLOCK_PATH,
    post_play_reapply_ticks: int = 5,
) -> Any:
    """Run the specimen pose hook when Isaac's timeline enters PLAY."""
    if before_play is None:
        return None
    try:
        import omni.timeline  # type: ignore

        timeline = omni.timeline.get_timeline_interface()
        if timeline is None:
            return None
        stream = timeline.get_timeline_event_stream()

        def _install_post_timeline_reapply(translate_m: list[float] | tuple[float, float, float], yaw_deg: float | None = None) -> None:
            ticks_remaining = max(0, int(post_play_reapply_ticks))
            if ticks_remaining <= 0:
                return
            try:
                import omni.kit.app  # type: ignore

                app = omni.kit.app.get_app()
                update_stream = app.get_update_event_stream()
            except Exception as exc:
                _log_warn(f"ATR OMX mirror specimen pose post-timeline reapply unavailable: {exc.__class__.__name__}: {exc}")
                return
            subscription_holder: dict[str, Any] = {}

            def _on_update(_event: Any) -> None:
                nonlocal ticks_remaining
                stage = _current_gui_stage()
                if stage is not None:
                    result = _apply_specimen_transform_to_stage(stage, translate_m, red_cube_path, yaw_deg)
                    if not bool(result.get("ok")):
                        _log_warn(f"ATR OMX mirror specimen pose post-timeline reapply warning: {result.get('message') or result}")
                ticks_remaining -= 1
                if ticks_remaining <= 0:
                    subscription_holder["subscription"] = None

            subscription_holder["subscription"] = update_stream.create_subscription_to_pop(
                _on_update,
                name="atr-isaac-omx-mirror-specimen-post-play-reapply",
            )

        def _run_timeline_hook(label: str) -> None:
            try:
                before_play_status = before_play()
            except Exception as exc:
                before_play_status = {
                    "ok": False,
                    "status": f"timeline_{label.lower()}_error",
                    "message": f"Specimen pose timeline {label} hook failed: {exc.__class__.__name__}: {exc}",
                }
            if bool(before_play_status.get("ok")):
                _log_info(f"ATR OMX mirror specimen pose {label} status={before_play_status}")
                translate_m = before_play_status.get("translate_m")
                if isinstance(translate_m, (list, tuple)) and len(translate_m) == 3:
                    orientation = before_play_status.get("orientation_deg") if isinstance(before_play_status.get("orientation_deg"), dict) else {}
                    yaw_deg = _float_from_pose(orientation.get("yaw")) if orientation else None
                    _install_post_timeline_reapply(translate_m, yaw_deg)
            else:
                _log_warn(f"ATR OMX mirror specimen pose {label} warning: {before_play_status.get('message') or before_play_status}")

        def _on_play(_event: Any) -> None:
            if skip_next_play is not None:
                try:
                    if skip_next_play():
                        _log_info("ATR OMX mirror specimen pose PLAY skipped after delayed auto-play pre-apply")
                        return
                except Exception as exc:
                    _log_warn(f"ATR OMX mirror specimen pose PLAY skip check failed: {exc.__class__.__name__}: {exc}")
            _run_timeline_hook("PLAY")

        return stream.create_subscription_to_pop_by_type(int(omni.timeline.TimelineEventType.PLAY), _on_play)
    except Exception as exc:
        _log_error(f"ATR OMX mirror timeline PLAY subscription failed: {exc.__class__.__name__}: {exc}")
        return None


class AtrOmxMirrorExtension(_BaseExtension):
    """Omniverse extension entrypoint for in-process Isaac mirror serving."""

    def __init__(self) -> None:
        super().__init__()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._state: Any | None = None
        self._subscription: Any | None = None
        self._server_start_subscription: Any | None = None
        self._timeline_subscription: Any | None = None
        self._timeline_play_subscription: Any | None = None
        self._endpoint = ""

    def on_startup(self, ext_id: str) -> None:  # noqa: D401 - Isaac extension API name
        """Start the HTTP mirror receiver inside the Isaac Sim process."""
        settings = _settings()
        if not _setting_bool(settings, "/exts/atr.omx.mirror/enabled", True):
            _log_info(f"[{ext_id}] ATR OMX mirror receiver disabled by settings")
            return
        if self._server is not None:
            return

        repo_root = _repo_root_from_extension()
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        from sim.robotis_omx.tools.isaac_omx_mirror_server import (  # pylint: disable=import-outside-toplevel
            DEFAULT_HOST,
            DEFAULT_PORT,
            DEFAULT_SCENE,
            IsaacMirrorState,
            install_kit_update_subscription,
            make_handler,
        )

        host = _setting_string(settings, "/exts/atr.omx.mirror/host", DEFAULT_HOST)
        port = _setting_int(settings, "/exts/atr.omx.mirror/port", DEFAULT_PORT)
        scene_setting = _setting_string(settings, "/exts/atr.omx.mirror/scene", "")
        scene_path = Path(scene_setting).expanduser().resolve() if scene_setting else Path(DEFAULT_SCENE).resolve()
        use_current_stage = _setting_bool(settings, "/exts/atr.omx.mirror/useCurrentStage", True)
        open_scene_on_startup = _setting_bool(settings, "/exts/atr.omx.mirror/openSceneOnStartup", True)
        play_timeline_on_startup = _setting_bool(settings, "/exts/atr.omx.mirror/playTimelineOnStartup", True)
        play_timeline_delay_ticks = _setting_int(settings, "/exts/atr.omx.mirror/playTimelineDelayTicks", 300)
        server_startup_delay_ticks = _setting_int(settings, "/exts/atr.omx.mirror/serverStartupDelayTicks", 0)
        specimen_pose_on_play = _setting_bool(settings, "/exts/atr.omx.mirror/specimenPoseOnPlay", True)
        specimen_pose_script_setting = _setting_string(
            settings,
            "/exts/atr.omx.mirror/specimenPoseScript",
            str(repo_root / "scripts" / "vision" / "run_specimen_pose_snapshot.sh"),
        )
        specimen_pose_script = Path(specimen_pose_script_setting).expanduser()
        if not specimen_pose_script.is_absolute():
            specimen_pose_script = (repo_root / specimen_pose_script).resolve()
        specimen_pose_timeout_sec = _setting_float(settings, "/exts/atr.omx.mirror/specimenPoseTimeoutSec", 8.0)
        specimen_pose_camera_startup_timeout_sec = _setting_float(settings, "/exts/atr.omx.mirror/specimenPoseCameraStartupTimeoutSec", 2.0)
        specimen_pose_confidence_threshold = _setting_float(settings, "/exts/atr.omx.mirror/specimenPoseConfidenceThreshold", 0.05)
        specimen_pose_post_play_reapply_ticks = _setting_int(settings, "/exts/atr.omx.mirror/specimenPosePostPlayReapplyTicks", 5)
        specimen_pose_red_cube_path = _setting_string(settings, "/exts/atr.omx.mirror/specimenPoseRedCubePath", RED_SPECIMEN_BLOCK_PATH)
        specimen_pose_payload: dict[str, Any] = {
            "specimen_id": _setting_string(settings, "/exts/atr.omx.mirror/specimenPoseSpecimenId", "redcube-play"),
            "output_dir": _setting_string(settings, "/exts/atr.omx.mirror/specimenPoseOutputDir", str(repo_root / "runs" / "specimen_pose_tracker")),
            "pending_pose_path": _setting_string(settings, "/exts/atr.omx.mirror/specimenPosePendingPath", DEFAULT_PENDING_SPECIMEN_POSE_PATH),
            "active_robot_cam_trigger": _setting_bool(settings, "/exts/atr.omx.mirror/specimenPoseActiveRobotCamOnMissing", False),
            "active_robot_cam_request_path": _setting_string(settings, "/exts/atr.omx.mirror/activeRobotCamRequestPath", DEFAULT_ACTIVE_ROBOT_CAM_REQUEST_PATH),
            "active_robot_cam_wait_timeout_s": _setting_float(settings, "/exts/atr.omx.mirror/activeRobotCamWaitTimeoutSec", 12.0),
            "timeout_sec": specimen_pose_timeout_sec,
            "camera_startup_timeout_sec": specimen_pose_camera_startup_timeout_sec,
            "confidence_threshold": specimen_pose_confidence_threshold,
            "autostart_realsense": _setting_bool(settings, "/exts/atr.omx.mirror/specimenPoseAutostartRealsense", False),
            "realsense_serial": _setting_string(settings, "/exts/atr.omx.mirror/specimenPoseRealsenseSerial", "341522300873"),
        }
        frame_manifest = _setting_string(settings, "/exts/atr.omx.mirror/specimenPoseFrameManifest", "/tmp/atr_lerobot_latest_frame/latest_frame.json")
        if frame_manifest:
            specimen_pose_payload["frame_manifest_path"] = frame_manifest
        for setting_key, payload_key in (
            ("/exts/atr.omx.mirror/specimenPoseCameraId", "camera_id"),
            ("/exts/atr.omx.mirror/specimenPoseColorTopic", "color_topic"),
            ("/exts/atr.omx.mirror/specimenPoseDepthTopic", "depth_topic"),
            ("/exts/atr.omx.mirror/specimenPoseInfoTopic", "info_topic"),
        ):
            value = _setting_string(settings, setting_key, "")
            if value:
                specimen_pose_payload[payload_key] = value
        if use_current_stage and open_scene_on_startup:
            open_status = _open_gui_stage(scene_path)
            _log_info(f"[{ext_id}] ATR OMX mirror requested GUI stage scene={scene_path} status={open_status}")

        def timeline_play_callback(*, reason: str = "") -> dict[str, Any]:
            status = _play_timeline()
            return {
                "ok": not status.startswith("failed:"),
                "status": status,
                "reason": reason,
            }

        self._state = IsaacMirrorState(
            scene_path,
            use_current_stage=use_current_stage,
            timeline_play_callback=timeline_play_callback,
        )
        self._subscription = install_kit_update_subscription(self._state)
        before_play = None
        delayed_play_skip_until = {"deadline": 0.0}
        if specimen_pose_on_play:
            def before_play() -> dict[str, Any]:
                return _run_and_apply_specimen_pose_snapshot(
                    repo_root,
                    specimen_pose_script,
                    specimen_pose_payload,
                    timeout_sec=specimen_pose_timeout_sec,
                    red_cube_path=specimen_pose_red_cube_path,
                )

            def skip_next_timeline_play() -> bool:
                deadline = float(delayed_play_skip_until.get("deadline") or 0.0)
                delayed_play_skip_until["deadline"] = 0.0
                return bool(deadline and time.monotonic() <= deadline)

            self._timeline_play_subscription = install_timeline_play_specimen_pose_subscription(
                before_play=before_play,
                skip_next_play=skip_next_timeline_play,
                red_cube_path=specimen_pose_red_cube_path,
                post_play_reapply_ticks=specimen_pose_post_play_reapply_ticks,
            )
        if play_timeline_on_startup:
            delayed_before_play = None
            if before_play is not None:
                def delayed_before_play() -> dict[str, Any]:
                    result = before_play()
                    delayed_play_skip_until["deadline"] = time.monotonic() + 3.0
                    return result

            self._timeline_subscription = install_delayed_timeline_play_subscription(
                play_timeline_delay_ticks,
                before_play=delayed_before_play,
            )
        def start_receiver() -> None:
            if self._server is not None or self._state is None:
                return
            try:
                self._server = ThreadingHTTPServer((host, port), make_handler(self._state))
                self._thread = threading.Thread(target=self._server.serve_forever, name="atr-isaac-omx-mirror", daemon=True)
                self._thread.start()
                self._endpoint = f"http://{host}:{port}/joints"
                mode = self._state.status_payload().get("apply_mode", "unknown")
                _log_info(f"[{ext_id}] ATR OMX mirror receiver listening at {self._endpoint} apply_mode={mode}")
            except Exception as exc:
                _log_error(f"[{ext_id}] ATR OMX mirror receiver failed to start: {exc.__class__.__name__}: {exc}")

        if server_startup_delay_ticks > 0:
            self._server_start_subscription = install_delayed_update_callback(
                server_startup_delay_ticks,
                start_receiver,
                name="atr-isaac-omx-mirror-delayed-server-start",
            )
            _log_info(f"[{ext_id}] ATR OMX mirror receiver start delayed ticks={server_startup_delay_ticks}")
        else:
            start_receiver()

    def on_shutdown(self) -> None:
        """Stop the in-process mirror receiver."""
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        self._subscription = None
        self._server_start_subscription = None
        self._timeline_subscription = None
        self._timeline_play_subscription = None
        self._state = None
        endpoint = self._endpoint
        self._endpoint = ""
        if server is not None:
            try:
                server.shutdown()
            except Exception as exc:  # pragma: no cover - best effort cleanup
                _log_error(f"ATR OMX mirror receiver shutdown failed: {exc}")
            try:
                server.server_close()
            except Exception:
                pass
        if thread is not None:
            thread.join(timeout=2.0)
        if endpoint:
            _log_info(f"ATR OMX mirror receiver stopped at {endpoint}")
