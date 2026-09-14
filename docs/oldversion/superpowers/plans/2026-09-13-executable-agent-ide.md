---
doc_type: plan
subtype: implementation
status: archived
authority: execution
audience: [developer, maintainer]
scope: [runtime_ide, design_agent, orchestrator_agent, executable_modules]
summary: Share one executable agent definition across owner dispatch, Runtime IDE editing and document SVGs.
execution_status: completed
governing_design: docs/oldversion/superpowers/specs/2026-09-13-executable-agent-ide-contract-design.md
related_docs: [docs/runtime/runtime_ide.md, docs/agents/design_agent.md, docs/agents/orchestrator_agent.md]
supersedes: []
---

> Archived development history (2026-09-14). Not the current implementation or acceptance contract. See the [archive index](../../README.md) for current references.


# Executable Agent IDE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make Design/Orchestrator internal Runtime IDE graphs and backend execution share one authoritative definition.

**Architecture:** Owner-bound operations wrap existing functions. A validated module execution graph drives those operations and the existing editable canvas; trace identifiers, branch outcomes and persistence round-trip exactly.

**Tech Stack:** Existing Python/Pydantic/FastAPI, YAML descriptors, vanilla JavaScript/SVG and pytest/Node/installed Playwright.

**Spec:** docs/oldversion/superpowers/specs/2026-09-13-executable-agent-ide-contract-design.md

## Global Constraints

- Work in the existing repository checkout and preserve unrelated edits. Complete implementation and review before the separately authorized commit, tag and push.
- No hardware, live-model calls, service restarts, equipment polling, private artifacts, or broad cleanup.
- Existing algorithms, result envelopes, archive wrappers, mode policies and downstream routes stay unchanged.
- One executable definition drives backend/IDE/SVG. Never infer executable edges from checkpoint array order or responsibility colors.
- New definitions apply via existing validate/version/activate routes; running definitions remain pinned.
- Tests deny external transport before application import; reuse `actual_controller` from `tests/integration/test_orchestrator_setup_loop.py`.
- Documentation is English except existing Korean design contracts. Use apply_patch for source changes.
- Implementation workers do not spawn subagents and do not commit. Parent handles independent review.

### Task 1: Executable definition, owner operations and backend integration

**Files:** Create `agents/execution_graph.py`, `agents/design/execution.py`, `agents/orchestrator_execution.py`, `tests/unit/test_agent_execution_graph.py`, `tests/integration/test_agent_execution_graph_api.py`. Modify `agents/design/agent.py`, `agents/orchestrator_agent.py`, `orchestrator/langgraph_runtime.py`, `graphs/modules/{design,orchestrator}/module.yaml`, `graphs/schema.py`, scoped module validation/GET/dry-run APIs in `app/main.py`. Preserve unrelated edits.

**Interfaces:** `module.execution_graph` uses `{schema:'ax4lab.execution_graph.v1',entry,nodes,edges,terminals}`; node `{id,handler,label,area,llm?,config?,position?}`; edge `{source,target,on,kind}`. Catalogs expose real allowlisted operations and accepted dependencies/outcomes/config. Backend GET adds `execution_catalog` alongside unchanged `module`. Publish exact Python signatures and event payload in report for Task 2.

- [x] Write RED tests using literal small graphs: reorder independent operations by editing edges, not nodes; rejected cycles, dangling/unknown handler, invalid outcome/config and skipped input producer; snapshot unchanged when source edited after run start; cancellation/failure no later side effects. Example fixture:

```python
graph = {'schema': 'ax4lab.execution_graph.v1', 'entry': 'a',
         'nodes': [{'id': 'a', 'handler': 'fixture.a', 'area': 'middle'},
                   {'id': 'b', 'handler': 'fixture.b', 'area': 'knowledge'}],
         'edges': [{'source': 'a', 'target': 'b', 'on': 'next', 'kind': 'execution'}],
         'terminals': ['b']}
# Changing entry to b and reversing the edge must run b,a, not array order a,b.
```

- [x] Run `pytest tests/unit/test_agent_execution_graph.py -q`; confirm feature-missing failure before production changes.
- [x] Implement schema/compiler/runner and catalog; fail before dispatch, route actual outcomes, emit stable node/edge/status trace with graph revision, preserve invocation scope and no private inputs in events.
- [x] Extract current `run()` operations into owner adapters without rewriting their computation. Design preparation/decision/accepted-finalize/review-result and deterministic policy must match current results. ORC mission and plan construction precede bounded decision, then existing reporting helpers. Composite decision operations keep existing internal validation/tool loop; label honestly.
- [x] Migrate both module definitions from decorative internal lists to explicit actual execution nodes/edges. Preserve stage pre-execution effects and unmigrated handler overrides; require migrated graphs to retain their catalog owner and prevent phantom checkpoint traversal before `agent.run`.
- [x] Pin applicable module definitions for current run, including ORC invoked from another stage or standalone planning. Reuse existing context/snapshot mechanisms; no mutable global current graph.
- [x] Integrate schema/catalog validation, real GET projection and honest structural dry-run preview using current module endpoints. Retain 409 busy activation and failed-save no-write behavior.
- [x] Add RED/GREEN API tests with isolated roots and real operations: save a valid edge reorder, execute and verify order; GET reflects backend edit; invalid and busy operations retain active bytes; deterministic and accepted/rejected original agent outcomes remain unchanged. Run existing Design/ORC tests and focused LangGraph compatibility.
- [x] Self-review and report exact commands, failures/pass counts, changed files and all contract decisions; leave code uncommitted for task review.

### Task 2: Editable frontend, actual edge projection and documentation

**Files:** Modify `web/static/module_control_view.js`, `web/static/runtime_ide.js`, scoped `web/static/runtime_ide.css`, `web/templates/runtime_ide.html`, `scripts/render_module_control_views.py`, tests in `tests/js/module_control_view.test.cjs`, `tests/unit/test_module_control_views.py`, new `tests/js/module_execution_editor.test.cjs`, relevant agent/runtime/spec docs and Wiki source hashes. Use existing backend contract from Task 1 report.

**Interfaces:** Consume exact `execution_graph` and GET `execution_catalog`. Keep existing graph tab/inspector/save API. Reuse stable node IDs and explicit edge outcomes/kinds; edits serialize back to same definition, not an ordered checkpoint list.

**Execution ownership:** Parent authors reference/contract Markdown and Wiki hashes
in parallel; the Task 2 implementer owns frontend, renderer, generated SVG and test
files, and may adjust YAML presentation positions/empty-area explanations only.
Review covers both contributions. Report required documentation corrections to
the parent without overwriting those files. The Browser plugin/skill is absent;
use installed `.venv` Playwright and `/usr/bin/google-chrome` with intercepted
actual IDE assets, no app bootstrap or external requests. Previous fixture
`/tmp/ax4lab_control_area_browser.py` is a starting point only: its ordered-step
assertions must be replaced with executable-graph interactions.
The parent has also captured an actual-asset RED with
`/tmp/ax4lab_executable_ide_browser.py`: Design expects 4 executable nodes but
the legacy canvas renders 1 pre-step. Extend that isolated fixture or replace it
with the required full interaction validation.

The two migrated `metadata.control_view` assertions in
`tests/integration/test_design_module_api.py` also need to assert the new real
graph/catalog contract; retain all unrelated module lifecycle/API checks.

- [x] Write RED Node tests that projection and editor serialization preserve non-array order, branch edges, operation config and node positions. Example: `[a,b,c]` nodes with edges `a→c→b` must remain those edges after drag/label edits and save.
- [x] Implement executable graph adapter for existing `modulePayloadToGraph` / `applyModuleGraphDraftToEditor`; never rewrite branch edges into a single default chain. Unmigrated modules retain old adapter.
- [x] Wire actual inspector and node/edge addition/deletion to executable definition; registered operation catalog only, supported config and outcome selection, invalid drafts visible to Validate. Preserve ports and layout geometry; no separate architecture-view switch.

  Existing integration points include `addCatalogModuleAsInternalStep`,
  `removeModuleStepNodeFromDraft`, `connectionDragPlan`, `finishPortConnect`,
  `syncLogicalTransitionEdge`, Apply/Delete Edge, `renderNodeInspector`,
  `updateModuleStepField`, `addModuleStep`, `loadModule`, and `saveModule`.
  Generic agent catalog drops must not become arbitrary owner-operation calls.
  Route outcomes must come from the operation catalog, not `next_stage:*`
  conditions intended for the outer orchestration graph. Keep outer graph
  behavior unchanged. On migrated modules the old internal step list is not a
  second editable source; operation controls belong to the existing inspector.
- [x] Reload backend changes through existing refresh route while protecting dirty drafts; event/status mapping uses graph revision/node IDs and current invocation, no phantom done markers.

  `loadModule` currently overwrites dirty same-module drafts; guard that path
  explicitly. `moduleTraceEventsForStage` currently falls back to other runs;
  migrated executable graphs must not use that fallback. `consumeRuntimeEvent`
  and `loadRecentEvents` must map actual execution events, including after a
  page refresh, without painting a different revision or prior invocation.
- [x] Render SVG from explicit executable edges with honest kind/outcome legend and composite labels. Keep five-area grouping without fake stage nodes.

  Orchestrator has several explicit outcomes between the same node pair. Do not
  silently deduplicate them into one transition; keep each route editable and
  its selected execution outcome distinguishable. Avoid stacked unreadable
  outcome labels in the SVG/canvas.
- [x] Run Node tests, focused Python projection/API tests, and intercepted actual IDE Playwright fixture at desktop and narrow viewport. Exercise route edit/serialize/backend execute, backend update/reload, label/drag and invalid draft. No operating service or external network; in-process API bootstrap only behind denied-effects fixtures.
- [x] Update Design/ORC docs, Runtime IDE reference, governing modularization contract, generated SVGs and Wiki hashes. State structural dry-run vs execution evidence, actual nodes/composite bounds, and no hardware validation.
- [x] Self-review and report covering commands and screenshot paths outside repository; leave code uncommitted for review.

### Task 3: Integration acceptance and non-actuating loop verification

**Files:** Focused tests and evidence sections of this plan; no unrelated runtime changes.

- [x] Independently verify baseline-equivalent original agent outcomes, explicit routing and frontend/backend round trip across existing module API.
- [x] Run `tests/integration/test_orchestrator_setup_loop.py`, `tests/integration/test_all_agent_loop_archives.py`, relevant execution-profile matrix and focused LangGraph tests with existing denied transport fixtures.
- [x] Validate changed docs and generated SVG parity; inspect actual screenshots, not just DOM assertions. Report any old suite failures separately from regressions introduced here.
- [x] Obtain scoped task and whole-change review. Fix Critical/Important issues through implementer, rerun covering tests. Preserve previous dirty changes and do not commit/push.

## Verification Record — 2026-09-13

These are overlapping engineering checks, not an aggregate test count or live
hardware/provider validation. All application integration uses denied-effects
fixtures, temporary roots and controlled provider responses.

| Scope | Result | Evidence boundary |
|---|---|---|
| Executable graphs, owners, module API, lifecycle, original-result comparison and mode profiles | 116 passed | Includes six frozen pre-migration result comparisons and five guarded profile cases |
| Existing LangGraph runtime | 70 passed | `tests/unit/test_langgraph_runtime.py`; legacy overrides and stage/approval behavior retained |
| Existing Setup, downstream cycle and loop archives | 54 passed | `test_orchestrator_setup_loop.py` and `test_all_agent_loop_archives.py`; no physical effects |
| Frontend projection, editing and asynchronous ownership | 19 passed | Node checks include both response orders, new edits during PUT/GET, tab switches and late old execution events |
| Module API, SVG parity and actual-asset browser | 11 passed | Desktop 1600×1100 and narrow 700×1100; real guarded API and owner functions, not an operating server |
| Publication, Wiki and knowledge workspace | 62 passed | Final rerun after updating source hashes for the agent docs and documentation index |
| Changed references, contracts, plan and index | 8 documents passed | Targeted documentation validation; generated SVGs separately checked for parity |

The browser changed Orchestrator's independent preparation route and saved it
through the existing API. Real owner operation starts then followed
`plan → mission → decide → report`. Reload reflected a backend definition edit,
while newer local drafts survived delayed responses. Design's accepted/review
branches, empty invalid drafts, retained invocation scopes and heading/label
separation were also checked.

Scoped and final whole-change reviews approved the implementation with no
remaining Critical, Important or Minor findings. Existing Pydantic and
FastAPI/Starlette deprecation warnings remain. The repository-wide document
validator still reports pre-existing format errors in unchanged
`windows_pyautogui_bridge.md` and `2026-08-24-plc-safety-bridge-design.md`; these
are outside this change and were not rewritten.

Implementation and review were completed in the existing working tree before
publication was requested. No operating service was restarted, and no hardware
call or live-model validation was performed. The subsequent publication includes
the Design modularization, shared executable IDE contract and governing design
update under the `Agent-Modularization` tag.
