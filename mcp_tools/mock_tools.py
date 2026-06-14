"""
File purpose:
- Mock MCP tool implementations for test-mode full dry runs.

Key classes/functions:
- register_mock_tools

Inputs/outputs:
- Input: ToolRegistry
- Output: registry populated with simulated device tools

Dependencies:
- mcp_tools.tool_registry.ToolRegistry

Modification guide:
- Safe places to edit: simulated response payload fields
- Risky places to edit: tool names used in agent logic
- Related files: agents/specimen_agent.py, agents/equipment_agent.py
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from random import Random
import re
from pathlib import Path
from typing import Any

from mcp_tools.tpms_geometry import generate_gyroid_stl_text, normalize_geometry_type, write_smooth_gyroid_stl
from mcp_tools.tool_registry import ToolRegistry
from mcp_tools.utm_tools import run_utm_protocol

_rng = Random(42)


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _printer_prepare(payload: dict[str, Any]) -> dict[str, Any]:
    specimen_id = payload.get("specimen_id", "spm-001")
    stl_path = payload.get("stl_path")
    sliced_path = str(Path(str(stl_path)).with_suffix(".gcode")) if stl_path else None
    return {
        "ok": True,
        "tool": "printer.prepare",
        "mode": payload.get("runtime_mode", "test"),
        "printer_path": "mock_virtual_prusalink",
        "specimen_id": specimen_id,
        "stl_path": stl_path,
        "sliced_path": sliced_path,
        "handoff_package_path": payload.get("handoff_package_path"),
        "printer_profile": payload.get("printer_profile"),
        "material": payload.get("material"),
        "slicer_profile_hint": payload.get("slicer_profile_hint"),
        "slicer_settings": {
            "enabled": False,
            "simulated": True,
            "input_model_path": stl_path,
            "output_gcode_path": sliced_path,
            "printer_profile": payload.get("printer_profile"),
            "material": payload.get("material"),
            "slicer_profile_hint": payload.get("slicer_profile_hint"),
            "layer_height_mm": 0.2,
            "bed_temperature_c": 60.0,
            "first_layer_bed_temperature_c": 60.0,
            "nozzle_diameter_mm": 0.4,
            "resolved_command": ["virtual-prusaslicer", "--export-gcode", "--output", sliced_path or "{output_path}", stl_path or "{stl_path}"],
        },
        "slicer_result": {"ok": True, "sliced_path": sliced_path, "simulated": True, "failure_code": None},
        "gcode_validation": {"ok": True, "failure_code": None, "violations": []},
        "printer": {"provider": "prusa_mk4s", "host_configured": False, "state": "MOCK_READY"},
        "prusalink": {"transport": "mock_virtual", "upload_endpoint": "/api/v1/files/usb/mock.gcode"},
        "print_result": {"status": "mock_prepared", "failure_code": None},
        "ejection_result": {"status": "disabled", "attempts": 0, "failure_code": None},
        "step_trace": [
            {"step": "PRECHECK", "status": "ok"},
            {"step": "SLICE", "status": "ok"},
            {"step": "UPLOAD", "status": "mock"},
            {"step": "DONE", "status": "ok"},
        ],
        "status": "prepared",
        "failure_code": None,
    }


def _camera_capture(payload: dict[str, Any]) -> dict[str, Any]:
    frame_id = payload.get("frame_id", f"frame-{_rng.randint(1000, 9999)}")
    specimen_id = str(payload.get("specimen_id") or "")
    timestamp = datetime.now(timezone.utc).isoformat()
    confidence = float(payload.get("confidence", 0.86))
    return {
        "ok": True,
        "tool": "camera.capture",
        "frame_id": frame_id,
        "observation_id": f"obs-{frame_id}",
        "camera_key": payload.get("camera_key", "top"),
        "purpose": payload.get("purpose", "3dp_output_pickup_check"),
        "source": "simulator",
        "timestamp": timestamp,
        "stable_for_ms": int(payload.get("stable_for_ms", 1200)),
        "confidence": confidence,
        "pose_confidence": confidence,
        "anomaly": False,
        "zones": {
            "printer_bed": {"specimen_present": False, "confidence": 0.74, "state": "clear"},
            "ejection_basket": {"specimen_present": bool(specimen_id), "object_count": 1 if specimen_id else 0, "confidence": confidence, "state": "loaded" if specimen_id else "empty_or_unknown"},
            "robot_workspace": {"clear": True, "confidence": 0.82, "state": "clear"},
        },
        "detections": [
            {
                "label": "printed_specimen",
                "zone": "ejection_basket",
                "specimen_id": specimen_id,
                "bbox_xyxy": [210, 120, 420, 310],
                "confidence": confidence,
                "source": "simulator",
            }
        ] if specimen_id else [],
    }


def _vision_equipment_cross_check(payload: dict[str, Any]) -> dict[str, Any]:
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    run_id = str(payload.get("run_id") or "run-test")
    mode = str(payload.get("runtime_mode") or payload.get("mode") or "test")
    confidence = float(payload.get("confidence", 0.9 if mode != "live" else 0.0))
    force_ok = payload.get("force_ok")
    if force_ok is None:
        force_ok = mode != "live"
    ttl_ms = int(payload.get("freshness_ttl_ms") or payload.get("ttl_ms") or 5000)
    timestamp = datetime.now(timezone.utc)
    expires_at = timestamp + timedelta(milliseconds=max(1, ttl_ms))
    results = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        check_id = str(item.get("check_id") or "").strip()
        if not check_id:
            continue
        ok = bool(force_ok)
        if check_id == "utm_pre_start":
            signals = {
                "specimen_on_utm_fixture": ok,
                "robot_clear_of_utm": ok,
                "compression_flatten_occupied": ok,
                "human_intrusion": False,
            }
        elif check_id == "utm_motion_confirm":
            signals = {
                "utm_crosshead_motion": ok,
                "specimen_on_fixture": ok,
                "robot_clear_of_utm": ok,
                "anomaly": False,
            }
        else:
            signals = {
                "utm_crosshead_stopped": ok,
                "fixture_safe_to_access": ok,
                "specimen_tested_or_crushed": ok,
                "anomaly": False,
            }
        results.append(
            {
                "agent_signal_type": "equipment_vision_check_result",
                "check_id": check_id,
                "ok": ok,
                "confidence": confidence if ok else 0.0,
                "signals": signals,
                "evidence": {"observation_id": f"obs-{run_id}-{check_id}", "frame_ids": [f"frame-{check_id}"] if ok else []},
                "timestamp": timestamp.isoformat(),
                "expires_at": expires_at.isoformat(),
                "freshness_ttl_ms": ttl_ms,
                "source": "simulator" if mode != "live" else "live_required_external_vision",
            }
        )
    return {
        "ok": all(item.get("ok") for item in results) if results else False,
        "tool": "vision.equipment_cross_check",
        "runtime_mode": mode,
        "results": results,
        "failure_code": None if results and all(item.get("ok") for item in results) else "VISION_EQUIPMENT_CROSS_CHECK_REQUIRED",
    }


def _robot_pick_place(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "tool": "robot.pick_place", "grasp_score": 0.89, "task": payload.get("task", "pick_place")}


def _utm_run(payload: dict[str, Any]) -> dict[str, Any]:
    return run_utm_protocol(payload)


def _device_health(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "printer": "ready",
        "camera": "ready",
        "robot": "ready",
        "utm": "ready",
        "simulator": "active",
    }


def _vector3(value: Any, default: list[float]) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        return list(default)
    out: list[float] = []
    for idx, item in enumerate(value):
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            out.append(float(default[idx]))
    return out


def _safe_segment(value: Any, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return text or fallback


def _try_write_stl_iso_capture_png(
    path: Path,
    *,
    stl_path: Path,
    specimen_id: str,
    geometry_type: str,
) -> bool:
    """Render an actual STL mesh into a deterministic isometric PNG preview."""
    try:
        from PIL import Image, ImageDraw
        import numpy as np
        import trimesh
    except Exception:
        return False
    if not stl_path.exists():
        return False
    try:
        mesh = trimesh.load_mesh(str(stl_path), force="mesh")
        vertices = np.asarray(mesh.vertices, dtype=float)
        faces = np.asarray(mesh.faces, dtype=int)
    except Exception:
        return False
    if vertices.size == 0 or faces.size == 0:
        return False

    # Keep the surface solid in small GUI cards.  The old 18k face stride made
    # dense TPMS meshes look like sparse wire/point clouds instead of surfaces.
    max_faces = 240000
    if len(faces) > max_faces:
        stride = max(1, math.ceil(len(faces) / max_faces))
        faces = faces[::stride]

    width, height = 760, 420
    scale_factor = 2
    render_size = (width * scale_factor, height * scale_factor)
    image = Image.new("RGB", render_size, "#07111f")
    draw = ImageDraw.Draw(image, "RGBA")

    for y in range(render_size[1]):
        r = int(7 + y * 0.009)
        g = int(17 + y * 0.013)
        b = int(31 + y * 0.021)
        draw.line([(0, y), (render_size[0], y)], fill=(r, g, min(b, 66), 255))
    centered = vertices - ((vertices.min(axis=0) + vertices.max(axis=0)) / 2.0)
    iso_x = (centered[:, 0] - centered[:, 1]) * 0.8660254
    iso_y = (centered[:, 0] + centered[:, 1]) * 0.50 - centered[:, 2] * 0.92
    min_x, max_x = float(iso_x.min()), float(iso_x.max())
    min_y, max_y = float(iso_y.min()), float(iso_y.max())
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    margin_x = 58 * scale_factor
    margin_y = 44 * scale_factor
    fit = min((render_size[0] - margin_x * 2) / span_x, (render_size[1] - margin_y * 2) / span_y)
    px = (iso_x - (min_x + max_x) / 2.0) * fit + render_size[0] / 2.0
    py = (iso_y - (min_y + max_y) / 2.0) * fit + render_size[1] / 2.0 + 8 * scale_factor

    shadow_w = min(render_size[0] * 0.54, span_x * fit * 1.10)
    shadow_h = min(render_size[1] * 0.18, max(18 * scale_factor, span_y * fit * 0.16))
    draw.ellipse(
        [
            render_size[0] / 2.0 - shadow_w / 2.0,
            render_size[1] / 2.0 + span_y * fit * 0.33,
            render_size[0] / 2.0 + shadow_w / 2.0,
            render_size[1] / 2.0 + span_y * fit * 0.33 + shadow_h,
        ],
        fill=(0, 0, 0, 62),
    )

    tri_vertices = centered[faces]
    normals = np.cross(tri_vertices[:, 1] - tri_vertices[:, 0], tri_vertices[:, 2] - tri_vertices[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    normals = normals / np.maximum(lengths[:, None], 1e-9)
    light = np.array([-0.35, -0.55, 0.78], dtype=float)
    light = light / np.linalg.norm(light)
    shade = np.clip(normals @ light, 0.0, 1.0)
    shade = 0.40 + shade * 0.60
    depth = tri_vertices.mean(axis=1) @ np.array([0.62, 0.62, 0.36], dtype=float)
    order = np.argsort(depth)

    palette = {
        "gyroid": (65, 220, 164),
        "lattice_bcc": (56, 189, 248),
        "lattice_fcc": (88, 166, 255),
        "lattice_octet": (167, 139, 250),
        "honeycomb": (245, 196, 83),
        "auxetic_reentrant": (244, 114, 182),
        "random_voronoi": (34, 211, 238),
    }
    base = palette.get(str(geometry_type), (96, 165, 250))
    screen_points = np.column_stack([px, py])
    for face_index in order:
        face = faces[face_index]
        pts = [(float(screen_points[idx, 0]), float(screen_points[idx, 1])) for idx in face]
        s = float(shade[face_index])
        fill = (
            int(base[0] * s + 12 * (1.0 - s)),
            int(base[1] * s + 22 * (1.0 - s)),
            int(base[2] * s + 38 * (1.0 - s)),
            255,
        )
        draw.polygon(pts, fill=fill)

    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:
        resample = Image.LANCZOS
    image = image.resize((width, height), resample)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    return True


def _write_viewer_capture_png(
    path: Path,
    *,
    specimen_id: str,
    geometry_type: str,
    size: list[float],
    cell: float,
    wall: float,
    relative_density: float,
    orientation_deg: float,
    geometry_hash: str,
    stl_path: Path | None = None,
) -> bool:
    """Write a bitmap capture, preferring an actual STL isometric render."""
    if stl_path is not None and _try_write_stl_iso_capture_png(
        path,
        stl_path=stl_path,
        specimen_id=specimen_id,
        geometry_type=geometry_type,
    ):
        return True
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False

    width, height = 760, 420
    image = Image.new("RGB", (width, height), "#07111f")
    draw = ImageDraw.Draw(image, "RGBA")

    for y in range(height):
        r = int(7 + y * 0.018)
        g = int(17 + y * 0.026)
        b = int(31 + y * 0.042)
        draw.line([(0, y), (width, y)], fill=(r, g, min(b, 64), 255))

    cx, cy = width * 0.53, height * 0.68
    density = max(0.08, min(0.85, float(relative_density or 0.28)))
    grid = max(3, min(8, round(9 - float(cell or 10.0) / 2.0 + density * 3.0)))
    stroke_width = max(2, min(6, round(float(wall or 1.6) * 1.7)))
    angle = float(orientation_deg or 0.0) * 3.141592653589793 / 180.0
    accent = (69, 227, 162, 210)
    accent2 = (56, 189, 248, 190)

    unit = min(width * 0.23, height * 0.38)
    sx, sy, sz = unit, unit * 0.54, unit * 1.05
    cos_a = math.cos(angle * 0.42)
    sin_a = math.sin(angle * 0.42)

    def project(x: float, y: float, z: float) -> tuple[float, float]:
        xr = x * cos_a - y * sin_a
        yr = x * sin_a + y * cos_a
        return (cx + (xr - yr) * sx, cy + (xr + yr) * sy - z * sz)

    corners = {
        "a": project(-0.5, -0.5, 0.0),
        "b": project(0.5, -0.5, 0.0),
        "c": project(0.5, 0.5, 0.0),
        "d": project(-0.5, 0.5, 0.0),
        "e": project(-0.5, -0.5, 1.0),
        "f": project(0.5, -0.5, 1.0),
        "g": project(0.5, 0.5, 1.0),
        "h": project(-0.5, 0.5, 1.0),
    }
    draw.ellipse([cx - unit * 1.35, cy + unit * 0.20, cx + unit * 1.35, cy + unit * 0.82], fill=(0, 0, 0, 58))
    draw.polygon([corners["d"], corners["c"], corners["g"], corners["h"]], fill=(15, 23, 42, 150))
    draw.polygon([corners["b"], corners["c"], corners["g"], corners["f"]], fill=(8, 15, 27, 178))
    draw.polygon([corners["e"], corners["f"], corners["g"], corners["h"]], fill=(28, 44, 68, 150))

    def lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * t

    def line3(a: tuple[float, float, float], b: tuple[float, float, float], fill: tuple[int, int, int, int], width_px: int) -> None:
        draw.line([project(*a), project(*b)], fill=fill, width=width_px)

    grid_color = (125, 211, 252, 156)
    brace_color = accent2
    for idx in range(grid + 1):
        t = idx / max(grid, 1)
        line3((lerp(-0.5, 0.5, t), 0.5, 0), (lerp(-0.5, 0.5, t), 0.5, 1), grid_color, stroke_width)
        line3((-0.5, 0.5, t), (0.5, 0.5, t), grid_color, stroke_width)
        line3((0.5, lerp(-0.5, 0.5, t), 0), (0.5, lerp(-0.5, 0.5, t), 1), (125, 211, 252, 120), stroke_width)
        line3((lerp(-0.5, 0.5, t), -0.5, 1), (lerp(-0.5, 0.5, t), 0.5, 1), (125, 211, 252, 112), max(1, stroke_width - 1))
        line3((-0.5, lerp(-0.5, 0.5, t), 1), (0.5, lerp(-0.5, 0.5, t), 1), (125, 211, 252, 112), max(1, stroke_width - 1))
    for idx in range(grid):
        t0 = idx / max(grid, 1)
        t1 = (idx + 1) / max(grid, 1)
        z0, z1 = (0.08, 0.92) if idx % 2 == 0 else (0.92, 0.08)
        line3((lerp(-0.5, 0.5, t0), 0.5, z0), (lerp(-0.5, 0.5, t1), 0.5, z1), brace_color, stroke_width + 1)
        line3((0.5, lerp(-0.5, 0.5, t0), z1), (0.5, lerp(-0.5, 0.5, t1), z0), (167, 139, 250, 140), stroke_width)

    if re.search(r"gyroid|tpms|voronoi", str(geometry_type), re.IGNORECASE):
        for band in range(3):
            points: list[tuple[float, float]] = []
            for step in range(54):
                t = step / 53.0
                x = lerp(-0.44, 0.44, t)
                z = 0.18 + band * 0.24 + math.sin(t * math.pi * 2.0 + band) * 0.045
                points.append(project(x, 0.505, z))
            draw.line(points, fill=(167, 139, 250, 150), width=max(2, stroke_width), joint="curve")

    for start, end in (
        ("a", "b"), ("b", "c"), ("c", "d"), ("d", "a"),
        ("e", "f"), ("f", "g"), ("g", "h"), ("h", "e"),
        ("a", "e"), ("b", "f"), ("c", "g"), ("d", "h"),
    ):
        draw.line([corners[start], corners[end]], fill=(125, 211, 252, 210), width=2)
    image.save(path, format="PNG", optimize=True)
    return True


def _cuboid_facets(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[str]:
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
        (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
        (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0),
    ]
    lines: list[str] = []
    for a, b, c in faces:
        lines.extend(
            [
                "  facet normal 0 0 0",
                "    outer loop",
                f"      vertex {v[a][0]:.6f} {v[a][1]:.6f} {v[a][2]:.6f}",
                f"      vertex {v[b][0]:.6f} {v[b][1]:.6f} {v[b][2]:.6f}",
                f"      vertex {v[c][0]:.6f} {v[c][1]:.6f} {v[c][2]:.6f}",
                "    endloop",
                "  endfacet",
            ]
        )
    return lines


def _cuboids_stl(name: str, cuboids: list[tuple[float, float, float, float, float, float]]) -> str:
    lines = [f"solid {name}"]
    for cuboid in cuboids:
        lines.extend(_cuboid_facets(*cuboid))
    lines.append(f"endsolid {name}")
    return "\n".join(lines) + "\n"


def _box_stl(name: str, size: list[float]) -> str:
    x, y, z = [max(float(item), 1.0) for item in size]
    cuboid = (-x / 2.0, x / 2.0, -y / 2.0, y / 2.0, -z / 2.0, z / 2.0)
    return _cuboids_stl(name, [cuboid])


def _lattice_stl(name: str, size: list[float], wall: float, cell_size: float, cap: bool) -> str:
    x, y, z = [max(float(item), 1.0) for item in size]
    hx, hy, hz = x / 2.0, y / 2.0, z / 2.0
    strut = max(0.6, min(float(wall), min(x, y, z) / 8.0))
    cell = max(float(cell_size), strut * 3.0)
    cells = max(2, min(5, round(min(x, y, z) / cell)))

    def positions(length: float) -> list[float]:
        half = length / 2.0
        step = length / cells
        return [round(-half + step * idx, 6) for idx in range(cells + 1)]

    def clipped(center: float, half_width: float, low: float, high: float) -> tuple[float, float]:
        return max(low, center - half_width), min(high, center + half_width)

    xs = positions(x)
    ys = positions(y)
    zs = positions(z)
    half = strut / 2.0
    cuboids: list[tuple[float, float, float, float, float, float]] = []

    for yy in ys:
        y0, y1 = clipped(yy, half, -hy, hy)
        for zz in zs:
            z0, z1 = clipped(zz, half, -hz, hz)
            cuboids.append((-hx, hx, y0, y1, z0, z1))
    for xx in xs:
        x0, x1 = clipped(xx, half, -hx, hx)
        for zz in zs:
            z0, z1 = clipped(zz, half, -hz, hz)
            cuboids.append((x0, x1, -hy, hy, z0, z1))
    for xx in xs:
        x0, x1 = clipped(xx, half, -hx, hx)
        for yy in ys:
            y0, y1 = clipped(yy, half, -hy, hy)
            cuboids.append((x0, x1, y0, y1, -hz, hz))

    if cap:
        cap_t = max(0.6, min(strut, z / 12.0))
        cuboids.append((-hx, hx, -hy, hy, -hz, -hz + cap_t))
        cuboids.append((-hx, hx, -hy, hy, hz - cap_t, hz))
    return _cuboids_stl(name, cuboids)


def _auxetic_reentrant_stl(name: str, size: list[float], wall: float, cell_size: float, cap: bool) -> str:
    x, y, z = [max(float(item), 1.0) for item in size]
    hx, hy, hz = x / 2.0, y / 2.0, z / 2.0
    strut = max(0.6, min(float(wall), min(x, y, z) / 10.0))
    cell = max(float(cell_size), strut * 4.0)
    cols = max(2, min(6, round(x / cell)))
    rows = max(2, min(6, round(y / cell)))
    pitch_x = x / cols
    pitch_y = y / rows
    amp = max(strut * 1.2, min(pitch_x * 0.28, pitch_y * 0.28))
    amp = min(amp, pitch_x * 0.4)
    z0, z1 = -hz, hz

    def add_segment(
        cuboids: list[tuple[float, float, float, float, float, float]],
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        steps: int = 1,
    ) -> None:
        parts = max(1, int(steps))
        for idx in range(parts):
            t0 = idx / parts
            t1 = (idx + 1) / parts
            xa = x0 + (x1 - x0) * t0
            xb = x0 + (x1 - x0) * t1
            ya = y0 + (y1 - y0) * t0
            yb = y0 + (y1 - y0) * t1
            cx = (xa + xb) / 2.0
            cy = (ya + yb) / 2.0
            lx = abs(xb - xa) + strut
            ly = abs(yb - ya) + strut
            ax0 = max(-hx, cx - lx / 2.0)
            ax1 = min(hx, cx + lx / 2.0)
            ay0 = max(-hy, cy - ly / 2.0)
            ay1 = min(hy, cy + ly / 2.0)
            if (ax1 - ax0) < 0.05 or (ay1 - ay0) < 0.05:
                continue
            cuboids.append((ax0, ax1, ay0, ay1, z0, z1))

    cuboids: list[tuple[float, float, float, float, float, float]] = []
    add_segment(cuboids, -hx, -hy, hx, -hy)
    add_segment(cuboids, -hx, hy, hx, hy)
    add_segment(cuboids, -hx, -hy, -hx, hy)
    add_segment(cuboids, hx, -hy, hx, hy)

    base_x = [(-hx + pitch_x * idx) for idx in range(cols + 1)]
    row_nodes: list[tuple[float, list[float]]] = []
    for row in range(rows + 1):
        y_coord = -hy + pitch_y * row
        shift = amp if row % 2 else -amp
        nodes: list[float] = []
        for col, x_coord in enumerate(base_x):
            shifted = x_coord
            if 0 < col < cols:
                shifted += shift
            shifted = max(-hx + strut * 0.7, min(hx - strut * 0.7, shifted))
            nodes.append(shifted)
        row_nodes.append((y_coord, nodes))

    for y_coord, nodes in row_nodes:
        for col in range(cols):
            add_segment(cuboids, nodes[col], y_coord, nodes[col + 1], y_coord)
    for row in range(rows):
        y0_row, nodes0 = row_nodes[row]
        y1_row, nodes1 = row_nodes[row + 1]
        for col in range(1, cols):
            add_segment(cuboids, nodes0[col], y0_row, nodes1[col], y1_row, steps=4)

    if cap:
        cap_t = max(0.6, min(strut, z / 14.0))
        cuboids.append((-hx, hx, -hy, hy, -hz, -hz + cap_t))
        cuboids.append((-hx, hx, -hy, hy, hz - cap_t, hz))
    return _cuboids_stl(name, cuboids)


def _generate_geometry_stl(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _safe_segment(payload.get("run_id", "run"), "run")
    specimen_id = _safe_segment(payload.get("specimen_id", "specimen"), "specimen")
    raw_geometry_type = payload.get("geometry_type", "gyroid")
    geometry_type = normalize_geometry_type(raw_geometry_type)
    if geometry_type not in {
        "gyroid",
        "lattice_bcc",
        "lattice_fcc",
        "lattice_octet",
        "honeycomb",
        "auxetic_reentrant",
        "random_voronoi",
    }:
        geometry_type = "gyroid"
    size = _vector3(payload.get("specimen_size_mm"), [30.0, 30.0, 30.0])
    wall = float(payload.get("wall_thickness_mm", 1.2) or 1.2)
    cell = float(payload.get("cell_size_mm", 7.5) or 7.5)
    relative_density = float(payload.get("relative_density", 0.32) or 0.32)
    anisotropy_ratio = float(payload.get("anisotropy_ratio", 1.0) or 1.0)
    orientation_deg = float(payload.get("orientation_deg", 0.0) or 0.0)
    defect_seed = int(payload.get("defect_seed", 1) or 1)
    defect_ratio = float(payload.get("defect_ratio", 0.0) or 0.0)
    raw_skin = payload.get("skin_thickness_mm", 0.0)
    skin_thickness_mm = 0.0 if raw_skin in (None, "") else float(raw_skin)
    legacy_cap = _as_bool(payload.get("top_bottom_cap"), False)
    explicit_top_cap = "top_cap_enabled" in payload
    explicit_bottom_cap = "bottom_cap_enabled" in payload
    if explicit_top_cap or explicit_bottom_cap:
        top_cap = _as_bool(payload.get("top_cap_enabled"), False)
        bottom_cap = _as_bool(payload.get("bottom_cap_enabled"), legacy_cap)
    else:
        top_cap = legacy_cap
        bottom_cap = legacy_cap
    cap = bool(top_cap or bottom_cap)
    if cap and skin_thickness_mm <= 0.0:
        skin_thickness_mm = 0.8
    if not cap:
        skin_thickness_mm = 0.0
    output_dir = Path(str(payload.get("output_dir") or Path("runs") / run_id / "specimens" / specimen_id))
    output_dir.mkdir(parents=True, exist_ok=True)

    stl_path = output_dir / "specimen.stl"
    metadata_path = output_dir / "geometry_report.json"
    preview_path = output_dir / "specimen_preview.svg"
    viewer_capture_path = output_dir / "viewer_capture.png"
    generation_log = output_dir / "geometry.log"
    generator_meta: dict[str, Any] = {}
    wrote_stl = False

    if geometry_type == "gyroid":
        generator_meta = write_smooth_gyroid_stl(
            stl_path=stl_path,
            name=specimen_id,
            specimen_size_mm=size,
            wall_thickness_mm=wall,
            cell_size_mm=cell,
            relative_density=relative_density,
            anisotropy_ratio=anisotropy_ratio,
            orientation_deg=orientation_deg,
            defect_seed=defect_seed,
            defect_ratio=defect_ratio,
            skin_thickness_mm=skin_thickness_mm,
            top_bottom_cap=cap,
            top_cap_enabled=top_cap,
            bottom_cap_enabled=bottom_cap,
            tpms_thickness=payload.get("tpms_thickness"),
            resolution=payload.get("tpms_resolution"),
        ) or {}
        wrote_stl = bool(generator_meta)
        if not wrote_stl:
            stl_text, generator_meta = generate_gyroid_stl_text(
                name=specimen_id,
                specimen_size_mm=size,
                wall_thickness_mm=wall,
                cell_size_mm=cell,
                relative_density=relative_density,
                anisotropy_ratio=anisotropy_ratio,
                orientation_deg=orientation_deg,
                defect_seed=defect_seed,
                defect_ratio=defect_ratio,
                skin_thickness_mm=skin_thickness_mm,
                top_bottom_cap=cap,
                top_cap_enabled=top_cap,
                bottom_cap_enabled=bottom_cap,
                tpms_thickness=payload.get("tpms_thickness"),
                resolution=payload.get("tpms_resolution"),
            )
    elif geometry_type.startswith("lattice"):
        stl_text = _lattice_stl(specimen_id, size, wall, cell, cap)
        generator_meta = {"generator_backend": "legacy_axis_lattice", "triangle_count": stl_text.count("facet normal")}
    elif geometry_type == "auxetic_reentrant":
        stl_text = _auxetic_reentrant_stl(specimen_id, size, wall, cell, cap)
        generator_meta = {"generator_backend": "legacy_reentrant_auxetic", "triangle_count": stl_text.count("facet normal")}
    else:
        stl_text = _box_stl(specimen_id, size)
        generator_meta = {"generator_backend": "legacy_box_fallback", "triangle_count": stl_text.count("facet normal")}

    digest_source = {
        "geometry_type": geometry_type,
        "specimen_size_mm": size,
        "cell_size_mm": cell,
        "wall_thickness_mm": wall,
        "relative_density": relative_density,
        "anisotropy_ratio": anisotropy_ratio,
        "orientation_deg": orientation_deg,
        "defect_seed": defect_seed,
        "defect_ratio": defect_ratio,
        "skin_thickness_mm": skin_thickness_mm,
        "top_cap_enabled": top_cap,
        "bottom_cap_enabled": bottom_cap,
        "top_bottom_cap": cap,
        "tpms_thickness": payload.get("tpms_thickness"),
        "tpms_resolution": payload.get("tpms_resolution"),
        "tool_version": "tpms-geometry-v3",
    }
    geometry_hash = hashlib.sha1(json.dumps(digest_source, sort_keys=True).encode("utf-8")).hexdigest()
    estimated_volume = float(generator_meta.get("estimated_volume_mm3") or (float(size[0] * size[1] * size[2]) * relative_density))
    density = 0.00124 if str(payload.get("material", "PLA")).upper() == "PLA" else 0.00120
    estimated_mass = estimated_volume * density

    if not wrote_stl:
        stl_path.write_text(stl_text, encoding="utf-8")
    preview_path.write_text(
        (
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"760\" height=\"260\" viewBox=\"0 0 760 260\">"
            "<rect width=\"760\" height=\"260\" rx=\"18\" fill=\"#f3f6ff\"/>"
            "<g fill=\"none\" stroke=\"#1f3a8a\" stroke-width=\"3\" opacity=\"0.75\">"
            "<path d=\"M36 188 C86 122 140 244 190 178 S290 126 340 188 S440 238 490 178\"/>"
            "<path d=\"M36 214 C92 156 142 202 190 136 S284 74 338 142 S430 222 496 154\"/>"
            "<path d=\"M92 92 C150 146 224 40 292 96 S392 178 466 92\"/>"
            "</g>"
            "<text x=\"24\" y=\"64\" font-family=\"monospace\" font-size=\"22\" fill=\"#1f3a8a\">"
            f"{specimen_id} / {geometry_type}</text>"
            "<text x=\"24\" y=\"104\" font-family=\"monospace\" font-size=\"16\" fill=\"#334155\">"
            f"size={size} cell={cell:.3f} wall={wall:.3f}</text>"
            "<text x=\"24\" y=\"144\" font-family=\"monospace\" font-size=\"16\" fill=\"#334155\">"
            f"backend={generator_meta.get('generator_backend', 'unknown')}</text>"
            "<text x=\"24\" y=\"236\" font-family=\"monospace\" font-size=\"14\" fill=\"#334155\">"
            f"hash={geometry_hash[:16]}</text>"
            "</svg>\n"
        ),
        encoding="utf-8",
    )
    capture_ready = _write_viewer_capture_png(
        viewer_capture_path,
        specimen_id=specimen_id,
        geometry_type=geometry_type,
        size=size,
        cell=cell,
        wall=wall,
        relative_density=relative_density,
        orientation_deg=orientation_deg,
        geometry_hash=geometry_hash,
        stl_path=stl_path,
    )
    metadata_payload = {
        "ok": True,
        "geometry_type": geometry_type,
        "specimen_size_mm": size,
        "wall_thickness_mm": wall,
        "cell_size_mm": cell,
        "relative_density": relative_density,
        "anisotropy_ratio": anisotropy_ratio,
        "orientation_deg": orientation_deg,
        "defect_seed": defect_seed,
        "defect_ratio": defect_ratio,
        "skin_thickness_mm": skin_thickness_mm,
        "top_cap_enabled": top_cap,
        "bottom_cap_enabled": bottom_cap,
        "top_bottom_cap": cap,
        "estimated_volume_mm3": round(estimated_volume, 3),
        "estimated_mass_g": round(estimated_mass, 3),
        "bounding_box_mm": size,
        "geometry_hash": geometry_hash,
        "viewer_capture_path": str(viewer_capture_path) if capture_ready else "",
        "tool_version": "tpms-geometry-v3",
        **generator_meta,
    }
    metadata_path.write_text(json.dumps(metadata_payload, ensure_ascii=True, indent=2), encoding="utf-8")
    generation_log.write_text(
        (
            "geometry.generate_metamaterial_stl completed\n"
            f"geometry_type={geometry_type}\n"
            f"generator_backend={generator_meta.get('generator_backend', 'unknown')}\n"
            f"geometry_hash={geometry_hash}\n"
        ),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "tool": "geometry.generate_metamaterial_stl",
        "specimen_id": specimen_id,
        "stl_path": str(stl_path),
        "metadata_path": str(metadata_path),
        "preview_image_path": str(preview_path),
        "viewer_capture_path": str(viewer_capture_path) if capture_ready else "",
        "capture_image_path": str(viewer_capture_path) if capture_ready else "",
        "geometry_report": metadata_payload,
        "estimated_volume_mm3": round(estimated_volume, 3),
        "estimated_mass_g": round(estimated_mass, 3),
        "bounding_box_mm": size,
        "generation_log_path": str(generation_log),
        "geometry_hash": geometry_hash,
        "error_message": "",
    }


def _check_mesh_quality(payload: dict[str, Any]) -> dict[str, Any]:
    stl_path = Path(str(payload.get("stl_path", "")))
    if not stl_path.exists():
        return {
            "ok": False,
            "tool": "geometry.check_mesh_quality",
            "mesh_status": "fail",
            "mesh_report": {},
            "watertight": False,
            "non_manifold_edges": 0,
            "inverted_normals": 0,
            "self_intersections": 0,
            "disconnected_components": 0,
            "bounding_box_mm": [0.0, 0.0, 0.0],
            "volume_mm3": 0.0,
            "reject_reasons": [f"stl_path does not exist: {stl_path}"],
            "warnings": [],
        }

    expected_bbox = _vector3(payload.get("expected_bounding_box_mm"), [30.0, 30.0, 30.0])
    reject_reasons: list[str] = []
    if any(item <= 0.0 for item in expected_bbox):
        reject_reasons.append("expected_bounding_box_mm contains non-positive value")
    if stl_path.stat().st_size < 128:
        reject_reasons.append("stl file appears too small")

    mesh_ok = len(reject_reasons) == 0
    mesh_report = {
        "watertight": True,
        "non_manifold_edges": 0,
        "inverted_normals": 0,
        "self_intersections": 0,
        "disconnected_components": 1,
        "bbox": expected_bbox,
    }
    volume = float(expected_bbox[0] * expected_bbox[1] * expected_bbox[2]) * 0.3
    return {
        "ok": mesh_ok,
        "tool": "geometry.check_mesh_quality",
        "mesh_status": "pass" if mesh_ok else "fail",
        "mesh_report": mesh_report,
        "watertight": True,
        "non_manifold_edges": 0,
        "inverted_normals": 0,
        "self_intersections": 0,
        "disconnected_components": 1,
        "bounding_box_mm": expected_bbox,
        "volume_mm3": round(volume, 3),
        "reject_reasons": reject_reasons,
        "warnings": [],
    }


def _check_manufacturability(payload: dict[str, Any]) -> dict[str, Any]:
    constraints = payload.get("constraints", {})
    constraints = constraints if isinstance(constraints, dict) else {}
    mesh_report = payload.get("mesh_report", {})
    mesh_report = mesh_report if isinstance(mesh_report, dict) else {}
    reject_reasons: list[str] = []
    warnings: list[str] = []

    wall = float(constraints.get("wall_thickness_mm", 1.2) or 1.2)
    cell = float(constraints.get("cell_size_mm", 7.5) or 7.5)
    min_feature = float(constraints.get("minimum_feature_size_mm", 0.8) or 0.8)
    nozzle = float(constraints.get("nozzle_diameter_mm", 0.4) or 0.4)
    layer_height = float(constraints.get("layer_height_mm", 0.2) or 0.2)
    geometry_type = str(constraints.get("geometry_type", "")).strip().lower()
    rel_density = float(constraints.get("relative_density", 0.32) or 0.32)
    top_bottom_cap = _as_bool(constraints.get("top_bottom_cap"), False)
    top_cap = _as_bool(constraints.get("top_cap_enabled"), top_bottom_cap)
    bottom_cap = _as_bool(constraints.get("bottom_cap_enabled"), top_bottom_cap)
    require_flat = bool(constraints.get("require_flat_compression_faces", False))
    fdm_min_wall = float(constraints.get("fdm_min_wall_thickness_mm", max(1.2, 3.0 * nozzle)) or max(1.2, 3.0 * nozzle))
    fdm_max_bridge = float(constraints.get("fdm_max_bridge_distance_mm", 10.0) or 10.0)
    fdm_max_overhang = float(constraints.get("fdm_max_unsupported_overhang_deg", 45.0) or 45.0)
    fdm_max_gyroid_wall_cell_ratio = float(constraints.get("fdm_max_gyroid_wall_cell_ratio", 0.28) or 0.28)
    max_print_time = float(constraints.get("max_print_time_min", 120.0) or 120.0)
    max_mass = float(constraints.get("max_mass_g", 50.0) or 50.0)
    expected_print_time = float(constraints.get("expected_print_time_min", 65.0) or 65.0)
    expected_mass = float(constraints.get("expected_mass_g", 18.0) or 18.0)
    bbox = _vector3(mesh_report.get("bbox"), [30.0, 30.0, 30.0])
    bed_contact = float(bbox[0] * bbox[1])

    if wall < min_feature:
        reject_reasons.append("wall_thickness_mm below minimum_feature_size_mm")
    if wall < max(fdm_min_wall, 2.0 * nozzle):
        reject_reasons.append("wall_thickness_mm below FDM printable wall rule")
    if cell < 3.0 * wall:
        reject_reasons.append("cell_size_mm below 3x wall_thickness_mm")
    if geometry_type == "gyroid":
        if cell > fdm_max_bridge:
            reject_reasons.append("gyroid cell_size_mm exceeds FDM bridge/span rule")
        if wall / max(cell, 1e-6) > fdm_max_gyroid_wall_cell_ratio:
            reject_reasons.append("gyroid wall/cell ratio too high for open FDM TPMS channels")
        if require_flat and not (top_cap and bottom_cap):
            reject_reasons.append("gyroid FDM specimen requires top and bottom caps for requested flat compression faces")
        if rel_density < 0.20:
            reject_reasons.append("gyroid relative_density below FDM continuous-shell rule")
        if layer_height > nozzle * 0.75:
            reject_reasons.append("layer_height_mm too high for FDM nozzle rule")
        if fdm_max_overhang > 55.0:
            warnings.append("fdm_max_unsupported_overhang_deg is permissive; 45 degrees is safer for FDM")
        if rel_density > 0.60:
            warnings.append("gyroid relative_density is high; print time and heat accumulation may increase")
    if expected_print_time > max_print_time:
        reject_reasons.append("expected_print_time_min exceeds max_print_time_min")
    if expected_mass > max_mass:
        reject_reasons.append("expected_mass_g exceeds max_mass_g")
    if bed_contact < 150.0:
        warnings.append("bed_contact_area_mm2 is low; adhesion risk may increase")

    ok = len(reject_reasons) == 0
    risk = 0.2 + min(0.6, len(reject_reasons) * 0.25 + len(warnings) * 0.05)
    return {
        "ok": ok,
        "tool": "geometry.check_manufacturability",
        "manufacturability_status": "pass" if ok else "fail",
        "risk_score": round(min(1.0, risk), 3),
        "expected_print_time_min": round(expected_print_time, 2),
        "expected_mass_g": round(expected_mass, 3),
        "minimum_feature_size_mm": round(min_feature, 3),
        "overhang_risk": "low",
        "unsupported_island_risk": "low",
        "bed_contact_area_mm2": round(bed_contact, 2),
        "compression_fixture_status": "pass",
        "reject_reasons": reject_reasons,
        "warnings": warnings,
    }


def _create_specimen_handoff(payload: dict[str, Any]) -> dict[str, Any]:
    specimen_id = _safe_segment(payload.get("specimen_id", "specimen"), "specimen")
    run_id = _safe_segment(payload.get("run_id", "run"), "run")
    geometry_result = payload.get("geometry_result", {})
    geometry_result = geometry_result if isinstance(geometry_result, dict) else {}
    stl_path = str(geometry_result.get("stl_path", ""))
    preview_image_path = str(geometry_result.get("preview_image_path", ""))
    handoff_path = Path(stl_path).parent / "handoff_package.json" if stl_path else Path("runs") / run_id / "specimens" / specimen_id / "handoff_package.json"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_package = {
        "run_id": run_id,
        "experiment_id": str(payload.get("experiment_id", "")),
        "specimen_id": specimen_id,
        "next_agent": str(payload.get("next_agent", "vision_agent")),
        "stl_path": stl_path,
        "preview_image_path": preview_image_path,
        "experiment_spec": payload.get("experiment_spec", {}),
        "geometry_result": geometry_result,
        "mesh_result": payload.get("mesh_result", {}),
        "manufacturability_result": payload.get("manufacturability_result", {}),
    }
    handoff_path.write_text(json.dumps(handoff_package, ensure_ascii=True, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "tool": "artifact.create_specimen_handoff",
        "handoff_status": "ready",
        "handoff_package_path": str(handoff_path),
        "handoff_package": handoff_package,
        "error_message": "",
    }


def register_mock_tools(registry: ToolRegistry) -> None:
    """Register default mock tool handlers."""
    registry.register("printer.prepare", _printer_prepare)
    registry.register("geometry.generate_metamaterial_stl", _generate_geometry_stl)
    registry.register("geometry.check_mesh_quality", _check_mesh_quality)
    registry.register("geometry.check_manufacturability", _check_manufacturability)
    registry.register("artifact.create_specimen_handoff", _create_specimen_handoff)
    registry.register("camera.capture", _camera_capture)
    registry.register("vision.equipment_cross_check", _vision_equipment_cross_check)
    registry.register("robot.pick_place", _robot_pick_place)
    registry.register("utm.run_protocol", _utm_run)
    registry.register("device.health", _device_health)
