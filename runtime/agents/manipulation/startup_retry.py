"""Owner-scoped startup recovery. No direct starts, homing, or capture commands."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from agents.base_agent import AgentResult


def _scope(state):
    spec = state.current_experiment_spec
    return {"run_id": state.run_id, "loop_id": state.loop_count,
            "specimen_id": spec.get("specimen_id") or (state.run_metadata.get("specimen_result") or {}).get("specimen_id"),
            "spec_hash": hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()}


def _stopped(state):
    return any(getattr(state, flag, False) for flag in
               ("stop_requested", "safe_stop_requested", "emergency_stop_requested"))


def _admission(state):
    record = (getattr(state, "run_metadata", None) or {}).get("manipulation_vision_admission") or {}
    if record and _stopped(state):
        record["revoked"] = True
    if not record or record.get("revoked") or record.get("scope") != _scope(state):
        return {}
    return record


def held_vision_freshness(state):
    """Original capture timestamps stay immutable; this is a task admission lease."""
    record = _admission(state)
    if not record or record.get("observation") != state.latest_observations:
        return None
    if record.get("policy_start_observed_at"):
        expires_at = record.get("execution_expires_at", "")
        try:
            fresh = datetime.fromisoformat(expires_at) > datetime.now(timezone.utc)
        except (TypeError, ValueError):
            fresh = False
        return {"fresh": fresh, "reason": "execution_window" if fresh else "stale_vision_signal",
                "expires_at": expires_at, "validity_anchor": "first_policy_action",
                "capture_timestamp_unchanged": True}
    return {"fresh": True, "reason": "admitted_waiting_for_policy_start",
            "admitted_at": record["admitted_at"], "validity_anchor": "first_policy_action",
            "expires_at": "", "capture_timestamp_unchanged": True}


def admit_vision(state, session_id, *, bind_session=False):
    """Caller must pass the normal preflight before admitting the original evidence."""
    record = _admission(state)
    if record and record.get("observation") == state.latest_observations:
        if bind_session:
            record["session_id"] = session_id
        return
    state.run_metadata["manipulation_vision_admission"] = {
        "scope": _scope(state), "session_id": session_id,
        "admitted_at": datetime.now(timezone.utc).isoformat(),
        "observation": deepcopy(state.latest_observations),
        "validity_anchor": "first_policy_action", "policy_start_observed_at": None,
    }


def _terminal(status, session_id):
    code = status.get("returncode")
    return (status.get("ok") is True and status.get("session_id") == session_id
            and status.get("status") == "FAILED" and isinstance(code, int)
            and not isinstance(code, bool) and code != 0)


def _safe_startup_failure(status, execution):
    runtime = status.get("runtime") or {}
    telemetry = status.get("joint_telemetry") or {}
    packet = telemetry.get("packet") or {}
    return (runtime.get("failed_before_policy_start") is True
            and runtime.get("action_count") == 0 and not execution.get("observed")
            and execution.get("action_count", 0) == 0
            and not packet.get("sequence") and not packet.get("actual_source"))


def _blocked(record, code="MANIPULATION_ROLLOUT_FAILED"):
    return AgentResult(success=False, summary="Manipulation rollout failed; owner review required",
        data={"failure_code": code, "safe_stop_recommended": True,
              "manipulation_startup_retry": deepcopy(record)})


def observe_rollout(state, status, execution):
    """Vision reports a dead async skill to MAN instead of waiting for impossible home."""
    previous = state.run_metadata.get("manipulation_result") or {}
    session_id = previous.get("session_id")
    admission = _admission(state)
    if (admission and admission.get("session_id") == status.get("session_id") == session_id
            and execution.get("observed") and not admission.get("policy_start_observed_at")):
        now = datetime.now(timezone.utc)
        admission["policy_start_observed_at"] = now.isoformat()
        # Execution admission and camera age are separate facts; never rewrite
        # producer expires_at/captured_at or manufacture a new image timestamp.
        from agents.vision.agent import VisionAgent
        admission["execution_expires_at"] = (now + timedelta(milliseconds=VisionAgent.SIGNAL_TTL_MS)).isoformat()
    if not session_id or not _terminal(status, session_id):
        return None
    record = {"schema": "manipulation_startup_retry.v1", "scope": _scope(state),
              "session_id": session_id, "status": "review_required",
              "execution": deepcopy(execution), "runtime": deepcopy(status.get("runtime") or {}),
              "returncode": status.get("returncode"), "log_path": status.get("log_path")}
    can_retry = (not _stopped(state) and admission and admission.get("session_id") == session_id
                 and not admission.get("policy_start_observed_at") and _safe_startup_failure(status, execution))
    record["status"] = "owner_review" if can_retry else "review_required"
    state.run_metadata["manipulation_startup_retry"] = record
    from utils.manipulation_execution import sync_manipulation_execution_status
    from orchestrator.state import Stage
    sync_manipulation_execution_status(state, Stage.VISION, failed=True)
    if not can_retry:
        return _blocked(record)
    return AgentResult(success=True, summary="Rollout startup failed; returning to Manipulation owner",
        data={"requested_next_stage": "manipulation", "transition_decision": "manipulation_startup_retry",
              "manipulation_startup_retry": deepcopy(record)}, next_hint="manipulation")


async def prepare_retry(state, ctx):
    """Revalidate a terminal failure; grant a single claim through the normal MAN path."""
    record = state.run_metadata.get("manipulation_startup_retry") or {}
    if record.get("status") not in {"owner_review", "ready"}:
        return None
    old_scope = record.get("scope") or {}
    if old_scope.get("run_id") != state.run_id or old_scope.get("loop_id") != state.loop_count:
        return None  # Historical retries do not control another run/cycle.
    admission = _admission(state)
    if (record.get("scope") != _scope(state) or not admission
            or admission.get("session_id") != record.get("session_id")
            or admission.get("policy_start_observed_at")):
        return _blocked(record, "MANIPULATION_RETRY_SCOPE_CHANGED")
    observation = state.latest_observations
    observation_snapshot = deepcopy(observation)
    completion = observation.get("vision_manipulation_completion") or {}
    if observation != admission.get("observation") and not (
        completion.get("session_id") == record["session_id"]
        and completion.get("run_id") == state.run_id and completion.get("loop_id") == state.loop_count
        and completion.get("specimen_id") == record["scope"]["specimen_id"]
        and completion.get("detected") is False
    ):
        return _blocked(record, "MANIPULATION_RETRY_VISION_CHANGED")
    previous = state.run_metadata.get("manipulation_result") or {}
    payload = {"session_id": record["session_id"], "mode": state.mode.value,
               "runtime_mode": previous.get("runtime_mode") or previous.get("mode") or state.mode.value,
               "profile_id": previous.get("profile_id", "")}
    import asyncio
    try:
        status = await asyncio.to_thread(ctx.tools.call, "lerobot.rollout.status", payload)
    except Exception:
        return _blocked(record, "MANIPULATION_RETRY_STATUS_UNAVAILABLE")
    # The status read is asynchronous: scope/stop must be checked again afterwards.
    if (not _admission(state) or record.get("scope") != _scope(state)
            or state.latest_observations != observation_snapshot
            or not _terminal(status, record["session_id"])
            or not _safe_startup_failure(status, record["execution"])):
        return _blocked(record, "MANIPULATION_RETRY_NOT_CONFIRMED")
    attempts = state.run_metadata.get("manipulation_skill_attempts") or {}
    attempt = next((a for a in attempts.values() if a.get("session_id") == record["session_id"]
                    and a.get("run_id") == state.run_id and a.get("loop_id") == state.loop_count
                    and a.get("task_id") == "transfer_to_utm"), None)
    from utils.config_loader import load_yaml
    default_limit = load_yaml(Path(__file__).resolve().parents[2] / "configs/system.yaml")["system"]["max_retry_per_stage"]
    config = ctx.runtime_module_config() if callable(getattr(ctx, "runtime_module_config", None)) else {}
    limit = (config.get("retry") or {}).get("max_attempts", default_limit)
    if not attempt or len(attempt.get("history", [])) >= int(limit):
        return _blocked(record, "MANIPULATION_STARTUP_RETRY_EXHAUSTED")
    attempt["retry_ready"] = True
    attempt["failure"] = deepcopy(record)
    record["status"] = "ready"
    state.latest_observations = deepcopy(admission["observation"])
    for name in ("manipulation_result", "robot_task_result"):
        current = state.run_metadata.get(name)
        if isinstance(current, dict):
            current.update(status="FAILED", handoff_status="startup_retry_ready", completion_status="startup_failed")
    return None
