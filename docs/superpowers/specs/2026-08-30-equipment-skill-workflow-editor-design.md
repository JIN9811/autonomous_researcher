# Equipment Skill Sequential Workflow Editor Design

## 1. Purpose

Equipment Skill authoring currently converts a Windows demonstration into a
Linux-owned `workflow.json`, compiles that workflow into deterministic Windows
program segments, validates the exact package, and deploys the result to one
selected worker. The runtime already understands action and wait primitives,
but users cannot inspect or revise the generated sequence before deployment.

This change adds a sequential Workflow Editor to Skill Management. It exposes
the generated steps, permits bounded edits, and preserves the existing
compile, validate, deploy, and execute boundaries. Compile and validation
remain backend stages, but are not exposed as separate Skill Management
buttons.

## 2. Scope

The first version is strictly sequential. It does not add IF nodes, arbitrary
graph edges, loops, parallel branches, or user-authored Python.

Supported step families are:

- pointer actions: click, double click, drag, and scroll;
- keyboard actions: press, hotkey, and write;
- timer wait: wait for a fixed duration;
- image wait: wait until a stored image locator is visible;
- text wait: wait until configured text is visible when the worker capability
  is available;
- file wait: wait until a path pattern exists and is stable;
- state wait: wait until a declared program or equipment state is observed;
- checkpoint: capture bounded screen/state evidence without changing control.

Each wait step owns its timeout and polling interval. The Windows worker polls
until that monotonic deadline; it does not create a branch or a second nested
retry loop. Exhaustion stops the deterministic sequence and returns bounded
evidence to the existing Linux Equipment Agent recovery boundary.

## 3. Skill Management Entry Point

Skill Management keeps its existing exact-version selector and action row. A
compact Workflow Editor icon button is placed immediately before Deploy:

```text
Refresh | [Workflow Editor icon] | Deploy
```

The button is disabled until an exact Skill version is selected. Activating it
opens a dedicated browser window for that exact `skill_id@version`; it does not
replace the Equipment Workspace page.

Deploy is one user operation with three ordered backend stages: compile the
saved canonical workflow, validate the exact compiled package, then transfer
and register that same package and its locator assets on the selected Windows
worker. A compile or validation failure prevents transfer and focuses the
responsible workflow step. Deploy does not execute the Skill. Test/Execute
remains a separate Main Progress operation.

## 4. Editor Layout

The editor uses one vertically ordered sequence, not a canvas graph.

### 4.1 Header

The fixed header shows:

- Skill ID and version;
- lifecycle and dirty state;
- selected equipment profile;
- source recording ID;
- estimated minimum and maximum duration;
- Save Draft, Check Workflow, and Close controls.

`Check Workflow` performs immediate schema and asset checks without compiling
or transferring the Skill. Saving marks the package dirty. The next Deploy
automatically compiles and validates the saved revision before transfer.

### 4.2 Step list

Every step is a numbered card with a stable `step_id`, type icon, concise
summary, and status badge. Cards support drag reorder, keyboard reorder,
duplicate, delete, and insert-before/after. Only one card is expanded at a
time so long workflows remain usable.

Action cards expose only fields relevant to their action. Image-based cards
show the locator crop, hash, recorded coordinate fallback, confidence, and a
Replace Locator control. Wait cards show timeout and polling. Checkpoint cards
show the evidence label and capture types.

### 4.3 Step palette

An Add Step control opens a compact palette grouped into Action, Wait, and
Evidence. Adding a step inserts it after the current selection or at the end
when no step is selected.

### 4.4 Test controls

The editor supports schema validation without equipment access and a bounded
single-step test for a deployed worker. A live single-step test requires the
same explicit confirmation and bridge checks as existing live execution. It
must never execute neighboring steps.

## 5. Canonical Data Contract

`workflow.json` remains the Linux-authoritative editable representation. Each
step has the following common envelope:

```json
{
  "step_id": "step-003",
  "label": "Wait for test completion",
  "kind": "wait_until_image",
  "action": {
    "action": "wait_until_image",
    "target": "test_complete",
    "image_candidates": [],
    "timeout_s": 300,
    "poll_interval_s": 0.5,
    "required": true
  },
  "checkpoint_after": true
}
```

The editor never writes compiled `programs/*.json` directly. Save writes the
canonical workflow, recalculates hashes, clears stale `program_ids`, and moves
the package back to an editable annotated lifecycle. The compile stage inside
Deploy is the only path that emits Windows programs.

## 6. Version and Concurrency Rules

- Draft and annotated packages may be edited in place before deployment.
- Compiled or validated packages may be edited, but Save invalidates their
  compiled programs and validation result.
- A deployed or disabled exact version is immutable. Opening it in the editor
  is read-only until the user creates a new version.
- Save uses an expected workflow SHA-256. A stale browser receives a conflict
  response instead of overwriting newer work.
- Every save appends a workflow-edited audit event containing old/new hashes,
  changed step IDs, editor source, and timestamp.
- Deploy records compile, validation, and transfer as separate backend events
  under one deployment operation ID so failures remain diagnosable.

## 7. API Boundaries

The dedicated window loads and saves through Linux APIs:

```text
GET  /equipment/skills/{skill_id}/{version}/workflow-editor
GET  /api/equipment/skills/{skill_id}/{version}/workflow
PUT  /api/equipment/skills/{skill_id}/{version}/workflow
POST /api/equipment/skills/{skill_id}/{version}/workflow/validate
POST /api/equipment/skills/{skill_id}/{version}/workflow/steps/{step_id}/test
```

The PUT request includes `expected_workflow_sha256` and the complete ordered
step list. Partial reorder endpoints are avoided so one save is atomic and
auditable.

The editor route encodes the exact Skill identity in the URL. Opening a second
Skill creates a separate window, and saving one window cannot change the
selection or workflow loaded by another window.

## 8. Validation and Compilation

Validation rejects:

- duplicate or missing step IDs;
- unsupported action types or fields;
- missing locator hashes or locator files;
- non-finite, negative, or excessive durations;
- unbounded waits;
- invalid polling values;
- unsafe paths or unresolved runtime placeholders;
- workflows exceeding configured step or payload limits;
- direct edits to deployed versions.

Deployment first compiles the ordered steps into the existing deterministic
Windows action schema and then validates that exact output. Long workflows may
still be segmented at safe existing boundaries, but their logical order
remains unchanged. Transfer starts only after both stages succeed.

## 9. Runtime Behavior

Normal execution remains deterministic and does not call an LLM. Timer and
until-wait steps run on the Windows worker with monotonic deadlines. Image
waits poll the declared locator without retaining an unbounded screenshot
history. A terminal `llm_recovery` policy returns bounded evidence to the Linux
Equipment Agent; it does not run a model on Windows.

Runtime progress reports the current `step_id`, elapsed time, remaining
timeout, and latest observation. Stop and E-Stop use the existing control path
and interrupt waits promptly.

## 10. Error Handling

- Schema errors are shown on the affected card and prevent Save or Deploy.
- Missing locator assets prevent validation and deployment.
- Worker capability mismatches prevent single-step live tests and deployment.
- Wait timeout exhaustion produces one stable failure code with step ID.
- Browser closure does not alter an unsaved package.
- Network interruption during Save cannot leave a partially written workflow.

## 11. Test Strategy

### Unit tests

- canonical schema normalization for every step family;
- timeout and polling validation;
- stable reorder and duplicate-step rejection;
- lifecycle invalidation after edits;
- optimistic-concurrency conflict handling;
- compile parity with existing action/wait primitives.

### API integration tests

- exact Skill workflow load/save/validate;
- deployed-version immutability;
- save followed by one Deploy request that compiles, validates, and transfers;
- single-step test cannot execute adjacent steps;
- locator replacement and missing-asset failure;
- audit and hash updates.

### Browser tests

- Workflow Editor icon placement immediately before Deploy;
- no separate Compile or Validate controls in Skill Management;
- disabled state without a selected Skill;
- dedicated-window launch with exact Skill identity;
- add, reorder, edit, save, reopen, and persistence;
- long workflows remain usable at 1920x1080;
- validation errors focus the affected card.

### End-to-end acceptance

Create a harmless desktop Skill containing an action, timer wait, image-until
wait, and checkpoint. Open it from Skill Management, edit and save it, press
Deploy once, and execute it through the GUI. Verify that the single Deploy
operation compiles, validates, and transfers the same revision in order; also
verify exact step order, runtime wait progress, artifacts, audit hashes, and
that the deployed package cannot be edited in place.

## 12. Non-Goals

- conditional IF nodes;
- arbitrary graph editing;
- loops or parallel execution;
- code injection or arbitrary shell commands;
- replacing the Runtime IDE;
- moving Skill authority or LLM inference to Windows.
