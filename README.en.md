# Autonomous Researcher Framework

Autonomous Researcher Framework is an integrated multi-agent system for autonomous laboratory workflows.
It combines LangGraph-based runtime execution, a Live GUI, hardware bridge integrations, BO/CAE analysis, and model-based orchestration in one control plane.

## 1) What You Need First

- Repository: `/home/jin/autonomous_researcher`
- Python 3.10+ and Git
- NVIDIA GPU host for vLLM-based inference (optional if using Ollama/virtual mode)
- One terminal session with write access to the repository and local cache directories

## 2) Installation

```bash
cd /home/jin/autonomous_researcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash install/install_cli.sh
```

Notes:

- Reload shell or run `source ~/.bashrc` so `atr` is in PATH.
- For quick startup without launcher: `.venv/bin/python -m app.serve`

## 3) Start / Stop Server

```bash
atr up      # start
atr down    # stop
```

Default endpoints (once running):

- Main: `http://localhost:7860`
- API docs: `http://localhost:7860/docs`
- Live GUI: `http://localhost:7860/live`
- Runtime IDE: `http://localhost:7860/ide`
- Module Management: `http://localhost:7860/module-management`

## 4) Runtime Modes

- `live`
  - Real equipment execution path (Prusa / LeRobot / Windows bridge)
- `test`
  - Dry-run + dry evaluation path with safety gates retained
- `virtual`
  - No physical device actions

All modes share the same Experiment Runtime contract:
- `experiment.evaluate`
- `experiment.benchmark`
- `experiment.queue.status`

## 5) Core Execution Flow

```text
Main GUI -> Live GUI -> Orchestrator -> LangGraph -> Stage Agents -> Bridges -> Guardian
```

Sequence in default runtime:

1. Design
2. Specimen
3. Vision
4. Manipulation
5. Equipment
6. Analysis
7. Knowledge
8. BO
9. Guardian
10. Complete / Stop / Error

## 6) Minimum First Run (Recommended)

1. Confirm services and dependencies are available (see [Requirements](REQUIREMENTS.md)).
2. Start GUI with `atr up`.
3. Open `http://localhost:7860/live`.
4. Run test mode first:
   - Check model load status
   - Open required model if not auto-loaded
   - Select `Test` mode
   - Press `Start`
5. Validate planning handoff and artifact output.
6. Confirm queue metadata exists for any equipment call (job id).
7. Switch to Live mode only after all required inputs are present.

## 7) Device Setup References

- Prusa / 3DP: [`docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`](docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md),
  [`docs/hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt`](docs/hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt)
- Robot: [`docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`](docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md)
- Windows bridge: [`docs/hardware/windows_pyautogui_equipment_agent_guideline.md`](docs/hardware/windows_pyautogui_equipment_agent_guideline.md)

## 8) Tutorial / Guide

- [First autonomous run (English)](docs/tutorials/first_autonomous_run.en.md)
- [First autonomous run (Korean)](docs/tutorials/first_autonomous_run.ko.md)

## 9) Architecture and Contract Docs

- [`docs/runtime/langgraph_runtime.md`](docs/runtime/langgraph_runtime.md)
- [`docs/runtime/autonomous_experiment_runtime.md`](docs/runtime/autonomous_experiment_runtime.md)
- [`docs/runtime/agent_program_baseline.md`](docs/runtime/agent_program_baseline.md)
- [`docs/README.md`](docs/README.md)

## 10) Troubleshooting

- If model responses fail due to context overflow, reduce prompt size and clear stale chat sessions.
- If printer queue is not moving, inspect `experiment.evaluate` output and `experiment queue status`.
- If Live GUI reconnects but state is stale, use refresh and confirm SSE / stream heartbeat in the header.

### Useful Commands

```bash
rg "TODO" /home/jin/autonomous_researcher/docs
rg "status\|ready\|dry-run\|run.created" -n /home/jin/autonomous_researcher/web/static /home/jin/autonomous_researcher/web/templates
```

## 11) Maintenance and Contributions

- Keep `main` as stable baseline.
- For risky changes: create branch, validate, then merge.
- Update `docs` and `REQUIREMENTS.md` whenever runtime behavior changes.
