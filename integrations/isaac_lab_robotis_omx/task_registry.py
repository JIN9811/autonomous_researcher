"""Gym task registration for the Robotis OMX Isaac Lab sidecar."""

from __future__ import annotations

from typing import Any


MIMIC_TASK_NAME = "ATR-Robotis-OMX-PickPlace-Mimic-v0"
POLICY_TASK_NAME = "ATR-Robotis-OMX-PickPlace-v0"
PHYSICAL_MIMIC_TASK_NAME = "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0"
PHYSICAL_POLICY_TASK_NAME = "ATR-Robotis-OMX-PickPlace-Physical-v0"
PHYSICAL_POLICY_STATE_TASK_NAME = "ATR-Robotis-OMX-PickPlace-Physical-State-v0"


def task_registration_kwargs() -> dict[str, dict[str, str]]:
    """Return Robotis OMX gym task kwargs without requiring gym/Isaac Lab."""
    return {
        POLICY_TASK_NAME: {
            "entry_point": "isaaclab.envs:ManagerBasedRLEnv",
            "env_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_env_cfg:RobotisOMXPickPlaceEnvCfg",
            "robomimic_bc_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robomimic:bc.json",
        },
        MIMIC_TASK_NAME: {
            "entry_point": "integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_mimic_env:RobotisOMXPickPlaceMimicEnv",
            "env_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_mimic_env_cfg:RobotisOMXPickPlaceMimicEnvCfg",
            "robomimic_bc_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robomimic:bc.json",
        },
        PHYSICAL_POLICY_TASK_NAME: {
            "entry_point": "isaaclab.envs:ManagerBasedRLEnv",
            "env_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robotis_omx_physical_env_cfg:RobotisOMXPhysicalPickPlaceEnvCfg",
            "robomimic_bc_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robomimic:bc_visual.json",
        },
        PHYSICAL_POLICY_STATE_TASK_NAME: {
            "entry_point": "isaaclab.envs:ManagerBasedRLEnv",
            "env_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robotis_omx_physical_env_cfg:RobotisOMXPhysicalPickPlaceEnvCfg",
            "robomimic_bc_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robomimic:bc.json",
        },
        PHYSICAL_MIMIC_TASK_NAME: {
            "entry_point": "integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_mimic_env:RobotisOMXPickPlaceMimicEnv",
            "env_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robotis_omx_physical_mimic_env_cfg:RobotisOMXPhysicalPickPlaceMimicEnvCfg",
            "robomimic_bc_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robomimic:bc_visual.json",
        },
    }


def register_tasks() -> None:
    """Register Robotis OMX Isaac Lab tasks exactly once."""
    try:
        import gymnasium as gym
    except ImportError:
        return

    registry: Any = gym.envs.registry
    for task_name, task_kwargs in task_registration_kwargs().items():
        if task_name in registry:
            continue
        gym.register(
            id=task_name,
            entry_point=task_kwargs["entry_point"],
            disable_env_checker=True,
            kwargs={
                "env_cfg_entry_point": task_kwargs["env_cfg_entry_point"],
                "robomimic_bc_cfg_entry_point": task_kwargs["robomimic_bc_cfg_entry_point"],
            },
        )
