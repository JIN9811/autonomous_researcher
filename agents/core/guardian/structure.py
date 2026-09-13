"""Source-bound responsibilities inside the composite Guardian task."""

from agents.control_structure import implementation_detail as detail


A = "agents/core/guardian/agent.py"
D = "agents/core/guardian/decision.py"
E = "agents/core/guardian/execution.py"


def guardian_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "guardian.task": detail([
            ("inputs", "Current mandatory policy inputs", "guardian", A, "GuardianAgent._run_task"),
            ("health", "Device health API and blocking alerts", "middle", A, "GuardianAgent._resolve_device_health"),
            ("failures", "Recent failure memory evidence", "knowledge", A, "GuardianAgent._failure_pattern_match"),
            ("advisory", "LLM policy evidence review", "high", D, "run_guardian_advisory"),
            ("design_gate", "Design and failure-pattern validation", "guardian", A, "GuardianAgent._validate_design_spec"),
            ("graph_gate", "Graph-wide gate and incident precedence", "guardian", A, "GuardianAgent._resolve_graph_gate_pressure"),
            ("consistency", "Analysis, observation and retry consistency", "guardian", A, "GuardianAgent._consistency_check"),
            ("result", "Continue, recover, retry or safe-stop result", "middle", A, "GuardianAgent._run_task"),
        ], [
            ("$operation", "inputs", "evidence", "read mandatory inputs"),
            ("inputs", "health", "call", "device.health"),
            ("inputs", "failures", "evidence", "read failure memory"),
            ("failures", "design_gate", "evidence", "validate design history"),
            ("inputs", "graph_gate", "evidence", "read graph gates"),
            ("inputs", "consistency", "evidence", "read analysis and retries"),
            ("health", "advisory", "evidence", "health evidence"),
            ("design_gate", "advisory", "evidence", "validated design evidence"),
            ("graph_gate", "advisory", "evidence", "gate evidence"),
            ("consistency", "advisory", "evidence", "consistency evidence"),
            ("design_gate", "result", "validation", "mandatory precedence"),
            ("health", "result", "validation", "mandatory precedence"),
            ("graph_gate", "result", "validation", "mandatory precedence"),
            ("consistency", "result", "validation", "select action"),
            ("advisory", "result", "evidence", "advisory note only"),
        ]),
        "guardian.deliver": detail([
            ("result", "Fresh composite AgentResult", "middle", E, "guardian_execution_catalog"),
        ], [("$operation", "result", "call", "deliver same result")]),
    }}
