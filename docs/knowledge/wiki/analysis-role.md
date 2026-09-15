---
{"topic_id":"analysis-role","owner":"analysis_agent","source_refs":["docs/agents/analysis_agent.md"],"source_revision":{"docs/agents/analysis_agent.md":"dd1427c585819820ad7a410301f0b69fb54057cd93b37f05ef5e58f2120bfd96"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: analysis-role","status":"reviewed"}
---

# Analysis Agent — Measurements and Objectives

Analysis (ANL) converts measurement files into curves, physical metrics and objective evaluations. Its scope is experimental-data postprocessing: it performs no FEM/CAE analysis or device actuation and has no device bridge dependency.

## Processing

Inputs include Equipment measurements, initial specimen geometry, required mass and the run-bound objective. Code parses data, normalizes units, integrates curves and evaluates the objective. The LLM reviews whether to process the supplied data and accept the results within bounded choices; it cannot invent numerical values.

| Output | Meaning |
|---|---|
| FD curve | Measured force versus displacement |
| SS curve | Engineering stress and strain using initial area and gauge length |
| Key Metrics | Peak load/stress, energy and other values over the evaluation interval |
| Objective | Run-bound value, units and interval |
| BO Handoff | Observation with validity, run identity and provenance |

## Is the evidence sufficient?

Measurements must cover the objective's required interval. Missing coverage is not extrapolated into success. An endpoint-maximum warning remains visible: energy over a sufficiently measured fixed interval is different from an unobserved ultimate failure peak.

SS and FD use the same canonical samples. Display reduction is separate from the original data. Zero remains the recording-start reference; contact detection must not silently shift zero or the integration interval.

![Analysis measurement inputs and result handoffs](../../agents/assets/figures/analysis_01_closed_loop_handoffs.svg)

[Analysis reference](../../agents/analysis_agent.md), [reading metrics](measurement-metrics.md), [BO role](bo-role.md).
