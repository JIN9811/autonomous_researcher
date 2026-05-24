"""
TPMS geometry helpers used by the existing geometry MCP tool contract.

This module is intentionally dependency-light. If numpy/scikit-image/trimesh
are available, callers can write a smooth marching-cubes gyroid. Otherwise the
fallback marching-tetrahedra emitter still produces a visible gyroid surface
from the same input payload variables.
"""

from __future__ import annotations

import math
from pathlib import Path
from random import Random
from typing import Any


def normalize_geometry_type(value: Any) -> str:
    """Normalize legacy and human-facing geometry names to runtime names."""
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "": "gyroid",
        "tpms": "gyroid",
        "tpms_gyroid": "gyroid",
        "gyroid_tpms": "gyroid",
        "metamaterial": "gyroid",
        "bending_dominated": "gyroid",
        "bending_dominated_lattice": "gyroid",
        "lattice": "gyroid",
        "compression_cube": "gyroid",
        "cube": "gyroid",
        "bcc": "lattice_bcc",
        "body_centered": "lattice_bcc",
        "body_centered_cubic": "lattice_bcc",
        "fcc": "lattice_fcc",
        "octet": "lattice_octet",
        "octet_lattice": "lattice_octet",
        "reentrant": "auxetic_reentrant",
        "re_entrant": "auxetic_reentrant",
    }
    return aliases.get(text, text)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool) -> bool:
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


def _vector3(value: Any, default: list[float]) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        return list(default)
    out: list[float] = []
    for idx, item in enumerate(value):
        out.append(_safe_float(item, default[idx]))
    return out


def tpms_thickness_level(
    *,
    tpms_thickness: Any = None,
    wall_thickness_mm: float,
    cell_size_mm: float,
    relative_density: float,
) -> float:
    """Return the dimensionless |F| threshold for gyroid shell thickness."""
    physical_min = _clamp(0.50 * wall_thickness_mm * (2.0 * math.pi / max(cell_size_mm, 1e-6)), 0.18, 0.68)
    explicit = _safe_float(tpms_thickness, -1.0)
    if explicit > 0.0:
        return _clamp(max(explicit, physical_min), 0.18, 0.75)
    wall_ratio = wall_thickness_mm / max(cell_size_mm, 1e-6)
    density_threshold = 0.10 + 0.40 * relative_density + min(0.06, 0.20 * wall_ratio)
    return _clamp(max(density_threshold, physical_min), 0.18, 0.68)


def _cap_skin_thickness(skin_thickness_mm: Any, top_bottom_cap: bool, z_dim: float) -> float:
    """Resolve the physical flat top/bottom cap thickness for compression faces."""
    if not top_bottom_cap:
        return 0.0
    requested = _safe_float(skin_thickness_mm, 0.8)
    if requested <= 0.0:
        requested = 0.8
    return _clamp(requested, 0.2, max(0.2, z_dim / 5.0))


def _cap_skin_config(
    *,
    skin_thickness_mm: Any,
    top_bottom_cap: bool,
    top_cap_enabled: Any = None,
    bottom_cap_enabled: Any = None,
    z_dim: float,
) -> tuple[float, bool, bool]:
    """Resolve independent top/bottom cap flags while preserving legacy callers."""
    legacy_cap = bool(top_bottom_cap)
    if top_cap_enabled is None and bottom_cap_enabled is None:
        top_cap = legacy_cap
        bottom_cap = legacy_cap
    else:
        top_cap = _safe_bool(top_cap_enabled, False)
        bottom_cap = _safe_bool(bottom_cap_enabled, legacy_cap)
    cap_skin = _cap_skin_thickness(skin_thickness_mm, top_cap or bottom_cap, z_dim)
    if cap_skin <= 0.0:
        return 0.0, False, False
    return cap_skin, top_cap, bottom_cap


def _cell_counts(size: list[float], cell_size_mm: float, anisotropy_ratio: float) -> tuple[int, int, int]:
    x, y, z = [max(float(item), 1.0) for item in size]
    cell = max(float(cell_size_mm), 1.0)
    anisotropy = _clamp(float(anisotropy_ratio), 0.5, 2.0)
    return (
        max(1, round(x / cell)),
        max(1, round(y / cell)),
        max(1, round((z / cell) * anisotropy)),
    )


def _gyroid_value(
    x: float,
    y: float,
    z: float,
    *,
    size: list[float],
    cell_counts_xyz: tuple[int, int, int],
    phase_rad: float,
) -> float:
    sx, sy, sz = [max(float(item), 1e-6) for item in size]
    cx, cy, cz = cell_counts_xyz
    kx = 2.0 * math.pi * cx / sx
    ky = 2.0 * math.pi * cy / sy
    kz = 2.0 * math.pi * cz / sz
    return (
        math.sin(kx * x + phase_rad) * math.cos(ky * y)
        + math.sin(ky * y + phase_rad * 0.5) * math.cos(kz * z)
        + math.sin(kz * z + phase_rad * 0.25) * math.cos(kx * x)
    )


def _facet(lines: list[str], normal: tuple[int, int, int], vertices: tuple[tuple[float, float, float], ...]) -> None:
    lines.extend(
        [
            f"  facet normal {normal[0]} {normal[1]} {normal[2]}",
            "    outer loop",
            f"      vertex {vertices[0][0]:.6f} {vertices[0][1]:.6f} {vertices[0][2]:.6f}",
            f"      vertex {vertices[1][0]:.6f} {vertices[1][1]:.6f} {vertices[1][2]:.6f}",
            f"      vertex {vertices[2][0]:.6f} {vertices[2][1]:.6f} {vertices[2][2]:.6f}",
            "    endloop",
            "  endfacet",
        ]
    )


def _triangle_normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (nx / length, ny / length, nz / length)


def _triangle_facet(lines: list[str], vertices: tuple[tuple[float, float, float], ...]) -> None:
    normal = _triangle_normal(vertices[0], vertices[1], vertices[2])
    lines.extend(
        [
            f"  facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}",
            "    outer loop",
            f"      vertex {vertices[0][0]:.6f} {vertices[0][1]:.6f} {vertices[0][2]:.6f}",
            f"      vertex {vertices[1][0]:.6f} {vertices[1][1]:.6f} {vertices[1][2]:.6f}",
            f"      vertex {vertices[2][0]:.6f} {vertices[2][1]:.6f} {vertices[2][2]:.6f}",
            "    endloop",
            "  endfacet",
        ]
    )


def _add_quad_face(
    lines: list[str],
    *,
    normal: tuple[int, int, int],
    quad: tuple[tuple[float, float, float], ...],
) -> None:
    _facet(lines, normal, (quad[0], quad[1], quad[2]))
    _facet(lines, normal, (quad[0], quad[2], quad[3]))


def _interpolate_iso(
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
    v0: float,
    v1: float,
) -> tuple[float, float, float]:
    denom = v0 - v1
    t = 0.5 if abs(denom) <= 1e-12 else v0 / denom
    t = _clamp(t, 0.0, 1.0)
    return (
        p0[0] + (p1[0] - p0[0]) * t,
        p0[1] + (p1[1] - p0[1]) * t,
        p0[2] + (p1[2] - p0[2]) * t,
    )


def _add_tetra_iso_facets(
    lines: list[str],
    points: tuple[tuple[float, float, float], ...],
    values: tuple[float, float, float, float],
) -> int:
    inside = [idx for idx, value in enumerate(values) if value <= 0.0]
    outside = [idx for idx, value in enumerate(values) if value > 0.0]
    if len(inside) == 0 or len(inside) == 4:
        return 0
    if len(inside) == 1:
        i0 = inside[0]
        tri = tuple(_interpolate_iso(points[i0], points[oi], values[i0], values[oi]) for oi in outside)
        _triangle_facet(lines, tri)
        return 1
    if len(inside) == 3:
        o0 = outside[0]
        tri = tuple(_interpolate_iso(points[o0], points[ii], values[o0], values[ii]) for ii in inside)
        _triangle_facet(lines, (tri[0], tri[2], tri[1]))
        return 1

    i0, i1 = inside
    o0, o1 = outside
    p00 = _interpolate_iso(points[i0], points[o0], values[i0], values[o0])
    p01 = _interpolate_iso(points[i0], points[o1], values[i0], values[o1])
    p10 = _interpolate_iso(points[i1], points[o0], values[i1], values[o0])
    p11 = _interpolate_iso(points[i1], points[o1], values[i1], values[o1])
    _triangle_facet(lines, (p00, p01, p10))
    _triangle_facet(lines, (p01, p11, p10))
    return 2


def _add_box(
    lines: list[str],
    *,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z0: float,
    z1: float,
) -> int:
    vertices = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    faces = [
        ((0, 1, 2, 3), (0, 0, -1)),
        ((4, 7, 6, 5), (0, 0, 1)),
        ((0, 4, 5, 1), (0, -1, 0)),
        ((1, 5, 6, 2), (1, 0, 0)),
        ((2, 6, 7, 3), (0, 1, 0)),
        ((3, 7, 4, 0), (-1, 0, 0)),
    ]
    for indices, normal in faces:
        quad = tuple(vertices[idx] for idx in indices)
        _add_quad_face(lines, normal=normal, quad=quad)
    return 12


def _add_boundary_closure_facets(
    lines: list[str],
    *,
    values: list[list[list[float]]],
    xs: list[float],
    ys: list[float],
    zs: list[float],
    x_dim: float,
    y_dim: float,
    z_dim: float,
    include_bottom_z: bool,
    include_top_z: bool,
) -> int:
    """Close TPMS cuts at the specimen bounding box so the mesh is printable."""
    nx = len(xs) - 1
    ny = len(ys) - 1
    nz = len(zs) - 1
    triangle_count = 0

    def inside(*corners: tuple[int, int, int]) -> bool:
        return any(values[ix][iy][iz] <= 0.0 for ix, iy, iz in corners)

    for side_ix, x_coord, normal in ((0, -x_dim / 2.0, (-1, 0, 0)), (nx, x_dim / 2.0, (1, 0, 0))):
        for iy in range(ny):
            for iz in range(nz):
                corners = ((side_ix, iy, iz), (side_ix, iy + 1, iz), (side_ix, iy + 1, iz + 1), (side_ix, iy, iz + 1))
                if not inside(*corners):
                    continue
                quad = (
                    (x_coord, -y_dim / 2.0 + ys[iy], -z_dim / 2.0 + zs[iz]),
                    (x_coord, -y_dim / 2.0 + ys[iy + 1], -z_dim / 2.0 + zs[iz]),
                    (x_coord, -y_dim / 2.0 + ys[iy + 1], -z_dim / 2.0 + zs[iz + 1]),
                    (x_coord, -y_dim / 2.0 + ys[iy], -z_dim / 2.0 + zs[iz + 1]),
                )
                if normal[0] > 0:
                    quad = (quad[0], quad[3], quad[2], quad[1])
                _add_quad_face(lines, normal=normal, quad=quad)
                triangle_count += 2

    for side_iy, y_coord, normal in ((0, -y_dim / 2.0, (0, -1, 0)), (ny, y_dim / 2.0, (0, 1, 0))):
        for ix in range(nx):
            for iz in range(nz):
                corners = ((ix, side_iy, iz), (ix + 1, side_iy, iz), (ix + 1, side_iy, iz + 1), (ix, side_iy, iz + 1))
                if not inside(*corners):
                    continue
                quad = (
                    (-x_dim / 2.0 + xs[ix], y_coord, -z_dim / 2.0 + zs[iz]),
                    (-x_dim / 2.0 + xs[ix + 1], y_coord, -z_dim / 2.0 + zs[iz]),
                    (-x_dim / 2.0 + xs[ix + 1], y_coord, -z_dim / 2.0 + zs[iz + 1]),
                    (-x_dim / 2.0 + xs[ix], y_coord, -z_dim / 2.0 + zs[iz + 1]),
                )
                if normal[1] < 0:
                    quad = (quad[0], quad[3], quad[2], quad[1])
                _add_quad_face(lines, normal=normal, quad=quad)
                triangle_count += 2

    for side_iz, z_coord, normal in ((0, -z_dim / 2.0, (0, 0, -1)), (nz, z_dim / 2.0, (0, 0, 1))):
        if side_iz == 0 and not include_bottom_z:
            continue
        if side_iz == nz and not include_top_z:
            continue
        for ix in range(nx):
            for iy in range(ny):
                corners = ((ix, iy, side_iz), (ix + 1, iy, side_iz), (ix + 1, iy + 1, side_iz), (ix, iy + 1, side_iz))
                if not inside(*corners):
                    continue
                quad = (
                    (-x_dim / 2.0 + xs[ix], -y_dim / 2.0 + ys[iy], z_coord),
                    (-x_dim / 2.0 + xs[ix + 1], -y_dim / 2.0 + ys[iy], z_coord),
                    (-x_dim / 2.0 + xs[ix + 1], -y_dim / 2.0 + ys[iy + 1], z_coord),
                    (-x_dim / 2.0 + xs[ix], -y_dim / 2.0 + ys[iy + 1], z_coord),
                )
                if normal[2] < 0:
                    quad = (quad[0], quad[3], quad[2], quad[1])
                _add_quad_face(lines, normal=normal, quad=quad)
                triangle_count += 2
    return triangle_count


def generate_gyroid_stl_text(
    *,
    name: str,
    specimen_size_mm: Any,
    wall_thickness_mm: float,
    cell_size_mm: float,
    relative_density: float = 0.32,
    anisotropy_ratio: float = 1.0,
    orientation_deg: float = 0.0,
    defect_seed: int = 1,
    defect_ratio: float = 0.0,
    skin_thickness_mm: float = 0.0,
    top_bottom_cap: bool = False,
    top_cap_enabled: Any = None,
    bottom_cap_enabled: Any = None,
    tpms_thickness: Any = None,
    resolution: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Generate a dependency-free marching-tetrahedra gyroid STL and metadata."""
    size = _vector3(specimen_size_mm, [30.0, 30.0, 30.0])
    x_dim, y_dim, z_dim = [max(float(item), 1.0) for item in size]
    max_dim = max(x_dim, y_dim, z_dim)
    requested = _safe_int(resolution, 0)
    base_resolution = requested or round(max_dim / 1.05)
    base_resolution = max(18, min(72, base_resolution))
    nx = max(10, min(96, round(base_resolution * x_dim / max_dim)))
    ny = max(10, min(96, round(base_resolution * y_dim / max_dim)))
    nz = max(10, min(96, round(base_resolution * z_dim / max_dim)))
    dx, dy, dz = x_dim / nx, y_dim / ny, z_dim / nz

    rel_density = _clamp(float(relative_density), 0.05, 0.85)
    wall = max(float(wall_thickness_mm), 0.05)
    cell = max(float(cell_size_mm), wall * 2.0, 1.0)
    thickness_level = tpms_thickness_level(
        tpms_thickness=tpms_thickness,
        wall_thickness_mm=wall,
        cell_size_mm=cell,
        relative_density=rel_density,
    )
    cell_counts_xyz = _cell_counts(size, cell, float(anisotropy_ratio))
    phase_rad = math.radians(float(orientation_deg))
    defect = _clamp(float(defect_ratio), 0.0, 0.35)
    cap_skin, top_cap, bottom_cap = _cap_skin_config(
        skin_thickness_mm=skin_thickness_mm,
        top_bottom_cap=top_bottom_cap,
        top_cap_enabled=top_cap_enabled,
        bottom_cap_enabled=bottom_cap_enabled,
        z_dim=z_dim,
    )
    rng = Random(int(defect_seed))

    xs = [idx * dx for idx in range(nx + 1)]
    ys = [idx * dy for idx in range(ny + 1)]
    zs = [idx * dz for idx in range(nz + 1)]
    values = [
        [
            [
                abs(
                    _gyroid_value(
                        xs[ix],
                        ys[iy],
                        zs[iz],
                        size=[x_dim, y_dim, z_dim],
                        cell_counts_xyz=cell_counts_xyz,
                        phase_rad=phase_rad,
                    )
                )
                - thickness_level
                for iz in range(nz + 1)
            ]
            for iy in range(ny + 1)
        ]
        for ix in range(nx + 1)
    ]

    cube_offsets = (
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
    )
    tetrahedra = (
        (0, 5, 1, 6),
        (0, 1, 2, 6),
        (0, 2, 3, 6),
        (0, 3, 7, 6),
        (0, 7, 4, 6),
        (0, 4, 5, 6),
    )
    lines = [f"solid {name}"]
    triangle_count = 0
    sampled_inside = 0
    sampled_total = (nx + 1) * (ny + 1) * (nz + 1)
    for ix in range(nx + 1):
        for iy in range(ny + 1):
            for iz in range(nz + 1):
                if values[ix][iy][iz] <= 0.0:
                    sampled_inside += 1

    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                if defect > 0.0 and rng.random() < defect:
                    continue
                cube_points: list[tuple[float, float, float]] = []
                cube_values: list[float] = []
                for ox, oy, oz in cube_offsets:
                    cube_points.append((-x_dim / 2.0 + xs[ix + ox], -y_dim / 2.0 + ys[iy + oy], -z_dim / 2.0 + zs[iz + oz]))
                    cube_values.append(values[ix + ox][iy + oy][iz + oz])
                for tetra in tetrahedra:
                    tetra_points = tuple(cube_points[idx] for idx in tetra)
                    tetra_values = tuple(cube_values[idx] for idx in tetra)
                    triangle_count += _add_tetra_iso_facets(lines, tetra_points, tetra_values)

    closure_triangle_count = _add_boundary_closure_facets(
        lines,
        values=values,
        xs=xs,
        ys=ys,
        zs=zs,
        x_dim=x_dim,
        y_dim=y_dim,
        z_dim=z_dim,
        include_bottom_z=not bool(bottom_cap),
        include_top_z=not bool(top_cap),
    )
    triangle_count += closure_triangle_count

    top_cap_triangle_count = 0
    bottom_cap_triangle_count = 0
    if cap_skin > 0.0 and bottom_cap:
        cap_t = cap_skin
        bottom_cap_triangle_count += _add_box(
            lines,
            x0=-x_dim / 2.0,
            x1=x_dim / 2.0,
            y0=-y_dim / 2.0,
            y1=y_dim / 2.0,
            z0=-z_dim / 2.0,
            z1=-z_dim / 2.0 + cap_t,
        )
    if cap_skin > 0.0 and top_cap:
        cap_t = cap_skin
        top_cap_triangle_count += _add_box(
            lines,
            x0=-x_dim / 2.0,
            x1=x_dim / 2.0,
            y0=-y_dim / 2.0,
            y1=y_dim / 2.0,
            z0=z_dim / 2.0 - cap_t,
            z1=z_dim / 2.0,
        )
    cap_triangle_count = top_cap_triangle_count + bottom_cap_triangle_count
    triangle_count += cap_triangle_count
    lines.append(f"endsolid {name}")

    solid_fraction = sampled_inside / max(sampled_total, 1)
    cap_volume = x_dim * y_dim * cap_skin * int(top_cap + bottom_cap)
    estimated_volume = x_dim * y_dim * z_dim * solid_fraction + cap_volume
    metadata = {
        "generator_backend": "tpms_gyroid_marching_tetra_fallback",
        "tpms_surface": "gyroid",
        "tpms_equation": "sin(x)cos(y)+sin(y)cos(z)+sin(z)cos(x)=0",
        "tpms_thickness": round(thickness_level, 5),
        "tpms_resolution": [nx + 1, ny + 1, nz + 1],
        "cell_count_xyz": list(cell_counts_xyz),
        "sampled_inside_count": sampled_inside,
        "boundary_closure_triangle_count": closure_triangle_count,
        "cap_triangle_count": cap_triangle_count,
        "top_cap_enabled": top_cap,
        "bottom_cap_enabled": bottom_cap,
        "top_bottom_cap": bool(top_cap or bottom_cap),
        "top_cap_triangle_count": top_cap_triangle_count,
        "bottom_cap_triangle_count": bottom_cap_triangle_count,
        "cap_skin_applied": bool((top_cap or bottom_cap) and cap_skin > 0.0),
        "cap_skin_thickness_mm": round(cap_skin, 4),
        "triangle_count": triangle_count,
        "estimated_volume_mm3": round(estimated_volume, 3),
        "solid_fraction": round(solid_fraction, 5),
        "printability_mode": "fdm_closed_shell",
        "minimum_feature_size_assumption_mm": round(wall, 4),
    }
    return "\n".join(lines) + "\n", metadata


def write_smooth_gyroid_stl(
    *,
    stl_path: Path,
    name: str,
    specimen_size_mm: Any,
    wall_thickness_mm: float,
    cell_size_mm: float,
    relative_density: float = 0.32,
    anisotropy_ratio: float = 1.0,
    orientation_deg: float = 0.0,
    defect_seed: int = 1,
    defect_ratio: float = 0.0,
    skin_thickness_mm: float = 0.0,
    top_bottom_cap: bool = False,
    top_cap_enabled: Any = None,
    bottom_cap_enabled: Any = None,
    tpms_thickness: Any = None,
    resolution: Any = None,
) -> dict[str, Any] | None:
    """Write a smooth marching-cubes gyroid STL when optional deps exist."""
    try:
        import numpy as np
        from skimage import measure
        import trimesh
    except ImportError:
        return None

    size = _vector3(specimen_size_mm, [30.0, 30.0, 30.0])
    x_dim, y_dim, z_dim = [max(float(item), 1.0) for item in size]
    max_dim = max(x_dim, y_dim, z_dim)
    requested = _safe_int(resolution, 0)
    n = requested or round(max_dim * 3.0)
    n = max(48, min(160, n))
    rel_density = _clamp(float(relative_density), 0.05, 0.85)
    wall = max(float(wall_thickness_mm), 0.05)
    cell = max(float(cell_size_mm), wall * 2.0, 1.0)
    thickness_level = tpms_thickness_level(
        tpms_thickness=tpms_thickness,
        wall_thickness_mm=wall,
        cell_size_mm=cell,
        relative_density=rel_density,
    )
    cx, cy, cz = _cell_counts(size, cell, float(anisotropy_ratio))
    phase_rad = math.radians(float(orientation_deg))
    xs = np.linspace(0.0, x_dim, n)
    ys = np.linspace(0.0, y_dim, n)
    zs = np.linspace(0.0, z_dim, n)
    x_grid, y_grid, z_grid = np.meshgrid(xs, ys, zs, indexing="ij")
    kx = 2.0 * np.pi * cx / x_dim
    ky = 2.0 * np.pi * cy / y_dim
    kz = 2.0 * np.pi * cz / z_dim
    field = (
        np.sin(kx * x_grid + phase_rad) * np.cos(ky * y_grid)
        + np.sin(ky * y_grid + phase_rad * 0.5) * np.cos(kz * z_grid)
        + np.sin(kz * z_grid + phase_rad * 0.25) * np.cos(kx * x_grid)
    )
    levelset = np.abs(field) - thickness_level
    cap_skin, top_cap, bottom_cap = _cap_skin_config(
        skin_thickness_mm=skin_thickness_mm,
        top_bottom_cap=top_bottom_cap,
        top_cap_enabled=top_cap_enabled,
        bottom_cap_enabled=bottom_cap_enabled,
        z_dim=z_dim,
    )
    bottom_cap_mask = zs <= cap_skin if bottom_cap and cap_skin > 0.0 else np.zeros_like(zs, dtype=bool)
    top_cap_mask = zs >= z_dim - cap_skin if top_cap and cap_skin > 0.0 else np.zeros_like(zs, dtype=bool)
    if bottom_cap and cap_skin > 0.0:
        levelset[:, :, zs <= cap_skin] = -thickness_level
    if top_cap and cap_skin > 0.0:
        levelset[:, :, zs >= z_dim - cap_skin] = -thickness_level
    defect = _clamp(float(defect_ratio), 0.0, 0.35)
    if defect > 0.0:
        rng = np.random.default_rng(int(defect_seed))
        void_mask = rng.random(levelset.shape) < defect
        if bottom_cap and cap_skin > 0.0:
            void_mask[:, :, bottom_cap_mask] = False
        if top_cap and cap_skin > 0.0:
            void_mask[:, :, top_cap_mask] = False
        levelset[void_mask] = max(float(levelset.max()), 1.0)

    spacing = (x_dim / (n - 1), y_dim / (n - 1), z_dim / (n - 1))
    outside_value = max(float(levelset.max()), 1.0)
    padded_levelset = np.pad(levelset.astype(np.float32), 1, mode="constant", constant_values=outside_value)
    verts, faces, _normals, _values = measure.marching_cubes(
        padded_levelset,
        level=0.0,
        spacing=spacing,
    )
    verts[:, 0] -= spacing[0] + x_dim / 2.0
    verts[:, 1] -= spacing[1] + y_dim / 2.0
    verts[:, 2] -= spacing[2] + z_dim / 2.0
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    components = mesh.split(only_watertight=False)
    component_count_before = len(components)
    removed_component_count = 0
    removed_triangle_count = 0
    if component_count_before > 1:
        largest = max(components, key=lambda item: len(item.faces))
        removed_component_count = component_count_before - 1
        removed_triangle_count = int(len(mesh.faces) - len(largest.faces))
        mesh = largest
        mesh.remove_unreferenced_vertices()
    mesh.metadata["name"] = name
    mesh.export(stl_path)
    solid_fraction = float(np.count_nonzero(levelset <= 0.0)) / float(levelset.size)
    return {
        "generator_backend": "tpms_gyroid_marching_cubes",
        "tpms_surface": "gyroid",
        "tpms_equation": "sin(x)cos(y)+sin(y)cos(z)+sin(z)cos(x)=0",
        "tpms_thickness": round(thickness_level, 5),
        "tpms_resolution": [n, n, n],
        "cell_count_xyz": [cx, cy, cz],
        "vertex_count": int(len(mesh.vertices)),
        "triangle_count": int(len(mesh.faces)),
        "connected_component_count_before_cleanup": component_count_before,
        "connected_component_count_after_cleanup": 1 if len(mesh.faces) else 0,
        "removed_disconnected_component_count": removed_component_count,
        "removed_disconnected_triangle_count": removed_triangle_count,
        "component_cleanup_action": "kept_largest_component" if removed_component_count else "none",
        "top_cap_enabled": top_cap,
        "bottom_cap_enabled": bottom_cap,
        "top_bottom_cap": bool(top_cap or bottom_cap),
        "cap_skin_applied": bool((top_cap or bottom_cap) and cap_skin > 0.0),
        "cap_skin_thickness_mm": round(cap_skin, 4),
        "cap_voxel_layer_count": int(np.count_nonzero(bottom_cap_mask) + np.count_nonzero(top_cap_mask)) if cap_skin > 0.0 else 0,
        "bottom_cap_voxel_layer_count": int(np.count_nonzero(bottom_cap_mask)) if cap_skin > 0.0 else 0,
        "top_cap_voxel_layer_count": int(np.count_nonzero(top_cap_mask)) if cap_skin > 0.0 else 0,
        "estimated_volume_mm3": round(x_dim * y_dim * z_dim * solid_fraction, 3),
        "solid_fraction": round(solid_fraction, 5),
        "printability_mode": "fdm_closed_shell",
        "boundary_padding_voxels": 1,
        "minimum_feature_size_assumption_mm": round(wall, 4),
    }
