---
doc_type: standard
subtype: repository
status: active
authority: normative
audience:
  - contributor
  - maintainer
  - researcher
scope:
  - repository_contributions
  - repository_documentation
summary: Defines how to propose, verify, and review code and documentation contributions to ATR.
related_docs:
  - docs/standards/documentation_standard.md
  - docs/README.md
  - SECURITY.md
supersedes: []
---

# Contributing

## Summary

Contributions should preserve ATR's runtime, safety, evidence, and document
authority boundaries. Discuss large architecture changes before implementation
and keep each change reviewable.

No open-source license is currently granted. Opening an issue or pull request
does not by itself grant a license to the repository or clarify the license of
a contribution. Resolve contribution and licensing terms with the maintainers
before submitting material intended for reuse.

## Before You Start

1. Read [REQUIREMENTS.md](REQUIREMENTS.md) and the relevant active Reference.
2. Check [docs/README.md](docs/README.md) for current, proposed, and legacy
   document authority.
3. Use an issue or design document for changes that alter architecture,
   safety, public contracts, claim semantics, or migration behavior.
4. Do not include credentials, private endpoints, personal paths,
   identifiable data, unpublished datasets, or third-party material without
   release permission.

Security vulnerabilities follow [SECURITY.md](SECURITY.md), not the normal
public issue workflow.

## Change Scope

- Preserve unrelated worktree changes.
- Keep implementation, tests, and directly affected documentation together.
- Do not describe proposed behavior as current behavior.
- Do not bypass Guardian, approval, device, ontology, ledger, or evidence
  contracts to simplify an integration.
- Add dependencies only when their purpose, version boundary, and deployment
  effect are clear.

## Tests and Verification

Run focused tests for the changed subsystem and the smallest relevant
integration surface. Before requesting review, run:

```bash
git diff --check
.venv/bin/python scripts/validate_documentation.py
```

Documentation changes also run:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_knowledge_publication.py
```

Figure changes must retain editable `.dot` sources and deterministic `.svg`
renderings. Runtime changes require subsystem-specific tests; documentation
checks do not substitute for runtime behavior tests.

<a id="paper-documentation-contributions"></a>

## Research Documentation Contributions

Follow the [Documentation Standard](docs/standards/documentation_standard.md).
The research manuscript is maintained separately; repository documents explain
the implementation and preserve the scope of recorded evidence. In particular:

- separate current implementation, proposed changes, and historical results;
- support factual claims with source code or identifiable evidence;
- quantitative results state environment, unit, denominator, uncertainty where
  applicable, and evidence ID;
- state when results are unavailable rather than inventing values or conclusions;
- English canonical changes synchronize the Korean root README when thesis,
  RQs, evaluation, safety, reproduction, citation, or license status changes.

Do not invent authors, affiliations, venue, DOI, benchmark values, live-device
results, or scientific conclusions.

## Commit and Review

Use focused commit messages that explain the outcome, for example:

```text
docs: clarify operator setup and evidence references
test: enforce documentation and evidence integrity
fix: preserve approval scope during resume
```

A review should independently consider implementation correctness, safety,
evidence integrity, public-data exposure, and document clarity. Passing tests
do not force acceptance of unsupported claims or unsafe design choices.

## Release-Related Changes

Changes to authorship, affiliation, citation type, license grant, release tag,
archival DOI, or public dataset require explicit approval from the responsible
people. Update `CITATION.cff`, `LICENSE`, `CHANGELOG.md`, the artifact manifest,
and affected READMEs together when such a decision is made.
