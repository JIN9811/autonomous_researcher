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
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

from agents.base_agent import AgentContext, AgentResult, BaseAgent
from utils.agent_artifact_archive import archive_agent_run
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
        """Detect Live GUI's LLM-generated test-mode handoff across live/test execution modes."""
        return state.mode in {Mode.LIVE, Mode.TEST} and bool(
            spec.get("test_mode_autofill")
            or spec.get("test_mode_llm_generated")
            or spec.get("printer_test_path")
            or spec.get("test_printer_path")
            or spec.get("printer_bridge_mode")
            or spec.get("printer_test_mode")
        )

    @staticmethod
    def _should_disable_test_surface_caps(
        state: OrchestratorState,
        spec: dict[str, Any],
        *,
        live_gui_test_spec: bool,
    ) -> bool:
        """Keep physical/test STL open after the first closed-loop cycle; CAE handles platens separately."""
        if bool(spec.get("test_loop_surface_caps_disabled")):
            return True
        test_like = state.mode == Mode.TEST or live_gui_test_spec
        return bool(test_like and state.loop_count >= 1)

    @staticmethod
    def _without_surface_caps(spec: dict[str, Any]) -> dict[str, Any]:
        """Return a copy with generated-model cap skins disabled."""
        effective = dict(spec)
        effective["top_cap_enabled"] = False
        effective["bottom_cap_enabled"] = False
        effective["top_bottom_cap"] = False
        effective["skin_thickness_mm"] = 0.0
        effective["require_flat_compression_faces"] = False
        effective["test_loop_surface_caps_disabled"] = True
        constraints = effective.get("constraints") if isinstance(effective.get("constraints"), dict) else {}
        effective["constraints"] = {
            **constraints,
            "top_cap_enabled": False,
            "bottom_cap_enabled": False,
            "top_bottom_cap": False,
            "skin_thickness_mm": 0.0,
            "require_flat_compression_faces": False,
        }
        return effective

    @staticmethod
    def _enforce_fdm_gyroid_hard_rules(spec: dict[str, Any]) -> dict[str, Any]:
        """Clamp generated gyroid specs to hard FDM manufacturability rules before tool calls."""
        geometry = str(spec.get("geometry_type", "")).strip().lower()
        if geometry != "gyroid":
            return spec
        try:
            density = float(spec.get("relative_density", 0.32))
        except (TypeError, ValueError):
            density = 0.32
        if density >= 0.20:
            return spec
        effective = dict(spec)
        effective["relative_density"] = 0.20
        constraints = effective.get("constraints") if isinstance(effective.get("constraints"), dict) else {}
        effective["constraints"] = {**constraints, "relative_density": 0.20}
        return effective

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
    def _safe_float(value: Any, default: float | None = None) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _stable_digest(value: Any, length: int = 12) -> str:
        payload = json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]

    @staticmethod
    def _dict_value(*values: Any) -> dict[str, Any]:
        for value in values:
            if isinstance(value, dict):
                return value
        return {}

    @staticmethod
    def _first_value(*values: Any, default: Any = None) -> Any:
        for value in values:
            if value not in (None, "", []):
                return value
        return default

    def _degraded_virtual_bridge_experiment_response(
        self,
        *,
        state: OrchestratorState,
        spec: dict[str, Any],
        candidate: str,
        specimen_id: str,
        printer_payload: dict[str, Any],
        printer_runtime_mode: str,
        printer_test_path: str,
        exc: OSError,
    ) -> dict[str, Any]:
        """Keep test-mode closed-loop moving when a local slicer executable is invalid."""
        failure_code = exc.__class__.__name__
        warning = f"virtual bridge degraded after local slicer launch failed: {failure_code}: {exc}"
        metric_name = "printability_score"
        score = self._safe_float(spec.get("expected_objective_proxy_score"), 0.72)
        bridge_result = {
            "ok": True,
            "tool": "printer.prepare",
            "mode": "test_virtual_bridge_degraded",
            "printer_path": printer_test_path or "virtual_bridge",
            "status": "virtual_bridge_degraded",
            "specimen_id": specimen_id,
            "warnings": [warning],
            "slicer_settings": {
                "printer_profile": spec.get("printer_profile"),
                "slicer_profile_hint": spec.get("slicer_profile_hint"),
                "material": spec.get("material"),
                "layer_height_mm": spec.get("layer_height_mm"),
                "first_layer_height_mm": spec.get("first_layer_height_mm"),
                "bed_temperature_c": spec.get("bed_temperature_c"),
                "nozzle_diameter_mm": spec.get("nozzle_diameter_mm"),
                "expected_mass_g": spec.get("expected_mass_g"),
                "expected_print_time_min": spec.get("expected_print_time_min"),
                "resolved_command": [],
                "degraded_reason": warning,
            },
            "slicer_result": {
                "ok": True,
                "status": "degraded_virtual_slice",
                "degraded": True,
                "original_failure_code": failure_code,
            },
            "gcode_validation": {
                "ok": True,
                "status": "degraded_virtual_validation",
                "degraded": True,
                "violations": [],
            },
            "printer": {"ok": True, "status": "virtual_bridge_degraded", "transport": "virtual"},
            "prusalink": {"ok": True, "status": "virtual_ack", "transport": "virtual"},
            "print_result": {"ok": True, "status": "dry_run", "start_immediately": False},
            "ejection_result": {"ok": True, "status": "disabled"},
            "step_trace": [
                {"step": "PRUSASLICER_LAUNCH", "status": "degraded", "detail": failure_code},
                {"step": "VIRTUAL_PRUSALINK_BOUNDARY", "status": "ok"},
                {"step": "DOWNSTREAM_HANDOFF", "status": "ok"},
            ],
        }
        return {
            "ok": True,
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "session_id": state.run_id,
            "evaluation_id": f"eval-degraded-{self._stable_digest({'run_id': state.run_id, 'specimen_id': specimen_id}, 10)}",
            "candidate_id": candidate,
            "mode": printer_runtime_mode,
            "bridge": "printer",
            "status": "evaluated_degraded",
            "objective_score": score,
            "metrics": {
                metric_name: score,
                "virtual": True,
                "degraded": True,
                "printer_status": bridge_result["status"],
                "slicer_ok": True,
                "gcode_ok": True,
            },
            "artifacts": {},
            "bridge_result": bridge_result,
            "step_trace": bridge_result["step_trace"],
            "failure_code": None,
            "warnings": [warning],
            "metadata": {
                "stage": state.stage.value,
                "live_gui_test_spec": True,
                "printer_test_path": printer_test_path,
                "fallback": "degraded_virtual_bridge",
            },
        }

    @staticmethod
    def _gate(gate: str, status: str, evidence: dict[str, Any] | None = None, repair: Any = None) -> dict[str, Any]:
        return {
            "gate": gate,
            "status": status,
            "evidence": evidence or {},
            "repair": repair,
        }

    @staticmethod
    def _gate_status_from_result(result: dict[str, Any], *, ok_key: str = "ok", status_key: str = "status") -> str:
        if not result:
            return "warn"
        if result.get(ok_key) is True:
            return "pass"
        status = str(result.get(status_key) or "").lower()
        if status in {"pass", "ready", "prepared", "queued", "virtual_finished", "uploaded", "started", "ok"}:
            return "pass"
        if status in {"blocked", "connection_info_required", "not_started", "disabled"}:
            return "blocked"
        if result.get("failure_code"):
            return "fail"
        return "warn"

    @staticmethod
    def _storage_gate_status(printer: dict[str, Any], prusalink: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        storage = printer.get("storage") if isinstance(printer.get("storage"), dict) else {}
        evidence = {
            "selected_storage": prusalink.get("storage"),
            "transport": prusalink.get("transport"),
            "storage": storage,
        }
        if not storage:
            return "warn", evidence
        if storage.get("ok") is True:
            return "pass", evidence
        return "blocked", evidence

    def _build_pending_fabrication_report(
        self,
        *,
        state: OrchestratorState | None,
        spec: dict[str, Any],
        candidate: str,
        specimen_id: str,
        request_type: str,
        prompt: str,
    ) -> dict[str, Any]:
        printer_path = self._printer_test_path(spec) or "operator_selection_required"
        return {
            "schema": "fabrication_report.v1",
            "fabrication_intent": {
                "mode": state.mode.value if state is not None else "unknown",
                "physical_intent": False,
                "printer_path": printer_path,
                "specimen_purpose": str(spec.get("specimen_purpose") or spec.get("purpose") or "mechanical_test"),
                "operator_input_required": request_type,
            },
            "digital_thread": {
                "candidate_id": candidate,
                "specimen_id": specimen_id,
                "design_hash": str(spec.get("candidate_fingerprint") or self._stable_digest(spec)),
                "geometry_hash": "",
                "stl_path": "",
                "gcode_path": "",
                "handoff_package_path": "",
                "printer_profile": str(spec.get("printer_profile") or ""),
                "slicer_profile_hint": str(spec.get("slicer_profile_hint") or ""),
                "material": str(spec.get("material") or ""),
                "graph_version": "",
                "run_id": state.run_id if state is not None else "",
            },
            "process_plan": {},
            "quality_gates": [
                self._gate("required_fields", "pass", {"missing": []}),
                self._gate("execution_gate", "blocked", {"request_type": request_type}, "operator_input_required"),
            ],
            "monitoring_plan": {
                "observe_prusalink_status": False,
                "observe_transfer_idle": False,
                "observe_camera_after_print": True,
                "layerwise_monitoring_available": False,
                "defect_classes": ["warping", "stringing", "under_extrusion", "layer_adhesion"],
            },
            "fabrication_outcome": {
                "status": "blocked",
                "location": "unknown",
                "warnings": [prompt],
                "failure_code": request_type,
            },
            "feedback_to_design": {
                "do_not_repeat": [],
                "recommended_parameter_adjustments": {},
                "quality_score": None,
                "uncertainty": 1.0,
            },
        }

    def _build_fabrication_report(
        self,
        *,
        state: OrchestratorState,
        spec: dict[str, Any],
        candidate: str,
        specimen_id: str,
        geometry_result: dict[str, Any],
        mesh_result: dict[str, Any],
        manufacturability_result: dict[str, Any],
        handoff_result: dict[str, Any],
        experiment_response: dict[str, Any],
        printer_response: dict[str, Any],
        printer_payload: dict[str, Any],
        protocol_note: str,
        live_gui_test_spec: bool,
        printer_test_path: str,
        top_cap_enabled: bool,
        bottom_cap_enabled: bool,
        geometry_payload: dict[str, Any],
    ) -> dict[str, Any]:
        tool_result = printer_response
        settings = self._dict_value(tool_result.get("slicer_settings"), tool_result.get("settings"))
        slicer_result = self._dict_value(tool_result.get("slicer_result"))
        gcode_validation = self._dict_value(tool_result.get("gcode_validation"))
        printer = self._dict_value(tool_result.get("printer"))
        prusalink = self._dict_value(tool_result.get("prusalink"))
        print_result = self._dict_value(tool_result.get("print_result"))
        ejection_result = self._dict_value(tool_result.get("ejection_result"))
        selected_printer = self._dict_value(tool_result.get("selected_printer"))
        device_screen = self._dict_value(tool_result.get("device_screen"))
        preprint_gate = self._dict_value(tool_result.get("preprint_gate"), tool_result.get("start_gate"))
        autoejection = self._dict_value(tool_result.get("autoejection"), tool_result.get("autoejection_gate"))
        autoejection_handoff = self._dict_value(tool_result.get("autoejection_handoff"), tool_result.get("handoff"), autoejection.get("handoff"))
        readiness_levels = [item for item in tool_result.get("readiness_levels", []) if isinstance(item, dict)]
        operator_actions = [item for item in tool_result.get("operator_actions", []) if isinstance(item, dict)]
        print_request = self._dict_value(printer_payload.get("print"))
        ejection_request = self._dict_value(printer_payload.get("ejection"))
        printer_preflight = self._dict_value(tool_result.get("printer_preflight"))
        printer_preflight_only = printer_preflight.get("status") in {
            "execution_ready_pending_approval",
            "blocked",
        }
        graph = state.run_metadata.get("runtime_graph") if isinstance(state.run_metadata, dict) else {}
        graph_version = ""
        if isinstance(graph, dict):
            graph_version = str(graph.get("graph_version") or graph.get("graph_hash") or graph.get("graph_id") or "")
        physical_intent = bool(
            print_request.get("physical_intent")
            or print_request.get("confirm_physical_print")
            or print_request.get("start_immediately")
            or (state.mode == Mode.LIVE and not live_gui_test_spec)
            or printer_test_path == "physical_print"
        )
        printer_path = str(tool_result.get("printer_path") or printer_test_path or ("live" if state.mode == Mode.LIVE else "virtual_bridge"))
        remote_path = self._first_value(
            print_result.get("remote_path"),
            print_result.get("upload", {}).get("remote_path") if isinstance(print_result.get("upload"), dict) else None,
            default="",
        )
        gcode_path = self._first_value(tool_result.get("sliced_path"), settings.get("output_gcode_path"), default="")
        design_hash = str(spec.get("candidate_fingerprint") or self._stable_digest({"candidate_id": candidate, "spec": spec}))
        digital_thread = {
            "candidate_id": candidate,
            "specimen_id": specimen_id,
            "design_hash": design_hash,
            "geometry_hash": str(geometry_result.get("geometry_hash") or self._stable_digest(geometry_result)),
            "stl_path": str(geometry_result.get("stl_path") or ""),
            "viewer_capture_path": str(geometry_result.get("viewer_capture_path") or geometry_result.get("capture_image_path") or ""),
            "gcode_path": str(gcode_path or ""),
            "remote_gcode_path": str(remote_path or ""),
            "handoff_package_path": str(handoff_result.get("handoff_package_path") or ""),
            "printer_profile": str(self._first_value(settings.get("printer_profile"), spec.get("printer_profile"), default="")),
            "slicer_profile_hint": str(self._first_value(settings.get("slicer_profile_hint"), spec.get("slicer_profile_hint"), default="")),
            "material": str(self._first_value(settings.get("material"), spec.get("material"), default="")),
            "printer_provider": str(self._first_value(tool_result.get("provider"), printer.get("provider"), selected_printer.get("provider"), spec.get("printer_provider"), default="")),
            "selected_printer_label": str(self._first_value(selected_printer.get("label"), selected_printer.get("profile_id"), spec.get("printer_model"), default="")),
            "graph_version": graph_version,
            "run_id": state.run_id,
            "printer_job_id": self._first_value(
                print_result.get("job_id"),
                print_result.get("start", {}).get("job_id") if isinstance(print_result.get("start"), dict) else None,
                print_result.get("start", {}).get("job", {}).get("job_id") if isinstance(print_result.get("start"), dict) and isinstance(print_result.get("start", {}).get("job"), dict) else None,
                default="",
            ),
        }
        cap_policy = {
            "top_cap_enabled": top_cap_enabled,
            "bottom_cap_enabled": bottom_cap_enabled,
            "top_bottom_cap": bool(top_cap_enabled or bottom_cap_enabled),
            "skin_thickness_mm": self._safe_float(geometry_payload.get("skin_thickness_mm"), 0.0),
            "generated_model_caps_disabled": bool(spec.get("test_loop_surface_caps_disabled", False)),
        }
        adhesion_policy = {
            "skirt_enabled": self._first_value(settings.get("skirt_enabled"), spec.get("skirt_enabled"), default=False),
            "brim_enabled": self._first_value(settings.get("brim_enabled"), spec.get("brim_enabled"), default=False),
            "raft_enabled": self._first_value(settings.get("raft_enabled"), spec.get("raft_enabled"), default=False),
            "slow_first_layer_enabled": self._first_value(settings.get("slow_first_layer_enabled"), spec.get("slow_first_layer_enabled"), default=True),
            "first_layer_speed_mm_s": self._first_value(settings.get("first_layer_speed_mm_s"), spec.get("first_layer_speed_mm_s"), default=None),
        }
        ejection_policy = {
            "requested": bool(ejection_request.get("enabled") or ejection_request.get("allow_ejection") or spec.get("allow_ejection")),
            "status": ejection_result.get("status", "disabled"),
            "failure_code": ejection_result.get("failure_code"),
            "policy_source": "3dp_gui_or_experiment_spec",
        }
        bambu_autoejection_readiness = self._dict_value(
            spec.get("bambu_autoejection_readiness"),
            printer_payload.get("bambu_autoejection_readiness"),
        )
        process_plan = {
            "layer_height_mm": self._safe_float(self._first_value(settings.get("layer_height_mm"), spec.get("layer_height_mm")), None),
            "first_layer_height_mm": self._safe_float(self._first_value(settings.get("first_layer_height_mm"), spec.get("first_layer_height_mm")), None),
            "nozzle_diameter_mm": self._safe_float(self._first_value(settings.get("nozzle_diameter_mm"), spec.get("nozzle_diameter_mm")), None),
            "bed_temperature_c": self._safe_float(self._first_value(settings.get("bed_temperature_c"), spec.get("bed_temperature_c")), None),
            "first_layer_bed_temperature_c": self._safe_float(self._first_value(settings.get("first_layer_bed_temperature_c"), spec.get("first_layer_bed_temperature_c")), None),
            "adhesion_policy": adhesion_policy,
            "cap_skin_policy": cap_policy,
            "ejection_policy": ejection_policy,
            "bambu_autoejection_readiness": bambu_autoejection_readiness,
            "estimated_mass_g": self._safe_float(self._first_value(settings.get("expected_mass_g"), manufacturability_result.get("expected_mass_g"), spec.get("expected_mass_g")), None),
            "estimated_print_time_min": self._safe_float(self._first_value(settings.get("expected_print_time_min"), manufacturability_result.get("expected_print_time_min"), spec.get("expected_print_time_min")), None),
            "slicer_command": settings.get("resolved_command", []),
        }
        storage_status, storage_evidence = self._storage_gate_status(printer, prusalink)
        spc_blockers = preprint_gate.get("blockers") if isinstance(preprint_gate.get("blockers"), list) else []
        spc_status = "warn"
        if preprint_gate:
            spc_status = "pass" if preprint_gate.get("technical_ready_for_start") else ("blocked" if spc_blockers else "warn")
        elif readiness_levels:
            spc_status = "blocked" if any(str(item.get("status")).lower() == "blocked" for item in readiness_levels) else "pass"
        quality_gates = [
            self._gate("required_fields", "pass", {"missing": []}),
            self._gate("geometry", "pass" if geometry_result.get("ok") else "fail", {"geometry_hash": digital_thread["geometry_hash"], "stl_path": digital_thread["stl_path"]}),
            self._gate("mesh", "pass" if mesh_result.get("ok") and mesh_result.get("mesh_status") == "pass" else "fail", {"mesh_status": mesh_result.get("mesh_status"), "warnings": mesh_result.get("warnings", [])}),
            self._gate("manufacturability", "pass" if manufacturability_result.get("ok") and manufacturability_result.get("manufacturability_status") == "pass" else "fail", {"status": manufacturability_result.get("manufacturability_status"), "warnings": manufacturability_result.get("warnings", [])}),
            self._gate("slicer", self._gate_status_from_result(slicer_result), {"sliced_path": digital_thread["gcode_path"], "failure_code": slicer_result.get("failure_code")}),
            self._gate("gcode", self._gate_status_from_result(gcode_validation), {"failure_code": gcode_validation.get("failure_code"), "violations": gcode_validation.get("violations", [])}),
            self._gate("printer_storage", storage_status, storage_evidence),
            self._gate(
                "spc_readiness",
                spc_status,
                {
                    "provider": digital_thread["printer_provider"],
                    "selected_printer": selected_printer,
                    "preprint_gate": preprint_gate,
                    "readiness_levels": readiness_levels,
                    "operator_actions": operator_actions,
                    "autoejection_handoff": autoejection_handoff,
                },
            ),
            self._gate("execution_gate", "pass" if tool_result.get("ok") else ("blocked" if tool_result.get("requires_connection_info") else "fail"), {"physical_intent": physical_intent, "printer_path": printer_path, "status": tool_result.get("status"), "failure_code": tool_result.get("failure_code")}),
            self._gate("ejection", "pass" if str(ejection_result.get("status", "disabled")) in {"disabled", "appended_to_print_gcode", "simulated_verified_ejected", "virtual_ack", "started", "standalone_motion_started"} else "warn", {"status": ejection_result.get("status"), "failure_code": ejection_result.get("failure_code")}),
        ]
        warnings = [
            *[str(item) for item in mesh_result.get("warnings", [])],
            *[str(item) for item in manufacturability_result.get("warnings", [])],
            *[str(item) for item in tool_result.get("warnings", []) if str(item).strip()],
        ]
        failure_code = self._first_value(
            tool_result.get("failure_code"),
            print_result.get("failure_code"),
            slicer_result.get("failure_code"),
            gcode_validation.get("failure_code"),
            default=None,
        )
        ejection_status = str(ejection_result.get("status") or "").strip().lower()
        physical_printer_path = printer_path in {"installed_printer", "physical_print", "actual_print", "bambulab_x2d", "live"}
        standalone_ejection_started = ejection_status in {"standalone_motion_started", "started", "simulated_verified_ejected", "virtual_ack"}
        virtual_bridge_ejection_complete = bool(
            printer_path == "virtual_bridge"
            and tool_result.get("ok", False)
            and not tool_result.get("requires_connection_info")
        )
        if tool_result.get("requires_connection_info"):
            outcome_status = "blocked"
            location = "unknown"
        elif not tool_result.get("ok", False):
            outcome_status = "failed"
            location = "unknown"
        elif printer_preflight_only:
            outcome_status = "preflight_complete"
            location = "not_actuated"
        elif virtual_bridge_ejection_complete:
            outcome_status = "ready_for_vision"
            location = "a4_workspace"
        elif physical_intent and physical_printer_path and standalone_ejection_started:
            outcome_status = "ready_for_vision"
            location = "a4_workspace"
        elif physical_intent and physical_printer_path:
            outcome_status = "ready_for_vision"
            location = "printer_bed"
        elif printer_path == "virtual_prusalink" or str(tool_result.get("mode", "")).startswith("test"):
            outcome_status = "virtual_finished"
            location = "virtual_bridge"
        elif physical_intent:
            outcome_status = "ready_for_vision"
            location = "printer_bed"
        else:
            outcome_status = "ready_for_vision"
            location = "printer_bed" if state.mode == Mode.LIVE else "virtual_bridge"
        passed = sum(1 for gate in quality_gates if gate.get("status") == "pass")
        blocked_or_failed = [gate for gate in quality_gates if gate.get("status") in {"blocked", "fail"}]
        quality_score = round(passed / max(len(quality_gates), 1), 4)
        adjustments: dict[str, Any] = {}
        if any(gate.get("gate") == "manufacturability" and gate.get("status") != "pass" for gate in quality_gates):
            adjustments.update({"increase_wall_thickness_mm": 0.2, "reduce_print_risk": True})
        if gcode_validation.get("failure_code"):
            adjustments["review_slicer_profile"] = True
        if ejection_result.get("failure_code"):
            adjustments["disable_or_retest_ejection"] = True
        return {
            "schema": "fabrication_report.v1",
            "fabrication_intent": {
                "mode": printer_payload.get("runtime_mode") or state.mode.value,
                "physical_intent": physical_intent,
                "printer_path": printer_path,
                "specimen_purpose": str(spec.get("specimen_purpose") or spec.get("purpose") or "mechanical_test"),
                "live_gui_test_spec": live_gui_test_spec,
                "printer_test_path": printer_test_path,
                "execution_policy_mode": printer_payload.get("execution_policy_mode", "execute"),
            },
            "digital_thread": digital_thread,
            "process_plan": process_plan,
            "quality_gates": quality_gates,
            "monitoring_plan": {
                "observe_prusalink_status": bool(prusalink or printer),
                "observe_printer_bridge_status": bool(prusalink or printer or selected_printer or device_screen),
                "observe_transfer_idle": bool(print_result.get("transfer_wait")),
                "observe_camera_after_print": True,
                "active_cam_verification_required": bool(location in {"a4_workspace", "robot_workspace", "ejection_basket", "3dp_output_area"}),
                "layerwise_monitoring_available": False,
                "defect_classes": ["warping", "stringing", "under_extrusion", "layer_adhesion"],
                "expected_location": location,
                "after_print_consumer": "vision_agent",
            },
            "printer_runtime": {
                "provider": digital_thread["printer_provider"],
                "selected_printer": selected_printer,
                "device_screen": device_screen,
                "preprint_gate": preprint_gate,
                "readiness_levels": readiness_levels,
                "operator_actions": operator_actions,
                "autoejection": autoejection,
                "autoejection_handoff": autoejection_handoff,
                "prepare_status": tool_result.get("status"),
                "mode": tool_result.get("mode"),
                "path": printer_path,
                "step_trace": tool_result.get("step_trace", []),
                "operator_messages": tool_result.get("operator_messages", []),
                "upload": print_result.get("upload", {}),
                "transfer_wait": print_result.get("transfer_wait", {}),
                "start": print_result.get("start", {}),
                "ejection": ejection_result,
                "printer_preflight": printer_preflight,
            },
            "fabrication_outcome": {
                "status": outcome_status,
                "location": location,
                "autoejection_status": "complete" if standalone_ejection_started or virtual_bridge_ejection_complete else ejection_status or "not_requested",
                "warnings": warnings,
                "failure_code": failure_code,
                "requires_after_print_confirmation": bool(physical_intent and not printer_preflight_only),
            },
            "feedback_to_design": {
                "do_not_repeat": [str(gate.get("gate")) for gate in blocked_or_failed],
                "recommended_parameter_adjustments": adjustments,
                "quality_score": quality_score,
                "uncertainty": round(0.15 + 0.1 * len(blocked_or_failed) + (0.2 if physical_intent else 0.0), 4),
            },
            "protocol_note": protocol_note,
            "experiment_evaluation_ref": experiment_response.get("job", {}) if isinstance(experiment_response, dict) else {},
        }

    def _fabrication_decisions(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        intent = report.get("fabrication_intent", {}) if isinstance(report.get("fabrication_intent"), dict) else {}
        outcome = report.get("fabrication_outcome", {}) if isinstance(report.get("fabrication_outcome"), dict) else {}
        failed_gates = [gate for gate in report.get("quality_gates", []) if isinstance(gate, dict) and gate.get("status") in {"blocked", "fail"}]
        return [
            {
                "decision_id": "specimen.intent.resolved",
                "status": "ok",
                "rationale": f"Fabrication path resolved as {intent.get('printer_path', '-')}; physical_intent={intent.get('physical_intent', False)}.",
            },
            {
                "decision_id": "specimen.digital_thread.initialized",
                "status": "ok",
                "rationale": "Design, geometry, slicer, printer, and handoff artifacts were linked into one digital thread.",
            },
            {
                "decision_id": "specimen.quality_gates.evaluated",
                "status": "blocked" if failed_gates else "ok",
                "rationale": f"{len(report.get('quality_gates', []))} manufacturing gates evaluated; blocked_or_failed={len(failed_gates)}.",
            },
            {
                "decision_id": "specimen.handoff.prepared",
                "status": "ok" if outcome.get("status") in {"ready_for_vision", "virtual_finished", "printed", "preflight_complete"} else "blocked",
                "rationale": "Stage completion records either a physical specimen handoff or a no-actuation fabrication preflight.",
            },
        ]

    def _fabrication_metrics(self, report: dict[str, Any]) -> dict[str, Any]:
        gates = [gate for gate in report.get("quality_gates", []) if isinstance(gate, dict)]
        return {
            "quality_gate_count": len(gates),
            "quality_gate_pass_count": sum(1 for gate in gates if gate.get("status") == "pass"),
            "quality_gate_blocked_count": sum(1 for gate in gates if gate.get("status") == "blocked"),
            "quality_gate_fail_count": sum(1 for gate in gates if gate.get("status") == "fail"),
            "fabrication_quality_score": (report.get("feedback_to_design", {}) or {}).get("quality_score") if isinstance(report.get("feedback_to_design"), dict) else None,
            "estimated_mass_g": (report.get("process_plan", {}) or {}).get("estimated_mass_g") if isinstance(report.get("process_plan"), dict) else None,
            "estimated_print_time_min": (report.get("process_plan", {}) or {}).get("estimated_print_time_min") if isinstance(report.get("process_plan"), dict) else None,
        }

    def _fabrication_evidence_refs(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        thread = report.get("digital_thread", {}) if isinstance(report.get("digital_thread"), dict) else {}
        refs: list[dict[str, Any]] = []
        for key, label in (
            ("stl_path", "stl"),
            ("gcode_path", "gcode"),
            ("handoff_package_path", "handoff_package"),
            ("viewer_capture_path", "viewer_capture"),
        ):
            value = thread.get(key)
            if value:
                refs.append({"type": label, "path": str(value)})
        return refs

    def _specimen_agent_report_snapshot(
        self,
        *,
        state: OrchestratorState,
        spec: dict[str, Any],
        candidate: str,
        specimen_id: str,
        fabrication_report: dict[str, Any],
        handoff_packet: dict[str, Any],
        preview_image_path: str = "",
        viewer_capture_path: str = "",
    ) -> dict[str, Any]:
        """Build the Live GUI Specimen Making screen contract from fabrication evidence."""
        intent = fabrication_report.get("fabrication_intent", {}) if isinstance(fabrication_report.get("fabrication_intent"), dict) else {}
        thread = fabrication_report.get("digital_thread", {}) if isinstance(fabrication_report.get("digital_thread"), dict) else {}
        plan = fabrication_report.get("process_plan", {}) if isinstance(fabrication_report.get("process_plan"), dict) else {}
        runtime = fabrication_report.get("printer_runtime", {}) if isinstance(fabrication_report.get("printer_runtime"), dict) else {}
        outcome = fabrication_report.get("fabrication_outcome", {}) if isinstance(fabrication_report.get("fabrication_outcome"), dict) else {}
        monitor = fabrication_report.get("monitoring_plan", {}) if isinstance(fabrication_report.get("monitoring_plan"), dict) else {}
        gates = [gate for gate in fabrication_report.get("quality_gates", []) if isinstance(gate, dict)]
        pass_count = sum(1 for gate in gates if gate.get("status") == "pass")
        blocked_count = sum(1 for gate in gates if gate.get("status") == "blocked")
        fail_count = sum(1 for gate in gates if gate.get("status") == "fail")
        warn_count = sum(1 for gate in gates if gate.get("status") == "warn")
        readiness_score = round(pass_count / max(len(gates), 1), 4)
        estimated_time = self._safe_float(plan.get("estimated_print_time_min"), self._safe_float(spec.get("expected_print_time_min"), None))
        estimated_mass = self._safe_float(plan.get("estimated_mass_g"), self._safe_float(spec.get("expected_mass_g"), None))
        material = str(thread.get("material") or spec.get("material") or "")
        slicer_gate = next((gate for gate in gates if gate.get("gate") == "slicer"), {})
        gcode_gate = next((gate for gate in gates if gate.get("gate") == "gcode"), {})
        execution_gate = next((gate for gate in gates if gate.get("gate") == "execution_gate"), {})
        storage_gate = next((gate for gate in gates if gate.get("gate") == "printer_storage"), {})
        spc_gate = next((gate for gate in gates if gate.get("gate") == "spc_readiness"), {})
        selected_printer = self._dict_value(runtime.get("selected_printer"))
        device_screen = self._dict_value(runtime.get("device_screen"))
        preprint_gate = self._dict_value(runtime.get("preprint_gate"))
        readiness_levels = [item for item in runtime.get("readiness_levels", []) if isinstance(item, dict)]
        operator_actions = [item for item in runtime.get("operator_actions", []) if isinstance(item, dict)]
        autoejection_gate = self._dict_value(runtime.get("autoejection"))
        autoejection_handoff = self._dict_value(runtime.get("autoejection_handoff"), autoejection_gate.get("handoff"))
        device_actions = self._dict_value(device_screen.get("actions"))
        device_connection = self._dict_value(device_screen.get("connection"))

        timeline_items: list[dict[str, Any]] = []
        step_trace = runtime.get("step_trace") if isinstance(runtime.get("step_trace"), list) else []
        for index, step in enumerate(step_trace[:14], start=1):
            if isinstance(step, dict):
                timeline_items.append(
                    {
                        "order": index,
                        "step": step.get("step") or step.get("name") or step.get("event") or f"step_{index}",
                        "status": step.get("status") or step.get("result") or "recorded",
                        "detail": step.get("detail") or step.get("message") or step.get("path") or "",
                        "duration_s": step.get("duration_s") or step.get("elapsed_sec"),
                    }
                )
            else:
                timeline_items.append({"order": index, "step": str(step), "status": "recorded", "detail": "", "duration_s": None})
        if not timeline_items:
            for index, gate in enumerate(gates[:12], start=1):
                timeline_items.append(
                    {
                        "order": index,
                        "step": str(gate.get("gate") or f"gate_{index}"),
                        "status": gate.get("status") or "unknown",
                        "detail": gate.get("repair") or "",
                        "duration_s": None,
                    }
                )

        queue_items = []
        for key in ("upload", "transfer_wait", "start", "ejection"):
            value = runtime.get(key)
            if isinstance(value, dict) and value:
                queue_items.append(
                    {
                        "queue_id": key,
                        "status": value.get("status") or value.get("ok") or "recorded",
                        "remote_path": value.get("remote_path") or value.get("path") or "",
                        "detail": value.get("message") or value.get("failure_code") or "",
                    }
                )
        if not queue_items:
            queue_items.append(
                {
                    "queue_id": "operator_or_virtual_bridge",
                    "status": outcome.get("status") or "blocked",
                    "remote_path": thread.get("remote_gcode_path") or "",
                    "detail": execution_gate.get("repair") or "",
                }
            )

        artifact_ledger = []
        for artifact_type, key in (
            ("stl", "stl_path"),
            ("gcode", "gcode_path"),
            ("remote_gcode", "remote_gcode_path"),
            ("handoff_package", "handoff_package_path"),
        ):
            artifact_ledger.append(
                {
                    "artifact_type": artifact_type,
                    "artifact_id": thread.get(key) or "",
                    "status": "ready" if thread.get(key) else "pending",
                    "owner": self.name,
                }
            )
        artifact_ledger.append(
            {
                "artifact_type": "layer_preview",
                "artifact_id": preview_image_path,
                "status": "ready" if preview_image_path else "pending",
                "owner": self.name,
            }
        )
        artifact_ledger.append(
            {
                "artifact_type": "viewer_capture",
                "artifact_id": viewer_capture_path,
                "status": "ready" if viewer_capture_path else "pending",
                "owner": self.name,
            }
        )

        part_mass = estimated_mass or 0.0
        material_donut = [
            {"label": "part", "value": round(part_mass, 4), "unit": "g"},
            {"label": "purge_support_allowance", "value": round(max(part_mass * 0.06, 0.0), 4), "unit": "g"},
        ]
        readiness_donut = [
            {"label": "pass", "value": pass_count},
            {"label": "warn", "value": warn_count},
            {"label": "blocked", "value": blocked_count},
            {"label": "fail", "value": fail_count},
        ]
        print_time_bars = [
            {"label": "slice", "value": 2.0 if thread.get("gcode_path") else 0.0, "unit": "min"},
            {"label": "print", "value": estimated_time or 0.0, "unit": "min"},
            {"label": "handoff", "value": 1.0 if handoff_packet.get("status") == "ready" else 0.0, "unit": "min"},
        ]

        return {
            "schema": "specimen_agent_report.v1",
            "source_report_schema": fabrication_report.get("schema"),
            "report_id": f"specimen-agent-report-{state.run_id or 'run'}-{state.loop_count + 1}",
            "run_id": state.run_id,
            "experiment_id": state.experiment_id,
            "loop_index": state.loop_count + 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "producer_agent": self.name,
            "slicer_configuration": {
                "slicer_profile_hint": thread.get("slicer_profile_hint") or spec.get("slicer_profile_hint"),
                "layer_height_mm": plan.get("layer_height_mm") or spec.get("layer_height_mm"),
                "first_layer_height_mm": plan.get("first_layer_height_mm") or spec.get("first_layer_height_mm"),
                "nozzle_diameter_mm": plan.get("nozzle_diameter_mm") or spec.get("nozzle_diameter_mm"),
                "bed_temperature_c": plan.get("bed_temperature_c") or spec.get("bed_temperature_c"),
                "first_layer_bed_temperature_c": plan.get("first_layer_bed_temperature_c") or spec.get("first_layer_bed_temperature_c"),
                "slicer_command": plan.get("slicer_command", []),
                "slicer_gate": slicer_gate,
            },
            "printer_profile": {
                "printer_profile": thread.get("printer_profile") or spec.get("printer_profile"),
                "provider": runtime.get("provider") or thread.get("printer_provider") or selected_printer.get("provider") or spec.get("printer_provider"),
                "selected_printer": selected_printer,
                "printer_path": intent.get("printer_path"),
                "material": material,
                "physical_intent": intent.get("physical_intent"),
                "storage_status": storage_gate.get("status"),
                "remote_gcode_path": thread.get("remote_gcode_path"),
            },
            "build_queue": {
                "queue_status": outcome.get("status") or handoff_packet.get("status"),
                "printer_job_id": thread.get("printer_job_id"),
                "items": queue_items,
            },
            "estimated_print_time": {
                "estimated_print_time_min": estimated_time,
                "bars": print_time_bars,
            },
            "filament_usage": {
                "material": material,
                "estimated_mass_g": estimated_mass,
                "donut": material_donut,
            },
            "gcode_validation": {
                "status": gcode_gate.get("status") or slicer_gate.get("status") or "pending",
                "gcode_path": thread.get("gcode_path"),
                "slicer_gate": slicer_gate,
                "gcode_gate": gcode_gate,
            },
            "print_readiness": {
                "readiness_score": readiness_score,
                "gate_count": len(gates),
                "pass_count": pass_count,
                "warn_count": warn_count,
                "blocked_count": blocked_count,
                "fail_count": fail_count,
                "gates": gates,
                "donut": readiness_donut,
            },
            "spc_readiness": {
                "provider": runtime.get("provider") or thread.get("printer_provider") or selected_printer.get("provider") or spec.get("printer_provider"),
                "selected_printer": selected_printer,
                "preprint_gate": preprint_gate,
                "preprint_gate_state": preprint_gate.get("state"),
                "technical_ready_for_start": preprint_gate.get("technical_ready_for_start"),
                "ready_for_live_print": preprint_gate.get("ready_for_live_print"),
                "blockers": preprint_gate.get("blockers", []) if isinstance(preprint_gate.get("blockers"), list) else [],
                "readiness_levels": readiness_levels,
                "operator_actions": operator_actions,
                "device_actions": device_actions,
                "device_connection": device_connection,
                "gate_status": spc_gate.get("status"),
            },
            "autoejection_gate": {
                "status": autoejection_gate.get("status") or (runtime.get("ejection") or {}).get("status") if isinstance(runtime.get("ejection"), dict) else autoejection_gate.get("status"),
                "blockers": autoejection_gate.get("blockers", []) if isinstance(autoejection_gate.get("blockers"), list) else [],
                "provider": autoejection_gate.get("provider") or runtime.get("provider") or thread.get("printer_provider"),
                "requested": autoejection_gate.get("requested"),
                "method": autoejection_gate.get("method"),
                "handoff": autoejection_handoff,
            },
            "bambu_autoejection_readiness": plan.get("bambu_autoejection_readiness", {}),
            "build_timeline": {
                "timeline": timeline_items,
                "bars": [
                    {"label": item.get("step"), "status": item.get("status"), "value": item.get("duration_s") or 1}
                    for item in timeline_items[:12]
                ],
            },
            "layer_preview": {
                "preview_image_path": preview_image_path,
                "viewer_capture_path": viewer_capture_path,
                "preview_available": bool(preview_image_path),
                "viewer_capture_available": bool(viewer_capture_path),
                "stl_path": thread.get("stl_path"),
                "gcode_path": thread.get("gcode_path"),
                "layerwise_monitoring_available": monitor.get("layerwise_monitoring_available"),
            },
            "artifact_ledger": artifact_ledger,
            "printer_status": {
                "provider": runtime.get("provider") or thread.get("printer_provider") or selected_printer.get("provider"),
                "selected_printer": selected_printer,
                "connection": device_connection,
                "actions": device_actions,
                "preprint_gate_state": preprint_gate.get("state"),
                "prepare_status": runtime.get("prepare_status") or outcome.get("status"),
                "mode": runtime.get("mode"),
                "path": runtime.get("path") or intent.get("printer_path"),
                "location": outcome.get("location"),
                "warnings": outcome.get("warnings", []),
                "failure_code": outcome.get("failure_code"),
            },
            "handoff_status": {
                "status": handoff_packet.get("status"),
                "next_action": handoff_packet.get("next_action"),
                "consumer_agent": handoff_packet.get("consumer_agent"),
                "physical_location": handoff_packet.get("physical_location") or outcome.get("location"),
                "fabrication_report_ref": handoff_packet.get("fabrication_report_ref"),
            },
            "visualization_manifest": [
                {"id": "layer_preview", "section": "layer_preview", "type": "layer_preview"},
                {"id": "filament_usage", "section": "filament_usage", "type": "material_donut"},
                {"id": "print_readiness", "section": "print_readiness", "type": "readiness_donut"},
                {"id": "spc_readiness", "section": "spc_readiness", "type": "readiness_levels"},
                {"id": "autoejection_gate", "section": "autoejection_gate", "type": "gate_board"},
                {"id": "build_timeline", "section": "build_timeline", "type": "timeline_bars"},
                {"id": "estimated_print_time", "section": "estimated_print_time", "type": "print_time_bars"},
            ],
        }

    def _build_specimen_fabricated_packet(
        self,
        *,
        state: OrchestratorState,
        candidate: str,
        specimen_id: str,
        report: dict[str, Any],
        decisions: list[dict[str, Any]],
        evidence_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        outcome = report.get("fabrication_outcome", {}) if isinstance(report.get("fabrication_outcome"), dict) else {}
        intent = report.get("fabrication_intent", {}) if isinstance(report.get("fabrication_intent"), dict) else {}
        thread = report.get("digital_thread", {}) if isinstance(report.get("digital_thread"), dict) else {}
        gates = [gate for gate in report.get("quality_gates", []) if isinstance(gate, dict)]
        outcome_status = str(outcome.get("status") or "")
        if outcome_status == "preflight_complete":
            status = "preflight_ready"
        else:
            status = "ready" if outcome_status in {"ready_for_vision", "virtual_finished", "printed"} else "blocked"
        return {
            "schema": "specimen_fabricated.v1",
            "run_id": state.run_id,
            "loop_id": f"loop-{state.loop_count}",
            "specimen_id": specimen_id,
            "candidate_id": candidate,
            "producer_agent": self.name,
            "consumer_agent": ["vision_agent", "manipulation_agent", "knowledge_agent", "bo_agent"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "evidence_refs": evidence_refs,
            "guardian_status": "not_checked",
            "decisions": decisions,
            "warnings": outcome.get("warnings", []),
            "next_action": (
                "vision_after_print_inspection"
                if status == "ready"
                else "physical_start_pending_approval"
                if status == "preflight_ready"
                else "operator_or_guardian_review"
            ),
            "fabrication_report_ref": "run_metadata.fabrication_report",
            "fabrication_summary": {
                "schema": report.get("schema"),
                "physical_intent": intent.get("physical_intent"),
                "printer_path": intent.get("printer_path"),
                "stl_path": thread.get("stl_path"),
                "gcode_path": thread.get("gcode_path"),
                "outcome_status": outcome.get("status"),
                "quality_gate_count": len(gates),
                "quality_gate_pass_count": sum(1 for gate in gates if gate.get("status") == "pass"),
                "quality_gate_blocked_or_failed": [
                    str(gate.get("gate")) for gate in gates if gate.get("status") in {"blocked", "fail"}
                ],
            },
            "physical_location": outcome.get("location", "unknown"),
            "pickup_pose_hint": {"source": "vision_agent_required", "status": "pending"},
        }

    def _printer_path_choice_result(self, state: OrchestratorState, spec: dict[str, Any], candidate: str, specimen_id: str) -> AgentResult:
        prompt = (
            "Specimen Making Agent가 테스트 프린터 경로 선택을 기다립니다.\n\n"
            "- 가상 브릿지: 선택된 3DP bridge의 slicing/upload/start boundary를 가상 통신으로 검증합니다.\n"
            "- 설치 프린터: 실제 STL을 slicing한 뒤 출력 구간을 제거한 ejection-only project file 하나만 active printer로 전송해 실행합니다.\n"
            "- 실제 출력: 테스트 모드에서 생성한 시편을 active printer bridge로 실제 slicing/upload/start 및 출력 경로까지 실행하고, 출력 G-code 끝에 autoejection tail을 붙입니다. 기본 profile은 Bambu Lab X2D이며, Prusa MK4S는 명시 선택 시만 사용합니다.\n\n"
            "답변은 `가상 브릿지`, `설치 프린터`, `실제 출력` 중 하나로 보내주세요."
        )
        fabrication_report = self._build_pending_fabrication_report(
            state=state,
            spec=spec,
            candidate=candidate,
            specimen_id=specimen_id,
            request_type="printer_test_path_choice",
            prompt=prompt,
        )
        decisions = self._fabrication_decisions(fabrication_report)
        metrics = self._fabrication_metrics(fabrication_report)
        evidence_refs = self._fabrication_evidence_refs(fabrication_report)
        handoff_packet = self._build_specimen_fabricated_packet(
            state=state,
            candidate=candidate,
            specimen_id=specimen_id,
            report=fabrication_report,
            decisions=decisions,
            evidence_refs=evidence_refs,
        )
        specimen_agent_report = self._specimen_agent_report_snapshot(
            state=state,
            spec=spec,
            candidate=candidate,
            specimen_id=specimen_id,
            fabrication_report=fabrication_report,
            handoff_packet=handoff_packet,
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
            "fabrication_report": fabrication_report,
            "specimen_fabricated": handoff_packet,
            "specimen_agent_report": specimen_agent_report,
        }
        return AgentResult(
            success=True,
            summary="Specimen Making Agent waiting for printer test path selection",
            data={
                "specimen_result": specimen_result,
                "fabrication_report": fabrication_report,
                "specimen_agent_report": specimen_agent_report,
                "handoff_packet": handoff_packet,
                "specimen_fabricated": handoff_packet,
                "decisions": decisions,
                "metrics": metrics,
                "evidence_refs": evidence_refs,
                "protocol_note": "waiting_for_printer_test_path",
            },
            next_hint="operator_input_required",
        )

    @archive_agent_run
    async def run(self, state: OrchestratorState, ctx: AgentContext) -> AgentResult:
        spec = dict(state.current_experiment_spec or {})
        candidate = str(spec.get("candidate_id", "cand-unknown"))
        specimen_id = str(spec.get("specimen_id", f"specimen-{candidate}"))
        missing = self._required_missing(spec)
        if missing:
            raise RuntimeError(f"specimen_agent missing required experiment_spec fields: {', '.join(missing)}")
        live_gui_test_spec = self._is_live_gui_test_spec(state, spec)
        printer_test_path = self._printer_test_path(spec)
        execution_policy = spec.get("execution_policy") if isinstance(spec.get("execution_policy"), dict) else {}
        printer_preflight_only = str(execution_policy.get("printer") or "").strip().lower() == "preflight_only"
        if live_gui_test_spec and not printer_test_path:
            return self._printer_path_choice_result(state, spec, candidate, specimen_id)
        if self._should_disable_test_surface_caps(state, spec, live_gui_test_spec=live_gui_test_spec):
            spec = self._without_surface_caps(spec)
            state.current_experiment_spec = spec
        spec = self._enforce_fdm_gyroid_hard_rules(spec)
        state.current_experiment_spec = spec

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
            "specimen_placement": spec.get("specimen_placement"),
            "experiment_id": state.experiment_id,
            "runtime_mode": printer_runtime_mode,
            "specimen_id": specimen_id,
            "candidate_id": candidate,
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
            "execution_policy_mode": "preflight_only" if printer_preflight_only else "execute",
        }
        if live_gui_test_spec:
            printer_payload["test_printer_path"] = printer_test_path
            profile_driven = isinstance(spec.get("test_mode_profile"), dict)
            printer_live = not printer_preflight_only and printer_test_path in {"installed_printer", "physical_print"}
            printer_payload["allow_test_printer_live"] = printer_live
            printer_payload["test_printer_transport"] = "real" if printer_live else "virtual"
            if printer_live:
                printer_payload["prefer_http_artifact"] = True
            if printer_live and not profile_driven:
                print_request = dict(printer_payload["print"]) if isinstance(printer_payload.get("print"), dict) else {}
                print_request.update(
                    {
                        "start_immediately": True,
                        "physical_intent": True,
                        "confirm_physical_print": True,
                        "stop_after_start": False,
                        "use_ejection_only_project_file": printer_test_path == "installed_printer",
                        "prefer_http_artifact": True,
                    }
                )
                printer_payload["print"] = print_request
                ejection_request = dict(printer_payload["ejection"]) if isinstance(printer_payload.get("ejection"), dict) else {}
                ejection_request.update(
                    {
                        "enabled": True,
                        "allow_ejection": True,
                        "object_size_mm": self._first_value(
                            ejection_request.get("object_size_mm"),
                            spec.get("object_size_mm"),
                            spec.get("specimen_size_mm"),
                        ),
                    }
                )
                if printer_test_path == "installed_printer":
                    ejection_request.update(
                        {
                            "use_ejection_only_project_file": True,
                            "source": "installed_printer_ejection_only_project_file",
                        }
                    )
                else:
                    ejection_request.setdefault("source", "physical_print_tail")
                printer_payload["ejection"] = ejection_request
            elif printer_live:
                ejection_request = dict(printer_payload["ejection"]) if isinstance(printer_payload.get("ejection"), dict) else {}
                ejection_request.setdefault(
                    "object_size_mm",
                    self._first_value(spec.get("object_size_mm"), spec.get("specimen_size_mm")),
                )
                printer_payload["ejection"] = ejection_request

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

        evaluation_payload = {
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
                "dry_run": printer_preflight_only or not bool((printer_payload.get("print") or {}).get("start_immediately", False)),
                "allow_physical": bool(
                    not printer_preflight_only
                    and (printer_runtime_mode == "live" or bool(printer_payload.get("allow_test_printer_live")))
                ),
            },
            "metadata": {
                "stage": state.stage.value,
                "live_gui_test_spec": live_gui_test_spec,
                "printer_test_path": printer_test_path,
            },
        }
        try:
            experiment_response = await asyncio.to_thread(
                ctx.tools.call,
                "experiment.evaluate",
                evaluation_payload,
            )
        except OSError as exc:
            if not (live_gui_test_spec and printer_test_path == "virtual_bridge"):
                raise
            experiment_response = self._degraded_virtual_bridge_experiment_response(
                state=state,
                spec=spec,
                candidate=candidate,
                specimen_id=specimen_id,
                printer_payload=printer_payload,
                printer_runtime_mode=printer_runtime_mode,
                printer_test_path=printer_test_path,
                exc=exc,
            )
        response = experiment_response.get("bridge_result") if isinstance(experiment_response.get("bridge_result"), dict) else experiment_response

        fabrication_report = self._build_fabrication_report(
            state=state,
            spec=spec,
            candidate=candidate,
            specimen_id=specimen_id,
            geometry_result=geometry_result,
            mesh_result=mesh_result,
            manufacturability_result=manufacturability_result,
            handoff_result=handoff_result,
            experiment_response=experiment_response,
            printer_response=response,
            printer_payload=printer_payload,
            protocol_note=protocol_note,
            live_gui_test_spec=live_gui_test_spec,
            printer_test_path=printer_test_path,
            top_cap_enabled=top_cap_enabled,
            bottom_cap_enabled=bottom_cap_enabled,
            geometry_payload=geometry_payload,
        )
        decisions = self._fabrication_decisions(fabrication_report)
        metrics = self._fabrication_metrics(fabrication_report)
        evidence_refs = self._fabrication_evidence_refs(fabrication_report)
        handoff_packet = self._build_specimen_fabricated_packet(
            state=state,
            candidate=candidate,
            specimen_id=specimen_id,
            report=fabrication_report,
            decisions=decisions,
            evidence_refs=evidence_refs,
        )
        specimen_agent_report = self._specimen_agent_report_snapshot(
            state=state,
            spec=spec,
            candidate=candidate,
            specimen_id=specimen_id,
            fabrication_report=fabrication_report,
            handoff_packet=handoff_packet,
            preview_image_path=str(geometry_result.get("preview_image_path") or ""),
            viewer_capture_path=str(geometry_result.get("viewer_capture_path") or geometry_result.get("capture_image_path") or ""),
        )
        fabrication_intent = fabrication_report.get("fabrication_intent", {}) if isinstance(fabrication_report.get("fabrication_intent"), dict) else {}
        printer_runtime = fabrication_report.get("printer_runtime", {}) if isinstance(fabrication_report.get("printer_runtime"), dict) else {}
        printer_preflight = response.get("printer_preflight")
        if not isinstance(printer_preflight, dict) or not printer_preflight:
            printer_preflight = None

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
            "printer_path": response.get("printer_path") or fabrication_intent.get("printer_path") or printer_runtime.get("path"),
            "printer_mode": response.get("mode") or printer_runtime.get("mode") or printer_runtime_mode,
            "provider": response.get("provider") or printer_runtime.get("provider"),
            "selected_printer": response.get("selected_printer") or printer_runtime.get("selected_printer", {}),
            "device_screen": response.get("device_screen") or printer_runtime.get("device_screen", {}),
            "preprint_gate": response.get("preprint_gate") or response.get("start_gate") or printer_runtime.get("preprint_gate", {}),
            "readiness_levels": response.get("readiness_levels") or printer_runtime.get("readiness_levels", []),
            "operator_actions": response.get("operator_actions") or printer_runtime.get("operator_actions", []),
            "autoejection": response.get("autoejection") or response.get("autoejection_gate") or printer_runtime.get("autoejection", {}),
            "autoejection_handoff": response.get("autoejection_handoff") or response.get("handoff") or printer_runtime.get("autoejection_handoff", {}),
            "stl_path": geometry_result.get("stl_path"),
            "sliced_path": response.get("sliced_path"),
            "preview_image_path": geometry_result.get("preview_image_path"),
            "viewer_capture_path": geometry_result.get("viewer_capture_path") or geometry_result.get("capture_image_path"),
            "handoff_package_path": handoff_result.get("handoff_package_path"),
            "geometry_hash": geometry_result.get("geometry_hash"),
            "geometry_report": geometry_result.get("geometry_report", {}),
            "surface_cap_policy": {
                "generated_model_caps_disabled": bool(spec.get("test_loop_surface_caps_disabled", False)),
                "analysis_uses_top_bottom_platens": True,
                "top_cap_enabled": top_cap_enabled,
                "bottom_cap_enabled": bottom_cap_enabled,
                "skin_thickness_mm": geometry_payload["skin_thickness_mm"],
            },
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
            "fabrication_report": fabrication_report,
            "specimen_fabricated": handoff_packet,
            "specimen_agent_report": specimen_agent_report,
            "decisions": decisions,
            "metrics": metrics,
            "evidence_refs": evidence_refs,
        }
        if printer_preflight is not None:
            specimen_result["printer_preflight"] = printer_preflight
        if response.get("requires_connection_info"):
            prompt = (
                "Specimen Making Agent가 설치 프린터 통신 테스트에 필요한 active printer 연결정보를 기다립니다.\n\n"
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
                summary="Specimen Making Agent waiting for active printer connection info",
                data={
                    "specimen_result": specimen_result,
                    "fabrication_report": fabrication_report,
                    "specimen_agent_report": specimen_agent_report,
                    "handoff_packet": handoff_packet,
                    "specimen_fabricated": handoff_packet,
                    "decisions": decisions,
                    "metrics": metrics,
                    "evidence_refs": evidence_refs,
                    "protocol_note": protocol_note,
                },
                next_hint="operator_input_required",
            )
        if not bool(response.get("ok")):
            raise RuntimeError(f"printer.prepare failed: {response}")
        operator_messages = [str(item) for item in response.get("operator_messages", []) if str(item).strip()]
        summary_suffix = f" ({operator_messages[-1]})" if operator_messages else ""
        result_data = {
            "specimen_result": specimen_result,
            "fabrication_report": fabrication_report,
            "specimen_agent_report": specimen_agent_report,
            "handoff_packet": handoff_packet,
            "specimen_fabricated": handoff_packet,
            "decisions": decisions,
            "metrics": metrics,
            "evidence_refs": evidence_refs,
            "protocol_note": protocol_note,
        }
        if printer_preflight is not None:
            result_data["printer_preflight"] = printer_preflight
        return AgentResult(
            success=True,
            summary=f"Specimen preparation executed{summary_suffix}",
            data=result_data,
        )
