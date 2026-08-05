# Common Equipment Workspace and UTM Test Bridge Design

## Purpose

Evolve the current Windows-only equipment page into a common Lab Equipment
Workspace. UTM is the first equipment profile. The existing
`Pyautogui_server_for_window` package remains the only Windows execution
driver for both test and live operation.

## Scope

- Provide one equipment profile contract for connection, test, runtime, and
  evidence.
- Register UTM as the initial profile backed by the existing Windows
  PyAutoGUI bridge.
- Reuse the bridge's `simulate_utm_protocol` mode for test execution.
- Keep live execution on the same endpoints, program IDs, locator contract,
  request log, CSV export contract, and Analysis handoff.
- Expose the contract through the Equipment Workspace and Equipment Agent.

## Non-goals

- Do not create a second virtual HTTP bridge or a second Windows package.
- Do not send arbitrary shell, Python, or PyAutoGUI instructions from ATR.
- Do not change the established physical UTM execution programs during this
  work.
- Do not make non-UTM equipment operational in this increment; the common
  profile registry is the extension point.

## Architecture

### Equipment profile registry

Each equipment profile has a stable `profile_id`, label, bridge provider,
selected bridge target, allowed program IDs, runtime mode, evidence contract,
and Analysis handoff contract. The initial profile is `utm_windows_v1`.

The profile owns:

- bridge identity: saved Windows candidate, URL, and token reference;
- UTM program IDs: start, export, manual export, stop;
- UI locator requirements: ready, start, running, complete;
- result paths: screenshot, Windows request log, exported CSV, Linux artifact;
- readiness requirements and the expected Analysis input schema.

Secrets remain in the existing local connection memory and are never returned
by the GUI or stored in run artifacts.

### Shared bridge contract

The Equipment Agent invokes only the existing Windows bridge endpoints:

- `GET /health`
- `GET /programs`
- `POST /execute`
- `GET /request-log`
- bridge-provided screenshot/evidence operations

The agent passes a registered `program_id` and the selected profile's execution
mode. It never constructs raw desktop automation instructions.

### Test and live mode

Test and live share the exact profile and bridge interface.

| Mode | `simulate_utm_protocol` | Physical Windows UI | Required output |
| --- | --- | --- | --- |
| Test | `true` | No | simulated screen evidence, request log, parseable CSV, Analysis handoff payload |
| Live | `false` | Yes | actual screen evidence, request log, stable exported CSV, Analysis handoff payload |

The selected UTM profile is the only source of truth for both modes. Test mode
may not silently select an unrelated bridge or program. Live mode may not
fallback to simulated execution.

## Workspace Design

The common Lab Equipment Workspace opens the same operator console served by
the selected Windows PyAutoGUI bridge in a separate browser tab. It is not a
recreated UTM control UI. ATR proxies only that saved bridge target and injects
the stored token on the server side, so the browser never receives the token
value. The console's absolute API calls are rewritten into the ATR proxy
namespace.

The workspace has an **Open Windows GUI** action plus four supporting areas.

1. **Windows Bridge Console**: the original Windows-side HTML control panel,
   opened in a separate tab at `/equipment/windows/bridge-ui/` through the
   token-safe ATR proxy.
2. **Equipment list**: selectable registered profiles; initially UTM only.
3. **Connection**: selected bridge target, health, token-authenticated state,
   program inventory, and request-log availability.
4. **Test / Runtime**: setup test, protocol test, live preflight, and approved
   registered program invocation. Buttons report their own in-progress and
   terminal states.
5. **Evidence**: latest screenshot, request-log identity, CSV artifact,
   parse result, and Analysis handoff status.

UTM-specific controls appear only when the UTM profile is selected. A later
device profile uses the same layout but supplies its own program and evidence
definitions.

## Agent and LangGraph Behavior

The Equipment Agent receives the selected equipment profile and run context.
It performs the following bounded sequence:

1. Check selected bridge health and available programs.
2. Validate the mode-specific profile readiness.
3. Run the registered UTM protocol program.
4. Collect screenshot, request-log identity, and CSV evidence.
5. Validate the CSV parse and evidence identity against the current run.
6. Emit `equipment_result`, `utm_data_ready`, and screen evidence only when
   the selected mode's contract succeeds.
7. Handoff to Analysis using the emitted artifacts.

A failed setup or evidence check remains in Equipment and reports the precise
contract failure. It must not emit a successful Analysis handoff.

## Verification

Automated tests must prove:

- test mode requests the selected UTM profile with
  `simulate_utm_protocol=true`;
- live mode requests the same profile with simulation disabled;
- the GUI/API reports the selected profile, bridge state, program inventory,
  evidence, and handoff consistently;
- simulated protocol output contains a parseable CSV and run-linked evidence;
- invalid bridge health, missing program, missing locator, invalid evidence,
  or CSV parse failure blocks Analysis handoff;
- no token value is exposed in response payloads, artifacts, or browser HTML.
- the embedded console uses the selected Windows bridge and routes its API
  calls through ATR without browser-side token injection.

Manual verification will use the common Workspace's UTM profile to execute one
test protocol run and one live preflight only after the Windows bridge is
reachable.

## Acceptance Criteria

- UTM appears as a selectable profile in the common Equipment Workspace.
- Test and live use one selected profile and one existing Windows bridge
  contract.
- Test produces visible, inspectable simulated evidence and an Analysis-ready
  payload without physical UTM control.
- Live cannot run when the selected profile's real bridge, program, locators,
  or evidence contract is invalid.
- A future equipment type can be added by registering a profile rather than
  copying the UTM UI or agent path.
