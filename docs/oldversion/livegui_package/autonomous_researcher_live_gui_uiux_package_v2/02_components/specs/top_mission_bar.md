# Top Mission Bar

## Purpose
mission, stage, safety, sync/resource/device, Safe Stop을 한 줄로 제공한다.

## Required data
- `mission_name`
- `stage`
- `safety_state`
- `latency_ms`
- `gpu_pct`
- `mem_pct`
- `tokens_per_sec`
- `device_state`

## CSS classes
- `.ar-topbar`
- `.ar-status-chip`
- `.ar-btn--danger`

## HTML skeleton

```html
<header class="ar-topbar ar-panel">
  <strong>ATR Runtime IDE — <span>LIVE</span></strong>
  <div>Mission <b>Autonomous Polymer Specimen Design</b></div>
  <span class="ar-status-chip" data-state="active">SAFE</span>
  <button class="ar-btn ar-btn--danger">SAFE STOP</button>
</header>
```

## Implementation notes
- Report view에는 사람이 읽는 summary를 우선 배치한다.
- raw prompt, raw event payload, stack trace는 Backend Trace Panel로 이동한다.
- action button은 실제 endpoint나 local view action에 연결한다.
