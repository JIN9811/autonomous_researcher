"""Tests for the Isaac OMX mirror receiver payload contract."""

from __future__ import annotations

from pathlib import Path

from sim.robotis_omx.tools.isaac_omx_mirror_server import IsaacMirrorState, _joint_targets


class _FakeAttr:
    def __init__(self) -> None:
        self.value = None

    def Set(self, value):  # noqa: N802 - USD-style fake
        self.value = value


class _FakePrim:
    def __init__(self) -> None:
        self.attrs = {"drive:angular:physics:targetPosition": _FakeAttr()}

    def IsValid(self):  # noqa: N802 - USD-style fake
        return True

    def GetAttribute(self, name):  # noqa: N802 - USD-style fake
        return self.attrs.get(name)


class _FakeStatefulPrim(_FakePrim):
    def __init__(self) -> None:
        super().__init__()
        self.attrs["state:angular:physics:position"] = _FakeAttr()


class _FakeStage:
    def __init__(self, path: str) -> None:
        self.path = path
        self.prim = _FakePrim()

    def GetPrimAtPath(self, path):  # noqa: N802 - USD-style fake
        if path == self.path:
            return self.prim
        return None


class _FakeTreePrim:
    def __init__(self, path: str, *, name: str = "", type_name: str = "", schemas: list[str] | None = None) -> None:
        self.path = path
        self.name = name or path.rsplit("/", 1)[-1]
        self.type_name = type_name
        self.schemas = schemas or []

    def IsValid(self):  # noqa: N802 - USD-style fake
        return True

    def GetName(self):  # noqa: N802 - USD-style fake
        return self.name

    def GetTypeName(self):  # noqa: N802 - USD-style fake
        return self.type_name

    def GetPath(self):  # noqa: N802 - USD-style fake
        return self.path

    def GetAppliedSchemas(self):  # noqa: N802 - USD-style fake
        return self.schemas

    def GetAttribute(self, name):  # noqa: N802 - USD-style fake
        return _FakeAttr() if name == "drive:angular:physics:targetPosition" else None


class _FakeTreeStage:
    def __init__(self) -> None:
        self.prims = [
            _FakeTreePrim("/World/PhysicsScene", type_name="PhysicsScene"),
            _FakeTreePrim("/World/Table/TableTop", type_name="Cube", schemas=["PhysicsCollisionAPI"]),
            _FakeTreePrim(
                "/World/Workspace/RedSpecimenBlock",
                type_name="Cube",
                schemas=["PhysicsCollisionAPI", "PhysicsRigidBodyAPI", "PhysicsMassAPI"],
            ),
            _FakeTreePrim("/World/Robot/Geometry/link0/link1/Joint1", type_name="PhysicsRevoluteJoint"),
        ]

    def GetPrimAtPath(self, path):  # noqa: N802 - USD-style fake
        for prim in self.prims:
            if prim.path == path:
                return prim
        return None

    def GetPseudoRoot(self):  # noqa: N802 - USD-style fake
        return type("_PseudoRoot", (), {"GetChildren": lambda _self: [_FakeTreePrim("/World", name="World")]})()

    def Traverse(self):  # noqa: N802 - USD-style fake
        return list(self.prims)


def test_joint_targets_extracts_valid_isaac_joint_targets() -> None:
    payload = {
        "joint_state": [
            {
                "motor_id": 11,
                "isaac_joint_name": "Joint1",
                "isaac_joint_path": "/World/Robot/Geometry/link0/link1/Joint1",
                "mimic_joint_path": "",
                "position_deg": "12.5",
                "unit": "deg",
            },
            {"motor_id": 99, "position_deg": 3.0},
        ]
    }

    targets = _joint_targets(payload)

    assert targets == [
        {
            "path": "/World/Robot/Geometry/link0/link1/Joint1",
            "mimic_path": "",
            "name": "Joint1",
            "motor_id": 11,
            "target_value": 12.5,
            "unit": "deg",
        }
    ]


def test_joint_targets_prefers_target_value_over_position() -> None:
    payload = {
        "joint_state": [
            {
                "motor_id": 16,
                "isaac_joint_name": "Gripper",
                "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper",
                "mimic_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic",
                "position_deg": 1.0,
                "target_value": 44.0,
            }
        ]
    }

    targets = _joint_targets(payload)

    assert targets[0]["target_value"] == 44.0
    assert targets[0]["mimic_path"].endswith("/Gripper_mimic")


def test_deferred_receive_queues_until_update_tick_applies_to_stage() -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=True, stage_provider=lambda: stage)
    payload = {
        "joint_state": [
            {
                "motor_id": 11,
                "isaac_joint_name": "Joint1",
                "isaac_joint_path": joint_path,
                "target_value": 31.25,
            }
        ]
    }

    queued = state.receive(payload)

    assert queued["ok"] is True
    assert queued["status"] == "queued"
    assert stage.prim.attrs["drive:angular:physics:targetPosition"].value is None

    applied = state.apply_latest_pending()

    assert applied["ok"] is True
    assert applied["status"] == "applied"
    assert applied["applied_count"] == 1
    assert stage.prim.attrs["drive:angular:physics:targetPosition"].value == 31.25


def test_direct_receive_applies_immediately_when_defer_disabled() -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive({"joint_state": [{"isaac_joint_path": joint_path, "target_value": -7.0}]})

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert stage.prim.attrs["drive:angular:physics:targetPosition"].value == -7.0


def test_apply_joint_target_updates_drive_target_and_authored_joint_state() -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    stage.prim = _FakeStatefulPrim()
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive({"joint_state": [{"isaac_joint_path": joint_path, "target_value": 42.0}]})

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert stage.prim.attrs["drive:angular:physics:targetPosition"].value == 42.0
    assert stage.prim.attrs["state:angular:physics:position"].value == 42.0


def test_status_payload_reports_apply_mode_and_pending_state() -> None:
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=True, stage_provider=lambda: None)
    state.receive({"joint_state": [{"isaac_joint_path": "/World/Robot/Joint", "target_value": 1.0}]})

    status = state.status_payload()

    assert status["ok"] is True
    assert status["apply_mode"] == "deferred_update_tick"
    assert status["pending_sample"] is True
    assert status["sample_count"] == 1
    assert status["latest_state_path"] == "/tmp/atr_isaac_omx_mirror_latest.json"


def test_status_payload_includes_last_payload_summary_for_bridge_verification() -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    state.receive(
        {
            "session_id": "isaac-mirror-123",
            "sample_index": 7,
            "timestamp": "2026-06-23T00:00:00+00:00",
            "joint_state": [{"motor_id": 11, "isaac_joint_path": joint_path, "target_value": 9.5}],
        }
    )

    status = state.status_payload()

    assert status["last_payload_summary"] == {
        "session_id": "isaac-mirror-123",
        "sample_index": 7,
        "timestamp": "2026-06-23T00:00:00+00:00",
        "joint_count": 1,
        "target_count": 1,
    }
    assert status["last_apply_result"]["status"] == "applied"


def test_stage_summary_reports_physics_readiness_for_workspace_objects() -> None:
    stage = _FakeTreeStage()
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.apply(
        {
            "joint_state": [
                {
                    "motor_id": 11,
                    "isaac_joint_path": "/World/Robot/Geometry/link0/link1/Joint1",
                    "target_value": 10.0,
                }
            ]
        }
    )

    summary = result["stage_summary"]
    assert summary["physics_ready"] is True
    assert summary["physics_scene_paths"] == ["/World/PhysicsScene"]
    assert "/World/Table/TableTop" in summary["collision_paths"]
    assert "/World/Workspace/RedSpecimenBlock" in summary["collision_paths"]
    assert summary["rigid_body_paths"] == ["/World/Workspace/RedSpecimenBlock"]
