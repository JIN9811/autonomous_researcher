---
doc_type: reference
subtype: system
status: review
authority: descriptive
audience:
  - researcher
  - artifact_evaluator
  - operator
  - integrator
scope:
  - paper
  - hardware
  - deployment
summary: Defines ATR deployment roles, optional services, hardware boundaries, and the evidence needed to claim a validated topology.
source_of_truth:
  - app/bootstrap.py
  - configs
  - device_bridges
  - Pyautogui_server_for_window
  - web
last_verified: 2026-08-09
verified_against: 0b7627b
paper_section: appendix_hardware_and_deployment
research_questions:
  - RQ3
  - RQ4
claim_ids:
  - C-SAFE-LIVE-01
  - C-PLAT-EXT-01
related_docs:
  - docs/paper/04_platform_architecture.md
  - docs/paper/07_reproducibility.md
  - docs/paper/08_safety_ethics_and_limitations.md
supersedes: []
---

# Appendix B: Hardware and Deployment

## Summary

ATR can place the primary application, models, graph storage, remote GUI
workers, and laboratory devices on different hosts. A supported interface is
not the same as a validated deployment; each result must name the topology it
actually used.

## Scope

This appendix describes deployment roles and paper evidence requirements. It
does not publish private network addresses, credentials, or a universal
installation recipe.

## Source of Truth

Bootstrap/configuration sources, bridge implementations, the Windows worker,
and web/API surfaces at baseline `0b7627b` define the available roles.

## Deployment Roles

| Role | Responsibility | Typical boundary | Required evidence for a claim |
|---|---|---|---|
| Primary application host | FastAPI, orchestrator, agents, local state, operator workspaces | Local process and configured services | OS/Python/dependencies, server command, graph/modules, logs |
| Model host/service | Local managed model or remote inference provider | Model API or managed process | Provider/model/version, readiness, generation config, latency protocol if measured |
| Knowledge backend | Durable local records and optional graph service | Service/repository interface | Backend/version, health, sync/receipt state, data snapshot |
| Remote Windows worker | Allowlisted desktop/equipment automation | Authenticated bridge | Worker version, capability list, target application, proof and stop path |
| Device host/bridge | Printer, robot, camera, instrument, or analysis service | Provider-specific bridge | Device/profile/firmware, calibration, dry run, raw response/proof |
| Browser client | Operator review and control | HTTP/API and rendered UI | Browser/driver, viewport, route, server mode, trace/screenshots |

## Local Inspection Topology

Tier 0 requires only a repository checkout, compatible Python environment, and
Graphviz. It does not require a model, graph database, browser, Windows worker,
or physical equipment. Optional service unavailability is therefore not a Tier
0 defect unless the documentation falsely claims it is mandatory.

## Remote Windows Worker Boundary

The Windows worker enables allowlisted GUI and equipment workflows on a host
that owns the target application. A paper record must identify the worker
software/configuration and capability without publishing private endpoints or
credentials. Recorded image-locator or automation skills remain bounded
actions, not arbitrary desktop authority.

The operator must be able to observe and stop the target application. A remote
worker timeout with uncertain GUI/device state requires review before replay.

## Physical Device Boundary

A logical bridge method does not establish device availability. A live record
must state device model/profile, relevant firmware or service version,
calibration, consumables/specimen state, environmental conditions where
material, connection mode, operator, dry-run result, stop procedure, and proof
of external effect.

Simulator, emulator, and test-backend results must remain labeled as such even
when the same bridge interface is used.

## Optional Services

Model providers, Neo4j, analysis services, robotics stacks, slicers, and vendor
software may be optional for a selected reproduction tier. The system should
report unavailable or degraded state rather than silently changing the
evidence environment. A fallback creates a new evaluated configuration and
must be recorded.

## Network and Secret Handling

- Use configuration variables or secret stores; do not commit credentials.
- Bind services to the smallest required network scope.
- Authenticate remote workers and mutation-capable services.
- Allowlist commands and capabilities by effect, not only by URL.
- Preserve request identity, timeout, and proof across bridge boundaries.
- Exclude private hostnames, addresses, tokens, and certificates from public
  evidence.

## Deployment Claims

The checked-in topology figure documents available roles and links. It does
not certify high availability, secure multi-tenancy, offline operation, or
every operating-system combination. Such claims require environment-specific
tests, failure injection, and security review.

## Limitations and Known Gaps

The initial paper package has no canonical container image, infrastructure-as-
code deployment, compatibility certification, physical equipment bill of
materials, or paper-scoped live topology record.

## Verification

Reviewed on 2026-08-09 against bootstrap, configuration, bridge, worker, and
web source families at baseline `0b7627b`.

## Related Documents

- [Platform architecture](04_platform_architecture.md)
- [Reproducibility](07_reproducibility.md)
- [Safety, ethics, and limitations](08_safety_ethics_and_limitations.md)
