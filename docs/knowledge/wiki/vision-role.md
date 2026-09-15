---
{"topic_id":"vision-role","owner":"vision_agent","source_refs":["docs/agents/vision_agent.md"],"source_revision":{"docs/agents/vision_agent.md":"4bcba27369ea9a3062679b959aba80700d3658499e2abd675da464643a1286d6"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: vision-role","status":"reviewed"}
---

# Vision Agent — Observation, Placement and Clearance

Vision (VIS) combines deterministic detection with bounded LLM review of same-capture original/annotated images. Missing detections alone cannot establish task success or an empty platen.

| Inspection | Evidence sought |
|---|---|
| Pickup / ActiveCam | Requested observation and task evidence |
| Initial placement | Specimen inside the green Live Observation ROI |
| Post-test removal | Residue within the platen ROI after removal and home return |

Initial placement reads the monitor's active ROI. Missing/invalid ROI does not permit full-frame fallback. Removal uses a broad platen ROI from the fixed camera profile, aggregates small red remnants and does not require green-marker registration. The model cannot arbitrarily change ROI or thresholds.

## Time and provenance

Handoff observations remain valid for 180 seconds from original observation time in both LIVE and TEST. Separate safety signals—workspace safety, anomalies and UTM motion—retain a five-second limit. A late model response does not refresh the capture timestamp.

A current view, another run's photo and an archived image are different evidence. Camera failures, occlusion, wrong viewpoints and signal loss remain unknown or require review.

## Clearance and progression

Completed removal replay, measured home return and current observation must agree before normal Analysis handoff. User-requested historical revalidation describes the stored scene only; it does not replace current safety clearance.

[Vision reference](../../agents/vision_agent.md), [Manipulation role](manipulation-role.md), [recovery boundaries](recovery.md).
