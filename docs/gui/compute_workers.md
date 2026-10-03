# CPU computation workers

The web server remains the **only controller**. A shared pool of at most three
persistent Python subprocesses runs numerical work. The operating system schedules
them across available CPUs; this is not hard CPU affinity and does not duplicate
the experiment controller. Existing video, robot-display and archival workers are
separate from this four-process controller/compute budget.

## Scope

| Work | Execution location |
| --- | --- |
| Experiment state, LLM decisions, approvals, hardware tools, handoffs | Main controller |
| DSN previews and SPC mesh generation/quality/manufacturability | Shared CPU pool |
| ANL saved-curve parsing, stress–strain and SEA calculations | Shared CPU pool |
| BO GP fit/acquisition optimization and plot artifacts | Shared CPU pool |
| Live robot saved-log streaming and plot rendering | Existing robot display worker |
| Printer and Vision preview video | Existing video worker |

Only named numerical jobs and JSON data cross the private pipes. Workers do not
receive an AgentContext, controller, device registry or LLM credentials. Fresh
interpreters avoid importing a recovery launcher or server as a multiprocessing
main module. No experiment decision, formula, printer option or motion route is
changed by worker selection.

Configure the pool before server startup:

- `ATR_CPU_WORKERS=3` is the default; values 1–3 set the worker limit.
- `0` runs calculations in the main process.
- Restart the server to apply the setting.
- `GET /api/runtime/compute` reports active/queued jobs and process IDs.

Dependent experiment stages remain sequential. Independent requests can use
multiple workers concurrently.

There are at most three active and three waiting jobs. Native BLAS/OpenMP thread
limits are set to one per worker. Jobs have deadlines; cancellation terminates
the numerical subprocess, rejects its result and does not automatically replay
partially completed artifact writes. A subsequent job may create a fresh worker.
The main process rechecks run/experiment/cycle identity and stop flags before
applying asynchronous calculation results. Hardware calls are not retried by this
pool. Full hardware capability isolation is not an OS sandbox: the job allowlist
is trusted application code.

## Validation and cost

`python -m scripts.benchmark_compute_workers` starts its own minimal loopback HTTP
server with synthetic gyroid jobs, never the application bootstrap. It does not
load bridges, use an LLM, print a specimen or move equipment. Output goes into a
new temporary folder. The server and its workers are stopped after measurement.

Measured locally on 2026-09-19, after interpreter warm-up, for three independent
30 mm gyroids (cell 6 mm, wall 0.8 mm, resolution 72):

| Metric | In-process | Three workers |
| --- | ---: | ---: |
| Three-request elapsed time | 17.096 s | 6.214 s |
| Aggregate CPU time | 28.73 s | 18.65 s |
| Average occupied CPU cores | 1.68 | 3.00 |
| Worst concurrent health request | 17,084.7 ms | 2.0 ms |

This is a local synthetic concurrency benchmark, not a guarantee of a 2.75×
speedup for a sequential experiment or an external LLM response. The three warmed
worker processes had a summed RSS of 4,268.7 MiB; RSS includes shared pages and is
not incremental RAM usage. The pool trades bounded extra memory for responsiveness
and parallel computation. Processes are reused, not spawned per browser tab.

Tests compare binary STL hashes, geometry/manufacturability reports, ANL metrics,
GP candidates/posteriors and CSV plot values against the in-process path. PNG,
SVG and CSV artifact creation is also verified, together with queue limits,
cancellation and unchanged fabrication tool payloads.

## Robot display continuity

If the main server has not published fresh context for five seconds, the robot
worker keeps its known session and follows the same saved log. It reports
`publisher_stale`; an active session is marked `stale`, not `idle`.

- An explicit reset or a session change clears the display.
- Parent-pipe EOF shuts down the worker.
- Display freshness does not change robot home detection or physical safety gates.
