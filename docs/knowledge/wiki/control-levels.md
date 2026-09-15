---
{"topic_id":"control-levels","owner":"documentation","source_refs":["docs/runtime/three_level_control_model.md"],"source_revision":{"docs/runtime/three_level_control_model.md":"85195ea1600067c61996f1201b29d3221cd2c91a05a038067d494b1de52d661b"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: control-levels","status":"reviewed"}
---

# High, Middle and Low — Control Levels

AX4LAB separates reasoning, software processing and physical execution by responsibility, not file location or whether functions share a file.

| Level | Responsibility | Examples |
|---|---|---|
| High | Bounded LLM reasoning and decisions | Design candidate review, Analysis result acceptance |
| Middle | Processes, APIs, computation and validation | Curve parsing, BO computation, tool dispatch |
| Low | Physical equipment and driver execution | Printer commands, robot motion, test-machine control |

## LLM versus LLM call

LLM denotes the actual model decision boundary. LLM call is the code-side relationship that constructs context, invokes the model and processes its response. Showing LLM call in Middle does not classify the model itself as Middle.

Low does not mean every small software function. Parsers, numerical optimizers and retrieval tools are Middle, not devices. Agents without physical actuation do not need an artificial Low stage.

## Cross-cutting areas

Guardian/Safety covers safety, approval and stop conditions across levels. Knowledge/Evidence preserves the basis for inputs, decisions, commands, observations and results. These five areas are not five sequential execution stages.

## Device workspaces and the IDE

Device workspaces support manual configuration, commissioning and diagnostics. They may use the same bridges, but manual success does not prove completion of an automatic agent handoff.

Distinguish execution transitions from call/reference relationships in Runtime IDE. A CODE box is an implementation reference, not an extra execution stage.

[Control-level reference](../../runtime/three_level_control_model.md), [packages and plans](packages-and-plans.md).
