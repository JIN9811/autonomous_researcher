---
doc_type: reference
subtype: current_snapshot
status: active
authority: descriptive
audience:
  - developer
  - operator
  - maintainer
scope:
  - runtime
  - api
  - gui
  - knowledge
summary: Reproducible snapshot of the routes, graph, workspaces, and runtime contracts, including Knowledge relation reconciliation.
source_of_truth:
  - app/main.py
  - objectives/service.py
  - objectives/compiler.py
  - objectives/evaluator.py
  - graphs/configs/atr_closed_loop.yaml
  - orchestrator/langgraph_runtime.py
  - web/templates/knowledge.html
  - web/static/knowledge.js
last_verified: 2026-08-09
verified_against: 4329853
related_docs:
  - docs/runtime/langgraph_runtime.md
  - docs/runtime/closed_loop_and_pages_reference.md
  - docs/knowledge/knowledge_graph_operations.ko.md
supersedes: []
---

# Current Code Snapshot

## Summary

This Reference records the current routes, executable graph, module/runtime
contracts, workspace surfaces, and selected source-size checks. The Knowledge
relation reconciliation layer is verified against implementation commit
`4329853`. Counts are observations used to detect documentation drift,
not stability guarantees.

## Scope

The snapshot covers the checked-in FastAPI application, primary closed-loop
graph, module/manifest surface, device/workspace API groups, and Knowledge
workspace. It does not claim that optional live devices or external services
are available in every environment.

## Source of Truth

- `app/main.py`
- `graphs/configs/atr_closed_loop.yaml`
- `graphs/modules/*/module.yaml` and committed `ui.yaml` descriptors
- `orchestrator/langgraph_runtime.py`
- `web/templates/` and `web/static/`
- `knowledge/` and `scripts/knowledge_graph_cli.py`

## Knowledge Graph Runtime (2026-08-09)

- ATR Core Ontology `atr-core-1.0.0` is defined under `knowledge/ontology/` with class, relation domain/range, event-family, and lifecycle validation.
- `knowledge_event.v1` records use deterministic event/idempotency identifiers.
- `AuditLedger` performs append, flush, and fsync before `DurableOutbox` enqueue.
- `GraphSyncWorker` acknowledges an outbox event only after the repository returns a matching Neo4j event receipt.
- Neo4j outage preserves pending events and reports degraded state; the JSON graph remains a compatibility/import tool rather than a silent Neo4j fallback.
- Graph queries use allowlisted plans with depth <= 4 and limit <= 100; raw Cypher from LLM/GUI/API is rejected.
- Knowledge Agent adds `graph_event_status` without replacing `knowledge_context.v1`, `knowledge_report.v1`, or `evolution_proposal.v1`.
- Knowledge ledger events record cycle-level `collected`, `updated`, `retrieved`, and `used` activity; `/api/knowledge/activity` provides a bounded aggregation.
- Live GUI renders the recorded activity as a preserved paper-style histogram only while the Knowledge report is selected.
- `/knowledge` provides Graph Explorer, Memory, Ontology, Sync, Project Graph, and Relation Review views; Main GUI exposes it as a status-aware workspace card.
- `RelationStore` persists incremental work, immutable proposals, operator decisions, graph edit decisions, and drafts under `memory/knowledge/reconciliation/`.
- `KnowledgeReconciliationService` detects isolated/weakly connected nodes, ranks existing-node candidates, invokes the selected already-loaded LLM through the shared priority lease, validates ontology/provenance/duplicate constraints, and promotes accepted relations through `KnowledgeService.ingest`.
- Automatic promotion requires LLM confidence `>=0.90` and deterministic evidence `>=0.80` plus all structural gates. Other proposals stay in the operator queue.
- The 60-second background worker reports `model_unloaded` instead of loading a model and uses reconciliation priority `30`, below Guardian `0`, workflow `10`, and chat `20`.
- Graph Explorer defaults to View Mode. Edit Mode supports drafts over existing nodes/relations and allowlisted metadata only, with undo/redo, server validation, optimistic graph revision, and audited apply.
- Live GUI Knowledge report exposes compact persisted reconciliation metrics. ATT produces at most one aggregate pending-review item and does not block the experiment loop.

## Objective Compiler Runtime (2026-08-09)

- `objectives/metric_registry.py` exposes nine Analysis-produced metrics with
  units, source paths, valid ranges, fidelity, quality, and provenance rules.
- `objectives/compiler.py` accepts only the bounded declarative DSL. Python,
  shell, Cypher, arbitrary file paths, unknown metrics, incompatible units,
  and unbounded ASTs are rejected.
- `ObjectiveService` owns compose/revise, validate, preview, approve, activate,
  evaluate, compare, and status. A run binding is immutable by objective
  id/version/hash and survives process restart.
- Eleven `/api/objectives/*` routes and eleven `objective.*` ToolRegistry
  operations expose the same lifecycle without request-supplied code or
  storage roots.
- `/bo` contains the authoring/lifecycle workspace. `/live` exposes a compact
  read-only active-objective card and does not invoke an LLM during polling.
- Analysis evaluates the active expression, Knowledge persists its complete
  lineage, and BO accepts one deduplicated hash-matched observation per
  `observation_id`. Live BO rejects synthetic proxy scores.
- End-to-end regression covers invalid-unit rejection, nonlinear revision,
  preview/approval/activation, Analysis evaluation, Knowledge JSONL lineage,
  BO handoff, and score replay after service restart without an LLM.
- Operational endpoints also include `/api/knowledge/relations/*` review actions and `/api/knowledge/graph/edit/{validate,apply}` in addition to ontology, graph stats/activity/sync/query endpoints.

Last checked against the local source tree on 2026-08-09.

This document records what the current code exposes. It is not a target design
document. If this conflicts with an older guideline, the files below are the
implementation source of truth:

- `app/main.py`
- `graphs/configs/atr_closed_loop.yaml`
- `graphs/modules/*/module.yaml`
- `graphs/modules/*/ui.yaml`
- `web/templates/*`
- `web/static/*`

## 0. Snapshot Verification Summary

This snapshot was refreshed from the local code tree, not from an older design
package. The authoritative count below comes from importing `app.main.app` and
inspecting FastAPI `APIRoute` objects. A raw decorator grep can report a smaller
number because a few routes use multiline decorators or are registered by
FastAPI outside the simple `@app.<method>("...")` pattern.

The current FastAPI `APIRoute` scan finds:

```text
operator page paths: 16
favicon route entries: 2
API/artifact APIRoute entries: 328
total FastAPI APIRoute entries in app/main.py: 346
total app.routes entries including docs/openapi/static: 353
```

Machine-checked snapshot labels used by `docs/document_manifest.yaml`:

```text
FastAPI APIRoute count: 346
Total app.routes count: 353
Graph nodes: 19
Graph edges: 68
stage_dispatch edges: 12
```

The route count is a sanity check, not a stability contract. `APIRoute` entries
are the operational API/page endpoints; the extra non-APIRoute entries are
FastAPI's OpenAPI/docs routes plus the mounted static route. New routes may be
added, but documentation should keep the same grouping:

Current endpoint group count from the same scan:

```text
bo: 4
bridges: 2
cae: 3
equipment_windows: 25
events_runs: 30
evolution: 14
favicon: 2
graphs: 16
knowledge: 20
lerobot: 87
modules: 15
operator_pages: 15
other_api: 43
planning: 5
printer: 27
printer_artifacts: 3
runtime: 21
```

Current TestClient sanity checks from the same source tree report:

```text
GET /api/runtime/agent-manifests -> ok=true, count=11, graph=atr_closed_loop@0.2.0
GET /api/bridges -> ok=true, count=5
GET /api/modules/management-state -> ok=true, modules=10
GET /api/runtime/state -> ok=true, runtime_ide_contract.device_bridges present
GET /api/runtime/models -> managed models: gemma4:31b, gemma4:e4b-it-nvfp4
GET /api/printer/fleet -> active_profile_id=bambulab_x2d_lab_01, automatic_fallback=false
GET /api/graphs/atr_closed_loop -> ok=true, graph.nodes=19, graph.edges=68, graph.stage_dispatch=12
```

The descriptor-backed Live GUI examples are still Design, Equipment, and
Guardian. Their manifest entries expose `ui_path`, `cards[]`, and
`report_sections[]`, but their built-in reference dashboards keep precedence in
the main `/live` report so the established Design/Equipment/Guardian layouts
are not displaced by descriptor preview cards. Draft/custom/generic modules use
the descriptor cards and report sections directly in Live GUI preview. Modules
without `ui.yaml` keep the generic renderer.
Module-local `ui.renderer` is normalized as presentation metadata when present:
allowlisted ids are returned in each agent manifest as `renderer.dashboard`,
`renderer.report`, `renderer.fallback`, `renderer.supported`,
`renderer.execution_scope=presentation_only`, and `renderer.blocked_reason`.
This is a safe profile hint, not arbitrary JavaScript/plugin execution.
The current checked-in Design, Equipment, and Guardian `ui.yaml` examples do
not need a renderer profile; they exercise the descriptor-card/report-section
path. Renderer profile behavior is covered by targeted module-template tests.

`events_runs` contains `/api/run/*`, `/api/runs/*`, `/api/events/*`, and
`/api/approvals/*`. `other_api` contains app-state, Guardian, agent-report,
artifact, GPU, documentation-baseline, and compatibility endpoints that do not
fit the primary workspace prefixes.

Current source-size sanity check for the files most likely to drift with this
snapshot:

```text
app/main.py: 15977 lines
web/static/planning.js: 19446 lines
web/static/styles.css: 25484 lines
web/static/runtime_ide.js: 7659 lines
web/static/module_management.js: 1592 lines
web/static/knowledge.js: 407 lines
web/static/knowledge.css: 439 lines
graphs/configs/atr_closed_loop.yaml: 963 lines
app/controller.py: 8871 lines
orchestrator/supervisor.py: 1251 lines
```

2026-08-08 Knowledge browser/runtime verification snapshot:

```text
real Neo4j health -> ready, 1739 nodes, 4509 edges, outbox pending=0/dead-letter=0
POST /api/knowledge/graph/query run_context limit=20 -> 26 nodes, 20 edges
tests/ui/knowledge_workspace_browser_audit.py @ 1920x1080 -> PASS
Knowledge graph canvas=1288.8x570, inspector width=551.2, horizontal overflow=none
```

Earlier 2026-06-17 browser/runtime verification snapshot:

```text
node --check web/static/planning.js -> pass
python -m py_compile app/main.py app/controller.py -> pass
tests/ui/live_runtime_ide_browser_audit.py @ 127.0.0.1:7862 -> PASS
tests/ui/planning_browser_audit.py @ 127.0.0.1:7862 -> PASS
tests/ui/module_management_browser_audit.py @ 127.0.0.1:7862 -> PASS
controller run/stop integration suite -> 2 passed in 93.94s
runtime/module/controller/live-layout file suite -> 117 passed, 4 warnings in 305.74s
```

The Live GUI audit confirms the reference mission bar, 196px agent binder,
92px chat composer, report toolbar actions, approval panel, runtime graph
actions, bridge/device strip, graph save-version evidence path, and
reference-preserving agent report layouts. It also verifies that the temporary
draft module `ui_audit_draft_descriptor` renders descriptor cards and
descriptor report sections in `/live`, while built-in
Design/Equipment/Guardian report surfaces do not get displaced by descriptor
preview cards. `save-version` is allowed while a run is active only when
`activate=false`; graph activation remains blocked during an active run. The
planning artifact audit confirms `analysis_ai` FEM/CAE contour cards
and collapsed-by-default BO surrogate/acquisition cards render in the chat
without creating the SVG plot until the operator expands the BO card. This
verification did not change the DSN/design-window layout contract.

| Group | Primary source | Operator-facing meaning |
|---|---|---|
| Main/Live/IDE pages | `web/templates/*`, `web/static/*` | Human control surfaces |
| Runtime graph/module APIs | `graphs/*`, `app/main.py` | Graph, module, handler, dry-run, version, run gates |
| Live planning APIs | `app/controller.py`, `app/main.py` | Chat/session transcript and orchestrator handoff |
| Printer APIs/artifacts | `device_bridges/bambu_*`, `device_bridges/prusa_bridge.py`, `app/main.py` | 3DP provider fleet, Bambu/Prusa status, slicing, start, autoejection, proof, Bambu HTTP artifact fetch route |
| LeRobot APIs | `device_bridges/lerobot_bridge.py`, `app/main.py` | ROBOTIS/LeRobot teleop, record, train, rollout, manipulation bridge, Isaac Sim mirror-state probe and mirror loop |
| PyAutoGUI equipment APIs | `device_bridges/windows_pyautogui_bridge.py`, `utils/local_pyautogui_bridge.py`, `app/main.py` | Windows bridge discovery plus managed localhost development target, proof, execution |
| Recorded Equipment Skills | `utils/equipment_skill_runtime.py`, `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`, `agents/equipment_agent.py`, `policies/guardian_gate.py` | Versioned demonstration packages, v2 image-first click/drag locators, deterministic segment execution, exact-model bounded recovery |
| BO/CAE APIs | `agents/bo_agent.py`, `device_bridges/cae_bridge.py` | Optimizer and analysis workspaces |
| Knowledge/Evolution APIs | `knowledge/`, `self_evolution/`, `app/main.py`, `web/templates/knowledge.html`, `web/static/knowledge.*` | Durable memory, bounded Neo4j/Graphify inspection, ontology, relation review/edit, activity visualization, and self-evolution tasks |

Do not use this document as an instruction prompt. Use it as the "what the code
currently does" layer when updating operator docs, README files, or improvement
plans.

Current LeRobot bridge behavior:

- `/api/lerobot/teleoperate/start`, `/api/lerobot/record/start`, and
  `/api/lerobot/rollout/start` share the same follower/camera command-building
  path in `device_bridges/lerobot_bridge.py`.
- If `camera_enabled=true` in live mode and a saved RealSense camera serial is
  not visible from the LeRobot conda environment, the bridge blocks before
  launching the subprocess with `LEROBOT_REALSENSE_CAMERA_UNAVAILABLE`.
- Training does not open robot/camera devices. It validates dataset/output
  paths, fresh/resume output behavior, and Pi0.5 dataset conversion paths.
- Rollout/inference normalizes selected local policy files or output folders to
  the executable LeRobot `pretrained_model` checkpoint directory before command
  construction.
- Isaac Sim mirror mode is read-only with respect to the physical robot. `/api/lerobot/mirror/joint-mapping`
  returns the static follower-ID to Isaac-joint contract for
  `sim/robotis_omx/scene/omx_table_layout.usda`; `/api/lerobot/mirror/state-probe`
  reads follower `Present_Position` through the saved follower port and closes
  the Dynamixel bus without launching teleop/record/train/rollout;
  `/api/lerobot/mirror/receiver-health` checks the configured Isaac receiver
  `/health` endpoint before synchronized live execution; `/api/lerobot/mirror/receiver-verify`
  posts one bounded sample and checks receiver `/state.last_payload_summary`
  against the just-created mirror session/sample.
- `/api/lerobot/mirror/receiver-process/start`, `/api/lerobot/mirror/receiver-process/status`,
  and `/api/lerobot/mirror/receiver-process/stop` manage the local
  Isaac receiver process for the configured host/port. The production default
  launches `/home/jin/IsaacSim/isaac-sim.sh` with
  `--ext-folder sim/robotis_omx/extensions --enable atr.omx.mirror`, so
  `sim/robotis_omx/extensions/atr.omx.mirror` hosts the HTTP receiver inside
  Isaac Sim, opens `sim/robotis_omx/scene/omx_table_layout.usda`, starts the
  Isaac timeline, and applies queued samples on Kit update ticks. The scene has
  a physics-lite contract: `/World/PhysicsScene`, static colliders for the table,
  A4 sheet, and right disk, plus a dynamic `RedSpecimenBlock` rigid body. The
  receiver `/state.last_apply_result.stage_summary` reports `physics_ready`,
  physics-scene paths, collision paths, and rigid-body paths so physical
  teleop/record mirror runs can prove that the visible stage is not a
  visual-only layout. The direct
  `sim/robotis_omx/tools/isaac_omx_mirror_server.py` Python launch remains a
  smoke-test path when `isaac_mirror_receiver_python` is explicitly supplied.
  The start call waits for `/health` and returns process evidence; stop only
  terminates the managed receiver process.
- `/api/lerobot/mirror/loop/start`, `/api/lerobot/mirror/loop/status`, and
  `/api/lerobot/mirror/loop/stop` manage workflow `isaac_mirror`. The loop
  samples follower state, POSTs it to the configured Isaac endpoint, and writes
  JSONL evidence to `runs/isaac_mirror_sessions/<session_id>.jsonl` for standalone
  runs. Teleop and record starts can attach the loop through
  `isaac_mirror_enabled=true`; stopping the parent teleop/record session stops
  the attached mirror loop. Record-attached mirror loops default to
  `<dataset_path>/sidecar/isaac_mirror/<record_session_id>.jsonl` and update
  `<dataset_path>/meta/atr_pipeline.json` with `isaac_mirror` session/path
  metadata plus `sync_summary` and `receiver_state_at_stop` when receiver
  `/state` is available at record stop. Each JSONL row includes per-sample
  `sync_metrics` such as target Hz, loop lag, POST latency, receiver status, and
  receiver sample count when available. The mirrored source is the measured
  follower state, not policy inference output. In live teleop/record with mirror enabled, receiver health
  failure returns `LEROBOT_ISAAC_MIRROR_RECEIVER_UNAVAILABLE` before the LeRobot
  subprocess is started. A reachable receiver that reports
  `apply_mode=direct_http_thread` is also blocked for live teleop/record with
  `LEROBOT_ISAAC_MIRROR_RECEIVER_NOT_IN_ISAAC_UPDATE_TICK`, because that path
  does not prove in-process visible-stage mirroring.
- Pi0.5 rollout runs through `scripts/lerobot_pi05_rollout_wrapper.py` in
  `lerobot-pi05-torch211` and injects
  `--robot.disable_torque_on_disconnect=false` for the ROBOTIS OMX-AI follower.
  If a follow-up handshake reports a missing follower ID, inspect the
  Dynamixel status/reboot path instead of changing the saved motor set.

## 1. Page Routes

The FastAPI app currently serves these operator pages:

| Route | Template | Primary script | Purpose |
|---|---|---|---|
| `/` | `web/templates/index.html` | `web/static/app.js` | Main GUI, runtime controls, model/API-key controls, device workspace launchers |
| `/live` | `web/templates/planning.html` | `web/static/planning.js` | Live GUI, chat orchestration, agent reports, runtime graph, artifacts |
| `/planning` | `web/templates/planning.html` | `web/static/planning.js` | Legacy alias for Live GUI |
| `/ide` | `web/templates/runtime_ide.html` | `web/static/runtime_ide.js` | Runtime IDE graph/module editor |
| `/module-management` | `web/templates/module_management.html` | `web/static/module_management.js` | Module validation, dry-run, versioning, draft module templates |
| `/printer` | `web/templates/printer.html` | `web/static/printer.js` | 3DP printer workspace, Bambu/Prusa fleet, slicing/start/autoejection gates |
| `/lerobot` | `web/templates/lerobot.html` | `web/static/lerobot.js` | ROBOTIS/LeRobot port, teleop, record, train, rollout, manipulation bridge |
| `/bo` | `web/templates/bo.html` | `web/static/bo.js` | BO/MBO strategy, benchmark, candidate ranking |
| `/cae` | `web/templates/cae.html` | `web/static/cae.js` | CAE/FEM analysis workspace |
| `/equipment/windows` | `web/templates/windows_equipment.html` | `web/static/windows_equipment.js` | Windows/local PyAutoGUI target management and UTM bridge workspace |
| `/evolution-lab` | `web/templates/evolution_lab.html` | `web/static/evolution_lab.js` | Self-evolution task/variant/approval workspace |

## 2. Runtime Graph And Agent Manifest

The default closed-loop graph is:

```text
graphs/configs/atr_closed_loop.yaml
```

Current execution order:

```text
dispatch -> idle -> design -> specimen -> vision -> manipulation -> equipment
-> analysis -> knowledge -> bo -> guardian
guardian continue -> design
guardian stop -> complete
guardian error -> error
```

`GET /api/runtime/agent-manifests` currently returns a dictionary payload:

```text
ok
graph_id
graph_version
agents[]
count
categories
source_endpoints[]
```

The `agents[]` list currently contains 11 Live GUI entries:

```text
objective
orchestrator
design
specimen
vision
manipulation
equipment
analysis
knowledge
bo
guardian
```

Descriptor-backed modules currently present in the tree:

```text
graphs/modules/design/ui.yaml
graphs/modules/equipment/ui.yaml
graphs/modules/guardian/ui.yaml
```

All other modules still render through the generic Live GUI report/card
fallback unless a module-local `ui.yaml` is added.

Current manifest details from `_runtime_agent_manifests_payload()`:

| Agent | Short | Handler | Descriptor cards | Report sections | `ui.yaml` |
|---|---:|---|---:|---:|---|
| `objective` | `OBJ` | `runtime.idle` | 0 | 0 | no |
| `orchestrator` | `ORC` | `agent.orchestrator_agent` | 0 | 0 | no |
| `design` | `DSN` | `agent.design_agent` | 2 | 1 | yes |
| `specimen` | `SPC` | `agent.specimen_agent` | 0 | 0 | no |
| `vision` | `VIS` | `agent.vision_agent` | 0 | 0 | no |
| `manipulation` | `MAN` | `agent.manipulation_agent` | 0 | 0 | no |
| `equipment` | `EQP` | `agent.equipment_agent` | 2 | 1 | yes |
| `analysis` | `ANL` | `agent.analysis_agent` | 0 | 0 | no |
| `knowledge` | `KNW` | `agent.knowledge_agent` | 0 | 0 | no |
| `bo` | `BO` | `agent.bo_agent` | 0 | 0 | no |
| `guardian` | `GRD` | `agent.guardian_agent` | 2 | 1 | yes |

Important boundary:

- `module.yaml` is execution-affecting.
- `ui.yaml` is presentation-only.
- `ui.yaml` must not be treated as handler registration, graph routing, tool
  permission, or live-device authority.
- Current `ui.yaml` rendering in `web/static/planning.js` supports `ui.cards[]`
  and selector-backed `ui.report_sections[]`. Selectors can read `report`,
  `state`, `spec`, `metadata`, and `runtime` roots. The generic descriptor
  renderer also supports `chart.type=mini_bar_chart`, `chart.type=scatter_plot`,
  `chart.type=line_chart`, `chart.type=table`, `chart.type=heatmap`,
  `chart.type=compound_chart`/`chart_grid`, safe internal GUI navigation links, and read-only GET API buttons in
  `actions[]`. POST, confirmation-required, and non-read-only API actions can
  be represented only as workspace handoff metadata when they point at an
  existing internal API route and a safe workspace route is provided or
  inferred. Unsupported or physical device actions are never executed by this
  descriptor path; `kind=device`, `kind=physical`, `kind=hardware`, and
  `kind=actuator` are normalized to blocked metadata with
  `blocked_reason=physical_device_action_requires_bridge_workspace`.
- Live GUI chat panel policy is also read from the manifest, not from a fixed
  JavaScript agent id set. `web/static/planning.js::liveAgentChatMode()` reads
  `agent.chat.mode` from `/api/runtime/agent-manifests`. Modes
  `persistent`, `always`, and `required` keep the chat panel visible;
  `open_on_demand`, `on_demand`, `collapsible`, and `contextual` allow a
  report-first agent to open Runtime Chat on demand; `disabled`, `none`, `off`,
  and `hidden` suppress the report Chat action. If no policy is declared,
  objective/orchestrator keep the legacy persistent chat behavior and other
  agents default to open-on-demand.
- `GET/PUT /api/modules/{module_id}/ui` reads and writes the module-local
  descriptor file. The backend stores the descriptor as presentation metadata
  and normalizes chart/action descriptors with `supported`, `render_mode`,
  `safe_navigation`, `live_card_runnable`, `execution_scope`, and
  `blocked_reason`. It also normalizes layout intent fields `span`,
  `density`, `priority`, and `mobile_behavior` into a bounded
  `layout_intent` object. Safe internal GUI links are marked `navigation_only`.
  Internal `/api/*` actions are callable only when declared as `kind=api`,
  `method=GET`, `read_only=true`, and backed by an actual FastAPI GET route; in
  that case they are marked `read_only_api` and rendered as Live GUI GET
  buttons. Internal API actions that are POST, confirmation-required, or
  non-read-only are marked `workspace_handoff` only when their route exists and
  a safe operator workspace is known; the frontend opens that workspace with
  descriptor query context instead of calling the endpoint. Unsupported, unsafe,
  or physical actions are preserved as blocked metadata. Physical action
  execution remains owned by graph validation, bridge APIs, and Guardian gates,
  not by `ui.yaml`.
- `ui.renderer` / custom renderer manifest-id support is partially active as a
  presentation-only manifest profile. `GET/PUT /api/modules/{module_id}/ui`
  normalizes `renderer.dashboard`, `renderer.report`, and `renderer.fallback`
  against the built-in allowlist (`descriptor`, `generic`,
  `objective_reference`, `orchestrator_reference`, `design_reference`,
  `specimen_reference`, `vision_reference`, `manipulation_reference`,
  `equipment_reference`, `analysis_reference`, `knowledge_reference`,
  `bo_reference`, `guardian_reference`). The normalized object is exposed
  through `/api/runtime/agent-manifests`, and `web/static/planning.js` ingests
  the field into `LIVE_AGENTS` with matching `LIVE_RENDERER_PROFILES`.
  `renderAgentSpecificReportSection()` uses the normalized report profile to
  choose the agent-specific report detail renderer, and
  `renderAgentSpecializedDashboardSections()` uses the normalized dashboard
  profile to choose the agent-specific dashboard card renderer.
  Unsupported ids are downgraded to the fallback renderer with
  `blocked_reason=unsupported_renderer_id:<id>`. This does not load arbitrary
  external renderer code; current operator-visible extension points remain
  `cards[]`, `report_sections[]`, `chat.mode`, descriptor charts, safe
  navigation, read-only GET API buttons, workspace handoff buttons, and the
  allowlisted presentation renderer profile.

## 3. Runtime Module APIs

The current module/editor API surface includes:

```text
GET  /api/modules
GET  /api/modules/management-state
GET  /api/modules/{module_id}
POST /api/modules
POST /api/modules/templates/{agent|ui-only|bridge}
GET  /api/modules/{module_id}/ui
PUT  /api/modules/{module_id}/ui
POST /api/modules/{module_id}/load
POST /api/modules/{module_id}/unload
POST /api/modules/{module_id}/validate
POST /api/modules/{module_id}/dry-run
PUT  /api/modules/{module_id}
GET  /api/modules/{module_id}/versions
GET  /api/modules/{module_id}/versions/{version_id}
POST /api/modules/{module_id}/register-generated
```

There are three different module creation/activation paths in the current code:

| Path | API | Runtime effect |
|---|---|---|
| Draft template | `POST /api/modules/templates/{agent|ui-only|bridge}` | Creates an inactive editable module plus starter `ui.yaml`. It is preview-only until attached to a graph and validated. |
| Module Designer transform | `POST /api/modules` | Stores uploaded/source Python, optionally asks the active LLM route to convert it into ATR module shape, writes `handler.py`, and records generated-adapter metadata. |
| Generated adapter approval | `POST /api/modules/{module_id}/register-generated` | Static-validates `handler.py`, switches the module handler to `module.generated_adapter`, records a version, and writes the active module config. It is still subject to graph validation/dry-run before live execution. |

Current Module Designer LLM attempt order is tied to the runtime API-key state.
If the Main GUI API-key cell is loaded and the active backend fallback is
`openai`, the OpenAI backend attempt is placed first. Otherwise the order is
active route primary model, active route model fallback, then configured backend
fallback. In every case, uploaded Python is stored as source/audit material and
is not imported or executed directly by the GUI.

Draft module templates are intentionally non-executable. The generated default
has:

```text
status=draft
enabled=false
handler=runtime.step_complete
execution.capability=ui_only
graph.attached=false
```

Dry-run evidence for an unattached draft must report zero executable steps.

`GET /api/modules/{module_id}`, `POST /api/modules/{module_id}/load`, and
`POST /api/modules/{module_id}/unload` now include a `runtime_effect` and
`lifecycle` payload. This explicitly states that load/unload changes only the
Module Management workspace selection, not graph config or runtime execution.
Actual runtime activation still requires validate/dry-run/save/versioning and a
graph node reference.

Current lifecycle fields include:

```text
module_status
enabled
handler
pending_handler_registration
management_loaded
graph_attached
executable_count
validation_errors
activation_status
activation_requirements[]
ready_for_live_activation
next_required_action
supervisor_policy_gate
dry_run_summary
```

`activation_status` is descriptive only. It can report states such as
`draft_unattached`, `contract_incomplete`, `contract_ready_unattached`,
`validation_blocked`, `dry_run_blocked`, and `active_graph_attached`.
`ready_for_live_activation=true` means the selected module contract is
non-draft/enabled, graph-attached, validation-clean, and has at least one
executable dry-run step. It does not perform graph attachment or start a live
run by itself.

If a module declares `supervisor_policy.required_outputs[]`, lifecycle
generation now adds a supervisor policy output gate. The gate compares
`supervisor_policy.required_outputs[]` with module-declared output contracts
from `output_contracts[]` and list-valued `io_contract.output`. The lifecycle
payload includes:

```text
supervisor_policy_gate.present
supervisor_policy_gate.required_outputs[]
supervisor_policy_gate.declared_outputs[]
supervisor_policy_gate.missing_outputs[]
supervisor_policy_gate.ok
```

When `missing_outputs[]` is non-empty, `activation_requirements[]` includes
`supervisor_policy_outputs` with `ok=false`; Module Management renders this as
`Supervisor required outputs` and lists `required_outputs`, `declared_outputs`,
and `missing_outputs`. This keeps custom supervisor text and follow-up policy
aligned with the module contract before a module is treated as live-ready.

For graph-unattached modules, Module Management opens Runtime IDE with
`/ide?module=<module_id>&action=attach`. Runtime IDE selects that module in the
Module Library, highlights it as the attach target, and shows the operator
instruction to drag it onto the main graph canvas, connect ports, validate,
dry-run, and `Save Version`. This is a guided graph-attach handoff; it does not
auto-edit the graph or bypass any activation gate.

The current Module Management frontend renders this distinction explicitly:

```text
Management-only load lifecycle
changes_runtime_execution=false
changes_graph_config=false
requires_validate_dry_run_save_for_activation=true
```

Therefore a module can be `Loaded` in the management workbench while remaining
absent from the active runtime graph.

The typed Module Configuration Workspace currently edits these module fields:

```text
handler
llm_role
llm.backend / llm.model
timeout_s
retry.max_attempts
tools
prompt.path / prompt.system / prompt.developer
safety.live_requires_validation
safety.dry_run_supported
safety.requires_human_approval
pre_execution[]
internal_graph[]
supervisor_policy.required_outputs[]
supervisor_policy.opinion_template
supervisor_policy.recommendation_template
supervisor_policy.requires_response_on_status[]
supervisor_policy.concern_rules[]
supervisor_policy.options[]
```

Other module fields can still be edited through the raw JSON panel and saved
through `PUT /api/modules/{module_id}` if the payload validates.

## 4. Graph APIs

The graph API is config-driven from `graphs/configs/*.yaml`:

```text
GET  /api/graphs
GET  /api/graphs/{graph_id}
PUT  /api/graphs/{graph_id}
POST /api/graphs/{graph_id}/validate
POST /api/graphs/{graph_id}/validate-draft
POST /api/graphs/{graph_id}/compile
POST /api/graphs/{graph_id}/export-yaml
POST /api/graphs/{graph_id}/import-yaml
POST /api/graphs/{graph_id}/dry-run
GET  /api/graphs/{graph_id}/dry-run-gate
POST /api/graphs/{graph_id}/run
GET  /api/graphs/{graph_id}/versions
GET  /api/graphs/{graph_id}/versions/{version_id}
POST /api/graphs/{graph_id}/save-version
```

Live graph runs require compile-valid graph config and the configured dry-run
gate. The legacy `/api/run/start` path and compatibility `/api/runtime/start`
path both converge on the same runtime controller.

## 5. Device Bridge Registry Versus Printer Fleet

There are two different device discovery layers in the current code.

### 5.1 Graph Bridge Registry

`GET /api/bridges` reads:

```text
graphs/configs/atr_closed_loop.yaml -> graph.metadata.device_bridges
```

and normalizes the metadata through `app/main.py::_normalized_bridge_manifests()`.
It currently returns these graph-level bridge entries:

```text
prusa_bridge
lerobot_bridge
windows_pyautogui_bridge
cae_bridge
camera_utm_bridge
```

This registry is a graph/IDE/Live GUI discovery manifest. It does not execute
hardware and it is not the printer fleet selector. The current API returns
bridge actions in `actions[]`; if graph metadata does not declare custom
actions, the backend materializes the standard `open_workspace`, `health_check`,
and `preflight` entries in that same list.

`POST /api/bridges/{bridge_id}/actions` is the current descriptor-authoring
endpoint. It validates a local action descriptor, writes it into active graph
metadata under `metadata.device_bridges[].actions`, records a graph version
snapshot, and returns the normalized bridge/action payload with
`execution_scope=descriptor_only`. It does not call the target endpoint, start
hardware, or grant Live GUI card execution authority. POST,
confirmation-required, non-read-only, and custom actions still normalize to
workspace handoff unless they satisfy the read-only GET `/api/*` rule.

Current normalized bridge fields:

```text
id
label
workspace
tools
config
live_boundary
health_endpoint
preflight_endpoint
actions
evidence_contracts
health
source
order
custom_action_count
live_card_runnable_action_count
```

Default action shape:

```text
id
label
kind
method
endpoint
requires_confirmation
read_only
tool
mode_support
source
live_card_runnable
handoff_required
handoff_workspace
blocked_reason
```

If the graph metadata does not declare actions, the backend creates these
standard entries under `actions[]`:

```text
open_workspace
health_check
preflight
```

The same normalized bridge list is also embedded in
`GET /api/runtime/state -> runtime_ide_contract.device_bridges`, so Runtime IDE,
Module Management, and Live GUI should read the same contract shape.
`tests/unit/test_langgraph_runtime.py::test_bridge_custom_action_descriptor_can_be_saved_to_graph_metadata`
verifies that a descriptor saved through `POST /api/bridges/{bridge_id}/actions`
is visible both in `GET /api/bridges` and in
`GET /api/runtime/state -> runtime_ide_contract.device_bridges` as the same
normalized handoff-only action.
`tests/unit/test_langgraph_runtime.py::test_new_bridge_manifest_entry_is_shared_by_bridge_api_and_runtime_contract`
verifies the add-new-bridge path: appending one bridge entry to graph metadata
is enough for both `/api/bridges` and the runtime IDE contract to expose the
same normalized bridge actions and evidence contracts. This proves registry
display/discovery; physical execution remains bridge-workspace specific.
The current Live GUI reads this payload through
`web/static/planning.js::liveBridgeContracts()` and renders read-only bridge
cards in `renderDeviceStrip()` with workspace, health endpoint, preflight
endpoint, `actions[]` summary, and evidence-contract count. These cards are
discovery/status surfaces only; hardware execution remains routed through each
bridge-specific API and safety gate. The standard `open_workspace` action is
implemented only as safe navigation that opens the bridge workspace route in a
new window. `health_check` and `preflight` actions are callable from the Live
GUI card only when the action is `read_only=true`, `method=GET`, and targets an
`/api/` endpoint. Non-read-only, POST, confirmation-required, or custom actions
are not executed from the card-level runner; they are shown as workspace
handoff actions. The handoff opens the bridge workspace with `bridge_id`,
`bridge_action`, and `bridge_endpoint` query context and records an operator
event instead of issuing the physical/API command directly.

Current normalized bridge endpoint defaults:

| Bridge | Workspace | Health | Preflight |
|---|---|---|---|
| `prusa_bridge` | `/printer` | `/api/printer/status` | `/api/printer/spc-readiness` |
| `lerobot_bridge` | `/lerobot` | `/api/lerobot/config` | `/api/lerobot/profiles/validate` |
| `windows_pyautogui_bridge` | `/equipment/windows` | `/api/equipment/windows/readiness` | `/api/equipment/windows/live-preflight` |
| `cae_bridge` | `/cae` | `/api/cae/config` | `/api/cae/config` |
| `camera_utm_bridge` | `/lerobot` | `/api/lerobot/config` | `/api/lerobot/camera/test` |

The graph YAML still contains the legacy Windows workspace alias
`/windows-equipment`; the backend normalizes it to `/equipment/windows` before
returning API payloads.

### 5.2 Printer Fleet

The active printer provider is managed by `/api/printer/fleet`, not by
`/api/bridges`.

Current fleet shape:

```text
active_profile_id: bambulab_x2d_lab_01
default_profile_id: bambulab_x2d_lab_01
available profiles:
  - bambulab_x2d_lab_01 / provider=bambulab_x2d
  - prusa_mk4s_lab_01 / provider=prusa_mk4s
automatic_fallback: false
settings_path: memory/printer_fleet.json
```

Bambu Lab X2D is therefore the default 3DP provider, but it is exposed through
the printer fleet and `/api/printer/*` endpoints. Prusa is not a fallback path;
it is selected explicitly through the fleet/profile layer.

## 6. Printer API Groups

The current `/printer` workspace uses these main groups:

```text
GET  /api/printer/fleet
POST /api/printer/fleet
GET  /api/printer/profile
POST /api/printer/profile
GET  /api/printer/connection
POST /api/printer/connection
GET  /api/printer/status
GET  /api/printer/video-status
GET  /api/printer/video-frame.jpg
GET  /api/printer/video-stream.mjpeg
POST /api/printer/upload-path-probe
POST /api/printer/bambu-slice-artifact
POST /api/printer/http-artifact-route
POST /api/printer/bambu-prestart-check
POST /api/printer/start-command-draft
POST /api/printer/start-gate
POST /api/printer/start-publish
POST /api/printer/spc-readiness
GET  /api/printer/autoejection-status
POST /api/printer/autoejection-config
POST /api/printer/autoejection-test
POST /api/printer/bambu-autoejection-patch
POST /api/printer/bambu-autoejection-sweep-test
GET  /api/printer/bed-clear
POST /api/printer/bed-clear
POST /api/printer/bambu-autoejection-proof-template
POST /api/printer/bambu-autoejection-completion-audit
GET  /printer-artifacts/bambu/{token}/{filename}
```

Pre-start, video, status, SPC readiness, and start-publish are separate planes.
Camera/video refresh must not clear existing MQTT/progress/material evidence.
Start-publish must not treat an MQTT acknowledgement alone as a completed or
started print; post-publish observation is required.

Current Bambu pre-start behavior:

- `/api/printer/bambu-prestart-check` is Bambu-only and returns
  `video_status`, `device_screen`, `slice_artifact`, optional
  `autoejection_patch`, `http_artifact_route`, `start_gate`, `spc_readiness`,
  `steps[]`, `ready_to_publish`, `will_publish=false`, `published=false`, and
  `start_enabled`.
- `web/static/printer.js::runBambuPrestartCheck()` disables the Pre-start
  button while the request is running, refreshes video status before and after
  the backend check, updates the sliced-artifact path when slicing produced a
  new artifact, and renders the returned device screen/SPC readiness without
  clearing unrelated MQTT/status/material panels.
- The pre-start path validates output-before-start only. It never publishes the
  Bambu MQTT `project_file` command.

## 7. Model And API-Key Runtime

`GET /api/runtime/models` currently exposes two managed NemoClaw/vLLM model
cells:

```text
gemma4:31b
gemma4:e4b-it-nvfp4
```

There is no active `e2b` managed model in the current runtime model list.

Current NemoClaw/vLLM deployment facts from `configs/system.yaml`:

```text
gemma4:31b
  hf_repo: nvidia/Gemma-4-31B-IT-NVFP4
  endpoint: http://127.0.0.1:8001/v1
  node_port: 31001
  speculative_method: mtp
  assistant_repo: google/gemma-4-31B-it-assistant
  num_speculative_tokens: 4

gemma4:e4b-it-nvfp4
  hf_repo: bg-digitalservices/Gemma-4-E4B-it-NVFP4
  endpoint: http://127.0.0.1:8002/v1
  node_port: 31002
  speculative_method: disabled
  num_speculative_tokens: 0
```

Both deployments use `quantization=modelopt_fp4` and
`nvfp4_gemm_backend=marlin`. E4B is deliberately target-only because the
E4B+NVFP4+MTP path was disabled after local CUDA device-side assert failures.

Current route mapping:

```text
orchestrator_plan      -> orchestrator -> gemma4:31b primary, e4b fallback
module_designer        -> orchestrator
design_reasoning       -> e4b
analysis_reasoning     -> e4b
analysis_fem_planning  -> e4b
bo_policy              -> e4b
knowledge_query        -> e4b
guardian_reasoning     -> e4b
tool_formatting        -> e4b
gui_helper             -> e4b
```

OpenAI API-key state is managed through:

```text
POST /api/runtime/backend
GET  /api/runtime/api-key
POST /api/runtime/api-key
POST /api/runtime/api-key/load
POST /api/runtime/api-key/unload
```

`POST /api/runtime/backend` switches the active inference backend for future
model calls. It does not itself load a NemoClaw/vLLM model or create an API key.

The saved key lives in `memory/api_keys.json`, which is local-only and must stay
ignored by Git. API responses report `has_key` / `key_status` only and must not
return the raw key.

When API-key loading is enabled, OpenAI becomes the first inference route in the
backend setting. When unloaded, the key can remain registered while local vLLM
returns to first priority.

## 8. Other Workspace API Groups

The current app also exposes:

```text
/api/lerobot/*
/api/equipment/windows/*
/api/bo/*
/api/cae/*
/api/knowledge/*
/api/evolution/*
/api/events/recent
/api/events/stream
/api/runtime/events
/api/planning/*
/api/runs/{run_id}/*
/api/artifacts/*
/api/runtime/gpu-clear
/api/docs/agent-baseline
/api/docs/agent-baseline.md
```

The workspace APIs are direct controls for setup, debugging, or operator-driven
execution. They are not a substitute for the closed-loop graph path unless the
controller explicitly calls them through the relevant agent/tool bridge.

Current endpoint ownership rules:

- `/api/bo/*` and `/api/cae/*` are workspace and agent-support APIs. They may
  produce BO/CAE artifacts, but they do not directly start printers or robots.
- `/api/lerobot/*` can start live subprocesses only through its own live gates
  and profile confirmation. The Manipulation Agent bridge reuses this layer
  instead of generating shell commands in the agent.
- `/api/equipment/windows/*` owns Windows PyAutoGUI/UTM bridge discovery,
  locator/proof capture, and program execution. Lab Equipment Agent should call
  the bridge/tool layer rather than manipulating GUI state directly.
- `/api/knowledge/*` and `/api/evolution/*` are evidence/memory/evolution
  support surfaces. They may inform BO/Guardian/Self-Evolution, but they are not
  physical actuation APIs.
- `/api/runtime/gpu-clear` is an operator maintenance endpoint. It should not
  be called automatically by normal stage execution.

## 8.1 Camera And RealSense Boundary

The current code has three different camera paths. They must not be described as
one unified live-camera stack.

| Path | Current owner | Runtime behavior |
|---|---|---|
| `camera.capture` tool | `mcp_tools/camera_tools.py`, `mcp_tools/mock_tools.py`, `agents/vision_agent.py` | Deterministic simulator-style capture contract used by Vision Agent. It returns typed observation fields and does not open real camera streams by itself. |
| LeRobot camera test | `device_bridges/lerobot_bridge.py`, `/api/lerobot/camera/test` | Profile-scoped OpenCV capture for saved `top`, `wrist`, or additional GUI camera keys. It may use the LeRobot conda environment when `cv2` is not available in the main `.venv`. |
| RealSense bridge class | `device_bridges/realsense_bridge.py` | Fail-closed bridge for RealSense enumeration, profile validation, and explicitly allowed single-frame capture. It is not currently exposed as a standalone FastAPI workspace route. |

Important RealSense rules in the current code:

- `RealSenseBridge.execute("enumerate"|"health"|"status")` imports
  `pyrealsense2`, lists devices and advertised profiles, and does not start a
  streaming pipeline.
- `validate_profile` selects only an advertised stream/format/fps/size profile.
- `capture` first validates the profile and then fails closed unless
  `allow_stream=true` or `live_stream_confirmed=true` is present in the payload.
- This bridge exists to avoid starting arbitrary unsupported streams on unstable
  USB camera topologies. A missing RealSense route in FastAPI does not mean the
  class is absent; it means live RealSense capture is not yet promoted to a
  first-class workspace API.
- `requirements.txt` and `REQUIREMENTS.md` list `pyrealsense2==2.58.2.10647`.
  Installing that wheel adds the Python SDK only; it does not change USB
  topology, kernel camera mappings, or LeRobot camera key assignments.
- LeRobotBridge owns policy-camera command generation. The current ROBOTIS OMX
  profile uses `top=341522300873` D455F with `color_format=rgb8` and
  `wrist=352122273019` D405 with `color_format=bgr8`; both RealSense cameras
  keep `warmup_s>=20`.
- `Detect & Save` must not store a visible D455F as the wrist camera when D405
  is absent. That failure is reported as `LEROBOT_REALSENSE_ROLE_CAMERA_NOT_FOUND`.
- `scripts/realsense_usb_stabilize.py` inspects RealSense/BRIO USB sysfs power
  settings and can set currently enumerated devices to `power/control=on`
  without opening a camera stream.

## 9. Live GUI Transcript And Session State

The Live GUI conversation is file-backed to avoid repeatedly keeping the entire
chat/artifact history in memory.

Current storage path:

```text
runs/<active_run_id>/live_planning_transcript.jsonl
```

Current APIs:

```text
GET  /api/planning/session
GET  /api/planning/messages?before=<index>&limit=<n>
POST /api/planning/bootstrap
POST /api/planning/message
GET  /api/planning/artifacts/{run_id}/{specimen_id}/{filename}
```

Controller behavior:

- each planning message is compacted and appended to the JSONL transcript;
- only the latest `PLANNING_TRANSCRIPT_MEMORY_LIMIT=50` messages remain in
  controller memory;
- `/api/planning/session` returns the current state plus a bounded latest page;
- `/api/planning/messages` lazy-loads older pages from the transcript file with
  `before`, `limit`, `has_more_messages`, and `next_before`;
- explicit `fresh=1`/fresh session paths reset the transcript;
- refreshing or reopening a browser tab should read the server-side transcript
  and current runtime state rather than reconstructing messages from local
  browser memory.

The storage compactor keeps operator-facing fields such as `experiment_spec`,
`specimen`, `device_screen`, `preprint_gate`, `readiness_levels`,
`operator_actions`, `analysis`, `bo_result`, and `module_runtime`, while dropping
bulky raw geometry/report internals.

## 10. Custom Stage Compatibility Boundary

The `Stage` enum remains the compatibility type for existing code, but it now
accepts graph-validated extension stage strings through `Stage._missing_()`.
This preserves `.value` serialization while allowing a configured stage such as
`custom_quality_gate` to move through `LangGraphRunLoop._coerce_stage()`.
Regression coverage proves two minimum custom-stage paths:

- `idle -> custom_quality_gate` transition preserves
  `state.stage.value == "custom_quality_gate"`.
- An allowlisted `agent.*` custom stage with module config can execute one
  runtime step and transition to `complete`.
- `MainController.snapshot()` builds the Orchestrator supervisor plan from the
  active graph route when a graph override is active, so a route such as
  `design -> specimen -> custom_quality_gate -> guardian` appears in
  `latest_orchestration_plan` and the Live GUI control-plane task queue instead
  of silently falling back to the legacy `BASE_ROUTE`.
- Live planning stage role/label resolution uses `module_runtime.handler` and
  graph node labels for custom stages. A custom node with
  `handler=agent.custom_quality_agent` is surfaced as `custom_quality_agent`
  and `Custom Quality Gate` in planning messages and supervisor route steps.
- Supervisor route steps also import module-declared output contracts from the
  active graph module root. `output_contracts[]` and list-valued
  `io_contract.output` become `required_outputs` in the Orchestrator plan and
  task queue for custom modules.
- Custom stage follow-up records can use a `supervisor_policy` descriptor from
  payload or `module_runtime`. The descriptor supports opinion/recommendation
  templates, required-output formatting, lightweight concern rules, options, and
  response-required statuses. Without that descriptor, custom stages still use
  the generic follow-up text.
- Module-local `ui.yaml` can declare `report_sections`; `/api/runtime/agent-manifests`
  preserves them and the Live GUI renders those selector-backed sections in the
  dashboard report and academic report surfaces. `ui.chat.mode` is also
  preserved and consumed by Live GUI to decide persistent chat, on-demand chat,
  or disabled chat controls. This is presentation-only and does not grant
  execution authority.

This is not the full custom-stage lifecycle. Selector-backed custom report
sections plus backend-normalized layout intent, `mini_bar_chart`, `scatter_plot`, `line_chart`, `table`, `heatmap`, `compound_chart`/`chart_grid`,
safe navigation action descriptors, and read-only GET API action descriptors are
implemented. POST/confirmation/non-read-only API descriptors now support
workspace handoff metadata and Live GUI handoff buttons. Physical-device
descriptor actions are explicitly blocked with
`physical_device_action_requires_bridge_workspace`; more domain-specific chart
types, actual physical device action authoring, and custom stage enable/load
policy are still partial.
Graph attach/save now has a minimal Module Management -> Runtime IDE attach
handoff, but the actual graph edit still occurs in Runtime IDE and must pass
validate/dry-run/Save Version before execution. The backend can consume
`supervisor_policy` from payloads/module runtime, and the current Module
Management GUI exposes the main descriptor fields through a typed editor. The
Module Management lifecycle gate now also checks that
`supervisor_policy.required_outputs[]` are declared by the module output
contract before reporting the module as ready for live activation.

## 11. Limitations and Known Gaps

The current code has the first modularization layer in place, but not the full
free-modularization goal:

- Stage enum decoupling is partial: graph-validated custom stage strings,
  allowlisted custom agent steps, controller/supervisor route visibility,
  descriptor-backed custom follow-up text, selector-backed `ui.yaml`
  report sections, manifest-driven `ui.chat.mode`, descriptor layout intent, basic `mini_bar_chart`, `scatter_plot`, `line_chart`, `table`, `heatmap`, `compound_chart`/`chart_grid`, safe
  navigation action descriptors, read-only GET API action descriptors,
  POST/confirmation/non-read-only API workspace handoff descriptors, and
  explicit physical-device action blocking metadata are supported, but more
  domain-specific charts and actual physical device action authoring are not
  complete. Graph-attach authoring has a minimal
  Module Management -> Runtime IDE deep-link handoff; full custom-stage
  activation authoring remains a follow-up.
- Module Management load/unload lifecycle visibility is implemented as
  management-only metadata with activation readiness fields. It is intentionally
  not runtime activation. When `supervisor_policy.required_outputs[]` is
  present, lifecycle readiness also checks those outputs against
  `output_contracts[]` and list-valued `io_contract.output`.
- Bridge registry backend normalization, Runtime IDE descriptor authoring, Live
  GUI bridge cards, safe `open_workspace` navigation, read-only GET
  health/preflight action runner, and non-read-only/custom action workspace
  handoff are implemented. Physical custom action execution workflow remains
  bridge-workspace/device-gate specific.
- Custom stage live execution lifecycle is partially visible through module
  activation readiness fields, and graph-unattached modules can deep-link into
  Runtime IDE attach mode. Actual graph activation still requires Runtime IDE
  validate/dry-run/save evidence.
- Only Design, Equipment, and Guardian currently have committed module-local
  `ui.yaml` descriptor examples. The Live GUI browser audit also creates a
  temporary draft module `ui_audit_draft_descriptor`, saves a `ui.yaml`
  descriptor through `GET/PUT /api/modules/{module_id}/ui`, and verifies that
  the draft appears in the Live GUI binder, Runtime Chat target, and
  descriptor report DOM without becoming executable.
- `/api/bridges` is normalized graph-bridge discovery only; Bambu printer fleet
  remains under `/api/printer/fleet` and `/api/printer/*`.
- Custom renderer manifest ids are a bounded presentation extension, not a
  runtime/plugin execution contract. Do not document or build operator
  workflows that require arbitrary third-party renderer code. The current
  supported path is the allowlisted `ui.renderer` profile plus descriptor
  cards/report sections and safe actions.

These are tracked in `개선안/12_free_modularization_gap_analysis.md`.

## 12. Documentation Update Rules For This Snapshot

When code changes after this snapshot, update docs in this order:

1. Re-run the route extraction command below and update the route count if it
   changed materially.
2. Update this file first with the actual API/page/contract change.
3. Update the relevant operator-facing document:
   - GUI or route change: `docs/gui/gui.md`
   - Loop/agent contract change: `docs/runtime/closed_loop_and_pages_reference.md`
   - Graph/module/runtime change: `docs/runtime/langgraph_runtime.md`
   - Device bridge change: `docs/hardware/*` plus the relevant tutorial
4. Update `README.ko.md`, `README.en.md`, and `docs/README.md` only when the
   public entry point, folder responsibility, or high-level runtime contract
   changed.
5. Keep design-package or improvement-plan documents separate from this
   snapshot. They can describe target direction, but they should not override
   the current code contract.

## 13. Verification Commands

Use these commands when this snapshot needs to be refreshed:

```bash
cd /home/jin/autonomous_researcher
.venv/bin/python - <<'PY'
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
for path in [
    "/api/runtime/agent-manifests",
    "/api/bridges",
    "/api/printer/fleet",
    "/api/runtime/models",
    "/api/runtime/api-key",
]:
    r = client.get(path)
    print(path, r.status_code, r.json())
PY
```

For route count and endpoint group extraction:

```bash
.venv/bin/python - <<'PY'
from collections import Counter
from fastapi.routing import APIRoute
from app.main import app
routes = [r for r in app.routes if isinstance(r, APIRoute)]
page_paths = {
    "/", "/live", "/planning", "/ide", "/module-management", "/printer",
    "/lerobot", "/bo", "/cae", "/knowledge", "/device-bridge/vision-utm",
    "/equipment/windows", "/equipment/windows/console",
    "/equipment/windows/bridge-ui/{resource_path:path}", "/evolution-lab",
}
favicon_paths = {"/favicon.ico", "/favicon.svg"}
page = [r.path for r in routes if r.path in page_paths]
favicon = [r.path for r in routes if r.path in favicon_paths]
api = [r.path for r in routes if r.path not in page_paths and r.path not in favicon_paths]
print("operator page paths", len(set(page)))
print("favicon route entries", len(favicon))
print("API/artifact APIRoute entries", len(api))
print("total FastAPI APIRoute entries", len(routes))
print("total app.routes entries including docs/openapi/static", len(app.routes))
def group(path: str) -> str:
    if path in page_paths:
        return "operator_pages"
    if path in favicon_paths:
        return "favicon"
    if path.startswith("/api/runtime"):
        return "runtime"
    if path.startswith("/api/modules"):
        return "modules"
    if path.startswith("/api/graphs") or path in {"/api/handlers", "/api/tools"}:
        return "graphs"
    if path.startswith("/api/planning"):
        return "planning"
    if path.startswith("/api/printer"):
        return "printer"
    if path.startswith("/api/artifacts") or path.startswith("/artifacts") or path.startswith("/printer-artifacts"):
        return "printer_artifacts"
    if path.startswith("/api/lerobot"):
        return "lerobot"
    if path.startswith("/api/equipment/windows"):
        return "equipment_windows"
    if path.startswith("/api/bo"):
        return "bo"
    if path.startswith("/api/cae"):
        return "cae"
    if path.startswith("/api/bridges"):
        return "bridges"
    if (
        path.startswith("/api/run")
        or path.startswith("/api/events")
        or path.startswith("/api/runs")
        or path.startswith("/api/approvals")
    ):
        return "events_runs"
    if path.startswith("/api/knowledge"):
        return "knowledge"
    if path.startswith("/api/evolution"):
        return "evolution"
    return "other_api"
for key, value in sorted(Counter(group(r.path) for r in routes).items()):
    print(f"{key}: {value}")
PY
```

For raw route extraction:

```bash
python3 - <<'PY'
import ast
from pathlib import Path
p = Path("app/main.py")
mod = ast.parse(p.read_text())
for node in mod.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for d in node.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute):
                if getattr(d.func.value, "id", "") == "app" and d.func.attr in {"get", "post", "put", "delete", "patch"}:
                    path = d.args[0].value if d.args else ""
                    print(d.func.attr.upper(), path, node.name)
PY
```

For primary graph counts:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import yaml

graph = yaml.safe_load(
    Path("graphs/configs/atr_closed_loop.yaml").read_text(encoding="utf-8")
)["graph"]
print("Graph nodes:", len(graph["nodes"]))
print("Graph edges:", len(graph["edges"]))
print("stage_dispatch edges:", len(graph["stage_dispatch"]))
PY
```

The labeled counts were collected during the 2026-08-08 Asia/Seoul
verification session from committed baseline `09bbe32`. Importing `app.main`
may create an empty run directory; verification cleanup may remove only the
directory proven to have been created by that import.

## BoTorch Sequential Optimization (2026-08-10)

- Production BO defaults to `botorch`; legacy `botorch_optional` settings are normalized to it.
- `learning/bo_parameter_space.py` owns the stable mixed-space codec, schema hash, and deterministic Latin Hypercube design.
- Closed-loop `BOAgent` calls evaluate exactly one next point per cycle. Initial cycles use LHS; subsequent cycles fit `SingleTaskGP` and call `optimize_acqf` or `optimize_acqf_mixed`.
- BO Workspace can still run a full synthetic budget for random/grid/BO comparison.
- BoTorch failures are typed and visible. No automatic lightweight backend substitution is allowed.
- Live GUI, BO Workspace, and PNG/SVG/CSV artifacts consume the same `bo_visualization.v1` posterior arrays.
- The visible BO posterior/EI figure is output-only: it shows score, uncertainty,
  measured scores, EI, and an anonymous normalized search coordinate. The two
  model inputs remain part of fitting and provenance but are not rendered as
  axes, strata, labels, facets, or tooltips in this figure; input-space display
  belongs to the separate LHS card.

## Two-Variable Gyroid SEA Optimization (2026-08-11)

- The canonical active space is `cell_size_mm x relative_density`. For a
  30 mm Gyroid specimen, cell size is the feasible discrete set
  `{5.0, 6.0, 7.5, 10.0}` mm from `a=L/N`, `N={6,5,4,3}`; relative density is
  continuous on `[0.20,0.48]`.
- `BOParameterSpace` normalizes both dimensions to `[0,1]^2`. The first eight
  accepted observations use one deterministic balanced Latin Hypercube design.
  The normal 20-cycle test run uses those eight initialization cycles followed
  by twelve `SingleTaskGP` / Expected Improvement cycles when all observations
  are accepted.
- In initial-design mode, `BOAgent` preserves the numeric LHS proposal without
  passing it through candidate/LLM reranking. The runtime exposes
  `optimization_phase=initial_design`, `backend_active=lhs`, and the explicit
  `completed/target/next_index` progress. Live GUI chat, report, and dashboard
  cards consume this phase contract and do not show combined/acquisition scores
  as if they selected the point.
- After eight valid measured observations, BoTorch fits `SingleTaskGP` with an
  ARD Matérn 5/2 covariance and Gaussian observation noise, then maximizes
  `LogExpectedImprovement`. Discrete feasible cell sizes are enumerated as
  fixed features while relative density is optimized continuously.
- The authoritative objective is measured
  `specific_energy_absorption_J_per_g` in J/g. Composite proxy scores,
  rejected observations, and infeasible observations do not enter the GP.
- Test-mode multi-cycle planning seeds its first Design request from BO Agent's
  canonical LHS sequence through an explicit Orchestrator-owned
  `orchestrator_design_contract.v1`. Each later `next_design_request.v1` is
  republished through the same contract before Design Agent runs. Closed-loop
  static constraint filtering releases both active variables while retaining
  specimen envelope, material, process, cap, and orientation settings.
- The deterministic LHS plan is generated once from the configured seed and
  retained as eight two-dimensional points. Every initialization cycle selects
  the next unobserved point from that plan; it does not regenerate a smaller
  LHS from the remaining count.
- Live and BO Workspace cards expose the same two-variable design-space,
  initial-design, kernel, noise, acquisition, normalization, and objective
  metadata. The selected-parameter graph is a one-dimensional marginal view of
  the two-dimensional model, not a separate one-dimensional optimizer.

## Related Documents

- [LangGraph Runtime](langgraph_runtime.md)
- [Closed Loop and Pages Reference](closed_loop_and_pages_reference.md)
- [Knowledge Graph Operations Guide](../knowledge/knowledge_graph_operations.ko.md)
- [Documentation Standard](../standards/documentation_standard.md)
