---
doc_type: evidence
subtype: test_report
status: active
authority: evidentiary
audience: [researcher, reviewer, operator]
scope: [supervised_closed_loop, live_equipment, feedback_handoff]
summary: One supervised mixed-mode ATR iteration reached UTM clearance, analysis, BO-managed LHS feedback, and the next design.
evidence_date: 2026-09-07
method: Read-only observation of the operator-started live run, event timestamps, archived agent results, and SHA-256 checks.
related_docs:
  - docs/paper/06_evaluation_and_results.md
  - docs/paper/09_claim_evidence_traceability.md
  - docs/runtime/loop_artifact_archiving.md
  - docs/agents/equipment_agent.md
supersedes: []
---

# Supervised Closed-Loop Integration Evidence

## Summary

Autonomous Researcher Framework (ATR) completed one observed feedback iteration
in a supervised, mixed-mode run: printer ejection test, transfer/placement
verification, live Equipment Skill Flow, specimen disposal, empty-UTM
verification, Analysis, Knowledge, BO-managed initial-design selection,
Guardian, and the next Design/Specimen entry.

`E-LIVE-LOOP-001` supports `C-SYS-LOOP-01` only within this integration scope.
It is not a full physical manufacturing campaign or a material-performance
result. The operator reported substituting a specimen; specimen-to-curve
scientific identity is therefore not established by this run.

## Scope and Environment

- Run: `run-20260906T154601Z-95cb07`.
- Observation date: 2026-09-07 KST; timestamps below use UTC on 2026-09-06.
- Runtime: existing Live GUI loop, Python 3.12, working-tree changes on base
  commit `c4005ca`; not a clean-commit reproducibility measurement.
- Outer mode: `test`, with the real-printer **ejection-only** path
  (`TEST_PRINTER_EJECTION_PROJECT_STARTED`) and live Equipment worker results.
  This does not claim new specimen deposition or cooling was performed.
- Disposal used a managed recorded robot motion on physical hardware. It is
  live actuation, not a non-actuating replay evidence class.
- One observed completed feedback iteration; no reliability denominator across
  independent runs, no comparative baseline, no safety-effectiveness estimate.
- The run entered its second iteration. Whole-run termination and completion
  of the second physical cycle are outside this record.

## Evidence Basis

The checked-in [result index](2026-09-07-closed-loop-summary.json) records the
archived result statuses, summaries, repository-relative local archive paths,
and SHA-256 digests. It includes the separate Manipulation disposal result and
Vision clearance result: a successful disposal call alone is not clearance.

Raw CSV files, images, robot streams, and full runtime payloads remain in the
local loop archive and are **not bundled with this public record**. The index
is an audit pointer, not a substitute for those bytes or an independently
replayable dataset. Raw payloads were not copied into Git because they include
device configuration and large operational artifacts.

## Observed Sequence

| UTC time | Boundary | Observed result | Evidence scope |
|---|---|---|---|
| 15:48:21 | Printer test → ActiveCam | Ejection verification completed | Ejection-only test, not new manufacturing |
| 15:50:54 | Transfer → Verification 1 | UTM placement confirmed; rollout stopped | Placement/control evidence |
| 15:52:24 | Equipment completion | Eight Skill Flow blocks completed; CSV pulled to Linux | Live worker and file handoff |
| 15:53:10 | Disposal → Verification 2 | Fresh empty-fixture result `clear` | Placement and clearance are distinct records |
| 15:53:30 | Analysis | `UTM analysis complete`; BO handoff available | Data processing completed, not material validation |
| 15:54:02 | Knowledge | Evidence/memory update completed | Agent result, not demonstrated scientific benefit |
| 15:54:30 | BO | `bo-candidate-002` selected | LHS initialization point 2/8 |
| 15:54:49 | Guardian → Design | Continue decision and transition | This boundary passed, not general safety efficacy |
| 15:55:17 | Design → Specimen | Next design selected and handed off | One feedback iteration closed |

Equipment blocks were `prepare_next_specimen`, `start_test`,
`monitor_contact_and_run`, `await_auto_return`, `save_raw_data`,
`validate_raw_data`, `advance_without_save`, and `restore_robot_clearance`.
The GUI progress defect discovered during observation did not prevent these
persisted execution transitions.

This was not an error-free observation: optional, non-blocking Equipment
Vision observers recorded `error` for preparation, test start, and clearance
restoration. Those failures remain visible and were not rewritten as successes.
They are distinct from the mandatory post-disposal Verification 2, whose
archived result is `clear`, `confirmed: true`. Successful loop progression
does not establish that every optional observer worked.

## Feedback Data and Next Design

The Analysis handoff recorded `energy_density_50pct_MJ_per_m3`, unit `MJ/m3`,
direction `maximize`, score `1.275e-06`. This is a transported pipeline value,
**not a publishable material measurement** for the designed specimen. The
quality result allowed BO but retained `peak_at_curve_boundary`; no claim of a
clean, correctly identified compression experiment follows from that gate.

Although the BO result summary says `via bo`, its request rationale explicitly
says LHS initial-design point **2/8**, with acquisition ranking inactive.
The next Design result preserves these requested parameters:

| Parameter | BO request | Next Design | Unit / interpretation |
|---|---|---|---|
| Cell size | 5.0 | 5.0 | mm |
| Wall thickness | 1.2 | 1.2 | mm |
| Relative density | 0.34359751696606483 | 0.3436 | Dimensionless, rounded design output |
| TPMS thickness | 0.38 | 0.38 in constraints | Generator parameter |

The Design agent assigned its own candidate ID, `cand-2-12`; it did not retain
the BO candidate ID verbatim. The parameter handoff, not identifier equality,
is the verified feedback boundary.

## Verification and Reproduction Boundary

Observation used read-only planning-session, run-events, and equipment-flow
GET endpoints plus local archived `result.json` files. No stop, restart,
resume, equipment command, or Guardian override was sent during this audit.

From repository root, verify local originals when the private run archive is
available (this only reads files):

```bash
.venv/bin/python - <<'PY'
import hashlib, json
from pathlib import Path
index = json.loads(Path('docs/paper/evidence/2026-09-07-closed-loop-summary.json').read_text())
for record in index['records']:
    path = Path(record['source_path'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'], path
print('11 archived result hashes verified')
PY
```

This command intentionally cannot reproduce raw evidence in a clean public
checkout without the separately retained archive. Public document/manifest
integrity is checked by `scripts/validate_documentation.py` and
`scripts/validate_paper_publication.py`.

## Limitations and Known Gaps

No claim is made for full fabrication, specimen identity/geometry matching,
mechanical accuracy, CAE agreement, acquisition-based BO improvement,
unattended operation, recovery robustness, or campaign-level safety. Earlier
failed runs remain separate evidence and were not converted into successes.
The UI refresh/color fixes were tested separately after this live iteration;
this record does not retrospectively claim the updated GUI ran during it.

## Related Documents

- [Evaluation and Results](../06_evaluation_and_results.md)
- [Claim-Evidence Traceability](../09_claim_evidence_traceability.md)
- [Lab Equipment Agent](../../agents/equipment_agent.md)
- [Loop Artifact Archiving](../../runtime/loop_artifact_archiving.md)
