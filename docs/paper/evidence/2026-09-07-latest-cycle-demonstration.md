---
doc_type: evidence
subtype: test_report
status: active
authority: evidentiary
audience: [researcher, reviewer, operator]
scope: [supervised_closed_loop, live_equipment, feedback_handoff]
summary: Records completion of one supervised integration cycle with measured compression data and entry into the next design.
evidence_date: 2026-09-07
method: Read-only audit of the latest operator-run cycle, loop-scoped results, event timestamps, CSV provenance, and SHA-256 digests.
related_docs:
  - docs/paper/06_evaluation_and_results.md
  - docs/paper/09_claim_evidence_traceability.md
  - docs/paper/evidence/2026-09-07-supervised-closed-loop.md
  - docs/runtime/loop_artifact_archiving.md
supersedes: []
---

# Latest Run: One-Cycle Integration Demonstration Completed

## Summary

Autonomous Researcher Framework (ATR) completed one supervised closed-loop
integration cycle in `run-20260907T043145Z-f6152b`. The operator reported that
the cycle completed without an interruption. Archived results independently
show progression through specimen preparation, vision, manipulation, live
compression testing, disposal and clearance verification, Analysis, Knowledge,
BO feedback, Guardian continuation, and the next Design/Specimen stage.

**Demonstration status: completed for one integration cycle.** Evidence
`E-LIVE-LOOP-002` supports `C-SYS-LOOP-01`. This is not a claim that an entire
campaign finished, every optional observer succeeded, or full fabrication and
scientific efficacy were validated.

## Scope and Environment

- Run: `run-20260907T043145Z-f6152b`; first archived loop `loop-000001`.
- Date: 2026-09-07; the timeline uses UTC (KST = UTC + 9 hours).
- Repository HEAD at audit: `39958d823caf48d35f449aceef2e6b54918df82c`.
  The live process and working-tree code were not immutably fingerprinted at
  execution time. This is operational evidence, not clean-commit reproduction.
- Printer mode: `test`, installed-printer ejection-only route, with
  `TEST_PRINTER_EJECTION_PROJECT_STARTED`. New specimen deposition was skipped.
- Equipment and manipulation reported `live` mode; manipulation was not
  virtualized. Recorded disposal motion actuated hardware and is therefore
  live evidence, not non-actuating replay evidence.
- Denominator: one completed feedback cycle in this selected run. The next
  cycle's Design and Specimen results establish continuation, not completion
  of a second cycle or a repeated-run reliability estimate.

## Evidence Basis

The [public result/hash index](2026-09-07-latest-cycle-summary.json) identifies
14 stage-result records and five data artifacts, including the raw CSV,
canonical curve, parse report, quality report, and metrics. SHA-256 digests
were checked against the local originals. Raw device payloads, images, and
robot streams remain local; they are not published by this documentation-only
change. Hash pointers do not make the public package independently replayable.

The earlier `E-LIVE-LOOP-001` record remains unchanged. Its specimen
substitution and near-zero transported objective are not attributed to this
new run.

## Observed Sequence

| UTC time | Boundary | Recorded result / evidence scope |
|---|---|---|
| 05:06:38 | Design | First specimen design selected |
| 05:07:18 | Specimen | Preparation result completed; installed-printer ejection-only project started |
| 05:08:31 | ActiveCam / Vision | Perception result available for transfer |
| 05:08:51 | Manipulation | Live policy launched; placement verification still pending at this boundary |
| 05:10:56 | Verification 1 | Placement detected; rollout stop result `STOPPED`; handoff ready |
| 05:12:25 | Equipment | Eight Skill blocks completed; live result `verified_complete`; CSV handoff eligible |
| 05:12:33 | Manipulation disposal | Disposal started; clearance verification pending |
| 05:13:12 | Verification 2 | Disposal state `done`, success true, home verified; fresh image confirms fixture `clear` |
| 05:13:31 | Analysis | Measured CSV parsed, quality gate passed, BO observation ready |
| 05:14:05 | Knowledge | Memory, pattern ledger, and evidence update completed |
| 05:14:37 | BO | Next initial-design point selected; request ready |
| 05:14:56 | Guardian | `continue` decision |
| 05:15:16 | Next Design | Requested parameters incorporated into the next specimen design |
| 05:16:22 | Next Specimen | Preparation result completed, confirming feedback-loop re-entry |

Times are persisted agent-result event times, not independent physical motion
duration measurements. In particular, the first Manipulation result is not
used as proof of completed transfer: the subsequent Vision result supplies
placement confirmation and rollout termination. Disposal completion likewise
requires the later clearance result rather than the initial pending record.

## Measured Data and Feedback

| Quantity | Recorded value | Unit / interpretation |
|---|---|---|
| Parsed numeric samples | 2,113 | Rows from one raw equipment CSV; zero invalid numeric rows |
| Recorded displacement interval | 0 to 20.99998 | mm; obtained from the file |
| Analysis quality | `ok_for_metrics: true`, `ok_for_bo: true` | Score 1.0; no quality warnings |
| Peak load in the configured evaluation interval | 6,385.264 | N; archived limit 15 mm was reached |
| Evaluation energy | 52,420.871477 | mJ; archived metric `energy_absorption_50pct_mJ` |
| BO objective | 1.941513759 | MJ/m³; `energy_density_50pct_MJ_per_m3`, maximize |
| Next BO point | 2/8 | LHS initialization; acquisition ranking inactive |

These values describe this recorded experiment configuration, not universal
platform constants. The raw CSV hash matches the parser's source fingerprint.
Equipment handoff identity, data parsing, and Analysis quality checks passed.
This establishes measured-data transport and processing; it does not by itself
certify the physical specimen's correspondence to the generated geometry,
instrument calibration, CAE agreement, or material performance.

| Feedback parameter | BO request | Next Design | Unit |
|---|---|---|---|
| Cell size | 5.0 | 5.0 | mm |
| Wall thickness | 1.2 | 1.2 | mm |
| Relative density | 0.34359751696606483 | 0.3436 | Dimensionless; rounded design field |
| TPMS thickness | 0.38 | 0.38 in constraints | Generator parameter |

The BO summary's `via bo` wording does not establish acquisition optimization:
the request explicitly identifies LHS initial-design point 2/8. The next Design
uses its own candidate identifier; matching parameters establish the handoff.

## Non-blocking Findings and Limitations

The mandatory integration path completed, but the archive is not error-free.
Three optional Equipment vision observers (preparation, test start, and
clearance restoration) recorded `EQUIPMENT_VISION_LINK_UNAVAILABLE`;
five other Equipment vision phases were configured as bypasses. All eight
Skill execution blocks completed. These optional observations are distinct
from mandatory Verification 1 and Verification 2, which reached their required
outcomes. Pending Vision polls and Guardian warning incidents are retained.
A BO reasoning warning records deterministic reasoning after a non-JSON model
response; it does not change the request's explicit LHS initialization status.

No claim is made for warning-free operation, new specimen printing, unattended
autonomy, campaign completion, acquisition-based improvement, recovery
robustness, or general safety effectiveness. This audit did not rerun, stop,
resume, or otherwise command any equipment, and it did not modify runtime code.

## Verification

From repository root, with the separately retained local archive available:

```bash
.venv/bin/python - <<'PY'
import hashlib, json
from pathlib import Path
index = json.loads(Path('docs/paper/evidence/2026-09-07-latest-cycle-summary.json').read_text())
for record in index['records']:
    path = Path(record['source_path'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256'], path
print(f"{len(index['records'])} archived artifact hashes verified")
PY
```

Public package checks, which require no hardware or private archive:

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python scripts/validate_paper_publication.py
.venv/bin/python -m pytest -q tests/unit/test_documentation_validation.py tests/unit/test_paper_publication_validation.py
```

Documentation audit outcome: 19 local artifact hashes verified; 40 focused
documentation tests passed; paper publication validation passed. All changed
Markdown documents passed individual validation. The full general documentation
validator still reports 27 pre-existing findings in two unchanged files:
`docs/device_bridges/windows_pyautogui_bridge.md` and
`docs/superpowers/specs/2026-08-24-plc-safety-bridge-design.md`. Both files were
verified byte-identical to HEAD; these unrelated format defects were not
modified or reported as passing by this evidence update.

## Related Documents

- [Evaluation and Results](../06_evaluation_and_results.md)
- [Claim-Evidence Traceability](../09_claim_evidence_traceability.md)
- [Earlier integration record](2026-09-07-supervised-closed-loop.md)
- [Loop Artifact Archiving](../../runtime/loop_artifact_archiving.md)
