# Test Mode

Supported run modes:
- `test`: full dry-run with mock tools
- `replay`: replays previous event trace
- `fault-injection`: injects configured fault at target stage

All device-facing actions in the current implementation are simulator-backed by default.

Analysis / CAE behavior in test mode:
- Analysis Agent parses real/saved UTM data when provided.
- If no UTM curve/file is provided, Analysis Agent generates deterministic synthetic UTM data from specimen size, relative density, and wall thickness.
- Analysis Agent also calls `cae.run_static_analysis` when registered.
- The CAE bridge uses deterministic equivalent bottom-fixed/top-cyclic analysis in test mode, so no external CalculiX/Gmsh installation is required.
- The resulting `cae_metrics.structural_score` is blended into `analysis.objective_score`, and `analysis.closed_loop_sources` records `cae.run_static_analysis`.
- This is closed-loop simulation data, not a claim of physical UTM validation.

Printer behavior in test mode:
- The full workflow can reach Specimen Making Agent without real printer hardware.
- `printer.prepare` uses the selected printer profile through `PrinterDeviceBridgeManager`; the default physical profile is Bambu Lab X2D, and virtual mode uses the same printer-tool contract without touching hardware.
- Live GUI test-mode design defaults to an FDM-printable gyroid TPMS with the 3DP GUI saved `test_unit_cell_size_mm`, defaulting to `cell_size_mm=10.0`, unless the operator explicitly provides another valid value.
- Bare TPMS adhesion is handled by operator-controlled first-layer and bed-temperature options, not by forcing skins/caps. Defaults are `first_layer_height_mm=0.2`, `slow_first_layer_enabled=true`, `first_layer_speed_mm_s=10.0`, `bed_temperature_c=60.0`, and `first_layer_bed_temperature_c=60.0`. The active slicer receives equivalent layer-height, first-layer-height, bed-temperature, first-layer-bed-temperature, and optional first-layer-speed settings. Bambu profiles use the Bambu slicer/bridge path; Prusa profiles use PrusaSlicer.
- The 3DP GUI `Test Options` section supplies saved `specimen_size_mm` / `max_specimen_size_mm` and `cell_size_mm` defaults to Live GUI test-mode handoffs. The current compatibility file is `memory/prusa_print_profile.json`, but the semantic owner is the active 3DP print profile, not a forced Prusa path.
- The default closed-loop test series runs 20 cycles. Its two BO variables are `cell_size_mm` and `relative_density`: cell size is selected only from `{5.0, 6.0, 7.5, 10.0}` mm under `a=L/N`, while relative density is continuous on `[0.20, 0.48]` and normalized before GP fitting.
- Cycles 1-8 collect the deterministic Latin Hypercube initialization. Cycles 9-20 use BoTorch `SingleTaskGP` with ARD Matérn 5/2 covariance and Expected Improvement when all eight initialization observations were accepted.
- The LHS card may display both design inputs. Once acquisition starts, the BO posterior/EI graph displays only scalar score, uncertainty, measured scores, EI, and an anonymous normalized search coordinate; it never displays input names, input values, strata, parameter slices, or parameter tooltips.
- The loop must not freeze the entire first specimen as the next-cycle constraint set. Only static/operator settings are carried forward. Shape variables (`relative_density`, `wall_thickness_mm`, `orientation_deg`, `anisotropy_ratio`, `tpms_thickness`, defect fields, and estimated scores) are regenerated or BO-recommended each cycle.
- BO must use current/prior evaluation points as already-seen candidates, so the next DesignAgent handoff changes the TPMS shape signature without repeating an evaluated `(cell_size_mm, relative_density)` pair.
- During every cycle, including the first LHS specimen, a test-mode closed-loop series disables generated STL cap skins (`top_cap_enabled=false`, `bottom_cap_enabled=false`, `skin_thickness_mm=0.0`). CAE still applies top/bottom platens internally and shows the result as a contour artifact in the Live GUI chat. Saved physical-print profile defaults remain independently operator-controlled outside this closed-loop design contract.
- In Live GUI "테스트 모드" handoff, Specimen Making Agent asks for the printer path:
  - `virtual_bridge`: run real active-slicer preparation, then use virtual printer communication only.
  - `installed_printer`: run real active-slicer preparation, upload/start the generated sliced artifact on the selected physical printer, require fresh progress-panel observation, stop immediately, then run the standalone autoejection artifact derived from the same sliced artifact. This is the "actual printer route validation" path.
  - `physical_print`: run real active-slicer preparation, patch the generated `.gcode.3mf` into `.autoeject.gcode.3mf`, then upload/start the test-generated specimen on the selected physical printer. This path keeps the print body and appends the autoejection tail to the print job.
- Live GUI also accepts one-shot commands: `테스트 모드, 가상 브릿지`, `테스트 모드, 설치 프린터`, `테스트 모드, 실제 프린터`, and `테스트 모드, 실제 출력`. These set `printer_test_path` during orchestration so the workflow proceeds without a second Specimen Making Agent path prompt.
- The `테스트 모드, 실제 출력` route returns the GUI request immediately and continues the long active-graph Design/Specimen/upload-start work in the background; progress is reflected through planning events/session refresh.
- `physical_print` uses the saved 3DP GUI cap profile. The default is bottom-only: `bottom_cap_enabled=true`, `top_cap_enabled=false`, `top_bottom_cap=true`, and `skin_thickness_mm=0.8`; disabling both cap options sets `top_bottom_cap=false`, clears `require_flat_compression_faces`, and uses `skin_thickness_mm=0.0` for bare TPMS gyroid specimens.
- Test mode must not upload, start print, or eject on real hardware unless `installed_printer` or `physical_print` is explicitly selected and the live upload/start gates are enabled. `installed_printer` must start the actual sliced `.gcode.3mf`, require fresh MQTT progress evidence (`RUNNING`/preparing state with progress panel fields), stop that print immediately, and then run the validated standalone autoejection artifact. `physical_print` must set physical print intent and preserve the print body.
- Both physical paths enable Bambu native autoejection by default. `installed_printer` uses the actual sliced artifact as the source for extrusion/object bounds, but does not publish a print-body-removed ejection-only project file unless that path is explicitly requested by a developer/test fixture. `physical_print` uses the patched print artifact itself and preserves the print body. Both paths require extrusion-move object bounds from the actual sliced artifact and use the configured push height rule (`max(10 mm absolute Z, object max Z - 15 mm)` by default).
- Even in virtual mode, the GUI should show slicer settings, G-code/3MF output path, endpoint shape, and step trace so the boundary immediately before real printer action can be inspected.
- After the printer step, both physical test paths continue through the same tail: printer autoejection handoff, Vision active-cam confirmation, Manipulation rollout, Vision completion verification, Lab Equipment, Analysis, Knowledge, BO, and Guardian.
- The Bambu X2D path is the default physical profile and exposes MQTT/FTPS/video evidence. The Prusa MK4S bridge remains a validated explicit profile; missing/unavailable Prusa USB storage must appear as `PRINTER_STORAGE_UNAVAILABLE`, not as a generic handoff failure.

LeRobot / ROBOTIS behavior in test mode:
- `/lerobot` opens without LeRobot hardware or LeRobot Python packages installed.
- `/api/lerobot/ports` returns deterministic fake robot/teleop ports from `configs/lerobot.yaml`.
- `lerobot.teleoperate.*`, `lerobot.record.*`, `lerobot.train.*`, and `lerobot.rollout.*` create deterministic in-process fake sessions with command previews and step traces.
- `ManipulationAgent` can call `lerobot.rollout.start` in test mode when the experiment spec requests `manipulation_strategy: lerobot_policy`.
- Test mode must not move a robot. It validates profile selection, payload shape, command preview, event trace, and SARM integration only.
- Live mode remains gated by the selected LeRobot profile and must fail closed unless explicit live gates are enabled.
- The LeRobot GUI path browser, policy list, and dataset visualization endpoints are usable in test mode.
- Dataset visualization in test mode reads local metadata/media if present and otherwise returns an empty but valid visualization payload.
