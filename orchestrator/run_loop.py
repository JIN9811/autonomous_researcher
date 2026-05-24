"""
File purpose:
- Execute the main LangGraph-style orchestration loop with event streaming.

Key classes/functions:
- RunLoop

Inputs/outputs:
- Input: state, agent registry, graph, and runtime context
- Output: updated state and emitted run events

Dependencies:
- asyncio
- agents.registry.AgentRegistry
- logging_system.structured_logger.StructuredLogger

Modification guide:
- Safe places to edit: event payload fields and interval behavior
- Risky places to edit: stage progression and retry error handling
- Related files: app/controller.py, orchestrator/transitions.py
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable

from agents.base_agent import AgentContext
from agents.registry import AgentRegistry
from logging_system.error_logger import log_error
from logging_system.event_logger import log_agent_event, log_system_event
from logging_system.structured_logger import StructuredLogger
from orchestrator.graph import OrchestrationGraph
from orchestrator.router import stage_to_agent
from orchestrator.state import AgentRuntimeStatus, OrchestratorState, Stage
from policies.recovery_policy import recovery_action
from policies.retry_policy import bump_retry, should_retry
from policies.safe_stop_policy import safe_stop_reason
from policies.validation_policy import validate_agent_output
from utils.ids import make_event_id

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class RunLoop:
    """Main orchestration engine with explicit stages and transitions."""

    def __init__(
        self,
        *,
        state: OrchestratorState,
        agent_registry: AgentRegistry,
        orchestrator_agent_name: str,
        ctx: AgentContext,
        graph: OrchestrationGraph,
        logger: StructuredLogger,
        max_retry_per_stage: int = 2,
        interval_seconds: float = 1.25,
        on_event: EventCallback | None = None,
    ) -> None:
        self._state = state
        self._agent_registry = agent_registry
        self._orchestrator_agent_name = orchestrator_agent_name
        self._ctx = ctx
        self._graph = graph
        self._logger = logger
        self._max_retry_per_stage = max_retry_per_stage
        self._interval_seconds = interval_seconds
        self._on_event = on_event

    async def _dispatch_event(self, event: dict[str, Any]) -> None:
        if not self._on_event:
            return
        maybe = self._on_event(event)
        if inspect.isawaitable(maybe):
            await maybe

    async def _emit(
        self,
        *,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
        level: str = "INFO",
    ) -> None:
        payload = payload or {}
        log_system_event(
            self._logger,
            run_id=self._state.run_id,
            level=level,
            event_type=event_type,
            message=message,
            payload=payload,
        )
        event = {
            "event_id": make_event_id(),
            "run_id": self._state.run_id,
            "experiment_id": self._state.experiment_id,
            "timestamp_stage": self._state.stage.value,
            "event_type": event_type,
            "level": level,
            "message": message,
            "payload": payload,
            "state": self._state.model_dump(mode="json"),
        }
        await self._dispatch_event(event)

    def _ensure_agent_status(self, name: str) -> AgentRuntimeStatus:
        if name not in self._state.agent_status:
            self._state.agent_status[name] = AgentRuntimeStatus(mode=self._state.mode.value)
        return self._state.agent_status[name]

    def _merge_agent_data(self, stage: Stage, data: dict[str, Any]) -> None:
        if "experiment_spec" in data:
            self._state.current_experiment_spec = data["experiment_spec"]
        if "experiment_objective" in data:
            self._state.current_experiment_objective = data["experiment_objective"]
        if "experiment_evaluation" in data and isinstance(data["experiment_evaluation"], dict):
            self._state.experiment_evaluations.append(data["experiment_evaluation"])
        specimen_result = data.get("specimen_result") if isinstance(data.get("specimen_result"), dict) else {}
        if isinstance(specimen_result.get("experiment_evaluation"), dict):
            self._state.experiment_evaluations.append(specimen_result["experiment_evaluation"])
        if "observation" in data:
            self._state.latest_observations = data["observation"]
        if "analysis" in data:
            self._state.latest_analysis.update(data["analysis"])
        if "sarm" in data:
            self._state.latest_analysis["sarm"] = data["sarm"]
        if "manipulation" in data:
            self._state.latest_analysis["last_grasp_score"] = float(data["manipulation"].get("grasp_score", 0.0))
            if "sarm" in data:
                self._state.latest_analysis["sarm"] = data["sarm"]
        if "guardian" in data:
            self._state.run_metadata["guardian"] = data["guardian"]
        self._state.run_metadata["last_stage_payload"] = {"stage": stage.value, "data": data}

    def _apply_fault_injection(self) -> None:
        fault_stage = str(self._state.fault_injection.get("stage", ""))
        fault_name = str(self._state.fault_injection.get("fault", "none"))
        if self._state.mode.value == "fault-injection":
            if fault_name != "none" and fault_stage == self._state.stage.value:
                raise RuntimeError(f"Injected fault at stage={fault_stage}: {fault_name}")

    async def _run_orchestrator_head(self) -> None:
        agent = self._agent_registry.get(self._orchestrator_agent_name)
        result = await agent.run(self._state, self._ctx)
        self._state.run_metadata["orchestrator_plan"] = result.data
        await self._emit(
            event_type="orchestrator_plan",
            message=result.summary,
            payload=result.data,
        )

    async def step(self) -> None:
        """Execute one stage transition step."""
        if self._state.stage == Stage.IDLE:
            self._state.stage = Stage.DESIGN
            await self._emit(event_type="stage_transition", message="Transition idle -> design")
            return

        if self._state.safe_stop_requested:
            self._state.stage = Stage.COMPLETE
            await self._emit(
                event_type="safe_stop",
                message=safe_stop_reason("safe_stop_requested flag"),
            )
            return

        # Run heavy top-level orchestration once per loop cycle.
        # A cycle starts at DESIGN (or when guardian routes back to DESIGN),
        # which avoids re-running the 31B planner on every physical stage.
        if self._state.stage == Stage.DESIGN:
            await self._run_orchestrator_head()
        stage = self._state.stage
        agent_name = stage_to_agent(stage)
        if not agent_name:
            self._state.stage = Stage.ERROR
            await self._emit(
                event_type="routing_error",
                message=f"No agent routing for stage={stage.value}",
                level="ERROR",
            )
            return

        status = self._ensure_agent_status(agent_name)
        status.state = "running"
        status.mode = self._state.mode.value

        agent = self._agent_registry.get(agent_name)
        try:
            self._apply_fault_injection()
            result = await agent.run(self._state, self._ctx)
            ok, validation_msg = validate_agent_output(stage.value, result.data)
            if not ok:
                raise ValueError(validation_msg)

            self._merge_agent_data(stage, result.data)
            status.state = "idle"
            status.last_result = result.summary
            status.last_run_time = agent.now_iso()
            status.success = result.success

            log_agent_event(
                self._logger,
                run_id=self._state.run_id,
                agent_name=agent_name,
                event_type="completed",
                message=result.summary,
                payload=result.data,
                experiment_id=self._state.experiment_id,
            )
            await self._emit(
                event_type="agent_result",
                message=f"{agent_name}: {result.summary}",
                payload={"agent": agent_name, "result": result.data},
            )

            guardian_decision = "continue"
            if stage == Stage.GUARDIAN:
                guardian_decision = str(result.data.get("guardian", {}).get("decision", "continue"))
                self._state.loop_count += 1
            self._state.stage = self._graph.next_stage(stage, guardian_decision=guardian_decision)

            await self._emit(
                event_type="stage_transition",
                message=f"Transition {stage.value} -> {self._state.stage.value}",
            )
        except Exception as exc:
            status.state = "error"
            status.last_result = str(exc)
            status.last_run_time = agent.now_iso()
            status.success = False
            log_error(
                self._logger,
                run_id=self._state.run_id,
                where=f"{agent_name}@{stage.value}",
                error=exc,
                state_snapshot=self._state.model_dump(mode="json"),
            )

            if should_retry(self._state, stage.value, self._max_retry_per_stage):
                retry_count = bump_retry(self._state, stage.value)
                action = recovery_action(stage.value, str(exc))
                await self._emit(
                    event_type="retry",
                    message=f"Retry stage={stage.value} attempt={retry_count}",
                    payload={"error": str(exc), "recovery": action},
                    level="WARNING",
                )
            else:
                self._state.stage = Stage.ERROR
                await self._emit(
                    event_type="fatal_error",
                    message=f"Stage={stage.value} exceeded retry budget: {exc}",
                    level="ERROR",
                )

    async def run(self) -> OrchestratorState:
        """Run until complete/error/stop_requested."""
        await self._emit(event_type="run_start", message="Orchestration run started")
        while True:
            if self._state.stop_requested:
                self._state.stage = Stage.COMPLETE
                await self._emit(event_type="run_stop", message="Stop requested by operator")
                break

            if self._state.stage in {Stage.COMPLETE, Stage.ERROR}:
                break

            if self._state.is_paused:
                await self._emit(event_type="paused", message="Run paused")
                await asyncio.sleep(0.25)
                continue

            await self.step()
            await asyncio.sleep(self._interval_seconds)

        final_event = "run_complete" if self._state.stage == Stage.COMPLETE else "run_error"
        await self._emit(event_type=final_event, message=f"Run finished in stage={self._state.stage.value}")
        return self._state
