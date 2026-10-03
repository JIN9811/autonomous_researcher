# AX4LAB Tutorials

Choose the task you want to complete. On a new workstation, begin with
[installation](../../install/README.md), then complete one virtual experiment in
your preferred language. That first exercise ends with saved results and a run ID;
device guides are separate tasks for when you are ready to use hardware.

새 워크스테이션이라면 [설치 안내](../../install/README.md)를 먼저 따르고,
아래의 **첫 실행**으로 가상 실험 한 사이클과 결과 확인까지 진행합니다.
실제 장비 작업은 해당 장비 안내를 별도로 선택합니다.

| Task | English | 한국어 |
|---|---|---|
| Start a first virtual experiment and inspect its results | [First run](first_autonomous_run.en.md) | [첫 실행](first_autonomous_run.ko.md) |
| Operate devices, record demonstrations, recover a run or review results | [Operator manual](user_manual.en.md) | [운영 안내](user_manual.ko.md) |
| Save print settings, slice and inspect before printing | [3D Printer](device_workspace_3dp_usage.en.md) | [3D 프린터](device_workspace_3dp_usage.ko.md) |
| Configure the UTM camera and distinguish pose tests from run evidence | [Vision](device_workspace_vision_camera_bridge_usage.en.md) | [비전](device_workspace_vision_camera_bridge_usage.ko.md) |

For a map of every page rather than a procedure, see
[GUI Structure and Screen Reference](../gui/visual_structure.md).
For dependency/version details after choosing your installation path, use
[Requirements](../../REQUIREMENTS.md).

## Before following a screenshot

Figures are actual **1920 × 1080** browser-content captures from 29 September 2026.
Open an image for its full-resolution view. They illustrate an existing installation,
not prescribed parameter values. Private connection details are redacted.

Use each figure to locate the named control, then check the outcome in your own
session. Some Live figures show a completed historical run; camera/robot panels
may be idle, and missing evidence is deliberately left visible. No experiment,
print, robot move, camera capture or configuration save was performed for the captures.
See the [capture record](assets/screenshots/2026-09-29/capture_manifest.json).

The Main GUI mode chooses how you enter the application; the execution profile
and per-agent settings determine device effects. **Test mode does not itself mean
“no hardware.”** Use **Virtual Bridge** with virtual boundaries for the first
exercise. **Installed Printer** and **Physical Print** can operate real devices.

Main의 모드와 장비 실행 프로필은 별개입니다. **Test라는 이름만으로 실제
장비 동작이 차단되지는 않습니다.** 첫 실습은 **Virtual Bridge**와 에이전트별
가상 실행 설정을 확인하고 진행합니다.

## What to keep at the end

Keep the run ID, cycle/candidate identity, artifact paths and the actual
completion or failure evidence. The first-run walkthrough shows where to find
these; [artifact preservation](../gui/artifact_preservation.md) explains what to
retain, and [Replay](../gui/run_replay.md) explains read-only session review.
Analysis and optimization figures help interpret a result, but do not prove that
a physical device completed its task.

실험을 마치거나 문제가 생기면 run ID, 사이클·후보 ID, 파일 경로와 완료·실패
근거를 함께 남깁니다. 멈춘 실험은 새로 시작하기 전에
[기존 실험 재개 안내](../gui/run_resume.md)를 확인합니다.
