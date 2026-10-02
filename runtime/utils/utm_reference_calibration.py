"""Select fingerprinted historical UTM curves for CAE scale calibration."""

from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any

from utils.utm_csv import parse_utm_csv


METRIC_NAME = "energy_density_50pct_MJ_per_m3"


def _energy_through_displacement(
    rows: list[dict[str, float]],
    target_displacement_mm: float,
) -> float | None:
    if len(rows) < 2:
        return None
    origin_displacement = float(rows[0]["displacement_mm"])
    origin_force = float(rows[0]["force_N"])
    points = sorted(
        (
            abs(float(row["displacement_mm"]) - origin_displacement),
            max(0.0, float(row["force_N"]) - origin_force),
        )
        for row in rows
        if math.isfinite(float(row["displacement_mm"])) and math.isfinite(float(row["force_N"]))
    )
    if not points or points[-1][0] + 1e-9 < target_displacement_mm:
        return None
    clipped: list[tuple[float, float]] = []
    for point in points:
        if point[0] < target_displacement_mm:
            clipped.append(point)
            continue
        if point[0] == target_displacement_mm:
            clipped.append(point)
        elif clipped:
            left_x, left_y = clipped[-1]
            ratio = (target_displacement_mm - left_x) / max(point[0] - left_x, 1e-12)
            clipped.append((target_displacement_mm, left_y + ratio * (point[1] - left_y)))
        break
    if len(clipped) < 2 or clipped[-1][0] + 1e-9 < target_displacement_mm:
        return None
    return sum(
        0.5 * (left[1] + right[1]) * (right[0] - left[0])
        for left, right in zip(clipped, clipped[1:])
    )


def build_reference_calibration(
    paths: list[Path],
    *,
    target_strain: float,
    specimen_size_mm: list[float],
) -> dict[str, Any]:
    """Return a deduplicated, quality-gated energy-density reference summary."""
    size = [float(value) for value in specimen_size_mm]
    if len(size) != 3 or any(not math.isfinite(value) or value <= 0.0 for value in size):
        raise ValueError("specimen_size_mm must contain three positive finite values")
    strain = float(target_strain)
    if not math.isfinite(strain) or strain <= 0.0 or strain > 0.8:
        raise ValueError("target_strain must be within (0, 0.8]")
    target_displacement = size[2] * strain
    initial_volume = size[0] * size[1] * size[2]
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        rows, probe = parse_utm_csv(path)
        digest = str(probe.get("sha256") or "")
        if digest and digest in seen_hashes:
            rejected.append({"path": str(path), "sha256": digest, "reason": "duplicate_content"})
            continue
        if digest:
            seen_hashes.add(digest)
        if not probe.get("ok"):
            rejected.append(
                {
                    "path": str(path),
                    "sha256": digest,
                    "reason": str(probe.get("failure_code") or "utm_parse_failed"),
                }
            )
            continue
        energy_mj = _energy_through_displacement(rows, target_displacement)
        if energy_mj is None:
            rejected.append(
                {
                    "path": str(path),
                    "sha256": digest,
                    "reason": "target_strain_not_reached",
                    "target_displacement_mm": target_displacement,
                    "measured_displacement_range_mm": probe.get("data_quality", {}).get("displacement_range_mm"),
                }
            )
            continue
        energy_density = energy_mj / initial_volume
        accepted.append(
            {
                "path": str(path),
                "sha256": digest,
                "source_format": probe.get("source_format"),
                "encoding": probe.get("encoding"),
                "row_count": probe.get("row_count_probe"),
                "target_displacement_mm": target_displacement,
                "energy_absorption_50pct_mJ": energy_mj,
                METRIC_NAME: energy_density,
                "quality": probe.get("data_quality", {}),
            }
        )

    values = [float(item[METRIC_NAME]) for item in accepted]
    reference_value = statistics.median(values) if values else None
    return {
        "schema": "utm_reference_calibration.v1",
        "status": "ready" if values else "blocked",
        "metric_name": METRIC_NAME,
        "unit": "MJ/m3",
        "target_strain": strain,
        "reference_specimen_size_mm": size,
        "reference_initial_volume_mm3": initial_volume,
        "reference_value": reference_value,
        "calibration_method": "median_integrated_force_displacement_energy_density",
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "reference_hashes": [item["sha256"] for item in accepted],
        "accepted": accepted,
        "rejected": rejected,
        "limitations": ["historical_unmatched_specimen_reference", "calibration_not_physical_validation"],
    }
