# Autonomous Researcher Complete User Manual

This manual is the operator and developer entry point for the current repository.
It is split into beginner and advanced sections so a new user can run the GUI while a developer can trace the runtime contracts, APIs, and extension points.

## 1. Beginner Path

### 1.1 Install

```bash
cd /home/jin/autonomous_researcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash install/install_cli.sh
atr up
```

Open:

- Main GUI: `http://localhost:7860/`
- Live GUI: `http://localhost:7860/live`
- API docs: `http://localhost:7860/docs`

Stop:

```bash
atr down
```

Full external requirements are tracked in [../../REQUIREMENTS.md](../../REQUIREMENTS.md).
The current code-exposed route/API/manifest/model snapshot is tracked in
[../runtime/current_code_snapshot.md](../runtime/current_code_snapshot.md).

Current local model controls expose two managed NemoClaw/vLLM deployments:
`gemma4:31b` and `gemma4:e4b-it-nvfp4`. `e2b` is not part of the managed model
surface. `31b` is the orchestrator primary route and uses MTP speculative
decoding; `e4b` is the subordinate route and is served as NVFP4 target-only.
Use the Main GUI `Current Models` panel or the CLI commands below:

```bash
atr models
atr model load 31b
atr model load e4b
atr model unload 31b
atr model unload e4b
```

OpenAI API-key operation is separate from managed local model loading. The
Main GUI `API Key` dialog stores the key in local `memory/api_keys.json`.
`Loading` promotes OpenAI to the first inference route; `Unloading` keeps the
stored key but returns local vLLM to first priority.

### 1.2 First Run

1. Start the server with `atr up`.
2. Open the Main GUI and confirm runtime/model/device status.
3. Open `/live`.
4. Send `테스트 모드` or a test objective.
5. Watch Report, Backend, Graph, Artifacts, and Timeline tabs.
6. Confirm that a `run_id`, stage events, and artifacts appear.
7. Review outputs under `runs/`, `artifacts/`, and `memory/`.

### 1.3 GUI Map

| Page | URL | Purpose |
|---|---|---|
| Main GUI | `/` | Runtime status, model state, run controls, device workspace launchers |
| Live GUI | `/live` | Chat-based orchestration and stage progress |
| Runtime IDE | `/ide` | Graph editing, validation, dry-run, version save |
| Module Management | `/module-management` | Module validation, load state, draft module creation, `ui.yaml` descriptor management, generated adapter registration |
| 3DP Workspace | `/printer` | Bambu Lab X2D default bridge, explicit Prusa selection, printer fleet, live video/status, slicing/start gates, auto-ejection, test options |
| LeRobot Workspace | `/lerobot` | Port/camera setup, teleop, recording, training, rollout |
| BO Workspace | `/bo` | Acquisition/strategy/budget/parameter-space configuration |
| CAE Workspace | `/cae` | STL analysis settings and results |
| Windows Equipment | `/equipment/windows` | Windows PyAutoGUI bridge discovery and program execution |
| Self-Evolution Lab | `/evolution-lab` | Prompt/module/graph variants, validation, approval, rollback |

### 1.4 Runtime Modes

- `live`: real hardware path, requires device gates and operator confirmation.
- `test`: dry-run and simulated path, with selected bridge/actual-print options when explicitly requested.
- In the current 3DP Workspace, `Start Gate Check`, `SPC Readiness`, and `Publish Start` no longer expose manual operator/Guardian/dry-run checkboxes. The frontend sends owner-managed publish defaults (`operator_confirmed=true`, `guardian_approved=true`, `dry_run=false`, ejection path fields true), and the backend remains the actual gate for artifact validity, printer safe state, camera evidence, bed-clear evidence, and post-publish observation.
- `Publish Start` can call the start-publish API, but the backend sends the Bambu MQTT `project_file` command only when the selected printer gate, transfer path, camera/bed-clear requirements, owner-managed publish defaults, and safe-state checks all pass.
- `SPC Readiness` level cards separate connection, transfer path, owner-managed publish defaults, publish command, and autoejection. `technical_ready_for_start=true` means the technical printer gates are clear, but publish still remains blocked when camera, bed-clear, safe-state, or start-gate evidence fails.
- For Bambu X2D, `Upload Path Probe` checks whether FTPS is actually writable. Login/list alone is not enough. If the probe reports read-only or `BAMBU_FTPS_WRITE_FAILED`, use `Prepare HTTP Artifact` with a sliced `.gcode.3mf` file. The backend must then GET the generated URL and match sha256 (`server_fetch_probe.ok=true`) before the GUI treats Upload as ready.
- `/api/bridges` is the graph bridge registry, not the printer fleet selector. Check the active Bambu/Prusa printer provider through `/api/printer/fleet`.
- That probe must use a printer-reachable LAN URL. The server default is `0.0.0.0:7860`, so operators may open `localhost` in the browser while Bambu receives `http://<ATR-server-LAN-IP>:7860/printer-artifacts/...`. A loopback-only bind or localhost artifact URL is not valid transfer evidence for the printer.
- A plain remote path such as `cache/specimen.gcode.3mf` is not an HTTP artifact route. It cannot bypass FTPS write verification. Only generated `http://` or `https://` artifact URLs with a passing fetch probe are treated as ready transfer evidence.
- `HTTP_ARTIFACT_READY_NOT_STARTED` means the artifact URL and guarded start-command draft are ready for review. It does not start printing; `Publish Start` still requires browser confirmation plus owner-managed publish defaults and a passing backend start gate.
- A Bambu MQTT `project_file` publish acknowledgement is not treated as proof that printing started. The backend immediately reads a fresh printer observation and returns `post_publish_status`. If the printer remains `IDLE` or not-started, the response keeps `published=true` but returns `ok=false` with `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED`.
- `Fill Native G-code Defaults` only fills Bambu autoejection patch fields locally. It does not save readiness evidence, patch the source artifact, or run motion. The gate changes only after the operator verifies the source artifact/plate target and clicks `Save Autoejection Config`; physical start still requires `Publish Start` after the normal gate passes.
- `Validate G-code Preview` and left/center/right validation are non-mutating checks. This validation-only path writes no `.autoeject.*` file and no manifest; it only returns the would-be tail, object bounds, candidate hash, and blockers. `Generate Ejection Test Artifact` and `Generate Sweep Test Artifact` create standalone validation files only and must not publish printer motion. Use `Generate Patched Artifact` to create a `.autoeject.*` file, then use `Publish Start` only after the normal live gate passes.
- Bambu native autoejection exposes push direction, Z push offset, push lane offset, push speed, full-bed sweep, sweep Z, and sweep speed. P1/P1S/X1/X1C use an X-axis multi-lane generator; A1/A1 Mini require a separate bed-slinger/wiggle generator.
- Before publishing a `.autoeject.*` artifact, the workstation owner/operator must physically manage front path/door clearance, ramp/bin readiness, toolhead cover security, release surface/profile, and supervised first ejection at the printer. The GUI records this as `operator_managed=true` evidence instead of a manual checklist, while the backend still blocks on camera, bed-clear, artifact, and start-state evidence.
- Camera/video status is a separate plane from MQTT progress/material status. A failed video probe must show a camera blocker without clearing already loaded printer progress or AMS/material evidence.
- Read Bambu bridge evidence as five planes: `artifact`, `validation`, `transport`, `runtime`, and `bed-clear`. Physical autoejection is not considered successful from `published=true` alone; it requires camera/operator observation, post-publish state, bed-clear lock/unlock evidence, and a clear next-job gate.
- Physical Bambu autoejection completion is audited through the `/printer` `Physical Proof Package` controls or `scripts/audit_bambu_autoejection_completion.py`. `Build Fail-Closed Proof Template` only creates a JSON scaffold. `Run Completion Audit` must verify file-backed camera, manifest, post-publish, bed-clear, and next-job gate evidence before the system may describe Bambu autoejection as physically complete.
- `virtual`: no physical device actions.

## 2. Advanced Path

### 2.1 Closed Loop

The executable source of truth is [../../graphs/configs/atr_closed_loop.yaml](../../graphs/configs/atr_closed_loop.yaml).

```text
dispatch -> idle -> design -> specimen -> vision -> manipulation -> equipment -> analysis -> knowledge -> bo -> guardian
                                                                                                      | continue
                                                                                                      v
                                                                                                    design

guardian -> stop: complete
guardian -> error: error
```

Runtime evidence is emitted through `run.started`, `node.started`, `node.completed`, `edge.traversed`, `approval.*`, `artifact.created`, and terminal run events.

### 2.2 Agent Modules

| Stage | Module | Responsibility |
|---|---|---|
| design | `graphs/modules/design` | Convert objective into TPMS/specimen design contract |
| specimen | `graphs/modules/specimen` | Generate STL/G-code/manufacturing handoff |
| vision | `graphs/modules/vision` | Capture observation and transfer readiness |
| manipulation | `graphs/modules/manipulation` | LeRobot policy rollout or pick-place handoff |
| equipment | `graphs/modules/equipment` | Windows/UTM/equipment command bridge |
| analysis | `graphs/modules/analysis` | UTM/CAE metrics and objective score |
| knowledge | `graphs/modules/knowledge` | Memory/evidence update |
| bo | `graphs/modules/bo` | Candidate selection with benchmark/acquisition logic |
| guardian | `graphs/modules/guardian` | Safety and continue/stop/error decision |

Live GUI agent tabs and descriptor cards are loaded from `/api/runtime/agent-manifests`, which merges graph YAML, module YAML, and optional `graphs/modules/<module>/ui.yaml` files. `ui.yaml` is presentation-only: labels, short names, icons, report card selectors, and report sections may change there, but handlers, graph routes, tool allowlists, and live device authority do not.

### 2.3 Core APIs

- Runtime: `/api/runtime/state`, `/api/events/recent`, `/api/events/stream`, `/api/run/start`, `/api/run/stop`, `/api/run/safe-stop`
- Runs: `/api/runs/{run_id}`, `/api/runs/{run_id}/events`, `/api/runs/{run_id}/artifacts`, `/api/runs/{run_id}/approvals`
- Planning: `/api/planning/session`, `/api/planning/messages`, `/api/planning/bootstrap`, `/api/planning/message`
- Graphs: `/api/graphs`, `/api/graphs/{graph_id}/validate`, `/compile`, `/dry-run`, `/run`, `/save-version`
- Modules: `/api/modules`, `/api/modules/management-state`, `/api/runtime/agent-manifests`, `/api/bridges`, `/api/modules/templates/{agent|ui-only|bridge}`, `/api/modules/{module_id}`, `/api/modules/{module_id}/ui`, `/api/modules/{module_id}/validate`, `/dry-run`, `/load`, `/unload`, `/register-generated`
- Workspaces: `/api/printer/*`, `/api/lerobot/*`, `/api/bo/*`, `/api/cae/*`, `/api/equipment/windows/*`, `/api/evolution/*`

### 2.4 Extension Rules

- Add or change execution order in graph YAML, then validate and dry-run.
- Add or change stage behavior in `graphs/modules/<module>/module.yaml`.
- Add or change Live GUI presentation in `graphs/modules/<module>/ui.yaml`; do not use it for execution authority.
- Draft modules created by `/api/modules/templates/*` are preview-only until attached to a graph, validated, dry-run, and saved.
- Keep tool allowlists minimal.
- Never execute arbitrary uploaded Python directly; use generated adapter approval.
- Keep real hardware calls behind live gates, job/session IDs, and runtime events.
- Update documentation and tests with runtime behavior changes.

### 2.5 Verification

```bash
pytest
pytest tests/integration/test_controller_run.py
pytest tests/integration/test_live_gui_runtime_layout.py
pytest tests/integration/test_printer_gui_api.py
pytest tests/integration/test_lerobot_gui_api.py
pytest tests/integration/test_bo_gui_api.py
pytest tests/integration/test_cae_gui_api.py
```

Browser audits:

```bash
python tests/ui/planning_browser_audit.py
python tests/ui/runtime_ide_browser_audit.py
python tests/ui/module_management_browser_audit.py
python tests/ui/live_runtime_ide_browser_audit.py
```

### 2.6 Where to Look

| Need | Source |
|---|---|
| Overall docs | [../README.md](../README.md) |
| Closed loop details | [../runtime/closed_loop_and_pages_reference.md](../runtime/closed_loop_and_pages_reference.md) |
| LangGraph runtime | [../runtime/langgraph_runtime.md](../runtime/langgraph_runtime.md) |
| Live GUI | [../gui/gui.md](../gui/gui.md) |
| Printer | [../hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt](../hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt) |
| LeRobot | [../hardware/lerobot_robotis_manipulation_runtime_guideline.md](../hardware/lerobot_robotis_manipulation_runtime_guideline.md) |
| Windows bridge | [../hardware/windows_pyautogui_equipment_agent_guideline.md](../hardware/windows_pyautogui_equipment_agent_guideline.md) |
| Git workflow | [../repository/github_version_control.md](../repository/github_version_control.md) |
