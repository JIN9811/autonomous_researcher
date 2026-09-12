"""Prompt presentation cannot change durable authorization or lose current denials."""
from copy import deepcopy
import json
import pytest
from types import SimpleNamespace
from pathlib import Path


def captured_current_guardian():
    # Exact current gate from the retained G8dnsY controlled prompt, index6.
    return json.loads((Path(__file__).parents[1] / "fixtures/orchestrator_current_guardian.json").read_text())


@pytest.mark.parametrize("malformation", ["absent_schema", "null_schema", "schema_object", "missing_decision", "unknown_current_field"])
def test_unversioned_or_malformed_current_guardian_is_not_complete(malformation):
    from orchestrator.handoff_projection import project_handoff_prompt
    raw = packet()
    gate = captured_current_guardian()
    if malformation == "absent_schema":
        del gate["schema"]
    elif malformation == "null_schema":
        gate["schema"] = None
    elif malformation == "schema_object":
        gate["schema"] = {"unsupported": "guardian_gate_result.v1"}
    elif malformation == "missing_decision":
        del gate["guardian_decision"]
    else:
        gate["unknown_current_requirement"] = "operator review still required"
    raw["evidence"]["boundary:result"]["guardian_context"] = gate
    with pytest.raises(ValueError, match="Unsupported current Guardian contract"):
        project_handoff_prompt(raw)


def test_history_is_referenced_separately_from_current_guardian_conditions():
    from orchestrator.handoff_projection import project_handoff_prompt, reference
    raw = packet()
    gate = captured_current_guardian()
    history = [{"status": "recovered", "failure_code": "HISTORICAL_ONLY_SENTINEL"}]
    gate["history"] = history
    gate["guardian_decision"]["historical_logs"] = history
    raw["evidence"]["boundary:result"]["guardian_context"] = gate
    public = project_handoff_prompt(raw)
    current = public["evidence"]["boundary:result"]["guardian_context"]
    assert "HISTORICAL_ONLY_SENTINEL" not in json.dumps(public)
    assert current["audit_refs"]["history"] == reference(history)
    assert current["guardian_decision"]["audit_refs"]["historical_logs"] == reference(history)
    assert current["guardian_decision"]["missing_evidence"] == ["MISSING_REQUIRED_INPUT", "artifact_refs"]
    assert current["guardian_contract"]["ok_for_bo"] is False


def test_real_guardian_producer_emits_the_supported_current_contract():
    from orchestrator.handoff_projection import guardian_contract
    from policies.guardian_gate import guardian_gate
    from orchestrator.state import OrchestratorState
    raw = guardian_gate(state=OrchestratorState(run_id="schema-producer", experiment_id="fixture"),
        stage="knowledge", phase="post", payload={}, agent="knowledge_agent")
    result = guardian_contract(raw)
    assert raw["schema"] == "guardian_gate_result.v1"
    assert result["guardian_contract"] == raw["guardian_contract"]
    assert result["guardian_decision"] == raw["guardian_decision"]


def test_explicit_guardian_absence_does_not_manufacture_a_current_contract():
    from orchestrator.handoff_projection import project_handoff_prompt
    raw = packet()
    raw["evidence"]["boundary:result"]["guardian_context"] = None
    current = project_handoff_prompt(raw)["evidence"]["boundary:result"]
    assert current["guardian_context"] is None
    assert current["required_admission"]["owner_admits_now"] is False


@pytest.mark.parametrize("field", ["guardian_contract", "guardian_gate"])
def test_unversioned_current_result_contract_cannot_bypass_guardian_validation(field):
    from orchestrator.handoff_projection import project_handoff_prompt
    raw = packet()
    gate = captured_current_guardian()
    current = gate["guardian_contract"] if field == "guardian_contract" else gate
    current.pop("schema_version" if field == "guardian_contract" else "schema")
    raw["evidence"]["boundary:result"]["result_data"][field] = current
    with pytest.raises(ValueError, match="Unsupported current Guardian contract"):
        project_handoff_prompt(raw)


def test_actual_current_guardian_contract_survives_projection_and_inspection():
    from orchestrator.handoff_projection import project_handoff_prompt, reference
    raw = packet()
    gate = captured_current_guardian()
    raw["evidence"]["boundary:result"]["guardian_context"] = gate
    raw["trace"] = [{"choice": {"tool": "inspect_context"}, "result": {"evidence": deepcopy(raw["evidence"])}}]
    public = project_handoff_prompt(raw)
    current = public["evidence"]["boundary:result"]["guardian_context"]
    assert current["guardian_decision"] == gate["guardian_decision"]
    assert current["guardian_contract"] == gate["guardian_contract"]
    assert current["risk_vector"] == gate["risk_vector"]
    assert current["guardian_decision"]["missing_evidence"] == ["MISSING_REQUIRED_INPUT", "artifact_refs"]
    assert current["guardian_decision"]["taxonomy_action"] == "block_bo_update"
    assert current["ok_for_bo"] is False and current["ok_for_next_stage"] is True
    inspected = public["trace"][0]["result"]["evidence"]["boundary:result"]
    assert inspected["same_evidence_ref"] == "boundary:result"
    assert inspected["full_evidence"] == reference(raw["evidence"]["boundary:result"])
    assert public["presentation"]["complete_current_contract_summary"] is True


def test_current_artifact_mappings_and_admission_conditions_are_not_filtered():
    from orchestrator.handoff_projection import project_handoff_prompt
    raw = packet()
    gate = captured_current_guardian()
    gate["guardian_contract"]["artifact_refs"] = [{"type": "stl", "path": "/retained/specimen.stl"}]
    admission = {"owner_admits_now": False, "minimum_quality": {"score": 0.9}, "missing_evidence": ["current-camera"]}
    raw["evidence"]["boundary:result"].update(guardian_context=gate, required_admission=admission)
    current = project_handoff_prompt(raw)["evidence"]["boundary:result"]
    assert current["guardian_context"]["guardian_contract"] == gate["guardian_contract"]
    assert current["required_admission"] == admission


def test_unsupported_admission_shape_cannot_be_labeled_complete():
    from orchestrator.handoff_projection import project_handoff_prompt
    raw = packet()
    raw["evidence"]["boundary:result"]["required_admission"] = ["unknown admission format"]
    with pytest.raises(ValueError, match="Unsupported current admission contract"):
        project_handoff_prompt(raw)


@pytest.mark.parametrize("field,value", [
    ("schema", "guardian_decision.v99"), ("required_evidence", {"hidden": "require approval"}),
    ("missing_evidence", "not a list"), ("risk_vector", {"hardware": "unknown"}),
    ("fallback_action", ["safe_stop"]), ("taxonomy_action", {"block_bo_update": True}),
])
def test_unsupported_current_guardian_condition_shape_fails_closed(field, value):
    from orchestrator.handoff_projection import project_handoff_prompt
    raw = packet()
    gate = captured_current_guardian()
    gate["guardian_decision"][field] = value
    raw["evidence"]["boundary:result"]["guardian_context"] = gate
    with pytest.raises(ValueError, match="Unsupported current Guardian contract"):
        project_handoff_prompt(raw)


def packet():
    return {"operation": "decide_orchestration", "scope": {"run_id": "r", "loop": 0, "stage": "equipment",
        "context": {"checkpoint": "c", "revision": 1, "stop": False, "setup_revision": 2,
            "authorization": {"run_id": "r", "mode": "test", "goal": "goal", "specimen": {
                "specimen_id": "s", "mesh": [1.2] * 10000}, "setup": {"revision": 2}},
            "request_payload": {"mesh": [1.2] * 10000}}},
        "context": {"handoff_candidates": ["analysis"], "required_evidence": ["boundary:result"]},
        "evidence": {"boundary:result": {"stage": "equipment", "next_stage": "analysis",
            "required_admission": {"owner_admits_now": False, "reason": "Required owner is busy"},
            "guardian_context": captured_current_guardian(),
            "result_data": {"equipment_handoff": {"status": "blocked", "blocking_reasons": ["CURRENT_BLOCK"]},
                "artifact_execution": {"old_history": [{"status": "failed", "failure_code": "RECOVERED_OLD_FAILURE"}]},
                "raw_curve": [[x, x] for x in range(10000)]}}},
        "trace": [], "tools": {"defer": {"condition": "text"}}, "response_schema": {}}


def test_projection_is_bounded_references_full_scope_and_preserves_current_denials():
    from orchestrator.handoff_projection import project_handoff_prompt, reference
    raw = packet()
    before = deepcopy(raw)
    public = project_handoff_prompt(raw)
    assert raw == before
    assert len(json.dumps(public).encode()) < 16000
    assert public["scope"]["full_scope"] == reference(raw["scope"])
    summary = public["evidence"]["boundary:result"]
    assert summary["full_evidence"] == reference(raw["evidence"]["boundary:result"])
    assert summary["required_admission"]["owner_admits_now"] is False
    assert summary["guardian_context"]["ok_for_bo"] is False
    assert summary["result_data"]["equipment_handoff"]["blocking_reasons"] == ["CURRENT_BLOCK"]
    assert "RECOVERED_OLD_FAILURE" not in json.dumps(public)


def test_inspection_trace_never_reintroduces_raw_payload_and_oversized_conditions_fail_closed():
    from orchestrator.handoff_projection import project_handoff_prompt
    raw = packet()
    raw["trace"] = [{"choice": {"tool": "inspect_context", "arguments": {"evidence_ids": ["boundary:result"]}},
        "result": {"evidence": deepcopy(raw["evidence"])}}] * 3
    assert len(json.dumps(project_handoff_prompt(raw)).encode()) < 16000
    raw["evidence"]["boundary:result"]["required_admission"]["reason"] = "Do not proceed " * 3000
    with pytest.raises(ValueError, match="budget"):
        project_handoff_prompt(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutate", [False, True])
async def test_model_projection_preserves_private_evidence_and_scope_checks(mutate):
    from agents.orchestrator_decision import decide_orchestration
    from orchestrator.handoff_projection import project_handoff_prompt
    raw = packet()
    scope = deepcopy(raw["scope"]["context"])
    state = SimpleNamespace(run_id="r", loop_count=0, stage=SimpleNamespace(value="equipment"))
    prompts, effects = [], []
    async def complete(task, prompt, **kwargs):
        public = json.loads(prompt)
        prompts.append(public)
        assert len(prompt.encode()) < 16000
        if mutate:
            scope["authorization"]["specimen"]["mesh"][0] = 9
        choice = {"tool": "inspect_context", "arguments": {"evidence_ids": ["boundary:result"]}} if len(prompts) == 1 else {
            "tool": "defer", "arguments": {"condition": "Required owner busy"}}
        return SimpleNamespace(model="controlled", text=json.dumps({**choice, "reason": "Current explicit denial",
            "evidence_refs": ["boundary:result"]}))
    async def inspect(args):
        effects.append("inspect")
        return {"evidence": deepcopy(raw["evidence"])}
    async def defer(args):
        effects.append("defer")
        return {"status": "deferred", **args}
    decision = await decide_orchestration(state, SimpleNamespace(complete=complete), context={
        "scope": deepcopy(scope), "current_scope": lambda: deepcopy(scope), "evidence": raw["evidence"],
        "required_evidence": ["boundary:result"], "prompt_projection": project_handoff_prompt},
        handlers={"inspect_context": inspect, "defer": defer})
    if mutate:
        assert decision["status"] == "failed" and effects == []
        assert "scope changed" in decision["reason"]
    else:
        assert decision["status"] == "deferred" and effects == ["inspect", "defer"]
        assert decision["trace"][0]["result"]["evidence"] == raw["evidence"]
        assert prompts[1]["trace"][0]["result"]["evidence"]["boundary:result"]["same_evidence_ref"] == "boundary:result"
