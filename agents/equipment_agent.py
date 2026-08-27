"""
File purpose:
- Control lab equipment and Windows-hosted GUI macros through MCP-compatible tools.

Key classes/functions:
- LabEquipmentAgent

Inputs/outputs:
- Input: experiment spec and run profile
- Output: protocol/macro execution status and result trace

Dependencies:
- mcp tools: equipment.pyautogui.health, equipment.pyautogui.list_programs,
  equipment.pyautogui.run, legacy utm.run_protocol

Modification guide:
- Safe places to edit: tool-plan prompt and safe payload normalization
- Risky places to edit: output keys consumed by analysis agent
- Related files: mcp_tools/equipment_tools.py, device_bridges/windows_pyautogui_bridge.py
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState
from utils.equipment_profiles import DEFAULT_UTM_PROFILE_ID, EquipmentProfile, EquipmentProfileRegistry, build_execution_contract
from policies.guardian_gate import equipment_skill_recovery_gate, gate_blocks_execution
from knowledge.manuals.prompting import build_manual_grounded_prompt, manual_context_audit
from knowledge.manuals.service import ManualKnowledgeService
from utils.equipment_skill_runtime import (
    EquipmentSkillRegistry,
    SkillContractError,
    build_exception_packet,
    validate_recovery_decision,
)


class LabEquipmentAgent(BaseAgent):
    """Runs physical/simulated equipment protocols and Windows GUI macros."""

    name = "equipment_agent"
    _PYAUTOGUI_TOOLS = {
        "equipment.pyautogui.health",
        "equipment.pyautogui.list_programs",
        "equipment.pyautogui.run",
    }
    _UTM_DEFAULT_PROGRAM = "utm_compression_start_v1"
    _RESULT_FILE_KEYS = ("result_file", "result_path", "csv_path", "utm_result_file", "utm_csv_path", "artifact_path")

    @staticmethod
    def _manual_context(query: str, *, purpose: str) -> dict[str, Any]:
        """Retrieve UTM-only evidence without making manuals an execution dependency."""
        service = ManualKnowledgeService(project_root=Path(__file__).resolve().parents[1])
        try:
            return service.query(
                {
                    "equipment_type": "utm",
                    "query": query,
                    "purpose": purpose,
                    "top_k": 6,
                }
            )
        except Exception as exc:
            return {
                "schema": "manual_context.v1",
                "equipment_type": "utm",
                "purpose": purpose,
                "query": query,
                "chunks": [],
                "insufficient_evidence": True,
                "error": f"{exc.__class__.__name__}: {exc}",
                "source_separation": {"manual_only": True, "web_used": False, "runtime_memory_used": False},
            }
        finally:
            service.close()

    def _manual_context_for_state(self, state: OrchestratorState, *, purpose: str) -> dict[str, Any]:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        query = " ".join(
            part
            for part in (
                f"UTM {purpose}",
                str(state.active_goal or ""),
                str(self._program_hint(state) or ""),
                json.dumps(spec, ensure_ascii=False, default=str)[:3000],
            )
            if part
        )
        return self._manual_context(query, purpose=purpose)

    @staticmethod
    def _is_live_gui_test_spec(state: OrchestratorState) -> bool:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        return bool(
            spec.get("test_mode_autofill")
            or spec.get("test_mode_llm_generated")
            or spec.get("test_printer_path")
            or spec.get("printer_test_path")
            or spec.get("printer_bridge_mode")
            or spec.get("printer_test_mode")
        )

    @classmethod
    def _test_like_mode(cls, state: OrchestratorState) -> bool:
        """Treat Live GUI test handoffs as test mode for deterministic equipment execution."""
        return state.mode == Mode.TEST or cls._is_live_gui_test_spec(state)

    @classmethod
    def _effective_runtime_mode(cls, state: OrchestratorState) -> str:
        return "test" if cls._test_like_mode(state) else state.mode.value

    def _program_hint(self, state: OrchestratorState) -> str:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        candidates: list[Any] = [
            spec.get("lab_equipment_program_id"),
            spec.get("equipment_pyautogui_program_id"),
            spec.get("pyautogui_program_id"),
            spec.get("equipment_program_id"),
            spec.get("program_id"),
            spec.get("equipment_command"),
            spec.get("command"),
            state.active_goal,
        ]
        lab_equipment = spec.get("lab_equipment") if isinstance(spec.get("lab_equipment"), dict) else {}
        equipment = spec.get("equipment") if isinstance(spec.get("equipment"), dict) else {}
        pyautogui = spec.get("pyautogui") if isinstance(spec.get("pyautogui"), dict) else {}
        candidates.extend(
            [
                lab_equipment.get("program_id"),
                lab_equipment.get("command"),
                equipment.get("program_id"),
                equipment.get("command"),
                pyautogui.get("program_id"),
                pyautogui.get("command"),
            ]
        )
        for value in candidates:
            text = str(value or "").strip()
            if not text:
                continue
            direct = re.fullmatch(r"program[0-9A-Za-z_-]+", text)
            if direct:
                return direct.group(0)
            match = re.search(r"\b(program[0-9A-Za-z_-]+)\b", text)
            if match:
                return match.group(1)
        return ""

    def _sequence_hint(self, state: OrchestratorState) -> list[dict[str, Any]]:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        for key in ("lab_equipment_sequence", "equipment_pyautogui_sequence", "equipment_sequence", "pyautogui_sequence"):
            raw = spec.get(key)
            if isinstance(raw, list):
                return [dict(item) for item in raw if isinstance(item, dict)]
        lab_equipment = spec.get("lab_equipment") if isinstance(spec.get("lab_equipment"), dict) else {}
        raw = lab_equipment.get("pyautogui_sequence")
        if isinstance(raw, list):
            return [dict(item) for item in raw if isinstance(item, dict)]
        equipment = spec.get("equipment") if isinstance(spec.get("equipment"), dict) else {}
        raw = equipment.get("pyautogui_sequence")
        if isinstance(raw, list):
            return [dict(item) for item in raw if isinstance(item, dict)]
        pyautogui = spec.get("pyautogui") if isinstance(spec.get("pyautogui"), dict) else {}
        raw = pyautogui.get("sequence")
        if isinstance(raw, list):
            return [dict(item) for item in raw if isinstance(item, dict)]
        return []

    def _has_explicit_equipment_plan(self, state: OrchestratorState) -> bool:
        """Return true only when the experiment spec intentionally selects equipment control."""
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        direct_keys = (
            "lab_equipment_program_id",
            "equipment_pyautogui_program_id",
            "pyautogui_program_id",
            "equipment_program_id",
            "program_id",
            "equipment_command",
            "command",
            "lab_equipment_sequence",
            "equipment_pyautogui_sequence",
            "equipment_sequence",
            "pyautogui_sequence",
        )
        if any(spec.get(key) for key in direct_keys):
            return True
        for key in ("lab_equipment", "equipment", "pyautogui"):
            nested = spec.get(key) if isinstance(spec.get(key), dict) else {}
            if any(nested.get(child_key) for child_key in ("program_id", "command", "pyautogui_sequence", "sequence")):
                return True
        return False

    def _tool_plan_prompt(self, state: OrchestratorState, tools: list[str]) -> str:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        program_hint = self._program_hint(state)
        sequence_hint = self._sequence_hint(state)
        base_prompt = (
            "You are the Equipment Agent tool-call planner.\n"
            "Choose only from these tools: equipment.pyautogui.health, "
            "equipment.pyautogui.list_programs, equipment.pyautogui.run.\n"
            "Use registered macro programs by program_id when the user command names a program.\n"
            "Never output raw Python, shell, PowerShell, or unregistered tool names.\n"
            "Return strict JSON only with keys: note, calls.\n"
            "calls is a list of {tool, payload}. Prefer health -> list_programs -> run for macro commands.\n\n"
            f"mode={self._effective_runtime_mode(state)}\n"
            f"active_goal={state.active_goal}\n"
            f"program_hint={program_hint}\n"
            f"sequence_hint={json.dumps(sequence_hint, ensure_ascii=True)}\n"
            f"available_tools={json.dumps(tools, ensure_ascii=True)}\n"
            f"experiment_spec={json.dumps(spec, ensure_ascii=True, default=str)[:4000]}\n"
        )
        return build_manual_grounded_prompt(base_prompt, self._manual_context_for_state(state, purpose="decision"))

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any] | None:
        clean = text.strip()
        if not clean:
            return None
        try:
            data = json.loads(clean)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    def _fallback_tool_plan(self, state: OrchestratorState) -> dict[str, Any]:
        program_id = self._program_hint(state)
        sequence = self._sequence_hint(state)
        calls: list[dict[str, Any]] = [{"tool": "equipment.pyautogui.health", "payload": {}}]
        calls.append({"tool": "equipment.pyautogui.list_programs", "payload": {}})
        if program_id:
            calls.append({"tool": "equipment.pyautogui.run", "payload": {"program_id": program_id, "command": state.active_goal}})
        elif sequence:
            calls.append({"tool": "equipment.pyautogui.run", "payload": {"sequence": sequence}})
        else:
            calls.append(
                {
                    "tool": "equipment.pyautogui.run",
                    "payload": {"program_id": self._UTM_DEFAULT_PROGRAM, "command": "Run UTM compression test and export CSV"},
                }
            )
        return {"note": "safe deterministic equipment tool plan", "calls": calls}

    def _normalize_plan(self, raw_plan: dict[str, Any], state: OrchestratorState) -> tuple[str, list[dict[str, Any]]]:
        note = str(raw_plan.get("note") or "Equipment tool plan selected.")[:220]
        raw_calls = raw_plan.get("calls", [])
        if not isinstance(raw_calls, list) or not raw_calls:
            raw_calls = self._fallback_tool_plan(state)["calls"]
        calls: list[dict[str, Any]] = []
        for item in raw_calls:
            if not isinstance(item, dict):
                continue
            tool = str(item.get("tool", "")).strip()
            if tool not in self._PYAUTOGUI_TOOLS:
                continue
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            calls.append({"tool": tool, "payload": dict(payload)})
        if not calls:
            calls = self._fallback_tool_plan(state)["calls"]
        return note, calls

    def _planned_utm_program(self, calls: list[dict[str, Any]], state: OrchestratorState) -> bool:
        for call in calls:
            if call.get("tool") != "equipment.pyautogui.run":
                continue
            payload = call.get("payload") if isinstance(call.get("payload"), dict) else {}
            program_id = str(payload.get("program_id") or self._program_hint(state) or "").strip()
            if program_id and self._is_utm_program(program_id):
                return True
            if not program_id and not payload.get("sequence"):
                return True
        return False

    @staticmethod
    def _has_equipment_vision_results(source_stage_context: dict[str, Any]) -> bool:
        vision = source_stage_context.get("vision") if isinstance(source_stage_context.get("vision"), dict) else {}
        for key in ("equipment_vision_check_results", "equipment_vision_results"):
            if isinstance(vision.get(key), list) and vision[key]:
                return True
        return isinstance(vision.get("equipment_vision_check_result"), dict)

    def _base_run_payload(self, state: OrchestratorState) -> dict[str, Any]:
        return {
            "sequence_id": f"equipment-{state.run_id}",
            "runtime_mode": self._effective_runtime_mode(state),
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "active_goal": state.active_goal,
            "experiment_spec": dict(state.current_experiment_spec or {}),
            "source_stage_context": {
                "specimen": state.run_metadata.get("specimen_result", {}),
                "vision": dict(state.latest_observations or {}),
                "manipulation": state.run_metadata.get("manipulation_result", {}),
                "analysis": dict(state.latest_analysis or {}),
            },
        }

    @staticmethod
    def _selected_profile(state: OrchestratorState) -> EquipmentProfile:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        profile_id = str(spec.get("equipment_profile_id") or DEFAULT_UTM_PROFILE_ID).strip()
        return EquipmentProfileRegistry.default().get(profile_id)

    async def _call_tool(self, ctx: AgentContext, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(ctx.tools.call, tool, payload)

    @staticmethod
    def _trace_file_ref(item: dict[str, Any], result: dict[str, Any]) -> str:
        for source in (item, result):
            for key in (
                "data_file_ref",
                "artifact_or_path",
                "result_file",
                "utm_csv_path",
                "linux_path",
                "local_path",
                "windows_path",
                "path",
            ):
                value = source.get(key)
                if value:
                    return str(value)
        data = result.get("data_acquisition") if isinstance(result.get("data_acquisition"), dict) else {}
        for key in ("linux_path", "local_path", "windows_path", "path"):
            value = data.get(key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _screen_checkpoint_for_trace_step(step: str) -> str:
        step_upper = str(step or "").upper()
        if "BEFORE" in step_upper or "READY" in step_upper:
            return "before_start"
        if "RUNNING" in step_upper or "AFTER_START" in step_upper:
            return "after_start"
        if "COMPLETE" in step_upper or "DONE" in step_upper:
            return "after_complete"
        if "FAIL" in step_upper or "ERROR" in step_upper or "BLOCK" in step_upper:
            return "failure"
        return ""

    @staticmethod
    def _is_data_trace_step(step: str) -> bool:
        step_upper = str(step or "").upper()
        return any(token in step_upper for token in ("SAVE", "EXPORT", "PULL_ARTIFACT", "PARSE", "WAIT_FOR_FILE", "WAIT_FOR_EXPORT"))

    @classmethod
    def _replay_pyautogui_step_trace(
        cls,
        *,
        result: dict[str, Any],
        payload: dict[str, Any],
        emit_tool_event: Any,
    ) -> None:
        """Replay returned bridge step_trace when the bridge cannot stream callbacks.

        The simulator emits callbacks while it runs. A real Windows bridge returns
        the trace after /execute completes, so replaying here keeps the Live GUI
        evidence stream consistent across simulator/live transports.
        """
        if not callable(emit_tool_event) or not isinstance(result, dict):
            return
        if str(result.get("mode") or "").strip().lower() == "simulator":
            return
        trace = result.get("step_trace")
        if not isinstance(trace, list) or not trace:
            return
        sequence_id = str(result.get("sequence_id") or payload.get("sequence_id") or "")
        program_id = str(result.get("program_id") or payload.get("program_id") or "")
        target_window = str(
            result.get("target_window")
            or payload.get("target_window")
            or result.get("target_window_regex")
            or payload.get("target_window_regex")
            or result.get("target_app")
            or payload.get("target_app")
            or ""
        )
        screen_checks = result.get("screen_checks") if isinstance(result.get("screen_checks"), list) else []
        screen_by_checkpoint = {
            str(item.get("checkpoint") or ""): item
            for item in screen_checks
            if isinstance(item, dict)
        }
        artifacts = result.get("output_artifacts") if isinstance(result.get("output_artifacts"), list) else []
        artifacts_by_id = {
            str(item.get("artifact_id") or ""): item
            for item in artifacts
            if isinstance(item, dict) and item.get("artifact_id")
        }
        data_acq = result.get("data_acquisition") if isinstance(result.get("data_acquisition"), dict) else {}
        common = {
            "tool": "equipment.pyautogui.run",
            "source": "bridge_response_trace",
            "sequence_id": sequence_id,
            "program_id": program_id,
            "bridge_host": result.get("bridge_host") or result.get("host"),
            "bridge_url": result.get("bridge_url"),
            "target_window": target_window,
            "target_ui": target_window,
            "server_version": result.get("server_version"),
            "script_version": result.get("script_version"),
            "client_latency_ms": result.get("client_latency_ms"),
            "failure_code": result.get("failure_code"),
        }
        for item in trace:
            if not isinstance(item, dict):
                continue
            step = str(item.get("step") or "STEP")
            status = str(item.get("status") or result.get("status") or "unknown")
            detail = item.get("detail")
            event = {
                **common,
                "step": step,
                "status": status,
                "detail": "" if detail is None else str(detail),
            }
            failure_code = item.get("failure_code") or item.get("code")
            if failure_code:
                event["failure_code"] = str(failure_code)
            checkpoint = str(item.get("checkpoint") or cls._screen_checkpoint_for_trace_step(step))
            screen_check = screen_by_checkpoint.get(checkpoint) if checkpoint else None
            if isinstance(screen_check, dict):
                event["checkpoint"] = checkpoint
                for key in ("state", "confidence", "screenshot_artifact"):
                    if screen_check.get(key) not in (None, "", [], {}):
                        event[key] = screen_check[key]
                artifact_id = str(screen_check.get("screenshot_artifact") or "")
                artifact = artifacts_by_id.get(artifact_id)
                if artifact:
                    event.setdefault("artifact_id", artifact_id)
                    for key in ("local_path", "path", "linux_path", "windows_path"):
                        if artifact.get(key) not in (None, "", [], {}):
                            event.setdefault(key, artifact[key])
            data_file_ref = cls._trace_file_ref(item, result)
            if data_file_ref:
                event["data_file_ref"] = data_file_ref
            if cls._is_data_trace_step(step):
                for key in (
                    "windows_path",
                    "linux_path",
                    "local_path",
                    "sha256",
                    "size_bytes",
                    "row_count_probe",
                    "columns_probe",
                    "missing_columns",
                    "save_method",
                    "artifact_pull_status",
                    "parse_failure_code",
                    "parse_failure_message",
                    "data_quality",
                    "filename",
                    "artifact_id",
                ):
                    if data_acq.get(key) not in (None, "", [], {}):
                        event.setdefault(key, data_acq[key])
            emit_tool_event({key: value for key, value in event.items() if value not in (None, "", [], {})})

    @staticmethod
    def _is_utm_program(program_id: str) -> bool:
        return str(program_id or "").startswith("utm_")

    @staticmethod
    def _safe_artifact_segment(value: Any, fallback: str) -> str:
        text = str(value or fallback).strip() or fallback
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)
        return cleaned[:96].strip("._-") or fallback

    @classmethod
    def _result_file_path(cls, result: dict[str, Any]) -> str:
        for key in cls._RESULT_FILE_KEYS:
            value = result.get(key)
            if value:
                return str(value)
        data_acq = result.get("data_acquisition") if isinstance(result.get("data_acquisition"), dict) else {}
        for key in ("linux_path", "local_path", "path"):
            value = data_acq.get(key)
            if value:
                return str(value)
        artifacts = result.get("output_artifacts") if isinstance(result.get("output_artifacts"), list) else []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            for key in ("local_path", "path", "linux_path"):
                value = artifact.get(key)
                if value:
                    return str(value)
        return ""


    @staticmethod
    def _unique_refs(values: list[Any]) -> list[str]:
        refs: list[str] = []
        seen: set[str] = set()
        for value in values:
            ref = str(value or "").strip()
            if ref and ref not in seen:
                refs.append(ref)
                seen.add(ref)
        return refs

    @classmethod
    def _artifact_records(cls, equipment_result: dict[str, Any]) -> list[dict[str, Any]]:
        artifacts = equipment_result.get("output_artifacts") if isinstance(equipment_result.get("output_artifacts"), list) else []
        records: list[dict[str, Any]] = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            record: dict[str, Any] = {}
            for key in (
                "kind",
                "artifact_id",
                "filename",
                "local_path",
                "linux_path",
                "path",
                "windows_path",
                "sha256",
                "size_bytes",
                "row_count_probe",
                "columns_probe",
                "stable_for_sec",
                "content_type",
            ):
                value = artifact.get(key)
                if value not in (None, "", []):
                    record[key] = value
            if record:
                records.append(record)
        return records

    @classmethod
    def _artifact_ref_from_record(cls, record: dict[str, Any]) -> str:
        for key in ("local_path", "linux_path", "path", "artifact_id", "windows_path"):
            value = record.get(key)
            if value:
                return str(value)
        return ""

    @classmethod
    def _artifact_evidence_refs(cls, *, equipment_result: dict[str, Any], data_path: str, screen_checks: list[dict[str, Any]]) -> dict[str, Any]:
        records = cls._artifact_records(equipment_result)
        all_refs = cls._unique_refs(([data_path] if data_path else []) + [cls._artifact_ref_from_record(record) for record in records])
        screen_ids = {
            str(item.get("screenshot_artifact") or "")
            for item in screen_checks
            if isinstance(item, dict) and item.get("screenshot_artifact")
        }
        screen_refs: list[str] = []
        data_refs: list[str] = [data_path] if data_path else []
        for record in records:
            ref = cls._artifact_ref_from_record(record)
            kind = str(record.get("kind") or "")
            artifact_id = str(record.get("artifact_id") or "")
            if kind == "screen_png" or artifact_id in screen_ids:
                screen_refs.append(ref)
            if kind == "utm_csv":
                data_refs.append(ref)
        return {
            "artifact_records": records,
            "artifact_refs": all_refs,
            "screen_evidence_refs": cls._unique_refs(screen_refs),
            "data_evidence_refs": cls._unique_refs(data_refs),
        }

    @classmethod
    def _bridge_artifact_context(
        cls,
        *,
        equipment_result: dict[str, Any],
        tool_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Collect Windows bridge filesystem/audit references for report and handoff provenance."""
        context: dict[str, Any] = {}

        def set_if_present(target_key: str, value: Any) -> None:
            if value not in (None, "", []):
                context[target_key] = str(value)

        def absorb(payload: dict[str, Any]) -> None:
            artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
            for source_key, target_key in (
                ("bridge_url", "bridge_url"),
                ("bridge_host", "bridge_host"),
                ("server_version", "server_version"),
                ("script_version", "script_version"),
                ("client_latency_ms", "client_latency_ms"),
            ):
                value = payload.get(source_key)
                if value not in (None, "", []):
                    context[target_key] = value
            pyautogui_status = payload.get("pyautogui") if isinstance(payload.get("pyautogui"), dict) else {}
            if pyautogui_status:
                context["pyautogui_available"] = bool(pyautogui_status.get("available"))
                if pyautogui_status.get("failsafe") is not None:
                    context["pyautogui_failsafe"] = bool(pyautogui_status.get("failsafe"))
                if pyautogui_status.get("pause") not in (None, ""):
                    context["pyautogui_pause"] = pyautogui_status.get("pause")
                if pyautogui_status.get("error"):
                    context["pyautogui_error"] = str(pyautogui_status.get("error"))
                if pyautogui_status.get("simulated") is not None:
                    context["pyautogui_simulated"] = bool(pyautogui_status.get("simulated"))
            set_if_present("artifact_root", artifacts.get("root") or payload.get("artifact_root"))
            set_if_present(
                "request_log_path",
                artifacts.get("request_log")
                or payload.get("request_log")
                or payload.get("request_log_path")
                or payload.get("bridge_request_log_ref"),
            )
            set_if_present("locator_root", artifacts.get("locator_root") or payload.get("locator_root"))
            set_if_present("utm_export_root", artifacts.get("utm_export_root") or payload.get("utm_export_root"))
            count_value = payload.get("event_count")
            if count_value in (None, ""):
                count_value = payload.get("request_log_event_count")
            if count_value not in (None, ""):
                try:
                    context["request_log_event_count"] = int(count_value or 0)
                except (TypeError, ValueError):
                    context["request_log_event_count"] = 0
            events = payload.get("events") if isinstance(payload.get("events"), list) else []
            if events:
                context["request_log_recent_paths"] = cls._unique_refs([str(item.get("path") or "") for item in events if isinstance(item, dict)])[-10:]
            recent_paths = []
            for key in ("request_log_recent_paths", "recent_paths"):
                value = payload.get(key)
                if isinstance(value, list) and value:
                    recent_paths = [str(item) for item in value]
                    break
            if recent_paths:
                context["request_log_recent_paths"] = cls._unique_refs(recent_paths)[-10:]
            execute_seen = payload.get("execute_event_seen")
            if execute_seen is None:
                execute_seen = payload.get("request_log_execute_seen")
            if execute_seen is not None:
                context["request_log_execute_seen"] = bool(execute_seen)
            execute_count = payload.get("execute_event_count")
            if execute_count in (None, ""):
                execute_count = payload.get("request_log_execute_count")
            if execute_count not in (None, ""):
                try:
                    context["request_log_execute_count"] = int(execute_count or 0)
                except (TypeError, ValueError):
                    context["request_log_execute_count"] = 0
            for source_key, target_key in (
                ("execute_payload_event_count", "request_log_execute_payload_event_count"),
                ("execute_result_event_count", "request_log_execute_result_event_count"),
            ):
                if payload.get(source_key) not in (None, ""):
                    try:
                        context[target_key] = int(payload.get(source_key) or 0)
                    except (TypeError, ValueError):
                        context[target_key] = 0
            for source_key, target_key in (
                ("execute_run_ids", "request_log_execute_run_ids"),
                ("execute_sequence_ids", "request_log_execute_sequence_ids"),
                ("execute_specimen_ids", "request_log_execute_specimen_ids"),
                ("execute_program_ids", "request_log_execute_program_ids"),
            ):
                values = payload.get(source_key)
                if isinstance(values, list) and values:
                    context[target_key] = cls._unique_refs(values)[-10:]
            execute_context = payload.get("last_execute_context") if isinstance(payload.get("last_execute_context"), dict) else {}
            if execute_context:
                context["request_log_last_execute_context"] = {
                    key: value
                    for key, value in execute_context.items()
                    if key in {"at", "status", "audit_kind", "sequence_id", "run_id", "specimen_id", "program_id", "payload_sha256", "result_ok", "result_status", "failure_code"}
                }
            if events:
                payload_events = [event for event in events if isinstance(event, dict) and str(event.get("path") or "") == "/execute" and str(event.get("audit_kind") or "") == "execute_payload"]
                if payload_events:
                    context.setdefault("request_log_execute_payload_event_count", len(payload_events))
                    context.setdefault("request_log_execute_run_ids", cls._unique_refs([event.get("run_id") for event in payload_events])[-10:])
                    context.setdefault("request_log_execute_sequence_ids", cls._unique_refs([event.get("sequence_id") for event in payload_events])[-10:])
                    context.setdefault("request_log_execute_specimen_ids", cls._unique_refs([event.get("specimen_id") for event in payload_events])[-10:])
                    context.setdefault("request_log_execute_program_ids", cls._unique_refs([event.get("program_id") for event in payload_events])[-10:])
                    context.setdefault("request_log_last_execute_context", {
                        key: value
                        for key, value in payload_events[-1].items()
                        if key in {"at", "status", "audit_kind", "sequence_id", "run_id", "specimen_id", "program_id", "payload_sha256"}
                    })
            set_if_present("request_log_last_execute_at", payload.get("last_execute_at") or payload.get("request_log_last_execute_at"))

        absorb(equipment_result)
        for item in tool_results:
            if not isinstance(item, dict):
                continue
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            if result:
                absorb(result)
        return context

    @staticmethod
    def _recommended_recovery(step: str, failure_code: str) -> str:
        step_upper = step.upper()
        code = failure_code.upper()
        if "LOCATOR" in code or "ASSERT" in step_upper or "CLICK" in step_upper:
            return "Recapture UTM screen locator, verify target window focus/DPI, then rerun live preflight."
        if "SAVE" in step_upper or "EXPORT" in step_upper or "DATA" in code:
            return "Check UTM export folder, Save/Export dialog, file permissions, and retry the registered save/export macro."
        if "REQUEST_LOG" in code:
            return "Check the Windows bridge /request-log endpoint, token auth, and bridge_requests.jsonl audit file before retry."
        if "VISION" in code:
            return "Refresh Vision cross-checks for fixture occupancy, robot clearance, and UTM motion before retry."
        return "Operator review required before retrying the registered UTM protocol."

    @classmethod
    def _failure_retry_table(cls, *, equipment_result: dict[str, Any], blocking_reasons: list[str], failure_code: str | None) -> list[dict[str, Any]]:
        trace = equipment_result.get("step_trace") if isinstance(equipment_result.get("step_trace"), list) else []
        rows: list[dict[str, Any]] = []
        effective_failure = str(failure_code or equipment_result.get("failure_code") or "EQUIPMENT_VERIFICATION_FAILED")
        for item in trace:
            if not isinstance(item, dict):
                continue
            step = str(item.get("step") or "")
            status = str(item.get("status") or "")
            status_lower = status.lower()
            interesting = status_lower in {"blocked", "failed", "warning"} or step.upper() in {
                "AUTO_SAVE_MISSING",
                "MANUAL_SAVE_EXPORT",
                "SAVE_EXPORT",
                "WAIT_FOR_EXPORT",
            }
            if not interesting:
                continue
            fallback_macro = "utm_manual_save_csv_v1" if "MANUAL_SAVE" in step.upper() else ""
            rows.append(
                {
                    "step": step,
                    "status": status,
                    "detail": str(item.get("detail") or ""),
                    "failure_code": effective_failure if status_lower in {"blocked", "failed"} else "",
                    "fallback_macro": fallback_macro,
                    "operator_intervention_required": status_lower in {"blocked", "failed"},
                    "recommended_action": cls._recommended_recovery(step, effective_failure),
                }
            )
        if not rows and blocking_reasons:
            for reason in blocking_reasons:
                rows.append(
                    {
                        "step": "HANDOFF_GATE",
                        "status": "blocked",
                        "detail": str(reason),
                        "failure_code": str(reason),
                        "fallback_macro": "",
                        "operator_intervention_required": True,
                        "recommended_action": cls._recommended_recovery("HANDOFF_GATE", str(reason)),
                    }
                )
        return rows

    @staticmethod
    def _probe_csv_file(path_value: str) -> dict[str, Any]:
        if not path_value:
            return {"ok": False, "failure_code": "UTM_EXPORT_FILE_MISSING"}
        path = Path(path_value).expanduser()
        if not path.exists() or not path.is_file():
            return {"ok": False, "failure_code": "UTM_EXPORT_FILE_MISSING", "path": str(path)}
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        lines = [line for line in text.splitlines() if line.strip()]
        columns = [item.strip() for item in lines[0].split(",")] if lines else []
        row_count = max(0, len(lines) - 1)
        required = {"time_s", "displacement_mm", "force_N"}
        missing = sorted(required.difference(columns))

        def result(ok: bool, *, failure_code: str | None = None, message: str = "", data_quality: dict[str, Any] | None = None) -> dict[str, Any]:
            payload: dict[str, Any] = {
                "ok": ok,
                "path": str(path),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
                "row_count_probe": row_count,
                "columns_probe": columns,
                "missing_columns": missing,
                "data_quality": data_quality or {},
            }
            if failure_code:
                payload["failure_code"] = failure_code
            if message:
                payload["message"] = message
            return payload

        if missing:
            return result(False, failure_code="UTM_DATA_PARSE_FAILED", message=f"Missing UTM columns: {', '.join(missing)}")
        if row_count < 2:
            return result(False, failure_code="UTM_DATA_PARSE_FAILED", message="UTM export must contain at least two data rows for signal validation.")
        index = {name: columns.index(name) for name in required}
        numeric_rows: list[dict[str, float]] = []
        invalid_numeric_rows = 0
        for line in lines[1:]:
            parts = [item.strip() for item in line.split(",")]
            try:
                numeric_rows.append({"time_s": float(parts[index["time_s"]]), "displacement_mm": float(parts[index["displacement_mm"]]), "force_N": float(parts[index["force_N"]])})
            except (IndexError, TypeError, ValueError):
                invalid_numeric_rows += 1
        if len(numeric_rows) < 2:
            return result(False, failure_code="UTM_DATA_PARSE_FAILED", message="UTM export must contain at least two numeric data rows.")
        eps = 1e-9
        time_values = [row["time_s"] for row in numeric_rows]
        displacement_values = [row["displacement_mm"] for row in numeric_rows]
        force_values = [row["force_N"] for row in numeric_rows]
        force_range = max(force_values) - min(force_values)
        displacement_range = max(displacement_values) - min(displacement_values)
        time_monotonic = all((b - a) >= -eps for a, b in zip(time_values, time_values[1:]))
        displacement_increasing = all((b - a) >= -eps for a, b in zip(displacement_values, displacement_values[1:]))
        displacement_decreasing = all((b - a) <= eps for a, b in zip(displacement_values, displacement_values[1:]))
        displacement_monotonic = displacement_increasing or displacement_decreasing
        force_nonzero = any(abs(value) > eps for value in force_values)
        force_changes = force_range > eps
        displacement_changes = displacement_range > eps
        quality = {
            "numeric_row_count": len(numeric_rows),
            "invalid_numeric_row_count": invalid_numeric_rows,
            "force_nonzero": force_nonzero,
            "force_changes": force_changes,
            "force_range_N": force_range,
            "force_min_N": min(force_values),
            "force_max_N": max(force_values),
            "displacement_changes": displacement_changes,
            "displacement_range_mm": displacement_range,
            "displacement_min_mm": min(displacement_values),
            "displacement_max_mm": max(displacement_values),
            "displacement_monotonic": displacement_monotonic,
            "displacement_direction": "increasing" if displacement_increasing else "decreasing" if displacement_decreasing else "mixed",
            "time_monotonic_non_decreasing": time_monotonic,
            "time_min_s": min(time_values),
            "time_max_s": max(time_values),
        }
        if not time_monotonic:
            return result(False, failure_code="UTM_DATA_NON_MONOTONIC_TIME", message="UTM time_s values are not monotonic non-decreasing.", data_quality=quality)
        if not displacement_changes:
            return result(False, failure_code="UTM_DATA_NO_DISPLACEMENT_SIGNAL", message="UTM displacement_mm does not change across samples.", data_quality=quality)
        if not displacement_monotonic:
            return result(False, failure_code="UTM_DATA_NON_MONOTONIC_DISPLACEMENT", message="UTM displacement_mm is not monotonic in either direction.", data_quality=quality)
        if not force_nonzero or not force_changes:
            return result(False, failure_code="UTM_DATA_NO_FORCE_SIGNAL", message="UTM force_N has no nonzero changing load signal.", data_quality=quality)
        return result(True, data_quality=quality)


    def _write_test_utm_csv(self, *, state: OrchestratorState, specimen_id: str, program_id: str) -> dict[str, Any]:
        artifact_dir = Path("artifacts") / "equipment" / state.run_id / "utm"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_specimen = self._safe_artifact_segment(specimen_id, "specimen-test")
        path = artifact_dir / f"utm_csv_{safe_specimen}_{stamp}.csv"
        rows = ["time_s,displacement_mm,force_N"]
        for idx in range(80):
            displacement = idx * 0.05
            force = max(0.0, 18.0 * displacement - 1.1 * displacement * displacement + (idx % 5) * 0.45)
            rows.append(f"{idx * 0.25:.3f},{displacement:.4f},{force:.4f}")
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        probe = self._probe_csv_file(str(path))
        artifact_id = path.stem
        return {
            "kind": "utm_csv",
            "artifact_id": artifact_id,
            "program_id": program_id,
            "windows_path": f"C:/ATR/utm_exports/{state.run_id}/{path.name}",
            "local_path": str(path),
            "path": str(path),
            "filename": path.name,
            "stable_for_sec": 2.0,
            **{key: value for key, value in probe.items() if key not in {"ok", "failure_code", "path"}},
        }

    def _equipment_preconditions(self, *, state: OrchestratorState, source_stage_context: dict[str, Any]) -> dict[str, Any]:
        vision = source_stage_context.get("vision") if isinstance(source_stage_context.get("vision"), dict) else {}
        manipulation = source_stage_context.get("manipulation") if isinstance(source_stage_context.get("manipulation"), dict) else {}
        transfer = vision.get("transfer_readiness") if isinstance(vision.get("transfer_readiness"), dict) else {}
        signal = vision.get("vision_signal") if isinstance(vision.get("vision_signal"), dict) else {}
        blocking: list[str] = []
        manipulation_status = str(manipulation.get("completion_status") or manipulation.get("handoff_status") or "unknown")
        test_like = self._test_like_mode(state)
        specimen_present = bool(transfer.get("ready", test_like)) or bool(signal.get("value", False)) or test_like
        robot_clear = not bool(vision.get("robot_in_utm_path", False))
        anomaly = bool(vision.get("anomaly", False))
        if state.mode == Mode.LIVE and not test_like:
            if not specimen_present:
                blocking.append("VISION_SPECIMEN_ON_FIXTURE_REQUIRED")
            if not robot_clear:
                blocking.append("VISION_ROBOT_CLEAR_REQUIRED")
            if anomaly:
                blocking.append("VISION_ANOMALY_DETECTED")
        return {
            "manipulation_handoff_status": manipulation_status,
            "vision_fixture_object_present": specimen_present,
            "vision_robot_clear": robot_clear,
            "utm_app_ready": True if test_like else "unknown",
            "blocking_reasons": blocking,
        }

    def _equipment_vision_requests(self, *, state: OrchestratorState, source_stage_context: dict[str, Any]) -> list[dict[str, Any]]:
        specimen = source_stage_context.get("specimen") if isinstance(source_stage_context.get("specimen"), dict) else {}
        specimen_id = str(specimen.get("specimen_id") or state.current_experiment_spec.get("specimen_id") or "")
        base = {
            "agent_signal_type": "equipment_vision_check_request",
            "run_id": state.run_id,
            "loop_id": state.loop_count,
            "specimen_id": specimen_id,
            "producer_agent": self.name,
            "consumer_agent": "vision_agent",
        }
        return [
            {
                **base,
                "check_id": "utm_pre_start",
                "expected": {
                    "specimen_on_utm_fixture": True,
                    "robot_clear_of_utm": True,
                    "compression_flatten_occupied": True,
                    "human_intrusion": False,
                },
                "timeout_s": 5,
            },
            {
                **base,
                "check_id": "utm_motion_confirm",
                "expected": {
                    "utm_crosshead_motion": "started_or_force_curve_active",
                    "specimen_remains_aligned": True,
                    "fixture_slip_detected": False,
                },
                "timeout_s": 10,
            },
            {
                **base,
                "check_id": "utm_test_complete",
                "expected": {
                    "utm_crosshead_stopped": True,
                    "fixture_safe_to_access": True,
                    "specimen_tested_or_crushed": True,
                },
                "timeout_s": 10,
            },
        ]

    @staticmethod
    def _parse_vision_time(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _vision_signal_expires_at(cls, signal: dict[str, Any]) -> datetime | None:
        return cls._parse_vision_time(signal.get("expires_at"))

    @classmethod
    def _vision_signal_freshness_missing(cls, signal: dict[str, Any]) -> bool:
        return cls._vision_signal_expires_at(signal) is None

    @staticmethod
    def _expected_vision_identity(*, state: OrchestratorState, source_stage_context: dict[str, Any]) -> dict[str, str]:
        specimen = source_stage_context.get("specimen") if isinstance(source_stage_context.get("specimen"), dict) else {}
        return {
            "run_id": str(state.run_id or ""),
            "specimen_id": str(specimen.get("specimen_id") or state.current_experiment_spec.get("specimen_id") or ""),
        }

    @staticmethod
    def _vision_identity_status(signal: dict[str, Any], expected: dict[str, str]) -> dict[str, Any]:
        observed = {
            "run_id": str(signal.get("run_id") or ""),
            "specimen_id": str(signal.get("specimen_id") or ""),
        }
        missing = [key for key, value in expected.items() if value and not observed.get(key)]
        mismatched = [key for key, value in expected.items() if value and observed.get(key) and observed.get(key) != value]
        return {
            "required": bool(expected.get("run_id") or expected.get("specimen_id")),
            "expected": dict(expected),
            "observed": observed,
            "missing_fields": missing,
            "mismatched_fields": mismatched,
            "present": not missing,
            "match": not missing and not mismatched,
        }

    @classmethod
    def _vision_identity_ok(cls, signal: dict[str, Any], expected: dict[str, str]) -> bool:
        return bool(cls._vision_identity_status(signal, expected).get("match"))

    @classmethod
    def _vision_signal_is_stale(cls, signal: dict[str, Any]) -> bool:
        expires_at = cls._vision_signal_expires_at(signal)
        if not expires_at:
            return False
        return datetime.now(timezone.utc) > expires_at

    @classmethod
    def _signal_is_ok(cls, signal: dict[str, Any], *, min_confidence: float = 0.6) -> bool:
        status = str(signal.get("status") or "").lower()
        value = signal.get("value")
        confidence_raw = signal.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except Exception:
            confidence = 0.0
        return (
            bool(value)
            and status not in {"blocked", "warning", "not_checked", "failed", "expired", "stale"}
            and confidence >= min_confidence
            and not cls._vision_signal_freshness_missing(signal)
            and not cls._vision_signal_is_stale(signal)
        )

    def _equipment_vision_cross_checks(self, *, state: OrchestratorState, source_stage_context: dict[str, Any]) -> dict[str, Any]:
        if self._test_like_mode(state):
            checks = {
                "utm_pre_start": {"ok": True, "source": "test_mode_simulated", "confidence": 1.0},
                "utm_motion_confirm": {"ok": True, "source": "test_mode_simulated", "confidence": 1.0},
                "utm_test_complete": {"ok": True, "source": "test_mode_simulated", "confidence": 1.0},
            }
            return {"required": list(checks), "checks": checks, "all_required_ok": True, "blocking_reasons": [], "evidence_frame_ids": []}

        vision = source_stage_context.get("vision") if isinstance(source_stage_context.get("vision"), dict) else {}
        expected_identity = self._expected_vision_identity(state=state, source_stage_context=source_stage_context)
        raw_results: list[dict[str, Any]] = []
        for key in ("equipment_vision_check_results", "equipment_vision_results"):
            values = vision.get(key)
            if isinstance(values, list):
                raw_results.extend([dict(item) for item in values if isinstance(item, dict)])
        single = vision.get("equipment_vision_check_result")
        if isinstance(single, dict):
            raw_results.append(dict(single))

        explicit: dict[str, dict[str, Any]] = {}
        evidence_frames: list[str] = []
        for item in raw_results:
            check_id = str(item.get("check_id") or "").strip()
            if not check_id:
                continue
            confidence_raw = item.get("confidence", 0.0)
            try:
                confidence = float(confidence_raw)
            except Exception:
                confidence = 0.0
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            frame_ids = evidence.get("frame_ids") if isinstance(evidence.get("frame_ids"), list) else []
            evidence_frames.extend([str(frame) for frame in frame_ids if frame])
            freshness_missing = self._vision_signal_freshness_missing(item)
            stale = self._vision_signal_is_stale(item)
            identity = self._vision_identity_status(item, expected_identity)
            explicit[check_id] = {
                "ok": bool(item.get("ok")) and confidence >= 0.6 and not freshness_missing and not stale and bool(identity.get("match")),
                "source": "equipment_vision_check_result",
                "confidence": confidence,
                "fresh": not freshness_missing and not stale,
                "stale": stale,
                "freshness_missing": freshness_missing,
                "identity": identity,
                "identity_missing": bool(identity.get("missing_fields")),
                "identity_mismatch": bool(identity.get("mismatched_fields")),
                "timestamp": item.get("timestamp", ""),
                "expires_at": item.get("expires_at", ""),
                "signals": item.get("signals", {}),
                "evidence": evidence,
            }

        signals: list[dict[str, Any]] = []
        for key in ("agent_signals", "signal_board"):
            values = vision.get(key)
            if isinstance(values, list):
                signals.extend([dict(item) for item in values if isinstance(item, dict)])
        report = vision.get("vision_report") if isinstance(vision.get("vision_report"), dict) else {}
        board = report.get("signal_board") if isinstance(report.get("signal_board"), list) else []
        signals.extend([dict(item) for item in board if isinstance(item, dict)])
        packet = vision.get("vision_signal") if isinstance(vision.get("vision_signal"), dict) else {}
        packet_signals = packet.get("signals") if isinstance(packet.get("signals"), list) else []
        signals.extend([dict(item) for item in packet_signals if isinstance(item, dict)])
        by_signal = {str(item.get("signal") or ""): item for item in signals if item.get("signal")}

        pre_start_signal_names = ["specimen_on_utm_platen", "fixture_alignment_ok"]
        motion_signal_names = ["utm_motion_observed"]
        complete_signal_names = ["utm_home_restored"]

        def stale_signal_names(names: list[str]) -> list[str]:
            return [name for name in names if self._vision_signal_is_stale(by_signal.get(name, {}))]

        def freshness_missing_signal_names(names: list[str]) -> list[str]:
            return [name for name in names if name in by_signal and self._vision_signal_freshness_missing(by_signal.get(name, {}))]

        def identity_missing_signal_names(names: list[str]) -> list[str]:
            return [
                name
                for name in names
                if name in by_signal and bool(self._vision_identity_status(by_signal.get(name, {}), expected_identity).get("missing_fields"))
            ]

        def identity_mismatched_signal_names(names: list[str]) -> list[str]:
            return [
                name
                for name in names
                if name in by_signal and bool(self._vision_identity_status(by_signal.get(name, {}), expected_identity).get("mismatched_fields"))
            ]

        def signal_group_identity_ok(names: list[str]) -> bool:
            return all(name in by_signal and self._vision_identity_ok(by_signal.get(name, {}), expected_identity) for name in names)

        inferred = {
            "utm_pre_start": {
                "ok": self._signal_is_ok(by_signal.get("specimen_on_utm_platen", {}))
                and self._signal_is_ok(by_signal.get("fixture_alignment_ok", {}))
                and signal_group_identity_ok(pre_start_signal_names),
                "source": "vision_signal_board",
                "signals": pre_start_signal_names,
                "identity_expected": expected_identity,
                "identity_missing": bool(identity_missing_signal_names(pre_start_signal_names)),
                "identity_missing_signals": identity_missing_signal_names(pre_start_signal_names),
                "identity_mismatch": bool(identity_mismatched_signal_names(pre_start_signal_names)),
                "identity_mismatched_signals": identity_mismatched_signal_names(pre_start_signal_names),
                "freshness_missing": bool(freshness_missing_signal_names(pre_start_signal_names)),
                "freshness_missing_signals": freshness_missing_signal_names(pre_start_signal_names),
                "stale": bool(stale_signal_names(pre_start_signal_names)),
                "stale_signals": stale_signal_names(pre_start_signal_names),
            },
            "utm_motion_confirm": {
                "ok": self._signal_is_ok(by_signal.get("utm_motion_observed", {})) and signal_group_identity_ok(motion_signal_names),
                "source": "vision_signal_board",
                "signals": motion_signal_names,
                "identity_expected": expected_identity,
                "identity_missing": bool(identity_missing_signal_names(motion_signal_names)),
                "identity_missing_signals": identity_missing_signal_names(motion_signal_names),
                "identity_mismatch": bool(identity_mismatched_signal_names(motion_signal_names)),
                "identity_mismatched_signals": identity_mismatched_signal_names(motion_signal_names),
                "freshness_missing": bool(freshness_missing_signal_names(motion_signal_names)),
                "freshness_missing_signals": freshness_missing_signal_names(motion_signal_names),
                "stale": bool(stale_signal_names(motion_signal_names)),
                "stale_signals": stale_signal_names(motion_signal_names),
            },
            "utm_test_complete": {
                "ok": self._signal_is_ok(by_signal.get("utm_home_restored", {})) and signal_group_identity_ok(complete_signal_names),
                "source": "vision_signal_board",
                "signals": complete_signal_names,
                "identity_expected": expected_identity,
                "identity_missing": bool(identity_missing_signal_names(complete_signal_names)),
                "identity_missing_signals": identity_missing_signal_names(complete_signal_names),
                "identity_mismatch": bool(identity_mismatched_signal_names(complete_signal_names)),
                "identity_mismatched_signals": identity_mismatched_signal_names(complete_signal_names),
                "freshness_missing": bool(freshness_missing_signal_names(complete_signal_names)),
                "freshness_missing_signals": freshness_missing_signal_names(complete_signal_names),
                "stale": bool(stale_signal_names(complete_signal_names)),
                "stale_signals": stale_signal_names(complete_signal_names),
            },
        }
        required = ["utm_pre_start", "utm_motion_confirm", "utm_test_complete"]
        checks: dict[str, dict[str, Any]] = {}
        blocking: list[str] = []
        for check_id in required:
            checks[check_id] = explicit.get(check_id) or inferred[check_id]
            if not checks[check_id].get("ok"):
                if checks[check_id].get("stale"):
                    blocking.append(f"VISION_{check_id.upper()}_STALE")
                elif checks[check_id].get("freshness_missing"):
                    blocking.append(f"VISION_{check_id.upper()}_FRESHNESS_REQUIRED")
                elif checks[check_id].get("identity_mismatch"):
                    blocking.append(f"VISION_{check_id.upper()}_IDENTITY_MISMATCH")
                elif checks[check_id].get("identity_missing"):
                    blocking.append(f"VISION_{check_id.upper()}_IDENTITY_REQUIRED")
                else:
                    blocking.append(f"VISION_{check_id.upper()}_REQUIRED")
        return {
            "required": required,
            "checks": checks,
            "all_required_ok": not blocking,
            "blocking_reasons": blocking,
            "evidence_frame_ids": sorted(set(evidence_frames)),
        }

    @staticmethod
    def _equipment_alert_component(failure_code: str, *, is_utm: bool) -> tuple[str, str, str]:
        code = str(failure_code or "EQUIPMENT_VERIFICATION_FAILED")
        if code.startswith("VISION_"):
            return "vision", "utm_physical_cross_check", "utm_camera_cross_check"
        if code.startswith("PYAUTOGUI_"):
            return "equipment", "windows_pyautogui_bridge", "windows_pyautogui"
        if code in {"UTM_EXPORT_FILE_MISSING", "UTM_DATA_TIMEOUT"} or code.startswith("UTM_DATA_"):
            return "utm", "utm_data_export", "utm_export_file"
        if "REQUEST_LOG" in code:
            return "equipment", "windows_pyautogui_request_audit", "windows_pyautogui"
        if code == "UTM_NO_MOTION_AFTER_START":
            return "utm", "utm_motion", "utm_crosshead"
        if code == "UTM_PROTOCOL_REQUIRED" or is_utm:
            return "utm", "utm_protocol", "utm_controller"
        return "equipment", "lab_equipment_protocol", "lab_equipment"

    def _build_hardware_alert(
        self,
        *,
        state: OrchestratorState,
        verified: bool,
        failure_code: str | None,
        blocking_reasons: list[str],
        report: dict[str, Any],
        packet: dict[str, Any],
        handoff: dict[str, Any],
        is_utm: bool,
    ) -> dict[str, Any] | None:
        if verified:
            return None
        code = str(failure_code or (blocking_reasons[0] if blocking_reasons else "EQUIPMENT_VERIFICATION_FAILED"))
        device_class, component, device = self._equipment_alert_component(code, is_utm=is_utm)
        test_like = self._test_like_mode(state)
        severity = "critical" if state.mode == Mode.LIVE and not test_like and code in {"UTM_NO_MOTION_AFTER_START", "VISION_UTM_MOTION_CONFIRM_REQUIRED"} else "blocking"
        alert_id_seed = f"{state.run_id}:{state.loop_count}:{component}:{code}"
        alert_id = "equipment-alert-" + hashlib.sha1(alert_id_seed.encode("utf-8")).hexdigest()[:12]
        created_at = datetime.now(timezone.utc).isoformat()
        risk_vector = {
            "equipment": 0.9 if device_class in {"equipment", "utm"} else 0.4,
            "vision": 0.9 if device_class == "vision" else 0.3,
            "data_integrity": 0.9 if "DATA" in code or "EXPORT" in code else 0.5,
            "operator_review": 1.0,
        }
        guardian_decision = {
            "schema": "guardian_decision.v1",
            "decision_id": alert_id,
            "decision": "safe_stop" if severity == "critical" else "recover",
            "reason_code": code,
            "risk_score": 0.95 if severity == "critical" else 0.82,
            "risk_vector": risk_vector,
            "dominant_risks": [key for key, value in risk_vector.items() if value >= 0.8],
            "requires_human_approval": True,
            "recommended_action": "safe_stop" if severity == "critical" else "operator_review_and_retry",
        }
        incident_record = {
            "schema": "incident_record.v1",
            "incident_id": alert_id,
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "stage": "equipment",
            "source": "lab_equipment_agent",
            "risk_class": device_class,
            "component": component,
            "severity": severity,
            "reason_code": code,
            "failure_code": code,
            "message": "Lab Equipment verification failed before Analysis handoff.",
            "blocking_reasons": list(blocking_reasons),
            "detected_by": ["equipment_agent", "guardian_sidecar_contract"],
            "guardian_decision": guardian_decision["decision"],
            "corrective_action": "Check UTM screen locator, Vision cross-check, export file, and rerun the registered UTM protocol.",
            "artifact_refs": list(packet.get("evidence_refs", [])),
            "failure_retry_table": report.get("failure_retry_table", []),
            "created_at": created_at,
        }
        contract = {
            "schema_version": "guardian_contract.v1",
            "run_id": state.run_id,
            "loop_id": int(state.loop_count),
            "stage": "equipment",
            "status": "blocked",
            "confidence": 1.0,
            "artifact_refs": list(packet.get("evidence_refs", [])),
            "provenance_refs": [alert_id],
            "requires_human_approval": True,
            "ok_for_next_stage": False,
            "ok_for_bo": False,
            "failure_code": code,
            "risk_flags": [code, device_class, component],
        }
        return {
            "schema": "hardware_alert.v1",
            "alert_id": alert_id,
            "device_class": device_class,
            "device": device,
            "component": component,
            "workspace": "equipment",
            "tool": "utm.run_protocol" if report.get("bridge", {}).get("provider") == "utm_direct" else "equipment.pyautogui.run",
            "agent": self.name,
            "stage": "equipment",
            "workflow": "utm_compression_protocol" if is_utm else "equipment_macro_setup",
            "severity": severity,
            "failure_code": code,
            "status": "blocked",
            "message": "Lab Equipment verification blocked Analysis handoff.",
            "blocks_workflow": True,
            "requires_ack": True,
            "guardian_route_hint": "stop" if severity == "critical" else "recover",
            "reason_code": code,
            "risk_score": guardian_decision["risk_score"],
            "risk_vector": risk_vector,
            "guardian_contract": contract,
            "guardian_decision": guardian_decision,
            "incident_record": incident_record,
            "recovery_hint": incident_record["corrective_action"],
            "equipment_handoff": handoff,
            "created_at": created_at,
        }

    def _build_equipment_package(
        self,
        *,
        state: OrchestratorState,
        final_result: dict[str, Any],
        run_payload: dict[str, Any],
        tool_results: list[dict[str, Any]],
        program_catalog: set[str],
        source_stage_context: dict[str, Any],
    ) -> dict[str, Any]:
        equipment_result = dict(final_result)
        bridge_provider = str(equipment_result.get("bridge") or run_payload.get("bridge") or "windows_pyautogui")
        program_id = str(run_payload.get("program_id") or equipment_result.get("program_id") or "")
        sequence_id = str(run_payload.get("sequence_id") or equipment_result.get("sequence_id") or f"equipment-{state.run_id}")
        source_specimen = source_stage_context.get("specimen") if isinstance(source_stage_context.get("specimen"), dict) else {}
        expected_request_run_id = str(state.run_id or "")
        expected_request_sequence_id = sequence_id
        expected_request_specimen_id = str(source_specimen.get("specimen_id") or state.current_experiment_spec.get("specimen_id") or "")
        expected_request_program_id = program_id
        is_utm = self._is_utm_program(program_id) or str(run_payload.get("program_type") or "") == "utm_protocol"
        test_like = self._test_like_mode(state)
        preconditions = self._equipment_preconditions(state=state, source_stage_context=source_stage_context)
        vision_requests = self._equipment_vision_requests(state=state, source_stage_context=source_stage_context)
        vision_cross_checks = self._equipment_vision_cross_checks(state=state, source_stage_context=source_stage_context)
        data_path = self._result_file_path(equipment_result)
        if test_like and is_utm and bool(equipment_result.get("ok", False)) and not data_path:
            specimen = source_stage_context.get("specimen") if isinstance(source_stage_context.get("specimen"), dict) else {}
            artifact = self._write_test_utm_csv(
                state=state,
                specimen_id=str(specimen.get("specimen_id") or state.current_experiment_spec.get("specimen_id") or "specimen-test"),
                program_id=program_id,
            )
            equipment_result.setdefault("output_artifacts", []).append(artifact)
            equipment_result["result_file"] = artifact["path"]
            equipment_result["utm_csv_path"] = artifact["path"]
            equipment_result["data_integrity"] = artifact
            equipment_result["data_acquisition"] = {
                "status": "pulled_to_linux",
                "save_method": "synthetic_test_export",
                "save_attempted_by_agent": True,
                "save_confirmation_screen_ok": True,
                "windows_path": artifact["windows_path"],
                "linux_path": artifact["path"],
                "sha256": artifact.get("sha256", ""),
                "size_bytes": artifact.get("size_bytes", 0),
                "row_count_probe": artifact.get("row_count_probe", 0),
                "columns_probe": artifact.get("columns_probe", []),
            }
            equipment_result["cross_checks"] = {
                "screen_started": True,
                "physical_motion_started": True,
                "save_completed": True,
                "data_file_created": True,
                "data_parse_probe_ok": True,
                "save_export_responsibility_ok": True,
            }
            data_path = str(artifact["path"])

        probe = self._probe_csv_file(data_path) if data_path else {"ok": False, "failure_code": "UTM_EXPORT_FILE_MISSING"}
        if data_path and probe.get("ok"):
            equipment_result.setdefault("result_file", data_path)
            equipment_result.setdefault("utm_csv_path", data_path)
        screen_checks = equipment_result.get("screen_checks") if isinstance(equipment_result.get("screen_checks"), list) else []
        if not screen_checks:
            screen_checks = [
                {"checkpoint": "before_start", "ok": bool(equipment_result.get("ok")), "state": "observed" if equipment_result.get("ok") else "unknown", "screenshot_artifact": ""}
            ]
        physical_checks = equipment_result.get("physical_checks") if isinstance(equipment_result.get("physical_checks"), dict) else {}
        if not physical_checks:
            physical_checks = {
                "vision_motion_confirmed": bool(test_like and is_utm),
                "specimen_alignment_ok": bool(test_like and is_utm),
                "fixture_safe_to_access": bool(test_like and is_utm),
                "evidence_frame_ids": [],
                "simulated": test_like and is_utm,
            }
        if is_utm:
            physical_checks["vision_cross_checks"] = vision_cross_checks
            physical_checks["evidence_frame_ids"] = sorted(
                set([str(item) for item in physical_checks.get("evidence_frame_ids", [])] + vision_cross_checks.get("evidence_frame_ids", []))
            )
            if state.mode == Mode.LIVE and not test_like:
                physical_checks["vision_motion_confirmed"] = bool(vision_cross_checks["checks"].get("utm_motion_confirm", {}).get("ok"))
                physical_checks["specimen_alignment_ok"] = bool(vision_cross_checks["checks"].get("utm_pre_start", {}).get("ok"))
                physical_checks["fixture_safe_to_access"] = bool(vision_cross_checks["checks"].get("utm_test_complete", {}).get("ok"))
        data_acquisition = equipment_result.get("data_acquisition") if isinstance(equipment_result.get("data_acquisition"), dict) else {}
        if data_acquisition:
            data_acquisition = dict(data_acquisition)
            if data_path and probe.get("ok"):
                data_acquisition.setdefault("linux_path", data_path)
                data_acquisition.setdefault("local_path", data_path)
                if str(data_acquisition.get("status") or "") in {"", "data_ready"}:
                    data_acquisition["status"] = "pulled_to_linux"
                for key in ("sha256", "size_bytes", "row_count_probe", "columns_probe", "data_quality", "failure_code", "message"):
                    if probe.get(key) not in (None, "", []):
                        data_acquisition.setdefault(key, probe.get(key))
            elif data_path and not probe.get("ok") and str(data_acquisition.get("status") or "") in {"pulled_to_linux", "data_ready", "exported_on_windows", ""}:
                data_acquisition["status"] = "pulled_to_linux_parse_failed"
                for key in ("failure_code", "message", "data_quality", "row_count_probe", "columns_probe", "missing_columns"):
                    if probe.get(key) not in (None, "", []):
                        data_acquisition[key] = probe.get(key)
        if not data_acquisition:
            data_acquisition = {
                "status": "pulled_to_linux" if probe.get("ok") else "missing",
                "save_method": "unknown",
                "save_attempted_by_agent": False,
                "save_confirmation_screen_ok": False,
                "windows_path": "",
                "linux_path": data_path,
                "sha256": probe.get("sha256", ""),
                "size_bytes": probe.get("size_bytes", 0),
                "row_count_probe": probe.get("row_count_probe", 0),
                "columns_probe": probe.get("columns_probe", []),
            }
        cross_checks = equipment_result.get("cross_checks") if isinstance(equipment_result.get("cross_checks"), dict) else {}
        screen_started = bool(cross_checks.get("screen_started", any(item.get("ok") for item in screen_checks if isinstance(item, dict))))
        physical_started = bool(cross_checks.get("physical_motion_started", physical_checks.get("vision_motion_confirmed")))
        if state.mode == Mode.LIVE and not test_like and is_utm:
            physical_started = bool(vision_cross_checks.get("all_required_ok"))
        cross_checks = {
            "screen_started": screen_started,
            "physical_motion_started": physical_started,
            "save_completed": bool(cross_checks.get("save_completed", data_acquisition.get("save_confirmation_screen_ok") or probe.get("ok"))),
            "data_file_created": bool(cross_checks.get("data_file_created", bool(data_path and Path(data_path).exists()))),
            "data_parse_probe_ok": bool(probe.get("ok")) and cross_checks.get("data_parse_probe_ok") is not False,
        }
        windows_gui_live = bool(is_utm and state.mode == Mode.LIVE and not test_like and bridge_provider == "windows_pyautogui")
        required_screen_checkpoints = ["before_start", "after_start", "after_complete"]
        screen_by_checkpoint = {
            str(item.get("checkpoint") or ""): item
            for item in screen_checks
            if isinstance(item, dict)
        }
        missing_screen_checkpoints = [
            checkpoint
            for checkpoint in required_screen_checkpoints
            if not (
                isinstance(screen_by_checkpoint.get(checkpoint), dict)
                and bool(screen_by_checkpoint[checkpoint].get("ok"))
                and bool(str(screen_by_checkpoint[checkpoint].get("screenshot_artifact") or "").strip())
            )
        ]
        screen_evidence_complete = not missing_screen_checkpoints
        linux_local_path = str(data_acquisition.get("linux_path") or data_acquisition.get("local_path") or data_path or "")
        linux_artifact_pulled = bool(
            (not windows_gui_live)
            or (
                str(data_acquisition.get("status") or "") == "pulled_to_linux"
                and bool(linux_local_path)
                and bool(data_path)
                and Path(data_path).exists()
                and bool(probe.get("ok"))
            )
        )
        save_method = str(data_acquisition.get("save_method") or "").strip()
        save_attempted_by_agent = bool(data_acquisition.get("save_attempted_by_agent"))
        save_confirmation_screen_ok = bool(data_acquisition.get("save_confirmation_screen_ok"))
        windows_export_path = str(data_acquisition.get("windows_path") or "").strip()
        recognized_save_methods = {
            "windows_export_watch",
            "manual_save_dialog",
            "export_menu",
            "simulated_bridge_export",
            "simulated_auto_export",
            "synthetic_test_export",
            "direct_backend_file",
            "synthetic_test_direct_backend",
        }
        if windows_gui_live:
            save_export_responsibility_ok = bool(
                linux_artifact_pulled
                and bool(probe.get("ok"))
                and save_method in recognized_save_methods
                and (save_attempted_by_agent or save_method in {"windows_export_watch", "simulated_bridge_export", "simulated_auto_export"})
                and (save_confirmation_screen_ok or bool(windows_export_path) or bool(linux_local_path))
            )
        else:
            save_export_responsibility_ok = bool(
                is_utm
                and bool(probe.get("ok"))
                and bool(linux_local_path or data_path)
                and save_method in recognized_save_methods
                and (save_confirmation_screen_ok or save_attempted_by_agent or bool(linux_local_path or data_path))
            )
        cross_checks["save_export_responsibility_ok"] = bool(save_export_responsibility_ok)
        vision_evidence_frame_ids = sorted({str(item) for item in physical_checks.get("evidence_frame_ids", []) if str(item or "").strip()})
        vision_evidence_complete = bool((not windows_gui_live) or (vision_cross_checks.get("all_required_ok") and vision_evidence_frame_ids))
        bridge_artifact_context = self._bridge_artifact_context(equipment_result=equipment_result, tool_results=tool_results)
        pyautogui_available = bridge_artifact_context.get("pyautogui_available")
        if pyautogui_available is None:
            pyautogui_available = bool(bridge_provider == "windows_pyautogui" and any(
                item.get("tool") == "equipment.pyautogui.health" and item.get("result", {}).get("ok")
                for item in tool_results
                if isinstance(item, dict) and isinstance(item.get("result"), dict)
            ))
        request_log_path = str(bridge_artifact_context.get("request_log_path") or "")
        request_log_event_count = int(bridge_artifact_context.get("request_log_event_count") or 0)
        request_log_recent_paths = [str(item) for item in bridge_artifact_context.get("request_log_recent_paths", []) if str(item or "").strip()]
        request_log_execute_count = int(bridge_artifact_context.get("request_log_execute_count") or 0)
        request_log_execute_seen = bool(bridge_artifact_context.get("request_log_execute_seen")) or any(path == "/execute" or path.endswith("/execute") for path in request_log_recent_paths)
        if request_log_execute_seen and request_log_execute_count <= 0:
            request_log_execute_count = 1
        request_log_last_execute_at = str(bridge_artifact_context.get("request_log_last_execute_at") or "")
        request_log_execute_payload_event_count = int(bridge_artifact_context.get("request_log_execute_payload_event_count") or 0)
        request_log_execute_result_event_count = int(bridge_artifact_context.get("request_log_execute_result_event_count") or 0)
        request_log_execute_run_ids = [str(item) for item in bridge_artifact_context.get("request_log_execute_run_ids", []) if str(item or "").strip()] if isinstance(bridge_artifact_context.get("request_log_execute_run_ids"), list) else []
        request_log_execute_sequence_ids = [str(item) for item in bridge_artifact_context.get("request_log_execute_sequence_ids", []) if str(item or "").strip()] if isinstance(bridge_artifact_context.get("request_log_execute_sequence_ids"), list) else []
        request_log_execute_specimen_ids = [str(item) for item in bridge_artifact_context.get("request_log_execute_specimen_ids", []) if str(item or "").strip()] if isinstance(bridge_artifact_context.get("request_log_execute_specimen_ids"), list) else []
        request_log_execute_program_ids = [str(item) for item in bridge_artifact_context.get("request_log_execute_program_ids", []) if str(item or "").strip()] if isinstance(bridge_artifact_context.get("request_log_execute_program_ids"), list) else []
        request_log_last_execute_context = bridge_artifact_context.get("request_log_last_execute_context") if isinstance(bridge_artifact_context.get("request_log_last_execute_context"), dict) else {}

        def _contains_identity(expected: str, observed: list[str]) -> bool:
            return not expected or expected in observed

        request_log_execute_identity_present = bool(
            request_log_execute_payload_event_count > 0
            or request_log_execute_run_ids
            or request_log_execute_sequence_ids
            or request_log_execute_specimen_ids
            or request_log_execute_program_ids
        )
        request_log_execute_identity_match = bool(
            (not windows_gui_live)
            or (
                request_log_execute_identity_present
                and _contains_identity(expected_request_sequence_id, request_log_execute_sequence_ids)
                and _contains_identity(expected_request_run_id, request_log_execute_run_ids)
                and _contains_identity(expected_request_program_id, request_log_execute_program_ids)
                and _contains_identity(expected_request_specimen_id, request_log_execute_specimen_ids)
            )
        )
        request_log_execute_identity_detail = {
            "required": bool(windows_gui_live),
            "present": bool(request_log_execute_identity_present),
            "match": bool(request_log_execute_identity_match),
            "expected": {
                "run_id": expected_request_run_id,
                "sequence_id": expected_request_sequence_id,
                "specimen_id": expected_request_specimen_id,
                "program_id": expected_request_program_id,
            },
            "observed": {
                "run_ids": request_log_execute_run_ids,
                "sequence_ids": request_log_execute_sequence_ids,
                "specimen_ids": request_log_execute_specimen_ids,
                "program_ids": request_log_execute_program_ids,
            },
        }
        request_audit_transport_available = bool(
            (not windows_gui_live)
            or (request_log_path and request_log_event_count > 0 and request_log_execute_seen)
        )
        request_audit_log_available = bool(request_audit_transport_available and request_log_execute_identity_match)
        live_evidence_audit = {
            "required_for_handoff": windows_gui_live,
            "screen_evidence": {
                "ok": bool(screen_evidence_complete),
                "required_checkpoints": required_screen_checkpoints,
                "observed_checkpoints": [checkpoint for checkpoint in required_screen_checkpoints if checkpoint not in missing_screen_checkpoints],
                "missing_checkpoints": missing_screen_checkpoints,
            },
            "linux_artifact_pull": {
                "ok": bool(linux_artifact_pulled),
                "status": data_acquisition.get("status", ""),
                "linux_path": linux_local_path,
                "data_path_exists": bool(data_path and Path(data_path).exists()),
                "parse_probe_ok": bool(probe.get("ok")),
            },
            "save_export": {
                "ok": bool(save_export_responsibility_ok),
                "save_method": save_method,
                "save_attempted_by_agent": bool(save_attempted_by_agent),
                "save_confirmation_screen_ok": bool(save_confirmation_screen_ok),
                "windows_path": windows_export_path,
                "linux_path": linux_local_path,
                "recognized_save_method": save_method in recognized_save_methods,
            },
            "vision_evidence": {
                "ok": bool(vision_evidence_complete),
                "all_required_ok": bool(vision_cross_checks.get("all_required_ok")),
                "evidence_frame_ids": vision_evidence_frame_ids,
            },
            "request_audit_log": {
                "ok": bool(request_audit_log_available),
                "path": request_log_path,
                "event_count": request_log_event_count,
                "recent_paths": request_log_recent_paths,
                "execute_event_seen": bool(request_log_execute_seen),
                "execute_event_count": request_log_execute_count,
                "execute_payload_event_count": request_log_execute_payload_event_count,
                "execute_result_event_count": request_log_execute_result_event_count,
                "execute_run_ids": request_log_execute_run_ids,
                "execute_sequence_ids": request_log_execute_sequence_ids,
                "execute_specimen_ids": request_log_execute_specimen_ids,
                "execute_program_ids": request_log_execute_program_ids,
                "last_execute_context": request_log_last_execute_context,
                "last_execute_at": request_log_last_execute_at,
                "execute_identity_required": bool(windows_gui_live),
                "execute_identity_present": bool(request_log_execute_identity_present),
                "execute_identity_match": bool(request_log_execute_identity_match),
                "execute_identity_detail": request_log_execute_identity_detail,
            },
        }
        if windows_gui_live:
            cross_checks["screen_evidence_complete"] = bool(screen_evidence_complete)
            cross_checks["linux_artifact_pulled"] = bool(linux_artifact_pulled)
            cross_checks["vision_evidence_complete"] = bool(vision_evidence_complete)
            cross_checks["request_audit_log_available"] = bool(request_audit_log_available)
            cross_checks["request_audit_execute_identity_match"] = bool(request_log_execute_identity_match)

        blocking_reasons = list(preconditions.get("blocking_reasons", []))
        if not is_utm:
            blocking_reasons.append("UTM_PROTOCOL_REQUIRED")
        if is_utm and not cross_checks["data_parse_probe_ok"]:
            blocking_reasons.append(str(probe.get("failure_code") or "UTM_DATA_PARSE_FAILED"))
        if is_utm and state.mode == Mode.LIVE and not test_like and not vision_cross_checks.get("all_required_ok"):
            blocking_reasons.extend(str(item) for item in vision_cross_checks.get("blocking_reasons", []))
        if is_utm and state.mode == Mode.LIVE and not test_like and not cross_checks["physical_motion_started"]:
            blocking_reasons.append("UTM_NO_MOTION_AFTER_START")
        if windows_gui_live and not screen_evidence_complete:
            blocking_reasons.append("UTM_SCREEN_EVIDENCE_INCOMPLETE")
        if windows_gui_live and not linux_artifact_pulled:
            blocking_reasons.append("UTM_LINUX_ARTIFACT_PULL_REQUIRED")
        if windows_gui_live and not save_export_responsibility_ok:
            blocking_reasons.append("UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED")
        if windows_gui_live and not vision_evidence_complete and vision_cross_checks.get("all_required_ok"):
            blocking_reasons.append("UTM_VISION_EVIDENCE_FRAMES_REQUIRED")
        if windows_gui_live and not request_audit_log_available:
            if request_audit_transport_available and not request_log_execute_identity_match:
                blocking_reasons.append("UTM_REQUEST_LOG_EXECUTE_IDENTITY_REQUIRED")
            elif request_log_path and request_log_event_count > 0 and not request_log_execute_seen:
                blocking_reasons.append("UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED")
            else:
                blocking_reasons.append("UTM_REQUEST_LOG_REQUIRED")
        blocking_reasons = list(dict.fromkeys(str(item) for item in blocking_reasons if str(item or "").strip()))
        verified = bool(equipment_result.get("ok", False)) and is_utm and not blocking_reasons and all(cross_checks.values())
        failure_code = equipment_result.get("failure_code")
        if not verified:
            failure_code = failure_code or (blocking_reasons[0] if blocking_reasons else "EQUIPMENT_VERIFICATION_FAILED")
            equipment_result["ok"] = False
            equipment_result["status"] = "blocked"
            equipment_result["failure_code"] = failure_code
            equipment_result.setdefault("message", "Lab Equipment verification did not satisfy screen/physical/data handoff gates.")
        else:
            equipment_result["ok"] = True
            equipment_result["status"] = "verified_complete"
            equipment_result["failure_code"] = None
        equipment_result["program_id"] = program_id
        equipment_result["sequence_id"] = sequence_id
        equipment_result["vision_requests"] = vision_requests
        equipment_result["vision_cross_checks"] = vision_cross_checks
        equipment_result["screen_checks"] = screen_checks
        equipment_result["physical_checks"] = physical_checks
        equipment_result["data_acquisition"] = data_acquisition
        equipment_result["cross_checks"] = cross_checks

        artifact_evidence = self._artifact_evidence_refs(equipment_result=equipment_result, data_path=data_path, screen_checks=screen_checks)
        failure_retry_table = self._failure_retry_table(
            equipment_result=equipment_result,
            blocking_reasons=blocking_reasons,
            failure_code=str(failure_code or "") if failure_code else None,
        )
        retry_count = sum(1 for item in failure_retry_table if str(item.get("fallback_macro") or ""))
        recovery = {
            "status": "not_required" if verified else "operator_review_required",
            "retry_count": retry_count,
            "fallback_macros": sorted({str(item.get("fallback_macro")) for item in failure_retry_table if item.get("fallback_macro")}),
            "operator_intervention_required": bool(not verified and failure_retry_table),
            "failure_code": None if verified else failure_code,
            "recommended_action": "analysis_agent" if verified else self._recommended_recovery("HANDOFF_GATE", str(failure_code or (blocking_reasons[0] if blocking_reasons else ""))),
        }

        specimen = source_stage_context.get("specimen") if isinstance(source_stage_context.get("specimen"), dict) else {}
        report = {
            "schema": "equipment_report.v1",
            "report_version": "lab_equipment_utm_visual_control_v1",
            "run_id": state.run_id,
            "mode": self._effective_runtime_mode(state),
            "task_id": "utm_compression_test" if is_utm else "equipment_macro_setup",
            "bridge": {
                "provider": bridge_provider,
                "connection_status": (
                    "ready"
                    if any(item.get("tool") == "equipment.pyautogui.health" and item.get("result", {}).get("ok") for item in tool_results)
                    else "ready" if bridge_provider == "utm_direct" and equipment_result.get("ok")
                    else "blocked" if bridge_provider == "utm_direct"
                    else "unknown"
                ),
                "pyautogui_available": bool(pyautogui_available),
                "pyautogui_failsafe": bridge_artifact_context.get("pyautogui_failsafe", ""),
                "pyautogui_pause": bridge_artifact_context.get("pyautogui_pause", ""),
                "pyautogui_simulated": bridge_artifact_context.get("pyautogui_simulated", ""),
                "pyautogui_error": bridge_artifact_context.get("pyautogui_error", ""),
                "live_execute_enabled": state.mode == Mode.LIVE and not test_like and (bridge_provider == "windows_pyautogui" or bool(equipment_result.get("ok"))),
                "bridge_url": bridge_artifact_context.get("bridge_url", ""),
                "bridge_url_host": bridge_artifact_context.get("bridge_host", ""),
                "remote_server_version": bridge_artifact_context.get("server_version", ""),
                "remote_script_version": bridge_artifact_context.get("script_version", ""),
                "client_latency_ms": bridge_artifact_context.get("client_latency_ms", ""),
                "artifact_root": bridge_artifact_context.get("artifact_root", ""),
                "request_log_path": bridge_artifact_context.get("request_log_path", ""),
                "request_log_event_count": bridge_artifact_context.get("request_log_event_count", 0),
                "request_log_recent_paths": bridge_artifact_context.get("request_log_recent_paths", []),
                "request_log_execute_seen": bool(request_log_execute_seen),
                "request_log_execute_count": request_log_execute_count,
                "request_log_execute_payload_event_count": request_log_execute_payload_event_count,
                "request_log_execute_result_event_count": request_log_execute_result_event_count,
                "request_log_execute_run_ids": request_log_execute_run_ids,
                "request_log_execute_sequence_ids": request_log_execute_sequence_ids,
                "request_log_execute_specimen_ids": request_log_execute_specimen_ids,
                "request_log_execute_program_ids": request_log_execute_program_ids,
                "request_log_last_execute_context": request_log_last_execute_context,
                "request_log_last_execute_at": request_log_last_execute_at,
                "request_log_execute_identity_required": bool(windows_gui_live),
                "request_log_execute_identity_present": bool(request_log_execute_identity_present),
                "request_log_execute_identity_match": bool(request_log_execute_identity_match),
                "request_log_execute_identity_detail": request_log_execute_identity_detail,
                "locator_root": bridge_artifact_context.get("locator_root", ""),
                "utm_export_root": bridge_artifact_context.get("utm_export_root", ""),
            },
            "preconditions": preconditions,
            "control_plan": {
                "program_id": program_id,
                "locator_backend": str(run_payload.get("locator_backend") or "image" if is_utm else ""),
                "macro_version": "v1" if program_id else "",
                "max_retries": 1 if is_utm else 0,
                "profile": equipment_result.get("control_profile") if isinstance(equipment_result.get("control_profile"), dict) else {},
            },
            "vision_requests": vision_requests,
            "vision_cross_checks": vision_cross_checks,
            "screen_checks": screen_checks,
            "physical_checks": physical_checks,
            "data_acquisition": data_acquisition,
            "cross_checks": cross_checks,
            "artifact_records": artifact_evidence["artifact_records"],
            "artifact_refs": artifact_evidence["artifact_refs"],
            "screen_evidence_refs": artifact_evidence["screen_evidence_refs"],
            "data_evidence_refs": artifact_evidence["data_evidence_refs"],
            "artifact_pull": equipment_result.get("artifact_pull") if isinstance(equipment_result.get("artifact_pull"), dict) else {},
            "live_evidence_audit": live_evidence_audit,
            "failure_retry_table": failure_retry_table,
            "recovery": recovery,
            "decision": {
                "equipment_status": "verified_complete" if verified else "blocked",
                "handoff_status": "ready_for_analysis" if verified else "blocked",
                "failure_code": None if verified else failure_code,
                "blocking_reasons": blocking_reasons,
                "recommended_next_agent": "analysis_agent" if verified else "guardian_agent",
            },
        }

        tool_sequence: list[dict[str, Any]] = []
        for item in tool_results:
            if not isinstance(item, dict):
                continue
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            artifacts = result.get("output_artifacts") if isinstance(result.get("output_artifacts"), list) else []
            tool_sequence.append(
                {
                    "tool": str(item.get("tool") or ""),
                    "ok": bool(result.get("ok")),
                    "status": str(result.get("status") or ""),
                    "failure_code": result.get("failure_code"),
                    "program_id": str(result.get("program_id") or ""),
                    "bridge": str(result.get("bridge") or ""),
                    "artifact_count": len(artifacts),
                }
            )
        screen_passed = sum(1 for item in screen_checks if isinstance(item, dict) and item.get("ok"))
        visual_verification = {
            "screen_checks_passed": screen_passed,
            "screen_checks_total": len(screen_checks),
            "screen_started": bool(cross_checks.get("screen_started")),
            "screen_evidence_complete": bool(screen_evidence_complete),
            "required_checkpoints": required_screen_checkpoints,
            "missing_checkpoints": missing_screen_checkpoints,
            "checkpoints": [str(item.get("checkpoint") or "") for item in screen_checks if isinstance(item, dict)],
            "screen_evidence_refs": artifact_evidence["screen_evidence_refs"],
        }
        physical_verification = {
            "all_required_ok": bool(vision_cross_checks.get("all_required_ok")),
            "vision_motion_confirmed": bool(physical_checks.get("vision_motion_confirmed")),
            "specimen_alignment_ok": bool(physical_checks.get("specimen_alignment_ok")),
            "fixture_safe_to_access": bool(physical_checks.get("fixture_safe_to_access")),
            "evidence_frame_ids": vision_evidence_frame_ids,
            "blocking_reasons": list(vision_cross_checks.get("blocking_reasons", [])) if isinstance(vision_cross_checks.get("blocking_reasons"), list) else [],
            "checks": vision_cross_checks.get("checks", {}),
        }
        data_ledger = {
            "status": data_acquisition.get("status", ""),
            "save_method": save_method,
            "save_attempted_by_agent": bool(save_attempted_by_agent),
            "save_confirmation_screen_ok": bool(save_confirmation_screen_ok),
            "save_export_responsibility_ok": bool(save_export_responsibility_ok),
            "recognized_save_method": save_method in recognized_save_methods,
            "windows_path": windows_export_path,
            "linux_path": linux_local_path,
            "sha256": data_acquisition.get("sha256", probe.get("sha256", "")),
            "size_bytes": data_acquisition.get("size_bytes", probe.get("size_bytes", 0)),
            "row_count_probe": data_acquisition.get("row_count_probe", probe.get("row_count_probe", 0)),
            "columns_probe": data_acquisition.get("columns_probe", probe.get("columns_probe", [])),
            "parse_ready": bool(cross_checks.get("data_parse_probe_ok")),
            "failure_code": probe.get("failure_code"),
            "data_quality": data_acquisition.get("data_quality", probe.get("data_quality", {})),
            "data_evidence_refs": artifact_evidence["data_evidence_refs"],
            "artifact_records": artifact_evidence["artifact_records"],
        }
        handoff_gate = {
            "handoff_status": "ready_for_analysis" if verified else "blocked",
            "equipment_status": "verified_complete" if verified else "blocked",
            "failure_code": None if verified else failure_code,
            "ready_for_analysis": bool(verified),
            "required_gates": dict(cross_checks),
            "blocking_reasons": list(blocking_reasons),
            "recommended_next_agent": "analysis_agent" if verified else "guardian_agent",
            "live_evidence_audit": live_evidence_audit,
        }
        safety_gate = {
            "guardian_status": "allow" if verified else "block",
            "blocks_workflow": not verified,
            "requires_human_approval": not verified,
            "hardware_alert_count": 0,
            "active_hardware_alert": {},
            "incident_records": [],
            "blocked_commands": list(blocking_reasons),
            "emergency_stop_evidence": {
                "safe_stop_recommended": False,
                "route_hint": "",
                "corrective_action": "",
            },
        }
        report.update(
            {
                "control_trace": {
                    "bridge_provider": bridge_provider,
                    "connection_status": report["bridge"].get("connection_status", ""),
                    "program_id": program_id,
                    "sequence_id": sequence_id,
                    "macro_version": report["control_plan"].get("macro_version", ""),
                    "locator_backend": report["control_plan"].get("locator_backend", ""),
                    "tool_result_count": len(tool_sequence),
                    "tool_sequence": tool_sequence,
                },
                "visual_verification": visual_verification,
                "physical_verification": physical_verification,
                "data_ledger": data_ledger,
                "artifact_ledger": {
                    "artifact_records": artifact_evidence["artifact_records"],
                    "artifact_refs": artifact_evidence["artifact_refs"],
                    "screen_evidence_refs": artifact_evidence["screen_evidence_refs"],
                    "data_evidence_refs": artifact_evidence["data_evidence_refs"],
                    "screen_evidence_count": len(artifact_evidence["screen_evidence_refs"]),
                    "data_evidence_count": len(artifact_evidence["data_evidence_refs"]),
                },
                "handoff_gate": handoff_gate,
                "safety_gate": safety_gate,
            }
        )
        packet = {
            "schema": "utm_data_ready.v1",
            "run_id": state.run_id,
            "loop_id": state.loop_count,
            "specimen_id": str(specimen.get("specimen_id") or state.current_experiment_spec.get("specimen_id") or ""),
            "producer_agent": self.name,
            "consumer_agent": "analysis_agent",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "ready" if verified else "blocked",
            "evidence_refs": artifact_evidence["artifact_refs"],
            "data_evidence_refs": artifact_evidence["data_evidence_refs"],
            "screen_evidence_refs": artifact_evidence["screen_evidence_refs"],
            "live_evidence_audit": live_evidence_audit,
            "save_export_responsibility_ok": bool(save_export_responsibility_ok),
            "save_export": live_evidence_audit["save_export"],
            "artifact_pull": equipment_result.get("artifact_pull") if isinstance(equipment_result.get("artifact_pull"), dict) else {},
            "bridge_request_log_ref": bridge_artifact_context.get("request_log_path", ""),
            "bridge_request_log_execute_event_seen": bool(request_log_execute_seen),
            "bridge_request_log_execute_run_ids": request_log_execute_run_ids,
            "bridge_request_log_execute_sequence_ids": request_log_execute_sequence_ids,
            "bridge_request_log_execute_specimen_ids": request_log_execute_specimen_ids,
            "bridge_request_log_execute_program_ids": request_log_execute_program_ids,
            "bridge_request_log_execute_identity_match": bool(request_log_execute_identity_match),
            "bridge_request_log_execute_identity_detail": request_log_execute_identity_detail,
            "guardian_status": "allow" if verified else "block",
            "decisions": [report["decision"]],
            "warnings": blocking_reasons,
            "next_action": "analysis_agent" if verified else "guardian_review",
            "equipment_report": report,
            "control_trace": report["control_trace"],
            "visual_verification": visual_verification,
            "physical_verification": physical_verification,
            "data_ledger": data_ledger,
            "handoff_gate": handoff_gate,
            "safety_gate": safety_gate,
            "vision_requests": vision_requests,
            "vision_cross_checks": vision_cross_checks,
            "result_file": data_path,
        }
        handoff = {
            "schema": "utm_data_ready.v1",
            "status": "ready_for_analysis" if verified else "blocked",
            "bridge": bridge_provider,
            "program_id": program_id,
            "sequence_id": sequence_id,
            "result_file": data_path,
            "utm_csv_path": data_path,
            "failure_code": None if verified else failure_code,
            "data_parse_probe_ok": bool(probe.get("ok")),
            "artifact_refs": artifact_evidence["artifact_refs"],
            "screen_evidence_refs": artifact_evidence["screen_evidence_refs"],
            "data_evidence_refs": artifact_evidence["data_evidence_refs"],
            "live_evidence_audit": live_evidence_audit,
            "save_export_responsibility_ok": bool(save_export_responsibility_ok),
            "save_export": live_evidence_audit["save_export"],
            "data_ledger": data_ledger,
            "handoff_gate": handoff_gate,
            "safety_gate": safety_gate,
            "bridge_request_log_ref": bridge_artifact_context.get("request_log_path", ""),
            "bridge_request_log_execute_event_seen": bool(request_log_execute_seen),
            "bridge_request_log_execute_run_ids": request_log_execute_run_ids,
            "bridge_request_log_execute_sequence_ids": request_log_execute_sequence_ids,
            "bridge_request_log_execute_specimen_ids": request_log_execute_specimen_ids,
            "bridge_request_log_execute_program_ids": request_log_execute_program_ids,
            "bridge_request_log_execute_identity_match": bool(request_log_execute_identity_match),
            "bridge_request_log_execute_identity_detail": request_log_execute_identity_detail,
        }
        hardware_alert = self._build_hardware_alert(
            state=state,
            verified=verified,
            failure_code=str(failure_code or "") if failure_code else None,
            blocking_reasons=blocking_reasons,
            report=report,
            packet=packet,
            handoff=handoff,
            is_utm=is_utm,
        )
        hardware_alerts = [hardware_alert] if isinstance(hardware_alert, dict) else []
        if hardware_alert:
            safety_gate.update(
                {
                    "guardian_status": "block",
                    "blocks_workflow": True,
                    "requires_human_approval": bool(hardware_alert.get("requires_ack", True)),
                    "hardware_alert_count": 1,
                    "active_hardware_alert": hardware_alert,
                    "incident_records": [hardware_alert["incident_record"]],
                    "emergency_stop_evidence": {
                        "safe_stop_recommended": hardware_alert.get("guardian_route_hint") == "stop",
                        "route_hint": str(hardware_alert.get("guardian_route_hint") or ""),
                        "corrective_action": str(hardware_alert.get("incident_record", {}).get("corrective_action") or "") if isinstance(hardware_alert.get("incident_record"), dict) else "",
                    },
                }
            )
            report["safety_gate"] = safety_gate
            report["handoff_gate"] = handoff_gate
            report["hardware_alert"] = hardware_alert
            report["hardware_alerts"] = hardware_alerts
            report["incident_records"] = [hardware_alert["incident_record"]]
            packet["hardware_alert"] = hardware_alert
            packet["safety_gate"] = safety_gate
            packet["handoff_gate"] = handoff_gate
            handoff["safety_gate"] = safety_gate
            handoff["handoff_gate"] = handoff_gate
            packet["guardian_status"] = "block"
            packet["warnings"] = sorted(set([*packet.get("warnings", []), hardware_alert["failure_code"]]))
            equipment_result["hardware_alert"] = hardware_alert
        return {
            "equipment_result": equipment_result,
            "equipment_report": report,
            "utm_data_ready": packet,
            "equipment_handoff": handoff,
            "hardware_alert": hardware_alert,
            "hardware_alerts": hardware_alerts,
            "incident_records": [hardware_alert["incident_record"]] if hardware_alert else [],
            "verified": verified,
        }

    @staticmethod
    def _direct_utm_config_from_spec(state: OrchestratorState) -> dict[str, Any]:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        sources: list[dict[str, Any]] = []
        for key in ("direct_utm", "utm", "lab_equipment", "equipment"):
            value = spec.get(key)
            if isinstance(value, dict):
                sources.append(value)
        sources.append(spec)
        accepted = {
            "profile",
            "program_id",
            "result_file",
            "result_path",
            "csv_path",
            "utm_csv_path",
            "direct_backend_configured",
            "allow_live_direct_backend",
        }
        alias = {
            "result_path": "result_file",
            "csv_path": "result_file",
            "utm_result_file": "result_file",
            "backend_configured": "direct_backend_configured",
            "enabled": "direct_backend_configured",
        }
        payload: dict[str, Any] = {}
        for source in sources:
            for key, value in source.items():
                normalized = alias.get(str(key), str(key))
                if normalized in accepted and value not in (None, ""):
                    payload[normalized] = value
        if payload.get("result_file") and not payload.get("utm_csv_path"):
            payload["utm_csv_path"] = payload["result_file"]
        return payload

    async def _legacy_utm(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        test_like = self._test_like_mode(state)
        profile = "test_profile" if test_like or state.mode.value != "live" else "live_profile"
        timeout_s = 30.0 if test_like else None
        manual_context = self._manual_context_for_state(state, purpose="procedure")
        manual_audit = manual_context_audit(manual_context)
        try:
            protocol = await ctx.complete(
                "tool_formatting",
                build_manual_grounded_prompt(
                    f"Format UTM run command profile={profile} with concise equipment-safe options.",
                    manual_context,
                ),
                timeout_s=timeout_s,
            )
            protocol_note = protocol.text[:220]
        except Exception as exc:
            if test_like:
                protocol_note = f"E2B degraded in test mode: {exc.__class__.__name__}"
            else:
                protocol_note = f"Direct UTM live path blocked before LLM formatting completed: {exc.__class__.__name__}"
        base_payload = self._base_run_payload(state)
        source_stage_context = base_payload["source_stage_context"]
        specimen = source_stage_context.get("specimen") if isinstance(source_stage_context.get("specimen"), dict) else {}
        direct_config = self._direct_utm_config_from_spec(state)
        payload = {
            "profile": str(direct_config.get("profile") or profile),
            "runtime_mode": self._effective_runtime_mode(state),
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "specimen_id": str(specimen.get("specimen_id") or state.current_experiment_spec.get("specimen_id") or "specimen-test"),
            "program_id": str(direct_config.get("program_id") or self._UTM_DEFAULT_PROGRAM),
        }
        payload.update({key: value for key, value in direct_config.items() if key not in {"profile", "program_id"}})
        response = ctx.tools.call("utm.run_protocol", payload)
        tool_results = [{"tool": "utm.run_protocol", "result": response}]
        package = self._build_equipment_package(
            state=state,
            final_result=response if isinstance(response, dict) else {},
            run_payload=response if isinstance(response, dict) else payload,
            tool_results=tool_results,
            program_catalog={self._UTM_DEFAULT_PROGRAM},
            source_stage_context=source_stage_context,
        )
        bridge = str(response.get("bridge") or "utm_direct") if isinstance(response, dict) else "utm_direct"
        return AgentResult(
            success=bool(package["verified"]),
            summary="Legacy/direct UTM protocol verified" if package["verified"] else "Legacy/direct UTM protocol blocked before analysis handoff",
            data={
                "equipment_result": package["equipment_result"],
                "protocol_note": protocol_note,
                "manual_context": manual_audit,
                "equipment_bridge": bridge,
                "tool_results": tool_results,
                "tool_plan": [{"tool": "utm.run_protocol", "payload": payload}],
                "program_catalog": [self._UTM_DEFAULT_PROGRAM],
                "source_stage_context": source_stage_context,
                "equipment_report": package["equipment_report"],
                "utm_data_ready": package["utm_data_ready"],
                "handoff_packet": package["utm_data_ready"],
                "decisions": [package["equipment_report"]["decision"]],
                "metrics": {
                    "screen_checks_passed": bool(package["equipment_report"]["cross_checks"].get("screen_started")),
                    "physical_motion_confirmed": bool(package["equipment_report"]["cross_checks"].get("physical_motion_started")),
                    "data_parse_probe_ok": bool(package["equipment_report"]["cross_checks"].get("data_parse_probe_ok")),
                    "row_count_probe": package["equipment_report"]["data_acquisition"].get("row_count_probe", 0),
                },
                "evidence_refs": package["utm_data_ready"].get("evidence_refs", []),
                "hardware_alert": package.get("hardware_alert"),
                "hardware_alerts": package.get("hardware_alerts", []),
                "incident_records": package.get("incident_records", []),
                "equipment_handoff": package["equipment_handoff"],
            },
        )

    @staticmethod
    def _equipment_skill_request(state: OrchestratorState) -> dict[str, Any]:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        value = spec.get("equipment_skill")
        if not isinstance(value, dict):
            return {}
        skill_id = str(value.get("skill_id") or "").strip()
        version = str(value.get("version") or "").strip()
        return dict(value) if skill_id and version else {}

    @staticmethod
    def _skill_execution_model_snapshot(ctx: AgentContext, manifest: dict[str, Any]) -> dict[str, Any]:
        creation = manifest.get("model_snapshot") if isinstance(manifest.get("model_snapshot"), dict) else {}
        active_backend = str(getattr(ctx, "active_backend", "") or creation.get("provider") or "unknown")
        model = str(creation.get("model") or "")
        routers = getattr(ctx, "model_routers", {})
        router = routers.get(active_backend) if isinstance(routers, dict) else None
        if router is not None:
            try:
                model = str(router.select("tool_formatting").primary or model)
            except Exception:
                pass
        return {
            "provider": active_backend,
            "model": model,
            "endpoint_profile": str(creation.get("endpoint_profile") or active_backend),
            "fallback_allowed": False,
            "snapshotted_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _skill_segment_retry_is_safe(result: dict[str, Any]) -> bool:
        """Retry only failures proven to have happened before the recorded segment actuated."""
        try:
            executed_action_count = int(result.get("executed_action_count", -1))
        except (TypeError, ValueError):
            return False
        return executed_action_count == 0 and str(result.get("failure_code") or "") in {
            "PYAUTOGUI_WINDOW_NOT_FOUND",
            "PYAUTOGUI_WINDOW_NOT_FOCUSED",
            "PYAUTOGUI_LOCATOR_NOT_FOUND",
        }

    async def _selected_skill_recovery_decision(
        self,
        ctx: AgentContext,
        *,
        model_snapshot: dict[str, Any],
        exception: dict[str, Any],
    ) -> dict[str, Any]:
        provider = str(model_snapshot.get("provider") or "").strip()
        model = str(model_snapshot.get("model") or "").strip()
        backends = getattr(ctx, "primary_backends", {})
        backend = backends.get(provider) if isinstance(backends, dict) else None
        if backend is None and provider == str(getattr(ctx, "active_backend", "") or ""):
            backend = getattr(ctx, "primary_backend", None)
        if backend is None or not model:
            raise SkillContractError("snapshotted recovery model is unavailable")
        manual_context = self._manual_context(json.dumps(exception, ensure_ascii=False, default=str), purpose="recovery")
        manual_audit = manual_context_audit(manual_context)
        response = await backend.complete(
            model=model,
            system_prompt=build_manual_grounded_prompt(
                "Return one JSON object only for a bounded Windows GUI recovery. "
                "Choose exactly one operation from allowed_recovery_operations. "
                "Do not add shell, Python, clicks, credentials, or physical-equipment actions.",
                manual_context,
            ),
            user_prompt=json.dumps(exception, ensure_ascii=True, sort_keys=True),
            metadata={
                "task_type": "equipment_skill_recovery",
                "role": "equipment_skill_recovery",
                "no_fallback": True,
                "manual_context_hash": manual_audit["context_hash"],
            },
        )
        raw = self._extract_json_object(str(response.text or ""))
        if raw is None:
            raise SkillContractError("selected recovery model returned invalid JSON")
        return validate_recovery_decision(raw, exception=exception, max_attempts=1)

    async def _run_equipment_skill(
        self,
        state: OrchestratorState,
        ctx: AgentContext,
        request: dict[str, Any],
    ) -> AgentResult:
        skill_id = str(request.get("skill_id") or "").strip()
        version = str(request.get("version") or "").strip()
        target_profile = str(request.get("target_profile") or "").strip()
        registry_root = Path(
            str(request.get("registry_root") or Path(__file__).resolve().parents[1] / "memory" / "equipment_skills")
        )
        registry = EquipmentSkillRegistry(registry_root)
        try:
            package = registry.get(skill_id, version)
            manifest = package["manifest"]
            if manifest.get("lifecycle") != "deployed" or manifest.get("enabled") is False:
                raise SkillContractError("exact Skill version is not deployed and enabled")
            expected_profile = str(manifest.get("target_profile") or "")
            if target_profile and target_profile != expected_profile:
                raise SkillContractError("target profile mismatch")
            target_profile = target_profile or expected_profile
            model_snapshot = self._skill_execution_model_snapshot(ctx, manifest)
            execution = registry.begin_execution(
                skill_id=skill_id,
                version=version,
                sequence_id=str(request.get("sequence_id") or f"{state.run_id}-{skill_id}-{version}"),
                target_profile=target_profile,
                model_snapshot=model_snapshot,
            )
        except SkillContractError as exc:
            return AgentResult(
                success=False,
                summary="Equipment Skill contract blocked execution",
                data={
                    "equipment_skill_execution": {"state": "ABORTED", "skill_id": skill_id, "version": version},
                    "equipment_handoff": {"status": "blocked", "failure_code": "SKILL_CONTRACT_INVALID", "message": str(exc)},
                    "hardware_alerts": [],
                },
            )

        if execution.get("state") == "COMPLETED":
            return AgentResult(
                success=True,
                summary="Equipment Skill already completed",
                data={
                    "equipment_skill_execution": execution,
                    "equipment_handoff": {"status": "ready_for_analysis", "skill_id": skill_id, "version": version},
                    "tool_results": [],
                    "hardware_alerts": [],
                },
            )

        completed = set(str(item) for item in execution.get("completed_segments", []))
        tool_results: list[dict[str, Any]] = []
        for index, program_id in enumerate(package["workflow"].get("program_ids", []), start=1):
            program_id = str(program_id)
            if program_id in completed:
                continue
            payload = {
                "runtime_mode": self._effective_runtime_mode(state),
                "program_id": program_id,
                "sequence_id": f"{execution['execution_id']}-segment-{index:03d}",
                "run_id": state.run_id,
                "experiment_id": state.experiment_id,
                "equipment_skill_id": skill_id,
                "equipment_skill_version": version,
                "equipment_skill_execution_id": execution["execution_id"],
            }
            result = await self._call_tool(ctx, "equipment.pyautogui.run", payload)
            tool_results.append({"tool": "equipment.pyautogui.run", "payload": payload, "result": result})
            if not result.get("ok"):
                evidence = result.get("screen_artifacts") if isinstance(result.get("screen_artifacts"), list) else []
                if not evidence:
                    evidence = [{"artifact_id": "bridge-result", "sha256": hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()}]
                exception = build_exception_packet(
                    skill_id=skill_id,
                    version=version,
                    execution_id=str(execution["execution_id"]),
                    segment_id=program_id,
                    checkpoint_id=str(result.get("step_trace", [{}])[-1].get("step") if result.get("step_trace") else "segment"),
                    failure_code=str(result.get("failure_code") or "SKILL_CHECKPOINT_FAILED"),
                    message=str(result.get("message") or "compiled Skill segment failed"),
                    evidence=evidence,
                    allowed_recovery_operations=["focus_window", "screenshot", "wait", "press"],
                )
                execution = registry.transition_execution(
                    str(execution["execution_id"]),
                    "EXCEPTION",
                    exception=exception,
                    failed_segment=program_id,
                )
                auto_recover = bool(request.get("auto_recover", True))
                if auto_recover and self._skill_segment_retry_is_safe(result):
                    try:
                        recovery = await self._selected_skill_recovery_decision(
                            ctx,
                            model_snapshot=model_snapshot,
                            exception=exception,
                        )
                        recovery_gate = equipment_skill_recovery_gate(
                            state=state,
                            recovery=recovery,
                            allowed_operations=list(exception.get("allowed_recovery_operations", [])),
                            max_attempts=1,
                        )
                        if gate_blocks_execution(recovery_gate):
                            raise SkillContractError(
                                f"Guardian rejected recovery: {recovery_gate.get('reason_code') or 'blocked'}"
                            )
                        execution = registry.transition_execution(
                            str(execution["execution_id"]),
                            "RECOVERING",
                            attempt=1,
                            recovery_candidate=recovery,
                            recovery_guardian=recovery_gate,
                        )
                        recovery_action = {"action": recovery["operation"], **dict(recovery["payload"])}
                        recovery_payload = {
                            "runtime_mode": self._effective_runtime_mode(state),
                            "sequence": [recovery_action],
                            "sequence_id": f"{execution['execution_id']}-recovery-001",
                            "run_id": state.run_id,
                            "experiment_id": state.experiment_id,
                            "equipment_skill_id": skill_id,
                            "equipment_skill_version": version,
                            "equipment_skill_execution_id": execution["execution_id"],
                        }
                        recovery_result = await self._call_tool(ctx, "equipment.pyautogui.run", recovery_payload)
                        tool_results.append(
                            {"tool": "equipment.pyautogui.run", "payload": recovery_payload, "result": recovery_result}
                        )
                        if not recovery_result.get("ok"):
                            raise SkillContractError("bounded recovery action failed verification")
                        execution = registry.transition_execution(
                            str(execution["execution_id"]),
                            "RECOVERY_VERIFY",
                            recovery_result=recovery_result,
                        )
                        history = list(execution.get("recovery_history", []))
                        history.append(
                            {
                                "operation": recovery["operation"],
                                "attempt": 1,
                                "confidence": recovery["confidence"],
                                "status": "verified",
                            }
                        )
                        execution = registry.transition_execution(
                            str(execution["execution_id"]),
                            "RESUMED",
                            recovery_history=history,
                        )
                        resume_payload = {
                            **payload,
                            "sequence_id": f"{execution['execution_id']}-segment-{index:03d}-resume-001",
                        }
                        result = await self._call_tool(ctx, "equipment.pyautogui.run", resume_payload)
                        tool_results.append(
                            {"tool": "equipment.pyautogui.run", "payload": resume_payload, "result": result}
                        )
                        if not result.get("ok"):
                            execution = registry.transition_execution(
                                str(execution["execution_id"]),
                                "ESCALATED",
                                failed_segment=program_id,
                                failure_code=str(result.get("failure_code") or "SKILL_RESUME_FAILED"),
                            )
                    except (SkillContractError, RuntimeError, KeyError, TypeError, ValueError) as exc:
                        execution = registry.transition_execution(
                            str(execution["execution_id"]),
                            "ESCALATED",
                            recovery_error=str(exc),
                            failed_segment=program_id,
                        )
                if not result.get("ok") or execution.get("state") == "ESCALATED":
                    failure_code = str(
                        execution.get("failure_code")
                        or exception.get("failure_code")
                        or "SKILL_RECOVERY_ESCALATED"
                    )
                    return AgentResult(
                        success=False,
                        summary=(
                            "Equipment Skill recovery escalated"
                            if execution.get("state") == "ESCALATED"
                            else "Equipment Skill paused at a verified exception boundary"
                        ),
                        data={
                            "equipment_skill_execution": execution,
                            "equipment_skill_exception": exception,
                            "equipment_handoff": {"status": "blocked", "failure_code": failure_code},
                            "tool_results": tool_results,
                            "hardware_alerts": [],
                        },
                    )
            completed.add(program_id)
            execution = registry.transition_execution(
                str(execution["execution_id"]),
                "RUNNING",
                completed_segments=sorted(completed),
                current_segment=program_id,
            )

        execution = registry.transition_execution(
            str(execution["execution_id"]),
            "COMPLETED",
            completed_segments=sorted(completed),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return AgentResult(
            success=True,
            summary=f"Equipment Skill completed: {skill_id}@{version}",
            data={
                "equipment_skill_execution": execution,
                "equipment_result": tool_results[-1]["result"] if tool_results else {},
                "equipment_report": {
                    "schema": "equipment_skill_report.v1",
                    "skill_id": skill_id,
                    "version": version,
                    "state": "COMPLETED",
                    "program_ids": list(package["workflow"].get("program_ids", [])),
                },
                "equipment_handoff": {"status": "ready_for_analysis", "skill_id": skill_id, "version": version},
                "tool_results": tool_results,
                "hardware_alerts": [],
            },
        )

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        available_tools = set(ctx.tools.list_tools())
        if "equipment.pyautogui.run" not in available_tools:
            return await self._legacy_utm(state, ctx)

        skill_request = self._equipment_skill_request(state)
        if skill_request:
            return await self._run_equipment_skill(state, ctx, skill_request)

        profile = self._selected_profile(state)
        runtime_mode = self._effective_runtime_mode(state)
        test_like = self._test_like_mode(state)
        timeout_s = 30.0 if test_like else None
        raw_plan: dict[str, Any] | None = None
        force_safe_test_plan = test_like and not self._has_explicit_equipment_plan(state)
        try:
            response = await ctx.complete(
                "tool_formatting",
                self._tool_plan_prompt(state, sorted(available_tools)),
                timeout_s=timeout_s,
            )
            raw_plan = self._extract_json_object(response.text)
            if raw_plan is None:
                raise ValueError("Equipment tool planner returned non-JSON output.")
        except Exception as exc:
            if test_like:
                raw_plan = self._fallback_tool_plan(state)
                raw_plan["note"] = f"E2B degraded in test mode: {exc.__class__.__name__}; using safe equipment tool plan"
            else:
                raise
        if force_safe_test_plan:
            raw_plan = self._fallback_tool_plan(state)
            raw_plan["note"] = "using safe equipment tool plan; no explicit equipment program was provided, so UTM bridge plan is enforced"

        protocol_note, calls = self._normalize_plan(raw_plan or {}, state)
        base_payload = self._base_run_payload(state)
        base_payload["equipment_profile_id"] = profile.profile_id
        tool_results: list[dict[str, Any]] = []
        source_stage_context = base_payload["source_stage_context"]
        program_catalog: set[str] = set()
        tool_event_callback = getattr(ctx, "on_tool_event", None)
        loop = asyncio.get_running_loop()

        def emit_tool_event(event: dict[str, Any]) -> None:
            if not callable(tool_event_callback):
                return
            event_payload = dict(event)
            event_payload.setdefault("run_id", state.run_id)
            event_payload.setdefault("experiment_id", state.experiment_id)

            def notify() -> None:
                result = tool_event_callback(event_payload)
                if inspect.isawaitable(result):
                    asyncio.create_task(result)

            loop.call_soon_threadsafe(notify)

        if (
            "vision.equipment_cross_check" in available_tools
            and self._planned_utm_program(calls, state)
            and (test_like or not self._has_equipment_vision_results(source_stage_context))
        ):
            vision_checks = self._equipment_vision_requests(state=state, source_stage_context=source_stage_context)
            vision_payload = {
                "run_id": state.run_id,
                "experiment_id": state.experiment_id,
                "runtime_mode": self._effective_runtime_mode(state),
                "checks": vision_checks,
                "source_stage_context": source_stage_context,
            }
            emit_tool_event(
                {
                    "tool": "vision.equipment_cross_check",
                    "step": "VISION_PRECHECK_REQUEST",
                    "status": "running",
                    "detail": ", ".join(str(item.get("check_id") or "") for item in vision_checks if isinstance(item, dict)),
                    "checks": vision_checks,
                }
            )
            vision_result = await self._call_tool(ctx, "vision.equipment_cross_check", vision_payload)
            tool_results.append({"tool": "vision.equipment_cross_check", "result": vision_result})
            vision_results = vision_result.get("results") if isinstance(vision_result.get("results"), list) else []
            for check in vision_results:
                if not isinstance(check, dict):
                    continue
                check_id = str(check.get("check_id") or "unknown")
                frames = []
                evidence = check.get("evidence") if isinstance(check.get("evidence"), dict) else {}
                if isinstance(evidence.get("frame_ids"), list):
                    frames = [str(item) for item in evidence["frame_ids"] if str(item or "")]
                emit_tool_event(
                    {
                        "tool": "vision.equipment_cross_check",
                        "step": f"VISION_CHECK:{check_id}",
                        "status": "ok" if check.get("ok") else "blocked",
                        "detail": f"confidence={check.get('confidence', '-')}; frames={','.join(frames) if frames else '-'}",
                        "check_id": check_id,
                        "check_result": check,
                    }
                )
            emit_tool_event(
                {
                    "tool": "vision.equipment_cross_check",
                    "step": "VISION_PRECHECK_DONE",
                    "status": "ok" if vision_result.get("ok") else "blocked",
                    "detail": str(vision_result.get("failure_code") or f"checks={len(vision_results)}"),
                    "result": vision_result,
                }
            )
            if vision_results:
                vision = source_stage_context.get("vision") if isinstance(source_stage_context.get("vision"), dict) else {}
                vision = dict(vision)
                vision["equipment_vision_check_results"] = [dict(item) for item in vision_results if isinstance(item, dict)]
                source_stage_context["vision"] = vision

        for call in calls:
            tool = call["tool"]
            payload = dict(call.get("payload", {}))
            effective_payload = payload
            if tool == "equipment.pyautogui.run":
                merged = dict(base_payload)
                merged.update(payload)
                effective_payload = merged
                if "program_id" not in merged and self._program_hint(state):
                    merged["program_id"] = self._program_hint(state)
                if "sequence" not in merged and self._sequence_hint(state):
                    merged["sequence"] = self._sequence_hint(state)
                requested_program = str(merged.get("program_id") or "").strip()
                if not requested_program or requested_program.startswith("utm_"):
                    contract = build_execution_contract(
                        profile,
                        runtime_mode=runtime_mode,
                        bridge_config={},
                        program_id=requested_program,
                    )
                    merged["program_id"] = contract.program_id
                    merged["simulate_utm_protocol"] = contract.simulate_utm_protocol
                    merged["equipment_profile"] = contract.to_safe_dict()
                merged["_event_callback"] = emit_tool_event
                if program_catalog and str(merged.get("program_id") or ""):
                    program_id = str(merged.get("program_id"))
                    if program_id not in program_catalog:
                        result = {
                            "ok": False,
                            "tool": "equipment.pyautogui.run",
                            "mode": self._effective_runtime_mode(state),
                            "bridge": "windows_pyautogui",
                            "status": "blocked",
                            "program_id": program_id,
                            "failure_code": "PYAUTOGUI_PROGRAM_NOT_FOUND",
                            "message": f"Registered PyAutoGUI macro program not found: {program_id}",
                            "step_trace": [{"step": "RESOLVE_PROGRAM", "status": "blocked", "detail": program_id}],
                        }
                    else:
                        result = await self._call_tool(ctx, tool, merged)
                else:
                    result = await self._call_tool(ctx, tool, merged)
            else:
                result = await self._call_tool(ctx, tool, payload)

            if tool == "equipment.pyautogui.run":
                self._replay_pyautogui_step_trace(
                    result=result if isinstance(result, dict) else {},
                    payload=effective_payload,
                    emit_tool_event=emit_tool_event,
                )

            if tool == "equipment.pyautogui.list_programs" and isinstance(result.get("programs"), list):
                program_catalog = {
                    str(item.get("program_id"))
                    for item in result["programs"]
                    if isinstance(item, dict) and item.get("program_id")
                }
            tool_results.append({"tool": tool, "result": result})
            if tool in {"equipment.pyautogui.health", "equipment.pyautogui.list_programs"} and not result.get("ok", False):
                break
            if tool == "equipment.pyautogui.run":
                break

        run_tool_result = next(
            (
                item.get("result", {})
                for item in tool_results
                if isinstance(item.get("result"), dict) and item.get("tool") == "equipment.pyautogui.run"
            ),
            None,
        )
        if run_tool_result is not None and "equipment.pyautogui.request_log" in available_tools:
            audit_payload = {"runtime_mode": self._effective_runtime_mode(state)}
            audit_result = await self._call_tool(ctx, "equipment.pyautogui.request_log", audit_payload)
            tool_results.append({"tool": "equipment.pyautogui.request_log", "result": audit_result})

        final_result = run_tool_result if isinstance(run_tool_result, dict) else (tool_results[-1]["result"] if tool_results else {"ok": False, "status": "no_tool_calls"})
        run_payload = next(
            (
                item.get("result", {})
                for item in tool_results
                if isinstance(item.get("result"), dict) and item.get("tool") == "equipment.pyautogui.run"
            ),
            final_result,
        )
        package = self._build_equipment_package(
            state=state,
            final_result=final_result if isinstance(final_result, dict) else {},
            run_payload=run_payload if isinstance(run_payload, dict) else {},
            tool_results=tool_results,
            program_catalog=program_catalog,
            source_stage_context=source_stage_context,
        )
        return AgentResult(
            success=bool(package["verified"]),
            summary="Equipment PyAutoGUI workflow verified" if package["verified"] else "Equipment PyAutoGUI workflow blocked before analysis handoff",
            data={
                "equipment_result": package["equipment_result"],
                "equipment_profile": profile.to_safe_dict(),
                "protocol_note": protocol_note,
                "equipment_bridge": "windows_pyautogui",
                "tool_results": tool_results,
                "tool_plan": calls,
                "program_catalog": sorted(program_catalog),
                "source_stage_context": source_stage_context,
                "equipment_report": package["equipment_report"],
                "utm_data_ready": package["utm_data_ready"],
                "handoff_packet": package["utm_data_ready"],
                "decisions": [package["equipment_report"]["decision"]],
                "metrics": {
                    "screen_checks_passed": bool(package["equipment_report"]["cross_checks"].get("screen_started")),
                    "physical_motion_confirmed": bool(package["equipment_report"]["cross_checks"].get("physical_motion_started")),
                    "data_parse_probe_ok": bool(package["equipment_report"]["cross_checks"].get("data_parse_probe_ok")),
                    "row_count_probe": package["equipment_report"]["data_acquisition"].get("row_count_probe", 0),
                },
                "evidence_refs": package["utm_data_ready"].get("evidence_refs", []),
                "hardware_alert": package.get("hardware_alert"),
                "hardware_alerts": package.get("hardware_alerts", []),
                "incident_records": package.get("incident_records", []),
                "equipment_handoff": package["equipment_handoff"],
            },
        )
