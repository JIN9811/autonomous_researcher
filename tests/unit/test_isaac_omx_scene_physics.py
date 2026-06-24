"""Physics contract tests for the Isaac OMX table-layout scene."""

from __future__ import annotations

import re
from pathlib import Path


SCENE = Path(__file__).resolve().parents[2] / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"
REPO_ROOT = SCENE.parents[3]
PHYSICS_PAYLOADS = [
    REPO_ROOT / "sim" / "robotis_omx" / "scene" / "payloads" / "Physics" / "physics.usda",
    REPO_ROOT / "sim" / "robotis_omx" / "omx" / "payloads" / "Physics" / "physics.usda",
]
PHYSX_PAYLOADS = [
    REPO_ROOT / "sim" / "robotis_omx" / "scene" / "payloads" / "Physics" / "physx.usda",
    REPO_ROOT / "sim" / "robotis_omx" / "omx" / "payloads" / "Physics" / "physx.usda",
]
BASE_PAYLOADS = [
    REPO_ROOT / "sim" / "robotis_omx" / "scene" / "payloads" / "base.usda",
    REPO_ROOT / "sim" / "robotis_omx" / "omx" / "payloads" / "base.usda",
]
INSTANCE_PAYLOADS = [
    (
        REPO_ROOT / "sim" / "robotis_omx" / "scene" / "payloads" / "instances.usda",
        "</tn__omxscene_h8/Physics/AntiSlipTapeMaterial>",
    ),
    (
        REPO_ROOT / "sim" / "robotis_omx" / "omx" / "payloads" / "instances.usda",
        "</omx/Physics/AntiSlipTapeMaterial>",
    ),
]


def _block(name: str) -> str:
    text = SCENE.read_text(encoding="utf-8")
    marker = f'"{name}"'
    start = text.index(marker)
    next_def = text.find("\n        def ", start + len(marker))
    if next_def == -1:
        next_def = text.find("\n    }", start)
    return text[start:next_def]


def _payload_joint_limits(path: Path, joint_name: str) -> tuple[float, float]:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf'def PhysicsRevoluteJoint "{re.escape(joint_name)}".*?\n\s*}}', text, flags=re.DOTALL)
    assert match, f"{joint_name} missing in {path}"
    block = match.group(0)
    lower = re.search(r"float physics:lowerLimit = (-?\d+(?:\.\d+)?)", block)
    upper = re.search(r"float physics:upperLimit = (-?\d+(?:\.\d+)?)", block)
    assert lower and upper, f"{joint_name} limits missing in {path}"
    return float(lower.group(1)), float(upper.group(1))


def test_workspace_static_objects_have_collision_contract() -> None:
    for prim_name in ["TableTop", "A4Sheet", "RightDiskAluminumTop", "RightDiskBlackBase"]:
        block = _block(prim_name)
        assert "PhysicsCollisionAPI" in block, prim_name
        assert "physics:collisionEnabled" in block, prim_name


def test_red_specimen_block_is_dynamic_rigid_body() -> None:
    block = _block("RedSpecimenBlock")

    assert "PhysicsRigidBodyAPI" in block
    assert "PhysxRigidBodyAPI" in block
    assert "PhysicsCollisionAPI" in block
    assert "PhysxCollisionAPI" in block
    assert "PhysicsMassAPI" in block
    assert re.search(r"float physics:mass = 0\.0?2", block), block
    assert "physics:collisionEnabled" in block
    assert "float physxCollision:contactOffset = 0.004" in block
    assert "float physxCollision:restOffset = 0" in block
    assert "bool physxRigidBody:enableCCD = 1" in block
    assert "float physxRigidBody:maxDepenetrationVelocity = 0.5" in block


def test_red_specimen_and_work_surfaces_use_realistic_contact_materials() -> None:
    text = SCENE.read_text(encoding="utf-8")

    assert 'def Material "paper_contact_physics"' in text
    assert 'def Material "pla_specimen_contact_physics"' in text
    assert "float physics:staticFriction = 0.75" in text
    assert "float physics:dynamicFriction = 0.55" in text
    assert "float physics:staticFriction = 0.5" in text
    assert "float physics:dynamicFriction = 0.35" in text
    assert "float physics:restitution = 0" in text

    block = _block("A4Sheet")
    assert "rel material:binding:physics = </World/Materials/paper_contact_physics>" in block
    assert "PhysxCollisionAPI" in block
    assert "float physxCollision:contactOffset = 0.003" in block
    assert "float physxCollision:restOffset = 0" in block

    block = _block("RedSpecimenBlock")
    assert "rel material:binding:physics = </World/Materials/pla_specimen_contact_physics>" in block


def test_robot_gripper_uses_antislip_tape_contact_material() -> None:
    for payload in [*BASE_PAYLOADS, *PHYSICS_PAYLOADS]:
        text = payload.read_text(encoding="utf-8")
        match = re.search(r'(?:def Material|over) "PhysicsMaterial".*?\n\s*}', text, flags=re.DOTALL)
        assert match, payload
        block = match.group(0)
        assert "float physics:staticFriction = 0.6" in block, payload
        assert "float physics:dynamicFriction = 0.45" in block, payload
        assert "float physics:restitution = 0" in block, payload

        match = re.search(r'def Material "AntiSlipTapeMaterial".*?\n\s*}', text, flags=re.DOTALL)
        assert match, payload
        block = match.group(0)
        assert "float physics:staticFriction = 2.4" in block, payload
        assert "float physics:dynamicFriction = 1.8" in block, payload
        assert "float physics:restitution = 0" in block, payload

    for payload, expected_binding in INSTANCE_PAYLOADS:
        text = payload.read_text(encoding="utf-8")
        for name in ("follower_07_gripper_motorized_1", "follower_08_gripper_gear_1"):
            match = re.search(rf'def Xform "{name}".*?\n    }}', text, flags=re.DOTALL)
            assert match, f"{payload}:{name}"
            block = match.group(0)
            assert expected_binding in block, f"{payload}:{name}"
            assert "PhysxCollisionAPI" in block, f"{payload}:{name}"
            assert "float physxCollision:contactOffset = 0.002" in block, f"{payload}:{name}"
            assert "float physxCollision:restOffset = 0" in block, f"{payload}:{name}"


def test_robot_internal_collision_is_not_filtered_out() -> None:
    for payload in PHYSICS_PAYLOADS:
        text = payload.read_text(encoding="utf-8")
        assert "bool newton:selfCollisionEnabled = 1" in text, payload
        assert "newton:selfCollisionEnabled = 0" not in text, payload
        assert "rel physics:filteredPairs" not in text, payload


def test_scene_has_global_gravity_and_high_precision_physx_contract() -> None:
    text = SCENE.read_text(encoding="utf-8")
    physics_scene = _block("PhysicsScene")

    assert "physics:gravityDirection = (0, 0, -1)" in physics_scene
    assert "physics:gravityMagnitude = 9.81" in physics_scene
    assert "custom int physxScene:timeStepsPerSecond = 240" in physics_scene
    assert "bool physxScene:enableCCD = 1" in physics_scene
    assert "bool physxScene:enableStabilization = 1" in physics_scene
    assert 'uniform token physxScene:solverType = "TGS"' in physics_scene
    assert "float physxScene:frictionCorrelationDistance = 0.005" in physics_scene
    assert "float physxScene:frictionOffsetThreshold = 0.002" in physics_scene


def test_robot_physx_articulation_uses_contact_solver_iterations() -> None:
    for payload in PHYSX_PAYLOADS:
        text = payload.read_text(encoding="utf-8")

        assert "PhysxArticulationAPI" in text, payload
        assert "int physxArticulation:solverPositionIterationCount = 64" in text, payload
        assert "int physxArticulation:solverVelocityIterationCount = 4" in text, payload


def test_robot_payload_joint_limits_cover_live_mirror_mapping_range() -> None:
    for payload in PHYSICS_PAYLOADS:
        for joint_name in ("Joint2", "Joint3", "Joint4"):
            lower, upper = _payload_joint_limits(payload, joint_name)
            assert lower <= -180.0, f"{payload}:{joint_name}"
            assert upper >= 180.0, f"{payload}:{joint_name}"

        lower, upper = _payload_joint_limits(payload, "Gripper")
        assert lower <= 0.0, f"{payload}:Gripper"
        assert upper >= 36.0, f"{payload}:Gripper"

        lower, upper = _payload_joint_limits(payload, "Gripper_mimic")
        assert lower <= -36.0, f"{payload}:Gripper_mimic"
        assert upper >= 0.0, f"{payload}:Gripper_mimic"


def test_scene_does_not_persist_live_articulation_runtime_state() -> None:
    text = SCENE.read_text(encoding="utf-8")

    globally_forbidden = [
        "drive:angular:physics:targetPosition",
        "state:angular:physics:position",
        "state:angular:physics:velocity",
    ]
    for token in globally_forbidden:
        assert token not in text, token

    robot_block = _block("Robot")
    robot_forbidden = [
        "physics:angularVelocity",
        "physics:velocity",
        "xformOp:orient",
    ]
    for token in robot_forbidden:
        assert token not in robot_block, token
