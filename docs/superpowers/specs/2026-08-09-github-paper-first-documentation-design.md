---
doc_type: design
subtype: architecture
status: review
authority: proposal
audience:
  - researcher
  - reviewer
  - maintainer
scope:
  - github_publication
  - paper_documentation
  - reproducibility
summary: Paper-first GitHub documentation architecture that presents ATR primarily as an autonomous experimental system and secondarily as an extensible platform.
decision_status: approved
related_docs:
  - docs/standards/documentation_standard.md
  - docs/templates/document_types.md
  - docs/README.md
  - docs/runtime/current_code_snapshot.md
  - docs/superpowers/specs/2026-08-08-documentation-governance-design.md
supersedes: []
---

# GitHub Paper-First Documentation Design

## Summary

The public ATR repository will use a paper-first dual documentation structure.
The primary narrative presents ATR as a safety-gated closed-loop autonomous
experimental system. The secondary narrative presents the same implementation
as a reusable platform composed of agents, graph runtime, device bridges,
operator workspaces, knowledge infrastructure, and evidence contracts.

The repository landing page acts as a graphical extended abstract rather than
a feature inventory. Detailed scientific argument and reproduction material
live under `docs/paper/`. Existing runtime, hardware, GUI, tutorial, and API
documents remain the platform documentation layer and are linked from the
paper narrative instead of being duplicated.

Working paper title:

> Autonomous Researcher Framework: A Safety-Gated Closed-Loop Multi-Agent
> System and Extensible Platform for Laboratory Automation

This Design is venue-agnostic. A later publication package may change title,
page limits, and supplementary formatting without changing the repository's
information architecture.

## Problem

ATR currently exposes a broad implementation surface: closed-loop experiment
planning, specimen design and fabrication, vision and robot manipulation,
equipment execution, analysis, Knowledge Graph updates, Bayesian optimization,
Guardian safety decisions, Runtime IDE tooling, and operator workspaces. A
flat README or feature-by-feature documentation list makes this appear to be a
collection of interfaces rather than one research system with a coherent
scientific claim.

The public documentation must let a reviewer answer, in order:

1. What scientific and engineering problem does ATR address?
2. What is the system-level contribution?
3. How does the autonomous closed loop work end to end?
4. Where are safety, operator authority, and evidence preserved?
5. What was evaluated, under which conditions, and with what result?
6. How can the reported result be reproduced or audited?
7. Which parts are reusable as a platform beyond the evaluated system?

The documentation must also prevent test-mode evidence, optional backends,
planned behavior, or unverified physical-device claims from being presented as
paper results.

## Goals and Non-goals

### Goals

- Present one system thesis before presenting platform features.
- Align README, paper documentation, code, configuration, tests, and artifacts.
- Give every paper claim a reproducible evidence path.
- Use figures and tables to explain relationships that prose would obscure.
- Preserve the existing documentation taxonomy and authority hierarchy.
- Make installation, evaluation, extension, and citation discoverable without
  forcing reviewers to read operator manuals.
- Support an archived, citable software release associated with the paper.
- Keep English as the canonical publication language while retaining Korean
  operational entry points.

### Non-goals

- The repository documentation does not replace the manuscript submitted to a
  journal or conference.
- The first rollout does not bulk-move existing domain documentation.
- GitHub Pages is not required for the first paper-ready release.
- The repository does not publish credentials, private device identifiers,
  local network topology, unpublished human data, or raw evidence that cannot
  be legally distributed.
- Documentation structure does not create evidence that has not been collected.
- A platform capability is not promoted to a scientific contribution merely
  because it exists in code.

## Current Context and Reference Projects

The design combines patterns observed in public scientific software projects:

- [NIMO](https://github.com/NIMS-DA/nimo) keeps a concise repository landing
  page and routes detailed use to hosted documentation and examples. ATR adopts
  the separation but keeps a stronger system argument in the landing page.
- [AlabOS](https://github.com/CederGroupHub/alabos) links the manuscript and
  documentation from a compact software repository. ATR adds explicit
  claim-to-evidence traceability because its system surface is broader.
- [ResearchAgent](https://github.com/JinheonBaek/ResearchAgent) follows a
  paper-oriented sequence of title, authors, overview, repository structure,
  running instructions, and citation. ATR adopts this recognisable scholarly
  order but adds architecture, safety, and evaluation evidence.
- [AI Scientist-v2](https://github.com/SakanaAI/ai-scientist-v2) places the
  paper, method, execution path, safety warning, FAQ, citation, and responsible
  use on the public landing page. ATR adopts the visible safety boundary and
  citation path without turning the README into the full manual.
- [Papers with Code research-code guidance](https://github.com/paperswithcode/releasing-research-code)
  recommends explicit dependencies, evaluation code, result tables, and exact
  commands that reproduce reported results. These become required ATR release
  gates.
- GitHub supports a root `CITATION.cff` that adds a “Cite this repository”
  entry and can name a paper as the preferred citation:
  [GitHub citation documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-citation-files).
- Zenodo can archive GitHub releases and assign persistent DOIs:
  [Zenodo GitHub integration](https://help.zenodo.org/docs/github/) and
  [release archival guide](https://help.zenodo.org/docs/github/archive-software/github-upload/).

## Options Considered

### Option A: Paper-first dual structure

Use README as a graphical extended abstract, `docs/paper/` as the scientific
narrative and reproduction package, and existing domain documentation as the
platform layer.

Advantages:

- makes the system contribution immediately legible;
- preserves practical documentation depth;
- avoids copying operator details into the paper narrative;
- supports both reviewers and platform users;
- permits publication-specific material to evolve without reorganizing code.

Cost:

- requires traceability rules to prevent the two layers from drifting.

### Option B: Manuscript-mirror documentation

Organize all public documentation as Introduction, Methods, Results, and
Discussion.

Advantages:

- very familiar to reviewers;
- manuscript sections map directly to repository files.

Rejected because installation, device operations, API reference, and extension
guides become difficult to discover. Manuscript revisions would also force
unrelated platform documentation changes.

### Option C: Platform-first documentation with a paper link

Lead with installation, workspaces, modules, and APIs, then link the paper.

Advantages:

- familiar to software users;
- simplest migration from the current repository.

Rejected because it makes the primary contribution look like a feature list
and gives reviewers no direct route from research claim to evidence.

## Decision

Adopt Option A: paper-first dual structure.

The public narrative has three layers:

| Layer | Primary purpose | Primary audience | Authority |
|---|---|---|---|
| Root `README.md` | Graphical extended abstract and research entry point | Reviewer and first-time researcher | Navigation with cited current facts |
| `docs/paper/` | Scientific argument, evaluation, reproduction, and limitations | Paper reader and reproduction researcher | Active Reference, Guide, and Evidence by file |
| Existing domain docs | Platform operation, interfaces, hardware, and extension | User, operator, and developer | Existing Standard/Reference/Guide hierarchy |

The system is always presented first. Platform extensibility is presented as
the mechanism that realizes and generalizes the system, not as an equal list of
features.

## Narrative Architecture

### Primary thesis

The repository will organize its evidence around this thesis:

> ATR integrates heterogeneous autonomous research functions into an
> operator-supervised, safety-gated, evidence-preserving closed loop whose
> modular runtime and device boundaries support reuse across laboratory tasks.

The thesis has four bounded research questions:

| ID | Research question | Contribution level |
|---|---|---|
| `RQ1` | Can ATR execute a complete heterogeneous research loop across planning, fabrication, observation, manipulation, equipment, analysis, knowledge, optimization, and safety stages? | Primary system contribution |
| `RQ2` | Does ATR preserve stage transitions, handoffs, artifacts, and safety decisions as auditable evidence across the loop? | Primary system contribution |
| `RQ3` | Do Guardian gates, device-specific readiness checks, and operator authority prevent unsupported transitions and unsafe live claims? | Primary system contribution |
| `RQ4` | Can graph/module configuration, typed APIs, device bridges, and workspaces extend the system without replacing the closed-loop runtime contract? | Secondary platform contribution |

Every result table, figure, experiment, and limitation MUST name at least one
research question. Platform documentation that does not support one of these
questions remains useful but MUST NOT be presented as paper evidence.

### Contribution statement

The README and manuscript-facing documents use this ordering:

1. A heterogeneous closed-loop autonomous experimental system.
2. Safety-gated execution with explicit human/operator authority.
3. End-to-end provenance across agent reasoning, device actions, analysis,
   Knowledge Graph updates, BO decisions, and artifacts.
4. A modular platform layer for graph, agent, model, tool, device bridge, and
   workspace integration.

## Root README Design

The canonical root `README.md` is English. `README.ko.md` remains a clearly
linked Korean operational entry point. The root README MUST be readable in five
minutes and SHOULD remain between approximately 1,500 and 2,500 words excluding
tables, code blocks, and references.

Required section order:

1. **Title and research identity**
   - working paper title;
   - one-sentence thesis;
   - Paper, Documentation, Reproduction, Release, Citation, and License links;
   - only badges that communicate release, test, documentation, DOI, or license
     state.
2. **Abstract**
   - problem, system, method, evaluation scope, and bounded conclusion;
   - 150–250 words;
   - no unverified superlatives.
3. **System at a glance**
   - Figure 1 graphical abstract;
   - one closed-loop sequence;
   - one concise explanation of operator and Guardian authority.
4. **Research questions and contributions**
   - the four RQs;
   - contribution table linked to implementation and evidence.
5. **System architecture**
   - Figure 2 layered architecture;
   - orchestration, agents, devices, data/evidence, and operator surfaces;
   - a short distinction between system and platform contributions.
6. **Closed-loop method**
   - actual stage order from checked-in graph configuration;
   - Figure 3 stage/data/evidence flow;
   - explicit stop/error/continue behavior.
7. **Evaluation and principal results**
   - result table organized by RQ;
   - link to full protocol and artifacts;
   - test-mode, simulation, and physical-device results labeled separately.
8. **Reproduce the reported results**
   - environment prerequisite;
   - one smoke command;
   - one evaluation command;
   - expected output and approximate resource/time envelope;
   - link to the full reproduction Guide.
9. **Platform capabilities**
   - compact matrix of modules, APIs, bridges, workspaces, and extension points;
   - no exhaustive endpoint list.
10. **Safety, limitations, and responsible operation**
    - test/live boundary;
    - physical-device authority;
    - known incomplete or environment-dependent functions;
    - security reporting link.
11. **Documentation map**
    - paper reader;
    - reproducer;
    - operator;
    - platform developer.
12. **Citation, release, license, and acknowledgements**
    - `CITATION.cff`;
    - paper and software citation distinction;
    - archived release DOI;
    - third-party systems and funding.

The README MUST NOT contain the full user manual, every API route, every GUI
page, internal implementation plans, or raw historical audit logs.

## Paper Documentation Structure

Create a curated publication layer without moving existing domain documents:

```text
docs/paper/
  README.md
  01_problem_and_contributions.md
  02_system_architecture.md
  03_closed_loop_method.md
  04_platform_architecture.md
  05_experimental_setup.md
  06_evaluation_and_results.md
  07_reproducibility.md
  08_safety_ethics_and_limitations.md
  09_claim_evidence_traceability.md
  appendix_a_interfaces.md
  appendix_b_hardware_and_deployment.md
  artifact_manifest.yaml
  assets/
    figures/
    tables/
```

### File responsibilities

| File | Responsibility | Primary document type |
|---|---|---|
| `README.md` | Paper documentation index and reading paths | `index/index` |
| `01_problem_and_contributions.md` | Problem boundary, related-system positioning, RQs, contribution claims | `design/architecture` until the manuscript baseline is frozen |
| `02_system_architecture.md` | Current components, ownership boundaries, data/control flow | `reference/system` |
| `03_closed_loop_method.md` | Current stage semantics, handoffs, state, event and artifact flow | `reference/system` |
| `04_platform_architecture.md` | Runtime, module, bridge, API, GUI, and extension contracts | `reference/system` |
| `05_experimental_setup.md` | Evaluation environments, datasets/specimens, modes, hardware, seeds, versions | `evidence/test_report` |
| `06_evaluation_and_results.md` | Protocols, baselines, ablations, metrics, results, and uncertainty | `evidence/test_report` |
| `07_reproducibility.md` | Clean-environment reproduction procedure and success criteria | `guide/how_to` |
| `08_safety_ethics_and_limitations.md` | Safety boundary, operator authority, disclosure, limitations, and failure scope | `standard/safety` or `evidence/audit` according to final content |
| `09_claim_evidence_traceability.md` | Claim-to-source-to-command-to-artifact matrix | `reference/schema` |
| `appendix_a_interfaces.md` | Selected API/event/schema contracts required to interpret results | `reference/api` |
| `appendix_b_hardware_and_deployment.md` | Evaluated deployment topology and device-specific boundaries | `reference/system` |
| `artifact_manifest.yaml` | Machine-readable IDs, hashes, commands, environments, and release locations | Manifest governed by the publication schema |

Mixed authority MUST be split. In particular, current system architecture and
future platform proposals MUST NOT share one active Reference.

## Figure System

Figures are explanatory evidence, not decoration. Every figure MUST have a
versioned editable source and a publication rendering. Vector SVG or PDF is
preferred for diagrams and plots; PNG is used only for screenshots or raster
camera evidence.

### Required figures

| Figure | Question answered | Required content | Placement |
|---|---|---|---|
| Figure 1: Graphical abstract | What does ATR do end to end? | objective, agents, physical/digital experiment, analysis, Knowledge/BO feedback, Guardian/operator loop | README and paper overview |
| Figure 2: Layered system architecture | What owns control, execution, evidence, and presentation? | operator layer, orchestration layer, agent/runtime layer, device/tool layer, evidence/data layer | README and architecture document |
| Figure 3: Closed-loop control and evidence flow | How do stages transition and what persists? | actual graph stages, dispatch/continue/stop/error, handoff payloads, events, artifacts | method document |
| Figure 4: Safety-gated action sequence | What prevents unsafe live execution? | operator confirmation, Guardian decision, bridge preflight, device gate, execution observation, recovery | safety document |
| Figure 5: Knowledge and optimization feedback | How does evidence influence the next experiment? | ledger, outbox, graph sync, retrieval, BO context, next Design handoff | method/results document |
| Figure 6: Evaluated deployment topology | What hardware/software environment produced the results? | hosts, OS boundaries, models, bridges, devices, network direction, optional services | experimental setup or appendix |

### Figure rules

- The same component name, stage color, and arrow meaning MUST be reused across
  all figures.
- Colors MUST remain distinguishable in grayscale and for common color-vision
  deficiencies; meaning MUST NOT depend on color alone.
- Control flow, data flow, evidence persistence, and optional integration MUST
  use different line styles and a visible legend.
- Implemented, evaluated, simulated, optional, and proposed components MUST be
  visually distinguishable.
- Captions MUST be understandable without the surrounding paragraph and MUST
  state the evaluated boundary where relevant.
- UI screenshots MUST show the actual committed interface and identify mode,
  date, commit, and whether data is recorded, simulated, or live.
- Raw Mermaid, Graphviz, plotting script, or editable design source MUST be
  committed beside or linked from the rendered asset.
- Paper figures MUST NOT embed secrets, LAN addresses, serial numbers, personal
  paths, or unpublished proprietary data.

## Table System

Tables provide exact mappings and comparisons. The following tables are
required unless a venue-specific manuscript combines them without information
loss.

| Table | Purpose | Minimum columns |
|---|---|---|
| Contribution matrix | Connect contributions to implementation and evidence | Claim ID, RQ, system component, novelty boundary, evidence |
| Agent and stage contract | Explain the closed loop without prose repetition | Stage, responsibility, input, output, tools/devices, next-stage authority |
| Safety gate matrix | Show when execution is permitted or blocked | Action, mode, operator gate, Guardian gate, device evidence, failure code |
| Evaluation matrix | Map experiments to research questions | Experiment ID, RQ, environment, baseline/ablation, metric, repetitions, artifact |
| Principal results | State results with uncertainty | RQ, metric, system result, comparator, uncertainty, evidence ID |
| Reproducibility matrix | Define what others need | Result ID, command, input, environment, expected output, time/resource estimate |
| Platform extension matrix | Support the secondary contribution | Extension unit, interface, validation gate, example, runtime effect |
| Limitations matrix | Bound claims explicitly | Limitation, affected claim, observed consequence, mitigation, remaining risk |

Result tables MUST distinguish:

- unit/integration verification;
- browser/UI verification;
- simulation or replay;
- test-mode system runs;
- live physical-device runs;
- manually inspected evidence.

Counts alone are not scientific results. Route, node, module, or test counts may
describe platform scale but MUST NOT be presented as system effectiveness.

## Claim-Evidence Traceability

Each manuscript-facing claim receives a stable ID such as `C-SYS-01`,
`C-SAFE-02`, or `C-PLAT-01`. `docs/paper/09_claim_evidence_traceability.md`
contains this schema:

| Field | Meaning |
|---|---|
| Claim ID | Stable identifier used in README, paper docs, and artifact manifest |
| Claim text | Bounded statement supported by evidence |
| RQ | Research question answered |
| Paper location | README/paper section and figure/table reference |
| Implementation source | Exact code and configuration paths |
| Verification command | Command that tests or reproduces the claim |
| Evidence ID | Stable artifact manifest identifier |
| Environment | test, simulation, replay, or named live setup |
| Verified commit | Commit hash used for the observation |
| Status | supported, partially supported, contradicted, or not evaluated |
| Limitation | Known boundary affecting interpretation |

No claim may be marked `supported` solely because the corresponding code path
exists. Evidence must record an executed verification method and result.

The machine-readable `artifact_manifest.yaml` contains, for each evidence ID:

```yaml
id: E-RQ1-001
claim_ids:
  - C-SYS-01
environment: test
verified_commit: 09bbe32
command: .venv/bin/pytest tests/unit/test_langgraph_runtime.py -q
inputs:
  - graphs/configs/atr_closed_loop.yaml
outputs:
  - artifacts/paper/E-RQ1-001/pytest.log
sha256:
  artifacts/paper/E-RQ1-001/pytest.log: release-generated-sha256
result: pass
```

The paths illustrate the required release layout. Generated release records
MUST replace `release-generated-sha256` with the computed digest and MUST fail
validation if the command output is not archived at the declared path.

## Evaluation and Reproducibility Design

### Evaluation hierarchy

The evaluation package SHOULD build evidence from least to most environment
dependent:

1. schema, graph, module, and contract tests;
2. closed-loop test-mode execution;
3. fault injection and safety-gate rejection;
4. replay and recovery;
5. browser/operator workflow verification;
6. simulation-backed robot/device execution;
7. live physical-device trials where publishable evidence exists.

The paper MUST state which levels were executed. Missing higher levels are
reported as limitations, not inferred from lower-level success.

### Reproduction tiers

| Tier | Outcome | External requirements |
|---|---|---|
| Tier 0: inspect | Read paper docs, schemas, figures, and archived evidence | GitHub browser only |
| Tier 1: software smoke | Install and run contract/unit verification | CPU development environment |
| Tier 2: system test | Execute a bounded closed-loop test-mode scenario | Supported model/API or deterministic fixture |
| Tier 3: simulation | Exercise available robot/device simulation paths | Documented simulator and assets |
| Tier 4: physical replication | Reproduce selected live device experiments | Named hardware, safety approval, local calibration |

Each tier MUST have prerequisites, exact commands, expected artifacts, success
criteria, time estimate, and stop/recovery procedure.

### Result integrity

- The reported commit and release tag MUST be immutable.
- Evaluation inputs, configuration, seed where applicable, dependency versions,
  and hardware must be recorded.
- Repeated measurements MUST report sample count and uncertainty.
- Failed and blocked trials MUST be retained in the evidence summary when they
  affect the conclusion.
- Large datasets, model weights, raw videos, and complete run archives SHOULD
  be stored in a suitable research repository or release asset, not committed
  indiscriminately to Git.
- Every externally stored artifact MUST have a stable link and checksum in the
  artifact manifest.

## Public Repository Surface

The paper-ready root SHOULD expose:

```text
README.md
README.ko.md
CITATION.cff
LICENSE
CONTRIBUTING.md
SECURITY.md
CHANGELOG.md
REQUIREMENTS.md
docs/
  README.md
  paper/
  standards/
  runtime/
  knowledge/
  gui/
  hardware/
  tutorials/
```

`CITATION.cff` describes the software release and uses `preferred-citation` for
the paper once bibliographic data is fixed. Before publication, it may cite the
software release without inventing journal or DOI fields.

`SECURITY.md` includes vulnerability reporting and an explicit physical-device
safety disclosure. `CONTRIBUTING.md` links the Documentation Standard and
defines how code changes update References, Guides, paper claims, and evidence.

GitHub Pages MAY later render only the curated README and `docs/paper/` layer.
It MUST NOT automatically publish every internal package instruction or
historical document merely because it resides under `docs/`. GitHub warns that
Pages sites can be publicly accessible even when the backing repository is
private, so the selected publishing source must contain only public material:
[GitHub Pages publishing documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

## Language Policy

- English is canonical for `README.md`, `docs/paper/`, citation metadata,
  releases, figures, table labels, and reproduction commands.
- Korean is maintained for operator Guides where it materially improves safe
  local use.
- `README.ko.md` MUST clearly identify whether it is a translation, an
  operational guide, or both.
- Scientific claims and numerical results MUST have one canonical English
  source. Translations link to that source rather than maintaining independent
  result values.

## Publication Safety and Privacy Gate

Before public push or archived release, scan the complete tracked file set for:

- passwords, tokens, private keys, cookies, and API credentials;
- personal names or identifiers not approved for publication;
- absolute home paths such as `/home/USER/`;
- local LAN addresses, device serial numbers, MAC addresses, and broker
  credentials;
- proprietary device files or third-party assets without redistribution rights;
- raw participant or human-subject data;
- unpublished reviewer material;
- generated run logs containing sensitive prompts or environment values;
- large binary artifacts that belong in release or research storage.

`.env.example` may contain variable names and non-secret example values only.
Runtime `.env`, local memory, live credentials, and raw run directories MUST NOT
be part of the release.

Redaction MUST preserve scientific interpretability. For example, a private
device identifier may become a stable published pseudonym such as
`printer-01`, while model, firmware, calibration, and protocol details needed
for reproduction remain documented where licensing permits.

## Release, Citation, and Archival

The paper artifact uses a tagged release whose commit is recorded in all active
paper References and Evidence.

Recommended sequence:

1. Freeze the evaluated commit.
2. Run publication safety and documentation validation.
3. Generate figures, tables, and artifact manifest from frozen evidence.
4. Run reproduction tiers in clean environments.
5. Create a release candidate and conduct an independent reproduction review.
6. Publish the final GitHub release and immutable tag.
7. Archive the release through Zenodo or a discipline-appropriate repository.
8. Add the release DOI to `CITATION.cff`, README, paper availability statement,
   and artifact manifest.
9. When the paper receives permanent bibliographic metadata, update
   `preferred-citation` without rewriting the archived software release.

Software DOI and paper DOI are distinct research objects and MUST be linked by
an explicit relationship rather than treated as interchangeable.

## Documentation Data Flow

```text
checked-in code/configuration
        |
        v
active runtime References -----> claim-evidence traceability
        |                                  |
        v                                  v
evaluation commands ------------> artifact manifest + results
        |                                  |
        v                                  v
docs/paper scientific narrative -> root README graphical abstract
        |                                  |
        +----------------+-----------------+
                         v
               tagged release + DOI
```

The root README summarizes; it does not originate facts. Numerical claims flow
from evaluated Evidence through the traceability matrix. Current architecture
claims flow from active References. The paper layer links both.

## Failure and Safety Design

Documentation validation must fail the paper release when:

- a required paper document or local link is missing;
- a claim marked supported lacks implementation source, command, evidence ID,
  environment, or verified commit;
- a result references an artifact absent from the manifest;
- an archived artifact checksum does not match;
- README result values disagree with the canonical results table;
- a live-device claim is backed only by test or simulation evidence;
- a proposed component is drawn as implemented;
- citation metadata names a version or DOI that does not match the release;
- public safety/privacy scanning finds unresolved sensitive material.

Documentation validation does not determine scientific validity. Human review
is still required for experiment design, statistical interpretation, novelty,
ethics, licensing, and physical-device safety.

## Acceptance Criteria

- A reviewer can identify ATR's system thesis, four RQs, primary contributions,
  main architecture, evaluation boundary, principal results, limitations, and
  reproduction entry point from the root README.
- Platform capability appears after the system argument and is explicitly
  labeled as the secondary contribution.
- `docs/paper/` contains the defined scientific narrative and reproduction
  structure without duplicating full operator manuals.
- Every supported paper claim maps to source, verification command, evidence,
  environment, and commit.
- Every principal result maps to an RQ and reports its evaluation mode.
- Required figures have editable sources, rendered publication assets,
  self-contained captions, and consistent visual semantics.
- Required tables distinguish implementation scale from scientific results.
- A clean reader can perform Tier 0 and Tier 1 reproduction; higher tiers state
  exact external dependencies and safety boundaries.
- `CITATION.cff`, license, contribution, security, release, and archival paths
  are visible from the repository root.
- The public release contains no secrets, personal paths, private device
  identifiers, or unlicensed artifacts.
- Existing active References and Guides remain the authority for platform
  behavior; paper documents link rather than fork those facts.

## Open Questions

No architecture-blocking questions remain. Venue-specific page limits,
anonymous-review rules, paper author order, final experimental sample counts,
and final DOI values are release inputs. They do not change the approved
paper-first dual documentation structure.

## Related Evidence and Plan

- [Documentation Standard](../../standards/documentation_standard.md)
- [Document Type Templates](../../templates/document_types.md)
- [Documentation Governance Design](2026-08-08-documentation-governance-design.md)
- [Current Code Snapshot](../../runtime/current_code_snapshot.md)
- [Documentation Index](../../README.md)

An implementation plan is written only after the user reviews and approves this
Design document.

## Limitations and Known Gaps

- The design specifies documentation and release architecture; it does not
  assert that all paper experiments or physical-device trials are complete.
- Current repository documents include historical and internal material outside
  the first governance manifest. Public-release classification remains work to
  be planned.
- The final venue may require an anonymous repository or supplementary archive;
  that packaging layer must preserve the same claim/evidence identifiers.
- GitHub rendering alone is not an archival guarantee; the tagged release and
  research repository provide the persistent record.

## Verification

This Design was prepared on 2026-08-09 against the active ATR Documentation
Standard, current repository entry points, and public primary documentation
from NIMO, AlabOS, ResearchAgent, AI Scientist-v2, GitHub, Zenodo, and the
Papers with Code research-code release guidance linked above.

The Design preserves the previously approved seven-type documentation taxonomy
and does not require runtime code or physical-device behavior changes.

## Related Documents

- [Documentation Standard](../../standards/documentation_standard.md)
- [Document Type Templates](../../templates/document_types.md)
- [Documentation Governance Design](2026-08-08-documentation-governance-design.md)
- [Current Code Snapshot](../../runtime/current_code_snapshot.md)
- [Documentation Index](../../README.md)
