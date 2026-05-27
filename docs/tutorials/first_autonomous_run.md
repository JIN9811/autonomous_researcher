# First Autonomous Run

This tutorial validates the end-to-end system without requiring immediate
hardware writes.

## Goal

Run one autonomous specimen workflow through:

`Main GUI -> Live GUI -> Orchestrator -> active LangGraph route -> Stage Agents -> Autonomous Experiment Runtime / Device Bridges -> Guardian`

## Preconditions

- Repository installed at `/home/jin/autonomous_researcher`.
- Python environment installed with `pip install -r requirements.txt`.
- `atr` launcher installed with `bash install/install_cli.sh`.
- Inference model loaded manually from the GUI or CLI.
- For live PrusaLink use, `memory/prusa_connection.json` contains the current
  host and auth fields.
- For test-only validation, real hardware is not required.

## Start Server

```bash
atr up
```

Open:

```text
http://localhost:7860
```

To stop:

```bash
atr down
```

## Test Run From Main GUI

1. Confirm inference backend is `NemoClaw / vLLM` or the intended backend.
2. Load the required model manually.
3. Select `Test` mode.
4. Press `Start`.
5. Watch the event stream until `complete` or a structured error appears.

Expected behavior:

- Design Agent creates a gyroid/FDM-compatible specimen candidate.
- Specimen Making Agent generates STL/handoff artifacts.
- `experiment.evaluate` wraps printer preparation.
- `printer.prepare` returns a queued result with `job_id`.
- Guardian validates the result.

## Live GUI Test-Mode Print Path

Open Live GUI and type one of the supported phrases:

```text
테스트 모드, 가상 브릿지
테스트 모드, 설치 프린터
테스트 모드, 실제 출력
```

Expected routing:

- `가상 브릿지`: virtual PrusaLink path after slicing.
- `설치 프린터`: real PrusaLink communication check with live gates.
- `실제 출력`: test-generated specimen can be physically uploaded/started if
  live gates and connection info allow it.

## Live Run

In Live GUI, discuss the specimen requirements with the orchestrator. When the
design inputs are complete, send the configured execution trigger such as:

```text
실험 수행
```

Expected behavior:

- The orchestrator announces handoff.
- Design Agent produces the candidate.
- Specimen Making Agent shows slicer and printer bridge steps.
- The unified experiment result appears under `experiment_evaluation`.
- Device job metadata is attached to the printer result.

## Verify Queue State

The queue can be checked through the tool layer:

```python
ctx.tools.call("experiment.queue.status", {})
```

For API/debugging, inspect recent logs under:

```text
runs/<run-id>/
```

## Recovery Rules

- If the model is not loaded, load it manually and retry. Server startup does
  not auto-prewarm vLLM.
- If PrusaLink connection info is missing, edit `memory/prusa_connection.json`
  and retry from the same specimen step.
- If a hardware job is already active, wait for completion or use the relevant
  device stop/clear control.
- Do not bypass live gates in code to force physical action.

## Inspect Runtime Trace

Open the Runtime IDE after a test or live run:

```text
http://localhost:7860/ide
```

Use the bottom dock to audit the run:

1. Select a `Run Timeline` event or press `Inspect` on a runtime row in `Event Log`, then confirm the detail card shows the event-local stage, node, handler, module, payload, and state snapshot. The operator decision strip should summarize event status, runtime target, selected route/candidate count, replay basis, and related artifact count before the raw JSON blocks. For warning/error events, the remediation panel should show likely cause, impacted target, evidence, and recommended next actions. If the event carries an approval id, press `Focus Approval Queue` and confirm the matching pending approval item is highlighted before approving or rejecting it. After approval resolution, confirm the same selected event remains open and the remediation card shows the resolved decision instead of a pending queue action.
2. Press `Focus Node` to jump the canvas and inspector to the node that produced the event.
3. Press `Replay From Stage` to run a dry-run preview from the selected event stage before changing live graph behavior. Confirm the Replay Preview validation panel reports whether stage, route, handler, and dry-run compile status match the selected event before trusting the replay sequence.
4. Press `Related Artifacts` to list files linked to the selected event. Preview text/image artifacts inline, or download other file types.
5. From `Artifact Lineage` or `Artifact Preview`, confirm the provenance strip shows producer stage, handler, artifact type, preview mode, and replay status. Use `Trace Event` to return from a file back to the timeline event that referenced it, or `Replay Producer Stage` to dry-run from the stage that produced the artifact.
6. If you used a direct BO or CAE workspace control, confirm the same run shows workspace artifacts: BO should include a result JSON and BO progress SVG under `workspace/bo/`; CAE should include result JSON plus copied contour/report files under `workspace/cae/`. These must appear in Runtime IDE artifact lineage even though the action was launched from a dedicated workspace rather than the main closed-loop graph. To regression-check this path with a browser, run `python3 tests/ui/runtime_ide_browser_audit.py --base-url http://127.0.0.1:7860 --webdriver-url http://127.0.0.1:4448 --scenario workspace-artifacts`.

Expected behavior: timeline stage labels should follow event-local `node_id` / payload stage metadata, not only the latest global run state. For example, an Analysis event should remain labeled `analysis` even if the current run state has returned to `idle`. Workspace artifacts should be grouped by producer stage (`bo`, `analysis`, `specimen`, `manipulation`, or `equipment`) rather than one undifferentiated workspace bucket.


## Extend Runtime Modules From GUI Or CUI

Runtime IDE and `atr` use the same module store:

```text
graphs/modules/<module-id>/module.yaml
memory/module_versions/<module-id>/
```

GUI path:

1. Open `/module-management` from the main GUI or directly in the browser.
2. Select an existing module from `Module Library`, or use `New Module Designer` to create one from a Python file.
3. Fill `Module ID` and `Label` if the inferred value is not suitable.
4. Leave `Category` blank when Gemma 31B should auto-classify it.
5. Keep `Execution Handler` as `runtime.step_complete` unless the module should reuse an existing allowlisted handler.
6. Press `Create + Load Module` for a new module, or select an existing module to inspect its active config.
7. In `Module Configuration Workspace`, edit handler/model/prompt/tool/safety settings and the `pre_execution` / `internal_graph` step cards.
8. Use `Add Checkpoint`, `Add Agent Step`, `Duplicate`, `Delete`, or drag the numbered handle to reorder steps within the same phase.
9. Press `Apply Draft`, then `Validate`, then `Dry Run`; the dry-run evidence should show exact step order, checkpoint/executable counts, and `Open Node` links for graph nodes affected by the module.
10. Press `Save Version` only after the preflight card reports the current draft is validated and dry-run.
11. If the module was created by Module Designer and shows pending generated registration, press `Register Generated` only after reviewing `handler.py`; this validates `async run(state, ctx)`, switches the active handler to `module.generated_adapter`, removes staging-only `runtime.step_complete` internal handlers, saves a version, then requires another validate/dry-run before live use.

CUI path:

```bash
atr modules
atr module show design
atr module validate design
atr module dry-run design
atr module create ./my_internal_module.py my_internal_module "My Internal Module"
atr module register-generated my_internal_module
```

Expected Module Designer behavior:

- Gemma 31B (`gemma4:31b`) converts the uploaded Python into an ATR adapter file.
- The adapter is saved as `graphs/modules/<module-id>/handler.py`.
- The original source is saved beside it for audit.
- The generated `module.yaml` contains category, handler, tool allowlist, safety metadata, IO contract, and internal step trace.
- If the generated Python is not yet registered in the runtime handler allowlist, the module is marked `pending_handler_registration` and uses `runtime.step_complete` until explicit approval.
- `Register Generated` / `atr module register-generated` is the approval step: it statically validates `handler.py`, sets `handler=module.generated_adapter`, clears `pending_handler_registration`, removes placeholder `runtime.step_complete` internal-step handlers, records a version, and lets the LangGraph runtime load the adapter wrapper on the next run.

Canvas and module editing rules:


Module configuration ownership:

- Use `/ide` for graph canvas, run launcher, readiness, timeline, artifacts, node inspector, and internal graph tab inspection.
- Use `/module-management` for module creation, load/unload workspace state, handler/model/prompt/tool/safety edits, pre/internal step edits, validation, dry-run, and module save/versioning. The Runtime IDE no longer presents a second visible module config editor.
- In Module Management, the `Module Configuration Workspace` is intentionally wide and summary-first: review the Summary, apply typed config edits, inspect Steps and Dry-run Evidence, then use Raw JSON only for advanced repair.

- The Runtime IDE opens graph-first: `Draft Safety Strip and Activation Checklist` and `Run Launcher` are compact drawers above the graph so the canvas remains visible. The Draft Safety Strip includes the current primary gate action, so operators can run validate, dry-run, save, or active-gate recording without searching through drawers. Open `Run Launcher` only when starting a saved active graph; the top summary must say `Saved active graph execution` and the final buttons read `Run Saved Test` or `Run Saved Live`. Saving an active graph now returns server-side dry-run evidence and records the matching live gate, so the saved version and run preflight refer to the same config digest. The Run Launcher target strip and disabled buttons should make it obvious whether the next click would execute the saved active graph or is blocked by unsaved editor changes. When a node shows a `readiness-warn` or `readiness-error` badge, click the corresponding Runtime Readiness issue row; handler/runtime issues focus Node Inspector, route issues focus Transition Editor with the current/baseline default target preselected when possible, and module issues focus the module tools entry point. Then use the Node Inspector `Runtime Recovery` card to inspect the latest issue, dry-run from that node, validate the draft, or jump to Module Management.
- The main graph auto-fits on initial load. Use `Fit Graph` again after dragging nodes or loading a graph version if the viewport coverage badge reports partial visibility.
- Node Inspector, Transition Editor, Run Timeline, Artifact Lineage, Replay Preview, and Event Log use internal scroll regions. Keep the graph visible and scroll inside the panel you are inspecting instead of scrolling the whole page whenever possible.
- Double-click an agent node on the Main System graph to open its internal graph tab. The Main System tab stays fixed; close internal tabs with `x` when done.
- Internal graph step labels are shortened for readability, for example `pre:orchestrator_plan` and `step:01_intake_constraints`; the full YAML ids remain unchanged in the draft config.
- Dragging an internal graph step changes that step's `metadata.position` in the module JSON draft and marks the tab/status as `Module Draft Changed`; validate and dry-run before saving the module version.
- With an internal module graph tab selected, use the main toolbar `Validate` or `Dry Run` buttons to check that module draft. The central `Dry-run Trace` panel should show module validation evidence or the ordered pre/internal step sequence before `Save Version`. The `Activation Checklist` also switches to module gates so you can see `Validate Module Draft`, `Dry-run Module Draft`, and `Save Module Version` state before pressing save. If the module draft was changed after those checks, `Save Version` is blocked until the current draft is validated and dry-run again. The save API also performs and returns a non-device dry-run summary, so a version record is tied to server-side evidence rather than only a browser-side check.
- Drag a Module Catalog item to `Main System` in `/ide` to add a graph node.
- Use Module Management graph-usage rows or dry-run evidence `Open Node` links to jump back to the affected Runtime IDE graph node.
- For operator workstations, use a 1920x1080 or larger browser window when editing graph routes. The Runtime IDE is expected to show the main graph canvas, node ports, and minimap in the first viewport; larger displays expand the canvas automatically.
- Drag from a node port to another node to add a logical transition candidate. If the source already has a default transition, the new arrow is saved as a candidate and does not overwrite the default route. Simple default routes render as clean arrows without repeated `default` labels; conditional routes and candidate routes keep labels, and multi-route nodes show a route-count badge.
- Use the Transition editor `Apply` action when you intentionally want to change the default `graph.transitions` route. The editor auto-selects the current default target for the selected source stage when possible.
- Use the route inventory in the preview panel to review every outgoing default/candidate route from the selected source stage before validating. Multiple candidate arrows from one node are runtime-active after validate/save; runtime events report `transition_candidates` and `selected_transition`.
- Edit internal module steps in `/module-management`; blank-handler internal steps are checkpoints, while explicit agent-step handlers execute before the module's main handler.
- Drag graph nodes from the Runtime IDE canvas to the bottom trash zone to remove them from the current graph draft.
- Always run `Apply Draft`, `Validate`, and `Dry Run` before `Save Version`.
