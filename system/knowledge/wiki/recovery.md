---
{"topic_id":"recovery","owner":"documentation","source_refs":["system/agents/equipment_agent.md","system/agents/vision_agent.md","system/agents/analysis_agent.md","system/device_bridges/plc_safety_bridge.md"],"source_revision":{"system/agents/equipment_agent.md":"44e2fa04db045e5b54a7580fca7674f3862409eb5103fc4d281bcd95975511ca","system/agents/vision_agent.md":"56f0d6b4aff9ea2d58b06a7d374ab09ad43675e780916a446158450be2fd24ec","system/agents/analysis_agent.md":"708ad6643bc4055b589b48237b69e4948412af8293d0eec918cf12aef5f71516","system/device_bridges/plc_safety_bridge.md":"b1d27bf8f94e18d31c8e67a323cb6ee0aecc74ebdc55289ebb3378d8a47fefbf"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: recovery","status":"reviewed"}
---

# Recovery — Resume and Archived Evidence

Recovery establishes what actually completed and what may continue without replay. It does not simply relabel failure as success. Device stop state and data postprocessing are separate decisions.

| State | Review path |
|---|---|
| Paused | Resume under existing conditions |
| Test completed; terminal review failed | Revalidate run, specimen, CSV hash and completed tasks |
| Requested archived-image review | Non-actuating review of the historical scene |
| Partial execution or unknown effects | Hold; do not repeat automatically |

Original compression CSV, completed Skills/replays and image timestamps/hashes are evidence. Preserve them; do not overwrite old decisions or give historical images a current timestamp.

## Historical images

Explicit archived review assesses the scene at capture time. It is not current physical clearance. A scoped path may retain the safety hold while continuing saved-data Analysis, Knowledge, BO and limited next Design. This is separate from resuming physical experiments.

Stopping at the next Design is a one-off recovery scope, not a permanent experiment rule or fabrication permission.

## Server and code application

Checkpoint restoration and limited hot reload do not actuate equipment. Hot reload validates supported modules at an inactive boundary; it cannot replace active/paused work or arbitrary modules. A controlled server update may still be required.

Recovery does not automatically clear PLC latches, operator stops or owner approvals. Past success cannot authorize new actuation when current effects are unknown.

[Equipment recovery contract](../../agents/equipment_agent.md), [Vision historical review](../../agents/vision_agent.md), [PLC safety boundary](../../device_bridges/plc_safety_bridge.md).
