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
import inspect
import json
import re
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState


class LabEquipmentAgent(BaseAgent):
    """Runs physical/simulated equipment protocols and Windows GUI macros."""

    name = "equipment_agent"
    _PYAUTOGUI_TOOLS = {
        "equipment.pyautogui.health",
        "equipment.pyautogui.list_programs",
        "equipment.pyautogui.run",
    }

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

    def _tool_plan_prompt(self, state: OrchestratorState, tools: list[str]) -> str:
        spec = state.current_experiment_spec if isinstance(state.current_experiment_spec, dict) else {}
        program_hint = self._program_hint(state)
        sequence_hint = self._sequence_hint(state)
        return (
            "You are the Equipment Agent tool-call planner.\n"
            "Choose only from these tools: equipment.pyautogui.health, "
            "equipment.pyautogui.list_programs, equipment.pyautogui.run.\n"
            "Use registered macro programs by program_id when the user command names a program.\n"
            "Never output raw Python, shell, PowerShell, or unregistered tool names.\n"
            "Return strict JSON only with keys: note, calls.\n"
            "calls is a list of {tool, payload}. Prefer health -> list_programs -> run for macro commands.\n\n"
            f"mode={state.mode.value}\n"
            f"active_goal={state.active_goal}\n"
            f"program_hint={program_hint}\n"
            f"sequence_hint={json.dumps(sequence_hint, ensure_ascii=True)}\n"
            f"available_tools={json.dumps(tools, ensure_ascii=True)}\n"
            f"experiment_spec={json.dumps(spec, ensure_ascii=True, default=str)[:4000]}\n"
        )

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
        if program_id:
            calls.append({"tool": "equipment.pyautogui.list_programs", "payload": {}})
            calls.append({"tool": "equipment.pyautogui.run", "payload": {"program_id": program_id, "command": state.active_goal}})
        else:
            calls.append({"tool": "equipment.pyautogui.run", "payload": {"sequence": sequence} if sequence else {}})
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

    def _base_run_payload(self, state: OrchestratorState) -> dict[str, Any]:
        return {
            "sequence_id": f"equipment-{state.run_id}",
            "runtime_mode": state.mode.value,
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

    async def _call_tool(self, ctx: AgentContext, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(ctx.tools.call, tool, payload)

    async def _legacy_utm(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        profile = "test_profile" if state.mode.value != "live" else "live_profile"
        timeout_s = 30.0 if state.mode == Mode.TEST else None
        try:
            protocol = await ctx.complete(
                "tool_formatting",
                f"Format UTM run command profile={profile} with concise equipment-safe options.",
                timeout_s=timeout_s,
            )
            protocol_note = protocol.text[:220]
        except Exception as exc:
            if state.mode == Mode.TEST:
                protocol_note = f"E2B degraded in test mode: {exc.__class__.__name__}"
            else:
                raise
        response = ctx.tools.call("utm.run_protocol", {"profile": profile})
        return AgentResult(
            success=bool(response.get("ok")),
            summary="Equipment protocol run completed",
            data={"equipment_result": response, "protocol_note": protocol_note, "equipment_bridge": "utm"},
        )

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        available_tools = set(ctx.tools.list_tools())
        if "equipment.pyautogui.run" not in available_tools:
            return await self._legacy_utm(state, ctx)

        timeout_s = 30.0 if state.mode == Mode.TEST else None
        raw_plan: dict[str, Any] | None = None
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
            if state.mode == Mode.TEST:
                raw_plan = self._fallback_tool_plan(state)
                raw_plan["note"] = f"E2B degraded in test mode: {exc.__class__.__name__}; using safe equipment tool plan"
            else:
                raise

        protocol_note, calls = self._normalize_plan(raw_plan or {}, state)
        base_payload = self._base_run_payload(state)
        tool_results: list[dict[str, Any]] = []
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

        for call in calls:
            tool = call["tool"]
            payload = dict(call.get("payload", {}))
            if tool == "equipment.pyautogui.run":
                merged = dict(base_payload)
                merged.update(payload)
                if "program_id" not in merged and self._program_hint(state):
                    merged["program_id"] = self._program_hint(state)
                if "sequence" not in merged and self._sequence_hint(state):
                    merged["sequence"] = self._sequence_hint(state)
                merged["_event_callback"] = emit_tool_event
                if program_catalog and str(merged.get("program_id") or ""):
                    program_id = str(merged.get("program_id"))
                    if program_id not in program_catalog:
                        result = {
                            "ok": False,
                            "tool": "equipment.pyautogui.run",
                            "mode": state.mode.value,
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

        final_result = tool_results[-1]["result"] if tool_results else {"ok": False, "status": "no_tool_calls"}
        source_stage_context = base_payload["source_stage_context"]
        run_payload = next(
            (
                item.get("result", {})
                for item in tool_results
                if isinstance(item.get("result"), dict) and item.get("tool") == "equipment.pyautogui.run"
            ),
            final_result,
        )
        return AgentResult(
            success=bool(final_result.get("ok")),
            summary="Equipment PyAutoGUI workflow completed",
            data={
                "equipment_result": final_result,
                "protocol_note": protocol_note,
                "equipment_bridge": "windows_pyautogui",
                "tool_results": tool_results,
                "tool_plan": calls,
                "program_catalog": sorted(program_catalog),
                "source_stage_context": source_stage_context,
                "equipment_handoff": {
                    "status": "ready_for_analysis" if final_result.get("ok") else "blocked",
                    "bridge": "windows_pyautogui",
                    "program_id": str(run_payload.get("program_id") or ""),
                    "sequence_id": str(run_payload.get("sequence_id") or base_payload["sequence_id"]),
                    "failure_code": final_result.get("failure_code"),
                },
            },
        )
