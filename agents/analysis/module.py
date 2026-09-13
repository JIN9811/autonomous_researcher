"""Code-discovered Analysis owner; the CAE bridge retains computation."""
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
            "background_fem_improvement",
            "bo_observation_handoff",
        ],
        "backend": {
            "entrypoint": "agents/analysis/agent.py",
            "decisions": "agents/analysis/decisions.py",
            "runtime": "agents/analysis/runtime.py",
            "improvement": "agents/analysis/improvement.py",
            "refinement": "agents/analysis/refinement.py",
            "mechanisms": "agents/analysis/mechanisms.py",
            "calibration": "agents/analysis/calibration.py",
            "fem": "agents/analysis/fem.py",
            "execution": "agents/analysis/execution.py",
            "structure": "agents/analysis/structure.py",
            "presentation": "agents/analysis/presentation.py",
            "compatibility_imports": [
                "agents.analysis_agent",
                "agents.analysis_decisions",
                "agents.analysis_runtime",
                "agents.analysis_improvement",
                "agents.analysis_refinement",
                "agents.analysis_mechanisms",
                "agents.analysis_calibration",
                "agents.analysis_fem",
            ],
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
            "persistence": "existing run artifacts and Analysis improvement database",
        },
        "storage": {
            "archive_owner": "analysis_agent",
            "archive": "runs/<run_id>/runtime/loops/loop-N/analysis_agent/attempt-N/",
            "analysis_artifacts": "runs/<run_id>/analysis/<specimen_id>/",
            "improvement": "runs/<run_id>/runtime/analysis_improvement/improvement.sqlite3",
            "new_settings_store": False,
            "background_resource_lifetime": "existing_runtime_owned",
            "shared_archive": "utils.agent_artifact_archive",
        },
        "dependencies": {
            "services": ["AgentContext.complete", "AnalysisRuntimeService", "objective.service"],
            "tools": [
                "cae.prepare_static_analysis",
                "cae.run_static_analysis",
            ],
            "bridge_modules": ["cae"],
            "direct_device_effect": False,
            "computation_ownership": "The registered CAE bridge retains deterministic and native numerical execution",
        },
        "owned_references": {
            "objective_service": "objectives/service.py",
            "shared_pinn": "mcp_tools/pinn_tools.py",
            "fem_routes": "app/analysis_fem_routes.py",
        },
        "documentation": "docs/agents/analysis_agent.md",
    }, allow_nan=False),
)

MODULE = ANALYSIS_MODULE
