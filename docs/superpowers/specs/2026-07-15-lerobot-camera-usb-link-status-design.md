# LeRobot Camera USB Link Status Design

## Objective

Show the negotiated USB link for the saved Top and Wrist RealSense cameras in
Device Port Setup so an operator can distinguish a healthy USB 3.x connection
from a USB 2.x fallback before starting teleoperation, recording, or rollout.

## Scope

- Detect the live USB type descriptor and numeric link speed during RealSense
  Detect & Save.
- Persist the detected link metadata with each saved camera entry.
- Render the saved link on the Top and Wrist camera cards after refresh.
- Use a normal green state for USB 3.x and an amber warning for USB 2.x.
- Do not reset cameras, block workflows, or change rollout behavior.

## Backend Contract

Each RealSense camera candidate and saved camera entry may include:

```json
{
  "usb_type": "3.2",
  "usb_speed_mbps": 5000,
  "usb_link_label": "USB 3.2 · 5000 Mbps",
  "usb_link_status": "ok"
}
```

`usb_link_status` is `ok` for a USB 3.x link, `warning` for a USB 2.x link,
and `unknown` when the runtime cannot read the descriptor. Missing metadata
must remain backward compatible with existing saved profiles.

## UI Behavior

- The Top and Wrist camera cards show one compact USB badge near the saved
  camera identifier.
- `ok`: green badge, for example `USB 3.2 · 5000 Mbps`.
- `warning`: amber badge, for example `USB 2.1 · 480 Mbps · rollout risk`.
- `unknown`: neutral badge `USB link unknown`.
- Detect & Save refreshes the badge immediately; page refresh restores the
  persisted value.

## Error Handling

- Failure to read USB metadata must not make Detect & Save fail when the camera
  itself is visible.
- Existing camera identity, profile selection, and rollout command generation
  remain unchanged.

## Verification

- Unit test candidate metadata normalization for USB 3.x, USB 2.x, and unknown.
- Unit test persistence in the saved camera profile.
- Static/UI test that Top and Wrist cards render the badge and warning state.
- Run the focused bridge and GUI test suites plus `git diff --check`.
