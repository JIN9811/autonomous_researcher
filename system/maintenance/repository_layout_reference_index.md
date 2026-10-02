<!-- atr-doc
doc_type: index
subtype: index
status: active
authority: navigation
audience: [developer, maintainer, reviewer]
scope: [repository_layout, historical_references, migration_provenance]
summary: Current navigation and explicit historical-reference boundaries for the documentation relocation.
related_docs:
  - system/plans/2026-10-01-repository-layout-migration.md
  - system/specs/2026-10-01-repository-layout-design.md
supersedes: []
-->

# Repository relocation reference index

System references now live under `system/`; user procedures and paper narrative
remain under `docs/`. This is a source-worktree migration, not a production or
private-state cutover. Runtime source remains at its previous location until
Task 9. The repository-layout manifest records exact moves, reviewed Git
identities, additions, raw-source deferrals and historical-reference accounting.

## Current navigation

- [User documentation](../../docs/README.md)
- [Agent references](../agents/README.md)
- [Device bridge references](../device_bridges/README.md)
- [Runtime IDE](../runtime/runtime_ide.md)
- [Publication rules](../knowledge/publication.md)
- [Contribution guide](../../docs/project/CONTRIBUTING.md)
- [Security policy](../../.github/SECURITY.md)
- [Migration plan](../plans/2026-10-01-repository-layout-migration.md)

## Preserved evidence and legal navigation

The exact documents below retain their complete reviewed bytes. Their embedded
paths are historical references resolved against the recorded pre-move Git
inventory, not assertions that old live paths still exist. The manifest reports
these references separately from current-link checks and records current
mapped targets where available. Evidence IDs, claims, results, approval hashes
and dates have not been refreshed. The security policy retains its legal text.

- [Equipment visual-control completion audit](../hardware/evidence/lab_equipment_utm_visual_control_completion_audit.md)
- [Artifact-archiving tests](../runtime/evidence/2026-09-06-loop-artifact-archiving-tests.md)
- [Dynamic setup verification](../runtime/evidence/2026-09-12-orchestrator-dynamic-setup-verification.md)
- [Design virtual-API verification](../../docs/paper/evidence/2026-09-07-design-gemma31b-virtual-api-verification.md)
- [Latest-cycle demonstration](../../docs/paper/evidence/2026-09-07-latest-cycle-demonstration.md)
- [Supervised closed loop](../../docs/paper/evidence/2026-09-07-supervised-closed-loop.md)
- [Vision prompt verification](../../docs/paper/evidence/2026-09-08-vision-generic-prompt-verification.md)
- [Campaign archive audit](../../docs/paper/evidence/2026-09-28-campaign-archive-audit.md)
- [Architecture inspection](../../docs/paper/evidence/architecture_inspection.md)
- [Claim-evidence traceability](../../docs/paper/09_claim_evidence_traceability.md)
- [September 29 documentation review](documentation_review_20260929.md)
- [Repository cleanup evidence](repository_cleanup.md)
- [September 28 code/documentation audit](code_documentation_audit_20260928.md)
- [Security policy](../../.github/SECURITY.md)

The dated September 29 inventories remain historical bytes. Their documented
baseline is [the September 29 Git tree](https://github.com/JIN9811/autonomous_researcher/tree/dd0d772472d5d44bfef690e6258fc62270192b96).
They are not current file counts or a replacement for the new reference audit.
`oldversion/2026-09-14-retired-computation/README.md` was non-distributed local-only
historical material; no public Git recovery URL is asserted for it.

## Reviewed Wiki migration provenance

The 23 topic identities, original reviewed timestamps and literal execution
excerpts remain unchanged. Reference-only edits to their 21 source documents
are recorded with exact before/after identities. Independent checkpoint review
verified reference-only edits before the controller authorized the exact 47
topic/source digest rebindings across these 23 previously fresh pages. Original
verified_at and semantic review fields are preserved. Separate migration
provenance is recorded in `repository_layout_reference_provenance.json`;
already-stale or substantively changed sources are not refreshed. The existing
freshness filter remains unchanged. No query, filtering or ingestion policy changes.

## Cutover runbook handoff: raw manual sources

The two tracked PDFs at `docs/knowledge/manuals/sources/Indicator Manual.pdf`
and `docs/knowledge/manuals/sources/Software Manual.pdf` remain at their original
locations with unchanged bytes and modes. The relocated manual registry refers
back to those exact files relative to its own directory. The source inbox's
selected binding is unchanged; no replacement private store is activated.

A later separately approved stopped/offline private-state phase must decide
copy verification and untracking, record identities and ownership, and retain
recoverable originals before changing bindings. Neither operation is executed
here. Existing privacy rules and the publication size limit remain in force;
there is no new PDF publication exception or directory exemption.
