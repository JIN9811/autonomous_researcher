---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience:
  - user
  - contributor
  - maintainer
  - researcher
scope:
  - repository_changes
summary: Records public, research-artifact-relevant changes to ATR.
source_of_truth:
  - .git
last_verified: 2026-08-09
verified_against: beca57f
related_docs:
  - README.md
  - docs/paper/README.md
supersedes: []
---

# Changelog

This changelog highlights public, paper, runtime, safety, and reproducibility
changes. Detailed implementation history remains in Git.

## Unreleased

### Added

- Paper-first dual documentation structure under `docs/paper/`, with the
  closed-loop system contribution primary and the platform contribution
  secondary.
- Six editable Graphviz figures with deterministic SVG renderings.
- Research questions, evaluation matrix, reproduction tiers, safety/ethics
  limitations, interface/deployment appendices, and human-readable
  claim-evidence traceability.
- Machine-readable `docs/paper/artifact_manifest.yaml` with bounded inspection
  and documentation-test evidence.
- Paper-specific authoring and review rules in
  `docs/standards/paper_documentation_standard.md`.
- Publication validator and focused tests for file structure, narrative order,
  claim/evidence IDs, evidence paths and hashes, figure pairs, and private-path
  rejection.
- Public citation, contribution, security, license-status, and changelog files.
- Canonical References for all ten executable agents, covering actual roles,
  handoffs, contracts, internal execution, APIs, tools, services, device
  connections, safety gates, evidence, recovery, and operator surfaces.
- Cross-agent API and connection matrix for responsibility, contract, service,
  external-effect, safety, and recovery comparisons.
- Twenty-six agent architecture figures with editable Graphviz sources and
  checked-in SVG renderings: closed-loop and execution/effect views for all ten
  agents plus connection views for six bridge- or persistence-heavy agents.
- Root README and agent-index navigation tables linking every canonical agent
  Reference and figure directly.
- Automated documentation checks for required agent figure sources,
  renderings, embeddings, captions, and root README links.

### Changed

- Root English and Korean READMEs now act as synchronized paper-first landing
  pages while preserving links to detailed operator and developer guides.
- Documentation navigation now places the paper/reviewer path before domain
  runtime paths.
- Agent References now include step-to-state-to-evidence traces, connection
  lifecycles, uncertain-effect recovery rules, and visual authority boundaries.

### Evidence Boundary

- Architecture inspection supports the dated graph and route counts recorded
  in the paper package.
- Focused documentation tests support only the documentation contracts they
  execute.
- End-to-end scientific performance, comparative results, generalized safety
  effectiveness, and supervised live-hardware campaigns remain
  `not_evaluated`.

## Release History

No stable public release or archival DOI is declared. Add versioned sections
only when a release tag and its evidence package exist.
