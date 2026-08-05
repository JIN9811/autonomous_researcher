# Active Cam Grounded Specimen Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ground the Active Cam specimen decision in the exact displayed frame, draw a UTM-style bounding box, and prevent later Vision reports from mismatching a persisted frame with unrelated status.

**Architecture:** Extend the existing deterministic red-specimen detector with file input and a bounded ROI. Vision Agent runs that detector on every completed Active Cam capture and persists the annotated frame plus its decision as one artifact. The frontend chooses one canonical evidence object so image and labels always refer to the same capture.

**Tech Stack:** Python 3.12, Pillow, NumPy, scikit-image, pytest, browser JavaScript, existing ATR run-artifact API.

## Global Constraints

- Do not change robot motion, camera ownership, rollout selection, UTM completion, Guardian, or agent ordering.
- Restrict Active Cam detection to the A4 workspace so red robot parts outside it are ignored.
- A readable empty frame is `not_detected`; an unreadable frame is a capture failure.
- Do not use status-only logic to fabricate a positive image detection.
- Keep every displayed image, bounding box, confidence, and status tied to one capture artifact.

---

### Task 1: Add path and ROI support to the shared specimen detector

**Files:**
- Modify: `utils/utm_specimen_presence.py:30-133`
- Modify: `tests/unit/test_utm_specimen_presence.py`

**Interfaces:**
- Consumes: RGB image path and optional normalized ROI `(left, top, right, bottom)`.
- Produces: `inspect_specimen_presence_path(image_path, *, output_dir, specimen_id, frame_id, min_area_px=300.0, roi_normalized=None) -> dict[str, Any]` with full-frame `bbox_xyxy`, `center_px`, annotated image, and detection fields.

- [ ] **Step 1: Write failing detector tests**

Add tests that create a 640x480 frame with a red specimen in the upper A4 ROI and larger red gripper shapes below it, then assert the detector boxes the upper specimen. Add an empty-workspace test that keeps the lower red grippers but returns `detected is False`.

```python
result = inspect_specimen_presence_path(
    frame_path,
    output_dir=tmp_path / "evidence",
    specimen_id="specimen-1",
    frame_id="active-cam-positive",
    roi_normalized=(0.18, 0.0, 0.84, 0.62),
)
assert result["detected"] is True
assert result["bbox_xyxy"] == [360, 90, 430, 170]
assert Path(result["annotated_frame_path"]).is_file()
```

- [ ] **Step 2: Run the tests and confirm the missing API failure**

Run: `pytest -q tests/unit/test_utm_specimen_presence.py`

Expected: FAIL because `inspect_specimen_presence_path` and ROI support do not exist.

- [ ] **Step 3: Refactor detection around one image implementation**

Add `_inspect_specimen_presence_image(...)` that crops only for segmentation, translates the selected component coordinates back into full-frame coordinates, draws on the full image, and writes the existing JSON contract. Keep `inspect_specimen_presence(data_url, ...)` backward compatible and implement the new path wrapper through the same function.

```python
def inspect_specimen_presence_path(
    image_path: Path | str,
    *,
    output_dir: Path | str,
    specimen_id: str,
    frame_id: str,
    min_area_px: float = 300.0,
    roi_normalized: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    image = Image.open(Path(image_path).expanduser()).convert("RGB")
    return _inspect_specimen_presence_image(
        image,
        output_dir=output_dir,
        specimen_id=specimen_id,
        frame_id=frame_id,
        min_area_px=min_area_px,
        roi_normalized=roi_normalized,
    )
```

- [ ] **Step 4: Run detector tests**

Run: `pytest -q tests/unit/test_utm_specimen_presence.py`

Expected: PASS, including existing data-URL behavior.

### Task 2: Ground Active Cam checks and artifacts in image evidence

**Files:**
- Modify: `agents/vision_agent.py:25-129,430-535,768-867,1751-1795`
- Modify: `tests/unit/test_vision_agent.py`
- Modify: `tests/unit/test_active_cam_artifact.py`

**Interfaces:**
- Consumes: the path returned by `lerobot.active_robot_cam.capture`.
- Produces: `active_cam_ejection_check.v1` and `active_cam_run_artifact.v1` containing `specimen_detected`, `bbox_xyxy`, `center_px`, `confidence`, `detector`, `raw_capture_path`, and annotated `capture_path`/`url`.

- [ ] **Step 1: Write failing Vision tests with real images**

Replace invalid byte-only positive fixtures in the affected Active Cam tests with valid RGB images. Add assertions that the positive frame is confirmed and annotated, while a frame containing red grippers only below the ROI enters operator waiting.

```python
active = result.data["vision_agent_report"]["active_cam_ejection_check"]
assert active["specimen_detected"] is True
assert active["bbox_xyxy"]
assert active["confidence"] > 0
assert Path(active["annotated_capture_path"]).is_file()
artifact = result.data["active_cam_artifact_update"]
assert artifact["specimen_detected"] is True
assert artifact["bbox_xyxy"] == active["bbox_xyxy"]
```

- [ ] **Step 2: Run targeted Vision tests and confirm failure**

Run: `pytest -q tests/unit/test_vision_agent.py -k 'active_cam or autoejection' tests/unit/test_active_cam_artifact.py`

Expected: FAIL because Active Cam currently derives detection from tool status and artifacts omit detector metadata.

- [ ] **Step 3: Invoke the shared detector for fresh Active Cam captures**

Import `inspect_specimen_presence_path`. In `_active_cam_ejection_check`, inspect a readable capture with `roi_normalized=(0.18, 0.0, 0.84, 0.62)` and an observation-scoped output directory. Use the detector result as the source of `specimen_detected`, placement status, bounding box, confidence, and annotated path. Keep port-release confirmation as a separate handoff gate.

```python
detection = inspect_specimen_presence_path(
    capture_path,
    output_dir=self._artifact_dir(state, observation_id) / "active_cam_detection",
    specimen_id=str(specimen.get("specimen_id") or "specimen"),
    frame_id=f"active-cam-{state.loop_count}",
    roi_normalized=(0.18, 0.0, 0.84, 0.62),
)
specimen_detected = bool(detection["detected"])
confirmed = bool(tool_ok and specimen_detected and release_ok)
```

- [ ] **Step 4: Persist one immutable image-decision artifact**

Make `_persist_active_cam_run_artifact` copy the annotated image when present and retain the raw source separately. Copy all detector fields into the stored artifact. A stored negative attempt remains a valid `stored` artifact with `specimen_detected: false`; actual capture failures remain `failed` and use the existing clearing behavior.

- [ ] **Step 5: Run Active Cam backend tests**

Run: `pytest -q tests/unit/test_vision_agent.py -k 'active_cam or autoejection' tests/unit/test_active_cam_artifact.py tests/unit/test_controller_planning.py -k 'active_cam'`

Expected: PASS.

### Task 3: Make the Active Cam card consume one canonical evidence object

**Files:**
- Modify: `web/static/planning.js:13591-13646`
- Modify: `tests/unit/test_utm_runtime_frontend_static.py`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: current `active_cam_ejection_check`, persisted `latest_active_cam_artifact`, and operator intervention.
- Produces: an Active Cam card whose image and metrics are derived from the same capture.

- [ ] **Step 1: Write failing frontend contract tests**

Assert that the renderer builds a canonical evidence object, reads persisted `specimen_detected`, `placement_status`, `confidence`, `bbox_xyxy`, and uses the artifact status when the current report is absent, `not_configured`, or points at a different capture.

```python
assert "function canonicalActiveCamEvidence(" in js
assert "persistedArtifact.specimen_detected" in active_cam_source
assert "evidence.capture_path" in active_cam_source
assert "evidence.specimen_detected === true" in active_cam_source
```

- [ ] **Step 2: Run frontend tests and confirm failure**

Run: `pytest -q tests/unit/test_utm_runtime_frontend_static.py tests/integration/test_live_gui_runtime_layout.py -k 'vision or active_cam'`

Expected: FAIL because the renderer currently combines persisted pixels with current-report status.

- [ ] **Step 3: Add canonical evidence selection and render annotated output**

Add `canonicalActiveCamEvidence(active, persistedArtifact, intervention)` and make all image, status, detector, confidence, resolution, camera, and path fields come from its returned `evidence`. Prefer a current result only when its capture path matches the displayed capture; otherwise use the persisted artifact as a complete record.

```javascript
const evidence = canonicalActiveCamEvidence(active, persistedArtifact, intervention);
const detected = !failed && evidence.specimen_detected === true;
const capturePath = evidence.path || evidence.capture_path || "";
const captureUrl = evidence.url || evidence.capture_url || "";
```

The backend-annotated PNG supplies the green box and center marker, matching the existing UTM presentation without a second browser-side detector.

- [ ] **Step 4: Run JavaScript and frontend tests**

Run: `node --check web/static/planning.js`

Run: `pytest -q tests/unit/test_utm_runtime_frontend_static.py tests/integration/test_live_gui_runtime_layout.py -k 'vision or active_cam'`

Expected: PASS.

### Task 4: Validate against the recorded real frames

**Files:**
- No source changes expected.
- Generated evidence stays under a temporary verification directory outside tracked source.

**Interfaces:**
- Consumes: positive `runs/run-20260722T055601Z-fbd01a/vision/obs-frame-0-vision/active_cam_capture_20260722T060343246886Z.png` and empty `active_cam_capture_20260722T055957754742Z.png`.
- Produces: positive and negative detector JSON plus annotated PNG evidence.

- [ ] **Step 1: Run the shared detector on both recorded frames**

Run a short Python command through the project environment that calls `inspect_specimen_presence_path` with the Active Cam ROI for both files.

Expected: positive frame `detected=true` with a box on the red specimen; empty frame `detected=false` despite red robot parts outside the ROI.

- [ ] **Step 2: Visually inspect both annotated PNGs**

Use the local image viewer on the generated files. Confirm the positive box encloses the specimen and the empty image has no fabricated box.

- [ ] **Step 3: Run the focused regression suite**

Run:

```bash
pytest -q \
  tests/unit/test_utm_specimen_presence.py \
  tests/unit/test_active_cam_artifact.py \
  tests/unit/test_vision_agent.py \
  tests/unit/test_controller_planning.py \
  tests/unit/test_utm_runtime_frontend_static.py \
  tests/integration/test_live_gui_runtime_layout.py
node --check web/static/planning.js
```

Expected: PASS, with no changes to physical motion or rollout behavior.
