# Resuming an existing printer job

Use this guide when the run paused after a printer completion timeout but the
printer task was already verified started. The objective is to finish observing
that exact job, not to manufacture another specimen.

## Continue without starting another print

1. In Live GUI, open the SPC report and confirm the run, cycle and specimen.
   Inspect its printer task identity and the completion-timeout evidence.
2. Compare that task with the printer's actual job and current state. If the
   identity is missing or different, or the effect of a prior request is unknown,
   leave the run paused and ask the operator responsible for the printer to
   investigate. Do not upload or publish another job as a diagnostic.
3. For an eligible paused run observing that verified job, use **Resume**. It checks
   the retained `printer_wait_recovery` record and normal safety gates.
4. Watch the same task through completion in SPC. The resumed path observes the
   existing print; it does not slice, upload or start a replacement. Fresh Vision
   and the normal downstream stages must still pass before the cycle is complete.

If Resume refuses, retain its failure code and the run/specimen/task IDs. A
printer percentage of 100%, an upload acknowledgement, or an old camera image is
not a substitute for completion evidence. Follow the
[recovery chooser](run_resume.md) if the failure is not a completion timeout.

## Why the wait can be longer than expected

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

## Support: preserve a timeout across a restart

Do not restart an active server merely to refresh the display. This procedure
requires an explicitly authorized restart and the inactive timeout boundary.
For that boundary, `python -m
app.printer_wait_recovery RUN_ID` preserves the inactive timeout boundary under
`runs/RUN_ID/recovery/printer_wait.json`. Restoration through
`POST /api/runs/RUN_ID/recovery/restore-printer-wait` requires a fresh idle server
and validates checkpoint, sliced artifact, owner result and transcript integrity.
Restoration alone performs no device action; Resume is separate.

The restart-recovery checkpoint currently requests a **one-cycle-only** review:
after the current cycle returns it pauses before any next design/print. This is
an explicit recovery-request flag, not a change to experiment cycle defaults.
Ordinary in-session timeout recovery retains the configured loop sequence.

## If only the monitor looks stale

Live printer monitoring runs independently of agent running/error/idle status,
throttles requests to two seconds, and releases stalled requests after 15 seconds.
Replay pages never poll live printer state. Reload existing browser tabs to load
updated frontend monitoring code.
