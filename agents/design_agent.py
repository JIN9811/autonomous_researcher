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
from datetime import datetime, timezone
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
        """Compatibility wrapper returning only the selected experiment spec."""
        return self._deterministic_design_payload(state, ctx)["experiment_spec"]

    def _deterministic_design_payload(self, state: OrchestratorState, ctx: AgentContext | Any) -> dict[str, Any]:
        """Build a traceable design decision packet without letting an LLM optimize."""
        constraints = self._resolve_constraints(state)
        objective = self._objective_contract(state, constraints)
        prior_summary = self._prior_results_summary(ctx)
        failure_summary = self._failure_memory_summary(ctx)
        bo_recommendation = self._bo_recommendation_summary(state)
        knowledge_summary = self._knowledge_summary(state, ctx, prior_summary)
        strategy = self._select_strategy(prior_summary["count"])
        pool = self._candidate_pool(state=state, constraints=constraints, prior_count=prior_summary["count"])
        valid_pool, rejected = self._filter_candidates(pool, constraints=constraints, failure_summary=failure_summary)
        hard_valid_count = len(valid_pool)
        repaired_candidates: list[dict[str, Any]] = []
        if not valid_pool:
            # Keep the loop moving with a conservative seed, but preserve the failed ledger.
            fallback = self._safe_seed_candidate(state=state, constraints=constraints)
            fallback["repair_source"] = "full_pool_rejected"
            fallback["candidate_status"] = "repaired_fallback"
            repaired_candidates.append(fallback)
            valid_pool = [fallback]
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
                fallback["repair_source"] = "preferred_geometry_invalid"
                fallback["candidate_status"] = "repaired_preferred_fallback"
                repaired_candidates.append(fallback)
                valid_pool = [fallback]
        ranked = sorted(valid_pool, key=lambda item: item["expected_objective_proxy_score"], reverse=True)
        selected = dict(ranked[0])
        selected["candidate_status"] = "selected"
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
                "validation_warnings": self._candidate_warnings(selected, constraints)
                + [self._rejection_summary(item) for item in rejected[:3]],
            }
        )
        design_report = self._design_report(
            state=state,
            selected=selected,
            pool=pool,
            ranked=ranked,
            rejected=rejected,
            repaired_candidates=repaired_candidates,
            objective=objective,
            strategy=strategy,
            constraints=constraints,
            prior_summary=prior_summary,
            failure_summary=failure_summary,
            bo_recommendation=bo_recommendation,
            knowledge_summary=knowledge_summary,
        )
        selected["candidate_pool_summary"] = {
            "generated_count": len(pool),
            "valid_count": hard_valid_count or len(valid_pool),
            "rejected_count": len(rejected),
            "selected_candidate_id": selected["candidate_id"],
            "selected_candidate_fingerprint": selected.get("candidate_fingerprint"),
            "top_candidates": design_report["candidate_generation"]["top_candidates"],
        }
        selected["objective_contract"] = objective
        selected["design_report_ref"] = {
            "schema": design_report["schema"],
            "report_id": design_report["report_id"],
            "selected_candidate_id": selected["candidate_id"],
        }
        handoff_packet = self._design_handoff_packet(state=state, selected=selected, design_report=design_report)
        return {
            "experiment_spec": selected,
            "design_report": design_report,
            "design_candidate": handoff_packet,
            "handoff_packet": handoff_packet,
            "candidate_ledger": design_report["candidate_generation"]["candidate_ledger"],
            "decisions": design_report["decision_register"],
            "metrics": design_report["candidate_evaluation"],
        }

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
            candidate["candidate_fingerprint"] = self._candidate_fingerprint(candidate)
            candidate["candidate_status"] = "generated"
            candidate["generation_reason"] = "Constraint-filtered DOE/acquisition candidate for compression metamaterial specimen."
            pool.append(candidate)
        return pool

    def _estimate_candidate(self, candidate: dict[str, Any], *, constraints: dict[str, Any]) -> dict[str, float]:
        """Estimate mass, print time, manufacturability, uncertainty, and information value."""
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
        print_time_ratio = self._clamp(print_time / max(float(constraints["max_print_time_min"]), 1.0), 0.0, 1.5)
        mass_ratio = self._clamp(expected_mass / max(float(constraints["max_mass_g"]), 1.0), 0.0, 1.5)
        risk = self._clamp(
            0.44 * (1.0 - manufacturability)
            + 0.22 * float(candidate["defect_ratio"])
            + 0.19 * print_time_ratio
            + 0.15 * mass_ratio,
            0.0,
            1.0,
        )
        uncertainty = self._clamp(0.12 + 0.32 * novelty + 0.22 * risk - 0.08 * manufacturability, 0.05, 0.72)
        information_gain = self._clamp(0.40 * novelty + 0.35 * uncertainty + 0.25 * (1.0 - abs(rel_density - 0.32) / 0.32), 0.0, 1.0)
        return {
            "expected_mass_g": round(expected_mass, 3),
            "expected_volume_mm3": round(expected_volume, 3),
            "expected_print_time_min": round(print_time, 2),
            "expected_manufacturability_score": round(manufacturability, 4),
            "expected_objective_proxy_score": round(proxy, 4),
            "predicted_objective": round(proxy, 4),
            "uncertainty": round(uncertainty, 4),
            "information_gain_score": round(information_gain, 4),
            "risk_score": round(risk, 4),
            "constraint_margin_score": round(feature_margin, 4),
        }

    def _filter_candidates(
        self,
        pool: list[dict[str, Any]],
        *,
        constraints: dict[str, Any],
        failure_summary: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Apply hard design constraints and keep a structured rejection ledger."""
        valid: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for candidate in pool:
            reasons = self._reject_reasons(candidate, constraints=constraints, failure_summary=failure_summary)
            if reasons:
                candidate["candidate_status"] = "rejected"
                rejected.append(
                    {
                        "candidate_id": str(candidate.get("candidate_id") or ""),
                        "candidate_fingerprint": candidate.get("candidate_fingerprint"),
                        "geometry_type": candidate.get("geometry_type"),
                        "reason": "; ".join(reasons),
                        "reasons": reasons,
                        "repair_attempted": False,
                        "repair_result": None,
                        "status": "rejected",
                    }
                )
            else:
                candidate["candidate_status"] = "valid"
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
        candidate["candidate_fingerprint"] = self._candidate_fingerprint(candidate)
        candidate["candidate_status"] = "generated"
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


    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _objective_contract(self, state: OrchestratorState, constraints: dict[str, Any]) -> dict[str, Any]:
        objective_type = self._objective_type(state.active_goal)
        direction = self._objective_direction(state.active_goal)
        metric_map = {
            "maximize_peak_load": "peak_load_n",
            "control_failure_mode": "failure_mode_score",
            "explore_design_space": "information_gain_score",
            "maximize_energy_absorption_per_mass": "energy_absorption_per_mass",
        }
        primary_metric = metric_map.get(objective_type, "energy_absorption_per_mass")
        return {
            "schema": "experiment_objective.v1",
            "objective_id": f"obj-{state.experiment_id or state.run_id or 'design'}",
            "source_goal": state.active_goal or "maximize metamaterial specimen performance",
            "objective_type": objective_type,
            "primary_metric": primary_metric,
            "direction": direction,
            "secondary_metrics": ["manufacturability_score", "print_time_min", "mass_g", "information_gain_score"],
            "constraints": {
                "geometry_types": list(self.SUPPORTED_GEOMETRIES),
                "material": constraints.get("material"),
                "printer_model": constraints.get("printer_model"),
                "max_specimen_size_mm": constraints.get("max_specimen_size_mm"),
                "utm_fixture_limit_mm": constraints.get("utm_fixture_limit_mm"),
                "max_print_time_min": constraints.get("max_print_time_min"),
                "max_mass_g": constraints.get("max_mass_g"),
                "fdm_min_wall_thickness_mm": constraints.get("fdm_min_wall_thickness_mm"),
                "fdm_max_bridge_distance_mm": constraints.get("fdm_max_bridge_distance_mm"),
            },
            "success_criteria": [
                "candidate passes deterministic FDM and fixture constraints",
                "experiment_spec contains all fields required by Specimen Agent",
                "candidate decision is backed by a candidate ledger and rejection log",
            ],
            "stop_criteria": [
                "no valid or repaired candidate can satisfy hard constraints",
                "Guardian blocks the design handoff",
            ],
        }

    def _bo_recommendation_summary(self, state: OrchestratorState) -> dict[str, Any]:
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        direct = metadata.get("bo_recommended_constraints") if isinstance(metadata.get("bo_recommended_constraints"), dict) else {}
        bo_agent = metadata.get("bo_agent") if isinstance(metadata.get("bo_agent"), dict) else {}
        recommendation = bo_agent.get("recommendation") if isinstance(bo_agent.get("recommendation"), dict) else {}
        selected = bo_agent.get("selected") if isinstance(bo_agent.get("selected"), dict) else {}
        merged = {**selected, **recommendation, **direct}
        return {
            "available": bool(merged),
            "source": "run_metadata.bo_agent/bo_recommended_constraints" if merged else "none",
            "parameters": merged,
            "acquisition": bo_agent.get("acquisition") or bo_agent.get("acquisition_function") or "not_available",
            "strategy": bo_agent.get("strategy") or "not_available",
        }

    def _knowledge_summary(
        self,
        state: OrchestratorState,
        ctx: AgentContext | Any,
        prior_summary: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = state.run_metadata if isinstance(state.run_metadata, dict) else {}
        knowledge = metadata.get("knowledge") if isinstance(metadata.get("knowledge"), dict) else {}
        best = prior_summary.get("best") if isinstance(prior_summary.get("best"), dict) else {}
        entries: list[str] = []
        if knowledge:
            for key in ("summary", "memory_update", "recommendation", "evidence"):
                value = knowledge.get(key)
                if value:
                    entries.append(f"{key}: {str(value)[:220]}")
        if best:
            entries.append(f"best_prior score={best.get('score')} summary={str(best.get('summary', ''))[:180]}")
        return {
            "available": bool(entries),
            "entries": entries[:5],
            "source": "run_metadata.knowledge + experiment_db" if entries else "none",
        }

    def _candidate_fingerprint(self, candidate: dict[str, Any]) -> str:
        payload = {
            "geometry_type": candidate.get("geometry_type"),
            "specimen_size_mm": candidate.get("specimen_size_mm"),
            "cell_size_mm": candidate.get("cell_size_mm"),
            "wall_thickness_mm": candidate.get("wall_thickness_mm"),
            "relative_density": candidate.get("relative_density"),
            "anisotropy_ratio": candidate.get("anisotropy_ratio"),
            "orientation_deg": candidate.get("orientation_deg"),
            "defect_ratio": candidate.get("defect_ratio"),
            "top_cap_enabled": candidate.get("top_cap_enabled"),
            "bottom_cap_enabled": candidate.get("bottom_cap_enabled"),
            "tpms_thickness": candidate.get("tpms_thickness"),
        }
        return hashlib.sha1(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _rejection_summary(record: dict[str, Any]) -> str:
        return f"{record.get('candidate_id', 'candidate')}: {record.get('reason', 'rejected')}"

    def _candidate_ledger_item(self, candidate: dict[str, Any], *, status: str) -> dict[str, Any]:
        return {
            "candidate_id": candidate.get("candidate_id"),
            "candidate_fingerprint": candidate.get("candidate_fingerprint"),
            "status": status,
            "geometry_type": candidate.get("geometry_type"),
            "specimen_size_mm": candidate.get("specimen_size_mm"),
            "cell_size_mm": candidate.get("cell_size_mm"),
            "wall_thickness_mm": candidate.get("wall_thickness_mm"),
            "relative_density": candidate.get("relative_density"),
            "orientation_deg": candidate.get("orientation_deg"),
            "expected_objective_proxy_score": candidate.get("expected_objective_proxy_score"),
            "predicted_objective": candidate.get("predicted_objective"),
            "uncertainty": candidate.get("uncertainty"),
            "manufacturability_score": candidate.get("expected_manufacturability_score"),
            "information_gain_score": candidate.get("information_gain_score"),
            "risk_score": candidate.get("risk_score"),
        }

    def _design_report(
        self,
        *,
        state: OrchestratorState,
        selected: dict[str, Any],
        pool: list[dict[str, Any]],
        ranked: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        repaired_candidates: list[dict[str, Any]],
        objective: dict[str, Any],
        strategy: str,
        constraints: dict[str, Any],
        prior_summary: dict[str, Any],
        failure_summary: dict[str, Any],
        bo_recommendation: dict[str, Any],
        knowledge_summary: dict[str, Any],
    ) -> dict[str, Any]:
        timestamp = self._now_iso()
        selected_id = str(selected.get("candidate_id") or "")
        valid_ids = {str(item.get("candidate_id") or "") for item in ranked}
        ledger = []
        for candidate in pool:
            cid = str(candidate.get("candidate_id") or "")
            raw_status = str(candidate.get("candidate_status") or "generated")
            if cid == selected_id:
                status = "selected"
            elif raw_status == "rejected":
                status = "rejected"
            elif raw_status == "valid" or cid in valid_ids:
                status = "valid"
            else:
                status = raw_status
            ledger.append(self._candidate_ledger_item(candidate, status=status))
        for repaired in repaired_candidates:
            if str(repaired.get("candidate_id") or "") not in {str(item.get("candidate_id") or "") for item in pool}:
                ledger.append(self._candidate_ledger_item(repaired, status=str(repaired.get("candidate_status") or "repaired")))
        top_candidates = [self._candidate_ledger_item(item, status="selected" if item.get("candidate_id") == selected_id else "valid") for item in ranked[:5]]
        hard_valid_count = sum(1 for item in pool if str(item.get("candidate_status") or "") == "valid") or len(ranked)
        required_fields = self._required_handoff_fields()
        missing = [field for field in required_fields if selected.get(field) in (None, "", [])]
        variables = [
            "geometry_type",
            "cell_size_mm",
            "wall_thickness_mm",
            "relative_density",
            "orientation_deg",
            "tpms_thickness",
        ]
        hypothesis = {
            "statement": (
                f"{selected.get('geometry_type')} geometry with cell_size={selected.get('cell_size_mm')} mm and "
                f"relative_density={selected.get('relative_density')} should improve "
                f"{objective.get('primary_metric')} while staying printable on {constraints.get('printer_model')}."
            ),
            "variables_under_test": [key for key in variables if selected.get(key) not in (None, "", [])],
            "expected_tradeoffs": [
                "higher relative density should improve load capacity but increases mass and print time",
                "larger cell size improves open-channel printability but can reduce structural uniformity",
                "bottom cap improves bed adhesion and compression contact but changes local stiffness",
            ],
            "falsification_signal": "measured objective below prior baseline, disconnected STL body, failed printability gate, or UTM failure mode outside expected range",
        }
        evaluation = {
            "selected_candidate_id": selected_id,
            "selected_candidate_fingerprint": selected.get("candidate_fingerprint"),
            "selected_score": selected.get("expected_objective_proxy_score"),
            "predicted_objective": selected.get("predicted_objective"),
            "uncertainty": selected.get("uncertainty"),
            "manufacturability_score": selected.get("expected_manufacturability_score"),
            "information_gain_score": selected.get("information_gain_score"),
            "risk_score": selected.get("risk_score"),
            "constraint_margin_score": selected.get("constraint_margin_score"),
            "ranked_position": 1,
        }
        decision_register = [
            {
                "decision_id": "design.objective.normalized",
                "decision": "objective_contract_created",
                "rationale": "Operator goal was normalized into metric, direction, constraints, and stop criteria before candidate ranking.",
                "evidence": {"primary_metric": objective.get("primary_metric"), "direction": objective.get("direction")},
                "status": "ok",
                "timestamp": timestamp,
            },
            {
                "decision_id": "design.pool.filtered",
                "decision": "constraint_gate_applied",
                "rationale": "Hard FDM, fixture, mass, time, and failure-memory constraints filtered the deterministic candidate pool.",
                "evidence": {"generated": len(pool), "valid": hard_valid_count, "rejected": len(rejected)},
                "status": "ok" if ranked else "repaired",
                "timestamp": timestamp,
            },
            {
                "decision_id": "design.candidate.selected",
                "decision": "selected_candidate_for_specimen_agent",
                "rationale": "Highest ranked valid candidate was selected by deterministic proxy score, not by free-form LLM generation.",
                "evidence": evaluation,
                "status": "ok",
                "timestamp": timestamp,
            },
            {
                "decision_id": "design.handoff.ready",
                "decision": "experiment_spec_is_authoritative_handoff",
                "rationale": "The canonical experiment_spec remains the downstream contract; design_report is explanatory evidence.",
                "evidence": {"missing_required_fields": missing},
                "status": "ok" if not missing else "blocked",
                "timestamp": timestamp,
            },
        ]
        return {
            "schema": "design_report.v1",
            "report_id": f"design-report-{state.run_id or 'run'}-{state.loop_count + 1}",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "loop_index": state.loop_count + 1,
            "created_at": timestamp,
            "producer_agent": self.name,
            "hypothesis": hypothesis,
            "objective": objective,
            "prior_context": {
                "prior_count": prior_summary.get("count", 0),
                "best_prior": prior_summary.get("best"),
                "knowledge_summary": knowledge_summary,
                "bo_recommendation": bo_recommendation,
                "failure_memory": failure_summary,
            },
            "candidate_generation": {
                "strategy": strategy,
                "budget": len(pool),
                "design_space": self.DEFAULT_DESIGN_SPACE,
                "candidate_count": len(pool),
                "valid_count": hard_valid_count,
                "rejected_count": len(rejected),
                "repaired_count": len(repaired_candidates),
                "candidate_ledger": ledger,
                "top_candidates": top_candidates,
            },
            "candidate_evaluation": evaluation,
            "rejected_candidates": rejected,
            "repaired_candidates": [self._candidate_ledger_item(item, status=str(item.get("candidate_status") or "repaired")) for item in repaired_candidates],
            "manufacturability": {
                "printer_model": constraints.get("printer_model"),
                "material": constraints.get("material"),
                "fdm_constraints_checked": True,
                "expected_print_time_min": selected.get("expected_print_time_min"),
                "expected_mass_g": selected.get("expected_mass_g"),
                "warnings": self._candidate_warnings(selected, constraints),
            },
            "decision_register": decision_register,
            "handoff_to_specimen": {
                "schema": "handoff_packet.v1",
                "consumer_agent": "specimen_agent",
                "required_fields_present": not missing,
                "missing_required_fields": missing,
                "manufacturing_notes": [
                    f"Use {selected.get('printer_profile')} and {selected.get('slicer_profile_hint')}.",
                    f"Target material={selected.get('material')} layer_height_mm={selected.get('layer_height_mm')}.",
                    "Specimen Agent must slice/bridge using experiment_spec as the authoritative payload.",
                ],
                "known_risks": self._candidate_warnings(selected, constraints),
                "authoritative_specimen_id": selected.get("specimen_id"),
                "authoritative_candidate_id": selected_id,
            },
        }

    @staticmethod
    def _required_handoff_fields() -> list[str]:
        return [
            "candidate_id",
            "specimen_id",
            "geometry_type",
            "specimen_size_mm",
            "cell_size_mm",
            "wall_thickness_mm",
            "relative_density",
            "material",
            "printer_profile",
            "slicer_profile_hint",
            "layer_height_mm",
            "expected_mass_g",
            "expected_print_time_min",
        ]

    def _design_handoff_packet(
        self,
        *,
        state: OrchestratorState,
        selected: dict[str, Any],
        design_report: dict[str, Any],
    ) -> dict[str, Any]:
        handoff = design_report.get("handoff_to_specimen", {}) if isinstance(design_report.get("handoff_to_specimen"), dict) else {}
        return {
            "schema": "design_candidate.v1",
            "packet_id": f"design-candidate-{selected.get('specimen_id', selected.get('candidate_id', 'unknown'))}",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "loop_index": state.loop_count + 1,
            "producer_agent": self.name,
            "consumer_agent": "specimen_agent",
            "status": "ready" if handoff.get("required_fields_present", False) else "blocked",
            "candidate_id": selected.get("candidate_id"),
            "specimen_id": selected.get("specimen_id"),
            "candidate_fingerprint": selected.get("candidate_fingerprint"),
            "experiment_spec": selected,
            "report_ref": {
                "schema": design_report.get("schema"),
                "report_id": design_report.get("report_id"),
            },
            "evidence_refs": [design_report.get("report_id")],
            "guardian_status": "not_evaluated",
            "decisions": design_report.get("decision_register", []),
            "warnings": handoff.get("known_risks", []),
            "next_action": "handoff_to_specimen_agent" if handoff.get("required_fields_present", False) else "complete_missing_design_fields",
        }

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        use_llm = state.mode != Mode.TEST or ctx.force_real_llm_in_test
        payload = self._deterministic_design_payload(state, ctx)
        spec = payload["experiment_spec"]
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
                payload["design_report"]["llm_protocol_note"] = response.text[:500]
                rationale = "E4B protocol reasoning reviewed a constraint-filtered specimen candidate."
            except Exception as exc:
                if state.mode == Mode.TEST:
                    spec["model_note"] = f"E4B degraded in test mode: {exc.__class__.__name__}"
                    payload["design_report"]["llm_protocol_note"] = spec["model_note"]
                    rationale = "E4B timeout degraded to deterministic specimen design in test mode."
                else:
                    raise
        return AgentResult(
            success=True,
            summary="Specimen experiment design selected",
            data={**payload, "rationale": rationale},
        )
