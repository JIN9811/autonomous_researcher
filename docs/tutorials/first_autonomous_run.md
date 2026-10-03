# AX4LAB Tutorials

Start with the first-run walkthrough, then follow the device guide for the hardware
you intend to use. Each tutorial pairs exact GUI actions with screenshots,
expected evidence and a recovery checkpoint.

| Task | English | 한국어 |
|---|---|---|
| Start a first virtual experiment and inspect its results | [First run](first_autonomous_run.en.md) | [첫 실행](first_autonomous_run.ko.md) |
| Configure devices, record demonstrations and review a session | [Operator walkthroughs](user_manual.en.md) | [운영자 실습](user_manual.ko.md) |
| Save print settings, slice and inspect before printing | [3D Printer](device_workspace_3dp_usage.en.md) | [3D 프린터](device_workspace_3dp_usage.ko.md) |
| Configure the UTM camera and distinguish pose tests from run evidence | [Vision](device_workspace_vision_camera_bridge_usage.en.md) | [비전](device_workspace_vision_camera_bridge_usage.ko.md) |

For a map of every page rather than a procedure, see
[GUI Structure and Screen Reference](../gui/visual_structure.md).
For installation, begin with [Requirements](../../REQUIREMENTS.md).

## Before following a screenshot

Figures are actual **1920 × 1080** browser-content captures from 29 September 2026.
Open an image for its full-resolution view. They illustrate an existing installation,
not prescribed parameter values. Private connection details are redacted.

Some Live figures show a completed historical run; camera/robot panels may be idle,
and missing evidence is deliberately left visible. No experiment, print, robot move,
camera capture or configuration save was performed to make these tutorials.
See the [capture record](assets/screenshots/2026-09-29/capture_manifest.json).

The Main GUI mode and the device execution profile are different choices.
**Test mode does not itself mean “no hardware.”** Begin with the Virtual Bridge
profile; Installed Printer and Physical Print can operate real devices.

## What to keep at the end

Keep the run ID, cycle/candidate identity, source artifact paths and the actual
completion/error evidence. ANL curves and BO posterior figures are useful outputs,
not substitutes for successful device execution. For two design variables, inspect
the BO mean, uncertainty and acquisition surfaces in 2D/3D; an old 1D display path
is not the full design space.
