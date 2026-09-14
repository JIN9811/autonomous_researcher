# Backend Trace Panel

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
