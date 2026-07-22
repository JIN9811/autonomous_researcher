# Active Cam Grounded Specimen Detection Design

## Objective

Make the Vision Agent Active Cam card show a specimen decision that is grounded in the exact displayed capture. Add a UTM-style bounding box and prevent later Vision stages from pairing an earlier image with a newer unrelated `not_configured` or negative status.

## Scope

- Detect the specimen in each fresh Active Cam capture.
- Restrict detection to the A4 work area so red robot parts outside the workspace do not become false positives.
- Save the raw capture, annotated capture, bounding box, center, confidence, and decision as one run artifact.
- Render the annotated capture and its matching decision in the Active Cam card.
- Preserve that evidence until a newer Active Cam attempt produces a replacement result.
- Keep the UTM card, robot control loop, rollout selection, and agent ordering unchanged.

## Architecture

### Detection

The existing deterministic UTM specimen-presence detector remains the common image-analysis implementation. It gains a path/image entry point and optional region of interest. The Active Cam path invokes it on the captured frame using an A4 workspace ROI. Bounding-box coordinates are returned in full-frame coordinates.

The detector produces:

- `specimen_detected`
- `bbox_xyxy`
- `center_px`
- `confidence`
- `detector`
- raw and annotated image paths

### Evidence ownership

An Active Cam capture and its detector result form one immutable evidence record. `latest_active_cam_artifact` stores both the image references and the decision fields. A later post-placement Vision invocation may update the current Vision report, but it must not reinterpret the stored Active Cam image with unrelated status fields.

A newer successful Active Cam capture replaces the artifact. A newer completed no-specimen capture also replaces it with a negative artifact. A capture failure follows the existing failure-clearing rule and must not display stale evidence as current.

### Frontend rendering

The Active Cam card selects one canonical evidence object:

1. Use the current Active Cam result when it refers to the displayed capture.
2. Otherwise use the persisted Active Cam artifact and all of its matching decision fields.

The card displays the annotated image containing the green bounding box and center marker. `Detected`, placement status, frame dimensions, camera, and capture path all come from that same evidence object.

## Error handling

- A readable frame with no qualifying component is a valid `not detected` result, not a transport error.
- An unreadable or missing capture is a capture failure and does not fabricate a detection result.
- If A4 marker localization is unavailable, detection uses a bounded normalized workspace ROI rather than the full image.
- No status-only fallback may convert a captured frame into a positive specimen decision.

## Verification

- Unit test the shared detector with a specimen inside the workspace and red robot parts outside it.
- Unit test an empty Active Cam frame as `not detected`.
- Unit test Vision artifact persistence for detection metadata and annotated output.
- Test that a later `not_configured` Vision report cannot change the decision paired with an earlier persisted image.
- Run the detector against the recorded positive frame from `run-20260722T055601Z-fbd01a` and its earlier empty frame.
- Visually inspect the generated annotated positive and negative images.
- Run relevant Vision, controller, frontend static, and JavaScript syntax tests.

## Success criteria

- The visible specimen in the recorded positive frame is boxed and reported as detected.
- The recorded empty frame is reported as not detected.
- The bounding box does not select the red gripper components outside the A4 workspace.
- The Active Cam image and all displayed status values always refer to the same capture.
- No unrelated runtime or hardware-control behavior changes.
