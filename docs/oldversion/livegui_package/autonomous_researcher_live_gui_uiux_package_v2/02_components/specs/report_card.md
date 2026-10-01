# Report Card

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

## Purpose
operator-facing section card. raw JSON 대신 summary, decision, evidence, next action을 보여준다.

## Required data
- `section_id`
- `title`
- `summary`
- `status`
- `actions`
- `evidence_refs`

## CSS classes
- `.ar-card`
- `.ar-card__title`
- `.ar-card__desc`

## HTML skeleton

```html
<article class="ar-card ar-span-4" data-section="mission_contract">
  <h3 class="ar-card__title">Mission Contract</h3>
  <p class="ar-card__desc">Current objective and constraints.</p>
</article>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
