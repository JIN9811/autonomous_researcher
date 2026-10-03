# BambuLab X2D Device Bridge Runtime Guideline

Baseline date: 2026-06-16
Scope: `3D Printer Bridge`, `PrinterDeviceBridgeManager`, `SpecimenMakingAgent`, and the active `BambuLab` printer provider
Document status: historical description of the implementation and verification as of 2026-06-16. Archived proposals are not current operating authority.

> Current-contract notice (2026-09-29 static audit at `dd0d772`, reconfirmed against local source): use the [Bambu X2D Reference](../device_bridges/bambu_x2d_bridge.md),
> [Printer Fleet](../device_bridges/printer_fleet_bridge.md), and [pre-eject cleanup](../device_bridges/x2d_pre_eject_cleanup.md) for current operations.
> “Current,” GUI buttons, absent preset injection, and Installed Printer procedures below describe the June record.
> The current slicer uses resolved presets and applies XYZ speed scaling. `installed_printer` is
> an ejection-only conversion path, not a normal print-start/cancel sequence; standalone live ejection GUI controls were removed.
> Ejection in a normal print cycle follows the current AMS-unload/nozzle-cooling/bed-cooldown contract.
> Do not execute these historical procedures verbatim or treat their results as current unattended-operation validation.

---

<a id="1-역할-정의"></a>
## 1. Role Definition

BambuLab X2D is ATR's default 3D printer provider. The bridge is not merely a file-upload adapter: it manages four separate planes.

| Plane | Responsibility | Representative evidence |
|---|---|---|
| Fleet / Provider | Active printer profile selection, Bambu/Prusa switching, separate secrets | `memory/printer_fleet.json`, `memory/bambu_connection.json` |
| Slicing / Artifact | Convert STL/3MF to a Bambu Studio or Orca-family sliced artifact | `.gcode.3mf`, sha256, command preview, stderr/stdout tail |
| Device Status / Control | MQTT status collection, `project_file` draft/publish, post-publish observation | `device_screen`, `gcode_state`, `mc_percent`, `subtask_name` |
| Camera / Bed-clear | Camera frame/proxy, visual evidence before/after ejection, next-job gate | `camera_snapshot_path`, `bambu_bed_clear_evidence.v1` |

Core principles:

- BambuLab X2D is the default active provider.
- Prusa MK4S is an explicitly selected alternative provider, not a fallback.
- Bambu autoejection is a Bambu-specific native G-code patch/validation path, not a Manipulation Agent handoff.
- MQTT publish acknowledgment is distinct from physical print start. A fresh post-publish observation must confirm a `RUNNING`/`PREPARING`-family state.
- Camera/video failures must not erase MQTT/progress/material status. The two planes provide parallel evidence.

---

<a id="11-외부-근거와-atr-적용-범위"></a>
## 1.1 External Evidence and ATR Scope

This document does not import external projects or community G-code verbatim. The cases reviewed at the time provide evidence for the following operating principles.

| Evidence scope | Recorded finding | ATR application |
|---|---|---|
| Bambu Studio CLI | The official CLI provides slicing/export through `--slice`, `--load-settings`, `--load-filaments`, and `--export-3mf`. | Separate slicing from publish and export by basename within the output directory. |
| OpenBambuAPI / Home Assistant family | Local MQTT uses TLS 8883, username `bblp`, and a LAN access code; `project_file` includes `url`, `param`, `subtask_name`, and AMS values. | Keep command drafts, internal plate paths, AMS mapping, publish acknowledgment, and post-publish observation as separate evidence. |
| ha-bambulab upload/start cases | FTPS upload and MQTT start are combined, but AMS mapping and actual start observation remain separate concerns. | Separate FTPS/HTTP transfer proof from the start gate; `published=true` alone is not success. |
| Looprint / Factorian autoeject cases | Repeated printing inserts cooldown, push-off, and optional sweep into sliced G-code/3MF. Push axes and safe envelopes differ by model family. | Use native `bambu_gcode_patch` only as deterministic post-processing, gated by model-family/envelope/height/residue validation. |
| Reddit / Bambu community failures | Recurring physical risks include bed adhesion, toolhead covers, directional loading of carbon rods, purge/skirt residue, and build-plate shift. | The workstation owner/operator manages the physical environment. Remove manual UI checklists; center runtime gates on printer state, geometry, camera, and bed-clear evidence. |
| Bambu Studio Device screen | Camera, progress/layer, thermal, material/AMS, and control status remain visible together. | The 3D Printer workspace shows status and camera planes together; video failure must not erase existing status. |
| X2D/H2D MQTT reports | X2D/H2D reports have deeper `2D`, `3D`, `device`, and nozzle/material structures than X1/P1. | Preserve raw reports and unknown fields; show only normalized summaries in the workspace. |

Principal references:

- Bambu Studio command line usage: `https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage`
- Bambu LAN mode: `https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode`
- Bambu printer network ports: `https://wiki.bambulab.com/en/general/printer-network-ports`
- OpenBambuAPI MQTT notes: `https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md`
- ha-bambulab upload/start discussion: `https://github.com/greghesp/ha-bambulab/discussions/307`
- Looprint multi-loop builder: `https://github.com/NickiAndersen/looprint`
- X2D MQTT report issue: `https://github.com/DrozmotiX/ioBroker.bambulab/issues/258`
- SimplyPrint / Bambu webcam and Developer Mode references: `https://help.simplyprint.io/en/article/bambu-lab-webcam-not-working-guide-pw6z3q/`, `https://help.simplyprint.io/en/article/bambu-lab-lan-only-mode-and-developer-mode-how-to-enable-xa0hch/`

---

<a id="2-runtime-경로"></a>
## 2. Runtime Path

The historical Live/Test workflow invokes the Bambu bridge at these points. The final stage list is a summary, not the current conditional transition table.

```text
Live GUI / Main GUI
  -> MainController / LangGraphRunLoop
  -> DesignAgent
      -> create bambu_autoejection_readiness
  -> SpecimenMakingAgent
      -> retain readiness in fabrication_report.process_plan
      -> create printer.prepare payload
  -> PrinterDeviceBridgeManager
      -> resolve active provider through PrinterFleetRegistry
      -> run Bambu status/slicing/start gates when BambuLabBridge is selected
      -> call BambuGcodeAutoejectionPatcher when native autoejection is enabled
  -> Vision / Manipulation / Equipment / Analysis / Knowledge / BO / Guardian
```

`SpecimenMakingAgent` does not implement printer-specific communications. It builds the `printer.prepare` payload and report evidence; the historical entry points are `device_bridges/bambu_bridge.py` and `device_bridges/bambu_autoejection.py`. In the installed code these forward through compatibility aliases under `device_bridges/bambu/` to the owner implementations in `device_bridges/printer_fleet/bridge.py` and `device_bridges/printer_fleet/providers/bambu_autoejection.py`.

---

<a id="3-bambu-통신-모델"></a>
## 3. Bambu Communication Model

### MQTT

Local MQTT targets a printer with LAN/Developer Mode enabled.

- host: `{printer_ip}:8883`
- username: `bblp`
- password: LAN access code
- report topic: `device/{serial}/report`
- request topic: `device/{serial}/request`

Evaluate `project_file` publication as separate checks:

1. Command draft validity
2. Consistency of artifact and internal plate paths
3. Presence of `ams_mapping` when AMS is used
4. MQTT publish ack
5. Printer state/progress in a fresh post-publish observation

Do not display print success from `published=true` alone. If the printer remains `IDLE` or not started after publication, show `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED` to the operator.

### FTPS / HTTP artifact route

Bambu artifact transfer separates FTPS upload from the HTTP artifact route.

- Successful FTPS login/listing does not establish upload readiness.
- A write/delete probe or server-fetch proof is required.
- The HTTP route must be reachable by the printer, using `http://<ATR-LAN-IP>:<port>/...`.
- A `localhost` URL is not reachable from the printer and is not live-transfer evidence.

### Camera / Video

Camera/video is a separate plane from MQTT status.

- `Pre-start Check` updates status and camera together.
- `Video Status` updates only the camera panel and must not erase existing device/material/progress cards.
- After ejection, `Mark Bed Clear` must retain the latest camera preview/proxy evidence as `camera_snapshot_path`.

---

<a id="4-slicing--artifact-기준"></a>
## 4. Slicing / Artifact Requirements

The primary Bambu artifact is a sliced `.gcode.3mf`. Plain `.gcode` is useful for development, validators, and standalone ejection tests, but is not the primary live Bambu publish path.

The Bambu Studio CLI documented for this record provides:

- `--slice <plate_index>`
- `--arrange <option>`
- `--load-settings "machine.json;process.json"`
- `--load-filaments "filament.json;..."`
- `--outputdir <dir>`
- `--export-3mf <output-basename.3mf>`
- `--debug <level>`

The ATR bridge separates slicing from upload/start. `Slice Bambu Artifact` only generates the artifact; it does not publish MQTT or execute physical motion.

Recorded CLI/route verification notes (June behavior unless qualified):

- Pass a basename within `--outputdir`, not an absolute path, to `--export-3mf`. BambuStudio `02.07.01.57` on the Spark workstation could combine the output directory twice and fail export when given an absolute path.
- Without explicit `load_settings`, the June runner retained Bambu Studio's default machine/process/filament presets. It preserved default purge, cleaning, and filament start/end G-code, removing only the front-of-plate test/intro/nozzle-load line during sliced-artifact post-processing. This no-injection behavior is historical; the current slicer resolves presets.
- Recorded verification using basename export and `<home>/다운로드/specimen(4).stl` produced `.gcode.3mf`, patched internal `Metadata/plate_1.gcode`, removed the front test line, updated the md5 sidecar, and passed validation. This proves artifact generation/patching only, not physical publish/ejection success.
- For the physical installation, the HTTP artifact route passed server-side fetch and sha256 matching using the ATR server's LAN IP URL. With owner-managed publish defaults and no artifact/camera/bed-clear/start-state blocker, `Pre-start Check` can reach `ready_to_publish_not_started`. The route still retains `published=false` and `will_publish=false`.
- A `.gcode.3mf` patch targets only `Metadata/plate_<id>.gcode` matching the requested `plate_id`. If that plate is absent, another plate is not substituted. This live-start contract prevents MQTT `project_file.param` from disagreeing with the internal plate path.
- Apply the same check when passing a local `.gcode.3mf` to `printer.prepare` or the HTTP artifact route. If the requested `Metadata/plate_<id>.gcode` is absent, block with `BAMBU_PROJECT_FILE_PARAM_MISMATCH` before FTPS upload or HTTP export.
- Patch results and manifests retain `source_sha256`, `patched_sha256`, `source_plate_path`, `plate_id`, `loop_index`, and validator results. If omitted from the request, `loop_index` defaults to `1` for a single-print artifact.
- If an input `.autoeject.*` already contains `atr.bambu.autoejection.v1`, the bridge does not create another `.autoeject.autoeject.*` file. It revalidates the existing artifact and updates only the sidecar manifest.

Recommended flow:

```text
STL/3MF source
  -> Bambu Studio/Orca slicing
  -> .gcode.3mf artifact
  -> optional Bambu native autoejection patch
  -> .autoeject.gcode.3mf artifact + manifest
  -> start gate
  -> publish only after backend start gate and browser confirmation
```

---

## 5. Native G-code Autoejection

Bambu autoejection is represented by the `bambu_gcode_patch` provider. It inserts a deterministic ejection tail into the sliced artifact's internal plate G-code rather than handing off to an external robot.

<a id="기본-설계"></a>
### Basic Design

```text
.gcode.3mf
  -> extract Metadata/plate_#.gcode
  -> analyze object bounds / max_layer_z / residual skirt-brim-raft risk
  -> insert ejection tail
  -> update Metadata/plate_#.gcode.md5
  -> generate .autoeject.gcode.3mf
  -> write sidecar manifest + run workspace manifest
```

<a id="validator가-막아야-하는-것"></a>
### Required Validator Blockers

- Missing or duplicate ejection markers
- Unexpected `G28` inside the ejection tail
- X/Y/Z motion outside the build envelope
- Excessive feed rate
- Object height below or above the permitted range
- multi-object plate without explicit support
- skirt/brim/raft/purge residue risk
- Missing AMS mapping
- Mismatch between the `.gcode.3mf` internal plate path and MQTT `project_file.param`
- Missing operator-managed physical-context evidence or insufficient bed-clear/camera evidence

<a id="tail-metadata-계약"></a>
### Tail Metadata Contract

The tail inserted by `bambu_gcode_patch` must include a traceable evidence header as well as motion commands. The deterministic tail described in this record writes these plate G-code comments:

- schema marker: `atr.bambu.autoejection.v1`
- source artifact hash and patched artifact hash reference
- source plate path, `plate_id`, `loop_index`
- specimen id, selected push position, object bounds, object height
- material type and bed surface, explicitly `unknown` when slicer metadata extraction is unavailable
- cooldown target and wait policy: default `M190`
- push Z offset, push lane offset, push speed, full-bed sweep enable, sweep Z, sweep speed
- purge/parking strategy: historical default `preserve_slicer_end_gcode_then_eject`
- door/front path assumption, toolhead-cover risk note, validation result reference

This metadata is an audit trail in the generated artifact itself, not invented GUI display data. `unknown` values are extension points for a later slicer/profile parser; they are not omitted to conceal missing knowledge.

<a id="live-publish-조건"></a>
### Live Publish Conditions

An `.autoeject.*` artifact requires stronger gates than an ordinary artifact.

- owner-managed publish defaults present (`operator_confirmed=true`, `guardian_approved=true`, `dry_run=false`)
- operator-managed physical clearance/ejection setup recorded as evidence
- camera frame available or operator visual evidence
- previous `bed_clear_required` lock cleared

<a id="standalone-autoejection-test-경로"></a>
### Historical Standalone Autoejection Test Path

The June 3D Printer workspace separated left/center/right standalone autoejection tests from actual specimen printing. The former live test buttons are no longer exposed; this section preserves the historical workflow, not current operating instructions.

```text
Historical 3D Printer workspace standalone button
  -> POST /api/printer/autoejection-test
  -> build_standalone_bambu_autoejection_artifact()
  -> standalone .autoeject.gcode.3mf artifact
  -> guarded upload/start through MQTT project_file
```

Installation paths recorded at the time (not portable defaults):

- printer host: `192.168.50.4`
- serial: `20P6BJ642001425`
- MQTT request topic: `device/20P6BJ642001425/request`
- config/evidence memory: `memory/bambu_autoejection.json`
- generated standalone artifact directory: `artifacts/bambu_autoejection/`
- physical validation summary: `runs/manual_bambu_validation/`

The recorded standalone test design did not use direct MQTT `gcode_line` motion. It passed `.autoeject.gcode.3mf` through the normal upload/start gate only after the workspace live gate passed. The tail did not execute all-axis `G28`: Bambu/X2D full homing can include central probing/contact, so the tail preserved the coordinate system established at print-job start.

The historical `Live GUI 테스트 모드, 설치 프린터` (Installed Printer) route validated routing without waiting for a full print. It sliced an actual STL to `.gcode.3mf` with the active slicer and published it through the ordinary `project_file` upload/start gate. Success required a fresh `RUNNING`/preparing-family observation and progress-panel evidence, not an MQTT acknowledgment. It then sent an immediate stop, extracted extrusion-move object bounds from `Metadata/plate_#.gcode` in the same sliced artifact, and published a standalone autoejection artifact. Missing extrusion bounds or unreadable plate G-code blocked ejection publication with a `BAMBU_AUTOEJECTION_SOURCE_EXTRUSION_BOUNDS_REQUIRED`-family failure. This start/cancel/eject sequence is obsolete: current `installed_printer` requests set `use_ejection_only_project_file=true` and remove the print body before starting the ejection-only job.

`Live GUI 테스트 모드, 실제 출력` (Physical Print) and normal Live printing preserve the print body. They append an autoejection tail to the internal plate G-code of the sliced `.gcode.3mf`, producing `.autoeject.gcode.3mf` for the ordinary upload/start gate.

The recorded default push-Z rule is `max(10 mm absolute Z, object max Z - 15 mm)`. For example, a 12 mm object is swept at Z10.000 and a 30 mm object at Z15.000. These values correspond to `z_push_offset_mm` and `min_absolute_push_z_mm` in `memory/bambu_autoejection.json`.

Z motion is calculated in absolute coordinates. The autoejection push height is `push_z_mm = max(10.0, object_bounds.max_z - z_push_offset_mm)`, with recorded default `z_push_offset_mm` of 15mm. Thus `max_z <= 25mm` gives `G0 Z10.000`, `max_z=26mm` gives `G0 Z11.000`, and `max_z=30mm` gives `G0 Z15.000`. The `object max Z + 10mm` method is prohibited.

Historical runtime paths, retained for comparison (not the current Installed Printer contract):

| Mode | Transport | Physical motion |
|---|---|---|
| Main GUI test / Live GUI `테스트 모드, 가상 브릿지` (Virtual Bridge) | `virtual` | None |
| Live GUI `테스트 모드, 설치 프린터` | actual sliced `.gcode.3mf` -> MQTT `project_file` start -> progress observation -> stop -> source-bounds-derived standalone `.autoeject.gcode.3mf` + MQTT `project_file` | actual-printer upload/start validation plus physical ejection-route validation; full print body is started only long enough to prove the progress panel receives a real job |
| Historical 3D Printer workspace standalone autoejection test with live gates | standalone `.autoeject.gcode.3mf` + MQTT `project_file` | ejection-only artifact through the same upload/start gate; no direct `gcode_line` |
| Live GUI `테스트 모드, 실제 출력` / normal Live actual print | `.autoeject.gcode.3mf` + MQTT `project_file` | real print body is preserved and deterministic autoejection tail is appended |

---

<a id="6-3d-device-workspace-표시-원칙"></a>
## 6. 3D Printer Workspace Display Principles

The 3D Printer workspace should retain live operational information on one screen, like the Bambu Studio Device tab. It must display only backend-normalized reports, never invented values.

Required display areas:

- active printer profile and provider
- LAN/Developer Mode confirmation
- camera preview or camera blocker
- current job/progress/layer/ETA
- nozzle/bed/chamber/fan status
- AMS/material mapping
- transfer/upload/HTTP route status
- start gate and post-publish observation
- autoejection config/validator result
- bed-clear evidence and next-job lock

Button policy:

- Prevent repeated clicks on `Pre-start Check`, `Video Status`, `Generate Patched Artifact`, `Validate *`, `Publish Start`, and `Mark Bed Clear` until their callbacks finish.
- `Pre-start Check` validates immediately before printing; it does not publish.
- Only `Publish Start` in this panel publishes an actual MQTT start.
- A `Video Status` failure must not reset existing status cards.
- `Physical Proof Package` is not a print/ejection execution button. It supplies only a fail-closed JSON template for operator evidence after supervised physical validation and a completion audit.
- `Build Fail-Closed Proof Template` calls `/api/printer/bambu-autoejection-proof-template` and can create a proof package under `artifacts/printer/manual/bambu/`. A newly generated package must fail audit.
- `Run Completion Audit` calls `/api/printer/bambu-autoejection-completion-audit` to read the proof package and judge completion. This API is also non-actuating: no MQTT publish, upload, camera capture, or axis motion.

---

<a id="7-test--live-동작-차이"></a>
## 7. Test / Live Behavior Differences

The table retains the June mode description. In the installed runtime, selecting Installed Printer can execute physical ejection and downstream equipment; Test is not a universal dry-run guarantee.

| Mode | Recorded Bambu bridge behavior | Physical motion |
|---|---|---|
| Test + virtual bridge | slicing/patch/validation simulation, virtual bed-clear evidence | None |
| Test + installed printer | MQTT/FTPS/video/pre-start communication checks; actual publication only when selected by the operator | None by default in this historical description, not a current-path guarantee |
| Live | Slicing/transfer/start through the active Bambu provider; patched artifact when autoejection is enabled | Yes, when gates pass |

Live and Test use the same API contract; bridge mode and publication gates distinguish their execution effects.

---

<a id="8-문서코드-동기화-체크리스트"></a>
## 8. Documentation / Code Synchronization Checklist

When changing Bambu bridge behavior, also check:

- `docs/oldversion/개선안/14_bambulab_gcode_autoejection_runtime_plan.md`: archived detailed proposal and verification items
- `docs/runtime/closed_loop_and_pages_reference.md`: runtime/API/Live GUI contracts
- `docs/gui/gui.md`: screen buttons, state, and API surface
- `docs/tutorials/device_workspace_3dp_usage.ko.md`: operator instructions
- `docs/tutorials/user_manual.ko.md`, `docs/tutorials/user_manual.en.md`: user manuals
- `docs/project/Project_guide.txt`: project-wide sequence and agent responsibilities
- `REQUIREMENTS.md`: Bambu Studio/OrcaSlicer/ffmpeg/mqtt/ftps dependencies

---

<a id="9-현재-검증-경계"></a>
## 9. Verification Boundaries at the Time of the Record

Separate the non-destructive checks completed against the code/documents at the time from work that still required physical validation. Recorded outcomes below are not new test results or current commissioning claims.

### 9.0 External-case contract

The bridge does not treat a Bambu printer as simply “transfer a file, then print.” The external cases reviewed imply at least these simultaneous contracts for automatic ejection.

| Evidence plane | Operational meaning | Bridge/GUI display |
| --- | --- | --- |
| Artifact | Which plate G-code a BambuStudio/Orca/manually sliced artifact contains and how post-processing changes the source | source/patched path, sha256, `Metadata/plate_#.gcode`, sidecar manifest |
| Validation | Object bounds, sweep envelope, skirt/brim/purge residue, homing or dangerous commands | validation summary, blocker list, object bounds, sweep path |
| Transport | Whether the physical printer can receive the FTPS or HTTP artifact route | transfer result, fetch URL, sha256 match, dedicated failures such as `BAMBU_FTPS_TOO_MANY_CONNECTIONS` |
| Runtime | Whether MQTT `project_file` publication was accepted and whether actual printer state changed | publish sequence/topic, `gcode_state`, progress, subtask, post-publish observation |
| Bed-clear | Whether the next job may start | camera snapshot reference, operator/camera/vision decision, source/patched sha256 continuity, next-job gate |

The reviewed Looprint cases insert cooldown/push-off/loop logic into already-sliced G-code/3MF. The 3DQue/Infinity Flow cases emphasize single-part center/front placement, release surfaces, purge residue, door/front clearance, and multi-height sweeps. The ha-bambulab/OpenBambuAPI cases separate FTPS upload from MQTT `project_file` start and treat AMS mapping separately. ATR does not copy these structures verbatim; it standardizes the evidence chain as `artifact -> validation -> transfer -> guarded publish -> observation -> bed-clear`.

Here, `published=true` does not mean physical ejection success. Actual success requires post-publish observation, camera/operator evidence, and bed-clear unlock together.

Recorded completed non-destructive verification:

- The Bambu Studio CLI runner passed an output-directory basename, not an absolute path, to `--export-3mf`.
- Without explicit `load_settings`, the June runner preserved Bambu Studio defaults and did not automatically inject `--load-settings`/`--load-filaments`. It removed only front test/intro/nozzle-load line blocks from generated `.gcode` or internal `.gcode.3mf` plate G-code and updated the md5 sidecar. The current preset-resolution behavior supersedes this historical no-injection result.
- `<home>/다운로드/specimen(4).stl` was verified through `.gcode.3mf` generation, internal `Metadata/plate_1.gcode` patching, md5 sidecar update, and validator pass.
- Bambu autoejection tails recorded `source_plate_path`, `plate_id`, `loop_index`, material/bed placeholders, cooldown policy, purge/parking strategy, door/front assumptions, and a toolhead-cover risk note as artifact comments.
- `Validate G-code Preview` / `Validate Left|Center|Right` used `validate_only=true`, returning only the would-be tail and validator evidence, without writing `.autoeject.*` artifacts or manifests.
- `Pre-start Check` combined camera/status, slicing, optional native autoejection patch, HTTP route, start gate, and SPC readiness without publishing MQTT.
- Tests covered the contract that `Video Status` failure must not erase existing device/progress/material status.
- After an `.autoeject.*` publish acknowledgment, bed-clear-required evidence was saved and the next start gate remained blocked until verification. This is not merely a checkbox: where available, retain remote artifact URL, subtask name, source/patched paths and sha256, sidecar manifest path, MQTT publish sequence/topic, post-publish status, and camera snapshot reference. Physical-completion proof also requires a separately saved `printer.bambu.start_publish` response snapshot; its `ready_to_publish=true`, `start_enabled=true`, empty blockers, remote path, publish sequence/topic, and post-publish running state must match the proof body. Updating verified status through `Mark Bed Clear` must preserve existing artifact/publish references.
- A temporary FastAPI server and Selenium/Firefox headless 1920x1080 rendering verified `/printer` page identity, nonblank rendering, camera placeholder, `Video Status`, `Pre-start Check`, autoejection validation controls, standalone left/center/right artifact controls, and `Mark Bed Clear`. On the same browser path, `Validate Center` called the validate-only API and displayed validation pass, source plate, object bounds, and sweep path in summary/detail/body, without raw G-code lines or an increase in `.autoeject.*` files. This covered GUI display and DOM wiring, not physical publish/ejection.

2026-06-16 local audit snapshot:

- Bambu Studio slicing of `<home>/다운로드/specimen(4).stl` passed through `.gcode.3mf` artifact generation.
- Non-mutating `Validate G-code Preview`-style validation of the same artifact must return only validator evidence without writing a patched artifact or manifest.
- `Generate Patched Artifact`-style execution was verified through `.autoeject.gcode.3mf` creation, sidecar manifest creation, and internal `Metadata/plate_1.gcode.md5` update.
- The HTTP artifact route passed server-side fetch and sha256 matching using the ATR server's LAN IP URL. This established a candidate URL deliverable to the printer, not printer publication.
- The early manual-gate `Pre-start Check` dry-run reached `camera_status`, optional native patch, and HTTP artifact route, then intentionally blocked on `BAMBU_START_DRY_RUN`, operator confirmation, Guardian approval, and ejection-checklist blockers. The subsequent UI removed that manual checklist: the 3D Printer workspace sends owner-managed publish defaults and the backend blocks on artifact/camera/bed-clear/start-state evidence.
- When physical-device status queries encountered FTPS `421 too many connections`, the error was shown as `BAMBU_FTPS_TOO_MANY_CONNECTIONS`, not a generic network failure. Live MQTT/video did not establish FTPS upload readiness.
- Workspace visual QA confirmed that `Video Status` displayed `proxy_ready`/RTSPS or MJPEG proxy status in the Bambu camera panel and that the subsequent `Pre-start Check` kept an actual frame visible. MQTT/progress/material cards remained visible, with the FTPS blocker shown separately.
- Autoejection-panel visual QA rendered `Save Autoejection Config`, `Validate G-code Preview`, `Generate Ejection Test Artifact`, `Generate Sweep Test Artifact`, `Generate Patched Artifact`, `Mark Bed Clear`, `Mark Not Clear`, and standalone left/center/right artifact buttons. `Validation Evidence` was collapsed by default; no full raw G-code block was displayed.
- An additional 2026-06-16 pre-start audit used saved physical Bambu connection data and an existing `.gcode.3mf` on a temporary `0.0.0.0:7862` server to call `camera_status -> existing sliced artifact -> native autoejection patch -> HTTP artifact route -> start gate -> SPC readiness`. The LAN-IP `HTTP artifact route` returned `ok=true` and `printer_fetch_ready=true`, preserving transfer evidence despite FTPS connection limits. Earlier manual-gate requests remained `blocked` on approval/checklist requirements; the subsequent GUI used owner-managed publish defaults. Blocking then depended on artifact validity, camera frame requirement, bed-clear lock, printer safe state, and post-publish observation.
- On that API path, passing owner-managed publish defaults and camera/bed-clear/start-state evidence allowed `Pre-start Check` to reach `ready_to_publish_not_started`. It still retained `published=false` and `will_publish=false`, indicating neither MQTT publication nor motion.
- The API path also verified `BAMBU_POST_EJECT_BED_NOT_CLEAR`. Saving `bed_clear_required=true` and `bed_clear_verified=false` through `/api/printer/bed-clear` blocked even the all-confirmed pre-start path with that code. Saving `bed_clear_required=false` and `bed_clear_verified=true` released the same start gate to `ready_to_publish_not_started`. Local bed-clear memory was restored after the check.
- The 2026-06-16 code smoke check returned `HTTP 200` and 3D Printer GUI HTML from `/printer` on a temporary FastAPI server. The HTML contained `Bambu LAN Connection`, `Bambu G-code Autoejection`, `Pre-start Check`, `Video Status`, `Publish Start`, `Mark Bed Clear`, and `Validate G-code Preview`. `/api/printer/status?mode=test` returned the active BambuLab X2D profile and device-screen payload; `will_publish`/`start_enabled` were not set by nonphysical queries. Selenium/Firefox headless rendering on the same server confirmed visible upper-console and autoejection-section buttons in the DOM. This was rendered-GUI and HTML/API smoke evidence, not physical publish/ejection validation.

Scope that required physical-device validation to establish completion:

- Supervised standalone center-ejection motion
- Live ejection of a small disposable object
- Ejection from left/right positions
- Post-ejection camera snapshots and actual bed-clear judgment
- Agreement between the next-job start gate and actual printer state after bed-clear unlock

Do not describe Bambu native autoejection as production-safe or unattended-ready before those physical checks are complete.

### 9.1 Supervised physical validation runbook

This historical runbook required an operator physically present at the printer. Every execution step had to pass `/api/printer/start-publish` or GUI `Publish Start`, without bypasses through direct MQTT `gcode_line` motion or overwritten profile start/end G-code. Reconcile it with current references before any use; the old standalone live GUI controls are not current instructions.

| Order | Purpose | Execution path | Completion evidence |
| --- | --- | --- | --- |
| 1 | Establish state before physical start | `Video Status` -> `Pre-start Check` -> `SPC Readiness` | saved pre-start snapshot, Bambu active profile, camera frame/proxy, `.autoeject.*` artifact, `ready_to_publish_not_started`, `published=false`, `will_publish=false` |
| 2 | Actual center standalone ejection motion | `Generate Ejection Test Artifact` center -> browser-confirmed `Publish Start` with owner-managed defaults | center artifact file with ATR marker and `atr_position=center`, saved `printer.bambu.start_publish` snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state, camera frame before/after, object moved to front-clearance/bin zone, no collision, no toolhead-cover/plate shift |
| 3 | disposable object live ejection | small disposable print using patched `.gcode.3mf` -> guarded `Publish Start` | print completion, autoejection tail execution observed, bed object removed, saved `printer.bambu.start_publish` snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state, `/api/printer/bed-clear` temporarily `required=true`, `verified=false` after publish, source/patched artifact files with matching sha256 and manifest reference |
| 4 | left/right lane validation | standalone left and right artifacts with the same gate | left/right artifact files, saved validation snapshots with matching position, saved start-publish snapshots with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state, no sweep outside envelope, validator blockers empty |
| 5 | post-ejection bed-clear | camera/operator confirms empty bed -> `Mark Bed Clear` | `memory/bambu_bed_clear_evidence.json` keeps `bed_clear_verified=true`, `blocking_code=""`, camera/operator/vision method, and source/patched sha256 matching the live `.autoeject.*` artifact |
| 6 | next-job gate consistency | run `Pre-start Check` or `/api/printer/start-gate` after bed-clear | saved start-gate snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, no `BAMBU_POST_EJECT_BED_NOT_CLEAR`, and printer idle/ready state matched |

Retain an API response or memory-file path for each step, not only a GUI display. In particular, `published=true` proves MQTT command acceptance, not successful motion; camera/visual evidence and post-ejection bed-clear evidence are both required for step completion.

### 9.2 Completion audit CLI

After physical-device validation, run the completion audit against the proof package. This is a non-actuating tool and does not move the printer.

```bash
./scripts/audit_bambu_autoejection_completion.py --write-template artifacts/printer/<run_id>/bambu/bambu_autoejection_physical_validation_<timestamp>.json --printer-profile-id bambulab_x2d_lab_01
./scripts/audit_bambu_autoejection_completion.py --proof-package artifacts/printer/<run_id>/bambu/bambu_autoejection_physical_validation_<timestamp>.json
./scripts/audit_bambu_autoejection_completion.py --latest
```

Files created with `--write-template` have fail-closed defaults. The audit must not pass until the operator supplies actual camera images, post-publish observations, bed-clear evidence, and next-job gate evidence.

For `complete_evidence_verified`, all of the following must be retained as files:

- physical start precheck evidence: saved `/api/printer/bambu-prestart-check` snapshot with Bambu active profile, camera snapshot/proxy, `ready_to_publish_not_started`, `published=false`, `will_publish=false`
- center standalone ejection evidence: local center artifact with ATR marker and `atr_position=center`, before/after camera image, saved `/api/printer/start-publish` response snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state, no collision/toolhead-cover/build-plate shift
- disposable live ejection evidence: tail observed, object cleared, bed-clear lock, remote path, source/patched artifact files with matching sha256, patch manifest, saved `/api/printer/start-publish` response snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state
- left/right lane evidence: both lane artifact files, saved validation snapshots with matching position and empty validator blockers, and saved start-publish snapshots with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state
- post-ejection bed-clear evidence: camera/operator/vision confirmation, matching live source/patched sha256, empty `blocking_code`
- next-job gate evidence: saved `/api/printer/start-gate` snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, `BAMBU_POST_EJECT_BED_NOT_CLEAR` cleared, and printer idle/ready state matched

If the audit fails, Bambu autoejection is not yet physical-complete. System documents, Live GUI reports, and tutorials must not call it `production-safe`, `unattended-ready`, or `physical success confirmed` in that state.

### 9.3 Completion audit GUI/API

The same completion audit is available from the 3D Printer workspace. The GUI/API is an operator convenience layer around the CLI and has the same execution boundary.

| GUI control | API | Behavior |
| --- | --- | --- |
| `Build Fail-Closed Proof Template` | `POST /api/printer/bambu-autoejection-proof-template` | Create a fail-closed physical-validation JSON template; no printer communication or actuation |
| `Run Completion Audit` | `POST /api/printer/bambu-autoejection-completion-audit` | Read/validate the selected or latest proof package; no printer communication or actuation |

These APIs apply only when Bambu is the active provider. If Prusa or another provider is active, block with `BAMBU_PROOF_TEMPLATE_NOT_APPLICABLE` / `BAMBU_COMPLETION_AUDIT_NOT_APPLICABLE` and do not create a proof-template file. Bambu completion proof can be created or passed only with the Bambu bridge selected.

The proof template must not pass audit until the operator supplies the following file-backed evidence.

Completion audit does not accept `published=true` or an MQTT acknowledgment alone. If the center standalone or disposable live-ejection proof has an `idle`, `ready`, or `not_started`-family post-publish state, it blocks with `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED`: the printer may have received the command, but actual print/ejection start was not observed.

- center standalone ejection artifact, saved start-publish snapshot, and before/after camera files; the artifact must contain the ATR marker plus `atr_position=center`, the publish snapshot must have `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state, and before/after images must be distinct files
- physical start precheck snapshot with `tool=printer.bambu.prestart_check`, `ready_to_publish_not_started`, `published=false`, and `will_publish=false`
- disposable live ejection post-publish observation, remote path, publish sequence/topic, saved start-publish snapshot, source/patched artifact file paths with sha256 matching the proof
- patch manifest with `schema=bambu_autoejection_artifact_manifest.v1`, matching source/patched sha256, and `validation.ok=true` with no validator blockers
- left/right lane validation/execution evidence, including local artifact files with ATR autoejection marker, matching `atr_position=left|right`, saved validation snapshot JSON files with empty blockers, and saved start-publish snapshots with matching remote path, publish sequence/topic, and running post-publish state
- post-ejection bed-clear evidence with `verification_method=operator|camera|vision` and source/patched sha256 values matching the disposable live ejection artifact
- next-job gate evidence, including a saved start-gate snapshot JSON rather than only proof booleans

Thus, successful `Build Fail-Closed Proof Template` means only “validation document created.” Until `Run Completion Audit` returns `complete_evidence_verified`, Bambu native autoejection must not be called complete or ready for unattended operation. Passing this evidence audit is not a general safety certification beyond its recorded scope.

---

<a id="10-참고-근거"></a>
## 10. References

- Bambu Studio CLI command manual: https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage
- Bambu Lab LAN mode: https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode
- Bambu Lab printer network ports: https://wiki.bambulab.com/en/general/printer-network-ports
- Bambu Lab third-party integration / Developer Mode: https://wiki.bambulab.com/en/software/third-party-integration
- OpenBambuAPI MQTT notes: https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
- BambuBoard LAN liveview / RTSPS setup notes (2026-09-29 link audit: main-branch path removed; retained commit): https://github.com/t0nyz0/BambuBoard/blob/0784168fc451d7206300bb1a1cf3cbef21dfae2d/VIDEO_STREAMING_SETUP.md
- ha-bambulab upload/start discussion: https://github.com/greghesp/ha-bambulab/discussions/307
- OrcaSlicer auto-ejection proposal: https://github.com/OrcaSlicer/OrcaSlicer/discussions/7693
- Looprint multi-loop G-code/3MF builder: https://github.com/NickiAndersen/looprint
- BambuLab Reddit auto-ejection queue discussion: https://www.reddit.com/r/BambuLab/comments/11wexiz/automatic_print_ejection_and_print_queue/
- BambuLab Reddit FarmLoop build plate shift failure: https://www.reddit.com/r/BambuLab/comments/1k7ffzl/a1_mini_auto_ejection_fail_build_plate_shifts/
- P1S motorized door/eject via G-code API discussion: https://www.reddit.com/r/BambuLab/comments/1jfv2of/i_built_an_autoeject_system_and_motorized_door/
- Factorian Designs P1/X1 automation video: https://www.youtube.com/watch?v=Vxj1ii6dPYo
- Bambu enclosed-printer auto-ejection kit article: https://www.tomshardware.com/3d-printing/new-auto-ejection-tool-for-bambu-lab-print-farms-automatically-ejects-finished-3d-prints-from-the-machine-usd129-kit-includes-auto-door-opener-and-special-bed-surface-for-frictionless-part-ejection

These links provide evidence for ATR safety gates and evidence requirements, not source code to copy verbatim. In particular, descriptions of repeated autoejection on enclosed Bambu printers require door/front clearance, release surface, toolhead-cover considerations, camera evidence, and bed-clear confirmation together.
