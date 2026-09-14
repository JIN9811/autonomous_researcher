"""Unit tests for Improvement 15 multi-fidelity contracts."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from device_bridges.pinn_bridge import PINNBridge, PINNBridgeConfig
from experiments.schemas import (
    FEAResult,
    MultifidelityJob,
    PINNModelRecord,
    TrustScore,
    UTMRecord,
)
from mcp_tools.pinn_tools import register_pinn_tools
from mcp_tools.tool_registry import ToolRegistry


def test_multifidelity_schema_models_are_additive() -> None:
    trust = TrustScore(score=0.82, gate="allow_bo", components={"q_data": 1.0})
    utm = UTMRecord(specimen_id="specimen-1", displacement_mm=[0.0, 1.0], force_n=[0.0, 120.0])
    fea = FEAResult(specimen_id="specimen-1", solver_meta={"solver": "calculix"})
    pinn = PINNModelRecord(model_id="pinn-fixture", family="pinn")
    job = MultifidelityJob(job_type="analysis_compare", specimen_id="specimen-1", trust_score=trust)

    assert trust.schema == "trust_score.v1"
    assert utm.schema == "utm_record.v1"
    assert fea.schema == "fea_result.v1"
    assert pinn.schema == "pinn_model_record.v1"
    assert job.schema == "multifidelity_job.v1"
    assert job.trust_score.gate == "allow_bo"


def test_pinn_bridge_contract_returns_unavailable_without_active_model(tmp_path: Path) -> None:
    bridge = PINNBridge(PINNBridgeConfig(enabled=True, mode="test", artifact_dir=tmp_path))

    health = bridge.health()
    dataset = bridge.build_dataset({"specimen_id": "specimen-1", "utm_curve": [{"x": 0, "y": 0}]})
    prediction = bridge.predict({"specimen_id": "specimen-1"})

    assert health["tool"] == "pinn.health"
    assert dataset["ok"] is True
    assert dataset["dataset_path"].endswith(".json")
    assert prediction["ok"] is False
    assert prediction["status"] == "unavailable"
    assert prediction["failure_code"] == "PINN_MODEL_UNAVAILABLE"


def test_multifidelity_tools_are_registered(tmp_path: Path) -> None:
    registry = ToolRegistry()
    register_pinn_tools(registry, {"devices": {"pinn": {"enabled": True, "mode": "test", "artifact_dir": str(tmp_path / "pinn")}}}, repo_root=tmp_path)

    tools = set(registry.list_tools())

    assert {"pinn.health", "pinn.dataset.build", "pinn.predict", "pinn.registry"}.issubset(tools)
    assert registry.call("pinn.predict", {"specimen_id": "specimen-1"})["failure_code"] == "PINN_MODEL_UNAVAILABLE"
