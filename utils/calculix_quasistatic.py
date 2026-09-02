"""Canonical transforms for displacement-controlled CalculiX compression."""

from __future__ import annotations

import math
import re
from typing import Any


def _number(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _fmt(value: float) -> str:
    return f"{float(value):g}"


def parse_gmsh_inp_mesh(text: str) -> tuple[dict[int, tuple[float, float, float]], list[str]]:
    """Return node coordinates and original mesh lines from a Gmsh Abaqus deck."""
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()
    nodes: dict[int, tuple[float, float, float]] = {}
    in_nodes = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("*"):
            in_nodes = stripped.lower().startswith("*node")
            continue
        if not in_nodes or not stripped or stripped.startswith("**"):
            continue
        parts = [part.strip() for part in stripped.split(",")]
        if len(parts) < 4:
            continue
        try:
            node_id = int(parts[0])
            xyz = tuple(float(parts[index]) for index in range(1, 4))
        except (TypeError, ValueError):
            continue
        if all(math.isfinite(value) for value in xyz):
            nodes[node_id] = (xyz[0], xyz[1], xyz[2])
    if not nodes:
        raise ValueError("CALCULIX_MESH_NODES_REQUIRED: no finite *NODE records found")
    return nodes, lines


def select_frictionless_boundary_nodes(
    nodes: dict[int, tuple[float, float, float]],
    *,
    tolerance_mm: float,
) -> dict[str, Any]:
    """Select horizontal face sets and minimal rigid-body stabilizer nodes."""
    if not nodes:
        raise ValueError("CALCULIX_MESH_NODES_REQUIRED: mesh is empty")
    z_values = [xyz[2] for xyz in nodes.values()]
    z_min = min(z_values)
    z_max = max(z_values)
    height = z_max - z_min
    if not math.isfinite(height) or height <= 0.0:
        raise ValueError("CALCULIX_MESH_HEIGHT_INVALID: mesh has no positive height")
    tolerance = max(abs(_number(tolerance_mm, 0.0)), height * 1e-6)
    bottom = sorted(node_id for node_id, xyz in nodes.items() if abs(xyz[2] - z_min) <= tolerance)
    top = sorted(node_id for node_id, xyz in nodes.items() if abs(xyz[2] - z_max) <= tolerance)
    if not bottom or not top:
        raise ValueError("CALCULIX_BOUNDARY_NODESET_REQUIRED: top or bottom face is empty")

    anchor_xy = min(bottom, key=lambda node_id: (nodes[node_id][1], nodes[node_id][0], node_id))
    ax, ay, _ = nodes[anchor_xy]
    same_edge = [
        node_id
        for node_id in bottom
        if node_id != anchor_xy and abs(nodes[node_id][1] - ay) <= tolerance
    ]
    candidates = same_edge or [node_id for node_id in bottom if node_id != anchor_xy]
    if not candidates:
        raise ValueError("CALCULIX_BOUNDARY_STABILIZER_REQUIRED: bottom face needs two nodes")
    anchor_y = max(
        candidates,
        key=lambda node_id: (abs(nodes[node_id][0] - ax), abs(nodes[node_id][1] - ay), -node_id),
    )
    return {
        "bottom_nodes": bottom,
        "top_nodes": top,
        "anchor_xy_node": anchor_xy,
        "anchor_y_node": anchor_y,
        "z_min_mm": z_min,
        "z_max_mm": z_max,
        "height_mm": height,
        "tolerance_mm": tolerance,
    }


def _nset(name: str, node_ids: list[int]) -> list[str]:
    lines = [f"*NSET,NSET={name}"]
    for start in range(0, len(node_ids), 16):
        lines.append(",".join(str(node_id) for node_id in node_ids[start : start + 16]))
    return lines


def _first_element_set(lines: list[str]) -> str:
    for line in lines:
        if not line.strip().lower().startswith("*element"):
            continue
        match = re.search(r"\belset\s*=\s*([^,\s]+)", line, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    raise ValueError("CALCULIX_ELEMENT_SET_REQUIRED: mesh has no named volume element set")


def build_compression_deck(
    mesh_text: str,
    *,
    material: dict[str, Any],
    target_displacement_mm: float,
    increments: dict[str, Any],
    boundary_tolerance_mm: float,
) -> tuple[str, dict[str, Any]]:
    """Append a nonlinear frictionless-face compression step to a Gmsh deck."""
    nodes, mesh_lines = parse_gmsh_inp_mesh(mesh_text)
    boundary = select_frictionless_boundary_nodes(nodes, tolerance_mm=boundary_tolerance_mm)
    target = abs(_number(target_displacement_mm, 0.0))
    if target <= 0.0 or target > boundary["height_mm"] * 0.8:
        raise ValueError("CALCULIX_TARGET_DISPLACEMENT_INVALID: target must be within 0-80% height")
    element_set = _first_element_set(mesh_lines)
    modulus = max(_number(material.get("elastic_modulus_mpa"), 1800.0), 1e-9)
    poisson = min(max(_number(material.get("poisson_ratio"), 0.35), -0.99), 0.499)
    plastic_curve = material.get("plastic_curve") if isinstance(material.get("plastic_curve"), list) else []
    if not plastic_curve and material.get("yield_strength_mpa") is not None:
        plastic_curve = [[_number(material.get("yield_strength_mpa"), 35.0), 0.0]]

    max_increments = max(1, int(_number(increments.get("max_increments"), 500)))
    initial = max(_number(increments.get("initial"), 0.01), 1e-12)
    period = max(_number(increments.get("time_period"), 1.0), initial)
    minimum = max(_number(increments.get("minimum"), 1e-7), 1e-15)
    maximum = max(_number(increments.get("maximum"), 0.02), initial)

    deck = list(mesh_lines)
    deck.extend(_nset("BOTTOM", boundary["bottom_nodes"]))
    deck.extend(_nset("TOP", boundary["top_nodes"]))
    deck.extend(_nset("ANCHOR_XY", [boundary["anchor_xy_node"]]))
    deck.extend(_nset("ANCHOR_Y", [boundary["anchor_y_node"]]))
    deck.extend(
        [
            "*MATERIAL,NAME=SPECIMEN_MATERIAL",
            "*ELASTIC",
            f"{_fmt(modulus)},{_fmt(poisson)}",
        ]
    )
    if plastic_curve:
        deck.append("*PLASTIC")
        for row in plastic_curve:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                deck.append(f"{_fmt(_number(row[0], 0.0))},{_fmt(_number(row[1], 0.0))}")
    deck.extend(
        [
            f"*SOLID SECTION,ELSET={element_set},MATERIAL=SPECIMEN_MATERIAL",
            "*AMPLITUDE,NAME=QS_RAMP",
            "0,0,1,1",
            f"*STEP,NLGEOM,INC={max_increments}",
            "*STATIC",
            f"{_fmt(initial)},{_fmt(period)},{_fmt(minimum)},{_fmt(maximum)}",
            "*BOUNDARY",
            "BOTTOM,3,3,0",
            "ANCHOR_XY,1,2,0",
            "ANCHOR_Y,2,2,0",
            "*BOUNDARY,AMPLITUDE=QS_RAMP",
            f"TOP,3,3,-{_fmt(target)}",
            "*NODE PRINT,NSET=TOP,TOTALS=ONLY,FREQUENCY=1",
            "RF",
            "*NODE PRINT,NSET=TOP,FREQUENCY=1",
            "U",
            "*NODE FILE,NSET=TOP,FREQUENCY=1",
            "U,RF",
            "*EL FILE,FREQUENCY=1",
            "S,E,PEEQ",
            "*END STEP",
        ]
    )
    manifest = {
        **boundary,
        "target_displacement_mm": target,
        "target_strain": target / boundary["height_mm"],
        "element_set": element_set,
        "frictionless_faces": True,
        "top_in_plane_constrained_dofs": 0,
        "bottom_in_plane_stabilizer_dofs": 3,
        "max_increments": max_increments,
    }
    return "\n".join(deck).rstrip() + "\n", manifest


def _canonical_curve(
    curve: list[dict[str, float]],
    *,
    target_displacement_mm: float,
    endpoint_tolerance_mm: float,
) -> tuple[list[dict[str, float]], bool]:
    target = abs(_number(target_displacement_mm, 0.0))
    tolerance = max(abs(_number(endpoint_tolerance_mm, 0.0)), max(target, 1.0) * 1e-8)
    points: dict[float, dict[str, float]] = {}
    for raw in curve:
        displacement = abs(_number(raw.get("displacement_mm"), float("nan")))
        force = abs(_number(raw.get("force_N"), float("nan")))
        step_time = _number(raw.get("step_time"), 0.0)
        if not all(math.isfinite(value) for value in (displacement, force, step_time)):
            continue
        key = round(displacement, 12)
        candidate = {
            "step_time": step_time,
            "displacement_mm": displacement,
            "force_N": force,
        }
        if key not in points or step_time >= points[key]["step_time"]:
            points[key] = candidate
    ordered = sorted(points.values(), key=lambda item: (item["displacement_mm"], item["step_time"]))
    if not ordered or ordered[0]["displacement_mm"] > tolerance:
        ordered.insert(0, {"step_time": 0.0, "displacement_mm": 0.0, "force_N": 0.0})
    elif ordered[0]["displacement_mm"] <= tolerance:
        ordered[0] = {"step_time": 0.0, "displacement_mm": 0.0, "force_N": 0.0}

    endpoint_reached = bool(ordered and target > 0.0 and ordered[-1]["displacement_mm"] >= target - tolerance)
    if not endpoint_reached:
        return ordered, False
    clipped: list[dict[str, float]] = []
    for point in ordered:
        displacement = point["displacement_mm"]
        if displacement < target - tolerance:
            clipped.append(point)
            continue
        if abs(displacement - target) <= tolerance:
            clipped.append({**point, "displacement_mm": target})
            break
        if not clipped:
            break
        previous = clipped[-1]
        span = displacement - previous["displacement_mm"]
        ratio = (target - previous["displacement_mm"]) / max(span, 1e-15)
        clipped.append(
            {
                "step_time": previous["step_time"] + ratio * (point["step_time"] - previous["step_time"]),
                "displacement_mm": target,
                "force_N": previous["force_N"] + ratio * (point["force_N"] - previous["force_N"]),
            }
        )
        break
    return clipped, bool(clipped and abs(clipped[-1]["displacement_mm"] - target) <= tolerance)


def curve_metrics(
    curve: list[dict[str, float]],
    *,
    target_displacement_mm: float,
    endpoint_tolerance_mm: float = 1e-6,
) -> dict[str, Any]:
    """Calculate comparable curve metrics without extrapolating a partial solve."""
    canonical, endpoint_reached = _canonical_curve(
        curve,
        target_displacement_mm=target_displacement_mm,
        endpoint_tolerance_mm=endpoint_tolerance_mm,
    )
    last_displacement = canonical[-1]["displacement_mm"] if canonical else 0.0
    peak_force = max((point["force_N"] for point in canonical), default=0.0)
    stiffness_window = abs(target_displacement_mm) * 0.05
    stiffness_points = [
        point
        for point in canonical
        if point["displacement_mm"] > 0.0 and point["displacement_mm"] <= stiffness_window
    ]
    if not stiffness_points:
        stiffness_points = [point for point in canonical if point["displacement_mm"] > 0.0][:1]
    slopes = [
        point["force_N"] / point["displacement_mm"]
        for point in stiffness_points
        if point["displacement_mm"] > 0.0
    ]
    stiffness = sum(slopes) / len(slopes) if slopes else 0.0
    energy: float | None = None
    if endpoint_reached:
        energy = 0.0
        for left, right in zip(canonical, canonical[1:]):
            energy += 0.5 * (left["force_N"] + right["force_N"]) * (
                right["displacement_mm"] - left["displacement_mm"]
            )
    return {
        "endpoint_reached": endpoint_reached,
        "target_displacement_mm": abs(float(target_displacement_mm)),
        "last_converged_displacement_mm": last_displacement,
        "peak_reaction_force_N": round(peak_force, 6),
        "initial_stiffness_N_per_mm": round(stiffness, 6),
        "energy_absorption_50pct_mJ": round(energy, 6) if energy is not None else None,
        "converged_increment_count": max(0, len(canonical) - 1),
    }


def parse_reaction_history(
    dat_text: str,
    *,
    target_displacement_mm: float,
    endpoint_tolerance_mm: float = 1e-6,
) -> dict[str, Any]:
    """Parse CalculiX TOP displacement and total reaction output from `.dat`."""
    displacement_by_time: dict[float, list[float]] = {}
    force_by_time: dict[float, float] = {}
    mode = ""
    active_time: float | None = None
    expect_total_force = False
    time_pattern = re.compile(r"\btime\s*[=:]?\s*([-+0-9.eE]+)", flags=re.IGNORECASE)
    for raw in str(dat_text or "").replace("\r", "\n").splitlines():
        line = raw.strip()
        lowered = line.lower()
        if "displacements" in lowered and "for set" in lowered:
            match = time_pattern.search(line)
            active_time = float(match.group(1)) if match else None
            mode = "displacement"
            expect_total_force = False
            continue
        if "total force" in lowered and "for set" in lowered:
            match = time_pattern.search(line)
            active_time = float(match.group(1)) if match else None
            mode = "force"
            expect_total_force = True
            continue
        if "forces" in lowered and "for set" in lowered:
            match = time_pattern.search(line)
            active_time = float(match.group(1)) if match else None
            mode = "force"
            expect_total_force = False
            continue
        if mode == "force" and "total force" in lowered:
            expect_total_force = True
            continue
        if not line or re.fullmatch(r"-+", line) or active_time is None:
            continue
        values: list[float] = []
        for token in re.split(r"[\s,]+", line):
            try:
                value = float(token)
            except ValueError:
                continue
            if math.isfinite(value):
                values.append(value)
        if mode == "displacement" and len(values) >= 4:
            displacement_by_time.setdefault(active_time, []).append(values[-1])
        elif mode == "force" and expect_total_force and len(values) >= 3:
            force_by_time[active_time] = values[-1]
            expect_total_force = False

    curve: list[dict[str, float]] = []
    for step_time in sorted(set(displacement_by_time) & set(force_by_time)):
        displacements = displacement_by_time[step_time]
        if not displacements:
            continue
        curve.append(
            {
                "step_time": step_time,
                "displacement_mm": abs(sum(displacements) / len(displacements)),
                "force_N": abs(force_by_time[step_time]),
            }
        )
    canonical, endpoint_reached = _canonical_curve(
        curve,
        target_displacement_mm=target_displacement_mm,
        endpoint_tolerance_mm=endpoint_tolerance_mm,
    )
    metrics = curve_metrics(
        canonical,
        target_displacement_mm=target_displacement_mm,
        endpoint_tolerance_mm=endpoint_tolerance_mm,
    )
    return {
        "curve": canonical,
        "endpoint_reached": endpoint_reached,
        "metrics": metrics,
    }
