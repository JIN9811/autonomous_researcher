---
{"topic_id":"recovery","owner":"documentation","source_refs":["docs/agents/equipment_agent.md","docs/agents/vision_agent.md","docs/agents/analysis_agent.md","docs/device_bridges/plc_safety_bridge.md"],"source_revision":{"docs/agents/equipment_agent.md":"833fc4d6c8181a3dc719f33b1c7d948c3f424798c4425f0fb36cd683e3852531","docs/agents/vision_agent.md":"eb1dfe2ecab1377fc2569ded072f6c91f71f36a721e238ef11e26d2010ce429b","docs/agents/analysis_agent.md":"92288bc305c63d5864c9e7680e233fa4ec85d3a1996e742541734972672400ad","docs/device_bridges/plc_safety_bridge.md":"59e03e759b75c0a46f3ad1cb75f6bba093693dd2bf3354be3422dfe3e69dceee"},"verified_at":"2026-09-28T00:00:00+09:00","applicability":"Public AX4LAB reference: recovery","status":"reviewed"}
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
