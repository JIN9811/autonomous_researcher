"""
File purpose:
- Define typed global state object for LangGraph-style orchestration.

Key classes/functions:
- Mode
- Stage
- AgentRuntimeStatus
- OrchestratorState

Inputs/outputs:
- Input: control commands, agent outputs, device health updates
- Output: validated mutable run state used by orchestration and GUI

Dependencies:
- enum.Enum
- pydantic.BaseModel

Modification guide:
- Safe places to edit: additive fields and optional metadata
- Risky places to edit: field names consumed by GUI and tests
- Related files: orchestrator/transitions.py, app/controller.py
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Mode(str, Enum):
    """Execution mode selected by operator or CLI."""

    LIVE = "live"
    TEST = "test"
    REPLAY = "replay"
    FAULT_INJECTION = "fault-injection"


class Stage(str, Enum):
    """Explicit orchestration stages used by the run graph."""

    IDLE = "idle"
    DESIGN = "design"
    SPECIMEN = "specimen"
    VISION = "vision"
    MANIPULATION = "manipulation"
    EQUIPMENT = "equipment"
    ANALYSIS = "analysis"
    KNOWLEDGE = "knowledge"
    GUARDIAN = "guardian"
    COMPLETE = "complete"
    ERROR = "error"


class AgentRuntimeStatus(BaseModel):
    """Per-agent status tracked for GUI monitoring."""

    state: str = "idle"
    last_run_time: str | None = None
    last_result: str | None = None
    success: bool | None = None
    mode: str = "test"


class OrchestratorState(BaseModel):
    """Global typed state object for orchestrator and GUI."""

    run_id: str
    experiment_id: str
    mode: Mode = Mode.TEST
    stage: Stage = Stage.IDLE
    active_goal: str = "Bootstrap autonomous researcher loop"
    device_health: dict[str, str] = Field(default_factory=dict)
    current_experiment_spec: dict[str, Any] = Field(default_factory=dict)
    current_experiment_objective: dict[str, Any] = Field(default_factory=dict)
    experiment_evaluations: list[dict[str, Any]] = Field(default_factory=list)
    active_session_id: str = ""
    latest_observations: dict[str, Any] = Field(default_factory=dict)
    latest_analysis: dict[str, Any] = Field(default_factory=dict)
    retry_counters: dict[str, int] = Field(default_factory=dict)
    run_metadata: dict[str, Any] = Field(default_factory=dict)
    agent_status: dict[str, AgentRuntimeStatus] = Field(default_factory=dict)
    fault_injection: dict[str, Any] = Field(default_factory=dict)
    is_paused: bool = False
    stop_requested: bool = False
    safe_stop_requested: bool = False
    loop_count: int = 0
