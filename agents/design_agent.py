"""
File purpose:
- Generate concrete metamaterial specimen experiment specs for the existing runtime.

Key classes/functions:
- DesignAgent

Inputs/outputs:
- Input: orchestrator state, prior experiment memory, failure memory, optional LLM note
- Output: AgentResult.data["experiment_spec"] with specimen-design parameters

Dependencies:
- agents.base_agent.BaseAgent
- orchestrator.state.OrchestratorState

Modification guide:
- Safe places to edit: scoring weights, design-space defaults, constraint defaults
- Risky places to edit: top-level AgentResult keys consumed by RunLoop/downstream agents
- Related files: docs/agents/specimen_design_existing_runtime_guideline.txt, agents/specimen_agent.py
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState


class DesignAgent(BaseAgent):
    """Creates one validated specimen-design candidate for the current run loop."""

    name = "design_agent"
    TEST_DEFAULT_GEOMETRY = "gyroid"
    LEGACY_ALIAS_GEOMETRY = "gyroid"

    SUPPORTED_GEOMETRIES = (
        "gyroid",
        "lattice_bcc",
        "lattice_fcc",
        "lattice_octet",
        "honeycomb",
        "auxetic_reentrant",
        "random_voronoi",
    )

    DEFAULT_CONSTRAINTS: dict[str, Any] = {
        "printer_model": "Prusa MK4S",
        "material": "PLA",
        "max_specimen_size_mm": [30.0, 30.0, 30.0],
        "utm_fixture_limit_mm": [40.0, 40.0, 60.0],
        "max_print_time_min": 120.0,
        "max_mass_g": 50.0,
        "nozzle_diameter_mm": 0.4,
        "layer_height_mm": 0.2,
        "bed_temperature_c": 60.0,
        "first_layer_bed_temperature_c": 60.0,
        "min_wall_thickness_mm": 0.8,
        "minimum_feature_size_mm": 0.8,
        "require_flat_compression_faces": False,
        "fdm_min_wall_thickness_mm": 1.2,
        "fdm_max_bridge_distance_mm": 10.0,
        "fdm_max_unsupported_overhang_deg": 45.0,
        "fdm_max_gyroid_wall_cell_ratio": 0.28,
        "cell_size_mm": 5.0,
        "wall_thickness_mm": 1.2,
        "relative_density": 0.32,
        "anisotropy_ratio": 1.0,
        "orientation_deg": 0.0,
        "defect_ratio": 0.0,
        "skin_thickness_mm": 0.8,
        "top_cap_enabled": False,
        "bottom_cap_enabled": True,
        "top_bottom_cap": True,
        "skirt_enabled": False,
        "tpms_thickness": 0.0,
        "tpms_resolution": 72,
        "preferred_geometry_type": "",
    }

    DEFAULT_DESIGN_SPACE: dict[str, Any] = {
        "geometry_types": list(SUPPORTED_GEOMETRIES),
        "specimen_size_mm": [[20.0, 20.0, 20.0], [30.0, 30.0, 30.0]],
        "cell_size_mm": [3.0, 10.0],
        "wall_thickness_mm": [1.2, 3.0],
        "relative_density": [0.10, 0.60],
        "porosity": [0.40, 0.90],
        "anisotropy_ratio": [0.5, 2.0],
        "orientation_deg": [0, 15, 30, 45, 60, 90],
        "defect_ratio": [0.0, 0.15],
        "skin_thickness_mm": [0.0, 1.2],
        "tpms_thickness": [0.18, 0.68],
        "tpms_resolution": [56, 96],
    }

    @staticmethod
    def _legacy_compat_fields(loop_count: int) -> dict[str, float | str]:
        """Keep old lightweight fields for compatibility with existing logs/tests."""
        return {
            "temperature_c": 25 + (loop_count % 5),
            "strain_rate": round(0.2 + 0.05 * (loop_count % 4), 3),
            "budget_cost": round(1.5 + 0.1 * loop_count, 2),
        }

    def _deterministic_spec(self, state: OrchestratorState, ctx: AgentContext | Any) -> dict[str, Any]:
        """Build the selected candidate without relying on an LLM."""
        constraints = self._resolve_constraints(state)
        prior_summary = self._prior_results_summary(ctx)
        failure_summary = self._failure_memory_summary(ctx)
        strategy = self._select_strategy(prior_summary["count"])
        pool = self._candidate_pool(state=state, constraints=constraints, prior_count=prior_summary["count"])
        valid_pool, rejected = self._filter_candidates(pool, constraints=constraints, failure_summary=failure_summary)
        if not valid_pool:
            # Keep the loop moving with the least-bad safe seed while surfacing warnings.
            valid_pool = [self._safe_seed_candidate(state=state, constraints=constraints)]
        preferred = str(constraints.get("preferred_geometry_type", "")).strip()
        if preferred:
            preferred_pool = [item for item in valid_pool if str(item.get("geometry_type")) == preferred]
            if preferred_pool:
                valid_pool = preferred_pool
            else:
                fallback = self._safe_seed_candidate(state=state, constraints=constraints)
                fallback["validation_warnings"] = [
                    f"preferred geometry '{preferred}' had no valid generated candidate; conservative preferred-geometry seed used"
                ]
                valid_pool = [fallback]
        ranked = sorted(valid_pool, key=lambda item: item["expected_objective_proxy_score"], reverse=True)
        selected = dict(ranked[0])
        selected.update(self._legacy_compat_fields(state.loop_count))
        selected.update(
            {
                "specimen_id": self._specimen_id(state=state, candidate=selected),
                "objective_type": self._objective_type(state.active_goal),
                "objective_direction": self._objective_direction(state.active_goal),
                "material": str(constraints["material"]),
                "printer_profile": self._printer_profile(constraints),
                "slicer_profile_hint": self._slicer_profile_hint(constraints),
                "layer_height_mm": round(float(constraints["layer_height_mm"]), 4),
                "bed_temperature_c": round(float(constraints["bed_temperature_c"]), 2),
                "first_layer_bed_temperature_c": round(float(constraints["first_layer_bed_temperature_c"]), 2),
                "nozzle_diameter_mm": round(float(constraints["nozzle_diameter_mm"]), 4),
                "generation_strategy": strategy,
                "generation_reason": self._generation_reason(strategy, prior_summary, failure_summary),
                "design_space": self.DEFAULT_DESIGN_SPACE,
                "constraints": constraints,
                "prior_results_summary": prior_summary,
                "failure_memory_summary": failure_summary,
                "validation_warnings": self._candidate_warnings(selected, constraints) + rejected[:3],
                "candidate_pool_summary": {
                    "generated_count": len(pool),
                    "valid_count": len(valid_pool),
                    "rejected_count": len(rejected),
                    "top_candidates": [
                        {
                            "candidate_id": item["candidate_id"],
                            "geometry_type": item["geometry_type"],
                            "expected_objective_proxy_score": item["expected_objective_proxy_score"],
                        }
                        for item in ranked[:5]
                    ],
                },
            }
        )
        return selected

    def _resolve_constraints(self, state: OrchestratorState) -> dict[str, Any]:
        """Merge runtime defaults with any constraint-like fields already present in state."""
        constraints = dict(self.DEFAULT_CONSTRAINTS)
        source = state.current_experiment_spec or {}
        nested = source.get("constraints") if isinstance(source.get("constraints"), dict) else {}
        explicit_cell_size = any(
            "cell_size_mm" in item and item["cell_size_mm"] not in (None, "", [])
            for item in (source, nested)
            if isinstance(item, dict)
        )
        for item in (source, nested):
            for key in constraints:
                if key in item and item[key] not in (None, "", []):
                    constraints[key] = item[key]
        bo_recommended = {}
        if isinstance(state.run_metadata, dict):
            raw_bo = state.run_metadata.get("bo_recommended_constraints")
            bo_recommended = raw_bo if isinstance(raw_bo, dict) else {}
        for key, value in bo_recommended.items():
            if value in (None, "", []):
                continue
            if key == "cell_size_mm":
                continue
            if key in constraints:
                constraints[key] = value
            elif key == "geometry_type":
                constraints["preferred_geometry_type"] = value
        explicit_top_cap = any(isinstance(item, dict) and "top_cap_enabled" in item for item in (source, nested))
        explicit_bottom_cap = any(isinstance(item, dict) and "bottom_cap_enabled" in item for item in (source, nested))
        explicit_legacy_cap = any(isinstance(item, dict) and "top_bottom_cap" in item for item in (source, nested))
        if state.mode == Mode.TEST and not explicit_cell_size:
            constraints["cell_size_mm"] = 10.0
        constraints["max_specimen_size_mm"] = self._vector3(constraints.get("max_specimen_size_mm"), [30.0, 30.0, 30.0])
        constraints["utm_fixture_limit_mm"] = self._vector3(constraints.get("utm_fixture_limit_mm"), [40.0, 40.0, 60.0])
        preferred_geometry = ""
        for item in (source, nested):
            for key in ("preferred_geometry_type", "geometry_type"):
                if key in item and item[key] not in (None, "", []):
                    preferred_geometry = str(item[key])
                    break
            if preferred_geometry:
                break
        if not preferred_geometry:
            preferred_geometry = str(
                bo_recommended.get("preferred_geometry_type")
                or bo_recommended.get("geometry_type")
                or constraints.get("preferred_geometry_type")
                or ""
            )
        if state.mode == Mode.TEST and not preferred_geometry:
            preferred_geometry = self.TEST_DEFAULT_GEOMETRY
        constraints["preferred_geometry_type"] = self._normalize_geometry_type(preferred_geometry)
        for key in (
            "max_print_time_min",
            "max_mass_g",
            "nozzle_diameter_mm",
            "layer_height_mm",
            "bed_temperature_c",
            "first_layer_bed_temperature_c",
            "min_wall_thickness_mm",
            "minimum_feature_size_mm",
            "fdm_min_wall_thickness_mm",
            "fdm_max_bridge_distance_mm",
            "fdm_max_unsupported_overhang_deg",
            "fdm_max_gyroid_wall_cell_ratio",
            "cell_size_mm",
            "wall_thickness_mm",
            "relative_density",
            "anisotropy_ratio",
            "orientation_deg",
            "defect_ratio",
            "skin_thickness_mm",
            "tpms_thickness",
            "tpms_resolution",
        ):
            constraints[key] = float(constraints[key])
        if constraints["preferred_geometry_type"] == "gyroid":
            constraints["relative_density"] = max(0.20, float(constraints["relative_density"]))
        legacy_cap = bool(constraints["top_bottom_cap"])
        if explicit_top_cap or explicit_bottom_cap:
            constraints["top_cap_enabled"] = bool(constraints.get("top_cap_enabled", False))
            constraints["bottom_cap_enabled"] = bool(constraints.get("bottom_cap_enabled", legacy_cap))
        elif explicit_legacy_cap:
            constraints["top_cap_enabled"] = False
            constraints["bottom_cap_enabled"] = legacy_cap
        else:
            constraints["top_cap_enabled"] = bool(constraints.get("top_cap_enabled", False))
            constraints["bottom_cap_enabled"] = bool(constraints.get("bottom_cap_enabled", True))
        constraints["top_bottom_cap"] = bool(constraints["top_cap_enabled"] or constraints["bottom_cap_enabled"])
        constraints["skirt_enabled"] = bool(constraints["skirt_enabled"])
        constraints["require_flat_compression_faces"] = bool(constraints["require_flat_compression_faces"])
        if constraints["top_bottom_cap"]:
            constraints["skin_thickness_mm"] = max(0.2, float(constraints["skin_thickness_mm"] or 0.8))
            constraints["require_flat_compression_faces"] = bool(
                constraints.get("require_flat_compression_faces", False)
                and constraints["top_cap_enabled"]
                and constraints["bottom_cap_enabled"]
            )
        else:
            constraints["skin_thickness_mm"] = 0.0
            constraints["require_flat_compression_faces"] = False
        return constraints

    def _candidate_pool(
        self,
        *,
        state: OrchestratorState,
        constraints: dict[str, Any],
        prior_count: int,
    ) -> list[dict[str, Any]]:
        """Generate deterministic DOE/acquisition candidates and score each one."""
        max_size = self._bounded_size(constraints["max_specimen_size_mm"], constraints["utm_fixture_limit_mm"])
        pool: list[dict[str, Any]] = []
        geometry_cycle = self._geometry_cycle(constraints)
        orientations = self.DEFAULT_DESIGN_SPACE["orientation_deg"]
        base = state.loop_count * 7 + prior_count * 3
        for idx in range(12):
            geometry = str(geometry_cycle[(base + idx) % len(geometry_cycle)])
            rel_density = self._clamp(0.18 + 0.035 * ((base + idx * 2) % 10), 0.10, 0.60)
            wall = self._clamp(1.2 + 0.2 * ((base + idx) % 8), 1.2, 3.0)
            cell = self._clamp(max(3.0 * wall, 3.0 + 0.65 * ((base + idx * 3) % 11)), 3.0, 10.0)
            anisotropy = self._clamp(0.75 + 0.15 * ((base + idx) % 7), 0.5, 2.0)
            defect_ratio = self._clamp(0.015 * ((base + idx) % 10), 0.0, 0.15)
            skin = self._clamp(float(constraints.get("skin_thickness_mm", 0.0)), 0.0, 1.2)
            top_cap_enabled = bool(constraints.get("top_cap_enabled", False))
            bottom_cap_enabled = bool(constraints.get("bottom_cap_enabled", False))
            top_bottom_cap = bool(top_cap_enabled or bottom_cap_enabled)
            if geometry == "gyroid":
                max_bridge = float(constraints.get("fdm_max_bridge_distance_mm", 10.0))
                max_ratio = float(constraints.get("fdm_max_gyroid_wall_cell_ratio", 0.28))
                min_wall = float(constraints.get("fdm_min_wall_thickness_mm", 1.2))
                cell = self._clamp(
                    float(constraints.get("cell_size_mm", cell)),
                    max(3.0 * min_wall, 3.0),
                    max_bridge,
                )
                wall = self._clamp(wall, min_wall, max(min_wall, cell * max_ratio))
                wall = self._clamp(float(constraints.get("wall_thickness_mm", wall)), min_wall, max(min_wall, cell * max_ratio))
                rel_density = self._clamp(float(constraints.get("relative_density", rel_density)), 0.10, 0.60)
            candidate = {
                "candidate_id": f"cand-{state.loop_count + 1}-{idx + 1:02d}",
                "geometry_type": geometry,
                "specimen_size_mm": list(max_size),
                "cell_size_mm": round(cell, 3),
                "wall_thickness_mm": round(wall, 3),
                "relative_density": round(rel_density, 4),
                "porosity": round(1.0 - rel_density, 4),
                "anisotropy_ratio": round(anisotropy, 3),
                "orientation_deg": float(orientations[(base + idx) % len(orientations)]),
                "defect_seed": int(base + idx + 1),
                "defect_ratio": round(defect_ratio, 4),
                "skin_thickness_mm": round(skin, 3),
                "top_cap_enabled": top_cap_enabled,
                "bottom_cap_enabled": bottom_cap_enabled,
                "top_bottom_cap": top_bottom_cap,
                "skirt_enabled": bool(constraints.get("skirt_enabled", False)),
                "fdm_min_wall_thickness_mm": float(constraints.get("fdm_min_wall_thickness_mm", 1.2)),
                "fdm_max_bridge_distance_mm": float(constraints.get("fdm_max_bridge_distance_mm", 10.0)),
                "fdm_max_unsupported_overhang_deg": float(constraints.get("fdm_max_unsupported_overhang_deg", 45.0)),
                "fdm_max_gyroid_wall_cell_ratio": float(constraints.get("fdm_max_gyroid_wall_cell_ratio", 0.28)),
                "tpms_resolution": int(float(constraints.get("tpms_resolution", 72))),
            }
            if geometry == "gyroid":
                candidate.update(self._tpms_fields(candidate))
            candidate.update(self._estimate_candidate(candidate, constraints=constraints))
            candidate["generation_reason"] = "Constraint-filtered DOE/acquisition candidate for compression metamaterial specimen."
            pool.append(candidate)
        return pool

    def _estimate_candidate(self, candidate: dict[str, Any], *, constraints: dict[str, Any]) -> dict[str, float]:
        """Estimate mass, print time, manufacturability, and design-time objective proxy."""
        size = candidate["specimen_size_mm"]
        volume = float(size[0] * size[1] * size[2])
        rel_density = float(candidate["relative_density"])
        density_g_per_mm3 = 0.00124 if str(constraints["material"]).upper() == "PLA" else 0.00120
        expected_volume = volume * rel_density
        expected_mass = expected_volume * density_g_per_mm3
        feature_margin = min(
            1.0,
            float(candidate["wall_thickness_mm"]) / max(float(constraints["minimum_feature_size_mm"]), 1e-6),
            float(candidate["cell_size_mm"]) / max(3.0 * float(candidate["wall_thickness_mm"]), 1e-6),
        )
        cap_bonus = 0.04 * int(bool(candidate.get("bottom_cap_enabled", candidate.get("top_bottom_cap", False))))
        cap_bonus += 0.02 * int(bool(candidate.get("top_cap_enabled", False)))
        if not candidate.get("top_bottom_cap", True):
            cap_bonus -= 0.25
        defect_penalty = float(candidate["defect_ratio"]) * 0.65
        manufacturability = self._clamp(0.48 + 0.34 * feature_margin + cap_bonus - defect_penalty, 0.0, 1.0)
        geometry_bonus = {
            "gyroid": 0.17,
            "lattice_octet": 0.15,
            "lattice_bcc": 0.12,
            "honeycomb": 0.10,
            "lattice_fcc": 0.08,
            "auxetic_reentrant": 0.06,
            "random_voronoi": 0.03,
        }.get(str(candidate["geometry_type"]), 0.0)
        preferred = str(constraints.get("preferred_geometry_type", "")).strip()
        preference_bonus = 0.18 if preferred and str(candidate["geometry_type"]) == preferred else 0.0
        mass_efficiency = self._clamp(1.0 - expected_mass / max(float(constraints["max_mass_g"]), 1.0), 0.0, 1.0)
        crush_stability = self._clamp(0.36 + 0.45 * rel_density + geometry_bonus - 0.18 * float(candidate["defect_ratio"]), 0.0, 1.0)
        novelty = self._clamp(0.25 + abs(float(candidate["orientation_deg"]) - 30.0) / 120.0, 0.0, 1.0)
        proxy = self._clamp(
            0.38 * crush_stability + 0.26 * mass_efficiency + 0.24 * manufacturability + 0.12 * novelty + preference_bonus,
            0.0,
            1.0,
        )
        print_time = 18.0 + expected_volume / 240.0 + float(candidate["skin_thickness_mm"]) * 8.0
        return {
            "expected_mass_g": round(expected_mass, 3),
            "expected_volume_mm3": round(expected_volume, 3),
            "expected_print_time_min": round(print_time, 2),
            "expected_manufacturability_score": round(manufacturability, 4),
            "expected_objective_proxy_score": round(proxy, 4),
        }

    def _filter_candidates(
        self,
        pool: list[dict[str, Any]],
        *,
        constraints: dict[str, Any],
        failure_summary: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Apply hard design constraints before returning a candidate."""
        valid: list[dict[str, Any]] = []
        rejected: list[str] = []
        for candidate in pool:
            reasons = self._reject_reasons(candidate, constraints=constraints, failure_summary=failure_summary)
            if reasons:
                rejected.append(f"{candidate['candidate_id']}: {'; '.join(reasons)}")
            else:
                valid.append(candidate)
        return valid, rejected

    def _reject_reasons(
        self,
        candidate: dict[str, Any],
        *,
        constraints: dict[str, Any],
        failure_summary: dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        if candidate["geometry_type"] not in self.SUPPORTED_GEOMETRIES:
            reasons.append("unsupported geometry_type")
        size = candidate["specimen_size_mm"]
        if any(float(size[i]) > float(constraints["max_specimen_size_mm"][i]) for i in range(3)):
            reasons.append("specimen_size_mm exceeds printer constraint")
        if any(float(size[i]) > float(constraints["utm_fixture_limit_mm"][i]) for i in range(3)):
            reasons.append("specimen_size_mm exceeds UTM fixture constraint")
        min_wall = max(
            2.0 * float(constraints["nozzle_diameter_mm"]),
            float(constraints["minimum_feature_size_mm"]),
            float(constraints.get("fdm_min_wall_thickness_mm", 1.2)),
        )
        if float(candidate["wall_thickness_mm"]) < min_wall:
            reasons.append("wall_thickness_mm below minimum feature/nozzle rule")
        if float(candidate["cell_size_mm"]) < 3.0 * float(candidate["wall_thickness_mm"]):
            reasons.append("cell_size_mm below 3x wall thickness rule")
        if str(candidate["geometry_type"]) == "gyroid":
            if float(candidate["cell_size_mm"]) > float(constraints.get("fdm_max_bridge_distance_mm", 10.0)):
                reasons.append("gyroid cell_size_mm exceeds FDM bridge/span rule")
            if float(candidate["wall_thickness_mm"]) / max(float(candidate["cell_size_mm"]), 1e-6) > float(
                constraints.get("fdm_max_gyroid_wall_cell_ratio", 0.28)
            ):
                reasons.append("gyroid wall/cell ratio too high for open FDM TPMS channels")
            if float(candidate["relative_density"]) < 0.20:
                reasons.append("gyroid relative_density below FDM continuous-shell rule")
        if float(candidate["expected_mass_g"]) > float(constraints["max_mass_g"]):
            reasons.append("expected_mass_g exceeds max_mass_g")
        if float(candidate["expected_print_time_min"]) > float(constraints["max_print_time_min"]):
            reasons.append("expected_print_time_min exceeds max_print_time_min")
        if constraints["require_flat_compression_faces"] and not (
            bool(candidate.get("top_cap_enabled", candidate.get("top_bottom_cap", False)))
            and bool(candidate.get("bottom_cap_enabled", candidate.get("top_bottom_cap", False)))
        ):
            reasons.append("missing flat compression faces")
        failed_geometries = set(failure_summary.get("failed_geometry_types", []))
        if str(candidate["geometry_type"]) in failed_geometries:
            reasons.append("geometry_type matches recent failure memory")
        return reasons

    def _safe_seed_candidate(self, *, state: OrchestratorState, constraints: dict[str, Any]) -> dict[str, Any]:
        """Generate one conservative fallback candidate if the pool is fully rejected."""
        fallback_geometry = self._normalize_geometry_type(constraints.get("preferred_geometry_type")) or self.TEST_DEFAULT_GEOMETRY
        candidate = {
            "candidate_id": f"cand-{state.loop_count + 1}-safe",
            "geometry_type": fallback_geometry,
            "specimen_size_mm": self._bounded_size(constraints["max_specimen_size_mm"], constraints["utm_fixture_limit_mm"]),
            "cell_size_mm": float(constraints.get("cell_size_mm", 5.0)),
            "wall_thickness_mm": 1.2,
            "relative_density": 0.32,
            "porosity": 0.68,
            "anisotropy_ratio": 1.0,
            "orientation_deg": 0.0,
            "defect_seed": state.loop_count + 1,
            "defect_ratio": 0.0,
            "skin_thickness_mm": self._clamp(float(constraints.get("skin_thickness_mm", 0.0)), 0.0, 1.2),
            "top_cap_enabled": bool(constraints.get("top_cap_enabled", False)),
            "bottom_cap_enabled": bool(constraints.get("bottom_cap_enabled", False)),
            "top_bottom_cap": bool(
                constraints.get("top_cap_enabled", False) or constraints.get("bottom_cap_enabled", False)
            ),
            "skirt_enabled": bool(constraints.get("skirt_enabled", False)),
            "fdm_min_wall_thickness_mm": float(constraints.get("fdm_min_wall_thickness_mm", 1.2)),
            "fdm_max_bridge_distance_mm": float(constraints.get("fdm_max_bridge_distance_mm", 10.0)),
            "fdm_max_unsupported_overhang_deg": float(constraints.get("fdm_max_unsupported_overhang_deg", 45.0)),
            "fdm_max_gyroid_wall_cell_ratio": float(constraints.get("fdm_max_gyroid_wall_cell_ratio", 0.28)),
        }
        if fallback_geometry == "gyroid":
            candidate.update(self._tpms_fields(candidate))
        candidate.update(self._estimate_candidate(candidate, constraints=constraints))
        candidate["generation_reason"] = "Conservative fallback seed after candidate-pool rejection."
        return candidate

    def _candidate_warnings(self, candidate: dict[str, Any], constraints: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        if float(candidate["expected_print_time_min"]) > 0.85 * float(constraints["max_print_time_min"]):
            warnings.append("expected print time is close to max_print_time_min")
        if float(candidate["expected_manufacturability_score"]) < 0.62:
            warnings.append("manufacturability score is low; Guardian should inspect closely")
        if str(candidate["geometry_type"]) == "random_voronoi":
            warnings.append("random_voronoi has higher disconnected-component risk")
        return warnings

    def _prior_results_summary(self, ctx: AgentContext | Any) -> dict[str, Any]:
        db = getattr(ctx, "experiment_db", None)
        records = []
        if db is not None and hasattr(db, "list_recent"):
            try:
                records = list(db.list_recent(20))
            except Exception:
                records = []
        best = None
        if records:
            best_record = max(records, key=lambda item: float(getattr(item, "score", 0.0)))
            best = {
                "run_id": getattr(best_record, "run_id", ""),
                "experiment_id": getattr(best_record, "experiment_id", ""),
                "score": float(getattr(best_record, "score", 0.0)),
                "uncertainty": float(getattr(best_record, "uncertainty", 0.0)),
                "summary": str(getattr(best_record, "summary", ""))[:240],
            }
        return {"count": len(records), "best": best}

    def _failure_memory_summary(self, ctx: AgentContext | Any) -> dict[str, Any]:
        memory = getattr(ctx, "failure_memory", None)
        records = []
        if memory is not None and hasattr(memory, "recent"):
            try:
                records = list(memory.recent(10))
            except Exception:
                records = []
        failed_geometries: list[str] = []
        failure_types: list[str] = []
        for record in records:
            failure_types.append(str(getattr(record, "failure_type", "unknown")))
            context = getattr(record, "context", {}) or {}
            geometry = context.get("geometry_type") if isinstance(context, dict) else None
            if geometry:
                failed_geometries.append(str(geometry))
        return {
            "count": len(records),
            "failure_types": sorted(set(failure_types)),
            "failed_geometry_types": sorted(set(failed_geometries)),
        }

    def _geometry_cycle(self, constraints: dict[str, Any]) -> list[str]:
        """Return design-space geometries with any preferred geometry first."""
        preferred = str(constraints.get("preferred_geometry_type", "")).strip()
        geometries = list(self.DEFAULT_DESIGN_SPACE["geometry_types"])
        if preferred in geometries:
            return [preferred] + [geometry for geometry in geometries if geometry != preferred]
        return geometries

    @classmethod
    def _normalize_geometry_type(cls, value: Any) -> str:
        """Normalize legacy/generic geometry labels into supported specimen-design names."""
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "lattice": cls.LEGACY_ALIAS_GEOMETRY,
            "tpms": "gyroid",
            "tpms_gyroid": "gyroid",
            "gyroid_tpms": "gyroid",
            "metamaterial": "gyroid",
            "bending_dominated": "gyroid",
            "bending_dominated_lattice": "gyroid",
            "bcc": "lattice_bcc",
            "fcc": "lattice_fcc",
            "octet": "lattice_octet",
            "octet_lattice": "lattice_octet",
            "compression_cube": cls.LEGACY_ALIAS_GEOMETRY,
            "cube": cls.LEGACY_ALIAS_GEOMETRY,
        }
        normalized = aliases.get(text, text)
        return normalized if normalized in cls.SUPPORTED_GEOMETRIES else ""

    @staticmethod
    def _select_strategy(prior_count: int) -> str:
        if prior_count <= 0:
            return "deterministic_doe_seed"
        if prior_count < 5:
            return "proxy_acquisition_from_few_priors"
        return "surrogate_active_learning_placeholder"

    @staticmethod
    def _generation_reason(strategy: str, prior_summary: dict[str, Any], failure_summary: dict[str, Any]) -> str:
        return (
            f"Selected {strategy}; prior_count={prior_summary['count']}; "
            f"recent_failure_count={failure_summary['count']}. Candidate pool was constraint-filtered and ranked by proxy score."
        )

    @staticmethod
    def _objective_type(goal: str) -> str:
        lowered = goal.lower()
        if "peak" in lowered or "피크" in lowered or "하중" in lowered:
            return "maximize_peak_load"
        if "failure" in lowered or "파손" in lowered:
            return "control_failure_mode"
        if "explore" in lowered or "탐색" in lowered:
            return "explore_design_space"
        if "mass" in lowered or "질량" in lowered or "specific" in lowered:
            return "maximize_energy_absorption_per_mass"
        return "maximize_energy_absorption_per_mass"

    @staticmethod
    def _objective_direction(goal: str) -> str:
        lowered = goal.lower()
        if "minimize" in lowered or "최소" in lowered:
            return "minimize"
        if "explore" in lowered or "탐색" in lowered:
            return "explore"
        return "maximize"

    @staticmethod
    def _printer_profile(constraints: dict[str, Any]) -> str:
        nozzle = str(constraints.get("nozzle_diameter_mm", 0.4)).replace(".", "p")
        material = str(constraints.get("material", "PLA")).lower()
        printer = str(constraints.get("printer_model", "prusa_mk4s")).lower().replace(" ", "_")
        return f"{printer}_{material}_{nozzle}_nozzle"

    @staticmethod
    def _slicer_profile_hint(constraints: dict[str, Any]) -> str:
        layer = f"{float(constraints.get('layer_height_mm', 0.2)):g}"
        return f"{layer}mm_quality"

    @staticmethod
    def _specimen_id(*, state: OrchestratorState, candidate: dict[str, Any]) -> str:
        digest = hashlib.sha1(
            json.dumps(
                {
                    "run_id": state.run_id,
                    "experiment_id": state.experiment_id,
                    "candidate_id": candidate["candidate_id"],
                    "geometry_type": candidate["geometry_type"],
                    "specimen_size_mm": candidate["specimen_size_mm"],
                    "cell_size_mm": candidate["cell_size_mm"],
                    "wall_thickness_mm": candidate["wall_thickness_mm"],
                    "relative_density": candidate.get("relative_density"),
                    "anisotropy_ratio": candidate.get("anisotropy_ratio"),
                    "orientation_deg": candidate.get("orientation_deg"),
                    "tpms_thickness": candidate.get("tpms_thickness"),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:8]
        return f"specimen-{candidate['candidate_id']}-{candidate['geometry_type']}-{digest}"

    @staticmethod
    def _bounded_size(max_size: list[float], fixture_limit: list[float]) -> list[float]:
        return [round(min(float(max_size[i]), float(fixture_limit[i])), 3) for i in range(3)]

    @staticmethod
    def _vector3(value: Any, default: list[float]) -> list[float]:
        if not isinstance(value, list) or len(value) != 3:
            return list(default)
        out: list[float] = []
        for idx, item in enumerate(value):
            try:
                out.append(float(item))
            except (TypeError, ValueError):
                out.append(float(default[idx]))
        return out

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @classmethod
    def _tpms_fields(cls, candidate: dict[str, Any]) -> dict[str, Any]:
        """Expose optional TPMS controls while preserving the existing payload contract."""
        wall = float(candidate.get("wall_thickness_mm", 1.2))
        cell = max(float(candidate.get("cell_size_mm", 7.5)), 1e-6)
        rel_density = float(candidate.get("relative_density", 0.32))
        physical_min = cls._clamp(0.50 * wall * (6.283185307179586 / cell), 0.18, 0.68)
        density_threshold = 0.10 + 0.40 * rel_density + min(0.06, 0.20 * wall / cell)
        thickness = cls._clamp(max(density_threshold, physical_min), 0.18, 0.68)
        return {
            "tpms_surface": "gyroid",
            "tpms_thickness": round(thickness, 4),
            "tpms_resolution": int(float(candidate.get("tpms_resolution", 72))),
            "printability_mode": "fdm_closed_shell",
        }

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        use_llm = state.mode != Mode.TEST or ctx.force_real_llm_in_test
        spec = self._deterministic_spec(state, ctx)
        if not use_llm:
            rationale = "Deterministic test-mode specimen candidate generated from docs algorithm."
        else:
            prompt = (
                "Review this selected metamaterial compression specimen candidate. "
                "Do not generate STL vertices or G-code. Return concise risk/strategy notes only.\n"
                f"goal={state.active_goal}\n"
                f"candidate={json.dumps(spec, ensure_ascii=False, sort_keys=True)}\n"
            )
            timeout_s = 45.0 if state.mode == Mode.TEST else None
            try:
                response = await ctx.complete("design_reasoning", prompt, timeout_s=timeout_s)
                spec["model_note"] = response.text[:500]
                rationale = "E4B protocol reasoning reviewed a constraint-filtered specimen candidate."
            except Exception as exc:
                if state.mode == Mode.TEST:
                    spec["model_note"] = f"E4B degraded in test mode: {exc.__class__.__name__}"
                    rationale = "E4B timeout degraded to deterministic specimen design in test mode."
                else:
                    raise
        return AgentResult(
            success=True,
            summary="Specimen experiment design selected",
            data={"experiment_spec": spec, "rationale": rationale},
        )
