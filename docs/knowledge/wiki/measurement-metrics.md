---
{"topic_id":"measurement-metrics","owner":"documentation","source_refs":["docs/agents/analysis_agent.md"],"source_revision":{"docs/agents/analysis_agent.md":"dd1427c585819820ad7a410301f0b69fb54057cd93b37f05ef5e58f2120bfd96"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: measurement-metrics","status":"reviewed"}
---

# Measurement Metrics — SS, FD and Energy

Analysis curves and objectives interpret the same measurements using different units and normalization. Check initial geometry, evaluation interval and provenance, not just plot names.

| Metric | Definition |
|---|---|
| FD: Force–Displacement | Measured force F versus displacement δ |
| SS: Stress–Strain | Engineering stress σ = F / A₀ and strain ε = δ / L₀ |
| Absorbed Energy | Force–displacement integral over the interval |
| Energy Density | Stress–strain integral over the interval |
| SEA | Energy normalized by mass; requires mass and objective definition |

A₀ is initial cross-sectional area; L₀ is initial gauge length. Energy, energy density and SEA have distinct units and normalizations. Energy density up to 50% strain is not peak load over the complete recording. The run-bound objective determines the evaluated quantity.

## Preview versus original

SS and FD share the same canonical preview samples. At most 200 extrema-preserving samples are used for display without overwriting the original CSV. Restoring the full run preview checks the original CSV SHA-256.

Zero remains the recording-start reference. Contact estimation is a separate diagnostic, not a silent zero shift. Distinguish corrections made in the test method from postprocessing conventions.

## Warnings and validity

An endpoint maximum does not establish a failure peak outside measured coverage. It also does not automatically invalidate energy over a sufficiently measured fixed interval. Inadequate objective coverage, incorrect units or geometry can block a valid BO observation.

Read Objective identity, direction, units and interval alongside Measured Response, Key Metrics, Data Quality and BO Handoff.

[Analysis reference](../../agents/analysis_agent.md), [BO plots](bo-visualization.md).
