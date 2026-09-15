---
{"topic_id":"recovery","owner":"documentation","source_refs":["docs/agents/equipment_agent.md","docs/agents/vision_agent.md","docs/agents/analysis_agent.md","docs/device_bridges/plc_safety_bridge.md"],"source_revision":{"docs/agents/equipment_agent.md":"4baaf79dcb3435baceb438fdb20cb4516e33a38e92a2c0d60f94e2e1a8999394","docs/agents/vision_agent.md":"4bcba27369ea9a3062679b959aba80700d3658499e2abd675da464643a1286d6","docs/agents/analysis_agent.md":"dd1427c585819820ad7a410301f0b69fb54057cd93b37f05ef5e58f2120bfd96","docs/device_bridges/plc_safety_bridge.md":"7957b423af9436dd18175a91761f3016e0ea6dc6290a02ebf9ef8391415ed6a1"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: recovery","status":"reviewed"}
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
