"""Code-discovered BO owner; existing services retain numerical execution."""
import json
from pathlib import Path

from agents.bo.agent import BOAgent
from agents.bo.presentation import REPORT_PROFILE, project_bo_report
from agents.module_contract import AgentModule


BO_MODULE = AgentModule(
    module_id="bo",
    agent_name="bo_agent",
    version="1.0.0",
    factory=BOAgent,
    project_report=project_bo_report,
    frontend_root=Path(__file__).parent / "frontend",
    descriptor_json=json.dumps({
        "report_profile": REPORT_PROFILE,
        "contract_version": "next_design_request.v1",
        "capabilities": [
            "analysis_observation_admission",
            "lhs_initial_design",
            "botorch_candidate_selection",
            "design_request_handoff",
        ],
        "backend": {
            "entrypoint": "agents/bo/agent.py",
            "decision": "agents/bo/decision.py",
            "execution": "agents/bo/execution.py",
            "structure": "agents/bo/structure.py",
            "presentation": "agents/bo/presentation.py",
        },
        "frontend": {
            "host": "/live",
            "descriptor": "graphs/modules/bo/ui.yaml",
            "asset_url": "/module-assets/bo/live_report.js",
            "namespace": "AX4LABBOUI",
            "factory": "createFrontend",
            "report_api": "/api/agents/bo/report",
        },
        "configuration": {
            "setup_write_enabled": True,
            "source": "graphs/modules/bo/module.yaml",
            "workspace_settings": "memory/bo_workspace_settings.json",
            "inputs": [
                "OrchestratorState.latest_analysis",
                "OrchestratorState.experiment_evaluations",
                "OrchestratorState.run_metadata",
            ],
            "persistence": "existing BO workspace settings and run metadata",
        },
        "storage": {
            "archive_owner": "bo_agent",
            "archive": "runs/<run_id>/runtime/loops/loop-N/bo_agent/attempt-N/",
            "artifacts": "runs/<run_id>/bo/",
            "workspace_settings": "memory/bo_workspace_settings.json",
            "new_settings_store": False,
            "shared_archive": "utils.agent_artifact_archive",
        },
        "dependencies": {
            "services": [
                "AgentContext.complete",
                "experiment.benchmark",
                "learning.BOParameterSpace",
                "learning.botorch_backend",
                "knowledge local index",
            ],
            "tools": ["experiment.benchmark"],
            "bridge_modules": [],
            "direct_device_effect": False,
            "numerical_ownership": "Existing learning and experiments services retain all LHS, BoTorch and acquisition computation",
        },
        "owned_references": {
            "parameter_space": "learning/bo_parameter_space.py",
            "botorch": "learning/botorch_backend.py",
            "benchmark": "experiments/benchmark.py",
            "workspace_template": "web/templates/bo.html",
            "workspace_assets": ["web/static/bo.js", "web/static/bo_visualization.js"],
        },
        "documentation": "docs/agents/bo_agent.md",
    }, allow_nan=False),
)

MODULE = BO_MODULE
