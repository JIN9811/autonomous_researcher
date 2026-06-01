# Approval Card

## Purpose
human/Guardian approval 상태를 명확히 보여주고 approve/reject/revise action을 제공한다.

## Required data
- `approval_id`
- `title`
- `risk_level`
- `status`
- `requested_by`
- `actions`

## CSS classes
- `.ar-card`
- `.ar-btn--primary`
- `.ar-btn--danger`

## HTML skeleton

```html
<article class="ar-card" data-approval-id="apv-001">
  <h3>Approve Execution Plan</h3><button class="ar-btn ar-btn--primary">Approve</button><button class="ar-btn">Request Changes</button>
</article>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
