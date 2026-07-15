# Active Cam Run Artifact Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist each successful loop Active Cam frame as a normal run artifact and keep it visible until the next Active Cam attempt succeeds or fails.

**Architecture:** Vision Agent copies the transient camera frame into its existing observation evidence directory and emits an explicit artifact-state update. A shared metadata merger applies that update consistently in both LangGraph and manual Live GUI execution paths, while no-update handoffs preserve the current display pointer. The Live GUI renders the canonical run artifact and suppresses the previous image after an explicit failed attempt.

**Tech Stack:** Python 3.12, pathlib/shutil, FastAPI run artifact route, LangGraph runtime metadata, vanilla JavaScript Live GUI, pytest.

## Global Constraints

- Store frames under the existing `runs/<run_id>/vision/<observation_id>/` evidence hierarchy.
- Treat the frame as a normal run artifact; do not create a second Active Cam storage system.
- Keep the previous successful frame while a new capture is running.
- Replace the frame only after a successful capture.
- Clear the current display pointer after a failed Active Cam attempt.
- Never delete earlier immutable run artifact files when a later attempt fails.
- Do not use frontend Base64/session-only caching as the persistence mechanism.

---

### Task 1: Persist Active Cam frames in Vision observation artifacts

**Files:**
- Modify: `agents/vision_agent.py:20-55,400-475,916-985,1316-1585`
- Test: `tests/unit/test_vision_agent.py`

**Interfaces:**
- Consumes: `OrchestratorState`, observation ID, and `active_cam_ejection_check.capture_path` from `lerobot.active_robot_cam.capture`.
- Produces: `VisionAgent._persist_active_cam_run_artifact(...) -> dict[str, Any]` and top-level `active_cam_artifact_update` in `AgentResult.data`.

- [ ] **Step 1: Write failing persistence tests**

Add tests that invoke the new helper with a real temporary source image and a missing source image:

```python
def test_active_cam_capture_is_copied_into_current_vision_run_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    source = tmp_path / "camera-runtime" / "frame.jpg"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"active-cam-frame")
    output = tmp_path / "runs" / state.run_id / "vision" / "frame-1-vision"
    monkeypatch.setattr(
        VisionAgent,
        "_artifact_dir",
        classmethod(lambda cls, runtime_state, observation_id: output),
    )

    artifact = VisionAgent()._persist_active_cam_run_artifact(
        state=state,
        observation_id="frame-1-vision",
        active_check={
            "status": "confirmed",
            "capture_path": str(source),
            "camera_key": "wrist",
            "frame_width": 640,
            "frame_height": 480,
            "specimen_id": "specimen-1",
        },
    )

    assert artifact["status"] == "stored"
    assert Path(artifact["path"]).is_file()
    assert Path(artifact["path"]).parent == output
    assert Path(artifact["path"]).read_bytes() == b"active-cam-frame"
    assert artifact["url"].startswith(f"/api/runs/{state.run_id}/artifact-file/vision/")


def test_active_cam_missing_source_returns_failed_update_without_deleting_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    output = tmp_path / "runs" / state.run_id / "vision" / "frame-2-vision"
    prior = output.parent / "frame-1-vision" / "active_cam_capture_prior.jpg"
    prior.parent.mkdir(parents=True)
    prior.write_bytes(b"prior")
    monkeypatch.setattr(
        VisionAgent,
        "_artifact_dir",
        classmethod(lambda cls, runtime_state, observation_id: output),
    )

    artifact = VisionAgent()._persist_active_cam_run_artifact(
        state=state,
        observation_id="frame-2-vision",
        active_check={"status": "blocked", "capture_path": str(tmp_path / "missing.jpg")},
    )

    assert artifact["status"] == "failed"
    assert artifact.get("path", "") == ""
    assert prior.read_bytes() == b"prior"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_vision_agent.py::test_active_cam_capture_is_copied_into_current_vision_run_artifacts \
  tests/unit/test_vision_agent.py::test_active_cam_missing_source_returns_failed_update_without_deleting_history
```

Expected: FAIL because `_persist_active_cam_run_artifact` does not exist.

- [ ] **Step 3: Implement the run-local artifact helper**

Add `shutil` and URL quoting imports, then implement:

```python
@classmethod
def _persist_active_cam_run_artifact(
    cls,
    *,
    state: OrchestratorState,
    observation_id: str,
    active_check: dict[str, Any],
) -> dict[str, Any]:
    captured_at = cls._now().isoformat()
    source_text = str(active_check.get("capture_path") or "").strip()
    source = Path(source_text).expanduser() if source_text else None
    if not source or not source.is_file():
        return {
            "schema": "active_cam_run_artifact.v1",
            "status": "failed",
            "failure_code": "ACTIVE_CAM_ARTIFACT_SOURCE_MISSING",
            "path": "",
            "url": "",
            "source_path": source_text,
            "captured_at": captured_at,
        }
    suffix = source.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg"}:
        return {
            "schema": "active_cam_run_artifact.v1",
            "status": "failed",
            "failure_code": "ACTIVE_CAM_ARTIFACT_FORMAT_UNSUPPORTED",
            "path": "",
            "url": "",
            "source_path": str(source),
            "captured_at": captured_at,
        }
    output_dir = cls._artifact_dir(state, observation_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = cls._now().strftime("%Y%m%dT%H%M%S%fZ")
    target = output_dir / f"active_cam_capture_{stamp}{suffix}"
    try:
        shutil.copy2(source, target)
    except OSError as exc:
        return {
            "schema": "active_cam_run_artifact.v1",
            "status": "failed",
            "failure_code": "ACTIVE_CAM_ARTIFACT_COPY_FAILED",
            "message": f"{exc.__class__.__name__}: {exc}",
            "path": "",
            "url": "",
            "source_path": str(source),
            "captured_at": captured_at,
        }
    run_dir = cls._repo_root() / "runs" / state.run_id
    relative = target.resolve().relative_to(run_dir.resolve()).as_posix()
    return {
        "schema": "active_cam_run_artifact.v1",
        "status": "stored",
        "path": str(target.resolve()),
        "url": f"/api/runs/{quote(state.run_id, safe='')}/artifact-file/{quote(relative, safe='/')}",
        "relative_path": relative,
        "source_path": str(source.resolve()),
        "run_id": state.run_id,
        "observation_id": observation_id,
        "loop_index": int(state.loop_count or 0),
        "specimen_id": str(active_check.get("specimen_id") or ""),
        "camera_key": str(active_check.get("camera_key") or ""),
        "frame_width": active_check.get("frame_width"),
        "frame_height": active_check.get("frame_height"),
        "captured_at": captured_at,
    }
```

Create `output_dir` in the test monkeypatch before deriving the run-relative URL, or derive `run_dir` from `output_dir.parents[2]` only in the test override. Production must still enforce that the target resolves inside `runs/<run_id>`.

- [ ] **Step 4: Integrate the helper into the Vision payload**

In `_transfer_observation`, after `observation_id` is known, process only an explicit Active Cam attempt:

```python
active_cam_payload = capture.get("active_cam_ejection_check") if isinstance(capture.get("active_cam_ejection_check"), dict) else {}
active_cam_artifact_update: dict[str, Any] = {}
if active_cam_payload:
    active_cam_artifact_update = self._persist_active_cam_run_artifact(
        state=state,
        observation_id=observation_id,
        active_check=active_cam_payload,
    )
    active_cam_payload = dict(active_cam_payload)
    if active_cam_artifact_update.get("status") == "stored":
        active_cam_payload["capture_path"] = active_cam_artifact_update["path"]
        active_cam_payload["capture_url"] = active_cam_artifact_update["url"]
        active_cam_payload["run_artifact"] = dict(active_cam_artifact_update)
    else:
        active_cam_payload.update(
            {
                "status": "blocked",
                "spc_autoejection_confirmed": False,
                "capture_path": "",
                "capture_url": "",
                "artifact_failure_code": active_cam_artifact_update.get("failure_code", "ACTIVE_CAM_ARTIFACT_FAILED"),
            }
        )
    capture["active_cam_ejection_check"] = active_cam_payload
```

Add the descriptor to `vision_report["artifacts"]`, evidence refs, and the top-level payload only when an Active Cam attempt occurred:

```python
if active_cam_artifact_update:
    artifacts["active_cam_run_artifact"] = dict(active_cam_artifact_update)
    payload["active_cam_artifact_update"] = dict(active_cam_artifact_update)
```

- [ ] **Step 5: Run Vision tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_vision_agent.py
```

Expected: all Vision Agent tests pass and successful Active Cam reports reference a `runs/<run_id>/vision/...` image.

- [ ] **Step 6: Commit Task 1**

```bash
git add agents/vision_agent.py tests/unit/test_vision_agent.py
git commit -m "feat: persist active cam frames as run artifacts"
```

---

### Task 2: Preserve or clear the current Active Cam display pointer across runtime paths

**Files:**
- Create: `utils/active_cam_artifact.py`
- Create: `tests/unit/test_active_cam_artifact.py`
- Modify: `orchestrator/langgraph_runtime.py:1280-1345`
- Modify: `app/controller.py:2885-2985,6580-6660`
- Test: `tests/unit/test_langgraph_runtime.py`
- Test: `tests/unit/test_controller_planning.py`

**Interfaces:**
- Consumes: top-level `active_cam_artifact_update` from Vision Agent data.
- Produces: canonical `run_metadata["latest_active_cam_artifact"]` or removes it after an explicit failed update.

- [ ] **Step 1: Write failing metadata lifecycle tests**

Create `tests/unit/test_active_cam_artifact.py`:

```python
from utils.active_cam_artifact import apply_active_cam_artifact_update


def test_no_update_preserves_latest_active_cam_artifact() -> None:
    latest = {"schema": "active_cam_run_artifact.v1", "status": "stored", "path": "/runs/frame-1.jpg"}
    metadata = {"latest_active_cam_artifact": dict(latest)}

    changed = apply_active_cam_artifact_update(metadata, None)

    assert changed is False
    assert metadata["latest_active_cam_artifact"] == latest


def test_stored_update_replaces_latest_active_cam_artifact() -> None:
    metadata = {"latest_active_cam_artifact": {"status": "stored", "path": "/runs/old.jpg"}}
    update = {"schema": "active_cam_run_artifact.v1", "status": "stored", "path": "/runs/new.jpg"}

    changed = apply_active_cam_artifact_update(metadata, update)

    assert changed is True
    assert metadata["latest_active_cam_artifact"] == update


def test_failed_update_clears_pointer_but_not_artifact_files(tmp_path: Path) -> None:
    prior = tmp_path / "prior.jpg"
    prior.write_bytes(b"prior")
    metadata = {"latest_active_cam_artifact": {"status": "stored", "path": str(prior)}}

    changed = apply_active_cam_artifact_update(
        metadata,
        {"schema": "active_cam_run_artifact.v1", "status": "failed", "failure_code": "CAPTURE_FAILED"},
    )

    assert changed is True
    assert "latest_active_cam_artifact" not in metadata
    assert prior.read_bytes() == b"prior"
```

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_active_cam_artifact.py
```

Expected: FAIL because `utils.active_cam_artifact` does not exist.

- [ ] **Step 3: Implement the shared metadata merger**

Create `utils/active_cam_artifact.py`:

```python
from __future__ import annotations

from typing import Any


def apply_active_cam_artifact_update(metadata: dict[str, Any], update: Any) -> bool:
    """Apply one explicit Active Cam attempt without disturbing no-update handoffs."""
    if not isinstance(update, dict):
        return False
    status = str(update.get("status") or "").strip().lower()
    if status == "stored" and update.get("path"):
        metadata["latest_active_cam_artifact"] = dict(update)
        return True
    if status in {"failed", "blocked", "error"}:
        metadata.pop("latest_active_cam_artifact", None)
        return True
    return False
```

- [ ] **Step 4: Wire both merge paths and metadata compaction**

In `orchestrator/langgraph_runtime.py::_merge_agent_data`:

```python
active_cam_update = data.get("active_cam_artifact_update")
if isinstance(active_cam_update, dict):
    apply_active_cam_artifact_update(
        self._state.run_metadata,
        compact_runtime_payload(active_cam_update),
    )
```

In `app/controller.py::_merge_planning_agent_data`:

```python
active_cam_update = data.get("active_cam_artifact_update")
if isinstance(active_cam_update, dict):
    apply_active_cam_artifact_update(self._state.run_metadata, active_cam_update)
```

Add `latest_active_cam_artifact` to `_compact_planning_run_metadata.allow_keys` so polling and page refresh preserve it.

- [ ] **Step 5: Add execution-path regression tests**

In both controller and LangGraph tests, apply a stored update, then merge unrelated Manipulation data, then apply a failed update:

```python
runtime._merge_agent_data(Stage.VISION, {"active_cam_artifact_update": stored})
runtime._merge_agent_data(Stage.MANIPULATION, {"manipulation_report": {"status": "running"}})
assert runtime._state.run_metadata["latest_active_cam_artifact"] == stored

runtime._merge_agent_data(Stage.VISION, {"active_cam_artifact_update": {"status": "failed"}})
assert "latest_active_cam_artifact" not in runtime._state.run_metadata
```

Use `_merge_planning_agent_data` with the same sequence for the manual Live GUI path.

- [ ] **Step 6: Run runtime merge tests and verify GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_active_cam_artifact.py \
  tests/unit/test_langgraph_runtime.py -k active_cam \
  tests/unit/test_controller_planning.py -k active_cam
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add \
  utils/active_cam_artifact.py \
  app/controller.py \
  orchestrator/langgraph_runtime.py \
  tests/unit/test_active_cam_artifact.py \
  tests/unit/test_langgraph_runtime.py \
  tests/unit/test_controller_planning.py
git commit -m "feat: retain active cam artifact state across handoffs"
```

---

### Task 3: Render the canonical artifact until replacement or failure

**Files:**
- Modify: `web/static/planning.js:4539-4570,13490-13560`
- Modify: `web/templates/planning.html:35-45`
- Test: `tests/unit/test_utm_runtime_frontend_static.py`

**Interfaces:**
- Consumes: `state.run_metadata.latest_active_cam_artifact` and current `vision_agent_report.active_cam_ejection_check`.
- Produces: Active Cam card image URL and explicit no-image failure rendering.

- [ ] **Step 1: Write failing frontend contract assertions**

Extend `test_live_gui_js_renders_utm_runtime_device_card`:

```python
assert "function latestActiveCamArtifact(report)" in js
assert 'metadata.latest_active_cam_artifact' in js
assert "function renderVisionActiveCamEjectionCheck(screenReport, persistedArtifact)" in js
assert 'const captureUrl = failed ? "" : persistedArtifact.url || active.capture_url' in js
assert "renderVisionActiveCamEjectionCheck(screenReport, latestActiveCamArtifact(report))" in js
```

- [ ] **Step 2: Run frontend test and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_utm_runtime_frontend_static.py::test_live_gui_js_renders_utm_runtime_device_card
```

Expected: FAIL because the persisted artifact helper and renderer argument do not exist.

- [ ] **Step 3: Implement metadata lookup and failure-aware rendering**

Add:

```javascript
function latestActiveCamArtifact(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && metadata !== null && typeof state.run_metadata === "object"
    ? state.run_metadata : {};
  const artifact = metadata.latest_active_cam_artifact;
  return artifact && typeof artifact === "object" ? artifact : {};
}
```

Use a corrected local variable expression in production:

```javascript
function latestActiveCamArtifact(report) {
  const state = report && report.state ? report.state : {};
  const metadata = state && state.run_metadata && typeof state.run_metadata === "object"
    ? state.run_metadata : {};
  const artifact = metadata.latest_active_cam_artifact;
  return artifact && typeof artifact === "object" ? artifact : {};
}
```

Change the card renderer:

```javascript
function renderVisionActiveCamEjectionCheck(screenReport, persistedArtifact = {}) {
  const active = screenReport.active_cam_ejection_check || {};
  const status = active.status || (persistedArtifact.path ? "confirmed" : "waiting");
  const failed = /failed|blocked|error/i.test(String(status));
  const capturePath = failed ? "" : persistedArtifact.path || active.capture_path || "";
  const captureUrl = failed ? "" : persistedArtifact.url || active.capture_url
    || (capturePath ? `/api/lerobot/visualization/file?path=${encodeURIComponent(capturePath)}` : "");
  // Keep the existing metrics/details markup and use capturePath/captureUrl above.
}
```

Call it with `latestActiveCamArtifact(report)`. Do not append a timestamp query because each stored artifact path is immutable and unique.

- [ ] **Step 4: Bump the Live GUI asset version**

Append one new version token in `web/templates/planning.html`:

```html
/static/styles.css?v=20260713-activecam-run-artifact-1
/static/planning.js?v=20260713-activecam-run-artifact-1
```

- [ ] **Step 5: Run frontend tests and JavaScript syntax verification**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_utm_runtime_frontend_static.py
node --check web/static/planning.js
```

Expected: all tests pass and Node reports no syntax errors.

- [ ] **Step 6: Commit Task 3**

```bash
git add web/static/planning.js web/templates/planning.html tests/unit/test_utm_runtime_frontend_static.py
git commit -m "fix: retain active cam evidence in live gui"
```

---

### Task 4: Document and verify the complete run-artifact lifecycle

**Files:**
- Modify: `docs/agents/vision_pickup_observation_runtime_guideline.txt`
- Modify: `docs/runtime/closed_loop_and_pages_reference.md`
- Verify: all files from Tasks 1-3

**Interfaces:**
- Consumes: implemented artifact and metadata contracts.
- Produces: operator/developer documentation and final verification evidence.

- [ ] **Step 1: Document the artifact lifecycle**

Add the following contract to both runtime documents, adapted to each document's language:

```text
Active Cam frames are copied from the transient camera runtime path into the
current Vision observation directory under runs/<run_id>/vision/<observation_id>.
The latest successful run artifact remains visible through later agent handoffs.
A successful later Active Cam attempt replaces the display pointer. An explicit
failed attempt clears the pointer but never deletes prior run artifacts.
```

- [ ] **Step 2: Run the focused regression suite**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_active_cam_artifact.py \
  tests/unit/test_vision_agent.py \
  tests/unit/test_langgraph_runtime.py -k 'active_cam or vision' \
  tests/unit/test_controller_planning.py -k 'active_cam or vision' \
  tests/unit/test_utm_runtime_frontend_static.py
node --check web/static/planning.js
.venv/bin/python -m py_compile \
  agents/vision_agent.py \
  utils/active_cam_artifact.py \
  orchestrator/langgraph_runtime.py \
  app/controller.py
git diff --check
```

Expected: all selected tests pass, JavaScript and Python syntax checks exit 0, and `git diff --check` emits no errors.

- [ ] **Step 3: Inspect one generated artifact contract**

Run a test capture or fixture and verify:

```bash
find runs -path '*/vision/*/active_cam_capture_*' -type f -printf '%p %s bytes\n' | tail -5
```

Expected: the newest successful capture exists below its run's Vision observation directory and has nonzero size.

- [ ] **Step 4: Commit Task 4**

```bash
git add \
  docs/agents/vision_pickup_observation_runtime_guideline.txt \
  docs/runtime/closed_loop_and_pages_reference.md
git commit -m "docs: describe active cam artifact lifecycle"
```
