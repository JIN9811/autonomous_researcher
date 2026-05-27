# UI Spec: ATR Live GUI Main Screen

## Layout
Use a 3-column layout: compact binder, center report/backend panel, persistent runtime chat.

Recommended desktop proportions:
- Agentic Binder: 1
- Center Panel: 4.5
- Runtime Chat: 4.5

Practical CSS:
```css
grid-template-columns: 104px minmax(520px, 1fr) minmax(480px, 1fr);
```

## Header
Header must include:
- Logo / title
- Run ID
- Stage
- Active Agent
- Mode
- Status
- Runtime
- System health
- resource chips
- Safe Stop button

## Agentic Binder
Vertical bookmark-style agent index.

Tab content:
- icon
- short label
- state dot/pill
- unread badge
- tooltip

States:
- idle
- pending
- running
- done
- waiting
- warning
- error

Unread behavior:
- unread_count = 1: show !
- unread_count > 1: show number
- click tab: mark read and open report

## Center Panel Modes
- Report Mode
- Backend Trace Mode
- Artifact View
- Graph Detail View
- Timeline Detail View

Report Mode is default.

## Report Page
Academic/futuristic report page with:
- title
- status
- elapsed time
- tab nav: Overview / Inputs / Process / Artifacts / Results / Handoff
- section cards
- artifact cards
- BACKEND button

## Backend Trace Drawer
Shows raw prompt, model stream, tool calls, node I/O JSON, logs, handler reference, artifacts.

## Runtime Chat
Persistent right-side panel.

Header:
- Runtime Chat
- active route/selected target

Controls:
- Target dropdown
- Mode segmented control: Ask / Command / Approval / Edit
- Message stream
- Input box
- Quick actions

## Bottom Timeline
Displays chronological events with clickable milestones.

## Device Status
Compact cards for printer, robot, UTM, camera, env sensor, GPU, LLM server.
