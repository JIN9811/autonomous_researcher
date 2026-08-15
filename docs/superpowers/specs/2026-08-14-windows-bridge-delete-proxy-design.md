# Windows Bridge GUI DELETE Proxy Design

Date: 2026-08-14

## Problem

The Windows PyAutoGUI bridge console supports deleting custom programs and
eligible Equipment Skills with HTTP `DELETE`. The same console fails when it is
opened through ATR at `/equipment/windows/bridge-ui/*` because both ATR proxy
layers currently allow only `GET` and `POST`:

1. the FastAPI proxy route does not match `DELETE`; and
2. `WindowsPyAutoGUIBridge.proxy_ui_request()` rejects `DELETE` before making a
   request to the selected Windows bridge.

The result is an HTTP 405 from the ATR-hosted console even though direct access
to the Nextpc console completes the same deletion successfully.

## Goals

- Make program and Equipment Skill deletion work from the ATR-hosted Windows
  bridge console.
- Preserve server-side bridge-token injection so the browser never receives the
  Windows bridge credential.
- Preserve the existing selected-candidate, live-precheck, path-validation,
  response-forwarding, and no-store behavior.
- Add regression coverage at the bridge proxy and FastAPI route boundaries.

## Non-goals

- Do not change the Windows bridge API contract.
- Do not convert deletion into a `POST` compatibility endpoint.
- Do not allow arbitrary HTTP methods such as `PUT`, `PATCH`, or `OPTIONS`.
- Do not change UTM locator capture, recording, or readiness behavior.
- Do not modify or deploy the Windows package as part of this fix; the defect is
  in the Linux ATR proxy path.

## Selected Design

### FastAPI route

Extend the existing `/equipment/windows/bridge-ui/{resource_path:path}` route
from `GET, POST` to `GET, POST, DELETE`. The handler continues to forward the
incoming method, path, query string, body, and content type to the bridge
adapter. HTML rewriting remains limited to HTML responses.

### Bridge adapter

Extend `WindowsPyAutoGUIBridge.proxy_ui_request()` to accept exactly `GET`,
`POST`, and `DELETE`. All methods use the same flow:

1. normalize and validate the resource path;
2. run the selected live bridge precheck;
3. resolve the selected bridge URL;
4. inject the saved bridge token server-side;
5. forward the request with `httpx`; and
6. return the upstream status, media type, and bytes unchanged.

Unsupported methods continue to return a local 405 response with
`PYAUTOGUI_UI_METHOD_NOT_ALLOWED`. The error message must describe the new
allowlist accurately.

## Security Boundary

- The browser supplies neither the Windows bridge URL nor its token.
- The target remains the selected saved bridge candidate.
- Existing path checks continue to reject traversal components, embedded
  schemes, and protocol-relative paths.
- `DELETE` receives no broader routing privileges than `GET` or `POST`.
- Upstream authorization continues to use the server-side token header.
- The proxy remains a narrow method allowlist rather than a general-purpose
  HTTP tunnel.

## Error Handling

- An unselected or unreachable bridge returns the existing proxy-safe 503
  response.
- An invalid resource path returns the existing 400 response.
- Unsupported methods return 405 before any network call.
- Windows bridge deletion errors, including immutable built-ins and missing
  resources, retain their upstream status and JSON body.

## Test Design

Testing follows a red-green cycle.

1. Add a unit test proving `proxy_ui_request(method="DELETE", ...)` reaches the
   upstream client with the selected URL and injected token. It must fail under
   the current GET/POST-only allowlist.
2. Add or extend an integration test proving the FastAPI bridge-UI route accepts
   `DELETE`, offloads the request, forwards the method and resource path, and
   returns the adapter response. It must initially fail with HTTP 405.
3. Preserve an explicit test that an unrelated method remains blocked.
4. Run the focused proxy tests and the Windows PyAutoGUI bridge test group.
5. Perform a live Nextpc regression check by registering a uniquely named
   no-op custom program through the ATR proxy and deleting it through the ATR
   proxy. Confirm it no longer appears in `/programs` afterward.

The live test cleans up its temporary program. It must not run UTM hardware or
modify existing programs or Skills.

## Acceptance Criteria

- A custom program can be deleted from the ATR-hosted bridge console.
- An eligible Skill deletion request can traverse the same proxy method path.
- Direct Nextpc console behavior is unchanged.
- The token remains absent from browser-visible responses and code.
- `PUT` and `PATCH` remain rejected.
- Focused automated tests and the live Nextpc deletion regression pass.

## UTM Readiness Context

The observed UTM readiness failure is separate from this proxy defect. Nextpc
does not currently contain the four required local locator images named
`ready_state`, `start_button`, `running_state`, and `complete_state`. They must
be captured and named during a UTM-specific recording/calibration session (or
captured manually). ATR-side profile names alone do not create the corresponding
files in the Windows bridge data root.
