<!-- atr-doc
doc_type: reference
subtype: runtime
status: active
authority: descriptive
audience:
  - researcher
  - operator
  - developer
  - integrator
scope:
  - bambu_x2d
  - printer_provider
  - autoejection
summary: Current Bambu Lab X2D provider contract for slicing, probing, transfer, telemetry, video, guarded start, and artifact-based autoejection.
source_of_truth:
  - device_bridges/printer_fleet/bridge.py
  - device_bridges/printer_fleet/providers/bambu_autoejection.py
  - configs/devices.yaml
  - mcp_tools/printer_tools.py
  - app/main.py
  - utils/specimen_placement.py
  - utils/bambu_material_priority.py
  - web/static/printer.js
last_verified: 2026-09-17
verified_against: print-start profile round-trip and G-code validation; no physical printing
related_docs:
  - docs/device_bridges/printer_fleet_bridge.md
  - docs/hardware/bambulab_x2d_device_bridge_runtime_guideline.md
  - docs/agents/specimen_agent.md
supersedes: []
-->

# Bambu Lab X2D Bridge Reference

## Status at a Glance

| At a glance | Details |
|---|---|
| Purpose | Slicing, artifact transfer, telemetry and guarded autoejection |
| Connects | Specimen / 3D workspace ↔ Bambu provider |
| Effect | Upload, heating and motion are possible through gated commands |
| Implementation | [Bambu implementation](../../device_bridges/printer_fleet/bridge.py) · [Requirements](../../device_bridges/printer_fleet/providers/bambu-requirements.txt) |
| Verification | [Recorded scope and evidence](#current-verification) · 2026-09-06 |

## Summary

The Bambu X2D provider turns a selected fabrication request into sliced and
identity-tracked artifacts, connection/readiness evidence, and—only on an
allowed live path—transfer and start commands. It also provides a pure-file
native G-code autoejection transformer whose output is inert until published.

## Scope

Included: Bambu Studio runner, connection/fleet/autoejection/bed-clear memory,
TLS probe, MQTT report and command clients, FTPS probing/upload, LAN video,
artifact HTTP route, start gates, and deterministic G-code patching. Excluded:
device firmware internals and claims for untested printer/firmware variants.

## Read-only live monitoring

Health/status observations share a process-local MQTT subscription per printer
connection. Incoming `print` deltas are merged under a lock, and readers receive
independent copies with `received_at` and `cache_age_sec`. Only the read-only
`pushall` request is published by this monitor; print/start/ejection commands and
their post-publish verification retain the original transport path.

Disconnected telemetry or reports older than 15 seconds are unavailable, not
healthy. Reconnection clears prior report fields; access-code/topic changes
replace the subscription. A periodic 10-second snapshot request refreshes quiet
printers. Unused subscriptions close after 120 seconds, and registry size is
bounded to four connections. Test mode never starts these subscriptions.

Camera snapshots and MJPEG viewers share one decoder per source (960-pixel width,
15 fps). A single latest-JPEG slot replaces per-viewer queues: slow viewers skip
frames instead of accumulating latency. Frame waiting and camera readiness probes
run outside the HTTP event loop. Snapshots must be at most two seconds old; failed
sources do not serve old frames as live. Initial connection/keyframe waiting has
a 60-second minimum budget; subsequent frame stalls have a 15-second budget.
This does not extend the two-second freshness limit. Decoders close after 15 seconds without
consumer requests, on source failure, or on server shutdown. Registries are local
to each server process, not shared across multiple worker processes.

SPC telemetry refreshes independently of Guardian/graph/detail requests, at most
once per two seconds per visible Live GUI. Responses from a previous run are
discarded. These changes affect observation latency only, not agent completion
criteria or printer permissions. Backend changes require a server restart;
browser JavaScript changes require a page reload.

## Print Start & Early Layers

Open **3D Printer Workspace → Print Defaults → Print Start & Early Layers**.
Existing first-layer height, speed override, bed temperature, bed leveling and
flow calibration controls now live together here, with no duplicate controls.
General layer height and bed temperature remain in the general defaults area.

### Current operator-tuned profile (2026-09-17)

These saved settings were cross-checked against `memory/prusa_print_profile.json`
and `GET /api/printer/profile` for `bambulab_x2d_lab_01`. They document the
operator's tuning, **not a change to code defaults or a universal validated
preset**. Disabled controls retain their numeric values without applying them.

| Print option / profile key | Current saved value |
|---|---|
| Start-point prime / `start_point_prime_enabled`, `start_point_prime_mm` | **On; 1.8 mm of filament** |
| Layers 2–5 extrusion cap / `early_layer_speed_limit_enabled`, `early_layer_speed_mm_s` | **Off**; stored 50 mm/s is inactive |
| Layers 1–5 Z cap / `early_layer_z_speed_limit_enabled`, `early_layer_z_speed_mm_s` | **Off**; stored 5 mm/s is inactive |
| Material / printer / nozzle | PLA / Bambu Lab X2D / 0.4 mm |
| Slicer profile hint | `0.2mm_quality` |
| Layer height / first-layer height | 0.2 mm / 0.2 mm |
| First-layer speed override | On; 10 mm/s |
| Bed temperature / first-layer bed temperature | 60°C / 60°C |
| Bed leveling / flow calibration | On / Off |
| Specimen placement | Custom; center X128 mm / Y58 mm |
| Skirt / top cap / bottom cap | Off / Off / Off |
| Combined top-bottom cap / skin thickness / flat-face requirement | Off / 0 mm / Off |
| Transfer storage / overwrite / maximum print time | FTPS / On / 180 min |
| Immediate live start / profile-level ejection permission | Off / Off |
| Test fallback specimen size / unit-cell size | 30 × 30 × 30 mm / 10 mm |

The test fallback cell size is not the LHS/BO search range. Profile-level start
and ejection options are distinct from separate bridge and Guardian gates;
this snapshot does not assert that autoejection is globally disabled or
authorize a device action.

For newly sliced supported files, this profile requests `G1 E1.8 F60` at the
first object point. The first-layer speed override remains active; layers 2–5
and early Z motion receive no **additional** AX4LAB speed cap. Slicer and machine
limits still apply. Existing G-code and active prints are not rewritten by
saving these options. This update read settings only: no G-code generation,
upload, or new physical-print validation of the tuned profile was performed.

### Control semantics

Start-point prime accepts a finite, nonnegative filament length with no software
upper cap; zero disables extra extrusion. It is not Z height or deposited line
length. The accepted ranges for the optional speed caps are 0.1–1000 mm/s for
layers 2–5 extrusion and 0.1–20 mm/s for layers 1–5 Z motion. Both caps are
currently disabled, as recorded above.

The speed-cap upper limits match the current X2D machine profile (`machine_max_speed_x/y=1000`,
`machine_max_speed_z=20`, in mm/s), not a promise of achieved physical speed. The first layer
retains its configured extrusion speed. Slower moves are not accelerated. Feed
is restored after every capped move; XY-only travel, retraction and layer 6 onward
retain slicer feeds unless the move also includes Z within the capped layers.
G-code `F` uses mm/min.

Negative and nonfinite priming values are rejected. Increasing this filament
length can cause a start-point blob or
over-extrusion. Saving a larger value affects only subsequently generated files.

Each of the three independent checkboxes sits immediately above its numeric
input, followed by a concise English `Limit` hint. All numeric inputs remain
editable and saved while unchecked; unchecking controls application, not editing.
The layers 2–5 toggle is independent of the first-layer speed override and Z
toggle. A mixed XYZ move can still be limited by either enabled cap. Profiles
without the new toggle fields retain the previous enabled behavior. Save and
re-slice the original model to apply either change; already limited G-code
cannot be used to recover original slicer speeds, and active prints are untouched.

For the recognized X2D `G130` nozzle-load-line block, AX4LAB removes the front
line/macro and its dependent motion while retaining preparation commands. It
adds one `G1 E<prime_mm> F60` (currently `E1.8`) at the first object point after travel, descent and
unretraction, then restores feed before object extrusion. The prime requires
absolute XYZ, millimetres, relative E, and first-point Z above zero and at most
0.4 mm. Unsupported priming contexts are rejected rather than guessed. This is
not a complete reverse-engineering of firmware `G130`, and does not create a
skirt, brim or substitute purge line.

### Save and apply

1. Edit the grouped controls and **Save Print Defaults**. Each checkbox is
   directly above its corresponding input.
2. `POST /api/printer/profile` validates and stores the values in
   `memory/prusa_print_profile.json`; `GET` returns them. This historical filename
   is shared profile storage, not a restriction to the Prusa provider.
3. Re-slice the **original STL/3MF**. The Bambu runner snapshots the three new
   settings at slice entry. Saving during slicing affects the next slice. These
   operator-owned postprocessing values are not overridden by experiment/LLM
   fields. Existing first-layer settings retain their experiment-override behavior;
   explicit custom slicer presets retain their own first-layer settings.
4. Inspect `print_start_settings` in the slice result and the generated G-code.
   `.gcode.3mf` checksums are regenerated. Normal export and recovered CLI-output
   packaging use the same settings. An artifact already patched with different
   early-layer caps must be re-sliced, not cumulatively patched.

Profiles missing keys receive code fallbacks, not necessarily the current
operator-tuned values. Without a saved
profile file, `devices.printer.bambu.slicer.start_point_prime_mm` remains a legacy
priming fallback. These controls apply to **Bambu slicing**, including test and
actual-print paths using that runner; they do not change the Prusa slicer or
virtual paths that do not generate Bambu G-code.

Saving or generating G-code does **not** upload, publish MQTT commands, start a
print or modify an active print. Existing artifacts remain unchanged. G-code
checks are not proof of physical adhesion or print success: those still require
operator-supervised hardware validation.

## Source of Truth

`device_bridges/printer_fleet/bridge.py` owns the provider and clients;
`device_bridges/printer_fleet/providers/bambu_autoejection.py` owns pure transformation and validation;
`devices.printer.bambu` and `devices.printer.autoejection` own defaults.

## Actual Role

The provider resolves connection and slicer configuration, produces or accepts
a sliced artifact, computes/retains identity, probes configured paths, exposes
telemetry/video, and constructs guarded publish operations. It does not infer
bed clearance or autoejection success without configured evidence.

## System Position and Agent Handoffs

![Bambu X2D system position](assets/figures/bambu_x2d_01_system_handoffs.svg)

**Figure Bambu X2D-1.** Specimen work enters through Printer Fleet; Bambu
artifacts and telemetry return to Specimen, Vision/Manipulation proof, Guardian,
and the operator. Dashed live paths require explicit gates. This is inspection,
not physical validation.

| Upstream | Required context | Output/consumer |
|---|---|---|
| Printer Fleet/Specimen | selected Bambu profile, geometry/slice request | sliced artifact and manufacturing result |
| Operator | connection, profile, start/proof action | redacted readiness or guarded result |
| Vision/Manipulation | pre/post-eject evidence or recovery capability | bed-clear/autoejection status |

## Inputs, Commands, and Outputs

Inputs include printer/profile ID, source artifact or model path, slicer hints,
connection memory, source/patched hash expectations, start intent, and proof
references. Outputs include `.gcode` or `.gcode.3mf`, slice metadata, probe
results, command drafts, MQTT/video state, bed-clear records, and structured
blockers.

## Internal Execution

![Bambu X2D execution boundary](assets/figures/bambu_x2d_02_execution_effect_boundary.svg)

**Figure Bambu X2D-2.** Slicing and G-code patching remain local artifact
effects; FTPS/MQTT publish is the first printer effect and is separated from
prestart, start, and proof gates. Evidence scope is implementation inspection.

| Phase | Main checks | Effect |
|---|---|---|
| Slice/accept | executable, output, artifact existence and identity | local subprocess/files |
| Patch | object bounds, envelope, motion/feedrate/cooldown, schema marker | new local artifact only |
| Probe | host/path/TLS and provider readiness | bounded network reads |
| Draft/gate | selected profile, route, source/patched hashes, proof blockers | no start command |
| Publish/start | live allowance and complete gate | network command; physical possible |
| Verify | MQTT/video/job/bed-clear/autoejection evidence | status/proof record |

## API Surface

Functional `/api/printer/*` groups include Bambu slicing and autoejection
patch/sweep/proof/completion-audit, upload-path probe, HTTP artifact route,
prestart check, start-command draft, start gate, start publish, video status/
frame/stream, bed clear, and shared connection/profile/status endpoints.

## Tools and Registry Integration

Bambu is selected behind `printer.prepare`; it is not registered as an
independent graph tool. `PrinterDeviceBridgeManager` owns provider methods and
the API uses the same manager. Pure patch endpoints call the transformer but
cannot publish by themselves.

## Connections and Protocols

![Bambu X2D API and connections](assets/figures/bambu_x2d_03_api_connection_architecture.svg)

**Figure Bambu X2D-3.** API/tool requests pass through provider configuration
to Bambu Studio, MQTT TLS, FTPS, artifact HTTP routing, and LAN video; command
and evidence returns remain distinct. UI/model bypass is prohibited.

- Bambu Studio wrapper: bounded local slicing subprocess;
- MQTT over TLS: report/request topics and print-control/project commands;
- FTPS: storage and upload-path probes plus file transfer;
- HTTP artifact route: makes the exact local artifact fetchable by a guarded
  workflow;
- LAN video: status, snapshots, and MJPEG proxy paths.

## Configuration and Secrets

`configs/devices.yaml` defines ports, topic templates, timeouts, slicer wrapper,
video, capabilities, and autoejection requirements. Mutable files include
`memory/bambu_connection.json`, `memory/bambu_autoejection.json`, and
`memory/bambu_bed_clear_evidence.json`. Access codes and serial values may be
stored in connection memory but are redacted from documents and responses.

## State, Events, Artifacts, and Evidence

Key evidence is source/patched SHA-256, slicer output, normalized object bounds,
patch metadata, path-probe results, MQTT sequence/status, video observations,
pre/post-eject references, and bed-clear records. An HTTP URL is routing
metadata, not proof that the printer fetched or ran the artifact.

## Runtime Modes and Fallbacks

Test behavior can create deterministic artifacts and avoid real publish.
Network-in-test promotion must be explicit. Live behavior requires configured
connection and live gates. Bambu failure does not automatically select Prusa;
robot pickoff recovery is separately configured and false by default.

## Safety, Approval, and Effect Boundary

Pure G-code patching never talks to a printer. Physical possibility begins at
FTPS upload, MQTT publish/control, or a printer fetch/start command. The start
path requires artifact identity, route readiness, provider/profile match,
prestart/start gates, and configured proof. Autoejection additionally requires
the verified routine and pre/post vision conditions declared by configuration.

## Errors, Timeouts, and Recovery

Invalid motion/envelope/cooldown, identity mismatch, unavailable path, missing
credential, and proof blockers fail closed. After publish timeout, query MQTT
report/job state and reconcile artifact identity before retry; network timeout
is not evidence of no effect. A failed patch is safe to regenerate because it
has no device effect.

## Operator and GUI Surfaces

The `/printer` workspace exposes fleet, connection, slicing, video, probe,
start-gate, autoejection, bed-clear, and proof views. Operators must distinguish
draft, gate-ready, published, observed-running, and proof-complete states.

## Current Verification

### Print-start workspace and generated artifacts (2026-09-17)

Validation covered profile persistence/API range rejection, zero-prime handling,
normal and recovered archive packaging, checksums, GUI save/reload and single
ownership of the relocated controls. Browser checks used isolated profile
storage and intercepted device endpoints: no printer requests were issued.

Earlier generated-artifact checks compared each patched artifact against its
own raw CLI G-code, including feed preservation and archive checksums. They do
not validate the current tuned profile by a new physical print; see the
[current operator-tuned profile](#current-operator-tuned-profile-2026-09-17).

Inspection covered provider/client/patcher code, current configuration, API
handlers, Bambu unit tests, autoejection tests, and the existing completion
audit contract. It does not establish continuous live reliability for X2D.

### Effective slicing settings and execution modes (2026-09-14)

The default CLI path resolves vendor preset `inherits` and `include` references
before exporting standalone machine, process, and filament settings. This
preserves the native X2D start/end programs and inherited process/material
values. Invalid inheritance blocks slicing. Explicit custom CLI profiles remain
operator-controlled.

Saved 3DP Print Defaults feed the default slicing path; experiment constraints
override saved values, and top-level experiment values override constraints.
Layer heights, bed temperatures, and the enabled first-layer speed setting are
applied to the exported profiles. The current PLA setup uses Textured PEI at
60°C, 0.2 mm layers, and **10 mm/s for both first-layer walls and infill**.
Outside the [early-layer caps](#print-start--early-layers), other speeds retain resolved vendor settings; there is no blanket 75% speed
multiplier. Existing no-skirt/brim/raft policy remains in place.

| Execution mode | Print body | Temperature-gated ejection wait | Device execution |
|---|---|---|---|
| Experiment / LIVE | Retained | Retained | Existing approved physical route |
| TEST / `physical_print` | Retained | Retained | Existing physical-print route |
| TEST / `installed_printer` | Omitted | Omitted | Existing ejection-only test route |
| TEST / `virtual_bridge` | Local preparation/preflight only | No physical wait | No upload or actuation |

Placement validation and bounds-derived autoejection are unchanged. The native
front test-line postprocessor recognizes the vendor closing marker and leaves
the source unchanged if the block cannot be safely delimited. Updated defaults
require re-slicing; they do not rewrite previously prepared artifacts.

Local STL generation, installed Bambu Studio slicing, patched G-code bodies,
cooldown commands, placement, and checksums were inspected without printer
communication. This is artifact/path verification, not a new physical print
validation. Regression coverage includes `test_bambu_slicer_profiles.py`,
`test_bambu_bridge.py`, and `test_test_mode_execution_profile_matrix.py`.

## Limitations and Known Gaps

### AMS material priority (2026-09-06)

In **3DP → AMS / Material Slots**, use ▲/▼ to reorder slots, then save.
Reordering enables priority; the checkbox can disable it without clearing the
saved order. Defaults are disabled, preserving existing explicit AMS/external
spool behavior. This setting is stored independently of Print Defaults at
`memory/bambu_material_priority.json` through
`GET/POST /api/printer/material-priority`. It is not an in-print spool-change rule.

When enabled, GUI start drafts and agent preparation use the same selection
logic: the first ranked slot with fresh MQTT presence evidence, a matching
material type, and no reported zero/invalid remaining amount. Unknown remaining
percentage alone is allowed when presence and material are known. Unlisted slots
are not an implicit fallback; absent, exhausted, or incompatible candidates are
skipped, and no compatible candidate blocks the start. Standard AMS IDs 0–3 and
tray IDs 0–3 are supported; other AMS types are not automatically mapped.

The actual local sliced plate must identify exactly one used filament and its
matching `filament_type`. Mapping has one entry per filament preset and selects
the actual used index—not a hardcoded five-entry vector. Multiple used materials,
missing evidence, or an artifact/material mismatch block publication. An E-free
motion program is exempt; genuine installed-printer ejection-only conversion
retains its existing flow. Virtual readiness does not read hardware, and start
selection differing between GUI draft and preparation blocks publication.

GUI HTTP-export URLs retain local artifact evidence. A printer-only
`cache/file.gcode.3mf` reference cannot prove its material and is blocked while
priority is enabled: use the GUI Slice/HTTP Artifact route. Agent preparation
with its local artifact supports the existing FTPS and HTTP paths. Selection is
rechecked after slicing; it does not trigger filament changes during a print.

Verification: `tests/unit/test_bambu_material_priority.py`,
`tests/integration/test_bambu_material_priority_api.py`, and
`tests/js/printer_material_priority.test.js` cover persistence, telemetry/order,
artifact binding, shared GUI/agent mapping, and non-actuating behavior.

### Operator-adjustable specimen placement (2026-09-06)

The 3D workspace Print Defaults exposes `specimen_placement`, shared with
controller initialization, Design/BO redesign handoffs, and Specimen Making.
Save defaults for subsequent requests; manual Slice/Prestart uses the current
form values. Existing run snapshots and already sliced files are not relocated.

| Mode | Meaning | Slicing behavior |
| --- | --- | --- |
| `auto` (legacy default) | Bambu's printable-area arrangement | Original `--arrange 1` path |
| `bed_center` | Physical bed center, X128/Y128 mm for X2D | Original STL + assembly translation, `--arrange 0` |
| `custom` | Operator-entered specimen center X/Y, in printer mm | Same explicit placement path |

The installed X2D profile's shared nozzle region is X20.5–256/Y0–256 mm,
so its automatic center can be X138.25/Y128, not the physical bed center.
Explicit placement reads the effective rectangular machine profile and checks
the **whole specimen bounds**, not only the center. The supported Bambu CLI
`--load-assemble-list` translates the original STL without editing it; `--center`
is not supported by the installed CLI. Explicit relocation of source 3MF
projects is blocked: use the original STL to preserve project settings.

Before accepting an explicitly positioned artifact, the bridge reads the sliced
G-code using the same object-bounds extractor as autoejection. It checks printable
bounds and center agreement within 0.5 mm. Missing evidence or mismatch blocks
preparation/prestart; it never silently reverts to automatic arrangement. Explicit
placement is X2D-only; other providers retain their existing `auto` behavior.
Normal print-cycle autoejection still follows the actual sliced specimen bounds.

The 3D GUI no longer exposes `Validate Left/Center/Right` or the three Physical
Proof Package `Run Standalone Eject` controls, including their click handlers.
The remaining ejection-test artifact handler fixes `mode=test` and
`start_immediately=false`. Preview validation, artifact generation, proof
templates, completion audit, and regular loop autoejection remain. This is a GUI
entry-point removal, not removal of the existing backend standalone API.

Regression coverage: `tests/unit/test_specimen_placement.py`,
`tests/integration/test_printer_placement_gui.py`, and
`tests/js/printer_placement.test.js`. Optional installed-CLI checks use
`ATR_TEST_REAL_SLICER=1`; they generate temporary files only, without upload,
MQTT publish, or printer actuation.

Bambu is the current configured default but lacks its own
`graph.metadata.device_bridges` entry. Optional transfer/video modes depend on
firmware/network behavior. Autoejection is disabled by default and remains
blocked without verified routine and evidence configuration.

## Related Documents

- [Printer Fleet](printer_fleet_bridge.md)
- [Bambu Runtime Guide](../hardware/bambulab_x2d_device_bridge_runtime_guideline.md)
- [Specimen Agent](../agents/specimen_agent.md)
- [Bridge Matrix](bridge_api_connection_matrix.md)
