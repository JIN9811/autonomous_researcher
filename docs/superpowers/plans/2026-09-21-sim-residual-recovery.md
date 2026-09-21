# Simulated Residual Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run an isolated 5,000-step residual SAC pilot against frozen SmolVLA 080000, reporting normal full-cycle success and observed-fault recovery separately.

**Architecture:** Keep the existing Isaac benchmark as the simulator and frozen VLA client. Add an opt-in residual session that sends observable features and transitions to a separate SAC process over localhost. Pure feature/action/reward modules remain independent of Isaac so tests run without a simulator.

**Tech Stack:** Existing Python environments, NumPy, OpenCV, PyTorch, multiprocessing.connection, Isaac Lab, pytest, and ffmpeg; no new service or pretrained model dependency.

**Spec:** `docs/superpowers/specs/2026-09-21-sim-residual-recovery-design.md`

## Global Constraints

- The user-approved pilot budget is 5,000 training environment steps.
- Base: `outputs/train/20260903_3_train(smolvla)/checkpoints/080000/pretrained_model`.
- Scene: `runs/sim_policy_bench_20260921/registered_scene_v4_r2/omx_recorded_rgbd_benchmark.usda`.
- Calibration: the sealed benchmark `baseline_v1/calibration.json`.
- Base action queue remains 50 steps; execution remains 15 Hz with existing physics decimation.
- Residual offsets are bounded to ±5 degrees and slew to 1 degree per control step.
- Each episode allows up to 900 policy steps (60 simulated seconds).
- Simulator truth may supply labels/rewards, never actor observations.
- No production endpoint, hardware bridge, server restart, real robot command, scene-source edit, or base checkpoint overwrite.
- Existing unrelated worktree changes must remain untouched.
- No residual-policy implementation or training until the user reviews this plan and chooses execution.

## Review Focus

1. Base-target motion near a joint limit can defeat a residual slew clamp: intersect both constraints, and fail explicitly if no feasible offset exists (Task 1).
2. A terminal next observation must never come from the reset episode or require an extra VLA queue advancement (Task 4).
3. A requested disturbance that never creates a measurable fault must not inflate recovery rate (Tasks 2 and 5).
4. A resumed collector may restore learner state but cannot silently splice unrelated simulator transitions (Tasks 3 and 4).
5. RGB/depth mismatch, missed detections, and primary/mimic joint order must not become fabricated object evidence or wrong joint commands (Tasks 1 and 4).

## File map and execution environment

All new executable files below use prefix
`runs/sim_policy_bench_20260921/` (abbreviated **B** in prose only).

- `residual_observation.py`: camera features and finite, fixed-size observation history.
- `residual_action.py`: degree-space offset constraints; no simulation imports.
- `residual_reward.py`: potential, one-shot milestones, and fault accounting.
- `residual_sac.py`: actor, critics, replay buffer, updates, and serialization.
- `residual_server.py`: localhost learner protocol and immutable evaluation mode.
- `residual_session.py`: collector sequencing, reward/history state, and IPC client.
- `residual_perturbation.py`: seeded intervention decisions and ledger.
- `run_residual_bench.sh`: owned-process launcher with unique logs/output directories.
- `summarize_residual.py`: paired evaluation, Wilson intervals, video manifests.
- Corresponding `test_residual_*.py`: pure tests next to benchmark files.
- Modify benchmark `isaac_bench_runner.py` only behind explicit residual flags.
- Do not change `policy_server.py`: queue age can be tracked as episode action index modulo the sealed 50-step queue; verify the loaded policy reports 50.

Pure tests use `/home/jin/autonomous_researcher/.venv/bin/python`.
Base server uses `/home/jin/miniconda3/envs/lerobot-pi05-torch211/bin/python`.
Simulation uses `/home/jin/IsaacLab/isaaclab.sh -p` with `--headless --enable_cameras`, stdin `/dev/null`, and stdout/stderr to a regular logfile.

At execution start, use the worktree-isolation skill. The benchmark directory is
ignored, so a worktree does not contain its files automatically: copy only the
required benchmark source/fixtures into the isolated execution directory and
record their SHA256 hashes; reuse large sealed assets by read-only absolute path.
Never rebuild the registered scene in place. Keep the original baseline runner
available for comparison. Task checkpoints are local commits containing only
explicitly selected source/tests; force-add ignored source files only, never model
weights, recorded data, output videos, secrets, or mutable scene artifacts.

### Task 1: Observable features and safe residual mapping

**Files:** Create `residual_observation.py`, `residual_action.py`,
`test_residual_observation.py`, `test_residual_action.py` under B.

**Interfaces:**

```python
camera_features(rgb: np.ndarray, depth_visual: np.ndarray) -> np.ndarray # (5,)
frame_features(q_deg, qd_deg_s, base_deg, limits_deg, cameras) -> np.ndarray # (34,)
ObservationHistory.reset() -> None
ObservationHistory.push(frame34, previous_offset6, queue_age: int) -> np.ndarray # (109,)
bounded_target(base6, raw6, previous6, limits6x2) -> tuple # target6, offset6, mask6
```

- [ ] Write failing tests for empty/red/occluded masks, mismatched RGB/depth shape,
  NaN joints, history reset, primary joint order, zero correction, and infeasible limits.

```python
def test_zero_and_slew():
    limits = np.tile([-90., 90.], (6, 1))
    q, offset, _ = bounded_target(np.zeros(6), np.ones(6), np.zeros(6), limits)
    np.testing.assert_allclose(q, np.ones(6))
    np.testing.assert_allclose(offset, np.ones(6))
    q, _, _ = bounded_target(np.zeros(6), np.zeros(6), np.zeros(6), limits)
    np.testing.assert_array_equal(q, np.zeros(6))

def test_infeasible_slew_does_not_silently_jump():
    with pytest.raises(ValueError):
        bounded_target(np.full(6, 95.), np.zeros(6), np.zeros(6), np.tile([-90., 90.], (6, 1)))
```

- [ ] Run `.venv/bin/python -m pytest runs/sim_policy_bench_20260921/test_residual_observation.py runs/sim_policy_bench_20260921/test_residual_action.py -q`; confirm new missing implementations cause failure.
- [ ] Implement largest connected red component with the existing RGB thresholds
  and 20-pixel threshold; centroid normalized to [-1,1], area fraction, depth
  intensity divided by 255, and validity. Reject mismatched shapes. Invalid
  detections are five zeros. Normalize joints about range midpoint, velocities
  by 180 deg/s, and base errors by joint half-range; clip finite features to [-1,1].
  Reset history to zeros, then shift/append frames. Append previous offset / 5
  and queue age / 49. Joint names, not articulation order, define primary vectors.

```python
lo = np.maximum.reduce([np.full(6, -5.), previous6 - 1., limits6x2[:, 0] - base6])
hi = np.minimum.reduce([np.full(6, 5.), previous6 + 1., limits6x2[:, 1] - base6])
if np.any(lo > hi):
    raise ValueError('No feasible bounded residual target')
offset = np.clip(5. * np.clip(raw6, -1., 1.), lo, hi)
target = base6 + offset
```

- [ ] Repeat tests, including random finite commands and residual reset. Confirm
  no simulator pose/contact argument exists in feature interfaces.
- [ ] Commit only the four Task 1 source/test files after inspecting staged diff.

### Task 2: Reward shaping and truthful recovery labels

**Files:** Create `residual_reward.py`, `test_residual_reward.py`; consume existing
`task_contract.py` without relaxing its success rules.

**Interfaces:** `potential(phase: str, sample: Sample) -> float`;
`RewardTracker.step(previous_phase, previous_sample, task, sample, offset6, previous_offset6, terminated) -> dict`;
`FaultTracker.update(triggered: bool, phase: str, sample: Sample, dt: float, success: bool) -> dict`.
Trackers expose `reset()` and JSON-serializable state. `task` is TaskEvaluator.

- [ ] Write tests for potential telescoping, one-shot milestones after regrasp,
  held/hovering cubes receiving no placement bonus, and zero-fault denominator.

```python
def test_discounted_shaping_telescopes():
    phi = [0.2, 0.8, 0.1, 0.2]
    rewards = [0.99*b-a for a, b in zip(phi, phi[1:])]
    assert sum(0.99**i*r for i, r in enumerate(rewards)) == pytest.approx(-phi[0] + 0.99**3*phi[-1])
```

- [ ] Run the new reward tests and verify failure before implementation.
- [ ] Implement the explicit bounded potential (clip each distance term):

```python
def potential(phase, s):
    near = 1. - np.clip(s.tip_distance_m / .15, 0., 1.)
    center = 1. - np.clip(s.xy_error_m / .30, 0., 1.)
    home = 1. - np.clip(s.home_error_deg / 90., 0., 1.)
    return float({
        'home': 0., 'detect': 0., 'approach': near, 'grasping': near,
        'transport': 1. + center, 'ungrasping': 2. + center,
        'return_home': 3. + home, 'complete': 0.,
    }[phase])
```

  Use `gamma * phi_next - phi_previous`, terminal phi zero, truncated phi intact.
  Award five +1 bonuses once: first bilateral grasp, first lifted transport,
  first verified centered release, first return_home transition, and success.
  Add +20 once for full success and the specified residual penalties using
  actual applied offsets divided by 5 degrees, not the pre-slew raw action. Reject
  nonfinite evidence rather than storing corrupt transitions. Fault detection:
  after an intervention, record bilateral grasp loss lasting >0.2 s before a
  verified release; or gripper closing below 20 degrees without bilateral grasp,
  followed by >1 s at tip distance >65 mm. Recovery requires a later new bilateral
  grasp and eventual full success. Merely reopening near the cube is not recovery.
- [ ] Run reward and existing task-contract tests; add exact boundary cases for
  fault dwell and no-trigger episodes. Confirm repeated successes cannot add rewards.
- [ ] Commit only Task 2 source/tests.

### Task 3: SAC learner, bounded storage, and restartable state

**Files:** Create `residual_sac.py`, `residual_server.py`,
`test_residual_sac.py`, `test_residual_server.py`.

**Interfaces:**

```python
SAC(obs_dim=109, act_dim=6, seed=0, device='cpu')
SAC.act(obs109, deterministic=False) -> np.ndarray
SAC.update(batch: dict[str, np.ndarray]) -> dict[str, float]
SAC.save(path, replay, counters, rng_states) -> None
SAC.load(path) -> dict # replay, counters, RNG states
Replay.add(obs, action, reward, next_obs, terminated, truncated, episode_id, step_id)
Replay.sample(batch_size, rng) -> dict
```

  Protocol: `('act', obs, deterministic)`, `('observe', transition)`,
  `('save', path)`, `('stats',)`, `('quit',)` → `('ok', payload)` or explicit error.
  Evaluation mode rejects observe/update and does not change normalization.

- [ ] Write tests for finite bounded samples, actual parameter updates, frozen
  target gradients, ring capacity, evaluation immutability, bad shapes/NaNs,
  and checkpoint reproduction of the next stochastic action/sample.

```python
def test_bootstrap_mask():
    terminated = torch.tensor([0., 1., 0.])
    reward = torch.tensor([1., 1., 1.])
    target_value = torch.tensor([2., 2., 2.])
    target = reward + .99 * (1. - terminated) * target_value
    torch.testing.assert_close(target, torch.tensor([2.98, 1., 2.98]))
    # Entries 0 and 2 cover continuing and truncated transitions, respectively.
```

- [ ] Run new learner/server tests; confirm failures before adding classes.
- [ ] Implement tanh Gaussian actor and twin critics (256/256 ReLU), stable
  squashing log-probability correction, frozen Polyak targets, Adam 3e-4,
  gamma .99, tau .005, target entropy -6. Clamp log std to [-5,2]. Initialize
  actor output mean to zero. Use sampled normalized raw residual actions in
  critics, not transformed offsets. Implement these updates:

```python
with torch.no_grad():
    next_a, next_logp = actor.sample(next_obs)
    value = torch.minimum(target_q1(next_obs, next_a), target_q2(next_obs, next_a)) - alpha * next_logp
    y = reward + .99 * (1. - terminated) * value
critic_loss = F.mse_loss(q1(obs, action), y) + F.mse_loss(q2(obs, action), y)
a, logp = actor.sample(obs)
actor_loss = (alpha.detach() * logp - torch.minimum(q1(obs, a), q2(obs, a))).mean()
alpha_loss = -(log_alpha * (logp.detach() - 6.)).mean()
```

  Use batch 256, capacity 50,000, no updates before 500 collected steps,
  and at most one update per later step. Warmup samples raw residuals uniformly
  in [-1,1]; environment still enforces slew. Save atomically via temporary
  file/rename at 1,000 steps and shutdown, including all network/optimizer states,
  alpha, ring contents/cursor, train count, episode counter, and RNGs. Reject
  nonfinite losses before stepping optimizers and stop the experiment.
- [ ] Run a CPU synthetic-transition smoke (not called robot learning), roundtrip
  saved state, and ensure localhost server owns no device-control imports.
- [ ] Commit only Task 3 source/tests.

### Task 4: Simulator collector, interventions, and process isolation

**Files:** Create `residual_session.py`, `residual_perturbation.py`,
`run_residual_bench.sh`, `test_residual_session.py`, `test_residual_perturbation.py`;
modify only opt-in paths in benchmark `isaac_bench_runner.py`.

**Interfaces:**

```python
ResidualSession(mode, rpc, limits_deg, seed)
ResidualSession.begin_episode(episode_id) -> None
ResidualSession.prepare(obs, q_deg, qd_deg_s, base_deg, queue_age) -> dict # target/offset/raw/actor_obs
ResidualSession.finish(sample, task, terminated, truncated) -> None
ResidualSession.flush_next(next_prepared: dict) -> None
ResidualSession.end_episode() -> None
Perturbation(seed, kind).decide(sample, phase, cube_xyz, spawn_bounds, dt) -> dict
```

  `finish` holds one pending transition until the next prepared observation is
  available. `flush_next` stores it without taking a second action. At termination,
  store a terminal observation using current sensors and the last base target;
  no next VLA request is needed because the target does not bootstrap. At a time
  limit, request the next base action once to construct a real next observation,
  then truncate/reset. Never use reset observations for a previous episode.

- [ ] Write fake-RPC/clock tests for one base act per executed step, one extra
  base act only for bootstrappable truncation, no reset-crossing transition,
  independent random streams, stale packet IDs, and 5,000-step stop after resume.
  Add perturbation tests for single application, valid tray bounds, no precontact
  teleport after contact, force clearing after .1 s, and not-triggered bookkeeping.

  In the fixture below, `sample_without_contact` is a finite TaskContract Sample
  with both finger forces zero and tip distance 0.05 m; `cube_xyz` is the midpoint
  of `spawn_bounds`, whose X/Y intervals each have width at least 0.02 m.

```python
def test_intervention_is_bounded_and_once():
    p = Perturbation(seed=17, kind='approach')
    event = p.decide(sample_without_contact, 'approach', cube_xyz, spawn_bounds, 1/15)
    assert np.linalg.norm(event['delta_xy']) <= .006
    assert p.decide(sample_without_contact, 'approach', cube_xyz, spawn_bounds, 1/15) == {}
```

- [ ] Run new tests, confirm failures, then implement the interfaces and fake
  end-to-end collector first. Episode selection cycles normal, approach, normal,
  transport (50/25/25%). Use SeedSequence children for scene, perturbation,
  exploration, and VLA; persist seed IDs. Transport force direction is sampled
  independently and held at ≤.02 N for .1 s, then explicitly cleared.
- [ ] Add flags `--residual-mode off|train|eval|zero`, `--residual-port`,
  `--residual-seed`, `--residual-kind normal|approach|transport|curriculum`,
  `--train-step-limit`, `--residual-checkpoint`. Default off executes the existing
  path. Insert hooks around mapping and physics steps, preserving `joint_vector`
  and Gripper_mimic sign. Primary joint limits come from the articulation and
  are recorded in degrees. Use post-step images for post-step visibility labels.
- [ ] Implement launcher with exclusive output-directory creation; unique
  policy/learner/runner logs; selected unused localhost ports; health polling;
  owned PIDs only for cleanup. Do not copy existing broad pkill patterns. Use
  CPU for the small learner initially; leave base VLA GPU placement unchanged.
  A broken RPC fails the episode and saves diagnostics, never silently disables
  the residual to claim a learned success.
- [ ] Run fake integration suite, then real Isaac scene/contact check, then
  30-step zero-mode smoke. Compare first mapped targets against original runner
  with the same seeds. Hash-check base model, calibration, scene and source USD
  before/after. Stop on drift; do not weaken tests or alter production.
- [ ] Commit only collector, launcher, opt-in runner edits, and their tests.

### Task 5: Paired reporting and the bounded pilot

**Files:** Create `summarize_residual.py`, `test_summarize_residual.py`;
create outputs only under a fresh `residual_pilot_v1/` run directory in B.

**Interfaces:** `summarize(episode_rows: list[dict]) -> dict` and
`paired_report(baseline_rows, residual_rows) -> dict`. Require identical evaluation
seed/kind keys, unique IDs, completed episode records, and separate training rows.

- [ ] Write tests rejecting missing/duplicate pairs and excluding training rows,
  zero-fault recovery returning null, unsuccessful recovered grasp not counting
  as recovered task, and correct success counts/Wilson intervals.

```python
def test_no_fault_is_not_perfect_recovery():
    result = summarize([{'success_task': True, 'fault': False, 'recovered': False,
                         'triggered': True, 'kind': 'transport', 'split': 'eval'}])
    assert result['recovery_rate'] is None
    assert result['fault_count'] == 0
```

- [ ] Run tests red, implement counts and Wilson 95% intervals (z=1.959964), then
  run green. Capture timing separately for VLA inference, collection, and SAC
  update; do not call cached action dequeue time fresh inference latency.
- [ ] Write the exact manifest before running: training seeds start 20000;
  ordinary eval seeds 30000–30004; disturbed eval seeds 31000–31004 with kinds
  approach, transport, approach, transport, approach. Both policies share these
  cases, scene seeds, and trigger rules. Evaluation residual uses deterministic
  actor means from the final finite 5,000-step checkpoint; no best-seed selection.
- [ ] Run training up to exactly 5,000 environment steps, saving at 1,000-step
  boundaries. Report progress and loss health without claiming success from loss.
  Interrupt on nonfinite updates, isolation violations, or resource exhaustion;
  retain artifacts and explain the interruption instead of automatically adding
  more training or changing the policy.
- [ ] Evaluate original and residual on all ten held-out cases each, maximum
  900 steps per case. Record all outcomes, including non-triggered disturbances.
  No scene teleport except explicitly logged approach perturbations/reset.
- [ ] Encode paired top/wrist frames at 15 fps for each eval episode with ffmpeg.
  Save a final post-action frame, do not end videos at the pre-action success
  observation, and label policy/seed/outcome. Save all videos, not just successes.
- [ ] Produce a short report with normal/full-task/centered-placement counts,
  disturbed success, faults/recoveries, uncertainty, failure stages, final errors,
  command saturation, wall time and memory. Include limitations: red solid-cube
  features, imperfect wrist registration, small sample size, ±5-degree bound,
  and no real-robot evaluation. Link successes and failures.
- [ ] Run all new pure tests and existing benchmark task/scene regressions again.
  Obtain independent final code review before claiming completion. Report the
  known project-wide pytest collection collision separately; do not claim the
  whole repository is green. Commit only tested code and report source, not bulky
  evaluation artifacts. Do not push or deploy without a separate request.

## Plan self-review and handoff

Coverage: Task 1 owns observable-only inputs and action limits; Task 2 owns
annotations/reward/recovery; Task 3 owns SAC and persistence; Task 4 owns isolation,
timing and collection; Task 5 owns the fixed budget, held-out evidence and videos.
Each of the five review-focus conditions has an owning test task. No simulator
or hardware operation is part of writing this document.

Recommended execution: **Native** in this session, with final independent review.
The simulator/collector/learner interfaces are closely coupled, so a single
implementer reduces coordination overhead. User review and execution selection
are still required before implementation.
