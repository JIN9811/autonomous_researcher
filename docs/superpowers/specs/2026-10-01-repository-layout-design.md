<!-- atr-doc
doc_type: design
subtype: architecture
status: review
authority: proposal
decision_status: proposed
audience: [developer, maintainer, operator]
scope: [repository_layout, path_resolution, documentation_separation, runtime_compatibility]
summary: Proposed staged repository relocation with unchanged module identities, isolated verification, and separately controlled private-state migration.
related_docs:
  - docs/modularity.md
  - docs/runtime/runtime_ide.md
  - docs/runtime/loop_artifact_archiving.md
  - docs/knowledge/runtime_reference_safety.md
  - docs/knowledge/publication.md
  - docs/standards/documentation_standard.md
supersedes: []
-->

# Repository Layout and Compatibility Design

## Summary

The user approved the four-directory concept on 2026-10-01 and requested that
obsolete design documents be reviewed and discarded. This document specifies
the proposed migration; it does not claim that files have moved or that a new
server has been deployed. The written design still requires review before an
implementation plan is prepared.

The rollback baseline is `c3c0c6e4ffedb83e62b86503632119635ae53616`, already pushed
to `main` before this work. The preceding dependency audit inventoried 2,312
tracked entries and parsed all 897 `.py` files without application imports.
Those checks are static coverage, not complete functional verification.

## Scope and non-goals

Organize the checkout, separate operator documentation from system material,
make path ownership explicit, and preserve existing module/package/Runtime IDE
contracts. Validate each migration boundary in a disposable, hardware-isolated
copy before integrating source changes.

Do not change experiment ordering, model selection, device commands, completion
criteria, thresholds, timeouts, recovery authority, prompts, or active run state.
Do not merge the unrelated report-agent worktree, move external installations,
or start a physical experiment. Structural changes are not live-hot-reload work.

Source integration and private-state cutover are separate operations. Neither
allows restarting the operating server or altering an active run without a
separately agreed maintenance point.

## Target layout

```text
README.md
runtime/             executable peer packages and their owned resources
  app/ agents/ graphs/ packages/ device_bridges/ ...
  configs/ web/ sim/ ros/ models/
  tests/ scripts/ install/ deploy/ tools/
  Pyautogui_server_for_window/
  pyproject.toml uv.lock requirements*.txt
system/              technical references and curated system inputs
  agents/ runtime/ device_bridges/ hardware/ knowledge/ project/
  standards/ templates/ maintenance/ repository/ process/
  plans/ specs/ references/ assets/ retained-history/
docs/                human-facing navigation and procedures
  tutorials/ gui/ paper/ assets/ project/
  README.md README.ko.md
workspace/           private generated state; final migration phase only
  memory/ runs/ artifacts/ outputs/ user_files/ logs/
  source-inbox/ local-history/ migration/
```

Necessary hidden repository tooling stays at the outer root: `.git`, `.github`,
`.gitignore`, `.gitattributes`, environment files and local worktrees/environments.
The only non-hidden top-level file is `README.md`. Private environment values
are neither copied into fixtures nor committed. No permanent forest of old-root
symlinks is introduced to make the visible layout appear clean.

### Placement rules

| Existing material | Destination rule |
|---|---|
| Executable peer packages, configs, registries, owned frontend assets | `runtime/<existing path>`; preserve internal package names and topology |
| Tests, scripts, install/deploy files, dependency metadata | `runtime/<existing path>`; update outer-root launch commands and CI together |
| Independently deployed Windows bridge and ROS source package | Keep each subtree internally intact under `runtime/`; its own README, manifests and install instructions remain adjacent |
| `docs/agents`, `docs/runtime`, `docs/device_bridges`, `docs/hardware` | `system/<domain>`; classify mixed operator procedures explicitly in the per-file manifest |
| Runtime guide, curated Wiki, manual registry | `system/project`, `system/knowledge` and owner domains; preserve effective runtime text |
| `docs/standards`, `templates`, `maintenance`, `repository`, `process`, `modularity.md` | Corresponding `system/` locations |
| Active `docs/superpowers/plans` and `specs` | `system/plans` and `system/specs`; superseded documents follow the disposal rule below |
| User tutorials, GUI tours, research narrative and their assets | Remain under `docs/`; technical GUI internals move to `system/runtime/gui/` by an explicit file mapping |
| Root `README.ko.md`, `REQUIREMENTS.md`, `CHANGELOG.md`, `CONTRIBUTING.md` | `docs/README.ko.md` and `docs/project/`; root README links to them |
| Root `SECURITY.md`, `LICENSE`, `CITATION.cff` | `.github/SECURITY.md`, `runtime/LICENSE`, `docs/paper/CITATION.cff`; preserve bytes and link from root README |
| Root `references/`, presentation `image/` | `system/references/`, `system/assets/presentation/`; preserve complete example/asset bundles and provenance |
| Tracked `memory/*.py` compatibility package | `runtime/memory/`; never confuse importable source with private data |
| Ignored private stores, runs, outputs and local residue | Stay authoritative at existing locations until the final offline migration; then named `workspace/` stores |
| External LeRobot/Isaac/ROS installations, datasets, weights and caches outside this checkout | Do not move; retain explicit external configuration |

The citation file will no longer occupy its former repository-root location.
Do not claim GitHub's automatic citation UI remains available: the supported
entry is the root README link and the preserved citation file. License and
security content remain accessible; distribution metadata includes the license.

Every tracked entry must have one explicit disposition in a migration manifest:
move, keep, approved deletion, or regenerated build output. There must be no
unclassified remainder, duplicate authoritative copies, or blanket text rewrite.
The manifest also records old/new relative paths, Git blob identity, file mode,
content hashes and the reason for intentional byte changes. Private manifests
must not enter the public source manifest.

## Root and reference contracts

Path resolution must be deterministic, side-effect-free, and finalized before
application import. Directory existence is not an authority-selection rule.

| Root/reference class | Resolution and invariant |
|---|---|
| `repository_root` | Outer checkout containing the four domains; documentation metadata and Git operations use this base |
| `runtime_root` | Executable peer tree; Python imports remain `app`, `agents`, `graphs`, `memory`, etc., never `runtime.app` |
| `system_root` | Curated system material only, not a writable learned-memory store |
| `workspace_root` | Final private-data boundary; merely computing it must not activate/create an empty replacement for existing state |
| Named data roots | Explicit run, memory, artifact, output, source-inbox and user-file locations; transitional bindings point to existing stores |
| Logical module reference | Preserve serialized `graphs/modules/<id>/module.yaml`, resolve against `runtime_root` |
| IDE implementation/configuration reference | Resolve against an explicit runtime source base; keep logical module/handler identities |
| Human/system document reference | Repository-relative metadata; Markdown links relative to the containing document |
| Registry source reference | Preserve the manual registry's own relative-path base |
| Historical artifact/evidence reference | Schema-specific read-time compatibility resolver, not the fresh-configuration resolver |
| Public asset/API URL | Unchanged route contract, mapped to the appropriate physical owner root |

Do not replace every `project_root()` with one new root mechanically. Existing
callers use it for code, data, provenance, package discovery and access control.
In particular, `ManualKnowledgeService.runtime_root` currently means writable
manual data; preserve that meaning through an adapter or explicitly rename the
parameter to `manual_data_root`.

Launches from the outer checkout and from `runtime/` must select the same source,
configuration and named state roots. Worker processes must also resolve the new
tree under their real filtered environments, including workers that omit
`PYTHONPATH`. Tests must detect accidental imports from the production checkout.

## Module, package and Runtime IDE invariants

Preserve Python namespace identities; agent and bridge discovery; core versus
specialist roles; schema strings; package IDs/versions; module IDs; handler IDs;
owner operation catalogs; frontend namespaces/factories; and public asset URLs.
`runtime/` is a filesystem container, not a new Python package namespace.

Preserve the four graph identities, ten module declarations and seven specialist
package manifests at the audited baseline. Compare topology, dispatch, handlers,
transitions, bridge requirements and owner-plan contracts separately from
path-bearing presentation metadata. If metadata changes a full graph hash,
record that difference; do not label it byte-identical.

Installed catalogs, detached drafts, active configuration, version snapshots and
pinned run bindings remain distinct. Existing runs retain their frozen execution
semantics. Generated adapters remain beneath the canonical modules root and
retain validation, approval and restricted-import requirements. A relocated
reference grants no authority to execute a draft.

Do not split editable `graphs/modules/` into a new overlay architecture in this
cleanup. Preserve the existing editing/version lifecycle at its new explicit
physical root. Test create, validate, save, version, rollback, import/export and
source-link operations using disposable modules and state only.

## System inputs and operator documentation

Runtime ingestion is an explicit allowlist, not a scan of all `system/` or
`docs/`. Preserve the bytes of the project guide, directly loaded specimen
guideline and reviewed owner execution excerpts. Relocating a stale guide is
not permission to revise its decision content.

Separate Wiki corpus location from reviewed source-reference resolution. Keep
all topic/citation identities and review states. Relocate both `source_refs` and
matching `source_revision` keys consistently. Keep hashes when source bytes are
unchanged; a changed source remains stale until separately reviewed. Do not
refresh `verified_at` merely because a path moved. Cursor/revision changes from
relocated metadata are expected and must not be described as changed knowledge.

Manual registry sources remain registry-relative. Raw uploaded sources move to
the private source inbox only during the state phase; derived extracts, receipts,
publications and learned indexes remain private. Preserve content-addressed IDs.
RAG guide chunks/text retain their identity; changed location metadata is recorded
as a relocation, not a new empirical source or changed instruction.

Graphify needs an executable import base and separately allowlisted technical
corpora. It must not crawl the whole outer checkout, import private namespaces,
or silently build a disconnected replacement graph because file IDs changed.
Reconcile path-derived identities explicitly without widening publication scope.

Move assets with their owning documents. Check Markdown files, headings, images,
source metadata, screenshot manifests, paper artifact manifests and generated
diagram references against the per-file mapping. A live link does not make an
obsolete proposal an implementation authority.

### Obsolete design disposal

The user's 2026-10-01 disposal request supersedes the previous blanket preference
to retain old design text in the working-tree archive. Delete only reviewed,
superseded design/specification/implementation-plan text with no required active
consumer. Redirect surviving navigation to current references or standards.

Preserve scientific evidence, original run data, current contracts, runtime
inputs, vendor manuals, and pending designs belonging to separate worktrees.
Historical plans containing unique verification evidence require an explicit
preservation decision; an old timestamp alone is insufficient. Associated binary
assets and complete reference bundles are not deleted merely because a prose
file was retired. Preserve their self-contained manifests or explicitly approve
the whole retired bundle as a separate disposition.

Record deleted paths, reasons, replacements and the last recoverable commit in
a short disposal ledger. Do not rewrite a dated audit to pretend its former
inventory never existed. Git history provides recovery; no history rewrite or
private trash directory is published.

## Historical state compatibility

Source relocation must initially continue using existing private locations. If
both old and new stores are populated without an explicit selected binding,
report ambiguity and do not choose the newest/nonempty one automatically.

Before final state migration, quiesce every writer and inventory actual local
paths without publishing secrets. Copy into an isolated migration destination,
compare bytes/hashes/permissions and only then switch explicit bindings. Keep a
recoverable original until acceptance; do not recursively delete it to clean up
the visible root. An approved private backup can live outside the checkout.

Use a versioned, reviewed old-root to new-root mapping outside immutable records.
Mapping applies only to known persisted-reference fields and matches complete
path components. Reject traversal, escaping symlinks, unsupported references and
ambiguous matches. Never search arbitrary directories by filename or treat a
mapping as expanded filesystem authorization.

Recovery verifies the original checkpoint envelope first, resolves only its
physical evidence locations, then verifies the unchanged evidence hashes, backup
hash, run identity and original resume/safety conditions. Do not re-sign or
rewrite historical checkpoints to make them pass. Replay aliases resolve only
to authorized archived copies; a historical source alias is not permission to
open an arbitrary external file. Successful read-only playback is not proof
that a run is safe to resume.

Keep source-inbox-relative, extraction-relative, run-relative, legacy
repository-relative and absolute-reference semantics distinct. Preserve original
source/publication/artifact IDs and immutable provenance. Do not apply historical
mapping to newly configured device endpoints, model checkpoints, datasets,
calibration files, credentials or external installations.

## Packaging, deployment and publication

Keep `pyproject.toml`, `uv.lock`, dependency files and the executable peer tree
together under `runtime/`. Root installation instructions become explicitly
runtime-project based. Use an in-project package README or inline package
description; do not rely on a build reading `../README.md`. Verify wheel/sdist
contents exclude private state, credentials and namespace-discovered runtime data.

Use a clean validation environment without the production editable-install
finder. Regenerate installed launchers at source cutover; their captured absolute
paths are not fixed by moving source. Keep the outer hidden environment location
explicit in installation/launch code rather than inferring it from script depth.

Windows release manifests, updater allowlists and portable data paths remain
package-relative. Do not update deployed Windows tasks as part of Linux source
staging. Preserve ROS source package/resource/entrypoint contracts; classify
generated `ros/install` and `ros/log` entries separately and rebuild required
outputs at the destination instead of patching generated absolute prefixes.
Validate USD asset dependencies without starting a simulator or model workload.

Update nested private-path guards, ignore patterns, corpus scopes, CI commands
and path-bound publication approvals before relocation commits. Explicitly test
that new `workspace/` and relocated raw-source paths cannot be force-published.
The tracked large voice model needs a narrow exact-source/destination/hash
relocation rule or separately reviewed asset delivery; do not increase the
global publication-size threshold or exempt a whole directory.

## Isolated verification server

OS isolation must exist before any `app.main` import. That module bootstraps
state at import, and lifecycle handlers can reach PLC or signal host video/robot
processes. A different port, test label, mocked LLM or disabled lifespan alone
does not provide isolation.

Use a tracked-only copy, clean environment, mock-only backends/transports,
synthetic state, private home/cache/temp and isolated PID/network/mount/device
namespaces. Mount no production secrets, writable state, GPU/camera/serial nodes,
desktop sockets or container-control sockets. Keep capabilities dropped, a
single worker and reload disabled. Browser/client requests run inside the same
isolated network namespace; do not share the host network for convenience.

The host's namespace preflight succeeded by executing only `/usr/bin/true`.
No application sandbox/server validation is yet claimed. Verify actual import
origins and forbidden-effect counters before exercising real routes. Assert no
outside-root writes, hardware calls, outbound connections or host-process
signals during import, startup, requests and teardown.

First validate owner assets and fixture rendering. Then test actual API,
controller, worker and Runtime IDE paths under fixture injection. A fixture-only
UI pass cannot substitute for real-route equivalence. Lifecycle tests use fake
services inside the same OS boundary. Stop only the test-owned process group.

## Migration boundaries and acceptance

This is an ordering constraint, not the implementation task plan:

1. Preserve a baseline and classify every file, consumer and runtime input.
2. Establish isolated verification and explicit roots while keeping current
   physical locations authoritative.
3. Relocate operator/system material with link, privacy and knowledge checks.
4. Relocate the executable peer tree with packaging, worker and contract checks.
5. Integrate verified source at an agreed quiescent maintenance point.
6. Migrate private state last, at a separately agreed offline point, retaining
   originals and validating historical compatibility before binding new stores.

Every boundary must pass its own checks before the next starts. Required evidence:

- Complete file/mode/hash accounting and no unexplained deletion or binary change.
- Identical effective execution-guide text and owner reference projections.
- Module/package/graph semantic comparisons, pinned snapshots and adapter trust.
- API/static/module-asset URLs; Runtime IDE lifecycle; Live/Replay/card artifacts.
- Fresh installation/distribution inspection and actual worker import origins.
- Explicit-root behavior from both launch directories and ambiguous-store tests.
- Preserved historical artifact/checkpoint/source-library identities and hashes.
- Unweakened privacy/containment tests, including adversarial path/symlink cases.
- Existing guarded loop tests, from initial design through analysis/BO/Guardian,
  with no physical effects and no synthetic result presented as physical evidence.
- Documentation links/anchors/images, metadata/source hashes and publication checks.

Do not make failing tests pass by deleting contract assertions or changing loop
behavior. A baseline failure must be identified separately; a path assertion
changes only when its physical path contract deliberately changed.

## Cutover, rollback and limits

Source and private-state cutovers each require a known stopped/quiescent state,
verified launcher/environment targets, preserved snapshots and operator agreement.
No host restart, live structural reload, automatic resume, one-cycle stop rule or
new production gate is introduced by this design.

Before new writes, rollback can restore the previous source/environment bindings.
After new writes, retain the new records and require compatible readers or an
explicit reconciliation process; never overwrite a newer store with an older
backup. Preserve the unaffected report-agent worktree and external installations.

Static inventory does not establish device safety, live run equivalence, external
script compatibility or a valid distribution. Those remain acceptance checks,
not claims made by this design. The detailed implementation plan follows written
design approval and will name the actual test entrypoints and bounded work units.

## Related documents

- [Modularity](../../modularity.md)
- [Runtime IDE](../../runtime/runtime_ide.md)
- [Artifact preservation](../../runtime/loop_artifact_archiving.md)
- [Runtime reference boundary](../../knowledge/runtime_reference_safety.md)
- [Publication rules](../../knowledge/publication.md)
- [Documentation standard](../../standards/documentation_standard.md)
