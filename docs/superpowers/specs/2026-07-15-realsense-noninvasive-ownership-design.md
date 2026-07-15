# RealSense Non-Invasive Ownership Design

## Goal

Prevent LeRobot inference and ActiveCam orchestration from repeatedly opening RealSense devices while preserving saved camera identities, rollout options, and explicit camera capture behavior.

## Runtime Contract

- Routine device presence and USB link checks read `/sys/bus/usb/devices` and do not instantiate `pyrealsense2` when matching USB devices are visible.
- A serial-less D455F discovered during USB 2.0 enumeration remains visible through its configured `top` identity and carries an explicit link warning.
- Explicit ActiveCam capture remains the only one-shot capture process in the Live GUI path.
- A successfully exited ActiveCam child process is treated as having released its OS handles; no second RGB-D stream is opened to prove release.
- Rollout remains the next process allowed to open the configured cameras.
- No fallback camera, USB reset, unbind/rebind, or saved profile mutation is introduced.

## Failure Handling

- Missing sysfs devices may use the existing SDK enumeration fallback for portability.
- ActiveCam capture failures remain blocking.
- A successful child process with a valid capture artifact reports `process_exit_verified` release status.

## Verification

- Unit tests prove sysfs enumeration avoids importing or calling `pyrealsense2`.
- Unit tests prove successful ActiveCam capture launches one process only and does not launch the reacquire probe.
- Focused camera, rollout-profile, and GUI API regression tests remain green.
