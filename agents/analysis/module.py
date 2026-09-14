"""Code-discovered owner of experimental postprocessing and BO observations."""
import json
from pathlib import Path

from agents.analysis.agent import AnalysisAgent
from agents.analysis.presentation import REPORT_PROFILE, project_analysis_report
from agents.module_contract import AgentModule


ANALYSIS_MODULE = AgentModule(
    module_id="analysis",
    agent_name="analysis_agent",
    version="1.0.0",
    factory=AnalysisAgent,
    project_report=project_analysis_report,
    frontend_root=Path(__file__).parent / "frontend",
    descriptor_json=json.dumps({
        "report_profile": REPORT_PROFILE,
        "contract_version": "analysis_bo_handoff_v2",
        "capabilities": [
            "utm_measurement_analysis",
            "objective_evaluation",
            "bo_observation_handoff",
        ],
        "backend": {
            "entrypoint": "agents/analysis/agent.py",
            "decisions": "agents/analysis/decisions.py",
            "execution": "agents/analysis/execution.py",
            "structure": "agents/analysis/structure.py",
            "presentation": "agents/analysis/presentation.py",
        },
        "frontend": {
            "host": "/live",
            "descriptor": "graphs/modules/analysis/ui.yaml",
            "asset_url": "/module-assets/analysis/live_report.js",
            "namespace": "AX4LABAnalysisUI",
            "factory": "createFrontend",
            "report_api": "/api/agents/analysis/report",
        },
        "configuration": {
            "setup_write_enabled": False,
            "source": "graphs/modules/analysis/module.yaml",
            "inputs": ["OrchestratorState.latest_analysis", "OrchestratorState.run_metadata"],
            "persistence": "existing loop-scoped measured-analysis artifacts",
        },
        "storage": {
            "archive_owner": "analysis_agent",
            "archive": "runs/<run_id>/runtime/loops/loop-N/analysis_agent/attempt-N/",
            "analysis_artifacts": "runs/<run_id>/analysis/<specimen_id>/",
            "new_settings_store": False,
            "shared_archive": "utils.agent_artifact_archive",
        },
        "dependencies": {
            "services": ["AgentContext.complete", "objective.service"],
            "tools": [],
            "bridge_modules": [],
            "direct_device_effect": False,
            "computation_ownership": "Analysis owns deterministic measurement processing and objective evaluation",
        },
        "owned_references": {
            "objective_service": "objectives/service.py",
        },
        "documentation": "docs/agents/analysis_agent.md",
    }, allow_nan=False),
)

MODULE = ANALYSIS_MODULE
