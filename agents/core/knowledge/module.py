"""Read-only Knowledge presentation contract; never exported for discovery."""

import json
from pathlib import Path

from agents.core.knowledge.agent import KnowledgeAgent
from agents.core.knowledge.presentation import REPORT_PROFILE, project_knowledge_report
from agents.module_contract import AgentModule


CORE_MODULE = AgentModule(
    module_id="knowledge",
    agent_name="knowledge_agent",
    version="1.0.0",
    factory=KnowledgeAgent,
    project_report=project_knowledge_report,
    frontend_root=Path(__file__).parent / "frontend",
    descriptor_json=json.dumps({
        "report_profile": REPORT_PROFILE,
        "capabilities": ["knowledge_context.v1", "knowledge_report.v1", "evolution_proposal.v1"],
        "frontend": {"host": "/live", "descriptor": "graphs/modules/knowledge/ui.yaml", "asset_url": "/module-assets/knowledge/live_report.js", "namespace": "AX4LABKnowledgeUI", "factory": "createFrontend", "report_api": "/api/agents/knowledge/report"},
        "configuration": {"plan_contract": "agents/core/knowledge/plan.py", "source": "graphs/modules/knowledge/module.yaml", "activation_supported": False},
        "documentation": "docs/agents/knowledge_agent.md",
    }, allow_nan=False),
)
