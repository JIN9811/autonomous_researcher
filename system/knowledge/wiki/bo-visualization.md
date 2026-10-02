---
{"topic_id":"bo-visualization","owner":"documentation","source_refs":["system/agents/bo_agent.md","system/agents/analysis_agent.md"],"source_revision":{"system/agents/bo_agent.md":"1ba8c389239b02ff03943b167d01eba7f50f196a3c36a3a6b0f273cf7d371d33","system/agents/analysis_agent.md":"708ad6643bc4055b589b48237b69e4948412af8293d0eec918cf12aef5f71516"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: bo-visualization","status":"reviewed"}
---

# BO Visualization — LHS, Live Posterior and Objective

The BO Report shows which points are being explored and what is being optimized. A new plot does not itself establish a new measurement or performance improvement.

## LHS

LHS shows initial points within the parameter space and their progress. Assigning a point differs from accepting a valid measurement for it. The initial plot can appear before any measurement.

Read the completed count, target count and next index together. Failed or ineligible observations do not count as successful initial experiments. An explicit-coordinate experiment retains its requested coordinates rather than being forced through LHS.

## Live Posterior

The posterior represents model predictions and uncertainty from available observations. Model uncertainty is not equipment measurement error or repeat-test variability. Early stages may not yet satisfy the conditions for fitting a posterior.

For the two-variable Gyroid space, the current report offers a 2D heatmap
triptych and three vertically stacked 3D surfaces: predicted objective,
uncertainty and expected improvement. Both views use the same GP values and
physical cell-size/wall-thickness axes. They retain observations, the next
candidate and separate color scales. The old anonymous 1D display is a legacy
view, not a separate optimizer or the required current presentation.

## EI / LogEI

Acquisition is the numerical criterion for choosing the next observation. Default Expected Improvement uses LogExpectedImprovement. LogEI and measured objective values have different axes, units and meanings; do not compare them directly. Other acquisitions may be configured.

## Objective Equation

The top equation describes the actual run-bound objective. SEA, energy density and load are distinct targets, not interchangeable objective scores. Display rounding must not alter stored candidate coordinates.

When reading historical results, check the run, loop and candidate identity. Plot inspection reads saved results; it does not rerun optimization or equipment.

[BO reference](../../agents/bo_agent.md), [measurement metrics](measurement-metrics.md), [artifact explorer](artifacts.md).
