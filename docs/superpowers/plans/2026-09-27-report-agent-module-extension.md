# Report Agent and Existing Module Lifecycle Implementation Plan

Status (source audit 2026-09-29): separate `feature/report-agent` worktree work,
not merged into the reviewed main baseline `dd0d772`. RPT is not an installed
main agent or an active production graph stage. The plan below remains the
branch's implementation specification, not current operating documentation or
authorization to attach the module, restart production, or operate equipment.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a paper-style RPT specialist on the existing module blueprint and complete the extension-to-package contract path without modifying the experimental loop.

**Architecture:** Reuse Module Management, AgentModule, execution catalogs, the shared frontend host and Experimental Package contracts. Keep report evidence collection and output validation deterministic; restrict LLM use to source-grounded narrative composition. RPT remains unattached to production graphs.

**Tech Stack:** Existing Python/Pydantic/FastAPI, YAML module definitions, vanilla JavaScript module UI, pytest and Node tests; no new runtime dependency initially.

**Spec:** `docs/superpowers/specs/2026-09-27-report-agent-module-extension-design.md`.

## Global Constraints

- No changes to active orchestration graphs, existing decisions, device commands, transitions, recovery policy or completion criteria.
- No production restart, equipment action, run resume or automatic RPT attachment.
- Use the existing blueprint/template, not a second source of configuration truth.
- Packages remain module connection/composition contracts.
- Source experiment data is read-only. Report-job artifacts have separate identities and paths.
- Existing package schemas and runtime acceptance remain backward compatible.
- English, paper-style output; no fabricated metrics, bibliography or significance claims.
- LLM interpretation and conclusions are required through existing external API/local routing; record model/backend provenance and never silently substitute a completed template-only report.
- All execution verification uses isolated paths, controlled models and denied device transports.
- Structural dry-run and functional execution evidence remain visibly distinct.

## Review Focus

1. Retried cycles must not be counted as independent experiments; preserve run/cycle/attempt identity (Task 1).
2. Evidence links escaping the source root, malformed files and prompt-like artifact text must not gain execution authority (Tasks 1–2).
3. LLM interruption or cancellation must not publish a complete report or alter source-run state (Task 2).
4. A fresh specialist must reach the package catalog without silently changing existing owners or activating a graph (Tasks 3–4).
5. Repeated generation, stale UI responses and server refresh must not overwrite reports or newer drafts (Tasks 2, 4–5).

## File and interface map

- `agents/report/contracts.py`: typed report request, evidence bundle and result schemas.
- `agents/report/evidence.py`: bounded, read-only archived-run evidence collection.
- `agents/report/composition.py`: bounded model request and validated narrative response.
- `agents/report/artifacts.py`: deterministic paper rendering and versioned publication.
- `agents/report/{agent,module,execution,structure,presentation}.py`: existing owner conventions and execution/catalog/frontend contracts.
- `agents/report/frontend/live_report.js`: common-host report presentation; no custom live-loop control.
- `graphs/modules/report/{module,ui}.yaml`: existing blueprint-derived configuration, unattached to production.
- `packages/agents/report/{package.yaml,README.md}`: RPT connection contract and usage documentation.
- `packages/service.py`: validated package discovery without fixed specialist names.
- `graphs/module_blueprints.py`: extract/reuse current template builder plus explicit scaffold manifest; no independent blueprint persistence.
- `app/main.py`, `web/static/module_management.js`, `web/templates/module_management.html`: thin existing creation/inspection integration, not a new builder application.
- `tests/unit/test_report_*.py`, `tests/unit/test_module_blueprints.py`, `tests/js/report_frontend.test.cjs`: isolated verification.

## Task 1: Read-only report evidence contract

**Interfaces:**
- `ReportRequest(source_run_id: str, source_run_root: Path, output_root: Path)` identifies a source run and separate report workspace.
- `collect_report_evidence(request: ReportRequest) -> ReportEvidenceBundle` returns source identities, claims with units/provenance, figure references, missing/conflicting evidence and a content digest.
- Each claim has `id`, `value`, `unit`, `source_path`, `source_sha256`, `run_id`, `cycle_id`, `attempt_id`.

- [ ] Add failing tests in `tests/unit/test_report_evidence.py` for two cycles where one has a failed attempt followed by a successful attempt: assert two cycles, all attempts retained and no averaging/recounting of retries.
- [ ] Add tests for authoritative numeric results conflicting with prose, missing artifacts, malformed JSON, synthetic evidence and symlink/path traversal: assert explicit warnings or bounded rejection, never inferred success.
- [ ] Run `.venv/bin/python -m pytest -q tests/unit/test_report_evidence.py`; confirm failures are missing functionality.
- [ ] Implement the typed contracts and collector using existing runtime attempt manifests, stored results and preservation indexes. Treat indexes as aids, not proof of completeness. Do not run backfill or recompute experimental metrics.
- [ ] Re-run the tests; assert source tree hashes and file inventory are unchanged. Record a checkpoint diff after passing.

## Task 2: Paper composition and independent publication

**Interfaces:**
- `async compose_report(bundle: ReportEvidenceBundle, ctx: AgentContext) -> ReportNarrative` uses the existing model routing API.
- `validate_report(narrative: ReportNarrative, bundle: ReportEvidenceBundle) -> list[str]` rejects unknown claim/source references.
- `publish_report(request: ReportRequest, bundle: ReportEvidenceBundle, narrative: ReportNarrative) -> ReportResult` writes `report.md`, `report.json`, `evidence_manifest.json` and referenced figure copies beneath one new report-job directory.
- Result schema `ax4lab.report_result.v1`: job/source identities, status, evidence digest, artifacts and warnings.

- [ ] Add failing tests in `tests/unit/test_report_composition.py` and `test_report_artifacts.py`; assert the eight specified paper sections, exact original metric values/units and resolvable figure/claim references.
- [ ] Add tests for invented citations, changed numeric values, artifact-embedded instructions, model failure/cancellation and a second generation: reject unsupported claims, mark incomplete jobs accurately, preserve prior reports and source state.
- [ ] Test the same report request through controlled external API and local backend configurations, asserting selected routing and provenance with identical evidence/validation semantics.
- [ ] Run those tests and confirm expected failures.
- [ ] Implement structured narrative generation with claim IDs, not unconstrained rewriting of measured tables. Deterministically render numerical results and source references. Bound model context by evidence summaries; do not load camera frame sequences into prompts.
- [ ] Implement unique report-job publication with a final manifest written only after validation. Reject output roots inside the source run; copy only declared bounded report figures, not full datasets.
- [ ] Re-run both suites; checkpoint the passing changes.

## Task 3: RPT owner on the existing blueprint

**Interfaces:**
- `ReportAgent.name = "report_agent"`, module ID `report`, version `1.0.0`; `run(state, ctx) -> AgentResult` consumes an explicit report request and returns `data["report"]`.
- `report_execution_catalog(agent) -> ExecutionCatalog`: registered collect, compose, validate/publish and deliver operations with explicit dependencies and failure outcomes.
- `MODULE` follows `AgentModule`; frontend/presentation/storage references use the common host. No bridge dependency.

- [ ] Add failing `tests/unit/test_report_module.py` checks for module discovery, factory identity, execution graph dependencies, required report output, no device tools and rejection of absent request.
- [ ] Add a test invoking RPT in an isolated harness with archived fixtures; compare source OrchestratorState before/after and assert no transition, stop, resume or device call.
- [ ] Run the module test and confirm expected failure.
- [ ] Implement the owner files using current `AgentModule`, `ExecutionCatalog`, invocation trace and archive conventions. Reporting job archive context must point at the separate job output, never the source run.
- [ ] Derive configuration and five-area representation from existing template/conventions. Keep production graphs untouched; retain explicit approval/admission semantics for any future graph integration.
- [ ] Re-run RPT and execution-graph tests; checkpoint changes. Do not add RPT-specific branches to legacy stage-output validation.

## Task 4: Existing Designer-to-package connection lifecycle

**Interfaces:**
- Keep `installed_agent_packages(descriptions)` public signature; discover shipped manifests only for installed code-owned modules, validate ID/version/handler identity and dependency references.
- `build_module_template(template_kind, *, module_id, label, category, notes, author, created_at) -> tuple[dict, dict]` extracts current template behavior without changing existing defaults.
- `describe_module_extension(module_id, *, module, installed_owner, package_contract, execution_catalog) -> dict` reports separate blueprint, implementation, owner-registration, connection-contract and structural readiness states. It must not claim functional verification from dry-run.

- [ ] Add failing tests in `tests/unit/test_module_blueprints.py` and extend `test_package_contracts.py`: existing template parity, RPT package discovery, duplicate/mismatched manifests, missing dependencies and unchanged legacy seven-package contract values.
- [ ] Add tests proving draft creation/import/inspection cannot attach a graph, execute generated code or create a successful functional-test claim.
- [ ] Run those suites to establish failures.
- [ ] Extract/reuse the template builder, preserving current endpoint payloads. Generalize installed contract discovery; editable input must never choose an arbitrary Python import or manifest filesystem root.
- [ ] Integrate extension readiness into existing Module Management inspection. Reuse draft/source creation and explicit registration; do not silently promote generated adapters to code-owned packages. Make missing owner/catalog/package surfaces visible as actionable requirements.
- [ ] Provide a development scaffold path derived from the existing template, with a file manifest and explicit review boundary for owner/config/UI/package/test files. Reject existing-file collisions; generated skeletons remain nonfunctional until implemented and verified. Test RPT against this same scaffold contract.
- [ ] Run existing Designer, package, lifecycle and execution editor regressions; checkpoint changes.

## Task 5: Common UI, real-evidence verification and documentation

**Interfaces:**
- `project_report_report(state: dict, snapshot: dict) -> dict` exposes report status, source identity, evidence coverage and artifacts without fabricating completion.
- Frontend `AX4LABReportUI.createFrontend` conforms to the existing module host lifecycle.
- Existing Module Management exposes extension readiness through current inspection APIs; production graph membership remains the source of active Live cards.

- [ ] Add failing `tests/js/report_frontend.test.cjs` and lifecycle checks: unattached RPT is not an active Live agent; pending/failed output is distinct; stale response cannot replace newer report/job selection.
- [ ] Implement the RPT presentation and minimally extend existing Designer labels/readiness display. Preserve dirty drafts, import/export behavior and five-area canvas. Do not introduce a parallel dashboard.
- [ ] Run Node tests and Python report suites to green.
- [ ] Start an isolated server with temporary graph/config/storage and denied transports; exercise existing draft creation, validation, registration readiness, package inspection and refresh behavior. Do not use production writes or save/activate the production graph.
- [ ] Run RPT against the completed archived run with source hashes captured before/after, controlled narrative responses and outputs outside its run directory. Verify cycle identity, recovery reporting, authoritative metrics, figure references and gaps; explicitly label model-substitute verification.
- [ ] Add `docs/agents/report_agent.md` and update modularity/Runtime IDE/package docs with the actual lifecycle, limitations and verification commands. Include a sample paper-style report from isolated fixtures, clearly labeled as fixture evidence.
- [ ] Run combined regression commands below, inspect diff for forbidden loop/device changes and confirm active graph files unchanged. Present result and separately request any production activation or loop placement.

## Final regression commands

```bash
.venv/bin/python -m pytest -q tests/unit/test_report_evidence.py tests/unit/test_report_composition.py tests/unit/test_report_artifacts.py tests/unit/test_report_module.py tests/unit/test_module_blueprints.py tests/unit/test_package_contracts.py tests/unit/test_module_designer_cli_contract.py tests/unit/test_ide_module_lifecycle_js.py tests/unit/test_agent_execution_graph.py tests/unit/test_module_control_views.py tests/unit/test_core_owner_plans.py
node --test tests/js/report_frontend.test.cjs tests/js/experimental_packages.test.cjs tests/js/module_execution_editor.test.cjs tests/js/module_control_structure.test.cjs tests/js/module_control_view.test.cjs tests/js/agent_module_host.test.cjs
git diff --check
git diff -- graphs/configs orchestrator/langgraph_runtime.py policies/validation_policy.py device_bridges
```

Expected: all selected tests pass; no forbidden production-path changes. Existing
audit baseline was 113 Python tests and 53 Node tests passing; this is not a
claim about a full repository or physical experiment test.

## Execution handoff

The user requested plan finalization, commit/push of the current state, and
immediate implementation. Execute natively in an isolated worktree, then perform
an independent final review. Production activation and invocation placement
remain excluded; do not restart or modify the running experiment.
