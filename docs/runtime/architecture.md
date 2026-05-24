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
- `design/specimen/vision/manipulation/equipment/analysis/knowledge/guardian`: stage-specific execution
- `specimen_agent`: geometry/handoff owner plus printer preparation delegation; it does not directly implement PrusaLink write logic.
- `experiment.evaluate`: common evaluation facade that routes candidates through virtual scoring or a hardware bridge while preserving session/experiment IDs.
- `experiment.benchmark`: random/grid/BO comparison mode for objective and candidate-generation validation.
- `experiment.queue.status`: current device-job queue diagnostics for printer, robot, and Windows equipment actions.
- `printer.prepare`: internal PrusaSlicer/PrusaLink boundary for slicing, upload/start gates, and ejection gates.
- `manipulation_agent`: robot manipulation owner. The default path keeps `robot.pick_place`; the LeRobot path calls `lerobot.rollout.start` when the experiment spec requests `lerobot_policy` or contains LeRobot policy/profile fields.
- `device_bridges/lerobot_bridge.py`: LeRobot / ROBOTIS bridge with deterministic test sessions, command previews, step traces, and live gates.
- `/lerobot`: dedicated teleoperation, recording, training, and rollout GUI opened from the main dashboard.

SARM logic is embedded inside `manipulation_agent` under `submodules/sarm`.

LeRobot naming and rollout-duration rules are centralized in `runtime/lerobot_dataset_policy_naming.md`. Manipulation Agent passes intent fields such as `rollout_dataset_repo_id` and `continuous_rollout`; the bridge enforces `eval_` rollout dataset names and manual-stop conversion.
