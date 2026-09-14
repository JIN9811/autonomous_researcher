"""
Fault injection integration tests.
"""

import pytest

from agents.base_agent import BaseAgent
from agents.registry import AgentRegistry
from logging_system.structured_logger import StructuredLogger
from orchestrator.langgraph_runtime import LangGraphRunLoop
from orchestrator.state import Mode, OrchestratorState, Stage


class NoExecutionAgent(BaseAgent):
    name = "manipulation_agent"

    async def run(self, state, ctx):
        raise AssertionError("Injected fault must prevent agent/device execution")


@pytest.mark.asyncio
async def test_fault_injection_emits_retry_or_error(tmp_path, handoff_no_external) -> None:
    # Exercise the actual stage exception/recovery boundary, not an unrelated
    # full experiment that may still be awaiting design or operator admission.
    state = OrchestratorState(
        run_id="fault-injection-test", experiment_id="fault-test",
        mode=Mode.FAULT_INJECTION,
        stage=Stage.MANIPULATION,
        fault_injection={"fault": "model_timeout", "stage": "manipulation"},
    )
    registry = AgentRegistry()
    registry.register(NoExecutionAgent())
    events = []
    runtime = LangGraphRunLoop(
        state=state, agent_registry=registry, ctx=object(),
        orchestrator_agent_name="orchestrator_agent",
        logger=StructuredLogger(tmp_path / "events.jsonl", tmp_path / "summary.log"),
        graph_config_path="graphs/configs/atr_closed_loop.yaml", on_event=events.append,
    )
    await runtime._execute_agent_stage(Stage.MANIPULATION)
    failures = [event for event in events if event.get("event_type") in {"retry", "fatal_error"}]
    assert len(failures) == 1
    assert failures[0]["payload"]["error"] == "Injected fault at stage=manipulation: model_timeout"
    assert state.agent_status["manipulation_agent"].success is False
