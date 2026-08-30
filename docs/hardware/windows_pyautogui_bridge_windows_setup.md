# Windows PyAutoGUI Bridge 설치 및 운영 가이드

현재 권위 문서는 `Pyautogui_server_for_window/README.md`와 `docs/USAGE.md`이며 이 문서는 ATR 시스템 관점의 설치 요약입니다.

## 설치

권장 방식은 Windows x64 포터블 폴더입니다.

1. 전체 release 폴더를 Windows 로컬 디스크에 복사
2. `START_PORTABLE_BRIDGE.cmd` 실행
3. 최초 folder-local runtime 구성 완료 대기
4. 브라우저 Console 확인
5. Linux ATR에서 4자리 코드로 Pair & Save

표준 설치는 `INSTALL_WINDOWS_BRIDGE.cmd`를 실행합니다. 이 과정에서 `%LOCALAPPDATA%\Programs\ATR\PyAutoGUIBridge`가 canonical 실행·원격 업데이트 경로로 저장됩니다. 이후 package 폴더의 START 파일을 눌러도 설치본을 우선 실행합니다. PyAutoGUI는 interactive desktop이 필요하므로 Windows service가 아니라 로그인 사용자 세션에서 실행합니다.

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

TCP 8765를 Linux ATR 사설 IP에만 허용하는 구성이 권장됩니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\firewall_allow_private.ps1 -RemoteAddress <linux-private-ip>
```

## 설치 확인

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_bridge.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_bridge.ps1
```

첫 명령은 local Health/pairing을, 두 번째는 paired `program1` 실행을 확인합니다.

## ATR 연결

1. Device Workspace > Lab Equipment
2. Windows Bridge Scan (코드 입력 없음)
3. candidate 선택
4. 선택한 Candidate 카드에 4자리 code 입력
5. Pair & Save와 alias 저장
6. Select > Health > Programs > Test

실험 루프는 `LabEquipmentAgent -> EquipmentRuntimeService -> equipment.pyautogui.run` 경로로만 실행합니다.

## 데이터와 백업

설치형 기본 data root:

```text
%LOCALAPPDATA%\ATR\PyAutoGUIBridge
```

포터블은 package `data\`를 사용합니다. 재설치 전 `programs`, `locators`, `recordings`를 백업할 수 있지만 `pairing.json`은 다른 PC에 복제하지 않는 것이 원칙입니다.

## 장애 진단

- 검색 실패: bind 주소, 포트, 방화벽, 같은 내부망 확인
- pairing 실패: 새 코드, 만료/lockout 확인
- desktop 제어 실패: 화면 잠금, interactive session, DPI, target window 확인
- locator 실패: 현재 screenshot과 reference 재검증
- execute timeout: 중복 실행하지 말고 request log와 실제 장비 상태 확인

## 상세 문서

- `Pyautogui_server_for_window/README.md`
- `Pyautogui_server_for_window/docs/USAGE.md`
- `docs/device_bridges/windows_pyautogui_bridge.md`
- `docs/agents/equipment_agent.md`
