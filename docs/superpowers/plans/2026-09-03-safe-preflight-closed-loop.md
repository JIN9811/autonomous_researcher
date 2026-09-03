# Safe Preflight Closed-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a hardware-free full closed loop with printer, VLA, and UTM stopped at their actuation boundaries, calibrated CAE observations, exact-metric fail-closed BO, and position-aware physical-printer auto-ejection readiness.

**Architecture:** Carry an additive per-stage execution policy in the experiment specification. Device-owning agents emit typed preflight records without claiming physical completion; Analysis accepts an explicitly calibrated CAE observation only for this policy, and BO trains only on exact named objective observations. Existing Bambu G-code patching, Lab Equipment skill flows, and CalculiX quasi-static interfaces remain the implementation boundaries.

**Tech Stack:** Python 3.12, pytest, asyncio, existing ATR agent/runtime contracts, Bambu `.gcode.3mf`, TrapeziumX CSV parser, CalculiX/CAE bridge, BoTorch backend.

**Spec:** `docs/superpowers/specs/2026-09-03-safe-preflight-closed-loop-design.md`

## Global Constraints

- Do not call physical printer, robot/VLA, Windows/PyAutoGUI, or UTM execution APIs in verification.
- Preserve unrelated and concurrent uncommitted changes.
- Keep `energy_density_50pct_MJ_per_m3` as the sole default optimization metric.
- Preserve explicit physical-run confirmations and fail closed on unknown execution-policy values.
- Use historical UTM CSVs as fingerprinted calibration references, never as current-cycle measurements.

---

### Task 1: Execution-policy contract and controller persistence

**Files:**
- Modify: `app/controller.py`
- Test: `tests/unit/test_controller_planning.py`

**Interfaces:**
- Consumes: `current_experiment_spec.execution_policy`
- Produces: normalized policy preserved across BO-driven redesigns and stage payloads

- [x] Add a failing test that starts a multi-cycle planning spec with printer/manipulation/lab-equipment `preflight_only`, applies a BO update, and asserts the complete policy survives in the next cycle.
- [x] Run the focused test and confirm it fails because the policy is dropped or not normalized.
- [x] Add minimal policy normalization, fail-closed validation, and merge preservation in the controller.
- [x] Run the focused controller tests and confirm they pass.

### Task 2: Position-aware printer preflight and auto-ejection artifact

**Files:**
- Modify: `agents/specimen_agent.py`
- Modify only if required: `device_bridges/bambu_bridge.py`
- Modify only if required: `device_bridges/bambu_autoejection.py`
- Modify: `device_bridges/prusa_bridge.py`
- Test: `tests/unit/test_specimen_agent.py`
- Test: `tests/unit/test_bambu_bridge.py`
- Test: `tests/unit/test_prusa_bridge.py`

**Interfaces:**
- Consumes: candidate STL, exact plate `.gcode.3mf`, plate ID, saved auto-ejection configuration
- Produces: provider-independent `printer_preflight.v1` with run/specimen lineage, source/patched hashes, extrusion bounds, ejection evidence, and readiness

- [x] Add a failing test using an off-center local plate G-code and assert the patched ejection path is derived from its actual bounds while upload/start tripwires remain untouched.
- [x] Run the test and confirm the missing typed preflight/readiness behavior fails.
- [x] Reuse the existing immutable Bambu patch/validation path from Specimen Agent when `printer=preflight_only`; never call upload/start.
- [x] Add or tighten validation only where the existing bridge does not prove archive mapping, MD5, print-body preservation, single-tail ordering, and bounded position-aware motion.
- [x] Run focused Specimen/Bambu tests.
- [x] Prove Prusa `preflight_only` performs local slicing/ejection validation and stops before every PrusaLink operation.

### Task 3: Manipulation/VLA preflight-only boundary

**Files:**
- Modify: `agents/manipulation_agent.py`
- Test: `tests/unit/test_manipulation_lerobot_agent.py`

**Interfaces:**
- Consumes: normalized execution policy, specimen/vision handoffs, VLA profile/policy settings
- Produces: `manipulation_preflight.v1` and a safe controller handoff

- [x] Add a failing async test registering tripwire `lerobot.rollout.start` and `robot.pick_place` tools and assert the agent returns `execution_ready_pending_approval` without calling either.
- [x] Run the focused test and verify the current code reaches a rollout/pick-place call.
- [x] Return after payload construction and existing preflight validation when the policy is `preflight_only`, including `would_execute_tool` and `actuation_performed=false`.
- [x] Run the focused Manipulation tests.

### Task 3a: Vision no-capture transfer preflight

**Files:**
- Modify: `agents/vision_agent.py`
- Modify: `agents/manipulation_agent.py`
- Modify: `orchestrator/langgraph_runtime.py`
- Modify: `graphs/configs/atr_closed_loop.yaml`
- Test: `tests/unit/test_vision_agent.py`
- Test: `tests/unit/test_graph_specimen_pose_tracking.py`
- Test: `tests/unit/test_langgraph_runtime.py`

**Interfaces:**
- Consumes: verified printer preflight and printer/Manipulation `preflight_only` policy
- Produces: `vision_preflight.v1`, then routes the logical transfer to Manipulation without starting a camera runtime

- [x] Add camera/runtime/LLM tripwires and prove Vision returns before every capture path.
- [x] Emit a typed preflight without fabricating a detection or physical pickup readiness.
- [x] Allow Manipulation to consume it only under its own `preflight_only` policy.
- [x] Persist all device preflight records and route Manipulation preflight to Equipment rather than looping back to Vision.
- [x] Run focused Vision, Manipulation, graph, and runtime tests.

### Task 4: Lab Equipment agentic-flow preflight-only boundary

**Files:**
- Modify: `agents/equipment_agent.py`
- Test: `tests/unit/test_equipment_agent.py`

**Interfaces:**
- Consumes: saved `run_utm_compression_cycle` skill flow and normalized execution policy
- Produces: resolved step plan, `workflow_agentic_task`, and `equipment_preflight.v1`

- [x] Add a failing async test with a tripwire `equipment.pyautogui.run` and a complete saved flow; assert every block is resolved and no bridge execution occurs.
- [x] Run the test and confirm the current flow calls the bridge.
- [x] Add a preflight traversal that validates entry identity, flow revision, block bindings, program IDs, routes, timeouts, postconditions, Vision slots, and export context, then stops before the first execution.
- [x] Emit `execution_ready_pending_approval`, `actuation_performed=false`, and `ready_for_analysis=false` without a synthetic measured CSV.
- [x] Run focused Equipment flow tests.

### Task 5: Reference UTM corpus and calibrated CAE observation

**Files:**
- Create: `utils/utm_reference_calibration.py`
- Modify: `agents/analysis_agent.py`
- Modify: `device_bridges/cae_bridge.py`
- Modify: `configs/devices.yaml`
- Test: `tests/unit/test_utm_reference_calibration.py`
- Test: `tests/unit/test_analysis_agent.py`
- Test: `tests/unit/test_cae_tools.py`
- Test: `tests/unit/test_calculix_quasistatic.py`

**Interfaces:**
- Produces: `build_reference_calibration(paths: list[Path], *, target_strain: float) -> dict[str, Any]`
- Consumes: existing `parse_utm_csv`, candidate geometry/design parameters, optional calibration summary
- Produces: fingerprinted accepted/rejected corpus plus candidate-dependent 50% CAE energy-density prediction

- [x] Add failing tests with duplicate, flat-force, partial-coverage, and valid TrapeziumX/canonical fixtures.
- [x] Run them and confirm the calibration utility is absent.
- [x] Implement hash deduplication, parser-based quality gates, robust reference summaries, and explicit limitations.
- [x] Add a failing CAE test asserting exact 50% endpoint, frictionless/no-platen metadata, calibration provenance, and different predictions for different design candidates.
- [x] Pass the calibration summary through Analysis into CAE and expose a finite `energy_density_50pct_MJ_per_m3` for the deterministic quasi-static result.
- [x] Run focused calibration, CAE, and Analysis tests.

### Task 6: Analysis typed fidelity and BO proxy removal

**Files:**
- Modify: `agents/analysis_agent.py`
- Modify: `agents/bo_agent.py`
- Test: `tests/unit/test_analysis_agent.py`
- Test: `tests/unit/test_bo_agent.py`

**Interfaces:**
- Consumes: verified UTM observation or explicit calibrated CAE preflight observation
- Produces: exact-metric `bo_observation.v1` with `utm_high/measured` or `cae_mid/predicted`

- [x] Add a failing Analysis test proving explicit preflight mode accepts a complete calibrated CAE endpoint, while a failed physical UTM handoff does not fall back.
- [x] Implement the source-selection gate and exact-metric handoff.
- [x] Add failing BO tests proving proxy-only histories and mismatched metric names yield no training scores and a blocked result.
- [x] Remove generic `objective_score`, printability, SEA, and differently named metric fallbacks from BO training extraction while retaining nonnumeric failure context.
- [x] Run focused Analysis/BO tests.

### Task 7: Hardware-free multi-cycle acceptance

**Files:**
- Modify: `tests/integration/test_controller_run.py`
- Modify if needed: `app/controller.py`

**Interfaces:**
- Consumes: all typed preflight and exact-objective handoffs
- Produces: verified multi-cycle redesign trace

- [x] Add an integration test whose physical-tool registrations raise immediately if called.
- [x] Assert every cycle has printer, Vision, VLA, and UTM preflight evidence; calibrated CAE endpoint; ready exact-metric Analysis observation; ready BO request; and preserved execution policy.
- [x] Assert each BO recommendation's two design variables appear in the following Design spec at configured precision.
- [x] Run the new integration test and fix only contract gaps it exposes.
- [x] Run the focused agent/bridge/controller suite, then the complete safe-validation cycle test.
- [x] Inspect generated artifacts and verify no physical or network tool event occurred.

### Task 8: Independent safety-review closure

**Files:**
- Modify: `app/controller.py`
- Modify: `agents/vision_agent.py`
- Modify: `agents/manipulation_agent.py`
- Modify: `agents/equipment_agent.py`
- Modify: `agents/specimen_agent.py`
- Modify: `device_bridges/bambu_autoejection.py`
- Modify: `device_bridges/bambu_bridge.py`
- Modify: `device_bridges/prusa_bridge.py`
- Modify: `policies/validation_policy.py`
- Test: focused agent, bridge, graph, and contract suites

- [x] Make an existing partial policy fail closed for omitted physical stages while preserving legacy specs with no policy.
- [x] Require exact run/specimen lineage across printer → Vision → Manipulation → Equipment preflights.
- [x] Prevent Equipment explicit-skill/profile/legacy fall-through when no saved valid flow exists.
- [x] Prove the ejection tail follows the final extrusion, approaches at collision-safe Z, and survives independent post-write MD5/SHA validation.
- [x] Recheck local artifact SHA immediately before HTTP/FTPS transfer and print-start publication.
- [x] Represent a prepared-but-unprinted specimen as `preflight_ready`, not fabricated or blocked.
