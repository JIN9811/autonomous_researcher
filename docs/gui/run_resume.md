# Resume routing and recovery evidence

Use **Resume** when you want to continue the same paused experiment, preserving
its specimen, completed work and failed-attempt evidence. Do not use **Start** as
a substitute: starting a new run is not recovery of the existing physical job.

## Choose the recovery that matches the symptom

Before clicking Resume, open Live GUI, check the run/cycle/specimen in the context
strip, and read the failed owner's Report and Backend trace. Check the actual
device state when a physical command may have been sent. A timeout or missing
screen update does not prove that the command had no effect.

| What you see | What to do next | What recovery may repeat |
| --- | --- | --- |
| SPC timed out, but the printer job was verified started | Follow [existing-printer-job recovery](printer_wait_recovery.md); match the printer task before Resume | Observation of that job, then fresh downstream verification; not slicing/upload/start |
| SPC failed during geometry or file validation before device use | Check the pre-device conditions below, then Resume the same specimen if admitted | SPC manufacturing checks; not Design |
| ActiveCam image review failed after a completed print | Use [Vision review recovery](vision_review_recovery.md); support must establish the eligible boundary first | Fresh Vision capture and the normal downstream tail; not print/ejection |
| `EQUIPMENT_WORKFLOW_SELECTION_REJECTED`, before any Equipment lifecycle event | Use [Equipment selection recovery](equipment_selection_recovery.md); contact support for checkpoint/restore | Equipment selection and the gated tail; not completed fabrication/transfer |
| E-STOP, PLC latch, active safety source, unknown device effect, or a different failure | Leave the run paused; retain evidence and use the device/Guardian recovery path | No generic retry is authorized |

After an admitted Resume, watch the same run's stage and new attempt in Timeline
and the selected owner's Report. If it remains blocked, read the returned reason;
do not delete an old checkpoint, incident, or claim to make it proceed. Save the
run ID, cycle, specimen ID, failure code, execution/session ID and relevant
[artifacts](artifact_preservation.md) for support. A new attempt is not itself a
successful completion; look for the owner's result and downstream verification.

## What Resume guarantees

Resume continues an existing paused task or selects a matching, proven recovery
boundary. It does not start a new run or report success when no task exists.
Repeated clicks on a running task never dispatch a second stage, but they are
not a way to bypass a blocker. Safety flags, active safety sources and the PLC
latch remain authoritative. Closing or refreshing Live GUI does not stop a run.

Prepared ROS, image review, printer-wait, Equipment selection and Guardian
review checkpoints retain their existing handlers. Routing checks the run,
cycle and specimen identity first; old recovery markers remain audit history.
Equipment terminal review still uses its completed-execution evidence.

## SPC retry before device execution

An inactive failed SPC stage can resume the same specimen without repeating
Design. All attempts for that cycle must have complete failed archives and only
geometry/validation/handoff-file calls. Unknown tools, in-flight calls, printer
operations, missing archives, successful attempts or downstream execution block
this path. Even an ambiguous printer request requires job-bound recovery rather
than a blind reprint.

The standard SPC stage runs again, including all manufacturing checks. On success,
the existing cycle series continues from that cycle. A second failure retains the
cycle and pauses at the error. No error record, specimen history or measurement
is deleted, and no permanent cycle limit is introduced.

## Guardian after recovery

Failure memory is historical reference, not a current design interlock. Current
design constraints, device health, safety controls and unresolved gate evidence
still block as before.

A manufacturing rejection is resolved only by a later passing SPC attempt for
the same run, experiment, cycle and specimen. Both attempts must have explicit
execution identities. The new evidence must include passing geometry, mesh and
wall checks, plus the measured STL hash. Other hazards and unbound legacy records
remain unresolved. The original decision is retained and linked to the resolving
gate, with matching incidents marked resolved rather than deleted.

Deployment does not migrate or hot-patch an active loop. Changes take effect at
the next controlled server deployment; existing jobs must be preserved and
restored using their corresponding recovery boundary.

## Completed-loop chat history

All completed loops remain listed independently of the bounded live-message
cache. A browser loads older transcript pages once per run and retains only
message text and identity, not large agent payloads. Refreshing reconstructs
the list; changing runs clears the prior run's history. Replay stays isolated.
At most three chat groups, including Loop Complete groups, may be expanded.
