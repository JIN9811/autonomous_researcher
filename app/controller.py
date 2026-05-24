"""
File purpose:
- Central runtime controller connecting API controls, run loop, logs, and event streams.

Key classes/functions:
- MainController

Inputs/outputs:
- Input: control commands (start/pause/stop), mode toggles, run goal updates
- Output: live state snapshots and streamed events for web GUI

Dependencies:
- asyncio
- orchestrator.run_loop.RunLoop
- logging_system.run_trace.RunTrace

Modification guide:
- Safe places to edit: control command behavior and event payload shape
- Risky places to edit: run lifecycle and concurrent task handling
- Related files: app/main.py, app/bootstrap.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from agents.base_agent import AgentContext
from agents.registry import AgentRegistry
from logging_system.logger_factory import LoggerBundle, build_logger_bundle
from logging_system.run_trace import RunTrace
from mcp_tools.tpms_geometry import (
    generate_gyroid_stl_text,
    normalize_geometry_type as normalize_tpms_geometry_type,
    write_smooth_gyroid_stl,
)
from orchestrator.graph import OrchestrationGraph
from orchestrator.run_loop import RunLoop
from orchestrator.state import Mode, OrchestratorState, Stage
from utils.ids import make_experiment_id, make_run_id
from utils.printer_profile import load_prusa_print_profile


@dataclass(slots=True)
class ControllerDeps:
    """Dependency bundle injected from bootstrap."""

    agent_registry: AgentRegistry
    orchestrator_agent_name: str
    agent_context: AgentContext
    graph: OrchestrationGraph
    run_root: Path
    logging_config: dict[str, Any]
    system_config: dict[str, Any]
    runtime_profile: dict[str, Any]


class MainController:
    """Stateful controller for orchestrator execution and event fanout."""

    TEST_MODE_FIXED_GEOMETRY = "gyroid"

    def __init__(self, deps: ControllerDeps) -> None:
        self._deps = deps
        self._trace = RunTrace(max_events=int(deps.system_config.get("event_buffer_size", 300)))
        self._event_queues: set[asyncio.Queue[dict[str, Any]]] = set()
        self._run_task: asyncio.Task[None] | None = None

        self._logger_bundle = self._new_logger_bundle()
        self._state = self._new_state(mode=Mode(deps.system_config.get("default_mode", "test")))
        self._last_completed_trace: list[dict[str, Any]] = []
        self._planning_messages: list[dict[str, Any]] = []
        self._planning_session_id: str | None = None
        self._planning_bootstrapped = False
        self._planning_request_lock = asyncio.Lock()
        self._planning_handoff_task: asyncio.Task[dict[str, Any]] | None = None
        self._vllm_transition_task: asyncio.Task[dict[str, Any]] | None = None
        self._deps.agent_context.on_model_call = self._on_model_call
        self._deps.agent_context.on_tool_event = self._on_tool_event

    def _new_logger_bundle(self) -> LoggerBundle:
        run_id = make_run_id()
        return build_logger_bundle(
            run_id=run_id,
            run_root=self._deps.run_root,
            logging_config=self._deps.logging_config,
        )

    def _new_state(self, mode: Mode) -> OrchestratorState:
        return OrchestratorState(
            run_id=self._logger_bundle.run_dir.name,
            experiment_id=make_experiment_id(),
            active_session_id=self._logger_bundle.run_dir.name,
            mode=mode,
            stage=Stage.IDLE,
            active_goal="Build and run autonomous AI researcher loop",
            device_health={"printer": "ready", "camera": "ready", "robot": "ready", "utm": "ready"},
            run_metadata=self._runtime_profile(),
            retry_counters={},
            fault_injection={"fault": "none", "stage": ""},
        )

    def _runtime_profile(self) -> dict[str, Any]:
        """Return active backend/model metadata from the shared AgentContext."""
        if hasattr(self._deps.agent_context, "runtime_profile"):
            profile = self._deps.agent_context.runtime_profile()
            self._deps.runtime_profile.clear()
            self._deps.runtime_profile.update(profile)
            return dict(profile)
        return dict(self._deps.runtime_profile)

    async def _on_model_call(self, *, task_type: str, model: str, role: str, backend: str) -> None:
        """Keep active vLLM deployments warm while a Live GUI/run workflow is progressing."""
        if backend != "vllm" or self._deps.agent_context.active_backend != "vllm":
            return
        self._cancel_pending_vllm_transition()

    async def _on_tool_event(self, event: dict[str, Any]) -> None:
        """Stream hardware tool step progress into the Live GUI conversation."""
        if not self._planning_bootstrapped or not isinstance(event, dict):
            return
        tool = str(event.get("tool", ""))
        if tool not in {"printer.prepare", "equipment.pyautogui.run"} and not tool.startswith("lerobot."):
            return
        step = str(event.get("step", "STEP"))
        status = str(event.get("status", "unknown"))
        detail = event.get("detail")
        suffix = f" ({detail})" if detail not in (None, "") else ""
        if tool.startswith("lerobot."):
            await self._append_planning_message(
                {
                    "role": "manipulation_ai",
                    "content": f"Manipulation Agent / LeRobot 단계 진행: {step} -> {status}{suffix}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": "manipulation_agent",
                    "ok": status not in {"blocked", "failed", "error"},
                    "lerobot_runtime_event": event,
                },
                event_type="planning_lerobot_step",
                message=f"{tool} step {step} {status}",
                level="ERROR" if status in {"blocked", "failed", "error"} else "INFO",
            )
            return
        if tool == "equipment.pyautogui.run":
            await self._append_planning_message(
                {
                    "role": "equipment_ai",
                    "content": f"Equipment Agent 단계 진행: {step} -> {status}{suffix}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": "equipment_agent",
                    "ok": status not in {"blocked", "failed"},
                    "equipment_runtime_event": event,
                },
                event_type="planning_equipment_step",
                message=f"equipment.pyautogui.run step {step} {status}",
                level="ERROR" if status in {"blocked", "failed"} else "INFO",
            )
            return
        await self._append_planning_message(
            {
                "role": "printer_ai",
                "content": f"Specimen Making Agent 단계 진행: {step} -> {status}{suffix}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "specimen_agent",
                "ok": status not in {"blocked", "failed"},
                "printer_runtime_event": event,
            },
            event_type="planning_printer_step",
            message=f"printer.prepare step {step} {status}",
            level="ERROR" if status in {"blocked", "failed"} else "INFO",
        )

    def _apply_inference_backend(self, backend: str | None) -> None:
        """Switch the central inference backend without touching individual agents."""
        clean_backend = str(backend or "").strip().lower()
        if not clean_backend:
            self._state.run_metadata = self._runtime_profile()
            return
        if self._run_task and not self._run_task.done():
            raise RuntimeError("Cannot switch inference backend while a run is active.")
        self._deps.agent_context.set_active_backend(clean_backend)
        self._state.run_metadata = self._runtime_profile()

    async def _broadcast_event(self, event: dict[str, Any]) -> None:
        self._trace.add(event)
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._event_queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self._event_queues.discard(queue)

    async def emit_lerobot_result(self, result: dict[str, Any]) -> None:
        """Broadcast a LeRobot GUI/tool result and stream its steps into Live GUI when active."""
        if not isinstance(result, dict):
            return
        tool = str(result.get("tool") or "lerobot")
        status = str(result.get("status") or ("ok" if result.get("ok") else "failed"))
        level = "INFO" if bool(result.get("ok", False)) else "ERROR"
        event_id_seed = f"{tool}-{len(self._trace.snapshot()) + 1}"
        await self._broadcast_event(
            {
                "event_id": f"evt-lerobot-{hashlib.sha1(event_id_seed.encode()).hexdigest()[:10]}",
                "run_id": self._state.run_id,
                "experiment_id": self._state.experiment_id,
                "event_type": "lerobot_step",
                "level": level,
                "message": f"{tool} {status}",
                "payload": {"result": result},
                "state": self._state.model_dump(mode="json"),
            }
        )
        for item in result.get("step_trace", []):
            if not isinstance(item, dict):
                continue
            await self._on_tool_event(
                {
                    "tool": tool,
                    "profile_id": result.get("profile_id", ""),
                    "session_id": result.get("session_id", ""),
                    "mode": result.get("mode", ""),
                    "step": item.get("step", "STEP"),
                    "status": item.get("status", status),
                    "detail": item.get("detail", ""),
                }
            )

    def snapshot(self) -> dict[str, Any]:
        """Return current state plus logging metadata."""
        return {
            "state": self._state.model_dump(mode="json"),
            "runtime": self._runtime_profile(),
            "logs": {
                "run_dir": str(self._logger_bundle.run_dir),
                "json": str(self._logger_bundle.json_log_path),
                "summary": str(self._logger_bundle.summary_log_path),
            },
            "is_running": bool(self._run_task and not self._run_task.done()) or self._planning_handoff_active(),
            "agents": self._deps.agent_registry.names(),
        }

    def recent_events(self) -> list[dict[str, Any]]:
        """Return buffered recent events."""
        return self._trace.snapshot()

    async def switch_inference_backend(self, backend: str) -> dict[str, Any]:
        """Switch active inference backend for future agent/model calls."""
        try:
            self._apply_inference_backend(backend)
        except Exception as exc:
            return {"ok": False, "message": str(exc), "snapshot": self.snapshot()}
        profile = self._runtime_profile()
        await self._broadcast_event(
            {
                "event_id": f"evt-backend-{profile.get('backend', {}).get('name', 'unknown')}",
                "run_id": self._state.run_id,
                "experiment_id": self._state.experiment_id,
                "event_type": "backend_switch",
                "level": "INFO",
                "message": f"Inference backend switched to {profile.get('backend', {}).get('label', backend)}",
                "payload": {"runtime": profile},
                "state": self._state.model_dump(mode="json"),
            }
        )
        return {"ok": True, "message": "Inference backend switched.", "snapshot": self.snapshot()}

    def planning_snapshot(self, *, session_id: str | None = None) -> dict[str, Any]:
        """Return current live-planning conversation and runtime context."""
        self._bind_planning_session(session_id)
        self._ensure_planning_intro()
        return {
            "messages": list(self._planning_messages),
            "state": self._state.model_dump(mode="json"),
            "runtime": self._runtime_profile(),
            "is_running": bool(self._run_task and not self._run_task.done()) or self._planning_handoff_active(),
            "is_planning_busy": self._planning_request_lock.locked() or self._planning_handoff_active(),
            "planning_session_id": self._planning_session_id,
        }

    def prepare_live_gui(
        self,
        *,
        goal: str | None = None,
        backend: str | None = None,
        reset: bool = False,
    ) -> dict[str, Any]:
        """Prepare the shared controller state for the live GUI without starting hardware."""
        if self._run_task and not self._run_task.done():
            return self.planning_snapshot()
        self._apply_inference_backend(backend)
        self._state.mode = Mode.LIVE
        if goal:
            self._state.active_goal = goal
        if reset:
            self._planning_messages = []
            self._planning_session_id = None
            self._planning_bootstrapped = False
        self._ensure_planning_intro()
        return self.planning_snapshot()

    def _bind_planning_session(self, session_id: str | None) -> None:
        """Bind Live GUI to a shared server-side conversation for all open windows."""
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id:
            return
        if self._planning_session_id is None:
            self._planning_session_id = clean_session_id
            return
        if clean_session_id == self._planning_session_id:
            return
        # A newly opened browser window may have a different local id. Do not clear
        # the server-side Live GUI transcript; reset is handled explicitly by fresh=1.
        return

    def _ensure_planning_intro(self) -> None:
        """Keep the Live GUI session initialized without injecting static chat copy."""
        return

    async def _append_planning_message(
        self,
        entry: dict[str, Any],
        *,
        event_type: str = "planning_message",
        level: str = "INFO",
        message: str = "Live GUI planning message updated.",
    ) -> None:
        """Append one Live GUI message and broadcast it immediately for incremental display."""
        self._planning_messages.append(entry)
        await self._broadcast_event(
            {
                "event_id": f"evt-planning-{len(self._planning_messages)}",
                "run_id": self._state.run_id,
                "experiment_id": self._state.experiment_id,
                "event_type": event_type,
                "level": level,
                "message": message,
                "payload": {"latest": entry},
                "state": self._state.model_dump(mode="json"),
            }
        )

    def subscribe(self, queue_size: int = 200) -> asyncio.Queue[dict[str, Any]]:
        """Create a new event subscription queue."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        self._event_queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove event subscription queue."""
        self._event_queues.discard(queue)

    async def _emit_control_event(self, event_type: str, message: str) -> None:
        """Emit control-plane events when run loop task is cancelled externally."""
        await self._broadcast_event(
            {
                "event_id": f"evt-control-{event_type}",
                "run_id": self._state.run_id,
                "experiment_id": self._state.experiment_id,
                "event_type": event_type,
                "level": "INFO",
                "message": message,
                "payload": {},
                "state": self._state.model_dump(mode="json"),
            }
        )

    async def _run_live_or_test(self) -> None:
        loop = RunLoop(
            state=self._state,
            agent_registry=self._deps.agent_registry,
            orchestrator_agent_name=self._deps.orchestrator_agent_name,
            ctx=self._deps.agent_context,
            graph=self._deps.graph,
            logger=self._logger_bundle.logger,
            max_retry_per_stage=int(self._deps.system_config.get("max_retry_per_stage", 2)),
            interval_seconds=float(self._deps.system_config.get("loop_interval_seconds", 1.25)),
            on_event=self._broadcast_event,
        )
        try:
            await loop.run()
            self._last_completed_trace = self._trace.snapshot()
        finally:
            self._schedule_post_run_vllm_transition()

    async def _run_replay(self) -> None:
        if not self._last_completed_trace:
            await self._broadcast_event(
                {
                    "event_id": "evt-replay-empty",
                    "event_type": "replay_empty",
                    "message": "No previous run to replay.",
                    "payload": {},
                    "state": self._state.model_dump(mode="json"),
                }
            )
            self._state.stage = Stage.COMPLETE
            return
        for event in self._last_completed_trace:
            replay_event = dict(event)
            replay_event["event_type"] = "replay_event"
            await self._broadcast_event(replay_event)
            await asyncio.sleep(0.15)
        self._state.stage = Stage.COMPLETE
        await self._broadcast_event(
            {
                "event_id": "evt-replay-done",
                "event_type": "replay_complete",
                "message": "Replay finished.",
                "payload": {},
                "state": self._state.model_dump(mode="json"),
            }
        )

    async def start(
        self,
        *,
        mode: Mode,
        goal: str | None = None,
        backend: str | None = None,
        fault: str = "none",
        fault_stage: str = "",
    ) -> dict[str, Any]:
        """Start a new run if idle."""
        if self._run_task and not self._run_task.done():
            return {"ok": False, "message": "Run already active."}

        try:
            self._apply_inference_backend(backend)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
        self._cancel_pending_vllm_transition()

        self._trace = RunTrace(max_events=int(self._deps.system_config.get("event_buffer_size", 300)))
        self._logger_bundle = self._new_logger_bundle()
        self._state = self._new_state(mode=mode)
        if goal:
            self._state.active_goal = goal
        self._state.fault_injection = {"fault": fault, "stage": fault_stage}

        if mode == Mode.REPLAY:
            self._run_task = asyncio.create_task(self._run_replay())
        else:
            self._run_task = asyncio.create_task(self._run_live_or_test())
        return {
            "ok": True,
            "message": f"Run started in mode={mode.value}",
            "run_id": self._state.run_id,
            "startup_vllm": {"enabled": False, "manual_loading_required": True},
        }

    async def pause(self) -> dict[str, Any]:
        """Pause the active run loop."""
        self._state.is_paused = True
        return {"ok": True, "message": "Paused"}

    async def resume(self) -> dict[str, Any]:
        """Resume paused run loop."""
        self._state.is_paused = False
        return {"ok": True, "message": "Resumed"}

    async def stop(self) -> dict[str, Any]:
        """Request stop for active run."""
        self._state.stop_requested = True
        if self._run_task and not self._run_task.done():
            self._state.stage = Stage.COMPLETE
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
            await self._emit_control_event("run_stop", "Stop requested by operator (forced cancel)")
            await self._emit_control_event("run_complete", "Run finished in stage=complete")
            self._last_completed_trace = self._trace.snapshot()
        return {"ok": True, "message": "Stop requested"}

    async def safe_stop(self) -> dict[str, Any]:
        """Request safe stop for active run."""
        self._state.safe_stop_requested = True
        return {"ok": True, "message": "Safe stop requested"}

    async def planning_message(
        self,
        *,
        message: str,
        goal: str | None = None,
        backend: str | None = None,
        constraints: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Run the top-level orchestrator model for live-planning discussion only."""
        try:
            self._apply_inference_backend(backend)
        except Exception as exc:
            return {"ok": False, "message": str(exc), "session": self.planning_snapshot(session_id=session_id)}
        self._cancel_pending_vllm_transition()
        self._bind_planning_session(session_id)
        self._ensure_planning_intro()
        clean_message = message.strip()
        if not clean_message:
            return {"ok": False, "message": "Planning message is empty.", "session": self.planning_snapshot(session_id=session_id)}
        if self._planning_request_lock.locked():
            return {
                "ok": False,
                "message": "Live GUI orchestrator is still reasoning.",
                "session": self.planning_snapshot(session_id=session_id),
            }

        async with self._planning_request_lock:
            return await self._planning_message_locked(
                message=clean_message,
                goal=goal,
                constraints=constraints or {},
                session_id=session_id,
            )

    async def _planning_message_locked(
        self,
        *,
        message: str,
        goal: str | None,
        constraints: dict[str, Any],
        session_id: str | None,
    ) -> dict[str, Any]:
        """Handle one operator message while the Live GUI planning lock is held."""
        now = datetime.now(timezone.utc).isoformat()
        user_entry = {
            "role": "operator",
            "content": message,
            "timestamp": now,
            "goal": goal or self._state.active_goal,
            "constraints": constraints,
        }
        self._planning_messages.append(user_entry)

        if self._should_trigger_test_design(message):
            return await self._run_test_mode_planning(goal=goal, constraints=constraints, operator_message=message)

        if self._should_route_specimen_printer_choice(message):
            self._ensure_pending_specimen_printer_choice()
            return await self._handle_pending_specimen_operator_input(message=message, session_id=session_id)

        if self._state.run_metadata.get("pending_specimen_input"):
            return await self._handle_pending_specimen_operator_input(message=message, session_id=session_id)

        if self._should_trigger_design(message):
            readiness = self._planning_design_handoff_readiness(goal=goal, constraints=constraints)
            if readiness["missing"]:
                return await self._request_missing_design_values(readiness, session_id=session_id)
            return await self._handoff_planning_to_design(
                goal=str(readiness.get("goal") or goal or self._state.active_goal),
                constraints=dict(readiness.get("constraints", constraints)),
            )

        prompt = await self._build_live_orchestrator_prompt(
            operator_message=message,
            goal=goal or self._state.active_goal,
            constraints=constraints,
        )

        try:
            response, response_message = await self._complete_live_planning_prompt(
                prompt=prompt
            )
            assistant_entry = {
                "role": "orchestrator",
                "content": response.text,
                "reasoning": self._extract_reasoning(response.raw),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": response.model,
                "ok": True,
            }
            ok = True
        except Exception as exc:
            assistant_entry = {
                "role": "orchestrator",
                "content": (
                    "Live GUI 오케스트레이터 호출에 실패했습니다. "
                    "NemoClaw/Ollama 연결과 모델 상태를 확인하세요.\n"
                    f"error={exc.__class__.__name__}: {exc}"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": None,
                "ok": False,
            }
            ok = False
            response_message = "Live GUI orchestrator_plan call failed."

        await self._append_planning_message(
            assistant_entry,
            level="INFO" if ok else "ERROR",
            message=response_message,
        )
        return {"ok": ok, "message": response_message, "session": self.planning_snapshot(session_id=session_id)}

    async def bootstrap_live_orchestrator(
        self,
        *,
        goal: str | None = None,
        backend: str | None = None,
        constraints: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Warm up and start the Live GUI orchestrator before the operator sends text."""
        try:
            self._apply_inference_backend(backend)
        except Exception as exc:
            return {"ok": False, "message": str(exc), "session": self.planning_snapshot(session_id=session_id)}
        self._cancel_pending_vllm_transition()
        self._bind_planning_session(session_id)
        self.prepare_live_gui(goal=goal, backend=backend, reset=False)
        if self._planning_bootstrapped:
            return {
                "ok": True,
                "message": "Live GUI orchestrator bootstrap already completed.",
                "session": self.planning_snapshot(session_id=session_id),
            }
        if self._planning_request_lock.locked():
            return {
                "ok": False,
                "message": "Live GUI orchestrator is already starting.",
                "session": self.planning_snapshot(session_id=session_id),
            }

        async with self._planning_request_lock:
            if self._planning_bootstrapped:
                return {
                    "ok": True,
                    "message": "Live GUI orchestrator bootstrap already completed.",
                    "session": self.planning_snapshot(session_id=session_id),
                }

            prompt = await self._build_live_orchestrator_prompt(
                operator_message=(
                    "Live GUI was opened from the main Start button. "
                    "No operator message has been sent yet. Start the orchestration discussion by asking for "
                    "the experiment objective, specimen size, material/printer constraints, and the trigger keyword."
                ),
                goal=goal or self._state.active_goal,
                constraints=constraints or {},
            )

            try:
                response, response_message = await self._complete_live_planning_prompt(prompt=prompt)
                assistant_entry = {
                    "role": "orchestrator",
                    "content": response.text,
                    "reasoning": self._extract_reasoning(response.raw),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": response.model,
                    "ok": True,
                    "bootstrap": True,
                }
                self._planning_bootstrapped = True
                ok = True
            except Exception as exc:
                assistant_entry = {
                    "role": "orchestrator",
                    "content": (
                        "Live GUI 오케스트레이터 초기 호출에 실패했습니다. "
                        "send를 누르면 동일한 orchestrator_plan 경로로 다시 호출할 수 있습니다.\n"
                        f"error={exc.__class__.__name__}: {exc}"
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": None,
                    "ok": False,
                    "bootstrap": True,
                }
                ok = False
                response_message = "Live GUI orchestrator bootstrap failed."

            await self._append_planning_message(
                assistant_entry,
                event_type="planning_bootstrap",
                level="INFO" if ok else "ERROR",
                message=response_message,
            )
            return {"ok": ok, "message": response_message, "session": self.planning_snapshot(session_id=session_id)}

    async def _run_test_mode_planning(
        self,
        *,
        goal: str | None,
        constraints: dict[str, Any],
        operator_message: str,
    ) -> dict[str, Any]:
        """Let the orchestrator LLM choose concrete test values, then hand off to DesignAgent."""
        base_goal = goal or "테스트 모드 TPMS gyroid(PLA) 압축 시편 설계"
        defaults = self._default_test_constraints(constraints)
        inline_printer_choice = self._parse_inline_test_mode_printer_choice(operator_message)
        if inline_printer_choice:
            defaults = self._apply_specimen_printer_choice_to_spec(defaults, inline_printer_choice)
        prompt = await self._build_test_mode_orchestrator_prompt(
            operator_message=operator_message,
            goal=base_goal,
            constraints=defaults,
        )

        try:
            response, response_message = await self._complete_live_planning_prompt(prompt=prompt)
            llm_payload = self._extract_test_mode_payload(response.text)
            test_goal = str(llm_payload.get("goal") or base_goal)
            llm_constraints = llm_payload.get("constraints") if isinstance(llm_payload.get("constraints"), dict) else {}
            test_constraints = self._normalize_test_mode_constraints(defaults, llm_constraints)
            if inline_printer_choice:
                test_constraints = self._apply_specimen_printer_choice_to_spec(test_constraints, inline_printer_choice)
            assistant_entry = {
                "role": "orchestrator",
                "content": (
                    f"{response.text.strip()}\n\n"
                    "적용할 테스트 실험값:\n"
                    "```json\n"
                    f"{json.dumps(test_constraints, ensure_ascii=False, indent=2)}\n"
                    "```"
                ),
                "reasoning": self._extract_reasoning(response.raw),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": response.model,
                "ok": True,
            }
            await self._append_planning_message(
                assistant_entry,
                level="INFO",
                message=response_message,
            )
            if inline_printer_choice == "physical_print":
                return await self._start_planning_handoff_background(goal=test_goal, constraints=test_constraints)
            return await self._handoff_planning_to_design(goal=test_goal, constraints=test_constraints)
        except Exception as exc:
            assistant_entry = {
                "role": "orchestrator",
                "content": (
                    "테스트 모드 실험값 생성에 실패했습니다. NemoClaw/Ollama 연결과 모델 상태를 확인하세요.\n"
                    f"error={exc.__class__.__name__}: {exc}"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": None,
                "ok": False,
            }
            await self._append_planning_message(
                assistant_entry,
                level="ERROR",
                message="Live GUI test-mode orchestration failed.",
            )
            return {"ok": False, "message": "Live GUI test-mode orchestration failed.", "session": self.planning_snapshot()}

    def _planning_handoff_active(self) -> bool:
        task = self._planning_handoff_task
        return bool(task and not task.done())

    async def _start_planning_handoff_background(self, *, goal: str | None, constraints: dict[str, Any]) -> dict[str, Any]:
        """Return the Live GUI request before long physical-print upload/start work blocks fetch."""
        if self._planning_handoff_active():
            await self._append_planning_message(
                {
                    "role": "system",
                    "content": "이미 실행 중인 Live GUI workflow가 있습니다. 현재 작업이 끝난 뒤 다음 요청을 보내세요.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": False,
                },
                event_type="planning_handoff",
                level="WARNING",
                message="Planning handoff already active.",
            )
            return {"ok": False, "message": "Planning handoff already active.", "session": self.planning_snapshot()}

        await self._append_planning_message(
            {
                "role": "system",
                "content": "테스트 모드 실제 출력 workflow를 시작했습니다. 슬라이싱, G-code 업로드, 출력 시작은 시간이 걸릴 수 있어 백그라운드에서 계속 진행하고 이 창에 단계별 결과를 갱신합니다.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": True,
            },
            event_type="planning_handoff",
            message="Physical-print planning handoff scheduled in background.",
        )

        async def _runner() -> dict[str, Any]:
            try:
                return await self._handoff_planning_to_design(goal=goal, constraints=constraints)
            except Exception as exc:
                await self._append_planning_message(
                    {
                        "role": "system",
                        "content": f"백그라운드 workflow 실행 실패: {exc.__class__.__name__}: {exc}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": False,
                    },
                    event_type="planning_handoff",
                    level="ERROR",
                    message="Background planning handoff failed.",
                )
                return {"ok": False, "message": "Background planning handoff failed.", "session": self.planning_snapshot()}

        task = asyncio.create_task(_runner())
        self._planning_handoff_task = task

        def _clear(done: asyncio.Task[dict[str, Any]]) -> None:
            if self._planning_handoff_task is done:
                self._planning_handoff_task = None
            try:
                done.result()
            except Exception:
                pass

        task.add_done_callback(_clear)
        return {"ok": True, "message": "Physical-print planning handoff started.", "session": self.planning_snapshot()}

    async def _build_live_orchestrator_prompt(
        self,
        *,
        operator_message: str,
        goal: str,
        constraints: dict[str, Any],
    ) -> str:
        """Build the Live GUI prompt from existing project/runtime guideline context."""
        conversation_memory = self._planning_memory_context(limit=4, max_chars=500)
        state_context = self._planning_state_context()
        return (
            "Live GUI operator conversation for the existing autonomous_researcher runtime.\n"
            "Use this compact project contract as the authoritative instruction basis.\n"
            f"{self._live_runtime_contract_context()}\n"
            "Use the conversation_memory as short-lived session memory; do not assume it persists after this Live GUI session.\n"
            "Do not create new top-level stages. Operator approval is expressed by the `실험 수행` keyword.\n"
            "Do not add runtime-safety disclaimers. Focus on missing design values and the next handoff.\n"
            "Do not use LaTeX math notation. Use plain text arrows like '->' for routes.\n"
            "For normal Live GUI execution, `실험 수행` means generate the design and proceed to actual Prusa MK4S print upload/start through Specimen Making Agent.\n"
            "For `테스트 모드`, keep printer actions virtual/read-only unless Specimen Making Agent later asks for the printer path and the operator explicitly chooses `실제 출력`.\n"
            "Use validated printer defaults unless the operator overrides them: Prusa MK4S, USB storage, 0.4 mm nozzle, 0.2 mm layer height, PLA-oriented profile.\n"
            "Ask for experimental objective, material, specimen size, structure/domain, and any printer/slicer override needed before handoff.\n"
            "If the operator includes `실험 수행` and required design inputs are complete, the controller will hand off to DesignAgent and then continue to the Specimen Making Agent.\n"
            "Respond in concise Korean as the OrchestratorAgent. Use at most 6 short bullets or 140 Korean words.\n\n"
            f"conversation_memory=\n{conversation_memory}\n\n"
            f"state_context={state_context}\n"
            f"goal={goal}\n"
            f"constraints={constraints}\n"
            f"operator_message={operator_message}\n"
            "Required response shape:\n"
            "- Ask for missing experiment-design and live-print inputs.\n"
            "- Summarize the proposed route only once, briefly.\n"
            "- Tell the operator that including `실험 수행` starts DesignAgent -> Specimen Making Agent and, in live mode, PrusaLink upload/start.\n"
        )

    async def _live_guideline_context(self, *, operator_message: str, goal: str) -> str:
        """Retrieve existing docs context for Live GUI orchestration guidance."""
        query = (
            "orchestrator live gui experiment planning existing runtime stages "
            "DesignAgent printer specimen spec Guardian operator approval "
            f"{goal} {operator_message}"
        )
        retrieved = await self._deps.agent_context.rag.retrieve(query, top_k_local=3)
        chunks = retrieved.get("local_chunks", []) if isinstance(retrieved, dict) else []
        lines = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            source = str(chunk.get("source", "Project_guide"))
            text = str(chunk.get("text", "")).strip()
            if text:
                lines.append(f"[source={source}]\n{text[:1200]}")

        specimen_guideline = self._load_optional_guideline(
            self._deps.run_root.parent / "docs" / "agents" / "specimen_design_existing_runtime_guideline.txt",
            limit=1800,
        )
        if specimen_guideline:
            lines.append(f"[source=docs/agents/specimen_design_existing_runtime_guideline.txt]\n{specimen_guideline}")
        return "\n\n---\n\n".join(lines) if lines else "No guideline context retrieved; follow current runtime state only."

    async def _build_test_mode_orchestrator_prompt(
        self,
        *,
        operator_message: str,
        goal: str,
        constraints: dict[str, Any],
    ) -> str:
        """Build a prompt that asks the orchestrator LLM to choose concrete test-mode values."""
        conversation_memory = self._planning_memory_context(limit=4, max_chars=500)
        state_context = self._planning_state_context()
        return (
            "Live GUI test-mode orchestration request.\n"
            "Use the existing autonomous_researcher runtime contract.\n"
            f"{self._live_runtime_contract_context()}\n"
            "Use conversation_memory as short-lived Live GUI session memory.\n"
            "Choose concrete test experiment values yourself, then prepare the DesignAgent handoff.\n"
            "The default specimen must be an FDM-printable closed-shell gyroid TPMS, not a visual-only thin TPMS surface.\n"
            "Test-mode printer handling first asks Specimen Making Agent for `가상 브릿지`, `설치 프린터`, or `실제 출력`; only `실제 출력` may physically upload/start.\n"
            "If operator_message already contains one of those choices, set constraints.printer_test_path accordingly so Specimen Making Agent can continue without asking again.\n"
            "Do not add runtime-safety disclaimers; focus on generated values and handoff.\n"
            "Do not use LaTeX math notation. Use plain text arrows like '->' for routes.\n"
            "Remember the planning handoff chain is DesignAgent -> Specimen Making Agent -> Guardian.\n"
            "Respond in concise Korean and include a fenced JSON block at the end with this schema:\n"
            "```json\n"
            "{\n"
            "  \"goal\": \"short concrete test goal\",\n"
            "  \"constraints\": {\n"
            "    \"material\": \"PLA\",\n"
            "    \"geometry_type\": \"gyroid\",\n"
            "    \"preferred_geometry_type\": \"gyroid\",\n"
            "    \"max_specimen_size_mm\": [30, 30, 30],\n"
            "    \"specimen_size_mm\": [30, 30, 30],\n"
            "    \"objective_type\": \"specific_energy_absorption\",\n"
            "    \"objective_direction\": \"maximize\",\n"
            "    \"cell_size_mm\": 10.0,\n"
            "    \"wall_thickness_mm\": 1.2,\n"
            "    \"relative_density\": 0.35,\n"
            "    \"tpms_surface\": \"gyroid\",\n"
            "    \"tpms_thickness\": 0.38,\n"
            "    \"tpms_resolution\": 72,\n"
            "    \"printability_mode\": \"fdm_closed_shell\",\n"
            "    \"fdm_min_wall_thickness_mm\": 1.2,\n"
            "    \"fdm_max_bridge_distance_mm\": 10.0,\n"
            "    \"fdm_max_unsupported_overhang_deg\": 45,\n"
            "    \"fdm_max_gyroid_wall_cell_ratio\": 0.28,\n"
            "    \"expected_mass_g\": 18.0,\n"
            "    \"max_print_time_min\": 120,\n"
            "    \"printer_model\": \"Prusa MK4S\",\n"
            "    \"printer_profile\": \"prusa_mk4s_pla_0p4_nozzle\",\n"
            "    \"slicer_profile_hint\": \"0.2mm_quality\",\n"
            "    \"nozzle_diameter_mm\": 0.4,\n"
            "    \"layer_height_mm\": 0.2,\n"
            "    \"first_layer_height_mm\": 0.2,\n"
            "    \"slow_first_layer_enabled\": true,\n"
            "    \"first_layer_speed_mm_s\": 10.0,\n"
            "    \"bed_temperature_c\": 60.0,\n"
            "    \"first_layer_bed_temperature_c\": 60.0,\n"
            "    \"storage\": \"usb\",\n"
            "    \"print\": {\"storage\": \"usb\", \"start_immediately\": false, \"overwrite\": true}\n"
            "  }\n"
            "}\n"
            "```\n\n"
            f"conversation_memory=\n{conversation_memory}\n\n"
            f"state_context={state_context}\n"
            f"operator_message={operator_message}\n"
            f"default_constraints={constraints}\n"
        )

    @staticmethod
    def _live_runtime_contract_context() -> str:
        """Compact docs-derived contract for Live GUI prompts."""
        return (
            "Project contract: Orchestrator routes existing stages only. Stage order is "
            "Design Agent -> Specimen Making Agent -> Vision Agent -> Manipulation Agent -> "
            "Lab Equipment Agent -> Analysis Agent -> Knowledge Agent -> Guardian Agent. "
            "Design Agent chooses metamaterial parameters; deterministic geometry tools create STL; "
            "Specimen Making Agent owns printer.prepare and printer/ejection preparation. "
            "Validated live printer path is Prusa MK4S -> PrusaSlicer -> PrusaLink Digest auth -> USB storage -> upload/start. "
            "Live mode may physically print after `실험 수행`; test modes stay virtual/read-only unless the operator explicitly selects `실제 출력` at the Specimen Making Agent printer-path prompt or sends `테스트 모드, 실제 출력`. "
            "Auto ejection uses a gated bed-sweep append G-code path when explicitly enabled. "
            "Do not use LaTeX route notation such as $\\rightarrow$; use '->' only."
        )

    def _planning_state_context(self) -> dict[str, Any]:
        """Return a compact state summary instead of the full controller state JSON."""
        spec = self._state.current_experiment_spec if isinstance(self._state.current_experiment_spec, dict) else {}
        return {
            "run_id": self._state.run_id,
            "mode": self._state.mode.value,
            "stage": self._state.stage.value,
            "loop_count": self._state.loop_count,
            "active_goal": self._state.active_goal,
            "current_specimen_id": spec.get("specimen_id"),
            "current_geometry_type": spec.get("geometry_type"),
        }

    def _planning_memory_context(self, *, limit: int = 10, max_chars: int = 1200) -> str:
        """Build compact, session-scoped conversation memory for Live GUI prompts."""
        if not self._planning_messages:
            return "No prior Live GUI messages in this session."
        lines: list[str] = []
        for msg in self._planning_messages[-limit:]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "unknown")).strip() or "unknown"
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            if len(content) > max_chars:
                content = content[:max_chars] + "..."
            model = str(msg.get("model", "")).strip()
            model_part = f" model={model}" if model else ""
            lines.append(f"{role}{model_part}: {content}")
        return "\n\n".join(lines) if lines else "No prior Live GUI messages in this session."

    async def _complete_live_planning_prompt(
        self,
        *,
        prompt: str,
    ):
        """Call the existing orchestrator_plan route for the Live GUI orchestrator chat."""
        timeout_s = self._live_gui_timeout_s()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = await self._deps.agent_context.complete(
                    "orchestrator_plan",
                    prompt,
                    timeout_s=timeout_s,
                )
                suffix = " after retry" if attempt else ""
                return response, f"Live GUI orchestrator_plan call completed{suffix}. model={response.model}"
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    # MTP/NVFP4 serving can JIT a few kernels on the first real generation
                    # after readiness. Retry internally so transient cold-start failures do
                    # not become a visible chat failure before the next operator action.
                    await asyncio.sleep(2.0)
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError("Live GUI orchestrator_plan call failed without an exception.")

    @staticmethod
    def _extract_reasoning(raw: dict[str, Any]) -> str:
        """Extract model reasoning text from OpenAI/vLLM or Ollama-style responses."""
        if not isinstance(raw, dict):
            return ""
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    for key in ("reasoning", "reasoning_content", "thinking"):
                        value = str(message.get(key, "")).strip()
                        if value and value.lower() != "none":
                            return value
                    # Fallback for Gemma-style channel output when parser output is absent.
                    content = str(message.get("content", ""))
                    match = re.search(r"<\|channel\>\s*thought\s*(.*?)<channel\|>", content, flags=re.DOTALL)
                    if match:
                        return match.group(1).strip()
        message = raw.get("message")
        if isinstance(message, dict):
            for key in ("thinking", "reasoning", "reasoning_content"):
                value = str(message.get(key, "")).strip()
                if value:
                    return value
        for key in ("thinking", "reasoning", "reasoning_content"):
            value = str(raw.get(key, "")).strip()
            if value:
                return value
        return ""

    def _live_gui_timeout_s(self) -> float:
        """Resolve Live GUI orchestrator route timeout."""
        timeout_s = float(os.getenv(
            "AUTONOMOUS_PLANNING_PRIMARY_TIMEOUT_S",
            str(self._deps.system_config.get("planning_primary_timeout_seconds", 240)),
        ))
        return max(30.0, timeout_s)

    @staticmethod
    def _load_optional_guideline(path: Path, *, limit: int) -> str:
        """Read a local guideline snippet when available."""
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()[:limit]

    def _should_trigger_design(self, message: str) -> bool:
        """Detect operator intent to move from orchestration discussion into design generation."""
        normalized = re.sub(r"\s+", "", message.lower())
        triggers = {"실험수행", "실험진행", "설계수행", "디자인수행", "runexperiment", "startexperiment"}
        return any(trigger in normalized for trigger in triggers)

    @staticmethod
    def _is_generic_planning_goal(value: Any) -> bool:
        """Return whether a goal is a GUI/bootstrap placeholder rather than operator input."""
        text = str(value or "").strip().lower()
        if not text:
            return True
        generic_fragments = (
            "build autonomous",
            "terminal live gui session",
            "design and validate a live-mode specimen plan",
            "autonomous ai researcher",
        )
        return any(fragment in text for fragment in generic_fragments)

    @staticmethod
    def _clean_design_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
        """Keep only concrete experiment-design values, not GUI transport metadata."""
        ignored = {"runtime_contract", "require_operator_approval"}
        cleaned: dict[str, Any] = {}
        for key, value in (constraints or {}).items():
            if key in ignored or value in (None, "", []):
                continue
            cleaned[key] = value
        return cleaned

    @staticmethod
    def _coerce_size_vector(value: Any) -> list[float] | None:
        """Normalize a 3D size vector when present."""
        if isinstance(value, (list, tuple)) and len(value) == 3:
            try:
                parsed = [float(item) for item in value]
            except (TypeError, ValueError):
                return None
            if all(item > 0 for item in parsed):
                return parsed
        return None

    @staticmethod
    def _extract_size_from_text(text: str) -> list[float] | None:
        """Extract dimensions like 30 x 30 x 30 mm from operator text."""
        pattern = (
            r"(\d+(?:\.\d+)?)\s*(?:mm|밀리|미리)?\s*"
            r"(?:x|×|\*)\s*"
            r"(\d+(?:\.\d+)?)\s*(?:mm|밀리|미리)?\s*"
            r"(?:x|×|\*)\s*"
            r"(\d+(?:\.\d+)?)\s*(?:mm|밀리|미리)?"
        )
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            return None
        return [float(match.group(idx)) for idx in range(1, 4)]

    @staticmethod
    def _extract_material_from_text(text: str) -> str:
        """Extract common 3DP material names from operator text."""
        upper = text.upper()
        for material in ("PLA", "PETG", "TPU", "ABS", "ASA", "PA", "NYLON", "RESIN"):
            if re.search(rf"(?<![A-Z0-9]){re.escape(material)}(?![A-Z0-9])", upper):
                return "Nylon" if material in {"PA", "NYLON"} else material
        if "나일론" in text:
            return "Nylon"
        if "레진" in text:
            return "resin"
        return ""

    @classmethod
    def _extract_geometry_or_domain_from_text(cls, text: str) -> dict[str, str]:
        """Extract supported geometry or broader lattice domain hints."""
        lowered = text.lower()
        normalized = lowered.replace("-", "_").replace(" ", "_")
        result: dict[str, str] = {}
        geometry_keywords = {
            "gyroid": (
                "gyroid",
                "tpms",
                "tpms_gyroid",
                "gyroid_tpms",
                "metamaterial",
                "bending_dominated",
                "bending-dominated",
                "자이로이드",
                "메타물질",
                "굽힘",
                "벤딩",
            ),
            "auxetic_reentrant": ("auxetic", "reentrant", "re_entrant", "re-entrant", "오제틱"),
            "lattice_octet": ("octet", "옥텟"),
            "lattice_bcc": ("bcc", "body_centered", "body-centered"),
            "lattice_fcc": ("fcc",),
            "honeycomb": ("honeycomb", "허니컴"),
            "random_voronoi": ("voronoi", "보로노이"),
        }
        for geometry, keywords in geometry_keywords.items():
            if any(keyword in lowered or keyword in normalized for keyword in keywords):
                result["geometry_type"] = geometry
                result["preferred_geometry_type"] = geometry
                break
        if "bending" in lowered or "굽힘" in text or "벤딩" in text:
            result["experiment_domain"] = "bending_dominated_lattice"
        elif "lattice" in lowered or "격자" in text:
            result["experiment_domain"] = "lattice"
        elif result.get("geometry_type"):
            result["experiment_domain"] = result["geometry_type"]
        return result

    @staticmethod
    def _extract_objective_from_text(text: str) -> tuple[str, str]:
        """Extract objective type/direction from compact operator text."""
        lowered = text.lower()
        objective = ""
        direction = "maximize"
        if any(token in lowered for token in ("energy absorption", "specific energy", "sea", "에너지 흡수", "흡수량")):
            objective = "specific_energy_absorption"
        elif any(token in lowered for token in ("stiffness", "강성")):
            objective = "stiffness"
        elif any(token in lowered for token in ("mass", "질량", "무게")):
            objective = "mass"
        elif any(token in lowered for token in ("strength", "강도")):
            objective = "strength"
        if any(token in lowered for token in ("minimize", "minimum", "최소화", "줄이")):
            direction = "minimize"
        if any(token in lowered for token in ("maximize", "maximum", "최대화", "높이", "늘리")):
            direction = "maximize"
        return objective, direction

    def _extract_design_values_from_text(self, text: str) -> dict[str, Any]:
        """Extract concrete design values from one operator message."""
        values: dict[str, Any] = {}
        size = self._extract_size_from_text(text)
        if size:
            values["specimen_size_mm"] = size
            values["max_specimen_size_mm"] = size
        material = self._extract_material_from_text(text)
        if material:
            values["material"] = material
        values.update(self._extract_geometry_or_domain_from_text(text))
        objective, direction = self._extract_objective_from_text(text)
        if objective:
            values["objective_type"] = objective
            values["objective_direction"] = direction
        if re.search(r"\bprusa\s*mk4s?\b", text, flags=re.IGNORECASE):
            values["printer_model"] = "Prusa MK4S"
        elif re.search(r"\bprusa\s*mk3s?\b", text, flags=re.IGNORECASE):
            values["printer_model"] = "Prusa MK3S"
        nozzle = re.search(r"(?:nozzle|노즐)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*mm", text, flags=re.IGNORECASE)
        if nozzle:
            values["nozzle_diameter_mm"] = float(nozzle.group(1))
        layer = re.search(r"(?:layer|레이어)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*mm", text, flags=re.IGNORECASE)
        if layer:
            values["layer_height_mm"] = float(layer.group(1))
        first_layer_height = re.search(
            r"(?:first\s*layer\s*height|첫\s*레이어\s*높이|초층\s*높이)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*mm",
            text,
            flags=re.IGNORECASE,
        )
        if first_layer_height:
            values["first_layer_height_mm"] = float(first_layer_height.group(1))
        first_layer_speed = re.search(
            r"(?:first\s*layer\s*speed|첫\s*레이어\s*속도|초층\s*속도)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:mm/s|mm\/s)?",
            text,
            flags=re.IGNORECASE,
        )
        if first_layer_speed:
            values["first_layer_speed_mm_s"] = float(first_layer_speed.group(1))
        bed_temp = re.search(
            r"(?:bed\s*(?:temperature|temp)|베드\s*온도)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:c|°c|도)?",
            text,
            flags=re.IGNORECASE,
        )
        if bed_temp:
            values["bed_temperature_c"] = float(bed_temp.group(1))
        first_layer_bed_temp = re.search(
            r"(?:first\s*layer\s*bed\s*(?:temperature|temp)|첫\s*레이어\s*베드\s*온도|초층\s*베드\s*온도)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:c|°c|도)?",
            text,
            flags=re.IGNORECASE,
        )
        if first_layer_bed_temp:
            values["first_layer_bed_temperature_c"] = float(first_layer_bed_temp.group(1))
        max_time = re.search(r"(?:max(?:imum)?\s*print\s*time|최대\s*출력\s*시간|출력\s*시간)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(?:min|분)?", text, flags=re.IGNORECASE)
        if max_time:
            values["max_print_time_min"] = float(max_time.group(1))
        if any(token in text.lower() for token in ("usb", "유에스비")):
            values["storage"] = "usb"
        lowered = text.lower()
        compact = re.sub(r"\s+", "", lowered)
        if any(token in compact for token in ("스커트켜", "skirton", "brimon", "rafton")):
            values["skirt_enabled"] = True
        if any(token in compact for token in ("스커트꺼", "스커트없이", "skirtoff", "brimoff", "raftoff", "noskirt")):
            values["skirt_enabled"] = False
        explicit_top_cap = False
        explicit_bottom_cap = False
        if any(token in compact for token in ("상단캡켜", "상부캡켜", "topcapon", "topcapson")):
            values["top_cap_enabled"] = True
            explicit_top_cap = True
        if any(token in compact for token in ("상단캡꺼", "상단캡없이", "상부캡꺼", "topcapoff", "notopcap")):
            values["top_cap_enabled"] = False
            explicit_top_cap = True
        if any(token in compact for token in ("하단캡켜", "하부캡켜", "bottomcapon", "bottomcapson")):
            values["bottom_cap_enabled"] = True
            explicit_bottom_cap = True
        if any(token in compact for token in ("하단캡꺼", "하단캡없이", "하부캡꺼", "bottomcapoff", "nobottomcap")):
            values["bottom_cap_enabled"] = False
            explicit_bottom_cap = True
        if any(token in compact for token in ("평판켜", "캡켜", "flatcapon", "capson")) and not (explicit_top_cap or explicit_bottom_cap):
            values["top_cap_enabled"] = False
            values["bottom_cap_enabled"] = True
            values["top_bottom_cap"] = True
            values["require_flat_compression_faces"] = False
            if "skin_thickness_mm" not in values:
                values["skin_thickness_mm"] = 0.8
        if explicit_top_cap or explicit_bottom_cap:
            top_cap = bool(values.get("top_cap_enabled", False))
            bottom_cap = bool(values.get("bottom_cap_enabled", True))
            values["top_bottom_cap"] = bool(top_cap or bottom_cap)
            values["require_flat_compression_faces"] = bool(top_cap and bottom_cap)
            if values["top_bottom_cap"] and "skin_thickness_mm" not in values:
                values["skin_thickness_mm"] = 0.8
        if any(token in compact for token in ("평판꺼", "평판없이", "캡꺼", "캡없이", "flatcapoff", "nocap")) and not (
            explicit_top_cap or explicit_bottom_cap
        ):
            values["top_cap_enabled"] = False
            values["bottom_cap_enabled"] = False
            values["top_bottom_cap"] = False
            values["require_flat_compression_faces"] = False
            values["skin_thickness_mm"] = 0.0
        if any(token in text for token in ("실제 출력", "실제 프린트", "출력까지", "프린트까지")):
            values["physical_print_intent"] = True
        return values

    @staticmethod
    def _validated_printer_defaults() -> dict[str, Any]:
        """Return operator-controlled MK4S/PrusaLink defaults."""
        profile = load_prusa_print_profile()
        allowed = (
            "material",
            "printer_model",
            "printer_profile",
            "slicer_profile_hint",
            "nozzle_diameter_mm",
            "layer_height_mm",
            "first_layer_height_mm",
            "slow_first_layer_enabled",
            "first_layer_speed_mm_s",
            "bed_temperature_c",
            "first_layer_bed_temperature_c",
            "storage",
            "max_print_time_min",
            "overwrite",
            "start_immediately_live",
            "allow_ejection",
            "skirt_enabled",
            "top_cap_enabled",
            "bottom_cap_enabled",
            "top_bottom_cap",
            "skin_thickness_mm",
            "require_flat_compression_faces",
            "test_specimen_size_mm",
            "test_unit_cell_size_mm",
        )
        return {key: profile[key] for key in allowed if key in profile}

    def _with_validated_printer_defaults(self, constraints: dict[str, Any]) -> dict[str, Any]:
        """Apply validated printer defaults while preserving operator overrides."""
        merged = dict(self._validated_printer_defaults())
        merged.update({key: value for key, value in constraints.items() if value not in (None, "", [])})
        return merged

    def _planning_design_handoff_readiness(self, *, goal: str | None, constraints: dict[str, Any]) -> dict[str, Any]:
        """Collect current Live GUI design inputs and decide whether handoff can proceed."""
        merged_constraints: dict[str, Any] = {}
        detected_goal = "" if self._is_generic_planning_goal(goal) else str(goal or "").strip()

        for entry in self._planning_messages:
            if not isinstance(entry, dict) or entry.get("role") != "operator":
                continue
            entry_constraints = entry.get("constraints") if isinstance(entry.get("constraints"), dict) else {}
            merged_constraints.update(self._clean_design_constraints(entry_constraints))
            content = str(entry.get("content", ""))
            extracted = self._extract_design_values_from_text(content)
            merged_constraints.update({key: value for key, value in extracted.items() if value not in (None, "", [])})
            if not detected_goal and not self._should_trigger_design(content):
                maybe_objective, _ = self._extract_objective_from_text(content)
                if maybe_objective or any(token in content for token in ("실험", "시편", "압축", "compression")):
                    detected_goal = content.strip()

        merged_constraints.update(self._clean_design_constraints(constraints))
        merged_constraints = self._with_validated_printer_defaults(merged_constraints)
        if not detected_goal and not self._is_generic_planning_goal(self._state.active_goal):
            detected_goal = self._state.active_goal

        size = self._coerce_size_vector(
            merged_constraints.get("specimen_size_mm") or merged_constraints.get("max_specimen_size_mm")
        )
        if size:
            merged_constraints["specimen_size_mm"] = size
            merged_constraints["max_specimen_size_mm"] = size

        has_goal = bool(detected_goal)
        has_material = bool(str(merged_constraints.get("material", "")).strip())
        has_size = bool(size)
        has_domain = bool(
            str(merged_constraints.get("geometry_type", "")).strip()
            or str(merged_constraints.get("preferred_geometry_type", "")).strip()
            or str(merged_constraints.get("experiment_domain", "")).strip()
        )

        missing: list[dict[str, str]] = []
        if not has_goal:
            missing.append(
                {
                    "field": "실험 목표/평가지표",
                    "key": "objective",
                    "example": "예: 압축 시편의 specific energy absorption을 최대화",
                }
            )
        if not has_material:
            missing.append({"field": "재료", "key": "material", "example": "예: PLA 또는 PETG"})
        if not has_size:
            missing.append({"field": "시편 크기", "key": "specimen_size_mm", "example": "예: 30 x 30 x 30 mm"})
        if not has_domain:
            missing.append(
                {
                    "field": "구조/실험 domain",
                    "key": "geometry_or_domain",
                    "example": "예: TPMS gyroid, gyroid metamaterial, BCC lattice",
                }
            )
        return {"goal": detected_goal, "constraints": merged_constraints, "missing": missing}

    def _format_design_readiness_message(self, readiness: dict[str, Any]) -> str:
        """Describe current and missing values before DesignAgent handoff."""
        constraints = readiness.get("constraints", {}) if isinstance(readiness.get("constraints"), dict) else {}
        goal = str(readiness.get("goal") or "").strip()

        def value_or_missing(value: Any) -> str:
            if value in (None, "", []):
                return "미입력"
            if isinstance(value, list):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        current_rows = [
            ("실험 목표/평가지표", goal),
            ("재료", constraints.get("material")),
            ("시편 크기 mm", constraints.get("specimen_size_mm") or constraints.get("max_specimen_size_mm")),
            (
                "구조/domain",
                constraints.get("geometry_type")
                or constraints.get("preferred_geometry_type")
                or constraints.get("experiment_domain"),
            ),
            ("프린터", constraints.get("printer_model")),
            ("노즐/레이어", self._join_optional_values([constraints.get("nozzle_diameter_mm"), constraints.get("layer_height_mm")], " / ")),
            ("첫 레이어 높이", constraints.get("first_layer_height_mm")),
            (
                "첫 레이어 속도 저하",
                f"{constraints.get('first_layer_speed_mm_s')} mm/s" if constraints.get("slow_first_layer_enabled", True) else "미사용",
            ),
            (
                "베드 온도",
                self._join_optional_values(
                    [constraints.get("bed_temperature_c"), constraints.get("first_layer_bed_temperature_c")],
                    " / ",
                ),
            ),
            ("최대 출력시간", constraints.get("max_print_time_min")),
            ("PrusaLink storage", constraints.get("storage")),
            ("스커트/브림/래프트", "사용" if constraints.get("skirt_enabled") else "미사용"),
            (
                "cap/skin",
                (
                    f"bottom={bool(constraints.get('bottom_cap_enabled'))}, "
                    f"top={bool(constraints.get('top_cap_enabled'))}, "
                    f"skin={constraints.get('skin_thickness_mm', 0.0)} mm"
                )
                if constraints.get("top_bottom_cap")
                else "미사용",
            ),
            ("실제 출력", "live mode에서 실험 수행 시 upload/start"),
        ]
        missing = readiness.get("missing", [])
        missing_lines = [
            f"- {item['field']}: {item['example']}"
            for item in missing
            if isinstance(item, dict) and item.get("field")
        ]
        return (
            "아직 Design Agent로 넘기기엔 필수 실험값이 부족합니다. 임의값으로 진행하지 않고, 아래 값을 먼저 확인하겠습니다.\n\n"
            "현재 확인된 값:\n"
            + "\n".join(f"- {label}: {value_or_missing(value)}" for label, value in current_rows)
            + "\n\n"
            "추가로 필요한 값:\n"
            + "\n".join(missing_lines)
            + "\n\n"
            "한 번에 입력하는 예:\n"
            "\"PLA로 30 x 30 x 30 mm TPMS gyroid 압축 시편을 만들고, "
            "specific energy absorption을 최대화. FDM 출력 가능한 closed-shell 구조로 하고, "
            "프린터는 Prusa MK4S, nozzle 0.4 mm, layer 0.2 mm, "
            "최대 출력 시간 120분. 실험 수행\""
        )

    @staticmethod
    def _join_optional_values(values: list[Any], sep: str) -> str:
        """Join non-empty values for compact display."""
        clean = [str(value) for value in values if value not in (None, "", [])]
        return sep.join(clean)

    async def _request_missing_design_values(
        self,
        readiness: dict[str, Any],
        *,
        session_id: str | None,
    ) -> dict[str, Any]:
        """Ask the operator for required values instead of fabricating a design."""
        content = self._format_design_readiness_message(readiness)
        await self._append_planning_message(
            {
                "role": "orchestrator",
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "orchestrator_plan",
                "ok": True,
                "requires_design_inputs": True,
                "current_design_inputs": readiness.get("constraints", {}),
                "missing_design_inputs": readiness.get("missing", []),
            },
            event_type="planning_design_inputs_required",
            message="Design handoff blocked until required operator inputs are provided.",
            level="INFO",
        )
        return {
            "ok": True,
            "message": "Design handoff requires operator inputs.",
            "session": self.planning_snapshot(session_id=session_id),
        }

    @staticmethod
    def _should_trigger_test_design(message: str) -> bool:
        """Detect Live GUI shortcut for creating a default test design handoff."""
        normalized = re.sub(r"\s+", "", message.lower())
        return normalized in {"테스트모드", "testmode", "test"} or "테스트모드" in normalized

    def _default_test_constraints(self, constraints: dict[str, Any]) -> dict[str, Any]:
        """Fill missing Live GUI constraints with deterministic test-mode defaults."""
        printer_defaults = self._validated_printer_defaults()
        test_unit_cell_size_mm = float(printer_defaults.get("test_unit_cell_size_mm", 10.0))
        defaults: dict[str, Any] = {
            "material": printer_defaults.get("material", "PLA"),
            "max_specimen_size_mm": printer_defaults.get("test_specimen_size_mm", [30, 30, 30]),
            "max_print_time_min": printer_defaults.get("max_print_time_min", 120),
            "geometry_type": MainController.TEST_MODE_FIXED_GEOMETRY,
            "preferred_geometry_type": MainController.TEST_MODE_FIXED_GEOMETRY,
            "specimen_size_mm": printer_defaults.get("test_specimen_size_mm", [30, 30, 30]),
            "objective_type": "specific_energy_absorption",
            "objective_direction": "maximize",
            "infill_pattern": MainController.TEST_MODE_FIXED_GEOMETRY,
            "infill_density_percent": 35,
            "layer_height_mm": printer_defaults.get("layer_height_mm", 0.2),
            "first_layer_height_mm": printer_defaults.get("first_layer_height_mm", printer_defaults.get("layer_height_mm", 0.2)),
            "slow_first_layer_enabled": printer_defaults.get("slow_first_layer_enabled", True),
            "first_layer_speed_mm_s": printer_defaults.get("first_layer_speed_mm_s", 10.0),
            "bed_temperature_c": printer_defaults.get("bed_temperature_c", 60.0),
            "first_layer_bed_temperature_c": printer_defaults.get("first_layer_bed_temperature_c", 60.0),
            "wall_thickness_mm": 1.2,
            "cell_size_mm": test_unit_cell_size_mm,
            "relative_density": 0.32,
            "skin_thickness_mm": printer_defaults.get("skin_thickness_mm", 0.8),
            "top_cap_enabled": printer_defaults.get("top_cap_enabled", False),
            "bottom_cap_enabled": printer_defaults.get("bottom_cap_enabled", True),
            "top_bottom_cap": printer_defaults.get("top_bottom_cap", True),
            "skirt_enabled": printer_defaults.get("skirt_enabled", False),
            "tpms_surface": "gyroid",
            "tpms_thickness": 0.38,
            "tpms_resolution": 72,
            "printability_mode": "fdm_closed_shell",
            "require_flat_compression_faces": printer_defaults.get("require_flat_compression_faces", False),
            "fdm_min_wall_thickness_mm": 1.2,
            "fdm_max_bridge_distance_mm": min(test_unit_cell_size_mm, 10.0),
            "fdm_max_unsupported_overhang_deg": 45.0,
            "fdm_max_gyroid_wall_cell_ratio": 0.28,
            "printer_model": printer_defaults.get("printer_model", "Prusa MK4S"),
            "printer_profile": printer_defaults.get("printer_profile", "prusa_mk4s_pla_0p4_nozzle"),
            "slicer_profile_hint": printer_defaults.get("slicer_profile_hint", "0.2mm_quality"),
            "nozzle_diameter_mm": printer_defaults.get("nozzle_diameter_mm", 0.4),
            "storage": printer_defaults.get("storage", "usb"),
            "print": {
                "storage": printer_defaults.get("storage", "usb"),
                "start_immediately": False,
                "overwrite": printer_defaults.get("overwrite", True),
                "physical_intent": False,
                "skirt_enabled": printer_defaults.get("skirt_enabled", False),
            },
            "ejection": {"enabled": bool(printer_defaults.get("allow_ejection", False))},
            "test_mode_autofill": True,
        }
        merged = dict(defaults)
        merged.update({key: value for key, value in constraints.items() if value not in (None, "", [])})
        geometry = MainController._normalize_planning_geometry_type(merged.get("geometry_type")) or MainController.TEST_MODE_FIXED_GEOMETRY
        merged["geometry_type"] = geometry
        merged["preferred_geometry_type"] = MainController._normalize_planning_geometry_type(
            merged.get("preferred_geometry_type") or geometry
        ) or geometry
        return merged

    @staticmethod
    def _extract_test_mode_payload(text: str) -> dict[str, Any]:
        """Parse the orchestrator's test-mode JSON block when available."""
        matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        candidates = matches or re.findall(r"(\{.*\})", text, flags=re.DOTALL)
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        return {}

    @staticmethod
    def _normalize_test_mode_constraints(defaults: dict[str, Any], llm_constraints: dict[str, Any]) -> dict[str, Any]:
        """Merge LLM-selected test values with safe defaults and normalize equivalent size keys."""
        merged = dict(defaults)
        merged.update({key: value for key, value in llm_constraints.items() if value not in (None, "", [])})
        if "specimen_size_mm" in merged and "max_specimen_size_mm" not in llm_constraints:
            merged["max_specimen_size_mm"] = merged["specimen_size_mm"]
        if "max_specimen_size_mm" in merged and "specimen_size_mm" not in llm_constraints:
            merged["specimen_size_mm"] = merged["max_specimen_size_mm"]
        forced_geometry = MainController.TEST_MODE_FIXED_GEOMETRY
        merged["geometry_type"] = forced_geometry
        merged["preferred_geometry_type"] = forced_geometry
        merged["infill_pattern"] = forced_geometry
        merged["tpms_surface"] = "gyroid"
        merged["cell_size_mm"] = float(defaults.get("cell_size_mm", merged.get("cell_size_mm", 10.0)))
        merged["tpms_thickness"] = merged.get("tpms_thickness", 0.38)
        merged["tpms_resolution"] = merged.get("tpms_resolution", 72)
        merged["printability_mode"] = "fdm_closed_shell"
        explicit_top_cap = "top_cap_enabled" in llm_constraints
        explicit_bottom_cap = "bottom_cap_enabled" in llm_constraints
        explicit_legacy_cap = "top_bottom_cap" in llm_constraints
        if explicit_top_cap or explicit_bottom_cap:
            merged["top_cap_enabled"] = bool(merged.get("top_cap_enabled", defaults.get("top_cap_enabled", False)))
            merged["bottom_cap_enabled"] = bool(merged.get("bottom_cap_enabled", defaults.get("bottom_cap_enabled", True)))
        elif explicit_legacy_cap:
            legacy_cap = bool(merged.get("top_bottom_cap", defaults.get("top_bottom_cap", True)))
            merged["top_cap_enabled"] = False
            merged["bottom_cap_enabled"] = legacy_cap
        else:
            merged["top_cap_enabled"] = bool(defaults.get("top_cap_enabled", False))
            merged["bottom_cap_enabled"] = bool(defaults.get("bottom_cap_enabled", True))
        merged["top_bottom_cap"] = bool(merged["top_cap_enabled"] or merged["bottom_cap_enabled"])
        if merged["top_bottom_cap"]:
            merged["skin_thickness_mm"] = max(
                0.2,
                float(merged.get("skin_thickness_mm", defaults.get("skin_thickness_mm", 0.8)) or 0.8),
            )
            merged["require_flat_compression_faces"] = bool(
                merged.get("require_flat_compression_faces", defaults.get("require_flat_compression_faces", False))
                and merged["top_cap_enabled"]
                and merged["bottom_cap_enabled"]
            )
        else:
            merged["skin_thickness_mm"] = 0.0
            merged["require_flat_compression_faces"] = False
        merged["fdm_min_wall_thickness_mm"] = merged.get("fdm_min_wall_thickness_mm", 1.2)
        merged["fdm_max_bridge_distance_mm"] = merged.get("fdm_max_bridge_distance_mm", 10.0)
        merged["fdm_max_unsupported_overhang_deg"] = merged.get("fdm_max_unsupported_overhang_deg", 45.0)
        merged["fdm_max_gyroid_wall_cell_ratio"] = merged.get("fdm_max_gyroid_wall_cell_ratio", 0.28)
        merged["print"] = {
            **{"storage": "usb", "start_immediately": False, "overwrite": True, "physical_intent": False},
            **(merged.get("print") if isinstance(merged.get("print"), dict) else {}),
            "start_immediately": False,
            "physical_intent": False,
            "skirt_enabled": bool(merged.get("skirt_enabled", defaults.get("skirt_enabled", False))),
        }
        default_ejection = defaults.get("ejection") if isinstance(defaults.get("ejection"), dict) else {}
        requested_ejection = merged.get("ejection") if isinstance(merged.get("ejection"), dict) else {}
        merged["ejection"] = {
            **default_ejection,
            **requested_ejection,
            "enabled": bool(requested_ejection.get("enabled", default_ejection.get("enabled", False))),
        }
        merged["test_mode_llm_generated"] = True
        return merged

    @staticmethod
    def _normalize_planning_geometry_type(value: Any) -> str:
        """Normalize legacy Live GUI geometry names into supported specimen-design names."""
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "lattice": "gyroid",
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
            "compression_cube": "gyroid",
            "cube": "gyroid",
        }
        normalized = aliases.get(text, normalize_tpms_geometry_type(text))
        supported = {
            "lattice_bcc",
            "lattice_fcc",
            "lattice_octet",
            "gyroid",
            "honeycomb",
            "auxetic_reentrant",
            "random_voronoi",
        }
        return normalized if normalized in supported else ""

    async def _handoff_planning_to_design(
        self,
        *,
        goal: str | None,
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        """Call DesignAgent for planning-only candidate generation and emit handoff chat messages."""
        self._state.active_goal = goal or self._state.active_goal
        await self._append_planning_message(
            {
                "role": "orchestrator",
                "content": "승인 키워드를 확인했습니다. DesignAgent → Specimen Making Agent → Guardian 순서로 workflow를 실행합니다.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "orchestrator_plan",
                "ok": True,
            },
            event_type="planning_message",
            message="Orchestrator approved DesignAgent -> Specimen Making Agent handoff.",
        )
        await self._append_planning_message(
            {
                "role": "system",
                "content": "Handoff: OrchestratorAgent -> DesignAgent. Design Agent가 시편 후보를 생성하고 Specimen Making Agent로 실행 인계를 전달합니다.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": True,
            },
            event_type="planning_handoff",
            message="Planning handoff to DesignAgent started.",
        )

        try:
            design_constraints = dict(constraints)
            geometry_hint = self._normalize_planning_geometry_type(design_constraints.get("geometry_type"))
            if geometry_hint:
                design_constraints["geometry_type"] = geometry_hint
                design_constraints["preferred_geometry_type"] = self._normalize_planning_geometry_type(
                    design_constraints.get("preferred_geometry_type") or geometry_hint
                ) or geometry_hint
            previous_spec = dict(self._state.current_experiment_spec or {})
            previous_constraints = previous_spec.get("constraints") if isinstance(previous_spec.get("constraints"), dict) else {}
            self._state.current_experiment_spec = {
                **previous_spec,
                **{key: value for key, value in design_constraints.items() if key in {"geometry_type", "specimen_size_mm"}},
                "constraints": {**previous_constraints, **design_constraints},
            }
            design_agent = self._deps.agent_registry.get("design_agent")
            result = await design_agent.run(self._state, self._deps.agent_context)
            if not result.success:
                raise RuntimeError(f"DesignAgent failed: {result.summary}")
            base_spec = dict(result.data.get("experiment_spec", {}))
            if not base_spec:
                raise RuntimeError("DesignAgent did not return experiment_spec.")
            design_model = result.data.get("experiment_spec", {}).get("model_note", "design_agent")
            experiment_spec = self._build_planning_spec(base_spec=base_spec, constraints=design_constraints)
            self._state.current_experiment_spec = experiment_spec
            artifact = self._write_planning_artifacts(experiment_spec)

            design_message = (
                "Design Agent가 후보 시편 설계를 생성했습니다.\n\n"
                f"- specimen_id: {experiment_spec['specimen_id']}\n"
                f"- geometry_type: {experiment_spec['geometry_type']}\n"
                f"- specimen_size_mm: {experiment_spec['specimen_size_mm']}\n"
                f"- wall_thickness_mm: {experiment_spec['wall_thickness_mm']}\n"
                f"- cell_size_mm: {experiment_spec['cell_size_mm']}\n"
                f"- expected_mass_g: {experiment_spec['expected_mass_g']}\n"
                f"- expected_print_time_min: {experiment_spec['expected_print_time_min']}\n\n"
                "시편 설계안과 실행용 입력값을 생성했습니다. 다음 단계는 Specimen Making Agent와 Guardian 검증입니다."
            )
            await self._append_planning_message(
                {
                    "role": "design_ai",
                    "content": design_message,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": design_model,
                    "ok": True,
                    "experiment_spec": experiment_spec,
                    "artifacts": artifact,
                },
                event_type="planning_design_result",
                message="DesignAgent generated planning artifacts.",
            )
            await self._append_planning_message(
                {
                    "role": "system",
                    "content": "Handoff: DesignAgent -> Specimen Making Agent. 시편 출력을 위한 준비 패키지 작성과 프린터 호출을 수행합니다.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": True,
                },
                event_type="planning_handoff",
                message="Planning handoff to Specimen Making Agent started.",
            )
            specimen_agent = self._deps.agent_registry.get("specimen_agent")
            specimen_result = await specimen_agent.run(self._state, self._deps.agent_context)
            if not specimen_result.success:
                raise RuntimeError(f"SpecimenMakingAgent failed: {specimen_result.summary}")

            specimen_payload = specimen_result.data.get("specimen_result", {})
            if not isinstance(specimen_payload, dict):
                raise RuntimeError("SpecimenMakingAgent did not return specimen_result.")
            if specimen_payload.get("requires_operator_input"):
                await self._record_pending_specimen_input(specimen_payload)
                self._schedule_post_run_vllm_transition()
                return {
                    "ok": True,
                    "message": "SpecimenMakingAgent waiting for operator input.",
                    "session": self.planning_snapshot(),
                }
            specimen_artifacts = self._write_planning_artifacts(experiment_spec, specimen_result=specimen_payload)
            specimen_message = self._format_specimen_runtime_message(experiment_spec, specimen_payload)
            await self._append_planning_message(
                {
                    "role": "printer_ai",
                    "content": specimen_message,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": "specimen_agent",
                    "ok": True,
                    "specimen": specimen_payload,
                    "specimen_artifacts": specimen_artifacts,
                    "render_artifacts": False,
                },
                event_type="planning_specimen_result",
                message="SpecimenMakingAgent completed Specimen Making Agent handoff preparation.",
            )

            guardian_agent = self._deps.agent_registry.get("guardian_agent")
            guardian_result = await guardian_agent.run(self._state, self._deps.agent_context)
            guardian_payload = (
                guardian_result.data.get("guardian", {})
                if isinstance(guardian_result.data.get("guardian", {}), dict)
                else {}
            )
            self._state.run_metadata["guardian"] = guardian_payload

            decision = str(guardian_payload.get("decision", "continue")).strip() or "continue"
            action = str(guardian_payload.get("action", "")).strip()
            reason = str(guardian_payload.get("reason", "")).strip()
            precursor = guardian_payload.get("precursor", "")
            design_validation = guardian_payload.get("design_validation", {})
            health_validation = guardian_payload.get("health_validation", {})
            consistency = guardian_payload.get("consistency", {})

            guardian_content = (
                "Guardian Agent 검증 결과:\n\n"
                f"- decision: {decision}\n"
                f"- action: {action or 'continue'}\n"
                f"- reason: {reason or 'n/a'}\n"
                f"- precursor: {precursor}\n"
                f"- design_validation: {json.dumps(design_validation, ensure_ascii=False)}\n"
                f"- health_validation: {json.dumps(health_validation, ensure_ascii=False)}\n"
                f"- consistency: {json.dumps(consistency, ensure_ascii=False)}"
            )
            await self._append_planning_message(
                {
                    "role": "guardian",
                    "content": guardian_content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "model": "guardian_agent",
                    "ok": bool(guardian_result.success),
                    "guardian": guardian_payload,
                },
                event_type="planning_guardian_result",
                message="GuardianAgent validation completed.",
                level="INFO" if guardian_result.success else "ERROR",
            )

            if decision in {"stop", "error"}:
                await self._append_planning_message(
                    {
                        "role": "system",
                        "content": "Guardian 판정으로 다음 단계 진행이 중단되었습니다. 조건을 수정한 뒤 다시 요청하세요.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": decision != "error",
                    },
                    event_type="planning_handoff",
                    message="Planning flow halted by Guardian decision.",
                    level="WARNING" if decision == "stop" else "ERROR",
                )
            else:
                await self._append_planning_message(
                    {
                        "role": "system",
                        "content": "Guardian 통과. 필요하면 이어서 다음 실험 계획/수행을 요청하세요.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "ok": True,
                    },
                    event_type="planning_handoff",
                    message="Planning flow passed Guardian validation.",
                )

            ok = bool(guardian_result.success) and decision != "error"
            message = "Planning handoff to DesignAgent -> Specimen Making Agent -> GuardianAgent completed."
        except Exception as exc:
            await self._append_planning_message(
                {
                    "role": "design_ai",
                    "content": (
                        "Planning handoff 실패했습니다.\n"
                        f"error={exc.__class__.__name__}: {exc}"
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": False,
                },
                event_type="planning_design_result",
                level="ERROR",
                message="Planning handoff chain failed.",
            )
            ok = False
            message = "Planning handoff chain failed."

        self._schedule_post_run_vllm_transition()
        return {"ok": ok, "message": message, "session": self.planning_snapshot()}

    @staticmethod
    def _runtime_value(value: Any, default: str = "n/a") -> str:
        if value in (None, "", []):
            return default
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _runtime_command(value: Any) -> str:
        if not isinstance(value, list) or not value:
            return "n/a"
        return " ".join(str(item) for item in value)

    @staticmethod
    def _runtime_step_lines(step_trace: Any) -> list[str]:
        if not isinstance(step_trace, list) or not step_trace:
            return ["- n/a"]
        lines: list[str] = []
        for item in step_trace:
            if not isinstance(item, dict):
                continue
            step = str(item.get("step", "UNKNOWN"))
            status = str(item.get("status", "unknown"))
            detail = item.get("detail")
            suffix = f" ({detail})" if detail not in (None, "") else ""
            lines.append(f"- [{status}] {step}{suffix}")
        return lines or ["- n/a"]

    def _format_specimen_runtime_message(
        self,
        experiment_spec: dict[str, Any],
        specimen_payload: dict[str, Any],
    ) -> str:
        tool_result = specimen_payload.get("tool_result") if isinstance(specimen_payload.get("tool_result"), dict) else {}
        settings = specimen_payload.get("slicer_settings") if isinstance(specimen_payload.get("slicer_settings"), dict) else {}
        if not settings and isinstance(tool_result.get("slicer_settings"), dict):
            settings = tool_result["slicer_settings"]
        slicer_result = specimen_payload.get("slicer_result") if isinstance(specimen_payload.get("slicer_result"), dict) else {}
        if not slicer_result and isinstance(tool_result.get("slicer_result"), dict):
            slicer_result = tool_result["slicer_result"]
        gcode_validation = specimen_payload.get("gcode_validation") if isinstance(specimen_payload.get("gcode_validation"), dict) else {}
        printer = specimen_payload.get("printer") if isinstance(specimen_payload.get("printer"), dict) else {}
        prusalink = specimen_payload.get("prusalink") if isinstance(specimen_payload.get("prusalink"), dict) else {}
        print_result = specimen_payload.get("print_result") if isinstance(specimen_payload.get("print_result"), dict) else {}
        upload_result = print_result.get("upload") if isinstance(print_result.get("upload"), dict) else {}
        start_result = print_result.get("start") if isinstance(print_result.get("start"), dict) else {}
        ejection_result = specimen_payload.get("ejection_result") if isinstance(specimen_payload.get("ejection_result"), dict) else {}
        storage_status = self._printer_storage_summary(printer.get("storage"), prusalink.get("storage"))

        lines = [
            "Specimen Making Agent가 PrusaSlicer/PrusaLink 실행 준비를 완료했습니다.",
            "",
            "STL 형상 확인은 Design Agent artifact에서 처리하고, 이 단계는 슬라이싱 설정과 프린터 bridge 진행 상태를 표시합니다.",
            "",
            "PrusaSlicer 적용 설정값:",
            f"- specimen_id: {self._runtime_value(specimen_payload.get('specimen_id', experiment_spec.get('specimen_id')))}",
            f"- printer_profile: {self._runtime_value(settings.get('printer_profile') or experiment_spec.get('printer_profile'))}",
            f"- material: {self._runtime_value(settings.get('material') or experiment_spec.get('material'))}",
            f"- slicer_profile_hint: {self._runtime_value(settings.get('slicer_profile_hint') or experiment_spec.get('slicer_profile_hint'))}",
            f"- layer_height_mm: {self._runtime_value(settings.get('layer_height_mm') or experiment_spec.get('layer_height_mm'))}",
            f"- nozzle_diameter_mm: {self._runtime_value(settings.get('nozzle_diameter_mm') or experiment_spec.get('nozzle_diameter_mm'))}",
            f"- first_layer_height_mm: {self._runtime_value(settings.get('first_layer_height_mm') or experiment_spec.get('first_layer_height_mm'))}",
            f"- slow_first_layer_enabled: {self._runtime_value(settings.get('slow_first_layer_enabled') if 'slow_first_layer_enabled' in settings else experiment_spec.get('slow_first_layer_enabled'))}",
            f"- first_layer_speed_mm_s: {self._runtime_value(settings.get('first_layer_speed_mm_s') or experiment_spec.get('first_layer_speed_mm_s'))}",
            f"- bed_temperature_c: {self._runtime_value(settings.get('bed_temperature_c') or experiment_spec.get('bed_temperature_c'))}",
            f"- first_layer_bed_temperature_c: {self._runtime_value(settings.get('first_layer_bed_temperature_c') or experiment_spec.get('first_layer_bed_temperature_c'))}",
            f"- wall_thickness_mm: {self._runtime_value(settings.get('wall_thickness_mm') or experiment_spec.get('wall_thickness_mm'))}",
            f"- cell_size_mm: {self._runtime_value(settings.get('cell_size_mm') or experiment_spec.get('cell_size_mm'))}",
            f"- relative_density: {self._runtime_value(settings.get('relative_density') or experiment_spec.get('relative_density'))}",
            f"- skirt_enabled: {self._runtime_value(settings.get('skirt_enabled') if 'skirt_enabled' in settings else experiment_spec.get('skirt_enabled'))}",
            f"- bottom_cap_enabled: {self._runtime_value(settings.get('bottom_cap_enabled') if 'bottom_cap_enabled' in settings else experiment_spec.get('bottom_cap_enabled'))}",
            f"- top_cap_enabled: {self._runtime_value(settings.get('top_cap_enabled') if 'top_cap_enabled' in settings else experiment_spec.get('top_cap_enabled'))}",
            f"- top_bottom_cap: {self._runtime_value(settings.get('top_bottom_cap') if 'top_bottom_cap' in settings else experiment_spec.get('top_bottom_cap'))}",
            f"- skin_thickness_mm: {self._runtime_value(settings.get('skin_thickness_mm') if 'skin_thickness_mm' in settings else experiment_spec.get('skin_thickness_mm'))}",
            f"- expected_mass_g: {self._runtime_value(settings.get('expected_mass_g') or specimen_payload.get('expected_mass_g') or experiment_spec.get('expected_mass_g'))}",
            f"- input_model_path: {self._runtime_value(settings.get('input_model_path') or specimen_payload.get('stl_path'))}",
            f"- output_gcode_path: {self._runtime_value(settings.get('output_gcode_path') or specimen_payload.get('sliced_path'))}",
            f"- slicer_simulated: {self._runtime_value(settings.get('simulated'))}",
            f"- slicer_command: {self._runtime_command(settings.get('resolved_command'))}",
            "",
            "PrusaLink/Bridge 결과:",
            f"- printer_prepare_status: {self._runtime_value(specimen_payload.get('printer_prepare_status'))}",
            f"- printer_mode: {self._runtime_value(specimen_payload.get('printer_mode'))}",
            f"- printer_path: {self._runtime_value(specimen_payload.get('printer_path'))}",
            f"- printer_state: {self._runtime_value(printer.get('state'))}",
            f"- prusalink_transport: {self._runtime_value(prusalink.get('transport'))}",
            f"- storage: {storage_status}",
            f"- upload_endpoint: {self._runtime_value(prusalink.get('upload_endpoint'))}",
            f"- upload_status: {self._runtime_value(upload_result.get('status') or upload_result.get('failure_code'))}",
            f"- upload_http_status: {self._runtime_value(upload_result.get('status_code'))}",
            f"- upload_elapsed_sec: {self._runtime_value(upload_result.get('elapsed_sec'))}",
            f"- upload_timeout_sec: {self._runtime_value(upload_result.get('timeout_sec'))}",
            f"- upload_bytes: {self._runtime_value(upload_result.get('bytes'))}",
            f"- start_status: {self._runtime_value(start_result.get('status') or start_result.get('failure_code'), 'ok' if start_result.get('ok') else 'n/a')}",
            f"- start_http_status: {self._runtime_value(start_result.get('status_code'))}",
            f"- gcode_validation: {self._runtime_value(gcode_validation.get('failure_code'), 'ok' if gcode_validation.get('ok') else 'n/a')}",
            f"- slicer_result: {self._runtime_value(slicer_result.get('failure_code'), 'ok' if slicer_result.get('ok') else 'n/a')}",
            f"- print_result: {self._runtime_value(print_result.get('status'))}",
            f"- ejection_result: {self._runtime_value(ejection_result.get('status'))}",
            "",
            "적용 중인 단계:",
            *self._runtime_step_lines(specimen_payload.get("step_trace")),
            "",
            "다음 단계는 GuardianAgent의 제조성/안전성 검증으로 넘깁니다.",
        ]
        return "\n".join(lines)

    @staticmethod
    def _printer_storage_summary(storage_result: Any, selected_storage: Any) -> str:
        """Summarize PrusaLink storage readiness for operator-facing runtime text."""
        selected = str(selected_storage or "usb")
        if not isinstance(storage_result, dict):
            return selected
        if not storage_result.get("ok", False):
            return f"{selected} ({storage_result.get('failure_code', 'status_failed')})"
        payload = storage_result.get("payload") if isinstance(storage_result.get("payload"), dict) else storage_result
        entries = payload.get("storage_list") if isinstance(payload.get("storage_list"), list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or entry.get("path") or "").strip("/")
            if name == selected:
                available = entry.get("available", "unknown")
                read_only = entry.get("read_only", "unknown")
                return f"{selected} available={available} read_only={read_only}"
        return selected

    async def _record_pending_specimen_input(self, specimen_payload: dict[str, Any]) -> None:
        input_request = specimen_payload.get("input_request") if isinstance(specimen_payload.get("input_request"), dict) else {}
        prompt = str(input_request.get("prompt") or "").strip()
        if not prompt:
            operator_messages = specimen_payload.get("operator_messages") if isinstance(specimen_payload.get("operator_messages"), list) else []
            prompt = "\n".join(str(item) for item in operator_messages if str(item).strip())
        prompt = prompt or "Specimen Making Agent가 작업자 입력을 기다립니다."
        self._state.run_metadata["pending_specimen_input"] = {
            "type": str(input_request.get("type") or "specimen_operator_input"),
            "specimen_id": specimen_payload.get("specimen_id"),
            "input_request": input_request,
        }
        await self._append_planning_message(
            {
                "role": "printer_ai",
                "content": prompt,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "specimen_agent",
                "ok": True,
                "pending_operator_input": True,
                "specimen": specimen_payload,
            },
            event_type="planning_specimen_input_required",
            message="SpecimenMakingAgent waiting for operator input.",
        )

    async def _handle_pending_specimen_operator_input(self, *, message: str, session_id: str | None) -> dict[str, Any]:
        pending = self._state.run_metadata.get("pending_specimen_input")
        pending = pending if isinstance(pending, dict) else {}
        request_type = str(pending.get("type", "")).strip()
        if request_type == "printer_test_path_choice":
            choice = self._parse_specimen_printer_choice(message)
            if not choice:
                await self._append_planning_message(
                    {
                        "role": "printer_ai",
                        "content": "Specimen Making Agent 선택지가 명확하지 않습니다. `가상 브릿지`, `설치 프린터`, `실제 출력` 중 하나로 답해주세요.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "model": "specimen_agent",
                        "ok": True,
                        "pending_operator_input": True,
                    },
                    event_type="planning_specimen_input_required",
                    message="SpecimenMakingAgent printer path choice still pending.",
                )
                return {"ok": True, "message": "SpecimenMakingAgent waiting for valid printer path choice.", "session": self.planning_snapshot(session_id=session_id)}

            experiment_spec = self._apply_specimen_printer_choice_to_spec(dict(self._state.current_experiment_spec or {}), choice)
            experiment_spec.setdefault("test_mode_autofill", True)
            experiment_spec.setdefault("test_mode_llm_generated", True)
            self._state.current_experiment_spec = experiment_spec
            self._state.run_metadata.pop("pending_specimen_input", None)
            await self._append_planning_message(
                {
                    "role": "system",
                    "content": (
                        "Specimen Making Agent 입력을 반영했습니다. "
                        + (
                            "테스트 시편을 실제 PrusaSlicer -> PrusaLink upload/start 경로로 출력합니다."
                            if choice == "physical_print"
                            else (
                                "설치 프린터 PrusaLink read-only 통신 테스트로 재시도합니다."
                                if choice == "installed_printer"
                                else "가상 PrusaLink 브릿지로 재시도합니다."
                            )
                        )
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": True,
                },
                event_type="planning_handoff",
                message="SpecimenMakingAgent operator input received.",
            )
            return await self._resume_specimen_after_operator_input(experiment_spec=experiment_spec, session_id=session_id)

        if request_type == "printer_connection_info":
            if not self._is_connection_retry_message(message):
                await self._append_planning_message(
                    {
                        "role": "printer_ai",
                        "content": "`memory/prusa_connection.json`에 PrusaLink host/auth 값을 채운 뒤 `연결정보 입력 완료`라고 보내면 재시도합니다.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "model": "specimen_agent",
                        "ok": True,
                        "pending_operator_input": True,
                    },
                    event_type="planning_specimen_input_required",
                    message="SpecimenMakingAgent connection info still pending.",
                )
                return {"ok": True, "message": "SpecimenMakingAgent waiting for PrusaLink connection info.", "session": self.planning_snapshot(session_id=session_id)}
            self._state.run_metadata.pop("pending_specimen_input", None)
            return await self._resume_specimen_after_operator_input(
                experiment_spec=dict(self._state.current_experiment_spec or {}),
                session_id=session_id,
            )

        self._state.run_metadata.pop("pending_specimen_input", None)
        return {"ok": False, "message": f"Unknown pending specimen input type: {request_type}", "session": self.planning_snapshot(session_id=session_id)}

    def _should_route_specimen_printer_choice(self, message: str) -> bool:
        """Give explicit printer-path answers priority over the orchestrator chat."""
        if not self._parse_specimen_printer_choice(message):
            return False
        pending = self._state.run_metadata.get("pending_specimen_input")
        if isinstance(pending, dict) and pending:
            return True
        spec = self._state.current_experiment_spec if isinstance(self._state.current_experiment_spec, dict) else {}
        if self._is_live_gui_test_handoff_spec(spec) and not self._specimen_printer_path(spec):
            return True
        for entry in reversed(self._planning_messages[-8:]):
            if not isinstance(entry, dict):
                continue
            if entry.get("pending_operator_input"):
                request = entry.get("input_request")
                if not isinstance(request, dict):
                    specimen = entry.get("specimen") if isinstance(entry.get("specimen"), dict) else {}
                    request = specimen.get("input_request") if isinstance(specimen.get("input_request"), dict) else {}
                if str(request.get("type", "")).strip() == "printer_test_path_choice":
                    return True
            content = str(entry.get("content", ""))
            if "가상 브릿지" in content and "설치 프린터" in content and "실제 출력" in content:
                return True
        return False

    def _ensure_pending_specimen_printer_choice(self) -> None:
        """Recover printer-path pending state if the browser/server session lost it."""
        spec = self._state.current_experiment_spec if isinstance(self._state.current_experiment_spec, dict) else {}
        self._state.run_metadata["pending_specimen_input"] = {
            "type": "printer_test_path_choice",
            "specimen_id": spec.get("specimen_id"),
            "input_request": {
                "type": "printer_test_path_choice",
                "choices": ["virtual_bridge", "installed_printer", "physical_print"],
            },
        }

    @staticmethod
    def _is_live_gui_test_handoff_spec(spec: dict[str, Any]) -> bool:
        return bool(spec.get("test_mode_autofill") or spec.get("test_mode_llm_generated"))

    @staticmethod
    def _specimen_printer_path(spec: dict[str, Any]) -> str:
        for key in ("printer_test_path", "test_printer_path", "printer_bridge_mode", "printer_test_mode"):
            value = str(spec.get(key, "")).strip()
            if value:
                return value
        return ""

    @staticmethod
    def _parse_inline_test_mode_printer_choice(message: str) -> str:
        """Parse one-shot Live GUI test commands like `테스트 모드, 실제 출력`."""
        if not MainController._should_trigger_test_design(message):
            return ""
        return MainController._parse_specimen_printer_choice(message)

    @staticmethod
    def _apply_specimen_printer_choice_to_spec(spec: dict[str, Any], choice: str) -> dict[str, Any]:
        """Apply the SpecimenMakingAgent printer path choice to a spec/constraint payload."""
        normalized = str(choice or "").strip()
        if normalized not in {"virtual_bridge", "installed_printer", "physical_print"}:
            return dict(spec)

        updated = dict(spec)
        updated["printer_test_path"] = normalized
        updated["test_printer_transport"] = "real" if normalized in {"installed_printer", "physical_print"} else "virtual"
        updated["allow_test_printer_live"] = normalized in {"installed_printer", "physical_print"}

        print_request = dict(updated.get("print", {})) if isinstance(updated.get("print"), dict) else {}
        if normalized == "physical_print":
            print_request.update(
                {
                    "start_immediately": True,
                    "physical_intent": True,
                    "confirm_physical_print": True,
                }
            )
        else:
            print_request.update(
                {
                    "start_immediately": False,
                    "physical_intent": False,
                    "confirm_physical_print": False,
                }
            )
        updated["print"] = print_request
        return updated

    @staticmethod
    def _parse_specimen_printer_choice(message: str) -> str:
        normalized = re.sub(r"\s+", "", message.lower())
        if any(token in normalized for token in ("실제출력", "출력", "actualprint", "physicalprint", "startprint")):
            return "physical_print"
        if any(token in normalized for token in ("가상", "virtual", "bridge", "브릿지", "브리지")):
            return "virtual_bridge"
        if any(token in normalized for token in ("설치", "실제", "프린터", "printer", "prusa", "real")):
            return "installed_printer"
        return ""

    @staticmethod
    def _is_connection_retry_message(message: str) -> bool:
        normalized = re.sub(r"\s+", "", message.lower())
        return any(token in normalized for token in ("완료", "입력", "저장", "재시도", "retry", "done"))

    async def _resume_specimen_after_operator_input(self, *, experiment_spec: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        try:
            tail = await self._run_specimen_guardian_tail(experiment_spec)
            ok = bool(tail.get("ok", False))
            message = str(tail.get("message", "SpecimenMakingAgent resumed."))
        except Exception as exc:
            await self._append_planning_message(
                {
                    "role": "printer_ai",
                    "content": (
                        "Specimen Making Agent 재시도에 실패했습니다.\n"
                        f"error={exc.__class__.__name__}: {exc}"
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": False,
                },
                event_type="planning_specimen_result",
                level="ERROR",
                message="SpecimenMakingAgent resume failed.",
            )
            ok = False
            message = "SpecimenMakingAgent resume failed."
        self._schedule_post_run_vllm_transition()
        return {"ok": ok, "message": message, "session": self.planning_snapshot(session_id=session_id)}

    async def _run_specimen_guardian_tail(self, experiment_spec: dict[str, Any]) -> dict[str, Any]:
        await self._append_planning_message(
            {
                "role": "system",
                "content": "Handoff: Operator input -> Specimen Making Agent. 기존 설계안을 유지하고 프린터 경로 선택값만 반영해 재시도합니다.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ok": True,
            },
            event_type="planning_handoff",
            message="Planning handoff back to Specimen Making Agent started.",
        )
        specimen_agent = self._deps.agent_registry.get("specimen_agent")
        specimen_result = await specimen_agent.run(self._state, self._deps.agent_context)
        if not specimen_result.success:
            raise RuntimeError(f"SpecimenMakingAgent failed: {specimen_result.summary}")
        specimen_payload = specimen_result.data.get("specimen_result", {})
        if not isinstance(specimen_payload, dict):
            raise RuntimeError("SpecimenMakingAgent did not return specimen_result.")
        if specimen_payload.get("requires_operator_input"):
            await self._record_pending_specimen_input(specimen_payload)
            return {"ok": True, "message": "SpecimenMakingAgent waiting for operator input."}

        specimen_artifacts = self._write_planning_artifacts(experiment_spec, specimen_result=specimen_payload)
        specimen_message = self._format_specimen_runtime_message(experiment_spec, specimen_payload)
        await self._append_planning_message(
            {
                "role": "printer_ai",
                "content": specimen_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "specimen_agent",
                "ok": True,
                "specimen": specimen_payload,
                "specimen_artifacts": specimen_artifacts,
                "render_artifacts": False,
            },
            event_type="planning_specimen_result",
            message="SpecimenMakingAgent completed Specimen Making Agent handoff preparation.",
        )

        guardian_agent = self._deps.agent_registry.get("guardian_agent")
        guardian_result = await guardian_agent.run(self._state, self._deps.agent_context)
        guardian_payload = (
            guardian_result.data.get("guardian", {})
            if isinstance(guardian_result.data.get("guardian", {}), dict)
            else {}
        )
        self._state.run_metadata["guardian"] = guardian_payload
        decision = str(guardian_payload.get("decision", "continue")).strip() or "continue"
        action = str(guardian_payload.get("action", "")).strip()
        reason = str(guardian_payload.get("reason", "")).strip()
        precursor = guardian_payload.get("precursor", "")
        design_validation = guardian_payload.get("design_validation", {})
        health_validation = guardian_payload.get("health_validation", {})
        consistency = guardian_payload.get("consistency", {})

        guardian_content = (
            "Guardian Agent 검증 결과:\n\n"
            f"- decision: {decision}\n"
            f"- action: {action or 'continue'}\n"
            f"- reason: {reason or 'n/a'}\n"
            f"- precursor: {precursor}\n"
            f"- design_validation: {json.dumps(design_validation, ensure_ascii=False)}\n"
            f"- health_validation: {json.dumps(health_validation, ensure_ascii=False)}\n"
            f"- consistency: {json.dumps(consistency, ensure_ascii=False)}"
        )
        await self._append_planning_message(
            {
                "role": "guardian",
                "content": guardian_content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": "guardian_agent",
                "ok": bool(guardian_result.success),
                "guardian": guardian_payload,
            },
            event_type="planning_guardian_result",
            message="GuardianAgent validation completed.",
            level="INFO" if guardian_result.success else "ERROR",
        )

        if decision in {"stop", "error"}:
            await self._append_planning_message(
                {
                    "role": "system",
                    "content": "Guardian 판정으로 다음 단계 진행이 중단되었습니다. 조건을 수정한 뒤 다시 요청하세요.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": decision != "error",
                },
                event_type="planning_handoff",
                message="Planning flow halted by Guardian decision.",
                level="WARNING" if decision == "stop" else "ERROR",
            )
        else:
            await self._append_planning_message(
                {
                    "role": "system",
                    "content": "Guardian 통과. 필요하면 이어서 다음 실험 계획/수행을 요청하세요.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "ok": True,
                },
                event_type="planning_handoff",
                message="Planning flow passed Guardian validation.",
            )
        return {
            "ok": bool(guardian_result.success) and decision != "error",
            "message": "Planning handoff to Specimen Making Agent -> GuardianAgent completed.",
        }

    def _build_planning_spec(
        self,
        *,
        base_spec: dict[str, Any],
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        """Adapt current DesignAgent output into a specimen-design planning spec."""
        def pick(key: str, default: Any) -> Any:
            return constraints.get(key, base_spec.get(key, default))

        candidate_id = str(base_spec.get("candidate_id", f"cand-{self._state.loop_count + 1}"))
        size = constraints.get("specimen_size_mm", constraints.get("max_specimen_size_mm", base_spec.get("specimen_size_mm", [30.0, 30.0, 30.0])))
        if not isinstance(size, list) or len(size) != 3:
            size = [30.0, 30.0, 30.0]
        specimen_size = [float(item) for item in size]
        validated_defaults = self._validated_printer_defaults()
        test_handoff = bool(constraints.get("test_mode_autofill") or constraints.get("test_mode_llm_generated"))
        print_constraints = constraints.get("print") if isinstance(constraints.get("print"), dict) else {}
        if "start_immediately" in print_constraints:
            requested_live_start = bool(print_constraints.get("start_immediately"))
        else:
            requested_live_start = bool(pick("start_immediately_live", validated_defaults.get("start_immediately_live", True)))
        live_physical_print = self._state.mode == Mode.LIVE and not test_handoff and requested_live_start
        default_cell_size_mm = 10.0 if self._state.mode == Mode.TEST or test_handoff else 5.0
        max_print_time_min = float(pick("max_print_time_min", validated_defaults.get("max_print_time_min", 120.0)))
        geometry_type = (
            self._normalize_planning_geometry_type(pick("geometry_type", ""))
            or self._normalize_planning_geometry_type(base_spec.get("geometry_type"))
            or (self.TEST_MODE_FIXED_GEOMETRY if self._state.mode == Mode.TEST else "gyroid")
        )
        digest = hashlib.sha1(
            json.dumps(
                {
                    "candidate_id": candidate_id,
                    "geometry_type": geometry_type,
                    "size": specimen_size,
                    "run_id": self._state.run_id,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:8]
        specimen_id = str(base_spec.get("specimen_id") or f"specimen-{candidate_id}-{digest}")
        planning_spec = {
            **base_spec,
            "candidate_id": candidate_id,
            "specimen_id": specimen_id,
            "objective_type": str(pick("objective_type", "maximize_energy_absorption_per_mass")),
            "objective_direction": str(pick("objective_direction", "maximize")),
            "geometry_type": geometry_type,
            "specimen_size_mm": specimen_size,
            "cell_size_mm": float(pick("cell_size_mm", default_cell_size_mm)),
            "wall_thickness_mm": float(pick("wall_thickness_mm", 1.0)),
            "relative_density": float(pick("relative_density", 0.35)),
            "porosity": float(pick("porosity", 0.65)),
            "anisotropy_ratio": float(pick("anisotropy_ratio", 1.0)),
            "orientation_deg": float(pick("orientation_deg", 0.0)),
            "defect_seed": int(pick("defect_seed", self._state.loop_count + 1)),
            "defect_ratio": float(pick("defect_ratio", 0.0)),
            "skin_thickness_mm": float(pick("skin_thickness_mm", validated_defaults.get("skin_thickness_mm", 0.8))),
            "top_cap_enabled": bool(pick("top_cap_enabled", validated_defaults.get("top_cap_enabled", False))),
            "bottom_cap_enabled": bool(pick("bottom_cap_enabled", validated_defaults.get("bottom_cap_enabled", True))),
            "top_bottom_cap": bool(pick("top_bottom_cap", validated_defaults.get("top_bottom_cap", True))),
            "skirt_enabled": bool(pick("skirt_enabled", validated_defaults.get("skirt_enabled", False))),
            "require_flat_compression_faces": bool(
                pick(
                    "require_flat_compression_faces",
                    validated_defaults.get("require_flat_compression_faces", False),
                )
            ),
            "fdm_min_wall_thickness_mm": float(pick("fdm_min_wall_thickness_mm", 1.2)),
            "fdm_max_bridge_distance_mm": float(pick("fdm_max_bridge_distance_mm", 10.0)),
            "fdm_max_unsupported_overhang_deg": float(pick("fdm_max_unsupported_overhang_deg", 45.0)),
            "fdm_max_gyroid_wall_cell_ratio": float(pick("fdm_max_gyroid_wall_cell_ratio", 0.28)),
            "material": str(pick("material", validated_defaults.get("material", "PLA"))),
            "printer_model": str(pick("printer_model", validated_defaults["printer_model"])),
            "printer_profile": str(pick("printer_profile", validated_defaults["printer_profile"])),
            "slicer_profile_hint": str(pick("slicer_profile_hint", validated_defaults["slicer_profile_hint"])),
            "layer_height_mm": float(pick("layer_height_mm", validated_defaults["layer_height_mm"])),
            "first_layer_height_mm": float(pick("first_layer_height_mm", validated_defaults.get("first_layer_height_mm", pick("layer_height_mm", validated_defaults["layer_height_mm"])))),
            "slow_first_layer_enabled": bool(pick("slow_first_layer_enabled", validated_defaults.get("slow_first_layer_enabled", True))),
            "first_layer_speed_mm_s": float(pick("first_layer_speed_mm_s", validated_defaults.get("first_layer_speed_mm_s", 10.0))),
            "bed_temperature_c": float(pick("bed_temperature_c", validated_defaults.get("bed_temperature_c", 60.0))),
            "first_layer_bed_temperature_c": float(
                pick("first_layer_bed_temperature_c", validated_defaults.get("first_layer_bed_temperature_c", validated_defaults.get("bed_temperature_c", 60.0)))
            ),
            "nozzle_diameter_mm": float(pick("nozzle_diameter_mm", validated_defaults["nozzle_diameter_mm"])),
            "storage": str(pick("storage", validated_defaults["storage"])),
            "max_print_time_min": max_print_time_min,
            "expected_mass_g": round(float(pick("expected_mass_g", 18.0)), 3),
            "expected_volume_mm3": round(float(pick("expected_volume_mm3", 14500.0)), 3),
            "expected_print_time_min": round(float(pick("expected_print_time_min", max_print_time_min * 0.62)), 2),
            "expected_manufacturability_score": float(pick("expected_manufacturability_score", 0.82)),
            "expected_objective_proxy_score": float(pick("expected_objective_proxy_score", 0.74)),
            "generation_strategy": str(pick("generation_strategy", "planning_chat_design_agent_with_artifact_adaptation")),
            "generation_reason": str(pick("generation_reason", "Operator requested experiment execution from planning chat.")),
            "print": {
                **(
                    {
                        "storage": validated_defaults["storage"],
                        "overwrite": bool(pick("overwrite", validated_defaults.get("overwrite", True))),
                    }
                    | print_constraints
                ),
                "storage": str(pick("storage", validated_defaults["storage"])),
                "skirt_enabled": bool(pick("skirt_enabled", validated_defaults.get("skirt_enabled", False))),
                "start_immediately": bool(live_physical_print),
                "physical_intent": bool(live_physical_print),
                "confirm_physical_print": bool(live_physical_print),
            },
            "ejection": {
                **(constraints.get("ejection") if isinstance(constraints.get("ejection"), dict) else {}),
                "enabled": bool(validated_defaults.get("allow_ejection", False)),
            },
        }
        explicit_top_cap = "top_cap_enabled" in constraints or "top_cap_enabled" in base_spec
        explicit_bottom_cap = "bottom_cap_enabled" in constraints or "bottom_cap_enabled" in base_spec
        explicit_legacy_cap = "top_bottom_cap" in constraints or "top_bottom_cap" in base_spec
        if explicit_top_cap or explicit_bottom_cap:
            planning_spec["top_cap_enabled"] = bool(planning_spec.get("top_cap_enabled", False))
            planning_spec["bottom_cap_enabled"] = bool(planning_spec.get("bottom_cap_enabled", False))
        elif explicit_legacy_cap:
            legacy_cap = bool(planning_spec.get("top_bottom_cap", validated_defaults.get("top_bottom_cap", True)))
            planning_spec["top_cap_enabled"] = False
            planning_spec["bottom_cap_enabled"] = legacy_cap
        else:
            planning_spec["top_cap_enabled"] = bool(validated_defaults.get("top_cap_enabled", False))
            planning_spec["bottom_cap_enabled"] = bool(validated_defaults.get("bottom_cap_enabled", True))
        planning_spec["top_bottom_cap"] = bool(planning_spec["top_cap_enabled"] or planning_spec["bottom_cap_enabled"])
        if planning_spec["top_bottom_cap"]:
            planning_spec["skin_thickness_mm"] = max(0.2, float(planning_spec.get("skin_thickness_mm") or 0.8))
            planning_spec["require_flat_compression_faces"] = bool(
                planning_spec.get("require_flat_compression_faces", False)
                and planning_spec["top_cap_enabled"]
                and planning_spec["bottom_cap_enabled"]
            )
        else:
            planning_spec["skin_thickness_mm"] = 0.0
            planning_spec["require_flat_compression_faces"] = False
        if geometry_type == "gyroid":
            wall_ratio = planning_spec["wall_thickness_mm"] / max(planning_spec["cell_size_mm"], 1e-6)
            physical_min = max(
                0.18,
                min(0.68, 0.50 * planning_spec["wall_thickness_mm"] * (6.283185307179586 / max(planning_spec["cell_size_mm"], 1e-6))),
            )
            default_tpms_thickness = max(
                physical_min,
                min(0.68, 0.10 + 0.40 * planning_spec["relative_density"] + min(0.06, 0.20 * wall_ratio)),
            )
            planning_spec["tpms_surface"] = str(pick("tpms_surface", planning_spec.get("tpms_surface", "gyroid")))
            planning_spec["tpms_thickness"] = float(pick("tpms_thickness", planning_spec.get("tpms_thickness", default_tpms_thickness)))
            planning_spec["tpms_resolution"] = int(pick("tpms_resolution", planning_spec.get("tpms_resolution", 72)))
            planning_spec["printability_mode"] = str(pick("printability_mode", planning_spec.get("printability_mode", "fdm_closed_shell")))
        # Preserve Live GUI test-mode handoff markers across the DesignAgent
        # adaptation step so SpecimenMakingAgent can request the printer path.
        passthrough_keys = (
            "test_mode_autofill",
            "test_mode_llm_generated",
            "printer_test_path",
            "test_printer_path",
            "printer_bridge_mode",
            "printer_test_mode",
            "test_printer_transport",
            "allow_test_printer_live",
        )
        for key in passthrough_keys:
            if key in constraints:
                planning_spec[key] = constraints[key]
            elif key in base_spec:
                planning_spec[key] = base_spec[key]
        return planning_spec

    def _write_planning_artifacts(
        self,
        experiment_spec: dict[str, Any],
        *,
        specimen_result: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Create planning artifacts and prefer real specimen results when available."""
        specimen_id = self._safe_artifact_segment(str(experiment_spec["specimen_id"]))
        artifact_dir = self._deps.run_root / self._state.run_id / "planning" / specimen_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        stl_path = artifact_dir / "specimen.stl"
        preview_path = artifact_dir / "specimen_preview.svg"
        spec_path = artifact_dir / "experiment_spec.json"
        specimen_paths = specimen_result or {}
        source_stl = None
        source_preview = None
        source_stl_candidate = specimen_paths.get("stl_path")
        source_preview_candidate = specimen_paths.get("preview_image_path")
        if isinstance(source_stl_candidate, str) and source_stl_candidate.strip():
            source_stl = Path(source_stl_candidate).expanduser()
        if isinstance(source_preview_candidate, str) and source_preview_candidate.strip():
            source_preview = Path(source_preview_candidate).expanduser()

        if source_stl is None or not source_stl.exists():
            source_stl = stl_path
            self._write_planning_stl(source_stl, experiment_spec)
        if source_preview is None or not source_preview.exists():
            source_preview = preview_path
            source_preview.write_text(self._preview_svg(experiment_spec), encoding="utf-8")

        if source_stl != stl_path:
            shutil.copy2(source_stl, stl_path)
        if source_preview != preview_path:
            shutil.copy2(source_preview, preview_path)

        spec_path.write_text(json.dumps(experiment_spec, ensure_ascii=True, indent=2), encoding="utf-8")

        base = f"/api/planning/artifacts/{self._state.run_id}/{specimen_id}"
        return {
            "stl_path": str(stl_path),
            "preview_image_path": str(preview_path),
            "experiment_spec_path": str(spec_path),
            "stl_url": f"{base}/specimen.stl",
            "preview_url": f"{base}/specimen_preview.svg",
            "experiment_spec_url": f"{base}/experiment_spec.json",
        }

    @staticmethod
    def _write_planning_stl(stl_path: Path, experiment_spec: dict[str, Any]) -> None:
        """Write planning STL with the same smooth/cleanup path as specimen generation."""
        geometry = str(experiment_spec.get("geometry_type", "")).strip()
        name = str(experiment_spec.get("specimen_id", "specimen"))
        size = experiment_spec.get("specimen_size_mm", [30.0, 30.0, 30.0])
        if geometry == "gyroid":
            metadata = write_smooth_gyroid_stl(
                stl_path=stl_path,
                name=name,
                specimen_size_mm=size,
                cell_size_mm=float(experiment_spec.get("cell_size_mm", 5.0)),
                wall_thickness_mm=float(experiment_spec.get("wall_thickness_mm", 1.2)),
                relative_density=float(experiment_spec.get("relative_density", 0.32)),
                anisotropy_ratio=float(experiment_spec.get("anisotropy_ratio", 1.0)),
                orientation_deg=float(experiment_spec.get("orientation_deg", 0.0)),
                defect_seed=int(experiment_spec.get("defect_seed", 1)),
                defect_ratio=float(experiment_spec.get("defect_ratio", 0.0)),
                skin_thickness_mm=float(experiment_spec.get("skin_thickness_mm", 0.0)),
                top_bottom_cap=bool(experiment_spec.get("top_bottom_cap", False)),
                top_cap_enabled=experiment_spec.get("top_cap_enabled"),
                bottom_cap_enabled=experiment_spec.get("bottom_cap_enabled"),
                tpms_thickness=experiment_spec.get("tpms_thickness"),
                resolution=max(72, min(96, int(experiment_spec.get("tpms_resolution", 72) or 72))),
            )
            if metadata is not None:
                return
        stl_path.write_text(MainController._planning_stl(experiment_spec), encoding="utf-8")

    @staticmethod
    def _safe_artifact_segment(value: str) -> str:
        """Return a filesystem and URL-safe artifact path segment."""
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip(".-")
        return safe or "artifact"

    @staticmethod
    def _planning_stl(experiment_spec: dict[str, Any]) -> str:
        """Generate a lightweight ASCII STL that reflects the selected planning geometry."""
        geometry = str(experiment_spec.get("geometry_type", "")).strip()
        name = str(experiment_spec.get("specimen_id", "specimen"))
        size = experiment_spec.get("specimen_size_mm", [30.0, 30.0, 30.0])
        if geometry == "gyroid":
            stl_text, _metadata = generate_gyroid_stl_text(
                name=name,
                specimen_size_mm=size,
                cell_size_mm=float(experiment_spec.get("cell_size_mm", 7.5)),
                wall_thickness_mm=float(experiment_spec.get("wall_thickness_mm", 1.2)),
                relative_density=float(experiment_spec.get("relative_density", 0.32)),
                anisotropy_ratio=float(experiment_spec.get("anisotropy_ratio", 1.0)),
                orientation_deg=float(experiment_spec.get("orientation_deg", 0.0)),
                defect_seed=int(experiment_spec.get("defect_seed", 1)),
                defect_ratio=float(experiment_spec.get("defect_ratio", 0.0)),
                skin_thickness_mm=float(experiment_spec.get("skin_thickness_mm", 0.0)),
                top_bottom_cap=bool(experiment_spec.get("top_bottom_cap", False)),
                top_cap_enabled=experiment_spec.get("top_cap_enabled"),
                bottom_cap_enabled=experiment_spec.get("bottom_cap_enabled"),
                tpms_thickness=experiment_spec.get("tpms_thickness"),
                resolution=max(72, min(96, int(experiment_spec.get("tpms_resolution", 72) or 72))),
            )
            return stl_text
        if geometry == "auxetic_reentrant":
            return MainController._auxetic_reentrant_stl(
                name=name,
                size=size,
                cell_size=float(experiment_spec.get("cell_size_mm", 7.5)),
                wall=float(experiment_spec.get("wall_thickness_mm", 1.2)),
                cap=bool(experiment_spec.get("top_bottom_cap", False)),
            )
        if geometry.startswith("lattice"):
            return MainController._lattice_stl(
                name=name,
                size=size,
                cell_size=float(experiment_spec.get("cell_size_mm", 7.5)),
                wall=float(experiment_spec.get("wall_thickness_mm", 1.2)),
                cap=bool(experiment_spec.get("top_bottom_cap", False)),
            )
        return MainController._box_stl(name, size)

    @staticmethod
    def _box_stl(name: str, size: list[float]) -> str:
        """Generate a simple ASCII STL box placeholder for planning visualization."""
        x, y, z = [max(float(item), 1.0) for item in size]
        return MainController._cuboids_stl(name, [(-x / 2.0, x / 2.0, -y / 2.0, y / 2.0, -z / 2.0, z / 2.0)])

    @staticmethod
    def _lattice_stl(*, name: str, size: Any, cell_size: float, wall: float, cap: bool) -> str:
        """Generate an axis-strut BCC-style lattice STL for immediate planning visualization."""
        x, y, z = [max(float(item), 1.0) for item in MainController._vector3_value(size, [30.0, 30.0, 30.0])]
        hx, hy, hz = x / 2.0, y / 2.0, z / 2.0
        strut = max(0.6, min(float(wall), min(x, y, z) / 8.0))
        cell = max(float(cell_size), strut * 3.0)
        cells = max(2, min(4, round(min(x, y, z) / cell)))

        def positions(length: float) -> list[float]:
            half = length / 2.0
            step = length / cells
            return [round(-half + step * idx, 6) for idx in range(cells + 1)]

        xs = positions(x)
        ys = positions(y)
        zs = positions(z)

        def clipped(center: float, half_width: float, low: float, high: float) -> tuple[float, float]:
            return max(low, center - half_width), min(high, center + half_width)

        cuboids: list[tuple[float, float, float, float, float, float]] = []
        h = strut / 2.0
        for yy in ys:
            y0, y1 = clipped(yy, h, -hy, hy)
            for zz in zs:
                z0, z1 = clipped(zz, h, -hz, hz)
                cuboids.append((-hx, hx, y0, y1, z0, z1))
        for xx in xs:
            x0, x1 = clipped(xx, h, -hx, hx)
            for zz in zs:
                z0, z1 = clipped(zz, h, -hz, hz)
                cuboids.append((x0, x1, -hy, hy, z0, z1))
        for xx in xs:
            x0, x1 = clipped(xx, h, -hx, hx)
            for yy in ys:
                y0, y1 = clipped(yy, h, -hy, hy)
                cuboids.append((x0, x1, y0, y1, -hz, hz))
        if cap:
            cap_thickness = max(0.6, min(strut, z / 12.0))
            cuboids.append((-hx, hx, -hy, hy, -hz, -hz + cap_thickness))
            cuboids.append((-hx, hx, -hy, hy, hz - cap_thickness, hz))
        return MainController._cuboids_stl(name, cuboids)

    @staticmethod
    def _auxetic_reentrant_stl(*, name: str, size: Any, cell_size: float, wall: float, cap: bool) -> str:
        """Generate a lightweight re-entrant auxetic (zigzag ligament) STL."""
        x, y, z = [max(float(item), 1.0) for item in MainController._vector3_value(size, [30.0, 30.0, 30.0])]
        hx, hy, hz = x / 2.0, y / 2.0, z / 2.0
        strut = max(0.6, min(float(wall), min(x, y, z) / 10.0))
        cell = max(float(cell_size), strut * 4.0)
        cols = max(2, min(6, round(x / cell)))
        rows = max(2, min(6, round(y / cell)))
        pitch_x = x / cols
        pitch_y = y / rows
        amp = max(strut * 1.2, min(pitch_x * 0.28, pitch_y * 0.28))
        amp = min(amp, pitch_x * 0.4)

        z0, z1 = -hz, hz
        cuboids: list[tuple[float, float, float, float, float, float]] = []
        bounds = (-hx, hx, -hy, hy)

        def add_segment(x0: float, y0: float, x1: float, y1: float, *, steps: int = 1) -> None:
            MainController._append_xy_segment_cuboids(
                cuboids=cuboids,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                strut=strut,
                z0=z0,
                z1=z1,
                steps=steps,
                bounds=bounds,
            )

        # Perimeter frame.
        add_segment(-hx, -hy, hx, -hy)
        add_segment(-hx, hy, hx, hy)
        add_segment(-hx, -hy, -hx, hy)
        add_segment(hx, -hy, hx, hy)

        base_x = [(-hx + pitch_x * idx) for idx in range(cols + 1)]
        row_nodes: list[tuple[float, list[float]]] = []
        for row in range(rows + 1):
            y_coord = -hy + pitch_y * row
            shift = amp if row % 2 else -amp
            nodes: list[float] = []
            for col, x_coord in enumerate(base_x):
                shifted = x_coord
                if 0 < col < cols:
                    shifted += shift
                shifted = max(-hx + strut * 0.7, min(hx - strut * 0.7, shifted))
                nodes.append(shifted)
            row_nodes.append((y_coord, nodes))

        # Horizontal ligaments in each row.
        for y_coord, nodes in row_nodes:
            for col in range(cols):
                add_segment(nodes[col], y_coord, nodes[col + 1], y_coord)

        # Re-entrant diagonals between alternating rows.
        for row in range(rows):
            y0_row, nodes0 = row_nodes[row]
            y1_row, nodes1 = row_nodes[row + 1]
            for col in range(1, cols):
                add_segment(nodes0[col], y0_row, nodes1[col], y1_row, steps=4)

        if cap:
            cap_thickness = max(0.6, min(strut, z / 14.0))
            cuboids.append((-hx, hx, -hy, hy, -hz, -hz + cap_thickness))
            cuboids.append((-hx, hx, -hy, hy, hz - cap_thickness, hz))

        return MainController._cuboids_stl(name, cuboids)

    @staticmethod
    def _append_xy_segment_cuboids(
        *,
        cuboids: list[tuple[float, float, float, float, float, float]],
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        strut: float,
        z0: float,
        z1: float,
        steps: int,
        bounds: tuple[float, float, float, float],
    ) -> None:
        """Append one XY segment (optionally staircase-subdivided) as cuboids."""
        min_x, max_x, min_y, max_y = bounds
        parts = max(1, int(steps))
        for idx in range(parts):
            t0 = idx / parts
            t1 = (idx + 1) / parts
            xa = x0 + (x1 - x0) * t0
            xb = x0 + (x1 - x0) * t1
            ya = y0 + (y1 - y0) * t0
            yb = y0 + (y1 - y0) * t1
            cx = (xa + xb) / 2.0
            cy = (ya + yb) / 2.0
            lx = abs(xb - xa) + strut
            ly = abs(yb - ya) + strut

            ax0 = max(min_x, cx - lx / 2.0)
            ax1 = min(max_x, cx + lx / 2.0)
            ay0 = max(min_y, cy - ly / 2.0)
            ay1 = min(max_y, cy + ly / 2.0)
            if (ax1 - ax0) < 0.05 or (ay1 - ay0) < 0.05 or (z1 - z0) < 0.05:
                continue
            cuboids.append((ax0, ax1, ay0, ay1, z0, z1))

    @staticmethod
    def _cuboids_stl(name: str, cuboids: list[tuple[float, float, float, float, float, float]]) -> str:
        """Generate one ASCII STL from multiple axis-aligned cuboids."""
        lines = [f"solid {name}"]
        for cuboid in cuboids:
            lines.extend(MainController._cuboid_facets(*cuboid))
        lines.append(f"endsolid {name}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _cuboid_facets(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float) -> list[str]:
        """Return ASCII STL facets for one axis-aligned cuboid."""
        v = [
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
        ]
        faces = [
            (0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6),
            (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2),
            (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0),
        ]
        lines: list[str] = []
        for a, b, c in faces:
            lines.extend(
                [
                    "  facet normal 0 0 0",
                    "    outer loop",
                    f"      vertex {v[a][0]:.6f} {v[a][1]:.6f} {v[a][2]:.6f}",
                    f"      vertex {v[b][0]:.6f} {v[b][1]:.6f} {v[b][2]:.6f}",
                    f"      vertex {v[c][0]:.6f} {v[c][1]:.6f} {v[c][2]:.6f}",
                    "    endloop",
                    "  endfacet",
                ]
            )
        return lines

    @staticmethod
    def _vector3_value(value: Any, default: list[float]) -> list[float]:
        """Convert a loose value into a numeric 3-vector."""
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
    def _preview_svg(experiment_spec: dict[str, Any]) -> str:
        """Create a lightweight SVG preview card for chat display."""
        specimen_id = str(experiment_spec.get("specimen_id", "specimen"))
        geometry = str(experiment_spec.get("geometry_type", "geometry"))
        size = experiment_spec.get("specimen_size_mm", [30, 30, 30])
        if geometry.startswith("lattice"):
            internal = """
  <g stroke="#1436b3" stroke-width="3" opacity="0.72">
    <path d="M92 108 H310 M92 160 H310 M92 212 H310 M92 264 H310"/>
    <path d="M92 108 V264 M146 108 V264 M200 108 V264 M254 108 V264 M310 108 V264"/>
    <path d="M345 124 L430 170 M345 176 L430 222 M345 228 L430 274"/>
    <path d="M310 108 L395 154 M310 160 L395 206 M310 212 L395 258"/>
    <path d="M92 108 L177 154 M146 108 L231 154 M200 108 L285 154 M254 108 L339 154"/>
  </g>
"""
        elif geometry == "auxetic_reentrant":
            internal = """
  <g stroke="#1436b3" stroke-width="3" opacity="0.78" fill="none">
    <path d="M92 110 L146 146 L200 110 L254 146 L310 110"/>
    <path d="M92 164 L146 200 L200 164 L254 200 L310 164"/>
    <path d="M92 218 L146 254 L200 218 L254 254 L310 218"/>
    <path d="M146 146 L146 200 M200 110 L200 164 M254 146 L254 200"/>
    <path d="M345 126 L396 160 L430 126 M345 182 L396 216 L430 182 M345 238 L396 272 L430 238"/>
  </g>
"""
        elif geometry == "gyroid":
            internal = """
  <g stroke="#1436b3" stroke-width="3" opacity="0.78" fill="none">
    <path d="M92 128 C138 78 184 178 230 128 S320 78 366 128"/>
    <path d="M92 180 C138 130 184 230 230 180 S320 130 366 180"/>
    <path d="M92 232 C138 182 184 282 230 232 S320 182 366 232"/>
    <path d="M112 108 C168 164 252 74 312 130 S388 230 430 168"/>
    <path d="M128 270 C186 214 250 304 318 244 S392 144 430 210"/>
    <path d="M345 126 C384 96 406 178 430 148 M345 190 C384 160 406 242 430 212 M345 252 C384 222 406 304 430 274"/>
  </g>
"""
        else:
            internal = ""
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="420" viewBox="0 0 720 420">
  <rect width="720" height="420" rx="28" fill="#f5f8ff"/>
  <rect x="70" y="80" width="260" height="220" rx="18" fill="#dfe9ff" fill-opacity="0.42" stroke="#1436b3" stroke-width="4"/>
  <path d="M330 80 L430 135 L430 350 L330 300 Z" fill="#b9ccff" fill-opacity="0.42" stroke="#1436b3" stroke-width="4"/>
  <path d="M70 80 L170 135 L430 135 L330 80 Z" fill="#edf3ff" fill-opacity="0.7" stroke="#1436b3" stroke-width="4"/>
{internal}
  <text x="470" y="135" font-family="monospace" font-size="22" fill="#1436b3">{geometry}</text>
  <text x="470" y="176" font-family="monospace" font-size="16" fill="#091225">{specimen_id}</text>
  <text x="470" y="215" font-family="monospace" font-size="16" fill="#5a6883">size={size}</text>
  <text x="470" y="252" font-family="monospace" font-size="16" fill="#5a6883">planning STL artifact</text>
</svg>
"""

    def planning_artifact_path(self, run_id: str, specimen_id: str, filename: str) -> Path:
        """Resolve a planning artifact path under run_root."""
        safe_run = self._safe_artifact_segment(run_id)
        safe_specimen = self._safe_artifact_segment(specimen_id)
        safe_filename = self._safe_artifact_segment(filename)
        allowed = {"specimen.stl", "specimen_preview.svg", "experiment_spec.json"}
        if safe_filename not in allowed:
            raise ValueError(f"Unsupported planning artifact: {filename}")
        run_root = self._deps.run_root.resolve()
        planning_path = (self._deps.run_root / safe_run / "planning" / safe_specimen / safe_filename).resolve()
        if planning_path.exists():
            path = planning_path
        else:
            specimens_path = (self._deps.run_root / safe_run / "specimens" / safe_specimen / safe_filename).resolve()
            if specimens_path.exists():
                path = specimens_path
            else:
                # Preserve previous behavior for missing files while returning a deterministic path.
                path = planning_path
        if not str(path).startswith(str(run_root)):
            raise ValueError("Planning artifact path escapes run root.")
        return path

    async def runtime_model_statuses(self) -> dict[str, Any]:
        """Return managed model statuses for the active vLLM backend."""
        backend = self._deps.agent_context.primary_backends.get("vllm")
        status_fn = getattr(backend, "managed_model_statuses", None)
        if self._deps.agent_context.active_backend != "vllm" or status_fn is None:
            return {
                "ok": False,
                "enabled": False,
                "active_backend": self._deps.agent_context.active_backend,
                "models": [],
                "runtime": self._runtime_profile(),
            }
        try:
            result = await status_fn()
        except Exception as exc:
            return {
                "ok": False,
                "enabled": True,
                "active_backend": "vllm",
                "models": [],
                "runtime": self._runtime_profile(),
                "error": str(exc),
            }
        return {
            "ok": True,
            "enabled": bool(result.get("enabled", False)) if isinstance(result, dict) else False,
            "active_backend": "vllm",
            "models": result.get("models", []) if isinstance(result, dict) else [],
            "runtime": self._runtime_profile(),
        }

    async def load_runtime_model(self, model: str) -> dict[str, Any]:
        """Manually load one managed vLLM model from the GUI."""
        backend = self._deps.agent_context.primary_backends.get("vllm")
        load_fn = getattr(backend, "load_model", None)
        if self._deps.agent_context.active_backend != "vllm" or load_fn is None:
            return {"ok": False, "message": "Managed vLLM runtime is not active."}
        clean_model = str(model or "").strip()
        if not clean_model:
            return {"ok": False, "message": "model is required."}
        self._cancel_pending_vllm_transition()
        try:
            result = await load_fn(clean_model)
        except Exception as exc:
            return {
                "ok": False,
                "message": f"Model load failed: {exc}",
                "status": await self.runtime_model_statuses(),
            }
        await self._emit_control_event("runtime_model_load", f"vLLM model loaded: {clean_model}")
        return {
            "ok": True,
            "message": f"Model loaded: {clean_model}",
            "result": result,
            "status": await self.runtime_model_statuses(),
        }

    async def unload_runtime_model(self, model: str) -> dict[str, Any]:
        """Manually unload one managed vLLM model from the GUI."""
        backend = self._deps.agent_context.primary_backends.get("vllm")
        unload_fn = getattr(backend, "unload_model", None)
        if self._deps.agent_context.active_backend != "vllm" or unload_fn is None:
            return {"ok": False, "message": "Managed vLLM runtime is not active."}
        clean_model = str(model or "").strip()
        if not clean_model:
            return {"ok": False, "message": "model is required."}
        try:
            result = await unload_fn(clean_model)
        except Exception as exc:
            return {
                "ok": False,
                "message": f"Model unload failed: {exc}",
                "status": await self.runtime_model_statuses(),
            }
        await self._emit_control_event("runtime_model_unload", f"vLLM model unloaded: {clean_model}")
        return {
            "ok": True,
            "message": f"Model unloaded: {clean_model}",
            "result": result,
            "status": await self.runtime_model_statuses(),
        }

    def _ollama_base_url(self) -> str:
        """Resolve direct Ollama endpoint used for model unload/clear."""
        explicit = os.getenv("OLLAMA_BASE_URL")
        if explicit:
            return explicit.rstrip("/")
        backend_port = os.getenv("NEMOCLAW_BACKEND_PORT", "11434").strip()
        return f"http://127.0.0.1:{backend_port}"

    async def _scale_down_idle_vllm_models(
        self,
        *,
        keep_models: set[str] | None = None,
        include_persistent: bool = False,
    ) -> dict[str, Any]:
        """Scale down NemoClaw-hosted vLLM deployments."""
        backend = self._deps.agent_context.primary_backends.get("vllm")
        scale_down = getattr(backend, "scale_down_idle_models", None)
        if scale_down is None:
            return {"enabled": False, "scaled_down": [], "errors": []}
        if keep_models:
            scale_down_except = getattr(backend, "scale_down_models_except", None)
            if scale_down_except is not None:
                try:
                    result = await scale_down_except(keep_models, include_persistent=include_persistent)
                    return result if isinstance(result, dict) else {"enabled": True, "scaled_down": [], "errors": []}
                except Exception as exc:
                    return {"enabled": True, "scaled_down": [], "errors": [str(exc)]}
        try:
            result = await scale_down(include_persistent=include_persistent)
        except Exception as exc:
            return {"enabled": True, "scaled_down": [], "errors": [str(exc)]}
        return result if isinstance(result, dict) else {"enabled": True, "scaled_down": [], "errors": []}

    def _cancel_pending_vllm_transition(self) -> None:
        """Cancel delayed idle transition when new model work begins."""
        task = self._vllm_transition_task
        if task is not None and not task.done():
            task.cancel()
        self._vllm_transition_task = None

    def _schedule_post_run_vllm_transition(self) -> None:
        """Run vLLM idle transition in the background instead of blocking GUI/API responses."""
        if self._deps.agent_context.active_backend != "vllm":
            return

        self._cancel_pending_vllm_transition()

        async def _runner() -> dict[str, Any]:
            return await self._post_run_vllm_transition()

        task = asyncio.create_task(_runner())
        self._vllm_transition_task = task

        def _clear(done: asyncio.Task[dict[str, Any]]) -> None:
            if self._vllm_transition_task is done:
                self._vllm_transition_task = None
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except Exception:
                return

        task.add_done_callback(_clear)

    async def _post_run_vllm_transition(self) -> dict[str, Any]:
        """After run/planning completion, scale idle vLLM deployments down."""
        if self._deps.agent_context.active_backend != "vllm":
            return {"enabled": False, "action": "none"}

        scale_result = await self._scale_down_idle_vllm_models()
        return {
            "enabled": True,
            "action": "scale_down",
            "scale_down": scale_result,
        }

    async def clear_gpu(self) -> dict[str, Any]:
        """Unload currently resident Ollama models to free GPU memory."""
        if self._run_task and not self._run_task.done():
            await self.stop()

        vllm_clear = await self._scale_down_idle_vllm_models(include_persistent=True)
        base_url = self._ollama_base_url()
        unloaded: list[str] = []
        errors: list[str] = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                ps_resp = await client.get(f"{base_url}/api/ps")
                ps_resp.raise_for_status()
                payload = ps_resp.json()
                models = payload.get("models", []) if isinstance(payload, dict) else []
                loaded_model_names: list[str] = []
                for item in models:
                    if isinstance(item, dict):
                        name = str(item.get("name") or item.get("model") or "").strip()
                        if name:
                            loaded_model_names.append(name)

                for model_name in loaded_model_names:
                    try:
                        unload_resp = await client.post(
                            f"{base_url}/api/generate",
                            json={"model": model_name, "prompt": "", "stream": False, "keep_alive": 0},
                        )
                        unload_resp.raise_for_status()
                        unloaded.append(model_name)
                    except Exception as exc:
                        errors.append(f"{model_name}: {exc}")
        except Exception as exc:
            if vllm_clear.get("scaled_down"):
                msg = f"GPU clear completed for vLLM; Ollama clear skipped: {exc}"
                await self._emit_control_event("gpu_clear", msg)
                return {
                    "ok": not vllm_clear.get("errors"),
                    "message": msg,
                    "base_url": base_url,
                    "unloaded_models": unloaded,
                    "vllm": vllm_clear,
                    "errors": [str(exc), *vllm_clear.get("errors", [])],
                }
            msg = f"GPU clear failed: {exc}"
            await self._emit_control_event("gpu_clear", msg)
            return {
                "ok": False,
                "message": msg,
                "base_url": base_url,
                "unloaded_models": [],
                "vllm": vllm_clear,
                "errors": [str(exc), *vllm_clear.get("errors", [])],
            }

        msg = f"GPU clear completed. unloaded={len(unloaded)} vllm_scaled_down={len(vllm_clear.get('scaled_down', []))}"
        await self._emit_control_event("gpu_clear", msg)
        return {
            "ok": len(errors) == 0 and not vllm_clear.get("errors"),
            "message": msg if not errors else f"{msg}, errors={len(errors)}",
            "base_url": base_url,
            "unloaded_models": unloaded,
            "vllm": vllm_clear,
            "errors": errors,
        }
