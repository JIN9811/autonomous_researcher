# Live report read-path optimization

The report endpoint selects owner-declared metadata and state fields **before**
JSON serialization. It reads the existing transcript page without also building
an unused full planning projection. Inputs remain detached from live state;
report shape, owner precedence, decisions and experiment execution are unchanged.
Unspecified third-party report projections retain the full-snapshot fallback.
Owner presentation modules declare `REPORT_METADATA_KEYS` and
`REPORT_STATE_FIELDS`; extend these alongside any new report input.

YAML caching stores **parsing results only**, with an LRU limit of 128 documents
and a 256-Ki-character per-document admission limit. Every lookup reads current
file contents, so edits, atomic replacements, unchanged timestamps, deletion and
invalid YAML take effect immediately. Each caller receives its own deep copy;
schema validation still runs. Neither execution decisions nor live state are
cached. Browser report responses explicitly use `Cache-Control: no-store`.
Refreshing or opening a new window therefore uses the shared server's current
run/transcript rather than a browser-local cached report or reset session.

## Isolated measurement — 2026-09-19

Saved cycle-seven state, same two-CPU affinity, three requests per endpoint.
The clone used a private network/PID namespace, a synthetic `/dev`, a read-only
host filesystem and a private writable clone. An audit hook additionally denied
outbound connections and process launches. Only allowlisted display GETs were
accepted through a Unix socket; production startup hooks were disabled.
No experiment, LLM, printer, ROS or robot action ran in the benchmark.

| Measurement | Before | After |
| --- | ---: | ---: |
| Nine agent reports, median latency range | 1078–1350 ms | 54–59 ms |
| Agent manifests | 148 ms | 48 ms |
| Planning session | 131 ms | 82 ms |
| Display state | 411 ms | 126 ms |
| Mixed reads, four concurrent clients | 2.15 requests/s | 13.10 requests/s |
| Mixed reads, median latency at concurrency four | 2070 ms | 303 ms |
| CPU time for the 15-request concurrent batch | 6.952 s | 1.142 s |
| Process RSS after the batch | 524 MiB | 419 MiB |

All nine saved-state report JSON responses compared exactly equal. RSS figures
are observations from these particular processes, not a memory guarantee; the
baseline process had a longer lifetime. This small benchmark is not a device
throughput or sustained-load claim. Multiple request clients simulate window
traffic; no claim of a Firefox rendering-speed measurement is made.

Regression coverage includes current-state refresh across separate clients,
run identity changes, detached inputs, identical legacy/selected report output,
updated module descriptors, concurrent YAML reads, mutation isolation, same-size
and same-mtime edits, atomic replacement, malformed/deleted files and cache bounds.

This change needs a controlled server reload/restart for deployment. It does not
restart or hotpatch the active experiment automatically.

## ANL and post-GP BO plot refresh

Live GUI requests `/api/bo/config?visualization_only=true` for plot notifications.
This read-only projection serializes only the current run ID, posterior and LHS
payloads, with existing artifact URLs. It does not copy the full run state, load
legacy reports, refit a GP, or change experiment decisions. The full BO Workspace
configuration endpoint retains its existing behavior without this parameter.

The frontend coalesces overlapping plot reads and performs one trailing read
when an event arrives during a request. Owner-report hydration runs separately
from compact session rendering, with a single active background report request
and the latest pending refresh. Late results cannot repaint another run, cycle,
stage, selected agent, or manifest generation. Routine manifest reconciliation
is limited to once per 30 seconds; explicit refresh/new-window discovery remains
immediate. Report requests allow 10 seconds rather than the old 1.2-second BO
timeout; this deadline does not block compact state rendering.

The synthetic BO audit checks LHS completion, GP fitting with eight observations,
refitting after a ninth, posterior/uncertainty/acquisition grids, candidate bounds,
PNG/SVG/CSV/JSON artifacts, and isolated HTTP projection of both GP steps. It
forbids full-state copying or read-triggered refitting and rejects old-run plots.
This is not a live-device or browser-rendering benchmark. Frontend changes apply
on reload; the backend projection requires a controlled server restart.
