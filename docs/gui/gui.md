# GUI
> [Runtime Closed-Loop/페이지/에이전트 실행 레퍼런스](../runtime/closed_loop_and_pages_reference.md)


Web dashboard panels:
- global run metrics
- run control buttons
- current NemoClaw/vLLM model cells with per-model Loading/Unloading controls and status dots
- Device Workspaces panel with dedicated launchers for Prusa MK4S 3DP Printer GUI, Windows PyAutoGUI Bridge GUI, LeRobot / ROBOTIS GUI, BO Workspace, and CAE Analysis Workspace
- live loop timeline
- agent status
- device health
- structured log viewer

Real-time updates are streamed via SSE endpoint `/api/events/stream`.

Terminal launcher:
- Install with `bash install/install_cli.sh`.
- `atr` with no arguments must print available commands and short descriptions.
- `atr up` starts the GUI server from any terminal.
- `atr down` stops this checkout's GUI server process from any terminal.
- CLI mirrors the main GUI control plane for status, run control, backend switching, model load/unload, GPU clear, recent events, and Live GUI chat/bootstrap calls.
- Detailed command usage lives in `install/README.md`.

Live GUI chat route:
- The Live GUI conversation is the operator-facing surface for orchestrator discussion and handoff execution.
- Opening Live GUI does not automatically load NemoClaw/vLLM models. Operators must use the main dashboard Loading buttons or `atr model load <model>` before sending model-backed chat/workflow requests.
- Server startup, Live GUI open, backend switching, and planning bootstrap are side-effect free with respect to Kubernetes vLLM scale-up.
- Live GUI orchestrator calls retry once internally before surfacing a chat failure, because MTP/NVFP4 vLLM servers may JIT kernels on the first real generation after readiness.
- `실험 수행` must not fabricate missing design values. If required values are missing, the chat must show current confirmed values, missing values, and one concrete example input.
- Required values before Design Agent handoff are experiment objective/metric, material, specimen size, and geometry/domain.
- Material and print defaults may come from the operator-controlled 3DP Printer GUI profile when not stated in chat. This counts as a confirmed GUI default, not an LLM-fabricated value.
- Validated print defaults are shown/used when the operator does not override them: PLA, Prusa MK4S, USB storage, 0.4 mm nozzle, 0.2 mm layer height, 60 C bed / 60 C first-layer bed, `prusa_mk4s_pla_0p4_nozzle`, and `0.2mm_quality`.
- 3DP Printer GUI route:
  - Main dashboard button: `Open 3DP GUI`
  - Route: `/printer`
  - API surface: `/api/printer/profile`, `/api/printer/status`, and `/api/printer/connection`.
  - Profile memory: `memory/prusa_print_profile.json`.
  - Connection memory remains separate: `memory/prusa_connection.json`.
  - The profile stores print defaults only: material, printer model/profile, slicer profile hint, nozzle diameter, layer height, first-layer controls, PLA bed-temperature controls, test specimen size, storage, max print time, overwrite, and live start-after-upload preference.
  - The 3DP GUI `PrusaLink Connection` panel can set bridge host/IP, scheme, port, storage, auth mode, username, password, API key header, and API key. Blank password/API key fields preserve the existing saved secret.
  - The profile never stores PrusaLink secrets. Connection secrets live only in `memory/prusa_connection.json`; GUI/API responses never return the password or API key value and only report `password_set` / `api_key_set`.
  - Live write gates (`allow_upload`, `allow_start_print`) are read from `configs/devices.yaml`; the GUI displays them so the operator sees what the runtime will actually permit.
  - Auto ejection is controlled by the 3DP GUI print-default checkbox and is saved in `memory/prusa_print_profile.json` as `allow_ejection`.
  - Skirt/brim/raft generation is controlled by the 3DP GUI profile field `skirt_enabled`; default is off, so PrusaSlicer receives `--skirts=0 --brim-width=0 --raft-layers=0`.
  - TPMS cap skins are controlled independently by `bottom_cap_enabled`, `top_cap_enabled`, and `skin_thickness_mm`; default is bottom-only with `skin_thickness_mm=0.8`. `top_bottom_cap` remains a compatibility field equal to either cap being enabled. `require_flat_compression_faces` is true only when both caps are enabled.
  - When `allow_ejection=true`, the same ejection request is applied to Main GUI test mode, normal Live GUI mode, and Live GUI `테스트 모드`.
  - Current ejection implementation is a bed-sweep append-G-code routine: PrusaSlicer output is copied to `*.autoeject.gcode`, the validated ejection tail is appended, and that combined G-code is uploaded/started. The ejection tail derives printed-object bounds from extrusion moves in the sliced G-code and resolves the nozzle X coordinate from the object center instead of always using bed center. The tail closes with `M400`, `M73 P100 R0`, and `M73 Q100 S0`; `M73 P99/Q99` is only the transition into the ejection segment.
- In normal Live GUI mode, `실험 수행` enters the configured LangGraph route at Design Agent, reaches Specimen Making Agent for PrusaSlicer/PrusaLink upload-start when live printing is enabled, and then continues through the active graph tail. The printer runtime card must show storage readiness plus upload/start status.
- Physical upload/start uses the validated MK4S sequence: upload the requested/display filename, wait for PrusaLink transfer idle, read `GET /api/v1/files/{storage}/{requested_name}` metadata, then start the returned storage filename such as `AUTOEJ~1.GCO`. The runtime card should surface `transfer_wait`, `start.path_resolution`, `start.retry_history`, upload result, and start result when present.
- Physical start does not trust the start HTTP response alone. After each start request, the bridge polls PrusaLink `status/job`; if `PRINTING` is not confirmed, it retries the start request every 1 second up to the configured attempt budget. This handles cases where PrusaLink accepts or drops the start signal while the printer is still settling.
- Before every physical start path, including normal live print, test-mode actual print, standalone autoejection test, and separate ejection job mode, the bridge checks PrusaLink `status/job`. It must not start another job while a previous job remains active at 99% or 100%; appended autoejection tails can still be executing homing or bed-sweep moves. The bridge waits until `/api/v1/job` is cleared and the printer reports idle/FINISHED before the next upload/start. The local MK4S PrusaLink 2.1.2 endpoint set does not expose a working `POST /api/printer/ready`, so the runtime must not depend on SetReady.
- The 3DP GUI print profile includes `first_layer_height_mm`, `slow_first_layer_enabled`, `first_layer_speed_mm_s`, `bed_temperature_c`, and `first_layer_bed_temperature_c`; defaults are 0.2 mm first-layer height, slow first layer enabled at 10 mm/s, and 60 C bed targets for PLA adhesion. PrusaSlicer must receive `--layer-height`, `--first-layer-height`, `--bed-temperature`, `--first-layer-bed-temperature`, and, when enabled, `--first-layer-speed`.
- The 3DP GUI has a `Test Options` section. `Test Specimen Size mm` is saved as `test_specimen_size_mm` and `Test Unit Cell Size mm` is saved as `test_unit_cell_size_mm` in `memory/prusa_print_profile.json`; Live GUI `테스트 모드` / `테스트 모드, 실제 출력` handoffs read those saved values as `specimen_size_mm`, `max_specimen_size_mm`, and `cell_size_mm`.
- In Live GUI `테스트 모드`, the generated test spec uses FDM-printable gyroid TPMS with the 3DP GUI saved test unit-cell size, defaulting to `cell_size_mm=10.0`, starts with physical printing off, and routes to Specimen Making Agent's printer-path selection: virtual bridge, installed-printer read-only communication, or explicit actual print.
- One-shot Live GUI commands `테스트 모드, 가상 브릿지`, `테스트 모드, 설치 프린터`, and `테스트 모드, 실제 출력` set the printer path during orchestration and continue without the separate path prompt.
- `테스트 모드, 실제 출력` must not keep the browser fetch open through the long PrusaLink upload/start step; it schedules the physical-print workflow in the background and updates the chat via planning events/session refresh.
- Physical TPMS gyroid output uses the operator/profile-controlled cap setting. The default profile generates a 0.8 mm bottom cap for bed adhesion and leaves the top cap off to avoid unsupported FDM sag; the operator may enable the top cap only when a flat upper compression face is required.
- Main GUI `test` runs must remain dry-run/virtual at the printer boundary. Main GUI `live` opens the Live GUI so the operator can provide values and trigger actual printing from the chat.
- The 3DP GUI provides standalone autoejection test buttons for left/center/right assumed object positions. These buttons do not print a specimen. They generate the same bed-sweep ejection program used by the normal autoeject path, inject synthetic object bounds for the selected position, then upload/start that ejection-only G-code through PrusaLink live upload/start gates.
- Design Agent messages render preview images and experiment-spec links only; direct STL links and browser STL viewer canvases are disabled for Design Agent cards to avoid heavy WebGL/DOM state in Live GUI refreshes.
- Specimen Making Agent messages must focus on manufacturing runtime state, not STL preview duplication.
- Specimen Making Agent runtime cards show:
  - PrusaSlicer profile/material/layer/nozzle settings
  - input model path and output G-code path
  - resolved slicer command template
  - PrusaLink transport and upload/start endpoint shape
  - PrusaLink storage availability/read-only state
  - upload/start HTTP result when physical live mode is used
  - print/ejection gate result
  - `printer.prepare` step trace
- `printer.prepare` may stream per-step events into the same chat while the tool is running.

Windows PyAutoGUI Bridge GUI route:
- Main dashboard button: `Open Windows Bridge GUI`
- Route: `/equipment/windows`
- The Live GUI no longer contains a Windows Bridge button; hardware workspace entry points live under Main GUI Device Workspaces.
- Saved bridge candidates are still persisted in `memory/windows_pyautogui_connection.json` and are shared by all GUI windows.

CAE Analysis GUI route:
- Main dashboard button: `Open CAE Workspace`
- Route: `/cae`
- API surface: `/api/cae/config` and `/api/cae/run`.
- The workspace has a `Save Settings` control. Saved settings are persisted in `memory/cae_workspace_settings.json` and are reapplied when a new CAE GUI window is opened.
- The default analysis setup is bottom fixed support and top cyclic compression loading.
- Test mode runs deterministic equivalent CAE and returns `cae_metrics` for closed-loop Analysis Agent scoring.
- Live mode performs solver preflight. If `require_solver_in_live=true` and CalculiX/ccx is unavailable, the run is blocked with `CAE_SOLVER_REQUIRED`.
- The GUI exposes solver, mesher, STL path, specimen size, mesh size, material properties, load max, load min ratio, cycle count, frequency, and live solver requirement controls.
- Result cards show max von Mises stress, max displacement, fatigue proxy, structural score, step trace, and raw JSON.

BO Workspace GUI route:
- Main dashboard button: `Open BO Workspace`
- Route: `/bo`
- API surface: `/api/bo/config`, `/api/bo/benchmark`, and `/api/bo/run`.
- The workspace has a `Save Settings` control. Saved settings are persisted in `memory/bo_workspace_settings.json` and are reapplied when a new BO GUI window is opened.
- Saved BO settings include mode, objective, strategy, numeric backend (`lightweight_pool` or `botorch_optional`), acquisition function, budget, seed, exploration/exploitation controls, LLM preference enable/weight, top-k, and parameter-space bounds.
- Benchmark and BO Agent actions remain virtual optimization controls only; the BO GUI does not directly start printer or robot hardware. `/api/bo/run` shows evidence intake, LLM reasoning audit, candidate ranking, and `next_design_request.v1` handoff.
- Live GUI BO Agent messages render surrogate/acquisition graphs in a collapsed state by default. The collapsed card shows only strategy/acquisition/budget/latest candidate/recommendation metadata; SVG trace graphs and selected-point rows are created only when the operator clicks `그래프 보기`, and removed again by `그래프 접기`.

LeRobot GUI route:
- Main dashboard button: `Open LeRobot GUI`
- Route: `/lerobot`
- API surface: `/api/lerobot/config`, `/api/lerobot/ports`, `/api/lerobot/ports/*`, `/api/lerobot/camera/test`, `/api/lerobot/teleoperate/*`, `/api/lerobot/record/*`, `/api/lerobot/train/*`, `/api/lerobot/rollout/*`, `/api/lerobot/manipulation-agent/*`, `/api/lerobot/dataset/inspect`, `/api/lerobot/sessions`.
- The route is a control/configuration workspace for ROBOTIS/LeRobot manipulation workflows.
- Opening the route does not start robot motion. Actions require explicit button calls.
- Test mode shows deterministic fake sessions, fake ports, command previews, and step traces.
- Device setup follows the LeRobot unplug/reconnect port-identification pattern: save a baseline, disconnect or reconnect one target MotorBus, detect the changed port, and save it separately for follower and leader.
- Camera setup is key-based multi-camera setup. Default camera keys are `top` and `wrist`; the GUI exposes `+ Camera` for additional camera keys and a `-` control for removing non-default camera keys. Each camera key has its own baseline, detect/save, capture-test controls, and action status box.
- Live camera capture tests use the LeRobot conda environment's OpenCV backend when the main app virtualenv does not provide `cv2`.
- Saved follower/leader/camera ports are profile-scoped and persisted in `memory/lerobot_device_ports.json`; cameras are stored under `devices.cameras.<camera_key>`. New GUI windows reconstruct this state through `/api/lerobot/config`.
- Device saves prefer persistent Linux identity links. If the operator saves `/dev/ttyACM*`, `/dev/ttyUSB*`, `/dev/video*`, or a camera index in live mode, the bridge stores a matching `/dev/serial/by-id/*`, `/dev/v4l/by-id/*`, or `/dev/v4l/by-path/*` path when available, with `raw_port`, `device_id`, and `device_link` preserved.
- Live LeRobot execution resolves those saved identity links back to the current kernel node just before use, so teleoperation, recording, rollout, and camera capture tests survive `/dev/ttyACM*` or `/dev/video*` renumbering.
- Every action button group has a local status message box showing `RUNNING`, `OK`, or `ERROR` with the latest structured tool status. Live LeRobot subprocess failures also render the filtered `log_tail` directly inside the same action box, so Teleop startup errors appear under the Teleop controls.
- Live LeRobot session IDs include a timestamp, and subprocess logs are written to that unique session file instead of reusing `lr-teleoperate-000N.log` across server restarts. This prevents old failed logs from appearing in a later Stop/Status result.
- For the current ROBOTIS OMX setup, leader means Dynamixel motor IDs `1-6` and follower means IDs `11-16`; saved profile ports must preserve that role mapping.
- Live mode uses the selected profile gates from `configs/lerobot.yaml` and fails closed by default.
- Current ROBOTIS OMX live teleoperation follows the verified terminal command shape: `python -m lerobot.teleoperate`, `robot.id=omx_follower_arm`, `teleop.id=omx_leader_arm`, no extra project calibration directory, follower resolved to `/dev/ttyACM0`, leader resolved to `/dev/ttyACM1`.
- Current ROBOTIS OMX live profile allows teleoperation, recording, training, and policy rollout when mode is `live`, the operator checks live confirmation, and the selected profile gate allows the workflow.
- Recording commands must include LeRobot's required `--dataset.single_task=<task>` argument. The GUI sends the Recording `Task Instruction` field as this value; the current default is `Pick up the cylinder`, with default repo `jin/record-test`.
- Recording uses the same saved follower, leader, and camera resolver as teleoperation. In live mode the current ROBOTIS OMX command resolves to follower `/dev/ttyACM0`, leader `/dev/ttyACM1`, top camera OpenCV index `2`, and wrist camera OpenCV index `0` when those device identities are connected.
- Camera capture is independent of the display checkbox. The display checkbox controls LeRobot visualization; saved cameras are still passed to recording so datasets contain camera observations.
- If the target local dataset already exists and the operator did not check `Resume dataset`, live recording does not silently resume it. The bridge records into a fresh suffixed dataset path, shows `existing dataset detected; recording to fresh dataset ...` in the action trace, and returns the effective dataset repo/path so the GUI can update the Dataset Repo ID field. This avoids timestamp-sync failures from partial/corrupt prior runs while preserving the old dataset.
- Live recording controls send the actual LeRobot keyboard events instead of only changing GUI state: `Save / Next` sends Right Arrow, `Retry Current` sends Left Arrow, and `Finish Gracefully` sends Esc. `Force Stop` performs emergency cleanup of tracked and stale LeRobot live process groups tied to this checkout.
- Recording controls must target the active `record` session first. If older stopped record sessions exist in the session list, the GUI and backend must not send `Save / Next`, `Retry Current`, or `Finish Gracefully` to the stopped session ID.
- Recording controls must not send extra Right/Left Arrow events while LeRobot is saving parquet/video after reset. During that phase the operator should wait for the next `Recording episode` or `Reset the environment` log line; otherwise LeRobot can start the next episode with zero frames.
- The local workstation LeRobot runtime is expected at conda env `lerobot`; current verified install path is `/home/jin/miniconda3/envs/lerobot`.
- Live subprocess execution uses `/home/jin/miniconda3/bin/conda run --no-capture-output -n lerobot ...` plus unbuffered Python output so Teleop/Recording logs stream into the GUI status box while the process is active.
- Dataset workflow is local-first. Default dataset root is `~/.cache/huggingface/lerobot`; Browse buttons first open a native OS folder picker through `/api/lerobot/files/pick` so the operator can select real local folders on this workstation. The Dataset Repo ID browse button stores a path relative to Dataset Root when possible, for example selecting `/home/jin/.cache/huggingface/lerobot/jin/record-test` writes `jin/record-test`. The older in-page path browser remains only as fallback if the native picker is unavailable, and its Refresh button reloads newly created folders without closing the browser.
- Training output and local policy checkpoints default to `outputs/train`. If live training has to avoid an existing `output_dir`, the bridge returns the fresh output directory and the GUI updates the Policy / Output Root field. Rollout policy browsing starts from that output root, shows folders plus LeRobot policy output files such as `model.safetensors`, and normalizes a selected model file to its parent `pretrained_model` checkpoint folder before execution.
- Rollout has an explicit task-instruction field. If filled, it overrides the shared task field and is sent to LeRobot as `--dataset.single_task=<instruction>`.
- Rollout has a dedicated optional duration field. Blank duration means run until `Stop Rollout`; the bridge converts this to `continuous_rollout=true`, `episode_s=86400.0`, and `num_episodes=1` for the installed LeRobot `lerobot-record --policy.path=...` runtime.
- Rollout has a default-enabled ACT Temporal Ensemble filter. When enabled, the command includes `--policy.temporal_ensemble_coeff=0.01` and `--policy.n_action_steps=1`; ACT requires `n_action_steps=1` for temporal ensembling.
- Rollout has a default-enabled Safe Action Clamp checkbox. When enabled, the command includes `--robot.max_relative_target=<limit>` with GUI default `5`, limiting per-step target jumps in the LeRobot follower.
- Rollout/evaluation output dataset repo names are automatically normalized to `eval_*` by the bridge. GUI input may be `jin/pick_and_place_cube_rollout`, but the executed LeRobot repo id becomes `jin/eval_pick_and_place_cube_rollout`.
- Training GUI exposes the LeRobot CLI fields needed for practical local training: dataset repo/root, policy type, policy repo ID, output dir, job name, device, batch size, steps, num workers, eval/log/save frequencies, checkpoint saving, resume, AMP, optimizer, scheduler, policy chunk/action/observation windows, WandB controls, and one-safe-arg-per-line advanced CLI options.
- The LeRobot workspace also acts as the Manipulation Agent management GUI. Its `Manipulation Agent Bridge` panel calls `/api/lerobot/manipulation-agent/run`, which runs the actual `ManipulationAgent` with selected strategy, Pi0.5/generic policy type, profile, policy checkpoint/repo, source/target locations, specimen handoff metadata, and vision observation JSON.
- Manipulation Agent Bridge has `Save Agent Defaults` and `Test Agent Bridge` actions. Save persists live/test loop defaults in `memory/manipulation_agent_bridge.json`; Test forces the same agent-mediated execution path through `mode=test` so the operator can validate payload/profile/policy wiring before live orchestration.
- Policy paths for Manipulation Agent Bridge must be selectable through the same local browse mechanism used by rollout. This keeps operator selection consistent between direct LeRobot rollout and agent-mediated manipulation.
- The current ROBOTIS OMX default GUI training shape maps to `lerobot-train --dataset.repo_id=<dataset> --dataset.root=<root> --policy.type=<policy> --output_dir=<output> --job_name=<job> --policy.device=<device> --policy.repo_id=<repo> --batch_size=<n> --steps=<n> --num_workers=<n>` plus explicit eval/log/save and optimizer/scheduler fields.
- ACT training defaults follow Hugging Face LeRobot defaults: `batch_size=8`, `steps=100000`, `num_workers=4`, `eval_freq=20000`, `log_freq=200`, `save_freq=20000`, `policy.n_obs_steps=1`, `policy.chunk_size=100`, and `policy.n_action_steps=100`.
- Pi0.5 training is routed to the dedicated conda environment `lerobot-pi05`, worktree `/home/jin/lerobot_pi05`, and Hugging Face cache `/home/jin/.cache/huggingface_pi05`. Select policy type `pi05 (Pi0.5)` and use `Train Source Policy / HF Base=lerobot/pi05_base`; the bridge command includes `--policy.type=pi05` and `--policy.pretrained_path=lerobot/pi05_base`.
- When Pi0.5 is selected, the GUI switches defaults to `batch_size=32`, `steps=3000`, `policy.chunk_size=50`, `policy.n_action_steps=50`, and seeds recommended fine-tuning args: `--policy.compile_model=true`, `--policy.gradient_checkpointing=true`, `--policy.dtype=bfloat16`, `--policy.freeze_vision_encoder=false`, `--policy.train_expert_only=false`, and `--policy.normalization_mapping={"ACTION":"MEAN_STD","STATE":"MEAN_STD","VISUAL":"IDENTITY"}`. Operators can edit or remove these in Additional Train CLI Args before starting.
- Training status shows current step, total steps, percent, elapsed time, steps/sec, parsed latest loss, and ETA when the live LeRobot log exposes step progress.
- Policy selection supports configured HF policy repo IDs and discovered local checkpoints; dataset expansion through Hugging Face Hub is not part of the current GUI scope.
- Live subprocess execution occurs only when mode is `live`, the profile live gate is enabled, and the operator checks the live execution confirmation box.
- Dataset visualization is local: the GUI reads metadata under the selected dataset path and previews local video/image media through `/api/lerobot/visualization/file`.

Runtime IDE graph workspace:
- Route: `/ide`.
- The Runtime IDE graph canvas uses a fixed `Main System` tab for the active orchestration graph. The old visible graph dropdown and `Load Graph` button are intentionally hidden from the operator surface.
- Runtime IDE graph canvas must show the actual backend runtime contract: executable stage nodes, non-executable Orchestrator/Guardian/device/evidence overlay planes, declared bridge contracts from graph metadata, and module contracts loaded from `graphs/modules/*/module.yaml`. Overlay edges are informational only; route editing and readiness checks remain bound to `logical_transition` edges.
- Double-clicking an agent node opens that agent module as a browser-style internal graph tab beside `Main System`. Module tabs are closable; `Main System` is fixed.
- Main graph edits update the graph JSON draft and are applied through `Validate`, `Dry Run`, and `Save Version`.
- Module internal graph edits update `module.yaml` draft state. `Save Version` on a module tab routes to the module save API and changes the executable module step order/config used by the runtime.
- Graph nodes expose four connection ports: top, right, bottom, and left. Operators connect nodes by dragging from a source port and dropping on another node or target port; the legacy click-connect control is hidden from the operator surface. The editor stores the selected port side in logical edge metadata so the canvas reopens with stable edge attachment points. Node hit-testing uses `elementsFromPoint` plus bounding-box fallback, so drop targets still resolve when ports/icons overlap.
- Port connections update `transitions` plus the corresponding logical transition edge metadata. This keeps the visual graph, dry-run path, and saved runtime config aligned.
- The left sidebar contains a Module Catalog grouped by category (`design`, `fabrication`, `vision`, `manipulation`, `equipment`, `analysis`, `optimization`, `knowledge`, `guardian`, etc.). Dragging a catalog item to the Main System canvas creates a draft graph node bound to `modules/<module_id>`. Dragging it to an agent internal tab creates an internal module step.
- While dragging a node, the canvas exposes a bottom trash zone. Dropping the node there removes it from the graph draft; in module tabs it removes the corresponding `internal_graph` or `pre_execution` step from the module draft. Save still requires explicit validate/save.
- Module Designer accepts a Python file and sends it to Gemma 31B (`gemma4:31b`) for ATR protocol conversion. The result is saved as `graphs/modules/<module_id>/handler.py` plus `module.yaml` metadata, category, tool allowlist, internal steps, and version history. The generated handler remains pending until it is registered in the allowlisted runtime handler registry; the GUI never executes arbitrary uploaded Python directly.
- GUI and CUI are cross-compatible: both read/write the same `graphs/modules/*/module.yaml` files through `/api/modules`, and the `atr modules` / `atr module show|validate|dry-run|create` commands use the same Runtime API.
- Node labels, tab labels, status cards, and output rows are constrained with ellipsis/overflow guards to prevent text overlap in the reference 1536x1024 Runtime IDE layout.

Design Agent report surface:
- The Live GUI selected-agent report for Design Agent reads `state.run_metadata.design_report`, latest message `design_report`, or event payload `design_report`.
- The Design report card shows objective metric/direction, hypothesis, candidate counts, valid/rejected counts, selected score, uncertainty, information gain, risk, prior count, and handoff readiness.
- The expanded Design detail area shows candidate board, rejected/repair log, decision register, Knowledge/BO/failure prior context, and missing handoff fields.
- The Agent Report API `/api/agents/design/report` returns the same structured report under `sections.design_report`, plus role-specific `candidate_board`, `manufacturability`, `decision_register`, and `handoff_packet` fields.


2026-05-29 Specimen Making report update:
- The Specimen Agent report is now `Manufacturing Digital Thread / Printer Runtime`.
- Live GUI Specimen cards must surface `fabrication_report.v1`: fabrication intent, digital thread, process plan, quality gates, printer runtime, monitoring plan, fabrication outcome, and feedback to Design/Knowledge/BO.
- `specimen_fabricated.v1` is the downstream handoff packet; Vision/Manipulation should treat its location/readiness as pending physical confirmation when `requires_after_print_confirmation=true`. The packet exposes a compact `fabrication_summary`; the report view reads the full `fabrication_report.v1`.
- Report view should summarize manufacturing evidence. Raw printer payloads, full command arrays, and raw logs remain backend-trace material.

2026-05-29 Vision Agent report update:
- The Vision Agent report is now `Lab Perception Signal Bus / Visual Evidence`.
- Live GUI Vision cards must surface `vision_report.v1`: scene task, camera
  source, zone state, detection/tracking evidence, signal board, evidence
  timeline, dataset ledger, safety/anomaly, and `vision_signal.v1` handoff.
- The report view should show confidence, `expires_at`, and blocking reasons in
  human-readable rows. Raw capture payloads remain backend-trace material.
- Vision report does not imply action execution. Robot/printer/equipment actions
  remain owned by downstream agents and Guardian gates.

Vision chat card requirement:
- During planning/live handoff, Vision completion messages are represented as
  `live_chat_message.v1` / `message_type=signal` entries. The card text should
  summarize camera source, zone state, pickup-ready confidence, expiry time,
  anomaly state, and visual evidence path without exposing raw JSON.

2026-05-29 Manipulation Agent / Pi0.5 GUI update:
- The LeRobot workspace `Manipulation Agent Bridge` panel now exposes the two bounded tasks used by the live loop: `transfer_to_utm` and `clear_utm_to_disposal`.
- Task selection updates the default source, target, task instruction, and Vision observation template; operators may still override those fields.
- The panel includes Policy Backend, Policy Type, Pi0.5 RTC Execution Horizon, Pi0.5 RTC Max Guidance Weight, Max Duration Seconds, Safe Action Clamp, camera/display, and continuous-rollout controls.
- `Save Agent Defaults` persists these values to `memory/manipulation_agent_bridge.json`; `Test Agent Bridge` runs the same Manipulation Agent path in forced test mode; `Run Manipulation Agent` runs the actual agent-mediated path for the selected GUI mode.
- The Manipulation runtime report panel summarizes Skill Episode Board, Preflight, Pi0.5/Policy Runtime, Vision Dependency, SARM Stage Progress, Decision/Handoff, and Evidence. It is a human-readable report surface; raw JSON remains in backend trace/output.
- Live GUI selected-agent report for Manipulation Agent reads `state.run_metadata.manipulation_report` and `state.run_metadata.robot_task_result`, then renders the same task, policy, preflight, Vision, SARM, rollout, decision, and evidence sections.

GUI browser inspection requirement:
- Use Selenium from the main `.venv` when GUI layout, report rendering, route wiring, Runtime IDE canvas behavior, or Live GUI chat/report surfaces are changed.
- Preferred local stack: Firefox + `/snap/bin/geckodriver` + `selenium` from `requirements.txt`.
- Standard inspection flow:
  1. Start a temporary FastAPI server, for example `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 7862`.
  2. Use Selenium to open the changed route at a fixed viewport such as 1920x1080.
  3. Check that required labels/buttons/panels exist in the DOM and that key report content renders without raw JSON dumps where a human report is expected.
  4. Save screenshots to `runs/` or `artifacts/` for audit evidence.
  5. Stop the temporary server and any headless browser/geckodriver process.
- For quick route-specific checks, a one-off Selenium script is acceptable. For repeatable UI contracts, add or update a script under `tests/ui/` and reference it from the relevant test notes.



2026-05-29 LeRobot rollout queue / Pi0.5 note:
- LeRobot GUI execution buttons call backend ToolRegistry tools, not a separate direct bridge, so rollout/record/train/teleop execution observes the same device queue and session state as the live loop.
- Live rollout has an active-session guard. A second rollout request is blocked with `LEROBOT_ROLLOUT_ALREADY_ACTIVE` until the operator stops the active rollout.
- Pi0.5 rollout uses the local RTC wrapper `scripts/lerobot_pi05_rollout_wrapper.py` in the `lerobot-pi05` conda environment, because that environment exposes `lerobot-eval` and RTC examples rather than a `lerobot-rollout` binary.

2026-05-30 Lab Equipment report surface update:
- The Live GUI selected-agent report for Lab Equipment is now `Lab Equipment / UTM Visual Control`, not a generic bridge-command summary.
- The report reads `state.run_metadata.equipment_report`, `equipment_result`, `utm_data_ready`, and `equipment_handoff`.
- The front-end summary rows show registered UTM `program_id`, bridge/provider state, saved control profile, screen assertion count, Vision physical gate, CSV data artifact status, Linux CSV path, and Analysis handoff gate.
- The expanded detail area must render: Bridge / Protocol Profile, Preconditions, Screen-State Assertions, Vision Physical Cross-Checks, UTM Data Ledger, Handoff Gate / Blocking Reasons, and Evidence Refs.
- Raw bridge payloads and command logs remain backend-trace material; the report surface is for operator-readable evidence that screen, physical, save/export, file, and parse gates were actually satisfied before Analysis.

2026-05-30 Equipment report browser audit:
- Repeatable browser audit script: `tests/ui/equipment_report_browser_audit.py`.
- The script launches headless Firefox through Selenium/geckodriver, injects a representative `equipment_report.v1` debug payload into `/live`, selects the Equipment report view, and verifies the 1920x1080 DOM contains the UTM visual-control report sections without horizontal overflow.
- Required visible sections are Bridge / Protocol Profile, Preconditions, Screen-State Assertions, Vision Physical Cross-Checks, UTM Data Ledger, Handoff Gate / Blocking Reasons, Safety Gate / Guardian, Live Evidence Audit, Artifact / Evidence Ledger, Failure / Recovery, and Evidence Refs.
- Latest audit evidence screenshot path: `artifacts/ui/equipment_report_browser_audit.png`.
- Latest 1920px browser audit result: PASS, `scrollWidth=1920`, `clientWidth=1920`, screenshot `1920x994`.

2026-05-30 Windows Bridge GUI browser audit:
- Repeatable browser audit script: `tests/ui/windows_bridge_gui_browser_audit.py`.
- The script opens the standalone Windows PyAutoGUI bridge root page, injects a non-actuating fake `step_trace`, verifies Run Timeline rendering, checks required operator panels, and enforces no horizontal overflow at 1920px.
- Required visible sections include Local Operator Console, Payload Preview, Run Timeline, UTM Protocol, Preflight + Run Live UTM, Stop / Abort, Live Proof Checklist, Request Audit, Bridge Files, Step Trace, Artifacts, Artifact Preview, and Operator Log.
- Latest audit evidence screenshot path: `artifacts/ui/windows_bridge_gui_browser_audit.png`.
- Latest 1920px browser audit result: PASS for both `install/windows_pyautogui_bridge_server.py` and `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`, `scrollWidth=1908`, `clientWidth=1908`, screenshot `1920x994`.

2026-05-30 Windows Equipment live preflight:
- The Windows PyAutoGUI Bridge GUI exposes a `Live Preflight` button next to UTM profile/readiness controls.
- The action calls `/api/equipment/windows/live-preflight` with explicit confirmation and displays the structured result in the Result Log.
- The preflight is non-actuating: it may check bridge health, program registry, locator listing, and optionally capture one screenshot, but it must not call `/execute`.
- Operators should use this after `Save UTM Profile` and before `Run UTM Protocol Test` or an autonomous Lab Equipment run.

## 2026-05-30 Live GUI Lab Equipment Evidence/Recovery Surface

The Live GUI Equipment selected-agent report now exposes the additional Lab Equipment failure-memory contract:

- `Artifact / Evidence Ledger`: all artifact refs, screen evidence refs, data evidence refs, and normalized bridge artifact records.
- `Failure / Recovery`: recovery status, operator intervention flag, retry count, fallback macros, recommended action, and failure/retry rows.
- `Handoff Gate / Blocking Reasons`: remains the workflow gate; screen evidence does not replace the UTM CSV required for Analysis.

This gives operators a visible path from Windows PyAutoGUI screen evidence to Guardian/Knowledge failure review without confusing screenshots with UTM curve data.

## 2026-05-30 Lab Equipment Report Safety Gate

The Live GUI Equipment report includes a dedicated `Safety Gate / Guardian` section. It surfaces Guardian/hardware-alert evidence next to UTM handoff gates so operators can distinguish these cases:

- UTM is ready and Guardian status is `allow`;
- UTM data/screen/Vision evidence is incomplete and workflow is blocked;
- Guardian requires human approval or safe-stop/recovery before retry.

The Equipment report also displays request-audit details under Live Evidence Audit, including whether the Windows bridge request log proves the live `/execute` command.

## 2026-05-30 Windows PyAutoGUI Bridge Local GUI Proof Checklist

The Windows-side bridge page at `http://<windows-bridge>:8765/` now includes a `Live Proof Checklist` panel.

- `Refresh Evidence` calls only passive endpoints: `/health`, `/readiness`, and `/request-log`.
- `Auto-refresh request audit` polls `/request-log` every 5 seconds while the page is visible.
- The checklist shows Health + PyAutoGUI, UTM locator readiness, local live-safety confirmation, request-log `/execute`, screen evidence, and CSV parse-probe state.
- The panel is for local operator awareness; Linux-side workflow gates remain authoritative for autonomous handoff.

## 2026-05-30 Windows Equipment Evidence Proof Checklist

The Linux-side Windows Equipment workspace now renders a proof checklist from `/api/equipment/windows/evidence-audit`.

- API fields: `proof_checklist[]` and `proof_ready`.
- Required proof items: Windows bridge `/execute` audit, UTM screen-state evidence, physical UTM motion cross-check, Linux UTM artifact pull, CSV parse probe, and Vision frame evidence.
- The UI shows the open proof item IDs in the UTM Evidence Audit card so operators can see why Analysis handoff is blocked, including save/export responsibility and `/execute` identity-audit failures.
- The request-audit parser accepts both recent request paths and Windows bridge summary fields such as `execute_event_seen`, `execute_event_count`, and `last_execute_at`.

## 2026-05-30 Windows Equipment UTM Pre-Execution Gate

The Windows Equipment workspace now blocks UTM live execution before contacting Windows `/execute` when setup readiness is incomplete.

- A UTM `Run UTM Protocol Test` request first evaluates passive readiness with the exact payload overrides from the GUI.
- Non-simulated UTM control requires `ready_for_autonomous_profile=true`.
- If blocked, the Result Log shows `UTM_PRE_EXECUTION_READINESS_BLOCKED`, `bridge_not_called=true`, and the readiness blockers. This is intentionally non-actuating.
- Simulation-mode UTM requests use the weaker `ready_for_setup_test` gate.


### Windows Equipment Proof Package

The Windows Equipment workspace exposes `Build Proof Package` for the Lab Equipment/UTM stage. The button calls `/api/equipment/windows/proof-package` and renders a single JSON package containing readiness, live preflight summary, evidence audit, proof checklist, request-log `/execute` proof, screen/data evidence refs, Vision frame IDs, blockers, warnings, and next actions. `Verify Proof Package` re-checks the persisted package and re-runs the Linux UTM CSV signal-quality gate, so flat/all-zero force or displacement files remain blocked even if the summary claimed a parseable CSV. This is a non-actuating review/export path; it must not call the Windows bridge `/execute` endpoint.

### Windows Equipment Proof Package Artifact

The Windows Equipment workspace `Build Proof Package` action now saves a JSON artifact for the current run. The file is written under `artifacts/equipment/<run_id>/utm/` and is returned as `package_artifact` from `/api/equipment/windows/proof-package`. This makes the operator-visible proof checklist reproducible after page refresh, server restart, or later audit.

### Windows Equipment Browser Audit

The Linux-side `/equipment/windows` workspace now has a repeatable Selenium browser audit: `tests/ui/windows_equipment_browser_audit.py`.

- The audit opens `/equipment/windows`, injects passive readiness/evidence/proof payloads into the browser-side renderers, and verifies the operator can see readiness, preflight, UTM run, evidence, abort, request audit, proof package, and proof verification controls.
- It checks blocked proof states such as `UTM_SAVE_EXPORT_RESPONSIBILITY_REQUIRED` and `UTM_DATA_NO_FORCE_SIGNAL` are visible without reading backend JSON first.
- Latest local 1920px audit result: PASS, `scrollWidth=1908`, `clientWidth=1908`, screenshot `artifacts/ui/windows_equipment_browser_audit.png` (`1920x994`).

### Windows Standalone Bridge Proof Gates

The Windows bridge root GUI now includes a compact seven-gate proof strip in the Live Proof Checklist. It summarizes the same gate state used by the detailed checklist: bridge health, UTM locators, local safety confirmation, `/execute` request-log proof, screen evidence, save/export responsibility, and CSV parse readiness. This is verified by `tests/ui/windows_bridge_gui_browser_audit.py`, which checks the new gate DOM ids and the 1920px layout without horizontal overflow.

### Windows PyAutoGUI Bridge Field Runbook

The standalone Windows bridge GUI includes a `Field Runbook` in the left connection column. The four cards summarize the operator path for live UTM work: connect the bridge, calibrate UTM locators, execute only a registered protocol, and verify handoff evidence. The cards update from the same proof-state logic as the Windows `Live Proof Checklist`, so they are not decorative status badges.

Use this page on the Windows workstation when calibrating or checking the PyAutoGUI bridge directly. Use the Linux `/equipment/windows` page for bridge discovery, saved profile management, Linux artifact pull verification, and autonomous Lab Equipment Agent handoff checks.

## 2026-05-30 Windows PyAutoGUI Bridge GUI Update

The standalone Windows PyAutoGUI bridge page now includes a `Bridge Command Kit` in the Connection panel. It copies Linux curl health, Windows PowerShell health, and curl `/execute` commands from the same URL/token/payload shown in the browser. This keeps GUI and CUI operation comparable during equipment debugging.

The page also waits for an entered bridge token before auto-running authenticated checks, widens the sticky live command rail for 1920x1080 operator displays, and color-codes Step Trace rows by status. The command banner includes `Recommended next action`, which follows the first open Live Proof Checklist gate and jumps to the appropriate token, Health, Readiness, safety confirmation, screenshot, evidence refresh, or Live UTM control.

2026-05-31 Orchestrator Supervisor report update:
- The Orchestrator report is now `Orchestration Supervisor / Follow-up Control`.
- Live GUI Orchestrator cards surface mission contract, compiled orchestration plan, route map, planned parallel read-only checks, latest executed parallel check batch, serial physical actions, expected artifacts, latest supervisor opinion, follow-up timeline, decision register, handoff registry, and loop reflection.
- Runtime chat receives `orchestrator.followup` as a concise supervisor message: current stage, trigger, judgment, concerns, recommendation, optional choices, and whether operator response is required.
- The report reads the same server state as the runtime: `state.run_metadata.latest_mission_contract`, `latest_orchestration_plan`, `latest_orchestrator_parallel_checks`, `orchestrator_followups`, `orchestrator_decision_register`, `orchestrator_handoff_packets`, and `loop_reflections`.
- Agent-produced packets remain visible in each agent report; Orchestrator handoff packets are the cross-agent broker layer and should not replace Design/Specimen/Vision/Equipment/Analysis/BO packets.
- Raw prompt/tool JSON remains backend trace material. The report view should show the operator-facing decision narrative and compact evidence links.
