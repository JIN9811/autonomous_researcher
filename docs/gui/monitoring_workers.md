# Isolated Live GUI monitoring

The experiment controller remains a **single process**. Do not increase Uvicorn
application workers: that would duplicate in-memory run state and device owners.

Local HTTP browser sessions use two lazy, read-only subprocesses instead:

- **Printer video:** shared latest-frame decoder and direct MJPEG HTTP delivery,
  targeting 30 FPS at 960 px width. Slow viewers skip old frames; no video history
  is retained. Up to eight viewers share the source. The decoder closes after
  15 seconds without consumers. This is a target, not a guarantee of camera/LAN
  throughput, and memory overhead is bounded, not zero.
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
