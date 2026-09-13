"""Code-discovered Equipment owner; the installed bridge executes device work."""
import json
from pathlib import Path

from agents.equipment.agent import LabEquipmentAgent
from agents.equipment.presentation import REPORT_PROFILE, project_equipment_report
from agents.module_contract import AgentModule


EQUIPMENT_MODULE = AgentModule(
    module_id="equipment",
    agent_name="equipment_agent",
    version="1.0.0",
    factory=LabEquipmentAgent,
    project_report=project_equipment_report,
    frontend_root=Path(__file__).parent / "frontend",
    descriptor_json=json.dumps({
        "report_profile": REPORT_PROFILE,
        "frontend": {
            "host": "/live",
            "descriptor": "graphs/modules/equipment/ui.yaml",
            "asset_url": "/module-assets/equipment/live_report.js",
            "namespace": "AX4LABEquipmentUI",
            "factory": "createFrontend",
            "report_api": "/api/agents/equipment/report",
        },
        "contract_version": "equipment_report.v1",
        "capabilities": [
            "bounded_equipment_workflow",
            "utm_compression_cycle",
            "equipment_result_handoff",
        ],
        "backend": {
            "entrypoint": "agents/equipment/agent.py",
            "decision": "agents/equipment/decision.py",
            "workflow": "agents/equipment/workflow.py",
            "execution": "agents/equipment/execution.py",
            "presentation": "agents/equipment/presentation.py",
        },
        "configuration": {
            "setup_write_enabled": False,
            "source": "graphs/modules/equipment/module.yaml",
            "profile": "utils.equipment_profiles.EquipmentProfileRegistry",
            "skill_flow": "graphs/modules/equipment/equipment_skill_flows.json",
            "workspace_settings": "memory/equipment_workspace_settings.json",
            "inputs": ["OrchestratorState.current_experiment_spec", "OrchestratorState.run_metadata"],
            "persistence": "existing Equipment profiles, Skills, Flow and run snapshots",
        },
        "storage": {
            "archive_owner": "equipment_agent",
            "archive": "runs/<run_id>/runtime/loops/loop-N/equipment_agent/attempt-N/",
            "runtime": "memory/equipment_runtime/",
            "skills": "memory/equipment_skills/",
            "connection": "memory/windows_pyautogui_connection.json",
            "new_settings_store": False,
            "shared_archive": "utils.agent_artifact_archive",
        },
        "dependencies": {
            "services": ["AgentContext.complete", "utils.equipment_runtime_service.EquipmentRuntimeService"],
            "tools": [
                "equipment.pyautogui.health",
                "equipment.pyautogui.list_programs",
                "equipment.pyautogui.run",
                "equipment.pyautogui.screenshot",
                "equipment.pyautogui.request_log",
                "vision.equipment_cross_check",
                "utm.run_protocol",
            ],
            "bridge_modules": ["windows_pyautogui"],
            "shared_bridge_sources": ["device_bridges/windows_pyautogui/bridge.py"],
            "direct_device_effect": True,
            "device_ownership": "The registered Windows/PyAutoGUI bridge retains all desktop and UTM effects",
        },
        "owned_references": {
            "workflow_agentic_task": "utils/equipment_agentic_task.py",
            "profiles": "utils/equipment_profiles.py",
            "skills": "utils/equipment_skill_runtime.py",
            "flow": "utils/equipment_skill_flow.py",
            "runtime": "utils/equipment_runtime_service.py",
            "csv": "utils/utm_csv.py",
            "workspace_template": "web/templates/equipment_agent_manager.html",
            "workspace_assets": [
                "web/static/equipment_agent_manager.js",
                "web/static/equipment_agent_manager.css",
                "web/static/equipment_agentic_task_model.js",
                "web/static/equipment_skill_flow_model.js",
                "web/static/equipment_skill_workflow_editor.js",
                "web/static/equipment_skill_workflow_model.js",
            ],
        },
        "documentation": "docs/agents/equipment_agent.md",
    }, allow_nan=False),
)

MODULE = EQUIPMENT_MODULE
