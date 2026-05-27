# Backend API Spec

## Runtime
GET /api/runtime/state
POST /api/runtime/start
POST /api/runtime/pause
POST /api/runtime/resume
POST /api/runtime/stop
POST /api/runtime/safe-stop
GET /api/runtime/events

## Agents
GET /api/agents
GET /api/agents/{agent_id}/report
GET /api/agents/{agent_id}/backend-trace
POST /api/agents/{agent_id}/message

## Graphs
GET /api/graphs
GET /api/graphs/{graph_id}
POST /api/graphs/{graph_id}/validate
POST /api/graphs/{graph_id}/compile
POST /api/graphs/{graph_id}/save-version
POST /api/graphs/{graph_id}/run

## Artifacts
GET /api/artifacts
GET /api/artifacts/{artifact_id}

## Devices
GET /api/devices/state

## Approvals
POST /api/approvals/{approval_id}/approve
POST /api/approvals/{approval_id}/revise
POST /api/approvals/{approval_id}/reject

## Runtime Event Types
- run_started
- run_completed
- run_failed
- stage_changed
- agent_started
- agent_completed
- agent_failed
- agent_question
- user_reply
- approval_requested
- approval_granted
- approval_rejected
- tool_call_started
- tool_call_completed
- artifact_created
- handoff_created
- graph_validated
- graph_compiled
- graph_version_saved
- device_state_changed
- safe_stop_triggered
