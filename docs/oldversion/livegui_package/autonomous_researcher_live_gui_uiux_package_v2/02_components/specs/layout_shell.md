# Layout Shell

## Purpose
전체 Live GUI frame. Header, agent rail, center report, operator chat, bottom dock를 고정한다.

## Required data
- `run_id`
- `selected_agent_id`
- `selected_view`
- `pending_approvals`
- `stream_status`

## CSS classes
- `.ar-live-shell`
- `.ar-panel`
- `.ar-report-grid`

## HTML skeleton

```html
<main class="ar-live-shell" data-run-id="run-...">
  <header class="ar-panel ar-topbar"></header>
  <aside class="ar-panel ar-agent-rail"></aside>
  <section class="ar-panel ar-center"></section>
  <aside class="ar-panel ar-operator-console"></aside>
  <footer class="ar-panel ar-bottom-dock"></footer>
</main>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
