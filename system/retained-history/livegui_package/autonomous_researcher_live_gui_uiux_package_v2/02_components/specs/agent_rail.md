# Agent Rail

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

## Purpose
agent 상태, warning, approval, selected agent를 빠르게 전환한다.

## Required data
- `agent_id`
- `name`
- `status`
- `warning_count`
- `approval_count`

## CSS classes
- `.ar-agent-row`
- `.ar-status-chip`

## HTML skeleton

```html
<button class="ar-agent-row" data-agent-id="dsn" aria-selected="true">
  <span class="ar-agent-icon">DSN</span><span>Design Agent</span><span class="ar-status-chip" data-state="active">Active</span>
</button>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
