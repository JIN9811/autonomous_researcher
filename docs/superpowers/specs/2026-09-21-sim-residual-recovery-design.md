# Isolated residual RL pilot for placement and recovery

Status: written specification for user review; not an implementation or training result.

## Purpose and scope

Improve the existing simulated SmolVLA manipulation policy with a small residual
controller, including recovery from modest approach/grasp disturbances. Preserve
the original policy, calibration, registered cameras, scene, and production loop.
The user-approved pilot budget is 5,000 training environment steps. It is a
feasibility experiment, not a promise of convergence or real-robot improvement.

The selected approach is a frozen base policy plus SAC residual joint commands.
Direct VLA fine-tuning is outside this pilot because it changes a much larger
model. A scripted retry controller is not substituted for learned recovery.
Large task-level mistakes may remain unrecoverable with the selected small bound.

## Fixed baseline

- Base: `outputs/train/20260903_3_train(smolvla)/checkpoints/080000/pretrained_model`.
- Scene: `runs/sim_policy_bench_20260921/registered_scene_v4_r2/omx_recorded_rgbd_benchmark.usda`.
- Calibration: the sealed benchmark `baseline_v1/calibration.json`.
- Base action queue remains 50 steps; execution remains 15 Hz with existing
  physics decimation. Do not silently improve the baseline by changing chunking.
- Full-cycle evaluator: benchmark `task_contract.py` and `task_runtime.py`.
- No production endpoint, hardware bridge, server restart, real robot command,
  scene-source edit, or base checkpoint overwrite is permitted by this scope.

All executable additions and results belong under the existing ignored benchmark
directory. This specification is the only tracked addition at this stage.

## Success and annotations

Use measured events, not commanded waypoints:

Home → visible specimen → approach → bilateral grasp → lifted transport →
centered release → stable supported placement → home return.

Retain the existing evaluator thresholds: radial center error at most 5 mm,
continuous supported/stable placement for 1 s, and all six primary joints within
5 degrees of recorded home at low speed for 0.5 s. Contact, clearance, orientation,
and velocity checks remain as implemented. Final home may close the gripper only
after a verified release and settling. Regrasp invalidates old release evidence.

Simulator poses and filtered contact forces may supply labels, rewards, and
evaluation. They must not enter actor observations. Existing broad target-volume
success is diagnostic only; it is not completed placement or full-task success.

## Inputs and action boundary

The pilot actor uses observable, inexpensive features instead of modifying the
VLA encoder. Per observation:

- Six measured primary joint positions and velocities, normalized by declared
  joint ranges and velocity scales.
- Six mapped base joint targets and six base-target minus measured-position errors.
- For each of the existing top and wrist RGB/depth-visual cameras: a validity bit,
  normalized red-component centroid X/Y, normalized area, and median depth-visual
  intensity inside that component. Missing detections produce zero values and a
  false validity bit. Depth-visual intensity is not claimed to be metric depth.
- Three consecutive observation feature frames, previous six residual offsets,
  and normalized base-action queue age. History is reset between episodes.

The red-component extractor builds on the current bench visibility proxy. This
deliberately limits the pilot to the red solid cube; it is not a general gyroid
detector or a validated real-robot perception system. No image-derived feature
may be replaced by simulator truth when detection fails.

The actor emits six normalized offsets. Convert to physical joint degrees after
the existing calibration mapping, with each offset bounded to ±5 degrees.
Residual slew is bounded to 1 degree per control step; reset begins at zero.
Apply joint limits consistently, with a logged saturation mask. Invalid base
commands or nonfinite observations stop the benchmark episode rather than moving
the robot using guessed values. Zero-residual mode must reproduce original mapped
commands on valid baseline inputs. Mimic joints use the existing mapping, not
independently learned commands. No scripted stage-dependent action override.

## Components and transition contract

Keep the existing baseline runner usable without importing a learner. Add small
bench-only units for observable features, residual action mapping, reward,
SAC/replay storage, and collection/evaluation orchestration.

The frozen policy server continues producing ordinary actions. Any optional
queue-age metadata must not alter action selection or existing protocol clients.
The residual learner runs in a separate benchmark process; simulator and base
policy use their current environments. Every collected transition contains the
actor observation, sampled offset, actually applied offset, next observation,
reward components, termination/truncation flags, episode/step IDs, and annotation.
The learner consumes the sampled action; the slew/limit transform is part of the
environment and its previous-offset state is observable. Record applied actions
as evidence instead of falsely treating them as independent policy samples.

## Learning and reward

Initial SAC settings: two 256-unit hidden layers for actor and twin critics,
discount 0.99, target smoothing 0.005, learning rate 0.0003, batch 256, automatic
entropy tuning, and a 50,000-transition bounded replay buffer. Freeze all VLA
weights; train only the residual actor/critics/temperature. Start with 500
collection steps before updates and at most one update per collected step.
Initial exploration obeys the same offset and slew limits as the trained policy.

Reward separates final success, progress, and regularization:

- Full measured task completion: +20, once.
- First bilateral grasp, lifted transport, verified centered release, stable
  placement, and final home milestones: +1 each, once per episode. Retrying cannot
  farm a milestone bonus.
- Dense distance guidance uses bounded potential shaping
  `0.99 * Phi(next) - Phi(current)`, with one documented potential covering
  approach, platen centering, and home return. Terminal potential is zero;
  time-limit truncations retain their observed next-state potential.
- Offset magnitude penalty: `-0.01 * mean(normalized_offset ** 2)` per step;
  offset-change penalty: `-0.01 * mean(normalized_offset_delta ** 2)`.
- Specimen irretrievably outside the workspace or simulator-invalid state: fail
  the episode. Exclude corrupt numerical transitions from learning and record
  the reason. A missed grasp inside the workspace is not an automatic terminal.

The implementation plan must define the potential formula and tests before
reward code is written. Do not reward being above the platen as if released.
Time-limit endings are truncations and bootstrap; genuine terminal endings do not.
Each episode allows up to 900 policy steps (60 simulated seconds), identically
for baseline and residual evaluation.

## Recovery curriculum and fair evaluation

Train half the episodes on ordinary safe tray spawn positions. Split the rest
between small approach disturbances and bounded transport disturbances:

- Approach: once, before finger contact, shift the cube laterally by up to 6 mm
  within the valid tray footprint. This is explicitly a simulator intervention,
  not an action or a claimed physical disturbance model.
- Transport: once after measured lift, apply at most 0.02 N lateral force for
  0.1 simulated seconds. Do not forcibly detach, disable collisions, or edit
  contact evidence. Log whether a slip/contact loss actually resulted.

Use independent deterministic random streams for scene, intervention, base
policy, and residual exploration. Evaluation never updates weights or statistics.
Use paired seeds and identical trigger rules for original and residual policies.
If a trigger is never reached, record it as not triggered, not recovered.

Initial evaluation is deliberately small: five held-out ordinary trials and five
held-out disturbance trials per policy, separate from training seeds. Report:

- Full-cycle success count/rate and stable centered-placement count/rate.
- Disturbance trigger count, verified fault count, and recovery count divided by
  verified faults. Zero faults means recovery rate is unavailable, not 100%.
- Fault definition: an observed post-trigger bilateral-contact loss during
  transport, or a missed grasp followed by the evaluator's retry path.
- Recovery requires a new valid grasp and eventual full-task completion after
  that fault. Also report the disturbed full-task rate over all five trials.
- Final radial error, time to success, failure phase, saturation frequency,
  and collection/update latency separately.

Five trials do not establish reliable population success rates. Show counts and
uncertainty and do not cherry-pick successful seeds. A force that causes no faults
cannot establish recovery ability; report the pilot as inconclusive on recovery.
Do not enlarge perturbations or training budget silently to obtain a result.

## Artifacts, isolation, and failure handling

Use fresh output directories. Save manifests with base/scene/calibration/code
hashes, config, versions and seeds; append-only episode/transition summaries;
residual/critic/optimizer/temperature checkpoints; replay buffer and RNG state;
and separate normal/disturbed evaluation summaries. Capture paired top/wrist
videos for every evaluation trial, success and failure, labeled with policy,
seed, disturbance, and final measured outcome.

Persist learner state at 1,000-step boundaries and clean shutdown. A resumed
training process starts a new simulator episode unless full simulator state can
be restored; never splice transitions across a reset or claim bitwise simulator
continuation. Track collected steps so restart does not silently exceed 5,000.
On nonfinite losses, retain the last finite checkpoint and stop with diagnostics;
do not deploy or keep training a diverged controller.

## Verification and acceptance

Before training, test feature invalidity/occlusion, calibration units, zero-offset
equivalence, bounds/slew/mimic joints, history reset, terminal versus truncated
targets, finite SAC updates, checkpoint round trips, and one-shot rewards. Run
the existing task/contact and scene-isolation regressions without weakening
their thresholds. Use a short Isaac smoke to verify the entire transition path.

Acceptance for the pilot is an auditable completed comparison, not a guaranteed
improvement. Claim an improvement only if actual held-out results support it;
claim recovery only when faults were observed and corrected. No deployment to
the real robot follows automatically. Camera-registration error and the solid
proxy specimen remain sim-to-real limitations.

## Review checkpoint

Concept approved in conversation. Written specification awaits user review.
After approval, write the implementation plan and select its execution method
before implementing or running the residual learner.
