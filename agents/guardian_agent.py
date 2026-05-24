"""
File purpose:
- Validate run safety, detect anomalies, and decide continue/retry/stop actions.

Key classes/functions:
- GuardianAgent

Inputs/outputs:
- Input: device health, SARM risk signals, retry counters
- Output: guardian decision and safety summary

Dependencies:
- knowledge.failure_memory.FailureMemory

Modification guide:
- Safe places to edit: decision thresholds
- Risky places to edit: action values consumed by transitions
- Related files: orchestrator/transitions.py, policies/safe_stop_policy.py
"""

from __future__ import annotations

from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from knowledge.failure_memory import FailureRecord
from orchestrator.state import OrchestratorState


class GuardianAgent(BaseAgent):
    """Applies run safety and consistency checks."""

    name = "guardian_agent"
    TEST_LOOP_CYCLE_LIMIT = 5
    _SUPPORTED_GEOMETRIES = {
        "lattice_bcc",
        "lattice_fcc",
        "lattice_octet",
        "gyroid",
        "honeycomb",
        "auxetic_reentrant",
        "random_voronoi",
    }
    _UNHEALTHY_DEVICE_STATES = {
        "error",
        "fault",
        "failed",
        "offline",
        "disconnected",
        "unknown",
        "emergency",
        "stopped",
    }

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        spec_payload = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        sarm = state.latest_analysis.get("sarm", {}) if isinstance(state.latest_analysis.get("sarm"), dict) else {}
        precursor = self._safe_float(sarm.get("failure_precursor"), 0.0)
        recovery = bool(sarm.get("recovery_suggested", False))
        anomaly_detected = bool(state.latest_observations.get("anomaly", False))
        uncertainty = self._safe_float(state.latest_analysis.get("uncertainty"), 0.0)
        retry_pressure = int(sum(max(0, int(v)) for v in state.retry_counters.values()))

        recent_failures = ctx.failure_memory.recent(limit=30)
        design_validation = self._validate_design_spec(spec_payload, recent_failures)
        health_validation = self._resolve_device_health(state, ctx)
        consistency = self._consistency_check(
            spec=spec_payload,
            latest_analysis=state.latest_analysis,
            latest_observations=state.latest_observations,
            precursor=precursor,
            uncertainty=uncertainty,
            retry_pressure=retry_pressure,
        )

        live_mode = state.mode.value == "live"
        stop_threshold = 0.85 if live_mode else 0.92
        recover_threshold = 0.62 if live_mode else 0.72

        timeout_s = 45.0 if state.mode.value == "test" else None
        try:
            reasoning = await ctx.complete(
                "guardian_reasoning",
                (
                    "Evaluate continue/recover/retry/safe-stop policy.\n"
                    f"stage={state.stage.value}\n"
                    f"loop={state.loop_count}\n"
                    f"precursor={precursor}\n"
                    f"recovery_suggested={recovery}\n"
                    f"anomaly_detected={anomaly_detected}\n"
                    f"uncertainty={uncertainty}\n"
                    f"retry_pressure={retry_pressure}\n"
                    f"safe_stop_requested={state.safe_stop_requested}\n"
                    f"design_validation={design_validation}\n"
                    f"health_validation={health_validation}\n"
                    f"consistency={consistency}\n"
                ),
                timeout_s=timeout_s,
            )
            policy_note = reasoning.text[:260]
        except Exception as exc:
            if state.mode.value == "test":
                policy_note = f"Guardian degraded in test mode: {exc.__class__.__name__}"
            else:
                raise

        decision = "continue"
        action = "continue"
        reason = "Safety checks passed."

        if state.safe_stop_requested or state.stop_requested:
            decision = "stop"
            action = "safe_stop"
            reason = "Operator requested stop."
        elif design_validation["status"] == "fail":
            decision = "stop"
            action = "safe_stop"
            reason = f"Design validation failed: {design_validation['reject_reasons'][0]}"
            ctx.failure_memory.add(
                FailureRecord(
                    stage="guardian",
                    failure_type="guardian_design_validation",
                    context={
                        "candidate_id": str(spec_payload.get("candidate_id", "")),
                        "specimen_id": str(spec_payload.get("specimen_id", "")),
                        "geometry_type": str(spec_payload.get("geometry_type", "")),
                        "reject_reasons": design_validation["reject_reasons"][:3],
                        "loop_count": state.loop_count,
                    },
                )
            )
        elif health_validation["status"] == "fail":
            decision = "stop"
            action = "safe_stop"
            reason = f"Device health check failed: {', '.join(health_validation['unhealthy_devices'])}"
            ctx.failure_memory.add(
                FailureRecord(
                    stage="guardian",
                    failure_type="device_unhealthy",
                    context={
                        "unhealthy_devices": health_validation["unhealthy_devices"],
                        "loop_count": state.loop_count,
                    },
                )
            )
        elif precursor > stop_threshold or (anomaly_detected and precursor >= max(recover_threshold, 0.7)):
            decision = "stop"
            action = "safe_stop"
            reason = "High failure precursor detected."
            ctx.failure_memory.add(
                FailureRecord(
                    stage="guardian",
                    failure_type="high_precursor",
                    context={"precursor": precursor, "loop_count": state.loop_count},
                )
            )
        elif state.mode.value == "test" and state.loop_count >= self.TEST_LOOP_CYCLE_LIMIT - 1:
            decision = "stop"
            action = "safe_stop"
            reason = f"Test run reached planned {self.TEST_LOOP_CYCLE_LIMIT}-cycle loop cap."
        elif consistency["status"] == "fail":
            decision = "continue"
            action = "recover"
            reason = f"Consistency risk detected: {consistency['issues'][0]}"
        elif recovery or precursor >= recover_threshold or anomaly_detected:
            decision = "continue"
            action = "recover"
            reason = "Recovery suggested; continue with caution."
        elif retry_pressure >= 3 or uncertainty >= 0.3 or consistency["status"] == "warning":
            decision = "continue"
            action = "retry"
            reason = "Retry recommended due uncertainty/retry pressure."

        return AgentResult(
            success=True,
            summary=f"Guardian decision: {decision} ({action})",
            data={
                "guardian": {
                    "decision": decision,
                    "reason": reason,
                    "precursor": precursor,
                    "policy_note": policy_note,
                    "action": action,
                    "retry_pressure": retry_pressure,
                    "design_validation": design_validation,
                    "health_validation": health_validation,
                    "consistency": consistency,
                }
            },
            next_hint=decision,
        )

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _vector3(value: Any, default: list[float]) -> list[float]:
        if isinstance(value, (list, tuple)) and len(value) == 3:
            out: list[float] = []
            for item in value:
                try:
                    out.append(float(item))
                except (TypeError, ValueError):
                    return list(default)
            return out
        return list(default)

    def _resolve_device_health(self, state: OrchestratorState, ctx: AgentContext) -> dict[str, Any]:
        snapshot = dict(state.device_health or {})
        try:
            health_payload = ctx.tools.call("device.health", {})
            if isinstance(health_payload, dict):
                for key in ("printer", "camera", "robot", "utm", "simulator"):
                    if key in health_payload:
                        snapshot[key] = health_payload[key]
        except Exception:
            pass

        unhealthy: list[str] = []
        for device, raw_status in snapshot.items():
            status = str(raw_status).strip().lower()
            if status in self._UNHEALTHY_DEVICE_STATES:
                unhealthy.append(f"{device}:{status}")
        return {
            "status": "fail" if unhealthy else "pass",
            "snapshot": snapshot,
            "unhealthy_devices": unhealthy,
        }

    def _validate_design_spec(
        self,
        spec: dict[str, Any],
        recent_failures: list[FailureRecord],
    ) -> dict[str, Any]:
        reject_reasons: list[str] = []
        warnings: list[str] = []

        if not isinstance(spec, dict) or not spec:
            return {
                "status": "fail",
                "reject_reasons": ["current_experiment_spec is missing or invalid."],
                "warnings": warnings,
            }

        candidate_id = str(spec.get("candidate_id", "")).strip()
        specimen_id = str(spec.get("specimen_id", "")).strip()
        geometry_type = str(spec.get("geometry_type", "")).strip()
        constraints = spec.get("constraints") if isinstance(spec.get("constraints"), dict) else {}

        if not candidate_id:
            reject_reasons.append("candidate_id is missing.")
        if not specimen_id:
            reject_reasons.append("specimen_id is missing.")
        if geometry_type not in self._SUPPORTED_GEOMETRIES:
            reject_reasons.append("geometry_type unsupported by current runtime.")

        size = self._vector3(spec.get("specimen_size_mm"), [0.0, 0.0, 0.0])
        max_size = self._vector3(constraints.get("max_specimen_size_mm"), [30.0, 30.0, 30.0])
        fixture = self._vector3(constraints.get("utm_fixture_limit_mm"), [40.0, 40.0, 60.0])
        if any(size[idx] > max_size[idx] for idx in range(3)):
            reject_reasons.append("specimen_size_mm exceeds max_specimen_size_mm.")
        if any(size[idx] > fixture[idx] for idx in range(3)):
            reject_reasons.append("specimen_size_mm exceeds utm_fixture_limit_mm.")

        wall = self._safe_float(spec.get("wall_thickness_mm"), -1.0)
        cell = self._safe_float(spec.get("cell_size_mm"), -1.0)
        mass = self._safe_float(spec.get("expected_mass_g"), -1.0)
        print_time = self._safe_float(spec.get("expected_print_time_min"), -1.0)

        nozzle = self._safe_float(constraints.get("nozzle_diameter_mm"), 0.4)
        min_feature = self._safe_float(constraints.get("minimum_feature_size_mm"), 0.8)
        min_wall = max(2.0 * nozzle, min_feature)
        if wall < min_wall:
            reject_reasons.append("wall_thickness_mm below nozzle/feature minimum.")
        if cell < 3.0 * max(wall, 1e-6):
            reject_reasons.append("cell_size_mm below 3x wall_thickness_mm.")

        max_mass = self._safe_float(constraints.get("max_mass_g"), 50.0)
        max_print_time = self._safe_float(constraints.get("max_print_time_min"), 120.0)
        allow_time_over = bool(constraints.get("allow_print_time_overrun", False))
        if mass > max_mass:
            reject_reasons.append("expected_mass_g exceeds max_mass_g.")
        if print_time > max_print_time and not allow_time_over:
            reject_reasons.append("expected_print_time_min exceeds max_print_time_min.")

        require_flat = bool(constraints.get("require_flat_compression_faces", False))
        legacy_cap = bool(spec.get("top_bottom_cap", False))
        top_cap = bool(spec.get("top_cap_enabled", legacy_cap))
        bottom_cap = bool(spec.get("bottom_cap_enabled", legacy_cap))
        if require_flat and not (top_cap and bottom_cap):
            reject_reasons.append("top_cap_enabled and bottom_cap_enabled must both be true for flat compression fixtures.")

        failure_pattern = self._failure_pattern_match(
            candidate_id=candidate_id,
            specimen_id=specimen_id,
            geometry_type=geometry_type,
            recent_failures=recent_failures,
        )
        if failure_pattern:
            reject_reasons.append(failure_pattern)

        if 0 <= mass <= max_mass * 1.05 and mass >= max_mass * 0.9:
            warnings.append("expected_mass_g is close to max_mass_g.")
        if 0 <= print_time <= max_print_time * 1.05 and print_time >= max_print_time * 0.9:
            warnings.append("expected_print_time_min is close to max_print_time_min.")

        status = "fail" if reject_reasons else ("warning" if warnings else "pass")
        return {"status": status, "reject_reasons": reject_reasons, "warnings": warnings}

    @staticmethod
    def _failure_pattern_match(
        *,
        candidate_id: str,
        specimen_id: str,
        geometry_type: str,
        recent_failures: list[FailureRecord],
    ) -> str:
        same_geometry_high_risk = 0
        for record in recent_failures:
            context = record.context if isinstance(record.context, dict) else {}
            if candidate_id and str(context.get("candidate_id", "")).strip() == candidate_id:
                return "candidate_id matches known failure memory pattern."
            if specimen_id and str(context.get("specimen_id", "")).strip() == specimen_id:
                return "specimen_id matches known failure memory pattern."
            if geometry_type and str(context.get("geometry_type", "")).strip() == geometry_type:
                if str(record.failure_type).strip() in {"high_precursor", "guardian_design_validation"}:
                    same_geometry_high_risk += 1
        if same_geometry_high_risk >= 2:
            return "geometry_type repeatedly triggered high-risk failures."
        return ""

    @staticmethod
    def _consistency_check(
        *,
        spec: dict[str, Any],
        latest_analysis: dict[str, Any],
        latest_observations: dict[str, Any],
        precursor: float,
        uncertainty: float,
        retry_pressure: int,
    ) -> dict[str, Any]:
        issues: list[str] = []
        warnings: list[str] = []

        objective = GuardianAgent._safe_float(latest_analysis.get("objective_score"), -1.0)
        progress = GuardianAgent._safe_float(
            latest_analysis.get("sarm", {}).get("progress_score") if isinstance(latest_analysis.get("sarm"), dict) else None,
            -1.0,
        )
        anomaly = bool(latest_observations.get("anomaly", False))
        expected_proxy = GuardianAgent._safe_float(spec.get("expected_objective_proxy_score"), -1.0) if isinstance(spec, dict) else -1.0

        if progress >= 0.85 and precursor >= 0.85:
            issues.append("high progress but also high failure precursor.")
        if objective >= 0.0 and objective < 0.45 and precursor >= 0.7:
            issues.append("low objective with high failure precursor.")
        if objective >= 0.0 and expected_proxy >= 0.0 and objective < expected_proxy * 0.55:
            warnings.append("observed objective is far below expected proxy score.")
        if anomaly and objective >= 0.8:
            warnings.append("camera anomaly conflicts with high objective score.")
        if uncertainty >= 0.3:
            warnings.append("analysis uncertainty is high.")
        if retry_pressure >= 3:
            warnings.append("retry pressure is high.")

        status = "fail" if issues else ("warning" if warnings else "pass")
        return {"status": status, "issues": issues, "warnings": warnings}
