<!-- atr-doc
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
evidence_date: 2026-09-28
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
-->

# Evaluation and Results

<a id="summary"></a>

Fifteen completed Analysis observations retain matching geometry, curves,
metrics and BO records in the audited campaign. That is the principal result:
a recorded multi-cycle evidence chain, checked without rerunning hardware.
The archive also contains failed and cancelled attempts and recovery
interventions. Completion therefore does not establish unattended reliability,
independent fabrication identity, scientific improvement or live safety
effectiveness.

The two earlier supervised one-cycle demonstrations establish narrower
integration results. Read them beside the campaign audit, not as three points
on a common scientific-improvement curve.

## What the three experiment records establish

| Record | Observation | Qualification needed to interpret it |
|---|---|---|
| [First September 7 cycle](evidence/2026-09-07-supervised-closed-loop.md) | Live UTM clearance, Analysis and next-design handoff; BO chose LHS point 2/8 | Deposition skipped; operator-reported specimen substitution; `1.275e-06 MJ/m³` is not a publishable material value for that design |
| [Later September 7 cycle](evidence/2026-09-07-latest-cycle-demonstration.md) | 2,113 measured samples; `1.941513759 MJ/m³`; next Design/Specimen entry | Deposition still skipped; earlier substitution/near-zero value not attributed here; LHS continuation is not acquisition-ranked improvement |
| [September 28 campaign audit](evidence/2026-09-28-campaign-archive-audit.md) | 15/15 identities, STL hashes and recorded SEA normalizations matched; terminal BO report | Read-only inspection of an intervention-containing archive; SEA is **J/g**, with slicer mass; no independent fabrication certification |

The [setup chapter](05_experimental_setup.md#setup-of-the-retained-campaign)
explains the campaign geometry, objective and mass denominator. The dated
records remain authoritative for their individual conditions and warnings.

## Principal Results

| Result ID | Result | Unit and denominator | Environment | Status | Evidence |
|---|---|---|---|---|---|
| R-ARCHIVE-15 | Fifteen completed observations with generated STL, canonical SS curves and metrics; final BO report | 15/15 identity/hash/formula checks in one campaign | Archive inspection | `supported` within archive scope | `E-INSPECT-CAMPAIGN-001` |
| R-LOOP-01 | UTM clearance → Analysis → BO-managed LHS → next Design/Specimen entry | One observed feedback iteration, no repeated-run reliability estimate | Supervised mixed-mode / live equipment | `supported` within integration scope | `E-LIVE-LOOP-001` |
| R-LOOP-02 | One-cycle demonstration completed with 2,113 measured CSV samples; BO objective 1.941513759 MJ/m³; next Design/Specimen reached | One selected cycle; no repeated-run reliability estimate | Supervised mixed-mode / live equipment | `supported` within integration scope | `E-LIVE-LOOP-002` |
| R-ARCH-01 | 19 configured graph nodes, 68 declared graph edges, and 12 stage-dispatch entries | Configuration entries at one commit | Inspection | `supported` | `E-INSPECT-ARCH-001` |
| R-API-01 | 346 FastAPI `APIRoute` entries and 353 total application routes | Route entries at one import baseline | Inspection | `supported` | `E-INSPECT-ARCH-001` |
| R-DOC-01 | 23 focused documentation tests passed in the initial validator cycle | 23 selected tests, 0 failures | Test | `supported` for the tested contracts | `E-TEST-DOC-001` |
| R-LIVE-01 | Independently certified end-to-end fabrication of every campaign specimen | No independent fabrication-audit denominator | Live | `not_evaluated` | Archive completion alone is insufficient |
| R-SCI-01 | Scientific improvement over a baseline | No study denominator | Comparative | `not_evaluated` | No qualifying evidence |
| R-SAFE-01 | Reduction in unsafe or unintended physical actions | No scenario denominator | Simulation/live | `not_evaluated` | No qualifying evidence |

R-ARCH-01 and R-API-01 are historical architecture counts, not throughput,
quality or stability measures. R-DOC-01 validates documentation tooling, not
system behavior or scientific validity. The invocation archive contains
485 attempts: 471 completed, 13 failed and one cancelled. Those are invocation
outcomes, not a physical-task success rate or fifteen independent campaigns.

## Evaluation Matrix

| Dimension | RQ | Required environment | Current status | Current evidence | Interpretation |
|---|---|---|---|---|---|
| Declared closed-loop architecture | RQ1 | Inspection | `supported` | `E-INSPECT-ARCH-001` | The configured graph and route surface exist at the recorded baseline. |
| Stage-contract integrity through a complete run | RQ1 | Archive inspection plus bounded live records | `partially_supported` | `E-LIVE-LOOP-001`, `E-INSPECT-CAMPAIGN-001` | Fifteen completed observations and a terminal BO final report are retained; this audit does not certify every physical action or an exhaustive failure matrix. |
| Later September 7 one-cycle integration demonstration | RQ1, RQ2 | Live / mixed mode | `supported` within one-cycle scope | `E-LIVE-LOOP-002` | Live compression CSV, placement and clearance verification, Analysis, BO-managed LHS, and next-design entry completed; no full-manufacturing claim. |
| Checkpoint and resume behavior by failure class | RQ1 | Replay/simulation/live | `not_evaluated` | No qualifying record | Recovery effectiveness remains open. |
| Claim-evidence schema integrity | RQ2 | Test | `partially_supported` | `E-TEST-DOC-001` | Structural references and hashes are checked; complete scientific lineage is not. |
| Full run artifact lineage | RQ2 | Archive inspection | `partially_supported` | `E-INSPECT-CAMPAIGN-001` | 15/15 Design-result/Specimen/Analysis identities and STL hashes match; raw data remain local. This does not independently establish physical specimen identity. |
| Guardian/operator decision behavior | RQ3 | Test/replay/simulation | `not_evaluated` | No qualifying paper record | Implemented control points are described, not behaviorally scored here. |
| Live consequential-action containment | RQ3 | Live | `not_evaluated` | No qualifying record | No live safety-effectiveness claim is made. |
| Knowledge/BO feedback benefit | RQ1, RQ2 | Controlled comparative study | `not_evaluated` | No qualifying record | The feedback path exists; scientific benefit is unknown. |
| Contract-preserving extension surface | RQ4 | Inspection | `supported` | `E-INSPECT-ARCH-001` | Modules, backends, bridges, graphs, and workspaces are present as bounded surfaces. |
| Extension behavior across representative adapters | RQ4 | Test/browser/live as applicable | `not_evaluated` | No paper-scoped matrix | General compatibility is not claimed. |
| Browser operator workflows | RQ3, RQ4 | Browser | `not_evaluated` | No paper-scoped browser record | Existing historical audits are not reclassified automatically. |
| End-to-end scientific outcome | RQ1–RQ3 | Simulation/live plus domain protocol | `not_evaluated` | No qualifying record | No accuracy, yield, discovery, or optimization outcome is reported. |

## RQ1 Assessment

`C-SYS-LOOP-01` adds one observed execution of the feedback boundary. The BO
agent selected initial-design point 2/8, not an acquisition-ranked optimum.
The next Design retained the requested parameters. See the evidence report
for timestamps, printer skips, specimen substitution, and the archive index.

The later September 7 record `E-LIVE-LOOP-002` separately documents one completed
feedback cycle using a nonzero measured compression curve. All eight Equipment
Skill blocks completed, both required placement/clearance verification
boundaries were satisfied, Analysis accepted the data, and BO's next LHS point
reached Design. The earlier record's specimen substitution and near-zero score
are not carried over to this run. Optional observer errors and reasoning
warnings remain explicitly recorded; completion does not mean an error-free log.

The declared graph supports `C-SYS-ARCH-01` within inspection scope. The graph
connects the research stages and contains explicit terminal and feedback paths.
The fifteen-iteration archive extends the earlier one-cycle result. It contains
485 invocations (471 completed, 13 failed and one cancelled), including recovery
history. These invocation outcomes are not a physical-task success-rate estimate.
An exhaustive failure-class recovery benchmark remains separate work.

## RQ2 Assessment

The campaign audit checks the Design result's specimen identity against
Specimen and Analysis, rather than relying on a Design manifest that may
describe the incoming previous specimen. It matches preserved STL and
curve/metric hashes, and checks the recorded SEA normalization. Iteration 15
ends with BO's `final_report`, decision `completed`, and no next candidate.
These are useful lineage findings; neither the hashes nor the formula check
independently identifies the physical material. Retained curve-quality and
boundary-peak warnings remain part of interpretation.

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

The results package now includes a fifteen-observation archive audit in addition
to the earlier live-equipment integration records. It does not supply a complete
raw public dataset, independently validated material identity or per-cycle
manufacturing audit, comparative baseline, exhaustive recovery matrix, or
statistical superiority evidence.
These gaps are release and study-planning inputs, not zero-valued results.

## Verification

<a id="scope"></a>

Results are limited to evidence listed in `artifact_manifest.yaml`. Historical
test notes and runtime snapshots provide context but are not silently promoted
into this paper's evaluated result set.

<a id="evidence-basis"></a>

- `E-INSPECT-ARCH-001`: inspected FastAPI and graph structure.
- `E-INSPECT-CAMPAIGN-001`: [fifteen-iteration archive audit](evidence/2026-09-28-campaign-archive-audit.md), including hashes, owner identity, curves, SEA normalization and retained failed attempts.
- `E-LIVE-LOOP-001`: [one supervised mixed-mode iteration](evidence/2026-09-07-supervised-closed-loop.md), with raw archives retained locally and a public result/hash index.
- `E-LIVE-LOOP-002`: [later September 7 one-cycle demonstration](evidence/2026-09-07-latest-cycle-demonstration.md), with measured-data quality, Analysis-to-BO feedback, and next-design continuity.
- `E-TEST-DOC-001`: automated documentation-governance and publication
  contract tests.

Each record names its environment, commit, command, inputs, outputs, and hash.

Initial synthesis: 2026-08-09; live records added on 2026-09-07; retained campaign
audited on 2026-09-28. Older architecture/test records keep their original
baselines; current counts are in the Current Code Snapshot. Run
`scripts/validate_paper_publication.py` to verify the machine-readable status
and evidence hashes.

## Related Documents

- [Experimental setup](05_experimental_setup.md)
- [Reproducibility](07_reproducibility.md)
- [Claim-evidence traceability](09_claim_evidence_traceability.md)
