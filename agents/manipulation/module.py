"""Code-discovered Manipulation owner; existing bridges execute device work."""
import json
from pathlib import Path

from agents.module_contract import AgentModule
from agents.manipulation.agent import ManipulationAgent
from agents.manipulation.presentation import REPORT_PROFILE, project_manipulation_report

MANIPULATION_MODULE = AgentModule(
    module_id="manipulation", agent_name="manipulation_agent", version="1.0.0", factory=ManipulationAgent,
    project_report=project_manipulation_report, frontend_root=Path(__file__).parent / "frontend",
    descriptor_json=json.dumps({
        "report_profile": REPORT_PROFILE,
        "frontend": {"host": "/live", "descriptor": "graphs/modules/manipulation/ui.yaml",
            "asset_url": "/module-assets/manipulation/live_report.js", "namespace": "AX4LABManipulationUI",
            "factory": "createFrontend", "report_api": "/api/agents/manipulation/report"},
        "contract_version": "manipulation_report.v1",
        "capabilities": ["bounded_manipulation", "specimen_transfer", "tested_specimen_disposal"],
        "backend": {"entrypoint": "agents/manipulation/agent.py", "decision": "agents/manipulation/decision.py",
            "presentation": "agents/manipulation/presentation.py",
            "compatibility_imports": ["agents.manipulation_agent", "agents.manipulation_decision"]},
        "configuration": {"setup_write_enabled": False, "source": "graphs/modules/manipulation/module.yaml",
            "inputs": ["OrchestratorState.current_experiment_spec"],
            "profile": "utils.manipulation_profile.load_manipulation_agent_profile",
            "persistence": "existing manipulation profile and run snapshots"},
        "storage": {"archive_owner": "manipulation_agent",
            "archive": "runs/<run_id>/runtime/loops/loop-N/manipulation_agent/attempt-N/",
            "new_settings_store": False, "shared_archive": "utils.agent_artifact_archive"},
        "dependencies": {"services": ["AgentContext.complete"],
            "tools": ["lerobot.rollout.start", "lerobot.rollout.status", "lerobot.rollout.stop",
                "lerobot.replay.start", "lerobot.replay.status", "lerobot.replay.stop", "robot.pick_place"],
            "bridge_modules": ["lerobot"],
            "shared_bridge_sources": ["device_bridges/lerobot/bridge.py"],
            "direct_device_effect": True,
            "device_ownership": "Registered LeRobot and robot executors retain existing device execution"},
        "documentation": "docs/agents/manipulation_agent.md",
    }, allow_nan=False),
)

MODULE = MANIPULATION_MODULE
