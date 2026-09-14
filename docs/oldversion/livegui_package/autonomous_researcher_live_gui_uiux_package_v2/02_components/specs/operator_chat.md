# Operator Chat

## Purpose
live_chat_message.v1를 사람이 읽을 수 있는 card로 렌더링한다.

## Required data
- `agent_id`
- `message_type`
- `headline`
- `content`
- `requires_response`
- `actions`

## CSS classes
- `.ar-chat-message`

## HTML skeleton

```html
<article class="ar-chat-message" data-type="decision">
  <strong>Design Agent</strong><p>Generated 5 design candidates. Top score 0.87.</p>
</article>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
