---
{"topic_id":"recovery","owner":"documentation","source_refs":["docs/agents/equipment_agent.md","docs/agents/vision_agent.md","docs/agents/analysis_agent.md","docs/device_bridges/plc_safety_bridge.md"],"source_revision":{"docs/agents/equipment_agent.md":"68850b6cbbbec745f5a134a4ac8676dfd08f0c24b8278bf7f90d67b3a6779ca2","docs/agents/vision_agent.md":"f9b3fdb014fa0114b7fb440e922fd64d9116943eb95536337798b81363675b3c","docs/agents/analysis_agent.md":"8963c88b1ca2a74dad2ea35a2195bf5f91f7d9f9e3ea66520d05a13cbb5e851b","docs/device_bridges/plc_safety_bridge.md":"7957b423af9436dd18175a91761f3016e0ea6dc6290a02ebf9ef8391415ed6a1"},"verified_at":"2026-09-28T00:00:00+09:00","applicability":"Public AX4LAB reference: recovery","status":"reviewed"}
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
