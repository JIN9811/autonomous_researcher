"""Read-only terminal revalidation of fully completed Equipment workflows."""
from copy import deepcopy
import asyncio
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone

from agents.base_agent import AgentResult
from utils.agent_artifact_archive import record_tool_artifact
from utils.equipment_agentic_task import project_equipment_cycle_evidence
from utils.equipment_vision_tasks import EQUIPMENT_VISION_FRESHNESS_TTL_MS, get_equipment_vision_task


def completed_candidate(record, flow, state):
    checkpoint = record.get("checkpoint") or {}
    blocks = flow.get("blocks") or []
    transitions = checkpoint.get("transitions") or []
    completed = [t.get("block_id") for t in transitions
                 if t.get("phase") == "skill" and t.get("outcome") == "completed" and t.get("success") is True]
    if not blocks or checkpoint.get("next_index") != len(blocks) or completed != [b["id"] for b in blocks]:
        raise ValueError("Equipment review retry requires every Skill to have completed exactly once")
    stored = record.get("workflow_result") or {}
    failure = (stored.get("data", {}).get("equipment_handoff") or {}).get("failure_code")
    recovery = record.get("recovery") or {}
    readonly_exception = (failure == "EQUIPMENT_WORKFLOW_EFFECT_UNKNOWN"
        and recovery.get("operation") == "terminal_review_only"
        and recovery.get("actuation_performed") is False)
    already_completed = record.get("lifecycle") == "COMPLETED" and stored.get("success") is True
    if not already_completed and (stored.get("success") or (failure != "EQUIPMENT_WORKFLOW_REVIEW_REQUIRED" and not readonly_exception)):
        raise ValueError("Equipment result is not awaiting terminal review")
    terminal = stored if already_completed else record.get("terminal_result")
    if terminal:
        candidate = AgentResult(**deepcopy(terminal))
    else:
        # Migration for older review records: re-derive the same handoff from
        # persisted, completed Skill evidence. No worker or actuator is invoked.
        data = deepcopy(stored["data"])
        projection = project_equipment_cycle_evidence(transitions=transitions, result_data=data)
        if not projection["handoff_eligibility"]["eligible"]:
            raise ValueError("Completed cycle evidence is insufficient")
        data.update(projection)
        export = projection["raw_data_export"]
        packet = {"schema": "utm_data_ready.v1", "status": "ready", "run_id": state.run_id,
            "specimen_id": record["identity"]["specimen_id"], "result_file": export["path"],
            "linux_path": export["path"], "artifact_id": export["artifact_id"],
            "sha256": export["sha256"], "row_count_probe": export["row_count"],
            "columns_probe": export["columns"], "evidence_refs": [export["path"]]}
        data["utm_data_ready"] = data["handoff_packet"] = packet
        data["equipment_handoff"] = {**packet, "status": "ready_for_analysis", "ready_for_analysis": True}
        data["equipment_result"].update(ok=True, status="verified_complete", failure_code=None)
        data["equipment_report"].update(status="verified_complete", data_acquisition=packet,
            decision={"handoff_status": "ready_for_analysis", "blocking_reasons": []})
        candidate = AgentResult(success=True, summary="Completed Equipment evidence restored for revalidation", data=data)
    export = candidate.data.get("raw_data_export") or {}
    if export:
        path = Path(export.get("path") or "")
        if not path.is_file() or not export.get("sha256"):
            raise ValueError("Completed CSV is missing")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != export["sha256"]:
                raise ValueError("Completed CSV changed")
    if not candidate.success:
        raise ValueError("Original workflow was not complete")
    return candidate


async def refresh_terminal_observations(agent, state, ctx, flow, result):
    """Refresh post-Skill sensors only; prohibit any worker/action replay."""
    flow_result = result.data.get("equipment_skill_flow_execution") or {}
    transitions = flow_result.get("transitions") or []
    for block in flow.get("blocks", []):
        binding = block.get("vision") or {}
        if not binding.get("enabled"):
            continue
        task = get_equipment_vision_task(binding["task_id"])
        if task.get("observation_timing") != "after_skill":
            continue
        source = agent._base_run_payload(state)["source_stage_context"]
        check = agent._equipment_vision_request(task_id=task["task_id"], state=state, source_stage_context=source)
        for observation_attempt in range(5):
            if any(getattr(state, key, False) for key in
                   ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
                raise ValueError("Terminal observation interrupted by safety control")
            response = await agent._call_tool(ctx, "vision.equipment_cross_check", {
                "run_id": state.run_id, "experiment_id": state.experiment_id,
                "runtime_mode": agent._effective_runtime_mode(state), "checks": [check],
                "source_stage_context": source, "duration_sec": float(task["timeout_s"]),
                "freshness_ttl_ms": EQUIPMENT_VISION_FRESHNESS_TTL_MS}, state=state)
            result.data.setdefault("terminal_observation_attempts", []).append({
                "block_id": block["id"], "attempt": observation_attempt + 1,
                "ok": response.get("ok"), "failure_code": response.get("failure_code"),
                "results": deepcopy(response.get("results") or [])})
            if (response.get("failure_code") != "UTM_INSUFFICIENT_TEMPORAL_EVIDENCE"
                    or observation_attempt == 4):
                break
            # A cold ROS observer may need time to produce samples. This is
            # bounded read-only warmup, never a retry of motion or a mismatch.
            await asyncio.sleep(0.5)
        # Older live observers stamped the envelope before ROS startup/probing.
        # Use their actual fresh sample time, never receipt time or a longer TTL.
        for item in response.get("results") or []:
            if item.get("source") != "ros_topic" or item.get("ok") is not True:
                continue
            samples = (item.get("evidence") or {}).get("samples") or []
            times = [agent._parse_vision_time(sample.get("timestamp")) for sample in samples
                     if sample.get("summary_fresh") is True]
            now = datetime.now(timezone.utc)
            times = [stamp for stamp in times if stamp is not None and stamp <= now]
            if times:
                observed_at = max(times)
                ttl = min(EQUIPMENT_VISION_FRESHNESS_TTL_MS, max(1, int(item.get("freshness_ttl_ms") or 5000)))
                item["request_started_at"] = item.get("timestamp")
                item["timestamp"] = observed_at.isoformat()
                item["expires_at"] = (observed_at + timedelta(milliseconds=ttl)).isoformat()
        if (not agent._equipment_vision_response_valid(response, check)
                or agent._equipment_vision_outcome(response) != "detected"):
            raise ValueError("Fresh Equipment terminal Vision evidence did not pass")
        item = response["results"][0]
        for transition in transitions:
            if transition.get("phase") == "vision" and transition.get("block_id") == block["id"]:
                result.data.setdefault("previous_terminal_observations", []).append(deepcopy(transition))
                transition.update(outcome="detected", failure_code=None, operator_attention=None,
                    confidence=item.get("confidence"), evidence_source=item.get("source"),
                    evidence=deepcopy(item.get("evidence") or {}), evidence_timestamp=item.get("timestamp"),
                    evidence_expires_at=item.get("expires_at"), vision_result=response,
                    summary="Fresh terminal observation after explicit Resume")
    # The report is a projection of the same execution, not a second source of
    # current truth. Keep other blocks (including their alarms) unchanged.
    report = result.data.get("equipment_report")
    if isinstance(report, dict) and "block_executions" in report:
        report["block_executions"] = deepcopy(transitions)
    # Superseded observations remain in the immutable previous attempt and this
    # attempt's audit events, not among the current Guardian gate inputs.
    history = {key: result.data[key] for key in
               ("previous_terminal_observations", "terminal_observation_attempts") if key in result.data}
    if history:
        record_tool_artifact("evidence_result", "equipment.terminal_observation_history", history)
        for key in history:
            result.data.pop(key)
    return result
