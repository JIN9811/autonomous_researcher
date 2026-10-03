---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience:
  - user
  - operator
  - developer
scope:
  - closed_loop
  - operator_pages
  - agents
summary: System reference linking the current closed-loop execution order to page, agent, and event contracts.
source_of_truth:
  - graphs/configs/atr_closed_loop.yaml
  - orchestrator/langgraph_runtime.py
  - app/controller.py
  - app/main.py
  - web/templates/planning.html
  - web/static/planning.js
last_verified: 2026-09-29
verified_against: dd0d772
related_docs:
  - docs/runtime/current_code_snapshot.md
  - docs/runtime/langgraph_runtime.md
  - docs/knowledge/markdown_memory_operations.ko.md
supersedes: []
---

<a id="닫힌-루프-실행-및-페이지에이전트-reference"></a>

# Closed-Loop Execution and Page/Agent Reference

## Summary

- Start the closed loop with `POST /api/run/start` or `POST /api/runtime/start`.
- The default execution graph is `atr_closed_loop` in `graphs/configs/atr_closed_loop.yaml`.
- If no progress is visible, check the start request, event delivery to the current window, and Guardian and lifecycle termination states.

## Scope

This document explains the default closed loop, operator pages, agents/modules,
and runtime event and artifact connections. Device-specific operating procedures
belong in active Guides; future design proposals belong in Design/Evidence documents.
Source inspection and historical test results do not establish current device readiness.

## Source of Truth

- `graphs/configs/atr_closed_loop.yaml`
- `orchestrator/langgraph_runtime.py`
- `app/controller.py` and `app/main.py`
- `graphs/modules/*/module.yaml`
- `web/templates/` and `web/static/`

---

<a id="1-초보자용-어떻게-돌아가는가-5분-정독"></a>

## 1) Beginner Overview: How It Works (5-Minute Read)

1. **Start**
   - GUI: `/live` or `POST /api/run/start` (mode: `live|test|replay|fault-injection`)
   - The server creates a Run object, sets the `orchestrator stage` to `idle`, then starts the loop.
2. **First transition**
   - `idle -> design` (the start of execution)
3. **Default cycle**
   - `design -> specimen -> vision -> manipulation -> vision -> equipment -> analysis -> knowledge -> bo -> guardian` (representative flow; transfer, observation, and UTM clearance use conditional routes)
4. **Repeat or terminate**
   - The `guardian` decision determines the next stage:
     - `continue` returns to `design`
     - `stop` selects `complete`
     - `error` selects `error`
   - `complete/error` terminates the loop.
5. **If the screen appears idle**
   - Check `state.run_id` and `state.stage` in `/api/runtime/state`.
   - Check `/api/runtime/events` or `/api/runs/{run_id}/events` for `run.started / node.started / node.completed / edge.traversed / run.completed`.
   - An immediate `complete/error` indicates termination through Guardian/safety conditions.

<a id="초보자용-실험-시작-체크리스트"></a>

### Beginner Experiment Startup Checklist

- [ ] Server is running (`atr up`).
- [ ] Open `/live`.
- [ ] Select `mode=test` for testing or `mode=live` for live execution.
- [ ] For device status, open the dedicated `/printer`, `/equipment/windows`, or `/lerobot` GUI from Main GUI `Device Workspaces` and check bridge status. `/bo` is the optimization workspace; the retired `/cae` page is not a current operating path.
- [ ] Start the Run and obtain a run_id.
- [ ] Confirm that these events appear in sequence:
  - `run.started`
  - `node.started(node=design)`
  - `node.completed`
  - `edge.traversed` or `stage_transition`
- [ ] Finally, `run_complete` or `run.failed`.

<a id="11-device-workspace와-live-gui의-관계"></a>

### 1.1 Relationship Between Device Workspaces and the Live GUI

Use Main GUI `Device Workspaces` for device-specific configuration and validation.
The default 3D Printer Bridge profile is Bambu Lab X2D; Prusa MK4S is used only
when explicitly selected. The BambuLab X2D provider layer, MQTT/FTPS/HTTP/camera
planes, and native G-code autoejection gate are described in
`docs/hardware/bambulab_x2d_device_bridge_runtime_guideline.md`.
This document covers the closed-loop and page/API contracts.

Bambu bridge evidence has 5 planes: `artifact`, `validation`, `transport`,
`runtime`, and `bed-clear`. The Live GUI and 3D Printer workspace must present
them consistently. `published=true` alone must not be displayed as physical ejection success.

The Live GUI summarizes `selected_printer`, `device_screen`, `preprint_gate`,
`readiness_levels`, `operator_actions`, `autoejection`, and `bed_clear` returned
by the 3D Printer workspace/API. The Specimen Making report shows the same
evidence as that workspace, centered on `Live Job Monitor`.

- Data: the active printer profile's `printer_status`, `build_queue`,
  `layer_preview`, `camera_evidence`, `autoejection_gate`, `artifact_ledger`.
- Cards: `Build Intent`, `Printer Telemetry`, `Readiness Gate`, `Slice Profile`,
  `Thermal / Material`, `Transfer Queue`, `Live Job Monitor`, `Layer Preview`,
  `Camera Evidence`, `Post-Print Automation`, `G-code Validation`,
  `Handoff / Artifacts`.

Do not fabricate fixed-brand cards or status. Show missing values as unknown/pending;
do not invent progress values or camera frames.

Design Agent records `bambu_autoejection_readiness` in the authoritative experiment
spec and design report for Bambu autoejection candidates. It includes
`ejection_contact_edge`, `bed_contact_area_mm2`, `bed_contact_area_ratio`,
`minimum_pushable_height_mm`, `pushable_edge_height_mm`, skirt/brim/raft
policy. Specimen Making Agent preserves this object unchanged in
`fabrication_report.process_plan.bambu_autoejection_readiness` and
`specimen_agent_report.bambu_autoejection_readiness`.
This keeps the design's contact surface, push edge, skirt/brim/raft policy,
and printer-validator evidence in the same trace.

Bambu's default ejection path uses deterministic G-code patching/validation.
`bambu_gcode_patch` preserves the original sliced `.gcode.3mf` or plain `.gcode`
and creates an `.autoeject.*` artifact. Publishing requires owner-managed publish
defaults, the backend start gate, camera/bed-clear evidence, and printer safe-state
validation. Manipulation Agent handles ejection-failure recovery and subsequent
specimen transfer; it is not the default ejection executor.

An operator checkbox alone cannot pass the bed-clear gate.
Obtain fresh camera preview/proxy evidence through `Video Status` or `Pre-start Check`
in the 3D Printer workspace, then use `Mark Bed Clear` to save it as
`camera_snapshot_path` through `/api/printer/bed-clear`. The next-cycle gate and
Live GUI report share this evidence. The pre-publish camera gate saves a local
JPEG under `artifacts/bambu_camera_evidence/` when possible; a successful guarded
`.autoeject.*` publish records that camera reference with its bed-clear evidence.

Distinguish execution results from status updates in the 3D Printer workspace.

- Standalone executions such as `/api/printer/autoejection-test` update the
  `/printer` log, `/api/events/recent`, and active Live GUI transcript.
  The frontend merges and deduplicates run-scoped and recent workspace events.
  The presence of run events must not hide workspace results.
- While the Live GUI is open, `/api/printer/status?mode=live&emit=1` creates a
  `workspace_monitor_snapshot` event. The device strip updates heartbeat/progress/
  connection from `monitor_snapshot.device_screen`, but this event creates neither
  a transcript message nor an artifact registration.

`/api/bridges` is the graph-bridge discovery API for Runtime IDE/Live GUI.
It returns normalized workspace, health/preflight endpoint, standard/custom
action descriptors in `actions[]`, and evidence contracts.
Bambu/Prusa selection belongs to the separate `/api/printer/fleet` layer, which
also identifies the default Bambu Lab X2D profile. Use
[current_code_snapshot.md](current_code_snapshot.md) to maintain the current
route/API/manifest snapshot.

---

<a id="2-상급자용-루프-아키텍처-계약"></a>

## 2) Advanced Reference: Loop Architecture Contracts

<a id="21-엔트리포인트"></a>

### 2.1 Entry Points

- `POST /api/run/start`: primary start API
- `POST /api/runtime/start`: compatibility alias
- `POST /api/run/pause`, `/api/run/resume`, `/api/run/stop`, `/api/run/safe-stop`
- `GET /api/runtime/state`, `GET /api/runs/{run_id}`, `GET /api/runs/{run_id}/events`

<a id="22-실행-경로"></a>

### 2.2 Execution Path

- Controller: `MainController.start(mode=...)`
- Execution object: `LangGraphRunLoop`
- Run loop: `while` → check `stop`/`pause` → `step()` → `ainvoke(compiled graph)` → `sleep(interval)`
- Default graph: `graphs/configs/atr_closed_loop.yaml` (`graph id=atr_closed_loop`)

<a id="23-stage-전이-규칙"></a>

### 2.3 Stage Transition Rules

- Default transitions: extracted from `stage.transitions`
- Runtime routing candidates: based on `runtime_edge=logical_transition` metadata
- Startup: requires successful `dispatch`/`idle` consistency validation
- Live start requires the active graph's dry-run gate.
  - Failure returns HTTP 409 with `GRAPH_DRY_RUN_REQUIRED` in `detail.code` and gate context in `detail`.

<a id="24-이벤트-계열핵심"></a>

### 2.4 Core Event Families

- `run.started`, `run.stopped`, `run.completed`, `run.failed`
- `node.started`, `node.completed`, `node.failed`
- `edge.traversed` (or `stage_transition`)
- `agent_result`, `tool_event`, `artifact.created`
- `approval.requested` / `approval.resolved`

<a id="25-live-gui-transcript-저장-계약"></a>

### 2.5 Live GUI Transcript Storage Contract

Live GUI conversations are not stored only in browser memory. The controller
appends each compact planning/chat message to the canonical planning-session file
`runs/<originating_run_id>/planning_sessions/<planning_session_id>/live_planning_transcript.jsonl`
and keeps only a recent window in memory. This path and the colocated Experimental
Setup store persist across execution run allocation. Before a canonical session
path is selected, the compatibility fallback is
`runs/<active_run_id>/live_planning_transcript.jsonl`.

- Latest state: `GET /api/planning/session`
- Older message pages: `GET /api/planning/messages?before=<index>&limit=<n>`
- Explicit reset: selects a new planning-session directory without deleting prior evidence.

After opening a new window or refreshing, restore state from `/api/planning/session`
and `/api/planning/messages`. Treating separate local-only Live GUI state as the
source of truth can make the conversation diverge from runtime state.

<a id="26-custom-stage-현재-지원-범위"></a>

### 2.6 Current Custom-Stage Support

The code has not completely removed the fixed `Stage` enum, but accepts
graph-validated extension-stage strings as `Stage._missing_()` pseudo-members.
The minimum supported behavior is:

- Stages such as `custom_quality_gate` in the active graph serialize through `.value`.
- Custom stages with an allowlisted `agent.*` handler and module config can run
  in LangGraphRunLoop.
- `MainController` Orchestrator plan/control-plane snapshots use active graph
  routes, so custom stages appear in `latest_orchestration_plan`, `route_state`,
  and the task queue.
- Module `output_contracts[]` and list-valued `io_contract.output` become
  supervisor route-step `required_outputs`.

Domain-specific report authoring for custom stages and custom-action execution UX
remain incomplete. Module Management can hand graph-unattached modules to Runtime
IDE through `/ide?module=<id>&action=attach`; Runtime IDE highlights the Module
Library attach target. Actual graph editing/activation still requires Runtime IDE
drag/drop, port connections, validate/dry-run, and Save Version gates. The backend
can read `supervisor_policy` from the payload/module runtime, and Module Management
can edit the main descriptor fields through a typed form. Remaining work is tracked
in `docs/oldversion/개선안/12_free_modularization_gap_analysis.md`.

---

<a id="3-기본-닫힌루프기본-모드-단계별-상세"></a>

## 3) Default Closed Loop: Stage Details

The following is a representative experiment flow. The actual default and
conditional routes are defined by
[`atr_closed_loop.yaml`](../../graphs/configs/atr_closed_loop.yaml).

```text
dispatch -> idle -> design -> specimen -> vision -> manipulation -> vision -> equipment -> analysis -> knowledge -> bo -> guardian -> (continue: design | stop: complete | error: error)
```

The default `manipulation -> vision` transition returns to post-manipulation
verification. Vision conditionally selects Manipulation when transfer is needed,
remains in Vision for observations during execution, and proceeds to Equipment
after placement verification. A separate scope-bound conditional route also
verifies UTM clearance before handing off to Analysis.

<a id="핵심-노드-동작-실행디버깅-포인트"></a>

### Core Node Behavior (Execution and Debugging)

- `dispatch`: routes from the state stage to the execution stage
- `idle`: reaches the loop entry point
- `design` through `guardian`: execute the respective agent handlers
- `complete`/`error`/`step_complete`: termination, summary, and audit stages

---

<a id="4-페이지별-상세"></a>

## 4) Page Details

| Page | Path | Template | Purpose | Main APIs |
|---|---:|---|---|---|
| Main Dashboard | `/` | `index.html` | Overall runtime status, model/run controls, device cards, Timeline, events, UTM ROS runtime card | `/api/state`, `/api/runtime/state`, `/api/runtime/start`, `/api/runtime/pause`, `/api/runtime/stop`, `/api/runtime/models*`, `/api/runtime/events`, `/api/equipment/utm-runtime/*` |
| Live Orchestration | `/live` | `planning.html` | Chat-based experiment instructions, planning handoff, stage messages/artifacts | `/api/planning/bootstrap`, `/api/planning/message`, `/api/planning/session`, `/api/planning/artifacts/{...}` |
| Live (legacy) | `/planning` | `planning.html` | Alias for `/live` | Same as above |
| 3DP/Printer GUI | `/printer` | `printer.html` | Default Bambu Lab X2D device bridge, explicit printer-fleet selection, connection, live video probe/proxy, Bambu Studio slicing, sliced-artifact route, pre-start checklist, start gate, guarded MQTT start publish, SPC readiness, autoejection-gate checks, physical-proof package audit | `/api/printer/fleet`, `/api/printer/profile`, `/api/printer/status`, `/api/printer/video-status`, `/api/printer/video-stream.mjpeg`, `/api/printer/connection`, `/api/printer/upload-path-probe`, `/api/printer/bambu-slice-artifact`, `/api/printer/http-artifact-route`, `/api/printer/bambu-prestart-check`, `/api/printer/start-command-draft`, `/api/printer/start-gate`, `/api/printer/start-publish`, `/api/printer/spc-readiness`, `/api/printer/autoejection-status`, `/api/printer/autoejection-config`, `/api/printer/autoejection-test`, `/api/printer/bambu-autoejection-patch`, `/api/printer/bambu-autoejection-sweep-test`, `/api/printer/bed-clear`, `/api/printer/bambu-autoejection-proof-template`, `/api/printer/bambu-autoejection-completion-audit` |
| BO Workspace | `/bo` | `bo.html` | BO/MBO/LLM preference strategy configuration, reasoning audit, candidate ranking, next-design handoff | `/api/bo/config`, `/api/bo/benchmark`, `/api/bo/run` |
| Runtime IDE | `/ide` | `runtime_ide.html` | Graph/edge/module editing, module-attach deep-link, validation/dry-run/execution, version management | `/api/graphs*`, `/api/modules*`, `/api/handlers` |
| Module Management | `/module-management` | `module_management.html` | Module load/unload/validation/version saving, draft-module creation, `ui.yaml` descriptor management, typed handler/LLM/tool/prompt/safety/step editing, raw JSON editing | `/api/modules*`, `/api/modules/templates/*`, `/api/modules/{id}/ui`, `/api/runtime/agent-manifests`, `/api/bridges`, `/api/handlers` |
| Knowledge Workspace | `/knowledge` | `knowledge.html` | AX4LAB Wiki, scoped Memory, Source Library, Agent Delivery, Ontology inspection; the relationship editor is retired | See [Wiki and Memory](../knowledge/wiki_memory.md) and [Knowledge owner](../agents/knowledge_agent.md) for current route/storage boundaries |
| PyAutoGUI Equipment Bridge | `/equipment/windows` | `windows_equipment.html` | Windows candidate discovery/selection and Ubuntu localhost development-bridge startup/selection/program execution | `/api/equipment/windows/config`, `/api/equipment/windows/local-bridge/*`, `/api/equipment/windows/discover`, `/api/equipment/windows/connect`, `/api/equipment/windows/select`, `/api/equipment/windows/delete`, `/api/equipment/windows/test`, `/api/equipment/windows/run-program` |
| LeRobot GUI | `/lerobot` | `lerobot.html` | ROBOTIS teleop/record/train/rollout, port/camera configuration, manipulation-agent bridge and integration, Isaac Sim follower-state probe/receiver process/receiver-health/receiver-verify and mirror loop | `/api/lerobot/config`, `/api/lerobot/ports*`, `/api/lerobot/camera/test`, `/api/lerobot/mirror/*`, `/api/lerobot/teleoperate/*`, `/api/lerobot/record/*`, `/api/lerobot/train/*`, `/api/lerobot/rollout/*`, `/api/lerobot/manipulation-agent/*` |

---

<a id="5-에이전트모듈별-상세-입력출력툴"></a>

## 5) Agent/Module Details (Inputs, Outputs, and Tools)

Each agent follows the module metadata in `graphs/modules/<agent>/module.yaml`: handler, LLM role, tool allowlist, pre_execution, and internal_graph.

### Design Agent (`modules/design`, `agent.design_agent`)

- **Purpose**: normalize experiment goals into an explicit specimen design specification
- **Core tool**: `agent.orchestrator_agent` (pre_execution: `orchestrator_plan`)
- **Main results**: `state.current_experiment_spec`, `state.current_experiment_objective`, `experiment_spec`
- **Key state values**: specimen dimensions, material, constraints, and metrics

### Specimen Making Agent (`modules/specimen`, `agent.specimen_agent`)

- **Purpose**: generate STL/manufacturing metadata and hand off to the manufacturing bridge
- **Core tools**: `geometry.generate_metamaterial_stl`, `geometry.check_mesh_quality`, `geometry.check_manufacturability`, `artifact.create_specimen_handoff`, `experiment.evaluate`, `printer.prepare`
- **Main results**: `specimen_result`, `protocol_note`, and manufacturing values in `state.current_experiment_spec` (layer/nozzle/profile/options)
- **Execution focus**: STL-viewer rendering is secondary; manufacturing status and artifact handoff are central.
- **Printer-fleet integration**: `/api/printer/fleet` in the 3D Printer workspace reads/saves the active printer profile. The default is `bambulab_x2d_lab_01`. Prusa MK4S is not a fallback; it runs only as an explicitly selected operator profile. Selection is saved in local-only `memory/printer_fleet.json`.
- **Fleet UI state retention**: preserve the `available_printers` list returned by `/api/printer/fleet` after rendering `/api/printer/status` or `/api/printer/spc-readiness` responses. A later response containing only the selected printer must not make the GUI show an empty Bambu/Prusa selection list.
- **Bambu slicer resolver**: the Bambu profile's slicer payload resolves the executable in this order: `BAMBU_STUDIO_EXECUTABLE` environment variable, configured wrapper path, then `bambu-studio` on `PATH`. `/api/printer/profile` and `/api/printer/status` return `resolved_executable_path`, `available`, `source`, and `output_dir`. The profile route detects the Bambu Studio installation only; it does not establish upload/start readiness.
- **Bambu slicer runner**: `/api/printer/bambu-slice-artifact` operates only when the active profile is Bambu. The input must be an actual local `.stl` or `.3mf`. The backend runs Bambu Studio CLI as `--slice 0 --arrange 1 --ensure-on-bed --outputdir <artifact-dir> --export-3mf <safe-id>.gcode.3mf --debug 2`. The `--export-3mf` value must be a basename within the output directory; an absolute path can cause Bambu Studio to join the output directory twice. Without explicit `load_settings`, the runner preserves Bambu Studio's default presets and does not inject `--load-settings`/`--load-filaments`.

  Purge/cleaning/filament start-end G-code is retained. Only front build-plate test/intro/nozzle-load line blocks are removed from the generated `.gcode` or the plate G-code inside `.gcode.3mf`, and the md5 sidecar is updated. Results include the actual generated `.gcode`, `.3mf`, or `.gcode.3mf` paths, size, sha256, command preview, stdout/stderr tail, `slicer_profile`, and `front_test_line_removal` evidence. This route only creates slicing artifacts; it does not upload, publish MQTT commands, or start printing.
- **Bambu pre-start checklist**: `/api/printer/bambu-prestart-check` is the operator-facing pre-print check. It runs actual backend paths in order: `camera_status -> slice_artifact -> native_autoejection_patch_when_enabled -> http_artifact_route -> start_gate -> spc_readiness`, returning each stage's result. It keeps `will_publish=false` and `published=false` and sends no MQTT `project_file` command. `ready_to_publish=true` means technical publishing conditions were verified, not that printing started.
- **Bambu pre-start aggregate**: like the Bambu Studio Device tab, Pre-start Check refreshes camera, thermal/progress, AMS/material, transfer/start, autoejection, and bed-clear evidence together. The camera/video plane is independent of the status plane. A failed video probe or repeated `/api/printer/video-status` call must not erase MQTT/progress/material evidence. The latest camera preview/evidence reference is reused as `camera_snapshot_path` for operator bed-clear evidence. `Mark Bed Clear` updates bed-clear verification and the latest camera reference without erasing tracking fields locked by an earlier `.autoeject.*` publish, such as remote path, artifact hashes, manifest, or publish sequence/topic.
- **Bambu bridge integration**: `/api/printer/spc-readiness` provides aggregate status for Specimen Making handoff. When Bambu is the active printer profile, it combines Bambu live `prepare`, start gate, device screen, native G-code autoejection gate, and bed-clear gate to return `ready_for_live_print`, `autonomous_cycle_ready`, and per-section blockers. It does not publish MQTT commands or start printing. Its `device_screen` must also update the frontend's top Bambu Device Screen, replacing old virtual/test evidence. Bambu autoejection becomes configured only through the local `memory/bambu_autoejection.json` overlay saved by `/api/printer/autoejection-config`.
- **Bambu Device screen contract**: `/api/printer/status?mode=live` builds user-facing `progress_panel`, `camera_panel`, `control_panel`, `material_panel`, and `evidence_cards` in `device_screen` rather than exposing raw MQTT JSON. Values derive from actual MQTT reports received by `normalize_bambu_report()`, FTPS/upload probes, start-command drafts, and connection gates; the GUI does not invent progress/camera/material state. The camera is a separate plane from MQTT. Repeated GUI polling uses a short in-process MQTT snapshot cache rather than creating a new MQTT client and `pushall` request per poll. Post-publish observation after `/api/printer/start-publish`, by contrast, bypasses the cache with `force_refresh` to verify MQTT acknowledgment separately from actual `RUNNING`/`PRINTING` state.

  `/api/printer/video-status` probes the LAN video port using the saved Bambu host/access code. When `ffmpeg` is available, `/api/printer/video-stream.mjpeg` provides a browser MJPEG proxy. Raw access codes must not appear in API responses or GUI logs.
- **Bambu autoejection parameter contract**: the native `bambu_gcode_patch` provider is a deterministic G-code patcher, not an external-provider handoff. Operator parameters are push direction, Z push offset, push lane offset, push speed, full-bed sweep enable, sweep Z, and sweep speed. P1/P1S/X1/X1C use X-axis multi-lane pushing; A1/A1 Mini require a separate Y-axis bed-slinger/wiggle generator. These generators must not be reused across families. The current CoreXY tail generator blocks A1/A1 Mini profiles with `BAMBU_AUTOEJECTION_MODEL_FAMILY_UNSUPPORTED` rather than producing invalid motion artifacts.
- **Bambu validation/test artifact contract**: `Validate G-code Preview` checks the selected direction without publishing or starting motion. Left/center/right are direction choices, not separate live-ejection buttons. Validation returns only the proposed tail, object bounds, candidate hash, and blocker evidence; it writes no `.autoeject.*` artifact, sidecar manifest, or run-workspace manifest. `Generate Ejection Test Artifact`, `Generate Sweep Test Artifact`, and `Generate Patched Artifact` create local files without overwriting the source artifact and retain `will_publish=false` / `start_enabled=false`. Generated artifacts receive a `.manifest.json` sidecar; when run context exists, they also update `runs/<run_id>/workspace/printer/bambu_autoejection_manifest.json`.

  `.gcode.3mf` patching maintains consistency between internal plate G-code and the `Metadata/plate_#.gcode.md5` hash sidecar. Tail comments record the schema marker, source/patched hash references, source plate path, plate id, loop index, object bounds/height, material/bed placeholder, cooldown, sweep, purge/parking strategy, door/front assumption, and validation reference. The validator checks a single schema marker, safe motion, no unexpected homing, object bounds, residual skirt/brim/raft, and cooldown-wait evidence (`M190 R/S...` or an explicit wait policy). Physical motion requires the applicable live gates: direct publishing uses `/api/printer/start-publish`; the separate standalone live-test path described below uses the printer owner.

  `/api/printer/autoejection-test` is not unconditionally non-actuating. For native Bambu autoejection, `mode=live`, `start_immediately=true`, and a valid standalone artifact enter a guarded execution branch. It requires `dry_run=false`, operator confirmation, Guardian approval, camera evidence, and bed-clear checks, then calls live `manager.prepare` with physical print intent for the startable project file. Artifact-only invocation leaves `motion_started=false`; `/api/printer/bambu-autoejection-sweep-test` remains artifact-only even if immediate start is requested.
- **Bambu physical-proof/audit contract**: `/api/printer/bambu-autoejection-proof-template` creates fail-closed physical-validation JSON. `/api/printer/bambu-autoejection-completion-audit` reads the specified path or latest package and verifies center ejection, disposable live ejection, left/right lanes, bed-clear, next-job gate, camera files, and patch manifest. Both routes are non-actuating audit helpers: they do not publish MQTT commands, upload, capture camera images, or move axes. If the active printer profile is not Bambu, both proof-template generation and audit are blocked as `NOT_APPLICABLE`, and no proof file is written. The Live GUI and tutorial must not display Bambu native autoejection as physically successful until completion audit returns `complete_evidence_verified`.
- **SPC screen contract**: `/api/printer/spc-readiness` returns `operator_summary`, `readiness_levels`, `next_actions`, `evidence`, and `sections` alongside the raw gate payload so operators can assess readiness directly. `readiness_levels` separates connection, transfer path, owner-managed publish defaults, publish command, and autoejection. `next_actions` derives from actual blockers, operator actions, and autoejection blockers; the GUI does not invent status.
- **Bambu Connection Confirmation contract**: the 3D Printer workspace's `Connection Confirmation` board combines saved Bambu connection settings with fresh status/SPC evidence to show LAN-only confirmation, Developer Mode confirmation, sliced-artifact transfer, and HTTP artifact-route status. Display codes derive from `BAMBU_LAN_MODE_NOT_CONFIRMED`, `BAMBU_DEVELOPER_MODE_NOT_CONFIRMED`, `BAMBU_FTPS_WRITE_FAILED`, `BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED`, and `BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE`. Checkbox/form values alone must not establish upload readiness.
- **Bambu transfer contract**: successful FTPS login/listing does not establish upload readiness. After root marker write/delete fails, live `prepare` probes `cache`, `sdcard`, `Metadata`, and `data/Metadata` using CWD+basename. If every candidate fails, transfer remains `read_only`, with `BAMBU_FTPS_WRITE_FAILED` / `BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED` as blockers. Only printer-reachable `http://`/`https://` URLs created by `/api/printer/http-artifact-route` with verified `server_fetch_probe.ok=true` and a matching sha256 qualify as HTTP artifact transfer. The ATR server must listen on a LAN-accessible interface (`server.host=0.0.0.0` or an explicit LAN IP), and the artifact URL sent to Bambu must use the ATR server's LAN IP, not `localhost`. An ordinary remote path (`cache/*.gcode.3mf`) is not an HTTP route and cannot bypass FTPS verification.
- **Bambu start integration**: `/api/printer/start-gate` validates only and does not publish. The direct publish route `/api/printer/start-publish` calls `BambuMqttReportClient.publish_project_file_command()` only when draft validity, the live preprint gate, device `can_start_print`, operator confirmation, Guardian approval, and `dry_run=false` all pass. Printer-owner `prepare` execution, including the guarded standalone live test above, can also publish through its own live gates; `/api/printer/start-publish` is not the only publishing path in the system. The 3D Printer workspace removes manual operator/Guardian/dry-run controls and sends `operator_confirmed=true`, `guardian_approved=true`, and `dry_run=false` as workstation owner/operator-managed defaults.

  For `.autoeject.*` artifacts, front path/door, ramp/bin, toolhead cover, release surface, and supervised-first-ejection items are also recorded as `operator_managed=true` evidence, not manual-checkbox blockers. A `project_file` draft is valid only for `.gcode.3mf` artifacts; plain `.gcode` or `plate_id < 1` is blocked with `BAMBU_PROJECT_FILE_PARAM_MISMATCH`. Status-snapshot and publish timeouts are separate. Status timeouts may stay short, while publishing uses the model setting `publish_timeout_sec`, defaulting to 180 seconds with a 60-second minimum.

  After publishing, fresh `printer.prepare` results are attached as `post_publish_observation`, `post_publish_status`, and `post_publish_failure_code`, recording `gcode_state`, progress, subtask, and safe-state evidence separately from the MQTT acknowledgment. An `.autoeject.*` artifact locks the bed-clear gate as required immediately after a successful publish acknowledgment. When available, `remote_path`, `subtask_name`, source/patched artifact paths, source/patched sha256, sidecar manifest path, MQTT publish sequence/topic, post-publish status, and camera snapshot reference are saved together in `memory/bambu_bed_clear_evidence.json`. An `IDLE`/not-started observation returns `ok=false` and `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED` even when `published=true`.

  A verified HTTP artifact route may set `device_screen.actions.can_start_print=true` and `technical_ready_for_start=true`, but these indicate only an open technical gate; backend start/publish observations still require checking.
- **Live GUI Specimen report contract**: `SpecimenMakingAgent` preserves Bambu/SPC evidence from `printer.prepare` in `fabrication_report.printer_runtime` and `specimen_agent_report.spc_readiness`. `MainController` Live GUI compaction must retain `selected_printer`, `device_screen`, `preprint_gate`, `readiness_levels`, `operator_actions`, and `autoejection`. The frontend displays these as `Printer Bridge / SPC Readiness`, showing PrusaLink-specific transport/storage rows as supplementary information only when Prusa is the active profile.

### Vision Agent (`modules/vision`, `agent.vision_agent`)

- **Purpose**: capture images, observe state, and generate observations for downstream manipulation
- **Core tools**: `camera.capture`, `lerobot.active_robot_cam.capture`, optional `lerobot.camera.test`
- **Required result key**: `observation`
- **Active-cam/SPC handback**: after printer-side autoejection, Vision Agent can save LeRobot active-camera one-shot evidence as `active_cam_ejection_check.v1`. Successful `lerobot.camera.test` responses must include `RELEASE_CAMERA_PORT`, `port_released`, `camera_returned_to_vla`, and `camera_owner_after=vla_runtime`. Once the specimen is confirmed and the camera is returned to the VLA runtime, it emits `spc_autoejection_confirmation.v1` and the `spc_autoejection_confirmed` signal targeting `specimen_agent`. A failed return blocks downstream manipulation/VLA handoff with `transfer_readiness.camera_returned_to_vla=false`.

  Live GUI Vision reports use `Live Observation`, `Active Cam Ejection`, `Specimen Pose`, `Camera / Runtime`, `Handoff Signal`, and `Agentic Progress` cards. The `Active Cam Ejection` card shows the active-cam capture image/path/status/release state.

### Manipulation Agent (`modules/manipulation`, `agent.manipulation_agent`)

- **Purpose**: plan/execute robot manipulation and coordinate specimen transfer
- **Core tools**: `lerobot.rollout.start`, `robot.pick_place`
- **Main results**: `manipulation`, `protocol_note`
- **Integration**: `/api/lerobot/manipulation-agent/*` and direct LeRobot workspace actions

### Lab Equipment Agent (`modules/equipment`, `agent.equipment_agent`)

- **Purpose**: hand off laboratory-equipment control to the Windows bridge or UTM macros
- **Core tools**: `equipment.pyautogui.health`, `equipment.pyautogui.list_programs`, `equipment.pyautogui.run`, `utm.run_protocol`
- **Required result keys**: `equipment_result`, `protocol_note`
- **UTM ROS evidence provider**: `device_bridges/utm_runtime_bridge.py` builds an RQT-like `usb_cam -> rectify_node -> green_dot_monitor -> yolov8` graph based on the `start_utm_vision_stack.sh`, `camera_rect.launch.py`, `green_dot_monitor.launch.py`, and `yolo.sh` flow in `<home>/external_repos/UTM`. Actual graph state is read through ROS2 node/topic introspection. `/api/equipment/utm-runtime/frame` captures one image-evidence frame, trying `/image_utm`, `/yolo/dbg_image`, `/compression_tester/debug_image`, `/camera/image_rect`, and `/camera/image_raw` in order.
- **UTM test/live policy**: the name `test` alone does not guarantee virtual fallback. Virtual evidence depends on each owner's selected scenario, effective mode, `allow_virtual_bridge_in_test`, and clearance-verification conditions. Missing ROS/frame evidence on physical-device paths must not be replaced with virtual success. Detailed contracts are defined in [Vision](../agents/vision_agent.md) and [UTM ROS bridge](../hardware/utm_ros_vision_runtime_bridge.md).

### Analysis Agent (`modules/analysis`, `agent.analysis_agent`)

- **Purpose**: convert Lab Equipment raw UTM artifacts into standard analysis records and a BO-ready handoff
- **Core processing**: Analysis-owned measurement-file parsing, canonical-curve generation, quality/SEA calculation, and BO handoff. Retired CAE/FEM tools are not part of the current Analysis execution path.
- **Main results**: `analysis`, `bo_observation`, `bo_handoff`, `experiment_evaluation`, `knowledge_payload`
- **Main artifacts**: `raw_input_sidecar.json`, `parse_report.json`, `preprocessing_report.json`, `quality_report.json`, `metrics.json`, `analysis_report.json`, `analysis_trace.jsonl`. Preserve `canonical_curve.csv` when a valid curve exists and `experiment_evaluation.json` / `bo_handoff.json` when the corresponding handoffs exist. Historical FEM files do not imply that those files are currently generated.

### Knowledge Agent (`modules/knowledge`, `agent.knowledge_agent`)

- **Purpose**: summarize failure/performance history to inform subsequent candidates and guidance
- **Main result**: `knowledge` (memory updates, failure patterns, and recent-result summaries)

### BO Agent (`modules/bo`, `agent.bo_agent`)

- **Purpose**: read Analysis/Knowledge evidence and failure memory, then recommend the next Design candidate using numeric BO with an LLM-reasoning soft prior
- **Core tool**: `experiment.benchmark`
- **LLM role**: generate strict JSON `bo_policy` reasoning (`bo_reasoning_v1`), while numeric acquisition, validators, and failure penalties retain final candidate authority
- **Main results**: `bo_result`, `candidate_pool`, `candidate_ranking`, `next_design_request.v1`, `run_metadata["bo_recommended_constraints"]`
- **GUI display**: Live GUI and `/bo` show evidence intake, hypotheses, strategy, candidate ranking, recommendation, and reasoning/artifact paths.
- **Caution**: BO Agent does not directly operate printers, robots, or equipment. Recommended candidates remain subject to subsequent Design Agent and Guardian validation.

### Guardian Agent (`modules/guardian`, `agent.guardian_agent`)

- **Purpose**: verify safety and progress, then decide the next action
- **Core tools**: `device.health`, `experiment.queue.status`
- **Decisions**: `continue`, `stop`, `error` (stage decision)

---

<a id="6-이벤트로-루프-확인하기트러블슈팅"></a>

## 6) Checking the Loop Through Events (Troubleshooting)

- If the loop appears inactive, first check:
  1. Whether the `POST /api/run/start` response contains `run_id`.
  2. Whether `GET /api/runs/{run_id}` reports `active=true` and `snapshot.is_running=true`. `active` identifies the current run; it does not alone mean the run is executing.
  3. Whether `/api/runs/{run_id}/events` or the SSE stream shows successive `node.started`/`edge.traversed`/`run.completed` events.
- If execution stops at `idle` immediately after entering the loop, first investigate **preconditions that prevented a stage from completing** (device gates or validation failures), rather than assuming a Guardian/default-launch issue.
- If `live` terminates immediately, check whether `safe_stop_requested` or `stop_requested` is true.

---

<a id="7-운영-권장-워크플로우초간단"></a>

## 7) Recommended Operating Workflow (Quick Reference)

<a id="테스트-모드"></a>

### Test Mode

`test` alone does not guarantee non-actuation. Explicitly verify that the selected
profile uses virtual I/O for every device. Installed Printer/Physical Print
selections retain separate device authority and safety gates. A failed model
decision is not virtual success.

1. Enter a goal or a test-mode command in the Live GUI.
2. Call `POST /api/run/start` (mode=test).
3. Check `run` events, then stage messages/artifacts.
4. After completion, check whether `guardian` chose continue or stop.

<a id="실모드"></a>

### Live Mode

1. Check device/bridge gates and model/connection status.
2. Enter an experiment command in Live chat (Korean command alias: `실험 수행`, meaning “run the experiment”).
3. At device-stage transitions after `specimen`, check the selected printer provider/robot/wrapper gates.
4. Check the `guardian` decision and whether execution enters the next loop.

---

<a id="8-참고문서"></a>

## 8) References

- [runtime/langgraph_runtime.md](langgraph_runtime.md)
- [runtime/agent_program_baseline.md](agent_program_baseline.md)
- [docs/process/codex_workflow.md](../process/codex_workflow.md)
- [runtime/autonomous_experiment_runtime.md](autonomous_experiment_runtime.md)
- [gui/gui.md](../gui/gui.md)

---

<a id="9-코드-위치별-빠른-추적표"></a>

## 9) Code Location Quick Reference

| What to inspect | File/folder |
|---|---|
| All server routes | `app/main.py` |
| Default closed-loop graph | `graphs/configs/atr_closed_loop.yaml` |
| Graph validation rules | `graphs/validator.py` |
| Graph compilation/adapters | `graphs/compiler.py`, `graphs/generated_adapter.py` |
| Module registry | `graphs/registry.py` |
| Live GUI screen | `web/templates/planning.html`, `web/static/planning.js` |
| Main GUI screen | `web/templates/index.html`, `web/static/app.js` |
| Runtime IDE | `web/templates/runtime_ide.html`, `web/static/runtime_ide.js` |
| Module Management | `web/templates/module_management.html`, `web/static/module_management.js` |
| 3D Printer workspace | `web/templates/printer.html`, `web/static/printer.js` |
| LeRobot GUI | `web/templates/lerobot.html`, `web/static/lerobot.js` |
| BO GUI | `web/templates/bo.html`, `web/static/bo.js` |
| Windows bridge GUI | `web/templates/windows_equipment.html`, `web/static/windows_equipment.js` |

<a id="10-루프가-안-도는-것처럼-보일-때-보는-순서"></a>

## 10) Inspection Order When the Loop Appears Inactive

1. Check `ok` and `run_id` in the `POST /api/run/start` response, then confirm the requested mode through `state.mode` in the runtime snapshot.
2. Check `is_running`, `state.stage`, and `state.run_id` in `GET /api/runtime/state`.
3. Check that `node.started` and `node.completed` follow each stage in `GET /api/runs/{run_id}/events`.
4. If execution enters `complete/error` immediately after `guardian`, inspect `guardian_decision`, `approval`, and `failure_code` first.
5. If the Live GUI shows stale state, compare the `/api/events/stream` heartbeat with `GET /api/events/recent`.
6. If execution stops at a device stage, inspect that workspace's saved settings (`memory/*`) and bridge-status API.

<a id="11-협업자에게-설명할-때-한-문장-요약"></a>

## 11) One-Sentence Summary for Collaborators

The FastAPI runtime executes the stage graph in `graphs/configs/atr_closed_loop.yaml`; each stage calls LLMs, tools, and device bridges through agent modules in `graphs/modules/*`, while the Live GUI and Runtime IDE share runtime state/event/artifact APIs.

## Active Cam Handoff Gate

Closed-loop order around manipulation:

```text
Specimen/3DP auto-ejection
-> VisionAgent wrist Active Cam one-shot confirmation
-> Active Cam port returned to VLA runtime
-> ManipulationAgent VLA inference
-> VisionAgent BRIO/UTM placement verification contract
-> Lab Equipment Agent
```

Runtime representation:

- `graphs/modules/vision/module.yaml` declares `lerobot.active_robot_cam.capture` and emits the active-camera confirmation contract.
- `graphs/modules/manipulation/module.yaml` consumes `transfer_readiness.camera_returned_to_vla`; it does not request a separate RGB-D pose snapshot before rollout.
- `graphs/configs/atr_closed_loop.yaml` defaults to executable `manipulation -> vision -> equipment`, with conditional transfer, monitoring and UTM-clearance routes. `vision_verify` remains a non-executable sidecar describing the evidence contract; it does not replace the executable Vision verification stage.
- Live GUI Vision cards show Active Cam confirmation and VLA camera-return state from `active_cam_ejection_check` and `transfer_readiness`.

<a id="active-cam-실행-산출물-수명주기"></a>

## Active Cam Run-Artifact Lifecycle

An Active Cam frame that successfully confirms SPC autoejection is copied to a
normal run artifact at the following path rather than exposing the camera runtime's
temporary path directly.

```text
runs/<run_id>/vision/<observation_id>/active_cam_capture_<timestamp>.<ext>
```

- Vision Agent returns an `active_cam_run_artifact.v1` descriptor as
  `active_cam_artifact_update`.
- Both LangGraph execution and manual Live GUI handoff save successful descriptors
  in `run_metadata.latest_active_cam_artifact`.
- Subsequent Manipulation/UTM Vision handoffs that do not invoke Active Cam leave
  this value unchanged. The display therefore persists until the next explicit
  Active Cam attempt completes, and refreshing page state returns the same artifact URL.
- The next successful attempt replaces it with a new artifact. If the next attempt
  is `failed`, `blocked`, or `error`, only the current display pointer is removed;
  existing run-artifact files are not deleted.
- The Live GUI prefers `/api/runs/<run_id>/artifact-file/...` paths.
  Base64 and browser-session caches are not evidence-preservation mechanisms.

## Limitations and Known Gaps

- This reference describes current interfaces. It does not authorize device-specific
  live execution or replace device safety conditions.
- The `/api/bridges` graph-bridge registry and `/api/printer/fleet` printer-provider
  selection are separate layers.
- Custom stages require module/graph validation and allowlisted handlers. A visible
  descriptor does not, by itself, attach a stage to the runtime.
- Historical browser screenshots and pass counts are evidence from their stated
  dates. Revalidate them when the GUI or cache keys change.

## Verification

Review covers the default graph, FastAPI page/API routes, agent/module registry,
Knowledge Workspace, and Live GUI event/artifact connections. Check current route
and graph counts with the reproduction commands in
[Current Code Snapshot](current_code_snapshot.md). Source review is distinct from
validation through actual device execution.

## Related Documents

- [Current Code Snapshot](current_code_snapshot.md)
- [LangGraph Runtime](langgraph_runtime.md)
- [Markdown Knowledge Operations Guide](../knowledge/markdown_memory_operations.ko.md)
- [Documentation Standard](../standards/documentation_standard.md)
