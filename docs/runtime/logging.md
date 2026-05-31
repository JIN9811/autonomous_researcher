# Logging

The runtime writes:
- `structured.jsonl`: machine-readable events
- `summary.log`: human-readable run summary

Each event includes `run_id`, `experiment_id`, `layer`, `event_type`, and payload.

Live GUI planning/tool events:
- Planning chat messages are also emitted as structured events by `MainController`.
- `printer.prepare` can emit supplemental per-step tool events while Specimen Making Agent is running.
- These events are UI/logging progress signals; the authoritative stage result remains `AgentResult.data["specimen_result"]`.
- Printer runtime events must never include PrusaLink secrets, API keys, passwords, or auth headers.

Guardian-ready hardware alerts:
- Hardware workspace failures are also emitted as `hardware.alert` runtime events.
- The API result keeps the same original tool payload and adds `hardware_alert` when a device-specific failure is detected.
- `hardware_alert` includes `guardian_contract.v1`, `guardian_decision.v1`, and `incident_record.v1` payloads so Guardian can consume the same signal later without reparsing GUI text.
- Incidents are appended to `runs/<run_id>/guardian_events.jsonl`; this file is the durable source for Guardian/Knowledge/Self-Evolution follow-up.
- `run_metadata.hardware_alerts` keeps the latest in-memory alerts for Live GUI state and Guardian loop review.
- `device_health` may contain values such as `blocking:LEROBOT_DEVICE_PORT_REQUIRED`; Guardian treats `blocking:` and `critical:` prefixes as unhealthy hardware states.

Guardian graph-wide gates:
- `guardian.gate` runtime events are emitted around stage `pre`, module/tool `action`, and stage `post` phases.
- Each gate carries `guardian_gate_result.v1`, `guardian_contract.v1`, `guardian_decision.v1`, optional `incident_record.v1`, and optional `corrective_action.v1`.
- The gate scans agent payloads for `failure_code`, `status=blocked/failed/error`, `ok=false`, `blocking_reasons`, `warnings`, `risk_flags`, `failure_tags`, approval flags, operator-input flags, and low confidence values.
- `incident.recorded` events are emitted for gate-generated incidents.
- Synchronous tool-call shields emit Live GUI planning/tool events with `tool=guardian.tool_shield`, `shielded_tool`, `decision`, `reason_code`, `risk_score`, and the full `guardian_gate`.
- Every module tool call records `tool_call_record.v1` request/result entries with `call_id`, stage, tool, payload hash, status, result status, failure code, and Guardian gate id when available. These records are mirrored into `run_metadata.tool_call_records` and appended to `runs/<run_id>/guardian_events.jsonl` for blackbox replay.
- Tool shield approval interrupts are persisted in `run_metadata.guardian_approval_queue` and `run_metadata.runtime_approvals`.
- Live GUI refreshes on `guardian` and `incident` event types and surfaces warning/error gates in Operator Attention.
- `/api/guardian/status` and `/api/state.guardian_status` expose the same Guardian blackbox state as a report payload for risk heatmap, approval queue, incident ledger, and handoff review panels.
