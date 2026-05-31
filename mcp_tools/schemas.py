"""
File purpose:
- Structured schema definitions for MCP tool payload validation.

Key classes/functions:
- PrinterPrepareInput
- CameraCaptureInput
- RobotPickPlaceInput
- UTMRunInput

Inputs/outputs:
- Input: incoming payload dicts
- Output: validated Pydantic models

Dependencies:
- pydantic.BaseModel

Modification guide:
- Safe places to edit: optional fields and defaults
- Risky places to edit: required fields used in existing callers
- Related files: mcp_tools/tool_registry.py, agents/*.py
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PrinterPrepareInput(BaseModel):
    """Input schema for printer.prepare."""

    specimen_id: str = Field(default="spm-001")
    stl_path: str = Field(default="")
    handoff_package_path: str = Field(default="")
    printer_profile: str = Field(default="")
    material: str = Field(default="PLA")
    slicer_profile_hint: str = Field(default="")
    runtime_mode: str = Field(default="test")
    experiment_spec: dict = Field(default_factory=dict)
    print: dict = Field(default_factory=dict)
    ejection: dict = Field(default_factory=dict)
    connection_info: dict = Field(default_factory=dict)


class CameraCaptureInput(BaseModel):
    """Input schema for camera.capture."""

    frame_id: str = Field(default="frame-mock")
    camera_key: str = Field(default="top")
    purpose: str = Field(default="3dp_output_pickup_check")
    specimen_id: str = Field(default="")


class RobotPickPlaceInput(BaseModel):
    """Input schema for robot.pick_place."""

    task: str = Field(default="pick_place")


class UTMRunInput(BaseModel):
    """Input schema for utm.run_protocol."""

    profile: str = Field(default="default")
    runtime_mode: str = Field(default="test")
    run_id: str = Field(default="run-test")
    experiment_id: str = Field(default="")
    specimen_id: str = Field(default="specimen-test")
    program_id: str = Field(default="utm_compression_start_v1")
    result_file: str = Field(default="")
    utm_csv_path: str = Field(default="")
    direct_backend_configured: bool = Field(default=False)
    allow_live_direct_backend: bool = Field(default=False)
