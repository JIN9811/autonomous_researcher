---
doc_type: standard
subtype: safety
status: review
authority: normative
audience:
  - researcher
  - reviewer
  - operator
  - maintainer
scope:
  - paper
  - safety
  - ethics
  - limitations
summary: States ATR safety, human-oversight, data-governance, dual-use, and publication limitations without overstating implemented controls.
related_docs:
  - docs/paper/03_closed_loop_method.md
  - docs/paper/05_experimental_setup.md
  - docs/paper/06_evaluation_and_results.md
  - SECURITY.md
supersedes: []
paper_section: safety_ethics_and_limitations
research_questions:
  - RQ3
claim_ids:
  - C-SAFE-LIVE-01
  - C-LIMIT-EVAL-01
---

# Safety, Ethics, and Limitations

## Summary

ATR coordinates software, models, remote workers, and potentially hazardous
laboratory equipment. Its Guardian, approval, dry-run, capability, stop, and
evidence mechanisms are defense layers, not a universal safety guarantee.
Laboratory-specific authorization and physical controls remain required.

## Normative Scope

This chapter applies to paper claims, artifact evaluation, operator procedures,
and release of examples or evidence involving consequential actions. It does
not replace institutional safety, legal, ethics, cybersecurity, or equipment
requirements.

## Source of Truth

Safety behavior is defined by executable policies, runtime/controller state,
device bridge contracts, graph safety metadata, deployment configuration, and
the evidence recorded for a specific environment. Documentation is subordinate
to those controls.

## Implemented Control Categories

| Category | Current mechanism | What it does not establish | Evaluation state |
|---|---|---|---|
| Policy gate | Guardian decision routes and risk/context evaluation | Complete hazard coverage or correct decisions | Live effectiveness `not_evaluated` |
| Human oversight | Approval, review, stop, and operator workspaces | Constant attention, informed consent, or error-free judgment | Scenario behavior `not_evaluated` |
| Pre-execution control | Schema, capability, allowlist, and dry-run checks | Physical safety under valid but hazardous commands | Broad live behavior `not_evaluated` |
| Failure containment | Error/stop states, checkpointing, bounded retries | Safe recovery from every uncertain external effect | Failure matrix `not_evaluated` |
| Auditability | Events, artifacts, ledger/outbox, proof records | Scientific truth or completeness of all provenance | Partially supported structurally |
| Access boundary | Bridge configuration, authentication surfaces, secret separation | Secure deployment under arbitrary networks | Security assessment `not_evaluated` |

## Human Oversight

Consequential operations MUST have a named responsible operator and an
understandable action preview. Approval scope MUST bind to the current action,
parameters, device, run/cycle, and validity period. An approval MUST NOT be
reused after material context changes.

The operator MUST be able to stop the workflow through a path independent of
the model that proposed the action. A paper experiment MUST report operator
interventions and rejected actions rather than excluding them as noise.

## Physical Safety

Before live execution, the protocol MUST identify mechanical, electrical,
thermal, chemical, biological, radiation, pressure, motion, and material risks
applicable to the selected equipment. Required guards, interlocks, ventilation,
personal protective equipment, exclusion zones, and emergency stops belong to
the laboratory protocol.

Software approval and dry-run checks MUST NOT be represented as substitutes for
physical interlocks. If the external effect of a timed-out command is unknown,
the system MUST enter review; automatic repetition is prohibited until state is
re-established.

## Model Uncertainty

Model outputs are proposals or bounded transformations, not authority. The
system MUST validate schemas, capabilities, constraints, provenance, and policy
outside the model where feasible. Confidence scores MUST NOT be treated as
calibrated probabilities without an evaluation demonstrating calibration in
the target domain.

The paper MUST name the model configuration for model-dependent results and
must not generalize a result to all supported providers.

## Data Governance and Privacy

Public artifacts MUST exclude credentials, private endpoints, personal home
paths, confidential equipment identifiers, participant identifiers, and
unpublished datasets unless release is explicitly authorized. Redaction SHOULD
preserve field names, schema, and reason for restriction so the evidence gap is
visible.

Human-subject, clinical, biological, or controlled data requires the applicable
review and consent basis before use. The repository's ability to store data is
not authorization to collect or publish it.

## Cybersecurity

Remote workers and bridges can transform a web/API request into a physical or
desktop action. Deployments MUST use least privilege, allowlisted operations,
authentication, network segmentation appropriate to risk, bounded timeouts,
and auditable requests. Secrets MUST remain in approved runtime configuration.

Security vulnerabilities MUST follow `SECURITY.md`; exploit details and secrets
must not be posted in public issues.

## Dual Use and Misuse

The same orchestration, robotics, GUI automation, and optimization capabilities
can accelerate beneficial or harmful work. Users remain responsible for legal,
ethical, export-control, biosafety, chemical-safety, and institutional limits.
The project SHOULD refuse examples that operationalize clearly harmful or
unauthorized procedures and SHOULD publish bounded safety assumptions with each
live protocol.

## Scientific Integrity

The system MUST preserve failed, stopped, and contradictory outcomes when they
affect interpretation. Selective omission of interventions or failed runs is
not permitted. Model-generated explanations, inferred graph relations, and
optimization candidates MUST remain distinguishable from measured facts.

Documentation or test pass status MUST NOT be used as evidence of scientific
validity. Scientific claims require a domain protocol, data, analysis, and
uncertainty treatment.

## Limitation Register

| ID | Limitation | Consequence | Required next evidence |
|---|---|---|---|
| `C-LIMIT-EVAL-01` | No paper-scoped end-to-end physical campaign | System-level efficacy and reliability remain unknown | Supervised Tier 4 campaign with complete lineage |
| L-SAFE-01 | Guardian effectiveness not behaviorally scored here | RQ3 remains open beyond architecture | Test/simulation hazard scenario matrix, then bounded live cases |
| L-SCI-01 | No comparative scientific baseline | No improvement or superiority conclusion | Controlled study with denominator and uncertainty |
| L-EXT-01 | No representative cross-adapter matrix | General platform compatibility is unknown | Tiered extension evaluation |
| L-SEC-01 | No paper-scoped penetration or threat-model assessment | Deployment security is not established | Reviewed threat model and security test evidence |
| L-HUMAN-01 | Operator burden and usability not measured | Human oversight scalability is unknown | Approved usability/workload study |
| L-REPRO-01 | No archival dataset, container, or DOI | Long-term reproduction is limited | Release package and archival record |

## Required Publication Safety Check

Before a public release, maintainers MUST review changed paper files for
secrets, personal paths, private endpoints, unsafe live commands, unpublished
data, overstated controls, and unsupported result language. Automated scanning
supports but does not replace this review.

## Exceptions

No exception permits bypassing equipment interlocks, fabricating approval,
repeating an uncertain physical action automatically, disclosing secrets, or
reporting unevaluated safety performance as a result.

## Limitations and Known Gaps

Risk categories vary by laboratory and experiment. This chapter cannot enumerate
every domain hazard. It also does not establish compliance with a specific
regulatory or institutional framework.

## Verification

Reviewed on 2026-08-09 against the implemented control categories and current
paper evidence state. No `E-LIVE` safety-effectiveness record is present.

## Related Documents

- [Closed-loop method](03_closed_loop_method.md)
- [Experimental setup](05_experimental_setup.md)
- [Evaluation and results](06_evaluation_and_results.md)
