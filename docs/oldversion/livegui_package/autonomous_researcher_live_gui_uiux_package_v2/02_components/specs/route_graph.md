# Route Graph

## Purpose
Orchestrator handoff route와 agent graph state를 보여준다.

## Required data
- `nodes`
- `edges`
- `current_node`
- `blocked_edges`

## CSS classes
- `.ar-route-graph`
- `.ar-card`

## HTML skeleton

```html
<section class="ar-card ar-route-graph"><svg role="img" aria-label="agent route graph"></svg></section>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
