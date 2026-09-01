# Equipment Vision Task Binding Design

## Objective

Bind each Lab Equipment Agent Vision Slot to one existing, deterministic Vision Agent task instead of storing an unbounded condition string and executing every UTM check. The selected task becomes the single source of truth across Agent Manager authoring, Equipment Agent execution, Runtime IDE projection, and evidence.

This design extends the Profile-bound Equipment Skill Flow defined in `2026-08-30-equipment-skill-flow-design.md`. It does not create a second Vision runtime, a second LLM path, or a direct `VisionAgent` instance inside `EquipmentAgent`.

## Existing Runtime To Reuse

The repository already contains the required Middle-Level Vision execution path:

- `vision.equipment_cross_check` is the canonical tool boundary.
- The camera tool observes the UTM ROS runtime in live mode.
- The same tool may use the existing virtual UTM bridge in test mode.
- Equipment Agent already emits run, loop, specimen, producer, and consumer identity with each check.
- Runtime IDE, Equipment Bridge, and Agent Manager already project the same Profile-bound Equipment Skill Flow.

The defect is at task selection. A Vision Slot currently stores `vision.condition`, but Equipment Agent ignores that value when choosing work and always submits `utm_pre_start`, `utm_motion_confirm`, and `utm_test_complete` together.

## Scope

This change will:

1. expose the existing Equipment-compatible Vision tasks as one shared catalog;
2. replace free-form Vision condition authoring with an exact task selection;
3. execute only the selected task for a Vision Slot;
4. preserve the selected task and its result in runtime evidence;
5. display the same task identity in Agent Manager, Runtime IDE, Equipment Bridge, and Live GUI projections;
6. migrate existing saved Vision Slots without creating another configuration source.

This change will not:

- duplicate UTM observation or specimen-detection code;
- move Vision inference into the browser;
- add conditional branching beyond the existing bounded Vision outcomes;
- expose manipulation-only checks, such as post-manipulation placement verification, as Equipment tasks;
- change the live/test virtual-bridge policy inside `vision.equipment_cross_check`;
- add an independent Vision block outside an Equipment composite block.

## Canonical Task Catalog

A shared, read-only Equipment Vision Task catalog owns the definitions that are currently embedded in `EquipmentAgent._equipment_vision_requests`.

| Task ID | Operator label | Purpose | Existing check ID |
| --- | --- | --- | --- |
| `utm_pre_start` | Pre-UTM Fixture Check | Verify fixture occupancy, specimen placement, robot clearance, and no human intrusion before UTM motion. | `utm_pre_start` |
| `utm_motion_confirm` | UTM Motion Confirmation | Verify that crosshead motion or a force-curve transition started while the specimen remains aligned. | `utm_motion_confirm` |
| `utm_test_complete` | Post-UTM Completion Check | Verify stopped motion, safe fixture access, and exported-data or completion evidence. | `utm_test_complete` |

Each catalog entry contains:

- stable `task_id` and `check_id`;
- operator label and bounded description;
- expected evidence contract;
- default timeout;
- compatible owner and consumer (`equipment_agent` to `vision_agent`);
- supported runtime modes;
- result-to-outcome mapping.

The catalog is code-owned and read-only in Agent Manager. Operators choose a task; they do not edit the task's expected evidence contract. This keeps live execution reproducible and prevents a free-form string from silently changing safety behavior.

## Stored Flow Contract

The canonical Vision Slot becomes:

```json
{
  "enabled": true,
  "task_id": "utm_pre_start",
  "detected": "next",
  "not_detected": "__blocked__",
  "timeout": "__blocked__",
  "error": "__blocked__"
}
```

Rules:

- `task_id` is required when `enabled` is true.
- `task_id` must exist in the shared Equipment Vision Task catalog.
- Disabled Vision Slots may retain a valid task selection for later re-enabling.
- An enabled slot with an unknown or missing task is unready and cannot execute.
- The existing bounded routes remain unchanged.
- `condition` is accepted only as a legacy input during normalization and is not persisted as the canonical selector.

The existing `atr.equipment_skill_flow.v1` envelope remains valid because the change is additive at the composite-block boundary and legacy payloads are normalized before persistence.

## Legacy Migration

Existing stored flows are normalized deterministically:

1. If `vision.task_id` is valid, keep it.
2. If legacy `vision.condition` exactly matches a catalog task ID, use that task.
3. If Vision is enabled and the legacy condition is `equipment_specimen_detected` or another unrecognized value, migrate it to `utm_pre_start` and expose a migration note in the API response.
4. If Vision is disabled and no task can be resolved, retain the slot as disabled with an empty `task_id`.
5. A newly enabled slot cannot be saved until the operator chooses a valid task.

Migration never expands one legacy Vision Slot into three checks. The old behavior of always executing all three checks is removed.

## Agent Manager

Vision Slot keeps the current enabled checkbox and bounded outcome routes. The free-form Condition field is replaced with a Vision Task selector populated from the shared catalog.

For the selected task, Agent Manager shows read-only metadata:

- task label;
- purpose;
- evidence expected;
- timeout;
- live/test support.

The selector is part of the same unsaved-draft and atomic-save behavior as the rest of the composite block. Polling must not overwrite an operator's unsaved selection.

The Profile Skill Flow payload returned to Agent Manager includes the read-only task catalog so the browser does not maintain a separate hard-coded list.

## Runtime Dispatch

Equipment Agent executes a Vision phase as follows:

1. Read `vision.task_id` from the active normalized block.
2. Resolve exactly one catalog entry.
3. Build one existing `equipment_vision_check_request` using the catalog entry plus current run, loop, specimen, producer, and consumer identity.
4. Call `vision.equipment_cross_check` once with a one-item `checks` list.
5. Map the returned check result to one bounded Vision outcome.
6. Record the outcome and evidence, then follow the configured route.

There is no fallback to the three-check list. A missing catalog entry, unavailable tool, malformed response, or identity mismatch produces an explicit blocked/error outcome before any subsequent Skill executes.

## Outcome Mapping

The selected check result maps to the existing Vision outcomes:

| Runtime result | Flow outcome |
| --- | --- |
| Check result is `ok` and evidence identity/freshness is valid | `detected` |
| Observation completed and explicitly reports the expected condition absent | `not_detected` |
| Observation or topic acquisition reaches its bounded timeout | `timeout` |
| Missing tool, invalid task, malformed result, stale identity, or infrastructure failure | `error` |

Test-mode virtualization remains visible in evidence through the existing `observer_mode`, `virtualized`, and `fallback_trace` fields. It does not change the selected task ID.

## Runtime Evidence

Each Vision transition records:

- `block_id`;
- `vision_task_id`;
- `check_id`;
- task label;
- runtime mode and observer mode;
- result outcome;
- confidence, timestamp, expiry, and source;
- bounded frame/observation references;
- failure code and operator attention when present.

The execution record is authoritative. GUI surfaces do not infer the selected task or outcome from labels or free-form messages.

## Runtime IDE And GUI Projection

Runtime IDE uses the same normalized flow graph and displays the selected task on the Vision node:

- node label: catalog task label;
- metadata: `task_id`, `check_id`, timeout, and control level `middle`;
- edges: the existing detected/not-detected/timeout/error routes.

Equipment Bridge and Live GUI remain read-only runtime projections. They show the same task label and current task result from the execution record. They do not provide another task editor.

Changing a task in Agent Manager and saving the Profile must update all projections after their next normal refresh without server-local hard-coded task labels.

## Safety And Failure Handling

- Vision task selection is Profile-bound and exact.
- Enabled Vision execution is fail-closed for unknown task IDs or unavailable tooling.
- No Vision failure produces device input.
- Equipment Agent cannot skip a configured Vision Slot because another UTM check succeeded earlier in the run.
- A result from a different run or specimen identity is rejected.
- Stale evidence cannot satisfy a new Vision Slot execution.
- Test-mode virtual evidence remains clearly marked and cannot be represented as live ROS evidence.
- Save validation is atomic; an invalid task leaves the previous Profile flow active.

## API Contract

The existing Profile Skill Flow endpoints remain the only authoring API:

- `GET /api/equipment/profiles/{profile_id}/skill-flow`
- `PUT /api/equipment/profiles/{profile_id}/skill-flow`

The GET response adds a read-only `vision_tasks` collection and migration notes when applicable. PUT accepts the canonical `vision.task_id`, normalizes legacy input, validates it against the catalog, and returns the same canonical response shape.

The Runtime IDE endpoint remains read-only for this concern and returns the graph produced from the normalized flow.

## Verification

### Unit tests

- catalog contains the three existing Equipment-compatible UTM tasks with their current expected evidence and timeout values;
- enabled Vision Slot requires a valid `task_id`;
- disabled unbound Vision Slot remains a valid draft;
- legacy condition migrates deterministically;
- runtime dispatch submits exactly one selected check;
- runtime dispatch never falls back to all three checks;
- each tool result category maps to the correct bounded outcome;
- selected task identity and evidence are persisted in the execution record.

### API and integration tests

- Agent Manager GET receives the same catalog used by Equipment Agent;
- PUT/GET round-trip preserves the selected task;
- Runtime IDE graph displays the selected task ID and label;
- Equipment Bridge and Live GUI project the same active task and result;
- invalid task save is rejected atomically;
- empty Profile flow preserves the existing legacy single-Skill path.

### Browser tests

- Vision Task selector lists the shared catalog;
- selection survives save and reopen;
- disabled/enabled transitions preserve a valid selection;
- an invalid or missing task shows unready state before execution;
- the selected task appears consistently in Agent Manager and Runtime IDE.

### Acceptance criteria

1. Selecting `utm_motion_confirm` causes exactly one `utm_motion_confirm` check to execute.
2. Neither `utm_pre_start` nor `utm_test_complete` executes unless selected by its own Vision Slot.
3. The same selected task ID is visible in saved JSON, Agent Manager, runtime execution evidence, and Runtime IDE.
4. Existing ROS observation and test virtual-bridge behavior continue through `vision.equipment_cross_check` unchanged.
5. No second Vision configuration or LLM execution path is introduced.
