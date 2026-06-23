"""Physics contract tests for the Isaac OMX table-layout scene."""

from __future__ import annotations

import re
from pathlib import Path


SCENE = Path(__file__).resolve().parents[2] / "sim" / "robotis_omx" / "scene" / "omx_table_layout.usda"


def _block(name: str) -> str:
    text = SCENE.read_text(encoding="utf-8")
    marker = f'"{name}"'
    start = text.index(marker)
    next_def = text.find("\n        def ", start + len(marker))
    if next_def == -1:
        next_def = text.find("\n    }", start)
    return text[start:next_def]


def test_workspace_static_objects_have_collision_contract() -> None:
    for prim_name in ["TableTop", "A4Sheet", "RightDiskAluminumTop", "RightDiskBlackBase"]:
        block = _block(prim_name)
        assert "PhysicsCollisionAPI" in block, prim_name
        assert "physics:collisionEnabled" in block, prim_name


def test_red_specimen_block_is_dynamic_rigid_body() -> None:
    block = _block("RedSpecimenBlock")

    assert "PhysicsRigidBodyAPI" in block
    assert "PhysicsCollisionAPI" in block
    assert "PhysicsMassAPI" in block
    assert re.search(r"float physics:mass = 0\.0?2", block), block
    assert "physics:collisionEnabled" in block


def test_scene_has_global_gravity_and_physx_timestep_contract() -> None:
    text = SCENE.read_text(encoding="utf-8")
    physics_scene = _block("PhysicsScene")

    assert "physics:gravityDirection = (0, 0, -1)" in physics_scene
    assert "physics:gravityMagnitude = 9.81" in physics_scene
    assert "physxScene:timeStepsPerSecond" in physics_scene
