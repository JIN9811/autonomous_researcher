---
{"topic_id":"recovery","owner":"documentation","source_refs":["docs/agents/equipment_agent.md","docs/agents/vision_agent.md","docs/agents/analysis_agent.md","docs/device_bridges/plc_safety_bridge.md"],"source_revision":{"docs/agents/equipment_agent.md":"86682debedafd4b6511f5a0d96ada348e5c1d4f3b8d53a443107fcfac2c4e671","docs/agents/vision_agent.md":"87dbe9f4163654e302c36aec96de36596eed909cf9e9d13311ae8df5baa99bd7","docs/agents/analysis_agent.md":"7dca2f8a0c8c4122a29de24daaed2df39c05bee6d811e6ab98d8c98567f50c3e","docs/device_bridges/plc_safety_bridge.md":"c39f85b9bbfe2bddb0415619b47760254a710da81df7203868a2958a4d25e5ff"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: recovery","status":"reviewed"}
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
