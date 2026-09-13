"""Code-discovered Specimen module; bridges retain their device_bridges ownership."""
import json
from pathlib import Path

from agents.module_contract import AgentModule
from agents.specimen.agent import SpecimenMakingAgent
from agents.specimen.presentation import REPORT_PROFILE, project_specimen_report

SPECIMEN_MODULE = AgentModule(
    module_id="specimen", agent_name="specimen_agent", version="1.0.0",
    factory=SpecimenMakingAgent, project_report=project_specimen_report,
    frontend_root=Path(__file__).parent / "frontend",
    descriptor_json=json.dumps({
        "report_profile": REPORT_PROFILE,
        "contract_version": "specimen_fabricated.v1",
        "capabilities": ["specimen_fabrication", "manufacturing_suitability_review"],
        "backend": {
            "entrypoint": "agents/specimen/agent.py", "decision": "agents/specimen/decision.py",
            "presentation": "agents/specimen/presentation.py",
        },
        "frontend": {
            "host": "/live", "descriptor": "graphs/modules/specimen/ui.yaml",
            "asset_url": "/module-assets/specimen/live_report.js",
            "namespace": "AX4LABSpecimenUI", "factory": "createFrontend",
            "report_api": "/api/agents/specimen/report",
        },
        "configuration": {
            "setup_write_enabled": False, "source": "graphs/modules/specimen/module.yaml",
            "inputs": ["OrchestratorState.current_experiment_spec"],
            "persistence": "existing graph/module configuration and run snapshots",
        },
        "storage": {
            "archive_owner": "specimen_agent",
            "archive": "runs/<run_id>/runtime/loops/loop-N/specimen_agent/attempt-N/",
            "new_settings_store": False, "shared_archive": "utils.agent_artifact_archive",
        },
        "dependencies": {
            "services": ["AgentContext.complete", "knowledge_service"],
            "tools": ["geometry.generate_metamaterial_stl", "geometry.check_mesh_quality",
                      "geometry.check_manufacturability", "artifact.create_specimen_handoff",
                      "experiment.evaluate", "printer.prepare"],
            "bridge_modules": ["printer_fleet"], "bridge_source": "device_bridges/",
            "handoff": "vision_agent", "direct_device_effect": True,
        },
        "documentation": "docs/agents/specimen_agent.md",
    }, allow_nan=False),
)

MODULE = SPECIMEN_MODULE
