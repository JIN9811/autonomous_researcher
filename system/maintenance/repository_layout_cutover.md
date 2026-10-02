# Repository-layout cutover runbook

This is a maintenance plan, not authorization to operate an installation.
Software validation on the isolated branch neither starts production nor proves
hardware, external providers or deployed native installations ready. Source and
private-state cutovers each require an explicitly agreed stopped maintenance point.

## Before scheduling maintenance

1. Obtain whole-branch review, including the later private-copy tooling and its
   synthetic rehearsal. Pin the reviewed commit/tree and keep the existing
   operating checkout unchanged until approval. Retain raw validation receipts,
   baseline failures, warning debt and unassessed gates; do not describe the
   branch as a universally passing test suite.
2. Record the intended repository, runtime and system roots and every private
   store binding. `runtime/` is a filesystem container, not a Python namespace.
   Logical graph/module IDs, asset URLs, guide labels and archived identities
   remain unchanged. Do not infer authority from directory existence.
3. Confirm recovery copies and hashes for active state, owner history, archive
   evidence, immutable checkpoints, bindings and launch configuration. Protect
   credentials separately; never include them in source, validation exports or
   reports. External installations, model caches, datasets and calibrations are
   not part of this source move.

## Approved source-maintenance window

1. The operator quiesces **every writer**: backend/reloader/workers, scheduled
   ingestion, recorders, bridges and any separate process writing selected
   stores. Preserve current run/stop/recovery state. Verify quiescence with the
   installation's established procedure; this plan adds no automatic stop rule,
   new recovery authority or automatic resume.
2. Integrate the reviewed source only. Keep Git, `.env` and the main `.venv` at
   the outer root; executable source/configuration/assets reside in `runtime/`,
   internal maintained material in `system/`, public material in `docs/`.
   Do not create an old-root symlink forest or activate empty replacement stores.
3. Regenerate the installed `atr` launcher using the reviewed
   `runtime/install/install_cli.sh` at the new location. Reconcile explicit
   `ATR_LAYOUT_CONFIG` and `ATR_PATH_BINDINGS` with the finalized RuntimePaths.
   Retain existing private bindings unless their separate migration is approved.
   A conflicting or ambiguous binding is a stop condition, not a fallback.
4. Rebuild the owned ROS package in the **intended deployed runtime prefix**
   using the approved platform procedure before declaring its snapshot launcher
   ready. Task10's isolated temporary build proves source compatibility only;
   it does not populate operating `runtime/ros/install`. Never silently source
   stale outer `ros/install`. Confirm the new setup/install paths and relocated
   resource paths without running a simulator, node or device as an implicit step.
5. Validate environment/import origins and readiness from both supported entry
   points: outer-root generated launcher and direct Python module execution from
   `runtime/` with the activated outer `.venv`. Run only approved non-actuating
   checks; document remaining platform/device/provider prerequisites separately.
   No production restart, live structural reload or experiment resume follows
   automatically from a passing readiness check.

## Separately approved private-state window

Use the reviewed private-copy/verification tooling with explicit selected roots
only after its own stopped-maintenance approval. Copy without deleting originals,
verify bytes/modes/identities and immutable checkpoint envelopes, then explicitly
select the verified destination. Keep original evidence intact and recoverable.
Do not move external caches/datasets/calibrations or merge unrelated worktrees.
The synthetic rehearsal is not evidence that real private stores were migrated.

## Rollback and operator handoff

If source, environment, native prefix or binding verification fails, keep all
writers stopped and preserve the failure receipt. Restore the recorded source
and launch/binding selection through the approved recovery procedure; do not
rewrite archived evidence or automatically replay a hardware run. A saved module
version may be read, drafted and validated without activation; rollback to it
requires an explicit save/activation decision. Source rollback and private-store
selection are separate operations.

The operator explicitly decides whether and when to restart and resume after
all required gates. Record the approved revision, selected roots, readiness
results, remaining limitations and recovery location. Actual-provider validation,
long unreleased controller cases, native Windows execution and physical-device
commissioning must not be inferred from controlled offline or Firefox fixtures.
