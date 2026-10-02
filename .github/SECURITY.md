---
doc_type: standard
subtype: safety
status: active
authority: normative
audience:
  - user
  - operator
  - contributor
  - security_researcher
scope:
  - repository_security
  - vulnerability_reporting
summary: Defines private vulnerability reporting and safe disclosure boundaries for ATR software and device integrations.
related_docs:
  - README.md
  - CONTRIBUTING.md
  - docs/paper/08_safety_ethics_and_limitations.md
supersedes: []
---

# Security Policy

## Supported State

This repository is under active development and has no published stable or
long-term-support release. Security fixes are applied to the active branch at
maintainer discretion. This policy does not certify the system for unattended,
hazardous, clinical, or production use.

## Reporting a Vulnerability

Use GitHub private vulnerability reporting for this repository when available:

<https://github.com/JIN9811/autonomous_researcher/security/advisories/new>

If that channel is unavailable, contact a repository maintainer through a
private channel before sharing technical details. Do not open a public issue
containing:

- exploit steps or proof-of-concept code;
- credentials, tokens, private keys, certificates, or private endpoints;
- personal or confidential data;
- details that could trigger unsafe device, desktop, robot, printer, or
  laboratory-equipment behavior.

Include the affected commit, component, environment, impact, preconditions,
reproduction steps that avoid unnecessary external effects, and any known
mitigation. State clearly whether physical equipment or a remote worker was
involved.

## Response Expectations

The project does not currently promise a fixed response or remediation time.
Maintainers should acknowledge a valid private report, assess impact and
affected versions, coordinate a fix and disclosure window, and credit the
reporter when requested and appropriate.

## High-Risk Areas

Pay particular attention to:

- authentication and allowlists for remote workers and device bridges;
- commands that can produce physical, desktop, printer, or robot effects;
- Guardian, operator-approval, dry-run, stop, and resume boundaries;
- ambiguous timeouts that could repeat an external action;
- artifact path traversal, upload/download, and archive handling;
- API keys, model-provider secrets, vendor credentials, and private endpoints;
- raw model or GUI input reaching command, Cypher, file, or device execution;
- knowledge provenance, audit ledger, outbox, and receipt integrity;
- mutation-capable browser workspaces and cross-site request protections.

## Deployment Responsibilities

Operators must apply least privilege, network segmentation, authenticated
bridges, secret management, allowlisted capabilities, equipment interlocks,
and laboratory-specific hazard controls. Test mode, schema validation, model
confidence, Guardian approval, or a dry run does not replace physical safety
controls.

Stop and review any operation whose external effect is unknown. Do not retry a
potentially completed physical action until state is independently verified.

## Disclosure and Safety Boundary

Coordinate public disclosure after affected users have a reasonable mitigation
path. Security research must not access data or systems without authorization,
degrade services, or operate physical equipment outside an approved protocol.
