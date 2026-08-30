---
doc_type: reference
subtype: runtime
status: active
authority: descriptive
audience: [researcher, operator, developer, integrator]
scope: [windows_pyautogui, equipment_worker, pairing, recording]
summary: Lightweight Windows worker contract for paired bounded PyAutoGUI programs and recording evidence.
source_of_truth:
  - Pyautogui_server_for_window/bridge/windows_pyautogui_bridge_server.py
  - install/windows_pyautogui_bridge_server.py
  - device_bridges/windows_pyautogui_bridge.py
  - mcp_tools/equipment_tools.py
last_verified: 2026-08-28
verified_against: working-tree-2026-08-28
related_docs:
  - docs/agents/equipment_agent.md
  - docs/hardware/windows_pyautogui_bridge_windows_setup.md
  - Pyautogui_server_for_window/README.md
---

# Windows PyAutoGUI Bridge Reference

## 목적

Windows PyAutoGUI Bridge는 Linux Equipment Runtime의 저수준 worker입니다. Windows desktop에서 검증된 프로그램을 실행하고 화면, locator, 녹화, 파일, 요청 로그를 반환합니다.

Windows Bridge는 LLM, Guardian 판단, Skill lifecycle, UTM 실험 의미, 완료 판정, Analysis handoff, ATR Controller 탐색을 소유하지 않습니다.

## 배포 형태

- 설치형: `%LOCALAPPDATA%\Programs\ATR\PyAutoGUIBridge`
- 포터블: 폴더 내부 `runtime\python`과 `data\`
- 개발형: 동일 서버를 Linux X11에서 Local Bridge로 명시 실행

설치형과 포터블은 같은 API와 프로그램 형식을 사용합니다. PyAutoGUI는 대화형 desktop이 필요하므로 Windows service로 실행하지 않습니다.

## 페어링과 인증

최초 연결은 4자리 일회성 코드로 수행합니다.

- 유효 시간 300초
- 최대 5회 입력
- 성공 즉시 폐기
- 실패 한도 도달 시 30초 lockout
- 성공 후 내부 장기키 자동 생성
- Windows와 Linux의 보호된 connection memory에 저장

사용자는 장기키를 반복 입력·복사하지 않습니다. 4자리 코드는 최초 연결 키 교환에만 쓰며, 이후 요청은 저장된 worker secret 또는 교환된 internal key를 자동 사용합니다. pairing code/internal key는 URL, 브라우저 저장소, request audit에 기록하지 않습니다.

페어링 전 로컬 Console에서 허용되는 기능:

- GUI와 local Health
- pairing status/new code
- Program Manager
- Recording

원격 `/execute`, screenshot, locator, artifact, request log와 업데이트는 저장된 연결 인증이 필요합니다. pairing 완료 여부 때문에 이미 저장된 worker secret을 무효화하지 않습니다.

녹화 시작·상태·목록·미리보기·checkpoint·중지·저장·삭제는 pairing 없이 사용할 수 있습니다. `GET /recordings/{id}/package`만 녹화 증거를 Linux로 반출하므로 저장된 연결 인증을 유지합니다.
POST 요청은 모두 `Content-Type: application/json`이어야 합니다.

## Windows Console

기본 화면은 다음 네 영역만 표시합니다.

1. Bridge Status
2. Program Manager
3. Recording
4. Latest Local Result

원시 Health와 request log는 접힌 Diagnostics에서 요청할 때만 로드합니다. UTM proof, Skill compile/deploy, Analysis handoff, LLM/model, closed-loop 제어는 Windows Console에 표시하지 않습니다.

## Program 계약

프로그램은 bounded action, target window, timeout, locator/checkpoint를 선언합니다.

- builtin `program1`은 삭제 불가 데모
- local draft는 Windows 로컬 시험만 가능
- deployed program은 Linux가 검증한 읽기 전용 캐시
- retired program은 신규 실행 금지

Windows는 program 의미를 재해석하지 않고 action allowlist와 제한만 검증합니다.

## Recording 계약

Recording은 keyboard/mouse event와 monotonic timestamp를 기록하고 전체 화면을 녹화 시작부터 종료까지 고정 2 FPS로 디스크에 즉시 저장합니다. periodic JPEG와 event/boundary PNG는 append-only `timeline.jsonl`에서 `pre_frame_id`, `event_frame_id`, `post_frame_id`로 연결됩니다. RAM에는 행동 직전 판정을 위한 작은 최근 프레임 캐시만 남습니다. 사용자 Stop은 최상위 오버레이 하나로 제공하며 `RecordingManager.stop()`이 listener와 overlay를 닫은 뒤 깨끗한 최종 상태 frame을 저장하고 frame memory를 해제합니다. Bounded Evidence는 활성 중 별도 Stop을 노출하지 않고 `/recordings/status`로 종료 상태를 동기화합니다. Preview는 cursor/limit 페이지에 포함된 browser-ready frame만 반환하고 Windows 절대경로는 반환하지 않습니다.

`mask_regions`는 `{x, y, width, height}` 목록으로 최대 32개까지 받을 수 있습니다. 마스크는 frame buffer, event/exception evidence, visual locator 원본, checkpoint에 동일하게 적용됩니다. 비밀번호, 개인정보, 외부 시스템 화면처럼 저장하면 안 되는 영역은 녹화 시작 계약에서 선언해야 하며, 마스크 적용 실패는 무마하지 않고 녹화 오류로 반환합니다.

Linux 전송은 `GET /recordings/{id}/package`를 사용합니다. 이 경로는 localhost에서도
내부키 인증이 필요하며, 파일별 relative path, size, SHA-256을
반환합니다. Linux client는 `artifacts/equipment/recording_imports/{recording_id}`에
검증 저장하고 Windows 절대경로를 Linux artifact 경로로 치환합니다.

녹화 분석과 Skill 생성은 Linux에서 수행합니다. Linux annotator는 16개 source frame을 4x4 스토리보드로 구성하고 모든 청크를 선택된 공용 multimodal backend로 순차 분석한 뒤, session overview와 청크 분석을 최종 합성합니다. 각 청크 응답은 모든 source frame ID를 순서대로 반환해야 하며 누락·재정렬은 실패합니다. 완료된 청크 JSON은 안전 중단 후에도 보존됩니다. LLM은 `초기 상태 -> 행동 -> 상태 변화 -> 완료/실패 증거`를 해석하고 결과를 `workflow_summary`와 `step_transitions`로 저장합니다. 정상 실행은 이 해석을 반복 호출하지 않고 컴파일된 deterministic program만 사용합니다.

Lab Equipment Workspace는 현재 선택된 Worker에 대해 `GET /api/equipment/workers/{bridge_id}/recordings`를 호출합니다. 이 API는 live Worker 조회만 허용하고 simulator나 다른 Worker로 fallback하지 않습니다. 사용자가 목록에서 Recording을 선택한 뒤에만 기존 package 검증·가져오기 경로를 실행합니다.

## 주요 API

| API | 인증/범위 |
|---|---|
| `GET /health` | local pre-pair 가능, remote는 내부키 |
| `GET /pairing/status` | local setup |
| `POST /pairing/new-code` | local setup |
| `POST /pairing/complete` | 일회성 code exchange |
| `GET /programs` | local setup/paired remote |
| `POST /programs/validate` | local setup |
| `POST /programs/register` | local setup 또는 paired deploy |
| `DELETE /programs/{id}` | 삭제 가능한 local draft |
| `POST /execute` | paired, bounded physical-possible action |
| `POST /screenshot` | paired evidence capture |
| `POST /locators/capture` | paired locator capture |
| `/recordings/...` | pairing-optional recording management |
| `GET /recordings/{id}/package` | paired recording evidence transfer |
| `GET /artifacts`, `/request-log` | paired evidence/audit |
| `GET /update/status` | paired Worker version/update state |
| `POST /update/stage` | paired, bounded release staging |
| `POST /update/apply` | paired, recording-idle process replacement |
| `POST /update/rollback` | paired, recording-idle latest backup restore |

## Linux Client

`WindowsPyAutoGUIBridge`는 URL, 내부키, timeout, candidate alias를 connection memory에서 읽습니다. Scan은 코드 없이 공개 `/discovery`의 최소 메타데이터로 candidate를 식별합니다. `/discovery`는 실제 검색 시에만 호출하며 주기적 supervisor 감시는 감사 로그에 남지 않는 `text/plain` `/ping`을 5초 간격으로 사용합니다. 사용자는 검색된 Candidate 카드에 4자리 코드를 입력하고 Pair & Save로 내부키를 교환합니다. `/health`, 실행, 파일 전송, 업데이트 경로는 이 공개 검색 계약에 포함되지 않습니다. 실행 payload에 `bridge_id`가 있으면 정확히 일치하는 saved candidate를 사용하며, 찾지 못한 경우 현재 선택 worker로 대체하지 않고 차단합니다. 이후 Select/Health/Programs/Test/Run과 recording import/deploy/delete가 같은 worker identity를 사용합니다.

Local Bridge와 Windows Bridge는 별도 provider 선택이며 자동 fallback 관계가 아닙니다.

### Saved Worker 업데이트

Saved Worker 카드는 candidate alias를 URL path와 bridge payload에 동시에 전달합니다. 따라서 현재 선택 Worker를 변경하지 않고 해당 카드의 Worker만 확인·업데이트·rollback합니다. 등록되지 않은 alias는 현재 선택 Worker로 fallback하지 않고 차단합니다.

Linux는 `Pyautogui_server_for_window/release_manifest.json`을 버전과 업데이트 파일 목록의 단일 source of truth로 사용해 package를 생성합니다. Worker 소스와 시작 명령에는 릴리스 번호를 고정하지 않습니다. Windows는 다음 교집합에 포함되는 파일만 staging합니다.

- Linux release manifest
- Windows `UPDATE_ALLOWED_PATHS`

각 파일의 size/SHA-256과 전체 package digest가 일치해야 합니다. 설치 시 저장한 `ATR_WINDOWS_BRIDGE_INSTALL_ROOT`를 canonical package root로 사용하므로 package 원본 폴더와 설치 폴더가 이원화되지 않습니다. 일반 시작과 로그온 예약 작업은 `scripts/start_supervisor.ps1`만 호출하고 supervisor가 canonical Worker를 감시합니다. 적용 전 `updates/update_in_progress.json`을 생성해 중복 시작을 막고 현재 파일은 `updates/backups/<backup-id>`에 보존합니다. 별도 self-updater가 기존 server 종료, canonical 경로 atomic replace, dependency 동기화, canonical server 재실행, local `/ping`의 manifest 목표 버전 일치 확인을 수행합니다. `requirements-windows.txt`가 직전 backup과 동일하면 pip를 실행하지 않습니다. 정상 종료 유예가 끝나도 이전 Worker PID가 남으면 해당 Worker 프로세스 트리만 종료한 뒤 교체를 계속합니다. 교체 이후 어느 단계에서든 예외가 나면 backup을 복원하고, updater 복구까지 실패하면 독립 supervisor가 잠금 해제 후 canonical Worker를 다시 실행합니다. 복구 결과는 `updates/status.json`, supervisor 상태는 `supervisor/status.json`에 남깁니다. frozen EXE는 bundled runtime으로 기록합니다.

recording이 활성 상태이면 apply/rollback은 `PYAUTOGUI_UPDATE_RECORDING_ACTIVE`로 차단합니다. 사용자 data root, pairing key, recording, program, locator, artifact는 release manifest에 포함하지 않습니다.

구버전 Worker 또는 canonical 경로가 저장되지 않은 Worker는 첫 1회 새 package의 `INSTALL_WINDOWS_BRIDGE.cmd`로 수동 설치합니다. 이후에는 package 폴더를 다시 옮기지 않고 Saved Worker의 Check Update/Update/Rollback만 사용합니다.

## Linux Lab Equipment Workspace

`/equipment/windows`는 Windows Console의 복제 화면이 아니라 Linux가 소유하는
Lab Equipment Device Bridge 작업면입니다. 기본 화면은 다음 순서로 구성됩니다.

1. `Profile & Worker`: 정확한 Equipment Profile과 saved worker 선택
2. `Connection & Profile`: scan/pair/select와 Local Bridge 개발 대상 관리
3. `Agentic Progress`: Record, Transfer, Annotate, Build Skill, Preflight, Execute,
   Verify, Handoff를 canonical execution snapshot으로 표시
4. `Skill Recording`: Windows recording package를 Linux로 가져와 2 FPS timeline 분석과 Skill draft 생성. 완료/중단된 청크 스토리보드는 페이지 단위로 확인
5. `Skill Management`: 정확한 Skill version을 순차 Workflow Editor로 검토/저장하고 단일 Deploy로 build/check/transfer
6. `Main Progress`: 선택된 Profile과 Skill/program으로 bounded macro 실행
7. `Vision Link`: Profile별 선택적 Middle-Level 검증 요청
8. `Error Recovery`: 정상 실행이 아니라 예외가 발생했을 때만 선택 모델 사용
9. `Evidence & Data Transfer`: screen/data/Vision/request evidence와 Analysis handoff 감사

프론트엔드는 `/api/equipment/runtime/current`와 `/api/equipment/skills`를 읽고,
Profile action은 `/api/equipment/profiles/{profile_id}/preflight|test`로 보냅니다.
Vision 체크박스는 `vision_link_enabled` 요청으로 전달되며, 백엔드는
`requested`, `profile_enabled`, `required`, `effective`를 반환합니다. Profile에서
해당 mode의 Vision을 필수로 선언한 경우 사용자가 체크를 해제해도 필수 gate를
약화시키지 않습니다.

체크 또는 해제 즉시 Profile별 선택값을
`memory/equipment_workspace_settings.json`에 자동 저장합니다. 따라서 페이지를
닫거나 새로고침해도, ATR 서버를 재시작해도 마지막 선택이 복원됩니다. 저장값이
없는 새 Profile만 Profile의 기본값을 사용합니다. 반면 화면 캡처와 물리 장비 안전
확인 체크는 작업별 승인값이므로 의도적으로 영속 저장하지 않습니다.

UTM locator, export, 물리 validation 같은 장비별 상세값은 기본 공통 화면과
분리된 `Selected Profile settings and diagnostics`에 유지합니다. 장비별 설정은
Profile/Skill에 있고 Lab Equipment Agent나 Windows worker에 하드코딩하지 않습니다.

## 증거와 effect boundary

`/execute` 수락은 물리 완료가 아닙니다. worker는 raw step trace, screenshot, locator, file metadata, request identity를 반환합니다. Linux Equipment Runtime이 Profile completion policy로 한 번 판정합니다.

invoke 이후 timeout은 effect unknown입니다. 같은 작업을 반복하기 전에 desktop, request log, 장비, 결과 파일을 확인해야 합니다.

Skill의 결정론적 segment 실행 완료는 `execution_complete`입니다. Profile completion
policy의 증거 검증 전에는 `ready_for_analysis`로 승격하지 않습니다.

### 순차 Skill 편집과 배포

Skill 목록에서 정확한 버전을 선택하고 Workflow Editor 아이콘을 누르면 별도 창이
열립니다. 편집기는 `workflow.json`의 순서와 action field만 수정하며 Windows의
`programs/*.json`을 직접 쓰지 않습니다. 단계 이동, 복제, 삭제, locator PNG 교체,
고정 대기, image/text/file 조건 대기를 지원합니다. 조건 대기는 timeout과 polling
주기를 반드시 가지므로 무한 대기하지 않습니다.

이미지 action에는 `Edit Crop`과 `Replace Locator`가 구분되어 있습니다. `Edit Crop`은
Linux가 보존한 hash-verified pre-action 전체 프레임을 읽어 Target ROI만 수정하고,
Context ROI 및 보조 candidate를 그대로 유지합니다. crop 결과는 PNG longest side
512px 이하로 저장됩니다. `Reset to AI`는 최초 annotation ROI로 되돌립니다.
`Replace Locator`는 사용자가 고른 PNG로 locator를 직접 교체합니다. 어느 방식이든
편집기 `Save` 전에는 Windows worker에 배포되지 않습니다.

`Save`는 optimistic workflow hash를 사용합니다. 다른 창에서 같은 버전이 먼저
바뀌면 로컬 편집을 보존한 채 충돌을 표시합니다. 정상 저장은 이전 compile/validation
산출물을 폐기합니다. `Deploy` 한 번으로 Linux가 compile, validate, package,
register, verify를 순서대로 수행합니다. Deploy는 실행 요청이 아니며 `/execute`를
호출하지 않습니다. GUI에는 Compile/Validate 버튼을 따로 노출하지 않지만 해당 API는
자동화와 CLI 호환을 위해 유지합니다.

## 데이터 위치

```text
<data-root>/
  artifacts/bridge_requests.jsonl
  artifacts/pairing.json
  locators/
  programs/
  recordings/
  utm_exports/
```

`pairing.json`, connection memory, 사용자 프로그램/녹화는 Git에 포함하지 않습니다.

## 안전

- PyAutoGUI failsafe 유지
- 허용 action/hotkey/step/time 제한
- 임의 Python/shell payload 금지
- credential을 program/recording에 포함하지 않음
- Windows에서 자동 provider 전환 금지
- 물리 장비 검증은 Profile별 현장 절차로 별도 수행
