# Advanced Visual Work Queue Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, record, compile, and replay a deterministic multi-window Equipment Skill that selects a specimen by identity, drags it into a work queue, performs one bounded visual recovery, and exports matching JSON/CSV evidence without executable coordinate fallback.

**Architecture:** A standalone Tk demo supplies the work queue, input browser, configuration dialog, and export dialog while persisting state for assertions. A reproducible E2E runner launches the exact packaged Windows bridge binary on an isolated X11 display, records the operator workflow, compiles it through `EquipmentSkillRegistry`, and replays it after window positions and row order change. Existing ATR runtime and bridge files are modified only if the new regression tests expose a real contract defect.

**Tech Stack:** Python 3.12, Tkinter, PyAutoGUI, pynput, Pillow, OpenCV, Xvfb, stdlib HTTP/JSON/CSV, pytest, existing `atr.equipment_recording.v2`, `atr.equipment_skill.v1`, and `atr.pyautogui_program.v1` contracts.

## Global Constraints

- Do not alter or restart the existing ATR main server or active model processes.
- Use the exact packaged Windows bridge implementation for recording and replay verification.
- Keep `coordinate_fallback=false`; recorded coordinates are audit metadata only.
- Do not add shell execution, arbitrary Python execution, password entry, or process termination to a Skill.
- Preserve source/install Windows bridge byte equality.
- Do not modify existing validated Skill packages.
- Do not commit before user review.
- Persist generated runtime data only under `runs/equipment_skill_advanced_queue_e2e/` and `memory/equipment_skills/advanced_visual_work_queue_demo/1.0.0/`.

---

## File Structure

- Create `Pyautogui_server_for_window/demo/advanced_visual_work_queue.py`: deterministic multi-window target application and atomic state/export writer.
- Create `scripts/advanced_visual_work_queue_e2e.py`: isolated bridge/app orchestration, real recording, Skill compilation, shifted replay, artifact validation, and fail-closed replay.
- Create `tests/unit/test_advanced_visual_work_queue_demo.py`: pure demo-state and export contract tests.
- Create `tests/unit/test_advanced_visual_work_queue_e2e.py`: compiled-program and artifact-verifier tests without opening physical UI.
- Modify `utils/equipment_skill_runtime.py`: discard ambient coordinate-only mouse movement when compiling an image-first recording.
- Modify `tests/unit/test_equipment_skill_runtime.py`: lock coordinate-free image-first compilation, including drag source and target.
- Modify `tests/unit/test_windows_pyautogui_bridge_server_helper.py`: lock global-best repeated-target and image-only drag behavior for both bridge copies.
- Modify `tests/unit/test_windows_pyautogui_demo_assets.py`: ensure the packaged advanced demo is present and import-safe.
- Modify `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py` only if the focused tests identify a bridge defect.
- Mirror that bridge byte-for-byte to `install/windows_pyautogui_bridge_server.py` only when the source bridge changes.
- Modify `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`: explain the advanced Skill and bounded recovery behavior.
- Modify `docs/hardware/windows_pyautogui_bridge_windows_setup.md`: add exact local reproduction commands and prerequisites.

---

### Task 1: Deterministic Multi-Window Work Queue

**Files:**
- Create: `Pyautogui_server_for_window/demo/advanced_visual_work_queue.py`
- Create: `tests/unit/test_advanced_visual_work_queue_demo.py`
- Modify: `tests/unit/test_windows_pyautogui_demo_assets.py`

**Interfaces:**
- Produces: `normalize_mode(raw: str) -> str`.
- Produces: `analysis_result(specimen_id: str, method: str, evidence: bool, load_limit: str) -> dict[str, object]`.
- Produces: `write_exports(output_root: Path, base_name: str, result: dict[str, object]) -> dict[str, str]`.
- Persists: `status.json` with `state`, `mode`, `selected_batch`, `selected_specimen`, `queue`, `configuration`, `analysis_attempts`, `recovery_count`, `result`, and `exports`.
- Consumes modes: `initial`, `shifted`, `reordered`, `shifted_reordered`, and `missing_target` from `mode.txt`.

- [ ] **Step 1: Write failing pure contract tests**

```python
def test_analysis_result_normalizes_exact_business_values():
    result = module.analysis_result("specimen-beta", "Compression", True, "12.5")
    assert result == {
        "specimen_id": "specimen-beta",
        "method": "Compression",
        "evidence_enabled": True,
        "load_limit": 12.5,
    }


def test_write_exports_emits_matching_json_and_csv(tmp_path):
    result = module.analysis_result("specimen-beta", "Compression", True, "12.5")
    paths = module.write_exports(tmp_path, "advanced_queue_result", result)
    assert json.loads(Path(paths["json"]).read_text()) == result
    assert list(csv.DictReader(Path(paths["csv"]).open())) == [{
        "specimen_id": "specimen-beta",
        "method": "Compression",
        "evidence_enabled": "true",
        "load_limit": "12.5",
    }]
```

- [ ] **Step 2: Run the tests and verify the missing module fails**

Run: `pytest -q tests/unit/test_advanced_visual_work_queue_demo.py`

Expected: collection fails because `advanced_visual_work_queue.py` does not exist.

- [ ] **Step 3: Implement pure state and artifact functions**

```python
def analysis_result(specimen_id: str, method: str, evidence: bool, load_limit: str) -> dict[str, object]:
    return {
        "specimen_id": specimen_id.strip(),
        "method": method.strip(),
        "evidence_enabled": bool(evidence),
        "load_limit": float(load_limit),
    }


def write_exports(output_root: Path, base_name: str, result: dict[str, object]) -> dict[str, str]:
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", base_name.strip()).strip("_")
    if not safe_name:
        raise ValueError("output name is required")
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / f"{safe_name}.json"
    csv_path = output_root / f"{safe_name}.csv"
    atomic_write_text(json_path, json.dumps(result, indent=2) + "\n")
    with tempfile.NamedTemporaryFile("w", newline="", delete=False, dir=output_root, encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result))
        writer.writeheader()
        writer.writerow({**result, "evidence_enabled": str(result["evidence_enabled"]).lower()})
        temporary = Path(handle.name)
    temporary.replace(csv_path)
    return {"json": str(json_path), "csv": str(csv_path)}
```

- [ ] **Step 4: Implement the deterministic Tk surfaces**

The main window must display a source table, an analysis queue drop lane, progress, result summary, and buttons that open the three independent dialogs. The source rows are `specimen-alpha`, `specimen-beta`, and `specimen-gamma`; `reordered` mode reverses them and `missing_target` omits `specimen-beta`. Drag release inside the queue lane moves only the selected source identity into the queue.

The first evidence-checkbox click must be intentionally ignored once per reset and recorded in `status.json` as `injected_missed_evidence=true`. The first Start action must therefore show a visible `EVIDENCE REQUIRED` validation banner. Reopening configuration, checking evidence again, saving, and starting a second time must set `recovery_count=1` and finish analysis. A third Start attempt must be rejected as `WORKFLOW_VALIDATION_FAILED`.

- [ ] **Step 5: Add packaged-demo source checks**

```python
def test_advanced_work_queue_demo_exposes_required_surfaces():
    source = DEMO_PATH.read_text(encoding="utf-8")
    for label in (
        "INPUT BROWSER", "specimen-beta", "ANALYSIS QUEUE", "Compression",
        "EVIDENCE REQUIRED", "advanced_queue_result", "JSON", "CSV",
    ):
        assert label in source
```

- [ ] **Step 6: Run focused tests**

Run: `pytest -q tests/unit/test_advanced_visual_work_queue_demo.py tests/unit/test_windows_pyautogui_demo_assets.py`

Expected: all tests pass without opening a display.

---

### Task 2: Image-Only Recording And Drag Compilation Locks

**Files:**
- Modify: `utils/equipment_skill_runtime.py`
- Modify: `tests/unit/test_equipment_skill_runtime.py`
- Modify: `tests/unit/test_windows_pyautogui_bridge_server_helper.py`
- Modify if required by a failing test: `Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py`
- Modify if the source bridge changes: `install/windows_pyautogui_bridge_server.py`

**Interfaces:**
- Consumes: `compile_recording_actions(events, visual_locator_policy=...)`.
- Consumes: bridge `_locate_on_screen(pyautogui_module, action, run_id, specimen_id)`.
- Produces invariant: ambient recorded `mouse_move` events are omitted in image-first mode; semantic `click`, drag-source `move_to`, and `drag_to` actions contain `image_candidates` and no executable `x`/`y` fields.

- [ ] **Step 1: Add a failing repeated-row and drag regression test**

```python
def test_advanced_queue_drag_uses_global_best_source_and_target(tmp_path, monkeypatch):
    source_candidate = candidate_for_text("specimen-beta")
    target_candidate = candidate_for_text("ANALYSIS QUEUE")
    screen = repeated_row_screen(
        rows=["specimen-gamma", "specimen-beta", "specimen-alpha"],
        queue_offset=(620, 310),
    )
    source = module._locate_on_screen(fake_for(screen), {"image_candidates": [source_candidate]}, run_id="advanced", specimen_id="specimen-beta")
    target = module._locate_on_screen(fake_for(screen), {"image_candidates": [target_candidate]}, run_id="advanced", specimen_id="specimen-beta")
    assert source == expected_beta_box
    assert target == expected_queue_box
```

- [ ] **Step 2: Add compiler assertions for both drag endpoints**

```python
actions = compile_recording_actions(
    [recorded_drag_with_inline_source_and_target()],
    visual_locator_policy={
        "mode": "image_first",
        "required_for_pointer_actions": True,
        "coordinate_fallback": False,
    },
)
assert [item["action"] for item in actions] == ["move_to", "drag_to"]
assert all("image_candidates" in item for item in actions)
assert all("x" not in item and "y" not in item for item in actions)
assert all(item.get("coordinate_fallback") is not True for item in actions)
```

Also add a recording containing ambient `mouse_move` events before a visual click and require the compiled output to contain only the visual click. Legacy v1 coordinate compilation must retain its existing timed `move_to` behavior.

- [ ] **Step 3: Run the focused bridge/compiler tests**

Run: `pytest -q tests/unit/test_equipment_skill_runtime.py -k 'image_first or drag' tests/unit/test_windows_pyautogui_bridge_server_helper.py -k 'inline_locator or image_resolved or required_recorded'`

Expected: the new ambient-move test fails before the compiler change; existing bridge matching tests continue to pass.

- [ ] **Step 4: Omit ambient mouse movement only for image-first compilation**

```python
if kind == "mouse_move" and image_first:
    previous_mouse_at_ms = max(previous_mouse_at_ms, int(event.get("at_ms", previous_mouse_at_ms)))
    continue
```

Place this branch before legacy `mouse_move` compilation. Do not change legacy coordinate recordings, semantic clicks, or image-resolved drag source/target generation.

- [ ] **Step 5: If and only if the repeated-target test fails, apply the minimal bridge fix**

The permitted implementation is limited to selecting the highest normalized OpenCV score across the complete screenshot for an inline candidate and returning its bounding box. It must not add coordinate fallback or alter external-file locator behavior.

```python
score, location = cv2.minMaxLoc(cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED))[1::2]
if score >= confidence:
    return (int(location[0]), int(location[1]), template_width, template_height)
return None
```

- [ ] **Step 6: Preserve source/install parity**

Run: `cmp -s Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py install/windows_pyautogui_bridge_server.py`

Expected: exit code `0`. If the source changed, copy it to `install/` before rerunning this check.

---

### Task 3: Reproducible E2E Runner And Artifact Verifier

**Files:**
- Create: `scripts/advanced_visual_work_queue_e2e.py`
- Create: `tests/unit/test_advanced_visual_work_queue_e2e.py`

**Interfaces:**
- Produces: `assert_image_only_programs(programs: list[dict[str, object]]) -> None`.
- Produces: `validate_exported_artifacts(json_path: Path, csv_path: Path, expected: dict[str, object]) -> dict[str, object]`.
- Produces: `run_scenario(*, run_root: Path, display: str, bridge_port: int) -> dict[str, object]`.
- Writes: `runs/equipment_skill_advanced_queue_e2e/e2e_summary.json`.

- [ ] **Step 1: Write failing verifier tests**

```python
def test_assert_image_only_program_rejects_executable_coordinates():
    with pytest.raises(AssertionError, match="executable coordinate"):
        assert_image_only_programs([{"sequence": [{"action": "click", "x": 10, "y": 20}]}])


def test_validate_exported_artifacts_requires_json_csv_identity(tmp_path):
    expected = {"specimen_id": "specimen-beta", "method": "Compression", "evidence_enabled": True, "load_limit": 12.5}
    write_test_outputs(tmp_path, expected)
    summary = validate_exported_artifacts(tmp_path / "advanced_queue_result.json", tmp_path / "advanced_queue_result.csv", expected)
    assert summary["ok"] is True
    assert summary["csv_rows"] == 1
```

- [ ] **Step 2: Run tests and verify missing functions fail**

Run: `pytest -q tests/unit/test_advanced_visual_work_queue_e2e.py`

Expected: import or attribute failure for the new runner helpers.

- [ ] **Step 3: Implement strict compiled-program validation**

```python
POINTER_ACTIONS = {"move_to", "click", "drag_to"}


def assert_image_only_programs(programs: list[dict[str, object]]) -> None:
    sequence = [item for program in programs for item in list(program.get("sequence") or [])]
    drag_actions = [item for item in sequence if item.get("action") == "drag_to"]
    if len(drag_actions) != 1:
        raise AssertionError("exactly one visual drag is required")
    for index, action in enumerate(sequence, start=1):
        if action.get("action") not in POINTER_ACTIONS:
            continue
        if "x" in action or "y" in action or action.get("coordinate_fallback") is True:
            raise AssertionError(f"executable coordinate at action {index}")
        if not action.get("image_candidates"):
            raise AssertionError(f"missing image candidates at action {index}")
```

- [ ] **Step 4: Implement exact JSON/CSV and PNG validation**

The verifier must parse both output formats, normalize only CSV scalar types, require one CSV data row, and compare every business field to the same expected object. PNG verification must check the eight-byte PNG signature and nonzero dimensions through Pillow.

- [ ] **Step 5: Implement isolated process orchestration**

The runner must use a dedicated display and port, refuse port `7860`, and launch only these known commands:

```python
Xvfb(display, "-screen", "0", "1920x1080x24")
python(Pyautogui_server_for_window / "bridge" / "windows_pyautogui_bridge_server.py")
python(Pyautogui_server_for_window / "demo" / "advanced_visual_work_queue.py")
```

It must wait for bridge health and demo `status.json`, execute compiled segments in `workflow.program_ids` order, terminate only child PIDs it created, and leave all ATR/vLLM processes untouched.

- [ ] **Step 6: Run the pure runner tests**

Run: `pytest -q tests/unit/test_advanced_visual_work_queue_e2e.py`

Expected: all tests pass without starting Xvfb.

---

### Task 4: Real Recording, Skill Package, And Bounded Recovery

**Files:**
- Modify: `scripts/advanced_visual_work_queue_e2e.py`
- Generate at runtime: `memory/equipment_skills/advanced_visual_work_queue_demo/1.0.0/*`
- Generate at runtime: `runs/equipment_skill_advanced_queue_e2e/recordings/*`

**Interfaces:**
- Consumes bridge routes: `/recordings/start`, `/recordings/checkpoint`, `/recordings/stop`, and `/execute`.
- Consumes: `EquipmentSkillRegistry.create_draft(...)`, `.compile(...)`, and `.validate(...)`.
- Produces manifest `last_test` entries for shifted/reordered success and missing-target fail-closed verification.

- [ ] **Step 1: Record the complete operator sequence through the real bridge**

The PyAutoGUI driver must perform this visible sequence while the recorder is active:

```text
Open Input Browser -> choose validated batch -> select specimen-beta ->
drag specimen-beta to ANALYSIS QUEUE -> open configuration ->
select Compression -> attempt evidence checkbox -> enter 12.5 -> save ->
start analysis -> observe EVIDENCE REQUIRED -> capture recovery evidence ->
reopen configuration -> enable evidence -> save -> retry once ->
wait for COMPLETED -> open export -> choose JSON and CSV ->
enter advanced_queue_result -> save
```

- [ ] **Step 2: Compile and validate the Skill package**

```python
package_dir = registry.root / "advanced_visual_work_queue_demo" / "1.0.0"
if package_dir.exists():
    compiled = registry.get("advanced_visual_work_queue_demo", "1.0.0")
    if compiled["manifest"]["lifecycle"] not in {"validated", "deployed"}:
        raise RuntimeError("existing advanced Skill version is not validated")
    validated = {"ok": True, "status": compiled["manifest"]["lifecycle"], "package": compiled}
else:
    registry.create_draft(
        recording=recording,
        skill_id="advanced_visual_work_queue_demo",
        version="1.0.0",
        target_profile="advanced_visual_work_queue",
        model_snapshot={"provider": "deterministic", "model": "operator_recording", "reasoning": "not_required"},
    )
    compiled = registry.compile("advanced_visual_work_queue_demo", "1.0.0")
    validated = registry.validate("advanced_visual_work_queue_demo", "1.0.0")
assert validated["ok"] is True
assert_image_only_programs(compiled["programs"])
```

For a rerun after validation, `--reuse-skill` must reuse the exact package and skip lifecycle-mutating `compile()`/`validate()` calls. A new recording requires an explicit new version argument. Never delete or overwrite an existing package automatically.

- [ ] **Step 3: Assert bounded recovery semantics before replay**

Read `status.json` after recording and require:

```python
assert status["analysis_attempts"] == 2
assert status["recovery_count"] == 1
assert status["state"] == "exported"
```

No third retry is permitted, and no recovery action may contain executable coordinates.

- [ ] **Step 4: Reset into shifted and reordered replay mode**

Write `shifted_reordered` to `mode.txt`, wait for `state=waiting`, then register each compiled program and execute every program ID through the isolated bridge `/execute` route in `workflow.program_ids` order. Do not call application methods directly during replay.

- [ ] **Step 5: Validate successful replay evidence**

Require the GUI to reach `state=exported`, validate both output files against:

```python
EXPECTED = {
    "specimen_id": "specimen-beta",
    "method": "Compression",
    "evidence_enabled": True,
    "load_limit": 12.5,
}
```

Save valid PNG evidence before replay, after completion, and after export.

- [ ] **Step 6: Run the actual success scenario**

Run: `python scripts/advanced_visual_work_queue_e2e.py --scenario shifted-reordered --display :99 --bridge-port 8878`

Expected: exit code `0`; summary reports `recorded=true`, `compiled=true`, `validated=true`, `recovery_count=1`, `shifted_reordered.ok=true`, and matching JSON/CSV outputs.

---

### Task 5: Missing-Target Fail-Closed Replay

**Files:**
- Modify: `scripts/advanced_visual_work_queue_e2e.py`
- Generate at runtime: `runs/equipment_skill_advanced_queue_e2e/evidence/missing_target/*`

**Interfaces:**
- Consumes the exact Skill package generated in Task 4.
- Produces failure code `UI_LOCATOR_NOT_FOUND` and screenshot evidence.

- [ ] **Step 1: Add a missing-target runner test double**

```python
def test_failure_summary_requires_locator_failure_and_no_exports():
    result = validate_missing_target_result(
        {"ok": False, "failure_code": "UI_LOCATOR_NOT_FOUND", "trace": [{"step": "SEQ_4_CLICK", "status": "blocked"}]},
        export_paths=[],
    )
    assert result["blocked_as_expected"] is True
```

- [ ] **Step 2: Run the unit test and verify it fails before implementation**

Run: `pytest -q tests/unit/test_advanced_visual_work_queue_e2e.py -k missing_target`

Expected: failure because `validate_missing_target_result` is absent.

- [ ] **Step 3: Implement strict missing-target validation**

The validator must require `ok=false`, `failure_code=UI_LOCATOR_NOT_FOUND`, at least one blocked trace step, at least one valid PNG failure artifact, and zero newly created JSON/CSV exports.

- [ ] **Step 4: Replay with the source identity removed**

Write `missing_target` to `mode.txt`, wait for reset, execute the same compiled program, and assert the bridge blocks before queue mutation. Verify `status.json` still has an empty queue and `analysis_attempts=0`.

- [ ] **Step 5: Run the actual fail-closed scenario**

Run: `python scripts/advanced_visual_work_queue_e2e.py --scenario missing-target --reuse-skill --display :99 --bridge-port 8878`

Expected: script exits `0` because the expected safe block was observed; `e2e_summary.json` records `missing_target.blocked_as_expected=true`.

---

### Task 6: Documentation And Reproduction Guide

**Files:**
- Modify: `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`
- Modify: `docs/hardware/windows_pyautogui_bridge_windows_setup.md`

**Interfaces:**
- Documents the exact Skill ID, storage paths, command lines, expected outputs, recovery limit, and stable failure codes.

- [ ] **Step 1: Document the operator workflow and safety boundary**

Add a section stating that normal replay is deterministic, no LLM is required, all pointer targets use embedded image locators, recorded coordinates are non-executing metadata, and validation recovery is limited to one recorded retry.

- [ ] **Step 2: Document exact reproduction commands**

```bash
pytest -q tests/unit/test_advanced_visual_work_queue_demo.py \
  tests/unit/test_advanced_visual_work_queue_e2e.py

python scripts/advanced_visual_work_queue_e2e.py \
  --scenario all --display :99 --bridge-port 8878
```

- [ ] **Step 3: Document expected artifacts**

List `e2e_summary.json`, the two exports, before/completed/absent PNG evidence, compiled program JSON, recording JSON, and the immutable Skill package path.

---

### Task 7: Full Verification Without Commit

**Files:**
- Verify all files from Tasks 1-6.

**Interfaces:**
- Produces a concise test report and residual-risk statement for user review.

- [ ] **Step 1: Run syntax and parity checks**

```bash
python -m py_compile \
  Pyautogui_server_for_window/demo/advanced_visual_work_queue.py \
  scripts/advanced_visual_work_queue_e2e.py \
  Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py \
  install/windows_pyautogui_bridge_server.py
cmp -s Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py \
  install/windows_pyautogui_bridge_server.py
```

- [ ] **Step 2: Run focused automated tests**

```bash
pytest -q \
  tests/unit/test_advanced_visual_work_queue_demo.py \
  tests/unit/test_advanced_visual_work_queue_e2e.py \
  tests/unit/test_equipment_skill_runtime.py \
  tests/unit/test_windows_pyautogui_bridge_server_helper.py \
  tests/unit/test_windows_pyautogui_demo_assets.py \
  tests/integration/test_equipment_skill_api.py
```

- [ ] **Step 3: Run both real isolated E2E scenarios**

Run: `python scripts/advanced_visual_work_queue_e2e.py --scenario all --display :99 --bridge-port 8878`

Expected: shifted/reordered replay succeeds with exactly one recovery; missing-target replay blocks safely; the main ATR server remains untouched.

- [ ] **Step 4: Check generated evidence and worktree integrity**

```bash
python - <<'PY'
import json
from pathlib import Path

summary = json.loads(Path("runs/equipment_skill_advanced_queue_e2e/e2e_summary.json").read_text())
assert summary["shifted_reordered"]["ok"] is True
assert summary["shifted_reordered"]["recovery_count"] == 1
assert summary["missing_target"]["blocked_as_expected"] is True
print(json.dumps(summary, indent=2))
PY
git diff --check
git status --short
```

- [ ] **Step 5: Report results without committing**

Report exact test counts, E2E artifact paths, selected specimen/configuration, recovery count, missing-target failure code, bridge parity, and any residual hardware-only risk. Leave all changes uncommitted for user inspection.
