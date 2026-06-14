# First Autonomous Run (English)

This tutorial validates the whole cycle from operator message to run completion without skipping safety gates.

## Scope

- Covers: Live/bo loop entry, test mode, specimen generation, queue-based hardware calls, and trace verification.
- Hardware required: only when you intentionally execute live print/robot actions.

## 1) Pre-Check

Before the first run, complete each item:

- `git status` is clean (or you know intentional pending changes)
- Virtual environment is activated
- Dependencies installed: `pip install -r requirements.txt`
- Launcher is installed: `bash install/install_cli.sh`
- Required ports are reachable: server uses 7860
- Optional: correct model and hardware profile exists

## 2) Start System

```bash
atr up
```

Open:

- `http://localhost:7860`
- `http://localhost:7860/live`

Stop later:

```bash
atr down
```

## 3) Start in Test Mode (Recommended First)

1. Open Live GUI.
2. Ensure backend and model are loaded.
3. In main control or Live GUI, select `Test` mode.
4. Start the run.
5. Confirm:
   - The run state becomes active.
   - Event stream emits `run.started` and stage transitions.
   - `experiment.evaluate` and `printer.prepare` produce structured output (if printer stage is involved).
   - `job_id` appears when queued hardware tools are used.

If any stage fails:

- open the timeline for failed node
- inspect artifact and context in Runtime IDE or event payload

## 4) Test-mode Print Paths

In Live GUI chat, you can request:

- `테스트 모드, 가상 브릿지`
- `테스트 모드, 설치 프린터`
- `테스트 모드, 실제 출력`

Routing behavior:

- 가상 브릿지: slicing + virtual path validation
- 설치 프린터: active printer profile connection check + live gate checks. Bambu X2D is the default; Prusa runs only after explicit profile selection.
- 실제 출력: slice/upload/start path when live gate passes

If live gate blocks, the run should stop before hardware start and show reason code.

## 5) Run in Live Mode

1. Send a clear execution goal such as:

```text
실험 수행
```

2. Wait for orchestrator handoff line.
3. Confirm Design and Specimen stages create valid candidate + artifacts.
4. Confirm downstream stages continue according to graph transitions.
5. Inspect BO/CAE/analysis artifacts in run artifact panel.

## 6) Verify Artifact Lineage and Trace

Open Runtime IDE: `http://localhost:7860/ide`

Minimum checks:

1. Select the latest run.
2. Confirm event order and `run.created -> run.started -> node.started/completed`.
3. Open node-level error details when anything fails.
4. Open Artifact Lineage for the run and confirm producer + artifact type.
5. Confirm trace can be returned to source node from artifact preview.

## 7) Queue and Recovery

Check queue status from tool layer:

```python
ctx.tools.call("experiment.queue.status", {})
```

Practical recovery checklist:

- Missing connection info: update `memory/prusa_connection.json` and retry specimen stage.
- Model context issue: reload model and re-run.
- Stale run state: refresh, then check SSE status in Live header.
- Device busy: wait for existing job completion or use explicit stop/restart controls.

## 8) Completion

A successful first run should yield:

- Stable planning trace
- Stage transitions according to graph config
- At least one artifact per stage output (where applicable)
- Queue metadata in hardware-involved operations
- Completed `Guardian` terminal state

## 9) Additional CLI/GUI Cross-check

Run:

```bash
atr model list
atr status
atr events recent
atr modules
```

Main GUI and CLI should return consistent high-level states.
