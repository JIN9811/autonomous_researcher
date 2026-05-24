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
from random import Random
import re
from pathlib import Path
from typing import Any

from mcp_tools.tpms_geometry import generate_gyroid_stl_text, normalize_geometry_type, write_smooth_gyroid_stl
from mcp_tools.tool_registry import ToolRegistry

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
    return {"ok": True, "tool": "camera.capture", "frame_id": frame_id, "anomaly": False}


def _robot_pick_place(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "tool": "robot.pick_place", "grasp_score": 0.89, "task": payload.get("task", "pick_place")}


def _utm_run(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "tool": "utm.run_protocol", "result_file": "result/mock_result.csv", "cycles": 1}


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
        "tool_version": "tpms-geometry-v2",
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
        "tool_version": "tpms-geometry-v2",
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
    registry.register("robot.pick_place", _robot_pick_place)
    registry.register("utm.run_protocol", _utm_run)
    registry.register("device.health", _device_health)
