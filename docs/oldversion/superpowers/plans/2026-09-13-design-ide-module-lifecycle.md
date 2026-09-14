---
doc_type: plan
subtype: implementation
status: archived
authority: execution
audience: [developer, maintainer]
scope: [design_agent, graph_module_lifecycle, frontend_backend_ownership]
summary: Complete Design's graph-applied add/remove/re-add lifecycle across execution, GUI and owner discovery.
execution_status: completed
governing_design: docs/oldversion/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs: [docs/agents/design_agent.md]
supersedes: []
---

> Archived development history (2026-09-14). Not the current implementation or acceptance contract. See the [archive index](../../README.md) for current references.


# Design IDE Module Lifecycle Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the independent frontend task and review. Keep current checkout; no commits, pushes, hardware or operating service/model restarts.

**Goal:** Applied Runtime IDE graph membership controls Design execution access, owner/setup discovery and Live GUI attachment, with reversible removal and unchanged experimental algorithms.

**Architecture:** Reuse the graph-linked OwnerCatalog and AgentRegistry. Installed code remains discoverable as a catalog; active bindings are a projection of the applied graph, not a second persistent list. Existing save/validate/activate and running guards remain authoritative. A common browser module host loads code-owned frontend declarations for active manifests.

**Tech Stack:** Existing Python/FastAPI/GraphConfig, plain JS, pytest, Node and isolated browser fixtures.

**Spec:** [Module boundaries](../specs/2026-09-13-package-agent-bridge-modularization-design.md). The user explicitly approved the graph-application lifecycle, not mere folder separation.

## Global Constraints

- Preserve Design's calculations, LLM/tool behavior, artifact paths, mode policies and existing handoffs.
- Add/remove means applied graph change through existing validation/activation, not opening/closing an editor tab. Do not bypass graph validity or invent experiment transitions.
- Core Orchestrator/Objective remain. Preserve past files, inactive settings and shared bridge resources. Installed module code is not uninstalled on graph exclusion.
- Running activation is rejected by existing guards; no midway graph switch. No real equipment, camera, network/model or subprocess actuation in lifecycle integration tests.
- No arbitrary Python import from YAML and no browser code execution from editable UI YAML. Frontend executable metadata comes from installed code only.
- No new editable Design setup fields; expose only actual owner-supported settings.

## Task 1: Applied-graph backend ownership

Files: `agents/registry.py`, `agents/module_contract.py`, new `agents/module_discovery.py`, `agents/design/module.py`, `agents/orchestrator_capabilities.py`, `app/bootstrap.py`, `app/controller.py`, `app/main.py`; tests in `tests/unit/test_design_module.py` and `tests/integration/test_design_module_lifecycle.py`.

Interfaces:

```python
discover_agent_modules()  # trusted agents/*/module.py exporting MODULE
registry.bind_activation(provider)  # provider() -> set of active agent names
registry.active_names()  # names admitted by graph membership; names() remains installed catalog
registry.module_for_agent(agent_name)  # optional code declaration
catalog.bindings()  # detached current graph-linked owner rows
```

- [x] Write failing registry behavior tests: excluded Design get raises, restored Design retains the original instance, unrelated legacy agents stay compatible; catalog names remain available for graph re-add validation.
- [x] Add trusted code discovery and generic bootstrap registration; preserve legacy imports and `DESIGN_MODULE`, export `MODULE` alias.
- [x] Reuse OwnerCatalog binding resolution for installed-module activation. Connect the controller registry resolver without invoking tools or creating a second saved activation list.
- [x] Filter runtime manifests and current agent list by actual graph bindings; preserve Objective/Orchestrator. Resolve code metadata by effective handler, not a conflicting module ID.
- [x] Return frontend metadata in `implementation.frontend`: existing `asset_url`, plus `namespace: AX4LABDesignUI`, `factory: createFrontend`. Serve generic code-owned module assets; current inactive access is not an executable API. Existing module catalog/load/unload editor semantics stay intact.
- [x] Current inactive Design report/message/direct planning entry rejects or reports inactive; history files remain queryable. Setup/ORC owner discovery uses the same graph and module root.
- [x] Verify save-without-activate does not change membership, invalid activation changes nothing, busy activation rejects, successful graph activation removes/re-adds Design consistently. No real graph/config writes: fixture roots only.

## Task 2: Manifest-driven frontend lifecycle and Design ownership

Files owned exclusively by worker: `web/static/planning.js`, `web/templates/planning.html`, new `web/static/agent_module_host.js`, `agents/design/frontend/live_report.js`, `graphs/modules/design/ui.yaml`, JS tests/fixtures and affected Python JS harness tests. Do not edit backend or docs.

Backend interface: `/api/runtime/agent-manifests` returns active graph agents only, with core Objective/Orchestrator. Each installed agent's `implementation.frontend` carries code-owned `asset_url`, `namespace`, `factory`. Design values are `/module-assets/design/live_report.js`, `AX4LABDesignUI`, `createFrontend`; use implementation version as cache key. Existing application serves that module asset. An agent/module ID is not an executable JS expression.

```javascript
// Common host reconciles only authoritative active manifests.
await moduleHost.reconcile(manifests, hostServices);
moduleHost.get(agentId); // frontend instance, or null when inactive/not ready
// Factory API exported by Design module:
window.AX4LABDesignUI.createFrontend(hostServices);
// returns renderDashboard(report,status,label,profile), renderReport(report), dispose()
```

- [x] Write failing behavior tests for active add/remove/re-add, removal during asset load, repeated refresh, failed/foreign asset URL and preservation of valid zero vs missing values.
- [x] Remove unconditional Design script loading and eager `window.AX4LABDesignUI` access. Load the common host only; cache-bust changed host assets.
- [x] Reconcile modules on existing manifest refresh before rendering; stale async loads cannot remount a removed agent. Detach frontend instance and subscriptions on exclusion; repeated reconciliation is idempotent.
- [x] Boot visible agent list with core only until a valid manifest arrives. Do not resurrect removed agents through DEFAULT list, node-test choices or failed refresh. Preserve last valid manifest on transient failure.
- [x] Add generic `module` renderer dispatch. Move Design dashboard/report composition into the Design frontend factory, retaining legacy exported pure helpers and shared STL/Specimen helpers in core with explicit dependency injection. Do not duplicate unrelated renderers or redesign cards.
- [x] Use existing polling/re-render path to refresh membership after IDE activation; add no duplicate background interval. Updated Design `ui.yaml` may select the common `module` renderer. Parent will admit `module` in backend UI profile allowlist.
- [x] Verify Node unit tests, existing affected JS harness tests, and isolated browser DOM fixture. Report exact host dependency boundary, test results and risks to parent. No commits/subagents/device calls or service restarts.

## Task 3: Lifecycle integration and compatibility handoff

Files: lifecycle tests, existing Design/module API tests, relevant docs and Wiki freshness metadata.

- [x] Exercise real IDE graph save/activate using isolated roots and forbidden physical boundaries. Assert Design across agent list, manifest, owner catalog, registry execution, current report and asset loading, then restored after re-add.
- [x] Check historical archive sentinel files unchanged; verify draft, rejection and busy cases produce no partial change.
- [x] Run existing non-actuating orchestration/profile/tail and all-agent archive tests, focused LangGraph compatibility and Basic Tests selection. Keep synthetic provider responses clearly distinguished from live model evaluation.
- [x] Independent review of scoped changes; resolve concrete regressions and rerun affected checks.
- [x] Update Design docs and governing design with achieved lifecycle and limits. Report only verified scope; no physical proof, uninstall, marketplace or full Bridge migration claims.

## IDE Addition and Review Resolutions

The existing Validate/Compile response now includes a read-only `module_lifecycle`
preview. The IDE renders applied/draft owner sets, additions/removals, retained
history/settings and the running-activation restriction. Save Version still uses
the original graph validator and activation route; no automatic bypass edges
or new persistent membership list were introduced.

Independent review identified and resolved three boundary cases:

- Pre-execution-only owners now receive their installed frontend and retain a
  canonical report stage, separate from the host node's `graph_stage`.
- Attached generated/presentation modules remain visible without borrowing an
  unrelated installed agent implementation. Unattached drafts remain available
  in Module Management, including UI preview responses, but not the Live list.
- Overlapping frontend reconciliation cannot remount an older removed module;
  immediate add/remove and asynchronous disposal are regression-tested.
  Out-of-order manifest HTTP responses are also superseded before updating the
  active list, rendering, or error state.

## Verification — 2026-09-13

| Check | Result and scope |
|---|---|
| Design/module/API/IDE lifecycle focused suites | 27 passed; isolated graph roots, original in-process APIs, no external effects |
| Existing Basic Tests selection plus Design decision/frontend helpers | 92 passed |
| Existing orchestration mode/tail and all-agent archive suites | 54 passed in 169.77 s; virtual/installed-printer/physical-print policy paths use denied physical boundaries and simulated transport |
| LangGraph compatibility | 9 passed; compile, pre-execution, handler overrides, routing and failure paths |
| Module catalog/template and manifest compatibility | 2 passed; unattached draft editing preserved without Live attachment |
| Wiki-focused workspace checks | 17 passed |
| Browser host and Design Node contracts | Passed; idempotency, async races, missing-vs-zero and report factory |
| Isolated Chromium DOM fixture | `data-rendered=true`; active, zero value, removal and re-addition verified |
| Original Design algorithms | Executable AST unchanged after normalizing module documentation and moved import path |
| Independent review | All identified critical/important issues resolved |

Primary focused command:

```bash
.venv/bin/python -m pytest tests/unit/test_design_module.py tests/unit/test_ide_module_lifecycle_js.py tests/integration/test_design_module_api.py tests/integration/test_design_module_lifecycle.py -q
.venv/bin/python -m pytest tests/integration/test_orchestrator_setup_loop.py tests/integration/test_all_agent_loop_archives.py -q
node tests/js/agent_module_host.test.cjs
node tests/js/design_live_report.test.cjs
```

The browser fixture is `tests/js/fixtures/agent_module_lifecycle.html`; it loads
local files without an application server. Neither this fixture nor synthetic
provider replies are physical validation or a new live-model evaluation.

Repository-wide checks are not claimed fully green. The broader Live GUI suite
reported 110 passed and three out-of-scope failures:
`test_live_gui_analysis_report_exposes_multifidelity_contract`,
`test_live_gui_operator_reply_is_recorded_as_runtime_trace_event`, and
`test_live_gui_operator_reply_separates_target_agent_from_selected_context`.
The documentation validator retains existing Windows PyAutoGUI Reference
section/metadata issues and the PLC design front-matter issue; it reported no
new errors for the documents changed here. These are not corrected by this
Design/IDE change.

No operating server, model configuration, device, committed version or remote
branch was changed. Retained files were checked; exclusion is not uninstallation.

## Follow-up: Five-area Editable Runtime IDE — 2026-09-13

Design and Orchestrator now use responsibility grouping on the existing editable
canvas, not a separate architecture-view toggle. Shared module metadata supplies
area membership, concise captions, actual LLM decision markers and explicit
empty roles. Document SVGs use the same presentation renderer. The next-agent
modularization acceptance contract includes this structure and visual QA.

Original checkpoint IDs, handlers and routing are unchanged. New/ID-renamed
unmapped checkpoints remain editable as Unassigned; saved label edits override
default captions. Drag positions persist through the existing editor. The legend
uses text plus solid/dashed/dotted relations without replacing runtime status
highlighting. Fit includes empty responsibility regions. Long labels retain the
76 px node geometry used by ports and connections.

| Check | Result and scope |
|---|---|
| Module, API, lifecycle and control-view suites | 34 passed; original in-process APIs and isolated transports |
| Focused LangGraph compatibility | 8 passed; compilation, pre-execution, handler dispatch, traces and failure handling |
| Pure Node presentation contract | Passed; identities, order, escaping, Unassigned and authored labels |
| Wiki-focused workspace checks | 17 passed; refreshed Design/Orchestrator source hashes |
| Changed canonical document validation | Five documents passed; shared generated SVG parity also passed |
| Chromium visual fixture | Actual IDE HTML/CSS/JS; Design 13 nodes and Orchestrator 12 nodes, five areas and one declared LLM marker each |
| Browser interactions | Selection, dragging, edited labels, adding steps, and 76 px long-label geometry passed; no page/console errors |
| Viewports | 1600 × 1100 desktop and 390 × 844 narrow viewport; narrow canvas scroll verified |

Browser plugin was not available; installed Playwright/Chromium ran an intercepted
`http://fixture.invalid/ide` fixture. Application boot and all external transport
were disabled. Screenshots and the temporary browser harness stayed outside the
repository. This checks rendered editing, not live-run execution or fresh model
responses. No operating server restart, hardware command, commit or push occurred.

```bash
.venv/bin/python -m pytest tests/unit/test_module_control_views.py tests/unit/test_ide_module_lifecycle_js.py tests/unit/test_design_module.py tests/integration/test_design_module_api.py tests/integration/test_design_module_lifecycle.py -q
node tests/js/module_control_view.test.cjs
.venv/bin/python scripts/render_module_control_views.py
```
