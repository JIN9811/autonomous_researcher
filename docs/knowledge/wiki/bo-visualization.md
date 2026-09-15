---
{"topic_id":"bo-visualization","owner":"documentation","source_refs":["docs/agents/bo_agent.md","docs/agents/analysis_agent.md"],"source_revision":{"docs/agents/bo_agent.md":"4cfbe0eb15190935ef636c3cbf50f4b6c657f4c9994cbbad750495acd996e29a","docs/agents/analysis_agent.md":"dd1427c585819820ad7a410301f0b69fb54057cd93b37f05ef5e58f2120bfd96"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: bo-visualization","status":"reviewed"}
---

# BO Visualization — LHS, Live Posterior and Objective

The BO Report shows which points are being explored and what is being optimized. A new plot does not itself establish a new measurement or performance improvement.

## LHS

LHS shows initial points within the parameter space and their progress. Assigning a point differs from accepting a valid measurement for it. The initial plot can appear before any measurement.

Read the completed count, target count and next index together. Failed or ineligible observations do not count as successful initial experiments. An explicit-coordinate experiment retains its requested coordinates rather than being forced through LHS.

## Live Posterior

The posterior represents model predictions and uncertainty from available observations. Model uncertainty is not equipment measurement error or repeat-test variability. Early stages may not yet satisfy the conditions for fitting a posterior.

## EI / LogEI

Acquisition is the numerical criterion for choosing the next observation. Default Expected Improvement uses LogExpectedImprovement. LogEI and measured objective values have different axes, units and meanings; do not compare them directly. Other acquisitions may be configured.

## Objective Equation

The top equation describes the actual run-bound objective. SEA, energy density and load are distinct targets, not interchangeable objective scores. Display rounding must not alter stored candidate coordinates.

When reading historical results, check the run, loop and candidate identity. Plot inspection reads saved results; it does not rerun optimization or equipment.

[BO reference](../../agents/bo_agent.md), [measurement metrics](measurement-metrics.md), [artifact explorer](artifacts.md).
