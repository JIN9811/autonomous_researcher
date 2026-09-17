# Resuming an existing printer job

Printer completion deadlines use the selected sliced artifact's duration (Bambu
`Metadata/slice_info.config` prediction in seconds, or a supported G-code header),
plus 25% or at least 15 minutes. A longer printer-reported remaining time takes
precedence. Geometry/design proxy estimates are not treated as slicer timings.
Explicit timeout overrides remain supported; an unknown duration uses a bounded
six-hour fallback.

After a completion timeout with a verified started task, the current run keeps a
`printer_wait_recovery` record and pauses. The existing **Resume** control checks
the run, specimen, cycle, printer task identity and safety gates, then observes
the existing print to completion. It does not slice, upload or start a new print.
Fresh Vision and the normal downstream stages still run; no completion evidence
is fabricated. Concurrent Resume requests cannot create duplicate workflows.

For an explicitly authorized server restart, `python -m
app.printer_wait_recovery RUN_ID` preserves the inactive timeout boundary under
`runs/RUN_ID/recovery/printer_wait.json`. Restoration through
`POST /api/runs/RUN_ID/recovery/restore-printer-wait` requires a fresh idle server
and validates checkpoint, sliced artifact, owner result and transcript integrity.
Restoration alone performs no device action; Resume is separate.

The restart-recovery checkpoint currently requests a **one-cycle-only** review:
after the current cycle returns it pauses before any next design/print. This is
an explicit recovery-request flag, not a change to experiment cycle defaults.
Ordinary in-session timeout recovery retains the configured loop sequence.

Live printer monitoring runs independently of agent running/error/idle status,
throttles requests to two seconds, and releases stalled requests after 15 seconds.
Replay pages never poll live printer state. Reload existing browser tabs to load
updated frontend monitoring code.
