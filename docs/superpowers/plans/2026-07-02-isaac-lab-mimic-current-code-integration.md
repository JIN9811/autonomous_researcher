# Isaac Lab Mimic + IL E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a real end-to-end Isaac Lab pipeline that exports LeRobot demonstrations, annotates them for Isaac Lab Mimic, generates domain-randomized Mimic trajectories, trains an Isaac Lab robomimic BC policy, evaluates it in Isaac Lab, and exposes the whole flow from the LeRobot Isaac Lab GUI tab.

**Architecture:** Keep live LeRobot teleoperation and recording unchanged. Add an external Robotis OMX Isaac Lab package inside this repo, register it through callbacks/wrappers, run Isaac Lab Mimic and robomimic as subprocess jobs, and import only success-filtered generated trajectories back into the existing training sidecar. Domain randomization lives in the Isaac Lab environment reset/event config, while the bridge owns manifests, status, GUI orchestration, and training source labels.

**Tech Stack:** FastAPI, Pydantic, LeRobot bridge, Isaac Sim `/home/jin/IsaacSim/python.sh`, Isaac Lab `release/3.0.0-beta2`, `ManagerBasedRLMimicEnv`, Isaac Lab Mimic, robomimic BC, HDF5, Replicator/Isaac Lab event randomization, pytest.

---

## Verified Current State

Local runtime state:

- Isaac Lab path: `/home/jin/IsaacLab`
- Isaac Lab branch: `release/3.0.0-beta2`
- Isaac Lab commit: `ffff603eafc6b74264a5261cc0183d6a65390d78`
- Backup branch before upgrade: `backup/pre-upgrade-v3.0.0-beta2-20260702`
- Isaac Sim path: `/home/jin/IsaacSim`
- Isaac Sim Python: `3.12.13`
- Isaac Sim version file: `6.0.0-rc.59+release.41464.5f2772bc.gl`

Current repo support:

- `mcp_tools/lerobot_schemas.py` already has `IsaacLabSyntheticRequest`, synthetic source labels, Mimic/RL fields, source weights, and fidelity weights.
- `app/main.py` already exposes `/api/lerobot/isaac-lab/*` endpoints for validate, prepare, build, HDF5 export, Mimic, RL teacher, status, and E2E smoke.
- `device_bridges/lerobot_bridge.py` already has file-backed job lifecycle, process launch, status, stop, and live-session blocking for Isaac Lab jobs.
- `device_bridges/isaac_lab_synthetic.py` already writes canonical indexes, HDF5 exports, dry-run Mimic/RL manifests, generated success manifests, training import manifests, and Replicator summaries.
- The GUI has a dedicated Isaac Lab tab split from section 7.

Current blocking gaps:

- Current Mimic runner command is stale. It builds `--hdf5`, `--env-wrapper`, `--trials`, `--num-envs`; current Isaac Lab expects `--input_file`, `--output_file`, `--generation_num_trials`, `--num_envs`, `--task`, and optional `--external_callback`.
- Isaac Lab Mimic requires a real Gym task derived from `ManagerBasedRLMimicEnv`; current code only declares an env wrapper manifest.
- `annotate_demos.py` and `generate_dataset.py` support `--external_callback`, but `robomimic/train.py`, `robomimic/play.py`, and `robomimic/robust_eval.py` do not. Training/evaluation need local wrapper scripts that register the custom task before delegating to Isaac Lab robomimic scripts.
- HDF5 export must include robomimic/Isaac Lab metadata and `obs/datagen_info` fields that Mimic reads.
- Domain randomization is currently a manifest concept; it must become actual Isaac Lab event terms.

Official references:

- Isaac Lab latest release list: https://github.com/isaac-sim/IsaacLab/releases
- Isaac Lab `release/3.0.0-beta2` compatibility table: https://raw.githubusercontent.com/isaac-sim/IsaacLab/release/3.0.0-beta2/README.md
- Isaac Lab Mimic workflow and required helpers: https://isaac-sim.github.io/IsaacLab/main/source/overview/imitation-learning/teleop_imitation.html
- Isaac Lab augmented imitation workflow: https://isaac-sim.github.io/IsaacLab/main/source/overview/imitation-learning/augmented_imitation.html
- Isaac Lab environment and `MimicEnvCfg` API: https://isaac-sim.github.io/IsaacLab/main/source/api/lab/isaaclab.envs.html
- Isaac Lab domain randomization APIs: https://isaac-sim.github.io/IsaacLab/main/source/api/lab/isaaclab.envs.mdp.html
- ROBOTIS Lab direction: https://ai.robotis.com/omy/robotis_lab_omy.html

## Target E2E Flow

The GUI `Isaac Lab` tab should execute this exact high-level sequence:

1. `Validate Stack`
   - Verify Isaac Lab branch/commit.
   - Verify Isaac Sim version/Python.
   - Verify scripts exist.
   - Verify our Robotis OMX task registration can be imported.
2. `Build Source HDF5`
   - Convert successful LeRobot episodes to `hdf5/source_real_success.hdf5`.
   - Include actions, observations, object pose, EEF pose, gripper state, success metadata, and env metadata.
3. `Annotate Source`
   - Run Isaac Lab `annotate_demos.py` with `--auto` and `--external_callback`.
   - Output `hdf5/source_real_success_annotated.hdf5`.
4. `Generate Mimic`
   - Run Isaac Lab `generate_dataset.py`.
   - Use `ATR-Robotis-OMX-PickPlace-Mimic-v0`.
   - Apply selected domain randomization profile in the environment reset/events.
   - Output `mimic/generated_dataset.hdf5`.
5. `Inspect And Import`
   - Inspect generated HDF5.
   - Convert successes to `mimic/successes.jsonl`.
   - Update `training_import/manifest.jsonl` with `source_type=isaac_lab_mimic`.
6. `Train Isaac Lab IL`
   - Run robomimic BC through a wrapper that registers our task first.
   - Output logs/checkpoints under `output_root/il/robomimic`.
7. `Evaluate Isaac Lab IL`
   - Run play or robust eval through wrappers.
   - Report rollout success rate and checkpoint path.
8. `Expose Training Sources`
   - Keep generated Isaac Lab source available to existing LeRobot training mix, but do not change normal LeRobot training command construction.

Primary artifact layout:

```text
<dataset>/sidecar/isaac_lab_synthetic/latest/
  compatibility.json
  request.json
  summary.json
  canonical_episode_index/
    manifest.jsonl
    summary.json
  hdf5/
    source_real_success.hdf5
    source_real_success_annotated.hdf5
    export_summary.json
    annotation_summary.json
    hdf5_contract_report.json
  lab_env/
    registration_report.json
    domain_randomization_profile.json
    command_contracts.json
  mimic/
    generated_dataset.hdf5
    generation_summary.json
    successes.jsonl
    failures.jsonl
    preview_cards.jsonl
  il/
    robomimic/
      train_job.json
      train_stdout.log
      train_stderr.log
      checkpoints.json
    eval/
      eval_job.json
      eval_stdout.log
      eval_stderr.log
      results.json
  training_import/
    manifest.jsonl
    lerobot_source_config.json
    summary.json
```

## File Structure

Create:

- `integrations/isaac_lab_robotis_omx/__init__.py`
  - Package marker and public registration function.
- `integrations/isaac_lab_robotis_omx/external_callback.py`
  - Isaac Lab callback used by `annotate_demos.py` and `generate_dataset.py`.
- `integrations/isaac_lab_robotis_omx/task_registry.py`
  - Registers `ATR-Robotis-OMX-PickPlace-v0` and `ATR-Robotis-OMX-PickPlace-Mimic-v0`.
- `integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_env_cfg.py`
  - Manager-based env config, scene config, action config, observation config, events, terminations, and robomimic config entry points.
- `integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_mimic_env.py`
  - `ManagerBasedRLMimicEnv` subclass and required Mimic helper methods.
- `integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_mimic_env_cfg.py`
  - Mimic-specific `MimicEnvCfg`, `DataGenConfig`, and `SubTaskConfig`.
- `integrations/isaac_lab_robotis_omx/mdp/actions.py`
  - EEF delta pose plus gripper action helpers, or joint target action mapping if first implementation uses joint actions.
- `integrations/isaac_lab_robotis_omx/mdp/observations.py`
  - Robot state, EEF pose, gripper state, cube pose, camera observations.
- `integrations/isaac_lab_robotis_omx/mdp/events.py`
  - A4 cube reset, domain randomization profile application, optional camera pose/light randomizers.
- `integrations/isaac_lab_robotis_omx/mdp/terminations.py`
  - success, time-out, out-of-workspace, failed grasp checks.
- `integrations/isaac_lab_robotis_omx/mdp/rewards.py`
  - Minimal reward terms for future RL/evaluator branch; not used for BC training initially.
- `device_bridges/isaac_lab_hdf5.py`
  - HDF5 export, HDF5 contract validation, annotation import, generated success import.
- `scripts/lerobot_isaac_lab_robomimic_train.py`
  - Registers our task, then runs Isaac Lab robomimic `train.py`.
- `scripts/lerobot_isaac_lab_robomimic_play.py`
  - Registers our task, then runs Isaac Lab robomimic `play.py`.
- `scripts/lerobot_isaac_lab_robomimic_robust_eval.py`
  - Registers our task, then runs Isaac Lab robomimic `robust_eval.py`.
- `tests/unit/test_isaac_lab_robotis_omx_registration.py`
  - Import and registration tests that do not launch Isaac Sim.
- `tests/unit/test_lerobot_isaac_lab_e2e_contract.py`
  - Command-contract, HDF5-contract, and bridge status tests.

Modify:

- `mcp_tools/lerobot_schemas.py`
  - Add real E2E fields for task names, annotation, Mimic generation, IL training, IL evaluation, and domain randomization.
- `device_bridges/isaac_lab_synthetic.py`
  - Replace stale Mimic command builder.
  - Add annotation, generation, IL train, and eval summaries.
  - Delegate HDF5 work to `device_bridges/isaac_lab_hdf5.py`.
- `device_bridges/lerobot_bridge.py`
  - Add job lifecycle methods for annotation, generation, IL train, and eval, or generalize existing Isaac Lab runner job handling.
- `app/main.py`
  - Add endpoints for `/annotate`, `/generate-mimic`, `/train-il`, `/eval-il`, and `/run-e2e`.
- `web/templates/lerobot.html`
  - Add GUI controls and status cards in the Isaac Lab tab.
- `web/static/lerobot.js`
  - Add payload fields, buttons, progress stages, polling.
- `web/static/styles.css`
  - Add compact E2E status layout.
- `tests/unit/test_lerobot_gui_static.py`
  - Cover new controls and stage cards.

## Domain Randomization Profiles

Profile IDs:

- `off`
  - Deterministic scene for debugging.
- `conservative`
  - Cube XY/yaw only, small material variation, no actuator randomization.
- `standard`
  - Cube pose, cube mass/friction, table/A4 friction, gripper inner pad friction, small camera pose/light variation.
- `stress`
  - Larger visual/material variation, small actuator gain/joint friction variation, used only for eval or robust training experiments.

Default: `conservative` for first Mimic generation, `standard` only after one-trial generation succeeds.

Core ranges:

```python
DOMAIN_RANDOMIZATION_PROFILES = {
    "off": {
        "cube_xy_m": (0.0, 0.0),
        "cube_yaw_rad": (0.0, 0.0),
        "cube_mass_scale": (1.0, 1.0),
        "cube_static_friction": (0.9, 0.9),
        "cube_dynamic_friction": (0.7, 0.7),
        "gripper_inner_static_friction": (1.2, 1.2),
        "camera_pose_xyz_m": (0.0, 0.0),
    },
    "conservative": {
        "cube_xy_m": (-0.015, 0.015),
        "cube_yaw_rad": (-0.174533, 0.174533),
        "cube_mass_scale": (0.9, 1.1),
        "cube_static_friction": (0.8, 1.1),
        "cube_dynamic_friction": (0.6, 0.9),
        "gripper_inner_static_friction": (1.1, 1.4),
        "camera_pose_xyz_m": (-0.002, 0.002),
    },
    "standard": {
        "cube_xy_m": (-0.04, 0.04),
        "cube_yaw_rad": (-0.785398, 0.785398),
        "cube_mass_scale": (0.75, 1.25),
        "cube_static_friction": (0.7, 1.3),
        "cube_dynamic_friction": (0.5, 1.0),
        "gripper_inner_static_friction": (1.0, 1.6),
        "camera_pose_xyz_m": (-0.006, 0.006),
    },
    "stress": {
        "cube_xy_m": (-0.08, 0.08),
        "cube_yaw_rad": (-3.141593, 3.141593),
        "cube_mass_scale": (0.6, 1.5),
        "cube_static_friction": (0.45, 1.6),
        "cube_dynamic_friction": (0.35, 1.2),
        "gripper_inner_static_friction": (0.8, 1.8),
        "camera_pose_xyz_m": (-0.012, 0.012),
    },
}
```

Implementation rule:

- Use Isaac Lab event terms for physics and reset randomization.
- Use Replicator or Isaac Lab visual randomization terms for RGB/depth/camera visual variation.
- Never apply `stress` to generated data by default. It is an evaluation profile until proven useful.

## Operational Isaac Lab Defaults

The GUI must expose these values, but the first implementation should use the defaults below so runs are reproducible.

Task names:

- Mimic generation task: `ATR-Robotis-OMX-PickPlace-Mimic-v0`
- IL policy task: `ATR-Robotis-OMX-PickPlace-v0`
- External callback: `integrations.isaac_lab_robotis_omx.external_callback.register`

Run presets:

| Preset | Purpose | Mimic trials | `--num_envs` | Domain randomization | Cameras | Training import |
| --- | --- | ---: | ---: | --- | --- | --- |
| `smoke` | Verify stack without long runtime | 1 | 1 | `conservative` | off | success-only |
| `first_real` | First usable generated batch | 20 | 2 | `conservative` | off | success-only |
| `train_standard` | Normal IL training batch | 100 | 4 | `standard` | off for state BC, on only for visual BC | success-only |
| `robust_eval` | Stress-test trained policy | 50 rollouts | 4 | `stress` | match policy type | do not import |

Default GUI values:

```python
isaac_lab_task_name = "ATR-Robotis-OMX-PickPlace-Mimic-v0"
isaac_lab_policy_task_name = "ATR-Robotis-OMX-PickPlace-v0"
mimic_trials = 20
mimic_num_envs = 2
mimic_annotate_auto = True
mimic_enable_cameras = False
mimic_rendering_mode = "performance"
mimic_use_skillgen = False
domain_randomization_profile = "conservative"
robomimic_algo = "bc"
robomimic_normalize_training_actions = True
il_eval_num_rollouts = 10
il_eval_horizon = 400
```

Mimic subtask split:

| Subtask | Term signal | Offset range | Action noise | Interpolation | Fixed steps |
| --- | --- | ---: | ---: | ---: | ---: |
| approach | `approach` | 0-3 frames | 0.003 | 3 | 0 |
| grasp | `grasp` | 0-5 frames | 0.002 | 2 | 2 |
| lift | `lift` | 0-5 frames | 0.003 | 4 | 1 |
| place | `place` | 0-8 frames | 0.003 | 5 | 2 |
| release | none | 0 frames | 0.000 | 1 | 3 |

Generation policy:

- First run must be `smoke`.
- If `smoke` passes, run `first_real`.
- If `first_real` produces at least one success and the generated HDF5 passes inspection, allow `train_standard`.
- Do not enable cameras for the first state-BC path. Enable cameras only when training a visual BC policy and only after the state path passes.
- Do not train on `stress` output by default. Use `stress` for evaluation and for later experiments only.
- Import only generated trajectories whose success signal is true. Failed Mimic attempts stay in the Isaac Lab output folder for debugging and are not mixed into LeRobot training by default.

## Task 1: Version Gate And Script Contract

**Files:**
- Modify: `mcp_tools/lerobot_schemas.py`
- Modify: `device_bridges/isaac_lab_synthetic.py`
- Test: `tests/unit/test_lerobot_isaac_lab_e2e_contract.py`

- [ ] **Step 1: Write failing tests for current script contracts**

Create `tests/unit/test_lerobot_isaac_lab_e2e_contract.py`:

```python
from pathlib import Path

from device_bridges.isaac_lab_synthetic import IsaacLabSyntheticPipeline
from mcp_tools.lerobot_schemas import IsaacLabSyntheticRequest


def test_mimic_runner_uses_current_isaac_lab_generate_dataset_cli(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    output_root = dataset / "sidecar" / "isaac_lab_synthetic" / "latest"
    isaac_lab = tmp_path / "IsaacLab"
    script = isaac_lab / "scripts" / "imitation_learning" / "isaaclab_mimic" / "generate_dataset.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('fake')\n", encoding="utf-8")

    request = IsaacLabSyntheticRequest(
        dataset_path=str(dataset),
        output_root=str(output_root),
        isaac_lab_path=str(isaac_lab),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        enable_mimic=True,
        mimic_trials=3,
        mimic_num_envs=2,
        dry_run=False,
        require_physics_pass=False,
        require_articulation_pass=False,
        isaac_lab_task_name="ATR-Robotis-OMX-PickPlace-Mimic-v0",
        mimic_external_callback="integrations.isaac_lab_robotis_omx.external_callback.register",
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    command = pipeline._runner_command(
        request,
        kind="mimic",
        hook_summary={"hdf5_path": str(output_root / "hdf5" / "source_real_success_annotated.hdf5")},
        smoke_summary={"output_root": str(output_root)},
    )

    assert "--task" in command
    assert command[command.index("--task") + 1] == "ATR-Robotis-OMX-PickPlace-Mimic-v0"
    assert "--input_file" in command
    assert "--output_file" in command
    assert "--generation_num_trials" in command
    assert command[command.index("--generation_num_trials") + 1] == "3"
    assert "--num_envs" in command
    assert command[command.index("--num_envs") + 1] == "2"
    assert "--external_callback" in command
    assert "--headless" in command
    assert "--hdf5" not in command
    assert "--env-wrapper" not in command
    assert "--trials" not in command
    assert "--num-envs" not in command
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_mimic_runner_uses_current_isaac_lab_generate_dataset_cli -q
```

Expected: FAIL because `IsaacLabSyntheticRequest` does not yet expose `isaac_lab_task_name` and current command uses old flags.

- [ ] **Step 3: Add request fields**

In `mcp_tools/lerobot_schemas.py`, add to `IsaacLabSyntheticRequest`:

```python
    isaac_lab_task_name: str = "ATR-Robotis-OMX-PickPlace-Mimic-v0"
    isaac_lab_policy_task_name: str = "ATR-Robotis-OMX-PickPlace-v0"
    mimic_external_callback: str = "integrations.isaac_lab_robotis_omx.external_callback.register"
    mimic_annotate_auto: bool = True
    mimic_enable_cameras: bool = False
    mimic_use_skillgen: bool = False
    mimic_rendering_mode: str = "performance"
    domain_randomization_profile: str = "conservative"
    robomimic_algo: str = "bc"
    robomimic_train_name: str = "robotis_omx_pickplace_bc"
    robomimic_normalize_training_actions: bool = True
    il_eval_num_rollouts: int = Field(default=10, ge=1, le=200)
    il_eval_horizon: int = Field(default=400, ge=1, le=5000)
```

- [ ] **Step 4: Replace Mimic runner command**

In `device_bridges/isaac_lab_synthetic.py`, update `_runner_command()` for `kind == "mimic"`:

```python
        if kind == "mimic":
            script = isaac_lab_root / MIMIC_SCRIPT_RELATIVE_PATHS["generate_dataset"]
            generated_hdf5 = output_root / "mimic" / "generated_dataset.hdf5"
            command = [
                str(isaac_python),
                str(script),
                "--task",
                request.isaac_lab_task_name,
                "--input_file",
                hdf5_path,
                "--output_file",
                str(generated_hdf5),
                "--generation_num_trials",
                str(request.mimic_trials),
                "--num_envs",
                str(request.mimic_num_envs),
                "--external_callback",
                request.mimic_external_callback,
                "--headless",
            ]
            if request.mimic_enable_cameras:
                command.append("--enable_cameras")
                command.extend(["--rendering_mode", request.mimic_rendering_mode])
            if request.mimic_use_skillgen:
                command.append("--use_skillgen")
            return command
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_mimic_runner_uses_current_isaac_lab_generate_dataset_cli -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mcp_tools/lerobot_schemas.py device_bridges/isaac_lab_synthetic.py tests/unit/test_lerobot_isaac_lab_e2e_contract.py
git commit -m "feat: align Isaac Lab Mimic runner CLI"
```

## Task 2: External Robotis OMX Isaac Lab Registration

**Files:**
- Create: `integrations/isaac_lab_robotis_omx/__init__.py`
- Create: `integrations/isaac_lab_robotis_omx/external_callback.py`
- Create: `integrations/isaac_lab_robotis_omx/task_registry.py`
- Create: `tests/unit/test_isaac_lab_robotis_omx_registration.py`

- [ ] **Step 1: Write failing registration test**

Create `tests/unit/test_isaac_lab_robotis_omx_registration.py`:

```python
import importlib


def test_external_callback_registers_expected_task_names_without_launching_sim() -> None:
    callback = importlib.import_module("integrations.isaac_lab_robotis_omx.external_callback")
    accepted_args = callback.register()
    assert isinstance(accepted_args, list)

    registry = importlib.import_module("integrations.isaac_lab_robotis_omx.task_registry")
    assert registry.MIMIC_TASK_NAME == "ATR-Robotis-OMX-PickPlace-Mimic-v0"
    assert registry.POLICY_TASK_NAME == "ATR-Robotis-OMX-PickPlace-v0"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/unit/test_isaac_lab_robotis_omx_registration.py -q
```

Expected: FAIL because the package does not exist.

- [ ] **Step 3: Add package files**

Create `integrations/isaac_lab_robotis_omx/__init__.py`:

```python
"""Robotis OMX Isaac Lab integration package."""

from .external_callback import register

__all__ = ["register"]
```

Create `integrations/isaac_lab_robotis_omx/task_registry.py`:

```python
from __future__ import annotations

import gymnasium as gym

MIMIC_TASK_NAME = "ATR-Robotis-OMX-PickPlace-Mimic-v0"
POLICY_TASK_NAME = "ATR-Robotis-OMX-PickPlace-v0"


def register_tasks() -> None:
    """Register Robotis OMX Isaac Lab tasks exactly once."""
    if POLICY_TASK_NAME not in gym.envs.registry:
        gym.register(
            id=POLICY_TASK_NAME,
            entry_point="isaaclab.envs:ManagerBasedRLEnv",
            disable_env_checker=True,
            kwargs={
                "env_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_env_cfg:RobotisOMXPickPlaceEnvCfg",
                "robomimic_bc_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robomimic:bc.json",
            },
        )
    if MIMIC_TASK_NAME not in gym.envs.registry:
        gym.register(
            id=MIMIC_TASK_NAME,
            entry_point="integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_mimic_env:RobotisOMXPickPlaceMimicEnv",
            disable_env_checker=True,
            kwargs={
                "env_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_mimic_env_cfg:RobotisOMXPickPlaceMimicEnvCfg",
                "robomimic_bc_cfg_entry_point": "integrations.isaac_lab_robotis_omx.robomimic:bc.json",
            },
        )
```

Create `integrations/isaac_lab_robotis_omx/external_callback.py`:

```python
from __future__ import annotations

from .task_registry import register_tasks


def register() -> list[str]:
    """Callback entry point used by Isaac Lab scripts before parsing unknown args."""
    register_tasks()
    return [
        "--robotis-domain-randomization-profile",
        "--robotis-stage-path",
        "--robotis-output-root",
    ]
```

- [ ] **Step 4: Run test**

Run:

```bash
pytest tests/unit/test_isaac_lab_robotis_omx_registration.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add integrations/isaac_lab_robotis_omx tests/unit/test_isaac_lab_robotis_omx_registration.py
git commit -m "feat: add Robotis OMX Isaac Lab task registration"
```

## Task 3: HDF5 Adapter And Mimic Annotation Contract

**Files:**
- Create: `device_bridges/isaac_lab_hdf5.py`
- Modify: `device_bridges/isaac_lab_synthetic.py`
- Test: `tests/unit/test_lerobot_isaac_lab_e2e_contract.py`

- [ ] **Step 1: Write failing HDF5 contract test**

Append to `tests/unit/test_lerobot_isaac_lab_e2e_contract.py`:

```python
import json
import h5py

from device_bridges.isaac_lab_hdf5 import validate_isaac_lab_hdf5_contract


def test_hdf5_contract_requires_env_args_and_datagen_info(tmp_path: Path) -> None:
    hdf5_path = tmp_path / "bad.hdf5"
    with h5py.File(hdf5_path, "w") as handle:
        data = handle.create_group("data")
        demo = data.create_group("demo_000000")
        demo.attrs["num_samples"] = 2
        demo.create_dataset("actions", data=[[0.0], [1.0]])

    report = validate_isaac_lab_hdf5_contract(
        hdf5_path,
        expected_env_name="ATR-Robotis-OMX-PickPlace-Mimic-v0",
    )

    assert report["ok"] is False
    assert "ENV_ARGS_MISSING" in report["blockers"]
    assert "DATAGEN_INFO_MISSING" in report["blockers"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_hdf5_contract_requires_env_args_and_datagen_info -q
```

Expected: FAIL because `device_bridges.isaac_lab_hdf5` does not exist.

- [ ] **Step 3: Implement HDF5 contract validator**

Create `device_bridges/isaac_lab_hdf5.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_env_args(attrs: Any) -> dict[str, Any]:
    raw = attrs.get("env_args")
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


def validate_isaac_lab_hdf5_contract(path: Path, *, expected_env_name: str) -> dict[str, Any]:
    import h5py

    blockers: list[str] = []
    demos: list[str] = []
    path = Path(path).expanduser()
    if not path.is_file():
        return {"ok": False, "path": str(path), "blockers": ["HDF5_FILE_MISSING"], "demo_count": 0}

    with h5py.File(path, "r") as handle:
        env_args = _load_env_args(handle.attrs)
        env_name = str(env_args.get("env_name") or "")
        if not env_args:
            blockers.append("ENV_ARGS_MISSING")
        elif env_name != expected_env_name:
            blockers.append("ENV_NAME_MISMATCH")

        data = handle.get("data")
        if data is None:
            blockers.append("DATA_GROUP_MISSING")
        else:
            demos = sorted(str(name) for name in data.keys() if str(name).startswith("demo_"))
            if not demos:
                blockers.append("DEMO_GROUPS_MISSING")
            for demo_name in demos:
                demo = data[demo_name]
                if "actions" not in demo:
                    blockers.append(f"{demo_name}:ACTIONS_MISSING")
                if "obs" not in demo:
                    blockers.append(f"{demo_name}:OBS_MISSING")
                    blockers.append("DATAGEN_INFO_MISSING")
                    continue
                if "datagen_info" not in demo["obs"]:
                    blockers.append("DATAGEN_INFO_MISSING")
                else:
                    datagen = demo["obs"]["datagen_info"]
                    for key in ("object_pose", "eef_pose", "target_eef_pose", "subtask_term_signals"):
                        if key not in datagen:
                            blockers.append(f"DATAGEN_{key.upper()}_MISSING")

    return {
        "ok": not blockers,
        "path": str(path),
        "expected_env_name": expected_env_name,
        "blockers": sorted(set(blockers)),
        "demo_count": len(demos),
        "demos": demos,
    }
```

- [ ] **Step 4: Run contract test**

Run:

```bash
pytest tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_hdf5_contract_requires_env_args_and_datagen_info -q
```

Expected: PASS.

- [ ] **Step 5: Move HDF5 writer logic**

Move HDF5 export helpers out of `device_bridges/isaac_lab_synthetic.py` into `device_bridges/isaac_lab_hdf5.py` behind functions:

```python
def export_lerobot_success_episodes_to_isaac_lab_hdf5(...) -> dict[str, Any]:
    ...

def import_mimic_successes_from_hdf5(...) -> dict[str, Any]:
    ...
```

The export function must set:

```python
handle.attrs["env_args"] = json.dumps({
    "env_name": request.isaac_lab_task_name,
    "type": 2,
    "env_kwargs": {},
})
```

Each demo must contain:

```text
data/demo_000000/actions
data/demo_000000/obs/joint_pos
data/demo_000000/obs/gripper_state
data/demo_000000/obs/object_pose
data/demo_000000/obs/eef_pose
data/demo_000000/obs/datagen_info/object_pose
data/demo_000000/obs/datagen_info/eef_pose
data/demo_000000/obs/datagen_info/target_eef_pose
data/demo_000000/obs/datagen_info/subtask_term_signals/approach
data/demo_000000/obs/datagen_info/subtask_term_signals/grasp
data/demo_000000/obs/datagen_info/subtask_term_signals/lift
data/demo_000000/obs/datagen_info/subtask_term_signals/place
```

The final `release` step can be inferred from the remaining trajectory tail, so its termination signal is not required in the same way as the earlier boundaries.

- [ ] **Step 6: Commit**

```bash
git add device_bridges/isaac_lab_hdf5.py device_bridges/isaac_lab_synthetic.py tests/unit/test_lerobot_isaac_lab_e2e_contract.py
git commit -m "feat: add Isaac Lab HDF5 contract adapter"
```

## Task 4: Robotis OMX Manager-Based Env And Mimic Helpers

**Files:**
- Create: `integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_env_cfg.py`
- Create: `integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_mimic_env.py`
- Create: `integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_mimic_env_cfg.py`
- Create: `integrations/isaac_lab_robotis_omx/mdp/observations.py`
- Create: `integrations/isaac_lab_robotis_omx/mdp/events.py`
- Create: `integrations/isaac_lab_robotis_omx/mdp/terminations.py`
- Create: `integrations/isaac_lab_robotis_omx/robomimic/bc.json`
- Test: `tests/unit/test_isaac_lab_robotis_omx_registration.py`

- [ ] **Step 1: Add import-level tests for required helper names**

Append to `tests/unit/test_isaac_lab_robotis_omx_registration.py`:

```python
def test_mimic_env_class_exposes_required_helper_methods() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.robotis_omx_pickplace_mimic_env")
    cls = module.RobotisOMXPickPlaceMimicEnv
    for name in (
        "get_robot_eef_pose",
        "target_eef_pose_to_action",
        "action_to_target_eef_pose",
        "actions_to_gripper_actions",
        "get_object_poses",
        "get_subtask_term_signals",
    ):
        assert callable(getattr(cls, name))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/unit/test_isaac_lab_robotis_omx_registration.py::test_mimic_env_class_exposes_required_helper_methods -q
```

Expected: FAIL because env files do not exist.

- [ ] **Step 3: Implement first state-based Mimic helper class**

Create `integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_mimic_env.py` using the Franka example as the local pattern:

```python
from __future__ import annotations

from collections.abc import Sequence

import torch

import isaaclab.utils.math as PoseUtils
from isaaclab.envs import ManagerBasedRLMimicEnv


class RobotisOMXPickPlaceMimicEnv(ManagerBasedRLMimicEnv):
    """Mimic-compatible Robotis OMX pick/place environment."""

    def get_robot_eef_pose(self, eef_name: str, env_ids: Sequence[int] | None = None) -> torch.Tensor:
        if env_ids is None:
            env_ids = slice(None)
        eef_pos = self.obs_buf["policy"]["eef_pos"][env_ids]
        eef_quat = self.obs_buf["policy"]["eef_quat"][env_ids]
        return PoseUtils.make_pose(eef_pos, PoseUtils.matrix_from_quat(eef_quat))

    def target_eef_pose_to_action(
        self,
        target_eef_pose_dict: dict,
        gripper_action_dict: dict,
        action_noise_dict: dict | None = None,
        env_id: int = 0,
    ) -> torch.Tensor:
        eef_name = list(self.cfg.subtask_configs.keys())[0]
        target_eef_pose = target_eef_pose_dict[eef_name]
        target_pos, target_rot = PoseUtils.unmake_pose(target_eef_pose)
        curr_pose = self.get_robot_eef_pose(eef_name, env_ids=[env_id])[0]
        curr_pos, curr_rot = PoseUtils.unmake_pose(curr_pose)
        delta_position = target_pos - curr_pos
        delta_rot_mat = target_rot.matmul(curr_rot.transpose(-1, -2))
        delta_quat = PoseUtils.quat_from_matrix(delta_rot_mat)
        delta_rotation = PoseUtils.axis_angle_from_quat(delta_quat)
        pose_action = torch.cat([delta_position, delta_rotation], dim=0)
        if action_noise_dict is not None:
            pose_action = torch.clamp(
                pose_action + action_noise_dict[eef_name] * torch.randn_like(pose_action),
                -1.0,
                1.0,
            )
        gripper_action = gripper_action_dict[eef_name]
        return torch.cat([pose_action, gripper_action], dim=0)

    def action_to_target_eef_pose(self, action: torch.Tensor) -> dict[str, torch.Tensor]:
        eef_name = list(self.cfg.subtask_configs.keys())[0]
        delta_position = action[:, :3]
        delta_rotation = action[:, 3:6]
        curr_pose = self.get_robot_eef_pose(eef_name, env_ids=None)
        curr_pos, curr_rot = PoseUtils.unmake_pose(curr_pose)
        target_pos = curr_pos + delta_position
        delta_rotation_angle = torch.linalg.norm(delta_rotation, dim=-1, keepdim=True)
        delta_rotation_axis = delta_rotation / torch.clamp(delta_rotation_angle, min=1.0e-6)
        is_zero = torch.isclose(delta_rotation_angle, torch.zeros_like(delta_rotation_angle)).squeeze(1)
        delta_rotation_axis[is_zero] = torch.zeros_like(delta_rotation_axis)[is_zero]
        delta_quat = PoseUtils.quat_from_angle_axis(delta_rotation_angle.squeeze(1), delta_rotation_axis).squeeze(0)
        target_rot = PoseUtils.matrix_from_quat(delta_quat).matmul(curr_rot)
        return {eef_name: PoseUtils.make_pose(target_pos, target_rot).clone()}

    def actions_to_gripper_actions(self, actions: torch.Tensor) -> dict[str, torch.Tensor]:
        eef_name = list(self.cfg.subtask_configs.keys())[0]
        return {eef_name: actions[:, -1:]}

    def get_subtask_term_signals(self, env_ids: Sequence[int] | None = None) -> dict[str, torch.Tensor]:
        if env_ids is None:
            env_ids = slice(None)
        terms = self.obs_buf["subtask_terms"]
        return {
            "approach": terms["approach"][env_ids],
            "grasp": terms["grasp"][env_ids],
            "lift": terms["lift"][env_ids],
            "place": terms["place"][env_ids],
        }
```

- [ ] **Step 4: Add Mimic config with minimal subtasks**

Create `integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_mimic_env_cfg.py`:

```python
from __future__ import annotations

from isaaclab.envs.mimic_env_cfg import MimicEnvCfg, SubTaskConfig
from isaaclab.utils.configclass import configclass

from .robotis_omx_pickplace_env_cfg import RobotisOMXPickPlaceEnvCfg


@configclass
class RobotisOMXPickPlaceMimicEnvCfg(RobotisOMXPickPlaceEnvCfg, MimicEnvCfg):
    """Mimic config for Robotis OMX pick/place."""

    def __post_init__(self):
        super().__post_init__()
        self.datagen_config.name = "robotis_omx_pickplace"
        self.datagen_config.generation_guarantee = True
        self.datagen_config.generation_keep_failed = False
        self.datagen_config.generation_num_trials = 20
        self.datagen_config.generation_select_src_per_subtask = False
        self.datagen_config.generation_transform_first_robot_pose = False
        self.datagen_config.generation_interpolate_from_last_target_pose = True
        self.datagen_config.max_num_failures = 50
        self.datagen_config.seed = 42
        self.subtask_configs["omx"] = [
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal="approach",
                subtask_term_offset_range=(0, 3),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 3},
                action_noise=0.003,
                num_interpolation_steps=3,
                num_fixed_steps=0,
                apply_noise_during_interpolation=False,
                description="Move end effector near red cube",
                next_subtask_description="Close gripper on red cube",
            ),
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal="grasp",
                subtask_term_offset_range=(0, 5),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 3},
                action_noise=0.002,
                num_interpolation_steps=2,
                num_fixed_steps=2,
                apply_noise_during_interpolation=False,
                description="Grasp red cube",
                next_subtask_description="Lift red cube",
            ),
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal="lift",
                subtask_term_offset_range=(0, 5),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 3},
                action_noise=0.003,
                num_interpolation_steps=4,
                num_fixed_steps=1,
                apply_noise_during_interpolation=False,
                description="Lift red cube",
                next_subtask_description="Move to place target",
            ),
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal="place",
                subtask_term_offset_range=(0, 8),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 3},
                action_noise=0.003,
                num_interpolation_steps=5,
                num_fixed_steps=2,
                apply_noise_during_interpolation=False,
                description="Place red cube at target",
                next_subtask_description="Release gripper",
            ),
            SubTaskConfig(
                object_ref="red_cube",
                subtask_term_signal=None,
                subtask_term_offset_range=(0, 0),
                selection_strategy="nearest_neighbor_object",
                selection_strategy_kwargs={"nn_k": 3},
                action_noise=0.0,
                num_interpolation_steps=1,
                num_fixed_steps=3,
                apply_noise_during_interpolation=False,
                description="Release gripper and hold final state",
            ),
        ]
```

- [ ] **Step 5: Add base env config**

Create `robotis_omx_pickplace_env_cfg.py` by adapting Isaac Lab manager-based manipulation configs. The first pass should be state-based and must expose these names:

```python
class RobotisOMXPickPlaceEnvCfg(ManagerBasedRLEnvCfg):
    scene: RobotisOMXSceneCfg = RobotisOMXSceneCfg(num_envs=1, env_spacing=2.0)
    observations: RobotisOMXObservationsCfg = RobotisOMXObservationsCfg()
    actions: RobotisOMXActionsCfg = RobotisOMXActionsCfg()
    events: RobotisOMXEventsCfg = RobotisOMXEventsCfg()
    terminations: RobotisOMXTerminationsCfg = RobotisOMXTerminationsCfg()
```

Required observation keys under `policy`:

```text
joint_pos
joint_vel
gripper_state
eef_pos
eef_quat
object_pose
```

Required `obs_buf["subtask_terms"]` keys:

```text
approach
grasp
lift
place
```

- [ ] **Step 6: Run import tests**

Run:

```bash
pytest tests/unit/test_isaac_lab_robotis_omx_registration.py -q
```

Expected: PASS for import and helper existence. Runtime instantiation is tested in Task 8 with Isaac Sim.

- [ ] **Step 7: Commit**

```bash
git add integrations/isaac_lab_robotis_omx tests/unit/test_isaac_lab_robotis_omx_registration.py
git commit -m "feat: add Robotis OMX Mimic env contract"
```

## Task 5: Actual Domain Randomization Events

**Files:**
- Create: `integrations/isaac_lab_robotis_omx/domain_randomization.py`
- Modify: `integrations/isaac_lab_robotis_omx/mdp/events.py`
- Modify: `integrations/isaac_lab_robotis_omx/robotis_omx_pickplace_env_cfg.py`
- Test: `tests/unit/test_isaac_lab_robotis_omx_registration.py`

- [ ] **Step 1: Add unit test for profile values**

Append:

```python
def test_domain_randomization_profiles_are_bounded() -> None:
    module = importlib.import_module("integrations.isaac_lab_robotis_omx.domain_randomization")
    profiles = module.DOMAIN_RANDOMIZATION_PROFILES
    assert set(profiles) == {"off", "conservative", "standard", "stress"}
    for profile in profiles.values():
        lo, hi = profile["cube_xy_m"]
        assert lo <= hi
        assert -0.105 <= lo <= 0.105
        assert -0.105 <= hi <= 0.105
```

- [ ] **Step 2: Add profile module**

Create `domain_randomization.py`:

```python
from __future__ import annotations

DOMAIN_RANDOMIZATION_PROFILES = {
    "off": {
        "cube_xy_m": (0.0, 0.0),
        "cube_yaw_rad": (0.0, 0.0),
        "cube_mass_scale": (1.0, 1.0),
        "cube_static_friction": (0.9, 0.9),
        "cube_dynamic_friction": (0.7, 0.7),
        "gripper_inner_static_friction": (1.2, 1.2),
        "camera_pose_xyz_m": (0.0, 0.0),
    },
    "conservative": {
        "cube_xy_m": (-0.015, 0.015),
        "cube_yaw_rad": (-0.174533, 0.174533),
        "cube_mass_scale": (0.9, 1.1),
        "cube_static_friction": (0.8, 1.1),
        "cube_dynamic_friction": (0.6, 0.9),
        "gripper_inner_static_friction": (1.1, 1.4),
        "camera_pose_xyz_m": (-0.002, 0.002),
    },
    "standard": {
        "cube_xy_m": (-0.04, 0.04),
        "cube_yaw_rad": (-0.785398, 0.785398),
        "cube_mass_scale": (0.75, 1.25),
        "cube_static_friction": (0.7, 1.3),
        "cube_dynamic_friction": (0.5, 1.0),
        "gripper_inner_static_friction": (1.0, 1.6),
        "camera_pose_xyz_m": (-0.006, 0.006),
    },
    "stress": {
        "cube_xy_m": (-0.08, 0.08),
        "cube_yaw_rad": (-3.141593, 3.141593),
        "cube_mass_scale": (0.6, 1.5),
        "cube_static_friction": (0.45, 1.6),
        "cube_dynamic_friction": (0.35, 1.2),
        "gripper_inner_static_friction": (0.8, 1.8),
        "camera_pose_xyz_m": (-0.012, 0.012),
    },
}


def get_profile(name: str) -> dict[str, tuple[float, float]]:
    return DOMAIN_RANDOMIZATION_PROFILES.get(name, DOMAIN_RANDOMIZATION_PROFILES["conservative"])
```

- [ ] **Step 3: Add event config wiring**

In env config, add reset/startup events using Isaac Lab event terms:

```python
from isaaclab.envs import mdp
from isaaclab.managers import EventTermCfg as EventTerm
from isaaclab.managers import SceneEntityCfg


@configclass
class RobotisOMXEventsCfg:
    reset_scene = EventTerm(func=mdp.reset_scene_to_default, mode="reset")
    reset_cube_pose = EventTerm(
        func=events.reset_red_cube_a4,
        mode="reset",
        params={"asset_cfg": SceneEntityCfg("red_cube")},
    )
    cube_material = EventTerm(
        func=mdp.randomize_rigid_body_material,
        mode="startup",
        params={
            "asset_cfg": SceneEntityCfg("red_cube"),
            "static_friction_range": (0.8, 1.1),
            "dynamic_friction_range": (0.6, 0.9),
            "restitution_range": (0.0, 0.02),
            "num_buckets": 16,
        },
    )
    cube_mass = EventTerm(
        func=mdp.randomize_rigid_body_mass,
        mode="startup",
        params={
            "asset_cfg": SceneEntityCfg("red_cube"),
            "mass_distribution_params": (0.9, 1.1),
            "operation": "scale",
            "distribution": "uniform",
        },
    )
    cube_collider_offsets = EventTerm(
        func=mdp.randomize_rigid_body_collider_offsets,
        mode="startup",
        params={
            "asset_cfg": SceneEntityCfg("red_cube"),
            "rest_offset_distribution_params": (0.0, 0.001),
            "contact_offset_distribution_params": (0.003, 0.006),
            "distribution": "uniform",
        },
    )
```

- [ ] **Step 4: Implement A4 cube reset**

In `mdp/events.py`:

```python
from __future__ import annotations

import math
import torch

import isaaclab.utils.math as math_utils
from isaaclab.assets import RigidObject
from isaaclab.envs import ManagerBasedEnv
from isaaclab.managers import SceneEntityCfg

from ..domain_randomization import get_profile


def reset_red_cube_a4(env: ManagerBasedEnv, env_ids: torch.Tensor, asset_cfg: SceneEntityCfg) -> None:
    cube: RigidObject = env.scene[asset_cfg.name]
    profile_name = getattr(env.cfg, "domain_randomization_profile", "conservative")
    profile = get_profile(profile_name)
    xy_lo, xy_hi = profile["cube_xy_m"]
    yaw_lo, yaw_hi = profile["cube_yaw_rad"]
    root_state = cube.data.default_root_state[env_ids].clone()
    root_state[:, 0] += torch.empty(len(env_ids), device=env.device).uniform_(xy_lo, xy_hi)
    root_state[:, 1] += torch.empty(len(env_ids), device=env.device).uniform_(xy_lo, xy_hi)
    yaw = torch.empty(len(env_ids), device=env.device).uniform_(yaw_lo, yaw_hi)
    quat = math_utils.quat_from_euler_xyz(torch.zeros_like(yaw), torch.zeros_like(yaw), yaw)
    root_state[:, 3:7] = quat
    cube.write_root_pose_to_sim(root_state[:, :7], env_ids=env_ids)
    cube.write_root_velocity_to_sim(root_state[:, 7:], env_ids=env_ids)
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/unit/test_isaac_lab_robotis_omx_registration.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add integrations/isaac_lab_robotis_omx tests/unit/test_isaac_lab_robotis_omx_registration.py
git commit -m "feat: add Robotis OMX domain randomization profiles"
```

## Task 6: Annotation, Generation, IL Train, Eval Runners

**Files:**
- Create: `scripts/lerobot_isaac_lab_robomimic_train.py`
- Create: `scripts/lerobot_isaac_lab_robomimic_play.py`
- Create: `scripts/lerobot_isaac_lab_robomimic_robust_eval.py`
- Modify: `device_bridges/isaac_lab_synthetic.py`
- Modify: `device_bridges/lerobot_bridge.py`
- Test: `tests/unit/test_lerobot_isaac_lab_e2e_contract.py`

- [ ] **Step 1: Add command builder tests**

Append tests asserting these commands:

```python
def test_annotation_command_uses_external_callback(tmp_path: Path) -> None:
    request = IsaacLabSyntheticRequest(
        dataset_path=str(tmp_path / "dataset"),
        output_root=str(tmp_path / "out"),
        isaac_lab_path="/home/jin/IsaacLab",
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        isaac_lab_task_name="ATR-Robotis-OMX-PickPlace-Mimic-v0",
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    command = pipeline._annotation_command(request, tmp_path / "source.hdf5", tmp_path / "annotated.hdf5")
    assert "annotate_demos.py" in command[1]
    assert "--auto" in command
    assert "--external_callback" in command


def test_il_train_command_uses_wrapper_because_train_has_no_external_callback(tmp_path: Path) -> None:
    request = IsaacLabSyntheticRequest(
        dataset_path=str(tmp_path / "dataset"),
        output_root=str(tmp_path / "out"),
        isaac_sim_python="/home/jin/IsaacSim/python.sh",
        isaac_lab_policy_task_name="ATR-Robotis-OMX-PickPlace-v0",
        robomimic_algo="bc",
    )
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    command = pipeline._il_train_command(request, tmp_path / "generated_dataset.hdf5")
    assert command[1].endswith("scripts/lerobot_isaac_lab_robomimic_train.py")
    assert "--task" in command
    assert command[command.index("--task") + 1] == "ATR-Robotis-OMX-PickPlace-v0"
    assert "--dataset" in command
```

- [ ] **Step 2: Add robomimic wrappers**

Create `scripts/lerobot_isaac_lab_robomimic_train.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path

from integrations.isaac_lab_robotis_omx.external_callback import register


def main() -> None:
    register()
    isaac_lab = Path(sys.argv[sys.argv.index("--isaac-lab-path") + 1]) if "--isaac-lab-path" in sys.argv else Path("/home/jin/IsaacLab")
    if "--isaac-lab-path" in sys.argv:
        idx = sys.argv.index("--isaac-lab-path")
        del sys.argv[idx : idx + 2]
    script = isaac_lab / "scripts" / "imitation_learning" / "robomimic" / "train.py"
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
```

Create `scripts/lerobot_isaac_lab_robomimic_play.py` and `scripts/lerobot_isaac_lab_robomimic_robust_eval.py` with the same wrapper shape, replacing `train.py` with `play.py` or `robust_eval.py`.

- [ ] **Step 3: Add bridge command builders**

Add methods in `IsaacLabSyntheticPipeline`:

```python
    def _annotation_command(self, request: IsaacLabSyntheticRequest, input_file: Path, output_file: Path) -> list[str]:
        isaac_python = Path(request.isaac_sim_python).expanduser() if request.isaac_sim_python else DEFAULT_ISAAC_SIM_PYTHON
        isaac_lab_root = Path(request.isaac_lab_path).expanduser()
        script = isaac_lab_root / MIMIC_SCRIPT_RELATIVE_PATHS["annotate_demos"]
        command = [
            str(isaac_python),
            str(script),
            "--task",
            request.isaac_lab_task_name,
            "--input_file",
            str(input_file),
            "--output_file",
            str(output_file),
            "--external_callback",
            request.mimic_external_callback,
            "--headless",
        ]
        if request.mimic_annotate_auto:
            command.append("--auto")
        return command

    def _il_train_command(self, request: IsaacLabSyntheticRequest, dataset_file: Path) -> list[str]:
        isaac_python = Path(request.isaac_sim_python).expanduser() if request.isaac_sim_python else DEFAULT_ISAAC_SIM_PYTHON
        wrapper = self.repo_root / "scripts" / "lerobot_isaac_lab_robomimic_train.py"
        return [
            str(isaac_python),
            str(wrapper),
            "--isaac-lab-path",
            str(Path(request.isaac_lab_path).expanduser()),
            "--task",
            request.isaac_lab_policy_task_name,
            "--algo",
            request.robomimic_algo,
            "--dataset",
            str(dataset_file),
            "--name",
            request.robomimic_train_name,
            "--log_dir",
            "robomimic",
        ] + (["--normalize_training_actions"] if request.robomimic_normalize_training_actions else [])
```

- [ ] **Step 4: Generalize job lifecycle**

In `device_bridges/lerobot_bridge.py`, reuse the current Isaac Lab runner job mechanism but allow kinds:

```python
ISAAC_LAB_JOB_KINDS = {"annotate", "mimic", "il_train", "il_eval", "rl_teacher"}
```

Every job manifest must contain:

```json
{
  "kind": "il_train",
  "job_id": "isaac_lab_il_train_...",
  "command": ["..."],
  "cwd": "/home/jin/IsaacLab",
  "log_path": ".../il/robomimic/train_stdout.log",
  "status": "RUNNING"
}
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/unit/test_lerobot_isaac_lab_e2e_contract.py tests/unit/test_lerobot_bridge.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/lerobot_isaac_lab_robomimic_train.py scripts/lerobot_isaac_lab_robomimic_play.py scripts/lerobot_isaac_lab_robomimic_robust_eval.py device_bridges/isaac_lab_synthetic.py device_bridges/lerobot_bridge.py tests/unit
git commit -m "feat: add Isaac Lab IL runner wrappers"
```

## Task 7: API And GUI E2E Controls

**Files:**
- Modify: `app/main.py`
- Modify: `web/templates/lerobot.html`
- Modify: `web/static/lerobot.js`
- Modify: `web/static/styles.css`
- Test: `tests/unit/test_lerobot_gui_static.py`

- [ ] **Step 1: Add GUI static test**

Add to `tests/unit/test_lerobot_gui_static.py`:

```python
def test_isaac_lab_tab_has_e2e_mimic_il_controls() -> None:
    html = _read_lerobot_html()
    for element_id in (
        "isaac-lab-run-e2e",
        "isaac-lab-annotate-source",
        "isaac-lab-generate-mimic",
        "isaac-lab-train-il",
        "isaac-lab-eval-il",
        "isaac-lab-domain-randomization-profile",
        "isaac-lab-e2e-status-card",
    ):
        assert element_id in html
```

- [ ] **Step 2: Add API endpoints**

In `app/main.py`, add:

```python
@app.post("/api/lerobot/isaac-lab/annotate")
async def post_lerobot_isaac_lab_annotate(req: IsaacLabSyntheticRequest) -> dict[str, object]:
    return _lerobot_bridge().isaac_lab_annotate(req.model_dump(mode="json"))


@app.post("/api/lerobot/isaac-lab/generate-mimic")
async def post_lerobot_isaac_lab_generate_mimic(req: IsaacLabSyntheticRequest) -> dict[str, object]:
    return _lerobot_bridge().isaac_lab_generate_mimic(req.model_dump(mode="json"))


@app.post("/api/lerobot/isaac-lab/train-il")
async def post_lerobot_isaac_lab_train_il(req: IsaacLabSyntheticRequest) -> dict[str, object]:
    return _lerobot_bridge().isaac_lab_train_il(req.model_dump(mode="json"))


@app.post("/api/lerobot/isaac-lab/eval-il")
async def post_lerobot_isaac_lab_eval_il(req: IsaacLabSyntheticRequest) -> dict[str, object]:
    return _lerobot_bridge().isaac_lab_eval_il(req.model_dump(mode="json"))


@app.post("/api/lerobot/isaac-lab/run-e2e")
async def post_lerobot_isaac_lab_run_e2e(req: IsaacLabSyntheticRequest) -> dict[str, object]:
    return _lerobot_bridge().isaac_lab_run_e2e(req.model_dump(mode="json"))
```

- [ ] **Step 3: Add GUI controls**

In the Isaac Lab tab, add controls:

```html
<select id="isaac-lab-domain-randomization-profile">
  <option value="conservative" selected>conservative</option>
  <option value="off">off</option>
  <option value="standard">standard</option>
  <option value="stress">stress eval only</option>
</select>
<button id="isaac-lab-annotate-source" type="button">Annotate Source HDF5</button>
<button id="isaac-lab-generate-mimic" type="button">Generate Mimic Dataset</button>
<button id="isaac-lab-train-il" type="button">Train Isaac Lab IL</button>
<button id="isaac-lab-eval-il" type="button">Evaluate Isaac Lab IL</button>
<button id="isaac-lab-run-e2e" type="button">Run E2E Mimic + IL</button>
<article id="isaac-lab-e2e-status-card" class="status-card"></article>
```

- [ ] **Step 4: Add JS payload and bindings**

In `web/static/lerobot.js`, extend the Isaac Lab payload:

```javascript
domain_randomization_profile: valueOf("isaac-lab-domain-randomization-profile", "conservative"),
isaac_lab_task_name: valueOf("isaac-lab-task-name", "ATR-Robotis-OMX-PickPlace-Mimic-v0"),
isaac_lab_policy_task_name: valueOf("isaac-lab-policy-task-name", "ATR-Robotis-OMX-PickPlace-v0"),
robomimic_algo: "bc",
robomimic_normalize_training_actions: true,
```

Bind:

```javascript
bind("isaac-lab-annotate-source", (event) => runIsaacSyntheticAction("Annotate source HDF5", "/api/lerobot/isaac-lab/annotate", actionStatusFromEvent(event), 300000));
bind("isaac-lab-generate-mimic", (event) => runIsaacSyntheticAction("Generate Mimic dataset", "/api/lerobot/isaac-lab/generate-mimic", actionStatusFromEvent(event), 900000, { enable_mimic: true }));
bind("isaac-lab-train-il", (event) => runIsaacSyntheticAction("Train Isaac Lab IL", "/api/lerobot/isaac-lab/train-il", actionStatusFromEvent(event), 900000));
bind("isaac-lab-eval-il", (event) => runIsaacSyntheticAction("Evaluate Isaac Lab IL", "/api/lerobot/isaac-lab/eval-il", actionStatusFromEvent(event), 900000));
bind("isaac-lab-run-e2e", (event) => runIsaacSyntheticAction("Run E2E Mimic + IL", "/api/lerobot/isaac-lab/run-e2e", actionStatusFromEvent(event), 1800000, { enable_mimic: true }));
```

- [ ] **Step 5: Run GUI tests**

Run:

```bash
pytest tests/unit/test_lerobot_gui_static.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/main.py web/templates/lerobot.html web/static/lerobot.js web/static/styles.css tests/unit/test_lerobot_gui_static.py
git commit -m "feat: add Isaac Lab E2E Mimic IL GUI controls"
```

## Task 8: Runtime Smoke And E2E Verification

**Files:**
- Modify: `scripts/lerobot_synthetic_e2e_smoke.py`
- Create: `scripts/lerobot_isaac_lab_e2e_smoke.py`
- Modify: `device_bridges/isaac_lab_synthetic.py`

- [ ] **Step 1: Add non-actuating smoke command**

Create `scripts/lerobot_isaac_lab_e2e_smoke.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from device_bridges.lerobot_bridge import LeRobotBridge


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--isaac-lab-path", default="/home/jin/IsaacLab")
    parser.add_argument("--isaac-sim-python", default="/home/jin/IsaacSim/python.sh")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--num-envs", type=int, default=1)
    parser.add_argument("--domain-randomization-profile", default="conservative")
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    bridge = LeRobotBridge()
    payload = {
        "dataset_path": args.dataset_path,
        "isaac_lab_path": args.isaac_lab_path,
        "isaac_sim_python": args.isaac_sim_python,
        "mimic_trials": args.trials,
        "mimic_num_envs": args.num_envs,
        "domain_randomization_profile": args.domain_randomization_profile,
        "dry_run": args.dry_run,
        "enable_mimic": True,
        "require_physics_pass": False,
        "require_articulation_pass": False,
    }
    result = bridge.isaac_lab_run_e2e(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run dry smoke**

Run:

```bash
python scripts/lerobot_isaac_lab_e2e_smoke.py \
  --dataset-path artifacts/lerobot/synthetic_e2e_gui/five-by-ten \
  --dry-run
```

Expected: PASS and writes dry-run E2E summary without launching Isaac Sim.

- [ ] **Step 3: Run one-trial runtime smoke**

Run only after Isaac Sim is free and no live teleop/record process is active:

```bash
python scripts/lerobot_isaac_lab_e2e_smoke.py \
  --dataset-path artifacts/lerobot/synthetic_e2e_gui/five-by-ten \
  --trials 1 \
  --num-envs 1 \
  --domain-randomization-profile conservative
```

Expected:

- HDF5 source export succeeds.
- Annotation command starts and exits 0.
- Mimic generation command starts and exits 0.
- Generated HDF5 exists.
- Import creates at least one `isaac_lab_mimic` success row, or reports a structured `MIMIC_ZERO_SUCCESS` blocker with the generated failure artifacts.
- IL training starts only if generated successes exist.

- [ ] **Step 4: Commit**

```bash
git add scripts/lerobot_isaac_lab_e2e_smoke.py scripts/lerobot_synthetic_e2e_smoke.py device_bridges/isaac_lab_synthetic.py
git commit -m "test: add Isaac Lab Mimic IL E2E smoke"
```

## Task 9: Acceptance Gate

The E2E implementation is acceptable only when all checks below pass:

- `pytest tests/unit/test_isaac_lab_robotis_omx_registration.py -q`
- `pytest tests/unit/test_lerobot_isaac_lab_e2e_contract.py -q`
- `pytest tests/unit/test_lerobot_bridge.py -q`
- `pytest tests/unit/test_lerobot_gui_static.py -q`
- `python scripts/lerobot_isaac_lab_e2e_smoke.py --dataset-path artifacts/lerobot/synthetic_e2e_gui/five-by-ten --dry-run`
- One-trial live Isaac Lab smoke runs without changing live teleoperation or recording code.

The GUI must show these statuses:

- Version Gate
- HDF5 Source
- Annotation
- Mimic Generation
- Domain Randomization Profile
- Generated Success Import
- Isaac Lab IL Training
- Isaac Lab IL Evaluation
- LeRobot Training Exposure

## Scope Boundaries

Do not change:

- live LeRobot teleoperation behavior
- live recording behavior
- existing Isaac Sim mirror runtime
- current LeRobot training command construction
- physical robot control from Isaac Lab

Do change:

- Isaac Lab synthetic sidecar flow
- HDF5 export/annotation/generation contracts
- Isaac Lab task registration
- GUI controls for the Isaac Lab tab
- source labels and status reporting

## Execution Order Summary

1. Fix command contracts and schema.
2. Add external task registration package.
3. Harden HDF5 export/validation.
4. Add the state-based Robotis OMX ManagerBasedRLMimicEnv.
5. Add actual domain randomization event terms.
6. Add annotation, generation, IL train, and eval wrappers.
7. Wire API and GUI.
8. Run dry smoke.
9. Run one-trial live Isaac Lab smoke.
10. Scale Mimic trials only after one-trial smoke is stable.
