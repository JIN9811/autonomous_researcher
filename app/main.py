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
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

import yaml
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from self_evolution import EvolutionTaskCreate, SelfEvolutionService
from self_evolution.models import EvolutionActivationRequest, EvolutionRollbackRequest

from agents.manipulation_agent import ManipulationAgent
from agents.bo_agent import BOAgent
from app.bootstrap import load_runtime
from graphs import ATRLangGraphCompiler, GraphConfig, GraphVersionStore, HandlerRegistry, ModuleConfig, ModuleConfigStore, load_graph_config
from graphs.generated_adapter import GENERATED_MODULE_HANDLER_ID, generated_adapter_enabled, generated_adapter_path, validate_generated_adapter_file
from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from device_bridges.prusa_bridge import PrusaBridgeConfig, PrinterAgenticWorkflow
from device_bridges.windows_pyautogui_bridge import (
    WindowsPyAutoGUIBridge,
    WindowsPyAutoGUIBridgeConfig,
    discover_windows_pyautogui_bridges,
)
from orchestrator.state import Mode, OrchestratorState, Stage
from utils.config_loader import load_all_configs
from utils.manipulation_profile import (
    MANIPULATION_AGENT_PROFILE_PATH,
    load_manipulation_agent_profile,
    save_manipulation_agent_profile,
)
from utils.ids import make_event_id
from utils.paths import resolve_path
from utils.printer_profile import PRUSA_PRINT_PROFILE_PATH, load_prusa_print_profile, save_prusa_print_profile

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
PRIMARY_RUNTIME_GRAPH_ID = "atr_closed_loop"
RUNTIME_GRAPH_CONFIG_ROOT = resolve_path("graphs/configs")
RUNTIME_GRAPH_CONFIG_PATH = RUNTIME_GRAPH_CONFIG_ROOT / f"{PRIMARY_RUNTIME_GRAPH_ID}.yaml"
RUNTIME_GRAPH_VERSION_ROOT = resolve_path("memory/graph_versions")
RUNTIME_MODULE_ROOT = resolve_path("graphs/modules")
RUNTIME_MODULE_VERSION_ROOT = resolve_path("memory/module_versions")
_RUNTIME_GRAPH_DRY_RUN_RECORDS: dict[str, dict[str, object]] = {}
_SYSTEM_RESOURCE_CACHE: dict[str, object] = {"updated_at_monotonic": 0.0, "payload": {}}
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
        "title": "Print Preparation / Prusa Bridge",
        "summary": "Transforms the selected STL into slicer settings, upload/start commands, and printer bridge evidence.",
        "focus_rows": [
            {"label": "Bridge", "value": "PrusaLink host/auth, virtual bridge, installed-printer test, or real print mode"},
            {"label": "Slicer", "value": "layer height, bed/nozzle temperature, skirt/cap options, first-layer settings"},
            {"label": "Execution", "value": "upload, start, auto-ejection option, ready-state recovery, and logs"},
        ],
        "checklist": ["Show slicer parameters", "Confirm bridge mode", "Log upload/start result"],
    },
    "vision": {
        "title": "Vision Capture / Pickup Observation",
        "summary": "Captures the printed specimen and reports pickup-ready pose, visibility, and confidence.",
        "focus_rows": [
            {"label": "Inputs", "value": "camera bridge state, image frame, printer bed region, specimen id"},
            {"label": "Detection", "value": "object presence, estimated pose, occlusion, and pickup risk"},
            {"label": "Handoff", "value": "pose and confidence metadata for manipulation"},
        ],
        "checklist": ["Verify camera heartbeat", "Attach observation artifact", "Flag low confidence"],
    },
    "manipulation": {
        "title": "Robot Policy / Transfer Execution",
        "summary": "Runs or tests the selected LeRobot/Pi0.5 policy for moving the printed specimen to the next station.",
        "focus_rows": [
            {"label": "Policy", "value": "policy path, robot profile, camera config, and rollout safety settings"},
            {"label": "Motion", "value": "teleop/record/inference readiness, action clamp, stop condition"},
            {"label": "Result", "value": "transfer completion, log path, and failure reason if blocked"},
        ],
        "checklist": ["Confirm robot bridge", "Use safe rollout limits", "Record session log"],
    },
    "equipment": {
        "title": "Lab Equipment / Bridge Commands",
        "summary": "Controls external lab equipment through registered bridges such as Windows PyAutoGUI and UTM interfaces.",
        "focus_rows": [
            {"label": "Bridge", "value": "saved device alias, token-validated endpoint, heartbeat, and command catalog"},
            {"label": "Command", "value": "macro/program request, dry-run/live mode, command id, and result log"},
            {"label": "Safety", "value": "connection validation, timeout, and explicit error propagation"},
        ],
        "checklist": ["Select saved bridge", "Log command result", "Do not hide bridge errors"],
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


@app.on_event("startup")
async def keep_startup_side_effect_free() -> None:
    """Keep GUI startup side-effect free; operators load vLLM models manually."""
    return None


@app.on_event("shutdown")
async def shutdown_lerobot_subprocesses() -> None:
    """Release LeRobot live subprocesses so cameras/serial ports are not left busy."""
    _lerobot_bridge().shutdown()


class StartRunRequest(BaseModel):
    """Request body for run start endpoint."""

    mode: Literal["live", "test", "replay", "fault-injection"] = "test"
    goal: str | None = None
    backend: Literal["nemoclaw", "ollama", "vllm"] | None = None
    fault: str = Field(default="none", description="Fault name for fault-injection mode")
    fault_stage: str = Field(default="", description="Stage where fault is injected")


class PlanningMessageRequest(BaseModel):
    """Request body for planning-workspace orchestrator messages."""

    message: str = Field(..., min_length=1)
    goal: str | None = None
    backend: Literal["nemoclaw", "ollama", "vllm"] | None = None
    constraints: dict[str, object] = Field(default_factory=dict)
    session_id: str | None = None


class PlanningBootstrapRequest(BaseModel):
    """Request body for starting the Live GUI orchestrator before user input."""

    goal: str | None = None
    backend: Literal["nemoclaw", "ollama", "vllm"] | None = None
    constraints: dict[str, object] = Field(default_factory=dict)
    session_id: str | None = None


class BackendSwitchRequest(BaseModel):
    """Request body for one-click inference backend switching."""

    backend: Literal["nemoclaw", "ollama", "vllm"]


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
    transform_model: str = "gemma4:31b"


class RuntimeGraphDryRunRequest(BaseModel):
    """Request body for graph dry-run simulation options."""

    start_stage: str = "idle"
    max_steps: int = 24
    graph: dict[str, object] = Field(default_factory=dict)


class RuntimeModelRequest(BaseModel):
    """Request body for managed vLLM model load/unload controls."""

    model: str = Field(..., min_length=1)


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
    """Request body for editable PrusaLink connection memory."""

    host: str = Field(default="", min_length=0)
    scheme: Literal["http", "https"] = "http"
    port: int = Field(default=80, ge=1, le=65535)
    storage: str = "usb"
    auth_mode: Literal["digest", "basic", "api_key", "none"] = "digest"
    username: str = ""
    password: str = ""
    api_key: str = ""
    api_key_header: str = "X-Api-Key"


class PrinterAutoejectionTestRequest(BaseModel):
    """Request body for standalone 3DP autoejection test programs."""

    position: Literal["left", "center", "right"] = "center"
    mode: Literal["live", "test"] = "live"
    object_size_mm: list[float] = Field(default_factory=lambda: [30.0, 30.0, 20.0])
    start_immediately: bool = True


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
    camera_enabled: bool = False
    display_data: bool = False
    resume: bool = False
    push_to_hub: bool = False
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
    backend: Literal["nemoclaw", "ollama", "vllm"] | None = None
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


def _lerobot_bridge() -> LeRobotBridge:
    """Return one shared LeRobot bridge for all GUI windows."""
    global _LEROBOT_BRIDGE, _LEROBOT_CONFIG_MTIME_NS
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


def _read_ram_snapshot() -> dict[str, object]:
    """Read host RAM from /proc/meminfo without adding a psutil dependency."""
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


def _read_nvidia_process_memory_mb(nvidia_smi: str) -> dict[str, float]:
    """Fallback GPU memory view for devices whose aggregate memory is reported as N/A."""
    try:
        result = subprocess.run([nvidia_smi], check=False, capture_output=True, text=True, timeout=1.5)
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
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {"status": "unavailable", "message": "nvidia-smi not found", "gpus": []}
    query = "index,name,memory.total,memory.used,utilization.gpu,temperature.gpu"
    try:
        result = subprocess.run(
            [nvidia_smi, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unknown", "message": f"nvidia-smi failed: {exc}", "gpus": []}
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "nvidia-smi returned non-zero").strip().splitlines()[0]
        return {"status": "unknown", "message": message, "gpus": []}
    process_memory = _read_nvidia_process_memory_mb(nvidia_smi)
    gpus: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6:
            continue
        index, name, mem_total, mem_used, util, temp = parts[:6]
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
    return {
        "status": worst,
        "message": f"{len(gpus)} NVIDIA GPU(s)",
        "gpus": gpus,
        "aggregate": aggregate,
    }


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


@app.get("/api/state")
async def get_state() -> dict[str, object]:
    """Return current controller state plus host/GPU resource telemetry."""
    snapshot = controller.snapshot()
    snapshot["system_resources"] = _system_resource_snapshot()
    return snapshot


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


def _self_evolution_service() -> SelfEvolutionService:
    """Return the file-backed ATR self-evolution service."""
    return SelfEvolutionService(
        root=SELF_EVOLUTION_ROOT,
        run_root=resolve_path("runs"),
        graph_config_root=RUNTIME_GRAPH_CONFIG_ROOT,
        graph_version_root=RUNTIME_GRAPH_VERSION_ROOT,
        module_root=RUNTIME_MODULE_ROOT,
        module_version_root=RUNTIME_MODULE_VERSION_ROOT,
    )


def _graph_config_payload(graph_id: str = PRIMARY_RUNTIME_GRAPH_ID) -> dict[str, object]:
    """Return one config-driven LangGraph definition as JSON-safe data."""
    config = _load_runtime_graph_config(graph_id)
    return config.model_dump(mode="json")


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
    """Return the fixed system prompt used by Gemma 31B module designer."""
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
    """Build the bounded Gemma 31B prompt for Python-to-ATR module conversion."""
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


async def _transform_module_source_with_gemma31b(req: RuntimeModuleCreateRequest, safe_id: str) -> dict[str, Any]:
    """Use Gemma 31B directly, without fallback, to transform uploaded Python into ATR module JSON."""
    source_text = str(req.source_text or "")
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="Module Designer requires a Python source file.")

    model = str(req.transform_model or "gemma4:31b").strip() or "gemma4:31b"
    if model != "gemma4:31b":
        raise HTTPException(status_code=400, detail="Module Designer is locked to gemma4:31b for protocol conversion.")

    ctx = controller._deps.agent_context
    backend = ctx.primary_backends.get("vllm") or ctx.primary_backend
    prepare_model = getattr(backend, "prepare_model", None)
    if prepare_model is not None:
        await prepare_model(model)

    source_limit = 7200
    source_excerpt = source_text[:source_limit]
    source_truncated = len(source_text) > source_limit
    handlers = sorted(_runtime_graph_handler_registry().names())
    tools = sorted(_registered_tool_names())
    try:
        response = await backend.complete(
            model=model,
            system_prompt=_module_designer_system_prompt(),
            user_prompt=_module_designer_user_prompt(
                req=req,
                safe_id=safe_id,
                source_excerpt=source_excerpt,
                source_truncated=source_truncated,
                handler_names=handlers,
                tool_names=tools,
            ),
            metadata={"task_type": "module_designer", "role": "orchestrator", "max_tokens": 1400},
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gemma 31B module transform failed: {exc}") from exc

    try:
        payload = _extract_json_object(response.text)
    except Exception as exc:
        snippet = response.text[:1200] if response.text else ""
        raise HTTPException(status_code=502, detail=f"Gemma 31B returned invalid module JSON: {exc}; response={snippet}") from exc

    transformed_source = str(payload.get("transformed_source") or "").strip()
    if not transformed_source:
        raise HTTPException(status_code=502, detail="Gemma 31B response did not include transformed_source.")
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
    snapshot = controller.planning_snapshot()
    state = snapshot.get("state", {}) if isinstance(snapshot.get("state"), dict) else {}
    messages = [msg for msg in snapshot.get("messages", []) if isinstance(msg, dict)]
    role_aliases = {definition["agent_id"], definition["stage"], definition["module_id"]}
    agent_messages = [msg for msg in messages if str(msg.get("role") or "").lower() in role_aliases]
    warning_events = [event for event in events if str(event.get("level") or event.get("severity") or "").lower() in {"warning", "error", "critical"}]
    status = "running" if str(state.get("stage") or "") == definition["stage"] and controller.snapshot().get("is_running") else "idle"
    if warning_events:
        status = "warning"
    if events and str(events[-1].get("level") or "").lower() == "error":
        status = "error"
    summary = events[-1].get("message") if events else f"No runtime events recorded for {definition['label']} yet."
    role_specific = LIVE_AGENT_REPORT_PROFILES.get(definition["agent_id"], {
        "title": f"{definition['label']} Runtime Role",
        "summary": f"Runtime evidence and follow-up context for {definition['label']}.",
        "focus_rows": [],
        "checklist": ["Review messages", "Inspect backend trace", "Confirm next action"],
    })
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
        "decisions": [],
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
    return {"ok": True, "run_id": _current_run_id(), "devices": devices, "system_resources": resources}


def _require_current_run(run_id: str) -> None:
    """Ensure a mutating run command targets the active run."""
    current = _current_run_id()
    if run_id != current:
        raise HTTPException(status_code=404, detail=f"Unknown active run_id={run_id}")


def _approval_id_from_event(event: dict[str, Any]) -> str:
    """Return the stable approval id associated with one approval event."""
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return str(payload.get("approval_id") or payload.get("id") or event.get("event_id") or "")


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
    """Create a cataloged Runtime IDE module from an uploaded Python file via Gemma 31B."""
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
        transform_payload = await _transform_module_source_with_gemma31b(req, safe_id)
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

    metadata: dict[str, object] = {
        "category": category,
        "created_from": "runtime_ide_module_designer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_filename": original_source_name,
        "python_source_path": str(original_path) if req.source_text.strip() else "",
        "transformed_python_source_path": str(transformed_path),
        "transformed_by_model": "gemma4:31b" if req.transform_with_llm else "operator_disabled_llm_transform",
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
            "model": "gemma4:31b" if req.transform_with_llm else "disabled",
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
        graph_config_path=config_path,
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
    strategies = ["random", "grid", "bo"] if settings["strategy"] == "mbo" else [settings["strategy"]]
    result = controller._deps.agent_context.tools.call(
        "experiment.benchmark",
        {
            "budget": settings["budget"],
            "strategies": strategies,
            "seed": settings["random_seed"],
            "parameter_space": settings["parameter_space"],
            "objective": objective,
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


@app.get("/api/equipment/windows/config")
async def get_windows_equipment_config() -> dict[str, object]:
    """Return saved Windows PyAutoGUI bridge configuration status."""
    bridge = _equipment_bridge()
    status = bridge.connection_status()
    programs = bridge.list_programs({"runtime_mode": "test"})
    return {"ok": True, "connection": status, "programs": programs.get("programs", [])}


@app.get("/api/printer/status")
async def get_printer_status(mode: Literal["live", "test"] = "live") -> dict[str, object]:
    """Return redacted Prusa MK4S/PrusaLink status for GUI display."""
    workflow = _printer_workflow()
    config = workflow.config
    connection = _redacted_printer_connection(workflow)
    health = workflow.health({"runtime_mode": mode})
    profile = load_prusa_print_profile()
    return {
        "ok": bool(health.get("ok")),
        "mode": mode,
        "provider": config.provider,
        "connection": connection,
        "live_gates": {
            "allow_status": config.live_gate("allow_status", True),
            "allow_upload": config.live_gate("allow_upload", False),
            "allow_start_print": config.live_gate("allow_start_print", False),
            "allow_ejection": config.live_gate("allow_ejection", False),
        },
        "auto_ejection": {
            "enabled": bool(profile.get("allow_ejection", False)),
            "method": config.ejection.method,
            "mode": config.ejection.mode,
        },
        "slicer": {
            "enabled": config.slicer.enabled,
            "executable_env": config.slicer.executable_env,
            "executable_path": config.slicer.executable_path,
            "output_dir": config.slicer.output_dir,
        },
        "profile": profile,
        "profile_path": str(PRUSA_PRINT_PROFILE_PATH),
        "health": health,
    }


@app.get("/api/printer/connection")
async def get_printer_connection() -> dict[str, object]:
    """Return editable PrusaLink bridge connection fields without secrets."""
    workflow = _printer_workflow()
    workflow.connection_memory.ensure_template(workflow.config.live)
    return {"ok": True, "connection": _redacted_printer_connection(workflow)}


@app.post("/api/printer/connection")
async def post_printer_connection(req: PrinterConnectionRequest) -> dict[str, object]:
    """Persist PrusaLink bridge connection memory from the 3DP GUI."""
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


@app.get("/api/printer/profile")
async def get_printer_profile() -> dict[str, object]:
    """Return operator-controlled 3DP print profile defaults."""
    workflow = _printer_workflow()
    config = workflow.config
    profile = load_prusa_print_profile()
    return {
        "ok": True,
        "profile": profile,
        "profile_path": str(PRUSA_PRINT_PROFILE_PATH),
        "connection_memory_path": str(workflow.connection_memory.path),
        "live_gates": {
            "allow_status": config.live_gate("allow_status", True),
            "allow_upload": config.live_gate("allow_upload", False),
            "allow_start_print": config.live_gate("allow_start_print", False),
            "allow_ejection": config.live_gate("allow_ejection", False),
        },
        "auto_ejection": {
            "enabled": bool(profile.get("allow_ejection", False)),
            "method": config.ejection.method,
            "mode": config.ejection.mode,
        },
        "slicer": {
            "enabled": config.slicer.enabled,
            "executable_env": config.slicer.executable_env,
            "executable_path": config.slicer.executable_path,
            "output_dir": config.slicer.output_dir,
        },
    }


@app.post("/api/printer/profile")
async def post_printer_profile(req: PrinterProfileRequest) -> dict[str, object]:
    """Persist operator-controlled 3DP print profile defaults."""
    workflow = _printer_workflow()
    config = workflow.config
    profile = save_prusa_print_profile(req.model_dump())
    return {
        "ok": True,
        "profile": profile,
        "profile_path": str(PRUSA_PRINT_PROFILE_PATH),
        "live_gates": {
            "allow_status": config.live_gate("allow_status", True),
            "allow_upload": config.live_gate("allow_upload", False),
            "allow_start_print": config.live_gate("allow_start_print", False),
            "allow_ejection": config.live_gate("allow_ejection", False),
        },
        "auto_ejection": {
            "enabled": bool(profile.get("allow_ejection", False)),
            "method": config.ejection.method,
            "mode": config.ejection.mode,
        },
        "slicer": {
            "enabled": config.slicer.enabled,
            "executable_env": config.slicer.executable_env,
            "executable_path": config.slicer.executable_path,
            "output_dir": config.slicer.output_dir,
        },
        "message": "Prusa MK4S print profile saved.",
    }


@app.post("/api/printer/autoejection-test")
async def post_printer_autoejection_test(req: PrinterAutoejectionTestRequest) -> dict[str, object]:
    """Run a standalone autoejection test using the same ejection G-code builder."""
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


@app.post("/api/equipment/windows/run-program")
async def post_windows_equipment_run_program(req: WindowsBridgeRunProgramRequest) -> dict[str, object]:
    """Run an explicit setup-GUI macro test such as program1."""
    if not req.confirm_execute:
        raise HTTPException(status_code=400, detail="confirm_execute=true is required for setup GUI macro tests")
    bridge = _equipment_bridge()
    result = bridge.run(
        {
            "runtime_mode": "live",
            "force_live_bridge": True,
            "confirm_setup_gui_execute": True,
            "sequence_id": f"setup-{req.program_id}",
            "program_id": req.program_id,
            "command": req.command or f"{req.program_id} 실행",
        }
    )
    await controller.emit_workspace_result(
        workspace="equipment",
        tool="equipment.pyautogui.run",
        result=result,
        stage=Stage.EQUIPMENT,
        module_id="equipment",
        agent="equipment_agent",
        workflow="windows_run_program",
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
    """Return recent LeRobot sessions."""
    bridge = _lerobot_bridge()
    return {"ok": True, "sessions": bridge.sessions_recent()}


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
    result = _lerobot_bridge().visualize_start(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/visualize/stop")
async def post_lerobot_visualize_stop(req: LeRobotAPIRequest) -> dict[str, object]:
    """Stop a LeRobot dataset visualizer session."""
    result = _lerobot_bridge().visualize_stop(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/visualize/status")
async def post_lerobot_visualize_status(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return LeRobot dataset visualizer status."""
    return _lerobot_bridge().visualize_status(req.model_dump())


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
    result = _lerobot_bridge().teleoperate_start(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/teleoperate/stop")
async def post_lerobot_teleoperate_stop(req: LeRobotAPIRequest) -> dict[str, object]:
    """Stop LeRobot teleoperation."""
    result = _lerobot_bridge().teleoperate_stop(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/teleoperate/status")
async def post_lerobot_teleoperate_status(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return LeRobot teleoperation status."""
    return _lerobot_bridge().teleoperate_status(req.model_dump())


@app.post("/api/lerobot/record/start")
async def post_lerobot_record_start(req: LeRobotAPIRequest) -> dict[str, object]:
    """Start LeRobot dataset recording."""
    result = _lerobot_bridge().record_start(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/record/control")
async def post_lerobot_record_control(req: LeRobotRecordControlAPIRequest) -> dict[str, object]:
    """Apply a LeRobot recording control action."""
    result = _lerobot_bridge().record_control(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/record/status")
async def post_lerobot_record_status(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return LeRobot recording status."""
    return _lerobot_bridge().record_status(req.model_dump())


@app.post("/api/lerobot/train/start")
async def post_lerobot_train_start(req: LeRobotAPIRequest) -> dict[str, object]:
    """Start LeRobot policy training."""
    result = _lerobot_bridge().train_start(req.model_dump(exclude_unset=True))
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/train/cancel")
async def post_lerobot_train_cancel(req: LeRobotAPIRequest) -> dict[str, object]:
    """Cancel LeRobot policy training."""
    result = _lerobot_bridge().train_cancel(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/train/status")
async def post_lerobot_train_status(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return LeRobot training status."""
    return _lerobot_bridge().train_status(req.model_dump())


@app.post("/api/lerobot/rollout/start")
async def post_lerobot_rollout_start(req: LeRobotAPIRequest) -> dict[str, object]:
    """Start LeRobot policy rollout/inference."""
    result = _lerobot_bridge().rollout_start(req.model_dump())
    return await _publish_lerobot_result(result)


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
        "task_instruction": req.task_instruction,
        "source_location": req.source_location,
        "target_location": req.target_location,
        "device": req.device,
        "fps": req.fps,
        "camera_enabled": req.camera_enabled,
        "display_data": req.display_data,
        "continuous_rollout": req.continuous_rollout,
        "rollout_action_clamp": req.rollout_action_clamp,
        "rollout_max_relative_target": req.rollout_max_relative_target,
        "rollout_temporal_ensemble": req.rollout_temporal_ensemble,
        "rollout_temporal_ensemble_coeff": req.rollout_temporal_ensemble_coeff,
        "rollout_inference_type": req.rollout_inference_type,
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
        "task_instruction": profile.get("task_instruction"),
        "source_location": profile.get("source_location"),
        "target_location": profile.get("target_location"),
        "lerobot_device": profile.get("device"),
        "device": profile.get("device"),
        "fps": profile.get("fps"),
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
    result = _lerobot_bridge().rollout_stop(req.model_dump())
    return await _publish_lerobot_result(result)


@app.post("/api/lerobot/rollout/status")
async def post_lerobot_rollout_status(req: LeRobotAPIRequest) -> dict[str, object]:
    """Return LeRobot rollout status."""
    return _lerobot_bridge().rollout_status(req.model_dump())


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
    await controller.emit_runtime_event(
        event_type="evolution.variant.approved",
        message=f"Self-evolution variant approved: {variant_id}",
        payload={"variant": variant.model_dump(mode="json")},
        level="INFO",
    )
    return {"ok": True, "variant": variant.model_dump(mode="json")}


@app.post("/api/evolution/variants/{variant_id}/activate")
async def activate_evolution_variant(variant_id: str, req: EvolutionActivationRequest | None = None) -> dict[str, object]:
    """Activate an approved variant for the next closed-loop run."""
    if controller.snapshot().get("is_running"):
        raise HTTPException(status_code=409, detail="Cannot activate self-evolution variant while a run is active.")
    payload = req or EvolutionActivationRequest()
    try:
        variant = _self_evolution_service().activate_variant(
            variant_id,
            operator=payload.operator,
            note=payload.note,
            activate_runtime=payload.activate_runtime,
            handler_registry=_runtime_graph_handler_registry(),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await controller.emit_runtime_event(
        event_type="evolution.variant.activated",
        message=f"Self-evolution variant active for next run: {variant_id}",
        payload={"variant": variant.model_dump(mode="json")},
        level="WARNING" if payload.activate_runtime else "INFO",
    )
    return {"ok": True, "variant": variant.model_dump(mode="json")}


@app.post("/api/evolution/variants/{variant_id}/rollback")
async def rollback_evolution_variant(variant_id: str, req: EvolutionRollbackRequest | None = None) -> dict[str, object]:
    """Mark a self-evolution variant as rolled back in the evolution registry."""
    payload = req or EvolutionRollbackRequest()
    try:
        variant = _self_evolution_service().rollback_variant(variant_id, operator=payload.operator, note=payload.note)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await controller.emit_runtime_event(
        event_type="evolution.variant.rolled_back",
        message=f"Self-evolution variant rolled back: {variant_id}",
        payload={"variant": variant.model_dump(mode="json")},
        level="WARNING",
    )
    return {"ok": True, "variant": variant.model_dump(mode="json")}


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
