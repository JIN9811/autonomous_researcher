---
doc_type: reference
subtype: api
status: review
authority: descriptive
audience:
  - researcher
  - artifact_evaluator
  - developer
  - integrator
scope:
  - paper
  - interfaces
  - schemas
summary: Maps paper-level ATR components to their current interface, schema, policy, and evidence boundaries.
source_of_truth:
  - agents
  - orchestrator
  - graphs/modules
  - device_bridges
  - knowledge
  - app/main.py
last_verified: 2026-08-09
verified_against: 0b7627b
paper_section: appendix_interfaces
research_questions:
  - RQ1
  - RQ2
  - RQ3
  - RQ4
claim_ids:
  - C-SYS-ARCH-01
  - C-PLAT-EXT-01
related_docs:
  - docs/paper/02_system_architecture.md
  - docs/paper/04_platform_architecture.md
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/runtime/current_code_snapshot.md
supersedes: []
---

# Appendix A: Interfaces and Contracts

## Summary

This appendix connects the paper abstraction to repository interface families.
It is a map, not a generated API specification. Exact payload fields remain in
code schemas, manifests, and endpoint responses. The canonical per-agent role,
API, connection, effect, and recovery contracts are maintained in the
[Agent Reference Index](../agents/README.md) and compared in the
[Agent API and Connection Matrix](../agents/agent_api_connection_matrix.md);
this appendix summarizes those boundaries for the paper instead of duplicating
them.

## Scope

Included are system-critical agent/stage, orchestrator, Guardian, device/model,
knowledge, graph/module, and operator interfaces. The appendix does not list
all 346 FastAPI routes individually.

## Source of Truth

The `agents/`, `orchestrator/`, `graphs/modules/`, `device_bridges/`,
`knowledge/`, and `app/main.py` sources at baseline `0b7627b` are authoritative.

## Contract Map

| Paper component | Repository boundary | Input category | Output category | Policy/evidence boundary |
|---|---|---|---|---|
| Orchestrator graph | `graphs/configs/atr_closed_loop.yaml`, runtime compiler | Orchestrator state and current stage | Next node/state/terminal route | Checkpoint and transition evidence |
| Supervisor | `orchestrator/supervisor.py` | Run context, handoff, candidate, Guardian decision | Routed handoff and context | No direct device bypass |
| Domain agents | `agents/*_agent.py`, module manifests | Typed stage context | Domain artifact and handoff | Schema/policy validation |
| Guardian | `policies/guardian_gate.py` | Action/risk/evidence context | Continue, stop, review, or error | Decision record and operator boundary |
| Model routing | `backends/`, agent context/bootstrap | Task and bounded prompt/input | Provider response normalized to caller contract | Readiness and priority lease where configured |
| Device bridges | `device_bridges/` | Capability-oriented action | Status, artifact, proof, or error | Allowlist, auth, dry run, timeout |
| Knowledge service | `knowledge/service.py` and repositories | Validated event/query/review request | Context, report, graph update, receipt | Ontology, ledger, outbox, bounded query |
| Graph/module management | graph/module APIs and manifests | Versioned configuration or draft | Validation, dry run, saved/activated state | Active-run and handler constraints |
| Operator workspaces | FastAPI routes, templates, static clients | Review/configuration/action intent | Rendered state and API result | Server policy remains authoritative |

## Handoff Properties

A paper-relevant handoff SHOULD expose:

- run and cycle identity;
- source and target stage/component;
- schema or contract version;
- objective and applicable constraints;
- input artifact references;
- decision and approval references;
- output artifact references;
- error or uncertainty state;
- timestamps and provenance.

Not every internal object uses one universal schema. Evaluation must check the
concrete handoff used by the selected scenario.

## API Families

The current route surface groups runtime/run/events/approvals, graphs/modules,
knowledge/evolution, equipment workers, printers, robotics, optimization,
analysis, and operator pages. The current code snapshot records counts and
representative responses. Routes are implementation interfaces; they are not
independent paper contributions.

## Versioning and Compatibility

- Graphs and modules use stable IDs and versioned configuration.
- Evidence payloads SHOULD declare schema versions.
- Provider-specific device/model details stay behind adapters.
- Removing or changing a field used by a stage requires migration or explicit
  incompatibility.
- Optional fields MUST NOT silently become required at runtime.
- An extension must fail closed when a required capability or policy contract
  is unavailable.

## Failure Contract

Failures should be machine-identifiable and operator-readable. The runtime must
distinguish invalid input, unavailable capability, denied action, timeout with
known no-effect, timeout with uncertain effect, external failure, evidence
persistence failure, and terminal policy stop. Collapsing these into one error
prevents safe resume and meaningful evaluation.

## Limitations and Known Gaps

This appendix does not freeze the complete API or schema set. Some historical
or optional interfaces have different maturity and test coverage. A submission
artifact may need generated OpenAPI/schema exports pinned to the release
commit.

## Verification

Interface families were reviewed on 2026-08-09 against baseline `0b7627b` and
the current code snapshot.

## Related Documents

- [Agent Reference Index](../agents/README.md)
- [Agent API and Connection Matrix](../agents/agent_api_connection_matrix.md)
- [System architecture](02_system_architecture.md)
- [Platform architecture](04_platform_architecture.md)
- [Current code snapshot](../runtime/current_code_snapshot.md)
