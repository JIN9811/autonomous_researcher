# Isaac Sim Grasp Latch Action Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a simulation-only contact-triggered pick/unpick latch layer so live LeRobot teleop can carry the red cube stably in Isaac Sim without changing physical robot commands.

**Architecture:** Keep LeRobot teleop action publication unchanged. Add a `GripperCaptureLatchManager` inside `sim/robotis_omx/tools/isaac_omx_mirror_server.py`, fed by existing `/joints` samples, gripper contact reports, finger positions, and red cube pose. The manager latches only the sim object when the cube is inside the A4 workspace/capture volume and both inner gripper sides contact the cube, then releases when the simulated finger gap opens past the cube width plus margin.

**Tech Stack:** Python, Isaac Sim USD/PhysX receiver, existing `IsaacMirrorState`, existing `grasp_diagnostics`, pytest unit fakes in `tests/unit/test_isaac_omx_mirror_server.py`.

---

## Scope

In scope:

- Isaac Sim receiver only.
- No LeRobot command changes.
- No Dynamixel, teleop, or physical robot motion changes.
- Add deterministic diagnostics into `/state`, `/joints` response, Isaac RGB-D render manifest rows, and mirror sidecar rows through the existing response path.
- Keep Lab handoff clean by emitting a stable `grasp_latch` contract in the action metadata.

Out of scope for this plan:

- Full Isaac Lab env implementation.
- GUI controls. The first pass uses environment variables and receiver status diagnostics.
- Pure PhysX grasp replacement. This is a scripted sim/lab action layer with explicit fidelity labeling.

## File Structure

- Modify: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`
  - Add latch config/state helpers.
  - Add capture volume, workspace bounds, finger gap, latch/release logic.
  - Replace the disabled runtime grip result with the new sim-only latch result.
  - Include `grasp_latch` in `action_metadata` and receiver status.

- Modify: `tests/unit/test_isaac_omx_mirror_server.py`
  - Extend existing fakes so object/finger transforms and prim attributes can be inspected.
  - Add tests for pick, no-pick, hold, release, and metadata.

- Modify: `device_bridges/isaac_lab_synthetic.py`
  - Add the latch-layer schema to generated Lab env/action manifests only. This does not run Lab physics.

- Modify: `tests/unit/test_lerobot_isaac_lab_synthetic.py`
  - Assert Lab manifests preserve the latch-layer contract and fidelity label.

- Modify only if needed: `scripts/lerobot_isaac_mirror_runtime_wrapper.py`
  - No behavioral change expected. Only update tests if receiver response metadata needs to be recorded explicitly outside `isaac_post.response`.

---

## Data Contract

Receiver response adds:

```json
{
  "grasp_latch": {
    "schema": "atr.isaac.grasp_latch.v1",
    "enabled": true,
    "state": "idle|candidate|latched|released|blocked",
    "latched": false,
    "event": "none|pick|hold|unpick",
    "fidelity_label": "scripted_contact_latch",
    "workspace_ok": true,
    "capture_volume_ok": true,
    "both_sides_contact": true,
    "contact_force_n": 0.24,
    "contact_threshold_n": 0.2,
    "stable_contact_frames": 2,
    "release_gap_m": 0.058,
    "finger_gap_m": 0.061,
    "relative_pose": {
      "source": "object_pose_relative_to_gripper_center",
      "translation_m": [0.0, 0.0, 0.0],
      "yaw_deg": 0.0
    },
    "object_path": "/World/Workspace/RedSpecimenBlock"
  }
}
```

State transitions:

```text
idle -> candidate:
  workspace_ok && capture_volume_ok && both_sides_contact && force >= threshold

candidate -> latched:
  pick condition stays true for required_stable_frames

latched -> released:
  finger_gap_m >= object_width_m + release_margin_m for release_stable_frames

latched -> blocked:
  object/gripper prim missing or transform unavailable

released -> idle:
  one tick after release metadata is emitted
```

Default env values:

```text
ATR_ISAAC_GRASP_LATCH_ENABLED=1
ATR_ISAAC_GRASP_LATCH_CONTACT_THRESHOLD_N=0.2
ATR_ISAAC_GRASP_LATCH_STABLE_FRAMES=2
ATR_ISAAC_GRASP_LATCH_RELEASE_STABLE_FRAMES=2
ATR_ISAAC_GRASP_LATCH_OBJECT_WIDTH_M=0.05
ATR_ISAAC_GRASP_LATCH_RELEASE_MARGIN_M=0.006
ATR_ISAAC_GRASP_LATCH_CAPTURE_MARGIN_M=0.012
ATR_ISAAC_GRASP_LATCH_A4_X_MIN_M=0.210
ATR_ISAAC_GRASP_LATCH_A4_X_MAX_M=0.420
ATR_ISAAC_GRASP_LATCH_A4_Y_MIN_M=0.1165
ATR_ISAAC_GRASP_LATCH_A4_Y_MAX_M=0.4135
ATR_ISAAC_GRASP_LATCH_Z_MIN_M=-0.02
ATR_ISAAC_GRASP_LATCH_Z_MAX_M=0.12
```

---

### Task 1: Add Unit Tests For Latch State Transitions

**Files:**
- Modify: `tests/unit/test_isaac_omx_mirror_server.py`
- Modify: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`

- [ ] **Step 1: Write failing tests for no-pick outside workspace and single-side contact**

Add imports:

```python
from sim.robotis_omx.tools.isaac_omx_mirror_server import (
    GRIPPER_CONTACT_COLLIDER_TOKENS,
    GripperCaptureLatchManager,
    IsaacMirrorState,
    IsaacReplicatorRgbdRenderBackend,
    MirrorActionProcessor,
    _joint_targets,
    make_handler,
)
```

Add fake prim helpers:

```python
def _set_translate(prim: _FakePrim, xyz: tuple[float, float, float]) -> None:
    attr = prim.attrs.get("xformOp:translate")
    if attr is None:
        attr = prim.CreateAttribute("xformOp:translate", "double3")
    attr.Set(xyz)
```

Add tests:

```python
def test_grasp_latch_does_not_pick_outside_a4_workspace(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_ENABLED", "1")
    stage = _FakeMultiStage(
        [
            "/World/Workspace/RedSpecimenBlock",
            "/World/Robot/Geometry/link6/InnerGripPadCollision",
            "/World/Robot/Geometry/link7/InnerGripPadCollision_mimic",
        ]
    )
    _set_translate(stage.prims["/World/Workspace/RedSpecimenBlock"], (0.60, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link6/InnerGripPadCollision"], (0.59, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link7/InnerGripPadCollision_mimic"], (0.61, 0.265, 0.025))

    state = IsaacMirrorState(Path("scene.usda"), stage_provider=lambda: stage)
    state.contact_force_provider = lambda _stage: {
        "available": True,
        "contact": True,
        "both_sides_contact": True,
        "gripper_contact_sides": ["primary", "mimic"],
        "force_n": 0.4,
        "penetration_m": 0.0,
        "matched_pairs": 2,
        "status": "provided",
    }

    result = state.apply(
        {
            "joint_state": [
                {
                    "isaac_joint_path": "/World/Robot/Geometry/link6/Gripper",
                    "isaac_joint_name": "Gripper",
                    "motor_name": "gripper",
                    "motor_id": 16,
                    "position_deg": 40.0,
                    "target_value": 40.0,
                    "unit": "deg",
                }
            ]
        }
    )

    assert result["grasp_latch"]["state"] == "blocked"
    assert result["grasp_latch"]["latched"] is False
    assert result["grasp_latch"]["workspace_ok"] is False


def test_grasp_latch_requires_both_finger_contacts(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_ENABLED", "1")
    stage = _FakeMultiStage(
        [
            "/World/Workspace/RedSpecimenBlock",
            "/World/Robot/Geometry/link6/InnerGripPadCollision",
            "/World/Robot/Geometry/link7/InnerGripPadCollision_mimic",
        ]
    )
    _set_translate(stage.prims["/World/Workspace/RedSpecimenBlock"], (0.315, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link6/InnerGripPadCollision"], (0.300, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link7/InnerGripPadCollision_mimic"], (0.330, 0.265, 0.025))

    state = IsaacMirrorState(Path("scene.usda"), stage_provider=lambda: stage)
    state.contact_force_provider = lambda _stage: {
        "available": True,
        "contact": False,
        "raw_contact": True,
        "both_sides_contact": False,
        "gripper_contact_sides": ["primary"],
        "force_n": 0.4,
        "penetration_m": 0.0,
        "matched_pairs": 1,
        "status": "provided",
    }

    result = state.apply(
        {
            "joint_state": [
                {
                    "isaac_joint_path": "/World/Robot/Geometry/link6/Gripper",
                    "isaac_joint_name": "Gripper",
                    "motor_name": "gripper",
                    "motor_id": 16,
                    "position_deg": 40.0,
                    "target_value": 40.0,
                    "unit": "deg",
                }
            ]
        }
    )

    assert result["grasp_latch"]["state"] == "idle"
    assert result["grasp_latch"]["both_sides_contact"] is False
    assert result["grasp_latch"]["latched"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_does_not_pick_outside_a4_workspace tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_requires_both_finger_contacts -q
```

Expected:

```text
ImportError or KeyError because GripperCaptureLatchManager/grasp_latch does not exist yet.
```

- [ ] **Step 3: Add minimal disabled latch response**

In `sim/robotis_omx/tools/isaac_omx_mirror_server.py`, add this class before `MirrorActionProcessor`:

```python
class GripperCaptureLatchManager:
    schema = "atr.isaac.grasp_latch.v1"

    def __init__(self, state: "IsaacMirrorState") -> None:
        self._state = state
        self.enabled = _env_bool("ATR_ISAAC_GRASP_LATCH_ENABLED", True)

    def update(self, stage: Any, targets: list[dict[str, Any]], gripper_contact: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "enabled": self.enabled,
            "state": "idle",
            "latched": False,
            "event": "none",
            "fidelity_label": "scripted_contact_latch",
            "workspace_ok": True,
            "capture_volume_ok": False,
            "both_sides_contact": bool(gripper_contact.get("both_sides_contact", gripper_contact.get("contact", False))),
            "contact_force_n": _safe_float(gripper_contact.get("force_n"), 0.0),
            "contact_threshold_n": _env_float("ATR_ISAAC_GRASP_LATCH_CONTACT_THRESHOLD_N", 0.2, minimum=0.0),
            "object_path": RED_SPECIMEN_BLOCK_PATH,
        }
```

In `IsaacMirrorState.__init__`, add:

```python
self.grasp_latch_manager = GripperCaptureLatchManager(self)
```

In `MirrorActionProcessor.process`, after `grasp_diagnostics`:

```python
grasp_latch = self._state.grasp_latch_manager.update(stage, targets, gripper_contact)
```

and return:

```python
"grasp_latch": grasp_latch,
```

In `IsaacMirrorState.apply`, read the processor field and add it to `action_metadata` and `last_apply_result`:

```python
grasp_latch = action_processing["grasp_latch"]
...
"grasp_latch": grasp_latch,
```

- [ ] **Step 4: Run tests again**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_does_not_pick_outside_a4_workspace tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_requires_both_finger_contacts -q
```

Expected:

```text
First test still fails because workspace blocking is not implemented.
Second test passes or fails only on exact state naming.
```

---

### Task 2: Implement Workspace And Capture Volume Gates

**Files:**
- Modify: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`
- Modify: `tests/unit/test_isaac_omx_mirror_server.py`

- [ ] **Step 1: Write failing test for capture volume**

Add:

```python
def test_grasp_latch_enters_candidate_inside_capture_volume(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_STABLE_FRAMES", "2")
    stage = _FakeMultiStage(
        [
            "/World/Workspace/RedSpecimenBlock",
            "/World/Robot/Geometry/link6/InnerGripPadCollision",
            "/World/Robot/Geometry/link7/InnerGripPadCollision_mimic",
        ]
    )
    _set_translate(stage.prims["/World/Workspace/RedSpecimenBlock"], (0.315, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link6/InnerGripPadCollision"], (0.290, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link7/InnerGripPadCollision_mimic"], (0.340, 0.265, 0.025))

    state = IsaacMirrorState(Path("scene.usda"), stage_provider=lambda: stage)
    state.contact_force_provider = lambda _stage: {
        "available": True,
        "contact": True,
        "both_sides_contact": True,
        "gripper_contact_sides": ["primary", "mimic"],
        "force_n": 0.25,
        "penetration_m": 0.0,
        "matched_pairs": 2,
        "status": "provided",
    }

    result = state.apply(
        {
            "joint_state": [
                {
                    "isaac_joint_path": "/World/Robot/Geometry/link6/Gripper",
                    "isaac_joint_name": "Gripper",
                    "motor_name": "gripper",
                    "motor_id": 16,
                    "position_deg": 40.0,
                    "target_value": 40.0,
                    "unit": "deg",
                }
            ]
        }
    )

    assert result["grasp_latch"]["workspace_ok"] is True
    assert result["grasp_latch"]["capture_volume_ok"] is True
    assert result["grasp_latch"]["state"] == "candidate"
    assert result["grasp_latch"]["stable_contact_frames"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_enters_candidate_inside_capture_volume -q
```

Expected:

```text
FAIL because capture_volume_ok and stable_contact_frames are not implemented.
```

- [ ] **Step 3: Implement gates**

Add helper methods to `GripperCaptureLatchManager`:

```python
def _bounds(self) -> dict[str, float]:
    return {
        "x_min": _env_float("ATR_ISAAC_GRASP_LATCH_A4_X_MIN_M", 0.210, minimum=-10.0),
        "x_max": _env_float("ATR_ISAAC_GRASP_LATCH_A4_X_MAX_M", 0.420, minimum=-10.0),
        "y_min": _env_float("ATR_ISAAC_GRASP_LATCH_A4_Y_MIN_M", 0.1165, minimum=-10.0),
        "y_max": _env_float("ATR_ISAAC_GRASP_LATCH_A4_Y_MAX_M", 0.4135, minimum=-10.0),
        "z_min": _env_float("ATR_ISAAC_GRASP_LATCH_Z_MIN_M", -0.02, minimum=-10.0),
        "z_max": _env_float("ATR_ISAAC_GRASP_LATCH_Z_MAX_M", 0.12, minimum=-10.0),
    }

def _workspace_ok(self, object_position: tuple[float, float, float] | None) -> bool:
    if object_position is None:
        return False
    bounds = self._bounds()
    return (
        bounds["x_min"] <= object_position[0] <= bounds["x_max"]
        and bounds["y_min"] <= object_position[1] <= bounds["y_max"]
        and bounds["z_min"] <= object_position[2] <= bounds["z_max"]
    )

def _finger_centers(self, stage: Any) -> dict[str, tuple[float, float, float]]:
    grouped: dict[str, list[tuple[float, float, float]]] = {"primary": [], "mimic": []}
    for item in self._state._gripper_finger_positions(stage):
        side = self._state._gripper_contact_side_for_path(str(item.get("path") or ""))
        position = item.get("position")
        if side in grouped and isinstance(position, tuple):
            grouped[side].append(position)
    centers: dict[str, tuple[float, float, float]] = {}
    for side, values in grouped.items():
        center = self._state._avg_vec3(values)
        if center is not None:
            centers[side] = center
    return centers

def _capture_volume_ok(
    self,
    object_position: tuple[float, float, float] | None,
    centers: dict[str, tuple[float, float, float]],
) -> bool:
    if object_position is None or "primary" not in centers or "mimic" not in centers:
        return False
    margin = _env_float("ATR_ISAAC_GRASP_LATCH_CAPTURE_MARGIN_M", 0.012, minimum=0.0)
    object_width = _env_float("ATR_ISAAC_GRASP_LATCH_OBJECT_WIDTH_M", 0.05, minimum=0.001)
    cx = (centers["primary"][0] + centers["mimic"][0]) * 0.5
    cy = (centers["primary"][1] + centers["mimic"][1]) * 0.5
    cz = (centers["primary"][2] + centers["mimic"][2]) * 0.5
    return (
        abs(object_position[0] - cx) <= object_width * 0.5 + margin
        and abs(object_position[1] - cy) <= object_width * 0.5 + margin
        and abs(object_position[2] - cz) <= object_width * 0.5 + margin
    )
```

In `GripperCaptureLatchManager.__init__`, add:

```python
self._stable_contact_frames = 0
self._release_stable_frames = 0
self._latched = False
self._just_released = False
self._relative_pose: dict[str, Any] = {}
```

In `update`, compute:

```python
object_prim = stage.GetPrimAtPath(RED_SPECIMEN_BLOCK_PATH) if stage is not None else None
object_position = self._state._prim_world_translation(object_prim)
centers = self._finger_centers(stage)
workspace_ok = self._workspace_ok(object_position)
capture_ok = self._capture_volume_ok(object_position, centers)
force_n = _safe_float(gripper_contact.get("force_n"), 0.0)
threshold_n = _env_float("ATR_ISAAC_GRASP_LATCH_CONTACT_THRESHOLD_N", 0.2, minimum=0.0)
both_sides = bool(gripper_contact.get("both_sides_contact", gripper_contact.get("contact", False)))
pick_condition = workspace_ok and capture_ok and both_sides and force_n >= threshold_n
if pick_condition and not self._latched:
    self._stable_contact_frames += 1
else:
    self._stable_contact_frames = 0
state = "candidate" if pick_condition else "blocked" if not workspace_ok else "idle"
```

Return the computed fields.

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_does_not_pick_outside_a4_workspace tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_requires_both_finger_contacts tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_enters_candidate_inside_capture_volume -q
```

Expected:

```text
3 passed
```

---

### Task 3: Implement Pick Latch And Hold Transform

**Files:**
- Modify: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`
- Modify: `tests/unit/test_isaac_omx_mirror_server.py`

- [ ] **Step 1: Write failing test for latch after stable frames**

Add:

```python
def test_grasp_latch_picks_after_stable_both_side_contact(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_STABLE_FRAMES", "2")
    stage = _FakeMultiStage(
        [
            "/World/Workspace/RedSpecimenBlock",
            "/World/Robot/Geometry/link6/InnerGripPadCollision",
            "/World/Robot/Geometry/link7/InnerGripPadCollision_mimic",
        ]
    )
    cube = stage.prims["/World/Workspace/RedSpecimenBlock"]
    _set_translate(cube, (0.315, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link6/InnerGripPadCollision"], (0.290, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link7/InnerGripPadCollision_mimic"], (0.340, 0.265, 0.025))

    state = IsaacMirrorState(Path("scene.usda"), stage_provider=lambda: stage)
    state.contact_force_provider = lambda _stage: {
        "available": True,
        "contact": True,
        "both_sides_contact": True,
        "gripper_contact_sides": ["primary", "mimic"],
        "force_n": 0.25,
        "penetration_m": 0.0,
        "matched_pairs": 2,
        "status": "provided",
    }
    payload = {
        "joint_state": [
            {
                "isaac_joint_path": "/World/Robot/Geometry/link6/Gripper",
                "isaac_joint_name": "Gripper",
                "motor_name": "gripper",
                "motor_id": 16,
                "position_deg": 40.0,
                "target_value": 40.0,
                "unit": "deg",
            }
        ]
    }

    first = state.apply(payload)
    second = state.apply(payload)

    assert first["grasp_latch"]["state"] == "candidate"
    assert second["grasp_latch"]["state"] == "latched"
    assert second["grasp_latch"]["event"] == "pick"
    assert second["grasp_latch"]["latched"] is True
    assert cube.attrs["physics:velocity"].Get() == (0.0, 0.0, 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_picks_after_stable_both_side_contact -q
```

Expected:

```text
FAIL because latched state and object transform hold are not implemented.
```

- [ ] **Step 3: Implement latch and hold**

Add helpers:

```python
def _gripper_center(self, centers: dict[str, tuple[float, float, float]]) -> tuple[float, float, float] | None:
    if "primary" not in centers or "mimic" not in centers:
        return None
    return (
        (centers["primary"][0] + centers["mimic"][0]) * 0.5,
        (centers["primary"][1] + centers["mimic"][1]) * 0.5,
        (centers["primary"][2] + centers["mimic"][2]) * 0.5,
    )

def _store_relative_pose(
    self,
    object_position: tuple[float, float, float],
    gripper_center: tuple[float, float, float],
) -> dict[str, Any]:
    relative = {
        "source": "object_pose_relative_to_gripper_center",
        "translation_m": [
            object_position[0] - gripper_center[0],
            object_position[1] - gripper_center[1],
            object_position[2] - gripper_center[2],
        ],
        "yaw_deg": None,
    }
    self._relative_pose = relative
    return relative

def _apply_latched_object_pose(
    self,
    object_prim: Any,
    gripper_center: tuple[float, float, float],
) -> dict[str, Any]:
    rel = self._relative_pose.get("translation_m")
    if not isinstance(rel, list) or len(rel) < 3:
        return {"ok": False, "status": "relative_pose_missing"}
    next_position = (
        gripper_center[0] + float(rel[0]),
        gripper_center[1] + float(rel[1]),
        gripper_center[2] + float(rel[2]),
    )
    attr = object_prim.GetAttribute("xformOp:translate")
    if attr is None:
        attr = object_prim.CreateAttribute("xformOp:translate", None)
    attr.Set(next_position)
    velocity_reset = self._state._reset_rigid_body_velocity(object_prim)
    return {"ok": True, "status": "object_pose_held", "translate_m": list(next_position), "velocity_reset": velocity_reset}
```

Update `update`:

```python
required_frames = _env_int("ATR_ISAAC_GRASP_LATCH_STABLE_FRAMES", 2, minimum=1)
gripper_center = self._gripper_center(centers)
event = "none"
hold_result: dict[str, Any] = {}
if not self._latched and pick_condition and self._stable_contact_frames >= required_frames:
    if object_position is not None and gripper_center is not None:
        self._latched = True
        self._store_relative_pose(object_position, gripper_center)
        event = "pick"
if self._latched and gripper_center is not None and object_prim is not None:
    hold_result = self._apply_latched_object_pose(object_prim, gripper_center)
state = "latched" if self._latched else "candidate" if pick_condition else "blocked" if not workspace_ok else "idle"
```

Add `relative_pose` and `hold_result` to return.

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_picks_after_stable_both_side_contact -q
```

Expected:

```text
1 passed
```

---

### Task 4: Implement Release Based On Sim Finger Gap

**Files:**
- Modify: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`
- Modify: `tests/unit/test_isaac_omx_mirror_server.py`

- [ ] **Step 1: Write failing release test**

Add:

```python
def test_grasp_latch_releases_when_finger_gap_exceeds_cube_width(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_ENABLED", "1")
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_STABLE_FRAMES", "1")
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_RELEASE_STABLE_FRAMES", "1")
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_OBJECT_WIDTH_M", "0.05")
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_RELEASE_MARGIN_M", "0.006")
    stage = _FakeMultiStage(
        [
            "/World/Workspace/RedSpecimenBlock",
            "/World/Robot/Geometry/link6/InnerGripPadCollision",
            "/World/Robot/Geometry/link7/InnerGripPadCollision_mimic",
        ]
    )
    cube = stage.prims["/World/Workspace/RedSpecimenBlock"]
    _set_translate(cube, (0.315, 0.265, 0.025))
    left = stage.prims["/World/Robot/Geometry/link6/InnerGripPadCollision"]
    right = stage.prims["/World/Robot/Geometry/link7/InnerGripPadCollision_mimic"]
    _set_translate(left, (0.290, 0.265, 0.025))
    _set_translate(right, (0.340, 0.265, 0.025))

    state = IsaacMirrorState(Path("scene.usda"), stage_provider=lambda: stage)
    state.contact_force_provider = lambda _stage: {
        "available": True,
        "contact": True,
        "both_sides_contact": True,
        "gripper_contact_sides": ["primary", "mimic"],
        "force_n": 0.25,
        "penetration_m": 0.0,
        "matched_pairs": 2,
        "status": "provided",
    }
    payload = {
        "joint_state": [
            {
                "isaac_joint_path": "/World/Robot/Geometry/link6/Gripper",
                "isaac_joint_name": "Gripper",
                "motor_name": "gripper",
                "motor_id": 16,
                "position_deg": 40.0,
                "target_value": 40.0,
                "unit": "deg",
            }
        ]
    }

    picked = state.apply(payload)
    assert picked["grasp_latch"]["latched"] is True

    _set_translate(left, (0.275, 0.265, 0.025))
    _set_translate(right, (0.355, 0.265, 0.025))
    released = state.apply(payload)

    assert released["grasp_latch"]["state"] == "released"
    assert released["grasp_latch"]["event"] == "unpick"
    assert released["grasp_latch"]["latched"] is False
    assert released["grasp_latch"]["finger_gap_m"] == pytest.approx(0.08)
```

- [ ] **Step 2: Run release test to verify it fails**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_releases_when_finger_gap_exceeds_cube_width -q
```

Expected:

```text
FAIL because release gap handling is not implemented.
```

- [ ] **Step 3: Implement finger gap release**

Add helper:

```python
def _finger_gap_m(self, centers: dict[str, tuple[float, float, float]]) -> float | None:
    if "primary" not in centers or "mimic" not in centers:
        return None
    return self._state._distance(centers["primary"], centers["mimic"])
```

Before hold pose application in `update`:

```python
finger_gap_m = self._finger_gap_m(centers)
object_width_m = _env_float("ATR_ISAAC_GRASP_LATCH_OBJECT_WIDTH_M", 0.05, minimum=0.001)
release_margin_m = _env_float("ATR_ISAAC_GRASP_LATCH_RELEASE_MARGIN_M", 0.006, minimum=0.0)
release_frames_required = _env_int("ATR_ISAAC_GRASP_LATCH_RELEASE_STABLE_FRAMES", 2, minimum=1)
release_condition = (
    self._latched
    and finger_gap_m is not None
    and finger_gap_m >= object_width_m + release_margin_m
)
if release_condition:
    self._release_stable_frames += 1
else:
    self._release_stable_frames = 0
if self._latched and self._release_stable_frames >= release_frames_required:
    self._latched = False
    self._stable_contact_frames = 0
    self._relative_pose = {}
    event = "unpick"
    state = "released"
```

Add fields to return:

```python
"finger_gap_m": finger_gap_m,
"release_gap_m": object_width_m + release_margin_m,
"release_stable_frames": self._release_stable_frames,
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_releases_when_finger_gap_exceeds_cube_width -q
```

Expected:

```text
1 passed
```

---

### Task 5: Remove Old Gripper Closure Clamp Interference From Latch Mode

**Files:**
- Modify: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`
- Modify: `tests/unit/test_isaac_omx_mirror_server.py`

- [ ] **Step 1: Write failing test that latch mode does not clamp gripper target**

Add:

```python
def test_grasp_latch_does_not_contact_clamp_gripper_target(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_ENABLED", "1")
    stage = _FakeMultiStage(
        [
            "/World/Workspace/RedSpecimenBlock",
            "/World/Robot/Geometry/link6/InnerGripPadCollision",
            "/World/Robot/Geometry/link7/InnerGripPadCollision_mimic",
        ]
    )
    _set_translate(stage.prims["/World/Workspace/RedSpecimenBlock"], (0.315, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link6/InnerGripPadCollision"], (0.290, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link7/InnerGripPadCollision_mimic"], (0.340, 0.265, 0.025))

    state = IsaacMirrorState(Path("scene.usda"), stage_provider=lambda: stage)
    state.contact_force_provider = lambda _stage: {
        "available": True,
        "contact": True,
        "both_sides_contact": True,
        "gripper_contact_sides": ["primary", "mimic"],
        "force_n": 0.25,
        "penetration_m": 0.0,
        "matched_pairs": 2,
        "status": "provided",
    }
    payload = {
        "joint_state": [
            {
                "isaac_joint_path": "/World/Robot/Geometry/link6/Gripper",
                "isaac_joint_name": "Gripper",
                "motor_name": "gripper",
                "motor_id": 16,
                "position_deg": 35.0,
                "target_value": 35.0,
                "unit": "deg",
            }
        ]
    }

    result = state.apply(payload)

    assert result["gripper_contact"]["hold_active"] is False
    assert result["applied_targets"][0]["target_value"] == pytest.approx(35.0)
```

- [ ] **Step 2: Run test to verify current behavior**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_does_not_contact_clamp_gripper_target -q
```

Expected:

```text
FAIL if the old contact hold clamps target_value.
```

- [ ] **Step 3: Gate old contact hold when latch is enabled**

At the top of `_apply_gripper_contact_control`, after gripper target initialization:

```python
if _env_bool("ATR_ISAAC_GRASP_LATCH_ENABLED", True):
    self._gripper_contact_hold_target_value = None
    self._remember_final_gripper_target(targets)
    self._last_gripper_contact = {
        **contact,
        "hold_active": False,
        "hold_reason": "disabled_by_grasp_latch",
        "hold_target_value": None,
        "hold_overtravel_deg": GRIPPER_CONTACT_HOLD_OVERTRAVEL_DEG,
        "release_margin_deg": GRIPPER_CONTACT_RELEASE_MARGIN_DEG,
        "probe_limited": False,
    }
    return dict(self._last_gripper_contact)
```

This preserves contact reporting while removing the old angle clamp that can stop the gripper from closing.

- [ ] **Step 4: Run focused tests**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_does_not_contact_clamp_gripper_target -q
```

Expected:

```text
1 passed
```

---

### Task 6: Persist Latch Metadata Into Render/Training Sidecars

**Files:**
- Modify: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`
- Modify: `device_bridges/isaac_lab_synthetic.py`
- Modify: `tests/unit/test_isaac_omx_mirror_server.py`
- Modify: `tests/unit/test_lerobot_isaac_lab_synthetic.py`

- [ ] **Step 1: Write failing receiver metadata test**

Add:

```python
def test_grasp_latch_metadata_is_written_to_render_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_ENABLED", "1")
    stage = _FakeMultiStage(
        [
            "/World/Workspace/RedSpecimenBlock",
            "/World/Robot/Geometry/link6/InnerGripPadCollision",
            "/World/Robot/Geometry/link7/InnerGripPadCollision_mimic",
        ]
    )
    _set_translate(stage.prims["/World/Workspace/RedSpecimenBlock"], (0.315, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link6/InnerGripPadCollision"], (0.290, 0.265, 0.025))
    _set_translate(stage.prims["/World/Robot/Geometry/link7/InnerGripPadCollision_mimic"], (0.340, 0.265, 0.025))
    state = IsaacMirrorState(Path("scene.usda"), stage_provider=lambda: stage, rgbd_render_backend=None)
    state.contact_force_provider = lambda _stage: {
        "available": True,
        "contact": True,
        "both_sides_contact": True,
        "gripper_contact_sides": ["primary", "mimic"],
        "force_n": 0.25,
        "penetration_m": 0.0,
        "matched_pairs": 2,
        "status": "provided",
    }
    output_dir = tmp_path / "renders"
    payload = {
        "joint_state": [
            {
                "isaac_joint_path": "/World/Robot/Geometry/link6/Gripper",
                "isaac_joint_name": "Gripper",
                "motor_name": "gripper",
                "motor_id": 16,
                "position_deg": 40.0,
                "target_value": 40.0,
                "unit": "deg",
            }
        ],
        "render_request": {
            "enabled": True,
            "output_dir": str(output_dir),
            "cameras": ["top"],
            "frame_index": 0,
            "sample_index": 1,
        },
    }

    state.apply(payload)
    row = json.loads((output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()[0])

    assert row["grasp_latch"]["schema"] == "atr.isaac.grasp_latch.v1"
    assert row["grasp_latch"]["fidelity_label"] == "scripted_contact_latch"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_metadata_is_written_to_render_manifest -q
```

Expected:

```text
FAIL because _handle_render_request does not copy grasp_latch.
```

- [ ] **Step 3: Add metadata to render rows**

In `IsaacMirrorState.apply`, add `grasp_latch` to `action_metadata`:

```python
action_metadata = {
    "action_processing": action_processing_summary,
    "gripper_contact": gripper_contact,
    "gripper_effort_limit": gripper_effort_limit,
    "grasp_diagnostics": grasp_diagnostics,
    "grasp_latch": grasp_latch,
}
```

In `_handle_render_request`, extend the copied metadata keys:

```python
for key in ("action_processing", "gripper_contact", "gripper_effort_limit", "grasp_diagnostics", "grasp_latch"):
```

- [ ] **Step 4: Add Lab manifest contract test**

In `tests/unit/test_lerobot_isaac_lab_synthetic.py`, extend the existing Lab env manifest test to assert:

```python
assert manifest["grasp_action_layer"]["schema"] == "atr.isaac.grasp_latch.v1"
assert manifest["grasp_action_layer"]["mode"] == "scripted_contact_latch"
assert manifest["grasp_action_layer"]["lab_hook"] == "pre_physics_step_action_postprocess"
```

- [ ] **Step 5: Implement Lab manifest fields**

In `device_bridges/isaac_lab_synthetic.py`, where `robotis_omx_pick_place_env.json` is built, add:

```python
"grasp_action_layer": {
    "schema": "atr.isaac.grasp_latch.v1",
    "mode": "scripted_contact_latch",
    "sim_receiver": "sim.robotis_omx.tools.isaac_omx_mirror_server.GripperCaptureLatchManager",
    "lab_hook": "pre_physics_step_action_postprocess",
    "workspace": "a4_bounds",
    "pick_condition": "workspace_ok && capture_volume_ok && both_fingers_contact && force >= threshold",
    "release_condition": "finger_gap_m >= object_width_m + release_margin_m",
    "fidelity_label": "scripted_contact_latch",
    "default_fidelity_weight": 0.35,
}
```

- [ ] **Step 6: Run metadata tests**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_grasp_latch_metadata_is_written_to_render_manifest tests/unit/test_lerobot_isaac_lab_synthetic.py -q
```

Expected:

```text
All selected tests pass.
```

---

### Task 7: Receiver Status And Safety Diagnostics

**Files:**
- Modify: `sim/robotis_omx/tools/isaac_omx_mirror_server.py`
- Modify: `tests/unit/test_isaac_omx_mirror_server.py`

- [ ] **Step 1: Write failing status test**

Add:

```python
def test_receiver_status_exposes_grasp_latch_state(monkeypatch) -> None:
    monkeypatch.setenv("ATR_ISAAC_GRASP_LATCH_ENABLED", "1")
    stage = _FakeMultiStage(["/World/Workspace/RedSpecimenBlock"])
    _set_translate(stage.prims["/World/Workspace/RedSpecimenBlock"], (0.315, 0.265, 0.025))
    state = IsaacMirrorState(Path("scene.usda"), stage_provider=lambda: stage)

    status = state.status_payload()

    assert status["grasp_latch"]["schema"] == "atr.isaac.grasp_latch.v1"
    assert status["grasp_latch"]["enabled"] is True
    assert status["grasp_latch"]["latched"] is False
```

- [ ] **Step 2: Run status test to verify it fails**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_receiver_status_exposes_grasp_latch_state -q
```

Expected:

```text
FAIL because status_payload lacks grasp_latch.
```

- [ ] **Step 3: Add manager snapshot**

In `GripperCaptureLatchManager.__init__`, add:

```python
self._last_result: dict[str, Any] = {
    "schema": self.schema,
    "enabled": self.enabled,
    "state": "idle",
    "latched": False,
    "event": "none",
    "fidelity_label": "scripted_contact_latch",
}
```

At end of `update`:

```python
self._last_result = result
return dict(result)
```

Add:

```python
def status(self) -> dict[str, Any]:
    return dict(self._last_result)
```

In `status_payload`, add:

```python
"grasp_latch": self.grasp_latch_manager.status(),
```

- [ ] **Step 4: Run status test**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py::test_receiver_status_exposes_grasp_latch_state -q
```

Expected:

```text
1 passed
```

---

### Task 8: Full Verification

**Files:**
- No code changes unless tests expose a regression.

- [ ] **Step 1: Run receiver unit tests**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_isaac_omx_mirror_server.py -q
```

Expected:

```text
All tests pass.
```

- [ ] **Step 2: Run wrapper unit tests to prove teleop publication is unchanged**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_lerobot_isaac_mirror_runtime_wrapper.py -q
```

Expected:

```text
All tests pass.
```

- [ ] **Step 3: Run Lab synthetic tests**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_lerobot_isaac_lab_synthetic.py tests/unit/test_lerobot_synthetic_e2e_smoke.py -q
```

Expected:

```text
All tests pass.
```

- [ ] **Step 4: Static checks**

Run:

```bash
.venv/bin/python -m compileall -q sim/robotis_omx/tools/isaac_omx_mirror_server.py device_bridges/isaac_lab_synthetic.py tests
git diff --check
```

Expected:

```text
No output from git diff --check.
compileall exits 0.
```

- [ ] **Step 5: Manual Isaac Sim smoke**

Run the receiver in Isaac extension mode from the GUI and perform:

```text
1. Put cube inside A4 workspace.
2. Start teleop mirror.
3. Close gripper until both inner pads touch cube.
4. Confirm /state last_apply_result.grasp_latch event becomes pick and latched=true.
5. Lift cube.
6. Open gripper.
7. Confirm event becomes unpick and latched=false.
8. Confirm physical teleop action stream still follows raw leader/follower action.
```

Expected:

```text
Cube sticks to the gripper in sim only after both-side contact and releases when sim finger gap opens.
No LeRobot command path is changed.
```

---

## Implementation Notes

- The old `_apply_gripper_contact_control` contact hold clamp should not fight the new latch mode. Keep its diagnostics, but disable its target clamping when `ATR_ISAAC_GRASP_LATCH_ENABLED=1`.
- Do not use raw gripper command as the primary release condition. Use measured sim finger gap.
- Do not center the cube on pick. Preserve the object pose relative to the gripper center at the moment of latch.
- Keep cube-vs-world collision active. If finger-vs-cube collisions fight the held pose in the real runtime, add runtime-only finger/object collision filtering as a separate follow-up, not in the first implementation.
- Mark all outputs with `fidelity_label=scripted_contact_latch` so training can down-weight these samples relative to real physical grasps.

## Self-Review

- Spec coverage: The plan covers sim-only pick/unpick, A4/workspace gating, capture volume, both-side contact threshold, stable frame hysteresis, release by sim finger gap, metadata, Lab handoff, and verification.
- Placeholder scan: No TBD/TODO/fill-later placeholders are present.
- Type consistency: `grasp_latch`, `GripperCaptureLatchManager`, `finger_gap_m`, `release_gap_m`, and `fidelity_label` are used consistently across tasks.
- Scope check: This is a single focused receiver feature. Isaac Lab runtime implementation remains intentionally out of scope.
