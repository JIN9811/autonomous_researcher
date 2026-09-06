"""Keep a long-running robot stream attached to its originating agent attempt."""
from pathlib import Path
import json
import logging

from utils.agent_artifact_archive import current_execution, _json, _error


def resolve_rollout_log(legacy: Path, *, run_root: Path | None = None) -> Path:
    legacy = Path(legacy)
    try:
        marker = json.loads((legacy / "artifact_location.json").read_text())
        # The root comes from trusted application configuration, never the marker.
        root = Path(run_root).resolve() if run_root is not None else legacy.parent.parent.resolve()
        target = (root / marker["path"]).resolve()
        relative = target.relative_to(root)
        if len(relative.parts) != 8 or relative.parts[1:3] != ("runtime", "loops"):
            return legacy
        if relative.parts[-2] != "streams" or relative.parts[-1] != legacy.name:
            return legacy
        if not (target / "session.json").is_file():
            return legacy
        return target
    except (OSError, ValueError, KeyError, TypeError):
        return legacy


def bind_rollout_log(legacy: Path) -> Path:
    """Write only a compatibility locator; raw bytes go straight into run artifacts."""
    execution = current_execution()
    if execution is None or legacy.parent.name == "streams":
        return legacy
    target = None
    try:
        legacy = Path(legacy)
        existing = resolve_rollout_log(legacy, run_root=execution.run_root)
        if existing != legacy:
            return existing
        target = execution.directory / "streams" / legacy.name
        relative = target.resolve().relative_to(execution.run_root)
        target.mkdir(parents=True, exist_ok=True)
        legacy.mkdir(parents=True, exist_ok=True)
        _json(target / "session.json", {"session_id": legacy.name, "status": "STARTING",
              "workflow": "rollout", "artifact_execution": execution.descriptor()})
        _json(legacy / "artifact_location.json", {"path": relative.as_posix()})
        return target
    except (OSError, ValueError) as exc:
        execution.errors.append("rollout_binding_" + type(exc).__name__)
        _error(execution.state, exc)
        if target is not None and (target / "session.json").is_file():
            try:
                _json(target / "session.json", {"session_id": legacy.name, "status": "FAILED",
                      "tracking_artifacts": {"ok": False, "error": "rollout_binding_failed"}})
            except OSError:
                pass
        return legacy


def update_rollout_artifact(directory: Path, session: dict) -> None:
    """A bridge status/stop observation finalizes evidence without a GUI subscriber."""
    path = Path(directory) / "session.json"
    if not path.is_file():
        return
    try:
        saved = json.loads(path.read_text())
        if saved.get("session_id") != session.get("session_id"):
            return
        for key in ("status", "workflow", "mode", "profile_id", "policy_type", "created_at", "updated_at"):
            if key in session:
                saved[key] = session[key]
        terminal = str(session.get("status", "")).upper() in {"STOPPED", "COMPLETED", "FAILED", "CANCELLED"}
        if terminal:
            from utils.lerobot_joint_telemetry import finalize_policy_tracking_artifacts
            saved["tracking_artifacts"] = finalize_policy_tracking_artifacts(directory / "motor_events.jsonl", session)
        _json(path, saved)
    except Exception as exc:
        logging.getLogger(__name__).warning("Rollout artifact finalization incomplete: %s", type(exc).__name__)
