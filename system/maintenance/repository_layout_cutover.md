# Repository-layout cutover runbook

This is a maintenance plan, not authorization to operate an installation.
Software validation on the isolated branch neither starts production nor proves
hardware, external providers or deployed native installations ready. Source and
private-state cutovers each require an explicitly agreed stopped maintenance point.

## Implementation status — 2026-10-03

Tasks1–10 source/layout work and scoped reviews are accepted. Task11 software
validation and Task12's reviewed synthetic private-copy tooling are integrated;
final combined accounting/publication review is still required. The operating
checkout, deployed services and real private stores have not been cut over.

Actual migration failures found in source/fixture roots were corrected and
independently reviewed. The evidence retains unrelated baseline test failures,
skips and warning debt; it is not a full-suite-green claim. Default Runtime IDE
geometry still fails three old audit assertions with unchanged UI bytes.
Contained Firefox evidence separately covers actual routes, ten owner reports,
Replay and Knowledge; unauthenticated401 and GPU-less WebGL limitations remain.
The49 offline owner scenarios/84 accepted captures are injected-response
evidence, not actual-provider, hardware or full cross-owner sequence evidence.
External-provider validation awaits explicit credential/provider authorization;
two original Playwright tests, unreleased long controller cases and native
Windows/device operation remain unassessed. Temporary ROS rebuild evidence is
not an installed production prefix.

The previously recorded outgoing publication gate has32 textual findings
(31 personal-path and1 credential-pattern finding). Their policy/identity
decision remains pending; neither source review nor software tests authorize
publishing them. Retain the final outgoing scan's exact result and revision.

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

The reviewed helper `runtime/scripts/maintenance/migrate_private_state.py`
offers `plan`, `copy`, `verify` and `propose-bindings`, all with explicit inputs
and exclusive private0600 output manifests. It never activates bindings,
restarts/resumes, discovers stores, operates devices or rewrites checkpoints.
Inputs must contain all seven canonical absolute normalized
`atr.path_bindings.v1` store roots; this is deliberately stricter than the
unchanged runtime loader. Keep manifests/proposals outside all selected stores
and public Git. Destination roots may be absent or empty, but their parents
must already exist; prepare parents only during approved maintenance.

Before copy the operator explicitly asserts every writer is quiescent. Changed
snapshots, populated destinations, symlinks, unsupported entries or permission/
integrity/durability failures block verification. Copy preserves bytes and mode
bits, not ownership, ACLs or xattrs; resolve any additional filesystem needs
before use. No native Windows copy support is claimed. Partial outputs remain
recoverable and must not be retried by merging/overwriting; originals and newer
destination records are never deleted. Only tool-owned temporary link names
are removed. This is not transactional rollback or automatic cleanup.

Typed historical reference requests identify exact schema/field/run/kind/source
and, where required, exact source run directory. Targets derive only from
verified copied entries; empty requests do not prove historical completeness.
Supply a reviewed map explicitly to read-only readers, never as resume authority.
`ready_for_activation` and `resume_certified` remain false after verification.

Explicit printer `connection_memory_path` selections remain repository-relative
authorities even if named memory moves; omitted fields use named-root defaults,
and absolute overrides remain external. Record retain/change decisions without
dropping default-looking values or changing Prusa defaults. The two deferred
manual PDFs retain separate frozen-move, private inbox and registry-reference
accounting. Copying an inbox alone does not complete registry/root cleanup;
retain original references until a separately approved transition. Do not read,
publish or relabel their bytes merely to finish development accounting.

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
