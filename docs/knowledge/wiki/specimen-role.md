---
{"topic_id":"specimen-role","owner":"specimen_agent","source_refs":["docs/agents/specimen_agent.md"],"source_revision":{"docs/agents/specimen_agent.md":"8073f3b51afbf3ed69b4deed29ae6aee4b08b2a1e3c4a77f97f29507b4c4027a"},"verified_at":"2026-09-13T00:00:00+00:00","applicability":"Public Specimen Making Agent responsibilities and handoff","status":"reviewed"}
---

# Specimen Making Agent

Specimen evaluates fabrication suitability for the Design contract and selects an existing bounded fabrication tool. The code validates intent, geometry, mesh, dimensions and manufacturability, then prepares slicing and the selected printer handoff. Source, sliced, patched, published, started, completed, ejected and Vision-confirmed states are distinct. Printer protocols and motion stay bridge-owned. The output specimen_fabricated.v1 feeds Vision and Manipulation.

Source: [Specimen Making Agent reference](../../agents/specimen_agent.md).
