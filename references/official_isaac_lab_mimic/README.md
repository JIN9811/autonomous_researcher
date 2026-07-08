# Official Isaac Lab Mimic Reference

This folder is a read-only reference copy of the Isaac Lab Mimic files used to redesign the Robotis OMX pipeline around the official Mimic flow.

Source:
- Repository: `/home/jin/IsaacLab`
- Remote: `https://github.com/isaac-sim/IsaacLab.git`
- Branch: `release/3.0.0-beta2`
- Commit: `ffff603eafc6b74264a5261cc0183d6a65390d78`

Import check:
- `/home/jin/IsaacLab/isaaclab.sh -p` imports `isaaclab_mimic` from `/home/jin/IsaacLab/source/isaaclab_mimic/isaaclab_mimic`.

Copied reference files:
- `scripts/imitation_learning/isaaclab_mimic/annotate_demos.py`
- `scripts/imitation_learning/isaaclab_mimic/generate_dataset.py`
- `scripts/imitation_learning/isaaclab_mimic/consolidated_demo.py`
- `scripts/tools/replay_demos.py`
- `source/isaaclab/envs/mimic_env_cfg.py`
- `source/isaaclab/envs/manager_based_rl_mimic_env.py`
- `source/isaaclab_mimic/datagen/*.py`
- `source/isaaclab_mimic/envs/franka_stack_ik_rel_mimic_env*.py`
- `source/isaaclab_mimic/envs/pickplace_gr1t2_mimic_env*.py`
- `docs/isaaclab_mimic.*.rst`

Do not import this folder from runtime code. Runtime should use the installed Isaac Lab package or the configured `/home/jin/IsaacLab` checkout.
