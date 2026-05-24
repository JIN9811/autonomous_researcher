# Architecture

## Core flow

`FastAPI Controller -> RunLoop -> Stage Agent -> Autonomous Experiment Runtime / MCP Tool -> State Update -> Event Stream -> Web GUI`

The orchestrator uses explicit `Stage` enums and deterministic transitions to remain debuggable and resumable.

Live GUI handoff flow:

`Live GUI Chat -> MainController -> Design Agent -> Specimen Making Agent -> experiment.evaluate -> printer.prepare -> Guardian Agent`

This route reuses the same agents and tool contracts as the run loop, but presents the handoff as a conversation.
Tool-level runtime callbacks may stream progress back to the controller before an agent returns its final `AgentResult`.

The runtime-facing experiment API is documented in `runtime/autonomous_experiment_runtime.md`.
It standardizes `ExperimentObjective`, `ExperimentCandidate`, `ExperimentExecution`,
and `ExperimentEvaluationResult` so test, virtual, and live bridge paths remain externally consistent.

## Agent responsibilities

- `orchestrator_agent`: top-level planning text
- `bo_agent`: advisory BO/MBO optimizer for ExperimentObjective and candidate-parameter recommendation; exposed through `/bo` and executed as a sidecar after `knowledge_agent` and before `guardian_agent`. It consumes KnowledgeAgent context and writes next-cycle DesignAgent constraints to `run_metadata["bo_recommended_constraints"]`.
- `design/specimen/vision/manipulation/equipment/analysis/knowledge/guardian`: stage-specific execution
- `specimen_agent`: geometry/handoff owner plus printer preparation delegation; it does not directly implement PrusaLink write logic.
- `experiment.evaluate`: common evaluation facade that routes candidates through virtual scoring or a hardware bridge while preserving session/experiment IDs.
- `experiment.benchmark`: random/grid/BO comparison mode for objective and candidate-generation validation.
- `experiment.queue.status`: current device-job queue diagnostics for printer, robot, and Windows equipment actions.
- `/bo`: dedicated BO Workspace for acquisition function, BO/MBO strategy, budget, and parameter-space tuning.
- `/cae`: dedicated CAE Analysis Workspace for bottom-fixed/top-cyclic simulation settings and metric review.
- `printer.prepare`: internal PrusaSlicer/PrusaLink boundary for slicing, upload/start gates, and ejection gates.
- `vision_agent`: lightweight 3DP output-area observation owner. It combines `camera.capture` with the latest `specimen_result` and emits `pose_estimate`, `pickup_target`, and `transfer_readiness` for the robot transfer stage.
- `manipulation_agent`: robot manipulation owner. The compatibility path keeps `robot.pick_place`; the LeRobot path calls `lerobot.rollout.start`. After a ready `specimen_result`, the default transfer strategy is Pi0.5 LeRobot rollout from `3dp_output_area` to `utm_fixture` unless the spec explicitly requests `fixed_kinematic`. Operator-saved Manipulation Agent defaults are loaded from `memory/manipulation_agent_bridge.json` before each live/test loop execution, with explicit experiment fields taking precedence.
- `equipment_agent`: Lab Equipment owner. It uses `equipment.pyautogui.health`, `equipment.pyautogui.list_programs`, and `equipment.pyautogui.run` through the Windows PyAutoGUI Bridge, then hands `equipment_result` and `equipment_handoff` to Analysis.
- `analysis_agent`: UTM-data analysis owner. It extracts force/displacement curves from `equipment_result` inline data or CSV/JSON files, computes mechanical metrics and objective score, calls `cae.run_static_analysis` when available, uses deterministic synthetic UTM/CAE data only in test mode, and blocks live analysis when real UTM data is missing.
- `device_bridges/cae_bridge.py`: CAE bridge for CalculiX/Gmsh preflight plus deterministic equivalent bottom-fixed/top-cyclic analysis used by test-mode closed-loop scoring.
- `device_bridges/lerobot_bridge.py`: LeRobot / ROBOTIS bridge with deterministic test sessions, command previews, step traces, and live gates.
- `/lerobot`: dedicated Manipulation Agent / LeRobot GUI opened from the main dashboard. It contains device setup, teleoperation, recording, training, direct rollout, and an agent-mediated `Manipulation Agent Bridge` panel.

SARM logic is embedded inside `manipulation_agent` under `submodules/sarm`.

LeRobot naming and rollout-duration rules are centralized in `runtime/lerobot_dataset_policy_naming.md`. Manipulation Agent passes intent fields such as `rollout_dataset_repo_id`, `continuous_rollout`, and `policy_type`; the bridge enforces `eval_` rollout dataset names for legacy rollout datasets, manual-stop conversion, and Pi0.5 runtime selection.
