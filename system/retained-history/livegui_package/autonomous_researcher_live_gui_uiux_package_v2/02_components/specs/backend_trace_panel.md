# Backend Trace Panel

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

## Purpose
raw prompt/tool I/O/event payload/stack trace를 Report와 분리해 보여준다.

## Required data
- `trace_id`
- `agent_id`
- `raw_payload`
- `tool_calls`
- `stack_trace`

## CSS classes
- `.ar-backend-trace`
- `.ar-card`

## HTML skeleton

```html
<section class="ar-backend-trace ar-card"><pre>{ "raw": true }</pre></section>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
