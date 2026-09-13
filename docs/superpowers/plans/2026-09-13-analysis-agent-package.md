<!-- atr-doc
doc_type: plan
subtype: migration
status: active
authority: execution
audience: [developer, maintainer, researcher]
scope: [analysis_agent, cae_bridge, agent_packages, runtime_ide]
summary: Preserve the current Analysis foreground and background behavior while installing its owner package and computational CAE bridge contract.
plan_status: implementation_verified
execution_status: completed
governing_design:
  - docs/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs:
  - docs/agents/analysis_agent.md
  - docs/device_bridges/cae_computation_bridges.md
  - docs/superpowers/specs/2026-09-13-executable-agent-ide-contract-design.md
supersedes: []
-->

# Analysis Agent Package implementation

## Status at a Glance

| At a glance | Details |
|---|---|
| Status | Implementation and bounded non-actuating verification complete; final review approved |
| Owner | Analysis Agent; measured data processing and independent background FEM |
| Bridge | Existing computational CAE facade and CalculiX provider |
| Preserved | Numerical settings, model decisions, tool contracts, handoffs and artifact paths |
| Validation | Non-actuating tests, registered-provider virtual cycle and read-only UI checks |
| Excluded | Hardware operation, new physical models and unrelated folder cleanup |

## Goal and authority

Apply the approved [package contract](../specs/2026-09-13-package-agent-bridge-modularization-design.md) to Analysis and its existing computational CAE bridge. Baseline: `d29a70e9b2fce5ee0bc272dad2acdbfa13fa7eb5`. Preserve measured-data delivery to BO and independently running FEM.

## Global Constraints

- Work in the current checkout. Do not commit, tag, push, restart the user server, operate hardware, launch native FEM, alter saved model credentials, or change solver/material/loading settings.
- Modularize ownership, not behavior. Preserve tool names, result shapes, archives, cancellation, admission, queues and current test-mode paths. Keep composite owner work intact; no additional workflow stages or done states.
- High means actual LLM decisions; Middle includes software APIs and numerical solvers. A computational bridge is not a physical Low device. Keep five-area backgrounds, existing node/edge styling, `LLM` for High and `LLM call` for invoking processes.
- Agent Package and bridge are distinct. Declare Analysis package → CAE bridge → its existing internal components. Bridge code remains under `device_bridges/`.
- Use exact legacy module identity aliases and existing module/discovery/report/asset/package contracts. No parallel registry, transport or settings store. Shared services and existing FEM UI assets may remain declared owned references.
- Measured foreground Analysis must reach BO without awaiting background FEM. Do not hot-unload running jobs or introduce an unload API. Existing worker/resource lifetime stays unchanged across graph activation and loop turnover.
- Scope excludes new physical models, PINN activation, new calibration behavior and unrelated bridge-folder cleanup. Retain validation artifacts only in ignored validation storage.

### Task 1: Analysis backend and computational bridge ownership

Read Global Constraints as binding. Reference the existing `agents/equipment/`, `device_bridges/windows_pyautogui/`, `packages/agents/equipment/` implementation.

Files: create `agents/analysis/` owning the existing agent, decisions, runtime, improvement, refinement, mechanisms, calibration and FEM files; preserve flat `agents/analysis_*.py` exact `sys.modules` aliases. Add `module.py`, `execution.py`, `structure.py`, `presentation.py`. Create `device_bridges/cae/` owning existing CAE and CalculiX implementations and tool-registration modules, with legacy bridge/tool aliases, `module.py`, `requirements.txt`, README. Leave PINN inactive and shared. Add `packages/agents/analysis/package.yaml` and README. Update bootstrap, execution catalog lookup and `graphs/modules/analysis/module.yaml` using existing extension contracts.

1. Write focused failing tests for module discovery, legacy identity/monkeypatches, bridge discovery/package binding, source-catalog resolution, graph invocation once, archive ownership and existing tool queues.
2. Move implementations mechanically, adjusting only imports and location-dependent paths. Audit every `__file__` use. Preserve function bodies, including solver defaults and numerical calculations. Use existing project path helpers where appropriate.
3. Wrap the existing archived run with a single guarded composite `analysis.task` and `analysis.deliver` execution graph, following Equipment. Keep the archive decorator once. A graph must not execute the composite twice in one invocation.
4. Describe actual High decisions and Middle orchestration/numerical/FEM work through the existing source-backed implementation catalog, not extra executable operations. No fake physical Low node. Move existing report profile/projection into `presentation.py` with equivalent output through generic host delegation; frontend extraction is Task 2.
5. Register Analysis once through discovery; preserve every `cae.*` and `calculix.*` tool and the `cae:calculix` queue. Bridge discovery must not instantiate native solvers.
6. Use focused guarded tests plus existing Analysis unit/background lifecycle and two-loop parallel tests. No real native executables. Prove measured foreground delivery and background job/resource preservation with existing safe test doubles. Audit behavioral equivalence against baseline.

Acceptance: old imports preserve object identity; one installed Analysis; one computational CAE bridge containing CalculiX; package resolves; original owner run executes once; measured/FEM/BO paths remain equivalent. Report exact tests and any baseline failure, without declaring mock LLM tests real-provider evidence.

### Task 2: Analysis frontend, IDE, documentation and integration

Read Global Constraints as binding. Consume Task 1's installed Analysis module, execution/source catalog, report projector and CAE bridge/package declarations.

Files: `agents/analysis/frontend/live_report.js`, `graphs/modules/analysis/ui.yaml`, narrow host edits in `web/static/planning.js` and module/UI wiring where necessary; related Analysis/bridge/index/runtime docs and approved modularization/executable-IDE specs. Reuse existing document SVG exporter and documentation theme.

1. Write failing focused frontend/module-asset tests, then extract only Analysis-specific report/details/dashboard composition into the owner frontend. Preserve the existing Analysis FEM controller, four evidence cards, pagination, mount/unmount, polling conditions and request lifecycle. Shared host helpers may be injected. Do not remove or duplicate `liveAnalysisFemController`, `refreshLiveAnalysisFemEvidence`, or FEM mounts accidentally.
   The user-requested refinement makes all four FEM panels independent common Live dashboard cards. They reuse the standard header, section selection and grid spacing while their existing data hooks and in-place controls remain controller-owned.
2. Use installed module ownership for assets/cards; inactive graph owners disappear through the existing host contract. Preserve safe historical/read-only evidence access, no unsolicited background-job cancellation.
3. Show the actual source-backed five-area internal relationship view and Analysis package → CAE bridge → internal solver/provider graph, with the existing canvas/node/port/edge styles and `LLM`/`LLM call` distinction. No substitute management screen.
4. Update current English owner/bridge/index/API docs, plan/spec implementation status and source paths. Preserve meaningful prior successful physical/numerical evidence as historical evidence; this work is software modularization only. Regenerate relevant document-theme SVGs through the existing exporter. Do not generate raster art.
5. Run focused JS/Python report/asset/IDE tests and document links/source validation. Controller separately runs current-graph registered-API virtual-device cycle and 1920×1080 read-only browser verification; incorporate only actual outcomes when supplied.

Acceptance: Analysis live report/FEM cards remain equivalent and owned; IDE internals share backend definitions, no hardware classified as computation or vice versa; documentation reflects implemented boundaries and actual evidence.

## Verification record

Task 2's focused owner/host/FEM Node tests and guarded Python module/API/source
contract tests pass. The document-theme Analysis control SVG was regenerated from
the installed source catalog. A cache-version contract prevents the new owner
asset from loading with stale host services. The final browser run confirmed four
independent common card wrappers, report-section selection, attempt navigation,
stress/strain switching, contour frame/field selection and the preserved compact
FEM job pointer/polling. No server, hardware or native solver was started by the
implementation task.

The controller's scoped registered GPT-5.5 Analysis check passed once in 7.06 s:
two actual decisions (`data_processing`, `data_validation`) produced a BO-ready
measured observation before FEM, with zero physical calls and no denied effects.
The separate offline two-loop background-resource-held check passed once in
45.26 s. A five-case mode-route regression also passed in 137.53 s with controlled
LLM/device boundaries and no denied physical effects.

The whole real-API virtual cycle did **not** pass. Attempt 1 stopped on Vision
review of the synthetic block/gyroid identity. Attempt 2 stopped on Manipulation
review and then a 902 s Guardian recovery timeout after ten calls. Both failures
occurred before Analysis; physical-call count remained zero and no effects were
denied. These upstream failures are retained and are not presented as an Analysis
or complete-cycle pass. No new physical or native-FEM validation is claimed.
