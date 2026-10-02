# X2D pre-ejection nozzle cleanup

The operator confirmed the supervised first-layer sequence test on 2026-09-18
and approved this sequence for regular printing. The production X2D artifact
patcher applies it to normal full-height specimens; the one-layer truncation
remains exclusive to the explicitly invoked rehearsal script. This confirmation
does not claim full-height specimen release was tested by the one-layer trial.

The previous X2D patch inserted bed cooling and ejection before the native AMS unload sequence. The nozzle remained hot during that wait and sweep. This change preserves native unloading/wiping and moves the ejection tail after it, before reduced Z motor current and final motor shutdown.

## Order

1. Finish printing and retain the native X2D Z-clearance moves.
2. Run the existing two AMS unload blocks and `G150.1` commands exactly once, followed by native `G150.3` parking.
3. Wait with `M109 S140 A`, then retain native `M104 S0 T0` and `M104 S0 T1`.
4. Wait for the existing bed-release target (`M190 R40` by default).
5. Perform the original ejection sweep, with unchanged specimen-derived coordinates, height and speeds.
6. Restore bed target OFF, raise to the safe approach height, park using `G150.3`, then continue the native final shutdown.

The 140 C command is present in the [official X2D start profile](https://github.com/bambulab/BambuStudio/blob/master/resources/profiles/BBL/machine/Bambu%20Lab%20X2D%200.4%20nozzle%20template%20machine_start_gcode.json). The operator validated its use in this sequence; it is not a guarantee of no residue, a safe-to-touch temperature, or proof that every firmware version waits identically. Revalidate on a firmware or machine change. The temperature wait is followed by heater OFF; it is not an off-only cooldown.

Only the recognized native X2D end structure is reordered. Changed/missing unload or heater-off blocks, conditional unloading, premature motor disable, or already-patched old X2D eject-before-unload files fail validation. Other machine profiles and no-print standalone routines retain their existing behavior. There is no additional extrusion, forced tool selection, or large custom retraction.

## Installed-printer test and transfer failures

The installed-printer test removes the print body and native end block. It keeps
the existing ejection-only path, without adding AMS unloading or nozzle heating.
An escaped `machine_end_gcode` template inside a slicer configuration comment is
not an executable X2D end block; only the standalone marker selects that path.

Any slicing, ejection-patch, local plate-validation, or integrity failure remains
blocking for both FTPS and HTTP transfer. HTTP availability may recover a transfer
failure, but must never clear an artifact failure or send the original full-print
file in place of a rejected ejection-only file.

## Supervised first-layer path rehearsal

`PYTHONPATH=. .venv/bin/python scripts/prepare_x2d_first_layer_path_trial.py ORIGINAL.gcode.3mf`

This is a file-generation command only. It builds and validates the complete specimen's revised end/ejection path, then retains only the original specimen's first printing layer and that entire end sequence. Startup and first-layer moves come from the original slice, not a separately designed test plate. It writes a new archive and recalculates its plate MD5 without changing the original.

For a planned 30 × 30 × 30 mm specimen, the rehearsal prints only the original first 0.2 mm layer but keeps the full-height specimen's ejection path. The report explicitly distinguishes actual printed height from planned geometry. It does not claim the thin layer will detach at the normal sweep height: the operator removes that layer after all motion ends. This verifies sequencing and leakage behavior, not full-height mechanical release. The usual production object-height validator is not relaxed.

Changes on disk and generated rehearsal artifacts do not modify a job already downloaded by the printer. Publishing requires the existing supervised printer-start gates; the generation script never publishes. The running experiment server is not restarted for the rehearsal.
