---
doc_type: standard
subtype: contract
status: active
authority: normative
audience:
  - researcher
  - contributor
scope:
  - paper_tables
summary: Defines where canonical paper tables live and how their evidence state is maintained.
related_docs:
  - docs/standards/paper_documentation_standard.md
  - docs/paper/README.md
supersedes: []
---

# Paper Table Sources

## Summary

Paper tables are maintained next to the argument that interprets them. This
avoids a second, drifting copy of claim status or result values. This directory
records that source policy and is reserved for generated tabular exports when
a submission format requires them.

## Rules

- The contribution matrix is canonical in
  `docs/paper/01_problem_and_contributions.md`.
- Stage and architecture tables are canonical in
  `docs/paper/02_system_architecture.md`.
- Safety-gate and recovery tables are canonical in
  `docs/paper/03_closed_loop_method.md`.
- Extension tables are canonical in
  `docs/paper/04_platform_architecture.md`.
- Evaluation and result-status tables are canonical in
  `docs/paper/06_evaluation_and_results.md`.
- Reproduction tiers are canonical in `docs/paper/07_reproducibility.md`.
- Risk and limitation tables are canonical in
  `docs/paper/08_safety_ethics_and_limitations.md`.

Generated CSV, LaTeX, or image exports MUST identify their canonical Markdown
source, generator command, commit, and evidence-manifest version. They MUST NOT
be edited independently.

## Verification

The paper index links each table system to its canonical chapter. Local links
and governed metadata are checked by `scripts/validate_documentation.py`.
