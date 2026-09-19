# Agent evidence preservation

Every agent invocation owns an immutable run, zero-based loop, attempt, and
execution ID. The common archive retains inputs, outputs, decisions/handoffs,
tool events and referenced evidence. Read-only derived outputs are stored in
that same attempt's `preserved/` directory, never attributed from the current UI
cycle or from a BO iteration number.

| Owner | Evidence retained |
| --- | --- |
| Orchestrator | Contract, routing plan, decisions, handoffs, input and events |
| Design | All candidate records, constraints, evaluations, CAD/previews, design-space figure |
| Specimen | Mesh checks, STL, sliced artifact, print settings/results, mass and timing evidence |
| Vision | Raw/annotated images, ROI/detection results, decisions and signal evidence |
| Manipulation | Session identity, action log, measured/target values, tracking plots and summaries |
| Equipment | Workflow steps, screen evidence, method values, exported raw CSV and completion evidence |
| Analysis | Archived canonical CSV, FD/SS figures, metrics, normalization, quality and BO handoff |
| Knowledge | Retrieval scope, citations, immutable note revisions, receipts and knowledge report |
| BO | Saved LHS/GP visualization payload, PNG/SVG/CSV, observations, candidates and acquisition |
| Guardian | Gate decisions, incidents, recovery advice and supporting evidence |

`evidence_index.json` records source hashes, retained components, generated files
and known gaps. `artifact_coverage.json` summarizes coverage for every owner.
An interrupted/running invocation is not declared complete. Unknown or missing
historical data is not synthesized. In particular, a current `/tmp/latest` image
must never replace an old cycle's missing image. New live captures may snapshot
the explicit camera evidence directories through the existing archive.

Plot export uses saved numbers only: no agent invocation, model fitting, metric
recalculation, verification retry or device action. It runs in one separate
background process. Failures cannot change the experiment result. Existing runs
can be backfilled with `python -m utils.artifact_preservation runs/<run_id>`.
Original manifests and results are not overwritten. Repeating backfill is
idempotent; a changed execution manifest triggers a new inspection.

The Live GUI artifact view defaults to all recorded cycles for the selected
agent. Users can still select a particular cycle, or All files for unclassified
legacy evidence. PNG/SVG plots remain ordinary downloadable files.
