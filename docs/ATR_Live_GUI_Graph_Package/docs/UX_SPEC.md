# UX Spec: ATR Runtime IDE Interaction Model

## Core UX Goal
The user must always know:
1. What is running now.
2. Which agent is responsible.
3. Why the agent made a decision.
4. What artifact was produced.
5. What the next handoff is.
6. Whether user approval is required.
7. How to inspect backend traces.
8. How to safely stop the system.

## Navigation Model
- Left binder selects agent/report.
- Center shows selected agent report or backend trace.
- Right chat remains persistent.
- Bottom timeline supports time-based inspection.

## Context Preservation
When the user selects an agent, the selected agent becomes the default chat target.
When the user selects a report section, the chat may edit/explain that section.
When the user opens backend trace, the chat may answer questions about trace_id.

## Follow-up Flow
1. Agent emits `agent_question` or `approval_requested` event.
2. Binder tab shows amber waiting indicator and unread badge.
3. Runtime Chat shows a question/approval card.
4. User answers or approves/revises/rejects.
5. Backend records the response in trace and run log.
6. Runtime continues or replans.

## Graph Editing Flow
1. User opens graph editor or selected module graph.
2. User changes nodes/edges/handler assignments.
3. User clicks Validate.
4. Backend returns diagnostics.
5. User clicks Compile.
6. Compiler emits graph hash/version.
7. User saves version.
8. Runtime can run that version.

## Report-to-Backend Flow
1. User sees structured report section.
2. User clicks BACKEND.
3. Backend drawer opens with raw trace.
4. User can inspect prompt/tool/JSON/log/code reference.
5. User can ask Runtime Chat about trace.
6. User can return to Report Mode without losing chat.

## Safety Flow
- Safe Stop visible at all times.
- Live mode graph changes require validation.
- Device errors surface in binder, header, timeline, and chat.
- Approval-required state must block unsafe live execution.
