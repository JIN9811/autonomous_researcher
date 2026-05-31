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

### 2026-05-29 Specimen Fabrication Report Contract

`SpecimenMakingAgent` still calls `experiment.evaluate -> printer.prepare`, but it now wraps the result in:

- `fabrication_report.v1`: fabrication intent, digital thread, process plan, quality gates, printer runtime evidence, monitoring handoff, outcome, and feedback to Design/Knowledge/BO.
- `specimen_fabricated.v1`: handoff packet consumed by Vision, Manipulation, Knowledge, and BO. It references the full `fabrication_report` and includes only a compact fabrication summary plus evidence refs.

The runtime merge layer stores these under `state.run_metadata.fabrication_report`, `state.run_metadata.specimen_fabricated`, `state.run_metadata.specimen_handoff_packet`, `state.run_metadata.specimen_decision_register`, and `state.run_metadata.specimen_metrics`. The generic `handoff_packets` registry also receives the specimen packet.

This keeps the printer bridge deterministic while making the manufacturing stage auditable as a digital-thread node.

### 2026-05-29 Vision Perception Signal Contract

`VisionAgent` now preserves the legacy `observation` contract while adding a
structured lab perception layer:

- `vision_report.v1`: scene task, camera source, zone state, detections, visual
  events, signal board, artifacts, dataset ledger, Knowledge payload, and safety
  anomaly summary.
- `vision_signal.v1`: downstream handoff packet for Manipulation, Knowledge,
  Guardian, and future Equipment cross-checks. It includes freshness fields
  (`timestamp`, `expires_at`, `stable_for_ms`) and evidence refs.

The runtime merge layer stores these under `state.run_metadata.vision_report`,
`state.run_metadata.vision_signal`, `state.run_metadata.vision_handoff_packet`,
`state.run_metadata.vision_decision_register`, and `state.run_metadata.vision_metrics`.
The generic `handoff_packets` registry also receives the Vision signal packet.

Manipulation rejects expired Vision signals before issuing robot commands. Vision
remains an observer/signal agent and does not execute hardware actions.

### 2026-05-29 Manipulation Report and Robot Task Result Contract

`ManipulationAgent` now preserves the legacy `manipulation` and `sarm` keys but
also emits:

- `manipulation_report.v1`: bounded task, policy plan, preflight, Vision context,
  rollout runtime, stage machine, SARM-lite state, decision, Knowledge payload,
  and handoff packet.
- `robot_task_result.v1`: compact downstream packet with task/skill/episode IDs,
  terminal pose, handoff status, completion status, preflight, SARM, decisions,
  warnings, and evidence refs.

The runtime merge layer stores these under:

- `state.run_metadata.manipulation_report`
- `state.run_metadata.robot_task_result`
- `state.run_metadata.manipulation_handoff_packet`
- `state.run_metadata.manipulation_decision_register`
- `state.run_metadata.manipulation_metrics`

The generic `handoff_packets` registry also receives `robot_task_result.v1`.
Physical handoff remains Vision-gated: successful LeRobot rollout can produce
`reported_complete`, but final downstream progression should wait for the
appropriate Vision verification signal when available.

### 2026-05-30 Knowledge Memory and Self-Evolution Evidence Contract

`KnowledgeAgent` now preserves legacy `MemoryRecord` writes while adding file-backed typed research memory:

- `knowledge_context.v1`: hot/episodic/semantic/evolution/archival memory summary for downstream agents.
- `knowledge_report.v1`: Live GUI report payload with memory ledger, retrieval panel, failure/success library, agent performance memory, data quality map, and self-evolution board.
- `experiment_knowledge_v1`: experiment-level memory with parameters, metrics, quality flags, artifact refs, and provenance.
- `agent_performance_v1`: per-agent ledger with missing fields, warnings, retry count, artifact completeness, and evolution hint.
- `failure_pattern_v1` / `success_pattern_v1`: reusable pattern memory.
- `evolution_evidence_pack_v1`: task prefill and evidence contract consumed by `SelfEvolutionService`.

Per-run artifacts are written to `runs/<run_id>/knowledge/`, and long-term JSONL memory is written to `memory/knowledge/`. The runtime merge layer stores the Knowledge payload under `state.run_metadata.knowledge`, so Live GUI reports and Evolution Lab can read the same evidence.

Self-evolution remains conservative: Knowledge recommends and prepares evidence, while `SelfEvolutionService`, Guardian gates, and operator approval control candidate validation and activation.


### 2026-05-31 Orchestration Supervisor Follow-up Contract

`OrchestratorAgent` is no longer treated as a keyword-only router. The runtime now records a deterministic supervisor layer around the existing graph execution without replacing the agent-specific packets.

New runtime records:

- `operator_intent.v1`: deterministic Live GUI intent extraction used before LLM fallback. It separates `ask_question`, `set_constraint`, `start_dry_run`, `start_live_run`, `select_option`, `request_status`, `pause`, `resume`, and `stop` instead of relying only on raw keyword matching.
- `experiment_contract.v1`: mission contract compiled from runtime state, operator intent, current specimen context, objective, constraints, and Guardian safety budget assumptions.
- `orchestration_plan.v1`: executable supervisor plan with ordered route steps, per-stage required outputs, read-only parallel checks, serial physical actions, expected artifacts, and control-plane ownership.
- `orchestrator_parallel_checks.v1`: async read-only supervisor check batch executed with `asyncio.gather`/thread offload for prior failure memory, FEM cache references, Guardian device health, BO/design constraints, artifact lookup, and previous-loop comparison. These checks must never actuate hardware.
- `orchestrator_followup.v1`: stage-level supervisor opinion with `opinion`, `confidence`, `concerns`, `recommendation`, optional operator choices, evidence refs, and response requirement.
- `decision_register.v1`: Orchestrator-owned routing/branch decision record with selected next stage, alternatives, reason, authority, and evidence refs.
- `handoff_packet.v1` under `state.run_metadata.orchestrator_handoff_packets`: compact Orchestrator handoff broker packet for the next stage. This does not overwrite agent-produced packets in `state.run_metadata.handoff_packets`.
- `loop_reflection.v1`: loop-level reflection created after Guardian review and stored under `state.run_metadata.loop_reflections` for Knowledge/Self-Evolution use.

Runtime storage keys:

- `state.run_metadata.mission_contract` / `state.run_metadata.latest_mission_contract`
- `state.run_metadata.orchestration_plans` / `state.run_metadata.latest_orchestration_plan`
- `state.run_metadata.orchestrator_parallel_checks` / `state.run_metadata.latest_orchestrator_parallel_checks`
- `state.run_metadata.orchestrator_followups`
- `state.run_metadata.latest_orchestrator_followup`
- `state.run_metadata.orchestrator_decision_register`
- `state.run_metadata.latest_orchestrator_decision`
- `state.run_metadata.orchestrator_handoff_packets`
- `state.run_metadata.latest_orchestrator_handoff`
- `state.run_metadata.loop_reflections`
- `state.run_metadata.latest_loop_reflection`

Event stream additions:

- `orchestrator.followup`: emitted after stage results, Guardian blocks, retry/fatal paths, and streamed into Live GUI planning chat when the Live GUI handoff tail is active.
- `orchestrator.decision`: emitted when the supervisor selects the next graph transition and prepares the Orchestrator handoff packet.
- `orchestrator.parallel_checks`: emitted after the supervisor executes read-only parallel planning checks for a compiled plan.
- `orchestrator.loop_reflection`: emitted after Guardian loop review.

Authority split remains strict:

- Guardian owns safety decisions, block/safe-stop/approval authority, and incident policy.
- Orchestrator owns workflow narrative, context packing, operator-facing follow-up, route decisions, and loop reflection.
