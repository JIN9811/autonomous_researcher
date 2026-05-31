from orchestrator.state import Mode, OrchestratorState, Stage
from orchestrator.supervisor import (
    build_loop_reflection,
    build_mission_contract,
    build_orchestration_plan,
    build_orchestrator_followup,
    build_orchestrator_parallel_check,
    build_orchestrator_parallel_check_batch,
    build_orchestrator_handoff_packet,
    normalize_operator_intent,
)


def _state() -> OrchestratorState:
    return OrchestratorState(
        run_id="run-supervisor-test",
        experiment_id="exp-supervisor-test",
        mode=Mode.TEST,
        stage=Stage.VISION,
        active_goal="test supervisor loop",
        current_experiment_spec={"specimen_id": "sp-supervisor"},
    )


def test_operator_intent_state_machine_distinguishes_live_test_and_status() -> None:
    assert normalize_operator_intent("실험 수행")["intent"] == "start_live_run"
    assert normalize_operator_intent("테스트 모드, 실제 출력")["intent"] == "start_dry_run"
    assert normalize_operator_intent("현재 상태 알려줘")["intent"] == "request_status"


def test_orchestrator_followup_handoff_and_reflection_contracts() -> None:
    state = _state()
    followup = build_orchestrator_followup(
        state=state,
        stage=Stage.VISION,
        trigger="post_stage",
        payload={"vision_signal": {"confidence": 0.62, "evidence_refs": ["artifact://frame"]}},
        next_stage=Stage.MANIPULATION,
    )
    assert followup["schema"] == "orchestrator_followup.v1"
    assert followup["stage"] == "vision"
    assert followup["concerns"]
    assert followup["next_agent"] == "manipulation_agent"

    handoff = build_orchestrator_handoff_packet(
        state=state,
        from_stage=Stage.VISION,
        to_stage=Stage.MANIPULATION,
        result_payload={"vision_signal": {"schema": "vision_signal.v1", "signal_id": "sig-1", "evidence_refs": ["artifact://frame"]}},
    )
    assert handoff["schema"] == "handoff_packet.v1"
    assert handoff["producer_agent"] == "orchestrator_agent"
    assert handoff["consumer_agent"] == "manipulation_agent"
    assert "robot_task_result" in handoff["required_outputs"]

    state.run_metadata["orchestrator_followups"] = [followup]
    state.run_metadata["orchestrator_handoff_packets"] = [handoff]
    reflection = build_loop_reflection(state=state, guardian_payload={"decision": "continue"}, next_stage=Stage.DESIGN)
    assert reflection["schema"] == "loop_reflection.v1"
    assert reflection["guardian_decision"] == "continue"
    assert "store_orchestrator_followups" in reflection["knowledge_updates"]


def test_orchestration_plan_compiles_route_parallel_checks_and_contract() -> None:
    state = _state()
    state.stage = Stage.DESIGN
    state.current_experiment_objective = {"objective_type": "specific_energy_absorption"}
    intent = normalize_operator_intent("테스트 모드, 실제 출력")

    contract = build_mission_contract(state=state, operator_intent=intent)
    plan = build_orchestration_plan(state=state, operator_intent=intent)

    assert contract["schema"] == "experiment_contract.v1"
    assert contract["operator_intent"] == "start_dry_run"
    assert contract["requires_guardian_gate"] is True
    assert plan["schema"] == "orchestration_plan.v1"
    assert plan["route"][0]["stage"] == "design"
    assert any(step["stage"] == "guardian" for step in plan["route"])
    assert "knowledge.retrieve_prior_failures" in plan["parallelizable_checks"]
    assert "vision.verify_print_or_fixture_state" in plan["serial_physical_actions"]
    assert "analysis_bo_handoff.json" in plan["expected_artifacts"]


def test_parallel_check_batch_records_read_only_evidence() -> None:
    state = _state()
    state.device_health = {"printer": "ready", "robot": "warning:camera_check"}
    state.run_metadata["incident_records"] = [{"incident_id": "inc-1", "reason_code": "DEVICE_UNHEALTHY"}]
    plan = build_orchestration_plan(state=state)
    checks = [
        build_orchestrator_parallel_check(state=state, check_id="knowledge.retrieve_prior_failures", plan_id=plan["plan_id"]),
        build_orchestrator_parallel_check(state=state, check_id="guardian.preflight_devices", plan_id=plan["plan_id"]),
    ]
    batch = build_orchestrator_parallel_check_batch(state=state, plan=plan, checks=checks, stage=Stage.VISION)

    assert all(item["schema"] == "orchestrator_parallel_check.v1" for item in checks)
    assert all(item["read_only"] is True for item in checks)
    assert batch["schema"] == "orchestrator_parallel_checks.v1"
    assert batch["execution_mode"] == "asyncio.gather/read_only"
    assert batch["check_count"] == 2
    assert batch["status_counts"]
