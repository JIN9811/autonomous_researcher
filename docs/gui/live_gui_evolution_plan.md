# Live GUI Evolution Plan

## Input Drafts

This plan adapts the newly added draft package:

- `docs/ATR_Live_GUI_Graph_Package/`
- `docs/system/ATR_Live_GUI_and_LangGraph_Codex_Instructions.txt`

The package is directionally aligned with ATR, but it describes a partially different API surface. The current repository already has:

- `/live` backed by `web/templates/planning.html` and `web/static/planning.js`
- `/ide` backed by Runtime IDE graph/module config editor
- `/module-management` for module catalog and Module Designer
- `/api/state`, `/api/events/stream`, `/api/planning/*`, `/api/graphs/*`, `/api/modules/*`, `/api/runs/*`

Therefore the package must be absorbed into the current pages rather than implemented as a separate duplicate frontend stack.

## Target UX

The Live GUI should evolve toward a three-zone operational runtime surface:

```text
left: compact agent binder
center: academic report / backend trace / artifact panel
right: persistent runtime chat
bottom: timeline + device state
```

The persistent chat must remain mounted while operators inspect reports, traces, artifacts, or graph state.

## Current Gap Map

This section records the gap identified from the imported draft before the 2026-05-26 Live GUI upgrade.

Already implemented elsewhere:

- config-driven LangGraph runtime
- Runtime IDE graph validate/compile/dry-run/save/run
- module internal graph editing
- runtime events, timeline, artifact lineage in `/ide`
- Live GUI chat handoff through `/api/planning/*`
- CAE contour and BO plot cards in Live GUI chat

Resolved by the 2026-05-26 `/live` upgrade unless noted in the implementation update:

- compact agent binder
- report-mode center panel separate from chat
- backend trace drawer per selected agent
- chat target selector bound to selected agent/node/trace
- unread badges and waiting indicators per agent
- approval cards integrated into the chat surface
- direct report-to-backend trace navigation

## API Adapter Rule

Do not add package-specified duplicate endpoints such as `/api/runtime/state` or `/api/agents/{agent_id}/report` unless they are thin compatibility adapters.

Use the current authoritative APIs:

- state: `GET /api/state`
- events: `GET /api/events/stream`, `GET /api/events/recent`
- planning chat: `GET /api/planning/session`, `POST /api/planning/message`
- graph: `GET/POST/PUT /api/graphs/*`
- module: `GET/POST/PUT /api/modules/*`
- run details: `GET /api/runs/{run_id}/events`, `GET /api/runs/{run_id}/artifacts`
- approvals: `GET /api/runs/{run_id}/approvals`, `POST /api/runs/{run_id}/approvals/{approval_id}/resolve`
- self-evolution: `GET/POST /api/evolution/*`

Compatibility adapters now exist for package-level consumers without changing the runtime source of truth:

- `GET /api/runtime/state` -> wraps `GET /api/state`
- `GET /api/runtime/events` -> wraps the existing SSE event stream
- `POST /api/runtime/start|pause|resume|stop|safe-stop` -> delegates to existing run control
- `GET /api/agents` -> exposes the Live GUI binder agent catalog
- `GET /api/agents/{agent_id}/report` -> builds a structured report payload from planning messages and runtime events
- `GET /api/agents/{agent_id}/backend-trace` -> filters raw runtime events for the selected agent
- `POST /api/agents/{agent_id}/message` -> routes context-aware messages through the existing planning chat path
- `GET /api/devices/state` -> normalizes controller device health and host/GPU resources
- `GET /api/artifacts`, `GET /api/artifacts/{artifact_id}` -> wrap run artifact listing/serving
- `POST /api/graphs/{graph_id}/save-version` -> wraps the existing Runtime IDE graph save/version gate and defaults to version-only writes unless `activate=true` is explicit
- `POST /api/approvals/{approval_id}/approve|revise|reject` -> resolves the current run approval queue

## Recommended Implementation Order

1. Add Live GUI state adapter in `planning.js` that normalizes `/api/state`, `/api/planning/session`, and SSE events into agent cards.
2. Add compact Agentic Binder to `planning.html` without removing the existing chat.
3. Add center report panel that renders agent summaries from planning messages and runtime events.
4. Add backend trace drawer using `/api/runs/{run_id}/events` filtered by node/stage.
5. Add approval cards using `/api/runs/{run_id}/approvals`.
6. Add Self-Evolution Lab entry points from Live GUI reports/traces.
7. Only after the current FastAPI UI reaches its limits, consider a React/TypeScript frontend rewrite.

## Safety Invariants

- Safe Stop remains visible in live mode.
- The frontend never executes Python or edits arbitrary Python source.
- Graph edits must still go through Runtime IDE validate/compile/dry-run/save.
- Live mode cannot bypass the active printer bridge, LeRobot, Windows bridge, CAE, or Guardian gates.
- Self-evolution variants cannot modify live hardware code directly.

## 2026-05-26 Implementation Update

The `/live` page has been upgraded from the former single-chat surface into an operational Live GUI shell using the existing FastAPI/Jinja frontend, not a duplicate React stack.

Implemented in this iteration:

- Header runtime summary with run id, stage, mode/running status, active agent chip, resource chip, runtime clock, and always-visible Safe Stop.
- Compact left Agentic Binder with Objective, Orchestrator, Design, Specimen, Vision, Manipulation, Equipment, Analysis, Knowledge, BO, and Guardian tabs.
- Agent tab status is derived from `/api/planning/session`, `/api/state`, `/api/events/recent`, run events, and pending approvals.
- Center panel modes: Report, Backend, Graph, Artifacts, Timeline.
- Report mode renders selected-agent messages, reasoning blocks, experiment spec fields, STL/FEM/BO artifacts, and an academic report layout with Overview / Summary, Received Inputs, Key Decisions, Process Steps, Tool Calls Summary, Artifacts, Validation / Quality Check, Warnings, Handoff, and Next Action sections.
- Backend mode renders selected-agent runtime events as expandable structured traces with separate Raw Prompt / LLM Response / Tool Calls / Node Input / Node Output / Logs / Artifacts / Error sections when those fields exist, plus full event JSON fallback.
- Artifact mode combines persisted run-directory artifacts from `/api/runs/{run_id}/artifacts` with chat-linked STL/FEM/BO artifacts.
- Approval and agent-question cards are shown in the persistent chat area. Approval cards use `/api/runs/{run_id}/approvals`; `agent_question`/missing-input events render Answer in Chat, Open Backend, and Mark Read actions without blocking the rest of the UI. Operator replies submitted through Runtime Chat are now also emitted as `user_reply` runtime events with selected agent, trace_id, event_key, and chat mode so backend trace/report views can reconstruct the follow-up flow.
- Graph mode renders the active `atr_closed_loop` graph from `/api/graphs/atr_closed_loop` as a read-only runtime mini-map with active-stage highlighting, logical transition edges, and a Selected Node View with handler/stage/edge counts and node-test actions.
- Runtime Chat quick action bar includes Approve Next Step, Revise, Reject, Pause Run, Resume Run, Safe Stop, Dry Run, Explain Current Node, Rewrite Report, Open Backend, Run Node Test, and Open Graph. The actions call existing approval/pause/safe-stop/graph dry-run/module dry-run/chat paths rather than introducing duplicate APIs. When a pending approval exists, Approve/Revise/Reject now resolve the approval through backend evidence (`approved` / `cancelled` / `rejected`) instead of only drafting chat text.
- Agent Binder now exposes the package-required right-click context menu: Open Report, Open Backend, Show Tool Calls, Show Artifacts, Run Node Test, Re-run From Here, Mark as Read, and Open in Graph.
- Report mode now exposes package-required operational actions: BACKEND, Export Section, Pin Finding, Ask in Chat, Mark Reviewed, and Re-run From Here. Export uses the same structured report sections; Pin/Review state is local UI state and does not mutate backend execution state. Each report action is also recorded through `/api/runs/{run_id}/operator-events` or `/api/runtime/operator-event` as `operator.report.*` evidence so Backend/Timeline views can audit operator decisions.
- Timeline supports All/Info/Warning/Error/Tool/Artifact/Handoff filters and selected-event trace inspection. Clicking a timeline item pins its event_id/trace_id/node context in Backend/Timeline views and exposes Open Backend, Open Report, Ask in Chat, Replay Prep, and Copy Trace actions.
- Bottom runtime strip shows clickable recent timeline events and event-derived runtime/device cards. Each card exposes bridge state, last command, heartbeat, and safety status where evidence exists.
- Runtime chat remains mounted while the operator switches reports, backend traces, artifacts, or timeline views.
- Runtime quick actions now use a single-flight guard for operator commands so repeated clicks cannot stack pause/resume/dry-run/node-test requests. Safe Stop remains available while other actions are busy, and Safe Stop responses are explicitly checked so failed safety requests surface as timeline/error evidence instead of silently failing.
- Chat target/mode controls are preserved in the GUI and are passed as lightweight context fields under the existing planning constraints payload. The payload also carries selected agent, view, graph node, event key, event id, trace id, node id, event type, timeline filter, and pinned findings so follow-up messages preserve runtime context.
- Live GUI browser windows now use a shared browser storage session id and adopt the server-returned `planning_session_id` after every `/api/planning/session`, bootstrap, or message response. This keeps newly opened windows, refreshed tabs, and Runtime Chat follow-up events aligned to the same server-side transcript instead of leaving per-window local ids in backend traces. `fresh=1` remains the explicit reset path.
- Package-level compatibility endpoints were added as thin adapters so future GUI shells or external tools can use the imported LIVE GUI API contract while the existing FastAPI controller, run loop, graph compiler, run event stream, and approval queue remain authoritative.
- Self-Evolution Lab is now reachable from Live GUI quick actions, report actions, and binder context menu. The link carries selected agent, target_type/target_id, run_id, selected event key, and an objective draft so operators can create trace-guided prompt/graph evolution tasks without re-entering runtime context.
- Evolution Lab now renders selected-target task history, variant reload controls, candidate leaderboard, pipeline progress, gate PASS/FAIL badges, and lineage/active-variant state so operators can compare candidates and return to earlier variants before validation, approval, activation, or rollback.

Still intentionally deferred:

- Persisted report-file authoring/loading beyond the current event/message-derived academic report renderer.
- Full raw LLM token stream persistence; the Live GUI now separates raw prompt/response/tool/node I/O fields when present, but can only display data recorded by the backend trace.
- Direct graph-mini-view editing inside `/live`; graph mutation remains routed through `/ide` for validate/compile/dry-run/version gates.

## 2026-05-26 Package Review Note

The imported SELF-EVOLV and LIVE GUI package drafts are compatible with the current repository direction, but they should be treated as ATR adaptation guides rather than files to copy verbatim.

- SELF-EVOLV: implemented as a conservative file-backed service under `self_evolution/` with trace collection, deterministic candidate generation, gate validation, versioned activation, rollback marking, `/evolution-lab`, and `/api/evolution/*`. The package's larger module list (`trace_miner`, `candidate_generator`, `evaluator`, `constraint_gate`, etc.) remains a future refactor target; current service boundaries preserve the same safety lifecycle.
- LIVE GUI: implemented in the existing FastAPI/Jinja `/live` surface rather than a duplicate React stack. The operational pieces from the package now map to existing APIs: planning/session, state, events, graph, module dry-run, run artifacts, approvals, pause, and safe-stop.
- Runtime graph editing remains in `/ide`; `/live` intentionally shows a read-only graph mini-map so live operation does not bypass graph validation, compile, dry-run, and version gates.

## Browser-Level Validation

A browser audit was added for the upgraded Live GUI shell:

```bash
.venv/bin/python tests/ui/live_runtime_ide_browser_audit.py \
  --base-url http://127.0.0.1:7862 \
  --webdriver-url http://127.0.0.1:4448 \
  --out-dir artifacts/ui/live_runtime_audit_1920x1080 \
  --width 1920 \
  --height 1080
```

The audit opens `/live` in Firefox/WebDriver and verifies:

- all major Live GUI panels are visible
- the `/live` page uses the dedicated `planning-live-body` visual shell rather than inheriting the light planning page theme
- the actual browser screenshot is compared against `docs/ATR_Live_GUI_Graph_Package/assets/reference/main_live_gui_reference.png` with pixel-level checks for mean RGB distance, bright-area ratio, and overall dark Runtime IDE visual direction
- visual layout metrics confirm the binder, graph/context workspace, runtime chat, timeline, and Safe Stop controls are visible, ordered correctly, and not overlapping at 1920x1080
- the Agentic Binder uses the package-provided SVG icons from `web/static/live_gui_icons/` and browser validation confirms all 11 binder icons load
- panel contrast is measured from the rendered browser page so title text remains readable on the dark reference-aligned panels
- the Agentic Binder renders 11 tabs
- target selector is populated
- pending approval cards are visible
- agent question cards are visible for `agent_question`/missing-input events and Answer in Chat preserves selected trace context
- device/runtime cards are populated
- timeline items render
- Report, Backend, Graph, Artifact, and Timeline tabs switch the active panel
- single-clicking an agent opens its report
- double-clicking an agent opens its backend trace
- Runtime Chat exposes at least the package-required quick actions
- Approve Next Step and Revise create real browser-level calls to the current run approval resolve API and the UI reflects `approval.resolved` evidence instead of only checking that the buttons exist
- Pause Run, Resume Run, and the always-visible Safe Stop button call the real runtime control APIs and produce `run_pause` / `run_resume` / `run_safe_stop` events with state snapshots for auditability
- Dry Run and Run Node Test quick actions call the real graph/module dry-run APIs and append runtime evidence to the Live GUI timeline
- Backend trace sections render separate raw prompt/tool/node I/O fields from fixture events
- Graph Mini View renders graph nodes, highlights the active runtime stage, and updates Selected Node View on graph-node click
- Report actions are present for export/pin/ask/review/rerun
- Academic report sections include Overview, Inputs, Decisions, Process, Tool Calls, Artifacts, Validation, Warnings, Handoff, and Next Action
- Pin Finding renders a Pinned Findings panel in Report mode and records `operator.report.pinned` runtime evidence
- Timeline filters are present and warning filtering preserves warning events
- Clicking a timeline event renders a selected trace inspection card with trace_id and replay-preparation actions
- Device cards expose bridge/command/heartbeat/safety fields
- Binder right-click context menu exposes the package-required actions
- the shell does not create large horizontal overflow at 1600 px width
- `/evolution-lab` renders the package-required pipeline diagram, candidate leaderboard, task history, target lineage, and variant body panels
- Evolution Lab does not create large horizontal overflow at 1600 px width
- the shell does not create large horizontal overflow at 1920 px width (`bodyWidth=1908`, `viewportWidth=1920`)
- `/evolution-lab` does not create large horizontal overflow at 1920 px width (`bodyWidth=1908`, `viewportWidth=1920`)
- the same browser audit passes at 2560x1440, including real approval resolve, graph dry-run, module node-test, pause, resume, safe stop, and no large horizontal overflow (`bodyWidth=2548`, `viewportWidth=2560`)

For browser testing only, `planning.js` exposes `window.__liveGuiDebugSetState(payload)`. This is a local frontend state injection hook and does not call hardware, mutate backend state, or bypass runtime safety gates.

## 2026-05-26 Compact Operations Pass

The Live GUI was tightened for 1920x1080 operator monitoring after browser review:

- Header copy was shortened to keep run/stage/agent/resource/Safe Stop visible without wrapping.
- Runtime Chat quick actions now render as compact icon controls with `title`/`aria-label` tooltips while retaining hidden accessible labels.
- Timeline cards keep the visible surface to time/type/status and expose full details through hover titles and selected-event drilldown.
- Device/runtime cards now show compact name/status by default and expose bridge, last command, heartbeat, and safety details through hover/focus cards and native titles.
- The `/live` shell is constrained to a 100vh operational grid at desktop sizes so binder, report/trace workspace, runtime chat, timeline, and device strip fit into a 1920x1080 control view without large horizontal overflow.
- Selected agent, active center view, timeline filter, selected event/node, chat target, and chat mode are persisted in browser storage and restored on refresh/new window unless `fresh=1` is used.

### Compact Report Controls Follow-up

- Center view tabs were converted to icon-first controls with native hover tooltips and hidden accessible labels.
- Report action buttons were converted to compact icon controls for backend trace, export, pin, ask, review, rerun, and evolution actions.
- Browser validation now checks that quick actions, report actions, and center tabs are compact controls rather than wide text buttons.

### Compact Secondary Actions Follow-up

- Selected timeline-event actions and selected graph-node actions were converted to compact icon controls with hover/focus tooltips.
- Agent question card actions were compacted in the same icon+tooltip pattern while preserving the existing answer/backend/read behavior.
- Approval decisions remain text-visible because approve/revise/reject are safety-critical operator choices.
- Browser validation now checks selected event, selected node, and agent-question actions for compact width, tooltip coverage, and hidden accessible labels.

### Compact Tooltip Layer Follow-up

- `/live` now has a shared `#live-hover-tooltip` layer for compact icon controls and dense cards.
- Quick actions, report actions, center tabs, selected trace/node/question controls, binder tabs, timeline items, and device cards keep visible text minimal while hover/focus restores the full explanation.
- Browser validation now dispatches a real hover event against the Dry Run control and asserts that the tooltip renders with visible text and measurable size.

### Bottom-Bar Density Follow-up

- Timeline and device headings were shortened for control-room use.
- Timeline filters now use compact icon chips with accessible labels and hover/focus tooltips instead of full text labels.
- The redundant device hint text was removed because device cards already expose details through the shared tooltip/hover-detail behavior.

### Keyboard Operations Follow-up

- `/live` now exposes operator shortcuts through `aria-keyshortcuts` and a compact keyboard help overlay opened with `?` and closed with `Esc`.
- View switching is available with `Alt+Shift+R/B/G/A/T` for Report, Backend, Graph, Artifacts, and Timeline.
- Runtime operations use `Alt+Shift+U` for refresh, `Alt+Shift+D` for graph dry-run, `Alt+Shift+N` for node test, `Alt+Shift+P/O` for pause/resume, and `Alt+Shift+X` for Safe Stop.
- Editable fields suppress non-safety global shortcuts so normal typing is not interrupted; Safe Stop remains available from editable focus.
- Browser validation now opens/closes the shortcut overlay from keyboard events and verifies `Alt+Shift+G` switches the active panel to Graph.

### Runtime Freshness Follow-up

- `/live` now shows separate `SSE` and `Sync` chips in the header so operators can tell whether the runtime event stream is connected and how fresh the last state refresh is.
- State refresh completion updates the Sync chip with relative age and an exact timestamp tooltip.
- Event stream open/update/error transitions update the SSE chip with live/error/unsupported state, last event age, and a tooltip.
- Browser validation now checks that both freshness chips render with informative text/title and runtime-chip styling.

### SSE Heartbeat Follow-up

- `/api/events/stream` now emits an immediate `stream.connected` event so the Live GUI can confirm the stream transport before the first runtime event.
- The stream also emits `stream.heartbeat` every 15 seconds of event inactivity, keeping the header freshness indicator meaningful during long-running quiet stages.

### Auto-Refresh / Stale-State Follow-up

- `/live` now runs a guarded background state refresh when the last sync becomes older than the auto-refresh interval.
- State refresh uses a single-flight guard, so manual refresh, SSE-triggered refresh, shortcut refresh, and periodic refresh do not stack concurrent network calls.
- Sync status now distinguishes `refreshing`, `ok`, `stale`, and `error`; stale/error states are reflected in the header chip class and tooltip.
- The Live GUI debug snapshot exposes `stream_state`, `sync_state`, `sync_failure_count`, `last_sync_at`, and `last_event_at` for browser audit and field debugging.

### Compact Operator Copy Follow-up

- Header run/stage/agent/resource fields are now short chips (`S:*`, `A:*`, compact run id, `GPU/RAM`) with full details preserved in hover tooltips.
- Runtime chat trigger guidance was reduced to the two operational keywords; detailed behavior stays in the tooltip.
- Empty-state copy in report/backend/artifact/timeline panels was shortened so the 1920x1080 control room view spends less space on explanatory filler.

### Token Usage Metric Follow-up

- `/live` now includes a compact `Tok` header chip for Live GUI LLM token usage when backend responses expose OpenAI/vLLM `usage` fields or Ollama-style `prompt_eval_count` / `eval_count` fields.
- Planning messages store normalized `token_usage` for orchestrator and bootstrap calls; the browser aggregates the current session total and preserves prompt/completion/call counts in the chip tooltip and debug snapshot.
- When no usage metadata is available, the chip remains `Tok -` instead of fabricating estimates.

### Cross-Window Busy-State Follow-up

- `/api/planning/session` already exposes `is_planning_busy`; `/live` now treats that backend field as authoritative, not only the local browser's pending request counter.
- If another Live GUI window or refresh cycle catches the orchestrator reasoning, Send and Plan are disabled, the status chip shows `BUSY`, and the buttons expose a tooltip explaining that the backend orchestrator is still reasoning.
- The debug snapshot now exposes `backend_planning_busy` so browser audits and field debugging can verify cross-window lock reflection.

### Runtime IDE Compact Surface Follow-up

- Runtime IDE visible copy was reduced to short operator labels; longer explanations moved to native `title` tooltips.
- Main controls now use compact labels (`VLD`, `CMP`, `DRY`, `EX`, `IM`, `SAVE`, `VER`) with unchanged element IDs and backend behavior.
- Runtime metrics, graph explorer, canvas controls, launcher, bottom dock, and event panels were tightened to preserve the 1920x1080 control-room layout.
- Canvas viewport status now uses compact `V% / Z%` copy with the full context preserved in a tooltip.

### Live Visible-Copy Compression Follow-up

- Header, binder, center panel, chat composer, and bottom timeline labels were shortened for control-room use while keeping `title`/`aria-label` context.
- The Safe Stop control now uses compact visible text (`STOP`) but keeps the full Safe Stop label and keyboard shortcut metadata.
- The chat composer label was visually compressed so the message input consumes the available vertical space instead of explanatory chrome.

### Backend Trace Completeness Follow-up

- Backend trace cards now always include a `Graph / Compile Context` raw section with graph id, graph version/compile marker, node id, module id, handler, and trace id.
- Tool-call extraction now accepts both singular and plural tool payload keys; error extraction also checks stack-oriented keys.
- Browser audit now verifies the required runtime debug sections instead of only counting backend cards.

### Live Compact-Copy Follow-up
- Live visible labels were tightened for 1920x1080 operation: chat target/mode labels are now `T`/`M`, timeline count is numeric only, bottom headings are shortened, and trigger keywords render as compact chips.
- Full wording remains available through native `title`/`aria-label` tooltips so the operator surface stays compact without losing meaning.


### Live Chat Context Strip Follow-up
- Runtime Chat now shows a one-line `CTX` strip with selected agent (`A:`), resolved chat target (`C:`), center view, chat mode, and trace/event/node/run reference (`Ref:`) so target and evidence anchor are not confused.
- The same context is exposed through `__liveGuiDebugSnapshot().chat_context` and preserved in the existing planning message constraints, so browser refreshes and selected trace workflows remain auditable.


### Runtime Chat Target Semantics Follow-up
- Runtime Chat target selection now exposes `Current Agent`, `Selected Agent`, and grouped `Specific Agent` entries instead of only raw agent names.
- Planning payloads include both `live_chat_target_mode` and resolved `live_chat_target` / `live_chat_target_resolved`, so backend agents receive a concrete target while the UI preserves the operator's semantic choice.


### Live Visual Polish Follow-up
- The Live header removes the redundant top-left eyebrow label and uses a thin reference-style accent line instead of extra explanatory chrome.
- Runtime events now use a two-row strip with compact two-line cards: time/type on the first line and event summary on the second line.
- The top-level Live background grid overlay was disabled for `/live` to remove the stray top-left bar seen in the 1920x1080 control-room layout.
- The Live title area now uses a compact bordered `LIVE` badge and tighter header metrics to match the reference image while preserving all existing controls and tooltips.

### Agent-Specific Report Follow-up
- Live Report keeps the required common academic sections, but now inserts a role-specific report section directly after the overview.
- Orchestrator, Design, Specimen, Vision, Manipulation, Equipment, Analysis, Knowledge, BO, and Guardian each expose different focus rows and checklists so the operator sees role-relevant evidence first.
- Exported report text also includes the role-specific section before the generic sections, preserving backend trace/report consistency.

### Agent Report Compatibility API Follow-up
- `/api/agents/{agent_id}/report` now returns the same role-specific report profile used by the Live GUI renderer under `role_specific` and `sections.role_specific`.
- Compatibility consumers receive schema-level report fields (`inputs`, `process_steps`, `tool_calls`, `artifacts`, `warnings`, `handoff`, and `next_action`) instead of only a generic `sections.events` payload.
- Design, Specimen, BO, and Guardian report profiles are covered by integration tests so external dashboards do not regress to generic reports while the Live GUI continues to render the richer in-page layout.

### Report Readability Follow-up
- Live report lists now render list items with explicit line breaks in the generated markup so checklist, copy/export, and browser audit text do not concatenate adjacent role-specific items.
- Common academic report sections now use a dedicated `live-report-section-body` wrapper so headings such as `Artifacts` and empty body text such as `No evidence.` remain visually and textually separated.
- Browser validation now checks that the agent-specific checklist is rendered as distinct list items and that common empty sections do not collapse into heading/body concatenation.

### Collapsible Event/IO Dock and IDE Effect Unification
- The bottom Event/IO dock can now be collapsed from the Live GUI; while collapsed, the main center/chat row expands vertically and the dock can be expanded back to the previous screen layout.
- The collapsed/expanded dock state is persisted through the existing Live UI state store and exposed in the debug snapshot.
- Runtime IDE visual effects were selectively reused in Live GUI: running binder pulse rings, active graph edge dash/flow, backend neon outlines, approval glow, safe-stop glow, hover lift, panel sheen/grid texture, running chip sweep, selected-node dashed rings, and reduced-motion safeguards.
- Context-menu and selected-timeline actions now emit `operator.context.*` / `operator.timeline.*` runtime events so GUI-only operator decisions are visible in the same evidence stream as report actions.
- Report Pin Finding and Mark Reviewed now store `pinned_finding` / `reviewed_at` payloads in `operator.report.*` events and reconstruct the visible Live GUI pin/review state from runtime events. This makes refreshes and newly opened Live GUI windows reflect the backend audit trail instead of depending only on local browser state.
- Report sections are now selectable work units. The selected section is highlighted, persisted in Live UI state, exposed in `chat_context`, and sent as `live_selected_report_section` / `live_selected_report_section_text` planning constraints so Rewrite Report Section and follow-up chat requests operate on the operator-selected evidence block.
- Report Export, Pin Finding, and Ask in Chat now operate on the selected report section and write the selected section title/key/text into `operator.report.*` evidence events, so exported text, pinned findings, and follow-up prompts match the operator's current evidence focus.
- Binder single-click/double-click now retargets Runtime Chat to the selected concrete agent while still falling back to `selected_agent` for non-chat targets such as Objective, matching the package rule that selecting an agent makes that agent the default chat target.
- Runtime Chat intent actions now emit the package-required event types: `report_rewrite_requested` for Rewrite Report Section, `runtime_command_requested` for dry-run/pause/resume/safe-stop commands, and `node_rerun_requested` for node-test/re-run requests before the execution evidence event is appended.

### Runtime IDE Effect Package Follow-up
- Live GUI now imports the Runtime IDE effect language into the operator chat surface rather than only the graph canvas: glass-panel borders, blue/cyan/purple neon accents, LIVE status blink, primary-button glow, chat message scan-in, selected-report pulse ring, timeline selection overlay, binder icon glow, and reasoning-spinner glow.
- These effects are CSS-only and preserve the existing Live GUI IDs, API calls, runtime events, keyboard shortcuts, and accessibility labels.
- Motion-sensitive operation remains protected through `prefers-reduced-motion` overrides for the new blink, chat scan, message-in, and selected-section pulse effects.
- 1920x1080 browser audit after the effect import: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_ide_effects/live_runtime_ide_browser_audit.png`.

### Binder Runtime Evidence Unread Follow-up
- Agent Binder unread badges now count not only chat messages but also run events, recent SSE events, and pending approval/question evidence attributed to each agent.
- Opening an agent report, opening its backend trace, marking a context item as read, or marking the report reviewed updates the read marker against the full notification count rather than only message count.
- Browser audit now verifies that runtime-only Specimen/Guardian updates create unread badges before the operator opens those agent tabs.

### Header and Runtime Chat Rail Follow-up
- The top Live header now has a fixed compact control-room row, guarded overflow handling, and browser-audit validation for metric text escaping the header cells.
- Runtime Chat quick actions are exposed as a thin vertical action rail beside the chat log, leaving the chat transcript and LLM response area with more vertical room.
- The visible rail keeps only operator-critical actions in the DOM: approve, revise, reject, pause, resume, safe stop, and dry run. Backend trace, graph open, node test, evolution, and report rewrite moved out of the chat rail into their dedicated panels, context menus, keyboard shortcuts, or selected-node controls.
- The composer was compacted to a short input row with refresh/send controls on the right, and approval cards were capped so they do not consume the full chat column.
- Browser audit now checks header overflow count, visible/hidden quick-action sets, action-rail geometry, chat-log height, and composer height at 1920x1080.

### Safe Stop Confirmation and Binder Read-State Follow-up
- Safe Stop now uses a two-step confirmation: first click arms the control for 6 seconds and changes the header button to `CONFIRM`; the second click records the runtime command intent and calls `/api/run/safe-stop`.
- The same confirmation path is used by the header Safe Stop button, the Runtime Chat Safe Stop quick action, and keyboard-triggered Safe Stop flows.
- The armed state is visually distinct with an amber/red pulse and reduced-motion fallback, preventing accidental live stop requests while keeping emergency access visible.
- Agent Binder unread badges are no longer cleared by passive rerendering. Read markers now move only through explicit operator actions such as selecting an agent, backend/report review, mark-read, or reviewed actions.
- Browser audit now verifies the Safe Stop first-click armed state before the second-click runtime stop event and still verifies runtime event evidence after confirmation.

### Live Graph Gate Controls Follow-up
- The Live Graph panel remains read-only for node/edge mutation, but now exposes compact gate controls for `Validate`, `Compile`, and `Save Version` directly inside `/live`.
- `Validate` calls `/api/graphs/{graph_id}/validate`, `Compile` calls `/api/graphs/{graph_id}/compile`, and `Save Version` calls `/api/graphs/{graph_id}/save-version` with `activate=false` so Live mode does not bypass the Runtime IDE validation/versioning gates.
- The Save Version flow records a `graph_change_requested` intent event before the backend version save and the browser audit verifies the resulting `graph_version_saved` runtime evidence.
- Graph gate results are shown in a compact status card inside the Live Graph panel with graph id, compile state, saved version id, activation state, and errors.
- The 1920x1080 browser audit now verifies graph gate button visibility/compactness and exercises Validate, Compile, and Save Version through real backend APIs.

### Runtime Fault Visibility Follow-up
- Live GUI now surfaces runtime/device faults in four places at once: compact header `F/E/W` fault chip, Agent Binder error state, Event timeline severity, and Runtime Chat `Operator Attention` cards.
- Device-oriented errors without explicit agent IDs are inferred from event text/payload fields such as `device`, `tool`, and `failure_code`; explicit `selected_agent` / `agent_id` still takes priority so report pin/review ownership does not regress.
- Fault cards use compact icon+tooltip actions for backend trace opening and mark-read, matching the Runtime Chat action rail style without consuming the LLM conversation height.
- Browser audit now injects a PrusaLink upload failure and verifies Specimen binder error state, fault chip title, chat fault card, IO-strip error card, and compact fault-card actions at 1920x1080.


### Runtime Chat Essential Rail Follow-up

- `/live` Runtime Chat now keeps only operator-critical quick buttons in the side rail: approve, revise, reject, pause, resume, safe stop, and dry-run.
- Debug/developer actions such as backend trace, graph open, evolution lab, node test, and report follow-up remain available through the dedicated center panels, context menus, keyboard shortcuts, selected-node controls, or report action buttons instead of occupying chat rail height.
- The rail is constrained to an icon-only strip beside the chat log so the LLM conversation keeps more vertical reading space at 1920x1080.

### Live Graph Run Gate Follow-up

- `/live` graph gate controls now include `Run Test`, which calls `POST /api/graphs/{graph_id}/run` with `mode=test` while preserving the read-only Live graph editing boundary.
- The action records a `graph_run_requested` operator event before dispatch and shows the backend `run_id`/mode in the graph gate status card.


### Live Header Control-Room Repair Follow-up

- The `/live` top header now uses a fixed two-row metric grid with Safe Stop pinned to the far-right column across both rows, keeping the emergency control visible while preserving compact runtime telemetry.
- Header-only pseudo overlays were disabled because they could create thin rectangular artifacts over the `LIVE` title tile and metric area after multiple visual polish passes.
- Browser audit now verifies the title tile stays inside the header, the product eyebrow remains visible, header pseudo overlays are disabled, metric chips fit into at most two stable rows, and Safe Stop remains tall enough for live operation.

### Safe Stop Armed Layout Guard Follow-up

- The header Safe Stop armed state now remains inside the compact header slot when it changes from `STOP` to `CONFIRM`; the armed button no longer inherits the older wider `min-width` rule that could break the top control-room strip.
- Browser audit now measures the armed Safe Stop button after the first click and fails if it grows beyond the compact header slot or escapes the header bounds.

### Persistent Runtime Chat Verification Follow-up

- Runtime Chat's transcript container is now exposed as an accessibility live log (`role=log`, `aria-live=polite`) so the conversation stream has an explicit operational/a11y contract rather than being only a visual panel.
- Browser audit now marks the chat log DOM node before report/backend/graph/timeline navigation and verifies the same mounted log keeps the original conversation messages after navigation, binder selection, and backend double-click flows.
- This directly covers the package acceptance rule that the right Runtime Chat must remain mounted and preserve conversation while operators inspect reports, traces, graph state, artifacts, and timeline events.

### Operator Attention Status Follow-up

- The `/live` header status badge now reflects pending human attention instead of remaining `READY` while approval/question cards are visible.
- Pending approval or agent-question evidence sets the header status to `WAITING_USER` with a tooltip summarizing approval/question/fault counts; unresolved runtime faults set an attention/error state when no operator question is pending.
- Browser audit now verifies that fixture approvals and agent questions produce both visible chat cards and a matching warning status badge in the top control strip.

### Runtime Chat Side-Rail Compaction Follow-up

- Runtime Chat quick actions remain limited to the operator-critical controls only: approve, revise, reject, pause, resume, safe stop, and dry-run.
- The quick-action rail is now attached to the right edge of the LLM transcript as a 30px icon strip, rather than consuming a full row above the conversation.
- Header/context/composer controls were further compacted so the chat transcript keeps more vertical reading space at 1920x1080 while preserving tooltips, keyboard shortcuts, and accessibility labels.
- Browser audit now checks that the rail is on the transcript side, remains narrower than a normal button row, and that the chat log/composer dimensions stay within the live-operation target.

### Live Graph Run Test Browser Gate Follow-up

- Browser audit now exercises the `/live` Graph `Run Test` control instead of only verifying that the button exists.
- The audit clicks `Run Test`, verifies the `graph_run_requested` runtime intent event includes `mode=test` and `source_action=live_graph.run_test`, and then checks the graph gate status card for the backend `run_id` and test mode.
- This closes the practical operation gap between read-only graph inspection and a validated test execution path from the Live GUI.

### Live Graph Run Test Intent Retention Follow-up

- `Run Test` starts a new test run and can quickly generate enough downstream runtime events to push the initiating operator intent out of the bounded recent-event buffer.
- The Live GUI now preserves the `graph_run_requested` operator intent locally after the state refresh that follows `/api/graphs/{graph_id}/run`, so the operator's action remains visible in debug snapshots and runtime evidence even when the new run emits many events.
- This retention is scoped to the Live GUI evidence stream and does not bypass graph validation, graph compilation, or backend run execution.

### Live Graph Run Test Requested-Mode Evidence Follow-up

- `recordLiveIntentEvent` now keeps the current runtime mode as `runtime_mode` while allowing action-specific payload fields to remain authoritative.
- This ensures `graph_run_requested` records `mode=test` for the `/api/graphs/{graph_id}/run` request even when the Live GUI itself was opened from a live-mode session.
- The browser audit checks this because operators need to distinguish the UI context mode from the graph execution mode being requested.

### Live GUI Reload State Restoration Follow-up

- Browser audit now performs an actual `/live` navigation after selecting Guardian backend context and verifies the restored selected agent, center view, active backend panel, chat live-log semantics, and target selector population.
- The reload check proves the stored Live UI state is not only written to browser storage but also applied when the Live GUI is reopened or refreshed.
- After the reload probe, the audit re-injects its deterministic fixture state before exercising destructive/control actions, keeping the state-restoration check independent from the API-action checks.

### 2560x1440 Side-Rail Scale Validation Follow-up

- The latest Runtime Chat side-rail layout was revalidated at 2560x1440 after limiting the chat rail to the seven essential operator controls.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_side_rail_2560/live_runtime_ide_browser_audit.png`.
- The audit confirmed the right-side rail remains 30px wide, stays attached to the transcript edge, the chat log expands to the larger viewport (`height=792`), and no large horizontal overflow is introduced (`bodyWidth=2548`, `viewportWidth=2560`).

### Runtime Event Compatibility Normalization Follow-up

- `/api/runtime/events` now emits package-normalized event fields for external Live GUI consumers while preserving the internal `event_type` as `event_type_internal`.
- Approval events are mapped from internal runtime evidence to the imported package contract: `approval.requested` -> `approval_requested`, approved `approval.resolved` -> `approval_granted`, and rejected/cancelled `approval.resolved` -> `approval_rejected`.
- The normalized payload also guarantees package-level `type`, `timestamp`, `stage`, `agent_id`, `graph_id`, `graph_version`, `severity`, `artifact_ids`, and `unread_targets` fields where available, without changing the authoritative internal `/api/events/stream` contract used by the current Live GUI.
- Integration tests now verify approval request/grant/reject normalization through real approval endpoint outputs.

### Graph Run Version/Hash Evidence Follow-up

- Graph run requests now compute stable evidence for the active graph payload before execution: `graph_hash`, `graph_version`, `graph_version_id`, and version path metadata when a saved version matches the active config.
- `controller.start()` records that evidence in `state.run_metadata.runtime_graph`, the `run.created` event payload, and the run start response so operators and external consumers can trace a run back to the exact graph configuration used.
- `graph.compiled` runtime events now carry the same evidence, and `/api/runtime/events` exposes the normalized package-level `graph_version` field from that payload.
- Integration coverage now verifies that `/api/graphs/atr_closed_loop/run` returns graph version/hash evidence, persists it in runtime state, records it in `run.created` and `graph.compiled`, and maps the compiled event to the package `graph_compiled` type.

### Runtime IDE Deep-Link Handoff and Chat Rail Recheck

- The `/live` graph panel now opens Runtime IDE with graph/node context (`/ide?graph=...&node=...&source=live_graph`) so the IDE focuses the currently selected runtime graph node instead of opening a context-free canvas.
- The latest 1920x1080 browser audit rechecked the compact Runtime Chat rail after the handoff update: visible quick actions are limited to approve, revise, reject, pause, resume, safe stop, and dry-run.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_side_rail_latest/live_runtime_ide_browser_audit.png`; measured chat log `height=432`, rail `width=30`, rail side `right`, and rail gap `4px`.

### Live Header Metric Clipping Guard Follow-up

- The top `LIVE` header resource chip now uses compact integer GB memory notation in the visible label while preserving full GPU/RAM details and utilization in the tooltip.
- This prevents long memory strings such as GPU/RAM usage from being hidden by the fixed two-row control-room header.
- Browser audit now fails if any top header metric chip has internal text clipping (`scrollWidth > clientWidth`), not only if the chip escapes the header bounds.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_header_compact_latest/live_runtime_ide_browser_audit.png`; measured `headerMetricOverflowCount=0` and `headerMetricClipped=[]`.

### Runtime Chat User-Reply Context Contract Follow-up

- Live GUI `user_reply` runtime events now separate the message recipient from the UI context that produced the message.
- The event payload records `target_agent_id`, `selected_agent_id`, `selected_node_id`, `selected_graph_node_id`, `selected_trace_id`, `selected_event_key`, `selected_event_type`, and `selected_report_section` in addition to the compatibility `agent_id`, `node_id`, `trace_id`, and `event_key` fields.
- This makes agent-question replies auditable when the operator answers a Specimen/Vision/etc. prompt while the center view or selected binder agent differs from the actual chat target.
- Integration coverage now verifies that a reply targeted to Specimen from an Orchestrator-selected UI context is still routed to the Specimen backend trace while preserving the original selected context.
- Browser audit result after the backend contract change: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_user_reply_context_latest/live_runtime_ide_browser_audit.png`.

### Runtime Chat Current Run-State Preservation Follow-up

- Runtime Chat planning payloads now include the active run context explicitly: `live_run_id`, `live_mode`, `live_stage`, `live_is_running`, and `live_active_goal`.
- Backend `user_reply` runtime events preserve the same data as both individual compatibility fields and a structured `run_context` payload.
- This closes the follow-up requirement that operator messages preserve selected agent/report/node/trace and the current run state, not only the selected UI anchor.
- Integration coverage now verifies that a Specimen-targeted reply from a different selected UI context carries `run_context` and still appears in the Specimen backend trace.
- Browser audit result after the run-context contract change: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_run_context_latest/live_runtime_ide_browser_audit.png`.

### Runtime Chat Report-Section Evidence Preservation Follow-up

- Runtime Chat `user_reply` runtime events now preserve the selected report section body text, not only the section title.
- The payload records `selected_report_section_text` and a bounded `selected_report_section_text_excerpt` so Backend Trace can reconstruct what evidence block the operator was viewing when drafting a follow-up.
- This strengthens the package requirement that follow-up messages preserve selected report context together with selected agent, selected node, selected trace, and current run state.
- Integration coverage now verifies that a Specimen-targeted reply keeps both `selected_report_section` and the selected section body text in the runtime event payload.
- Browser audit result after the report-section evidence change: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_report_section_text_latest/live_runtime_ide_browser_audit.png`.

### Runtime Chat Selected Report Evidence Follow-up

- Runtime Chat already sends `live_selected_report_section_text` with planning messages; backend `user_reply` events now persist that selected report-section body as `selected_report_section_text` plus a compact `selected_report_section_text_excerpt`.
- This lets backend traces reconstruct not only which report section was selected, but the actual evidence block the operator was responding from.
- Integration coverage verifies that Specimen-targeted replies preserve the selected report section title and body text while still routing to the Specimen backend trace.
- Browser audit result after the report-section evidence change: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_report_section_text_latest/live_runtime_ide_browser_audit.png`.

### Runtime Chat Context Reference Label Follow-up

- The compact Runtime Chat context strip now labels the trace/event/node/run anchor as `Ref:` instead of `T:`.
- `A:` remains the selected context agent and `C:` remains the resolved chat target, avoiding ambiguity between target and trace/reference during live operation.
- Integration and browser-audit checks now assert that selected trace flows preserve agent, chat target, and reference context together.

### Live GUI Refresh/Cache Robustness Follow-up

- `/live` now bumps the stylesheet/script asset query version after the Runtime Chat context-ref change so refreshed or newly opened browser windows do not reuse the older rail/context JavaScript.
- `liveChatContextSummary()` now falls back to the latest `/api/state` snapshot when `/api/planning/session` has not yet supplied state, keeping run/stage/reference context populated during initial load, reconnects, and background refresh races.
- Integration coverage checks both the asset version and the session/snapshot state fallback contract.

### Runtime Chat Mode/Run-State Visibility Follow-up

- The compact Runtime Chat `CTX` strip now includes `R:<mode>:<ON|IDLE>` so operators can distinguish live/test/dry-run context without opening a tooltip.
- The tooltip/debug snapshot now preserve `mode`, `running`, and `active_goal` alongside selected agent, resolved chat target, report section, trace/event/node reference, and run id.
- Selected-event context now falls back to the selected binder agent when the event has no mappable agent id, preventing empty `A:-` context during runtime-event inspection.
- Browser audit verifies that selected-trace question handling keeps agent, chat target, live mode, running state, goal, and reference anchor together.

### Runtime State Precedence Follow-up

- Live GUI now uses one `liveRunningFlag(session, snapshot, state)` precedence rule for the Runtime Chat context, planning-message constraints, header run detail, Agent Binder status, and report status.
- Explicit `session.is_running=false` now wins over a stale `/api/state` snapshot, preventing follow-up messages from being tagged as still running after a run has already stopped or paused.
- Snapshot fallback remains available when the planning session has not yet supplied state during initial load or reconnect.

### Operator Attention Evidence Follow-up

- Runtime Chat Operator Attention cards now record backend evidence for question and fault actions instead of only changing local UI state.
- Question `Answer`, question/fault `Open Backend`, and question/fault `Mark Read` actions emit `operator.attention.*` events with attention kind, action, event key, event type, agent, node, trace id, message, and compact payload excerpt.
- The same existing `/api/runs/{run_id}/operator-events` / `/api/runtime/operator-event` path is used, so no duplicate API surface was introduced.
- Browser audit verifies that answering an agent question and opening a fault backend trace append `operator.attention.question_answer` and `operator.attention.fault_backend` evidence.

### Runtime Chat Compact Rail and Fault Trace Readability Follow-up

- Runtime Chat keeps only the essential operator controls in the side rail: approve, revise, reject, pause, resume, safe stop, and dry-run.
- The control rail is attached to the right side of the LLM transcript as a 30px icon-only strip, with full labels available through tooltips; this preserves vertical space for the transcript and keeps the composer compact.
- Selected backend/timeline event cards now expose `failure_code`, `device`, `tool`, and `status` rows so fault handoff actions show operator-readable failure evidence such as `PRINTER_UPLOAD_FAILED` immediately after focus.
- The browser audit helper uses `ATR_WEBDRIVER_HTTP_TIMEOUT_S` with a 90s default because the full Live GUI audit intentionally serializes a large runtime snapshot and report payload.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_chat_rail_final/live_runtime_ide_browser_audit.png`; measured chat log `height=432`, rail `width=30`, rail side `right`, and rail gap `4px`.

### Live Bottom Dock Containment Follow-up

- The Event/IO bottom dock is now constrained as a two-column control-room dock instead of allowing the collapse button to participate as a grid item.
- The collapse button is pinned as a compact absolute control in expanded mode and remains the only visible control in collapsed mode.
- Timeline and IO strips are constrained to the bottom dock bounds, preventing the IO device cards from extending below the 1920x1080 viewport.
- Browser audit now verifies bottom dock containment for timeline, device strip, and collapse button geometry.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_bottom_dock_final/live_runtime_ide_browser_audit.png`; measured bottom dock `height=178`, timeline/device/button containment all `true`, and collapsed chat log expansion from `432px` to `568px`.

### Live Graph and Timeline Blank-Click Deselect Follow-up

- Live Graph mini-canvas now supports operator blank-click deselection: clicking empty canvas clears the selected graph node instead of forcing the previous node to remain selected.
- The cleared state is persisted in the shared Live UI state as `graphSelectionCleared`, so refresh/new-window restoration does not immediately reselect a stale node unless the operator clicks a node again.
- Timeline strips/details now support blank-click deselection for the selected runtime event, clearing the selected trace card and removing the event/trace reference from Runtime Chat context.
- Browser audit now verifies graph canvas blank-click behavior by selecting the Specimen node, clicking empty graph canvas, and confirming zero selected nodes, an empty selected-node panel, and persisted cleared state.
- Browser audit also verifies timeline blank-click behavior by selecting a warning timeline event, clicking empty timeline strip space, and confirming zero selected timeline items, an empty selected-event card, and cleared `selected_event_key` / `trace_id` chat context.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_timeline_deselect_final/live_runtime_ide_browser_audit.png`.

### Timeline-to-Chat Target Follow-up
- Timeline event selection now retargets Runtime Chat to the event's responsible agent, not only the visible timeline/detail panel.
- This prevents a stale specific-agent target from remaining active after the operator selects a backend trace or warning/error event from another agent.
- Browser audit now verifies that selecting a warning timeline event updates the `live-chat-target` selector, debug `chat_context.chat_target`, and `chat_context.selected_agent` to the same event agent before follow-up messages are sent.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_timeline_target/live_runtime_ide_browser_audit.png`.

### Agent Binder Ctrl/Cmd Pin Follow-up
- Agent Binder now supports the package-specified modifier-click operation: Ctrl/Cmd-clicking an agent tab pins that agent's current report evidence without requiring the operator to move to the report action row first.
- The action retargets Runtime Chat to the pinned agent, keeps the visible pinned-finding panel updated, and records auditable runtime evidence as `operator.binder.report_pinned` with `source_action=binder.ctrl_click`.
- Report pin restoration now accepts both `operator.report.pinned` and `operator.binder.report_pinned`, so refreshed/new Live GUI windows can reconstruct pins created from the binder as well as pins created from the report toolbar.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_binder_pin/live_runtime_ide_browser_audit.png`.

### Approval-Gated Execution Follow-up
- Pending operator approval now blocks execution-starting Live GUI actions instead of only showing an approval card. The blocked paths are graph run-test, Runtime Chat node-test, report re-run, binder context node re-run, and timeline replay-prep.
- Safe inspection/control actions remain available: validate, compile, save-version, dry-run, pause, resume, and Safe Stop are not blocked by this gate.
- Blocked execution attempts are recorded as `approval.blocked_execution` with `blocked_action`, `source_action`, `pending_approval_id`, selected agent/node, and the selected report/trace context so Backend/Timeline views can audit why a run did not proceed.
- Approval resolution now updates local pending state immediately and refreshes the resolved run's details instead of pulling unrelated global active-run state. Resolved approval ids are also filtered during debug/state restoration to prevent stale pending approvals from reappearing.
- Operator/intent event recording now falls back to `/api/runtime/operator-event` when a run-specific operator-event endpoint is unavailable, preserving audit evidence even when the selected UI context references a fixture, stale, or closed run id.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_approval_gate/live_runtime_ide_browser_audit.png`.

### Runtime Chat Vertical Space Follow-up
- Runtime Chat now reserves the right side of the LLM transcript as a thinner 28px operator rail and keeps only essential controls there: approve, revise, reject, pause, resume, safe stop, and dry-run.
- The top LIVE header, chat context row, approval area, composer, and Event/IO dock were compressed without changing the runtime API contract, giving the transcript more vertical space in the 1920x1080 control-room layout.
- Browser measurement after the pass: transcript height increased from `500px` to `570px`, quick-action rail width decreased from `30px` to `28px`, rail side remains `right`, and header metric overflow/clipping remains zero.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_compact_after2/live_runtime_ide_browser_audit.png`.

### Runtime Focus Strip Follow-up
- The center Report/Backend/Graph panel now has a compact `live-focus-strip` directly under the panel title. It mirrors the same source of truth as Runtime Chat `CTX` through `liveChatContextSummary()`.
- The strip exposes operator-critical context before any action is pressed: selected agent, center view, chat target, run mode/running state, runtime stage, selected trace/event/node reference, and selected report section.
- Trace/question/fault selection updates both the chat `CTX` line and the center Focus strip, reducing the risk of approving, re-running, or asking about the wrong agent or trace.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_focus_strip/live_runtime_ide_browser_audit.png`; Focus strip rendered 7 chips with no overflow at 1920px width.

### Device Trace Focus Follow-up
- Device/runtime cards in the bottom IO strip now become trace entry points when they are backed by a runtime event.
- Clicking a device card, or pressing Enter/Space while focused on it, selects the related runtime event, switches the center panel to Backend mode, retargets Runtime Chat to the owning agent, updates the Focus strip, and records `operator.device.trace_focused` evidence.
- This keeps device errors from being passive status text only: a 3D printer, robot, UTM, camera, Windows bridge, or sensor fault can be inspected from the IO strip without manually searching the timeline.
- Browser audit result: `live_runtime_ide_browser_audit: PASS` with screenshot `/tmp/atr_live_goal_audit_device_focus/live_runtime_ide_browser_audit.png`; the audit verifies that a device error card focuses the matching `PRINTER_UPLOAD_FAILED` backend trace and emits `operator.device.trace_focused`.

### Pinned Finding Compare Follow-up
- The report surface now includes a compact `Selected vs Pinned` comparison block above the pinned findings list.
- The latest pinned finding is rendered with a `Focus Pinned` action so the operator can jump back into the same report/trace context without hunting through the timeline.
- Focusing a pinned item now restores the report section, selected trace context, chat target, and Focus strip in one step, and appends `operator.report.pinned_focused` evidence.
- Focused browser probe result: the compare card rendered with the expected current/pinned sections, `Focus Pinned` updated the report focus strip, and the event stream appended `operator.report.pinned` followed by `operator.report.pinned_focused`.
### Pinned Compare Sync Note
- The report compare area now shows the current selection next to the latest pinned finding, and `Focus Pinned` returns the report workspace to that pinned context without losing the selected section or trace focus.
- Browser validation for the focused pin path now covers `operator.report.pinned` and `operator.report.pinned_focused` as separate events.
