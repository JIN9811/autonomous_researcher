"""Robotis OMX Mimic environment helpers for Isaac Lab."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import torch

try:
    import isaaclab.utils.math as PoseUtils
    from isaaclab.envs import ManagerBasedRLMimicEnv
except ImportError:
    ManagerBasedRLMimicEnv = object  # type: ignore[assignment]

    class _PoseUtilsFallback:
        @staticmethod
        def make_pose(position: torch.Tensor, rotation: torch.Tensor) -> torch.Tensor:
            pose = torch.eye(4, dtype=position.dtype, device=position.device).repeat(position.shape[0], 1, 1)
            pose[:, :3, :3] = rotation
            pose[:, :3, 3] = position
            return pose

        @staticmethod
        def unmake_pose(pose: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
            if pose.ndim == 2:
                pose = pose.unsqueeze(0)
            return pose[..., :3, 3], pose[..., :3, :3]

        @staticmethod
        def matrix_from_quat(quat: torch.Tensor) -> torch.Tensor:
            return torch.eye(3, dtype=quat.dtype, device=quat.device).repeat(quat.shape[0], 1, 1)

        @staticmethod
        def quat_from_matrix(matrix: torch.Tensor) -> torch.Tensor:
            return torch.zeros((*matrix.shape[:-2], 4), dtype=matrix.dtype, device=matrix.device)

        @staticmethod
        def axis_angle_from_quat(quat: torch.Tensor) -> torch.Tensor:
            return torch.zeros((*quat.shape[:-1], 3), dtype=quat.dtype, device=quat.device)

        @staticmethod
        def quat_from_angle_axis(angle: torch.Tensor, axis: torch.Tensor) -> torch.Tensor:
            quat = torch.zeros((*axis.shape[:-1], 4), dtype=axis.dtype, device=axis.device)
            quat[..., 0] = 1.0
            return quat

    PoseUtils = _PoseUtilsFallback()  # type: ignore[assignment]


PHYSICAL_JOINT_POSITION_CONTROL_MODE = "joint_position_physical_articulation"


class RobotisOMXPickPlaceMimicEnv(ManagerBasedRLMimicEnv):
    """Mimic-compatible Robotis OMX pick/place environment."""

    def get_robot_eef_pose(self, eef_name: str, env_ids: Sequence[int] | None = None) -> torch.Tensor:
        if env_ids is None:
            env_ids = slice(None)
        policy_obs = self.obs_buf["policy"]
        if "eef_pose" in policy_obs:
            return policy_obs["eef_pose"][env_ids]
        eef_pos = policy_obs["eef_pos"][env_ids]
        eef_quat = policy_obs["eef_quat"][env_ids]
        return PoseUtils.make_pose(eef_pos, PoseUtils.matrix_from_quat(eef_quat))

    def target_eef_pose_to_action(
        self,
        target_eef_pose_dict: dict[str, torch.Tensor],
        gripper_action_dict: dict[str, torch.Tensor],
        action_noise_dict: dict[str, float] | None = None,
        env_id: int = 0,
    ) -> torch.Tensor:
        eef_name = self._first_eef_name()
        if self._uses_physical_joint_position_actions():
            joint_action = self._retarget_physical_joint_action(
                target_eef_pose_dict.get(eef_name),
                gripper_action_dict.get(eef_name),
                action_noise_dict=action_noise_dict,
                env_id=env_id,
                eef_name=eef_name,
            )
            if joint_action is not None:
                return joint_action
            joint_action = self._joint_action_from_mimic_payload(gripper_action_dict.get(eef_name), env_id=env_id)
            if joint_action is not None:
                return joint_action

        target_eef_pose = target_eef_pose_dict[eef_name]
        target_pos, target_rot = PoseUtils.unmake_pose(target_eef_pose)
        curr_pose = self.get_robot_eef_pose(eef_name, env_ids=[env_id])[0]
        curr_pos, curr_rot = PoseUtils.unmake_pose(curr_pose)
        delta_position = target_pos.squeeze(0) - curr_pos.squeeze(0)
        delta_rot_mat = target_rot.matmul(curr_rot.transpose(-1, -2))
        delta_quat = PoseUtils.quat_from_matrix(delta_rot_mat)
        delta_rotation = PoseUtils.axis_angle_from_quat(delta_quat).reshape(-1)[:3]
        pose_action = torch.cat([delta_position.reshape(-1)[:3], delta_rotation], dim=0)
        if action_noise_dict is not None:
            noise_scale = float(action_noise_dict.get(eef_name, 0.0))
            pose_action = torch.clamp(pose_action + noise_scale * torch.randn_like(pose_action), -1.0, 1.0)
        gripper_action = gripper_action_dict[eef_name].reshape(-1)
        return torch.cat([pose_action, gripper_action], dim=0)

    def action_to_target_eef_pose(self, action: torch.Tensor) -> dict[str, torch.Tensor]:
        eef_name = self._first_eef_name()
        if self._uses_physical_joint_position_actions() and action.shape[-1] == self._physical_action_dim():
            env_ids = [0] if action.ndim == 1 else list(range(action.shape[0]))
            return {eef_name: self.get_robot_eef_pose(eef_name, env_ids=env_ids).clone()}

        if action.ndim == 1:
            action = action.unsqueeze(0)
        delta_position = action[:, :3]
        delta_rotation = action[:, 3:6]
        curr_pose = self.get_robot_eef_pose(eef_name, env_ids=None)
        curr_pos, curr_rot = PoseUtils.unmake_pose(curr_pose)
        target_pos = curr_pos + delta_position
        delta_rotation_angle = torch.linalg.norm(delta_rotation, dim=-1, keepdim=True)
        delta_rotation_axis = delta_rotation / torch.clamp(delta_rotation_angle, min=1.0e-6)
        is_zero = torch.isclose(delta_rotation_angle, torch.zeros_like(delta_rotation_angle)).squeeze(1)
        delta_rotation_axis[is_zero] = torch.zeros_like(delta_rotation_axis)[is_zero]
        delta_quat = PoseUtils.quat_from_angle_axis(delta_rotation_angle.squeeze(1), delta_rotation_axis)
        target_rot = PoseUtils.matrix_from_quat(delta_quat).matmul(curr_rot)
        return {eef_name: PoseUtils.make_pose(target_pos, target_rot).clone()}

    def actions_to_gripper_actions(self, actions: torch.Tensor) -> dict[str, torch.Tensor]:
        if self._uses_physical_joint_position_actions() and actions.shape[-1] == self._physical_action_dim():
            return {self._first_eef_name(): actions.clone()}

        if actions.ndim == 1:
            actions = actions.unsqueeze(0)
        return {self._first_eef_name(): actions[:, -1:]}

    def get_object_poses(self, env_ids: Sequence[int] | None = None) -> dict[str, torch.Tensor]:
        if env_ids is None:
            env_ids = slice(None)
        policy_obs = self.obs_buf["policy"]
        object_poses: dict[str, torch.Tensor] = {}
        if "object_pose" in policy_obs:
            red_cube_pose = policy_obs["object_pose"][env_ids]
            object_poses["red_cube"] = red_cube_pose
            count = policy_obs["object_pose"].shape[0]
            dtype = policy_obs["object_pose"].dtype
            device = policy_obs["object_pose"].device
            reference_xy = policy_obs["object_pose"][:, :2, 3]
        else:
            count = self.num_envs if hasattr(self, "num_envs") else 1
            dtype = torch.float32
            device = self.device if hasattr(self, "device") else None
            pose = torch.eye(4, dtype=dtype, device=device).repeat(count, 1, 1)
            object_poses["red_cube"] = pose[env_ids]
            reference_xy = None
        object_poses["place_target"] = self._place_target_pose(
            count=count,
            dtype=dtype,
            device=device,
            reference_xy=reference_xy,
        )[env_ids]
        return object_poses

    def get_subtask_term_signals(self, env_ids: Sequence[int] | None = None) -> dict[str, torch.Tensor]:
        if env_ids is None:
            env_ids = slice(None)
        terms = self.obs_buf["subtask_terms"]
        signal_names = ("approach", "grasp", "lift", "place", "release", "retract")
        result = {name: terms[name][env_ids] for name in signal_names if name in terms}
        if "cube_lifted" in terms:
            result["cube_lifted"] = terms["cube_lifted"][env_ids]
        elif "lift" in terms:
            result["cube_lifted"] = terms["lift"][env_ids]
        if "released_at_target" in terms:
            result["released_at_target"] = terms["released_at_target"][env_ids]
        elif "release" in terms:
            result["released_at_target"] = terms["release"][env_ids]
        return result

    def get_subtask_start_signals(self, env_ids: Sequence[int] | None = None) -> dict[str, torch.Tensor]:
        if env_ids is None:
            env_ids = slice(None)
        terms = self.obs_buf.get("subtask_starts", {})
        return {name: values[env_ids] for name, values in terms.items()}

    def _first_eef_name(self) -> str:
        configs: Any = getattr(getattr(self, "cfg", None), "subtask_configs", {"omx": []})
        return next(iter(configs.keys()), "omx")

    def _action_contract(self) -> dict[str, Any]:
        contract = getattr(getattr(self, "cfg", None), "action_contract", {})
        return contract if isinstance(contract, dict) else {}

    def _uses_physical_joint_position_actions(self) -> bool:
        return self._action_contract().get("control_mode") == PHYSICAL_JOINT_POSITION_CONTROL_MODE

    def _physical_action_dim(self) -> int:
        contract = self._action_contract()
        if "action_dim" in contract:
            return int(contract["action_dim"])
        joint_names = contract.get("joint_names", ())
        return len(joint_names)

    def _joint_action_from_mimic_payload(self, action: torch.Tensor | None, *, env_id: int) -> torch.Tensor | None:
        if action is None:
            return None
        action_dim = self._physical_action_dim()
        if action.shape[-1] == action_dim:
            if action.ndim == 1:
                return action.clone()
            index = min(max(int(env_id), 0), action.shape[0] - 1)
            return action[index].clone()
        policy_obs = self.obs_buf.get("policy", {})
        joint_pos = policy_obs.get("joint_pos")
        if not isinstance(joint_pos, torch.Tensor) or joint_pos.shape[-1] != action_dim:
            return None
        index = min(max(int(env_id), 0), joint_pos.shape[0] - 1)
        replay_action = joint_pos[index].clone()
        gripper_action = action.reshape(-1)
        if gripper_action.numel() >= 1:
            replay_action[-2] = gripper_action[0]
            replay_action[-1] = -gripper_action[0] if gripper_action.numel() == 1 else gripper_action[1]
        return replay_action

    def _retarget_physical_joint_action(
        self,
        target_eef_pose: torch.Tensor | None,
        gripper_action: torch.Tensor | None,
        *,
        action_noise_dict: dict[str, float] | None,
        env_id: int,
        eef_name: str,
    ) -> torch.Tensor | None:
        contract = self._action_contract()
        if contract.get("retarget_mode") != "differential_ik" or target_eef_pose is None:
            return None

        base_action = self._joint_action_from_mimic_payload(gripper_action, env_id=env_id)
        if base_action is None:
            base_action = self._current_physical_joint_action(env_id=env_id)
        if base_action is None:
            return None

        jacobian, action_arm_indices = self._physical_eef_position_jacobian(env_id=env_id)
        if jacobian is None or not action_arm_indices:
            return None

        target_pose = self._select_env_tensor(target_eef_pose, env_id=env_id).to(
            dtype=base_action.dtype,
            device=base_action.device,
        )
        curr_pose = self.get_robot_eef_pose(eef_name, env_ids=[env_id])[0].to(
            dtype=base_action.dtype,
            device=base_action.device,
        )
        target_pos, _ = PoseUtils.unmake_pose(target_pose)
        curr_pos, _ = PoseUtils.unmake_pose(curr_pose)
        position_error = target_pos.reshape(-1)[:3] - curr_pos.reshape(-1)[:3]
        if action_noise_dict is not None:
            noise_scale = float(action_noise_dict.get(eef_name, 0.0))
            if noise_scale > 0.0:
                position_error = position_error + noise_scale * torch.randn_like(position_error)

        damping = float(contract.get("ik_damping", 0.03))
        gain = float(contract.get("ik_position_gain", 0.8))
        max_delta = float(contract.get("ik_max_delta_rad", 0.08))
        delta_joint_pos = self._damped_least_squares_delta(jacobian, position_error, damping=damping, gain=gain)
        delta_joint_pos = torch.clamp(delta_joint_pos, -max_delta, max_delta)

        retargeted = base_action.clone()
        arm_indices = torch.as_tensor(action_arm_indices, device=base_action.device, dtype=torch.long)
        retargeted[arm_indices] = retargeted[arm_indices] + delta_joint_pos[: len(action_arm_indices)]
        retargeted = self._apply_gripper_payload(retargeted, gripper_action, env_id=env_id)
        return self._clamp_physical_joint_action(retargeted, env_id=env_id)

    def _current_physical_joint_action(self, *, env_id: int) -> torch.Tensor | None:
        action_dim = self._physical_action_dim()
        policy_obs = self.obs_buf.get("policy", {}) if hasattr(self, "obs_buf") else {}
        joint_pos = policy_obs.get("joint_pos") if isinstance(policy_obs, dict) else None
        if isinstance(joint_pos, torch.Tensor) and joint_pos.shape[-1] == action_dim:
            return self._select_env_tensor(joint_pos, env_id=env_id).reshape(-1)[:action_dim].clone()
        try:
            robot = self.scene["robot"]
            robot_joint_pos = self._proxy_tensor(robot.data.joint_pos)
            if isinstance(robot_joint_pos, torch.Tensor) and robot_joint_pos.shape[-1] >= action_dim:
                return self._select_env_tensor(robot_joint_pos, env_id=env_id).reshape(-1)[:action_dim].clone()
        except Exception:
            return None
        return None

    def _physical_eef_position_jacobian(self, *, env_id: int) -> tuple[torch.Tensor | None, list[int]]:
        contract = self._action_contract()
        joint_names = list(contract.get("joint_names", ()))
        arm_joint_names = list(contract.get("arm_joint_names", joint_names[:5]))
        if not joint_names or not arm_joint_names:
            return None, []
        try:
            robot = self.scene["robot"]
            body_ids, _ = robot.find_bodies(str(contract.get("eef_body_name", "link5")), preserve_order=True)
            robot_joint_ids, _ = robot.find_joints(arm_joint_names, preserve_order=True)
            action_arm_indices = [joint_names.index(name) for name in arm_joint_names]
            jacobians = self._proxy_tensor(robot.data.body_link_jacobian_w)
        except Exception:
            return None, []
        if not isinstance(jacobians, torch.Tensor) or not body_ids or not robot_joint_ids:
            return None, []
        body_index = int(body_ids[0])
        if hasattr(robot, "body_names") and jacobians.shape[1] == max(len(getattr(robot, "body_names", [])) - 1, 1):
            body_index = max(body_index - 1, 0)
        body_index = min(max(body_index, 0), jacobians.shape[1] - 1)
        env_index = min(max(int(env_id), 0), jacobians.shape[0] - 1)
        joint_ids = torch.as_tensor(robot_joint_ids, device=jacobians.device, dtype=torch.long)
        jacobian = jacobians[env_index, body_index, 0:3, :].index_select(1, joint_ids)
        return jacobian, action_arm_indices

    def _damped_least_squares_delta(
        self,
        jacobian: torch.Tensor,
        position_error: torch.Tensor,
        *,
        damping: float,
        gain: float,
    ) -> torch.Tensor:
        rows = jacobian.shape[0]
        identity = torch.eye(rows, dtype=jacobian.dtype, device=jacobian.device)
        lhs = jacobian @ jacobian.transpose(0, 1) + (float(damping) ** 2) * identity
        rhs = position_error.reshape(rows, 1)
        delta = jacobian.transpose(0, 1) @ torch.linalg.solve(lhs, rhs)
        return float(gain) * delta.reshape(-1)

    def _apply_gripper_payload(
        self,
        action: torch.Tensor,
        gripper_action: torch.Tensor | None,
        *,
        env_id: int,
    ) -> torch.Tensor:
        if gripper_action is None:
            return action
        payload = self._select_env_tensor(gripper_action, env_id=env_id).reshape(-1).to(
            dtype=action.dtype,
            device=action.device,
        )
        if payload.numel() == 0:
            return action
        joint_names = list(self._action_contract().get("joint_names", ()))
        primary_index = joint_names.index("Gripper") if "Gripper" in joint_names else action.shape[0] - 2
        mimic_index = joint_names.index("Gripper_mimic") if "Gripper_mimic" in joint_names else action.shape[0] - 1
        if payload.numel() >= self._physical_action_dim():
            action[primary_index] = payload[primary_index]
            action[mimic_index] = payload[mimic_index]
        elif payload.numel() == 1:
            action[primary_index] = payload[0]
            action[mimic_index] = -payload[0]
        else:
            action[primary_index] = payload[-2]
            action[mimic_index] = payload[-1]
        return action

    def _clamp_physical_joint_action(self, action: torch.Tensor, *, env_id: int) -> torch.Tensor:
        try:
            limits = self._proxy_tensor(self.scene["robot"].data.soft_joint_pos_limits)
        except Exception:
            limits = None
        if not isinstance(limits, torch.Tensor) or limits.ndim < 3:
            return action
        env_index = min(max(int(env_id), 0), limits.shape[0] - 1)
        limit_row = limits[env_index, : action.shape[0]].to(dtype=action.dtype, device=action.device)
        return torch.minimum(torch.maximum(action, limit_row[:, 0]), limit_row[:, 1])

    def _select_env_tensor(self, value: torch.Tensor, *, env_id: int) -> torch.Tensor:
        if value.ndim == 0:
            return value
        if value.ndim == 2 and value.shape == (4, 4):
            return value
        if value.ndim >= 3 and value.shape[-2:] == (4, 4):
            index = min(max(int(env_id), 0), value.shape[0] - 1)
            return value[index]
        if value.ndim >= 2:
            index = min(max(int(env_id), 0), value.shape[0] - 1)
            return value[index]
        return value

    @staticmethod
    def _proxy_tensor(value: Any) -> Any:
        return getattr(value, "torch", value)

    def _place_target_pose(
        self,
        *,
        count: int,
        dtype: torch.dtype,
        device: Any,
        reference_xy: torch.Tensor | None = None,
    ) -> torch.Tensor:
        from .mdp import physical_observations

        center_xy = torch.tensor(physical_observations.PLACE_TARGET_XY_M, dtype=dtype, device=device).reshape(1, 2)
        if reference_xy is None:
            xy = center_xy.repeat(count, 1)
        else:
            reference_xy = reference_xy.to(dtype=dtype, device=device).reshape(count, 2)
            offset = reference_xy - center_xy
            distance = torch.linalg.norm(offset, dim=1, keepdim=True)
            radius = torch.as_tensor(physical_observations.PLACE_RADIUS_M, dtype=dtype, device=device)
            scale = torch.where(
                distance > radius,
                radius / torch.clamp(distance, min=1.0e-6),
                torch.ones_like(distance),
            )
            xy = center_xy + offset * scale
        z = torch.full(
            (count, 1),
            float(physical_observations.PLACE_TARGET_CUBE_CENTER_Z_M),
            dtype=dtype,
            device=device,
        )
        pos = torch.cat([xy, z], dim=1)
        rot = torch.eye(3, dtype=dtype, device=device).repeat(count, 1, 1)
        return PoseUtils.make_pose(pos, rot)
