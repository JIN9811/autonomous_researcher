# Lab Equipment Agent UTM Visual-Control/Data-Loop Audit

Date: 2026-05-30
Source requirement: `개선안/05_lab_equipment_agent_utm_visual_control_data_loop_research.md`
Status: implementation and simulator/browser evidence strengthened; physical live UTM run evidence is still required before calling the goal fully complete.

## Completion Rule

Improvement 05 defines Lab Equipment success as all of the following, not macro success alone:

1. Windows GUI state changed as intended.
2. UTM physical motion/test progression is verified.
3. UTM CSV/JSON data returns to Linux and is readable by Analysis.
4. Save/export responsibility is explicit when auto-save is not guaranteed.

The current implementation enforces this through `equipment_report.v1`, `utm_data_ready.v1`, `equipment_handoff`, live evidence audit gates, Vision cross-checks, request-log identity proof, Linux artifact pull, and CSV parse/signal probes.

## Requirement Evidence Matrix

| Requirement | Current Evidence | Status |
| --- | --- | --- |
| Do not hand off on `macro ok` alone | `LabEquipmentAgent` builds `cross_checks`, `handoff_gate`, and blocks unless screen, Vision, save/export, Linux pull, parse probe, and request audit pass. Covered by `tests/unit/test_equipment_agent.py`. | Implemented/tested |
| Registered UTM protocols | `utm_compression_start_v1`, `utm_export_csv_v1`, `utm_manual_save_csv_v1`, `utm_stop_or_abort_v1` exist in Linux bridge and both Windows bridge servers. Metadata includes preconditions, expected screen states, save policy, output artifacts, and abort metadata. | Implemented/tested |
| Screen-control primitives | `screenshot`, `locate_image`, `wait_until_image`, `focus_window`, `assert_visible`, `assert_text`, `wait_until_text` are supported in Windows `/execute`. | Implemented/tested |
| UIA/image/OCR/coordinate priority | UIA/pywinauto is attempted first when selector fields exist, image matching next, OCR/text as explicit primitive, and coordinate fallback only when configured. | Implemented/tested |
| Coordinate fallback evidence | Coordinate click records screen size, DPI scaling, target window rect, before/after screenshots, and SHA-256 hashes. | Implemented/tested |
| Failure taxonomy | Explicit codes include `CLICK_NO_STATE_CHANGE`, `UI_LOCATOR_NOT_FOUND`, `UTM_RUNNING_STATE_TIMEOUT`, `UTM_NO_MOTION_AFTER_START`, `UTM_SAVE_DIALOG_TIMEOUT`, `UTM_SAVE_CONFIRMATION_FAILED`, `UTM_DATA_TIMEOUT`, `UTM_EXPORT_FILE_MISSING`, and `UTM_DATA_PARSE_FAILED`. | Implemented/tested |
| Vision physical cross-check | Equipment requests/consumes `utm_pre_start`, `utm_motion_confirm`, and `utm_test_complete`; live mode blocks on missing/stale/identity-mismatched Vision evidence. | Implemented/tested with simulated Vision signals |
| Windows export and manual save fallback | Windows bridge watches export path and runs `utm_manual_save_csv_v1` when needed; save method and confirmation evidence enter `data_acquisition`. | Implemented/tested |
| Linux artifact pull | Linux bridge pulls `GET /artifacts/{artifact_id}`, writes under `artifacts/equipment/<run_id>/utm`, and only sets `result_file`/`utm_csv_path` when parse probe passes. | Implemented/tested |
| Request-log audit | Windows bridge writes non-secret `/execute` audit identity; Equipment requires matching `run_id`, `sequence_id`, `specimen_id`, and `program_id`. | Implemented/tested |
| Analysis handoff gate | Analysis blocks live CSVs when `equipment_handoff` or `utm_data_ready` is not ready, or evidence cross-checks are incomplete. | Implemented/tested |
| Knowledge/Guardian propagation | Blocked equipment evidence, artifact refs, metrics, and failure tags are preserved for Knowledge and Guardian recovery decisions. | Implemented/tested |
| Live GUI report | `/live` equipment report renders bridge/profile, preconditions, screen assertions, Vision physical checks, data ledger, save/export, handoff gate, safety gate, evidence audit, artifacts, and recovery. | Browser-audited |
| Linux Windows Equipment GUI live validation | `/equipment/windows` exposes `Live Validation Report`, which calls live `/request-log`, `/health`, and `/programs`, writes `lab_equipment_utm_live_validation.json`, and intentionally does not send `/execute`. The same API now supports guarded physical validation only when `confirm_live_execute` and `confirm_physical_setup_safe` are both true. | Implemented/tested with fake bridge; real UTM proof still required |
| Windows Bridge GUI | Standalone Windows bridge page renders operator HUD, timeline, live proof checklist, recommended next action, evidence/artifact views, and guarded Live UTM controls at 1920x1080 without horizontal overflow. | Browser-audited |
| Physical live UTM motion | Requires an actual UTM software/fixture run with Vision confirmation and exported CSV. No current evidence in this workspace proves this against real hardware. | Remaining live validation |

## Validation Commands Executed

```bash
python3 -m py_compile \
  Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py \
  install/windows_pyautogui_bridge_server.py \
  device_bridges/windows_pyautogui_bridge.py \
  agents/equipment_agent.py

.venv/bin/pytest -q \
  tests/unit/test_windows_pyautogui_bridge_server_helper.py \
  tests/unit/test_equipment_pyautogui_bridge.py \
  tests/unit/test_equipment_agent.py \
  tests/unit/test_analysis_agent.py \
  tests/unit/test_knowledge_agent.py \
  tests/unit/test_guardian_agent.py \
  tests/integration/test_live_gui_runtime_layout.py

python3 Pyautogui_server_for_window/tests/smoke_test.py

python3 -m py_compile \
  scripts/lab_equipment_live_utm_validation.py \
  scripts/audit_lab_equipment_utm_completion.py

.venv/bin/pytest -q tests/unit/test_lab_equipment_live_validation_runner.py
.venv/bin/pytest -q tests/unit/test_lab_equipment_completion_audit.py

.venv/bin/pytest -q tests/integration/test_live_gui_runtime_layout.py -k "windows_equipment"

.venv/bin/python tests/ui/windows_bridge_gui_browser_audit.py \
  --base-url http://127.0.0.1:18765 \
  --out-dir artifacts/ui \
  --width 1920 \
  --height 1080 \
  --geckodriver /snap/bin/geckodriver

.venv/bin/python tests/ui/equipment_report_browser_audit.py \
  --base-url http://127.0.0.1:7862 \
  --out-dir artifacts/ui \
  --width 1920 \
  --height 1080 \
  --geckodriver /snap/bin/geckodriver

.venv/bin/python tests/ui/windows_equipment_browser_audit.py \
  --base-url http://127.0.0.1:7862 \
  --out-dir artifacts/ui \
  --width 1920 \
  --height 1080 \
  --geckodriver /snap/bin/geckodriver
```

Latest observed automated results:

- Targeted Windows Equipment GUI/API tests after physical-validation API extension: `12 passed, 16 deselected, 4 warnings`.
- Physical validation -> Analysis handoff metadata -> evidence audit -> proof package integration targeted test: `2 passed, 22 deselected, 4 warnings`.
- Windows Equipment live-validation/proof/completion-audit API/GUI contract target: `12 passed, 18 deselected, 4 warnings`; this covers `/api/equipment/windows/completion-audit` and the GUI completion-audit card.
- Analysis/Equipment live-handoff targeted gate checks: `3 passed, 37 deselected`.
- Improvement 05 completion audit CLI fail-closed unit tests: passed (`tests/unit/test_lab_equipment_completion_audit.py`).
- Current workspace completion audit: `./scripts/audit_lab_equipment_utm_completion.py --latest --quiet` returns non-zero with current proof blockers such as missing screen/Vision evidence, which correctly keeps this goal incomplete until the real UTM run artifacts exist.
- Windows bridge helper unit tests: `57 passed`.
- Python compile checks for FastAPI, runner, Windows bridge, install copy, Linux bridge, and Equipment Agent: passed.
- Windows Equipment JS syntax check with `node --check`: passed.
- Windows package smoke: `smoke test passed`.
- Windows bridge browser audit: `PASS`, `scrollWidth=1908`, `clientWidth=1908`.
- Equipment report browser audit: `PASS`.
- Windows equipment browser audit after completion-audit GUI extension: `PASS`, `scrollWidth=1908`, `clientWidth=1908`.
- Live validation runner unit tests: `4 passed`.
- Broader prior core unit/integration bundle: `159 passed, 4 warnings`.

## Live Validation Runner And GUI Report

A dedicated runner and matching Linux Equipment GUI report now exist for collecting live-readiness proof before physical UTM execution. The GUI path is:

```text
/equipment/windows -> Live Validation Report
```

The GUI report is non-actuating. It contacts the selected Windows bridge for request audit, health, and program registry only, then persists the same `lab_equipment_utm_live_validation.v1` report schema under the current run artifacts. It must not be treated as physical completion because `/execute` is intentionally not sent.

The same GUI also exposes `Run Physical Validation`. That path sends `/execute` only when the operator checks `Physical UTM setup safe` and the API receives both `confirm_live_execute=true` and `confirm_physical_setup_safe=true`. The API first runs readiness and live preflight gates; if either gate is incomplete, `/execute` is not sent and the report is blocked. If `/execute` is sent, the report only passes when request-log identity, screen evidence, Vision proof, save/export responsibility, Linux data artifact, and CSV parse gates all pass. A successful physical validation report is now consumed by `/api/equipment/windows/evidence-audit` and `/api/equipment/windows/proof-package` as `last_windows_utm_physical_validation`, so the proof package can be built directly from the guarded live validation report. The same successful report is also promoted into the normal runtime handoff keys: `equipment_result`, `equipment_report`, `equipment_handoff`, and `utm_data_ready`. This is the bridge from guarded physical validation to `AnalysisAgent`; blocked validation reports are stored for audit but do not overwrite the last Analysis-readable equipment handoff.

A dedicated runner also exists for collecting the remaining physical-live proof:

```bash
# Non-actuating preflight only. Does not send /execute.
./scripts/lab_equipment_live_utm_validation.py \
  --run-id utm-live-validation-001 \
  --specimen-id specimen-live-validation-001

# Physical live validation. Use only after the UTM fixture, Windows bridge,
# locator/profile setup, and Vision proof path are ready.
./scripts/lab_equipment_live_utm_validation.py \
  --run-id utm-live-validation-001 \
  --specimen-id specimen-live-validation-001 \
  --confirm-live-execute \
  --require-screen-assertions \
  --require-window-focus \
  --vision-proof-json artifacts/equipment/utm-live-validation-001/vision_proof.json
```

The runner uses `device_bridges.windows_pyautogui_bridge.WindowsPyAutoGUIBridge`, not raw ad-hoc HTTP, and writes:

```text
artifacts/equipment/<run_id>/live_validation/lab_equipment_utm_live_validation.json
```

The report schema is `lab_equipment_utm_live_validation.v1`. A live run only passes when all required gates pass: bridge/PyAutoGUI health, registered UTM program, request-log access, `/execute` request identity match, execution completion, before/running/complete screen evidence, Vision physical proof, save/export responsibility, Linux data artifact pull, and UTM CSV parse probe. When those gates pass, `runtime_promotion.verified=true` appears in the API response and the active controller state receives an Analysis-ready `utm_data_ready.v1` packet with `status=ready` and a Linux-local `result_file`/`utm_csv_path`.

The runner intentionally returns success for non-actuating preflight only when bridge health, program registry, and request-log access are valid. That preflight success is not physical-live completion; it only proves the setup is ready to attempt the physical validation.

The Windows Equipment GUI now includes a `Completion Audit` button beside `Verify Proof Package`. It calls `/api/equipment/windows/completion-audit`, stores `last_windows_utm_completion_audit`, persists `windows_utm_completion_audit_<timestamp>.json` under `artifacts/equipment/<run_id>/utm/`, and displays `complete_evidence_verified` only when the persisted proof package verifier returns `status=verified`. This is the GUI-side guard against treating preflight, simulator output, or a partial proof package as completed Improvement 05 evidence.

A strict completion audit CLI is also available after a proof package is generated:

```bash
# Fails closed if no proof package exists or any required proof gate is missing.
./scripts/audit_lab_equipment_utm_completion.py --latest

# Or verify a specific persisted proof package.
./scripts/audit_lab_equipment_utm_completion.py \
  --proof-package artifacts/equipment/<run_id>/utm/windows_utm_proof_package_<timestamp>.json
```

The audit exits `0` only when `equipment.pyautogui.live_proof_package.verify` returns `status=verified`. It exits non-zero for preflight-only reports, missing physical `/execute` identity, missing screen files, missing Vision frame proof, missing Linux CSV, parse failure, or incomplete save/export responsibility.

## Required Live Validation Before Goal Completion

To mark Improvement 05 fully complete, run at least one real UTM live validation with the Windows bridge and Vision system connected:

1. Select the saved Windows bridge candidate in `/equipment/windows`.
2. Confirm `/health`, `/readiness`, and `/request-log` pass.
3. Calibrate or confirm UTM locators/text regions for ready/start/running/complete/save states.
4. Paste or attach Vision proof for `utm_pre_start`, `utm_motion_confirm`, and `utm_test_complete` with matching run/specimen identity.
5. Check `Physical UTM setup safe`, then run `Run Physical Validation` or the CLI with `--confirm-live-execute`.
6. Confirm the report shows `execute_sent=true`, `/execute` in `touched_endpoints`, and `requested_physical_execute=true`.
7. Confirm Windows export or manual save creates a UTM CSV.
8. Confirm Linux pulls the CSV and parse probe passes with non-flat force/displacement signals.
9. Confirm `equipment_handoff.status=ready_for_analysis` and Analysis accepts the file.
10. Generate `/api/equipment/windows/proof-package`, then run the GUI `Completion Audit` or `./scripts/audit_lab_equipment_utm_completion.py --latest` and require `complete_evidence_verified` / exit code `0`.
11. Archive the Live GUI equipment report, request log, screenshots, proof package, completion audit artifact (`windows_utm_completion_audit_<timestamp>.json`), and UTM CSV under the run artifacts.

Until this real hardware run is captured, the implementation is strong but the full objective remains not formally complete.

## Vision Proof Draft Helper

The Windows Equipment GUI now includes `Load Vision Proof Draft` beside the `Vision Proof JSON for physical validation` textarea. It calls:

```text
POST /api/equipment/windows/vision-proof-draft
```

This endpoint is non-actuating. It reads the active runtime metadata and latest Vision observations, searches for `utm_pre_start`, `utm_motion_confirm`, and `utm_test_complete`, and fills a physical-validation JSON draft with the matching run/specimen identity and collected frame IDs.

Important boundary:

- `status=ready` means all three Vision checks were found and at least one frame/evidence id is present.
- `status=incomplete` means the draft is only a template and must not be used as proof of physical completion.
- The helper does not start the Windows bridge, UTM software, robot, or `/execute` endpoint.
- The final objective is still incomplete until physical validation, proof-package verification, and Completion Audit all pass.

The GUI stores the latest draft in `last_windows_utm_vision_proof_draft` and shows the generated JSON in the textarea so the operator can review it before running physical validation.

## Physical Screen Evidence Strictness Update

Physical live validation now verifies screen evidence at the same level expected by Completion Audit. The `screen_state_evidence` gate requires `before_start`, `after_start`, and `after_complete` checkpoints to be `ok=true`, each checkpoint must have a unique screenshot reference, and every reference must resolve either directly to a Linux-local file or through an artifact record with an existing local file. String-only refs such as `screen-before` are no longer accepted unless an accompanying artifact record maps them to an actual file.

This prevents a physical validation report from becoming `verified_complete` when the later proof-package verifier would still fail with `UTM_SCREEN_EVIDENCE_FILES_REQUIRED`.

## Physical Save/Export Responsibility Strictness Update

Physical live validation and Completion Audit no longer accept a boolean-only `save_export_responsibility_ok=true` claim. Save/export responsibility must include a recognized live save method (`windows_export_watch`, `manual_save_dialog`, or `export_menu`), an agent-attempted or watched save path, explicit save confirmation, and a Windows or Linux path. Simulated or synthetic save methods are not accepted for physical live validation.

This keeps the `save/export responsibility` gate aligned with the 5번 requirement: if the UTM software does not auto-save reliably, Equipment Agent must prove the export/save UI path or watched export path actually completed.

## Physical Data Artifact Strictness Update

Physical live validation now requires the UTM CSV to exist as a Linux-local file before the run can be considered `verified_complete`. `result_file`, `utm_csv_path`, `data_acquisition.linux_path`, or `data_acquisition.local_path` must resolve to an existing local file. The runner then opens that CSV and checks the required `time_s`, `displacement_mm`, and `force_N` columns plus basic signal quality: monotonic time, changing displacement, and nonzero changing force.

This prevents a physical validation report from passing on `local_parse_ok=true`, `data_parse_probe_ok=true`, or a path string alone when the proof-package verifier would later fail with a missing CSV or flat signal.

## Physical Vision Proof Strictness Update

Physical live validation now fails closed unless the submitted `vision_proof` carries both identity and visual evidence:

- top-level `run_id` must be present and match the live validation run id;
- top-level `specimen_id` must be present and match the specimen under UTM;
- each required check, `utm_pre_start`, `utm_motion_confirm`, and `utm_test_complete`, must be `ok=true`;
- each required check must carry frame evidence such as `evidence.frame_ids[]`, `frame_ids[]`, or an equivalent observation/frame id;
- the combined Vision proof must contain at least three unique frame/observation IDs, so one reused screenshot cannot satisfy fixture, motion, and completion proof at the same time;
- if a generated Vision check embeds an `identity` object with missing or mismatched fields, that check is not accepted.

This closes the gap where a boolean-only Vision JSON could make the live-validation report look complete before physical evidence was actually attached. The later proof-package verifier and Completion Audit still remain mandatory.

## Linux Artifact Record Compatibility Update

After a live Windows bridge `/execute` response exposes `output_artifacts[]`, the Linux bridge now preserves the pulled records in both `output_artifacts[]` and `artifact_records[]`. This keeps the live validation runner, proof-package verifier, Equipment Agent report, and Analysis handoff on the same resolvable evidence list. Each pulled screen or CSV artifact must carry a Linux-local `local_path`/`path`, checksum, size, and kind; Windows-only paths remain provenance only.

## Physical Live Execute Strictness Update

Completion Audit now requires explicit physical live dispatch evidence in addition to request-log, screen, Vision, save/export, and CSV proof. A proof package and the intermediate `/api/equipment/windows/evidence-audit` result must include physical execution evidence with `ok=true`, `requested_physical_execute=true`, `execute_sent=true`, `non_actuating=false`, `status=verified_complete`, and matching `run_id`, `sequence_id`, `specimen_id`, and `program_id`. A manually assembled `equipment_report.v1`, a non-actuating preflight report, simulator output, or a copied CSV/screenshot bundle cannot satisfy this gate. Missing or incomplete dispatch evidence blocks verification with `UTM_PHYSICAL_LIVE_EXECUTE_REQUIRED`.

## Proof Package Source And Uniqueness Strictness Update

The live validation runner, proof package builder, intermediate evidence-audit API, and proof verifier no longer accept `manifest.physical_execution` alone. Verification also requires `source_packets.last_windows_utm_physical_validation` to carry matching physical dispatch evidence. The manifest and source packet must both carry `run_id`, `sequence_id`, `specimen_id`, and `program_id`, and those identity fields must match. Screen evidence must resolve to at least three distinct Linux-local image files with a recognized image signature; repeating the same screenshot path three times, referencing a text placeholder, or pointing to a non-image file is treated as incomplete screen proof and blocks verification with `UTM_SCREEN_EVIDENCE_FILES_REQUIRED`. The intermediate evidence-audit API also checks that the referenced Linux-local UTM CSV exists and reruns the CSV parse/signal probe before showing the run as Analysis-ready.

## Windows Bridge Source-Evidence Strictness Update

The Windows bridge now performs the first screen-evidence gate before Linux proof packaging. During `utm_compression_start_v1`, screenshots are accepted only when the saved file has a recognized image signature. A live compression protocol cannot return `verified_complete` unless `before_start`, `after_start`, and `after_complete` each map to a distinct valid screen artifact. Invalid `.png` placeholders are blocked at the source with `UTM_SCREEN_EVIDENCE_FILES_REQUIRED`.

`utm_export_csv_v1` is intentionally exempt from the three-checkpoint physical-motion gate because it is an export/save macro, not proof that the compression test started and completed. Downstream Analysis handoff still requires the full compression-run proof package and Completion Audit.

Latest focused validation after this source-evidence gate:

```bash
.venv/bin/pytest -q tests/unit/test_windows_pyautogui_bridge_server_helper.py
# 57 passed

python3 Pyautogui_server_for_window/tests/smoke_test.py
# smoke test passed
```


## CLI Physical-Execution Readiness Gate Update

The standalone runner `scripts/lab_equipment_live_utm_validation.py` now mirrors the GUI safety boundary before physical execution. It builds a passive UTM readiness packet from the active UTM profile, registered program catalog, export glob, `require_screen_assertions`, locator set, and simulation flag. When `--confirm-live-execute` is provided, the runner sends `/execute` only if `passive_readiness.ready_for_autonomous_profile=true`. If the UTM profile is missing required locators, has no export glob, uses simulation, or has screen assertions disabled/incomplete, the runner records `UTM_PHYSICAL_VALIDATION_READINESS_BLOCKED`, keeps `execute_sent=false`, and writes the blocked report instead of contacting `/execute`.

This prevents the CLI path from being less strict than the FastAPI Equipment GUI path. Non-actuating preflight now reports `passive_utm_readiness` as a required gate when the runner has profile evidence available, so an operator can see missing locator/export/profile work before attempting the real UTM run.
