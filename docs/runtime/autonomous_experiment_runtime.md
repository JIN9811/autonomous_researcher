# Autonomous Experiment Runtime

## Purpose

The Autonomous Experiment Runtime is the standard execution layer above the
existing agents and MCP tools.

It improves the current system without replacing the established structure:

`Orchestrator/Live GUI -> Agent -> experiment.evaluate -> MCP Tool/Bridge -> Job Queue -> Result`

Existing tool names such as `printer.prepare`, `lerobot.record.start`, and
`equipment.pyautogui.run` remain valid. The new runtime adds a common
experiment contract, queue metadata, and benchmark entry points.

## Standard Interface

Core schema location:

`experiments/schemas.py`

Primary objects:

- `ExperimentObjective`: measurable goal, metric name, direction, constraints.
- `ExperimentCandidate`: concrete parameters and/or `experiment_spec`.
- `ExperimentExecution`: mode, bridge, dry-run flag, physical-action gate.
- `ExperimentEvaluationRequest`: full request passed from agents or GUI.
- `ExperimentEvaluationResult`: common result for test, virtual, and live runs.

Tool entry points:

- `experiment.evaluate`
- `experiment.benchmark`
- `experiment.queue.status`

Agent/UI entry points:

- `bo_agent`
- `/bo` BO Workspace

## Naming

Use system-native names in user-facing docs and GUI:

- Runtime layer: `Autonomous Experiment Runtime`
- Single execution: `Experiment Evaluation`
- Candidate proposal comparison: `Experiment Benchmark`
- Queue record: `Device Job`
- Physical/logical session: `Session ID`
- Research run: `Experiment ID`

Avoid importing external benchmark naming directly. External concepts such as
frugal twins, virtual runs, or optimization baselines should be described as
improvements to this project's runtime.

## Mode Contract

The public API is intentionally uniform:

| Mode | Bridge | Expected behavior |
|---|---|---|
| `test` | `virtual` | No hardware write. Deterministic objective calculation. |
| `test` | `printer` | Slice/upload/start boundary can be checked through configured test path. |
| `live` | `printer` | Uses existing live gates, PrusaLink connection memory, and physical-start flags. |
| `virtual` | `virtual` | Pure evaluator path for benchmark and BO comparison. |
| `replay` | `analysis` | Reserved for replaying existing records without hardware writes. |

Safety rule:

The unified API does not bypass bridge-specific gates. Physical actions are
still enforced inside each device bridge, especially PrusaLink start/ejection
and LeRobot live execution gates.

## Device Job Queue

`mcp_tools.tool_registry.ToolRegistry` now supports optional device assignment.
When a tool is registered with a device name, the call is serialized through
`experiments.job_queue.DeviceJobQueue`.

Queued hardware-facing tools:

- `printer.prepare` -> `printer:prusa_mk4s`
- `equipment.pyautogui.run` -> `equipment:windows_pyautogui`
- `lerobot.teleoperate.start` -> `robot:lerobot`
- `lerobot.record.start` -> `robot:lerobot`
- `lerobot.train.start` -> `robot:lerobot`
- `lerobot.rollout.start` -> `robot:lerobot`
- `lerobot.visualize.start` -> `robot:lerobot`

Each queued result receives:

- `job_id`
- `job.device`
- `job.tool`
- `job.experiment_id`
- `job.session_id`
- `job.queued_at`
- `job.started_at`
- `job.finished_at`
- `job.queue_wait_sec`
- `job.status`

Queue diagnostics:

```python
ctx.tools.call("experiment.queue.status", {})
```

## Specimen Making Integration

`SpecimenMakingAgent` now evaluates printer preparation through:

`experiment.evaluate -> printer.prepare`

The existing `printer.prepare` response is still exposed as
`specimen_result.tool_result`, and the standard runtime result is attached as:

`specimen_result.experiment_evaluation`

This preserves the previous GUI and bridge behavior while adding a common
Experiment Evaluation record for logs, benchmark comparison, and future report
generation.

## Benchmark Mode

`experiment.benchmark` compares proposal strategies over the same objective:

- `random`
- `grid`
- `bo`

`bo_agent` wraps this benchmark tool with system-specific settings:

- strategy: `random`, `grid`, `bo`, `mbo`
- acquisition: `expected_improvement`, `upper_confidence_bound`,
  `probability_of_improvement`, `uncertainty_sampling`, `exploitation`,
  `exploration`
- recommendation: candidate parameter payload that can later be merged into
  Design Agent constraints.

The benchmark output includes per-strategy:

- raw evaluation results
- best score
- best candidate ID
- best-so-far curve

Default benchmark execution should use `virtual` mode unless the operator
explicitly requests live hardware evaluation.

## Extension Rules

When adding a new hardware bridge:

1. Keep the bridge-specific MCP tool intact.
2. Register write/start actions with a device name.
3. Add a route in `ExperimentRuntime` only if the bridge needs a specialized
   objective interpretation.
4. Preserve `ExperimentEvaluationResult` field names.
5. Add at least one virtual/test unit test before live testing.
