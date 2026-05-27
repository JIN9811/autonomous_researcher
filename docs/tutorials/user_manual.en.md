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
| Module Management | `/module-management` | Module validation, load state, generated adapter registration |
| 3DP Workspace | `/printer` | Prusa connection, slicing profile, auto-ejection, test options |
| LeRobot Workspace | `/lerobot` | Port/camera setup, teleop, recording, training, rollout |
| BO Workspace | `/bo` | Acquisition/strategy/budget/parameter-space configuration |
| CAE Workspace | `/cae` | STL analysis settings and results |
| Windows Equipment | `/equipment/windows` | Windows PyAutoGUI bridge discovery and program execution |
| Self-Evolution Lab | `/evolution-lab` | Prompt/module/graph variants, validation, approval, rollback |

### 1.4 Runtime Modes

- `live`: real hardware path, requires device gates and operator confirmation.
- `test`: dry-run and simulated path, with selected bridge/actual-print options when explicitly requested.
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

### 2.3 Core APIs

- Runtime: `/api/runtime/state`, `/api/events/recent`, `/api/events/stream`, `/api/run/start`, `/api/run/stop`, `/api/run/safe-stop`
- Runs: `/api/runs/{run_id}`, `/api/runs/{run_id}/events`, `/api/runs/{run_id}/artifacts`, `/api/runs/{run_id}/approvals`
- Planning: `/api/planning/session`, `/api/planning/bootstrap`, `/api/planning/message`
- Graphs: `/api/graphs`, `/api/graphs/{graph_id}/validate`, `/compile`, `/dry-run`, `/run`, `/save-version`
- Modules: `/api/modules`, `/api/modules/{module_id}/validate`, `/dry-run`, `/load`, `/unload`, `/register-generated`
- Workspaces: `/api/printer/*`, `/api/lerobot/*`, `/api/bo/*`, `/api/cae/*`, `/api/equipment/windows/*`, `/api/evolution/*`

### 2.4 Extension Rules

- Add or change execution order in graph YAML, then validate and dry-run.
- Add or change stage behavior in `graphs/modules/<module>/module.yaml`.
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
