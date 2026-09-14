<!-- atr-doc
doc_type: design
subtype: architecture
status: archived
authority: proposal
decision_status: approved
audience: [developer, maintainer]
scope: [runtime_ide, design, orchestrator, specimen, vision, manipulation, equipment, analysis, executable_modules]
summary: One executable definition shared by the agent backend and editable Runtime IDE.
related_docs:
  - docs/runtime/runtime_ide.md
  - docs/agents/design_agent.md
  - docs/agents/orchestrator_agent.md
supersedes: []
-->

> Archived development history (2026-09-14). Not the current implementation or acceptance contract. See the [archive index](../../README.md) for current references.


# Executable Agent Graph and Runtime IDE Contract

## Status at a Glance

| Item | Status |
|---|---|
| User approval | Approved in conversation, 2026-09-13 |
| Scope | Orchestrator plus installed Design, Specimen, Vision, Manipulation, Equipment and Analysis internals; shared extension contract |
| Authority | One executable graph, not a separate diagram or inferred checkpoint chain |
| Physical effects | No hardware validation or device-path changes in this migration |
| Application | Existing validate/version/activate path; running definitions remain pinned |

## Summary

The user requires frontend graph edits to change backend execution and backend
execution-definition edits to change the frontend. The pre-migration five-area display
did not satisfy this: it connected ordered descriptive checkpoints, while actual
work occurs separately in agent `run()` methods. Replace that source discrepancy,
not just line geometry. Retain existing algorithms and owner boundaries.

## Architecture and Contracts

Add `module.execution_graph` with schema `ax4lab.execution_graph.v1`, an `entry`
node ID, `nodes`, `edges`, and `terminals`. Each node declares `id`, `handler`,
`label`, `area`, optional `llm`, `config`, and presentation `position`. Each edge
declares `source`, `target`, `on` (an operation outcome, such as `next`, `accepted`
or `blocked`), and `kind` (`execution`, `validation`, or `evidence`).

Backend operation catalogs bind allowlisted IDs to existing owner functions;
they declare input dependencies, outputs, outcomes and accepted configuration.
Node IDs and edge declarations are shared by execution, trace events, IDE and
document SVGs. Never infer actual edges or relation kinds from array order or
responsibility colors. Node position never changes execution.

The graph runner validates definitions before any operation, executes only
declared edges and existing registered owner functions, and returns the original
AgentResult contract. Initial scope is acyclic graphs; existing bounded LLM
tool/retry loops remain inside their real decision operation, visibly labeled as
composite rather than inventing individually executable internal nodes. Reject
unknown handlers/configuration, dangling edges, unreachable nodes, cycles,
ambiguous/incomplete outcomes and routes violating required input dependencies.
Failure/cancellation must terminate the current traversal; never replay a
successful owner operation to make the display look complete.

Design preserves deterministic-test vs real-LLM selection, accepted vs owner-
review branches, original candidate generation, finalization and archive wrapper.
Orchestrator preserves actual mission/plan construction before decision and its
existing snapshot/followup/decision-record/result functions. No direct bridge
access, new device actions, or inferred readiness. Five responsibility areas are
presentation groups; an area without a separate operation explains where its
checks actually live. Do not create fake nodes just to fill five areas.

Owner catalogs additionally expose `implementation_structure`, keyed by registered
operation handler, with source-bound internal nodes and call/validation/evidence
relationships. These are displayed beside the executable nodes in the same canvas.
Dashed CODE boxes inspect the existing implementation; they cannot be connected as
extra commands, serialized as execution nodes or painted as independently done.
Repeated/added/rebound operation instances receive their own matching relationships.
High is each agent's bounded LLM reasoning and decision layer. Middle is software
processing, API/tool dispatch and internal workflow supervision. Low is the actual
device/bridge execution boundary, not numerical computation or local queries.
Guardian / Safety and Knowledge / Evidence are cross-cutting responsibilities.
Software-only agents may have an empty Low area. Composite owner operations stay
intact in Middle, with their actual model decisions exposed as High CODE nodes;
classification must never split handlers or change call order, tools or handoffs.
Use **LLM** on the actual High decision and **LLM call** on the calling process.
The latter supplies decision context and consumes the response; it does not imply
file containment, Middle-level reasoning, or a model call in every mode. Keep
the existing background responsibility areas and source-bound call relationships.
Legacy modules use `metadata.control_view.areas` and optional source-bound
`checkpoint_details`, keyed by `phase:step_id`. Those details are display-only;
legacy checkpoint IDs, ordering, serialization and runtime handlers stay unchanged.
Document SVGs share this structure but use a separate light document theme, not the
Runtime IDE's dark theme.

Outcome labels such as `blocked`, `next`, and `accepted` use compact capsules
anchored to their owning edge. Collision avoidance searches along the same Bezier
curve instead of moving labels onto an unrelated canvas grid. Preserve label
selection and route editing; verify curve attachment and node clearance after
zooming. Label placement does not alter outcomes or execution routing.

The Orchestrator execution graph covers its `run()` operation boundary. Existing
program-core Chat/Setup semantic intake is not rerouted through a mission run to
make the diagram appear broader; document that boundary explicitly.

Existing stage-level pre-execution, Guardian, handoff, approval, archive and mode
policies remain authoritative. A migrated agent must not run its old decorative
internal-step walk and then run the real graph again. Unmigrated modules retain
their existing behavior. Orchestrator remains part of the program core.

Migrated modules retain the handler of their catalog owner; an unrelated handler
cannot coexist with a graph that claims to execute Design/Orchestrator operations.
Generic handler overrides remain available for unmigrated modules.

Equipment applies this contract without flattening its nested Profile Skill
Flow. `equipment.task` and `equipment.deliver` are the executable Middle
operations; source-bound CODE relationships expose the real High LLM decisions,
Middle software, Low Windows/local worker boundary and cross-cutting
Guardian/Evidence internals. The editable module graph and the read-only
eight-block Skill Flow are separate projections of separate contracts.

Analysis applies the contract with `analysis.task` and `analysis.deliver` as its
two composite Middle operations. Its High CODE nodes show actual bounded LLM
decisions; numerical processing and the CAE computation bridge stay Middle; Low
is empty because a solver is not a device controller. Guardian/Evidence remain
cross-cutting. The installed package composes CAE and its internal CalculiX
provider without activating the shared PINN bridge or changing foreground BO,
background worker, admission, queue or cancellation semantics.

## Frontend and Application

The existing Runtime IDE module canvas projects the executable definition. Edges
round-trip with exact source, target, outcome and kind. The inspector edits
registered operations, supported configuration, labels and responsibility. Save
and activation use current endpoints; Validate rejects invalid drafts without
writing or silently repairing them. GET and explicit reload obtain backend
changes. Dirty drafts are never silently overwritten; revisions/conflicts are
visible. Closing a tab is not deactivation. Running invocations/loops use pinned
definitions; an idle change applies through the existing next-run boundary.

A catalog-backed Equipment tab always uses this generic executable/source-bound
renderer. Profile/Skill Flow refresh may update its separate workspace but must
not replace the module graph or baseline. Legacy Equipment definitions without
an `execution_graph` retain the earlier shared Skill Flow projection.

The backend dry-run API must clearly describe structural validation/path
enumeration if it does not execute the owner functions. Test evidence separately
executes the real graph with hardware boundaries denied and provider responses
simulated. It must not misrepresent a structural preview as successful execution.

## Acceptance Criteria

1. Baseline successful and blocked results remain equivalent for both agents.
2. A valid edge/order change saved through the existing API demonstrably changes
   execution order of real registered operations; array reordering alone does not.
3. Backend graph changes appear on GET/reload and round-trip through the editor.
4. Every execution trace node/edge corresponds to the shared definition; no
   phantom checkpoints or duplicate agent execution.
5. Invalid handlers/dependencies/branches/cycles, failed saves and busy activation
   cannot partially apply. Running definitions remain unchanged.
6. Existing virtual, real-printer and physical-print policy tests run with denied
   equipment transport. Any registered-model verification records every attempt
   separately and makes no physical-equipment claim.
7. Rendered node/port/edge editing, long labels, legend and narrow viewport
   navigation work. Documentation SVGs use explicit executable edges.
8. Agent docs, Runtime IDE reference and future modularization contract state
   achieved scope and remaining composite boundaries accurately.

## Equipment Implementation Evidence — 2026-09-13

Equipment's installed graph, source relationships, generated light-theme SVG,
module asset admission, report/card preservation, host timer boundary and IDE
Skill Flow separation are covered by focused Node and Python tests. A controller
browser inspection at 1920×1080 confirmed the generic Equipment internal map,
the separate eight-block Flow workspace, and the Package-to-Windows/PyAutoGUI
bridge internals after cache-busted reload. The corrected Live check also
rendered the original Equipment cards and eight-step Flow, preserved Design →
Equipment owner switching, and reported no console warning or error.

An unchanged second guarded registered-model run completed through the next
Design with 34 actual saved-provider calls across all ten required owners, zero
physical calls and no denied effects. The first attempt stopped at Knowledge
after a response violated the required search-before-read identity contract;
Guardian correctly blocked before BO. Both attempts are retained, so the record
shows a successful virtual cycle and the observed stochastic failure rather than
claiming universal model reliability or physical validation.

## Analysis Implementation Evidence — 2026-09-13

Analysis now uses the same installed executable/source catalog for backend,
generic five-area IDE canvas and light document SVG. The two composite operations
and source-bound CODE relationships preserve High actual LLM decisions, Middle
processing/CAE computation, an empty Low device area and cross-cutting
Guardian/Evidence. `analysis@1.0.0` composes `cae@1.0.0`, whose internal provider
is CalculiX; the shared PINN bridge remains inactive.

The module frontend owns the existing Analysis report/dashboard composition.
Four FEM panels now use independent common dashboard-card wrappers while the host
retains one controller, read-only polling, selection and in-place updates. Focused
Node and guarded Python owner, asset, source-symbol and renderer tests pass. The
scoped GPT-5.5 Analysis path reached BO readiness with two actual decisions and
without waiting for FEM; the separate background resource-held two-loop test also
passed. Both used non-physical boundaries. A whole real-API virtual cycle has not
passed because two attempts stopped at upstream review/recovery gates before
Analysis, so this evidence does not claim a complete cycle or hardware validation.

## Non-goals

No arbitrary Python-to-graph extraction, new solver/model/provider, graph-wide
agent migration, bridge refactor, new orchestrator route, live server restart,
commit or push. Work in the user's current checkout; preserve prior changes.
