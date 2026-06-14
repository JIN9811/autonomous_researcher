"""
File purpose:
- FastAPI entrypoint exposing runtime control APIs and web dashboard.

Key classes/functions:
- app
- start_run
- stream_events

Inputs/outputs:
- Input: HTTP control requests and SSE subscriptions
- Output: state snapshots and live orchestration events

Dependencies:
- fastapi
- app.bootstrap.load_runtime

Modification guide:
- Safe places to edit: endpoint payload fields and response shapes
- Risky places to edit: SSE formatting and lifecycle behavior
- Related files: app/controller.py, web/static/app.js
"""

from __future__ import annotations

import asyncio
import csv
import ctypes
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import yaml
import httpx
from dotenv import dotenv_values
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from self_evolution import EvolutionTaskCreate, SelfEvolutionService
from self_evolution.models import EvolutionActivationRequest, EvolutionRollbackRequest

from agents.manipulation_agent import ManipulationAgent
from agents.bo_agent import BOAgent
from agents.equipment_agent import LabEquipmentAgent
from app.bootstrap import load_runtime
from graphs import ATRLangGraphCompiler, GraphConfig, GraphVersionStore, HandlerRegistry, ModuleConfig, ModuleConfigStore, load_graph_config
from graphs.generated_adapter import GENERATED_MODULE_HANDLER_ID, generated_adapter_enabled, generated_adapter_path, validate_generated_adapter_file
from knowledge.graph_backend import graph_backend_from_env
from knowledge.graph_importer import import_store_to_graph
from knowledge.graphify_bridge import import_project_graph, scan_project_graph
from knowledge.schemas import EvolutionOutcomeRecord
from knowledge.stores import JsonlKnowledgeStore
from device_bridges.bambu_bridge import (
    BambuConnectionMemory,
    BambuStudioSlicerRunner,
    PrinterDeviceBridgeManager,
    build_bambu_project_file_command_draft,
)
from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from device_bridges.prusa_bridge import PrusaBridgeConfig, PrinterAgenticWorkflow
from device_bridges.windows_pyautogui_bridge import (
    WindowsPyAutoGUIBridge,
    WindowsPyAutoGUIBridgeConfig,
    discover_windows_pyautogui_bridges,
)
from orchestrator.state import Mode, OrchestratorState, Stage
from orchestrator.supervisor import build_mission_contract, build_orchestration_plan, build_orchestrator_control_plane_snapshot
from policies.guardian_gate import gate_blocks_execution, guardian_gate
from utils.config_loader import load_all_configs
from utils.manipulation_profile import (
    MANIPULATION_AGENT_PROFILE_PATH,
    load_manipulation_agent_profile,
    normalize_manipulation_agent_profile,
    save_manipulation_agent_profile,
)
from utils.ids import make_event_id
from utils.paths import resolve_path
from utils.printer_profile import (
    PRUSA_PRINT_PROFILE_PATH,
    adapt_print_profile_for_provider,
    load_prusa_print_profile,
    save_prusa_print_profile,
)

app = FastAPI(title="Autonomous Researcher")
templates = Jinja2Templates(directory=str(resolve_path("web/templates")))
app.mount("/static", StaticFiles(directory=str(resolve_path("web/static"))), name="static")


@app.get("/favicon.ico", include_in_schema=False)
@app.head("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """Serve the ATR GUI favicon for browser default icon requests."""
    return FileResponse(resolve_path("web/static/favicon.svg"), media_type="image/svg+xml")

controller = load_runtime()
AGENT_BASELINE_DOC_PATH = resolve_path("docs/runtime/agent_program_baseline.md")
BO_WORKSPACE_SETTINGS_PATH = resolve_path("memory/bo_workspace_settings.json")
CAE_WORKSPACE_SETTINGS_PATH = resolve_path("memory/cae_workspace_settings.json")
SELF_EVOLUTION_ROOT = resolve_path("memory/evolution")
KNOWLEDGE_MEMORY_ROOT = resolve_path("memory/knowledge")
PRIMARY_RUNTIME_GRAPH_ID = "atr_closed_loop"
RUNTIME_GRAPH_CONFIG_ROOT = resolve_path("graphs/configs")
RUNTIME_GRAPH_CONFIG_PATH = RUNTIME_GRAPH_CONFIG_ROOT / f"{PRIMARY_RUNTIME_GRAPH_ID}.yaml"
RUNTIME_GRAPH_VERSION_ROOT = resolve_path("memory/graph_versions")
RUNTIME_MODULE_ROOT = resolve_path("graphs/modules")
RUNTIME_MODULE_VERSION_ROOT = resolve_path("memory/module_versions")
API_KEY_SETTINGS_PATH = resolve_path("memory/api_keys.json")
BAMBU_HTTP_EXPORT_ROOT = resolve_path("artifacts/bambu_http_exports")
_RUNTIME_GRAPH_DRY_RUN_RECORDS: dict[str, dict[str, object]] = {}
_SYSTEM_RESOURCE_CACHE: dict[str, object] = {"updated_at_monotonic": 0.0, "payload": {}, "last_good_gpu": {}}
try:
    _NVIDIA_SMI_TIMEOUT_SEC = float(os.getenv("AUTONOMOUS_NVIDIA_SMI_TIMEOUT_SEC", "5.0") or 5.0)
except ValueError:
    _NVIDIA_SMI_TIMEOUT_SEC = 5.0
_RUNTIME_MODULE_MANAGEMENT_LOADED: set[str] = set()
_LEROBOT_BRIDGE: LeRobotBridge | None = None
_LEROBOT_CONFIG_MTIME_NS: int = -1

LIVE_AGENT_DEFINITIONS: list[dict[str, str]] = [
    {"agent_id": "objective", "label": "Objective", "stage": "idle", "module_id": "objective"},
    {"agent_id": "orchestrator", "label": "Orchestrator", "stage": "orchestrator", "module_id": "orchestrator"},
    {"agent_id": "design", "label": "Design Agent", "stage": "design", "module_id": "design"},
    {"agent_id": "specimen", "label": "Specimen Agent", "stage": "specimen", "module_id": "specimen"},
    {"agent_id": "vision", "label": "Vision Agent", "stage": "vision", "module_id": "vision"},
    {"agent_id": "manipulation", "label": "Manipulation Agent", "stage": "manipulation", "module_id": "manipulation"},
    {"agent_id": "equipment", "label": "Lab Equipment Agent", "stage": "equipment", "module_id": "equipment"},
    {"agent_id": "analysis", "label": "Analysis Agent", "stage": "analysis", "module_id": "analysis"},
    {"agent_id": "knowledge", "label": "Knowledge Agent", "stage": "knowledge", "module_id": "knowledge"},
    {"agent_id": "bo", "label": "BO Agent", "stage": "bo", "module_id": "bo"},
    {"agent_id": "guardian", "label": "Guardian Agent", "stage": "guardian", "module_id": "guardian"},
]

LIVE_AGENT_REPORT_PROFILES: dict[str, dict[str, object]] = {
    "objective": {
        "title": "Objective Intake / Experiment Contract",
        "summary": "Tracks operator intent, required specimen constraints, missing values, and the trigger condition for starting the workflow.",
        "focus_rows": [
            {"label": "Intent", "value": "experiment objective, target metric, and material domain"},
            {"label": "Required inputs", "value": "specimen size, material, print mode, evaluation target, safety gates"},
            {"label": "Start gate", "value": "workflow starts only after explicit execution intent or a configured test-mode command"},
        ],
        "checklist": ["Confirm missing parameters", "Keep examples visible", "Preserve operator trigger wording"],
    },
    "orchestrator": {
        "title": "Orchestration Plan / Handoff Control",
        "summary": "Coordinates stage order, missing-input questions, handoff messages, and safe workflow continuation.",
        "focus_rows": [
            {"label": "Route", "value": "Objective -> Design -> Specimen -> Vision -> Manipulation -> Equipment -> Analysis -> Knowledge -> BO -> Guardian"},
            {"label": "Decision gate", "value": "ask for missing required values instead of fabricating live parameters"},
            {"label": "Context", "value": "session memory, selected chat target, selected trace, and active graph stage"},
        ],
        "checklist": ["Validate required inputs", "Emit system handoff messages", "Stop on unresolved approval"],
    },
    "design": {
        "title": "Design Geometry / Manufacturability",
        "summary": "Converts approved requirements into printable TPMS/FDM specimen geometry with traceable parameters.",
        "focus_rows": [
            {"label": "Geometry", "value": "gyroid TPMS with cell size, unit-cell count, shell thickness, and cap settings"},
            {"label": "Manufacturability", "value": "single connected body, FDM constraints, slicer-safe dimensions"},
            {"label": "Artifacts", "value": "STL preview, parameter JSON, and design candidate metadata"},
        ],
        "checklist": ["Check connected components", "Record final parameters", "Expose STL artifact"],
    },
    "specimen": {
        "title": "Manufacturing Digital Thread / Printer Runtime",
        "summary": "Transforms the selected STL into a fabrication digital thread with slicer settings, quality gates, printer runtime evidence, monitoring handoff, and feedback to the next loop.",
        "focus_rows": [
            {"label": "Digital thread", "value": "design candidate -> STL -> G-code -> printer job -> Vision/Manipulation handoff"},
            {"label": "Process plan", "value": "material, profile, layer/nozzle/temp, adhesion, cap skin, and ejection policy"},
            {"label": "Quality gates", "value": "required fields, mesh, manufacturability, slicer, G-code, storage, live execution, and ejection"},
            {"label": "Runtime evidence", "value": "PrusaLink upload/start/transfer trace, operator messages, outcome, and feedback to Design/Knowledge/BO"},
        ],
        "checklist": ["Confirm fabrication intent", "Inspect digital thread", "Review quality gates", "Log printer runtime", "Prepare Vision handoff"],
    },
    "vision": {
        "title": "Lab Perception Signal Bus / Visual Evidence",
        "summary": "Converts camera or screenshot evidence into zone states, freshness-bounded agent signals, visual evidence, and downstream handoff gates.",
        "focus_rows": [
            {"label": "Scene task", "value": "post-ejection, pickup, UTM fixture, or reset observation task with current specimen context"},
            {"label": "Signal board", "value": "pickup_ready, visual_evidence_ready, anomaly_detected, and future equipment cross-check signals with confidence/freshness"},
            {"label": "Evidence", "value": "frame/annotated scene, detection JSON, zone states, and Knowledge memory payload"},
            {"label": "Safety", "value": "Vision observes only; robot/printer/equipment actions remain gated by downstream agents and Guardian"},
        ],
        "checklist": ["Check camera heartbeat", "Review zone state", "Verify signal freshness", "Inspect visual evidence", "Gate manipulation handoff"],
    },
    "manipulation": {
        "title": "Manipulation Agent / Pi0.5 Skill Supervision",
        "summary": "Supervises bounded LeRobot/Pi0.5 skills, preflight readiness, SARM-lite progress/risk, Vision verification dependency, and robot_task_result handoff.",
        "focus_rows": [
            {"label": "Task", "value": "transfer_to_utm or clear_utm_to_disposal with source/target/terminal pose"},
            {"label": "Policy boundary", "value": "LeRobot bridge executes; Manipulation Agent supervises stage, safety, and handoff"},
            {"label": "SARM/Vision gate", "value": "stage progress, failure precursor, recovery hint, and post-place verification"},
        ],
        "checklist": ["Confirm Vision freshness", "Validate robot/profile/policy preflight", "Run bounded rollout", "Check SARM risk", "Require post-place Vision verification"],
    },
    "equipment": {
        "title": "Lab Equipment / UTM Visual Control",
        "summary": "Shows Windows/UTM control trace, screen-state assertions, Vision physical cross-checks, data artifact ledger, and Analysis handoff gate evidence.",
        "focus_rows": [
            {"label": "Control trace", "value": "registered UTM program, macro version, locator backend, bridge provider, and tool result sequence"},
            {"label": "Visual assertion", "value": "before/running/complete screen checks and state-transition evidence"},
            {"label": "Physical check", "value": "Vision-backed fixture, crosshead motion, alignment, and safe-access confirmation"},
            {"label": "Data ledger", "value": "Windows export path, Linux pulled CSV path, checksum, row count, columns, and parse probe"},
            {"label": "Handoff gate", "value": "ready_for_analysis only when screen, physical, save, file, and parse gates all pass"},
        ],
        "checklist": ["Confirm bridge/profile readiness", "Verify screen assertions", "Verify Vision physical checks", "Confirm CSV artifact pull", "Gate Analysis handoff"],
    },
    "analysis": {
        "title": "UTM / FEM / Objective Evaluation",
        "summary": "Processes measurement or simulation output into force/displacement features and objective scores.",
        "focus_rows": [
            {"label": "Data", "value": "UTM curve, CAE contour, boundary conditions, and specimen metadata"},
            {"label": "Metrics", "value": "stiffness, energy absorption, peak force, mass-normalized score"},
            {"label": "Evidence", "value": "plots, contour SVG, tabular summary, and objective JSON"},
        ],
        "checklist": ["Validate boundary conditions", "Attach quantitative metrics", "Prepare BO observation"],
    },
    "knowledge": {
        "title": "Knowledge Memory / Evidence Update",
        "summary": "Writes validated outcomes into session/project knowledge so BO and later reports use observed evidence.",
        "focus_rows": [
            {"label": "Memory", "value": "experiment id, specimen id, final parameters, metrics, and artifacts"},
            {"label": "Quality", "value": "provenance, duplicate detection, uncertainty, and failed-run notes"},
            {"label": "Consumers", "value": "BO candidate selection and final report generation"},
        ],
        "checklist": ["Store observed data", "Link artifacts", "Expose BO-ready row"],
    },
    "bo": {
        "title": "Bayesian Optimization / Candidate Selection",
        "summary": "Updates surrogate/acquisition state from knowledge observations and proposes the next candidate.",
        "focus_rows": [
            {"label": "Observation", "value": "latest design parameters and objective value from Knowledge Agent"},
            {"label": "Acquisition", "value": "EI/UCB/PI or benchmark mode, plotted sampled points, next candidate"},
            {"label": "Loop", "value": "candidate handoff to Design Agent with graph/event evidence"},
        ],
        "checklist": ["Plot surrogate/acquisition", "Log selected candidate", "Preserve parameter bounds"],
    },
    "guardian": {
        "title": "Safety Gate / Continue-Stop Decision",
        "summary": "Checks live/test gate results, hardware risk, and operator approvals before continuation.",
        "focus_rows": [
            {"label": "Gate", "value": "safe/hold/retry/replan/stop decision with reason"},
            {"label": "Risk", "value": "device errors, missing approvals, unsafe bridge state, failed validation"},
            {"label": "Action", "value": "continue workflow, request operator input, or trigger safe stop"},
        ],
        "checklist": ["Require approval when needed", "Surface blocking errors", "Record final decision"],
    },
}


def _read_workspace_settings(path: Path) -> dict[str, Any]:
    """Read a workspace settings JSON file, returning an empty dict on first use/corruption."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_workspace_settings(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist workspace settings under memory/ using an atomic-ish replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return payload


def _mask_api_key(value: str) -> str:
    """Return a display-safe API key hint without exposing the secret."""
    clean = str(value or "").strip()
    if not clean:
        return ""
    if len(clean) <= 8:
        return "*" * len(clean)
    return f"{clean[:4]}••••{clean[-4:]}"


def _read_openai_api_key_from_local_env() -> tuple[str, str]:
    """Read only OPENAI_API_KEY from supported local env sources."""
    env_key = str(os.getenv("OPENAI_API_KEY", "")).strip()
    if env_key:
        return env_key, "env"
    for env_path in (resolve_path(".env"), resolve_path("env")):
        if not env_path.exists() or not env_path.is_file():
            continue
        try:
            file_key = str(dotenv_values(env_path).get("OPENAI_API_KEY") or "").strip()
        except Exception:
            file_key = ""
        if file_key:
            return file_key, env_path.name
    return "", "none"


def _read_api_key_settings(*, import_env: bool = True) -> dict[str, Any]:
    """Read the gitignored API key settings file, initializing from .env on first use."""
    path = API_KEY_SETTINGS_PATH
    existed = path.exists()
    settings = _read_workspace_settings(path) if existed else {}
    env_key, env_source = _read_openai_api_key_from_local_env()
    api_key = str(settings.get("api_key") or "").strip()
    source = str(settings.get("source") or "").strip()
    if import_env and not existed and env_key:
        settings = {
            "schema": "api_key.v1",
            "provider": "openai",
            "api_key": env_key,
            "enabled": True,
            "source": env_source,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_workspace_settings(path, settings)
        return settings
    enabled = bool(settings.get("enabled", False)) and bool(api_key)
    return {
        "schema": "api_key.v1",
        "provider": "openai",
        "api_key": api_key,
        "enabled": enabled,
        "source": source or ("memory" if api_key else "none"),
        "updated_at": str(settings.get("updated_at") or ""),
    }


def _write_api_key_settings(api_key: str, *, enabled: bool, source: str = "user") -> dict[str, Any]:
    """Persist OpenAI API key settings to the local gitignored single-file store."""
    clean_key = str(api_key or "").strip()
    payload = {
        "schema": "api_key.v1",
        "provider": "openai",
        "api_key": clean_key,
        "enabled": bool(enabled and clean_key),
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return _write_workspace_settings(API_KEY_SETTINGS_PATH, payload)


def _public_api_key_settings(settings: dict[str, Any]) -> dict[str, object]:
    """Return API key status without the secret value."""
    api_key = str(settings.get("api_key") or "").strip()
    enabled = bool(settings.get("enabled") and api_key)
    return {
        "ok": True,
        "provider": "openai",
        "enabled": enabled,
        "has_key": bool(api_key),
        "key_status": "registered" if api_key else "not_registered",
        "source": str(settings.get("source") or ("memory" if api_key else "none")),
        "settings_path": str(API_KEY_SETTINGS_PATH),
        "updated_at": str(settings.get("updated_at") or ""),
    }


async def _apply_runtime_api_key_settings(settings: dict[str, Any], *, emit_event: bool = True) -> dict[str, object]:
    apply_result = await controller.apply_openai_api_key(
        str(settings.get("api_key") or ""),
        enabled=bool(settings.get("enabled")),
        emit_event=emit_event,
    )
    public = _public_api_key_settings(settings)
    public["apply_result"] = apply_result
    public["primary_backend"] = str(apply_result.get("primary_backend") or "")
    public["fallback_backend"] = str(apply_result.get("fallback_backend") or "")
    return public


@app.on_event("startup")
async def keep_startup_side_effect_free() -> None:
    """Keep GUI startup free of model prewarming while applying saved secrets."""
    settings = _read_api_key_settings(import_env=True)
    await _apply_runtime_api_key_settings(settings, emit_event=False)


@app.on_event("shutdown")
async def shutdown_lerobot_subprocesses() -> None:
    """Release LeRobot live subprocesses so cameras/serial ports are not left busy."""
    _lerobot_bridge().shutdown()


class StartRunRequest(BaseModel):
    """Request body for run start endpoint."""

    mode: Literal["live", "test", "replay", "fault-injection"] = "test"
    goal: str | None = None
    backend: Literal["openai", "nemoclaw", "ollama", "vllm"] | None = None
    fault: str = Field(default="none", description="Fault name for fault-injection mode")
    fault_stage: str = Field(default="", description="Stage where fault is injected")


class PlanningMessageRequest(BaseModel):
    """Request body for planning-workspace orchestrator messages."""

    message: str = Field(..., min_length=1)
    goal: str | None = None
    backend: Literal["openai", "nemoclaw", "ollama", "vllm"] | None = None
    constraints: dict[str, object] = Field(default_factory=dict)
    session_id: str | None = None


class PlanningBootstrapRequest(BaseModel):
    """Request body for starting the Live GUI orchestrator before user input."""

    goal: str | None = None
    backend: Literal["openai", "nemoclaw", "ollama", "vllm"] | None = None
    constraints: dict[str, object] = Field(default_factory=dict)
    session_id: str | None = None


class BackendSwitchRequest(BaseModel):
    """Request body for one-click inference backend switching."""

    backend: Literal["openai", "nemoclaw", "ollama", "vllm"]


class RuntimeGraphSaveRequest(BaseModel):
    """Request body for saving a validated Runtime IDE graph config."""

    graph: dict[str, object] = Field(default_factory=dict)
    reason: str = "runtime_ide_save"
    author: str = "operator"
    activate: bool = True


class RuntimeGraphSaveVersionRequest(BaseModel):
    """Compatibility request body for package graph save-version calls."""

    graph: dict[str, object] = Field(default_factory=dict)
    reason: str = "package_save_version"
    author: str = "operator"
    activate: bool = False


class RuntimeGraphYamlImportRequest(BaseModel):
    """Request body for importing a graph YAML draft into the Runtime IDE."""

    yaml_text: str = Field(..., min_length=1)


class RuntimeModuleSaveRequest(BaseModel):
    """Request body for saving Runtime IDE module config."""

    module: dict[str, object] = Field(default_factory=dict)
    reason: str = "runtime_module_save"
    author: str = "operator"
    activate: bool = True


class RuntimeModuleCreateRequest(BaseModel):
    """Request body for creating a cataloged Runtime IDE module."""

    module_id: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    category: str = ""
    handler: str = "runtime.step_complete"
    llm_role: str = ""
    tools: list[str] = Field(default_factory=list)
    source_filename: str = ""
    source_text: str = ""
    notes: str = ""
    transform_with_llm: bool = True
    transform_model: str = ""


class RuntimeGraphDryRunRequest(BaseModel):
    """Request body for graph dry-run simulation options."""

    start_stage: str = "idle"
    max_steps: int = 24
    graph: dict[str, object] = Field(default_factory=dict)


class RuntimeModelRequest(BaseModel):
    """Request body for managed vLLM model load/unload controls."""

    model: str = Field(..., min_length=1)


class RuntimeApiKeyRequest(BaseModel):
    """Request body for local API key storage controls."""

    api_key: str = Field(..., min_length=1)
    enabled: bool = True


class BOAgentRequest(BaseModel):
    """Request body for BO Workspace benchmark and agent execution."""

    strategy: str = "bo"
    acquisition: str = "expected_improvement"
    budget: int = 8
    random_seed: int = 7
    kappa: float = 2.0
    xi: float = 0.01
    exploration_weight: float = 0.35
    exploitation_weight: float = 0.65
    llm_preference_enabled: bool = True
    llm_candidate_weight: float | str = "auto"
    top_k: int = 5
    bo_backend: str = "lightweight_pool"
    parameter_space: dict[str, object] = Field(default_factory=dict)
    objective: dict[str, object] = Field(default_factory=dict)
    mode: Literal["test", "live", "virtual", "replay"] = "test"


class CAEAnalysisRequest(BaseModel):
    """Request body for CAE Workspace analysis execution."""

    mode: Literal["test", "live", "virtual", "replay"] = "test"
    solver: str = "calculix"
    mesher: str = "gmsh"
    stl_path: str = ""
    specimen_id: str = "manual-specimen"
    specimen_size_mm: list[float] = Field(default_factory=lambda: [20.0, 20.0, 20.0])
    mesh_size_mm: float = 2.0
    elastic_modulus_mpa: float = 1800.0
    poisson_ratio: float = 0.35
    yield_strength_mpa: float = 35.0
    load_max_n: float = 500.0
    load_min_ratio: float = 0.1
    cycles: int = 10
    frequency_hz: float = 1.0
    require_solver: bool = False


class PrinterProfileRequest(BaseModel):
    """Request body for operator-controlled Prusa MK4S print defaults."""

    material: str = "PLA"
    printer_model: str = "Prusa MK4S"
    printer_profile: str = "prusa_mk4s_pla_0p4_nozzle"
    slicer_profile_hint: str = "0.2mm_quality"
    nozzle_diameter_mm: float = 0.4
    layer_height_mm: float = 0.2
    first_layer_height_mm: float = 0.2
    slow_first_layer_enabled: bool = True
    first_layer_speed_mm_s: float = 10.0
    bed_temperature_c: float = 60.0
    first_layer_bed_temperature_c: float = 60.0
    storage: str = "usb"
    max_print_time_min: float = 120.0
    overwrite: bool = True
    start_immediately_live: bool = True
    allow_ejection: bool = False
    skirt_enabled: bool = False
    top_cap_enabled: bool = False
    bottom_cap_enabled: bool = True
    top_bottom_cap: bool = True
    skin_thickness_mm: float = 0.8
    require_flat_compression_faces: bool = False
    test_specimen_size_mm: list[float] = Field(default_factory=lambda: [30.0, 30.0, 30.0])
    test_unit_cell_size_mm: float = 10.0
    notes: str = ""


class PrinterConnectionRequest(BaseModel):
    """Request body for editable printer bridge connection memory."""

    host: str = Field(default="", min_length=0)
    scheme: Literal["http", "https"] = "http"
    port: int = Field(default=80, ge=1, le=65535)
    storage: str = "usb"
    auth_mode: Literal["digest", "basic", "api_key", "none", "lan_access_code"] = "lan_access_code"
    username: str = ""
    password: str = ""
    api_key: str = ""
    api_key_header: str = "X-Api-Key"
    serial: str = ""
    printer_name: str = ""
    model: str = "Bambu Lab X2D"
    access_code: str = ""
    lan_mode_confirmed: bool = False
    developer_mode_confirmed: bool = False


class PrinterFleetSelectionRequest(BaseModel):
    """Request body for explicit selected-printer profile changes."""

    profile_id: str = Field(..., min_length=1)


class PrinterAutoejectionTestRequest(BaseModel):
    """Request body for standalone 3DP autoejection test programs."""

    position: Literal["left", "center", "right"] = "center"
    mode: Literal["live", "test"] = "live"
    object_size_mm: list[float] = Field(default_factory=lambda: [30.0, 30.0, 20.0])
    start_immediately: bool = True


class PrinterAutoejectionConfigRequest(BaseModel):
    """Request body for operator-verified Bambu autoejection gate settings."""

    enabled: bool = False
    provider: str = "none"
    verified_routine_id: str = ""
    pre_eject_vision_profile: str = ""
    post_eject_vision_profile: str = ""
    require_verified_routine: bool = True
    require_pre_eject_vision: bool = True
    require_post_eject_vision: bool = True
    fallback_to_robot_pickoff: bool = True


class PrinterUploadPathProbeRequest(BaseModel):
    """Request body for safe Bambu FTPS marker write/delete path probing."""

    candidate_dirs: list[str] = Field(default_factory=lambda: ["", "cache", "sdcard", "Metadata", "data/Metadata"])
    timeout_sec: float = Field(default=8.0, ge=1.0, le=60.0)


class PrinterStartCommandDraftRequest(BaseModel):
    """Request body for draft-only Bambu project_file command inspection."""

    remote_path: str = ""
    subtask_name: str = ""
    plate_id: int = Field(default=1, ge=1, le=32)
    use_ams: bool = False
    ams_mapping: list[int] | None = None
    timelapse: bool = False
    bed_leveling: bool = False
    flow_cali: bool = False
    vibration_cali: bool = False
    layer_inspect: bool = False


class PrinterStartGateRequest(PrinterStartCommandDraftRequest):
    """Request body for guarded Bambu project_file start preflight."""

    operator_confirmed: bool = False
    guardian_approved: bool = False
    dry_run: bool = True


class PrinterSpcReadinessRequest(PrinterStartGateRequest):
    """Request body for Specimen Making Agent printer-readiness aggregation."""

    mode: Literal["live", "test"] = "live"


class PrinterBambuSliceArtifactRequest(BaseModel):
    """Request body for creating a real Bambu sliced artifact from an STL/3MF source."""

    source_path: str = ""
    specimen_id: str = ""
    load_settings: str = ""
    load_filaments: str = ""
    extra_args: list[str] = Field(default_factory=list)
    timeout_sec: float | None = Field(default=None, ge=1.0, le=3600.0)


class PrinterHttpArtifactRouteRequest(BaseModel):
    """Request body for exposing a sliced Bambu artifact over a printer-reachable HTTP route."""

    artifact_path: str = ""
    public_base_url: str = ""
    subtask_name: str = ""
    plate_id: int = Field(default=1, ge=1, le=32)
    use_ams: bool = False
    ams_mapping: list[int] | None = None
    timelapse: bool = False
    bed_leveling: bool = False
    flow_cali: bool = False
    vibration_cali: bool = False
    layer_inspect: bool = False
    verify_fetch: bool = True
    fetch_timeout_sec: float = Field(default=3.0, ge=0.5, le=15.0)


class PrinterBambuPrestartCheckRequest(BaseModel):
    """Request body for the user-facing Bambu pre-start checklist."""

    source_path: str = ""
    artifact_path: str = ""
    specimen_id: str = ""
    load_settings: str = ""
    load_filaments: str = ""
    extra_args: list[str] = Field(default_factory=list)
    timeout_sec: float | None = Field(default=None, ge=1.0, le=3600.0)
    public_base_url: str = ""
    subtask_name: str = ""
    plate_id: int = Field(default=1, ge=1, le=32)
    use_ams: bool = False
    ams_mapping: list[int] | None = None
    timelapse: bool = False
    bed_leveling: bool = False
    flow_cali: bool = False
    vibration_cali: bool = False
    layer_inspect: bool = False
    verify_fetch: bool = True
    fetch_timeout_sec: float = Field(default=3.0, ge=0.5, le=15.0)
    operator_confirmed: bool = False
    guardian_approved: bool = False
    dry_run: bool = True
    mode: Literal["live", "test"] = "live"


class WindowsBridgeDiscoverRequest(BaseModel):
    """Request body for discovering Windows PyAutoGUI bridge hosts."""

    subnet: str = ""
    port: int = 8765
    token: str = ""
    timeout_sec: float | None = None
    max_hosts: int = 256


class WindowsBridgeConnectRequest(BaseModel):
    """Request body for saving a selected Windows PyAutoGUI bridge candidate."""

    candidate_alias: str = ""
    name: str = Field(default="", min_length=0)
    host: str = ""
    bridge_url: str = ""
    port: int = 8765
    token: str = ""
    token_header: str = "X-Bridge-Token"


class WindowsBridgeCandidateRequest(BaseModel):
    """Request body for selecting/deleting a saved Windows PyAutoGUI candidate."""

    candidate_alias: str = Field(..., min_length=1)


class WindowsBridgeRunProgramRequest(BaseModel):
    """Request body for setup-GUI macro execution tests."""

    program_id: str = Field(default="program1", min_length=1)
    command: str = ""
    confirm_execute: bool = False
    require_screen_assertions: bool = False
    simulate_utm_protocol: bool = False
    export_glob: str = ""
    artifact_timeout_s: float | None = None
    stable_for_sec: float | None = None
    expected_export_path: str = ""
    require_window_focus: bool = False
    manual_save_required_if_no_artifact: bool = True
    target_window: str = ""
    target_window_regex: str = ""
    locators: dict[str, object] = Field(default_factory=dict)
    sequence: list[dict[str, object]] = Field(default_factory=list)


class WindowsBridgeScreenshotRequest(BaseModel):
    """Request body for manual Windows bridge screenshot capture."""

    checkpoint: str = "manual"
    run_id: str = "locator-calibration"
    confirm_capture: bool = False


class WindowsBridgeUtmProfileRequest(BaseModel):
    """Request body for persisting UTM protocol GUI calibration into autonomous runs."""

    program_id: str = Field(default="utm_compression_start_v1", min_length=1)
    export_glob: str = "*.csv"
    artifact_timeout_s: float | None = None
    stable_for_sec: float | None = None
    expected_export_path: str = ""
    require_window_focus: bool = False
    manual_save_required_if_no_artifact: bool = True
    target_window: str = ""
    target_window_regex: str = ""
    require_screen_assertions: bool = False
    simulate_utm_protocol: bool = False
    locators: dict[str, object] = Field(default_factory=dict)
    sequence: list[dict[str, object]] = Field(default_factory=list)


class WindowsBridgeLocatorCaptureRequest(BaseModel):
    """Request body for Windows bridge image-locator calibration."""

    program_id: str = Field(default="utm_compression_start_v1", min_length=1)
    name: str = Field(default="ready_state", min_length=1)
    region: list[float] = Field(default_factory=list)
    confidence: float = 0.8
    confirm_capture: bool = False


class WindowsBridgeLivePreflightRequest(BaseModel):
    """Request body for non-actuating live UTM bridge preflight."""

    confirm_preflight: bool = False
    include_locators: bool = True
    include_screenshot: bool = False
    include_request_log: bool = True


class WindowsBridgeLiveValidationRequest(BaseModel):
    """Request body for live UTM validation report generation."""

    confirm_non_actuating: bool = False
    confirm_live_execute: bool = False
    confirm_physical_setup_safe: bool = False
    run_id: str = ""
    sequence_id: str = ""
    specimen_id: str = "specimen-live-validation"
    program_id: str = "utm_compression_start_v1"
    command: str = "Run UTM compression protocol and export CSV"
    include_screenshot: bool = False
    require_screen_assertions: bool = False
    require_window_focus: bool = False
    manual_save_required_if_no_artifact: bool = True
    export_glob: str = ""
    artifact_timeout_s: float | None = None
    stable_for_sec: float | None = None
    expected_export_path: str = ""
    target_window: str = ""
    target_window_regex: str = ""
    locators: dict[str, object] = Field(default_factory=dict)
    sequence: list[dict[str, object]] = Field(default_factory=list)
    vision_proof: dict[str, object] = Field(default_factory=dict)


class WindowsBridgeRequestLogRequest(BaseModel):
    """Request body for retrieving Windows bridge request-audit events."""

    runtime_mode: Literal["test", "live"] = "live"
    confirm_live: bool = False


class WindowsBridgeProofPackageVerifyRequest(BaseModel):
    """Request body for verifying a persisted Windows UTM proof package."""

    path: str = ""
    use_current: bool = True


class WindowsBridgeCompletionAuditRequest(BaseModel):
    """Request body for strict Improvement 05 completion audit."""

    path: str = ""
    use_current: bool = True
    latest: bool = False


class WindowsBridgeVisionProofDraftRequest(BaseModel):
    """Request body for building a non-actuating Vision proof draft."""

    run_id: str = ""
    specimen_id: str = ""


class LeRobotConfigRequest(BaseModel):
    """Request body for selecting a LeRobot robot profile."""

    profile_id: str = ""
    mode: Literal["live", "test", "replay", "fault-injection"] = "test"


class LeRobotAPIRequest(BaseModel):
    """Request body shared by LeRobot GUI action endpoints."""

    mode: Literal["live", "test", "replay", "fault-injection"] = "test"
    runtime_mode: Literal["live", "test", "replay", "fault-injection"] | None = None
    profile_id: str = ""
    session_id: str = ""
    task_instruction: str = "pick and place specimen"
    dataset_path: str = ""
    dataset_root: str = ""
    dataset_repo_id: str = ""
    policy_path: str = ""
    policy_repo_id: str = ""
    policy_checkpoint_path: str = ""
    policy_pretrained_path: str = ""
    policy_type: str = "act"
    output_dir: str = ""
    job_name: str = ""
    device: str = "cuda"
    seed: int | None = None
    batch_size: int = 8
    steps: int = 100000
    num_workers: int = 4
    eval_freq: int = 20000
    log_freq: int = 200
    save_freq: int = 20000
    save_checkpoint: bool = True
    eval_batch_size: int | None = None
    optimizer_type: str = ""
    optimizer_lr: float | None = None
    optimizer_weight_decay: float | None = None
    optimizer_grad_clip_norm: float | None = None
    scheduler_type: str = ""
    scheduler_warmup_steps: int | None = None
    scheduler_decay_steps: int | None = None
    scheduler_peak_lr: float | None = None
    scheduler_decay_lr: float | None = None
    policy_n_obs_steps: int | None = None
    policy_chunk_size: int | None = None
    policy_n_action_steps: int | None = None
    policy_use_amp: bool = False
    wandb_enable: bool = False
    wandb_project: str = ""
    wandb_mode: str = "disabled"
    train_extra_args: list[str] = Field(default_factory=list)
    fps: int | None = None
    camera_fps: int | None = None
    teleop_time_s: float | None = None
    warmup_s: float = 2.0
    episode_s: float = 5.0
    reset_s: float = 2.0
    num_episodes: int = 1
    continuous_rollout: bool = False
    rollout_action_clamp: bool = True
    rollout_max_relative_target: int = 5
    rollout_temporal_ensemble: bool = True
    rollout_temporal_ensemble_coeff: float = 0.01
    rollout_inference_type: str = ""
    rollout_rtc_execution_horizon: int | None = None
    rollout_rtc_max_guidance_weight: float | None = None
    rollout_action_queue_size_to_get_new_actions: int | None = None
    max_duration_s: float | None = None
    policy_backend: str = "lerobot_cli"
    camera_enabled: bool = False
    display_data: bool = False
    resume: bool = False
    push_to_hub: bool = False
    tts_engine: str = ""
    tts_rate: int | None = None
    tts_voice: str = ""
    confirm_live_execute: bool = False
    episode_index: int = 0
    visualization_tool: Literal["html", "rerun"] = "html"
    visualization_mode: Literal["local", "distant"] = "local"
    visualization_batch_size: int = 32
    visualization_num_workers: int = 4
    visualization_save: bool = False
    visualization_output_dir: str = ""
    visualization_web_port: int = 9090
    visualization_ws_port: int = 9087
    visualization_tolerance_s: float = 1e-4
    observation: dict[str, object] = Field(default_factory=dict)
    fault: str = ""
    dry_run: bool = True


class ManipulationAgentBridgeRequest(LeRobotAPIRequest):
    """Request body for running the actual Manipulation Agent from the LeRobot GUI."""

    manipulation_strategy: str = "pi05_lerobot_policy"
    task_id: str = "transfer_to_utm"
    skill_id: str = ""
    source_location: str = "3dp_output_area"
    target_location: str = "utm_fixture"
    specimen_result: dict[str, object] = Field(default_factory=dict)


class LeRobotRecordControlAPIRequest(BaseModel):
    """Request body for LeRobot recording controls."""

    action: Literal["stop", "retry", "next", "finish"] = "stop"
    mode: Literal["live", "test", "replay", "fault-injection"] = "test"
    runtime_mode: Literal["live", "test", "replay", "fault-injection"] | None = None
    profile_id: str = ""
    session_id: str = ""
    dry_run: bool = True


class LeRobotBrowseRequest(BaseModel):
    """Request body for local LeRobot path browsing."""

    kind: Literal["dataset", "policy", "output", "any"] = "any"
    path: str = ""
    include_files: bool = True
    select: Literal["directory", "file"] = "directory"


class LeRobotDevicePortAPIRequest(BaseModel):
    """Request body for LeRobot follower/leader/camera port setup."""

    mode: Literal["live", "test", "replay", "fault-injection"] = "test"
    runtime_mode: Literal["live", "test", "replay", "fault-injection"] | None = None
    profile_id: str = ""
    device_role: Literal["follower", "leader", "camera"] = "follower"
    port: str = ""
    camera_key: str = "top"
    camera_index: int | None = None
    confirm_live_execute: bool = False
    dry_run: bool = True


class LeRobotVisualizationFileRequest(BaseModel):
    """Request body for safe local dataset visualization file serving."""

    path: str = Field(..., min_length=1)


class RuntimeApprovalCreateRequest(BaseModel):
    """Request body for creating a runtime human-approval request event."""

    title: str = Field(default="Human approval required", min_length=1)
    reason: str = ""
    stage: str = ""
    safety_class: str = "operator_review"
    requester: str = "runtime_ide"
    payload: dict[str, object] = Field(default_factory=dict)


class RuntimeApprovalResolveRequest(BaseModel):
    """Request body for resolving a runtime human-approval request."""

    decision: Literal["approved", "rejected", "cancelled"] = "approved"
    note: str = ""
    operator: str = "operator"


class RuntimeAgentMessageRequest(BaseModel):
    """Compatibility request body for context-aware agent messages."""

    message: str = Field(..., min_length=1)
    goal: str | None = None
    backend: Literal["openai", "nemoclaw", "ollama", "vllm"] | None = None
    mode: Literal["ask", "command", "approval", "edit_report"] = "ask"
    constraints: dict[str, object] = Field(default_factory=dict)
    session_id: str | None = None


class RuntimeOperatorEventRequest(BaseModel):
    """Request body for recording an operator UI action into the runtime event stream."""

    event_type: str = Field(default="operator.event", min_length=1, max_length=160)
    message: str = ""
    action: str = ""
    agent_id: str = ""
    node_id: str = ""
    trace_id: str = ""
    event_key: str = ""
    level: Literal["INFO", "WARNING", "ERROR"] = "INFO"
    payload: dict[str, object] = Field(default_factory=dict)


class GuardianIncidentNoteRequest(BaseModel):
    """Request body for attaching an operator note to a Guardian incident."""

    note: str = Field(..., min_length=1, max_length=4000)
    operator: str = "operator"
    source: str = "live_gui"


def _load_agent_baseline_markdown() -> str:
    """Read baseline markdown for agent program integration."""
    if not AGENT_BASELINE_DOC_PATH.exists():
        raise HTTPException(status_code=404, detail=f"Baseline doc not found: {AGENT_BASELINE_DOC_PATH}")
    return AGENT_BASELINE_DOC_PATH.read_text(encoding="utf-8")


def _equipment_bridge() -> WindowsPyAutoGUIBridge:
    cfg = load_all_configs(resolve_path("configs"))
    config = WindowsPyAutoGUIBridgeConfig.from_devices_config(cfg.get("devices", {}), repo_root=resolve_path("."))
    return WindowsPyAutoGUIBridge(config)


def _printer_workflow() -> PrinterAgenticWorkflow:
    cfg = load_all_configs(resolve_path("configs"))
    config = PrusaBridgeConfig.from_devices_config(cfg.get("devices", {}), repo_root=resolve_path("."))
    return PrinterAgenticWorkflow(config, repo_root=resolve_path("."))


def _printer_bridge_manager() -> PrinterDeviceBridgeManager:
    """Return the selected-printer bridge manager used by 3DP GUI and printer.prepare."""
    cfg = load_all_configs(resolve_path("configs"))
    return PrinterDeviceBridgeManager.from_devices_config(cfg.get("devices", {}), repo_root=resolve_path("."))


def _redacted_printer_connection(workflow: PrinterAgenticWorkflow) -> dict[str, object]:
    """Return PrusaLink connection memory without exposing secrets."""
    config = workflow.config
    memory = workflow.connection_memory.load()
    auth = memory.get("auth") if isinstance(memory.get("auth"), dict) else {}
    live_auth = config.live.get("auth", {}) if isinstance(config.live.get("auth"), dict) else {}
    return {
        "host": memory.get("host", ""),
        "scheme": memory.get("scheme", config.live.get("scheme", "http")),
        "port": memory.get("port", config.live.get("port", 80)),
        "storage": memory.get("storage", config.live.get("storage", "usb")),
        "auth_mode": auth.get("mode", live_auth.get("mode", "digest")),
        "username": auth.get("username", ""),
        "password_set": bool(auth.get("password")),
        "api_key_set": bool(auth.get("api_key")),
        "api_key_header": auth.get("api_key_header", live_auth.get("api_key_header", "X-Api-Key")),
        "connection_memory_path": str(workflow.connection_memory.path),
    }


def _redacted_selected_printer_connection(manager: PrinterDeviceBridgeManager) -> dict[str, object]:
    """Return selected printer connection memory without exposing Bambu/Prusa secrets."""
    profile, _reason = manager.fleet_selection()
    if profile.provider == "bambulab_x2d":
        return BambuConnectionMemory(profile.connection_memory_path).redacted()
    workflow = _printer_workflow()
    return _redacted_printer_connection(workflow)


def _host_is_loopback_or_unspecified(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if not normalized or normalized == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_unspecified)


def _detect_printer_reachable_host(printer_host: str) -> str:
    """Return the local interface IP that would route to the printer host."""
    if not printer_host:
        return ""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(1.0)
        sock.connect((printer_host, 9))
        return str(sock.getsockname()[0])
    except OSError:
        return ""
    finally:
        sock.close()


def _bambu_http_public_base_url(request: Request, *, printer_host: str, override: str = "") -> str:
    raw_override = str(override or "").strip().rstrip("/")
    if raw_override:
        parsed = urlparse(raw_override)
        if parsed.scheme not in {"http", "https"} or _host_is_loopback_or_unspecified(parsed.hostname or ""):
            raise HTTPException(status_code=400, detail="BAMBU_HTTP_ARTIFACT_URL_NOT_PRINTER_REACHABLE")
        return raw_override

    local_host = _detect_printer_reachable_host(printer_host)
    if not local_host:
        req_host = request.url.hostname or ""
        if _host_is_loopback_or_unspecified(req_host):
            raise HTTPException(status_code=400, detail="BAMBU_HTTP_ARTIFACT_HOST_DETECTION_FAILED")
        local_host = req_host
    port = request.url.port
    netloc = f"{local_host}:{port}" if port else local_host
    scheme = request.url.scheme if request.url.scheme in {"http", "https"} else "http"
    return f"{scheme}://{netloc}"


def _safe_bambu_http_artifact_source(path_value: str) -> Path:
    source = Path(str(path_value or "")).expanduser()
    if not source.is_absolute():
        source = resolve_path(source)
    source = source.resolve()
    if not source.exists() or not source.is_file():
        raise HTTPException(status_code=404, detail="BAMBU_HTTP_ARTIFACT_FILE_NOT_FOUND")
    name = source.name.lower()
    allowed = name.endswith((".gcode.3mf", ".3mf", ".gcode"))
    if not allowed:
        raise HTTPException(status_code=400, detail="BAMBU_HTTP_ARTIFACT_UNSUPPORTED_EXTENSION")
    return source


def _safe_bambu_http_filename(source: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", source.name).strip("._")
    return name or "bambu_artifact.gcode.3mf"


def _safe_bambu_http_export_path(token: str, filename: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", str(token or "")):
        raise HTTPException(status_code=404, detail="Bambu HTTP artifact not found")
    safe_name = _safe_bambu_http_filename(Path(filename))
    root = BAMBU_HTTP_EXPORT_ROOT.resolve()
    path = (root / token / safe_name).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bambu HTTP artifact path escapes export root") from exc
    return path


async def _probe_bambu_http_artifact_fetch(
    artifact_url: str,
    *,
    expected_sha256: str,
    timeout_sec: float = 3.0,
) -> dict[str, object]:
    """Fetch the prepared artifact URL and compare bytes before treating it as a transfer route."""
    parsed = urlparse(str(artifact_url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "ok": False,
            "failure_code": "BAMBU_HTTP_ARTIFACT_PROBE_URL_INVALID",
            "message": "Artifact URL is not an HTTP(S) URL.",
        }
    try:
        async with httpx.AsyncClient(timeout=float(timeout_sec), follow_redirects=True) as client:
            response = await client.get(artifact_url)
    except Exception as exc:  # noqa: BLE001 - return operator-facing probe evidence.
        return {
            "ok": False,
            "failure_code": "BAMBU_HTTP_ARTIFACT_FETCH_FAILED",
            "message": f"ATR server artifact URL could not be fetched: {exc}",
        }
    content = response.content
    digest = hashlib.sha256(content).hexdigest()
    status_ok = 200 <= response.status_code < 300
    hash_ok = digest == expected_sha256
    return {
        "ok": bool(status_ok and hash_ok),
        "status_code": response.status_code,
        "size_bytes": len(content),
        "sha256": digest,
        "matches_expected_sha256": hash_ok,
        "failure_code": "" if status_ok and hash_ok else (
            "BAMBU_HTTP_ARTIFACT_HASH_MISMATCH" if status_ok else "BAMBU_HTTP_ARTIFACT_FETCH_STATUS_FAILED"
        ),
        "message": (
            "Artifact URL fetched successfully and sha256 matched."
            if status_ok and hash_ok
            else "Artifact URL fetch did not prove that the prepared file is reachable and intact."
        ),
    }


def _selected_print_profile(manager: PrinterDeviceBridgeManager) -> dict[str, object]:
    """Return print defaults adapted to the selected printer provider without mutating memory."""
    profile = load_prusa_print_profile()
    selected_profile, _reason = manager.fleet_selection()
    return adapt_print_profile_for_provider(profile, selected_profile.provider)


def _selected_printer_autoejection_payload(
    manager: PrinterDeviceBridgeManager,
    config: PrusaBridgeConfig,
    profile: dict[str, object],
) -> dict[str, object]:
    selected_profile, _reason = manager.fleet_selection()
    if selected_profile.provider == "bambulab_x2d":
        status = manager.autoejection_status()
        return {
            "enabled": bool(status.get("enabled", False)),
            "method": status.get("provider", "none"),
            "mode": status.get("status", "not_configured"),
            "requested": bool(status.get("requested", False)),
            "can_run_test": bool(status.get("can_run_test", False)),
            "blockers": status.get("blockers", []),
            "verified_routine_id": status.get("verified_routine_id", ""),
            "pre_eject_vision_profile": status.get("pre_eject_vision_profile", ""),
            "post_eject_vision_profile": status.get("post_eject_vision_profile", ""),
            "require_verified_routine": bool(status.get("require_verified_routine", True)),
            "require_pre_eject_vision": bool(status.get("require_pre_eject_vision", True)),
            "require_post_eject_vision": bool(status.get("require_post_eject_vision", True)),
        }
    return {
        "enabled": bool(profile.get("allow_ejection", False)),
        "method": config.ejection.method,
        "mode": config.ejection.mode,
    }


def _selected_printer_profile_live_gates(
    manager: PrinterDeviceBridgeManager,
    config: PrusaBridgeConfig,
) -> dict[str, object]:
    """Return non-actuating profile-page gate defaults for the active printer."""
    selected_profile, _reason = manager.fleet_selection()
    if selected_profile.provider == "bambulab_x2d":
        autoejection = manager.autoejection_status()
        return {
            "allow_status": True,
            # Profile load must not imply Bambu upload/start readiness. The live
            # status/SPC routes attach the current MQTT/transfer/start evidence.
            "allow_upload": False,
            "allow_start_print": False,
            "allow_ejection": bool(autoejection.get("enabled", False)),
        }
    return {
        "allow_status": config.live_gate("allow_status", True),
        "allow_upload": config.live_gate("allow_upload", False),
        "allow_start_print": config.live_gate("allow_start_print", False),
        "allow_ejection": config.live_gate("allow_ejection", False),
    }


def _selected_printer_slicer_payload(
    manager: PrinterDeviceBridgeManager,
    config: PrusaBridgeConfig,
) -> dict[str, object]:
    """Return slicer config for the active printer provider."""
    selected_profile, _reason = manager.fleet_selection()
    if selected_profile.provider == "bambulab_x2d":
        return manager.config.slicer.resolved_payload(repo_root=resolve_path("."))
    return {
        "enabled": config.slicer.enabled,
        "available": bool(os.environ.get(config.slicer.executable_env) or Path(config.slicer.executable_path).exists()),
        "source": "env" if os.environ.get(config.slicer.executable_env) else "configured",
        "executable_env": config.slicer.executable_env,
        "executable_path": config.slicer.executable_path,
        "configured_executable_path": config.slicer.executable_path,
        "resolved_executable_path": os.environ.get(config.slicer.executable_env, config.slicer.executable_path),
        "output_dir": config.slicer.output_dir,
        "timeout_sec": config.slicer.timeout_sec,
    }


def _registered_lerobot_bridge() -> LeRobotBridge | None:
    """Return the LeRobot bridge owned by the backend ToolRegistry when available."""
    resource_getter = getattr(controller._deps.agent_context.tools, "resource", None)
    if callable(resource_getter):
        bridge = resource_getter("lerobot.bridge")
        if isinstance(bridge, LeRobotBridge):
            return bridge
    return None


def _lerobot_bridge() -> LeRobotBridge:
    """Return the shared LeRobot bridge used by registered backend tools."""
    global _LEROBOT_BRIDGE, _LEROBOT_CONFIG_MTIME_NS
    if _LEROBOT_BRIDGE is not None:
        return _LEROBOT_BRIDGE
    bridge = _registered_lerobot_bridge()
    if bridge is not None:
        return bridge
    config_path = resolve_path("configs/lerobot.yaml")
    try:
        config_mtime_ns = config_path.stat().st_mtime_ns
    except OSError:
        config_mtime_ns = -1
    if _LEROBOT_BRIDGE is None or config_mtime_ns != _LEROBOT_CONFIG_MTIME_NS:
        cfg = load_all_configs(resolve_path("configs"))
        config = LeRobotBridgeConfig.from_config(cfg.get("lerobot", {}), repo_root=resolve_path("."))
        _LEROBOT_BRIDGE = LeRobotBridge(config)
        _LEROBOT_CONFIG_MTIME_NS = config_mtime_ns
    return _LEROBOT_BRIDGE


async def _publish_lerobot_result(result: dict[str, object]) -> dict[str, object]:
    """Broadcast LeRobot tool results into the shared runtime event stream."""
    await controller.emit_lerobot_result(result)
    return result


async def _call_lerobot_backend_tool(tool_name: str, payload: dict[str, object], *, publish: bool = True) -> dict[str, object]:
    """Call LeRobot through the backend ToolRegistry so device queues and guards apply."""
    try:
        result = await asyncio.to_thread(controller._deps.agent_context.tools.call, tool_name, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if publish:
        return await _publish_lerobot_result(result)
    return result


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """Serve main web dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"title": "Autonomous Researcher Dashboard"},
    )


@app.get("/lerobot", response_class=HTMLResponse)
async def lerobot_gui(request: Request) -> HTMLResponse:
    """Serve LeRobot / ROBOTIS teleoperation, recording, and rollout GUI."""
    return templates.TemplateResponse(
        request=request,
        name="lerobot.html",
        context={"title": "LeRobot ROBOTIS GUI"},
    )


@app.get("/printer", response_class=HTMLResponse)
async def printer_gui(request: Request) -> HTMLResponse:
    """Serve Prusa MK4S 3DP profile and bridge control GUI."""
    return templates.TemplateResponse(
        request=request,
        name="printer.html",
        context={"title": "3DP Printer GUI"},
    )


@app.get("/bo", response_class=HTMLResponse)
async def bo_gui(request: Request) -> HTMLResponse:
    """Serve Bayesian Optimization / MBO workspace GUI."""
    return templates.TemplateResponse(
        request=request,
        name="bo.html",
        context={"title": "BO Workspace"},
    )


@app.get("/cae", response_class=HTMLResponse)
async def cae_gui(request: Request) -> HTMLResponse:
    """Serve CAE analysis workspace GUI."""
    return templates.TemplateResponse(
        request=request,
        name="cae.html",
        context={"title": "CAE Analysis Workspace"},
    )


@app.get("/ide", response_class=HTMLResponse)
async def runtime_ide(request: Request) -> HTMLResponse:
    """Serve config-driven LangGraph Runtime IDE."""
    return templates.TemplateResponse(
        request=request,
        name="runtime_ide.html",
        context={"title": "ATR Runtime IDE"},
    )


@app.get("/module-management", response_class=HTMLResponse)
async def module_management_tool(request: Request) -> HTMLResponse:
    """Serve the standalone Module Management Tool GUI."""
    return templates.TemplateResponse(
        request=request,
        name="module_management.html",
        context={"title": "Module Management Tool"},
    )


@app.get("/evolution-lab", response_class=HTMLResponse)
async def evolution_lab(request: Request) -> HTMLResponse:
    """Serve the Self-Evolution Lab GUI."""
    return templates.TemplateResponse(
        request=request,
        name="evolution_lab.html",
        context={"title": "ATR Self-Evolution Lab"},
    )


@app.get("/planning", response_class=HTMLResponse)
async def planning(request: Request) -> HTMLResponse:
    """Serve the live-mode GUI workspace (legacy planning route)."""
    return await live_gui(request)


@app.get("/live", response_class=HTMLResponse)
async def live_gui(request: Request) -> HTMLResponse:
    """Serve the live-mode GUI conversation workspace."""
    controller.prepare_live_gui(
        goal=request.query_params.get("goal"),
        backend=request.query_params.get("backend"),
        reset=request.query_params.get("fresh") == "1",
    )
    return templates.TemplateResponse(
        request=request,
        name="planning.html",
        context={"title": "Live GUI"},
    )


@app.get("/equipment/windows", response_class=HTMLResponse)
async def windows_equipment_gui(request: Request) -> HTMLResponse:
    """Serve Windows PyAutoGUI bridge discovery and setup GUI."""
    return templates.TemplateResponse(
        request=request,
        name="windows_equipment.html",
        context={"title": "Windows Equipment Bridge"},
    )


def _bytes_to_gb(value: int | float | None) -> float | None:
    """Convert bytes to GiB with stable rounding for UI display."""
    if value is None:
        return None
    return round(float(value) / (1024 ** 3), 2)


def _read_windows_ram_snapshot() -> dict[str, object]:
    """Read host RAM through the Windows API when /proc is unavailable."""
    if os.name != "nt":
        return {"status": "unknown", "message": "Windows RAM metrics unavailable on this OS"}

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError, ValueError):
        return {"status": "unknown", "message": "Windows RAM metrics unavailable"}
    if not ok:
        return {"status": "unknown", "message": "Windows RAM metrics unavailable"}

    total = int(status.ullTotalPhys)
    available = int(status.ullAvailPhys)
    if not total:
        return {"status": "unknown", "message": "RAM total unavailable"}
    used = max(total - available, 0)
    used_percent = round((used / total) * 100, 1)
    health = "error" if used_percent >= 92 else "warn" if used_percent >= 82 else "ready"
    return {
        "status": health,
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "total_gb": _bytes_to_gb(total),
        "available_gb": _bytes_to_gb(available),
        "used_gb": _bytes_to_gb(used),
        "used_percent": used_percent,
        "source": "windows_api",
    }


def _read_ram_snapshot() -> dict[str, object]:
    """Read host RAM from /proc/meminfo without adding a psutil dependency."""
    if os.name == "nt":
        return _read_windows_ram_snapshot()

    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable", "MemFree"}:
                values[key] = int(rest.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return {"status": "unknown", "message": "RAM metrics unavailable"}
    total = values.get("MemTotal")
    available = values.get("MemAvailable", values.get("MemFree", 0))
    if not total:
        return {"status": "unknown", "message": "RAM total unavailable"}
    used = max(total - available, 0)
    used_percent = round((used / total) * 100, 1)
    status = "error" if used_percent >= 92 else "warn" if used_percent >= 82 else "ready"
    return {
        "status": status,
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "total_gb": _bytes_to_gb(total),
        "available_gb": _bytes_to_gb(available),
        "used_gb": _bytes_to_gb(used),
        "used_percent": used_percent,
    }


def _float_or_none(value: str) -> float | None:
    """Parse nvidia-smi numeric fields while tolerating N/A tokens."""
    clean = str(value or "").strip().replace("[", "").replace("]", "")
    if not clean or clean.upper() == "N/A":
        return None
    try:
        return float(clean)
    except ValueError:
        return None


def _resolve_nvidia_smi() -> str:
    """Resolve nvidia-smi with Windows-specific executable fallbacks."""
    candidates: list[Path] = []
    for executable in ("nvidia-smi", "nvidia-smi.exe"):
        found = shutil.which(executable)
        if found:
            candidates.append(Path(found))

    if os.name == "nt":
        system_root = os.getenv("SystemRoot") or os.getenv("windir") or "C:\\Windows"
        program_files = [os.getenv("ProgramFiles"), os.getenv("ProgramW6432"), os.getenv("ProgramFiles(x86)")]
        candidates.extend(
            [
                Path(system_root) / "System32" / "nvidia-smi.exe",
                Path(system_root) / "Sysnative" / "nvidia-smi.exe",
            ]
        )
        for root in program_files:
            if root:
                candidates.append(Path(root) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe")

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            resolved = candidate
        key = str(resolved).casefold() if os.name == "nt" else str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            return str(resolved)
    return ""


def _read_nvidia_process_memory_mb(nvidia_smi: str) -> dict[str, float]:
    """Fallback GPU memory view for devices whose aggregate memory is reported as N/A."""
    try:
        result = subprocess.run([nvidia_smi], check=False, capture_output=True, text=True, timeout=_NVIDIA_SMI_TIMEOUT_SEC)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    memory_by_gpu: dict[str, float] = {}
    for line in result.stdout.splitlines():
        match = re.search(r"^\|\s*(\d+)\s+.*?\s+(\d+)MiB\s*\|$", line)
        if not match:
            continue
        gpu_index, memory_mib = match.groups()
        memory_by_gpu[gpu_index] = memory_by_gpu.get(gpu_index, 0.0) + float(memory_mib)
    return memory_by_gpu


def _read_gpu_snapshot() -> dict[str, object]:
    """Read GPU/VRAM through nvidia-smi when present; degrade safely otherwise."""
    nvidia_smi = _resolve_nvidia_smi()
    if not nvidia_smi:
        return {"status": "unavailable", "message": "nvidia-smi not found", "gpus": []}
    query = "index,name,memory.total,memory.used,utilization.gpu,temperature.gpu"
    try:
        result = subprocess.run(
            [nvidia_smi, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_NVIDIA_SMI_TIMEOUT_SEC,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fallback = _last_good_gpu_snapshot(f"nvidia-smi telemetry delayed: {exc}")
        if fallback:
            return fallback
        return {"status": "unknown", "message": f"nvidia-smi failed: {exc}", "gpus": []}
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "nvidia-smi returned non-zero").strip().splitlines()[0]
        fallback = _last_good_gpu_snapshot(f"nvidia-smi telemetry unavailable: {message}")
        if fallback:
            return fallback
        return {"status": "unknown", "message": message, "gpus": []}
    raw_rows = []
    needs_process_memory = False
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6:
            continue
        if _float_or_none(parts[3]) is None:
            needs_process_memory = True
        raw_rows.append(parts[:6])

    process_memory = _read_nvidia_process_memory_mb(nvidia_smi) if needs_process_memory else {}
    gpus: list[dict[str, object]] = []
    for index, name, mem_total, mem_used, util, temp in raw_rows:
        total_mb = _float_or_none(mem_total)
        used_mb = _float_or_none(mem_used)
        if used_mb is None:
            used_mb = process_memory.get(index)
        util_percent = _float_or_none(util)
        temp_c = _float_or_none(temp)
        used_percent = round((used_mb / total_mb) * 100, 1) if total_mb and used_mb is not None else None
        status = "error" if used_percent is not None and used_percent >= 94 else "warn" if used_percent is not None and used_percent >= 86 else "ready"
        item: dict[str, object] = {
            "index": index,
            "name": name,
            "status": status,
            "memory_total_mb": round(total_mb, 1) if total_mb is not None else None,
            "memory_used_mb": round(used_mb, 1) if used_mb is not None else None,
            "memory_total_gb": round(total_mb / 1024, 2) if total_mb is not None else None,
            "memory_used_gb": round(used_mb / 1024, 2) if used_mb is not None else None,
            "memory_used_percent": used_percent,
            "utilization_percent": util_percent,
            "temperature_c": temp_c,
            "memory_source": "query" if _float_or_none(mem_used) is not None else "process_table" if used_mb is not None else "unavailable",
        }
        gpus.append(item)
    if not gpus:
        fallback = _last_good_gpu_snapshot("nvidia-smi telemetry parse returned no rows")
        if fallback:
            return fallback
        return {"status": "unknown", "message": "No GPU rows parsed from nvidia-smi", "gpus": []}
    worst = "error" if any(gpu["status"] == "error" for gpu in gpus) else "warn" if any(gpu["status"] == "warn" for gpu in gpus) else "ready"
    total_values = [float(gpu["memory_total_mb"]) for gpu in gpus if gpu.get("memory_total_mb") is not None]
    used_values = [float(gpu["memory_used_mb"]) for gpu in gpus if gpu.get("memory_used_mb") is not None]
    total_mb = sum(total_values) if total_values else None
    used_mb = sum(used_values) if used_values else None
    util_values = [float(gpu["utilization_percent"]) for gpu in gpus if gpu.get("utilization_percent") is not None]
    aggregate: dict[str, object] = {
        "memory_total_gb": round(total_mb / 1024, 2) if total_mb is not None else None,
        "memory_used_gb": round(used_mb / 1024, 2) if used_mb is not None else None,
        "memory_used_percent": round((used_mb / total_mb) * 100, 1) if total_mb and used_mb is not None else None,
        "utilization_percent": round(sum(util_values) / len(util_values), 1) if util_values else None,
    }
    snapshot = {
        "status": worst,
        "message": f"{len(gpus)} NVIDIA GPU(s)",
        "gpus": gpus,
        "aggregate": aggregate,
    }
    _SYSTEM_RESOURCE_CACHE["last_good_gpu"] = snapshot
    return snapshot


def _last_good_gpu_snapshot(message: str) -> dict[str, object]:
    """Return the previous successful GPU telemetry snapshot with a stale marker."""
    previous = _SYSTEM_RESOURCE_CACHE.get("last_good_gpu")
    if not isinstance(previous, dict) or not previous.get("gpus"):
        return {}
    snapshot = dict(previous)
    snapshot["stale"] = True
    snapshot["message"] = f"{previous.get('message', 'GPU telemetry cached')} (cached; {message})"
    return snapshot


def _system_resource_snapshot() -> dict[str, object]:
    """Return a short-lived cached host/GPU resource snapshot for Runtime IDE panels."""
    now = time.monotonic()
    cached_at = float(_SYSTEM_RESOURCE_CACHE.get("updated_at_monotonic") or 0.0)
    if now - cached_at < 2.0 and isinstance(_SYSTEM_RESOURCE_CACHE.get("payload"), dict):
        return dict(_SYSTEM_RESOURCE_CACHE["payload"])
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "ram": _read_ram_snapshot(),
        "gpu": _read_gpu_snapshot(),
    }
    _SYSTEM_RESOURCE_CACHE["updated_at_monotonic"] = now
    _SYSTEM_RESOURCE_CACHE["payload"] = payload
    return payload


def _guardian_status_payload(run_id: str | None = None, *, snapshot: dict[str, object] | None = None) -> dict[str, object]:
    """Build a graph-wide Guardian monitor payload for Live GUI and Runtime IDE consumers."""
    snapshot = snapshot if isinstance(snapshot, dict) else controller.planning_snapshot()
    state = snapshot.get("state", {}) if isinstance(snapshot.get("state"), dict) else {}
    active_run_id = str(state.get("run_id") or _current_run_id() or "")
    requested_run_id = str(run_id or active_run_id)
    if requested_run_id and requested_run_id != active_run_id and not _safe_run_dir(requested_run_id).exists():
        raise HTTPException(status_code=404, detail=f"Unknown run_id={requested_run_id}")
    metadata = state.get("run_metadata", {}) if isinstance(state.get("run_metadata"), dict) else {}

    gates = [dict(item) for item in metadata.get("guardian_gates", []) if isinstance(item, dict)] if isinstance(metadata.get("guardian_gates"), list) else []
    incidents = [dict(item) for item in metadata.get("incident_records", []) if isinstance(item, dict)] if isinstance(metadata.get("incident_records"), list) else []
    hardware_alerts = [dict(item) for item in metadata.get("hardware_alerts", []) if isinstance(item, dict)] if isinstance(metadata.get("hardware_alerts"), list) else []
    tool_records = [dict(item) for item in metadata.get("tool_call_records", []) if isinstance(item, dict)] if isinstance(metadata.get("tool_call_records"), list) else []
    corrective_actions = [dict(item) for item in metadata.get("corrective_actions", []) if isinstance(item, dict)] if isinstance(metadata.get("corrective_actions"), list) else []
    contracts = [dict(item) for item in metadata.get("guardian_contracts", []) if isinstance(item, dict)] if isinstance(metadata.get("guardian_contracts"), list) else []
    current_spec = state.get("current_experiment_spec", {}) if isinstance(state.get("current_experiment_spec"), dict) else {}
    constraints = current_spec.get("constraints", {}) if isinstance(current_spec.get("constraints"), dict) else {}
    objective = state.get("current_experiment_objective", {}) if isinstance(state.get("current_experiment_objective"), dict) else {}

    def safe_float(value: object, default: float | None = None) -> float | None:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def first_number(*values: object, default: float | None = None) -> float | None:
        for value in values:
            resolved = safe_float(value, None)
            if resolved is not None:
                return resolved
        return default

    def first_int(*values: object, default: int = 0) -> int:
        resolved = first_number(*values, default=float(default))
        try:
            return int(resolved if resolved is not None else default)
        except (TypeError, ValueError):
            return default

    def tool_name(item: dict[str, object]) -> str:
        return str(item.get("tool") or item.get("name") or item.get("requested_tool") or "").lower()

    def count_tool_records(*needles: str) -> int:
        lowered = tuple(str(item).lower() for item in needles)
        return sum(1 for item in tool_records if any(needle in tool_name(item) for needle in lowered))

    risk_classes = ["hardware", "vision", "robot", "equipment", "data", "optimization", "self_evolution", "operator"]
    risk_map: dict[str, dict[str, object]] = {
        key: {"risk_class": key, "score": 0.0, "stage": "", "decision": "allow", "reason_code": "OK", "gate_id": ""}
        for key in risk_classes
    }
    for gate in gates:
        vector = gate.get("risk_vector") if isinstance(gate.get("risk_vector"), dict) else {}
        for key in risk_classes:
            try:
                score = float(vector.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            if score >= float(risk_map[key]["score"] or 0.0):
                risk_map[key] = {
                    "risk_class": key,
                    "score": round(score, 4),
                    "stage": str(gate.get("stage") or ""),
                    "phase": str(gate.get("phase") or ""),
                    "decision": str(gate.get("decision") or "allow"),
                    "reason_code": str(gate.get("reason_code") or "OK"),
                    "gate_id": str(gate.get("gate_id") or ""),
                }
    max_score = max((float(item.get("score", 0.0) or 0.0) for item in risk_map.values()), default=0.0)
    dominant_risks = [key for key, item in risk_map.items() if float(item.get("score", 0.0) or 0.0) >= max(0.5, max_score)] if max_score else []

    def gate_row(gate: dict[str, object]) -> dict[str, object]:
        return {
            "gate_id": gate.get("gate_id", ""),
            "stage": gate.get("stage", ""),
            "phase": gate.get("phase", ""),
            "tool": gate.get("tool", ""),
            "action": gate.get("action", ""),
            "decision": gate.get("decision", ""),
            "reason_code": gate.get("reason_code", ""),
            "risk_score": gate.get("risk_score", 0.0),
            "created_at": gate.get("created_at", ""),
        }

    gate_timeline = [gate_row(gate) for gate in gates[-80:]]
    blocked_gate_rows = [row for row in gate_timeline if str(row.get("decision") or "") in {"block", "safe_stop", "require_human_approval"}]
    blocked_tool_rows = [
        {
            "call_id": item.get("call_id", ""),
            "stage": item.get("stage", ""),
            "tool": item.get("tool", ""),
            "status": item.get("status", ""),
            "failure_code": item.get("failure_code", ""),
            "guardian_decision": item.get("guardian_decision", ""),
            "guardian_reason_code": item.get("guardian_reason_code", ""),
            "created_at": item.get("created_at", ""),
        }
        for item in tool_records[-80:]
        if str(item.get("status") or "") in {"blocked", "approval_required", "failed"}
    ]
    blocked_hardware_rows = [
        {
            "alert_id": item.get("alert_id", ""),
            "stage": item.get("stage") or item.get("workspace") or "",
            "device_class": item.get("device_class", ""),
            "component": item.get("component", ""),
            "status": item.get("status", ""),
            "failure_code": item.get("failure_code", ""),
            "severity": item.get("severity", ""),
        }
        for item in hardware_alerts[-80:]
        if bool(item.get("blocks_workflow")) or str(item.get("severity") or "") in {"blocking", "critical"}
    ]

    severity_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    for incident in incidents:
        severity = str(incident.get("severity") or "unknown")
        risk_class = str(incident.get("risk_class") or incident.get("class") or "unknown")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        class_counts[risk_class] = class_counts.get(risk_class, 0) + 1

    approvals = _approval_events_for_run(requested_run_id or active_run_id) if (requested_run_id or active_run_id) else {"approvals": [], "pending": [], "resolved": []}
    metadata_queue = [dict(item) for item in metadata.get("guardian_approval_queue", []) if isinstance(item, dict)] if isinstance(metadata.get("guardian_approval_queue"), list) else []
    pending_ids = {str(item.get("approval_id") or "") for item in approvals.get("pending", []) if isinstance(item, dict)}
    merged_pending = [dict(item) for item in approvals.get("pending", []) if isinstance(item, dict)]
    for item in metadata_queue:
        approval_id = str(item.get("approval_id") or "")
        if approval_id and approval_id not in pending_ids and str(item.get("status") or "pending") == "pending":
            merged_pending.append(item)
            pending_ids.add(approval_id)

    latest_gate = gates[-1] if gates else {}
    latest_contract = contracts[-1] if contracts else metadata.get("latest_guardian_gate", {}).get("guardian_contract", {}) if isinstance(metadata.get("latest_guardian_gate"), dict) else {}
    latest_decision = metadata.get("latest_guardian_gate_decision") if isinstance(metadata.get("latest_guardian_gate_decision"), dict) else latest_gate.get("guardian_decision", {}) if isinstance(latest_gate.get("guardian_decision"), dict) else {}
    handoff_packets = [dict(item) for item in metadata.get("handoff_packets", []) if isinstance(item, dict)] if isinstance(metadata.get("handoff_packets"), list) else []

    tool_counts: dict[str, int] = {}
    for item in tool_records:
        status = str(item.get("status") or "unknown")
        tool_counts[status] = tool_counts.get(status, 0) + 1

    budget_config = metadata.get("safety_budget") if isinstance(metadata.get("safety_budget"), dict) else {}
    if not budget_config:
        budget_config = metadata.get("risk_budget") if isinstance(metadata.get("risk_budget"), dict) else {}
    loop_count = first_int(state.get("loop_count"), default=0)
    max_loop_count = first_int(
        budget_config.get("max_loop_count"),
        budget_config.get("max_loops"),
        objective.get("max_loop_count"),
        objective.get("max_loops"),
        default=5 if str(state.get("mode") or "").lower() == "test" else 1,
    )
    expected_print_time = first_number(
        current_spec.get("expected_print_time_min"),
        current_spec.get("print_time_min"),
        budget_config.get("expected_print_time_min"),
        default=0.0,
    )
    max_print_time = first_number(
        budget_config.get("max_print_time_min"),
        constraints.get("max_print_time_min"),
        current_spec.get("max_print_time_min"),
        default=120.0,
    )
    expected_load = first_number(
        current_spec.get("target_load_n"),
        current_spec.get("expected_load_n"),
        current_spec.get("load_n"),
        objective.get("target_load_n"),
        default=0.0,
    )
    load_range = constraints.get("allowed_load_range_n") or constraints.get("load_range_n") or []
    range_max_load = load_range[-1] if isinstance(load_range, list) and load_range else None
    max_load = first_number(
        budget_config.get("max_load_n"),
        constraints.get("max_load_n"),
        constraints.get("max_force_n"),
        range_max_load,
        default=0.0,
    )
    robot_rollout_count = count_tool_records("lerobot.rollout", "robot.pick_place")
    max_robot_rollouts = first_int(budget_config.get("max_robot_live_rollouts"), budget_config.get("max_robot_rollouts"), default=3)
    physical_print_count = count_tool_records("printer.start", "printer.auto_eject", "experiment.evaluate")
    max_physical_prints = first_int(budget_config.get("max_physical_prints"), budget_config.get("max_print_jobs"), default=1)

    def budget_item(resource: str, used: float | int | None, limit: float | int | None, unit: str) -> dict[str, object]:
        used_value = float(used or 0.0)
        limit_value = float(limit or 0.0)
        ratio = (used_value / limit_value) if limit_value > 0 else 0.0
        status_value = "exceeded" if limit_value > 0 and ratio > 1.0 else "near_limit" if limit_value > 0 and ratio >= 0.85 else "within_budget"
        return {
            "resource": resource,
            "used": round(used_value, 4),
            "limit": round(limit_value, 4),
            "unit": unit,
            "used_ratio": round(ratio, 4),
            "status": status_value,
        }

    safety_budget_items = [
        budget_item("loop_count", loop_count, max_loop_count, "cycles"),
        budget_item("print_time", expected_print_time, max_print_time, "min"),
        budget_item("load", expected_load, max_load, "N"),
        budget_item("robot_live_rollouts", robot_rollout_count, max_robot_rollouts, "calls"),
        budget_item("physical_prints", physical_print_count, max_physical_prints, "jobs"),
    ]
    safety_budget_status = "exceeded" if any(item["status"] == "exceeded" for item in safety_budget_items) else "near_limit" if any(item["status"] == "near_limit" for item in safety_budget_items) else "within_budget"
    safety_budget = {
        "schema": "guardian_safety_budget.v1",
        "status": safety_budget_status,
        "items": safety_budget_items,
        "source": "run_metadata.safety_budget|current_experiment_spec.constraints|runtime_counts",
    }

    now_iso = datetime.now(timezone.utc).isoformat()
    device_health = state.get("device_health", {}) if isinstance(state.get("device_health"), dict) else {}
    heartbeat_rows: list[dict[str, object]] = []
    for device_id, bridge_state in sorted(device_health.items()):
        device_key = str(device_id)
        latest_alert = next(
            (
                item
                for item in reversed(hardware_alerts)
                if str(item.get("device_class") or item.get("device_id") or item.get("workspace") or "").lower() == device_key.lower()
            ),
            {},
        )
        latest_tool = next(
            (
                item
                for item in reversed(tool_records)
                if device_key.lower() in str(item.get("tool") or item.get("stage") or "").lower()
                or (device_key.lower() == "robot" and "lerobot" in tool_name(item))
                or (device_key.lower() == "printer" and "printer" in tool_name(item))
                or (device_key.lower() == "utm" and ("utm" in tool_name(item) or "pyautogui" in tool_name(item)))
            ),
            {},
        )
        status_text = str(bridge_state or "unknown")
        alert_blocks = isinstance(latest_alert, dict) and bool(latest_alert.get("blocks_workflow"))
        heartbeat_status = (
            "blocked"
            if alert_blocks or any(token in status_text.lower() for token in ("block", "critical", "failed", "error", "unhealthy"))
            else "ready"
            if status_text.lower() in {"ready", "ok", "healthy"}
            else "review"
        )
        heartbeat_rows.append(
            {
                "device_id": device_key,
                "bridge_state": status_text,
                "heartbeat_status": heartbeat_status,
                "last_heartbeat": str(latest_alert.get("created_at") or latest_tool.get("created_at") or now_iso) if isinstance(latest_alert, dict) else now_iso,
                "last_command": str(latest_tool.get("tool") or latest_alert.get("tool") or latest_alert.get("component") or "runtime snapshot") if isinstance(latest_tool, dict) else "runtime snapshot",
                "last_alert_id": str(latest_alert.get("alert_id") or "") if isinstance(latest_alert, dict) else "",
            }
        )
    if not heartbeat_rows:
        heartbeat_rows.append(
            {
                "device_id": "runtime",
                "bridge_state": "unknown",
                "heartbeat_status": "review",
                "last_heartbeat": now_iso,
                "last_command": "runtime snapshot",
                "last_alert_id": "",
            }
        )

    safe_stop_gates = [gate for gate in gates if str(gate.get("decision") or "") in {"safe_stop", "safe_stop_verified"}]
    safe_stop_requested = bool(state.get("safe_stop_requested") or state.get("stop_requested") or any(str(gate.get("decision") or "") == "safe_stop" for gate in safe_stop_gates))
    explicit_safe_stop_verified = bool(metadata.get("safe_stop_verified") or metadata.get("safe_stop_confirmed"))
    inferred_safe_stop_verified = bool(safe_stop_requested and not bool(snapshot.get("is_running")) and str(state.get("stage") or "").lower() in {"complete", "idle", "guardian", "error"})
    safe_stop_verified = explicit_safe_stop_verified or inferred_safe_stop_verified or any(str(gate.get("decision") or "") == "safe_stop_verified" for gate in safe_stop_gates)
    safe_stop_verification = {
        "schema": "guardian_safe_stop_verification.v1",
        "requested": safe_stop_requested,
        "verified": safe_stop_verified,
        "status": "verified" if safe_stop_requested and safe_stop_verified else "requested_unverified" if safe_stop_requested else "not_requested",
        "latest_gate": gate_row(safe_stop_gates[-1]) if safe_stop_gates else {},
        "verification_basis": "explicit_metadata" if explicit_safe_stop_verified else "controller_not_running" if inferred_safe_stop_verified else "guardian_gate" if safe_stop_verified else "none",
    }

    latest_contract_artifacts = latest_contract.get("artifact_refs", []) if isinstance(latest_contract, dict) and isinstance(latest_contract.get("artifact_refs"), list) else []
    latest_contract_provenance = latest_contract.get("provenance_refs", []) if isinstance(latest_contract, dict) and isinstance(latest_contract.get("provenance_refs"), list) else []
    evidence_checks = {
        "guardian_gate_present": bool(latest_gate),
        "contract_present": bool(latest_contract),
        "artifact_refs_present": bool(latest_contract_artifacts),
        "provenance_refs_present": bool(latest_contract_provenance),
        "tool_or_incident_evidence_present": bool(tool_records or incidents or hardware_alerts),
    }
    evidence_score = sum(1 for value in evidence_checks.values() if value) / max(1, len(evidence_checks))
    evidence_completeness = {
        "schema": "guardian_evidence_completeness.v1",
        "score": round(evidence_score, 4),
        "status": "complete" if evidence_score >= 0.8 else "partial" if evidence_score >= 0.4 else "missing",
        "checks": evidence_checks,
        "artifact_ref_count": len(latest_contract_artifacts),
        "provenance_ref_count": len(latest_contract_provenance),
    }

    try:
        variants = [variant.model_dump(mode="json") for variant in _self_evolution_service().list_variants()]
    except Exception as exc:
        variants = []
        evolution_error = str(exc)
    else:
        evolution_error = ""
    pending_variants = [
        item
        for item in variants
        if str(item.get("status") or "") in {"gate_passed", "approved", "evaluated"}
    ][-20:]
    active_variants = [
        item
        for item in variants
        if str(item.get("status") or "") in {"active", "active_next_run"}
    ][-20:]
    activation_gate_status = (
        "active_next_run"
        if active_variants
        else "ready_for_activation"
        if any(str(item.get("status") or "") == "approved" for item in pending_variants)
        else "pending_operator_approval"
        if pending_variants
        else "idle"
    )
    self_evolution_gate = {
        "schema": "guardian_self_evolution_gate.v1",
        "status": activation_gate_status if not evolution_error else "unavailable",
        "pending_variants": pending_variants,
        "active_variants": active_variants,
        "variant_count": len(variants),
        "error": evolution_error,
    }

    status = "safe_stop" if any(row.get("decision") == "safe_stop" for row in blocked_gate_rows) else "blocked" if blocked_gate_rows or blocked_tool_rows or blocked_hardware_rows else "approval_required" if merged_pending else "warning" if incidents or max_score >= 0.35 else "allow"
    return {
        "ok": True,
        "schema": "guardian_status_report.v1",
        "run_id": requested_run_id or active_run_id,
        "experiment_id": state.get("experiment_id", ""),
        "stage": state.get("stage", ""),
        "status": status,
        "summary": {
            "risk_score": round(max_score, 4),
            "dominant_risks": dominant_risks,
            "gate_count": len(gates),
            "incident_count": len(incidents),
            "pending_approval_count": len(merged_pending),
            "blocked_action_count": len(blocked_gate_rows) + len(blocked_tool_rows) + len(blocked_hardware_rows),
            "tool_call_record_count": len(tool_records),
            "safety_budget_status": safety_budget_status,
            "safe_stop_status": safe_stop_verification["status"],
            "evidence_completeness_status": evidence_completeness["status"],
            "self_evolution_gate_status": self_evolution_gate["status"],
        },
        "safety_budget": safety_budget,
        "evidence_completeness": evidence_completeness,
        "self_evolution_gate": self_evolution_gate,
        "graph_wide_risk_map": list(risk_map.values()),
        "gate_timeline": gate_timeline,
        "blocked_actions": {
            "gates": blocked_gate_rows[-40:],
            "tool_calls": blocked_tool_rows[-40:],
            "hardware_alerts": blocked_hardware_rows[-40:],
        },
        "approval_queue": {
            "pending": merged_pending[-50:],
            "resolved": [dict(item) for item in approvals.get("resolved", []) if isinstance(item, dict)][-50:],
            "approvals": [dict(item) for item in approvals.get("approvals", []) if isinstance(item, dict)][-80:],
        },
        "incident_ledger": {
            "records": incidents[-80:],
            "severity_counts": severity_counts,
            "class_counts": class_counts,
        },
        "policy_version_panel": {
            "guardian_gate_schema": "guardian_gate_result.v1",
            "contract_schema": "guardian_contract.v1",
            "decision_schema": "guardian_decision.v1",
            "incident_schema": "incident_record.v1",
            "tool_call_schema": "tool_call_record.v1",
            "source_doc": "docs/runtime/guardian_graphwide_safety.md",
        },
        "device_data_integrity": {
            "device_health": state.get("device_health", {}),
            "live_device_heartbeat": heartbeat_rows,
            "hardware_alert_count": len(hardware_alerts),
            "tool_call_counts": tool_counts,
            "latest_contract_ok_for_next_stage": latest_contract.get("ok_for_next_stage") if isinstance(latest_contract, dict) else None,
            "latest_contract_ok_for_bo": latest_contract.get("ok_for_bo") if isinstance(latest_contract, dict) else None,
            "data_related_incident_count": sum(1 for item in incidents if str(item.get("risk_class") or item.get("class") or "").lower() in {"data", "data_integrity"}),
        },
        "safe_stop_verification": safe_stop_verification,
        "handoff_packet": {
            "latest_guardian_gate": gate_row(latest_gate) if latest_gate else {},
            "latest_guardian_decision": latest_decision if isinstance(latest_decision, dict) else {},
            "latest_guardian_contract": latest_contract if isinstance(latest_contract, dict) else {},
            "latest_handoff_packet": handoff_packets[-1] if handoff_packets else {},
            "corrective_actions": corrective_actions[-40:],
        },
    }


@app.get("/api/state")
async def get_state() -> dict[str, object]:
    """Return current controller state plus host/GPU resource telemetry."""
    snapshot = controller.snapshot()
    snapshot["system_resources"] = _system_resource_snapshot()
    snapshot["guardian_status"] = _guardian_status_payload(snapshot=snapshot)
    snapshot["runtime_ide_contract"] = _runtime_ide_contract_payload(snapshot)
    return snapshot


@app.get("/api/guardian/status")
async def get_guardian_status(run_id: str | None = None) -> dict[str, object]:
    """Return a Guardian graph-wide safety monitor/report payload."""
    return _guardian_status_payload(run_id=run_id)


@app.get("/api/runs/{run_id}/guardian/status")
async def get_run_guardian_status(run_id: str) -> dict[str, object]:
    """Return Guardian monitor/report payload for the requested run."""
    return _guardian_status_payload(run_id=run_id)


@app.get("/api/runtime/state")
async def get_runtime_state_compat() -> dict[str, object]:
    """Compatibility alias for the package-specified runtime state endpoint."""
    snapshot = await get_state()
    return {"ok": True, "compatibility": "atr_live_gui_package", **snapshot}


@app.get("/api/devices/state")
async def get_devices_state_compat() -> dict[str, object]:
    """Compatibility endpoint exposing device/resource state for Live GUI consumers."""
    return _device_state_payload()


@app.get("/api/agents")
async def get_agents_compat() -> dict[str, object]:
    """Compatibility endpoint listing Live GUI agent tabs and runtime aliases."""
    snapshot = controller.snapshot()
    state = snapshot.get("state", {}) if isinstance(snapshot.get("state"), dict) else {}
    active_stage = str(state.get("stage") or "")
    agents = []
    for item in LIVE_AGENT_DEFINITIONS:
        agents.append({
            **item,
            "status": "running" if item["stage"] == active_stage and snapshot.get("is_running") else "idle",
            "report_url": f"/api/agents/{item['agent_id']}/report",
            "backend_trace_url": f"/api/agents/{item['agent_id']}/backend-trace",
        })
    return {"ok": True, "agents": agents, "active_stage": active_stage}


@app.get("/api/agents/{agent_id}/report")
async def get_agent_report_compat(agent_id: str, run_id: str | None = None) -> dict[str, object]:
    """Compatibility endpoint returning a structured agent report payload."""
    return {"ok": True, "report": _agent_report_payload(agent_id, run_id=run_id)}


@app.get("/api/agents/{agent_id}/backend-trace")
async def get_agent_backend_trace_compat(agent_id: str, run_id: str | None = None) -> dict[str, object]:
    """Compatibility endpoint returning raw runtime trace events for one agent."""
    definition, events = _events_for_agent(agent_id, run_id=run_id)
    return {"ok": True, "agent": definition, "run_id": run_id or _current_run_id(), "events": events}


@app.post("/api/agents/{agent_id}/message")
async def post_agent_message_compat(agent_id: str, req: RuntimeAgentMessageRequest) -> dict[str, object]:
    """Compatibility endpoint routing agent-targeted messages through Runtime Chat."""
    definition = _agent_definition(agent_id)
    constraints = dict(req.constraints)
    constraints.update({
        "live_chat_target": definition["agent_id"],
        "live_chat_mode": req.mode,
        "live_selected_agent": definition["agent_id"],
        "compatibility_endpoint": f"/api/agents/{definition['agent_id']}/message",
    })
    return await controller.planning_message(
        message=req.message,
        goal=req.goal,
        backend=req.backend,
        constraints=constraints,
        session_id=req.session_id,
    )


async def _emit_runtime_operator_event(req: RuntimeOperatorEventRequest, run_id: str | None = None) -> dict[str, object]:
    """Record a frontend operator action as auditable runtime evidence."""
    clean_event_type = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", req.event_type.strip())[:160] or "operator.event"
    payload = dict(req.payload)
    payload.update({
        "action": req.action or clean_event_type,
        "agent_id": req.agent_id,
        "agent": req.agent_id,
        "node_id": req.node_id or req.agent_id,
        "trace_id": req.trace_id,
        "event_key": req.event_key,
        "operator_source": "live_gui",
        "status": "recorded" if req.level != "ERROR" else "failed",
    })
    event = await controller.emit_runtime_event(
        event_type=clean_event_type,
        message=req.message or f"Operator action recorded: {req.action or clean_event_type}",
        payload=payload,
        level=req.level,
        run_id=run_id,
    )
    return {"ok": True, "event": event}


@app.post("/api/runtime/operator-event")
async def post_runtime_operator_event(req: RuntimeOperatorEventRequest) -> dict[str, object]:
    """Record a Live GUI operator action against the current runtime session."""
    return await _emit_runtime_operator_event(req)


@app.post("/api/runs/{run_id}/operator-events")
async def post_runtime_run_operator_event(run_id: str, req: RuntimeOperatorEventRequest) -> dict[str, object]:
    """Record a Live GUI operator action against the addressed active run."""
    _require_current_run(run_id)
    return await _emit_runtime_operator_event(req, run_id=run_id)


@app.post("/api/guardian/incidents/{incident_id}/notes")
async def post_guardian_incident_note(incident_id: str, req: GuardianIncidentNoteRequest) -> dict[str, object]:
    """Attach an operator note to a Guardian incident in the active run."""
    return await _attach_guardian_incident_note(incident_id, req)


@app.post("/api/runs/{run_id}/guardian/incidents/{incident_id}/notes")
async def post_run_guardian_incident_note(run_id: str, incident_id: str, req: GuardianIncidentNoteRequest) -> dict[str, object]:
    """Attach an operator note to a Guardian incident in the addressed active run."""
    _require_current_run(run_id)
    return await _attach_guardian_incident_note(incident_id, req, run_id=run_id)


def _graph_config_items() -> list[tuple[str, Path, GraphConfig]]:
    """Return all discoverable graph configs, with the main closed-loop graph first."""
    items: list[tuple[str, Path, GraphConfig]] = []
    for path in sorted(RUNTIME_GRAPH_CONFIG_ROOT.glob("*.yaml")):
        try:
            config = load_graph_config(path)
        except Exception:
            continue
        items.append((config.id, path, config))
    return sorted(items, key=lambda item: (item[0] != PRIMARY_RUNTIME_GRAPH_ID, item[0]))


def _graph_config_path(graph_id: str) -> Path:
    """Resolve one graph id to its config file."""
    for item_id, path, _config in _graph_config_items():
        if item_id == graph_id:
            return path
    raise HTTPException(status_code=404, detail=f"Unknown graph_id={graph_id}")


def _graph_config_runtime_path(path: Path) -> str:
    """Return a stable graph config path for runtime handoff payloads."""
    try:
        return path.resolve().relative_to(resolve_path(".").resolve()).as_posix()
    except ValueError:
        return str(path)


def _load_runtime_graph_config(graph_id: str) -> GraphConfig:
    """Load one runtime graph config by graph id."""
    return load_graph_config(_graph_config_path(graph_id))


def _graph_version_store(graph_id: str = PRIMARY_RUNTIME_GRAPH_ID) -> GraphVersionStore:
    """Return the file-backed graph version store for one graph config."""
    return GraphVersionStore(
        active_config_path=_graph_config_path(graph_id),
        version_root=RUNTIME_GRAPH_VERSION_ROOT,
    )


def _module_config_store() -> ModuleConfigStore:
    """Return the file-backed module config store."""
    return ModuleConfigStore(
        module_root=RUNTIME_MODULE_ROOT,
        version_root=RUNTIME_MODULE_VERSION_ROOT,
    )


def _knowledge_store() -> JsonlKnowledgeStore:
    """Return the file-backed Knowledge memory store."""
    return JsonlKnowledgeStore(memory_root=KNOWLEDGE_MEMORY_ROOT, run_root=resolve_path("runs"))


def _knowledge_graph_backend():
    """Return optional Knowledge graph backend from environment.

    Neo4j is optional. If disabled or unavailable with fail-open enabled, the
    backend returns disabled/JSON fallback status and does not break runtime APIs.
    """
    return graph_backend_from_env(resolve_path("."))


def _self_evolution_service() -> SelfEvolutionService:
    """Return the file-backed ATR self-evolution service."""
    return SelfEvolutionService(
        root=SELF_EVOLUTION_ROOT,
        run_root=resolve_path("runs"),
        graph_config_root=RUNTIME_GRAPH_CONFIG_ROOT,
        graph_version_root=RUNTIME_GRAPH_VERSION_ROOT,
        module_root=RUNTIME_MODULE_ROOT,
        module_version_root=RUNTIME_MODULE_VERSION_ROOT,
        knowledge_memory_root=KNOWLEDGE_MEMORY_ROOT,
    )


def _store_api_guardian_gate(gate: dict[str, Any]) -> dict[str, Any] | None:
    """Persist a controller/API-origin Guardian gate into current runtime metadata."""
    metadata = controller._state.run_metadata
    gates = metadata.setdefault("guardian_gates", [])
    if not isinstance(gates, list):
        gates = []
        metadata["guardian_gates"] = gates
    gates.append(gate)
    del gates[:-200]
    metadata["latest_guardian_gate"] = gate
    decision = gate.get("guardian_decision") if isinstance(gate.get("guardian_decision"), dict) else {}
    if decision:
        metadata["latest_guardian_gate_decision"] = decision
    contract = gate.get("guardian_contract") if isinstance(gate.get("guardian_contract"), dict) else {}
    if contract:
        contracts = metadata.setdefault("guardian_contracts", [])
        if isinstance(contracts, list):
            contracts.append(contract)
            del contracts[:-200]
    incidents = [dict(item) for item in gate.get("incident_records", []) if isinstance(item, dict)] if isinstance(gate.get("incident_records"), list) else []
    if incidents and hasattr(controller, "_record_incident_records"):
        controller._record_incident_records(incidents)
    else:
        incident_records = metadata.setdefault("incident_records", [])
        if not isinstance(incident_records, list):
            incident_records = []
            metadata["incident_records"] = incident_records
        for incident in incidents:
            incident_records.append(dict(incident))
        del incident_records[:-100]
    if str(gate.get("decision") or "") != "require_human_approval":
        return None
    approvals = metadata.setdefault("runtime_approvals", {})
    if not isinstance(approvals, dict):
        approvals = {}
        metadata["runtime_approvals"] = approvals
    gate_id = str(gate.get("gate_id") or make_event_id())
    gate_key = f"guardian:{gate.get('stage', 'self_evolution')}:{gate.get('phase', '')}:{gate.get('tool') or gate.get('agent') or 'runtime'}:{gate_id}"
    record = {
        "approval_id": gate_id.replace("guardian-gate-", "approval-", 1) if gate_id.startswith("guardian-gate-") else make_event_id().replace("evt-", "approval-", 1),
        "gate_key": gate_key,
        "source": "guardian_gate",
        "stage": gate.get("stage", "self_evolution"),
        "phase": gate.get("phase", "evolution_review"),
        "tool": gate.get("tool", ""),
        "agent": gate.get("agent", "self_evolution_service"),
        "status": "pending",
        "reason": gate.get("reason_code", "HUMAN_APPROVAL_REQUIRED"),
        "guardian_gate_id": gate_id,
        "guardian_gate": gate,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    approvals[gate_key] = record
    queue = metadata.setdefault("guardian_approval_queue", [])
    if isinstance(queue, list):
        queue.append(record)
        del queue[:-100]
    return record


async def _emit_self_evolution_guardian_gate(
    *,
    action: str,
    variant_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Create, persist, and emit a Guardian gate for self-evolution control actions."""
    tool_name = "self_evolution.rollback" if action == "rollback_variant" else "self_evolution.activate"
    gate = guardian_gate(
        state=controller._state,
        stage="self_evolution",
        phase="evolution_review",
        payload={"variant_id": variant_id, **payload},
        agent="self_evolution_service",
        tool=tool_name,
        action=action,
    )
    approval_record = _store_api_guardian_gate(gate)
    await controller.emit_runtime_event(
        event_type="guardian.gate",
        message=f"Guardian self-evolution gate {gate.get('decision')} for {action}: {variant_id}",
        payload={
            "agent": "guardian_agent",
            "node_id": "self_evolution",
            "module_id": "guardian",
            "status": gate.get("status", ""),
            "guardian_gate": gate,
            "guardian_decision": gate.get("guardian_decision", {}),
            "guardian_contract": gate.get("guardian_contract", {}),
            "approval_request": approval_record if isinstance(approval_record, dict) else {},
            "risk_score": gate.get("risk_score", 0.0),
            "reason_code": gate.get("reason_code", ""),
        },
        level="ERROR" if gate_blocks_execution(gate) else "WARNING" if gate.get("decision") in {"require_human_approval", "allow_with_warning"} else "INFO",
    )
    return gate


def _graph_config_payload(graph_id: str = PRIMARY_RUNTIME_GRAPH_ID) -> dict[str, object]:
    """Return one config-driven LangGraph definition as JSON-safe data."""
    config = _load_runtime_graph_config(graph_id)
    return config.model_dump(mode="json")


def _runtime_ide_contract_payload(snapshot: dict[str, Any] | None = None) -> dict[str, object]:
    """Expose the actual runtime graph/module/bridge contract consumed by Runtime IDE."""
    snapshot = snapshot or {}
    state = snapshot.get("state", {}) if isinstance(snapshot.get("state"), dict) else {}
    run_metadata = state.get("run_metadata", {}) if isinstance(state.get("run_metadata"), dict) else {}
    try:
        config = _load_runtime_graph_config(PRIMARY_RUNTIME_GRAPH_ID)
        graph_payload = config.model_dump(mode="json")
        graph_metadata = graph_payload.get("metadata", {}) if isinstance(graph_payload.get("metadata"), dict) else {}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "graph_id": PRIMARY_RUNTIME_GRAPH_ID}

    module_contracts: list[dict[str, object]] = []
    for module_path in sorted(RUNTIME_MODULE_ROOT.glob("*/module.yaml")):
        try:
            item = _module_list_item(module_path)
            module_payload = _module_config_payload(str(item.get("id") or module_path.parent.name))
        except Exception as exc:
            module_contracts.append({"module_id": module_path.parent.name, "error": str(exc), "path": str(module_path)})
            continue
        module = module_payload.get("module", {}) if isinstance(module_payload.get("module"), dict) else {}
        metadata = module.get("metadata") if isinstance(module.get("metadata"), dict) else {}
        module_contracts.append({
            "module_id": str(module.get("id") or item.get("id") or module_path.parent.name),
            "label": str(module.get("label") or item.get("label") or module_path.parent.name),
            "handler": str(module.get("handler") or item.get("handler") or ""),
            "category": item.get("category", _module_category(module)),
            "llm_role": str(module.get("llm_role") or ""),
            "tools": list(module.get("tools") or []),
            "runtime_contract": module.get("runtime_contract", {}) if isinstance(module.get("runtime_contract"), dict) else {},
            "device_bridge_contracts": module.get("device_bridge_contracts", []) if isinstance(module.get("device_bridge_contracts"), list) else [],
            "output_contracts": module.get("output_contracts", []) if isinstance(module.get("output_contracts"), list) else [],
            "io_contract": module.get("io_contract", {}) if isinstance(module.get("io_contract"), dict) else {},
            "safety": module.get("safety", {}) if isinstance(module.get("safety"), dict) else {},
            "source_path": str(metadata.get("python_source_path") or metadata.get("source_path") or ""),
            "path": str(module_path),
        })

    supervisor_evidence_keys = [
        "latest_mission_contract",
        "latest_orchestration_plan",
        "latest_orchestrator_parallel_checks",
        "latest_orchestrator_followup",
        "orchestrator_decision_register",
        "latest_orchestrator_handoff",
        "latest_loop_reflection",
    ]
    supervisor_evidence = {key: run_metadata.get(key) for key in supervisor_evidence_keys if key in run_metadata}
    bridge_health = state.get("device_health", {}) if isinstance(state.get("device_health"), dict) else {}

    return {
        "ok": True,
        "graph_id": graph_payload.get("id", PRIMARY_RUNTIME_GRAPH_ID),
        "graph_version": graph_payload.get("version", ""),
        "runtime_planes": graph_metadata.get("runtime_planes", []),
        "device_bridges": graph_metadata.get("device_bridges", []),
        "runtime_contract_map": graph_metadata.get("runtime_contract_map", {}),
        "module_contracts": module_contracts,
        "supervisor_evidence": supervisor_evidence,
        "device_health": bridge_health,
        "active_stage": state.get("stage", ""),
        "run_id": snapshot.get("run_id") or state.get("run_id") or _current_run_id(),
        "source_endpoints": ["/api/graphs/atr_closed_loop", "/api/modules", "/api/state", "/api/devices/state", "/api/guardian/status"],
    }


def _graph_config_digest(config: GraphConfig) -> str:
    """Return a stable digest for dry-run gating against the active graph payload."""
    payload = json.dumps(config.model_dump(mode="json"), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _graph_version_evidence(graph_id: str, config: GraphConfig) -> dict[str, object]:
    """Return traceable graph version/hash evidence for run and event payloads."""
    graph_hash = _graph_config_digest(config)
    matched_version: dict[str, object] = {}
    for item in _graph_version_store(graph_id).list_versions(graph_id):
        version_id = str(item.get("version_id") or "")
        if not version_id:
            continue
        try:
            version = _graph_version_store(graph_id).read_version(graph_id, version_id)
            version_graph = GraphConfig.model_validate(version.get("graph") or {})
        except Exception:
            continue
        if _graph_config_digest(version_graph) == graph_hash:
            matched_version = version
            break
    metadata = matched_version.get("metadata") if isinstance(matched_version.get("metadata"), dict) else {}
    return {
        "graph_id": graph_id,
        "graph_hash": graph_hash,
        "graph_version": str(matched_version.get("version_id") or metadata.get("version_id") or "active"),
        "graph_version_id": str(matched_version.get("version_id") or metadata.get("version_id") or ""),
        "graph_version_path": str(matched_version.get("path") or ""),
        "graph_version_created_at": str(metadata.get("created_at") or ""),
        "graph_version_author": str(metadata.get("author") or ""),
        "graph_version_reason": str(metadata.get("reason") or ""),
    }


def _record_graph_dry_run(
    *,
    config: GraphConfig,
    options: RuntimeGraphDryRunRequest,
    sequence: list[dict[str, object]],
    compiled_graph: dict[str, object],
) -> dict[str, object]:
    """Store the latest successful active-config dry-run evidence for live run gates."""
    record = {
        "graph_id": config.id,
        "digest": _graph_config_digest(config),
        "dry_run_at": datetime.now(timezone.utc).isoformat(),
        "start_stage": options.start_stage,
        "max_steps": options.max_steps,
        "step_count": len(sequence),
        "compiled_graph": compiled_graph,
        "live_gate_recorded": True,
    }
    _RUNTIME_GRAPH_DRY_RUN_RECORDS[config.id] = record
    return record


def _graph_dry_run_evidence(
    *,
    config: GraphConfig,
    compiled_graph: dict[str, object],
    options: RuntimeGraphDryRunRequest | None = None,
    record_live_gate: bool = False,
) -> dict[str, object]:
    """Build non-device graph dry-run evidence, optionally recording the live gate."""
    run_options = options or RuntimeGraphDryRunRequest(start_stage="idle", max_steps=24)
    sequence = _graph_dry_run_sequence(config, max_steps=run_options.max_steps, start_stage=run_options.start_stage)
    if record_live_gate:
        dry_run_record = _record_graph_dry_run(
            config=config,
            options=run_options,
            sequence=sequence,
            compiled_graph=compiled_graph,
        )
    else:
        dry_run_record = {
            "graph_id": config.id,
            "digest": _graph_config_digest(config),
            "dry_run_at": datetime.now(timezone.utc).isoformat(),
            "start_stage": run_options.start_stage,
            "max_steps": run_options.max_steps,
            "step_count": len(sequence),
            "compiled_graph": compiled_graph,
            "draft": True,
            "live_gate_recorded": False,
        }
    return {
        "ok": True,
        "graph_id": config.id,
        "errors": [],
        "start_stage": run_options.start_stage,
        "sequence": sequence,
        "compiled_graph": compiled_graph,
        "dry_run_record": dry_run_record,
    }


def _graph_live_dry_run_gate(config: GraphConfig) -> tuple[bool, dict[str, object]]:
    """Return whether the active graph has a matching dry-run record for live execution."""
    record = _RUNTIME_GRAPH_DRY_RUN_RECORDS.get(config.id, {})
    if not record:
        return False, {}
    return record.get("digest") == _graph_config_digest(config), record


def _graph_list_item(config: GraphConfig, path: Path) -> dict[str, object]:
    """Return one graph list entry for Runtime IDE selection."""
    metadata = config.metadata if isinstance(config.metadata, dict) else {}
    return {
        "id": config.id,
        "name": config.name,
        "version": config.version,
        "path": str(path),
        "primary": config.id == PRIMARY_RUNTIME_GRAPH_ID,
        "workspace": metadata.get("workspace", ""),
        "template": metadata.get("template", config.id != PRIMARY_RUNTIME_GRAPH_ID),
        "executable_from_runtime_ide": bool(
            metadata.get("executable_from_runtime_ide", config.id == PRIMARY_RUNTIME_GRAPH_ID)
        ),
        "node_count": len(config.nodes),
        "transition_count": len(config.transitions),
    }


def _module_config_payload(module_id: str) -> dict[str, object]:
    """Read one allowlisted module config by id."""
    safe_module = module_id.strip().replace("/", "_").replace("..", "_")
    module_path = RUNTIME_MODULE_ROOT / safe_module / "module.yaml"
    if not module_path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown module_id={module_id}")
    raw = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def _module_category(module: dict[str, Any]) -> str:
    """Return an operator-facing module category for catalog grouping."""
    metadata = module.get("metadata") if isinstance(module.get("metadata"), dict) else {}
    explicit = str(module.get("category") or metadata.get("category") or "").strip()
    if explicit:
        return explicit
    module_id = str(module.get("id") or "").strip().lower()
    id_categories = {
        "orchestrator": "orchestration",
        "design": "design",
        "specimen": "fabrication",
        "specimen_making": "fabrication",
        "vision": "vision",
        "manipulation": "manipulation",
        "equipment": "equipment",
        "analysis": "analysis",
        "bo": "optimization",
        "knowledge": "knowledge",
        "guardian": "guardian",
    }
    if module_id in id_categories:
        return id_categories[module_id]
    handler = str(module.get("handler") or "")
    tools = module.get("tools") if isinstance(module.get("tools"), list) else []
    if any(str(tool).startswith("printer.") or str(tool).startswith("geometry.") for tool in tools):
        return "fabrication"
    if any(str(tool).startswith("lerobot.") or str(tool).startswith("robot.") for tool in tools):
        return "robotics"
    if any(str(tool).startswith("equipment.") or str(tool).startswith("utm.") for tool in tools):
        return "lab-equipment"
    if any(str(tool).startswith("cae.") or str(tool).startswith("experiment.") for tool in tools):
        return "analysis-optimization"
    return "runtime"


def _module_list_item(path: Path) -> dict[str, object]:
    """Return one catalog item for Runtime IDE module listing."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raw = {}
    module = raw.get("module", {}) if isinstance(raw, dict) else {}
    module = module if isinstance(module, dict) else {}
    metadata = module.get("metadata") if isinstance(module.get("metadata"), dict) else {}
    internal_graph = module.get("internal_graph") if isinstance(module.get("internal_graph"), list) else []
    pre_execution = module.get("pre_execution") if isinstance(module.get("pre_execution"), list) else []
    tools = module.get("tools") if isinstance(module.get("tools"), list) else []
    return {
        "id": module.get("id", path.parent.name),
        "label": module.get("label", path.parent.name),
        "handler": module.get("handler", ""),
        "category": _module_category(module),
        "path": str(path),
        "tools": tools,
        "tool_count": len(tools),
        "pre_execution_count": len(pre_execution),
        "internal_graph_count": len(internal_graph),
        "source_path": metadata.get("python_source_path", ""),
        "source_filename": metadata.get("source_filename", ""),
        "pending_handler_registration": bool(metadata.get("pending_handler_registration", False)),
        "generated_adapter_approved": bool(metadata.get("generated_adapter_approved", False)),
        "generated_adapter_handler_id": metadata.get("generated_adapter_handler_id", ""),
        "generated_adapter_path": metadata.get("transformed_python_source_path") or metadata.get("transformed_source_path") or "",
        "runtime_contract": module.get("runtime_contract", {}) if isinstance(module.get("runtime_contract"), dict) else {},
        "device_bridge_contracts": module.get("device_bridge_contracts", []) if isinstance(module.get("device_bridge_contracts"), list) else [],
        "output_contracts": module.get("output_contracts", []) if isinstance(module.get("output_contracts"), list) else [],
        "io_contract": module.get("io_contract", {}) if isinstance(module.get("io_contract"), dict) else {},
    }


def _safe_source_filename(filename: str) -> str:
    """Return a safe Python source filename for module designer uploads."""
    clean = Path(str(filename or "handler.py")).name.strip() or "handler.py"
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in clean)
    if not safe.endswith(".py"):
        safe += ".py"
    return safe


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response."""
    clean = str(text or "").strip()
    if not clean:
        raise ValueError("empty LLM response")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, re.DOTALL | re.IGNORECASE)
    if fence:
        clean = fence.group(1).strip()
    else:
        start = clean.find("{")
        end = clean.rfind("}")
        if start >= 0 and end > start:
            clean = clean[start : end + 1]
    data = json.loads(clean)
    if not isinstance(data, dict):
        raise ValueError("LLM response JSON must be an object")
    return data


def _module_designer_category(value: str) -> str:
    """Normalize LLM/user category names for catalog grouping."""
    clean = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    aliases = {
        "3dp": "fabrication",
        "printer": "fabrication",
        "printing": "fabrication",
        "robot": "manipulation",
        "robotics": "manipulation",
        "lab-equipment": "equipment",
        "lab": "equipment",
        "cae": "analysis",
        "bo": "optimization",
        "mbo": "optimization",
        "safety": "guardian",
    }
    return aliases.get(clean, clean or "custom")


def _registered_tool_names() -> set[str]:
    """Return tool registry names without letting registry failures break module design."""
    try:
        return set(controller._deps.agent_context.tools.list_tools())
    except Exception:
        return set()


def _safe_step_id(value: str, fallback: str) -> str:
    """Return a module-step-safe id."""
    clean = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_")
    return clean or fallback


def _normalize_designer_steps(
    raw_steps: Any,
    *,
    default_handler: str,
    handler_registry: set[str],
) -> list[dict[str, object]]:
    """Normalize LLM-generated internal steps into ModuleStep-compatible dictionaries."""
    if not isinstance(raw_steps, list):
        raw_steps = []
    steps: list[dict[str, object]] = []
    for index, item in enumerate(raw_steps[:8], start=1):
        if not isinstance(item, dict):
            continue
        step_id = _safe_step_id(str(item.get("id") or item.get("name") or ""), f"step_{index:02d}")
        label = str(item.get("label") or item.get("name") or step_id).strip() or step_id
        kind = str(item.get("kind") or "internal_step").strip() or "internal_step"
        step: dict[str, object] = {"id": step_id, "label": label, "kind": kind}
        handler = str(item.get("handler") or "").strip()
        if handler and handler in handler_registry:
            step["handler"] = handler
        steps.append(step)
    if steps:
        return steps
    return [
        {"id": "01_review_inputs", "label": "Review Inputs", "kind": "internal_step"},
        {"id": "02_execute_protocol_adapter", "label": "Execute Protocol Adapter", "kind": "internal_step", "handler": default_handler},
        {"id": "03_emit_agent_result", "label": "Emit AgentResult", "kind": "internal_step"},
    ]


def _module_designer_system_prompt() -> str:
    """Return the fixed system prompt used by the Module Designer model."""
    return (
        "You are the ATR Runtime IDE Module Designer. Convert one uploaded Python module "
        "into an Autonomous Researcher internal module adapter. Return only strict JSON. "
        "The generated file must respect the ATR communication contract: async run(state: "
        "OrchestratorState, ctx: AgentContext) -> AgentResult, no top-level side effects, no "
        "hardware/network action during import, structured errors, and all tool/device work routed "
        "through ctx.tools or existing allowlisted handlers. Classify the module category. "
        "Do not invent unregistered handler ids; if execution needs new Python registration, keep "
        "handler as runtime.step_complete and explain pending_handler_registration in notes."
    )


def _module_designer_user_prompt(
    *,
    req: RuntimeModuleCreateRequest,
    safe_id: str,
    source_excerpt: str,
    source_truncated: bool,
    handler_names: list[str],
    tool_names: list[str],
) -> str:
    """Build the bounded prompt for Python-to-ATR module conversion."""
    return json.dumps(
        {
            "task": "convert_python_file_to_atr_internal_module",
            "module_id": safe_id,
            "requested_label": req.label,
            "requested_category": req.category,
            "requested_handler": req.handler,
            "requested_llm_role": req.llm_role,
            "operator_notes": req.notes,
            "source_filename": req.source_filename,
            "source_truncated_for_prompt": source_truncated,
            "atr_protocol_contract": {
                "adapter_signature": "async run(state: OrchestratorState, ctx: AgentContext) -> AgentResult",
                "return_type": "agents.base_agent.AgentResult",
                "state_type": "orchestrator.state.OrchestratorState",
                "tool_access": "ctx.tools.call(tool_name, payload)",
                "no_import_side_effects": True,
                "output_rule": "AgentResult.data must be JSON-serializable and merge-safe",
            },
            "allowed_handlers": handler_names[:64],
            "registered_tools": tool_names[:160],
            "required_json_schema": {
                "label": "short operator label",
                "category": "one of orchestration/design/fabrication/vision/manipulation/equipment/analysis/optimization/knowledge/guardian/runtime/custom or a concise custom slug",
                "handler": "one allowed handler id, usually runtime.step_complete unless an existing agent handler is appropriate",
                "llm_role": "optional task route hint",
                "tools": ["registered tool names only"],
                "internal_graph": [{"id": "01_step", "label": "Step label", "kind": "internal_step", "handler": "optional allowed handler"}],
                "notes": "operator-facing transformation summary",
                "transformed_source": "complete Python source for the ATR adapter file",
            },
            "uploaded_python_source": source_excerpt,
        },
        ensure_ascii=False,
    )


async def _transform_module_source_with_model(req: RuntimeModuleCreateRequest, safe_id: str) -> dict[str, Any]:
    """Use the active inference backend to transform uploaded Python into ATR module JSON."""
    source_text = str(req.source_text or "")
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="Module Designer requires a Python source file.")

    source_limit = 7200
    source_excerpt = source_text[:source_limit]
    source_truncated = len(source_text) > source_limit
    handlers = sorted(_runtime_graph_handler_registry().names())
    tools = sorted(_registered_tool_names())
    ctx = controller._deps.agent_context
    active_router = ctx.model_routers.get(ctx.active_backend, ctx.model_router)
    active_selection = active_router.select("module_designer")
    requested_model = str(req.transform_model or "").strip() or os.getenv(
        "AUTONOMOUS_MODULE_DESIGNER_MODEL",
        "",
    ).strip()
    model = requested_model or active_selection.primary
    active_backend = ctx.primary_backends.get(ctx.active_backend) or ctx.primary_backend
    attempts: list[tuple[str, Any, str, str]] = []
    fallback_backend_name = ctx.backend_fallbacks.get(ctx.active_backend, "")
    backend_fallback_attempt: tuple[str, Any, str, str] | None = None
    if fallback_backend_name and fallback_backend_name != ctx.active_backend:
        fallback_router = ctx.model_routers.get(fallback_backend_name, ctx.model_router)
        fallback_selection = fallback_router.select("module_designer")
        backend_fallback_attempt = (
            fallback_backend_name,
            ctx.fallback_backends.get(ctx.active_backend, ctx.fallback_backend),
            fallback_selection.primary,
            f"{fallback_selection.role}:backend_fallback",
        )
    api_key_primary = fallback_backend_name == "openai" and backend_fallback_attempt is not None
    if api_key_primary:
        attempts.append(backend_fallback_attempt)

    attempts.append((ctx.active_backend, active_backend, model, active_selection.role))
    if (
        not requested_model
        and active_selection.fallback
        and active_selection.fallback != active_selection.primary
    ):
        attempts.append(
            (
                ctx.active_backend,
                active_backend,
                active_selection.fallback,
                f"{active_selection.role}:model_fallback",
            )
        )
    if backend_fallback_attempt is not None and not api_key_primary:
        attempts.append(backend_fallback_attempt)

    last_error: Exception | None = None
    response = None
    used_model = model
    for _backend_name, backend, attempt_model, role in attempts:
        prepare_model = getattr(backend, "prepare_model", None)
        if prepare_model is not None:
            await prepare_model(attempt_model)
        try:
            response = await backend.complete(
                model=attempt_model,
                system_prompt=_module_designer_system_prompt(),
                user_prompt=_module_designer_user_prompt(
                    req=req,
                    safe_id=safe_id,
                    source_excerpt=source_excerpt,
                    source_truncated=source_truncated,
                    handler_names=handlers,
                    tool_names=tools,
                ),
                metadata={"task_type": "module_designer", "role": role, "max_tokens": 1400},
            )
            if not str(response.text or "").strip():
                raise RuntimeError(f"empty LLM response from backend={_backend_name} model={attempt_model}")
            used_model = attempt_model
            break
        except Exception as exc:
            last_error = exc
    if response is None:
        raise HTTPException(status_code=502, detail=f"Module Designer model transform failed: {last_error}") from last_error

    try:
        payload = _extract_json_object(response.text)
    except Exception as exc:
        snippet = response.text[:1200] if response.text else ""
        raise HTTPException(status_code=502, detail=f"Module Designer model returned invalid module JSON: {exc}; response={snippet}") from exc

    transformed_source = str(payload.get("transformed_source") or "").strip()
    if not transformed_source:
        raise HTTPException(status_code=502, detail="Module Designer model response did not include transformed_source.")
    payload["_used_model"] = used_model
    payload["_model"] = response.model
    payload["_source_truncated_for_prompt"] = source_truncated
    return payload


def _module_id_from_graph_node_module_id(module_id: str | None) -> str:
    """Normalize a graph node module reference such as modules/design to design."""
    if not module_id:
        return ""
    return Path(str(module_id).strip()).name


def _module_runtime_summary(module_id: str) -> dict[str, object]:
    """Return the editable module runtime metadata exposed by dry-run APIs."""
    if not module_id:
        return {}
    try:
        payload = _module_config_payload(module_id)
    except HTTPException:
        return {"module_id": module_id, "missing": True}
    normalized = ModuleConfigStore.normalize_payload(dict(payload))
    module = normalized.get("module", {}) if isinstance(normalized, dict) else {}
    if not isinstance(module, dict):
        return {"module_id": module_id, "missing": True}
    try:
        module = ModuleConfig.model_validate(module).model_dump(mode="json", exclude_none=True)
    except Exception as exc:
        return {"module_id": module_id, "schema_error": str(exc)}
    sequence = _module_dry_run_sequence(module_id, {"module": module})
    pre_execution = [item for item in sequence if item.get("phase") == "pre_execution"]
    internal_graph = [item for item in sequence if item.get("phase") == "internal_graph"]
    return {
        "module_id": module.get("id", module_id),
        "label": module.get("label", ""),
        "handler": module.get("handler", ""),
        "effective_handler": module.get("handler", ""),
        "llm_role": module.get("llm_role", ""),
        "tool_count": len(module.get("tools", [])) if isinstance(module.get("tools"), list) else 0,
        "pre_execution_count": len(pre_execution),
        "internal_graph_count": len(internal_graph),
        "sequence": sequence,
        "runtime_contract": module.get("runtime_contract", {}) if isinstance(module.get("runtime_contract"), dict) else {},
        "device_bridge_contracts": module.get("device_bridge_contracts", []) if isinstance(module.get("device_bridge_contracts"), list) else [],
        "output_contracts": module.get("output_contracts", []) if isinstance(module.get("output_contracts"), list) else [],
        "io_contract": module.get("io_contract", {}) if isinstance(module.get("io_contract"), dict) else {},
        "safety": module.get("safety", {}) if isinstance(module.get("safety"), dict) else {},
    }


def _validate_module_payload(module_id: str, payload: dict[str, Any]) -> list[str]:
    """Validate editable module config without executing Python source."""
    errors: list[str] = []
    normalized = ModuleConfigStore.normalize_payload(dict(payload))
    module = normalized.get("module", {}) if isinstance(normalized, dict) else {}
    if not isinstance(module, dict):
        return ["module payload must contain an object"]
    try:
        ModuleConfig.model_validate(module)
    except Exception as exc:
        errors.append(f"module schema validation failed: {exc}")
    if module.get("id") != module_id:
        errors.append(f"module_id path/body mismatch: {module_id} != {module.get('id')}")
    handler_registry = _runtime_graph_handler_registry().names()
    handler = str(module.get("handler", ""))
    if handler not in handler_registry:
        errors.append(f"unregistered handler: {handler}")
    llm_role = module.get("llm_role", "")
    if llm_role is not None and not isinstance(llm_role, str):
        errors.append("llm_role must be a string")
    llm = module.get("llm", {})
    if llm and not isinstance(llm, dict):
        errors.append("llm must be an object")
    elif isinstance(llm, dict):
        for key in ("backend", "model", "primary", "fallback"):
            if key in llm and not isinstance(llm[key], str):
                errors.append(f"llm.{key} must be a string")
        for key in ("temperature", "top_p"):
            if key in llm and not isinstance(llm[key], int | float):
                errors.append(f"llm.{key} must be numeric")
        if "max_tokens" in llm and (not isinstance(llm["max_tokens"], int) or int(llm["max_tokens"]) < 1):
            errors.append("llm.max_tokens must be a positive integer")
    timeout = module.get("timeout_s")
    if timeout is not None and (not isinstance(timeout, int | float) or float(timeout) < 0):
        errors.append("timeout_s must be a non-negative number")
    retry = module.get("retry", {})
    if retry and not isinstance(retry, dict):
        errors.append("retry must be an object")
    elif isinstance(retry, dict):
        max_attempts = retry.get("max_attempts")
        if max_attempts is not None and (not isinstance(max_attempts, int) or not 0 <= max_attempts <= 10):
            errors.append("retry.max_attempts must be an integer between 0 and 10")
        backoff_s = retry.get("backoff_s")
        if backoff_s is not None and (not isinstance(backoff_s, int | float) or float(backoff_s) < 0):
            errors.append("retry.backoff_s must be a non-negative number")
    prompt = module.get("prompt", {})
    if prompt and not isinstance(prompt, (dict, str)):
        errors.append("prompt must be an object or string")
    elif isinstance(prompt, dict):
        for key in ("path", "system", "developer", "user_template"):
            if key in prompt and not isinstance(prompt[key], str):
                errors.append(f"prompt.{key} must be a string")
    pre_execution = module.get("pre_execution", [])
    if pre_execution and not isinstance(pre_execution, list):
        errors.append("pre_execution must be a list")
    elif isinstance(pre_execution, list):
        pre_ids = [str(step.get("id", "")) for step in pre_execution if isinstance(step, dict)]
        for index, step in enumerate(pre_execution, start=1):
            if not isinstance(step, dict):
                errors.append(f"pre_execution contains non-object step at {index}")
                continue
            if not str(step.get("id", "")).strip():
                errors.append(f"pre_execution step at {index} must have id")
            handler_id = str(step.get("handler") or "").strip()
            if not handler_id:
                errors.append(f"pre_execution step at {index} must have handler")
            elif handler_id not in handler_registry:
                errors.append(f"unregistered pre_execution handler at {index}: {handler_id}")
            if "enabled" in step and not isinstance(step["enabled"], bool):
                errors.append(f"pre_execution.enabled at {index} must be boolean")
            for key in ("output_key", "event_type", "label", "kind"):
                if key in step and not isinstance(step[key], str):
                    errors.append(f"pre_execution.{key} at {index} must be a string")
        for step_id in sorted({step_id for step_id in pre_ids if step_id and pre_ids.count(step_id) > 1}):
            errors.append(f"duplicate pre_execution step id: {step_id}")
    internal_graph = module.get("internal_graph", [])
    if not isinstance(internal_graph, list):
        errors.append("internal_graph must be a list")
    else:
        step_ids = [str(step.get("id", "")) for step in internal_graph if isinstance(step, dict)]
        missing_id_count = sum(1 for step_id in step_ids if not step_id.strip())
        if missing_id_count:
            errors.append(f"internal_graph contains {missing_id_count} step(s) without id")
        malformed_step_count = sum(1 for step in internal_graph if not isinstance(step, dict))
        if malformed_step_count:
            errors.append(f"internal_graph contains {malformed_step_count} non-object step(s)")
        duplicates = sorted({step_id for step_id in step_ids if step_id and step_ids.count(step_id) > 1})
        for step_id in duplicates:
            errors.append(f"duplicate internal_graph step id: {step_id}")
        for index, step in enumerate(internal_graph, start=1):
            if not isinstance(step, dict):
                continue
            step_handler = step.get("handler")
            if step_handler and str(step_handler) not in handler_registry:
                errors.append(f"unregistered internal_graph step handler at {index}: {step_handler}")
    safety = module.get("safety", {})
    if safety and not isinstance(safety, dict):
        errors.append("safety must be an object")
    elif isinstance(safety, dict):
        for key in ("live_requires_validation", "dry_run_supported", "requires_human_approval"):
            if key in safety and not isinstance(safety[key], bool):
                errors.append(f"safety.{key} must be boolean")
    registered_tools: set[str] = set()
    try:
        registered_tools = set(controller._deps.agent_context.tools.list_tools())
    except Exception:
        registered_tools = set()
    tools = module.get("tools", [])
    if tools and not isinstance(tools, list):
        errors.append("tools must be a list")
    elif isinstance(tools, list):
        for index, tool in enumerate(tools, start=1):
            if not isinstance(tool, str) or not tool.strip():
                errors.append(f"tools[{index}] must be a non-empty string")
                continue
            if registered_tools and tool.strip() not in registered_tools:
                errors.append(f"unregistered tool: {tool.strip()}")
    return errors


def _module_dry_run_sequence(module_id: str, payload: dict[str, Any] | None = None) -> list[dict[str, object]]:
    """Return the configured internal module step order without executing handlers/tools."""
    module_payload = payload or _module_config_payload(module_id)
    normalized = ModuleConfigStore.normalize_payload(dict(module_payload))
    module = normalized.get("module", {}) if isinstance(normalized, dict) else {}
    if not isinstance(module, dict):
        return []
    try:
        module = ModuleConfig.model_validate(module).model_dump(mode="json", exclude_none=True)
    except Exception:
        return []
    internal_graph = module.get("internal_graph", [])
    if not isinstance(internal_graph, list):
        return []
    sequence: list[dict[str, object]] = []
    pre_execution = module.get("pre_execution", []) if isinstance(module, dict) else []
    if isinstance(pre_execution, list):
        for index, step in enumerate(pre_execution, start=1):
            item = step if isinstance(step, dict) else {}
            if item.get("enabled", True) is False:
                continue
            handler = str(item.get("handler") or "").strip()
            sequence.append(
                {
                    "step": len(sequence) + 1,
                    "id": item.get("id", f"pre_step_{index}"),
                    "label": item.get("label", item.get("id", f"pre_step_{index}")),
                    "handler": handler,
                    "kind": item.get("kind", "pre_stage"),
                    "phase": "pre_execution",
                    "handler_configured": bool(handler),
                    "executable": handler.startswith("agent."),
                }
            )
    for index, step in enumerate(internal_graph, start=1):
        item = step if isinstance(step, dict) else {}
        configured_handler = str(item.get("handler") or "").strip()
        display_handler = configured_handler or str(module.get("handler", ""))
        sequence.append(
            {
                "step": len(sequence) + 1,
                "id": item.get("id", f"step_{index}"),
                "label": item.get("label", item.get("id", f"step_{index}")),
                "handler": display_handler,
                "kind": item.get("kind", "internal_step"),
                "phase": "internal_graph",
                "handler_configured": bool(configured_handler),
                "executable": configured_handler.startswith("agent."),
            }
        )
    return sequence


def _module_dry_run_summary(sequence: list[dict[str, object]]) -> dict[str, object]:
    """Summarize draft module dry-run sequence for operator evidence panels."""
    pre = [item for item in sequence if item.get("phase") == "pre_execution"]
    internal = [item for item in sequence if item.get("phase") == "internal_graph"]
    executable = [item for item in sequence if item.get("executable")]
    checkpoints = [item for item in sequence if not item.get("executable")]
    handlers = sorted({str(item.get("handler") or "") for item in sequence if item.get("handler")})
    return {
        "step_count": len(sequence),
        "pre_execution_count": len(pre),
        "internal_graph_count": len(internal),
        "executable_count": len(executable),
        "checkpoint_count": len(checkpoints),
        "handler_count": len(handlers),
        "handlers": handlers,
        "ordered_step_ids": [str(item.get("id") or "") for item in sequence],
        "first_step_id": str(sequence[0].get("id") or "") if sequence else "",
        "last_step_id": str(sequence[-1].get("id") or "") if sequence else "",
    }


def _module_dry_run_evidence(module_id: str, payload: dict[str, Any]) -> dict[str, object]:
    """Build reusable non-device dry-run evidence for module API save/create responses."""
    sequence = _module_dry_run_sequence(module_id, payload)
    return {
        "ok": True,
        "module_id": module_id,
        "sequence": sequence,
        "summary": _module_dry_run_summary(sequence),
    }


def _safe_run_dir(run_id: str) -> Path:
    """Resolve a run directory under run_root without allowing path traversal."""
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in run_id).strip(".-")
    if not safe:
        raise HTTPException(status_code=400, detail="run_id cannot be empty")
    root = controller._deps.run_root.resolve()
    run_dir = (root / safe).resolve()
    try:
        run_dir.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="run_id escapes run root") from exc
    return run_dir


def _safe_run_artifact_path(run_id: str, artifact_path: str) -> Path:
    """Resolve one artifact path under a safe run directory."""
    run_dir = _safe_run_dir(run_id)
    artifact = (run_dir / artifact_path).resolve()
    try:
        artifact.relative_to(run_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="artifact path escapes run directory") from exc
    if not artifact.exists() or not artifact.is_file():
        raise HTTPException(status_code=404, detail="Run artifact not found")
    return artifact


def _artifact_preview_kind(path: Path) -> str:
    """Classify artifact preview behavior for Runtime IDE."""
    suffix = path.suffix.lower()
    if suffix in {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".json", ".md", ".txt", ".csv", ".log", ".yaml", ".yml", ".gcode"}:
        return "text"
    if suffix in {".stl"}:
        return "mesh"
    return "download"


def _current_run_id() -> str:
    """Return current controller run id."""
    snapshot = controller.snapshot()
    state = snapshot.get("state", {}) if isinstance(snapshot.get("state"), dict) else {}
    return str(state.get("run_id") or "")


def _artifact_items_for_run(run_id: str) -> tuple[Path, list[dict[str, object]]]:
    """Return run artifacts with both native and package-compatibility ids."""
    run_dir = _safe_run_dir(run_id)
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"Unknown run_id={run_id}")
    artifacts: list[dict[str, object]] = []
    for item in sorted(run_dir.rglob("*")):
        if not item.is_file():
            continue
        rel = item.relative_to(run_dir).as_posix()
        encoded_rel = quote(rel, safe="/")
        artifact_id = f"{run_id}::{quote(rel, safe='')}"
        preview_kind = _artifact_preview_kind(item)
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "run_id": run_id,
                "path": rel,
                "name": item.name,
                "suffix": item.suffix,
                "size_bytes": item.stat().st_size,
                "kind": "artifact",
                "preview_kind": preview_kind,
                "previewable": preview_kind in {"image", "text"},
                "url": f"/api/runs/{run_id}/artifact-file/{encoded_rel}",
                "download_url": f"/api/runs/{run_id}/artifact-file/{encoded_rel}?download=1",
                "compat_url": f"/api/artifacts/{quote(artifact_id, safe='')}",
            }
        )
    return run_dir, artifacts


def _parse_artifact_id(artifact_id: str, run_id: str | None = None) -> tuple[str, str]:
    """Decode a package-compatibility artifact id into run id and artifact path."""
    raw = unquote(str(artifact_id or "").strip())
    if "::" in raw:
        decoded_run_id, encoded_path = raw.split("::", 1)
        return decoded_run_id, unquote(encoded_path)
    if raw.startswith("run-") and ":" in raw:
        decoded_run_id, encoded_path = raw.split(":", 1)
        return decoded_run_id, unquote(encoded_path)
    if raw.startswith("run-") and "/" in raw:
        decoded_run_id, artifact_path = raw.split("/", 1)
        return decoded_run_id, artifact_path
    return run_id or _current_run_id(), raw


def _agent_definition(agent_id: str) -> dict[str, str]:
    """Return one Live GUI agent definition by canonical id or module/stage alias."""
    normalized = str(agent_id or "").strip().lower().replace("-", "_")
    for item in LIVE_AGENT_DEFINITIONS:
        aliases = {item["agent_id"], item["stage"], item["module_id"]}
        if normalized in aliases:
            return item
    raise HTTPException(status_code=404, detail=f"Unknown agent_id={agent_id}")


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Return event payload as a dict."""
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}


def _event_matches_agent(event: dict[str, Any], definition: dict[str, str]) -> bool:
    """Match a runtime event to a Live GUI agent without relying on one backend shape."""
    payload = _event_payload(event)
    tokens = {
        str(event.get("agent") or "").lower(),
        str(event.get("agent_id") or "").lower(),
        str(event.get("node_id") or "").lower(),
        str(event.get("module_id") or "").lower(),
        str(event.get("timestamp_stage") or "").lower(),
        str(payload.get("agent") or "").lower(),
        str(payload.get("agent_id") or "").lower(),
        str(payload.get("node_id") or "").lower(),
        str(payload.get("module_id") or "").lower(),
        str(payload.get("stage") or "").lower(),
    }
    aliases = {definition["agent_id"], definition["stage"], definition["module_id"]}
    if tokens.intersection(aliases):
        return True
    event_type = str(event.get("event_type") or event.get("type") or "").lower()
    message = str(event.get("message") or "").lower()
    return definition["agent_id"] in event_type or definition["agent_id"] in message


def _events_for_agent(agent_id: str, run_id: str | None = None) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Return recent runtime events filtered for one Live GUI agent."""
    definition = _agent_definition(agent_id)
    events = controller.recent_events()
    if run_id:
        events = [event for event in events if str(event.get("run_id") or "") == run_id]
    return definition, [event for event in events if _event_matches_agent(event, definition)]


def _agent_report_payload(agent_id: str, run_id: str | None = None) -> dict[str, object]:
    """Build a lightweight academic-report payload for compatibility consumers."""
    definition, events = _events_for_agent(agent_id, run_id=run_id)
    planning_snapshot = controller.planning_snapshot()
    snapshot = controller.snapshot()
    state = snapshot.get("state", {}) if isinstance(snapshot.get("state"), dict) else {}
    messages = [msg for msg in planning_snapshot.get("messages", []) if isinstance(msg, dict)]
    role_aliases = {definition["agent_id"], definition["stage"], definition["module_id"]}
    agent_messages = [msg for msg in messages if str(msg.get("role") or "").lower() in role_aliases]
    warning_events = [event for event in events if str(event.get("level") or event.get("severity") or "").lower() in {"warning", "error", "critical"}]
    status = "running" if str(state.get("stage") or "") == definition["stage"] and snapshot.get("is_running") else "idle"
    if warning_events:
        status = "warning"
    if events and str(events[-1].get("level") or "").lower() == "error":
        status = "error"
    summary = events[-1].get("message") if events else f"No runtime events recorded for {definition['label']} yet."
    role_specific = dict(LIVE_AGENT_REPORT_PROFILES.get(definition["agent_id"], {
        "title": f"{definition['label']} Runtime Role",
        "summary": f"Runtime evidence and follow-up context for {definition['label']}.",
        "focus_rows": [],
        "checklist": ["Review messages", "Inspect backend trace", "Confirm next action"],
    }))
    metadata = state.get("run_metadata", {}) if isinstance(state.get("run_metadata"), dict) else {}
    agent_payload = metadata.get(f"{definition['stage']}_agent_payload") if isinstance(metadata.get(f"{definition['stage']}_agent_payload"), dict) else {}
    design_report = None
    design_agent_report = None
    report_decisions: list[object] = []
    report_metrics: dict[str, object] = {}
    if definition["agent_id"] == "orchestrator":
        followups = [dict(item) for item in metadata.get("orchestrator_followups", []) if isinstance(item, dict)] if isinstance(metadata.get("orchestrator_followups"), list) else []
        decisions = [dict(item) for item in metadata.get("orchestrator_decision_register", []) if isinstance(item, dict)] if isinstance(metadata.get("orchestrator_decision_register"), list) else []
        handoffs = [dict(item) for item in metadata.get("orchestrator_handoff_packets", []) if isinstance(item, dict)] if isinstance(metadata.get("orchestrator_handoff_packets"), list) else []
        reflections = [dict(item) for item in metadata.get("loop_reflections", []) if isinstance(item, dict)] if isinstance(metadata.get("loop_reflections"), list) else []
        latest_followup = metadata.get("latest_orchestrator_followup") if isinstance(metadata.get("latest_orchestrator_followup"), dict) else (followups[-1] if followups else {})
        latest_handoff = metadata.get("latest_orchestrator_handoff") if isinstance(metadata.get("latest_orchestrator_handoff"), dict) else (handoffs[-1] if handoffs else {})
        parallel_batches = [dict(item) for item in metadata.get("orchestrator_parallel_checks", []) if isinstance(item, dict)] if isinstance(metadata.get("orchestrator_parallel_checks"), list) else []
        latest_parallel_checks = metadata.get("latest_orchestrator_parallel_checks") if isinstance(metadata.get("latest_orchestrator_parallel_checks"), dict) else (parallel_batches[-1] if parallel_batches else {})
        latest_reflection = metadata.get("latest_loop_reflection") if isinstance(metadata.get("latest_loop_reflection"), dict) else (reflections[-1] if reflections else {})
        latest_mission_contract = metadata.get("latest_mission_contract") if isinstance(metadata.get("latest_mission_contract"), dict) else metadata.get("mission_contract") if isinstance(metadata.get("mission_contract"), dict) else {}
        latest_orchestration_plan = metadata.get("latest_orchestration_plan") if isinstance(metadata.get("latest_orchestration_plan"), dict) else {}
        latest_control_plane = metadata.get("latest_orchestrator_control_plane") if isinstance(metadata.get("latest_orchestrator_control_plane"), dict) else {}
        if not latest_mission_contract or not latest_orchestration_plan:
            try:
                report_state = OrchestratorState.model_validate(state)
                latest_mission_contract = latest_mission_contract or build_mission_contract(state=report_state)
                latest_orchestration_plan = latest_orchestration_plan or build_orchestration_plan(state=report_state)
            except Exception:
                pass
        if not latest_control_plane:
            try:
                report_state = OrchestratorState.model_validate(state)
                latest_control_plane = build_orchestrator_control_plane_snapshot(
                    state=report_state,
                    mission_contract=latest_mission_contract,
                    orchestration_plan=latest_orchestration_plan,
                )
            except Exception:
                latest_control_plane = {}
        role_specific.update(
            {
                "title": "Orchestration Supervisor / Follow-up Control",
                "summary": "Mission contract, graph route, context handoff registry, intermediate follow-up opinions, decision register, Guardian/operator coordination, and loop reflection.",
                "orchestrator_control_plane": latest_control_plane,
                "mission_contract": latest_mission_contract or {
                    "run_id": state.get("run_id", ""),
                    "mode": state.get("mode", ""),
                    "stage": state.get("stage", ""),
                    "active_goal": state.get("active_goal", ""),
                    "current_specimen_id": (state.get("current_experiment_spec") or {}).get("specimen_id") if isinstance(state.get("current_experiment_spec"), dict) else "",
                    "loop_count": state.get("loop_count", 0),
                },
                "orchestration_plan": latest_orchestration_plan,
                "route_map": {
                    "active_graph": latest_orchestration_plan.get("graph_id") or metadata.get("active_graph_id", "atr_closed_loop"),
                    "current_stage": latest_orchestration_plan.get("current_stage") or state.get("stage", ""),
                    "route": latest_orchestration_plan.get("route", []),
                    "parallelizable_checks": latest_orchestration_plan.get("parallelizable_checks", []),
                    "serial_physical_actions": latest_orchestration_plan.get("serial_physical_actions", []),
                    "expected_artifacts": latest_orchestration_plan.get("expected_artifacts", []),
                    "latest_handoff_to": latest_handoff.get("to_stage", ""),
                    "latest_handoff_from": latest_handoff.get("from_stage", ""),
                },
                "followup_timeline": followups[-20:],
                "handoff_registry": handoffs[-20:],
                "decision_register": decisions[-30:],
                "parallel_check_batches": parallel_batches[-20:],
                "latest_parallel_checks": latest_parallel_checks,
                "loop_reflections": reflections[-10:],
                "open_questions": [item for item in followups[-20:] if item.get("requires_response")],
                "latest_followup": latest_followup,
                "latest_loop_reflection": latest_reflection,
                "run_health": {
                    "followup_count": len(followups),
                    "decision_count": len(decisions),
                    "handoff_count": len(handoffs),
                    "parallel_check_batch_count": len(parallel_batches),
                    "latest_parallel_check_status": latest_parallel_checks.get("status", "not_run") if latest_parallel_checks else "not_run",
                    "reflection_count": len(reflections),
                    "warning_followup_count": sum(1 for item in followups if item.get("concerns")),
                },
            }
        )
        report_decisions = decisions
        report_metrics = role_specific["run_health"]
    if definition["agent_id"] == "design":
        if isinstance(metadata.get("latest_design_agent_report"), dict):
            design_agent_report = metadata["latest_design_agent_report"]
        elif isinstance(agent_payload.get("design_agent_report"), dict):
            design_agent_report = agent_payload["design_agent_report"]
        if isinstance(metadata.get("design_report"), dict):
            design_report = metadata["design_report"]
        elif isinstance(agent_payload.get("design_report"), dict):
            design_report = agent_payload["design_report"]
        if isinstance(design_report, dict):
            candidate_generation = design_report.get("candidate_generation") if isinstance(design_report.get("candidate_generation"), dict) else {}
            candidate_evaluation = design_report.get("candidate_evaluation") if isinstance(design_report.get("candidate_evaluation"), dict) else {}
            manufacturability = design_report.get("manufacturability") if isinstance(design_report.get("manufacturability"), dict) else {}
            handoff_packet = design_report.get("handoff_to_specimen") if isinstance(design_report.get("handoff_to_specimen"), dict) else {}
            role_specific["summary"] = "Traceable objective, hypothesis, candidate pool, selection rationale, rejected/repair log, and Specimen Agent handoff evidence."
            role_specific["candidate_board"] = {
                "candidate_count": candidate_generation.get("candidate_count"),
                "valid_count": candidate_generation.get("valid_count"),
                "rejected_count": candidate_generation.get("rejected_count"),
                "top_candidates": candidate_generation.get("top_candidates", []),
                "candidate_ledger": candidate_generation.get("candidate_ledger", []),
            }
            role_specific["manufacturability"] = manufacturability
            role_specific["decision_register"] = design_report.get("decision_register", [])
            role_specific["handoff_packet"] = handoff_packet
            role_specific["objective"] = design_report.get("objective", {})
            role_specific["hypothesis"] = design_report.get("hypothesis", {})
            role_specific["prior_context"] = design_report.get("prior_context", {})
            if isinstance(design_agent_report, dict):
                role_specific["design_agent_report"] = design_agent_report
            report_decisions = design_report.get("decision_register", []) if isinstance(design_report.get("decision_register"), list) else []
            report_metrics = candidate_evaluation
    specimen_fabrication_report = None
    specimen_agent_report = None
    if definition["agent_id"] == "specimen":
        specimen_result = metadata.get("specimen_result") if isinstance(metadata.get("specimen_result"), dict) else {}
        if not specimen_result and isinstance(agent_payload.get("specimen_result"), dict):
            specimen_result = agent_payload["specimen_result"]
        if isinstance(metadata.get("latest_specimen_agent_report"), dict):
            specimen_agent_report = metadata["latest_specimen_agent_report"]
        elif isinstance(agent_payload.get("specimen_agent_report"), dict):
            specimen_agent_report = agent_payload["specimen_agent_report"]
        elif isinstance(specimen_result.get("specimen_agent_report"), dict):
            specimen_agent_report = specimen_result["specimen_agent_report"]
        if isinstance(metadata.get("fabrication_report"), dict):
            specimen_fabrication_report = metadata["fabrication_report"]
        elif isinstance(specimen_result.get("fabrication_report"), dict):
            specimen_fabrication_report = specimen_result["fabrication_report"]
        elif isinstance(agent_payload.get("fabrication_report"), dict):
            specimen_fabrication_report = agent_payload["fabrication_report"]
        specimen_packet = metadata.get("specimen_fabricated") if isinstance(metadata.get("specimen_fabricated"), dict) else {}
        if not specimen_packet and isinstance(agent_payload.get("specimen_fabricated"), dict):
            specimen_packet = agent_payload["specimen_fabricated"]
        if isinstance(specimen_fabrication_report, dict):
            role_specific["summary"] = "Manufacturing digital thread, process plan, quality gates, printer runtime evidence, monitoring handoff, and feedback to Design/Knowledge/BO."
            role_specific["fabrication_intent"] = specimen_fabrication_report.get("fabrication_intent", {})
            role_specific["digital_thread"] = specimen_fabrication_report.get("digital_thread", {})
            role_specific["process_plan"] = specimen_fabrication_report.get("process_plan", {})
            role_specific["quality_gates"] = specimen_fabrication_report.get("quality_gates", [])
            role_specific["monitoring_plan"] = specimen_fabrication_report.get("monitoring_plan", {})
            role_specific["printer_runtime"] = specimen_fabrication_report.get("printer_runtime", {})
            role_specific["fabrication_outcome"] = specimen_fabrication_report.get("fabrication_outcome", {})
            role_specific["feedback_to_design"] = specimen_fabrication_report.get("feedback_to_design", {})
            role_specific["handoff_packet"] = specimen_packet
            if isinstance(specimen_agent_report, dict):
                role_specific["specimen_agent_report"] = specimen_agent_report
            report_decisions = specimen_packet.get("decisions", []) if isinstance(specimen_packet.get("decisions"), list) else agent_payload.get("decisions", []) if isinstance(agent_payload.get("decisions"), list) else []
            report_metrics = metadata.get("specimen_metrics") if isinstance(metadata.get("specimen_metrics"), dict) else agent_payload.get("metrics", {}) if isinstance(agent_payload.get("metrics"), dict) else {}
    vision_report = None
    vision_agent_report = None
    knowledge_report = None
    manipulation_report = None
    manipulation_agent_report = None
    robot_task_result = None
    if definition["agent_id"] == "vision":
        latest_observation = state.get("latest_observations") if isinstance(state.get("latest_observations"), dict) else {}
        if not latest_observation and isinstance(metadata.get("latest_vision_observation"), dict):
            latest_observation = metadata["latest_vision_observation"]
        if isinstance(metadata.get("latest_vision_agent_report"), dict):
            vision_agent_report = metadata["latest_vision_agent_report"]
        elif isinstance(latest_observation.get("vision_agent_report"), dict):
            vision_agent_report = latest_observation["vision_agent_report"]
        elif isinstance(agent_payload.get("vision_agent_report"), dict):
            vision_agent_report = agent_payload["vision_agent_report"]
        if isinstance(metadata.get("vision_report"), dict):
            vision_report = metadata["vision_report"]
        elif isinstance(latest_observation.get("vision_report"), dict):
            vision_report = latest_observation["vision_report"]
        elif isinstance(agent_payload.get("vision_report"), dict):
            vision_report = agent_payload["vision_report"]
        vision_packet = metadata.get("vision_signal") if isinstance(metadata.get("vision_signal"), dict) else {}
        if not vision_packet and isinstance(latest_observation.get("vision_signal"), dict):
            vision_packet = latest_observation["vision_signal"]
        if not vision_packet and isinstance(agent_payload.get("vision_signal"), dict):
            vision_packet = agent_payload["vision_signal"]
        if isinstance(vision_report, dict):
            role_specific["summary"] = "Lab perception signal board with zone states, freshness-bounded signals, visual evidence artifacts, and Knowledge/Guardian handoff context."
            role_specific["scene_map"] = vision_report.get("scene_map", vision_report.get("zones", {}))
            role_specific["signal_board"] = vision_report.get("signal_board", vision_report.get("agent_signals", []))
            role_specific["evidence_timeline"] = vision_report.get("events", [])
            role_specific["dataset_ledger"] = vision_report.get("dataset_ledger", {})
            role_specific["model_backend"] = vision_report.get("model_backend", {})
            role_specific["camera_source"] = vision_report.get("camera_source", {})
            role_specific["safety_anomaly"] = vision_report.get("safety_anomaly", {})
            role_specific["knowledge_payload"] = vision_report.get("knowledge_payload", {})
            role_specific["handoff_packet"] = vision_packet
            if isinstance(vision_agent_report, dict):
                role_specific["vision_agent_report"] = vision_agent_report
            report_decisions = vision_packet.get("decisions", []) if isinstance(vision_packet.get("decisions"), list) else agent_payload.get("decisions", []) if isinstance(agent_payload.get("decisions"), list) else []
            report_metrics = metadata.get("vision_metrics") if isinstance(metadata.get("vision_metrics"), dict) else agent_payload.get("metrics", {}) if isinstance(agent_payload.get("metrics"), dict) else {}
    if definition["agent_id"] == "equipment":
        equipment_report = metadata.get("equipment_report") if isinstance(metadata.get("equipment_report"), dict) else {}
        if not equipment_report and isinstance(agent_payload.get("equipment_report"), dict):
            equipment_report = agent_payload["equipment_report"]
        equipment_result = metadata.get("equipment_result") if isinstance(metadata.get("equipment_result"), dict) else agent_payload.get("equipment_result", {}) if isinstance(agent_payload.get("equipment_result"), dict) else {}
        utm_packet = metadata.get("utm_data_ready") if isinstance(metadata.get("utm_data_ready"), dict) else agent_payload.get("utm_data_ready", {}) if isinstance(agent_payload.get("utm_data_ready"), dict) else {}
        equipment_handoff = metadata.get("equipment_handoff") if isinstance(metadata.get("equipment_handoff"), dict) else agent_payload.get("equipment_handoff", {}) if isinstance(agent_payload.get("equipment_handoff"), dict) else {}
        if isinstance(equipment_report, dict) and equipment_report:
            role_specific["summary"] = "Windows bridge control trace, UTM screen assertions, Vision physical cross-checks, exported data ledger, and Analysis handoff gate evidence."
            bridge = equipment_report.get("bridge", {}) if isinstance(equipment_report.get("bridge"), dict) else {}
            control_plan = equipment_report.get("control_plan", {}) if isinstance(equipment_report.get("control_plan"), dict) else {}
            vision_cross_checks = equipment_report.get("vision_cross_checks", {}) if isinstance(equipment_report.get("vision_cross_checks"), dict) else {}
            screen_checks = equipment_report.get("screen_checks", []) if isinstance(equipment_report.get("screen_checks"), list) else []
            physical_checks = equipment_report.get("physical_checks", {}) if isinstance(equipment_report.get("physical_checks"), dict) else {}
            data_acquisition = equipment_report.get("data_acquisition", {}) if isinstance(equipment_report.get("data_acquisition"), dict) else {}
            cross_checks = equipment_report.get("cross_checks", {}) if isinstance(equipment_report.get("cross_checks"), dict) else {}
            decision = equipment_report.get("decision", {}) if isinstance(equipment_report.get("decision"), dict) else {}
            artifact_records = equipment_report.get("artifact_records", []) if isinstance(equipment_report.get("artifact_records"), list) else []
            artifact_refs = equipment_report.get("artifact_refs", []) if isinstance(equipment_report.get("artifact_refs"), list) else []
            screen_evidence_refs = equipment_report.get("screen_evidence_refs", []) if isinstance(equipment_report.get("screen_evidence_refs"), list) else []
            data_evidence_refs = equipment_report.get("data_evidence_refs", []) if isinstance(equipment_report.get("data_evidence_refs"), list) else []
            failure_retry_table = equipment_report.get("failure_retry_table", []) if isinstance(equipment_report.get("failure_retry_table"), list) else []
            recovery = equipment_report.get("recovery", {}) if isinstance(equipment_report.get("recovery"), dict) else {}
            live_evidence_audit = equipment_report.get("live_evidence_audit", {}) if isinstance(equipment_report.get("live_evidence_audit"), dict) else {}
            save_export_audit = live_evidence_audit.get("save_export", {}) if isinstance(live_evidence_audit.get("save_export"), dict) else {}
            hardware_alert = equipment_report.get("hardware_alert") if isinstance(equipment_report.get("hardware_alert"), dict) else metadata.get("hardware_alert") if isinstance(metadata.get("hardware_alert"), dict) else agent_payload.get("hardware_alert") if isinstance(agent_payload.get("hardware_alert"), dict) else {}
            hardware_alerts = metadata.get("hardware_alerts") if isinstance(metadata.get("hardware_alerts"), list) else agent_payload.get("hardware_alerts") if isinstance(agent_payload.get("hardware_alerts"), list) else []
            hardware_alerts = [dict(item) for item in hardware_alerts if isinstance(item, dict)]
            if hardware_alert and not any(item.get("alert_id") == hardware_alert.get("alert_id") for item in hardware_alerts):
                hardware_alerts.insert(0, hardware_alert)
            incident_records = metadata.get("incident_records") if isinstance(metadata.get("incident_records"), list) else agent_payload.get("incident_records") if isinstance(agent_payload.get("incident_records"), list) else []
            incident_records = [dict(item) for item in incident_records if isinstance(item, dict)]
            report_incidents = equipment_report.get("incident_records") if isinstance(equipment_report.get("incident_records"), list) else []
            for incident in report_incidents:
                if isinstance(incident, dict):
                    incident_records.append(dict(incident))
            hardware_incident = hardware_alert.get("incident_record") if isinstance(hardware_alert.get("incident_record"), dict) else {}
            if hardware_incident:
                incident_records.append(dict(hardware_incident))
            seen_incident_ids: set[str] = set()
            unique_incidents: list[dict[str, Any]] = []
            for incident in incident_records:
                incident_id = str(incident.get("incident_id") or incident.get("id") or json.dumps(incident, sort_keys=True, default=str))
                if incident_id in seen_incident_ids:
                    continue
                seen_incident_ids.add(incident_id)
                unique_incidents.append(incident)
            incident_records = unique_incidents
            guardian_decision = hardware_alert.get("guardian_decision") if isinstance(hardware_alert.get("guardian_decision"), dict) else {}
            guardian_contract = hardware_alert.get("guardian_contract") if isinstance(hardware_alert.get("guardian_contract"), dict) else {}
            screen_passed = sum(1 for item in screen_checks if isinstance(item, dict) and item.get("ok"))
            role_specific["bridge"] = bridge
            role_specific["preconditions"] = equipment_report.get("preconditions", {})
            role_specific["control_plan"] = control_plan
            role_specific["vision_requests"] = equipment_report.get("vision_requests", [])
            role_specific["vision_cross_checks"] = vision_cross_checks
            role_specific["screen_checks"] = screen_checks
            role_specific["physical_checks"] = physical_checks
            role_specific["data_acquisition"] = data_acquisition
            role_specific["cross_checks"] = cross_checks
            role_specific["decision"] = decision
            role_specific["control_trace"] = {
                "bridge_provider": bridge.get("provider", ""),
                "connection_status": bridge.get("connection_status", ""),
                "program_id": control_plan.get("program_id", equipment_result.get("program_id", "")),
                "macro_version": control_plan.get("macro_version", ""),
                "locator_backend": control_plan.get("locator_backend", ""),
                "tool_result_count": len(agent_payload.get("tool_results", [])) if isinstance(agent_payload.get("tool_results"), list) else 0,
            }
            role_specific["visual_assertion"] = {
                "screen_checks_passed": screen_passed,
                "screen_checks_total": len(screen_checks),
                "screen_started": bool(cross_checks.get("screen_started")),
                "checkpoints": [item.get("checkpoint") for item in screen_checks if isinstance(item, dict)],
            }
            role_specific["physical_verification"] = {
                "all_required_ok": bool(vision_cross_checks.get("all_required_ok")),
                "vision_motion_confirmed": bool(physical_checks.get("vision_motion_confirmed")),
                "specimen_alignment_ok": bool(physical_checks.get("specimen_alignment_ok")),
                "fixture_safe_to_access": bool(physical_checks.get("fixture_safe_to_access")),
                "evidence_frame_ids": physical_checks.get("evidence_frame_ids", []),
            }
            role_specific["data_ledger"] = {
                "status": data_acquisition.get("status", ""),
                "save_method": data_acquisition.get("save_method", ""),
                "save_attempted_by_agent": data_acquisition.get("save_attempted_by_agent", save_export_audit.get("save_attempted_by_agent", "")),
                "save_confirmation_screen_ok": data_acquisition.get("save_confirmation_screen_ok", save_export_audit.get("save_confirmation_screen_ok", "")),
                "save_export_responsibility_ok": bool(cross_checks.get("save_export_responsibility_ok", save_export_audit.get("ok", False))),
                "recognized_save_method": save_export_audit.get("recognized_save_method", ""),
                "windows_path": data_acquisition.get("windows_path") or save_export_audit.get("windows_path", ""),
                "linux_path": data_acquisition.get("linux_path") or save_export_audit.get("linux_path") or equipment_result.get("result_file") or equipment_result.get("utm_csv_path") or "",
                "sha256": data_acquisition.get("sha256", ""),
                "size_bytes": data_acquisition.get("size_bytes", 0),
                "row_count_probe": data_acquisition.get("row_count_probe", 0),
                "columns_probe": data_acquisition.get("columns_probe", []),
                "parse_ready": bool(cross_checks.get("data_parse_probe_ok")),
            }
            role_specific["artifact_ledger"] = {
                "artifact_records": artifact_records,
                "artifact_refs": artifact_refs,
                "screen_evidence_refs": screen_evidence_refs,
                "data_evidence_refs": data_evidence_refs,
                "screen_evidence_count": len(screen_evidence_refs),
                "data_evidence_count": len(data_evidence_refs),
            }
            role_specific["failure_recovery"] = {
                "recovery": recovery,
                "failure_retry_table": failure_retry_table,
                "operator_intervention_required": bool(recovery.get("operator_intervention_required")),
                "retry_count": recovery.get("retry_count", 0),
                "fallback_macros": recovery.get("fallback_macros", []),
            }
            blocked_commands = list(decision.get("blocking_reasons", [])) if isinstance(decision.get("blocking_reasons"), list) else []
            role_specific["safety_gate"] = {
                "guardian_status": (utm_packet or {}).get("guardian_status", "") or ("block" if hardware_alerts or decision.get("failure_code") else "allow" if (decision.get("handoff_status") or equipment_handoff.get("status")) == "ready_for_analysis" else "not_checked"),
                "hardware_alert_count": len(hardware_alerts),
                "active_hardware_alert": hardware_alert,
                "incident_records": incident_records,
                "incident_count": len(incident_records),
                "requires_human_approval": bool(hardware_alert.get("requires_ack") or guardian_decision.get("requires_human_approval") or guardian_contract.get("requires_human_approval")),
                "blocks_workflow": bool(hardware_alert.get("blocks_workflow") or guardian_contract.get("ok_for_next_stage") is False or (decision.get("handoff_status") or equipment_handoff.get("status")) == "blocked"),
                "guardian_route_hint": hardware_alert.get("guardian_route_hint", guardian_decision.get("recommended_action", "")),
                "guardian_decision": guardian_decision.get("decision", ""),
                "risk_score": hardware_alert.get("risk_score", guardian_decision.get("risk_score", "")),
                "risk_flags": guardian_contract.get("risk_flags", hardware_alert.get("risk_flags", [])),
                "blocked_commands": blocked_commands,
                "emergency_stop_evidence": {
                    "safe_stop_recommended": guardian_decision.get("decision") == "safe_stop" or hardware_alert.get("guardian_route_hint") == "stop",
                    "route_hint": hardware_alert.get("guardian_route_hint", ""),
                    "corrective_action": (hardware_alert.get("incident_record") or {}).get("corrective_action", "") if isinstance(hardware_alert.get("incident_record"), dict) else "",
                },
            }
            role_specific["live_evidence_audit"] = live_evidence_audit
            role_specific["handoff_gate"] = {
                "handoff_status": decision.get("handoff_status") or equipment_handoff.get("status"),
                "equipment_status": decision.get("equipment_status") or equipment_result.get("status"),
                "failure_code": decision.get("failure_code") or equipment_result.get("failure_code"),
                "guardian_status": (utm_packet or {}).get("guardian_status", ""),
                "required_gates": cross_checks,
                "save_export_responsibility_ok": bool(cross_checks.get("save_export_responsibility_ok", save_export_audit.get("ok", False))),
                "live_evidence_audit": live_evidence_audit,
            }
            role_specific["handoff_packet"] = utm_packet or equipment_handoff
            role_specific["equipment_result"] = {
                "status": equipment_result.get("status", ""),
                "program_id": equipment_result.get("program_id", ""),
                "failure_code": equipment_result.get("failure_code"),
                "result_file": equipment_result.get("result_file") or equipment_result.get("utm_csv_path"),
            }
            report_decisions = [equipment_report.get("decision", {})] if isinstance(equipment_report.get("decision"), dict) else agent_payload.get("decisions", []) if isinstance(agent_payload.get("decisions"), list) else []
            report_metrics = metadata.get("equipment_metrics") if isinstance(metadata.get("equipment_metrics"), dict) else agent_payload.get("metrics", {}) if isinstance(agent_payload.get("metrics"), dict) else {}
    if definition["agent_id"] == "manipulation":
        if isinstance(metadata.get("latest_manipulation_agent_report"), dict):
            manipulation_agent_report = metadata["latest_manipulation_agent_report"]
        elif isinstance(agent_payload.get("manipulation_agent_report"), dict):
            manipulation_agent_report = agent_payload["manipulation_agent_report"]
        if isinstance(metadata.get("manipulation_report"), dict):
            manipulation_report = metadata["manipulation_report"]
        elif isinstance(agent_payload.get("manipulation_report"), dict):
            manipulation_report = agent_payload["manipulation_report"]
        if isinstance(metadata.get("robot_task_result"), dict):
            robot_task_result = metadata["robot_task_result"]
        elif isinstance(agent_payload.get("robot_task_result"), dict):
            robot_task_result = agent_payload["robot_task_result"]
        if isinstance(manipulation_report, dict):
            task = manipulation_report.get("task") if isinstance(manipulation_report.get("task"), dict) else {}
            role_specific["summary"] = "Bounded Pi0.5/LeRobot skill execution, preflight readiness, SARM-lite progress/risk state, Vision dependency, and robot_task_result handoff evidence."
            role_specific["task"] = task
            role_specific["skill_episode_board"] = {
                "task_id": task.get("task_id", ""),
                "skill_id": robot_task_result.get("skill_id", "") if isinstance(robot_task_result, dict) else "",
                "episode_id": robot_task_result.get("episode_id", "") if isinstance(robot_task_result, dict) else manipulation_report.get("session_id", ""),
                "terminal_pose": robot_task_result.get("terminal_pose", "") if isinstance(robot_task_result, dict) else "",
                "handoff_status": robot_task_result.get("handoff_status", "") if isinstance(robot_task_result, dict) else "",
                "completion_status": robot_task_result.get("completion_status", "") if isinstance(robot_task_result, dict) else "",
            }
            role_specific["policy_plan"] = manipulation_report.get("policy_plan", {})
            role_specific["preflight"] = manipulation_report.get("preflight", {})
            role_specific["vision_context"] = manipulation_report.get("vision_context", {})
            role_specific["rollout_runtime"] = manipulation_report.get("rollout_runtime", {})
            role_specific["stage_machine"] = manipulation_report.get("stage_machine", {})
            role_specific["sarm"] = manipulation_report.get("sarm", {})
            role_specific["decision"] = manipulation_report.get("decision", {})
            role_specific["knowledge_payload"] = manipulation_report.get("knowledge_payload", {})
            role_specific["handoff_packet"] = robot_task_result if isinstance(robot_task_result, dict) else manipulation_report.get("handoff_packet", {})
            if isinstance(manipulation_agent_report, dict):
                role_specific["manipulation_agent_report"] = manipulation_agent_report
            report_decisions = robot_task_result.get("decisions", []) if isinstance(robot_task_result, dict) and isinstance(robot_task_result.get("decisions"), list) else agent_payload.get("decisions", []) if isinstance(agent_payload.get("decisions"), list) else []
            report_metrics = metadata.get("manipulation_metrics") if isinstance(metadata.get("manipulation_metrics"), dict) else agent_payload.get("metrics", {}) if isinstance(agent_payload.get("metrics"), dict) else {}
    if definition["agent_id"] == "knowledge":
        knowledge_payload = metadata.get("knowledge") if isinstance(metadata.get("knowledge"), dict) else {}
        knowledge_report = knowledge_payload.get("knowledge_report") if isinstance(knowledge_payload.get("knowledge_report"), dict) else {}
        knowledge_context = knowledge_payload.get("knowledge_context") if isinstance(knowledge_payload.get("knowledge_context"), dict) else {}
        evolution_proposal = knowledge_payload.get("evolution_proposal") if isinstance(knowledge_payload.get("evolution_proposal"), dict) else {}
        if knowledge_report:
            memory_intake = knowledge_report.get("memory_intake") if isinstance(knowledge_report.get("memory_intake"), dict) else {}
            self_evolution = knowledge_report.get("self_evolution") if isinstance(knowledge_report.get("self_evolution"), dict) else evolution_proposal
            packs = self_evolution.get("evidence_packs") if isinstance(self_evolution.get("evidence_packs"), list) else []
            performance = knowledge_report.get("agent_performance_records") if isinstance(knowledge_report.get("agent_performance_records"), list) else []
            role_specific["summary"] = "Research memory board with provenance, failure/success pattern memory, agent performance ledger, and self-evolution evidence packs."
            role_specific["memory_ledger"] = {
                "experiment_record_id": memory_intake.get("experiment_record_id", ""),
                "agent_performance_count": memory_intake.get("agent_performance_count", 0),
                "failure_pattern_count": memory_intake.get("failure_pattern_count", 0),
                "success_pattern_count": memory_intake.get("success_pattern_count", 0),
                "evolution_pack_count": memory_intake.get("evolution_pack_count", len(packs)),
                "artifact_paths": knowledge_payload.get("artifact_paths", {}),
            }
            role_specific["retrieval_panel"] = {
                "coverage": knowledge_payload.get("retrieval_coverage", 0.0),
                "local_chunks": knowledge_payload.get("local_chunks", 0),
                "web_results": knowledge_payload.get("web_results", 0),
                "sources": (knowledge_report.get("data_quality_map") or {}).get("retrieval_sources", {}) if isinstance(knowledge_report.get("data_quality_map"), dict) else {},
            }
            role_specific["failure_success_library"] = {
                "failure_patterns": knowledge_report.get("failure_patterns", []),
                "success_patterns": knowledge_report.get("success_patterns", []),
            }
            role_specific["self_evolution_board"] = {
                "status": self_evolution.get("status", ""),
                "top_packs": packs[:5],
                "prefill_tasks": self_evolution.get("prefill_tasks", []),
                "outcomes": self_evolution.get("outcomes", knowledge_report.get("evolution_outcomes", [])),
                "no_evolution_needed_reason": self_evolution.get("no_evolution_needed_reason", ""),
            }
            role_specific["data_quality_map"] = knowledge_report.get("data_quality_map", {})
            role_specific["graph_backend_status"] = knowledge_report.get("graph_backend_status", knowledge_context.get("graph_backend_status", {}))
            role_specific["agent_performance_memory"] = performance
            role_specific["handoff_packet"] = {
                "knowledge_context": knowledge_context,
                "evolution_proposal": evolution_proposal,
            }
            report_decisions = [
                {
                    "decision": "prepare_self_evolution_evidence_pack",
                    "target_type": pack.get("target_type", ""),
                    "target_id": pack.get("target_id", ""),
                    "priority": pack.get("priority", 0.0),
                    "rationale": "; ".join(pack.get("why_this_target", [])[:2]) if isinstance(pack, dict) else "",
                }
                for pack in packs[:8]
                if isinstance(pack, dict)
            ] or [{"decision": "no_evolution_needed", "rationale": self_evolution.get("no_evolution_needed_reason", "No evidence pack generated.")}]
            report_metrics = knowledge_report.get("evidence_quality", {}) if isinstance(knowledge_report.get("evidence_quality"), dict) else knowledge_context.get("evidence_quality", {}) if isinstance(knowledge_context.get("evidence_quality"), dict) else {}
    if definition["agent_id"] == "bo":
        bo_result = metadata.get("bo_agent") if isinstance(metadata.get("bo_agent"), dict) else {}
        if not bo_result and isinstance(agent_payload.get("bo_result"), dict):
            bo_result = agent_payload["bo_result"]
        if isinstance(bo_result, dict) and bo_result:
            reasoning = bo_result.get("reasoning") if isinstance(bo_result.get("reasoning"), dict) else {}
            recommendation = bo_result.get("recommendation") if isinstance(bo_result.get("recommendation"), dict) else {}
            candidate_ranking = bo_result.get("candidate_ranking") if isinstance(bo_result.get("candidate_ranking"), list) else bo_result.get("candidate_pool", []) if isinstance(bo_result.get("candidate_pool"), list) else []
            next_design_request = bo_result.get("next_design_request") if isinstance(bo_result.get("next_design_request"), dict) else metadata.get("next_design_request") if isinstance(metadata.get("next_design_request"), dict) else {}
            benchmark = bo_result.get("benchmark") if isinstance(bo_result.get("benchmark"), dict) else {}
            strategies = benchmark.get("strategies") if isinstance(benchmark.get("strategies"), dict) else {}
            benchmark_strategy = bo_result.get("benchmark_strategy") or bo_result.get("strategy") or "bo"
            strategy_payload = strategies.get(benchmark_strategy) if isinstance(strategies.get(benchmark_strategy), dict) else strategies.get("bo") if isinstance(strategies.get("bo"), dict) else {}
            surrogate_trace = strategy_payload.get("surrogate_trace") if isinstance(strategy_payload.get("surrogate_trace"), list) else []
            latest_trace = surrogate_trace[-1] if surrogate_trace and isinstance(surrogate_trace[-1], dict) else {}
            latest_selected = latest_trace.get("selected") if isinstance(latest_trace.get("selected"), dict) else {}
            role_specific["summary"] = "Reasoning-augmented BO cockpit: measured evidence, Knowledge/failure priors, surrogate/acquisition scoring, LLM preference audit, and Design handoff."
            role_specific["surrogate_panel"] = {
                "strategy": bo_result.get("strategy", ""),
                "benchmark_strategy": benchmark_strategy,
                "acquisition": bo_result.get("acquisition", ""),
                "budget": bo_result.get("budget", ""),
                "trace_step_count": len(surrogate_trace),
                "latest_selected": latest_selected,
                "prior_summary": bo_result.get("prior_summary", {}),
            }
            role_specific["candidate_ranking"] = candidate_ranking[:10]
            role_specific["reasoning_audit"] = {
                "schema_version": reasoning.get("schema_version", ""),
                "source": reasoning.get("source", ""),
                "operator_summary": reasoning.get("operator_summary", ""),
                "strategy_recommendation": reasoning.get("strategy_recommendation", {}),
                "hypotheses": reasoning.get("hypotheses", []),
                "preference_regions": reasoning.get("preference_regions", []),
                "risk_flags": reasoning.get("risk_flags", []),
            }
            role_specific["decision_register"] = [
                {
                    "decision": "select_next_design_candidate",
                    "candidate_id": recommendation.get("candidate_id", ""),
                    "source_strategy": recommendation.get("source_strategy", ""),
                    "combined_score": recommendation.get("combined_score", ""),
                    "rationale": recommendation.get("why_this_candidate") or recommendation.get("reason", ""),
                }
            ]
            role_specific["recommendation"] = recommendation
            role_specific["handoff_packet"] = next_design_request
            role_specific["failure_model"] = bo_result.get("failure_model", {})
            role_specific["artifacts"] = bo_result.get("artifacts", {})
            report_decisions = role_specific["decision_register"]
            report_metrics = {
                "prior_summary": bo_result.get("prior_summary", {}),
                "best_so_far_count": len(bo_result.get("best_so_far", [])) if isinstance(bo_result.get("best_so_far"), list) else 0,
                "candidate_count": len(bo_result.get("candidate_pool", [])) if isinstance(bo_result.get("candidate_pool"), list) else len(candidate_ranking),
                "recommended_score": recommendation.get("objective_score"),
            }
    process_steps = [
        {
            "timestamp": event.get("ts") or event.get("timestamp") or "",
            "event_type": event.get("event_type") or event.get("type") or "runtime.event",
            "message": event.get("message") or "",
            "node_id": event.get("node_id") or _event_payload(event).get("node_id") or "",
            "trace_id": event.get("trace_id") or _event_payload(event).get("trace_id") or "",
        }
        for event in events[-20:]
    ]
    tool_calls = [
        {
            "timestamp": event.get("ts") or event.get("timestamp") or "",
            "event_type": event.get("event_type") or event.get("type") or "tool",
            "message": event.get("message") or "",
            "payload": _event_payload(event),
        }
        for event in events[-50:]
        if "tool" in str(event.get("event_type") or event.get("type") or "").lower()
        or bool(_event_payload(event).get("tool_calls"))
        or bool(_event_payload(event).get("tool_call"))
    ]
    artifacts = []
    for event in events[-50:]:
        payload = _event_payload(event)
        artifact_ids = event.get("artifact_ids") or payload.get("artifact_ids") or payload.get("artifacts") or []
        if isinstance(artifact_ids, (str, bytes)):
            artifact_ids = [artifact_ids]
        if isinstance(artifact_ids, list):
            for artifact_id in artifact_ids:
                artifacts.append({
                    "artifact_id": str(artifact_id),
                    "event_id": str(event.get("event_id") or event.get("id") or ""),
                    "event_type": str(event.get("event_type") or event.get("type") or ""),
                })
    next_action = "Inspect backend trace, answer pending questions, or continue the active run." if events else "Wait for runtime activity."
    return {
        "agent_id": definition["agent_id"],
        "label": definition["label"],
        "run_id": run_id or _current_run_id(),
        "status": status,
        "summary": summary,
        "role_specific": role_specific,
        "inputs": agent_messages[-12:],
        "decisions": report_decisions,
        "metrics": report_metrics,
        "process_steps": process_steps,
        "tool_calls": tool_calls,
        "artifacts": artifacts,
        "warnings": warning_events[-12:],
        "handoff": {
            "current_stage": str(state.get("stage") or ""),
            "agent_stage": definition["stage"],
            "next_action": next_action,
        },
        "next_action": next_action,
        "sections": {
            "overview": summary,
            "role_specific": role_specific,
            "design_agent_report": design_agent_report if definition["agent_id"] == "design" else None,
            "design_report": design_report if definition["agent_id"] == "design" else None,
            "specimen_agent_report": specimen_agent_report if definition["agent_id"] == "specimen" else None,
            "fabrication_report": specimen_fabrication_report if definition["agent_id"] == "specimen" else None,
            "vision_agent_report": vision_agent_report if definition["agent_id"] == "vision" else None,
            "vision_report": vision_report if definition["agent_id"] == "vision" else None,
            "manipulation_report": manipulation_report if definition["agent_id"] == "manipulation" else None,
            "manipulation_agent_report": manipulation_agent_report if definition["agent_id"] == "manipulation" else None,
            "robot_task_result": robot_task_result if definition["agent_id"] == "manipulation" else None,
            "knowledge_report": knowledge_report if definition["agent_id"] == "knowledge" else None,
            "bo_result": metadata.get("bo_agent") if definition["agent_id"] == "bo" else None,
            "metrics": report_metrics,
            "messages": agent_messages[-12:],
            "events": events[-50:],
            "process_steps": process_steps,
            "tool_calls": tool_calls,
            "artifacts": artifacts,
            "warnings": warning_events[-12:],
            "handoff": {
                "current_stage": str(state.get("stage") or ""),
                "agent_stage": definition["stage"],
                "next_action": next_action,
            },
            "next_action": next_action,
        },
        "backend_refs": {
            "trace_id": str(events[-1].get("trace_id") or _event_payload(events[-1]).get("trace_id") or "") if events else "",
            "node_id": str(events[-1].get("node_id") or "") if events else definition["stage"],
            "graph_version": str(events[-1].get("graph_version") or "") if events else "",
        },
    }


def _device_state_payload() -> dict[str, object]:
    """Build package-compatible device state from controller health and resources."""
    snapshot = controller.snapshot()
    state = snapshot.get("state", {}) if isinstance(snapshot.get("state"), dict) else {}
    health = state.get("device_health", {}) if isinstance(state.get("device_health"), dict) else {}
    resources = _system_resource_snapshot()
    devices: list[dict[str, object]] = []
    for device_id, bridge_state in sorted(health.items()):
        status = str(bridge_state or "unknown")
        devices.append({
            "device_id": str(device_id),
            "name": str(device_id).replace("_", " ").title(),
            "bridge_state": status,
            "last_command": "runtime snapshot",
            "last_heartbeat": datetime.now(timezone.utc).isoformat(),
            "safe_state": "unsafe/review" if status.lower() in {"error", "failed", "unsafe"} else "safe/ready",
            "status": status,
        })
    devices.append({
        "device_id": "gpu",
        "name": "GPU / vLLM",
        "bridge_state": resources.get("gpu", {}).get("status", "unknown") if isinstance(resources.get("gpu"), dict) else "unknown",
        "last_command": "resource telemetry",
        "last_heartbeat": resources.get("updated_at", ""),
        "safe_state": "resource monitor",
        "status": resources.get("gpu", {}).get("status", "unknown") if isinstance(resources.get("gpu"), dict) else "unknown",
        "payload": resources.get("gpu", {}),
    })
    try:
        runtime_contract = _runtime_ide_contract_payload(snapshot)
        bridge_contracts = runtime_contract.get("device_bridges", []) if isinstance(runtime_contract, dict) else []
    except Exception:
        bridge_contracts = []
    return {
        "ok": True,
        "run_id": _current_run_id(),
        "devices": devices,
        "bridge_contracts": bridge_contracts,
        "system_resources": resources,
    }


def _require_current_run(run_id: str) -> None:
    """Ensure a mutating run command targets the active run."""
    current = _current_run_id()
    if run_id != current:
        raise HTTPException(status_code=404, detail=f"Unknown active run_id={run_id}")


def _approval_id_from_event(event: dict[str, Any]) -> str:
    """Return the stable approval id associated with one approval event."""
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return str(payload.get("approval_id") or payload.get("id") or event.get("event_id") or "")


async def _attach_guardian_incident_note(incident_id: str, req: GuardianIncidentNoteRequest, *, run_id: str | None = None) -> dict[str, object]:
    """Attach an operator note to one Guardian incident and emit auditable evidence."""
    clean_incident_id = str(incident_id or "").strip()
    if not clean_incident_id:
        raise HTTPException(status_code=400, detail="incident_id cannot be empty")
    note_text = str(req.note or "").strip()
    if not note_text:
        raise HTTPException(status_code=400, detail="note cannot be empty")
    effective_run_id = run_id or _current_run_id()
    note_record = {
        "schema": "guardian_incident_note.v1",
        "note_id": make_event_id().replace("evt-", "guardian-note-", 1),
        "incident_id": clean_incident_id,
        "run_id": effective_run_id,
        "operator": req.operator or "operator",
        "source": req.source or "live_gui",
        "note": note_text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata = controller._state.run_metadata
    notes = metadata.setdefault("guardian_incident_notes", [])
    if not isinstance(notes, list):
        notes = []
        metadata["guardian_incident_notes"] = notes
    notes.append(note_record)
    del notes[:-200]

    matched = False
    incidents = metadata.get("incident_records") if isinstance(metadata.get("incident_records"), list) else []
    for incident in incidents:
        if not isinstance(incident, dict):
            continue
        if str(incident.get("incident_id") or incident.get("id") or "") != clean_incident_id:
            continue
        incident_notes = incident.setdefault("operator_notes", [])
        if not isinstance(incident_notes, list):
            incident_notes = []
            incident["operator_notes"] = incident_notes
        incident_notes.append(note_record)
        incident["last_operator_note_at"] = note_record["created_at"]
        matched = True
        break

    try:
        controller._append_guardian_event(note_record)
    except Exception:
        pass
    event = await controller.emit_runtime_event(
        event_type="operator.guardian.incident_note_attached",
        message=f"Guardian incident note attached: {clean_incident_id}",
        payload={
            "agent": "guardian_agent",
            "agent_id": "guardian",
            "node_id": "guardian",
            "status": "recorded",
            "incident_id": clean_incident_id,
            "note_id": note_record["note_id"],
            "matched_incident": matched,
            "guardian_incident_note": note_record,
        },
        level="INFO",
        run_id=effective_run_id,
    )
    return {"ok": True, "matched_incident": matched, "note": note_record, "event": event}


def _approval_events_for_run(run_id: str) -> dict[str, list[dict[str, object]]]:
    """Build pending/resolved approval queues from buffered runtime events."""
    events = [event for event in controller.recent_events() if event.get("run_id") == run_id]
    requested: list[dict[str, Any]] = []
    resolved: dict[str, dict[str, Any]] = {}
    for event in events:
        event_type = str(event.get("type") or event.get("event_type") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        is_request = (
            event_type == "approval.requested"
            or bool(payload.get("requires_human_approval"))
            or bool(payload.get("requires_approval"))
            or str(payload.get("status") or "") == "waiting_approval"
        )
        if is_request:
            requested.append(event)
        if event_type == "approval.resolved":
            approval_id = _approval_id_from_event(event)
            if approval_id:
                resolved[approval_id] = event
    approvals: list[dict[str, object]] = []
    for event in requested:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        approval_id = _approval_id_from_event(event)
        resolved_event = resolved.get(approval_id)
        approvals.append(
            {
                "approval_id": approval_id,
                "status": "resolved" if resolved_event else "pending",
                "title": payload.get("title") or event.get("message") or "Approval required",
                "reason": payload.get("reason") or payload.get("failure_code") or "",
                "stage": payload.get("stage") or event.get("timestamp_stage") or event.get("node_id") or "",
                "safety_class": payload.get("safety_class", "operator_review"),
                "request_event_id": event.get("event_id", ""),
                "requested_at": event.get("ts") or event.get("timestamp") or "",
                "resolved_event_id": resolved_event.get("event_id", "") if resolved_event else "",
                "resolved_at": resolved_event.get("ts", "") if resolved_event else "",
                "decision": (resolved_event.get("payload", {}) if isinstance(resolved_event, dict) else {}).get("decision", "") if resolved_event else "",
                "operator": (resolved_event.get("payload", {}) if isinstance(resolved_event, dict) else {}).get("operator", "") if resolved_event else "",
                "payload": payload,
            }
        )
    pending = [item for item in approvals if item["status"] == "pending"]
    resolved_items = [item for item in approvals if item["status"] == "resolved"]
    return {"approvals": approvals, "pending": pending, "resolved": resolved_items}


def _runtime_graph_handler_registry() -> HandlerRegistry:
    """Build the Runtime IDE handler allowlist from registered runtime agents."""
    registry = HandlerRegistry()

    async def _noop(runtime_state: dict[str, object]) -> dict[str, object]:
        return runtime_state

    for handler_id in {"runtime.dispatch", "runtime.idle", "runtime.terminal", "runtime.step_complete", GENERATED_MODULE_HANDLER_ID}:
        registry.register(handler_id, _noop)
    for agent_name in controller._deps.agent_registry.names():
        registry.register(f"agent.{agent_name}", _noop)
    return registry


def _runtime_module_ids() -> set[str]:
    """Return module ids available to graph/module validation."""
    ids: set[str] = set()
    for path in RUNTIME_MODULE_ROOT.glob("*/module.yaml"):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            ids.add(path.parent.name)
            continue
        module = raw.get("module", raw) if isinstance(raw, dict) else {}
        if isinstance(module, dict):
            ids.add(str(module.get("id") or path.parent.name))
        else:
            ids.add(path.parent.name)
    return ids


def _runtime_graph_compiler(config: GraphConfig) -> ATRLangGraphCompiler:
    """Build a compiler with current handler and module allowlists."""
    return ATRLangGraphCompiler(config, _runtime_graph_handler_registry(), module_ids=_runtime_module_ids())


async def _emit_graph_validation_failed(
    *,
    graph_id: str,
    action: str,
    errors: list[str],
) -> None:
    """Emit a standard Runtime IDE graph validation failure event."""
    await controller.emit_runtime_event(
        event_type="graph.validation_failed",
        message=f"Runtime graph {graph_id} validation failed during {action}.",
        level="ERROR",
        payload={
            "graph_id": graph_id,
            "node_id": "runtime_ide",
            "status": "failed",
            "action": action,
            "errors": list(errors),
        },
    )


async def _emit_graph_compiled(
    *,
    graph_id: str,
    action: str,
    compiled_graph: dict[str, object],
    graph_evidence: dict[str, object] | None = None,
) -> None:
    """Emit a standard Runtime IDE graph compiled event."""
    await controller.emit_runtime_event(
        event_type="graph.compiled",
        message=f"Runtime graph {graph_id} compiled for {action}.",
        payload={
            "graph_id": graph_id,
            "node_id": "runtime_ide",
            "status": "compiled",
            "action": action,
            "compiled_graph": compiled_graph,
            **dict(graph_evidence or {}),
        },
    )


def _graph_dry_run_sequence(
    config: GraphConfig,
    max_steps: int = 24,
    *,
    start_stage: str = "idle",
) -> list[dict[str, object]]:
    """Simulate configured stage transitions without calling agents or device tools."""
    stage = start_stage or "idle"
    if stage not in config.stage_dispatch and stage not in config.terminal_stages:
        raise HTTPException(status_code=400, detail=f"Unknown dry-run start_stage={stage}")
    sequence: list[dict[str, object]] = []
    seen: set[str] = set()
    nodes_by_id = {node.id: node for node in config.nodes}
    for step_index in range(max_steps):
        node_id = config.node_for_stage(stage)
        node = nodes_by_id.get(node_id or "")
        module_id = _module_id_from_graph_node_module_id(node.module_id if node else None)
        module_runtime = _module_runtime_summary(module_id) if module_id else {}
        graph_handler = str(node.handler) if node else ""
        module_handler = str(module_runtime.get("handler") or "") if module_runtime else ""
        effective_handler = module_handler or graph_handler
        transition_candidates = config.transition_candidates(stage)
        next_stage = config.next_stage(stage, guardian_decision="continue", state_metadata={})
        selected_transition = next((candidate for candidate in transition_candidates if str(candidate.get("to_stage")) == next_stage), {})
        sequence.append(
            {
                "step": step_index + 1,
                "stage": stage,
                "node_id": node_id,
                "node_label": node.label if node else "",
                "node_kind": node.kind if node else "",
                "graph_handler": graph_handler,
                "module_id": module_id,
                "module_handler": module_handler,
                "effective_handler": effective_handler,
                "module_runtime": module_runtime,
                "next_stage": next_stage,
                "transition_candidates": transition_candidates,
                "selected_transition": selected_transition,
            }
        )
        if stage == "guardian" and next_stage == "design":
            break
        if next_stage in config.terminal_stages:
            break
        if next_stage in seen:
            break
        seen.add(stage)
        stage = next_stage
    return sequence


@app.get("/api/graphs")
async def get_runtime_graphs() -> dict[str, object]:
    """List runtime graph configs exposed to the GUI/IDE."""
    graphs = [_graph_list_item(config, path) for _graph_id, path, config in _graph_config_items()]
    return {"ok": True, "active_graph_id": PRIMARY_RUNTIME_GRAPH_ID, "graphs": graphs}


@app.get("/api/graphs/{graph_id}")
async def get_runtime_graph(graph_id: str) -> dict[str, object]:
    """Return one runtime graph config."""
    return {"ok": True, "graph": _graph_config_payload(graph_id)}


@app.get("/api/handlers")
async def get_runtime_handlers() -> dict[str, object]:
    """Return allowlisted graph handler ids and runtime-call metadata."""
    registry = _runtime_graph_handler_registry()
    return {"ok": True, "handlers": registry.names(), "handler_metadata": registry.metadata_all()}


@app.get("/api/tools")
async def get_runtime_tools() -> dict[str, object]:
    """Return registered ToolRegistry names for module allowlist editing."""
    tools = sorted(_registered_tool_names())
    return {"ok": True, "tools": tools, "count": len(tools)}


@app.get("/api/modules")
async def get_runtime_modules() -> dict[str, object]:
    """List editable module configs exposed to the Runtime IDE."""
    modules = [_module_list_item(path) for path in sorted(RUNTIME_MODULE_ROOT.glob("*/module.yaml"))]
    categories: dict[str, int] = {}
    for module in modules:
        category = str(module.get("category") or "runtime")
        categories[category] = categories.get(category, 0) + 1
    return {"ok": True, "modules": modules, "categories": categories, "loaded_module_ids": sorted(_RUNTIME_MODULE_MANAGEMENT_LOADED)}


@app.get("/api/modules/management-state")
async def get_runtime_module_management_state() -> dict[str, object]:
    """Return module management workspace load state."""
    modules = [_module_list_item(path) for path in sorted(RUNTIME_MODULE_ROOT.glob("*/module.yaml"))]
    known_ids = {str(module.get("id")) for module in modules}
    _RUNTIME_MODULE_MANAGEMENT_LOADED.intersection_update(known_ids)
    return {"ok": True, "loaded_module_ids": sorted(_RUNTIME_MODULE_MANAGEMENT_LOADED), "modules": modules}


@app.post("/api/modules")
async def create_runtime_module(req: RuntimeModuleCreateRequest) -> dict[str, object]:
    """Create a cataloged Runtime IDE module from an uploaded Python file via the active LLM backend."""
    if controller.snapshot().get("is_running"):
        raise HTTPException(status_code=409, detail="Cannot create runtime module while a run is active.")
    try:
        safe_id = ModuleConfigStore.safe_module_id(req.module_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    module_dir = RUNTIME_MODULE_ROOT / safe_id
    module_path = module_dir / "module.yaml"
    if module_path.exists():
        raise HTTPException(status_code=409, detail=f"Module already exists: {safe_id}")

    handler_registry = set(_runtime_graph_handler_registry().names())
    registered_tools = _registered_tool_names()
    warnings: list[str] = []
    transform_payload: dict[str, Any] = {}
    transformed_source = ""

    if req.transform_with_llm:
        transform_payload = await _transform_module_source_with_model(req, safe_id)
        transformed_source = str(transform_payload.get("transformed_source") or "").strip()
    else:
        transformed_source = str(req.source_text or "").strip()
        if not transformed_source:
            raise HTTPException(status_code=400, detail="source_text is required when transform_with_llm is false.")
        warnings.append("LLM transform was disabled; module is stored as a protocol-pending source artifact.")

    requested_handler = str(req.handler or "").strip()
    suggested_handler = str(transform_payload.get("handler") or "").strip()
    if requested_handler and requested_handler != "runtime.step_complete" and requested_handler in handler_registry:
        handler = requested_handler
    elif suggested_handler in handler_registry:
        handler = suggested_handler
    elif requested_handler in handler_registry:
        handler = requested_handler
    else:
        handler = "runtime.step_complete"
        if requested_handler or suggested_handler:
            warnings.append(f"Unsupported handler ignored: requested={requested_handler or '-'} suggested={suggested_handler or '-'}")

    category = _module_designer_category(str(transform_payload.get("category") or req.category or "custom"))
    label = str(transform_payload.get("label") or req.label or safe_id).strip() or safe_id
    llm_role = str(req.llm_role or transform_payload.get("llm_role") or "").strip()
    notes = str(transform_payload.get("notes") or req.notes or "Created from Runtime IDE Module Designer.").strip()

    suggested_tools = transform_payload.get("tools") if isinstance(transform_payload.get("tools"), list) else []
    raw_tools = [*req.tools, *[str(tool) for tool in suggested_tools]]
    tools: list[str] = []
    rejected_tools: list[str] = []
    for tool in raw_tools:
        clean = str(tool).strip()
        if not clean or clean in tools:
            continue
        if registered_tools and clean not in registered_tools:
            rejected_tools.append(clean)
            continue
        tools.append(clean)
    if rejected_tools:
        warnings.append(f"Unregistered tools omitted: {', '.join(rejected_tools[:8])}")

    internal_graph = _normalize_designer_steps(
        transform_payload.get("internal_graph"),
        default_handler=handler,
        handler_registry=handler_registry,
    )

    module_dir.mkdir(parents=True, exist_ok=True)
    original_source_name = _safe_source_filename(req.source_filename or f"{safe_id}_original.py")
    if original_source_name == "handler.py":
        original_source_name = "source_original.py"
    original_path = module_dir / original_source_name
    if req.source_text.strip():
        original_path.write_text(req.source_text, encoding="utf-8")

    transformed_path = module_dir / "handler.py"
    transformed_path.write_text(transformed_source + ("\n" if not transformed_source.endswith("\n") else ""), encoding="utf-8")
    designer_model = str(
        transform_payload.get("_used_model")
        or req.transform_model
        or os.getenv("AUTONOMOUS_MODULE_DESIGNER_MODEL", "")
        or "module_designer_route"
    )

    metadata: dict[str, object] = {
        "category": category,
        "created_from": "runtime_ide_module_designer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_filename": original_source_name,
        "python_source_path": str(original_path) if req.source_text.strip() else "",
        "transformed_python_source_path": str(transformed_path),
        "transformed_by_model": designer_model if req.transform_with_llm else "operator_disabled_llm_transform",
        "source_truncated_for_prompt": bool(transform_payload.get("_source_truncated_for_prompt", False)),
        "pending_handler_registration": handler == "runtime.step_complete",
        "generated_adapter_approved": False,
        "generated_adapter_handler_id": GENERATED_MODULE_HANDLER_ID,
        "protocol_contract": "AgentResult / OrchestratorState / AgentContext / ToolRegistry",
        "warnings": warnings,
    }
    if rejected_tools:
        metadata["rejected_tools"] = rejected_tools

    payload = {
        "module": {
            "id": safe_id,
            "label": label,
            "handler": handler,
            "llm_role": llm_role,
            "editable": True,
            "category": category,
            "metadata": metadata,
            "safety": {"live_requires_validation": True, "dry_run_supported": True, "requires_human_approval": handler == "runtime.step_complete"},
            "tools": tools,
            "pre_execution": [],
            "internal_graph": internal_graph,
            "io_contract": {
                "input": "OrchestratorState",
                "output": "AgentResult.data merged into OrchestratorState",
                "adapter_signature": "async run(state: OrchestratorState, ctx: AgentContext) -> AgentResult",
            },
            "notes": notes,
        }
    }
    errors = _validate_module_payload(safe_id, payload)
    if errors:
        return {"ok": False, "module_id": safe_id, "errors": errors, "warnings": warnings, "module": payload}

    store = _module_config_store()
    dry_run = _module_dry_run_evidence(safe_id, payload)
    version = store.save_version(safe_id, payload, reason="runtime_ide_module_designer_create", author="runtime_ide")
    store.write_active(safe_id, payload)
    return {
        "ok": True,
        "module_id": safe_id,
        "errors": [],
        "warnings": warnings,
        "version": version,
        "module": payload,
        "dry_run": dry_run,
        "catalog_item": _module_list_item(module_path),
        "transform": {
            "model": designer_model if req.transform_with_llm else "disabled",
            "category": category,
            "handler": handler,
            "transformed_source_path": str(transformed_path),
            "pending_handler_registration": handler == "runtime.step_complete",
            "generated_adapter_approved": False,
            "generated_adapter_handler_id": GENERATED_MODULE_HANDLER_ID,
        },
    }


@app.get("/api/modules/{module_id}")
async def get_runtime_module(module_id: str) -> dict[str, object]:
    """Return one editable module config."""
    return {"ok": True, "module": _module_config_payload(module_id), "loaded": module_id in _RUNTIME_MODULE_MANAGEMENT_LOADED}


@app.post("/api/modules/{module_id}/register-generated")
async def register_generated_runtime_module(module_id: str) -> dict[str, object]:
    """Approve and activate a Module Designer-generated adapter after static validation."""
    if controller.snapshot().get("is_running"):
        raise HTTPException(status_code=409, detail="Cannot register generated module while a run is active.")
    payload = ModuleConfigStore.normalize_payload(dict(_module_config_payload(module_id)))
    module = payload.get("module", {}) if isinstance(payload, dict) else {}
    if not isinstance(module, dict):
        raise HTTPException(status_code=400, detail="Invalid module payload.")
    safe_id = ModuleConfigStore.safe_module_id(module_id)
    adapter_path = generated_adapter_path(RUNTIME_MODULE_ROOT, safe_id)
    errors = validate_generated_adapter_file(adapter_path)
    if errors:
        return {"ok": False, "module_id": safe_id, "registered": False, "errors": errors, "adapter_path": str(adapter_path)}
    metadata = module.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        module["metadata"] = metadata
    module["handler"] = GENERATED_MODULE_HANDLER_ID
    for step in module.get("internal_graph", []) if isinstance(module.get("internal_graph"), list) else []:
        if isinstance(step, dict) and str(step.get("handler") or "").strip() == "runtime.step_complete":
            step.pop("handler", None)
    safety = module.setdefault("safety", {})
    if isinstance(safety, dict):
        safety["requires_human_approval"] = True
        safety["live_requires_validation"] = True
        safety["dry_run_supported"] = True
    metadata["pending_handler_registration"] = False
    metadata["generated_adapter_approved"] = True
    metadata["generated_adapter_handler_id"] = GENERATED_MODULE_HANDLER_ID
    metadata["generated_adapter_registered_at"] = datetime.now(timezone.utc).isoformat()
    metadata["generated_adapter_path"] = str(adapter_path)
    normalized = {"module": module}
    enabled, enable_errors = generated_adapter_enabled(safe_id, normalized, RUNTIME_MODULE_ROOT)
    if not enabled:
        return {"ok": False, "module_id": safe_id, "registered": False, "errors": enable_errors, "adapter_path": str(adapter_path)}
    errors = _validate_module_payload(safe_id, normalized)
    if errors:
        return {"ok": False, "module_id": safe_id, "registered": False, "errors": errors, "adapter_path": str(adapter_path)}
    dry_run = _module_dry_run_evidence(safe_id, normalized)
    version = _module_config_store().save_version(
        safe_id,
        normalized,
        reason="runtime_module_register_generated_adapter",
        author="runtime_ide",
    )
    _module_config_store().write_active(safe_id, normalized)
    return {
        "ok": True,
        "module_id": safe_id,
        "registered": True,
        "handler": GENERATED_MODULE_HANDLER_ID,
        "adapter_path": str(adapter_path),
        "version": version,
        "dry_run": dry_run,
        "module": normalized,
    }


@app.post("/api/modules/{module_id}/load")
async def load_runtime_module_into_management(module_id: str) -> dict[str, object]:
    """Load a module into the standalone management workspace without changing runtime config."""
    payload = _module_config_payload(module_id)
    _RUNTIME_MODULE_MANAGEMENT_LOADED.add(module_id)
    return {
        "ok": True,
        "module_id": module_id,
        "loaded": True,
        "loaded_module_ids": sorted(_RUNTIME_MODULE_MANAGEMENT_LOADED),
        "module": payload,
    }


@app.post("/api/modules/{module_id}/unload")
async def unload_runtime_module_from_management(module_id: str) -> dict[str, object]:
    """Unload a module from the management workspace without deleting module.yaml."""
    _module_config_payload(module_id)
    _RUNTIME_MODULE_MANAGEMENT_LOADED.discard(module_id)
    return {"ok": True, "module_id": module_id, "loaded": False, "loaded_module_ids": sorted(_RUNTIME_MODULE_MANAGEMENT_LOADED)}


@app.get("/api/modules/{module_id}/versions")
async def get_runtime_module_versions(module_id: str) -> dict[str, object]:
    """List saved versions for one module config."""
    _module_config_payload(module_id)
    return {"ok": True, "module_id": module_id, "versions": _module_config_store().list_versions(module_id)}


@app.get("/api/modules/{module_id}/versions/{version_id}")
async def get_runtime_module_version(module_id: str, version_id: str) -> dict[str, object]:
    """Return one saved module config version without activating it."""
    _module_config_payload(module_id)
    try:
        version = _module_config_store().read_version(module_id, version_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "module_id": module_id, "version": version}


@app.post("/api/modules/{module_id}/validate")
async def validate_runtime_module(module_id: str, req: RuntimeModuleSaveRequest | None = None) -> dict[str, object]:
    """Validate an active or draft module config without writing it."""
    payload = dict(req.module) if req and req.module else _module_config_payload(module_id)
    errors = _validate_module_payload(module_id, payload)
    return {"ok": not errors, "module_id": module_id, "errors": errors}


@app.post("/api/modules/{module_id}/dry-run")
async def dry_run_runtime_module(module_id: str, req: RuntimeModuleSaveRequest | None = None) -> dict[str, object]:
    """Simulate the configured internal module step order without calling tools/devices."""
    payload = dict(req.module) if req and req.module else _module_config_payload(module_id)
    errors = _validate_module_payload(module_id, payload)
    if errors:
        return {"ok": False, "module_id": module_id, "errors": errors, "sequence": [], "summary": _module_dry_run_summary([])}
    sequence = _module_dry_run_sequence(module_id, payload)
    return {"ok": True, "module_id": module_id, "errors": [], "sequence": sequence, "summary": _module_dry_run_summary(sequence)}


@app.put("/api/modules/{module_id}")
async def save_runtime_module(module_id: str, req: RuntimeModuleSaveRequest) -> dict[str, object]:
    """Validate, version, and optionally activate one module config."""
    if controller.snapshot().get("is_running"):
        raise HTTPException(status_code=409, detail="Cannot modify runtime module while a run is active.")
    if not req.module:
        raise HTTPException(status_code=400, detail="Missing module payload.")
    payload = ModuleConfigStore.normalize_payload(dict(req.module))
    errors = _validate_module_payload(module_id, payload)
    if errors:
        return {
            "ok": False,
            "module_id": module_id,
            "errors": errors,
            "version": None,
            "dry_run": {"ok": False, "module_id": module_id, "sequence": [], "summary": _module_dry_run_summary([])},
        }
    dry_run = _module_dry_run_evidence(module_id, payload)
    version = _module_config_store().save_version(module_id, payload, reason=req.reason, author=req.author)
    if req.activate:
        _module_config_store().write_active(module_id, payload)
    return {
        "ok": True,
        "module_id": module_id,
        "errors": [],
        "version": version,
        "activated": req.activate,
        "dry_run": dry_run,
    }


@app.post("/api/graphs/{graph_id}/validate")
async def validate_runtime_graph(graph_id: str) -> dict[str, object]:
    """Validate the runtime graph against the current handler allowlist."""
    config = _load_runtime_graph_config(graph_id)
    compiler = _runtime_graph_compiler(config)
    errors = compiler.validate()
    if errors:
        await _emit_graph_validation_failed(graph_id=graph_id, action="validate", errors=errors)
    return {"ok": not errors, "graph_id": graph_id, "errors": errors}


@app.post("/api/graphs/{graph_id}/validate-draft")
async def validate_runtime_graph_draft(graph_id: str, req: RuntimeGraphSaveRequest) -> dict[str, object]:
    """Validate and compile-check a draft graph payload without writing a version."""
    if not req.graph:
        raise HTTPException(status_code=400, detail="Missing graph payload.")
    try:
        config = GraphConfig.model_validate(req.graph)
    except Exception as exc:
        errors = [str(exc)]
        await _emit_graph_validation_failed(graph_id=graph_id, action="validate-draft", errors=errors)
        return {"ok": False, "graph_id": graph_id, "errors": errors, "compiled": False}
    if graph_id != config.id:
        raise HTTPException(status_code=400, detail=f"graph_id path/body mismatch: {graph_id} != {config.id}")
    compiler = _runtime_graph_compiler(config)
    errors = compiler.validate()
    if errors:
        await _emit_graph_validation_failed(graph_id=graph_id, action="validate-draft", errors=errors)
        return {"ok": False, "graph_id": graph_id, "errors": errors, "compiled": False}
    compiler.compile()
    compiled_graph = compiler.summary()
    await _emit_graph_compiled(graph_id=graph_id, action="validate-draft", compiled_graph=compiled_graph, graph_evidence=_graph_version_evidence(graph_id, config))
    return {"ok": True, "graph_id": graph_id, "errors": [], "compiled": True, "compiled_graph": compiled_graph}


@app.post("/api/graphs/{graph_id}/compile")
async def compile_runtime_graph(graph_id: str) -> dict[str, object]:
    """Compile the active graph without starting agents or hardware."""
    config = _load_runtime_graph_config(graph_id)
    compiler = _runtime_graph_compiler(config)
    errors = compiler.validate()
    if errors:
        await _emit_graph_validation_failed(graph_id=graph_id, action="compile", errors=errors)
        return {"ok": False, "graph_id": graph_id, "errors": errors, "compiled": False}
    compiler.compile()
    compiled_graph = compiler.summary()
    await _emit_graph_compiled(graph_id=graph_id, action="compile", compiled_graph=compiled_graph, graph_evidence=_graph_version_evidence(graph_id, config))
    return {"ok": True, "graph_id": graph_id, "errors": [], "compiled": True, "compiled_graph": compiled_graph}


@app.post("/api/graphs/{graph_id}/export-yaml", response_class=PlainTextResponse)
async def export_runtime_graph_yaml(graph_id: str, req: RuntimeGraphSaveRequest | None = None) -> PlainTextResponse:
    """Export an active or draft graph payload as canonical YAML."""
    payload = dict(req.graph) if req and req.graph else _graph_config_payload(graph_id)
    try:
        config = GraphConfig.model_validate(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid graph payload: {exc}") from exc
    if graph_id != config.id:
        raise HTTPException(status_code=400, detail=f"graph_id path/body mismatch: {graph_id} != {config.id}")
    body = yaml.safe_dump({"graph": config.model_dump(mode="json")}, sort_keys=False, allow_unicode=True)
    return PlainTextResponse(
        content=body,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{config.id}.yaml"'},
    )


@app.post("/api/graphs/{graph_id}/import-yaml")
async def import_runtime_graph_yaml(graph_id: str, req: RuntimeGraphYamlImportRequest) -> dict[str, object]:
    """Parse, validate, and compile-check an imported graph YAML draft without activation."""
    try:
        raw = yaml.safe_load(req.yaml_text) or {}
    except yaml.YAMLError as exc:
        errors = [f"YAML parse error: {exc}"]
        await _emit_graph_validation_failed(graph_id=graph_id, action="import-yaml", errors=errors)
        return {"ok": False, "graph_id": graph_id, "errors": errors, "compiled": False, "graph": None}
    if not isinstance(raw, dict):
        errors = ["YAML root must be an object"]
        await _emit_graph_validation_failed(graph_id=graph_id, action="import-yaml", errors=errors)
        return {"ok": False, "graph_id": graph_id, "errors": errors, "compiled": False, "graph": None}
    graph_payload = raw.get("graph", raw)
    try:
        config = GraphConfig.model_validate(graph_payload)
    except Exception as exc:
        errors = [str(exc)]
        await _emit_graph_validation_failed(graph_id=graph_id, action="import-yaml", errors=errors)
        return {"ok": False, "graph_id": graph_id, "errors": errors, "compiled": False, "graph": None}
    if graph_id != config.id:
        errors = [f"graph_id path/body mismatch: {graph_id} != {config.id}"]
        await _emit_graph_validation_failed(graph_id=graph_id, action="import-yaml", errors=errors)
        raise HTTPException(status_code=400, detail=errors[0])
    compiler = _runtime_graph_compiler(config)
    errors = compiler.validate()
    if errors:
        await _emit_graph_validation_failed(graph_id=graph_id, action="import-yaml", errors=errors)
        return {
            "ok": False,
            "graph_id": graph_id,
            "errors": errors,
            "compiled": False,
            "compiled_graph": None,
            "graph": config.model_dump(mode="json"),
        }
    compiler.compile()
    compiled_graph = compiler.summary()
    await _emit_graph_compiled(graph_id=graph_id, action="import-yaml", compiled_graph=compiled_graph, graph_evidence=_graph_version_evidence(graph_id, config))
    return {
        "ok": True,
        "graph_id": graph_id,
        "errors": [],
        "compiled": True,
        "compiled_graph": compiled_graph,
        "graph": config.model_dump(mode="json"),
    }


@app.get("/api/graphs/{graph_id}/versions")
async def get_runtime_graph_versions(graph_id: str) -> dict[str, object]:
    """List saved graph config versions."""
    _graph_config_payload(graph_id)
    return {"ok": True, "graph_id": graph_id, "versions": _graph_version_store(graph_id).list_versions(graph_id)}


@app.get("/api/graphs/{graph_id}/versions/{version_id}")
async def get_runtime_graph_version(graph_id: str, version_id: str) -> dict[str, object]:
    """Return one saved graph config version without activating it."""
    _graph_config_payload(graph_id)
    try:
        version = _graph_version_store(graph_id).read_version(graph_id, version_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "graph_id": graph_id, "version": version}


@app.put("/api/graphs/{graph_id}")
async def save_runtime_graph(graph_id: str, req: RuntimeGraphSaveRequest) -> dict[str, object]:
    """Validate, version, and optionally activate a Runtime IDE graph config."""
    if controller.snapshot().get("is_running"):
        raise HTTPException(status_code=409, detail="Cannot modify runtime graph while a run is active.")
    if not req.graph:
        raise HTTPException(status_code=400, detail="Missing graph payload.")
    try:
        config = GraphConfig.model_validate(req.graph)
    except Exception as exc:
        errors = [str(exc)]
        await _emit_graph_validation_failed(graph_id=graph_id, action="save", errors=errors)
        return {"ok": False, "graph_id": graph_id, "errors": errors, "version": None, "dry_run": {"ok": False, "sequence": [], "dry_run_record": {}}}
    if graph_id != config.id:
        errors = [f"graph_id path/body mismatch: {graph_id} != {config.id}"]
        await _emit_graph_validation_failed(graph_id=graph_id, action="save", errors=errors)
        raise HTTPException(status_code=400, detail=errors[0])
    compiler = _runtime_graph_compiler(config)
    errors = compiler.validate()
    if errors:
        await _emit_graph_validation_failed(graph_id=graph_id, action="save", errors=errors)
        return {"ok": False, "graph_id": graph_id, "errors": errors, "version": None, "dry_run": {"ok": False, "sequence": [], "dry_run_record": {}}}
    compiler.compile()
    compiled_graph = compiler.summary()
    dry_run = _graph_dry_run_evidence(config=config, compiled_graph=compiled_graph, record_live_gate=False)
    await _emit_graph_compiled(graph_id=graph_id, action="save", compiled_graph=compiled_graph, graph_evidence=_graph_version_evidence(graph_id, config))
    payload = config.model_dump(mode="json")
    version = _graph_version_store(graph_id).save_version(graph_id, payload, reason=req.reason, author=req.author)
    if req.activate:
        _graph_version_store(graph_id).write_active(payload)
        dry_run["dry_run_record"] = _record_graph_dry_run(
            config=config,
            options=RuntimeGraphDryRunRequest(start_stage=str(dry_run.get("start_stage") or "idle"), max_steps=24),
            sequence=dry_run.get("sequence", []),
            compiled_graph=compiled_graph,
        )
    return {
        "ok": True,
        "graph_id": graph_id,
        "errors": [],
        "version": version,
        "activated": req.activate,
        "compiled_graph": compiled_graph,
        "dry_run": dry_run,
        "dry_run_record": dry_run.get("dry_run_record", {}),
    }


@app.post("/api/graphs/{graph_id}/save-version")
async def save_runtime_graph_version_compat(graph_id: str, req: RuntimeGraphSaveVersionRequest | None = None) -> dict[str, object]:
    """Compatibility endpoint for package-specified graph version saves.

    Unlike the Runtime IDE PUT endpoint, this package endpoint defaults to
    version-only writes. Activation still requires an explicit activate=true.
    """
    payload = req or RuntimeGraphSaveVersionRequest()
    graph_payload = dict(payload.graph) if payload.graph else _graph_config_payload(graph_id)
    result = await save_runtime_graph(
        graph_id,
        RuntimeGraphSaveRequest(
            graph=graph_payload,
            reason=payload.reason,
            author=payload.author,
            activate=payload.activate,
        ),
    )
    if result.get("ok"):
        await controller.emit_runtime_event(
            event_type="graph_version_saved",
            message=f"Graph version saved: {graph_id}",
            payload={
                "graph_id": graph_id,
                "version": result.get("version"),
                "activated": result.get("activated"),
                "compatibility_endpoint": f"/api/graphs/{graph_id}/save-version",
            },
            level="INFO",
        )
    result["compatibility"] = "atr_live_gui_package"
    result["save_version_endpoint"] = True
    return result


@app.post("/api/graphs/{graph_id}/dry-run")
async def dry_run_runtime_graph(graph_id: str, req: RuntimeGraphDryRunRequest | None = None) -> dict[str, object]:
    """Run a non-device transition simulation for the active graph or a supplied draft graph."""
    options = req or RuntimeGraphDryRunRequest()
    draft_mode = bool(options.graph)
    if draft_mode:
        try:
            config = GraphConfig.model_validate(options.graph)
        except Exception as exc:
            errors = [str(exc)]
            await _emit_graph_validation_failed(graph_id=graph_id, action="dry-run-draft", errors=errors)
            return {"ok": False, "graph_id": graph_id, "errors": errors, "sequence": [], "draft": True}
        if graph_id != config.id:
            raise HTTPException(status_code=400, detail=f"graph_id path/body mismatch: {graph_id} != {config.id}")
    else:
        config = _load_runtime_graph_config(graph_id)
    compiler = _runtime_graph_compiler(config)
    errors = compiler.validate()
    if errors:
        await _emit_graph_validation_failed(graph_id=graph_id, action="dry-run-draft" if draft_mode else "dry-run", errors=errors)
        return {"ok": False, "graph_id": graph_id, "errors": errors, "sequence": [], "draft": draft_mode}
    compiler.compile()
    compiled_graph = compiler.summary()
    sequence = _graph_dry_run_sequence(config, max_steps=options.max_steps, start_stage=options.start_stage)
    if draft_mode:
        dry_run_record = {
            "graph_id": config.id,
            "digest": _graph_config_digest(config),
            "dry_run_at": datetime.now(timezone.utc).isoformat(),
            "start_stage": options.start_stage,
            "max_steps": options.max_steps,
            "step_count": len(sequence),
            "compiled_graph": compiled_graph,
            "draft": True,
            "live_gate_recorded": False,
        }
    else:
        dry_run_record = _record_graph_dry_run(config=config, options=options, sequence=sequence, compiled_graph=compiled_graph)
    await _emit_graph_compiled(graph_id=graph_id, action="dry-run-draft" if draft_mode else "dry-run", compiled_graph=compiled_graph, graph_evidence=_graph_version_evidence(graph_id, config))
    return {
        "ok": True,
        "graph_id": graph_id,
        "errors": [],
        "start_stage": options.start_stage,
        "sequence": sequence,
        "compiled_graph": compiled_graph,
        "dry_run_record": dry_run_record,
        "draft": draft_mode,
    }


@app.get("/api/graphs/{graph_id}/dry-run-gate")
async def get_runtime_graph_dry_run_gate(graph_id: str) -> dict[str, object]:
    """Return active-config dry-run gate status for live Runtime IDE execution."""
    config = _load_runtime_graph_config(graph_id)
    dry_run_ok, dry_run_record = _graph_live_dry_run_gate(config)
    return {
        "ok": True,
        "graph_id": graph_id,
        "gate_ok": dry_run_ok,
        "has_record": bool(dry_run_record),
        "dry_run_record": dry_run_record,
    }


@app.post("/api/graphs/{graph_id}/run")
async def run_runtime_graph(graph_id: str, req: StartRunRequest) -> dict[str, object]:
    """Compile-check one graph config and start it through the shared LangGraph run loop."""
    config_path = _graph_config_path(graph_id)
    config = load_graph_config(config_path)
    compiler = _runtime_graph_compiler(config)
    errors = compiler.validate()
    if errors:
        await _emit_graph_validation_failed(graph_id=graph_id, action="run", errors=errors)
        return {"ok": False, "graph_id": graph_id, "errors": errors, "run": None}
    compiler.compile()
    compiled_graph = compiler.summary()
    metadata = config.metadata if isinstance(config.metadata, dict) else {}
    if graph_id != PRIMARY_RUNTIME_GRAPH_ID and req.mode == "live" and not bool(metadata.get("executable_from_runtime_ide")):
        raise HTTPException(
            status_code=400,
            detail="Workspace template graph live run is disabled by graph metadata; use test/replay/fault-injection or set executable_from_runtime_ide=true after validation.",
        )
    dry_run_ok, dry_run_record = _graph_live_dry_run_gate(config)
    if req.mode == "live" and not dry_run_ok:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "GRAPH_DRY_RUN_REQUIRED",
                "message": "Run graph dry-run on the active graph config before live execution.",
                "graph_id": graph_id,
                "has_record": bool(dry_run_record),
            },
        )
    graph_evidence = _graph_version_evidence(graph_id, config)
    run = await controller.start(
        mode=Mode(req.mode),
        goal=req.goal,
        backend=req.backend,
        fault=req.fault,
        fault_stage=req.fault_stage,
        graph_id=graph_id,
        graph_config_path=_graph_config_runtime_path(config_path),
        graph_hash=str(graph_evidence.get("graph_hash") or ""),
        graph_version=str(graph_evidence.get("graph_version") or ""),
        graph_version_id=str(graph_evidence.get("graph_version_id") or ""),
        graph_version_path=str(graph_evidence.get("graph_version_path") or ""),
    )
    await _emit_graph_compiled(graph_id=graph_id, action="run", compiled_graph=compiled_graph, graph_evidence=graph_evidence)
    return {
        "ok": bool(run.get("ok")),
        "graph_id": graph_id,
        "graph_hash": graph_evidence.get("graph_hash", ""),
        "graph_version": graph_evidence.get("graph_version", ""),
        "graph_version_id": graph_evidence.get("graph_version_id", ""),
        "errors": [],
        "run": run,
        "compiled_graph": compiled_graph,
        "dry_run_record": dry_run_record if req.mode == "live" else _RUNTIME_GRAPH_DRY_RUN_RECORDS.get(graph_id, {}),
    }


@app.get("/api/bo/config")
async def get_bo_config() -> dict[str, object]:
    """Return BO Workspace defaults and recent BO state."""
    snapshot = controller.snapshot()
    state = snapshot.get("state", {}) if isinstance(snapshot.get("state"), dict) else {}
    metadata = state.get("run_metadata", {}) if isinstance(state.get("run_metadata"), dict) else {}
    saved = _read_workspace_settings(BO_WORKSPACE_SETTINGS_PATH)
    return {
        "ok": True,
        "defaults": BOAgent.defaults(),
        "saved": saved,
        "settings_path": str(BO_WORKSPACE_SETTINGS_PATH),
        "recent": metadata.get("bo_agent", {}),
        "state": state,
    }


@app.post("/api/bo/config")
async def save_bo_config(req: BOAgentRequest) -> dict[str, object]:
    """Persist BO Workspace settings for future GUI sessions."""
    settings, warnings = BOAgent.normalize_settings(req.model_dump())
    saved: dict[str, Any] = {
        **settings,
        "objective": req.objective,
        "mode": req.mode,
    }
    _write_workspace_settings(BO_WORKSPACE_SETTINGS_PATH, saved)
    return {
        "ok": True,
        "saved": saved,
        "warnings": warnings,
        "settings_path": str(BO_WORKSPACE_SETTINGS_PATH),
    }


@app.post("/api/bo/benchmark")
async def post_bo_benchmark(req: BOAgentRequest) -> dict[str, object]:
    """Run experiment.benchmark from BO Workspace without changing hardware state."""
    settings, warnings = BOAgent.normalize_settings(req.model_dump())
    objective = req.objective or {
        "objective_id": "bo-workspace-objective",
        "name": "Specimen printability and performance proxy",
        "metric_name": "objective_score",
        "direction": "maximize",
        "tags": ["bo", "workspace"],
    }
    strategies = ["random", "grid", "bo"] if settings["strategy"] == "mbo" else [settings["benchmark_strategy"]]
    result = controller._deps.agent_context.tools.call(
        "experiment.benchmark",
        {
            "budget": settings["budget"],
            "strategies": strategies,
            "seed": settings["random_seed"],
            "parameter_space": settings["parameter_space"],
            "objective": objective,
            "acquisition": settings["acquisition"],
            "kappa": settings["kappa"],
            "xi": settings["xi"],
            "exploration_weight": settings["exploration_weight"],
            "exploitation_weight": settings["exploitation_weight"],
            "bo_backend": settings["bo_backend"],
            "prior_evaluations": BOAgent._prior_evaluations_from_state(controller._state),
            "request": {
                "run_id": controller.snapshot()["state"]["run_id"],
                "experiment_id": controller.snapshot()["state"]["experiment_id"],
                "objective": objective,
                "execution": {"mode": "virtual", "bridge": "virtual", "dry_run": True},
                "metadata": {
                    "source": "bo_workspace",
                    "acquisition": settings["acquisition"],
                    "kappa": settings["kappa"],
                    "xi": settings["xi"],
                    "exploration_weight": settings["exploration_weight"],
                    "exploitation_weight": settings["exploitation_weight"],
                    "bo_backend": settings["bo_backend"],
                },
            },
        },
    )
    await controller.emit_workspace_result(
        workspace="bo",
        tool="experiment.benchmark",
        result=result,
        stage=Stage.BO,
        module_id="bo",
        agent="bo_agent",
        workflow="benchmark",
    )
    return {"ok": bool(result.get("ok", False)), "warnings": warnings, "benchmark": result}


@app.post("/api/bo/run")
async def post_bo_run(req: BOAgentRequest) -> dict[str, object]:
    """Run registered BO Agent and store latest advisory result in controller state."""
    state = controller._state
    if req.mode in {"test", "live", "replay"}:
        state.mode = Mode(req.mode)
    agent = controller._deps.agent_registry.get("bo_agent")
    result = await agent.run_with_settings(state, controller._deps.agent_context, req.model_dump())
    workspace_result = {"ok": bool(result.success), "summary": result.summary, "data": result.data}
    await controller.emit_workspace_result(
        workspace="bo",
        tool="bo_agent.run_with_settings",
        result=workspace_result,
        stage=Stage.BO,
        module_id="bo",
        agent="bo_agent",
        workflow="bo_agent_run",
        node_event=True,
    )
    return {
        "ok": bool(result.success),
        "summary": result.summary,
        "data": result.data,
        "snapshot": controller.snapshot(),
    }


@app.get("/api/cae/config")
async def get_cae_config() -> dict[str, object]:
    """Return CAE Workspace defaults, solver health, and recent analysis state."""
    health = controller._deps.agent_context.tools.call("cae.health", {})
    snapshot = controller.snapshot()
    state = snapshot.get("state", {}) if isinstance(snapshot.get("state"), dict) else {}
    latest = state.get("latest_analysis", {}) if isinstance(state.get("latest_analysis"), dict) else {}
    metadata = state.get("run_metadata", {}) if isinstance(state.get("run_metadata"), dict) else {}
    saved = _read_workspace_settings(CAE_WORKSPACE_SETTINGS_PATH)
    return {
        "ok": True,
        "health": health,
        "defaults": health.get("defaults", {}),
        "saved": saved,
        "settings_path": str(CAE_WORKSPACE_SETTINGS_PATH),
        "recent": latest.get("cae_result") or metadata.get("last_cae_result") or {},
        "state": state,
    }


@app.post("/api/cae/config")
async def save_cae_config(req: CAEAnalysisRequest) -> dict[str, object]:
    """Persist CAE Workspace settings for future GUI sessions."""
    saved = req.model_dump()
    _write_workspace_settings(CAE_WORKSPACE_SETTINGS_PATH, saved)
    return {
        "ok": True,
        "saved": saved,
        "settings_path": str(CAE_WORKSPACE_SETTINGS_PATH),
    }


@app.post("/api/cae/run")
async def post_cae_run(req: CAEAnalysisRequest) -> dict[str, object]:
    """Run CAE analysis from the dedicated workspace."""
    payload = {
        "runtime_mode": req.mode,
        "mode": req.mode,
        "solver": req.solver,
        "mesher": req.mesher,
        "stl_path": req.stl_path,
        "specimen_id": req.specimen_id,
        "specimen_size_mm": req.specimen_size_mm,
        "mesh_size_mm": req.mesh_size_mm,
        "material": {
            "elastic_modulus_mpa": req.elastic_modulus_mpa,
            "poisson_ratio": req.poisson_ratio,
            "yield_strength_mpa": req.yield_strength_mpa,
        },
        "loading": {
            "load_type": "cyclic_compression",
            "load_max_n": req.load_max_n,
            "load_min_ratio": req.load_min_ratio,
            "cycles": req.cycles,
            "frequency_hz": req.frequency_hz,
        },
        "boundary": {"bottom": "fixed_support", "top": "cyclic_loading"},
        "require_solver": req.require_solver,
        "source": "cae_workspace",
    }
    result = controller._deps.agent_context.tools.call("cae.run_static_analysis", payload)
    controller._state.run_metadata["last_cae_result"] = result
    if result.get("ok"):
        controller._state.latest_analysis["cae_result"] = result
        controller._state.latest_analysis["cae_metrics"] = result.get("cae_metrics") or result.get("metrics") or {}
    await controller.emit_workspace_result(
        workspace="cae",
        tool="cae.run_static_analysis",
        result=result,
        stage=Stage.ANALYSIS,
        module_id="analysis",
        agent="analysis_agent",
        workflow="cae_static_analysis",
        node_event=True,
    )
    return {"ok": bool(result.get("ok")), "result": result, "snapshot": controller.snapshot()}


@app.post("/api/runtime/backend")
async def post_runtime_backend(req: BackendSwitchRequest) -> dict[str, object]:
    """Switch active inference backend for future model calls."""
    return await controller.switch_inference_backend(req.backend)


@app.get("/api/runtime/models")
async def get_runtime_models() -> dict[str, object]:
    """Return managed model serving status for the selected backend."""
    return await controller.runtime_model_statuses()


@app.post("/api/runtime/models/load")
async def post_runtime_model_load(req: RuntimeModelRequest) -> dict[str, object]:
    """Load one managed NemoClaw vLLM model."""
    return await controller.load_runtime_model(req.model)


@app.post("/api/runtime/models/unload")
async def post_runtime_model_unload(req: RuntimeModelRequest) -> dict[str, object]:
    """Unload one managed NemoClaw vLLM model."""
    return await controller.unload_runtime_model(req.model)


@app.get("/api/runtime/api-key")
async def get_runtime_api_key() -> dict[str, object]:
    """Return the local OpenAI API key status without exposing the secret."""
    settings = _read_api_key_settings(import_env=True)
    return await _apply_runtime_api_key_settings(settings, emit_event=False)


@app.post("/api/runtime/api-key")
async def post_runtime_api_key(req: RuntimeApiKeyRequest) -> dict[str, object]:
    """Save the OpenAI API key to the local gitignored single-file store."""
    settings = _write_api_key_settings(req.api_key, enabled=req.enabled, source="user")
    return await _apply_runtime_api_key_settings(settings)


@app.post("/api/runtime/api-key/load")
async def post_runtime_api_key_load() -> dict[str, object]:
    """Enable the saved OpenAI API key for runtime fallback use."""
    settings = _read_api_key_settings(import_env=True)
    if not str(settings.get("api_key") or "").strip():
        public = _public_api_key_settings(settings)
        public.update({"ok": False, "message": "API key is not configured."})
        return public
    settings = _write_api_key_settings(
        str(settings.get("api_key") or ""),
        enabled=True,
        source=str(settings.get("source") or "memory"),
    )
    return await _apply_runtime_api_key_settings(settings)


@app.post("/api/runtime/api-key/unload")
async def post_runtime_api_key_unload() -> dict[str, object]:
    """Disable the saved OpenAI API key without deleting it from the local store."""
    settings = _read_api_key_settings(import_env=True)
    settings = _write_api_key_settings(
        str(settings.get("api_key") or ""),
        enabled=False,
        source=str(settings.get("source") or "memory"),
    )
    return await _apply_runtime_api_key_settings(settings)


def _request_audit_log_gate(payload: dict[str, object]) -> tuple[dict[str, object], str | None]:
    """Return strict request-audit evidence for a live Windows UTM command path."""
    audit = payload.get("request_audit_log") if isinstance(payload.get("request_audit_log"), dict) else {}
    path = str(
        audit.get("path")
        or audit.get("request_log")
        or payload.get("request_log_path")
        or payload.get("bridge_request_log_ref")
        or payload.get("request_log")
        or ""
    )

    def as_int(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    raw_count = audit.get("event_count")
    if raw_count in (None, ""):
        raw_count = payload.get("request_log_event_count")
    if raw_count in (None, ""):
        raw_count = payload.get("event_count")
    event_count = as_int(raw_count)
    execute_event_count = as_int(
        audit.get("execute_event_count")
        or payload.get("request_log_execute_count")
        or payload.get("execute_event_count")
    )
    execute_payload_event_count = as_int(
        audit.get("execute_payload_event_count")
        or payload.get("request_log_execute_payload_event_count")
        or payload.get("execute_payload_event_count")
    )
    execute_result_event_count = as_int(
        audit.get("execute_result_event_count")
        or payload.get("request_log_execute_result_event_count")
        or payload.get("execute_result_event_count")
    )
    if event_count <= 0 and execute_event_count > 0:
        event_count = execute_event_count

    recent_paths = audit.get("recent_paths") if isinstance(audit.get("recent_paths"), list) else []
    if not recent_paths and isinstance(payload.get("request_log_recent_paths"), list):
        recent_paths = payload.get("request_log_recent_paths")  # type: ignore[assignment]
    if not recent_paths and isinstance(payload.get("events"), list):
        recent_paths = [item.get("path") for item in payload["events"] if isinstance(item, dict)]
    recent_paths = [str(item) for item in recent_paths if str(item or "").strip()]
    execute_from_paths = any(item == "/execute" or item.endswith("/execute") for item in recent_paths)
    execute_event_seen = bool(
        audit.get("execute_event_seen") is True
        or payload.get("request_log_execute_seen") is True
        or payload.get("execute_event_seen") is True
        or execute_event_count > 0
        or execute_from_paths
    )
    last_execute_at = str(
        audit.get("last_execute_at")
        or payload.get("request_log_last_execute_at")
        or payload.get("last_execute_at")
        or ""
    )

    def string_list(*values: object) -> list[str]:
        output: list[str] = []
        for value in values:
            if isinstance(value, list):
                for item in value:
                    text = str(item or "").strip()
                    if text and text not in output:
                        output.append(text)
            else:
                text = str(value or "").strip()
                if text and text not in output:
                    output.append(text)
        return output

    last_context = audit.get("last_execute_context") if isinstance(audit.get("last_execute_context"), dict) else payload.get("request_log_last_execute_context") if isinstance(payload.get("request_log_last_execute_context"), dict) else {}
    execute_run_ids = string_list(audit.get("execute_run_ids"), payload.get("request_log_execute_run_ids"), payload.get("execute_run_ids"), last_context.get("run_id") if isinstance(last_context, dict) else "")
    execute_sequence_ids = string_list(audit.get("execute_sequence_ids"), payload.get("request_log_execute_sequence_ids"), payload.get("execute_sequence_ids"), last_context.get("sequence_id") if isinstance(last_context, dict) else "")
    execute_specimen_ids = string_list(audit.get("execute_specimen_ids"), payload.get("request_log_execute_specimen_ids"), payload.get("execute_specimen_ids"), last_context.get("specimen_id") if isinstance(last_context, dict) else "")
    execute_program_ids = string_list(audit.get("execute_program_ids"), payload.get("request_log_execute_program_ids"), payload.get("execute_program_ids"), last_context.get("program_id") if isinstance(last_context, dict) else "")
    expected_identity = {
        "run_id": str(payload.get("expected_run_id") or audit.get("expected_run_id") or ""),
        "sequence_id": str(payload.get("expected_sequence_id") or audit.get("expected_sequence_id") or ""),
        "specimen_id": str(payload.get("expected_specimen_id") or audit.get("expected_specimen_id") or ""),
        "program_id": str(payload.get("expected_program_id") or audit.get("expected_program_id") or ""),
    }
    identity_required = bool(payload.get("require_execute_identity_match") or audit.get("require_execute_identity_match") or any(expected_identity.values()))
    identity_present = bool(execute_payload_event_count > 0 or execute_run_ids or execute_specimen_ids or execute_program_ids)

    def contains(expected: str, observed: list[str]) -> bool:
        return not expected or expected in observed

    identity_match = bool(
        (not identity_required)
        or (
            identity_present
            and contains(expected_identity["run_id"], execute_run_ids)
            and contains(expected_identity["program_id"], execute_program_ids)
            and contains(expected_identity["specimen_id"], execute_specimen_ids)
        )
    )
    ok = bool(path and event_count > 0 and execute_event_seen and identity_match)
    failure_code = None
    if not ok:
        if path and event_count > 0 and execute_event_seen and not identity_match:
            failure_code = "UTM_REQUEST_LOG_EXECUTE_IDENTITY_REQUIRED"
        else:
            failure_code = "UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED" if path and event_count > 0 else "UTM_REQUEST_LOG_REQUIRED"
    return (
        {
            "ok": ok,
            "path": path,
            "event_count": event_count,
            "recent_paths": recent_paths,
            "execute_event_seen": execute_event_seen,
            "execute_event_count": execute_event_count,
            "execute_payload_event_count": execute_payload_event_count,
            "execute_result_event_count": execute_result_event_count,
            "execute_run_ids": execute_run_ids,
            "execute_sequence_ids": execute_sequence_ids,
            "execute_specimen_ids": execute_specimen_ids,
            "execute_program_ids": execute_program_ids,
            "last_execute_context": last_context,
            "last_execute_at": last_execute_at,
            "execute_identity_required": identity_required,
            "execute_identity_present": identity_present,
            "execute_identity_match": identity_match,
            "execute_identity_detail": {
                "expected": expected_identity,
                "observed": {
                    "run_ids": execute_run_ids,
                    "sequence_ids": execute_sequence_ids,
                    "specimen_ids": execute_specimen_ids,
                    "program_ids": execute_program_ids,
                },
            },
        },
        failure_code,
    )


def _windows_utm_proof_checklist(
    *,
    gates: dict[str, object],
    request_audit_log: dict[str, object],
    screen_refs: list[object],
    data_refs: list[object],
    data_acquisition: dict[str, object],
    blockers: list[str],
    source: str,
) -> tuple[list[dict[str, object]], bool]:
    """Build an operator-readable proof checklist for Windows UTM handoff evidence."""
    screen_ref_count = len([item for item in screen_refs if str(item or "").strip()])
    data_ref_count = len([item for item in data_refs if str(item or "").strip()])
    linux_path = str(data_acquisition.get("linux_path") or data_acquisition.get("local_path") or "")
    row_count = data_acquisition.get("row_count_probe")
    try:
        row_count_int = int(row_count or 0)
    except (TypeError, ValueError):
        row_count_int = 0
    checklist = [
        {
            "id": "request_log_execute",
            "label": "Windows bridge /execute audit",
            "ok": bool(request_audit_log.get("ok") and request_audit_log.get("execute_event_seen") and request_audit_log.get("execute_identity_match") is not False),
            "required": True,
            "detail": f"events={request_audit_log.get('event_count', 0)}; execute_count={request_audit_log.get('execute_event_count', 0)}; identity_match={request_audit_log.get('execute_identity_match', '-')}; last_execute_at={request_audit_log.get('last_execute_at', '') or '-'}",
        },
        {
            "id": "physical_live_execute",
            "label": "Physical live /execute dispatch",
            "ok": bool(gates.get("physical_live_execute")),
            "required": True,
            "detail": "The proof must come from a live physical validation run, not preflight, simulator, or a copied report.",
        },
        {
            "id": "screen_evidence",
            "label": "UTM screen-state evidence",
            "ok": bool(gates.get("screen_evidence_complete")),
            "required": True,
            "detail": f"screen_refs={screen_ref_count}; expected before_start/after_start/after_complete screenshots",
        },
        {
            "id": "physical_motion",
            "label": "Physical UTM motion cross-check",
            "ok": bool(gates.get("physical_motion_started")),
            "required": True,
            "detail": "Vision or data-stream evidence must confirm motion; screen running alone is not sufficient.",
        },
        {
            "id": "linux_artifact_pull",
            "label": "Linux-side UTM artifact pull",
            "ok": bool(gates.get("linux_artifact_pulled")),
            "required": True,
            "detail": linux_path or "Linux-local UTM CSV path is not recorded.",
        },
        {
            "id": "save_export_responsibility",
            "label": "UTM save/export responsibility",
            "ok": bool(gates.get("save_export_responsibility_ok")),
            "required": True,
            "detail": f"save_method={data_acquisition.get('save_method', '') or '-'}; save_attempted={bool(data_acquisition.get('save_attempted_by_agent'))}; confirmation={bool(data_acquisition.get('save_confirmation_screen_ok'))}",
        },
        {
            "id": "data_parse_probe",
            "label": "UTM CSV parse probe",
            "ok": bool(gates.get("data_parse_probe_ok")),
            "required": True,
            "detail": f"data_refs={data_ref_count}; row_count_probe={row_count_int}",
        },
        {
            "id": "vision_evidence_frames",
            "label": "Vision frame evidence",
            "ok": bool(gates.get("vision_evidence_complete")),
            "required": True,
            "detail": "Frame IDs must prove fixture/motion/complete physical states before Analysis handoff.",
        },
    ]
    blockers_set = set(blockers)
    if blockers_set:
        checklist.append(
            {
                "id": "blocking_reason_review",
                "label": "Blocking reason review",
                "ok": False,
                "required": False,
                "detail": ", ".join(sorted(blockers_set)[:8]),
            }
        )
    proof_ready = all(bool(item.get("ok")) for item in checklist if item.get("required") is not False)
    for item in checklist:
        item["source"] = source
    return checklist, proof_ready


def _windows_utm_evidence_audit_from_raw_result(result: dict[str, object], *, run_id: str = "") -> dict[str, object]:
    """Audit a direct /equipment/windows UTM protocol-test result without hardware calls."""
    screen_checks = result.get("screen_checks") if isinstance(result.get("screen_checks"), list) else []
    artifacts = result.get("output_artifacts") if isinstance(result.get("output_artifacts"), list) else []
    data_acquisition = result.get("data_acquisition") if isinstance(result.get("data_acquisition"), dict) else {}
    cross_checks = result.get("cross_checks") if isinstance(result.get("cross_checks"), dict) else {}
    request_audit_log, request_audit_failure = _request_audit_log_gate({
        **result,
        "expected_run_id": str(run_id or result.get("run_id") or ""),
        "expected_sequence_id": str(result.get("sequence_id") or ""),
        "expected_specimen_id": str(result.get("specimen_id") or ""),
        "expected_program_id": str(result.get("program_id") or ""),
        "require_execute_identity_match": True,
    })

    required_checkpoints = ["before_start", "after_start", "after_complete"]
    screen_by_checkpoint = {
        str(item.get("checkpoint") or ""): item
        for item in screen_checks
        if isinstance(item, dict)
    }
    missing_checkpoints = [
        checkpoint
        for checkpoint in required_checkpoints
        if not (
            isinstance(screen_by_checkpoint.get(checkpoint), dict)
            and bool(screen_by_checkpoint[checkpoint].get("ok"))
            and bool(str(screen_by_checkpoint[checkpoint].get("screenshot_artifact") or "").strip())
        )
    ]

    screen_ids = {
        str(item.get("screenshot_artifact") or "")
        for item in screen_checks
        if isinstance(item, dict) and item.get("screenshot_artifact")
    }
    screen_refs: list[str] = []
    data_refs: list[str] = []
    artifact_refs: list[str] = []
    data_row_count_probe = data_acquisition.get("row_count_probe")
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        ref = str(artifact.get("local_path") or artifact.get("linux_path") or artifact.get("path") or artifact.get("artifact_id") or artifact.get("windows_path") or "")
        if ref:
            artifact_refs.append(ref)
        kind = str(artifact.get("kind") or "")
        artifact_id = str(artifact.get("artifact_id") or "")
        if kind == "screen_png" or artifact_id in screen_ids:
            screen_refs.append(ref)
        if kind == "utm_csv":
            data_refs.append(ref)
            if data_row_count_probe in (None, 0, "") and artifact.get("row_count_probe") not in (None, 0, ""):
                data_row_count_probe = artifact.get("row_count_probe")
    result_file = str(result.get("result_file") or result.get("utm_csv_path") or data_acquisition.get("linux_path") or data_acquisition.get("local_path") or "")
    if result_file:
        data_refs.insert(0, result_file)
        artifact_refs.insert(0, result_file)

    screen_evidence_complete = not missing_checkpoints
    linux_artifact_pulled = bool(
        str(data_acquisition.get("status") or "") == "pulled_to_linux"
        and bool(result_file)
        and bool(data_acquisition.get("linux_path") or data_acquisition.get("local_path") or result.get("result_file"))
    )
    data_parse_probe_ok = bool(cross_checks.get("data_parse_probe_ok", result_file and data_row_count_probe not in (None, 0, "")))
    save_completed = bool(cross_checks.get("save_completed", data_acquisition.get("save_confirmation_screen_ok") or linux_artifact_pulled))
    data_file_created = bool(cross_checks.get("data_file_created", bool(result_file)))
    save_method = str(data_acquisition.get("save_method") or "").strip()
    recognized_save_methods = {"windows_export_watch", "manual_save_dialog", "export_menu", "simulated_bridge_export", "simulated_auto_export", "synthetic_test_export"}
    save_export_responsibility_ok = bool(
        cross_checks.get(
            "save_export_responsibility_ok",
            linux_artifact_pulled
            and data_parse_probe_ok
            and save_method in recognized_save_methods
            and (bool(data_acquisition.get("save_attempted_by_agent")) or save_method in {"windows_export_watch", "simulated_bridge_export", "simulated_auto_export"})
            and (bool(data_acquisition.get("save_confirmation_screen_ok")) or bool(data_acquisition.get("windows_path")) or bool(result_file)),
        )
    )

    gate_values = {
        "screen_started": bool(cross_checks.get("screen_started", screen_evidence_complete)),
        "physical_motion_started": bool(cross_checks.get("physical_motion_started", False)),
        "save_completed": save_completed,
        "data_file_created": data_file_created,
        "data_parse_probe_ok": data_parse_probe_ok,
        "screen_evidence_complete": bool(screen_evidence_complete),
        "linux_artifact_pulled": bool(linux_artifact_pulled),
        "save_export_responsibility_ok": bool(save_export_responsibility_ok),
        "vision_evidence_complete": False,
        "request_audit_log_available": bool(request_audit_log.get("ok")),
        "physical_live_execute": False,
    }
    blockers: list[str] = []
    for gate, ok in gate_values.items():
        if not ok:
            if gate == "request_audit_log_available" and request_audit_failure:
                blockers.append(request_audit_failure)
            elif gate == "save_export_responsibility_ok":
                blockers.append("UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED")
            else:
                blockers.append(f"{gate.upper()}_REQUIRED")
    if not data_refs:
        blockers.append("UTM_DATA_EVIDENCE_REF_REQUIRED")
    if len(screen_refs) < 3:
        blockers.append("UTM_SCREEN_EVIDENCE_REFS_INCOMPLETE")
    if request_audit_failure:
        blockers.append(request_audit_failure)
    blockers.append("UTM_VISION_EVIDENCE_FRAMES_REQUIRED")
    if result.get("failure_code"):
        blockers.append(str(result["failure_code"]))
    blockers = list(dict.fromkeys(item for item in blockers if item))

    live_evidence_audit = {
        "required_for_handoff": True,
        "source": "windows_equipment_run_program",
        "screen_evidence": {
            "ok": bool(screen_evidence_complete),
            "required_checkpoints": required_checkpoints,
            "observed_checkpoints": [checkpoint for checkpoint in required_checkpoints if checkpoint not in missing_checkpoints],
            "missing_checkpoints": missing_checkpoints,
        },
        "linux_artifact_pull": {
            "ok": bool(linux_artifact_pulled),
            "status": data_acquisition.get("status", ""),
            "linux_path": result_file,
            "parse_probe_ok": bool(data_parse_probe_ok),
        },
        "save_export": {
            "ok": bool(save_export_responsibility_ok),
            "save_method": save_method,
            "save_attempted_by_agent": bool(data_acquisition.get("save_attempted_by_agent")),
            "save_confirmation_screen_ok": bool(data_acquisition.get("save_confirmation_screen_ok")),
            "windows_path": str(data_acquisition.get("windows_path") or ""),
            "linux_path": result_file,
            "recognized_save_method": save_method in recognized_save_methods,
        },
        "vision_evidence": {
            "ok": False,
            "all_required_ok": False,
            "evidence_frame_ids": [],
        },
        "request_audit_log": request_audit_log,
    }
    proof_checklist, proof_ready = _windows_utm_proof_checklist(
        gates=gate_values,
        request_audit_log=request_audit_log,
        screen_refs=list(screen_refs),
        data_refs=list(data_refs),
        data_acquisition=data_acquisition,
        blockers=blockers,
        source="windows_equipment_run_program",
    )

    return {
        "ok": False,
        "tool": "equipment.pyautogui.live_evidence_audit",
        "status": "blocked",
        "run_id": run_id or str(result.get("run_id") or result.get("sequence_id") or ""),
        "bridge": str(result.get("bridge") or "windows_pyautogui"),
        "program_id": str(result.get("program_id") or ""),
        "handoff_status": "blocked",
        "equipment_status": str(result.get("status") or ""),
        "failure_code": blockers[0] if blockers else None,
        "required_for_handoff": True,
        "gates": gate_values,
        "live_evidence_audit": live_evidence_audit,
        "request_audit_log": request_audit_log,
        "proof_checklist": proof_checklist,
        "proof_ready": proof_ready,
        "decision": {
            "handoff_status": "blocked",
            "equipment_status": str(result.get("status") or ""),
            "blocking_reasons": blockers,
            "recommended_next_agent": "equipment_agent",
        },
        "data_acquisition": data_acquisition,
        "evidence_refs": list(dict.fromkeys(str(item) for item in artifact_refs if str(item or "").strip())),
        "screen_evidence_refs": list(dict.fromkeys(str(item) for item in screen_refs if str(item or "").strip())),
        "data_evidence_refs": list(dict.fromkeys(str(item) for item in data_refs if str(item or "").strip())),
        "blockers": blockers,
        "warnings": ["WINDOWS_GUI_PROTOCOL_TEST_REQUIRES_LABEQUIPMENT_AGENT_VISION_PACKAGE_FOR_ANALYSIS_HANDOFF"],
        "next_actions": [
            "Use the full Lab Equipment Agent stage to add Vision frame evidence before Analysis handoff.",
            "If this was a setup test, review screen and CSV pull gates, then run the autonomous equipment stage.",
        ] + (
            ["Inspect the Windows bridge request log and confirm the live /execute request was recorded."]
            if request_audit_failure
            else []
        ),
    }



def _physical_validation_identity_gate(
    source: dict[str, object],
    *,
    expected_run_id: str = "",
    expected_sequence_id: str = "",
    expected_specimen_id: str = "",
    expected_program_id: str = "",
) -> tuple[bool, dict[str, object]]:
    """Require the physical validation packet itself to identify the live UTM command."""
    expected = {
        "run_id": str(expected_run_id or "").strip(),
        "sequence_id": str(expected_sequence_id or "").strip(),
        "specimen_id": str(expected_specimen_id or "").strip(),
        "program_id": str(expected_program_id or "").strip(),
    }
    observed = {key: str(source.get(key) or "").strip() for key in expected}
    missing = [key for key, value in observed.items() if not value]
    mismatched = [key for key, value in expected.items() if value and observed.get(key) and observed.get(key) != value]
    dispatch_ok = bool(
        source.get("requested_physical_execute") is True
        and source.get("execute_sent") is True
        and source.get("non_actuating") is False
        and str(source.get("status") or "") == "verified_complete"
    )
    identity_ok = bool(not missing and not mismatched)
    evidence = {
        "dispatch_ok": dispatch_ok,
        "identity_ok": identity_ok,
        "expected": expected,
        "observed": observed,
        "missing_identity_fields": missing,
        "mismatched_identity_fields": mismatched,
        "requested_physical_execute": bool(source.get("requested_physical_execute")),
        "execute_sent": bool(source.get("execute_sent")),
        "non_actuating": bool(source.get("non_actuating", True)),
        "status": str(source.get("status") or ""),
    }
    return bool(dispatch_ok and identity_ok), evidence



def _windows_utm_intermediate_file_evidence_gate(
    screen_refs: list[str],
    data_refs: list[str],
    *artifact_sources: object,
) -> dict[str, object]:
    """Verify local screen/data evidence before the final proof-package audit."""
    package = {
        "source_packets": {
            f"source_{index}": value
            for index, value in enumerate(artifact_sources)
            if isinstance(value, dict)
        }
    }
    artifact_records = _windows_proof_artifact_records(package)

    verified_screen_files: list[str] = []
    missing_screen_files: list[str] = []
    invalid_screen_files: list[str] = []
    unresolved_screen_refs: list[str] = []
    for ref in screen_refs:
        path, source = _windows_proof_resolved_ref_path(ref, artifact_records)
        if path is None:
            unresolved_screen_refs.append(str(ref))
            continue
        if path.exists() and path.is_file():
            image_ok, image_detail = _windows_proof_image_signature(path)
            if image_ok:
                verified_screen_files.append(str(path))
            else:
                invalid_screen_files.append(f"{path} ({image_detail}; {source})")
        else:
            missing_screen_files.append(f"{path} ({source})")
    unique_screen_files = sorted(set(verified_screen_files))
    duplicate_screen_files = len(unique_screen_files) != len(verified_screen_files)
    screen_ok = bool(
        len(screen_refs) >= 3
        and len(unique_screen_files) >= 3
        and not missing_screen_files
        and not invalid_screen_files
        and not unresolved_screen_refs
        and not duplicate_screen_files
    )

    verified_data_files: list[str] = []
    missing_data_files: list[str] = []
    unresolved_data_refs: list[str] = []
    for ref in data_refs:
        path, source = _windows_proof_resolved_ref_path(ref, artifact_records)
        if path is None:
            unresolved_data_refs.append(str(ref))
            continue
        if path.exists() and path.is_file():
            verified_data_files.append(str(path))
        else:
            missing_data_files.append(f"{path} ({source})")
    unique_data_files = sorted(set(verified_data_files))
    csv_probes = [_windows_proof_csv_probe(Path(item)) for item in unique_data_files]
    failed_csv_probes = [probe for probe in csv_probes if not bool(probe.get("ok"))]
    data_ok = bool(data_refs and unique_data_files and not missing_data_files and not unresolved_data_refs)
    data_probe_ok = bool(data_ok and csv_probes and not failed_csv_probes)

    blockers: list[str] = []
    if not screen_ok:
        blockers.append("UTM_SCREEN_EVIDENCE_FILES_REQUIRED")
    if not data_ok:
        blockers.append("UTM_DATA_EVIDENCE_FILES_REQUIRED")
    if data_ok and not data_probe_ok:
        for probe in failed_csv_probes:
            code = str(probe.get("failure_code") or "UTM_CSV_PARSE_PROBE_FAILED")
            if code not in blockers:
                blockers.append(code)
    return {
        "screen_ok": screen_ok,
        "data_ok": data_ok,
        "data_probe_ok": data_probe_ok,
        "verified_screen_files": unique_screen_files,
        "verified_data_files": unique_data_files,
        "csv_probes": csv_probes,
        "failed_csv_probes": failed_csv_probes,
        "missing_screen_files": missing_screen_files,
        "invalid_screen_files": invalid_screen_files,
        "unresolved_screen_refs": unresolved_screen_refs,
        "duplicate_screen_files": duplicate_screen_files,
        "missing_data_files": missing_data_files,
        "unresolved_data_refs": unresolved_data_refs,
        "blockers": blockers,
    }


def _windows_utm_evidence_audit_from_live_validation_report(report: dict[str, object], *, run_id: str = "") -> dict[str, object]:
    """Convert a lab_equipment_utm_live_validation.v1 report into the proof-package audit contract."""
    evidence = report.get("evidence") if isinstance(report.get("evidence"), dict) else {}
    execution = evidence.get("execution") if isinstance(evidence.get("execution"), dict) else {}
    data_acquisition = execution.get("data_acquisition") if isinstance(execution.get("data_acquisition"), dict) else {}
    request_audit_source = report.get("request_audit_log") if isinstance(report.get("request_audit_log"), dict) else evidence.get("request_log_after") if isinstance(evidence.get("request_log_after"), dict) else {}
    expected_run_id = str(report.get("run_id") or run_id or execution.get("run_id") or "")
    expected_sequence_id = str(report.get("sequence_id") or execution.get("sequence_id") or "")
    expected_specimen_id = str(report.get("specimen_id") or execution.get("specimen_id") or "")
    expected_program_id = str(report.get("program_id") or execution.get("program_id") or "")
    request_audit_log, request_audit_failure = _request_audit_log_gate({
        **dict(request_audit_source),
        "request_audit_log": request_audit_source,
        "expected_run_id": expected_run_id,
        "expected_sequence_id": expected_sequence_id,
        "expected_specimen_id": expected_specimen_id,
        "expected_program_id": expected_program_id,
        "require_execute_identity_match": True,
    })

    gates_by_name = {
        str(item.get("name") or ""): item
        for item in report.get("gates", [])
        if isinstance(item, dict)
    }

    def gate_ok(name: str) -> bool:
        return bool(isinstance(gates_by_name.get(name), dict) and gates_by_name[name].get("ok") is True)

    screen_gate = gates_by_name.get("screen_state_evidence") if isinstance(gates_by_name.get("screen_state_evidence"), dict) else {}
    screen_evidence = screen_gate.get("evidence") if isinstance(screen_gate.get("evidence"), dict) else {}
    observed_screens = screen_evidence.get("observed") if isinstance(screen_evidence.get("observed"), list) else execution.get("screen_checks") if isinstance(execution.get("screen_checks"), list) else []
    screen_refs = [
        str(item.get("screenshot_artifact") or item.get("artifact") or item.get("path") or "")
        for item in observed_screens
        if isinstance(item, dict) and str(item.get("screenshot_artifact") or item.get("artifact") or item.get("path") or "").strip()
    ]

    data_refs: list[str] = []
    result_file = str(execution.get("result_file") or execution.get("utm_csv_path") or data_acquisition.get("linux_path") or data_acquisition.get("local_path") or "").strip()
    if result_file:
        data_refs.append(result_file)
    artifacts = execution.get("output_artifacts") if isinstance(execution.get("output_artifacts"), list) else []
    artifact_refs: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        ref = str(artifact.get("local_path") or artifact.get("linux_path") or artifact.get("path") or artifact.get("artifact_id") or artifact.get("windows_path") or "").strip()
        if ref:
            artifact_refs.append(ref)
            if str(artifact.get("kind") or "") == "utm_csv":
                data_refs.append(ref)
    report_artifact = report.get("report_artifact") if isinstance(report.get("report_artifact"), dict) else report.get("artifact") if isinstance(report.get("artifact"), dict) else {}
    if report_artifact.get("path"):
        artifact_refs.append(str(report_artifact["path"]))

    file_evidence = _windows_utm_intermediate_file_evidence_gate(
        list(dict.fromkeys(screen_refs)),
        list(dict.fromkeys(data_refs)),
        execution,
        report,
        evidence,
    )

    physical_execute_ok, physical_execute_evidence = _physical_validation_identity_gate(
        report,
        expected_run_id=expected_run_id,
        expected_sequence_id=expected_sequence_id,
        expected_specimen_id=expected_specimen_id,
        expected_program_id=expected_program_id,
    )
    gate_values = {
        "physical_live_execute": physical_execute_ok,
        "screen_started": gate_ok("screen_state_evidence"),
        "physical_motion_started": gate_ok("vision_physical_cross_check"),
        "save_completed": gate_ok("save_export_responsibility"),
        "data_file_created": bool(gate_ok("linux_data_artifact") and file_evidence["data_ok"]),
        "data_parse_probe_ok": bool(gate_ok("utm_csv_parse_probe") and file_evidence["data_probe_ok"]),
        "screen_evidence_complete": bool(gate_ok("screen_state_evidence") and file_evidence["screen_ok"]),
        "linux_artifact_pulled": bool(gate_ok("linux_data_artifact") and file_evidence["data_ok"]),
        "save_export_responsibility_ok": gate_ok("save_export_responsibility"),
        "vision_evidence_complete": gate_ok("vision_physical_cross_check"),
        "request_audit_log_available": bool(request_audit_log.get("ok")),
        "request_audit_execute_identity_match": bool(request_audit_log.get("execute_identity_match")),
    }
    blockers: list[str] = []
    for item in report.get("blockers", []):
        if isinstance(item, dict):
            blockers.append(str(item.get("failure_code") or item.get("name") or item.get("detail") or ""))
        elif str(item or "").strip():
            blockers.append(str(item))
    if request_audit_failure:
        blockers.append(request_audit_failure)
    if not physical_execute_ok:
        blockers.append("UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED")
        if physical_execute_evidence.get("missing_identity_fields"):
            blockers.append("UTM_PHYSICAL_LIVE_EXECUTE_IDENTITY_REQUIRED")
        if physical_execute_evidence.get("mismatched_identity_fields"):
            blockers.append("UTM_PHYSICAL_LIVE_EXECUTE_IDENTITY_MISMATCH")
    if not data_refs:
        blockers.append("UTM_DATA_EVIDENCE_REF_REQUIRED")
    if len(screen_refs) < 3:
        blockers.append("UTM_SCREEN_EVIDENCE_REFS_INCOMPLETE")
    blockers.extend(str(item) for item in file_evidence.get("blockers", []) if str(item or "").strip())
    blockers = list(dict.fromkeys(item for item in blockers if str(item or "").strip()))

    vision_gate = gates_by_name.get("vision_physical_cross_check") if isinstance(gates_by_name.get("vision_physical_cross_check"), dict) else {}
    vision_evidence = vision_gate.get("evidence") if isinstance(vision_gate.get("evidence"), dict) else evidence.get("vision_proof") if isinstance(evidence.get("vision_proof"), dict) else {}
    vision_frame_ids = _windows_utm_vision_frame_ids(vision_evidence)

    live_evidence_audit = {
        "required_for_handoff": True,
        "source": "lab_equipment_utm_live_validation",
        "screen_evidence": {
            "ok": bool(gate_values["screen_evidence_complete"]),
            "observed_checkpoints": [str(item.get("checkpoint") or "") for item in observed_screens if isinstance(item, dict)],
            "screen_refs": list(dict.fromkeys(screen_refs)),
            "file_evidence": file_evidence,
        },
        "linux_artifact_pull": {
            "ok": bool(gate_values["linux_artifact_pulled"]),
            "status": data_acquisition.get("status", ""),
            "linux_path": result_file,
            "parse_probe_ok": bool(gate_values["data_parse_probe_ok"]),
            "file_evidence": {
                "ok": bool(file_evidence["data_ok"]),
                "verified_data_files": file_evidence.get("verified_data_files", []),
                "csv_probes": file_evidence.get("csv_probes", []),
                "failed_csv_probes": file_evidence.get("failed_csv_probes", []),
                "missing_data_files": file_evidence.get("missing_data_files", []),
                "unresolved_data_refs": file_evidence.get("unresolved_data_refs", []),
            },
        },
        "save_export": {
            "ok": bool(gate_values["save_export_responsibility_ok"]),
            "save_method": str(data_acquisition.get("save_method") or ""),
            "save_attempted_by_agent": bool(data_acquisition.get("save_attempted_by_agent")),
            "save_confirmation_screen_ok": bool(data_acquisition.get("save_confirmation_screen_ok")),
            "windows_path": str(data_acquisition.get("windows_path") or ""),
            "linux_path": result_file,
            "recognized_save_method": bool(gate_values["save_export_responsibility_ok"]),
        },
        "vision_evidence": {
            "ok": bool(gate_values["vision_evidence_complete"]),
            "all_required_ok": bool(gate_values["vision_evidence_complete"]),
            "evidence_frame_ids": list(dict.fromkeys(vision_frame_ids)),
            "source_report_gate": vision_evidence,
        },
        "request_audit_log": request_audit_log,
        "physical_execution": physical_execute_evidence,
    }
    proof_checklist, proof_ready = _windows_utm_proof_checklist(
        gates=gate_values,
        request_audit_log=request_audit_log,
        screen_refs=list(screen_refs),
        data_refs=list(data_refs),
        data_acquisition=data_acquisition,
        blockers=blockers,
        source="lab_equipment_utm_live_validation",
    )
    ready_for_analysis = bool(report.get("ok") is True and str(report.get("status") or "") == "verified_complete" and proof_ready and not blockers)
    status = "ready_for_analysis" if ready_for_analysis else "blocked"
    return {
        "ok": ready_for_analysis,
        "tool": "equipment.pyautogui.live_evidence_audit",
        "status": status,
        "run_id": expected_run_id,
        "bridge": "windows_pyautogui",
        "program_id": expected_program_id,
        "handoff_status": "ready_for_analysis" if ready_for_analysis else "blocked",
        "equipment_status": str(report.get("status") or ""),
        "failure_code": blockers[0] if blockers else None,
        "required_for_handoff": True,
        "gates": gate_values,
        "live_evidence_audit": live_evidence_audit,
        "request_audit_log": request_audit_log,
        "proof_checklist": proof_checklist,
        "proof_ready": proof_ready,
        "decision": {
            "handoff_status": "ready_for_analysis" if ready_for_analysis else "blocked",
            "equipment_status": str(report.get("status") or ""),
            "blocking_reasons": blockers,
            "recommended_next_agent": "analysis_agent" if ready_for_analysis else "equipment_agent",
        },
        "data_acquisition": data_acquisition,
        "evidence_refs": list(dict.fromkeys([*artifact_refs, *screen_refs, *data_refs])),
        "screen_evidence_refs": list(dict.fromkeys(screen_refs)),
        "data_evidence_refs": list(dict.fromkeys(data_refs)),
        "source_live_validation_report": report,
        "blockers": blockers,
        "warnings": [] if ready_for_analysis else ["LIVE_VALIDATION_REPORT_NOT_READY_FOR_ANALYSIS"],
        "next_actions": ["Proof package can be built for Analysis handoff review."] if ready_for_analysis else ["Resolve blocked live validation gates, then rerun physical validation."],
    }


def _windows_utm_runtime_metadata_from_live_validation_report(report: dict[str, object], *, run_id: str = "") -> dict[str, object]:
    """Promote a successful physical live-validation report into Analysis-readable runtime packets."""
    audit = _windows_utm_evidence_audit_from_live_validation_report(report, run_id=run_id)
    evidence = report.get("evidence") if isinstance(report.get("evidence"), dict) else {}
    execution = evidence.get("execution") if isinstance(evidence.get("execution"), dict) else {}
    data_acquisition = execution.get("data_acquisition") if isinstance(execution.get("data_acquisition"), dict) else {}
    request_audit_log = audit.get("request_audit_log") if isinstance(audit.get("request_audit_log"), dict) else {}
    live_evidence_audit = audit.get("live_evidence_audit") if isinstance(audit.get("live_evidence_audit"), dict) else {}
    cross_checks = audit.get("gates") if isinstance(audit.get("gates"), dict) else {}
    decision = audit.get("decision") if isinstance(audit.get("decision"), dict) else {}
    run_id_value = str(report.get("run_id") or run_id or execution.get("run_id") or "").strip()
    sequence_id = str(report.get("sequence_id") or execution.get("sequence_id") or "").strip()
    specimen_id = str(report.get("specimen_id") or execution.get("specimen_id") or "").strip()
    program_id = str(report.get("program_id") or execution.get("program_id") or "").strip()
    created_at = str(report.get("created_at") or datetime.now(timezone.utc).isoformat())
    result_file = str(
        execution.get("result_file")
        or execution.get("utm_csv_path")
        or data_acquisition.get("linux_path")
        or data_acquisition.get("local_path")
        or ""
    ).strip()
    artifact_refs = [str(item) for item in audit.get("evidence_refs", []) if str(item or "").strip()] if isinstance(audit.get("evidence_refs"), list) else []
    screen_refs = [str(item) for item in audit.get("screen_evidence_refs", []) if str(item or "").strip()] if isinstance(audit.get("screen_evidence_refs"), list) else []
    data_refs = [str(item) for item in audit.get("data_evidence_refs", []) if str(item or "").strip()] if isinstance(audit.get("data_evidence_refs"), list) else []
    if result_file and result_file not in data_refs:
        data_refs.append(result_file)
    if result_file and result_file not in artifact_refs:
        artifact_refs.append(result_file)

    vision_evidence = live_evidence_audit.get("vision_evidence") if isinstance(live_evidence_audit.get("vision_evidence"), dict) else {}
    evidence_frame_ids = (
        [str(item) for item in vision_evidence.get("evidence_frame_ids", []) if str(item or "").strip()]
        if isinstance(vision_evidence.get("evidence_frame_ids"), list)
        else []
    )
    screen_evidence = live_evidence_audit.get("screen_evidence") if isinstance(live_evidence_audit.get("screen_evidence"), dict) else {}
    save_export = live_evidence_audit.get("save_export") if isinstance(live_evidence_audit.get("save_export"), dict) else {}
    verified = bool(audit.get("ok") is True and audit.get("status") == "ready_for_analysis" and result_file)
    status = "ready_for_analysis" if verified else "blocked"
    equipment_status = "verified_complete" if verified else "blocked"
    failure_code = None if verified else str(audit.get("failure_code") or "LIVE_VALIDATION_NOT_READY_FOR_ANALYSIS")

    physical_checks = {
        "vision_motion_confirmed": bool(cross_checks.get("physical_motion_started")),
        "specimen_alignment_ok": bool(cross_checks.get("vision_evidence_complete")),
        "fixture_safe_to_access": bool(cross_checks.get("vision_evidence_complete")),
        "evidence_frame_ids": evidence_frame_ids,
    }
    visual_verification = {
        "screen_started": bool(cross_checks.get("screen_started")),
        "screen_evidence_complete": bool(cross_checks.get("screen_evidence_complete")),
        "screen_evidence_refs": screen_refs,
        "observed_checkpoints": screen_evidence.get("observed_checkpoints", []),
    }
    physical_verification = {
        "all_required_ok": bool(cross_checks.get("vision_evidence_complete")),
        **physical_checks,
        "checks": vision_evidence.get("source_report_gate", {}),
    }
    data_ledger = {
        "status": data_acquisition.get("status", ""),
        "save_method": data_acquisition.get("save_method", ""),
        "save_attempted_by_agent": bool(data_acquisition.get("save_attempted_by_agent")),
        "save_confirmation_screen_ok": bool(data_acquisition.get("save_confirmation_screen_ok")),
        "save_export_responsibility_ok": bool(cross_checks.get("save_export_responsibility_ok")),
        "recognized_save_method": bool(save_export.get("recognized_save_method")),
        "windows_path": data_acquisition.get("windows_path", ""),
        "linux_path": result_file,
        "row_count_probe": data_acquisition.get("row_count_probe", 0),
        "columns_probe": data_acquisition.get("columns_probe", []),
        "parse_ready": bool(cross_checks.get("data_parse_probe_ok")),
        "data_evidence_refs": data_refs,
    }
    handoff_gate = {
        "handoff_status": status,
        "equipment_status": equipment_status,
        "failure_code": failure_code,
        "ready_for_analysis": verified,
        "required_gates": dict(cross_checks),
        "blocking_reasons": list(decision.get("blocking_reasons", [])) if isinstance(decision.get("blocking_reasons"), list) else [],
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
        "blocked_commands": [] if verified else [failure_code],
    }
    bridge_report = {
        "provider": "windows_pyautogui",
        "connection_status": "ready" if verified else "blocked",
        "live_execute_enabled": True,
        "request_log_path": request_audit_log.get("path", ""),
        "request_log_event_count": request_audit_log.get("event_count", 0),
        "request_log_recent_paths": request_audit_log.get("recent_paths", []),
        "request_log_execute_seen": bool(request_audit_log.get("execute_event_seen")),
        "request_log_execute_count": request_audit_log.get("execute_event_count", 0),
        "request_log_execute_payload_event_count": request_audit_log.get("execute_payload_event_count", 0),
        "request_log_execute_result_event_count": request_audit_log.get("execute_result_event_count", 0),
        "request_log_execute_run_ids": request_audit_log.get("execute_run_ids", []),
        "request_log_execute_sequence_ids": request_audit_log.get("execute_sequence_ids", []),
        "request_log_execute_specimen_ids": request_audit_log.get("execute_specimen_ids", []),
        "request_log_execute_program_ids": request_audit_log.get("execute_program_ids", []),
        "request_log_last_execute_context": request_audit_log.get("last_execute_context", {}),
        "request_log_last_execute_at": request_audit_log.get("last_execute_at", ""),
        "request_log_execute_identity_required": bool(request_audit_log.get("execute_identity_required")),
        "request_log_execute_identity_present": bool(request_audit_log.get("execute_identity_present")),
        "request_log_execute_identity_match": bool(request_audit_log.get("execute_identity_match")),
        "request_log_execute_identity_detail": request_audit_log.get("execute_identity_detail", {}),
    }
    report_packet = {
        "schema": "equipment_report.v1",
        "report_version": "lab_equipment_utm_visual_control_v1",
        "source": "lab_equipment_utm_live_validation",
        "run_id": run_id_value,
        "mode": "live",
        "task_id": "utm_compression_test",
        "bridge": bridge_report,
        "control_plan": {
            "program_id": program_id,
            "macro_version": "v1" if program_id else "",
            "profile": report.get("execution_payload_preview") if isinstance(report.get("execution_payload_preview"), dict) else {},
        },
        "screen_checks": execution.get("screen_checks") if isinstance(execution.get("screen_checks"), list) else [],
        "physical_checks": physical_checks,
        "data_acquisition": data_acquisition,
        "cross_checks": dict(cross_checks),
        "artifact_refs": artifact_refs,
        "screen_evidence_refs": screen_refs,
        "data_evidence_refs": data_refs,
        "artifact_pull": execution.get("artifact_pull") if isinstance(execution.get("artifact_pull"), dict) else {},
        "live_evidence_audit": live_evidence_audit,
        "visual_verification": visual_verification,
        "physical_verification": physical_verification,
        "data_ledger": data_ledger,
        "handoff_gate": handoff_gate,
        "safety_gate": safety_gate,
        "decision": {
            "equipment_status": equipment_status,
            "handoff_status": status,
            "failure_code": failure_code,
            "blocking_reasons": handoff_gate["blocking_reasons"],
            "recommended_next_agent": "analysis_agent" if verified else "guardian_agent",
        },
    }
    packet = {
        "schema": "utm_data_ready.v1",
        "run_id": run_id_value,
        "specimen_id": specimen_id,
        "producer_agent": "lab_equipment_agent",
        "consumer_agent": "analysis_agent",
        "created_at": created_at,
        "status": "ready" if verified else "blocked",
        "evidence_refs": artifact_refs,
        "data_evidence_refs": data_refs,
        "screen_evidence_refs": screen_refs,
        "live_evidence_audit": live_evidence_audit,
        "save_export_responsibility_ok": bool(cross_checks.get("save_export_responsibility_ok")),
        "save_export": save_export,
        "artifact_pull": execution.get("artifact_pull") if isinstance(execution.get("artifact_pull"), dict) else {},
        "bridge_request_log_ref": request_audit_log.get("path", ""),
        "bridge_request_log_execute_event_seen": bool(request_audit_log.get("execute_event_seen")),
        "bridge_request_log_execute_run_ids": request_audit_log.get("execute_run_ids", []),
        "bridge_request_log_execute_sequence_ids": request_audit_log.get("execute_sequence_ids", []),
        "bridge_request_log_execute_specimen_ids": request_audit_log.get("execute_specimen_ids", []),
        "bridge_request_log_execute_program_ids": request_audit_log.get("execute_program_ids", []),
        "bridge_request_log_execute_identity_match": bool(request_audit_log.get("execute_identity_match")),
        "bridge_request_log_execute_identity_detail": request_audit_log.get("execute_identity_detail", {}),
        "guardian_status": "allow" if verified else "block",
        "decisions": [report_packet["decision"]],
        "warnings": [] if verified else [failure_code],
        "next_action": "analysis_agent" if verified else "guardian_review",
        "equipment_report": report_packet,
        "control_trace": {
            "bridge_provider": "windows_pyautogui",
            "connection_status": bridge_report["connection_status"],
            "program_id": program_id,
            "sequence_id": sequence_id,
            "macro_version": report_packet["control_plan"]["macro_version"],
            "source": "lab_equipment_utm_live_validation",
        },
        "visual_verification": visual_verification,
        "physical_verification": physical_verification,
        "data_ledger": data_ledger,
        "handoff_gate": handoff_gate,
        "safety_gate": safety_gate,
        "result_file": result_file,
        "utm_csv_path": result_file,
    }
    handoff = {
        "schema": "utm_data_ready.v1",
        "status": status,
        "bridge": "windows_pyautogui",
        "program_id": program_id,
        "sequence_id": sequence_id,
        "result_file": result_file,
        "utm_csv_path": result_file,
        "failure_code": failure_code,
        "data_parse_probe_ok": bool(cross_checks.get("data_parse_probe_ok")),
        "artifact_refs": artifact_refs,
        "screen_evidence_refs": screen_refs,
        "data_evidence_refs": data_refs,
        "live_evidence_audit": live_evidence_audit,
        "save_export_responsibility_ok": bool(cross_checks.get("save_export_responsibility_ok")),
        "save_export": save_export,
        "data_ledger": data_ledger,
        "handoff_gate": handoff_gate,
        "safety_gate": safety_gate,
        "bridge_request_log_ref": request_audit_log.get("path", ""),
        "bridge_request_log_execute_event_seen": bool(request_audit_log.get("execute_event_seen")),
        "bridge_request_log_execute_run_ids": request_audit_log.get("execute_run_ids", []),
        "bridge_request_log_execute_sequence_ids": request_audit_log.get("execute_sequence_ids", []),
        "bridge_request_log_execute_specimen_ids": request_audit_log.get("execute_specimen_ids", []),
        "bridge_request_log_execute_program_ids": request_audit_log.get("execute_program_ids", []),
        "bridge_request_log_execute_identity_match": bool(request_audit_log.get("execute_identity_match")),
        "bridge_request_log_execute_identity_detail": request_audit_log.get("execute_identity_detail", {}),
    }
    equipment_result = dict(execution)
    equipment_result.update(
        {
            "ok": verified,
            "tool": str(execution.get("tool") or "equipment.pyautogui.run"),
            "status": equipment_status,
            "failure_code": failure_code,
            "bridge": "windows_pyautogui",
            "program_id": program_id,
            "sequence_id": sequence_id,
            "result_file": result_file,
            "utm_csv_path": result_file,
            "data_acquisition": data_acquisition,
            "cross_checks": dict(cross_checks),
            "equipment_report": report_packet,
            "utm_data_ready": packet,
            "equipment_handoff": handoff,
        }
    )
    return {
        "verified": verified,
        "equipment_result": equipment_result,
        "equipment_report": report_packet,
        "utm_data_ready": packet,
        "equipment_handoff": handoff,
        "evidence_audit": audit,
    }


def _windows_utm_evidence_audit_from_metadata(metadata: dict[str, object], *, run_id: str = "") -> dict[str, object]:
    """Return post-run UTM evidence gates without touching live hardware."""
    equipment_report = metadata.get("equipment_report") if isinstance(metadata.get("equipment_report"), dict) else {}
    equipment_result = metadata.get("equipment_result") if isinstance(metadata.get("equipment_result"), dict) else {}
    equipment_handoff = metadata.get("equipment_handoff") if isinstance(metadata.get("equipment_handoff"), dict) else {}
    utm_packet = metadata.get("utm_data_ready") if isinstance(metadata.get("utm_data_ready"), dict) else {}

    if not equipment_report:
        physical_validation = metadata.get("last_windows_utm_physical_validation") if isinstance(metadata.get("last_windows_utm_physical_validation"), dict) else {}
        if physical_validation and physical_validation.get("execute_sent") is True:
            return _windows_utm_evidence_audit_from_live_validation_report(physical_validation, run_id=run_id)
        raw_result = metadata.get("last_windows_utm_protocol_result") if isinstance(metadata.get("last_windows_utm_protocol_result"), dict) else metadata.get("last_windows_equipment_run_result") if isinstance(metadata.get("last_windows_equipment_run_result"), dict) else {}
        if raw_result and str(raw_result.get("program_id") or "").startswith("utm_"):
            return _windows_utm_evidence_audit_from_raw_result(raw_result, run_id=run_id)
        return {
            "ok": False,
            "tool": "equipment.pyautogui.live_evidence_audit",
            "status": "missing",
            "run_id": run_id,
            "bridge": "windows_pyautogui",
            "blockers": ["EQUIPMENT_REPORT_NOT_AVAILABLE"],
            "warnings": [],
            "gates": {},
            "live_evidence_audit": {},
            "proof_checklist": [],
            "proof_ready": False,
            "decision": {},
            "evidence_refs": [],
            "next_actions": ["Run the Lab Equipment Agent stage or load a completed run with equipment_report.v1."],
        }

    bridge = equipment_report.get("bridge") if isinstance(equipment_report.get("bridge"), dict) else {}
    cross_checks = equipment_report.get("cross_checks") if isinstance(equipment_report.get("cross_checks"), dict) else {}
    decision = equipment_report.get("decision") if isinstance(equipment_report.get("decision"), dict) else {}
    audit = equipment_report.get("live_evidence_audit") if isinstance(equipment_report.get("live_evidence_audit"), dict) else {}
    data_acquisition = equipment_report.get("data_acquisition") if isinstance(equipment_report.get("data_acquisition"), dict) else {}
    request_audit_source = audit.get("request_audit_log") if isinstance(audit.get("request_audit_log"), dict) else {}
    if not request_audit_source and isinstance(bridge, dict) and bridge.get("request_log_path"):
        request_audit_source = {
            "path": str(bridge.get("request_log_path") or ""),
            "event_count": bridge.get("request_log_event_count", 0),
            "recent_paths": bridge.get("request_log_recent_paths", []),
        }
    expected_specimen_id = str(
        equipment_handoff.get("specimen_id")
        or utm_packet.get("specimen_id")
        or equipment_report.get("specimen_id")
        or ""
    )
    request_audit_log, request_audit_failure = _request_audit_log_gate({
        **dict(request_audit_source),
        "request_audit_log": request_audit_source,
        "expected_run_id": str(equipment_report.get("run_id") or run_id or ""),
        "expected_sequence_id": str(equipment_handoff.get("sequence_id") or equipment_report.get("sequence_id") or ""),
        "expected_specimen_id": expected_specimen_id,
        "expected_program_id": str(equipment_handoff.get("program_id") or (equipment_report.get("control_plan") if isinstance(equipment_report.get("control_plan"), dict) else {}).get("program_id") or ""),
        "require_execute_identity_match": bool(audit.get("required_for_handoff")),
    })
    screen_refs = equipment_report.get("screen_evidence_refs") if isinstance(equipment_report.get("screen_evidence_refs"), list) else []
    data_refs = equipment_report.get("data_evidence_refs") if isinstance(equipment_report.get("data_evidence_refs"), list) else []
    artifact_refs = equipment_report.get("artifact_refs") if isinstance(equipment_report.get("artifact_refs"), list) else []

    blockers: list[str] = [str(item) for item in decision.get("blocking_reasons", []) if str(item or "").strip()] if isinstance(decision.get("blocking_reasons"), list) else []
    warnings: list[str] = []
    required_for_handoff = bool(audit.get("required_for_handoff"))

    save_export_audit = audit.get("save_export") if isinstance(audit.get("save_export"), dict) else {}
    source_live_validation_report = metadata.get("last_windows_utm_physical_validation") if isinstance(metadata.get("last_windows_utm_physical_validation"), dict) else {}
    file_evidence = _windows_utm_intermediate_file_evidence_gate(
        [str(item) for item in screen_refs],
        [str(item) for item in data_refs],
        equipment_report,
        equipment_result,
        source_live_validation_report,
    )
    required_screen_files_ok = bool(file_evidence["screen_ok"]) if required_for_handoff else True
    required_data_files_ok = bool(file_evidence["data_ok"]) if required_for_handoff else True
    physical_execute_ok, physical_execute_evidence = _physical_validation_identity_gate(
        source_live_validation_report,
        expected_run_id=str(equipment_report.get("run_id") or run_id or ""),
        expected_sequence_id=str(equipment_handoff.get("sequence_id") or equipment_report.get("sequence_id") or ""),
        expected_specimen_id=expected_specimen_id,
        expected_program_id=str(equipment_handoff.get("program_id") or (equipment_report.get("control_plan") if isinstance(equipment_report.get("control_plan"), dict) else {}).get("program_id") or ""),
    )
    gate_values = {
        "physical_live_execute": physical_execute_ok,
        "screen_started": bool(cross_checks.get("screen_started")),
        "physical_motion_started": bool(cross_checks.get("physical_motion_started")),
        "save_completed": bool(cross_checks.get("save_completed")),
        "data_file_created": bool(cross_checks.get("data_file_created") and required_data_files_ok),
        "data_parse_probe_ok": bool(cross_checks.get("data_parse_probe_ok") and (not required_for_handoff or file_evidence["data_probe_ok"])),
        "screen_evidence_complete": bool(cross_checks.get("screen_evidence_complete", not required_for_handoff) and required_screen_files_ok),
        "linux_artifact_pulled": bool(cross_checks.get("linux_artifact_pulled", not required_for_handoff) and required_data_files_ok),
        "save_export_responsibility_ok": bool(cross_checks.get("save_export_responsibility_ok", save_export_audit.get("ok", not required_for_handoff))),
        "vision_evidence_complete": bool(cross_checks.get("vision_evidence_complete", not required_for_handoff)),
        "request_audit_log_available": bool(request_audit_log.get("ok")),
        "request_audit_execute_identity_match": bool(request_audit_log.get("execute_identity_match")),
    }
    if required_for_handoff:
        for gate, ok in gate_values.items():
            if not ok:
                if gate == "request_audit_log_available" and request_audit_failure:
                    blockers.append(request_audit_failure)
                elif gate == "save_export_responsibility_ok":
                    blockers.append("UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED")
                else:
                    blockers.append(f"{gate.upper()}_REQUIRED")
        if str(data_acquisition.get("status") or "") != "pulled_to_linux":
            blockers.append("UTM_LINUX_ARTIFACT_PULL_REQUIRED")
        if not data_refs:
            blockers.append("UTM_DATA_EVIDENCE_REF_REQUIRED")
        if len(screen_refs) < 3:
            blockers.append("UTM_SCREEN_EVIDENCE_REFS_INCOMPLETE")
        blockers.extend(str(item) for item in file_evidence.get("blockers", []) if str(item or "").strip())
        if not physical_execute_ok:
            blockers.append("UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED")
            if physical_execute_evidence.get("missing_identity_fields"):
                blockers.append("UTM_PHYSICAL_LIVE_EXECUTE_IDENTITY_REQUIRED")
            if physical_execute_evidence.get("mismatched_identity_fields"):
                blockers.append("UTM_PHYSICAL_LIVE_EXECUTE_IDENTITY_MISMATCH")
    else:
        warnings.append("LIVE_WINDOWS_UTM_AUDIT_NOT_REQUIRED_FOR_THIS_REPORT")

    handoff_status = str(decision.get("handoff_status") or equipment_handoff.get("status") or "")
    equipment_status = str(decision.get("equipment_status") or equipment_result.get("status") or "")
    failure_code = str(decision.get("failure_code") or equipment_result.get("failure_code") or "")
    blockers = list(dict.fromkeys(item for item in blockers if item))
    status = "ready_for_analysis" if not blockers and handoff_status == "ready_for_analysis" else "blocked" if blockers else handoff_status or equipment_status or "unknown"

    proof_checklist, proof_ready = _windows_utm_proof_checklist(
        gates=gate_values,
        request_audit_log=request_audit_log,
        screen_refs=list(screen_refs),
        data_refs=list(data_refs),
        data_acquisition=data_acquisition,
        blockers=blockers,
        source="equipment_report",
    )

    next_actions = []
    if "UTM_SCREEN_EVIDENCE_INCOMPLETE" in blockers or "SCREEN_EVIDENCE_COMPLETE_REQUIRED" in blockers or "UTM_SCREEN_EVIDENCE_REFS_INCOMPLETE" in blockers:
        next_actions.append("Verify UTM locators and rerun the protocol until before/start/complete screenshots are captured.")
    if "UTM_LINUX_ARTIFACT_PULL_REQUIRED" in blockers or "LINUX_ARTIFACT_PULLED_REQUIRED" in blockers or "UTM_DATA_EVIDENCE_REF_REQUIRED" in blockers:
        next_actions.append("Pull the UTM CSV through the Windows artifact endpoint and confirm a Linux-local path is recorded.")
    if "UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED" in blockers or "SAVE_EXPORT_RESPONSIBILITY_OK_REQUIRED" in blockers:
        next_actions.append("Confirm the UTM save/export method, save attempt, and Windows/Linux export paths before Analysis handoff.")
    if "UTM_VISION_EVIDENCE_FRAMES_REQUIRED" in blockers or "VISION_EVIDENCE_COMPLETE_REQUIRED" in blockers:
        next_actions.append("Refresh Vision cross-checks and preserve frame IDs for pre-start, motion, and complete states.")
    if "UTM_REQUEST_LOG_REQUIRED" in blockers or "UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED" in blockers:
        next_actions.append("Inspect the Windows bridge request log and confirm the live /execute request was recorded.")
    if failure_code and not next_actions:
        next_actions.append("Review the Equipment report failure/recovery table before retrying.")

    return {
        "ok": not blockers and status == "ready_for_analysis",
        "tool": "equipment.pyautogui.live_evidence_audit",
        "status": status,
        "run_id": run_id,
        "bridge": bridge.get("provider", "windows_pyautogui"),
        "program_id": (equipment_report.get("control_plan") or {}).get("program_id", equipment_result.get("program_id", "")) if isinstance(equipment_report.get("control_plan"), dict) else equipment_result.get("program_id", ""),
        "handoff_status": handoff_status,
        "equipment_status": equipment_status,
        "failure_code": failure_code or None,
        "required_for_handoff": required_for_handoff,
        "gates": gate_values,
        "live_evidence_audit": audit,
        "request_audit_log": request_audit_log,
        "physical_execution": physical_execute_evidence,
        "file_evidence": file_evidence,
        "proof_checklist": proof_checklist,
        "proof_ready": proof_ready,
        "decision": decision,
        "data_acquisition": data_acquisition,
        "evidence_refs": list(dict.fromkeys(str(item) for item in [*artifact_refs, *screen_refs, *data_refs] if str(item or "").strip())),
        "screen_evidence_refs": [str(item) for item in screen_refs],
        "data_evidence_refs": [str(item) for item in data_refs],
        "source_live_validation_report": source_live_validation_report,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": next_actions,
    }


_DEFAULT_REQUIRED_UTM_LOCATORS = ("ready_state", "start_button", "running_state", "complete_state")


def _required_utm_locator_names(runtime_profile: dict[str, object]) -> list[str]:
    """Infer screen-control locator names required by the configured UTM protocol."""
    sequence = runtime_profile.get("sequence") if isinstance(runtime_profile.get("sequence"), list) else []
    names: list[str] = []
    for action in sequence:
        if not isinstance(action, dict):
            continue
        action_name = str(action.get("action") or "").strip()
        if action_name not in {"assert_visible", "wait_until", "click"}:
            continue
        target = str(action.get("target") or action.get("name") or "").strip()
        if target and target not in names:
            names.append(target)
    if not names:
        names = list(_DEFAULT_REQUIRED_UTM_LOCATORS)
    return names


def _configured_locator_names(locators: object) -> list[str]:
    if isinstance(locators, dict):
        return sorted(str(name) for name, value in locators.items() if isinstance(value, dict))
    return []


def _windows_utm_readiness_from_bridge(
    bridge: WindowsPyAutoGUIBridge,
    runtime_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return passive UTM readiness without touching live hardware endpoints."""
    overrides = runtime_overrides if isinstance(runtime_overrides, dict) else {}
    connection = bridge.connection_status()
    programs = bridge.list_programs({"runtime_mode": "test"})
    profile_status = bridge.utm_profile_status()
    profile = profile_status.get("profile") if isinstance(profile_status.get("profile"), dict) else {}
    program_id = str(overrides.get("program_id") or profile.get("program_id") or "utm_compression_start_v1")
    program_list = programs.get("programs") if isinstance(programs.get("programs"), list) else []
    program_ids = {str(item.get("program_id")) for item in program_list if isinstance(item, dict) and item.get("program_id")}
    runtime_profile: dict[str, object]
    runtime_payload_builder = getattr(bridge, "_runtime_program_payload", None)
    if callable(runtime_payload_builder):
        runtime_profile = runtime_payload_builder({"program_id": program_id, "runtime_mode": "live"})
    else:
        runtime_profile = dict(profile)
        runtime_profile.setdefault("program_id", program_id)
    for key, value in overrides.items():
        if key in {"sequence", "locators"}:
            if value:
                runtime_profile[key] = value
            continue
        if value not in (None, ""):
            runtime_profile[key] = value
    locators = runtime_profile.get("locators") if isinstance(runtime_profile.get("locators"), dict) else {}
    export_glob = str(runtime_profile.get("export_glob") or profile.get("export_glob") or "").strip()
    require_screen = bool(runtime_profile.get("require_screen_assertions", profile.get("require_screen_assertions", False)))
    simulate = bool(runtime_profile.get("simulate_utm_protocol", profile.get("simulate_utm_protocol", False)))
    required_locator_names = _required_utm_locator_names(runtime_profile)
    configured_locator_names = _configured_locator_names(locators)
    missing_required_locators = [name for name in required_locator_names if name not in set(configured_locator_names)]

    blockers: list[str] = []
    warnings: list[str] = []
    if not bool(connection.get("selected")):
        blockers.append("PYAUTOGUI_BRIDGE_NOT_SELECTED")
    if not bool(connection.get("token_configured")):
        blockers.append("PYAUTOGUI_TOKEN_MISSING")
    if program_id not in program_ids:
        blockers.append("UTM_PROGRAM_NOT_REGISTERED")
    if not export_glob:
        blockers.append("UTM_EXPORT_GLOB_MISSING")
    if require_screen and missing_required_locators:
        blockers.append("UTM_REQUIRED_LOCATORS_MISSING")
    if profile_status.get("source") != "memory":
        warnings.append("UTM_PROFILE_USING_REGISTERED_DEFAULTS")
    if not locators:
        warnings.append("UTM_LOCATORS_NOT_CAPTURED")
    elif missing_required_locators:
        warnings.append("UTM_LOCATOR_SET_INCOMPLETE")
    if not require_screen:
        warnings.append("UTM_SCREEN_ASSERTIONS_NOT_REQUIRED")
    if simulate:
        warnings.append("UTM_PROFILE_SIMULATION_ENABLED")

    status = "blocked" if blockers else "warning" if warnings else "ready"
    next_actions = [
        "Select a token-verified Windows bridge candidate." if "PYAUTOGUI_BRIDGE_NOT_SELECTED" in blockers else "",
        "Save the bridge token with the selected candidate." if "PYAUTOGUI_TOKEN_MISSING" in blockers else "",
        f"Register program {program_id}." if "UTM_PROGRAM_NOT_REGISTERED" in blockers else "",
        "Set the UTM export glob for the CSV file." if "UTM_EXPORT_GLOB_MISSING" in blockers else "",
        f"Capture required UTM locators: {', '.join(missing_required_locators)}." if "UTM_REQUIRED_LOCATORS_MISSING" in blockers else "",
        "Capture UTM screen locators and enable screen assertions before live autonomous UTM." if "UTM_LOCATORS_NOT_CAPTURED" in warnings or "UTM_SCREEN_ASSERTIONS_NOT_REQUIRED" in warnings else "",
        "Disable bench simulation before live UTM." if "UTM_PROFILE_SIMULATION_ENABLED" in warnings else "",
    ]
    return {
        "ok": not blockers,
        "tool": "equipment.pyautogui.utm_readiness",
        "status": status,
        "bridge": "windows_pyautogui",
        "program_id": program_id,
        "ready_for_setup_test": not blockers,
        "ready_for_autonomous_profile": not blockers and require_screen and bool(locators) and not missing_required_locators and not simulate,
        "runtime_overrides_applied": bool(overrides),
        "blockers": blockers,
        "warnings": warnings,
        "gates": {
            "connection_saved": bool(connection.get("selected")),
            "token_configured": bool(connection.get("token_configured")),
            "utm_program_registered": program_id in program_ids,
            "export_glob_configured": bool(export_glob),
            "locator_count": len(locators),
            "locator_names": configured_locator_names,
            "required_locator_names": required_locator_names,
            "missing_required_locators": missing_required_locators,
            "required_locators_complete": not missing_required_locators,
            "require_screen_assertions": require_screen,
            "simulate_utm_protocol": simulate,
            "profile_source": str(profile_status.get("source") or ""),
            "profile_memory_path": str(profile_status.get("profile_memory_path") or ""),
        },
        "next_actions": [item for item in next_actions if item],
    }


def _windows_bridge_request_log_from_bridge(
    bridge: WindowsPyAutoGUIBridge,
    *,
    runtime_mode: str = "live",
    confirm_live: bool = False,
) -> dict[str, object]:
    """Retrieve bridge request-audit events; live mode is non-actuating but explicit."""
    mode = "live" if str(runtime_mode).strip().lower() == "live" else "test"
    if mode == "live" and not confirm_live:
        return {
            "ok": False,
            "tool": "equipment.pyautogui.request_log",
            "status": "blocked",
            "bridge": "windows_pyautogui",
            "failure_code": "PYAUTOGUI_REQUEST_LOG_CONFIRMATION_REQUIRED",
            "message": "confirm_live=true is required before contacting the live Windows bridge request-log endpoint.",
            "events": [],
            "event_count": 0,
        }
    payload = {"runtime_mode": mode}
    if mode == "live":
        payload["force_live_bridge"] = True
    result = bridge.request_log(payload)
    events = result.get("events") if isinstance(result.get("events"), list) else []
    sanitized_events: list[dict[str, object]] = []
    for event in events[-100:]:
        if not isinstance(event, dict):
            continue
        sanitized_events.append(
            {
                key: value
                for key, value in event.items()
                if "token" not in str(key).lower() or str(key).lower() in {"token_auth_enabled", "token_header_present"}
            }
        )
    result["events"] = sanitized_events
    result["event_count"] = int(result.get("event_count") or len(sanitized_events))
    result.setdefault("request_log", result.get("request_log") or "")
    result.setdefault("non_actuating", True)
    return result



def _windows_utm_proof_package_from_metadata(
    metadata: dict[str, object],
    *,
    run_id: str = "",
    passive_readiness: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a single operator/audit package for live Windows UTM proof review."""
    evidence_audit = _windows_utm_evidence_audit_from_metadata(metadata, run_id=run_id)
    checklist = evidence_audit.get("proof_checklist") if isinstance(evidence_audit.get("proof_checklist"), list) else []
    required_items = [item for item in checklist if isinstance(item, dict) and item.get("required") is not False]
    missing_items = [item for item in required_items if item.get("ok") is not True]
    evidence_refs = [str(item) for item in evidence_audit.get("evidence_refs", []) if str(item or "").strip()] if isinstance(evidence_audit.get("evidence_refs"), list) else []
    screen_refs = [str(item) for item in evidence_audit.get("screen_evidence_refs", []) if str(item or "").strip()] if isinstance(evidence_audit.get("screen_evidence_refs"), list) else []
    data_refs = [str(item) for item in evidence_audit.get("data_evidence_refs", []) if str(item or "").strip()] if isinstance(evidence_audit.get("data_evidence_refs"), list) else []
    live_audit = evidence_audit.get("live_evidence_audit") if isinstance(evidence_audit.get("live_evidence_audit"), dict) else {}
    vision_evidence = live_audit.get("vision_evidence") if isinstance(live_audit.get("vision_evidence"), dict) else {}
    vision_frame_ids = [str(item) for item in vision_evidence.get("evidence_frame_ids", []) if str(item or "").strip()] if isinstance(vision_evidence.get("evidence_frame_ids"), list) else []
    request_audit = evidence_audit.get("request_audit_log") if isinstance(evidence_audit.get("request_audit_log"), dict) else {}
    save_export = live_audit.get("save_export") if isinstance(live_audit.get("save_export"), dict) else {}
    data_acquisition = evidence_audit.get("data_acquisition") if isinstance(evidence_audit.get("data_acquisition"), dict) else {}
    blockers = [str(item) for item in evidence_audit.get("blockers", []) if str(item or "").strip()] if isinstance(evidence_audit.get("blockers"), list) else []
    warnings = [str(item) for item in evidence_audit.get("warnings", []) if str(item or "").strip()] if isinstance(evidence_audit.get("warnings"), list) else []
    proof_ready = bool(evidence_audit.get("proof_ready"))
    ready_for_analysis = proof_ready and str(evidence_audit.get("status") or "") == "ready_for_analysis"
    last_preflight = metadata.get("last_windows_live_preflight_result") if isinstance(metadata.get("last_windows_live_preflight_result"), dict) else {}
    last_result = metadata.get("last_windows_utm_protocol_result") if isinstance(metadata.get("last_windows_utm_protocol_result"), dict) else metadata.get("last_windows_equipment_run_result") if isinstance(metadata.get("last_windows_equipment_run_result"), dict) else {}
    last_live_validation = metadata.get("last_windows_utm_live_validation") if isinstance(metadata.get("last_windows_utm_live_validation"), dict) else {}
    last_physical_validation = metadata.get("last_windows_utm_physical_validation") if isinstance(metadata.get("last_windows_utm_physical_validation"), dict) else {}
    source_packets = {
        "equipment_report": metadata.get("equipment_report") if isinstance(metadata.get("equipment_report"), dict) else {},
        "utm_data_ready": metadata.get("utm_data_ready") if isinstance(metadata.get("utm_data_ready"), dict) else {},
        "equipment_handoff": metadata.get("equipment_handoff") if isinstance(metadata.get("equipment_handoff"), dict) else {},
        "last_windows_utm_live_validation": last_live_validation,
        "last_windows_utm_physical_validation": last_physical_validation,
    }
    physical_evidence = evidence_audit.get("physical_execution") if isinstance(evidence_audit.get("physical_execution"), dict) else {}
    physical_execution_ok = bool(physical_evidence.get("dispatch_ok") is True and physical_evidence.get("identity_ok") is True)
    physical_execution = {
        "ok": physical_execution_ok,
        "source": "last_windows_utm_physical_validation" if last_physical_validation else "missing",
        "requested_physical_execute": bool(last_physical_validation.get("requested_physical_execute")),
        "execute_sent": bool(last_physical_validation.get("execute_sent")),
        "non_actuating": bool(last_physical_validation.get("non_actuating", True)),
        "status": str(last_physical_validation.get("status") or ""),
        "run_id": str(last_physical_validation.get("run_id") or ""),
        "sequence_id": str(last_physical_validation.get("sequence_id") or ""),
        "specimen_id": str(last_physical_validation.get("specimen_id") or ""),
        "program_id": str(last_physical_validation.get("program_id") or ""),
        "dispatch_ok": bool(physical_evidence.get("dispatch_ok")),
        "identity_ok": bool(physical_evidence.get("identity_ok")),
        "expected_identity": physical_evidence.get("expected", {}),
        "observed_identity": physical_evidence.get("observed", {}),
        "missing_identity_fields": physical_evidence.get("missing_identity_fields", []),
        "mismatched_identity_fields": physical_evidence.get("mismatched_identity_fields", []),
    }
    if not physical_execution_ok and "UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED" not in blockers:
        blockers.append("UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED")
    if physical_execution.get("missing_identity_fields") and "UTM_PHYSICAL_LIVE_EXECUTE_IDENTITY_REQUIRED" not in blockers:
        blockers.append("UTM_PHYSICAL_LIVE_EXECUTE_IDENTITY_REQUIRED")
    if physical_execution.get("mismatched_identity_fields") and "UTM_PHYSICAL_LIVE_EXECUTE_IDENTITY_MISMATCH" not in blockers:
        blockers.append("UTM_PHYSICAL_LIVE_EXECUTE_IDENTITY_MISMATCH")
    physical_item = {
        "id": "physical_live_execute",
        "label": "Physical live /execute dispatch",
        "ok": physical_execution_ok,
        "required": True,
        "detail": "requires Run Physical Validation with execute_sent=true, non_actuating=false, status=verified_complete, and matching run/sequence/specimen/program identity",
        "source": "proof_package_manifest",
    }
    checklist = [physical_item, *[item for item in checklist if not (isinstance(item, dict) and item.get("id") == "physical_live_execute")]]
    required_items = [item for item in checklist if isinstance(item, dict) and item.get("required") is not False]
    missing_items = [item for item in required_items if item.get("ok") is not True]
    proof_ready = bool(proof_ready and physical_execution_ok)
    ready_for_analysis = bool(ready_for_analysis and physical_execution_ok and not blockers)
    manifest = {
        "physical_execution": physical_execution,
        "request_log": {
            "path": str(request_audit.get("path") or request_audit.get("request_log") or ""),
            "event_count": int(request_audit.get("event_count") or 0),
            "execute_event_seen": bool(request_audit.get("execute_event_seen")),
            "execute_event_count": int(request_audit.get("execute_event_count") or 0),
            "last_execute_at": str(request_audit.get("last_execute_at") or ""),
            "execute_payload_event_count": int(request_audit.get("execute_payload_event_count") or 0),
            "execute_result_event_count": int(request_audit.get("execute_result_event_count") or 0),
            "execute_run_ids": request_audit.get("execute_run_ids", []),
            "execute_sequence_ids": request_audit.get("execute_sequence_ids", []),
            "execute_specimen_ids": request_audit.get("execute_specimen_ids", []),
            "execute_program_ids": request_audit.get("execute_program_ids", []),
            "execute_identity_required": bool(request_audit.get("execute_identity_required")),
            "execute_identity_present": bool(request_audit.get("execute_identity_present")),
            "execute_identity_match": bool(request_audit.get("execute_identity_match")),
            "execute_identity_detail": request_audit.get("execute_identity_detail", {}),
        },
        "screen_evidence_refs": screen_refs,
        "screen_evidence_count": len(screen_refs),
        "data_evidence_refs": data_refs,
        "data_evidence_count": len(data_refs),
        "evidence_refs": list(dict.fromkeys(evidence_refs + screen_refs + data_refs)),
        "linux_data_path": str(data_acquisition.get("linux_path") or data_acquisition.get("local_path") or ""),
        "data_status": str(data_acquisition.get("status") or ""),
        "row_count_probe": data_acquisition.get("row_count_probe"),
        "save_export": {
            "ok": bool(save_export.get("ok")),
            "save_method": str(save_export.get("save_method") or data_acquisition.get("save_method") or ""),
            "save_attempted_by_agent": bool(save_export.get("save_attempted_by_agent", data_acquisition.get("save_attempted_by_agent"))),
            "save_confirmation_screen_ok": bool(save_export.get("save_confirmation_screen_ok", data_acquisition.get("save_confirmation_screen_ok"))),
            "windows_path": str(save_export.get("windows_path") or data_acquisition.get("windows_path") or ""),
            "linux_path": str(save_export.get("linux_path") or data_acquisition.get("linux_path") or data_acquisition.get("local_path") or ""),
            "recognized_save_method": bool(save_export.get("recognized_save_method")),
        },
        "vision_frame_ids": vision_frame_ids,
        "vision_frame_count": len(vision_frame_ids),
    }
    next_actions = [str(item) for item in evidence_audit.get("next_actions", []) if str(item or "").strip()] if isinstance(evidence_audit.get("next_actions"), list) else []
    if missing_items:
        next_actions = [
            "Resolve missing proof checklist items before Analysis handoff: " + ", ".join(str(item.get("id") or item.get("label") or "proof") for item in missing_items),
            *next_actions,
        ]
    elif ready_for_analysis:
        next_actions = ["Proof package is ready for Analysis handoff review.", *next_actions]
    return {
        "ok": ready_for_analysis,
        "tool": "equipment.pyautogui.live_proof_package",
        "status": "ready_for_analysis" if ready_for_analysis else "incomplete",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": run_id,
        "bridge": "windows_pyautogui",
        "ready_for_analysis": ready_for_analysis,
        "proof_ready": proof_ready,
        "required_item_count": len(required_items),
        "missing_required_item_count": len(missing_items),
        "missing_required_items": [
            {
                "id": str(item.get("id") or ""),
                "label": str(item.get("label") or item.get("id") or ""),
                "detail": str(item.get("detail") or ""),
            }
            for item in missing_items
        ],
        "proof_checklist": checklist,
        "evidence_audit": evidence_audit,
        "passive_readiness": passive_readiness or {},
        "last_live_preflight": last_preflight,
        "last_windows_utm_result": last_result,
        "last_windows_utm_live_validation": last_live_validation,
        "last_windows_utm_physical_validation": last_physical_validation,
        "source_packets": source_packets,
        "manifest": manifest,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": list(dict.fromkeys(next_actions)),
    }



def _persist_windows_utm_proof_package(package: dict[str, object]) -> dict[str, object]:
    """Persist the Windows UTM proof package as a run-local JSON artifact."""
    run_id = str(package.get("run_id") or controller._state.run_id or "run").strip() or "run"
    safe_run_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id).strip("._-")[:96] or "run"
    artifact_dir = resolve_path("artifacts/equipment") / safe_run_id / "utm"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = artifact_dir / f"windows_utm_proof_package_{stamp}.json"
    artifact = {
        "kind": "windows_utm_proof_package",
        "content_type": "application/json",
        "filename": path.name,
        "path": str(path),
        "local_path": str(path),
        "run_id": run_id,
        "ready_for_analysis": bool(package.get("ready_for_analysis")),
        "proof_ready": bool(package.get("proof_ready")),
        "missing_required_item_count": int(package.get("missing_required_item_count") or 0),
    }
    package = dict(package)
    package["package_artifact"] = artifact
    manifest = package.get("manifest") if isinstance(package.get("manifest"), dict) else {}
    manifest = dict(manifest)
    manifest["proof_package_path"] = str(path)
    manifest["proof_package_filename"] = path.name
    package["manifest"] = manifest
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    try:
        artifact["size_bytes"] = path.stat().st_size
    except OSError:
        artifact["size_bytes"] = 0
    package["package_artifact"] = artifact
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return package



_WINDOWS_UTM_VISION_REQUIRED_CHECKS = ("utm_pre_start", "utm_motion_confirm", "utm_test_complete")
_WINDOWS_UTM_VISION_SIGNAL_TO_CHECK = {
    "specimen_on_utm_platen": "utm_pre_start",
    "fixture_alignment_ok": "utm_pre_start",
    "utm_motion_observed": "utm_motion_confirm",
    "utm_home_restored": "utm_test_complete",
}


def _windows_utm_vision_frame_ids(value: object) -> list[str]:
    """Collect frame-like evidence ids from a Vision payload without validating the files."""
    frames: list[str] = []

    def collect(item: object, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(item, dict):
            for key in ("frame_ids", "evidence_frame_ids", "frames"):
                values = item.get(key)
                if isinstance(values, list):
                    frames.extend(str(value) for value in values if str(value or "").strip())
                elif isinstance(values, str) and values.strip():
                    frames.append(values.strip())
            for key in ("frame_id", "observation_id", "image_id", "artifact_id"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    frames.append(value.strip())
            for value in item.values():
                collect(value, depth + 1)
        elif isinstance(item, list):
            for value in item:
                collect(value, depth + 1)

    collect(value)
    return list(dict.fromkeys(frames))


def _windows_utm_vision_truthy(value: object) -> bool:
    if value is True:
        return True
    if not isinstance(value, dict):
        return False
    if "ok" in value:
        return value.get("ok") is True
    if "ready" in value:
        return value.get("ready") is True
    status = str(value.get("status") or value.get("state") or "").strip().lower()
    return status in {"ok", "ready", "verified", "complete", "completed", "observed", "passed"}


def _windows_utm_vision_identity(value: object, *, run_id: str, specimen_id: str) -> dict[str, object]:
    payload = value if isinstance(value, dict) else {}
    nested = payload.get("identity") if isinstance(payload.get("identity"), dict) else {}
    observed = {
        "run_id": str(payload.get("run_id") or nested.get("run_id") or "").strip(),
        "specimen_id": str(payload.get("specimen_id") or nested.get("specimen_id") or "").strip(),
    }
    expected = {"run_id": str(run_id or "").strip(), "specimen_id": str(specimen_id or "").strip()}
    mismatched = [key for key, expected_value in expected.items() if expected_value and observed.get(key) and observed[key] != expected_value]
    missing = [key for key, expected_value in expected.items() if expected_value and not observed.get(key)]
    return {
        "expected": expected,
        "observed": observed,
        "match": not mismatched,
        "missing_fields": missing,
        "mismatched_fields": mismatched,
    }


def _windows_utm_normalize_vision_candidate(check_id: str, value: object, *, source: str, run_id: str, specimen_id: str) -> dict[str, object]:
    payload = value if isinstance(value, dict) else {"ok": value}
    confidence_value = payload.get("confidence") if isinstance(payload, dict) else None
    confidence: float | None = None
    if confidence_value not in (None, ""):
        try:
            confidence = float(confidence_value)
        except Exception:
            confidence = None
    identity = _windows_utm_vision_identity(payload, run_id=run_id, specimen_id=specimen_id)
    ok = _windows_utm_vision_truthy(payload)
    if confidence is not None and confidence < 0.6:
        ok = False
    if identity.get("missing_fields") or identity.get("mismatched_fields"):
        ok = False
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    frame_ids = _windows_utm_vision_frame_ids(payload)
    normalized: dict[str, object] = {
        "ok": bool(ok),
        "source": source,
        "confidence": confidence if confidence is not None else payload.get("confidence", ""),
        "identity": identity,
        "evidence": evidence,
        "frame_ids": frame_ids,
    }
    for key in ("timestamp", "expires_at", "freshness_ttl_ms", "signals", "status", "state", "message"):
        if isinstance(payload, dict) and key in payload:
            normalized[key] = payload[key]
    return normalized


def _windows_utm_vision_proof_draft(
    metadata: dict[str, object],
    *,
    observations: dict[str, object] | None = None,
    run_id: str = "",
    specimen_id: str = "",
) -> dict[str, object]:
    """Build a non-actuating Vision proof JSON draft from current runtime evidence."""
    observations = observations if isinstance(observations, dict) else {}

    def nested_value(payload: object, *keys: str) -> str:
        current = payload
        for key in keys:
            if not isinstance(current, dict):
                return ""
            current = current.get(key)
        return str(current or "").strip()

    resolved_run_id = str(run_id or controller._state.run_id or nested_value(metadata.get("equipment_report"), "run_id") or "utm-live-validation").strip() or "utm-live-validation"
    resolved_specimen_id = str(
        specimen_id
        or nested_value(metadata.get("equipment_report"), "specimen_id")
        or nested_value(metadata.get("equipment_handoff"), "specimen_id")
        or nested_value(metadata.get("utm_data_ready"), "specimen_id")
        or nested_value(metadata.get("last_windows_utm_physical_validation"), "specimen_id")
        or "specimen-live-validation"
    ).strip() or "specimen-live-validation"

    candidates: dict[str, list[dict[str, object]]] = {check_id: [] for check_id in _WINDOWS_UTM_VISION_REQUIRED_CHECKS}

    def add_candidate(check_id: str, value: object, source: str) -> None:
        if check_id not in candidates:
            return
        candidates[check_id].append(
            _windows_utm_normalize_vision_candidate(
                check_id,
                value,
                source=source,
                run_id=resolved_run_id,
                specimen_id=resolved_specimen_id,
            )
        )

    def scan(value: object, source: str, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(value, dict):
            checks = value.get("checks")
            if isinstance(checks, dict):
                for check_id in _WINDOWS_UTM_VISION_REQUIRED_CHECKS:
                    if check_id in checks:
                        add_candidate(check_id, checks[check_id], f"{source}.checks.{check_id}")
            check_id = str(value.get("check_id") or "").strip()
            if check_id in candidates:
                add_candidate(check_id, value, f"{source}.check_id")
            signal = str(value.get("signal") or value.get("signal_id") or "").strip()
            mapped = _WINDOWS_UTM_VISION_SIGNAL_TO_CHECK.get(signal)
            if mapped:
                add_candidate(mapped, value, f"{source}.signal.{signal}")
            for check_id in _WINDOWS_UTM_VISION_REQUIRED_CHECKS:
                if check_id in value:
                    add_candidate(check_id, value[check_id], f"{source}.{check_id}")
            for key, child in value.items():
                scan(child, f"{source}.{key}", depth + 1)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan(child, f"{source}[{index}]", depth + 1)

    scan(metadata, "run_metadata")
    scan(observations, "latest_observations")

    selected_checks: dict[str, dict[str, object]] = {}
    blockers: list[str] = []
    warnings: list[str] = []
    all_frame_ids: list[str] = []
    candidate_counts: dict[str, int] = {}
    for check_id in _WINDOWS_UTM_VISION_REQUIRED_CHECKS:
        values = candidates.get(check_id, [])
        candidate_counts[check_id] = len(values)
        values.sort(
            key=lambda item: (
                item.get("ok") is True,
                len(item.get("frame_ids", [])) if isinstance(item.get("frame_ids"), list) else 0,
                float(item.get("confidence") or 0.0) if str(item.get("confidence") or "").replace(".", "", 1).isdigit() else 0.0,
            ),
            reverse=True,
        )
        selected = dict(values[0]) if values else {"ok": False, "source": "missing", "confidence": "", "identity": {}, "evidence": {}, "frame_ids": []}
        selected_checks[check_id] = selected
        frame_ids = selected.get("frame_ids") if isinstance(selected.get("frame_ids"), list) else []
        all_frame_ids.extend(str(frame_id) for frame_id in frame_ids if str(frame_id or "").strip())
        if selected.get("ok") is not True:
            blockers.append(f"VISION_{check_id.upper()}_REQUIRED")
        identity = selected.get("identity") if isinstance(selected.get("identity"), dict) else {}
        missing_identity = identity.get("missing_fields") if isinstance(identity.get("missing_fields"), list) else []
        if missing_identity and selected.get("source") != "missing":
            warnings.append(f"VISION_{check_id.upper()}_IDENTITY_FIELDS_NOT_PRESENT: {', '.join(str(item) for item in missing_identity)}")

    all_frame_ids = list(dict.fromkeys(all_frame_ids or _windows_utm_vision_frame_ids({"metadata": metadata, "observations": observations})))
    if len(all_frame_ids) < len(_WINDOWS_UTM_VISION_REQUIRED_CHECKS):
        blockers.append("VISION_FRAME_IDS_REQUIRED")

    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    ready = not blockers
    vision_proof = {
        "ok": ready,
        "run_id": resolved_run_id,
        "specimen_id": resolved_specimen_id,
        "checks": selected_checks,
        "evidence": {"frame_ids": all_frame_ids},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "runtime_vision_proof_draft",
    }
    return {
        "ok": ready,
        "tool": "equipment.pyautogui.vision_proof_draft",
        "status": "ready" if ready else "incomplete",
        "non_actuating": True,
        "run_id": resolved_run_id,
        "specimen_id": resolved_specimen_id,
        "required_checks": list(_WINDOWS_UTM_VISION_REQUIRED_CHECKS),
        "candidate_counts": candidate_counts,
        "vision_proof": vision_proof,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": ["Paste the generated vision_proof into physical live validation."] if ready else ["Attach real Vision Agent evidence for every required UTM check before physical validation."],
    }



def _persist_windows_utm_completion_audit(result: dict[str, object]) -> dict[str, object]:
    """Persist the Improvement 05 completion audit as a run-local JSON artifact."""
    verification = result.get("verification") if isinstance(result.get("verification"), dict) else {}
    run_id = str(verification.get("run_id") or controller._state.run_id or result.get("run_id") or "run").strip() or "run"
    safe_run_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id).strip("._-")[:96] or "run"
    artifact_dir = resolve_path("artifacts/equipment") / safe_run_id / "utm"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = artifact_dir / f"windows_utm_completion_audit_{stamp}.json"
    artifact = {
        "kind": "windows_utm_completion_audit",
        "content_type": "application/json",
        "filename": path.name,
        "path": str(path),
        "local_path": str(path),
        "run_id": run_id,
        "status": str(result.get("status") or ""),
        "ok": bool(result.get("ok")),
        "blocker_count": len(result.get("blockers", [])) if isinstance(result.get("blockers"), list) else 0,
    }
    persisted = dict(result)
    persisted["audit_artifact"] = artifact
    persisted["artifact"] = artifact
    path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    try:
        artifact["size_bytes"] = path.stat().st_size
    except OSError:
        artifact["size_bytes"] = 0
    persisted["audit_artifact"] = artifact
    persisted["artifact"] = artifact
    path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return persisted


def _persist_windows_utm_live_validation(report: dict[str, object]) -> dict[str, object]:
    """Persist the non-actuating Windows UTM live validation report as a JSON artifact."""
    run_id = str(report.get("run_id") or controller._state.run_id or "run").strip() or "run"
    safe_run_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id).strip("._-")[:96] or "run"
    artifact_dir = resolve_path("artifacts/equipment") / safe_run_id / "live_validation"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / "lab_equipment_utm_live_validation.json"
    artifact = {
        "kind": "lab_equipment_utm_live_validation",
        "content_type": "application/json",
        "filename": path.name,
        "path": str(path),
        "local_path": str(path),
        "run_id": run_id,
        "status": str(report.get("status") or ""),
        "non_actuating": bool(report.get("non_actuating", True)),
    }
    persisted = dict(report)
    persisted["report_artifact"] = artifact
    persisted["artifact"] = artifact
    path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    try:
        artifact["size_bytes"] = path.stat().st_size
    except OSError:
        artifact["size_bytes"] = 0
    persisted["report_artifact"] = artifact
    persisted["artifact"] = artifact
    path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return persisted


def _windows_proof_checkable_path(value: object) -> Path | None:
    """Return a local filesystem path for refs that are checkable on this host."""
    raw = str(value or "").strip()
    if not raw or "://" in raw:
        return None
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return Path(raw).expanduser()
    if raw.startswith("/") or raw.startswith("~"):
        return Path(raw).expanduser()
    if raw.startswith("artifacts/") or raw.startswith("./artifacts/"):
        return resolve_path(raw[2:] if raw.startswith("./") else raw)
    return None


def _windows_proof_image_signature(path: Path) -> tuple[bool, str]:
    """Check that a screen evidence file looks like an actual image artifact."""
    try:
        header = path.read_bytes()[:16]
    except OSError as exc:
        return False, str(exc)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return True, "png"
    if header.startswith(b"\xff\xd8\xff"):
        return True, "jpeg"
    if header.startswith(b"BM"):
        return True, "bmp"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return True, "gif"
    return False, "unsupported image signature"


def _windows_proof_csv_probe(path: Path) -> dict[str, object]:
    """Re-run the Equipment Agent UTM signal-quality gate for proof packages."""
    probe = dict(LabEquipmentAgent._probe_csv_file(str(path)))
    columns = [str(item) for item in probe.get("columns_probe", [])] if isinstance(probe.get("columns_probe"), list) else []
    probe.setdefault("path", str(path))
    probe["row_count"] = int(probe.get("row_count_probe") or 0)
    probe["headers"] = columns
    probe["has_force_column"] = "force_N" in columns
    probe["has_displacement_column"] = "displacement_mm" in columns
    return probe




def _windows_proof_artifact_records(package: dict[str, object]) -> list[dict[str, object]]:
    """Collect artifact records from all proof-package source packets."""
    records: list[dict[str, object]] = []

    def absorb(payload: object) -> None:
        if not isinstance(payload, dict):
            return
        for key in ("artifact_records", "output_artifacts", "artifacts"):
            values = payload.get(key)
            if isinstance(values, list):
                records.extend([dict(item) for item in values if isinstance(item, dict)])
        nested = payload.get("equipment_report")
        if isinstance(nested, dict):
            absorb(nested)

    absorb(package.get("evidence_audit"))
    absorb(package.get("last_windows_utm_result"))
    source_packets = package.get("source_packets") if isinstance(package.get("source_packets"), dict) else {}
    for value in source_packets.values():
        absorb(value)
    seen: set[str] = set()
    unique: list[dict[str, object]] = []
    for record in records:
        key = str(record.get("artifact_id") or record.get("local_path") or record.get("linux_path") or record.get("path") or record.get("filename") or record)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def _windows_proof_resolved_ref_path(ref: object, artifact_records: list[dict[str, object]]) -> tuple[Path | None, str]:
    """Resolve an evidence ref to a Linux-local file path when the proof package carries one."""
    direct = _windows_proof_checkable_path(ref)
    if direct is not None:
        return direct, "direct"
    ref_text = str(ref or "").strip()
    if not ref_text:
        return None, "empty"
    for record in artifact_records:
        candidates = [
            record.get("artifact_id"),
            record.get("filename"),
            record.get("local_path"),
            record.get("linux_path"),
            record.get("path"),
        ]
        if ref_text not in {str(item) for item in candidates if item not in (None, "")}:
            continue
        for key in ("local_path", "linux_path", "path"):
            path = _windows_proof_checkable_path(record.get(key))
            if path is not None:
                return path, f"artifact_record.{key}"
    return None, "unresolved"

def _latest_windows_utm_proof_package_path() -> Path | None:
    """Return the newest persisted Windows UTM proof package under artifacts/equipment."""
    root = resolve_path("artifacts/equipment")
    if not root.exists():
        return None
    candidates = sorted(
        root.glob("*/utm/windows_utm_proof_package_*.json"),
        key=lambda item: item.stat().st_mtime if item.exists() else 0.0,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _windows_utm_completion_audit(path_value: str = "", *, use_current: bool = True, latest: bool = False) -> dict[str, object]:
    """Strict final audit for Improvement 05 physical UTM completion evidence."""
    selected_path = str(path_value or "").strip()
    latest_path: Path | None = None
    if not selected_path and latest:
        latest_path = _latest_windows_utm_proof_package_path()
        selected_path = str(latest_path or "")
        use_current = False
    package, load_info = _load_windows_utm_proof_package_for_verify(selected_path, use_current=use_current)
    verification = _verify_windows_utm_proof_package(package, load_info=load_info)
    blockers = [str(item) for item in verification.get("blockers", []) if str(item or "").strip()] if isinstance(verification.get("blockers"), list) else []
    ok = bool(verification.get("ok") and verification.get("status") == "verified")
    if not selected_path and not use_current:
        blockers = list(dict.fromkeys([*blockers, "PROOF_PACKAGE_PATH_REQUIRED"]))
        ok = False
    result = {
        "ok": ok,
        "tool": "equipment.pyautogui.improvement05_completion_audit",
        "status": "complete_evidence_verified" if ok else "incomplete",
        "objective": "05_lab_equipment_agent_utm_visual_control_data_loop",
        "proof_package_path": selected_path,
        "latest_search_used": bool(latest and latest_path is not None),
        "runtime_state_used": bool(not selected_path and use_current),
        "completion_rule": "Only status=verified from equipment.pyautogui.live_proof_package.verify can satisfy Improvement 05 physical UTM proof.",
        "verification": verification,
        "blockers": blockers,
        "warnings": verification.get("warnings", []) if isinstance(verification.get("warnings"), list) else [],
        "next_actions": ["Improvement 05 physical UTM evidence is verified for this proof package."]
        if ok
        else [
            "Resolve blockers in verification.blockers.",
            "Run real UTM physical validation, build a proof package, then rerun Completion Audit.",
            "Do not mark Improvement 05 complete until this audit status is complete_evidence_verified.",
        ],
    }
    if not selected_path and not use_current:
        result["next_actions"] = [
            "Run /equipment/windows -> Run Physical Validation with real UTM hardware.",
            "Build /api/equipment/windows/proof-package after validation.",
            "Rerun Completion Audit with latest=true or a specific proof package path.",
        ]
    return result


def _load_windows_utm_proof_package_for_verify(path_value: str = "", *, use_current: bool = True) -> tuple[dict[str, object], dict[str, object]]:
    """Load a proof package from an artifact path or the active runtime state."""
    load_info: dict[str, object] = {"source": "none", "path": "", "blockers": [], "warnings": []}
    raw_path = str(path_value or "").strip()
    if raw_path:
        candidate = Path(raw_path).expanduser()
        try:
            resolved = candidate.resolve()
            repo_root = resolve_path(".").resolve()
        except Exception as exc:
            load_info["blockers"] = ["PROOF_PACKAGE_PATH_INVALID"]
            load_info["message"] = str(exc)
            return {}, load_info
        if repo_root not in resolved.parents and resolved != repo_root:
            load_info["blockers"] = ["PROOF_PACKAGE_PATH_OUTSIDE_PROJECT"]
            load_info["path"] = str(resolved)
            return {}, load_info
        if not resolved.exists():
            load_info["blockers"] = ["PROOF_PACKAGE_FILE_MISSING"]
            load_info["path"] = str(resolved)
            return {}, load_info
        try:
            package = json.loads(resolved.read_text(encoding="utf-8"))
        except Exception as exc:
            load_info["blockers"] = ["PROOF_PACKAGE_JSON_INVALID"]
            load_info["path"] = str(resolved)
            load_info["message"] = str(exc)
            return {}, load_info
        if not isinstance(package, dict):
            load_info["blockers"] = ["PROOF_PACKAGE_JSON_NOT_OBJECT"]
            load_info["path"] = str(resolved)
            return {}, load_info
        load_info["source"] = "path"
        load_info["path"] = str(resolved)
        return package, load_info
    if use_current:
        package = controller._state.run_metadata.get("last_windows_utm_proof_package")
        if isinstance(package, dict):
            load_info["source"] = "runtime_state"
            artifact = package.get("package_artifact") if isinstance(package.get("package_artifact"), dict) else {}
            load_info["path"] = str(artifact.get("path") or "")
            return dict(package), load_info
    load_info["blockers"] = ["PROOF_PACKAGE_NOT_AVAILABLE"]
    return {}, load_info


def _verify_windows_utm_proof_package(package: dict[str, object], *, load_info: dict[str, object] | None = None) -> dict[str, object]:
    """Re-verify package metadata and local artifacts before Analysis handoff."""
    load_info = load_info or {}
    blockers: list[str] = [str(item) for item in load_info.get("blockers", []) if str(item or "").strip()] if isinstance(load_info.get("blockers"), list) else []
    warnings: list[str] = [str(item) for item in load_info.get("warnings", []) if str(item or "").strip()] if isinstance(load_info.get("warnings"), list) else []
    checks: list[dict[str, object]] = []

    def add_check(name: str, status: str, detail: str = "", *, code: str = "") -> None:
        item: dict[str, object] = {"name": name, "status": status}
        if detail:
            item["detail"] = detail
        if code:
            item["code"] = code
        checks.append(item)

    def add_blocker(code: str, name: str, detail: str = "") -> None:
        if code not in blockers:
            blockers.append(code)
        add_check(name, "blocked", detail or code, code=code)

    def add_warning(code: str, name: str, detail: str = "") -> None:
        if code not in warnings:
            warnings.append(code)
        add_check(name, "warning", detail or code, code=code)

    if not package:
        add_blocker("PROOF_PACKAGE_NOT_AVAILABLE", "package_loaded", "No proof package was provided or cached.")
        return {
            "ok": False,
            "tool": "equipment.pyautogui.live_proof_package.verify",
            "status": "blocked",
            "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "load_info": load_info,
            "checks": checks,
            "blockers": blockers,
            "warnings": warnings,
        }

    if str(package.get("tool") or "") == "equipment.pyautogui.live_proof_package":
        add_check("package_schema", "ok", "equipment.pyautogui.live_proof_package")
    else:
        add_blocker("PROOF_PACKAGE_SCHEMA_INVALID", "package_schema", str(package.get("tool") or "missing tool"))

    manifest = package.get("manifest") if isinstance(package.get("manifest"), dict) else {}
    artifact = package.get("package_artifact") if isinstance(package.get("package_artifact"), dict) else {}
    artifact_path = str(artifact.get("path") or manifest.get("proof_package_path") or load_info.get("path") or "")
    if artifact_path:
        local_path = _windows_proof_checkable_path(artifact_path)
        if local_path and local_path.exists():
            add_check("package_artifact_file", "ok", str(local_path))
        elif local_path:
            add_blocker("PROOF_PACKAGE_ARTIFACT_FILE_MISSING", "package_artifact_file", str(local_path))
        else:
            add_warning("PROOF_PACKAGE_ARTIFACT_PATH_NOT_LOCAL", "package_artifact_file", artifact_path)
    else:
        add_warning("PROOF_PACKAGE_ARTIFACT_PATH_MISSING", "package_artifact_file", "package path not recorded")

    if bool(package.get("ready_for_analysis")) and bool(package.get("proof_ready")):
        add_check("ready_for_analysis_claim", "ok", "package claims proof_ready and ready_for_analysis")
    else:
        add_blocker("PROOF_PACKAGE_NOT_READY_FOR_ANALYSIS", "ready_for_analysis_claim", f"status={package.get('status')}")

    source_packets = package.get("source_packets") if isinstance(package.get("source_packets"), dict) else {}
    physical_source = source_packets.get("last_windows_utm_physical_validation") if isinstance(source_packets.get("last_windows_utm_physical_validation"), dict) else {}
    physical_execution = manifest.get("physical_execution") if isinstance(manifest.get("physical_execution"), dict) else {}
    physical_execution_ok = bool(
        physical_execution.get("ok") is True
        and physical_execution.get("requested_physical_execute") is True
        and physical_execution.get("execute_sent") is True
        and physical_execution.get("non_actuating") is False
        and str(physical_execution.get("status") or "") == "verified_complete"
    )
    physical_source_ok = bool(
        physical_source.get("requested_physical_execute") is True
        and physical_source.get("execute_sent") is True
        and physical_source.get("non_actuating") is False
        and str(physical_source.get("status") or "") == "verified_complete"
    )
    identity_keys = ("run_id", "sequence_id", "specimen_id", "program_id")
    physical_identity_present = all(
        str(physical_execution.get(key) or "").strip() and str(physical_source.get(key) or "").strip()
        for key in identity_keys
    )
    physical_identity_match = bool(
        physical_identity_present
        and all(str(physical_execution.get(key) or "") == str(physical_source.get(key) or "") for key in identity_keys)
    )
    if physical_execution_ok and physical_source_ok and physical_identity_match:
        add_check("physical_live_execute", "ok", f"source={physical_execution.get('source', '-')}; sequence={physical_execution.get('sequence_id', '-')}")
    else:
        add_blocker(
            "UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED",
            "physical_live_execute",
            f"manifest_ok={physical_execution_ok}; source_ok={physical_source_ok}; identity_present={physical_identity_present}; identity_match={physical_identity_match}; requested={physical_execution.get('requested_physical_execute')}; execute_sent={physical_execution.get('execute_sent')}; non_actuating={physical_execution.get('non_actuating')}; status={physical_execution.get('status') or '-'}",
        )

    request_log = manifest.get("request_log") if isinstance(manifest.get("request_log"), dict) else {}
    if bool(request_log.get("execute_event_seen")):
        add_check("request_log_execute", "ok", f"execute_event_count={request_log.get('execute_event_count', 1)}")
    else:
        add_blocker("UTM_REQUEST_LOG_EXECUTE_EVENT_REQUIRED", "request_log_execute", "no live /execute event in proof manifest")
    if bool(request_log.get("execute_identity_match")):
        add_check("request_log_execute_identity", "ok", "run/specimen/program identity matched")
    else:
        add_blocker("UTM_REQUEST_LOG_EXECUTE_IDENTITY_REQUIRED", "request_log_execute_identity", "live /execute identity did not match proof manifest run/specimen/program")

    save_export = manifest.get("save_export") if isinstance(manifest.get("save_export"), dict) else {}
    recognized_live_save_methods = {"windows_export_watch", "manual_save_dialog", "export_menu"}
    save_method = str(save_export.get("save_method") or "").strip()
    save_attempted = bool(save_export.get("save_attempted_by_agent")) or save_method == "windows_export_watch"
    save_confirmed = bool(save_export.get("save_confirmation_screen_ok"))
    save_path_present = bool(str(save_export.get("windows_path") or save_export.get("linux_path") or "").strip())
    save_export_ok = bool(
        save_export.get("ok")
        and save_method in recognized_live_save_methods
        and save_attempted
        and save_confirmed
        and save_path_present
    )
    if save_export_ok:
        add_check(
            "save_export_responsibility",
            "ok",
            f"method={save_method}; attempted={save_attempted}; confirmed={save_confirmed}; path_present={save_path_present}",
        )
    else:
        add_blocker(
            "UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED",
            "save_export_responsibility",
            f"method={save_method or '-'}; recognized={save_method in recognized_live_save_methods}; save_attempted={save_attempted}; confirmation={save_confirmed}; path_present={save_path_present}; ok_claim={bool(save_export.get('ok'))}",
        )

    artifact_records = _windows_proof_artifact_records(package)
    screen_refs = manifest.get("screen_evidence_refs") if isinstance(manifest.get("screen_evidence_refs"), list) else []
    data_refs = manifest.get("data_evidence_refs") if isinstance(manifest.get("data_evidence_refs"), list) else []

    screen_count = int(manifest.get("screen_evidence_count") or 0)
    verified_screen_files: list[str] = []
    missing_screen_files: list[str] = []
    invalid_screen_files: list[str] = []
    unresolved_screen_refs: list[str] = []
    for ref in screen_refs:
        path, source = _windows_proof_resolved_ref_path(ref, artifact_records)
        if path is None:
            unresolved_screen_refs.append(str(ref))
            continue
        if path.exists() and path.is_file():
            image_ok, image_detail = _windows_proof_image_signature(path)
            if image_ok:
                verified_screen_files.append(str(path))
            else:
                invalid_screen_files.append(f"{path} ({image_detail}; {source})")
        else:
            missing_screen_files.append(f"{path} ({source})")
    unique_screen_files = sorted(set(verified_screen_files))
    duplicate_screen_files = len(unique_screen_files) != len(verified_screen_files)
    if screen_count >= 3 and len(unique_screen_files) >= 3 and not missing_screen_files and not invalid_screen_files and not duplicate_screen_files:
        add_check("screen_evidence_files", "ok", f"verified_screen_files={len(unique_screen_files)}")
    else:
        detail = f"screen_evidence_count={screen_count}; verified_files={len(verified_screen_files)}; unique_files={len(unique_screen_files)}"
        if duplicate_screen_files:
            detail += "; duplicate screen files"
        if invalid_screen_files:
            detail += f"; invalid_image={', '.join(invalid_screen_files[:3])}"
        if missing_screen_files:
            detail += f"; missing={', '.join(missing_screen_files[:3])}"
        if unresolved_screen_refs:
            detail += f"; unresolved={', '.join(unresolved_screen_refs[:3])}"
        add_blocker("UTM_SCREEN_EVIDENCE_FILES_REQUIRED", "screen_evidence_files", detail)

    data_count = int(manifest.get("data_evidence_count") or 0)
    verified_data_files: list[str] = []
    missing_data_files: list[str] = []
    unresolved_data_refs: list[str] = []
    for ref in data_refs:
        path, source = _windows_proof_resolved_ref_path(ref, artifact_records)
        if path is None:
            unresolved_data_refs.append(str(ref))
            continue
        if path.exists() and path.is_file():
            verified_data_files.append(str(path))
        else:
            missing_data_files.append(f"{path} ({source})")
    unique_data_files = sorted(set(verified_data_files))
    if data_count >= 1 and unique_data_files and not missing_data_files:
        add_check("data_evidence_files", "ok", f"verified_data_files={len(unique_data_files)}")
    else:
        detail = f"data_evidence_count={data_count}; verified_files={len(verified_data_files)}; unique_files={len(unique_data_files)}"
        if missing_data_files:
            detail += f"; missing={', '.join(missing_data_files[:3])}"
        if unresolved_data_refs:
            detail += f"; unresolved={', '.join(unresolved_data_refs[:3])}"
        add_blocker("UTM_DATA_EVIDENCE_FILES_REQUIRED", "data_evidence_files", detail)

    csv_probe: dict[str, object] = {}
    linux_data_path = str(manifest.get("linux_data_path") or "").strip()
    local_csv_path = _windows_proof_checkable_path(linux_data_path)
    if local_csv_path:
        if local_csv_path.exists():
            csv_probe = _windows_proof_csv_probe(local_csv_path)
            if bool(csv_probe.get("ok")):
                add_check("linux_csv_parse_probe", "ok", f"rows={csv_probe.get('row_count')} path={local_csv_path}")
            else:
                failure_code = str(csv_probe.get("failure_code") or "UTM_CSV_PARSE_PROBE_FAILED")
                add_blocker(failure_code, "linux_csv_parse_probe", str(csv_probe.get("message") or csv_probe))
        else:
            add_blocker("UTM_LINUX_CSV_FILE_MISSING", "linux_csv_parse_probe", str(local_csv_path))
    elif linux_data_path:
        add_warning("UTM_LINUX_DATA_PATH_NOT_LOCAL", "linux_csv_parse_probe", linux_data_path)
    else:
        add_blocker("UTM_LINUX_DATA_PATH_MISSING", "linux_csv_parse_probe", "manifest.linux_data_path is empty")

    vision_count = int(manifest.get("vision_frame_count") or 0)
    if vision_count >= 3:
        add_check("vision_frame_refs", "ok", f"vision_frame_count={vision_count}")
    else:
        add_blocker("VISION_FRAME_IDS_REQUIRED", "vision_frame_refs", f"vision_frame_count={vision_count}; expected fixture/motion/complete frames")

    checks_by_name = {str(item.get("name") or ""): item for item in checks if isinstance(item, dict)}
    checklist = package.get("proof_checklist") if isinstance(package.get("proof_checklist"), list) else []
    checklist_by_id = {str(item.get("id") or ""): item for item in checklist if isinstance(item, dict)}

    def check_ok(name: str) -> bool:
        item = checks_by_name.get(name)
        return bool(item and item.get("status") == "ok")

    def checklist_ok(item_id: str) -> bool:
        item = checklist_by_id.get(item_id)
        return bool(item and item.get("ok") is True)

    def gate_item(key: str, label: str, ok_value: bool, detail: str) -> dict[str, object]:
        return {"key": key, "label": label, "ok": bool(ok_value), "status": "ok" if ok_value else "blocked", "detail": detail}

    gate_summary = [
        gate_item(
            "windows_bridge",
            "Windows Bridge",
            check_ok("request_log_execute") and check_ok("request_log_execute_identity"),
            "requires live /execute request and matching run/specimen/program identity",
        ),
        gate_item(
            "utm_program",
            "UTM Program",
            check_ok("package_schema") and bool(str((package.get("evidence_audit") if isinstance(package.get("evidence_audit"), dict) else {}).get("program_id") or "").startswith("utm_")),
            "requires a UTM protocol evidence package rather than a demo macro",
        ),
        gate_item(
            "vision_preconditions",
            "Vision Preconditions",
            check_ok("vision_frame_refs"),
            "requires fixture/motion/complete Vision frame references",
        ),
        gate_item(
            "physical_execution",
            "Physical Execute",
            check_ok("physical_live_execute"),
            "requires guarded live physical validation dispatch, not preflight or simulator evidence",
        ),
        gate_item(
            "screen_state",
            "Screen State",
            check_ok("screen_evidence_files"),
            "requires before_start, after_start, and after_complete screen evidence files",
        ),
        gate_item(
            "physical_crosscheck",
            "Physical Cross-check",
            check_ok("vision_frame_refs") and checklist_ok("physical_motion"),
            "requires physical motion proof beyond a successful GUI click",
        ),
        gate_item(
            "data_artifact",
            "Data Artifact",
            check_ok("data_evidence_files") and check_ok("linux_csv_parse_probe") and check_ok("save_export_responsibility"),
            "requires Linux-local CSV, save/export responsibility, and parse probe",
        ),
    ]

    ok = not blockers
    gate_summary.append(
        gate_item(
            "analysis_handoff",
            "Analysis Handoff",
            ok and check_ok("ready_for_analysis_claim"),
            "allowed only after every required proof gate verifies",
        )
    )

    return {
        "ok": ok,
        "tool": "equipment.pyautogui.live_proof_package.verify",
        "status": "verified" if ok else "blocked",
        "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": str(package.get("run_id") or ""),
        "bridge": "windows_pyautogui",
        "load_info": load_info,
        "package_artifact": artifact,
        "ready_for_analysis_claimed": bool(package.get("ready_for_analysis")),
        "proof_ready_claimed": bool(package.get("proof_ready")),
        "checks": checks,
        "gate_summary": gate_summary,
        "csv_probe": csv_probe,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": ["Proceed to Analysis handoff only after this verification is status=verified."] if ok else ["Resolve blockers, rebuild the proof package, then run Verify Proof Package again."],
    }

def _windows_utm_live_preflight_from_bridge(
    bridge: WindowsPyAutoGUIBridge,
    *,
    include_locators: bool = True,
    include_screenshot: bool = False,
    include_request_log: bool = True,
    runtime_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """Actively verify live Windows UTM setup without executing UTM controls."""
    passive = _windows_utm_readiness_from_bridge(bridge, runtime_overrides=runtime_overrides)
    passive_gates = passive.get("gates") if isinstance(passive.get("gates"), dict) else {}
    program_id = str(passive.get("program_id") or "utm_compression_start_v1")
    require_screen = bool(passive_gates.get("require_screen_assertions"))
    blockers = [str(item) for item in passive.get("blockers", []) if item]
    warnings = [str(item) for item in passive.get("warnings", []) if item]
    checks: list[dict[str, object]] = []
    touched_endpoints: list[str] = []
    evidence_refs: list[str] = []

    def add_check(name: str, status: str, detail: str = "", *, code: str = "") -> None:
        item: dict[str, object] = {"name": name, "status": status}
        if detail:
            item["detail"] = detail
        if code:
            item["code"] = code
        checks.append(item)

    def add_blocker(code: str, name: str, detail: str = "") -> None:
        if code not in blockers:
            blockers.append(code)
        add_check(name, "blocked", detail or code, code=code)

    def add_warning(code: str, name: str, detail: str = "") -> None:
        if code not in warnings:
            warnings.append(code)
        add_check(name, "warning", detail or code, code=code)

    def locator_count(payload: object) -> int:
        if isinstance(payload, dict):
            locators = payload.get("locators")
            if isinstance(locators, dict):
                return len(locators)
            if isinstance(locators, list):
                return len(locators)
        return 0

    add_check(
        "passive_readiness",
        str(passive.get("status") or "unknown"),
        f"setup gates: {', '.join(blockers + warnings) if blockers or warnings else 'ready'}",
    )

    touched_endpoints.append("/health")
    health = bridge.health({"runtime_mode": "live", "force_live_bridge": True})
    if not bool(health.get("ok")):
        add_blocker("LIVE_BRIDGE_HEALTH_FAILED", "bridge_health", str(health.get("failure_code") or health.get("message") or "health failed"))
        programs: dict[str, object] = {}
        locators: dict[str, object] = {}
        screenshot: dict[str, object] = {}
        request_log: dict[str, object] = {}
    else:
        add_check("bridge_health", "ok", str(health.get("status") or "ready"))
        pyautogui = health.get("pyautogui") if isinstance(health.get("pyautogui"), dict) else {}
        if isinstance(pyautogui, dict) and pyautogui.get("available") is False:
            add_blocker("LIVE_PYAUTOGUI_UNAVAILABLE", "pyautogui_import", "Windows bridge reports PyAutoGUI unavailable.")
        elif isinstance(pyautogui, dict):
            add_check("pyautogui_import", "ok", "PyAutoGUI available")
        else:
            add_warning("LIVE_PYAUTOGUI_STATUS_UNKNOWN", "pyautogui_import", "Health response did not include PyAutoGUI status.")

        touched_endpoints.append("/programs")
        programs = bridge.list_programs({"runtime_mode": "live", "force_live_bridge": True})
        program_list = programs.get("programs") if isinstance(programs.get("programs"), list) else []
        live_program_ids = {
            str(item.get("program_id"))
            for item in program_list
            if isinstance(item, dict) and item.get("program_id")
        }
        if not bool(programs.get("ok")):
            add_blocker("LIVE_PROGRAM_REGISTRY_FAILED", "program_registry", str(programs.get("failure_code") or programs.get("message") or "program registry failed"))
        elif program_id not in live_program_ids:
            add_blocker("LIVE_UTM_PROGRAM_NOT_REGISTERED", "utm_program", f"{program_id} missing from live Windows /programs response")
        else:
            add_check("utm_program", "ok", f"{program_id} registered")

        locators = {}
        if include_locators:
            touched_endpoints.append("/locators")
            locators = bridge.list_locators({"runtime_mode": "live", "force_live_bridge": True})
            live_locator_count = locator_count(locators)
            profile_locator_count = int(passive_gates.get("locator_count") or 0)
            if not bool(locators.get("ok")):
                add_warning("LIVE_LOCATOR_LIST_FAILED", "locator_library", str(locators.get("failure_code") or locators.get("message") or "locator listing failed"))
            elif require_screen and live_locator_count == 0 and profile_locator_count == 0:
                add_blocker("LIVE_UTM_LOCATORS_NOT_AVAILABLE", "locator_library", "screen assertions are required but no locator profile/library is available")
            elif live_locator_count == 0:
                add_warning("LIVE_LOCATOR_LIBRARY_EMPTY", "locator_library", "Windows locator library returned no stored locator entries")
            else:
                add_check("locator_library", "ok", f"{live_locator_count} Windows-side locator(s) visible")

        request_log: dict[str, object] = {}
        if include_request_log:
            touched_endpoints.append("/request-log")
            request_log = _windows_bridge_request_log_from_bridge(bridge, runtime_mode="live", confirm_live=True)
            if bool(request_log.get("ok")):
                add_check("request_audit_log", "ok", f"events={request_log.get('event_count', 0)}")
            else:
                add_warning("LIVE_REQUEST_LOG_UNAVAILABLE", "request_audit_log", str(request_log.get("failure_code") or request_log.get("message") or "request log unavailable"))

        screenshot = {}
        if include_screenshot:
            touched_endpoints.append("/screenshot")
            screenshot = bridge.screenshot(
                {
                    "runtime_mode": "live",
                    "force_live_bridge": True,
                    "run_id": "live-preflight",
                    "checkpoint": "preflight",
                }
            )
            if not bool(screenshot.get("ok")):
                add_blocker("LIVE_SCREENSHOT_FAILED", "preflight_screenshot", str(screenshot.get("failure_code") or screenshot.get("message") or "screenshot failed"))
            else:
                add_check("preflight_screenshot", "ok", str(screenshot.get("artifact_path") or screenshot.get("path") or "captured"))
                for key in ("artifact_path", "path", "local_path"):
                    if screenshot.get(key):
                        evidence_refs.append(str(screenshot[key]))
                        break

    status = "blocked" if blockers else "warning" if warnings else "ready"
    return {
        "ok": not blockers,
        "tool": "equipment.pyautogui.live_preflight",
        "status": status,
        "bridge": "windows_pyautogui",
        "program_id": program_id,
        "non_actuating": True,
        "touched_endpoints": touched_endpoints,
        "passive_readiness": passive,
        "health": health,
        "programs": programs,
        "locators": locators,
        "screenshot": screenshot,
        "request_log": request_log,
        "request_audit_log": {
            "ok": bool(request_log.get("ok")) if isinstance(request_log, dict) else False,
            "path": str(request_log.get("request_log") or "") if isinstance(request_log, dict) else "",
            "event_count": int(request_log.get("event_count") or 0) if isinstance(request_log, dict) else 0,
        },
        "checks": checks,
        "blockers": blockers,
        "warnings": warnings,
        "ready_for_setup_test": not blockers,
        "ready_for_autonomous_profile": not blockers and bool(passive.get("ready_for_autonomous_profile")),
        "evidence_refs": evidence_refs,
        "next_actions": passive.get("next_actions", []),
    }


@app.post("/api/equipment/windows/live-preflight")
async def post_windows_equipment_live_preflight(req: WindowsBridgeLivePreflightRequest) -> dict[str, object]:
    """Actively check live Windows UTM readiness without starting equipment motion."""
    if not req.confirm_preflight:
        raise HTTPException(status_code=400, detail="confirm_preflight=true is required for live Windows preflight")
    bridge = _equipment_bridge()
    result = _windows_utm_live_preflight_from_bridge(
        bridge,
        include_locators=req.include_locators,
        include_screenshot=req.include_screenshot,
        include_request_log=req.include_request_log,
    )
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.live_preflight",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_live_preflight",
        node_event=True,
    )
    return result


@app.post("/api/equipment/windows/live-validation")
async def post_windows_equipment_live_validation(req: WindowsBridgeLiveValidationRequest) -> dict[str, object]:
    """Build live UTM validation reports, optionally sending /execute after explicit physical confirmation."""
    execute_requested = bool(req.confirm_live_execute)
    if execute_requested:
        if not req.confirm_physical_setup_safe:
            raise HTTPException(status_code=400, detail="confirm_physical_setup_safe=true is required before physical live UTM validation")
    elif not req.confirm_non_actuating:
        raise HTTPException(status_code=400, detail="confirm_non_actuating=true or confirm_live_execute=true is required for Windows UTM validation")
    from scripts.lab_equipment_live_utm_validation import evaluate_live_validation, gate

    bridge = _equipment_bridge()
    run_id = str(req.run_id or controller._state.run_id or "utm-live-validation").strip() or "utm-live-validation"
    sequence_id = str(req.sequence_id or run_id).strip() or run_id
    specimen_id = str(req.specimen_id or "specimen-live-validation").strip() or "specimen-live-validation"
    program_id = str(req.program_id or "utm_compression_start_v1").strip() or "utm_compression_start_v1"
    common = {"runtime_mode": "live", "force_live_bridge": True}
    payload: dict[str, object] = {
        **common,
        "confirm_setup_gui_execute": True,
        "run_id": run_id,
        "sequence_id": sequence_id,
        "specimen_id": specimen_id,
        "program_id": program_id,
        "command": req.command or "Run UTM compression protocol and export CSV",
        "require_screen_assertions": req.require_screen_assertions,
        "require_window_focus": req.require_window_focus,
        "manual_save_required_if_no_artifact": req.manual_save_required_if_no_artifact,
        "simulate_utm_protocol": False,
    }
    if req.export_glob.strip():
        payload["export_glob"] = req.export_glob.strip()
    if req.artifact_timeout_s is not None:
        payload["artifact_timeout_s"] = req.artifact_timeout_s
    if req.stable_for_sec is not None:
        payload["stable_for_sec"] = req.stable_for_sec
    if req.expected_export_path.strip():
        payload["expected_export_path"] = req.expected_export_path.strip()
    if req.target_window.strip():
        payload["target_window"] = req.target_window.strip()
    if req.target_window_regex.strip():
        payload["target_window_regex"] = req.target_window_regex.strip()
    if req.locators:
        payload["locators"] = req.locators
    if req.sequence:
        payload["sequence"] = req.sequence

    touched_endpoints = ["/request-log", "/health"]
    request_log_before = _windows_bridge_request_log_from_bridge(bridge, runtime_mode="live", confirm_live=True)
    health = bridge.health(common)
    if bool(health.get("ok")):
        touched_endpoints.append("/programs")
        programs = bridge.list_programs(common)
    else:
        programs = {
            "ok": False,
            "tool": "equipment.pyautogui.list_programs",
            "status": "skipped",
            "failure_code": "LIVE_BRIDGE_HEALTH_FAILED",
            "programs": [],
        }

    readiness: dict[str, object] = {}
    preflight: dict[str, object] = {}
    execution: dict[str, object] | None = None
    execute_sent = False
    extra_gates: list[dict[str, object]] = []
    if execute_requested:
        readiness = _windows_utm_readiness_from_bridge(bridge, runtime_overrides=payload)
        preflight = _windows_utm_live_preflight_from_bridge(
            bridge,
            include_locators=True,
            include_screenshot=False,
            include_request_log=True,
            runtime_overrides=payload,
        )
        for endpoint in preflight.get("touched_endpoints", []) if isinstance(preflight.get("touched_endpoints"), list) else []:
            if isinstance(endpoint, str) and endpoint not in touched_endpoints:
                touched_endpoints.append(endpoint)
        readiness_ok = bool(readiness.get("ready_for_autonomous_profile"))
        preflight_ok = bool(preflight.get("ready_for_autonomous_profile"))
        extra_gates.extend(
            [
                gate(
                    "pre_execution_readiness",
                    readiness_ok,
                    f"status={readiness.get('status', '-')}; blockers={', '.join(str(item) for item in readiness.get('blockers', []) if str(item or '').strip()) or '-'}",
                    evidence=readiness,
                ),
                gate(
                    "pre_execution_live_preflight",
                    preflight_ok,
                    f"status={preflight.get('status', '-')}; blockers={', '.join(str(item) for item in preflight.get('blockers', []) if str(item or '').strip()) or '-'}",
                    evidence={"ready_for_autonomous_profile": preflight.get("ready_for_autonomous_profile"), "checks": preflight.get("checks", [])},
                ),
                gate(
                    "physical_setup_confirmation",
                    bool(req.confirm_physical_setup_safe),
                    "operator confirmed physical UTM setup safe before /execute",
                    evidence={"confirm_physical_setup_safe": bool(req.confirm_physical_setup_safe)},
                ),
            ]
        )
        if readiness_ok and preflight_ok:
            touched_endpoints.append("/execute")
            execution = bridge.run(payload)
            execute_sent = True
        else:
            execution = {
                "ok": False,
                "tool": "equipment.pyautogui.run",
                "status": "blocked",
                "failure_code": "UTM_PHYSICAL_VALIDATION_PREFLIGHT_BLOCKED",
                "message": "Physical UTM validation did not send /execute because readiness or live preflight gates are incomplete.",
                "bridge_not_called": True,
                "non_actuating": True,
                "run_id": run_id,
                "sequence_id": sequence_id,
                "specimen_id": specimen_id,
                "program_id": program_id,
                "readiness": readiness,
                "preflight": preflight,
                "step_trace": [
                    {"step": "READINESS_PRECHECK", "status": "ok" if readiness_ok else "blocked", "detail": str(readiness.get("status") or "unknown")},
                    {"step": "LIVE_PREFLIGHT", "status": "ok" if preflight_ok else "blocked", "detail": str(preflight.get("status") or "unknown")},
                ],
            }

    touched_endpoints.append("/request-log")
    request_log_after = _windows_bridge_request_log_from_bridge(bridge, runtime_mode="live", confirm_live=True)
    vision_proof = req.vision_proof if isinstance(req.vision_proof, dict) else {}
    report = evaluate_live_validation(
        run_id=run_id,
        sequence_id=sequence_id,
        specimen_id=specimen_id,
        program_id=program_id,
        health=health,
        programs=programs,
        request_log_before=request_log_before,
        execution=execution,
        request_log_after=request_log_after,
        vision_proof=vision_proof,
        executed=execute_sent,
    )
    if extra_gates:
        report_gates = list(extra_gates) + [item for item in report.get("gates", []) if isinstance(item, dict)]
        blockers = [item for item in report_gates if item.get("required") and item.get("ok") is not True]
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        summary = dict(summary)
        summary["required_gate_count"] = len([item for item in report_gates if item.get("required")])
        summary["passed_required_gate_count"] = len([item for item in report_gates if item.get("required") and item.get("ok") is True])
        summary["blocker_count"] = len(blockers)
        summary["physical_live_evidence_captured"] = execute_sent and not blockers
        report["gates"] = report_gates
        report["blockers"] = blockers
        report["summary"] = summary
        report["ok"] = not blockers
        if blockers:
            report["status"] = "blocked"
    report["tool"] = "equipment.pyautogui.live_validation"
    report["touched_endpoints"] = list(dict.fromkeys(touched_endpoints))
    report["request_audit_log"] = request_log_after
    report["requested_physical_execute"] = execute_requested
    report["execute_sent"] = execute_sent
    report["ready_for_physical_live_run"] = (not execute_requested) and bool(report.get("ok"))
    report["pre_execution_readiness"] = readiness
    report["pre_execution_preflight"] = preflight
    report["execution_payload_preview"] = {key: value for key, value in payload.items() if key not in {"locators", "sequence"}}
    if req.include_screenshot and not execute_sent:
        touched_endpoints.append("/screenshot")
        screenshot = bridge.screenshot(
            {
                "runtime_mode": "live",
                "force_live_bridge": True,
                "run_id": run_id,
                "checkpoint": "live_validation_pre_execute",
            }
        )
        evidence = report.get("evidence") if isinstance(report.get("evidence"), dict) else {}
        evidence = dict(evidence)
        evidence["non_actuating_screenshot"] = screenshot
        report["evidence"] = evidence
        report["screenshot"] = screenshot
        report["touched_endpoints"] = list(dict.fromkeys(touched_endpoints))
    report = _persist_windows_utm_live_validation(report)
    runtime_promotion: dict[str, object] = {}
    if execute_requested:
        runtime_promotion = _windows_utm_runtime_metadata_from_live_validation_report(report, run_id=run_id)
        promotion_summary = {
            "verified": bool(runtime_promotion.get("verified")),
            "promoted_keys": [
                key
                for key in ("equipment_result", "equipment_report", "utm_data_ready", "equipment_handoff")
                if isinstance(runtime_promotion.get(key), dict)
            ],
            "result_file": str(
                runtime_promotion.get("equipment_result", {}).get("result_file", "")
                if isinstance(runtime_promotion.get("equipment_result"), dict)
                else ""
            ),
            "analysis_handoff_status": str(
                runtime_promotion.get("equipment_handoff", {}).get("status", "")
                if isinstance(runtime_promotion.get("equipment_handoff"), dict)
                else ""
            ),
        }
        report["runtime_promotion"] = promotion_summary
        if runtime_promotion.get("verified") is True:
            for key in ("equipment_result", "equipment_report", "utm_data_ready", "equipment_handoff"):
                value = runtime_promotion.get(key)
                if isinstance(value, dict):
                    controller._state.run_metadata[key] = value
            controller._state.run_metadata["last_windows_utm_runtime_promotion"] = runtime_promotion
        report = _persist_windows_utm_live_validation(report)
    controller._state.run_metadata["last_windows_utm_live_validation"] = report
    if execute_requested:
        controller._state.run_metadata["last_windows_utm_physical_validation"] = report
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.live_validation",
        result=report,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_utm_physical_live_validation" if execute_requested else "windows_utm_live_validation",
        node_event=True,
    )
    return report


@app.get("/api/equipment/windows/config")
async def get_windows_equipment_config() -> dict[str, object]:
    """Return saved Windows PyAutoGUI bridge configuration status."""
    bridge = _equipment_bridge()
    status = bridge.connection_status()
    programs = bridge.list_programs({"runtime_mode": "test"})
    profile = bridge.utm_profile_status()
    readiness = _windows_utm_readiness_from_bridge(bridge)
    evidence_audit = _windows_utm_evidence_audit_from_metadata(dict(controller._state.run_metadata), run_id=controller._state.run_id)
    request_audit = _windows_bridge_request_log_from_bridge(bridge, runtime_mode="test", confirm_live=False)
    live_validation = controller._state.run_metadata.get("last_windows_utm_live_validation")
    if not isinstance(live_validation, dict):
        live_validation = {}
    completion_audit = controller._state.run_metadata.get("last_windows_utm_completion_audit")
    if not isinstance(completion_audit, dict):
        completion_audit = {}
    vision_proof_draft = controller._state.run_metadata.get("last_windows_utm_vision_proof_draft")
    if not isinstance(vision_proof_draft, dict):
        vision_proof_draft = {}
    return {
        "ok": True,
        "connection": status,
        "programs": programs.get("programs", []),
        "utm_profile": profile,
        "utm_readiness": readiness,
        "utm_evidence_audit": evidence_audit,
        "utm_live_validation": live_validation,
        "utm_completion_audit": completion_audit,
        "utm_vision_proof_draft": vision_proof_draft,
        "request_audit": request_audit,
    }


@app.get("/api/equipment/windows/readiness")
async def get_windows_equipment_readiness() -> dict[str, object]:
    """Return passive UTM readiness gates for the Equipment workspace."""
    return _windows_utm_readiness_from_bridge(_equipment_bridge())


@app.get("/api/equipment/windows/evidence-audit")
async def get_windows_equipment_evidence_audit() -> dict[str, object]:
    """Return post-run UTM evidence gates from current runtime metadata."""
    return _windows_utm_evidence_audit_from_metadata(dict(controller._state.run_metadata), run_id=controller._state.run_id)


@app.get("/api/equipment/windows/proof-package")
async def get_windows_equipment_proof_package() -> dict[str, object]:
    """Return a consolidated non-actuating proof package for the current Windows UTM run."""
    bridge = _equipment_bridge()
    readiness = _windows_utm_readiness_from_bridge(bridge)
    package = _windows_utm_proof_package_from_metadata(
        dict(controller._state.run_metadata),
        run_id=controller._state.run_id,
        passive_readiness=readiness,
    )
    package = _persist_windows_utm_proof_package(package)
    controller._state.run_metadata["last_windows_utm_proof_package"] = package
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.live_proof_package",
        result=package,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_utm_proof_package",
        node_event=False,
    )
    return package


@app.post("/api/equipment/windows/proof-package/verify")
async def post_windows_equipment_verify_proof_package(req: WindowsBridgeProofPackageVerifyRequest) -> dict[str, object]:
    """Re-verify a persisted Windows UTM proof package and its local artifacts."""
    package, load_info = _load_windows_utm_proof_package_for_verify(req.path, use_current=req.use_current)
    result = _verify_windows_utm_proof_package(package, load_info=load_info)
    controller._state.run_metadata["last_windows_utm_proof_package_verification"] = result
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.live_proof_package.verify",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_utm_proof_package_verify",
        node_event=False,
    )
    return result


@app.post("/api/equipment/windows/completion-audit")
async def post_windows_equipment_completion_audit(req: WindowsBridgeCompletionAuditRequest) -> dict[str, object]:
    """Run the strict final Improvement 05 completion audit against a proof package."""
    result = _windows_utm_completion_audit(req.path, use_current=req.use_current, latest=req.latest)
    result = _persist_windows_utm_completion_audit(result)
    controller._state.run_metadata["last_windows_utm_completion_audit"] = result
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.improvement05_completion_audit",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_utm_completion_audit",
        node_event=False,
    )
    return result


@app.post("/api/equipment/windows/vision-proof-draft")
async def post_windows_equipment_vision_proof_draft(req: WindowsBridgeVisionProofDraftRequest) -> dict[str, object]:
    """Build a non-actuating Vision proof JSON draft from current runtime evidence."""
    result = _windows_utm_vision_proof_draft(
        dict(controller._state.run_metadata),
        observations=dict(controller._state.latest_observations),
        run_id=req.run_id,
        specimen_id=req.specimen_id,
    )
    controller._state.run_metadata["last_windows_utm_vision_proof_draft"] = result
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.vision_proof_draft",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_utm_vision_proof_draft",
        node_event=False,
    )
    return result


@app.post("/api/equipment/windows/request-log")
async def post_windows_equipment_request_log(req: WindowsBridgeRequestLogRequest) -> dict[str, object]:
    """Return Windows bridge request-audit events for setup/live evidence review."""
    result = _windows_bridge_request_log_from_bridge(
        _equipment_bridge(),
        runtime_mode=req.runtime_mode,
        confirm_live=req.confirm_live,
    )
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.request_log",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_request_audit",
        node_event=True,
    )
    return result


@app.get("/api/printer/status")
async def get_printer_status(mode: Literal["live", "test"] = "live") -> dict[str, object]:
    """Return selected-printer fleet/device status for GUI display."""
    manager = _printer_bridge_manager()
    health = manager.prepare({"runtime_mode": mode, "health_only": mode != "live"})
    connection = _redacted_selected_printer_connection(manager)
    profile = _selected_print_profile(manager)
    config = manager.config
    return {
        "ok": bool(health.get("ok")),
        "mode": mode,
        "provider": health.get("provider", config.default_profile.provider),
        "selected_printer": health.get("selected_printer", {}),
        "available_printers": health.get("available_printers", manager.available_printers()),
        "automatic_fallback": bool(health.get("automatic_fallback", config.allow_automatic_fallback)),
        "connection": connection,
        "live_gates": {
            "allow_status": True,
            "allow_upload": bool(health.get("device_screen", {}).get("actions", {}).get("can_upload", False)),
            "allow_start_print": bool(health.get("device_screen", {}).get("actions", {}).get("can_start_print", False)),
            "allow_ejection": bool(health.get("autoejection", {}).get("enabled", False)),
        },
        "auto_ejection": {
            "enabled": bool(health.get("autoejection", {}).get("enabled", False)),
            "method": health.get("autoejection", {}).get("provider", "none"),
            "mode": health.get("autoejection", {}).get("status", "not_configured"),
        },
        "slicer": _selected_printer_slicer_payload(manager, _printer_workflow().config),
        "profile": profile,
        "profile_path": str(PRUSA_PRINT_PROFILE_PATH),
        "device_screen": health.get("device_screen", {}),
        "preprint_gate": health.get("preprint_gate", {}),
        "operator_actions": health.get("operator_actions", []),
        "health": health,
    }


@app.get("/api/printer/video-status")
async def get_printer_video_status() -> dict[str, object]:
    """Probe selected Bambu live-view readiness without exposing access-code secrets."""
    manager = _printer_bridge_manager()
    return manager.video_status({})


def _selected_bambu_video_connection(manager: PrinterDeviceBridgeManager) -> tuple[str, str]:
    """Return selected Bambu host/access-code for local video proxy routes."""
    selected_profile, _reason = manager.fleet_selection()
    if selected_profile.provider != "bambulab_x2d":
        raise HTTPException(status_code=400, detail="BAMBU_VIDEO_STREAM_REQUIRES_BAMBU_PROFILE")
    memory = BambuConnectionMemory(selected_profile.connection_memory_path)
    raw_connection = memory.load()
    raw_auth = raw_connection.get("auth") if isinstance(raw_connection.get("auth"), dict) else {}
    host = str(raw_connection.get("host") or "").strip()
    access_code = str(raw_auth.get("access_code") or "")
    if not host or not access_code:
        raise HTTPException(status_code=400, detail="BAMBU_VIDEO_CONNECTION_INFO_INCOMPLETE")
    return host, access_code


@app.get("/api/printer/video-frame.jpg")
async def get_printer_video_frame() -> Response:
    """Return one Bambu camera frame as JPEG for reliable browser preview cards."""
    manager = _printer_bridge_manager()
    host, access_code = _selected_bambu_video_connection(manager)
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise HTTPException(status_code=503, detail="BAMBU_VIDEO_PROXY_FFMPEG_MISSING")

    stream_url = f"rtsps://bblp:{quote(access_code, safe='')}@{host}:{manager.config.video.rtsps_port}/streaming/live/1"
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        stream_url,
        "-frames:v",
        "1",
        "-vf",
        "scale=960:-1",
        "-q:v",
        "4",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=max(5.0, float(manager.config.video.timeout_sec) + 3.0),
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="BAMBU_VIDEO_FRAME_TIMEOUT") from exc
    if completed.returncode != 0 or not completed.stdout:
        raise HTTPException(status_code=502, detail="BAMBU_VIDEO_FRAME_CAPTURE_FAILED")
    return Response(
        content=completed.stdout,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/printer/video-stream.mjpeg")
async def get_printer_video_stream() -> StreamingResponse:
    """Proxy selected Bambu RTSPS live view as MJPEG for the browser device panel."""
    manager = _printer_bridge_manager()
    host, access_code = _selected_bambu_video_connection(manager)
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise HTTPException(status_code=503, detail="BAMBU_VIDEO_PROXY_FFMPEG_MISSING")

    stream_url = f"rtsps://bblp:{quote(access_code, safe='')}@{host}:{manager.config.video.rtsps_port}/streaming/live/1"
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-i",
        stream_url,
        "-an",
        "-vf",
        "fps=5,scale=960:-1",
        "-q:v",
        "5",
        "-f",
        "mpjpeg",
        "-",
    ]

    def iter_mjpeg() -> object:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        try:
            if process.stdout is None:
                return
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()

    return StreamingResponse(iter_mjpeg(), media_type="multipart/x-mixed-replace; boundary=ffmpeg")


@app.get("/api/printer/fleet")
async def get_printer_fleet() -> dict[str, object]:
    """Return selectable printer profiles and the active operator-selected profile."""
    manager = _printer_bridge_manager()
    return manager.fleet_payload()


@app.post("/api/printer/fleet")
async def post_printer_fleet(req: PrinterFleetSelectionRequest) -> dict[str, object]:
    """Persist the active printer profile without enabling automatic fallback."""
    manager = _printer_bridge_manager()
    try:
        return manager.save_fleet_selection(req.profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/printer/connection")
async def get_printer_connection() -> dict[str, object]:
    """Return editable selected-printer bridge connection fields without secrets."""
    manager = _printer_bridge_manager()
    selected_profile, _reason = manager.fleet_selection()
    if selected_profile.provider == "bambulab_x2d":
        return {"ok": True, "connection": _redacted_selected_printer_connection(manager)}
    workflow = _printer_workflow()
    workflow.connection_memory.ensure_template(workflow.config.live)
    return {"ok": True, "connection": _redacted_printer_connection(workflow)}


@app.post("/api/printer/connection")
async def post_printer_connection(req: PrinterConnectionRequest) -> dict[str, object]:
    """Persist selected-printer bridge connection memory from the 3DP GUI."""
    manager = _printer_bridge_manager()
    selected_profile, _reason = manager.fleet_selection()
    if selected_profile.provider == "bambulab_x2d":
        memory = BambuConnectionMemory(selected_profile.connection_memory_path)
        memory.save_from_payload(
            {
                "host": req.host.strip(),
                "model": req.model.strip() or "Bambu Lab X2D",
                "serial": req.serial.strip(),
                "printer_name": req.printer_name.strip(),
                "lan_mode_confirmed": req.lan_mode_confirmed,
                "developer_mode_confirmed": req.developer_mode_confirmed,
                "auth": {
                    "mode": "lan_access_code",
                    "username": req.username.strip() or "bblp",
                    "access_code": req.access_code or req.password,
                },
                "mqtt_port": 8883,
                "ftps_port": 990,
            }
        )
        return {
            "ok": True,
            "connection": memory.redacted(),
            "message": "Bambu Lab bridge connection saved.",
        }

    workflow = _printer_workflow()
    connection_info: dict[str, object] = {
        "host": req.host.strip(),
        "scheme": req.scheme,
        "port": int(req.port),
        "storage": req.storage.strip() or "usb",
        "auth": {
            "mode": req.auth_mode,
            "username": req.username.strip(),
            "password": req.password,
            "api_key": req.api_key,
            "api_key_header": req.api_key_header.strip() or "X-Api-Key",
        },
    }
    workflow.connection_memory.save_from_payload({"connection_info": connection_info})
    return {
        "ok": True,
        "connection": _redacted_printer_connection(workflow),
        "message": "PrusaLink bridge connection saved.",
    }


@app.post("/api/printer/upload-path-probe")
async def post_printer_upload_path_probe(req: PrinterUploadPathProbeRequest) -> dict[str, object]:
    """Probe Bambu FTPS candidate upload paths using a small marker file that is deleted immediately."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    if selected_profile.provider != "bambulab_x2d":
        return {
            "ok": False,
            "provider": selected_profile.provider,
            "failure_code": "BAMBU_UPLOAD_PATH_PROBE_NOT_APPLICABLE",
            "message": "Upload path probing is only implemented for the Bambu Lab bridge.",
        }
    memory = BambuConnectionMemory(selected_profile.connection_memory_path)
    connection = memory.load()
    auth = connection.get("auth") if isinstance(connection.get("auth"), dict) else {}
    result = manager.ftps_client.probe_upload_paths(
        host=str(connection.get("host") or ""),
        username=str(auth.get("username") or "bblp"),
        access_code=str(auth.get("access_code") or ""),
        timeout_sec=float(req.timeout_sec),
        candidate_dirs=[str(item) for item in req.candidate_dirs],
    )
    return {
        **result,
        "tool": "printer.bambu.upload_path_probe",
        "provider": selected_profile.provider,
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "connection": memory.redacted(),
    }


@app.post("/api/printer/start-command-draft")
async def post_printer_start_command_draft(req: PrinterStartCommandDraftRequest) -> dict[str, object]:
    """Build a Bambu MQTT project_file command draft without publishing or starting a print."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    if selected_profile.provider != "bambulab_x2d":
        return {
            "ok": False,
            "provider": selected_profile.provider,
            "failure_code": "BAMBU_START_COMMAND_DRAFT_NOT_APPLICABLE",
            "message": "Start command drafts are only implemented for the Bambu Lab bridge.",
            "will_publish": False,
            "start_enabled": False,
        }
    memory = BambuConnectionMemory(selected_profile.connection_memory_path)
    connection = memory.redacted()
    draft = build_bambu_project_file_command_draft(
        serial=str(connection.get("serial") or ""),
        remote_path=req.remote_path,
        subtask_name=req.subtask_name,
        plate_id=req.plate_id,
        use_ams=req.use_ams,
        ams_mapping=req.ams_mapping,
        timelapse=req.timelapse,
        bed_leveling=req.bed_leveling,
        flow_cali=req.flow_cali,
        vibration_cali=req.vibration_cali,
        layer_inspect=req.layer_inspect,
    )
    return {
        **draft,
        "tool": "printer.bambu.start_command_draft",
        "provider": selected_profile.provider,
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "connection": connection,
    }


def _bambu_start_gate_blockers(
    *,
    draft: dict[str, object],
    prepare_result: dict[str, object],
    operator_confirmed: bool,
    guardian_approved: bool,
    dry_run: bool,
) -> tuple[list[str], dict[str, object]]:
    """Return deterministic publish blockers for Bambu start-command preflight."""
    device_screen = prepare_result.get("device_screen") if isinstance(prepare_result.get("device_screen"), dict) else {}
    actions = device_screen.get("actions") if isinstance(device_screen.get("actions"), dict) else {}
    preprint_gate = prepare_result.get("preprint_gate") if isinstance(prepare_result.get("preprint_gate"), dict) else {}
    checks = preprint_gate.get("checks") if isinstance(preprint_gate.get("checks"), dict) else {}
    blockers: list[str] = []

    def add(code: str) -> None:
        if code and code not in blockers:
            blockers.append(code)

    if not draft.get("ok"):
        add(str(draft.get("failure_code") or "BAMBU_START_DRAFT_INVALID"))
    for code in preprint_gate.get("blockers", []) if isinstance(preprint_gate.get("blockers"), list) else []:
        add(str(code))
    if dry_run:
        add("BAMBU_START_DRY_RUN")
    if not operator_confirmed:
        add("BAMBU_OPERATOR_CONFIRMATION_REQUIRED")
    if not guardian_approved:
        add("BAMBU_GUARDIAN_APPROVAL_REQUIRED")
    if not bool(actions.get("can_start_print", False)):
        add("BAMBU_DEVICE_SCREEN_START_DISABLED")

    required_check_codes = {
        "mqtt_authenticated_or_virtual": "BAMBU_MQTT_NOT_AUTHENTICATED",
        "latest_report_fresh": "BAMBU_MQTT_REPORT_NOT_FRESH",
        "storage_transfer_path_verified": "BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED",
        "printer_safe_state_verified": "BAMBU_PRINTER_SAFE_STATE_NOT_VERIFIED",
        "start_command_draft_prepared": "BAMBU_START_COMMAND_DRAFT_NOT_PREPARED",
    }
    for key, code in required_check_codes.items():
        if key in checks and not bool(checks.get(key)):
            add(code)

    gate_checks = {
        "draft_valid": bool(draft.get("ok")),
        "operator_confirmed": bool(operator_confirmed),
        "guardian_approved": bool(guardian_approved),
        "dry_run": bool(dry_run),
        "device_screen_can_start_print": bool(actions.get("can_start_print", False)),
        "device_screen_can_prepare_start_command": bool(actions.get("can_prepare_start_command", False)),
        "preprint_gate_state": preprint_gate.get("state", ""),
        "preprint_gate_checks": checks,
    }
    return blockers, gate_checks


@app.post("/api/printer/start-gate")
async def post_printer_start_gate(req: PrinterStartGateRequest) -> dict[str, object]:
    """Evaluate the guarded Bambu start gate without publishing by default."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    if selected_profile.provider != "bambulab_x2d":
        return {
            "ok": False,
            "tool": "printer.bambu.start_gate",
            "provider": selected_profile.provider,
            "failure_code": "BAMBU_START_GATE_NOT_APPLICABLE",
            "message": "Start gate checks are only implemented for the Bambu Lab bridge.",
            "will_publish": False,
            "start_enabled": False,
            "ready_to_publish": False,
        }
    memory = BambuConnectionMemory(selected_profile.connection_memory_path)
    connection = memory.redacted()
    draft = build_bambu_project_file_command_draft(
        serial=str(connection.get("serial") or ""),
        remote_path=req.remote_path,
        subtask_name=req.subtask_name,
        plate_id=req.plate_id,
        use_ams=req.use_ams,
        ams_mapping=req.ams_mapping,
        timelapse=req.timelapse,
        bed_leveling=req.bed_leveling,
        flow_cali=req.flow_cali,
        vibration_cali=req.vibration_cali,
        layer_inspect=req.layer_inspect,
    )
    prepare_result = manager.prepare(
        {
            "runtime_mode": "live",
            "health_only": False,
            "bambu_artifact_url": req.remote_path,
            "subtask_name": req.subtask_name,
            "plate_id": req.plate_id,
            "use_ams": req.use_ams,
            "ams_mapping": req.ams_mapping,
            "timelapse": req.timelapse,
            "bed_leveling": req.bed_leveling,
            "flow_cali": req.flow_cali,
            "vibration_cali": req.vibration_cali,
            "layer_inspect": req.layer_inspect,
        }
    )
    blockers, gate_checks = _bambu_start_gate_blockers(
        draft=draft,
        prepare_result=prepare_result,
        operator_confirmed=req.operator_confirmed,
        guardian_approved=req.guardian_approved,
        dry_run=req.dry_run,
    )
    ready_to_publish = not blockers
    return {
        "ok": True,
        "tool": "printer.bambu.start_gate",
        "provider": selected_profile.provider,
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "connection": connection,
        "draft": draft,
        "preprint_gate": prepare_result.get("preprint_gate", {}),
        "device_screen": prepare_result.get("device_screen", {}),
        "operator_actions": prepare_result.get("operator_actions", []),
        "checks": gate_checks,
        "blockers": blockers,
        "ready_to_publish": ready_to_publish,
        "will_publish": False,
        "start_enabled": ready_to_publish,
        "message": (
            "Bambu start gate is ready, but this endpoint does not publish by itself."
            if ready_to_publish
            else "Bambu start gate blocked; no MQTT publish was attempted."
        ),
    }


@app.post("/api/printer/start-publish")
async def post_printer_start_publish(req: PrinterStartGateRequest) -> dict[str, object]:
    """Publish the Bambu project_file command only after every guarded start gate passes."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    if selected_profile.provider != "bambulab_x2d":
        return {
            "ok": False,
            "tool": "printer.bambu.start_publish",
            "provider": selected_profile.provider,
            "failure_code": "BAMBU_START_PUBLISH_NOT_APPLICABLE",
            "message": "Start publish is only implemented for the Bambu Lab bridge.",
            "will_publish": False,
            "published": False,
            "ready_to_publish": False,
        }
    memory = BambuConnectionMemory(selected_profile.connection_memory_path)
    raw_connection = memory.load()
    raw_auth = raw_connection.get("auth") if isinstance(raw_connection.get("auth"), dict) else {}
    connection = memory.redacted()
    draft = build_bambu_project_file_command_draft(
        serial=str(connection.get("serial") or ""),
        remote_path=req.remote_path,
        subtask_name=req.subtask_name,
        plate_id=req.plate_id,
        use_ams=req.use_ams,
        ams_mapping=req.ams_mapping,
        timelapse=req.timelapse,
        bed_leveling=req.bed_leveling,
        flow_cali=req.flow_cali,
        vibration_cali=req.vibration_cali,
        layer_inspect=req.layer_inspect,
    )
    prepare_result = manager.prepare(
        {
            "runtime_mode": "live",
            "health_only": False,
            "bambu_artifact_url": req.remote_path,
            "subtask_name": req.subtask_name,
            "plate_id": req.plate_id,
            "use_ams": req.use_ams,
            "ams_mapping": req.ams_mapping,
            "timelapse": req.timelapse,
            "bed_leveling": req.bed_leveling,
            "flow_cali": req.flow_cali,
            "vibration_cali": req.vibration_cali,
            "layer_inspect": req.layer_inspect,
        }
    )
    blockers, gate_checks = _bambu_start_gate_blockers(
        draft=draft,
        prepare_result=prepare_result,
        operator_confirmed=req.operator_confirmed,
        guardian_approved=req.guardian_approved,
        dry_run=req.dry_run,
    )
    ready_to_publish = not blockers
    base_payload: dict[str, object] = {
        "tool": "printer.bambu.start_publish",
        "provider": selected_profile.provider,
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "connection": connection,
        "draft": draft,
        "preprint_gate": prepare_result.get("preprint_gate", {}),
        "device_screen": prepare_result.get("device_screen", {}),
        "operator_actions": prepare_result.get("operator_actions", []),
        "checks": gate_checks,
        "blockers": blockers,
        "ready_to_publish": ready_to_publish,
    }
    if not ready_to_publish:
        return {
            **base_payload,
            "ok": False,
            "failure_code": "BAMBU_START_GATE_BLOCKED",
            "will_publish": False,
            "published": False,
            "start_enabled": False,
            "message": "Bambu start publish blocked by start-gate checks; no MQTT command was sent.",
        }

    publish_result = manager.mqtt_client.publish_project_file_command(
        host=str(raw_connection.get("host") or ""),
        serial=str(connection.get("serial") or ""),
        username=str(connection.get("username") or "bblp"),
        access_code=str(raw_auth.get("access_code") or ""),
        topic=str(draft.get("topic") or ""),
        payload=draft.get("payload") if isinstance(draft.get("payload"), dict) else {},
        timeout_sec=manager.config.mqtt.timeout_sec,
    )
    published = bool(publish_result.get("ok"))
    return {
        **base_payload,
        "ok": published,
        "failure_code": "" if published else str(publish_result.get("failure_code") or "BAMBU_MQTT_PUBLISH_FAILED"),
        "will_publish": published,
        "published": published,
        "start_enabled": published,
        "publish_result": publish_result,
        "message": (
            "Bambu MQTT project_file command was published."
            if published
            else "Bambu start gate passed, but MQTT publish failed."
        ),
    }


def _readiness_section(
    *,
    section_id: str,
    label: str,
    status: str,
    detail: str,
    blockers: list[str] | None = None,
) -> dict[str, object]:
    """Return a compact operator-facing readiness section."""
    return {
        "id": section_id,
        "label": label,
        "status": status,
        "detail": detail,
        "blockers": blockers or [],
    }


def _spc_action_for_code(code: str, *, source: str = "gate") -> dict[str, object]:
    """Map backend gate codes into operator-facing actions without inventing status."""
    labels = {
        "BAMBU_FTPS_WRITE_FAILED": (
            "Fix Bambu transfer path",
            "FTPS read works but marker write failed. Confirm LAN/Developer mode, writable storage, or use a verified HTTP artifact route.",
        ),
        "BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED": (
            "Verify sliced-artifact transfer",
            "Run Upload Path Probe or Prepare HTTP Artifact, then rerun SPC Readiness.",
        ),
        "BAMBU_START_DRY_RUN": (
            "Keep dry-run until final approval",
            "Dry-run blocks MQTT publish by design. Disable it only for the final explicit start command.",
        ),
        "BAMBU_OPERATOR_CONFIRMATION_REQUIRED": (
            "Confirm operator start",
            "The operator must explicitly confirm that the Bambu job may be started.",
        ),
        "BAMBU_GUARDIAN_APPROVAL_REQUIRED": (
            "Wait for Guardian approval",
            "Guardian must approve the artifact, printer state, and safety gate before publish.",
        ),
        "BAMBU_DEVICE_SCREEN_START_DISABLED": (
            "Wait for printer start-ready state",
            "The live device screen does not currently report that start is allowed.",
        ),
        "BAMBU_DEVELOPER_MODE_NOT_CONFIRMED": (
            "Confirm Developer Mode",
            "Save the Bambu connection setting after confirming the printer allows local write/control.",
        ),
        "BAMBU_LAN_MODE_NOT_CONFIRMED": (
            "Confirm LAN-only mode",
            "Save the Bambu connection setting after confirming local LAN control is enabled.",
        ),
        "BAMBU_AUTOEJECTION_NOT_REQUESTED": (
            "Configure autoejection provider",
            "Autonomous loop readiness needs a verified provider routine and pre/post eject vision evidence.",
        ),
    }
    label, detail = labels.get(code, ("Review printer gate", "Inspect the corresponding backend gate evidence before proceeding."))
    return {
        "code": code,
        "label": label,
        "detail": detail,
        "severity": "blocking" if "REQUIRED" in code or "FAILED" in code or "DISABLED" in code else "warning",
        "source": source,
    }


def _spc_next_actions(
    *,
    blockers: list[str],
    operator_actions: list[object],
    autoejection_blockers: list[str],
) -> list[dict[str, object]]:
    """Build a de-duplicated operator action list from actual backend evidence."""
    ordered_codes: list[tuple[str, str]] = []
    for code in blockers:
        ordered_codes.append((str(code), "start_gate"))
    for item in operator_actions:
        if isinstance(item, dict) and item.get("code"):
            ordered_codes.append((str(item.get("code")), "operator_action"))
    for code in autoejection_blockers:
        ordered_codes.append((str(code), "autoejection_gate"))
    seen: set[str] = set()
    actions: list[dict[str, object]] = []
    for code, source in ordered_codes:
        if not code or code in seen:
            continue
        seen.add(code)
        actions.append(_spc_action_for_code(code, source=source))
    return actions[:8]


def _spc_readiness_level(
    *,
    level_id: str,
    label: str,
    status: str,
    detail: str,
    blocking_codes: list[str] | None = None,
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return one operator-facing readiness level derived from backend gates."""
    return {
        "id": level_id,
        "label": label,
        "status": status,
        "detail": detail,
        "blocking_codes": blocking_codes or [],
        "evidence": evidence or {},
    }


def _looks_like_local_policy_ref(policy_ref: str) -> bool:
    """Return whether a policy reference should be proven on local disk."""
    text = str(policy_ref or "").strip()
    if not text or text.startswith("fake://"):
        return False
    return text.startswith(("/", "./", "../", "~", "outputs/", "artifacts/", "runs/"))


def _bambu_manipulation_consumer_readiness(*, mode: str = "live") -> dict[str, object]:
    """Verify that Bambu autoejection has an actual Manipulation Agent consumer path."""
    profile_path = Path(MANIPULATION_AGENT_PROFILE_PATH)
    profile_saved = profile_path.exists()
    raw: dict[str, object] = {}
    if profile_saved:
        try:
            loaded = json.loads(profile_path.read_text(encoding="utf-8"))
            raw = loaded if isinstance(loaded, dict) else {}
        except Exception:
            raw = {}
    profile = normalize_manipulation_agent_profile(raw)
    strategy = str(profile.get("manipulation_strategy") or "")
    task_id = str(profile.get("task_id") or profile.get("skill_id") or "")
    profile_id = str(profile.get("profile_id") or "")
    policy_path = str(profile.get("policy_path") or "")
    policy_checkpoint_path = str(profile.get("policy_checkpoint_path") or "")
    policy_repo_id = str(profile.get("policy_repo_id") or "")
    policy_ref = policy_path or policy_checkpoint_path or policy_repo_id
    blockers: list[str] = []
    if not profile_saved:
        blockers.append("MANIPULATION_AGENT_DEFAULTS_NOT_SAVED")
    if strategy not in {"pi05_lerobot_policy", "lerobot_policy"}:
        blockers.append("MANIPULATION_AGENT_STRATEGY_NOT_ROLLOUT")
    if task_id != "transfer_to_utm":
        blockers.append("MANIPULATION_AGENT_TASK_NOT_3DP_TO_UTM")
    if not profile_id:
        blockers.append("MANIPULATION_AGENT_PROFILE_ID_REQUIRED")
    if not policy_ref:
        blockers.append("MANIPULATION_POLICY_REFERENCE_REQUIRED")
    if policy_ref.startswith("fake://") and str(mode).lower() == "live":
        blockers.append("MANIPULATION_FAKE_POLICY_NOT_ALLOWED_IN_LIVE")
    policy_local_path = ""
    if _looks_like_local_policy_ref(policy_ref):
        local_path = Path(policy_ref).expanduser()
        if not local_path.is_absolute():
            local_path = resolve_path(str(local_path))
        policy_local_path = str(local_path)
        if not local_path.exists():
            blockers.append("MANIPULATION_POLICY_LOCAL_PATH_NOT_FOUND")
    ready = not blockers
    return {
        "schema": "bambu_autoejection_consumer_readiness.v1",
        "ready": ready,
        "mode": str(mode or "live"),
        "profile_saved": profile_saved,
        "profile_path": str(profile_path),
        "profile_id": profile_id,
        "strategy": strategy,
        "task_id": task_id,
        "skill_id": str(profile.get("skill_id") or ""),
        "source_location": str(profile.get("source_location") or ""),
        "target_location": str(profile.get("target_location") or ""),
        "policy_type": str(profile.get("policy_type") or ""),
        "policy_backend": str(profile.get("policy_backend") or ""),
        "policy_ref": policy_ref,
        "policy_local_path": policy_local_path,
        "blockers": blockers,
    }


def _bambu_autoejection_handoff_payload(
    autoejection: dict[str, object],
    *,
    position: str = "post_print",
    object_size_mm: list[float] | None = None,
    mode: str = "live",
    consumer_readiness: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build the safe Bambu autoejection provider handoff packet without starting motion."""
    if not autoejection.get("can_run_test"):
        return {}
    consumer = consumer_readiness or _bambu_manipulation_consumer_readiness(mode=mode)
    if not consumer.get("ready"):
        return {}
    return {
        "schema": "bambu_autoejection_provider_handoff.v1",
        "status": "provider_handoff_ready",
        "provider": str(autoejection.get("provider") or "none"),
        "routine_id": str(autoejection.get("verified_routine_id") or ""),
        "pre_eject_vision_profile": str(autoejection.get("pre_eject_vision_profile") or ""),
        "post_eject_vision_profile": str(autoejection.get("post_eject_vision_profile") or ""),
        "position": position,
        "object_size_mm": [float(item) for item in object_size_mm] if object_size_mm else [],
        "mode": mode,
        "next_owner": "ManipulationAgent",
        "recommended_consumer_agent": "ManipulationAgent",
        "next_tool": "lerobot.manipulation-agent.run",
        "requires_provider_executor": True,
        "requires_guardian_approval": True,
        "requires_operator_confirmation": True,
        "motion_started": False,
        "dry_run_only": True,
        "consumer_readiness": consumer,
        "consumer_profile_id": str(consumer.get("profile_id") or ""),
        "consumer_policy_ref": str(consumer.get("policy_ref") or ""),
    }


@app.post("/api/printer/spc-readiness")
async def post_printer_spc_readiness(req: PrinterSpcReadinessRequest) -> dict[str, object]:
    """Aggregate real printer gates for the Specimen Making Agent without publishing."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    if selected_profile.provider != "bambulab_x2d":
        return {
            "ok": False,
            "tool": "printer.spc_readiness",
            "provider": selected_profile.provider,
            "failure_code": "SPC_READINESS_NOT_APPLICABLE",
            "message": "SPC readiness aggregation is currently implemented for the Bambu Lab device bridge.",
            "ready_for_live_print": False,
            "autonomous_cycle_ready": False,
            "will_publish": False,
            "sections": [],
        }

    memory = BambuConnectionMemory(selected_profile.connection_memory_path)
    connection = memory.redacted()
    draft = build_bambu_project_file_command_draft(
        serial=str(connection.get("serial") or ""),
        remote_path=req.remote_path,
        subtask_name=req.subtask_name,
        plate_id=req.plate_id,
        use_ams=req.use_ams,
        ams_mapping=req.ams_mapping,
        timelapse=req.timelapse,
        bed_leveling=req.bed_leveling,
        flow_cali=req.flow_cali,
        vibration_cali=req.vibration_cali,
        layer_inspect=req.layer_inspect,
    )
    prepare_result = manager.prepare(
        {
            "runtime_mode": req.mode,
            "health_only": False,
            "bambu_artifact_url": req.remote_path,
            "subtask_name": req.subtask_name,
            "plate_id": req.plate_id,
            "use_ams": req.use_ams,
            "ams_mapping": req.ams_mapping,
            "timelapse": req.timelapse,
            "bed_leveling": req.bed_leveling,
            "flow_cali": req.flow_cali,
            "vibration_cali": req.vibration_cali,
            "layer_inspect": req.layer_inspect,
        }
    )
    blockers, gate_checks = _bambu_start_gate_blockers(
        draft=draft,
        prepare_result=prepare_result,
        operator_confirmed=req.operator_confirmed,
        guardian_approved=req.guardian_approved,
        dry_run=req.dry_run,
    )
    device_screen = prepare_result.get("device_screen") if isinstance(prepare_result.get("device_screen"), dict) else {}
    device_connection = device_screen.get("connection") if isinstance(device_screen.get("connection"), dict) else {}
    preprint_gate = prepare_result.get("preprint_gate") if isinstance(prepare_result.get("preprint_gate"), dict) else {}
    raw_preprint_blockers = preprint_gate.get("blockers", [])
    preprint_blockers = [str(item) for item in raw_preprint_blockers] if isinstance(raw_preprint_blockers, list) else []
    autoejection = manager.autoejection_status()
    raw_autoejection_blockers = autoejection.get("blockers", [])
    autoejection_blockers = [str(item) for item in raw_autoejection_blockers] if isinstance(raw_autoejection_blockers, list) else []
    connection_ready = bool(connection.get("host")) and bool(connection.get("serial")) and bool(connection.get("access_code_set"))
    mqtt_ready = device_connection.get("mqtt") in {"connected", "virtual"}
    transfer_ready = device_connection.get("transfer") in {"connected", "virtual"}
    ready_for_live_print = not blockers
    approval_blockers = [
        code
        for code in blockers
        if code in {"BAMBU_START_DRY_RUN", "BAMBU_OPERATOR_CONFIRMATION_REQUIRED", "BAMBU_GUARDIAN_APPROVAL_REQUIRED"}
    ]
    technical_blockers = [code for code in blockers if code not in set(approval_blockers)]
    technical_ready_for_start = not technical_blockers
    approval_ready_for_start = not approval_blockers
    autoejection_ready = bool(autoejection.get("can_run_test", False))
    consumer_readiness = _bambu_manipulation_consumer_readiness(mode=req.mode)
    autoejection_handoff = _bambu_autoejection_handoff_payload(
        autoejection,
        position="post_print",
        mode=req.mode,
        consumer_readiness=consumer_readiness,
    )
    if autoejection_ready and not consumer_readiness.get("ready"):
        autoejection_blockers = [*autoejection_blockers, *[str(item) for item in consumer_readiness.get("blockers", [])]]
        autoejection_ready = False
        autoejection_handoff = {}
    autonomous_cycle_ready = ready_for_live_print and autoejection_ready
    status = "ready" if ready_for_live_print else "blocked"
    operator_actions = prepare_result.get("operator_actions", [])
    operator_actions_list = operator_actions if isinstance(operator_actions, list) else []
    next_actions = _spc_next_actions(
        blockers=blockers,
        operator_actions=operator_actions_list,
        autoejection_blockers=autoejection_blockers,
    )
    primary_blocker = blockers[0] if blockers else (autoejection_blockers[0] if autoejection_blockers else "")
    operator_summary = {
        "title": "Ready for explicit Bambu start" if ready_for_live_print else "Blocked before Bambu start",
        "severity": "ready" if ready_for_live_print else "blocked",
        "primary_blocker": primary_blocker,
        "print_gate": "ready" if ready_for_live_print else "blocked",
        "technical_gate": "ready" if technical_ready_for_start else "blocked",
        "approval_gate": "ready" if approval_ready_for_start else "waiting",
        "autonomous_loop": "ready" if autonomous_cycle_ready else "attention",
        "publish_policy": "no MQTT publish from SPC readiness",
    }
    evidence = {
        "device_connection": {
            "mqtt": device_connection.get("mqtt", "unknown"),
            "transfer": device_connection.get("transfer", "unknown"),
            "video": device_connection.get("video", "unknown"),
        },
        "job": device_screen.get("job", {}) if isinstance(device_screen.get("job"), dict) else {},
        "preprint_gate_state": preprint_gate.get("state", "unknown"),
        "autoejection_status": autoejection.get("status", "unknown"),
        "autoejection_handoff": autoejection_handoff,
        "autoejection_consumer_readiness": consumer_readiness,
    }
    preprint_checks = preprint_gate.get("checks") if isinstance(preprint_gate.get("checks"), dict) else {}
    transfer_blockers = [
        code
        for code in blockers
        if code
        in {
            "BAMBU_FTPS_WRITE_FAILED",
            "BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED",
            "BAMBU_START_COMMAND_DRAFT_NOT_PREPARED",
            "BAMBU_START_DRAFT_INVALID",
        }
    ]
    connection_blockers: list[str] = []
    if not connection_ready:
        connection_blockers.append("BAMBU_CONNECTION_MEMORY_INCOMPLETE")
    if not mqtt_ready:
        connection_blockers.append("BAMBU_MQTT_NOT_AUTHENTICATED")
    transfer_verified = bool(preprint_checks.get("storage_transfer_path_verified", False)) and transfer_ready
    readiness_levels = [
        _spc_readiness_level(
            level_id="connection",
            label="Printer connection",
            status="ready" if connection_ready and mqtt_ready else "blocked",
            detail=f"mqtt={device_connection.get('mqtt', 'unknown')} · host={connection.get('host') or 'missing'}",
            blocking_codes=connection_blockers,
            evidence={
                "host": connection.get("host", ""),
                "serial": connection.get("serial", ""),
                "mqtt": device_connection.get("mqtt", "unknown"),
                "access_code_set": bool(connection.get("access_code_set")),
            },
        ),
        _spc_readiness_level(
            level_id="transfer_path",
            label="Sliced artifact transfer",
            status="ready" if transfer_verified and not transfer_blockers else "blocked",
            detail=f"transfer={device_connection.get('transfer', 'unknown')} · storage_verified={bool(preprint_checks.get('storage_transfer_path_verified', False))}",
            blocking_codes=transfer_blockers,
            evidence={
                "transfer": device_connection.get("transfer", "unknown"),
                "preprint_gate_state": preprint_gate.get("state", "unknown"),
                "storage_transfer_path_verified": bool(preprint_checks.get("storage_transfer_path_verified", False)),
            },
        ),
        _spc_readiness_level(
            level_id="start_approval",
            label="Operator / Guardian approval",
            status="ready" if approval_ready_for_start else "waiting",
            detail=(
                f"operator={bool(req.operator_confirmed)} · guardian={bool(req.guardian_approved)}"
                f" · dry_run={bool(req.dry_run)}"
            ),
            blocking_codes=approval_blockers,
            evidence={
                "operator_confirmed": bool(req.operator_confirmed),
                "guardian_approved": bool(req.guardian_approved),
                "dry_run": bool(req.dry_run),
            },
        ),
        _spc_readiness_level(
            level_id="publish_command",
            label="MQTT publish command",
            status="ready" if ready_for_live_print else "blocked",
            detail="ready to publish from explicit Publish Start" if ready_for_live_print else "no MQTT command will be published",
            blocking_codes=blockers,
            evidence={
                "draft_valid": bool(draft.get("ok")),
                "device_screen_can_start_print": bool(gate_checks.get("device_screen_can_start_print")),
                "will_publish_from_spc": False,
            },
        ),
        _spc_readiness_level(
            level_id="autoejection",
            label="Autoejection loop",
            status="ready" if autoejection_ready else "warning",
            detail=f"status={autoejection.get('status', 'unknown')} · provider={autoejection.get('provider') or 'none'}",
            blocking_codes=autoejection_blockers,
            evidence={
                "can_run_test": bool(autoejection.get("can_run_test", False)),
                "routine": autoejection.get("verified_routine_id", ""),
                "pre_vision": autoejection.get("pre_eject_vision_profile", ""),
                "post_vision": autoejection.get("post_eject_vision_profile", ""),
                "handoff": autoejection_handoff,
                "consumer_readiness": consumer_readiness,
            },
        ),
    ]

    sections = [
        _readiness_section(
            section_id="printer_connection",
            label="Printer connection",
            status="ready" if connection_ready else "blocked",
            detail=f"{connection.get('host') or 'host missing'} · {connection.get('serial') or 'serial missing'}",
            blockers=[] if connection_ready else ["BAMBU_CONNECTION_MEMORY_INCOMPLETE"],
        ),
        _readiness_section(
            section_id="device_screen",
            label="Live device screen",
            status="ready" if mqtt_ready and transfer_ready else "blocked",
            detail=f"mqtt={device_connection.get('mqtt', 'unknown')} · transfer={device_connection.get('transfer', 'unknown')}",
            blockers=[] if mqtt_ready and transfer_ready else ["BAMBU_DEVICE_SCREEN_NOT_READY"],
        ),
        _readiness_section(
            section_id="preprint_gate",
            label="Pre-print communication gate",
            status="ready" if not preprint_blockers else "blocked",
            detail=f"state={preprint_gate.get('state', 'unknown')}",
            blockers=preprint_blockers,
        ),
        _readiness_section(
            section_id="start_gate",
            label="MQTT start-command gate",
            status="ready" if ready_for_live_print else "blocked",
            detail="ready to publish after explicit run command" if ready_for_live_print else "publish blocked; no MQTT command sent",
            blockers=blockers,
        ),
        _readiness_section(
            section_id="autoejection_gate",
            label="Autoejection gate",
            status="ready" if autoejection_ready else "warning",
            detail=(
                f"routine={autoejection.get('verified_routine_id') or 'not configured'}"
                f" · provider={autoejection.get('provider') or 'none'}"
            ),
            blockers=autoejection_blockers,
        ),
    ]

    return {
        "ok": True,
        "tool": "printer.spc_readiness",
        "provider": selected_profile.provider,
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "connection": connection,
        "status": status,
        "technical_ready_for_start": technical_ready_for_start,
        "approval_ready_for_start": approval_ready_for_start,
        "ready_for_live_print": ready_for_live_print,
        "autonomous_cycle_ready": autonomous_cycle_ready,
        "will_publish": False,
        "start_enabled": ready_for_live_print,
        "draft": draft,
        "device_screen": device_screen,
        "preprint_gate": preprint_gate,
        "start_gate": {
            "checks": gate_checks,
            "blockers": blockers,
            "ready_to_publish": ready_for_live_print,
            "will_publish": False,
        },
        "autoejection": autoejection,
        "autoejection_handoff": autoejection_handoff,
        "consumer_readiness": consumer_readiness,
        "operator_summary": operator_summary,
        "readiness_levels": readiness_levels,
        "next_actions": next_actions,
        "evidence": evidence,
        "sections": sections,
        "blockers": blockers,
        "operator_actions": operator_actions_list,
        "message": (
            "Specimen Making Agent can hand off to live print start after explicit operator run command."
            if ready_for_live_print
            else "Specimen Making Agent is waiting on printer readiness gates; no print command was published."
        ),
    }


@app.post("/api/printer/bambu-slice-artifact")
async def post_printer_bambu_slice_artifact(req: PrinterBambuSliceArtifactRequest) -> dict[str, object]:
    """Create a real Bambu sliced artifact from STL/3MF without upload or print start."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    if selected_profile.provider != "bambulab_x2d":
        return {
            "ok": False,
            "tool": "printer.bambu.slice_artifact",
            "provider": selected_profile.provider,
            "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
            "failure_code": "BAMBU_SLICE_ARTIFACT_NOT_APPLICABLE",
            "message": "Bambu Studio slicing is only implemented for the Bambu Lab bridge.",
            "will_publish": False,
            "start_enabled": False,
        }
    runner = BambuStudioSlicerRunner(manager.config.slicer, repo_root=resolve_path("."))
    result = runner.slice(
        source_path=req.source_path,
        specimen_id=req.specimen_id,
        load_settings=req.load_settings or None,
        load_filaments=req.load_filaments or None,
        extra_args=req.extra_args,
        timeout_sec=req.timeout_sec,
    )
    artifact = {
        "source_path": result.get("source_path", req.source_path),
        "sliced_artifact_path": result.get("sliced_artifact_path", ""),
        "size_bytes": result.get("size_bytes", 0),
        "sha256": result.get("sha256", ""),
    }
    return {
        **result,
        "provider": selected_profile.provider,
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "slicer": result.get("slicer") or _selected_printer_slicer_payload(manager, _printer_workflow().config),
        "artifact": artifact,
        "will_publish": False,
        "start_enabled": False,
    }


@app.post("/api/printer/http-artifact-route")
async def post_printer_http_artifact_route(req: PrinterHttpArtifactRouteRequest, request: Request) -> dict[str, object]:
    """Expose a sliced Bambu artifact through an HTTP URL the printer can fetch."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    if selected_profile.provider != "bambulab_x2d":
        return {
            "ok": False,
            "provider": selected_profile.provider,
            "failure_code": "BAMBU_HTTP_ARTIFACT_ROUTE_NOT_APPLICABLE",
            "message": "HTTP artifact routing is only implemented for the Bambu Lab bridge.",
        }
    memory = BambuConnectionMemory(selected_profile.connection_memory_path)
    connection = memory.redacted()
    source = _safe_bambu_http_artifact_source(req.artifact_path)
    token = uuid.uuid4().hex
    filename = _safe_bambu_http_filename(source)
    export_path = _safe_bambu_http_export_path(token, filename)
    export_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, export_path)
    digest = hashlib.sha256(export_path.read_bytes()).hexdigest()
    public_base = _bambu_http_public_base_url(
        request,
        printer_host=str(connection.get("host") or ""),
        override=req.public_base_url,
    )
    url_path = f"/printer-artifacts/bambu/{token}/{quote(filename, safe='')}"
    artifact_url = f"{public_base}{url_path}"
    draft = build_bambu_project_file_command_draft(
        serial=str(connection.get("serial") or ""),
        remote_path=artifact_url,
        subtask_name=req.subtask_name or source.stem,
        plate_id=req.plate_id,
        use_ams=req.use_ams,
        ams_mapping=req.ams_mapping,
        timelapse=req.timelapse,
        bed_leveling=req.bed_leveling,
        flow_cali=req.flow_cali,
        vibration_cali=req.vibration_cali,
        layer_inspect=req.layer_inspect,
    )
    if not draft.get("ok"):
        raise HTTPException(status_code=400, detail=str(draft.get("failure_code") or "BAMBU_HTTP_ARTIFACT_DRAFT_FAILED"))
    fetch_probe = (
        await _probe_bambu_http_artifact_fetch(
            artifact_url,
            expected_sha256=digest,
            timeout_sec=req.fetch_timeout_sec,
        )
        if req.verify_fetch
        else {
            "ok": False,
            "skipped": True,
            "failure_code": "BAMBU_HTTP_ARTIFACT_FETCH_PROBE_SKIPPED",
            "message": "Artifact URL fetch probe was skipped by request.",
        }
    )
    printer_fetch_ready = bool(fetch_probe.get("ok"))
    operator_actions = [
        {
            "code": "BAMBU_HTTP_ARTIFACT_FETCH_VERIFIED",
            "severity": "info",
            "message": "ATR served the prepared artifact URL and sha256 matched. MQTT publish is still disabled until explicit approval.",
        }
    ] if printer_fetch_ready else [
        {
            "code": str(fetch_probe.get("failure_code") or "BAMBU_HTTP_ARTIFACT_SERVER_BIND_CHECK_REQUIRED"),
            "severity": "warning",
            "message": (
                f"{fetch_probe.get('message') or 'Artifact URL fetch probe failed.'} "
                "Ensure the ATR server is bound to a LAN-reachable host/port before publishing this draft to the printer."
            ),
        }
    ]
    return {
        "ok": True,
        "tool": "printer.bambu.http_artifact_route",
        "provider": selected_profile.provider,
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "connection": connection,
        "artifact": {
            "source_path": str(source),
            "export_path": str(export_path),
            "filename": filename,
            "size_bytes": export_path.stat().st_size,
            "sha256": digest,
        },
        "artifact_url": artifact_url,
        "artifact_url_path": url_path,
        "server_fetch_probe": fetch_probe,
        "printer_fetch_ready": printer_fetch_ready,
        "start_command_draft": draft,
        "will_publish": False,
        "start_enabled": False,
        "operator_actions": operator_actions,
    }


def _bambu_prestart_step(step_id: str, label: str, result: dict[str, object], *, ok: bool | None = None) -> dict[str, object]:
    """Compact one backend result into an operator-facing pre-start step."""
    resolved_ok = bool(result.get("ok")) if ok is None else bool(ok)
    detail = (
        result.get("failure_code")
        or result.get("status")
        or result.get("message")
        or result.get("artifact_url")
        or result.get("sliced_artifact_path")
        or ""
    )
    return {
        "id": step_id,
        "label": label,
        "status": "ok" if resolved_ok else "blocked",
        "ok": resolved_ok,
        "detail": str(detail),
    }


@app.post("/api/printer/bambu-prestart-check")
async def post_printer_bambu_prestart_check(req: PrinterBambuPrestartCheckRequest, request: Request) -> dict[str, object]:
    """Run the Bambu pre-start path up to guarded start readiness without publishing."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    selected_printer = manager._selected_printer_payload(selected_profile, selection_reason)
    if selected_profile.provider != "bambulab_x2d":
        return {
            "ok": False,
            "tool": "printer.bambu.prestart_check",
            "provider": selected_profile.provider,
            "selected_printer": selected_printer,
            "status": "blocked",
            "failure_code": "BAMBU_PRESTART_CHECK_NOT_APPLICABLE",
            "message": "Bambu pre-start check is only implemented for the Bambu Lab bridge.",
            "will_publish": False,
            "published": False,
            "start_enabled": False,
        }

    steps: list[dict[str, object]] = []
    source_path = str(req.source_path or "").strip()
    artifact_path = str(req.artifact_path or "").strip()
    slice_result: dict[str, object] = {}
    if source_path:
        slice_result = await post_printer_bambu_slice_artifact(
            PrinterBambuSliceArtifactRequest(
                source_path=source_path,
                specimen_id=req.specimen_id,
                load_settings=req.load_settings,
                load_filaments=req.load_filaments,
                extra_args=req.extra_args,
                timeout_sec=req.timeout_sec,
            )
        )
        steps.append(_bambu_prestart_step("slice_artifact", "Bambu Studio slicing", slice_result))
        artifact_path = str(slice_result.get("sliced_artifact_path") or "")
        if not slice_result.get("ok"):
            return {
                "ok": False,
                "tool": "printer.bambu.prestart_check",
                "provider": selected_profile.provider,
                "selected_printer": selected_printer,
                "status": "blocked",
                "failure_code": str(slice_result.get("failure_code") or "BAMBU_PRESTART_SLICE_FAILED"),
                "steps": steps,
                "slice_artifact": slice_result,
                "sliced_artifact_path": artifact_path,
                "will_publish": False,
                "published": False,
                "start_enabled": False,
                "message": "Bambu pre-start check stopped before transfer because slicing failed.",
            }
    else:
        steps.append(
            {
                "id": "slice_artifact",
                "label": "Bambu Studio slicing",
                "status": "skipped" if artifact_path else "blocked",
                "ok": bool(artifact_path),
                "detail": "using existing sliced artifact" if artifact_path else "source_path or artifact_path required",
            }
        )
        if not artifact_path:
            return {
                "ok": False,
                "tool": "printer.bambu.prestart_check",
                "provider": selected_profile.provider,
                "selected_printer": selected_printer,
                "status": "blocked",
                "failure_code": "BAMBU_PRESTART_ARTIFACT_REQUIRED",
                "steps": steps,
                "will_publish": False,
                "published": False,
                "start_enabled": False,
                "message": "Provide a source STL/3MF or an existing sliced artifact path.",
            }

    try:
        http_route = await post_printer_http_artifact_route(
            PrinterHttpArtifactRouteRequest(
                artifact_path=artifact_path,
                public_base_url=req.public_base_url,
                subtask_name=req.subtask_name or req.specimen_id or "atr-bambu-prestart",
                plate_id=req.plate_id,
                use_ams=req.use_ams,
                ams_mapping=req.ams_mapping,
                timelapse=req.timelapse,
                bed_leveling=req.bed_leveling,
                flow_cali=req.flow_cali,
                vibration_cali=req.vibration_cali,
                layer_inspect=req.layer_inspect,
                verify_fetch=req.verify_fetch,
                fetch_timeout_sec=req.fetch_timeout_sec,
            ),
            request,
        )
    except HTTPException as exc:
        http_route = {
            "ok": False,
            "tool": "printer.bambu.http_artifact_route",
            "failure_code": str(exc.detail),
            "message": str(exc.detail),
            "printer_fetch_ready": False,
        }
    http_ok = bool(http_route.get("ok")) and bool(http_route.get("printer_fetch_ready"))
    steps.append(_bambu_prestart_step("http_artifact_route", "HTTP artifact route", http_route, ok=http_ok))
    if not http_ok:
        return {
            "ok": False,
            "tool": "printer.bambu.prestart_check",
            "provider": selected_profile.provider,
            "selected_printer": selected_printer,
            "status": "blocked",
            "failure_code": str(
                http_route.get("failure_code")
                or (http_route.get("server_fetch_probe", {}) if isinstance(http_route.get("server_fetch_probe"), dict) else {}).get("failure_code")
                or "BAMBU_PRESTART_HTTP_ARTIFACT_NOT_VERIFIED"
            ),
            "steps": steps,
            "slice_artifact": slice_result,
            "http_artifact_route": http_route,
            "sliced_artifact_path": artifact_path,
            "artifact_url": str(http_route.get("artifact_url") or ""),
            "will_publish": False,
            "published": False,
            "start_enabled": False,
            "message": "Bambu pre-start check stopped before start gate because the printer-reachable artifact route is not verified.",
        }

    artifact_url = str(http_route.get("artifact_url") or "")
    start_req = PrinterStartGateRequest(
        remote_path=artifact_url,
        subtask_name=req.subtask_name or req.specimen_id or "atr-bambu-prestart",
        plate_id=req.plate_id,
        use_ams=req.use_ams,
        ams_mapping=req.ams_mapping,
        timelapse=req.timelapse,
        bed_leveling=req.bed_leveling,
        flow_cali=req.flow_cali,
        vibration_cali=req.vibration_cali,
        layer_inspect=req.layer_inspect,
        operator_confirmed=req.operator_confirmed,
        guardian_approved=req.guardian_approved,
        dry_run=req.dry_run,
    )
    start_gate = await post_printer_start_gate(start_req)
    steps.append(_bambu_prestart_step("start_gate", "Guarded start gate", start_gate, ok=bool(start_gate.get("ready_to_publish"))))
    spc_readiness = await post_printer_spc_readiness(
        PrinterSpcReadinessRequest(
            mode=req.mode,
            **start_req.model_dump(),
        )
    )
    steps.append(
        _bambu_prestart_step(
            "spc_readiness",
            "SPC readiness report",
            spc_readiness,
            ok=bool(spc_readiness.get("ready_for_live_print")),
        )
    )
    autoejection_handoff = (
        spc_readiness.get("autoejection_handoff") if isinstance(spc_readiness.get("autoejection_handoff"), dict) else {}
    )
    steps.append(
        {
            "id": "autoejection_handoff",
            "label": "Autoejection handoff",
            "status": "ok" if autoejection_handoff else "blocked",
            "ok": bool(autoejection_handoff),
            "detail": str(autoejection_handoff.get("routine_id") or "not configured") if autoejection_handoff else "not configured",
        }
    )
    ready_to_publish = bool(start_gate.get("ready_to_publish"))
    return {
        "ok": bool(http_ok and ready_to_publish),
        "tool": "printer.bambu.prestart_check",
        "provider": selected_profile.provider,
        "selected_printer": selected_printer,
        "status": "ready_to_publish_not_started" if ready_to_publish else "blocked",
        "steps": steps,
        "slice_artifact": slice_result,
        "http_artifact_route": http_route,
        "start_gate": start_gate,
        "spc_readiness": spc_readiness,
        "autoejection_handoff": autoejection_handoff,
        "sliced_artifact_path": artifact_path,
        "artifact_url": artifact_url,
        "ready_to_publish": ready_to_publish,
        "will_publish": False,
        "published": False,
        "start_enabled": ready_to_publish,
        "message": (
            "Bambu artifact, HTTP route, and guarded start gate are ready. No MQTT command was published."
            if ready_to_publish
            else "Bambu pre-start check completed with blockers. No MQTT command was published."
        ),
    }


@app.get("/printer-artifacts/bambu/{token}/{filename}")
async def get_bambu_http_artifact(token: str, filename: str) -> FileResponse:
    """Serve a copied Bambu sliced artifact for printer-side HTTP fetch tests."""
    path = _safe_bambu_http_export_path(token, filename)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Bambu HTTP artifact not found")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream", filename=path.name)


@app.get("/api/printer/profile")
async def get_printer_profile() -> dict[str, object]:
    """Return operator-controlled 3DP print profile defaults."""
    manager = _printer_bridge_manager()
    workflow = _printer_workflow()
    config = workflow.config
    profile = _selected_print_profile(manager)
    selected_profile, selection_reason = manager.fleet_selection()
    return {
        "ok": True,
        "profile": profile,
        "profile_path": str(PRUSA_PRINT_PROFILE_PATH),
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "connection_memory_path": str(selected_profile.connection_memory_path),
        "live_gates": _selected_printer_profile_live_gates(manager, config),
        "auto_ejection": _selected_printer_autoejection_payload(manager, config, profile),
        "slicer": _selected_printer_slicer_payload(manager, config),
    }


@app.post("/api/printer/profile")
async def post_printer_profile(req: PrinterProfileRequest) -> dict[str, object]:
    """Persist operator-controlled 3DP print profile defaults."""
    manager = _printer_bridge_manager()
    workflow = _printer_workflow()
    config = workflow.config
    profile = save_prusa_print_profile(req.model_dump())
    profile = _selected_print_profile(manager)
    selected_profile, selection_reason = manager.fleet_selection()
    return {
        "ok": True,
        "profile": profile,
        "profile_path": str(PRUSA_PRINT_PROFILE_PATH),
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "connection_memory_path": str(selected_profile.connection_memory_path),
        "live_gates": _selected_printer_profile_live_gates(manager, config),
        "auto_ejection": _selected_printer_autoejection_payload(manager, config, profile),
        "slicer": _selected_printer_slicer_payload(manager, config),
        "message": "3DP print profile saved for the active printer bridge.",
    }


@app.get("/api/printer/autoejection-status")
async def get_printer_autoejection_status() -> dict[str, object]:
    """Return selected-printer autoejection capability without running hardware motion."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    if selected_profile.provider == "bambulab_x2d":
        status = manager.autoejection_status()
        consumer_readiness = _bambu_manipulation_consumer_readiness(mode="live")
        blockers = [str(item) for item in status.get("blockers", [])] if isinstance(status.get("blockers"), list) else []
        if status.get("can_run_test") and not consumer_readiness.get("ready"):
            blockers = [*blockers, *[str(item) for item in consumer_readiness.get("blockers", [])]]
        return {
            "ok": True,
            "tool": "printer.autoejection_status",
            "provider": selected_profile.provider,
            "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
            "autoejection": status,
            "consumer_readiness": consumer_readiness,
            "can_run_test": bool(status.get("can_run_test", False) and consumer_readiness.get("ready")),
            "blockers": blockers,
            "settings_path": str(manager.config.autoejection_memory_path),
            "message": (
                "Bambu autoejection routine and Manipulation Agent consumer are configured and testable."
                if status.get("can_run_test") and consumer_readiness.get("ready")
                else "Bambu autoejection provider is configured, but the Manipulation Agent consumer is not ready."
                if status.get("can_run_test")
                else "Bambu autoejection is blocked until a verified provider routine and vision evidence are configured."
            ),
        }
    workflow = _printer_workflow()
    profile = load_prusa_print_profile()
    payload = _selected_printer_autoejection_payload(manager, workflow.config, profile)
    return {
        "ok": True,
        "tool": "printer.autoejection_status",
        "provider": selected_profile.provider,
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "autoejection": payload,
        "can_run_test": bool(payload.get("enabled", False)),
        "blockers": [] if payload.get("enabled", False) else ["AUTOEJECTION_DISABLED"],
    }


@app.post("/api/printer/autoejection-config")
async def post_printer_autoejection_config(req: PrinterAutoejectionConfigRequest) -> dict[str, object]:
    """Persist operator-verified Bambu autoejection settings without running motion."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    if selected_profile.provider != "bambulab_x2d":
        return {
            "ok": False,
            "tool": "printer.autoejection_config",
            "provider": selected_profile.provider,
            "failure_code": "BAMBU_AUTOEJECTION_CONFIG_NOT_APPLICABLE",
            "message": "Bambu autoejection config is only applicable to the Bambu Lab bridge.",
        }
    status = manager.save_autoejection_config(req.model_dump())
    consumer_readiness = _bambu_manipulation_consumer_readiness(mode="live")
    blockers = [str(item) for item in status.get("blockers", [])] if isinstance(status.get("blockers"), list) else []
    if status.get("can_run_test") and not consumer_readiness.get("ready"):
        blockers = [*blockers, *[str(item) for item in consumer_readiness.get("blockers", [])]]
    return {
        "ok": True,
        "tool": "printer.autoejection_config",
        "provider": selected_profile.provider,
        "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
        "autoejection": status,
        "consumer_readiness": consumer_readiness,
        "can_run_test": bool(status.get("can_run_test", False) and consumer_readiness.get("ready")),
        "blockers": blockers,
        "settings_path": str(manager.config.autoejection_memory_path),
        "message": (
            "Bambu autoejection routine and Manipulation Agent consumer are configured and testable."
            if status.get("can_run_test") and consumer_readiness.get("ready")
            else "Bambu autoejection config saved, but the Manipulation Agent consumer is not ready."
            if status.get("can_run_test")
            else "Bambu autoejection config saved, but required routine or vision evidence is still missing."
        ),
    }


@app.post("/api/printer/autoejection-test")
async def post_printer_autoejection_test(req: PrinterAutoejectionTestRequest) -> dict[str, object]:
    """Run a standalone autoejection test using the same ejection G-code builder."""
    manager = _printer_bridge_manager()
    selected_profile, selection_reason = manager.fleet_selection()
    if selected_profile.provider == "bambulab_x2d":
        autoejection = manager.autoejection_status()
        if not autoejection.get("enabled"):
            result = {
                "ok": False,
                "tool": "printer.autoejection_test",
                "provider": "bambulab_x2d",
                "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
                "status": "blocked",
                "failure_code": "BAMBU_AUTOEJECTION_NOT_CONFIGURED",
                "message": "Bambu autoejection routine is not configured or verified yet.",
                "autoejection": autoejection,
                "step_trace": [{"step": "AUTOEJECTION_GATE", "status": "blocked", "detail": "not_configured"}],
            }
            await controller.emit_workspace_result(
                workspace="printer",
                tool="printer.autoejection_test",
                result=result,
                stage=Stage.SPECIMEN,
                module_id="specimen",
                agent="specimen_agent",
                workflow="autoejection_test",
            )
            return result
        consumer_readiness = _bambu_manipulation_consumer_readiness(mode=req.mode)
        if not consumer_readiness.get("ready"):
            result = {
                "ok": False,
                "tool": "printer.autoejection_test",
                "provider": "bambulab_x2d",
                "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
                "status": "blocked",
                "failure_code": "BAMBU_AUTOEJECTION_CONSUMER_NOT_READY",
                "message": "Bambu autoejection provider is configured, but Manipulation Agent consumer defaults or policy evidence are not ready.",
                "autoejection": autoejection,
                "consumer_readiness": consumer_readiness,
                "autoejection_handoff": {},
                "step_trace": [
                    {"step": "AUTOEJECTION_GATE", "status": "ok", "detail": str(autoejection.get("provider") or "")},
                    {"step": "CONSUMER_READINESS", "status": "blocked", "detail": ",".join(str(item) for item in consumer_readiness.get("blockers", []))},
                ],
            }
            await controller.emit_workspace_result(
                workspace="printer",
                tool="printer.autoejection_test",
                result=result,
                stage=Stage.SPECIMEN,
                module_id="specimen",
                agent="specimen_agent",
                workflow="autoejection_test",
            )
            return result
        handoff = _bambu_autoejection_handoff_payload(
            autoejection,
            position=req.position,
            object_size_mm=[float(item) for item in req.object_size_mm],
            mode=req.mode,
            consumer_readiness=consumer_readiness,
        )
        result = {
            "ok": True,
            "tool": "printer.autoejection_test",
            "provider": "bambulab_x2d",
            "selected_printer": manager._selected_printer_payload(selected_profile, selection_reason),
            "status": "provider_handoff_ready",
            "motion_started": False,
            "requested_start_immediately": bool(req.start_immediately),
            "autoejection": autoejection,
            "consumer_readiness": consumer_readiness,
            "handoff": handoff,
            "autoejection_handoff": handoff,
            "message": (
                "Bambu autoejection provider handoff is ready. No Prusa bed-sweep G-code was generated "
                "and no robot motion was started by this endpoint."
            ),
            "step_trace": [
                {"step": "AUTOEJECTION_GATE", "status": "ok", "detail": str(autoejection.get("provider") or "")},
                {"step": "PROVIDER_HANDOFF", "status": "ready", "detail": str(autoejection.get("verified_routine_id") or "")},
            ],
        }
        await controller.emit_workspace_result(
            workspace="printer",
            tool="printer.autoejection_test",
            result=result,
            stage=Stage.SPECIMEN,
            module_id="specimen",
            agent="specimen_agent",
            workflow="autoejection_test",
        )
        return result
    workflow = _printer_workflow()
    profile = load_prusa_print_profile()
    payload = {
        "runtime_mode": req.mode,
        "position": req.position,
        "object_size_mm": req.object_size_mm,
        "start_immediately": req.start_immediately,
        "storage": profile.get("storage", "usb"),
        "ejection": {"enabled": True},
    }
    result = workflow.run_autoejection_test(payload)
    await controller.emit_workspace_result(
        workspace="printer",
        tool="printer.autoejection_test",
        result=result,
        stage=Stage.SPECIMEN,
        module_id="specimen",
        agent="specimen_agent",
        workflow="autoejection_test",
    )
    return result


@app.post("/api/equipment/windows/discover")
async def post_windows_equipment_discover(req: WindowsBridgeDiscoverRequest) -> dict[str, object]:
    """Scan the current network for Windows PyAutoGUI bridge hosts."""
    bridge = _equipment_bridge()
    return await discover_windows_pyautogui_bridges(
        bridge.config,
        subnet=req.subnet,
        port=req.port,
        token=req.token,
        timeout_sec=req.timeout_sec,
        max_hosts=req.max_hosts,
    )


@app.post("/api/equipment/windows/connect")
async def post_windows_equipment_connect(req: WindowsBridgeConnectRequest) -> dict[str, object]:
    """Persist a token-verified Windows PyAutoGUI bridge candidate."""
    bridge = _equipment_bridge()
    return bridge.save_connection(req.model_dump())


@app.post("/api/equipment/windows/select")
async def post_windows_equipment_select(req: WindowsBridgeCandidateRequest) -> dict[str, object]:
    """Quick-select a saved Windows PyAutoGUI bridge candidate."""
    bridge = _equipment_bridge()
    return bridge.select_candidate(req.model_dump())


@app.post("/api/equipment/windows/delete")
async def post_windows_equipment_delete(req: WindowsBridgeCandidateRequest) -> dict[str, object]:
    """Delete a saved Windows PyAutoGUI bridge candidate."""
    bridge = _equipment_bridge()
    return bridge.delete_candidate(req.model_dump())


@app.post("/api/equipment/windows/test")
async def post_windows_equipment_test() -> dict[str, object]:
    """Test the selected Windows PyAutoGUI bridge with live /health and /programs."""
    bridge = _equipment_bridge()
    health = bridge.health({"runtime_mode": "live", "force_live_bridge": True})
    programs = bridge.list_programs({"runtime_mode": "live", "force_live_bridge": True}) if health.get("ok") else {}
    result = {"ok": bool(health.get("ok")), "health": health, "programs": programs}
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.health",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_bridge_test",
    )
    return result


@app.get("/api/equipment/windows/utm-profile")
async def get_windows_equipment_utm_profile() -> dict[str, object]:
    """Return the persisted UTM protocol profile merged into autonomous Equipment runs."""
    bridge = _equipment_bridge()
    return bridge.utm_profile_status()


@app.post("/api/equipment/windows/utm-profile")
async def post_windows_equipment_utm_profile(req: WindowsBridgeUtmProfileRequest) -> dict[str, object]:
    """Persist UTM protocol calibration settings for GUI, CUI, and agent-loop reuse."""
    bridge = _equipment_bridge()
    result = bridge.save_utm_profile(req.model_dump())
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.save_utm_profile",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_utm_profile",
        node_event=True,
    )
    return result


@app.post("/api/equipment/windows/run-program")
async def post_windows_equipment_run_program(req: WindowsBridgeRunProgramRequest) -> dict[str, object]:
    """Run an explicit setup-GUI macro test such as program1."""
    if not req.confirm_execute:
        raise HTTPException(status_code=400, detail="confirm_execute=true is required for setup GUI macro tests")
    bridge = _equipment_bridge()
    specimen_result = controller._state.run_metadata.get("specimen_result") if isinstance(controller._state.run_metadata.get("specimen_result"), dict) else {}
    setup_specimen_id = str(
        specimen_result.get("specimen_id")
        or controller._state.current_experiment_spec.get("specimen_id")
        or "specimen-test"
    )
    payload: dict[str, object] = {
        "runtime_mode": "live",
        "force_live_bridge": True,
        "confirm_setup_gui_execute": True,
        "sequence_id": f"setup-{req.program_id}",
        "run_id": controller._state.run_id,
        "specimen_id": setup_specimen_id,
        "program_id": req.program_id,
        "command": req.command or f"{req.program_id} 실행",
        "require_screen_assertions": req.require_screen_assertions,
        "simulate_utm_protocol": req.simulate_utm_protocol,
    }
    if req.export_glob.strip():
        payload["export_glob"] = req.export_glob.strip()
    if req.artifact_timeout_s is not None:
        payload["artifact_timeout_s"] = req.artifact_timeout_s
    if req.stable_for_sec is not None:
        payload["stable_for_sec"] = req.stable_for_sec
    if req.expected_export_path.strip():
        payload["expected_export_path"] = req.expected_export_path.strip()
    if req.target_window.strip():
        payload["target_window"] = req.target_window.strip()
    if req.target_window_regex.strip():
        payload["target_window_regex"] = req.target_window_regex.strip()
    payload["require_window_focus"] = req.require_window_focus
    payload["manual_save_required_if_no_artifact"] = req.manual_save_required_if_no_artifact
    if req.locators:
        payload["locators"] = req.locators
    if req.sequence:
        payload["sequence"] = req.sequence
    is_utm_program = str(req.program_id or "").startswith("utm_")
    is_utm_recovery_program = str(req.program_id or "") == "utm_stop_or_abort_v1"
    if is_utm_program and not is_utm_recovery_program:
        readiness = _windows_utm_readiness_from_bridge(bridge, runtime_overrides=payload)
        required_gate = "ready_for_setup_test" if req.simulate_utm_protocol else "ready_for_autonomous_profile"
        if not bool(readiness.get(required_gate)):
            blockers = [str(item) for item in readiness.get("blockers", []) if str(item or "").strip()]
            warnings = [str(item) for item in readiness.get("warnings", []) if str(item or "").strip()]
            gate_blocker = "UTM_AUTONOMOUS_PROFILE_NOT_READY" if required_gate == "ready_for_autonomous_profile" else "UTM_SETUP_PROFILE_NOT_READY"
            if gate_blocker not in blockers:
                blockers.append(gate_blocker)
            result = {
                "ok": False,
                "tool": "equipment.pyautogui.run",
                "status": "blocked",
                "bridge": "windows_pyautogui",
                "program_id": req.program_id,
                "sequence_id": payload["sequence_id"],
                "failure_code": "UTM_PRE_EXECUTION_READINESS_BLOCKED",
                "message": "UTM execution was blocked before contacting /execute because readiness gates are incomplete.",
                "non_actuating": True,
                "bridge_not_called": True,
                "required_gate": required_gate,
                "readiness": readiness,
                "blockers": blockers,
                "warnings": warnings,
                "step_trace": [
                    {"step": "READINESS_PRECHECK", "status": "blocked", "detail": ", ".join(blockers) or required_gate},
                ],
            }
            controller._state.run_metadata["last_windows_equipment_run_result"] = result
            controller._state.run_metadata["last_windows_utm_protocol_result"] = result
            await controller.emit_workspace_result(
                workspace="equipment",
                tool="equipment.pyautogui.run",
                result=result,
                stage=Stage.EQUIPMENT,
                module_id="equipment",
                agent="equipment_agent",
                workflow="windows_run_program_precheck_blocked",
                node_event=True,
            )
            return result
        if not req.simulate_utm_protocol:
            preflight = _windows_utm_live_preflight_from_bridge(
                bridge,
                include_locators=True,
                include_screenshot=False,
                include_request_log=True,
                runtime_overrides=payload,
            )
            controller._state.run_metadata["last_windows_live_preflight_result"] = preflight
            if not bool(preflight.get("ready_for_autonomous_profile")):
                blockers = [str(item) for item in preflight.get("blockers", []) if str(item or "").strip()]
                warnings = [str(item) for item in preflight.get("warnings", []) if str(item or "").strip()]
                if "UTM_LIVE_PREFLIGHT_NOT_READY" not in blockers:
                    blockers.append("UTM_LIVE_PREFLIGHT_NOT_READY")
                result = {
                    "ok": False,
                    "tool": "equipment.pyautogui.run",
                    "status": "blocked",
                    "bridge": "windows_pyautogui",
                    "program_id": req.program_id,
                    "sequence_id": payload["sequence_id"],
                    "failure_code": "UTM_LIVE_PREFLIGHT_BLOCKED",
                    "message": "UTM execution was blocked before /execute because live preflight gates are incomplete.",
                    "non_actuating": True,
                    "bridge_not_called": True,
                    "required_gate": "live_preflight.ready_for_autonomous_profile",
                    "readiness": readiness,
                    "preflight": preflight,
                    "blockers": blockers,
                    "warnings": warnings,
                    "step_trace": [
                        {"step": "READINESS_PRECHECK", "status": "ok", "detail": required_gate},
                        {"step": "LIVE_PREFLIGHT", "status": "blocked", "detail": ", ".join(blockers) or "live_preflight"},
                    ],
                }
                controller._state.run_metadata["last_windows_equipment_run_result"] = result
                controller._state.run_metadata["last_windows_utm_protocol_result"] = result
                await controller.emit_workspace_result(
                    workspace="equipment",
                    tool="equipment.pyautogui.run",
                    result=result,
                    stage=Stage.EQUIPMENT,
                    module_id="equipment",
                    agent="equipment_agent",
                    workflow="windows_run_program_live_preflight_blocked",
                    node_event=True,
                )
                return result
    result = bridge.run(payload)
    if is_utm_program:
        request_log_after_execute = _windows_bridge_request_log_from_bridge(bridge, runtime_mode="live", confirm_live=True)
        result["request_audit_log"] = request_log_after_execute
        for key in (
            "request_log",
            "event_count",
            "recent_paths",
            "execute_event_seen",
            "execute_event_count",
            "execute_payload_event_count",
            "execute_result_event_count",
            "execute_run_ids",
            "execute_sequence_ids",
            "execute_specimen_ids",
            "execute_program_ids",
            "last_execute_context",
            "last_execute_at",
        ):
            if key in request_log_after_execute and key not in result:
                result[key] = request_log_after_execute[key]
        if is_utm_recovery_program:
            result["recovery_macro"] = True
            result["pre_execution_readiness"] = {
                "ok": True,
                "status": "bypassed_for_recovery_macro",
                "non_actuating": False,
                "reason": "utm_stop_or_abort_v1 must remain callable even when UTM setup locators are incomplete.",
            }
        else:
            result["pre_execution_readiness"] = readiness
            if not req.simulate_utm_protocol:
                result["pre_execution_preflight"] = controller._state.run_metadata.get("last_windows_live_preflight_result", {})
    controller._state.run_metadata["last_windows_equipment_run_result"] = result
    if str(result.get("program_id") or req.program_id or "").startswith("utm_"):
        controller._state.run_metadata["last_windows_utm_protocol_result"] = result
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.run",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_utm_recovery_macro" if is_utm_recovery_program else "windows_run_program",
        node_event=True,
    )
    return result


@app.get("/api/equipment/windows/locators")
async def get_windows_equipment_locators() -> dict[str, object]:
    """List Windows-side locator images captured for equipment protocols."""
    bridge = _equipment_bridge()
    return bridge.list_locators({"runtime_mode": "live", "force_live_bridge": True})


@app.post("/api/equipment/windows/screenshot")
async def post_windows_equipment_screenshot(req: WindowsBridgeScreenshotRequest) -> dict[str, object]:
    """Capture a full Windows bridge screenshot for UTM UI calibration."""
    if not req.confirm_capture:
        raise HTTPException(status_code=400, detail="confirm_capture=true is required for Windows screenshot capture")
    bridge = _equipment_bridge()
    result = bridge.screenshot(
        {
            "runtime_mode": "live",
            "force_live_bridge": True,
            "run_id": req.run_id or "locator-calibration",
            "checkpoint": req.checkpoint or "manual",
        }
    )
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.screenshot",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_locator_calibration",
        node_event=True,
    )
    return result


@app.post("/api/equipment/windows/capture-locator")
async def post_windows_equipment_capture_locator(req: WindowsBridgeLocatorCaptureRequest) -> dict[str, object]:
    """Capture a selected Windows screen region as an image locator for UTM protocol assertions."""
    if not req.confirm_capture:
        raise HTTPException(status_code=400, detail="confirm_capture=true is required for locator capture")
    bridge = _equipment_bridge()
    result = bridge.capture_locator(
        {
            "runtime_mode": "live",
            "force_live_bridge": True,
            "confirm_setup_gui_execute": True,
            "program_id": req.program_id,
            "name": req.name,
            "target": req.name,
            "region": req.region,
            "confidence": req.confidence,
        }
    )
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.capture_locator",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_locator_calibration",
        node_event=True,
    )
    return result


@app.get("/api/lerobot/config")
async def get_lerobot_config() -> dict[str, object]:
    """Return LeRobot profile/session configuration for all GUI windows."""
    return _lerobot_bridge().config_status()


@app.post("/api/lerobot/config")
async def post_lerobot_config(req: LeRobotConfigRequest) -> dict[str, object]:
    """Select the active LeRobot robot profile."""
    return _lerobot_bridge().configure(req.model_dump())


@app.get("/api/lerobot/sessions")
async def get_lerobot_sessions() -> dict[str, object]:
    """Return recent LeRobot sessions across the backend-owned bridge."""
    sessions: list[dict[str, object]] = []
    seen: set[str] = set()
    for bridge in (_lerobot_bridge(), _registered_lerobot_bridge()):
        if bridge is None:
            continue
        for session in bridge.sessions_recent():
            session_id = str(session.get("session_id") or "")
            if session_id and session_id in seen:
                continue
            if session_id:
                seen.add(session_id)
            sessions.append(session)
    return {"ok": True, "sessions": sessions}


@app.get("/api/lerobot/policies")
async def get_lerobot_policies() -> dict[str, object]:
    """Return configured and locally discovered LeRobot policy choices."""
    return _lerobot_bridge().policies_list({"mode": "test"})


@app.post("/api/lerobot/files/browse")
async def post_lerobot_files_browse(req: LeRobotBrowseRequest) -> dict[str, object]:
    """Browse allowed local LeRobot dataset/policy/output roots for GUI path selection."""
    return _lerobot_bridge().browse_paths(req.model_dump())


@app.post("/api/lerobot/files/pick")
async def post_lerobot_files_pick(req: LeRobotBrowseRequest) -> dict[str, object]:
    """Open a native local file/folder picker for the LeRobot GUI."""
    return _lerobot_bridge().pick_path(req.model_dump())


@app.post("/api/lerobot/visualize/dataset")
async def post_lerobot_visualize_dataset(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return local LeRobot dataset metadata and media candidates for lightweight preview."""
    result = _lerobot_bridge().visualize_dataset(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/visualize/start")
async def post_lerobot_visualize_start(req: LeRobotAPIRequest) -> dict[str, object]:
    """Start LeRobot's dataset visualizer."""
    return await _call_lerobot_backend_tool("lerobot.visualize.start", req.model_dump())


@app.post("/api/lerobot/visualize/stop")
async def post_lerobot_visualize_stop(req: LeRobotAPIRequest) -> dict[str, object]:
    """Stop a LeRobot dataset visualizer session."""
    return await _call_lerobot_backend_tool("lerobot.visualize.stop", req.model_dump())


@app.post("/api/lerobot/visualize/status")
async def post_lerobot_visualize_status(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return LeRobot dataset visualizer status."""
    return await _call_lerobot_backend_tool("lerobot.visualize.status", req.model_dump(), publish=False)


@app.get("/api/lerobot/visualization/file")
async def get_lerobot_visualization_file(path: str) -> FileResponse:
    """Serve an allowed local LeRobot dataset media file."""
    try:
        file_path = _lerobot_bridge().visualization_file_path(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return FileResponse(file_path)


@app.get("/api/lerobot/ports")
async def get_lerobot_ports(
    profile_id: str = "",
    mode: Literal["live", "test", "replay", "fault-injection"] = "test",
) -> dict[str, object]:
    """Discover robot/teleop ports or return deterministic test ports."""
    result = _lerobot_bridge().find_ports({"profile_id": profile_id, "mode": mode})
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/ports/baseline")
async def post_lerobot_ports_baseline(req: LeRobotDevicePortAPIRequest) -> dict[str, object]:
    """Save current serial/camera state before reconnecting a target LeRobot device."""
    result = _lerobot_bridge().ports_baseline(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/ports/detect")
async def post_lerobot_ports_detect(req: LeRobotDevicePortAPIRequest) -> dict[str, object]:
    """Detect and save the target LeRobot device that appeared after the baseline."""
    result = _lerobot_bridge().ports_detect(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/ports/save")
async def post_lerobot_ports_save(req: LeRobotDevicePortAPIRequest) -> dict[str, object]:
    """Persist an explicitly selected LeRobot follower/leader/camera port."""
    result = _lerobot_bridge().ports_save(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/ports/delete")
async def post_lerobot_ports_delete(req: LeRobotDevicePortAPIRequest) -> dict[str, object]:
    """Remove a saved LeRobot follower/leader/camera port entry."""
    result = _lerobot_bridge().ports_delete(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/camera/test")
async def post_lerobot_camera_test(req: LeRobotDevicePortAPIRequest) -> dict[str, object]:
    """Capture one LeRobot camera test frame or a deterministic test-mode preview."""
    result = _lerobot_bridge().camera_test(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/profiles/validate")
async def post_lerobot_profile_validate(req: LeRobotAPIRequest) -> dict[str, object]:
    """Validate a LeRobot robot profile."""
    result = _lerobot_bridge().profiles_validate(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/teleoperate/start")
async def post_lerobot_teleoperate_start(req: LeRobotAPIRequest) -> dict[str, object]:
    """Start LeRobot teleoperation."""
    return await _call_lerobot_backend_tool("lerobot.teleoperate.start", req.model_dump())


@app.post("/api/lerobot/teleoperate/stop")
async def post_lerobot_teleoperate_stop(req: LeRobotAPIRequest) -> dict[str, object]:
    """Stop LeRobot teleoperation."""
    return await _call_lerobot_backend_tool("lerobot.teleoperate.stop", req.model_dump())


@app.post("/api/lerobot/teleoperate/status")
async def post_lerobot_teleoperate_status(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return LeRobot teleoperation status."""
    return await _call_lerobot_backend_tool("lerobot.teleoperate.status", req.model_dump(), publish=False)


@app.post("/api/lerobot/record/start")
async def post_lerobot_record_start(req: LeRobotAPIRequest) -> dict[str, object]:
    """Start LeRobot dataset recording."""
    return await _call_lerobot_backend_tool("lerobot.record.start", req.model_dump())


@app.post("/api/lerobot/record/control")
async def post_lerobot_record_control(req: LeRobotRecordControlAPIRequest) -> dict[str, object]:
    """Apply a LeRobot recording control action."""
    return await _call_lerobot_backend_tool("lerobot.record.control", req.model_dump())


@app.post("/api/lerobot/record/status")
async def post_lerobot_record_status(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return LeRobot recording status."""
    return await _call_lerobot_backend_tool("lerobot.record.status", req.model_dump(), publish=False)


@app.post("/api/lerobot/train/start")
async def post_lerobot_train_start(req: LeRobotAPIRequest) -> dict[str, object]:
    """Start LeRobot policy training."""
    return await _call_lerobot_backend_tool("lerobot.train.start", req.model_dump(exclude_unset=True))


@app.post("/api/lerobot/train/cancel")
async def post_lerobot_train_cancel(req: LeRobotAPIRequest) -> dict[str, object]:
    """Cancel LeRobot policy training."""
    return await _call_lerobot_backend_tool("lerobot.train.cancel", req.model_dump())


@app.post("/api/lerobot/train/status")
async def post_lerobot_train_status(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return LeRobot training status."""
    return await _call_lerobot_backend_tool("lerobot.train.status", req.model_dump(), publish=False)


@app.post("/api/lerobot/rollout/start")
async def post_lerobot_rollout_start(req: LeRobotAPIRequest) -> dict[str, object]:
    """Start LeRobot policy rollout/inference."""
    return await _call_lerobot_backend_tool("lerobot.rollout.start", req.model_dump())


def _manipulation_profile_from_request(req: ManipulationAgentBridgeRequest) -> dict[str, object]:
    """Convert GUI/API request to persisted Manipulation Agent profile keys."""
    policy_path = req.policy_path or req.policy_checkpoint_path
    return {
        "manipulation_strategy": req.manipulation_strategy,
        "policy_type": req.policy_type,
        "policy_path": policy_path,
        "policy_checkpoint_path": req.policy_checkpoint_path,
        "policy_repo_id": req.policy_repo_id,
        "profile_id": req.profile_id,
        "dataset_repo_id": req.dataset_repo_id,
        "dataset_root": req.dataset_root,
        "task_id": req.task_id or req.skill_id,
        "skill_id": req.skill_id or req.task_id,
        "task_instruction": req.task_instruction,
        "source_location": req.source_location,
        "target_location": req.target_location,
        "policy_backend": req.policy_backend,
        "device": req.device,
        "fps": req.fps,
        "camera_fps": req.camera_fps,
        "camera_enabled": req.camera_enabled,
        "display_data": req.display_data,
        "continuous_rollout": req.continuous_rollout,
        "rollout_action_clamp": req.rollout_action_clamp,
        "rollout_max_relative_target": req.rollout_max_relative_target,
        "rollout_temporal_ensemble": req.rollout_temporal_ensemble,
        "rollout_temporal_ensemble_coeff": req.rollout_temporal_ensemble_coeff,
        "rollout_inference_type": req.rollout_inference_type,
        "rollout_rtc_execution_horizon": req.rollout_rtc_execution_horizon,
        "rollout_rtc_max_guidance_weight": req.rollout_rtc_max_guidance_weight,
        "rollout_action_queue_size_to_get_new_actions": req.rollout_action_queue_size_to_get_new_actions,
        "max_duration_s": req.max_duration_s,
    }


def _manipulation_spec_from_request(req: ManipulationAgentBridgeRequest) -> dict[str, object]:
    """Convert GUI/API request to ManipulationAgent current_experiment_spec keys."""
    profile = _manipulation_profile_from_request(req)
    policy_path = str(profile.get("policy_path") or "")
    return {
        "manipulation_strategy": profile.get("manipulation_strategy"),
        "lerobot_profile_id": profile.get("profile_id"),
        "robot_profile_id": profile.get("profile_id"),
        "lerobot_policy_type": profile.get("policy_type"),
        "policy_type": profile.get("policy_type"),
        "lerobot_policy_path": policy_path,
        "policy_path": policy_path,
        "lerobot_policy_checkpoint_path": profile.get("policy_checkpoint_path"),
        "policy_checkpoint_path": profile.get("policy_checkpoint_path"),
        "lerobot_policy_repo_id": profile.get("policy_repo_id"),
        "policy_repo_id": profile.get("policy_repo_id"),
        "lerobot_rollout_dataset_repo_id": profile.get("dataset_repo_id"),
        "dataset_repo_id": profile.get("dataset_repo_id"),
        "lerobot_dataset_root": profile.get("dataset_root"),
        "dataset_root": profile.get("dataset_root"),
        "manipulation_task_id": profile.get("task_id"),
        "task_id": profile.get("task_id"),
        "skill_id": profile.get("skill_id"),
        "task_instruction": profile.get("task_instruction"),
        "source_location": profile.get("source_location"),
        "target_location": profile.get("target_location"),
        "policy_backend": profile.get("policy_backend"),
        "lerobot_device": profile.get("device"),
        "device": profile.get("device"),
        "fps": profile.get("fps"),
        "camera_fps": profile.get("camera_fps"),
        "camera_enabled": profile.get("camera_enabled"),
        "display_data": profile.get("display_data"),
        "confirm_live_execute": req.confirm_live_execute,
        "rollout_episode_s": req.episode_s,
        "rollout_num_episodes": req.num_episodes,
        "continuous_rollout": profile.get("continuous_rollout"),
        "rollout_action_clamp": profile.get("rollout_action_clamp"),
        "rollout_max_relative_target": profile.get("rollout_max_relative_target"),
        "rollout_temporal_ensemble": profile.get("rollout_temporal_ensemble"),
        "rollout_temporal_ensemble_coeff": profile.get("rollout_temporal_ensemble_coeff"),
        "rollout_inference_type": profile.get("rollout_inference_type"),
        "rollout_rtc_execution_horizon": profile.get("rollout_rtc_execution_horizon"),
        "rollout_rtc_max_guidance_weight": profile.get("rollout_rtc_max_guidance_weight"),
        "rollout_action_queue_size_to_get_new_actions": profile.get("rollout_action_queue_size_to_get_new_actions"),
        "max_duration_s": profile.get("max_duration_s"),
    }


async def _run_manipulation_agent_bridge(req: ManipulationAgentBridgeRequest, *, force_test: bool = False) -> dict[str, object]:
    """Run the actual Manipulation Agent bridge with optional forced test mode."""
    mode = Mode.TEST if force_test else Mode(req.runtime_mode or req.mode)
    specimen_result = dict(req.specimen_result or {})
    specimen_result.setdefault("ok", True)
    specimen_result.setdefault("handoff_status", "ready")
    specimen_result.setdefault("specimen_id", "manual-specimen")
    specimen_result.setdefault("candidate_id", "manual-candidate")
    spec = _manipulation_spec_from_request(req)
    if force_test:
        spec["confirm_live_execute"] = False
        spec["lerobot_profile_id"] = spec.get("lerobot_profile_id") or "fake_omx_ai"
        spec["robot_profile_id"] = spec.get("robot_profile_id") or "fake_omx_ai"
    snapshot = controller.snapshot()
    state = OrchestratorState(
        run_id=str(snapshot.get("state", {}).get("run_id") or "gui-manipulation"),
        experiment_id=str(snapshot.get("state", {}).get("experiment_id") or "gui-manipulation-experiment"),
        active_session_id=str(snapshot.get("state", {}).get("active_session_id") or "gui-manipulation"),
        mode=mode,
        stage=Stage.MANIPULATION,
        active_goal=req.task_instruction,
        current_experiment_spec={key: value for key, value in spec.items() if value not in (None, "")},
        latest_observations=dict(req.observation or {}),
        run_metadata={"specimen_result": specimen_result, "source": "lerobot_gui_manipulation_bridge"},
        device_health={"printer": "ready", "camera": "ready", "robot": "ready", "utm": "ready"},
    )
    result = await ManipulationAgent().run(state, controller._deps.agent_context)
    manipulation = result.data.get("manipulation") if isinstance(result.data.get("manipulation"), dict) else {}
    if manipulation:
        await controller.emit_lerobot_result(manipulation)
    response = {
        "ok": bool(result.success),
        "tool": "manipulation_agent.test" if force_test else "manipulation_agent.run",
        "mode": mode.value,
        "summary": result.summary,
        "data": result.data,
        "manipulation": manipulation,
        "sarm": result.data.get("sarm", {}),
        "manipulation_report": result.data.get("manipulation_report", {}),
        "manipulation_agent_report": result.data.get("manipulation_agent_report", {}),
        "robot_task_result": result.data.get("robot_task_result", {}),
        "next_hint": result.next_hint,
        "state": state.model_dump(mode="json"),
    }
    await controller.emit_workspace_result(
        workspace="lerobot",
        tool=str(response["tool"]),
        result=response,
        stage=Stage.MANIPULATION,
        module_id="manipulation",
        agent="manipulation_agent",
        workflow="manipulation_agent_bridge",
        node_event=True,
    )
    return response


@app.get("/api/lerobot/manipulation-agent/config")
async def get_lerobot_manipulation_agent_config() -> dict[str, object]:
    """Return saved Manipulation Agent bridge defaults."""
    return {
        "ok": True,
        "profile": load_manipulation_agent_profile(),
        "profile_path": str(MANIPULATION_AGENT_PROFILE_PATH),
    }


@app.post("/api/lerobot/manipulation-agent/config")
async def post_lerobot_manipulation_agent_config(req: ManipulationAgentBridgeRequest) -> dict[str, object]:
    """Persist Manipulation Agent bridge defaults for live/test loop usage."""
    profile = save_manipulation_agent_profile(_manipulation_profile_from_request(req))
    return {
        "ok": True,
        "tool": "manipulation_agent.config.save",
        "profile": profile,
        "profile_path": str(MANIPULATION_AGENT_PROFILE_PATH),
        "message": "Manipulation Agent bridge defaults saved.",
    }


@app.post("/api/lerobot/manipulation-agent/test")
async def post_lerobot_manipulation_agent_test(req: ManipulationAgentBridgeRequest) -> dict[str, object]:
    """Run Manipulation Agent bridge in forced test mode before live-loop use."""
    result = await _run_manipulation_agent_bridge(req, force_test=True)
    result["tool"] = "manipulation_agent.test"
    result["test_mode_forced"] = True
    return result


@app.post("/api/lerobot/manipulation-agent/run")
async def post_lerobot_manipulation_agent_run(req: ManipulationAgentBridgeRequest) -> dict[str, object]:
    """Run the actual Manipulation Agent bridge from the LeRobot GUI."""
    return await _run_manipulation_agent_bridge(req)


@app.post("/api/lerobot/rollout/stop")
async def post_lerobot_rollout_stop(req: LeRobotAPIRequest) -> dict[str, object]:
    """Stop LeRobot policy rollout/inference."""
    return await _call_lerobot_backend_tool("lerobot.rollout.stop", req.model_dump())


@app.post("/api/lerobot/rollout/status")
async def post_lerobot_rollout_status(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return LeRobot rollout status."""
    return await _call_lerobot_backend_tool("lerobot.rollout.status", req.model_dump(), publish=False)


@app.post("/api/lerobot/dataset/inspect")
async def post_lerobot_dataset_inspect(req: LeRobotAPIRequest) -> dict[str, object]:
    """Inspect a LeRobot dataset path/repo."""
    result = _lerobot_bridge().dataset_inspect(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/policy/download")
async def post_lerobot_policy_download(req: LeRobotAPIRequest) -> dict[str, object]:
    """Dry-run or gated LeRobot policy download."""
    result = _lerobot_bridge().policy_download(req.model_dump())
    return await _publish_lerobot_result(result)


@app.get("/api/knowledge/evolution-packs")
async def get_knowledge_evolution_packs(target_type: str | None = None, target_id: str | None = None, limit: int = 20) -> dict[str, object]:
    """List Knowledge-built evidence packs for Self-Evolution prefill."""
    packs = _knowledge_store().list_evolution_packs(target_type=target_type, target_id=target_id, limit=limit)
    return {"ok": True, "target_type": target_type or "", "target_id": target_id or "", "packs": [pack.model_dump(mode="json") for pack in packs]}


@app.get("/api/knowledge/agent-performance")
async def get_knowledge_agent_performance(agent_id: str | None = None, limit: int = 50) -> dict[str, object]:
    """List Knowledge Agent performance ledger entries."""
    records = _knowledge_store().list_agent_performance(agent_id=agent_id, limit=limit)
    return {"ok": True, "agent_id": agent_id or "", "records": [record.model_dump(mode="json") for record in records]}


@app.get("/api/knowledge/failure-patterns")
async def get_knowledge_failure_patterns(agent_id: str | None = None, stage: str | None = None, limit: int = 50) -> dict[str, object]:
    """List repeated/current failure patterns known to Knowledge Agent."""
    records = _knowledge_store().list_failure_patterns(limit=limit * 4)
    if agent_id:
        records = [record for record in records if agent_id in record.affected_agents]
    if stage:
        records = [record for record in records if stage in record.affected_agents]
    return {"ok": True, "records": [record.model_dump(mode="json") for record in records[-limit:]]}


@app.get("/api/knowledge/success-patterns")
async def get_knowledge_success_patterns(agent_id: str | None = None, limit: int = 50) -> dict[str, object]:
    """List reusable success/skill cards known to Knowledge Agent."""
    records = _knowledge_store().list_success_patterns(limit=limit * 4)
    if agent_id:
        records = [record for record in records if record.agent_id == agent_id]
    return {"ok": True, "agent_id": agent_id or "", "records": [record.model_dump(mode="json") for record in records[-limit:]]}


@app.get("/api/knowledge/evolution-outcomes")
async def get_knowledge_evolution_outcomes(target_id: str | None = None, limit: int = 50) -> dict[str, object]:
    """List before/after attribution records for activated variants."""
    records = _knowledge_store().list_evolution_outcomes(target_id=target_id, limit=limit)
    return {"ok": True, "target_id": target_id or "", "records": [record.model_dump(mode="json") for record in records]}


@app.post("/api/knowledge/evolution-outcomes")
async def post_knowledge_evolution_outcome(payload: dict[str, object]) -> dict[str, object]:
    """Append an operator/replay-reviewed evolution outcome record."""
    try:
        record = EvolutionOutcomeRecord.model_validate(payload)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _knowledge_store().append_evolution_outcome(record)
    await controller.emit_runtime_event(
        event_type="knowledge.evolution_outcome.recorded",
        message=f"Evolution outcome recorded: {record.target_type}:{record.target_id}",
        payload={"record": record.model_dump(mode="json")},
        level="INFO",
    )
    return {"ok": True, "record": record.model_dump(mode="json")}


@app.get("/api/knowledge/graph/health")
async def get_knowledge_graph_health() -> dict[str, object]:
    """Return optional Knowledge graph backend health.

    The graph backend is a mirror/index. JSONL memory remains authoritative.
    """
    backend = _knowledge_graph_backend()
    try:
        return backend.health()
    finally:
        backend.close()


@app.post("/api/knowledge/graph/import")
async def post_knowledge_graph_import(payload: dict[str, object] | None = None) -> dict[str, object]:
    """Import recent file-backed Knowledge memory into the optional graph backend."""
    payload = payload or {}
    try:
        limit = max(1, min(int(payload.get("limit") or 500), 5000))
    except Exception:
        limit = 500
    backend = _knowledge_graph_backend()
    try:
        result = import_store_to_graph(_knowledge_store(), backend, limit=limit)
    finally:
        backend.close()
    await controller.emit_runtime_event(
        event_type="knowledge.graph_import.completed",
        message=f"Knowledge graph import completed: backend={result.get('backend')} records={result.get('records', 0)}",
        payload={"result": result},
        level="INFO" if result.get("ok", True) else "WARNING",
    )
    return result


@app.get("/api/knowledge/graph/query")
async def get_knowledge_graph_query(
    kind: str = "summary",
    node_id: str = "",
    target_type: str = "",
    target_id: str = "",
    q: str = "",
    limit: int = 50,
    include_properties: bool = False,
) -> dict[str, object]:
    """Query optional Knowledge graph backend with safe high-level query modes."""
    backend = _knowledge_graph_backend()
    try:
        result = backend.query({"kind": kind, "node_id": node_id, "target_type": target_type, "target_id": target_id, "q": q, "limit": limit, "include_properties": include_properties})
    finally:
        backend.close()
    return result


@app.post("/api/knowledge/graphify/scan")
async def post_knowledge_graphify_scan(payload: dict[str, object] | None = None) -> dict[str, object]:
    """Create Graphify-compatible project graph artifacts for the current ATR checkout."""
    payload = payload or {}
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else None
    source_paths = [str(item) for item in sources] if sources else None
    max_file_bytes = max(1024, min(int(payload.get("max_file_bytes") or 256_000), 5_000_000))
    out_dir_raw = str(payload.get("out_dir") or "memory/knowledge/graphify")
    out_dir = resolve_path(out_dir_raw) if not Path(out_dir_raw).is_absolute() else Path(out_dir_raw)
    result = scan_project_graph(
        resolve_path("."),
        out_dir=out_dir,
        source_paths=source_paths,
        max_file_bytes=max_file_bytes,
        run_external_graphify=bool(payload.get("external_graphify", False)),
    )
    await controller.emit_runtime_event(
        event_type="knowledge.graphify_scan.completed",
        message=f"Knowledge Graphify scan completed: nodes={result.get('node_count', 0)} edges={result.get('edge_count', 0)}",
        payload={"result": result},
        level="INFO" if result.get("ok", True) else "WARNING",
    )
    return result


@app.post("/api/knowledge/graphify/import")
async def post_knowledge_graphify_import(payload: dict[str, object] | None = None) -> dict[str, object]:
    """Import Graphify-compatible project graph artifacts into the optional graph backend."""
    payload = payload or {}
    graph_raw = str(payload.get("graphify_json") or "memory/knowledge/graphify/project_graph.json")
    graph_json = resolve_path(graph_raw) if not Path(graph_raw).is_absolute() else Path(graph_raw)
    if not graph_json.exists():
        return {"ok": False, "error": f"graphify JSON not found: {graph_json}", "hint": "run /api/knowledge/graphify/scan first"}
    runtime_limit = max(1, min(int(payload.get("runtime_limit") or 500), 5000))
    include_runtime = bool(payload.get("include_runtime_memory", True))
    backend = _knowledge_graph_backend()
    try:
        result = import_project_graph(backend, graph_json, include_runtime_memory=include_runtime, store=_knowledge_store() if include_runtime else None, runtime_limit=runtime_limit)
    finally:
        backend.close()
    await controller.emit_runtime_event(
        event_type="knowledge.graphify_import.completed",
        message=f"Knowledge Graphify import completed: backend={result.get('backend')} project_nodes={result.get('project_nodes', 0)}",
        payload={"result": result},
        level="INFO" if result.get("ok", True) else "WARNING",
    )
    return result


@app.get("/api/knowledge/run-context")
async def get_knowledge_run_context(agent_id: str = "", run_id: str | None = None) -> dict[str, object]:
    """Return the latest per-run Knowledge report context when available."""
    selected_run = run_id or _current_run_id()
    try:
        report = _knowledge_store().read_run_artifact(selected_run, "knowledge_report")
    except Exception:
        report = {}
    return {"ok": True, "agent_id": agent_id, "run_id": selected_run, "knowledge_report": report}


@app.get("/api/knowledge/bo-context")
async def get_knowledge_bo_context(objective_id: str | None = None, limit: int = 20) -> dict[str, object]:
    """Return Knowledge memory useful for BO/Design context."""
    store = _knowledge_store()
    failures = [record.model_dump(mode="json") for record in store.list_failure_patterns(limit=limit)]
    successes = [record.model_dump(mode="json") for record in store.list_success_patterns(limit=limit)]
    return {"ok": True, "objective_id": objective_id or "", "failure_patterns": failures, "success_patterns": successes}


@app.get("/api/knowledge/safety-context")
async def get_knowledge_safety_context(stage: str | None = None, limit: int = 20) -> dict[str, object]:
    """Return Knowledge memory useful for Guardian/safety gates."""
    records = _knowledge_store().list_failure_patterns(limit=limit * 3)
    if stage:
        records = [record for record in records if stage in record.affected_agents]
    return {"ok": True, "stage": stage or "", "risk_patterns": [record.model_dump(mode="json") for record in records[-limit:]]}


@app.get("/api/evolution/targets")
async def get_evolution_targets() -> dict[str, object]:
    """List self-evolution targets mapped to current graph/module configs."""
    return {"ok": True, "targets": _self_evolution_service().list_targets()}


@app.get("/api/evolution/traces")
async def get_evolution_traces(limit: int = 12) -> dict[str, object]:
    """List recent run traces available for self-evolution."""
    return {"ok": True, "traces": _self_evolution_service().latest_traces(limit=limit)}


@app.get("/api/evolution/tasks")
async def get_evolution_tasks() -> dict[str, object]:
    """List self-evolution tasks."""
    tasks = [task.model_dump(mode="json") for task in _self_evolution_service().list_tasks()]
    return {"ok": True, "tasks": tasks}


@app.post("/api/evolution/tasks")
async def create_evolution_task(req: EvolutionTaskCreate) -> dict[str, object]:
    """Create a self-evolution task without executing devices."""
    task = _self_evolution_service().create_task(req)
    await controller.emit_runtime_event(
        event_type="evolution.task.created",
        message=f"Self-evolution task created: {task.target_type}:{task.target_id}",
        payload={"task": task.model_dump(mode="json")},
        level="INFO",
    )
    return {"ok": True, "task": task.model_dump(mode="json")}


@app.get("/api/evolution/tasks/{task_id}")
async def get_evolution_task(task_id: str) -> dict[str, object]:
    """Return one self-evolution task."""
    try:
        task = _self_evolution_service().read_task(task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "task": task.model_dump(mode="json")}


@app.post("/api/evolution/tasks/{task_id}/run")
async def run_evolution_task(task_id: str) -> dict[str, object]:
    """Generate and gate a candidate variant from selected closed-loop traces."""
    result = _self_evolution_service().run_task(task_id, handler_registry=_runtime_graph_handler_registry())
    level = "INFO" if result.get("ok") else "ERROR"
    await controller.emit_runtime_event(
        event_type="evolution.task.completed" if result.get("ok") else "evolution.task.failed",
        message=f"Self-evolution task {task_id} {'completed' if result.get('ok') else 'failed'}",
        payload=result,
        level=level,
    )
    return result


@app.get("/api/evolution/tasks/{task_id}/variants")
async def get_evolution_task_variants(task_id: str) -> dict[str, object]:
    """List variants generated for one task."""
    variants = [variant.model_dump(mode="json") for variant in _self_evolution_service().list_variants(task_id)]
    return {"ok": True, "task_id": task_id, "variants": variants}


@app.get("/api/evolution/variants")
async def get_evolution_variants(task_id: str | None = None, target_type: str | None = None, target_id: str | None = None) -> dict[str, object]:
    """List self-evolution variants for history/leaderboard views."""
    variants = _self_evolution_service().list_variants(task_id)
    if target_type:
        variants = [variant for variant in variants if variant.target_type == target_type]
    if target_id:
        variants = [variant for variant in variants if variant.target_id == target_id]
    payload = [variant.model_dump(mode="json") for variant in variants]
    return {"ok": True, "task_id": task_id or "", "target_type": target_type or "", "target_id": target_id or "", "variants": payload}


@app.get("/api/evolution/variants/{variant_id}")
async def get_evolution_variant(variant_id: str) -> dict[str, object]:
    """Return one self-evolution variant."""
    try:
        variant = _self_evolution_service().read_variant(variant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "variant": variant.model_dump(mode="json")}


@app.post("/api/evolution/variants/{variant_id}/validate")
async def validate_evolution_variant(variant_id: str) -> dict[str, object]:
    """Re-run schema/compiler/dry-run gates for one variant."""
    try:
        variant = _self_evolution_service().evaluate_variant(variant_id, handler_registry=_runtime_graph_handler_registry())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await controller.emit_runtime_event(
        event_type="evolution.variant.validated",
        message=f"Self-evolution variant validated: {variant_id}",
        payload={"variant": variant.model_dump(mode="json")},
        level="INFO" if all(gate.passed for gate in variant.gate_results) else "WARNING",
    )
    return {"ok": True, "variant": variant.model_dump(mode="json")}


@app.post("/api/evolution/variants/{variant_id}/approve")
async def approve_evolution_variant(variant_id: str, req: EvolutionActivationRequest | None = None) -> dict[str, object]:
    """Approve a gate-passed variant for optional next-run activation."""
    payload = req or EvolutionActivationRequest()
    try:
        variant = _self_evolution_service().approve_variant(variant_id, operator=payload.operator, note=payload.note)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    gate = await _emit_self_evolution_guardian_gate(
        action="approve_variant",
        variant_id=variant_id,
        payload={
            "variant": variant.model_dump(mode="json"),
            "human_approved": bool(payload.operator),
            "requires_human_approval": not bool(payload.operator),
            "approved": True,
            "approval_resolved": True,
            "activate_runtime": False,
        },
    )
    await controller.emit_runtime_event(
        event_type="evolution.variant.approved",
        message=f"Self-evolution variant approved: {variant_id}",
        payload={"variant": variant.model_dump(mode="json"), "guardian_gate": gate},
        level="INFO",
    )
    return {"ok": True, "variant": variant.model_dump(mode="json"), "guardian_gate": gate}


@app.post("/api/evolution/variants/{variant_id}/activate")
async def activate_evolution_variant(variant_id: str, req: EvolutionActivationRequest | None = None) -> dict[str, object]:
    """Activate an approved variant for the next closed-loop run."""
    payload = req or EvolutionActivationRequest()
    if controller.snapshot().get("is_running"):
        gate = await _emit_self_evolution_guardian_gate(
            action="activate_variant",
            variant_id=variant_id,
            payload={
                "status": "blocked",
                "failure_code": "SELF_EVOLUTION_GATE_FAILED",
                "message": "Cannot activate self-evolution variant while a run is active.",
                "human_approved": bool(payload.operator),
                "requires_human_approval": not bool(payload.operator),
                "activate_runtime": payload.activate_runtime,
            },
        )
        raise HTTPException(status_code=409, detail={"message": "Cannot activate self-evolution variant while a run is active.", "guardian_gate": gate})
    try:
        candidate_variant = _self_evolution_service().read_variant(variant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    gate = await _emit_self_evolution_guardian_gate(
        action="activate_variant",
        variant_id=variant_id,
        payload={
            "variant": candidate_variant.model_dump(mode="json"),
            "human_approved": bool(payload.operator),
            "requires_human_approval": not bool(payload.operator),
            "approved": candidate_variant.status in {"approved", "active_next_run", "active"},
            "approval_resolved": bool(payload.operator),
            "activate_runtime": payload.activate_runtime,
            "failure_code": "" if candidate_variant.status in {"approved", "active_next_run", "active"} else "SELF_EVOLUTION_GATE_FAILED",
            "message": "variant approved for activation" if candidate_variant.status in {"approved", "active_next_run", "active"} else "variant must be approved before activation",
        },
    )
    if gate_blocks_execution(gate) or str(gate.get("decision") or "") == "require_human_approval":
        raise HTTPException(status_code=409, detail={"message": "Guardian blocked self-evolution activation.", "guardian_gate": gate})
    try:
        variant = _self_evolution_service().activate_variant(
            variant_id,
            operator=payload.operator,
            note=payload.note,
            activate_runtime=payload.activate_runtime,
            handler_registry=_runtime_graph_handler_registry(),
        )
    except ValueError as exc:
        failure_gate = await _emit_self_evolution_guardian_gate(
            action="activate_variant",
            variant_id=variant_id,
            payload={
                "status": "blocked",
                "failure_code": "SELF_EVOLUTION_GATE_FAILED",
                "message": str(exc),
                "human_approved": bool(payload.operator),
                "requires_human_approval": not bool(payload.operator),
                "activate_runtime": payload.activate_runtime,
            },
        )
        raise HTTPException(status_code=409, detail={"message": str(exc), "guardian_gate": failure_gate}) from exc
    await controller.emit_runtime_event(
        event_type="evolution.variant.activated",
        message=f"Self-evolution variant active for next run: {variant_id}",
        payload={"variant": variant.model_dump(mode="json"), "guardian_gate": gate},
        level="WARNING" if payload.activate_runtime else "INFO",
    )
    return {"ok": True, "variant": variant.model_dump(mode="json"), "guardian_gate": gate}


@app.post("/api/evolution/variants/{variant_id}/rollback")
async def rollback_evolution_variant(variant_id: str, req: EvolutionRollbackRequest | None = None) -> dict[str, object]:
    """Mark a self-evolution variant as rolled back in the evolution registry."""
    payload = req or EvolutionRollbackRequest()
    try:
        candidate_variant = _self_evolution_service().read_variant(variant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    gate = await _emit_self_evolution_guardian_gate(
        action="rollback_variant",
        variant_id=variant_id,
        payload={
            "variant": candidate_variant.model_dump(mode="json"),
            "human_approved": bool(payload.operator),
            "requires_human_approval": not bool(payload.operator),
            "approval_resolved": bool(payload.operator),
            "approved": True,
        },
    )
    if gate_blocks_execution(gate) or str(gate.get("decision") or "") == "require_human_approval":
        raise HTTPException(status_code=409, detail={"message": "Guardian blocked self-evolution rollback.", "guardian_gate": gate})
    variant = _self_evolution_service().rollback_variant(variant_id, operator=payload.operator, note=payload.note)
    await controller.emit_runtime_event(
        event_type="evolution.variant.rolled_back",
        message=f"Self-evolution variant rolled back: {variant_id}",
        payload={"variant": variant.model_dump(mode="json"), "guardian_gate": gate},
        level="WARNING",
    )
    return {"ok": True, "variant": variant.model_dump(mode="json"), "guardian_gate": gate}


@app.get("/api/evolution/lineage/{target_id}")
async def get_evolution_lineage(target_id: str) -> dict[str, object]:
    """Return active variant lineage for one target id."""
    return {"ok": True, **_self_evolution_service().lineage(target_id)}


@app.get("/api/events/recent")
async def get_recent_events() -> dict[str, object]:
    """Return recent buffered events."""
    return {"events": controller.recent_events()}


_PACKAGE_EVENT_TYPE_ALIASES = {
    "run.created": "run_started",
    "run_safe_stop": "safe_stop_triggered",
    "graph.compiled": "graph_compiled",
    "graph_version_saved": "graph_version_saved",
    "tool_call_completed": "tool_call_completed",
    "handoff_created": "handoff_created",
    "agent_question": "agent_question",
    "user_reply": "user_reply",
    "approval.requested": "approval_requested",
}


def _package_runtime_event_type(event: dict[str, object]) -> str:
    """Return the package-level RuntimeEventType while preserving internal event names elsewhere."""
    raw_type = str(event.get("event_type") or event.get("type") or "runtime.event")
    if raw_type == "approval.resolved":
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        decision = str(payload.get("decision") or "").lower()
        if decision == "approved":
            return "approval_granted"
        if decision in {"rejected", "cancelled", "canceled"}:
            return "approval_rejected"
        return "approval_resolved"
    if raw_type in _PACKAGE_EVENT_TYPE_ALIASES:
        return _PACKAGE_EVENT_TYPE_ALIASES[raw_type]
    return re.sub(r"[^a-zA-Z0-9]+", "_", raw_type).strip("_").lower() or "runtime_event"


def _package_runtime_event(event: dict[str, object]) -> dict[str, object]:
    """Normalize an internal runtime event for the imported Live GUI package contract."""
    normalized = dict(event)
    payload = dict(event.get("payload") or {}) if isinstance(event.get("payload"), dict) else {}
    state = event.get("state") if isinstance(event.get("state"), dict) else {}
    package_type = _package_runtime_event_type(event)
    internal_type = str(event.get("event_type") or event.get("type") or package_type)
    artifact_ids = event.get("artifact_ids") or payload.get("artifact_ids") or payload.get("artifacts") or []
    if isinstance(artifact_ids, dict):
        artifact_ids = [artifact_ids.get("artifact_id") or artifact_ids.get("id") or artifact_ids.get("path") or artifact_ids.get("url") or ""]
    if not isinstance(artifact_ids, list):
        artifact_ids = [artifact_ids]
    unread_targets = event.get("unread_targets") or payload.get("unread_targets") or []
    if isinstance(unread_targets, str):
        unread_targets = [unread_targets]
    if not isinstance(unread_targets, list):
        unread_targets = []
    normalized.update({
        "event_type": internal_type,
        "event_type_internal": internal_type,
        "type": package_type,
        "timestamp": event.get("timestamp") or event.get("ts") or datetime.now(timezone.utc).isoformat(),
        "stage": event.get("stage") or payload.get("stage") or event.get("timestamp_stage") or state.get("stage", ""),
        "agent_id": event.get("agent_id") or payload.get("agent_id") or payload.get("agent") or event.get("agent") or "",
        "graph_id": event.get("graph_id") or payload.get("graph_id") or "atr_closed_loop",
        "graph_version": event.get("graph_version") or payload.get("graph_version") or payload.get("version_id") or payload.get("graph_hash") or "",
        "severity": str(event.get("severity") or event.get("level") or "info").lower(),
        "artifact_ids": [str(item) for item in artifact_ids if str(item)],
        "unread_targets": [str(item) for item in unread_targets if str(item)],
    })
    return normalized


@app.get("/api/events/stream")
async def stream_events() -> StreamingResponse:
    """SSE stream endpoint for real-time GUI updates."""
    queue = controller.subscribe()

    def sse_payload(event: dict[str, object]) -> str:
        payload = json.dumps(event, ensure_ascii=True)
        return f"event: update\ndata: {payload}\n\n"

    async def generator():
        try:
            yield sse_payload(
                {
                    "event_id": make_event_id(),
                    "event_type": "stream.connected",
                    "level": "INFO",
                    "message": "Runtime event stream connected",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "payload": {"heartbeat_interval_s": 15},
                }
            )
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    event = {
                        "event_id": make_event_id(),
                        "event_type": "stream.heartbeat",
                        "level": "INFO",
                        "message": "Runtime event stream heartbeat",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {"heartbeat": True},
                    }
                yield sse_payload(event)
        except asyncio.CancelledError:
            raise
        finally:
            controller.unsubscribe(queue)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/api/runtime/events")
async def stream_runtime_events_compat() -> StreamingResponse:
    """Compatibility SSE stream using the imported package runtime event contract."""
    queue = controller.subscribe()

    def sse_payload(event: dict[str, object]) -> str:
        payload = json.dumps(_package_runtime_event(event), ensure_ascii=True)
        return f"event: update\ndata: {payload}\n\n"

    async def generator():
        try:
            yield sse_payload(
                {
                    "event_id": make_event_id(),
                    "event_type": "stream.connected",
                    "level": "INFO",
                    "message": "Runtime event stream connected",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "payload": {"heartbeat_interval_s": 15},
                }
            )
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    event = {
                        "event_id": make_event_id(),
                        "event_type": "stream.heartbeat",
                        "level": "INFO",
                        "message": "Runtime event stream heartbeat",
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "payload": {"heartbeat": True},
                    }
                yield sse_payload(event)
        except asyncio.CancelledError:
            raise
        finally:
            controller.unsubscribe(queue)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/api/planning/session")
async def get_planning_session(session_id: str | None = None) -> dict[str, object]:
    """Return planning conversation state without starting hardware."""
    return controller.planning_snapshot(session_id=session_id)


@app.get("/api/planning/messages")
async def get_planning_messages(
    session_id: str | None = None,
    before: int | None = None,
    limit: int = 80,
) -> dict[str, object]:
    """Return one lazy-loaded page from the file-backed Live GUI transcript."""
    return controller.planning_messages_page(session_id=session_id, before=before, limit=limit)


@app.post("/api/planning/bootstrap")
async def post_planning_bootstrap(req: PlanningBootstrapRequest) -> dict[str, object]:
    """Start the Live GUI orchestrator model before the operator sends a message."""
    return await controller.bootstrap_live_orchestrator(
        goal=req.goal,
        backend=req.backend,
        constraints=dict(req.constraints),
        session_id=req.session_id,
    )


@app.post("/api/planning/message")
async def post_planning_message(req: PlanningMessageRequest) -> dict[str, object]:
    """Ask the OrchestratorAgent model for live-planning guidance."""
    return await controller.planning_message(
        message=req.message,
        goal=req.goal,
        backend=req.backend,
        constraints=dict(req.constraints),
        session_id=req.session_id,
    )


@app.get("/api/planning/artifacts/{run_id}/{specimen_id}/{filename}")
async def get_planning_artifact(run_id: str, specimen_id: str, filename: str) -> FileResponse:
    """Serve planning-generated STL, preview, and experiment spec artifacts."""
    try:
        path = controller.planning_artifact_path(run_id, specimen_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="Planning artifact not found")
    return FileResponse(path)


@app.post("/api/run/start")
async def start_run(req: StartRunRequest) -> dict[str, object]:
    """Start a new orchestration run."""
    if req.mode == "live":
        config = _load_runtime_graph_config(PRIMARY_RUNTIME_GRAPH_ID)
        compiler = _runtime_graph_compiler(config)
        errors = compiler.validate()
        if errors:
            return {"ok": False, "graph_id": PRIMARY_RUNTIME_GRAPH_ID, "errors": errors, "run": None}
        compiler.compile()
        dry_run_ok, dry_run_record = _graph_live_dry_run_gate(config)
        if not dry_run_ok:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "GRAPH_DRY_RUN_REQUIRED",
                    "message": "Run graph dry-run on the active graph config before live execution.",
                    "graph_id": PRIMARY_RUNTIME_GRAPH_ID,
                    "has_record": bool(dry_run_record),
                },
            )
    return await controller.start(
        mode=Mode(req.mode),
        goal=req.goal,
        backend=req.backend,
        fault=req.fault,
        fault_stage=req.fault_stage,
    )


@app.post("/api/run/pause")
async def pause_run() -> dict[str, object]:
    """Pause current run."""
    return await controller.pause()


@app.post("/api/run/resume")
async def resume_run() -> dict[str, object]:
    """Resume paused run."""
    return await controller.resume()


@app.post("/api/run/stop")
async def stop_run() -> dict[str, object]:
    """Stop current run."""
    return await controller.stop()


@app.post("/api/run/safe-stop")
async def safe_stop_run() -> dict[str, object]:
    """Request safe stop."""
    return await controller.safe_stop()


@app.post("/api/runtime/start")
async def start_runtime_compat(req: StartRunRequest) -> dict[str, object]:
    """Compatibility alias for package-specified runtime start."""
    return await start_run(req)


@app.post("/api/runtime/pause")
async def pause_runtime_compat() -> dict[str, object]:
    """Compatibility alias for package-specified runtime pause."""
    return await controller.pause()


@app.post("/api/runtime/resume")
async def resume_runtime_compat() -> dict[str, object]:
    """Compatibility alias for package-specified runtime resume."""
    return await controller.resume()


@app.post("/api/runtime/stop")
async def stop_runtime_compat() -> dict[str, object]:
    """Compatibility alias for package-specified runtime stop."""
    return await controller.stop()


@app.post("/api/runtime/safe-stop")
async def safe_stop_runtime_compat() -> dict[str, object]:
    """Compatibility alias for package-specified runtime safe-stop."""
    return await controller.safe_stop()


@app.get("/api/runs/{run_id}")
async def get_runtime_run(run_id: str) -> dict[str, object]:
    """Return current run snapshot or persisted run directory metadata."""
    snapshot = controller.snapshot()
    current = _current_run_id()
    run_dir = _safe_run_dir(run_id)
    if run_id == current:
        return {"ok": True, "run_id": run_id, "active": True, "snapshot": snapshot, "run_dir": str(run_dir)}
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"Unknown run_id={run_id}")
    return {"ok": True, "run_id": run_id, "active": False, "snapshot": None, "run_dir": str(run_dir)}


@app.post("/api/runs/{run_id}/pause")
async def pause_runtime_run(run_id: str) -> dict[str, object]:
    """Pause the active run addressed by run_id."""
    _require_current_run(run_id)
    return await controller.pause()


@app.post("/api/runs/{run_id}/resume")
async def resume_runtime_run(run_id: str) -> dict[str, object]:
    """Resume the active run addressed by run_id."""
    _require_current_run(run_id)
    return await controller.resume()


@app.post("/api/runs/{run_id}/stop")
async def stop_runtime_run(run_id: str) -> dict[str, object]:
    """Stop the active run addressed by run_id."""
    _require_current_run(run_id)
    return await controller.stop()


@app.get("/api/runs/{run_id}/approvals")
async def get_runtime_approvals(run_id: str) -> dict[str, object]:
    """Return pending/resolved human approval items derived from runtime events."""
    if run_id != _current_run_id() and not _safe_run_dir(run_id).exists():
        raise HTTPException(status_code=404, detail=f"Unknown run_id={run_id}")
    queues = _approval_events_for_run(run_id)
    return {"ok": True, "run_id": run_id, **queues}


@app.post("/api/runs/{run_id}/approvals")
async def request_runtime_approval(run_id: str, req: RuntimeApprovalCreateRequest) -> dict[str, object]:
    """Create a standard approval.requested event for the active run."""
    _require_current_run(run_id)
    approval_id = make_event_id().replace("evt-", "approval-", 1)
    payload: dict[str, object] = {
        **req.payload,
        "approval_id": approval_id,
        "title": req.title,
        "reason": req.reason,
        "stage": req.stage or controller.snapshot().get("state", {}).get("stage", ""),
        "safety_class": req.safety_class,
        "requester": req.requester,
        "requires_human_approval": True,
        "status": "waiting_approval",
    }
    event = await controller.emit_runtime_event(
        event_type="approval.requested",
        message=req.title,
        payload=payload,
        level="WARNING",
        run_id=run_id,
    )
    queues = _approval_events_for_run(run_id)
    return {"ok": True, "run_id": run_id, "approval_id": approval_id, "event": event, **queues}


@app.post("/api/runs/{run_id}/approvals/{approval_id}/resolve")
async def resolve_runtime_approval(run_id: str, approval_id: str, req: RuntimeApprovalResolveRequest) -> dict[str, object]:
    """Resolve one pending human approval request and broadcast approval.resolved."""
    _require_current_run(run_id)
    queues = _approval_events_for_run(run_id)
    pending_ids = {str(item.get("approval_id")) for item in queues["pending"]}
    if approval_id not in pending_ids:
        raise HTTPException(status_code=404, detail=f"Unknown pending approval_id={approval_id}")
    resolution_state = controller.apply_runtime_approval_resolution(
        approval_id=approval_id,
        decision=req.decision,
        operator=req.operator,
        note=req.note,
    )
    payload = {
        "approval_id": approval_id,
        "decision": req.decision,
        "note": req.note,
        "operator": req.operator,
        "status": "resolved",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "runtime_gate": resolution_state,
    }
    level = "INFO" if req.decision == "approved" else "WARNING"
    event = await controller.emit_runtime_event(
        event_type="approval.resolved",
        message=f"Approval {req.decision}: {approval_id}",
        payload=payload,
        level=level,
        run_id=run_id,
    )
    updated = _approval_events_for_run(run_id)
    return {"ok": True, "run_id": run_id, "approval_id": approval_id, "event": event, **updated}


async def _resolve_approval_compat(approval_id: str, decision: Literal["approved", "rejected", "cancelled"], req: RuntimeApprovalResolveRequest | None) -> dict[str, object]:
    """Resolve an approval through the package-level approval endpoint aliases."""
    run_id = _current_run_id()
    if not run_id:
        raise HTTPException(status_code=404, detail="No active runtime run_id")
    payload = req or RuntimeApprovalResolveRequest(decision=decision)
    payload.decision = decision
    return await resolve_runtime_approval(run_id, approval_id, payload)


@app.post("/api/approvals/{approval_id}/approve")
async def approve_runtime_approval_compat(approval_id: str, req: RuntimeApprovalResolveRequest | None = None) -> dict[str, object]:
    """Compatibility endpoint for package-specified approval approval."""
    return await _resolve_approval_compat(approval_id, "approved", req)


@app.post("/api/approvals/{approval_id}/reject")
async def reject_runtime_approval_compat(approval_id: str, req: RuntimeApprovalResolveRequest | None = None) -> dict[str, object]:
    """Compatibility endpoint for package-specified approval rejection."""
    return await _resolve_approval_compat(approval_id, "rejected", req)


@app.post("/api/approvals/{approval_id}/revise")
async def revise_runtime_approval_compat(approval_id: str, req: RuntimeApprovalResolveRequest | None = None) -> dict[str, object]:
    """Compatibility endpoint for package-specified approval revision requests."""
    return await _resolve_approval_compat(approval_id, "cancelled", req)


@app.get("/api/runs/{run_id}/events")
async def get_runtime_run_events(run_id: str) -> dict[str, object]:
    """Return buffered events for one run id."""
    events = [event for event in controller.recent_events() if event.get("run_id") == run_id]
    if not events and run_id != _current_run_id() and not _safe_run_dir(run_id).exists():
        raise HTTPException(status_code=404, detail=f"Unknown run_id={run_id}")
    return {"ok": True, "run_id": run_id, "events": events}


@app.get("/api/runs/{run_id}/artifacts")
async def get_runtime_run_artifacts(run_id: str) -> dict[str, object]:
    """List artifact files created under one run directory."""
    run_dir, artifacts = _artifact_items_for_run(run_id)
    return {"ok": True, "run_id": run_id, "run_dir": str(run_dir), "artifacts": artifacts}


@app.get("/api/runs/{run_id}/artifact-file/{artifact_path:path}")
async def get_runtime_run_artifact_file(run_id: str, artifact_path: str, download: bool = False) -> FileResponse:
    """Preview or download one artifact file under a run directory."""
    path = _safe_run_artifact_path(run_id, artifact_path)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@app.get("/api/artifacts")
async def get_artifacts_compat(run_id: str | None = None) -> dict[str, object]:
    """Compatibility endpoint listing artifacts for a run or the active run."""
    selected_run_id = run_id or _current_run_id()
    run_dir, artifacts = _artifact_items_for_run(selected_run_id)
    return {"ok": True, "run_id": selected_run_id, "run_dir": str(run_dir), "artifacts": artifacts}


@app.get("/api/artifacts/{artifact_id:path}")
async def get_artifact_compat(artifact_id: str, run_id: str | None = None, download: bool = False) -> FileResponse:
    """Compatibility endpoint serving one artifact by artifact_id."""
    decoded_run_id, artifact_path = _parse_artifact_id(artifact_id, run_id=run_id)
    return await get_runtime_run_artifact_file(decoded_run_id, artifact_path, download=download)


@app.post("/api/runtime/gpu-clear")
async def runtime_gpu_clear() -> dict[str, object]:
    """Unload resident models and clear GPU memory pressure."""
    return await controller.clear_gpu()


@app.get(
    "/api/docs/agent-baseline",
    tags=["documentation"],
    summary="Agent Integration Baseline",
    description="Returns the baseline markdown content used when integrating real programs into agents.",
)
async def get_agent_integration_baseline() -> dict[str, object]:
    """Return baseline doc content as JSON for API consumers."""
    content = _load_agent_baseline_markdown()
    return {
        "name": "agent_program_baseline",
        "path": str(AGENT_BASELINE_DOC_PATH),
        "content": content,
    }


@app.get(
    "/api/docs/agent-baseline.md",
    response_class=PlainTextResponse,
    tags=["documentation"],
    summary="Agent Integration Baseline (Raw Markdown)",
    description="Returns raw markdown text for the agent integration baseline document.",
)
async def get_agent_integration_baseline_markdown() -> PlainTextResponse:
    """Return baseline doc as raw markdown text."""
    return PlainTextResponse(_load_agent_baseline_markdown(), media_type="text/markdown")
