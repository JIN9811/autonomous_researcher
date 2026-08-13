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
import ctypes
import gc
import hashlib
import inspect
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import yaml

from agents.base_agent import AgentContext, AgentResult
from agents.registry import AgentRegistry
from backends.prompt_registry import get_system_prompt
from graphs import ATRLangGraphCompiler, GraphConfig, HandlerRegistry, load_graph_config
from graphs.generated_adapter import GENERATED_MODULE_HANDLER_ID, generated_adapter_enabled, load_generated_adapter_run
from logging_system.error_logger import log_error
from logging_system.event_logger import log_agent_event, log_system_event
from logging_system.structured_logger import StructuredLogger
from orchestrator.state import AgentRuntimeStatus, Mode, OrchestratorState, Stage
from orchestrator.supervisor import (
    build_decision_record,
    build_loop_reflection,
    build_mission_contract,
    build_orchestration_plan,
    build_orchestrator_control_plane_snapshot,
    build_orchestrator_followup,
    build_orchestrator_handoff_packet,
    build_orchestrator_parallel_check,
    build_orchestrator_parallel_check_batch,
)
from policies.recovery_policy import recovery_action
from policies.guardian_gate import gate_blocks_execution, guardian_gate, tool_requires_action_shield
from policies.retry_policy import bump_retry, should_retry
from policies.safe_stop_policy import safe_stop_reason
from policies.validation_policy import validate_agent_output
from reporting.bo_visualization_artifacts import write_bo_visualization_artifacts
from utils.active_cam_artifact import apply_active_cam_artifact_update
from utils.utm_completion_artifact import apply_utm_completion_artifact_update
from utils.ids import make_event_id

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
RUNTIME_ARTIFACT_COPY_LIMIT_BYTES = 50 * 1024 * 1024
RUNTIME_PAYLOAD_MAX_DEPTH = 8
RUNTIME_PAYLOAD_LIST_LIMIT = 80
RUNTIME_PAYLOAD_STRING_LIMIT = 3000
RUNTIME_PAYLOAD_LARGE_KEYS = {
    "raw_trace",
    "raw_events",
    "source_stage_context",
    "full_context",
    "full_payload",
    "raw_input_sidecar",
    "canonical_curve",
    "mesh_vertices",
    "mesh_faces",
    "stl_text",
    "stl_bytes",
}


def compact_runtime_payload(value: Any, *, depth: int = 0, seen: set[int] | None = None) -> Any:
    """Return a recursion-safe, UI-sized runtime payload for in-memory state/events."""
    if seen is None:
        seen = set()
    if depth >= RUNTIME_PAYLOAD_MAX_DEPTH:
        if isinstance(value, dict):
            return {"_truncated": "depth_limit", "keys": list(value.keys())[:24]}
        if isinstance(value, (list, tuple, set)):
            return {"_truncated": "depth_limit", "items": len(value)}
        text = str(value)
        return text[:RUNTIME_PAYLOAD_STRING_LIMIT] + "..." if len(text) > RUNTIME_PAYLOAD_STRING_LIMIT else value
    if isinstance(value, dict):
        obj_id = id(value)
        if obj_id in seen:
            return {"_omitted": "recursive_ref", "type": type(value).__name__}
        seen.add(obj_id)
        try:
            compact: dict[str, Any] = {}
            for key, child in value.items():
                key_text = str(key)
                if key_text in RUNTIME_PAYLOAD_LARGE_KEYS:
                    compact[key_text] = {
                        "_omitted": "large_runtime_payload",
                        "type": type(child).__name__,
                        "items": len(child) if isinstance(child, (dict, list, tuple, set)) else None,
                    }
                    continue
                compact[key_text] = compact_runtime_payload(child, depth=depth + 1, seen=seen)
            return compact
        finally:
            seen.remove(obj_id)
    if isinstance(value, (list, tuple, set)):
        obj_id = id(value)
        if obj_id in seen:
            return {"_omitted": "recursive_ref", "type": type(value).__name__}
        seen.add(obj_id)
        try:
            seq = list(value)
            items = [compact_runtime_payload(item, depth=depth + 1, seen=seen) for item in seq[:RUNTIME_PAYLOAD_LIST_LIMIT]]
            if len(seq) > RUNTIME_PAYLOAD_LIST_LIMIT:
                items.append({"_truncated_items": len(seq) - RUNTIME_PAYLOAD_LIST_LIMIT})
            return items
        finally:
            seen.remove(obj_id)
    if isinstance(value, str) and len(value) > RUNTIME_PAYLOAD_STRING_LIMIT:
        return value[:RUNTIME_PAYLOAD_STRING_LIMIT] + "..."
    return value


def trim_runtime_memory() -> None:
    """Release Python/c-lib heap pages after mesh/FEM/BO-heavy runtime stages."""
    try:
        gc.collect()
    except Exception:
        return
    if os.name != "posix":
        return
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        return


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

    def __init__(
        self,
        base_tools: Any,
        allowed_tools: list[str],
        stage: Stage,
        *,
        state: OrchestratorState | None = None,
        gate_recorder: Callable[[dict[str, Any]], None] | None = None,
        tool_event_emitter: Callable[[dict[str, Any]], None] | None = None,
        tool_call_recorder: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._base = base_tools
        self._stage = stage
        self._state = state
        self._gate_recorder = gate_recorder
        self._tool_event_emitter = tool_event_emitter
        self._tool_call_recorder = tool_call_recorder
        self._allowed = {str(tool).strip() for tool in allowed_tools if str(tool).strip()}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    def _ensure_allowed(self, name: str) -> None:
        if self._allowed and name not in self._allowed:
            allowed = ", ".join(sorted(self._allowed))
            raise PermissionError(f"Tool not allowed for stage={self._stage.value}: {name}. allowed={allowed}")

    def _record_gate(self, gate: dict[str, Any]) -> None:
        if not callable(self._gate_recorder):
            return
        try:
            self._gate_recorder(gate)
        except Exception:
            return

    @staticmethod
    def _tool_payload_digest(payload: dict[str, Any]) -> str:
        try:
            raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")
        except Exception:
            raw = str(payload).encode("utf-8", errors="replace")
        return hashlib.sha256(raw).hexdigest()

    def _record_tool_call(
        self,
        *,
        call_id: str,
        tool: str,
        status: str,
        payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        gate: dict[str, Any] | None = None,
    ) -> None:
        payload = dict(payload or {})
        result = dict(result or {})
        gate = dict(gate or {})
        state = self._state
        record = {
            "schema": "tool_call_record.v1",
            "record_id": make_event_id(),
            "call_id": call_id,
            "run_id": str(getattr(state, "run_id", "")) if state is not None else "",
            "experiment_id": str(getattr(state, "experiment_id", "")) if state is not None else "",
            "loop_id": int(getattr(state, "loop_count", 0) or 0) if state is not None else 0,
            "stage": self._stage.value,
            "tool": tool,
            "status": status,
            "payload_sha256": self._tool_payload_digest(payload) if payload else "",
            "payload_keys": sorted(str(key) for key in payload.keys())[:64],
            "result_ok": result.get("ok") if result else None,
            "result_status": str(result.get("status") or "") if result else "",
            "failure_code": str(result.get("failure_code") or result.get("error_code") or "") if result else "",
            "guardian_gate_id": str(gate.get("gate_id") or ""),
            "guardian_decision": str(gate.get("decision") or ""),
            "guardian_reason_code": str(gate.get("reason_code") or ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if callable(self._tool_call_recorder):
            try:
                self._tool_call_recorder(record)
                return
            except Exception:
                pass
        if state is None:
            return
        metadata = getattr(state, "run_metadata", None)
        if not isinstance(metadata, dict):
            return
        records = metadata.setdefault("tool_call_records", [])
        if not isinstance(records, list):
            records = []
            metadata["tool_call_records"] = records
        records.append(record)
        del records[:-200]

    def _emit_tool_shield_event(self, *, tool: str, gate: dict[str, Any], status: str, detail: str = "") -> None:
        if not callable(self._tool_event_emitter):
            return
        try:
            self._tool_event_emitter(
                {
                    "tool": "guardian.tool_shield",
                    "shielded_tool": tool,
                    "step": str(gate.get("action") or "GUARDIAN_TOOL_SHIELD"),
                    "status": status,
                    "detail": detail or gate.get("reason_code", ""),
                    "stage": self._stage.value,
                    "decision": gate.get("decision", ""),
                    "reason_code": gate.get("reason_code", ""),
                    "risk_score": gate.get("risk_score", 0.0),
                    "guardian_gate": gate,
                    "guardian_decision": gate.get("guardian_decision", {}),
                    "guardian_contract": gate.get("guardian_contract", {}),
                    "requires_human_approval": str(gate.get("decision") or "") == "require_human_approval",
                    "blocks_workflow": str(gate.get("decision") or "") in {"block", "safe_stop", "require_human_approval"},
                }
            )
        except Exception:
            return

    @staticmethod
    def _blocked_tool_result(name: str, gate: dict[str, Any]) -> dict[str, Any]:
        decision = str(gate.get("decision") or "block")
        approval_required = decision == "require_human_approval"
        failure_code = "GUARDIAN_TOOL_APPROVAL_REQUIRED" if approval_required else "GUARDIAN_TOOL_SHIELD_BLOCKED"
        return {
            "ok": False,
            "tool": name,
            "status": "approval_required" if approval_required else "blocked",
            "failure_code": failure_code,
            "message": f"Guardian action shield blocked {name}: {gate.get('reason_code') or decision}",
            "requires_human_approval": approval_required,
            "blocks_workflow": True,
            "guardian_gate": gate,
            "guardian_contract": gate.get("guardian_contract", {}),
            "guardian_decision": gate.get("guardian_decision", {}),
            "incident_records": gate.get("incident_records", []),
            "corrective_actions": gate.get("corrective_actions", []),
            "step_trace": [
                {
                    "step": "GUARDIAN_PRE_TOOL_SHIELD",
                    "status": "approval_required" if approval_required else "blocked",
                    "detail": gate.get("reason_code") or decision,
                }
            ],
        }

    def call(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call only tools declared by the active module config, after Guardian sidecar checks."""
        self._ensure_allowed(name)
        normalized = dict(payload or {})
        call_id = make_event_id().replace("evt-", "tool-call-", 1)
        self._record_tool_call(call_id=call_id, tool=name, status="requested", payload=normalized)
        if not tool_requires_action_shield(name):
            try:
                result = self._base.call(name, normalized)
            except Exception as exc:
                self._record_tool_call(
                    call_id=call_id,
                    tool=name,
                    status="failed",
                    payload=normalized,
                    result={"ok": False, "status": "failed", "failure_code": exc.__class__.__name__},
                )
                raise
            result_payload = result if isinstance(result, dict) else {"ok": False, "status": "failed", "failure_code": "TOOL_RESULT_NON_DICT"}
            result_status = "completed" if result_payload.get("ok", True) is not False and str(result_payload.get("status") or "").lower() not in {"blocked", "failed", "error"} else "failed"
            self._record_tool_call(call_id=call_id, tool=name, status=result_status, payload=normalized, result=result_payload)
            return result

        pre_gate = guardian_gate(
            state=self._state,
            stage=self._stage.value,
            phase="action",
            payload=normalized,
            tool=name,
            action="pre_tool_call",
        )
        self._record_gate(pre_gate)
        decision = str(pre_gate.get("decision") or "allow")
        if decision in {"block", "safe_stop", "require_human_approval"}:
            status = "approval_required" if decision == "require_human_approval" else "blocked"
            self._emit_tool_shield_event(tool=name, gate=pre_gate, status=status)
            blocked = self._blocked_tool_result(name, pre_gate)
            self._record_tool_call(call_id=call_id, tool=name, status=status, payload=normalized, result=blocked, gate=pre_gate)
            return blocked
        if decision == "modify":
            patch = pre_gate.get("modified_payload_patch") if isinstance(pre_gate.get("modified_payload_patch"), dict) else {}
            if patch:
                normalized.update(patch)
            self._emit_tool_shield_event(tool=name, gate=pre_gate, status="modified", detail="guardian_payload_patch")
            self._record_tool_call(
                call_id=call_id,
                tool=name,
                status="modified",
                payload=normalized,
                result={"ok": True, "status": "modified", "guardian_payload_patch": patch},
                gate=pre_gate,
            )
        elif decision == "allow_with_warning":
            self._emit_tool_shield_event(tool=name, gate=pre_gate, status="warning")

        try:
            result = self._base.call(name, normalized)
        except Exception as exc:
            failed = {"ok": False, "status": "failed", "failure_code": exc.__class__.__name__}
            self._record_tool_call(call_id=call_id, tool=name, status="failed", payload=normalized, result=failed, gate=pre_gate)
            raise
        post_payload = result if isinstance(result, dict) else {"ok": False, "status": "failed", "failure_code": "TOOL_RESULT_NON_DICT"}
        post_gate = guardian_gate(
            state=self._state,
            stage=self._stage.value,
            phase="action",
            payload=post_payload,
            tool=name,
            action="post_tool_call",
        )
        self._record_gate(post_gate)
        result_status = "completed" if post_payload.get("ok", True) is not False and str(post_payload.get("status") or "").lower() not in {"blocked", "failed", "error"} else "failed"
        self._record_tool_call(call_id=call_id, tool=name, status=result_status, payload=normalized, result=post_payload, gate=post_gate)
        if str(post_gate.get("decision") or "allow") != "allow":
            self._emit_tool_shield_event(tool=name, gate=post_gate, status=str(post_gate.get("status") or "warning"), detail="post_tool_result")
        return result

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
        *,
        state: OrchestratorState | None = None,
        gate_recorder: Callable[[dict[str, Any]], None] | None = None,
        tool_call_recorder: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._base = base
        self._module = module_config
        self._stage = stage
        self._state = state
        self._gate_recorder = gate_recorder
        self._tool_call_recorder = tool_call_recorder
        self._active_internal_step = dict(active_internal_step or {})
        self._llm = module_config.get("llm") if isinstance(module_config.get("llm"), dict) else {}
        self._prompt = module_config.get("prompt") if isinstance(module_config.get("prompt"), dict) else {}
        self._timeout_s = module_config.get("timeout_s")
        self._task_type = str(module_config.get("llm_role") or "").strip()
        self._allowed_tools = module_config.get("tools") if isinstance(module_config.get("tools"), list) else []
        self.active_backend = str(self._llm.get("backend") or base.active_backend).strip() or base.active_backend
        base_tools = getattr(base, "tools", None)
        if base_tools is not None and self._allowed_tools:
            self.tools = ModuleToolRegistryProxy(
                base_tools,
                self._allowed_tools,
                stage,
                state=state,
                gate_recorder=gate_recorder,
                tool_event_emitter=self._tool_event_dispatcher(),
                tool_call_recorder=tool_call_recorder,
            )

    def _tool_event_dispatcher(self) -> Callable[[dict[str, Any]], None] | None:
        """Return a thread-safe dispatcher for tool events emitted inside worker threads."""
        callback = getattr(self._base, "on_tool_event", None)
        if not callable(callback):
            return None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        def emit(event: dict[str, Any]) -> None:
            event_payload = dict(event)

            def notify() -> None:
                try:
                    result = callback(event_payload)
                    if inspect.isawaitable(result):
                        asyncio.create_task(result)
                except Exception:
                    return

            def close_or_run_without_loop() -> None:
                try:
                    result = callback(event_payload)
                    if inspect.isawaitable(result):
                        close = getattr(result, "close", None)
                        if callable(close):
                            close()
                except Exception:
                    return

            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(notify)
            else:
                close_or_run_without_loop()

        return emit

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

    async def _notify_model_call(
        self,
        task_type: str,
        model: str,
        role: str,
        *,
        backend_name: str | None = None,
    ) -> None:
        """Notify controller hooks with the module-selected backend name."""
        resolved_backend = backend_name or self.active_backend
        callback = getattr(self._base, "on_model_call", None)
        if callback is not None:
            try:
                result = callback(task_type=task_type, model=model, role=role, backend=resolved_backend)
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
        priority: int | None = None,
        owner: str = "",
        lease_wait: bool = True,
    ):
        """Call the module-selected LLM route without changing Python agent code."""
        lease = getattr(self._base, "llm_lease", None)
        if lease is None:
            return await self._complete_unleased(task_type, user_prompt, timeout_s=timeout_s)
        resolved_priority = 0 if task_type.startswith("guardian") else 10
        if priority is not None:
            resolved_priority = int(priority)
        lease_owner = owner or f"module:{self._module.get('id', self._stage.value)}:{task_type}"
        async with lease.acquire(priority=resolved_priority, owner=lease_owner, wait=lease_wait):
            return await self._complete_unleased(task_type, user_prompt, timeout_s=timeout_s)

    async def _complete_unleased(
        self,
        task_type: str,
        user_prompt: str,
        *,
        timeout_s: float | None = None,
    ):
        effective_task = self._task_type or task_type
        effective_timeout = timeout_s
        if effective_timeout is None and isinstance(self._timeout_s, (int, float)) and float(self._timeout_s) > 0:
            effective_timeout = float(self._timeout_s)
        backend_name = self.active_backend
        router = self._base.model_routers.get(backend_name, self._base.model_router)
        primary_backend = self._base.primary_backends.get(backend_name, self._base.primary_backend)
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

        attempts: list[tuple[str, Any, str, str]] = [
            (backend_name, primary_backend, primary_model, selection.role),
        ]
        if fallback_model and fallback_model != primary_model:
            attempts.append(
                (
                    backend_name,
                    primary_backend,
                    fallback_model,
                    f"{selection.role}:model_fallback",
                )
            )

        fallback_backend_name = self._base.backend_fallbacks.get(backend_name, "")
        if fallback_backend_name and fallback_backend_name != backend_name:
            fallback_router = self._base.model_routers.get(fallback_backend_name, router)
            fallback_selection = fallback_router.select(effective_task)
            fallback_backend = self._base.fallback_backends.get(backend_name, self._base.fallback_backend)
            attempts.append(
                (
                    fallback_backend_name,
                    fallback_backend,
                    fallback_selection.primary,
                    f"{fallback_selection.role}:backend_fallback",
                )
            )
            if fallback_selection.fallback and fallback_selection.fallback != fallback_selection.primary:
                attempts.append(
                    (
                        fallback_backend_name,
                        fallback_backend,
                        fallback_selection.fallback,
                        f"{fallback_selection.role}:backend_fallback_model_fallback",
                    )
                )
        else:
            fallback_backend = self._base.fallback_backends.get(backend_name, self._base.fallback_backend)
            if fallback_backend is not primary_backend and fallback_model:
                attempts.append((backend_name, fallback_backend, fallback_model, f"{selection.role}:fallback"))

        errors: list[tuple[str, str, str, Exception]] = []
        seen: set[tuple[int, str, str]] = set()
        for attempt_backend_name, backend, model, role in attempts:
            key = (id(backend), model, role)
            if key in seen:
                continue
            seen.add(key)
            try:
                response = await _call_backend(backend, model, role)
                await self._notify_model_call(
                    task_type=effective_task,
                    model=model,
                    role=role,
                    backend_name=attempt_backend_name,
                )
                return response
            except Exception as exc:
                errors.append((attempt_backend_name, model, role, exc))

        detail = "; ".join(
            f"{attempt_backend}/{role}/{model}: {type(exc).__name__}: {exc}"
            for attempt_backend, model, role, exc in errors[-3:]
        )
        raise RuntimeError(
            f"LLM call failed task={effective_task} active_backend={backend_name} "
            f"fallback_backend={fallback_backend_name or backend_name}: {detail}"
        ) from (errors[-1][3] if errors else None)


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
        return ModuleRuntimeContext(
            self._ctx,
            module,
            stage,
            active_internal_step=active_internal_step,
            state=self._state,
            gate_recorder=self._record_guardian_gate_snapshot,
            tool_call_recorder=self._record_tool_call_snapshot,
        )

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

    def _graph_config_digest(self) -> str:
        """Return a stable digest for the active runtime graph config."""
        payload = json.dumps(self._graph_config.model_dump(mode="json"), ensure_ascii=True, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _pre_run_gate_payload(self) -> dict[str, Any]:
        """Build the graph-wide Guardian pre-run contract payload."""
        metadata = self._graph_config.metadata if isinstance(self._graph_config.metadata, dict) else {}
        safety = metadata.get("safety") if isinstance(metadata.get("safety"), dict) else {}
        mode_support = [str(item) for item in metadata.get("mode_support", [])] if isinstance(metadata.get("mode_support"), list) else []
        runtime_graph = self._state.run_metadata.get("runtime_graph") if isinstance(self._state.run_metadata.get("runtime_graph"), dict) else {}
        module_versions = []
        for stage, module in sorted(self._module_configs.items()):
            if not isinstance(module, dict):
                continue
            module_versions.append(
                {
                    "stage": stage,
                    "module_id": str(module.get("id") or stage),
                    "handler": str(module.get("handler") or ""),
                    "version": str(module.get("version") or module.get("module_version") or ""),
                    "tools": module.get("tools", []) if isinstance(module.get("tools"), list) else [],
                }
            )
        payload: dict[str, Any] = {
            "schema_version": "guardian_pre_run.v1",
            "status": "ok",
            "graph": {
                "graph_id": self._graph_config.id,
                "graph_name": self._graph_config.name,
                "graph_version": self._graph_config.version,
                "graph_hash": runtime_graph.get("graph_hash") or self._graph_config_digest(),
                "runtime_graph": runtime_graph,
            },
            "mode": self._state.mode.value,
            "mode_support": mode_support,
            "safety_policy": safety,
            "module_versions": module_versions,
            "device_heartbeat": dict(self._state.device_health or {}),
            "operator_approval_status": self._state.run_metadata.get("runtime_approvals", {}),
            "required_user_inputs_present": bool(self._state.current_experiment_spec or self._state.current_experiment_objective),
            "risk_budget": self._state.run_metadata.get("safety_budget") or self._state.run_metadata.get("risk_budget") or {},
        }
        warnings: list[str] = []
        blockers: list[str] = []
        if mode_support and self._state.mode.value not in mode_support:
            payload["failure_code"] = "CONTRACT_SCHEMA_INVALID"
            blockers.append(f"mode={self._state.mode.value} is not supported by graph metadata")
        if self._state.mode == Mode.LIVE and bool(safety.get("live_device_dry_run_required_before_execution")):
            if not runtime_graph.get("graph_hash"):
                warnings.append("live dry-run evidence is not attached to runtime_graph metadata")
        if blockers:
            payload["status"] = "blocked"
            payload["blocking_reasons"] = blockers
        if warnings:
            payload["warnings"] = warnings
        return payload

    async def _emit_pre_run_guardian_gate(self) -> dict[str, Any]:
        """Record the graph-wide Guardian pre-run gate before executing any stage."""
        gate = guardian_gate(
            state=self._state,
            stage="runtime",
            phase="pre_run",
            payload=self._pre_run_gate_payload(),
            agent="guardian_agent",
            action="pre_run",
        )
        await self._record_guardian_gate_result(gate)
        return gate

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

    def _append_metadata_record(self, key: str, record: dict[str, Any], *, limit: int = 200) -> None:
        records = self._state.run_metadata.setdefault(key, [])
        if not isinstance(records, list):
            records = []
            self._state.run_metadata[key] = records
        records.append(record)
        del records[:-limit]

    async def _record_orchestrator_followup(
        self,
        *,
        stage: Stage,
        trigger: str,
        payload: dict[str, Any] | None = None,
        next_stage: Stage | None = None,
        guardian_context: dict[str, Any] | None = None,
        level: str = "INFO",
    ) -> dict[str, Any]:
        followup = build_orchestrator_followup(
            state=self._state,
            stage=stage,
            trigger=trigger,
            payload=payload or {},
            next_stage=next_stage,
            guardian_context=guardian_context,
        )
        self._append_metadata_record("orchestrator_followups", followup)
        self._state.run_metadata["latest_orchestrator_followup"] = followup
        await self._emit(
            event_type="orchestrator.followup",
            message=f"Orchestrator follow-up for {stage.value}: {followup.get('recommendation', '')}",
            payload={
                "agent": "orchestrator",
                "node_id": stage.value,
                "module_id": "orchestrator",
                "status": followup.get("status", "ok"),
                "orchestrator_followup": followup,
            },
            level=level,
        )
        return followup

    async def _drain_operator_followups(self, *, stage: Stage, phase: str) -> list[dict[str, Any]]:
        """Consume Live GUI operator follow-ups at safe stage boundaries."""
        queue = self._state.run_metadata.get("operator_followup_queue")
        if not isinstance(queue, list) or not queue:
            return []
        now = datetime.now(timezone.utc).isoformat()
        pending: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        for item in queue:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "queued")
            if status == "queued":
                consumed = dict(item)
                consumed.update(
                    {
                        "status": "consumed",
                        "consumed_at": now,
                        "consumed_stage": stage.value,
                        "consumed_phase": phase,
                    }
                )
                pending.append(consumed)
            else:
                remaining.append(item)
        self._state.run_metadata["operator_followup_queue"] = remaining[-50:]
        if not pending:
            return []

        context = self._state.run_metadata.setdefault("operator_followup_context", [])
        if not isinstance(context, list):
            context = []
            self._state.run_metadata["operator_followup_context"] = context
        history = self._state.run_metadata.setdefault("operator_followups", [])
        if not isinstance(history, list):
            history = []
            self._state.run_metadata["operator_followups"] = history
        for record in pending:
            context.append(compact_runtime_payload(record))
            history.append(record)
            self._state.run_metadata["latest_operator_followup"] = record
            await self._emit(
                event_type="operator.followup_consumed",
                message=f"Operator follow-up consumed at {stage.value} boundary",
                payload={
                    "agent": "orchestrator",
                    "node_id": stage.value,
                    "module_id": "orchestrator",
                    "status": "consumed",
                    "phase": phase,
                    "operator_followup": record,
                    "target_agent_id": record.get("target_agent", ""),
                    "chat_mode": record.get("chat_mode", "ask"),
                },
            )
            await self._record_orchestrator_followup(
                stage=stage,
                trigger="operator_followup",
                payload={"operator_followup": record, "status": "ok", "phase": phase},
                next_stage=stage,
            )
        del context[:-20]
        del history[:-200]
        return pending

    async def _record_orchestrator_transition(
        self,
        *,
        stage: Stage,
        next_stage: Stage,
        result_data: dict[str, Any],
        selected_transition: dict[str, Any],
        transition_candidates: list[dict[str, Any]],
        guardian_context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        evidence_refs: list[str] = []
        if isinstance(result_data.get("handoff_packet"), dict):
            refs = result_data["handoff_packet"].get("evidence_refs")
            if isinstance(refs, list):
                evidence_refs = [str(item) for item in refs if str(item or "").strip()]
        decision = build_decision_record(
            state=self._state,
            stage=stage,
            decision="route_next_stage",
            selected=next_stage.value,
            alternatives=[str(item.get("to_stage")) for item in transition_candidates if isinstance(item, dict)],
            reason=f"Graph transition selected after {stage.value} result and Guardian post-gate review.",
            authority="orchestrator",
            evidence_refs=evidence_refs,
        )
        handoff = build_orchestrator_handoff_packet(
            state=self._state,
            from_stage=stage,
            to_stage=next_stage,
            result_payload=result_data,
            selected_transition=selected_transition,
            guardian_context=guardian_context,
        )
        self._append_metadata_record("orchestrator_decision_register", decision)
        self._append_metadata_record("orchestrator_handoff_packets", handoff)
        self._state.run_metadata["latest_orchestrator_decision"] = decision
        self._state.run_metadata["latest_orchestrator_handoff"] = handoff
        mission_contract = build_mission_contract(state=self._state)
        orchestration_plan = build_orchestration_plan(state=self._state, graph_id=self._graph_config.id)
        self._state.run_metadata["mission_contract"] = mission_contract
        self._state.run_metadata["latest_mission_contract"] = mission_contract
        self._append_metadata_record("orchestration_plans", orchestration_plan, limit=20)
        self._state.run_metadata["latest_orchestration_plan"] = orchestration_plan
        await self._record_orchestrator_parallel_checks(plan=orchestration_plan, stage=stage)
        self._state.run_metadata["latest_orchestrator_control_plane"] = compact_runtime_payload(
            build_orchestrator_control_plane_snapshot(
                state=self._state,
                mission_contract=mission_contract,
                orchestration_plan=orchestration_plan,
                next_action=f"Route {stage.value} to {next_stage.value}.",
            )
        )
        await self._emit(
            event_type="orchestrator.decision",
            message=f"Orchestrator selected route {stage.value} -> {next_stage.value}",
            payload={
                "agent": "orchestrator",
                "node_id": stage.value,
                "module_id": "orchestrator",
                "status": "ok",
                "decision": decision,
                "handoff_packet": handoff,
            },
        )
        return decision, handoff

    async def _record_orchestrator_loop_reflection(
        self,
        *,
        guardian_payload: dict[str, Any] | None = None,
        next_stage: Stage | None = None,
    ) -> dict[str, Any]:
        reflection = build_loop_reflection(
            state=self._state,
            guardian_payload=guardian_payload,
            next_stage=next_stage,
        )
        self._append_metadata_record("loop_reflections", reflection)
        self._state.run_metadata["latest_loop_reflection"] = reflection
        await self._emit(
            event_type="orchestrator.loop_reflection",
            message=str(reflection.get("operator_visible_summary") or "Orchestrator loop reflection recorded."),
            payload={
                "agent": "orchestrator",
                "node_id": Stage.GUARDIAN.value,
                "module_id": "orchestrator",
                "status": "ok",
                "loop_reflection": reflection,
            },
        )
        return reflection

    async def _record_orchestrator_parallel_checks(
        self,
        *,
        plan: dict[str, Any],
        stage: Stage,
    ) -> dict[str, Any]:
        check_names = plan.get("parallelizable_checks") if isinstance(plan.get("parallelizable_checks"), list) else []
        if not check_names:
            return {}
        tasks = [
            asyncio.to_thread(
                build_orchestrator_parallel_check,
                state=self._state,
                check_id=str(check_name),
                plan_id=str(plan.get("plan_id") or ""),
            )
            for check_name in check_names
        ]
        checks = await asyncio.gather(*tasks)
        batch = build_orchestrator_parallel_check_batch(state=self._state, plan=plan, checks=list(checks), stage=stage)
        self._append_metadata_record("orchestrator_parallel_checks", batch, limit=100)
        self._state.run_metadata["latest_orchestrator_parallel_checks"] = batch
        await self._emit(
            event_type="orchestrator.parallel_checks",
            message=f"Orchestrator executed {batch.get('check_count', 0)} read-only parallel planning checks for {stage.value}.",
            payload={
                "agent": "orchestrator",
                "node_id": stage.value,
                "module_id": "orchestrator",
                "status": batch.get("status", "ok"),
                "parallel_checks": batch,
            },
            level="WARNING" if batch.get("status") in {"warning", "blocked"} else "INFO",
        )
        return batch

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
        compact_data = compact_runtime_payload(data) if isinstance(data, dict) else data
        if isinstance(data, dict):
            self._state.run_metadata[f"{stage.value}_agent_payload"] = compact_data
            if isinstance(data.get("design_report"), dict):
                self._state.run_metadata["design_report"] = compact_runtime_payload(data["design_report"])
            if isinstance(data.get("design_agent_report"), dict):
                self._state.run_metadata["latest_design_agent_report"] = compact_runtime_payload(data["design_agent_report"])
            if isinstance(data.get("design_candidate"), dict):
                self._state.run_metadata["design_candidate"] = compact_runtime_payload(data["design_candidate"])
            if isinstance(data.get("handoff_packet"), dict):
                self._state.run_metadata[f"{stage.value}_handoff_packet"] = compact_runtime_payload(data["handoff_packet"])
                packets = self._state.run_metadata.get("handoff_packets")
                if not isinstance(packets, list):
                    packets = []
                packets.append({"stage": stage.value, "packet": compact_runtime_payload(data["handoff_packet"])})
                self._state.run_metadata["handoff_packets"] = packets[-20:]
            if isinstance(data.get("decisions"), list):
                self._state.run_metadata[f"{stage.value}_decision_register"] = compact_runtime_payload(data["decisions"])
            if isinstance(data.get("metrics"), dict):
                self._state.run_metadata[f"{stage.value}_metrics"] = compact_runtime_payload(data["metrics"])
            if isinstance(data.get("mission_contract"), dict):
                self._state.run_metadata["mission_contract"] = compact_runtime_payload(data["mission_contract"])
                self._state.run_metadata["latest_mission_contract"] = compact_runtime_payload(data["mission_contract"])
            if isinstance(data.get("orchestration_plan"), dict):
                plans = self._state.run_metadata.get("orchestration_plans")
                if not isinstance(plans, list):
                    plans = []
                plans.append(compact_runtime_payload(data["orchestration_plan"]))
                self._state.run_metadata["orchestration_plans"] = plans[-20:]
                self._state.run_metadata["latest_orchestration_plan"] = compact_runtime_payload(data["orchestration_plan"])
            if isinstance(data.get("orchestrator_control_plane"), dict):
                self._state.run_metadata["latest_orchestrator_control_plane"] = compact_runtime_payload(data["orchestrator_control_plane"])
            if isinstance(data.get("fabrication_report"), dict):
                self._state.run_metadata["fabrication_report"] = compact_runtime_payload(data["fabrication_report"])
                self._state.run_metadata[f"{stage.value}_fabrication_report"] = compact_runtime_payload(data["fabrication_report"])
            if isinstance(data.get("specimen_agent_report"), dict):
                self._state.run_metadata["latest_specimen_agent_report"] = compact_runtime_payload(data["specimen_agent_report"])
            if isinstance(data.get("specimen_fabricated"), dict):
                self._state.run_metadata["specimen_fabricated"] = compact_runtime_payload(data["specimen_fabricated"])
            if isinstance(data.get("vision_report"), dict):
                self._state.run_metadata["vision_report"] = compact_runtime_payload(data["vision_report"])
                self._state.run_metadata[f"{stage.value}_vision_report"] = compact_runtime_payload(data["vision_report"])
            if isinstance(data.get("vision_agent_report"), dict):
                self._state.run_metadata["latest_vision_agent_report"] = compact_runtime_payload(data["vision_agent_report"])
            if isinstance(data.get("vision_signal"), dict):
                self._state.run_metadata["vision_signal"] = compact_runtime_payload(data["vision_signal"])
            if isinstance(data.get("vision_operator_intervention"), dict):
                self._state.run_metadata["vision_operator_intervention"] = compact_runtime_payload(
                    data["vision_operator_intervention"]
                )
            if isinstance(data.get("active_cam_artifact_update"), dict):
                apply_active_cam_artifact_update(
                    self._state.run_metadata,
                    compact_runtime_payload(data["active_cam_artifact_update"]),
                )
            if isinstance(data.get("utm_completion_artifact_update"), dict):
                apply_utm_completion_artifact_update(
                    self._state.run_metadata,
                    compact_runtime_payload(data["utm_completion_artifact_update"]),
                )
            if isinstance(data.get("manipulation_report"), dict):
                self._state.run_metadata["manipulation_report"] = compact_runtime_payload(data["manipulation_report"])
                self._state.run_metadata[f"{stage.value}_manipulation_report"] = compact_runtime_payload(data["manipulation_report"])
            if isinstance(data.get("manipulation_agent_report"), dict):
                self._state.run_metadata["latest_manipulation_agent_report"] = compact_runtime_payload(data["manipulation_agent_report"])
            if isinstance(data.get("robot_task_result"), dict):
                self._state.run_metadata["robot_task_result"] = compact_runtime_payload(data["robot_task_result"])
                self._state.run_metadata[f"{stage.value}_robot_task_result"] = compact_runtime_payload(data["robot_task_result"])

        if "experiment_spec" in data:
            self._state.current_experiment_spec = compact_runtime_payload(data["experiment_spec"])
        if "experiment_objective" in data:
            self._state.current_experiment_objective = compact_runtime_payload(data["experiment_objective"])
        if "experiment_evaluation" in data and isinstance(data["experiment_evaluation"], dict):
            self._state.experiment_evaluations.append(compact_runtime_payload(data["experiment_evaluation"]))
        specimen_result = data.get("specimen_result") if isinstance(data.get("specimen_result"), dict) else {}
        if specimen_result:
            self._state.run_metadata["specimen_result"] = compact_runtime_payload(specimen_result)
        if isinstance(specimen_result.get("experiment_evaluation"), dict):
            self._state.experiment_evaluations.append(compact_runtime_payload(specimen_result["experiment_evaluation"]))
        if "observation" in data:
            self._state.latest_observations = compact_runtime_payload(data["observation"])
            if isinstance(data["observation"], dict):
                self._state.run_metadata["latest_vision_observation"] = compact_runtime_payload(data["observation"])
                self._merge_vision_completion_into_specimen_result(data["observation"], data)
        if "analysis" in data:
            analysis_payload = compact_runtime_payload(data["analysis"])
            if isinstance(analysis_payload, dict):
                self._state.latest_analysis.update(analysis_payload)
        if "sarm" in data:
            self._state.latest_analysis["sarm"] = compact_runtime_payload(data["sarm"])
        if "manipulation" in data:
            self._state.run_metadata["manipulation_result"] = compact_runtime_payload(data["manipulation"])
            self._state.latest_analysis["last_grasp_score"] = float(data["manipulation"].get("grasp_score", 0.0))
            if "sarm" in data:
                self._state.latest_analysis["sarm"] = compact_runtime_payload(data["sarm"])
        if "equipment_result" in data:
            equipment_result = data["equipment_result"] if isinstance(data["equipment_result"], dict) else {}
            self._state.run_metadata["equipment_result"] = compact_runtime_payload(equipment_result)
            if isinstance(data.get("equipment_report"), dict):
                self._state.run_metadata["equipment_report"] = compact_runtime_payload(data["equipment_report"])
            if isinstance(data.get("utm_data_ready"), dict):
                self._state.run_metadata["utm_data_ready"] = compact_runtime_payload(data["utm_data_ready"])
            if "equipment_handoff" in data:
                self._state.run_metadata["equipment_handoff"] = compact_runtime_payload(data["equipment_handoff"])
            self._state.latest_analysis["equipment_ok"] = bool(equipment_result.get("ok", False))
            self._state.latest_analysis["equipment_status"] = str(equipment_result.get("status") or "")
            self._state.latest_analysis["equipment_program_id"] = str(equipment_result.get("program_id") or "")
            result_file = equipment_result.get("result_file") or equipment_result.get("utm_csv_path")
            if result_file:
                self._state.latest_analysis["equipment_result_file"] = str(result_file)
            failure_code = equipment_result.get("failure_code")
            if failure_code:
                self._state.latest_analysis["equipment_failure_code"] = str(failure_code)
        hardware_alerts_raw = data.get("hardware_alerts") if isinstance(data.get("hardware_alerts"), list) else []
        hardware_alert_single = data.get("hardware_alert") if isinstance(data.get("hardware_alert"), dict) else None
        hardware_alerts = [dict(item) for item in hardware_alerts_raw if isinstance(item, dict)]
        if hardware_alert_single:
            hardware_alerts.append(dict(hardware_alert_single))
        incident_records_raw = data.get("incident_records") if isinstance(data.get("incident_records"), list) else []
        incident_records = [dict(item) for item in incident_records_raw if isinstance(item, dict)]
        if hardware_alerts:
            stored_alerts = self._state.run_metadata.setdefault("hardware_alerts", [])
            if not isinstance(stored_alerts, list):
                stored_alerts = []
                self._state.run_metadata["hardware_alerts"] = stored_alerts
            seen_alert_ids = {str(item.get("alert_id")) for item in stored_alerts if isinstance(item, dict)}
            for alert in hardware_alerts:
                alert_id = str(alert.get("alert_id") or "")
                if alert_id and alert_id in seen_alert_ids:
                    incident = alert.get("incident_record")
                    if isinstance(incident, dict):
                        incident_records.append(dict(incident))
                    continue
                stored_alerts.append(alert)
                guardian_decision = alert.get("guardian_decision")
                if isinstance(guardian_decision, dict):
                    self._state.run_metadata["latest_guardian_decision"] = guardian_decision
                incident = alert.get("incident_record")
                if isinstance(incident, dict):
                    incident_records.append(dict(incident))
                device_class = str(alert.get("device_class") or "hardware")
                failure = str(alert.get("failure_code") or alert.get("status") or "alert")
                severity = str(alert.get("severity") or "warning")
                self._state.device_health[device_class] = f"{severity}:{failure}"
            del stored_alerts[:-50]
        if incident_records:
            self._record_incident_records(incident_records)
        if "knowledge" in data:
            self._state.run_metadata["knowledge"] = compact_runtime_payload(data["knowledge"])
        if "bo_result" in data:
            self._state.run_metadata["bo_agent"] = compact_runtime_payload(data["bo_result"])
            visualization = self._bo_visualization_from_result(data)
            if visualization:
                compact_visualization = compact_runtime_payload(visualization)
                self._state.run_metadata["bo_visualization"] = compact_visualization
                steps = self._state.run_metadata.get("bo_visualization_steps")
                if not isinstance(steps, list):
                    steps = []
                step_summary = {
                    "run_id": str(visualization.get("run_id") or self._state.run_id),
                    "step": int(visualization.get("step") or 0),
                    "selected_parameter": str((visualization.get("view") or {}).get("selected_parameter") or ""),
                    "generated_at": str(visualization.get("generated_at") or ""),
                }
                if not steps or steps[-1] != step_summary:
                    steps.append(step_summary)
                self._state.run_metadata["bo_visualization_steps"] = steps[-80:]
        if "experiment_spec_update" in data and isinstance(data["experiment_spec_update"], dict):
            self._state.run_metadata["bo_recommended_constraints"] = dict(data["experiment_spec_update"])
        if "guardian" in data:
            self._state.run_metadata["guardian"] = compact_runtime_payload(data["guardian"])
        self._state.run_metadata["last_stage_payload"] = {"stage": stage.value, "data": compact_data}

    async def _pause_for_vision_intervention(
        self,
        *,
        stage: Stage,
        agent_name: str,
        status: AgentRuntimeStatus,
        result_data: dict[str, Any],
    ) -> bool:
        if stage != Stage.VISION:
            return False
        intervention = result_data.get("vision_operator_intervention")
        if not isinstance(intervention, dict):
            return False
        if (
            intervention.get("schema") != "vision_operator_intervention.v1"
            or intervention.get("reason") != "specimen_not_detected"
            or intervention.get("status") != "waiting_for_specimen"
        ):
            return False
        stored = compact_runtime_payload(intervention)
        self._state.run_metadata["vision_operator_intervention"] = stored
        self._state.stage = Stage.VISION
        self._state.is_paused = True
        status.state = "waiting"
        status.last_result = "specimen_not_detected"
        status.success = None
        await self._emit(
            event_type="operator_input_required",
            message="Vision is waiting for the specimen to be placed in the working area.",
            payload={
                "agent": agent_name,
                "node_id": stage.value,
                "status": "waiting",
                "checkpoint": intervention.get("checkpoint"),
                "vision_operator_intervention": stored,
                "pending_operator_input": True,
                "requires_response": True,
            },
            level="WARNING",
        )
        return True

    def _merge_vision_completion_into_specimen_result(
        self,
        observation: dict[str, Any],
        data: dict[str, Any] | None = None,
    ) -> None:
        """Attach active-cam Vision verification back to the specimen completion record."""
        if not isinstance(observation, dict):
            return
        # The post-manipulation Vision pass owns only the UTM placement gate.
        # It must not replace the earlier active-camera confirmation that closes
        # the Specimen Making Agent's ejection task.
        decision = str((data or {}).get("transition_decision") or "")
        if decision in {"vision_utm_monitoring", "vision_equipment_handoff"}:
            return
        confirmation = observation.get("spc_autoejection_confirmation")
        active_check = observation.get("active_cam_ejection_check")
        if not isinstance(confirmation, dict) and not isinstance(active_check, dict):
            return
        specimen = self._state.run_metadata.get("specimen_result")
        if not isinstance(specimen, dict):
            return
        updated = dict(specimen)
        confirmed_now = bool(
            (isinstance(confirmation, dict) and confirmation.get("confirmed"))
            or (isinstance(active_check, dict) and active_check.get("spc_autoejection_confirmed"))
        )
        # Every new active-camera result is authoritative for the SPC card and
        # completion gate.  Keeping an old success makes later failures stale.
        confirmed = confirmed_now
        if isinstance(confirmation, dict):
            updated["vision_completion_signal"] = compact_runtime_payload(dict(confirmation))
        if isinstance(active_check, dict):
            updated["active_cam_ejection_check"] = compact_runtime_payload(dict(active_check))
        signal = data.get("vision_signal") if isinstance(data, dict) and isinstance(data.get("vision_signal"), dict) else {}
        updated["vision_verification"] = {
            "schema": "specimen_completion_vision_verification.v1",
            "status": "confirmed" if confirmed else "observed",
            "confirmed": confirmed,
            "source_agent": "vision_agent",
            "consumer_agent": "specimen_agent",
            "vision_signal": compact_runtime_payload(dict(signal)) if isinstance(signal, dict) else {},
        }
        updated["autoejection_completion_verified"] = confirmed
        fabrication = dict(updated.get("fabrication_report")) if isinstance(updated.get("fabrication_report"), dict) else {}
        if fabrication:
            outcome = dict(fabrication.get("fabrication_outcome")) if isinstance(fabrication.get("fabrication_outcome"), dict) else {}
            outcome.update({
                "autoejection_status": "complete" if confirmed else "awaiting_vision_confirmation",
                "vision_confirmation_status": "confirmed" if confirmed else "not_confirmed",
            })
            fabrication["fabrication_outcome"] = outcome
            updated["fabrication_report"] = fabrication
            self._state.run_metadata["fabrication_report"] = compact_runtime_payload(fabrication)
            self._state.run_metadata["specimen_fabrication_report"] = compact_runtime_payload(fabrication)
        fabricated = dict(updated.get("specimen_fabricated")) if isinstance(updated.get("specimen_fabricated"), dict) else {}
        if fabricated:
            summary = dict(fabricated.get("fabrication_summary")) if isinstance(fabricated.get("fabrication_summary"), dict) else {}
            summary.update({
                "autoejection_status": "complete" if confirmed else "awaiting_vision_confirmation",
                "vision_confirmation_status": "confirmed" if confirmed else "not_confirmed",
            })
            fabricated["fabrication_summary"] = summary
            updated["specimen_fabricated"] = fabricated
            self._state.run_metadata["specimen_fabricated"] = compact_runtime_payload(fabricated)
        agent_report = dict(updated.get("specimen_agent_report")) if isinstance(updated.get("specimen_agent_report"), dict) else {}
        if agent_report:
            gate = dict(agent_report.get("autoejection_gate")) if isinstance(agent_report.get("autoejection_gate"), dict) else {}
            gate.update({"status": "complete" if confirmed else "waiting", "vision_confirmed": confirmed})
            agent_report["autoejection_gate"] = gate
            updated["specimen_agent_report"] = agent_report
            compact_agent_report = compact_runtime_payload(agent_report)
            self._state.run_metadata["specimen_agent_report"] = compact_agent_report
            self._state.run_metadata["latest_specimen_agent_report"] = compact_agent_report
        self._state.run_metadata["specimen_result"] = compact_runtime_payload(updated)

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

    def _append_guardian_event(self, event: dict[str, Any]) -> None:
        """Persist Guardian-readable incident evidence for replay and report recovery."""
        try:
            path = self._run_dir() / "guardian_events.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True, default=str) + "\n")
        except Exception:
            return

    def _record_incident_records(self, records: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> None:
        stored = self._state.run_metadata.setdefault("incident_records", [])
        if not isinstance(stored, list):
            stored = []
            self._state.run_metadata["incident_records"] = stored
        seen = {str(item.get("incident_id") or item.get("id") or "") for item in stored if isinstance(item, dict)}
        for record in records:
            if not isinstance(record, dict):
                continue
            copied = dict(record)
            incident_id = str(copied.get("incident_id") or copied.get("id") or "")
            if incident_id and incident_id in seen:
                continue
            stored.append(copied)
            if incident_id:
                seen.add(incident_id)
            self._append_guardian_event(copied)
        del stored[:-100]

    @staticmethod
    def _guardian_gate_event_level(gate: dict[str, Any]) -> str:
        decision = str(gate.get("decision") or "")
        if decision in {"block", "safe_stop"}:
            return "ERROR"
        if decision in {"allow_with_warning", "require_human_approval"}:
            return "WARNING"
        return "INFO"

    def _queue_guardian_approval(self, gate: dict[str, Any]) -> dict[str, Any] | None:
        """Persist an approval interrupt record for Guardian decisions needing an operator."""
        if str(gate.get("decision") or "") != "require_human_approval":
            return None
        approvals = self._state.run_metadata.setdefault("runtime_approvals", {})
        if not isinstance(approvals, dict):
            approvals = {}
            self._state.run_metadata["runtime_approvals"] = approvals
        gate_id = str(gate.get("gate_id") or make_event_id())
        gate_key = f"guardian:{gate.get('stage', self._state.stage.value)}:{gate.get('phase', '')}:{gate.get('tool') or gate.get('agent') or 'runtime'}:{gate_id}"
        existing = approvals.get(gate_key) if isinstance(approvals.get(gate_key), dict) else None
        if existing:
            return existing
        approval_id = gate_id.replace("guardian-gate-", "approval-", 1) if gate_id.startswith("guardian-gate-") else make_event_id().replace("evt-", "approval-", 1)
        record = {
            "approval_id": approval_id,
            "gate_key": gate_key,
            "source": "guardian_gate",
            "stage": gate.get("stage", self._state.stage.value),
            "phase": gate.get("phase", ""),
            "tool": gate.get("tool", ""),
            "agent": gate.get("agent", "guardian_agent"),
            "action": gate.get("action", ""),
            "status": "pending",
            "title": f"Guardian approval required: {gate.get('tool') or gate.get('stage')}",
            "reason": gate.get("reason_code", "HUMAN_APPROVAL_REQUIRED"),
            "risk_score": gate.get("risk_score", 0.0),
            "guardian_gate_id": gate_id,
            "guardian_gate": gate,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        approvals[gate_key] = record
        queue = self._state.run_metadata.setdefault("guardian_approval_queue", [])
        if not isinstance(queue, list):
            queue = []
            self._state.run_metadata["guardian_approval_queue"] = queue
        queue.append(record)
        del queue[:-100]
        return record

    def _record_tool_call_snapshot(self, record: dict[str, Any]) -> None:
        """Persist a Guardian-readable tool call request/result record."""
        if not isinstance(record, dict):
            return
        copied = dict(record)
        records = self._state.run_metadata.setdefault("tool_call_records", [])
        if not isinstance(records, list):
            records = []
            self._state.run_metadata["tool_call_records"] = records
        records.append(copied)
        del records[:-200]
        self._append_guardian_event(copied)

    def _record_guardian_gate_snapshot(self, gate: dict[str, Any]) -> None:
        """Persist a Guardian gate from synchronous tool-call sidecars."""
        gates = self._state.run_metadata.setdefault("guardian_gates", [])
        if not isinstance(gates, list):
            gates = []
            self._state.run_metadata["guardian_gates"] = gates
        gates.append(gate)
        del gates[:-200]
        self._state.run_metadata["latest_guardian_gate"] = gate
        decision = gate.get("guardian_decision")
        if isinstance(decision, dict):
            self._state.run_metadata["latest_guardian_gate_decision"] = decision
        contract = gate.get("guardian_contract")
        if isinstance(contract, dict):
            contracts = self._state.run_metadata.setdefault("guardian_contracts", [])
            if not isinstance(contracts, list):
                contracts = []
                self._state.run_metadata["guardian_contracts"] = contracts
            contracts.append(contract)
            del contracts[:-200]
        corrective_actions = gate.get("corrective_actions") if isinstance(gate.get("corrective_actions"), list) else []
        if corrective_actions:
            stored_actions = self._state.run_metadata.setdefault("corrective_actions", [])
            if not isinstance(stored_actions, list):
                stored_actions = []
                self._state.run_metadata["corrective_actions"] = stored_actions
            stored_actions.extend(item for item in corrective_actions if isinstance(item, dict))
            del stored_actions[:-200]
        incidents = gate.get("incident_records") if isinstance(gate.get("incident_records"), list) else []
        incident_records = [item for item in incidents if isinstance(item, dict)]
        if incident_records:
            self._record_incident_records(incident_records)
        self._queue_guardian_approval(gate)

    async def _record_guardian_gate_result(self, gate: dict[str, Any]) -> None:
        """Persist and emit one Guardian graph-wide gate decision."""
        gates = self._state.run_metadata.setdefault("guardian_gates", [])
        if not isinstance(gates, list):
            gates = []
            self._state.run_metadata["guardian_gates"] = gates
        gates.append(gate)
        del gates[:-200]
        self._state.run_metadata["latest_guardian_gate"] = gate
        decision = gate.get("guardian_decision")
        if isinstance(decision, dict):
            self._state.run_metadata["latest_guardian_gate_decision"] = decision
        contract = gate.get("guardian_contract")
        if isinstance(contract, dict):
            contracts = self._state.run_metadata.setdefault("guardian_contracts", [])
            if not isinstance(contracts, list):
                contracts = []
                self._state.run_metadata["guardian_contracts"] = contracts
            contracts.append(contract)
            del contracts[:-200]
        corrective_actions = gate.get("corrective_actions") if isinstance(gate.get("corrective_actions"), list) else []
        if corrective_actions:
            stored_actions = self._state.run_metadata.setdefault("corrective_actions", [])
            if not isinstance(stored_actions, list):
                stored_actions = []
                self._state.run_metadata["corrective_actions"] = stored_actions
            stored_actions.extend(item for item in corrective_actions if isinstance(item, dict))
            del stored_actions[:-200]
        incidents = gate.get("incident_records") if isinstance(gate.get("incident_records"), list) else []
        incident_records = [item for item in incidents if isinstance(item, dict)]
        if incident_records:
            self._record_incident_records(incident_records)
        approval_record = self._queue_guardian_approval(gate)

        level = self._guardian_gate_event_level(gate)
        await self._emit(
            event_type="guardian.gate",
            message=f"Guardian {gate.get('phase', 'gate')} gate {gate.get('decision', 'allow')} for stage={gate.get('stage', '')}",
            payload={
                "agent": "guardian_agent",
                "node_id": str(gate.get("stage") or self._state.stage.value),
                "module_id": "guardian",
                "status": gate.get("status", ""),
                "guardian_gate": gate,
                "guardian_decision": decision if isinstance(decision, dict) else {},
                "guardian_contract": contract if isinstance(contract, dict) else {},
                "incident_count": len(incident_records),
                "approval_request": approval_record if isinstance(approval_record, dict) else {},
                "risk_score": gate.get("risk_score", 0.0),
                "reason_code": gate.get("reason_code", ""),
            },
            level=level,
        )
        for incident in incident_records:
            await self._emit(
                event_type="incident.recorded",
                message=f"Guardian incident recorded: {incident.get('summary') or incident.get('failure_code') or incident.get('incident_id')}",
                payload={
                    "agent": "guardian_agent",
                    "node_id": str(incident.get("stage") or gate.get("stage") or self._state.stage.value),
                    "module_id": "guardian",
                    "status": incident.get("status", "open"),
                    "incident_record": incident,
                    "guardian_gate_id": gate.get("gate_id", ""),
                },
                level=level,
            )

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
        if stage not in {Stage.BO, Stage.ANALYSIS, Stage.VISION}:
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
            "frame_path",
            "annotated_frame_path",
            "before_after_path",
            "detection_json_path",
            "mask_path",
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

    @staticmethod
    def _bo_visualization_from_result(result: dict[str, Any]) -> dict[str, Any]:
        """Extract the latest shared BO visualization from closed-loop result shapes."""
        direct = result.get("visualization")
        if isinstance(direct, dict):
            return direct
        bo_result = result.get("bo_result") if isinstance(result.get("bo_result"), dict) else {}
        if isinstance(bo_result.get("visualization"), dict):
            return bo_result["visualization"]
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        bo_result = data.get("bo_result") if isinstance(data.get("bo_result"), dict) else {}
        if isinstance(bo_result.get("visualization"), dict):
            return bo_result["visualization"]
        strategies = LangGraphRunLoop._bo_strategies_from_result(result)
        bo_payload = strategies.get("bo") if isinstance(strategies.get("bo"), dict) else {}
        trace = bo_payload.get("surrogate_trace") if isinstance(bo_payload.get("surrogate_trace"), list) else []
        for item in reversed(trace):
            if isinstance(item, dict) and isinstance(item.get("visualization"), dict):
                return item["visualization"]
        return {}

    def _write_bo_visualization_artifacts(self, stage: Stage, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Publish the shared BO projection under the active closed-loop run."""
        visualization = self._bo_visualization_from_result(data)
        if not visualization:
            return []
        try:
            records = write_bo_visualization_artifacts(visualization, self._runtime_artifact_dir(stage))
            return [
                {
                    **record,
                    "key": f"runtime.bo_posterior.{Path(str(record['path'])).suffix.lstrip('.')}",
                    "path": self._runtime_artifact_relpath(Path(str(record["path"]))),
                    "stage": stage.value,
                }
                for record in records
            ]
        except Exception as exc:
            return [
                {
                    "key": "runtime.bo_posterior.warning",
                    "path": "",
                    "name": "",
                    "source": "bo_visualization.v1",
                    "stage": stage.value,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
            ]

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
            visualization_records = self._write_bo_visualization_artifacts(stage, data)
            if visualization_records:
                records.extend(visualization_records)
                visualization = self._bo_visualization_from_result(data)
                if visualization:
                    artifact_urls = visualization.setdefault("artifacts", {})
                    if isinstance(artifact_urls, dict):
                        encoded_run_id = quote(str(self._state.run_id), safe="")
                        for record in visualization_records:
                            path = str(record.get("path") or "")
                            suffix = Path(path).suffix.lower().lstrip(".")
                            if path and suffix in {"png", "svg", "csv"}:
                                encoded_path = quote(path, safe="/")
                                artifact_urls[f"{suffix}_path"] = path
                                artifact_urls[f"{suffix}_url"] = (
                                    f"/api/runs/{encoded_run_id}/artifact-file/{encoded_path}"
                                )
            else:
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

    async def _emit_artifact_events(
        self,
        stage: Stage,
        agent_name: str,
        data: dict[str, Any],
        *,
        registered_artifacts: list[dict[str, Any]] | None = None,
    ) -> None:
        """Emit artifact.created aliases without changing agent result payload shape."""
        artifacts = (
            registered_artifacts
            if registered_artifacts is not None
            else self._register_runtime_artifacts(stage, agent_name, data)
        )
        for artifact in artifacts:
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
                        "result_keys": self._public_result_keys(result_data),
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


    @staticmethod
    def _public_result_keys(result_data: dict[str, Any]) -> list[str]:
        """Return user-facing result keys without Guardian sidecar metadata."""
        hidden = {"guardian_gate", "guardian_contract", "guardian_decision", "corrective_actions", "incident_records"}
        return sorted(key for key in result_data.keys() if key not in hidden)

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
                "result_keys": self._public_result_keys(result_data),
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
            if isinstance(result.data, dict):
                followup = result.data.get("orchestrator_followup")
                if isinstance(followup, dict):
                    self._append_metadata_record("orchestrator_followups", followup)
                    self._state.run_metadata["latest_orchestrator_followup"] = followup
                decisions = result.data.get("decisions")
                if isinstance(decisions, list):
                    for decision in decisions:
                        if isinstance(decision, dict) and decision.get("schema") == "decision_register.v1":
                            self._append_metadata_record("orchestrator_decision_register", decision)
                            self._state.run_metadata["latest_orchestrator_decision"] = decision
                mission_contract = result.data.get("mission_contract")
                if isinstance(mission_contract, dict):
                    self._state.run_metadata["mission_contract"] = mission_contract
                    self._state.run_metadata["latest_mission_contract"] = mission_contract
                orchestration_plan = result.data.get("orchestration_plan")
                if isinstance(orchestration_plan, dict):
                    self._append_metadata_record("orchestration_plans", orchestration_plan, limit=20)
                    self._state.run_metadata["latest_orchestration_plan"] = orchestration_plan
                    await self._record_orchestrator_parallel_checks(plan=orchestration_plan, stage=stage)
                control_plane = result.data.get("orchestrator_control_plane")
                if isinstance(control_plane, dict):
                    self._state.run_metadata["latest_orchestrator_control_plane"] = compact_runtime_payload(control_plane)
                elif isinstance(mission_contract, dict) and isinstance(orchestration_plan, dict):
                    self._state.run_metadata["latest_orchestrator_control_plane"] = compact_runtime_payload(
                        build_orchestrator_control_plane_snapshot(
                            state=self._state,
                            mission_contract=mission_contract,
                            orchestration_plan=orchestration_plan,
                            next_action=str(result.data.get("plan_text") or ""),
                        )
                    )
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
            pre_step_gate = guardian_gate(
                state=self._state,
                stage=stage.value,
                phase="action",
                payload=completed_payload,
                agent=agent_name,
                tool=handler,
                action=str(step.get("id") or "pre_execution"),
            )
            completed_payload["guardian_gate"] = pre_step_gate
            completed_payload["guardian_contract"] = pre_step_gate.get("guardian_contract", {})
            await self._record_guardian_gate_result(pre_step_gate)
            if gate_blocks_execution(pre_step_gate):
                raise RuntimeError(str(pre_step_gate.get("reason_code") or "guardian_pre_step_gate_blocked"))
            await self._emit(
                event_type="module_pre_step_completed",
                message=f"{agent_name}: pre-execution step {step.get('id')} completed",
                payload=completed_payload,
            )
            if isinstance(result.data, dict) and isinstance(result.data.get("orchestrator_followup"), dict):
                await self._emit(
                    event_type="orchestrator.followup",
                    message=f"Orchestrator pre-stage follow-up for {stage.value}",
                    payload={
                        "agent": "orchestrator",
                        "node_id": stage.value,
                        "module_id": "orchestrator",
                        "status": result.data["orchestrator_followup"].get("status", "ok"),
                        "orchestrator_followup": result.data["orchestrator_followup"],
                    },
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
        await self._drain_operator_followups(stage=stage, phase="pre_stage")
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
        pre_gate = guardian_gate(
            state=self._state,
            stage=stage.value,
            phase="pre",
            payload={"module_runtime": module_runtime},
            agent=agent_name,
        )
        await self._record_guardian_gate_result(pre_gate)
        if stage != Stage.GUARDIAN and gate_blocks_execution(pre_gate):
            status.state = "blocked"
            status.last_result = str(pre_gate.get("reason_code") or pre_gate.get("decision") or "guardian_gate_blocked")
            status.last_run_time = self._agent_now_iso(agent)
            status.success = False
            target_stage = Stage.COMPLETE if str(pre_gate.get("decision")) == "safe_stop" else Stage.GUARDIAN
            self._state.stage = target_stage
            await self._emit(
                event_type="stage_transition",
                message=f"Guardian pre-gate routed {stage.value} -> {target_stage.value}",
                payload={
                    "agent": "guardian_agent",
                    "node_id": stage.value,
                    "status": "blocked",
                    "from_stage": stage.value,
                    "to_stage": target_stage.value,
                    "guardian_gate": pre_gate,
                },
                level="WARNING",
            )
            await self._record_orchestrator_followup(
                stage=stage,
                trigger="guardian_pre_gate_block",
                payload={"guardian_gate": pre_gate, "status": "blocked"},
                next_stage=target_stage,
                guardian_context=pre_gate,
                level="WARNING",
            )
            return
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
            result_data = result.data if isinstance(result.data, dict) else {}
            gate_payload = compact_runtime_payload(result_data)
            if not isinstance(gate_payload, dict):
                gate_payload = {}
            if result.success is False:
                gate_payload.setdefault("failure_code", "AGENT_RESULT_FAILED")
            ok, validation_msg = validate_agent_output(stage.value, result_data)
            if not ok:
                gate_payload["failure_code"] = "CONTRACT_SCHEMA_INVALID"
                existing_blockers = gate_payload.get("blocking_reasons")
                if isinstance(existing_blockers, list):
                    existing_blockers.append(validation_msg)
                elif existing_blockers:
                    gate_payload["blocking_reasons"] = [str(existing_blockers), validation_msg]
                else:
                    gate_payload["blocking_reasons"] = [validation_msg]
                validation_gate = guardian_gate(
                    state=self._state,
                    stage=stage.value,
                    phase="post",
                    payload=gate_payload,
                    agent=agent_name,
                )
                result_data["guardian_gate"] = validation_gate
                result_data["guardian_contract"] = validation_gate.get("guardian_contract", {})
                result_data.setdefault("incident_records", []).extend(validation_gate.get("incident_records", []))
                result_data.setdefault("corrective_actions", []).extend(validation_gate.get("corrective_actions", []))
                await self._record_guardian_gate_result(validation_gate)
                raise ValueError(validation_msg)

            post_gate = guardian_gate(
                state=self._state,
                stage=stage.value,
                phase="post",
                payload=gate_payload,
                agent=agent_name,
            )
            result_data["guardian_gate"] = post_gate
            result_data["guardian_contract"] = post_gate.get("guardian_contract", {})
            if post_gate.get("incident_records"):
                result_data.setdefault("incident_records", []).extend(post_gate.get("incident_records", []))
            if post_gate.get("corrective_actions"):
                result_data.setdefault("corrective_actions", []).extend(post_gate.get("corrective_actions", []))
            runtime_artifacts = self._register_runtime_artifacts(stage, agent_name, result_data)
            self._merge_agent_data(stage, result_data)
            await self._record_guardian_gate_result(post_gate)
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
                payload=compact_runtime_payload(result.data),
                experiment_id=self._state.experiment_id,
            )
            await self._emit(
                event_type="agent_result",
                message=f"{agent_name}: {result.summary}",
                payload={"agent": agent_name, "node_id": stage.value, "status": "done", "module_runtime": module_runtime, "result": compact_runtime_payload(result.data)},
            )
            await self._emit_module_graph_completed(stage, agent_name, module_runtime, compact_runtime_payload(result_data))
            await self._emit_artifact_events(
                stage,
                agent_name,
                result_data,
                registered_artifacts=runtime_artifacts,
            )

            if await self._pause_for_vision_intervention(
                stage=stage,
                agent_name=agent_name,
                status=status,
                result_data=result_data,
            ):
                return

            if stage != Stage.GUARDIAN and gate_blocks_execution(post_gate):
                target_stage = Stage.COMPLETE if str(post_gate.get("decision")) == "safe_stop" else Stage.GUARDIAN
                self._state.stage = target_stage
                await self._emit(
                    event_type="stage_transition",
                    message=f"Guardian post-gate routed {stage.value} -> {target_stage.value}",
                    payload={
                        "agent": "guardian_agent",
                        "node_id": stage.value,
                        "status": "blocked",
                        "from_stage": stage.value,
                        "to_stage": target_stage.value,
                        "guardian_gate": post_gate,
                    },
                    level="WARNING",
                )
                await self._record_orchestrator_followup(
                    stage=stage,
                    trigger="guardian_post_gate_block",
                    payload=compact_runtime_payload(result_data),
                    next_stage=target_stage,
                    guardian_context=post_gate,
                    level="WARNING",
                )
                return

            guardian_decision = "continue"
            if stage == Stage.GUARDIAN:
                guardian_decision = str(result.data.get("guardian", {}).get("decision", "continue"))
                self._state.loop_count += 1
            transition_context = {**self._state.run_metadata, "agent_result": compact_runtime_payload(result.data)}
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
            await self._record_orchestrator_transition(
                stage=stage,
                next_stage=next_stage,
                result_data=result_data,
                selected_transition=selected_candidate,
                transition_candidates=candidates,
                guardian_context=post_gate,
            )
            await self._record_orchestrator_followup(
                stage=stage,
                trigger="post_stage",
                payload=compact_runtime_payload(result_data),
                next_stage=next_stage,
                guardian_context=post_gate,
            )
            if stage == Stage.GUARDIAN:
                await self._record_orchestrator_loop_reflection(
                    guardian_payload=compact_runtime_payload(result.data.get("guardian", {})) if isinstance(result.data, dict) else {},
                    next_stage=next_stage,
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
                    "orchestrator_decision": self._state.run_metadata.get("latest_orchestrator_decision", {}),
                    "orchestrator_handoff": self._state.run_metadata.get("latest_orchestrator_handoff", {}),
                    "orchestrator_followup": self._state.run_metadata.get("latest_orchestrator_followup", {}),
                },
            )
        except Exception as exc:
            exception_gate = guardian_gate(
                state=self._state,
                stage=stage.value,
                phase="exception",
                payload={
                    "status": "failed",
                    "failure_code": exc.__class__.__name__,
                    "error": str(exc),
                    "agent_exception": True,
                    "module_runtime": module_runtime,
                },
                agent=agent_name,
            )
            await self._record_guardian_gate_result(exception_gate)
            status.state = "error"
            status.last_result = str(exc)
            status.last_run_time = self._agent_now_iso(agent)
            status.success = False
            log_error(
                self._logger,
                run_id=self._state.run_id,
                where=f"{agent_name}@{stage.value}",
                error=exc,
                state_snapshot=compact_runtime_payload(self._state.model_dump(mode="json")),
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
                        "guardian_gate": exception_gate,
                    },
                    level="WARNING",
                )
                await self._record_orchestrator_followup(
                    stage=stage,
                    trigger="retry",
                    payload={"status": "retry", "error": str(exc), "recovery": action, "guardian_gate": exception_gate},
                    next_stage=stage,
                    guardian_context=exception_gate,
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
                        "guardian_gate": exception_gate,
                    },
                    level="ERROR",
                )
                await self._record_orchestrator_followup(
                    stage=stage,
                    trigger="fatal_error",
                    payload={"status": "error", "error": str(exc), "guardian_gate": exception_gate},
                    next_stage=Stage.ERROR,
                    guardian_context=exception_gate,
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
        pre_run_gate = await self._emit_pre_run_guardian_gate()
        await self._emit(
            event_type="run_start",
            message="LangGraph orchestration run started",
            payload={"node_id": self._state.stage.value, "status": "running", "guardian_gate": pre_run_gate},
        )
        if gate_blocks_execution(pre_run_gate):
            self._state.stage = Stage.COMPLETE if str(pre_run_gate.get("decision")) == "safe_stop" else Stage.ERROR
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
            trim_runtime_memory()
            await asyncio.sleep(self._interval_seconds)

        final_event = "run_complete" if self._state.stage == Stage.COMPLETE else "run_error"
        await self._emit(
            event_type=final_event,
            message=f"Run finished in stage={self._state.stage.value}",
            payload={"node_id": self._state.stage.value, "status": self._state.stage.value},
        )
        return self._state
