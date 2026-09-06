# Test-Mode Execution Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent per-path test-mode execution profiles and a cycle-preserving operator LeRobot teleop handoff that is confirmed in the Manipulation Bridge popup before UTM Vision and Lab Equipment execution.

**Architecture:** A focused profile-store module owns schema validation, defaults, hashing, revisions, and atomic persistence; the main API and settings popup are thin clients of that store. The controller resolves one immutable profile snapshot at test-run start, maps physical-device choices onto the existing execution-policy boundaries, and holds any hybrid Manipulation-to-UTM transfer in the same coroutine behind a server-owned, single-use teleop handoff token. The existing LeRobot bridge remains the only teleop boundary, and UTM Vision remains the final placement authority after operator confirmation.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, asyncio, vanilla JavaScript/HTML/CSS, pytest, existing ATR controller/agent contracts, existing LeRobot and Bambu bridges.

**Spec:** `docs/superpowers/specs/2026-09-04-test-mode-execution-profiles-design.md`

## Global Constraints

- Do not call a printer, robot/VLA, camera, Windows/PyAutoGUI bridge, or UTM execution API in automated verification.
- Preserve every agent in the closed-loop graph; a `virtual` device maps to `preflight_only`, never to a fabricated physical success.
- Keep the saved profile immutable for an active run and preserve it through BO redesign cycles.
- Keep settings in the main-GUI popup; keep teleop controls and `Teleop Complete` in the Manipulation Bridge popup; keep Live GUI status-only.
- A stopped teleop session alone must never resume the loop; matching explicit confirmation and a fresh UTM Vision observation are both required.
- Preserve all existing Guardian, PLC, identity, freshness, hash, upload, start, and device-confirmation gates.
- Cooling may be skipped only on a print-body-skipped ejection-only artifact; full-print and all other auto-ejection flows retain cooldown.
- Preserve unrelated and concurrent uncommitted changes.

---

### Task 1: Persistent execution-profile store

**Files:**
- Create: `utils/test_mode_execution_profiles.py`
- Create: `tests/unit/test_test_mode_execution_profiles.py`

**Interfaces:**
- Produces: `TestModeExecutionProfileStore(path: Path)`
- Produces: `snapshot() -> dict[str, Any]`
- Produces: `resolve(profile_id: str, override: Mapping[str, Any] | None = None) -> dict[str, Any]`
- Produces: `save_profile(profile_id: str, profile: Mapping[str, Any], *, expected_revision: int) -> dict[str, Any]`
- Produces: `reset(profile_id: str | None, *, expected_revision: int) -> dict[str, Any]`
- Persists: `memory/test_mode_execution_profiles.json` as schema `test_mode_execution_profiles.v1`

- [ ] **Step 1: Write failing store tests**

```python
def test_missing_store_returns_safe_defaults_without_writing(tmp_path):
    store = TestModeExecutionProfileStore(tmp_path / "profiles.json")
    snapshot = store.snapshot()
    assert snapshot["profiles"]["installed_printer"]["printer_flow"] == {
        "print_body": "skip", "cooling_wait": "skip", "auto_ejection": True,
    }
    assert not (tmp_path / "profiles.json").exists()

def test_save_is_revisioned_hashed_and_atomic(tmp_path):
    store = TestModeExecutionProfileStore(tmp_path / "profiles.json")
    result = store.save_profile("virtual_bridge", VALID_PROFILE, expected_revision=0)
    assert result["revision"] == 1
    assert len(result["sha256"]) == 64

def test_cooling_skip_requires_print_skip(tmp_path):
    with pytest.raises(TestModeExecutionProfileValidationError):
        store.save_profile("physical_print", INVALID_COOLING_PROFILE, expected_revision=0)
```

- [ ] **Step 2: Run the store tests and confirm they fail because the module is absent**

Run: `pytest -q tests/unit/test_test_mode_execution_profiles.py`

Expected: collection failure for `utils.test_mode_execution_profiles`.

- [ ] **Step 3: Implement strict schemas, built-in defaults, and derived policy**

Implement exact allowed profile IDs (`virtual_bridge`, `installed_printer`, `physical_print`), agent IDs (`specimen`, `vision`, `manipulation`, `lab_equipment`), modes (`virtual`, `real`), printer values, and fixed `operator_teleop` strategy. Reject unknown keys. Map modes to `printer`, `vision`, `manipulation`, and `lab_equipment` execution-policy keys.

- [ ] **Step 4: Implement revision/hash/atomic persistence**

Serialize canonical JSON for SHA-256, use a same-directory temporary file plus `os.replace`, guard in-process writes with `threading.RLock`, and reject stale `expected_revision` with a distinct conflict exception. Loading missing/empty data returns defaults; malformed non-empty data returns defaults plus a warning and never partially applies it.

- [ ] **Step 5: Run the focused tests**

Run: `pytest -q tests/unit/test_test_mode_execution_profiles.py`

Expected: PASS for defaults, round trip, stale conflict, unsafe combinations, unknown keys, reset-one, reset-all, deterministic hash, and malformed-file fallback.

### Task 2: Main-GUI settings API and popup

**Files:**
- Modify: `app/main.py`
- Modify: `web/templates/index.html`
- Modify: `web/static/app.js`
- Create: `web/templates/test_mode_settings.html`
- Create: `web/static/test_mode_settings.js`
- Modify: `web/static/styles.css`
- Create: `tests/integration/test_test_mode_execution_profiles_api.py`
- Create: `tests/unit/test_test_mode_settings_gui_static.py`

**Interfaces:**
- Consumes: `TestModeExecutionProfileStore`
- Produces: `GET /test-mode-settings`
- Produces: `GET /api/test-mode-execution-profiles`
- Produces: `PUT /api/test-mode-execution-profiles/{profile_id}` with `{expected_revision, profile}`
- Produces: `POST /api/test-mode-execution-profiles/reset` with `{expected_revision, profile_id?}`

- [ ] **Step 1: Write failing route and static-contract tests**

Assert the Run Control contains `btn-test-mode-settings` immediately after `btn-gpu-clear`, the click handler opens `/test-mode-settings`, and the popup renders all three profile tabs, four always-visible device controls, printer controls, handoff strategy, revision, derived warnings/blockers, and save/reload/reset actions.

- [ ] **Step 2: Run the tests and verify 404/missing-markup failures**

Run: `pytest -q tests/integration/test_test_mode_execution_profiles_api.py tests/unit/test_test_mode_settings_gui_static.py`

- [ ] **Step 3: Add typed API handlers and error mapping**

Return `409` for stale revisions and `422` for unsafe or unknown profile data. Resolve the store at the repository `memory/test_mode_execution_profiles.json`; never accept a client path.

- [ ] **Step 4: Implement the popup and main-GUI launcher**

Keep all controls visible. Disable `cooling_wait=skip` while print body executes and show the invariant inline. Render the server-returned revision/hash, independently retain unsaved state per tab, and label changes as applying to the next run.

- [ ] **Step 5: Run focused API/static tests**

Run: `pytest -q tests/integration/test_test_mode_execution_profiles_api.py tests/unit/test_test_mode_settings_gui_static.py`

Expected: PASS without opening a browser or device connection.

### Task 3: Controller snapshot and per-device execution policy

**Files:**
- Modify: `app/controller.py`
- Modify: `agents/vision_agent.py`
- Modify: `tests/unit/test_controller_planning.py`
- Modify: `tests/unit/test_vision_agent.py`

**Interfaces:**
- Consumes: `TestModeExecutionProfileStore.resolve(profile_id, override)`
- Produces in experiment spec: `test_mode_profile` schema `resolved_test_mode_execution_profile.v1`
- Produces in experiment spec: normalized `execution_policy` including `vision`
- Preserves: snapshot, policy, and printer flow across `_closed_loop_static_design_constraints` and BO redesign

- [ ] **Step 1: Write failing controller resolution tests**

Save a hybrid installed-printer profile, select that path, and assert selection no longer forces unrelated agents to execute. Assert `source_revision`, `source_sha256`, and the four derived policy keys appear in the current spec, and remain byte-equivalent after a BO recommendation is merged.

- [ ] **Step 2: Write a failing independent Vision-preflight test**

Set `vision=preflight_only` while other stages execute, install camera/LLM tripwires, and assert Vision emits typed preflight evidence without capture.

- [ ] **Step 3: Run tests and confirm current hard-coded path behavior fails**

Run: `pytest -q tests/unit/test_controller_planning.py -k 'execution_profile or execution_policy' tests/unit/test_vision_agent.py -k preflight`

- [ ] **Step 4: Resolve and freeze the profile at new-run start**

Replace the installed/physical `all execute` assignment in `_apply_specimen_printer_choice_to_spec` with store resolution. Apply precedence defaults -> saved profile -> explicit validated one-shot override -> final invariant validation. Reuse the same resolved object after LLM normalization and across later cycles.

- [ ] **Step 5: Extend execution-policy normalization and Vision boundary**

Accept only `execute`/`preflight_only` for the new `vision` key. Preserve legacy specs without `test_mode_profile`. Stop Vision before camera/runtime calls whenever its own policy is `preflight_only`.

- [ ] **Step 6: Run focused controller/Vision tests**

Run: `pytest -q tests/unit/test_controller_planning.py tests/unit/test_vision_agent.py`

### Task 4: Profile-driven printer-body and cooldown behavior

**Files:**
- Modify: `app/controller.py`
- Modify: `device_bridges/bambu_autoejection.py`
- Modify: `device_bridges/bambu_bridge.py`
- Modify: `tests/unit/test_bambu_autoejection.py`
- Modify: `tests/unit/test_bambu_bridge.py`
- Modify: `tests/unit/test_controller_planning.py`

**Interfaces:**
- Consumes: `test_mode_profile.printer_flow`
- Produces: existing ejection-only project-file request plus explicit cooldown policy
- Produces: `atr_cooldown_wait_policy=not_required_no_print_body` only when both print body and cooldown are skipped

- [ ] **Step 1: Extend failing tests to cover all printer-flow combinations**

Assert installed defaults select ejection-only with no `M190`, physical print retains `M190`, virtual artifacts retain the full sequence locally, and no full-print auto-ejection route loses cooldown.

- [ ] **Step 2: Run tests and confirm the currently hard-coded ejection-only behavior is insufficient**

Run: `pytest -q tests/unit/test_bambu_autoejection.py tests/unit/test_bambu_bridge.py tests/unit/test_controller_planning.py -k printer`

- [ ] **Step 3: Thread the resolved printer flow through existing fields**

Use the current immutable Bambu patch/validation boundary. Pass an explicit cooldown inclusion flag only to ejection-only generation, record its policy in metadata, and leave full-print patching unchanged.

- [ ] **Step 4: Run focused printer tests**

Run: `pytest -q tests/unit/test_bambu_autoejection.py tests/unit/test_bambu_bridge.py tests/unit/test_controller_planning.py -k 'printer or specimen_choice'`

### Task 5: Server-owned operator teleop handoff state and API

**Files:**
- Create: `utils/operator_teleop_handoff.py`
- Create: `tests/unit/test_operator_teleop_handoff.py`
- Modify: `app/controller.py`
- Modify: `app/main.py`
- Modify: `tests/integration/test_lerobot_gui_api.py`

**Interfaces:**
- Produces: `OperatorTeleopHandoffRegistry`
- Produces: single-use records keyed by `(run_id, handoff_token)` with cycle/specimen/candidate identity and an `asyncio.Event`
- Produces: `GET /api/planning/runs/{run_id}/teleop-handoff?handoff_token=...`
- Produces: `POST /api/planning/runs/{run_id}/teleop-handoff/confirm`
- Confirmation body: `{handoff_token, teleop_session_id, confirmed_by}`

- [ ] **Step 1: Write failing registry lifecycle tests**

Cover pending creation, refresh-safe lookup, identity mismatch, active-session rejection, stop/port/camera evidence rejection, single-use confirmation, cancellation, and token invalidation.

- [ ] **Step 2: Write failing bounded API tests**

Use a fake LeRobot bridge only. Assert the API rejects the wrong run/token/session and any active or unreleased session; assert a matching stopped session marks operator confirmation but does not itself claim Vision success.

- [ ] **Step 3: Implement the registry and controller facade**

Store only bounded metadata and events in memory. Use cryptographically random tokens. Expose status/confirm/cancel methods; stop/reset/E-stop invalidates pending tokens and attempts an idempotent teleop stop through the existing bridge boundary.

- [ ] **Step 4: Implement API validation against existing LeRobot status**

Require the matching session to be stopped and require trustworthy follower/leader port-release and camera-return evidence before delegating confirmation to the controller. Never accept those safety booleans solely from the browser payload.

- [ ] **Step 5: Run focused lifecycle/API tests**

Run: `pytest -q tests/unit/test_operator_teleop_handoff.py tests/integration/test_lerobot_gui_api.py -k teleop`

### Task 6: Manipulation Bridge handoff popup

**Files:**
- Modify: `web/templates/lerobot.html`
- Modify: `web/static/lerobot.js`
- Modify: `web/static/lerobot.css`
- Modify: `tests/unit/test_lerobot_gui_static.py`
- Modify: `tests/integration/test_lerobot_gui_browser_smoke.py`

**Interfaces:**
- Consumes query: `run_id` and `handoff_token`
- Consumes existing: `/api/lerobot/teleoperate/start|stop|status`
- Consumes new: teleop-handoff GET/confirm endpoints
- Produces: `Teleop Handoff` panel and `Teleop Complete` action

- [x] **Step 1: Write failing static/browser-contract tests**

Assert the handoff panel is in `#teleoperation-card`, shows bounded identity, and keeps `Teleop Complete` disabled until a matching session exists. Assert the completion action invokes the ordinary Teleop Stop endpoint before the bounded confirmation endpoint, and ordinary `/lerobot` use remains unchanged.

- [x] **Step 2: Run tests and confirm the panel is absent**

Run: `pytest -q tests/unit/test_lerobot_gui_static.py tests/integration/test_lerobot_gui_browser_smoke.py -k teleop`

- [x] **Step 3: Add handoff-scoped UI behavior**

Load pending context from the query token, bind the started teleop session ID, and enable completion once that matching session exists. `Teleop Complete` must call the same idempotent stop endpoint as Teleop Stop, verify stopped/released status, and only then call confirm. Stopping by itself updates the panel but never calls confirm. A successful explicit confirm reports that UTM Vision verification is next.

- [x] **Step 4: Run focused GUI tests**

Run: `pytest -q tests/unit/test_lerobot_gui_static.py tests/integration/test_lerobot_gui_browser_smoke.py -k teleop`

### Task 7: Same-cycle pause, UTM Vision, and Lab Equipment ordering

**Files:**
- Modify: `app/controller.py`
- Modify: `tests/unit/test_controller_planning.py`
- Modify: `tests/integration/test_controller_run.py`

**Interfaces:**
- Consumes: resolved hybrid policy where `manipulation=preflight_only` and `lab_equipment=execute`
- Produces: `pending_operator_teleop_handoff` runtime state and popup URL
- Resumes: the same `_run_planning_loop_tail` coroutine after confirmation
- Orders: operator confirm -> fresh equipment-owned UTM Vision -> Lab Equipment execute

- [ ] **Step 1: Write a failing same-cycle hybrid test with device tripwires**

Count Design, Specimen, Manipulation, Vision, and Equipment calls. Assert the loop pauses after Manipulation preflight; Equipment is untouched; teleop stop alone does not resume; confirmation resumes the same run/cycle without repeating earlier agents; fresh UTM Vision occurs once before Equipment.

- [ ] **Step 2: Add failing negative tests**

Reject missing physical-material evidence, stale/negative UTM Vision, wrong specimen/candidate/cycle, reused token, and stop/E-stop cancellation. Assert every failure has a stable reason code and no Equipment call.

- [ ] **Step 3: Run tests and confirm the loop currently advances or exits incorrectly**

Run: `pytest -q tests/unit/test_controller_planning.py -k teleop_handoff tests/integration/test_controller_run.py -k teleop_handoff`

- [ ] **Step 4: Insert the gate at the existing stage boundary**

After Manipulation preflight and before the equipment-placement Vision stage, derive the hybrid requirement, create one pending handoff, publish its popup URL, and await its event. Do not create another run or recursively restart the loop.

- [ ] **Step 5: Require fresh UTM Vision before Equipment**

After operator confirmation, execute the existing equipment-owned UTM placement observation with the same lineage. Record the observation in the handoff payload, require non-stale positive placement evidence, then and only then allow the existing Lab Equipment stage.

- [ ] **Step 6: Add the external-specimen fail-closed gate**

If printer actuation did not produce a physical specimen, require explicit materialization identity plus fresh pickup-side Vision evidence before teleop. Until that evidence exists, leave the handoff blocked with a stable `EXTERNAL_SPECIMEN_MATERIALIZATION_REQUIRED` result.

- [ ] **Step 7: Run focused controller/integration tests**

Run: `pytest -q tests/unit/test_controller_planning.py -k 'teleop_handoff or execution_profile' tests/integration/test_controller_run.py -k teleop_handoff`

### Task 8: Hardware-free profile matrix and regression closure

**Files:**
- Create: `tests/integration/test_test_mode_execution_profile_matrix.py`
- Modify only for discovered contract defects: files from Tasks 1-7

**Interfaces:**
- Consumes: the three built-in profiles plus representative hybrid profiles
- Produces: a hardware-free evidence matrix for physical boundary reachability and loop ordering

- [ ] **Step 1: Add a matrix test with tripwire physical tools**

Cover the default virtual, installed, physical, virtual-Manipulation/real-Lab, and real-Manipulation/virtual-Lab profiles. Replace every external call with a deterministic fake or a tripwire; do not use the real LAN.

- [ ] **Step 2: Run focused affected suites**

Run: `pytest -q tests/unit/test_test_mode_execution_profiles.py tests/integration/test_test_mode_execution_profiles_api.py tests/unit/test_test_mode_settings_gui_static.py tests/unit/test_controller_planning.py tests/unit/test_vision_agent.py tests/unit/test_bambu_autoejection.py tests/unit/test_bambu_bridge.py tests/unit/test_operator_teleop_handoff.py tests/integration/test_lerobot_gui_api.py tests/unit/test_lerobot_gui_static.py tests/integration/test_test_mode_execution_profile_matrix.py`

- [ ] **Step 3: Run broader controller, agent, GUI, and bridge regression suites**

Run: `pytest -q tests/integration/test_controller_run.py tests/unit/test_specimen_agent.py tests/unit/test_manipulation_lerobot_agent.py tests/unit/test_equipment_agent.py tests/integration/test_live_gui_runtime_layout.py tests/integration/test_lerobot_gui_browser_smoke.py`

- [ ] **Step 4: Inspect the diff and generated state**

Confirm no generated profile/runtime artifact is tracked, no secret/token is logged, Live GUI has no handoff confirmation action, full-print cooldown is intact, and all modified files are within the approved scope.

- [ ] **Step 5: Record verification evidence**

Update the checkbox state in this plan only for completed work and report exact test commands, pass/fail counts, and any remaining hardware-only validation separately. Do not claim real-device success from mocks.
