"""Publication-style artifacts for mixed-space Latin hypercube designs."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from experiments.lhs_design_visualization import validate_lhs_design_visualization


def _safe(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "run")).strip("-") or "run"


def _record(path: Path, media_type: str) -> dict[str, Any]:
    return {"path": str(path), "name": path.name, "media_type": media_type, "source": "lhs_design_visualization.v1"}


def _style_axis(axis: Any) -> None:
    axis.set_facecolor("white")
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.spines["left"].set_color("#111827")
    axis.spines["bottom"].set_color("#111827")
    axis.tick_params(colors="#334155", labelsize=8)
    axis.grid(color="#d8dee8", linestyle="--", linewidth=0.6, alpha=0.9)
    axis.set_axisbelow(True)


def _plot(payload: dict[str, Any]) -> Any:
    design = payload["initial_design"]
    points = design["points"]
    x_axis = payload["design_space"]["x"]
    y_axis = payload["design_space"]["y"]
    cells = x_axis.get("values", x_axis.get("bounds", []))
    lower, upper = y_axis["bounds"]
    target = int(design["target"])
    figure, axis = plt.subplots(figsize=(7.2, 4.5), constrained_layout=True)
    figure.patch.set_facecolor("white")
    _style_axis(axis)

    for index in range(target + 1):
        boundary = lower + (upper - lower) * index / target
        axis.axhline(boundary, color="#cbd5e1", linewidth=0.55, alpha=0.72, zorder=0)
    axis.text(1.0, 0.01, "Density strata", transform=axis.transAxes, ha="right", va="bottom", fontsize=7, color="#64748b")

    groups = {
        "measured": ("Measured design", "#2563eb", "o", 42),
        "next": ("Next design", "#f97316", "x", 68),
        "planned": ("Planned design", "#94a3b8", "o", 30),
    }
    for status, (label, color, marker, size) in groups.items():
        selected = [item for item in points if item["status"] == status]
        if not selected:
            continue
        axis.scatter(
            [item["parameters"]["cell_size_mm"] for item in selected],
            [item["parameters"]["relative_density"] for item in selected],
            color=color,
            marker=marker,
            s=size,
            edgecolor="white" if marker == "o" else None,
            linewidth=0.8 if marker == "o" else 1.8,
            zorder=4,
            label=label,
        )

    if x_axis.get("kind") == "discrete":
        axis.set_xticks(cells)
    x_span = max(cells) - min(cells)
    axis.set_xlim(min(cells) - max(x_span * 0.06, 0.2), max(cells) + max(x_span * 0.06, 0.2))
    axis.set_ylim(lower, upper)
    axis.set_xlabel("Cell size (mm)", fontsize=9)
    axis.set_ylabel("Relative density", fontsize=9)
    axis.set_title("Mixed-space Latin hypercube initial design", fontsize=11, fontweight="bold", loc="left")
    axis.text(
        1.0,
        1.02,
        f"{design['completed']} / {target} measured",
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=8.5,
        color="#475569",
    )
    axis.legend(loc="best", frameon=False, fontsize=8, ncols=3)
    return figure


def write_lhs_design_visualization_artifacts(payload: dict[str, Any], output_dir: str | Path) -> list[dict[str, Any]]:
    normalized = validate_lhs_design_visualization(payload)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    stem = f"{_safe(normalized.get('run_id'))}_lhs_design_step_{int(normalized.get('step') or 0):03d}"
    paths = {
        ".png": destination / f"{stem}.png",
        ".svg": destination / f"{stem}.svg",
        ".csv": destination / f"{stem}.csv",
        ".json": destination / f"{stem}.json",
    }
    figure = _plot(normalized)
    figure.savefig(paths[".png"], dpi=180, facecolor="white", transparent=False)
    figure.savefig(paths[".svg"], facecolor="white", transparent=False)
    plt.close(figure)

    with paths[".csv"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["index", "status", "candidate_id", "cell_size_mm", "relative_density", "density_stratum"])
        for item in normalized["initial_design"]["points"]:
            writer.writerow(
                [
                    item["index"], item["status"], item["candidate_id"],
                    item["parameters"]["cell_size_mm"], item["parameters"]["relative_density"], item["density_stratum"],
                ]
            )
    paths[".json"].write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    return [
        _record(paths[".png"], "image/png"),
        _record(paths[".svg"], "image/svg+xml"),
        _record(paths[".csv"], "text/csv"),
        _record(paths[".json"], "application/json"),
    ]
