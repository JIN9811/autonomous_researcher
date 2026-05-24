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
import json
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.bootstrap import load_runtime
from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig
from device_bridges.prusa_bridge import PrusaBridgeConfig, PrinterAgenticWorkflow
from device_bridges.windows_pyautogui_bridge import (
    WindowsPyAutoGUIBridge,
    WindowsPyAutoGUIBridgeConfig,
    discover_windows_pyautogui_bridges,
)
from orchestrator.state import Mode
from utils.config_loader import load_all_configs
from utils.paths import resolve_path
from utils.printer_profile import PRUSA_PRINT_PROFILE_PATH, load_prusa_print_profile, save_prusa_print_profile

app = FastAPI(title="Autonomous Researcher")
templates = Jinja2Templates(directory=str(resolve_path("web/templates")))
app.mount("/static", StaticFiles(directory=str(resolve_path("web/static"))), name="static")

controller = load_runtime()
AGENT_BASELINE_DOC_PATH = resolve_path("docs/runtime/agent_program_baseline.md")
_LEROBOT_BRIDGE: LeRobotBridge | None = None
_LEROBOT_CONFIG_MTIME_NS: int = -1


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


class RuntimeModelRequest(BaseModel):
    """Request body for managed vLLM model load/unload controls."""

    model: str = Field(..., min_length=1)


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


@app.get("/api/state")
async def get_state() -> dict[str, object]:
    """Return current controller state."""
    return controller.snapshot()


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
    return workflow.run_autoejection_test(payload)


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
    return {"ok": bool(health.get("ok")), "health": health, "programs": programs}


@app.post("/api/equipment/windows/run-program")
async def post_windows_equipment_run_program(req: WindowsBridgeRunProgramRequest) -> dict[str, object]:
    """Run an explicit setup-GUI macro test such as program1."""
    if not req.confirm_execute:
        raise HTTPException(status_code=400, detail="confirm_execute=true is required for setup GUI macro tests")
    bridge = _equipment_bridge()
    return bridge.run(
        {
            "runtime_mode": "live",
            "force_live_bridge": True,
            "confirm_setup_gui_execute": True,
            "sequence_id": f"setup-{req.program_id}",
            "program_id": req.program_id,
            "command": req.command or f"{req.program_id} 실행",
        }
    )


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


@app.get("/api/events/recent")
async def get_recent_events() -> dict[str, object]:
    """Return recent buffered events."""
    return {"events": controller.recent_events()}


@app.get("/api/events/stream")
async def stream_events() -> StreamingResponse:
    """SSE stream endpoint for real-time GUI updates."""
    queue = controller.subscribe()

    async def generator():
        try:
            while True:
                event = await queue.get()
                payload = json.dumps(event, ensure_ascii=True)
                yield f"event: update\ndata: {payload}\n\n"
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
