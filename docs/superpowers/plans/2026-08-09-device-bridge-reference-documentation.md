# Device Bridge Reference Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish eight code-backed device-bridge References, 24 editable/rendered architecture figures, cross-bridge navigation, and automated drift validation.

**Architecture:** Treat an operator-visible capability boundary—not each Python class and not only graph metadata—as the documentation unit. Each active Reference follows one 19-section contract and owns three Graphviz figures; the index and matrix classify graph, tool, API, provider, sidecar, artifact-transformer, and test-only boundaries without changing runtime behavior.

**Tech Stack:** Markdown with YAML front matter, Graphviz DOT/SVG, Python documentation validator, pytest, git.

## Global Constraints

- Create exactly eight canonical bridge References under `docs/device_bridges/` plus one index and one matrix.
- Create exactly 24 stable `.dot` sources and 24 same-stem `.svg` renderings under `docs/device_bridges/assets/figures/`.
- Every Reference contains all 19 H2 sections from the approved Design and embeds three figures with stable captions.
- Documentation reports inspected implementation, configuration, registered tools, imported API routes, and known gaps; it does not claim live reliability, safety effectiveness, or scientific validity.
- Do not change bridge, provider, tool, API, graph, safety, or runtime behavior.
- Do not stage or modify the user's pre-existing `.env.example` change.
- Full `pytest` is not a completion gate; run focused documentation and selected bridge tests and report any unrelated full-suite result separately.
- Commit documentation in reviewable groups and push only after final verification.

---

### Task 1: Encode the Bridge Documentation Contract as Failing Tests

**Files:**
- Modify: `tests/unit/test_documentation_validation.py`
- Modify: `scripts/validate_documentation.py`

**Interfaces:**
- Consumes: existing `validate_repository(root: Path) -> list[str]` behavior and agent-figure validation patterns.
- Produces: `DEVICE_BRIDGE_REFERENCE_FILES`, `DEVICE_BRIDGE_REQUIRED_SECTIONS`, `DEVICE_BRIDGE_FIGURE_STEMS`, and validation errors for missing assets, captions, index links, and root rows.

- [ ] **Step 1: Add fixture builders for a minimal eight-Reference bridge documentation tree**

Add test helpers that write the index, matrix, eight 19-section References,
three `.dot`/`.svg` pairs per Reference, and eight root-table rows. Use the
stable stems from the approved Design rather than deriving names from files.

- [ ] **Step 2: Add focused failing tests**

Cover at minimum:

```python
def test_validator_requires_all_device_bridge_reference_sections(tmp_path: Path) -> None: ...
def test_validator_requires_device_bridge_figure_source_and_render(tmp_path: Path) -> None: ...
def test_validator_requires_device_bridge_caption_and_embed(tmp_path: Path) -> None: ...
def test_validator_requires_device_bridge_index_navigation(tmp_path: Path) -> None: ...
def test_validator_requires_root_device_bridge_rows(tmp_path: Path) -> None: ...
```

- [ ] **Step 3: Run the new tests and confirm contract failures**

Run:

```bash
pytest -q tests/unit/test_documentation_validation.py -k device_bridge
```

Expected: FAIL because the validator has no device-bridge contract yet.

- [ ] **Step 4: Implement the minimal validator inventory and checks**

Follow the existing agent validation structure. Report stable, path-specific
messages for missing governed files, sections, figure pairs, embeds, captions,
index links, root links, and extra undeclared figure assets. Do not require
optional live hardware or import the application runtime in this validator.

- [ ] **Step 5: Run the focused validator tests**

Run:

```bash
pytest -q tests/unit/test_documentation_validation.py -k 'device_bridge or agent_reference'
```

Expected: PASS.

- [ ] **Step 6: Commit the validation contract**

```bash
git add scripts/validate_documentation.py tests/unit/test_documentation_validation.py
git commit -m "test: define device bridge documentation contract"
```

### Task 2: Create the Bridge Index, Matrix, and Printer References

**Files:**
- Create: `docs/device_bridges/README.md`
- Create: `docs/device_bridges/bridge_api_connection_matrix.md`
- Create: `docs/device_bridges/printer_fleet_bridge.md`
- Create: `docs/device_bridges/bambu_x2d_bridge.md`
- Create: `docs/device_bridges/prusa_mk4s_bridge.md`
- Create: nine DOT/SVG pairs with `printer_fleet_*`, `bambu_x2d_*`, and `prusa_mk4s_*` stems.

**Interfaces:**
- Consumes: `configs/devices.yaml`, printer tool registration, printer manager/provider implementations, `/api/printer/*`, graph bridge metadata, printer hardware Guides, and focused tests.
- Produces: canonical printer routing/provider References and the shared inventory/matrix skeleton used by all later References.

- [ ] **Step 1: Write the index and matrix classification model**

The index table labels each of the eight boundaries with the applicable
classification values. The matrix compares entry tools, APIs, protocols,
configuration, modes, highest effect, stop/status owner, evidence, and
unknown-effect rule. Populate printer rows now and all remaining rows in their
own tasks.

- [ ] **Step 2: Write the Printer Fleet Reference**

Document explicit provider selection, `allow_automatic_fallback`, profile and
connection memory, `printer.prepare`, `/api/printer/fleet`, manager routing,
shared status, and the distinction between the graph's Prusa label and the
current Bambu default.

- [ ] **Step 3: Write the Bambu X2D Reference**

Document Bambu Studio slicing, deterministic autoejection patching, MQTT
report/request flow, FTPS storage probing/upload, LAN video, HTTP artifact
routing, start draft/gate/publish, bed-clear proof, and the boundary between a
pure file patch and a physical printer command.

- [ ] **Step 4: Write the Prusa MK4S Reference**

Document PrusaSlicer, PrusaLink authentication/status/upload/start, virtual
PrusaLink, G-code safety and bounds, optional paddle/bed-sweep ejection, live
allow flags, state polling, and restart rules.

- [ ] **Step 5: Create and render the nine printer figures**

Each provider gets System/Handoffs, Execution/Effect, and API/Connections
figures. Render with:

```bash
find docs/device_bridges/assets/figures -name 'printer_fleet_*.dot' -o -name 'bambu_x2d_*.dot' -o -name 'prusa_mk4s_*.dot' | sort | while read -r source; do dot -Tsvg "$source" -o "${source%.dot}.svg"; done
```

- [ ] **Step 6: Run validator and printer bridge tests**

Run:

```bash
python scripts/validate_documentation.py
pytest -q tests/unit/test_bambu_bridge.py tests/unit/test_bambu_autoejection.py tests/unit/test_prusa_bridge.py
```

Expected: bridge-document completeness may still report later missing
References, while printer-specific content/assets and bridge tests pass.

- [ ] **Step 7: Commit printer documentation**

```bash
git add docs/device_bridges
git commit -m "docs: add illustrated printer bridge references"
```

### Task 3: Create the LeRobot and Windows Equipment References

**Files:**
- Create: `docs/device_bridges/lerobot_bridge.md`
- Create: `docs/device_bridges/windows_pyautogui_bridge.md`
- Create: six DOT/SVG pairs with `lerobot_*` and `windows_pyautogui_*` stems.
- Modify: `docs/device_bridges/README.md`
- Modify: `docs/device_bridges/bridge_api_connection_matrix.md`

**Interfaces:**
- Consumes: LeRobot and Windows bridge classes/configs, registered tools,
  `/api/lerobot/*`, `/api/equipment/windows/*`, install-side bridge server,
  profiles/memory, Guides, and tests.
- Produces: canonical robot/process and token-gated desktop-effect References.

- [ ] **Step 1: Write the LeRobot Reference**

Cover profiles/ports, camera capture, teleoperation, recording, training,
rollout lifecycle, joint telemetry, policy and dataset operations, Isaac
render/Mimic/RL/mirror sidecars, subprocess ownership, serial/camera/device
effects, stop/status routes, and evidence before restart.

- [ ] **Step 2: Write the Windows PyAutoGUI Reference**

Cover discovery, candidates, token header, allowed actions/hotkeys/limits,
registered programs, locator capture, screenshots, UTM profile, local bridge
supervisor, live-preflight/validation, request log, proof package, completion
audit, desktop effect, and uncertain-effect recovery.

- [ ] **Step 3: Create and render six figures**

Use the stable stems and common visual grammar. Show LeRobot subprocess/serial
and Windows HTTP/PyAutoGUI targets separately from their API workspaces.

- [ ] **Step 4: Complete index and matrix rows**

Add exact graph/tool/API classifications and link all new figures.

- [ ] **Step 5: Verify focused contracts**

Run:

```bash
pytest -q tests/unit/test_lerobot_bridge.py tests/unit/test_equipment_pyautogui_bridge.py tests/unit/test_windows_pyautogui_bridge_server_helper.py tests/integration/test_lerobot_gui_api.py tests/integration/test_local_pyautogui_bridge_api.py
```

Expected: PASS, except any environment-dependent selection must be reported
and narrowed to deterministic contract tests rather than hidden.

- [ ] **Step 6: Commit robot and equipment documentation**

```bash
git add docs/device_bridges
git commit -m "docs: add illustrated robot and equipment bridge references"
```

### Task 4: Create UTM Vision, Computation, and Simulator References

**Files:**
- Create: `docs/device_bridges/utm_vision_bridge.md`
- Create: `docs/device_bridges/cae_computation_bridges.md`
- Create: `docs/device_bridges/base_simulator_bridges.md`
- Create: nine DOT/SVG pairs with `utm_vision_*`, `cae_computation_*`, and `base_simulator_*` stems.
- Modify: `docs/device_bridges/README.md`
- Modify: `docs/device_bridges/bridge_api_connection_matrix.md`

**Interfaces:**
- Consumes: UTM runtime/camera/pose/state components, CAE/CalculiX/PINN bridges
  and tools, simulator/base classes, APIs, configs, Guides, and tests.
- Produces: canonical observation/runtime, scientific-computation, and
  deterministic-test boundary References.

- [ ] **Step 1: Write the UTM Vision Reference**

Cover ROS workspace process lifecycle, topics, MJPEG/frame paths, camera
configuration/device discovery/calibration, RealSense one-frame capture,
specimen pose freshness/release, UTM state observation, macro compatibility,
virtual test behavior, and stale/missing evidence handling.

- [ ] **Step 2: Write the CAE Computation Reference**

Cover the CAE facade and deterministic mode, CalculiX preflight/input/solve/
postprocess/job path, PINN dataset/train/predict/registry path, executables,
subprocess gates, artifact identity, timeout/cancellation, and the absence of a
physical device effect.

- [ ] **Step 3: Write the Base and Simulator Reference**

Cover the `execute(command, payload)` abstraction, deterministic printer,
camera, robot, and UTM substitutes, compatibility shells, tool-registry access,
schema fidelity limits, and why simulation cannot support live claims.

- [ ] **Step 4: Create and render nine figures**

Show ROS/camera and computation subprocess connections explicitly. The
simulator Effect figure must terminate before external-device effect and label
that absence as test-only behavior.

- [ ] **Step 5: Complete index and matrix rows**

Add the remaining classifications, APIs, protocols, modes, effects, evidence,
recovery rules, and figure links.

- [ ] **Step 6: Verify focused contracts**

Run:

```bash
pytest -q tests/unit/test_utm_runtime_bridge.py tests/unit/test_realsense_bridge.py tests/unit/test_specimen_pose_tracker.py tests/unit/test_cae_tools.py tests/unit/test_multifidelity_contracts.py
```

Expected: PASS.

- [ ] **Step 7: Commit the remaining References**

```bash
git add docs/device_bridges
git commit -m "docs: complete illustrated device bridge references"
```

### Task 5: Govern and Expose the Bridge Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/standards/documentation_standard.md`
- Modify: `docs/document_manifest.yaml`
- Modify: `docs/device_bridges/README.md`
- Test: `tests/unit/test_documentation_validation.py`

**Interfaces:**
- Consumes: all ten bridge documents and 24 figure pairs.
- Produces: root entry table, governed manifest membership, normative bridge
  figure contract, and complete repository navigation.

- [ ] **Step 1: Add the root Device Bridge References table**

Place it after Agent References and before Safety. Include exactly eight rows
and direct Details/Flow/Execution/Connections links.

- [ ] **Step 2: Update documentation navigation**

Link the bridge index and matrix from `docs/README.md`; add all ten new
Markdown documents to `docs/document_manifest.yaml`.

- [ ] **Step 3: Add normative Documentation Standard rules**

Specify the eight-file inventory, 19-section contract, 24 stems, DOT/SVG
pairing, caption and visual rules, classification labels, root table, update
obligations, and inspection-only evidence boundary.

- [ ] **Step 4: Run documentation and paper validation**

Run:

```bash
python scripts/validate_documentation.py
python scripts/validate_paper_publication.py
pytest -q tests/unit/test_documentation_validation.py tests/unit/test_paper_publication_validation.py
```

Expected: PASS.

- [ ] **Step 5: Commit governance and navigation**

```bash
git add README.md docs/README.md docs/standards/documentation_standard.md docs/document_manifest.yaml docs/device_bridges/README.md tests/unit/test_documentation_validation.py scripts/validate_documentation.py
git commit -m "docs: govern device bridge references"
```

### Task 6: Final Verification, Audit, and Publication

**Files:**
- Verify only: all changed files

**Interfaces:**
- Consumes: committed documentation, validator, figures, and focused tests.
- Produces: evidence-backed completion report and pushed commits.

- [ ] **Step 1: Check source/render freshness for all 24 figures**

Render each DOT source to a temporary directory and use `cmp` against the
checked-in same-stem SVG. Expected: all 24 byte comparisons succeed.

- [ ] **Step 2: Audit inventory and navigation**

Confirm exactly eight References, 24 DOT files, 24 SVG files, eight root rows,
all manifest paths, all local links, and all required headings/captions.

- [ ] **Step 3: Run the full focused verification set**

Run the two documentation validators, documentation/paper validator tests,
and the deterministic bridge test files named in Tasks 2–4. Expected: PASS or
an explicitly bounded environment issue that does not invalidate the
documentation contract.

- [ ] **Step 4: Inspect the final diff and worktree**

Run:

```bash
git diff --check origin/main...HEAD
git status -sb
git diff -- .env.example
```

Expected: no whitespace errors; only the user's pre-existing `.env.example`
change remains unstaged.

- [ ] **Step 5: Commit any verification-only corrections**

Stage only task-owned files and use a documentation-scoped commit message.

- [ ] **Step 6: Push the current branch**

```bash
git push origin main
```

Expected: remote `main` advances to the final verified commit and
`.env.example` remains local and unstaged.
