# Live GUI Chat Message Separation Plan

## Purpose

Live GUI의 채팅 영역을 실제 사용자-에이전트 대화 중심으로 정리하고, 시스템 이벤트와 백엔드 실행 로그는 Report, Backend, Timeline, IO 영역으로 분리한다.

이 문서는 코드 구현 전 계획 문서다. 기존 LLM/MCP 프로토콜, transcript 저장 구조, agent loop 실행 순서는 변경하지 않는다.

## Current System Baseline

현재 Live GUI는 다음 구조를 가진다.

- Chat: `web/templates/planning.html`의 `planning-chat-log`와 입력 영역
- Report: agent별 실행 결과, 카드, artifact 표시 영역
- Backend: raw event, tool trace, debug payload 표시 영역
- Graph: runtime map과 workflow 진행 상태 표시 영역
- Artifacts: STL, image, FEM contour, BO plot 등 산출물 표시 영역
- Timeline/EVT: cycle, handoff, workflow transition 표시 영역
- IO: 장비 bridge, printer, robot, equipment, file transfer 상태 표시 영역

현재 backend 쪽 핵심 흐름은 다음과 같다.

- `app/controller.py`가 planning transcript를 관리한다.
- `_planning_messages`가 세션 메시지를 유지한다.
- `_record_planning_message()`가 transcript JSONL 저장을 담당한다.
- `_compact_planning_message_for_storage()`가 저장용 메시지 압축을 담당한다.
- `_compact_planning_message_for_display()`가 frontend 전달용 메시지 압축을 담당한다.
- `_append_planning_message()`가 메시지 추가와 broadcast를 담당한다.

현재 frontend 쪽 핵심 흐름은 다음과 같다.

- `web/static/planning.js`의 `renderPlanningMessages()`가 채팅 메시지 렌더링을 담당한다.
- `roleLabel()`이 `orchestrator`, `design_ai`, `printer_ai`, `vision_ai`, `manipulation_ai`, `equipment_ai`, `analysis_ai`, `knowledge_ai`, `bo_ai`, `guardian`, `system` 등을 사용자 표시명으로 변환한다.
- `renderSpecimenRuntimeCard()`, `renderEquipmentRuntimeCard()`, `renderFemContourCard()`, `renderBoResultCard()`, `renderArtifactCard()`가 agent 산출물 카드 표시를 담당한다.
- Backend, Timeline, Report renderer가 이미 존재하므로 새 페이지를 만드는 대신 기존 surface에 라우팅한다.

## Problem

현재 채팅 영역에는 사용자에게 말해야 하는 agent 메시지와 시스템 내부 이벤트가 섞인다.

대표 문제는 다음과 같다.

- `SYSTEM_EVENT: HANDOFF` 같은 내부 이벤트가 채팅 메시지처럼 보인다.
- cycle 시작, cycle 완료, workflow 완료 같은 상태 전이가 대화 흐름을 끊는다.
- agent별 상세 결과 JSON, backend payload, report payload가 사용자 대화와 섞일 수 있다.
- 5-cycle test loop에서는 메시지 수가 많아져 사용자가 실제 agent 응답을 찾기 어렵다.
- 실제 대화가 아닌 debug trace가 채팅에 노출되면 Live GUI가 상용 LLM 대화창처럼 동작하지 않는다.

핵심 원칙은 다음이다.

채팅은 대화만 보여준다. 시스템은 시스템 영역에 보여준다. 산출물은 report/artifact 영역에 보여준다.

## Target UX

### Chat Surface

Chat에는 다음만 표시한다.

- 사용자 입력
- Orchestrator의 질문, 확인, 실행 안내
- 각 agent가 사용자에게 전달해야 하는 요약 메시지
- Guardian이 사용자 조치나 승인 판단을 요구하는 메시지
- 오류 또는 위험이 사용자 행동을 요구하는 경우의 짧은 안내

Chat에는 다음을 표시하지 않는다.

- `SYSTEM_EVENT:*`
- raw tool call payload
- handoff debug text
- 내부 backend trace
- 긴 JSON dump
- 반복적인 cycle heartbeat
- report에 들어갈 상세 표, contour, BO plot 원본 payload

### Report Surface

Report에는 agent별 결과와 해석을 표시한다.

- Design: 후보 설계, 이전/다음 형상 비교, BO 입력 반영 여부
- Specimen Making: slicer 설정, PrusaLink 단계, 출력 옵션, G-code 적용 요약
- Vision: 인식 결과, 품질 판단, image evidence
- Manipulation: policy rollout, robot bridge, transport status
- Lab Equipment: pyautogui bridge, UTM command, 장비 로그
- Analysis: UTM/CAE/FEM 결과, contour, metric, 실패 원인
- Knowledge: experiment memory update, evidence store update
- BO: acquisition 결과, surrogate 갱신, 다음 후보 제안
- Guardian: gate 결과, 위험 판단, 허용/차단 사유

### Backend Surface

Backend에는 개발자와 운영자가 추적해야 하는 내부 실행 정보를 표시한다.

- raw system event
- tool call request/response summary
- handoff packet
- API failure detail
- bridge protocol detail
- retry trace
- state machine transition
- transcript storage status

### Timeline / EVT Surface

Timeline에는 workflow 진행 흐름만 표시한다.

- workflow started
- cycle started
- agent handoff
- agent completed
- cycle completed
- workflow completed
- blocked, retrying, resumed

Timeline 이벤트는 사람이 빠르게 흐름을 볼 수 있도록 짧게 유지한다.

### IO Surface

IO에는 장비, 파일, bridge 상태를 표시한다.

- printer upload/slice/start status
- PrusaLink state
- robot session and rollout state
- Windows pyautogui bridge connection
- UTM command/result
- file transfer and artifact path

## Message Taxonomy

모든 planning message는 저장 시 audit/replay를 위해 보존하되, 표시 surface를 명확히 분류한다.

### Message Classes

| Class | Purpose | Default Surface |
|---|---|---|
| `operator_input` | 사용자가 직접 입력한 메시지 | Chat |
| `agent_chat` | agent가 사용자에게 말하는 자연어 메시지 | Chat |
| `agent_report` | agent 실행 결과 상세 보고 | Report |
| `system_event` | 내부 시스템 이벤트 | Backend |
| `handoff_event` | agent 간 handoff 상태 | Timeline + Backend |
| `tool_event` | tool call, bridge call, retry, API result | Backend + IO |
| `artifact_event` | STL/image/plot/table/file 산출물 | Report + Artifacts |
| `guardian_event` | Guardian gate 결과 | Chat if user-facing, otherwise Timeline + Report |
| `reasoning_trace` | reasoning 요약 또는 streaming reasoning | Chat collapsed area or Backend |
| `error_event` | 오류, 중단, 복구 안내 | Chat if user action needed, otherwise Backend |

### Proposed Fields

기존 message 구조에 다음 metadata를 추가한다.

```json
{
  "message_id": "msg-...",
  "transcript_index": 42,
  "timestamp": "2026-06-01T...",
  "role": "design_ai",
  "agent_id": "DesignAgent",
  "message_class": "agent_chat",
  "surface": ["chat"],
  "message_type": "summary",
  "event_type": null,
  "cycle_index": 2,
  "total_cycles": 5,
  "severity": "info",
  "content": "다음 후보 형상을 생성했습니다.",
  "summary": "cycle 2 design candidate ready",
  "payload_ref": "runs/.../design_report.json",
  "artifact_refs": ["runs/.../candidate_02.png"],
  "visibility": "user"
}
```

필수 원칙은 다음이다.

- `content`는 사람이 읽는 짧은 문장이다.
- 상세 데이터는 `payload_ref`와 `artifact_refs`로 보낸다.
- `surface`는 frontend가 어느 영역에 표시할지 결정하는 기준이다.
- legacy transcript에는 `surface`가 없을 수 있으므로 frontend/backend 양쪽에서 추론 fallback을 둔다.

## Routing Rules

### Chat Routing

Chat에 표시하는 조건은 다음이다.

- `surface`에 `chat`이 포함된다.
- 또는 legacy message에서 `role`이 `operator`, `orchestrator`, agent role이고 `content`가 `SYSTEM_EVENT:`로 시작하지 않는다.
- 또는 `message_type`이 `approval`, `warning`, `incident`이고 사용자 조치가 필요하다.

Chat에서 제외하는 조건은 다음이다.

- `role == "system"`
- `content`가 `SYSTEM_EVENT:`로 시작한다.
- `message_class`가 `system_event`, `handoff_event`, `tool_event`, `artifact_event`다.
- `visibility == "internal"`이다.
- `content`가 raw JSON dump에 가깝고 report/backend payload로 대체 가능하다.

### Timeline Routing

Timeline에 표시하는 조건은 다음이다.

- `message_class == "handoff_event"`
- `event_type`이 `workflow_started`, `cycle_started`, `agent_started`, `agent_completed`, `cycle_completed`, `workflow_completed`, `blocked`, `retrying`, `resumed` 중 하나다.
- legacy content가 `SYSTEM_EVENT: HANDOFF`, `SYSTEM_EVENT: CYCLE_COMPLETE`, `SYSTEM_EVENT: WORKFLOW_COMPLETE`로 시작한다.

### Backend Routing

Backend에 표시하는 조건은 다음이다.

- `message_class == "system_event"`
- `message_class == "tool_event"`
- `visibility == "internal"`
- raw payload, stack trace, bridge response, retry trace를 포함한다.
- 실패 원인 분석에 필요한 low-level data를 포함한다.

### Report Routing

Report에 표시하는 조건은 다음이다.

- `message_class == "agent_report"`
- `message_class == "artifact_event"`
- agent-specific result payload가 있다.
- figure, table, STL screenshot, FEM contour, BO plot, printer settings, robot rollout log 등이 있다.

### IO Routing

IO에 표시하는 조건은 다음이다.

- `tool_event` 중 장비 또는 파일 입출력과 관련된다.
- printer, PrusaLink, pyautogui bridge, lerobot bridge, UTM, CAE bridge, file transfer 상태가 포함된다.

## Agent Chat Contract

각 agent는 채팅에 노출할 메시지와 report에 남길 정보를 분리한다.

### Orchestrator

Chat:

- 필요한 실험 정보를 질문한다.
- 부족한 값을 명확히 알려준다.
- 사용자가 실행 키워드를 알 수 있게 안내한다.
- 현재 workflow가 어디까지 왔는지 짧게 말한다.

Report:

- mission plan
- experiment objective
- input completeness
- selected workflow path

Backend:

- routing decision
- agent handoff plan
- tool selection trace

### Design Agent

Chat:

- 설계값이 부족하면 현재 있는 값과 없는 값을 예시와 함께 알려준다.
- 후보 설계를 만들면 핵심 변경점만 말한다.
- test loop에서는 이전 형상과 다음 형상 비교가 준비되었다고 말한다.

Report:

- TPMS/FDM 조건
- geometry parameter
- BO candidate input
- STL screenshot or figure
- previous/current candidate comparison

Backend:

- generator parameter
- geometry validation trace
- artifact path

### Specimen Making Agent

Chat:

- 테스트 모드에서 가상 bridge, 설치 프린터, 실제 출력 선택이 필요한 경우 질문한다.
- 실제 출력이면 slicing, upload, start 상태를 사용자 친화적으로 말한다.
- printer connection info가 없으면 필요한 정보와 저장 경로를 안내한다.

Report:

- slicer profile
- layer height, first layer height, bed/nozzle temperature
- cap skin option
- skirt option
- autoeject option
- PrusaLink preparation result

IO:

- upload status
- start print status
- printer ready state
- PrusaLink response

### Vision Agent

Chat:

- vision evidence가 확보되었는지 말한다.
- 물체 인식 또는 품질 검사가 막히면 사용자에게 필요한 조치를 말한다.

Report:

- image evidence
- detection result
- confidence
- anomaly summary

Backend:

- camera/vision tool trace

### Manipulation Agent

Chat:

- robot rollout 준비 여부를 말한다.
- 안전상 대기 또는 승인 필요 시 사용자에게 직접 말한다.
- transport 완료 여부를 짧게 말한다.

Report:

- policy path
- robot profile
- rollout guard
- action clamp/speed setting
- session result

IO:

- lerobot process state
- robot bridge response

### Lab Equipment Agent

Chat:

- 장비 bridge 연결 상태와 사용자 조치가 필요한 부분만 말한다.
- UTM 또는 Windows macro 실행 준비 여부를 말한다.

Report:

- equipment command plan
- UTM run metadata
- pyautogui bridge target
- output data path

IO:

- bridge discovery/connect/test result
- hardware command trace

### Analysis Agent

Chat:

- 분석 완료 여부와 핵심 결과를 짧게 말한다.
- test loop에서 다음 BO에 전달할 metric을 말한다.

Report:

- UTM metric
- CAE/FEM metric
- contour figure
- failure mode
- model-data agreement

Backend:

- CAE bridge trace
- solver status

### Knowledge Agent

Chat:

- 새 실험 지식이 저장되었는지 말한다.
- 다음 cycle에 반영될 핵심 정보를 말한다.

Report:

- memory update
- evidence link
- experiment ID
- reusable constraints

Backend:

- graph DB or file store update trace

### BO Agent

Chat:

- 다음 후보가 왜 선택되었는지 한두 문장으로 말한다.
- 탐색/활용 방향을 사용자에게 이해 가능한 수준으로 말한다.

Report:

- surrogate update
- acquisition function
- observed points
- next candidate
- BO plot

Backend:

- optimizer state
- random/grid/BO benchmark trace

### Guardian Agent

Chat:

- 사용자 승인이나 조치가 필요한 allow/block/warning만 말한다.
- 위험 또는 중단 이유를 명확히 말한다.

Report:

- gate decision
- evidence completeness
- safety/compliance check
- failure or warning code

Backend:

- rule evaluation trace
- policy decision payload

## Implementation Plan

### Phase 1: Backend Message Classification

목표:

- 새 메시지를 저장할 때 `message_class`, `surface`, `visibility`, `event_type`을 부여한다.
- 기존 transcript 저장은 유지한다.
- legacy message도 display 시점에 fallback classification을 적용한다.

작업 후보:

- `app/controller.py`에 `classify_planning_message()` helper 추가
- `_record_planning_message()` 또는 `_compact_planning_message_for_display()`에서 classification 적용
- `SYSTEM_EVENT:` prefix 기반 legacy system event 분류
- `message_type` 기반 guardian/chat/report 분류
- agent role 기반 기본 surface 분류

불변 조건:

- JSONL transcript는 삭제하지 않는다.
- 기존 API response shape는 가능한 유지하고 metadata만 추가한다.
- audit/replay 가능한 raw message는 Backend에서 접근 가능해야 한다.

### Phase 2: Frontend Chat Filtering

목표:

- `renderPlanningMessages()`가 chat surface message만 렌더링한다.
- system event는 chat에서 사라지고 Timeline/Backend에 표시된다.

작업 후보:

- `web/static/planning.js`에 `isChatSurfaceMessage(message)` 추가
- `renderPlanningMessages()`에서 chat filter 적용
- legacy `SYSTEM_EVENT:` message fallback filter 추가
- chat empty state와 scroll behavior 유지
- operator input과 agent chat은 기존 스타일 유지

불변 조건:

- 사용자는 agent 응답을 놓치지 않아야 한다.
- error/warning 중 사용자 조치가 필요한 것은 chat에 남아야 한다.
- long-running test loop에서도 chat scroll이 안정적으로 동작해야 한다.

### Phase 3: Timeline / Backend Routing

목표:

- handoff, cycle, workflow 이벤트를 Timeline에 안정적으로 표시한다.
- raw backend trace는 Backend에 표시한다.

작업 후보:

- existing backend/timeline renderer가 `message_class`와 `event_type`을 소비하도록 보강
- `SYSTEM_EVENT: HANDOFF` legacy parser 추가
- `cycle_index`, `total_cycles`를 cycle chip과 timeline 양쪽에 반영
- Backend에는 raw payload, retry, bridge response를 남긴다.

불변 조건:

- 5-cycle test에서 모든 handoff가 Timeline에 보여야 한다.
- Backend에는 debugging에 필요한 원본 정보가 남아야 한다.

### Phase 4: Agent Report Separation

목표:

- agent의 상세 결과는 Report/Artifacts에 표시하고 chat에는 요약만 남긴다.

작업 후보:

- agent별 report card payload schema 정리
- Design STL screenshot, BO plot, FEM contour 등 heavy artifact는 lazy/collapsed display 유지
- chat에는 report anchor 또는 짧은 summary만 표시
- Specimen Making은 STL preview가 아니라 slicing/printer 단계와 설정값 중심으로 표시

불변 조건:

- 기존 artifact path와 generated files는 유지한다.
- report에 들어갈 핵심 evidence가 chat filter로 사라지면 안 된다.

### Phase 5: Verification

목표:

- Test mode, Live mode, Live GUI 내부 test command에서 동일한 routing 원칙이 적용되는지 검증한다.

검증 항목:

- Chat에 `SYSTEM_EVENT:` 문자열이 보이지 않는다.
- Chat에 모든 agent의 사용자-facing 요약이 표시된다.
- Timeline에 cycle 1/5부터 5/5까지 표시된다.
- Timeline에 Design → Specimen Making → Vision → Manipulation → Lab Equipment → Analysis → Knowledge → BO → Guardian handoff가 표시된다.
- Report에 각 agent 결과가 agent별로 분리된다.
- Backend에 raw handoff/tool/system event가 남는다.
- IO에 printer, robot, bridge, file transfer 상태가 표시된다.
- 새로고침 후 현재 세션 상태가 복원된다.
- 서버 재시작 후 세션 상태는 초기화되되 transcript 파일은 audit용으로 남는다.
- legacy transcript 파일도 crash 없이 열린다.

## Compatibility Rules

다음은 반드시 유지한다.

- 기존 LLM/MCP tool protocol은 변경하지 않는다.
- agent loop 순서는 변경하지 않는다.
- transcript JSONL 저장은 유지한다.
- `/api/planning/messages` 계열 endpoint는 기존 frontend를 깨지 않도록 metadata 추가 방식으로 확장한다.
- 기존 role 이름은 유지한다.
- 기존 report/backend/timeline DOM 구조는 재사용한다.
- hardware bridge 호출 방식은 변경하지 않는다.

## Risk And Mitigation

### Risk: 중요한 오류가 Chat에서 숨겨짐

대응:

- `severity == "error"`이고 `requires_user_action == true`인 경우 chat에도 표시한다.
- Guardian block, printer connection required, hardware disconnected 같은 사용자 조치 필요 오류는 chat 예외로 둔다.

### Risk: legacy transcript와 새 schema가 섞임

대응:

- `surface`가 없으면 content prefix, role, message_type으로 추론한다.
- 추론 실패 시 Backend에 표시하고 Chat에는 표시하지 않는다.

### Risk: Report에 표시되어야 할 artifact가 사라짐

대응:

- chat filter는 message 삭제가 아니라 surface 분리만 수행한다.
- `artifact_refs`, `payload_ref`를 Backend/Report renderer가 계속 참조한다.

### Risk: frontend에서 message count가 줄어든 것으로 오해됨

대응:

- Chat에는 filtered count를 표시하지 않는다.
- Backend 또는 Timeline에 전체 event count를 유지한다.

### Risk: agent가 여전히 raw JSON을 content에 넣음

대응:

- backend classification에서 raw JSON형 content를 `agent_report` 또는 `backend`로 우선 라우팅한다.
- agent별 chat contract를 docs와 tests에 반영한다.

## Test Plan

### Unit Tests

추가 또는 보강 대상:

- `tests/unit/test_controller_planning.py`
- planning message classification test
- legacy `SYSTEM_EVENT:` routing test
- guardian user-facing warning chat exception test
- artifact/report message non-chat routing test

핵심 assertion:

- `SYSTEM_EVENT: HANDOFF`는 `surface=["timeline", "backend"]`
- operator message는 `surface=["chat"]`
- design summary는 `surface=["chat"]`
- design artifact payload는 `surface=["report", "artifacts"]`
- printer connection required는 `surface=["chat", "io", "backend"]`
- raw bridge response는 `surface=["backend", "io"]`

### Frontend Checks

검증 대상:

- `renderPlanningMessages()`가 chat message만 표시한다.
- Timeline renderer가 handoff/cycle event를 표시한다.
- Backend renderer가 raw event를 표시한다.
- Report renderer가 agent-specific cards를 표시한다.
- 새 메시지 수신 시 chat scroll이 하단으로 이동한다.
- event가 많아도 chat DOM이 과도하게 커지지 않는다.

### End-To-End Checks

검증 시나리오:

- Main GUI test mode
- Live GUI에서 `테스트 모드, 가상 브릿지`
- Live GUI에서 `테스트 모드, 설치 프린터`
- Live GUI에서 `테스트 모드, 실제 출력`
- Live mode 실제 printer/robot bridge 비활성 dry run
- 5-cycle closed-loop test

완료 기준:

- 5-cycle loop가 `WORKFLOW_COMPLETE`까지 간다.
- Chat은 사람이 읽는 대화 흐름으로 유지된다.
- Timeline은 모든 handoff와 cycle을 포함한다.
- Report는 각 agent별 결과를 포함한다.
- Backend는 raw system/tool event를 포함한다.
- 메모리 사용량이 메시지 렌더링 때문에 지속 증가하지 않는다.

## Suggested File Map

계획상 수정 대상은 다음이다. 이 문서 단계에서는 수정하지 않는다.

| File | Planned Role |
|---|---|
| `app/controller.py` | planning message classification, display compact metadata |
| `web/static/planning.js` | chat filtering, routing-aware render, scroll behavior |
| `web/templates/planning.html` | 필요 시 surface label 또는 container만 최소 변경 |
| `web/static/styles.css` | chat/system/report visual separation style |
| `tests/unit/test_controller_planning.py` | backend classification tests |
| `tests/ui/...` | optional frontend regression checks |
| `docs/gui/gui.md` | 구현 완료 후 사용자 설명 반영 |

## Non-Goals

이번 변경 계획에 포함하지 않는 항목은 다음이다.

- Live GUI 전체 레이아웃 재디자인
- LLM/MCP 프로토콜 변경
- agent 실행 순서 변경
- transcript 삭제 또는 저장 방식 폐기
- hardware bridge 동작 방식 변경
- 새로운 agent 추가
- Report/Backend/Timeline 패널 제거

## Acceptance Criteria

구현 완료 판단 기준은 다음이다.

- Chat에서 `SYSTEM_EVENT:`가 사라진다.
- Chat에는 사용자와 agent의 자연어 대화만 남는다.
- agent별 상세 결과는 Report에 표시된다.
- handoff와 cycle 진행은 Timeline에 표시된다.
- raw tool/system trace는 Backend에 표시된다.
- hardware/file 상태는 IO에 표시된다.
- 기존 transcript는 audit/replay 용도로 유지된다.
- 5-cycle test mode에서 cycle 1/5부터 5/5까지 끊기지 않는다.
- 사용자가 Live GUI를 새로고침해도 현재 상태가 복원된다.
- 서버를 재시작하면 UI 상태는 초기화되지만 저장 transcript는 보존된다.

## Recommended Execution Order

구현 시에는 다음 순서로 진행한다.

1. Backend classification helper를 먼저 만든다.
2. Unit test로 legacy/system/chat/report routing을 고정한다.
3. Frontend chat filter를 적용한다.
4. Timeline/Backend renderer가 새 metadata를 소비하도록 보강한다.
5. Agent report card routing을 정리한다.
6. 5-cycle test loop로 실제 표시 흐름을 검증한다.
7. 메모리 사용량과 DOM node 증가 여부를 확인한다.
8. 검증 후 `docs/gui/gui.md`와 tutorial 문서를 갱신한다.

## One-Line Design Decision

Live GUI의 Chat은 사용자와 agent의 대화 surface로 제한하고, 시스템 이벤트는 Timeline/Backend/IO/Report로 라우팅한다.
