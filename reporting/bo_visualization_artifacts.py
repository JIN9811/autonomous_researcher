"""Write publication-style artifacts from the shared BO projection contract."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["svg.fonttype"] = "none"

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


def _style_axis(axis: Any) -> None:
    axis.set_facecolor("white")
    axis.grid(True, color="#d9e0e8", linewidth=0.65, linestyle="--", alpha=0.85)
    axis.spines[["top", "right"]].set_visible(False)
    axis.tick_params(labelsize=8, colors="#334155")


def _plot_posterior(normalized: dict[str, Any]) -> Any:
    objective_trace = normalized.get("objective_trace") if isinstance(normalized.get("objective_trace"), dict) else {}
    if objective_trace.get("mode") == "normalized_search_path":
        return _plot_objective_trace(normalized, objective_trace)
    surface = normalized.get("gp_surface") if isinstance(normalized.get("gp_surface"), dict) else {}
    if surface.get("mode") == "mixed_2d_gp_surface":
        return _plot_objective_surface(normalized, surface)
    posterior = normalized["posterior"]
    x = posterior["x"]
    mean = posterior["mean"]
    lower = posterior["lower_95"]
    upper = posterior["upper_95"]

    figure, posterior_axis = plt.subplots(figsize=(8.4, 4.8), constrained_layout=True)
    figure.patch.set_facecolor("white")
    _style_axis(posterior_axis)

    posterior_axis.fill_between(x, lower, upper, color="#94a3b8", alpha=0.32, label="95% confidence interval")
    posterior_axis.plot(x, mean, color="#111827", linewidth=1.8, label="Posterior mean")
    observations = [item for item in normalized.get("observations", []) if isinstance(item, dict)]
    if observations:
        posterior_axis.scatter(
            [item["x"] for item in observations],
            [item["score"] for item in observations],
            color="#2563eb",
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
            color="#f97316",
            marker="x",
            linewidth=1.8,
            s=52,
            zorder=5,
            label="EI-selected Next point",
        )
        posterior_axis.axvline(next_point["x"], color="#f97316", linewidth=0.9, linestyle="--", alpha=0.75)
    objective = normalized.get("objective") if isinstance(normalized.get("objective"), dict) else {}
    objective_unit = str(objective.get("unit") or "")
    posterior_axis.set_ylabel(f"Objective ({objective_unit})" if objective_unit else "Objective", fontsize=9)
    posterior_axis.set_xlabel(str(normalized.get("view", {}).get("x_label") or "Parameter"), fontsize=9)
    posterior_axis.set_title(
        f"Bayesian optimization posterior, step {int(normalized.get('step') or 0)}",
        fontsize=11,
        fontweight="bold",
        loc="left",
    )
    posterior_axis.legend(loc="best", fontsize=7.5, frameon=False, ncols=2)

    return figure


def _plot_objective_trace(normalized: dict[str, Any], trace: dict[str, Any]) -> Any:
    rows = [row for row in trace.get("rows", []) if isinstance(row, dict)]
    figure, (posterior_axis, acquisition_axis) = plt.subplots(
        2, 1, figsize=(8.4, 5.8), sharex=True,
        gridspec_kw={"height_ratios": [3.0, 1.15], "hspace": 0.12},
    )
    figure.patch.set_facecolor("white")
    _style_axis(posterior_axis)
    _style_axis(acquisition_axis)
    colors = {3: "#dbeafe", 2: "#93c5fd", 1: "#3b82f6"}
    alphas = {3: 0.55, 2: 0.50, 1: 0.42}
    rows.sort(key=lambda item: float(item["search_x"]))
    x = [row["search_x"] for row in rows]
    mean = [row["mean"] for row in rows]
    std = [row["std"] for row in rows]
    acquisition = [max(0.0, row.get("acquisition") or 0.0) for row in rows]
    for sigma in (3, 2, 1):
        posterior_axis.fill_between(
            x,
            [value - sigma * deviation for value, deviation in zip(mean, std, strict=True)],
            [value + sigma * deviation for value, deviation in zip(mean, std, strict=True)],
            color=colors[sigma], alpha=alphas[sigma], label=f"±{sigma}σ",
        )
    posterior_axis.plot(x, mean, color="#111827", linewidth=1.9)
    acquisition_axis.plot(x, acquisition, color="#15803d", linewidth=1.9)
    posterior_axis.plot([], [], color="#111827", linewidth=1.9, label="GP posterior mean")
    evaluated = [row for row in trace.get("observations", []) if isinstance(row, dict) and isinstance(row.get("observed"), (int, float))]
    if evaluated:
        posterior_axis.scatter(
            [row["search_x"] for row in evaluated], [row["observed"] for row in evaluated],
            color="#dc2626", edgecolor="white", linewidth=0.7, s=31, zorder=5, label="Measured observations",
        )
    threshold = trace.get("improvement_threshold")
    if isinstance(threshold, (int, float)):
        posterior_axis.axhline(
            threshold,
            color="#f59e0b",
            linewidth=1.25,
            linestyle="--",
            label="Improvement threshold (best + ξ)",
        )
    acquisition_axis.plot([], [], color="#15803d", linewidth=1.9, label="Expected Improvement")
    next_row = trace.get("next_point") if isinstance(trace.get("next_point"), dict) else None
    if next_row:
        for axis in (posterior_axis, acquisition_axis):
            axis.axvline(next_row["search_x"], color="#2563eb", linewidth=1.2, linestyle="-.")
        acquisition_axis.scatter(
            [next_row["search_x"]], [max(0.0, next_row.get("acquisition") or 0.0)],
            color="#1d4ed8", marker="*", s=80, zorder=6, label="EI-selected next input",
        )
    posterior_axis.set_xlim(0.0, 1.0)
    posterior_axis.set_ylabel("Score", fontsize=9)
    acquisition_axis.set_ylabel("Expected Improvement", fontsize=9)
    acquisition_axis.set_xlabel("Normalized BO search coordinate", fontsize=9)
    posterior_axis.set_title(
        f"BO objective posterior and expected improvement, step {int(normalized.get('step') or 0)}",
        fontsize=11, fontweight="bold", loc="left", pad=54,
    )
    posterior_axis.legend(
        loc="lower left",
        bbox_to_anchor=(0.0, 1.015),
        fontsize=7.2,
        frameon=False,
        ncols=3,
        borderaxespad=0.0,
        columnspacing=1.2,
        handletextpad=0.5,
    )
    acquisition_axis.legend(loc="best", fontsize=7.2, frameon=False)
    figure.subplots_adjust(top=0.81)
    return figure


def _plot_objective_surface(normalized: dict[str, Any], surface: dict[str, Any]) -> Any:
    """Plot the GP's scalar output f(x1, x2), not either input as an output."""
    x1 = surface["x_values"]
    x2 = surface["y_values"]
    mean = surface["mean"]
    figure, axis = plt.subplots(figsize=(8.4, 5.2), constrained_layout=True)
    figure.patch.set_facecolor("white")
    _style_axis(axis)
    mesh = axis.pcolormesh(x2, x1, mean, shading="nearest", cmap="viridis")
    colorbar = figure.colorbar(mesh, ax=axis, pad=0.025)
    objective = normalized.get("objective") if isinstance(normalized.get("objective"), dict) else {}
    equation = str(objective.get("equation") or "objective_score")
    unit = str(objective.get("unit") or "")
    colorbar.set_label(f"Predicted f(x1, x2){f' ({unit})' if unit else ''}", fontsize=9)
    observations = [item for item in normalized.get("training_observations", []) if isinstance(item, dict)]
    observed_x = []
    observed_y = []
    for item in observations:
        parameters = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        if isinstance(parameters.get(surface["y_parameter"]), (int, float)) and isinstance(parameters.get(surface["x_parameter"]), (int, float)):
            observed_x.append(parameters[surface["y_parameter"]])
            observed_y.append(parameters[surface["x_parameter"]])
    if observed_x:
        axis.scatter(observed_x, observed_y, color="white", edgecolor="#111827", linewidth=0.8, s=34, zorder=4, label="Measured f")
    next_point = normalized.get("next_point") if isinstance(normalized.get("next_point"), dict) else {}
    next_parameters = next_point.get("parameters") if isinstance(next_point.get("parameters"), dict) else {}
    next_x = next_parameters.get(surface["y_parameter"])
    next_y = next_parameters.get(surface["x_parameter"])
    if isinstance(next_x, (int, float)) and isinstance(next_y, (int, float)):
        axis.scatter([next_x], [next_y], color="#f97316", marker="x", linewidth=2.0, s=64, zorder=5, label="EI-selected next input")
    axis.set_xlabel(f"x2: {str(surface['y_parameter']).replace('_', ' ')}", fontsize=9)
    axis.set_ylabel(f"x1: {str(surface['x_parameter']).replace('_', ' ')}", fontsize=9)
    axis.set_title(
        f"Surrogate objective function, step {int(normalized.get('step') or 0)}\n"
        f"Inputs (x1, x2) → f(x1, x2) = {equation}",
        fontsize=10.5,
        fontweight="bold",
        loc="left",
    )
    if observed_x or (isinstance(next_x, (int, float)) and isinstance(next_y, (int, float))):
        axis.legend(loc="best", fontsize=7.5, frameon=False)
    return figure


def _plot_grouped_posterior(normalized: dict[str, Any], series_rows: list[dict[str, Any]]) -> Any:
    colors = ("#2563eb", "#0891b2", "#16a34a", "#7c3aed", "#dc2626", "#ca8a04")
    figure, (posterior_axis, acquisition_axis) = plt.subplots(
        2,
        1,
        figsize=(8.4, 5.7),
        sharex=True,
        gridspec_kw={"height_ratios": [3.0, 1.15], "hspace": 0.12},
    )
    figure.patch.set_facecolor("white")
    _style_axis(posterior_axis)
    _style_axis(acquisition_axis)
    for index, series in enumerate(series_rows):
        color = colors[index % len(colors)]
        label = str(series.get("label") or series.get("series_id") or f"Series {index + 1}")
        x = series["x"]
        posterior_axis.fill_between(x, series["lower_95"], series["upper_95"], color=color, alpha=0.11)
        posterior_axis.plot(x, series["mean"], color=color, linewidth=1.7, label=label)
        acquisition_axis.plot(x, series["acquisition"], color=color, linewidth=1.5, label=label)
        observations = [item for item in series.get("observations", []) if isinstance(item, dict)]
        if observations:
            posterior_axis.scatter(
                [item["x"] for item in observations],
                [item["score"] for item in observations],
                color=color,
                edgecolor="white",
                linewidth=0.7,
                s=30,
                zorder=4,
            )
    # Stable semantic legend entries remain separate from the design-stratum colors.
    posterior_axis.plot([], [], color="#111827", linewidth=1.7, label="Posterior mean")
    posterior_axis.fill_between([], [], [], color="#94a3b8", alpha=0.22, label="95% confidence interval")
    posterior_axis.scatter([], [], color="#2563eb", edgecolor="white", linewidth=0.7, s=30, label="Measured observations")
    next_point = normalized.get("next_point") if isinstance(normalized.get("next_point"), dict) else {}
    next_parameters = next_point.get("parameters") if isinstance(next_point.get("parameters"), dict) else {}
    x_parameter = str(series_rows[0].get("x_parameter") or "")
    next_x = next_parameters.get(x_parameter, next_point.get("x"))
    next_mean = next_point.get("mean")
    if isinstance(next_x, (int, float)) and isinstance(next_mean, (int, float)):
        posterior_axis.scatter(
            [next_x], [next_mean], color="#f97316", marker="x", linewidth=1.8, s=52,
            zorder=5, label="EI-selected next point",
        )
        posterior_axis.axvline(next_x, color="#f97316", linewidth=0.9, linestyle="--", alpha=0.75)
        acquisition_axis.axvline(next_x, color="#f97316", linewidth=0.9, linestyle="--", alpha=0.75)
    objective = normalized.get("objective") if isinstance(normalized.get("objective"), dict) else {}
    objective_unit = str(objective.get("unit") or "")
    posterior_axis.set_ylabel(f"Objective ({objective_unit})" if objective_unit else "Objective", fontsize=9)
    acquisition_axis.set_ylabel("Expected Improvement", fontsize=9)
    acquisition_axis.set_xlabel(str(series_rows[0].get("x_label") or x_parameter or "Parameter"), fontsize=9)
    posterior_axis.set_title(
        f"Bayesian optimization posterior, step {int(normalized.get('step') or 0)}",
        fontsize=11,
        fontweight="bold",
        loc="left",
    )
    posterior_axis.legend(loc="best", fontsize=6.8, frameon=False, ncols=2)
    return figure


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
    figure = _plot_posterior(normalized)

    figure.savefig(png_path, dpi=150, transparent=False, facecolor="white")
    figure.savefig(svg_path, transparent=False, facecolor="white")
    plt.close(figure)

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        surface = normalized.get("gp_surface") if isinstance(normalized.get("gp_surface"), dict) else {}
        if surface.get("mode") == "mixed_2d_gp_surface":
            trace = normalized.get("objective_trace") if isinstance(normalized.get("objective_trace"), dict) else {}
            writer.writerow(["search_x", surface["x_parameter"], surface["y_parameter"], "mean", "std", "lower_95", "upper_95", "acquisition"])
            for row in trace.get("rows", []):
                parameters = row.get("parameters") if isinstance(row.get("parameters"), dict) else {}
                mean = row["mean"]
                std = row["std"]
                writer.writerow([
                    row["search_x"],
                    parameters.get(surface["x_parameter"]),
                    parameters.get(surface["y_parameter"]),
                    mean,
                    std,
                    mean - 1.96 * std,
                    mean + 1.96 * std,
                    row["acquisition"],
                ])
        else:
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
