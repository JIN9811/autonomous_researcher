---
doc_type: design
subtype: architecture
status: active
authority: proposal
audience: [developer, maintainer, researcher, reviewer]
scope: [orchestrator, experimental_setup, live_gui, agent_owned_configuration]
summary: 에이전트가 보고한 가용 상태에 근거하는 Orchestrator 판단과, Chat에서 편집하는 동적 실험 설정 블록을 기존 실행 경로에 연결한다.
decision_status: approved
related_docs:
  - docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
  - docs/agents/orchestrator_agent.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/runtime/runtime_ide.md
  - docs/runtime/loop_artifact_archiving.md
  - docs/standards/documentation_standard.md
  - docs/superpowers/plans/2026-09-12-orchestrator-dynamic-experimental-setup.md
supersedes: []
---

# Orchestrator · 동적 Experimental Setup · Live GUI 통합 설계

## Status at a Glance

| At a glance | Details |
|---|---|
| 범위 | Orchestrator의 국소 판단층, 실험 설정 블록, 기존 Live GUI/Chat 연결 |
| 설계 상태 | 상세안 승인; 구현 계획 진행 중 |
| 구현 상태 | 핵심 계약·Setup·Chat·기존 인계 연결과 bounded provider aggregate까지 working tree에서 완료; 문서 최종 검토는 별도 절차 |
| 보존 경계 | 기존 graph/runtime, 전문 에이전트 소유권, 장비 실행·정지 경로 |
| 검증 계획 | 단위·API·GUI·비구동 루프 및 등록 API/로컬 vLLM 검증 |
| 실제 장비 | 이번 구현·검증 범위에서 구동하지 않음 |

## Summary

**Chat은 실험을 합의하고 수정하는 공간, Experimental Setup은 현재 합의와 실제
적용 상태를 주제별 블록으로 보여주는 공간**으로 만든다. Orchestrator는 담당
에이전트가 공개한 기능·설정·가용 상태를 조회하여 변경과 위임을 판단한다.

블록의 수정 버튼은 과거 대화로 이동하거나 입력폼을 직접 수정하지 않는다.
현재 Chat을 열어 수정 대상의 맥락을 연결한다. Chat에서 시작한 수정도 같은
블록과 서버 측 초안을 사용한다.

이 문서는 공통 5영역 계약의 Orchestrator 적용 상세안이다. 이번에 명시적으로
합의한 동적 설정 연동만 범위에 추가한다. 과거 캠페인·슬롯 설계 전체를 재개하지 않는다.
상세안은 구현의 목표 계약을 소유한다. 현재 구현 상태와 한정된 검증 근거는 아래
`구현 반영 현황`과 `Verification`에만 기록하며, 이 문서가 모델·장비 실증 완료를
대신 주장하지 않는다.

## Problem

현재 Orchestrator는 상태를 충분히 확인하지 않은 제안을 할 수 있고, 계획 문장과
실제 실행 결정이 분리되어 있다. Setup은 고정된 읽기 전용 요약이어서 대화로 결정한
내용·수정안·실제로 적용된 값의 차이를 확인하기 어렵다.

단순히 Chat의 답변을 화면에 복사하거나 설정값을 전역 상태에 쓰는 방식으로는
담당 에이전트가 실제로 적용했는지 보장할 수 없다. 또한 실행 중인 작업과
다음 작업의 설정, 오래된 자원 상태와 현재 준비 상태를 구분해야 한다.

## Goals and Non-goals

### 목표

- 정상 경로에서 LLM의 의미 있는 조회·위임·추가 확인·진행 판단을 실제 도구 호출에 연결한다.
- 현재 가용 상태와 설정 지원 범위를 확인하고, 알 수 없는 상태를 명시한다.
- 실험별로 필요한 설정 블록을 구성하고 Chat과 동일한 상태를 공유한다.
- 설정의 의미·검증·적용은 담당 에이전트에 남기고 실제 소비 경로까지 추적한다.
- 기존 handoff, 실행 모드, 재시도, Guardian, loop/attempt 보관을 보존한다.

### 범위 밖

- 새로운 실험 슬롯·연구 캠페인 관리 시스템, 새 범용 워크플로 엔진.
- LLM의 자유로운 graph 생성·변경, 전문 에이전트 계산 및 장비 동작의 재작성.
- Orchestrator의 bridge 직접 호출, 임의 설정 파일 편집, 자유 형식 장비 명령.
- Chat의 설정 확정과 장비 실행 승인을 동일하게 처리하는 것.
- 현재 실행의 입력을 대화 도중 덮어쓰거나 성공한 물리 작업을 자동 재실행하는 것.
- 미지원 설정을 지원하는 것처럼 표시하기 위한 전체 에이전트·브릿지 개편.
- 운영 서버 재시작, 실제 장비 구동, 기존 실증을 새 구현 검증으로 재분류하기.

## Current Context

조사 기준은 `5081c12b521ae7b6fb2cd4deb76ab867616d3533`이다.

| 현재 코드 | 확인한 동작 | 재사용·변경 방향 |
|---|---|---|
| [OrchestratorAgent](../../../agents/orchestrator_agent.py) | `orchestrator_plan`으로 문장을 생성한 뒤 고정 결정 `prepare_stage_handoff_context` 구성 | 기존 결과 키를 유지하고 제한된 판단·도구 실행 추가 |
| [Supervisor](../../../orchestrator/supervisor.py) | mission/plan/followup/decision/handoff 계약 생성 | 구조화 결과와 근거의 직렬화에 재사용 |
| [LangGraph runtime](../../../orchestrator/langgraph_runtime.py) | pre-step 실행, 완료 결과 처리, graph 후보·다음 단계 계산, followup 기록 | 기존 인계 경계에서만 판단 결과 소비; 별도 실행 루프 신설 금지 |
| [Controller](../../../app/controller.py) | planning lock, 세션 snapshot, Chat, 실행 중 followup queue, Design 인계 경로 | 같은 판단 서비스·설정 상태를 연결하고 기존 진입 경로 유지 |
| [Planning API](../../../app/main.py) | `/api/planning/session`, `/messages`, `/message`, `/bootstrap` | 기존 Chat와 snapshot에 선택적 설정 맥락·요약 추가 |
| [Planning UI](../../../web/static/planning.js) | `renderLiveExperimentSetupPanel`에 고정된 6개 readonly 항목 | 에이전트가 공개한 주제별 블록으로 교체 |
| 같은 UI의 `draft_apply` 처리 | 현재 spec을 문장으로 만들어 Chat 입력란에 배치 | 블록 ID·revision 기반 편집 맥락으로 교체; 클릭만으로 전송하지 않음 |
| [State](../../../orchestrator/state.py) | `agent_status`, `device_health`, `run_metadata` 등 | 기존 증거의 출처로 활용하되 idle/health 문자열만으로 실행 가능 판정 금지 |

`OrchestratorAgent.run`만 바꾸면 Live Chat와 일부 planning 경로에는 반영되지 않는다.
반대로 Chat 답변만 바꾸면 runtime 인계 결정은 그대로다. 두 진입점이 같은 판단
서비스를 호출하고, 실제 기존 소비 경로에 결과가 반영되는 검증이 필요하다.

## Options Considered

| 방식 | 장점 | 한계 | 결정 |
|---|---|---|---|
| Chat 요약을 카드로 표시 | 변경이 작음 | 실제 설정 적용·가용성·위임 판단을 보장하지 못함 | 제외 |
| LLM이 화면·설정·장비 명령까지 자유 생성 | 표현 자유도가 큼 | 소유권·검증·기존 실행 경로가 불명확해짐 | 제외 |
| 에이전트 공개 계약 + 서버 측 설정 블록 + 제한된 LLM 판단 | 실제 지원 범위와 효과를 추적하면서 동적으로 구성 가능 | 최소 설정 adapter와 상태 동기화 필요 | 채택 |

## Decision

공통 계약 위에 **가용 상태에 근거하는 Orchestrator 판단층**을 두고, 그 대화에서
합의한 설정을 **동일 세션의 revision을 가진 블록**으로 관리한다. UI는 상태의
표현이며 실제 설정의 별도 소유자가 아니다.

LLM은 무엇을 조회하고 어떤 변경·위임을 제안할지 판단한다. 코드가 허용된
설정 경로·graph 후보·입력 계약을 검증하고, 담당 에이전트가 적용 및 수용 여부를 결정한다.

## Architecture and Contracts

### 1. 다섯 영역의 책임

| 영역 | 이번 책임 | 기존 소유권 |
|---|---|---|
| High-Level Control | 목표와 근거를 종합해 설정 제안, 추가 조회, 위임, 대기·검토 반환 선택 | 전문 에이전트의 계산·조건을 대신 결정하지 않음 |
| Middle-Level Control | 구조화된 도구 선택 검증, 블록 변경안, owner 요청, 기존 handoff 연결 | 실제 라우팅·상태 변경은 기존 runtime/controller |
| Low-Level Control | 기존 에이전트 호출 및 상태·설정 adapter 실행 | 장비 동작은 담당 에이전트와 기존 bridge |
| Guardian / Safety | 권한·scope·승인·freshness·취소·중복 효과 검증 | 긴급 정지와 기존 hard gate는 LLM을 기다리지 않음 |
| Knowledge / Evidence | 모델·도구·근거·설정 revision·적용 응답을 기존 보관에 연결 | 과거 아티팩트를 현재 준비 상태로 승격하지 않음 |

### 2. 에이전트 공개 계약과 가용 상태

참여 목록의 기준은 IDE 목록이나 전체 AgentRegistry가 아니라 **현재 메인 LangGraph의
실행 노드와 연결된 module 계약**이다. graph의 node/module/handler를 해석하여 공개
계약을 자동 수집한다. 노드 추가·제거·계약 revision 변경 시 현재 목록과 Setup을
동기화하되 과거 블록은 inactive 이력으로 보존한다. 이미 시작한 run은 graph와 계약
snapshot을 유지한다. 동일 에이전트의 여러 노드는 node별 인수 조건을 구분하고
owner 설정은 중복 생성하지 않는다. 런타임 dispatch 같은 비에이전트 노드는 제외한다.
모듈이 admission/result/acceptance 계약을 공개하며 Orchestrator는 이름별 분기 없이
해석한다. 미제공 계약은 명시적으로 unknown이며 기존 owner 검증을 우회하지 않는다.
계약 목록에서 stage dispatch 실행 노드, 기존 pre-execution 참여자, overlay-only 역할을
구분한다. overlay 계약을 표시한다고 그 노드를 새로 실행하거나 인계 후보로 추가하지 않는다.

새 공통 서비스나 네트워크 프로토콜을 먼저 만들지 않는다. 등록된 에이전트의
기존 함수·계약을 얇은 in-process adapter로 노출한다. 아래 이름은 **새 내부 계약의
제안명**이며 현재 모든 에이전트에 존재하는 API라는 뜻이 아니다.

| 공개 항목 | 필수 내용 |
|---|---|
| 기능·설정 descriptor | owner, capability/setting ID, type, unit, 허용 범위·선택지, 읽기/쓰기 지원, 적용 가능 시점, 의존 입력 |
| Availability snapshot | scope, capability, 상태, blocker/reason, 관측 시각, 만료 시각 또는 unknown, evidence refs, owner revision |
| 설정 validation 응답 | 지원 여부, 정규화 값, 거부 이유, 필요한 승인, 영향받는 의존 항목 |
| 설정 적용 receipt | request ID, owner, 적용 값·revision, 적용 대상/시점, 실제 소비 위치, readback 결과 |

가용 상태는 capability 단위로 `ready`, `busy`, `unavailable`, `unknown`을 표현한다.
의사결정 선택지는 이 근거를 코드가 종합해 실행 가능·대기·불가·추가 확인으로 좁힌다.
등록됨, 에이전트 idle, 과거 성공, 모델 목록에 존재함은 각각 현재 준비 완료와 다르다.

에이전트가 기존 경로로 보고한 상태·이벤트를 먼저 사용한다. 해당 판단에 필요한
근거가 누락·만료되었을 때만 owner의 읽기 전용 조회를 호출한다. 조회 구현이 없다면
`unknown`으로 남기며 임의 ping·장비 초기화·모델 로딩으로 상태를 만들지 않는다.
무거운 조회를 렌더링이나 폴링마다 수행하지 않고 관련 이벤트에 따라 무효화한다.
기존 Vision/장비 신호의 timestamp와 TTL은 이 snapshot 때문에 연장하지 않는다.

인계 직전 owner/runtime이 준비 상태·예약/점유·입력 revision을 다시 확인한다.
기존 자원 lease가 있으면 사용한다. 원자적인 확보 기능이 없는 경우 availability
snapshot을 예약으로 취급하지 않고 owner의 실행 수용 응답을 최종 기준으로 삼는다.
상태 변경 시 먼저 실행하지 않고 인계를 보류한다.

### 3. Orchestrator의 제한된 도구

| 제안 도구 | 의미 있는 효과 | 제약 |
|---|---|---|
| `inspect_context` | 현재 계약·결과·설정 및 필요한 근거 조회 | 등록된 scope/evidence만; 임의 파일 접근 없음 |
| `inspect_availability` | 필요한 owner/capability 상태 확인 | 읽기 전용; 타 에이전트의 run을 상태 조회용으로 호출하지 않음 |
| `propose_setup_change` | 특정 블록 revision에 대한 구조화 변경안 생성 | owner가 공개한 설정만; 실제 적용 아님 |
| `request_owner_review` | 구체적인 누락·충돌 근거를 담당자에게 반환 | 기존 문의·대기 경로; 물리 작업 재시작 아님 |
| `prepare_handoff` | 허용된 다음 작업의 context/handoff를 구성하여 기존 dispatcher에 전달 | 현재 graph의 유효 후보만; 직접 agent.run과 dispatcher를 함께 호출하지 않음 |
| `defer` | 대기 이유와 재평가 조건을 기록 | 즉시 반복 추론 대신 해당 상태 변경 또는 명시적 사용자 응답을 기다림 |

모델 응답은 `tool`, schema로 제한된 `arguments`, 짧은 `reason`, `evidence_refs`로
검증한다. 내적 추론 전문은 필요하지 않다. 채팅 답변과 실제 도구 효과를 구분한다.
설정 확정은 사용자의 행위이며 LLM이 자기 제안을 스스로 확정하는 도구는 제공하지 않는다.

판단 호출 위치는 (a) 계획·설정 관련 사용자 요청, (b) 기존 실행 인계 경계이다.
동일 경계의 pre/post callback에서 두 번 호출하지 않도록 한 번의 결정 ID로 묶는다.
진행 중 poll, UI 클릭, 이미 처리된 이벤트, 장비 workflow 내부에는 호출하지 않는다.
조회 회수·토큰·timeout은 기존 모델 설정을 우선 사용하고 bounded decision budget으로
제한한다. 등록 API와 로컬 vLLM 모두 같은 계약을 사용한다.

판단은 `(run, loop, stage/task, checkpoint, attempt, input/result revision, setup revision)`에 연결한다.
유효한 동일 결정은 재사용하고, 관련 상태가 바뀌면 다시 검토한다. 새 모델 판단이
이미 수행한 물리 효과를 새 작업으로 바꾸지는 않는다.

### 4. 실제 인계 경계와 중복 실행 방지

기존 runtime이 전문 에이전트 결과와 필수 gate를 확인한 뒤 허용된 인계 후보를
판단층에 전달한다. `prepare_handoff`가 반환한 계약은 **기존 전이·dispatch 경로에서
한 번만 소비**한다. 모델이 선택할 수 있는 후보가 하나뿐이어도 근거 확인, 추가
조회 또는 보류의 선택은 실제 결과에 반영되어야 한다.

결과 완료와 인계 대기를 분리한다. 보류 시 완료된 stage를 단순히 같은 stage로
되돌려 다음 tick에서 `agent.run`을 다시 호출하면 안 된다. 기존 metadata에
소비 대기 중인 결과/인계 ID를 보존하고, 재개는 그 인계 검토부터 한다.
이미 완료된 작업, 아카이브, Guardian loop counter 역시 한 번만 반영한다.
안전 정지·취소·기존 필수 종료 전이는 새 LLM 검토로 지연하지 않는다.

**짧은 freshness 유효시간을 갖는 관측과 그 소비 사이에는 새 LLM await를 끼우지
않는다.** 그런 복합 작업의 Orchestrator 판단은 해당 관측을 시작하기 전의 기존
작업 위임 경계에 배치한다. 이후 관측·장비 인계 구간은 기존 owner 루틴과 결정론적
검증을 유지한다. 이는 모든 stage 전후에 획일적인 LLM gate를 추가하는 설계가 아니다.
구현 시 callback별 판단 위치와 시간 민감 구간을 대응표로 확정하고, 모델 지연을
주입해 기존 신호 유효기간·인계가 훼손되지 않는지 검사한다. 유효기간 연장으로 해결하지 않는다.

기존 planning Design 인계, 일반 runtime, 실행 중 followup에 같은 정책을 연결한다.
어느 한 경로의 shortcut으로 정상 LLM 판단이 빠지거나, 새 별도 테스트 경로만
통과하는 것은 구현 완료가 아니다.

관측 후 실제 실행 입력 변경으로 승인이 무효화되면, 해당 checkpoint/run/loop/specimen에
결부된 명시적 재관측 요청을 기존 followup/dispatch에서 처리한다. 완료한 물리 작업은
보존하고 기존 Vision 경계에서 새 관측을 승인한 후 촬영한다. 일반 대화·폴링은 재촬영을
유발하지 않으며 새 촬영과 소비 사이에 모델 판단을 추가하지 않는다. 기존 시편 미검출
개입이나 로봇 정지·카메라 반환 근거를 이 복구용으로 위조하지 않는다.

### 5. 동적 Setup 블록

주제 예시는 Research Goal, Design Space, Execution Plan, Resources, Evaluation이다.
고정 다섯 블록이나 고정 실험 종류를 강제하지 않는다. 활성 실험의 계약과 참여
에이전트 descriptor에 따라 구성하며 block kind는 등록된 UI renderer에서 선택한다.
LLM이 임의 HTML, 코드, 새 설정 키를 생성하지 않는다.

블록은 채팅 메시지가 아니라 하나의 결정 주제다. 생성은 유효한 구조화 제안이나
기존 명시적 설정을 불러올 때 이루어진다. 단순 설명·조회 답변마다 블록을 만들지 않는다.
기존 블록 수정은 안정된 ID를 유지하고 revision을 올린다. 화면 배열은 실행 순서가 아니다.

| 블록 필드 | 계약 |
|---|---|
| 정체성 | `block_id`, `topic_key`, `kind`, `title`, owner 목록, planning session |
| 변경 제어 | `revision`, `base_revision`, 제안/message ID, 변경 사유 |
| 값 | proposed values, 사용자 confirmed values, owner effective values 구분 |
| 적용 대상 | run/loop 또는 다음 실행; 기존 immutable execution snapshot 참조 |
| 의존성 | 설정·owner revision 및 영향을 받는 블록 참조 |
| 근거 | owner receipt, validation 결과, evidence refs, 변경 이력 참조 |

상태를 하나의 문자열에 과도하게 섞지 않는다.

- 합의 상태: `draft`, `confirmed`.
- 적용 상태: `not_applied`, `scheduled`, `applying`, `applied`, `partial`, `rejected`, `unknown`.
- 자원 가용 상태: 별도 live projection. 일시적인 연결 해제가 합의 내용을 삭제하지 않는다.

카드에는 제목, 핵심 값, owner, 상태, 적용 시점, `Edit in Chat`을 간결하게 표시한다.
변경 전·후 값과 상세 근거·이력은 펼쳐서 본다. 새 draft가 있어도 현재 effective
값을 숨기지 않는다. 여러 owner 중 일부만 적용되면 전체 `Applied`로 표시하지 않는다.

### 6. Chat과 블록 편집

블록 UI는 기존 Experimental Setup의 배치 공간을 그대로 사용한다. 별도 패널을
추가하지 않으며, 세로 공간이 부족하면 Setup 영역 안에서 스크롤한다. 기존
Chat/Setup 전환과 주변 화면 배치를 유지하고 마지막 블록의 조작까지 접근 가능해야 한다.

추가 승인된 입력 범위 정책: 실험 계획·시스템 상태·관련 연구 질문은 답변할 수 있다.
무관한 요청에는 실질적인 답변 대신 짧은 범위 안내만 하고, 의미 불명 요청에는
짧게 확인한다. 욕설·오타·축약어 자체를 차단 기준으로 삼지 않는다. 질문·부정·인용을
실행 명령으로 해석하지 않으며, 분류가 불확실하면 설정/실행 효과가 없는 응답을 선택한다.
현재 작업 맥락에 결부된 명시적 승인만 기존 실행 승인 경로로 넘긴다.

1. 블록의 `Edit in Chat`을 누르면 기존 Chat을 열고 Orchestrator를 대상으로 설정한다.
2. 상단에 `Editing: <block title>`과 `Exit editing`을 표시한다. ID·revision을
   맥락으로 전달하되 문장을 자동 전송하거나 설정을 변경하지 않는다.
3. 서버는 클라이언트가 보낸 값 대신 해당 세션의 최신 블록을 다시 읽는다.
   실제 run·mode·실행 여부·소유권도 서버 상태를 기준으로 검증한다.
4. 사용자 요청을 변경안으로 만들어 Chat과 해당 블록에 동시에 표시한다.
5. 정확한 diff·대상 revision·적용 시점을 확인한 사용자가 확정하면 owner 검증·적용을 수행한다.
6. owner readback 결과에 따라 두 화면을 같은 서버 revision으로 갱신한다.

Chat에서 바로 시작해도 동일 경로를 탄다. 대상이 명확하면 블록을 선택하고,
여러 대상에 걸치는 모호한 요청은 확인한다. 일반 질의는 설정을 바꾸지 않는다.
편집 중 무관한 주제로 바뀌면 이전 블록에 강제로 적용하지 않고 편집 대상 해제를 안내한다.
편집 종료는 초안을 삭제하지 않는다.

명시적인 확인 UI를 기본 확정 수단으로 둔다. 채팅의 확인 표현도 서버가 특정
pending proposal ID/revision 하나로 연결할 수 있을 때만 같은 확정 경로를 사용한다.
일반적인 “ㅇㅋ”를 임의 설정이나 장비 실행 승인으로 확대 해석하지 않는다.

**Setup 편집 요청은 기존 Design 실행·프린터 선택 등 command keyword 분기보다 먼저
구조화된 편집 요청으로 분류**한다. “다음 실험 설계를 수정”이라는 문장이 기존
`_should_trigger_design` 경로를 통해 바로 실험을 시작하지 않도록 한다.
실행 시작은 기존 별도 실행 명령·승인 경로를 유지한다.

### 7. 설정 소유권과 적용

첫 구현의 등록 목록은 기존 소비 경로가 확인되는 설정으로 제한한다. 각 write-enabled
설정에 대해 **descriptor → owner 검증/적용 함수 → 실제 실행 입력 소비 위치 →
readback → 테스트** 대응표를 만든다. 이 중 빠진 항목은 read-only 또는 unsupported다.
LLM의 문장이나 임의 `run_metadata` 저장만으로 `Applied`를 만들지 않는다.

고수준 목표는 Orchestrator가 소유할 수 있지만 전문 설정은 각 에이전트 소유다.
BO 수치 추천을 Orchestrator가 다시 계산하거나, 장비 조건을 bridge 설정 파일에
직접 쓰지 않는다. Execution Plan 블록도 기존 graph의 설명·허용된 선택 범위이지
임의 graph editor가 아니다.

실행 중 수정은 원칙적으로 다음 실행 대상으로 저장한다. 현재 실행의 snapshot은
보존한다. 기존 owner가 명시적으로 지원하고 사용자가 선택한 안전한 경계 적용만
예외적으로 허용한다. `scheduled`는 적용 성공이 아니다.

여러 owner 변경은 먼저 전체 validation을 수행한다. 그 뒤 부분 실패하면 owner별
receipt와 `partial`을 남기고 성공한 적용을 반복하지 않는다. 물리 작업을 롤백으로
수행하지 않으며 원자적 다중 owner transaction을 지원한다고 주장하지 않는다.
관련 설정을 모두 확인하기 전에는 영향을 받는 새 작업을 인계하지 않는다.
의존 블록은 stale 표시 후 재검증하고, 사용자 합의 없이 값을 연쇄 변경하지 않는다.

### 8. API·저장·이벤트

기존 `/api/planning/message`의 optional 편집 맥락으로 session/block/proposal/revision을
전달한다. 기존 일반 Chat 요청의 필수 필드를 늘리지 않는다. `/api/planning/session`에
현재 Setup 요약·revision을 추가하고 기존 메시지 페이지네이션을 유지한다.

목표 API로 `/api/planning/setup/actions` 하나를 추가하여 구조화된 `confirm`,
`discard_proposal` 요청을 받는다. 서버 측 서비스는 Chat 확정과 이 API에서 공통 사용한다.
요청은 session, proposal, expected revision, request ID, 적용 대상을 포함한다.
임의 owner/path를 받는 범용 config write API로 만들지 않는다.

기존 세션 보관 경로 아래 Setup 상태와 revision 이력을 저장한다. Chat transcript는
근거이지 매번 전체 재추출하는 상태 저장소가 아니다. run을 시작할 때 Setup snapshot을
기존 run/loop 아티팩트에 연결한다. 새 외부 저장소·DB는 만들지 않는다.

쓰기 시 revision 비교와 기존 lock/원자적 파일 저장을 사용한다. 두 탭의 충돌은
후입력 덮어쓰기 대신 conflict로 반환한다. 동일 request ID의 재전송은 저장된
결과를 반환한다. owner 적용 직후 응답 유실은 readback으로 확인하며 무조건 재적용하지 않는다.
재시작 후 기존 세션을 읽어 복원하되 pending/applying 상태가 장비 실행 재개를 유발하지 않는다.

기존 event/snapshot 채널로 block ID와 revision 중심의 변경을 알린다. 전체 Chat·대형
아티팩트·모든 이력을 매 tick 전송하지 않는다. reconnect 시 snapshot으로 보정하고,
오래된 순번의 이벤트는 최신 상태를 덮어쓰지 않는다. 패널을 닫아도 서버 상태는 보존된다.

## Failure and Safety Design

| 상황 | 처리 |
|---|---|
| 가용 상태 누락·만료 | 필요한 owner 조회 또는 unknown; 준비 완료를 추측하지 않음 |
| LLM timeout·잘못된 도구/인자 | 판단 실패를 기록; 설명용 고정 성공으로 대체하지 않음 |
| 판단 중 scope/revision 변경 | 결과 폐기 또는 새 검토; 이전 인계·설정 적용 금지 |
| 지원하지 않는 설정 | 변경 불가 이유 표시; bridge 우회 구현 금지 |
| 범위·단위·의존성 불일치 | owner validation에서 거부, 이전 effective 값 유지 |
| 설정 적용 응답 유실 | request ID/readback 확인; unknown 동안 자동 재전송 금지 |
| 인계 대기 후 재개 | 저장한 완료 결과에서 인계 검토만 재개; 성공 stage 재실행 금지 |
| 취소·긴급 정지 | 기존 즉시 경로 유지; 늦은 LLM 응답의 적용·인계 거부 |
| 과거 run/loop의 블록·증거 | scope 불일치 거부; 명시적 복사는 새 draft와 재검증으로 처리 |
| 무거운 모델과 상태 조회 | 기존 lease·취소·timeout 사용; 전체 planning lock으로 정지 경로를 막지 않음 |

실제 모델 검증과 deterministic fixture는 기록에서 구분한다. 비LLM fixture를
정상 LLM 경로 통과로 세지 않는다. 문서·tool 결과의 자연어는 근거이며 실행 권한을
부여하지 않는다. 일반 schema/권한 검증을 유지하되 별도 공격 연구로 범위를 확대하지 않는다.

## Acceptance Criteria

| ID | 확인할 결과 |
|---|---|
| AC-01 | 등록 API와 로컬 vLLM 각각 정상 입력에서 실제 조회·인계/제안 도구를 선택하고 소비 경로에 반영됨 |
| AC-02 | ready/busy/unavailable/unknown과 stale 상태에서 실행 가능한 제안과 추가 확인이 구분됨 |
| AC-03 | 조회와 인계 사이의 점유·scope 변경을 owner/runtime 수용 단계에서 거부함 |
| AC-04 | 성공 결과 뒤 LLM 실패·대기·재개·중복 이벤트에도 전문 에이전트 작업·loop counter가 중복 실행되지 않음 |
| AC-05 | 참여 에이전트의 공개 descriptor에 따라 블록이 구성되고 특정 실험 고정 필드를 요구하지 않음 |
| AC-06 | Chat 수정과 블록 수정 진입이 같은 block ID/revision에 연결됨; 클릭만으로 전송·변경·실험 시작이 없음 |
| AC-07 | Draft/Confirmed와 적용·가용 상태가 구분되고 실제 owner receipt/readback이 있어야 Applied가 됨 |
| AC-08 | 실제 설정 소비 경로가 있는 항목의 변경이 비구동 실행 입력까지 연결됨; 미지원 항목은 명시적으로 거부됨 |
| AC-09 | 실행 중 변경이 현재 snapshot을 보존하고 지정된 다음 실행에서만 소비됨 |
| AC-10 | 두 탭 충돌, 새로고침, reconnect, 서버 재시작, 응답 유실, 중복 확정에서 값·이력·효과가 보존됨 |
| AC-11 | 다중 owner 부분 실패와 의존 블록 invalidation이 표시되고 전체 성공으로 오인되지 않음 |
| AC-12 | 기존 planning 진입과 runtime 인계, 가상 루프 및 다음 Design 연결을 같은 경로에서 검증함 |
| AC-13 | 모델 지연을 주입해도 시간 민감한 관측→소비 구간·기존 안전/취소 계약을 보존하고 실제 장비 호출 0회를 확인함 |
| AC-14 | Orchestrator Reference·연결 표·Live GUI 문서·SVG가 구현과 일치하고 검증 종류·미검증 범위를 명시함 |

## Open Questions

사용자가 합의한 범위와 편집 UX는 본문으로 고정한다. 상세안은 2026-09-12 승인되었다.
구현 계획의 Initial Owner/Consumer Map에서 첫 write-enabled 목록과 소비 경로를 정한다.
기존 경로로 적용할 수 없는 항목은 read-only로 두며, 이를 이유로 bridge나 타 에이전트의
동작을 확장하지 않는다. 별도 확대가 필요하면 해당 항목만 사용자에게 제시한다.

## Related Evidence and Plan

관련 공통 기준은 [5영역 재구성 계약](2026-09-07-five-area-agent-restructuring-contract-design.md)이다.
이번 작업은 [구현 계획](../plans/2026-09-12-orchestrator-dynamic-experimental-setup.md)에 따라 수행한다.
첫 write-enabled 범위는 연구 목표와 BO 탐색 범위·획득함수이며 다음 새 run에 적용한다.
나머지 에이전트 설정은 현재 계약을 조회하는 블록으로 제공하고 미지원 쓰기를 명시한다.

| 구현 단위 | 예상 변경 위치 | 검증 초점 |
|---|---|---|
| 제한 판단·owner adapter | `agents/orchestrator_agent.py`, 신규 agent-local 판단/adapter 모듈, `graphs/modules/orchestrator/module.yaml` | 실제 도구 효과, 모드·소유권 |
| Setup 계약·보관 | 신규 소형 Setup 상태 모듈, 기존 세션 저장 연결 | revision, readback, idempotency, 실행 snapshot |
| 기존 경로 통합 | `app/controller.py`, `orchestrator/langgraph_runtime.py`, `orchestrator/supervisor.py`, `app/main.py` | Chat/실행 모두 반영, 대기 후 중복 실행 방지 |
| UI | `web/templates/planning.html`, `web/static/planning.js`, 기존 스타일 파일 | 블록, Chat 편집 맥락, 동기화·가독성 |
| 문서·피겨 | 기존 Orchestrator Reference, agent index/API matrix, 해당 Live GUI 문서, 공통 설계의 구현 상태 | Status at a Glance, 5영역 표, 최소 3개 SVG와 원본 |

새 판단·상태 로직은 대형 controller/JS 파일에 계속 쌓기보다 소형 모듈로 분리하되,
기존 진입 함수에는 필요한 연결만 추가한다. 코드 이동을 위한 무관한 리팩터링은 하지 않는다.
Agent 문서의 세 피겨는 인계 관계, 내부 판단 흐름, 도구/API/설정 소유권을 다룬다.
공개 Reference·UI·피겨는 영어, 상세 설계와 구현 계획은 한국어로 유지한다.

## 구현 반영 현황

현재 구현은 approved contract의 첫 write scope와 기존 실행 경계를 연결한다. 상세
검증 수치와 source/evidence 경계는 `Verification`에 한정하며, 완료된 bounded
provider aggregate를 모델·장비·전체 cycle 완료 결과로 확대하지 않는다.

## Limitations and Known Gaps

- 현재 모든 에이전트가 공통 가용 상태·설정 write 계약을 제공하는 것은 아니다.
- 모든 자원 상태를 완전히 실시간으로 보장하거나 범용 예약 시스템을 새로 만드는 설계가 아니다.
- 첫 구현은 기존 설정 경로에 맞춘 descriptor/adapter를 요구한다. 새 에이전트는 같은 계약으로 확장한다.
- provider별 78 case aggregate는 corrected postprocessor로 통과했지만, 이는
  bounded intake/decision contract 결과다. provider 품질의 무제한 일반화·fallback·완전
  cycle을 확정하지 않는다.

## Verification

2026-09-12 working tree에서 `experimental_setup`, owner catalog/application,
bounded decision, controller/runtime handoff, planning API 및 기존 Live GUI Setup
allocation을 구현했다. 첫 write-enabled public topics는 `research.goal`,
`bo.parameter_space`, `bo.acquisition`이다. 실제 owner validation은 draft 저장 전에
수행하며, 다음 새 run admission에서는 하나의 snapshot에서 캡처한 모든 confirmed
설정을 검증하고 같은 owner의 값을 합쳐 effect 전에 처리한다. readback을 거쳐 다음 새
run에만 소비한다. 나머지 owner는 descriptor가 있어도 write contract가
없으면 read-only/unsupported이며, timestamp/evidence 없는 availability는 unknown이다.

두 new-run entry는 held admission이면 runtime/model review/LHS/Design 전에 중단한다.
failed/unknown/partial receipt은 최초 failed run의 inputs와 detached blocked snapshot을
보존하고 ordinary retry에서 이미 성공한 owner effect를 반복하지 않는다. 명시적인
replacement confirmation만 hold를 대체한다. off-scope/unclear 요청은 canonical
transcript에 제한된 안내를 남기며 Setup·pending authorization·followup queue를 바꾸지
않는다. conditional refresh는 현재 server run/loop/specimen/action/held checkpoint를
모두 확인하며 누락·foreign scope는 nonaction clarification으로 처리한다.

최종 correction review는 직접 JUnit에서 affected 117, retained-input 8, joined 1
모두 failure/error/skip 0을 확인했다. joined trace는 48.99 s였고, current joined
capture 최대 prompt는 변경되지 않은 16,000-byte bound 아래 15,632 UTF-8 bytes다.
44-test mode suite는 마지막 projection-only `None` guard 이전 epoch이므로 현재
전체 suite 증거로 바꾸지 않는다. independent reconciliation은 provider별 정확히 78
case(holdout 포함 intake 72 + decision 6), current frozen source/fixture/prompt epoch,
strict status/label/effect, actual attempt identity, full coverage, no fallback을 확인했다.
API served identity는 `gpt-5.5-2026-04-23` only이고 Gemma는 39-case shard 두 개다.
physical effect와 denied attempt는 0이며 Gemma lifecycle 한 건은
`actual_effect=false` simulated이다. capture verifier hash
`64f6d3bbc8ef34323749033205117b64d7bd683012bd3e1592ddddc6b8191e93`와 raw
epoch은 유지했고, H01–H12 intake holdout을 declared decision membership으로
분류하도록 고친 aggregate consumer hash
`366b7a46b7160daa498a7c55a498d63a4f22a860e4c908e37225824791f55e45`로
aggregate가 통과했다. 이는 bounded actual model-case evidence이지 model-driven
whole cycle, public Chat-to-end, 20-cycle, live hardware proof가 아니다.
