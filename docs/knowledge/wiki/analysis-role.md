---
{"topic_id":"analysis-role","owner":"analysis_agent","source_refs":["docs/agents/analysis_agent.md"],"source_revision":{"docs/agents/analysis_agent.md":"7f1c46280f979b2bffa18d8a922e60747a08fa1c2cf8832f5730fbfdd4fb7348"},"verified_at":"2026-09-13T00:00:00+00:00","applicability":"Public Analysis Agent responsibilities and handoff","status":"reviewed"}
---

# Analysis Agent

Analysis validates and processes measured data and produces objective evidence for Knowledge and BO. Numerical parsing, metrics and objective computation remain code-owned. Background FEM runs independently of the measured handoff; bounded LLM roles assess measurement admissibility, simulation actions and candidate promotion. Existing CAE preparation, solvers and field postprocessing remain numerical tools. A model explanation cannot overwrite a measurement or declare a new physical validation.

Source: [Analysis Agent reference](../../agents/analysis_agent.md).
