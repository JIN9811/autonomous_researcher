"""Read-only Guardian presentation contract; never exported for discovery."""

import json
from pathlib import Path

from agents.core.guardian.agent import GuardianAgent
from agents.core.guardian.presentation import REPORT_PROFILE, project_guardian_report
from agents.module_contract import AgentModule


CORE_MODULE = AgentModule(
    module_id="guardian",
    agent_name="guardian_agent",
    version="1.0.0",
    factory=GuardianAgent,
    project_report=project_guardian_report,
    frontend_root=Path(__file__).parent / "frontend",
    descriptor_json=json.dumps({
        "report_profile": REPORT_PROFILE,
        "capabilities": ["guardian_decision", "deterministic_policy_gates", "advisory_policy_review"],
        "frontend": {"host": "/live", "descriptor": "graphs/modules/guardian/ui.yaml", "asset_url": "/module-assets/guardian/live_report.js", "namespace": "AX4LABGuardianUI", "factory": "createFrontend", "report_api": "/api/agents/guardian/report"},
        "configuration": {"plan_contract": "agents/core/guardian/plan.py", "source": "graphs/modules/guardian/module.yaml", "activation_supported": False},
        "documentation": "docs/agents/guardian_agent.md",
    }, allow_nan=False),
)
