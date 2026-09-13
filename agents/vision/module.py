"""Code-discovered Vision owner and its existing observation/LeRobot dependencies."""
import json
from pathlib import Path

from agents.module_contract import AgentModule
from agents.vision.agent import VisionAgent
from agents.vision.presentation import REPORT_PROFILE, project_vision_report

VISION_MODULE = AgentModule(
    module_id="vision", agent_name="vision_agent", version="1.0.0", factory=VisionAgent,
    project_report=project_vision_report, frontend_root=Path(__file__).parent / "frontend",
    descriptor_json=json.dumps({
        "report_profile": REPORT_PROFILE,
        "frontend": {"host": "/live", "descriptor": "graphs/modules/vision/ui.yaml",
            "asset_url": "/module-assets/vision/live_report.js", "namespace": "AX4LABVisionUI",
            "factory": "createFrontend", "report_api": "/api/agents/vision/report"},
        "contract_version": "vision_signal.v1",
        "capabilities": ["lab_perception", "placement_verification", "clearance_verification"],
        "backend": {
            "entrypoint": "agents/vision/agent.py", "decision": "agents/vision/decision.py",
            "presentation": "agents/vision/presentation.py",
            "compatibility_imports": ["agents.vision_agent", "agents.vision_decision"],
        },
        "configuration": {"setup_write_enabled": False, "source": "graphs/modules/vision/module.yaml",
            "inputs": ["OrchestratorState.current_experiment_spec"],
            "persistence": "existing graph/module configuration and run snapshots"},
        "storage": {"archive_owner": "vision_agent",
            "archive": "runs/<run_id>/runtime/loops/loop-N/vision_agent/attempt-N/",
            "observations": "runs/<run_id>/vision/<observation_id>/",
            "new_settings_store": False, "shared_archive": "utils.agent_artifact_archive"},
        "dependencies": {
            "services": ["AgentContext.complete"],
            "tools": ["camera.capture", "vision.utm_runtime.start", "vision.utm_specimen_presence.capture",
                "lerobot.replay.status", "lerobot.replay.stop", "lerobot.camera.test",
                "lerobot.active_robot_cam.capture", "lerobot.rollout.status", "lerobot.rollout.stop"],
            "bridge_modules": ["camera_vision", "lerobot"], "bridge_source": "device_bridges/",
            "shared_bridge_sources": ["device_bridges/lerobot/bridge.py"],
            "direct_device_effect": True,
            "device_ownership": "Existing LeRobot bridge owns ActiveCam motion/capture/return and rollout stop",
        },
        "documentation": "docs/agents/vision_agent.md",
    }, allow_nan=False),
)

MODULE = VISION_MODULE
