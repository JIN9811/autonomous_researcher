---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, developer, reviewer, operator]
scope: [agents, analysis, utm, cae]
summary: Current contract for fingerprinting and parsing equipment artifacts, deriving UTM metrics, optional CAE comparison, and BO handoff.
source_of_truth:
  - agents/analysis_agent.py
  - graphs/modules/analysis/module.yaml
  - device_bridges/cae_bridge.py
  - experiments/schemas.py
  - app/main.py
last_verified: 2026-08-09
verified_against: 0b7627b
related_docs:
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/agents/equipment_agent.md
  - docs/agents/knowledge_agent.md
  - docs/agents/bo_agent.md
  - docs/agents/analysis_utm_runtime_guideline.txt
  - docs/agents/cae_analysis_runtime_guideline.txt
supersedes: []
---

# Analysis Agent Reference

## Summary

`AnalysisAgent` converts an identifiable equipment artifact into a canonical
curve, quality record, UTM metrics, optional CAE/FEM comparison, objective and
uncertainty, versioned analysis artifacts, experiment evaluation, and BO
handoff. It preserves the distinction between measured input and derived or
simulated output.

## Scope

Included are file fingerprinting, format/parser and unit resolution, curve
processing, UTM metrics, optional CalculiX/CAE, prior comparison, and evidence.
It does not fabricate missing measurements or operate equipment.

## Source of Truth

Analysis agent/module, CAE bridge, experiment schemas, Analysis/BO merge paths,
and CAE APIs.

## Actual Role

| Does | Does not |
|---|---|
| Hash and parse an equipment artifact | Assume an unidentifiable file is valid measurement |
| Resolve columns/units and build canonical curve | Silently guess units needed for the result |
| Compute bounded UTM metrics/objective/uncertainty | Replace raw evidence with derived values |
| Optionally run validated CAE/CalculiX | Describe simulation as physical measurement |
| Emit evaluation and BO handoff | Select the next physical experiment itself |

## Closed-Loop Position and Handoffs

| Direction | Component | Contract/state | Purpose | Gate |
|---|---|---|---|---|
| In | Equipment | measurement file/handoff/proof | raw analysis input | identity/completion |
| In | CAE service | config/runtime capability | optional simulation | probe/validated payload |
| In | Prior trials | previous metrics | comparison | compatible schema/units |
| Out | Knowledge | analysis artifacts/provenance | durable record | input/output refs |
| Out | BO | objective/uncertainty/constraints | candidate scoring | evaluation validity |

## Inputs and Outputs

Input state includes equipment handoff/result, raw file path and hash context,
format hints, units, experiment specification, previous experiments, and CAE
configuration. Outputs include canonical curve, quality report, UTM metrics,
CAE/FEM problem/results/comparison, objective score, uncertainty, decisions,
analysis artifacts, experiment evaluation, and BO handoff.

## Internal Execution

| IDs | Work | Boundary/output |
|---|---|---|
| `01_receive_equipment_artifact`, `02_fingerprint_input_file` | receive/hash | missing/mismatch blocks |
| `03_detect_format_and_parser`, `04_parse_raw_table`, `05_resolve_columns_and_units` | parse/normalize | unsupported format/unit blocks |
| `06_build_canonical_curve`, `07_preprocess_curve`, `08_validate_curve_quality` | curve pipeline | quality pass/failure |
| `09_compute_utm_metrics` | measured metrics | typed metrics |
| `10_prepare_fem_problem`, `11_prepare_cae_calculix_payload`, `12_probe_cae_runtime` | optional CAE preparation | unavailable remains explicit |
| `13_run_cae_calculix_analysis`, `14_compare_iteration_with_utm`, `15_accept_or_refine_fem` | iterative CAE path | compare/refine result |
| `16_run_cae_if_available`, `17_compare_fem_with_utm` | compatibility optional path | no silent physical equivalence |
| `18_compute_objective_and_uncertainty`, `19_compare_with_previous_experiments` | evaluation | score/uncertainty/comparison |
| `20_write_analysis_artifacts`, `21_emit_experiment_evaluation`, `22_emit_bo_handoff` | persist/handoff | artifacts/evaluation/BO context |

All 22 manifest IDs are represented above.

## API Surface

| Class | Method | Path | Service | Effect | Notes |
|---|---|---|---|---|---|
| connected | GET | `/api/cae/config` | CAE bridge | read_only | selected runtime/config |
| operator | POST | `/api/cae/config` | CAE bridge | local_state | saves validated config |
| connected | POST | `/api/cae/run` | CAE bridge | external_service/local_state | bounded analysis payload |
| shared | GET | `/api/runs/{run_id}/artifacts` | run artifact service | read_only | raw/derived retrieval |

The graph-stage agent runs through the graph handler, not a dedicated
`/api/analysis/run` endpoint.

## Tools and Connections

| Tool/service | Boundary | Effect | Evidence |
|---|---|---|---|
| `cae.run_static_analysis` | registered CAE bridge | external_service/local process | payload/log/result/artifacts |
| Parser/curve/metric logic | in-process Python | local_state | input hash, parser, units, curve, metrics |
| CalculiX/CAE runtime | optional process/service | external_service | probe and solver outputs |
| task-specific `analysis_reasoning` | selected model route; module role empty | model | reasoning metadata |

An empty module `llm_role` keeps Python task routes distinct rather than
granting one broad Analysis role.

## State, Events, Artifacts, and Storage

Raw measurement, fingerprint, parser/unit mapping, canonical/preprocessed
curve, quality report, metrics, CAE payload/log/result, comparison, objective,
uncertainty, and handoff are separate records. Derived artifacts reference raw
input and configuration; they do not overwrite it.

## Modes and Fallbacks

Test can use fixtures; replay uses recorded raw artifacts; simulation/CAE is
labeled separately; Live analysis can consume physical measurement but remains
software-only. Unavailable CAE yields explicit no-CAE/degraded state where the
contract permits it, not a fabricated solver result.

## Safety, Approval, and Effect Boundary

Analysis has no direct physical effect. Input identity, units, curve quality,
validated CAE payload, and artifact paths are the main gates. CAE process
execution is bounded by the registered tool. Results cannot authorize equipment
actions without BO/Design/Guardian/downstream gates.

## Errors and Recovery

Missing/corrupt input, hash mismatch, unsupported format, ambiguous units, or
invalid curve blocks evaluation. Preserve raw and partial outputs; correct the
mapping/input and rerun deterministically. CAE failure may be reported as
unavailable/failed; do not substitute a synthetic physical value.

## Operator and GUI Surfaces

CAE workspace configures and invokes bounded CAE runs. Live GUI Analysis report
shows curves, UTM metrics, objective/uncertainty, FEM/CAE cards, comparisons,
and artifacts. Report rendering is not numerical authority.

## Current Verification

Verified against all 22 internal IDs, `cae.run_static_analysis`, three CAE API
routes, schemas and handoff roles at baseline `0b7627b`. No new measurement or
solver benchmark was executed.

## Limitations and Known Gaps

No paper-scoped evidence establishes parser coverage, unit inference accuracy,
metric uncertainty calibration, CAE fidelity, or scientific validity. Optional
solver availability varies.

## Related Documents

- [Agent Matrix](agent_api_connection_matrix.md)
- [Equipment](equipment_agent.md)
- [Knowledge](knowledge_agent.md)
- [BO](bo_agent.md)
- [Legacy UTM Analysis Guideline](analysis_utm_runtime_guideline.txt)
- [Legacy CAE Guideline](cae_analysis_runtime_guideline.txt)
