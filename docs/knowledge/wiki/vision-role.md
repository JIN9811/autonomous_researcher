---
{"topic_id":"vision-role","owner":"vision_agent","source_refs":["docs/agents/vision_agent.md"],"source_revision":{"docs/agents/vision_agent.md":"4bcba27369ea9a3062679b959aba80700d3658499e2abd675da464643a1286d6"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: vision-role","status":"reviewed"}
---

# Vision Agent — Observation, Placement and Clearance

## Runtime decision reference

Vision reviews the supplied inspection contract and current same-capture evidence. Code owns configured ROI, coordinate validation, identity, freshness and detector gates. Interpret the observed scene without importing reference thresholds, expected appearance, checks for other inspection phases or prior images as current evidence.

## Overview

Vision (VIS) combines deterministic detection with bounded LLM review of same-capture original/annotated images. Missing detections alone cannot establish task success or an empty platen.

| Inspection | Evidence sought |
|---|---|
| Pickup / ActiveCam | Requested observation and task evidence |
| Initial placement | Specimen inside the fixed platen ROI shared with Verification 2 |
| Post-test removal | Residue within the platen ROI after removal and home return |

Placement and removal share the fixed platen ROI `[200, 240, 400, 420]` in the 640 × 480 camera view. Placement does not use the monitor's full-height ROI or accept caller overrides. Removal aggregates small red remnants and does not require green-marker registration. Presence and clearance retain separate success criteria; neither the model nor the caller can widen the ROI.

## Time and provenance

Handoff observations and separate workspace/UTM safety signals have different code-owned validity limits. Read the active contract and runtime freshness result; this page does not supply a timeout. A late model response does not refresh the capture timestamp.

A current view, another run's photo and an archived image are different evidence. Camera failures, occlusion, wrong viewpoints and signal loss remain unknown or require review.

## Clearance and progression

Completed removal replay, measured home return and current observation must agree before normal Analysis handoff. User-requested historical revalidation describes the stored scene only; it does not replace current safety clearance.

[Vision reference](../../agents/vision_agent.md), [Manipulation role](manipulation-role.md), [recovery boundaries](recovery.md).
