"""Live Posterior figures, using the approved bo-surface-preview/bo-3d-strips layout.

Only data/labels are supplied by the run; plotting does not fit or optimize a GP.
"""
from __future__ import annotations

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
from scipy.interpolate import RegularGridInterpolator


def _label(name):
    return {"cell_size_mm": "Cell size (mm)", "wall_thickness_mm": "Wall thickness (mm)"}.get(name, name.replace("_", " "))


def _coordinate(name, value):
    label = _label(name)
    return f"{label.removesuffix(' (mm)').lower()} {value:.3f}" + (" mm" if label.endswith(" (mm)") else "")


def plot_surface_views(payload):
    """Return the original side-by-side heatmaps and stacked square-base surfaces."""
    s = payload["response_surface"]
    x, y = np.asarray(s["x_values"]), np.asarray(s["y_values"])
    X, Y = np.meshgrid(x, y)
    xp, yp = s["x_parameter"], s["y_parameter"]
    obs = np.asarray([[o["parameters"][xp], o["parameters"][yp], o["score"]]
                      for o in payload.get("training_observations", [])
                      if xp in o.get("parameters", {}) and yp in o.get("parameters", {})], dtype=float).reshape(-1, 3)
    candidate = payload.get("next_point") or {}
    params = candidate.get("parameters") or {}
    point = (params[xp], params[yp]) if xp in params and yp in params else None
    objective = payload.get("objective") or {}
    unit = objective.get("unit") or ""
    name = "SEA" if objective.get("equation") == "specific_energy_absorption_J_per_g" else objective.get("name") or "Objective"
    suffix = f" ({unit})" if unit else ""
    acq = payload.get("acquisition") or {}
    acq_name = acq.get("name") or "Acquisition"
    is_ei = acq_name.lower().replace(" ", "") in {"expectedimprovement", "logexpectedimprovement"}
    acq_title = "Expected improvement" if is_ei else acq_name
    acq_short = "EI" if is_ei else acq_name
    acq_suffix = "" if "probability" in acq_name.lower() else suffix
    synthetic = bool(payload.get("synthetic_only"))
    title = f"BO objective posterior and {acq_title.lower()}, step {int(payload.get('step') or 0)}"
    observation_label = "Synthetic observations" if synthetic else "Measured observations"
    panels = [("mean", "Posterior mean", name + suffix, "viridis"),
              ("std", "Posterior uncertainty", "Standard deviation" + suffix, "magma"),
              ("acquisition", acq_title, acq_short + acq_suffix, "YlGnBu")]
    style = {"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
             "axes.spines.right": False, "axes.labelcolor": "#243247", "text.color": "#162236"}
    with plt.rc_context(style):
        heatmap, axes = plt.subplots(1, 3, figsize=(16, 5.5), constrained_layout=True)
        for ax, (key, heading, color_label, cmap) in zip(axes, panels):
            Z = np.asarray(s[key])
            mesh = ax.pcolormesh(X, Y, Z, shading="auto", cmap=cmap)
            ax.contour(X, Y, Z, levels=7, colors="white", linewidths=.45, alpha=.4)
            if len(obs):
                ax.scatter(obs[:, 0], obs[:, 1], s=48, facecolor="white", edgecolor="#172033", linewidth=.9, zorder=5, clip_on=False)
            if point:
                ax.scatter(*point, marker="*", s=240, color="#ff6534", edgecolor="white", linewidth=1, zorder=7)
            ax.set(xlim=(x.min(), x.max()), ylim=(y.min(), y.max()), xlabel=_label(xp), ylabel=_label(yp))
            ax.set_title(heading, fontsize=14, fontweight="bold", pad=12)
            ax.set_box_aspect(1)
            heatmap.colorbar(mesh, ax=ax, shrink=.82, pad=.025).set_label(color_label)
        handles = [Line2D([], [], marker="o", linestyle="none", color="white", markeredgecolor="#172033", label=f"{observation_label} ({len(obs)})"),
                   Line2D([], [], marker="*", linestyle="none", color="#ff6534", markersize=13, label="Next BO candidate")]
        rows = (payload.get("objective_trace") or {}).get("rows") or []
        path = [r["parameters"] for r in rows if xp in r.get("parameters", {}) and yp in r.get("parameters", {})]
        if path:
            axes[0].plot([p[xp] for p in path], [p[yp] for p in path], color="white", linewidth=1.1, linestyle="--", alpha=.75)
            handles.append(Line2D([], [], linestyle="--", color="#697586", label="Previous 1D display path (mean panel)"))
        # The historical diagnostic marker belongs only to the synthetic preview.
        marker = payload.get("preview_reference") if synthetic else None
        if marker:
            axes[0].scatter(marker[xp], marker[yp], marker="D", s=72, facecolor="#ff4bc2", edgecolor="white", linewidth=1, zorder=8)
            axes[0].annotate("Old graph x ≈ 0.90", (marker[xp], marker[yp]), xytext=(x.min()+.54*np.ptp(x), y.min()+.9*np.ptp(y)), color="white", fontsize=10, arrowprops={"arrowstyle": "->", "color": "white"})
        heatmap.legend(handles=handles, loc="outside lower center", ncols=3, frameon=False)
        heatmap.suptitle(title + (" · SYNTHETIC DATA ONLY" if synthetic else ""), fontsize=17, fontweight="bold")

    with plt.rc_context({**style, "text.color": "#243247"}):
        fig = plt.figure(figsize=(11, 10.5), facecolor="white")
        fig.text(.5, .982, title, fontsize=18, weight="bold", va="top", ha="center")
        direction = str(objective.get("direction") or "maximize").capitalize()
        acquisition_detail = "LogEI optimization / EI display" if is_ei and "log" in str(acq.get("raw_name")).lower() else acq_title
        fig.text(.5, .948, ("SYNTHETIC DATA ONLY · " if synthetic else "") + f"{(payload.get('backend') or {}).get('model') or 'GP'} · {len(obs)} observations · {direction} {name} · {acquisition_detail}", fontsize=10, ha="center", color="#526177")
        for i, (key, heading, color_label, cmap) in enumerate([
            ("mean", f"Predicted {name}", f"Predicted {name}"+suffix, "viridis"),
            ("std", "Uncertainty", "Standard deviation σ"+suffix, "Blues"),
            ("acquisition", "Expected\nimprovement" if is_ei else acq_title, acq_title+acq_suffix, "YlOrRd")]):
            bottom = .635 - i * .265
            ax = fig.add_axes([.20, bottom, .65, .235], projection="3d", computed_zorder=False)
            Z = np.asarray(s[key])
            norm = Normalize(vmin=float(Z.min()), vmax=float(Z.max()))
            ax.plot_surface(X, Y, Z, cmap=cmap, norm=norm, rcount=len(y), ccount=len(x), linewidth=0, antialiased=True, zorder=1, clip_on=False)
            ax.plot_wireframe(X, Y, Z, rstride=max(1,len(y)//8), cstride=max(1,len(x)//8), color="#26364d", alpha=.18, linewidth=.45, zorder=2, clip_on=False)
            if point:
                cz = float(RegularGridInterpolator((y, x), Z)([[point[1], point[0]]])[0])
                ax.scatter([point[0]], [point[1]], [cz], marker="*", s=230, color="#ff6534", edgecolor="white", linewidth=1.2, depthshade=False, zorder=4, clip_on=False)
            if key == "mean" and len(obs):
                ax.scatter(obs[:,0], obs[:,1], obs[:,2], s=48, color="#ed3855", edgecolor="white", linewidth=1, depthshade=False, zorder=3, clip_on=False)
            ax.set_xlim(x.min(), x.max())
            ax.set_ylim(y.min(), y.max())
            if key != "mean" and Z.min() >= 0:
                ax.set_zlim(0, max(float(Z.max()) * 1.05, 1e-12))
            ax.set_xticks(np.linspace(x.min(), x.max(), 3))
            ax.set_yticks(np.linspace(y.min(), y.max(), 3))
            ax.zaxis.set_major_locator(MaxNLocator(3))
            ax.tick_params(labelsize=9, pad=0)
            ax.set_proj_type("ortho")
            ax.view_init(elev=21, azim=-135)
            ax.set_box_aspect((1, 1, .35), zoom=1.55)
            ax.set_xlabel(_label(xp) if i == 2 else "", labelpad=2, fontsize=11)
            ax.set_ylabel(_label(yp) if i == 2 else "", labelpad=2, fontsize=11)
            for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
                axis.pane.set_facecolor((.96,.97,.98,.3))
                axis.pane.set_edgecolor((.7,.75,.8,.4))
                axis._axinfo["grid"]["color"] = (.65,.7,.76,.25)
            fig.text(.025, bottom+.125, heading, fontsize=14, weight="bold", va="center")
            cax = fig.add_axes([.842, bottom+.014, .019, .21])
            bar = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), cax=cax)
            bar.locator = MaxNLocator(nbins=5, steps=[1,2,2.5,5,10])
            bar.update_ticks()
            bar.ax.tick_params(labelsize=10, length=3, pad=5)
            bar.set_label(color_label, fontsize=11, labelpad=9)
            bar.outline.set_linewidth(.6)
        fig.legend(handles=[
            Line2D([], [], marker="o", color="#ed3855", markeredgecolor="white", linestyle="none", markersize=8, label=observation_label+" (mean surface)"),
            Line2D([], [], marker="*", color="#ff6534", markeredgecolor="white", linestyle="none", markersize=14, label="Next BO candidate")],
            loc="upper center", bbox_to_anchor=(.5,.935), ncols=2, frameon=False, fontsize=11)
        if point:
            fig.text(.5,.062,f"Next candidate: {_coordinate(xp, point[0])} · {_coordinate(yp, point[1])}", ha="center", fontsize=11, weight="bold")
            prediction = [float(candidate.get(k)) if candidate.get(k) is not None else float(RegularGridInterpolator((y,x),np.asarray(s[k]))([[point[1],point[0]]])[0]) for k in ("mean","std","acquisition")]
            fig.text(.5,.041,f"Predicted μ ≈ {prediction[0]:.3f} {unit} · σ ≈ {prediction[1]:.3f} {unit} · {acq_short} ≈ {prediction[2]:.3f} {unit if acq_suffix else ''}", ha="center", fontsize=11)
        if len(obs):
            best = obs[np.argmin(obs[:,2]) if direction.lower()=="minimize" else np.argmax(obs[:,2])]
            fig.text(.5,.020,f"Best observed {name}: {best[2]:.3f} {unit} · {_coordinate(xp, best[0])} · {_coordinate(yp, best[1])}", ha="center", fontsize=10, color="#526177")
    return heatmap, fig
