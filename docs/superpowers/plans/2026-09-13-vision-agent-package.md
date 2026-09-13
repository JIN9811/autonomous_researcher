<!-- atr-doc
doc_type: plan
subtype: implementation
status: active
authority: execution
execution_status: completed
audience: [developer, maintainer]
scope: [vision_agent, camera_vision_bridge, agent_packages, runtime_ide]
summary: Modularize the existing Vision owner and observation bridge while preserving robot control, evidence and orchestration paths.
governing_design: docs/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs: [docs/agents/vision_agent.md, docs/runtime/runtime_ide.md]
supersedes: []
-->

# Vision Agent and Camera/Vision Bridge Implementation Plan

**Goal:** Apply the approved package contract to Vision without changing its observation, interlock, reasoning, cancellation or handoff semantics.

**Architecture:** Reuse installed AgentModule/BridgeModule discovery, package composition, the shared execution catalog/runner, existing report APIs and the Runtime IDE graph renderer. Observation code belongs to the Camera/Vision bridge; robot movement and rollout control remain in LeRobot.

**Tech Stack:** Python, FastAPI, YAML, existing JavaScript UI, pytest and Node tests.

**Spec:** [Approved package contract](../specs/2026-09-13-package-agent-bridge-modularization-design.md) and [executable IDE contract](../specs/2026-09-13-executable-agent-ide-contract-design.md). The user approved Vision as the next owner and the existing LeRobot boundary.

## Global Constraints

- Work in the current checkout; baseline `f51c479`. No commits, pushes, model lifecycle changes or physical device actions during this implementation.
- Preserve `agent.vision_agent`, all existing tool IDs, AgentResult fields, evidence timestamps, intervention/stop order and run/loop/attempt storage paths. No new orchestration route.
- Keep ActiveCam move/capture/return and rollout stop in the existing LeRobot bridge. Camera/Vision declares this shared dependency; it does not copy or replace robot control.
- Virtual-device verification must call ATR-registered LLM routing; only equipment I/O is simulated. Deterministic tests are separate evidence, not model validation.
- Package `vision@1.0.0` refers to agent module `vision@1.0.0` and observation bridge `camera_vision@1.0.0`. Bridge code stays under `device_bridges/camera_vision/`.
- Legacy imports share canonical module identity. Preserve monkeypatch boundaries and moved file-relative repository roots. Never duplicate runtime objects or settings stores.
- Reuse the common five-area execution/implementation projection and existing graph canvas, ports, labels, legend and Inspector. Package Manager remains separate from Device Bridges. Document SVGs use the light document theme.
- Retain configuration, calibration, private memory and output files in existing local stores. Package manifests contain source references, not private connection values or experiment data.
- Use test-first implementation and scoped independent review. Workers do not spawn agents, commit, restart services or run hardware. Existing unrelated changes belong to the user.

### Task 1: Vision owner module and executable internal graph

**Files:** `agents/vision/{__init__,agent,decision,module,execution,structure}.py`, compatibility `agents/vision_agent.py` and `agents/vision_decision.py`, `graphs/modules/vision/module.yaml`, `app/bootstrap.py`, focused Vision module/execution tests and necessary existing discovery assertions.

**Interfaces:** `MODULE: AgentModule`, `VisionAgent.execution_catalog()`, and `execute_vision_graph()` follow Design/Specimen. Expose the existing `VisionAgent.run(state, ctx)` result contract. Module descriptor initially references no frontend projector until Task 3 adds it. Its dependencies declare camera_vision and existing LeRobot tools, not direct robot ownership.

- [x] Establish existing Vision/decision test results and add RED tests for discovery, aliases, invalid execution routes, fresh terminal results and original tool/result behavior.
- [x] Relocate owner and decision code without rewriting observation logic. Extract only genuine owner boundaries: preflight/task admission, the existing composite observation/interlock/review operation, and result delivery. Clearance verification remains its existing owner route. Preserve the original ordering of current-clear handling, stop handling and preflight checks.
- [x] Model explicit branch dependencies and once-only side-effect guards. Keep bounded LLM decisions and the placement stop-before-review behavior inside their real composite operation, with source-bound CODE relationships for High/Middle/Low/Guardian/Knowledge rather than invented executable steps.
- [x] Add the registered graph to module YAML, remove its decorative internal walk and explicit duplicate bootstrap registration. Verify code discovery, activation exclusion, original imports, graph compilation and existing run behavior.
- [x] Test changed valid graph node/edge identities are actually traversed, invalid bypasses fail before tools, cancelled/failed attempts do not repeat capture or stop, and module trace retains invocation identity.
- [x] Run `.venv/bin/python -m pytest tests/unit/test_vision_agent.py tests/unit/test_vision_decision.py` plus new focused module/execution tests; record RED/GREEN commands and results in the task report.

### Task 2: Observation bridge and Vision package

**Files:** `device_bridges/camera_vision/` module, observation runtime/providers/tools, README and requirements; compatibility imports for relocated camera/UTM/pose files; `packages/agents/vision/{package.yaml,README.md}`; focused bridge/package tests and affected existing discovery expectations.

**Interfaces:** `BridgeModule(module_id="camera_vision", version="1.0.0")` publishes actual current observation tools, runtime aliases, internal components, APIs and storage references. Package discovery consumes the exact-version YAML. Existing `register_camera_tools(registry, *, utm_state_observer, utm_runtime_manager, specimen_pose_tracker)` remains callable through its old import and keeps injected resources.

Integration points found during baseline inspection: `packages/service.py:installed_agent_packages` currently enumerates Design/Specimen, and `app/main.py:_package_service` supplies only Printer Fleet. Extend installed-code discovery using the existing agent discovery pattern; editable manifests must never grant imports. `camera_utm_bridge` is the existing graph's observation alias. Its legacy metadata also mentions shared LeRobot and protocol tools, so distinguish those dependencies from observation ownership. Keep the canonical observation reference at `docs/device_bridges/utm_vision_bridge.md` rather than creating a duplicate reference document. Existing camera tools are partly simulated by design; relocating them must not silently switch `camera.capture` to RealSense.

- [x] Add RED tests for package membership, camera runtime aliases, unchanged tool registration/injected resources, shared bridge projection and inactive import/export.
- [x] Group existing `utm_runtime_bridge`, `utm_state_observer`, `specimen_pose_tracker`, `realsense_bridge` and camera tool implementation under the observation bridge, keeping compatibility aliases and original root/path behavior. Do not move LeRobot files, create new camera implementations or enable unused RealSense routes.
- [x] Inspect actual imports and list required/optional Python dependencies and external runtime dependencies without installation or hardware probing. Preserve external checkout/config resolution without publishing private machine paths.
- [x] Describe real internal components so Device Bridges shows package → camera_vision and drill-down shows observation components, not separate package peers. Resolve only actual runtime aliases from current graph declarations.
- [x] Preserve shared UTM observer use by Equipment; no duplicate instances, automatic starts, or lifecycle ownership changes. Test original UTM/camera/pose fixture paths, cancellation and calibrated snapshot behavior.
- [x] Run focused package/bridge tests and `tests/unit/test_package_contracts.py`; report exact commands, RED/GREEN and no-actuation scope.

### Task 3: Vision presentation, IDE integration and documentation

**Files:** `agents/vision/presentation.py`, `agents/vision/frontend/live_report.js`, module descriptor, existing `app/main.py` and `web/static/planning.js` dispatch, `graphs/modules/vision/ui.yaml`, Vision and Camera/Vision references/index/matrix, modularization spec, generated Vision document SVG and focused API/JS tests.

**Interfaces:** Reuse Design/Specimen's `project_report(metadata, agent_payload)` and descriptor-based frontend host. Keep current Vision cards, image selection, verification tabs and shared host utilities; no new polling or global subscriptions. Existing generic module API and IDE projections consume installed descriptors.

Preserve the existing report's `state.latest_observations` precedence over `metadata.latest_vision_observation`; supply needed state observation context through the generic projection boundary without changing persisted metadata or another owner's report. The common host is `web/static/planning.js` and `web/static/agent_module_host.js`. Register the new asset in setuptools package data. Extend `scripts/render_module_control_views.py` and its parity tests to Vision; generate only changed module output and do not rewrite unrelated figures.

- [x] Add regression tests for report precedence, module asset routing, mount/unmount, inactive owner behavior and old Vision rendering contracts before extraction.
- [x] Move coherent Vision-owned projection/rendering behind existing host interfaces, preserving all current card data and interactions. Avoid duplicating shared camera helpers or introducing a second report store.
- [x] Verify original API report fields and frontend behavior with deterministic data; actual API saved graph must execute the registered Vision owner, not only pass a structural preview.
- [x] Update canonical English references, Status at a Glance, agent index/API-control matrix, bridge index and approved modularization spec. Describe composite reasoning and LeRobot dependency accurately.
- [x] Regenerate the Vision executable structure SVG from the common owner structure with the light document theme. Reuse existing IDE styling and curves; do not redesign the interface.
- [x] Run focused API/JS tests and changed-document/link/publication validation. Record results without inventing new physical proof.

### Task 4: Non-actuating integration and rendered verification

**Files:** Existing guarded cycle validation harness and test fixtures; new focused parity checks if needed; verification record in this plan.

- [x] Run affected Vision/UTM/camera/package/IDE/module regressions and Specimen linkage in virtual_bridge, installed_printer and physical_print modes with device boundaries intercepted.
- [x] Run a complete current orchestration cycle and next Design using actual ATR-registered model calls with virtual equipment and physical-effect guard. Record model attempts, owner sequence, timing and zero hardware effects in ignored validation artifacts.
- [x] Verify run/loop attribution, success/failure/cancel paths and no duplicate successful action. Separate retained physical evidence from new software-only verification.
- [x] Inspect module and bridge APIs and Runtime IDE at 1920×1080, including Vision internal CODE relationships, package→bridge and bridge internals. Do not execute the UI's run/device controls. Restart an idle service only with user authorization; otherwise verify the updated app in an isolated non-actuating test server.
- [x] Review the combined diff, update the verification record and report completed scope and any concrete remaining gaps. Do not commit or push this new package without a user request.

## Verification Record

Completed in the current checkout on 2026-09-13; no new Vision commit or tag is created by this plan.

| Verification | Result | Scope |
| --- | --- | --- |
| Final owner, bridge, package, API and documentation-test regression | 333 passed in 19.30 s | Existing Design/Specimen paths plus Vision and Camera/Vision |
| Original mode/path matrix, final rerun | 44 passed in 246.00 s | Virtual bridge, installed-printer and physical-print profiles; device boundaries intercepted |
| Registered API cycle | 1 passed in 358.76 s | 34/34 completed model calls across ten owners; full cycle and next Design |
| Frontend tests | 27 passed in the focused owner/shared and verification-tab groups | Six cards, module lifecycle, both snapshots, current-scope polling and stale-evidence rejection |
| Runtime IDE / Live GUI | Verified at 1920×1080 | Existing five-area CODE graph, package-to-bridge and provider drill-down, correct draft membership, both retained synthetic snapshots |
| Changed references | Eight canonical documents validated | Metadata, sections, links and source contracts; generated light-theme SVG parity |
| Publication boundary | 58 changed/new public files passed | Working-tree blobs checked without staging; private validation artifacts remain ignored |
| Independent review | No critical or important findings | Owner/bridge relocation, presentation extraction and cross-task contracts |

The registered cycle traversed Design → Specimen → Vision → Manipulation → Vision
→ Equipment → Manipulation → Vision → Analysis → Knowledge → BO → Guardian →
next Design. The saved ATR API route served `gpt-5.5-2026-04-23`. Recorded cycle
elapsed time was 357.934 s, physical call count was zero, and no effect was denied
during that cycle. This is **software/virtual-equipment evidence**, not a new
physical demonstration or local-model qualification.

Validation artifacts remain under ignored
`artifacts/validation/vision-module-20260913-aWZi54/`. Browser QA used a temporary
guarded host with synthetic resource/ROS topology data and retained synthetic-cycle
images; the existing user server was not restarted. No camera load, robot movement,
printer command or equipment protocol was executed through the browser.

### Retained baseline gaps

- The legacy `test_actual_runtime_equipment_success_enters_clear_in_same_loop`
  fixture fails before this migration: its registry omits the Orchestrator required
  by current stage-entry supervision. The fully populated guarded cycle above is
  the acceptance path; production admission was not relaxed.
- The older MJPEG source-text test expects rate-limit identifiers absent from both
  the baseline and relocated runtime. The assertion was not used to introduce
  unrelated streaming behavior.
- Whole-tree documentation validation still reports pre-existing Windows bridge
  reference and older PLC specification metadata/section issues. Changed canonical
  references pass their scoped checks.
