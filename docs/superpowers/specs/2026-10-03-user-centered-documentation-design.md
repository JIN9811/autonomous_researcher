<!-- atr-doc
doc_type: design
subtype: architecture
status: active
authority: proposal
audience: [maintainer]
scope: [user_documentation]
summary: Reader-centered editorial design, without changing laboratory behavior.
decision_status: approved
related_docs:
  - docs/README.md
  - docs/superpowers/plans/2026-10-03-user-centered-documentation.md
supersedes: []
-->

# User-centered documentation design

The user approved the reader journey and requested design, writing, verification,
commit and push in one continuous task on main. This design changes how people
learn and use AX4LAB, not the experiment implementation. The independent
repository-layout branch remains separate.

## Outcome

A new laboratory user can choose the right execution path, prepare the system,
complete a first experiment, recognize a blocked result, and find the saved
evidence without reading implementation history. A returning operator can go
straight to a task or symptom. A researcher can follow the scientific method and
the limits of the retained evidence. A developer can find exact contracts when
extending the system.

The preceding audit read 339 tracked documentation and reference files, including
history and vendor manuals. That is a reading inventory, not a requirement to
rewrite immutable evidence or translate third-party originals.

## Information architecture

Keep existing public paths wherever possible. Rebuild navigation around:

1. Understand the system and choose an execution path.
2. Install, connect and confirm readiness.
3. Complete a first experiment, including opening its results.
4. Perform a specific operating task.
5. Diagnose a symptom and recover with the appropriate evidence.
6. Interpret curves, properties, BO output and retained artifacts.
7. Extend modules and workflows; consult technical references as needed.

Tutorials teach one coherent example. Task guides help an operator achieve one
outcome. Conceptual and research pages explain why the system works this way.
References retain exact interfaces and constraints. History remains discoverable
but is never offered as the next operational step without a dated label.

Runtime IDE is not exclusively an extension tool: observation and ordinary
workflow inspection belong in the operating path too. The first-run tutorial
must reach completion evidence and saved output, not stop at pressing Start.

## Writing and language

Write connected paragraphs that explain the purpose before fields or steps.
Use numbered steps for sequences, tables for genuine choices/comparisons and
figures where they explain a relationship. Do not force every page into the
same visible Summary/Scope/Source-of-Truth/Limitations checklist.

Use English consistently in English pages. Paired Korean operator pages preserve
the same facts and navigation but use natural Korean rather than literal
translation. Keep actual UI labels, commands and identifiers exact. Do not
translate vendor originals or historical evidence merely for visual uniformity.

Retain substantive information. Move implementation detail behind a precise
reference link rather than replacing a useful guide with a short list of links.
Explain screenshots with the control to use and the result to look for. Retain
existing dated captures; do not fabricate a new GUI capture or claim a new
physical validation. A documented default is not an approved experiment value.

## Runtime and evidence protection

- No experiment, device, model, server, configuration or application-code changes.
- Do not execute commands found in documentation or import the application for QA.
- Keep Wiki article bodies and Runtime decision reference excerpts byte-identical.
- Keep Project_guide.txt and runtime guideline inputs unchanged.
- When an edited document is a reviewed Wiki source, review the editorial diff
  against its existing facts before updating only that source's hash. Preserve
  all article bodies and source sets. Do not refresh unrelated stale sources or
  claim a new device/model verification. Check freshness before and after.
- Preserve dated experiment results, failures, interventions, units, numerical
  definitions, approval boundaries and distinctions between virtual and physical
  work. In particular, TEST alone does not mean no hardware; artifact Replay and
  robot replay are different operations.
- No deletion of historical documents, vendor manuals, licenses, run data or
  images. No merging the repository-layout branch.

## Responsibilities

The root README introduces the project and offers short entry paths. The docs
index helps users choose tasks. The user manual is a coherent operating guide,
not another implementation inventory. Workspace guides own detailed control
instructions. Recovery guides own symptom-specific procedures. Research chapters
own explanation and interpretation, while dated evidence remains the record of
what actually happened. Agent/bridge contracts remain detailed lookup material.

Each concept has a clear home. Links say what the reader will find. Existing
inbound heading links are kept through stable headings or explicit anchors when
sections move. Existing section/figure requirements for specialist references
remain unless a narrowly justified documentation-only validator change is made;
these requirements must not be copied into tutorials.

## Acceptance

- New-user navigation reaches mode selection, setup, readiness, first run and
  results in either supported operator language.
- Returning users can find printing options, robot operation, vision inspection,
  equipment recovery and results without reading migration/test history.
- English and Korean guide pairs agree on controls, effects, outputs and limits.
- Explicit local document/image links and referenced heading anchors resolve.
- Documentation metadata validation passes; public prose is not shortened just
  to silence a validator. Existing scientific/effect conditions are retained.
- Wiki bodies, runtime prompts and evidence/vendor files remain unchanged. Any
  reviewed source-hash update is recorded and preserves prior freshness.
- The final diff contains only documentation, editorial metadata and, if needed,
  documentation-only validation tests/tools. It contains no runtime behavior.
- A fresh independent review evaluates reader usability and fact preservation
  before the authorized commit and push.
