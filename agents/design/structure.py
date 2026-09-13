"""Internal relationships of existing Design functions and bounded local tools.

Inline decision checks reference decide_design itself, not invented handlers.
These references document code ownership; editing routes still uses the owner
execution catalog. Every reference is checked against source in regression tests.
"""
from agents.control_structure import implementation_detail as detail

A = "agents/design/agent.py"
D = "agents/design/decision.py"
K = "agents/knowledge_context.py"


def design_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "design.prepare": detail([
            ("contract", "Objective and locked inputs", "middle", A, "DesignAgent._objective_contract"),
            ("history", "BO, prior results and failure memory", "knowledge", A, "DesignAgent._prepare_design_payload"),
            ("generate", "Generate candidate pool", "low", A, "DesignAgent._candidate_pool"),
            ("constraints", "Constraint gate and rejected ledger", "guardian", A, "DesignAgent._filter_candidates"),
            ("repair", "Conditional candidate repair", "low", A, "DesignAgent._safe_seed_candidate"),
        ], [
            ("$operation", "contract", "call", "normalize"),
            ("$operation", "history", "evidence", "collect context"),
            ("$operation", "generate", "call", "generate"),
            ("generate", "constraints", "validation", "candidate checks"),
            ("constraints", "repair", "validation", "if no valid / preferred candidate"),
            ("history", "$operation", "evidence", "prepared evidence"),
        ]),
        "design.decide": detail([
            ("references", "Scoped Wiki / reference context", "knowledge", K, "build_reference_context"),
            ("choice_gate", "Tool, arguments and evidence gate", "guardian", D, "decide_design"),
            ("inspect", "inspect_candidate / inspect_history", "low", D, "decide_design"),
            ("accept", "Checked candidate acceptance", "guardian", D, "candidate_evaluation"),
            ("trace", "Decision and tool evidence trace", "knowledge", D, "decide_design"),
        ], [
            ("references", "$operation", "evidence", "reference only"),
            ("$operation", "choice_gate", "validation", "LLM choice"),
            ("choice_gate", "inspect", "call", "inspect"),
            ("inspect", "$operation", "evidence", "observation / next decision"),
            ("choice_gate", "accept", "validation", "accept candidate"),
            ("$operation", "trace", "evidence", "record"),
        ]),
        "design.finalize": detail([
            ("report", "Evaluation and design report", "knowledge", A, "DesignAgent._design_report"),
            ("handoff", "Checked Specimen handoff packet", "high", A, "DesignAgent._design_handoff_packet"),
        ], [
            ("$operation", "report", "evidence", "build report"),
            ("report", "handoff", "call", "handoff evidence"),
            ("$operation", "handoff", "call", "build packet"),
        ]),
    }}
