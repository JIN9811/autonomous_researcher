# Windows PyAutoGUI Bridge 설치 및 운영 가이드

이 가이드는 Windows 장비 제어 PC를 Linux AX4LAB(ATR)에 연결하고, 연결 확인과
실제 프로그램 실행을 구분하는 절차입니다. 연결 성공은 UTM 시험 완료를 뜻하지
않습니다. Windows에서는 로그인한 사용자의 화면을 제어하고, Linux에서는 실행
대상 선택과 증거 확인을 담당합니다.

패키지 설치·녹화·업데이트의 상세 절차는
[Windows Bridge 시작 안내](../../Pyautogui_server_for_window/README.md)와
[Windows Bridge 운영 안내](../../Pyautogui_server_for_window/docs/USAGE.md)를
따릅니다. 이 페이지에서는 ATR과 연결할 때 확인할 항목을 설명합니다.

## 시작 전 확인

Windows x64 PC의 로그인 세션과 제어할 프로그램을 준비합니다. 화면 잠금 상태나
Windows service에서는 PyAutoGUI의 대화형 데스크톱 제어를 기대하면 안 됩니다.
장비가 연결된 경우 시험 프로그램의 동작과 정지 방법을 먼저 확인하고, 진행 중인
ATR 실험이 소유한 장비를 수동으로 조작하지 않습니다.

Windows와 Linux가 같은 내부망에서 통신할 수 있는지 확인합니다. 방화벽 규칙은
가능하면 TCP 8765를 Linux ATR 사설 IP에만 허용합니다. 아래 명령의 주소는 실제
Linux 사설 IP로 바꾸며, 설치 권한을 가진 관리자가 적용합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\firewall_allow_private.ps1 -RemoteAddress <linux-private-ip>
```

## 설치

권장 방식은 Windows x64 포터블 폴더입니다.

1. 배포받은 release 폴더 전체를 Windows 로컬 디스크에 복사합니다. 실행 파일만
   따로 옮기지 않습니다.
2. `START_PORTABLE_BRIDGE.cmd`를 실행하고, 해당 폴더 안에 실행 환경을 구성하는
   최초 준비 작업이 끝날 때까지 기다립니다.
3. 브라우저 Console에서 `Bridge Status`와 일회성 연결 코드를 확인합니다.
   Console이 열렸다는 사실만으로 장비 실행이 가능한 것은 아닙니다.
4. 아래 **ATR 연결** 절차로 연결을 저장하고 `Health`와 `Programs`를 확인합니다.
   실제 `Test` 실행은 연결 점검과 분리하여 승인된 경우에만 진행합니다.

표준 설치는 전체 package를 유지할 폴더에 복사한 뒤 `INSTALL_WINDOWS_BRIDGE.cmd`를 실행합니다. 현재 installer는 그 package 폴더에 `.venv`를 만들고 같은 폴더의 supervisor를 로그인 작업·바로가기에 등록하며 별도 `%LOCALAPPDATA%\Programs` 설치본으로 복사하지 않습니다. 기본 데이터 경로는 `%LOCALAPPDATA%\ATR\PyAutoGUIBridge`입니다. PyAutoGUI는 interactive desktop이 필요하므로 Windows service가 아니라 로그인 사용자 세션에서 실행합니다.

구버전에서 전환할 때만 최신 package를 한 번 복사해 `INSTALL_WINDOWS_BRIDGE.cmd`를 실행합니다. 그 다음 버전부터는 Linux `Lab Equipment Workspace > Saved Worker`의 `Check Update`와 `Update`로 server, launcher, updater, Python dependency를 같은 설치 폴더에 원격 반영합니다.

## Console 구성

- Bridge Status
- Program Manager
- Recording
- Latest Local Result
- 접힌 Diagnostics

Windows Console에서 UTM proof, Skill compile/deploy, Analysis handoff, ATR Controller 검색은 수행하지 않습니다.

## 4자리 페어링

Bridge Status에 표시된 4자리 일회성 코드를 Linux ATR Equipment Workspace에 최초 한 번 입력합니다. 성공 후 내부 인증키가 양쪽 보호 파일에 저장되어 서버·GUI 재시작 뒤에도 자동 사용되며, 사용자는 코드를 다시 입력하지 않습니다. 기존에 저장된 worker secret도 연결 인증으로 계속 유효합니다. 코드 유효 시간은 5분, 입력 한도는 5회, lockout은 30초입니다.

## 방화벽

TCP 8765의 제한된 허용 규칙은 **시작 전 확인**에 있습니다. 검색되지 않을 때
광범위하게 방화벽을 끄기보다 bind 주소, 포트, Linux 사설 IP와 내부망 경로를
확인합니다.

## 설치 확인

먼저 연결 상태만 확인합니다. 이 명령은 local Health/pairing을 점검합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_bridge.ps1
```

다음 명령은 별도 실행 시험입니다. 연결된 `program1`을 실제 실행하므로, 프로그램
내용과 대상 창, 장비의 안전 상태 및 실행 승인을 확인한 경우에만 사용합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_bridge.ps1
```

결과는 `Latest Local Result`와 요청 로그에서 확인합니다. 응답이 없거나 timeout이
발생하면 실제 장비 상태와 실행 흔적을 먼저 확인하고, 같은 명령을 재전송하지 않습니다.

## ATR 연결

1. Linux Main GUI의 `Device Workspace > Lab Equipment`를 엽니다.
2. `Windows Bridge Scan`으로 검색합니다. 검색 단계에는 코드가 필요 없습니다.
3. 사용할 candidate를 선택하고, 선택한 `Candidate` 카드에 Windows의 4자리 코드를
   입력합니다. 다른 PC의 후보를 선택하지 않았는지 주소와 이름을 확인합니다.
4. `Pair & Save`로 연결과 alias를 저장한 뒤 `Select`로 실행 대상을 선택합니다.
5. `Health`와 `Programs`로 선택한 worker의 응답 및 등록 프로그램 목록을
   확인합니다. 이 단계의 성공은 연결·목록 확인이며 프로그램 실행 완료가 아닙니다.
6. 실제 실행이 필요한 경우에만 정확한 프로그램과 버전을 검토하고 `Test`를
   사용합니다. 결과의 실행 식별자와 단계 기록, 화면·파일 증거를 함께 확인합니다.

실험 루프는 `LabEquipmentAgent -> EquipmentRuntimeService -> equipment.pyautogui.run` 경로로만 실행합니다.

## 데이터와 백업

설치형 기본 data root:

```text
%LOCALAPPDATA%\ATR\PyAutoGUIBridge
```

포터블은 package `data\`를 사용합니다. 재설치 전 `programs`, `locators`, `recordings`를 백업할 수 있지만 `pairing.json`은 다른 PC에 복제하지 않는 것이 원칙입니다.

## 장애 진단

| 증상 | 먼저 확인할 것 | 멈춰야 하는 경우 |
| --- | --- | --- |
| 검색 실패 | bind 주소, 포트, 방화벽, 같은 내부망 | 다른 worker로 임의 전환하지 않음 |
| pairing 실패 | 새 코드, 5분 만료, 5회 입력 한도, 30초 lockout | 연결키를 복사해 우회하지 않음 |
| desktop 제어 실패 | 화면 잠금, 로그인 세션, DPI, 대상 창 | 실행 효과가 불분명하면 재실행하지 않음 |
| locator 실패 | 현재 screenshot과 reference의 일치 여부 | 창 위치를 임의로 추정하여 클릭하지 않음 |
| execute timeout | request log, 실제 장비 상태, 실행 ID | 실행되지 않았다고 가정하여 중복 전송하지 않음 |

지원 요청에는 선택한 worker/profile, 실행 ID, 실패 코드와 관련 로그를 남깁니다.
연결키나 비공개 화면은 공개 보고서에 포함하지 않습니다.

## 상세 문서

- [패키지 시작 안내](../../Pyautogui_server_for_window/README.md)
- [프로그램·녹화·업데이트 운영 절차](../../Pyautogui_server_for_window/docs/USAGE.md)
- [Windows bridge 실행 경계](../device_bridges/windows_pyautogui_bridge.md)
- [Equipment 완료 증거와 복구 기준](../agents/equipment_agent.md)
