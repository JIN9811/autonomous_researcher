# Measurement-only Analysis and retired computation services

> Execute in the current working tree, preserving existing unrelated changes. Use the executing-plans and test-driven-development workflows. Do not operate hardware or commit without a new request.

**Goal:** Retain experimental postprocessing, quantitative metrics, LLM evidence decisions and BO delivery; retire FEM/CAE and Self-Evolution from active functionality.

**Approved scope:** The user requested archiving code, documents and prior illustrations in `oldversion`, not deleting historical evidence. Knowledge ingestion, RAG and memory remain active. Regenerate Analysis documentation SVG and representative illustration.

**Architecture:** Preserve the existing Analysis task/deliver graph and numerical observation contracts. Remove computation and model-improvement branches rather than replacing them with successful stubs. Archive dedicated retired modules; archive pre-change copies of shared files before removing only retired sections.

## Verification and execution checklist

- [x] Add regression tests: measured data produces metrics and BO observation without simulation decisions, tools or background jobs; invalid data remains blocked.
- [x] Preserve retired implementations and mixed-file snapshots under `oldversion/2026-09-14-retired-computation/`, mirroring repository paths and documenting restoration boundaries.
- [x] Remove Analysis simulation selection, solver invocation, model pinning, background submission and simulation-only output artifacts. Preserve data-processing and validation LLM calls, CSV parsing, geometry normalization and objective binding.
- [x] Remove CAE and Self-Evolution registrations, lifecycle hooks, routes, package dependencies and UI entrypoints. Keep Knowledge evidence storage and retrieval independent of retired services.
- [x] Update Analysis owner descriptor, execution graph labels, implementation structure, report projection, Live GUI and IDE. Historical reports must not reintroduce retired panels.
- [x] Update active user-facing documentation, links, diagrams and representative image. Archive superseded dedicated documentation and figures; do not mislabel old evidence as a new verification.
- [ ] Run targeted Python and JS tests, module discovery/API import tests and no-hardware cycle validation; inspect rendered UI and updated figures. Record limitations accurately.

## Acceptance examples

```python
assert [d['phase'] for d in result.data['analysis']['decisions']] == ['data_processing', 'data_validation']
assert result.data['bo_observation']
assert not any(k in result.data['analysis'] for k in ('fem_job', 'improvement', 'model_pin'))
```

All historical run directories remain untouched. No solver, robot, printer or test-machine invocation is permitted during verification.

## Verification update — 2026-09-14

Implemented measurement-only owner and retired service registration, routes and
panels. Dedicated implementations and prior figures are archived under the path
above; shared historical evidence/proposal contracts remain readable.

- Guarded mode/cycle suite: 44 passed, including next Design and mixed-mode handoffs.
- Analysis/core-plan focused suite: 96 passed; controlled model responses, no hardware.
- Frontend module lifecycle/rendering: 2 passed; JavaScript syntax checked.
- Fresh-app OpenAPI rejects retired computation routes; `/cae` returns 404.
- Wider legacy UI tests retain unrelated Equipment expectations; Windows bridge
  documentation does not satisfy the older full-reference validator template.
- Updated representative image inspected; document SVGs regenerated from current sources.
- The running servers were not restarted and no new live-browser backend verification
  or registered API/local-model benchmark is claimed for this revision.
