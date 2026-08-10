"""Write publication-style artifacts from the shared BO projection contract."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

from matplotlib import pyplot as plt

from experiments.bo_visualization import validate_bo_visualization


def _artifact_stem(payload: dict[str, Any]) -> str:
    run_id = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in str(payload.get("run_id") or "run"))
    return f"{run_id}_bo_step_{int(payload.get('step') or 0):03d}_posterior"


def _record(path: Path, media_type: str) -> dict[str, Any]:
    return {
        "name": path.name,
        "path": str(path),
        "media_type": media_type,
        "source": "bo_visualization.v1",
    }


def write_bo_visualization_artifacts(payload: dict[str, Any], output_dir: str | Path) -> list[dict[str, Any]]:
    """Persist one validated BO projection as PNG, SVG, and numeric CSV."""
    normalized = validate_bo_visualization(payload)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    stem = _artifact_stem(normalized)
    png_path = destination / f"{stem}.png"
    svg_path = destination / f"{stem}.svg"
    csv_path = destination / f"{stem}.csv"

    posterior = normalized["posterior"]
    acquisition = normalized["acquisition"]
    x = posterior["x"]
    mean = posterior["mean"]
    lower = posterior["lower_95"]
    upper = posterior["upper_95"]

    figure, (posterior_axis, acquisition_axis) = plt.subplots(
        2,
        1,
        figsize=(7.2, 5.2),
        sharex=True,
        gridspec_kw={"height_ratios": [2.2, 1.0]},
        constrained_layout=True,
    )
    figure.patch.set_facecolor("white")
    for axis in (posterior_axis, acquisition_axis):
        axis.set_facecolor("white")
        axis.grid(True, color="#d9e0e8", linewidth=0.65, linestyle="--", alpha=0.85)
        axis.spines[["top", "right"]].set_visible(False)
        axis.tick_params(labelsize=8, colors="#334155")

    posterior_axis.fill_between(x, lower, upper, color="#60a5fa", alpha=0.23, label="95% confidence interval")
    posterior_axis.plot(x, mean, color="#2563eb", linewidth=1.8, label="Posterior mean")
    observations = [item for item in normalized.get("observations", []) if isinstance(item, dict)]
    if observations:
        posterior_axis.scatter(
            [item["x"] for item in observations],
            [item["score"] for item in observations],
            color="#111827",
            edgecolor="white",
            linewidth=0.7,
            s=31,
            zorder=4,
            label="Measured observations",
        )
    next_point = normalized.get("next_point") if isinstance(normalized.get("next_point"), dict) else {}
    if isinstance(next_point.get("x"), (int, float)) and isinstance(next_point.get("mean"), (int, float)):
        posterior_axis.scatter(
            [next_point["x"]],
            [next_point["mean"]],
            color="#dc2626",
            edgecolor="white",
            linewidth=0.9,
            s=48,
            zorder=5,
            label="Next point",
        )
    objective = normalized.get("objective") if isinstance(normalized.get("objective"), dict) else {}
    objective_unit = str(objective.get("unit") or "")
    posterior_axis.set_ylabel(f"Objective ({objective_unit})" if objective_unit else "Objective", fontsize=9)
    posterior_axis.set_title(
        f"Bayesian optimization posterior, step {int(normalized.get('step') or 0)}",
        fontsize=11,
        fontweight="bold",
        loc="left",
    )
    posterior_axis.legend(loc="best", fontsize=7.5, frameon=False, ncols=2)

    acquisition_axis.plot(acquisition["x"], acquisition["value"], color="#f59e0b", linewidth=1.8)
    if isinstance(next_point.get("x"), (int, float)) and isinstance(next_point.get("acquisition"), (int, float)):
        acquisition_axis.scatter([next_point["x"]], [next_point["acquisition"]], color="#dc2626", s=40, zorder=4)
    acquisition_axis.set_ylabel("Acquisition", fontsize=9)
    acquisition_axis.set_xlabel(str(normalized.get("view", {}).get("x_label") or "Parameter"), fontsize=9)

    figure.savefig(png_path, dpi=150, facecolor="white")
    figure.savefig(svg_path, facecolor="white")
    plt.close(figure)

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "mean", "std", "lower_95", "upper_95", "acquisition"])
        writer.writerows(
            zip(
                posterior["x"],
                posterior["mean"],
                posterior["std"],
                posterior["lower_95"],
                posterior["upper_95"],
                acquisition["value"],
                strict=True,
            )
        )

    return [
        _record(png_path, "image/png"),
        _record(svg_path, "image/svg+xml"),
        _record(csv_path, "text/csv"),
    ]
