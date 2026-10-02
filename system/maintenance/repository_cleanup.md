<!-- atr-doc
doc_type: evidence
subtype: audit
status: active
authority: evidentiary
audience: [developer, maintainer, reviewer]
scope: [repository_cleanup, retired_scaffolds, reference_assets]
summary: Tracked-file cleanup decisions, preserved consumers, and guarded regression results for the September 2026 modularization baseline.
evidence_date: 2026-09-14
method: Tracked-tree inventory, Python import inspection, resource and packaging reference searches, byte comparisons, and guarded regression tests.
related_docs:
  - docs/modularity.md
  - docs/standards/documentation_standard.md
  - docs/gui/reference/live_gui_reference_alignment.md
supersedes: []
-->

# Repository Cleanup Audit

## Status at a Glance

| At a glance | Details |
|---|---|
| Baseline | `ae09f3c75a5dffc509cd5f516cb59bf6e680c8c2` |
| Inventory | 2,111 tracked files; no static Python parse failures |
| Removed | 25 generated caches, 11 unused GUI scaffolds, 2 duplicate outer files and the retired image-comparison script |
| Archived | Former UI bundle and alignment history, plus 350 previous design/plan/instruction assets; local Windows-path outputs kept private |
| Execution boundary | No change to GUI implementation, agent, bridge or orchestration behavior |
| Recovery | Removed tracked content is recoverable from the baseline commit |

## Scope and Evidence Basis

The inventory covered tracked files, duplicate Git blobs and Python imports.
Candidate decisions also checked entry points, configuration, package discovery,
documents and tests. A stale test referencing an obsolete asset does not make
that asset a current requirement: the owner confirmed that the former Live GUI
visual reference is no longer used.

## Cleanup Decisions

| Target | Final disposition |
|---|---|
| `graphify-out/cache/` | Remove 25 generated caches and ignore future `graphify-out/` output. The optional scanner's code remains intact. |
| `gui/` | Remove 11 unconsumed Python metadata scaffolds and their package-discovery entry, plus 11 disposable local compiled-cache files. Actual browser code remains in `web/` and `app/`. |
| Outer `livegui_package/index.html` and `README_KR.md` | Remove exact duplicate copies; the self-contained historical bundle retains its own entry points. |
| Former Live GUI visual-reference bundle | Archive 108 tracked assets under `docs/oldversion/livegui_package/`. Preserve its two existing public CSS/JSON design-token files using exact ignore exceptions so the historical preview is self-contained. No current test or runtime consumes the bundle. |
| Old pixel-comparison audit | Remove `tests/ui/live_gui_agent_reference_layout_audit.py` and the newly introduced reference-consumption test. Do not enforce the retired visual baseline. |
| Alignment guide | Preserve its old layout instructions and logs as archive history. Keep the current Setup/Chat contracts at the existing active document path, without reference-image acceptance rules. |
| Previous development material | Archive 185 design/plan files, 134 source-package assets and 30 older prompts/guides/proposals. Update links; keep current References, Standards and scientific evidence active. |
| Remaining Live GUI browser audit | Preserve behavioral and layout checks, but remove comparison with the retired concept image. Screenshot metrics remain diagnostic output. |
| Root documents | Remove the redundant `README.en.md` entry point and redirect its links to the main `README.md`; preserve the earlier detailed body in the archive. Keep the English main README, Korean translation, dependency reference and separate contribution/security/changelog policies. Installer-consumed requirements files remain in place. |
| Four root Windows-path directories | 201 local files, 36 unique contents and 165 duplicate copies. No open file handles or Windows bridge server process were found at inspection. Preserve all bytes under ignored `oldversion/local_windows_path_outputs/2026-09-14/`; do not publish screenshots or recordings. |
| Remaining root residues | Move `build/`, root `meta/`, `output/`, `test-results/` and `result.json` into ignored `oldversion/top_level_cleanup/2026-09-14/`. Preserve 364 files (15,121,261 bytes) with a private restoration manifest and per-file hashes. No open consumers were found; 17 local settings files contained no dataset path resolving to the repository root. |

The publication guard also rejects force-added files from the private root
`oldversion/`. The public `docs/oldversion/` remains a separate, reviewed document
archive. Regression tests cover both paths.

Archive locations and current replacements are recorded in the
[Old Version Index](../oldversion/README.md). The 40 binary reference images
remain byte-identical to the baseline. Their exact archive-path SHA-256 approvals
do not waive private-data or credential checks. Design-token exceptions cover
only the two reviewed style files, not authentication tokens.

## Preserved Boundaries

- Graph/Neo4j modules still have Knowledge/API/service/script/test consumers.
  Removing their optional functionality is a separate refactoring decision.
- Memory forwarding modules preserve canonical Knowledge import compatibility.
- Prior designs and plans are retained as history, not current instructions.
  Scientific evidence and reproduction material remain accessible.
- Installer/server copies and deployment paths retain their independent consumers.
- `autonomous_researcher.egg-info/` remains: the installed Python distribution
  currently resolves its metadata there. `outputs/` remains a configured training
  destination, `logs/` is a runtime logging location, and `tools/tts/` is used by
  the installer and LeRobot configuration. Active source packages, ROS/Isaac
  integration trees and device distribution files are not rearranged for appearance.
- `docs/project/Project_guide.txt` is still loaded by `app/bootstrap.py` through
  `configs/system.yaml`. Retain its original bytes and path; removing or replacing
  this RAG seed would be a separate runtime change, not historical cleanup.
- Equipment settings, models and installations are untouched. The local Windows-path
  output move preserves every file and has a private restoration manifest.
  Git history is not rewritten.

## Verification

The focused Graphify, Knowledge backend, canonical-import and package-contract
suite plus documentation-validator tests passes 90 tests, with five existing schema warnings:

```bash
.venv/bin/python -m pytest -q tests/unit/test_graphify_bridge.py tests/unit/test_knowledge_graph_backend.py tests/unit/test_core_agent_roots.py tests/unit/test_package_contracts.py tests/unit/test_documentation_validation.py
```

The publication-guard suite passes 21 tests, including rejection of force-added
private local archives and acceptance of public document archives. Twelve changed
Bash installation examples were syntax-checked without execution; embedded Python
home-path examples parse and use `expanduser`, rather than redirection placeholders.

The unchanged guarded original-route suite passed all five cases in 130.95
seconds during this cleanup, with 76 existing warnings. It uses controlled model
and equipment I/O, not physical equipment:

```bash
.venv/bin/python -m pytest -q tests/integration/test_orchestrator_setup_loop.py::test_confirmed_setup_enters_original_initial_lhs_and_real_design
```

Document/link checks, archived manifest/preview resource checks, byte comparisons
and publication checks are retained in the ignored maintenance workspace.
Archived preview checks establish preservation only; they are not current GUI
acceptance tests. No operating server/model service was restarted.

Post-relocation application import and the Live host FEM dependency check pass.
The broad legacy multifidelity layout test still fails on its old
`renderDashboardCard("Now printing"` assertion: the checked-in `planning.js`
already lacks that string and remains byte-identical to the baseline. This is
not recorded as passing. During verification, the still-consumed project RAG
seed was restored to its original path and bytes; executable configuration
was also confirmed byte-identical to the baseline before handoff.

## Limitations and Related Documents

This audit does not certify external consumers of the retired Python scaffold or
remove every optional subsystem. The existing unrelated Live GUI assertions and
Windows document-format debt remain outside this change. Archived historical
documents are link-checked; they are not newly certified as current References.

- [Modularity Reference](../modularity.md)
- [Live GUI Runtime Contracts](../gui/reference/live_gui_reference_alignment.md)
- [Documentation Archive Rules](../standards/documentation_standard.md#document-relocation-and-archive)
