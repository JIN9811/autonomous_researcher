---
{"topic_id":"specimen-role","owner":"specimen_agent","source_refs":["docs/agents/specimen_agent.md"],"source_revision":{"docs/agents/specimen_agent.md":"272c0ce57347517af23eb2eaac0a4bc24a67b8943859a952f748e3ddf5622c68"},"verified_at":"2026-09-14T00:00:00+00:00","applicability":"Public Specimen Making Agent responsibilities and handoff","status":"reviewed"}
---

# Specimen Making Agent

Specimen evaluates fabrication suitability for the Design contract and selects an existing bounded fabrication tool. The code validates intent, geometry, mesh, dimensions and manufacturability, then prepares slicing and the selected printer handoff. Source, sliced, patched, published, started, completed, ejected and Vision-confirmed states are distinct. Printer protocols and motion stay bridge-owned. The output specimen_fabricated.v1 feeds Vision and Manipulation.

Source: [Specimen Making Agent reference](../../agents/specimen_agent.md).
