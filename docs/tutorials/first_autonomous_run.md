# First Autonomous Run

This tutorial validates the end-to-end system without requiring immediate
hardware writes.

## Goal

Run one autonomous specimen workflow through:

`Main GUI -> Live GUI -> Orchestrator -> Design Agent -> Specimen Making Agent -> Autonomous Experiment Runtime -> Printer Bridge -> Guardian`

## Preconditions

- Repository installed at `/home/jin/autonomous_researcher`.
- Python environment installed with `pip install -r requirements.txt`.
- `atr` launcher installed with `bash install/install_cli.sh`.
- Inference model loaded manually from the GUI or CLI.
- For live PrusaLink use, `memory/prusa_connection.json` contains the current
  host and auth fields.
- For test-only validation, real hardware is not required.

## Start Server

```bash
atr up
```

Open:

```text
http://localhost:7860
```

To stop:

```bash
atr down
```

## Test Run From Main GUI

1. Confirm inference backend is `NemoClaw / vLLM` or the intended backend.
2. Load the required model manually.
3. Select `Test` mode.
4. Press `Start`.
5. Watch the event stream until `complete` or a structured error appears.

Expected behavior:

- Design Agent creates a gyroid/FDM-compatible specimen candidate.
- Specimen Making Agent generates STL/handoff artifacts.
- `experiment.evaluate` wraps printer preparation.
- `printer.prepare` returns a queued result with `job_id`.
- Guardian validates the result.

## Live GUI Test-Mode Print Path

Open Live GUI and type one of the supported phrases:

```text
테스트 모드, 가상 브릿지
테스트 모드, 설치 프린터
테스트 모드, 실제 출력
```

Expected routing:

- `가상 브릿지`: virtual PrusaLink path after slicing.
- `설치 프린터`: real PrusaLink communication check with live gates.
- `실제 출력`: test-generated specimen can be physically uploaded/started if
  live gates and connection info allow it.

## Live Run

In Live GUI, discuss the specimen requirements with the orchestrator. When the
design inputs are complete, send the configured execution trigger such as:

```text
실험 수행
```

Expected behavior:

- The orchestrator announces handoff.
- Design Agent produces the candidate.
- Specimen Making Agent shows slicer and printer bridge steps.
- The unified experiment result appears under `experiment_evaluation`.
- Device job metadata is attached to the printer result.

## Verify Queue State

The queue can be checked through the tool layer:

```python
ctx.tools.call("experiment.queue.status", {})
```

For API/debugging, inspect recent logs under:

```text
runs/<run-id>/
```

## Recovery Rules

- If the model is not loaded, load it manually and retry. Server startup does
  not auto-prewarm vLLM.
- If PrusaLink connection info is missing, edit `memory/prusa_connection.json`
  and retry from the same specimen step.
- If a hardware job is already active, wait for completion or use the relevant
  device stop/clear control.
- Do not bypass live gates in code to force physical action.
