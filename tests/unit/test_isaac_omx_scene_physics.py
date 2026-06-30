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
BASELINE_COLLISION_DENSITY_KG_PER_M3 = 1000
BASELINE_LINK_MASS_KG = {
    "link0": "0.22389051",
    "link1": "0.06598704",
    "link2": "0.08722147",
    "link3": "0.08375913",
    "link4": "0.029975062",
    "link5": "0.103810885",
    "link6": "0.012090677",
    "link7": "0.012090677",
}
BASELINE_LINK_DIAGONAL_INERTIA = {
    "link0": "(0.0003568046, 0.00021941932, 0.000455759)",
    "link1": "(0.000021731666, 0.000021351512, 0.000011657955)",
    "link2": "(0.00010307915, 0.00012086327, 0.000041993677)",
    "link3": "(0.000015203101, 0.00022606157, 0.00023066887)",
    "link4": "(0.000005099513, 0.0000070990473, 0.0000063119496)",
    "link5": "(0.000060238684, 0.00010429448, 0.00006933399)",
    "link6": "(0.0000027083288, 0.000006873373, 0.000004694188)",
    "link7": "(0.0000027083288, 0.000006873373, 0.000004694188)",
}
CONTACT_LINK_PATHS = (
    "link0/link1/link2/link3/link4/follower_05_tip_1",
    "link0/link1/link2/link3/link4/link5/link6/follower_07_gripper_motorized_1",
    "link0/link1/link2/link3/link4/link5/link7/follower_08_gripper_gear_1",
)
GRIPPER_CONTACT_PROXY_NAMES = (
    "InnerGripPadCollision",
    "InnerGripPadCollision_mimic",
)
GRIPPER_STL_COLLISION_LINKS = {
    "follower_07_gripper_motorized_1": "follower_07_gripper_motorized",
    "follower_08_gripper_gear_1": "follower_08_gripper_gear",
}
ARM_BOARD_COLLISION_LINKS = (
    "follower_03_middle_verticle_1",
    "follower_04_middle_horizontal_1",
    "follower_05_tip_1",
    "follower_06_pan_Revised_1",
)


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


def _workspace_translate(prim_name: str) -> tuple[float, float, float]:
    block = _block(prim_name)
    match = re.search(r"double3 xformOp:translate = \(([^,]+), ([^,]+), ([^)]+)\)", block)
    assert match, f"{prim_name} translate missing"
    return float(match.group(1)), float(match.group(2)), float(match.group(3))


def _workspace_scale(prim_name: str) -> tuple[float, float, float]:
    block = _block(prim_name)
    match = re.search(r"float3 xformOp:scale = \(([^,]+), ([^,]+), ([^)]+)\)", block)
    assert match, f"{prim_name} scale missing"
    return float(match.group(1)), float(match.group(2)), float(match.group(3))


def test_workspace_static_objects_have_collision_contract() -> None:
    for prim_name in [
        "TableTop",
        "TableTopFrontLeft",
        "TableTopFrontRight",
        "RobotBasePocketFloor",
        "A4Sheet",
        "RightDiskAluminumTop",
        "RightDiskBlackBase",
    ]:
        block = _block(prim_name)
        assert "PhysicsCollisionAPI" in block, prim_name
        assert "physics:collisionEnabled" in block, prim_name


def test_right_disk_uses_original_height_and_robot_base_sits_in_two_cm_table_pocket() -> None:
    assert _workspace_translate("RightDiskAluminumTop") == (0.59, 0.078, 0.037)
    assert _workspace_translate("RightDiskBlackBase") == (0.59, 0.078, 0.012)
    marker_block = _block("RightDiskCenterYellowMarker")
    assert "(0.59, 0.078, 0.0743)" in marker_block
    assert _workspace_translate("Robot") == (0.315, 0.06, -0.02)

    assert _workspace_translate("TableTop") == (0.35, 0.285, -0.015)
    assert _workspace_scale("TableTop") == (0.7, 0.33, 0.03)
    assert _workspace_translate("TableTopFrontLeft") == (0.12, 0.06, -0.015)
    assert _workspace_scale("TableTopFrontLeft") == (0.24, 0.12, 0.03)
    assert _workspace_translate("TableTopFrontRight") == (0.545, 0.06, -0.015)
    assert _workspace_scale("TableTopFrontRight") == (0.31, 0.12, 0.03)
    assert _workspace_translate("RobotBasePocketFloor") == (0.315, 0.06, -0.022)
    assert _workspace_scale("RobotBasePocketFloor") == (0.15, 0.12, 0.004)

    text = SCENE.read_text(encoding="utf-8")
    assert 'def Mesh "TableTopRedwoodGrainSurface"\n' not in text


def test_red_specimen_block_is_dynamic_rigid_body() -> None:
    block = _block("RedSpecimenBlock")

    assert "PhysicsRigidBodyAPI" in block
    assert "PhysxRigidBodyAPI" in block
    assert "PhysicsCollisionAPI" in block
    assert "PhysxCollisionAPI" in block
    assert "PhysxContactReportAPI" in block
    assert "PhysicsMassAPI" in block
    assert re.search(r"float physics:mass = 0\.0?3", block), block
    assert "physics:collisionEnabled" in block
    assert "float physxCollision:contactOffset = 0.003" in block
    assert "float physxCollision:restOffset = 0" in block
    assert "bool physxRigidBody:enableCCD = 1" in block
    assert "float physxRigidBody:maxDepenetrationVelocity = 0.2" in block
    assert re.search(r"(?:custom )?int physxRigidBody:solverPositionIterationCount = 32", block)
    assert re.search(r"(?:custom )?int physxRigidBody:solverVelocityIterationCount = 4", block)
    assert "float physxContactReport:threshold = 0.2" in block
    assert 'double3 xformOp:translate = (0.4, 0.3, 0.0152)' in block
    assert "float3 xformOp:scale = (0.03, 0.03, 0.03)" in block
    assert "PhysicsMeshCollisionAPI" not in block
    assert "PhysxSDFMeshCollisionAPI" not in block
    assert "physics:approximation" not in block


def test_red_specimen_collision_skin_is_derived_from_object_size() -> None:
    script = (REPO_ROOT / "sim" / "robotis_omx" / "tools" / "build_table_layout_scene.py").read_text(encoding="utf-8")

    assert "def collision_skin_for_dimensions" in script
    assert "COLLISION_SKIN_FRACTION = 0.10" in script
    assert "specimen_size = (0.030, 0.030, 0.030)" in script
    assert "contact_offset=collision_skin_for_dimensions(specimen_size)" in script


def test_red_specimen_and_work_surfaces_use_realistic_contact_materials() -> None:
    text = SCENE.read_text(encoding="utf-8")

    assert 'def Material "paper_contact_physics"' in text
    assert 'def Material "pla_specimen_contact_physics"' in text
    assert "float physics:staticFriction = 1.1" in text
    assert "float physics:dynamicFriction = 0.9" in text
    assert "float physics:staticFriction = 1" in text
    assert "float physics:dynamicFriction = 0.8" in text
    assert "float physics:restitution = 0" in text
    pla_block = _block("pla_specimen_contact_physics")
    assert "PhysxMaterialAPI" in pla_block
    assert 'uniform token physxMaterial:frictionCombineMode = "max"' in pla_block
    assert "float physxMaterial:compliantContactStiffness = 100000" in pla_block
    assert "float physxMaterial:compliantContactDamping = 1000" in pla_block

    block = _block("A4Sheet")
    assert "rel material:binding:physics = </World/Materials/paper_contact_physics>" in block
    assert "PhysxCollisionAPI" in block
    assert "float physxCollision:contactOffset = 0.001" in block
    assert "float physxCollision:restOffset = 0" in block

    block = _block("RedSpecimenBlock")
    assert "rel material:binding:physics = </World/Materials/pla_specimen_contact_physics>" in block


def test_robot_gripper_uses_antislip_only_on_inner_pad_contact_material() -> None:
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
        assert "float physics:staticFriction = 5" in block, payload
        assert "float physics:dynamicFriction = 4" in block, payload
        assert "float physics:restitution = 0" in block, payload
        assert "PhysxMaterialAPI" in block, payload
        assert 'uniform token physxMaterial:frictionCombineMode = "max"' in block, payload
        assert "float physxMaterial:compliantContactStiffness = 50000" in block, payload
        assert "float physxMaterial:compliantContactDamping = 300" in block, payload

    for payload, expected_binding in INSTANCE_PAYLOADS:
        text = payload.read_text(encoding="utf-8")
        root_material = expected_binding.replace("AntiSlipTapeMaterial", "PhysicsMaterial")
        for name in ("follower_05_tip_1", "follower_07_gripper_motorized_1", "follower_08_gripper_gear_1"):
            match = re.search(rf'def Xform "{name}".*?\n    }}', text, flags=re.DOTALL)
            assert match, f"{payload}:{name}"
            block = match.group(0)
            assert root_material in block, f"{payload}:{name}"
            assert expected_binding not in block, f"{payload}:{name}"
            assert "PhysxCollisionAPI" in block, f"{payload}:{name}"
            expected_offset = "0.0005" if name in {"follower_07_gripper_motorized_1", "follower_08_gripper_gear_1"} else "0.001"
            assert f"float physxCollision:contactOffset = {expected_offset}" in block, f"{payload}:{name}"
            assert "float physxCollision:restOffset = 0" in block, f"{payload}:{name}"


def test_robot_gripper_uses_stl_mesh_collision_with_enabled_inner_pad_proxy() -> None:
    expected_fallback_bindings = {
        REPO_ROOT / "sim" / "robotis_omx" / "scene" / "payloads" / "base.usda": "</tn__omxscene_h8/Physics/AntiSlipTapeMaterial>",
        REPO_ROOT / "sim" / "robotis_omx" / "omx" / "payloads" / "base.usda": "</omx/Physics/AntiSlipTapeMaterial>",
    }
    for payload in BASE_PAYLOADS:
        text = payload.read_text(encoding="utf-8")
        expected_binding = expected_fallback_bindings[payload]
        for name in GRIPPER_CONTACT_PROXY_NAMES:
            match = re.search(rf'def Cube "{re.escape(name)}".*?\n\s*}}', text, flags=re.DOTALL)
            assert match, f"{payload}:{name}"
            block = match.group(0)
            assert expected_binding in block, f"{payload}:{name}"
            assert 'custom string atr:collision:role = "inner_pad_fallback"' in block, f"{payload}:{name}"
            assert 'custom token physics:approximation = "box"' in block, f"{payload}:{name}"
            assert "bool physics:collisionEnabled = 1" in block, f"{payload}:{name}"
            assert "float physxCollision:contactOffset = 0.0005" in block, f"{payload}:{name}"
            assert "float physxCollision:restOffset = 0" in block, f"{payload}:{name}"
            scale = re.search(r"float3 xformOp:scale = \(([^,]+), ([^,]+), ([^)]+)\)", block)
            assert scale, f"{payload}:{name}"
            assert float(scale.group(2)) <= 0.0008, f"{payload}:{name}"

    for payload, expected_binding in INSTANCE_PAYLOADS:
        text = payload.read_text(encoding="utf-8")
        for collision_link, geometry_name in GRIPPER_STL_COLLISION_LINKS.items():
            match = re.search(rf'def Xform "{re.escape(collision_link)}".*?\n    }}', text, flags=re.DOTALL)
            assert match, f"{payload}:{collision_link}"
            block = match.group(0)
            assert f"prepend references = @./geometries.usd@</Geometries/{geometry_name}>" in block
            assert expected_binding.replace("AntiSlipTapeMaterial", "PhysicsMaterial") in block, f"{payload}:{collision_link}"
            assert expected_binding not in block, f"{payload}:{collision_link}"
            assert "PhysicsMeshCollisionAPI" in block, f"{payload}:{collision_link}"
            assert "PhysxSDFMeshCollisionAPI" not in block, f"{payload}:{collision_link}"
            assert 'token physics:approximation = "convexDecomposition"' in block, f"{payload}:{collision_link}"
            assert 'token physics:approximation = "convexHull"' not in block, f"{payload}:{collision_link}"
            assert 'token physics:approximation = "sdf"' not in block, f"{payload}:{collision_link}"
            assert "float physxCollision:contactOffset = 0.0005" in block, f"{payload}:{collision_link}"
            assert "physxSDFMeshCollision:" not in block, f"{payload}:{collision_link}"


def test_robot_arm_board_collision_meshes_use_decomposition_not_broad_hulls() -> None:
    for payload in INSTANCE_PAYLOADS:
        text = payload[0].read_text(encoding="utf-8")
        for collision_link in ARM_BOARD_COLLISION_LINKS:
            match = re.search(rf'def Xform "{re.escape(collision_link)}".*?\n    }}', text, flags=re.DOTALL)
            assert match, f"{payload[0]}:{collision_link}"
            block = match.group(0)
            assert "PhysicsMeshCollisionAPI" in block, f"{payload[0]}:{collision_link}"
            assert "PhysxCollisionAPI" in block, f"{payload[0]}:{collision_link}"
            assert 'token physics:approximation = "convexDecomposition"' in block, f"{payload[0]}:{collision_link}"
            assert 'token physics:approximation = "convexHull"' not in block, f"{payload[0]}:{collision_link}"
            expected_offset = "0.001" if collision_link == "follower_05_tip_1" else "0.0005"
            assert f"float physxCollision:contactOffset = {expected_offset}" in block, f"{payload[0]}:{collision_link}"
            assert "float physxCollision:restOffset = 0" in block, f"{payload[0]}:{collision_link}"


def test_robot_gripper_physx_payload_keeps_antislip_off_stl_roots() -> None:
    for payload, antislip_binding in zip(PHYSX_PAYLOADS, (
        "</tn__omxscene_h8/Physics/AntiSlipTapeMaterial>",
        "</omx/Physics/AntiSlipTapeMaterial>",
    ), strict=True):
        text = payload.read_text(encoding="utf-8")
        default_binding = antislip_binding.replace("AntiSlipTapeMaterial", "PhysicsMaterial")
        for link_path in CONTACT_LINK_PATHS:
            name = link_path.rsplit("/", 1)[-1]
            match = re.search(
                rf'over "{re.escape(name)}".*?\n\s*}}',
                text,
                flags=re.DOTALL,
            )
            assert match, f"{payload}:{link_path}"
            block = match.group(0)
            assert default_binding in block, f"{payload}:{link_path}"
            assert antislip_binding not in block, f"{payload}:{link_path}"
            assert "PhysxCollisionAPI" in block, f"{payload}:{link_path}"
            assert "MaterialBindingAPI" in block, f"{payload}:{link_path}"
            expected_offset = "0.0005" if name in {"follower_07_gripper_motorized_1", "follower_08_gripper_gear_1"} else "0.001"
            assert f"float physxCollision:contactOffset = {expected_offset}" in block, f"{payload}:{link_path}"
            assert "float physxCollision:restOffset = 0" in block, f"{payload}:{link_path}"


def _payload_joint_drive_max_force(path: Path, joint_name: str) -> float:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf'def PhysicsRevoluteJoint "{re.escape(joint_name)}".*?\n\s*}}', text, flags=re.DOTALL)
    assert match, f"{joint_name} missing in {path}"
    block = match.group(0)
    max_force = re.search(r"float drive:angular:physics:maxForce = (-?\d+(?:\.\d+)?)", block)
    assert max_force, f"{joint_name} drive max force missing in {path}"
    return float(max_force.group(1))


def _payload_joint_drive_attr(path: Path, joint_name: str, attr_name: str) -> float:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf'def PhysicsRevoluteJoint "{re.escape(joint_name)}".*?\n\s*}}', text, flags=re.DOTALL)
    assert match, f"{joint_name} missing in {path}"
    block = match.group(0)
    attr = re.search(rf"float drive:angular:physics:{re.escape(attr_name)} = (-?\d+(?:\.\d+)?)", block)
    assert attr, f"{joint_name} drive {attr_name} missing in {path}"
    return float(attr.group(1))


def test_robot_payload_drives_use_stable_pick_place_gripper_effort_contract() -> None:
    for payload in PHYSICS_PAYLOADS:
        for joint_name in ("Joint1", "Joint2", "Joint3", "Joint4", "Joint5"):
            assert _payload_joint_drive_max_force(payload, joint_name) == 1.5
        for joint_name in ("Gripper", "Gripper_mimic"):
            assert _payload_joint_drive_max_force(payload, joint_name) == 4.0
            assert _payload_joint_drive_attr(payload, joint_name, "stiffness") == 180.0
            assert _payload_joint_drive_attr(payload, joint_name, "damping") == 18.0


def test_robot_collision_mesh_density_preserves_existing_converter_density() -> None:
    for payload, _expected_binding in INSTANCE_PAYLOADS:
        text = payload.read_text(encoding="utf-8")
        assert "float physics:density = 1240" not in text, payload
        assert text.count(f"float physics:density = {BASELINE_COLLISION_DENSITY_KG_PER_M3}") >= 8, payload


def test_robot_link_masses_and_inertia_are_not_changed_by_torque_tuning() -> None:
    for payload in PHYSICS_PAYLOADS:
        text = payload.read_text(encoding="utf-8")
        for link_name, mass in BASELINE_LINK_MASS_KG.items():
            match = re.search(rf'over "{re.escape(link_name)}".*?(?:over "|def PhysicsRevoluteJoint|$)', text, flags=re.DOTALL)
            assert match, f"{payload}:{link_name}"
            block = match.group(0)
            assert f"float physics:mass = {mass}" in block, f"{payload}:{link_name}"
            assert f"float3 physics:diagonalInertia = {BASELINE_LINK_DIAGONAL_INERTIA[link_name]}" in block, (
                f"{payload}:{link_name}"
            )


def test_wrist_link5_includes_d405_camera_payload_mass_for_sag() -> None:
    for payload in PHYSICS_PAYLOADS:
        text = payload.read_text(encoding="utf-8")
        match = re.search(r'over "link5".*?over "link6"', text, flags=re.DOTALL)
        assert match, f"link5 physics block missing in {payload}"
        block = match.group(0)

        assert 'custom string atr:payload:name = "Intel RealSense D405 wrist camera"' in block, payload
        assert "custom float atr:payload:mass = 0.06" in block, payload
        assert "custom point3f atr:payload:centerOfMass = (0.07, 0, 0.045)" in block, payload
        assert "float physics:mass = 0.103810885" in block, payload
        assert "point3f physics:centerOfMass = (0.05230547, 0.000010186, 0.031718386)" in block, payload
        assert "float3 physics:diagonalInertia = (0.000060238684, 0.00010429448, 0.00006933399)" in block, payload


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
    assert "float physxScene:bounceThresholdVelocity = 0.01" in physics_scene
    assert "float physxScene:frictionCorrelationDistance = 0.00625" in physics_scene
    assert "float physxScene:frictionOffsetThreshold = 0.002" in physics_scene
    assert 'uniform token physxScene:broadphaseType = "GPU"' in physics_scene
    assert "uint physxScene:gpuFoundLostAggregatePairsCapacity = 8192" in physics_scene
    assert "uint physxScene:gpuTotalAggregatePairsCapacity = 8192" in physics_scene


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
