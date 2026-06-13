"""
File purpose:
- Deterministic/test and live-preflight bridge for open-source CAE analysis.

Key classes/functions:
- CAEBridgeConfig
- CAEBridge

Inputs/outputs:
- Input: geometry/material/loading payload
- Output: static/cyclic compression analysis metrics and solver status

Dependencies:
- shutil
- utils.paths.resolve_path

Modification guide:
- Safe places to edit: deterministic equivalent formulas and default parameters.
- Risky places to edit: response keys consumed by AnalysisAgent and CAE GUI.
- Related files: mcp_tools/cae_tools.py, agents/analysis_agent.py.
"""

from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from device_bridges.base_bridge import BaseBridge
from utils.paths import resolve_path


@dataclass(slots=True)
class CAEBridgeConfig:
    """Configuration for the CAE bridge."""

    enabled: bool = True
    mode: str = "test"
    default_solver: str = "calculix"
    default_mesher: str = "gmsh"
    solver_path: str = ""
    mesher_path: str = ""
    require_solver_in_live: bool = True
    artifact_dir: Path = field(default_factory=lambda: resolve_path("artifacts/cae"))
    default_material: dict[str, float] = field(
        default_factory=lambda: {
            "elastic_modulus_mpa": 1800.0,
            "poisson_ratio": 0.35,
            "yield_strength_mpa": 35.0,
        }
    )
    default_loading: dict[str, float | int | str] = field(
        default_factory=lambda: {
            "load_type": "cyclic_compression",
            "load_max_n": 500.0,
            "load_min_ratio": 0.1,
            "cycles": 10,
            "frequency_hz": 1.0,
        }
    )
    default_boundary: dict[str, str] = field(
        default_factory=lambda: {
            "bottom": "fixed_support",
            "top": "cyclic_loading",
        }
    )

    @classmethod
    def from_devices_config(cls, devices_config: dict[str, Any] | None = None, *, repo_root: Path | None = None) -> "CAEBridgeConfig":
        """Build CAE config from devices.yaml-like data."""
        raw = devices_config or {}
        devices = raw.get("devices", raw) if isinstance(raw, dict) else {}
        cae_raw = devices.get("cae", {}) if isinstance(devices, dict) and isinstance(devices.get("cae"), dict) else {}
        artifact = Path(str(cae_raw.get("artifact_dir", "artifacts/cae"))).expanduser()
        if not artifact.is_absolute():
            artifact = (repo_root or resolve_path(".")).joinpath(artifact).resolve()
        defaults = cls()
        material = dict(defaults.default_material)
        for key in ("material", "default_material"):
            if isinstance(cae_raw.get(key), dict):
                material.update(cae_raw[key])
        loading = dict(defaults.default_loading)
        for key in ("loading", "default_loading"):
            if isinstance(cae_raw.get(key), dict):
                loading.update(cae_raw[key])
        if isinstance(cae_raw.get("default_loading"), dict):
            default_loading = cae_raw["default_loading"]
            if "mode" in default_loading and "load_type" not in loading:
                loading["load_type"] = default_loading["mode"]
        boundary = dict(defaults.default_boundary)
        for key in ("boundary", "default_boundary"):
            if isinstance(cae_raw.get(key), dict):
                boundary.update(cae_raw[key])
        if cae_raw.get("default_boundary_condition"):
            boundary["bottom"] = str(cae_raw["default_boundary_condition"])
        if isinstance(cae_raw.get("default_loading"), dict) and cae_raw["default_loading"].get("mode"):
            boundary["top"] = str(cae_raw["default_loading"]["mode"])
        base_root = repo_root or resolve_path(".")

        def _configured_path(*keys: str) -> str:
            for key in keys:
                raw_path = str(cae_raw.get(key) or "").strip()
                if not raw_path:
                    continue
                path = Path(raw_path).expanduser()
                if not path.is_absolute():
                    path = base_root.joinpath(path).resolve()
                return str(path)
            return ""

        return cls(
            enabled=bool(cae_raw.get("enabled", True)),
            mode=str(cae_raw.get("mode", devices.get("mode", "test") if isinstance(devices, dict) else "test")),
            default_solver=str(cae_raw.get("solver", cae_raw.get("default_solver", "calculix"))),
            default_mesher=str(cae_raw.get("mesher", cae_raw.get("default_mesher", "gmsh"))),
            solver_path=_configured_path("solver_path", "calculix_path", "ccx_path"),
            mesher_path=_configured_path("mesher_path", "gmsh_path"),
            require_solver_in_live=bool(cae_raw.get("require_solver_in_live", True)),
            artifact_dir=artifact,
            default_material={key: float(value) for key, value in material.items()},
            default_loading={**loading},
            default_boundary={key: str(value) for key, value in boundary.items()},
        )


class CAEBridge(BaseBridge):
    """CAE tool bridge using deterministic equivalent analysis plus live solver preflight."""

    def __init__(self, config: CAEBridgeConfig) -> None:
        self.config = config

    @staticmethod
    def defaults() -> dict[str, Any]:
        cfg = CAEBridgeConfig()
        return {
            "solver": cfg.default_solver,
            "mesher": cfg.default_mesher,
            "material": cfg.default_material,
            "loading": cfg.default_loading,
            "boundary": cfg.default_boundary,
            "boundary_condition": "bottom_fixed_support",
            "loading_mode": "top_cyclic_loading",
            "specimen_size_mm": [20.0, 20.0, 20.0],
            "mesh_size_mm": 2.0,
        }

    def solver_status(self) -> dict[str, Any]:
        """Return local open-source CAE solver availability."""
        ccx = self._existing_executable(self.config.solver_path) or shutil.which("ccx") or shutil.which("calculix")
        gmsh = self._existing_executable(self.config.mesher_path) or shutil.which("gmsh")
        return {
            "ok": True,
            "tool": "cae.health",
            "default_solver": self.config.default_solver,
            "default_mesher": self.config.default_mesher,
            "calculix": {"available": bool(ccx), "path": ccx or ""},
            "gmsh": {"available": bool(gmsh), "path": gmsh or ""},
            "artifact_dir": str(self.config.artifact_dir),
            "mode": self.config.mode,
            "require_solver_in_live": self.config.require_solver_in_live,
            "defaults": {
                "solver": self.config.default_solver,
                "mesher": self.config.default_mesher,
                "material": self.config.default_material,
                "loading": self.config.default_loading,
                "boundary": self.config.default_boundary,
                "boundary_condition": "bottom_fixed_support",
                "loading_mode": "top_cyclic_loading",
                "specimen_size_mm": [20.0, 20.0, 20.0],
                "mesh_size_mm": 2.0,
            },
        }

    @staticmethod
    def _existing_executable(path_text: str) -> str:
        if not path_text:
            return ""
        path = Path(path_text).expanduser()
        return str(path) if path.exists() and path.is_file() else ""

    @staticmethod
    def _float(payload: dict[str, Any], key: str, default: float) -> float:
        try:
            value = float(payload.get(key, default))
        except (TypeError, ValueError):
            value = default
        return value if math.isfinite(value) else default

    @staticmethod
    def _int(payload: dict[str, Any], key: str, default: int) -> int:
        try:
            value = int(payload.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(1, value)

    @staticmethod
    def _bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        if value is None:
            return default
        return bool(value)

    @staticmethod
    def _bottom_boundary_from_label(value: Any) -> str:
        label = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        if label in {"bottom_fixed_support", "fixed_support", "fixed", "encastre"}:
            return "fixed_support"
        return str(value or "fixed_support")

    @staticmethod
    def _top_boundary_from_label(value: Any) -> str:
        label = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        if label in {"top_cyclic_loading", "cyclic_loading", "cyclic_compression", "top_cyclic_compression"}:
            return "cyclic_loading"
        return str(value or "cyclic_loading")

    @staticmethod
    def _boundary_condition_label(bottom_boundary: Any) -> str:
        bottom = str(bottom_boundary or "").strip().lower()
        return "bottom_fixed_support" if bottom == "fixed_support" else bottom or "bottom_fixed_support"

    @staticmethod
    def _loading_mode_label(top_boundary: Any, load_type: Any) -> str:
        top = str(top_boundary or "").strip().lower()
        load = str(load_type or "").strip().lower()
        if top == "cyclic_loading" and "cyclic" in load:
            return "top_cyclic_loading"
        return top or "top_cyclic_loading"

    @staticmethod
    def _vector3(value: Any, default: list[float]) -> list[float]:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            out: list[float] = []
            for idx in range(3):
                try:
                    parsed = float(value[idx])
                except (TypeError, ValueError):
                    parsed = default[idx]
                out.append(parsed if math.isfinite(parsed) and parsed > 0 else default[idx])
            return out
        return list(default)

    def _normalized_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        material = dict(self.config.default_material)
        if isinstance(payload.get("material"), dict):
            material.update(payload["material"])
        for key in ("elastic_modulus_mpa", "poisson_ratio", "yield_strength_mpa"):
            if key in payload:
                material[key] = payload[key]
        loading = dict(self.config.default_loading)
        if isinstance(payload.get("loading"), dict):
            loading.update(payload["loading"])
        for key in ("load_max_n", "load_max_N", "load_min_ratio", "cycles", "frequency_hz"):
            if key in payload:
                normalized_key = "load_max_n" if key == "load_max_N" else key
                loading[normalized_key] = payload[key]
        boundary = dict(self.config.default_boundary)
        if isinstance(payload.get("boundary"), dict):
            boundary.update(payload["boundary"])
        if payload.get("boundary_condition") not in (None, "", []):
            boundary["bottom"] = self._bottom_boundary_from_label(payload.get("boundary_condition"))
        else:
            boundary["bottom"] = self._bottom_boundary_from_label(boundary.get("bottom"))
        if payload.get("loading_mode") not in (None, "", []):
            boundary["top"] = self._top_boundary_from_label(payload.get("loading_mode"))
            if boundary["top"] == "cyclic_loading" and not str(loading.get("load_type", "")).startswith("cyclic"):
                loading["load_type"] = "cyclic_compression"
        else:
            boundary["top"] = self._top_boundary_from_label(boundary.get("top"))
        size = self._vector3(payload.get("specimen_size_mm") or payload.get("size_mm"), [20.0, 20.0, 20.0])
        boundary_condition = self._boundary_condition_label(boundary.get("bottom"))
        loading_mode = self._loading_mode_label(boundary.get("top"), loading.get("load_type"))
        design_raw = payload.get("design_parameters") if isinstance(payload.get("design_parameters"), dict) else {}
        design_parameters = {
            "geometry_type": str(design_raw.get("geometry_type") or payload.get("geometry_type") or "gyroid"),
            "relative_density": self._float(
                {**design_raw, **payload},
                "relative_density",
                0.32,
            ),
            "wall_thickness_mm": self._float(
                {**design_raw, **payload},
                "wall_thickness_mm",
                1.2,
            ),
            "cell_size_mm": self._float(
                {**design_raw, **payload},
                "cell_size_mm",
                5.0,
            ),
        }
        platens_raw = payload.get("analysis_platens") if isinstance(payload.get("analysis_platens"), dict) else {}
        platen_thickness = platens_raw.get("thickness_mm", payload.get("cae_platen_thickness_mm", 1.0))
        try:
            platen_thickness_value = float(platen_thickness)
        except (TypeError, ValueError):
            platen_thickness_value = 1.0
        analysis_platens = {
            "bottom": self._bool(platens_raw.get("bottom"), True),
            "top": self._bool(platens_raw.get("top"), True),
            "thickness_mm": max(0.2, platen_thickness_value),
            "applies_to": str(platens_raw.get("applies_to") or "cae_only_not_generated_stl"),
        }
        generated_caps = payload.get("generated_model_caps") if isinstance(payload.get("generated_model_caps"), dict) else {}
        return {
            "mode": str(payload.get("runtime_mode") or payload.get("mode") or self.config.mode or "test"),
            "solver": str(payload.get("solver") or self.config.default_solver),
            "mesher": str(payload.get("mesher") or self.config.default_mesher),
            "stl_path": str(payload.get("stl_path") or ""),
            "specimen_id": str(payload.get("specimen_id") or "manual-specimen"),
            "specimen_size_mm": size,
            "mesh_size_mm": self._float(payload, "mesh_size_mm", 2.0),
            "material": {
                "elastic_modulus_mpa": float(material.get("elastic_modulus_mpa", 1800.0)),
                "poisson_ratio": float(material.get("poisson_ratio", 0.35)),
                "yield_strength_mpa": float(material.get("yield_strength_mpa", 35.0)),
            },
            "loading": {
                "load_type": str(loading.get("load_type", "cyclic_compression")),
                "load_max_n": float(loading.get("load_max_n", 500.0)),
                "load_min_ratio": float(loading.get("load_min_ratio", 0.1)),
                "cycles": int(loading.get("cycles", 10)),
                "frequency_hz": float(loading.get("frequency_hz", 1.0)),
            },
            "boundary": {
                "bottom": str(boundary.get("bottom", "fixed_support")),
                "top": str(boundary.get("top", "cyclic_loading")),
            },
            "boundary_condition": boundary_condition,
            "loading_mode": loading_mode,
            "analysis_platens": analysis_platens,
            "generated_model_caps": dict(generated_caps),
            "design_parameters": design_parameters,
            "require_solver": bool(payload.get("require_solver", False)),
        }

    def _equivalent_analysis(self, normalized: dict[str, Any]) -> dict[str, Any]:
        size = normalized["specimen_size_mm"]
        area = max(float(size[0]) * float(size[1]), 1e-6)
        height = max(float(size[2]), 1e-6)
        material = normalized["material"]
        loading = normalized["loading"]
        design = normalized.get("design_parameters") if isinstance(normalized.get("design_parameters"), dict) else {}
        platens = normalized.get("analysis_platens") if isinstance(normalized.get("analysis_platens"), dict) else {}
        relative_density = min(max(float(design.get("relative_density", 0.32) or 0.32), 0.05), 0.85)
        wall = max(float(design.get("wall_thickness_mm", 1.2) or 1.2), 0.05)
        cell = max(float(design.get("cell_size_mm", 5.0) or 5.0), wall * 2.0)
        modulus = max(float(material["elastic_modulus_mpa"]), 1e-6)
        yield_strength = max(float(material["yield_strength_mpa"]), 1e-6)
        load_max = max(float(loading["load_max_n"]), 0.0)
        load_min_ratio = min(max(float(loading["load_min_ratio"]), 0.0), 1.0)
        cycles = max(int(loading["cycles"]), 1)
        nominal_stress = load_max / area
        cellular_modulus = modulus * max(0.035, relative_density**1.75)
        cellular_yield = yield_strength * max(0.04, relative_density**1.45)
        wall_cell_ratio = wall / max(cell, 1e-6)
        platen_factor = 0.90 if bool(platens.get("top", True)) and bool(platens.get("bottom", True)) else 1.0
        lattice_factor = (1.18 + 0.72 * (1.0 - relative_density) + 0.35 * wall_cell_ratio) * platen_factor
        max_von_mises = nominal_stress * lattice_factor / max(relative_density, 0.08)
        max_displacement = load_max * height / (cellular_modulus * area)
        stiffness = load_max / max(max_displacement, 1e-9)
        stress_ratio = max_von_mises / max(cellular_yield, 1e-9)
        load_amplitude = 0.5 * load_max * (1.0 - load_min_ratio)
        fatigue_damage = min(1.0, (stress_ratio**3) * math.log10(cycles + 1.0) * 0.18)
        safety_factor = cellular_yield / max(max_von_mises, 1e-9)
        compliance = max_displacement / max(load_max, 1e-9)
        return {
            "max_von_mises_MPa": round(max_von_mises, 6),
            "max_displacement_mm": round(max_displacement, 9),
            "apparent_stiffness_N_per_mm": round(stiffness, 6),
            "nominal_top_stress_MPa": round(nominal_stress, 6),
            "stress_concentration_factor": round(lattice_factor, 6),
            "load_amplitude_N": round(load_amplitude, 6),
            "load_max_N": round(load_max, 6),
            "load_min_N": round(load_max * load_min_ratio, 6),
            "fatigue_damage_proxy": round(fatigue_damage, 6),
            "safety_factor_yield": round(safety_factor, 6),
            "compliance_mm_per_N": round(compliance, 12),
            "structural_score": round(max(0.0, min(1.0, (1.0 - fatigue_damage) * min(safety_factor / 2.0, 1.0))), 6),
            "cycles": cycles,
            "relative_density_used": round(relative_density, 6),
            "effective_modulus_MPa": round(cellular_modulus, 6),
            "effective_yield_strength_MPa": round(cellular_yield, 6),
            "analysis_platens_applied": bool(platens.get("top", True) and platens.get("bottom", True)),
        }

    @staticmethod
    def _contour_color(value: float) -> str:
        value = max(0.0, min(1.0, value))
        palette = (
            "#243b8f",
            "#1d6ec1",
            "#24a7b5",
            "#4fbd6b",
            "#d8c647",
            "#e98633",
            "#c83f2f",
        )
        idx = min(len(palette) - 1, int(value * len(palette)))
        return palette[idx]

    def _write_contour_svg(self, path: Path, normalized: dict[str, Any], metrics: dict[str, Any]) -> None:
        size = normalized["specimen_size_mm"]
        max_stress = float(metrics.get("max_von_mises_MPa", 0.0) or 0.0)
        max_disp = float(metrics.get("max_displacement_mm", 0.0) or 0.0)
        structural = float(metrics.get("structural_score", 0.0) or 0.0)
        cols, rows = 18, 10
        cell_w, cell_h = 26, 18
        x0, y0 = 116, 72
        rects: list[str] = []
        for row in range(rows):
            z_norm = row / max(rows - 1, 1)
            for col in range(cols):
                x_norm = col / max(cols - 1, 1)
                edge = 0.42 * abs(x_norm - 0.5)
                top_load = 0.58 * z_norm
                tpms_band = 0.22 * (0.5 + 0.5 * math.sin((x_norm * 3.0 + z_norm * 2.0) * math.pi))
                value = max(0.0, min(1.0, top_load + edge + tpms_band))
                rects.append(
                    f'<rect x="{x0 + col * cell_w}" y="{y0 + (rows - 1 - row) * cell_h}" '
                    f'width="{cell_w + 0.8:.1f}" height="{cell_h + 0.8:.1f}" fill="{self._contour_color(value)}" />'
                )
        platen_top = '<rect x="96" y="50" width="508" height="16" rx="3" fill="#475569" />'
        platen_bottom = '<rect x="96" y="258" width="508" height="16" rx="3" fill="#475569" />'
        legend = []
        for idx in range(7):
            legend.append(
                f'<rect x="{640}" y="{74 + idx * 24}" width="30" height="18" fill="{self._contour_color(idx / 6.0)}" />'
            )
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="340" viewBox="0 0 760 340">\n'
            '<rect width="760" height="340" fill="#ffffff"/>\n'
            '<text x="28" y="34" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#0f172a">Equivalent FEM contour</text>\n'
            '<text x="28" y="58" font-family="Arial, sans-serif" font-size="13" fill="#475569">bottom fixed support, top cyclic loading, top/bottom platens are CAE-only</text>\n'
            f"{platen_top}\n{''.join(rects)}\n{platen_bottom}\n"
            '<rect x="96" y="72" width="508" height="180" fill="none" stroke="#0f172a" stroke-width="1.2"/>\n'
            '<line x1="350" y1="42" x2="350" y2="66" stroke="#dc2626" stroke-width="3"/>\n'
            '<polygon points="350,70 342,58 358,58" fill="#dc2626"/>\n'
            '<text x="100" y="296" font-family="Arial, sans-serif" font-size="13" fill="#334155">specimen '
            f'{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm</text>\n'
            '<text x="100" y="316" font-family="Arial, sans-serif" font-size="13" fill="#334155">'
            f'max von Mises={max_stress:.3f} MPa, displacement={max_disp:.6f} mm, structural score={structural:.3f}</text>\n'
            f"{''.join(legend)}\n"
            '<text x="676" y="88" font-family="Arial, sans-serif" font-size="12" fill="#475569">high</text>\n'
            '<text x="676" y="232" font-family="Arial, sans-serif" font-size="12" fill="#475569">low</text>\n'
            '</svg>\n'
        )
        path.write_text(svg, encoding="utf-8")

    def _write_artifacts(self, normalized: dict[str, Any], metrics: dict[str, Any], solver_status: dict[str, Any]) -> dict[str, str]:
        self.config.artifact_dir.mkdir(parents=True, exist_ok=True)
        specimen_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in normalized["specimen_id"])[:120] or "specimen"
        base = self.config.artifact_dir / f"{specimen_id}_cae"
        input_path = base.with_suffix(".json")
        report_path = base.with_suffix(".report.json")
        contour_path = base.with_suffix(".contour.svg")
        input_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=True), encoding="utf-8")
        self._write_contour_svg(contour_path, normalized, metrics)
        report_path.write_text(
            json.dumps(
                {
                    "ok": True,
                    "tool": "cae.run_static_analysis",
                    "input": normalized,
                    "metrics": metrics,
                    "solver_status": solver_status,
                },
                indent=2,
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        return {"input_path": str(input_path), "report_path": str(report_path), "contour_svg_path": str(contour_path)}

    def run_static_analysis(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run static/cyclic CAE equivalent analysis, with live solver preflight."""
        if not self.config.enabled:
            return {
                "ok": False,
                "tool": "cae.run_static_analysis",
                "status": "blocked",
                "failure_code": "CAE_BRIDGE_DISABLED",
                "message": "CAE bridge is disabled in config.",
            }
        raw_payload = dict(payload or {})
        normalized = self._normalized_payload(raw_payload)
        mode = normalized["mode"]
        solver = self.solver_status()
        live_mode = mode == "live"
        solver_available = bool(solver.get("calculix", {}).get("available"))
        require_solver = bool(raw_payload.get("require_solver")) if "require_solver" in raw_payload else self.config.require_solver_in_live
        if live_mode and require_solver and not solver_available:
            return {
                "ok": False,
                "tool": "cae.run_static_analysis",
                "mode": mode,
                "status": "blocked",
                "failure_code": "CAE_SOLVER_REQUIRED",
                "message": "CalculiX executable was not found. Install CalculiX/ccx or run in test mode.",
                "solver_status": solver,
                "boundary": normalized["boundary"],
                "loading": normalized["loading"],
                "boundary_condition": normalized["boundary_condition"],
                "loading_mode": normalized["loading_mode"],
                "analysis_platens": normalized["analysis_platens"],
                "step_trace": [
                    {"step": "PRECHECK", "status": "blocked", "detail": "ccx/calculix not found"},
                ],
            }
        metrics = self._equivalent_analysis(normalized)
        artifacts = self._write_artifacts(normalized, metrics, solver)
        return {
            "ok": True,
            "tool": "cae.run_static_analysis",
            "mode": mode,
            "status": "completed",
            "solver": normalized["solver"],
            "mesher": normalized["mesher"],
            "solver_mode": "deterministic_equivalent" if not live_mode else "solver_preflight_equivalent",
            "solver_status": solver,
            "specimen_id": normalized["specimen_id"],
            "stl_path": normalized["stl_path"],
            "specimen_size_mm": normalized["specimen_size_mm"],
            "boundary": normalized["boundary"],
            "boundary_condition": normalized["boundary_condition"],
            "loading": normalized["loading"],
            "loading_mode": normalized["loading_mode"],
            "analysis_platens": normalized["analysis_platens"],
            "generated_model_caps": normalized["generated_model_caps"],
            "design_parameters": normalized["design_parameters"],
            "material": normalized["material"],
            "mesh": {"mesh_size_mm": normalized["mesh_size_mm"], "source": "equivalent_block"},
            "metrics": metrics,
            "cae_metrics": metrics,
            "artifacts": artifacts,
            "closed_loop_source": True,
            "step_trace": [
                {"step": "PRECHECK", "status": "ok", "detail": f"mode={mode}"},
                {"step": "BUILD_MODEL", "status": "ok", "detail": "specimen equivalent model"},
                {"step": "APPLY_BC", "status": "ok", "detail": "bottom=fixed_support"},
                {"step": "APPLY_CYCLIC_LOAD", "status": "ok", "detail": "top=cyclic_loading"},
                {"step": "SOLVE", "status": "ok", "detail": "deterministic equivalent CAE"},
                {"step": "POSTPROCESS", "status": "ok", "detail": "metrics extracted"},
                {"step": "DONE", "status": "ok", "detail": "ready for closed-loop analysis"},
            ],
            "failure_code": None,
        }

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a CAE bridge command through the common bridge interface."""
        if command in {"run_static_analysis", "cae.run_static_analysis"}:
            return self.run_static_analysis(payload)
        if command in {"health", "solver_status", "cae.health"}:
            return self.solver_status()
        return {
            "ok": False,
            "tool": f"cae.{command}",
            "status": "blocked",
            "failure_code": "CAE_COMMAND_UNSUPPORTED",
            "message": f"Unsupported CAE command: {command}",
        }
