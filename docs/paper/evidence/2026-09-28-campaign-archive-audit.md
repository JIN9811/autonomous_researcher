<!-- atr-doc
doc_type: evidence
subtype: audit
status: active
authority: evidentiary
audience: [researcher, reviewer, developer]
scope: [campaign_archive, artifact_lineage]
summary: Read-only reconciliation of fifteen retained Gyroid experiment iterations.
evidence_date: 2026-09-28
method: Inspect completed owner results, verify preserved artifact hashes and identities, and reproduce the recorded SEA normalization.
related_docs:
  - docs/paper/evidence/2026-09-28-campaign-archive-summary.json
  - docs/runtime/loop_artifact_archiving.md
  - docs/paper/06_evaluation_and_results.md
supersedes: []
-->

# Fifteen-iteration campaign archive audit

## Summary

The retained campaign contains **15 completed Analysis observations** with
matching Design and Specimen results, generated Gyroid STL, canonical
stress–strain data, PNG/SVG curves, metrics and next-point records. This replaces
the outdated statement that only a one-cycle archive exists. It is a read-only
audit of recorded outputs, not a new hardware experiment.

## Scope and Evidence Basis

Evidence ID: `E-INSPECT-CAMPAIGN-001`. The
[machine-readable summary](2026-09-28-campaign-archive-summary.json) retains
per-iteration numeric values and SHA-256 identities without copying private
paths, screenshots, device connections or the raw dataset into public docs.
The local raw archive remains the source; the summary alone is not a complete
replay package. Inspection baseline: main `e70daa1`. The experiment used a
changing working tree and recovery interventions, not one fingerprinted clean
commit. This audit does not relabel those interventions as autonomous recovery.

## Reproduction Protocol

From the retained run's `runtime/loops/loop-*/` tree:

1. Enumerate each agent's `attempt-*/manifest.json`; count all statuses, including
   failures and cancellation. Do not read only the latest-view aliases.
2. For each of iterations 1–15, select the latest result with both manifest and
   result status `completed` for Design, Specimen, Analysis and BO.
3. Check run/loop/attempt identity. Bind the Design **result's** `experiment_spec`
   to Specimen and Analysis specimen identity. A Design manifest can identify
   the incoming previous specimen and is not sufficient alone.
4. Resolve manifest entries whose status is `copied`; require paths within the
   run and matching SHA-256. Compare Design and Specimen `result.stl_path` hashes.
5. Check Analysis canonical CSV row count against the curve's `point_count`;
   require the preserved metrics JSON to equal the result's metrics. Require
   preserved stress–strain PNG and SVG files.
6. Recompute `energy_absorption_50pct_mJ / 1000 / mass_g`; compare with recorded
   `specific_energy_absorption_J_per_g` within `1e-6` J/g. This checks recorded
   normalization, not independent recalculation of the raw-curve integral.
7. Keep BO's output after iteration N separate from the specimen tested at N.
   Check final-report behavior at the approved campaign limit.

No device, model, controller API, restart or data rewrite is part of this protocol.

## Results

| Check | Recorded result | Interpretation |
|---|---|---|
| Iteration identities | 15/15 matched | Design-result, fabrication and Analysis linkage |
| Generated STL | 15/15 Design–Specimen hashes matched | Original geometry, not an auto-oriented slicer substitute |
| Curves and metrics | 15/15 present with matched manifest hashes | Each canonical curve has 48,005 or 48,006 rows |
| SEA normalization | 15/15 matched within `1e-6` J/g | Energy to 50% initial height divided by slicer mass |
| BO terminal result | Iteration 15 is `final_report`, decision `completed`, no next candidate | No unwanted iteration-16 recommendation |
| Invocation archive | 485 attempts: 471 completed, 13 failed, 1 cancelled | Invocation counts are not a task/physical success rate |

This campaign's recorded domain is cell size 6–9 mm and wall thickness
0.6–0.9 mm, with 30 mm specimen dimensions. It is not the default domain for
every experiment. Relative density remains derived. The mass denominator is
slicer-reported, not a balance measurement. The 50% boundary corresponds to
15 mm **for this geometry**, not a hardcoded platform travel limit.

## Limitations and Known Gaps

Completed observations coexist with diagnostic failures and recoveries. The
summary preserves `curve_quality` warnings, including boundary-peak warnings;
these are not erased or converted into a new scientific-validity verdict.
No controlled baseline, statistical superiority, unattended reliability,
independent material certification or per-cycle physical fabrication audit is
claimed. Fifteen accepted observations do not mean fifteen independent campaigns
or 100% first-attempt robot success. Earlier mixed-mode demonstrations retain
their own scope; their skipped printing or specimen substitutions are not
automatically attributed to this later campaign.

## Verification

The read-only protocol above was executed on 2026-09-28. All 15 required
iteration sets were present. The public summary is content-hashed in the paper
artifact manifest; private source files were read, not modified.

## Related Documents

- [Analysis definition](../../agents/analysis_agent.md)
- [BO owner](../../agents/bo_agent.md)
- [Claim-evidence map](../09_claim_evidence_traceability.md)
