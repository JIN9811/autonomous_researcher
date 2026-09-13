"""Source-bound Analysis relationships; these are not additional execution stages."""
from agents.control_structure import implementation_detail as detail


A = "agents/analysis/agent.py"
D = "agents/analysis/decisions.py"
R = "agents/analysis/runtime.py"
I = "agents/analysis/improvement.py"
F = "agents/analysis/fem.py"
C = "agents/analysis/calibration.py"
M = "agents/analysis/mechanisms.py"
X = "agents/analysis/refinement.py"
B = "device_bridges/cae/bridge.py"
K = "device_bridges/cae/calculix.py"


def analysis_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "analysis.task": detail([
            ("input", "Equipment artifact and curve provenance", "knowledge", A, "AnalysisAgent._curve_from_equipment"),
            ("simulation_decision", "LLM optional simulation selection", "high", D, "decide"),
            ("data_decision", "LLM data-processing selection", "high", D, "decide"),
            ("validation_decision", "LLM measured-evidence review", "high", D, "decide"),
            ("quality", "Existing curve and BO admission gates", "guardian", A, "AnalysisAgent._quality_gate"),
            ("metrics", "UTM numerical metrics and objective inputs", "middle", A, "AnalysisAgent._metrics"),
            ("cae", "Optional registered CAE orchestration", "middle", A, "AnalysisAgent._run_cae"),
            ("bridge", "Deterministic CAE and CalculiX orchestration boundary", "middle", B, "CAEBridge"),
            ("solver", "Existing guarded CalculiX implementation", "middle", K, "CalculiXBridge"),
            ("background", "Existing Analysis background resource and queue", "middle", R, "AnalysisRuntimeService"),
            ("mesh_decision", "LLM FEM mesh preparation and assessment", "high", D, "decide"),
            ("fem", "Existing bounded FEM study", "middle", F, "run_fem_study"),
            ("result_decision", "LLM post-solve FEM evidence review", "high", D, "decide"),
            ("calibration", "Existing bounded calibration study", "middle", C, "calibrate"),
            ("calibration_decision", "LLM calibration admission and review", "high", D, "decide"),
            ("mechanisms", "Mechanism evidence assessment", "middle", M, "assess_mechanisms"),
            ("refinement", "Existing numerical refinement", "middle", X, "refine"),
            ("improvement_decision", "LLM improvement candidate and validation review", "high", D, "decide"),
            ("store", "Existing improvement records and worker lifetime", "knowledge", I, "ImprovementStore"),
            ("handoff", "Measured observation and BO handoff", "knowledge", A, "AnalysisAgent._handoff_payloads"),
        ], [
            ("input", "$operation", "evidence", "existing measured or simulation input"),
            ("$operation", "simulation_decision", "call", "actual bounded simulation decision"),
            ("simulation_decision", "data_decision", "call", "actual bounded data-processing decision"),
            ("data_decision", "quality", "validation", "existing evidence gate"),
            ("quality", "validation_decision", "call", "actual bounded measured-evidence review"),
            ("validation_decision", "metrics", "call", "accepted curve computation"),
            ("simulation_decision", "cae", "call", "registered optional computation"),
            ("cae", "bridge", "call", "existing CAE request"),
            ("bridge", "solver", "call", "guarded internal solver component"),
            ("metrics", "background", "call", "queue without awaiting FEM"),
            ("background", "mesh_decision", "call", "actual bounded mesh review"),
            ("mesh_decision", "fem", "call", "existing background worker"),
            ("fem", "result_decision", "call", "actual bounded post-solve review"),
            ("result_decision", "calibration", "call", "registered calibration branch"),
            ("calibration", "calibration_decision", "call", "actual bounded calibration review"),
            ("result_decision", "mechanisms", "evidence", "deformation interpretation"),
            ("background", "refinement", "call", "registered refinement branch"),
            ("refinement", "improvement_decision", "call", "actual bounded improvement review"),
            ("background", "store", "evidence", "persistent job evidence"),
            ("metrics", "handoff", "evidence", "foreground measured result"),
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
