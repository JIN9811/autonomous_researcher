# Bottom Dock

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

## Purpose
events, device health, run logs, artifacts를 접히는 strip으로 보여준다.

## Required data
- `events`
- `device_health`
- `run_logs`
- `artifacts`

## CSS classes
- `.ar-bottom-dock`
- `.ar-card`

## HTML skeleton

```html
<footer class="ar-bottom-dock ar-panel">
  <section class="ar-card">Events</section><section class="ar-card">Device Health</section><section class="ar-card">Artifacts</section>
</footer>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
