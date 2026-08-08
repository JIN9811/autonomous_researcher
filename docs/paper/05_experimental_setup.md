---
doc_type: reference
subtype: system
status: review
authority: descriptive
audience:
  - researcher
  - reviewer
  - artifact_evaluator
scope:
  - paper
  - experimental_setup
  - evaluation_protocol
summary: Defines the environments, units of evaluation, controls, and evidence collection required for ATR experiments.
source_of_truth:
  - REQUIREMENTS.md
  - configs
  - graphs/configs/atr_closed_loop.yaml
  - tests
last_verified: 2026-08-09
verified_against: 0b7627b
paper_section: experimental_setup
research_questions:
  - RQ1
  - RQ2
  - RQ3
  - RQ4
claim_ids:
  - C-SYS-ARCH-01
  - C-TRACE-DOC-01
  - C-SAFE-LIVE-01
  - C-PLAT-EXT-01
related_docs:
  - docs/paper/03_closed_loop_method.md
  - docs/paper/06_evaluation_and_results.md
  - docs/paper/07_reproducibility.md
supersedes: []
---

# Experimental Setup

## Summary

ATR evaluation is organized by evidence environment rather than by a single
binary “works” label. Static inspection, automated tests, replay, simulation,
browser observation, and live-hardware execution answer different questions.
This chapter defines the shared setup and the information every result must
record.

## Scope

The current package instantiates repository inspection and documentation
contract tests. It specifies, but does not claim completion of, replay,
simulation, browser, and supervised live-hardware campaigns.

## Evidence Basis

Requirements, checked-in configuration, graph/runtime contracts, test suites,
and the paper evidence schema define the initial setup. Machine and equipment
inventories must be added to an evidence record when those environments are
actually used.

## Evaluation Environments

| Environment | Purpose | External effect | Minimum record |
|---|---|---|---|
| `inspection` | Verify declared architecture, files, counts, and contracts | None | Commit, command, source paths, observed values |
| `test` | Exercise bounded unit, contract, or integration behavior | None or controlled local state | Test selection, dependency versions, result count, output |
| `replay` | Re-run recorded inputs without a new physical action | None | Dataset/artifact identity, replay seed, expected/observed outputs |
| `simulation` | Exercise workflow against a declared simulator/emulator | Simulated only | Simulator/version, scenario, seed, model/device configuration |
| `browser` | Validate operator workflow and rendered state | UI/API state; physical effects disabled unless separately declared | Route, viewport, browser/driver, server mode, screenshots/logs |
| `live` | Exercise supervised physical or production-equivalent behavior | Potentially consequential | Equipment identity, calibration, operator, approval, stop conditions, raw evidence |

Results MUST remain in their recorded environment. A test result cannot fill a
live-evaluation row.

## Units of Evaluation

The evaluation unit changes by research question:

- RQ1 uses a graph/run/cycle with explicit stage and checkpoint state.
- RQ2 uses a claim-to-artifact lineage ending in a verifiable evidence record.
- RQ3 uses a consequential action scenario with expected gate and route.
- RQ4 uses an extension package plus its registration, validation, execution,
  evidence, and failure behavior.

The unit MUST be named before reporting a rate. For example, “gate success” is
ambiguous unless the denominator is scenarios, decisions, actions, or runs.

## Configuration Record

Every behavioral experiment SHOULD record:

- repository commit and dirty-state declaration;
- operating system, Python version, and dependency lock/requirement source;
- graph ID/version and active module versions;
- model provider, model identifier, generation configuration, and seed where
  supported;
- device/bridge profile, firmware or service version, and calibration state;
- run mode (`test`, `replay`, `simulation`, or `live`);
- objective, constraints, initial state, and expected terminal condition;
- operator approvals and stop procedure;
- artifact root and checksums.

Secrets and private endpoints MUST be represented by configuration variable
names, never copied into an evidence file.

## RQ1 Protocol: Closed-Loop Composition

The minimum protocol executes or replays a run from initialization to an
explicit continuation or terminal state. It records every stage transition,
typed handoff, checkpoint, artifact, failure route, and resume action. Scenario
families SHOULD include nominal flow, invalid contract, unavailable capability,
analysis failure, knowledge-sync degradation, Guardian stop, and uncertain
external effect.

Primary measures:

- stage-contract acceptance rate with numerator and denominator;
- runs reaching the expected terminal/continuation state;
- checkpoint recovery rate by failure class;
- duplicate consequential actions after resume;
- orphaned or unreferenced artifacts.

## RQ2 Protocol: Evidence Continuity

Select a bounded set of material claims from a run. For each claim, traverse
from the claim to evidence ID, output artifact, command or protocol, inputs,
commit, environment, and result. Record missing or conflicting links rather
than excluding them.

Primary measures:

- traceable claims divided by evaluated claims;
- outputs with verified SHA-256 divided by declared outputs;
- artifacts with complete run/cycle/stage identity;
- graph or report statements lacking a durable source record.

## RQ3 Protocol: Safety and Operator Gates

Construct scenarios where policy should allow, deny, require review, expire an
approval, fail a dry run, time out, or encounter uncertain external state. For
live scenarios, obtain laboratory-specific risk approval before execution.

Primary measures:

- expected gate decision agreement;
- unsafe or out-of-scope actions reaching a bridge;
- time to operator-visible stop state;
- repeated physical actions after ambiguous timeout;
- evidence completeness for denials and approvals.

Presence of a gate in configuration is not included as a successful safety
scenario.

## RQ4 Protocol: Contract-Preserving Extension

Add one bounded extension in each selected category—module, graph, backend,
bridge, or workspace—and exercise valid registration, invalid schema, missing
capability, evidence emission, and removal/rollback. Compare changed core files
and contract violations, not just integration time.

Primary measures:

- required core modifications per extension;
- validation defects detected before activation;
- extension failures contained within declared boundaries;
- evidence completeness under both success and failure;
- unsupported combinations explicitly rejected.

## Controls and Baselines

A comparative experiment MUST name a baseline that answers the same objective
under the same environment and stopping rule. Useful baseline classes may
include a linear scripted pipeline, the same graph without knowledge feedback,
the same graph without Bayesian-optimization candidate selection, or a manual
operator workflow. Baselines are proposals until their implementation and
protocol are recorded.

## Data Handling

Raw and derived artifacts SHOULD be immutable or content-addressed where
practical. Participant data, confidential instrument metadata, private network
details, and unpublished datasets require a publication decision before
release. Redaction MUST preserve enough structural information to understand
what was removed and why a result remains reproducible or becomes restricted.

## Limitations and Known Gaps

The current repository package does not yet pin a venue-specific experimental
matrix, physical equipment inventory, statistical power analysis, or domain
scientific endpoint. Those choices depend on the submitted study and must not
be inferred from available integration code.

## Verification

Reviewed on 2026-08-09 against requirements, graph modes, tests, and the paper
evidence schema. Only the inspection and documentation-test records are
instantiated in the initial artifact manifest.

## Related Documents

- [Closed-loop method](03_closed_loop_method.md)
- [Evaluation and results](06_evaluation_and_results.md)
- [Reproducibility](07_reproducibility.md)
