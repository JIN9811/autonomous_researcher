---
doc_type: evidence
subtype: test_report
status: active
authority: evidentiary
audience:
  - developer
  - reviewer
  - operator
scope:
  - loop_artifact_archiving
  - non_actuating_regression_tests
summary: Offline validation of loop-scoped evidence preservation and known unrelated test/documentation failures.
evidence_date: 2026-09-06
method: Pytest with temporary artifact roots and non-actuating fixtures, Node rendering tests, source review, and documentation validation.
related_docs:
  - docs/runtime/loop_artifact_archiving.md
  - docs/standards/documentation_standard.md
supersedes: []
---

# Loop Artifact Archiving — Offline Verification

## Summary

The selected agent/runtime regression suite passed 403 tests. After the final
custom-root and failure-handling changes, focused preservation/telemetry tests
passed 75 tests and selected LeRobot rollout tests passed 27 tests. JavaScript
history/rendering tests passed 7 tests. These groups overlap and must not be
summed as unique coverage.

The repository-wide test/doc state is **not all green**: an earlier broader
run had 7 LeRobot failures, reproduced with this change's archive hooks
disabled; the documentation validator reports 27 existing defects across two
unchanged documents. Those failures were not silently waived or fixed as
part of the archival feature.

## Scope and Evidence Basis

- Workspace: `/home/jin/autonomous_researcher`, local `.venv`, Python 3.12.
- Scope: uncommitted working-tree changes on 2026-09-06; the checkout already
  contained other work. This is not a clean-HEAD baseline measurement.
- Device calls, printers, robots, UTM, model providers, and training jobs were
  not intentionally started. Tests use temporary files and fixtures.
- No live-server restart, commit, push, old-artifact migration, or deletion
  was performed for this task.
- Independent read-only review identified and prompted tests/fixes for late
  results after cancellation, Guardian loop ownership, storage-error masking,
  run-switch filters, and separately configured logging/archive roots.

## Reproduction and Results

### Agent/runtime regression

```bash
.venv/bin/pytest tests/unit/test_agent_artifact_archive.py tests/integration/test_all_agent_loop_archives.py tests/integration/test_loop_artifact_api.py tests/unit/test_manipulation_lerobot_agent.py tests/unit/test_lerobot_joint_telemetry.py tests/unit/test_langgraph_runtime.py tests/unit/test_equipment_agent.py tests/unit/test_bo_agent.py tests/unit/test_tool_registry.py tests/integration/test_joint_telemetry_history.py tests/integration/test_live_gui_runtime_layout.py -q --tb=short --disable-warnings
```

Observed: **403 passed, 12 warnings**, 222.62 seconds. This process started
before the final custom-root and marker-failure tests were added; a later
rerun may collect additional cases. The final affected paths were checked
again in the focused commands below.

### Final preservation and telemetry checks

```bash
.venv/bin/pytest tests/unit/test_agent_artifact_archive.py tests/integration/test_all_agent_loop_archives.py tests/integration/test_loop_artifact_api.py tests/integration/test_joint_telemetry_history.py tests/unit/test_lerobot_joint_telemetry.py -q --tb=short --disable-warnings
.venv/bin/pytest tests/unit/test_lerobot_bridge.py -q -k 'action_log or joint_telemetry or rollout' --tb=short --disable-warnings
node --test tests/js/loop_artifact_history.test.cjs tests/js/omx_telemetry_history.test.cjs
node --check web/static/runtime_ide.js
node --check web/static/planning.js
git diff --check
```

Observed: **75 passed, 10 warnings**; **27 passed, 213 deselected**;
**7 JavaScript tests passed**; syntax and whitespace checks passed.

| Verified behavior | Test evidence |
|---|---|
| Loops and repeated invocation do not replace saved bytes | Two loops plus retry, mutable producer file, source deletion, disk reload |
| All ten agents enter the archive boundary | Actual entrypoints, two loop identities, provider access stopped by a non-actuating dependency boundary |
| Failed/cancelled calls retain evidence | Tool export followed by exception/cancellation; worker result arriving after cancellation |
| In-flight evidence is not prematurely complete | Pending-tool accounting and persisted stream session status |
| Large files are not merely left as pointers | 51 MiB snapshot test |
| Storage errors do not change scientific result or replay work | Invalid root, input-write failure, malformed prior error metadata, locator-write failure |
| Safe path and independent-root handling | Traversal/symlink rejection, configured separate roots, selected bridge/API log resolution |
| Runtime postprocessing keeps ownership | Analysis/BO derived paths and pre-increment Guardian loop events |
| Old-loop inspection does not use current live data | Existing filtered artifact API and saved-file rendering tests |
| Charts can recover saved motor history | Full-history reconnect tests; independent stream tracking finalization |

### Broader LeRobot failures

An earlier expanded regression selection returned **696 passed, 7 failed**.
All failures were in `tests/unit/test_lerobot_bridge.py`:

| Test | Observed mismatch |
|---|---|
| `test_live_teleoperate_blocks_missing_saved_realsense_camera_before_process_start` | Missing `active_camera_lease` response key |
| `test_pi05_live_train_uses_dedicated_hf_cache` | Training start `ok=False` |
| `test_vla_live_train_uses_standard_data_pipeline_env` | Training start `ok=False` |
| `test_pi05_live_train_augments_missing_quantile_stats` | Training start `ok=False` |
| `test_train_progress_does_not_inflate_step_from_sample_count` | 1031 observed vs 1000 expected |
| `test_train_dataset_mix_defaults_are_sim2real_balanced_for_all_policies` | Additional `source_selection` data |
| `test_isaac_lab_mimic_and_rl_runner_endpoints_generate_training_sources` | Zero pose bounds vs previous expected extents |

An isolated comparison process restored the previous bodies of
`_omx_action_log_env_overrides`, `_omx_action_log_dir`, and
`_rollout_joint_telemetry_contract` **in memory only**, removing the new
binding/resolution/finalization calls. It also replaced ToolRegistry's archive
recorder with a no-op. Running the seven named tests again returned **7 failed**
with the same assertion differences, in 4.95 seconds. No files were reverted.
This supports independence from those archive hooks; it is not a diagnosis
of the underlying training/teleop/Isaac problems or a clean-commit A/B test.

### Documentation governance

```bash
.venv/bin/python scripts/validate_documentation.py
```

The full manifest validator reported existing defects in:

- `docs/device_bridges/windows_pyautogui_bridge.md`: 26 missing metadata,
  required-section, and figure defects.
- `docs/superpowers/specs/2026-08-24-plc-safety-bridge-design.md`: missing
  leading YAML front matter.

Both files were byte-equal to `git show HEAD:<path>` when checked. Neither was
changed for this feature. The archival Reference and edited navigation,
Runtime IDE, and LeRobot documents passed individual `validate_document`
checks; the evidence report is included in the final validation pass.

## Limitations and Known Gaps

### Commit-scope verification

Before the requested publication, only the archive/history/grasp-evidence
changes were staged; unrelated test-mode, teleop handoff, printer, and UTM
changes remained in the working tree. The staged tree was exported with
`git checkout-index` into an isolated temporary directory and tested there.
The preservation/telemetry selection above, with
`tests/unit/test_manipulation_runtime_view.py` and
`tests/unit/test_tool_registry.py` added, returned **84 passed**. The selected
LeRobot rollout checks returned **27 passed**, and JavaScript tests returned
**7 passed**. This verifies the commit contents without relying on the
excluded working-tree changes.

The exported tree has no `.git` directory, so full documentation validation
there additionally flags CHANGELOG's existing `.git` source reference. This
is an export-environment difference, not a missing tracked document.

These tests prove software behavior within the fixtures, not a completed
physical closed loop. The ten-agent test proves archive wiring even when
an agent fails before its provider boundary; it does not prove successful
scientific output from each agent. JavaScript VM tests do not replace a full
browser interaction audit. Process crash, power loss, disk quota exhaustion,
and cross-machine backup were not exhaustively exercised.

## Related Documents

- [Current storage and API contract](../loop_artifact_archiving.md)
- [Documentation standard](../../standards/documentation_standard.md)
