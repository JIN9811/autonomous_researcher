<!-- atr-doc
doc_type: plan
subtype: implementation
status: active
authority: execution
execution_status: completed
audience: [developer, maintainer, reviewer]
scope: [agents, canonical_imports, module_ownership, runtime_ide]
summary: Migrate maintained callers to canonical agent owner modules and retire the unused root compatibility wrappers without changing runtime behavior.
governing_design: docs/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs:
  - docs/agents/README.md
  - docs/runtime/runtime_ide.md
supersedes: []
-->

# Agent Canonical Import Cleanup

> Implementation follows the approved agent/package modularization design and the user's approval to retire unused compatibility wrappers.

## Goal

Reduce the top-level `agents/` Python surface from 38 files to seven shared files by migrating callers to existing owner modules and retiring 31 compatibility wrappers. Git history preserves the removed wrappers; do not duplicate them in `oldversion`.

## Global Constraints

- Work in the current checkout at baseline `05d5e55687aacf7647413bb266aef8d836eb1346`. Do not commit, tag, push, or restart the user server during this cleanup.
- Preserve execution logic, API URLs, agent and handler IDs, orchestration routes, storage paths, numerical behavior, and hardware behavior.
- Do not operate hardware, run native FEM, change providers, or access private credentials.
- Retain `__init__.py`, `base_agent.py`, `control_structure.py`, `execution_graph.py`, `module_contract.py`, `module_discovery.py`, and `registry.py` at the `agents/` root.
- Retire agent compatibility imports only. Device bridge compatibility paths are outside scope.
- External callers of retired imports must migrate to canonical owner modules; do not hide aliases in import hooks or `agents/__init__.py`.
- Existing archived plans remain historical records. Active code/source links and current contracts must resolve to maintained paths.
- Keep verification evidence in this plan's ignored validation workspace, not the knowledge corpus.

## Task 1: Migrate callers and retire agent wrappers

Inspect the 31 root-level wrappers and derive their canonical targets from their imports. The owner folders are `agents/design`, `specimen`, `vision`, `manipulation`, `equipment`, `analysis`, `bo`, and `agents/core/{orchestrator,knowledge,guardian}`. No runtime implementation is to move in this task.

1. Add focused regression coverage that asserts the seven retained root Python files, canonical module imports/registry identities, and absence of retired imports in maintained runtime and test code. Demonstrate failure before removal. Preserve existing canonical root/storage tests; replace obsolete alias-identity tests with canonical-import checks.
2. Migrate actual imports, module-from-package imports, dynamic import strings, monkeypatch targets, source references, and module descriptors to canonical paths. Remove obsolete `compatibility_imports` declarations rather than relabeling canonical paths as compatibility aliases.
3. Remove all 31 wrappers with no `oldversion` copies. Keep all seven shared files and all device bridge files.
4. Update active agent/index/runtime docs, design contract and code references. Explain that compatibility retirement follows caller migration. Preserve historical evidence; redirect file links where necessary without pretending old runs used the new import layout. Review and refresh only affected public Wiki source hashes when required by changed current docs.
5. Run focused hardware-free tests spanning every affected owner, discovery, graph controls, canonical imports, and publication boundaries. Do not weaken tests or suppress freshness validation to obtain passing results. Report pre-existing failures explicitly.
6. Self-review the diff for changes beyond imports/metadata/tests/docs and report any unavoidable semantic changes before proceeding.

## Verification and Review

The controller independently runs the five existing guarded route cases in `test_confirmed_setup_enters_original_initial_lhs_and_real_design`, which block physical effects and use controlled LLM fixtures. The cases cover virtual bridge, installed-printer preparation, physical-print preparation, and next-design continuity. This is not a live hardware or live LLM validation claim.

Task and final reviews inspect the complete uncommitted diff and test evidence. Validate changed governed documentation and scan publication boundaries without staging user/private data.

## Verification Results

- The regression test first failed because all 31 root wrappers and maintained retired imports were present, then passed after caller migration and wrapper removal.
- Focused owner, discovery, graph-control, documentation, and publication suites passed: 285 tests. A second focused run covering changed decision/runtime imports and execution-graph APIs passed: 201 tests. The final canonical-root regression passed: 7 tests.
- Changed governed-document validation and the paper publication validator passed.
- The affected reviewed `guardian-role` Wiki page was rechecked against its unchanged role claims and refreshed to the new Guardian Reference hash. Other affected Wiki pages were already stale at baseline and were not rewritten. The private-index publication-boundary scan passed all 155 changed files without touching the real Git index.
- The controller's five guarded setup-route cases passed in 136.60 seconds with controlled LLM fixtures and zero physical or denied calls. The result covers virtual bridge, installed-printer preparation, physical-print preparation, next-design continuity, all ten loop-0 owners, and loop-1 Design parameter continuity. It is fixture-only evidence, not live LLM, hardware, FEM, or provider validation.
- Semantic review found no runtime structural differences beyond canonical imports, source-path references, and retired compatibility metadata.
