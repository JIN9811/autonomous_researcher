# Report Agent and Existing Module Extension Lifecycle

Status: design approved; implementation planning in progress.

## Intent and non-negotiable boundary

Add a report-writing specialist (RPT) through AX4LAB's existing modular system,
using it to improve the existing Module Designer/Management extension lifecycle.
Packages are connection and composition contracts between modules, not merely
distribution metadata. Reuse Runtime IDE, the module store, registration,
execution catalogs, Package Manager, and the existing frontend host.

The existing experimental loop must remain unaffected. No edits to the active
orchestration graph, current run configuration, existing agent decisions,
device commands, stage transitions, recovery policy, or completion criteria are
part of this work. Do not restart the production server, resume a run, or start
equipment as an implementation or verification step.

Whether RPT is attached after end/error, invoked manually, or used elsewhere is
deferred. Creating or registering RPT must not select any of these placements.

## Existing implementation to extend

- Module Management provides inactive draft templates, Python-to-adapter
  creation, explicit generated-adapter registration, validation, structural
  dry-run, configuration versioning, and an IDE attachment deep link.
- Code-owned specialists use `AgentModule`, automatic discovery, owner execution
  catalogs, frontend descriptors, and package connection contracts.
- Generated adapters currently use a different registration path from code-owned
  specialists. They must not be relabeled as fully packaged owners without the
  corresponding contracts and implementation.
- Installed Agent Package discovery currently enumerates seven specialist IDs.
- Experimental Packages carry graph composition, package references, module
  configurations, bridge dependencies, and symbolic local binding requirements.
  Import produces detached drafts and does not activate an experiment.
- Owner execution graphs validate registered operations, outcomes and available
  input/output evidence. Structural dry-run does not execute owner functions.
- The shared stage-output validator still has stage-specific rules; this change
  must not silently replace or tighten those rules for existing experiments.

## Proposed boundaries

### 1. RPT as a specialist owner

Create a code-owned report specialist with the same module, configuration,
execution catalog, presentation and archive conventions as existing specialists.
It has no device bridge dependency or actuation tools.

Inputs identify an existing source run and a bounded evidence snapshot. The
source run, cycle identities, attempts, authoritative results, graphs, images,
and recovery evidence remain read-only. Report output is written to a separate
report-job directory with its own identity and provenance manifest, never over
source measurements, results, manifests or historical reports.

First-version output is an English paper-style research-report draft: Abstract,
Introduction, Materials and Methods, Results, Discussion, Conclusion, References,
and Evidence Appendix. Include cycle results, optimization history when present,
interruptions/recovery, and limitations in the appropriate sections.
Use Markdown plus structured report/evidence metadata and existing figure
references; additional document export formats are outside this initial scope.
References must resolve to supplied sources; do not invent bibliography entries
or present run artifacts as peer-reviewed publications. Do not claim statistical
significance or causal performance improvements without appropriate evidence.

Metric values come from authoritative stored results. LLM prose cannot change
those values or invent missing experiments. Conflicting summaries, missing
evidence and synthetic inputs must be identified explicitly. Each numerical
claim and figure must retain resolvable source provenance.

Separate deterministic evidence collection/validation from model-assisted
composition and final report validation. Report failure is scoped to the report
job and cannot modify the source experiment's state or stop/resume it.
LLM-based data interpretation, discussion and conclusions are required, not just
formatting. Support both external API and local backends through the existing
AgentContext/ModuleRuntimeContext routing and editable module LLM settings; do
not hardcode a provider or model. Persist backend/model provenance. A model
failure must not silently downgrade to a supposedly interpreted final report.

### 2. Extend the existing Designer, not a parallel builder

Retain the existing UI, APIs and lifecycle concepts. Distinguish inactive
blueprint, implementation present, registered owner, valid connection contract,
structurally valid configuration, functionally tested module, and graph-attached
module. An installation/registration claim must not imply any later state.

Build RPT on the already defined module blueprint/template and existing
five-area execution/canvas conventions; do not introduce a parallel blueprint
system. Use RPT to establish the owner scaffold and required contract surfaces. Reuse
existing fields where possible rather than introducing a second authoritative
blueprint/configuration store. Generated code remains subject to explicit review
and registration; arbitrary imported source is not trusted or executed merely
because a package references it. Static checking is not a Python sandbox.

### 3. Package connection contracts

Generalize specialist package discovery to validated, explicitly installed owner
manifests without expanding editable package references into executable imports.
Preserve existing package IDs, versions, ownership, bridge requirements and core
owner behavior. No broad plugin installer or remote marketplace is included.

Add extension-scoped checks for RPT's declared evidence input and report output
contracts. Keep declared requirements, supported outputs and verification state
consistent across the Designer, package catalog and Runtime IDE. Existing
packages must retain current acceptance and execution behavior. Do not introduce
a new mandatory runtime gate for the existing experimental loop.

### 4. Explicit composition remains separate

Management load/unload remains management-only. Package import remains detached.
Module configuration save does not attach a graph node. Existing run-pinned
configuration semantics remain intact. RPT registration must not mutate the
active experiment or cause live frontend cards to appear as if RPT were active.

## Verification and integration conditions

All construction and execution tests use an isolated checkout/configuration/run
root, controlled model responses and denied physical-device transports. Existing
run artifacts may be read as fixtures, with all outputs redirected to test-owned
paths. No report generation is dispatched through the production run controller.

Required checks:

1. Existing package contracts, module lifecycle, execution-graph and frontend-host
   tests remain passing, with no compatibility assertions weakened.
2. Registering RPT leaves existing graph membership, routes, configuration and
   package contracts unchanged. No output, motion, printer or resume command is
   emitted by creation, inspection, import, validation or report execution.
3. Invalid/duplicate identities, unresolved owner/bridge dependencies and invalid
   report contracts fail without partial activation.
4. Structural validation and actual report execution have separate evidence.
5. Report tests cover complete runs, failed/incomplete runs, retries, missing
   artifacts, contradictory prose, synthetic data, cancellation and repeated
   generation. Missing data cannot be presented as successful measurements.
6. Source artifact hashes remain unchanged; report versions do not overwrite one
   another. Evidence paths and run/cycle/attempt identities are validated.
7. A read-only fixture from the completed experiment demonstrates real report
   generation and traceable claims, independently of the experiment loop.
8. Browser verification covers the existing Designer-to-contract lifecycle,
   refresh/draft retention and truthful readiness labels in an isolated server.

Before production integration, review the diff specifically for active graph,
existing agent, device bridge, recovery and runtime admission changes. Such
changes are outside scope and require a separate decision, not implicit approval
through the RPT feature.

## Deferred decisions

RPT invocation placement and production activation are intentionally excluded.
The written design has been approved, including paper-style output and reuse of
the existing blueprint. Review the implementation plan before implementation.
