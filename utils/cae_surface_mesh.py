"""Explicit geometry-checked surface conditioning, run as an owned native subprocess.

The checks reproduce the saved isotropic-remesh study; sampled vertex-to-surface
distance is not a continuous Hausdorff-distance certificate.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Any


def normalize_profile(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict) or profile.get("method") != "isotropic":
        raise ValueError("CAE_SURFACE_REMESH_PROFILE_INVALID")
    try:
        edge = float(profile.get("edge_length_mm", 0.6))
        iterations = int(profile.get("iterations", 8))
        distance = float(profile.get("max_surface_distance_mm", 0.05))
        if not (math.isfinite(edge) and 0.05 <= edge <= 5 and 1 <= iterations <= 20
                and math.isfinite(distance) and 0 < distance <= 0.05):
            raise ValueError("limits")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("CAE_SURFACE_REMESH_PROFILE_INVALID") from exc
    return {"method": "isotropic", "edge_length_mm": edge, "iterations": iterations,
            "max_surface_distance_mm": distance}


def condition_surface(source: Path, output_dir: Path, profile: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    import pymeshlab
    import pyvista as pv
    import trimesh

    profile = normalize_profile(profile)
    started = time.monotonic()
    original = trimesh.load_mesh(source, process=True)
    if not isinstance(original, trimesh.Trimesh) or not original.is_watertight or original.volume <= 0:
        raise ValueError("CAE_SURFACE_SOURCE_INVALID")
    meshset = pymeshlab.MeshSet()
    meshset.add_mesh(pymeshlab.Mesh(vertex_matrix=original.vertices, face_matrix=original.faces))
    meshset.meshing_isotropic_explicit_remeshing(
        iterations=profile["iterations"], targetlen=pymeshlab.PureValue(profile["edge_length_mm"]),
        featuredeg=45, checksurfdist=True,
        maxsurfdist=pymeshlab.PureValue(profile["max_surface_distance_mm"]), reprojectflag=True,
    )
    current = meshset.current_mesh()
    remeshed = trimesh.Trimesh(current.vertex_matrix(), current.face_matrix(), process=True)

    def poly(mesh):
        return pv.PolyData(mesh.vertices, np.column_stack([np.full(len(mesh.faces), 3), mesh.faces]).ravel())

    left, right = poly(original), poly(remeshed)
    distance = float(max(np.abs(left.compute_implicit_distance(right)["implicit_distance"]).max(),
                         np.abs(right.compute_implicit_distance(left)["implicit_distance"]).max()))
    surface_path = output_dir / "conditioned_surface.stl"
    report_path = output_dir / "surface_geometry_check.json"
    remeshed.export(surface_path)
    with source.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    check = {
        "schema": "cae_surface_conditioning.v1", "source": str(source), "source_sha256": source_hash,
        "profile": profile, "method": "MeshLab isotropic remeshing with reprojection",
        "original_faces": len(original.faces), "remeshed_faces": len(remeshed.faces),
        "watertight": bool(remeshed.is_watertight), "euler_original": int(original.euler_number),
        "euler_remeshed": int(remeshed.euler_number), "original_volume_mm3": float(original.volume),
        "remeshed_volume_mm3": float(remeshed.volume),
        "volume_error_pct": float(100 * (remeshed.volume / original.volume - 1)),
        "bidirectional_vertex_surface_max_mm": distance,
        "distance_definition": "sampled bidirectional vertex-to-surface maximum; not continuous Hausdorff",
        "acceptance_limits": {"absolute_volume_error_pct_lt": 1.0, "sampled_distance_mm_lt": 0.1,
                              "watertight_required": True, "euler_preserved_required": True},
        "bounds_mm": remeshed.bounds.tolist(), "elapsed_s": time.monotonic() - started,
        "surface_path": str(surface_path), "geometry_check_path": str(report_path),
    }
    check["accepted"] = bool(check["watertight"] and check["euler_original"] == check["euler_remeshed"]
                             and abs(check["volume_error_pct"]) < 1 and distance < 0.1)
    report_path.write_text(json.dumps(check, indent=2, allow_nan=False), encoding="utf-8")
    return check


def main() -> int:
    request = json.loads(Path(sys.argv[1]).read_text())
    try:
        result = condition_surface(Path(request["source"]), Path(request["output_dir"]), request["profile"])
    except Exception as exc:
        print(json.dumps({"error": str(exc), "error_type": type(exc).__name__}), flush=True)
        return 1
    print(json.dumps(result), flush=True)
    return 0 if result["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
