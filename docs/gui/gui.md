# GUI

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
- In normal Live GUI mode, `실험 수행` means Design Agent -> Specimen Making Agent -> PrusaSlicer -> PrusaLink upload/start. The printer runtime card must show storage readiness plus upload/start status.
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
- Design Agent messages may render STL/preview artifacts and the browser STL viewer.
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
- Saved BO settings include mode, objective, strategy, acquisition function, budget, seed, exploration/exploitation controls, and parameter-space bounds.
- Benchmark and BO Agent actions remain virtual optimization controls only; the BO GUI does not directly start printer or robot hardware.

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
