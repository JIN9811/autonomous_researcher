"""Offline mesh thickness audit; never invokes a device or changes run evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp_tools.tpms_geometry import write_smooth_gyroid_stl


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    reports = []
    for resolution in (72, 144):
        path = args.output / f"gyroid-r{resolution}.stl"
        report = write_smooth_gyroid_stl(
            stl_path=path, name="thickness-audit", specimen_size_mm=[30, 30, 30],
            wall_thickness_mm=1.2, cell_size_mm=5.859315333372083,
            relative_density=0.20359751696606487, tpms_thickness=0.317,
            resolution=resolution, skin_thickness_mm=0, top_bottom_cap=False,
        )
        if report is None:
            raise RuntimeError("Geometry dependencies unavailable")
        mesh = trimesh.load_mesh(path, process=True)
        # Exclude specimen clipping faces, which are not the interior sheet.
        eligible = np.all(np.abs(mesh.triangles_center) < 12.0, axis=1)
        indices = np.flatnonzero(eligible)
        rng = np.random.default_rng(20260916)
        areas = mesh.area_faces[indices]
        selected = rng.choice(indices, size=1000, p=areas / areas.sum())
        points = mesh.triangles_center[selected]
        normals = mesh.face_normals[selected]
        values = trimesh.proximity.thickness(mesh, points, normals=normals, method="ray")
        valid = values[np.isfinite(values) & (values > 0)]
        result = {
            "resolution": resolution, "voxel_spacing_mm": 30 / (resolution - 1),
            "mesh_path": str(path), "watertight": bool(mesh.is_watertight),
            "winding_consistent": bool(mesh.is_winding_consistent),
            "method": "1000 area-weighted interior face centers; inward normal first-hit rays",
            "excluded_boundary_band_mm": 3, "valid_samples": len(valid),
            "quantiles_mm": dict(zip(["min_sample", "p05", "median", "p95", "max_sample"],
                                     np.quantile(valid, [0, .05, .5, .95, 1]).tolist())),
            "sample_fraction_below_1p2_mm": float(np.mean(valid < 1.2)),
            "sample_fraction_below_0p4_mm": float(np.mean(valid < .4)),
            "generator_report": report,
            "limitation": "Sampled normal-ray chord lengths, not certified global minimum thickness; finite mesh resolution and face normals affect estimates.",
        }
        reports.append(result)
        (args.output / "report.json").write_text(json.dumps(reports, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k != "generator_report"}), flush=True)


if __name__ == "__main__":
    main()
