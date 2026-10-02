---
{"topic_id":"recovery","owner":"documentation","source_refs":["system/agents/equipment_agent.md","system/agents/vision_agent.md","system/agents/analysis_agent.md","system/device_bridges/plc_safety_bridge.md"],"source_revision":{"system/agents/equipment_agent.md":"21de8d0387ce55d54c666d687dcddbc443ced70cfcdaade3f0687f12fc63a396","system/agents/vision_agent.md":"ad04cfe9bcc0c0f76a8dae75658d5ee2e101cfb1074b6c87a732626ca7bc9946","system/agents/analysis_agent.md":"b4e4c1d2a5ce25ddc2dbbea46bcd522ccd841ad00aa0838e3768b0fd7d76ce19","system/device_bridges/plc_safety_bridge.md":"06805f23d8f066b175e9e9b9a63e1c356ea9547b73adf48b233f005c9e8e7e4f"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: recovery","status":"reviewed"}
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
