---
doc_type: evidence
subtype: audit
status: active
authority: evidentiary
audience:
  - researcher
  - reviewer
  - artifact_evaluator
scope:
  - paper
  - architecture_inspection
summary: Records the initial paper-scoped route and graph structure inspection.
evidence_date: 2026-08-09
method: Imported FastAPI route inspection and direct YAML graph parsing at the recorded code baseline.
related_docs:
  - docs/paper/02_system_architecture.md
  - docs/runtime/current_code_snapshot.md
supersedes: []
---

# Architecture Inspection Evidence

## Summary

Evidence ID `E-INSPECT-ARCH-001` records the bounded architecture counts used
by the paper package.

## Environment

- Evidence class: `inspection`
- Date: 2026-08-09
- Code baseline: `0b7627b`
- Working directory: repository root
- Python: repository `.venv`

Documentation-only commits after the code baseline do not change the measured
application or graph sources.

## Commands

FastAPI route inspection:

```bash
.venv/bin/python -c 'from fastapi.routing import APIRoute; from app.main import app; print(f"api_routes={sum(isinstance(route, APIRoute) for route in app.routes)}"); print(f"app_routes={len(app.routes)}")'
```

Graph configuration inspection:

```bash
.venv/bin/python -c 'from pathlib import Path; import yaml; graph=yaml.safe_load(Path("graphs/configs/atr_closed_loop.yaml").read_text())["graph"]; print("graph_nodes=%d" % len(graph["nodes"])); print("graph_edges=%d" % len(graph["edges"])); print("stage_dispatch_edges=%d" % len(graph["stage_dispatch"]))'
```

## Observed Output

```text
api_routes=346
app_routes=353
graph_nodes=19
graph_edges=68
stage_dispatch_edges=12
```

Importing the application also emitted five Pydantic warnings about fields
named `schema` shadowing parent attributes. Those warnings do not change the
route count and are retained as an observation rather than hidden.

## Result

`pass` for the bounded proposition that the recorded route and graph entries
exist at baseline `0b7627b` and match the governed current snapshot.

## Interpretation Boundary

This record does not execute a research cycle, validate route behavior, prove
checkpoint recovery, measure safety effectiveness, establish scientific
outcomes, or certify optional backends and devices.

## Related Documents

- [System architecture](../02_system_architecture.md)
- [Current code snapshot](../../runtime/current_code_snapshot.md)
