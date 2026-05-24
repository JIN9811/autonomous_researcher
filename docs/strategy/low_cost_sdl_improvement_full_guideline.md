# Low-Cost SDL Improvement Full Runtime Guideline

Source basis:
- `/home/jin/다운로드/codex_improvement_instructions.txt`
- `docs/project/Project_guide.txt`
- `docs/runtime/architecture.md`
- `docs/runtime/test_mode.md`
- `docs/process/codex_workflow.md`
- `docs/runtime/agent_program_baseline.md`
- `docs/agents/specimen_design_existing_runtime_guideline.txt`
- `docs/hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt`

Purpose:
- Convert the current autonomous researcher demo/runtime into a measurable, reproducible, closed-loop low-cost self-driving lab framework.
- Keep all existing runtime contracts intact.
- Implement improvements as bounded, testable changes.
- Prefer quantitative evidence, logs, metrics, replayability, and fault-injection coverage over narrative claims.

Current repository mapping:
- API/runtime controller: `app/controller.py`, `app/main.py`, `app/bootstrap.py`
- Main stage loop: `orchestrator/run_loop.py`
- Stage definitions/transitions: `orchestrator/state.py`, `orchestrator/transitions.py`, `orchestrator/router.py`
- Stage agents: `agents/*.py`
- Tool layer: `mcp_tools/*.py`
- Device bridges: `device_bridges/*.py`, `device_bridges/simulator/*.py`
- LLM/vLLM/NemoClaw backends: `backends/*.py`, `deploy/nemoclaw-vllm.yaml`
- Existing learning primitives: `learning/*.py`
- Existing policy primitives: `policies/*.py`
- Memory/knowledge: `memory/*.py`, `knowledge/*.py`
- Logging/event stream: `logging_system/*.py`
- Web GUI: `web/templates/*`, `web/static/*`
- Legacy/local GUI modules: `gui/*`
- Tests: `tests/unit`, `tests/integration`, `tests/fault_injection`, `tests/replay`

Known implemented baseline:
- Stage topology exists and must not be renamed.
- Live GUI chat handoff exists.
- Specimen design and STL generation path exists.
- PrusaBridge Phase 1 exists with test virtual bridge, live connection memory, and gated physical printer actions.
- Live GUI test-mode printer path question is handled by `SpecimenMakingAgent`.
- `printer.prepare` remains the internal printer tool boundary; do not add a new top-level printer stage.
- Design Agent owns Live GUI STL artifact rendering.
- Specimen Making Agent owns PrusaSlicer/PrusaLink runtime visibility, including slicer settings, G-code path, endpoint shape, gate result, and step trace.

============================================================
0. Non-Negotiable Runtime Contracts
============================================================

Do not break this topology:

`FastAPI Controller -> RunLoop -> Stage Agent -> MCP Tool -> State Update -> Event Stream -> Web GUI`

Preserve stage order:
1. `design`
2. `specimen`
3. `vision`
4. `manipulation`
5. `equipment`
6. `analysis`
7. `knowledge`
8. `guardian`
9. `guardian=continue -> design`
10. `guardian=stop -> complete`
11. `guardian=error -> error`

Do not rename:
- `Stage` enum values in `orchestrator/state.py`
- Existing tool names unless all agent code and tests are updated in the same change set
- Existing required `AgentResult.data` keys

Required `AgentResult.data` keys to preserve:
- design stage: `experiment_spec`
- vision stage: `observation`
- analysis stage: `analysis`
- guardian stage: `guardian`

Tool names to preserve:
- `printer.prepare`
- `camera.capture`
- `robot.pick_place`
- `utm.run_protocol`
- `device.health`

SARM rule:
- Do not turn SARM into a top-level agent.
- Keep SARM inside `manipulation_agent` or `submodules/sarm`.

Hardware-facing rule:
- Every hardware-facing component must remain executable in:
  - test mode
  - replay mode
  - fault-injection mode
- Physical write actions must remain gated.
- Test mode must not depend on real hardware unless the operator explicitly selects a real communication test path.

Codex implementation rule:
1. Implement exactly one bounded modification at a time.
2. Add or update tests in the same change.
3. Run targeted tests after each modification.
4. Run relevant integration/replay/fault tests when affected.
5. Inspect logs/events when runtime behavior changes.
6. Repair and re-run until verified.

============================================================
1. Improvement Area A: Measurable Low-Cost Validation
============================================================

Problem:
- The system must quantify whether the low-cost setup is reliable enough for SDL operation.
- It is not enough to automate a demo; the runtime must record success rate, repeatability, cycle time, intervention rate, and hardware failure modes.

Objective:
- Add a metrics subsystem that records low-cost SDL validation records for every completed run.
- Metrics must work in test mode using synthetic/mock outputs.
- Metrics must be written to disk in JSONL format.

Required metrics:
- `full_loop_success_rate`
- `specimen_print_success_rate`
- `auto_ejection_success_rate`
- `robot_pick_success_rate`
- `robot_place_success_rate`
- `transfer_success_rate`
- `camera_pose_detection_success_rate`
- `utm_protocol_success_rate`
- `human_intervention_count`
- `cycle_time_sec`
- `retry_count_by_stage`
- `safe_stop_count`
- `hardware_error_count`
- `cost_per_successful_run_krw`
- `autonomous_fraction`

Add files:
- `metrics/__init__.py`
- `metrics/schemas.py`
- `metrics/low_cost_validation.py`
- `metrics/aggregator.py`
- `metrics/report_writer.py`

Update files:
- `orchestrator/run_loop.py`
- optionally `logging_system/event_logger.py`
- optionally `app/controller.py` if run completion is easier to hook there
- tests under `tests/unit`, `tests/integration`, `tests/fault_injection`, `tests/replay`

Output path:
- `research/metrics/low_cost_validation.jsonl`
- `research/metrics/low_cost_validation_summary.md`

Minimum metric record fields:
- `run_id`
- `experiment_id`
- `mode`
- `started_at`
- `completed_at`
- `final_stage`
- `full_loop_success`
- `stage_success`
- `stage_failures`
- `retry_count_by_stage`
- `safe_stop_count`
- `hardware_error_count`
- `human_intervention_count`
- `cycle_time_sec`
- `autonomous_fraction`
- `printer`
- `vision`
- `manipulation`
- `equipment`
- `analysis`
- `guardian`

Behavior:
- On run completion or run error, append exactly one metric record.
- Test mode must create a record without real hardware.
- Fault-injection mode must record the injected failure and affected hardware metric.
- Replay mode must be able to regenerate a summary from persisted records/events.

Acceptance tests:
- Unit: metric schema validation passes.
- Unit: aggregator computes success rates from multiple JSONL records.
- Integration: a full test-mode run produces one metric record.
- Fault: injected robot failure increments manipulation/hardware failure metrics.
- Replay: replayed run can regenerate the same metric summary.

First implementation priority:
- Implement this area before closed-loop optimization, VLA benchmark, GUI reporting, or ResearchOps master tracking.

============================================================
2. Improvement Area B: VLA Necessity Benchmark
============================================================

Problem:
- VLA usefulness must be demonstrated against simpler manipulation baselines.
- Without controlled comparison, VLA can appear unnecessary or over-engineered.

Objective:
- Add a benchmark framework that compares manipulation strategies under controlled specimen pose and environment variation.

Strategies:
1. `fixed_kinematic`
   - Fixed pick/place coordinates.
   - No camera correction.
2. `vision_pose_correction`
   - Uses camera observation and pose estimation.
   - Applies deterministic correction.
3. `vla_policy`
   - Uses a VLA-style policy interface.
   - May be mocked initially, but must allow real policy integration later.

Scenario variables:
- `specimen_initial_x_offset_mm`
- `specimen_initial_y_offset_mm`
- `specimen_rotation_deg`
- `lighting_condition`
- `camera_noise_level`
- `ejection_position_variability`
- `gripper_offset_mm`

Metrics:
- `grasp_success_rate`
- `place_success_rate`
- `recovery_success_rate`
- `mean_task_time_sec`
- `collision_or_near_miss_count`
- `retry_count`
- `final_pose_error_mm`
- `failure_reason_distribution`

Add files:
- `benchmarks/__init__.py`
- `benchmarks/manipulation_benchmark.py`
- `benchmarks/manipulation_scenarios.yaml`
- `benchmarks/result_schemas.py`
- `benchmarks/report_manipulation.py`

Update files:
- `agents/manipulation_agent.py`
- `device_bridges/simulator/robot_sim.py`
- `device_bridges/simulator/camera_sim.py`
- `submodules/vla/` when real VLA integration is added

Output paths:
- `research/benchmarks/manipulation_runs.jsonl`
- `research/benchmarks/manipulation_summary.json`

Example command:

```bash
python -m benchmarks.manipulation_benchmark \
  --mode test \
  --strategies fixed_kinematic vision_pose_correction vla_policy \
  --scenario-file benchmarks/manipulation_scenarios.yaml
```

Acceptance tests:
- Unit: each strategy implements the same interface.
- Unit: scenario parser validates variable ranges.
- Integration: benchmark runs all three strategies in simulator mode.
- Fault: camera noise or grasp failure creates expected failure records.
- Report: summary computes per-strategy success rate and final pose error.

Implementation timing:
- Do after metrics foundation exists, so benchmark results can share metrics/reporting conventions.

============================================================
3. Improvement Area C: True Closed-Loop SDL Optimization
============================================================

Problem:
- A single automated run is not a full SDL.
- The loop must propose candidate, execute, analyze objective, update model, and propose the next candidate.

Objective:
- Strengthen a closed-loop engine connecting Design, Analysis, Knowledge, and Guardian.

Required loop:
1. Load prior experiment memory.
2. Generate candidate design/process condition.
3. Execute specimen/vision/manipulation/equipment stages.
4. Extract physical objective from UTM result or synthetic test result.
5. Update surrogate/BO/active-learning state.
6. Select next candidate.
7. Stop on budget, safety, convergence, max loop count, or Guardian decision.

Add files:
- `research_ops/run_context.py`
- `research_ops/results_ledger.py`
- `research_ops/promotion_gate.py`
- `learning/objective_registry.py`
- `learning/closed_loop_driver.py`
- `learning/candidate_selector.py`

Update files:
- `agents/design_agent.py`
- `agents/analysis_agent.py`
- `agents/knowledge_agent.py`
- `agents/guardian_agent.py`
- `orchestrator/run_loop.py`
- `memory/experiment_db.py`
- `configs/system.yaml`

Design output extension:
- Keep `experiment_spec` unchanged.
- Add optional `research_meta` alongside or inside `experiment_spec`.

Example:

```json
{
  "experiment_spec": {
    "specimen_id": "specimen_0007",
    "geometry_id": "lattice_a",
    "print_profile": "profile_default",
    "utm_profile": "compression_v1"
  },
  "research_meta": {
    "run_type": "science_experiment",
    "hypothesis": "Increasing relative density may increase specific energy absorption while preserving acceptable print time.",
    "candidate_source": "bayesian_optimization",
    "target_objective": "specific_energy_absorption_j_per_g",
    "constraints": {
      "max_print_time_min": 120,
      "max_human_intervention_count": 0,
      "safe_stop_required_on_anomaly": true
    }
  }
}
```

Analysis output extension:
- Keep `analysis` unchanged.
- Add objective values and uncertainty inside `analysis`.

Guardian output extension:
- Keep `guardian` unchanged.
- Add loop decision and promotion decision inside `guardian`.

Acceptance tests:
- Unit: candidate selector returns a valid candidate within constraints.
- Unit: objective extraction handles missing or malformed result files.
- Integration: three-cycle test-mode SDL loop records objective trend.
- Replay: closed-loop trajectory can be replayed from stored events.
- Guardian: unsafe/anomalous candidate is rejected before hardware stage.

Implementation timing:
- Do after metrics, objective registry, and ResearchOps ledger exist.

============================================================
4. Improvement Area D: Metamaterial Objective Formalization
============================================================

Problem:
- The experimental domain needs clear objective definitions.
- BO/active learning cannot optimize meaningful outcomes without formal objective definitions.

Objective:
- Add an objective registry for energy-absorbing metamaterial experiments.

Primary objective candidates:
- `specific_energy_absorption_j_per_g`
- `energy_absorption_j`
- `plateau_stress_mpa`
- `peak_force_n`
- `densification_strain`
- `stiffness_n_per_mm`
- `recoverability_ratio`
- `mass_g`
- `print_time_min`

Multi-objective examples:
1. Maximize `specific_energy_absorption_j_per_g` subject to `print_time_min <= threshold`.
2. Maximize `energy_absorption_j`, minimize `mass_g`, constrain `peak_force_n <= threshold`.
3. Maximize plateau stress stability and minimize failure variability.

Add files:
- `learning/objective_registry.py`
- `learning/metamaterial_objectives.py`
- `learning/utm_curve_features.py`
- `configs/objectives.yaml`

Update files:
- `agents/analysis_agent.py`
- `learning/evaluation.py`
- tests under `tests/unit/test_objectives.py`

Required UTM curve features:
- `force_n`
- `displacement_mm`
- `stress_mpa`
- `strain`
- `absorbed_energy_j`
- `mass_g`
- `specific_energy_absorption_j_per_g`
- `peak_force_n`
- `plateau_stress_mpa`
- `densification_strain`

Behavior:
- Objectives must be registered by name.
- Each objective must specify input fields, units, direction, and constraints.
- `AnalysisAgent` must use the objective registry rather than hard-coded metric names.
- Missing inputs must produce structured errors.

Acceptance tests:
- Unit: objective registry loads `configs/objectives.yaml`.
- Unit: UTM feature extraction computes absorbed energy from force-displacement data.
- Unit: missing `mass_g` blocks specific energy absorption with structured error.
- Integration: analysis stage emits objective block with primary and secondary metrics.

============================================================
5. Improvement Area E: Replicates, Uncertainty, Reproducibility
============================================================

Problem:
- Single physical experiments are noisy.
- The runtime must distinguish true improvement from noise, manipulation failure, and measurement variation.

Objective:
- Add replicate planning, uncertainty recording, and reproducibility checks.

Required fields:
- `replicate_count`
- repeated UTM test records where appropriate
- `material_batch_id`
- `print_profile_id`
- `specimen_geometry_id`
- `specimen_mass_g`
- `camera_calibration_id`
- `robot_calibration_id`
- `utm_protocol_id`
- `environment_notes`

Add files:
- `research_ops/replicate_policy.py`
- `research_ops/reproducibility.py`
- `memory/specimen_registry.py`

Update files:
- `agents/design_agent.py`
- `agents/specimen_agent.py`
- `agents/analysis_agent.py`
- `memory/experiment_db.py`

Behavior:
- Design may request replicates based on uncertainty or promotion requirements.
- Analysis must summarize replicate mean, standard deviation, and confidence/uncertainty.
- Guardian may require additional replicate before promotion.

Acceptance tests:
- Unit: replicate policy requests additional replicate when uncertainty is high.
- Unit: analysis aggregates replicate metrics correctly.
- Integration: science master is not promoted if replicate requirement is unmet.

============================================================
6. Improvement Area F: Safety and Physical Failure Handling
============================================================

Problem:
- Physical SDL failures can damage hardware or invalidate results.
- Safety conditions must be explicit, testable, and visible.

Objective:
- Strengthen Guardian and policies for hardware safety, anomaly detection, and safe-stop.

Required checks:
- device health before hardware stages
- robot workspace boundary
- gripper force/load sanity, if available
- camera observation validity
- specimen pose confidence threshold
- UTM ready-state
- UTM emergency stop/safe-stop path
- printer/ejection status
- unexpected human intervention, if observable

Add files:
- `policies/physical_safety_policy.py`
- `policies/anomaly_policy.py`
- `policies/promotion_policy.py`

Update files:
- `agents/guardian_agent.py`
- `agents/vision_agent.py`
- `agents/manipulation_agent.py`
- `agents/equipment_agent.py`
- `mcp_tools/*_tools.py`
- `tests/fault_injection/*`

Behavior:
- Guardian must reject or safe-stop when critical safety checks fail.
- Fault-injection tests must cover printer failure, camera disconnect, grasp failure, UTM not ready, model timeout, and malformed tool output.
- Safety failures must be logged into failure memory.

Acceptance tests:
- Fault: camera disconnect triggers safe-stop or retry according to policy.
- Fault: UTM not ready blocks equipment stage.
- Fault: malformed tool output does not crash the run loop.
- Unit: Guardian decision is deterministic for identical policy inputs.

============================================================
7. Improvement Area G: ResearchOps Ledger and Master Tracking
============================================================

Problem:
- The system needs a durable record of what was tried, what failed, and what should be considered the current best configuration or experiment condition.

Objective:
- Add ResearchOps records for runtime changes and science experiment results.

Distinction:
- `runtime_master`: best validated software/agent/config/prompt/runtime version.
- `science_master`: best validated experimental condition/specimen/protocol candidate.

Add files:
- `research_ops/__init__.py`
- `research_ops/schemas.py`
- `research_ops/master_registry.py`
- `research_ops/ledger.py`
- `research_ops/proposal_validator.py`
- `research_ops/duplicate_checker.py`
- `research_ops/promotion_gate.py`
- `research/runtime_master.json`
- `research/science_master.json`
- `research/results.jsonl`
- `research/do_not_repeat.md`

Minimum run record fields:
- `run_id`
- `timestamp`
- `mode`
- `run_type`
- `parent_runtime_master`
- `parent_science_master`
- `hypothesis`
- `experiment_spec`
- `research_meta`
- `stage_path`
- `primary_metric`
- `secondary_metrics`
- `failure_modes`
- `guardian_decision`
- `promotion_status`

Behavior:
- Every run should be append-only recorded.
- Duplicate or near-duplicate experiments should be flagged.
- Failed experiments should update `do_not_repeat.md` or failure memory.
- Promotion must not happen automatically unless required tests, metrics, and constraints pass.

Acceptance tests:
- Unit: ledger appends valid JSONL and rejects malformed records.
- Unit: master registry reads/writes runtime and science masters.
- Unit: duplicate checker flags exact repeated candidate.
- Integration: completed test-mode run writes `research/results.jsonl`.
- Integration: Guardian promotion decision updates only the intended master.

============================================================
8. Improvement Area H: GUI/API Visibility for Validation Status
============================================================

Problem:
- The GUI should show whether the system is merely running or actually improving.
- Researchers need visibility into metrics, objective trend, failures, and promotion decisions.

Objective:
- Add API and GUI surfaces for validation metrics and ResearchOps state.

Current GUI mapping:
- API route additions belong in `app/main.py`.
- Controller data access belongs in `app/controller.py`.
- Current browser Live GUI uses `web/static/*.js`, `web/static/*.css`, and `web/templates/*.html`.
- `gui/panels` and `gui/viewmodels` exist, but browser GUI changes should not assume those are active unless verified.

Suggested additions:
- API: `/api/research/master`
- API: `/api/research/results`
- API: `/api/research/metrics`
- GUI section: Master / Promotion status
- GUI section: Objective trend
- GUI section: Low-cost validation metrics
- GUI section: Fault/replay status

Displayed fields:
- current `runtime_master`
- current `science_master`
- active `run_id`
- parent masters
- hypothesis
- target objective
- latest objective value
- objective trend
- full-loop success rate
- robot pick success rate
- human intervention count
- current Guardian decision
- promotion status
- latest failure reason

Acceptance tests:
- API: `/api/research/master` returns both masters.
- API: `/api/research/results` returns recent records.
- API: `/api/research/metrics` returns summary even when records are missing.
- GUI viewmodel/render test handles missing metrics without crashing.
- Integration: completed test-mode run appears in experiment memory/validation view.

Implementation timing:
- Do after metrics and ResearchOps ledger exist.

============================================================
9. Improvement Area I: Paper/Report-Ready Evidence Generation
============================================================

Problem:
- Evidence should be quantitative and reproducible.
- Reports should be generated from persisted records, not ad-hoc narrative.

Objective:
- Add report generation for runs, benchmarks, closed-loop optimization, and failure summaries.

Report artifacts:
- cost summary
- full-loop success summary
- manipulation benchmark comparison
- objective improvement curve
- failure mode distribution
- replicate uncertainty table
- hardware/test/replay status summary

Add files:
- `reporting/__init__.py`
- `reporting/run_report.py`
- `reporting/benchmark_report.py`
- `reporting/research_summary.py`

Output paths:
- `reports/latest_run_summary.md`
- `reports/manipulation_benchmark_summary.md`
- `reports/closed_loop_summary.md`

Acceptance tests:
- Report generation works from JSONL files only.
- Report generation works in test mode.
- Report includes run_id and source file paths for traceability.

============================================================
10. Recommended Implementation Phases
============================================================

Phase 1: Measurement foundation
- Add metric schemas and `low_cost_validation.jsonl` writer.
- Add full-loop test-mode metric output.
- Add unit, integration, fault, and replay coverage.

Phase 2: Objective formalization
- Add `configs/objectives.yaml`.
- Add objective registry and UTM curve feature extraction.
- Connect `AnalysisAgent` to objective registry.

Phase 3: ResearchOps ledger
- Add `research/results.jsonl`, `runtime_master.json`, `science_master.json`.
- Add proposal validation and promotion gate.
- Add duplicate checker.

Phase 4: Closed-loop SDL
- Connect Design -> Analysis -> Knowledge -> Guardian into multi-cycle optimization.
- Add candidate selector and closed-loop driver.

Phase 5: Manipulation benchmark
- Add fixed kinematic, vision pose correction, and VLA policy strategy interfaces.
- Add simulator scenario sweep and benchmark reports.

Phase 6: Reproducibility and replicates
- Add replicate policy and uncertainty handling.
- Add promotion requirements based on replicate confidence.

Phase 7: GUI/API/reporting
- Add master/promotion API and panel.
- Add objective trend and validation metrics panels.
- Add report generation from ledger and benchmark records.

============================================================
11. Default Codex Task Template
============================================================

Task:
- Implement exactly one bounded improvement from this guideline.

Read first:
- `docs/project/Project_guide.txt`
- `docs/runtime/architecture.md`
- `docs/runtime/test_mode.md`
- `docs/process/codex_workflow.md`
- `docs/runtime/agent_program_baseline.md`
- this guideline
- relevant target modules

Constraints:
- Do not rename `Stage` enum values.
- Do not change required `AgentResult.data` keys.
- Do not rename ToolRegistry tool names.
- Do not make SARM a top-level agent.
- Preserve full test-mode execution.
- Preserve replay/fault-injection behavior for affected hardware paths.
- Add or update tests in the same change.

Implementation steps:
1. Inspect relevant files.
2. Write a short plan.
3. Implement the smallest safe change.
4. Run targeted unit tests.
5. Run relevant integration/replay/fault tests if affected.
6. Inspect logs/events when runtime behavior changes.
7. Repair failures.
8. Summarize modified files, tests run, and remaining risks.

Completion criteria:
- Tests pass.
- Existing runtime contracts remain intact.
- New behavior works in test mode.
- Logs include `run_id` or `experiment_id` where relevant.
- No hidden hardware dependency is introduced.

Preferred test command pattern:

```bash
/home/jin/autonomous_researcher/.venv/bin/pytest tests -q
```

Use narrower tests first, then full tests:

```bash
/home/jin/autonomous_researcher/.venv/bin/pytest tests/unit/<target>.py -q
/home/jin/autonomous_researcher/.venv/bin/pytest tests/integration/<target>.py -q
/home/jin/autonomous_researcher/.venv/bin/pytest tests -q
```

============================================================
12. First Recommended Implementation Task
============================================================

Implement the measurement foundation first.

Task:
- Add a low-cost SDL validation metrics subsystem.

Concrete requirements:
1. Create `metrics/schemas.py` with typed schemas for stage outcomes and low-cost validation metrics.
2. Create `metrics/low_cost_validation.py` with functions to build one metric record from run state/events.
3. Create `metrics/aggregator.py` to compute success rates from JSONL records.
4. Create `metrics/report_writer.py` to write compact Markdown summaries.
5. Update `orchestrator/run_loop.py` or `app/controller.py` so a completed test-mode run writes one record to `research/metrics/low_cost_validation.jsonl`.
6. Add unit tests for schema and aggregation.
7. Add one integration test proving a full test-mode dry run writes a metric record.
8. Add one fault-injection test proving a simulated robot failure is counted.

Do not implement in this first task:
- Objective optimization.
- VLA benchmark.
- GUI panels.
- ResearchOps master promotion.
- Closed-loop candidate selector.

Recommended minimal implementation details:
- Use append-only JSONL.
- Create parent directories automatically.
- Derive stage outcomes from `RunLoop` events and `OrchestratorState`.
- Store raw counts plus derived summary fields.
- Keep hardware-specific metrics nullable or false in test mode when no corresponding stage/tool result exists.
- Include `schema_version`.

Recommended first-test set:
- `tests/unit/test_low_cost_metrics.py`
- `tests/integration/test_controller_run.py`
- `tests/fault_injection/test_fault_mode.py`

Expected risk:
- `RunLoop` currently emits final events but does not own a persistent metrics writer.
- The safest hook is likely at the end of `RunLoop.run()` after final event emission, or in `MainController` after run task completion.
- Avoid making metric writing crash a run; metric writer failures should be logged and surfaced, not treated as hardware execution failures.
