# Active Cam Run Artifact Persistence Design

## Goal

Treat every successful Active Cam frame as a normal run artifact. The Live GUI
must keep showing the most recent successful frame until the next Active Cam
attempt finishes. A successful attempt replaces the displayed frame; a failed
attempt clears the displayed frame while preserving prior files in the run
artifact history.

## Scope

- Vision Agent Active Cam captures used during the closed loop.
- Existing `runs/<run_id>/vision/<observation_id>/` evidence directory.
- Existing Vision report, evidence reference, controller metadata, and Live GUI
  rendering paths.
- No second camera implementation, frontend Base64 cache, or standalone Active
  Cam storage hierarchy.

## Artifact Contract

On a successful Active Cam capture, Vision Agent copies the source image into
the current observation artifact directory:

```text
runs/<run_id>/vision/<observation_id>/active_cam_capture.<source-extension>
```

The copied file is registered alongside `detection.json` and `scene_map.svg` in
the existing Vision evidence contract. The report exposes:

- immutable run-local `capture_path`
- artifact-serving URL
- run ID, observation ID, loop index, specimen ID, camera key, dimensions, and
  capture timestamp
- an evidence reference with type `active_cam_capture`

The source file may reside under `/tmp` or another camera runtime directory,
but that transient source path is not the canonical run artifact.

## Runtime State

The controller stores the latest successful Active Cam artifact descriptor in
run metadata. Non-Vision stages and ordinary polling do not clear or replace
this descriptor, so the same image remains visible while the loop advances.

State transitions are:

1. No attempt yet: no frame is displayed.
2. Capture running: retain the previous successful frame.
3. Capture succeeds: register the new run artifact and replace the latest
   descriptor.
4. Capture fails: clear the latest display descriptor and show the failure
   state. Previously written artifacts remain available in run history.

The display pointer is current-state data; the artifact ledger is immutable
historical evidence.

## Live GUI

The Active Cam card resolves its image from the latest run-artifact descriptor
first and the current Vision report second. It never relies on a browser-only
cache for persistence. Unique run-local paths prevent stale browser image
caching.

The card keeps the last frame while a new capture is in progress. On failure it
renders the failed/blocked state without the previous image. On success it
switches to the newly registered artifact.

## Error Handling

- Missing or unreadable source image makes artifact persistence fail for that
  attempt and clears the displayed frame.
- A failed copy must not overwrite or delete earlier run artifacts.
- Paths must remain inside the configured run root before they are exposed by
  run artifact APIs.
- Failed artifact persistence is recorded in Vision evidence and must not be
  silently represented as a successful capture.

## Verification

- Unit test: successful capture is copied into the observation run directory
  and registered as `active_cam_capture` evidence.
- Unit test: a subsequent non-Active-Cam state keeps the current descriptor.
- Unit test: a subsequent failed Active Cam attempt clears the display
  descriptor but leaves the prior file intact.
- Controller test: Vision merge preserves the descriptor across other agent
  handoffs and replaces it only with an explicit Active Cam result.
- Frontend test: the card prefers the run artifact URL and renders no image for
  an explicit failed attempt.

