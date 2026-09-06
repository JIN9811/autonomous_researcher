# Test-Mode Execution Profiles and Operator-Teleop Handoff Design

## Goal

Provide a persistent, operator-editable test-mode settings surface from the main GUI. The settings select, per test path, which agent-owned devices execute physically and which stop at validated preflight. They also control printer-body, cooldown, and auto-ejection behavior without changing the closed-loop agent sequence.

The settings UI belongs to the main GUI, not the Live GUI. Runtime approvals that arise from a hybrid physical/virtual chain remain visible through the runtime event surfaces, while teleop completion is confirmed in a handoff-specific Manipulation Bridge popup.

## Entry point and settings window

The main GUI Run Control adds a `Test Mode Settings` button immediately after `GPU Clear`. It opens `/test-mode-settings` in a separate popup window, following the existing printer and equipment workspace behavior.

The settings page has one tab for each existing test printer path:

1. `Virtual Bridge` (`virtual_bridge`)
2. `Installed Printer` (`installed_printer`)
3. `Physical Print` (`physical_print`)

Each tab edits an independent persistent profile. Saving one tab does not alter the others. The page shows the stored revision, last-updated time, validation errors, and whether changes apply to the next run. An active run always uses the profile snapshot resolved at run start; editing a profile never mutates an in-flight cycle.

## Profile model

Profiles are stored server-side in `memory/test_mode_execution_profiles.json` so they survive browser and server restarts and remain shared across main-GUI and Live-GUI sessions. Writes use validated whole-document replacement through a temporary file and atomic rename.

The stored document uses this logical shape:

```json
{
  "schema": "test_mode_execution_profiles.v1",
  "revision": 1,
  "profiles": {
    "virtual_bridge": {
      "agents": {
        "specimen": {"device_mode": "virtual"},
        "vision": {"device_mode": "virtual"},
        "manipulation": {"device_mode": "virtual"},
        "lab_equipment": {"device_mode": "virtual"}
      },
      "printer_flow": {
        "print_body": "execute",
        "cooling_wait": "execute",
        "auto_ejection": true
      },
      "handoff": {
        "strategy": "operator_teleop"
      }
    }
  }
}
```

Allowed `device_mode` values are `virtual` and `real`. The GUI labels them `Preflight only` and `Real device`. Turning a device off therefore does not remove its agent or fabricate completion: the agent still validates its intended payload and emits its existing typed preflight handoff.

The resolver maps device modes to the internal execution policy:

| GUI agent row | Device boundary | Internal policy key |
|---|---|---|
| SpecimenMakingAgent | selected 3D printer | `printer` |
| VisionAgent | active robot camera | `vision` |
| ManipulationAgent | VLA/robot actuation | `manipulation` |
| LabEquipmentAgent | UTM, Windows bridge, and equipment-owned UTM observation | `lab_equipment` |

`virtual` maps to `preflight_only`; `real` maps to `execute`. CAE, Analysis, Knowledge, BO, Design, and Guardian remain enabled because they do not own the physical boundaries configured here. Existing per-device confirmation, Guardian, PLC, freshness, connection, and safety gates still apply when a row is set to `real`.

The Vision row controls pickup/active-camera perception. A post-teleop UTM placement capture is equipment-owned: when Lab Equipment is real, that mandatory UTM capture still executes even if pickup Vision is set to preflight-only. This exception applies only to the bounded post-manipulation verification and cannot enable robot actuation.

The internal execution policy accepts the new `vision` key. Legacy specifications without a saved-profile snapshot retain current behavior.

## Built-in defaults

The file is created lazily from safe built-in defaults when it does not exist or is empty.

| Profile | Printer | Vision | Manipulation | Lab Equipment | Print body | Cooling | Auto-ejection |
|---|---|---|---|---|---|---|---|
| Virtual Bridge | Virtual | Virtual | Virtual | Virtual | Execute locally | Execute locally | On |
| Installed Printer | Real | Real | Real | Real | Skip | Skip | On |
| Physical Print | Real | Real | Real | Real | Execute | Execute | On |

“Execute locally” in the virtual profile means the immutable sliced artifact can retain and validate the full print/cooldown sequence; it does not authorize a physical upload or start.

The settings page provides `Restore this profile` and `Restore all profiles` actions. Restoring is explicit and goes through the same validation and revision rules as saving.

## Printer-flow constraints

The printer-flow controls are:

- `print_body`: `execute` or `skip`
- `cooling_wait`: `execute` or `skip`
- `auto_ejection`: boolean

The following invariants are enforced by both the API and the runtime resolver:

1. `cooling_wait=skip` is allowed only when `print_body=skip`.
2. If `print_body=execute`, the resolver forces or requires `cooling_wait=execute`; an unsafe saved payload is rejected rather than silently weakened.
3. A real printer with `print_body=skip` requires `auto_ejection=true`, because the only valid physical job in that combination is the validated ejection-only project file. To perform connection/preflight without any job, the printer row must be `virtual`.
4. `print_body=skip` selects the ejection-only artifact path and removes extrusion/print-body commands.
5. `cooling_wait=skip` omits the `M190` cooldown command only from that ejection-only artifact and records `atr_cooldown_wait_policy=not_required_no_print_body`.
6. Full physical-print artifacts and every other auto-ejection path keep the configured cooldown wait unless the resolved profile explicitly satisfies rules 1–5.
7. Printer-body and cooldown settings never bypass artifact hashing, post-write validation, upload hash checks, start confirmation, or motion validation.

The existing installed-printer behavior is therefore represented as a normal stored profile instead of a hard-coded exception.

## Profile resolution and precedence

At the beginning of a test-mode run, the controller resolves the selected path and snapshots the matching profile into the experiment specification:

```json
{
  "test_mode_profile": {
    "schema": "resolved_test_mode_execution_profile.v1",
    "profile_id": "installed_printer",
    "source_revision": 4,
    "source_sha256": "...",
    "resolved_at": "...",
    "agents": {},
    "printer_flow": {}
  },
  "execution_policy": {}
}
```

Precedence is:

1. built-in safe defaults;
2. saved profile for the selected test path;
3. an explicit, validated one-shot API override supplied by a caller or test;
4. final safety validation, which may reject but never silently weaken a required gate.

Selecting `installed_printer` or `physical_print` no longer overwrites every device stage with `execute`. It selects the saved profile, and each agent row remains independent. The resolved profile and execution policy are static closed-loop constraints and survive BO recommendations and redesign cycles unchanged.

Only new test-mode runs consume newly saved settings. Live mode, replay, fault injection, standalone device workspaces, and an already-running test remain unaffected.

## Hybrid virtual/real chains

The controller derives whether a physical specimen exists at every material handoff. A downstream real device cannot consume a handoff whose upstream device performed no physical actuation.

### Operator-teleop handoff rule

When virtual autonomous Manipulation is followed by real Lab Equipment, the controller inserts a mandatory operator-teleop handoff gate before the first downstream actuation. It does not relabel the virtual VLA result as a physical completion. `manipulation.device_mode=virtual` disables autonomous policy actuation; it does not prevent a separately confirmed operator from controlling the same robot through the existing LeRobot leader/follower teleoperation boundary.

The initial supported `handoff.strategy` is `operator_teleop`. The settings page stores and displays it explicitly so a future strategy cannot silently replace it. It is not an autonomous fallback: the runtime must pause and wait for the operator to start and finish the teleop session and then confirm completion in the Manipulation Bridge popup.

The primary supported case is:

```text
Manipulation virtual/preflight
  -> operator teleop transfer required
  -> existing LeRobot live teleop starts with explicit confirmation
  -> operator moves the identified specimen into the UTM
  -> teleop stops and returns robot/camera ownership
  -> operator clicks Teleop Complete in the Manipulation Bridge popup
  -> equipment-owned UTM vision performs a fresh placement check
  -> Lab Equipment real execution may start
```

The gate records a typed payload:

```json
{
  "schema": "operator_teleop_handoff.v1",
  "status": "confirmed",
  "run_id": "...",
  "specimen_id": "...",
  "candidate_id": "...",
  "source_stage": "manipulation",
  "target_stage": "lab_equipment",
  "source_actuation_performed": false,
  "target_device": "utm",
  "handoff_strategy": "operator_teleop",
  "teleop_session_id": "...",
  "teleop_started_at": "...",
  "teleop_stopped_at": "...",
  "teleop_stop_verified": true,
  "robot_port_released": true,
  "camera_returned_to_vision": true,
  "confirmed_by": "local_operator",
  "confirmed_at": "...",
  "vision_verification": {}
}
```

The run pauses with `pending_operator_teleop_handoff` and opens or links to a handoff-scoped Manipulation Bridge popup at `/lerobot?handoff_token=<token>&run_id=<run_id>#teleoperation-card`. The existing LeRobot page validates the token against the server-held pending handoff and renders the teleop controls plus a dedicated completion panel. Starting the session calls the existing `lerobot.teleoperate.start` boundary in live mode with its normal explicit execution confirmation and selected robot profile. The operator may stop teleop explicitly, but stopping teleop alone does not resume the agent loop.

The Manipulation Bridge popup keeps a `Teleop Handoff` panel visible with the active run, cycle, specimen, candidate, source, and target. Its `Teleop Complete` action is disabled until a matching session exists. When clicked, it first calls the same existing `lerobot.teleoperate.stop` endpoint used by the normal Teleop Stop control, even if the session was already stopped. Only after that idempotent stop response proves the matching session is `STOPPED`, the robot port is released, and camera ownership has returned does it call the bounded teleop-handoff confirmation API. The controller independently re-reads the bridge status and requires the same evidence plus the current handoff token before it requests a fresh target-side placement observation. The popup displays the confirmation result and may close after the controller accepts it.

Only the explicit GUI confirmation followed by a successful, non-stale UTM placement observation releases the Lab Equipment execution gate. The confirmation must match the active run, cycle index, specimen, candidate, source, target, handoff token, and teleop session. Cancel, timeout, identity mismatch, mismatched or still-active session, unverified stop, unreleased port, camera ownership failure, stale signal, missing image evidence, or negative detection stops the cycle with a stable failure code.

The confirmation resumes the same paused coroutine and preserves the existing `run_id`, `cycle_index`, `specimen_id`, `candidate_id`, and accumulated agent state. It does not start a new run, repeat Design/Specimen, or create a one-off execution route. Refreshing or temporarily closing the Live GUI does not discard the server-held pending handoff.

Settings remain in the main-GUI popup. The runtime-only teleop transfer and completion confirmation are presented in the Manipulation Bridge popup and recorded in the normal runtime event stream. The Live GUI remains a read-only status mirror for this handoff and does not own its confirmation button. The settings page never starts teleoperation or confirms completion.

If the printer was virtual or its print body was skipped, the system cannot assume that a physical specimen exists for teleoperation. Before teleop starts, the operator must confirm that the matching external specimen has been placed in the configured robot pickup area; a fresh pickup-side Vision observation must then confirm it. This materialization gate is distinct from the subsequent robot teleop transfer.

### Other combinations

| Combination | Resolution |
|---|---|
| Printer virtual or print body skipped, then any real specimen-consuming stage | Require matching external-specimen materialization plus pickup-side Vision evidence before teleop or the first real consumer. |
| Vision virtual, Manipulation real | Block robot actuation unless another existing validated pose provider is explicitly selected; an operator click alone cannot replace robot pose evidence. |
| Manipulation virtual, Lab Equipment real | Require a separately confirmed live LeRobot teleop session, verified stop/port return, and fresh equipment-owned UTM Vision verification. |
| Manipulation real, Lab Equipment virtual | Allow with a warning; robot actuation occurs, UTM stops at preflight. |
| All physical stages virtual | Run the existing safe preflight closed loop without device actuation. |
| All physical stages real | Run the normal guarded physical chain. |

The settings page previews derived requirements and invalid combinations before save. A valid but asymmetric profile displays warnings; an unsafe profile is rejected.

## API and persistence boundary

The main application exposes:

- `GET /api/test-mode-execution-profiles`: return defaults merged with stored profiles, revision, hash, and validation state.
- `PUT /api/test-mode-execution-profiles/{profile_id}`: validate and atomically save one complete profile with optimistic `expected_revision`.
- `POST /api/test-mode-execution-profiles/reset`: restore one or all built-in profiles.
- `GET /test-mode-settings`: serve the popup settings page.
- `GET /api/planning/runs/{run_id}/teleop-handoff?handoff_token=...`: return the bounded handoff context consumed by the Manipulation Bridge popup.
- `POST /api/planning/runs/{run_id}/teleop-handoff/confirm`: validate the current handoff token and stopped teleop session, release the same paused coroutine specifically to its mandatory target-side Vision verification, and keep Lab Equipment blocked until that verification succeeds.

The API never accepts arbitrary paths, unknown agents, unknown modes, unknown printer-flow values, or extra execution commands. A stale `expected_revision` returns a conflict instead of overwriting another settings window.

The profile store owns schema validation, defaults, hashing, revisions, and atomic persistence. The controller depends only on its read/resolve interface. Agent modules continue to consume the resolved execution policy and typed handoff data rather than reading the file directly.

## UI behavior

Each profile tab contains:

1. four agent/device cards with a `Preflight only / Real device` segmented control;
2. a printer-flow card for print body, cooling wait, and auto-ejection;
3. a handoff-strategy control fixed initially to `Operator teleop`, plus a derived-flow summary showing physical stages, preflight stages, required teleop/materialization gates, warnings, and blockers;
4. Save, Reload, and Restore controls.

The UI disables the cooling-skip choice while print body is enabled and explains why. It does not hide invalid dependencies conditionally: every setting stays visible, with disabled state and an inline reason where appropriate. Save success reflects the server-returned revision; local browser state alone is never treated as saved configuration.

## Runtime and failure semantics

- Profile load failure falls back to built-in safe defaults and emits an operator-visible warning.
- Invalid stored data is not partially applied.
- A missing path selection keeps the existing printer-path selection request; no profile is guessed.
- A saved `real` device mode is authorization to reach that device's existing confirmation gate, not authorization to bypass it.
- An active run reports the resolved profile ID, revision, and hash in state and artifacts for reproducibility.
- Teleop handoff confirmation is single-use and cycle-bound. Neither its confirmation nor its session ID can be replayed for another specimen or BO iteration.
- A stopped teleop session never advances the cycle until the operator clicks the GUI confirmation action.
- `Teleop Complete` always terminates teleoperation through the ordinary Teleop Stop endpoint before it attempts confirmation; it does not implement a second stop path.
- Emergency stop, stop, or reset stops the associated teleop session when possible and invalidates every pending handoff token.

## Verification

Implementation follows test-driven development and does not contact hardware.

1. Store tests cover missing-file defaults, round-trip persistence, atomic replacement, stale revision conflicts, unknown fields, unsafe print/cooling combinations, and reset behavior.
2. API tests cover the popup route plus GET, PUT, and reset responses.
3. Frontend tests cover the Run Control button, settings popup opening, all visible controls, per-tab independence, server save/reload, dependency messages, derived operator-teleop handoff previews, handoff-scoped Manipulation Bridge popup state, and the disabled/enabled Teleop Complete action.
4. Controller tests prove each path resolves the correct saved profile, explicit one-shot overrides obey precedence, selection no longer forces unrelated devices real, and the snapshot survives BO redesign.
5. Printer tests prove print-body/cooling skip affects only the resolved ejection-only path and that full printing retains cooldown.
6. Agent tests install tripwires at printer, Vision, VLA, and UTM physical calls and verify every virtual row stops before its own device boundary.
7. Hybrid tests prove virtual Manipulation plus real Lab Equipment pauses before UTM; starts no teleop without explicit operator confirmation; does not resume when teleop merely stops; rejects wrong identity, wrong cycle, wrong token, wrong session, active/unreleased sessions, and stale evidence; accepts one GUI confirmation for a matching stopped teleop session plus fresh UTM Vision evidence; resumes the same cycle without repeating prior agents; and cannot reuse the confirmation in the next cycle.
8. A hardware-free closed-loop matrix test covers the default three profiles and representative hybrid combinations.

## Compatibility and non-goals

- No agent is removed from the graph by these switches.
- This design does not add arbitrary graph editing to the settings window.
- This design does not weaken live-mode safety or confirmation requirements.
- This design does not claim that an operator confirmation or teleop session alone establishes a robot-safe pose or valid UTM placement.
- Existing configuration files and legacy test callers remain valid; saved profiles are additive and test-mode-only.
- The current uncommitted installed-printer cooldown change is preserved and becomes the implementation basis for the stored skip policy.
