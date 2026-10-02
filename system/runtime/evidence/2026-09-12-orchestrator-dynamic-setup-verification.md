<!-- atr-doc
doc_type: evidence
subtype: test_report
status: active
authority: evidentiary
audience: [researcher, reviewer, developer, maintainer]
scope: [orchestrator, experimental_setup, bounded_model_verification, aggregate_postprocessing]
summary: Bounded working-tree verification of Orchestrator dynamic Setup contracts and a corrected aggregate of immutable provider captures.
source_of_truth:
  - scripts/verify_orchestrator_setup.py
  - tests/integration/test_orchestrator_setup_loop.py
  - tests/integration/test_orchestrator_verifier_shards.py
  - tests/integration/test_orchestrator_model_verifier.py
  - docs/agents/orchestrator_agent.md
last_verified: 2026-09-12
evidence_date: 2026-09-12
verified_against: working-tree
method: focused deterministic, guarded provider-case, and aggregate-consumer verification
related_docs:
  - docs/agents/orchestrator_agent.md
  - docs/runtime/langgraph_runtime.md
  - docs/paper/05_experimental_setup.md
  - docs/paper/07_reproducibility.md
supersedes: []
-->

# Orchestrator Dynamic Setup Verification

## Status at a Glance

| At a glance | Details |
|---|---|
| Scope | Working-tree contract, focused deterministic/API/GUI/loop checks, and bounded provider-case aggregation |
| Deterministic correction | 117 affected tests, eight retained-input checks, and one joined trace passed with zero failures/errors/skips; counts overlap and are not summed |
| Provider cases | Corrected aggregate passed: 78 unique cases per provider (72 intake including H01–H12 holdouts, plus six decisions) |
| Provider identities | API served only `gpt-5.5-2026-04-23`; Gemma served `gemma4:31b` from two 39-case shards; no fallback |
| External effects | Physical calls and denied attempts were zero; one Gemma lifecycle receipt was nonactuating (`actual_effect=false`) |
| Limit | This is not hardware, an all-20-cycle campaign, a public-Chat-to-end trace, or a model-driven whole-cycle result |

## Evidence Scope

The current contract is described in the [Orchestrator Agent Reference](../../agents/orchestrator_agent.md).
Confirmed settings schedule the next new run; its admission validates the captured
confirmed set before runtime/model review/LHS/Design, combines same-owner values
before an owner effect, and requires readback. This evidence checks that bounded
implementation and verifier behavior. It does not establish owner availability,
device readiness, service operation, scientific performance, or a general model-quality claim.

The final correction review directly inspected 117 affected tests, eight
retained-input tests, and one joined trace (48.99 s), all with zero
failures/errors/skips. The maximum current joined prompt capture was 15,632 UTF-8
bytes against the unchanged 16,000-byte bound. An earlier 44-test mode suite
predates the final projection-only `None` guard and is retained as earlier-epoch
evidence, not recast as a current whole-suite result.

## Immutable Provider Capture and Corrected Aggregation

The raw provider captures are immutable and share one frozen runtime/source,
fixture, prompt, and capture-verifier epoch. The capture verifier SHA-256 is
`64f6d3bbc8ef34323749033205117b64d7bd683012bd3e1592ddddc6b8191e93`.
The aggregate consumer was then corrected to classify intake rows by declared
decision membership instead of an ID prefix. Its SHA-256 is
`366b7a46b7160daa498a7c55a498d63a4f22a860e4c908e37225824791f55e45`;
the different hash is a postprocessing epoch, not a rewritten capture epoch or
a model rerun.

The corrected aggregate SHA-256 is
`5be1375dd1e2486e9fcce0fb735047bc1b4f5d801caedb20c3c0c19b5e2af5a2`.
It passed with empty errors after checking complete unique coverage, frozen
epochs, strict labels/status/effects, served attempt identity, and clean guards.
The API contributed one complete 78-case report; Gemma contributed two complete
39-case reports. Raw artifacts are retained in the local verification ledger,
not linked here because they are not public repository artifacts.

The aggregate-only correction had a focused RED/GREEN sequence. Before the
dispatch correction, five focused holdout/coverage tests failed; afterward the
focused verifier suites passed 70 tests (plus a later fresh 30-test shard suite),
with inherited Pydantic shadow warnings and no suppressed warnings:

```bash
.venv/bin/python -m pytest \
  tests/integration/test_orchestrator_verifier_shards.py \
  tests/integration/test_orchestrator_model_verifier.py -q --tb=short
```

The accepted aggregate command used the existing immutable API report and two
Gemma shard reports with `scripts/verify_orchestrator_setup.py --aggregate`; it
ran without `--execute` and therefore did not invoke a provider. Its output was
the local aggregate artifact identified by the SHA-256 above. The command and
raw artifact names are retained in the task ledger rather than presented as
public links.

The following is an illustrative reproduction shape, not a claim that these
placeholder paths were executed in a public checkout:

```bash
.venv/bin/python scripts/verify_orchestrator_setup.py \
  --aggregate <api-report.json> \
  --aggregate <gemma-shard-0-report.json> \
  --aggregate <gemma-shard-1-report.json>
```

## Interpretation Limits

Provider cases exercise bounded intake/decision contracts with guarded local
handlers. They do not prove a provider autonomously ran the complete experiment
loop, performed a physical effect, or used a public Chat session from start to
finish. The one simulated lifecycle receipt is expressly nonactuating. No
hardware, operating-service change, model-server configuration, commit, tag, or
push was performed for this documentation evidence.

## Related Documents

- [Orchestrator Agent Reference](../../agents/orchestrator_agent.md)
- [LangGraph Runtime](../langgraph_runtime.md)
- [Experimental Setup](../../paper/05_experimental_setup.md)
- [Reproducibility](../../paper/07_reproducibility.md)
