# Test Mode

Supported run modes:
- `test`: full dry-run with mock tools
- `replay`: replays previous event trace
- `fault-injection`: injects configured fault at target stage

All device-facing actions in the current implementation are simulator-backed by default.

Printer behavior in test mode:
- The full workflow can reach Specimen Making Agent without real printer hardware.
- `printer.prepare` defaults to a virtual PrusaLink-shaped bridge when configured with `virtual_prusalink_dry_run: true`.
- Live GUI test-mode design defaults to an FDM-printable gyroid TPMS with the 3DP GUI saved `test_unit_cell_size_mm`, defaulting to `cell_size_mm=10.0`, unless the operator explicitly provides another valid value.
- Bare TPMS adhesion is handled by operator-controlled first-layer and bed-temperature options, not by forcing skins/caps. Defaults are `first_layer_height_mm=0.2`, `slow_first_layer_enabled=true`, `first_layer_speed_mm_s=10.0`, `bed_temperature_c=60.0`, and `first_layer_bed_temperature_c=60.0`. PrusaSlicer receives `--layer-height`, `--first-layer-height`, `--bed-temperature`, `--first-layer-bed-temperature`, and, when enabled, `--first-layer-speed`; disabling the speed option leaves PrusaSlicer profile/default speed unchanged.
- The 3DP GUI `Test Options` section supplies saved `specimen_size_mm` / `max_specimen_size_mm` and `cell_size_mm` defaults to Live GUI test-mode handoffs through `memory/prusa_print_profile.json`, so the operator can change test specimen size and unit-cell size without editing chat text.
- In Live GUI "테스트 모드" handoff, Specimen Making Agent asks for the printer path:
  - `virtual_bridge`: run real PrusaSlicer slicing, then use virtual PrusaLink communication only.
  - `installed_printer`: run real PrusaSlicer slicing, then perform real PrusaLink read-only communication testing when connection info exists.
  - `physical_print`: run real PrusaSlicer slicing, then upload/start the test-generated specimen on the real printer.
- Live GUI also accepts one-shot commands: `테스트 모드, 가상 브릿지`, `테스트 모드, 설치 프린터`, and `테스트 모드, 실제 출력`. These set `printer_test_path` during orchestration so the workflow proceeds without a second Specimen Making Agent path prompt.
- The `테스트 모드, 실제 출력` route returns the GUI request immediately and continues the long DesignAgent -> Specimen Making Agent -> PrusaLink upload/start work in the background; progress is reflected through planning events/session refresh.
- `physical_print` uses the saved 3DP GUI cap profile. The default is bottom-only: `bottom_cap_enabled=true`, `top_cap_enabled=false`, `top_bottom_cap=true`, and `skin_thickness_mm=0.8`; disabling both cap options sets `top_bottom_cap=false`, clears `require_flat_compression_faces`, and uses `skin_thickness_mm=0.0` for bare TPMS gyroid specimens.
- Test mode must not upload, start print, or eject on real hardware unless `physical_print` is explicitly selected and the live upload/start gates are enabled.
- Even in virtual mode, the GUI should show slicer settings, G-code output path, endpoint shape, and step trace so the boundary immediately before real printer action can be inspected.
- Installed-printer test handoff may perform read-only PrusaLink status/storage probes, but upload/start remain blocked unless `physical_print` is selected.
- The Prusa MK4S live bridge has been validated with Digest auth and USB storage; missing/unavailable USB storage must appear as `PRINTER_STORAGE_UNAVAILABLE`, not as a generic handoff failure.

LeRobot / ROBOTIS behavior in test mode:
- `/lerobot` opens without LeRobot hardware or LeRobot Python packages installed.
- `/api/lerobot/ports` returns deterministic fake robot/teleop ports from `configs/lerobot.yaml`.
- `lerobot.teleoperate.*`, `lerobot.record.*`, `lerobot.train.*`, and `lerobot.rollout.*` create deterministic in-process fake sessions with command previews and step traces.
- `ManipulationAgent` can call `lerobot.rollout.start` in test mode when the experiment spec requests `manipulation_strategy: lerobot_policy`.
- Test mode must not move a robot. It validates profile selection, payload shape, command preview, event trace, and SARM integration only.
- Live mode remains gated by the selected LeRobot profile and must fail closed unless explicit live gates are enabled.
- The LeRobot GUI path browser, policy list, and dataset visualization endpoints are usable in test mode.
- Dataset visualization in test mode reads local metadata/media if present and otherwise returns an empty but valid visualization payload.
