# Autonomous Researcher Framework

Autonomous Researcher Framework is a local multi-agent automation system for closed-loop experimental research.
It connects experiment design, specimen manufacturing, equipment control, analysis, Bayesian optimization, and safety gating through a FastAPI server, Live GUI, LangGraph runtime, device bridges, BO/CAE workspaces, LeRobot tooling, and Runtime IDE.

## 1. Quick Start

New users should start with the [Complete User Manual](docs/tutorials/user_manual.en.md). It covers installation, first run, GUI usage, device setup, advanced APIs, graph/module contracts, troubleshooting, and extension rules.

If code and documentation appear to disagree, check the
[Current Code Snapshot](docs/runtime/current_code_snapshot.md) first. That
snapshot is refreshed against `app/main.py`, `graphs/configs/*.yaml`,
`graphs/modules/*`, `device_bridges/*`, `web/templates/*`, and `web/static/*`.
As of 2026-06-17, `app/main.py` exposes 224 FastAPI `APIRoute`
endpoints. The full `app.routes` registry has 229 entries when
`/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`, and `/static`
are included. These counts are used as documentation sanity checks when
route/API contracts are updated. They are measured by importing the FastAPI
app, not by grepping decorators, because some route registrations are not
single-line decorator literals.

Windows/API-key users can skip local AI by setting `AUTONOMOUS_BACKEND=openai`
and `OPENAI_API_KEY` in `.env`, then starting with `python -m app.serve`.
For local-first Linux workstations, keep `AUTONOMOUS_BACKEND=vllm`; OpenAI is
available as the final backend fallback through `configs/models.yaml`.
The Main GUI `Current Models` panel also includes an `API Key` button.
The saved key is kept only in local `memory/api_keys.json`. When `Loading` is
enabled, OpenAI becomes the first inference route; `Unloading` keeps the saved
key but returns local vLLM to first priority.
The current managed local vLLM surface has two models:
`gemma4:31b` and `gemma4:e4b-it-nvfp4`. `e2b` is not part of the Main GUI/API
managed model list. `31b` uses MTP speculative decoding, while `e4b` is served
as a stable NVFP4 target-only deployment.

```bash
cd /home/jin/autonomous_researcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash install/install_cli.sh
atr up
```

Stop the server:

```bash
atr down
```

Direct startup without the launcher:

```bash
.venv/bin/python -m app.serve
```

Windows direct startup:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.serve
```

## 2. Main Pages

| Page | URL | Template / Script | Purpose |
|---|---|---|---|
| Main GUI | `http://localhost:7860/` | `web/templates/index.html`, `web/static/app.js` | Runtime status, run control, model state, device workspace entry |
| Live GUI | `http://localhost:7860/live` | `web/templates/planning.html`, `web/static/planning.js` | Chat-based orchestration, agent progress, artifacts, backend trace |
| Runtime IDE | `http://localhost:7860/ide` | `web/templates/runtime_ide.html`, `web/static/runtime_ide.js` | LangGraph graph/node/edge editing, validation, dry-run, execution |
| Module Management | `http://localhost:7860/module-management` | `web/templates/module_management.html`, `web/static/module_management.js` | Module loading, validation, versioning, draft module creation, `ui.yaml` descriptor management, generated adapter management |
| 3DP Workspace | `http://localhost:7860/printer` | `web/templates/printer.html`, `web/static/printer.js` | Bambu Lab X2D default bridge, explicit Prusa selection, live video/status, slicing/start gates, auto-ejection, test-print settings |
| LeRobot Workspace | `http://localhost:7860/lerobot` | `web/templates/lerobot.html`, `web/static/lerobot.js` | Port detection, teleop, recording, training, visualization, rollout |
| BO Workspace | `http://localhost:7860/bo` | `web/templates/bo.html`, `web/static/bo.js` | BO/MBO/LLM preference strategy, lightweight/BoTorch optional backend, reasoning audit, candidate ranking/selection |
| CAE Workspace | `http://localhost:7860/cae` | `web/templates/cae.html`, `web/static/cae.js` | STL analysis, bottom fixed/top cyclic load settings, result review |
| Windows Equipment | `http://localhost:7860/equipment/windows` | `web/templates/windows_equipment.html`, `web/static/windows_equipment.js` | Windows PyAutoGUI bridge discovery, saved targets, tests, program launch |
| Self-Evolution Lab | `http://localhost:7860/evolution-lab` | `web/templates/evolution_lab.html`, `web/static/evolution_lab.js` | Prompt/module/graph variants, validation, approval, rollback |

Open `http://localhost:7860/docs` for FastAPI API documentation.

The default server bind is `0.0.0.0:7860`. Operators may still open the GUI at
`http://localhost:7860/`, but Bambu Lab HTTP artifact routing requires a printer
reachable URL such as `http://<ATR-server-LAN-IP>:7860/printer-artifacts/...`.
If the server is bound only to `127.0.0.1`, the GUI can load locally but Bambu
fetch probe and the SPC Readiness transfer gate will fail.

## 3. Actual Closed Loop

The default execution graph is [graphs/configs/atr_closed_loop.yaml](graphs/configs/atr_closed_loop.yaml).
A run starts through `POST /api/run/start` or `POST /api/runtime/start`. The runtime then invokes `LangGraphRunLoop`, reads the current stage, executes the corresponding node, and records events.

```text
dispatch -> idle -> design -> specimen -> vision -> manipulation -> equipment -> analysis -> knowledge -> bo -> guardian
                                                                                                      | continue
                                                                                                      v
                                                                                                    design

guardian -> stop: complete
guardian -> error: error
```

A real loop is visible through runtime events:

- `run.started`
- `node.started`
- `node.completed`
- `edge.traversed` or `stage_transition`
- `approval.requested` / `approval.resolved`
- `artifact.created`
- `run.completed` or `run.failed`

Useful APIs:

- `GET /api/runtime/state`
- `GET /api/events/recent`
- `GET /api/events/stream`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/artifacts`

## 4. Agents

| Stage | Module Path | Responsibility | Representative Output |
|---|---|---|---|
| `design` | `graphs/modules/design` | Convert the objective into TPMS/specimen design variables and `experiment_spec` | `current_experiment_spec`, STL candidate settings |
| `specimen` | `graphs/modules/specimen` | Create STL/manufacturing metadata and hand off to the selected Bambu/Prusa/virtual printer bridge | STL, gcode/sliced artifact, slicer settings, printer prepare result |
| `vision` | `graphs/modules/vision` | Observe printed specimen/workspace and create pickup/test observation | `observation`, camera artifact |
| `manipulation` | `graphs/modules/manipulation` | Run LeRobot rollout or pick-place handoff | rollout status, policy path, transfer evidence |
| `equipment` | `graphs/modules/equipment` | Execute UTM/Windows bridge/equipment commands | equipment result, protocol note |
| `analysis` | `graphs/modules/analysis` | Compute UTM/CAE/FEM metrics and objective score | metrics, contour artifact, objective_score |
| `knowledge` | `graphs/modules/knowledge` | Summarize evidence into memory and inform next optimization | memory update, evidence summary |
| `bo` | `graphs/modules/bo` | Select next candidate using Analysis/Knowledge evidence, numeric BO, and LLM reasoning as a soft prior | `bo_result`, `candidate_ranking`, `next_design_request` |
| `guardian` | `graphs/modules/guardian` | Enforce safety, approval, continue/stop/error decision | guardian decision |

The older top-level `agents/` directory is an implementation/compatibility layer. The active runtime contract is primarily defined by `graphs/modules/*/module.yaml` and `graphs/configs/*.yaml`.

Live GUI agent lists and some report cards/sections are loaded from graph/module/`ui.yaml` metadata through `/api/runtime/agent-manifests`. That API returns a manifest payload containing `agents[]`; `web/static/planning.js` keeps `DEFAULT_LIVE_AGENTS` only as a fallback if the backend manifest request fails. The current descriptor-backed examples are `design`, `equipment`, and `guardian`; they use descriptor cards and selector-backed `report_sections`. Agents without a `ui.yaml` descriptor continue to use the generic renderer. The current generic descriptor renderer handles selector rows/cards/report sections, `mini_bar_chart`, `scatter_plot`, `line_chart`, `table`, `heatmap`, `compound_chart`/`chart_grid`, internal GUI navigation actions, read-only GET API actions, and safe workspace handoff buttons. The backend normalizes chart/action descriptors as presentation contracts with `supported`, `render_mode`, `safe_navigation`, `live_card_runnable`, `handoff_required`, `handoff_workspace`, `execution_scope`, and `blocked_reason`; the frontend applies its own safe rendering filter on top. `ui.renderer.dashboard/report/fallback` is only a presentation-only profile inside the `descriptor`, `generic`, and `<agent>_reference` allowlist; it does not load arbitrary external renderer/plugin code. Only internal `/api/*` actions declared as `kind=api`, `method=GET`, `read_only=true`, and backed by an actual FastAPI GET route are callable as `read_only_api`. POST, confirmation-required, or non-read-only API descriptors can only hand off to a safe operator workspace; physical device actions are not executed by this descriptor path. New draft modules can be created through `/api/modules/templates/{agent|ui-only|bridge}`, but the generated default is `status=draft`, `enabled=false`, and `graph.attached=false`, so it is preview-only until validated, attached, dry-run, and saved.

Live GUI conversation entries are stored in `runs/<active_run_id>/live_planning_transcript.jsonl` and paged through `/api/planning/messages`. Module Management `Load/Unload` is only a management-workspace selection state, not runtime activation. Execution still requires Runtime IDE graph attachment, validation, dry-run, save/versioning, and the live gate. For a module that is not graph-attached yet, the Module Management Runtime IDE button opens `/ide?module=<id>&action=attach` so the Module Library attach target is highlighted.

Custom stages can now run through graph/module validation and the
`Stage._missing_()` compatibility path. To customize stage-specific follow-up
language, provide a `supervisor_policy` descriptor in the payload or
`module_runtime`. The current Module Management typed form covers handler,
LLM, tool, prompt, safety, step edits, and `supervisor_policy` fields for
required outputs, opinion/recommendation templates, response-required statuses,
concern rules, and options. Graph attach/save uses the Runtime IDE main-graph
drag/drop workflow plus validate, dry-run, and Save Version gates.

## 5. Runtime Modes

- `live`: Physical equipment path. Requires a valid selected printer bridge (Bambu Lab X2D by default, Prusa only by explicit selection), LeRobot, Windows bridge, UTM, and safety-gate configuration where applicable.
- `test`: Dry-run and simulated evaluation path. Some operator-selected test paths can still go up to bridge verification or real print.
- `virtual`: No physical device actions; used for experiment API, benchmark, and dry-run validation.

Shared contracts:

- `experiment.evaluate`
- `experiment.benchmark`
- `experiment.queue.status`
- graph dry-run gate
- Guardian approval gate

## 6. Repository Structure

| Path | Purpose |
|---|---|
| `app/` | FastAPI app, routes, runtime controller, API endpoints |
| `web/templates/` | HTML templates |
| `web/static/` | GUI JavaScript, CSS, icons, static assets |
| `graphs/configs/` | LangGraph execution graph YAML files |
| `graphs/modules/` | Stage agent module contracts, handlers, tool allowlists |
| `device_bridges/` | Bambu, Prusa, LeRobot, Windows, UTM bridge layers |
| `experiments/` | Experiment objective/evaluate/benchmark/queue contracts |
| `orchestrator/` | Orchestration and planning flow |
| `backends/` | Ollama/vLLM/Nemoclaw backend integration |
| `gui/` | GUI viewmodel/panel support code |
| `knowledge/` | Memory and retrieval code |
| `learning/` | LeRobot/training helper code |
| `self_evolution/` | Self-Evolution variant/task/validation logic |
| `mcp_tools/` | Tool-call and MCP integration layer |
| `memory/` | Local settings, device connections, graph versions, session memory |
| `runs/` | Run logs, artifacts, printer/robot session records |
| `artifacts/` | STL, gcode, CAE, UI audit outputs |
| `image/` | System/agent diagram prompts, SVG, rendered images |
| `install/` | `atr` CLI install scripts and setup helpers |
| `tests/` | Unit, integration, and UI audit tests |
| `docs/` | Documentation and separated system instruction files |
| `user_files/` | User-provided working files |

## 7. Important Config Files

- [REQUIREMENTS.md](REQUIREMENTS.md): external dependencies, installs, clone/download requirements
- [requirements.txt](requirements.txt): Python packages
- [pyproject.toml](pyproject.toml): project and pytest settings
- [graphs/configs/atr_closed_loop.yaml](graphs/configs/atr_closed_loop.yaml): default closed-loop graph
- `graphs/modules/*/module.yaml`: per-stage execution contract, handler, tool allowlist, and safety settings
- `graphs/modules/*/ui.yaml`: Live GUI card/report section presentation descriptor. It does not grant execution authority
- `memory/printer_fleet.json`: active printer profile selection
- `memory/bambu_connection.json`: Bambu Lab LAN connection data
- `memory/bambu_autoejection.json`: Bambu provider routine and pre/post vision evidence for autoejection handoff
- `memory/manipulation_agent_bridge.json`: Manipulation Agent consumer profile and policy path used by Bambu handoff
- `memory/prusa_connection.json`: PrusaLink connection data for explicit Prusa profile runs
- `memory/bo_workspace_settings.json`: BO workspace saved settings
- `memory/cae_workspace_settings.json`: CAE workspace saved settings
- `memory/lerobot/`: LeRobot profile, calibration, port memory

The current code-exposed page routes, API groups, agent manifest, printer fleet,
and model/API-key state are tracked in
[Current Code Snapshot](docs/runtime/current_code_snapshot.md). If an older
design guideline disagrees with the running code, check this snapshot and
`app/main.py` first.

Important boundary: `/api/bridges` currently returns the normalized graph
metadata bridge registry from `graphs/configs/atr_closed_loop.yaml`. The
payload includes workspace, health/preflight endpoints, standard/custom action
descriptors under `actions[]`, evidence contracts, and health snapshots, and
the same shape is embedded in
`/api/runtime/state.runtime_ide_contract.device_bridges`. Bambu Lab X2D is
managed through `/api/printer/fleet` and `/api/printer/*`, not through that
bridge registry. Therefore Bambu not appearing in `/api/bridges` does not mean
the Bambu printer bridge is inactive.

## 8. Operating Flow

1. Start the server with `atr up`.
2. Check model and device status from Main GUI.
3. Open `/live` and start with test mode.
4. Inspect each stage through Live GUI Report, Backend, Graph, Artifacts, and Timeline tabs.
5. Save required device settings in the 3DP, LeRobot, CAE, BO, and Windows workspaces.
6. Before live execution, confirm Guardian approval and device gates.
7. Review outputs under `runs/`, `artifacts/`, and `memory/`.

## 9. Documentation Entry Points

- [Documentation index](docs/README.md)
- [Complete User Manual](docs/tutorials/user_manual.en.md)
- [Closed loop and page/agent reference](docs/runtime/closed_loop_and_pages_reference.md)
- [Current code/API snapshot](docs/runtime/current_code_snapshot.md)
- [LangGraph runtime](docs/runtime/langgraph_runtime.md)
- [Experiment runtime](docs/runtime/autonomous_experiment_runtime.md)
- [Live GUI guide](docs/gui/gui.md)
- [API key / OpenAI fallback](docs/runtime/api_keys.md)
- [First autonomous run tutorial](docs/tutorials/first_autonomous_run.en.md)
- [GitHub/version-control rules](docs/repository/github_version_control.md)

## 10. Maintenance Rules

- Runtime behavior changes must update related `docs/runtime`, `docs/gui`, `docs/agents`, and `docs/hardware` files.
- Create branches for risky changes only when requested, then validate and merge.
- Keep `main` as the stable runnable baseline.
- System instruction files stay under `docs/system/`; user-facing/collaboration docs stay under the other docs folders.
