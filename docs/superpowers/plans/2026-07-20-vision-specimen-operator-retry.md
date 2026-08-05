# Vision Specimen Operator Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep a healthy run resumable when a fresh Active Cam or UTM frame contains no specimen, provide the operator-placement action in the existing Live GUI cards, and preserve the existing safety behavior for camera/runtime failures.

**Architecture:** Store one normalized `vision_operator_intervention.v1` record in the active run metadata and make it the sole backend/frontend source of truth. Vision creates or resolves that record, LangGraph pauses at the relevant Vision checkpoint instead of advancing or terminating, and a run-scoped controller endpoint re-executes only that checkpoint. UTM non-detection first enters a bounded five-minute automatic recovery phase while the existing rollout remains active; only expiry enters operator wait.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, asyncio, LangGraph runtime, pytest/pytest-asyncio, vanilla JavaScript/CSS, Selenium/browser smoke verification.

## Global Constraints

- Only a valid fresh frame with no specimen may enter operator placement; camera, port, process, and runtime failures keep existing Guardian safety handling.
- Do not change printer execution, autoejection G-code, policy selection, rollout start, or camera ownership rules.
- The exact operator action copy is `Place the specimen into the working area`.
- UTM automatic recovery lasts exactly 300 seconds from the first valid non-detection.
- Active Cam retry repeats Active Cam verification only; UTM operator retry repeats UTM verification only and never restarts Manipulation rollout.
- The intervention is run-scoped, idempotent, refresh-persistent, and cleared by run reset.
- Existing dirty worktree changes are preserved; only files listed in each task are edited for this feature.

---

### Task 1: Run-Scoped Intervention State Contract

**Files:**
- Create: `utils/vision_operator_intervention.py`
- Create: `tests/unit/test_vision_operator_intervention.py`

**Interfaces:**
- Produces: `begin_intervention(metadata: dict, *, run_id: str, checkpoint: str, capture: dict, now: datetime, automatic_recovery: bool = False, timeout_seconds: int = 300, rollout_session_id: str = "") -> dict`
- Produces: `mark_intervention_retrying(metadata: dict, *, checkpoint: str, now: datetime) -> dict`
- Produces: `resolve_intervention(metadata: dict, *, checkpoint: str, now: datetime) -> dict`
- Produces: `intervention_deadline_expired(record: dict, *, now: datetime) -> bool`
- Produces: `active_intervention(metadata: dict) -> dict`

- [ ] **Step 1: Write failing contract tests**

```python
def test_begin_active_cam_wait_preserves_fresh_frame():
    metadata = {}
    record = begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="active_cam_ejection",
        capture={"capture_path": "/tmp/frame.png", "capture_url": "/frame.png", "camera_key": "wrist"},
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    assert record["schema"] == "vision_operator_intervention.v1"
    assert record["status"] == "waiting_for_specimen"
    assert record["capture_path"] == "/tmp/frame.png"
    assert metadata["vision_operator_intervention"] == record

def test_begin_utm_recovery_sets_exact_five_minute_deadline():
    metadata = {}
    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    record = begin_intervention(
        metadata,
        run_id="run-1",
        checkpoint="utm_post_place",
        capture={"capture_path": "/tmp/utm.png", "camera_key": "utm"},
        now=now,
        automatic_recovery=True,
        timeout_seconds=300,
        rollout_session_id="lr-rollout-1",
    )
    assert record["status"] == "retrying"
    assert record["retry_deadline_at"] == (now + timedelta(seconds=300)).isoformat()
    assert record["rollout_stopped"] is False
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `./.venv/bin/pytest -q tests/unit/test_vision_operator_intervention.py`

Expected: collection failure because `utils.vision_operator_intervention` does not exist.

- [ ] **Step 3: Implement the normalized state helpers**

```python
INTERVENTION_SCHEMA = "vision_operator_intervention.v1"
VALID_CHECKPOINTS = {"active_cam_ejection", "utm_post_place"}

def begin_intervention(...):
    deadline = now + timedelta(seconds=timeout_seconds) if automatic_recovery else None
    record = {
        "schema": INTERVENTION_SCHEMA,
        "run_id": run_id,
        "checkpoint": checkpoint,
        "status": "retrying" if automatic_recovery else "waiting_for_specimen",
        "reason": "specimen_not_detected",
        "capture_path": str(capture.get("capture_path") or capture.get("frame_path") or ""),
        "capture_url": str(capture.get("capture_url") or capture.get("frame_url") or ""),
        "camera_key": str(capture.get("camera_key") or ""),
        "requested_at": now.isoformat(),
        "retry_started_at": now.isoformat() if automatic_recovery else "",
        "retry_deadline_at": deadline.isoformat() if deadline else "",
        "retry_count": 0,
        "rollout_session_id": rollout_session_id,
        "rollout_stopped": False,
    }
    metadata["vision_operator_intervention"] = record
    return record
```

Validate checkpoints, copy returned records, increment retry count idempotently, and preserve the first UTM deadline when refreshing its latest frame.

- [ ] **Step 4: Run contract tests and confirm GREEN**

Run: `./.venv/bin/pytest -q tests/unit/test_vision_operator_intervention.py`

Expected: all tests pass.

### Task 2: Vision Agent Classification and Recovery Records

**Files:**
- Modify: `agents/vision_agent.py`
- Modify: `tests/unit/test_vision_agent.py`

**Interfaces:**
- Consumes: Task 1 intervention helpers.
- Produces: Vision result fields `pending_operator_input`, `requires_response`, `vision_operator_intervention`, and `operator_intervention_update` only for valid non-detection.
- Produces: UTM automatic recovery metadata with the original five-minute deadline and latest fresh frame.

- [ ] **Step 1: Add failing Active Cam tests**

Add tests proving that an `ok=True` capture with a valid frame and `specimen_detected=False` returns a successful resumable Vision result, stores `checkpoint=active_cam_ejection`, and does not emit `ACTIVE_ROBOT_CAM_SPECIMEN_POSE_FAILED`. Add a second-attempt test proving that the frame path is replaced while the run/checkpoint remains unchanged.

- [ ] **Step 2: Add failing UTM tests**

Add tests proving that first valid non-detection creates `status=retrying`, a 300-second deadline, and `rollout_stopped=False`; a later measured `ungrasping -> home` refreshes the frame without extending the deadline; detection resolves the record; expiry produces `waiting_for_specimen` only after controlled-stop/port-return evidence is present.

- [ ] **Step 3: Run focused tests and confirm RED**

Run: `./.venv/bin/pytest -q tests/unit/test_vision_agent.py -k 'operator_intervention or utm_recovery'`

Expected: assertions fail because valid non-detection is currently converted into an agent/Guardian failure.

- [ ] **Step 4: Implement minimal Vision classification**

In `_active_cam_ejection_check`, distinguish:

```python
valid_frame = bool(result.get("ok") and capture_path and port_released)
specimen_not_detected = bool(valid_frame and not specimen_detected)
```

When `specimen_not_detected` is true, retain the frame evidence, create/update the intervention, set `pending_operator_input=True`, and avoid assigning a camera/runtime failure code. Leave all capture/port/runtime failure branches unchanged.

For post-place UTM verification, create the automatic-recovery record on first non-detection, retain the first deadline, update only the fresh frame/retry count on later gates, resolve on detection, and expose operator wait only after deadline plus controlled-stop/port-return evidence.

- [ ] **Step 5: Run Vision tests and confirm GREEN**

Run: `./.venv/bin/pytest -q tests/unit/test_vision_agent.py`

Expected: all Vision tests pass.

### Task 3: Guardian and LangGraph Pause Semantics

**Files:**
- Modify: `policies/guardian_gate.py`
- Modify: `orchestrator/langgraph_runtime.py`
- Modify: `tests/unit/test_guardian_gate.py`
- Modify: `tests/unit/test_langgraph_runtime.py`

**Interfaces:**
- Consumes: `vision_operator_intervention.v1` and `pending_operator_input` from Task 2.
- Produces: paused graph state at `Stage.VISION` with no terminal Guardian incident for `specimen_not_detected`.

- [ ] **Step 1: Add failing Guardian distinction tests**

```python
def test_guardian_allows_valid_frame_specimen_non_detection_wait():
    result = guardian_gate(... payload={
        "pending_operator_input": True,
        "vision_operator_intervention": {
            "schema": "vision_operator_intervention.v1",
            "reason": "specimen_not_detected",
            "status": "waiting_for_specimen",
        },
    })
    assert result["decision"] == "allow_with_warning"
```

Retain existing tests that camera capture and port-release failures block execution.

- [ ] **Step 2: Add failing runtime pause test**

Run a Vision result containing the intervention and assert that the graph remains on Vision, marks the status `waiting`, emits `operator_input_required`, and does not call Manipulation or route to Guardian/Complete.

- [ ] **Step 3: Run tests and confirm RED**

Run: `./.venv/bin/pytest -q tests/unit/test_guardian_gate.py tests/unit/test_langgraph_runtime.py -k 'specimen_not_detected or operator_intervention'`

Expected: current post-gate routes to Guardian/Complete or advances to Manipulation.

- [ ] **Step 4: Implement pause semantics after result merge**

Immediately after `_merge_agent_data` and Guardian recording, inspect the normalized intervention. If Vision has an active `waiting_for_specimen` or UTM `retrying` record, set the agent status to `waiting`, keep `state.stage = Stage.VISION`, set `state.is_paused = True`, emit one `operator_input_required`/`vision_recovery_waiting` event, and return before transition selection. Do not apply this branch to missing/invalid frames or port/runtime failure codes.

- [ ] **Step 5: Run Guardian/runtime tests and confirm GREEN**

Run: `./.venv/bin/pytest -q tests/unit/test_guardian_gate.py tests/unit/test_langgraph_runtime.py`

Expected: all tests pass.

### Task 4: Run-Scoped Vision Retry API

**Files:**
- Modify: `app/controller.py`
- Modify: `app/main.py`
- Create: `tests/unit/test_vision_specimen_retry_api.py`

**Interfaces:**
- Produces: `Controller.retry_vision_specimen_placement(*, run_id: str, checkpoint: str) -> dict[str, object]`.
- Produces: `POST /api/runs/{run_id}/vision/specimen-placement-retry` with body `{"checkpoint": "active_cam_ejection"}` or `{"checkpoint": "utm_post_place"}`.

- [ ] **Step 1: Add failing endpoint tests**

Test mismatched run ID (404), mismatched checkpoint (409), duplicate click while status is `retrying` (200 idempotent), Active Cam retry invoking only Vision, and UTM retry invoking only post-place Vision without restarting rollout.

- [ ] **Step 2: Run endpoint tests and confirm RED**

Run: `./.venv/bin/pytest -q tests/unit/test_vision_specimen_retry_api.py`

Expected: endpoint is 404/not registered and controller method is absent.

- [ ] **Step 3: Implement controller retry with a per-run lock**

Use an `asyncio.Lock` keyed by run ID. Validate the current state record, return the current compact status if already retrying, mark the record retrying, execute the existing Vision stage with checkpoint context, merge only Vision output into the current run, and resume the paused graph only when the intervention resolves. For UTM operator retry, assert the rollout is already stopped and do not call Manipulation start/resume.

- [ ] **Step 4: Add FastAPI request model and route**

```python
class VisionSpecimenPlacementRetryRequest(BaseModel):
    checkpoint: Literal["active_cam_ejection", "utm_post_place"]

@app.post("/api/runs/{run_id}/vision/specimen-placement-retry")
async def retry_vision_specimen_placement(...):
    _require_current_run(run_id)
    return await controller.retry_vision_specimen_placement(
        run_id=run_id,
        checkpoint=req.checkpoint,
    )
```

- [ ] **Step 5: Run endpoint tests and confirm GREEN**

Run: `./.venv/bin/pytest -q tests/unit/test_vision_specimen_retry_api.py`

Expected: all tests pass.

### Task 5: Existing-Card Operator UI and Countdown

**Files:**
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Modify: `web/templates/planning.html`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`
- Modify: `tests/unit/test_utm_runtime_frontend_static.py`

**Interfaces:**
- Consumes: `state.run_metadata.vision_operator_intervention` and Task 4 endpoint.
- Produces: `renderVisionSpecimenIntervention(record, checkpoint) -> string` and delegated click action `data-vision-specimen-retry`.

- [ ] **Step 1: Add failing static/layout tests**

Assert the bundle source contains the exact button copy, endpoint path, `active_cam_ejection`, `utm_post_place`, pending disabled copy `Checking specimen...`, and countdown rendering. Assert both existing Vision cards call the shared renderer and no new modal/page is introduced.

- [ ] **Step 2: Run frontend tests and confirm RED**

Run: `./.venv/bin/pytest -q tests/integration/test_live_gui_runtime_layout.py tests/unit/test_utm_runtime_frontend_static.py`

Expected: assertions fail because the intervention controls do not exist.

- [ ] **Step 3: Implement shared renderer and delegated action**

Render the stored fresh frame in the card's existing image area. For `waiting_for_specimen`, append a full-width squared dark-red button and status line. For UTM `retrying`, render remaining time from `retry_deadline_at` and no button. The delegated click handler disables only the clicked button, posts `{checkpoint}`, refreshes runtime state, and restores the button on another non-detection or request failure.

- [ ] **Step 4: Add scoped styles and cache-bust the served asset**

Use `.vision-specimen-placement-action` styles scoped to Vision cards; do not alter E-STOP, chat, report, or global button styles. Update the `planning.js` query version in `planning.html` once.

- [ ] **Step 5: Run frontend tests and confirm GREEN**

Run: `./.venv/bin/pytest -q tests/integration/test_live_gui_runtime_layout.py tests/unit/test_utm_runtime_frontend_static.py`

Expected: all tests pass.

### Task 6: Regression and Top-Level Live GUI Verification

**Files:**
- Modify: `docs/architecture/live_gui_runtime_guide.md` if present, otherwise the existing Live GUI runtime guide discovered with `rg --files docs | rg 'live.*gui|runtime.*guide'`.
- Create: `runs/verification/vision_specimen_operator_retry/verification.json`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: automated and browser evidence that the full top-level route works without a backend-only shortcut.

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
./.venv/bin/pytest -q \
  tests/unit/test_vision_operator_intervention.py \
  tests/unit/test_vision_agent.py \
  tests/unit/test_guardian_gate.py \
  tests/unit/test_langgraph_runtime.py \
  tests/unit/test_vision_specimen_retry_api.py \
  tests/integration/test_live_gui_runtime_layout.py \
  tests/unit/test_utm_runtime_frontend_static.py
```

Expected: all tests pass.

- [ ] **Step 2: Verify the normal `/live` route in a browser**

Start or reuse the existing GUI server without interrupting external training/rollout processes. Through `/live`, inject a test run using the normal chat/UI path and verify: Active Cam fresh non-detection frame remains visible; red action button appears; click shows `Checking specimen...`; a detected retry advances; UTM automatic recovery shows a countdown without a button; expired UTM wait shows the same action; refresh preserves the frame/state.

- [ ] **Step 3: Verify safety separation**

Exercise synthetic camera capture failure and camera-port-release failure through the normal test route. Confirm neither exposes the placement button and both retain existing Guardian error presentation.

- [ ] **Step 4: Save compact verification evidence and update docs**

Record run ID, tested checkpoints, endpoint statuses, browser assertions, test commands, and timestamps in `verification.json`. Document operator behavior, the 300-second UTM recovery window, and the distinction between non-detection and hardware failure.

- [ ] **Step 5: Review the diff without touching unrelated changes**

Run: `git diff --check && git diff --stat && git status --short`

Expected: no whitespace errors; only planned feature files plus pre-existing dirty files are present.
