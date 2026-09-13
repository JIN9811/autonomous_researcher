"""Source-bound responsibilities inside the composite Knowledge task."""

from agents.control_structure import implementation_detail as detail


A = "agents/core/knowledge/agent.py"
D = "agents/core/knowledge/decision.py"
C = "agents/core/knowledge/context.py"
E = "agents/core/knowledge/execution.py"


def knowledge_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "knowledge.task": detail([
            ("binding", "Existing knowledge_settings and applicability parsing", "guardian", A, "KnowledgeAgent._run_task"),
            ("intake", "Frozen Analysis and Guardian evidence intake", "knowledge", A, "KnowledgeAgent._run_task"),
            ("references", "Scoped Wiki / reference delivery", "knowledge", C, "build_reference_context"),
            ("decision", "LLM scoped retrieval and curation", "high", D, "run_knowledge_decision"),
            ("local_tools", "Inspect, search, read, note and publish tools", "middle", D, "run_knowledge_decision"),
            ("provenance", "Provenance and ontology validation", "guardian", A, "_ingest_local_event"),
            ("storage", "Markdown, JSONL, report and evidence persistence", "knowledge", A, "KnowledgeAgent._run_task"),
            ("handoff", "Knowledge context and evolution proposal", "middle", A, "KnowledgeAgent._run_task"),
        ], [
            ("$operation", "binding", "validation", "read current owner settings"),
            ("binding", "intake", "evidence", "scope observed inputs"),
            ("references", "decision", "evidence", "reference only"),
            ("intake", "decision", "evidence", "current evidence"),
            ("decision", "local_tools", "call", "bounded tool choice"),
            ("local_tools", "decision", "evidence", "observation / next choice"),
            ("decision", "provenance", "validation", "accepted evidence"),
            ("provenance", "storage", "evidence", "validated records"),
            ("storage", "handoff", "call", "build result"),
        ]),
        "knowledge.deliver": detail([
            ("result", "Fresh composite AgentResult", "middle", E, "knowledge_execution_catalog"),
        ], [("$operation", "result", "call", "deliver same result")]),
    }}
