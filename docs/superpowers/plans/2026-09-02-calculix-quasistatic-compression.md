# CalculiX Quasi-Static Compression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run displacement-controlled CalculiX compression to 50% of the planned specimen height and expose a reaction-force curve and energy metric comparable with UTM Analysis.

**Architecture:** Add a focused quasi-static utility for mesh/deck/result transformations, enhance the existing CalculiX bridge to call Gmsh and `ccx`, and make `CAEBridge` select the real backend in live mode while retaining a nonlinear deterministic equivalent in test mode. Keep `cae.run_static_analysis` and all existing response keys stable.

**Tech Stack:** Python 3.12, Gmsh 4.12, CalculiX CrunchiX 2.21, Abaqus/CalculiX `.inp`, CalculiX `.dat`/`.frd`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-calculix-quasistatic-compression-design.md`

## Global Constraints

- The target displacement is always `0.5 * specimen_size_mm[2]`; neither 15 mm nor 30 mm is a code constant.
- Bottom and top face nodes are constrained only in `U3`; in-plane constraints are limited to the minimum nodes needed to remove rigid motion.
- Do not model platens, contact, friction, self-contact, or dynamics.
- A partial real solve must not receive a 50%-height energy value.
- Test-mode equivalent results must remain visibly distinct from real CalculiX results.
- The temporary unidentified UTM CSV is scale-check evidence only and is never a calibration constant.
- Preserve unrelated dirty-worktree changes and do not create a mixed commit.

---

### Task 1: Canonical quasi-static transforms

**Files:**
- Create: `utils/calculix_quasistatic.py`
- Create: `tests/unit/test_calculix_quasistatic.py`

**Interfaces:**
- Produces: `parse_gmsh_inp_mesh(text: str) -> tuple[dict[int, tuple[float, float, float]], list[str]]`
- Produces: `select_frictionless_boundary_nodes(nodes, *, tolerance_mm: float) -> dict[str, Any]`
- Produces: `build_compression_deck(mesh_text: str, *, material: dict[str, Any], target_displacement_mm: float, increments: dict[str, Any]) -> tuple[str, dict[str, Any]]`
- Produces: `parse_reaction_history(dat_text: str, *, target_displacement_mm: float, endpoint_tolerance_mm: float) -> dict[str, Any]`
- Produces: `curve_metrics(curve: list[dict[str, float]], *, target_displacement_mm: float) -> dict[str, Any]`

- [ ] **Step 1: Write failing boundary/deck tests**

Use a literal eight-node 10 mm cube mesh. Assert bottom nodes are `{1,2,3,4}`, top nodes are `{5,6,7,8}`, all face nodes get only degree 3 boundary lines, exactly one anchor gets degrees 1-2, the second anchor gets one in-plane degree, and the deck contains:

```text
*STEP,NLGEOM,INC=500
*STATIC
*AMPLITUDE,NAME=QS_RAMP
*BOUNDARY,AMPLITUDE=QS_RAMP
TOP,3,3,-5
*NODE PRINT,NSET=TOP,TOTALS=ONLY,FREQUENCY=1
RF
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_calculix_quasistatic.py -k 'boundary or deck'`

Expected: import failure because `utils.calculix_quasistatic` does not exist.

- [ ] **Step 3: Implement mesh parsing, boundary selection, and deck generation**

Parse only `*NODE` coordinates while preserving all mesh cards. Compute `z_min/z_max`, use `max(tolerance_mm, height * 1e-6)`, choose deterministic anchor nodes by `(x,y,node_id)`, append node sets/material/step cards, and return a manifest containing face nodes, anchors, height, target, and constraint counts.

- [ ] **Step 4: Write failing reaction-history tests**

Use literal `.dat` excerpts with two `time=` blocks, `displacements (vx,vy,vz)` output for `TOP_REF`, and `total force (fx,fy,fz)` output for `TOP`. Assert compression signs become positive, endpoint interpolation is forbidden, `N*mm` integrates directly to `mJ`, and a 4.9 mm partial curve for a 5 mm target yields `endpoint_reached=false` and `energy_absorption_50pct_mJ=None`.

- [ ] **Step 5: Run parser tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_calculix_quasistatic.py -k 'reaction or endpoint or energy'`

- [ ] **Step 6: Implement result parsing and curve metrics**

Return an ordered canonical curve with zero origin, positive compression magnitudes, finite-value filtering, duplicate-displacement collapse, exact endpoint validation, trapezoidal energy, peak force, and initial 0-5% target-range stiffness.

- [ ] **Step 7: Run Task 1 tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_calculix_quasistatic.py`

---

### Task 2: CalculiX bridge real meshing and solve pipeline

**Files:**
- Modify: `device_bridges/calculix_bridge.py`
- Modify: `tests/unit/test_multifidelity_contracts.py`

**Interfaces:**
- Consumes: Task 1 deck/parser functions.
- Produces: `CalculiXBridge.mesh_stl(payload) -> dict[str, Any]`
- Produces: `CalculiXBridge.prepare_quasistatic_input(payload) -> dict[str, Any]`
- Extends: `CalculiXBridge.run_job(payload)` with `analysis_type=quasistatic_compression`.

- [ ] **Step 1: Write a failing fake-Gmsh/fake-ccx pipeline test**

Create executable test scripts in `tmp_path`: fake Gmsh writes a literal cube `.inp`; fake `ccx` writes a literal converged `.dat` and `.frd`. Run the real bridge subprocess path with `runtime_solver_enabled=true`, a real temporary STL, `specimen_size_mm=[10,10,10]`, and assert:

```python
assert result["ok"] is True
assert result["solver_mode"] == "calculix_quasistatic"
assert result["target_displacement_mm"] == 5.0
assert result["metrics"]["endpoint_reached"] is True
assert result["artifacts"]["curve_json_path"].endswith(".curve.json")
```

- [ ] **Step 2: Run the pipeline test and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_multifidelity_contracts.py -k quasistatic`

Expected: `run_job` does not mesh STL, generate a deck, or return curve metrics.

- [ ] **Step 3: Add Gmsh configuration and health details**

Extend `CalculiXBridgeConfig` with `gmsh_path`, mesh timeout, and default increment controls. Health resolves `ccx` and `gmsh` through configured absolute paths then `PATH`, and reports version strings without executing a solve.

- [ ] **Step 4: Implement STL meshing and deck preparation**

Write a `.geo` file into the job directory, run Gmsh with an explicit output path and mesh size, validate the generated `.inp`, call Task 1 deck generation, and persist a mesh/deck manifest. Do not mutate the source STL.

- [ ] **Step 5: Implement solve/postprocess orchestration**

Keep the existing runtime execution gate. Run `ccx <jobname>` in the job directory, parse `.dat`, retain `.frd`, write `.curve.json`, and return explicit convergence/endpoint metadata. Preserve stdout/stderr tails and existing failure codes.

- [ ] **Step 6: Add failure tests**

Cover missing STL, unavailable Gmsh, empty mesh, nonzero `ccx`, missing `.dat`, malformed history, and incomplete endpoint. Each test asserts the specific failure code and available diagnostic artifacts.

- [ ] **Step 7: Run bridge tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_multifidelity_contracts.py tests/unit/test_calculix_quasistatic.py`

---

### Task 3: CAE public API and nonlinear test equivalent

**Files:**
- Modify: `device_bridges/cae_bridge.py`
- Modify: `mcp_tools/cae_tools.py`
- Modify: `tests/unit/test_cae_tools.py`

**Interfaces:**
- Preserves: `cae.run_static_analysis`.
- Adds normalized loading fields: `loading_control`, `target_strain`, `target_displacement_mm`, `initial_increment`, `minimum_increment`, `maximum_increment`, `max_increments`.
- Produces the same curve metric names in real and test modes.

- [ ] **Step 1: Write failing deterministic quasi-static tests**

For `[30,30,30]`, PLA defaults, relative density `0.32`, wall `1.2`, and cell `10`, assert the returned curve begins at zero, ends at exactly 15 mm, contains elastic/plateau/densification regions, is labelled `deterministic_quasistatic_equivalent`, and has finite nonnegative `energy_absorption_50pct_mJ` in the same decade as `68284.046414 mJ`.

- [ ] **Step 2: Write a failing live-delegation test**

Inject a configured CalculiX bridge resource or factory and assert live mode calls the real quasi-static job while test mode does not execute external commands.

- [ ] **Step 3: Run CAE tests and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_cae_tools.py -k quasistatic`

- [ ] **Step 4: Implement normalized displacement-control defaults**

Replace the default cyclic force contract with additive quasi-static fields while continuing to parse legacy load fields. Derive the target exclusively from specimen height unless an explicit target strain is supplied within `(0, 0.8]`.

- [ ] **Step 5: Implement the test-mode cellular curve**

Use material/design parameters to derive elastic stiffness, plateau stress, and densification hardening. Generate a deterministic 101-point curve to the target. Reuse Task 1 curve metrics. Keep legacy CAE scalar metrics and add curve metrics; do not use the temporary UTM energy as a coefficient.

- [ ] **Step 6: Route live mode to CalculiX**

Construct the real bridge from the same device config, pass the STL/material/mesh/increment contract, require the solver gate, and map its result into the stable CAE response envelope.

- [ ] **Step 7: Run CAE regression tests and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_cae_tools.py tests/integration/test_cae_gui_api.py`

---

### Task 4: Analysis curve agreement

**Files:**
- Modify: `agents/analysis_agent.py`
- Modify: `tests/unit/test_analysis_agent.py`

**Interfaces:**
- Consumes CAE metrics: `peak_reaction_force_N`, `initial_stiffness_N_per_mm`, `energy_absorption_50pct_mJ`.
- Extends: `fem_utm_comparison.v1` additively with `energy_absorption_50pct_error_pct`.

- [ ] **Step 1: Write a failing three-metric comparison test**

Supply literal UTM and CAE values with hand-calculated peak, stiffness, and energy percentage errors. Assert the agreement score includes all three and that the comparison exposes both UTM and CAE energy values.

- [ ] **Step 2: Run the comparison test and verify RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py -k cae_quasistatic_energy`

- [ ] **Step 3: Add the quasi-static aliases and energy comparison**

Prefer `peak_reaction_force_N` over legacy `load_max_N`; compare the matching 50%-height energies only when both endpoints were reached. Preserve old records that expose only peak/stiffness.

- [ ] **Step 4: Run Analysis regressions and verify GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_analysis_agent.py tests/unit/test_cae_tools.py`

---

### Task 5: Host installation, configuration, and real smoke tests

**Files:**
- Modify: `configs/devices.yaml`
- Modify: `docs/agents/cae_analysis_runtime_guideline.txt`
- Modify: `docs/device_bridges/cae_computation_bridges.md`

**Interfaces:**
- Installs host commands: `/usr/bin/ccx`, `/usr/bin/gmsh`.
- Preserves real-solve opt-in through `runtime_solver_enabled` and live mode.

- [ ] **Step 1: Install Ubuntu packages**

Run:

```bash
sudo apt-get update
sudo apt-get install -y calculix-ccx gmsh python3-gmsh python3-meshio
```

- [ ] **Step 2: Verify executable health**

Run: `ccx -v` and `gmsh --version`. Confirm health reports Linux paths and version output.

- [ ] **Step 3: Replace stale Windows configuration paths**

Set Linux CAE paths to `/usr/bin/ccx` and `/usr/bin/gmsh`, retain `require_solver_in_live=true`, and add explicit quasi-static mesh/increment defaults.

- [ ] **Step 4: Run a real cube smoke test**

Generate a temporary closed cube STL through the repository's existing geometry path, run a coarse 5%-strain smoke solve first, and assert `.inp`, `.dat`, `.frd`, curve JSON, convergence, and endpoint. This smoke test is diagnostic and is not persisted as an experiment observation.

- [ ] **Step 5: Run a representative gyroid scale test**

Select an existing closed 30 mm gyroid STL, use a deliberately coarse mesh and 50% target, and cap runtime with the configured timeout. If convergence stops early, retain the partial artifacts and report the last converged displacement rather than fabricating energy.

- [ ] **Step 6: Compare with the temporary UTM artifact**

Report force, stiffness, and 50%-energy ratios. Treat within one decade as a smoke-scale success only; do not mark the model calibrated.

- [ ] **Step 7: Update runtime documentation**

Document installation, frictionless constraint details, solver gating, new curve artifacts, partial-solve behavior, and the difference between deterministic equivalent and real CalculiX results.

---

### Task 6: Final regression and hygiene

**Files:**
- Verify all files above.

**Interfaces:**
- Confirms legacy CAE/Analysis contracts and new quasi-static behavior coexist.

- [ ] **Step 1: Run focused suites**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_calculix_quasistatic.py \
  tests/unit/test_multifidelity_contracts.py \
  tests/unit/test_cae_tools.py \
  tests/unit/test_analysis_agent.py \
  tests/integration/test_cae_gui_api.py
```

- [ ] **Step 2: Run static checks**

Run: `.venv/bin/python -m py_compile utils/calculix_quasistatic.py device_bridges/calculix_bridge.py device_bridges/cae_bridge.py agents/analysis_agent.py` and `git diff --check`.

- [ ] **Step 3: Inspect provenance and worktree scope**

Confirm real-solver reports contain executable versions, mesh/deck/result paths, endpoint status, and solver mode. Inspect only intended diffs and leave unrelated agent changes untouched.
