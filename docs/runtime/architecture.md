# Architecture

## Core flow

`FastAPI Controller -> LangGraphRunLoop -> Compiled LangGraph Node -> Stage Agent -> Autonomous Experiment Runtime / MCP Tool -> State Update -> Event Stream -> Web GUI`

The orchestrator uses the backward-compatible `Stage` type plus `graphs/configs/atr_closed_loop.yaml` to compile a LangGraph-backed, debuggable, and resumable runtime path. Known ATR stages remain enum members, while graph-validated extension stages are preserved as `Stage._missing_()` pseudo-members so `.value` stays the serialized contract. Runtime IDE also discovers workspace graph templates from `graphs/configs/printer_pipeline.yaml`, `graphs/configs/lerobot_pick_place.yaml`, and `graphs/configs/utm_test_flow.yaml` for validate/compile/dry-run/versioning and gated test-mode execution through the same run loop.

Live GUI handoff flow:

`Live GUI Chat -> MainController -> configured LangGraph stages -> Stage Agent -> MCP-style Tool/Device Bridge -> runtime event stream`

This route reuses the same agents and tool contracts as the run loop, but presents the handoff as a conversation. Design/Specimen handoff and the downstream tail are resolved from the active graph config, so changing `graphs/configs/*.yaml` changes both runtime execution and Live GUI route text.
The Orchestrator supervisor plan also receives the active graph route from the controller; inserted graph stages such as custom quality gates appear in `latest_orchestration_plan`, `route_state`, and the Live GUI task queue instead of using the legacy fixed route.
Tool-level runtime callbacks may stream progress back to the controller before an agent returns its final `AgentResult`.

Live GUI agent metadata is also backend-derived. `/api/runtime/agent-manifests`
merges the active graph, `graphs/modules/*/module.yaml`, and optional
`graphs/modules/*/ui.yaml` files so the frontend can render agent tabs and
descriptor cards without treating `planning.js` hardcoded fallback data as the
runtime source of truth. `/api/bridges` exposes the normalized graph bridge
registry for GUI/IDE discovery, including workspace, health/preflight endpoints,
standard actions materialized under `actions[]`, evidence contracts, and health
snapshots. The same shape is embedded in
`/api/runtime/state.runtime_ide_contract.device_bridges`.
Bridge-specific APIs still own live execution.

The runtime-facing experiment API is documented in `runtime/autonomous_experiment_runtime.md`.
It standardizes `ExperimentObjective`, `ExperimentCandidate`, `ExperimentExecution`,
and `ExperimentEvaluationResult` so test, virtual, and live bridge paths remain externally consistent.

Objective authoring is a control-plane workflow before BO runtime evaluation.
AI Compose, Visual Builder, and Advanced JSON all produce the same
`objective_spec.v1` contract and enter the same deterministic lifecycle:

```text
AI research intent -----------+
Visual expression tree -------+--> draft --> validate --> preview --> approve --> activate(run_id)
Advanced objective JSON ------+                                      |
                                                                     v
Analysis evaluates registered metrics --> BO consumes objective_evaluation.v1
```

`GET /api/objectives/authoring-contract` is the frontend/backend compatibility
boundary for enabled compiler operators, fields, child shapes, supported units,
and AST limits. The browser keeps one canonical last-valid manual tree plus a
separate JSON edit buffer, so malformed JSON cannot corrupt the visual state.
`POST /api/objectives/manual` normalizes server-owned lifecycle, provenance,
registry, timestamp, and immutable version fields. Stored Objective selection
and unsaved authoring state remain separate until an operator explicitly loads
the selected version as a revision. None of these authoring routes executes an
experiment or bypasses Preview, approval, activation, Analysis evaluation, BO,
or Guardian.

LLM routing is configured from `configs/models.yaml` and surfaced through Main GUI
`Current Models`. The local-first default is NemoClaw/vLLM with `gemma4:31b` for
the orchestrator route and `gemma4:e4b-it-nvfp4` for subordinate `e4b` routes.
`/api/runtime/models`, `/api/runtime/models/load`, and
`/api/runtime/models/unload` control managed vLLM serving. `/api/runtime/api-key`
and `/api/runtime/api-key/load|unload` manage the local OpenAI key store
(`memory/api_keys.json`). When the key is loaded, OpenAI becomes the first
inference route; when unloaded, the saved key remains registered but local vLLM
returns to first priority.

## Agent responsibilities

- `orchestrator_agent`: top-level planning text
- `bo_agent`: mandatory LangGraph stage after `knowledge_agent` and before `guardian_agent`; exposed through `/bo` for acquisition/BO/MBO controls and bounded Objective Compiler authoring. It consumes KnowledgeAgent context and writes next-cycle DesignAgent constraints to `run_metadata["bo_recommended_constraints"]`.
- `design/specimen/vision/manipulation/equipment/analysis/knowledge/guardian`: stage-specific execution
- `specimen_agent`: geometry/handoff owner plus printer preparation delegation; it does not directly implement PrusaLink write logic.
- `experiment.evaluate`: common evaluation facade that routes candidates through virtual scoring or a hardware bridge while preserving session/experiment IDs.
- `experiment.benchmark`: random/grid/BO comparison mode for objective and candidate-generation validation.
- `experiment.queue.status`: current device-job queue diagnostics for printer, robot, and Windows equipment actions.
- `/bo`: dedicated BO Workspace for acquisition function, BO/MBO strategy, budget, parameter-space tuning, AI objective composition, template-free visual AST authoring, and advanced `objective_spec.v1` JSON authoring.
- `/cae`: dedicated CAE Analysis Workspace for bottom-fixed/top-cyclic simulation settings and metric review.
- `printer.prepare`: provider-neutral 3DP handoff boundary for slicing, upload/transfer, start gates, and ejection gates. The active printer provider is selected by the printer fleet registry; BambuLab X2D is the default provider and Prusa MK4S is an operator-selected provider, not a fallback path.
- `vision_agent`: lightweight 3DP output-area observation owner. It combines `camera.capture` with the latest `specimen_result` and emits `pose_estimate`, `pickup_target`, and `transfer_readiness` for the robot transfer stage.
- `manipulation_agent`: robot manipulation owner. The compatibility path keeps `robot.pick_place`; the LeRobot path calls `lerobot.rollout.start`. After a ready `specimen_result`, the default transfer strategy is Pi0.5 LeRobot rollout from `3dp_output_area` to `utm_fixture` unless the spec explicitly requests `fixed_kinematic`. Operator-saved Manipulation Agent defaults are loaded from `memory/manipulation_agent_bridge.json` before each live/test loop execution, with explicit experiment fields taking precedence.
- `equipment_agent`: Lab Equipment owner. It uses `equipment.pyautogui.health`, `equipment.pyautogui.list_programs`, `equipment.pyautogui.run`, and `equipment.pyautogui.request_log` through the Windows PyAutoGUI Bridge, then hands `equipment_result`, `equipment_report.v1`, `utm_data_ready.v1`, and `equipment_handoff` to Analysis with screen/data/vision/request-audit evidence refs.
- `analysis_agent`: UTM-data analysis owner. It extracts force/displacement curves from `equipment_result` inline data or CSV/JSON files, computes mechanical metrics and objective score, calls `cae.run_static_analysis` when available, uses deterministic synthetic UTM/CAE data only in test mode, and blocks live analysis when real UTM data is missing.
- `device_bridges/cae_bridge.py`: CAE bridge for CalculiX/Gmsh preflight plus deterministic equivalent bottom-fixed/top-cyclic analysis used by test-mode closed-loop scoring.
- `device_bridges/lerobot_bridge.py`: LeRobot / ROBOTIS bridge with deterministic test sessions, command previews, step traces, and live gates.
- `device_bridges/realsense_bridge.py`: fail-closed RealSense bridge for live camera discovery and guarded single-frame capture. Enumeration/profile validation never starts a stream; capture requires explicit `allow_stream=true` or `live_stream_confirmed=true` and an advertised stream profile. The class is present in the codebase but is not currently a standalone FastAPI workspace route.
- `device_bridges/bambu_bridge.py`: BambuLab X2D printer bridge for the default 3DP provider. It keeps printer fleet selection, Bambu Studio/Orca slicing, MQTT status/control, FTPS/HTTP artifact transfer, camera/video evidence, guarded `project_file` publish, and native G-code autoejection gates as separate runtime planes. Native Bambu autoejection is represented as `bambu_gcode_patch`: the bridge patches a sliced `.gcode.3mf` plate G-code, records tail metadata and a manifest, and only then exposes it to start-gate approval. The operating contract is documented in `hardware/bambulab_x2d_device_bridge_runtime_guideline.md`.
- `/lerobot`: dedicated Manipulation Agent / LeRobot GUI opened from the main dashboard. It contains device setup, teleoperation, recording, training, direct rollout, and an agent-mediated `Manipulation Agent Bridge` panel.

SARM logic is embedded inside `manipulation_agent` under `submodules/sarm`.

LeRobot naming and rollout-duration rules are centralized in `runtime/lerobot_dataset_policy_naming.md`. Manipulation Agent passes intent fields such as `rollout_dataset_repo_id`, `continuous_rollout`, and `policy_type`; the bridge enforces `eval_` rollout dataset names for legacy rollout datasets, manual-stop conversion, and Pi0.5 runtime selection.

Dedicated workspace APIs for BO, CAE, printer autoejection, LeRobot, and Windows PyAutoGUI remain manual control surfaces, but execution results are normalized through `emit_workspace_result(...)` into `tool.completed/tool.failed`, optional `node.completed/node.failed`, and `artifact.created` runtime events. Main run creation is also event-backed: `MainController.start(...)` emits `run.created` before the LangGraph loop emits `run.started`. Controller-origin runtime events are persisted to the structured JSONL run log before SSE broadcast, keeping direct operator controls and graph runs visible to the same Runtime IDE timeline/artifact model without pretending workspace controls are the main closed-loop graph.


The executable graph is documented in `runtime/langgraph_runtime.md`.

## 3DP / Bambu execution boundary

The BambuLab path is intentionally split into evidence-producing stages instead of a single "upload and print" action.

```text
DesignAgent
  -> SpecimenMakingAgent
  -> printer.prepare
  -> PrinterDeviceBridgeManager
  -> BambuLabBridge
      -> camera/status evidence
      -> Bambu Studio/Orca slicing
      -> optional bambu_gcode_patch autoejection artifact
      -> FTPS or HTTP artifact transfer evidence
      -> start-gate check
      -> MQTT project_file publish only after live approval
      -> post-publish observation
      -> bed-clear evidence before the next job
```

Current validation status is deliberately separated from physical success. Non-motion validation has confirmed sliced `.gcode.3mf` generation, internal `Metadata/plate_1.gcode` patching, md5 sidecar update, deterministic autoejection manifest creation, and HTTP artifact route preparation from the ATR server LAN address. Current 3DP GUI requests use owner-managed publish defaults instead of manual approval/checklist widgets, so blocked pre-start checks should now be interpreted through artifact validity, camera frame requirement, bed-clear lock, printer safe-state, transfer route, and start-command draft evidence. A proof package that claims the physical start precheck passed must point to a saved `/api/printer/bambu-prestart-check` snapshot with `ready_to_publish_not_started`, `published=false`, and `will_publish=false`; a hand-written boolean is not enough. When a guarded `.autoeject.*` publish succeeds, the bed-clear lock records the remote path, subtask name, source/patched artifact path and sha256 when a sidecar manifest is available, publish sequence/topic, post-publish status, and camera snapshot reference. A physical proof package must also keep saved `printer.bambu.start_publish` response snapshots for center standalone ejection, left/right lane ejection, and disposable live ejection, and must match each snapshot's start gate state, remote path, publish sequence/topic, and running post-publish state against the corresponding proof entry. A publish snapshot with blockers, `ready_to_publish=false`, or `start_enabled=false` is not completion evidence even if it says `published=true`. Physical ejection is not considered complete until a supervised printer run proves the motion and a camera/bed-clear evidence record unlocks the next job.

The mechanical completion check for this path is `scripts/audit_bambu_autoejection_completion.py`. It is intentionally non-actuating: it only reads a persisted proof package and returns `complete_evidence_verified` when center ejection, disposable live ejection, left/right lane evidence, bed-clear evidence, and the next-job gate are all file-backed. Center before/after camera evidence must be distinct files, not a reused snapshot, and the center standalone proof must point to a local artifact containing the ATR autoejection marker and `atr_position=center`. It must also point to a saved `/api/printer/start-publish` response snapshot with matching remote path, publish sequence/topic, and running post-publish state. The disposable live proof must point to local source/patched artifact files whose sha256 values match the proof and to its own saved `/api/printer/start-publish` response snapshot. Each publish snapshot must be `tool=printer.bambu.start_publish`, `ok=true`, `published=true`, `ready_to_publish=true`, `start_enabled=true`, no blockers, and must carry a matching remote path, publish sequence/topic, and running post-publish state. The patch manifest evidence is not only a file-existence check: it must use `bambu_autoejection_artifact_manifest.v1`, match the source/patched sha256 values in the live proof, and carry a clean validator result. Bed-clear evidence is also tied back to the same live artifact: it must name `operator`, `camera`, or `vision` as the verification method and repeat the live source/patched sha256 values before the next-job gate can be considered clear. The next-job gate is not a boolean-only claim either: the proof must include a saved `/api/printer/start-gate` snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, and no `BAMBU_POST_EJECT_BED_NOT_CLEAR` code. Left/right lane evidence cannot be boolean-only either: each lane must point to a local artifact containing the ATR autoejection marker and the matching lane position marker, a saved validation snapshot with matching position and no validator blockers, and a saved `/api/printer/start-publish` response snapshot with matching remote path, publish sequence/topic, and running post-publish state. The 3DP GUI exposes the same rule through `POST /api/printer/bambu-autoejection-proof-template` and `POST /api/printer/bambu-autoejection-completion-audit`; both endpoints are read/write-audit helpers only and do not upload, publish MQTT, capture live images, or move the printer. These endpoints are also provider-gated: if the active printer profile is Prusa or any non-Bambu provider, they return `BAMBU_PROOF_TEMPLATE_NOT_APPLICABLE` or `BAMBU_COMPLETION_AUDIT_NOT_APPLICABLE` and do not create proof files. If the center standalone proof, left/right lane proof, or disposable live proof shows a `project_file`-style publish but the post-publish state remained `idle`, `ready`, or otherwise not-started, completion audit returns `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED` instead of treating the run as verified. This keeps system documentation, Live GUI reports, and device bridge behavior aligned: `published=true`, HTTP route readiness, validator pass, proof-template creation, or a GUI success banner cannot be described as physical Bambu autoejection success by themselves.

The Bambu bridge follows print-farm and community patterns only at the architectural level: local LAN control, sliced artifact transfer, cooldown/release, toolhead-based clearing, camera observation, and next-job gating. It does not embed third-party G-code verbatim. External references are kept in the Bambu hardware guideline and the 14th improvement plan so this architecture page remains a source-backed system explanation instead of an untraceable script collection.

The bridge uses five evidence planes to keep the system explanation aligned with runtime behavior: artifact, validation, transport, runtime, and bed-clear. This is intentionally stricter than a direct `start print` button. Loop-style Bambu tools and community G-code workflows show that cooldown and push-off can be automated, while Bambu local-control integrations show that FTPS upload, MQTT `project_file` publish, AMS mapping, and post-publish state observation are separate concerns. ATR therefore treats BambuLab as the default active printer provider but not as a fallback target, and it treats Prusa as an operator-selected provider with the same high-level `printer.prepare` boundary.


## Runtime IDE configuration surface

The runtime exposes graph/module configuration endpoints for the `/ide` Runtime IDE.
Graph edits are validated, compiled, versioned, and only then activated. Module edits are limited to `graphs/modules/*/module.yaml` and must keep handlers inside the registered allowlist, which is generated from runtime control handlers plus all currently registered `AgentRegistry` entries.

Runtime IDE is required to reflect the actual runtime contract, not an approximate concept map. The active graph `graphs/configs/atr_closed_loop.yaml` now includes non-executable control-plane nodes for `orchestrator_supervisor`, `safety_gate_plane`, `device_bridge_plane`, and `memory_evidence_plane`. `graphs.validator` and `graphs.compiler` exclude those nodes and their `control_overlay`, `device_bridge`, `evidence_flow`, and `runtime_sidecar` edges from executable LangGraph compilation, while `/ide` renders them as runtime overlays. `/api/state` also returns `runtime_ide_contract`, built from the active graph metadata plus every `graphs/modules/*/module.yaml`, so the IDE can show declared runtime planes, output contracts, module contracts, and device bridge boundaries from the same files used by the backend.



### Module Runtime Binding

Module YAML is now bound into execution through `ModuleRuntimeContext`. Stage agents still run through their existing Python classes, but `module.handler` now resolves the actual `AgentRegistry` entry for the stage, and `ctx.complete(...)` observes the module's LLM role, backend, model, fallback model, system/developer prompt overrides, and timeout. `ctx.tools` is also wrapped by a stage-scoped allowlist from `module.tools`, so tool access is controlled by module config while preserving the shared ToolRegistry implementation. `module.safety.requires_human_approval` is enforced as a graph-level pause gate before the handler runs; approval resumes the same stage and rejection/cancellation fails the run. `module.retry.max_attempts/backoff_s` override the global stage retry policy. `module.internal_graph` now emits planning/start/completion/failure events for each step; steps without an explicit handler are checkpoints, and steps with an explicit `agent.*` handler execute that agent as an internal module step before the main module handler. Runtime events include a sanitized `module_runtime` payload so the IDE can audit which module config was active for each node execution. Live GUI planning handoffs use the same LangGraph single-step runtime for Design, Specimen, and the downstream tail, so chat-triggered workflows no longer bypass module runtime binding. Optional `ui.yaml` files are intentionally outside this execution binding and only describe Live GUI presentation.

### Runtime IDE Config Guarantees

- Runtime IDE transition edits are persisted in both `graph.transitions` and YAML logical transition edges.
- Graph validation rejects disconnected runtime nodes, unknown module references, and missing Guardian dispatch/transition when graph safety metadata requires Guardian.
- Compile, validate-draft, import, save, dry-run, and run endpoints return `compiled_graph` summaries so the GUI can display the executable graph that was actually checked. Those endpoints also publish `graph.compiled` on success and `graph.validation_failed` on schema/handler/compile failures so the Runtime IDE timeline can audit configuration operations, not only active runs. Graph dry-run additionally returns per-stage `effective_handler` and `module_runtime` evidence plus a digest-backed `dry_run_record` so module handler/step edits are visible before activation. Live run endpoints reject execution with `GRAPH_DRY_RUN_REQUIRED` when the latest dry-run digest does not match the active graph config. Workspace templates now execute through the same LangGraph run loop for test/replay/fault-injection; live execution remains gated by graph metadata.
- Logical transition edges are audit/UI edges; executable LangGraph edges remain dispatch/step boundaries to preserve one-stage-per-step behavior.
- Module configs are parsed through `graphs.schema.ModuleConfig` and support validate/dry-run APIs before versioned activation.
- Run compatibility APIs expose run snapshots, buffered events, and run-directory artifact listings.

- Runtime IDE now shows a run timeline and artifact lineage sourced from `/api/runs/{run_id}/events` and `/api/runs/{run_id}/artifacts`; a timeline event can be selected to focus node state and dry-run from that stage.

- Runtime artifact lineage now exposes path-safe inline preview/download via `/api/runs/{run_id}/artifact-file/{artifact_path}`; the IDE previews text/image artifacts and offers downloads for all files.

- Runtime graph nodes now carry `GraphNode.position`; the Runtime IDE uses it for drag/snap layout, visual transition edges, zoom controls, and minimap rendering while persisting edits as config changes.

- Runtime IDE supports click-based edge connect/disconnect. These actions mutate graph config (`transitions` and logical edges) and require validate/save before activation.
- Runtime IDE supports graph YAML export/import. Imports are parsed, schema-validated, and compile-checked as drafts; activation still requires an explicit versioned save.
- Runtime IDE supports module internal graph step reordering/add/delete, handler dropdown edits, prompt path/override edits, tool list edits, LLM backend/model hints, timeout/retry policy, and safety flags as module config edits only; Python source remains immutable from the IDE and handler values come from the registry allowlist.
- Runtime IDE validation must include hands-on feature exercise: graph selection across primary/workspace templates, Top Bar state/control buttons, Graph Explorer search/select, Agent/Device/Metrics/Approval panels, approval request/resolve API flow, node drag, edge edit/connect/delete, YAML export/import, module handler/step edit, module prompt/tool/LLM/backend config edit, live timeline, replay, artifact preview, workspace API calls, debugging of failures found during exercise, and full regression tests.

### 2026-05-29 Vision signal bus update

`vision_agent` now acts as a lab perception signal bus. It still provides the
legacy pickup observation consumed by Manipulation, but also emits
`vision_report.v1` and `vision_signal.v1` with zone state, confidence,
freshness, visual evidence paths, and Knowledge/Guardian handoff context.

### 2026-05-30 Windows bridge request-audit GUI update

`/equipment/windows` now surfaces Windows PyAutoGUI bridge request-audit evidence directly in the Linux GUI. The page includes a Bridge Request Audit card backed by `POST /api/equipment/windows/request-log`, and live preflight includes `/request-log` by default while remaining non-actuating. The audit payload is sanitized before returning to the browser so token values are not exposed. Missing or identity-mismatched request-audit evidence is a hard live Equipment -> Analysis handoff gate together with screen-state evidence, Vision evidence, save/export responsibility, Linux UTM artifact pull, and parse probes.
