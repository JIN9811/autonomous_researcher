# FEniCSx Analysis Runtime Assets

Status: implemented runtime asset note
Last reviewed: 2026-05-30
Scope: Analysis Agent FEM/FEniCSx assets, bridge runtime, and improvement 06 integration.

## Purpose

FEniCSx is prepared as an optional FEM backend for the Analysis Agent. It must be
used as a validated template runner or deterministic/cache-backed backend, not
as arbitrary live LLM-generated solver code.

In the closed-loop workflow, FEniCSx output is treated as a simulation signal.
It is not a physical UTM observation and must not be inserted into BO as a
measured high-fidelity point.

## Local Asset Bundle

Downloaded source, tutorial, and documentation snapshots are stored outside Git:

```text
artifacts/external/fenicsx/
```

The bundle currently contains:

```text
sources/dolfinx
sources/basix
sources/ffcx
sources/ufl
sources/fenics-docs
sources/dolfinx-tutorial
docs/html
docs/pdf/dolfinx-tutorial-latest.pdf
examples/poisson_smoke.py
manifests/fenicsx_sources_manifest.txt
```

This directory is under `artifacts/` and is intentionally ignored by Git because
the checkout and Docker assets are large.

## Verified Runtime Paths

Conda runtime:

```bash
conda run -n fenicsx python artifacts/external/fenicsx/examples/poisson_smoke.py
```

Verified local package versions:

```text
dolfinx=0.10.0
basix=0.10.0
ufl=2025.2.1
ffcx=0.10.0
```

Docker runtime:

```bash
docker run --rm --entrypoint python3 \
  -v "$PWD/artifacts/external/fenicsx/examples:/work/examples:ro" \
  -w /work \
  dolfinx/dolfinx:stable \
  examples/poisson_smoke.py
```

Verified Docker image:

```text
dolfinx/dolfinx:stable
```

## Analysis Agent Integration Rule

The Analysis Agent should create and validate structured FEM artifacts:

```text
fem_request.json
fem_plan.json
fem_result.json
fem_cache_manifest.json
fem_utm_comparison.json
```

Required separation:

- `utm_high`: physical UTM measurement and objective source.
- `fem_low`: simulation prediction, risk signal, calibration signal, or cache lookup.
- `fem_utm_comparison`: agreement/residual diagnostic used by Analysis, Knowledge, Guardian, and BO context.

FEM cache keys should include geometry hash, material model, loading/boundary
condition, solver backend/version, mesh setting, and calibration version.

## Implemented Bridge Contract

Runtime bridge files:

```text
device_bridges/fenicsx_bridge.py
mcp_tools/fenicsx_tools.py
scripts/fenicsx_linear_elasticity_template.py
```

Registered MCP tools:

```text
fenicsx.health
fenicsx.run_linear_elasticity
fenicsx.run_fem
fenicsx.set_runtime_solver
```

The bridge accepts a validated `fem_request.v1`-style payload and returns
`fem_result.v1`. By default, `runtime_solver_enabled=false` keeps repeated test loops on the fast deterministic bridge path. When `runtime_solver_enabled=true`, `auto`, `conda`, or `docker` first attempts to run the fixed DOLFINx solver template. `fenicsx.set_runtime_solver` can toggle this at runtime. In `deterministic` mode, or when configured to allow fallback after a runtime failure, it uses the deterministic template.

The real DOLFINx template solves a homogenized small-strain linear-elasticity
problem using bottom fixed support and top compression traction, matching the
DOLFINx tutorial workflow while staying bounded and reproducible for agentic
runtime use.

`fem_result.v1` includes:

- `metrics` / `fem_metrics`
- `fidelity_record.fidelity=fem_low`
- `cache_key`
- `cache_status`
- `runtime_probe`
- `artifacts.fem_request`
- `artifacts.fem_result`
- `artifacts.fem_cache_manifest`
- `artifacts.fenicsx_solver_output` when a real solver run was attempted
- `artifacts.solver_xdmf` when DOLFINx wrote visualization output

The bridge writes artifacts under:

```text
artifacts/fenicsx/<run_id>/<specimen_id>/
```

The Analysis Agent consumes this result and writes run-local evidence under:

```text
runs/<run_id>/analysis/<specimen_id>/
```

Key downstream payloads:

- `bo_observation.v1`
- `analysis_bo_handoff_v1`
- `experiment_evaluation.v1`
- `analysis_knowledge_payload.v1`

Validation commands:

```bash
.venv/bin/python -m pytest tests/unit/test_fenicsx_bridge.py tests/unit/test_analysis_agent.py -q
conda run -n fenicsx python scripts/fenicsx_linear_elasticity_template.py <request.json> <result.json>
```

## LLM Agentic Loop Contract

Analysis Agent now runs FEniCSx as a tutorial-derived agentic loop after UTM
metrics are available:

```text
UTM metrics
-> analysis_fem_planning LLM call
-> sanitized analysis_fem_agentic_plan.v1
-> fenicsx.health
-> fenicsx.run_linear_elasticity mesh/refinement iteration(s)
-> FEM/UTM agreement check
-> selected fem_result.v1
-> fem_agentic_loop.json
-> analysis_bo_handoff_v1
```

The LLM is allowed to choose planning metadata only: `mesh_sweep_mm`,
`max_iterations`, `acceptance.min_agreement_score`, and a decision policy. The
agent sanitizes these values and caps iterations before tool execution. The LLM
never writes or executes solver source code.

Tutorial-derived fixed steps embedded in the loop:

- Create a 3D mesh or bounding-box mesh representation.
- Define a vector-valued Lagrange displacement function space.
- Apply bottom Dirichlet support and top compression loading.
- Define small-strain `epsilon(u)`, isotropic `sigma(u)`, bilinear form, and
  linear form.
- Solve the linear variational problem using the registered FEniCSx bridge.
- Postprocess displacement, reaction force, stiffness, Von Mises proxy, and
  FEM/UTM residuals.

## Source References

- FEniCSx documentation index: `https://docs.fenicsproject.org/`
- DOLFINx Python installation: `https://docs.fenicsproject.org/dolfinx/main/python/installation.html`
- DOLFINx source: `https://github.com/FEniCS/dolfinx`
- Basix source: `https://github.com/FEniCS/basix`
- FFCx source: `https://github.com/FEniCS/ffcx`
- UFL source: `https://github.com/FEniCS/ufl`
- Dokken FEniCSx tutorial: `https://jsdokken.com/dolfinx-tutorial/`
- Dokken tutorial source: `https://github.com/jorgensd/dolfinx-tutorial`
