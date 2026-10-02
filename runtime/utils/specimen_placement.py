"""Bambu X2D specimen-center settings and non-actuating placement validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
import zipfile

from pydantic import BaseModel, ConfigDict, Field


class SpecimenPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["auto", "bed_center", "custom"] = "auto"
    center_x_mm: float = Field(default=128.0, ge=0, le=256)
    center_y_mm: float = Field(default=128.0, ge=0, le=256)


def normalize_placement(value: Any = None) -> dict[str, Any]:
    return SpecimenPlacement.model_validate({} if value is None else value).model_dump()


def placement_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for source in (payload, payload.get("print"), payload.get("experiment_spec")):
        if isinstance(source, dict) and source.get("specimen_placement") is not None:
            return normalize_placement(source["specimen_placement"])
    return normalize_placement()


def _rectangle(points) -> list[float]:
    if isinstance(points, str):
        points = points.split(",")
    pairs = [tuple(float(v) for v in point.split("x")) for point in points]
    xs, ys = {p[0] for p in pairs}, {p[1] for p in pairs}
    if len(xs) != 2 or len(ys) != 2 or set(pairs) != {(x, y) for x in xs for y in ys}:
        raise ValueError("Explicit placement requires a rectangular printer area")
    return [min(xs), min(ys), max(xs), max(ys)]


def placement_area(load_settings=None) -> dict[str, Any]:
    """Use the same rectangular shared nozzle region used by X2D arrangement."""
    bed = [0.0, 0.0, 256.0, 256.0]
    areas = [[0.0, 0.0, 256.0, 256.0], [20.5, 0.0, 256.0, 256.0]]
    if load_settings:
        for name in str(load_settings).split(";"):
            config = json.loads(Path(name).read_text(encoding="utf-8"))
            if config.get("printable_area"):
                bed = _rectangle(config["printable_area"])
            if config.get("extruder_printable_area"):
                areas = [_rectangle(value) for value in config["extruder_printable_area"]]
    all_areas = [bed, *areas]
    shared = [max(a[0] for a in all_areas), max(a[1] for a in all_areas),
              min(a[2] for a in all_areas), min(a[3] for a in all_areas)]
    return {"bed_bounds_xy_mm": bed, "allowed_bounds_xy_mm": shared}


def requested_center(placement: dict, area: dict) -> list[float] | None:
    if placement["mode"] == "auto":
        return None
    if placement["mode"] == "bed_center":
        x0, y0, x1, y1 = area["bed_bounds_xy_mm"]
        return [(x0 + x1) / 2, (y0 + y1) / 2]
    return [placement["center_x_mm"], placement["center_y_mm"]]


def _contains(bounds, area) -> bool:
    allowed = area["allowed_bounds_xy_mm"]
    return bool(bounds[0] >= allowed[0] and bounds[1] >= allowed[1]
                and bounds[2] <= allowed[2] and bounds[3] <= allowed[3])


def preflight_placement(source: Path, placement: dict, area: dict) -> dict:
    center = requested_center(placement, area)
    if center is None:
        return {"ok": True, "mode": "auto"}
    if source.suffix.lower() != ".stl":
        return {"ok": False, "failure_code": "SPECIMEN_PLACEMENT_REQUIRES_STL",
                "message": "Re-slice the original STL to change placement without losing 3MF settings."}
    import numpy as np
    import trimesh
    mesh = trimesh.load(str(source), force="scene", process=False)
    bounds = mesh.bounds
    if bounds is None or not np.isfinite(bounds).all():
        raise ValueError("Missing or nonfinite specimen geometry")
    # Keep NumPy scalars out of the nested experiment/API result.
    extent = (bounds[1] - bounds[0]).tolist()
    proposed = [center[0] - extent[0] / 2, center[1] - extent[1] / 2,
                center[0] + extent[0] / 2, center[1] + extent[1] / 2]
    ok = _contains(proposed, area)
    return {"ok": ok, "mode": placement["mode"], "requested_center_mm": center,
            "translation_mm": [center[0] - float((bounds[0, 0] + bounds[1, 0]) / 2),
                               center[1] - float((bounds[0, 1] + bounds[1, 1]) / 2), -float(bounds[0, 2])],
            "requested_bounds_xy_mm": proposed, **area,
            "failure_code": "" if ok else "SPECIMEN_PLACEMENT_OUT_OF_BOUNDS"}


def validate_sliced_placement(path: Path, value=None, *, area=None) -> dict:
    placement = normalize_placement(value)
    if placement["mode"] == "auto":
        return {"ok": True, "mode": "auto", "status": "slicer_managed"}
    from device_bridges.bambu_autoejection import extract_object_bounds_mm
    area = area or placement_area()
    center = requested_center(placement, area)
    try:
        with zipfile.ZipFile(path) as archive:
            plates = [name for name in archive.namelist() if name.startswith("Metadata/plate_") and name.endswith(".gcode")]
            if len(plates) != 1:
                raise ValueError("Explicit placement requires one sliced plate")
            bounds = extract_object_bounds_mm(archive.read(plates[0]).decode("utf-8"))
        actual = [float(bounds["center_x_mm"]), float(bounds["center_y_mm"])]
        xy = [float(bounds[k]) for k in ("min_x", "min_y", "max_x", "max_y")]
        matched = all(abs(a - b) <= 0.5 for a, b in zip(actual, center))
        inside = _contains(xy, area)
        return {"ok": matched and inside, "mode": placement["mode"],
                "requested_center_mm": center, "actual_center_mm": actual,
                "object_bounds_mm": bounds, **area,
                "failure_code": "" if matched and inside else "SPECIMEN_PLACEMENT_MISMATCH" if not matched else "SPECIMEN_PLACEMENT_OUT_OF_BOUNDS"}
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile):
        return {"ok": False, "mode": placement["mode"], "failure_code": "SPECIMEN_PLACEMENT_EVIDENCE_MISSING"}
