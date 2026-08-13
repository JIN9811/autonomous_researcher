# Two-Variable Gyroid SEA Bayesian Optimization Design

## Scope

The first production BO problem is restricted to two Gyroid design variables:

\[
\mathbf{x} = [a, \rho]
\]

- `cell_size_mm` \(a=L/N\), with `L=30 mm` and integer `N in {3,4,5,6}`.
- The only valid cell sizes are `{10.0, 7.5, 6.0, 5.0} mm`.
- `relative_density` \(\rho\) is continuous on `[0.20, 0.48]`.
- A later revision may add `orientation_deg`; it is fixed at `0` in this revision.

## Fixed Geometry And Manufacturing Conditions

- Geometry is `gyroid`.
- `specimen_size_mm=[30,30,30]`.
- `anisotropy_ratio=1.0`.
- `orientation_deg=0.0`.
- `defect_ratio=0.0`.
- Closed-loop test specimens contain only the TPMS body from the first LHS point onward; generated top/bottom caps are disabled. CAE compression platens remain analysis-only geometry, while standalone physical-print profile settings remain operator-controlled.
- Printer, material, nozzle, layer, skirt, and cap settings are manufacturing constraints, not GP dimensions.
- `tpms_thickness` is derived from target relative density instead of being optimized independently.
- Realized relative density and generated wall/feature measurements are persisted alongside requested values.

## Initial Design

Before fitting a GP, BO Agent creates a deterministic Latin Hypercube initial-design queue. Cell-size choices are balanced across the queue; relative density is stratified continuously. A queue item is consumed only after its realized geometry and SEA observation are linked to the same experiment/cycle identifier.

The automatic initial-design size is eight observations. GP fitting and acquisition optimization remain unavailable until all eight valid SEA observations exist. Invalid or failed experiments do not count as completed initial observations.

## GP Model

- Inputs are encoded in `[0,1]^2` before model fitting.
- `relative_density` uses affine min-max normalization.
- `cell_size_mm` uses the ordered feasible set and mixed/discrete acquisition optimization; decoded proposals always belong to the feasible set.
- Model is `SingleTaskGP` with an explicit ARD Matérn 5/2 covariance (`ard_num_dims=2`) and output scale.
- Observation noise is inferred as homoskedastic Gaussian noise unless positive measurement uncertainty is supplied, in which case fixed per-observation variance is used.
- SEA output is standardized for fitting and converted back to physical units for reports.

## Objective And Acquisition

The objective is to maximize measured specific energy absorption:

\[
SEA = \frac{E_{absorbed}}{m}\quad[J/g]
\]

The authoritative value is `specific_energy_absorption_J_per_g` from Analysis Agent. Composite `objective_score` values must not replace SEA for this objective.

Expected Improvement is the only default acquisition for this first problem. The optimizer enumerates each valid cell size, optimizes EI over normalized relative density for that choice, and returns the globally best feasible candidate. Duplicate evaluated or queued candidates are rejected.

## Agent Handoffs

1. Orchestrator receives the operator experiment JSON. In test mode it creates or resumes the deterministic eight-point LHS plan automatically; in live mode it uses the operator-approved values.
2. Orchestrator publishes `orchestrator_design_contract.v1` with the current `requested_parameters={cell_size_mm, relative_density}`, phase, cycle identity, optimization contract, and LHS point states.
3. Design Agent consumes that Orchestrator contract as the only authoritative active-variable request and generates the realizable Gyroid.
4. Design Agent records requested and realized parameters separately and retains the Orchestrator contract reference.
5. Analysis Agent calculates measured SEA and Knowledge Agent persists the observation and provenance.
6. BO Agent consumes the valid observation. Before eight accepted observations it selects the next point from the same fixed LHS plan; afterwards it fits/updates the GP and optimizes EI.
7. The BO `next_design_request.v1` is republished by Orchestrator as the next cycle's `orchestrator_design_contract.v1` before Design Agent runs.

The required closed-loop order is therefore:

`Orchestrator JSON -> Design -> experiment/evidence -> Analysis -> Knowledge -> BO -> Orchestrator JSON -> Design`

BO never bypasses Orchestrator to mutate Design Agent inputs directly.

## GUI And Artifacts

During initialization, the Design Agent card displays the two-dimensional `cell_size_mm x relative_density` LHS design-space scatter: measured points are blue, the next point is an orange cross, and remaining planned points are gray. It also exposes the feasible cell sizes, `L/N` definition, relative-density bounds, and completed/required initial observations.

The BO Agent card remains at `Waiting for initial design data` until all eight valid LHS observations exist. After that gate opens, the BO card displays the ARD Matérn 5/2 scalar-score posterior, uncertainty bands, Expected Improvement, measured scores, and requested next point over an anonymous normalized search coordinate. This output figure never displays input-variable names or values, parameter strata, parameter slices, facets, or input tooltips; the separate LHS card owns input-space visualization. Figures use a white publication-style plotting surface.

## Failure Rules

- Reject cell sizes outside the exact feasible set.
- Reject relative density outside `[0.20,0.48]`.
- Reject missing, non-finite, or unit-incompatible SEA observations.
- Do not silently substitute a heuristic backend if BoTorch fitting or EI optimization fails.
- Do not advance from LHS to GPR until eight valid unique observations are present.

## Verification

- Unit tests cover feasible cell sizes, normalization round trips, balanced LHS, SEA extraction, explicit ARD Matérn 5/2 construction, noise mode, and EI proposals.
- Agent tests prove the first Design request comes from LHS and later requests come from GPR/EI.
- Browser tests prove the Design card owns the LHS design-space plot and the BO card exposes only the post-initialization surrogate/acquisition view without clipping.
- Closed-loop tests prove one observation is consumed and one next point is emitted per completed cycle.
