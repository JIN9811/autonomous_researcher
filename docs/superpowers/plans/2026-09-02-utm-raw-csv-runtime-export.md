# UTM Raw CSV Runtime Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save TRAPEZIUM-X Raw CSV files under the Windows PyAutoGUI server package's fixed `artifacts/raw_csv` directory with deterministic runtime filenames, collision prevention, clipboard paste, and separate dry-run/test/live behavior.

**Architecture:** The Windows worker is the single authority for path construction, normalization, collision checks, atomic reservations, clipboard paste, and post-save verification. Linux passes only a structured export context and proxies the worker's dry-run or execution result; the exact Equipment Skill contains a runtime-value paste action rather than a path literal. Agent Manager exposes preview and test controls for the bound Raw CSV block.

**Tech Stack:** Python 3.10+, FastAPI/Pydantic, Windows PyAutoGUI worker, pyperclip, Pillow/OpenCV locator execution, vanilla JavaScript/CSS, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-02-utm-raw-csv-runtime-export-design.md`

## Global Constraints

- Windows output root is exactly `<pyautogui-server-package-root>\artifacts\raw_csv\`; AppData and client-supplied output roots are forbidden.
- Filename format is exactly `{mode}_{session_id}_{specimen_id}_loop-{loop_index:04d}_rep-{repeat_index:04d}.csv`.
- Field separators use one `_`; identifiers normalize internal `_`, whitespace, and invalid Windows characters to `-`.
- `session_id` and `specimen_id` are required; `loop_index` and `repeat_index` are integers greater than or equal to 1.
- Existing files and active reservations block before any GUI click; never overwrite and never auto-increment.
- `dry_run` performs no GUI action, file creation, or reservation.
- `test` and `live` require explicit execution confirmation and use clipboard paste without a `pyautogui.write()` fallback.
- The worker restores the previous clipboard value and never logs it.
- LeRobot training and the main application server must not be restarted; only the Windows worker may be remotely updated/restarted.

---

### Task 1: Windows Raw CSV Path Contract and Atomic Reservation

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Test: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`

**Interfaces:**
- Consumes: worker package root from `ATR_WINDOWS_BRIDGE_PACKAGE_ROOT` or the existing bridge package-root resolver.
- Produces: `_raw_csv_export_plan(payload: dict[str, Any]) -> dict[str, Any]`, `_reserve_raw_csv_export(plan: dict[str, Any]) -> Path`, and `_release_raw_csv_reservation(path: Path | None) -> None`.
- Plan keys: `ok`, `mode`, `session_id`, `specimen_id`, `loop_index`, `repeat_index`, `filename`, `windows_path`, `exists`, `reserved`, `available`, and optional `failure_code`/`message`.

- [ ] **Step 1: Write failing normalization and path tests**

Add tests that load the real worker module and assert:

```python
def test_raw_csv_plan_uses_package_artifacts_root_and_single_underscore_separators(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "BRIDGE_PACKAGE_ROOT", tmp_path / "server")
    plan = module._raw_csv_export_plan({
        "export_context": {
            "mode": "live",
            "session_id": "session_ 20260902-A",
            "specimen_id": "cube_03",
            "loop_index": 2,
            "repeat_index": 4,
        }
    })
    assert plan["ok"] is True
    assert plan["filename"] == "live_session-20260902-A_cube-03_loop-0002_rep-0004.csv"
    assert Path(plan["windows_path"]) == tmp_path / "server" / "artifacts" / "raw_csv" / plan["filename"]
    assert "__" not in plan["filename"]


def test_raw_csv_plan_rejects_invalid_context(module):
    plan = module._raw_csv_export_plan({
        "export_context": {"mode": "live", "session_id": "..", "specimen_id": "", "loop_index": 0, "repeat_index": -1}
    })
    assert plan["ok"] is False
    assert plan["failure_code"] == "UTM_RAW_CSV_CONTEXT_INVALID"
```

- [ ] **Step 2: Run the new contract tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'raw_csv_plan'`

Expected: FAIL because `_raw_csv_export_plan` and `BRIDGE_PACKAGE_ROOT` do not exist.

- [ ] **Step 3: Implement the canonical resolver in the worker source**

Add a package-root-derived `RAW_CSV_ROOT`, NFKC identifier normalization, strict mode/index validation, fixed filename formatting, and root-containment check. Return structured failure payloads rather than raising across the HTTP boundary.

Core behavior:

```python
def _raw_csv_export_plan(payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("export_context") if isinstance(payload.get("export_context"), dict) else {}
    mode = str(context.get("mode") or payload.get("runtime_mode") or "").strip().lower()
    session_id = _normalize_raw_csv_identifier(context.get("session_id"))
    specimen_id = _normalize_raw_csv_identifier(context.get("specimen_id"))
    loop_index = _positive_index(context.get("loop_index"))
    repeat_index = _positive_index(context.get("repeat_index"))
    if mode not in {"dry_run", "test", "live"} or not session_id or not specimen_id or loop_index is None or repeat_index is None:
        return _raw_csv_failure("UTM_RAW_CSV_CONTEXT_INVALID", "Raw CSV export context is incomplete or invalid.")
    filename = f"{mode}_{session_id}_{specimen_id}_loop-{loop_index:04d}_rep-{repeat_index:04d}.csv"
    target = RAW_CSV_ROOT / filename
    # Resolve and verify target remains inside RAW_CSV_ROOT before returning availability.
```

- [ ] **Step 4: Write failing collision and concurrency tests**

```python
def test_raw_csv_plan_blocks_existing_file_before_reservation(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "RAW_CSV_ROOT", tmp_path)
    payload = _valid_export_payload("test")
    first = module._raw_csv_export_plan(payload)
    Path(first["windows_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(first["windows_path"]).write_text("existing", encoding="utf-8")
    blocked = module._raw_csv_export_plan(payload)
    assert blocked["available"] is False
    assert blocked["failure_code"] == "UTM_RAW_CSV_ALREADY_EXISTS"


def test_raw_csv_reservation_is_atomic_and_second_attempt_is_blocked(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "RAW_CSV_ROOT", tmp_path)
    plan = module._raw_csv_export_plan(_valid_export_payload("live"))
    reservation = module._reserve_raw_csv_export(plan)
    with pytest.raises(module.RawCsvExportError) as error:
        module._reserve_raw_csv_export(plan)
    assert error.value.failure_code == "UTM_RAW_CSV_NAME_RESERVED"
    module._release_raw_csv_reservation(reservation)
```

- [ ] **Step 5: Run collision tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'raw_csv_reservation or raw_csv_plan_blocks'`

Expected: FAIL because reservation functions and `RawCsvExportError` do not exist.

- [ ] **Step 6: Implement atomic `.reservations` files and cleanup**

Use `os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)` under `RAW_CSV_ROOT / ".reservations"`. Reservation filenames mirror the CSV filename with `.lock`; write only public execution identity JSON. Existing CSV takes precedence over reservation status. Cleanup accepts `None`, ignores `FileNotFoundError`, and never deletes a CSV.

- [ ] **Step 7: Keep standalone and packaged worker sources identical**

Apply the same production changes to `install/windows_pyautogui_bridge_server.py`. Run:

`cmp Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py`

Expected: exit 0.

- [ ] **Step 8: Run Task 1 tests and commit**

Run: `.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'raw_csv_plan or raw_csv_reservation'`

Expected: PASS.

Commit only Task 1 files:

```bash
git add Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py tests/unit/test_windows_pyautogui_bridge_server_helper.py
git commit -m "feat: add collision-safe UTM raw CSV paths"
```

---

### Task 2: Worker Dry-Run and Clipboard-Based Save Execution

**Files:**
- Modify: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify: `install/windows_pyautogui_bridge_server.py`
- Modify: `Pyautogui_server_for_window/release_manifest.json`
- Test: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`

**Interfaces:**
- Consumes: `_raw_csv_export_plan`, `_reserve_raw_csv_export`, `_release_raw_csv_reservation` from Task 1 and `export_context` in `/execute` payloads.
- Produces: `paste_runtime_value` sequence action with `key="raw_csv_path"`; dry-run result with `status="dry_run_ready"`; test/live result containing `raw_csv_export` plan and artifact metadata.

- [ ] **Step 1: Write failing dry-run tests**

Assert a registered `utm_save_raw_data_*` program with `runtime_mode="dry_run"` returns the plan before loading PyAutoGUI, does not call `_reserve_raw_csv_export`, and does not create `RAW_CSV_ROOT`.

```python
def test_save_raw_csv_dry_run_resolves_without_gui_or_reservation(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "RAW_CSV_ROOT", tmp_path / "raw_csv")
    monkeypatch.setattr(module, "_load_pyautogui", lambda: (_ for _ in ()).throw(AssertionError("GUI touched")))
    result = module._execute(_registered_save_payload(mode="dry_run"))
    assert result["ok"] is True
    assert result["status"] == "dry_run_ready"
    assert result["raw_csv_export"]["available"] is True
    assert not (tmp_path / "raw_csv").exists()
```

- [ ] **Step 2: Run dry-run test and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'save_raw_csv_dry_run'`

Expected: FAIL because `_execute` currently loads PyAutoGUI and dispatches the macro.

- [ ] **Step 3: Implement non-actuating dry-run before desktop loading**

Identify managed save programs with a helper that accepts only `utm_save_raw_data_` program IDs whose program metadata has `managed_by="atr_equipment_skill"`. Resolve the plan and return it for `dry_run`; do not create directories, reserve a name, capture a screenshot, or load PyAutoGUI.

- [ ] **Step 4: Write failing clipboard action and cleanup tests**

Use a fake PyAutoGUI and fake pyperclip object to assert:

```python
def test_paste_runtime_value_preserves_clipboard_and_never_types(module, fake_pyautogui, monkeypatch):
    clipboard = FakeClipboard("operator value")
    monkeypatch.setattr(module, "_load_pyperclip", lambda: clipboard)
    result = module._execute_protocol_sequence(
        fake_pyautogui,
        program_id="utm_save_raw_data_1_0_7_segment_001",
        payload={
            "runtime_values": {"raw_csv_path": r"C:\worker\artifacts\raw_csv\test_s_x_loop-0001_rep-0001.csv"},
            "sequence": [{"action": "paste_runtime_value", "key": "raw_csv_path"}],
        },
        run_id="run",
        specimen_id="specimen",
        trace=[],
        screen_artifacts=[],
    )
    assert result["ok"] is True
    assert fake_pyautogui.hotkeys == [("ctrl", "v")]
    assert fake_pyautogui.writes == []
    assert clipboard.value == "operator value"


def test_clipboard_failure_has_no_write_fallback(module, fake_pyautogui, monkeypatch):
    monkeypatch.setattr(module, "_load_pyperclip", lambda: None)
    result = _run_paste_action(module, fake_pyautogui)
    assert result["failure_code"] == "UTM_RAW_CSV_CLIPBOARD_FAILED"
    assert fake_pyautogui.writes == []
```

Also assert reservation cleanup occurs on locator failure, clipboard failure, Save-dialog cancellation, file timeout, and success.

- [ ] **Step 5: Run clipboard tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'paste_runtime_value or raw_csv_reservation_cleanup'`

Expected: FAIL because `paste_runtime_value`, `_load_pyperclip`, and execution-scoped cleanup are absent.

- [ ] **Step 6: Implement clipboard paste and execution-scoped reservation**

Before the first GUI action for test/live, resolve and reserve the target and add `runtime_values.raw_csv_path` plus `expected_export_path` to a copied payload. Execute the program inside `try/finally` so the reservation is always removed. Add `paste_runtime_value` to the worker action dispatcher; allow only the key `raw_csv_path`, limit the value to 512 characters, preserve/restore clipboard through pyperclip, and report only `pasted runtime value: raw_csv_path` in traces.

- [ ] **Step 7: Verify exact saved file and return export metadata**

Make `wait_for_file` resolve `{raw_csv_path}` from `runtime_values`, require the exact path, wait for 2 seconds of stability, probe the CSV, add it to `ARTIFACT_INDEX`, and return `raw_csv_export`, `windows_path`, SHA-256, size, row count, and columns. A pre-existing target must fail before `SCREENSHOT_BEFORE_START` or any click trace.

- [ ] **Step 8: Update release metadata and mirror the worker**

Increment the worker release version, update hashes in `Pyautogui_server_for_window/release_manifest.json`, synchronize `install/windows_pyautogui_bridge_server.py`, and verify the two worker scripts are byte-identical.

- [ ] **Step 9: Run worker tests and commit**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py
cmp Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py
```

Expected: all tests PASS and `cmp` exits 0.

Commit only Task 2 files:

```bash
git add Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py Pyautogui_server_for_window/release_manifest.json tests/unit/test_windows_pyautogui_bridge_server_helper.py
git commit -m "feat: paste runtime UTM CSV paths safely"
```

---

### Task 3: Linux Bridge and Skill Execution API Modes

**Files:**
- Modify: `device_bridges/windows_pyautogui_bridge.py`
- Modify: `app/main.py`
- Test: `tests/unit/test_equipment_pyautogui_bridge.py`
- Test: `tests/integration/test_equipment_skill_api.py`

**Interfaces:**
- Consumes: worker `/execute` result and `export_context` contract from Tasks 1–2.
- Produces: `EquipmentRawCsvExportContext`, extended `EquipmentSkillTestRequest`, and exact skill test behavior for `dry_run`, `test`, and `live`.

- [ ] **Step 1: Write failing bridge pass-through tests**

Assert `_runtime_program_payload` and `_public_payload` preserve this exact object without accepting an output path:

```python
context = {
    "mode": "test",
    "session_id": "session-20260902-A",
    "specimen_id": "cube-03",
    "loop_index": 2,
    "repeat_index": 4,
}
```

Assert `output_csv_path`, `export_root`, and `filename` supplied by a caller are dropped or rejected for managed Raw CSV programs.

- [ ] **Step 2: Run bridge tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_equipment_pyautogui_bridge.py -k 'raw_csv_export_context'`

Expected: FAIL because managed export context filtering does not exist.

- [ ] **Step 3: Add bridge validation and pass-through**

Validate public context shape before network dispatch, retain only the five approved fields, and return `UTM_RAW_CSV_CONTEXT_INVALID` locally for invalid values. Do not resolve Windows paths on Linux.

- [ ] **Step 4: Write failing API mode tests**

Add integration tests for:

```python
dry = client.post(
    "/api/equipment/skills/utm_save_raw_data/1.0.7/test",
    json={"runtime_mode": "dry_run", "confirm_execute": False, "export_context": valid_context("dry_run")},
)
assert dry.status_code == 200
assert dry.json()["program_results"][0]["status"] == "dry_run_ready"

blocked = client.post(
    "/api/equipment/skills/utm_save_raw_data/1.0.7/test",
    json={"runtime_mode": "test", "confirm_execute": False, "export_context": valid_context("test")},
)
assert blocked.status_code == 422

live_defaults = client.post(
    "/api/equipment/skills/utm_save_raw_data/1.0.7/test",
    json={"runtime_mode": "live", "confirm_execute": True, "export_context": {"mode": "live"}},
)
assert live_defaults.status_code == 422
```

- [ ] **Step 5: Run API tests and verify RED**

Run: `.venv/bin/pytest -q tests/integration/test_equipment_skill_api.py -k 'raw_csv and skill'`

Expected: FAIL because the request model accepts no export context and test mode does not require confirmation.

- [ ] **Step 6: Implement Pydantic models and mode policy**

Define:

```python
class EquipmentRawCsvExportContext(BaseModel):
    mode: Literal["dry_run", "test", "live"]
    session_id: str = Field(..., min_length=1, max_length=96)
    specimen_id: str = Field(..., min_length=1, max_length=96)
    loop_index: int = Field(..., ge=1, le=9999)
    repeat_index: int = Field(..., ge=1, le=9999)


class EquipmentSkillTestRequest(BaseModel):
    runtime_mode: Literal["dry_run", "test", "live"] = "dry_run"
    confirm_execute: bool = False
    export_context: EquipmentRawCsvExportContext | None = None
```

Require confirmation for both test and live, require `export_context` only for `utm_save_raw_data`, require context mode to equal request mode, and pass session/specimen IDs plus the context to the worker. Dry-run still contacts the selected worker for authoritative path calculation but carries no actuation confirmation.

- [ ] **Step 7: Run Task 3 tests and commit**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_equipment_pyautogui_bridge.py -k 'raw_csv_export_context'
.venv/bin/pytest -q tests/integration/test_equipment_skill_api.py -k 'raw_csv or equipment_skill_test'
```

Expected: PASS.

Commit only Task 3 files:

```bash
git add device_bridges/windows_pyautogui_bridge.py app/main.py tests/unit/test_equipment_pyautogui_bridge.py tests/integration/test_equipment_skill_api.py
git commit -m "feat: add UTM CSV execution modes"
```

---

### Task 4: Exact Save Skill Upgrade

**Files:**
- Modify: `utils/equipment_skill_workflow.py`
- Modify: `utils/equipment_utm_skills.py`
- Modify: `tests/unit/test_equipment_skill_workflow.py`
- Modify: `tests/unit/test_equipment_utm_skills.py`

**Interfaces:**
- Consumes: worker action `paste_runtime_value` and runtime key `raw_csv_path` from Task 2.
- Produces: `utm_save_raw_data@1.0.7` workflow with no literal output path and Agent Manager binding to the new deployed version.

- [ ] **Step 1: Write failing workflow validator tests**

Assert `paste_runtime_value` is accepted only with `key="raw_csv_path"`, rejects any embedded `text`, `path`, or unknown key, and contributes no literal secret/path to the program.

- [ ] **Step 2: Run validator tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_equipment_skill_workflow.py -k 'paste_runtime_value'`

Expected: FAIL with `ACTION_UNSUPPORTED`.

- [ ] **Step 3: Add the bounded workflow action**

Add `paste_runtime_value` to editable actions and validate the exact allowed key. Do not add generic clipboard-write or arbitrary paste actions.

- [ ] **Step 4: Write failing exact-skill tests**

Update the expected save sequence to:

```python
[
    "click",
    "wait",
    "hotkey",
    "paste_runtime_value",
    "press",
    "wait_for_file",
    "screenshot",
]
```

Assert the paste action is `{"action": "paste_runtime_value", "key": "raw_csv_path"}`, the file wait pattern is `{raw_csv_path}`, no save action contains `C:/ATR`, `{run_id}`, `{specimen_id}`, `write`, or `type_path`, and only `save_raw_data` advances from `1.0.6` to `1.0.7`.

- [ ] **Step 5: Run exact-skill tests and verify RED**

Run: `.venv/bin/pytest -q tests/unit/test_equipment_utm_skills.py`

Expected: FAIL because the current skill uses `write` and version `1.0.6`.

- [ ] **Step 6: Implement and stage the new exact skill**

Change only the `save_raw_data` binding to `utm_save_raw_data@1.0.7`, replace the literal write action with `paste_runtime_value`, and use an exact `{raw_csv_path}` file wait. Compile and validate into `memory/equipment_skills` without executing it.

- [ ] **Step 7: Run Task 4 tests and commit**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_equipment_skill_workflow.py tests/unit/test_equipment_utm_skills.py
```

Expected: PASS.

Commit only Task 4 source and test files; generated runtime memory remains deployment state and is not included unless already tracked:

```bash
git add utils/equipment_skill_workflow.py utils/equipment_utm_skills.py tests/unit/test_equipment_skill_workflow.py tests/unit/test_equipment_utm_skills.py
git commit -m "feat: parameterize UTM raw CSV skill"
```

---

### Task 5: Agent Manager Raw CSV Preview and Test Panel

**Files:**
- Modify: `web/templates/equipment_agent_manager.html`
- Modify: `web/static/equipment_agent_manager.js`
- Modify: `web/static/equipment_agent_manager.css`
- Modify: `tests/ui/equipment_agent_manager_browser_audit.py`
- Modify: `tests/integration/test_live_gui_runtime_layout.py`

**Interfaces:**
- Consumes: exact skill test API from Task 3 and `utm_save_raw_data` block identity.
- Produces: a Raw CSV runtime panel with mode, session, specimen, loop, repeat, preview, test-save action, collision status, and result metadata.

- [ ] **Step 1: Write failing GUI contract tests**

Assert the page contains stable IDs:

```text
equipment-raw-csv-panel
equipment-raw-csv-mode
equipment-raw-csv-session
equipment-raw-csv-specimen
equipment-raw-csv-loop
equipment-raw-csv-repeat
equipment-raw-csv-preview
equipment-raw-csv-execute
equipment-raw-csv-status
equipment-raw-csv-path
```

Browser audit requirements:

- panel appears only when the canonical flow contains `utm_save_raw_data`;
- preview posts `runtime_mode="dry_run"` with `confirm_execute=false`;
- execute is enabled only in test mode after a successful, available preview;
- any field change invalidates the previous preview;
- collision renders blocked state and disables execute;
- live mode displays current experiment context read-only and cannot use manual overrides.

- [ ] **Step 2: Run GUI tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'equipment_agent_manager and raw_csv'
.venv/bin/python tests/ui/equipment_agent_manager_browser_audit.py --base-url http://127.0.0.1:7860
```

Expected: contract test FAILS because controls do not exist; browser audit reports missing Raw CSV panel.

- [ ] **Step 3: Implement panel rendering and preview**

Render the panel below the workflow summary. Use numeric inputs with min 1/max 9999, HTML escaping for returned paths, and a single request builder shared by preview and execute. Preview displays canonical filename/path and one of `available`, `already_exists`, or `reserved`.

- [ ] **Step 4: Implement confirmed test execution**

Only test mode may use manual values. Require `window.confirm` before posting `runtime_mode="test", confirm_execute=true`. Display SHA-256, Linux artifact path, row count, columns, and screenshot evidence. Do not expose a live execute button in this panel; live execution remains owned by the agentic runtime.

- [ ] **Step 5: Run Task 5 tests and commit**

Run:

```bash
.venv/bin/pytest -q tests/integration/test_live_gui_runtime_layout.py -k 'equipment_agent_manager'
.venv/bin/python tests/ui/equipment_agent_manager_browser_audit.py --base-url http://127.0.0.1:7860
```

Expected: PASS.

Commit only Task 5 files:

```bash
git add web/templates/equipment_agent_manager.html web/static/equipment_agent_manager.js web/static/equipment_agent_manager.css tests/ui/equipment_agent_manager_browser_audit.py tests/integration/test_live_gui_runtime_layout.py
git commit -m "feat: add UTM CSV runtime controls"
```

---

### Task 6: Worker Deployment, Skill Binding, and Controlled Acceptance

**Files:**
- Runtime state: `memory/equipment_skills/utm_save_raw_data/1.0.7/`
- Runtime state: `graphs/modules/equipment/equipment_skill_flows.json`
- Evidence: `artifacts/equipment/`

**Interfaces:**
- Consumes: completed Tasks 1–5.
- Produces: updated Windows worker, exact deployed save skill, Agent Manager binding, deleted old version, dry-run evidence, and one confirmed test CSV artifact.

- [ ] **Step 1: Run the full relevant automated suite**

```bash
.venv/bin/pytest -q \
  tests/unit/test_windows_pyautogui_bridge_server_helper.py \
  tests/unit/test_equipment_pyautogui_bridge.py \
  tests/unit/test_equipment_skill_workflow.py \
  tests/unit/test_equipment_utm_skills.py \
  tests/integration/test_equipment_skill_api.py \
  tests/integration/test_live_gui_runtime_layout.py
git diff --check
```

Expected: all tests PASS and diff check is clean.

- [ ] **Step 2: Remotely update only the Windows worker**

Use the existing worker self-update endpoint/package flow. Verify worker health reports the new release version and keep the main server and LeRobot training PIDs unchanged.

- [ ] **Step 3: Deploy and bind `utm_save_raw_data@1.0.7`**

Stage the exact package, deploy it to `windows_192.168.50.201`, verify the worker program SHA-256 and `integrity_ok=true`, atomically bind the Agent Manager `save_raw_data` block to `1.0.7`, then disable and delete `1.0.6` locally and from the worker.

- [ ] **Step 4: Run dry-run acceptance**

Use a unique test context such as:

```json
{
  "mode": "dry_run",
  "session_id": "agent-dryrun-20260902",
  "specimen_id": "specimen-preview",
  "loop_index": 1,
  "repeat_index": 1
}
```

Verify no `/execute` GUI step trace, no reservation, and no CSV creation. Confirm the preview path is inside the worker package `artifacts/raw_csv` and contains no `__`.

- [ ] **Step 5: Run one confirmed test-save acceptance with the operator**

Capture the completed TRAPEZIUM-X screen first. Use a new test context, preview it, confirm `available=true`, then execute only `utm_save_raw_data@1.0.7` in test mode. Verify the Raw CSV button click, clipboard paste, exact file creation, stable-file check, CSV probe, screenshot, and Linux pull. Re-run the same preview and verify it blocks with `UTM_RAW_CSV_ALREADY_EXISTS` before any click.

- [ ] **Step 6: Final verification and handoff**

Verify Agent Manager readiness is true, the new worker program exists with exact hash, the old program is absent, the test CSV is recoverable from both Windows and Linux paths, no manual `Save` fallback occurred, and LeRobot/main-server processes were untouched. Record the exact test filename, paths, hash, rows, columns, and screenshots in the handoff.
