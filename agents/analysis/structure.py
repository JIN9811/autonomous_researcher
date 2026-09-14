"""Source-bound Analysis relationships; these are not additional execution stages."""
from agents.control_structure import implementation_detail as detail


A = "agents/analysis/agent.py"
D = "agents/analysis/decisions.py"


def analysis_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "analysis.task": detail([
            ("input", "Equipment artifact and curve provenance", "knowledge", A, "AnalysisAgent._curve_from_equipment"),
            ("data_decision", "LLM data-processing selection", "high", D, "decide"),
            ("validation_decision", "LLM measured-evidence review", "high", D, "decide"),
            ("quality", "Existing curve and BO admission gates", "guardian", A, "AnalysisAgent._quality_gate"),
            ("metrics", "UTM numerical metrics and objective inputs", "middle", A, "AnalysisAgent._metrics"),
            ("handoff", "Measured observation and BO handoff", "knowledge", A, "AnalysisAgent._handoff_payloads"),
        ], [
            ("input", "$operation", "evidence", "equipment acquisition"),
            ("$operation", "data_decision", "call", "LLM call"),
            ("data_decision", "metrics", "call", "accepted processing"),
            ("metrics", "quality", "validation", "metric coverage"),
            ("quality", "validation_decision", "call", "actual bounded measured-evidence review"),
            ("validation_decision", "handoff", "evidence", "accepted measured result"),

        ]),
        "analysis.deliver": detail([
            ("report", "Analysis artifacts and evidence report", "knowledge", A, "AnalysisAgent._write_analysis_artifacts"),
            ("projection", "Owner report projection", "knowledge", "agents/analysis/presentation.py", "project_analysis_report"),
            ("archive", "Public run archive wrapper", "knowledge", "utils/agent_artifact_archive.py", "archive_agent_run"),
        ], [
            ("report", "$operation", "evidence", "original owner AgentResult"),
            ("report", "projection", "evidence", "state and payload precedence"),
            ("$operation", "archive", "evidence", "public run archives once"),
        ]),
    }}
