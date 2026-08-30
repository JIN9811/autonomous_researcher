# Equipment Skill Full-Screen Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve a complete 2 FPS Windows desktop recording, convert it into timestamped temporal storyboards for full-flow multimodal LLM interpretation, and verify GUI-driven Skill creation, deployment, and execution.

**Architecture:** The Windows worker writes periodic and event frames directly to a versioned recording directory with an append-only timeline and manifest. Linux verifies imported source evidence, generates deterministic 4x4 storyboards, analyzes every chunk through the selected multimodal backend, and synthesizes one traceable Skill annotation. Existing deterministic Skill deployment and execution routes remain unchanged.

**Tech Stack:** Python 3.10+, Pillow, FastAPI, pytest, vanilla JavaScript, Windows PowerShell packaging, existing ATR LLM backend abstraction.

**Spec:** `docs/superpowers/specs/2026-08-30-equipment-skill-fullscreen-timeline-design.md`

## Global Constraints

- Periodic full-screen capture is fixed at 2 FPS for the complete recording session.
- Periodic source frames are JPEG; event and boundary source frames are PNG.
- Source evidence is never replaced by preview or LLM derivatives.
- No arbitrary frame-count, duration, or package-byte limit may silently discard completed recording evidence.
- RAM retains only the active encode buffer and a small pre-action cache.
- Every storyboard tile maps to an immutable source frame and SHA-256.
- The selected shared multimodal backend analyzes all chronological chunks; unavailable visual capability fails explicitly.
- Normal deployed Skill execution remains deterministic and does not call the LLM.
- Canonical Windows server and `install/` mirror remain byte-identical.
- No physical actuation occurs until the desktop-only full path passes.

---

### Task 1: Disk-Backed 2 FPS Recording Timeline

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Test: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`

**Interfaces:**
- Consumes: `RecordingManager.start()`, `RecordingFrameBuffer.start()`, screenshot provider, mask policy, and recording directory.
- Produces: append-only `timeline.jsonl`, `frames/periodic/*.jpg`, event/boundary PNG files, and status fields `periodic_frame_count`, `timeline_path`, `writer_status`, and `capture_fps`.

- [x] **Step 1: Write failing full-session persistence tests**

Capture more frames than the current rolling capacity and assert every frame remains on disk, `capture_fps == 2.0`, and in-memory frame state remains bounded.

- [x] **Step 2: Run focused tests and verify RED**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'full_session or disk_timeline or capture_fps'`

Expected: FAIL because the current buffer evicts unpinned periodic frames and has no append-only timeline.

- [x] **Step 3: Implement immediate periodic persistence**

Assign monotonic frame IDs, encode periodic frames as JPEG, write atomically, append one JSONL row, and retain only recent pre-action frames in memory.

- [x] **Step 4: Add disk-health tests and implementation**

Test warning state, critical stop, incomplete package finalization, and write failure. Preserve partial evidence without automatic deletion.

- [x] **Step 5: Verify GREEN and mirror parity**

Run:

```bash
pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'recording or timeline or overlay'
cmp -s Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py
```

### Task 2: Event and Boundary Evidence Linkage

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Test: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`

**Interfaces:**
- Consumes: periodic timeline entries and existing mouse/keyboard/window/checkpoint/exception events.
- Produces: event records with `pre_frame_id`, `event_frame_id`, `post_frame_id`, and source hashes; clean recording start/stop boundaries.

- [x] **Step 1: Write failing pre/event/post linkage tests**

Assert each actionable event resolves to a clean pre-action frame, exact event PNG, deferred post-action PNG, and chronological timeline references.

- [x] **Step 2: Verify RED**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'event_linkage or boundary_frame'`

- [x] **Step 3: Implement event linkage and clean stop boundary**

Use the recent-frame cache for pre-action evidence, persist event/post-action PNG files, hide the overlay before stop capture, and finalize links before package completion.

- [x] **Step 4: Verify GREEN**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'event or exception or final_state or overlay'`

### Task 3: Recording Package and Paginated Preview

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `device_bridges/windows_pyautogui_bridge.py`
- Test: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Test: `tests/unit/test_equipment_pyautogui_bridge.py`

**Interfaces:**
- Consumes: finalized timeline and source files.
- Produces: complete hashed package manifest and preview API fields `cursor`, `limit`, and `next_cursor`.

- [x] **Step 1: Write failing package and preview pagination tests**

Assert every source file appears in the authenticated package, hash/path mismatches fail, and preview returns only the requested page without Windows absolute paths.

- [x] **Step 2: Verify RED**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py tests/unit/test_equipment_pyautogui_bridge.py -k 'package or preview'`

- [x] **Step 3: Implement complete manifest and on-demand preview**

Remove package evidence truncation, transfer the verified inventory, and retain bounded response size only for browser preview pages.

- [x] **Step 4: Verify GREEN**

Run: `pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py tests/unit/test_equipment_pyautogui_bridge.py -k 'package or preview or recording'`

### Task 4: Temporal Storyboard Builder

**Files:**
- Modify: `utils/equipment_skill_vision.py`
- Test: `tests/unit/test_equipment_skill_vision.py`

**Interfaces:**
- Consumes: imported `timeline.jsonl`, verified source roots, event metadata, and source hashes.
- Produces: `TemporalStoryboardBundle` with ordered chunk storyboards, overview storyboards, tile mappings, and complete source-frame coverage.

- [x] **Step 1: Write failing storyboard tests**

Test deterministic 16-frame 4x4 composition, eight-second chunks at 2 FPS, labels, boundary event references, tile mapping, overview pagination, and zero omitted source IDs.

- [x] **Step 2: Verify RED**

Run: `pytest -q tests/unit/test_equipment_skill_vision.py -k 'storyboard or timeline_chunk'`

- [x] **Step 3: Implement `build_temporal_storyboards()`**

Generate readable labels outside protected ROI areas, deterministic evidence-role colors, chronological arrows, derivative hashes, and JSON mappings without modifying source files.

- [x] **Step 4: Verify GREEN**

Run: `pytest -q tests/unit/test_equipment_skill_vision.py -k 'storyboard or timeline or evidence'`

### Task 5: Hierarchical Multimodal Annotation

**Files:**
- Modify: `utils/equipment_skill_vision.py`
- Modify: `app/main.py`
- Modify: `utils/equipment_skill_authoring_jobs.py`
- Test: `tests/unit/test_llm_multimodal.py`
- Test: `tests/unit/test_equipment_skill_vision.py`
- Test: `tests/integration/test_equipment_skill_api.py`

**Interfaces:**
- Consumes: `TemporalStoryboardBundle`, selected shared LLM backend, and authoring stop boundaries.
- Produces: persisted chunk annotations, final workflow summary, ordered step transitions, source references, locator proposals, model provenance, and granular job progress.

- [x] **Step 1: Write failing every-chunk analysis tests**

Use a three-chunk recording. Assert one model request per chunk, one synthesis request, ordered source references, restart-safe chunk artifacts, explicit capability failure, and no hidden fallback.

- [x] **Step 2: Verify RED**

Run: `pytest -q tests/unit/test_llm_multimodal.py tests/unit/test_equipment_skill_vision.py tests/integration/test_equipment_skill_api.py -k 'chunk or storyboard or multimodal or authoring'`

- [x] **Step 3: Implement chunk analysis and synthesis**

Replace fixed `max_images=16` collection with storyboards, sequential chunk requests, persisted chunk outputs, and final synthesis from ordered chunk analyses. Overview storyboards remain GUI/audit artifacts; already analyzed state images are not resent, while required action-locator images remain available. Backend request limits remain local and cannot drop chunks.

- [x] **Step 4: Add progress and cooperative-stop stages**

Expose `ANALYZING_TIMELINE`, `SYNTHESIZING`, and per-chunk progress. Stop only at safe chunk or compilation boundaries and preserve completed chunks.

- [x] **Step 5: Verify GREEN**

Run: `pytest -q tests/unit/test_llm_multimodal.py tests/unit/test_equipment_skill_vision.py tests/integration/test_equipment_skill_api.py -k 'chunk or storyboard or multimodal or authoring or annotate'`

### Task 6: GUI Progress and Storyboard Preview

**Files:**
- Modify: `web/templates/windows_equipment.html`
- Modify: `web/static/windows_equipment.js`
- Modify: `web/static/styles.css`
- Test: `tests/js/windows_equipment_selection.test.js`
- Test: `tests/ui/windows_equipment_browser_audit.py`

**Interfaces:**
- Consumes: existing recording preview and authoring job APIs.
- Produces: paginated recording/storyboard preview and ordered authoring progress without loading every image into browser memory.

- [x] **Step 1: Write failing frontend contract tests**

Assert paginated preview requests, timeline-analysis stages, available Stop control, and inspectable completed storyboards.

- [x] **Step 2: Verify RED**

Run: `node --test tests/js/windows_equipment_selection.test.js && pytest -q tests/ui/windows_equipment_browser_audit.py`

- [x] **Step 3: Implement minimal GUI changes**

Reuse the existing layout and controls. Add no duplicate recording, deployment, or execution path.

- [x] **Step 4: Verify GREEN and inspect at 1920x1080**

Run JS/UI tests and browser audit for clipping, duplicate controls, and unbounded image loading.

### Task 7: Packaging, Documentation, and Public-Path Acceptance

**Files:**
- Modify: `Pyautogui_server_for_window/release_manifest.json`
- Modify: `Pyautogui_server_for_window/docs/USAGE.md`
- Modify: `docs/device_bridges/windows_pyautogui_bridge.md`
- Modify: `REQUIREMENTS.md` only if a new dependency is introduced
- Test: `tests/unit/test_install_packaging.py`
- Test: `tests/unit/test_windows_bridge_release.py`

**Interfaces:**
- Consumes: completed recorder, package, storyboard, authoring, deployment, and GUI behavior.
- Produces: validated portable Windows release and acceptance artifacts.

- [x] **Step 1: Update release parity tests and verify RED for stale manifest**

Run: `pytest -q tests/unit/test_install_packaging.py tests/unit/test_windows_bridge_release.py`

- [x] **Step 2: Update mirror, release manifest, and documentation**

Document storage, 2 FPS capture, capacity warnings, storyboard analysis, GUI workflow, and recovery.

- [x] **Step 3: Run complete automated verification**

```bash
python -m py_compile Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py utils/equipment_skill_vision.py app/main.py
pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py tests/unit/test_equipment_pyautogui_bridge.py tests/unit/test_equipment_skill_vision.py tests/unit/test_llm_multimodal.py tests/integration/test_equipment_skill_api.py tests/unit/test_install_packaging.py tests/unit/test_windows_bridge_release.py
node --test tests/js/windows_equipment_selection.test.js
git diff --check
```

- [x] **Step 4: Build and validate portable release**

Build with `Pyautogui_server_for_window/scripts/build_portable_release.py`, compare canonical/install/release hashes, and inspect archive inventory.

- [x] **Step 5: Execute the GUI full path**

Use a desktop-only Skill first: record for more than 30 seconds, stop from the overlay, inspect source frames and storyboards, import through Lab Equipment Workspace, annotate with the selected backend, compile, validate, deploy, and execute from the GUI. Confirm audit logs, artifacts, process cleanup, and stable memory. Only after that passes may an explicitly approved physical-equipment Skill execute.
