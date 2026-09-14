---
{"topic_id":"manipulation-role","owner":"manipulation_agent","source_refs":["docs/agents/manipulation_agent.md"],"source_revision":{"docs/agents/manipulation_agent.md":"fef922545e6d642ec0f8304935ae41d11946ec7f45b279124f7fa7b1ad3d212c"},"verified_at":"2026-09-14T00:00:00+00:00","applicability":"Public Manipulation Agent responsibilities and handoff","status":"reviewed"}
---

# Manipulation Agent

Manipulation judges configured-skill suitability and task-result consistency after existing Vision and termination checks. It uses the existing transfer and post-test clearance paths, with bounded rollout or configured replay operations. The model chooses an immutable proposal reference; code supplies driver arguments. robot_task_result.v1 goes to Vision and Equipment; verified clearance precedes Analysis. Real-time action timing, process lifecycle, ports and camera leases remain bridge-owned.

Source: [Manipulation Agent reference](../../agents/manipulation_agent.md).
