# Recorded PyAutoGUI Image Locator Design

## Objective

Make image-based target tracking the default replay contract for newly recorded
PyAutoGUI Equipment Skills. A recorded click or drag must follow the visible UI
target when its screen coordinate changes. Coordinate replay remains available
only for legacy recordings or when an operator explicitly enables it.

## Scope

- Capture visual evidence at mouse press and release.
- Generate bounded tight and contextual crops for clicks and drag endpoints.
- Preserve locator assets inside the portable recording and Skill definition.
- Resolve recorded image candidates before executing click, move, or drag.
- Save current-screen evidence when a required target cannot be found.
- Expose locator readiness and previews in the Windows Program Manager.

This change does not add arbitrary Python, shell execution, password entry,
window closing, file deletion, or process termination.

## Recording Contract

New recordings use `schema=atr.equipment_recording.v2` and contain:

```json
{
  "visual_locator_policy": {
    "mode": "image_first",
    "required_for_pointer_actions": true,
    "coordinate_fallback": false
  }
}
```

Each mouse click contains a `visual_locator`. A drag contains
`source_visual_locator` and `target_visual_locator`. Each locator contains:

- a stable locator ID,
- the recorded coordinate as evidence,
- a tight PNG crop centered on the pointer,
- a larger contextual PNG crop centered on the pointer,
- SHA-256, dimensions, crop origin, and confidence for each candidate,
- capture status and failure detail.

The original full frame is saved under the recording directory as local
evidence. It is not embedded in the Skill payload. The bounded crops are
base64-encoded in the recording so the Linux ATR server and a different Windows
bridge can receive the same portable Skill without sharing a filesystem.

## Capture Rules

- Click: capture on mouse press; use the release coordinate as the recorded
  coordinate when movement remains below the drag threshold.
- Drag: capture the source on press and destination on release.
- Tight crop: 64 x 64 pixels, clamped to the screen.
- Context crop: 192 x 128 pixels, clamped to the screen.
- Capture failures are explicit (`status=unavailable`) and never fabricate an
  image locator.
- New image-first recordings cannot be converted into a runnable draft while a
  required pointer locator is unavailable, unless the operator explicitly
  enables coordinate fallback for that recording.

## Replay Rules

1. Materialize inline PNG candidates into the bridge locator cache using their
   SHA-256 as the filename.
2. Try the tight crop, then the contextual crop.
3. Execute against the center of the first matched image.
4. A click uses the matched target directly.
5. A drag moves to the matched source, then drags to the matched destination.
6. If all candidates fail, save a current-screen screenshot and return
   `UI_LOCATOR_NOT_FOUND` with locator and evidence identifiers.
7. Do not execute recorded coordinates unless `coordinate_fallback=true` is
   explicitly present.

Legacy `atr.equipment_recording.v1` recordings continue to compile as coordinate
programs. This compatibility rule does not change the default for new recordings.

## Payload Limits

- PNG only; decoded bytes must start with the PNG signature.
- Maximum 256 KiB per crop.
- Maximum 32 MiB of inline locator data per recording.
- Maximum 200 pointer events with embedded locator assets.
- SHA-256 is verified before materialization.

These limits prevent a long recording from exhausting bridge memory or disk.

## Program Manager UX

The Record workspace shows:

- `Image tracking` enabled by default,
- `Coordinate fallback` disabled by default,
- locator coverage as `ready / pointer events`,
- tight and contextual previews for the selected recording,
- a visible blocked state when any required locator is unavailable.

The UI must not expose full-frame evidence by default because it may contain
unrelated desktop content. Full frames remain available in the local recording
artifact directory for operator review.

## Safety And Failure Semantics

- PyAutoGUI FAILSAFE remains enabled.
- Held mouse buttons and keys are released on every execution exit.
- Missing locators fail closed for image-first recordings.
- No silent coordinate fallback.
- A failed match records the current screen, candidate hashes, target ID, and
  attempted confidence values.
- Existing popup, window focus, retry, and Guardian contracts remain intact.

## Verification

- Unit tests for click and drag capture crops.
- Unit tests for capture failure and payload bounds.
- Compiler tests proving image-first actions omit executable coordinates.
- Executor tests proving click, move, and drag resolve image candidates.
- Failure tests proving no coordinate click occurs after a locator miss.
- HTTP lifecycle test from recording through draft creation.
- Source/install bridge byte-parity test.
- Selenium/browser inspection of the Record workspace.
