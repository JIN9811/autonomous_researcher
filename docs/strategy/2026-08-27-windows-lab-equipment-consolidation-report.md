# Windows Bridge / Lab Equipment Agent 일원화 보고서

- 작성일: 2026-08-27
- 상태: 구현 및 집중 자동 검증 완료, Windows/UTM 현장 검증 대기
- 범위: Lab Equipment Agent, Windows PyAutoGUI Bridge, UTM 프로파일, Equipment Skill, 관련 GUI

## 1. 결론

현재 구조는 Windows 서버와 Linux ATR이 장비 프로파일, 프로그램, UTM 실행,
Skill, 증거 검증, 완료 판정을 중복으로 관리한다. 이 때문에 기능이 이원화되고
Windows 콘솔이 불필요하게 무거워졌다.

권장 구조는 다음과 같다.

> **Linux ATR은 판단과 상태를 관리하고, Windows Bridge는 실제 Windows GUI를
> 실행하는 가벼운 작업자로 제한한다.**

- `LabEquipmentAgent`가 실험 루프의 Equipment 단계를 계속 소유한다.
- Linux에 장비 실행을 통합 관리하는 단일 런타임 서비스를 둔다.
- Windows Bridge는 PyAutoGUI 실행, 화면 확인, 녹화, 로컬 프로그램 관리만 담당한다.
- UTM 절차, Skill 버전, LLM 복구, 증거 판정, Analysis handoff는 Linux ATR이 담당한다.
- `equipment.pyautogui.run`과 `utm.run_protocol`의 암묵적 이원화를 제거한다.
- Live GUI, Equipment Workspace, CUI, Runtime IDE는 같은 실행 상태를 읽는다.

## 2. 원래 목표

Windows 프로그램의 원래 목적은 별도의 장비 관제 시스템을 만드는 것이 아니다.

1. Windows PC에서 가벼운 Bridge 서버를 실행한다.
2. Linux ATR이 인증된 HTTP 통신으로 Windows GUI 작업을 요청한다.
3. Windows에서는 연결 상태, 프로그램 관리, 입력 녹화 정도만 제공한다.
4. 녹화 결과를 Linux ATR로 가져와 LLM으로 분석하고 Equipment Skill로 만든다.
5. 정상 실행은 결정론적 매크로로 빠르게 수행한다.
6. 예외가 발생한 경우에만 Lab Equipment Agent와 LLM이 제한적으로 복구한다.
7. 실험 완료와 Analysis 전달 여부는 Linux ATR이 판단한다.

Lab Equipment Agent는 UTM 전용 에이전트가 아니다. 저자동화 또는 반자동화된
PC 제어 장비를 범용적으로 수용하는 제어 에이전트이며, UTM은 현재 구현하는 첫
번째 장비 프로파일이다. 장비명, 프로그램명, 창 제목, 저장 절차는 에이전트 본체에
하드코딩하지 않고 Equipment Profile과 Equipment Skill에 저장한다.

## 3. 재구성 전 구조

| 계층 | 현재 역할 |
|---|---|
| Lab Equipment Agent | 프로파일·Skill 선택, 실행 계획, 증거 검증, Analysis 전달 |
| Equipment Profile | UTM 프로파일과 허용 프로그램 정의 |
| Equipment Skill Runtime | 녹화, 컴파일, 검증, 배포, 실행, 복구 상태 관리 |
| Linux Windows Bridge Client | 연결 대상, 장기 토큰, 프로그램 실행, 화면·파일 회수 |
| Local Bridge | 같은 Bridge 서버를 Ubuntu에서 실행하여 매크로 개발 |
| Windows Bridge Server | PyAutoGUI, UTM, 녹화, 프로그램, 증거, Skill 프록시, GUI |
| ATR Equipment Workspace | 연결, UTM, Skill, 증거, 로컬 Bridge, 실행 관리 |
| Windows Console | 연결, UTM, 증거, Skill, 프로그램, 녹화, 진단 관리 |
| Direct UTM Tool | 테스트 CSV 생성 및 직접 UTM 백엔드 경로 |

핵심 문제는 Windows Console과 ATR Equipment Workspace가 비슷한 기능을 동시에
소유한다는 점이다.

## 4. 재구성 전 문제점

### 4.1 실행 경로 이원화

현재 Equipment Agent는 상황에 따라 다음 두 경로를 사용할 수 있다.

- `equipment.pyautogui.run`
- `utm.run_protocol`

PyAutoGUI Tool이 없다는 이유만으로 direct UTM 경로로 전환될 수 있어, 사용자가
선택하지 않은 실행 경로가 사용될 가능성이 있다. 테스트 데이터, 증거 형식,
완료 판정도 경로마다 달라질 수 있다.

### 4.2 UTM 로직 중복

UTM 관련 처리가 다음 위치에 분산돼 있다.

- Lab Equipment Agent
- 장비 설정 파일
- Linux Bridge Client
- Windows Bridge Server
- ATR Equipment Workspace
- Windows Console
- direct UTM Tool
- 증거 및 완료 판정 API

하나의 규칙을 변경해도 다른 경로에는 이전 규칙이 남을 수 있다.

### 4.3 프로그램 저장 위치 분산

프로그램 정의가 다음 위치에 존재한다.

- `configs/devices.yaml`
- `memory/equipment_skills/`
- `memory/local_pyautogui_programs/`
- Windows `C:\ATR\programs`

어떤 파일이 원본이고 어떤 파일이 배포 복사본인지 구분이 명확하지 않다.

### 4.4 Windows 서버 과대화

Windows 서버 한 파일이 약 9천 줄이며 다음 기능을 함께 처리한다.

- HTTP 서버와 인증
- PyAutoGUI 실행
- 프로그램 관리
- 입력 녹화
- 이미지 로케이터
- UTM 절차
- 증거와 완료 판정
- ATR Controller 탐색
- Skill 프록시
- Windows Web GUI 전체

Windows PC에는 필요하지 않은 판단 기능까지 포함돼 있어 유지보수와 배포가
어려워졌다.

### 4.5 완료 상태 중복 계산

Windows 실행 결과, Linux 아티팩트 회수, Agent 보고서, 증거 API, completion
audit, Live GUI가 각각 완료 여부를 해석한다. 동일 실행이 화면마다 다른 상태로
보일 가능성이 있다.

## 5. 목표 구조

```text
LangGraph 실험 루프
  -> Lab Equipment Agent
  -> Linux Equipment Runtime Service
       1. 프로파일·Skill·프로그램 확정
       2. 모드·Vision·Guardian·장비 상태 확인
       3. 정확한 프로그램을 Worker에 배포 또는 조회
       4. 선택된 Worker에 실행 요청
       5. 화면·파일·장비 상태·요청 로그 수집
       6. 완료 조건을 한 번만 판정
       7. 하나의 실행 기록 저장
  -> Analysis Agent 또는 명시적인 차단/검토 상태

선택된 Worker
  -> Local Ubuntu Bridge 또는 Windows Bridge
  -> 결정론적 PyAutoGUI 실행
  -> 실행 결과와 원시 증거 반환
```

## 6. 계층별 책임

### 6.1 High-Level Control: Lab Equipment Agent

담당:

- Equipment 단계 진입과 종료
- 실험 ID, 시편 ID, 프로파일, Skill 버전 확정
- LLM을 사용한 제한적 계획과 예외 복구
- 재시도, 정지, 사용자 검토, Analysis 전달 결정
- 녹화 패키지를 해석할 Local/API LLM 선택
- 자동 어노테이션 결과 검토와 Equipment Skill 생성
- 선언된 예외에서 원인 추론과 허용된 복구 전략 선택

담당하지 않음:

- Windows 주소와 토큰 처리
- PyAutoGUI 세부 동작
- Windows 프로그램 파일 관리
- 독립적인 CSV 파싱 경로
- 화면마다 별도의 완료 판정 생성

### 6.2 Middle-Level Control: Equipment Runtime Service

Linux에 장비 실행의 단일 진입점을 둔다.

주요 책임:

- 장비 프로파일 조회
- Skill과 프로그램 버전 조회
- Worker 선택
- Test/Live 실행 계약 생성
- 실행, 관측, 정지, 복구
- 증거 수집
- 완료 판정
- Analysis handoff 생성
- 실행 상태 저장
- 녹화 패키지 수신, Skill 생성 작업, 검증, 버전 및 배포 관리
- Windows Worker와 Linux ATR 사이 프로그램·Skill·결과 파일 자동 전송
- 선택적인 Vision Agent Bridge 요청과 결과 수신

Agent, Equipment Workspace, CUI, Live GUI, Runtime IDE는 모두 이 서비스의 상태를
사용한다.

### 6.3 Low-Level Control: Windows Bridge

담당:

- 인증된 HTTP 요청 처리
- Windows 데스크톱과 PyAutoGUI 상태 확인
- 허용된 프로그램 실행
- 실행 중 정지와 입력 해제
- 화면 캡처와 이미지 로케이터
- 입력 녹화와 로컬 시각 증거 생성
- 검증된 Skill의 이미지 기반 탐색, 대기, 입력, 저장 매크로 실행
- 로컬 프로그램 캐시
- 원시 아티팩트와 요청 로그 반환

담당하지 않음:

- LLM 실행과 모델 선택
- Equipment Agent 판단
- Skill 컴파일·검증·배포 상태 관리
- UTM 실험 절차 결정
- Guardian 판단
- Analysis handoff
- 실험 루프 전환
- ATR Controller 자동 검색

## 7. Windows Console 재구성

Windows Console 기본 화면에는 다음 네 영역만 남긴다.

### 7.1 Bridge Status

- 서버 실행 상태
- Linux ATR의 최근 접속 상태
- Windows 데스크톱 제어 가능 여부
- PyAutoGUI 상태
- 서버 버전, 포트, 데이터 경로
- 최초 연결용 4자리 숫자 페어링 코드
- Health, Pair, Refresh 버튼

기존의 긴 토큰 입력·복사·저장 UI는 제거한다. Windows Console에는 최초 연결에
사용하는 4자리 숫자 코드만 일시적으로 표시하고, 페어링이 끝나면 코드 입력창도
숨긴다. 평상시에는 `연결됨`, `미연결`, `재연결 필요` 상태만 표시한다.

### 7.2 4자리 페어링 규칙

4자리 숫자는 상시 HTTP 인증 토큰이 아니라 일회성 페어링 코드로 사용한다.

- 허용 형식: `0000`부터 `9999`까지의 숫자 4자리
- Windows Bridge 시작 또는 `새 코드 생성` 요청 시 무작위 생성
- 유효 시간: 5분
- 성공 여부와 관계없이 최대 5회 입력 후 폐기
- 페어링 성공 즉시 코드 폐기
- 동일 코드 재사용 금지
- 코드와 인증키를 URL, 로그, request audit, 브라우저 저장소에 기록하지 않음
- 실패 횟수 초과 시 30초 동안 새 페어링 요청 제한

페어링 성공 후 Linux ATR과 Windows Bridge는 내부용 장기 인증키를 자동 생성해
각 시스템의 보호된 설정 파일에 저장한다. 이후 모든 Bridge 요청은 이 내부
인증키로 인증하며 사용자는 값을 직접 입력하거나 확인하지 않는다.

Windows Bridge는 페어링되지 않은 상태에서 다음 기능만 허용한다.

- 로컬 Console 표시
- 로컬 Health 확인
- 새 4자리 코드 생성
- 로컬 Program Manager와 Recording 사용

원격 프로그램 실행, 화면 캡처, 로케이터, 아티팩트 조회, 요청 로그 조회는 페어링
완료 후에만 허용한다. 페어링 해제 시 기존 내부 인증키를 양쪽에서 폐기한다.

### 7.3 Program Manager

- 기본 프로그램, 로컬 초안, ATR 배포 프로그램 목록
- Add, Browse JSON, Template, Validate, Save, Test, Delete
- `program1`은 삭제할 수 없는 기본 데모로 유지
- ATR에서 배포한 프로그램은 Windows에서 수정 불가
- 로컬 프로그램은 ATR 승인 전까지 실험 루프에서 사용 불가

### 7.4 Recording

- 5초 카운트다운 후 녹화 시작
- 녹화 중 최상단 배너와 경과 시간 표시
- Start/Stop
- 대상 프로그램과 창 이름
- 이미지 추적 사용 여부
- 녹화 목록, 미리보기, 내보내기, 삭제
- 입력 이벤트와 동일한 monotonic timestamp를 사용하는 시계열 화면 순환 버퍼

Windows에서는 녹화까지만 한다. 녹화 분석, 자동 어노테이션, Skill 생성,
LLM 판단은 Linux ATR이 수행한다.

시계열 화면은 연속 영상을 무조건 영구 저장하는 기능이 아니다. 녹화 중에는
저속 화면 프레임을 메모리 순환 버퍼에 유지하고, 정상 구간은 이벤트와 연결된
핵심 프레임만 저장한다. 오류가 발생하면 오류 전후 구간을 고정하여 Skill 생성과
복구 판단의 시각 증거로 사용한다.

### 7.5 Latest Local Result

- 최근 Health, 프로그램 검증, 테스트, 녹화 결과
- 간단한 오류 코드와 로컬 조치 안내
- 필요할 때만 펼치는 원시 JSON과 요청 로그

## 8. Windows Console에서 제거할 기능

다음 기능은 ATR Equipment Workspace로 이동하거나 기존 ATR 기능만 사용한다.

- UTM Live/Simulation/Abort 제어 화면
- UTM 프로파일 편집
- UTM 증거와 proof gate
- Analysis handoff 판정
- Vision proof 작성
- Skill 생성·컴파일·검증·배포·활성화·삭제
- ATR Controller 탐색과 주소 선택
- 모델과 LLM 선택
- 네트워크 장비 검색
- Linux 아티팩트 검증
- completion audit
- 실험 단계와 closed-loop 상태
- 중복된 readiness 및 field runbook

필수 저수준 진단만 하나의 접힌 `Diagnostics` 영역에 남긴다. 같은 기능을 기본
화면과 Diagnostics에 중복 배치하지 않는다.

## 9. 실행 경로 일원화

실험 루프의 유일한 경로는 다음과 같이 한다.

```text
LabEquipmentAgent.run()
  -> EquipmentRuntimeService.execute()
  -> 선택된 Worker Client
  -> Windows 또는 Local Bridge /execute
  -> 증거 회수
  -> EquipmentRuntimeService.verify()
  -> Analysis handoff
```

`utm.run_protocol`은 Tool 부재 시 자동으로 선택되는 fallback에서 제거한다.

향후 native UTM 통신이 필요하면 다음처럼 명시적 프로파일로 등록한다.

```text
utm_windows_v1 -> windows_pyautogui provider
utm_native_v1  -> native_utm provider
utm_virtual_v1 -> simulator provider
```

사용자가 선택한 프로파일 외의 provider로 자동 전환하지 않는다.

## 10. 프로그램과 Skill의 단일 원본

프로그램을 네 종류로 구분한다.

| 종류 | 의미 |
|---|---|
| `builtin` | Bridge에 포함된 읽기 전용 기본 프로그램 |
| `local_draft` | 특정 PC에서 개발·테스트 중인 로컬 프로그램 |
| `deployed` | ATR에서 검증 후 배포한 수정 불가능한 프로그램 |
| `retired` | 신규 실행은 금지하지만 감사용으로 보존한 프로그램 |

승격 순서는 다음과 같다.

```text
Windows 녹화
  -> ATR로 녹화 데이터 가져오기
  -> LLM 어노테이션과 컴파일
  -> 사용자 검증
  -> 버전 Skill 생성
  -> 배포 hash 생성
  -> Windows Worker 캐시에 배포
  -> 실험 루프에서 실행
```

Linux `memory/equipment_skills/`가 Skill의 원본이다. Windows 프로그램 폴더는 로컬
초안과 배포 캐시만 저장한다.

### 10.1 Agentic Progress: 전처리 및 Skill 생성

Equipment Skill 생성은 다음 단일 흐름을 사용한다.

```text
Windows Bridge에서 Record Skill 요청
  -> 5초 카운트다운
  -> 입력 이벤트 + 시계열 화면 순환 버퍼 기록
  -> 녹화 종료
  -> 녹화 패키지를 Linux ATR로 자동 전송
  -> 자동 어노테이션
  -> 선택된 Local/API LLM으로 Skill 초안 생성
  -> 정적 검증 + simulator/local bridge 테스트
  -> 사용자 또는 정책 승인
  -> 이름·버전·장비 Profile과 함께 Skill 등록
  -> Windows Worker로 검증된 Skill 자동 재배포
  -> Live GUI Agentic Progress와 아티팩트 갱신
```

Live GUI의 Agentic Progress는 최소한 다음 상태를 표현한다.

- `RECORDING`
- `TRANSFERRING`
- `ANNOTATING`
- `BUILDING_SKILL`
- `VALIDATING`
- `AWAITING_APPROVAL`
- `DEPLOYING`
- `READY`
- `FAILED`

LLM은 Windows PC에서 상시 실행하지 않는다. Linux ATR에서 현재 선택된 Local LLM
또는 API 모델을 사용하며, 생성된 결과는 검증된 Skill 패키지로만 Windows에 다시
전송한다.

### 10.2 Skill 패키지 계약

Skill은 단일 JSON 매크로가 아니라 버전이 고정된 실행 패키지다.

| 구성 | 역할 |
|---|---|
| `manifest.json` | Skill ID, 이름, 버전, 장비 Profile, 생성 모델, 해시 |
| `skill.json` | 결정론적 실행 단계, 대기 조건, timeout, 결과 계약 |
| `events.jsonl` | 원본 입력 이벤트와 monotonic timestamp |
| `locators/` | 이미지 기반 탐색에 사용하는 기준 이미지와 메타데이터 |
| `checkpoints/` | 단계별 기대 화면과 성공·실패 판정 기준 |
| `recovery.json` | 허용된 재시도, 대체 locator, 제한된 복구 규칙 |
| `evidence/` | 검증 결과, 핵심 프레임, 오류 전후 보존 프레임 |

Skill 이름은 장비와 작업을 식별할 수 있어야 하지만 UTM 고정 문자열을 요구하지
않는다. UTM 시험 시작, 완료 대기, 원점 복귀, 파일 저장은 각각 일반적인 Skill
단계의 첫 적용 사례로 문서화한다.

### 10.3 Main Progress: 경량 매크로 실행

정상 실험 루프에서는 LLM 없이 검증된 Skill을 실행한다.

```text
Skill/Profile 확정
  -> Preflight
  -> 시작 상태 또는 이미지 확인
  -> 결정론적 PyAutoGUI 단계 실행
  -> 종료 상태 대기
  -> 선택적인 장비 자체 원점 복귀 확인
  -> 파일 이름과 저장 경로 적용
  -> 결과 파일 Linux ATR로 자동 전송
  -> 증거 검증
  -> Analysis handoff
```

`start`, `wait until end`, `home`, `save` 같은 이름은 공통 동작의 예시다. 실제
창 제목, 버튼 이미지, 파일명 규칙, 저장 경로는 Equipment Profile과 Skill이
제공한다. Windows Bridge는 해당 정의를 실행할 뿐 장비 의미를 판단하지 않는다.

### 10.4 선택적 Vision Link

Equipment Profile은 `vision_link.enabled`를 선택적으로 선언할 수 있다.

- 비활성화: 화면 locator, 장비 상태, 파일 증거만으로 실행한다.
- 활성화: Equipment Runtime Service가 Vision Agent Bridge에 관측을 요청한다.
- Vision Agent는 이미지·상태 판정 결과를 반환하고 장비 제어 명령은 보내지 않는다.
- Lab Equipment Agent가 Vision 결과와 실행 상태를 결합해 다음 단계 또는 복구를
  결정한다.
- 이 통신은 Middle-Level API 계약으로 구현하며 Windows 실행기와 직접 결합하지
  않는다.

### 10.5 시계열 녹화 버퍼 보존 정책

시계열 버퍼는 Skill 기록 견고성과 예외 복구를 위한 증거 계층이다.

- 권장 캡처율: 기본 2~5 FPS, Profile에서 제한적으로 조정
- 권장 보존 창: 최근 20~30초
- 저장 기준 시각: monotonic clock
- 입력 이벤트, checkpoint, locator 판정과 동일한 timeline ID 사용
- mouse move를 제외한 실행 이벤트는 발생 시점의 nearest frame을 즉시 event keyframe으로
  고정하여 20~30초 순환 버퍼에서 해당 시점이 밀려나도 증거가 사라지지 않음
- 오래된 프레임은 메모리 순환 버퍼에서 자동 폐기
- 정상 실행은 이벤트 전후 핵심 프레임과 명시적 checkpoint만 영구 저장
- 오류 발생 시 오류 이전·발생·복구 이후 구간만 고정하여 보존
- 전체 녹화 영상을 기본 아티팩트로 영구 저장하지 않음
- 민감 영역은 Profile의 마스킹 규칙을 캡처 전에 적용
- 녹화 종료 또는 실행 종료 시 보존 대상이 아닌 프레임 메모리를 즉시 해제

이 정책은 연속 MP4를 실행 원본으로 사용하는 방식보다 가볍다. Skill 실행 원본은
입력 이벤트, locator, checkpoint이며, 시계열 프레임은 어노테이션과 예외 복구의
보조 증거로만 사용한다.

### 10.6 Skill 관리

Skill 관리의 원본은 Linux ATR이다.

- 이름, 설명, 장비 Profile, 버전, 상태, 해시 관리
- `draft`, `validated`, `deployed`, `retired` lifecycle 관리
- 장비별 허용 Skill과 배포 Worker 관리
- 녹화 원본과 생성 Skill의 provenance 연결
- Windows 녹화 산출물은 인증된 package API로 전송하고 Linux가 파일별 크기와
  SHA-256을 검증한 뒤 Linux-owned artifact 경로로 다시 기록
- 수정 Skill은 새 버전으로 등록하고 기존 배포본을 덮어쓰지 않음
- Live GUI, Equipment Workspace, CUI가 동일한 catalog와 배포 상태 사용

## 11. 상태 저장 기준

### Linux ATR이 원본인 상태

- 장비 프로파일
- Worker 선택
- Skill 정의, 버전, 검증 상태, 배포 hash
- 실험 ID, run ID, 시편 ID
- 실행 lifecycle
- 증거 목록과 완료 판정
- Analysis handoff
- LLM 복구 판단

### Windows가 원본인 상태

- 현재 데스크톱 실행 상태
- 마우스와 키보드 입력 해제 상태
- Windows 화면과 PyAutoGUI 상태
- 녹화 원본
- 로컬 이미지 로케이터
- 원시 스크린샷과 요청 로그
- 배포 프로그램 캐시

### 브라우저

브라우저 상태는 원본으로 사용하지 않는다. 새로고침하면 Linux 또는 Windows
서버의 현재 상태를 다시 읽는다.

## 12. 통합 실행 기록과 상태 투영

모든 화면은 동일한 `EquipmentExecutionRecord`를 원본으로 사용한다. 아래 값은
장비 실행에서 자주 나타나는 **대표 상태 예시**이며, 모든 에이전트와 Skill에
동일한 순서로 적용하는 전역 수명주기가 아니다.

```text
RESOLVING
  -> PREFLIGHT
  -> READY
  -> RUNNING
  -> OBSERVING
  -> VERIFYING
  -> COMPLETED | BLOCKED | EFFECT_UNKNOWN | STOPPED
```

실제 상태 집합과 전이는 선택된 Equipment Profile, Skill, provider의 실행 계약이
정한다. 예를 들어 녹화 전처리 상태, Windows 저수준 실행 상태, Vision 검증 상태는
서로 다른 상태 집합을 가질 수 있다. GUI, CUI, Live GUI, Runtime IDE는 상태를 새로
계산하지 않고 같은 실행 기록의 현재 상태와 agentic progress를 각 화면 형식으로만
투영한다.

- `COMPLETED`: 필수 증거까지 확인된 정상 완료
- `BLOCKED`: 실행 전에 조건이 충족되지 않음
- `EFFECT_UNKNOWN`: 요청 후 통신이 끊겨 실제 장비 효과를 알 수 없음
- `STOPPED`: 정지 요청과 정지 확인이 완료됨

필수 증거가 없는 상태에서는 Analysis로 넘기지 않는다.
Skill segment가 모두 실행된 상태는 `execution_complete`이며 그 자체로
`ready_for_analysis`가 아니다. 선택된 Equipment Profile의 completion interpreter가
필수 장비 증거를 검증한 이후에만 Analysis handoff를 생성한다.

`/api/equipment/runtime/current`는 선택적으로 `run_id`, `profile_id`, `execution_id`를
받는다. Live GUI는 현재 run ID를 전달하여 다른 실험의 최신 Equipment 실행을 현재
상태로 오인하지 않는다. Skill segment가 끝나면 canonical runtime은 먼저
`VERIFYING`에 머물고, Profile completion/evidence 검증이 통과한 뒤에만
`COMPLETED`로 전이한다.

## 13. 오류와 복구 원칙

- provider 자동 fallback 금지
- 4자리 코드를 상시 인증키로 사용하지 않음
- 페어링 이후 원격 요청은 자동 생성된 내부 인증키로만 허용
- paired worker는 과거 환경 token을 원격 인증 우회키로 허용하지 않음
- 모든 mutating HTTP 요청은 `Content-Type: application/json`을 요구
- Worker 미연결은 simulator 성공이 아니라 `BLOCKED`
- 실행 요청 후 timeout은 즉시 재실행하지 않고 `EFFECT_UNKNOWN`
- 읽기 작업 또는 동일 execution key의 멱등 요청만 자동 재시도
- 실패 시 Windows가 눌린 마우스·키보드 입력을 반드시 해제
- 정상 경로는 LLM 없이 실행
- 선언된 예외에서만 LLM 복구 요청
- LLM은 허용된 복구 프로그램만 선택
- 복구 요청에는 전체 녹화가 아니라 오류 전후 고정 프레임, 관련 이벤트,
  checkpoint 차이, 장비 상태를 최소 증거 묶음으로 전달
- 예외 pre/post 화면은 rolling retention과 별도로 예외 발생 시점에 즉시 고정
- 녹화 계약의 민감영역 마스크를 frame, locator, checkpoint에 공통 적용
- 복구 성공 후에는 복구 이후 checkpoint를 다시 검증하고 실행 기록에 연결
- Guardian과 사용자 승인 판단은 Linux에서 수행
- 부분 CSV와 스크린샷은 증거로 보존하지만 완료로 처리하지 않음

## 14. 단계별 재구성 순서

### 1단계: 현재 성공 경로 고정

- 현재 프로그램, Skill, API, 아티팩트 계약 기록
- 실제 동작하는 UTM 경로를 회귀 테스트 기준으로 보존
- 각 상태를 누가 생성하는지 테스트로 고정

### 2단계: Linux 단일 런타임 추가

- 기존 코드를 감싸는 `EquipmentRuntimeService` 추가
- 물리 동작은 바꾸지 않고 Agent와 Workspace 호출만 통합

### 3단계: 상태와 완료 판정 통합

- 실행마다 하나의 `EquipmentExecutionRecord` 저장
- Live GUI, CUI, Runtime IDE, 증거 화면이 같은 기록을 사용
- 화면별 독립 완료 계산 제거

### 4단계: 프로그램 원본 구분

- `builtin`, `local_draft`, `deployed`, `retired` 구분
- ATR Skill 배포본은 hash가 고정된 Worker 캐시로 저장
- 기존 사용자 프로그램은 삭제하지 않고 명시적으로 가져오기

### 5단계: Windows 서버 경량화

- ATR Controller 자동 탐색 제거
- Windows Skill 프록시 제거
- Windows UTM/proof/handoff UI 제거
- 네 영역의 가벼운 Windows Console로 교체
- HTTP, 실행기, 녹화, 로케이터, 프로그램, GUI 모듈 분리

### 6단계: 이원화 경로 제거

- Equipment Agent의 implicit direct UTM fallback 제거
- native/direct UTM은 명시적인 provider로만 허용
- 호환성 테스트와 물리 검증 후 구 API 제거

### 7단계: 문서와 배포 패키지 정리

- 현재 명세와 과거 변경 기록 분리
- Windows source ZIP과 실행 패키지 재생성
- 실제 Windows PC에서 설치, 녹화, 프로그램 실행 검증

## 15. 완료 기준

- 실험 루프의 Equipment 실행 진입점이 하나다.
- Agent가 Tool 부재를 이유로 다른 UTM 경로로 전환하지 않는다.
- 실행마다 하나의 ID와 하나의 완료 판정 원본이 존재하되, 모든 모듈에 하나의
  고정 상태 순서를 강제하지 않는다.
- Windows 서버는 LLM, Guardian, Skill lifecycle, Analysis handoff를 소유하지 않는다.
- Windows 기본 화면에는 Bridge Status, Program Manager, Recording, Latest Result만 있다.
- 사용자가 긴 토큰을 입력·복사·저장하는 기능이 없다.
- 최초 연결은 4자리 숫자 코드로 완료되고 이후 인증은 내부적으로 자동 유지된다.
- `program1`, 녹화, 화면 캡처, 로케이터, 프로그램 실행은 유지된다.
- Lab Equipment Agent 본체에 UTM 프로그램명·창 제목·저장 경로가 하드코딩되지
  않고 UTM은 Equipment Profile/Skill의 첫 적용 사례로만 존재한다.
- 녹화 결과가 Linux로 자동 전송되고 어노테이션, LLM Skill 생성, 검증, 버전 등록,
  Windows 재배포까지 하나의 Agentic Progress로 추적된다.
- 배포 프로그램 hash는 Windows가 실제 저장한 정규화 프로그램 본문을 기준으로
  계산하고 Linux가 동일 hash를 검증한다.
- 정상 실행은 LLM 없이 결정론적으로 수행되고 선언된 예외에서만 LLM을 호출한다.
- 입력 이벤트와 동기화된 시계열 순환 버퍼가 동작하며 정상 핵심 프레임과 오류
  전후 구간만 영구 보존된다.
- 결과 데이터 파일이 실행 ID와 연결되어 Linux ATR로 자동 전송된다.
- 선택한 Profile에서만 Vision Link가 활성화되고 제어권은 Lab Equipment Agent에
  유지된다.
- Local Bridge와 Windows Bridge가 같은 Equipment Runtime 계약을 사용한다.
- GUI, CUI, Live GUI, Runtime IDE의 상태가 일치한다.
- 브라우저 새로고침으로 실행이 초기화되거나 중복되지 않는다.
- Test와 Live 모두 같은 실행 구조를 사용하고 provider만 명시적으로 다르다.
- 기존 기능 회귀 테스트 후 실제 Windows 및 UTM 물리 검증을 통과한다.

## 16. 구현 검증 결과

2026-08-27 현재 다음 비물리 검증을 수행했다.

- Windows source 서버와 설치 서버 파일 동등성: `cmp` 통과
- 변경 Python 파일 구문 검사: `py_compile` 통과
- Equipment Runtime, Agent, Profile, Skill, Bridge, API, Live GUI, Windows 패키징
  집중 회귀 테스트: `323 passed`, 실패 0
- 녹화 패키지 회수 검증: 인증된 package API, 파일별 크기/SHA-256 확인,
  변조 아티팩트 차단 및 Linux artifact 경로 재작성 통과
- Firefox Selenium 1920×1080 감사: 통과
  - 4자리 임시 페어링 코드 표시
  - `program1` 읽기 전용 유지
  - JSON Browse, Validate, Save, Delete 실제 브라우저 조작
  - Recording 기본값과 접힌 Diagnostics 확인
  - 가로 오버플로와 가려진 라벨 없음
- 별도 임시 서버 HTTP 페어링 E2E: 통과
  - 발급 코드는 숫자 4자리
  - 성공 후 코드는 즉시 숨김
  - 내부 인증키 저장 파일 권한은 `0600`
  - request audit에 페어링 코드와 내부 인증키가 남지 않음
- 활성 Windows 배포 문서와 스크립트에서 이전 장기 토큰·Controller 프록시 문구가
  남지 않았음을 정적 검사

전체 저장소 테스트는 기존 ROS/카메라 통합 항목
`test_controller_completes_test_run`이 실제 `/image_utm` 및 YOLO 프로세스를 시작한 뒤
장시간 반환하지 않아 완료하지 않았다. 중단 전 확인된 fault-injection과 BO GUI 실패는
이번 Equipment 집중 회귀 범위 밖의 기존 실패 항목이다. 따라서 이번 검증은 Windows
실장비 또는 UTM 물리 동작 성공을 의미하지 않는다. 실제 Windows에서 설치, 4자리
페어링, 녹화, 프로그램 실행, 파일 회수 및 UTM 동작은 현장 승인 절차로 별도 검증한다.

## 17. 적용 항목

1. Linux ATR 중심의 단일 제어 구조 적용
2. Windows에서 Skill/UTM/proof 판단 기능 제거
3. Windows Console을 네 영역으로 축소
4. Windows 녹화 결과를 Linux가 가져가는 방식 적용
5. `utm.run_protocol` 암묵적 fallback 제거
6. Windows 로컬 프로그램은 초안으로 두고 ATR 승인 후 실험 루프에 사용
7. 4자리 숫자는 일회성 페어링에만 사용하고 상시 인증은 내부 인증키로 유지
8. Lab Equipment Agent를 범용 장비 제어 에이전트로 유지하고 UTM은 Profile/Skill로 구현
9. 녹화 패키지의 Linux 자동 전송, LLM Skill 생성, 검증, Windows 재배포 적용
10. 시계열 화면은 순환 버퍼로 수집하고 핵심 프레임과 오류 전후 구간만 영구 보존
11. Vision Link는 Profile별 선택 사항으로 두고 Middle-Level API로 연동

이 문서는 재구성 방향과 현재 구현 계약을 함께 기록한다. 자동 검증은 물리 장비
실행을 승인하지 않으며 실제 장비 검증은 별도 현장 절차를 따른다.
