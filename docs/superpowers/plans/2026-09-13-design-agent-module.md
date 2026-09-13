---
doc_type: plan
subtype: implementation
status: active
authority: execution
audience: [developer, maintainer]
scope: [design_agent, module_contract, frontend_backend_ownership, compatibility]
summary: First Design module migration through existing registration, GUI and non-actuating orchestration paths.
execution_status: completed
governing_design: docs/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs: [docs/agents/design_agent.md]
supersedes: []
---

# Design Agent Module Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for the backend tasks and a scoped subagent for the independent frontend extraction. Track the checkboxes below. User authorization is to implement this first agent in the current workspace; do not commit, push, run hardware, or restart operating services.

**Goal:** Register Design through a reusable module contract and give its backend report projection, existing frontend assets, configuration and storage an explicit owner while preserving existing execution.

**Architecture:** Reuse `AgentRegistry` with an additive code-registered module contract, referenced by the existing `graphs/modules/design/module.yaml`. Existing `DesignAgent`, decision logic, graph handler and artifact writers remain the execution source. Move only Design-owned presentation logic out of the shared application/frontend; keep the existing API and UI entry points.

**Tech Stack:** Python dataclasses, existing FastAPI/PyYAML, plain JavaScript, pytest and Node.

**Spec:** [Package / Agent / Bridge design](../specs/2026-09-13-package-agent-bridge-modularization-design.md).

## Global Constraints

- Reuse existing modularization and existing file paths. No bridge/package installer implementation in this first agent slice.
- Preserve `agent.design_agent`, `DesignAgent.run`, `AgentResult`, `design_candidate.v1`, existing Setup support, artifact paths and test-mode semantics.
- Public contracts contain no local personal settings, credentials, private memory or runtime content.
- Registration uses a callable from installed code, never a dynamic import supplied by editable YAML.
- Current workspace includes the user's pending modularization design documents. Preserve them.
- The first agent deliverable does not claim completion of package installation, module removal, all-owner graph projection, or physical validation.

## Task 1: Code-registered module and backend report boundary

Files: create `agents/module_contract.py`, `agents/design/module.py`, `agents/design/presentation.py`, `tests/unit/test_design_module.py`; move the existing agent and decision implementation into `agents/design/agent.py` and `agents/design/decision.py` with legacy import shims; modify `agents/registry.py`, `app/bootstrap.py`, Design report dispatch and module responses in `app/main.py`, and `graphs/modules/design/module.yaml`.

Interfaces:

```python
@dataclass(frozen=True)
class AgentModule:
    module_id: str
    agent_name: str
    version: str
    factory: Callable[[], BaseAgent]
    descriptor_json: str  # immutable JSON; describe() returns a detached dictionary
    project_report: Callable[[dict, dict], dict] | None = None
    frontend_root: Path | None = None

# AgentRegistry owns both normal instances and optional module bindings.
registry.register_module(DESIGN_MODULE)
registry.get("design_agent")  # original DesignAgent instance
registry.get_module("design")  # optional code-registered AgentModule
module.describe()  # deep copied public descriptor; no executable callables
```

- [x] Baseline: run Design agent/decision tests and current Design frontend tests. Record failures before changing implementation.
- [x] Add behavior tests: normal registration identity; duplicate module/agent collision leaves registry unchanged; wrong factory name is rejected; descriptor copy cannot mutate registered contract; report projection preserves metadata-over-payload precedence, blocked and missing report semantics.
- [x] Run the new tests and inspect the failure.
- [x] Implement the contract in the existing registry and register Design from `app/bootstrap.py` through `DESIGN_MODULE` only. Preserve other registrations.
- [x] Extract the existing Design branch from `_agent_report_payload` into `project_design_report(metadata, agent_payload)`; route registered report projectors via the registry and preserve output keys and values.
- [x] Add public implementation metadata to the existing module detail/runtime-manifest APIs. Graph YAML references the registered contract; it cannot override its callable, identity, or ownership declarations.
- [x] Declare actual backend files, frontend host/descriptor, read-only Setup state, configuration inputs/default sources, shared services and existing archive/storage ownership. Do not invent an editable Design settings file or a Design-to-printer binding.
- [x] Verify the module-registered Design path with the existing tests, not only descriptor inspection.

## Task 2: Design frontend ownership

Files: create `agents/design/frontend/live_report.js` and a covering Node test under `tests/js/`; modify `web/static/planning.js`, `web/templates/planning.html`, and directly affected frontend tests only. The host will serve this module asset at `/module-assets/design/live_report.js`; the primary agent owns that mount in `app/main.py`.

The existing Design report view is the product surface. Extract a coherent Design-only presentation unit into `window.AX4LABDesignUI`, with explicit host inputs/helpers. Keep shared camera/STL/Specimen rendering in the host. Keep existing function entry points as thin adapters when existing consumers require them.

```javascript
// Shape of the boundary; implementation exports only the functions actually extracted.
window.AX4LABDesignUI = Object.freeze({ /* pure Design report functions */ });
// Host adapters pass required state/helpers explicitly; module owns no global polling.
```

- [x] Inspect the actual Design call graph and select the largest coherent unit whose external dependencies can be explicit without reproducing the host.
- [x] Baseline two existing event tests fail before edits because extracted functions lack their current helper dependencies. Diagnose these harness failures and supply the missing real helpers or narrow stubs in the harness, without changing runtime event semantics.
- [x] Capture the existing unit's output for populated, empty and adapted/unassessed evidence. Use before/after output comparison to verify extraction.
- [x] Move the unit with `apply_patch`; preserve markup, labels, sorting, escaping and event selectors. Include the script before `planning.js` with cache-busting URLs.
- [x] Run `node --check` on both files and relevant existing pytest/Node checks. Test repeated rendering does not create timers or duplicate subscriptions.
- [x] Validate actual browser rendering with installed browser tooling when available; use a non-actuating isolated fixture page. Report the limitation if no browser runtime is installed rather than claiming browser validation.
- [x] Report exact exports, host dependency boundary, extracted functions, tests and remaining shared Design code to the primary agent. No commits, hardware calls, operating server restart or subagent delegation.

## Task 3: Integration, compatibility and documents

Files: integration coverage under `tests/integration/test_design_module_api.py`; update `docs/agents/design_agent.md`, relevant index/matrix rows, the governing design's implementation note and this plan.

- [x] Test `/api/modules/design`, runtime manifest and existing Design report APIs using the normal application with a synthetic controller; assert registration metadata and original result semantics.
- [x] Confirm original registry entry uses the same Design class and existing deterministic/LLM decision tests cover that implementation. Exercise module entry with real existing archive and a synthetic model/transport across two loop identities.
- [x] Run Design tests, registry tests, touched API/frontend tests and the Basic Tests CI command. Do not run real-device workflows.
- [x] Update Design Reference with the implemented module boundary, retained paths, frontend backend connection and actual verification limits. Preserve canonical docs/figures and distinguish the wider target design from this first agent.
- [x] Perform code review of the complete scoped change. Fix actionable regressions and rerun affected checks.
- [x] Report implemented behavior, verification and remaining platform-wide work. Leave the result uncommitted for user review.

## Verification — 2026-09-13

Base: `9d11cf923f556e6abe87df3084dbbd5c022a5ea6`. This is software compatibility
evidence, not a new physical experiment or a new provider-model evaluation.

| Check | Result and scope |
|---|---|
| Before-change Design/backend/frontend baseline | 43 passed, 2 frontend harness failures; missing helper dependencies repaired without changing runtime event behavior |
| Basic Tests CI selection + Design/module/frontend/API regressions | 102 passed in 6.64 s, including the explicit module asset package-data declaration |
| Existing guarded orchestration and all-agent archive suites | 54 passed in 162.46 s; original profile entry, mixed-mode handoffs, next Design and per-loop retention |
| Existing LangGraph compile/module/transition/pre-execution/failure checks | 9 passed; 61 unrelated cases deselected |
| Design execution and decision implementation against base | Executable AST identical after normalizing only the moved decision import path; class and functions remain available through legacy imports |
| Frontend compatibility | Node contract and syntax checks passed; populated/empty/unassessed/missing/zero cases characterized against the original helpers |
| Browser fixture and API hosting | Isolated headless browser renders expected evidence; in-process `/live`, module assets, reports and manifests verified |
| Review | Missing-value-to-zero rendering regression fixed; stale legacy registration binding cleared; reviewed fixes verified |
| Documents | Changed governed documents checked with the existing validator; full manifest retains pre-existing Windows bridge reference and PLC design defects |

The guarded suite denies network, camera, serial/device and process execution
before bootstrap, then explicitly substitutes named transport boundaries.
It exercises the existing initial LHS → Design → Specimen route for
`virtual_bridge`, `installed_printer`, and `physical_print`, and the existing
tail through Analysis/BO back to Design. Real equipment-mode tests verify
existing command/admission contracts with simulated I/O, not actuation.
The archive suite checks two loop identities for every agent; it does not
claim each isolated archive attempt is a successful experiment.

The module-specific test separately performs controlled-model inspect→accept
tool decisions in two loops through `registry.get("design_agent").run` and
checks the resulting real archive files. Existing Design tests cover
return-to-owner, invalid tool/candidate/evidence, budget, timeout and cancellation.

Reproduction:

```bash
.venv/bin/python -m pytest tests/unit/test_experiment_runtime.py tests/unit/test_model_router.py tests/unit/test_printer_tools.py tests/unit/test_printer_profile.py tests/unit/test_guardian_agent.py tests/unit/test_design_module.py tests/unit/test_design_agent.py tests/unit/test_design_decision.py tests/unit/test_planning_design_report_js.py tests/integration/test_design_module_api.py -q
.venv/bin/python -m pytest tests/integration/test_orchestrator_setup_loop.py tests/integration/test_all_agent_loop_archives.py -q
.venv/bin/python -m pytest tests/unit/test_langgraph_runtime.py -q -k 'atr_graph_config_validates_and_compiles or module_config_schema_validates_active_modules or legacy_compatibility_helpers_derive or module_pre_execution_runs_orchestrator_before_design_from_config or module_pre_execution_can_be_skipped_for_live_planning_handoff or module_handler_override_changes_actual_agent_execution or missing_module_handler_fails_as_routing_error or module_internal_graph_emits_failure_event or configured_transition_changes_actual_langgraph_runtime'
node tests/js/design_live_report.test.cjs
```

`pyproject.toml` explicitly includes Design's JavaScript as package data; this is
not a complete standalone wheel/application-install validation. Existing
operating services were not restarted, models were not switched and no commit,
tag or push was made. Package installation, hot removal, multi-version hosting
and remaining Agent/Bridge migrations are deferred to subsequent slices.
