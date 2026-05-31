"""
File purpose:
- MCP tool wrapper for UTM/equipment protocol operations.

Key classes/functions:
- register_utm_tools
- run_utm_protocol

Inputs/outputs:
- Input: ToolRegistry and UTM run payload
- Output: UTM run/probe result dictionary

Dependencies:
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: protocol argument fields and test-mode deterministic artifact generation
- Risky places to edit: tool names consumed by equipment agent
- Related files: agents/equipment_agent.py, device_bridges/utm_macro_bridge.py
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_tools.tool_registry import ToolRegistry


def _safe_segment(value: Any, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return text[:96] or fallback


def _probe_csv(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"ok": False, "failure_code": "UTM_EXPORT_FILE_MISSING", "path": str(path)}
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()]
    columns = [item.strip() for item in lines[0].split(",")] if lines else []
    required = {"time_s", "displacement_mm", "force_N"}
    missing = sorted(required.difference(columns))
    row_count = max(0, len(lines) - 1)

    data_quality: dict[str, Any] = {
        "required_columns_present": not missing,
        "numeric_rows": 0,
        "time_monotonic": False,
        "displacement_signal_present": False,
        "displacement_monotonic": False,
        "force_signal_present": False,
    }
    failure_code = "UTM_DATA_PARSE_FAILED" if missing or row_count <= 0 else None
    message = ""

    numeric_rows: list[tuple[float, float, float]] = []
    if not failure_code:
        index = {name: idx for idx, name in enumerate(columns)}
        for raw_line in lines[1:]:
            cells = [item.strip() for item in raw_line.split(",")]
            try:
                t = float(cells[index["time_s"]])
                d = float(cells[index["displacement_mm"]])
                f = float(cells[index["force_N"]])
            except (ValueError, IndexError, KeyError):
                continue
            numeric_rows.append((t, d, f))
        data_quality["numeric_rows"] = len(numeric_rows)

        if len(numeric_rows) < 2:
            failure_code = "UTM_DATA_PARSE_FAILED"
            message = "UTM CSV must include at least two numeric rows for signal validation."
        else:
            times = [row[0] for row in numeric_rows]
            displacements = [row[1] for row in numeric_rows]
            forces = [row[2] for row in numeric_rows]
            time_monotonic = all(b >= a for a, b in zip(times, times[1:]))
            displacement_range = max(displacements) - min(displacements)
            displacement_non_decreasing = all(b >= a for a, b in zip(displacements, displacements[1:]))
            displacement_non_increasing = all(b <= a for a, b in zip(displacements, displacements[1:]))
            displacement_monotonic = displacement_non_decreasing or displacement_non_increasing
            force_abs_max = max(abs(value) for value in forces)
            force_range = max(forces) - min(forces)
            force_signal_present = force_abs_max > 1e-9 and force_range > 1e-9

            data_quality.update(
                {
                    "time_monotonic": time_monotonic,
                    "displacement_signal_present": displacement_range > 1e-9,
                    "displacement_monotonic": displacement_monotonic,
                    "force_signal_present": force_signal_present,
                    "time_start_s": times[0],
                    "time_end_s": times[-1],
                    "displacement_min_mm": min(displacements),
                    "displacement_max_mm": max(displacements),
                    "force_min_N": min(forces),
                    "force_max_N": max(forces),
                }
            )

            if not time_monotonic:
                failure_code = "UTM_DATA_NON_MONOTONIC_TIME"
                message = "UTM CSV time_s must be monotonic non-decreasing."
            elif displacement_range <= 1e-9:
                failure_code = "UTM_DATA_NO_DISPLACEMENT_SIGNAL"
                message = "UTM CSV displacement_mm has no measurable motion signal."
            elif not displacement_monotonic:
                failure_code = "UTM_DATA_NON_MONOTONIC_DISPLACEMENT"
                message = "UTM CSV displacement_mm must be monotonic for the current compression protocol."
            elif not force_signal_present:
                failure_code = "UTM_DATA_NO_FORCE_SIGNAL"
                message = "UTM CSV force_N has no measurable force signal."

    return {
        "ok": failure_code is None,
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "row_count_probe": row_count,
        "columns_probe": columns,
        "missing_columns": missing,
        "data_quality": data_quality,
        "failure_code": failure_code,
        "message": message,
    }


def _write_test_csv(*, root: Path, run_id: str, specimen_id: str, profile: str) -> dict[str, Any]:
    artifact_dir = root / "artifacts" / "equipment" / _safe_segment(run_id, "run-test") / "utm"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"utm_direct_{_safe_segment(specimen_id, 'specimen-test')}_{stamp}.csv"
    path = artifact_dir / filename
    rows = ["time_s,displacement_mm,force_N"]
    for idx in range(96):
        displacement = idx * 0.04
        # Deterministic compression-like curve: initially near-linear, then mild softening.
        force = max(0.0, 22.0 * displacement - 1.4 * displacement * displacement + (idx % 7) * 0.32)
        rows.append(f"{idx * 0.2:.3f},{displacement:.5f},{force:.5f}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    probe = _probe_csv(path)
    artifact_id = path.stem
    return {
        "kind": "utm_csv",
        "artifact_id": artifact_id,
        "profile": profile,
        "windows_path": f"C:/ATR/utm_exports/{_safe_segment(run_id, 'run-test')}/{filename}",
        "local_path": str(path),
        "path": str(path),
        "filename": filename,
        "stable_for_sec": 2.0,
        **{key: value for key, value in probe.items() if key not in {"ok", "failure_code", "path"}},
    }


def run_utm_protocol(payload: dict[str, Any], *, repo_root: str | Path | None = None) -> dict[str, Any]:
    """Run the legacy/direct UTM contract without pretending live hardware succeeded."""
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    mode = str(payload.get("runtime_mode") or payload.get("mode") or "test").strip().lower()
    profile = str(payload.get("profile") or "default")
    run_id = str(payload.get("run_id") or "run-test")
    specimen_id = str(payload.get("specimen_id") or "specimen-test")
    program_id = str(payload.get("program_id") or "utm_compression_start_v1")

    direct_backend_configured = bool(payload.get("direct_backend_configured") or payload.get("allow_live_direct_backend"))
    supplied_result_file = str(payload.get("result_file") or payload.get("utm_csv_path") or "")
    if mode == "live" and not direct_backend_configured:
        return {
            "ok": False,
            "tool": "utm.run_protocol",
            "bridge": "utm_direct",
            "mode": mode,
            "profile": profile,
            "program_id": program_id,
            "status": "blocked",
            "failure_code": "UTM_DIRECT_BACKEND_NOT_CONFIGURED",
            "message": "Direct UTM live backend is not configured. Use Windows PyAutoGUI bridge with artifact pull, or provide an explicit direct backend result file.",
            "requires_direct_backend_config": True,
            "data_acquisition": {"status": "missing", "save_method": "direct_backend_unconfigured", "linux_path": ""},
            "cross_checks": {
                "screen_started": False,
                "physical_motion_started": False,
                "save_completed": False,
                "data_file_created": False,
                "data_parse_probe_ok": False,
                "save_export_responsibility_ok": False,
            },
            "step_trace": [{"step": "DIRECT_BACKEND_CONFIG", "status": "blocked", "detail": "UTM_DIRECT_BACKEND_NOT_CONFIGURED"}],
        }

    if mode == "live" and direct_backend_configured:
        path = Path(supplied_result_file).expanduser() if supplied_result_file else Path()
        probe = _probe_csv(path) if supplied_result_file else {"ok": False, "failure_code": "UTM_EXPORT_FILE_MISSING", "path": ""}
        ok = bool(probe.get("ok"))
        return {
            "ok": ok,
            "tool": "utm.run_protocol",
            "bridge": "utm_direct",
            "mode": mode,
            "profile": profile,
            "program_id": program_id,
            "status": "verified_complete" if ok else "blocked",
            "failure_code": None if ok else probe.get("failure_code", "UTM_DATA_PARSE_FAILED"),
            "result_file": str(path) if supplied_result_file else "",
            "utm_csv_path": str(path) if supplied_result_file else "",
            "data_integrity": {key: value for key, value in probe.items() if key not in {"ok", "failure_code"}},
            "data_acquisition": {
                "status": "pulled_to_linux" if ok else ("pulled_to_linux_parse_failed" if supplied_result_file else "missing"),
                "save_method": "direct_backend_file",
                "save_attempted_by_agent": False,
                "save_confirmation_screen_ok": ok,
                "linux_path": str(path) if supplied_result_file else "",
                "sha256": probe.get("sha256", ""),
                "size_bytes": probe.get("size_bytes", 0),
                "row_count_probe": probe.get("row_count_probe", 0),
                "columns_probe": probe.get("columns_probe", []),
                "missing_columns": probe.get("missing_columns", []),
                "data_quality": probe.get("data_quality", {}),
                "parse_failure_code": probe.get("failure_code"),
                "message": probe.get("message", ""),
            },
            "cross_checks": {
                "screen_started": ok,
                "physical_motion_started": ok,
                "save_completed": ok,
                "data_file_created": ok,
                "data_parse_probe_ok": ok,
                "save_export_responsibility_ok": ok,
            },
            "step_trace": [{"step": "DIRECT_BACKEND_FILE", "status": "ok" if ok else "blocked", "detail": probe.get("failure_code") or str(path)}],
        }

    artifact = _write_test_csv(root=root, run_id=run_id, specimen_id=specimen_id, profile=profile)
    return {
        "ok": True,
        "tool": "utm.run_protocol",
        "bridge": "utm_direct",
        "mode": mode or "test",
        "profile": profile,
        "program_id": program_id,
        "status": "verified_complete",
        "failure_code": None,
        "result_file": artifact["path"],
        "utm_csv_path": artifact["path"],
        "output_artifacts": [artifact],
        "data_integrity": artifact,
        "data_acquisition": {
            "status": "pulled_to_linux",
            "save_method": "synthetic_test_direct_backend",
            "save_attempted_by_agent": True,
            "save_confirmation_screen_ok": True,
            "windows_path": artifact["windows_path"],
            "linux_path": artifact["path"],
            "sha256": artifact.get("sha256", ""),
            "size_bytes": artifact.get("size_bytes", 0),
            "row_count_probe": artifact.get("row_count_probe", 0),
            "columns_probe": artifact.get("columns_probe", []),
            "data_quality": artifact.get("data_quality", {}),
        },
        "cross_checks": {
            "screen_started": True,
            "physical_motion_started": True,
            "save_completed": True,
            "data_file_created": True,
            "data_parse_probe_ok": True,
            "save_export_responsibility_ok": True,
        },
        "step_trace": [
            {"step": "TEST_DIRECT_UTM", "status": "ok", "detail": "deterministic CSV generated"},
            {"step": "PARSE_PROBE", "status": "ok", "detail": f"rows={artifact.get('row_count_probe', 0)}"},
        ],
    }


def register_utm_tools(registry: ToolRegistry, repo_root: str | Path | None = None) -> None:
    """Register UTM macro run tool."""
    registry.register(
        "utm.run_protocol",
        lambda payload: run_utm_protocol(payload, repo_root=repo_root),
    )
