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
- During the 5-cycle closed-loop test series, BO recommendations must not change `cell_size_mm`; the saved/operator-selected unit-cell size remains fixed across cycles.
- The loop must not freeze the entire first specimen as the next-cycle constraint set. Only static/operator settings are carried forward. Shape variables (`relative_density`, `wall_thickness_mm`, `orientation_deg`, `anisotropy_ratio`, `tpms_thickness`, defect fields, and estimated scores) are regenerated or BO-recommended each cycle.
- BO must use current/prior evaluation points as already-seen candidates, so the next DesignAgent handoff visibly changes the TPMS shape signature while keeping the operator-selected unit-cell size.
- During cycle 2 and later in a test-mode closed-loop series, generated STL cap skins are disabled (`top_cap_enabled=false`, `bottom_cap_enabled=false`, `skin_thickness_mm=0.0`). CAE still applies top/bottom platens internally and shows the result as a contour artifact in the Live GUI chat.
- In Live GUI "테스트 모드" handoff, Specimen Making Agent asks for the printer path:
  - `virtual_bridge`: run real active-slicer preparation, then use virtual printer communication only.
  - `installed_printer`: run real active-slicer preparation, then perform real selected-printer read-only communication testing when connection info exists.
  - `physical_print`: run real active-slicer preparation, then upload/start the test-generated specimen on the selected physical printer.
- Live GUI also accepts one-shot commands: `테스트 모드, 가상 브릿지`, `테스트 모드, 설치 프린터`, and `테스트 모드, 실제 출력`. These set `printer_test_path` during orchestration so the workflow proceeds without a second Specimen Making Agent path prompt.
- The `테스트 모드, 실제 출력` route returns the GUI request immediately and continues the long active-graph Design/Specimen/upload-start work in the background; progress is reflected through planning events/session refresh.
- `physical_print` uses the saved 3DP GUI cap profile. The default is bottom-only: `bottom_cap_enabled=true`, `top_cap_enabled=false`, `top_bottom_cap=true`, and `skin_thickness_mm=0.8`; disabling both cap options sets `top_bottom_cap=false`, clears `require_flat_compression_faces`, and uses `skin_thickness_mm=0.0` for bare TPMS gyroid specimens.
- Test mode must not upload, start print, or eject on real hardware unless `physical_print` is explicitly selected and the live upload/start gates are enabled.
- Even in virtual mode, the GUI should show slicer settings, G-code/3MF output path, endpoint shape, and step trace so the boundary immediately before real printer action can be inspected.
- Installed-printer test handoff may perform read-only selected-printer status/storage/video probes, but upload/start remain blocked unless `physical_print` is selected.
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
