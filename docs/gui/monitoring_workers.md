# Isolated Live GUI monitoring

Use this guide when printer video or robot telemetry looks stale while the
experiment is still running. These displays observe the controller; closing a
window, losing video, or stopping a display worker does not stop the experiment.

## Decide whether the problem is presentation or execution

1. Check Live GUI's run/session identity, sync status and the owner's Report and
   Timeline. Compare the displayed observation time with the current task.
2. If robot display reports `publisher_stale` or `stale`, treat the visible pose
   and plot as retained history. A five-second context-publication delay can
   leave the worker following its known session; that is not fresh home evidence.
3. After an approved frontend deployment, reload the page to obtain the current
   monitoring bundle. If the same symptom remains, retain the run/session ID,
   timestamps and blocker for support. Do not start a second camera reader or
   robot session just to compare the pictures.
4. If device execution itself failed, use the owner's recovery path, not a
   monitoring restart. Emergency/stop controls and their confirmation remain
   separate from closing the GUI.

A later fresh update can restore the display. It does not retrospectively prove
that an old image or pose met a physical gate. Replay is intentionally isolated
from these live transports and will not become live after a refresh.

## Maintainer architecture

The experiment controller remains a **single process**. Do not increase Uvicorn
application workers: that would duplicate in-memory run state and device owners.

Local HTTP browser sessions use two lazy, read-only subprocesses instead:

- **Video (printer and Vision preview):** shared latest-frame decoder and direct MJPEG HTTP delivery,
  targeting 30 FPS at 960 px width. Slow viewers skip old frames; no video history
  is retained. Up to eight viewers share the source. The decoder closes after
  15 seconds without consumers. This is a target, not a guarantee of camera/LAN
  throughput, and memory overhead is bounded, not zero.
  Vision's existing ROS MJPEG subscriber and byte-for-byte multipart delivery are
  hosted in this same video worker (up to four topic/FPS/quality configurations).
  Each topic retains only the latest frame; multiple viewers share its subscriber.
  Runtime shutdown/reload releases only the Vision sources, not printer video.
  Source configuration travels over the private parent pipe, not a browser API.
  Raw decision capture, ROI settings, capture timing, LLM inputs, verification
  conditions, and ROS runtime ownership remain on their existing paths. This
  isolates presentation, **not** the Vision agent or its decision processing.
- **Robot telemetry:** tails the existing motor action log, streams measured and
  requested joint samples, and produces policy-tracking graph artifacts on session
  completion. It has no robot command, serial, camera acquisition, inference, or
  replay control endpoint. Browser 3D rendering remains separately capped at 15 FPS.

The robot worker receives only selected session identity, log path, reset epoch,
and manipulation display state through a private stdin pipe, twice per second.
Reset/session changes clear its reader. A stale feed is not advertised as live.
Reconnection reads saved history in bounded batches without dropping graph points.

Each subprocess has its own interpreter/GIL and may run on a different CPU core;
there is no fixed CPU affinity. Workers bind only to loopback on ephemeral ports,
use unguessable capability URLs, and enforce the parent origin for WebSockets.
Camera credentials are passed over stdin, never in the worker command line.
They terminate with the owning server; closing a GUI does not stop an experiment.

Remote/HTTPS clients retain same-origin monitoring. Set `ATR_MONITOR_WORKERS=0`
before server startup to use the original monitoring transport everywhere.
Do not open additional RTSPS readers to compare performance during a live run:
camera connection limits and LAN contention can affect both viewers.

## Display projection and deployment

Main GUI and Runtime IDE request `/api/state?view=display`, which projects fields
before serialization. `/api/state` retains full-fidelity recovery output.
Repeated graph owner lookups reuse one resolution only during the synchronous
setup display call; the next call rereads graph files. No execution admission,
completion criterion, device command path, or experiment timeout changes.

Backend changes require a controlled server restart at an operator-approved safe
boundary. Updating files does not activate workers in an already-running server.
Refresh the GUI after deployment to load the new telemetry bundle.
