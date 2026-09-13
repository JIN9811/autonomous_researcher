<!-- atr-doc
doc_type: design
subtype: architecture
status: active
authority: proposal
decision_status: approved
audience: [developer, maintainer]
scope: [runtime_ide, design, orchestrator, executable_modules]
summary: One executable definition shared by the agent backend and editable Runtime IDE.
related_docs:
  - docs/runtime/runtime_ide.md
  - docs/agents/design_agent.md
  - docs/agents/orchestrator_agent.md
supersedes: []
-->

# Executable Agent Graph and Runtime IDE Contract

## Status at a Glance

| Item | Status |
|---|---|
| User approval | Approved in conversation, 2026-09-13 |
| Scope | Orchestrator and Design internals; shared extension contract |
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
Low includes software functions and tools; Design's suitability decision is Middle.
Document SVGs share this structure but use a separate light document theme, not the
Runtime IDE's dark theme.

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

## Frontend and Application

The existing Runtime IDE module canvas projects the executable definition. Edges
round-trip with exact source, target, outcome and kind. The inspector edits
registered operations, supported configuration, labels and responsibility. Save
and activation use current endpoints; Validate rejects invalid drafts without
writing or silently repairing them. GET and explicit reload obtain backend
changes. Dirty drafts are never silently overwritten; revisions/conflicts are
visible. Closing a tab is not deactivation. Running invocations/loops use pinned
definitions; an idle change applies through the existing next-run boundary.

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
   equipment transport. No physical or live-model validation is claimed.
7. Rendered node/port/edge editing, long labels, legend and narrow viewport
   navigation work. Documentation SVGs use explicit executable edges.
8. Agent docs, Runtime IDE reference and future modularization contract state
   achieved scope and remaining composite boundaries accurately.

## Non-goals

No arbitrary Python-to-graph extraction, new solver/model/provider, graph-wide
agent migration, bridge refactor, new orchestrator route, live server restart,
commit or push. Work in the user's current checkout; preserve prior changes.
