"""Isaac Lab external callback for Robotis OMX task registration."""

from __future__ import annotations

import os
import sys

from .task_registry import register_tasks


_ARG_ENV_KEYS = {
    "--robotis-domain-randomization-profile": "ROBOTIS_OMX_DOMAIN_RANDOMIZATION_PROFILE",
    "--robotis-stage-path": "ROBOTIS_OMX_STAGE_PATH",
    "--robotis-output-root": "ROBOTIS_OMX_OUTPUT_ROOT",
    "--robotis-camera-width": "ROBOTIS_OMX_CAMERA_WIDTH",
    "--robotis-camera-height": "ROBOTIS_OMX_CAMERA_HEIGHT",
    "--robotis-camera-mode": "ROBOTIS_OMX_CAMERA_MODE",
    "--robotis-mimic-generation-guarantee": "ROBOTIS_OMX_MIMIC_GENERATION_GUARANTEE",
    "--robotis-mimic-keep-failed": "ROBOTIS_OMX_MIMIC_KEEP_FAILED",
    "--robotis-cube-reset-xyz": "ROBOTIS_OMX_CUBE_RESET_XYZ",
    "--robotis-cube-reset-yaw": "ROBOTIS_OMX_CUBE_RESET_YAW",
}


def _consume_robotis_args(argv: list[str]) -> None:
    index = 1
    while index < len(argv):
        flag = argv[index]
        env_key = _ARG_ENV_KEYS.get(flag)
        if env_key is None:
            index += 1
            continue
        if index + 1 >= len(argv):
            del argv[index]
            continue
        os.environ[env_key] = argv[index + 1]
        del argv[index : index + 2]


def register() -> list[str]:
    """Register Robotis OMX tasks and return callback-owned CLI arguments."""
    _consume_robotis_args(sys.argv)
    register_tasks()
    return []
