---
doc_type: plan
subtype: implementation
status: active
authority: execution
audience: [developer, maintainer]
scope: [guardian, reasoning, readonly_tools, verification]
summary: Implement the approved bounded Guardian evidence decision without changing physical execution or safety gates.
execution_status: completed
governing_design:
  - docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
  - docs/superpowers/specs/2026-09-11-guardian-evidence-decision-design.md
related_docs:
  - docs/agents/guardian_agent.md
supersedes: []
---

# Guardian Evidence Decision Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development task-by-task. Do not commit or push without the user's next instruction.

**Goal:** Replace Guardian's explanatory model note with a bounded evidence-review and read-only tool decision layer while retaining the existing safety and runtime routes.

**Architecture:** Deterministic mandatory checks remain authoritative. A normal-path model may inspect scoped evidence and request continuation, operator review, or safe stop; validated output maps to the existing Guardian return contract. Hardware and PLC integration are excluded.

**Tech Stack:** Existing Python AgentContext, registered tools, pytest, DOT/SVG documentation.

**Spec:** [Guardian approved design](../specs/2026-09-11-guardian-evidence-decision-design.md), under the [five-area contract](../specs/2026-09-07-five-area-agent-restructuring-contract-design.md).

## Global Constraints

- Preserve graph routes, bridge implementations, physical interlocks, stop authority, and current mandatory gate semantics.
- No PLC, device actuation, model startup/shutdown, automatic recovery/replay, commit, tag, or push.
- Use registered AgentContext API and vLLM routes; never add another model backend.
- Current run/loop/specimen identity and evidence provenance must be code-bound, not model-invented.
- API and local verification use isolated virtual tool registries and validation-only artifacts.
- English agent reference, concise status summary, five-area table, tool/contract tables, three readable SVG figures with DOT sources. Do not claim physical validation.

### Task 1: Bounded Guardian decision and integration

**Files:** Create `agents/guardian_decision.py`, `tests/unit/test_guardian_decision.py`; modify `agents/guardian_agent.py`, `tests/unit/test_guardian_agent.py`, `graphs/modules/guardian/module.yaml`, and Guardian's prompt entry in `backends/prompt_registry.py` if needed. Do not change model-global settings or routing.

**Interfaces:** `async run_guardian_decision(state, ctx, *, evidence, read_health)` returns a JSON-safe decision dictionary. Evidence includes code-computed validations and baseline action. `read_health` calls the existing health validator preserving installed-printer parameters. Return includes `status`, `action`, `reason`, `evidence_refs`, `llm_used`, `trace`, and identity. Existing Guardian fields remain and add `llm_decision`.

- [x] Write RED tests through the real GuardianAgent: valid structured `review` changes a formerly normal continuation into existing `continue/recover`; malformed output also holds; preexisting stop skips model; concurrent stop interrupts a sleeping model promptly; hard gate cannot be overridden by structured continue.

```python
result = await GuardianAgent().run(state, ctx_with_review_response)
assert result.data['guardian']['action'] == 'recover'
assert result.data['guardian']['llm_decision']['llm_used'] is True
```

- [x] Run `.venv/bin/python -m pytest tests/unit/test_guardian_decision.py -q` and record actual failing assertions before implementation.
- [x] Implement bounded JSON tool protocol using `ctx.complete('guardian_reasoning', ...)`, with requests `{"tool": NAME, "arguments": OBJECT}`. Proposed scoped tools: `guardian.evidence.read` (section allowlist), `guardian.failures.read` (bounded and labeled historical), `device.health` (no model-supplied route override), `experiment.queue.status` (code-bound run identity), and `guardian.decision.submit` (`action`: continue/review/safe_stop, reason, evidence_refs). Names are local capabilities; only existing external registry names are dispatched externally. No arbitrary file reads, SQL, shell, or device commands.
- [x] Enforce maximum turns/duplicate request budgets and finite positive timeouts via `run_metadata.guardian_settings`. Defaults: 6 turns, 120 s per call, 300 s total; use cancellation-aware waits and preserve external CancelledError. Unknown tools/invalid schema/nonfinite values/provider errors produce review, never allow. Final submit requires nonempty valid evidence refs. Archive tool request/result using existing archive helper. Capture only concise rationale, not hidden thinking.
- [x] Keep mandatory baseline stop/recover/retry constraints as a floor, permit model escalation, and recheck latest stop flags, graph gates, health metadata, consistency, and changed evidence before return. Model is not required on already blocked/terminal states. Unknown health/tool failures must not become healthy evidence. Do not have model clear gates or mark historical failures resolved.
- [x] Cover current-versus-foreign identity, duplicate tools, fresh health fault, concurrent state mutation, failed queries followed by continue, settings validation, cancellation, JSON parsing, budget expiry, and tool observation influencing model submission. Update old explanatory test stubs to structured requests, preserving mandatory branch expectations.
- [x] Run focused Guardian unit/gate/shield/fault tests; self-review and report RED/GREEN evidence. No commits.

### Task 2: Verification and reference integration

**Files:** Create `scripts/verify_guardian_decisions.py` and tests for its non-actuating harness; update `docs/agents/guardian_agent.md`, Guardian DOT/SVG figures, five-area contract's Guardian status, and API matrix only if the declared interface needs correction.

**Interfaces:** Consume actual Task 1 schema; use `_build_backend`, `_models_cfg_for_backend`, `AgentContext`, existing saved API credential convention from `scripts/verify_bo_decisions.py`. Read credentials without printing them. Do not start servers or change active GUI backend.

- [x] Add an opt-in CLI requiring `--execute`; default output under `artifacts/validation/guardian-evidence-decision-*`. Install only virtual status tools. Test rejection of physical tools and case expectation logic before adding harness behavior.
- [x] Run API and registered local cases: normal continuation, evidence lookup, conflict requiring review, hard-stop precedence, and a bounded virtual loop/handoff test using existing runtime helpers. Assert model actually used on normal cases and no fallback masquerades as the requested backend.
- [x] Record requested/actual backend and model, elapsed time, calls, decisions, trace, verification category and failures. Preserve validation artifacts; missing service is a reported blocker, not fabricated success.
- [x] Update existing Reference, not a duplicate: six-line status; five-area roles; actual tool schema/decision mapping; API and connections; bounded errors; artifacts and verification. Three DOT/SVGs describe handoffs, local decision loop, and read-only/safety boundary. Keep historical physical evidence separate from new software validation.
- [x] Run focused tests, existing documentation validator and links/figure checks. Inspect rendered SVG readability. Complete independent code/spec review and final review before reporting.

## Execution ledger

- Baseline: `ddb08a8`; 54 Guardian tests pass, five preexisting Pydantic field-shadow warnings.
- User approved implementation and excluded PLC. Previous FEM changes are stashed and out of scope.
- Work in current checkout on `feat/guardian-evidence-decision`; separate worktree not created without consent.
- Completed: final focused unit set 158 passed (2.67 s); combined regression with two virtual full cycles 158 passed (95.66 s), followed by one additional contradictory-health regression in the final unit set.
- Registered API and vLLM probe: 10/10 cases passed; receipt `artifacts/validation/guardian-evidence-decision-lzse61pz/results.json`. Mandatory-stop cases intentionally do not invoke a model.
- Independent review findings closed: missing/nested/contradictory health, nonfinite evidence, model conflict assertion and provider-returned identity verification. Existing bridge, graph and physical execution paths were not edited.
- Guardian reference and three figures validated. Repository-wide documentation failures remain limited to the preexisting Windows bridge reference and old PLC design metadata; no unrelated repairs performed.
- No hardware actuation, service startup, commit, tag or push performed.
