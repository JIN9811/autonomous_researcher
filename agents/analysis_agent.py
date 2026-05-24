"""
File purpose:
- Analyze UTM/equipment outputs and compute objective/uncertainty summaries.

Key classes/functions:
- AnalysisAgent

Inputs/outputs:
- Input: Lab Equipment Agent output, UTM curve data/files, specimen geometry
- Output: UTM metrics, objective score, uncertainty, and summary text

Dependencies:
- csv/json/math/pathlib
- agents.base_agent.BaseAgent

Modification guide:
- Safe places to edit: scoring formula and summary fields
- Risky places to edit: schema expected by memory DB and guardian
- Related files: knowledge/experiment_db.py, agents/knowledge_agent.py
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState
from utils.paths import resolve_path


_DISPLACEMENT_KEYS = (
    "displacement_mm",
    "extension_mm",
    "stroke_mm",
    "crosshead_mm",
    "position_mm",
    "displacement",
    "extension",
)
_FORCE_KEYS = ("force_n", "load_n", "force", "load", "force_N", "load_N")
_TIME_KEYS = ("time_s", "time_sec", "seconds", "time")


class AnalysisAgent(BaseAgent):
    """Computes UTM-based experiment analysis outputs."""

    name = "analysis_agent"

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        if math.isfinite(parsed):
            return parsed
        return default

    @staticmethod
    def _vector3(value: Any, default: list[float]) -> list[float]:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return [AnalysisAgent._safe_float(value[i], default[i]) for i in range(3)]
        return list(default)

    @staticmethod
    def _first_number(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        lowered = {str(key).strip().lower(): value for key, value in row.items()}
        for key in keys:
            if key in row:
                return AnalysisAgent._safe_float(row[key], math.nan)
            low_key = key.lower()
            if low_key in lowered:
                return AnalysisAgent._safe_float(lowered[low_key], math.nan)
        return None

    def _specimen_geometry(self, state: OrchestratorState) -> dict[str, float | list[float]]:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        specimen = state.run_metadata.get("specimen_result") if isinstance(state.run_metadata, dict) else {}
        specimen = specimen if isinstance(specimen, dict) else {}
        candidate = specimen.get("candidate") if isinstance(specimen.get("candidate"), dict) else {}
        parameters = candidate.get("parameters") if isinstance(candidate.get("parameters"), dict) else {}
        source = {**parameters, **spec}
        size = self._vector3(source.get("specimen_size_mm") or source.get("size_mm"), [20.0, 20.0, 20.0])
        area = max(float(source.get("cross_section_area_mm2") or size[0] * size[1]), 1e-6)
        gauge = max(float(source.get("gauge_length_mm") or source.get("height_mm") or size[2]), 1e-6)
        volume = max(size[0] * size[1] * size[2], 1e-6)
        mass = self._safe_float(source.get("measured_mass_g") or source.get("expected_mass_g"), 0.0)
        return {
            "specimen_size_mm": size,
            "cross_section_area_mm2": round(area, 6),
            "gauge_length_mm": round(gauge, 6),
            "volume_mm3": round(volume, 6),
            "mass_g": round(mass, 6),
        }

    @staticmethod
    def _specimen_result(state: OrchestratorState) -> dict[str, Any]:
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        specimen = metadata.get("specimen_result") if isinstance(metadata.get("specimen_result"), dict) else {}
        return dict(specimen)

    def _cae_payload(self, state: OrchestratorState, geometry: dict[str, Any]) -> dict[str, Any]:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        specimen = self._specimen_result(state)
        candidate = specimen.get("candidate") if isinstance(specimen.get("candidate"), dict) else {}
        parameters = candidate.get("parameters") if isinstance(candidate.get("parameters"), dict) else {}
        material = {
            "elastic_modulus_mpa": self._safe_float(
                spec.get("cae_elastic_modulus_mpa")
                or spec.get("elastic_modulus_mpa")
                or parameters.get("elastic_modulus_mpa"),
                1800.0,
            ),
            "poisson_ratio": self._safe_float(spec.get("cae_poisson_ratio") or spec.get("poisson_ratio"), 0.35),
            "yield_strength_mpa": self._safe_float(
                spec.get("cae_yield_strength_mpa") or spec.get("yield_strength_mpa"),
                35.0,
            ),
        }
        loading = {
            "load_type": str(spec.get("cae_load_type") or "cyclic_compression"),
            "load_max_n": self._safe_float(spec.get("cae_load_max_n") or spec.get("load_max_n"), 500.0),
            "load_min_ratio": self._safe_float(spec.get("cae_load_min_ratio") or spec.get("load_min_ratio"), 0.1),
            "cycles": int(self._safe_float(spec.get("cae_cycles") or spec.get("cycles"), 10.0)),
            "frequency_hz": self._safe_float(spec.get("cae_frequency_hz") or spec.get("frequency_hz"), 1.0),
        }
        boundary_condition = str(spec.get("cae_boundary_condition") or "bottom_fixed_support")
        loading_mode = str(spec.get("cae_loading_mode") or "top_cyclic_loading")
        legacy_cap = bool(spec.get("top_bottom_cap", False))
        return {
            "runtime_mode": state.mode.value,
            "mode": state.mode.value,
            "specimen_id": str(specimen.get("specimen_id") or spec.get("specimen_id") or state.experiment_id),
            "stl_path": str(specimen.get("stl_path") or spec.get("stl_path") or ""),
            "specimen_size_mm": geometry.get("specimen_size_mm", [20.0, 20.0, 20.0]),
            "cross_section_area_mm2": geometry.get("cross_section_area_mm2"),
            "gauge_length_mm": geometry.get("gauge_length_mm"),
            "material": material,
            "loading": loading,
            "boundary": {"bottom": "fixed_support", "top": "cyclic_loading"},
            "boundary_condition": boundary_condition,
            "loading_mode": loading_mode,
            "fixture": {
                "bottom_face": "fixed_support",
                "top_face": "cyclic_compression",
            },
            "analysis_platens": {
                "bottom": True,
                "top": True,
                "thickness_mm": self._safe_float(spec.get("cae_platen_thickness_mm"), 1.0),
                "applies_to": "cae_only_not_generated_stl",
            },
            "generated_model_caps": {
                "top_cap_enabled": bool(spec.get("top_cap_enabled", legacy_cap)),
                "bottom_cap_enabled": bool(spec.get("bottom_cap_enabled", legacy_cap)),
                "top_bottom_cap": bool(spec.get("top_cap_enabled", legacy_cap) or spec.get("bottom_cap_enabled", legacy_cap)),
                "skin_thickness_mm": self._safe_float(spec.get("skin_thickness_mm"), 0.0),
            },
            "design_parameters": {
                "geometry_type": str(spec.get("geometry_type") or ""),
                "relative_density": self._safe_float(spec.get("relative_density"), 0.32),
                "wall_thickness_mm": self._safe_float(spec.get("wall_thickness_mm"), 1.2),
                "cell_size_mm": self._safe_float(spec.get("cell_size_mm"), 5.0),
            },
            "mesh_size_mm": self._safe_float(spec.get("cae_mesh_size_mm") or spec.get("mesh_size_mm"), 2.0),
            "require_solver": bool(spec.get("require_cae_solver", False)),
            "source": "analysis_agent",
        }

    def _run_cae(self, state: OrchestratorState, ctx: AgentContext, geometry: dict[str, Any]) -> dict[str, Any] | None:
        tools = getattr(ctx, "tools", None)
        if tools is None:
            return None
        try:
            available = tools.list_tools() if hasattr(tools, "list_tools") else []
            if available and "cae.run_static_analysis" not in available:
                return None
            return tools.call("cae.run_static_analysis", self._cae_payload(state, geometry))
        except KeyError:
            return None
        except Exception as exc:
            return {
                "ok": False,
                "tool": "cae.run_static_analysis",
                "status": "error",
                "failure_code": "CAE_TOOL_ERROR",
                "message": f"{exc.__class__.__name__}: {exc}",
            }

    @staticmethod
    def _equipment_result(state: OrchestratorState) -> dict[str, Any]:
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        result = metadata.get("equipment_result") if isinstance(metadata.get("equipment_result"), dict) else {}
        if result:
            return dict(result)
        last_payload = metadata.get("last_stage_payload") if isinstance(metadata.get("last_stage_payload"), dict) else {}
        data = last_payload.get("data") if isinstance(last_payload.get("data"), dict) else {}
        result = data.get("equipment_result") if isinstance(data.get("equipment_result"), dict) else {}
        return dict(result)

    @staticmethod
    def _nested_candidates(source: dict[str, Any]) -> list[Any]:
        candidates: list[Any] = []
        for key in (
            "utm_data",
            "utm_curve",
            "curve",
            "measurements",
            "samples",
            "data",
            "raw_data",
        ):
            if key in source:
                candidates.append(source[key])
        for key in ("result", "payload", "analysis_input", "metadata"):
            nested = source.get(key)
            if isinstance(nested, dict):
                candidates.extend(AnalysisAgent._nested_candidates(nested))
        return candidates

    def _curve_from_rows(self, rows: Any) -> list[dict[str, float]]:
        if not isinstance(rows, list):
            return []
        curve: list[dict[str, float]] = []
        for index, item in enumerate(rows):
            if isinstance(item, dict):
                displacement = self._first_number(item, _DISPLACEMENT_KEYS)
                force = self._first_number(item, _FORCE_KEYS)
                time_s = self._first_number(item, _TIME_KEYS)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                time_s = self._safe_float(item[0], float(index)) if len(item) >= 3 else float(index)
                displacement = self._safe_float(item[-2], math.nan)
                force = self._safe_float(item[-1], math.nan)
            else:
                continue
            if displacement is None or force is None:
                continue
            if not math.isfinite(displacement) or not math.isfinite(force):
                continue
            point = {"displacement_mm": float(displacement), "force_N": max(0.0, float(force))}
            if time_s is not None and math.isfinite(time_s):
                point["time_s"] = float(time_s)
            curve.append(point)
        curve.sort(key=lambda item: item["displacement_mm"])
        return curve

    def _read_curve_file(self, path_value: Any) -> tuple[list[dict[str, float]], dict[str, Any]]:
        raw_path = str(path_value or "").strip()
        if not raw_path:
            return [], {}
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = resolve_path(raw_path)
        meta = {"path": str(path), "exists": path.exists()}
        if not path.exists() or not path.is_file():
            return [], meta
        suffix = path.suffix.lower()
        try:
            if suffix in {".json", ".jsonl"}:
                if suffix == ".jsonl":
                    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                else:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    rows = data.get("samples") if isinstance(data, dict) else data
                    if isinstance(data, dict):
                        for candidate in self._nested_candidates(data):
                            parsed = self._curve_from_rows(candidate)
                            if parsed:
                                meta["format"] = "json"
                                return parsed, meta
                meta["format"] = "json"
                return self._curve_from_rows(rows), meta
            with path.open("r", encoding="utf-8", newline="") as handle:
                sample = handle.read(2048)
                handle.seek(0)
                has_header = csv.Sniffer().has_header(sample) if sample.strip() else False
                if has_header:
                    rows = list(csv.DictReader(handle))
                    meta["format"] = "csv_header"
                    return self._curve_from_rows(rows), meta
                rows = []
                for row in csv.reader(handle):
                    if len(row) >= 2:
                        rows.append(row)
                meta["format"] = "csv_numeric"
                return self._curve_from_rows(rows), meta
        except Exception as exc:
            meta["error"] = f"{exc.__class__.__name__}: {exc}"
            return [], meta

    def _curve_from_equipment(self, equipment_result: dict[str, Any]) -> tuple[list[dict[str, float]], dict[str, Any]]:
        for candidate in self._nested_candidates(equipment_result):
            parsed = self._curve_from_rows(candidate)
            if parsed:
                return parsed, {"source": "equipment_result.inline"}
        for key in (
            "result_file",
            "result_path",
            "csv_path",
            "utm_result_file",
            "utm_csv_path",
            "artifact_path",
        ):
            if key in equipment_result:
                curve, meta = self._read_curve_file(equipment_result.get(key))
                if curve:
                    meta["source"] = f"equipment_result.{key}"
                    return curve, meta
                if meta:
                    return [], {"source": f"equipment_result.{key}", **meta}
        return [], {"source": "none"}

    def _synthetic_curve(self, state: OrchestratorState, geometry: dict[str, Any]) -> tuple[list[dict[str, float]], dict[str, Any]]:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        density = self._safe_float(spec.get("relative_density"), 0.32)
        wall = self._safe_float(spec.get("wall_thickness_mm"), 1.2)
        area = self._safe_float(geometry.get("cross_section_area_mm2"), 400.0)
        gauge = self._safe_float(geometry.get("gauge_length_mm"), 20.0)
        peak_force = max(80.0, area * (0.35 + 2.6 * density + 0.08 * wall))
        peak_disp = max(0.8, gauge * (0.10 + 0.18 * density))
        curve: list[dict[str, float]] = []
        for i in range(80):
            t = i / 79
            displacement = gauge * 0.32 * t
            if displacement <= peak_disp:
                force = peak_force * (displacement / peak_disp) ** 1.15
            else:
                drop = min(0.72, (displacement - peak_disp) / max(gauge * 0.22, 1e-6))
                force = peak_force * (1.0 - 0.55 * drop)
            ripple = 1.0 + 0.018 * math.sin(i * 0.7)
            curve.append(
                {
                    "time_s": round(i * 0.25, 6),
                    "displacement_mm": round(displacement, 6),
                    "force_N": round(max(0.0, force * ripple), 6),
                }
            )
        return curve, {"source": "synthetic_test_utm_curve", "reason": "no equipment UTM data in test mode"}

    @staticmethod
    def _linear_slope(points: list[dict[str, float]], peak_force: float) -> float:
        elastic = [
            point
            for point in points
            if point["displacement_mm"] > 0 and 0.05 * peak_force <= point["force_N"] <= 0.45 * peak_force
        ]
        if len(elastic) < 3:
            elastic = [point for point in points[: max(3, min(12, len(points)))] if point["displacement_mm"] > 0]
        if len(elastic) < 2:
            return 0.0
        xs = [point["displacement_mm"] for point in elastic]
        ys = [point["force_N"] for point in elastic]
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        denom = sum((x - x_mean) ** 2 for x in xs)
        if denom <= 1e-12:
            return 0.0
        slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=False)) / denom
        return max(0.0, slope)

    @staticmethod
    def _integrate_energy(points: list[dict[str, float]]) -> float:
        energy = 0.0
        for left, right in zip(points, points[1:], strict=False):
            dx = max(0.0, right["displacement_mm"] - left["displacement_mm"])
            energy += 0.5 * (left["force_N"] + right["force_N"]) * dx
        return max(0.0, energy)

    def _curve_quality(self, curve: list[dict[str, float]], peak_index: int) -> dict[str, Any]:
        if not curve:
            return {"ok": False, "point_count": 0, "warnings": ["empty_curve"]}
        warnings: list[str] = []
        monotonic_steps = sum(
            1
            for left, right in zip(curve, curve[1:], strict=False)
            if right["displacement_mm"] >= left["displacement_mm"]
        )
        monotonic_ratio = monotonic_steps / max(len(curve) - 1, 1)
        if len(curve) < 10:
            warnings.append("low_point_count")
        if monotonic_ratio < 0.95:
            warnings.append("non_monotonic_displacement")
        if peak_index in {0, len(curve) - 1}:
            warnings.append("peak_at_curve_boundary")
        if max(point["force_N"] for point in curve) <= 0:
            warnings.append("no_positive_force")
        return {
            "ok": not warnings,
            "point_count": len(curve),
            "monotonic_displacement_ratio": round(monotonic_ratio, 4),
            "warnings": warnings,
        }

    def _metrics(self, curve: list[dict[str, float]], geometry: dict[str, Any]) -> dict[str, Any]:
        if not curve:
            return {}
        peak_index, peak = max(enumerate(curve), key=lambda item: item[1]["force_N"])
        peak_force = peak["force_N"]
        peak_disp = peak["displacement_mm"]
        stiffness = self._linear_slope(curve, peak_force)
        energy = self._integrate_energy(curve)
        area = self._safe_float(geometry.get("cross_section_area_mm2"), 400.0)
        gauge = self._safe_float(geometry.get("gauge_length_mm"), 20.0)
        volume = self._safe_float(geometry.get("volume_mm3"), area * gauge)
        mass = self._safe_float(geometry.get("mass_g"), 0.0)
        strength = peak_force / max(area, 1e-6)
        modulus = stiffness * gauge / max(area, 1e-6)
        strain_at_peak = peak_disp / max(gauge, 1e-6)
        quality = self._curve_quality(curve, peak_index)
        return {
            "peak_force_N": round(peak_force, 6),
            "displacement_at_peak_mm": round(peak_disp, 6),
            "initial_stiffness_N_per_mm": round(stiffness, 6),
            "compressive_strength_MPa": round(strength, 6),
            "apparent_modulus_MPa": round(modulus, 6),
            "strain_at_peak": round(strain_at_peak, 6),
            "energy_absorption_mJ": round(energy, 6),
            "energy_density_mJ_per_mm3": round(energy / max(volume, 1e-6), 9),
            "specific_energy_absorption_J_per_g": round((energy / 1000.0) / mass, 9) if mass > 0 else None,
            "curve_quality": quality,
        }

    def _cae_score(self, cae_result: dict[str, Any] | None) -> float | None:
        if not isinstance(cae_result, dict) or not cae_result.get("ok"):
            return None
        metrics = cae_result.get("cae_metrics") if isinstance(cae_result.get("cae_metrics"), dict) else cae_result.get("metrics")
        if not isinstance(metrics, dict):
            return None
        if "structural_score" in metrics:
            return round(max(0.0, min(self._safe_float(metrics.get("structural_score"), 0.0), 1.0)), 4)
        fatigue = max(0.0, min(self._safe_float(metrics.get("fatigue_damage_proxy"), 0.0), 1.0))
        safety = self._safe_float(metrics.get("safety_factor_yield"), 1.0)
        displacement = self._safe_float(metrics.get("max_displacement_mm"), 0.0)
        score = (1.0 - fatigue) * min(safety / 2.0, 1.0) * (1.0 / (1.0 + displacement / 5.0))
        return round(max(0.0, min(score, 1.0)), 4)

    def _objective_score(self, metrics: dict[str, Any], state: OrchestratorState, cae_result: dict[str, Any] | None = None) -> float:
        metric_name = ""
        objective = state.current_experiment_objective if isinstance(state.current_experiment_objective, dict) else {}
        metric_name = str(objective.get("metric_name") or objective.get("name") or "").lower()
        strength = self._safe_float(metrics.get("compressive_strength_MPa"), 0.0)
        modulus = self._safe_float(metrics.get("apparent_modulus_MPa"), 0.0)
        sea = self._safe_float(metrics.get("specific_energy_absorption_J_per_g"), 0.0)
        energy_density = self._safe_float(metrics.get("energy_density_mJ_per_mm3"), 0.0)
        if "strength" in metric_name or "peak" in metric_name:
            score = min(strength / 5.0, 1.0)
        elif "stiff" in metric_name or "modulus" in metric_name:
            score = min(modulus / 80.0, 1.0)
        elif "energy" in metric_name or "absor" in metric_name:
            score = min(max(sea / 0.25, energy_density / 0.08), 1.0)
        else:
            score = 0.45 * min(strength / 5.0, 1.0) + 0.25 * min(modulus / 80.0, 1.0) + 0.30 * min(
                max(sea / 0.25, energy_density / 0.08),
                1.0,
            )
        quality = metrics.get("curve_quality") if isinstance(metrics.get("curve_quality"), dict) else {}
        if quality.get("warnings"):
            score *= 0.9
        cae_score = self._cae_score(cae_result)
        if cae_score is not None:
            score = 0.75 * score + 0.25 * cae_score
        return round(max(0.0, min(score, 1.0)), 4)

    def _uncertainty(
        self,
        source_meta: dict[str, Any],
        metrics: dict[str, Any],
        state: OrchestratorState,
        cae_result: dict[str, Any] | None = None,
    ) -> float:
        source = str(source_meta.get("source") or "")
        if source.startswith("synthetic"):
            base = 0.28
        elif state.mode == Mode.LIVE:
            base = 0.10
        else:
            base = 0.16
        quality = metrics.get("curve_quality") if isinstance(metrics.get("curve_quality"), dict) else {}
        point_count = int(quality.get("point_count") or 0)
        if point_count < 10:
            base += 0.18
        elif point_count < 30:
            base += 0.07
        base += 0.04 * len(quality.get("warnings") or [])
        if isinstance(cae_result, dict):
            if cae_result.get("ok"):
                base -= 0.03
            elif state.mode == Mode.TEST:
                base += 0.05
            elif cae_result.get("failure_code"):
                base += 0.03
        return round(min(max(base, 0.03), 0.85), 4)

    def _curve_preview(self, curve: list[dict[str, float]]) -> dict[str, Any]:
        if len(curve) <= 12:
            preview = curve
        else:
            indices = sorted({0, 1, 2, len(curve) // 4, len(curve) // 2, (3 * len(curve)) // 4, len(curve) - 3, len(curve) - 2, len(curve) - 1})
            preview = [curve[index] for index in indices]
        return {"point_count": len(curve), "preview": preview}

    async def _summary(self, state: OrchestratorState, ctx: AgentContext, analysis: dict[str, Any]) -> str:
        metrics = analysis.get("utm_metrics", {})
        cae_metrics = analysis.get("cae_metrics", {})
        use_llm = state.mode.value == "live" or ctx.force_real_llm_in_test
        fallback = (
            f"UTM analysis: peak_force={metrics.get('peak_force_N')} N, "
            f"strength={metrics.get('compressive_strength_MPa')} MPa, "
            f"CAE stress={cae_metrics.get('max_von_mises_MPa', 'n/a')} MPa, "
            f"objective={analysis.get('objective_score')}, uncertainty={analysis.get('uncertainty')}."
        )
        if not use_llm:
            return fallback
        timeout_s = 45.0 if state.mode == Mode.TEST else None
        try:
            response = await ctx.complete(
                "analysis_reasoning",
                (
                    "Summarize this UTM compression analysis for the operator. "
                    "Mention peak force, stiffness/strength, energy absorption, CAE bottom-fixed/top-cyclic result, data source, and whether the result is ready for Knowledge/Guardian. "
                    f"analysis={json.dumps(analysis, ensure_ascii=True, default=str)[:3500]}"
                ),
                timeout_s=timeout_s,
            )
            return response.text[:420]
        except Exception as exc:
            if state.mode == Mode.TEST:
                return f"{fallback} (analysis LLM degraded: {exc.__class__.__name__})"
            raise

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        geometry = self._specimen_geometry(state)
        cae_result = self._run_cae(state, ctx, geometry)
        cae_metrics = {}
        if isinstance(cae_result, dict):
            raw_cae_metrics = cae_result.get("cae_metrics") if isinstance(cae_result.get("cae_metrics"), dict) else cae_result.get("metrics")
            cae_metrics = dict(raw_cae_metrics) if isinstance(raw_cae_metrics, dict) else {}
        equipment_result = self._equipment_result(state)
        curve, source_meta = self._curve_from_equipment(equipment_result)
        if not curve and state.mode != Mode.LIVE:
            curve, source_meta = self._synthetic_curve(state, geometry)
        if not curve:
            analysis = {
                "ok": False,
                "failure_code": "UTM_DATA_REQUIRED",
                "summary": "UTM data is required for live analysis but no inline curve or readable result file was provided.",
                "objective_score": 0.0,
                "uncertainty": 0.85,
                "source": source_meta,
                "specimen_geometry": geometry,
                "cae_result": cae_result or {},
                "cae_metrics": cae_metrics,
                "equipment_result": {
                    "tool": equipment_result.get("tool", ""),
                    "status": equipment_result.get("status", ""),
                    "failure_code": equipment_result.get("failure_code"),
                },
            }
            return AgentResult(success=False, summary="Analysis blocked: UTM data required", data={"analysis": analysis})

        metrics = self._metrics(curve, geometry)
        objective = self._objective_score(metrics, state, cae_result)
        uncertainty = self._uncertainty(source_meta, metrics, state, cae_result)
        analysis = {
            "ok": True,
            "source": source_meta,
            "objective_score": objective,
            "uncertainty": uncertainty,
            "utm_metrics": metrics,
            "utm_curve": self._curve_preview(curve),
            "cae_result": cae_result or {},
            "cae_metrics": cae_metrics,
            "closed_loop_sources": [
                source_meta.get("source", "utm"),
                "cae.run_static_analysis" if isinstance(cae_result, dict) and cae_result.get("ok") else "cae.unavailable",
            ],
            "specimen_geometry": geometry,
            "equipment_result": {
                "tool": equipment_result.get("tool", ""),
                "status": equipment_result.get("status", ""),
                "program_id": equipment_result.get("program_id", ""),
                "sequence_id": equipment_result.get("sequence_id", ""),
                "result_file": equipment_result.get("result_file", ""),
            },
            "recommendation": "ready_for_knowledge_guardian"
            if uncertainty <= 0.35
            else "review_utm_curve_quality_before_model_update",
        }
        analysis["summary"] = await self._summary(state, ctx, analysis)
        return AgentResult(
            success=True,
            summary="UTM analysis complete",
            data={"analysis": analysis},
        )
