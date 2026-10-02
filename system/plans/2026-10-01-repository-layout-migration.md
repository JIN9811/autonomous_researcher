<!-- atr-doc
doc_type: plan
subtype: migration
status: review
authority: proposal
execution_status: planned
governing_design: system/specs/2026-10-01-repository-layout-design.md
audience: [developer, maintainer, operator]
scope: [repository_layout, runtime_paths, isolated_validation, documentation, historical_state]
summary: Task-by-task relocation plan preserving runtime identities and existing data bindings, with isolated verification before separately approved source and state cutovers.
related_docs:
  - system/specs/2026-10-01-repository-layout-design.md
  - system/modularity.md
  - system/runtime/runtime_ide.md
  - system/standards/documentation_standard.md
supersedes: []
-->

# Repository Layout Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (the user's selected method) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved README plus `runtime/`, `system/`, `docs/` and private `workspace/` layout without changing experimental behavior, module contracts or historical evidence.

**Architecture:** First make roots explicit while current paths remain authoritative, then migrate system documents and the coherent executable tree in a hardware-isolated checkout. Source integration and private-state migration are separate maintenance operations; the latter uses immutable-record-compatible readers and retains recoverable originals. These are dependent migration phases, not independently deployable features, so one ordered plan governs them.

**Tech Stack:** Existing Python >=3.11, pathlib/dataclasses, FastAPI, YAML/JSON, pytest and Node tests; Git tracked-file manifests and Linux bubblewrap isolation. No new production framework or model/device workload.

**Spec:** [Approved repository-layout design](../specs/2026-10-01-repository-layout-design.md).

## Global Constraints

- `runtime/` is a filesystem container, not a new Python package namespace.
- No experiment ordering, model selection, device command, completion criterion, threshold, timeout, recovery authority or active run-state changes.
- No permanent forest of old-root symlinks; necessary hidden Git/environment tooling remains at the outer root.
- Preserve the four graph identities, ten module declarations and seven specialist package manifests at the audited baseline.
- Logical package references remain `graphs/modules/<id>/module.yaml`; frontend namespaces/factories and public URLs remain unchanged.
- Runtime ingestion is an explicit allowlist, not a scan of all `system/` or `docs/`.
- Preserve effective project/specimen guide text, owner execution excerpts, evidence bytes/hashes and immutable checkpoint envelopes.
- No directory-existence-based authority selection and no implicit activation of empty replacement stores.
- Do not merge the unrelated report-agent worktree or move external installations, datasets, calibrations or model caches.
- OS isolation must exist before any `app.main` import, including pytest collection.
- No production restart, live structural reload, automatic resume, one-cycle stop rule or new production gate is introduced by this plan.
- Source and private-state cutovers each require a separately agreed stopped/quiescent maintenance point.
- A baseline failure stays distinct from a migration regression; never delete behavioral assertions to pass relocation tests.

## Review Focus

1. A refresh, second launch directory or filtered worker must not select different source or state roots (Tasks 2, 7, 11).
2. Old and new stores both existing must not silently select the newest/nonempty copy (Tasks 2, 12).
3. A copied checkpoint can contain valid hashes but escaping paths, prefix collisions or the wrong run identity (Task 6).
4. A document move can leave apparently valid Wiki pages with stale hashes or changed effective prompts (Tasks 5, 8).
5. A fresh install or forced Git add can accidentally package/publish private namespace data (Tasks 3, 9).

## Execution conventions and ownership

The pre-work baseline `c3c0c6e` was pushed. Documentation retirement is local commit `a79340c`; it removed 169 reviewed texts only. At execution start record the actual plan-approved HEAD as the migration baseline; do not assume either earlier inventory count is still current.

Use `superpowers:using-git-worktrees` at execution time. Create a dedicated worktree and tracked-only sandbox export, never repurpose `.worktrees/report-agent`. A worktree isolates edits, **not processes or hardware**. No execution is authorized by the existence of this plan alone.

Before Task 9, paths below are current repository-relative paths. After Task 9, executable files/tests/tools gain `runtime/`; system-document paths follow the explicit Task 1 manifest. Git commands always run at the outer checkout. Every task ends with a scoped commit after its verification; no `git add .`, force push, reset or production deployment.

All executable validation below means the Task 1 namespace with a fresh dependency environment. Commands using `python`, `pytest` or `node` run there, never in the operating checkout. The plan's `check TASK_ID` command resolves test paths from the manifest, sets the executable working directory and writes private test results. Missing dependencies are reported, not worked around by importing the operating `.venv`.

### File responsibilities

| Owner | Files to create or change | Responsibility |
|---|---|---|
| Migration harness | `tools/repository_layout/{manifest,sandbox,fixture_server,checks,move_files}.py`, package initializer; `docs/maintenance/repository_layout_manifest.json` | Tracked-file accounting, OS boundary, fixture injection, checks and explicit moves |
| Root contract | `utils/runtime_paths.py`, `utils/paths.py`, `configs/repository_layout.json` | Pure immutable bindings; root-specific resolution |
| Runtime consumers | `app/{bootstrap,controller,main,serve,cli}.py`, `agents/base_agent.py`, consumer manifest | Bind source/configuration/system/private domains explicitly |
| Knowledge | `knowledge/{wiki,context_service,graphify_bridge,source_runtime,markdown_runtime}.py`, `knowledge/manuals/service.py` | Separate curated source and writable stores; preserve IDs and references |
| Historical readers | `utils/persisted_references.py`, recovery/read-review/archive consumers in Task 6 | Schema-specific read-time aliases, not record rewriting |
| Delivery | `pyproject.toml`, installers, CI, publication guard, worker launchers | Coherent runtime-tree installation and private-path protection |
| Private cutover | `scripts/maintenance/migrate_private_state.py` | Offline copy/verify/bind proposal, separate operator gate |

## Task 1: Reproducible inventory and hardware-isolated verification harness

**Files:** Create the migration harness files above and `tests/unit/test_layout_validation_sandbox.py`, `tests/unit/test_layout_manifest.py`; create the public manifest under current `docs/maintenance/`. No production application edits.

**Interfaces:** `build_manifest(repository_root: Path, revision: str) -> dict`; `validate_manifest(manifest: dict) -> list[str]`; `sandbox_command(snapshot: Path, dependencies: Path, argv: list[str], *, cwd: str) -> list[str]`. CLI: `python -m tools.repository_layout.checks check TASK_ID`; the module's `CHECKS: dict[str, list[list[str]]]` pins the commands listed in subsequent tasks. `fixture_server.main(*, lifespan_mode: str, port: int = 17860) -> int` accepts only `import_only` or `fake_services`; `checks.main(argv: list[str] | None = None) -> int` exits zero only when every required check passes.

- [ ] Write failing tests: every tracked entry has one disposition; missing/duplicate/colliding targets fail; mode and symlink target are inventoried without following them. `assert set(manifest['entries']) == set(tracked_paths)` and `assert validate_manifest(duplicate_target_fixture)`.
- [ ] Run `python -m pytest -q tests/unit/test_layout_manifest.py tests/unit/test_layout_validation_sandbox.py`; expect missing harness interfaces before implementation.
- [ ] Implement manifest schema `atr.repository_layout.v1`: baseline commit, per-path destination/disposition/reason/mode/Git blob/SHA-256, approved content-change categories and typed consumer rows `(file, symbol, expression, root_kind)`. Classify every entry using the spec, including symlinks, legal files, independent bundles and generated ROS outputs. Record generated manifest self-updates explicitly, not as unexplained hash drift. No private-path inventory is public.
- [ ] Implement tracked-only export and separate dependency environment with no user site, production `.pth` or editable finder. Pre-stage dependencies outside the execution namespace; mount only the validation dependency tree, not production `.venv` or home. Use private network/PID/mount/IPC/device namespaces, dropped capabilities, no host `/sys`, no device/GPU/display/container sockets, private HOME/cache/temp, and bounded test-owned process cleanup.
- [ ] Add containment tests before importing the app: production path unreadable, host PID unavailable, non-loopback network denied, device open denied. `assert boundary['host_paths_visible'] == []`; `assert boundary['device_nodes'] == []`; denied attempts are counted and expected only in this negative test.
- [ ] Implement fixture bootstrap inside the namespace: inject synthetic `_load_configs`, controlled model responses and fake device/process/lifecycle services **before** importing `app.main`. Serve the real routes at `127.0.0.1:17860`, one worker, no reload; client/browser runs in the same namespace. Import/route tests and fake-service lifespan tests are separate modes. Never invent a supported virtual PLC YAML transport.
- [ ] Verify with `python -m tools.repository_layout.checks check 1`: actual API/static/module routes, import origins, zero unexpected external effects, no outside-copy writes. Record baseline failures individually; this is software-only evidence. Commit `test: add isolated repository migration harness`.

## Task 2: Immutable explicit roots with legacy data still authoritative

**Files:** Create `utils/runtime_paths.py`, `configs/repository_layout.json`, `tests/unit/test_runtime_paths.py`, `tests/unit/test_runtime_path_consumers.py`; modify `utils/paths.py`, `app/bootstrap.py`, `app/controller.py`, `agents/base_agent.py`, `app/main.py`.

**Interfaces:** Frozen `RuntimePaths` with `repository_root`, `runtime_root`, `system_root`, `workspace_root`, `run_root`, `memory_root`, `artifact_root`, `output_root`, `source_inbox_root`, `user_file_root`, `log_root` (all `Path`). `load_paths(layout_file: Path, *, bindings_file: Path | None = None) -> RuntimePaths`; `current_paths() -> RuntimePaths`; `resolve_runtime_path(value: str | Path, *, paths: RuntimePaths | None = None) -> Path`; equivalent repository/system accessors and `resolve_data_path(store: str, value: str | Path = '.', *, paths: RuntimePaths | None = None) -> Path`.

- [ ] Add `test_resolution_is_pure_and_cwd_independent`, `test_explicit_legacy_binding_wins_without_copy`, `test_conflicting_bindings_fail`, `test_unselected_populated_stores_fail`. Assert equal bindings from outer/runtime CWD and unchanged file inventory; use unrelated source/data directories rather than convenient siblings.
- [ ] Run `python -m pytest -q tests/unit/test_runtime_paths.py tests/unit/test_runtime_path_consumers.py`; expect missing interface failures.
- [ ] Implement schema `atr.path_layout.v1`: paths relative to the layout file, named defaults relative to the explicit repository root, and optional private `atr.path_bindings.v1` selected stores. `ATR_LAYOUT_CONFIG` names the layout file; `ATR_PATH_BINDINGS` names the private bindings file. Reject contradictory explicit bindings. Without overrides the transitional checked-in layout binds existing stores, never `workspace/`; no mkdir or copying during resolution. Select configuration by explicit value or the canonical runtime config path, not directory search.
- [ ] Keep `project_root()` and `resolve_path()` compatibility semantics repository-relative until all internal consumers are classified and converted. Add optional `paths` fields to `ControllerDeps`/`AgentContext` without changing positional constructors; `load_runtime(*, paths: RuntimePaths | None = None)` finalizes bindings before module-global consumers. Production bootstrap always supplies the same object; test contexts explicitly supply disposable roots.
- [ ] Route `.env` to repository root; configs/web/sim/graphs to runtime root; guides to system root; stored settings/logs/runs/artifacts to named roots. Preserve explicitly configured existing `system.run_root`, guide and storage settings through typed config loading; defaults must not override operator settings. Classify absolute external paths without remapping them. No `run_root.parent` substitute in missing-context cases.
- [ ] Run Task 2 tests plus `tests/unit/test_source_runtime.py`, `test_knowledge_archive_intake.py`, `test_run_review.py`, `test_experiment_runtime.py` in the sandbox. Compare resolved flat-baseline paths and rendered owner prompt text. Commit `refactor: separate runtime and private path bindings`.

## Task 3: Privacy and exact asset-relocation policy before moving files

**Files:** Modify `.gitignore`, `scripts/verify_knowledge_publication.py`, `docs/knowledge/publication_allowlist.json`, `tests/unit/test_knowledge_publication.py`, `.github/workflows/knowledge-publication.yml`.

**Interfaces:** Preserve `inspect(root, base=None, head=None)` and `private_path(path)`; add `validate_relocation_asset(root: Path, record: dict, *, base: str, head: str | None) -> bool`. Review records contain exact source/destination/baseline/size/SHA-256, not directory exemptions.

- [ ] Extend temporary-Git tests: forced-added `workspace/memory/secret.json`, `runtime/runs/raw.csv`, `system/knowledge/manuals/sources/private.pdf`, alternate separators/traversal and absolute inputs are rejected, including when allowlisted. Only manifest-enumerated tracked `memory/*.py` source may move to `runtime/memory/`; a new Python-looking private file is rejected.
- [ ] Add exact large-asset tests: unchanged source/destination passes only with a valid baseline; changed bytes, sibling destination, wrong source and missing baseline fail. Run `python -m pytest -q tests/unit/test_knowledge_publication.py` to observe new failures.
- [ ] Implement nested protection before ignore/move changes. Preserve existing private-root rules during transition and protect all private `workspace/` stores. Keep `MAX_BLOB = 5_000_000` and credential/private-path checks stronger than any asset approval.
- [ ] Authorize only the existing Piper ONNX relocation: `models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx` to the same suffix under `runtime/`, size `63201294`, SHA-256 `5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f`; validate these values against the frozen baseline before use. Explicitly rekey other approved asset hashes/corpus prefixes through the manifest at each move, never refresh evidence approval merely by filename.
- [ ] Run all publication tests and staged/outgoing scans with both flat and split fixtures. Commit `fix: preserve publication boundaries across repository relocation`.

## Task 4: Preserve module/package/Runtime IDE contracts under explicit source roots

**Files:** Modify `app/main.py`, `orchestrator/langgraph_runtime.py`, `agents/control_structure.py`, owner descriptor reference fields identified by Task 1, `scripts/render_module_control_views.py`; extend `tests/unit/test_package_contracts.py`, `test_langgraph_runtime.py`, `test_module_control_views.py`; create `tests/unit/test_runtime_reference_roots.py`. Existing `graphs/{module_store,version_store,generated_adapter}.py` interfaces stay injectable.

**Interfaces:** `resolve_runtime_reference(value: str, *, paths: RuntimePaths) -> Path` and `resolve_document_reference(value: str, *, paths: RuntimePaths) -> Path` in `utils/runtime_paths.py`. Code-owned references only; no resolver is added to incoming package validation. `render(module_id: str, runtime_root: Path)` retains the renderer's existing result shape; CLI receives a separate document output destination.

- [ ] Add old/new fixture tests asserting identical seven package payloads, graph semantic projection, ten module identities and owner catalogs. Test traversal/symlink rejection and detached drafts that cannot activate or open arbitrary source files. Run the three extended suites plus the new suite; expect root-location failures.
- [ ] Bind graph source to `runtime_root/graphs`, module source to `runtime_root/graphs/modules`, and graph/module version stores to named memory. Preserve the graph loader's **graphs-directory** input, not a modules-directory substitution. Keep package regex `graphs/modules/<id>/module.yaml`, public imports, schemas, versions and generated adapter trust checks.
- [ ] Classify descriptor implementation/config/frontend references as runtime-relative and documentation as repository-relative. Preserve identity strings where their logical base stays the same. Keep `/module-assets/...` activation/containment behavior and Runtime IDE source-path display; do not create a new source-open endpoint.
- [ ] Exercise create/validate/save/version/rollback/import/export with disposable modules through `tests/integration/test_agent_execution_graph_api.py`, `test_packages_api.py`, `test_design_module_lifecycle.py`; run `tests/unit/test_orchestrator_capabilities.py`, `test_ide_module_lifecycle_js.py` and Node `agent_module_host`, `module_execution_editor`, `module_control_view`, `module_control_structure` tests. No pinned execution semantics change; record metadata-only graph hash differences explicitly. Commit `refactor: bind module lifecycle to explicit runtime roots`.

## Task 5: Separate curated Knowledge inputs from learned state

**Files:** Modify `knowledge/{wiki,context_service,source_runtime,markdown_runtime,graphify_bridge}.py`, `knowledge/manuals/service.py`, `app/bootstrap.py`, `app/controller.py`, `app/main.py`; create `tests/unit/test_knowledge_layout_compatibility.py`; extend existing Wiki/manual/RAG/Graphify tests.

**Interfaces:** `WikiCatalog(project_root: Path | None = None, *, corpus_root: Path | None = None, source_root: Path | None = None)` retains explicit old-call compatibility but rejects missing/contradictory root selection; production passes both roots. Extend `KnowledgeContextService` with keyword-only `wiki_corpus_root`, `wiki_source_root`; extend `ManualKnowledgeService` with `manual_data_root`, retaining `runtime_root` solely as a deprecated writable-data alias and rejecting conflicting aliases. Extend `library_for`/`store_for` with explicit library/inbox/memory roots while preserving return types. Extend `scan_project_graph` with explicit `runtime_root`, `corpus_paths`, `reference_map` and existing output/options.

- [ ] Add fixture assertions: `assert before.execution_excerpts == after.execution_excerpts`; `assert before.guide_chunks == after.guide_chunks`; all 23 Wiki identities/citations and `verified_at` remain equal; changing a source byte produces stale status. Conflicting manual aliases fail; registry-relative source resolution stays identical. Run `python -m pytest -q tests/unit/test_knowledge_layout_compatibility.py` and confirm new failures.
- [ ] Remove Wiki's existence-based bundled fallback; select corpus and reviewed-source base separately. Route project guide and controller specimen guideline through system roots, not `run_root.parent`. Preserve the controller's effective guide text/source marker; record any relocated provenance metadata separately from prompt content.
- [ ] Inject learned-memory, manual-data, library and inbox roots explicitly. Keep manual sources relative to registry location; do not instantiate a new empty SourceLibrary at a new default location as a side effect of root resolution.
- [ ] Give Graphify runtime import resolution and an explicit repository-relative technical corpus allowlist; never scan the whole new checkout/system tree. Reconcile path-derived node identities using Task 1's reference map in both fallback and optional external engines; preserve edges instead of silently creating a disconnected duplicate graph.
- [ ] Test real fixture import edges with an existing Python target, private/symlink corpus exclusion and identity reconciliation. Run `test_runtime_wiki_safety.py`, `test_knowledge_workspace_services.py`, `test_manual_knowledge_ingest.py`, `test_manual_knowledge_retrieval.py`, `test_rag.py`, `test_graphify_bridge.py`, `test_source_runtime.py`, `test_knowledge_archive_intake.py` under `tests/unit/`, plus `tests/integration/test_knowledge_graphify_api.py`. Commit `refactor: split knowledge corpus and private storage roots`.

## Task 6: Read historical artifacts/checkpoints through typed compatibility mappings

**Files:** Create `utils/persisted_references.py`, `tests/unit/test_persisted_references.py`; modify `app/{run_recovery,equipment_tail_recovery,bo_budget_recovery,run_review_routes}.py`, `utils/{agent_artifact_archive,run_review,run_review_artifacts,artifact_preservation}.py` and controller historical-source resolution.

**Interfaces:** `resolve_persisted_reference(value: str, *, schema: str, field: str, run_id: str, reference_kind: str, allowed_roots: tuple[Path, ...], relocation_map: dict) -> Path`; mapping schema `atr.persisted_reference_map.v1` stays outside immutable records. Add keyword-only `paths`/reference-root parameters to affected readers/recorders without changing original stored payload schemas.

- [ ] Add synthetic pre-move checkpoint tests: moved CSV/result/transcript reads succeed while `assert envelope.read_bytes() == original_envelope`; altered payload/evidence/backup, wrong run, traversal, symlink escape, component-prefix collision and ambiguous maps fail. Archive source aliases only address existing archive copies; no source file is opened through an alias. Run new and recovery tests to confirm failures.
- [ ] Implement explicit schema/field allowlists and complete-component matching. Fresh device/model/calibration/configuration paths never use this resolver. Identity mapping is default until approved state migration. Absolute, run-relative, source-inbox-relative and extraction-relative fields retain separate bases; unknown fields fail rather than guessing.
- [ ] In `read_checkpoint`, verify the original envelope before resolving `csv_path`/`result_path`; verify unchanged evidence/backup hashes and return the original payload. Handle transcript paths at restore, and clearance `source_result`/frame path comparisons at their own readers. Equipment-tail hash dictionary keys remain unchanged; resolve only for file opens. BO restore verifies its original envelope before transcript resolution.
- [ ] Bind archive capture allowlists and recorder image bases explicitly. Preserve original path-derived artifact IDs and content hashes. Replay's `artifact_path` remains serving authority; a readable replay must not grant resume authority.
- [ ] Run `tests/unit/test_run_recovery_checkpoint.py`, `test_equipment_tail_recovery.py`, `test_bo_budget_recovery.py`, `test_run_review_artifacts.py`, `test_agent_artifact_archive.py`, `test_run_review.py`, `test_artifact_preservation.py`, and Node `tests/js/run_review_artifacts.test.cjs`. Commit `refactor: preserve historical references through scoped path mappings`.

## Task 7: Workers, bridge launchers and remaining runtime callers

**Files:** Modify `utils/{compute_pool,monitor_process,local_pyautogui_bridge}.py`, `app/{serve,cli,safe_hot_reload}.py`, recovery subprocess CWDs, and remaining classified consumers from Task 1; create `tests/unit/test_runtime_worker_origins.py`; extend worker/launcher tests.

**Interfaces:** Add keyword-only optional `paths: RuntimePaths | None = None` to `ComputePool`, `MonitorProcess`, local bridge supervisor and their factories; internal compute `_Worker` consumes the finalized binding. Preserve worker protocol/command names and current constructor positional arguments. Explicit `runtime_root` CWD plus safe layout/binding metadata replaces ancestry inference.

- [ ] Write origin tests running bounded real compute and monitor workers from both outer/runtime launch locations, without `PYTHONPATH`: `assert all(origin.is_relative_to(snapshot_runtime) for origin in loaded_project_origins)`; no production editable finder, private original or parent environment leak. Assert identical bounded CPU result/artifact/cancellation behavior; monitor frames are synthetic.
- [ ] Run `python -m pytest -q tests/unit/test_runtime_worker_origins.py tests/unit/test_compute_pool.py tests/unit/test_monitor_process.py` and observe new origin/binding failures.
- [ ] Keep fresh interpreters `-m utils.compute_worker` / `-m utils.monitor_worker`; propagate only root metadata needed by the already-filtered compute environment. Do not expand it to inherit all secrets. Separate the bridge's executable subtree, outer hidden environment and named data/log/token/PID roots. No real bridge launch.
- [ ] Finish classified source/config/system/data callers across agents, experiments, tools, scripts and bridges. Every Task 1 consumer row must have a disposition and owning regression before relocation. Retain fresh external path configuration and standalone Windows/ROS package semantics; no behavioral refactoring of bridge logic.
- [ ] Run `test_safe_hot_reload.py`, `test_local_pyautogui_bridge.py`, `test_cli_restart.py`, `test_module_designer_cli_contract.py` under `tests/unit/`, plus worker tests. Assert original reload restrictions: structural migration is not hot reload. Commit `refactor: preserve worker and launcher roots across relocation`.

## Task 8: Move system material and repair documentation/reference metadata

**Files:** Apply approved document/asset rows of the manifest through `tools/repository_layout/move_files.py`; modify `scripts/{validate_documentation,validate_paper_publication}.py`, their tests, source-reference metadata and owner documentation fields. Manifest becomes `system/maintenance/repository_layout_manifest.json`; public doc manifest becomes `system/document_manifest.yaml`.

**Interfaces:** `apply_moves(repository_root: Path, manifest: dict, *, phase: str, dry_run: bool = True) -> dict` returns exact changed paths and hash/mode comparisons. It refuses untracked targets, collisions, escaping symlinks or changed source bytes. No deletion is inferred; only previously approved disposal/generated-output dispositions apply. `audit_document_references(repository_root: Path, manifest: dict) -> dict` in `checks.py` returns `checked`, `missing_files`, `missing_anchors`, `escaping_references`, `metadata_errors`; external URLs are counted separately, not claimed network-validated.

- [ ] Add `tests/unit/test_document_relocation.py`: mixed technical/user fixtures, same-named assets, headings, image links, YAML metadata and registry sources. Assert the complete target set, no missing internal links, guide/excerpt byte invariance and unchanged evidence values. Run this test to confirm missing move support.
- [ ] Implement moves via the explicit map; keep user tutorials/GUI tours/paper narrative under `docs/`, runtime references/curated Wiki/standards/plans/specs under `system/`. Preserve complete vendor/reference/visual bundles and independent Windows documentation in their owner subtree. Do not treat the retired-design ledger as a new deletion list.
- [ ] Rewrite only reference-bearing fields/links and owned configuration defaults. Remap Wiki `source_refs` and matching `source_revision` keys; unchanged source bytes retain hashes, changed sources remain stale until reviewed, and `verified_at` is not refreshed. Preserve frozen execution excerpts even when navigation changes. Registry sources, asset links and generated figure destinations use their own bases.
- [ ] Update document/publication validators to repository-root semantics and the exact new legal/citation locations from the spec. Migrate allowlist keys/corpus prefixes atomically. Keep dated audit inventories historically accurate; explicitly link their historical baseline instead of rewriting old claims.
- [ ] Extend the new relocation tests with Markdown/HTML/RST links, URL-encoded paths, fragment anchors, images, fenced-code false positives and metadata references. Implement the full tracked-document reference audit, including documents outside the selected public manifest; assert all four issue lists are empty in the target fixture.
- [ ] Run `python scripts/validate_documentation.py --root .`, `python scripts/validate_paper_publication.py --root .`, and `python -m tools.repository_layout.checks check 8` for all tracked-document references, publication tests and Task 5 comparisons. Root commands here are before Task 9; afterward use `runtime/scripts/`. Commit `refactor: separate system references from user documentation`.

## Task 9: Relocate the coherent runtime tree and its build/delivery contracts

**Files:** Move every executable/config/test/tool/resource row under `runtime/`; modify moved `pyproject.toml`, `uv.lock` only if required by project metadata, installers, `.github/workflows/{basic-tests,knowledge-publication}.yml`, root README and approved legal/navigation files. Create `runtime/README.md`, `tests/unit/test_distribution_layout.py` (at its moved location).

**Interfaces:** Reuse Task 8's move utility, phase `runtime`; switch checked-in layout anchors to the new source/system locations while keeping existing named private bindings. Public Python imports remain unchanged; `runtime` has no new package initializer. Distribution remains `autonomous-researcher`.

- [ ] Add target-layout tests in a disposable copied tree: sole visible root file `README.md`; exact manifest paths/modes/hashes; intended modules/assets included in wheel/sdist; no namespace-discovered private memory, credentials or output files. Run against the pre-move tree and record expected location failures.
- [ ] Move peers together, retaining scripts/libs/models/config/web/sim sibling topology. Keep Python package names and include the package README/license inside the build project. Restrict setuptools discovery to intended source packages/resources; private filenames are negative fixtures, not the only privacy check.
- [ ] Update both Linux **and Windows** jobs in `basic-tests.yml`; publication scanning still uses outer Git root. Split `test_install_packaging.py` runtime file base from outer `.github` base. Update Linux/Windows bootstrap, CLI generation and TTS launchers to outer environment/runtime source roots; do not install a host launcher yet.
- [ ] Move the whole Windows bridge tree intact; preserve duplicated server sources with existing consumers, relative update/release manifests, portable data-root contracts and native acceptance help surface. No live Windows scheduled-task or shortcut changes.
- [ ] From the sandbox outer root run `python -m pip install -e './runtime[dev]'`; from runtime run `python -m build --no-isolation`. Inspect both archives, install the wheel into a second fresh environment, then import from outside the source tree with explicit copied resource bindings and no user site/PYTHONPATH. Assert imports come only from the intended install, not the source/editable finder.
- [ ] Run packaging/CLI/package/publication tests, shell `bash -n`, the existing Windows packaging/updater/supervisor/helper/demo tests and Windows CI PowerShell parsing. Move guards must pass before commit. Commit `refactor: place executable project under runtime`.

## Task 10: ROS/simulation/generated-output and external-dependency closure

**Files:** Manifest rows for `runtime/ros`, `runtime/sim`, `runtime/scripts/vision/run_specimen_pose_snapshot.sh`, `runtime/utils/isaac_omx_mirror_mapping.py`, installer wrappers and `runtime/deploy`; create `runtime/tests/unit/test_external_asset_layout.py`.

**Interfaces:** `audit_asset_references(repository_root: Path, manifest: dict) -> dict` in `tools/repository_layout/manifest.py` reports owned, explicitly external, missing or escaping references without executing scene/device code. Generated-output rows list their rebuild command and owning source, not a patched binary/prefix.

- [ ] Add failing tests for an owned relative USD asset, explicit external asset, missing dependency, escaping target and generated ROS prefix. Assert classified dependencies and preservation of external configuration values.
- [ ] Keep ROS source package/resource/entrypoint identities intact. Rebuild classified generated output in an isolated destination ROS environment; retain baseline history and never patch generated absolute prefixes. Required ROS/USD software must be staged into a separately reviewed read-only dependency prefix; do not mount an existing workspace/home or weaken the namespace. If required tooling is unavailable, record that specific gate as outstanding rather than claiming compatibility or running Isaac/GPU workloads.
- [ ] Inspect both text and binary USD dependencies using a read-only USD inspection library/tool; use asset-relative paths for owned assets and explicit configuration for external assets. Keep Docker wrapper mount/CWD behavior and deployment namespace/NodePort/GPU-cache contracts unchanged. No Docker/Kubernetes/simulator action is a relocation test.
- [ ] Run the new suite; existing `test_specimen_pose_tracker.py`, `test_isaac_lab_robotis_omx_registration.py`, `test_isaac_grip_pad_inset.py`, `test_camera_vision_package.py`, `test_utm_runtime_stack_script.py`, `test_utm_runtime_camera_env.py`, `test_linear_interpolation_options.py`, `test_lerobot_bridge.py`, `test_plc_bridge.py`, `test_plc_bridge_service.py`, `test_lerobot_gui_static.py`; integration RTC queue test, Node `omx_environment_layout.test.cjs`, library transmitter tests. Commit `test: verify relocated external and asset boundaries`.

## Task 11: Whole-branch regression, actual API/GUI check and source cutover package

**Files:** Complete `tools/repository_layout/checks.py`; create synthetic `tests/integration/test_repository_layout_equivalence.py`; update root README/user installation instructions and `system/maintenance/repository_layout_cutover.md`.

**Interfaces:** Equivalence report `atr.layout_equivalence.v1` includes baseline/target revisions, file accounting, actual module import origins, source/config/state bindings, contract projections, test outcomes and unexpected-effect counters. This private validation report is not physical experiment evidence.

- [ ] Write before/after fixture assertions for initial design → specimen → vision → manipulation → equipment → analysis → knowledge/BO/Guardian, refresh/new window, interrupted owner history, pinned modules and replay. `assert target.owner_trace == baseline.owner_trace`; `assert target.unexpected_external_effects == []`; `assert target.original_evidence_hashes == baseline.original_evidence_hashes`. All models/transports are controlled.
- [ ] Run real API/controller/Runtime IDE paths, not just a static fixture UI: `test_docs_endpoints.py`, module API suites, `test_all_agent_loop_archives.py`, `test_orchestrator_handoff_projection.py`, `test_analysis_saved_archive.py` and new equivalence suite under `tests/integration/`; all existing unit/JS tests within isolation. Classify unrelated baseline failures separately and fix only migration regressions.
- [ ] Start the temporary real-route server in both import-only and fake-lifespan modes. Use the existing UI audits from `tests/ui/` and in-namespace browser at 1920×1080: main/Live/Replay, all owner cards/artifacts, module designer/package lifecycle, user/system document navigation. Preserve existing layout; record screenshot/console/route evidence. Do not expose the sandbox by sharing host network.
- [ ] Check every manifest consumer/disposition, byte-preserved guides, Wiki freshness, archive IDs/hashes, four graph semantic projections, ten module and seven package identities, legal links, publication gates and both launch directories. Ensure no unexplained file, permission, symlink or binary changes. Obtain whole-branch review before integration.
- [ ] Commit the verified source/documentation and cutover runbook. Report unresolved external/native gates explicitly. **Pause production cutover for the separately approved source-maintenance point**: preserve active state, quiesce every writer, integrate source, regenerate the launcher/environment bindings and validate readiness without automatic resume. Until that approval, keep the operating checkout/server unchanged and the isolated branch available. Task 12's tooling and synthetic rehearsal may continue on that branch; the pause does not require production downtime to finish software development.

## Task 12: Private-state copy/verify tooling and final separately approved migration

**Files:** Create `runtime/scripts/maintenance/migrate_private_state.py`, `runtime/tests/unit/test_private_state_migration.py`; extend the cutover runbook. Private manifests/binding files stay outside public Git.

**Interfaces:** `plan_copy(source_bindings: dict, destination_bindings: dict) -> dict`; `copy_and_verify(plan: dict, *, writers_quiescent: bool) -> dict`; `propose_bindings(verified_manifest: dict) -> dict`. CLI modes `plan`, `copy`, `verify`, `propose-bindings` never restart/resume/delete or automatically activate proposals. Private schema `atr.private_state_migration.v1` records paths/hashes/modes/permissions, compatibility-map version and selected bindings.

- [ ] Write synthetic tests for open writer rejection, copy interruption, hash/mode mismatch, collisions, permission errors, symlink escapes, populated dual stores and post-copy source change. `assert not result['activated']`; `assert source_bytes_after == source_bytes_before`; post-write rollback cannot overwrite newer destination records.
- [ ] Run `python -m pytest -q tests/unit/test_private_state_migration.py` in the migrated sandbox; implement the minimal copy/verify/proposal functions using explicit named roots, no real-store discovery during development. Keep originals recoverable and supply the Task 6 reference map only after verification.
- [ ] Rehearse with synthetic multi-cycle artifacts, manual library, knowledge stores, generated IDE versions and all checkpoint types. Replay must remain read-only; successful playback does not certify resume. Re-run Tasks 2, 5, 6 and 11 on the synthetic migrated stores; commit only tooling/tests/runbook.
- [ ] **At the separately approved offline state-maintenance point only:** privately inventory selected real stores, quiesce all writers, copy to `workspace/`, verify bytes/hashes/permissions, then have the operator explicitly select the proposed bindings. Preserve originals outside the checkout if root cleanup is required; no recursive deletion. Do not change external installs or immutable records.
- [ ] Validate readiness and historical readers without automatic equipment operation. Report final visible-root inventory and retained backup location privately. A hardware smoke run or resume needs its own request; no automatic run is part of this migration.

## Self-review and handoff

Design coverage: layout/accounting → Tasks 1/8/9; explicit roots and all consumers → 2/4/5/7; ingestion/reference invariants → 5/8; historical state → 6/12; packaging/deploy/privacy → 3/9/10; isolation/API/GUI → 1/11; separate cutover/rollback → 11/12. The five Review Focus cases are explicitly assigned tests above.

The user has selected subagent-assisted execution. Parent owns shared root interfaces, manifest review and integration; independent agents may work concurrently only on non-overlapping consumers after shared interfaces are committed. Fresh task review precedes the next dependent task. This plan is ready for user review, not yet executing; no temporary app server or source relocation has been performed while writing it.
