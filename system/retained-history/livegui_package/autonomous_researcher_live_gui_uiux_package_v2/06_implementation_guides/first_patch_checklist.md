# First Patch Checklist

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../README.md) for maintained replacements.

## CSS-only pass

- [ ] Add CSS variables from `01_design_tokens/design_tokens.css`.
- [ ] Reduce glow/gradient on Live GUI panels.
- [ ] Normalize status chip colors.
- [ ] Make header one-line and prevent chip overlap.
- [ ] Improve chat message padding/line-height.
- [ ] Add `prefers-reduced-motion` guard.

## Renderer pass

- [ ] Add `normalizePlanningMessage(raw)`.
- [ ] Add `renderLiveChatMessageV1(message)`.
- [ ] Add `renderAgentReport(agentId, report)`.
- [ ] Add `AGENT_REPORT_SECTIONS` registry based on `03_screen_specs/json`.
- [ ] Keep raw JSON only in Backend Trace view.

## Audit

- [ ] 1920x1080 screenshot: no horizontal overflow.
- [ ] Header, center, chat, agent rail do not overlap.
- [ ] Report view has no raw JSON dump.
- [ ] Backend view shows raw payloads.
- [ ] Approval/Guardian state is visible.
