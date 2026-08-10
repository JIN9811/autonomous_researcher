---
doc_type: design
subtype: feature
status: review
authority: proposal
audience:
  - researcher
  - operator
  - developer
  - maintainer
scope:
  - objective_compiler
  - bo_workspace
  - objective_lifecycle
summary: Human-authored visual and JSON objective design that reuses the bounded objective compiler lifecycle.
decision_status: approved
related_docs:
  - docs/superpowers/specs/2026-08-09-llm-objective-compiler-design.md
  - docs/superpowers/plans/2026-08-09-llm-objective-compiler.md
  - docs/agents/bo_agent.md
supersedes: []
---

# Manual Objective Builder Design

## 1. Purpose

Researchers must be able to design an experiment objective without asking an
LLM to compose it. The BO Workspace will therefore expose two synchronized
manual authoring surfaces:

1. a visual expression-tree builder; and
2. an advanced `objective_spec.v1` JSON editor.

Both surfaces produce the same bounded declarative contract already used by the
LLM Objective Compiler. Manual objectives do not introduce another evaluator,
activation path, or BO integration. They pass through the existing Draft,
Validate, Preview, Approve, and Activate lifecycle.

## 2. Confirmed Decisions

1. The visual builder and JSON editor are both available.
2. The visual builder is template-free. It supports arbitrary nesting of the
   operators allowed by `objective_spec.v1`.
3. Visual edits update the JSON representation immediately.
4. JSON edits update the visual tree only after an explicit `Apply to Builder`
   action succeeds.
5. Invalid JSON never replaces the last valid visual tree.
6. Manual and LLM-authored objectives become equivalent after draft creation.
7. Manual input cannot contain Python, shell, Cypher, JavaScript, filesystem
   access, network access, or unregistered functions.
8. Metrics can only be selected from the active Metric Registry.
9. The server, not the browser, assigns lifecycle state, author provenance, and
   the next immutable version.
10. A manual objective cannot bypass validation, preview, operator approval, or
    run activation.

## 3. Selected Approach

The selected approach is a bidirectionally synchronized expression tree and JSON
editor backed by one canonical in-browser draft.

Alternatives were rejected as follows:

- independent form and JSON drafts can diverge and create ambiguous approvals;
- a free-form code editor violates the bounded execution model;
- a node-canvas graph adds interaction cost without improving the authoring of
  mostly hierarchical mathematical expressions.

The tree editor keeps the formula readable, supports arbitrary nesting, and
maps directly to the existing JSON AST.

## 4. User Experience

### 4.1 Authoring Modes

The Objective Compiler area gains three authoring modes:

- `AI Compose`: the existing natural-language composer;
- `Visual Builder`: direct structured editing;
- `Advanced JSON`: direct contract editing.

Switching between modes does not create another draft. Unsaved manual edits
remain in the browser while the operator switches between Visual Builder and
Advanced JSON. AI Compose remains an explicit replacement or revision action;
it does not silently overwrite manual edits.

### 4.2 Objective Metadata

The manual workspace exposes:

- objective name;
- objective description;
- objective direction: `maximize` or `minimize`;
- optional research intent note;
- objective id when creating a new objective;
- current objective id and version when revising an existing objective.

For a revision, the objective id is fixed. The server creates the next version.
The operator cannot overwrite an existing immutable version.

### 4.3 Visual Expression Tree

Each tree row shows:

- indentation and parent-child relationship;
- node type and operator;
- operator-specific fields;
- inferred unit or dimension when available;
- validation state;
- controls to add, duplicate, move, or delete the node.

Supported nodes are derived from the server-provided operator registry rather
than duplicated as an independent client allowlist. At minimum the builder must
cover every operator currently accepted by `objectives.schemas.ALLOWED_OPERATORS`.

Examples of node-specific controls:

- `metric`: Metric Registry selector;
- `literal`: finite numeric value and unit;
- arithmetic operators: ordered child nodes;
- `weighted_sum`: ordered terms and finite weights;
- `divide` and `ratio`: numerator, denominator, and explicit positive epsilon;
- `normalize`: child expression and supported normalization parameters;
- penalties: source expression, threshold or target, and weight;
- `clip`: source expression, lower bound, and upper bound;
- comparisons: left and right expressions;
- Boolean operators: ordered constraint children.

The root Expression accepts a numeric expression. Each Constraints entry accepts
a Boolean expression. Invalid parent-child combinations are blocked in the UI
and rejected again by the server.

### 4.4 Tree Operations

The operator can:

- add a compatible child;
- add or remove a constraint root;
- duplicate a subtree;
- move a node up or down among siblings;
- drag a node to another compatible parent;
- delete a subtree after confirmation;
- collapse or expand subtrees;
- load the currently selected objective version for revision.

Drag-and-drop is an ergonomic shortcut. All operations must also be available
as buttons so the builder remains keyboard-accessible and testable.

### 4.5 Advanced JSON

The JSON editor displays the complete canonical draft using stable indentation.
It provides:

- syntax feedback;
- `Format JSON`;
- `Apply to Builder`;
- `Restore Last Valid`;
- an error list containing JSON paths and messages.

`Apply to Builder` performs local shape checks and then server validation. Only
successful parsing replaces the visual tree. The JSON editor does not accept a
partial fragment; it edits one complete `objective_spec.v1` draft.

### 4.6 Draft Actions

`Create Manual Draft` submits the canonical draft to the server. On success the
existing objective lifecycle panel becomes authoritative. Validation, Preview,
Approve, and Activate continue to use the existing buttons and API routes.

The UI clearly distinguishes:

- unsaved browser edits;
- saved draft version;
- validated version;
- approved version; and
- active run binding.

## 5. Canonical State and Synchronization

The browser stores these independent values:

- `lastValidSpec`: the canonical structured object;
- `jsonBuffer`: the possibly invalid text in the JSON editor;
- `dirty`: whether the canonical object differs from the saved draft;
- `selectedObjective`: the server-persisted identity and version.

Synchronization rules:

1. Visual edit mutates a cloned tree, checks structural compatibility, replaces
   `lastValidSpec`, regenerates `jsonBuffer`, and sets `dirty=true`.
2. JSON typing changes only `jsonBuffer`.
3. `Apply to Builder` parses and validates `jsonBuffer`; success replaces
   `lastValidSpec`, while failure preserves the previous tree.
4. Loading a server version replaces both values after an unsaved-change
   confirmation.
5. Successful draft creation replaces both values with the server-normalized
   response and sets `dirty=false`.

The server response is authoritative for objective id, version, lifecycle,
registry version, author, and timestamps.

## 6. Backend Contract

### 6.1 Manual Draft Endpoint

Add one HTTP operation that accepts a complete proposed spec:

```text
POST /api/objectives/manual
```

Request:

```json
{
  "spec": {
    "schema_version": "objective_spec.v1",
    "objective_id": "specific-energy-objective",
    "name": "Specific energy absorption",
    "direction": "maximize",
    "expression": {
      "op": "metric",
      "metric_id": "specific_energy_absorption"
    },
    "constraints": []
  },
  "operator": "jin",
  "revision_of": null
}
```

Response:

```json
{
  "ok": true,
  "objective": {},
  "validation": {},
  "source": "manual"
}
```

The endpoint delegates to the Objective Service. It does not compile or
evaluate expressions itself.

### 6.2 Service Behavior

The Objective Service will expose a manual draft operation with these rules:

- force `schema_version=objective_spec.v1`;
- force `lifecycle=draft`;
- set `created_by=operator:<identity>`;
- set the active Metric Registry version;
- assign version `1` for a new objective id;
- assign `latest_version + 1` for a revision;
- reject creation when the id already exists unless `revision_of` identifies
  that same objective;
- reject client-supplied executable or unexpected fields through the existing
  bounded schema and compiler validation;
- persist a compose decision identifying manual authorship;
- return the normalized draft and validation result.

Manual draft creation may persist a structurally valid draft that has semantic
validation errors so the operator can inspect and revise it. It must reject
malformed contracts and prohibited fields.

### 6.3 Authoring Metadata

Manual provenance is recorded in structured metadata:

```json
{
  "authoring_mode": "manual",
  "operator": "jin",
  "parent_objective_id": "specific-energy-objective",
  "parent_version": 1
}
```

LLM metadata remains unchanged. Downstream Analysis, Knowledge, and BO use the
objective id, version, and hash and do not branch on authoring mode.

## 7. Validation and Safety

Validation remains defense in depth:

1. The visual builder limits available node combinations.
2. JSON apply performs parsing and structural checks.
3. Manual draft creation runs Pydantic contract validation.
4. Objective compiler validation checks operators, metrics, units, domains,
   depth, node count, and numerical stability.
5. Preview evaluates bounded historical observations.
6. Approval and activation enforce persisted validation and preview gates.

No browser-generated validation result is trusted by the backend. A manually
authored objective cannot activate when validation is stale or its content hash
has changed.

## 8. Error Handling

Expected operator-facing errors include:

- invalid JSON syntax with line and column;
- missing required field with JSON path;
- incompatible child node;
- unknown metric or stale Metric Registry selection;
- incompatible physical units;
- invalid numerical domain or denominator policy;
- excessive AST depth or node count;
- immutable version conflict;
- unsaved edits before loading another objective;
- validation, preview, approval, or activation prerequisites not met.

Errors remain attached to the relevant tree row where possible and are also
listed in the validation panel. Network failure preserves all unsaved browser
state and allows a retry.

## 9. Persistence and Recovery

Only server-created drafts are durable objective versions. Unsaved browser edits
are session-local and restored after an ordinary page refresh using scoped
browser storage. They are cleared after successful draft creation or an explicit
discard action.

Server restart behavior is unchanged: persisted drafts, validations, previews,
decisions, bindings, and active objective state reload from the Objective Store.
Browser recovery data cannot replace a newer server version without explicit
operator confirmation.

## 10. Integration Boundaries

The feature changes only objective authoring. It does not change:

- deterministic objective compilation or evaluation;
- Analysis metric production;
- Knowledge observation persistence;
- BO objective-hash filtering;
- Guardian authority;
- physical device bridges;
- Live GUI objective runtime reporting.

After activation, a manual objective follows the same closed-loop path as an
LLM-authored objective:

```text
Manual Builder -> Draft -> Validate -> Preview -> Approve -> Activate
  -> Analysis evaluation -> Knowledge lineage -> BO -> Design
```

## 11. Verification

### 11.1 Unit and Service Tests

- a new manual objective receives version `1` and manual provenance;
- a revision receives the next immutable version;
- an existing id cannot be overwritten as a new objective;
- client lifecycle, author, registry version, and timestamps are normalized;
- prohibited fields and malformed AST nodes are rejected;
- semantically invalid but structurally valid drafts return validation errors;
- manual drafts use the same objective hash as equivalent LLM drafts.

### 11.2 API Tests

- the manual endpoint returns normalized draft and validation data;
- lifecycle routes accept a manual draft without special handling;
- invalid JSON contracts map to bounded `400` responses;
- version conflicts map to `409`;
- server errors never expose executable evaluation behavior.

### 11.3 UI Tests

- all authoring modes are present;
- arbitrary nested nodes can be added, reordered, duplicated, and removed;
- visual edits update JSON;
- valid JSON updates the tree;
- invalid JSON preserves the last valid tree;
- metric choices come from the Metric Registry;
- constraint roots only accept Boolean expressions;
- unsaved changes survive refresh and require confirmation before replacement;
- lifecycle actions operate on the saved server version, not unsaved edits.

### 11.4 Browser Audit

At 1920 x 1080 and a mobile-width viewport, verify:

- no labels, controls, tree branches, or validation messages overflow;
- deep trees remain usable through local scrolling and subtree collapse;
- keyboard controls provide every drag-and-drop action;
- Visual Builder and Advanced JSON preserve state while switching;
- the existing BO controls remain usable without excessive page length;
- dark-theme colors and focus states remain legible.

## 12. Acceptance Criteria

The feature is complete when an operator can build a nonlinear, constrained,
unit-valid objective without an LLM; inspect and edit the equivalent JSON; save
it as an immutable manual draft; validate and preview it; approve and activate
it; and observe the same Analysis, Knowledge, BO, and Live GUI behavior as an
equivalent LLM-authored objective.
