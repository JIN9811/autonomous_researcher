# Live GUI Runtime Contracts

This page retains the current Setup and Chat contracts. The former generated
UI reference images and their pixel-comparison audit are retired; they are not
the visual acceptance baseline. Existing runtime behavior and the current
agent references remain authoritative.

## Current Sources

- `web/templates/planning.html`, `web/static/planning.js`, `web/static/styles.css`
- `app/main.py`, `app/controller.py`, `app/planning_setup.py`
- [Agent References](../../agents/README.md)
- [Runtime IDE](../../runtime/runtime_ide.md)

## Current Experimental Setup and Chat Boundary

Chat supports up to three expanded message/loop bubbles. Opening a fourth closes
the earliest opened bubble; explicit Hide closes only its own bubble. Refreshes
preserve expansion. When a completed loop is compressed, its replaced detailed
bubbles close and the new summary starts closed; unrelated bubbles stay open.
A manually reopened summary follows the same three-bubble rule and remains open
on subsequent refreshes.

Knowledge cards retain activity, memory and retrieval evidence. The
[Wiki and Memory](../../knowledge/wiki_memory.md) integration adds the shared
Wiki, scoped private-memory actions and delivery receipts; its browser rendering
is not yet verified. The existing Knowledge Workspace keeps Source Library,
execution Markdown and ontology alongside the new views. Knowledge-bound Chat
HTML is excluded from persistent browser snapshots, while the server transcript
and existing three-expanded-message interaction remain intact. Retired graph
relation summaries are not polled, and relation review cards/links are absent.
Operator Attention covers approvals, agent questions and runtime faults, not
retired relation queues. See the [Knowledge Agent](../../agents/knowledge_agent.md)
for the current workspace and API boundaries.

New run/session identifiers use [date, KST time, and the known purpose](../../runtime/logging.md#readable-run-and-session-names).
An already-created planning session or run keeps its identity when the operator
later selects a mode; this naming change does not replace the canonical Setup store.

The existing Live GUI Setup allocation now renders the server-canonical
Experimental Setup blocks for the current planning session. It remains in the
existing Setup dock; it does not add a panel or move the Chat allocation. When
content exceeds that allocation, the Setup region scrolls vertically internally.

`Edit in Chat` opens the existing Orchestrator Chat with the selected
`block_id` and revision as context. The click does not send a message, propose
or confirm a value, or start a run. Chat-originated edits and Setup-originated
edits use the same canonical server state, rather than a selected historical
report. Draft, confirmed, effective, validation, application, and availability
are separate displayed facts. An unknown owner availability must remain
`unknown`; a descriptor or an editable field is not a readiness badge.

The current public writable topics are `research.goal`, `bo.parameter_space`,
and `bo.acquisition`. Actual owner validation occurs before a draft is stored.
Explicit confirmation schedules settings for the next new run; the current run
snapshot is not changed. At that new run's admission, all captured confirmed
settings are validated together from one snapshot, same-owner values are
combined before any owner effect, and owner readback completes before the
affected runtime path. Other owners appear according to graph-linked descriptors
but are read-only or unsupported when they lack the complete owner adapter
contract. A Confirm or Discard action is an explicit scoped request and never
starts a run.

Rejected, failed, unknown, or partial receipts remain visible holds. An ordinary
retry preserves the original failed-run inputs and does not repeat a successful
owner; only an explicit replacement confirmation may supersede the hold.

Focused static-fixture browser evidence covered this allocation and internal
scroll at 1440x960, 1440x480, and 390x640, including the last block's keyboard
actions and the same Chat context. It is not evidence of an operating GUI
service, live owner readiness, a full-page mobile layout pass, or hardware.
The related [bounded verification evidence](../../runtime/evidence/2026-09-12-orchestrator-dynamic-setup-verification.md)
records the aggregate/provider scope separately; it is not browser or service proof.

## Report and Backend Boundary

Operator reports show decisions, measured results, artifacts, warnings and next
actions. Raw prompts, tool payloads and technical traces belong to Backend Trace.
Missing measurements remain missing; synthetic chart values are not a substitute.
Device configuration stays in its existing workspace rather than being moved
into the Live GUI report surface.

## Verification Scope

Use current functional and rendered-UI checks when changing the GUI: preserve
report/backend separation, readable content, keyboard access, scroll behavior,
and existing API contracts. Do not score changes against the retired generated
images. This documentation cleanup changes no GUI implementation or run path.
