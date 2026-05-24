"""
File purpose:
- Trigger specimen preparation workflow via MCP tool abstraction.

Key classes/functions:
- SpecimenMakingAgent

Inputs/outputs:
- Input: current experiment spec
- Output: specimen preparation result

Dependencies:
- agents.base_agent.BaseAgent
- mcp tools: geometry.generate_metamaterial_stl, geometry.check_mesh_quality,
  geometry.check_manufacturability, artifact.create_specimen_handoff, printer.prepare

Modification guide:
- Safe places to edit: payload schema and validation thresholds
- Risky places to edit: tool names and required output keys
- Related files: mcp_tools/printer_tools.py, device_bridges/prusa_bridge.py
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from orchestrator.state import Mode, OrchestratorState


class SpecimenMakingAgent(BaseAgent):
    """Handles specimen creation and preparation."""

    name = "specimen_agent"
    REQUIRED_FIELDS = (
        "candidate_id",
        "specimen_id",
        "geometry_type",
        "specimen_size_mm",
        "cell_size_mm",
        "wall_thickness_mm",
        "relative_density",
        "material",
        "printer_profile",
        "slicer_profile_hint",
        "layer_height_mm",
        "nozzle_diameter_mm",
    )

    @staticmethod
    def _vector3(value: Any, default: list[float]) -> list[float]:
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
    def _artifact_dir(state: OrchestratorState, specimen_id: str) -> Path:
        repo_root = Path(__file__).resolve().parents[1]
        path = repo_root / "runs" / state.run_id / "specimens" / specimen_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _required_missing(self, spec: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        for key in self.REQUIRED_FIELDS:
            value = spec.get(key)
            if value in (None, "", []):
                missing.append(key)
        return missing

    @staticmethod
    def _is_live_gui_test_spec(state: OrchestratorState, spec: dict[str, Any]) -> bool:
        """Detect Live GUI's LLM-generated test-mode handoff while runtime mode remains live."""
        return state.mode == Mode.LIVE and bool(
            spec.get("test_mode_autofill")
            or spec.get("test_mode_llm_generated")
            or spec.get("printer_test_path")
            or spec.get("test_printer_path")
            or spec.get("printer_bridge_mode")
            or spec.get("printer_test_mode")
        )

    @staticmethod
    def _normalize_printer_test_path(value: Any) -> str:
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        compact = text.replace("_", "")
        if not text:
            return ""
        if any(token in compact for token in ("actualprint", "physicalprint", "startprint", "실제출력", "출력")):
            return "physical_print"
        if any(token in text for token in ("virtual", "가상", "bridge", "브릿지", "브리지")):
            return "virtual_bridge"
        if any(token in text for token in ("installed", "real", "prusa", "printer", "설치", "실제", "프린터")):
            return "installed_printer"
        return ""

    def _printer_test_path(self, spec: dict[str, Any]) -> str:
        for key in ("printer_test_path", "test_printer_path", "printer_bridge_mode", "printer_test_mode"):
            normalized = self._normalize_printer_test_path(spec.get(key))
            if normalized:
                return normalized
        printer = spec.get("printer") if isinstance(spec.get("printer"), dict) else {}
        for key in ("test_path", "bridge_mode", "test_mode"):
            normalized = self._normalize_printer_test_path(printer.get(key))
            if normalized:
                return normalized
        return ""

    @staticmethod
    def _printer_path_choice_result(candidate: str, specimen_id: str) -> AgentResult:
        prompt = (
            "Specimen Making Agent가 테스트 프린터 경로 선택을 기다립니다.\n\n"
            "- 가상 브릿지: 실제 PrusaSlicer로 슬라이싱한 뒤 PrusaLink 형태의 가상 통신으로 upload/start 경계까지 검증합니다.\n"
            "- 설치 프린터 통신 테스트: 실제 PrusaSlicer로 슬라이싱한 뒤 저장된 PrusaLink 연결정보로 실제 프린터 read-only 상태 통신을 확인합니다.\n"
            "- 실제 출력: 테스트 모드에서 생성한 시편을 실제 PrusaSlicer -> PrusaLink upload/start 경로로 출력합니다.\n\n"
            "답변은 `가상 브릿지`, `설치 프린터`, `실제 출력` 중 하나로 보내주세요."
        )
        specimen_result = {
            "ok": False,
            "candidate_id": candidate,
            "specimen_id": specimen_id,
            "printer_prepare_status": "printer_test_path_required",
            "requires_operator_input": True,
            "input_request": {
                "type": "printer_test_path_choice",
                "prompt": prompt,
                "choices": ["virtual_bridge", "installed_printer", "physical_print"],
            },
            "operator_messages": [prompt],
            "reject_reasons": [],
            "warnings": [],
        }
        return AgentResult(
            success=True,
            summary="Specimen Making Agent waiting for printer test path selection",
            data={"specimen_result": specimen_result, "protocol_note": "waiting_for_printer_test_path"},
            next_hint="operator_input_required",
        )

    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        spec = dict(state.current_experiment_spec or {})
        candidate = str(spec.get("candidate_id", "cand-unknown"))
        specimen_id = str(spec.get("specimen_id", f"specimen-{candidate}"))
        missing = self._required_missing(spec)
        if missing:
            raise RuntimeError(f"specimen_agent missing required experiment_spec fields: {', '.join(missing)}")
        live_gui_test_spec = self._is_live_gui_test_spec(state, spec)
        printer_test_path = self._printer_test_path(spec)
        if live_gui_test_spec and not printer_test_path:
            return self._printer_path_choice_result(candidate, specimen_id)

        constraints = spec.get("constraints") if isinstance(spec.get("constraints"), dict) else {}
        output_dir = self._artifact_dir(state, specimen_id)
        specimen_size = self._vector3(spec.get("specimen_size_mm"), [30.0, 30.0, 30.0])
        wall = float(spec.get("wall_thickness_mm", 1.2))
        cell = float(spec.get("cell_size_mm", 7.5))

        timeout_s = 30.0 if state.mode == Mode.TEST else None
        try:
            protocol = await ctx.complete(
                "tool_formatting",
                (
                    "Format specimen fabrication handoff intent. Return concise command intent.\n"
                    f"candidate={candidate}\n"
                    f"specimen_id={specimen_id}\n"
                    f"geometry_type={spec.get('geometry_type')}\n"
                    f"specimen_size_mm={specimen_size}\n"
                    f"cell_size_mm={cell}\n"
                    f"wall_thickness_mm={wall}"
                ),
                timeout_s=timeout_s,
            )
            protocol_note = protocol.text[:220]
        except Exception as exc:
            if state.mode == Mode.TEST:
                protocol_note = f"E2B degraded in test mode: {exc.__class__.__name__}"
            else:
                raise

        legacy_cap = bool(spec.get("top_bottom_cap", False))
        top_cap_enabled = bool(spec.get("top_cap_enabled", legacy_cap))
        bottom_cap_enabled = bool(spec.get("bottom_cap_enabled", legacy_cap))
        geometry_payload = {
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "candidate_id": candidate,
            "specimen_id": specimen_id,
            "geometry_type": str(spec.get("geometry_type")),
            "specimen_size_mm": specimen_size,
            "cell_size_mm": cell,
            "wall_thickness_mm": wall,
            "relative_density": float(spec.get("relative_density", 0.32)),
            "anisotropy_ratio": float(spec.get("anisotropy_ratio", 1.0)),
            "orientation_deg": float(spec.get("orientation_deg", 0.0)),
            "defect_seed": int(spec.get("defect_seed", state.loop_count + 1)),
            "defect_ratio": float(spec.get("defect_ratio", 0.0)),
            "skin_thickness_mm": float(spec.get("skin_thickness_mm", 0.0)),
            "top_cap_enabled": top_cap_enabled,
            "bottom_cap_enabled": bottom_cap_enabled,
            "top_bottom_cap": bool(top_cap_enabled or bottom_cap_enabled),
            "material": str(spec.get("material", "PLA")),
            "output_dir": str(output_dir),
            "output_format": "stl",
        }
        for optional_key in ("tpms_surface", "tpms_thickness", "tpms_resolution"):
            if optional_key in spec and spec[optional_key] not in (None, "", []):
                geometry_payload[optional_key] = spec[optional_key]
        geometry_result = ctx.tools.call("geometry.generate_metamaterial_stl", geometry_payload)
        if not bool(geometry_result.get("ok")):
            raise RuntimeError(f"geometry.generate_metamaterial_stl failed: {geometry_result.get('error_message', 'unknown')}")

        mesh_result = ctx.tools.call(
            "geometry.check_mesh_quality",
            {
                "stl_path": geometry_result.get("stl_path"),
                "expected_bounding_box_mm": specimen_size,
                "constraints": constraints,
            },
        )
        if not bool(mesh_result.get("ok")) or str(mesh_result.get("mesh_status", "fail")) != "pass":
            raise RuntimeError(
                "geometry.check_mesh_quality failed: "
                + ", ".join(str(item) for item in mesh_result.get("reject_reasons", []))
            )

        manufacturability_result = ctx.tools.call(
            "geometry.check_manufacturability",
            {
                "stl_path": geometry_result.get("stl_path"),
                "printer_profile": str(spec.get("printer_profile")),
                "material": str(spec.get("material")),
                "constraints": {
                    **constraints,
                    "geometry_type": str(spec.get("geometry_type")),
                    "wall_thickness_mm": wall,
                    "cell_size_mm": cell,
                    "relative_density": float(spec.get("relative_density", 0.32)),
                    "top_cap_enabled": top_cap_enabled,
                    "bottom_cap_enabled": bottom_cap_enabled,
                    "top_bottom_cap": bool(top_cap_enabled or bottom_cap_enabled),
                    "require_flat_compression_faces": bool(spec.get("require_flat_compression_faces", False)),
                    "nozzle_diameter_mm": float(spec.get("nozzle_diameter_mm", 0.4)),
                    "layer_height_mm": float(spec.get("layer_height_mm", 0.2)),
                    "tpms_thickness": spec.get("tpms_thickness"),
                    "fdm_min_wall_thickness_mm": float(spec.get("fdm_min_wall_thickness_mm", 1.2)),
                    "fdm_max_bridge_distance_mm": float(spec.get("fdm_max_bridge_distance_mm", 10.0)),
                    "fdm_max_unsupported_overhang_deg": float(spec.get("fdm_max_unsupported_overhang_deg", 45.0)),
                    "fdm_max_gyroid_wall_cell_ratio": float(spec.get("fdm_max_gyroid_wall_cell_ratio", 0.28)),
                    "expected_print_time_min": float(spec.get("expected_print_time_min", 0.0)),
                    "expected_mass_g": float(spec.get("expected_mass_g", 0.0)),
                },
                "mesh_report": mesh_result.get("mesh_report", {}),
            },
        )
        if not bool(manufacturability_result.get("ok")) or str(
            manufacturability_result.get("manufacturability_status", "fail")
        ) != "pass":
            raise RuntimeError(
                "geometry.check_manufacturability failed: "
                + ", ".join(str(item) for item in manufacturability_result.get("reject_reasons", []))
            )

        handoff_result = ctx.tools.call(
            "artifact.create_specimen_handoff",
            {
                "run_id": state.run_id,
                "experiment_id": state.experiment_id,
                "specimen_id": specimen_id,
                "experiment_spec": spec,
                "geometry_result": geometry_result,
                "mesh_result": mesh_result,
                "manufacturability_result": manufacturability_result,
                "next_agent": "vision_agent",
            },
        )
        if not bool(handoff_result.get("ok")) or str(handoff_result.get("handoff_status", "failed")) != "ready":
            raise RuntimeError(f"artifact.create_specimen_handoff failed: {handoff_result.get('error_message', 'unknown')}")

        printer_runtime_mode = "test" if live_gui_test_spec else state.mode.value
        printer_payload = {
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "runtime_mode": printer_runtime_mode,
            "specimen_id": specimen_id,
            "stl_path": geometry_result.get("stl_path"),
            "handoff_package_path": handoff_result.get("handoff_package_path"),
            "printer_profile": str(spec.get("printer_profile")),
            "material": str(spec.get("material")),
            "slicer_profile_hint": str(spec.get("slicer_profile_hint")),
            "experiment_spec": spec,
            "print": spec.get("print") if isinstance(spec.get("print"), dict) else {},
            "ejection": spec.get("ejection") if isinstance(spec.get("ejection"), dict) else {},
            "connection_info": spec.get("printer_connection") if isinstance(spec.get("printer_connection"), dict) else {},
            "stop_requested": bool(state.stop_requested),
            "safe_stop_requested": bool(state.safe_stop_requested),
        }
        if live_gui_test_spec:
            printer_payload["test_printer_path"] = printer_test_path
            printer_payload["allow_test_printer_live"] = printer_test_path in {"installed_printer", "physical_print"}
            printer_payload["test_printer_transport"] = "real" if printer_test_path in {"installed_printer", "physical_print"} else "virtual"
            if printer_test_path == "physical_print":
                print_request = dict(printer_payload["print"]) if isinstance(printer_payload.get("print"), dict) else {}
                print_request.update(
                    {
                        "start_immediately": True,
                        "physical_intent": True,
                        "confirm_physical_print": True,
                    }
                )
                printer_payload["print"] = print_request

        tool_event_callback = getattr(ctx, "on_tool_event", None)
        if callable(tool_event_callback):
            loop = asyncio.get_running_loop()

            def emit_tool_event(event: dict[str, Any]) -> None:
                event_payload = dict(event)
                event_payload.setdefault("run_id", state.run_id)
                event_payload.setdefault("experiment_id", state.experiment_id)
                event_payload.setdefault("specimen_id", specimen_id)

                def notify() -> None:
                    result = tool_event_callback(event_payload)
                    if inspect.isawaitable(result):
                        asyncio.create_task(result)

                loop.call_soon_threadsafe(notify)

            printer_payload["_event_callback"] = emit_tool_event

        experiment_response = await asyncio.to_thread(
            ctx.tools.call,
            "experiment.evaluate",
            {
                "run_id": state.run_id,
                "experiment_id": state.experiment_id,
                "session_id": state.run_id,
                "objective": {
                    "objective_id": f"specimen-print-{specimen_id}",
                    "name": "Specimen print preparation",
                    "description": "Evaluate generated specimen through the unified experiment runtime.",
                    "metric_name": "printability_score",
                    "direction": "maximize",
                    "constraints": constraints,
                    "tags": ["specimen", "printer", "fdm"],
                },
                "candidate": {
                    "candidate_id": candidate,
                    "source_agent": self.name,
                    "experiment_spec": spec,
                    "parameters": printer_payload,
                },
                "execution": {
                    "mode": printer_runtime_mode,
                    "bridge": "printer",
                    "requested_tool": "printer.prepare",
                    "dry_run": not bool((printer_payload.get("print") or {}).get("start_immediately", False)),
                    "allow_physical": printer_runtime_mode == "live" or bool(printer_payload.get("allow_test_printer_live")),
                },
                "metadata": {
                    "stage": state.stage.value,
                    "live_gui_test_spec": live_gui_test_spec,
                    "printer_test_path": printer_test_path,
                },
            },
        )
        response = experiment_response.get("bridge_result") if isinstance(experiment_response.get("bridge_result"), dict) else experiment_response

        specimen_result = {
            "ok": True,
            "tool": "printer.prepare",
            "experiment_evaluation": experiment_response,
            "candidate_id": candidate,
            "specimen_id": specimen_id,
            "geometry_status": "generated",
            "mesh_status": str(mesh_result.get("mesh_status", "pass")),
            "manufacturability_status": str(manufacturability_result.get("manufacturability_status", "pass")),
            "handoff_status": str(handoff_result.get("handoff_status", "ready")),
            "printer_prepare_status": str(response.get("status", "queued")),
            "printer_path": response.get("printer_path"),
            "printer_mode": response.get("mode"),
            "stl_path": geometry_result.get("stl_path"),
            "sliced_path": response.get("sliced_path"),
            "preview_image_path": geometry_result.get("preview_image_path"),
            "handoff_package_path": handoff_result.get("handoff_package_path"),
            "geometry_hash": geometry_result.get("geometry_hash"),
            "expected_mass_g": manufacturability_result.get("expected_mass_g"),
            "expected_print_time_min": manufacturability_result.get("expected_print_time_min"),
            "slicer_settings": response.get("slicer_settings", {}),
            "slicer_result": response.get("slicer_result", {}),
            "gcode_validation": response.get("gcode_validation", {}),
            "printer": response.get("printer", {}),
            "prusalink": response.get("prusalink", {}),
            "print_result": response.get("print_result", {}),
            "ejection_result": response.get("ejection_result", {}),
            "step_trace": response.get("step_trace", []),
            "operator_messages": response.get("operator_messages", []),
            "reject_reasons": [],
            "warnings": [
                *[str(item) for item in mesh_result.get("warnings", [])],
                *[str(item) for item in manufacturability_result.get("warnings", [])],
            ],
            "tool_result": response,
        }
        if response.get("requires_connection_info"):
            prompt = (
                "Specimen Making Agent가 설치 프린터 통신 테스트에 필요한 PrusaLink 연결정보를 기다립니다.\n\n"
                f"- 연결정보 파일: {response.get('connection_memory_path')}\n"
                "- 파일의 host/auth 값을 채운 뒤 `연결정보 입력 완료`라고 보내면 같은 specimen 단계에서 재시도합니다."
            )
            specimen_result["ok"] = False
            specimen_result["requires_operator_input"] = True
            specimen_result["input_request"] = {
                "type": "printer_connection_info",
                "prompt": prompt,
                "connection_memory_path": response.get("connection_memory_path"),
            }
            specimen_result["operator_messages"] = [*specimen_result["operator_messages"], prompt]
            return AgentResult(
                success=True,
                summary="Specimen Making Agent waiting for PrusaLink connection info",
                data={"specimen_result": specimen_result, "protocol_note": protocol_note},
                next_hint="operator_input_required",
            )
        if not bool(response.get("ok")):
            raise RuntimeError(f"printer.prepare failed: {response}")
        operator_messages = [str(item) for item in response.get("operator_messages", []) if str(item).strip()]
        summary_suffix = f" ({operator_messages[-1]})" if operator_messages else ""
        return AgentResult(
            success=True,
            summary=f"Specimen preparation executed{summary_suffix}",
            data={"specimen_result": specimen_result, "protocol_note": protocol_note},
        )
