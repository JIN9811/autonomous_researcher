# Chart Card

## Purpose
donut, line, bar, scatter, heatmap, radar 등 plot을 report card 크기에 맞춰 제공한다.

## Required data
- `chart_type`
- `series`
- `legend`
- `axis`
- `summary`

## CSS classes
- `.ar-chart-card`
- `.ar-card`

## HTML skeleton

```html
<article class="ar-card ar-chart-card"><h3>Decision Register</h3><div class="chart"></div></article>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
