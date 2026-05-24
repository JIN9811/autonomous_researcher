# Prusa MK4S Live Validation - 2026-05-06

Purpose:
- Record the actual Prusa MK4S bridge validation result for this repository.
- Keep operator secrets out of documentation.
- Define the runtime assumptions that printer-related code must preserve.

## Validated Target

- Printer: Prusa MK4S.
- PrusaLink IP used during validation is stored in `memory/prusa_connection.json` and must not be committed.
- Prefer mDNS hostname `prusa-mk4.local` when available so the source tree does not depend on a machine-specific address.
- PrusaLink hostname reported by `/api/version`: `prusa-mk4`.
- API response:
  - `api: 2.0.0`
  - `server: 2.1.2`
  - `nozzle_diameter: 0.4`
  - `capabilities.upload-by-put: true`
- Auth mode: Digest.
- Storage target: `usb`.

Connection memory:
- Path: `memory/prusa_connection.json`.
- Store only the required live connection values there.
- Do not copy password values into docs, prompts, GUI messages, runtime events, or test logs.

## Validated Endpoints

- Read version: `GET /api/version`.
- Read status: `GET /api/v1/status`.
- Read storage: `GET /api/v1/storage`.
- Read job: `GET /api/v1/job`.
- Read transfer: `GET /api/v1/transfer`.
- Upload G-code: `PUT /api/v1/files/usb/<file>.gcode`.
- Read uploaded-file metadata: `GET /api/v1/files/usb/<requested-file>.gcode`.
- Start uploaded G-code with the metadata storage name: `POST /api/v1/files/usb/<metadata.name>`.

Upload requirements:
- Body: replayable bytes payload.
- `Content-Type: application/octet-stream`.
- `Overwrite: ?1` or `?0`.
- `Print-After-Upload: ?0` for staged upload/start separation.

Why bytes payload matters:
- Digest auth may challenge and replay the request.
- A generator stream can be consumed before the authenticated retry.
- The live bridge must upload `local.read_bytes()` or another replayable body.

## Storage Handling

Observed blocked state:

```json
{
  "storage_list": [
    {
      "path": "/usb/",
      "name": "usb",
      "type": "USB",
      "read_only": false,
      "available": false
    }
  ]
}
```

Observed upload failure in that state:
- HTTP 507.
- Response text included `Failed to write to location`.

Required bridge behavior:
- Check `GET /api/v1/storage` before live upload.
- Block selected storage with `available: false` as `PRINTER_STORAGE_UNAVAILABLE`.
- Block selected storage with `read_only: true` as `PRINTER_STORAGE_READ_ONLY`.
- Normalize upload HTTP 507 to `PRINTER_STORAGE_UNAVAILABLE`.
- Keep generic `PRINTER_HTTP_ERROR` only for unclassified non-2xx responses.

## Slicer Deployment

Validated local deployment path:
- Dockerfile: `install/prusaslicer/Dockerfile`.
- Wrapper: `install/prusaslicer/prusa-slicer-docker`.
- Image tag: `atr-prusa-slicer:ubuntu24.04`.

Build:

```bash
docker build -t atr-prusa-slicer:ubuntu24.04 install/prusaslicer
```

Runtime config:

```yaml
devices:
  printer:
    slicer:
      executable_env: PRUSA_SLICER_EXECUTABLE
      executable_path: install/prusaslicer/prusa-slicer-docker
```

Resolution rule:
- `PRUSA_SLICER_EXECUTABLE` wins if set.
- Otherwise use `executable_path`, resolved relative to repository root.

Note:
- The Docker apt build is suitable for local slicing smoke tests.
- Production MK4S profile compatibility must be validated when upgrading PrusaSlicer/profile bundles.

## Physical Test Result

Test artifact:
- Model: 2 mm cube.
- G-code: `runs/prusa_cube_20260506T124928Z/cube_2mm_mk4s_safe_start.gcode`.

Successful path:
1. `GET /api/version` returned PrusaLink metadata.
2. `GET /api/v1/status` returned printer state.
3. `GET /api/v1/storage` returned USB storage with `available: true`.
4. `PUT /api/v1/files/usb/<file>.gcode` returned HTTP 201.
5. `POST /api/v1/files/usb/<file>.gcode` returned HTTP 204 in the initial cube validation; subsequent MK4S validation requires resolving `<metadata.name>` first when PrusaLink stores an 8.3 USB filename.
6. Polling observed the job move through printing states.
7. Final printer state reached `FINISHED`.

2026-05-08 MK4S start-path refinement:
- PrusaLink stores uploaded display filenames on USB as actual 8.3 filenames such as `AUTOEJ~1.GCO`.
- The reliable physical-start sequence is:
  1. upload requested/display filename with staged upload/start separation,
  2. poll `GET /api/v1/transfer` until idle/HTTP 204,
  3. read `GET /api/v1/files/usb/<requested-file>.gcode`,
  4. start `POST /api/v1/files/usb/<metadata.name>`.
- Standalone autoejection was validated with requested filename `autoeject-test-center.gcode`, resolved filename `AUTOEJ~1.GCO`, start endpoint `/api/v1/files/usb/AUTOEJ~1.GCO`, and final `/api/v1/job=204`.
- The embedded PrusaLink 2.1.2 target returned 404 for `POST /api/printer/ready`; the runtime must wait for job clear/FINISHED instead of relying on SetReady.

Validation logs:
- `runs/prusa_cube_20260506T124928Z/bridge_comm_log.jsonl`.
- `runs/prusa_cube_20260506T124928Z/test_log.jsonl`.

## Runtime Safety Policy

Current local runtime policy:
- `allow_upload: true`.
- `allow_start_print: true`.
- `allow_ejection: false`.
- Live GUI `실험 수행` is allowed to upload and start a Prusa MK4S print through PrusaLink after the required design inputs are complete.
- Test mode uses virtual bridge unless the Specimen Making Agent printer-path prompt explicitly selects installed-printer read-only communication or `physical_print` / `실제 출력` for real upload/start of the test-generated specimen.

Live print execution requires:
- Valid `memory/prusa_connection.json`.
- Writable selected storage.
- Slicer output validated by `GCodeSafetyValidator.validate_print_gcode`.
- Live GUI or API payload with physical print intent, typically `print.start_immediately=true`.
- Operator intent for physical execution through the `실험 수행` trigger in normal Live GUI mode.

Ejection remains off while `memory/prusa_print_profile.json` has `allow_ejection:false`.
The available ejection implementation is the bed-sweep append-G-code path: when the operator enables ejection in the 3DP GUI, the controller applies it to test, live, and Live GUI test-mode payloads, and the bridge appends a validated tail to the sliced print G-code before PrusaLink upload/start.
