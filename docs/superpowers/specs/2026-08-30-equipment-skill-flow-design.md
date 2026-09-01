# Lab Equipment Agent Manager Design

## Objective

Separate Lab Equipment flow authoring from runtime observation. Equipment Bridge and Live GUI project execution progress, while a dedicated Agent Manager owns Profile-bound Skill composition. Runtime IDE projects the same flow as a graph and opens the same Agent Manager instead of maintaining another editor.

## Operator surfaces

### Equipment Bridge

- Keep the Agentic Progress runtime card.
- Remove Skill and Vision editing controls.
- Add `Open Agent Manager` for the selected Equipment Profile.
- Continue to show Profile connection and runtime evidence without becoming another configuration source.

### Live GUI

- Add the same Agentic Progress projection to the Lab Equipment Agent report.
- Show active, completed, blocked, and pending composite blocks from the current run.
- Do not allow flow editing from the Live GUI.

### Runtime IDE

- Keep the read-only Equipment flow graph projection.
- Replace the inline Skill Flow editor with `Open Agent Manager`.
- Refresh graph nodes and runtime state from the canonical contract.
- Runtime IDE graph operations must not create a second Equipment flow configuration path.

### Agent Manager

Provide one dedicated Profile-bound authoring page. Both Equipment Bridge and Runtime IDE open this page.

The manager has one `+ Block` action. It creates an empty composite block without
requiring a deployed Skill. The operator binds a Skill afterward inside Skill Slot:

```text
+-----------------------------------------------------------+
| Skill Slot                    | Agentic Task              |
| exact skill_id@version        | task name, outcome routes |
| deterministic low-level work | middle-level supervision  |
+-----------------------------------------------------------+
| Vision Slot                                               |
| enabled/disabled, exact task_id, bounded outcome routes   |
+-----------------------------------------------------------+
```

Supported block operations:

- select an exact deployed Skill version;
- edit the actual Agentic Task independently from the selected Skill;
- bind that Task to the selected Skill's existing annotation and bounded recovery context without creating a second LLM path;
- enable or disable the block's Vision verification;
- select one exact Equipment-compatible Vision Task from the shared catalog;
- move the complete block up or down;
- delete the complete block;
- save the Profile flow atomically.

There is no independent `+ Vision` action. Vision belongs to its Skill block.

An unbound block is a valid saved draft and remains visible in every projection. It
is not executable: readiness reports `Skill Slot is unbound`, and the Equipment Agent
blocks without invoking a worker or falling back to the legacy path. Partially bound
Skill references are invalid.

## Canonical contract

`graphs/modules/equipment/equipment_skill_flows.json` remains the single source of truth. One Profile stores an ordered list of composite blocks.

Each block contains:

- stable block id;
- exact `skill_id` and `skill_version`, or an explicitly unbound pair of empty values while authoring;
- label;
- Skill completed/failed routes;
- canonical `agentic.task` plus bounded outcome metadata used for execution and progress projection;
- embedded Vision configuration with `enabled`, catalog-backed `task_id`, and bounded outcome routes.

The exact task binding and legacy migration are defined by
`2026-08-31-equipment-vision-task-binding-design.md`. A free-form legacy
`condition` may be accepted only while normalizing older stored data; it is not
the canonical saved selector and is not exposed as an editor field.

The API normalizes a block into execution nodes internally:

1. execute exact Skill;
2. if Skill fails, follow the blocked route;
3. if Vision is disabled, complete the block;
4. if Vision is enabled, run the deterministic Vision check;
5. continue to the next block or a terminal according to the result.

The browser does not persist a separate flattened node graph.

## Compatibility and migration

- Existing composite-compatible Skill nodes are retained.
- A legacy Skill followed immediately by a Vision node is migrated into one composite block.
- A standalone Vision node without an owning Skill is rejected rather than preserved as an independent block.
- A non-empty active Agent Manager flow takes priority over the legacy single-Skill request.
- An empty flow keeps the existing single-Skill/Profile program path unchanged.

## Runtime state

Each execution records:

- block id and exact Skill identity;
- current phase: Skill, Vision, or handoff;
- selected `vision_task_id`, `check_id`, task label, and bounded Vision outcome when Vision is enabled;
- outcome and target;
- timestamps and bounded evidence references;
- terminal state.

Equipment Bridge, Live GUI, and Runtime IDE read this same execution projection. They do not infer progress independently.

## Safety and error handling

- Only deployed, enabled exact Skill versions for the selected Profile may be saved as ready.
- Invalid Skill references, cycles, unreachable routes, and standalone Vision nodes are rejected.
- Vision failures never produce device input.
- Unsaved Agent Manager drafts are not overwritten by polling.
- Save is atomic; a validation failure leaves the previous flow active.
- Closing Agent Manager with unsaved changes requires an operator confirmation.

## Verification

- Unit tests cover composite-block validation, migration, sequencing, Vision disabled/enabled outcomes, and invalid references.
- API tests prove one canonical flow is shared across Agent Manager, Equipment Bridge, Live GUI, and Runtime IDE.
- Browser tests prove a block can be added, edited, reordered, saved, reopened, and reflected in both runtime projections.
- Regression tests prove the legacy single-Skill path remains active for an empty Profile flow.
