---
{"topic_id":"bo-role","owner":"bo_agent","source_refs":["docs/agents/bo_agent.md"],"source_revision":{"docs/agents/bo_agent.md":"4cfbe0eb15190935ef636c3cbf50f4b6c657f4c9994cbbad750495acd996e29a"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: bo-role","status":"reviewed"}
---

# Bayesian Optimization Agent — Initial and Next Designs

## Runtime decision reference

BO reviews the supplied strategy and numerical results. The active request owns the objective, direction, parameter space, fixed values, initialization budget and acquisition configuration. Solver outputs own exact coordinates. Documentation examples cannot override these settings or count as observations.

## Overview

BO calculates design coordinates from the declared parameter space and valid objective observations. The LLM selects bounded strategies/tools and reviews results; LHS and numerical optimization tools determine exact coordinates. Model prose cannot rewrite them.

## Initial LHS and subsequent BO

When Latin Hypercube initialization is configured, initial points explore the declared space. The active initialization configuration supplies the required observation count; no count is prescribed by this page. Failed or ineligible observations do not increase the count.

During initialization, LHS status and the next index govern progression. GP modeling and acquisition apply when eligible. Default EI uses LogExpectedImprovement; other supported acquisitions may be configured.

## What is preserved?

Inputs include the objective and direction, parameter space, fixed values, valid Analysis observations and provenance. The next-design request carries candidate identity, exact coordinates and the declared space. Design preserves these coordinates and independently checks manufacturing constraints.

Model review cannot ignore fixed values, out-of-range parameters or invalid observations. Reviewing an already computed candidate does not rerun optimization.

## Reading the report

Objective shows the run-bound equation and units. LHS shows initial coverage and progress. Live Posterior shows predictions, uncertainty and observations; it may be unavailable early on. A plot's existence is not proof of measured improvement.

The first LHS plot is published through normal Design entry before the first measurement. Viewing historical plots does not rerun the optimizer.

[BO reference](../../agents/bo_agent.md), [BO plots](bo-visualization.md), [Design role](design-role.md).
