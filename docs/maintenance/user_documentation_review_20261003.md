<!-- atr-doc
doc_type: evidence
subtype: audit
status: active
authority: evidentiary
audience: [maintainer, contributor, reviewer]
scope: [user_documentation, editorial_review]
summary: Scope, preservation checks, independent review and remaining boundaries of the reader-centered documentation rewrite.
evidence_date: 2026-10-03
method: Prior full-document inventory, bounded parallel editorial review, static source comparisons, documentation tests and filesystem-only checks.
related_docs:
  - docs/README.md
  - docs/README.ko.md
  - docs/maintenance/user_documentation_disposition_20261003.json
  - docs/superpowers/specs/2026-10-03-user-centered-documentation-design.md
  - docs/superpowers/plans/2026-10-03-user-centered-documentation.md
supersedes: []
-->

# Reader-centered documentation review — October 3, 2026

## What changed

The revision starts from a reader's task: install, choose a mode, complete a first
experiment, operate a workspace, recover a paused run, inspect results, or extend
a module. English and Korean entry points now follow those paths. Detailed
contracts and historical records remain available without leading the ordinary
operating instructions.

The baseline is main `ba273ddb0fc2bf8795630d51d93d3932748e0a51`. The prior inventory
read **339 tracked human-readable documents**, including historical references,
vendor manuals, licenses, and presentation provenance. This revision changes
**61 existing reader documents** and adds **three reader entry points/guides**:
the Korean documentation index and English counterparts to the two Knowledge
operating guides. It does not claim that all 339 documents were rewritten.

The [file-level disposition](user_documentation_disposition_20261003.json)
records every audited path, baseline hash, and preservation/edit decision.
The new editorial design, plan, this audit, and metadata maintenance are separate
from the reader-document count.

## Editorial decisions

- Installation and first-run guides carry the reader through result inspection,
  not just launch. Optional hardware branches follow the basic path.
- Paired printer and Vision guides retain their controls, units, commands,
  screenshots, physical-effect boundaries, and failure branches.
- Live GUI and recovery pages begin with tasks and symptoms. The long existing
  GUI implementation/history ledger is retained in a labeled expandable section.
- Knowledge guides distinguish public Wiki, Source Library, execution Markdown,
  private memory, and delivery evidence. Retrieval and delivery are not claims
  of model use.
- Research chapters present actual retained setup and results before proposed
  evaluation protocols. Historical units, failure records, interventions,
  scientific limits, and claim statuses remain distinct.
- Runtime IDE distinguishes read-only inspection from editing and activation.
  Its mandatory section order and figures remain intact.
- Reader-first guidance now applies to guides and indexes without relaxing the
  specialized agent, bridge, or Runtime IDE reference contracts.

The separate repository-layout branch was neither merged nor rewritten.
Application code, configuration, device state, model routes, and experiment data
were not changed or executed.

## Independent review and corrections

Three independent read-only reviews covered onboarding, operation/recovery,
and research/Knowledge/entry-point changes. They found no new physical-effect,
scientific-unit, privacy, or module-authority regression. Corrections made
before publication were:

1. The English manual now links to the new English Knowledge guide.
2. The read-only IDE link points to inspection, not graph activation.
3. Former root/index/guide title anchors remain reachable.
4. Printer-wait wording identifies a paused **run observing a job**, not a
   command to unpause the printer.
5. The English Windows bridge reference now agrees with
   `Pyautogui_server_for_window/scripts/install_bridge.ps1`: installation
   stays in the copied package folder, while data has a separate local root.
   The incorrect Programs installation path predated this rewrite.

The documentation validator caught an intermediate IDE section-order change,
which was corrected in the document. Paper validation also retained the
canonical System Contribution / Platform Contribution headings. No tests or
validators were weakened to accommodate the prose.

## Runtime-linked Wiki preservation

All **23 Wiki article bodies** remain byte-identical, including operational
decision excerpts. Their source sets, status, applicability, and verification
dates are unchanged. Only source-revision hashes on **11 pages** were reconciled
for **eight editorially changed source documents**, after source-equivalence
review. All 23 pages remain source-fresh under the existing hash comparison.

This is **not a new semantic certification of every Wiki statement**. Review
found an inherited discrepancy in [the artifact Wiki](../knowledge/wiki/artifacts.md):
it says an agent's Artifacts view defaults to the current loop. Both baseline
and current [owning reference](../runtime/loop_artifact_archiving.md#live-gui-file-explorer)
say it defaults to the selected agent across all indexed loops, with an explicit
loop filter. The owner reference and new user guides carry the correct behavior.
The Wiki body was deliberately preserved under the no-runtime-input-change
boundary; its correction requires a separately scoped runtime-reference review.

Legacy runtime guidelines and `docs/project/Project_guide.txt` remain verbatim.
Other retained specialist documents are not silently reclassified as rewritten
or freshly validated. The disposition map makes that boundary explicit.

## Verification scope

The editorial acceptance checks are:

- Standalone documentation validation: passed.
- Standalone paper-publication validation: passed.
- Documentation, paper-validation, and publication-guard unit suites:
  **68 tests passed**, with plugin autoload and the cache provider disabled.
- Repository-wide explicit local file, image, and heading-link check:
  no unresolved destinations in the final scan.
- Original screenshot references in changed documents: no removals.
- Protected-file scope, Wiki bodies/source sets, source freshness, and whitespace:
  passed static checks.
- Staged public-content scanning uses the existing publication guard; changed
  evidence-classified synthesis and this report receive explicit content-hash
  review rather than bypassing the guard.

These checks read files and Git history and exercise isolated documentation
tooling. They do not import the application, start servers, call model providers,
operate equipment, rerun the campaign, or test a browser. External URLs were
not network-verified. The 339-file prior review read both vendor PDFs' complete
116-page text layers and selected visual material, not every image on every page.

The existing experiment evidence and screenshot bytes are unchanged. Source
inspection and clearer wording are not new hardware or scientific validation.
