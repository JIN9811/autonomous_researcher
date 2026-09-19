"""Recheck a terminal Guardian hold after proven same-check image recovery."""
import ast
import asyncio
from copy import deepcopy
import inspect
import json
from pathlib import Path

from orchestrator.state import Stage
from policies.guardian_gate_lifecycle import resolve_image_rechecks


def validate_boundary(controller):
    state = controller._state
    if controller.snapshot().get("is_running") or controller._planning_handoff_active():
        raise ValueError("Guardian recovery requires an inactive run")
    if state.stage != Stage.COMPLETE or controller._active_safety_sources() or any(
        getattr(state, key) for key in ("stop_requested", "safe_stop_requested", "emergency_stop_requested")
    ):
        raise ValueError("Guardian recovery cannot release safety controls")
    guardian = state.run_metadata.get("guardian") or {}
    if guardian.get("reason") != "Guardian graph-wide gate requested safe stop: SYSTEM_SAFE_STOP_RECOMMENDED":
        raise ValueError("Not a terminal graph-gate review")
    context = state.run_metadata.get("_planning_resume_context") or {}
    cycle = int(context.get("cycle_index") or 0)
    if not cycle or cycle != state.loop_count or cycle >= int(context.get("total_cycles") or 0):
        raise ValueError("No unfinished cycle-series continuation")
    return state.run_id, state.experiment_id, cycle


def reconciled_gates(state, log_path):
    """Recover identities lost by older UI projections from matching audit entries."""
    audit = {}
    with Path(log_path).open() as stream:
        for line in stream:
            event = json.loads(line)
            payload = event.get("payload") or {}
            gate = payload.get("guardian_gate") or {}
            if gate.get("run_id") != state.run_id or not gate.get("gate_id"):
                continue
            gate = deepcopy(gate)
            if payload.get("utm_verification_2") or payload.get("utm_clear_execution"):
                gate.setdefault("audit_log", {})["check_scope"] = "utm_clearance"
            elif payload.get("utm_verification_1"):
                gate.setdefault("audit_log", {})["check_scope"] = "utm_placement"
            old = audit.get(gate["gate_id"], {})
            audit[gate["gate_id"]] = {**old, **gate, "audit_log": {**old.get("audit_log", {}), **gate.get("audit_log", {})}}
    gates = deepcopy(state.run_metadata.get("guardian_gates") or [])
    for index, gate in enumerate(gates):
        candidates = [full for full in audit.values() if all(
            full.get(key) == gate.get(key) for key in
            ("stage", "phase", "decision", "reason_code", "risk_score", "created_at")
        ) and (not gate.get("gate_id") or gate["gate_id"] == full["gate_id"])]
        if len(candidates) == 1:
            gates[index] = candidates[0]
    incidents = deepcopy(state.run_metadata.get("incident_records") or [])
    resolve_image_rechecks(gates, incidents)
    blocked = [g for g in gates if g.get("decision") in {"block", "safe_stop"}]
    if not blocked or any((g.get("audit_log") or {}).get("lifecycle") != "resolved" or not (g.get("audit_log") or {}).get("resolved_by") for g in blocked):
        raise ValueError("A blocking gate lacks a proven successful matching image recheck")
    return gates, incidents


def prepare(controller):
    """Prepare only; retain state, artifacts and device sessions, never actuate."""
    from app.run_recovery import run_directory
    from app.safe_hot_reload import reload_sources, stage_resume
    from agents.core.guardian.agent import GuardianAgent
    import policies.guardian_gate as gate_module

    boundary = validate_boundary(controller)
    root = Path(__file__).resolve().parents[1]
    gates, incidents = reconciled_gates(controller._state,
        run_directory(controller._deps.run_root, boundary[0]) / "structured.jsonl")
    # Compile just the pure gate-summary method. Keep the active agent instance.
    current = GuardianAgent._resolve_graph_gate_pressure
    path = root / "agents/core/guardian/agent.py"
    tree = ast.parse(path.read_text())
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GuardianAgent")
    node = next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == current.__name__)
    node.decorator_list = []
    namespace = dict(current.__globals__)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    candidate = namespace[current.__name__]
    if inspect.signature(candidate) != inspect.signature(current):
        raise ValueError("Guardian summary signature changed; restart required")
    resume, new_resume = stage_resume(root / "app/controller.py")
    if validate_boundary(controller) != boundary:
        raise ValueError("Guardian recovery boundary changed")
    reload_sources({"policies.guardian_gate": Path(gate_module.__file__)})
    current.__code__ = candidate.__code__
    resume.__code__ = new_resume.__code__
    controller._state.run_metadata["guardian_gates"] = gates
    controller._state.run_metadata["incident_records"] = incidents
    controller._state.run_metadata["guardian_review_retry"] = {
        "run_id": boundary[0], "experiment_id": boundary[1], "cycle": boundary[2], "status": "ready"}
    return {"ok": True, "status": "guardian_recheck_ready", "run_id": boundary[0], "actuation_performed": False}


async def resume_review(controller):
    async with controller._error_resume_lock:
        marker = controller._state.run_metadata.get("guardian_review_retry") or {}
        if marker.get("status") == "running" and controller._planning_handoff_active():
            return {"ok": True, "status": "already_resuming"}
        boundary = validate_boundary(controller)
        if (marker.get("run_id"), marker.get("experiment_id"), marker.get("cycle")) != boundary or marker.get("status") != "ready":
            raise ValueError("Guardian recovery identity changed")
        from agents.core.guardian.agent import GuardianAgent
        if GuardianAgent._resolve_graph_gate_pressure(controller._state)["status"] == "fail":
            raise ValueError("An unresolved Guardian gate still blocks recovery")
        rejection = await controller._plc_service_start_rejection()
        if rejection:
            return rejection
        context = controller._state.run_metadata["_planning_resume_context"]
        controller._state.is_paused = False
        marker["status"] = "running"
        async def continue_review():
            # The one-shot recovery has been consumed. Later Pause/Resume in
            # subsequent cycles must use the ordinary runtime controls.
            marker["status"] = "consumed"
            try:
                return await controller._run_planning_cycle_series(
                    first_spec=controller._state.current_experiment_spec,
                    design_constraints=context.get("design_constraints") or {},
                    start_cycle=boundary[2], resume_tail_stage=Stage.GUARDIAN)
            finally:
                marker["status"] = "finished"
        controller._set_planning_handoff_task(asyncio.create_task(continue_review()))
        await controller._emit_control_event("run_resume", "Rechecking Guardian; completed device stages will not repeat",
            {"run_id": boundary[0], "cycle": boundary[2], "resume_stage": "guardian"})
        return {"ok": True, "status": "resuming", "run_id": boundary[0], "resume_stage": "guardian"}
