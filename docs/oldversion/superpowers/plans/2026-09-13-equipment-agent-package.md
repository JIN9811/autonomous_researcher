

> Archived development history (2026-09-14). Not the current implementation or acceptance contract. See the [archive index](../../README.md) for current references.
# Lab Equipment Agent Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved installed Agent/Device Bridge package contract to Lab Equipment without changing its existing experiment workflow.

**Architecture:** Keep the existing LabEquipmentAgent task as one Middle composite and expose its existing High decisions, Low worker boundary, and cross-cutting checks/evidence through source-bound CODE relationships. Reuse module discovery, execution graphs, package discovery, report composition and the existing IDE canvas. Windows and Local worker selection remains the responsibility of the same equipment bridge.

**Tech Stack:** Python, existing AgentModule/BridgeModule contracts, FastAPI, YAML, plain JavaScript and the shared SVG renderer.

**Spec:** `docs/oldversion/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md`; `docs/oldversion/superpowers/specs/2026-09-13-executable-agent-ide-contract-design.md`.

## Global Constraints

- Modularization only: preserve original tool IDs, payloads, result shape, profile selection, stacked Flow ordering, admission, stop/cancel, terminal LLM review, recovery budgets, duplicate-success suppression and downstream clearance/vision/analysis handoffs.
- High is agent-local LLM reasoning; Middle is software/API/composite processing; Low is device/bridge execution. Guardian/Safety and Knowledge/Evidence are cross-cutting. Do not split a composite merely to populate five areas.
- Package is a composition contract, not a device. IDE displays Agent Package → Device Bridge, then actual internal components using the existing renderer, canvas, ports, labels, legend and Inspector.
- Keep bridge implementation under `device_bridges/`; use one `windows_pyautogui@1.0.0` bridge for the existing Windows/Local transport paths, not separate provider packages.
- Preserve old imports as exact module-identity aliases, including monkeypatch behavior. Preserve existing configuration, repository-root anchors, API URLs, Workspace assets and storage paths.
- Work in the current checkout as requested. Do not restart the operating server, invoke hardware, install/start/stop models, modify private settings or publish validation artifacts. Complete independent review before publication; the prior package has already been committed/tagged/pushed.
- Use `.venv/bin/python` and guarded tests. Actual-model cycle uses the registered ATR provider with device I/O replaced; deterministic fixtures do not count as live LLM validation.
- Keep validation evidence in this plan's ignored `.superpowers/sdd/2026-09-13-equipment-agent-package/` directory. Public documentation is English and distinguishes software verification from prior physical proof.

## Task 1: Canonical owner, bridge and package contracts

**Files:**
- Create `agents/equipment/{__init__,agent,decision,workflow,module,execution,structure,presentation}.py`.
- Convert `agents/equipment_agent.py`, `agents/equipment_decision.py`, `agents/equipment_workflow.py` to exact compatibility aliases.
- Create `device_bridges/windows_pyautogui/{__init__,bridge,tools,module}.py`, `README.md`, `requirements.txt`; alias `device_bridges/windows_pyautogui_bridge.py` and `mcp_tools/equipment_tools.py`.
- Update `app/bootstrap.py`, `app/main.py` report projection only, `graphs/modules/equipment/module.yaml`, `packages/service.py`, packaging declarations if explicitly enumerated.
- Create `packages/agents/equipment/package.yaml` and `README.md`.
- Add `tests/unit/test_equipment_module_contract.py`, `tests/unit/test_windows_equipment_module_contract.py`; extend `tests/integration/test_packages_api.py` and graph API coverage where needed.

**Interfaces:**
- Consume `AgentModule`, `BridgeModule`, `ExecutionCatalog`, `ExecutionOperation`, `OperationResult`, `compile_execution_graph`, `run_execution_graph`, existing module discovery/registration.
- Produce `agents.equipment.module.MODULE`, owner `equipment_agent`, module/package `equipment@1.0.0`; `device_bridges.windows_pyautogui.module.MODULE` declares `windows_pyautogui@1.0.0`.
- Produce `LabEquipmentAgent.execution_catalog()`, `default_equipment_execution_graph()`, `execute_equipment_graph(agent, state, ctx, *, graph=None, emit=None, invocation=None)`, `project_equipment_report(metadata, agent_payload)` and `REPORT_PROFILE` matching the existing report payload.
- Graph operations are `equipment.task` (Middle composite, `llm=True`, produces `task_result`) and `equipment.deliver` (Middle, requires `task_result`, produces `agent_result`); required terminal output is `agent_result`.

- [x] Add RED consumer tests before implementation: discovery contains equipment; old/new module identities match; profile/root paths remain repository-local; package resolves the installed bridge once; tool IDs/queue names stay unchanged.

```python
def test_equipment_identity_and_discovery():
    import importlib
    from agents.module_discovery import discover_agent_modules
    assert 'equipment' in {m.module_id for m in discover_agent_modules()}
    assert importlib.import_module('agents.equipment_agent') is importlib.import_module('agents.equipment.agent')
```

- [x] Run the new focused test and record its expected missing-module assertion failure.
- [x] Move existing owner/decision/workflow and bridge/tool bodies mechanically, updating only import references and `__file__` parent depth. Keep legacy aliases exactly as the existing Manipulation package does. Compare ASTs against baseline `7af7978` and record allowed differences.
- [x] Wrap the unchanged former owner `run` body as `_run_task`; keep the archive decorator only on public `run`. Reuse the Manipulation execution wrapper pattern. Set `scope['task_started'] = True` before awaiting the task; reject repeated task nodes before a second workflow effect. Delivery must return the same real AgentResult, including blocked/error outcomes.

```python
async def task(state, ctx, scope, config):
    if scope.get('task_started'):
        raise ExecutionGraphError('Equipment task cannot repeat within an invocation')
    scope['task_started'] = True
    return OperationResult('next', {'task_result': await agent._run_task(state, ctx)})
```

- [x] Add source-bound implementation relationships for actual suitability/terminal-review LLM calls, stacked Flow supervisor, runtime service, selected worker calls, admission/recovery checks and CSV/handoff evidence. Retain the configured `workflow_agentic_tasks`, Flow data and existing mandatory guards. CODE nodes are descriptive, not extra execution.
- [x] Register the owner through discovered modules once; remove only its duplicate explicit registration. Declare the existing bridge tool registration and runtime aliases using IDs actually returned by existing catalog code. Include existing local worker/server source, workspace templates/assets, profiles/skills/runtime references in ownership declarations without relocating those shared services or deploying a new server.
- [x] Move the existing Equipment report profile and projection branch into `presentation.py`; use the existing generic host projector. Do not add a second runtime query/store or alter precedence/keys.
- [x] Test equivalent original-body vs graph results and tool order for virtual, blocked, preflight, completed/repeated and failure paths using existing fixtures; verify unknown graph operations/missing delivery/duplicate task fail before extra effects. Test trace invocation isolation and API graph round-trip.
- [x] Run focused tests plus existing equipment decision/workflow/profile/runtime suites under the verification guard. Record exact failures separately; do not weaken production or fixtures to hide them. Leave changes uncommitted and write the task report with RED/GREEN evidence.

## Task 2: Owned Live composition, IDE and documentation

**Files:**
- Create `agents/equipment/frontend/live_report.js`, `graphs/modules/equipment/ui.yaml`, `tests/js/equipment_frontend.test.cjs`, `tests/integration/test_equipment_module_api.py`.
- Update `tests/unit/test_control_area_semantics.py` and `tests/unit/test_module_control_views.py` to consume the installed Equipment catalog instead of the legacy checkpoint fixture.
- Update `agents/equipment/module.py`, `web/static/planning.js`, `scripts/render_module_control_views.py`; generic IDE changes only if an actual contract integration gap is demonstrated.
- Update `docs/agents/equipment_agent.md`, agent index/API matrix, `docs/device_bridges/windows_pyautogui_bridge.md`, bridge index/API matrix, Runtime IDE reference and the two linked modularization/execution specs.
- Generate `docs/agents/assets/figures/equipment_control_areas.svg` using the existing light document renderer.

**Interfaces:**
- Consume Task 1's owner projector/descriptor, execution catalog and package/bridge declarations.
- Produce `/module-assets/equipment/live_report.js`, `window.AX4LABEquipmentUI.createFrontend(host)` with `renderReport`, `renderDashboard`, `dispose`, following the existing module frontend lifecycle.
- Preserve existing Equipment card IDs, controls, event delegation, process-driven refresh and report API. Host retains common polling and current equipment process/state synchronization.

- [x] Add RED API/Node tests: module assets admitted only for an installed owner; inactive owner renders no current cards; report projection retains existing evidence; existing Equipment dashboard cards/actions are present with correct IDs.
- [x] Move only Equipment-specific report/dashboard composition to its frontend factory. Pass existing host helpers explicitly, keep shared freshness/polling/action functions in the host, and do not create timers/listeners in the renderer. Declare the same existing cards in `ui.yaml`.

```javascript
(function (global) {
  function createFrontend(host) {
    // Existing owner composition moves here with its original helper inputs.
    return Object.freeze({renderReport, renderDashboard, dispose});
  }
  global.AX4LABEquipmentUI = Object.freeze({createFrontend});
})(window);
```

- [x] Extend generic document rendering to the Equipment execution catalog; verify real source symbols/edges and generated SVG equality. In the IDE, use Package → Windows/PyAutoGUI → existing transport/runtime components, not a new management layout.
- [x] Run focused Node and API tests, including existing Equipment progress refresh, task/Flow model and selection suites. Reuse guarded API fixtures and temporary roots; no user server restart.
- [x] Update Status at a Glance, ownership/layout, APIs/tools/storage and verification sections. Retain prior physical-proof provenance. Public verification summary includes only actually observed results; raw logs stay ignored.
- [x] Update the modularization and executable-IDE specs with implemented Equipment scope and exact limitations. Validate changed documentation and local links. Leave changes uncommitted and report results.

## Final Verification (controller)

- [x] Run guarded original-mode/hybrid route suites after backend changes are frozen.
- [x] Run the registered-model cycle with `AX4LAB_VERIFY_REGISTERED_MODEL_CYCLE=1 .venv/bin/python -m pytest tests/integration/test_specimen_registered_model_cycle.py -q -s` and isolated `--basetemp` paths. Attempt 1 stopped on the Knowledge contract; unchanged attempt 2 (`api-cycle-check-2`) confirmed actual model calls, completed next Design, zero physical calls and no denied effects. Retain both outcomes.
- [x] Inspect the temporary guarded UI at 1920×1080: Equipment internal relationships and Inspector, package/bridge internals, original Live cards and module lifecycle. Never operate real controls. Stop only the assistant-owned temporary helper afterward.
- [x] Complete fresh task reviews and final cross-boundary review; resolve important findings and record verification results here. Check diff/publication boundary. Do not push this next package without a new publish instruction.

## Verification Record

Implemented against baseline `7af7978ad28c3f7980480bb67eeb58b1478af7ff`; both independent task reviews and the final cross-boundary review approved the change with no Critical or Important findings. Publication was subsequently authorized under `Lab-Equipment-Agent-Modularization`, including the agreed `LLM` / `LLM call` display and documentation clarification.

| Boundary | Observed verification |
|---|---|
| Owner / bridge preservation | Five normalized runtime ASTs match the baseline after documented relocation, registration and graph-wrapper changes; exact legacy module aliases retained |
| Backend and runtime | 285 guarded owner/bridge/API tests, 86 guarded runtime/Skill tests, and one separately executed pure multiprocessing serialization test passed |
| Original modes / hybrid handoffs | 49 guarded tests passed in 249.20 s |
| Installed frontend | 38 Equipment Node tests, 19 IDE editor tests, 69 API/control-view tests, and 16 selected Live/host checks passed |
| Final combined checks | 88 owner/bridge/API/control tests passed in 6.74 s; 57 combined Equipment/IDE Node tests passed; publication boundary accepted all 56 changed/new files |
| Registered-model virtual cycle | Unchanged second attempt passed in 470.15 s: 34 actual saved-provider calls across ten owners, BO/Guardian and next Design completed; physical calls 0, denied effects empty |
| Model reliability limit | First attempt completed Equipment and Analysis but Knowledge supplied an invalid tool sequence; Guardian blocked before BO. Both attempts are retained; no model, prompt, fixture or gate change was made between them |
| Browser | At 1920×1080: existing five-area Equipment map, separate Skill Flow workspace, Package → Bridge → internals, original Live cards and owner-selection lifecycle confirmed; final console errors/warnings empty |
| Documentation | Generated Equipment SVG is deterministic; legacy documentation-format failures remain recorded separately from changed-link and source-path validation |

The frontend verification caught and corrected a catalog-tab/Skill-Flow replacement bug and an extraction error involving the adjacent shared Analysis FEM polling helper. The shared helper was restored unchanged, regressions cover both cases, and corrected asset cache versions were verified in the browser. No equipment was actuated; the user's operating server, private settings and model services were not changed. Temporary guarded UI helpers were stopped with zero physical calls and no denied effects. Raw evidence remains in the ignored plan-specific validation directory, not in published knowledge or documentation assets.
