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
  - docs/README.md
supersedes: []
---

# Changelog

This changelog highlights public, paper, runtime, safety, and reproducibility
changes. Detailed implementation history remains in Git.

## Unreleased

### Added

- [Retained 15-observation campaign audit](https://github.com/JIN9811/autonomous_researcher/blob/862f36a/docs/paper/evidence/2026-09-28-campaign-archive-audit.md), distinguishing accepted measurements from failed attempts, recoveries, and unsupported claims of unattended operation.
- Screenshot-based GUI reference and bilingual tutorials for the existing application, with capture conditions and publication manifests.
- Earlier one-cycle integration demonstration (`E-LIVE-LOOP-002`) for
  `run-20260907T043145Z-f6152b`: measured compression CSV, placement/clearance
  verification, Analysis-to-BO feedback, and next-design entry. Includes a
  public artifact hash index, explicit mixed-mode limitations, and synchronized
  evaluation/README navigation. Documentation only; no runtime changes.

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
- Twenty-nine agent architecture figures with editable Graphviz sources and
  checked-in SVG renderings: closed-loop and execution/effect views for all ten
  agents plus nine connection views (including the supplementary BO view).
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
- Supervised hardware operation and retained multi-cycle measurement artifacts
  have dated evidence; see the campaign audit above. Controlled comparative
  scientific benefit, generalized safety effectiveness and reliability across
  independent campaigns remain unevaluated. Historical test results are not
  evidence that every current deployment is ready for hardware operation.

## Release History

No stable public release or archival DOI is declared. Add versioned sections
only when a release tag and its evidence package exist.
