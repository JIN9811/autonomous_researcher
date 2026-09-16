"""Deterministic, fail-closed thickness inspection of the generated STL.

Normal-ray chords measure the actual mesh, not the nominal wall parameter.
This is a sampled engineering check, not a certified global minimum proof.
"""
from pathlib import Path
import hashlib
import math


def _bounded_normal_chords(mesh, indices, limit):
    """First hits on short inward segments; no hit gives a lower bound of limit."""
    import numpy as np
    tree = mesh.triangles_tree
    triangles = mesh.triangles
    results = []
    for index in indices:
        origin = mesh.triangles_center[index]
        direction = -mesh.face_normals[index]
        end = origin + direction * limit
        bounds = np.concatenate([np.minimum(origin, end)-1e-7, np.maximum(origin, end)+1e-7])
        candidates = np.asarray([i for i in tree.intersection(bounds) if i != index], dtype=int)
        if not len(candidates):
            results.append(limit)
            continue
        tri = triangles[candidates]
        e1, e2 = tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]
        p = np.cross(direction, e2)
        det = np.einsum("ij,ij->i", e1, p)
        valid = np.abs(det) > 1e-12
        inv = np.divide(1.0, det, out=np.zeros_like(det), where=valid)
        tvec = origin-tri[:, 0]
        u = np.einsum("ij,ij->i", tvec, p)*inv
        q = np.cross(tvec, e1)
        v = (q @ direction)*inv
        distance = np.einsum("ij,ij->i", e2, q)*inv
        hits = distance[valid & (u >= -1e-8) & (v >= -1e-8) & (u+v <= 1+1e-8)
                        & (distance > 1e-7) & (distance <= limit)]
        results.append(float(hits.min()) if len(hits) else limit)
    return np.asarray(results)


def inspect_wall_thickness(stl_path, minimum_mm=0.4, *, max_samples=4096):
    minimum_mm = float(minimum_mm)
    if not math.isfinite(minimum_mm) or minimum_mm <= 0:
        raise ValueError("minimum wall thickness must be positive and finite")
    report = {"schema": "mesh_wall_thickness.v1", "status": "unverified",
              "required_minimum_mm": minimum_mm, "method": "interior_normal_ray_chords",
              "limitation": "Deterministic surface sampling; not a certified global minimum. Crop faces excluded. No hit within search limit is a lower bound.",
              "search_limit_mm": max(4*minimum_mm, 1.6)}
    try:
        import numpy as np
        import trimesh
        path = Path(stl_path)
        report["stl_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        mesh = trimesh.load_mesh(path, process=True)
        if not mesh.is_watertight or not mesh.is_winding_consistent:
            return {**report, "reason": "closed_consistently_oriented_mesh_required"}
        centers = mesh.triangles_center
        # An inward ray near the crop rim may hit the crop end, rather than
        # the opposite sheet surface. Measure the interior wall, not rim length.
        report["excluded_crop_band_mm"] = minimum_mm
        on_crop = np.any((centers-mesh.bounds[0] <= minimum_mm)
                         | (mesh.bounds[1]-centers <= minimum_mm), axis=1)
        indices = np.flatnonzero(~on_crop)
        if len(indices) == 0:
            return {**report, "reason": "no_interior_sheet_faces"}
        if len(indices) > max_samples:
            rng = np.random.default_rng(0)
            area = mesh.area_faces[indices]
            indices = np.sort(rng.choice(indices, size=max_samples, replace=False, p=area / area.sum()))
        # Bound peak memory in trimesh's broad-phase ray candidate arrays.
        chunks = []
        for start in range(0, len(indices), 128):
            batch = indices[start:start + 128]
            chunks.append(_bounded_normal_chords(mesh, batch, report["search_limit_mm"]))
            current = chunks[-1]
            if np.any(np.isfinite(current) & (current > 0) & (current < minimum_mm)):
                measured_values = np.concatenate(chunks)
                valid = measured_values[np.isfinite(measured_values) & (measured_values > 0)]
                return {**report, "status": "fail", "minimum_sampled_mm": float(valid.min()),
                        "sample_count": len(measured_values), "early_rejection": True,
                        "fraction_below_minimum": float(np.mean(valid < minimum_mm))}
        values = np.concatenate(chunks)
        if not np.all(np.isfinite(values) & (values > 0)):
            return {**report, "reason": "incomplete_ray_measurements", "sample_count": len(values)}
        measured = float(values.min())
        return {**report, "status": "pass" if measured >= minimum_mm else "fail",
                "minimum_sampled_mm": measured, "sample_count": len(values),
                "fraction_below_minimum": float(np.mean(values < minimum_mm))}
    except (ImportError, OSError, ValueError, TypeError) as exc:
        return {**report, "reason": f"measurement_unavailable:{type(exc).__name__}"}
