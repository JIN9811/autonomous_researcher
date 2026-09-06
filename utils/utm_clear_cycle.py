"""Identity-scoped UTM disposal handoff. No motion outside managed replay tools."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import asyncio
import time
import os
import math
from pathlib import Path
from urllib.parse import quote
from typing import Any

from orchestrator.state import Stage

TASK_ID = "clear_utm_to_disposal"


def scope(state) -> dict[str, Any]:
    return {"run_id": state.run_id, "loop_id": int(state.loop_count),
            "specimen_id": str(state.current_experiment_spec.get("specimen_id") or "")}


def matches(state, value: Any) -> bool:
    return isinstance(value, dict) and all(value.get(k) == v for k, v in scope(state).items())


def current_clear(state) -> dict[str, Any]:
    value = state.run_metadata.get("utm_clear_execution")
    return value if matches(state, value) else {}


def clearance_missing(state) -> bool:
    execution = current_clear(state)
    requirement = state.run_metadata.get("utm_clear_requirement")
    verifications = state.run_metadata.get("utm_verifications", {})
    second = verifications.get("verification_2", {}) if matches(state, verifications) else {}
    return bool((execution or matches(state, requirement)) and not (execution.get("success") is True and second.get("confirmed") is True))


def merge_utm_clear_cycle(state, stage: Stage, data: dict[str, Any]) -> None:
    """Consume only this invocation's payload; never rearm a scoped terminal task."""
    metadata = state.run_metadata
    verifications = metadata.get("utm_verifications", {})
    if not matches(state, verifications):
        verifications = {**scope(state)}
        metadata["utm_verifications"] = verifications
        metadata.pop("utm_clear_execution", None)
        metadata.pop("utm_clear_next_stage", None)
        if not matches(state, metadata.get("utm_clear_requirement")):
            metadata.pop("utm_clear_requirement", None)
    if stage == Stage.VISION:
        completion = (data.get("observation") or {}).get("vision_manipulation_completion", {})
        artifact = data.get("utm_completion_artifact_update", {})
        if matches(state, completion) and "verification_1" not in verifications:
            verified = bool(completion.get("detected") is True and completion.get("rollout_stopped") is True
                and completion.get("rollout_stop_status") == "STOPPED"
                and (completion.get("post_place_interlock") or {}).get("ready_for_utm_snapshot") is True
                and not completion.get("blocking_reason"))
            # The first placement record remains independent of all disposal observations.
            verifications["verification_1"] = {
                "verification_index": 1, "status": "confirmed" if verified else "pending",
                "confirmed": verified, "captured_at": artifact.get("captured_at", ""),
                "artifact": deepcopy(artifact), "evidence": deepcopy(completion),
            }
        elif matches(state, completion) and not verifications.get("verification_1", {}).get("confirmed"):
            verifications.pop("verification_1", None)
            merge_utm_clear_cycle(state, stage, data)
        update = data.get("utm_verification_2")
        execution = current_clear(state)
        if matches(state, update) and execution and update.get("session_id") == execution.get("session_id"):
            verifications["verification_2"] = deepcopy(update["record"])
    if stage == Stage.EQUIPMENT:
        result, packet, export = (data.get(k) or {} for k in ("equipment_result", "utm_data_ready", "raw_data_export"))
        readiness = data.get("next_specimen_readiness") or {}
        handoff = data.get("equipment_handoff") or {}
        contradictory = any(key in item and item[key] != expected
            for item in (result, packet, export, handoff)
            for key, expected in scope(state).items())
        identity = all(item.get("run_id") == state.run_id and item.get("specimen_id") == scope(state)["specimen_id"]
                       for item in (result, packet, export))
        ready = (identity and not contradictory and result.get("ok") is True and result.get("status") == "verified_complete"
                 and packet.get("status") == "ready" and export.get("validated") is True
                 and (data.get("handoff_eligibility") or {}).get("eligible") is True
                 and readiness.get("clearance_restored") is True and readiness.get("next_test_completed") is True
                 and verifications.get("verification_1", {}).get("confirmed") is True)
        # A contradictory completion claim must block the current transition,
        # not opt out of clearance merely because its asserted identity is wrong.
        required = (result.get("status") == "verified_complete" or handoff.get("status") == "ready_for_analysis"
                    or handoff.get("ready_for_analysis") is True or packet.get("status") == "ready")
        existing = current_clear(state)
        if existing and required and contradictory:
            existing.update(state="error", success=False, failure_code="UTM_CLEAR_HANDOFF_IDENTITY_MISMATCH")
        if (ready or required) and not existing:
            metadata["utm_clear_requirement"] = {**scope(state), "required": True, "task_id": TASK_ID}
            token = hashlib.sha256(repr(tuple(scope(state).values())).encode()).hexdigest()[:20]
            metadata["utm_clear_execution"] = {**scope(state), "session_id": f"utm-clear-{token}",
                "task_id": TASK_ID, "state": "requested" if ready else "error", "success": None if ready else False}
            if not ready:
                metadata["utm_clear_execution"]["failure_code"] = (
                    "UTM_CLEAR_HANDOFF_IDENTITY_MISMATCH" if contradictory else "UTM_CLEAR_HANDOFF_PREREQUISITES_MISSING")
            metadata["initial_manipulation_execution"] = deepcopy(metadata.get("manipulation_execution", {}))
    update = data.get("utm_clear_execution")
    execution = current_clear(state)
    if execution and matches(state, update) and update.get("session_id") == execution.get("session_id"):
        execution.update(deepcopy(update))
    execution = current_clear(state)
    if execution:
        metadata["utm_clear_next_stage"] = (
            "manipulation" if stage == Stage.EQUIPMENT and execution.get("state") == "requested"
            else "analysis" if execution.get("success") is True and not clearance_missing(state)
            else "vision")
        sync_clear_status(state)


def sync_clear_status(state, *, failed=False):
    from orchestrator.state import AgentRuntimeStatus
    execution = current_clear(state)
    if not execution:
        return
    if failed:
        execution.update(state="error", success=False)
    status = state.agent_status.setdefault("manipulation_agent", AgentRuntimeStatus(mode=state.mode.value))
    status.state = {"requested": "waiting", "starting": "running"}.get(execution["state"], execution["state"])
    status.success = execution.get("success")
    status.last_result = "UTM disposal and empty fixture verified" if execution.get("success") else "UTM disposal / clearance verification pending"


def _result(execution, *, capture=None, summary="UTM clear verification pending"):
    from agents.base_agent import AgentResult
    done = execution.get("success") is True
    data = {"utm_clear_execution": deepcopy(execution),
            "requested_next_stage": "analysis" if done else "vision",
            "observation": {"utm_clear_verification": deepcopy(capture or {}), "specimen_id": execution["specimen_id"]}}
    if capture is not None:
        artifact = {k: capture.get(k, "") for k in ("raw_frame_path", "annotated_frame_path", "evidence_path")}
        artifact["path"] = artifact["annotated_frame_path"] or artifact["raw_frame_path"]
        artifact["url"] = capture.get("artifact_url", "")
        data["utm_verification_2"] = {**{k: execution[k] for k in ("run_id", "loop_id", "specimen_id", "session_id")},
            "record": {"verification_index": 2, "status": capture.get("status", "unknown"),
                       "confirmed": done, "captured_at": capture.get("captured_at", ""),
                       "artifact": artifact, "evidence": deepcopy(capture)}}
    if execution.get("state") == "error":
        data["failure_code"] = execution.get("failure_code") or "UTM_CLEARANCE_REQUIRED"
    return AgentResult(success=execution.get("state") != "error", summary=summary, data=data,
                       next_hint=data["requested_next_stage"])


def _explicit_virtual(state):
    policy = state.current_experiment_spec.get("execution_policy") or {}
    return all(policy.get(k) in {"virtual", "simulate", "simulation"} for k in ("manipulation", "vision", "lab_equipment"))


def _physical_execution(state):
    from agents.manipulation_agent import ManipulationAgent
    return state.mode.value == "live" or ManipulationAgent._physical_printer_tail_requested(state)


def _execution_allowed(state, agent):
    policy = state.current_experiment_spec.get("execution_policy") or {}
    return policy.get(agent) == "execute" if agent in policy else _physical_execution(state)


def clear_poll_pending(state):
    """Only this scoped, time-bounded child can consume polling (not stage) visits."""
    execution = current_clear(state)
    return bool(execution and execution.get("state") in {"starting", "running", "waiting"}
                and execution.get("pending_deadline_at"))


def _bind_pending_deadline(execution, response):
    if execution.get("pending_deadline_at"):
        return
    try:
        replay_bound = float(response.get("replay_max_duration_s", 0))
    except (TypeError, ValueError):
        return
    if not math.isfinite(replay_bound) or replay_bound <= 0:
        return
    # One runner time budget and one same-sized observation budget, fixed once
    # per child. This derives from the accepted recording's effective timeout,
    # never a frame count or an arbitrary number of graph visits.
    started = execution.setdefault("pending_started_at", time.time())
    execution.update(replay_max_duration_s=replay_bound, pending_timeout_s=2 * replay_bound,
                     pending_deadline_at=started + 2 * replay_bound)


async def stop_pending_clear(state, ctx, *, reason):
    """Bounded, idempotent cleanup of the owned child; never retry replay.start."""
    execution = current_clear(state)
    if not execution:
        return
    if execution.get("state") == "done" and execution.get("success") is True:
        return
    active = execution.get("state") in {"starting", "running", "waiting"} and not execution.get("simulated")
    if active and not execution.get("replay_home_verified") and not execution.get("stop_attempted"):
        execution["stop_attempted"] = True
        payload = {**scope(state), "session_id": execution["session_id"],
                   "mode": state.mode.value, "runtime_mode": execution.get("runtime_mode", state.mode.value)}
        try:
            execution["stop_result"] = await asyncio.to_thread(ctx.tools.call, "lerobot.replay.stop", payload)
        except Exception as exc:
            execution["stop_result"] = {"ok": False, "message": str(exc)}
    execution.update(state="error", success=False, failure_code=reason)
    sync_clear_status(state)


async def run_clear_manipulation(state, ctx, *, spec):
    execution = current_clear(state)
    if execution.get("state") == "done" and execution.get("success") is True:
        return _result(execution)
    if any(getattr(state, flag, False) for flag in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
        execution.update(state="error", success=False, failure_code="UTM_CLEAR_OPERATOR_STOPPED")
        return _result(execution)
    if execution.get("state") != "requested":
        return _result(execution)
    policy = state.current_experiment_spec.get("execution_policy") or {}
    if _explicit_virtual(state):
        execution.update(state="waiting", simulated=True, success=None, replay_completed_at=time.time(),
                         replay_home_verified=True, replay_evidence={"simulated": True, "actuation_performed": False})
        return _result(execution, summary="Explicitly simulated clearance; no replay actuation")
    if not _execution_allowed(state, "manipulation") or not _execution_allowed(state, "lab_equipment"):
        execution.update(state="error", success=False, failure_code="UTM_CLEAR_MANUAL_CLEARANCE_REQUIRED")
        return _result(execution)
    root = Path(str(spec.get("lerobot_dataset_root") or spec.get("dataset_root")
                    or os.environ.get("HF_LEROBOT_HOME") or Path.home() / ".cache/huggingface/lerobot")).expanduser()
    runtime_mode = "live" if _physical_execution(state) else state.mode.value
    confirmation = spec.get("confirm_live_execute", spec.get("confirm_manipulation_execute", runtime_mode == "live"))
    payload = {**scope(state), "session_id": execution["session_id"], "dataset_repo_id": "jin/utm_clear",
        "dataset_path": str(root / "jin/utm_clear"), "replay_episode": 0, "mode": state.mode.value, "runtime_mode": runtime_mode,
        "profile_id": spec.get("lerobot_profile_id") or spec.get("robot_profile_id") or spec.get("profile_id") or "",
        "confirm_live_execute": confirmation is True}
    execution["runtime_mode"] = runtime_mode
    # Persist attempted ownership before crossing the effectful boundary, including exceptions.
    execution.update(state="starting", success=None, started_at=datetime.now(timezone.utc).isoformat(), pending_started_at=time.time())
    try:
        response = await asyncio.to_thread(ctx.tools.call, "lerobot.replay.start", payload)
    except Exception as exc:
        response = {"ok": False, "failure_code": "UTM_CLEAR_REPLAY_START_FAILED", "message": str(exc)}
    valid = matches(state, response) and response.get("session_id") == execution["session_id"]
    if not response.get("ok") or not valid:
        execution.update(state="error", success=False, failure_code=response.get("failure_code") or "UTM_CLEAR_REPLAY_IDENTITY_MISMATCH")
    else:
        execution.update(state="running", replay_status=response.get("status"))
        _bind_pending_deadline(execution, response)
    return _result(execution)


async def run_clear_vision(state, ctx, *, artifact_dir):
    execution = current_clear(state)
    if any(getattr(state, flag, False) for flag in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
        await stop_pending_clear(state, ctx, reason="UTM_CLEAR_OPERATOR_STOPPED")
        return _result(execution)
    if execution.get("state") in {"error", "requested", "done"}:
        return _result(execution)
    if clear_poll_pending(state):
        remaining = execution["pending_deadline_at"] - time.time()
        if remaining <= 0:
            await stop_pending_clear(state, ctx, reason="UTM_CLEAR_PENDING_TIMEOUT")
            return _result(execution)
        await asyncio.sleep(min(0.25, remaining))
        if any(getattr(state, flag, False) for flag in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
            await stop_pending_clear(state, ctx, reason="UTM_CLEAR_OPERATOR_STOPPED")
            return _result(execution)
        if time.time() >= execution["pending_deadline_at"]:
            await stop_pending_clear(state, ctx, reason="UTM_CLEAR_PENDING_TIMEOUT")
            return _result(execution)
    if execution.get("simulated") is True:
        if not _explicit_virtual(state):
            execution.update(state="error", success=False, failure_code="UTM_CLEAR_SIMULATION_SCOPE_CHANGED")
            return _result(execution)
        capture = {"ok": True, "status": "clear", "detected": False, "clear_confirmed": True,
                   "simulated": True, "actuation_performed": False, "captured_at": datetime.now(timezone.utc).isoformat()}
        execution.update(state="done", success=True)
        return _result(execution, capture=capture, summary="Simulated empty fixture verified (not physical evidence)")
    policy = state.current_experiment_spec.get("execution_policy") or {}
    if not _execution_allowed(state, "vision"):
        execution.update(state="error", success=False, failure_code="UTM_CLEAR_PHYSICAL_VISION_REQUIRED")
        return _result(execution)
    identity = {**scope(state), "session_id": execution["session_id"], "mode": state.mode.value,
                "runtime_mode": execution.get("runtime_mode", "live" if _physical_execution(state) else state.mode.value)}
    try:
        replay = await asyncio.to_thread(ctx.tools.call, "lerobot.replay.status", identity)
    except Exception as exc:
        replay = {"ok": False, "message": str(exc)}
    valid = matches(state, replay) and replay.get("session_id") == execution["session_id"]
    if valid:
        _bind_pending_deadline(execution, replay)
    status = str(replay.get("status") or "").upper()
    if not replay.get("ok") or not valid or status in {"STOPPED", "FAILED", "ERROR"}:
        execution.update(state="error", success=False, failure_code="UTM_CLEAR_REPLAY_FAILED_OR_STOPPED")
        return _result(execution)
    if status != "COMPLETED":
        return _result(execution)
    if replay.get("exit_code") != 0 or replay.get("replay_home_verified") is not True or not replay.get("replay_evidence"):
        execution.update(state="error", success=False, failure_code="UTM_CLEAR_MEASURED_RETURN_REQUIRED")
        return _result(execution)
    execution.setdefault("replay_completed_at", time.time())
    execution.update(state="waiting", replay_home_verified=True, replay_evidence=deepcopy(replay["replay_evidence"]))
    first = state.run_metadata["utm_verifications"].get("verification_1", {})
    evidence = first.get("evidence") or {}
    artifact = first.get("artifact") or {}
    red = first.get("confirmed") is True and (
        evidence.get("detector") == "high_chroma_red_hsv_largest_component"
        or artifact.get("detector") == "high_chroma_red_hsv_largest_component")
    payload = {**identity, "runtime_mode": "live", "purpose": "utm_clear_verification", "auto_start_runtime": False,
        "allow_virtual_bridge_in_test": False, "material": "high_chroma_red" if red else "unknown",
        "after_timestamp": execution["replay_completed_at"], "output_dir": str(artifact_dir), "frame_attempts": 1}
    try:
        capture = await asyncio.to_thread(ctx.tools.call, "vision.utm_specimen_presence.capture", payload)
    except Exception as exc:
        capture = {"ok": False, "status": "unknown", "clear_confirmed": False, "message": str(exc)}
    try:
        fresh = execution["replay_completed_at"] < float(capture.get("frame_timestamp", 0)) <= time.time() + 1
    except (TypeError, ValueError):
        fresh = False
    from utils.utm_specimen_presence import UTM_CLEAR_CAMERA_TOPICS
    confirmed = bool(red and fresh and matches(state, capture) and capture.get("session_id") == execution["session_id"]
        and capture.get("ok") is True and capture.get("clear_confirmed") is True and capture.get("detected") is False
        and capture.get("status") == "clear" and capture.get("registered") is True
        and capture.get("topic") in UTM_CLEAR_CAMERA_TOPICS and capture.get("camera_profile_id") == "camera_utm_primary"
        and not capture.get("virtualized"))
    if not confirmed and capture.get("status") == "clear":
        capture = {**capture, "status": "unknown", "clear_confirmed": False}
    execution.update(state="done" if confirmed else "waiting", success=True if confirmed else None)
    path = capture.get("annotated_frame_path") or capture.get("raw_frame_path")
    if path:
        try:
            relative = Path(path).resolve().relative_to(Path("runs", state.run_id).resolve()).as_posix()
            capture["artifact_url"] = f"/api/runs/{quote(state.run_id, safe='')}/artifact-file/{quote(relative, safe='/')}"
        except ValueError:
            pass
    return _result(execution, capture=capture, summary="UTM clearance verified" if confirmed else "UTM clearance remains unverified")
