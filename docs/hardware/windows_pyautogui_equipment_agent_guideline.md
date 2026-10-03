# Lab Equipment Agent / Windows Bridge 통합 운영 지침

이 문서는 연결된 Windows worker로 장비 작업을 실행할 때, 무엇을 선택하고
어떤 증거를 확인해야 하는지 설명합니다. 최초 설치와 연결은
[Windows 연결 가이드](windows_pyautogui_bridge_windows_setup.md)를 먼저 따릅니다.
HTTP 성공, 화면 클릭 성공, UTM 물리 시험 완료는 서로 다른 결과입니다.

## 실행 전부터 결과 확인까지

1. Linux `/equipment/windows`에서 사용할 worker를 선택하고 `Health`, `Programs`로
   연결과 등록 프로그램을 확인합니다. 실험에서 사용할 exact Profile과
   program/Skill version을 확인하며, unavailable 상태에서 다른 provider로 임의
   전환하지 않습니다.
2. Equipment Agent Manager의 Flow와 선택된 Skill 순서, 필요한 Vision 슬롯을
   검토합니다. Vision을 요구하는 Profile이라면 최신 실행 식별자에 묶인 증거 또는
   사용 가능한 Vision tool이 필요합니다. 둘 다 없으면 실행 전 차단이 정상입니다.
3. 물리 장비 작업은 해당 Profile의 live 승인과 정지 경로를 확인한 후 기존
   Equipment 실행 경로로 요청합니다. 진행 중인 실험을 수동 Windows 프로그램
   실행으로 보조하려고 하지 않습니다.
4. Live GUI → EQP에서 같은 `EquipmentExecutionRecord`의 진행 상태를 확인하고,
   Backend/Artifacts에서 원시 단계 기록, 화면 증거와 출력 파일을 확인합니다.
   Windows `Latest Local Result`는 worker의 결과이며 Linux의 완료 판정을
   대신하지 않습니다.
5. Profile이 요구한 파일 hash/row probe, identity와 Vision cross-check가
   충족됐는지 확인합니다. Analysis로 넘기기 전에는 Manipulation의 post-test
   clear와 새로운 Vision clearance도 통과해야 합니다.

partial file이나 timeout이면 증거를 보존하고 중단 사유를 검토합니다. timeout은
실행 효과가 불명확한 상태이므로 같은 Skill을 즉시 다시 실행하지 않습니다.
지원 요청에는 run/specimen/request/sequence와 execution ID, 실패 코드, 단계 로그를
포함하되 인증키는 제외합니다. 선택 단계만 실패했고 실행 이벤트가 전혀 없다면
[제한된 Equipment 선택 복구](../gui/equipment_selection_recovery.md)를 확인합니다.

## 구조 원칙

Linux ATR이 판단과 실행 기록을 소유하고 Windows Bridge는 경량 PyAutoGUI worker로 동작합니다.

```text
LabEquipmentAgent (High-Level)
  -> EquipmentRuntimeService (Middle-Level)
  -> Windows/Local Bridge (Low-Level)
```

UTM은 `utm_windows_v1` Profile의 첫 적용 사례입니다. Agent 본체에 장비명, 프로그램명, 창 제목, 저장 경로를 고정하지 않습니다.

## 실행 원칙

1. exact Profile과 program/Skill version을 확정합니다.
2. 하나의 `EquipmentExecutionRecord`를 생성합니다.
3. 선택 provider의 `equipment.pyautogui.run`만 호출합니다.
4. worker의 원시 결과와 증거를 수집합니다.
5. Linux에서 completion policy를 한 번 적용합니다.
6. 완료된 evidence package를 유지하고, Manipulation의 post-test clear와 새 Vision clearance를 통과한 뒤 Analysis에 전달합니다.

`utm.run_protocol`은 tool 부재 시 자동 fallback으로 사용하지 않습니다. native/direct UTM은 별도 Profile로 명시 등록해야 합니다.

## 상태 투영

Agent, Workspace, Live GUI, CUI, Runtime IDE는 동일 execution record를 읽습니다. 상태 목록은 Profile/Skill/provider별로 다를 수 있습니다. 대표 상태 예시를 전역 수명주기로 강제하지 않습니다.

## Program과 Skill

- builtin: Bridge 포함 읽기 전용
- local draft: Windows 개발/테스트
- validated/deployed: Linux 검증 후 배포
- retired: 신규 실행 금지

Skill 원본은 Linux `memory/equipment_skills/`입니다. 정상 Skill block 실행은 결정론적입니다.
Managed Flow에서는 시작 전 bounded LLM selection과 종료 후 result review가 정상 경로에도 존재하며,
block 사이마다 모델을 polling하지 않습니다. 예외 복구도 별도의 제한된 권한과 증거를 따릅니다.

## 녹화 기반 Skill 생성

```text
Windows Record
  -> bounded event/frame package
  -> Linux transfer
  -> selected Local/API LLM annotation
  -> deterministic compile
  -> static/simulator/local validation
  -> approval
  -> version/hash deployment
  -> Windows cache
```

Windows에는 모델과 API key를 두지 않습니다.

## Vision Link

Profile에서 선택적으로 활성화합니다. 기존의 신선한 identity-bound evidence를 사용하거나 Vision Agent tool을 호출합니다. evidence/tool이 모두 없으면 실행 전 차단합니다. Vision은 관측만 제공하며 worker에 직접 명령하지 않습니다.

## 완료 증거

Profile이 요구하는 증거 예:

- request/sequence/run/specimen identity
- target window/checkpoint screenshot
- locator state
- output file와 hash/row probe
- Vision cross-check
- worker raw status/step trace

HTTP success만으로 완료 처리하지 않습니다. partial file과 timeout 결과는 증거로 보존하되 handoff를 허용하지 않습니다.

## Windows Console 범위

Windows 기본 화면은 Bridge Status, Program Manager, Recording, Latest Local Result만 제공합니다. UTM proof, Guardian, Analysis, Skill lifecycle, closed loop, ATR Controller 탐색은 Linux Workspace 기능입니다.

## 최초 연결

4자리 일회성 pairing code를 사용합니다. 성공 후 내부키는 보호 파일에 자동 저장되고 사용자 UI에는 표시하지 않습니다. 장기 token 입력/복사 절차는 사용하지 않습니다.

## 안전 및 복구

- unknown Profile/program: no effect block
- worker unavailable: no automatic provider fallback
- locator/checkpoint failure: compiled recovery only
- invoke timeout: effect unknown, inspect before retry
- LLM: allowlisted selection/reasoning only
- physical equipment: Profile별 live 승인과 stop path 필요

## 검증 기준

- generic profile이 UTM/Vision hidden dependency 없이 실행
- UTM Profile이 required Vision evidence를 검증
- source/install Windows server parity
- 4자리 pairing TTL/attempt/lockout/persistence
- recording frame buffer bounded memory
- canonical runtime projection 일치
- browser refresh가 실행을 중복 생성하지 않음
- 자동 테스트는 물리 장비를 구동하지 않음
