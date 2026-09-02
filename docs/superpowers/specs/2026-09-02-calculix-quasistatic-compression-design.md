# CalculiX Quasi-Static Compression Design

## Goal

Replace the current load-controlled linear equivalent CAE result with a displacement-controlled quasi-static compression path that evaluates the specimen to 50% of its experiment-planned initial height. The real path must run Gmsh and CalculiX when available; test mode must retain an explicitly labelled deterministic nonlinear equivalent so CI does not require external solvers.

## Current-state diagnosis

- `cae.run_static_analysis` only checks whether CalculiX exists and always calls `_equivalent_analysis`; it never invokes `ccx`.
- `CalculiXBridge.prepare_input` accepts prebuilt deck text but cannot generate a mesh or a compression deck.
- `CalculiXBridge.postprocess` only checks for `.dat` or `.frd`; it does not extract reaction force, displacement, or energy.
- Existing CAE defaults prescribe a 500 N cyclic load and therefore cannot be compared with a UTM curve measured to 50% engineering strain.
- The current host has neither `ccx` nor `gmsh`. Ubuntu packages are available for `calculix-ccx` 2.21 and Gmsh 4.12.1.

## Mechanical model

### Geometry and mesh

- Use the generated specimen STL as the real analysis geometry.
- Tetrahedralize the closed STL volume with Gmsh.
- Keep the mesh size configurable; use a coarse validation mesh for smoke tests and the experiment plan value for production jobs.
- Identify bottom and top node sets from the mesh coordinates using a tolerance derived from specimen height and mesh size.
- Reject a real solve if the STL is missing, the tetrahedral volume is empty, or either boundary node set is empty.

### Frictionless boundary conditions

There are no modeled platens and no contact pair.

- Bottom-face nodes: constrain only the compression-axis displacement `U3=0`.
- Top-face nodes: prescribe only `U3=-0.5 * initial_height_mm` through a linear ramp.
- Leave `U1` and `U2` free on both faces to represent frictionless lateral sliding.
- Remove the remaining rigid-body modes with minimal in-plane constraints: one bottom reference node gets `U1=U2=0`, and a second separated bottom node gets one in-plane constraint. These stabilizers must be reported separately from the frictionless face constraints.
- Never constrain every top/bottom node in `U1` or `U2`.

### Procedure and material

- Use `*STEP, NLGEOM, INC=<max_increments>` and `*STATIC` with automatic incrementation.
- Ramp the prescribed displacement from zero to the 50%-height endpoint. CalculiX static steps ramp boundary values by default; the deck should still emit an explicit named amplitude so the requested history is inspectable.
- Use the experiment-plan material properties. The first supported material is isotropic elastic plus multilinear plastic PLA; the elastic-only legacy values remain accepted but must be flagged as low-fidelity above yield.
- Do not use mass scaling or a dynamic procedure. “Quasi-static” here means a converged nonlinear static equilibrium path, not a physical wall-clock loading rate.

CalculiX supports nonlinear static analysis with `NLGEOM`, prescribed displacements through `*BOUNDARY`, and ramp histories through `*AMPLITUDE`; these are the governing solver features for this design. See the [official CalculiX project](https://www.calculix.de/) and the CalculiX keyword documentation for `*STEP`, `*BOUNDARY`, and `*AMPLITUDE`.

## Solver integration

### Real backend

`CAEBridge.run_static_analysis` remains the public API. In live mode it delegates to an enhanced `CalculiXBridge` pipeline:

1. validate STL and solver availability;
2. generate the Gmsh tetrahedral mesh;
3. build the CalculiX input deck and node sets;
4. run `ccx` behind the existing `runtime_solver_enabled` safety gate;
5. parse `.dat` reaction/displacement history;
6. write the canonical force-displacement curve and derived metrics;
7. return `.inp`, `.dat`, `.frd`, mesh, curve, and report provenance.

The existing `cae.run_static_analysis` name and response envelopes remain stable. Additive fields expose analysis type, target displacement, convergence, curve metrics, and artifacts.

### Test-mode equivalent

When test mode is used, calculate a deterministic nonlinear cellular compression curve with three inspectable regimes:

1. elastic rise;
2. collapse plateau;
3. densification hardening.

The curve depends on material modulus/yield strength, relative density, wall-to-cell ratio, specimen area, and initial height. It ends at 50% of the supplied height and is integrated with the same trapezoidal convention as Analysis Agent. It is labelled `deterministic_quasistatic_equivalent`, never `calculix` or `measured`.

The temporary UTM CSV may be used only as a validation band for a 30 mm reference case. Its value (`energy_absorption_50pct_mJ ~= 68284`) must not be embedded as a calibration constant or persisted as a real experiment.

## Result contract

Add these fields while preserving existing metrics:

- `analysis_type = quasistatic_compression`
- `loading_control = displacement`
- `target_strain = 0.5`
- `target_displacement_mm`
- `reaction_force_displacement_curve`
- `peak_reaction_force_N`
- `initial_stiffness_N_per_mm`
- `energy_absorption_50pct_mJ`
- `converged_increment_count`
- `requested_increment_count`
- `endpoint_reached`
- `solver_mode = calculix_quasistatic | deterministic_quasistatic_equivalent`

The canonical curve uses positive compression displacement and positive reaction-force magnitude. It must contain the exact target-displacement endpoint and must never extrapolate a partial real solve to 50% height.

## Installation and configuration

- Install `calculix-ccx`, `gmsh`, `python3-gmsh`, and `python3-meshio` from the host's Ubuntu repositories.
- Replace the stale Windows `.exe` paths in the Linux CAE configuration with discovered Linux executable paths or empty values that fall back to `PATH` discovery.
- Keep real solver execution gated. Installation alone must not cause background solves.
- Health output must report executable versions and paths.

## Failure handling

- Missing/invalid STL: `CAE_STL_REQUIRED` or `CAE_MESH_FAILED`.
- Missing executables: retain `CAE_SOLVER_REQUIRED` and add a distinct Gmsh failure code.
- CalculiX nonzero return: retain stdout/stderr tails and `CALCULIX_SOLVE_FAILED`.
- Non-convergence or incomplete endpoint: return the partial curve for diagnosis, set `endpoint_reached=false`, and do not emit a 50%-energy value.
- Malformed/missing reaction history: `CALCULIX_RESULT_PARSE_FAILED`.
- Test equivalent failures must never be silently relabelled as real solver results.

## Verification

- Unit-test normalization, frictionless node-set constraints, exact 50%-height target, deck keywords, `.dat` parsing, integration, incomplete-endpoint blocking, and legacy response keys.
- Use a fake `ccx` executable in unit tests to prove subprocess and artifact wiring without depending on system packages.
- After installing dependencies, run a small closed tetrahedral specimen smoke test through real Gmsh and CalculiX.
- Run a coarse representative gyroid STL when available and compare its 50%-energy, peak force, and stiffness with the temporary UTM curve only as a non-authoritative scale check.
- Acceptance for the temporary 30 mm validation case is the same order of magnitude, not forced agreement: finite endpoint, physically monotonic displacement, nonnegative reaction force, and 50%-energy within one decade. Tighter calibration waits for matched specimen IDs and repeated physical tests.

## Out of scope

- Rigid platen solids, surface contact, friction coefficients, and self-contact.
- Dynamic or cyclic fatigue simulation.
- Inverse fitting of material parameters to the temporary unidentified CSV.
- Claiming validation from a single unmatched specimen.
