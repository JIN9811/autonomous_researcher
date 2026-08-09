---
doc_type: reference
subtype: runtime
status: active
authority: descriptive
audience:
  - researcher
  - operator
  - developer
  - integrator
scope:
  - cae
  - calculix
  - pinn
  - external_computation
summary: Current computation-bridge contract for deterministic CAE, guarded CalculiX jobs, and explicit-availability PINN dataset/model operations.
source_of_truth:
  - device_bridges/cae_bridge.py
  - device_bridges/calculix_bridge.py
  - device_bridges/pinn_bridge.py
  - mcp_tools/cae_tools.py
  - mcp_tools/calculix_tools.py
  - mcp_tools/pinn_tools.py
  - configs/devices.yaml
  - app/main.py
last_verified: 2026-08-09
verified_against: 188a1d6
related_docs:
  - docs/device_bridges/README.md
  - docs/agents/analysis_agent.md
  - docs/paper/appendix_a_interfaces.md
supersedes: []
---

# CAE, CalculiX, and PINN Bridge Reference

## Summary

The CAE Computation boundary provides three related adapters: a deterministic/
live-preflight CAE facade, a guarded real CalculiX job path, and a PINN
dataset/model registry that reports unavailable models instead of inventing
predictions. These are external-computation and filesystem effects, not
physical laboratory device control.

## Scope

Included: solver health/defaults, static-analysis facade, CalculiX input deck,
solve/postprocess/job, PINN health/dataset/train/predict/registry, artifact
paths, runtime gates, and API/tool integration. Excluded: validation of
materials/models/meshes, solver numerical correctness, trained-model quality,
and scientific equivalence between deterministic/test and real results.

## Source of Truth

`CAEBridge`, `CalculiXBridge`, and `PINNBridge` define separate contracts.
Their `mcp_tools` registrars are all called by bootstrap. `/api/cae/*` exposes
the facade, while CalculiX and PINN primarily enter through registered tools.

## Actual Role

The boundary normalizes geometry/material/loading or solver/model payloads,
checks availability and explicit runtime gates, writes request/input artifacts,
runs or blocks bounded computation, and returns identity-bearing results. It
does not fabricate solver output or call a missing PINN model a failed physical
experiment.

## System Position and Agent Handoffs

![CAE computation system position](assets/figures/cae_computation_01_system_handoffs.svg)

**Figure CAE Computation-1.** Analysis may request deterministic comparison,
guarded CalculiX execution, or optional PINN work; solver/model evidence returns
to Analysis and downstream Knowledge/BO without a physical device effect.
Optional paths are dashed inspection projections.

| Producer | Input | Output/consumer |
|---|---|---|
| Analysis Agent | geometry/material/loading, measurement/FEA evidence | metrics/comparison/uncertainty context |
| Operator `/cae` | configuration and run request | health, blockers, artifacts, result |
| Knowledge/BO | accepted Analysis handoff | derived evidence only; no direct bridge call implied |
| Guardian | process/risk/budget context | allow/block/timeout evidence |

## Inputs, Commands, and Outputs

| Adapter | Inputs | Outputs |
|---|---|---|
| CAE facade | geometry/material/loading/boundary/mesh | deterministic or live-preflight static/cyclic metrics and artifacts |
| CalculiX | `.inp` path/text, run/specimen/job, runtime flag, timeout | request/deck, health, return code, DAT/FRD, postprocess status, trace |
| PINN | UTM/FEA records, dataset/model IDs, metrics/checkpoints, fixture prediction | dataset JSON, registry, registered/unavailable/predicted status |

## Internal Execution

![CAE computation execution boundary](assets/figures/cae_computation_02_execution_effect_boundary.svg)

**Figure CAE Computation-2.** Schema/input and availability gates precede
filesystem creation and optional solver/training subprocess work; result
artifacts and logs are validated before Analysis consumption. There is no
physical-effect node because the current boundary controls computation only.

| Phase | Gate/transformation | Effect/evidence |
|---|---|---|
| Configure | enabled/mode/executable/artifact roots/defaults | normalized config/health |
| Prepare | identifiers and deck/dataset payload | request, `.inp`, or dataset JSON |
| Execute | solver/training enabled and implementation available | bounded subprocess or registry write |
| Postprocess | expected DAT/FRD/model/result exists | artifact paths/status |
| Return | preserve failure/unavailable semantics | Analysis comparison/handoff |

## API Surface

`GET/POST /api/cae/config` reads or writes facade workspace settings;
`POST /api/cae/run` executes its bounded run contract. CalculiX and PINN do not
own dedicated HTTP families at this baseline; their exhaustive callable
surface is the Tool Registry. The Runtime IDE may display graph bridge/action
descriptors but those do not grant solver execution.

## Tools and Registry Integration

- `cae.health`, `cae.run_static_analysis` (`cae:calculix` device label);
- `calculix.health`, `prepare_input`, `solve`, `postprocess`, `run_job` plus
  resource `calculix_bridge`;
- `pinn.health`, `dataset.build`, `train`, `predict`, `registry` plus resource
  `pinn_bridge`.

Bootstrap registers all three; the graph projection names the CAE facade and
does not enumerate the other tool groups.

## Connections and Protocols

![CAE computation API and connections](assets/figures/cae_computation_03_api_connection_architecture.svg)

**Figure CAE Computation-3.** CAE API and three tool families reach independent
facade, solver-job, and model-registry adapters; filesystem and guarded
subprocess boundaries return decks, logs, fields, metrics, and model records.
No model/UI/graph descriptor bypasses execution gates.

Current connections are local filesystem and subprocess/executable discovery.
The CAE facade resolves CalculiX/Gmsh paths; the CalculiX adapter can run `ccx`
and discover optional postprocessors; PINN currently records explicit dataset/
model/prediction contracts and does not hide model unavailability.

## Configuration and Secrets

`devices.cae` defines enabled/mode/provider/solver/mesher paths, live solver
requirement, artifact directory, and material/loading/boundary/mesh defaults.
CalculiX falls back to CAE config unless a dedicated section exists. PINN uses
defaults unless `devices.pinn` is provided; runtime training defaults false and
no active model is configured. Current adapters require executable paths, not
network credentials.

## State, Events, Artifacts, and Evidence

Artifacts include facade requests/results, CalculiX request JSON and `.inp`,
stdout/stderr tails, DAT/FRD and optional converted fields, PINN dataset JSON,
`model_registry.json`, metrics/checkpoint metadata, and step traces. Raw UTM
measurement remains distinct from derived solver/PINN output.

## Runtime Modes and Fallbacks

CAE test mode can return deterministic equivalent calculations. Live facade
requires configured solver availability as declared. CalculiX real execution
requires `runtime_solver_enabled`; missing executable blocks. PINN training
requires `runtime_training_enabled`; prediction without a registered model is
`unavailable`, not a synthetic fallback. No adapter silently substitutes
another fidelity.

## Safety, Approval, and Effect Boundary

Effects are local filesystem writes and optional CPU/GPU/external solver
processes. They can consume time/resources and overwrite job-named artifacts
within bounded directories but do not command laboratory mechanics. Schema,
identifier, enabled/mode, executable/model availability, runtime permission,
timeout, and artifact checks guard the boundary.

## Errors, Timeouts, and Recovery

Disabled bridge, missing executable/model, disabled runtime gate, invalid
input, nonzero return, timeout, or missing result artifact remains explicit.
On solver timeout retain request/deck and partial logs/artifacts, inspect the
process and job directory, and avoid labeling partial output complete. PINN
unavailability should route Analysis without fabricating a curve.

## Operator and GUI Surfaces

The `/cae` workspace exposes facade configuration and runs. Tool/Runtime IDE
surfaces may expose CalculiX/PINN health and actions. Operator output must show
mode, executable/model availability, runtime gate, input identity, artifacts,
and failure/unavailable distinction.

## Current Verification

Inspection covered all three bridge and registrar implementations,
configuration, CAE APIs, multifidelity schemas/tests, and focused CAE contracts
at `188a1d6`. Numerical accuracy and live solver/PINN quality were not
evaluated by documentation inspection.

## Limitations and Known Gaps

The graph/API projection does not show CalculiX and PINN as separate bridge
entries despite bootstrap registration. CAE facade and CalculiX job adapter
overlap conceptually but expose different contracts. PINN training currently
registers supplied metadata rather than proving a training backend ran.

## Related Documents

- [Analysis Agent](../agents/analysis_agent.md)
- [Agent API Matrix](../agents/agent_api_connection_matrix.md)
- [Interfaces Appendix](../paper/appendix_a_interfaces.md)
- [Bridge Matrix](bridge_api_connection_matrix.md)
