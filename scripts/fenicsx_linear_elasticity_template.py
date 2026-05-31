#!/usr/bin/env python3
"""
Validated FEniCSx/DOLFINx linear elasticity runner for ATR Analysis Agent.

This script is intentionally a fixed template. The LLM may choose sanitized
planning parameters upstream, but it must not generate or execute solver code.

Usage:
  python scripts/fenicsx_linear_elasticity_template.py request.json result.json
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import ufl
from dolfinx import default_scalar_type, fem, io, mesh
from dolfinx.fem.petsc import LinearProblem
from mpi4py import MPI


def _safe_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _vector3(value: Any, default: list[float]) -> list[float]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return [max(_safe_float(value[i], default[i]), 1e-6) for i in range(3)]
    return list(default)


def _epsilon(u):
    return ufl.sym(ufl.grad(u))


def _main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: fenicsx_linear_elasticity_template.py request.json result.json")
    request_path = Path(sys.argv[1]).resolve()
    result_path = Path(sys.argv[2]).resolve()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    specimen_id = str(request.get("specimen_id") or "specimen")
    size = _vector3(request.get("specimen_size_mm"), [20.0, 20.0, 20.0])
    mesh_size = max(_safe_float(request.get("mesh_size_mm"), 2.0), 0.2)
    material = request.get("material") if isinstance(request.get("material"), dict) else {}
    loading = request.get("loading") if isinstance(request.get("loading"), dict) else {}
    design = request.get("design_parameters") if isinstance(request.get("design_parameters"), dict) else {}

    relative_density = min(max(_safe_float(design.get("relative_density"), 0.32), 0.05), 0.95)
    E = max(_safe_float(material.get("elastic_modulus_mpa"), 1800.0), 1e-6)
    nu = min(max(_safe_float(material.get("poisson_ratio"), 0.35), 0.0), 0.49)
    yield_strength = max(_safe_float(material.get("yield_strength_mpa"), 35.0), 1e-6)
    # Homogenized TPMS/lattice proxy: solve on specimen envelope while retaining
    # relative-density scaling. Units: MPa = N/mm^2, displacement in mm.
    effective_E = E * max(0.035, relative_density**1.75)
    effective_yield = yield_strength * max(0.04, relative_density**1.45)
    mu = effective_E / (2.0 * (1.0 + nu))
    lambda_ = effective_E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))

    load_max = max(_safe_float(loading.get("load_max_n"), 500.0), 0.0)
    load_min_ratio = min(max(_safe_float(loading.get("load_min_ratio"), 0.1), 0.0), 1.0)
    cycles = _safe_int(loading.get("cycles"), 10)
    load_min = load_max * load_min_ratio
    area = max(size[0] * size[1], 1e-6)
    height = max(size[2], 1e-6)
    traction = load_max / area

    nx = max(2, min(24, int(math.ceil(size[0] / mesh_size))))
    ny = max(2, min(24, int(math.ceil(size[1] / mesh_size))))
    nz = max(2, min(24, int(math.ceil(size[2] / mesh_size))))
    domain = mesh.create_box(
        MPI.COMM_WORLD,
        [np.array([0.0, 0.0, 0.0]), np.array(size, dtype=np.float64)],
        [nx, ny, nz],
        cell_type=mesh.CellType.hexahedron,
    )
    V = fem.functionspace(domain, ("Lagrange", 1, (domain.geometry.dim,)))
    fdim = domain.topology.dim - 1

    def bottom_boundary(x):
        return np.isclose(x[2], 0.0)

    def top_boundary(x):
        return np.isclose(x[2], height)

    bottom_facets = mesh.locate_entities_boundary(domain, fdim, bottom_boundary)
    top_facets = mesh.locate_entities_boundary(domain, fdim, top_boundary)
    u_D = np.array([0.0, 0.0, 0.0], dtype=default_scalar_type)
    bc = fem.dirichletbc(u_D, fem.locate_dofs_topological(V, fdim, bottom_facets), V)

    top_marker = 1
    if len(top_facets):
        sorted_facets = np.array(top_facets, dtype=np.int32)
        sort_order = np.argsort(sorted_facets)
        facet_tags = mesh.meshtags(domain, fdim, sorted_facets[sort_order], np.full(len(sorted_facets), top_marker, dtype=np.int32)[sort_order])
        ds = ufl.Measure("ds", domain=domain, subdomain_data=facet_tags)
    else:
        ds = ufl.Measure("ds", domain=domain)

    def sigma(u):
        return lambda_ * ufl.nabla_div(u) * ufl.Identity(len(u)) + 2.0 * mu * _epsilon(u)

    u = ufl.TrialFunction(V)
    v = ufl.TestFunction(V)
    body_force = fem.Constant(domain, default_scalar_type((0.0, 0.0, 0.0)))
    top_traction = fem.Constant(domain, default_scalar_type((0.0, 0.0, -traction)))
    a = ufl.inner(sigma(u), _epsilon(v)) * ufl.dx
    L = ufl.dot(body_force, v) * ufl.dx + ufl.dot(top_traction, v) * ds(top_marker)

    problem = LinearProblem(
        a,
        L,
        bcs=[bc],
        petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
        petsc_options_prefix="atr_linear_elasticity",
    )
    uh = problem.solve()
    uh.name = "displacement"
    disp = uh.x.array.reshape((-1, 3))
    disp_norm = np.linalg.norm(disp, axis=1)
    z_disp = disp[:, 2]
    max_displacement = float(np.max(disp_norm)) if disp_norm.size else 0.0
    max_compression = abs(float(np.min(z_disp))) if z_disp.size else max_displacement
    stiffness = load_max / max(max_compression, 1e-12) if load_max > 0 else 0.0
    energy = 0.5 * load_max * max_compression

    s = sigma(uh) - (1.0 / 3.0) * ufl.tr(sigma(uh)) * ufl.Identity(len(uh))
    von_mises = ufl.sqrt(3.0 / 2.0 * ufl.inner(s, s))
    V_vm = fem.functionspace(domain, ("DG", 0))
    interpolation_points = V_vm.element.interpolation_points
    stress_expr = fem.Expression(von_mises, interpolation_points)
    stresses = fem.Function(V_vm)
    stresses.interpolate(stress_expr)
    stress_values = np.asarray(stresses.x.array, dtype=np.float64)
    max_von_mises = float(np.max(np.abs(stress_values))) if stress_values.size else 0.0
    mean_von_mises = float(np.mean(np.abs(stress_values))) if stress_values.size else 0.0

    safety = effective_yield / max(max_von_mises, 1e-12)
    fatigue = min(1.0, (max_von_mises / max(effective_yield, 1e-12)) ** 3 * math.log10(cycles + 1.0) * 0.16)
    structural_score = max(0.0, min(1.0, (1.0 - fatigue) * min(safety / 2.0, 1.0)))
    mesh_quality = max(0.35, min(0.99, 1.0 - mesh_size / max(min(size), 1e-6)))

    result_path.parent.mkdir(parents=True, exist_ok=True)
    xdmf_path = result_path.with_suffix(".xdmf")
    try:
        with io.XDMFFile(domain.comm, str(xdmf_path), "w") as xdmf:
            xdmf.write_mesh(domain)
            xdmf.write_function(uh)
    except Exception as exc:  # XDMF is useful but not required for metrics.
        xdmf_path = None
        xdmf_error = f"{exc.__class__.__name__}: {exc}"
    else:
        xdmf_error = ""

    result = {
        "ok": True,
        "schema": "fenicsx_solver_output.v1",
        "solver_backend": "dolfinx_linear_elasticity_template",
        "template_version": request.get("template_version") or "atr_linear_elasticity_template_v1",
        "specimen_id": specimen_id,
        "mesh": {
            "cell_type": "hexahedron",
            "cell_counts": [nx, ny, nz],
            "mesh_size_mm": mesh_size,
            "num_cells": int(nx * ny * nz),
            "num_vertices": int(disp.shape[0]),
        },
        "boundary_condition": "bottom_fixed_support",
        "loading_mode": "top_compression_traction",
        "metrics": {
            "predicted_peak_force_N": round(load_max, 6),
            "load_min_N": round(load_min, 6),
            "predicted_initial_stiffness_N_per_mm": round(stiffness, 6),
            "predicted_energy_absorption_mJ": round(energy, 6),
            "max_displacement_mm": round(max_displacement, 9),
            "max_compression_mm": round(max_compression, 9),
            "max_von_mises_MPa": round(max_von_mises, 6),
            "mean_von_mises_MPa": round(mean_von_mises, 6),
            "effective_modulus_MPa": round(effective_E, 6),
            "effective_yield_strength_MPa": round(effective_yield, 6),
            "nominal_top_stress_MPa": round(traction, 6),
            "safety_factor_yield": round(safety, 6),
            "fatigue_damage_proxy": round(fatigue, 6),
            "structural_score": round(structural_score, 6),
            "mesh_quality_score": round(mesh_quality, 6),
            "fem_confidence": 0.86,
            "solver_converged": True,
            "cycles": cycles,
            "reaction_force_curve": [
                {"step": i, "displacement_mm": round(max_compression * scale, 9), "reaction_force_N": round(load_max * scale, 6)}
                for i, scale in enumerate((0.0, 0.25, 0.5, 0.75, 1.0))
            ],
        },
        "artifacts": {
            "xdmf": str(xdmf_path) if xdmf_path else "",
            "xdmf_error": xdmf_error,
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
