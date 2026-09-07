---
doc_type: evidence
subtype: benchmark
status: review
authority: evidentiary
audience:
  - researcher
  - reviewer
  - artifact_evaluator
scope:
  - paper
  - evaluation
  - results_status
summary: Reports the current evidence state for each ATR evaluation dimension without promoting unevaluated results.
evidence_date: 2026-09-07
method: Evidence-status synthesis from the artifact manifest and recorded repository checks.
paper_section: evaluation_and_results
research_questions:
  - RQ1
  - RQ2
  - RQ3
  - RQ4
claim_ids:
  - C-SYS-LOOP-01
  - C-SYS-ARCH-01
  - C-TRACE-DOC-01
  - C-SAFE-LIVE-01
  - C-PLAT-EXT-01
related_docs:
  - docs/paper/05_experimental_setup.md
  - docs/paper/07_reproducibility.md
  - docs/paper/09_claim_evidence_traceability.md
supersedes: []
---

# Evaluation and Results

## Summary

The current evidence establishes bounded architecture and documentation
contracts, plus supervised mixed-mode closed-loop integration evidence.
The latest audited run completed one cycle with measured compression data
and entry into the next Design/Specimen stage (`E-LIVE-LOOP-002`).
It does not establish end-to-end scientific efficacy, generalized
safety effectiveness, live-hardware robustness, or superiority to another
system. This chapter reports that boundary as a result rather than hiding it
behind incomplete tables.

## Scope

Results are limited to evidence listed in `artifact_manifest.yaml`. Historical
test notes and runtime snapshots provide context but are not silently promoted
into this paper's evaluated result set.

## Evidence Basis

- `E-INSPECT-ARCH-001`: inspected FastAPI and graph structure.
- `E-LIVE-LOOP-001`: [one supervised mixed-mode iteration](evidence/2026-09-07-supervised-closed-loop.md), with raw archives retained locally and a public result/hash index.
- `E-LIVE-LOOP-002`: [latest one-cycle demonstration](evidence/2026-09-07-latest-cycle-demonstration.md), with measured-data quality, Analysis-to-BO feedback, and next-design continuity.
- `E-TEST-DOC-001`: automated documentation-governance and publication
  contract tests.

Each record names its environment, commit, command, inputs, outputs, and hash.

## Evaluation Matrix

| Dimension | RQ | Required environment | Current status | Current evidence | Interpretation |
|---|---|---|---|---|---|
| Declared closed-loop architecture | RQ1 | Inspection | `supported` | `E-INSPECT-ARCH-001` | The configured graph and route surface exist at the recorded baseline. |
| Stage-contract integrity through a complete run | RQ1 | Test/replay or higher | `partially_supported` | `E-LIVE-LOOP-001` | One supervised mixed-mode feedback iteration reached the next Design; whole-run completion, full fabrication, and failure matrices remain unverified. |
| Latest one-cycle integration demonstration | RQ1, RQ2 | Live / mixed mode | `supported` within one-cycle scope | `E-LIVE-LOOP-002` | Live compression CSV, placement and clearance verification, Analysis, BO-managed LHS, and next-design entry completed; no full-manufacturing claim. |
| Checkpoint and resume behavior by failure class | RQ1 | Replay/simulation/live | `not_evaluated` | No qualifying record | Recovery effectiveness remains open. |
| Claim-evidence schema integrity | RQ2 | Test | `partially_supported` | `E-TEST-DOC-001` | Structural references and hashes are checked; complete scientific lineage is not. |
| Full run artifact lineage | RQ2 | Replay/simulation/live | `partially_supported` | `E-LIVE-LOOP-001` | Loop/attempt results and hashes are indexed; raw data are not publicly bundled and specimen substitution prevents scientific lineage validation. |
| Guardian/operator decision behavior | RQ3 | Test/replay/simulation | `not_evaluated` | No qualifying paper record | Implemented control points are described, not behaviorally scored here. |
| Live consequential-action containment | RQ3 | Live | `not_evaluated` | No qualifying record | No live safety-effectiveness claim is made. |
| Knowledge/BO feedback benefit | RQ1, RQ2 | Controlled comparative study | `not_evaluated` | No qualifying record | The feedback path exists; scientific benefit is unknown. |
| Contract-preserving extension surface | RQ4 | Inspection | `supported` | `E-INSPECT-ARCH-001` | Modules, backends, bridges, graphs, and workspaces are present as bounded surfaces. |
| Extension behavior across representative adapters | RQ4 | Test/browser/live as applicable | `not_evaluated` | No paper-scoped matrix | General compatibility is not claimed. |
| Browser operator workflows | RQ3, RQ4 | Browser | `not_evaluated` | No paper-scoped browser record | Existing historical audits are not reclassified automatically. |
| End-to-end scientific outcome | RQ1–RQ3 | Simulation/live plus domain protocol | `not_evaluated` | No qualifying record | No accuracy, yield, discovery, or optimization outcome is reported. |

## Principal Results

| Result ID | Result | Unit and denominator | Environment | Status | Evidence |
|---|---|---|---|---|---|
| R-ARCH-01 | 19 configured graph nodes, 68 declared graph edges, and 12 stage-dispatch entries | Configuration entries at one commit | Inspection | `supported` | `E-INSPECT-ARCH-001` |
| R-API-01 | 346 FastAPI `APIRoute` entries and 353 total application routes | Route entries at one import baseline | Inspection | `supported` | `E-INSPECT-ARCH-001` |
| R-DOC-01 | 23 focused documentation tests passed in the initial validator cycle | 23 selected tests, 0 failures | Test | `supported` for the tested contracts | `E-TEST-DOC-001` |
| R-LOOP-01 | UTM clearance → Analysis → BO-managed LHS → next Design/Specimen entry | One observed feedback iteration, no repeated-run reliability estimate | Supervised mixed-mode / live equipment | `supported` within integration scope | `E-LIVE-LOOP-001` |
| R-LOOP-02 | One-cycle demonstration completed with 2,113 measured CSV samples; BO objective 1.941513759 MJ/m³; next Design/Specimen reached | One selected cycle; no repeated-run reliability estimate | Supervised mixed-mode / live equipment | `supported` within integration scope | `E-LIVE-LOOP-002` |
| R-LIVE-01 | End-to-end physical campaign completion | No campaign denominator | Live | `not_evaluated` | No qualifying evidence |
| R-SCI-01 | Scientific improvement over a baseline | No study denominator | Comparative | `not_evaluated` | No qualifying evidence |
| R-SAFE-01 | Reduction in unsafe or unintended physical actions | No scenario denominator | Simulation/live | `not_evaluated` | No qualifying evidence |

The first two rows are architecture counts, not throughput, quality, or
stability metrics. The third row validates documentation tooling, not system
or scientific behavior.

## RQ1 Assessment

`C-SYS-LOOP-01` adds one observed execution of the feedback boundary. The BO
agent selected initial-design point 2/8, not an acquisition-ranked optimum.
The next Design retained the requested parameters. See the evidence report
for timestamps, printer skips, specimen substitution, and the archive index.

The latest record `E-LIVE-LOOP-002` independently documents one completed
feedback cycle using a nonzero measured compression curve. All eight Equipment
Skill blocks completed, both required placement/clearance verification
boundaries were satisfied, Analysis accepted the data, and BO's next LHS point
reached Design. The earlier record's specimen substitution and near-zero score
are not carried over to this run. Optional observer errors and reasoning
warnings remain explicitly recorded; completion does not mean an error-free log.

The declared graph supports `C-SYS-ARCH-01` within inspection scope. The graph
connects the research stages and contains explicit terminal and feedback paths.
RQ1 is not fully answered until representative cycles execute with typed
handoffs, checkpoints, failure routes, and resume behavior recorded.

## RQ2 Assessment

The artifact schema and validator support `C-TRACE-DOC-01` only partially.
They prevent supported claims from referencing missing evidence and validate
output hashes. This proves the documentation package can enforce its declared
links; it does not prove that every runtime decision and scientific artifact is
captured correctly.

## RQ3 Assessment

The architecture contains Guardian, approval, dry-run, stop, and error
boundaries, but the live-safety claim `C-SAFE-LIVE-01` is `not_evaluated`.
Behavioral scenarios must measure expected decisions, bridge reachability,
ambiguous timeouts, and operator-visible stop state.

## RQ4 Assessment

Inspection supports the existence of contract-oriented extension surfaces in
`C-PLAT-EXT-01`. A representative extension matrix is still required to
measure core modification burden, validation coverage, failure containment,
and cross-environment behavior.

## Threats to Validity

- **Construct validity:** route and graph counts measure declared structure,
  not usefulness or correctness.
- **Internal validity:** documentation tests can pass while runtime behavior is
  defective.
- **External validity:** one repository configuration cannot establish
  behavior across laboratories, devices, or scientific domains.
- **Conclusion validity:** no comparative statistical result is present, so no
  superiority or causal conclusion is supported.
- **Reproducibility:** optional dependencies and external devices may prevent
  higher-tier reproduction in a clean environment.

## Limitations and Known Gaps

The results package intentionally exposes substantial unevaluated scope.
The supervised live-equipment integration records do not supply a
complete raw public dataset, validated material identity, full manufacturing
campaign, comparative baseline, recovery matrix, or statistical evidence.
These gaps are release and study-planning inputs, not zero-valued results.

## Verification

Initial synthesis: 2026-08-09. Updated on 2026-09-07 with bounded working-tree
live integration evidence, including the latest completed cycle; the older architecture/test baselines are unchanged. Run
`scripts/validate_paper_publication.py` to verify the machine-readable status
and evidence hashes.

## Related Documents

- [Experimental setup](05_experimental_setup.md)
- [Reproducibility](07_reproducibility.md)
- [Claim-evidence traceability](09_claim_evidence_traceability.md)
