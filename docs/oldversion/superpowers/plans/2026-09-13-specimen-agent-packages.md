<!-- atr-doc
doc_type: plan
subtype: implementation
status: archived
authority: execution
execution_status: completed
audience: [developer, maintainer]
scope: [specimen_agent, printer_bridge, agent_packages, experimental_packages, runtime_ide]
summary: Preserve the Specimen fabrication route while adding owner modules, portable experiment drafts, and package composition.
governing_design: docs/oldversion/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs: [docs/agents/specimen_agent.md, docs/device_bridges/printer_fleet_bridge.md, docs/runtime/runtime_ide.md]
supersedes: []
-->

> Archived development history (2026-09-14). Not the current implementation or acceptance contract. See the [archive index](../../README.md) for current references.


# Specimen Agent and Experimental Packages Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development for scoped implementation and review. Work in the existing user-requested checkout. No commits, pushes, hardware calls, or operating-service restarts. Implementation workers use deterministic tests; the final cycle validation must also use ATR-registered real model routes under the physical-effect guard.

**Goal:** Apply the existing agent/module contract to Specimen and make Design/Specimen Agent Packages composable into importable, inactive Experimental Package drafts.

**Architecture:** Keep AgentRegistry, ToolRegistry, ModuleConfigStore, graph validation/activation, existing printer workflows and artifact writers. Separate owner implementation and UI through the Design pattern. Packages describe composition and portability, never execute or auto-install code.

**Tech Stack:** Python/FastAPI, YAML/JSON, existing vanilla JavaScript Runtime IDE, pytest, Node tests, intercepted Playwright.

**Spec:** [Approved modularization and package contract](../specs/2026-09-13-package-agent-bridge-modularization-design.md).

## Global Constraints

- Existing repository checkout; baseline `ba8e1f5`. Preserve the three pending specification edits.
- No physical devices, live device transport probes, server restart, commit or push. Test physical-mode semantics using intercepted transports and existing effect guards. Real model calls are included in final non-actuating cycle verification through ATR's registered routes; never substitute an unregistered model/provider or change live model lifecycle/settings.
- Preserve `agent.specimen_agent`, `SpecimenMakingAgent`, `printer.prepare`, `experiment.evaluate`, modes, slicing/placement/cooling/ejection, approvals, cancellation and run/loop/attempt archives.
- Agent Package IDs follow owner IDs: `design`, `specimen`. Shared bridge module ID `printer_fleet` refers to current Bambu/Prusa owner code, not a new printer protocol.
- Bridge source remains under `device_bridges/`, including when referenced by the same Agent Package; never nest or duplicate it under `agents/specimen/` or the package folder.
- Keep one Device Bridge Package at `device_bridges/printer_fleet/`, containing the shared runtime, internal Bambu/Prusa providers and requirements. Old Bambu/Prusa paths retain only compatibility aliases. Other bridge families remain outside this migration.
- Experimental Packages carry graph plans and portable owner configuration. Import returns an inactive draft; only existing explicit graph/module save and activation can change execution. No arbitrary Python imports or remote downloads.
- Keep private connection/configuration memory and runtime artifacts out of exports. Reject unknown fields, unresolved dependencies and conflicting versions rather than silently enabling substitutes.
- Five-area display uses editable registered owner operations plus source-bound CODE relationships; compact outcome labels stay on their curves. Document SVGs use the light document theme.
- Device Bridges opens an internal node-based Agent Package → Device Bridge Package → provider structure and Inspector. Package Manager is a separate IDE tab for membership and exchange. Both use installed contracts and the current draft; neither reports live hardware readiness.

### Task 1: Specimen owner module, executable graph, and presentation

**Status:** Implemented and reviewed. Durable deterministic state/result/tool
parity is covered; the isolated legacy fixture limitations are recorded below.

**Files:** `agents/specimen/{agent,decision,module,execution,structure,presentation}.py`, compatibility `agents/specimen_agent.py` and `agents/specimen_decision.py`, Specimen frontend assets, `graphs/modules/specimen/{module,ui}.yaml`, existing bootstrap/catalog/report dispatch and package-data declarations; focused Specimen/module/execution/API/JS tests.

**Interfaces:** Code discovery consumes `MODULE: AgentModule`; expose `specimen_execution_catalog(agent)` and owner `execution_catalog()` using the shared ExecutionCatalog and graph runner. `SpecimenMakingAgent.run(state,ctx)` retains AgentResult behavior. Use the installed registered module descriptor for report projection and local frontend assets, as Design already does.

- [x] Run baseline Specimen agent/decision/status/JS tests without live transports.
- [x] Add failing tests for code discovery, compatibility imports, inactive graph admission, catalog dependency gates, terminal fresh results, and unchanged tool sequence/output on deterministic fixtures.
- [x] Move owner code into `agents/specimen/` using compatibility shims. Split the existing run into meaningful owner operations at actual preparation/decision/result boundaries without replaying side effects. Keep the bounded decision/execution callback composite; inspect its internal calls through CODE relationships.
- [x] Remove legacy decorative internal steps from the migrated module; supply explicit outcomes and required producer dependencies. Wire the generic catalog lookup through registered owners where possible; keep ORC's special core context.
- [x] Extract the coherent existing Specimen report projection and frontend renderer behind existing host inputs; no duplicated polling, shared camera/STL helpers, or new settings store.
- [x] Verify real saved graph controls owner calls, branch errors cannot skip preparation, failures/cancellation do not duplicate successful fabrication, and existing mode fixtures retain outputs. Run `PYTHONPATH=. .venv/bin/python -m pytest tests/unit/test_specimen_agent.py tests/unit/test_specimen_decision.py tests/unit/test_specimen_execution_status.py` and added focused tests.
- [x] Report changed files, exact commands/results, RED/GREEN evidence and remaining risks. Do not commit.

### Task 2: Printer module and two package contracts

**Status:** Implemented and reviewed. Provider bodies preserve their previous
behavior; package import/export remains inactive and local-only.

**Files:** `device_bridges/printer_fleet/{module,bridge}.py`, internal `providers/`, package/provider requirements, `device_bridges/module_contract.py`, legacy aliases, `packages/{__init__,contracts,service,api}.py`, and `packages/agents/{design,specimen}/package.yaml`; existing tool registration/bootstrap; guarded API and package tests.

**Interfaces:** `BridgeModule.describe()` publishes code-owned ID/version/tools/provider/UI/storage references, never probes equipment. Package service accepts installed agent/bridge descriptions and existing graph validation callbacks. Public methods `catalog()`, `export_experimental(payload)`, `import_experimental(payload)` return JSON-compatible results. Mount `/api/packages` (catalog), `/api/packages/experimental/export`, `/api/packages/experimental/import` through an APIRouter; application owns injected graph/module stores and validators.

- [x] Test first that `design` needs no bridge, `specimen` resolves the existing printer_fleet module, two package references share one module, and missing/version-conflicting dependencies fail atomically.
- [x] Expose package-to-bridge membership in the catalog, including bridge ID/version, package ownership references, and declared provider components where applicable. Reading this data must not instantiate transports or probe devices.
- [x] Define strict versioned Agent Package and Experimental Package schemas, validated identifiers and exact versions. Experimental packages contain an embedded graph plan, selected agent package references, module configuration and portable bindings, not executable code, arbitrary file inclusion, or private machine-local paths. Keep existing declarative repository-relative graph/module references where required; never read and bundle their target files implicitly.
- [x] Reuse printer tool/provider registration without changing commands or provider selection; expose the existing 3DP workspace/API and storage paths as ownership references. No copying large bridge files solely for folder appearance.
- [x] Group the migrated Fleet/Bambu/Prusa bridges as explicitly requested, relocating rather than duplicating implementation. Adjust moved file-relative repository-root resolution, preserve old imports and monkeypatch boundaries, and verify provider routing with original fixtures. Requirements list actual imported third-party dependencies; document optional dependencies and external slicers separately, without installing anything or guessing new version floors.
- [x] Implement pure export/import validation with detached data, bounded input size and privacy checks. Export excludes runtime state and credentials; incoming unknown executable/connection fields are rejected. Include external/legacy graph owner dependencies explicitly; do not pretend all agents are migrated.
- [x] Import checks installed handlers and module graphs with existing validators and returns drafts plus locally unresolved binding requirements; it does not write or activate. Unit/API tests compare before/after stores and deny transports, processes and graph starts.
- [x] Test round trip with rearranged existing graph nodes, duplicate references, invalid edges/handlers, version mismatch, missing owners, private fields and removal of composition references without data deletion.
- [x] Report exact tests and ownership/activation boundaries; do not commit.

### Task 3: IDE package controls, documentation and integration verification

**Files:** existing `web/templates/runtime_ide.html`, `web/static/runtime_ide.js`, a focused `web/static/experimental_packages.js` helper if needed, Specimen/printer references, agent index/matrix, runtime documentation, generated Specimen five-area SVG, this plan verification record.

**Interfaces:** Existing graph editor is the editable draft host. Package controls call Task 2 APIs; export downloads JSON, import validates the chosen JSON file and explicitly loads the accepted draft into the current editor. Dirty drafts require replacement confirmation. Module configurations travel with the draft and use existing save/activation, never hidden POSTs on import.

- [x] Test pure package UI parsing/projection and stale/failed import preservation before implementation.
- [x] Keep Export/Import Experimental Package controls and membership in a separate Package Manager tab, preserving detached draft semantics.
- [x] Open Device Bridges using the existing IDE graph renderer: package → bridge contracts on the plane, then a separate drill-down graph for one bridge's internals. Reuse canvas background, coordinate system, ports, labels, legend and Inspector; no custom renderer. Resolve legacy bridge aliases from installed declarations, preserve other runtime bridges and Main/module drafts, and keep Package Manager separate.
- [x] Verify bridge click/open/back behavior, shared bridge membership, package addition/removal, empty states, and draft-versus-installed labels in unit/browser checks without any device request.
- [x] Validate actual served static files and API shape in guarded intercepted browser at desktop/narrow sizes; exercise Specimen CODE inspection, outcome label attachment, draft import/export and dirty-state preservation.
- [x] Update current references, index/matrix and approved package spec; preserve canonical files and old physical-proof scope. Generate the Specimen document SVG using the same source structure with document theme and verify parity.
- [x] Run module/execution/bridge/package/UI regressions plus existing guarded orchestration and per-loop archive suites. Record commands/counts and any pre-existing failures separately. No physical or model verification claim.
- [x] After integration, run the current orchestration graph through a complete non-actuating cycle and the next Design handoff, including Specimen, Vision, Manipulation, Equipment, Analysis and BO. Replace device/model boundaries with deterministic admitted fixtures under the existing effect guard, not a second production route; keep supervision, validation, transitions and loop/attempt archiving intact. Exercise applicable mode combinations and stop/failure branches. Report actual covered stages and zero physical calls; partial stage checks alone are not full-cycle proof.
- [x] Separately run the complete cycle with actual model calls through ATR-registered model/backend routing, keeping only physical/native device boundaries simulated. Record requested/served model identities, model calls and timing, agent outcomes, full stage sequence, and guard results. Do not label deterministic-model cycle timings or outcomes as real-LLM evidence. Do not start/stop models, install providers, or alter live settings for this check.
- [x] Run changed-document validation, publication/privacy tests, source-hash checks where applicable and `git diff --check`; finish with read-only review of the combined diff. Do not commit.

### Task 4: Preserve LLM execution on virtual-device paths

User clarification: `virtual_bridge` means real agent reasoning and tool calling
with simulated equipment I/O, not a successful preflight that skips decisions.

**Scope:** Existing resolved virtual-device selection, Vision/Manipulation/Equipment
decision paths, existing virtual transport boundaries and their regression tests.
Keep all installed-printer/physical-print commands and explicit standalone
preflight behavior; mixed real/virtual profiles retain operator handoff gates.

- [x] Reproduce the skipped decision as a failing regression. Model unavailability
  must not become successful virtual preflight.
- [x] Distinguish virtual device execution from explicit preflight. Reuse existing
  decisions, tool names, virtual bridge implementations, archives and graph edges;
  do not add model calls only to satisfy a counter or manufacture owner success.
- [x] Check every reached device/native boundary. Explicit virtual transport cannot
  be promoted to real by saved connection settings. No native camera, robot process,
  device network request or sidecar start occurs during a virtual cycle.
- [x] Retain evidence identity, fresh same-capture image review, CSV processing,
  once-only execution and mixed-mode physical authorization. Synthetic observations
  are identified as such and cannot authorize real manipulation/equipment.
- [x] Verify deterministic regression coverage, then real registered API calls for
  every agent decision layer through the current cycle and next Design handoff.
  Record each model owner, outcome, timing, tool results and zero physical effects.
  Explicit offline fixtures remain useful regression evidence, never LLM evidence.

## Verification Record

### Printer Fleet consolidation and IDE separation — 2026-09-13

Printer Fleet is one Device Bridge Package. The canonical manager, internal
providers, G-code transformer and requirements are under its directory. Legacy
imports share the same runtime module objects. Provider selection, existing
3DP APIs, storage and physical gates were not rewritten.

| Check | Result |
|---|---|
| Fleet/package, Bambu, Prusa and printer tools | 164 passed; 5 existing warnings |
| Specimen three-mode prefix, module/API linkage | 19 passed; 75 existing warnings |
| IDE navigation/module lifecycle and package API | 7 passed; 10 existing warnings |
| Bridge structure renderer | 1 passed; safe text, no management controls, unchanged-update preservation |
| Package projection and bridge topology | 11 Node tests passed |
| Registered-model full virtual-device cycle | 1 passed; 394.57 s pytest / 393.809 s cycle |
| Actual model requests | 34 successful, 0 failed; gpt-5.5 through the saved ATR API route; all 10 owners |
| Physical effects | 0 calls; no denied effects |

The three prefix modes are `virtual_bridge`, `installed_printer`, and
`physical_print`. The last two execute the existing preparation, placement and
G-code patching path with intercepted slicer/transport boundaries, not hardware.
The installed-printer artifact omits the print body and cooling; physical-print
retains the print body and cooling. Default Bambu and explicit Prusa dispatch
are additionally exercised by the original printer-tool tests.

The real-model cycle follows Design → Specimen → Vision → Manipulation → Vision
→ Equipment → Manipulation → Vision → Analysis → Knowledge → BO → Guardian →
Design. Device data is synthetic and background FEM is not executed. No claim
of new physical validation is made. Local evidence is retained under the ignored
`artifacts/validation/printer-fleet-package-20260913/` directory; credentials,
prompts and user memory are not part of the published record.

Browser verification at `/ide` uses the existing server: bridge entry opens a
relationship canvas and node Inspector, while **Package Manager** opens a separate
tab with membership and exchange controls. Back preserves Main/agent drafts and
Dry-run Trace. After the user's subsequent restart approval, the existing server
was restarted with its launch command and environment preserved. It returned to
idle; the catalog API and 1920×1080 IDE then showed the canonical fleet manager
and internal provider paths. No graph run or device action was started.

#### Two-level bridge canvas correction

The bridge view now reuses the standard IDE graph renderer and Inspector rather
than a separate SVG implementation. The plane contains package → bridge links;
Printer Fleet internals contain its manager and Bambu/Prusa providers. Declared
runtime aliases prevent duplicate printer nodes. Other runtime bridge contracts
remain visible, without invented package owners. Contract projections reject
route edits, catalog drops and graph execution. Global operator stop controls
remain available. Closing an agent tab into Package Manager also activates the
correct workspace instead of leaving the closed canvas visible.

- IDE/package/API/document regression: **87 passed**, 10 existing warnings.
- Package projection and two-level topology: **12 Node tests passed**.
- Specimen three-mode prefix and module/API regression: **19 passed**,
  75 existing warnings, **39.05 seconds**; all device boundaries intercepted.
- Browser: `/ide`, **1920×1080**; plane/internal navigation, provider isolation,
  Package Manager separation, standard canvas background, port alignment and
  Inspector checked. No app console warnings/errors observed.
- This correction does not add physical or new full-LLM-cycle evidence; the
  earlier registered-model cycle above remains a separate verification record.

### Approved follow-up: Guardian/Knowledge BO admission repair

The user approved this bounded follow-up after the actual-model run exposed the
misclassification. Keep the existing checkout and all earlier changes; no hardware,
server restart, model lifecycle change, commit or push.

- [x] Reproduce `peak_at_curve_boundary` becoming a BO risk; match BO as a domain
  token/code rather than a substring while retaining genuine BO unsafe rejection.
- [x] Separate Knowledge archival incident metadata from current failure tags.
  Preserve the full historical records for retrieval; do not turn component,
  severity, risk class or tool names into fresh error codes. Current explicit
  failures, active hardware alerts and stop/approval gates remain authoritative.
- [x] Consume canonical Analysis BO readiness with conservative conflict handling:
  explicit false/malformed current claims cannot be overridden by true legacy
  fields, and missing evidence cannot authorize BO. Retain supported legacy inputs.
- [x] Add regressions for the observed warning, archival metadata, genuine current
  BO/data failures, stop/approval signals and conflicting readiness. Use real gate
  and Knowledge projections with isolated I/O, not fixed successful gate results.
- [x] Review the scoped correction, then rerun the same registered-model virtual
  cycle through BO, Guardian and next Design; record actual coverage and effects.
- [x] Update current Guardian/Knowledge references and this verification record.


Implementation, registered-model acceptance and the final combined review are
complete for this scope, with no remaining Important/Critical review findings.
Offline regression results do not establish
real-model or physical success. Counts below describe individual
checks and overlap; they must not be summed as distinct coverage.

| Check | Result | Scope |
|---|---|---|
| Printer tools and printer workflow modes, before bridge relocation | 7 passed, 5 warnings | Virtual/intercepted provider fixtures; no hardware validation |
| Three changed specifications and this plan | 4 documents validated | Metadata and document contracts; not implementation completion |
| Specimen module, owner API and presentation | 67 Python and 37 JavaScript checks passed; 12 module checks passed after durable golden coverage | Original results, state and tool payloads; no hardware |
| Package contracts and owner API | 49 passed | Installed dependencies, inactive import/export, privacy and validation |
| IDE package controls | 9 focused JavaScript checks and intercepted desktop/narrow browser acceptance passed; UI re-review approved | Membership, closed-tab configuration, imported identity/version/bindings and newer edits survive export; import does not activate |
| Relocated printer providers | 150 passed | Intercepted existing provider paths; source-body comparison also verified |
| Resolved virtual decision/transport regressions | 303 passed | Owner decisions, camera/robot/Equipment simulation and failure handling; deterministic model fixtures |
| Mode resolver and installed/hybrid admission | 16 combinations and 5 controller checks passed | Existing mode boundaries retained; no physical device calls |
| Current virtual graph through next Design | 1 passed, 95.53 seconds | Offline decisions, 13 graph events, CSV processing, BO once, all first-loop owner archives and zero physical effects |
| Bounded orchestration handoff projection | 29 passed | Complete current receipts admitted within 32,000 UTF-8 bytes; larger contracts rejected before a model call |
| Vision acquisition/review prompt separation | 119 passed | Acquisition does not demand a not-yet-captured image; post-capture evidence checks retained |
| Host transport authority and scoped simulator screenshots | 284 passed; scoped re-review approved | Model fields cannot choose simulated transport for a physical request; standalone and resolved virtual workflow identities agree |
| Candidate-matched virtual camera | 151 focused checks passed; virtual tail passed in 56.41 seconds | Current STL rendering, distinct identity/content hashes, same-capture detector/overlay, missing/invalid/zero-area mesh rejection and unchanged physical/legacy paths |
| Documentation/publication rules and source-driven SVGs | 56 passed; registered-model check skipped without opt-in | Validator and renderer behavior; not model or physical validation |
| Final module/package/API/document regression | 117 passed, 63 existing warnings, 14.91 seconds | Existing provider isolation, saved owner execution, package admission, documentation and SVG rules |
| Guardian/Knowledge BO admission correction | 48 passed, 5 existing warnings, 1.07 seconds | Curve-boundary classification, canonical/legacy readiness, archival/current evidence and genuine BO/data/stop/approval controls |
| Existing Guardian agent, action shield and fault matrix | 32 passed, 5 existing warnings, 0.60 seconds | Existing current-state gates and tool-action protections |
| Final documentation/publication check | 46 passed, 0.19 seconds; changed Markdown validation and diff whitespace checks passed | Public document contracts, publication rules and final scoped review |
| Registered API full-cycle acceptance, after admission repair | 1 passed, 61 existing warnings, 343.50 seconds; 34 completed actual API calls across all 10 owners | Exact 13-event route through BO, Guardian and next Design; first-loop archives, once-only simulated skills, CSV processing and zero physical calls/denied effects |

The registered API check used the existing `gpt-5.5` route (served model
`gpt-5.5-2026-04-23`), no mock fallback and zero physical calls or denied effects.
Vision used its existing per-run timeout setting of 90 seconds in the isolated
test only; the production default of 45 seconds and evidence freshness admission
were not changed. The passing cycle took 342.667 seconds inside the test
(343.50 seconds including pytest overhead), with no failed model completion.
Model owners were Orchestrator, Design, Specimen, Vision, Manipulation, Equipment,
Analysis, Knowledge, BO and Guardian. The completed event sequence was:

`Design → Specimen → Vision → Manipulation → Vision → Equipment → Manipulation → Vision → Analysis → Knowledge → BO → Guardian → Design`.

The check uses `tests/integration/test_specimen_registered_model_cycle.py` with
`AX4LAB_VERIFY_REGISTERED_MODEL_CYCLE=1`. Sanitized model-call and cycle summaries
are retained under ignored `artifacts/validation/`; they contain no prompts,
responses or credentials and are separate from operational Knowledge stores.
Device observations and experiment data are synthetic; background FEM and
physical hardware were not executed. No direct handoff or approval was forced.

The earlier diagnostic attempt stopped at BO owner review after 25 completed
calls across eight owners. Its 506.483-second duration includes the review wait,
not a latency benchmark. Its failed acceptance remains distinct from the passing
post-correction cycle and the deterministic offline cycle above.

Read-only tracing found that the current Analysis quality gate and BO handoff
both permit BO. The warning `peak_at_curve_boundary` is misclassified by the
existing Guardian substring check (`"BO" in text` matches `BOUNDARY`), and
Knowledge promotes incident classification metadata such as `data` into failure
tags. Guardian also consults older readiness locations rather than these canonical
handoff fields. The user subsequently approved the scoped follow-up above:
token-aware classification, conservative canonical readiness and separation of
historical evidence from current failure signals. The original failure remains
an audit record, not evidence that the generated candidate was physically unsafe.

Existing isolated fixtures remain explicit limitations: the original Specimen
suite has two missing-supervisor fixture failures, the separate archive fixture
expects success from an intentionally failing offline supervisor, and four old
clearance fixtures omit the required registered Orchestrator. Production admission
was not weakened to make these fixtures pass. Focused suites also report existing
schema and NumPy warnings. No whole-repository pass is claimed.
