"""Guardian's existing bounded policy-evidence call; deterministic gates stay in agent.py."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from agents.core.knowledge.context import mark_reference_delivered, record_reference_use
from agents.core.knowledge.runtime_reference import build_execution_reference as build_reference_context


async def run_guardian_advisory(
    state: Any,
    ctx: Any,
    *,
    anomaly_detected: bool,
    uncertainty: float | None,
    retry_pressure: int,
    design_validation: dict[str, Any],
    health_validation: dict[str, Any],
    graph_gate_pressure: dict[str, Any],
    consistency: dict[str, Any],
    advisory_evidence_context: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return the same advisory note and reference receipt used by the original body."""
    timeout_s = 45.0 if state.mode.value == "test" else None
    reference = build_reference_context(
        ctx,
        consumer="guardian_agent",
        query=state.active_goal or "Guardian policy evidence",
        run_id=state.run_id,
        loop_id=str(state.loop_count),
    )
    delivery = reference["delivery"]
    reference_pack = reference["pack"]
    if advisory_evidence_context is not None:
        reference_pack = {
            **deepcopy(reference_pack),
            "configured_owner_plan": {
                "authority": "reference_only",
                "advisory_evidence_context": deepcopy(advisory_evidence_context),
            },
        }
    try:
        delivery = mark_reference_delivered(ctx, reference)
        reasoning = await ctx.complete(
            "guardian_reasoning",
            (
                "Evaluate continue/recover/retry/safe-stop policy.\n"
                f"stage={state.stage.value}\n"
                f"loop={state.loop_count}\n"
                f"anomaly_detected={anomaly_detected}\n"
                f"uncertainty={uncertainty}\n"
                f"retry_pressure={retry_pressure}\n"
                f"safe_stop_requested={state.safe_stop_requested}\n"
                f"design_validation={design_validation}\n"
                f"health_validation={health_validation}\n"
                f"graph_gate_pressure={graph_gate_pressure}\n"
                f"consistency={consistency}\n"
                f"reference_only={json.dumps(reference_pack, ensure_ascii=False)}\n"
            ),
            timeout_s=timeout_s,
        )
        policy_note = reasoning.text[:260]
        delivery = record_reference_use(ctx, reference, policy_note)
    except Exception as exc:
        if state.mode.value == "test":
            policy_note = f"Guardian degraded in test mode: {exc.__class__.__name__}"
        else:
            raise
    return policy_note, delivery
