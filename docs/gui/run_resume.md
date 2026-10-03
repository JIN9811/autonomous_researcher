# Resume routing and recovery evidence

Resume continues an existing paused task or selects a matching, proven recovery
boundary. It does not start a new run or silently report success when no task
exists. Running tasks are idempotent: repeated clicks never dispatch a second
stage. Safety flags, active safety sources and the PLC latch remain authoritative.

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
