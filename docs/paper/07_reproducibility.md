<!-- atr-doc
doc_type: guide
subtype: how_to
status: review
authority: procedural
audience:
  - artifact_evaluator
  - researcher
  - developer
scope:
  - paper
  - reproducibility
summary: Defines progressive ATR reproduction tiers from static inspection through supervised live hardware.
source_of_truth:
  - REQUIREMENTS.md
  - scripts/validate_documentation.py
  - scripts/validate_paper_publication.py
  - tests
last_verified: 2026-08-09
verified_against: 78b0913
paper_section: reproducibility
research_questions:
  - RQ1
  - RQ2
  - RQ3
  - RQ4
claim_ids:
  - C-TRACE-DOC-01
related_docs:
  - docs/paper/05_experimental_setup.md
  - docs/paper/06_evaluation_and_results.md
  - docs/paper/artifact_manifest.yaml
supersedes: []
-->

# Reproducibility

<a id="summary"></a>

The latest [fifteen-iteration archive audit](evidence/2026-09-28-campaign-archive-audit.md)
provides a bounded read-only reproduction protocol and per-iteration hashes.
The public summary does not bundle private raw run data. Re-running the
experiment, re-analyzing retained CSV and checking an archive are different
reproduction tasks; none is silently performed by opening Replay.

From this public checkout, begin with document integrity and static architecture
inspection (Tier 0), or the focused documentation tests (selected Tier 1).
Reanalyzing campaign curves requires the separately retained private raw files;
a public hash index cannot supply those inputs. Launching hardware would be a
new authorized experiment, not a prerequisite for reviewing this paper.

Reproduction is progressive. A reviewer can validate the public document and
architecture contracts without models or devices, then proceed to tests,
replay, browser workflows, and supervised hardware only when the required
dependencies and approvals are available.

## Reproduction Tiers

| Tier | Environment | Objective | External effect | Recorded/public reproduction state |
|---|---|---|---|---|
| 0 | Inspection | Validate files, narrative order, graph/route counts, figures, links, and evidence hashes | None | Available |
| 1 | Test | Run focused unit and contract tests | Controlled local files/processes | Documentation subset available; full system subset not evaluated here |
| 2 | Replay or simulation | Exercise workflow and failures without new physical action | None or simulated | `not_evaluated` |
| 3 | Browser | Validate operator workflows against a declared server mode | UI/API state | `not_evaluated` in this package |
| 4 | Live | Execute supervised physical or production-equivalent protocol | Consequential | Bounded September 7 mixed-mode observations recorded; independent public reproduction and full fabrication certification remain unavailable |

## Prerequisites

For Tier 0:

- Git with the repository checkout;
- Python environment satisfying `REQUIREMENTS.md`;
- Graphviz `dot` for figure reproduction.

Higher tiers additionally require the exact services, models, datasets,
workers, simulators, browsers, devices, credentials, and approvals named by
their evidence record. Never infer those values from a developer machine path.

## Safety Boundary

Tier 0 is read-only except for generated verification files. Tier 1 may create
controlled local test artifacts. Tier 2 must prevent physical side effects.
Tier 3 must declare whether UI actions mutate server state. Tier 4 requires a
reviewed protocol, equipment-specific hazards, explicit operator authority,
dry run, emergency stop, and post-action proof.

Do not progress to a higher tier merely because a lower tier passes.

## Tier 0 Procedure

From repository root:

```bash
git rev-parse --short HEAD
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python scripts/validate_paper_publication.py
```

Re-render figures into an isolated temporary directory or explicit verification
files, compare them with the checked-in SVGs, and remove only those generated
verification files after comparison.

Inspect `docs/paper/artifact_manifest.yaml`, recompute each declared SHA-256,
and confirm that supported claims reference existing evidence.

Do not import the production `app.main` merely to count routes: that import
constructs the controller. Historical route commands belong to their recorded
baseline. Use static inspection, or an isolated offline environment with
controller construction stubbed and external effects denied.

## Tier 1 Procedure

The focused paper-documentation subset is:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_paper_publication_validation.py
```

Any system-test subset used for a paper result must be listed explicitly in a
new evidence record. Reporting “the test suite passed” without the command,
selection, result count, commit, and environment is non-reproducible.

## Tier 2 Procedure Contract

This and the following higher-tier sections define requirements for a new,
separately authorized reproduction. They are not ready-to-run recipes or claims
that the necessary datasets, servers or equipment are bundled.

A Tier 2 record must name the replay bundle or simulator, scenario IDs, seeds,
graph and module versions, model configuration, expected gates, expected
terminal states, and output artifact root. Physical bridges must be disabled or
replaced by declared simulation adapters. Record both nominal and failure
scenarios.

## Tier 3 Procedure Contract

A Tier 3 record must name server command and mode, URL route, viewport,
browser/driver versions, test script, screenshots or trace, mutation behavior,
and cleanup. Screenshots alone are insufficient when the claim concerns API or
runtime state.

## Tier 4 Procedure Contract

A Tier 4 record must identify equipment and calibration state without exposing
private network details, name the responsible operator, include approval and
stop criteria, record raw observations and external-effect proof, and state how
ambiguous timeouts are handled. Repeating an uncertain physical action is not
an automatic recovery step.

## Success Criteria

A tier is reproduced when:

- every required command or protocol step completes with recorded output;
- output hashes match or expected nondeterminism is quantified;
- the observed result matches the bounded claim;
- failures and deviations remain in the record;
- the report names only the completed tier.

## Failure Recovery

Stop at the first unmet prerequisite and report which part could not be
reproduced. Do not silently substitute another model, device or dataset merely
to obtain a passing result. Distinguish an unavailable tier from a failed
execution within an available tier.

- A missing optional dependency means the affected tier is unavailable, not
  failed or passed.
- A checksum mismatch invalidates the referenced output until explained and
  re-recorded.
- A stale commit requires a new evidence record; do not edit historical output
  to appear current.
- A simulator or device mismatch creates a new configuration and must not be
  merged silently with prior results.
- A live uncertainty requires stop/review before retry.

## Rollback or Stop Procedure

Tier 0 and focused Tier 1 may stop after terminating local processes and
removing only explicit generated artifacts. Tier 2–4 stop procedures belong to
their scenario records. Live stop procedures must be verified before the first
consequential command.

## Limitations and Known Gaps

The public package does not provide a complete archival dataset, pinned model
weight bundle, or venue artifact badge. It contains bounded Tier 4 observations,
but not public raw inputs sufficient to independently reproduce them, or a
paper-scoped Tier 2/3 record. The later fifteen-observation audit is Tier 0
inspection of retained evidence, not a new Tier 4 execution. Optional external
services may require agreements or hardware unavailable to reviewers.

## Verification

<a id="scope"></a>

Tier 0 and focused Tier 1 documentation checks are reproducible from the public
package. Bounded supervised mixed-mode Tier 4 observations were subsequently
recorded on September 7; their private raw archives are not bundled. Repeating
those experiments or claiming another Tier 1–4 result requires its own evidence
record, environment and authorization.

The [Orchestrator dynamic Setup verification](../runtime/evidence/2026-09-12-orchestrator-dynamic-setup-verification.md)
is one such bounded working-tree/Tier 1 record. Its provider cases use guarded
local handlers and do not elevate the result to Tier 2–4, live hardware, or a
complete experimental cycle.

<a id="source-of-truth"></a>

- Environment and setup requirements: `REQUIREMENTS.md`
- Document governance: `scripts/validate_documentation.py`
- Paper package contract: `scripts/validate_paper_publication.py`
- Machine-readable evidence: `docs/paper/artifact_manifest.yaml`

<a id="audience-and-outcome"></a>

This guide is for artifact evaluators, researchers, and developers. Completion
means reproducing one declared tier and reporting that tier without implying
completion of a higher one.

Tier definitions and focused commands were reviewed on 2026-08-09. The public
validator and its unit tests provide the initial machine-checkable reproduction
surface.

## Related Reference

- [Experimental setup](05_experimental_setup.md)
- [Evaluation and results](06_evaluation_and_results.md)
- [Artifact manifest](artifact_manifest.yaml)
