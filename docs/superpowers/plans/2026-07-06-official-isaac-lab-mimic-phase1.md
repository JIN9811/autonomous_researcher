# Official Isaac Lab Mimic Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify that the local official Isaac Lab Mimic install and Robotis OMX task registry are ready before changing the data-generation pipeline.

**Architecture:** Phase 1 is a non-mutating validation gate. It checks imports, official script presence, external task registration, gym registry entries, and config parsing for Robotis OMX Mimic and policy tasks.

**Tech Stack:** Isaac Lab 3.0.0 beta checkout, Isaac Sim Python via `/home/jin/IsaacLab/isaaclab.sh -p`, Gymnasium task registry, local `integrations.isaac_lab_robotis_omx` callback.

---

### Task 1: Official Reference Completeness

**Files:**
- Inspect: `/home/jin/IsaacLab/scripts/imitation_learning/isaaclab_mimic/annotate_demos.py`
- Inspect: `/home/jin/IsaacLab/scripts/imitation_learning/isaaclab_mimic/generate_dataset.py`
- Inspect: `/home/jin/IsaacLab/scripts/tools/replay_demos.py`
- Inspect: `/home/jin/IsaacLab/source/isaaclab/isaaclab/envs/mimic_env_cfg.py`
- Inspect: `/home/jin/IsaacLab/source/isaaclab/isaaclab/envs/manager_based_rl_mimic_env.py`
- Reference: `references/official_isaac_lab_mimic/`

- [x] **Step 1: Verify copied reference file count**

Run:

```bash
find references/official_isaac_lab_mimic -type f | sort | wc -l
```

Expected: at least `20`.

- [x] **Step 2: Verify official script names are present in the reference copy**

Run:

```bash
test -f references/official_isaac_lab_mimic/scripts/imitation_learning/isaaclab_mimic/annotate_demos.py
test -f references/official_isaac_lab_mimic/scripts/imitation_learning/isaaclab_mimic/generate_dataset.py
test -f references/official_isaac_lab_mimic/scripts/tools/replay_demos.py
```

Expected: exit code `0`.

Observed: `20` reference files and `reference_scripts_ok`.

### Task 2: Isaac Lab Mimic Import Gate

**Files:**
- Runtime: `/home/jin/IsaacLab/isaaclab.sh`
- Import: `isaaclab`
- Import: `isaaclab_mimic`

- [x] **Step 1: Run official import check**

Run:

```bash
/home/jin/IsaacLab/isaaclab.sh -p - <<'PY'
from pathlib import Path
import isaaclab
import isaaclab_mimic
print("isaaclab", Path(isaaclab.__file__).resolve())
print("isaaclab_mimic", Path(isaaclab_mimic.__file__).resolve())
PY
```

Expected:

```text
isaaclab /home/jin/IsaacLab/source/isaaclab/isaaclab/__init__.py
isaaclab_mimic /home/jin/IsaacLab/source/isaaclab_mimic/isaaclab_mimic/__init__.py
```

Observed: both imports resolved to the expected `/home/jin/IsaacLab/source/...` paths.

### Task 3: Robotis OMX Task Registry Gate

**Files:**
- Import: `integrations/isaac_lab_robotis_omx/external_callback.py`
- Import: `integrations/isaac_lab_robotis_omx/task_registry.py`
- Config: `integrations/isaac_lab_robotis_omx/robotis_omx_physical_mimic_env_cfg.py`
- Config: `integrations/isaac_lab_robotis_omx/robotis_omx_physical_env_cfg.py`

- [x] **Step 1: Register Robotis OMX tasks in Isaac Lab Python**

Run:

```bash
PYTHONPATH=/home/jin/autonomous_researcher /home/jin/IsaacLab/isaaclab.sh -p - <<'PY'
import gymnasium as gym
from integrations.isaac_lab_robotis_omx.external_callback import register

remaining = register()
print("remaining_args", remaining)
required = [
    "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0",
    "ATR-Robotis-OMX-PickPlace-Physical-v0",
    "ATR-Robotis-OMX-PickPlace-Physical-State-v0",
]
for task in required:
    print(task, task in gym.envs.registry)
missing = [task for task in required if task not in gym.envs.registry]
if missing:
    raise SystemExit(f"missing task registry entries: {missing}")
PY
```

Expected: every task prints `True`.

- [x] **Step 2: Parse Robotis OMX configs without launching a simulation app**

Run:

```bash
PYTHONPATH=/home/jin/autonomous_researcher /home/jin/IsaacLab/isaaclab.sh -p - <<'PY'
from integrations.isaac_lab_robotis_omx.external_callback import register
from isaaclab_tasks.utils import parse_env_cfg

register()
for task in [
    "ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0",
    "ATR-Robotis-OMX-PickPlace-Physical-v0",
]:
    cfg = parse_env_cfg(task, num_envs=1, use_fabric=False)
    print(task, type(cfg).__name__)
    print("has_subtasks", bool(getattr(cfg, "subtask_configs", {})))
    print("has_success", hasattr(cfg.terminations, "success"))
PY
```

Expected:

```text
ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0 RobotisOMXPhysicalPickPlaceMimicEnvCfg
has_subtasks True
has_success True
ATR-Robotis-OMX-PickPlace-Physical-v0 RobotisOMXPhysicalPickPlaceEnvCfg
has_subtasks False
has_success True
```

The policy task may expose an empty `subtask_configs`; the Mimic task must expose real subtasks.

Observed:

```text
ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0 True
ATR-Robotis-OMX-PickPlace-Physical-v0 True
ATR-Robotis-OMX-PickPlace-Physical-State-v0 True
ATR-Robotis-OMX-PickPlace-Physical-Mimic-v0 RobotisOMXPhysicalPickPlaceMimicEnvCfg
has_subtasks True
has_success True
ATR-Robotis-OMX-PickPlace-Physical-v0 RobotisOMXPhysicalPickPlaceEnvCfg
has_subtasks False
has_success True
```

### Task 4: Phase 1 Status Report

**Files:**
- Update: `docs/superpowers/specs/2026-07-06-official-isaac-lab-mimic-integration-design.md`
- Update: `docs/superpowers/plans/2026-07-06-official-isaac-lab-mimic-phase1.md`

- [x] **Step 1: Record Phase 1 result in the chat response**

Report:

```text
Official Isaac Lab Mimic import: PASS/FAIL
Official reference scripts: PASS/FAIL
Robotis OMX gym registry: PASS/FAIL
Mimic config parse: PASS/FAIL
Next blocking task: source HDF5 replay or Mimic action adapter, depending on result
```

Observed Phase 1 status:

```text
Official Isaac Lab Mimic import: PASS
Official reference scripts: PASS
Robotis OMX gym registry: PASS
Mimic config parse: PASS
Next blocking task: source HDF5 replay through official replay_demos.py, then 3-subtask annotation.
```
