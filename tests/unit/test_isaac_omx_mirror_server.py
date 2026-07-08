"""Tests for the Isaac OMX mirror receiver payload contract."""

from __future__ import annotations

import json
import inspect
import sys
import types
import asyncio
from pathlib import Path

import pytest

from sim.robotis_omx.tools.isaac_omx_mirror_server import (
    GRIPPER_CONTACT_COLLIDER_TOKENS,
    IsaacMirrorState,
    IsaacReplicatorRgbdRenderBackend,
    MirrorActionProcessor,
    _joint_targets,
    make_handler,
)


class _FakeAttr:
    def __init__(self, value=None, type_name="double") -> None:
        self.value = value
        self.type_name = type_name
        self.clear_count = 0
        self.set_count = 0

    def Set(self, value):  # noqa: N802 - USD-style fake
        self.value = value
        self.set_count += 1

    def Get(self):  # noqa: N802 - USD-style fake
        return self.value

    def GetTypeName(self):  # noqa: N802 - USD-style fake
        return self.type_name

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
        attr = _FakeAttr(type_name=_type_name)
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


class _FakeXformOp:
    def __init__(self, prim: _FakePrim, name: str) -> None:
        self.prim = prim
        self.name = name

    def GetOpName(self):  # noqa: N802 - USD-style fake
        return self.name

    def Set(self, value):  # noqa: N802 - USD-style fake
        attr = self.prim.attrs.get(self.name)
        if attr is None:
            attr = self.prim.CreateAttribute(self.name, "double")
        attr.Set(value)

    def GetPrecision(self):  # noqa: N802 - USD-style fake
        attr = self.prim.attrs.get(self.name)
        return getattr(attr, "type_name", "double")

    def GetAttr(self):  # noqa: N802 - USD-style fake
        return self.prim.attrs.get(self.name)


class _FakeUsdXformable:
    def __init__(self, prim: _FakePrim) -> None:
        self.prim = prim

    def GetOrderedXformOps(self):  # noqa: N802 - USD-style fake
        order_attr = self.prim.attrs.get("xformOpOrder")
        if order_attr is not None:
            names = [str(name) for name in (order_attr.Get() or [])]
        else:
            names = [name for name in self.prim.attrs if name.startswith("xformOp:")]
        return [_FakeXformOp(self.prim, name) for name in names if name in self.prim.attrs]

    def AddRotateZOp(self, precision=None):  # noqa: N802 - USD-style fake
        if "xformOp:rotateZ" not in self.prim.attrs:
            self.prim.CreateAttribute("xformOp:rotateZ", precision or "double")
        order_attr = self.prim.attrs.get("xformOpOrder")
        order = list(order_attr.Get() or []) if order_attr is not None else []
        if "xformOp:rotateZ" not in order:
            order.append("xformOp:rotateZ")
            if order_attr is None:
                order_attr = self.prim.CreateAttribute("xformOpOrder", "token[]")
            order_attr.Set(order)
        return _FakeXformOp(self.prim, "xformOp:rotateZ")

    def SetXformOpOrder(self, ops):  # noqa: N802 - USD-style fake
        order_attr = self.prim.attrs.get("xformOpOrder")
        if order_attr is None:
            order_attr = self.prim.CreateAttribute("xformOpOrder", "token[]")
        order_attr.Set([op.GetOpName() for op in ops])


def _install_fake_pxr_usdgeom(monkeypatch: pytest.MonkeyPatch) -> None:
    gf_module = types.SimpleNamespace(
        Vec3f=lambda x, y, z: ("Vec3f", x, y, z),
        Vec3d=lambda x, y, z: ("Vec3d", x, y, z),
        Quatf=lambda real, vec: ("Quatf", real, vec),
        Quatd=lambda real, vec: ("Quatd", real, vec),
    )
    usd_geom_module = types.SimpleNamespace(
        Xformable=_FakeUsdXformable,
        XformOp=types.SimpleNamespace(PrecisionFloat="float", PrecisionDouble="double"),
    )
    pxr_module = types.ModuleType("pxr")
    pxr_module.UsdGeom = usd_geom_module
    pxr_module.Gf = gf_module
    monkeypatch.setitem(sys.modules, "pxr", pxr_module)
    monkeypatch.setitem(sys.modules, "pxr.UsdGeom", usd_geom_module)
    monkeypatch.setitem(sys.modules, "pxr.Gf", gf_module)


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
            "motor_model": "xl430-w250",
            "backlash_deg": 0.25,
            "backlash_source": "xm430_w350_15_arcmin_proxy",
            "backlash_note": "Isaac mirror applies a conservative 15 arcmin X-series proxy backlash hysteresis unless a measured per-joint calibration overrides it.",
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


def test_receive_keeps_direct_joint_target_without_backlash_hysteresis() -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    first = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 11,
                    "motor_name": "shoulder_pan",
                    "isaac_joint_path": joint_path,
                    "target_value": 10.0,
                }
            ]
        }
    )
    second = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 11,
                    "motor_name": "shoulder_pan",
                    "isaac_joint_path": joint_path,
                    "target_value": 11.0,
                }
            ]
        }
    )
    third = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 11,
                    "motor_name": "shoulder_pan",
                    "isaac_joint_path": joint_path,
                    "target_value": 10.4,
                }
            ]
        }
    )

    assert first["applied_targets"][0]["target_value"] == pytest.approx(10.0)
    assert first["applied_targets"][0]["backlash_applied"] is False
    assert second["applied_targets"][0]["raw_target_value"] is None
    assert second["applied_targets"][0]["target_value"] == pytest.approx(11.0)
    assert second["applied_targets"][0]["backlash_applied"] is False
    assert second["applied_targets"][0]["backlash_direction"] is None
    assert third["applied_targets"][0]["raw_target_value"] is None
    assert third["applied_targets"][0]["target_value"] == pytest.approx(10.4)
    assert third["applied_targets"][0]["backlash_applied"] is False
    assert third["applied_targets"][0]["backlash_direction"] is None
    assert stage.prim.attrs["drive:angular:physics:targetPosition"].value == pytest.approx(10.4)


def test_specimen_pose_updates_red_cube_translate() -> None:
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([cube_path])
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.0, 0.0, 0.0))
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive_specimen_pose(
        {
            "ok": True,
            "pose": {
                "position_isaac_world_mm": {
                    "x": 123.0,
                    "y": -45.0,
                    "z": 18.5,
                }
            },
        }
    )

    assert result["ok"] is True
    assert result["status"] == "specimen_pose_applied"
    assert result["red_cube_path"] == cube_path
    assert result["translate_m"] == [0.123, -0.045, 0.0185]
    assert state.status_payload()["last_specimen_pose_result"]["translate_m"] == [0.123, -0.045, 0.0185]
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.123, -0.045, 0.0185)


def test_specimen_pose_updates_red_cube_yaw_rotate_z(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_pxr_usdgeom(monkeypatch)
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([cube_path])
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.0, 0.0, 0.0))
    stage.prims[cube_path].attrs["xformOp:scale"] = _FakeAttr((0.03, 0.03, 0.03))
    stage.prims[cube_path].attrs["xformOpOrder"] = _FakeAttr(["xformOp:translate", "xformOp:scale"])
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive_specimen_pose(
        {
            "ok": True,
            "pose": {
                "position_isaac_world_mm": {"x": 123.0, "y": -45.0, "z": 18.5},
                "orientation_deg": {"yaw": 37.5},
            },
        }
    )

    assert result["ok"] is True
    assert result["orientation_deg"]["yaw"] == 37.5
    assert stage.prims[cube_path].attrs["xformOp:rotateZ"].value == 37.5
    assert stage.prims[cube_path].attrs["xformOpOrder"].value == ["xformOp:translate", "xformOp:rotateZ", "xformOp:scale"]


def test_specimen_pose_uses_existing_orient_without_adding_second_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_pxr_usdgeom(monkeypatch)
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([cube_path])
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.0, 0.0, 0.0))
    stage.prims[cube_path].attrs["xformOp:orient"] = _FakeAttr((1.0, 0.0, 0.0, 0.0))
    stage.prims[cube_path].attrs["xformOp:rotateZ"] = _FakeAttr(12.0)
    stage.prims[cube_path].attrs["xformOp:scale"] = _FakeAttr((0.03, 0.03, 0.03))
    stage.prims[cube_path].attrs["xformOpOrder"] = _FakeAttr(
        ["xformOp:translate", "xformOp:orient", "xformOp:rotateZ", "xformOp:scale"]
    )
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive_specimen_pose(
        {
            "ok": True,
            "pose": {
                "position_isaac_world_mm": {"x": 123.0, "y": -45.0, "z": 18.5},
                "orientation_deg": {"yaw": 37.5},
            },
        }
    )

    assert result["ok"] is True
    assert result["xformOpOrder"] == ["xformOp:translate", "xformOp:orient", "xformOp:scale"]
    assert "xformOp:rotateZ" not in stage.prims[cube_path].attrs["xformOpOrder"].value
    assert stage.prims[cube_path].attrs["xformOp:orient"].value != (1.0, 0.0, 0.0, 0.0)


def test_specimen_pose_existing_float_orient_uses_quatf(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_pxr_usdgeom(monkeypatch)
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([cube_path])
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.0, 0.0, 0.0))
    stage.prims[cube_path].attrs["xformOp:orient"] = _FakeAttr((1.0, 0.0, 0.0, 0.0), type_name="float")
    stage.prims[cube_path].attrs["xformOp:scale"] = _FakeAttr((0.03, 0.03, 0.03))
    stage.prims[cube_path].attrs["xformOpOrder"] = _FakeAttr(["xformOp:translate", "xformOp:orient", "xformOp:scale"])
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive_specimen_pose(
        {
            "ok": True,
            "pose": {
                "position_isaac_world_mm": {"x": 123.0, "y": -45.0, "z": 18.5},
                "orientation_deg": {"yaw": 37.5},
            },
        }
    )

    assert result["ok"] is True
    assert stage.prims[cube_path].attrs["xformOp:orient"].value[0] == "Quatf"


def test_specimen_pose_resets_dynamic_cube_velocities() -> None:
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([cube_path])
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.0, 0.0, 0.0))
    stage.prims[cube_path].attrs["physics:velocity"] = _FakeAttr((1.0, 2.0, 3.0))
    stage.prims[cube_path].attrs["physics:angularVelocity"] = _FakeAttr((4.0, 5.0, 6.0))
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: stage)

    result = state.receive_specimen_pose(
        {
            "ok": True,
            "pose": {
                "position_isaac_world_mm": {
                    "x": 123.0,
                    "y": -45.0,
                    "z": 18.5,
                }
            },
        }
    )

    assert result["ok"] is True
    assert result["velocity_reset"] is True
    assert stage.prims[cube_path].attrs["physics:velocity"].value == (0.0, 0.0, 0.0)
    assert stage.prims[cube_path].attrs["physics:angularVelocity"].value == (0.0, 0.0, 0.0)


def test_deferred_specimen_pose_queues_until_update_tick() -> None:
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([cube_path])
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.0, 0.0, 0.0))
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=True, stage_provider=lambda: stage)

    queued = state.receive_specimen_pose(
        {
            "ok": True,
            "pose": {
                "position_isaac_world_mm": {
                    "x": 11.0,
                    "y": 22.0,
                    "z": 33.0,
                }
            },
        }
    )

    assert queued["ok"] is True
    assert queued["status"] == "specimen_pose_queued"
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.0, 0.0, 0.0)

    applied = state.apply_latest_pending()

    assert applied["ok"] is True
    assert applied["status"] == "specimen_pose_applied"
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.011, 0.022, 0.033)


def test_handler_accepts_specimen_pose_endpoint() -> None:
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: _FakeMultiStage([]))
    handler = make_handler(state)

    response_source = inspect.getsource(handler._json_response)
    source = inspect.getsource(handler.do_POST)
    assert "BrokenPipeError" in response_source
    assert "ConnectionResetError" in response_source
    assert "/specimen_pose" in source
    assert "receive_specimen_pose" in source
    assert "/viewport/frame" in source
    assert "receive_viewport_frame" in source


def test_deferred_viewport_frame_request_runs_on_update_tick() -> None:
    calls: list[dict[str, object]] = []
    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=True,
        stage_provider=lambda: _FakeMultiStage(["/World/Robot", "/World/Workspace", "/World/Unused"]),
        viewport_frame_callback=lambda *, stage, prim_paths, reason: calls.append(
            {"stage": stage, "prim_paths": list(prim_paths), "reason": reason}
        )
        or {"ok": True, "status": "viewport_framed", "prim_paths": list(prim_paths), "reason": reason},
    )

    queued = state.receive_viewport_frame({"reason": "teleoperate_start"})
    status = state.status_payload()
    applied = state.apply_pending_viewport_frame()

    assert queued["ok"] is True
    assert queued["status"] == "viewport_frame_queued"
    assert status["pending_viewport_frame"] is True
    assert applied["ok"] is True
    assert applied["status"] == "viewport_framed"
    assert calls == [
        {
            "stage": state.stage,
            "prim_paths": ["/World/Robot", "/World/Workspace"],
            "reason": "teleoperate_start",
        }
    ]
    assert state.status_payload()["pending_viewport_frame"] is False
    assert state.status_payload()["last_viewport_frame_result"]["status"] == "viewport_framed"


def test_deferred_timeline_play_request_runs_on_update_tick(tmp_path: Path) -> None:
    calls: list[str] = []
    state = IsaacMirrorState(
        tmp_path / "scene.usda",
        defer_apply=True,
        timeline_play_callback=lambda *, reason: calls.append(reason) or {"ok": True, "status": "playing:True", "reason": reason},
    )

    queued = state.receive_timeline_play({"reason": "record_start"})
    status = state.status_payload()
    applied = state.apply_pending_timeline_play()

    assert queued["ok"] is True
    assert queued["status"] == "timeline_play_queued"
    assert status["pending_timeline_play"] is True
    assert applied["ok"] is True
    assert applied["status"] == "playing:True"
    assert calls == ["record_start"]
    assert state.status_payload()["pending_timeline_play"] is False
    assert state.status_payload()["last_timeline_play_result"]["reason"] == "record_start"


def test_timeline_play_request_forwards_specimen_pose_skip_flag(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    state = IsaacMirrorState(
        tmp_path / "scene.usda",
        timeline_play_callback=lambda **kwargs: calls.append(dict(kwargs)) or {"ok": True, "status": "playing:True", **kwargs},
    )

    result = state.receive_timeline_play(
        {
            "reason": "isaac_rgbd_post_render_preplay",
            "skip_specimen_pose_on_play": True,
        }
    )

    assert result["ok"] is True
    assert result["status"] == "playing:True"
    assert result["skip_specimen_pose_on_play"] is True
    assert calls == [
        {
            "reason": "isaac_rgbd_post_render_preplay",
            "skip_specimen_pose_on_play": True,
        }
    ]


def test_deferred_timeline_stop_request_runs_on_update_tick(tmp_path: Path) -> None:
    calls: list[str] = []
    state = IsaacMirrorState(
        tmp_path / "scene.usda",
        defer_apply=True,
        timeline_stop_callback=lambda *, reason: calls.append(reason) or {"ok": True, "status": "stopped:True", "reason": reason},
    )

    queued = state.receive_timeline_stop({"reason": "post_render_next_episode"})
    status = state.status_payload()
    applied = state.apply_pending_timeline_stop()

    assert queued["ok"] is True
    assert queued["status"] == "timeline_stop_queued"
    assert status["pending_timeline_stop"] is True
    assert applied["ok"] is True
    assert applied["status"] == "stopped:True"
    assert calls == ["post_render_next_episode"]
    assert state.status_payload()["pending_timeline_stop"] is False
    assert state.status_payload()["last_timeline_stop_result"]["reason"] == "post_render_next_episode"


def test_deferred_stop_specimen_pose_play_apply_in_replay_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([cube_path])
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.0, 0.0, 0.0))
    state = IsaacMirrorState(
        tmp_path / "scene.usda",
        defer_apply=True,
        stage_provider=lambda: stage,
        timeline_stop_callback=lambda *, reason: order.append("stop") or {"ok": True, "status": "stopped:True", "reason": reason},
        timeline_play_callback=lambda *, reason: order.append("play") or {"ok": True, "status": "playing:True", "reason": reason},
    )
    original_apply_specimen_pose = state.apply_specimen_pose

    def apply_specimen_pose_with_order(payload: dict[str, object]) -> dict[str, object]:
        order.append("specimen")
        return original_apply_specimen_pose(payload)  # type: ignore[return-value]

    monkeypatch.setattr(state, "apply_specimen_pose", apply_specimen_pose_with_order)

    state.receive_timeline_stop({"reason": "post_render_next_episode"})
    state.receive_specimen_pose({"pose": {"position_isaac_world_mm": {"x": 123.0, "y": 45.0, "z": 15.2}}})
    state.receive_timeline_play({"reason": "post_render_replay"})

    applied = state.apply_latest_pending()

    assert applied["ok"] is True
    assert order == ["stop", "specimen", "play"]
    assert stage.prims[cube_path].attrs["xformOp:translate"].value == (0.123, 0.045, 0.0152)


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


def test_gripper_action_processing_is_centralized_on_mirror_action_processor() -> None:
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: _FakeMultiStage([]))

    assert isinstance(state.action_processor, MirrorActionProcessor)


def test_gripper_effort_limit_keeps_base_force_until_contact_is_reliable() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([gripper_path, mimic_path, cube_path])
    stage.prims[cube_path].attrs["physics:mass"] = _FakeAttr(0.03)
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
    assert result["action_processing"]["processor"] == "MirrorActionProcessor"
    assert result["gripper_effort_limit"]["status"] == "stable_drive_effort"
    assert result["gripper_effort_limit"]["object_mass_kg"] == pytest.approx(0.03)
    assert result["gripper_effort_limit"]["mass_scaled_effort_limit"] == pytest.approx(0.2)
    assert result["gripper_effort_limit"]["effort_limit"] == pytest.approx(4.0)
    assert result["applied_targets"][0]["drive_max_force"] == pytest.approx(4.0)
    assert stage.prims[gripper_path].attrs["drive:angular:physics:maxForce"].value == pytest.approx(4.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:maxForce"].value == pytest.approx(4.0)


def test_gripper_effort_limit_keeps_stable_drive_force_when_contact_is_reliable() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([gripper_path, mimic_path, cube_path])
    stage.prims[cube_path].attrs["physics:mass"] = _FakeAttr(0.03)
    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=False,
        stage_provider=lambda: stage,
        contact_force_provider=lambda _stage: {
            "available": True,
            "contact": True,
            "force_n": 0.5,
            "penetration_m": 0.0,
            "matched_pairs": 1,
        },
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
                    "target_value": 60.0,
                    "source_value": 60.0,
                    "unit": "percent",
                }
            ]
        }
    )

    assert result["ok"] is True
    assert result["action_processing"]["processor"] == "MirrorActionProcessor"
    assert result["gripper_effort_limit"]["status"] == "stable_drive_effort"
    assert result["gripper_effort_limit"]["contact_reliable"] is True
    assert result["gripper_effort_limit"]["mass_scaled_effort_limit"] == pytest.approx(0.2)
    assert result["gripper_effort_limit"]["effort_limit"] == pytest.approx(4.0)
    assert result["applied_targets"][0]["drive_max_force"] == pytest.approx(4.0)
    assert stage.prims[gripper_path].attrs["drive:angular:physics:maxForce"].value == pytest.approx(4.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:maxForce"].value == pytest.approx(4.0)


def test_gripper_action_processing_reports_grasp_diagnostics() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    left_finger_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/InnerGripPadCollision"
    right_finger_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/InnerGripPadCollision"
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([gripper_path, mimic_path, left_finger_path, right_finger_path, cube_path])
    stage.prims[left_finger_path].attrs["xformOp:translate"] = _FakeAttr((0.39, 0.3, 0.03))
    stage.prims[right_finger_path].attrs["xformOp:translate"] = _FakeAttr((0.41, 0.3, 0.03))
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.4, 0.3, 0.015))
    stage.prims[cube_path].attrs["physics:mass"] = _FakeAttr(0.03)
    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=False,
        stage_provider=lambda: stage,
        contact_force_provider=lambda _stage: {
            "available": True,
            "contact": True,
            "force_n": 0.4,
            "penetration_m": 0.0,
            "matched_pairs": 2,
        },
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

    diagnostics = result["grasp_diagnostics"]
    assert diagnostics["available"] is True
    assert diagnostics["status"] == "grasp_candidate"
    assert diagnostics["object_path"] == cube_path
    assert diagnostics["object_position"] == [0.4, 0.3, 0.015]
    assert diagnostics["finger_count"] == 2
    assert diagnostics["gripper_closed"] is True
    assert diagnostics["near_object"] is True
    assert diagnostics["contact"] is True
    assert diagnostics["min_finger_distance_m"] == pytest.approx(0.01803, rel=1e-3)
    assert result["action_processing"]["grasp_status"] == "grasp_candidate"


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


def test_contact_report_tracks_single_side_but_does_not_accept_contact(monkeypatch: pytest.MonkeyPatch) -> None:
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

    assert result["contact"] is False
    assert result["raw_contact"] is True
    assert result["both_sides_contact"] is False
    assert result["gripper_contact_sides"] == ["primary"]
    assert result["force_n"] == pytest.approx(5.0)
    assert result["penetration_m"] == pytest.approx(0.0012)
    assert result["matched_pairs"] == 1
    assert result["matched_pair_paths"] == [{"collider0": gripper_path, "collider1": cube_path}]


def test_contact_report_accepts_contact_only_when_both_gripper_sides_touch(monkeypatch: pytest.MonkeyPatch) -> None:
    primary_path = (
        "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/"
        "follower_07_gripper_motorized_1/follower_07_gripper_motorized"
    )
    mimic_path = (
        "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/"
        "follower_08_gripper_gear_1/follower_08_gripper_gear"
    )
    cube_path = "/World/Workspace/RedSpecimenBlock"
    headers = [
        types.SimpleNamespace(
            collider0=primary_path,
            collider1=cube_path,
            contact_data_offset=0,
            num_contact_data=1,
        ),
        types.SimpleNamespace(
            collider0=mimic_path,
            collider1=cube_path,
            contact_data_offset=1,
            num_contact_data=1,
        ),
    ]
    contacts = [
        types.SimpleNamespace(impulse=(0.0, 0.03, 0.0), separation=0.0),
        types.SimpleNamespace(impulse=(0.0, 0.04, 0.0), separation=-0.0007),
    ]

    class _FakePhysxInterface:
        def get_contact_report(self):
            return headers, contacts

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
    assert result["raw_contact"] is True
    assert result["both_sides_contact"] is True
    assert result["gripper_contact_sides"] == ["primary", "mimic"]
    assert result["force_n"] == pytest.approx(4.0)
    assert result["penetration_m"] == pytest.approx(0.0007)
    assert result["matched_pairs"] == 2
    assert result["matched_pair_paths"] == [
        {"collider0": primary_path, "collider1": cube_path},
        {"collider0": mimic_path, "collider1": cube_path},
    ]


def test_contact_report_matches_actor_paths_when_collider_paths_are_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    gripper_path = (
        "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/"
        "follower_08_gripper_gear_1/follower_08_gripper_gear"
    )
    cube_path = "/World/Workspace/RedSpecimenBlock"
    header = types.SimpleNamespace(
        actor0=gripper_path,
        actor1=cube_path,
        contact_data_offset=0,
        num_contact_data=1,
    )
    contact = types.SimpleNamespace(impulse=(0.0, 0.03, 0.04), separation=0.0)

    class _FakePhysxInterface:
        def get_contact_report(self):
            return [header], [contact]

    physx_module = types.ModuleType("omni.physx")
    physx_module.get_physx_simulation_interface = lambda: _FakePhysxInterface()
    omni_module = types.ModuleType("omni")
    omni_module.physx = physx_module
    monkeypatch.setitem(sys.modules, "omni", omni_module)
    monkeypatch.setitem(sys.modules, "omni.physx", physx_module)

    class _FakeSdfPath:
        def __init__(self, value: str) -> None:
            self.value = value

        def __str__(self) -> str:
            return f"Sdf.Path('{self.value}')"

    class _FakePhysicsSchemaTools:
        @staticmethod
        def intToSdfPath(value):  # noqa: N802 - USD-style fake
            return _FakeSdfPath(value)

    pxr_module = types.ModuleType("pxr")
    pxr_module.PhysicsSchemaTools = _FakePhysicsSchemaTools
    monkeypatch.setitem(sys.modules, "pxr", pxr_module)

    state = IsaacMirrorState(Path("scene.usda"), defer_apply=False, stage_provider=lambda: _FakeMultiStage([]))

    result = state._poll_gripper_contact_force(None)

    assert result["contact"] is False
    assert result["raw_contact"] is True
    assert result["both_sides_contact"] is False
    assert result["gripper_contact_sides"] == ["mimic"]
    assert result["force_n"] == pytest.approx(12.0)
    assert result["matched_pairs"] == 1
    assert result["matched_pair_paths"] == [{"actor0": gripper_path, "actor1": cube_path}]


def test_gripper_close_target_is_not_probe_limited_without_contact_force() -> None:
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
    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(0.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-0.0)
    assert result["applied_targets"][0]["slew_limited"] is False
    assert result["applied_targets"][0]["raw_target_value"] == pytest.approx(0.0)
    assert result["applied_targets"][0]["contact_probe_limited"] is False
    assert result["applied_targets"][0]["contact_hold_active"] is False
    assert result["gripper_contact"]["hold_active"] is False


def test_gripper_contact_force_latches_hold_and_still_releases_when_opening() -> None:
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

    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == 0.0
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == -0.0
    assert contact_result["gripper_contact"]["contact"] is True
    assert contact_result["gripper_contact"]["force_n"] == pytest.approx(18.0)
    assert contact_result["gripper_contact"]["hold_active"] is True
    assert contact_result["gripper_contact"]["hold_reason"] == "contact_hold_armed"
    assert contact_result["gripper_contact"]["hold_target_value"] == pytest.approx(-1.0)
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

    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == 0.0
    assert held_result["gripper_contact"]["hold_active"] is True
    assert held_result["gripper_contact"]["hold_reason"] == "contact_hold_tracking"
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

    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == 36.0
    assert open_result["gripper_contact"]["hold_active"] is False
    assert open_result["gripper_contact"]["hold_reason"] == "released_opening"
    assert open_result["gripper_contact"]["hold_target_value"] is None


def test_gripper_contact_hold_clamps_close_command_until_operator_opens() -> None:
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
                    "target_value": 20.0,
                }
            ]
        }
    )

    contact_state.update({"contact": True, "force_n": 0.4})
    contact_result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "target_value": 15.0,
                }
            ]
        }
    )

    assert contact_result["gripper_contact"]["hold_active"] is True
    assert contact_result["gripper_contact"]["hold_reason"] == "contact_hold_armed"
    assert contact_result["gripper_contact"]["hold_target_value"] == pytest.approx(14.0)
    assert contact_result["applied_targets"][0]["contact_hold_active"] is True
    assert contact_result["applied_targets"][0]["contact_hold_target_value"] == pytest.approx(14.0)
    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(15.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-15.0)

    close_result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "target_value": 10.0,
                }
            ]
        }
    )

    assert close_result["gripper_contact"]["hold_active"] is True
    assert close_result["gripper_contact"]["hold_reason"] == "contact_hold_clamped"
    assert close_result["applied_targets"][0]["raw_target_value"] == pytest.approx(10.0)
    assert close_result["applied_targets"][0]["target_value"] == pytest.approx(14.0)
    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(14.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-14.0)

    open_result = state.receive(
        {
            "joint_state": [
                {
                    "motor_id": 16,
                    "motor_name": "gripper",
                    "isaac_joint_name": "Gripper",
                    "isaac_joint_path": gripper_path,
                    "mimic_joint_path": mimic_path,
                    "target_value": 16.0,
                }
            ]
        }
    )

    assert open_result["gripper_contact"]["hold_active"] is False
    assert open_result["gripper_contact"]["hold_reason"] == "released_opening"
    assert open_result["gripper_contact"]["hold_target_value"] is None
    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(16.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-16.0)


def test_gripper_contact_hold_uses_reliable_contact_without_force_threshold() -> None:
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

    contact_state.update({"contact": True, "force_n": 3.0})
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

    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == 0.0
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == -0.0
    assert result["gripper_contact"]["hold_active"] is True
    assert result["gripper_contact"]["hold_reason"] == "contact_hold_armed"
    assert result["gripper_contact"]["hold_target_value"] == pytest.approx(-1.0)
    assert result["gripper_contact"]["probe_limited"] is False
    assert result["applied_targets"][0]["contact_probe_limited"] is False
    assert result["applied_targets"][0]["contact_hold_active"] is True


def test_gripper_contact_pair_without_force_does_not_hold_target() -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    stage = _FakeMultiStage([gripper_path, mimic_path])
    contact_state = {
        "available": True,
        "contact": False,
        "force_n": 0.0,
        "matched_pairs": 0,
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

    contact_state.update({"contact": True, "matched_pairs": 1, "force_n": 0.0})
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

    assert contact_result["gripper_contact"]["contact"] is True
    assert contact_result["gripper_contact"]["matched_pairs"] == 1
    assert contact_result["gripper_contact"]["hold_active"] is False
    assert contact_result["gripper_contact"]["hold_reason"] == ""
    assert contact_result["gripper_contact"]["hold_target_value"] is None
    assert contact_result["applied_targets"][0]["contact_hold_active"] is False
    assert contact_result["applied_targets"][0]["contact_probe_limited"] is False


def test_gripper_contact_penetration_is_reported_without_backoff_target() -> None:
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

    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(0.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-0.0)
    assert result["gripper_contact"]["contact"] is True
    assert result["gripper_contact"]["penetration_m"] == pytest.approx(0.0012)
    assert result["gripper_contact"]["hold_active"] is True
    assert result["gripper_contact"]["hold_reason"] == "contact_hold_armed"
    assert result["gripper_contact"]["hold_target_value"] == pytest.approx(-1.0)
    assert result["applied_targets"][0]["contact_hold_active"] is True
    assert result["applied_targets"][0]["contact_penetration_limited"] is False


def test_gripper_contact_state_does_not_latch_after_contact_is_lost() -> None:
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
    assert held["gripper_contact"]["contact"] is True
    assert held["gripper_contact"]["hold_active"] is True
    assert held["gripper_contact"]["hold_reason"] == "contact_hold_armed"
    assert held["gripper_contact"]["hold_target_value"] == pytest.approx(34.2)

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
    assert released["gripper_contact"]["hold_reason"] == "released_opening"
    assert released["gripper_contact"]["hold_target_value"] is None
    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(35.9)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-35.9)


def test_gripper_contact_hold_releases_when_contact_is_lost_before_closing_more() -> None:
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
    assert held["gripper_contact"]["hold_target_value"] == pytest.approx(34.2)

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
                    "target_value": 20.0,
                }
            ]
        }
    )

    assert released["gripper_contact"]["hold_active"] is False
    assert released["gripper_contact"]["hold_reason"] == "released_contact_lost"
    assert released["gripper_contact"]["hold_target_value"] is None
    assert stage.prims[gripper_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(20.0)
    assert stage.prims[mimic_path].attrs["drive:angular:physics:targetPosition"].value == pytest.approx(-20.0)


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


def test_receive_writes_rgbd_render_manifest_for_deferred_samples(tmp_path: Path) -> None:
    output_dir = tmp_path / "isaac_rgbd" / "episode_000" / "attempt_one"
    state = IsaacMirrorState(Path("scene.usda"), defer_apply=True, stage_provider=lambda: None)

    result = state.receive(
        {
            "session_id": "lr-record-1",
            "sample_index": 4,
            "timestamp": "2026-06-28T00:00:00+00:00",
            "joint_state": [],
            "render_request": {
                "schema": "atr.isaac_rgbd.render_request.v1",
                "enabled": True,
                "attempt_id": "attempt_one",
                "episode_index": 0,
                "frame_index": 3,
                "sample_index": 4,
                "timestamp": "2026-06-28T00:00:00+00:00",
                "target_fps": 15.0,
                "cameras": ["wrist", "top"],
                "output_dir": str(output_dir),
            },
        }
    )

    assert result["ok"] is True
    assert result["render_request"]["status"] == "metadata_only"
    manifest_path = output_dir / "manifest.jsonl"
    row = json.loads(manifest_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["schema"] == "atr.isaac_rgbd.render_manifest.v1"
    assert row["attempt_id"] == "attempt_one"
    assert row["sample_index"] == 4
    assert row["target_fps"] == 15.0
    assert row["cameras"] == ["wrist", "top"]
    assert state.status_payload()["last_render_request_result"]["manifest_path"] == str(manifest_path)


def test_deferred_update_tick_renders_rgbd_files_after_joint_apply(tmp_path: Path) -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    output_dir = tmp_path / "isaac_rgbd" / "episode_000" / "attempt_rendered"
    backend_calls: list[dict[str, object]] = []

    def fake_rgbd_backend(*, request: dict[str, object], output_dir: Path, stage: object, payload: dict[str, object]) -> dict[str, object]:
        backend_calls.append({"request": request, "output_dir": output_dir, "stage": stage, "payload": payload})
        files: list[dict[str, object]] = []
        frame_index = int(request["frame_index"])
        for camera in request["cameras"]:  # type: ignore[index]
            camera_dir = output_dir / str(camera)
            camera_dir.mkdir(parents=True, exist_ok=True)
            rgb_path = camera_dir / f"frame_{frame_index:06d}_rgb.png"
            depth_path = camera_dir / f"frame_{frame_index:06d}_depth.png"
            rgb_path.write_bytes(b"fake-rgb")
            depth_path.write_bytes(b"fake-depth")
            files.extend(
                [
                    {"camera": camera, "kind": "rgb", "path": str(rgb_path), "encoding": "png"},
                    {"camera": camera, "kind": "depth", "path": str(depth_path), "encoding": "png16"},
                ]
            )
        return {"ok": True, "status": "rendered", "backend": "fake_rgbd", "files": files}

    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=True,
        stage_provider=lambda: stage,
        rgbd_render_backend=fake_rgbd_backend,
    )

    state.receive(
        {
            "session_id": "lr-record-rendered",
            "sample_index": 5,
            "timestamp": "2026-06-28T00:00:01+00:00",
            "joint_state": [{"isaac_joint_path": joint_path, "target_value": 11.0}],
            "render_request": {
                "schema": "atr.isaac_rgbd.render_request.v1",
                "enabled": True,
                "attempt_id": "attempt_rendered",
                "episode_index": 0,
                "frame_index": 4,
                "sample_index": 5,
                "timestamp": "2026-06-28T00:00:01+00:00",
                "target_fps": 15.0,
                "cameras": ["wrist", "top"],
                "output_dir": str(output_dir),
            },
        }
    )

    result = state.apply_latest_pending()

    assert result["ok"] is True
    assert stage.prim.attrs["drive:angular:physics:targetPosition"].value == 11.0
    assert result["render_request"]["status"] == "rendered"
    assert result["render_request"]["backend"] == "fake_rgbd"
    assert len(result["render_request"]["files"]) == 4
    assert backend_calls[0]["stage"] is stage
    for file_info in result["render_request"]["files"]:
        assert Path(str(file_info["path"])).is_file()
    rows = [json.loads(line) for line in (output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "metadata_only"
    assert rows[-1]["status"] == "rendered"
    assert rows[-1]["backend"] == "fake_rgbd"
    assert len(rows[-1]["files"]) == 4


def test_receive_render_applies_specimen_pose_before_rgbd_backend(tmp_path: Path) -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([joint_path, cube_path])
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.0, 0.0, 0.0))
    output_dir = tmp_path / "isaac_rgbd" / "episode_000" / "attempt_pose_render"
    backend_cube_translates: list[tuple[float, float, float]] = []

    def fake_rgbd_backend(*, request: dict[str, object], output_dir: Path, stage: object, payload: dict[str, object]) -> dict[str, object]:
        del request, payload
        cube = stage.GetPrimAtPath(cube_path)  # type: ignore[attr-defined]
        backend_cube_translates.append(tuple(cube.attrs["xformOp:translate"].value))
        camera_dir = output_dir / "top"
        camera_dir.mkdir(parents=True, exist_ok=True)
        rgb_path = camera_dir / "frame_000000_rgb.png"
        rgb_path.write_bytes(b"fake-rgb")
        return {
            "ok": True,
            "status": "rendered",
            "backend": "fake_rgbd",
            "files": [{"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"}],
        }

    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=False,
        stage_provider=lambda: stage,
        rgbd_render_backend=fake_rgbd_backend,
    )

    result = state.receive_render(
        {
            "session_id": "lr-record-pose-render",
            "sample_index": 1,
            "joint_state": [{"isaac_joint_path": joint_path, "target_value": 11.0}],
            "specimen_pose": {
                "source_path": "/dataset/sidecar/attempts/episode_000/attempt_pose_render/specimen_pose.json",
                "pose": {
                    "position_isaac_world_mm": {"x": 417.0, "y": 311.0, "z": 15.2},
                },
            },
            "render_request": {
                "schema": "atr.isaac_rgbd.render_request.v1",
                "enabled": True,
                "attempt_id": "attempt_pose_render",
                "episode_index": 0,
                "frame_index": 0,
                "sample_index": 1,
                "target_fps": 15.0,
                "cameras": ["top"],
                "output_dir": str(output_dir),
            },
        }
    )

    assert result["ok"] is True
    assert result["specimen_pose"]["status"] == "specimen_pose_applied"
    assert backend_cube_translates == [(0.417, 0.311, 0.0152)]
    assert stage.prims[joint_path].attrs["drive:angular:physics:targetPosition"].value == 11.0
    rows = [json.loads(line) for line in (output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["specimen_pose"]["source_path"].endswith("specimen_pose.json")
    assert rows[-1]["specimen_pose"]["translate_m"] == [0.417, 0.311, 0.0152]


def test_rgbd_render_manifest_records_action_processing_metadata(tmp_path: Path) -> None:
    gripper_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/Gripper"
    mimic_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/Gripper_mimic"
    left_finger_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link6/InnerGripPadCollision"
    right_finger_path = "/World/Robot/Geometry/link0/link1/link2/link3/link4/link5/link7/InnerGripPadCollision"
    cube_path = "/World/Workspace/RedSpecimenBlock"
    stage = _FakeMultiStage([gripper_path, mimic_path, left_finger_path, right_finger_path, cube_path])
    stage.prims[left_finger_path].attrs["xformOp:translate"] = _FakeAttr((0.39, 0.3, 0.03))
    stage.prims[right_finger_path].attrs["xformOp:translate"] = _FakeAttr((0.41, 0.3, 0.03))
    stage.prims[cube_path].attrs["xformOp:translate"] = _FakeAttr((0.4, 0.3, 0.015))
    stage.prims[cube_path].attrs["physics:mass"] = _FakeAttr(0.03)
    output_dir = tmp_path / "isaac_rgbd" / "episode_000" / "attempt_action_metadata"

    def fake_rgbd_backend(*, request: dict[str, object], output_dir: Path, stage: object, payload: dict[str, object]) -> dict[str, object]:
        camera_dir = output_dir / "top"
        camera_dir.mkdir(parents=True, exist_ok=True)
        rgb_path = camera_dir / "frame_000000_rgb.png"
        rgb_path.write_bytes(b"fake-rgb")
        return {
            "ok": True,
            "status": "rendered",
            "backend": "fake_rgbd",
            "files": [{"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"}],
        }

    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=False,
        stage_provider=lambda: stage,
        contact_force_provider=lambda _stage: {
            "available": True,
            "contact": True,
            "force_n": 0.4,
            "penetration_m": 0.0,
            "matched_pairs": 2,
        },
        rgbd_render_backend=fake_rgbd_backend,
    )

    result = state.receive(
        {
            "session_id": "lr-record-action-metadata",
            "sample_index": 1,
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
            ],
            "render_request": {
                "schema": "atr.isaac_rgbd.render_request.v1",
                "enabled": True,
                "attempt_id": "attempt_action_metadata",
                "episode_index": 0,
                "frame_index": 0,
                "sample_index": 1,
                "target_fps": 15.0,
                "cameras": ["top"],
                "output_dir": str(output_dir),
            },
        }
    )

    assert result["ok"] is True
    rows = [json.loads(line) for line in (output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    row = rows[-1]
    assert row["status"] == "rendered"
    assert row["action_processing"]["processor"] == "MirrorActionProcessor"
    assert row["action_processing"]["grasp_status"] == "grasp_candidate"
    assert row["gripper_effort_limit"]["status"] == "stable_drive_effort"
    assert row["grasp_diagnostics"]["status"] == "grasp_candidate"
    assert row["grasp_diagnostics"]["contact"] is True


def test_deferred_render_jobs_keep_latest_frame_and_stay_separate_from_latest_joint_sample(tmp_path: Path) -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    output_dir = tmp_path / "isaac_rgbd" / "episode_000" / "attempt_fifo"
    rendered_frames: list[int] = []

    def fake_rgbd_backend(*, request: dict[str, object], output_dir: Path, stage: object, payload: dict[str, object]) -> dict[str, object]:
        frame_index = int(request["frame_index"])
        rendered_frames.append(frame_index)
        camera_dir = output_dir / "top"
        camera_dir.mkdir(parents=True, exist_ok=True)
        rgb_path = camera_dir / f"frame_{frame_index:06d}_rgb.png"
        rgb_path.write_bytes(f"rgb-{frame_index}".encode("utf-8"))
        return {
            "ok": True,
            "status": "rendered",
            "backend": "fake_rgbd",
            "files": [{"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"}],
        }

    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=True,
        stage_provider=lambda: stage,
        rgbd_render_backend=fake_rgbd_backend,
    )
    base_request = {
        "schema": "atr.isaac_rgbd.render_request.v1",
        "enabled": True,
        "attempt_id": "attempt_fifo",
        "episode_index": 0,
        "target_fps": 15.0,
        "cameras": ["top"],
        "output_dir": str(output_dir),
    }

    first = state.receive_render(
        {
            "sample_index": 1,
            "joint_state": [{"isaac_joint_path": joint_path, "target_value": 11.0}],
            "render_request": {**base_request, "frame_index": 0, "sample_index": 1},
        }
    )
    second = state.receive_render(
        {
            "sample_index": 2,
            "joint_state": [{"isaac_joint_path": joint_path, "target_value": 12.0}],
            "render_request": {**base_request, "frame_index": 1, "sample_index": 2},
        }
    )
    state.receive({"sample_index": 99, "joint_state": [{"isaac_joint_path": joint_path, "target_value": 99.0}]})

    assert first["status"] == "render_queued"
    assert second["status"] == "render_queued_replaced_stale"
    assert second["pending_render_jobs"] == 1
    assert state.status_payload()["pending_render_jobs"] == 1

    latest = state.apply_latest_pending()
    assert latest["ok"] is True
    assert "render_request" not in latest
    assert stage.prim.attrs["drive:angular:physics:targetPosition"].value == 99.0

    render_one = state.apply_next_render_job()
    render_idle = state.apply_next_render_job()

    assert render_one["render_request"]["frame_index"] == 1
    assert render_idle["status"] == "render_idle"
    assert rendered_frames == [1]
    assert state.status_payload()["pending_render_jobs"] == 0
    rows = [json.loads(line) for line in (output_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["frame_index"] for row in rows] == [1]
    assert all(row["status"] == "rendered" for row in rows)


def test_deferred_render_jobs_wait_for_async_render_finalize_before_popping_next(tmp_path: Path) -> None:
    joint_path = "/World/Robot/Geometry/link0/link1/Joint1"
    stage = _FakeStage(joint_path)
    output_dir = tmp_path / "isaac_rgbd" / "episode_000" / "attempt_async_fifo"
    backend_calls: list[tuple[int, bool]] = []

    def fake_rgbd_backend(*, request: dict[str, object], output_dir: Path, stage: object, payload: dict[str, object]) -> dict[str, object]:
        frame_index = int(request["frame_index"])
        finalize = bool(request.get("_atr_finalize_after_async_step"))
        backend_calls.append((frame_index, finalize))
        if not finalize:
            return {
                "ok": True,
                "status": "render_pending",
                "backend": "fake_async_rgbd",
                "files": [],
                "pending_key": f"frame-{frame_index}",
                "step_mode": "async_scheduled",
            }
        camera_dir = output_dir / "top"
        camera_dir.mkdir(parents=True, exist_ok=True)
        rgb_path = camera_dir / f"frame_{frame_index:06d}_rgb.png"
        rgb_path.write_bytes(f"rgb-{frame_index}".encode("utf-8"))
        return {
            "ok": True,
            "status": "rendered",
            "backend": "fake_async_rgbd",
            "files": [{"camera": "top", "kind": "rgb", "path": str(rgb_path), "encoding": "png"}],
        }

    state = IsaacMirrorState(
        Path("scene.usda"),
        defer_apply=True,
        stage_provider=lambda: stage,
        rgbd_render_backend=fake_rgbd_backend,
    )
    base_request = {
        "schema": "atr.isaac_rgbd.render_request.v1",
        "enabled": True,
        "attempt_id": "attempt_async_fifo",
        "episode_index": 0,
        "target_fps": 15.0,
        "cameras": ["top"],
        "output_dir": str(output_dir),
    }
    state.receive_render(
        {
            "sample_index": 1,
            "joint_state": [{"isaac_joint_path": joint_path, "target_value": 11.0}],
            "render_request": {**base_request, "frame_index": 0, "sample_index": 1},
        }
    )

    first = state.apply_next_render_job()
    state.receive_render(
        {
            "sample_index": 2,
            "joint_state": [{"isaac_joint_path": joint_path, "target_value": 12.0}],
            "render_request": {**base_request, "frame_index": 1, "sample_index": 2},
        }
    )
    waiting = state.apply_next_render_job()
    finalized = state.finalize_pending_render()
    second = state.apply_next_render_job()

    assert first["render_request"]["status"] == "render_pending"
    assert waiting["status"] == "render_waiting_for_async_step"
    assert waiting["pending_render_jobs"] == 1
    assert finalized["status"] == "rendered"
    assert finalized["frame_index"] == 0
    assert second["render_request"]["status"] == "render_pending"
    assert backend_calls == [(0, False), (0, True), (1, False)]


def test_rgbd_render_backend_uses_camera_specs_as_distinct_render_resources() -> None:
    class _FakeAnnotator:
        def attach(self, _render_product) -> None:
            return None

    class _FakeAnnotatorRegistry:
        @staticmethod
        def get_annotator(_name: str) -> _FakeAnnotator:
            return _FakeAnnotator()

    class _FakeRep:
        def __init__(self) -> None:
            self.camera_calls: list[dict[str, object]] = []
            self.render_products: list[object] = []
            self.functional = types.SimpleNamespace(create=types.SimpleNamespace(camera=self._camera))
            self.create = types.SimpleNamespace(render_product=self._render_product)
            self.annotators = types.SimpleNamespace(get=lambda _name: _FakeAnnotator())
            self.AnnotatorRegistry = _FakeAnnotatorRegistry

        def _camera(self, **kwargs):
            self.camera_calls.append(kwargs)
            return f"{kwargs['parent']}/{kwargs['name']}"

        def _render_product(self, camera, resolution, name):
            product = {"camera": camera, "resolution": resolution, "name": name}
            self.render_products.append(product)
            return product

    backend = IsaacReplicatorRgbdRenderBackend()
    rep = _FakeRep()
    stage = _FakeMultiStage([])
    first = {"camera_specs": {"wrist": {"position": [0.2, 0.1, 0.3], "look_at": [0.36, 0.28, 0.02]}}}
    second = {"camera_specs": {"wrist": {"position": [0.23, 0.1, 0.32], "look_at": [0.36, 0.28, 0.02]}}}

    one = backend._resource_for_camera(rep, stage, "wrist", first, (640, 480))
    one_again = backend._resource_for_camera(rep, stage, "wrist", first, (640, 480))
    two = backend._resource_for_camera(rep, stage, "wrist", second, (640, 480))

    assert one["ok"] is True
    assert one_again is one
    assert two["ok"] is True
    assert len(rep.camera_calls) == 2
    assert rep.camera_calls[0]["position"] == (0.2, 0.1, 0.3)
    assert rep.camera_calls[1]["position"] == (0.23, 0.1, 0.32)
    assert rep.camera_calls[0]["look_at"] == (0.36, 0.28, 0.02)
    assert rep.camera_calls[0]["look_at_up_axis"] == (0.0, 0.0, 1.0)
    assert rep.camera_calls[0]["focal_length"] == 18.0
    assert rep.camera_calls[0]["focus_distance"] == pytest.approx(0.369324)
    assert rep.camera_calls[0]["clipping_range"] == (0.001, 10.0)
    assert rep.camera_calls[0]["name"] != rep.camera_calls[1]["name"]


def test_rgbd_render_backend_camera_create_kwargs_preserves_explicit_lens_options() -> None:
    kwargs = IsaacReplicatorRgbdRenderBackend._camera_create_kwargs(
        {
            "position": [0.0, 0.0, 0.5],
            "look_at": [0.0, 0.0, 0.0],
            "look_at_up_axis": [0.0, 1.0, 0.0],
            "focal_length": 24.0,
            "focus_distance": 0.42,
            "clipping_range": [0.01, 3.0],
        }
    )

    assert kwargs == {
        "position": (0.0, 0.0, 0.5),
        "look_at": (0.0, 0.0, 0.0),
        "look_at_up_axis": (0.0, 1.0, 0.0),
        "focal_length": 24.0,
        "focus_distance": 0.42,
        "clipping_range": (0.01, 3.0),
    }


def test_rgbd_render_backend_default_camera_specs_are_top_front_right_obliques() -> None:
    assert IsaacReplicatorRgbdRenderBackend._default_camera_spec("top") == {
        "position": (0.315, 0.205, 0.72),
        "look_at": (0.315, 0.265, 0.0),
    }
    assert IsaacReplicatorRgbdRenderBackend._default_camera_spec("front") == {
        "position": (0.36, 0.96, 0.52),
        "look_at": (0.36, 0.28, 0.025),
        "focal_length": 14.0,
    }
    assert IsaacReplicatorRgbdRenderBackend._default_camera_spec("right") == {
        "position": (0.86, 0.58, 0.52),
        "look_at": (0.38, 0.24, 0.02),
        "focal_length": 10.0,
    }


def test_rgbd_render_backend_falls_back_to_step_async_inside_kit() -> None:
    class _FakeOrchestrator:
        def __init__(self) -> None:
            self.sync_calls: list[dict[str, object]] = []
            self.async_calls: list[dict[str, object]] = []

        def step(self, **kwargs) -> None:
            self.sync_calls.append(kwargs)
            raise RuntimeError(
                "Synchronous call to `step` can only be performed in a standalone workflow and may not be made from within Kit."
            )

        async def step_async(self, **kwargs) -> None:
            self.async_calls.append(kwargs)

    orchestrator = _FakeOrchestrator()
    backend = IsaacReplicatorRgbdRenderBackend()

    result = backend._step_orchestrator(
        types.SimpleNamespace(orchestrator=orchestrator),
        {"rt_subframes": 2, "target_fps": 15.0},
        pending_key="sync",
    )

    assert result == {"ok": True, "mode": "async_fallback"}
    assert orchestrator.sync_calls == [{"rt_subframes": 2, "delta_time": pytest.approx(1.0 / 15.0), "pause_timeline": False}]
    assert orchestrator.async_calls == [{"rt_subframes": 2, "delta_time": pytest.approx(1.0 / 15.0), "pause_timeline": False}]


def test_rgbd_render_backend_writes_png16_depth_without_npy_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np

    def fake_write_image(*, path: str, data: object) -> None:
        Path(path).write_bytes(b"fake-rgb")

    fake_rep = types.SimpleNamespace(orchestrator=types.SimpleNamespace(step=lambda **_: None))
    monkeypatch.setitem(sys.modules, "omni", types.ModuleType("omni"))
    monkeypatch.setitem(sys.modules, "omni.replicator", types.ModuleType("omni.replicator"))
    monkeypatch.setitem(sys.modules, "omni.replicator.core", fake_rep)
    monkeypatch.setitem(sys.modules, "omni.replicator.core.functional", types.SimpleNamespace(write_image=fake_write_image))

    class _FakeRgbAnnotator:
        @staticmethod
        def get_data():
            return np.zeros((2, 2, 3), dtype=np.uint8)

    class _FakeDepthAnnotator:
        @staticmethod
        def get_data():
            return np.full((2, 2), 0.42, dtype=np.float32)

    backend = IsaacReplicatorRgbdRenderBackend()
    monkeypatch.setattr(
        backend,
        "_resource_for_camera",
        lambda *_args, **_kwargs: {
            "ok": True,
            "camera_path": "/World/Camera",
            "render_product": object(),
            "render_product_name": "rp",
            "rgb_annotator": _FakeRgbAnnotator(),
            "depth_annotator": _FakeDepthAnnotator(),
        },
    )
    output_dir = tmp_path / "isaac_rgbd"

    result = backend(
        request={"cameras": ["top"], "frame_index": 7, "target_fps": 15.0},
        output_dir=output_dir,
        stage=object(),
        payload={},
    )

    depth_png = output_dir / "top" / "frame_000007_depth.png"
    assert result["ok"] is True
    assert depth_png.is_file()
    assert not (output_dir / "top" / "frame_000007_depth_m.npy").exists()
    assert [item["kind"] for item in result["files"]] == ["rgb", "depth"]
    assert all(item["encoding"] != "npy" for item in result["files"])


def test_rgbd_render_backend_schedules_step_async_when_event_loop_is_running() -> None:
    class _FakeOrchestrator:
        def __init__(self) -> None:
            self.async_calls: list[dict[str, object]] = []

        def step(self, **_kwargs) -> None:
            raise RuntimeError(
                "Synchronous call to `step` can only be performed in a standalone workflow and may not be made from within Kit."
            )

        async def step_async(self, **kwargs) -> None:
            self.async_calls.append(kwargs)

    async def _scenario() -> None:
        orchestrator = _FakeOrchestrator()
        backend = IsaacReplicatorRgbdRenderBackend()

        result = backend._step_orchestrator(
            types.SimpleNamespace(orchestrator=orchestrator),
            {"rt_subframes": 3, "target_fps": 15.0},
            pending_key="running-loop",
        )

        assert result == {"ok": True, "mode": "async_scheduled", "pending_key": "running-loop"}
        pending = backend._pending_steps["running-loop"]
        assert pending.done() is False
        await asyncio.sleep(0)
        assert pending.done() is True
        assert orchestrator.async_calls == [{"rt_subframes": 3, "delta_time": pytest.approx(1.0 / 15.0), "pause_timeline": False}]

    asyncio.run(_scenario())


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
