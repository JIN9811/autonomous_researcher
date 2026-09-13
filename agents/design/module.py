"""Code-registered Design module; existing files remain its public contracts."""
import json
from pathlib import Path

from agents.design.agent import DesignAgent
from agents.design.presentation import REPORT_PROFILE, project_design_report
from agents.module_contract import AgentModule


DESIGN_MODULE = AgentModule(
    module_id="design",
    agent_name="design_agent",
    version="1.0.0",
    factory=DesignAgent,
    project_report=project_design_report,
    frontend_root=Path(__file__).parent / "frontend",
    descriptor_json=json.dumps({
        "report_profile": REPORT_PROFILE,
        "contract_version": "design_candidate.v1",
        "capabilities": ["design_candidate", "candidate_suitability_review"],
        "backend": {
            "entrypoint": "agents/design/agent.py",
            "decision": "agents/design/decision.py",
            "presentation": "agents/design/presentation.py",
        },
        "frontend": {
            "host": "/live",
            "descriptor": "graphs/modules/design/ui.yaml",
            "asset_url": "/module-assets/design/live_report.js",
            "namespace": "AX4LABDesignUI",
            "factory": "createFrontend",
            "report_api": "/api/agents/design/report",
        },
        "configuration": {
            "setup_write_enabled": False,
            "source": "graphs/modules/design/module.yaml",
            "defaults": ["DesignAgent.DEFAULT_CONSTRAINTS", "DesignAgent.DEFAULT_DESIGN_SPACE"],
            "inputs": ["OrchestratorState.current_experiment_spec", "run_metadata.orchestrator_design_contract"],
            "persistence": "existing graph/module configuration and run snapshots",
        },
        "storage": {
            "archive_owner": "design_agent",
            "archive": "runs/<run_id>/runtime/loops/loop-N/design_agent/attempt-N/",
            "previews": "runs/<run_id>/design_candidates/",
            "new_settings_store": False,
            "shared_archive": "utils.agent_artifact_archive",
        },
        "dependencies": {
            "services": ["AgentContext.complete", "experiment_db", "failure_memory", "knowledge_service"],
            "optional_tools": ["geometry.generate_metamaterial_stl"],
            "handoff": "specimen_agent",
            "direct_device_effect": False,
        },
        "documentation": "docs/agents/design_agent.md",
    }, allow_nan=False),
)

# Discovery convention; preserve the established compatibility name above.
MODULE = DESIGN_MODULE
