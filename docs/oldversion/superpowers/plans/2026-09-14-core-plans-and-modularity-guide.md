<!-- atr-doc
doc_type: plan
subtype: implementation
status: archived
authority: execution
execution_status: completed
audience: [developer, maintainer, reviewer]
scope: [core_plans, modularity, runtime_ide, packages, documentation]
summary: Connect core-owner plans through existing module configuration and package paths, explain modularity, and retire only verified superseded code.
governing_design: docs/oldversion/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs: [packages/README.md, docs/runtime/runtime_ide.md, docs/agents/knowledge_agent.md, docs/agents/guardian_agent.md]
supersedes: []
-->

> Archived development history (2026-09-14). Not the current implementation or acceptance contract. See the [archive index](../../README.md) for current references.


# Core Plans and Modularity Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Continue in the current checkout; no commit, tag, push, operating-server restart or hardware actuation.

**Goal:** Make declared Knowledge/Guardian plans usable through existing contracts and Package Manager, document the implemented modular architecture, and remove only proven obsolete code after validation.

**Architecture:** Store optional owner plans within existing module configurations, carry them through existing Experimental Package exchange, and consume them from invocation-scoped pinned module snapshots. Each core owner validates and interprets its own supported settings. Orchestration remains the existing graph and LangGraph runtime.

**Tech Stack:** Existing Python/Pydantic/FastAPI, module YAML store, JavaScript IDE, Graphviz DOT/SVG; no new dependencies.

**Spec:** `docs/oldversion/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md`, Core Plan extension approved 2026-09-14.

## Global Constraints

- Baseline tree `3cc9b724620423965ed658a08c398667afe11e89` includes prior uncommitted cleanup and core structure. Preserve it. HEAD is `05d5e55687aacf7647413bb266aef8d836eb1346`. Review this task from that tree, not HEAD.
- Keep current checkout and existing private data, artifact roots, handler/tool/API IDs and equipment behavior. Do not restart or connect to the operating server, hardware, native FEM, providers or model lifecycle. Tests use guarded controlled dependencies, not physical proof.
- No new Plan store, registry, executor, scheduler, transport, device authority or duplicated Orchestration Plan. KNW/GRD/ORC remain core agents; specialist packages remain unchanged.
- No-plan invocation preserves existing outputs, call order/count/arguments, error/cancel behavior and single archive. Configured plans affect supported owner inputs only. Unsupported policy changes fail; Guardian operator stop/deterministic gates cannot be disabled.
- Use existing module version/save/apply APIs and pinned per-run module configuration. Editing/importing/validating is not applying; applying does not start a run and active-run mutation remains rejected. A running/pinned run never rereads changed files.
- Portable plan declarations must not contain live snapshots, personal/session identifiers, credentials, machine paths or connection values. Do not strip invalid scope selectors into a broader scope during export; reject them. Existing authorization services remain authoritative.
- Keep existing IDE style, controls and Package Manager. English UI/current reader docs; Korean implementation design. No standalone management page or redesigned graph nodes.
- Keep ignored verification artifacts. No staging/commit/tag/push. Remove only explicitly inventoried superseded code after covering tests and review; retain consumed adapters/history/evidence.

## Task 1: Owner plans, package transport, IDE and execution binding

**Files:**
- Extend `agents/core/knowledge/plan.py`, `agents/core/guardian/plan.py`, bounded owner consumption in `agent.py`/Guardian `decision.py`.
- Add a small declarative transport type/helper in `agents/core/plans.py` if needed; it owns shape only, never owner policy.
- Extend `graphs/schema.py` with optional `owner_plan`, existing `app/main.py` module validation/catalog response, `packages/service.py` portable checks and existing package/module transport tests.
- Extend `web/static/runtime_ide.js` and existing package UI helper under `web/static/`; preserve style and current editor caches/save paths. Add a narrowly owned helper file only if required to avoid bloating host composition.
- Add `tests/unit/test_core_plan_binding.py`, extend `tests/unit/test_package_contracts.py`, `tests/integration/test_packages_api.py`, `tests/integration/test_agent_execution_graph_api.py`, `tests/js/experimental_packages.test.cjs` or one dedicated core-plan JS test.

**Interfaces:**

```json
{"owner_plan":{"schema":"ax4lab.owner_plan.v1","id":"knowledge_reference","owner":"knowledge","version":"1.0.0","contract_version":"1.0.0","settings":{"corpora":["markdown"],"decision_max_steps":6}}}
```

- `owner_plan` is optional within `module`; absence means existing inputs. A declaration has exact keys above, valid existing-style IDs/exact numeric version, matching module/owner, supported contract version. Unknown/duplicate fields fail existing bounded JSON parsing. No runtime `inputs` field is portable.
- Reuse owner `plan_contract()`/`validate_plan` rules with a distinct declaration-validation entry point if needed. Validation cannot initialize stores or write state. Definition version is separate from owner contract version.
- Knowledge reads declared overrides via `ctx.runtime_module_config()` only for the matching owner. Derive effective settings/applicability as local detached values rather than permanently overwriting run metadata; unprovided settings retain current defaults. Guardian includes configured context as explicitly reference-only evidence in the existing single advisory call. No new model calls or gate authority.
- Record configured plan identity/version and effective supported settings in existing owner result/archive evidence, without adding speculative default records to no-plan runs. Existing archives remain readable.
- Module host asks the registered owner to validate; package exchange relies on the same module validator and existing `module_configurations`. Old packages lacking owner plans still round-trip. No second plan copy in top-level package fields.
- Package Manager shows current Orchestration graph reference and Knowledge/Guardian Default/Configured controls with ID/version/settings, Validate and explicit Apply using the existing owner module save API. Validation/save results identify draft versus applied state; errors never show success. Clearing a declaration restores future-run legacy settings, not disabling a core agent. Import updates detached module drafts/caches and controls without writing active configuration.

- [x] Add failing contract tests for unknown owner/schema/version/settings, private snapshot fields, invalid scope values, detached defaults and declared settings reaching the real owner decision input.

```python
definition = {"schema": "ax4lab.owner_plan.v1", "id": "knowledge_reference",
              "owner": "knowledge", "version": "1.0.0", "contract_version": "1.0.0",
              "settings": {"corpora": ["markdown"], "decision_max_steps": 6}}
# Use the real owner with controlled external calls; assert its decision receives
# corpora=["markdown"] and decision_max_steps=6, while original metadata stays equal.
# Mutating module.yaml after RunLoop construction cannot change those inputs.
```

- [x] Implement minimal declaration validation and owner consumption through existing pinned context. Keep all normal no-plan branches unchanged; do not apply through a bridge or new controller run endpoint.
- [x] Test and wire existing module validation/save and package export/import with owner plans. Assert import/validation writes nothing, explicit apply saves only selected module, active-run apply rejected, mismatched owner/unknown setting rejected before persistence, and exported scopes never widen through private-field stripping.
- [x] Implement Package Manager controls with original module draft/cache and existing request helpers. Behavioral tests exercise Default/Configured, invalid JSON/settings, Validate, Apply, imported draft and clear/reset; no source-string assertions as UI proof.
- [x] Run `.venv/bin/python -m pytest -q tests/unit/test_core_owner_plans.py tests/unit/test_core_plan_binding.py tests/unit/test_package_contracts.py tests/integration/test_packages_api.py tests/integration/test_agent_execution_graph_api.py`, plus relevant owner tests and `node --test tests/js/experimental_packages.test.cjs tests/js/module_execution_editor.test.cjs` and any new core-plan JS file.
- [x] Report changed interfaces, exact RED/GREEN commands/results and residual risk; freeze for review. Do not remove legacy code yet.

## Task 2: Reader explanation, final verification and obsolete-code retirement

**Files:**
- Create `docs/modularity.md` and `docs/assets/modularity/{contracts,lifecycle}.dot` with same-stem SVG output.
- Update root `README.md`, language README navigation, `docs/README.md`, `docs/document_manifest.yaml`, `packages/README.md`, owner Knowledge/Guardian refs, agent index/matrix, Runtime IDE and authoritative modularization spec to describe verified implementation.
- Refresh only reviewed affected Wiki source hashes. Do not alter unrelated stale pages.
- Code retirement targets are discovered from Task 1 diff and previous flat-agent cleanup, not guessed in advance. Preserve active canonical code, public APIs, bridge providers, archived evidence and required aliases.

**Interfaces:** Task 1 report and verified source define current capabilities; no aspirational content labelled implemented. User-facing document is an explanatory Reference, not an implementation checklist.

- [x] Write reader-first English explanation: 5–7-row Status at a Glance, why modularity, definitions/relationship table, core versus specialist owners, frontend/backend/storage folder tree, IDE/package/plan lifecycle, one generic extension example, current limits and evidence links. Keep normal page headings and concise prose; no repeated defensive text.
- [x] Create two small document-theme DOT/SVG diagrams: contract ownership/composition and draft→validate→explicit apply→pinned run. Label Package references versus runtime execution differently; no bridge direct-control shortcut, no mandatory sequential five-layer pipeline. Render using existing Graphviz; inspect at document width, provide alt/caption and source links.
- [x] Add direct navigation from main README table and docs index; link packages, agent index and bridges to the new explanation rather than duplicate it. Update current docs/spec after inspection and refresh corresponding Wiki hashes only.
- [x] Controller independently runs existing guarded five-route suite `tests/integration/test_orchestrator_setup_loop.py::test_confirmed_setup_enters_original_initial_lhs_and_real_design`, plus configured-plan invocation/pinning and transport/apply tests. Preserve test-mode provider choice; no actual hardware. Record controlled LLM scope explicitly.
- [x] Browser QA at 1920×1080 and narrow width: actual IDE HTML/static + isolated guarded API, Package Manager controls, invalid input, import, validation and explicit apply, module→outer navigation. No operating-server connection; Browser plugin absent so existing Playwright permitted. Retain screenshots in this task's ignored validation workspace.
- [x] After tests and review pass, inventory superseded candidates: old target, replacement, static/dynamic/config/test/package consumers, historical/reproduction need. If no safe candidate exists say so. Delete redundant consumed-by-nobody implementations already recoverable in Git; archive only useful history with mapping. No blanket moves by age/name. Rerun affected import/route/transport tests after any deletion.
- [x] Validate changed governed docs/local links/DOT-SVG reproducibility/private publication; distinguish known baseline ORC fixture and global Windows/PLC document debt. Record cleanup result and update spec/plan verification; no commit.

### Task 2 Documentation Record — 2026-09-14

`docs/modularity.md` is a 195-line active Reference with two editable/rendered
document-theme diagrams. Both figures were inspected at document width; labels,
line semantics and bounds were readable with no overlap. Focused validation of
19 changed reader documents reported 0 governance/local-link errors, both DOT
renders matched their SVG byte-for-byte, the manifest contains one Reference
entry, four reviewed Wiki source hashes match, and the scoped diff check passed.

Final independent verification recorded 158 focused Python passes in 23.91 s
with 10 existing warnings, 48 Node passes, and 5 guarded route passes in
131.23 s with 76 existing warnings. The final isolated browser/API test passed
in 25.49 s with 10 existing warnings at 1920/900 px; console errors, external
requests and physical calls were absent. These checks used controlled model
and equipment I/O and do not establish live provider or hardware behavior.
All final review findings were resolved, including private owner-plan selectors
and stale Validate/Apply responses after newer or invalid draft edits. The
publication boundary check passed for 221 files without policy exceptions.
Known unrelated baseline debt remains the recorded ORC fixture, nine broader
Live GUI layout assertions, and global Windows/PyAutoGUI and PLC documentation
findings; these are not claimed as passing by this scoped verification.

Reproduce the focused backend suite with `.venv/bin/python -m pytest -q
tests/unit/test_core_owner_plans.py tests/unit/test_core_plan_binding.py
tests/unit/test_package_contracts.py tests/unit/test_knowledge_agent.py
tests/unit/test_knowledge_decision.py tests/unit/test_guardian_agent.py
tests/integration/test_packages_api.py
tests/integration/test_agent_execution_graph_api.py`. Run frontend regressions
with `node --test tests/js/experimental_packages.test.cjs
tests/js/module_execution_editor.test.cjs`. The guarded route command is
`.venv/bin/python -m pytest -q
tests/integration/test_orchestrator_setup_loop.py::test_confirmed_setup_enters_original_initial_lhs_and_real_design`.
Detailed RED/GREEN reports, screenshots, isolated API evidence and cleanup
inventory remain in the ignored task validation workspace. No operating-server
restart, hardware actuation, staging, commit, tag or push was performed.

The final cleanup inventory found active static/schema/runtime/package/test
consumers for `agents/core/plans.py` and `packages/portability.py`; the latter is
the single replacement for the already removed in-file helper. No additional
code removal or archive move was safe, and Task 2 deleted nothing.

## Completion Criteria

Existing no-plan cycles pass, configured settings reach the correct core owner, exchange preserves definitions but not private runtime context, explicit application uses current module store and affects only the next run, IDE state reflects backend responses, and readers have one linked explanation. Call this the agreed first modularization milestone only after these checks; remote installers, marketplace, hot code replacement and multi-version execution remain out of scope.
