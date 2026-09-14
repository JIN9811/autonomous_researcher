"""Private, integrity-checked error-run checkpoints; never execute device work."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil


def run_directory(root, run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,191}", run_id):
        raise ValueError("Invalid recovery run ID")
    root = Path(root).resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("Invalid recovery run directory")
    return path


def _hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _check_boundary(snapshot, run_id):
    state = snapshot.get("state") or {}
    if (snapshot.get("is_running") or state.get("run_id") != run_id
            or state.get("stage") != "error"):
        raise ValueError("Recovery requires this exact stopped error run")
    if any(state.get(key) for key in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
        raise ValueError("Safety recovery must use the existing safety controls")
    if (state.get("run_metadata") or {}).get("active_safety_sources"):
        raise ValueError("Active safety sources prohibit error recovery")


def equipment_archive(root, run_id):
    run = run_directory(root, run_id)
    paths = sorted(run.glob("runtime/loops/loop-*/equipment_agent/attempt-*/result.json"))
    if not paths:
        raise ValueError("No archived Equipment result")
    result = json.loads(paths[-1].read_text())
    data = result.get("data") or {}
    handoff = data.get("equipment_handoff") or {}
    awaiting_review = result.get("status") == "failed" and handoff.get("failure_code") in {
        "EQUIPMENT_WORKFLOW_REVIEW_REQUIRED", "EQUIPMENT_WORKFLOW_EFFECT_UNKNOWN"}
    accepted_review = (result.get("status") == "completed" and handoff.get("ready_for_analysis") is True
        and handoff.get("status") == "ready_for_analysis"
        and ((data.get("equipment_report") or {}).get("llm_workflow_review") or {}).get("accepted") is True)
    if not awaiting_review and not accepted_review:
        raise ValueError("Only a completed Equipment workflow awaiting review is recoverable")
    # EFFECT_UNKNOWN is not recovery authority. prepare_error_resume requires
    # the durable terminal-review-only/no-actuation proof in completed_candidate.
    return paths[-1], data


def save_checkpoint(snapshot, planning, root, run_id):
    _check_boundary(snapshot, run_id)
    run = run_directory(root, run_id)
    result_path, data = equipment_archive(root, run_id)
    export = data.get("raw_data_export") or {}
    source = Path(export.get("path") or "")
    digest = export.get("sha256")
    if not source.is_file() or not digest or _hash(source) != digest:
        raise ValueError("CSV missing or changed; recovery checkpoint rejected")
    directory = run / "recovery"
    checkpoint = directory / "checkpoint.json"
    if checkpoint.exists():
        return read_checkpoint(root, run_id)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = directory / "compression.csv"
    shutil.copyfile(source, backup)
    backup.chmod(0o600)
    if _hash(backup) != digest:
        raise ValueError("CSV backup integrity mismatch")
    payload = {"schema": "atr.error_run_checkpoint.v1", "run_id": run_id,
        "snapshot": deepcopy(snapshot), "planning": deepcopy(planning),
        "csv_path": str(source.resolve()), "csv_sha256": digest,
        "result_path": str(result_path.resolve()), "result_sha256": _hash(result_path),
        "workflow_execution_id": data.get("equipment_workflow_execution_id")}
    encoded = json.dumps(payload, ensure_ascii=False).encode()
    envelope = {"sha256": hashlib.sha256(encoded).hexdigest(), "payload_json": encoded.decode()}
    temporary = directory / "checkpoint.tmp"
    temporary.write_text(json.dumps(envelope, ensure_ascii=False))
    temporary.chmod(0o600)
    temporary.replace(checkpoint)
    return read_checkpoint(root, run_id)


def read_checkpoint(root, run_id):
    run = run_directory(root, run_id)
    envelope = json.loads((run / "recovery/checkpoint.json").read_text())
    encoded = envelope["payload_json"].encode()
    if hashlib.sha256(encoded).hexdigest() != envelope.get("sha256"):
        raise ValueError("Recovery checkpoint integrity mismatch")
    payload = json.loads(encoded)
    _check_boundary(payload["snapshot"], run_id)
    if payload.get("run_id") != run_id:
        raise ValueError("Recovery run identity mismatch")
    if (_hash(payload["csv_path"]) != payload["csv_sha256"] or
            _hash(run / "recovery/compression.csv") != payload["csv_sha256"]):
        raise ValueError("CSV integrity mismatch")
    if _hash(payload["result_path"]) != payload["result_sha256"]:
        raise ValueError("Archived Equipment result integrity mismatch")
    return payload


def prepare_error_resume(controller):
    """Validate the durable completed boundary without changing device/run state."""
    from agents.equipment.agent import LabEquipmentAgent
    from agents.equipment.recovery import completed_candidate
    from agents.equipment.workflow import _scope, _describe, _digest
    from orchestrator.state import Mode, Stage
    from utils.equipment_runtime_service import EquipmentRuntimeService
    from utils.equipment_skill_flow import EquipmentSkillFlowStore
    snapshot = controller.snapshot()
    run_id = controller._state.run_id
    _check_boundary(snapshot, run_id)
    _, data = equipment_archive(controller._deps.run_root, run_id)
    archived_request = controller._state.run_metadata.get("archived_postprocessing_request")
    if archived_request:
        # This route cannot invoke Equipment. Validate the pinned data/image and
        # unchanged experiment inputs instead of a mutable device-review digest.
        saved = read_checkpoint(controller._deps.run_root, run_id)
        original = saved["snapshot"]["state"]
        from orchestrator.langgraph_runtime import compact_runtime_payload
        if (controller._state.experiment_id != original["experiment_id"]
                or controller._state.current_experiment_spec not in (
                    original["current_experiment_spec"], compact_runtime_payload(original["current_experiment_spec"]))):
            raise ValueError("Archived analysis experiment conditions changed")
        archived_clearance_capture(controller._state, archived_request,
            run_directory(controller._deps.run_root, run_id) / "recovery/archived_review")
        return saved["workflow_execution_id"]
    agent = controller._deps.agent_registry.get("equipment_agent")
    if not isinstance(agent, LabEquipmentAgent):
        raise ValueError("Installed Equipment implementation does not support this recovery contract")
    state = deepcopy(controller._state)
    state.stage = Stage.EQUIPMENT
    if controller._is_planning_test_spec(state.current_experiment_spec):
        state.mode = Mode.TEST
    flow = EquipmentSkillFlowStore(agent._SKILL_FLOW_PATH).get(
        state.current_experiment_spec.get("equipment_profile_id") or "utm_windows_v1")
    record = EquipmentRuntimeService(agent._RUNTIME_ROOT / "workflow_decisions").get(data["equipment_workflow_execution_id"])
    identity = record.get("identity") or {}
    if (identity.get("run_id") != run_id or identity.get("experiment_id") != state.experiment_id
            or record.get("lifecycle") not in {"ESCALATED", "COMPLETED"}
            or record.get("metadata", {}).get("scope_digest") != _digest([_scope(state), _describe(agent, state, flow)])):
        raise ValueError("Equipment recovery scope changed or no longer awaits review")
    completed_candidate(record, flow, state)
    return record["execution_id"]


def restore_compacted_owner_inputs(state, request, root):
    """Compatibility helper for already loaded bounded-recovery deployments."""
    from app.controller import MainController
    path = run_directory(root, state.run_id) / "recovery/after-readonly-equipment-retry.json"
    if not request.get("scope_snapshot_sha256") or _hash(path) != request["scope_snapshot_sha256"]:
        raise ValueError("Owner-input snapshot integrity mismatch")
    saved = json.loads(path.read_text())["state"]
    if saved["run_id"] != state.run_id or saved["loop_count"] != state.loop_count:
        raise ValueError("Owner-input snapshot scope mismatch")
    metadata = saved["run_metadata"]
    compact = MainController._compact_planning_run_metadata(metadata)
    for key in ("robot_task_result", "specimen_result"):
        current = state.run_metadata.get(key)
        if current != metadata.get(key) and current != compact.get(key):
            raise ValueError("Owner input changed beyond its compact UI projection")
        state.run_metadata[key] = deepcopy(metadata[key])


def reload_analysis_decisions(controller):
    """Idle-only data-decision leaf reload; no agent/device instance replacement."""
    import subprocess
    import sys
    from app.safe_hot_reload import assert_idle, reload_sources
    import agents.analysis.decisions as module
    import agents.core.knowledge.decision as knowledge_module
    assert_idle(controller)
    sources = {"agents.analysis.decisions": Path(module.__file__),
        "agents.core.knowledge.decision": Path(knowledge_module.__file__)}
    digests = {name: _hash(path) for name, path in sources.items()}
    root = Path(__file__).resolve().parents[1]
    checked = subprocess.run([sys.executable, "-m", "pytest", "tests/unit/test_analysis_decisions.py",
        "tests/unit/test_analysis_measurement_only.py", "tests/unit/test_knowledge_decision.py", "-q"],
        cwd=root, capture_output=True, timeout=30)
    if checked.returncode or any(_hash(path) != digests[name] for name, path in sources.items()):
        raise ValueError("Analysis decision reload validation failed")
    reload_sources(sources)


def prepare_clearance_review_retry(state, root):
    """Retry observation after a proven ended replay, never rearm its motion."""
    import math
    import time
    from orchestrator.state import Stage
    from utils.utm_clear_cycle import current_clear, matches
    clear = current_clear(state)
    proof = clear.get("replay_evidence") or {}
    previous_retry = state.run_metadata.get("clearance_review_recovery") or {}
    retry_wait = clear.get("state") == "waiting" and clear.get("success") is None and bool(previous_retry)
    original_failure = clear.get("state") == "error" and clear.get("failure_code") == "VISION_REVIEW_REQUIRED" and clear.get("success") is False
    if (state.stage not in {Stage.COMPLETE, Stage.ERROR}
            or any(getattr(state, k) for k in ("stop_requested", "safe_stop_requested", "emergency_stop_requested"))
            or state.run_metadata.get("active_safety_sources")
            or not (original_failure or retry_wait) or clear.get("replay_home_verified") is not True
            or clear.get("task_id") != "clear_utm_to_disposal" or not clear.get("replay_completed_at")
            or proof.get("ok") is not True or proof.get("replay_home_verified") is not True
            or proof.get("follower_closed") is not True or not proof.get("frames_sent")
            or proof.get("session_id") != clear.get("session_id") or not proof.get("evidence_token")):
        raise ValueError("Clearance retry requires a proven ended replay with only an unresolved Vision review")
    paths = sorted((run_directory(root, state.run_id) / "runtime/loops" /
        f"loop-{state.loop_count + 1:06d}/vision_agent").glob("attempt-*/result.json"))
    if not paths:
        raise ValueError("Archived clearance review is unavailable")
    archived = json.loads(paths[-1].read_text())
    data = archived.get("data") or {}
    second = data.get("utm_verification_2") or {}
    evidence = (second.get("record") or {}).get("evidence") or {}
    from utils.agent_artifact_archive import _public
    # Runtime archives redact evidence tokens. Compare the same public projection;
    # run_clear_vision still fetches the exact live replay session before capture.
    comparison = _public(clear)
    if retry_wait:
        if previous_retry.get("source_sha256") != _hash(paths[-1]) or previous_retry.get("session_id") != clear.get("session_id"):
            raise ValueError("Original clearance retry evidence changed")
        original = data.get("utm_clear_execution") or {}
        for key in ("state", "success", "failure_code", "pending_deadline_at"):
            comparison[key] = original.get(key)
    if (_public(data.get("utm_clear_execution")) != comparison or not matches(state, second)
            or second.get("session_id") != clear.get("session_id")
            or evidence.get("status") != "unknown" or evidence.get("registered") is not False
            or evidence.get("clear_confirmed") is not False
            or evidence.get("unknown_reason") != "capture_profile_material_or_registration_invalid"):
        raise ValueError("Archived clearance failure or execution scope changed")
    timeout = float(clear.get("pending_timeout_s") or 0)
    if not math.isfinite(timeout) or not 0 < timeout <= 180:
        raise ValueError("Invalid clearance observation retry bound")
    restored = state.model_copy(deep=True)
    restored.stage = Stage.ERROR
    retry = restored.run_metadata["utm_clear_execution"]
    retry.update(state="waiting", success=None, pending_deadline_at=time.time() + timeout)
    retry.pop("failure_code", None)
    retry.pop("visual_clearance_confirmed", None)
    restored.run_metadata["utm_clear_next_stage"] = "vision"
    restored.run_metadata["clearance_review_recovery"] = {
        "source_result": str(paths[-1]), "source_sha256": _hash(paths[-1]),
        "session_id": clear["session_id"], "requested_at": time.time(),
        "previous_deadline_at": clear.get("pending_deadline_at"), "actuation_performed": False}
    return restored


def restore_completed_equipment_handoff(controller, execution_id):
    """Rehydrate an already accepted result, not a new judgment about live devices."""
    from agents.equipment.recovery import completed_candidate
    from utils.equipment_runtime_service import EquipmentRuntimeService
    from utils.equipment_skill_flow import EquipmentSkillFlowStore
    from orchestrator.state import Stage
    agent = controller._deps.agent_registry.get("equipment_agent")
    record = EquipmentRuntimeService(agent._RUNTIME_ROOT / "workflow_decisions").get(execution_id)
    flow = EquipmentSkillFlowStore(agent._SKILL_FLOW_PATH).get(
        controller._state.current_experiment_spec.get("equipment_profile_id") or "utm_windows_v1")
    candidate = completed_candidate(record, flow, controller._state)
    accepted = (candidate.data.get("equipment_report") or {}).get("llm_workflow_review") or {}
    if record.get("lifecycle") != "COMPLETED" or accepted.get("accepted") is not True:
        raise ValueError("Clearance-only recovery requires an already accepted Equipment result")
    recovery_metadata = {key: deepcopy(value) for key, value in controller._state.run_metadata.items()
        if key in {"clearance_review_recovery", "recovery_design_limit", "robot_task_result", "specimen_result"}}
    controller._merge_planning_agent_data(Stage.EQUIPMENT, candidate.data)
    controller._state.run_metadata.update(recovery_metadata)
    controller._state.run_metadata["recovery_resume_stage"] = "vision"


def archived_clearance_capture(state, request, output_dir):
    """Re-evaluate immutable past evidence, never claim a current camera capture."""
    import math
    import time
    from PIL import Image
    from utils.utm_clear_cycle import current_clear, matches
    from utils.utm_specimen_presence import _inspect_clear_at
    recovery = state.run_metadata.get("clearance_review_recovery") or {}
    clear = current_clear(state)
    source = Path(recovery.get("source_result") or "")
    if (not matches(state, request) or request.get("requested_by") != "operator"
            or request.get("session_id") != clear.get("session_id")
            or request.get("stop_after_cycle") != state.loop_count + 2
            or not source.is_file() or _hash(source) != request.get("source_sha256")
            or recovery.get("source_sha256") != request.get("source_sha256")
            or clear.get("replay_home_verified") is not True
            or (clear.get("replay_evidence") or {}).get("follower_closed") is not True):
        raise ValueError("Historical review requires explicit same-run authorization and immutable completed replay")
    archived = json.loads(source.read_text())["data"]["utm_verification_2"]
    evidence = archived["record"]["evidence"]
    if not matches(state, archived) or not matches(state, evidence) or evidence.get("session_id") != clear["session_id"]:
        raise ValueError("Historical image identity differs")
    raw = Path(evidence.get("raw_frame_path") or "").resolve()
    images = (evidence.get("vision_decision") or {}).get("images") or []
    proof = next((v for v in images if v.get("label") == "raw frame" and Path(v.get("path", "")).resolve() == raw), {})
    if not raw.is_file() or not proof.get("sha256") or _hash(raw) != proof["sha256"]:
        raise ValueError("Original image integrity mismatch")
    stamp = float(evidence.get("frame_timestamp", 0))
    after = float(clear.get("replay_completed_at", 0))
    if not math.isfinite(stamp) or not 0 < after < stamp <= time.time() or evidence.get("after_timestamp") != after:
        raise ValueError("Image is not from after this completed removal")
    facts = {k: evidence[k] for k in ("run_id", "loop_id", "specimen_id", "session_id", "frame_timestamp",
        "after_timestamp", "topic", "camera_profile_id", "material") if k in evidence}
    facts.update(historical_review=True, current_physical_clearance=False,
        source_result=str(source), source_sha256=request["source_sha256"],
        source_image_sha256=proof["sha256"], reviewed_at=time.time(), actuation_performed=False)
    with Image.open(raw) as image:
        return _inspect_clear_at(image.convert("RGB"), output_dir=output_dir,
            specimen_id=evidence["specimen_id"], frame_id=evidence["frame_id"],
            evidence=facts, observation_time=stamp)


class PostprocessingTools:
    """Run-local allowlist: a changed graph still cannot dispatch device tools."""
    def __init__(self, original):
        self.original = original

    def call(self, name, payload):
        if name == "experiment.benchmark":
            from experiments.api import ExperimentRuntime
            from experiments.benchmark import run_benchmark
            execution = (payload.get("request") or {}).get("execution") or {}
            if execution.get("bridge") != "virtual" or execution.get("dry_run") is not True or execution.get("allow_physical"):
                raise ValueError("Only the existing nonphysical BO benchmark is allowed")
            return run_benchmark(dict(payload), evaluator=ExperimentRuntime(tools=self).evaluate)
        if name != "geometry.generate_metamaterial_stl":
            raise ValueError(f"Device/tool dispatch disabled during archived-data recovery: {name}")
        return self.original.call(name, payload)

    def list_tools(self):
        return ["geometry.generate_metamaterial_stl", "experiment.benchmark"]

    def resource(self, name):
        return None

    def queue_status(self):
        return self.original.queue_status()


async def continue_archived_postprocessing(controller, *, first_spec, design_constraints, start_cycle):
    """One authorized offline tail plus one Design, without fabrication or device I/O."""
    import time
    from dataclasses import replace
    from orchestrator.state import Stage
    from utils.utm_clear_cycle import current_clear, _result
    from agents.vision.decision import review_visual_evidence, decision_allows_existing_gate
    from agents.manipulation.decision import review_manipulation_result, allows
    state = controller._state
    request = state.run_metadata["archived_postprocessing_request"]
    if start_cycle != state.loop_count + 1:
        raise ValueError("Archived continuation cycle changed")
    directory = run_directory(controller._deps.run_root, state.run_id) / "recovery/archived_review"
    capture = archived_clearance_capture(state, request, directory)
    original_context = controller._deps.agent_context
    context = replace(original_context, tools=PostprocessingTools(original_context.tools))
    controller._deps.agent_context = context
    try:
        if any(getattr(state, k) for k in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
            raise ValueError("Recovery interrupted by safety controls")
        if request.get("phase") == "design_only":
            return await finish_archived_design(controller, request=request, first_spec=first_spec,
                design_constraints=design_constraints, start_cycle=start_cycle)
        state.stage = Stage.VISION
        await controller._emit_control_event("recovery.archived_review", "Reviewing saved post-removal image; no camera/device I/O", capture)
        decision = await review_visual_evidence(state, context, capture, "clearance")
        capture["vision_decision"] = decision
        if not decision_allows_existing_gate(decision) or not capture.get("clear_confirmed"):
            raise ValueError("Saved clearance image was not accepted by Vision")
        execution = current_clear(state)
        replay = {**execution, "ok": True, "status": "COMPLETED", "exit_code": 0,
            "historical_review": True, "actuation_performed": False}
        task = await review_manipulation_result(state, context, "clear_utm_to_disposal", replay, capture,
            execution_ended=True, vision_accepted=True)
        record = {"capture": capture, "manipulation_decision": task}
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "review.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
        if not allows(task) or any(getattr(state, k) for k in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")):
            raise ValueError("Archived clearance task review was not accepted or operator stopped")
        execution.update(state="done", success=True, visual_clearance_confirmed=True,
            historical_review=True, current_physical_clearance=False, manipulation_result_decision=task)
        result = _result(execution, capture=capture, summary="Archived post-removal image accepted for data postprocessing only")
        result.data["vision_decision"] = decision
        controller._merge_planning_agent_data(Stage.VISION, result.data)
        await controller._emit_control_event("recovery.archived_review.accepted", result.summary, result.data)
        total = max(start_cycle + 1, controller._planning_cycle_limit(first_spec))
        tail = await controller._run_planning_loop_tail(first_spec, cycle_index=start_cycle,
            total_cycles=total, resume_stage=Stage.ANALYSIS)
        if not tail.get("ok") or tail.get("decision") != "continue":
            return tail
        return await finish_archived_design(controller, request=request, first_spec=first_spec,
            design_constraints=design_constraints, start_cycle=start_cycle)
    finally:
        controller._deps.agent_context = original_context


async def finish_archived_design(controller, *, request, first_spec, design_constraints, start_cycle):
    """Draft only: retain physical Guardian holds, never resume equipment."""
    import time
    from orchestrator.state import Stage
    state = controller._state
    if not isinstance(controller._deps.agent_context.tools, PostprocessingTools):
        raise ValueError("Draft recovery requires the non-actuating tool guard")
    run = run_directory(controller._deps.run_root, state.run_id)
    if request.get("phase") == "design_only":
        path = (run / request["bo_result_relative"]).resolve()
        if not path.is_relative_to(run) or _hash(path) != request.get("bo_result_sha256"):
            raise ValueError("BO draft source changed")
        archived = json.loads(path.read_text())
        data = archived.get("data") or {}
        bo = data.get("bo_result") or {}
        if (archived.get("status") != "completed" or bo.get("ok") is not True
                or bo.get("run_id") != state.run_id or bo.get("experiment_id") != state.experiment_id
                or not data.get("experiment_spec_update")):
            raise ValueError("No accepted same-run BO draft candidate")
        state.run_metadata["bo_recommended_constraints"] = deepcopy(data["experiment_spec_update"])
        if data.get("next_design_request"):
            state.run_metadata["next_design_request"] = deepcopy(data["next_design_request"])
        state.run_metadata["draft_only_with_physical_hold"] = {
            "guardian": deepcopy(state.run_metadata.get("guardian", {})),
            "bo_result_sha256": request["bo_result_sha256"], "equipment_authorized": False}
        state.loop_count = start_cycle
    total = max(start_cycle + 1, controller._planning_cycle_limit(first_spec))
    constraints = controller._closed_loop_static_design_constraints(design_constraints)
    spec = await controller._run_planning_design_stage(previous_spec=dict(first_spec),
        design_constraints=constraints, cycle_index=start_cycle + 1, total_cycles=total, emit_handoff=True)
    controller._store_planning_resume_context(goal=state.active_goal, current_spec=spec,
        design_constraints=constraints, cycle_index=start_cycle + 1, total_cycles=total, phase="specimen")
    state.stage, state.is_paused = Stage.DESIGN, True
    state.run_metadata["completed_recovery_design_limit"] = {
        "run_id": state.run_id, "cycle_index": start_cycle + 1, "requested_by": "operator",
        "reached": True, "completed_at": time.time()}
    state.run_metadata.pop("recovery_design_limit", None)
    state.run_metadata.pop("archived_postprocessing_request", None)
    state.run_metadata["completed_archived_postprocessing"] = request
    for name in ("archived_postprocessing.json", "stop_after_design.json"):
        source = run / "recovery" / name
        if source.is_file(): source.replace(run / "recovery" / (name + ".consumed"))
    return {"ok": True, "decision": "paused_after_design", "specimen_id": spec.get("specimen_id"),
        "message": "Requested next design completed; no fabrication or equipment dispatched."}


def restore_checkpoint(controller, run_id):
    """Restore an error boundary only. Operator Resume remains a separate action."""
    from logging_system.logger_factory import build_logger_bundle
    from orchestrator.state import OrchestratorState, Stage
    if controller.snapshot().get("is_running") or controller._state.stage not in {Stage.IDLE, Stage.ERROR, Stage.COMPLETE}:
        raise ValueError("Cannot replace an active or nonterminal run")
    if controller._state.stage in {Stage.ERROR, Stage.COMPLETE} and controller._state.run_id != run_id:
        raise ValueError("Cannot replace another error run")
    if any(getattr(controller._state, k) for k in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")) or controller._active_safety_sources():
        raise ValueError("Safety recovery is required before restore")
    saved = read_checkpoint(controller._deps.run_root, run_id)
    planning = saved.get("planning") or {}
    session_id = planning.get("planning_session_id")
    transcript = Path(planning.get("transcript_path") or "").resolve()
    if (not session_id or not transcript.is_relative_to(Path(controller._deps.run_root).resolve())
            or transcript.name != "live_planning_transcript.jsonl" or not transcript.is_file()):
        raise ValueError("Original planning transcript is unavailable")
    from orchestrator.experimental_setup import SetupStore
    from app.controller import PLANNING_TRANSCRIPT_MEMORY_LIMIT
    from collections import deque
    # Validate session ownership before replacing state; never reuse startup's cache.
    setup_store = SetupStore(transcript.parent, session_id)
    messages = deque(maxlen=PLANNING_TRANSCRIPT_MEMORY_LIMIT)
    message_total = 0
    with transcript.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Invalid saved planning transcript")
                messages.append(message)
                message_total += 1
    # A same-run ended disposal must never roll back to the pre-disposal checkpoint.
    # Its current completion facts are retained; fresh camera and both agent
    # reviews are still mandatory after Resume. Unrelated COMPLETE runs reject.
    from utils.utm_clear_cycle import current_clear
    request_path = run_directory(controller._deps.run_root, run_id) / "recovery/archived_postprocessing.json"
    raw_clear = controller._state.run_metadata.get("utm_clear_execution") or {}
    historical_done = raw_clear.get("historical_review") is True and raw_clear.get("success") is True
    if historical_done and request_path.is_file():
        restored = controller._state.model_copy(deep=True)
        restored.stage = Stage.ERROR
        request = json.loads(request_path.read_text())
        if restored.loop_count != request.get("loop_id"):
            if (controller._state.stage != Stage.COMPLETE or restored.loop_count != request.get("loop_id", -2) + 1
                    or raw_clear.get("loop_id") != request["loop_id"]
                    or restored.current_experiment_spec.get("specimen_id") != request.get("specimen_id")):
                raise ValueError("Cannot rewind a different or newly started cycle")
            restored.run_metadata["archived_cycle_cursor_recovery"] = {
                "from_loop": restored.loop_count, "to_loop": request["loop_id"],
                "reason": "Resume unfinished nonphysical tail of the same specimen; retain all attempts"}
            restored.loop_count = request["loop_id"]
        source = run_directory(controller._deps.run_root, run_id) / request["source_result_relative"]
        if not source.resolve().is_relative_to(run_directory(controller._deps.run_root, run_id)):
            raise ValueError("Historical review path outside this run")
        restored.run_metadata["clearance_review_recovery"] = {"source_result": str(source),
            "source_sha256": request["source_sha256"]}
    elif controller._state.stage == Stage.COMPLETE or current_clear(controller._state):
        restored = prepare_clearance_review_retry(controller._state, controller._deps.run_root)
    else:
        restored = OrchestratorState.model_validate(saved["snapshot"]["state"])
    limit_path = run_directory(controller._deps.run_root, run_id) / "recovery/stop_after_design.json"
    if limit_path.is_file():
        limit = json.loads(limit_path.read_text())
        if (limit.get("run_id") != run_id or limit.get("requested_by") != "operator"
                or limit.get("cycle_index") != restored.loop_count + 2):
            raise ValueError("Requested next-design limit does not match this run/cycle")
        restored.run_metadata["recovery_design_limit"] = limit
    previous = controller._state
    controller._state = restored
    try:
        request_path = run_directory(controller._deps.run_root, run_id) / "recovery/archived_postprocessing.json"
        if request_path.is_file():
            request = json.loads(request_path.read_text())
            archived_clearance_capture(restored, request, request_path.parent / "archived_review")
            restored.run_metadata["archived_postprocessing_request"] = request
        execution_id = prepare_error_resume(controller)
        if restored.run_metadata.get("clearance_review_recovery"):
            restore_completed_equipment_handoff(controller, execution_id)
        if request_path.is_file():
            request = json.loads(request_path.read_text())
            archived_clearance_capture(restored, request, request_path.parent / "archived_review")
            restored.run_metadata["archived_postprocessing_request"] = request
            reload_analysis_decisions(controller)
    except Exception:
        controller._state = previous
        raise
    controller._logger_bundle = build_logger_bundle(run_id=run_id,
        run_root=controller._deps.run_root, logging_config=controller._deps.logging_config)
    controller._planning_session_id = session_id
    controller._canonical_planning_transcript_path = transcript
    controller._experimental_setup_store = setup_store
    controller._experimental_setup_session = session_id
    controller._planning_messages = list(messages)
    controller._planning_message_total = message_total
    controller._planning_bootstrapped = True
    return {"ok": True, "run_id": run_id, "stage": "error", "status": "restored_awaiting_resume",
            "csv_sha256": saved["csv_sha256"], "actuation_performed": False}


if __name__ == "__main__":
    import argparse
    from urllib.request import urlopen
    parser = argparse.ArgumentParser(description="Preserve a stopped error run without changing the server")
    parser.add_argument("run_id")
    parser.add_argument("--url", default="http://127.0.0.1:7860")
    parser.add_argument("--root", default="runs")
    args = parser.parse_args()
    def get(path):
        with urlopen(args.url + path, timeout=20) as response:
            return json.load(response)
    snapshot = get("/api/state")
    planning = get("/api/planning/session")
    # Reject a boundary that moved while the transcript was being captured.
    current = get("/api/state")
    _check_boundary(current, args.run_id)
    if current["state"] != snapshot["state"]:
        raise ValueError("Run state changed during checkpoint capture; retry")
    saved = save_checkpoint(snapshot, planning, args.root, args.run_id)
    print(json.dumps({"run_id": saved["run_id"], "csv_sha256": saved["csv_sha256"],
                      "checkpoint": str(run_directory(args.root, args.run_id) / "recovery/checkpoint.json")}))
