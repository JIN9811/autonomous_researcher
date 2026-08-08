---
doc_type: standard
subtype: documentation
status: active
authority: normative
audience:
  - researcher
  - contributor
  - maintainer
  - reviewer
scope:
  - paper_documentation
  - public_repository_surface
  - claim_evidence_traceability
summary: Normative rules for authoring, reviewing, and releasing paper-facing ATR documentation.
related_docs:
  - docs/standards/documentation_standard.md
  - docs/templates/document_types.md
  - docs/superpowers/specs/2026-08-09-github-paper-first-documentation-design.md
supersedes: []
---

# Paper Documentation Standard

## Summary

This Standard governs the paper-facing documentation for Autonomous
Researcher Framework (ATR). It makes the system contribution primary, the
platform contribution secondary, and requires every public claim to expose its
evidence state. Its purpose is to let a reviewer distinguish implemented
architecture, tested behavior, simulated behavior, browser observations, and
live-hardware results without inferring more than the repository proves.

The uppercase terms `MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative.

## Normative Scope

This Standard applies to:

- `README.md` and `README.ko.md`;
- every Markdown document under `docs/paper/`;
- figures and tables under `docs/paper/assets/`;
- `docs/paper/artifact_manifest.yaml` and its evidence records;
- `CITATION.cff`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, and
  `LICENSE` where their contents affect paper readers or artifact reviewers.

The general metadata, lifecycle, path, and manifest rules in
`docs/standards/documentation_standard.md` continue to apply. When the two
Standards differ, this Standard governs the paper-specific presentation and
claim-evidence contract; the general Standard governs document taxonomy.

## Source of Truth

- Approved structure and narrative decision:
  `docs/superpowers/specs/2026-08-09-github-paper-first-documentation-design.md`
- General document governance: `docs/standards/documentation_standard.md`
- Current implementation facts: executable code and checked-in configuration
- Current measured snapshot: `docs/runtime/current_code_snapshot.md`
- Paper publication validator: `scripts/validate_paper_publication.py`
- General documentation validator: `scripts/validate_documentation.py`

## Contribution Priority and Argument Order

Paper-facing documents MUST present contributions in this order:

1. the laboratory-automation problem and evidence gap;
2. the safety-gated closed-loop multi-agent system;
3. evidence capture, auditability, and recovery boundaries;
4. evaluation status and limitations;
5. the platform and extension model.

The platform MUST be described as enabling and extending the system thesis. It
MUST NOT displace the system contribution through earlier placement, greater
visual prominence, or stronger unsupported language.

The canonical research questions are:

- `RQ1`: How does the system compose heterogeneous research stages into a
  complete, resumable closed loop?
- `RQ2`: How does the system preserve auditable evidence across decisions,
  execution, observation, analysis, and knowledge updates?
- `RQ3`: How do Guardian and operator gates constrain unsafe, uncertain, or
  irreversible actions?
- `RQ4`: How can new agents, devices, models, and workspaces be added without
  weakening the system contracts?

## Canonical Terminology

The first use in a document MUST be `Autonomous Researcher Framework (ATR)`.
Subsequent use MAY use `ATR`. The terms below have fixed meanings:

| Term | Required meaning |
|---|---|
| `system` | The closed-loop orchestrator, agents, gates, evidence flow, and recovery contracts |
| `platform` | The extension, backend, device, workspace, and deployment surfaces supporting the system |
| `stage` | One typed unit of the research loop |
| `agent` | A component responsible for one or more stage contracts |
| `gate` | A policy or human decision point that can block, approve, or redirect an action |
| `evidence` | A bounded observation with a command, environment, commit, inputs, outputs, and result |
| `live` | Execution against physical equipment or a production-equivalent external system |
| `simulation` | Execution using a declared simulator, emulator, or synthetic environment |
| `replay` | Deterministic or recorded-input execution without a new physical action |

`autonomous` MUST NOT imply absence of human oversight. A document using the
term MUST identify required approvals, stop paths, and unsupported autonomy.

## Paper Chapter Metadata

Every governed paper chapter MUST use the general YAML front matter and SHOULD
add:

```yaml
paper_section: system_architecture
research_questions:
  - RQ1
claim_ids:
  - C-SYS-ARCH-01
```

An active Reference or Guide MUST include `source_of_truth`, `last_verified`,
and `verified_against`. At initial publication, a complete chapter MAY remain
`status: review` while evidence is incomplete, but it MUST still state the
commit used for every code-backed observation.

`paper_section` MUST match the chapter responsibility rather than its file
number. `research_questions` and `claim_ids` MUST contain only identifiers
actually addressed in the body.

## Claim Classes and Identifiers

Each material claim MUST belong to one class and use a stable identifier:

| Prefix | Claim class |
|---|---|
| `C-SYS` | Closed-loop system architecture or method |
| `C-SAFE` | Safety, Guardian, approval, or recovery behavior |
| `C-TRACE` | Evidence, provenance, audit, or reproducibility behavior |
| `C-PLAT` | Platform, extension, backend, device, or workspace behavior |
| `C-EVAL` | Measured comparative, performance, or scientific result |
| `C-LIMIT` | Explicit limitation, contradiction, or unsupported boundary |

Identifiers MUST use uppercase ASCII, hyphen-separated scope, and a two-digit
or three-digit sequence, such as `C-SYS-ARCH-01`. Renaming a claim requires an
explicit mapping in the traceability chapter; an identifier MUST NOT be reused
for a different proposition.

Every claim in `docs/paper/artifact_manifest.yaml` MUST have exactly one status:

- `supported`: the stated scope follows from the referenced evidence;
- `partially_supported`: some scope, environment, or outcome remains unverified;
- `not_evaluated`: no qualifying evidence has been executed or recorded;
- `contradicted`: recorded evidence conflicts with the proposition.

`supported` and `partially_supported` MUST reference at least one evidence ID.
`not_evaluated` MUST be used instead of an empty cell, optimistic wording, or
an unqualified future tense.

## Evidence Classes and Records

Evidence identifiers MUST use one of these prefixes:

| Prefix | Environment |
|---|---|
| `E-INSPECT` | Static code, configuration, or repository inspection |
| `E-TEST` | Automated unit, contract, or integration test |
| `E-REPLAY` | Deterministic or recorded-input replay |
| `E-SIM` | Simulation or emulation |
| `E-BROWSER` | Browser-level workflow observation |
| `E-LIVE` | Supervised physical or production-equivalent execution |

Each machine-readable evidence record MUST contain:

- a unique `id`;
- an allowlisted `environment`;
- the `verified_commit`;
- the exact `command` or bounded manual protocol;
- repository-relative `inputs`;
- repository-relative `outputs` with lowercase SHA-256 digests;
- a non-empty `result`.

Evidence MUST NOT be promoted across environments. A passing inspection does
not become test evidence, a simulator result does not become live evidence,
and a browser rendering does not establish scientific efficacy.

## Academic Voice and Argument

Paper prose MUST:

- state the problem before the solution;
- identify the mechanism before claiming its consequence;
- separate observation from interpretation;
- use bounded verbs such as `implements`, `records`, `rejects`, `exposes`, or
  `was observed` for repository-backed facts;
- qualify inference with `suggests`, `is consistent with`, or `within the
  evaluated scope`;
- name the comparison basis whenever using `better`, `faster`, `safer`,
  `robust`, or `efficient`.

Paper prose MUST NOT use `proves`, `guarantees`, `fully autonomous`,
`production-ready`, `state of the art`, or causal language unless the cited
evidence and evaluation design establish that exact scope.

One paragraph SHOULD advance one primary proposition. A section SHOULD open
with its role in the overall argument and close with its evidence boundary or
transition to the next section.

## Quantitative Reporting

Every quantitative result MUST report:

- the metric name and unit;
- the evaluation environment;
- the denominator or sample size;
- the aggregation method where multiple observations exist;
- dispersion or uncertainty where scientifically relevant;
- the baseline or comparator where the text makes a comparison;
- the evidence ID.

SI units SHOULD be used. Non-SI device units MAY be retained when they are the
native equipment contract, with an SI conversion when interpretation depends
on it. Rates MUST state both numerator and denominator. Percentages MUST NOT be
reported without the underlying count. Rounded values MUST preserve enough
precision to reproduce the stated conclusion.

Architecture counts are dated observations, not performance results or stable
API guarantees.

## Headings and Chapter Structure

The canonical chapter order is:

1. problem and contributions;
2. system architecture;
3. closed-loop method;
4. platform architecture;
5. experimental setup;
6. evaluation and results;
7. reproducibility;
8. safety, ethics, and limitations;
9. claim-evidence traceability;
10. interface and deployment appendices.

Each chapter SHOULD contain `Summary`, `Scope`, `Evidence Basis` or `Source of
Truth`, its chapter-specific argument, `Limitations and Known Gaps`,
`Verification`, and `Related Documents`. Heading levels MUST NOT skip from H2
to H4. File numbers establish reading order; headings MUST remain semantic.

## Citations and Related Work

Claims about another system, paper, dataset, standard, or tool MUST cite its
primary source. A project repository MAY support implementation details but
MUST NOT replace the associated paper when the claim concerns scientific
results. Web access dates SHOULD be recorded for mutable pages.

Related-work prose MUST state the dimension of comparison and MUST NOT infer an
absent feature merely because it was not described. Quoted text MUST be brief,
necessary, and attributed. Bibliographic metadata MUST not invent authors,
affiliations, venues, dates, or persistent identifiers.

## Figures and Tables

Each figure MUST have:

- an editable source under `docs/paper/assets/figures/`;
- a checked-in SVG rendering with the same stem;
- a numbered caption stating its message, scope, and evidence state;
- readable labels without relying on color alone;
- explicit styling for gates, durable evidence, and optional paths.

Figures MUST distinguish current implementation from proposed or unevaluated
paths. Screenshots MUST include the route, viewport, collection date, and
environment in adjacent text. Decorative images MUST NOT be used as evidence.

Each table MUST state units and evidence status in its header or caption.
Empty result cells are prohibited; use `not_evaluated`, `not_applicable`, or a
bounded explanation. A result table MUST link or name the evidence record that
supports each non-empty result.

## Commands, Code, Links, and Paths

Commands MUST be copied from a verified repository state and MUST state their
working directory when it is not repository root. Destructive, mutating, or
live-hardware commands MUST display their approval and stop conditions before
the command.

Paper-facing content MUST use repository-relative paths. It MUST NOT contain
personal home paths, private endpoints, access tokens, credentials, private
keys, unpublished dataset locations, or identifiable participant data. Local
links MUST resolve in a clean checkout. External links SHOULD target stable,
primary sources.

Code excerpts SHOULD be minimal and MUST identify whether they are executable,
pseudocode, configuration, or illustrative schema. Ellipses MUST NOT hide a
safety gate, failure path, or value required to reproduce a result.

## English and Korean Synchronization

English is canonical for `README.md` and `docs/paper/`. `README.ko.md` is the
Korean landing-page companion. A change to thesis, contribution order,
research questions, evaluation status, safety boundary, reproduction entry
point, citation status, or license status MUST update both root READMEs in the
same change.

Korean prose MAY adapt sentence structure for clarity but MUST preserve claim
scope and evidence state. If synchronization cannot be completed, the Korean
section MUST identify the canonical English section and the date of divergence;
silent semantic drift is prohibited.

## Review Gates

A paper-facing change MUST pass these five gates:

1. **Narrative gate** — the system thesis remains primary and RQs are answered
   in a traceable order.
2. **Technical gate** — current-behavior statements match code, configuration,
   or declared evidence.
3. **Evidence gate** — claim statuses and evidence records are complete and
   environment-bounded.
4. **Safety and privacy gate** — public files disclose no secret, private path,
   unsafe operational shortcut, or unsupported safety claim.
5. **Release gate** — citation, license status, links, figures, and validation
   commands match the intended release state.

A reviewer SHOULD be able to reject one gate without implying acceptance or
rejection of the others.

## Prohibited Patterns

Paper-facing documents MUST NOT contain:

- unresolved authoring markers or empty result cells;
- invented benchmark, live-hardware, user-study, or scientific outcomes;
- claims that tests or documentation checks prove scientific validity;
- proposed behavior written in present tense as implemented behavior;
- a figure rendering without its editable source;
- a claim citation that points only to a marketing page when a primary source
  exists;
- personal absolute paths, credentials, secrets, or unpublished identifiers;
- license grants, authorship, affiliations, or DOI metadata not approved by the
  responsible people.

## Author Checklist

Before review, the author MUST confirm:

- the chapter declares its audience, scope, RQs, claims, and source basis;
- system contribution precedes platform contribution where both appear;
- every material claim has a status and every supported claim has evidence;
- quantitative statements include units, denominators, environment, and
  uncertainty where applicable;
- current, proposed, and unevaluated behavior are visually and verbally distinct;
- figures have matching `.dot` and `.svg` files and complete captions;
- tables contain no ambiguous blank cells;
- public paths and commands work from repository root without private context;
- README language companions remain semantically synchronized;
- the required validation commands pass.

## Required Checks

Every paper-facing documentation change MUST run:

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python scripts/validate_paper_publication.py
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_paper_publication_validation.py
git diff --check
```

Every figure change MUST additionally render all sources with Graphviz and
compare the checked-in SVGs against fresh output.

## Exceptions

- A paper chapter MAY remain `status: review` while scientific results are
  incomplete, but its unsupported claims MUST be `not_evaluated`.
- A release candidate MAY omit a DOI before archival; citation metadata MUST
  not imply that one exists.
- A repository without an approved open-source license MUST publish its actual
  no-license condition rather than selecting a license by assumption.
- Private security contact details MAY be omitted from public files when GitHub
  private vulnerability reporting is the documented channel.

No exception permits invented evidence, concealed hazards, silent translation
drift, or exposure of private information.

## Change Process

1. Propose changes to claim semantics, chapter order, or release policy in an
   approved Design or ADR.
2. Update this Standard, the paper templates, validators, tests, and affected
   documents together.
3. Run all required checks from a clean repository root.
4. Review the five gates independently.
5. Record release-state changes in `CHANGELOG.md` and the artifact manifest.

## Limitations and Known Gaps

This Standard structures evidence but does not create scientific evidence. It
does not choose authorship, affiliations, publication venue, an open-source
license, or a DOI. Those decisions require the responsible people and, where
applicable, institutional review.

The publication validator checks structural and machine-readable integrity. A
human review remains necessary for argument quality, citation accuracy,
scientific method, safety adequacy, and translation fidelity.

## Verification

Reviewed on 2026-08-09 against approved design commit `506ff44`, current
implementation baseline `0b7627b`, the general Documentation Standard, and the
paper publication validator contract.

## Related Documents

- `docs/standards/documentation_standard.md`
- `docs/templates/document_types.md`
- `docs/superpowers/specs/2026-08-09-github-paper-first-documentation-design.md`
