"""Tests for the Isaac OMX mirror receiver payload contract."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from sim.robotis_omx.tools.isaac_omx_mirror_server import (
    GRIPPER_CONTACT_COLLIDER_TOKENS,
    IsaacMirrorState,
    _joint_targets,
)


class _FakeAttr:
    def __init__(self, value=None) -> None:
        self.value = value
        self.clear_count = 0
        self.set_count = 0

    def Set(self, value):  # noqa: N802 - USD-style fake
        self.value = value
        self.set_count += 1

    def Get(self):  # noqa: N802 - USD-style fake
        return self.value

    def Clear(self):  # noqa: N802 - USD-style fake
        self.value = None
        self.clear_count += 1


class _FakeRootLayer:
    def __init__(self) -> None:
        self.save_count = 0

    def Save(self):  # noqa: N802 - USD-style fake
        self.save_count += 1


class _FakeRelationship:
    def __init__(self) -> None:
        self.targets = []

    def SetTargets(self, targets):  # noqa: N802 - USD-style fake
        self.targets = list(targets)


class _FakePrim:
    def __init__(self, path: str = "") -> None:
        self.path = path
        self.type_name = ""
        self.attrs = {"drive:angular:physics:targetPosition": _FakeAttr()}
        self.relationships: dict[str, _FakeRelationship] = {}

    def IsValid(self):  # noqa: N802 - USD-style fake
        return True

    def GetPath(self):  # noqa: N802 - USD-style fake
        return self.path

    def GetTypeName(self):  # noqa: N802 - USD-style fake
        return self.type_name

    def GetAttribute(self, name):  # noqa: N802 - USD-style fake
        return self.attrs.get(name)

    def CreateAttribute(self, name, _type_name):  # noqa: N802 - USD-style fake
        attr = _FakeAttr()
        self.attrs[name] = attr
        return attr

    def GetRelationship(self, name):  # noqa: N802 - USD-style fake
        return self.relationships.get(name)

    def CreateRelationship(self, name):  # noqa: N802 - USD-style fake
        rel = _FakeRelationship()
        self.relationships[name] = rel
        return rel


class _FakeStatefulPrim(_FakePrim):
    def __init__(self) -> None:
        super().__init__()
        self.attrs["state:angular:physics:position"] = _FakeAttr()


class _FakeStage:
    def __init__(self, path: str) -> None:
        self.path = path
        self.prim = _FakePrim()
        self.root_layer = _FakeRootLayer()

    def GetPrimAtPath(self, path):  # noqa: N802 - USD-style fake
        if path == self.path:
            return self.prim
        return None

    def GetRootLayer(self):  # noqa: N802 - USD-style fake
        return self.root_layer


class _FakeMultiStage:
    def __init__(self, paths: list[str]) -> None:
        self.prims = {path: _FakePrim(path) for path in paths}
        self.root_layer = _FakeRootLayer()

    def GetPrimAtPath(self, path):  # noqa: N802 - USD-style fake
        return self.prims.get(path)

    def GetRootLayer(self):  # noqa: N802 - USD-style fake
        return self.root_layer

    def DefinePrim(self, path, type_name):  # noqa: N802 - USD-style fake
        prim = self.prims.get(path)
        if prim is None:
            prim = _FakePrim(path)
            self.prims[path] = prim
        prim.type_name = type_name
        return prim

    def RemovePrim(self, path):  # noqa: N802 - USD-style fake
        self.prims.pop(path, None)
        return True

    def Traverse(self):  # noqa: N802 - USD-style fake
        return list(self.prims.values())


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

    def CreateAttribute(self, _name, _type_name):  # noqa: N802 - USD-style fake
        return _FakeAttr()


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
            "motor_name": "",
            "motor_id": 11,
            "target_value": 12.5,
            "source_value": 12.5,
            "base_target_value": 12.5,
            "calibration_applied": False,
            "clamped": False,
            "recomputed_from_source": False,
            "mimic_multiplier": 1.0,
            "unit": "deg",
            "drive_stiffness": 450.0,
            "drive_damping": 60.0,
            "drive_max_force": 1.5,
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
    assert targets[0]["mimic_multiplier"] == -1.0


def test_joint_targets_recomputes_running_wrapper_payload_from_source_value() -> None:
    payload = {
        "joint_state": [
            {
                "motor_id": 13,
                "motor_name": "elbow_flex",
                "isaac_joint_name": "Joint3",
                "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/Joint3",
                "position_deg": 43.58974358974362,
                "target_value": 43.58974358974362,
                "source_value": 55.799755799755815,
            }
        ]
    }

    targets = _joint_targets(payload)

    assert targets[0]["target_value"] == pytest.approx(100.43956043956047)
    assert targets[0]["recomputed_from_source"] is True
    assert targets[0]["conversion_mode"] == "dynamixel_raw_resolution"
    assert targets[0]["source_raw_position"] == pytest.approx(3190.0)


def test_joint_targets_recomputes_gripper_live_source_as_dynamixel_angle() -> None:
    payload = {
        "joint_state": [
            {
                "motor_id": 16,
                "motor_name": "gripper",
                "isaac_joint_name": "Gripper",
                "isaac_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper",
                "mimic_joint_path": "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic",
                "target_value": 59.9,
                "source_value": 59.9,
                "unit": "percent",
            }
        ]
    }

    targets = _joint_targets(payload)

    assert targets[0]["target_value"] == pytest.approx(35.64)
    assert targets[0]["recomputed_from_source"] is True
    assert targets[0]["drive_stiffness"] == 180.0
    assert targets[0]["drive_damping"] == 18.0
    assert targets[0]["drive_max_force"] == 4.0


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
    assert stage.prim.attrs["drive:angular:physics:stiffness"].value == 450.0
    assert stage.prim.attrs["drive:angular:physics:damping"].value == 60.0
    assert stage.prim.attrs["drive:angular:physics:maxForce"].value == 1.5


def test_direct_receive_applies_immediately_when_defer_disabled() -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive({"joint_state": [{"isaac_joint_path": joint_path, "target_value": -7.0}]})

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert stage.prim.attrs["drive:angular:physics:targetPosition"].value == -7.0
    assert stage.prim.attrs["drive:angular:physics:stiffness"].value == 450.0
    assert stage.prim.attrs["drive:angular:physics:damping"].value == 60.0
    assert stage.prim.attrs["drive:angular:physics:maxForce"].value == 1.5


def test_apply_joint_target_prefers_drive_target_without_teleporting_joint_state() -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    stage.prim = _FakeStatefulPrim()
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive({"joint_state": [{"isaac_joint_path": joint_path, "target_value": 42.0}]})

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert stage.prim.attrs["drive:angular:physics:targetPosition"].value == 42.0
    assert stage.prim.attrs["drive:angular:physics:stiffness"].value == 450.0
    assert stage.prim.attrs["drive:angular:physics:damping"].value == 60.0
    assert stage.prim.attrs["drive:angular:physics:maxForce"].value == 1.5
    assert stage.prim.attrs["state:angular:physics:position"].value is None


def test_apply_joint_target_expands_physics_limits_to_include_live_target() -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/link2/link3/Joint3"
    stage = _FakeStage(joint_path)
    stage.prim.attrs["physics:lowerLimit"] = _FakeAttr(-120.0)
    stage.prim.attrs["physics:upperLimit"] = _FakeAttr(90.0)
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive({"joint_state": [{"isaac_joint_path": joint_path, "target_value": 101.0}]})

    assert result["ok"] is True
    assert stage.prim.attrs["physics:lowerLimit"].value == -120.0
    assert stage.prim.attrs["physics:upperLimit"].value == 101.0
    assert result["applied_targets"][0]["physics_lower_limit"] == -120.0
    assert result["applied_targets"][0]["physics_upper_limit"] == 101.0


def test_gripper_mimic_applies_inverse_target_value() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    stage = _FakeMultiStage([gripper_path, mimic_path])
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "target_value": 60.0,
                    "source_value": 60.0,
                    "unit": "percent",
                }
            ]
        }
    )

    assert result["ok"] is True
    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == 36.0
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == -36.0
    assert stage.prims[gripper_path].attrs["drive:angular:physics:stiffness"].value == 180.0
    assert stage.prims[gripper_path].attrs["drive:angular:physics:damping"].value == 18.0
    assert stage.prims[gripper_path].attrs["drive:angular:physics:maxForce"].value == 4.0
    assert result["applied_targets"][0]["conversion_mode"] == "dynamixel_raw_resolution"
    assert result["applied_targets"][0]["source_raw_position"] == pytest.approx(2457.0)
    assert result["applied_targets"][0]["source_zero_raw_position"] == pytest.approx(2047.5)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:stiffness"].value == 180.0
    assert stage.prims[mimic_path].attrs["drive:angular:physics:damping"].value == 18.0
    assert stage.prims[mimic_path].attrs["drive:angular:physics:maxForce"].value == 4.0


def test_gripper_contact_matching_covers_real_collision_meshes() -> None:
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: _FakeMultiStage([]))
    contact_paths = (
        "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/InnerGripPadCollision",
        "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/follower_07_gripper_motorized_1/follower_07_gripper_motorized",
        "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/follower_08_gripper_gear_1/follower_08_gripper_gear",
        "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/follower_05_tip_1/follower_05_tip",
    )

    for path in contact_paths:
        assert state._path_matches_any(path, GRIPPER_CONTACT_COLLIDER_TOKENS), path


def test_contact_report_returns_matched_real_gripper_pair_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    gripper_path = (
        "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/"
        "follower_07_gripper_motorized_1/follower_07_gripper_motorized"
    )
    cube_path = "/World/Workspace/RedSpecimenBlock"
    header = types.SimpleNamespace(
        collider0=gripper_path,
        collider1=cube_path,
        contact_data_offset=0,
        num_contact_data=1,
    )
    contact = types.SimpleNamespace(impulse=(0.0, 0.05, 0.0), separation=-0.0012)

    class _FakePhysxInterface:
        def get_contact_report(self):
            return [header], [contact]

        def get_simulation_time_steps_per_second(self, _stage_id, _scene_path):
            return 100.0

    physx_module = types.ModuleType("omni.physx")
    physx_module.get_physx_simulation_interface = lambda: _FakePhysxInterface()
    omni_module = types.ModuleType("omni")
    omni_module.physx = physx_module
    monkeypatch.setitem(sys.modules, "omni", omni_module)
    monkeypatch.setitem(sys.modules, "omni.physx", physx_module)

    class _FakePhysicsSchemaTools:
        @staticmethod
        def intToSdfPath(value):  # noqa: N802 - USD-style fake
            return value

    pxr_module = types.ModuleType("pxr")
    pxr_module.PhysicsSchemaTools = _FakePhysicsSchemaTools
    monkeypatch.setitem(sys.modules, "pxr", pxr_module)

    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: _FakeMultiStage([]))

    result = state._poll_gripper_contact_force(None)

    assert result["contact"] is True
    assert result["force_n"] == pytest.approx(5.0)
    assert result["penetration_m"] == pytest.approx(0.0012)
    assert result["matched_pairs"] == 1
    assert result["matched_pair_paths"] == [{"collider0": gripper_path, "collider1": cube_path}]


def test_gripper_close_target_uses_fast_probe_step_before_contact_hold() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    stage = _FakeMultiStage([gripper_path, mimic_path])
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 60.0,
                    "unit": "percent",
                }
            ]
        }
    )
    result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 50.0,
                    "unit": "percent",
                }
            ]
        }
    )

    assert result["runtime_grip"]["status"] == "runtime_grip_disabled"
    assert result["runtime_grip"]["enabled"] is False
    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(30.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-30.0)
    assert result["applied_targets"][0]["slew_limited"] is False
    assert result["applied_targets"][0]["raw_target_value"] == pytest.approx(0.0)
    assert result["applied_targets"][0]["contact_probe_limited"] is True
    assert result["applied_targets"][0]["contact_hold_active"] is False
    assert result["gripper_contact"]["hold_active"] is False


def test_gripper_contact_force_holds_close_target_until_operator_opens() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    stage = _FakeMultiStage([gripper_path, mimic_path])
    contact_state = {
        "available": True,
        "contact": False,
        "force_n": 0.0,
        "status": "test_contact_report",
    }
    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=False,
        stage_provider=lambda: stage,
        contact_force_provider=lambda _stage: dict(contact_state),
    )

    state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 60.0,
                    "unit": "percent",
                }
            ]
        }
    )

    contact_state.update({"contact": True, "force_n": 18.0})
    contact_result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 50.0,
                    "unit": "percent",
                }
            ]
        }
    )

    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(30.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-30.0)
    assert contact_result["gripper_contact"]["hold_active"] is True
    assert contact_result["gripper_contact"]["hold_target_value"] == pytest.approx(30.0)
    assert contact_result["applied_targets"][0]["contact_hold_active"] is True

    held_result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 50.0,
                    "unit": "percent",
                }
            ]
        }
    )

    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(30.0)
    assert held_result["gripper_contact"]["hold_active"] is True
    assert held_result["applied_targets"][0]["contact_hold_active"] is True

    contact_state.update({"contact": False, "force_n": 0.0})
    open_result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 60.0,
                    "unit": "percent",
                }
            ]
        }
    )

    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(36.0)
    assert open_result["gripper_contact"]["hold_active"] is False


def test_gripper_contact_penetration_holds_previous_target_instead_of_digging_deeper() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    stage = _FakeMultiStage([gripper_path, mimic_path])
    contact_state = {
        "available": True,
        "contact": False,
        "force_n": 0.0,
        "penetration_m": 0.0,
        "status": "test_contact_report",
    }
    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=False,
        stage_provider=lambda: stage,
        contact_force_provider=lambda _stage: dict(contact_state),
    )

    state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 60.0,
                    "unit": "percent",
                }
            ]
        }
    )
    state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 50.0,
                    "unit": "percent",
                }
            ]
        }
    )

    contact_state.update({"contact": True, "force_n": 18.0, "penetration_m": 0.0012})
    result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 40.0,
                    "unit": "percent",
                }
            ]
        }
    )

    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(30.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-30.0)
    assert result["gripper_contact"]["hold_active"] is True
    assert result["gripper_contact"]["hold_target_value"] == pytest.approx(30.0)
    assert result["applied_targets"][0]["contact_hold_active"] is True
    assert result["applied_targets"][0]["contact_penetration_limited"] is True


def test_gripper_contact_hold_releases_when_contact_is_lost_and_operator_opens() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    stage = _FakeMultiStage([gripper_path, mimic_path])
    contact_state = {
        "available": True,
        "contact": False,
        "force_n": 0.0,
        "penetration_m": 0.0,
        "status": "test_contact_report",
    }
    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=False,
        stage_provider=lambda: stage,
        contact_force_provider=lambda _stage: dict(contact_state),
    )

    state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "target_value": 36.0,
                }
            ]
        }
    )
    contact_state.update({"contact": True, "force_n": 18.0})
    held = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "target_value": 35.2,
                }
            ]
        }
    )
    assert held["gripper_contact"]["hold_active"] is True
    assert held["gripper_contact"]["hold_target_value"] == pytest.approx(35.2)

    contact_state.update({"contact": False, "force_n": 0.0})
    released = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "target_value": 35.9,
                }
            ]
        }
    )

    assert released["gripper_contact"]["hold_active"] is False
    assert released["gripper_contact"]["hold_target_value"] is None
    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(35.9)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-35.9)


def test_gripper_direct_target_jump_is_not_slew_limited() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    stage = _FakeMultiStage([gripper_path])
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "target_value": 0.0,
                }
            ]
        }
    )
    result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "target_value": 90.0,
                }
            ]
        }
    )

    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(90.0)
    assert result["applied_targets"][0]["slew_limited"] is False
    assert result["applied_targets"][0]["raw_target_value"] == pytest.approx(90.0)


def test_runtime_grip_disabled_does_not_author_surface_gripper_or_fixed_joint() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    body0_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5"
    left_finger_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6"
    right_finger_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7"
    cube_path = "/World/Workspace/RedSpecimenBlock"
    grip_joint_path = "/World/RuntimeGrip/OmxTeleopGripJoint"
    surface_gripper_path = "/World/RuntimeGrip/SurfaceGripper"
    stage = _FakeMultiStage([gripper_path, mimic_path, body0_path, left_finger_path, right_finger_path, cube_path])
    stage.prims[left_finger_path].attrs["xformOp:translate"] = _FakeAttr((0.39, 0.3, 0.03))
    stage.prims[right_finger_path].attrs["xformOp:translate"] = _FakeAttr((0.41, 0.3, 0.03))
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.4, 0.3, 0.015))
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 52.0,
                    "unit": "percent",
                }
            ]
        }
    )

    assert "grasp_assist" not in result
    assert result["runtime_grip"]["status"] == "runtime_grip_disabled"
    assert result["runtime_grip"]["enabled"] is False
    assert grip_joint_path not in stage.prims
    assert surface_gripper_path not in stage.prims
    assert "physics:kinematicEnabled" not in stage.prims[cube_path].attrs
    assert "physics:velocity" not in stage.prims[cube_path].attrs
    assert "physics:angularVelocity" not in stage.prims[cube_path].attrs
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.4, 0.3, 0.015)


def test_gripper_open_removes_stale_legacy_fixed_joint() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    body0_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5"
    left_finger_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6"
    right_finger_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7"
    cube_path = "/World/Workspace/RedSpecimenBlock"
    grip_joint_path = "/World/RuntimeGrip/OmxTeleopGripJoint"
    stage = _FakeMultiStage([gripper_path, mimic_path, body0_path, left_finger_path, right_finger_path, cube_path])
    stage.prims[left_finger_path].attrs["xformOp:translate"] = _FakeAttr((0.39, 0.3, 0.03))
    stage.prims[right_finger_path].attrs["xformOp:translate"] = _FakeAttr((0.41, 0.3, 0.03))
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.4, 0.3, 0.015))
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    stage.DefinePrim(grip_joint_path, "PhysicsFixedJoint")
    result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 60.0,
                    "unit": "percent",
                }
            ]
        }
    )
    assert result["runtime_grip"]["status"] == "runtime_grip_disabled"
    assert result["runtime_grip"]["enabled"] is False
    assert result["runtime_grip"]["removed_legacy_joint"] is True
    assert grip_joint_path not in stage.prims


def test_gripper_open_idle_keeps_runtime_grip_disabled() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    body0_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5"
    stage = _FakeMultiStage([gripper_path, mimic_path, body0_path])
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "source_value": 60.0,
                    "unit": "percent",
                }
            ]
        }
    )

    assert result["runtime_grip"]["status"] == "runtime_grip_disabled"
    assert result["runtime_grip"]["enabled"] is False


def test_gripper_close_does_not_create_runtime_joint_when_grip_disabled() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    body0_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5"
    left_finger_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6"
    right_finger_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7"
    cube_path = "/World/Workspace/RedSpecimenBlock"
    grip_joint_path = "/World/RuntimeGrip/OmxTeleopGripJoint"
    stage = _FakeMultiStage([gripper_path, body0_path, left_finger_path, right_finger_path, cube_path])
    stage.prims[left_finger_path].attrs["xformOp:translate"] = _FakeAttr((0.1, 0.1, 0.03))
    stage.prims[right_finger_path].attrs["xformOp:translate"] = _FakeAttr((0.12, 0.1, 0.03))
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.4, 0.3, 0.015))
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "source_value": 52.0,
                    "unit": "percent",
                }
            ]
        }
    )

    assert result["runtime_grip"]["status"] == "runtime_grip_disabled"
    assert result["runtime_grip"]["enabled"] is False
    assert grip_joint_path not in stage.prims


def test_live_stage_apply_does_not_save_root_layer_each_sample() -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive({"joint_state": [{"isaac_joint_path": joint_path, "target_value": 8.0}]})

    assert result["ok"] is True
    assert result["status"] == "applied"
    assert stage.root_layer.save_count == 0


def test_stage_apply_clears_stale_saved_robot_runtime_state_before_live_target() -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    link_path = "/World/Robot/Geometry/link0/link1"
    stage = _FakeMultiStage([joint_path, link_path])
    stage.prims[joint_path].attrs["state:angular:physics:position"] = _FakeAttr(11.0)
    stage.prims[joint_path].attrs["state:angular:physics:velocity"] = _FakeAttr(2.0)
    stage.prims[link_path].attrs["physics:velocity"] = _FakeAttr((1.0, 2.0, 3.0))
    stage.prims[link_path].attrs["physics:angularVelocity"] = _FakeAttr((4.0, 5.0, 6.0))
    stage.prims[link_path].attrs["xformOp:orient"] = _FakeAttr((1.0, 0.0, 0.0, 0.0))
    stage.prims[link_path].attrs["xformOp:translate"] = _FakeAttr((0.0, 0.0, 0.034))
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive({"joint_state": [{"isaac_joint_path": joint_path, "target_value": 8.0}]})

    assert result["ok"] is True
    assert stage.prims[joint_path].attrs["drive:angular:physics:targetPosition"].value == 8.0
    assert stage.prims[joint_path].attrs["state:angular:physics:position"].value is None
    assert stage.prims[joint_path].attrs["state:angular:physics:velocity"].value is None
    assert stage.prims[link_path].attrs["physics:velocity"].value is None
    assert stage.prims[link_path].attrs["physics:angularVelocity"].value is None
    assert stage.prims[link_path].attrs["xformOp:orient"].value == (1.0, 0.0, 0.0, 0.0)
    assert stage.prims[link_path].attrs["xformOp:translate"].value == (0.0, 0.0, 0.034)


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
