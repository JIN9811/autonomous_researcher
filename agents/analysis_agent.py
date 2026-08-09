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
import hashlib
import json
import math
from datetime import datetime, timezone
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
_LOCAL_FILE_KEYS = (
    "result_file",
    "result_path",
    "csv_path",
    "utm_result_file",
    "utm_csv_path",
    "artifact_path",
    "linux_path",
    "local_path",
    "path",
)
_FILE_CONTAINER_KEYS = (
    "equipment_report",
    "utm_data_ready",
    "equipment_handoff",
    "data_acquisition",
    "data_integrity",
    "artifact",
    "output_artifacts",
    "artifacts",
)


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
    def _header_role_unit(header: Any) -> tuple[str | None, float, str]:
        text = str(header or "").strip()
        lowered = text.lower().replace("_", " ").replace("-", " ")
        compact = "".join(ch for ch in lowered if ch.isalnum())
        unit = ""
        multiplier = 1.0
        role: str | None = None
        if any(token in compact for token in ("force", "load", "loadcell", "axialforce", "standardforce")):
            role = "force_N"
            unit = "N"
            if "kgf" in compact:
                multiplier = 9.80665
                unit = "kgf"
            elif "kn" in compact or "kilonewton" in compact:
                multiplier = 1000.0
                unit = "kN"
        elif any(token in compact for token in ("displacement", "extension", "stroke", "crosshead", "position", "travel", "compression")):
            role = "displacement_mm"
            unit = "mm"
            if "inch" in compact or compact.endswith("in") or "inches" in compact:
                multiplier = 25.4
                unit = "in"
        elif any(token in compact for token in ("times", "timesec", "elapsedtime", "second", "seconds")) or compact in {"time", "t", "sec", "s", "min"}:
            role = "time_s"
            unit = "s"
            if "min" in compact and "admin" not in compact:
                multiplier = 60.0
                unit = "min"
        elif "stress" in compact:
            role = "stress_MPa"
            unit = "MPa"
            if "kpa" in compact:
                multiplier = 0.001
                unit = "kPa"
            elif "psi" in compact:
                multiplier = 0.00689476
                unit = "psi"
        elif "strain" in compact:
            role = "strain"
            unit = "mm/mm"
            if "percent" in compact or "%" in lowered:
                multiplier = 0.01
                unit = "%"
        return role, multiplier, unit

    @classmethod
    def _column_mapping_report(cls, headers: Any) -> dict[str, Any]:
        mapping: dict[str, Any] = {}
        roles: dict[str, str] = {}
        if not headers:
            return {
                "schema": "analysis_column_mapping.v1",
                "mappings": {},
                "column_mapping_confidence": 0.0,
                "unit_mapping_confidence": 0.0,
                "warnings": ["no_headers"],
            }
        for header in headers:
            role, multiplier, unit = cls._header_role_unit(header)
            if not role:
                continue
            mapping[str(header)] = {"canonical": role, "multiplier": multiplier, "unit": unit}
            roles[role] = str(header)
        required = {"displacement_mm", "force_N"}
        has_required = required.issubset(set(roles))
        confidence = 0.95 if has_required else 0.55 if roles else 0.0
        unit_confidence = 0.92 if has_required else 0.50 if roles else 0.0
        warnings = [] if has_required else ["missing_force_or_displacement_mapping"]
        return {
            "schema": "analysis_column_mapping.v1",
            "mappings": mapping,
            "roles": roles,
            "column_mapping_confidence": confidence,
            "unit_mapping_confidence": unit_confidence,
            "warnings": warnings,
        }

    @staticmethod
    def _first_number(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        lowered = {str(key).strip().lower(): value for key, value in row.items()}
        for key in keys:
            if key in row:
                return AnalysisAgent._safe_float(row[key], math.nan)
            low_key = key.lower()
            if low_key in lowered:
                return AnalysisAgent._safe_float(lowered[low_key], math.nan)
        target_role = ""
        if keys == _FORCE_KEYS:
            target_role = "force_N"
        elif keys == _DISPLACEMENT_KEYS:
            target_role = "displacement_mm"
        elif keys == _TIME_KEYS:
            target_role = "time_s"
        for header, value in row.items():
            role, multiplier, _unit = AnalysisAgent._header_role_unit(header)
            if role == target_role:
                parsed = AnalysisAgent._safe_float(value, math.nan)
                return parsed * multiplier if math.isfinite(parsed) else math.nan
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

    def _cae_simulation_loop(self, cae_result: dict[str, Any] | None) -> dict[str, Any]:
        """Expose CAE/CalculiX simulation evidence in the legacy loop slot."""
        if not isinstance(cae_result, dict):
            return {
                "schema": "analysis_cae_simulation_loop.v1",
                "status": "skipped",
                "reason": "cae_tool_unavailable",
                "iterations": [],
                "selected_result": {},
                "tool_sequence": ["cae.health", "cae.run_static_analysis"],
            }
        record = {
            "iteration": 1,
            "tool": cae_result.get("tool", "cae.run_static_analysis"),
            "status": cae_result.get("status", "unknown"),
            "ok": bool(cae_result.get("ok")),
            "solver": cae_result.get("solver") or cae_result.get("default_solver") or "calculix",
            "mesh_size_mm": cae_result.get("mesh_size_mm"),
            "agreement_source": "fem_utm_comparison.v1",
        }
        return {
            "schema": "analysis_cae_simulation_loop.v1",
            "status": "completed" if cae_result.get("ok") else "blocked",
            "health": {},
            "iterations": [record],
            "selected_iteration": 1 if cae_result.get("ok") else None,
            "selected_cache_status": cae_result.get("cache_status"),
            "selected_result": cae_result if cae_result.get("ok") else {},
            "tool_sequence": ["cae.health", "cae.run_static_analysis"],
            "safety_rule": "simulation evidence is produced only through registered CAE/CalculiX bridge tools and validated payloads",
        }

    @staticmethod
    def _cae_as_fem_result(cae_result: dict[str, Any] | None) -> dict[str, Any]:
        """Keep legacy FEM report slots backed by CAE/CalculiX evidence."""
        if not isinstance(cae_result, dict):
            return {}
        return {"schema": "fem_result.v1", "source": "cae.run_static_analysis", "result": cae_result}

    @staticmethod
    def _equipment_result(state: OrchestratorState) -> dict[str, Any]:
        """Collect Equipment handoff data from result, report, packet, and last-stage payloads."""
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        sources: list[dict[str, Any]] = [metadata]
        last_payload = metadata.get("last_stage_payload") if isinstance(metadata.get("last_stage_payload"), dict) else {}
        data = last_payload.get("data") if isinstance(last_payload.get("data"), dict) else {}
        if data:
            sources.append(data)

        merged: dict[str, Any] = {}
        for source in sources:
            result = source.get("equipment_result") if isinstance(source.get("equipment_result"), dict) else {}
            if result:
                merged.update(dict(result))
            for key in ("equipment_report", "utm_data_ready", "equipment_handoff"):
                value = source.get(key) if isinstance(source.get(key), dict) else {}
                if value and key not in merged:
                    merged[key] = dict(value)
        return merged

    @staticmethod
    def _file_path_candidates(source: Any, *, prefix: str = "equipment_result") -> list[tuple[str, Any]]:
        """Return local file candidates from Equipment result/report/packet structures."""
        candidates: list[tuple[str, Any]] = []
        if isinstance(source, dict):
            for key in _LOCAL_FILE_KEYS:
                value = source.get(key)
                if value:
                    candidates.append((f"{prefix}.{key}", value))
            for key in _FILE_CONTAINER_KEYS:
                value = source.get(key)
                if isinstance(value, dict):
                    candidates.extend(AnalysisAgent._file_path_candidates(value, prefix=f"{prefix}.{key}"))
                elif isinstance(value, list):
                    for index, item in enumerate(value):
                        candidates.extend(AnalysisAgent._file_path_candidates(item, prefix=f"{prefix}.{key}[{index}]"))
        elif isinstance(source, list):
            for index, item in enumerate(source):
                candidates.extend(AnalysisAgent._file_path_candidates(item, prefix=f"{prefix}[{index}]"))
        seen: set[str] = set()
        unique: list[tuple[str, Any]] = []
        for label, value in candidates:
            token = f"{label}:{value}"
            if token in seen:
                continue
            seen.add(token)
            unique.append((label, value))
        return unique

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

    def _curve_points_from_rows(self, rows: Any, *, sort_by_displacement: bool) -> list[dict[str, float]]:
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
            # UTM compression exports may use either positive or negative force sign.
            point = {"displacement_mm": float(displacement), "force_N": abs(float(force))}
            if time_s is not None and math.isfinite(time_s):
                point["time_s"] = float(time_s)
            curve.append(point)
        if sort_by_displacement:
            curve.sort(key=lambda item: item["displacement_mm"])
        return curve

    def _curve_from_rows(self, rows: Any) -> list[dict[str, float]]:
        return self._curve_points_from_rows(rows, sort_by_displacement=True)

    @staticmethod
    def _file_fingerprint(path: Path) -> dict[str, Any]:
        if not path.exists() or not path.is_file():
            return {"exists": False, "path": str(path)}
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        stat = path.stat()
        return {
            "artifact_id": f"utm_raw_{digest.hexdigest()[:16]}",
            "path": str(path),
            "exists": True,
            "suffix": path.suffix.lower(),
            "size_bytes": stat.st_size,
            "sha256": digest.hexdigest(),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }

    @staticmethod
    def _curve_signal_quality(curve: list[dict[str, float]]) -> dict[str, Any]:
        if not curve:
            return {"ok": False, "failure_code": "UTM_DATA_REQUIRED", "message": "No UTM curve points were parsed.", "point_count": 0}
        eps = 1e-9
        force_values = [float(point.get("force_N", 0.0)) for point in curve]
        displacement_values = [float(point.get("displacement_mm", 0.0)) for point in curve]
        time_values = [float(point["time_s"]) for point in curve if "time_s" in point and math.isfinite(float(point["time_s"]))]
        force_range = max(force_values) - min(force_values)
        displacement_range = max(displacement_values) - min(displacement_values)
        force_nonzero = any(abs(value) > eps for value in force_values)
        force_changes = force_range > eps
        displacement_changes = displacement_range > eps
        time_monotonic = True
        if len(time_values) >= 2:
            time_monotonic = all((b - a) >= -eps for a, b in zip(time_values, time_values[1:], strict=False))
        quality = {
            "ok": True,
            "point_count": len(curve),
            "force_nonzero": force_nonzero,
            "force_changes": force_changes,
            "force_range_N": force_range,
            "force_min_N": min(force_values),
            "force_max_N": max(force_values),
            "displacement_changes": displacement_changes,
            "displacement_range_mm": displacement_range,
            "displacement_min_mm": min(displacement_values),
            "displacement_max_mm": max(displacement_values),
            "time_monotonic_non_decreasing": time_monotonic,
        }
        if len(curve) < 2:
            quality.update({"ok": False, "failure_code": "UTM_DATA_PARSE_FAILED", "message": "UTM curve must contain at least two points."})
        elif not time_monotonic:
            quality.update({"ok": False, "failure_code": "UTM_DATA_NON_MONOTONIC_TIME", "message": "UTM time_s values are not monotonic non-decreasing."})
        elif not displacement_changes:
            quality.update({"ok": False, "failure_code": "UTM_DATA_NO_DISPLACEMENT_SIGNAL", "message": "UTM displacement_mm does not change across samples."})
        elif not force_nonzero or not force_changes:
            quality.update({"ok": False, "failure_code": "UTM_DATA_NO_FORCE_SIGNAL", "message": "UTM force_N has no nonzero changing load signal."})
        return quality

    def _read_curve_file(self, path_value: Any) -> tuple[list[dict[str, float]], dict[str, Any]]:
        raw_path = str(path_value or "").strip()
        if not raw_path:
            return [], {}
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = resolve_path(raw_path)
        meta = {"path": str(path), "exists": path.exists(), "fingerprint": self._file_fingerprint(path)}
        if not path.exists() or not path.is_file():
            return [], meta
        suffix = path.suffix.lower()
        meta.update({"suffix": suffix, "parser_probe": {"attempted": True}})
        try:
            if suffix in {".json", ".jsonl"}:
                if suffix == ".jsonl":
                    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                else:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    rows = data.get("samples") if isinstance(data, dict) else data
                    if isinstance(data, dict):
                        for candidate in self._nested_candidates(data):
                            raw_curve = self._curve_points_from_rows(candidate, sort_by_displacement=False)
                            if raw_curve:
                                parsed = sorted(raw_curve, key=lambda item: item["displacement_mm"])
                                meta["format"] = "json"
                                meta["parser_id"] = "analysis.parsers.json_curve"
                                meta["column_mapping"] = self._column_mapping_report(raw_curve[0].keys() if raw_curve else [])
                                meta["signal_quality_probe"] = self._curve_signal_quality(raw_curve)
                                return parsed, meta
                raw_curve = self._curve_points_from_rows(rows, sort_by_displacement=False)
                meta["format"] = "json"
                meta["parser_id"] = "analysis.parsers.json_curve" if suffix == ".json" else "analysis.parsers.jsonl_curve"
                meta["column_mapping"] = self._column_mapping_report(raw_curve[0].keys() if raw_curve else [])
                meta["signal_quality_probe"] = self._curve_signal_quality(raw_curve)
                return sorted(raw_curve, key=lambda item: item["displacement_mm"]), meta
            with path.open("r", encoding="utf-8", newline="") as handle:
                sample = handle.read(2048)
                handle.seek(0)
                has_header = csv.Sniffer().has_header(sample) if sample.strip() else False
                if has_header:
                    rows = list(csv.DictReader(handle))
                    raw_curve = self._curve_points_from_rows(rows, sort_by_displacement=False)
                    meta["format"] = "csv_header"
                    meta["parser_id"] = "analysis.parsers.csv_header"
                    meta["column_mapping"] = self._column_mapping_report(rows[0].keys() if rows else [])
                    meta["signal_quality_probe"] = self._curve_signal_quality(raw_curve)
                    return sorted(raw_curve, key=lambda item: item["displacement_mm"]), meta
                rows = []
                for row in csv.reader(handle):
                    if len(row) >= 2:
                        rows.append(row)
                raw_curve = self._curve_points_from_rows(rows, sort_by_displacement=False)
                meta["format"] = "csv_numeric"
                meta["parser_id"] = "analysis.parsers.csv_numeric"
                meta["column_mapping"] = {"schema": "analysis_column_mapping.v1", "mappings": {"col[-2]": {"canonical": "displacement_mm", "multiplier": 1.0, "unit": "mm"}, "col[-1]": {"canonical": "force_N", "multiplier": 1.0, "unit": "N"}}, "column_mapping_confidence": 0.75, "unit_mapping_confidence": 0.70, "warnings": ["numeric_csv_no_header"]}
                meta["signal_quality_probe"] = self._curve_signal_quality(raw_curve)
                return sorted(raw_curve, key=lambda item: item["displacement_mm"]), meta
        except Exception as exc:
            meta["error"] = f"{exc.__class__.__name__}: {exc}"
            return [], meta

    @staticmethod
    def _live_equipment_handoff_gate(equipment_result: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Defensively block live Analysis if Equipment handoff evidence is not ready."""
        equipment_report = equipment_result.get("equipment_report") if isinstance(equipment_result.get("equipment_report"), dict) else {}
        equipment_handoff = equipment_result.get("equipment_handoff") if isinstance(equipment_result.get("equipment_handoff"), dict) else {}
        utm_packet = equipment_result.get("utm_data_ready") if isinstance(equipment_result.get("utm_data_ready"), dict) else {}
        live_audit = equipment_report.get("live_evidence_audit") if isinstance(equipment_report.get("live_evidence_audit"), dict) else {}
        decision = equipment_report.get("decision") if isinstance(equipment_report.get("decision"), dict) else {}
        cross_checks = equipment_report.get("cross_checks") if isinstance(equipment_report.get("cross_checks"), dict) else {}
        cross_checks = dict(cross_checks)
        screen_audit = live_audit.get("screen_evidence") if isinstance(live_audit.get("screen_evidence"), dict) else {}
        linux_audit = live_audit.get("linux_artifact_pull") if isinstance(live_audit.get("linux_artifact_pull"), dict) else {}
        vision_audit = live_audit.get("vision_evidence") if isinstance(live_audit.get("vision_evidence"), dict) else {}
        request_audit = live_audit.get("request_audit_log") if isinstance(live_audit.get("request_audit_log"), dict) else {}
        audit_gate_defaults = {
            "screen_evidence_complete": bool(screen_audit.get("ok")),
            "linux_artifact_pulled": bool(linux_audit.get("ok")),
            "vision_evidence_complete": bool(vision_audit.get("ok") or vision_audit.get("all_required_ok")),
            "request_audit_log_available": bool(request_audit.get("ok")),
            "request_audit_execute_identity_match": request_audit.get("execute_identity_match") is not False,
        }
        for name, value in audit_gate_defaults.items():
            if name not in cross_checks:
                cross_checks[name] = value
        required_for_handoff = bool(live_audit.get("required_for_handoff"))
        bridge_report = equipment_report.get("bridge") if isinstance(equipment_report.get("bridge"), dict) else {}
        is_windows_utm = str(
            equipment_result.get("bridge")
            or bridge_report.get("provider")
            or equipment_report.get("equipment_bridge")
            or ""
        ).lower() == "windows_pyautogui"
        control_plan = equipment_report.get("control_plan") if isinstance(equipment_report.get("control_plan"), dict) else {}
        program_id = str(equipment_result.get("program_id") or control_plan.get("program_id") or "")
        if program_id.startswith("utm_") and (equipment_report or equipment_handoff or utm_packet):
            required_for_handoff = True if is_windows_utm or required_for_handoff else required_for_handoff
        if not (required_for_handoff or equipment_handoff or utm_packet):
            return True, {"ok": True, "status": "not_required"}

        blockers: list[str] = []
        handoff_status = str(equipment_handoff.get("status") or decision.get("handoff_status") or "")
        if handoff_status != "ready_for_analysis":
            blockers.append(str(equipment_handoff.get("failure_code") or decision.get("failure_code") or "EQUIPMENT_HANDOFF_NOT_READY"))
        if utm_packet and str(utm_packet.get("status") or "") != "ready":
            blockers.append(str(utm_packet.get("failure_code") or "UTM_DATA_READY_PACKET_NOT_READY"))
        if required_for_handoff:
            required_checks = (
                "screen_started",
                "physical_motion_started",
                "save_completed",
                "data_file_created",
                "data_parse_probe_ok",
                "save_export_responsibility_ok",
                "screen_evidence_complete",
                "linux_artifact_pulled",
                "vision_evidence_complete",
                "request_audit_log_available",
                "request_audit_execute_identity_match",
            )
            missing = [name for name in required_checks if cross_checks.get(name) is not True]
            if missing:
                blockers.append("EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:" + ",".join(missing))
            audit_decision = live_audit.get("decision") if isinstance(live_audit.get("decision"), dict) else {}
            if audit_decision.get("blocking_reasons") and isinstance(audit_decision.get("blocking_reasons"), list):
                blockers.extend(str(item) for item in audit_decision["blocking_reasons"] if str(item or "").strip())
        blockers = list(dict.fromkeys(item for item in blockers if item and item != "None"))
        return (not blockers), {
            "ok": not blockers,
            "status": "ready_for_analysis" if not blockers else "blocked",
            "failure_code": blockers[0] if blockers else None,
            "blockers": blockers,
            "handoff_status": handoff_status,
            "required_for_handoff": required_for_handoff,
        }

    def _curve_from_equipment(self, equipment_result: dict[str, Any]) -> tuple[list[dict[str, float]], dict[str, Any]]:
        for candidate in self._nested_candidates(equipment_result):
            parsed = self._curve_from_rows(candidate)
            if parsed:
                return parsed, {"source": "equipment_result.inline"}
        first_meta: dict[str, Any] = {}
        for label, path_value in self._file_path_candidates(equipment_result):
            curve, meta = self._read_curve_file(path_value)
            if curve:
                meta["source"] = label
                return curve, meta
            if meta and not first_meta:
                first_meta = {"source": label, **meta}
        return [], first_meta or {"source": "none"}

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

    @staticmethod
    def _compiled_objective_requested(state: OrchestratorState) -> bool:
        objective = state.current_experiment_objective if isinstance(state.current_experiment_objective, dict) else {}
        return bool(
            objective.get("schema_version") == "objective_spec.v1"
            or objective.get("objective_hash")
            or objective.get("compiled_objective")
        )

    @staticmethod
    def _objective_service(ctx: AgentContext) -> Any | None:
        tools = getattr(ctx, "tools", None)
        resource = getattr(tools, "resource", None)
        return resource("objective.service") if callable(resource) else None

    @staticmethod
    def _registry_metric_values(service: Any, metrics: dict[str, Any]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for definition in service.registry.list():
            source_name = str(definition.source_path).rsplit(".", 1)[-1]
            if source_name in metrics:
                values[definition.metric_id] = metrics[source_name]
        return values

    def _evaluate_compiled_objective(
        self,
        *,
        state: OrchestratorState,
        ctx: AgentContext,
        metrics: dict[str, Any],
        uncertainty: float,
        source_meta: dict[str, Any],
        equipment_result: dict[str, Any],
        cae_result: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        service = self._objective_service(ctx)
        requested = self._compiled_objective_requested(state)
        if service is None:
            if requested:
                raise RuntimeError("OBJECTIVE_BINDING_REQUIRED: objective service is unavailable")
            return None
        binding = service.status(run_id=state.run_id).get("active_binding")
        if not isinstance(binding, dict):
            if requested:
                raise RuntimeError("OBJECTIVE_BINDING_REQUIRED: run has no active objective binding")
            return None
        requested_objective = state.current_experiment_objective if isinstance(state.current_experiment_objective, dict) else {}
        requested_hash = str(requested_objective.get("objective_hash") or "")
        if requested_hash and requested_hash != str(binding.get("objective_hash") or ""):
            raise RuntimeError("OBJECTIVE_BINDING_MISMATCH: requested and active objective hashes differ")
        requested_id = str(requested_objective.get("objective_id") or "")
        if requested and requested_id and requested_id != str(binding.get("objective_id") or ""):
            raise RuntimeError("OBJECTIVE_BINDING_MISMATCH: requested and active objective ids differ")
        provenance_refs = [
            str(item.get("path") or item.get("source") or "")
            for item in self._artifact_refs(equipment_result, source_meta, cae_result)
            if str(item.get("path") or item.get("source") or "").strip()
        ]
        if not provenance_refs:
            provenance_refs = [str(source_meta.get("source") or "analysis_agent")]
        fidelity = "synthetic" if str(source_meta.get("source") or "").startswith("synthetic") else "measured"
        evaluation = service.evaluate(
            run_id=state.run_id,
            metrics=self._registry_metric_values(service, metrics),
            observation_id=f"{state.run_id}:{state.experiment_id}:analysis",
            uncertainty=uncertainty,
            provenance_refs=provenance_refs,
            fidelity=fidelity,
        )
        return evaluation.model_dump(mode="json")

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

    @staticmethod
    def _safe_slug(value: Any, default: str = "item") -> str:
        text = str(value or default)
        slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text).strip("_")
        return slug[:120] or default

    def _analysis_artifact_dir(self, state: OrchestratorState) -> Path:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        specimen_id = str(spec.get("specimen_id") or state.experiment_id or "specimen")
        path = resolve_path("runs") / self._safe_slug(state.run_id, "run") / "analysis" / self._safe_slug(specimen_id, "specimen")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
        return str(path)

    @staticmethod
    def _canonical_curve(curve: list[dict[str, float]], geometry: dict[str, Any]) -> list[dict[str, Any]]:
        area = max(AnalysisAgent._safe_float(geometry.get("cross_section_area_mm2"), 400.0), 1e-6)
        gauge = max(AnalysisAgent._safe_float(geometry.get("gauge_length_mm"), 20.0), 1e-6)
        force_offset = float(curve[0].get("force_N", 0.0)) if curve else 0.0
        disp_offset = float(curve[0].get("displacement_mm", 0.0)) if curve else 0.0
        canonical: list[dict[str, Any]] = []
        for index, point in enumerate(curve):
            displacement = max(0.0, float(point.get("displacement_mm", 0.0)) - disp_offset)
            force = max(0.0, float(point.get("force_N", 0.0)) - force_offset)
            canonical.append(
                {
                    "source_row_index": index,
                    "time_s": point.get("time_s"),
                    "displacement_mm": round(displacement, 9),
                    "force_N": round(force, 9),
                    "stress_MPa": round(force / area, 9),
                    "strain": round(displacement / gauge, 9),
                    "segment": "post_contact" if force > max(2.0, 0.01 * max((p.get("force_N", 0.0) for p in curve), default=0.0)) else "pre_contact",
                }
            )
        return canonical

    @staticmethod
    def _write_canonical_csv(path: Path, canonical_curve: list[dict[str, Any]]) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = ["source_row_index", "time_s", "displacement_mm", "force_N", "stress_MPa", "strain", "segment"]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in canonical_curve:
                writer.writerow({key: row.get(key, "") for key in fields})
        return str(path)

    @staticmethod
    def _preprocessing_report(curve: list[dict[str, float]], canonical_curve: list[dict[str, Any]]) -> dict[str, Any]:
        peak = max((float(point.get("force_N", 0.0)) for point in curve), default=0.0)
        contact_threshold = max(2.0, 0.01 * peak)
        contact_index = None
        for row in canonical_curve:
            if float(row.get("force_N", 0.0) or 0.0) > contact_threshold:
                contact_index = int(row.get("source_row_index", 0))
                break
        return {
            "schema": "analysis_preprocessing.v1",
            "numeric_coercion": True,
            "unit_conversion_applied": True,
            "sorted_by_displacement": True,
            "force_zero_offset_N": float(curve[0].get("force_N", 0.0)) if curve else 0.0,
            "displacement_zero_offset_mm": float(curve[0].get("displacement_mm", 0.0)) if curve else 0.0,
            "smoothing": {"method": "none", "window": 0},
            "contact_detection": {
                "method": "first_force_above_max_2N_or_1pct_peak",
                "threshold_N": round(contact_threshold, 6),
                "contact_index": contact_index,
            },
            "input_rows": len(curve),
            "output_rows": len(canonical_curve),
            "dropped_rows": max(0, len(curve) - len(canonical_curve)),
        }

    @staticmethod
    def _quality_gate(signal_quality: dict[str, Any], metrics: dict[str, Any], source_meta: dict[str, Any], analysis_ok: bool) -> dict[str, Any]:
        column_mapping = source_meta.get("column_mapping") if isinstance(source_meta.get("column_mapping"), dict) else {}
        curve_quality = metrics.get("curve_quality") if isinstance(metrics.get("curve_quality"), dict) else {}
        checks = {
            "min_row_count": int(signal_quality.get("point_count") or 0) >= 2,
            "finite_numeric_values": bool(signal_quality.get("ok", False)),
            "monotonic_displacement": float(curve_quality.get("monotonic_displacement_ratio", 1.0) or 0.0) >= 0.95,
            "positive_force_detected": bool(signal_quality.get("force_nonzero", False)),
            "peak_not_at_boundary": "peak_at_curve_boundary" not in (curve_quality.get("warnings") or []),
            "unit_mapping_confident": float(column_mapping.get("unit_mapping_confidence", 0.9 if not column_mapping else 0.0) or 0.0) >= 0.70,
            "column_mapping_confident": float(column_mapping.get("column_mapping_confidence", 0.9 if not column_mapping else 0.0) or 0.0) >= 0.70,
            "equipment_handoff_verified": True,
        }
        warnings = list(curve_quality.get("warnings") or []) + list(column_mapping.get("warnings") or [])
        ok_for_metrics = bool(analysis_ok and signal_quality.get("ok", False) and checks["positive_force_detected"] and checks["min_row_count"])
        ok_for_bo = bool(ok_for_metrics and checks["unit_mapping_confident"] and checks["column_mapping_confident"] and checks["peak_not_at_boundary"])
        score = sum(1 for value in checks.values() if value) / max(len(checks), 1)
        failure_code = None if ok_for_metrics else str(signal_quality.get("failure_code") or "ANALYSIS_QUALITY_GATE_FAILED")
        return {
            "schema": "analysis_quality_gate.v1",
            "ok_for_metrics": ok_for_metrics,
            "ok_for_bo": ok_for_bo,
            "score": round(score, 4),
            "checks": checks,
            "warnings": sorted(set(str(item) for item in warnings if item)),
            "failure_code": failure_code,
        }

    def _comparison(self, state: OrchestratorState, objective_score: float, metrics: dict[str, Any]) -> dict[str, Any]:
        prior = [item for item in state.experiment_evaluations if isinstance(item, dict) and item.get("objective_score") is not None]
        if not prior:
            return {
                "schema": "analysis_comparison.v1",
                "mode": "first_loop",
                "previous_loop": None,
                "best_so_far": None,
                "nearest_neighbor": None,
                "summary": "No prior measured experiment available.",
            }
        previous = prior[-1]
        best = max(prior, key=lambda item: self._safe_float(item.get("objective_score"), float("-inf")))
        prev_score = self._safe_float(previous.get("objective_score"), 0.0)
        best_score = self._safe_float(best.get("objective_score"), 0.0)
        return {
            "schema": "analysis_comparison.v1",
            "mode": "has_prior",
            "previous_loop": {
                "experiment_id": previous.get("experiment_id", ""),
                "objective_score": prev_score,
                "delta_objective": round(objective_score - prev_score, 6),
                "delta_percent": round(((objective_score - prev_score) / max(abs(prev_score), 1e-9)) * 100.0, 3),
            },
            "best_so_far": {
                "experiment_id": best.get("experiment_id", ""),
                "objective_score": best_score,
                "is_new_best": objective_score > best_score,
                "margin": round(objective_score - best_score, 6),
            },
            "nearest_neighbor": None,
            "summary": "Compared against previous and best measured evaluations.",
        }

    def _fem_utm_comparison(self, metrics: dict[str, Any], fem_result: dict[str, Any] | None, cae_result: dict[str, Any] | None) -> dict[str, Any]:
        simulation = fem_result if isinstance(fem_result, dict) and fem_result.get("ok") else cae_result
        sim_metrics = {}
        if isinstance(simulation, dict):
            sim_metrics = simulation.get("fem_metrics") if isinstance(simulation.get("fem_metrics"), dict) else simulation.get("cae_metrics") if isinstance(simulation.get("cae_metrics"), dict) else simulation.get("metrics", {})
        if not isinstance(sim_metrics, dict) or not sim_metrics:
            return {"schema": "fem_utm_comparison.v1", "available": False, "reason": "no_simulation_metrics"}
        utm_peak = self._safe_float(metrics.get("peak_force_N"), 0.0)
        utm_stiffness = self._safe_float(metrics.get("initial_stiffness_N_per_mm"), 0.0)
        pred_peak = self._safe_float(sim_metrics.get("predicted_peak_force_N") or sim_metrics.get("load_max_N"), 0.0)
        pred_stiffness = self._safe_float(sim_metrics.get("predicted_initial_stiffness_N_per_mm") or sim_metrics.get("apparent_stiffness_N_per_mm"), 0.0)
        peak_error = abs(pred_peak - utm_peak) / max(abs(utm_peak), 1e-9) * 100.0 if utm_peak > 0 and pred_peak > 0 else None
        stiffness_error = abs(pred_stiffness - utm_stiffness) / max(abs(utm_stiffness), 1e-9) * 100.0 if utm_stiffness > 0 and pred_stiffness > 0 else None
        numeric_errors = [item for item in (peak_error, stiffness_error) if item is not None]
        agreement = 1.0 / (1.0 + (sum(numeric_errors) / max(len(numeric_errors), 1)) / 100.0) if numeric_errors else 0.0
        tags = []
        if peak_error is not None and peak_error > 40.0:
            tags.append("peak_force_discrepancy_high")
        if stiffness_error is not None and stiffness_error > 40.0:
            tags.append("stiffness_discrepancy_high")
        if not tags:
            tags.append("acceptable" if agreement >= 0.65 else "needs_more_samples_for_calibration")
        return {
            "schema": "fem_utm_comparison.v1",
            "available": True,
            "simulation_tool": simulation.get("tool") if isinstance(simulation, dict) else "",
            "peak_force_error_pct": round(peak_error, 6) if peak_error is not None else None,
            "stiffness_error_pct": round(stiffness_error, 6) if stiffness_error is not None else None,
            "agreement_score": round(agreement, 6),
            "discrepancy_tags": tags,
        }

    def _multifidelity_comparison(
        self,
        metrics: dict[str, Any],
        fem_utm_comparison: dict[str, Any],
        cae_result: dict[str, Any] | None,
        fem_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        simulation = fem_result if isinstance(fem_result, dict) and fem_result.get("ok") else cae_result
        sim_metrics = {}
        if isinstance(simulation, dict):
            sim_metrics = simulation.get("fem_metrics") if isinstance(simulation.get("fem_metrics"), dict) else simulation.get("cae_metrics") if isinstance(simulation.get("cae_metrics"), dict) else simulation.get("metrics", {})
        return {
            "schema": "multifidelity_comparison.v1",
            "available": bool(fem_utm_comparison.get("available")),
            "curve": {
                "utm_peak_force_N": metrics.get("peak_force_N"),
                "fea_peak_force_N": sim_metrics.get("predicted_peak_force_N") or sim_metrics.get("load_max_N"),
                "peak_force_error_pct": fem_utm_comparison.get("peak_force_error_pct"),
                "utm_stiffness_N_per_mm": metrics.get("initial_stiffness_N_per_mm"),
                "fea_stiffness_N_per_mm": sim_metrics.get("predicted_initial_stiffness_N_per_mm") or sim_metrics.get("apparent_stiffness_N_per_mm"),
                "stiffness_error_pct": fem_utm_comparison.get("stiffness_error_pct"),
                "agreement_score": fem_utm_comparison.get("agreement_score", 0.0),
                "tags": fem_utm_comparison.get("discrepancy_tags", []),
            },
            "field": {
                "available": bool(isinstance(simulation, dict) and simulation.get("ok")),
                "max_von_mises_MPa": sim_metrics.get("max_von_mises_MPa"),
                "max_displacement_mm": sim_metrics.get("max_displacement_mm"),
                "structural_score": sim_metrics.get("structural_score"),
            },
            "hotspot": {"available": False, "reason": "hotspot_extraction_not_enabled"},
            "pinn": {"status": "unavailable", "reason": "no_active_pinn_model"},
            "sources": {
                "utm": "equipment_handoff",
                "fea": (simulation or {}).get("tool") if isinstance(simulation, dict) else "unavailable",
                "pinn": "unavailable",
            },
        }

    def _fidelity_records(
        self,
        *,
        state: OrchestratorState,
        metrics: dict[str, Any],
        source_meta: dict[str, Any],
        cae_result: dict[str, Any] | None,
        fem_result: dict[str, Any] | None,
        analysis_artifacts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifacts = analysis_artifacts if isinstance(analysis_artifacts, dict) else {}
        simulation = fem_result if isinstance(fem_result, dict) and fem_result.get("ok") else cae_result
        sim_metrics = {}
        if isinstance(simulation, dict):
            sim_metrics = simulation.get("fem_metrics") if isinstance(simulation.get("fem_metrics"), dict) else simulation.get("cae_metrics") if isinstance(simulation.get("cae_metrics"), dict) else simulation.get("metrics", {})
        return {
            "utm_high": {
                "schema": "utm_record.v1",
                "status": "available" if metrics else "unavailable",
                "source": source_meta.get("source") or "utm",
                "parser_id": source_meta.get("parser_id"),
                "path": source_meta.get("path"),
                "metrics_artifact": artifacts.get("metrics"),
                "canonical_curve_artifact": artifacts.get("canonical_curve"),
                "peak_force_N": metrics.get("peak_force_N"),
                "objective_source": True,
                "run_id": state.run_id,
                "experiment_id": state.experiment_id,
            },
            "fea_mid": {
                "schema": "fea_result.v1",
                "status": "available" if isinstance(simulation, dict) and simulation.get("ok") else "unavailable",
                "tool": (simulation or {}).get("tool") if isinstance(simulation, dict) else None,
                "artifact": artifacts.get("fem_result"),
                "metrics": sim_metrics,
                "objective_source": False,
            },
            "pinn_low_or_surrogate": {
                "schema": "pinn_prediction.v1",
                "status": "unavailable",
                "reason": "no_active_pinn_model",
                "objective_source": False,
            },
        }

    def _trust_score(
        self,
        *,
        quality_gate: dict[str, Any],
        multifidelity_comparison: dict[str, Any],
        uncertainty: float,
        source_meta: dict[str, Any],
        cae_result: dict[str, Any] | None,
        analysis_ok: bool,
    ) -> dict[str, Any]:
        curve = multifidelity_comparison.get("curve") if isinstance(multifidelity_comparison.get("curve"), dict) else {}
        raw_agreement = self._safe_float(curve.get("agreement_score"), 0.0)
        q_data = self._safe_float(quality_gate.get("score"), 0.0)
        # FEA/CAE is an advisory mid-fidelity source here; UTM remains the
        # high-fidelity objective source, so one uncalibrated mismatch should
        # reduce trust but not automatically block BO updates.
        q_agreement = max(raw_agreement, 0.65) if multifidelity_comparison.get("available") and q_data >= 0.75 else raw_agreement
        if isinstance(cae_result, dict) and cae_result.get("ok"):
            cae_metrics = cae_result.get("cae_metrics") if isinstance(cae_result.get("cae_metrics"), dict) else cae_result.get("metrics", {})
            q_physics = self._safe_float(cae_metrics.get("structural_score"), 0.72)
        else:
            q_physics = 0.35
        q_uq = max(0.0, min(1.0, 1.0 - self._safe_float(uncertainty, 1.0)))
        fingerprint = source_meta.get("fingerprint") if isinstance(source_meta.get("fingerprint"), dict) else {}
        column_mapping = source_meta.get("column_mapping") if isinstance(source_meta.get("column_mapping"), dict) else {}
        q_provenance = 0.55
        if source_meta.get("path") or fingerprint.get("sha256"):
            q_provenance += 0.20
        q_provenance += 0.15 * self._safe_float(column_mapping.get("column_mapping_confidence"), 0.8 if not column_mapping else 0.0)
        q_provenance = max(0.0, min(1.0, q_provenance))
        components = {
            "q_data": round(max(0.0, min(q_data, 1.0)), 4),
            "q_agreement": round(max(0.0, min(q_agreement, 1.0)), 4),
            "q_physics": round(max(0.0, min(q_physics, 1.0)), 4),
            "q_uq": round(q_uq, 4),
            "q_provenance": round(q_provenance, 4),
        }
        weights = {"q_data": 0.30, "q_agreement": 0.25, "q_physics": 0.15, "q_uq": 0.15, "q_provenance": 0.15}
        score = sum(components[key] * weight for key, weight in weights.items())
        reasons: list[str] = []
        if raw_agreement < 0.45 and multifidelity_comparison.get("available"):
            reasons.append("fea_requires_calibration")
        if not analysis_ok:
            reasons.append("analysis_not_ok")
            gate = "block"
        elif components["q_data"] < 0.55:
            reasons.append("data_quality_low")
            gate = "block"
        elif score < 0.62:
            reasons.append("calibration_recommended_before_physical_update")
            gate = "calibrate_only"
        elif score >= 0.85 and components["q_agreement"] >= 0.75 and components["q_data"] >= 0.75:
            gate = "allow_physical"
        else:
            gate = "allow_bo"
        return {
            "schema": "trust_score.v1",
            "score": round(max(0.0, min(score, 1.0)), 4),
            "gate": gate,
            "components": components,
            "weights": weights,
            "reasons": reasons,
        }

    def _write_analysis_artifacts(
        self,
        *,
        state: OrchestratorState,
        curve: list[dict[str, float]],
        source_meta: dict[str, Any],
        metrics: dict[str, Any],
        analysis: dict[str, Any],
        handoff: dict[str, Any],
        fem_result: dict[str, Any] | None,
        cae_result: dict[str, Any] | None,
    ) -> dict[str, str]:
        base = self._analysis_artifact_dir(state)
        canonical = self._canonical_curve(curve, analysis.get("specimen_geometry", {})) if curve else []
        preprocessing = self._preprocessing_report(curve, canonical) if curve else {"schema": "analysis_preprocessing.v1", "input_rows": 0, "output_rows": 0}
        paths: dict[str, str] = {}
        paths["raw_input_sidecar"] = self._write_json(base / "raw_input_sidecar.json", {"schema": "raw_input_sidecar.v1", "source": source_meta, "fingerprint": source_meta.get("fingerprint", {})})
        paths["parse_report"] = self._write_json(base / "parse_report.json", {"schema": "analysis_parse_report.v1", "source": source_meta, "parser_id": source_meta.get("parser_id"), "column_mapping": source_meta.get("column_mapping", {})})
        if canonical:
            paths["canonical_curve"] = self._write_canonical_csv(base / "canonical_curve.csv", canonical)
        paths["preprocessing_report"] = self._write_json(base / "preprocessing_report.json", preprocessing)
        paths["quality_report"] = self._write_json(base / "quality_report.json", analysis.get("quality_gate", analysis.get("data_quality_gate", {})))
        paths["metrics"] = self._write_json(base / "metrics.json", metrics)
        if isinstance(fem_result, dict):
            paths["fem_result"] = self._write_json(base / "fem_result.json", fem_result)
            if isinstance(fem_result.get("request"), dict):
                paths["fem_request"] = self._write_json(base / "fem_request.json", fem_result["request"])
            if fem_result.get("artifacts") and isinstance(fem_result.get("artifacts"), dict) and fem_result["artifacts"].get("fem_cache_manifest"):
                paths["fem_cache_manifest"] = str(fem_result["artifacts"]["fem_cache_manifest"])
        elif isinstance(cae_result, dict):
            paths["fem_result"] = self._write_json(base / "fem_result.json", {"schema": "fem_result.v1", "source": "cae.run_static_analysis", "result": cae_result})
            if isinstance(cae_result.get("request"), dict):
                paths["fem_request"] = self._write_json(base / "fem_request.json", cae_result["request"])
        if analysis.get("fem_agentic_loop"):
            paths["fem_agentic_loop"] = self._write_json(base / "fem_agentic_loop.json", analysis["fem_agentic_loop"])
        if analysis.get("fem_utm_comparison"):
            paths["fem_utm_comparison"] = self._write_json(base / "fem_utm_comparison.json", analysis["fem_utm_comparison"])
        if analysis.get("multifidelity_comparison"):
            paths["multifidelity_comparison"] = self._write_json(base / "multifidelity_comparison.json", analysis["multifidelity_comparison"])
        if analysis.get("trust_score"):
            paths["trust_score"] = self._write_json(base / "trust_score.json", analysis["trust_score"])
        if analysis.get("comparison"):
            paths["comparison"] = self._write_json(base / "comparison.json", analysis["comparison"])
        paths["analysis_report"] = self._write_json(base / "analysis_report.json", analysis)
        if handoff.get("experiment_evaluation"):
            paths["experiment_evaluation"] = self._write_json(base / "experiment_evaluation.json", handoff["experiment_evaluation"])
        if handoff.get("bo_handoff"):
            paths["bo_handoff"] = self._write_json(base / "bo_handoff.json", handoff["bo_handoff"])
        trace_path = base / "analysis_trace.jsonl"
        events = [
            {"event": "analysis.file_discovered", "source": source_meta, "created_at": datetime.now(timezone.utc).isoformat()},
            {"event": "analysis.metrics_computed", "metrics": metrics, "created_at": datetime.now(timezone.utc).isoformat()},
            {"event": "analysis.cae_simulation_completed", "status": analysis.get("fem_agentic_loop", {}).get("status"), "selected_iteration": analysis.get("fem_agentic_loop", {}).get("selected_iteration"), "created_at": datetime.now(timezone.utc).isoformat()},
            {"event": "analysis.bo_handoff_created", "ok_for_bo": handoff.get("bo_handoff", {}).get("ok_for_bo"), "created_at": datetime.now(timezone.utc).isoformat()},
        ]
        trace_path.write_text("".join(json.dumps(item, ensure_ascii=True, default=str) + "\n" for item in events), encoding="utf-8")
        paths["analysis_trace"] = str(trace_path)
        return paths

    @staticmethod
    def _artifact_refs(equipment_result: dict[str, Any], source_meta: dict[str, Any], cae_result: dict[str, Any] | None) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []

        def add_ref(kind: str, *, path: Any = "", artifact_id: Any = "", source: str = "") -> None:
            path_text = str(path or "").strip()
            artifact_text = str(artifact_id or "").strip()
            if not path_text and not artifact_text:
                return
            item: dict[str, Any] = {"kind": kind or "artifact"}
            if path_text:
                item["path"] = path_text
            if artifact_text:
                item["artifact_id"] = artifact_text
            if source:
                item["source"] = source
            refs.append(item)

        if source_meta.get("path"):
            add_ref("utm_csv", path=source_meta["path"], source=str(source_meta.get("source") or "utm"))

        def default_kind_for_key(key: str) -> str:
            if "screen" in key:
                return "screen_evidence"
            if "data" in key or "csv" in key:
                return "utm_csv"
            if "failure" in key:
                return "failure_evidence"
            return "equipment_artifact"

        def collect_item(item: Any, *, default_kind: str, source: str, depth: int) -> None:
            if depth > 5:
                return
            if isinstance(item, dict):
                kind = str(item.get("kind") or item.get("type") or default_kind)
                path_value = (
                    item.get("local_path")
                    or item.get("linux_path")
                    or item.get("path")
                    or item.get("file_path")
                    or item.get("filename")
                    or item.get("windows_path")
                    or item.get("href")
                    or item.get("file")
                )
                artifact_value = item.get("artifact_id") or item.get("id") or item.get("ref") or item.get("artifact")
                add_ref(kind, path=path_value, artifact_id=artifact_value, source=source)
                for nested_key in (
                    "artifact_refs",
                    "evidence_refs",
                    "screen_evidence_refs",
                    "data_evidence_refs",
                    "raw_artifact_refs",
                    "output_artifacts",
                    "artifacts",
                ):
                    nested = item.get(nested_key)
                    if isinstance(nested, list):
                        for nested_item in nested:
                            collect_item(nested_item, default_kind=default_kind_for_key(nested_key), source=f"{source}.{nested_key}", depth=depth + 1)
                for nested_key in ("equipment_report", "utm_data_ready", "equipment_handoff", "data_acquisition", "live_evidence_audit", "manifest", "source_packets"):
                    nested = item.get(nested_key)
                    if isinstance(nested, dict):
                        collect_item(nested, default_kind=default_kind, source=f"{source}.{nested_key}", depth=depth + 1)
            elif isinstance(item, (str, Path)):
                add_ref(default_kind, path=item, source=source)

        collect_item(equipment_result, default_kind="equipment_artifact", source="equipment_result", depth=0)
        if isinstance(cae_result, dict):
            for key in ("contour_svg", "report_path", "artifact_path"):
                value = cae_result.get(key)
                if value:
                    add_ref(f"cae_{key}", path=value, source="cae.run_static_analysis")
        seen: set[tuple[str, str, str, str]] = set()
        unique: list[dict[str, Any]] = []
        for item in refs:
            token = (
                str(item.get("kind") or ""),
                str(item.get("path") or ""),
                str(item.get("artifact_id") or ""),
                str(item.get("source") or ""),
            )
            if token in seen:
                continue
            seen.add(token)
            unique.append(item)
        return unique

    @staticmethod
    def _failure_tags(source_meta: dict[str, Any], metrics: dict[str, Any], equipment_result: dict[str, Any], cae_result: dict[str, Any] | None) -> list[str]:
        tags: list[str] = []
        if source_meta.get("error"):
            tags.append("utm_source_read_error")
        if source_meta.get("failure_code"):
            tags.append(str(source_meta["failure_code"]))
        if str(source_meta.get("source") or "").startswith("synthetic"):
            tags.append("synthetic_utm_curve")
        quality = metrics.get("curve_quality") if isinstance(metrics.get("curve_quality"), dict) else {}
        tags.extend(str(item) for item in quality.get("warnings", []) if item)
        for quality_source in (source_meta.get("signal_quality_probe"), metrics.get("data_quality")):
            if isinstance(quality_source, dict) and quality_source.get("failure_code"):
                tags.append(str(quality_source["failure_code"]))
        failure_code = equipment_result.get("failure_code")
        if failure_code:
            tags.append(str(failure_code))
        for key in ("equipment_handoff", "utm_data_ready", "equipment_report"):
            packet = equipment_result.get(key) if isinstance(equipment_result.get(key), dict) else {}
            if packet.get("failure_code"):
                tags.append(str(packet["failure_code"]))
            decision = packet.get("decision") if isinstance(packet.get("decision"), dict) else {}
            if decision.get("failure_code"):
                tags.append(str(decision["failure_code"]))
        if isinstance(cae_result, dict) and cae_result.get("failure_code"):
            tags.append(str(cae_result["failure_code"]))
        return sorted(set(str(item) for item in tags if str(item or "").strip()))

    def _handoff_payloads(
        self,
        *,
        state: OrchestratorState,
        analysis: dict[str, Any],
        metrics: dict[str, Any],
        source_meta: dict[str, Any],
        equipment_result: dict[str, Any],
        cae_result: dict[str, Any] | None,
        fem_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact_refs = self._artifact_refs(equipment_result, source_meta, cae_result)
        analysis_artifacts = analysis.get("analysis_artifacts") if isinstance(analysis.get("analysis_artifacts"), dict) else {}
        for kind, path in analysis_artifacts.items():
            if path:
                artifact_refs.append({"kind": str(kind), "path": str(path), "source": "analysis_agent"})
        failure_tags = self._failure_tags(source_meta, metrics, equipment_result, cae_result)
        extra_failure_tags: list[str] = []

        def add_failure_tag(value: Any) -> None:
            text = str(value or "").strip()
            if text:
                extra_failure_tags.append(text)

        add_failure_tag(analysis.get("failure_code"))
        data_quality = analysis.get("data_quality") if isinstance(analysis.get("data_quality"), dict) else {}
        add_failure_tag(data_quality.get("failure_code"))
        handoff_gate = analysis.get("equipment_handoff_gate") if isinstance(analysis.get("equipment_handoff_gate"), dict) else {}
        add_failure_tag(handoff_gate.get("failure_code"))
        blockers = handoff_gate.get("blockers") if isinstance(handoff_gate.get("blockers"), list) else []
        for blocker in blockers:
            add_failure_tag(blocker)
        failure_tags = sorted(set(failure_tags + extra_failure_tags))
        parameters = {
            key: state.current_experiment_spec.get(key)
            for key in ("geometry_type", "relative_density", "wall_thickness_mm", "cell_size_mm", "tpms_thickness")
            if isinstance(state.current_experiment_spec, dict) and key in state.current_experiment_spec
        }
        quality_gate = analysis.get("quality_gate") if isinstance(analysis.get("quality_gate"), dict) else analysis.get("data_quality_gate", {})
        fem_metrics = analysis.get("fem_metrics") if isinstance(analysis.get("fem_metrics"), dict) else {}
        simulation_metrics = {
            "cae": analysis.get("cae_metrics", {}),
            "fem": fem_metrics,
        }
        fem_comparison = analysis.get("fem_utm_comparison") if isinstance(analysis.get("fem_utm_comparison"), dict) else {}
        multifidelity_comparison = analysis.get("multifidelity_comparison") if isinstance(analysis.get("multifidelity_comparison"), dict) else self._multifidelity_comparison(metrics, fem_comparison, cae_result, fem_result)
        fidelity_records = analysis.get("fidelity_records") if isinstance(analysis.get("fidelity_records"), dict) else self._fidelity_records(
            state=state,
            metrics=metrics,
            source_meta=source_meta,
            cae_result=cae_result,
            fem_result=fem_result,
            analysis_artifacts=analysis_artifacts,
        )
        trust_score = analysis.get("trust_score") if isinstance(analysis.get("trust_score"), dict) else self._trust_score(
            quality_gate=quality_gate,
            multifidelity_comparison=multifidelity_comparison,
            uncertainty=self._safe_float(analysis.get("uncertainty"), 1.0),
            source_meta=source_meta,
            cae_result=cae_result,
            analysis_ok=bool(analysis.get("ok")),
        )
        analysis["multifidelity_comparison"] = multifidelity_comparison
        analysis["fidelity_records"] = fidelity_records
        analysis["trust_score"] = trust_score
        trust_gate = str(trust_score.get("gate") or "").strip()
        bo_ready = bool(analysis.get("ok") and (quality_gate.get("ok_for_bo", True) is True) and trust_gate in {"allow_bo", "allow_physical"})
        bo_observation = {
            "schema": "bo_observation.v1",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "producer_agent": self.name,
            "consumer_agent": "bo_agent",
            "status": "ready" if bo_ready else "blocked",
            "objective_score": analysis.get("objective_score", 0.0),
            "objective_evaluation": analysis.get("objective_evaluation", {}),
            "uncertainty": analysis.get("uncertainty", 1.0),
            "observed_metrics": metrics,
            "simulation_metrics": simulation_metrics,
            "simulation_residual": fem_comparison,
            "multifidelity_comparison": multifidelity_comparison,
            "trust_score": trust_score,
            "trust_gate": trust_gate,
            "data_quality": quality_gate or metrics.get("curve_quality", {}),
            "parameters": parameters,
            "artifact_refs": artifact_refs,
            "failure_tags": failure_tags,
            "source": source_meta,
        }
        objective = state.current_experiment_objective if isinstance(state.current_experiment_objective, dict) else {}
        experiment_evaluation = {
            "schema": "experiment_evaluation.v1",
            "ok": bool(analysis.get("ok")),
            "tool": "analysis.agent",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "session_id": state.active_session_id or state.run_id,
            "evaluation_id": f"eval-analysis-{state.experiment_id}",
            "objective": {
                "objective_id": objective.get("objective_id") or "bo-specimen-objective",
                "name": objective.get("name") or "Compression performance",
                "metric_name": objective.get("metric_name") or "objective_score",
                "direction": objective.get("direction") or "maximize",
                "constraints": objective.get("constraints") if isinstance(objective.get("constraints"), dict) else {},
            },
            "candidate_id": parameters.get("candidate_id") or state.current_experiment_spec.get("specimen_id", state.experiment_id),
            "mode": state.mode.value,
            "bridge": "analysis",
            "status": "measured_analysis_complete" if analysis.get("ok") else "analysis_blocked",
            "objective_score": analysis.get("objective_score", 0.0),
            "uncertainty": analysis.get("uncertainty", 1.0),
            "metrics": {**parameters, **metrics, "quality_score": quality_gate.get("score"), "fem_utm_agreement_score": fem_comparison.get("agreement_score")},
            "fidelity_records": {
                "utm_high": "metrics",
                "fem_low": (fem_result or {}).get("artifacts", {}).get("fem_result") if isinstance(fem_result, dict) else None,
                "agreement": analysis_artifacts.get("fem_utm_comparison"),
            },
            "multifidelity_comparison": multifidelity_comparison,
            "trust_score": trust_score,
            "artifacts": analysis_artifacts,
            "artifact_refs": artifact_refs,
            "bridge_result": {
                "analysis_source": source_meta.get("source"),
                "parser_id": source_meta.get("parser_id"),
                "quality_gate": "passed" if quality_gate.get("ok_for_metrics") else "blocked",
            },
            "failure_tags": failure_tags,
            "source": "analysis_agent",
            "failure_code": analysis.get("failure_code"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        bo_handoff = {
            "schema_version": "analysis_bo_handoff_v2",
            "ok_for_bo": bo_ready,
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "candidate_id": experiment_evaluation["candidate_id"],
            "parameters": parameters,
            "objective": {
                "metric_name": "objective_score",
                "direction": experiment_evaluation["objective"].get("direction", "maximize"),
                "score": analysis.get("objective_score", 0.0),
                "uncertainty": analysis.get("uncertainty", 1.0),
            },
            "objective_evaluation": analysis.get("objective_evaluation", {}),
            "metrics": metrics,
            "fidelity": {
                "mode": "single_high_fidelity_with_low_fidelity_context",
                "utm_high": {"objective_source": True, "artifact": analysis_artifacts.get("metrics")},
                "fem_low": {
                    "used_for_objective": False,
                    "artifact": analysis_artifacts.get("fem_result") or ((fem_result or {}).get("artifacts", {}).get("fem_result") if isinstance(fem_result, dict) else None),
                    "cache_status": (fem_result or {}).get("cache_status") if isinstance(fem_result, dict) else None,
                },
            },
            "fidelity_records": fidelity_records,
            "multifidelity_comparison": multifidelity_comparison,
            "trust_score": trust_score,
            "trust_gate": trust_gate,
            "quality": quality_gate,
            "comparison": analysis.get("comparison", {}),
            "artifacts": analysis_artifacts,
            "failure_tags": failure_tags,
        }
        knowledge_payload = {
            "schema": "analysis_knowledge_payload.v1",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "summary": analysis.get("summary", ""),
            "raw_artifact_refs": artifact_refs,
            "metrics": metrics,
            "objective_evaluation": analysis.get("objective_evaluation", {}),
            "parameters": parameters,
            "quality": quality_gate,
            "artifact_refs": analysis_artifacts,
            "failure_tags": failure_tags,
            "source": source_meta,
        }
        return {
            "bo_observation": bo_observation,
            "bo_handoff": bo_handoff,
            "experiment_evaluation": experiment_evaluation,
            "knowledge_payload": knowledge_payload,
            "artifact_refs": artifact_refs,
            "failure_tags": failure_tags,
        }

    def _blocked_result(
        self,
        *,
        state: OrchestratorState,
        summary: str,
        analysis: dict[str, Any],
        metrics: dict[str, Any],
        source_meta: dict[str, Any],
        equipment_result: dict[str, Any],
        cae_result: dict[str, Any] | None,
    ) -> AgentResult:
        handoff = self._handoff_payloads(
            state=state,
            analysis=analysis,
            metrics=metrics,
            source_meta=source_meta,
            equipment_result=equipment_result,
            cae_result=cae_result,
        )
        analysis["artifact_refs"] = handoff["artifact_refs"]
        analysis["failure_tags"] = handoff["failure_tags"]
        analysis["bo_observation"] = handoff["bo_observation"]
        analysis["knowledge_payload"] = handoff["knowledge_payload"]
        return AgentResult(
            success=False,
            summary=summary,
            data={
                "analysis": analysis,
                "bo_observation": handoff["bo_observation"],
                "bo_handoff": handoff["bo_handoff"],
                "experiment_evaluation": handoff["experiment_evaluation"],
                "knowledge_payload": handoff["knowledge_payload"],
                "metrics": metrics,
                "handoff_packet": handoff["bo_observation"],
            },
        )

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
        fem_result: dict[str, Any] | None = None
        fem_agentic_loop: dict[str, Any] = self._cae_simulation_loop(cae_result)
        cae_metrics = {}
        if isinstance(cae_result, dict):
            raw_cae_metrics = cae_result.get("cae_metrics") if isinstance(cae_result.get("cae_metrics"), dict) else cae_result.get("metrics")
            cae_metrics = dict(raw_cae_metrics) if isinstance(raw_cae_metrics, dict) else {}
        fem_metrics = {}
        equipment_result = self._equipment_result(state)
        curve, source_meta = self._curve_from_equipment(equipment_result)
        live_handoff_ok = True
        live_handoff_gate: dict[str, Any] = {"ok": True, "status": "not_required"}
        if state.mode == Mode.LIVE:
            live_handoff_ok, live_handoff_gate = self._live_equipment_handoff_gate(equipment_result)
        if not curve and state.mode != Mode.LIVE:
            curve, source_meta = self._synthetic_curve(state, geometry)
        if state.mode == Mode.LIVE and curve and not live_handoff_ok:
            signal_quality = self._curve_signal_quality(curve)
            source_meta["signal_quality_probe"] = signal_quality
            blocked_metrics = {"data_quality": signal_quality}
            analysis = {
                "ok": False,
                "failure_code": live_handoff_gate.get("failure_code") or "EQUIPMENT_HANDOFF_NOT_READY",
                "summary": "Live UTM data was present, but Equipment proof/handoff gates were not ready for Analysis.",
                "objective_score": 0.0,
                "uncertainty": 0.9,
                "source": source_meta,
                "specimen_geometry": geometry,
                "cae_result": cae_result or {},
                "cae_metrics": cae_metrics,
                "fem_result": fem_result or self._cae_as_fem_result(cae_result),
                "fem_metrics": fem_metrics,
                "equipment_handoff_gate": live_handoff_gate,
                "equipment_result": {
                    "tool": equipment_result.get("tool", ""),
                    "status": equipment_result.get("status", ""),
                    "failure_code": equipment_result.get("failure_code"),
                },
            }
            return self._blocked_result(
                state=state,
                summary="Analysis blocked: Equipment handoff not ready",
                analysis=analysis,
                metrics=blocked_metrics,
                source_meta=source_meta,
                equipment_result=equipment_result,
                cae_result=cae_result,
            )
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
                "fem_result": fem_result or self._cae_as_fem_result(cae_result),
                "fem_metrics": fem_metrics,
                "equipment_result": {
                    "tool": equipment_result.get("tool", ""),
                    "status": equipment_result.get("status", ""),
                    "failure_code": equipment_result.get("failure_code"),
                },
                "equipment_handoff_gate": live_handoff_gate,
            }
            return self._blocked_result(
                state=state,
                summary="Analysis blocked: UTM data required",
                analysis=analysis,
                metrics={},
                source_meta=source_meta,
                equipment_result=equipment_result,
                cae_result=cae_result,
            )

        signal_quality = source_meta.get("signal_quality_probe") if isinstance(source_meta.get("signal_quality_probe"), dict) else self._curve_signal_quality(curve)
        source_meta["signal_quality_probe"] = signal_quality
        if not signal_quality.get("ok", False):
            failure_code = str(signal_quality.get("failure_code") or "UTM_DATA_PARSE_FAILED")
            analysis = {
                "ok": False,
                "failure_code": failure_code,
                "summary": str(signal_quality.get("message") or "UTM curve failed signal-quality validation before Analysis."),
                "objective_score": 0.0,
                "uncertainty": 0.9,
                "source": source_meta,
                "specimen_geometry": geometry,
                "cae_result": cae_result or {},
                "cae_metrics": cae_metrics,
                "fem_result": fem_result or self._cae_as_fem_result(cae_result),
                "fem_metrics": fem_metrics,
                "data_quality": signal_quality,
                "equipment_handoff_gate": live_handoff_gate,
                "equipment_result": {
                    "tool": equipment_result.get("tool", ""),
                    "status": equipment_result.get("status", ""),
                    "failure_code": equipment_result.get("failure_code"),
                },
            }
            return self._blocked_result(
                state=state,
                summary=f"Analysis blocked: {failure_code}",
                analysis=analysis,
                metrics={"data_quality": signal_quality},
                source_meta=source_meta,
                equipment_result=equipment_result,
                cae_result=cae_result,
            )

        metrics = self._metrics(curve, geometry)
        fem_agentic_loop = self._cae_simulation_loop(cae_result)
        fem_result = None
        if isinstance(fem_result, dict):
            raw_fem_metrics = fem_result.get("fem_metrics") if isinstance(fem_result.get("fem_metrics"), dict) else fem_result.get("metrics")
            fem_metrics = dict(raw_fem_metrics) if isinstance(raw_fem_metrics, dict) else {}
        objective_simulation = cae_result if isinstance(cae_result, dict) and cae_result.get("ok") else fem_result
        uncertainty = self._uncertainty(source_meta, metrics, state, objective_simulation)
        quality_gate = self._quality_gate(signal_quality, metrics, source_meta, True)
        try:
            objective_evaluation = self._evaluate_compiled_objective(
                state=state,
                ctx=ctx,
                metrics=metrics,
                uncertainty=uncertainty,
                source_meta=source_meta,
                equipment_result=equipment_result,
                cae_result=cae_result,
            )
        except Exception as exc:
            failure_code = str(exc).split(":", 1)[0]
            if failure_code not in {"OBJECTIVE_BINDING_REQUIRED", "OBJECTIVE_BINDING_MISMATCH"}:
                failure_code = "OBJECTIVE_EVALUATION_FAILED"
            analysis = {
                "ok": False,
                "failure_code": failure_code,
                "summary": str(exc),
                "objective_score": None,
                "objective_evaluation": {},
                "uncertainty": uncertainty,
                "utm_metrics": metrics,
                "source": source_meta,
                "specimen_geometry": geometry,
                "quality_gate": quality_gate,
                "cae_result": cae_result or {},
                "cae_metrics": cae_metrics,
                "fem_result": fem_result or self._cae_as_fem_result(cae_result),
                "fem_metrics": fem_metrics,
                "equipment_handoff_gate": live_handoff_gate,
            }
            return self._blocked_result(
                state=state,
                summary=f"Analysis blocked: {failure_code}",
                analysis=analysis,
                metrics=metrics,
                source_meta=source_meta,
                equipment_result=equipment_result,
                cae_result=cae_result,
            )
        objective = (
            self._safe_float(objective_evaluation.get("score"), 0.0)
            if isinstance(objective_evaluation, dict)
            else self._objective_score(metrics, state, objective_simulation)
        )
        comparison = self._comparison(state, objective, metrics)
        fem_utm_comparison = self._fem_utm_comparison(metrics, fem_result, cae_result)
        closed_loop_sources = [source_meta.get("source", "utm")]
        closed_loop_sources.append("cae.run_static_analysis" if isinstance(cae_result, dict) and cae_result.get("ok") else "cae.unavailable")
        analysis = {
            "ok": True,
            "source": source_meta,
            "objective_score": objective,
            "objective_evaluation": objective_evaluation or {},
            "uncertainty": uncertainty,
            "utm_metrics": metrics,
            "utm_curve": self._curve_preview(curve),
            "data_quality_gate": signal_quality,
            "quality_gate": quality_gate,
            "comparison": comparison,
            "fem_utm_comparison": fem_utm_comparison,
            "cae_result": cae_result or {},
            "cae_metrics": cae_metrics,
            "fem_result": fem_result or self._cae_as_fem_result(cae_result),
            "fem_metrics": fem_metrics,
            "fem_agentic_loop": fem_agentic_loop,
            "closed_loop_sources": closed_loop_sources,
            "specimen_geometry": geometry,
            "equipment_result": {
                "tool": equipment_result.get("tool", ""),
                "status": equipment_result.get("status", ""),
                "program_id": equipment_result.get("program_id", ""),
                "sequence_id": equipment_result.get("sequence_id", ""),
                "result_file": equipment_result.get("result_file", ""),
            },
            "equipment_handoff_gate": live_handoff_gate,
            "recommendation": "ready_for_knowledge_guardian"
            if uncertainty <= 0.35 and quality_gate.get("ok_for_bo")
            else "review_utm_curve_quality_before_model_update",
        }
        analysis["summary"] = await self._summary(state, ctx, analysis)
        handoff = self._handoff_payloads(
            state=state,
            analysis=analysis,
            metrics=metrics,
            source_meta=source_meta,
            equipment_result=equipment_result,
            cae_result=cae_result,
            fem_result=fem_result,
        )
        analysis["analysis_artifacts"] = self._write_analysis_artifacts(
            state=state,
            curve=curve,
            source_meta=source_meta,
            metrics=metrics,
            analysis=analysis,
            handoff=handoff,
            fem_result=fem_result,
            cae_result=cae_result,
        )
        handoff = self._handoff_payloads(
            state=state,
            analysis=analysis,
            metrics=metrics,
            source_meta=source_meta,
            equipment_result=equipment_result,
            cae_result=cae_result,
            fem_result=fem_result,
        )
        analysis["artifact_refs"] = handoff["artifact_refs"]
        analysis["failure_tags"] = handoff["failure_tags"]
        analysis["bo_observation"] = handoff["bo_observation"]
        analysis["bo_handoff"] = handoff["bo_handoff"]
        analysis["knowledge_payload"] = handoff["knowledge_payload"]
        # Rewrite final handoff/report files after analysis_artifacts has been attached.
        final_artifacts = analysis.get("analysis_artifacts") if isinstance(analysis.get("analysis_artifacts"), dict) else {}
        if final_artifacts.get("bo_handoff"):
            self._write_json(Path(str(final_artifacts["bo_handoff"])), handoff["bo_handoff"])
        if final_artifacts.get("experiment_evaluation"):
            self._write_json(Path(str(final_artifacts["experiment_evaluation"])), handoff["experiment_evaluation"])
        if final_artifacts.get("multifidelity_comparison"):
            self._write_json(Path(str(final_artifacts["multifidelity_comparison"])), analysis["multifidelity_comparison"])
        if final_artifacts.get("trust_score"):
            self._write_json(Path(str(final_artifacts["trust_score"])), analysis["trust_score"])
        if final_artifacts.get("analysis_report"):
            self._write_json(Path(str(final_artifacts["analysis_report"])), analysis)
        return AgentResult(
            success=True,
            summary="UTM analysis complete",
            data={
                "analysis": analysis,
                "bo_observation": handoff["bo_observation"],
                "bo_handoff": handoff["bo_handoff"],
                "experiment_evaluation": handoff["experiment_evaluation"],
                "knowledge_payload": handoff["knowledge_payload"],
                "metrics": metrics,
                "handoff_packet": handoff["bo_observation"],
            },
        )
