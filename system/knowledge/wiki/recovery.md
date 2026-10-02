---
{"topic_id":"recovery","owner":"documentation","source_refs":["system/agents/equipment_agent.md","system/agents/vision_agent.md","system/agents/analysis_agent.md","system/device_bridges/plc_safety_bridge.md"],"source_revision":{"system/agents/equipment_agent.md":"ef49a454b482be24ec5fd6ae347e287cca26383f285165b9ec8de2ef3f7f9a8e","system/agents/vision_agent.md":"a30661502aff943c53e9ae4f02909c82ea2d5f5c8c1f642d54aec6c49a85b93d","system/agents/analysis_agent.md":"fd0e6921b8443f318e3cb2139e614482288c828d8633fac1746bddd0fa04a6cd","system/device_bridges/plc_safety_bridge.md":"fae567937e82ccc704ca6c5a403ee6140975be9dbdb81ed5ce7e0da0f52821f3"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: recovery","status":"reviewed"}
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
