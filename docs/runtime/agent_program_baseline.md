# Agent Program Integration Baseline

This document is the baseline contract for integrating real programs into the existing multi-agent runtime.
Use it when replacing mock logic with production device/program logic in each agent.

## Scope

- Runtime: `FastAPI + LangGraphRunLoop + config-driven LangGraph stage transitions`
- Control plane: GUI and API endpoints in `app/main.py`
- Agent contract: `BaseAgent.run(state, ctx) -> AgentResult`
- Model hierarchy: `orchestrator (31B primary, E4B fallback) + e2b`
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
| `guardian` | `guardian_agent` |

## Agent Integration Baseline

When replacing internals with real programs, keep these output keys stable.

| Stage | Runtime-required keys | Current output keys | Real program integration target |
|---|---|---|---|
| `design` | `experiment_spec` | `experiment_spec`, `rationale` | protocol/candidate generation service |
| `specimen` | none | `specimen_result`, `protocol_note` | geometry handoff + PrusaSlicer/PrusaLink runtime pipeline |
| `vision` | `observation` | `observation`, `protocol_note` | 3DP output pickup observation via `camera.capture` |
| `manipulation` | none | `manipulation`, `sarm`, `protocol_note` | robot control runtime: `robot.pick_place` or Pi0.5/LeRobot rollout |
| `equipment` | `equipment_result`, `protocol_note` | `equipment_result`, `protocol_note`, `equipment_handoff` | Windows PyAutoGUI bridge macro runner or legacy UTM runner |
| `analysis` | `analysis` | `analysis` | UTM curve feature extraction + CAE closed-loop objective/uncertainty post-processor |
| `knowledge` | none | `knowledge` | local+web RAG and memory writer |
| `guardian` | `guardian` | `guardian` | safety/policy engine |

Notes:

- SARM remains a submodule under `manipulation_agent` (not top-level stage).
- Design-stage orchestrator planning is declared as `module.pre_execution` in `graphs/modules/design/module.yaml` (`orchestrator_plan -> agent.orchestrator_agent`) and writes plan metadata to `state.run_metadata.orchestrator_plan`; it must not be reintroduced as a hard-coded run-loop special case.
- Live GUI planning may skip that pre-execution step only after the chat orchestrator has already approved the same Design handoff, to avoid duplicate model calls.

## Model Hierarchy Baseline

Configured defaults (`configs/models.yaml`):

- `orchestrator`: `gemma4:31b` (fallback `gemma4:e4b-it-nvfp4`)
- `e4b`: `gemma4:e4b-it-nvfp4` (fallback `gemma4:31b`)
- `e2b`: `gemma4:e2b-it-nvfp4` (fallback `gemma4:e4b-it-nvfp4`)

NemoClaw/vLLM deployment repos:

- `gemma4:31b`: `nvidia/Gemma-4-31B-IT-NVFP4`
- `gemma4:e4b-it-nvfp4`: `bg-digitalservices/Gemma-4-E4B-it-NVFP4`
- `gemma4:e2b-it-nvfp4`: `bg-digitalservices/Gemma-4-E2B-it-NVFP4`

All three vLLM deployments use `modelopt_fp4` quantization. The vLLM branch uses `*-nvfp4` aliases for E4B/E2B so runtime status reflects the actual served checkpoint. The `ollama` and `nemoclaw` proxy branches keep their installed local Ollama tags.

Gemma4 MTP speculative decoding is enabled only in the NemoClaw/vLLM deployments. Use a vLLM image that includes Gemma4 MTP support (`vllm/vllm-openai:v0.21.0-cu129-ubuntu2404` or newer). Older local `vllm/vllm-openai:latest` / `latest-cu130` images around vLLM `0.20.0` do not include the Gemma4 MTP path. The earlier `gemma4-0505-cu130` tag has the MTP path but failed local verification with assistant weight shape mismatch, so it is not used.

GB10/NVFP4 backend requirement:

- Set `VLLM_NVFP4_GEMM_BACKEND=marlin` on every Gemma4 NVFP4 deployment.
- Do not use the automatic FlashInfer FP4 path on this host; it fails with `CUDA error: no kernel image is available for execution on the device`.
- Do not force `cutlass` on this host; it reaches the vLLM CUTLASS path but fails during profile run with `cutlass_scaled_fp4_mm` internal errors.
- Verified working path: `MarlinNvFp4LinearKernel` + Gemma4 MTP assistant, tested on `gemma4:e2b-it-nvfp4`, `gemma4:e4b-it-nvfp4`, and `gemma4:31b` via `/v1/chat/completions`.

MTP assistant mapping:

- `gemma4:31b`: `google/gemma-4-31B-it-assistant`, `num_speculative_tokens=4`
- `gemma4:e4b-it-nvfp4`: `google/gemma-4-E4B-it-assistant`, `num_speculative_tokens=4`
- `gemma4:e2b-it-nvfp4`: `google/gemma-4-E2B-it-assistant`, `num_speculative_tokens=2`

NemoClaw/vLLM GPU residency profile:

- `gemma4:31b`: `--gpu-memory-utilization 0.37`
- `gemma4:e4b-it-nvfp4`: `--gpu-memory-utilization 0.20`
- `gemma4:e2b-it-nvfp4`: `--gpu-memory-utilization 0.12`
- This profile is intentionally asymmetric so all three managed deployments can remain resident on the 120 GB class GPU.
- Do not raise E4B/E2B to `0.30` while 31B remains resident; two small deployments would reserve roughly 70 GB before 31B starts, causing 31B startup to fail with insufficient free memory.

Live GUI startup policy:

- No automatic NemoClaw/vLLM model loading is performed by server startup, Live GUI open, backend switching, run start, or planning bootstrap.
- Operators manually load the required model through the main dashboard per-model Loading buttons or `atr model load <e4b|e2b|31b>`.
- Model-backed requests assume the target vLLM deployment is already loaded. If it is not loaded, the request should fail visibly instead of issuing hidden Kubernetes scale-up commands.
- The main dashboard exposes per-model Loading/Unloading controls and deployment status dots for the managed NemoClaw/vLLM models.

Task routing baseline:

- `orchestrator_plan -> orchestrator`
- `design_reasoning -> e4b`
- `analysis_reasoning -> e4b`
- `knowledge_query -> e4b`
- `guardian_reasoning -> e4b`
- `tool_formatting -> e2b`

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
| `utm.run_protocol` | `profile` | `ok`, `tool`, `result_file`, `cycles` |
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
- Specimen Making Agent owns PrusaSlicer settings, G-code output path, PrusaLink endpoint/gate status, and runtime step trace.
- Do not render the STL viewer again from Specimen Making Agent messages.
- Keep final design values consistent across `experiment_spec`, `printer.prepare.slicer_settings`, text chat, and Live GUI runtime cards.
- For Prusa MK4S live use, `printer.prepare` must expose storage readiness and map unavailable USB storage to `PRINTER_STORAGE_UNAVAILABLE` before upload/start.
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
  - `printer_model=Prusa MK4S`
  - `printer_profile=prusa_mk4s_pla_0p4_nozzle`
  - `slicer_profile_hint=0.2mm_quality`
  - `nozzle_diameter_mm=0.4`
  - `layer_height_mm=0.2`
  - `storage=usb`
- In normal Live GUI mode, `실험 수행` builds `experiment_spec.print` with `start_immediately=true` and `confirm_physical_print=true`, so Specimen Making Agent proceeds to PrusaLink upload/start.
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
