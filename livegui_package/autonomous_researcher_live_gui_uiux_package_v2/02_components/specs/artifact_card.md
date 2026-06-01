# Artifact Card

## Purpose
STL/PNG/SVG/CSV/JSON/PDF/MD 등 산출물을 공통 card로 제공한다.

## Required data
- `artifact_id`
- `filename`
- `type`
- `size`
- `agent_id`
- `created_at`
- `preview_url`

## CSS classes
- `.ar-card`
- `.ar-artifact-card`

## HTML skeleton

```html
<article class="ar-card ar-artifact-card">
  <img src="preview.png" alt="artifact preview"><b>specimen_design.stl</b><small>DSN · 1.2 MB</small>
</article>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
