# Guardian Improvement 09 Implementation Audit

Date: 2026-05-31
Scope: `개선안/09_guardian_agent_graphwide_safety_incident_loop_research.md`

This audit records the current implementation evidence for the graph-wide Guardian safety, runtime shield, and incident loop upgrade. It is intentionally requirement-based so future work can verify whether a change preserves the intended safety architecture.

## Requirement Status Matrix

| Requirement | Current Status | Authoritative Evidence |
| --- | --- | --- |
| Guardian is graph-wide, not only end-of-loop | Implemented for configured LangGraph stages | `orchestrator/langgraph_runtime.py` calls `guardian_gate(... phase="pre")` before stage execution and `guardian_gate(... phase="post")` after `AgentResult.data`; `tests/unit/test_langgraph_runtime.py`; `tests/unit/test_guardian_gate.py` |
| Pre-run gate checks graph/mode/module/device/risk metadata | Implemented | `LangGraphRunLoop._emit_pre_run_guardian_gate()` records `phase=pre_run` before `run.started`; `tests/unit/test_langgraph_runtime.py::test_langgraph_run_records_pre_run_guardian_gate` |
| `guardian_contract.v1`, `guardian_decision.v1`, `incident_record.v1`, `corrective_action.v1` exist | Implemented | `policies/guardian_gate.py`; `docs/runtime/guardian_graphwide_safety.md`; `tests/unit/test_guardian_gate.py` |
| Cross-agent alarm fields are normalized | Implemented with guarded exceptions | `policies/guardian_gate.py` recursively scans `failure_code`, blocked statuses, `ok=false`, missing-field keys, `warnings`, `validation_warnings`, `risk_flags`, `failure_tags`, approval flags, operator-input flags, and confidence; `requires_ack` is not treated as operator approval by itself; `tests/unit/test_guardian_gate.py` |
| Agent exceptions enter the Guardian timeline | Implemented | `orchestrator/langgraph_runtime.py` records `guardian_gate(... phase="exception")` when any agent raises before returning `AgentResult`; retry/fatal events carry the same gate; `tests/unit/test_langgraph_runtime.py::test_module_retry_policy_zero_attempts_fails_without_retry` |
| Hardware alerts persist across stages | Implemented | `orchestrator/langgraph_runtime.py::_merge_agent_data`; `app/controller.py`; `tests/unit/test_langgraph_runtime.py::test_langgraph_runtime_equipment_alert_merge_persists_incident_records`; `tests/unit/test_guardian_agent.py` |
| Runtime action shield before physical/persistent tools | Implemented | `ModuleToolRegistryProxy.call()` wraps side-effect tools with `guardian_gate(... action="pre_tool_call")`; `decision=modify` patches unsafe rollout clamp payloads before execution; `tests/unit/test_guardian_tool_shield.py` |
| Post-tool result Guardian inspection | Implemented | `ModuleToolRegistryProxy.call()` records `guardian_gate(... action="post_tool_call")` for shielded tools; `tests/unit/test_guardian_tool_shield.py` |
| Tool call request/result blackbox records | Implemented | `tool_call_record.v1` records are written to `run_metadata.tool_call_records` and `runs/<run_id>/guardian_events.jsonl`; `tests/unit/test_guardian_tool_shield.py`; `tests/unit/test_langgraph_runtime.py::test_langgraph_runtime_tool_call_snapshot_persists_blackbox_record` |
| Append-only Guardian/incident log | Implemented for incidents and tool-call records | `orchestrator/langgraph_runtime.py::_append_guardian_event`, `_record_incident_records`, `_record_tool_call_snapshot`; `docs/runtime/logging.md` |
| Human approval coordinator | Implemented | `run_metadata.guardian_approval_queue`, `run_metadata.runtime_approvals`, `/api/runs/{run_id}/approvals`, `/api/approvals/{approval_id}/approve|reject|revise`; `tests/ui/live_runtime_ide_browser_audit.py` references UI coverage; `tests/unit/test_guardian_tool_shield.py` covers pre-tool approval block |
| Self-evolution safety board hooks | Implemented at API gate level plus Knowledge evidence intake | `app/main.py` emits Guardian gates for self-evolution approve/activate/rollback and blocks active-run or unapproved activation; `agents/knowledge_agent.py` maps Guardian incidents/gates/tool blocks into `guardian_incident_evidence.v1` for Knowledge/Self-Evolution evidence; `tests/unit/test_self_evolution.py`; `tests/unit/test_knowledge_agent.py::test_knowledge_agent_ingests_guardian_incidents_as_evolution_evidence` |
| Guardian final loop review consumes graph-wide evidence | Implemented | `agents/guardian_agent.py` reads `guardian_gates`, `incident_records`, and `hardware_alerts`; broad regression tests include `tests/unit/test_guardian_agent.py` |
| Live GUI surfaces Guardian/tool shield events | Implemented at event/chat layer | `app/controller.py::_on_tool_event` handles `guardian.tool_shield`; `docs/runtime/guardian_graphwide_safety.md`; `tests/unit/test_controller_planning.py::test_planning_guardian_tool_shield_event_becomes_live_chat_message` |
| Physical verification path for equipment/UTM | Implemented in existing equipment path, not exhaustively hardware-tested here | `agents/equipment_agent.py`, `mcp_tools/utm_tools.py`, Windows equipment API tests; related tests in `tests/unit/test_equipment_agent.py` and `tests/unit/test_lab_equipment_live_validation_runner.py` |
| Fault-injection matrix | Implemented for deterministic Guardian policy; hardware-in-the-loop expansion remains ongoing | `tests/unit/test_guardian_fault_matrix.py` covers representative vision, robot, UTM, CSV/data, BO, and self-evolution faults; `tests/fault_injection/*` remains the place for hardware/runtime scenario expansion |
| Operator incident/near-miss notes | Implemented | `POST /api/runs/{run_id}/guardian/incidents/{incident_id}/notes` attaches `guardian_incident_note.v1` to `incident_record.operator_notes`, mirrors `run_metadata.guardian_incident_notes`, and emits `operator.guardian.incident_note_attached`; `web/static/planning.js`; `tests/integration/test_guardian_status_api.py::test_guardian_incident_note_api_attaches_note_to_incident_record` |
| Live GUI Guardian-specific heatmap/report payload | Implemented | `/api/guardian/status`, `/api/runs/{run_id}/guardian/status`, and `/api/state.guardian_status` return graph-wide risk map, safety budget, live device heartbeat, safe-stop verification, evidence completeness, self-evolution gate status, gate timeline, blocked actions, approval queue, incident ledger, policy panel, device/data integrity, and handoff packet; `web/static/planning.js` renders these in the Guardian Agent report; `tests/integration/test_guardian_status_api.py`; `tests/integration/test_live_gui_runtime_layout.py` |
| Test/virtual printer dry-run markers | Implemented | `START_PRINT_DISABLED`/`AUTO_EJECT_DISABLED` are filtered only for TEST, virtual bridge, or explicit dry-run payloads; live physical requests still block. | `tests/unit/test_guardian_gate.py`, `tests/integration/test_controller_run.py` |
| Test loop cap precedence | Implemented | Recoverable graph-gate pressure can no longer extend the deterministic TEST loop beyond the planned five cycles. | `tests/unit/test_guardian_agent.py`, `tests/integration/test_controller_run.py` |
| TEST runtime cadence | Implemented | Controller-driven TEST runs use zero inter-stage sleep so five-cycle safety regressions complete deterministically without weakening Live mode pacing. | `tests/integration/test_controller_run.py` |
| Controller integration timeout | Implemented | The real-LLM controller integration test now allows 240 seconds so full-suite resource contention does not fail a valid five-cycle TEST run. | `tests/integration/test_controller_run.py` |

## Current Safety Semantics

- `allow`: no alarm; stage/action may continue.
- `allow_with_warning`: near-miss or diagnostic warning; evidence is recorded and the loop can continue.
- `modify`: Guardian patches a known unsafe-but-correctable action payload before execution, records the modification, and continues.
- `require_human_approval`: approval queue item is created; side-effect tool calls do not execute until resolved.
- `block`: current transition/action is stopped and routed to Guardian review/recovery.
- `safe_stop`: physical progression is stopped and Guardian review is required.

The deterministic gate remains the primary safety path. LLM reasoning may explain or summarize, but it is not the sole decider for tool execution.

## Important Implementation Notes

- Vision `agent_signals.requires_ack` means downstream-agent acknowledgement, not operator approval. Actual operator approval must be represented by `requires_human_approval`, `requires_approval`, `blocks_workflow`, or concrete failure/block fields.
- Knowledge `agent_performance_records` are historical/diagnostic records. Missing fields inside those records are preserved as warning evidence rather than current-loop hard blockers.
- Pre-tool alarm scanning intentionally excludes prior context fields such as `source_stage_context`, `previous_stage_context`, `vision_signal`, and prior `incident_records` to avoid cascading stale warnings into unrelated action blocks.
- Tool-call records store payload hashes and key lists, not raw payload bodies, so bridge secrets and API credentials are not copied into the blackbox log.

## Verification Commands

Current focused verification:

```bash
python3 -m py_compile orchestrator/langgraph_runtime.py policies/guardian_gate.py tests/unit/test_guardian_tool_shield.py tests/unit/test_guardian_gate.py tests/unit/test_langgraph_runtime.py
.venv/bin/python -m pytest tests/unit/test_guardian_tool_shield.py tests/unit/test_langgraph_runtime.py::test_langgraph_runtime_tool_call_snapshot_persists_blackbox_record tests/unit/test_langgraph_runtime.py::test_langgraph_runtime_equipment_alert_merge_persists_incident_records tests/unit/test_langgraph_runtime.py::test_module_retry_policy_zero_attempts_fails_without_retry tests/unit/test_knowledge_agent.py::test_knowledge_agent_ingests_guardian_incidents_as_evolution_evidence -q
```

The Guardian status API regression also verifies `guardian_safety_budget.v1`, `live_device_heartbeat`, and `guardian_safe_stop_verification.v1` so other agents can emit alarms without adding separate UI channels.

Recommended broad regression before marking this improvement complete:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_guardian_tool_shield.py \
  tests/unit/test_guardian_gate.py \
  tests/unit/test_guardian_agent.py \
  tests/unit/test_self_evolution.py \
  tests/unit/test_langgraph_runtime.py \
  tests/unit/test_controller_planning.py \
  tests/integration/test_lerobot_gui_api.py::test_lerobot_rollout_api_hardware_alert_is_guardian_ready \
  tests/unit/test_guardian_fault_matrix.py \
  tests/integration/test_guardian_status_api.py \
  -q
```

## Remaining Work Before Strong Completion Claim

- Hardware-in-the-loop fault-injection remains environment-dependent for physical reproducibility; deterministic fault-matrix coverage is implemented and should be expanded as devices are available.
- Browser-level visual smoke testing remains optional for visual QA; current static/integration tests verify the Guardian status API and Live GUI rendering hooks.
