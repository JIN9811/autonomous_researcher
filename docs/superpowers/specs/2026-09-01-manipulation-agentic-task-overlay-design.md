# Manipulation Agentic Task Overlay Design

## Objective

Add an Agentic Task supervision layer above the existing Manipulation Agent and
LeRobot Skill runtime so the real robot-to-UTM workflow is explicit, recoverable,
and safe without replacing the current policy, bridge, profile, or stage logic.

The overlay owns workflow phase, mandatory gates, recovery routing, and downstream
handoff. Existing LeRobot Skills continue to own bounded robot motion. Existing
Lab Equipment Skill Flow Vision switches continue to control only optional Vision
checks that run alongside individual equipment steps.

## Source Of Truth

The recorded TRAPEZIUMX-V workflow and its extracted reference bundle are the
current physical-process source of truth. Older contracts remain useful only when
they do not conflict with that observed flow.

The reference bundle is:

`references/trapeziumx_v_equipment_agent/`

Current method and cell values such as contact force, target Stroke, and robot
clearance Height are configuration values, not workflow constants. The contracts
name the equipment readings as Force, Stroke, and Height. They do not encode the
transport used to obtain those values.

## Architectural Constraint

This change is additive. The runtime stack becomes:

1. Agentic Task overlay: phase progression, mandatory gates, recovery, handoff;
2. existing Manipulation Agent supervisor: preflight, policy selection, rollout
   supervision, SARM scoring, interlocks, evidence packaging;
3. existing LeRobot Skill and bridge: bounded physical robot execution;
4. existing robot, camera, and equipment adapters.

The overlay must not:

- call robot hardware directly;
- replace `ManipulationAgent.run` with another execution path;
- create a second LeRobot profile or policy-selection source;
- split a learned rollout into new policies implicitly;
- weaken Guardian stop authority or the LeRobot bridge boundary;
- convert optional equipment-time Vision into an alternative to mandatory
  manipulation verification.

## Terms And Responsibility Boundaries

### Agentic Task

An Agentic Task is the deterministic supervisory contract for a complete physical
intent, such as transferring one printed specimen to the UTM and producing a
verified handoff. It describes phases, gates, success criteria, recovery routes,
and the next agent.

### Skill

A Skill is the existing bounded execution capability selected by `skill_id` and
implemented by the current LeRobot rollout or compatibility bridge. A Skill
executes motion; it does not decide whether a mandatory UTM handoff gate may be
skipped.

### Vision Modes

There are two distinct Vision responsibilities:

- **Mandatory manipulation Vision** verifies the robot's UTM entry and final
  specimen placement for the physical handoff. It is locked on and has no
  operator enable/disable option.
- **Optional equipment-concurrent Vision** observes selected Lab Equipment steps.
  Its existing per-step switches remain editable. Disabling one of these switches
  does not disable or satisfy a mandatory manipulation gate.

## Canonical Agentic Tasks

### `transfer_to_utm`

The existing task and Skill IDs remain stable. The overlay adds the following
canonical phases around the current execution:

| Phase | Owner | Requirement | Success evidence |
| --- | --- | --- | --- |
| `resolve_and_preflight` | Manipulation Agent | Required | specimen, robot profile, policy, camera ownership, and live authorization are valid |
| `acquire_specimen` | Existing LeRobot Skill | Required | pickup-ready context and bounded rollout progress |
| `transfer_toward_utm` | Existing LeRobot Skill | Required | measured rollout execution and no anomaly/stop condition |
| `verify_utm_entry` | Agentic overlay + Vision | Required, locked | fresh run/specimen-bound UTM-entry approval |
| `place_on_platen` | Existing LeRobot Skill | Required | placement and release progress observed |
| `release_and_home` | Existing interlock | Required | measured ungrasping followed by stable Home/clear state |
| `verify_utm_placement` | Agentic overlay + Vision | Required, locked | fresh specimen-on-platen evidence after Home/clear state |
| `handoff_to_equipment` | Agentic overlay | Required | all required gates passed and `ready_for_equipment` emitted |

`verify_utm_entry` and `verify_utm_placement` are not profile switches. They may
be represented by existing Vision observations and signals, but the overlay owns
the requirement and rejects stale or mismatched evidence.

The final placement check must occur after measured release and Home/clear state.
Preflight imagery cannot satisfy the final placement gate.

### `clear_utm_to_disposal`

The existing task and Skill IDs also remain stable. The overlay requires:

1. a completed equipment result and safe-access state;
2. a valid tested-specimen pickup context;
3. bounded removal and discard execution;
4. measured release and stable Home/clear state;
5. final confirmation that the UTM fixture is clear;
6. a verified downstream handoff.

This design does not invent a new disposal policy. It supervises the existing
`clear_utm_to_disposal` Skill.

## Overlay Contract

The new code-owned contract uses a schema such as
`atr.manipulation_agentic_task.v1` and contains:

- stable `task_id` and `skill_id`;
- ordered phase definitions;
- phase owner (`agentic`, `skill`, `vision`, or `interlock`);
- requirement class (`required_locked` or `runtime`);
- accepted evidence schema and freshness/identity requirements;
- bounded success, retry, recovery, stop, and blocked routes;
- verified next agent and handoff status.

Task profiles keep the current policy path, policy type, robot profile, timing,
camera, and rollout safety settings. The overlay references the selected task
profile; it does not copy those settings into a second store.

The selected `skill_id` defaults to the existing task ID for backward
compatibility. Existing saved profiles continue to load without migration.

## Runtime Composition

At run start, Manipulation Agent resolves the existing task/profile exactly as it
does today, then resolves the matching overlay definition. The current preflight,
rollout call, status refresh, completion handling, post-place interlock, SARM
result, decision, and report are retained.

The overlay composes those existing outputs into one phase-state record:

- current and completed phases;
- required locked gates;
- evidence accepted or rejected for each gate;
- retry/recovery recommendation;
- terminal status;
- downstream handoff eligibility.

The overlay is fail-closed. An unknown task definition, skipped required phase,
missing mandatory evidence, stale identity, robot-not-clear state, or unresolved
stop prevents `ready_for_equipment`.

No LLM decides whether a required gate passes. The LLM may continue formatting a
bounded task instruction, while deterministic code evaluates all phase and gate
transitions.

## UTM Entry And Placement Gates

Mandatory Vision evidence must be bound to the current run and specimen, must be
fresh within the existing observation contract, and must identify the intended
checkpoint. The two checkpoints have different temporal meaning:

- `utm_entry`: permission/evidence for entering the UTM work envelope;
- `utm_post_place`: specimen correctly located on the platen after release while
  the robot is Home/clear.

Evidence from one checkpoint cannot satisfy the other. The post-place gate also
requires the existing measured post-place interlock before a snapshot is accepted.

If mandatory Vision is temporarily unavailable, the task becomes blocked and
requests recovery/operator attention. It does not silently fall back to equipment
telemetry or policy completion alone.

## Lab Equipment Boundary

The Manipulation Agent emits `ready_for_equipment` only after every required
manipulation phase and gate succeeds. Lab Equipment Agent then follows its saved
Profile-bound Skill Flow.

Its actual workflow is represented as equipment steps including:

1. move jigs for the next specimen;
2. start the test;
3. detect contact and establish the relative Stroke reference according to the
   selected method;
4. run to the method target;
5. observe automatic Height return;
6. save and validate Raw Data CSV;
7. select Next Test without saving the current test;
8. automatically open to the configured robot-clearance Height.

Force, Stroke, Height, speed, threshold, travel, and clearance values are read
from the selected method/equipment result. Recorded example values are displayed
as current applied values or evidence and are never embedded as task constants.

Each existing Equipment Skill Flow block may retain its own optional Vision Slot.
Those switches only control equipment-concurrent observation for that block. They
do not alter the already-completed mandatory UTM entry or placement gates.

## Recovery And Stop Behavior

Recovery remains bounded by the current Manipulation Agent, LeRobot bridge, and
Guardian mechanisms. The overlay selects from declared outcomes rather than
generating arbitrary motion:

- retry current observation when evidence is missing but motion is safely stopped;
- request existing rollout status/stop handling when execution is active;
- request the existing bounded recovery path when SARM reports recoverable drift;
- stop and require operator attention for identity mismatch, anomaly, unsafe UTM
  entry, failed release/Home interlock, or indeterminate robot state;
- never advance to Lab Equipment Agent from a blocked manipulation task.

## Persistence And Compatibility

Overlay definitions are code-owned alongside the Manipulation module definition.
Operator-editable runtime settings remain in the existing Manipulation Agent task
profiles. There is no second editable task-profile database.

Backward compatibility rules:

- existing `task_id`, `skill_id`, API payloads, and saved task profiles remain
  accepted;
- if an existing request omits overlay metadata, the server resolves it from the
  task ID;
- report additions are additive;
- the existing LeRobot GUI can run the same profile and policy;
- compatibility `robot.pick_place` remains under the same required handoff gates;
- existing equipment per-step Vision settings are unchanged.

## UI Projection

The Manipulation Agent UI and runtime reports show the overlay above the existing
Skill details:

- Agentic Task name and terminal intent;
- ordered phases and current phase;
- locked badges for UTM entry and post-place verification;
- the underlying Skill ID, profile, policy, and rollout status;
- recovery/blocked reason;
- downstream handoff eligibility.

Locked mandatory gates are informational and cannot be toggled. The Lab Equipment
Agent editor continues to expose its existing per-step optional Vision switches.
The wording must visually distinguish `Mandatory manipulation verification` from
`Optional equipment-step Vision`.

## Evidence And Reports

`manipulation_report` and `robot_task_result` gain additive overlay fields:

- `agentic_task` with schema, task ID, phase state, and terminal status;
- `skill_execution` referencing the existing skill, profile, policy, and session;
- `mandatory_gates` with checkpoint, evidence identity, freshness, and result;
- `handoff_eligibility` with explicit missing requirements;
- `equipment_concurrent_vision` as a downstream configuration summary only.

The existing execution trace, post-place interlock, Vision context, SARM output,
and evidence references remain intact. GUI surfaces render these authoritative
fields rather than inferring phase completion from prose.

## Failure Codes

The overlay introduces stable failure categories while preserving existing lower
level details:

- `AGENTIC_TASK_DEFINITION_MISSING`;
- `MANDATORY_UTM_ENTRY_NOT_VERIFIED`;
- `MANDATORY_POST_PLACE_NOT_VERIFIED`;
- `MANDATORY_VISION_IDENTITY_MISMATCH`;
- `RELEASE_HOME_INTERLOCK_NOT_READY`;
- `REQUIRED_PHASE_SKIPPED`;
- `DOWNSTREAM_HANDOFF_BLOCKED`.

These codes describe supervisory failure. They do not replace detailed LeRobot,
camera, or equipment failure codes.

## Verification

### Contract tests

- both existing task IDs resolve to one code-owned overlay;
- existing Skill IDs and task profiles remain unchanged;
- required locked gates cannot be disabled by profile or API input;
- equipment-concurrent Vision settings never satisfy mandatory manipulation gates;
- unknown task/phase definitions fail closed.

### Manipulation Agent tests

- a valid UTM-entry signal advances to placement execution;
- missing, stale, or mismatched UTM-entry evidence blocks entry/handoff;
- post-place evidence is rejected before measured release and Home/clear state;
- valid post-place evidence after the interlock emits `ready_for_equipment`;
- compatibility and LeRobot execution paths obey the same overlay gates;
- existing SARM and stop/recovery behavior remains reachable;
- disposal cannot start without equipment-complete and safe-access evidence.

### API and persistence tests

- old saved Manipulation profiles load without migration or data loss;
- existing request payloads resolve the overlay by task ID;
- new report fields round-trip through the bridge and Runtime IDE projection;
- mandatory gate fields are read-only;
- existing Equipment Skill Flow Vision switches preserve their stored values.

### Browser tests

- the Agentic Task overlay appears above existing Skill/runtime details;
- locked mandatory gates have no editable checkbox;
- optional equipment-step Vision switches remain independently editable;
- UI copy uses Force, Stroke, and Height without adding a transport label;
- handoff cannot display ready while any required phase is incomplete.

## Acceptance Criteria

The change is complete when the existing Manipulation Agent and LeRobot Skills run
through the additive overlay, UTM entry and post-place verification are mandatory
and non-toggleable, Lab Equipment per-step Vision remains optional, recorded
method values remain configurable, and only a fully verified manipulation result
can hand off to Lab Equipment Agent.
