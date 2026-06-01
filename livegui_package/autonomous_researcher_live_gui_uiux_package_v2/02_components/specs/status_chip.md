# Status Chip

## Purpose
active/running/waiting/blocked/warning/done/idle 상태를 통일한다.

## Required data
- `state`
- `label`

## CSS classes
- `.ar-status-chip`

## HTML skeleton

```html
<span class="ar-status-chip" data-state="warning">Warning</span>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
