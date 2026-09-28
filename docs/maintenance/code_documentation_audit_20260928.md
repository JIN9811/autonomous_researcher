<!-- atr-doc
doc_type: evidence
subtype: audit
status: active
authority: evidentiary
audience: [developer, maintainer, operator, researcher]
scope: [documentation, current_implementation, verification_boundaries]
summary: Reconciliation of current documentation with the main code, retained campaign and isolated report-module work.
evidence_date: 2026-09-28
method: Static code/configuration inspection, read-only archive audit and scoped automated regressions.
related_docs:
  - docs/runtime/current_code_snapshot.md
  - docs/paper/evidence/2026-09-28-campaign-archive-audit.md
  - docs/README.md
supersedes: []
-->

# Code/documentation reconciliation — 2026-09-28

## Scope

Main implementation baseline: `e70daa1`. This maintenance updates documentation,
not executable agent logic, configuration, installed profiles, devices or running services.
The corrected runtime-guideline text may be retrieved as model context on a
future request; it explicitly defers to current contracts and owner evidence.
Historical plans and dated evidence remain history, not current instructions.
The separate `feature/report-agent` worktree (baseline `8968eb4` plus uncommitted
RPT changes) is not merged or deployed by this documentation update.

## Current Contract Map

| Area | Current implementation and authoritative reference | Verification boundary |
|---|---|---|
| Design / Gyroid | `agents/design/agent.py`: continuous cell size and wall thickness, `wall_cell_v1`; [Design](../agents/design_agent.md) | Default domains 5–10 mm and 0.6–1.2 mm; a campaign may override them; density is derived |
| Specimen / printer | Existing selected-provider prepare/upload/start path; [Bambu](../device_bridges/bambu_x2d_bridge.md), [test modes](../runtime/test_mode.md) | Installed-printer ejection-only and full physical printing are distinct; a successful API response alone is not print completion |
| Print profile | One XYZ speed-scale input, storage key `xy_speed_scale_percent`; independent prime and early-layer/Z toggles | Existing profile/speed-scale tests; user-saved settings are not universal defaults |
| Vision | Active Cam and UTM ROI captures; cycle-scoped ROS reload; [Vision](../agents/vision_agent.md) | Fresh identity-bound images and review remain required; preview receipt is not acceptance |
| Manipulation | Existing policy/replay paths, optional output linear interpolation; [LeRobot](../device_bridges/lerobot_bridge.md), [MAN](../agents/manipulation_agent.md) | GUI and bridge options share configuration; no implicit timeout homing or post-motion blind retry |
| Equipment | Owner-selected stacked Flow and Windows/Local worker; [EQP](../agents/equipment_agent.md) | Actual deployed Flow and required acquisition evidence determine completion |
| Analysis | [Measured curves and metrics](../agents/analysis_agent.md) | SEA uses energy to 50% of initial specimen height and selected slicer mass; mass is an estimate, not a balance result |
| BO | `learning/botorch_backend.py`, [BO](../agents/bo_agent.md) | LHS then normalized SingleTaskGP/acquisition; 2D triptych/3D surfaces; final-report path at approved experiment count |
| Knowledge | [Wiki/private memory](../knowledge/wiki_memory.md), [reference safety](../knowledge/runtime_reference_safety.md) | Retrieved prose is context, never current device state or permission; delivery and use are different evidence |
| Guardian / Resume | [Resume routing](../gui/run_resume.md), [Guardian](../agents/guardian_agent.md) | Matching recovery evidence can resolve prior failure; unresolved current safety gates still apply |
| GUI / workers | [Monitoring](../gui/monitoring_workers.md), [compute](../gui/compute_workers.md), [read path](../gui/read_path_performance.md) | Process separation is not guaranteed CPU pinning; printer target FPS is not measured source FPS |
| Replay / artifacts | [Read-only replay](../gui/run_replay.md), [preservation](../gui/artifact_preservation.md) | Historical views do not re-execute equipment; absent past evidence is not synthesized |
| Modularity | [Module/package contracts](../modularity.md), [Runtime IDE](../runtime/runtime_ide.md) | Management selection, package membership, graph attachment and run activation remain distinct |
| RPT development | Isolated `feature/report-agent`: `agents/report/`, `docs/agents/report_agent.md`, `docs/runtime/module_blueprint.md` | Implemented PDF/DOCX and API/local-model writing with recorded tests/exports; not a main-loop stage or a production deployment; prose-quality warnings remain in its verification record |

## Current Inventory

Imported main-branch FastAPI application: **420 APIRoute entries**, **430 total
routes**. Primary checked-in graph: **19 nodes**, **73 edges**, **12 stage-dispatch
entries**. These are configuration counts, not a speed or reliability result.
The controller factory was replaced by a mock for the import; ASGI startup was
not run. Reproduce without starting the operating server:

```bash
.venv/bin/python - <<'PY'
from unittest.mock import MagicMock, patch
from fastapi.routing import APIRoute
import yaml
with patch('app.bootstrap.load_runtime', return_value=MagicMock()):
    from app.main import app
print(sum(isinstance(r, APIRoute) for r in app.routes), len(app.routes))
with open('graphs/configs/atr_closed_loop.yaml') as f:
    graph = yaml.safe_load(f)['graph']
print(len(graph['nodes']), len(graph['edges']), len(graph['stage_dispatch']))
PY
```

## Campaign Evidence

The [new archive audit](../paper/evidence/2026-09-28-campaign-archive-audit.md)
checks 15 accepted observation sets and retains failed/cancelled attempts.
It supersedes the *current inventory claim* that only one cycle is available;
it does not rewrite the earlier one-cycle reports or establish unattended
manufacturing, comparative scientific benefit or hazard coverage.

## Verification

The final no-device selection passed **212 tests**, with six warnings:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_paper_publication_validation.py \
  tests/unit/test_bo_budget_recovery.py \
  tests/unit/test_equipment_entry_resume.py \
  tests/unit/test_guardian_retry_completion.py \
  tests/unit/test_linear_interpolation_options.py \
  tests/unit/test_bambu_xy_speed_scale.py \
  tests/unit/test_vision_ros_cycle_reload.py \
  tests/unit/test_runtime_wiki_safety.py --disable-warnings --tb=short
```

Documentation validation and public-evidence/hash validation both passed.
Local-link checks passed for all 131 Markdown files under `docs/`, excluding
historical `oldversion` and `superpowers` plans. All 47 Wiki source-revision
references match their current files; 17 affected Wiki pages were refreshed.
`git diff --check` passed. These structural checks supplement the domain review;
they do not certify every historical statement or every runtime behavior.
No full-suite, fresh browser, new physical experiment or RPT prose-parity claim
follows from this scoped selection.

## Remaining Boundaries

Genuine unsupported scope remains explicit: safety efficacy, cross-laboratory
reliability, comparison against a controlled baseline, measurement-error
estimation and scientific certification. A stale "not implemented" sentence is
removed only where code contradicts it; a dated test's "no hardware calls"
statement remains a true description of that test.
