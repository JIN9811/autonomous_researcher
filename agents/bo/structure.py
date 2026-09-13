"""Source-bound BO relationships; these are not additional execution stages."""
from agents.control_structure import implementation_detail as detail


A = "agents/bo/agent.py"
D = "agents/bo/decision.py"
S = "learning/bo_parameter_space.py"
N = "learning/botorch_backend.py"
E = "experiments/benchmark.py"
P = "agents/bo/presentation.py"


def bo_implementation_structure():
    return {"schema": "ax4lab.implementation_structure.v1", "operations": {
        "bo.task": detail([
            ("input", "Analysis handoff and measured priors", "knowledge", A, "BOAgent._analysis_handoff_records"),
            ("objective", "Objective-bound observation filtering", "guardian", A, "BOAgent.objective_observations"),
            ("space", "Existing mixed and continuous parameter-space contract", "middle", S, "BOParameterSpace"),
            ("strategy", "LLM bounded strategy and evidence review", "high", D, "run_bo_decision"),
            ("diagnostics", "Code-owned observation diagnostics", "middle", D, "_diagnostics"),
            ("benchmark", "Existing numerical benchmark tool implementation", "middle", E, "run_benchmark"),
            ("botorch", "Existing BoTorch acquisition implementation", "middle", N, "propose_next"),
            ("candidate", "Exact numerical candidate validation", "guardian", D, "_validate_candidate"),
            ("review", "LLM exact-result acceptance or owner return", "high", D, "run_bo_decision"),
            ("artifacts", "Existing BO evidence artifact writer", "knowledge", A, "BOAgent._write_artifacts"),
            ("handoff", "Existing Design request construction", "knowledge", A, "BOAgent._run_task"),
        ], [
            ("input", "$operation", "evidence", "current or historical measured evidence"),
            ("$operation", "objective", "validation", "objective identity and evidence gate"),
            ("objective", "space", "call", "unchanged configured domain"),
            ("space", "strategy", "call", "bounded BO-local decision"),
            ("strategy", "diagnostics", "call", "inspect observations before optimization"),
            ("diagnostics", "benchmark", "call", "existing experiment.benchmark service"),
            ("benchmark", "botorch", "call", "existing numerical backend"),
            ("botorch", "candidate", "validation", "preserve exact solver coordinates"),
            ("candidate", "review", "call", "accept or return without coordinate edits"),
            ("review", "artifacts", "evidence", "accepted or blocked decision record"),
            ("artifacts", "handoff", "evidence", "ready or blocked Design request"),
        ]),
        "bo.deliver": detail([
            ("report", "BO result and Design handoff payload", "knowledge", A, "BOAgent._run_task"),
            ("projection", "Owner report projection", "knowledge", P, "project_bo_report"),
            ("archive", "Public run archive wrapper", "knowledge", "utils/agent_artifact_archive.py", "archive_agent_run"),
        ], [
            ("report", "$operation", "evidence", "original owner AgentResult"),
            ("report", "projection", "evidence", "metadata and payload precedence"),
            ("$operation", "archive", "evidence", "public entrypoint archives once"),
        ]),
    }}
