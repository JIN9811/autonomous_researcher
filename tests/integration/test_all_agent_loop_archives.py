"""All production agent entrypoints retain two-loop evidence without providers.

Dependencies stop at an explicit non-actuating boundary: this verifies archive
coverage, not experimental success or hardware behavior.
"""
from pathlib import Path

import pytest

from agents.analysis_agent import AnalysisAgent
from agents.bo_agent import BOAgent
from agents.design_agent import DesignAgent
from agents.equipment_agent import LabEquipmentAgent
from agents.guardian_agent import GuardianAgent
from agents.knowledge_agent import KnowledgeAgent
from agents.manipulation_agent import ManipulationAgent
from agents.orchestrator_agent import OrchestratorAgent
from agents.specimen_agent import SpecimenMakingAgent
from agents.vision_agent import VisionAgent
from orchestrator.state import OrchestratorState, Stage
from utils.agent_artifact_archive import list_executions


class NonActuatingBoundary(BaseException):
    pass


class OfflineContext:
    def __init__(self, root):
        self.artifact_run_root = root

    def __getattr__(self, name):
        raise NonActuatingBoundary(name)


@pytest.mark.asyncio
@pytest.mark.parametrize("agent_type,stage", [
    (OrchestratorAgent, Stage.DESIGN), (BOAgent, Stage.BO), (DesignAgent, Stage.DESIGN),
    (SpecimenMakingAgent, Stage.SPECIMEN), (VisionAgent, Stage.VISION),
    (ManipulationAgent, Stage.MANIPULATION), (LabEquipmentAgent, Stage.EQUIPMENT),
    (AnalysisAgent, Stage.ANALYSIS), (KnowledgeAgent, Stage.KNOWLEDGE), (GuardianAgent, Stage.GUARDIAN),
])
async def test_all_real_entrypoints_preserve_loop_and_failure_identity(tmp_path, agent_type, stage):
    ctx = OfflineContext(tmp_path / "runs")
    for loop in (0, 1):
        state = OrchestratorState(run_id="run-all-agent-archive", experiment_id="offline-only",
            loop_count=loop, stage=stage, current_experiment_spec={"specimen_id": "fixture"})
        try:
            await agent_type().run(state, ctx)
        except (NonActuatingBoundary, RuntimeError, ValueError):
            pass
    entries = list_executions(Path(ctx.artifact_run_root) / "run-all-agent-archive")
    assert len(entries) == 2
    assert [item["loop_index"] for item in entries] == [0, 1]
    assert all(item["agent"] == agent_type.name for item in entries)
    assert all(item["specimen_id"] == "fixture" for item in entries)
    assert all(item["status"] in {"completed", "failed"} for item in entries)
    assert all((Path(ctx.artifact_run_root) / state.run_id / item["result_path"]).is_file() for item in entries)
