# Lab Equipment Agentic Task Overlay Design

## Objective

Add a workflow-level Agentic Task above the existing Profile-bound Lab Equipment
Skill Flow so the recorded TRAPEZIUMX-V test cycle is the canonical execution
sequence without replacing the current Equipment Agent, Skill packages, Vision
Slots, Skill Runtime, or PyAutoGUI bridge.

The workflow-level task owns sequence, required entry conditions, screen-state
postconditions, recovery routing, CSV validation, and terminal handoff. Existing
composite blocks continue to own one bounded Agentic Task, one Equipment Skill,
and one optional per-step Vision Slot.

## Source Of Truth

The recorded TRAPEZIUMX-V interaction and its extracted reference bundle are the
physical workflow source of truth:

`references/trapeziumx_v_equipment_agent/`

Older contracts remain applicable only where they do not conflict with this
recorded flow. The important evidence is the visible screen transition at the end
of each step, including changed values, status text, active controls, disabled
controls, and icon state.

Force, Stroke, and Height are equipment readings. Their acquisition transport is
outside this workflow vocabulary. Example thresholds, travel values, speed, and
clearance values in the recording are current method/cell settings, not constants.

## Additive Architecture

The runtime hierarchy becomes:

1. **Workflow-level Agentic Task overlay**
   - selects the canonical UTM compression cycle;
   - validates the required upstream handoff;
   - advances through ordered flow blocks;
   - aggregates step evidence and recovery state;
   - emits the terminal data-ready or blocked handoff.
2. **Existing Profile-bound Equipment Skill Flow**
   - retains the ordered composite blocks;
   - retains each block's Agentic Task text;
   - retains each block's exact Skill binding;
   - retains each block's optional Vision Slot and bounded routes.
3. **Existing Equipment Skill Runtime and PyAutoGUI bridge**
   - compile and execute allowlisted deterministic UI actions;
   - capture screenshots, locator results, and execution evidence.
4. **Existing equipment and file adapters**
   - provide Force, Stroke, Height, result state, and exported CSV evidence.

No new agent, direct device path, second Skill registry, or second Vision runtime
is introduced.

## Scope Boundaries

This design changes Lab Equipment Agent orchestration only. It does not modify:

- Manipulation Agent task definitions, policies, or rollout behavior;
- robot motion or LeRobot Skill execution;
- the current manipulation-to-equipment handoff producer;
- the operator's one-time initial manual clearance setup;
- the existing per-step Vision enable/disable controls;
- the selected equipment method's Force, Stroke, Height, speed, or travel values.

The Lab Equipment Agent consumes the existing verified specimen/UTM handoff as a
required start condition. It does not reimplement Manipulation Agent verification.

## Canonical Workflow-Level Agentic Task

The canonical task ID is `run_utm_compression_cycle`. Its intent is:

> Accept one verified specimen already placed for UTM testing, execute the saved
> equipment preparation and test sequence, export and validate Raw Data CSV,
> prepare the equipment for the next specimen, and emit a bounded result handoff.

The task references one selected Equipment Profile and its existing Skill Flow.
It does not copy Skill versions, locator definitions, or Vision settings into a
second configuration store.

## Required Start Condition

Before the first equipment action, the overlay requires an existing handoff that
establishes:

- the current specimen/run identity;
- specimen placement at the UTM fixture;
- robot Home/clear state;
- permission for Lab Equipment Agent to begin;
- a terminal handoff status equivalent to `ready_for_equipment`.

This is a required, locked precondition. It has no ON/OFF option and is independent
from all Equipment Skill Flow Vision switches. Missing, stale, mismatched, or
blocked handoff evidence prevents equipment input.

The initial operator action that establishes a robot-entry clearance Height is a
one-time cell setup outside the repeating Agentic Task. The final workflow step
restores the configured clearance automatically for the next robot entry.

## Canonical Ordered Blocks

The selected Equipment Profile receives or references an ordered Skill Flow with
the following logical blocks. Exact Skill IDs and versions remain Profile-bound.

| Block | Agentic Task responsibility | Required completion evidence |
| --- | --- | --- |
| `prepare_next_specimen` | Invoke **Move Jigs for Next Specimen** after accepting the verified robot handoff. | command accepted and the preparation-state screen transition is visible |
| `start_test` | Invoke **Start Test** only after preparation completes. | test-running state, control/icon transition, or equivalent authoritative equipment state |
| `monitor_contact_and_run` | Observe contact detection, establish the relative Stroke reference according to the selected method, and monitor travel to the method target. | contact/run evidence and method-defined terminal condition; no hardcoded threshold or travel |
| `await_auto_return` | Wait for the equipment-controlled Height return after test completion. | stopped/returned state and Height consistent with the selected method/cell configuration |
| `save_raw_data` | Invoke the Raw Data CSV save action. | export action accepted and a concrete CSV artifact candidate exists |
| `validate_raw_data` | Validate the exported CSV before continuing. | readable, non-empty, identity-bound CSV with required columns/rows and no partial-write state |
| `advance_without_save` | Invoke **Next Test** while intentionally not saving the current test record. | next-test screen/state transition without a current-test save confirmation |
| `restore_robot_clearance` | Automatically open the jigs to the configured robot-entry clearance Height. | ready-for-next-specimen screen/equipment state and configured clearance reached |

The labels above describe logical responsibilities. Implementations bind each
block to existing or newly recorded versioned Equipment Skills through the current
Skill registry. They do not embed arbitrary UI scripts in the Agentic Task.

## Screen-State Transition Contract

Each UI-affecting block records both its precondition and postcondition. Completion
is based on the postcondition, not merely a successful click.

The block evidence may include:

- before/after screenshot references;
- matched locator ID and locator version;
- relevant button enabled/disabled state;
- active or inactive icon state;
- selected workflow/test state;
- visible status or confirmation text;
- displayed Force, Stroke, and Height values;
- equipment-side state returned by an existing adapter;
- bounded timestamps and run/specimen identity.

Each Skill package declares the postcondition it can prove. A click without a
recognized state change is `indeterminate` or `failed`, never `completed`.

The extracted transition images and locator crops are reference material for
authoring and testing Skill locators. They are not silently treated as live proof.

## Method-Driven Values

The workflow contract never fixes the recorded example values. It resolves the
active method/cell settings at runtime and records both intent and applied value:

- contact Force: detect specimen contact and establish the Stroke reference;
- target Stroke or travel: terminate the compression phase according to the method;
- return Height: confirm equipment-controlled automatic return;
- robot-entry clearance Height: restore sufficient clearance for the next robot
  approach;
- speed and other parameters: execute the selected method without shadow values.

Evidence includes the resolved current values so an operator can audit what was
applied. Missing or contradictory method values block the affected step instead of
falling back to recording-specific numbers.

## Existing Per-Step Vision Behavior

Every existing Equipment Skill Flow block keeps its current `vision.enabled`
switch, selected Vision task, and bounded outcomes. Vision may therefore be
enabled or disabled independently for each equipment step.

These switches apply only while Lab Equipment Agent executes its equipment flow.
They do not control, bypass, or satisfy the required upstream UTM-entry/handoff
condition.

When a block's Vision Slot is disabled:

- the Skill still requires its declared equipment/UI postcondition;
- Force, Stroke, Height, CSV, and GUI state remain authoritative where applicable;
- the block routes through its existing disabled/bypass behavior;
- the runtime report records that concurrent Vision was not requested.

When enabled, the existing Vision task and detected/not-detected/timeout/error
routes remain fail-closed according to the saved Profile flow.

## Overlay State Contract

The workflow-level overlay uses an additive schema such as
`atr.equipment_agentic_task.v1` with:

- `task_id` and selected `profile_id`;
- referenced Skill Flow ID and revision;
- run, loop, and specimen identity;
- required start-condition result;
- current, completed, and remaining block IDs;
- each block's Agentic Task, Skill execution, optional Vision result, and
  postcondition evidence;
- current method values as observed/applied runtime evidence;
- CSV artifact and validation state;
- recovery attempts and operator-attention reason;
- terminal status and downstream handoff eligibility.

The Profile-bound Skill Flow remains the sole editable source for block order,
Skill binding, Vision enablement, Vision task selection, and bounded routes. The
overlay snapshots the resolved flow revision for reproducibility.

## Runtime Composition

Lab Equipment Agent resolves execution in this order:

1. resolve the requested workflow-level Agentic Task;
2. resolve the selected Equipment Profile and its saved Skill Flow revision;
3. validate the locked upstream handoff;
4. validate every enabled block's Skill binding and optional Vision task before
   sending equipment input;
5. execute one block through the existing Equipment Skill Runtime;
6. evaluate its explicit UI/equipment postcondition;
7. execute the block's existing optional Vision Slot when enabled;
8. follow the saved bounded route;
9. checkpoint the overlay state and evidence;
10. continue, recover, block, or emit the final data-ready handoff.

The LLM may format bounded task text or recovery explanation. It does not invent
device actions, change method values, decide that a postcondition passed, or skip
a required block.

## CSV Save And Validation

Raw Data CSV is an explicit workflow block rather than an inferred side effect.
The save step must produce a concrete artifact candidate. Validation must complete
before **Next Test** is invoked.

Validation includes, where supported by the current export contract:

- path exists and is within the configured export boundary;
- file is stable rather than still being written;
- file is non-empty and parseable;
- expected Force, Stroke, and Height fields or mapped equivalents are present;
- row count is plausible for a completed test;
- run/specimen/test identity is attached to the artifact evidence;
- validation failure retains the current screen state for bounded retry or
  operator recovery.

The next-test action deliberately does not save the current test record. That
intent is explicit in the Agentic Task and Skill postcondition so a generic
save/close prompt handler cannot choose the opposite action.

## Recovery And Failure Handling

Recovery uses existing Equipment Agent, Skill Runtime, Guardian, and bridge
boundaries. The overlay permits only declared outcomes:

- retry a locator or observation within the Skill's bounded retry policy;
- retry CSV discovery/validation without repeating the physical test;
- resume from a checkpoint only when the live screen/equipment state matches the
  expected block precondition;
- stop and request operator attention for ambiguous prompts, contradictory state,
  unexpected motion, identity mismatch, or unknown application state;
- never rerun **Start Test** after physical motion has begun unless an explicit
  recovery contract proves the previous test did not start;
- never invoke **Next Test** before valid CSV evidence exists;
- never emit ready-for-next-specimen before the configured clearance is verified.

Stable workflow-level failure categories include:

- `EQUIPMENT_HANDOFF_NOT_READY`;
- `EQUIPMENT_FLOW_REVISION_INVALID`;
- `EQUIPMENT_STEP_POSTCONDITION_MISSING`;
- `EQUIPMENT_METHOD_VALUE_UNRESOLVED`;
- `EQUIPMENT_TEST_STATE_INDETERMINATE`;
- `RAW_CSV_EXPORT_NOT_FOUND`;
- `RAW_CSV_VALIDATION_FAILED`;
- `NEXT_TEST_TRANSITION_FAILED`;
- `ROBOT_CLEARANCE_NOT_RESTORED`.

Existing lower-level Skill, bridge, Vision, and locator failure details remain
attached rather than being replaced.

## Persistence And Compatibility

The workflow-level Agentic Task definition is code-owned and references the
current Profile-bound Skill Flow. It does not create a second editable workflow.

Compatibility rules:

- existing Equipment Profiles, Skill packages, versions, and flow revisions
  remain valid;
- existing `agentic.task`, `skill`, and `vision` composite block fields remain
  canonical;
- current per-step Vision switches retain their stored values;
- existing single-Skill/legacy execution remains available for Profiles not bound
  to `run_utm_compression_cycle`;
- new report fields are additive;
- existing PyAutoGUI bridge and allowlist validation remain mandatory;
- no Manipulation Agent source or profile migration is required.

## Agent Manager And Runtime IDE Projection

Agent Manager shows the workflow-level task above the existing Equipment Skill
Flow editor:

- task name, intent, Profile, flow revision, and terminal outcome;
- required upstream handoff as a locked precondition with no checkbox;
- ordered block progress;
- the existing Agentic Task, Skill, and optional Vision controls inside each block;
- declared UI/equipment postcondition and latest evidence;
- current applied method values;
- CSV save/validation state;
- recovery or blocked reason;
- ready-for-next-specimen status.

Runtime IDE and Equipment Bridge remain projections of the same authoritative
task/flow execution record. They do not introduce another editor or hidden Vision
toggle.

## Live GUI Equipment Workspace

The implementation extends the existing Lab Equipment dashboard in `/live`; it
does not create a separate Live GUI page or a second runtime state source. The
current Equipment Agent report selection, canonical runtime polling, report cards,
timeline, artifacts view, and global Pause/Resume/Safe Stop controls are reused.

When Lab Equipment Agent is selected, the report view contains:

1. **Cycle header**
   - `run_utm_compression_cycle`, selected Profile, flow revision, specimen/run
     identity, and overall state;
   - required upstream handoff shown as a locked gate;
   - bridge health and latest refresh time.
2. **Eight-step execution rail**
   - one node per canonical block in saved flow order;
   - waiting, active, completed, recovering, or blocked state;
   - underlying Skill ID/version;
   - optional Vision state shown inside the same block rather than as a mandatory
     global Vision score.
3. **Live equipment values**
   - current Force, Stroke, and Height;
   - current applied method targets/settings when available;
   - clear distinction between observed value and configured target;
   - no transport label.
4. **Screen transition evidence**
   - most recent before/after frame thumbnails or bounded references;
   - changed button, icon, status, and displayed-value evidence;
   - locator ID/version and postcondition result.
5. **Raw Data and next-specimen readiness**
   - export path, stability, parse/column/row validation, and artifact link;
   - Next Test transition status;
   - final robot-entry clearance state.
6. **Recovery boundary and handoff**
   - stable failure code, bounded retry status, and operator-attention request;
   - final data-ready eligibility and missing requirements.

The existing Live GUI header actions remain diagnostic (`TEST`, `OPEN`, and
`REFRESH`). Normal task execution continues through the orchestrator and Equipment
Agent; the dashboard does not add a direct Start Test or arbitrary click endpoint.
Global Pause, Resume, and Safe Stop continue to use the existing runtime command
path.

Live GUI may link to Agent Manager for editing the selected Profile flow. It does
not edit Skill bindings or per-step Vision switches inline, preventing runtime
observation from becoming a second authoring surface.

The Live GUI equipment progress renderer consumes the additive
`workflow_agentic_task`, `block_executions`, `method_values`, `raw_data_export`,
and `next_specimen_readiness` report fields. During compatibility runs where those
fields are absent, it retains the current canonical Skill Flow/lifecycle fallback.

## Reports And Handoffs

The existing Equipment Agent report gains additive fields:

- `workflow_agentic_task` with task schema, ID, Profile, flow revision, and state;
- `required_entry_gate` with upstream handoff identity and result;
- `block_executions` with Agentic Task, Skill, optional Vision, and postcondition;
- `method_values` with current observed/applied Force, Stroke, Height, and other
  selected-method settings;
- `raw_data_export` with artifact and validation evidence;
- `next_specimen_readiness` with next-test and clearance state;
- `handoff_eligibility` with explicit missing requirements.

The final data-ready handoff requires a completed physical test, valid Raw Data
CSV, successful Next Test transition, and verified robot-entry clearance. A
failed optional Vision Slot follows its configured route; a disabled optional
Vision Slot is recorded as disabled and is not itself a blocker.

## Verification

### Contract tests

- `run_utm_compression_cycle` resolves above one existing Profile-bound Skill Flow;
- overlay resolution does not copy or mutate Skill bindings or Vision switches;
- required upstream handoff has no editable enable/disable field;
- recorded example method values are absent from executable constants;
- Profiles not using the overlay preserve legacy behavior.

### Equipment Agent tests

- missing or mismatched `ready_for_equipment` evidence blocks before device input;
- all eight logical blocks execute in the saved order;
- a block cannot complete from click success without its postcondition;
- each existing per-step Vision switch independently controls only its own slot;
- disabled Vision still requires equipment/UI postcondition evidence;
- method values are resolved and reported without hardcoded defaults;
- test start is not repeated after motion evidence;
- CSV validation completes before Next Test;
- current-test save is not invoked during the Next Test transition;
- final handoff remains blocked until robot clearance is restored.

### Skill Runtime and bridge tests

- each bound Skill compiles through the existing allowlist boundary;
- before/after screen evidence and locator revision are retained;
- ambiguous application state produces a blocked outcome;
- checkpoint resume validates the current screen state;
- CSV artifact discovery rejects partial or out-of-bound files.

### API and browser tests

- Agent Manager displays the overlay above the existing flow editor;
- locked entry condition has no toggle;
- existing block Vision checkboxes preserve save/reopen behavior;
- each block displays its intended postcondition and observed transition;
- selecting Lab Equipment Agent in Live GUI renders the cycle header and eight-step
  rail from the authoritative report/flow order;
- Live GUI renders observed Force, Stroke, and Height separately from configured
  method targets;
- Live GUI renders screen-transition, Raw CSV, Next Test, and clearance evidence;
- Live GUI preserves the existing legacy progress renderer when overlay fields are
  absent;
- Live GUI adds no direct equipment click or duplicate flow-editing endpoint;
- Force, Stroke, and Height appear without a transport label;
- current applied values are identified as method/cell settings;
- Runtime IDE and Equipment Bridge show the same task, block, and terminal state.

## Acceptance Criteria

The change is complete when Lab Equipment Agent can supervise the recorded UTM
compression cycle through a workflow-level Agentic Task layered above the existing
Profile-bound Equipment Skill Flow, while preserving current Skill execution and
per-step optional Vision controls. Equipment execution must remain blocked without
the locked upstream handoff, every step must prove its screen/equipment
postcondition, Raw Data CSV must be validated before Next Test, and the final state
must restore configured robot-entry clearance without hardcoded recorded values.
The same authoritative execution state must be visible in the existing Live GUI
Lab Equipment dashboard with no duplicate authoring or direct-control path.
