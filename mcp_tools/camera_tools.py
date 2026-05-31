"""
File purpose:
- MCP tool wrapper for camera operations.

Key classes/functions:
- register_camera_tools

Inputs/outputs:
- Input: ToolRegistry
- Output: camera tool handlers registered

Dependencies:
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: payload schema and response fields
- Risky places to edit: tool names consumed by vision agent
- Related files: agents/vision_agent.py, device_bridges/realsense_bridge.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from mcp_tools.tool_registry import ToolRegistry


def _equipment_cross_check(payload: dict[str, Any]) -> dict[str, Any]:
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    mode = str(payload.get("runtime_mode") or payload.get("mode") or "test")
    confidence = float(payload.get("confidence", 0.9 if mode != "live" else 0.0))
    ok_default = bool(payload.get("force_ok", mode != "live"))
    ttl_ms = int(payload.get("freshness_ttl_ms") or payload.get("ttl_ms") or 5000)
    timestamp = datetime.now(timezone.utc)
    expires_at = timestamp + timedelta(milliseconds=max(1, ttl_ms))
    results = []
    for item in checks:
        if not isinstance(item, dict) or not item.get("check_id"):
            continue
        check_id = str(item["check_id"])
        ok = ok_default
        results.append(
            {
                "agent_signal_type": "equipment_vision_check_result",
                "check_id": check_id,
                "ok": ok,
                "confidence": confidence if ok else 0.0,
                "signals": {"simulated_or_external_check": ok, "anomaly": False},
                "evidence": {"observation_id": f"obs-{check_id}", "frame_ids": [f"frame-{check_id}"] if ok else []},
                "timestamp": timestamp.isoformat(),
                "expires_at": expires_at.isoformat(),
                "freshness_ttl_ms": ttl_ms,
                "source": "simulator" if mode != "live" else "live_required_external_vision",
            }
        )
    return {
        "ok": bool(results) and all(item.get("ok") for item in results),
        "tool": "vision.equipment_cross_check",
        "runtime_mode": mode,
        "results": results,
        "failure_code": None if results and all(item.get("ok") for item in results) else "VISION_EQUIPMENT_CROSS_CHECK_REQUIRED",
    }


def register_camera_tools(registry: ToolRegistry) -> None:
    """Register camera capture and equipment cross-check tools."""
    registry.register(
        "camera.capture",
        lambda payload: {
            "ok": True,
            "tool": "camera.capture",
            "frame_id": payload.get("frame_id", "mock"),
            "observation_id": f"obs-{payload.get('frame_id', 'mock')}",
            "camera_key": payload.get("camera_key", "top"),
            "purpose": payload.get("purpose", "3dp_output_pickup_check"),
            "source": "simulator",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stable_for_ms": 1200,
            "confidence": 0.86,
            "pose_confidence": 0.86,
            "anomaly": False,
        },
    )
    registry.register("vision.equipment_cross_check", _equipment_cross_check)
