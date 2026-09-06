---
doc_type: evidence
subtype: audit
status: review
authority: evidentiary
audience:
  - researcher
  - reviewer
  - artifact_evaluator
scope:
  - paper
  - claim_evidence_traceability
summary: Maps ATR paper claims to research questions, evidence environments, records, and explicit gaps.
evidence_date: 2026-09-07
method: Cross-check of paper claim identifiers against docs/paper/artifact_manifest.yaml.
paper_section: claim_evidence_traceability
research_questions:
  - RQ1
  - RQ2
  - RQ3
  - RQ4
claim_ids:
  - C-SYS-LOOP-01
  - C-SYS-ARCH-01
  - C-TRACE-DOC-01
  - C-SAFE-LIVE-01
  - C-PLAT-EXT-01
  - C-LIMIT-EVAL-01
related_docs:
  - docs/paper/artifact_manifest.yaml
  - docs/paper/06_evaluation_and_results.md
  - docs/standards/paper_documentation_standard.md
supersedes: []
---

# Claim-Evidence Traceability

## Summary

This chapter is the human-readable view of
`docs/paper/artifact_manifest.yaml`. It prevents a reader from having to infer
which command, environment, or artifact supports a material claim.

## Scope

The initial map covers the top-level system, traceability, safety, platform,
and evaluation-limit claims. Chapter-level explanatory sentences inherit these
boundaries but do not create new evidence classes.

## Evidence Basis

The mapping was checked against artifact-manifest schema version 1. The
publication validator rejects duplicate IDs, invalid statuses, missing
evidence references, unsafe paths, missing outputs, and mismatched SHA-256
digests.

## Claim Map

| Claim ID | Proposition | RQ | Status | Evidence | Boundary / next evidence |
|---|---|---|---|---|---|
| `C-SYS-LOOP-01` | One supervised mixed-mode iteration reached live UTM clearance, Analysis, BO-managed LHS feedback, and the next Design/Specimen entry. | RQ1, RQ2 | `supported` within integration scope | `E-LIVE-LOOP-001` | Deposition skipped, specimen substituted; no material-validity, acquisition-optimization, or campaign-completion claim. |
| `C-SYS-ARCH-01` | ATR declares a closed-loop graph spanning research stages with explicit dispatch, feedback, and terminal structure. | RQ1 | `supported` | `E-INSPECT-ARCH-001` | Execution and recovery across a complete run require Tier 1–4 evidence. |
| `C-TRACE-DOC-01` | The paper package enforces machine-readable links from supported claims to bounded evidence outputs. | RQ2 | `partially_supported` | `E-TEST-DOC-001` | Runtime scientific lineage is not established by document tests. |
| `C-SAFE-LIVE-01` | Guardian and operator gates prevent or safely contain consequential live actions. | RQ3 | `not_evaluated` | No qualifying record | Requires scenario matrix and supervised live evidence. |
| `C-PLAT-EXT-01` | ATR exposes contract-oriented module, graph, backend, bridge, and workspace extension surfaces. | RQ4 | `supported` | `E-INSPECT-ARCH-001` | General compatibility and containment require representative extension tests. |
| `C-LIMIT-EVAL-01` | The current paper package does not establish end-to-end physical or scientific efficacy. | RQ1–RQ3 | `partially_supported` | `E-TEST-DOC-001`; bounded integration evidence does not validate efficacy | One mixed-mode iteration is not a full physical/scientific campaign. |

`C-LIMIT-EVAL-01` remains a release limitation. The added supervised live record
changes integration evidence, not the absence of a full physical/scientific
campaign or statistical evaluation.

## Evidence Map

| Evidence ID | Environment | Verified scope | Does not establish |
|---|---|---|---|
| `E-LIVE-LOOP-001` | Supervised mixed-mode / live equipment | One feedback iteration, eight Equipment blocks, fresh UTM clearance, Analysis, BO-managed LHS, and next Design parameters | Full manufacturing, specimen scientific identity, acquisition improvement, safety effectiveness, independent replay from the public summary |
| `E-INSPECT-ARCH-001` | Inspection | Route counts, graph node/edge/dispatch counts, inspected extension categories | Runtime correctness, safety effectiveness, scientific outcome |
| `E-TEST-DOC-001` | Test | Front-matter, manifest, paper structure, claim-reference, path, hash, and privacy contracts selected by the focused test command | System tests, browser workflows, physical execution, scientific validity |

## Claim Lifecycle

1. Create a stable claim ID and bounded proposition.
2. Assign `not_evaluated` before qualifying evidence exists.
3. Record evidence with environment, commit, command/protocol, inputs, outputs,
   hashes, and result.
4. Review whether the evidence supports the entire proposition or only part.
5. Set `supported`, `partially_supported`, or `contradicted` without deleting
   conflicting evidence.
6. Update affected chapters, the evaluation table, manifest, and changelog in
   the same reviewed change.

An evidence record is immutable in interpretation scope. A rerun at a new
commit or environment receives a new record instead of rewriting the old
context.

## Contradictions and Negative Results

If evidence conflicts with a claim, set `contradicted`, retain the evidence,
and explain the affected scope. A negative or stopped result may be the most
important safety or recovery evidence and MUST NOT be removed merely because
it weakens the paper narrative.

## Limitations and Known Gaps

The initial map is deliberately sparse. It has no replay, simulation, browser,
or live evidence records. It does not replace a manuscript bibliography,
statistical analysis, or domain data repository.

## Verification

Run from repository root:

```bash
.venv/bin/python scripts/validate_paper_publication.py
```

The validator reads the machine manifest; reviewers must still assess whether
each proposition is appropriately bounded by its referenced evidence.

## Related Documents

- [Artifact manifest](artifact_manifest.yaml)
- [Evaluation and results](06_evaluation_and_results.md)
- [Paper Documentation Standard](../standards/paper_documentation_standard.md)
