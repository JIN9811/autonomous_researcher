# Agent Program Integration Baseline

This document is the baseline contract for integrating real programs into the existing multi-agent runtime.
Use it when replacing mock logic with production device/program logic in each agent.

## Scope

- Runtime: `FastAPI + LangGraphRunLoop + config-driven LangGraph stage transitions`
- Control plane: GUI and API endpoints in `app/main.py`
- Agent contract: `BaseAgent.run(state, ctx) -> AgentResult`
- Model hierarchy: `orchestrator (31B primary, E4B fallback) + e4b subordinate`
- Tool contract: `ToolRegistry.call(name, payload)`

## Canonical Runtime Topology

```text
User/GUI
  -> MainController
    -> LangGraphRunLoop
      -> selected graphs/configs/*.yaml
      -> Compiled LangGraph node
      -> (design stage only) OrchestratorAgent
      -> Stage Agent (design/specimen/vision/manipulation/equipment/analysis/knowledge/bo/guardian)
        -> ToolRegistry / RAG / DB / FailureMemory / Backends
```

Cycle order:

1. `design`
2. `specimen`
3. `vision`
4. `manipulation`
5. `equipment`
6. `analysis`
7. `knowledge`
8. `bo`
9. `guardian`
10. `guardian=continue` routes back to `design`
11. `guardian=stop` routes to `complete`, `guardian=error` routes to `error`

## Hard Contracts (Do Not Break)

### 1) Stage and state names

- Stage enum values in `orchestrator/state.py` are API/GUI/test-facing contracts.
- Do not rename existing stages without updating graph config, GUI map, and tests together.

### 2) Agent interface

- Every agent must implement:
  - `name: str`
  - `async run(state: OrchestratorState, ctx: AgentContext) -> AgentResult`
- `AgentResult` fields:
  - `success: bool`
  - `summary: str`
  - `data: dict[str, Any]`
  - `next_hint: str | None` (optional)

### 3) Runtime-required payload keys (validated)

The current validation policy enforces these keys:

| Stage | Required key(s) in `AgentResult.data` |
|---|---|
| `design` | `experiment_spec` |
| `vision` | `observation` |
| `equipment` | `equipment_result`, `protocol_note` |
| `analysis` | `analysis` |
| `guardian` | `guardian` |

If a required key is missing, the stage is retried and may end in `fatal_error`.

### 4) Stage-to-agent routing

| Stage | Agent |
|---|---|
| `design` | `design_agent` |
| `specimen` | `specimen_agent` |
| `vision` | `vision_agent` |
| `manipulation` | `manipulation_agent` |
| `equipment` | `equipment_agent` |
| `analysis` | `analysis_agent` |
| `knowledge` | `knowledge_agent` |
| `bo` | `bo_agent` |
| `guardian` | `guardian_agent` |

## Agent Integration Baseline

When replacing internals with real programs, keep these output keys stable.

| Stage | Runtime-required keys | Current output keys | Real program integration target |
|---|---|---|---|
| `design` | `experiment_spec` | `experiment_spec`, `rationale` | protocol/candidate generation service |
| `specimen` | none | `specimen_result`, `protocol_note` | geometry handoff + provider-neutral printer bridge; Bambu Lab X2D is the default provider and PrusaLink is an explicit profile |
| `vision` | `observation` | `observation`, `protocol_note` | 3DP output pickup observation via `camera.capture` |
| `manipulation` | none | `manipulation`, `sarm`, `manipulation_report`, `robot_task_result`, `handoff_packet`, `protocol_note` | bounded robot skills through `robot.pick_place` or Pi0.5/LeRobot rollout |
| `equipment` | `equipment_result`, `protocol_note` | `equipment_result`, `protocol_note`, `equipment_handoff` | Windows PyAutoGUI bridge macro runner or legacy UTM runner |
| `analysis` | `analysis` | `analysis` | UTM curve feature extraction + CAE closed-loop objective/uncertainty post-processor |
| `knowledge` | none | `knowledge` | local+web RAG and memory writer |
| `guardian` | `guardian` | `guardian` | safety/policy engine |

Notes:

- SARM remains a submodule under `manipulation_agent` (not top-level stage).
- Manipulation emits `manipulation_report.v1` and `robot_task_result.v1`; downstream agents and GUI reports must consume those structured packets rather than scraping raw rollout logs.
- Design-stage orchestrator planning is declared as `module.pre_execution` in `graphs/modules/design/module.yaml` (`orchestrator_plan -> agent.orchestrator_agent`) and writes plan metadata to `state.run_metadata.orchestrator_plan`; it must not be reintroduced as a hard-coded run-loop special case.
- Live GUI planning may skip that pre-execution step only after the chat orchestrator has already approved the same Design handoff, to avoid duplicate model calls.
- Live GUI agent tabs and descriptor cards are loaded from `/api/runtime/agent-manifests`, not directly from hard-coded JavaScript. The manifest merges `graphs/configs/atr_closed_loop.yaml`, `graphs/modules/*/module.yaml`, and optional presentation-only `graphs/modules/*/ui.yaml`.
- Module Management may create preview modules through `/api/modules/templates/{agent|ui-only|bridge}`. These draft modules are intentionally `enabled=false`, `status=draft`, and `graph.attached=false`; they cannot execute until attached, validated, dry-run, and saved with allowlisted handlers/tools.
- Module Designer may create a source-backed module through `POST /api/modules`. The backend can use the active module-designer LLM route to convert Python source into ATR protocol shape, stores the original source and generated `handler.py`, and marks the module as pending generated-adapter registration when needed.
- `POST /api/modules/{module_id}/register-generated` is the explicit approval path for generated adapters. It validates `handler.py`, sets the handler to `module.generated_adapter`, records `generated_adapter_approved=true`, and writes a versioned active module config. This still does not bypass graph validation or dry-run gates.
- Module Management `Load/Unload` controls are workbench selection state only. API responses expose `runtime_effect.changes_runtime_execution=false`; a loaded module is not active in the closed loop until a graph node references it and the graph has been validated/dry-run.
- Module Management lifecycle responses also expose `activation_status`,
  `activation_requirements`, `ready_for_live_activation`, and
  `next_required_action`. These are readiness indicators only; they do not
  attach graph nodes, save graph versions, or start live execution.
- Graph-validated custom stage strings are currently accepted through
  `Stage._missing_()` pseudo-members, and controller/supervisor route snapshots
  can show inserted stages. Custom stages may also provide a
  `supervisor_policy` descriptor in the stage payload or `module_runtime` to
  customize Orchestrator follow-up opinion/recommendation text, required-output
  formatting, concern rules, operator options, and response-required statuses.
  The current Module Management typed form exposes the main supervisor-policy
  descriptor fields. Module Management can hand graph-unattached modules to
  Runtime IDE attach mode via `/ide?module=<id>&action=attach`, but the graph
  edit itself still uses Runtime IDE drag/drop plus validate/dry-run/Save
  Version gates. Remaining custom-stage report authoring and deeper activation
  authoring are tracked under
  `개선안/12_free_modularization_gap_analysis.md`.

## Model Hierarchy Baseline

Configured defaults (`configs/models.yaml`):

- `orchestrator`: `gemma4:31b` (fallback `gemma4:e4b-it-nvfp4`)
- `e4b`: `gemma4:e4b-it-nvfp4` (fallback `gemma4:31b`)
- `e4b subordinate`: `gemma4:e4b-it-nvfp4` (fallback `gemma4:31b`)
- Backend fallback: `openai`, using `gpt-5.5` by default when the active local
  backend and its model fallback both fail. Set `AUTONOMOUS_BACKEND=openai` only
  when intentionally skipping local inference.

NemoClaw/vLLM deployment repos:

- `gemma4:31b`: `nvidia/Gemma-4-31B-IT-NVFP4`
- `gemma4:e4b-it-nvfp4`: `bg-digitalservices/Gemma-4-E4B-it-NVFP4`

The vLLM branch uses `*-nvfp4` aliases so runtime status reflects the actual served checkpoint. The `ollama` and `nemoclaw` proxy branches keep their installed local Ollama tags.

Gemma4 MTP speculative decoding is enabled only for the current
`gemma4:31b` NemoClaw/vLLM deployment. Use a vLLM image that includes Gemma4
MTP support (`vllm/vllm-openai:v0.21.0-cu129-ubuntu2404` or newer). Older local
`vllm/vllm-openai:latest` / `latest-cu130` images around vLLM `0.20.0` do not
include the Gemma4 MTP path. The earlier `gemma4-0505-cu130` tag has the MTP
path but failed local verification with assistant weight shape mismatch, so it
is not used.

GB10/NVFP4 backend requirement:

- Set `VLLM_NVFP4_GEMM_BACKEND=marlin` on every Gemma4 NVFP4 deployment.
- Do not use the automatic FlashInfer FP4 path on this host; it fails with `CUDA error: no kernel image is available for execution on the device`.
- Do not force `cutlass` on this host; it reaches the vLLM CUTLASS path but fails during profile run with `cutlass_scaled_fp4_mm` internal errors.
- Verified working path for speculative serving: `MarlinNvFp4LinearKernel` +
  Gemma4 MTP assistant on `gemma4:31b` via `/v1/chat/completions`.
- Verified stable target-only serving path: `MarlinNvFp4LinearKernel` on
  `gemma4:e4b-it-nvfp4`. Do not enable MTP for E4B unless the local CUDA
  device-side assert issue is revalidated and resolved.

MTP assistant mapping:

- `gemma4:31b`: `google/gemma-4-31B-it-assistant`, `num_speculative_tokens=4`
- `gemma4:e4b-it-nvfp4`: MTP disabled, `num_speculative_tokens=0`

NemoClaw/vLLM GPU residency profile:

- `gemma4:31b`: `--gpu-memory-utilization 0.37`
- `gemma4:e4b-it-nvfp4`: `--gpu-memory-utilization 0.14` with `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0`
- The current managed model list is intentionally limited to two deployments: 31B and E4B. E2B is not part of the active `/api/runtime/models` surface.
- This profile is intentionally asymmetric so the two managed deployments can remain resident on the 120 GB class GPU.
- Keep E4B at the low-residency `0.14` profile while 31B remains resident. vLLM 0.21 CUDA graph memory estimation can incorrectly force a higher reservation on this GB10/NVFP4 profile, so E4B disables `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS` instead of raising the memory fraction. This profile was verified with 31B loaded: both `/v1/chat/completions` probes returned `OK`, E4B reserved about 15.7 GiB, and total system memory stayed at about 99 GiB used. Revalidate before raising E4B above `0.14`.

Live GUI startup policy:

- No automatic NemoClaw/vLLM model loading is performed by server startup, Live GUI open, backend switching, run start, or planning bootstrap.
- Operators manually load the required model through the main dashboard per-model Loading buttons or `atr model load <e4b|31b>`.
- Model-backed requests assume the target vLLM deployment is already loaded. If it is not loaded, the request should fail visibly instead of issuing hidden Kubernetes scale-up commands.
- The main dashboard exposes per-model Loading/Unloading controls and deployment status dots for the managed NemoClaw/vLLM models.
- OpenAI API-key loading is managed separately through `/api/runtime/api-key`. When enabled, OpenAI becomes the first inference route while preserving the saved key in local `memory/api_keys.json`; raw key text is never returned by API responses.

Task routing baseline:

- `orchestrator_plan -> orchestrator`
- `design_reasoning -> e4b`
- `analysis_reasoning -> e4b`
- `knowledge_query -> e4b`
- `guardian_reasoning -> e4b`
- `tool_formatting -> e4b`

## Live GUI Runtime Event Baseline

`AgentContext` includes two optional callbacks used by the controller:

- `on_model_call`: records active model work and cancels pending transition tasks; it must not issue model load/scale-up commands.
- `on_tool_event`: streams tool-level runtime progress into the Live GUI conversation.

Current tool-level event producer:

- `printer.prepare` emits per-step progress for the Specimen Making Agent path.
- `lerobot.*` emits per-step progress for the Manipulation Agent / LeRobot path.
- `equipment.pyautogui.run` emits per-step progress for the Equipment Agent / Windows GUI macro path.
- `cae.run_static_analysis` provides bottom-fixed/top-cyclic CAE metrics for Analysis Agent and `/cae`.
- Main loop stage order includes `Manipulation -> Equipment -> Analysis`; Equipment stage results are stored in `run_metadata.equipment_result`, `run_metadata.equipment_handoff`, and summary fields under `latest_analysis`.
- Equipment validation requires `equipment_result` and `protocol_note`. If `equipment_result.ok` is false, the loop retries or errors instead of continuing to Analysis.
- Analysis Agent reads UTM data from `run_metadata.equipment_result.utm_data`/`utm_curve`/`curve` or from `result_file`/`result_path`/CSV/JSON paths.
- Test mode may synthesize a deterministic UTM curve when no data is available; live mode must not fabricate UTM metrics and returns `UTM_DATA_REQUIRED` when no readable data is present.
- Test mode also runs deterministic equivalent CAE when `cae.run_static_analysis` is registered; Analysis blends CAE structural score into `objective_score` and records `analysis.closed_loop_sources`.
- Typical steps: `PRECHECK`, `RESOLVE_STL`, `PRUSALINK_STORAGE`, `VALIDATE_MESH`, `SLICE`, `VALIDATE_GCODE`, `UPLOAD`, `START_PRINT`, `MONITOR_PRINT`, `COOLDOWN`, `AUTO_EJECT`, `VERIFY_EJECTED`, `DONE`.
- Runtime events are best-effort UI/logging signals and must not alter hardware safety gates.

## Tool Contract Baseline (MCP-style)

Current tool names expected by agents:

- `printer.prepare`
- `camera.capture`
- `robot.pick_place`
- `utm.run_protocol`
- `equipment.pyautogui.health`
- `equipment.pyautogui.list_programs`
- `equipment.pyautogui.run`
- `equipment.pyautogui.connection_status`
- `equipment.pyautogui.save_connection`
- `cae.health`
- `cae.run_static_analysis`
- `lerobot.profiles.list`
- `lerobot.profiles.validate`
- `lerobot.find_ports`
- `lerobot.teleoperate.start`
- `lerobot.teleoperate.stop`
- `lerobot.teleoperate.status`
- `lerobot.record.start`
- `lerobot.record.control`
- `lerobot.record.status`
- `lerobot.train.start`
- `lerobot.train.cancel`
- `lerobot.train.status`
- `lerobot.rollout.start`
- `lerobot.rollout.stop`
- `lerobot.rollout.status`
- `lerobot.dataset.inspect`
- `lerobot.policy.download`
- `device.health`

Payload baseline:

| Tool | Minimal payload keys | Typical response keys |
|---|---|---|
| `printer.prepare` | `specimen_id`, optional `stl_path` | `ok`, `tool`, `specimen_id`, `status`, `printer_path`, `printer_mode`, `sliced_path`, `slicer_settings`, `slicer_result`, `gcode_validation`, `printer`, `prusalink`, `print_result`, `ejection_result`, `step_trace` |
| `camera.capture` | `frame_id`, optional `camera_key`, `purpose`, `specimen_id` | `ok`, `tool`, `frame_id`, `camera_key`, `source`, `anomaly` |
| `robot.pick_place` | `task` | `ok`, `tool`, `grasp_score`, `task` |
| `utm.run_protocol` | `profile`, `runtime_mode`, optional `run_id`, `specimen_id`, `result_file`, `direct_backend_configured` | test: parseable `result_file`/`utm_csv_path`, `data_acquisition`, `cross_checks`; live without explicit direct backend: `ok=false`, `failure_code=UTM_DIRECT_BACKEND_NOT_CONFIGURED` |
| `equipment.pyautogui.health` | none | `ok`, `tool`, `status`, `screen`, `pyautogui` |
| `equipment.pyautogui.list_programs` | none | `ok`, `tool`, `programs` |
| `equipment.pyautogui.run` | `program_id` or `sequence` | `ok`, `tool`, `status`, `program_id`, `program_log`, `step_trace`, `failure_code` |
| `equipment.pyautogui.connection_status` | none | `ok`, `bridge_url`, `token_configured`, `connection_memory_path` |
| `equipment.pyautogui.save_connection` | `host` or `bridge_url`, optional `token` | `ok`, `bridge_url`, `selected`, `token_configured` |
| `cae.health` | none | `ok`, `tool`, `calculix`, `gmsh`, `defaults`, `artifact_dir` |
| `cae.run_static_analysis` | `runtime_mode`, `specimen_id`, `specimen_size_mm`, `material`, `loading`, `boundary` | `ok`, `tool`, `status`, `boundary_condition`, `loading_mode`, `metrics`, `cae_metrics`, `artifacts`, `step_trace`, `closed_loop_source` |
| `lerobot.find_ports` | `mode`, optional `profile_id` | `ok`, `tool`, `mode`, `profile_id`, `ports`, `command_preview`, `step_trace` |
| `lerobot.teleoperate.*` | `mode`, `profile_id`, optional `session_id` | `ok`, `tool`, `workflow`, `session_id`, `status`, `command_preview`, `step_trace` |
| `lerobot.record.*` | `mode`, `profile_id`, optional `dataset_path`/`dataset_repo_id`/`session_id` | `ok`, `tool`, `workflow`, `session_id`, `status`, `dataset_path`, `command_preview`, `step_trace` |
| `lerobot.train.*` | `mode`, `profile_id`, optional `dataset_path`/`policy_type`/`output_dir` | `ok`, `tool`, `workflow`, `checkpoint_path`, `status`, `command_preview`, `step_trace` |
| `lerobot.rollout.*` | `mode`, `profile_id`, optional `policy_path`/`policy_repo_id`/`observation` | `ok`, `tool`, `workflow`, `session_id`, `status`, `command_preview`, `step_trace` |
| `lerobot.dataset.inspect` | `mode`, `profile_id`, optional `dataset_path`/`dataset_repo_id` | `ok`, `tool`, `dataset`, `step_trace` |
| `device.health` | none | `ok`, `printer`, `camera`, `robot`, `utm`, `simulator` |

Integration rule:

- Keep tool names stable unless agent code and tests are updated in same change set.
- Return at least `ok: bool` and deterministic keys consumed by downstream stages.

Printer-specific integration rule:

- Design Agent owns STL preview/artifact rendering in the Live GUI.
- Specimen Making Agent owns active slicer settings, G-code/3MF output path, selected-printer endpoint/gate status, and runtime step trace.
- Do not render the STL viewer again from Specimen Making Agent messages.
- Keep final design values consistent across `experiment_spec`, `printer.prepare.slicer_settings`, text chat, and Live GUI runtime cards.
- For Bambu X2D live use, `printer.prepare` must expose MQTT/FTPS/video evidence and keep upload/start blocked until the selected Bambu gates pass. For Prusa MK4S live use, it must expose storage readiness and map unavailable USB storage to `PRINTER_STORAGE_UNAVAILABLE` before upload/start.
- `layer_height_mm` and `nozzle_diameter_mm` must be copied as numeric top-level `experiment_spec` fields and must override any value inferred from `slicer_profile_hint` or `printer_profile`.
- Canonical quality profile hints use decimal notation, for example `0.2mm_quality`; parsers may accept legacy `0p2mm_quality` but must not display it as `2.0 mm`.
- Runtime cards should show final `cell_size_mm`, `relative_density`, and `expected_mass_g` from the selected candidate, not from an intermediate LLM suggestion.

Equipment-specific integration rule:

- Equipment Agent uses LLM-selected tool calls over `equipment.pyautogui.health`, `equipment.pyautogui.list_programs`, and `equipment.pyautogui.run`.
- Equipment Agent stops before execution when `equipment.pyautogui.health` or `equipment.pyautogui.list_programs` fails.
- Internal-network Windows bridge discovery and selection are handled by `/equipment/windows`.
- Saved bridge selection is stored in `memory/windows_pyautogui_connection.json`.
- Discovery lists only token-verified Windows bridge hosts.
- Saved Windows bridge candidates use aliases, for example `windows_pyautogui_pc_1`, so LLM/tool-call planning can refer to a stable device identity and quick-connect later.
- `program1` is the setup demo macro: after PyAutoGUI is installed on Windows it briefly moves the mouse and returns `program_log: "program1 completed"`.

LeRobot-specific integration rule:

- LeRobot/ROBOTIS belongs to the Manipulation Agent path, not Equipment Agent.
- `configs/lerobot.yaml` defines selectable robot profiles, fake test profiles, command templates, and live gates.
- The main GUI opens the dedicated LeRobot workspace at `/lerobot`; the launcher itself must not start teleoperation, recording, training, rollout, or hardware movement.
- The dedicated GUI uses `/api/lerobot/*` endpoints and keeps sessions in the current server process only.
- Test mode uses deterministic fake sessions and fake ports so LeRobot can be tested without installed robot hardware.
- Live mode is blocked by profile gates unless `live_enabled` and the specific `allow_*` workflow gate are explicitly enabled.
- Live mode also requires `confirm_live_execute=true` from the GUI before a LeRobot subprocess starts.
- The local runtime command path is `/home/jin/miniconda3/bin/conda run -n lerobot ...`.
- Default local dataset root is `~/.cache/huggingface/lerobot`; default policy/training root is `outputs/train`.
- `lerobot.find_ports` is non-interactive in the GUI and scans local serial candidates instead of calling the interactive `lerobot-find-port` script.
- `lerobot.rollout.start` uses the installed LeRobot policy-control path. Because this workstation does not expose `lerobot-rollout`, the bridge uses `lerobot-record` with `--policy.path=<checkpoint_dir>` for real-robot policy execution.
- Local rollout policy paths are preferred over Hub repo IDs. If the GUI selects `model.safetensors` or another recognized policy output file under `outputs/train`, the bridge resolves it to the parent `pretrained_model` checkpoint folder before building the live command.
- Rollout output dataset names are normalized to `eval_*` by the bridge, while teleoperation/training datasets keep their original names. Blank GUI rollout duration means manual-stop mode and is converted to a long one-episode LeRobot run.
- Manipulation Agent switches to `lerobot.rollout.start` when `current_experiment_spec.manipulation_strategy` contains `lerobot`/`policy`, or when LeRobot policy/profile fields are present.
- Manipulation Agent supports bounded tasks `transfer_to_utm` and `clear_utm_to_disposal`, stores defaults in `memory/manipulation_agent_bridge.json`, and uses Pi0.5 RTC/action-clamp fields from the LeRobot GUI/profile when present.

## State Fields Commonly Read/Written

Frequently read by agents:

- `active_goal`
- `mode`
- `stage`
- `loop_count`
- `retry_counters`
- `latest_observations`
- `latest_analysis`
- `current_experiment_spec`
- `safe_stop_requested`, `stop_requested`

Frequently written by run loop merge:

- `current_experiment_spec` from `experiment_spec`
- `latest_observations` from `observation`
- `latest_analysis` from `analysis`, `sarm`, `manipulation`
- `run_metadata["guardian"]` from `guardian`

## Retry, Pause, Stop, and Safe-Stop Baseline

- Retry policy: per-stage bounded retries (`retry_counters[stage] < max_retry_per_stage`)
- Default max retry budget comes from system config and run loop initialization.
- `pause`: sets `is_paused=True`, loop emits `paused` repeatedly until resumed.
- `stop`: sets `stop_requested=True`; controller may force-cancel active task.
- `safe-stop`: sets `safe_stop_requested=True`; loop transitions to `complete` via safe-stop branch.

## GPU Clear Baseline

- API: `POST /api/runtime/gpu-clear`
- CLI: `atr gpu clear`
- Behavior:
  1. stops active run if needed
  2. calls Ollama `/api/ps`
  3. unloads each resident model via `/api/generate` with `keep_alive=0`
- Designed to free resident GPU model memory without killing the whole process tree.

## CLI Control Baseline

- Installer: `bash install/install_cli.sh`
- Usage document: `install/README.md`
- Help contract: `atr` with no arguments prints all available commands and explanations.
- Server start: `atr up`.
- Server stop: `atr down`.
- GUI URL helpers: `atr gui`, `atr live`, `atr docs`.
- Runtime APIs:
  - `atr status` -> `GET /api/state`
  - `atr events` -> `GET /api/events/recent`
  - `atr backend <backend>` -> `POST /api/runtime/backend`
  - `atr run start|pause|resume|stop|safe-stop` -> corresponding `/api/run/*` endpoint
  - `atr models` -> `GET /api/runtime/models`
  - `atr model load|unload <model>` -> corresponding `/api/runtime/models/*` endpoint
  - `atr chat ...` -> Live GUI planning message/bootstrap endpoints
- Environment:
  - `ATR_URL` overrides the API base URL.
  - `ATR_BACKEND` controls backend selection used by `run` and `chat` commands.

## Live GUI Design Handoff Gate

- The `실험 수행` trigger is not allowed to call Design Agent with fabricated defaults.
- Before handoff, the controller must confirm these required values from the current Live GUI session:
  - experiment objective or evaluation metric
  - material
  - specimen size in mm
  - geometry or experiment domain
- Validated printer defaults are applied unless overridden:
  - `printer_model=Bambu Lab X2D`
  - `printer_profile=bambulab_x2d_lab_01`
  - `slicer_profile_hint=0.2mm_quality`
  - `nozzle_diameter_mm=0.4`
  - `layer_height_mm=0.2`
  - `storage=internal`
- In normal Live GUI mode, `실험 수행` builds `experiment_spec.print` with `start_immediately=true` and `confirm_physical_print=true`, so Specimen Making Agent proceeds through the active printer bridge. The default bridge is Bambu Lab X2D; PrusaLink upload/start is used only when Prusa MK4S is explicitly selected.
- In Live GUI `테스트 모드` and Main GUI `test`, the generated TPMS gyroid cell size comes from the 3DP GUI saved `test_unit_cell_size_mm`, defaulting to `cell_size_mm=10.0`.
- In Live GUI `테스트 모드` and Main GUI `test`, `print.start_immediately` remains false until Specimen Making Agent asks for a printer path; choosing `실제 출력` promotes only the printer step to real PrusaSlicer -> PrusaLink upload/start.
- Live GUI one-shot commands `테스트 모드, 가상 브릿지`, `테스트 모드, 설치 프린터`, and `테스트 모드, 실제 출력` inject the selected `printer_test_path` before DesignAgent handoff, so Specimen Making Agent proceeds without the separate printer-path prompt.
- If any required value is missing, the Live GUI must append an Orchestrator message that includes:
  - current confirmed values
  - missing values
  - field-level examples
  - one complete example sentence ending with `실험 수행`
- Test mode is the exception: `테스트 모드` still lets the LLM generate explicit test values and displays those generated values before handoff.

## Test Mode Baseline

- Test mode should remain full-loop executable without real hardware.
- Real LLM path can be enabled in test mode; timeouts degrade gracefully in stage agents.
- Keep deterministic fallback outputs for required schema keys.

## Integration Checklist Before Merge

- Agent output keys still satisfy validation policy.
- Stage transitions still reach `guardian` and feedback loop (`guardian -> design`).
- Real tool adapters preserve tool names and minimal payload/result contract.
- Timeout and exception handling avoid retry storms in test mode.
- `pause`, `stop`, `safe-stop`, `gpu-clear` still function from GUI and API.
- GUI status panels still receive expected state fields.
- `pytest -q` passes.

## Useful Reference Files

- `docs/project/Project_guide.txt`
- `docs/process/codex_workflow.md`
- `orchestrator/run_loop.py`
- `orchestrator/state.py`
- `graphs/configs/*.yaml` is the runtime transition source of truth. `orchestrator/transitions.py` is compatibility-only and delegates to graph config.
- `orchestrator/router.py` is compatibility-only and resolves stage handlers from graph/module config, not from an internal stage map.
- `agents/*.py`
- `configs/models.yaml`
- `mcp_tools/tool_registry.py`
- `app/main.py`


## Runtime Event Contract

LangGraphRunLoop emits legacy `event_type` keys plus Runtime IDE `type` aliases such as `node.started`, `node.completed`, `edge.traversed`, and `run.completed`. Runtime IDE consumers should depend on the alias fields while existing GUI code may continue reading the legacy keys.

### 2026-05-29 Vision Agent baseline update

The Vision stage output is now:

- `observation` for backward compatibility.
- `vision_report.v1` for report/GUI use.
- `vision_signal.v1` as `handoff_packet` for downstream agents.
- `decisions`, `metrics`, and `evidence_refs` for runtime trace and reports.

`camera.capture` may now include optional `camera_key`, `purpose`, `specimen_id`,
`timestamp`, `confidence`, `zones`, `detections`, and artifact path fields. The
agent tolerates missing optional fields and degrades to simulator/rule evidence.

## 2026-05-30 Lab Equipment Failure Evidence Contract

For UTM visual-control runs, Lab Equipment reports must preserve both data and non-data evidence:

- `equipment_report.artifact_records`: normalized Windows/Linux artifact metadata from bridge output.
- `equipment_report.artifact_refs`: all known artifact references.
- `equipment_report.screen_evidence_refs`: screen PNG evidence for ready/running/complete/failure states.
- `equipment_report.data_evidence_refs`: parseable UTM CSV references only.
- `utm_data_ready.evidence_refs`: broad evidence package for Guardian/Knowledge review.
- `equipment_handoff.result_file` / `utm_csv_path`: Analysis input; do not replace these with screen artifacts.
- `equipment_report.failure_retry_table`: warning/blocked/retry/fallback steps for operator recovery.

This separates recovery evidence from Analysis data while keeping blocked runs debuggable.

### 2026-05-30 Analysis Live Equipment Handoff Gate

In live mode, Analysis does not treat a readable UTM CSV as sufficient by itself when the run carries Windows/UTM Equipment handoff metadata. If `equipment_report.live_evidence_audit.required_for_handoff=true`, `equipment_handoff`, or `utm_data_ready` is present, `AnalysisAgent` rechecks that the handoff is `ready_for_analysis`, the UTM packet is `ready`, and the required screen/physical/save/file/parse/Linux-pull/Vision/request-audit cross-checks are true. Otherwise the analysis result is blocked with `EQUIPMENT_HANDOFF_NOT_READY` or the specific Equipment failure code.

### Lab Equipment Vision Freshness Requirement

For live UTM handoff, Lab Equipment treats Vision physical evidence as freshness-bounded data. A positive `equipment_vision_check_result` or Vision signal-board entry is not consumable unless it carries a valid ISO-8601 `expires_at` value and that value is still in the future. Missing live freshness metadata blocks with `VISION_UTM_*_FRESHNESS_REQUIRED`; expired metadata blocks with `VISION_UTM_*_STALE`; absent evidence remains `VISION_UTM_*_REQUIRED`.

This distinction is intentional:

- `REQUIRED`: the physical UTM check was never observed.
- `FRESHNESS_REQUIRED`: the check was observed but not bounded by a validity window.
- `STALE`: the check had a validity window but it has expired.

Test mode may still use deterministic simulated checks. Live mode must refresh Vision before retrying Equipment handoff when any of these blockers appear.

## Lab Equipment Vision Identity Requirement

For live Lab Equipment / UTM handoff, Vision evidence consumed by `LabEquipmentAgent` must include current-run identity. `equipment_vision_check_result` and Equipment-targeted `vision_signal_item.v1` entries must carry `run_id`, `specimen_id`, and `expires_at`. Freshness alone is not sufficient: stale, identity-missing, or identity-mismatched Vision evidence blocks `ready_for_analysis` and routes to Guardian/operator review.

## Analysis Blocked-Handoff Evidence Payload

Live Lab Equipment failures are still analysis events, even when they are not accepted as valid mechanical results. `AnalysisAgent` now emits the same downstream evidence envelope for blocked paths as it does for successful analysis:

- `analysis.artifact_refs` and top-level `knowledge_payload.raw_artifact_refs` preserve UTM CSV paths, screen evidence, bridge artifact IDs, and nested `equipment_report` / `utm_data_ready` evidence refs.
- `analysis.failure_tags` and `knowledge_payload.failure_tags` include the Analysis failure code, Equipment handoff failure code, signal-quality failure code, and live handoff blockers.
- `analysis.knowledge_payload` is populated for `EQUIPMENT_HANDOFF_NOT_READY`, `UTM_DATA_REQUIRED`, and `UTM_DATA_*` signal-quality blocks so Knowledge/Guardian/Self-Evolution can learn from failed runs instead of losing provenance.
- Blocked payloads do not mark the experiment as Analysis-ready. `bo_observation.status` is `blocked`, and `equipment_handoff_gate.status` remains `blocked` when Equipment proof gates are incomplete.

This implements the Improvement 05 rule that data success, save/export success, and analysis success are separate gates. A failed handoff must remain traceable through raw artifacts and failure tags, not disappear because Analysis refused to compute objective metrics.

## Guardian Review of Blocked Analysis

`GuardianAgent` now treats blocked UTM analysis as a consistency signal. If `latest_analysis.ok=false`, `latest_analysis.failure_code` is set, or `latest_analysis.equipment_handoff_gate.status=blocked`, Guardian records a consistency issue and routes toward recovery unless a higher-priority stop condition is active. UTM/data/evidence failure tags such as `UTM_DATA_*`, `UTM_SAVE_EXPORT_*`, and `EQUIPMENT_LIVE_EVIDENCE_INCOMPLETE:*` are surfaced as Guardian warnings.

This keeps Improvement 05 failure modes visible to the loop policy: rejected UTM CSVs, missing Linux artifact pulls, save/export responsibility failures, and request-audit evidence failures are not silently treated as ordinary low objective scores.
