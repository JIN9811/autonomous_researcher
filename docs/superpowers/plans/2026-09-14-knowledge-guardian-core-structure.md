<!-- atr-doc
doc_type: plan
subtype: implementation
status: active
authority: execution
execution_status: completed
audience: [developer, maintainer, reviewer]
scope: [knowledge, guardian, core_agents, plan_contracts, runtime_ide]
summary: Refactor Knowledge and Guardian into plan-ready core owner structures while preserving the existing execution flow.
governing_design: docs/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs: [docs/agents/knowledge_agent.md, docs/agents/guardian_agent.md, docs/runtime/runtime_ide.md]
supersedes: []
-->

# Knowledge and Guardian Core Structure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Work in the current checkout; keep prior changes and this task uncommitted.

**Goal:** Give both core owners executable/source-backed structure, owner-owned presentation and plan-binding boundaries without changing the existing flow.

**Architecture:** Reuse the existing execution catalog, graph compiler, IDE renderer and report host. ORC/KNW/GRD remain explicitly registered core agents, not removable specialist packages. Preserve the original Knowledge and Guardian bodies as composite tasks; expose real internal responsibilities through source-backed CODE relationships rather than splitting side effects into new stages.

**Tech Stack:** Existing Python, YAML, JavaScript and SVG renderer; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md`, especially core agents, five-area execution views, existing-path reuse and plan boundaries. User approved plan-ready refactoring with unchanged flow on 2026-09-14.

## Global Constraints

- Baseline working-tree snapshot is `b322bf72fa5cc5accbbd56e048de54b41c57f825`, on HEAD `05d5e55687aacf7647413bb266aef8d836eb1346`. Prior agent-import cleanup is uncommitted and must be preserved. Review only this task's delta from that snapshot.
- No commit, tag, push, operating-server restart, actual device action, native FEM or provider lifecycle changes. No private data added to Git. Keep validation evidence in the task's ignored workspace.
- Preserve public `run(state, ctx)`, agent/handler/tool/API IDs, external stage order, LLM/tool call counts and arguments, stop/cancel/error semantics, existing storage paths and one archive attempt per invocation.
- Knowledge scope, ontology, Markdown/source curation, user memory boundaries and evidence provenance remain authoritative in their existing services. Do not revive graph storage or expand permissions.
- Guardian's deterministic gate precedence and operator stop remain authoritative; its existing LLM policy note remains advisory. No plan may disable mandatory checks or convert missing evidence into readiness.
- A plan-ready boundary is not a new workflow: no Plan editor, scheduler, event bus, settings store or Experimental Package import activation. Do not introduce a parallel run endpoint or make a speculative plan metadata key silently override execution.
- Plan contracts expose only supported configuration. Default resolution reads current owner inputs without adding new effective defaults to downstream payloads. Unsupported policy/settings changes are rejected rather than ignored. No configurable Guardian threshold changes in this structural refactor.
- Keep `knowledge/`, `policies/`, common chat/session/API/storage services in place; move only owner presentation or bounded decision code when there is an actual responsibility to separate.
- Use the existing five-area theme and legend: actual LLM decisions are High; preparation/API/composite execution are Middle and labeled `LLM call` where applicable; Guardian/Evidence cross-cut; both agents have no fabricated device Low.

## Task 1: Core owner structure, plan contracts, presentation and verification

**Files:**
- Modify: `agents/core/knowledge/agent.py`, `agents/core/guardian/agent.py`.
- Create for each owner: `execution.py`, `structure.py`, `plan.py`, `presentation.py`, `module.py`; add `agents/core/guardian/decision.py` for the existing bounded advisory call.
- Modify: `graphs/modules/knowledge/module.yaml`, `graphs/modules/guardian/module.yaml`, `app/main.py`, `scripts/render_module_control_views.py`.
- Add owner frontend files under `agents/core/knowledge/frontend/` and `agents/core/guardian/frontend/` only for existing owner-specific Live composition; preserve shared `web/static/knowledge_live.js` chat/delivery helpers. Integrate through existing host code in `web/static/planning.js` and its current template.
- Modify relevant owner/index/matrix/Runtime IDE docs and `agents/core/README.md`; generate `knowledge_control_areas.svg` and `guardian_control_areas.svg` using the existing light document renderer.
- Create: `tests/unit/test_core_owner_structure.py`, `tests/unit/test_core_owner_plans.py`, and focused core report/frontend integration tests alongside existing tests.

**Interfaces:**
- Public owner `execution_catalog()` and `_execute(state, ctx)` follow existing specialist/ORC patterns; archived `run` invokes `_execute` once.
- `knowledge_execution_catalog(agent)` / `guardian_execution_catalog(agent)` declare exactly one composite task and delivery operation. Each task invokes the preserved `_run_task` body once; each delivery returns the actual fresh `AgentResult` produced by that task.
- Owner `plan_contract()` returns a detached, serializable description of the existing settings/input bindings and authority boundaries. Owner `resolve_plan(state)` returns the current effective input snapshot; `validate_plan(plan, state)` validates a proposed binding without applying it or writing state. Resolve and validate must share the same owner rules. A future caller can use these APIs before the existing invocation path; this task does not add activation.
- Knowledge binding supports its existing `knowledge_settings` scope, corpora, source scope, applicability, decision timeout and decision step budget. Preserve their current defaults/validation and service authorization; default execution must not manufacture new settings keys. Guardian binding describes existing mandatory policy inputs/references and optional advisory evidence context only; executable threshold overrides/check disabling remain unsupported.
- Reuse `AgentModule` as a read-only core presentation contract if useful, through a class `core_module()` method returning `CORE_MODULE`. Do not call `register_module` for core agents or export discovery `MODULE`; retain explicit bootstrap and specialist package enumeration. Existing report/asset/IDE hosts may query the contract of an already registered core instance. No new registry.

- [x] Characterize the baseline results and side effects with controlled dependencies before refactoring. Preserve default successful Knowledge writes/BO handoff, invalid scope failures, Guardian continue/retry/recover/stop precedence, test-only degraded advisory call versus live exception, cancellation, and one archive attempt. Copy baseline owner files into ignored verification fixtures if needed; never retain a second production implementation.
- [x] Add RED tests for the new owner boundary. In particular, `validate_plan` must not mutate `state.run_metadata`, default `resolve_plan` must preserve existing settings, a Guardian proposal to disable forced stop must raise, and unsupported owner/version/settings must be rejected.

```python
before = deepcopy(state.run_metadata)
snapshot = agent.resolve_plan(state)
assert state.run_metadata == before
with pytest.raises(ValueError):
    guardian.validate_plan({"disable_operator_stop": True}, state)
assert state.run_metadata == before
```

- [x] Add RED execution contract tests: a compiled graph cannot deliver without the task result, repeat the composite side effects, call an unregistered operation or claim a branch without required outputs. Default graph calls the original task once and archives once. Valid graph presentation edits leave outputs unchanged; supported execution edits use the same compiler and owner catalog as the IDE.
- [x] Implement the smallest owner split. Move Guardian advisory reasoning without changing prompt, timeout, reference delivery or exception handling. Keep numerical/policy decisions and all Knowledge side effects in their existing order. Expose existing owner settings through detached `resolve_plan` / `validate_plan` queries without inserting a resolver call into the current run or changing its values, payload shape or error order.
- [x] Implement source-bound structure for each composite: actual model calls, reference delivery, local tools, deterministic gates, storage/evidence and returned observations. Do not turn source nodes into separately executable operations or sequential five-stage workflows.
- [x] Extract current report projection/profile and owner card composition into owner files, retaining original output/card IDs and host-owned polling/events. Keep `/knowledge`, Guardian status/approval APIs, existing CSS and cross-agent chat/memory controls intact. Core presentation availability must not change core registration or graph admission semantics.
- [x] Update IDE catalog lookup to obtain registered core owner catalogs without special-casing every owner. Preserve ORC behavior, specialist discovery and missing/disabled module handling. Render shared light SVGs and include them in current owner docs, with Status at a Glance, source links, plan-ready boundaries and validation scope.
- [x] Run focused owner/plan/graph/API/frontend tests, then the established guarded five-route suite through next Design, with no physical effects. Compare baseline and new default results rather than weakening prior expectations. Verify core agents remain outside the specialist package catalog, archived results remain readable and plan proposals cannot widen permissions or disable gates.
- [x] Review only changed source-doc claims before refreshing any Wiki source hashes. Validate affected governed docs and private-index publication boundaries; leave unrelated pre-existing governance debt unchanged.
- [ ] Report exact commands/results, changes, supported versus deferred plan capabilities, and no-actuation boundary. Freeze code for task and final review; do not commit.

## Controller Verification

The controller independently runs guarded route cases and validates IDE/Live using an isolated non-actuating test server, not the user's operating process. Viewports are 1920×1080 and a narrow layout. Verify owner switching, real source/legend display, no duplicate cards/pollers, no console errors, and existing graph save/validation semantics using test-only paths. No production graph activation or configuration overwrite.

## Acceptance

Default owner output, existing scientific/safety decisions and outer route remain equivalent. The new contracts make supported plan binding inspectable and testable but do not claim a new Plan UI, new policy behavior or live hardware/model validation. All changes are applied over, not in place of, the preceding import cleanup.
