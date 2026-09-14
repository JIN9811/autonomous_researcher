<!-- atr-doc
doc_type: plan
subtype: implementation
status: archived
authority: proposal
audience: [developer, maintainer, reviewer]
scope: [bo, packages, module_ownership, runtime_ide, live_gui]
summary: Preserve BO behavior while installing its owner package, executable view and frontend through existing module contracts.
plan_status: completed
execution_status: completed
governing_design: docs/oldversion/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs:
  - docs/oldversion/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
  - docs/oldversion/superpowers/specs/2026-09-13-executable-agent-ide-contract-design.md
  - docs/agents/bo_agent.md
supersedes: []
-->

> Archived development history (2026-09-14). Not the current implementation or acceptance contract. See the [archive index](../../README.md) for current references.


# BO Agent Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Preserve the current checkout and do not publish without a new user request.

**Goal:** Install BO as the final specialist Agent Package without changing its optimization or experimental route.

**Architecture:** Reuse the installed Analysis/Equipment module contracts, generic host, package service and source-backed IDE renderer. Canonical BO ownership contains the existing agent/decision code and report composition; existing numerical services remain referenced dependencies, not a new bridge.

**Tech Stack:** Python, existing AgentModule/ExecutionCatalog, YAML descriptors, vanilla JavaScript Live host and pytest/Node tests.

**Spec:** [Package / agent / bridge design](../specs/2026-09-13-package-agent-bridge-modularization-design.md), including the 2026-09-14 core-agent decision.

## Status at a Glance

| At a glance | Details |
|---|---|
| Status | Completed; scoped review approved |
| Baseline | `ec955d99180683c36483be64be87e909f546fcfb` |
| Owner | `agents/bo/`; package `bo@1.0.0` |
| Device effects | None; do not introduce a BO Device Bridge |
| Verification | Software-only; distinguish controlled decisions from real registered-provider calls |

## Global Constraints

- Current working checkout; preserve unrelated changes. No user-server restart, hardware/native-FEM execution, model lifecycle changes, credential changes or automatic publication.
- Preserve continuous/discrete domains, LHS initialization, BoTorch acquisition, numerical coordinates, objectives, budget/seed, evidence gates, failure outcomes, settings persistence and Design handoff.
- Existing `agents.bo_agent` and `agents.bo_decision` imports remain exact module aliases. Preserve public `run` and `run_with_settings` signatures and one archive receipt per invocation.
- High means actual LLM decisions; Middle means APIs/processes/numerical tools; BO has no physical Low node. Keep common five-area backgrounds, source edges and `LLM`/`LLM call` labels.
- Reuse registries, graph schemas, module assets, report endpoint, setup hooks, storage and numerical services. No new polling timer, report store, transport, queue or optimizer bridge.
- ORC/KNW/GRD remain untouched in code this step. Their core folder grouping and Knowledge/Guardian Plans are subsequent design/work, not hidden implementation here.
- Current reference docs are English; design notes may remain Korean. Regenerate document-theme SVG only, not raster artwork.

### Task 1: Install BO owner, frontend and package while retaining behavior

**Files:** Create `agents/bo/{__init__,agent,decision,module,execution,structure,presentation}.py`, `agents/bo/frontend/live_report.js`, `packages/agents/bo/{package.yaml,README.md}`, `graphs/modules/bo/ui.yaml`, `tests/unit/test_bo_module_contract.py`, `tests/integration/test_bo_module_api.py`, `tests/js/bo_frontend.test.cjs`. Modify `agents/bo_agent.py`, `agents/bo_decision.py`, `app/bootstrap.py`, narrow BO-owned portions of `app/main.py` and `web/static/planning.js`, existing BO module YAML, package service, setuptools data, document exporter and relevant owner/index/API/runtime/spec docs. Numerical implementations under `learning/` and `experiments/` remain in place.

**Interfaces:** Consume existing `AgentModule`, `ExecutionCatalog`, `AgentContext`, generic module asset/report host and `renderDashboardCard`. Produce `BO_MODULE`, `bo_execution_catalog`, `bo_implementation_structure`, `project_bo_report`, namespace `AX4LABBOUI.createFrontend`, `/module-assets/bo/live_report.js`, the unchanged `/api/agents/bo/report` and handler `agent.bo_agent`.

- [x] Write RED tests for owner identity/discovery, public entrypoint/archiving behavior, source catalog, package with empty bridge dependencies and frontend/report admission. The consumer-facing identity contract includes:

  ```python
  import importlib
  old = importlib.import_module('agents.bo_agent')
  new = importlib.import_module('agents.bo.agent')
  assert old is new
  assert registry.get_module('bo').factory is new.BOAgent
  assert registry.get('bo_agent').name == 'bo_agent'
  ```

- [x] Run `pytest tests/unit/test_bo_module_contract.py` before creating the owner; record missing canonical module failure. Run installed API checks only with the existing VerificationGuard fixture, never live device services.
- [x] Move BO agent and decision implementation mechanically through apply_patch; adjust `__file__` root depth for existing run storage. Preserve old modules using the existing exact alias pattern:

  ```python
  import sys
  from agents.bo import agent as _implementation
  sys.modules[__name__] = _implementation
  ```

- [x] Expose the existing task body through guarded `bo.task` → `bo.deliver` operations, without running BO twice. Keep default-run versus explicit-settings behavior and archive semantics; test both public entrypoints. Source catalog describes actual local LLM strategy/review and numerical/knowledge/gate relations rather than inventing execution steps.
- [x] Register one discovered BO module and remove only duplicate bootstrap registration. The Agent Package is `schema: ax4lab.agent_package.v1`, `id: bo`, `version: 1.0.0`, `agent_module: {id: bo, version: 1.0.0}`, `handler: agent.bo_agent`, `module_reference: graphs/modules/bo/module.yaml`, `bridge_modules: []`.
- [x] Extract existing BO-specific report profile/projection and report/dashboard composition into the owner. Keep LHS visibility, BO charts, paging, layout, plot mounts and existing workspace API/settings routes. Reuse shared render helpers and the existing selected-owner hydration lifecycle for full report evidence; test missing-asset descriptor fallback, inactive owner, prior-loop evidence and stale responses. Do not repeat the Analysis cache mismatch: publish a new host cache token and keep preceding Analysis cache regression test current.
- [x] Run safe baseline-versus-owner BO tests covering initial LHS, completed measured priors, continuous parameters, invalid/missing evidence, numerical-backend failure without fallback, settings readback, archive and Design request identity. Prove an Analysis → BO → Design software handoff with synthetic measurement inputs; test-mode route checks reuse guarded fixtures and identify controlled versus real LLM evidence explicitly.
- [x] Run Node owner/host/BO visualization tests, guarded API/source/activation tests, common IDE renderer tests and publication scan. Use an isolated GET-only helper for 1920×1080 Live/IDE verification when needed; do not restart port7860.
- [x] Update BO reference, agent index/API matrix, Runtime IDE and modularization implementation status. Generate `docs/agents/assets/figures/bo_control_areas.svg` from the existing document-theme exporter. Preserve earlier scientific/physical evidence as historical and record exact software validation results, including any inherited failures.
- [x] Obtain scoped code review and resolve concrete regressions before final handoff. Leave changes uncommitted until the user requests publication.

## Verification Record

Exact RED/GREEN commands, independent guarded evidence, modified files and
limitations are recorded in
`.superpowers/sdd/2026-09-14-bo-agent-package/task-1-report.md`. No new physical
or full-provider cycle result is claimed by this plan. Independent checks
retained 74 focused BO regressions, passed five fixture-guarded routes and two
registered-provider BO cases. Final independent checks passed 44 BO plotting
contracts in 2.71 s and four guarded BO API contracts in 4.57 s, validated a
37-file staged publication snapshot, and confirmed acquisition plus initial-LHS
owner views and the post-fix parameter/priority handoff at 1920×1080. The final
helper exited with zero device calls, zero denied effects and no console errors.
Both scoped reviews approved the resolved snapshot with no remaining Critical or
Important finding.
