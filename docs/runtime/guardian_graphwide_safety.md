# Guardian Graph-Wide Safety and Alarm Contract

This document describes the runtime Guardian sidecar introduced for graph-wide safety, quality, approval, and incident handling.

## Runtime Position

Guardian is no longer only the final loop stage. The runtime now evaluates Guardian gates around every configured agent stage:

- `pre_run`: before the run loop executes any stage, using graph hash/version, mode support, module versions, safety metadata, device heartbeat, operator approval state, required-input presence, and risk-budget evidence.
- `pre`: before a stage starts, using graph/module runtime metadata and active state alerts.
- `action`: after configured module pre-execution agent/tool steps and around protected tool calls.
- `post`: after an agent returns its `AgentResult.data` and before the next stage is selected.
- `exception`: when an agent raises before returning `AgentResult`; the runtime records the exception as a Guardian gate while preserving the configured retry policy.

The final `GuardianAgent` still owns the loop-level decision (`continue`, `recover`, `retry`, `stop`) but it now also reads the graph-wide gate history from `state.run_metadata`.

## Standard Payloads

The common gate implementation is `policies/guardian_gate.py`.

It returns `guardian_gate_result.v1` with these nested records:

- `guardian_contract.v1`: stage, phase, status, artifact/provenance refs, approval requirement, next-stage permission, BO permission, risk flags.
- `guardian_decision.v1`: decision, reason code, risk score/vector, dominant risks, recommended action, required/missing evidence.
- `incident_record.v1`: durable incident or near-miss record for Guardian, Knowledge, and self-evolution follow-up.
- `corrective_action.v1`: recommended recovery/debug action derived from the alarm.

Incidents are appended to `runs/<run_id>/guardian_events.jsonl` and mirrored into `state.run_metadata.incident_records`.

## Alarm Sources Consumed From Agents

The gate recursively scans agent/tool payloads and normalizes these existing fields:

| Source field | Typical producers | Guardian meaning |
| --- | --- | --- |
| `failure_code`, `error_code`, `incident_code` | Specimen, Manipulation, Equipment, Analysis, workspace APIs | Blocking or critical failure, depending on severity |
| `status=blocked/failed/error/critical/not_enabled` | Specimen quality gates, Equipment handoff, Analysis gates, bridge tools | Blocking workflow state |
| `ok=false` | Tool/API results, analysis quality probes | Result cannot be treated as passed |
| `blocking_reasons`, `blockers`, `blocking_reason`, `missing_fields`, `missing_required_fields`, `required_missing`, `issues`, `errors` | Design handoff, Vision signals, Manipulation preflight, Equipment/Analysis handoff | Required input/evidence/contract gap or blocking downstream precondition |
| `warnings`, `validation_warnings`, `*_warnings`, `risk_flags`, `failure_tags`, `quality_flags`, `alerts` | Design, Vision, BO, Knowledge, Analysis, Manipulation | Warning or near-miss evidence |
| `requires_operator_input`, `requires_connection_info` | Specimen/printer setup, bridge setup | Missing operator/configuration input |
| `requires_human_approval`, `requires_approval` | Hardware alerts, approval gates, high-risk actions | Human approval required |
| `blocks_workflow` | Hardware alerts, handoff gates | Hard workflow block |
| `safe_stop_recommended` or runtime `safe_stop_requested` | Guardian/tool/runtime controls | Safe-stop decision |
| `confidence < 0.5` | Vision and perception signals | Low confidence warning |

`requires_ack` is intentionally not treated as a human approval alarm by itself. Vision `agent_signals` use it as an inter-agent acknowledgement marker; actual operator approval must be represented with `requires_human_approval=true`, `requires_approval=true`, `blocks_workflow=true`, or a concrete `failure_code`.

Historical or diagnostic records, such as Knowledge `agent_performance_records`, may still carry missing-field or warning signals. Those are preserved as warnings/near-misses unless they appear in the current stage handoff/output contract.

## Agent-Specific Alarm Expectations

- Design Agent: must use `missing_fields`, `warnings`, and manufacturability risk warnings instead of silently fabricating missing operator requirements.
- Specimen Making Agent: reports mesh/manufacturability/slicer/G-code/printer/ejection gate failures through `failure_code`, `warnings`, `requires_connection_info`, or `requires_operator_input`.
- Vision Agent: reports stale/low-confidence scene signals through `confidence`, transfer-readiness `status`, and `blocking_reason`. Its signal-level `requires_ack` is a downstream-agent acknowledgement marker, not operator approval.
- Manipulation Agent: reports LeRobot/Pi0.5 preflight blockers, rollout failures, stale vision, and unsafe policy conditions through `blocking_reasons`, `failure_code`, and `failure_tags`.
- Lab Equipment Agent: emits `hardware_alert.v1` plus `incident_record.v1` for UTM, Windows PyAutoGUI, request-log, screen-evidence, CSV, or no-motion failures.
- Analysis Agent: reports data/FEM/CAE quality gates through `failure_code`, `failure_tags`, `quality_gate`, and `ok_for_bo`.
- Knowledge Agent: reports memory/evidence quality warnings and self-evolution evidence gaps through `warnings` and `failure_tags`.
- BO Agent: reports unsafe candidates and constraint penalties through `risk_flags`, `warnings`, and recommendation constraints.
- Guardian Agent: reads `guardian_gates`, `incident_records`, and `hardware_alerts` from `state.run_metadata` and folds them into the final loop decision.

## Runtime Action Shield

Physical, persistent, or runtime-mutating tool calls now pass through a Guardian sidecar in `ModuleToolRegistryProxy.call()` before the underlying MCP-style handler is executed. The shield is applied to these tool families:

- Printer and fabrication: `experiment.evaluate`, `printer.prepare`, `printer.start`, `printer.auto_eject`.
- Robot and manipulation: `lerobot.rollout.start`, `robot.pick_place`.
- Lab equipment: `equipment.pyautogui.run`, `utm.run_protocol`.
- Runtime mutation hooks: `self_evolution.activate`, `self_evolution.rollback`, `graph.active_config.activate`, `knowledge.memory.commit`.

The pre-tool shield calls `guardian_gate(stage, phase="action", tool=<tool>, action="pre_tool_call")`. If the decision is `block`, `safe_stop`, or `require_human_approval`, the real tool handler is not called and the caller receives a structured blocked result with:

- `failure_code=GUARDIAN_TOOL_SHIELD_BLOCKED` for hard blocks.
- `failure_code=GUARDIAN_TOOL_APPROVAL_REQUIRED` for approval interrupts.
- `guardian_gate`, `guardian_contract`, `guardian_decision`, `incident_records`, and `corrective_actions` sidecars.

Live hardware tools are conservative by default. Live robot rollout requires explicit confirmation and an approved policy reference. Live equipment macros require a program/protocol id and explicit operator confirmation. Live printer execution requires physical execution intent such as `execution.allow_physical=true`, `confirm_physical_print`, `physical_intent`, or the approved live-test printer path. Non-live, dry-run, virtual, and non-actuating calls are allowed to proceed while still producing post-tool evidence when relevant.

Post-tool results are also passed through `guardian_gate(... action="post_tool_call")` so `ok=false`, `failure_code`, warnings, or blocked statuses become incidents without reinterpreting GUI text.

In addition, module tool calls create `tool_call_record.v1` blackbox records for `requested`, `completed`, `failed`, `blocked`, or `approval_required` outcomes. The record stores a payload hash and key list rather than raw secrets, links to the Guardian gate when present, and is mirrored into `run_metadata.tool_call_records` plus `runs/<run_id>/guardian_events.jsonl`.

## Cross-Agent Alarm Path

Other agents should not invent separate alarm channels. They should emit one or more of the standard fields listed above in their `AgentResult.data`, tool result, or workspace API result. The runtime handles them as follows:

- Stage pre/post Guardian gates normalize the fields into `guardian_gate_result.v1`.
- Agent exceptions before `AgentResult` are recorded as `phase=exception` Guardian gates and attached to retry/fatal runtime events.
- Explicit `hardware_alert.v1` records are merged into `run_metadata.hardware_alerts`, `run_metadata.incident_records`, and `device_health`.
- Tool-call shield decisions are merged into `run_metadata.guardian_gates`, `guardian_contracts`, `corrective_actions`, `incident_records`, and `guardian_approval_queue`. Tool request/result records are merged into `run_metadata.tool_call_records` and the run-local blackbox log.
- The Live GUI receives `guardian.tool_shield` planning messages for blocked, warning, and approval-required tool actions.
- The final Guardian Agent reads `guardian_gates`, `hardware_alerts`, and `incident_records` together, so alarms from Design, Specimen, Vision, Manipulation, Equipment, Analysis, Knowledge, BO, and self-evolution share one decision surface.
- Knowledge Agent converts Guardian incidents, gate decisions, hardware alerts, and blocked tool records into `guardian_incident_evidence.v1`, folds their reason/failure tags into memory failure tags, and carries them into Knowledge/Self-Evolution evidence payloads.

## Runtime State Fields

The runtime stores Guardian sidecar data in:

- `run_metadata.guardian_gates`: recent gate decisions for every stage/action.
- `run_metadata.latest_guardian_gate`: most recent `guardian_gate_result.v1`.
- `run_metadata.latest_guardian_gate_decision`: most recent `guardian_decision.v1`.
- `run_metadata.guardian_contracts`: recent `guardian_contract.v1` records.
- `run_metadata.corrective_actions`: recent `corrective_action.v1` records.
- `run_metadata.incident_records`: recent incident records.
- `run_metadata.hardware_alerts`: device/workspace hardware alerts.
- `run_metadata.tool_call_records`: recent module tool call request/result blackbox records.
- `run_metadata.guardian_approval_queue`: pending Guardian approval interrupts created by stage gates or pre-tool shields.
- `run_metadata.runtime_approvals`: keyed approval records used by Runtime IDE/Live GUI approval controls.
- `device_health[device_class]`: may be set to values like `blocking:<failure_code>`.

## Guardian Status Report API

The graph-wide Guardian monitor payload is available from:

- `GET /api/guardian/status` for the active run.
- `GET /api/runs/{run_id}/guardian/status` for a requested run id when available.
- `GET /api/state`, field `guardian_status`, for reload-safe GUI state synchronization.

The payload schema is `guardian_status_report.v1` and includes `graph_wide_risk_map`, `gate_timeline`, `blocked_actions`, `approval_queue`, `incident_ledger`, `policy_version_panel`, `device_data_integrity`, `safety_budget`, `evidence_completeness`, `safe_stop_verification`, `self_evolution_gate`, and `handoff_packet`. This is the canonical data source for the Guardian heatmap/report panel; the visual page renders it compactly and must not recompute safety decisions in JavaScript.

Additional Guardian monitor sections are normalized in the backend so all agents share the same alarm surface:

- `safety_budget` (`guardian_safety_budget.v1`): loop count, expected print time, expected load, robot live rollout count, and physical print count against `run_metadata.safety_budget`, `run_metadata.risk_budget`, or experiment constraints.
- `device_data_integrity.live_device_heartbeat`: per-device bridge state, latest command, latest alert id, and heartbeat status derived from `device_health`, hardware alerts, and tool-call records.
- `safe_stop_verification` (`guardian_safe_stop_verification.v1`): `safe_stop requested -> safe_stop verified` state, with explicit metadata, controller stopped state, or Guardian gate evidence as the verification basis.
- `evidence_completeness` (`guardian_evidence_completeness.v1`): current gate/contract/artifact/provenance/tool/incident evidence coverage score.
- `self_evolution_gate` (`guardian_self_evolution_gate.v1`): pending, approved, active-next-run, and active self-evolution variants visible to the Guardian safety board.

## Live GUI Behavior

The runtime emits:

- `guardian.gate` for each async stage gate decision.
- `incident.recorded` for each incident generated by a gate.
- `guardian.tool_shield` planning/tool events when a synchronous pre-tool/post-tool shield warns, blocks, or requests approval.
- Existing `hardware.alert` events from workspace APIs remain supported.

The Live GUI event stream refreshes on `guardian` and `incident` event types. Warning/error Guardian events are included in Operator Attention, not just the timeline, so the operator sees cross-agent alarms even when the emitting agent is not currently selected. The Guardian Agent report also fetches `/api/runs/{run_id}/guardian/status` and shows the graph-wide risk map, safety budget, live device heartbeat, safe-stop verification, evidence completeness, self-evolution gate status, blocked actions, approval queue with approve/revise/reject controls, incident/near-miss ledger with note attachment, policy/version panel, device/data integrity, and corrective actions.

Operator notes are attached through `POST /api/runs/{run_id}/guardian/incidents/{incident_id}/notes` or the active-run alias `POST /api/guardian/incidents/{incident_id}/notes`. Notes are mirrored into `run_metadata.guardian_incident_notes`, appended to the matching `incident_record.operator_notes` when present, and written to the Guardian append-only event log as `guardian_incident_note.v1`.

## Decision Semantics

- `allow`: no alarm.
- `allow_with_warning`: warning/near-miss, record evidence and continue.
- `modify`: non-blocking shield correction; currently used to force safe rollout action clamping before executing a robot rollout payload.
- `require_human_approval`: approval gate; stage gates enqueue an approval request, and pre-tool action shields stop the tool call until the operator resolves the request.
- `block`: route to Guardian review/recovery before continuing.
- `safe_stop`: stop physical progression and verify safe state.

`gate_blocks_execution()` currently blocks `block` and `safe_stop` decisions. Human approval remains visible through the approval/event layer and should be resolved before an operator starts a physical action.

## Test Coverage

Relevant tests:

- `tests/unit/test_guardian_gate.py`: alarm normalization, nested warnings, agent-specific alarm keys, signal ACK handling, approval, and blocker handling.
- `tests/unit/test_guardian_tool_shield.py`: pre-tool action shield blocking/allowing side-effect tools.
- `tests/unit/test_guardian_agent.py`: Guardian final decision from hardware alerts and graph-wide gates.
- `tests/unit/test_knowledge_agent.py`: Guardian incidents become Knowledge/Self-Evolution evidence through `guardian_incident_evidence.v1`.
- `tests/unit/test_controller_planning.py`: Live GUI planning messages for Guardian shield events and hardware/tool progress.
- `tests/unit/test_langgraph_runtime.py`: runtime merge/event behavior, agent-exception Guardian gates, and result-key compatibility.

### Cross-Agent Alarm Semantics

Guardian reads cross-agent alarm fields such as `failure_code`, `blocking_reasons`, `warnings`, `failure_tags`, `confidence`, `hardware_alert.v1`, and `incident_record.v1` across Design, Specimen, Vision, Manipulation, Equipment, Analysis, Knowledge, BO, and Guardian outputs. TEST/virtual/dry-run printer `START_PRINT_DISABLED` markers are treated as expected non-actuating evidence, while live physical print/ejection requests still block on the same marker. TEST mode loop caps override recoverable graph-gate pressure so deterministic test runs do not retry indefinitely.
