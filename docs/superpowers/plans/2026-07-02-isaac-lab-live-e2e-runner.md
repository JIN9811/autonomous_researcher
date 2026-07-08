# Isaac Lab Live E2E Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GUI-driven live Isaac Lab Mimic + IL E2E runner with a 10 second x 3 episode preset, visual/headless checkbox behavior, job status, stop support, and artifact verification.

**Architecture:** Keep recording and teleoperation untouched. Add a dedicated live E2E job kind in `LeRobotBridge` that launches `scripts/lerobot_isaac_lab_e2e_smoke.py --mode live` as a tracked subprocess, while the GUI sends a clear preset payload and polls status.

**Tech Stack:** FastAPI, Pydantic, LeRobot bridge, Isaac Sim Python, Isaac Lab Mimic, robomimic, HDF5, vanilla HTML/JS, pytest.

---

### Task 1: Document and Lock the Request

**Files:**
- Create: `docs/superpowers/specs/2026-07-02-isaac-lab-live-e2e-runner-design.md`
- Create: `docs/superpowers/plans/2026-07-02-isaac-lab-live-e2e-runner.md`

- [ ] **Step 1: Write design spec**

Save the approved scope: live 10s x 3 check, visual checkbox behavior, no teleop/recording changes, artifact verification.

- [ ] **Step 2: Write implementation plan**

Save this plan with concrete task boundaries.

- [ ] **Step 3: Self-review**

Check that the spec and plan do not claim the live Isaac Lab workflow already passes before verification.

### Task 2: Add Failing Tests for Live E2E Command and Artifact Checks

**Files:**
- Modify: `tests/unit/test_lerobot_isaac_lab_e2e_contract.py`
- Modify: `tests/unit/test_lerobot_gui_static.py`

- [ ] **Step 1: Add test for live E2E command construction**

Add a test that builds a live command and asserts:

```python
assert "--mode" in command
assert command[command.index("--mode") + 1] == "live"
assert "--trials" in command
assert command[command.index("--trials") + 1] == "3"
assert "--episodes" in command
assert command[command.index("--episodes") + 1] == "3"
assert "--episode-s" in command
assert command[command.index("--episode-s") + 1] == "10"
assert "--no-create-fixture" in command
```

- [ ] **Step 2: Add test for visual checkbox command behavior**

Assert that visual mode is represented in payload/command and that Mimic runner commands remove `--headless`, include `--viz kit`, and keep `--enable_cameras` reserved for explicit camera-sensor runs.

- [ ] **Step 3: Add GUI static test**

Assert these strings exist:

```text
isaac-synthetic-run-live-e2e-check
/api/lerobot/isaac-lab/run-live-e2e-check
/api/lerobot/isaac-lab/live-e2e/status
isaac_lab_visualize_generation: checkboxValue(isaacLabVisualizeGenerationInput)
```

- [ ] **Step 4: Run tests and verify they fail for missing implementation**

Run:

```bash
/home/jin/miniconda3/envs/lerobot/bin/python -m pytest tests/unit/test_lerobot_isaac_lab_e2e_contract.py -q
python3 -m pytest tests/unit/test_lerobot_gui_static.py -q
```

Expected: tests fail because the live E2E helper/button/API does not exist yet.

### Task 3: Implement Backend Live E2E Runner

**Files:**
- Modify: `mcp_tools/lerobot_schemas.py`
- Modify: `device_bridges/lerobot_bridge.py`
- Modify: `app/main.py`

- [ ] **Step 1: Add request fields**

Add bounded fields if missing:

```python
e2e_stage_timeout_s: float = Field(default=1800.0, ge=30.0, le=7200.0)
```

- [ ] **Step 2: Add bridge command builder**

Add a method that returns the exact live E2E command for tests and launch:

```python
def _isaac_lab_live_e2e_command(self, request: IsaacLabSyntheticRequest) -> list[str]:
    ...
```

- [ ] **Step 3: Add bridge launch/status/stop methods**

Add:

```python
def isaac_lab_run_live_e2e_check(...)
def isaac_lab_live_e2e_status(...)
def isaac_lab_live_e2e_stop(...)
```

Use a runner kind of `live_e2e`.

- [ ] **Step 4: Add artifact checker**

Add an artifact checker that reports present/missing for HDF5, annotated HDF5, Mimic generated dataset, Mimic successes, and IL output dir.

- [ ] **Step 5: Add FastAPI routes**

Add:

```python
POST /api/lerobot/isaac-lab/run-live-e2e-check
POST /api/lerobot/isaac-lab/live-e2e/status
POST /api/lerobot/isaac-lab/live-e2e/stop
```

- [ ] **Step 6: Run backend tests**

Run the E2E contract tests and py_compile.

### Task 4: Implement GUI Controls and Polling

**Files:**
- Modify: `web/templates/lerobot.html`
- Modify: `web/static/lerobot.js`
- Test: `tests/unit/test_lerobot_gui_static.py`

- [ ] **Step 1: Add live check controls**

Add a compact row near the E2E controls:

```html
<button id="isaac-synthetic-run-live-e2e-check" class="btn primary">Run 10s x 3 Live Check</button>
<button id="isaac-synthetic-live-e2e-status" class="btn">Live Check Status</button>
<button id="isaac-synthetic-live-e2e-stop" class="btn danger">Stop Live Check</button>
```

- [ ] **Step 2: Add JS payload preset**

Add a function that merges:

```javascript
{
  mode: "live",
  runtime_mode: "live",
  dry_run: false,
  e2e_create_fixture: false,
  e2e_episodes: 3,
  e2e_episode_s: 10,
  e2e_fps: 15,
  mimic_trials: 3,
  enable_mimic: true,
  enable_hdf5_export: true,
  enable_replicator: false,
  isaac_lab_visualize_generation: checkboxValue(isaacLabVisualizeGenerationInput)
}
```

- [ ] **Step 3: Bind buttons**

Start button posts to `/run-live-e2e-check`. Status and stop buttons call their matching endpoints.

- [ ] **Step 4: Poll while running**

If returned status is `RUNNING`, poll `/live-e2e/status` until terminal.

- [ ] **Step 5: Run GUI tests and JS syntax check**

Run:

```bash
python3 -m pytest tests/unit/test_lerobot_gui_static.py -q
node --check web/static/lerobot.js
```

### Task 5: Live Verification

**Files:**
- No source edits unless the live run reveals a concrete bug.

- [ ] **Step 1: Find selected or recent dataset**

Use GUI status or recent dataset paths. Do not fabricate fixture data for the live check.

- [ ] **Step 2: Run 10s x 3 live check**

Run via GUI if server/browser is active, otherwise call the API-equivalent bridge/script command directly.

- [ ] **Step 3: Inspect job status and artifacts**

Check:

```text
hdf5/exported_successful_real_episodes.hdf5
hdf5/source_real_success_annotated.hdf5
mimic/generated_dataset.hdf5
mimic/successes.jsonl
il/robomimic
```

- [ ] **Step 4: Report actual status**

If Isaac Lab fails, report the exact command, return code, log path, and first actionable error. Do not claim the live pipeline works unless the artifacts exist.
