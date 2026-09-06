---
doc_type: reference
subtype: runtime
status: active
authority: descriptive
audience:
  - developer
  - operator
  - researcher
scope:
  - agent_execution_artifacts
  - loop_history
  - rollout_telemetry
summary: Run, loop, agent, and invocation-scoped evidence storage with compatible legacy artifact access.
source_of_truth:
  - utils/agent_artifact_archive.py
  - utils/rollout_artifact_stream.py
  - agents
  - app/bootstrap.py
  - app/main.py
  - mcp_tools/tool_registry.py
  - orchestrator/langgraph_runtime.py
  - device_bridges/lerobot_bridge.py
  - web/static/runtime_ide.js
  - web/static/planning.js
last_verified: 2026-09-06
verified_against: working-tree
related_docs:
  - docs/agents/README.md
  - docs/runtime/runtime_ide.md
  - docs/device_bridges/lerobot_bridge.md
  - docs/standards/documentation_standard.md
  - docs/runtime/evidence/2026-09-06-loop-artifact-archiving-tests.md
supersedes: []
---

# Loop Artifact Archiving

## Summary

ATR stores execution evidence beneath the existing run directory, partitioned
by loop, agent, and invocation. A later loop or retry does not overwrite the
earlier invocation's input, result, or copied file bytes. This is an observation
layer around existing agent and tool calls, not a replacement execution graph,
device driver, retry policy, or success gate.

한국어 요약: 기존 `runs/` 안에서 실행 → 루프 → 에이전트 → 호출 차수별로
보관합니다. 성공뿐 아니라 실패·취소 결과와 취소 후 도착한 tool 결과도 같은
호출에 연결합니다. Live GUI의 완료 루프와 Runtime IDE에서 저장된 파일을
조회할 수 있으며, 아카이브 완료와 물리 실험 성공은 별개의 상태입니다.

## Scope

All ten agent entrypoints participate when their `AgentContext` has an
`artifact_run_root`. Application bootstrap supplies the configured
`system.run_root` (default `./runs`). A manually constructed context without
that field retains the prior behavior. Arbitrary standalone bridge commands
outside an agent invocation do not acquire a synthetic loop identity.

Existing producer directories, run files, download URLs, and legacy LeRobot
sessions are retained. This change does not migrate, delete, or relabel old
results whose loop ownership is unknown.

## Source of Truth

- `utils/agent_artifact_archive.py`: identity, input/result/event recording,
  bounded file snapshots, status, and disk-backed enumeration.
- `utils/rollout_artifact_stream.py`: long-running rollout ownership and legacy
  locator compatibility.
- `agents/*_agent.py`, `mcp_tools/tool_registry.py`: invocation/tool boundaries.
- `orchestrator/langgraph_runtime.py`: stage events and derived Analysis/BO files.
- `app/main.py`, `web/static/runtime_ide.js`, `web/static/planning.js`: existing
  artifact API, filters, and saved-loop views.

## Storage and Identity

```text
runs/<run_id>/
└── runtime/loops/
    └── loop-000001/                    # loop_index=0, loop_number=1
        ├── events.jsonl               # routing/gate events for this loop
        └── <agent_name>/
            ├── attempt-000001/
            │   ├── manifest.json      # ownership, state, file inventory
            │   ├── input.json         # state and extra call arguments
            │   ├── result.json        # success/failure/cancellation result
            │   ├── events.jsonl       # agent/tool/evidence events
            │   ├── files/<sha256>_<name>
            │   ├── derived/           # runtime-generated Analysis/BO files
            │   └── streams/<session_id>/
            │       ├── session.json
            │       ├── motor_events.jsonl
            │       └── ...            # logger and tracking evidence
            └── attempt-000002/        # another invocation in the same loop
```

Optional directories appear only when used. `attempt_index` is a positive
per-agent invocation counter, not an assertion that the runtime classified
the invocation as a retry. Exclusive directory creation allocates attempts
across processes; each attempt also has a UUID `execution_id`.

`run_id`, `loop_index`, `loop_number`, `agent`, `stage`, `experiment_id`, and
the current input `specimen_id` are frozen at entry. An absent specimen ID
stays empty; this layer does not invent experimental identity. Specimens
created later and output lists remain in the result payload. Guardian's final
events retain the loop identity from before its counter increment.

Nested BO `run → run_with_settings` in the same async task uses one archive.
An independent child task gets its own invocation. Existing in-flight rollout
recovery continues to use its original session; new agent-owned rollout IDs
include loop, attempt, and execution suffixes to avoid reuse.

## Agent Coverage

Every row stores the complete returned data, entry state, and observed tool
results, including unsuccessful outcomes. Files below are examples when the
owning producer actually emits and references them, not mandatory outputs.

| Agent | Evidence preserved with its invocation |
|---|---|
| Orchestrator | Mission/dispatch/handoff decisions and returned control data |
| Design | Candidate-space, selection, and experiment specification data |
| Specimen | Geometry/slicing/print/ejection results and referenced local files |
| Vision | Observation/validation data and referenced images/proofs |
| Manipulation | Task/session/rollout result, streamed motor history, tracking evidence |
| Equipment | Tool/skill execution results, exported CSV references and copies; successive skill-flow execution snapshots before overwrite |
| Analysis | Parsed measurement/metric/CAE results, referenced files, runtime-generated plots |
| Knowledge | Returned record/provenance/persistence outcomes and referenced allowed files |
| BO | LHS/optimization/recommendation results and runtime-generated posterior artifacts |
| Guardian | Risk/approval/continuation/stop decisions and loop-tail events |

The archive is not a database backup, model-checkpoint mirror, or recursive
copy of every producer directory.

## Recording Lifecycle and Status

`manifest.json` uses schema `atr.agent_artifact_execution.v1`.

| Field | Meaning |
|---|---|
| `status` | Invocation `running`, `completed`, `failed`, or `cancelled`; `completed` reflects `AgentResult.success`, not independent physical validation |
| `archive_status` | `recording`, `complete`, or `incomplete`; storage/evidence completeness, independent of invocation success |
| `pending_tools` | Observed synchronous tool calls that have not returned a result/error yet |
| `artifacts[]` | Source, ownership key, copy status, saved path, byte size, SHA-256 when copied |
| `archive_errors` | Storage error codes; no arbitrary exception text |
| `streams[]` | Added by the listing API from persisted stream session records |
| `invocation_archive_status` | Listing API's preserved invocation status before factoring in longer-lived streams |

File entries are `copied`, `partial` (changed while copying), `missing`,
`external` (not an allowed copy source), or `error`. Non-copied entries make
the archive incomplete. Unfinished tools or streams keep an otherwise intact
archive recording. A failed invocation can have a complete archive.

Agent cancellation does not imply that a synchronous device worker stopped.
If that worker returns later in the same process, its event and referenced
files are appended to the original invocation while `status=cancelled`
remains unchanged. These late additions and ongoing streams mean manifests
are mutable until evidence production ends; copied snapshots are not replaced
by the next loop's source bytes.

Archival exceptions are reported separately in `run_metadata.artifact_archive_errors`
and logs. They do not replay the device call or turn an otherwise successful
scientific result into an agent failure.

## Rollout Streams and Compatibility

For an agent-owned rollout, the logger writes directly into that attempt's
`streams/<session_id>/`. The old session directory contains
`artifact_location.json`; bridge and API readers resolve this locator before
opening `motor_events.jsonl`. Legacy sessions without a locator keep their
original path.

The logger starts with the rollout process, not a chart subscriber. A terminal
bridge status/stop observation finalizes tracking artifacts without requiring
the Live GUI to be open. Session records, raw logs, and final artifacts remain
under their originating attempt after the agent call returns.

Locator resolution is restricted to the trusted configured run-root subtree
and the expected run/loop/agent/attempt/stream shape. Application bootstrap
supplies `system.run_root` to both the agent context and LeRobot bridge;
`session_log_root` may be configured independently. Standalone bridge setups
can set `lerobot.artifact_run_root` to that same root. Markers contain only a
relative path and cannot authorize a different filesystem root. The telemetry
API uses the selected session's owning bridge to resolve its log location.
Binding failures keep legacy logging and mark preservation incomplete; they
are not reported as successful archival or
allowed to leave a valid stream permanently marked `STARTING` when its
failure record can be written.

## API and GUI Access

Existing endpoint: `GET /api/runs/{run_id}/artifacts`.

| Optional query | Meaning |
|---|---|
| `loop_index=0` | Only the first loop; zero-based |
| `agent=analysis_agent` | Only that agent |
| `attempt_index=2` | Only the second invocation; positive integer |

The response retains `artifacts` and adds `executions`. Artifact items include
loop, agent, attempt, execution, specimen, and archive-status fields. Existing
`url`, `download_url`, `artifact_id`, and compatibility routes still work.
Negative loop indices and nonpositive attempts are rejected; an absent loop
returns an empty list, never the current loop as a fallback. Unknown legacy
ownership is labelled `legacy` with empty identity fields.

- Runtime IDE: Artifact Lineage provides a loop filter and groups files by
  loop/agent/attempt; the former 80-file truncation is removed. Changing runs
  clears the previous filter and artifact set.
- Live GUI: a completed loop's **Loop Artifacts** button fetches that loop's
  disk-backed inventory and offers saved-file/image access. Refresh fetches
  new late-arriving artifacts. It does not start telemetry subscriptions,
  reconnect the old robot, or execute a device command.

## Limitations and Known Gaps

- References are discovered in structured result/tool payloads using file
  suffixes and path keys. Unreferenced files and directory contents are not
  automatically collected. Files created after the only reference was
  captured need a later result/evidence event or an owned stream.
- Copy roots are the configured run root and its parent's `artifacts/`,
  `memory/equipment_runtime/`, and `memory/knowledge/`. Other local sources
  remain external references. Policy/model checkpoint fields are excluded.
- Snapshots are bounded by the source size at capture, with no 50 MiB
  exclusion. Copying large files costs I/O and disk space; no quota, retention
  deletion, or cross-attempt deduplication is implemented.
- Structured credential fields are redacted. Free-form text and raw copied
  files are not guaranteed secret-free; review artifacts before sharing.
- Atomic JSON replacement is not a power-loss durability guarantee. Process
  termination may leave `running`/`recording` records; these remain visible,
  and are not automatically relabelled successful. A killed device worker
  cannot return late evidence to a dead archive process.
- Tracking finalization requires a terminal bridge observation. Process death
  without that observation preserves raw files but may leave summaries absent.
- Derived plots are enumerated from the attempt directory; the manifest's
  copied-file list is not an exhaustive inventory of derived/stream files.
- The archival layer adds result metadata and storage work but no actuation
  authority. Tests below do not validate physical printing, transfer, or UTM.

## Verification

This Reference intentionally covers the uncommitted **working-tree** on
2026-09-06, not the older committed baseline. Implementation was followed by
offline tests; the running application was not restarted as part of this work.
A later normal application restart loads the changes.

```bash
.venv/bin/pytest tests/unit/test_agent_artifact_archive.py tests/integration/test_all_agent_loop_archives.py tests/integration/test_loop_artifact_api.py -q
node --test tests/js/loop_artifact_history.test.cjs tests/js/omx_telemetry_history.test.cjs
.venv/bin/python scripts/validate_documentation.py
```

The Python tests exercise loop/retry isolation, late worker results after
cancellation, storage failures, traversal rejection, large file preservation,
stream finalization, and existing API access. The ten-agent wiring test uses
real entrypoints with a dependency boundary that prevents providers/devices
from being invoked; it does not claim ten successful scientific stages.
JavaScript tests execute extracted rendering functions, not a full browser
end-to-end hardware run.

Recorded counts, broader regression failures, and documentation-validator
baseline issues are separated in the
[offline test report](evidence/2026-09-06-loop-artifact-archiving-tests.md).

## Related Documents

- [Agent reference index](../agents/README.md)
- [Runtime IDE](runtime_ide.md)
- [LeRobot bridge](../device_bridges/lerobot_bridge.md)
- [Documentation standard](../standards/documentation_standard.md)
