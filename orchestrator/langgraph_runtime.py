"""
File purpose:
- Execute ATR's closed-loop workflow through a config-driven LangGraph runtime.

Key classes/functions:
- LangGraphRunLoop

Inputs/outputs:
- Input: OrchestratorState, agent registry, graph config, runtime context
- Output: updated OrchestratorState and standard runtime events

Dependencies:
- graphs.compiler.ATRLangGraphCompiler
- graphs.registry.HandlerRegistry
- agents.registry.AgentRegistry

Modification guide:
- Safe places to edit: event metadata, additive state merge fields, new node handlers
- Risky places to edit: stage transition semantics and live-device safety gates
- Related files: graphs/configs/*.yaml, app/controller.py
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

from agents.base_agent import AgentContext, AgentResult
from agents.registry import AgentRegistry
from backends.prompt_registry import get_system_prompt
from graphs import ATRLangGraphCompiler, GraphConfig, HandlerRegistry, load_graph_config
from graphs.generated_adapter import GENERATED_MODULE_HANDLER_ID, generated_adapter_enabled, load_generated_adapter_run
from logging_system.error_logger import log_error
from logging_system.event_logger import log_agent_event, log_system_event
from logging_system.structured_logger import StructuredLogger
from orchestrator.state import AgentRuntimeStatus, OrchestratorState, Stage
from policies.recovery_policy import recovery_action
from policies.retry_policy import bump_retry, should_retry
from policies.safe_stop_policy import safe_stop_reason
from policies.validation_policy import validate_agent_output
from utils.ids import make_event_id

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
RUNTIME_ARTIFACT_COPY_LIMIT_BYTES = 50 * 1024 * 1024


class GeneratedModuleRuntimeAdapter:
    """Explicitly approved Module Designer adapter wrapper."""

    def __init__(self, modules_root: Path, module_id: str) -> None:
        self.modules_root = modules_root
        self.module_id = module_id
        self.name = f"generated:{module_id}"

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        """Load, validate, and execute the generated adapter run coroutine."""
        run = load_generated_adapter_run(self.modules_root, self.module_id)
        result = await run(state, ctx)
        if isinstance(result, AgentResult):
            return result
        if isinstance(result, dict):
            data = result.get("data") if isinstance(result.get("data"), dict) else dict(result)
            return AgentResult(
                success=bool(result.get("success", result.get("ok", True))),
                summary=str(result.get("summary") or f"generated adapter {self.module_id} completed"),
                data=data,
                next_hint=result.get("next_hint") if isinstance(result.get("next_hint"), str) else None,
            )
        raise TypeError(f"generated adapter {self.module_id} returned unsupported type={type(result).__name__}")

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


class ModuleToolRegistryProxy:
    """Stage-scoped tool allowlist view over the shared ToolRegistry."""

    def __init__(self, base_tools: Any, allowed_tools: list[str], stage: Stage) -> None:
        self._base = base_tools
        self._stage = stage
        self._allowed = {str(tool).strip() for tool in allowed_tools if str(tool).strip()}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    def _ensure_allowed(self, name: str) -> None:
        if self._allowed and name not in self._allowed:
            allowed = ", ".join(sorted(self._allowed))
            raise PermissionError(f"Tool not allowed for stage={self._stage.value}: {name}. allowed={allowed}")

    def call(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call only tools declared by the active module config."""
        self._ensure_allowed(name)
        return self._base.call(name, payload)

    def list_tools(self) -> list[str]:
        """Expose only declared tools that are available in the shared registry."""
        tools = list(self._base.list_tools())
        if not self._allowed:
            return sorted(tools)
        return sorted(tool for tool in tools if tool in self._allowed)

    def queue_status(self) -> dict[str, Any]:
        """Queue status remains visible for dashboard/debugging."""
        return self._base.queue_status()


def _standard_event_type(event_type: str) -> str:
    """Map legacy ATR event names to Runtime IDE event schema names."""
    return {
        "run_created": "run.created",
        "run_start": "run.started",
        "run_complete": "run.completed",
        "run_error": "run.failed",
        "run_stop": "run.stopped",
        "paused": "run.paused",
        "agent_started": "node.started",
        "agent_result": "node.completed",
        "fatal_error": "node.failed",
        "retry": "node.retrying",
        "stage_transition": "edge.traversed",
        "routing_error": "node.failed",
        "stage_mismatch": "node.failed",
        "orchestrator_plan": "node.completed",
        "safe_stop": "run.stopped",
        "module_graph_started": "module.graph.started",
        "module_step_planned": "module.step.planned",
        "module_step_started": "module.step.started",
        "module_step_completed": "module.step.completed",
        "module_step_failed": "module.step.failed",
        "module_graph_completed": "module.graph.completed",
        "module_graph_failed": "module.graph.failed",
        "module_pre_step_started": "module.pre_step.started",
        "module_pre_step_completed": "module.pre_step.completed",
        "module_pre_step_failed": "module.pre_step.failed",
    }.get(event_type, event_type)


class ModuleRuntimeContext:
    """Stage-scoped AgentContext proxy applying module config LLM/prompt hints."""

    def __init__(
        self,
        base: AgentContext,
        module_config: dict[str, Any],
        stage: Stage,
        active_internal_step: dict[str, Any] | None = None,
    ) -> None:
        self._base = base
        self._module = module_config
        self._stage = stage
        self._active_internal_step = dict(active_internal_step or {})
        self._llm = module_config.get("llm") if isinstance(module_config.get("llm"), dict) else {}
        self._prompt = module_config.get("prompt") if isinstance(module_config.get("prompt"), dict) else {}
        self._timeout_s = module_config.get("timeout_s")
        self._task_type = str(module_config.get("llm_role") or "").strip()
        self._allowed_tools = module_config.get("tools") if isinstance(module_config.get("tools"), list) else []
        self.active_backend = str(self._llm.get("backend") or base.active_backend).strip() or base.active_backend
        base_tools = getattr(base, "tools", None)
        if base_tools is not None and self._allowed_tools:
            self.tools = ModuleToolRegistryProxy(base_tools, self._allowed_tools, stage)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    def runtime_module_config(self) -> dict[str, Any]:
        """Return the stage module config visible to agents that opt in."""
        payload = dict(self._module)
        if self._active_internal_step:
            payload["active_internal_step"] = dict(self._active_internal_step)
        return payload

    def _system_prompt(self, task_type: str) -> str:
        configured = str(self._prompt.get("system") or "").strip()
        return configured or get_system_prompt(task_type)

    def _user_prompt(self, user_prompt: str) -> str:
        developer = str(self._prompt.get("developer") or "").strip()
        if not developer:
            return user_prompt
        return f"[Module developer guidance: {developer}]\n\n{user_prompt}"

    async def _notify_model_call(self, task_type: str, model: str, role: str) -> None:
        """Notify controller hooks with the module-selected backend name."""
        callback = getattr(self._base, "on_model_call", None)
        if callback is not None:
            try:
                result = callback(task_type=task_type, model=model, role=role, backend=self.active_backend)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                return
            return
        fallback_notify = getattr(self._base, "_notify_model_call", None)
        if fallback_notify is not None:
            result = fallback_notify(task_type=task_type, model=model, role=role)
            if inspect.isawaitable(result):
                await result

    async def complete(
        self,
        task_type: str,
        user_prompt: str,
        *,
        timeout_s: float | None = None,
    ):
        """Call the module-selected LLM route without changing Python agent code."""
        effective_task = self._task_type or task_type
        effective_timeout = timeout_s
        if effective_timeout is None and isinstance(self._timeout_s, (int, float)) and float(self._timeout_s) > 0:
            effective_timeout = float(self._timeout_s)
        backend_name = self.active_backend
        router = self._base.model_routers.get(backend_name, self._base.model_router)
        primary_backend = self._base.primary_backends.get(backend_name, self._base.primary_backend)
        fallback_backend = self._base.fallback_backends.get(backend_name, self._base.fallback_backend)
        selection = router.select(effective_task)
        primary_model = str(self._llm.get("model") or self._llm.get("primary") or selection.primary)
        fallback_model = str(self._llm.get("fallback") or selection.fallback or primary_model)
        system_prompt = self._system_prompt(effective_task)
        routed_prompt = self._user_prompt(user_prompt)

        async def _call_backend(backend, model: str, role: str):
            metadata = {
                "task_type": effective_task,
                "requested_task_type": task_type,
                "role": role,
                "stage": self._stage.value,
                "module_id": self._module.get("id", ""),
                "module_config_applied": True,
            }
            if self._active_internal_step:
                metadata["module_step_id"] = self._active_internal_step.get("id", "")
                metadata["module_step_kind"] = self._active_internal_step.get("kind", "")
            coro = backend.complete(
                model=model,
                system_prompt=system_prompt,
                user_prompt=routed_prompt,
                metadata=metadata,
            )
            if effective_timeout is not None and effective_timeout > 0:
                return await asyncio.wait_for(coro, timeout=effective_timeout)
            return await coro

        try:
            response = await _call_backend(primary_backend, primary_model, selection.role)
            await self._notify_model_call(task_type=effective_task, model=primary_model, role=selection.role)
            return response
        except Exception as primary_error:
            if fallback_backend is primary_backend and fallback_model == primary_model:
                raise primary_error
            try:
                response = await _call_backend(fallback_backend, fallback_model, f"{selection.role}:fallback")
                await self._notify_model_call(task_type=effective_task, model=fallback_model, role=f"{selection.role}:fallback")
                return response
            except Exception as fallback_error:
                raise RuntimeError(
                    f"LLM call failed task={effective_task} primary={primary_model} fallback={fallback_model}"
                ) from fallback_error


class LangGraphRunLoop:
    """Main orchestration engine backed by a compiled LangGraph graph."""

    def __init__(
        self,
        *,
        state: OrchestratorState,
        agent_registry: AgentRegistry,
        orchestrator_agent_name: str,
        ctx: AgentContext,
        logger: StructuredLogger,
        max_retry_per_stage: int = 2,
        interval_seconds: float = 1.25,
        on_event: EventCallback | None = None,
        graph_config_path: str | Path | None = None,
        module_root: str | Path | None = None,
        run_orchestrator_before_design: bool | None = None,
    ) -> None:
        self._state = state
        self._agent_registry = agent_registry
        self._orchestrator_agent_name = orchestrator_agent_name
        self._ctx = ctx
        self._logger = logger
        self._max_retry_per_stage = max_retry_per_stage
        self._interval_seconds = interval_seconds
        self._on_event = on_event
        self._run_orchestrator_before_design = run_orchestrator_before_design
        self._module_root = self._resolve_module_root(module_root)
        self._graph_config = self._load_config(graph_config_path)
        self._module_configs = self._load_module_configs()
        self._pause_notice_emitted = False
        self._handler_registry = self._build_handler_registry()
        module_ids = {str(module.get("id") or stage) for stage, module in self._module_configs.items()}
        self._compiled_graph = ATRLangGraphCompiler(self._graph_config, self._handler_registry, module_ids=module_ids).compile()

    @staticmethod
    def _load_config(graph_config_path: str | Path | None) -> GraphConfig:
        """Load the configured executable graph."""
        if graph_config_path is None:
            graph_config_path = Path(__file__).resolve().parent.parent / "graphs" / "configs" / "atr_closed_loop.yaml"
        return load_graph_config(graph_config_path)

    @staticmethod
    def _resolve_module_root(module_root: str | Path | None) -> Path:
        """Return the graph root containing module paths such as modules/design."""
        if module_root is None:
            return Path(__file__).resolve().parent.parent / "graphs"
        return Path(module_root)

    def _load_module_configs(self) -> dict[str, dict[str, Any]]:
        """Load editable module configs referenced by graph nodes."""
        configs: dict[str, dict[str, Any]] = {}
        for node in self._graph_config.nodes:
            if not node.stage or not node.module_id:
                continue
            module_path = self._module_root / node.module_id / "module.yaml"
            if not module_path.exists():
                continue
            raw = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
            module = raw.get("module", raw) if isinstance(raw, dict) else {}
            if isinstance(module, dict):
                configs[node.stage] = module
        return configs

    def _graph_node_for_stage(self, stage: Stage):
        """Return the graph node bound to one stage, if present."""
        for node in self._graph_config.nodes:
            if node.stage == stage.value:
                return node
        return None

    def _handler_for_stage(self, stage: Stage) -> str:
        """Resolve the executable handler id strictly from module/graph config."""
        module = self._module_config_for_stage(stage)
        module_handler = str(module.get("handler") or "").strip() if module else ""
        if module_handler:
            return module_handler
        node = self._graph_node_for_stage(stage)
        return str(node.handler).strip() if node and node.handler else ""

    def _agent_name_for_stage(self, stage: Stage) -> str | None:
        """Resolve actual agent registry name from the configured handler id."""
        handler = self._handler_for_stage(stage)
        if handler.startswith("agent."):
            return handler.removeprefix("agent.")
        return None


    def _module_config_for_stage(self, stage: Stage) -> dict[str, Any]:
        """Return one stage module config, if configured."""
        return dict(self._module_configs.get(stage.value, {}))

    def _context_for_stage(
        self,
        stage: Stage,
        active_internal_step: dict[str, Any] | None = None,
    ) -> AgentContext | ModuleRuntimeContext:
        """Return a stage-scoped context that applies module config hints."""
        module = self._module_config_for_stage(stage)
        if not module or not isinstance(self._ctx, AgentContext):
            return self._ctx
        return ModuleRuntimeContext(self._ctx, module, stage, active_internal_step=active_internal_step)

    def _module_runtime_payload(self, stage: Stage) -> dict[str, Any]:
        """Return sanitized module config details for events/state metadata."""
        module = self._module_config_for_stage(stage)
        if not module:
            return {}
        prompt = module.get("prompt") if isinstance(module.get("prompt"), dict) else {}
        metadata = module.get("metadata") if isinstance(module.get("metadata"), dict) else {}
        internal_steps = []
        if isinstance(module.get("internal_graph"), list):
            for index, step in enumerate(module["internal_graph"], start=1):
                if not isinstance(step, dict):
                    continue
                handler_configured = bool(str(step.get("handler") or "").strip())
                internal_steps.append(
                    {
                        "index": index,
                        "id": str(step.get("id") or f"step_{index}"),
                        "label": str(step.get("label") or step.get("id") or f"Step {index}"),
                        "kind": str(step.get("kind") or "internal_step"),
                        "handler": str(step.get("handler") or module.get("handler") or ""),
                        "handler_configured": handler_configured,
                    }
                )
        pre_steps = []
        if isinstance(module.get("pre_execution"), list):
            for index, step in enumerate(module["pre_execution"], start=1):
                if not isinstance(step, dict):
                    continue
                pre_steps.append(
                    {
                        "index": index,
                        "id": str(step.get("id") or f"pre_step_{index}"),
                        "label": str(step.get("label") or step.get("id") or f"Pre Step {index}"),
                        "kind": str(step.get("kind") or "pre_stage"),
                        "handler": str(step.get("handler") or ""),
                        "output_key": str(step.get("output_key") or step.get("id") or f"pre_step_{index}"),
                        "event_type": str(step.get("event_type") or "module_pre_step_completed"),
                        "enabled": bool(step.get("enabled", True)),
                    }
                )
        return {
            "module_id": module.get("id", stage.value),
            "label": module.get("label", ""),
            "handler": module.get("handler", ""),
            "effective_handler": self._handler_for_stage(stage),
            "llm_role": module.get("llm_role", ""),
            "llm": module.get("llm", {}) if isinstance(module.get("llm"), dict) else {},
            "prompt": {
                "path": prompt.get("path", ""),
                "system_override": bool(prompt.get("system")),
                "developer_override": bool(prompt.get("developer")),
            },
            "generated_adapter": {
                "handler_id": metadata.get("generated_adapter_handler_id", ""),
                "approved": bool(metadata.get("generated_adapter_approved", False)),
                "pending_registration": bool(metadata.get("pending_handler_registration", False)),
                "path": metadata.get("generated_adapter_path") or metadata.get("transformed_python_source_path") or metadata.get("transformed_source_path") or "",
            },
            "tools": module.get("tools", []) if isinstance(module.get("tools"), list) else [],
            "timeout_s": module.get("timeout_s"),
            "retry": module.get("retry", {}) if isinstance(module.get("retry"), dict) else {},
            "safety": module.get("safety", {}) if isinstance(module.get("safety"), dict) else {},
            "internal_graph": internal_steps,
            "pre_execution": pre_steps,
        }

    def _build_handler_registry(self) -> HandlerRegistry:
        """Register only allowlisted runtime/agent handlers."""
        registry = HandlerRegistry()
        registry.register("runtime.dispatch", self._dispatch_node)
        registry.register("runtime.idle", self._idle_node)
        registry.register("runtime.terminal", self._terminal_node)
        registry.register("runtime.step_complete", self._step_complete_node)
        registry.register(GENERATED_MODULE_HANDLER_ID, self._step_complete_node)
        for node in self._graph_config.nodes:
            if not node.handler.startswith("agent.") or not node.stage:
                continue
            stage = Stage(node.stage)
            registry.register(node.handler, self._make_agent_node(stage))
        return registry

    async def _dispatch_node(self, runtime_state: dict[str, Any]) -> dict[str, Any]:
        """LangGraph dispatch node; routing is handled by conditional edges."""
        self._state = runtime_state["state"]
        return {"state": self._state}

    async def _idle_node(self, runtime_state: dict[str, Any]) -> dict[str, Any]:
        """Enter the configured first executable stage."""
        self._state = runtime_state["state"]
        next_stage = self._coerce_stage(self._graph_config.next_stage(Stage.IDLE.value, state_metadata=self._state.run_metadata))
        self._state.stage = next_stage
        await self._emit(
            event_type="stage_transition",
            message=f"Transition idle -> {next_stage.value}",
            payload={"node_id": "idle", "status": "done"},
        )
        return {"state": self._state}

    async def _terminal_node(self, runtime_state: dict[str, Any]) -> dict[str, Any]:
        """Terminal stage no-op for complete/error graph states."""
        self._state = runtime_state["state"]
        return {"state": self._state}

    async def _step_complete_node(self, runtime_state: dict[str, Any]) -> dict[str, Any]:
        """Marker node used to finish exactly one runtime step per graph invoke."""
        self._state = runtime_state["state"]
        return {"state": self._state}

    def _make_agent_node(self, stage: Stage) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
        async def _node(runtime_state: dict[str, Any]) -> dict[str, Any]:
            self._state = runtime_state["state"]
            await self._execute_agent_stage(stage)
            return {"state": self._state}

        return _node

    @staticmethod
    def _coerce_stage(stage_value: str) -> Stage:
        """Convert configured stage strings to typed Stage values."""
        return Stage(stage_value)

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
        ts = datetime.now(timezone.utc).isoformat()
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
            "ts": ts,
            "type": _standard_event_type(event_type),
            "severity": level.lower(),
            "graph_id": self._graph_config.id,
            "node_id": payload.get("node_id", self._state.stage.value),
            "module_id": payload.get("module_id", ""),
            "agent": payload.get("agent", ""),
            "status": payload.get("status", "failed" if level == "ERROR" else "ok"),
        }
        await self._dispatch_event(event)

    @staticmethod
    def _agent_now_iso(agent: Any) -> str:
        """Return agent timestamp with a safe fallback for adapter/test agents."""
        now_iso = getattr(agent, "now_iso", None)
        if callable(now_iso):
            try:
                return str(now_iso())
            except Exception:
                pass
        return datetime.now(timezone.utc).isoformat()

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
        if specimen_result:
            self._state.run_metadata["specimen_result"] = specimen_result
        if isinstance(specimen_result.get("experiment_evaluation"), dict):
            self._state.experiment_evaluations.append(specimen_result["experiment_evaluation"])
        if "observation" in data:
            self._state.latest_observations = data["observation"]
        if "analysis" in data:
            self._state.latest_analysis.update(data["analysis"])
        if "sarm" in data:
            self._state.latest_analysis["sarm"] = data["sarm"]
        if "manipulation" in data:
            self._state.run_metadata["manipulation_result"] = data["manipulation"]
            self._state.latest_analysis["last_grasp_score"] = float(data["manipulation"].get("grasp_score", 0.0))
            if "sarm" in data:
                self._state.latest_analysis["sarm"] = data["sarm"]
        if "equipment_result" in data:
            equipment_result = data["equipment_result"] if isinstance(data["equipment_result"], dict) else {}
            self._state.run_metadata["equipment_result"] = equipment_result
            if "equipment_handoff" in data:
                self._state.run_metadata["equipment_handoff"] = data["equipment_handoff"]
            self._state.latest_analysis["equipment_ok"] = bool(equipment_result.get("ok", False))
            self._state.latest_analysis["equipment_status"] = str(equipment_result.get("status") or "")
            self._state.latest_analysis["equipment_program_id"] = str(equipment_result.get("program_id") or "")
            failure_code = equipment_result.get("failure_code")
            if failure_code:
                self._state.latest_analysis["equipment_failure_code"] = str(failure_code)
        if "knowledge" in data:
            self._state.run_metadata["knowledge"] = data["knowledge"]
        if "bo_result" in data:
            self._state.run_metadata["bo_agent"] = data["bo_result"]
        if "experiment_spec_update" in data and isinstance(data["experiment_spec_update"], dict):
            update = {key: value for key, value in data["experiment_spec_update"].items() if key != "cell_size_mm"}
            self._state.run_metadata["bo_recommended_constraints"] = update
        if "guardian" in data:
            self._state.run_metadata["guardian"] = data["guardian"]
        self._state.run_metadata["last_stage_payload"] = {"stage": stage.value, "data": data}

    def _apply_fault_injection(self) -> None:
        fault_stage = str(self._state.fault_injection.get("stage", ""))
        fault_name = str(self._state.fault_injection.get("fault", "none"))
        if self._state.mode.value == "fault-injection" and fault_name != "none" and fault_stage == self._state.stage.value:
            raise RuntimeError(f"Injected fault at stage={fault_stage}: {fault_name}")


    def _run_dir(self) -> Path:
        """Return the filesystem directory for the active run."""
        log_path = getattr(self._logger, "_jsonl_path", None)
        if log_path:
            return Path(log_path).expanduser().resolve().parent
        return (Path(__file__).resolve().parent.parent / "runs" / self._state.run_id).resolve()

    @staticmethod
    def _safe_artifact_segment(value: str, fallback: str = "artifact") -> str:
        """Return a filesystem-safe path segment for run artifacts."""
        clean = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
        return clean[:120] or fallback

    def _runtime_artifact_dir(self, stage: Stage) -> Path:
        """Return the run-local directory used for materialized runtime evidence."""
        output_dir = self._run_dir() / "runtime" / self._safe_artifact_segment(stage.value, "stage")
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _runtime_artifact_relpath(self, path: Path) -> str:
        """Return a run-relative artifact path for the Runtime IDE file API."""
        try:
            return path.resolve().relative_to(self._run_dir()).as_posix()
        except ValueError:
            return path.name

    def _write_stage_result_artifact(self, stage: Stage, agent_name: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Persist key stage result payloads so closed-loop runs have replayable evidence."""
        if stage not in {Stage.BO, Stage.ANALYSIS}:
            return None
        try:
            output_dir = self._runtime_artifact_dir(stage)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            safe_agent = self._safe_artifact_segment(agent_name, "agent")
            file_path = output_dir / f"{stamp}_{safe_agent}_result.json"
            file_path.write_text(json.dumps(data, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
            return {
                "key": "runtime.result",
                "path": self._runtime_artifact_relpath(file_path),
                "name": file_path.name,
                "source": "closed_loop_stage_result",
                "stage": stage.value,
                "agent": agent_name,
            }
        except Exception as exc:
            return {
                "key": "runtime.result",
                "path": "",
                "name": "",
                "source": "closed_loop_stage_result",
                "stage": stage.value,
                "agent": agent_name,
                "error": f"{exc.__class__.__name__}: {exc}",
            }

    @staticmethod
    def _iter_runtime_file_candidates(value: Any, path: str = "result") -> list[tuple[str, str]]:
        """Return likely local file paths embedded in an agent result."""
        path_keys = {
            "path",
            "stl_path",
            "sliced_path",
            "gcode_path",
            "log_path",
            "dataset_path",
            "checkpoint_path",
            "input_path",
            "report_path",
            "contour_svg_path",
            "artifact_path",
            "result_file",
        }
        candidates: list[tuple[str, str]] = []
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                if key in path_keys and isinstance(child, str) and child.strip():
                    candidates.append((child_path, child.strip()))
                candidates.extend(LangGraphRunLoop._iter_runtime_file_candidates(child, child_path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                candidates.extend(LangGraphRunLoop._iter_runtime_file_candidates(child, f"{path}[{index}]"))
        return candidates

    @staticmethod
    def _resolve_runtime_source_path(value: str) -> Path:
        """Resolve an artifact source path relative to the project root when needed."""
        source = Path(value).expanduser()
        if source.is_absolute():
            return source.resolve()
        return (Path(__file__).resolve().parent.parent / source).resolve()

    def _copy_runtime_file_artifact(self, *, stage: Stage, key: str, source_value: str) -> dict[str, Any] | None:
        """Copy a closed-loop produced file into the active run directory."""
        try:
            source = self._resolve_runtime_source_path(source_value)
            if not source.exists() or not source.is_file():
                return None
            output_dir = self._runtime_artifact_dir(stage)
            digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()[:10]
            safe_key = self._safe_artifact_segment(key.replace(".", "_").replace("[", "_").replace("]", ""), "file")
            target_name = f"{safe_key}_{digest}_{source.name}"
            target = output_dir / target_name
            size = source.stat().st_size
            try:
                source.relative_to(self._run_dir())
                already_in_run = True
            except ValueError:
                already_in_run = False
            if already_in_run:
                return None
            if size <= RUNTIME_ARTIFACT_COPY_LIMIT_BYTES:
                if source.resolve() != target.resolve():
                    shutil.copy2(source, target)
                copied = True
            else:
                target = output_dir / f"{target_name}.pointer.json"
                target.write_text(
                    json.dumps(
                        {
                            "source_path": str(source),
                            "source_size_bytes": size,
                            "reason": "source file exceeded runtime artifact copy limit",
                            "copy_limit_bytes": RUNTIME_ARTIFACT_COPY_LIMIT_BYTES,
                        },
                        indent=2,
                        ensure_ascii=True,
                    ),
                    encoding="utf-8",
                )
                copied = False
            return {
                "key": key,
                "path": self._runtime_artifact_relpath(target),
                "name": target.name,
                "source_path": str(source),
                "source_size_bytes": size,
                "copied": copied,
                "stage": stage.value,
            }
        except Exception as exc:
            return {
                "key": key,
                "path": "",
                "name": "",
                "source_path": source_value,
                "stage": stage.value,
                "error": f"{exc.__class__.__name__}: {exc}",
            }

    @staticmethod
    def _bo_strategies_from_result(result: dict[str, Any]) -> dict[str, Any]:
        """Extract benchmark strategy payloads from closed-loop BO result shapes."""
        if isinstance(result.get("strategies"), dict):
            return result["strategies"]
        benchmark = result.get("benchmark") if isinstance(result.get("benchmark"), dict) else {}
        if isinstance(benchmark.get("strategies"), dict):
            return benchmark["strategies"]
        bo_result = result.get("bo_result") if isinstance(result.get("bo_result"), dict) else {}
        benchmark = bo_result.get("benchmark") if isinstance(bo_result.get("benchmark"), dict) else {}
        if isinstance(benchmark.get("strategies"), dict):
            return benchmark["strategies"]
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        bo_result = data.get("bo_result") if isinstance(data.get("bo_result"), dict) else {}
        benchmark = bo_result.get("benchmark") if isinstance(bo_result.get("benchmark"), dict) else {}
        if isinstance(benchmark.get("strategies"), dict):
            return benchmark["strategies"]
        return {}

    def _write_bo_progress_artifact(self, stage: Stage, data: dict[str, Any]) -> dict[str, Any] | None:
        """Write a compact BO progress/acquisition SVG for live closed-loop evidence."""
        strategies = self._bo_strategies_from_result(data)
        if not strategies:
            return None
        colors = ["#1d4ed8", "#047857", "#b45309", "#be123c"]
        width, height = 760, 360
        margin_left, margin_right, margin_top, margin_bottom = 70, 30, 48, 64
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom
        series: list[tuple[str, list[tuple[float, float]]]] = []
        values: list[float] = []
        max_step = 1.0
        for name, payload in strategies.items():
            if not isinstance(payload, dict):
                continue
            points: list[tuple[float, float]] = []
            for item in payload.get("curve", []):
                if not isinstance(item, dict) or item.get("best_score") is None:
                    continue
                try:
                    step = float(item.get("step", len(points) + 1))
                    score = float(item["best_score"])
                except (TypeError, ValueError):
                    continue
                points.append((step, score))
                values.append(score)
                max_step = max(max_step, step)
            if points:
                series.append((str(name), points))
        if not series or not values:
            return None
        min_value = min(values)
        max_value = max(values)
        span = max(max_value - min_value, 1e-9)

        def sx(step: float) -> float:
            return margin_left + ((step - 1.0) / max(max_step - 1.0, 1.0)) * plot_w

        def sy(score: float) -> float:
            return margin_top + (1.0 - ((score - min_value) / span)) * plot_h

        paths: list[str] = []
        legends: list[str] = []
        for idx, (name, points) in enumerate(series):
            color = colors[idx % len(colors)]
            commands = " ".join(f"{'M' if point_idx == 0 else 'L'} {sx(step):.2f} {sy(score):.2f}" for point_idx, (step, score) in enumerate(points))
            circles = "\n".join(
                f'<circle cx="{sx(step):.2f}" cy="{sy(score):.2f}" r="4.2" fill="{color}" stroke="#ffffff" stroke-width="1.5"/>'
                for step, score in points
            )
            paths.append(f'<path d="{commands}" fill="none" stroke="{color}" stroke-width="2.8"/>\n{circles}')
            legends.append(
                f'<g transform="translate({margin_left + idx * 150}, 326)"><rect width="14" height="14" rx="3" fill="{color}"/>'
                f'<text x="22" y="12" font-family="Arial, sans-serif" font-size="13" fill="#334155">{name}</text></g>'
            )
        latest_trace = ""
        bo_payload = strategies.get("bo") if isinstance(strategies.get("bo"), dict) else {}
        surrogate = bo_payload.get("surrogate_trace") if isinstance(bo_payload.get("surrogate_trace"), list) else []
        if surrogate:
            last = surrogate[-1] if isinstance(surrogate[-1], dict) else {}
            selected = last.get("selected") if isinstance(last.get("selected"), dict) else {}
            latest_trace = (
                f"latest acquisition={last.get('acquisition', '')}, "
                f"selected={selected.get('candidate_id', '')}, "
                f"value={selected.get('acquisition_value', '')}"
            )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
            '<rect width="100%" height="100%" fill="#ffffff"/>\n'
            '<text x="28" y="30" font-family="Arial, sans-serif" font-size="20" font-weight="700" fill="#0f172a">BO progress and acquisition trace</text>\n'
            f'<text x="28" y="52" font-family="Arial, sans-serif" font-size="13" fill="#475569">{latest_trace}</text>\n'
            f'<rect x="{margin_left}" y="{margin_top}" width="{plot_w}" height="{plot_h}" fill="#f8fafc" stroke="#cbd5e1"/>\n'
            f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" stroke="#334155"/>\n'
            f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="#334155"/>\n'
            f'<text x="{margin_left}" y="{height - 22}" font-family="Arial, sans-serif" font-size="12" fill="#475569">iteration</text>\n'
            f'<text x="18" y="{margin_top + 12}" font-family="Arial, sans-serif" font-size="12" fill="#475569">best score</text>\n'
            f'<text x="{margin_left - 54}" y="{margin_top + 8}" font-family="Arial, sans-serif" font-size="11" fill="#64748b">{max_value:.3f}</text>\n'
            f'<text x="{margin_left - 54}" y="{margin_top + plot_h}" font-family="Arial, sans-serif" font-size="11" fill="#64748b">{min_value:.3f}</text>\n'
            f"{''.join(paths)}\n{''.join(legends)}\n"
            "</svg>\n"
        )
        try:
            output_dir = self._runtime_artifact_dir(stage)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            file_path = output_dir / f"{stamp}_bo_progress.svg"
            file_path.write_text(svg, encoding="utf-8")
            return {
                "key": "runtime.bo_progress",
                "path": self._runtime_artifact_relpath(file_path),
                "name": file_path.name,
                "source": "closed_loop_bo_progress",
                "stage": stage.value,
            }
        except Exception as exc:
            return {
                "key": "runtime.bo_progress",
                "path": "",
                "name": "",
                "source": "closed_loop_bo_progress",
                "stage": stage.value,
                "error": f"{exc.__class__.__name__}: {exc}",
            }

    def _register_runtime_artifacts(self, stage: Stage, agent_name: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Materialize closed-loop BO/CAE evidence under the active run directory."""
        if stage not in {Stage.BO, Stage.ANALYSIS}:
            return []
        records: list[dict[str, Any]] = []
        result_record = self._write_stage_result_artifact(stage, agent_name, data)
        if result_record:
            records.append(result_record)
        if stage == Stage.BO:
            bo_plot = self._write_bo_progress_artifact(stage, data)
            if bo_plot:
                records.append(bo_plot)
        seen_sources: set[str] = set()
        for key, source_path in self._iter_runtime_file_candidates(data):
            if source_path in seen_sources:
                continue
            seen_sources.add(source_path)
            record = self._copy_runtime_file_artifact(stage=stage, key=key, source_value=source_path)
            if record:
                records.append(record)
        if records:
            runtime_artifacts = self._state.run_metadata.setdefault("runtime_artifacts", [])
            if isinstance(runtime_artifacts, list):
                runtime_artifacts.extend(records)
        return records

    def _artifact_payloads(self, stage: Stage, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract artifact-like payloads from agent outputs for Runtime IDE lineage."""
        artifacts: list[dict[str, Any]] = []

        def _walk(value: Any, path: str) -> None:
            if isinstance(value, dict):
                is_artifact_key = path.split(".")[-1] in {"artifact", "artifacts", "specimen_artifacts", "fem_artifacts"}
                has_artifact_fields = any(key in value for key in {"path", "url", "stl_url", "preview_url", "experiment_spec_url", "contour_url", "report_url"})
                if is_artifact_key or has_artifact_fields:
                    artifacts.append({"stage": stage.value, "key": path, "value": value})
                for key, child in value.items():
                    _walk(child, f"{path}.{key}" if path else str(key))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    _walk(child, f"{path}[{index}]")

        _walk(data, "result")
        return artifacts

    async def _emit_artifact_events(self, stage: Stage, agent_name: str, data: dict[str, Any]) -> None:
        """Emit artifact.created aliases without changing agent result payload shape."""
        for artifact in self._register_runtime_artifacts(stage, agent_name, data):
            if not artifact.get("path"):
                continue
            await self._emit(
                event_type="artifact.created",
                message=f"{agent_name} runtime artifact file: {artifact['path']}",
                payload={"agent": agent_name, "node_id": stage.value, "status": "done", "artifact": artifact},
            )
        for artifact in self._artifact_payloads(stage, data):
            await self._emit(
                event_type="artifact.created",
                message=f"{agent_name} artifact created: {artifact['key']}",
                payload={"agent": agent_name, "node_id": stage.value, "status": "done", "artifact": artifact},
            )

    def _module_internal_steps(self, module_runtime: dict[str, Any]) -> list[dict[str, Any]]:
        """Return sanitized internal graph steps from module runtime metadata."""
        steps = module_runtime.get("internal_graph")
        if not isinstance(steps, list):
            return []
        return [dict(step) for step in steps if isinstance(step, dict)]

    async def _emit_module_graph_started(self, stage: Stage, agent_name: str, module_runtime: dict[str, Any]) -> None:
        """Emit module internal graph planning events before the monolithic handler runs."""
        steps = self._module_internal_steps(module_runtime)
        if not steps:
            return
        await self._emit(
            event_type="module_graph_started",
            message=f"{agent_name}: module internal graph planned",
            payload={
                "agent": agent_name,
                "node_id": stage.value,
                "module_id": module_runtime.get("module_id", ""),
                "status": "running",
                "module_runtime": module_runtime,
                "step_count": len(steps),
            },
        )
        for step in steps:
            await self._emit(
                event_type="module_step_planned",
                message=f"{agent_name}: planned module step {step.get('id')}",
                payload={
                    "agent": agent_name,
                    "node_id": stage.value,
                    "module_id": module_runtime.get("module_id", ""),
                    "status": "planned",
                    "module_step": step,
                    "module_runtime": module_runtime,
                },
            )

    async def _execute_module_internal_steps(
        self,
        *,
        stage: Stage,
        agent_name: str,
        module_runtime: dict[str, Any],
    ) -> None:
        """Execute configured module internal steps as runtime checkpoints or handler calls."""
        steps = self._module_internal_steps(module_runtime)
        if not steps:
            return
        traces = self._state.run_metadata.setdefault("module_step_trace", {})
        if not isinstance(traces, dict):
            traces = {}
            self._state.run_metadata["module_step_trace"] = traces
        stage_trace = traces.setdefault(stage.value, [])
        if not isinstance(stage_trace, list):
            stage_trace = []
            traces[stage.value] = stage_trace
        results = self._state.run_metadata.setdefault("module_step_results", {})
        if not isinstance(results, dict):
            results = {}
            self._state.run_metadata["module_step_results"] = results
        stage_results = results.setdefault(stage.value, {})
        if not isinstance(stage_results, dict):
            stage_results = {}
            results[stage.value] = stage_results

        for step in steps:
            step_id = str(step.get("id") or f"step_{step.get('index', len(stage_trace) + 1)}")
            handler = str(step.get("handler") or "").strip()
            handler_configured = bool(step.get("handler_configured"))
            step_agent_name = handler.removeprefix("agent.") if handler_configured and handler.startswith("agent.") else ""
            started = {
                "step_id": step_id,
                "handler": handler,
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            stage_trace.append(started)
            self._state.run_metadata["active_module_step"] = {
                "stage": stage.value,
                "module_id": module_runtime.get("module_id", ""),
                "step": step,
            }
            await self._emit(
                event_type="module_step_started",
                message=f"{agent_name}: module step {step_id} started",
                payload={
                    "agent": step_agent_name or agent_name,
                    "node_id": stage.value,
                    "module_id": module_runtime.get("module_id", ""),
                    "status": "running",
                    "module_step": step,
                    "module_runtime": module_runtime,
                    "handler": handler,
                    "executable": bool(step_agent_name),
                    "handler_configured": handler_configured,
                },
            )
            try:
                result_data: dict[str, Any] = {}
                summary = "checkpoint"
                if step_agent_name:
                    if step_agent_name not in self._agent_registry.names():
                        raise RuntimeError(f"Configured module step handler resolved to missing agent={step_agent_name}")
                    step_ctx = self._context_for_stage(stage, active_internal_step=step)
                    result = await self._agent_registry.get(step_agent_name).run(self._state, step_ctx)
                    result_data = result.data
                    summary = result.summary
                    stage_results[step_id] = result_data
                started["status"] = "done"
                started["completed_at"] = datetime.now(timezone.utc).isoformat()
                await self._emit(
                    event_type="module_step_completed",
                    message=f"{agent_name}: module step {step_id} completed",
                    payload={
                        "agent": step_agent_name or agent_name,
                        "node_id": stage.value,
                        "module_id": module_runtime.get("module_id", ""),
                        "status": "done",
                        "module_step": step,
                        "module_runtime": module_runtime,
                        "handler": handler,
                        "executable": bool(step_agent_name),
                        "handler_configured": handler_configured,
                        "summary": summary,
                        "result_keys": sorted(result_data.keys()),
                    },
                )
            except Exception as exc:
                started["status"] = "error"
                started["completed_at"] = datetime.now(timezone.utc).isoformat()
                started["error"] = str(exc)
                await self._emit(
                    event_type="module_step_failed",
                    message=f"{agent_name}: module step {step_id} failed",
                    payload={
                        "agent": step_agent_name or agent_name,
                        "node_id": stage.value,
                        "module_id": module_runtime.get("module_id", ""),
                        "status": "error",
                        "module_step": step,
                        "module_runtime": module_runtime,
                        "handler": handler,
                        "executable": bool(step_agent_name),
                        "handler_configured": handler_configured,
                        "error": str(exc),
                    },
                    level="ERROR",
                )
                raise
            finally:
                self._state.run_metadata.pop("active_module_step", None)


    async def _emit_module_graph_completed(
        self,
        stage: Stage,
        agent_name: str,
        module_runtime: dict[str, Any],
        result_data: dict[str, Any],
    ) -> None:
        """Emit a module-level completion event after the stage handler succeeds."""
        steps = self._module_internal_steps(module_runtime)
        if not steps:
            return
        await self._emit(
            event_type="module_graph_completed",
            message=f"{agent_name}: module internal graph completed",
            payload={
                "agent": agent_name,
                "node_id": stage.value,
                "module_id": module_runtime.get("module_id", ""),
                "status": "done",
                "module_runtime": module_runtime,
                "step_count": len(steps),
                "result_keys": sorted(result_data.keys()),
            },
        )

    async def _emit_module_graph_failed(
        self,
        stage: Stage,
        agent_name: str,
        module_runtime: dict[str, Any],
        error: Exception,
    ) -> None:
        """Emit a module-level failure event when the stage handler fails."""
        steps = self._module_internal_steps(module_runtime)
        if not steps:
            return
        await self._emit(
            event_type="module_graph_failed",
            message=f"{agent_name}: module internal graph failed",
            payload={
                "agent": agent_name,
                "node_id": stage.value,
                "module_id": module_runtime.get("module_id", ""),
                "status": "error",
                "module_runtime": module_runtime,
                "step_count": len(steps),
                "error": str(error),
            },
            level="ERROR",
        )


    def _approval_gate_key(self, stage: Stage, module_runtime: dict[str, Any]) -> str:
        """Return the per-run-loop approval key for one module stage."""
        module_id = str(module_runtime.get("module_id") or stage.value)
        return f"{stage.value}:loop-{self._state.loop_count}:{module_id}"

    def _module_retry_policy(self, module_runtime: dict[str, Any]) -> dict[str, float | int]:
        """Resolve stage retry policy from module config with global fallback."""
        retry = module_runtime.get("retry") if isinstance(module_runtime.get("retry"), dict) else {}
        max_attempts = self._max_retry_per_stage
        raw_max_attempts = retry.get("max_attempts") if isinstance(retry, dict) else None
        if isinstance(raw_max_attempts, int) and raw_max_attempts >= 0:
            max_attempts = raw_max_attempts
        backoff_s = 0.0
        raw_backoff = retry.get("backoff_s") if isinstance(retry, dict) else None
        if isinstance(raw_backoff, (int, float)) and float(raw_backoff) > 0:
            backoff_s = float(raw_backoff)
        return {"max_attempts": int(max_attempts), "backoff_s": backoff_s}


    async def _module_approval_ready(
        self,
        *,
        stage: Stage,
        agent_name: str,
        module_runtime: dict[str, Any],
        status: AgentRuntimeStatus,
    ) -> bool:
        """Enforce module.safety.requires_human_approval before executing a stage."""
        safety = module_runtime.get("safety") if isinstance(module_runtime.get("safety"), dict) else {}
        if not bool(safety.get("requires_human_approval")):
            return True

        approvals = self._state.run_metadata.setdefault("runtime_approvals", {})
        if not isinstance(approvals, dict):
            approvals = {}
            self._state.run_metadata["runtime_approvals"] = approvals
        gate_key = self._approval_gate_key(stage, module_runtime)
        gate = approvals.get(gate_key) if isinstance(approvals.get(gate_key), dict) else None
        if gate and str(gate.get("status") or "") == "approved":
            return True
        if gate and str(gate.get("status") or "") in {"rejected", "cancelled"}:
            status.state = "error"
            status.success = False
            self._state.stage = Stage.ERROR
            await self._emit(
                event_type="fatal_error",
                message=f"Human approval {gate.get('status')} for stage={stage.value}",
                payload={
                    "agent": agent_name,
                    "node_id": stage.value,
                    "module_id": module_runtime.get("module_id", ""),
                    "status": "error",
                    "approval_id": gate.get("approval_id", ""),
                    "gate_key": gate_key,
                    "decision": gate.get("status"),
                },
                level="ERROR",
            )
            return False

        if not gate:
            approval_id = make_event_id().replace("evt-", "approval-", 1)
            gate = {
                "approval_id": approval_id,
                "gate_key": gate_key,
                "stage": stage.value,
                "module_id": module_runtime.get("module_id", stage.value),
                "agent": agent_name,
                "status": "pending",
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "safety": safety,
            }
            approvals[gate_key] = gate
            self._state.is_paused = True
            status.state = "waiting_approval"
            status.success = None
            await self._emit(
                event_type="approval.requested",
                message=f"Human approval required before {stage.value}",
                payload={
                    "approval_id": approval_id,
                    "gate_key": gate_key,
                    "title": f"Human approval required: {stage.value}",
                    "reason": "module.safety.requires_human_approval is enabled",
                    "stage": stage.value,
                    "node_id": stage.value,
                    "module_id": module_runtime.get("module_id", ""),
                    "agent": agent_name,
                    "safety_class": "module_safety_gate",
                    "requires_human_approval": True,
                    "status": "waiting_approval",
                    "module_runtime": module_runtime,
                },
                level="WARNING",
            )
        else:
            self._state.is_paused = True
            status.state = "waiting_approval"

        self._state.run_metadata["approval_blocked_stage"] = {
            "stage": stage.value,
            "agent": agent_name,
            "gate_key": gate_key,
            "approval_id": gate.get("approval_id", ""),
        }
        return False

    def _pre_execution_enabled(self, stage: Stage, module_runtime: dict[str, Any]) -> bool:
        """Resolve whether module pre-execution steps should run for this stage."""
        steps = module_runtime.get("pre_execution")
        if not isinstance(steps, list) or not steps:
            return False
        if self._run_orchestrator_before_design is False and stage == Stage.DESIGN:
            return False
        if self._run_orchestrator_before_design is True and stage == Stage.DESIGN:
            return True
        return True

    async def _execute_module_pre_steps(
        self,
        *,
        stage: Stage,
        module_runtime: dict[str, Any],
    ) -> None:
        """Execute config-declared pre-stage agent steps before the stage handler."""
        if not self._pre_execution_enabled(stage, module_runtime):
            return
        steps = [step for step in module_runtime.get("pre_execution", []) if isinstance(step, dict) and step.get("enabled", True)]
        for step in steps:
            handler = str(step.get("handler") or "").strip()
            if not handler.startswith("agent."):
                raise RuntimeError(f"Invalid pre_execution handler for stage={stage.value}: {handler}")
            agent_name = handler.removeprefix("agent.")
            if agent_name not in self._agent_registry.names():
                raise RuntimeError(f"Missing pre_execution agent={agent_name} for stage={stage.value}")
            await self._emit(
                event_type="module_pre_step_started",
                message=f"{agent_name}: pre-execution step {step.get('id')} started",
                payload={
                    "agent": agent_name,
                    "node_id": stage.value,
                    "module_id": module_runtime.get("module_id", ""),
                    "status": "running",
                    "module_runtime": module_runtime,
                    "module_pre_step": step,
                },
            )
            try:
                result = await self._agent_registry.get(agent_name).run(self._state, self._ctx)
            except Exception as exc:
                await self._emit(
                    event_type="module_pre_step_failed",
                    message=f"{agent_name}: pre-execution step {step.get('id')} failed",
                    payload={
                        "agent": agent_name,
                        "node_id": stage.value,
                        "module_id": module_runtime.get("module_id", ""),
                        "status": "error",
                        "module_runtime": module_runtime,
                        "module_pre_step": step,
                        "error": str(exc),
                    },
                    level="ERROR",
                )
                raise
            output_key = str(step.get("output_key") or step.get("id") or "pre_execution")
            self._state.run_metadata[output_key] = result.data
            completed_payload = {
                "agent": agent_name,
                "node_id": stage.value,
                "module_id": module_runtime.get("module_id", ""),
                "status": "done",
                "module_runtime": module_runtime,
                "module_pre_step": step,
                "result": result.data,
                **result.data,
            }
            await self._emit(
                event_type="module_pre_step_completed",
                message=f"{agent_name}: pre-execution step {step.get('id')} completed",
                payload=completed_payload,
            )
            event_type = str(step.get("event_type") or "").strip()
            if event_type and event_type != "module_pre_step_completed":
                await self._emit(
                    event_type=event_type,
                    message=result.summary,
                    payload={**completed_payload, "node_id": str(step.get("id") or stage.value)},
                )

    async def _execute_agent_stage(self, stage: Stage) -> None:
        """Execute one configured agent stage and update state for the next step."""
        if self._state.stage != stage:
            await self._emit(
                event_type="stage_mismatch",
                message=f"LangGraph routed node={stage.value} while state.stage={self._state.stage.value}",
                payload={"node_id": stage.value, "status": "skipped"},
                level="WARNING",
            )
            return
        handler = self._handler_for_stage(stage)
        module_runtime = self._module_runtime_payload(stage)
        module_id = str(module_runtime.get("module_id") or stage.value)
        is_generated_adapter = handler == GENERATED_MODULE_HANDLER_ID
        agent_name = self._agent_name_for_stage(stage)
        if not agent_name and not is_generated_adapter:
            self._state.stage = Stage.ERROR
            await self._emit(
                event_type="routing_error",
                message=f"No agent routing for stage={stage.value}",
                payload={"node_id": stage.value, "status": "error", "handler": handler, "module_runtime": module_runtime},
                level="ERROR",
            )
            return

        if is_generated_adapter:
            enabled, errors = generated_adapter_enabled(module_id, {"module": self._module_config_for_stage(stage)}, self._module_root / "modules")
            if not enabled:
                self._state.stage = Stage.ERROR
                await self._emit(
                    event_type="routing_error",
                    message=f"Generated adapter is not executable for stage={stage.value}",
                    payload={
                        "node_id": stage.value,
                        "status": "error",
                        "handler": handler,
                        "agent": f"generated:{module_id}",
                        "errors": errors,
                        "module_runtime": module_runtime,
                    },
                    level="ERROR",
                )
                return
            agent_name = f"generated:{module_id}"
            agent = GeneratedModuleRuntimeAdapter(self._module_root / "modules", module_id)
        else:
            if agent_name not in self._agent_registry.names():
                self._state.stage = Stage.ERROR
                await self._emit(
                    event_type="routing_error",
                    message=f"Configured handler resolved to missing agent={agent_name}",
                    payload={
                        "node_id": stage.value,
                        "status": "error",
                        "handler": handler,
                        "agent": agent_name,
                        "module_runtime": module_runtime,
                    },
                    level="ERROR",
                )
                return
            agent = self._agent_registry.get(agent_name)

        status = self._ensure_agent_status(agent_name)
        status.state = "running"
        status.mode = self._state.mode.value

        if module_runtime:
            self._state.run_metadata.setdefault("module_runtime", {})[stage.value] = module_runtime
        if not await self._module_approval_ready(stage=stage, agent_name=agent_name, module_runtime=module_runtime, status=status):
            return
        await self._emit(
            event_type="agent_started",
            message=f"{agent_name}: started",
            payload={"agent": agent_name, "node_id": stage.value, "status": "running", "module_runtime": module_runtime},
        )
        await self._emit_module_graph_started(stage, agent_name, module_runtime)
        try:
            self._apply_fault_injection()
            await self._execute_module_pre_steps(stage=stage, module_runtime=module_runtime)
            await self._execute_module_internal_steps(stage=stage, agent_name=agent_name, module_runtime=module_runtime)
            ctx = self._context_for_stage(stage)
            result = await agent.run(self._state, ctx)
            ok, validation_msg = validate_agent_output(stage.value, result.data)
            if not ok:
                raise ValueError(validation_msg)

            self._merge_agent_data(stage, result.data)
            status.state = "idle"
            status.last_result = result.summary
            status.last_run_time = self._agent_now_iso(agent)
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
                payload={"agent": agent_name, "node_id": stage.value, "status": "done", "module_runtime": module_runtime, "result": result.data},
            )
            await self._emit_module_graph_completed(stage, agent_name, module_runtime, result.data)
            await self._emit_artifact_events(stage, agent_name, result.data)

            guardian_decision = "continue"
            if stage == Stage.GUARDIAN:
                guardian_decision = str(result.data.get("guardian", {}).get("decision", "continue"))
                self._state.loop_count += 1
            transition_context = {**self._state.run_metadata, "agent_result": result.data}
            next_stage = self._coerce_stage(
                self._graph_config.next_stage(
                    stage.value,
                    guardian_decision=guardian_decision,
                    state_metadata=transition_context,
                )
            )
            candidates = self._graph_config.transition_candidates(stage.value)
            selected_candidate = next(
                (candidate for candidate in candidates if str(candidate.get("to_stage")) == next_stage.value),
                {},
            )
            self._state.stage = next_stage

            await self._emit(
                event_type="stage_transition",
                message=f"Transition {stage.value} -> {self._state.stage.value}",
                payload={
                    "node_id": stage.value,
                    "status": "done",
                    "from_stage": stage.value,
                    "to_stage": self._state.stage.value,
                    "transition_candidates": candidates,
                    "selected_transition": selected_candidate,
                },
            )
        except Exception as exc:
            status.state = "error"
            status.last_result = str(exc)
            status.last_run_time = self._agent_now_iso(agent)
            status.success = False
            log_error(
                self._logger,
                run_id=self._state.run_id,
                where=f"{agent_name}@{stage.value}",
                error=exc,
                state_snapshot=self._state.model_dump(mode="json"),
            )
            await self._emit_module_graph_failed(stage, agent_name, module_runtime, exc)

            retry_policy = self._module_retry_policy(module_runtime)
            max_attempts = int(retry_policy["max_attempts"])
            backoff_s = float(retry_policy["backoff_s"])
            if should_retry(self._state, stage.value, max_attempts):
                retry_count = bump_retry(self._state, stage.value)
                action = recovery_action(stage.value, str(exc))
                await self._emit(
                    event_type="retry",
                    message=f"Retry stage={stage.value} attempt={retry_count}",
                    payload={
                        "agent": agent_name,
                        "node_id": stage.value,
                        "status": "retry",
                        "error": str(exc),
                        "recovery": action,
                        "module_runtime": module_runtime,
                        "retry_policy": {"max_attempts": max_attempts, "backoff_s": backoff_s},
                        "retry_count": retry_count,
                    },
                    level="WARNING",
                )
                if backoff_s > 0:
                    await asyncio.sleep(backoff_s)
            else:
                self._state.stage = Stage.ERROR
                await self._emit(
                    event_type="fatal_error",
                    message=f"Stage={stage.value} exceeded retry budget: {exc}",
                    payload={
                        "agent": agent_name,
                        "node_id": stage.value,
                        "status": "error",
                        "error": str(exc),
                        "module_runtime": module_runtime,
                        "retry_policy": {"max_attempts": max_attempts, "backoff_s": backoff_s},
                    },
                    level="ERROR",
                )

    async def step(self) -> None:
        """Invoke the compiled LangGraph graph for exactly one runtime step."""
        if self._state.safe_stop_requested:
            self._state.stage = Stage.COMPLETE
            await self._emit(
                event_type="safe_stop",
                message=safe_stop_reason("safe_stop_requested flag"),
                payload={"node_id": "guardian", "status": "done"},
            )
            return
        result = await self._compiled_graph.ainvoke({"state": self._state})
        if isinstance(result, dict) and isinstance(result.get("state"), OrchestratorState):
            self._state = result["state"]

    async def run(self) -> OrchestratorState:
        """Run until complete/error/stop_requested using the compiled LangGraph runtime."""
        await self._emit(
            event_type="run_start",
            message="LangGraph orchestration run started",
            payload={"node_id": self._state.stage.value, "status": "running"},
        )
        while True:
            if self._state.stop_requested:
                self._state.stage = Stage.COMPLETE
                await self._emit(event_type="run_stop", message="Stop requested by operator")
                break

            if self._state.stage in {Stage.COMPLETE, Stage.ERROR}:
                break

            if self._state.is_paused:
                if not self._pause_notice_emitted:
                    await self._emit(event_type="paused", message="Run paused")
                    self._pause_notice_emitted = True
                await asyncio.sleep(0.25)
                continue

            self._pause_notice_emitted = False
            await self.step()
            await asyncio.sleep(self._interval_seconds)

        final_event = "run_complete" if self._state.stage == Stage.COMPLETE else "run_error"
        await self._emit(
            event_type=final_event,
            message=f"Run finished in stage={self._state.stage.value}",
            payload={"node_id": self._state.stage.value, "status": self._state.stage.value},
        )
        return self._state
