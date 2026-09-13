"""Source-bound Specimen CODE relationships; these are not executable nodes."""
from agents.control_structure import implementation_detail as detail

A = "agents/specimen/agent.py"
D = "agents/specimen/decision.py"


def specimen_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "specimen.prepare": detail([
            ("intake", "Required experiment fields", "guardian", A, "SpecimenMakingAgent._required_missing"),
            ("intent", "Printer path and execution intent", "middle", A, "SpecimenMakingAgent._printer_test_path"),
            ("hard_rules", "FDM geometry hard rules", "guardian", A, "SpecimenMakingAgent._enforce_fdm_gyroid_hard_rules"),
            ("geometry", "Geometry, mesh, manufacturing and handoff tools", "middle", A, "SpecimenMakingAgent._prepare_fabrication"),
        ], [("$operation", "intake", "validation", "required fields"),
            ("$operation", "intent", "call", "resolve intent"),
            ("$operation", "hard_rules", "validation", "geometry constraints"),
            ("$operation", "geometry", "call", "prepare checked artifacts")]),
        "specimen.decide": detail([
            ("reason", "LLM suitability and tool decision", "high", D, "decide_specimen"),
            ("evidence", "Credential-free fabrication evidence", "knowledge", D, "fabrication_evidence"),
            ("choice", "Schema and evidence validated tool choice", "guardian", D, "decide_specimen"),
            ("inspect", "Inspect evidence and return observations", "middle", D, "decide_specimen"),
            ("execute", "experiment.evaluate / printer.prepare callback", "middle", A, "SpecimenMakingAgent._decide_fabrication"),
            ("device", "Printer device boundary / selected provider", "low", "device_bridges/printer_fleet/bridge.py", "PrinterDeviceBridgeManager"),
            ("references", "Reference-only knowledge context", "knowledge", "agents/knowledge_context.py", "build_reference_context"),
        ], [("evidence", "$operation", "evidence", "manufacturing facts"),
            ("references", "$operation", "evidence", "reference only"),
            ("$operation", "reason", "call", "existing bounded model loop"),
            ("reason", "choice", "validation", "bounded choice"),
            ("choice", "inspect", "call", "inspect"),
            ("inspect", "reason", "evidence", "observation / next choice"),
            ("choice", "execute", "call", "execute once"),
            ("execute", "device", "call", "existing printer path when selected")]),
        "specimen.finalize": detail([
            ("report", "Manufacturing digital thread and quality gates", "knowledge", A, "SpecimenMakingAgent._build_fabrication_report"),
            ("handoff", "Vision / manipulation fabricated packet", "middle", A, "SpecimenMakingAgent._build_specimen_fabricated_packet"),
            ("screen", "Specimen report snapshot", "knowledge", A, "SpecimenMakingAgent._specimen_agent_report_snapshot"),
        ], [("$operation", "report", "evidence", "callback response"),
            ("report", "handoff", "call", "handoff evidence"),
            ("$operation", "screen", "call", "report projection")]),
        "specimen.review": detail([
            ("review", "Blocked decision result", "guardian", A, "SpecimenMakingAgent._review_fabrication"),
        ], [("$operation", "review", "call", "return to owner")]),
        "specimen.operator_input": detail([
            ("request", "Printer-path operator request", "middle", A, "SpecimenMakingAgent._printer_path_choice_result"),
        ], [("request", "$operation", "evidence", "prepared operator request")]),
    }}
