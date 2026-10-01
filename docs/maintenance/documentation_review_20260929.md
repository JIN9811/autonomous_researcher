<!-- atr-doc
doc_type: evidence
subtype: audit
status: active
authority: evidentiary
audience: [developer, maintainer, operator, researcher, reviewer]
scope: [documentation, navigation, provenance, historical_material]
summary: File-by-file documentation review and link audit against the September 29 main baseline.
evidence_date: 2026-09-29
method: Full textual reads, static source inspection, local path and anchor checks, public URL requests, and no-device documentation regressions.
related_docs:
  - docs/README.md
  - docs/maintenance/code_documentation_audit_20260928.md
  - docs/standards/documentation_standard.md
supersedes: []
-->

# File-by-file documentation review — 2026-09-29

## Scope and method

Baseline: `dd0d772472d5d44bfef690e6258fc62270192b96` on `main`.
The inventory covers tracked documents throughout the repository, not only
governed or recently changed pages: Markdown, RST, text, archived HTML and vendor
PDFs, plus `LICENSE` and `CITATION.cff`. Dependency text files are reviewed as
installation inputs. A filename scan or validator pass is not a full read.

Private runs, downloaded dependencies, ignored local archives and the separate
report-agent worktree are outside the public-document scope. Runtime HTML and
JavaScript are implementation evidence rather than extra documentation pages.
The two vendor PDFs were read through their complete text layers (50 and 66
pages); image-only labels/screenshots are not claimed as exhaustively visually
audited. Existing GUI/tutorial images retain their original capture manifests.

## Corrections

| Area | Reconciliation |
|---|---|
| Navigation | Rebuilt the index around reader tasks and owning references; fixed installation self-links |
| Agents/bridges | Removed current-tense retired FEM/CAE and automatic Self-Evolution claims; reconciled seven canonical bridges and supplementary PLC |
| Modes/effects | Corrected universal no-device Test claims, passive-only Vision descriptions and permissive preflight versus enforced guard distinctions |
| Analysis/BO | Matched half-height SEA, slicer-derived mass, cell-size/wall-thickness variables and current 2D/3D GP views |
| GUI/deployment | Reconciled report, recovery, archive, worker, model and Windows installation behavior without changing implementations or saved settings |
| Installation | Corrected solver/fallback, camera adapter, isolated model environment and Windows deployment instructions |
| Evidence | Distinguished the fifteen-observation campaign from earlier one-cycle evidence and unattended-reliability claims |
| History | Read archived plans, specifications, HTML and prompts; preserved dated requirements and added current-owner navigation |
| Links | Checked relative files, anchors, images, metadata paths and public references; distinguished removals from access restrictions |

Old proposals are not converted into fictional implementation records. A dated
FEM plan remains a plan; its proposed test does not become current experimental
evidence. Missing private artifacts are marked local-only/unavailable, not
published or linked to nonexistent public files.

## Runtime-sensitive exceptions

`docs/project/Project_guide.txt` is still loaded through `configs/system.yaml`
and `app/bootstrap.py`; `backends/prompt_registry.py` calls that context
authoritative. Its reviewed text contains stale operational claims: old FEM/CAE,
synthetic substitution and device-effect assumptions. Its bytes are preserved.
Replacing a runtime prompt needs a separate behavior change and regression review,
not a silent documentation edit.

The directly loaded
`docs/agents/specimen_design_existing_runtime_guideline.txt` and owner-specific
Wiki **Runtime decision reference** excerpts are also preserved. Wiki source
hashes are refreshed only after source review; no owner acceptance criteria are
changed. Other source-level mismatches remain explicit: the graph can still
project retired Knowledge/Evolution terminology, and permissive Isaac mirror
preflight is not proof of a connected receiver.

No executable graph, agent, bridge, configuration, service or device is modified
by this review. No server restart or experiment is performed.

## Link interpretation

File existence and heading anchors are checked separately. Code examples, local
application URLs and private-address placeholders are not requests to operate
devices. External HTTP success proves reachability, not scientific correctness
or equivalence of a replacement page.

Verified same-version BoTorch pages and a pinned historical BambuBoard guide
replace broken navigation. Retired NVIDIA version pages and the missing
`darkorb/bambu-ftp-and-print` repository retain provenance with availability notes.
The ChemRxiv article initially returned 404, but retry reached the matching
title/abstract/DOI; it is not labelled permanently unavailable. A current index is not presented
as the original version-specific article. Publisher restrictions, throttling and
network failures remain separate from confirmed missing destinations.

## Verification record

The [per-file ledger](documentation_review_20260929.json) contains **512 unique
baseline files**, with no omitted or duplicated inventory entries: 280 historical
archive documents, 49 runtime/GUI/package documents, 39 agent/device/hardware
documents, 142 root/knowledge/paper/other documents, and two license/citation files.
Every row records its disposition and reviewed-content SHA-256. The three audit
files created by this review are additional outputs, not part of that baseline.

The [link ledger](documentation_links_20260929.json) records:

- **2,237** local file/anchor/image references in the baseline document tree;
  **zero missing file or heading targets**.
- **1,012** provenance/related-document metadata references checked; no missing
  current targets. Original retired aliases are retained as historical provenance.
- **318** unique public URLs, including the PDF vendor reference: 296 reachable,
  11 access-restricted, two rate-limited, five network-unresolved, and four
  unavailable historical URLs explicitly annotated in their documents.
- 27 local/example URLs and one revision placeholder were not requested.
  Their existence is not a live-service health check.

Both PDF URL-object scans produced no entries; the Software Manual emitted a
Poppler optional-content warning, so this is not proof of a pristine PDF.
The Indicator Manual's printed vendor URL was separately checked. Image-only
text remains outside the exhaustive textual-link claim.

Verification commands and results:

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_paper_publication_validation.py \
  tests/unit/test_runtime_wiki_safety.py \
  tests/unit/test_knowledge_publication.py --disable-warnings --tb=short
git diff --check
```

The selected **95 tests passed**. The documentation validator and whitespace
checks passed. All **48** GUI/tutorial screenshot dimensions and manifest hashes
matched; all are 1920×1080. The two directly loaded guide files and ten Wiki
runtime excerpts were byte-compared with the baseline and are unchanged.
Wiki source hashes were refreshed in all 23 reviewed pages after source edits.
The new audit page's own local links are also checked separately from baseline
counts. These checks do not certify physical safety, every old screenshot,
external-paper correctness or scientific superiority.

The [September 28 reconciliation](code_documentation_audit_20260928.md) retains
its original date and narrower scope. This audit expands coverage rather than
retroactively claiming the earlier checks covered everything.
