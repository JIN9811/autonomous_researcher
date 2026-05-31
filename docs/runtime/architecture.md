# Architecture

## Core flow

`FastAPI Controller -> LangGraphRunLoop -> Compiled LangGraph Node -> Stage Agent -> Autonomous Experiment Runtime / MCP Tool -> State Update -> Event Stream -> Web GUI`

The orchestrator uses explicit `Stage` enums plus `graphs/configs/atr_closed_loop.yaml` to compile a LangGraph-backed, debuggable, and resumable runtime path. Runtime IDE also discovers workspace graph templates from `graphs/configs/printer_pipeline.yaml`, `graphs/configs/lerobot_pick_place.yaml`, and `graphs/configs/utm_test_flow.yaml` for validate/compile/dry-run/versioning and gated test-mode execution through the same run loop.

Live GUI handoff flow:

`Live GUI Chat -> MainController -> configured LangGraph stages -> Stage Agent -> MCP-style Tool/Device Bridge -> runtime event stream`

This route reuses the same agents and tool contracts as the run loop, but presents the handoff as a conversation. Design/Specimen handoff and the downstream tail are resolved from the active graph config, so changing `graphs/configs/*.yaml` changes both runtime execution and Live GUI route text.
Tool-level runtime callbacks may stream progress back to the controller before an agent returns its final `AgentResult`.

The runtime-facing experiment API is documented in `runtime/autonomous_experiment_runtime.md`.
It standardizes `ExperimentObjective`, `ExperimentCandidate`, `ExperimentExecution`,
and `ExperimentEvaluationResult` so test, virtual, and live bridge paths remain externally consistent.

## Agent responsibilities

- `orchestrator_agent`: top-level planning text
- `bo_agent`: mandatory LangGraph stage after `knowledge_agent` and before `guardian_agent`; exposed through `/bo` for acquisition/BO/MBO controls. It consumes KnowledgeAgent context and writes next-cycle DesignAgent constraints to `run_metadata["bo_recommended_constraints"]`.
- `design/specimen/vision/manipulation/equipment/analysis/knowledge/guardian`: stage-specific execution
- `specimen_agent`: geometry/handoff owner plus printer preparation delegation; it does not directly implement PrusaLink write logic.
- `experiment.evaluate`: common evaluation facade that routes candidates through virtual scoring or a hardware bridge while preserving session/experiment IDs.
- `experiment.benchmark`: random/grid/BO comparison mode for objective and candidate-generation validation.
- `experiment.queue.status`: current device-job queue diagnostics for printer, robot, and Windows equipment actions.
- `/bo`: dedicated BO Workspace for acquisition function, BO/MBO strategy, budget, and parameter-space tuning.
- `/cae`: dedicated CAE Analysis Workspace for bottom-fixed/top-cyclic simulation settings and metric review.
- `printer.prepare`: internal PrusaSlicer/PrusaLink boundary for slicing, upload/start gates, and ejection gates.
- `vision_agent`: lightweight 3DP output-area observation owner. It combines `camera.capture` with the latest `specimen_result` and emits `pose_estimate`, `pickup_target`, and `transfer_readiness` for the robot transfer stage.
- `manipulation_agent`: robot manipulation owner. The compatibility path keeps `robot.pick_place`; the LeRobot path calls `lerobot.rollout.start`. After a ready `specimen_result`, the default transfer strategy is Pi0.5 LeRobot rollout from `3dp_output_area` to `utm_fixture` unless the spec explicitly requests `fixed_kinematic`. Operator-saved Manipulation Agent defaults are loaded from `memory/manipulation_agent_bridge.json` before each live/test loop execution, with explicit experiment fields taking precedence.
- `equipment_agent`: Lab Equipment owner. It uses `equipment.pyautogui.health`, `equipment.pyautogui.list_programs`, `equipment.pyautogui.run`, and `equipment.pyautogui.request_log` through the Windows PyAutoGUI Bridge, then hands `equipment_result`, `equipment_report.v1`, `utm_data_ready.v1`, and `equipment_handoff` to Analysis with screen/data/vision/request-audit evidence refs.
- `analysis_agent`: UTM-data analysis owner. It extracts force/displacement curves from `equipment_result` inline data or CSV/JSON files, computes mechanical metrics and objective score, calls `cae.run_static_analysis` when available, uses deterministic synthetic UTM/CAE data only in test mode, and blocks live analysis when real UTM data is missing.
- `device_bridges/cae_bridge.py`: CAE bridge for CalculiX/Gmsh preflight plus deterministic equivalent bottom-fixed/top-cyclic analysis used by test-mode closed-loop scoring.
- `device_bridges/lerobot_bridge.py`: LeRobot / ROBOTIS bridge with deterministic test sessions, command previews, step traces, and live gates.
- `/lerobot`: dedicated Manipulation Agent / LeRobot GUI opened from the main dashboard. It contains device setup, teleoperation, recording, training, direct rollout, and an agent-mediated `Manipulation Agent Bridge` panel.

SARM logic is embedded inside `manipulation_agent` under `submodules/sarm`.

LeRobot naming and rollout-duration rules are centralized in `runtime/lerobot_dataset_policy_naming.md`. Manipulation Agent passes intent fields such as `rollout_dataset_repo_id`, `continuous_rollout`, and `policy_type`; the bridge enforces `eval_` rollout dataset names for legacy rollout datasets, manual-stop conversion, and Pi0.5 runtime selection.

Dedicated workspace APIs for BO, CAE, printer autoejection, LeRobot, and Windows PyAutoGUI remain manual control surfaces, but execution results are normalized through `emit_workspace_result(...)` into `tool.completed/tool.failed`, optional `node.completed/node.failed`, and `artifact.created` runtime events. Main run creation is also event-backed: `MainController.start(...)` emits `run.created` before the LangGraph loop emits `run.started`. Controller-origin runtime events are persisted to the structured JSONL run log before SSE broadcast, keeping direct operator controls and graph runs visible to the same Runtime IDE timeline/artifact model without pretending workspace controls are the main closed-loop graph.


The executable graph is documented in `runtime/langgraph_runtime.md`.


## Runtime IDE configuration surface

The runtime exposes graph/module configuration endpoints for the `/ide` Runtime IDE.
Graph edits are validated, compiled, versioned, and only then activated. Module edits are limited to `graphs/modules/*/module.yaml` and must keep handlers inside the registered allowlist, which is generated from runtime control handlers plus all currently registered `AgentRegistry` entries.



### Module Runtime Binding

Module YAML is now bound into execution through `ModuleRuntimeContext`. Stage agents still run through their existing Python classes, but `module.handler` now resolves the actual `AgentRegistry` entry for the stage, and `ctx.complete(...)` observes the module's LLM role, backend, model, fallback model, system/developer prompt overrides, and timeout. `ctx.tools` is also wrapped by a stage-scoped allowlist from `module.tools`, so tool access is controlled by module config while preserving the shared ToolRegistry implementation. `module.safety.requires_human_approval` is enforced as a graph-level pause gate before the handler runs; approval resumes the same stage and rejection/cancellation fails the run. `module.retry.max_attempts/backoff_s` override the global stage retry policy. `module.internal_graph` now emits planning/start/completion/failure events for each step; steps without an explicit handler are checkpoints, and steps with an explicit `agent.*` handler execute that agent as an internal module step before the main module handler. Runtime events include a sanitized `module_runtime` payload so the IDE can audit which module config was active for each node execution. Live GUI planning handoffs use the same LangGraph single-step runtime for Design, Specimen, and the downstream tail, so chat-triggered workflows no longer bypass module runtime binding.

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
