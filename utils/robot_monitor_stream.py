"""Read saved robot samples; never import a bridge or issue device commands."""
from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.websockets import WebSocketDisconnect

from utils.lerobot_joint_telemetry import (
    JointTelemetryFileObserver, TELEMETRY_SCHEMA, TERMINAL_SESSION_STATUSES,
    build_joint_telemetry_batch, session_status_label,
)


async def stream_robot_samples(socket, *, context, reset, public_session, runtime_view, artifacts, publisher_fresh=lambda: True):
    await socket.accept()
    observer = JointTelemetryFileObserver(preserve_history=True)
    compact = socket.query_params.get("sample_format") == "compact-v1"
    active = None
    history_sent = False
    signature = None
    finalized = False
    latest = None
    try:
        while True:
            reset_ms = reset()
            selected = context()
            session = dict(selected["session"]) if selected else {}
            identity = (reset_ms, str(session.get("session_id") or ""))
            if identity != active:
                observer.reset()
                active, history_sent, signature, finalized, latest = identity, False, None, False, None
            status = session_status_label(session.get("status"))
            packets = await asyncio.to_thread(observer.poll, Path(selected["log_path"]), session) if selected else []
            if selected and status == "idle":
                status = "live" if packets else "waiting"
            if packets:
                latest = packets[-1]
            fresh = publisher_fresh()
            if selected and not fresh and str(session.get("status") or "").upper() not in TERMINAL_SESSION_STATUSES:
                status = "stale"
            base = {"ok": True, "schema": TELEMETRY_SCHEMA, "reset_at_ms": reset_ms,
                    "status": status, "publisher_stale": not fresh, "session": public_session(session)}
            if selected and (packets or not history_sent):
                batches = ([packets[i:i + 128] for i in range(0, len(packets), 128)] or [[]]) if compact else [packets]
                for batch in batches:
                    await socket.send_json({**base, "type": "joint_samples" if history_sent else "joint_history",
                                            **build_joint_telemetry_batch(batch, compact=compact),
                                            "runtime_view": runtime_view(session, batch[-1] if batch else latest)})
                    history_sent = True
            elif signature != (identity, status, session.get("status")):
                await socket.send_json({**base, "type": "telemetry_state", "runtime_view": runtime_view(session, latest)})
                signature = (identity, status, session.get("status"))
            if selected and str(session.get("status") or "").upper() in TERMINAL_SESSION_STATUSES and not finalized:
                result = await asyncio.to_thread(artifacts, Path(selected["log_path"]), session)
                await socket.send_json({**base, "ok": bool(result.get("ok")), "type": "telemetry_artifacts",
                                        "artifacts": result, "runtime_view": runtime_view(session, latest, result)})
                finalized = True
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect, RuntimeError, OSError):
        return
