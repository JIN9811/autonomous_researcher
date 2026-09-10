---
doc_type: design
subtype: architecture
status: review
authority: proposal
audience: [developer, maintainer, researcher, reviewer]
scope: [closed_loop_agents, agent_restructuring, reasoning_tool_contract, agent_documentation]
summary: 모든 에이전트의 정상 경로에 역할에 맞는 국소 LLM 의사결정층을 두고, 기존 실행·문서·표·SVG·검증을 함께 보존하는 5영역 재구성 계약.
decision_status: proposed
related_docs:
  - docs/runtime/three_level_control_model.md
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/standards/documentation_standard.md
  - docs/standards/paper_documentation_standard.md
  - docs/templates/document_types.md
  - docs/runtime/loop_artifact_archiving.md
  - docs/superpowers/specs/2026-09-09-analysis-multifidelity-decision-design.md
  - docs/paper/evidence/2026-09-07-latest-cycle-demonstration.md
supersedes: []
---

# 에이전트 5영역 재구성 통합 계약 설계

## Summary

이 문서는 **에이전트 재구성 자체의 공통 계약**이다. 문서 정리만을 위한
별도 규칙이 아니며, 각 에이전트의 구조·LLM 판단·툴 호출·기존 Reference·표·SVG·검증을
하나의 완료 단위로 묶는다.

**LLM은 모든 에이전트의 정상 유효 작업 경로에 참여한다. 다만 에이전트 내부 전체
실행 경로가 아니라, 그 전문 역할에 맞는 일부 의사결정층만 담당한다.**
입력 정규화·정형 계산·장비 실행·필수 검증·보관을 매 단계 LLM 호출로 바꾸지 않는다.
예외 때만 LLM을 호출하는 구조도 목표가 아니다. 의사결정층은 새로운 여섯 번째 계층이나
별도 에이전트가 아니라, 기존 책임 영역 안에서 실제 선택권을 가진 논리적 구간이다.

핵심 완료식은 다음과 같다.

**한 에이전트 재구성 완료 = 실제 판단/툴 실행 구현 + 기존 인계 호환성 +
5영역 Reference + 계약 표 + SVG/원본 + 검증 근거.**

사용자가 합의한 방향을 상세 계약으로 정리한 검토안이다. 이 문서 작성은 에이전트
구현이나 전체 사이클 변경 승인이 아니다. 적용은 한 에이전트씩 별도 확인 후 진행한다.

## Problem

기존 코드에는 역할·입출력·툴·브릿지 경계가 있지만, 여러 LLM 호출은 실행 선택에
영향을 주지 않는 설명 메모 생성에 머문다. 반대로 `agentic`, `reasoning`이라는
화면 단계명만으로 실제 모델 판단·툴 실행이 존재한다고 해석할 위험이 있다.

에이전트 내부 판단권을 확대하면서도 기존 실행 경로를 보존하려면, 코드만이 아니라
문서와 검증에서도 **모델이 결정하는 것 / 코드가 강제하는 것 / 실행기가 수행하는 것**이
일치해야 한다. 문서 갱신은 재구성 이후의 선택 작업이 아니라 완료 조건이다.

## Goals and Non-goals

### 목표

- High-Level, Middle-Level, Low-Level, Guardian / Safety, Knowledge / Evidence를 모든 에이전트에 적용하는 공통 책임 계약으로 사용한다.
- 각 에이전트의 정상 유효 작업 경로에 역할 적합성이 설명되는 LLM 의사결정층과 의미 있는 툴 호출을 둔다.
- 맥락·상충 근거·불확실성을 종합하는 판단과 정형 계산·필수 실행을 분리한다. LLM의 선택은 실제 후속 작업에 반영한다.
- 기존 함수·등록 툴·Skill·브릿지·런타임·아카이브를 우선 사용한다.
- 기존 `docs/agents/*_agent.md`는 역할·흐름 중심 목차로 정리하고, 같은 다섯 영역의 책임을 대응표로 연결한다.
- 구현, 표, 피겨, 검증의 대응 관계를 에이전트별로 확인한다.
- 미변경 에이전트와 변경된 에이전트가 기존 계약으로 함께 동작하게 한다.

### 이번 설계에서 하지 않는 일

- 모든 에이전트의 동시 구현, 런타임/브릿지 교체, 그래프 경로 전면 변경.
- 다섯 실행 stage, 다섯 하위 에이전트, 다섯 프로세스의 의무 생성.
- 전체 내부 단계를 LLM이 스케줄링하는 범용 루프로 교체하거나 단순 계산·고정 순서까지 모델 선택으로 포장하기.
- 임의 shell/Python 실행, 자유로운 장비 명령 생성, 기존 안전 인터록 해제.
- 캠페인·슬롯·새 설정 연동 시스템 등 이번 요청 밖의 기능 재도입.
- 열 개의 중복 Reference 신설, 기존 문서 일괄 이동·폐기.
- 실제 장비 구동, 운영 서버 재시작, 과거 실증의 새 구현 실증으로의 전용.

## Current Context

- 보호 기준점: `closed-loop-stable`, 커밋 `ef4a996c3faf201b01078cf33cd5e485891b0218`.
- 기존 계층 정의: `docs/runtime/three_level_control_model.md`.
- 기존 진입점: `docs/agents/README.md`, 각 Agent Reference, API/Connection Matrix.
- 기존 실행 경계: `AgentContext`, 등록 툴, `AgentResult`, LangGraph/controller의 상태·인계 처리.
- 기존 보관: run/loop/agent/attempt 단위 아티팩트 및 이벤트.

현행 코드 조사에서는 Design의 LLM 검토 메모, Analysis 요약, Guardian의 정책 메모와
실제 계산·결정 분기가 분리되어 있었다. BO의 일부 후보 평가 및 Equipment의 조건부
계획·복구에는 실제 선택 참여가 있다. 각 에이전트 착수 시 해당 기준을 다시 확인한다.
현재 기능으로 간주할 근거는 코드와 실행 기록이지 문서의 단계 이름이 아니다.

## Options Considered

| 방식 | 장점 | 한계 | 선택 |
|---|---|---|---|
| 문서 제목만 다섯 영역으로 변경 | 변경량이 작음 | 실제 판단·툴 호출 재구성을 보장하지 못함 | 제외 |
| 전체 에이전트와 공통 런타임을 한 번에 교체 | 일괄 통일 가능 | 기존 실증 경로 훼손과 원인 분리 위험, 요청 범위 초과 | 제외 |
| 공통 통합 계약 아래 에이전트 하나씩 재구성 | 기존 경계 보존, 개별 검증, 문서와 구현의 동시 완료 | 전환 기간에는 구현 상태가 서로 다름 | 채택 제안 |

## Decision

**5영역 통합 계약을 먼저 검토하고, 에이전트별로 분석 → 변경 범위 확인 → 구현 →
문서/피겨 갱신 → 검증 → 사용자 확인 순으로 적용한다.** 한 에이전트 검증을 위해
다른 에이전트 전체를 먼저 바꾸어야 하는 설계는 채택하지 않는다.

다섯 영역은 책임 구분이다. High/Middle/Low는 제어 계층이며 Guardian/Safety와
Knowledge/Evidence는 이 계층들을 가로지르는 공통 영역이다. 다섯 영역을 순서대로
한 번씩 실행해야 한다는 뜻이 아니다.

2026-09-07 보정: **모든 에이전트에 LLM 판단층이 있어야 한다는 조건은 유지한다.**
이를 모든 내부 단계의 LLM화나 예외 전용 LLM으로 해석하지 않는다. 각 에이전트는 먼저
자기 역할에서 LLM에 적합한 의사결정 문제를 정의하고, 그 경계에만 판단·툴 호출을 배치한다.

## Architecture and Contracts

### 1. 다섯 영역의 책임 계약

| 영역 | 주된 책임 | LLM의 역할 | 기존 코드/실행기의 역할 | 경계 |
|---|---|---|---|---|
| High-Level Control | 목표·위임·인계·사이클 진행 | 허용된 작업 위임, 결과 검토, 추가 작업/진행/상위 검토 판단 | 실행 가능한 경로, 상태 전이, 식별자와 인계 계약 적용 | 전문 에이전트를 건너뛰어 브릿지 직접 제어 금지 |
| Middle-Level Control | 담당 작업의 수행 전략 | 상태를 보고 툴·인자를 선택하고 반환 결과로 다음 행동/완료 판단 | 입력 검증, 계산, 계약 검사, 실행 예산 강제 | 다른 에이전트의 설정·산출물 소유권 침범 금지 |
| Low-Level Control | 단일 요청 실행·관측 | LLM을 의무 배치하지 않음 | 기존 함수·툴·서비스·Skill·브릿지·VLA/solver 실행 | 연구 목표나 다음 에이전트를 임의 변경하지 않음 |
| Guardian / Safety | 위험 판단과 실행 제한 | 근거 조회, 불일치 판단, 보류/검토/정지 요청 등 실제 판단 | 하드 제한·기존 승인·인터록·긴급 정지 강제 | 모델 허용으로 코드/장비 차단을 무효화할 수 없음 |
| Knowledge / Evidence | 근거 제공·지식 갱신·이력 보존 | 검색 대상/분류/기억 내용 선택, 근거 기반 해석 | 원시 기록 자동 저장, 출처·스키마·정체성 검증 | 가설을 측정 사실로 저장하거나 타 에이전트 설정 직접 변경 금지 |

각 Agent Reference는 다섯 영역을 모두 설명하되, 직접 소유하지 않는 영역에서는
연결 대상과 계약만 기록한다. Guardian과 Knowledge도 자기 전문 작업의 판단–툴–관측
루프를 갖지만, 이를 위해 별도의 Guardian/Knowledge 복제 에이전트를 만들지 않는다.
High 담당 에이전트는 High의 위임 판단에, Middle 담당 에이전트는 전문 작업 판단에,
Guardian/Knowledge 에이전트는 각자의 검토·지식 판단에 LLM을 둔다. 모든 에이전트의
다섯 영역 각각에 모델을 배치하거나 모든 결정권을 Middle로 옮긴다는 뜻이 아니다.

### 2. 공통 실행 계약

![Proposed five-area agent restructuring contract](assets/five_area_agent_contract.svg)

**Figure Contract-1.** Proposed architecture: deterministic preparation feeds a
role-owned LLM decision layer on the normal task path. Only that bounded layer
selects meaningful actions/tools and interprets observations; existing execution,
mandatory checks and handoff remain code-owned. Its owner is High, Middle,
Guardian or Knowledge according to the agent, not an additional control level.
The lower acceptance box is a development-completion contract, not a runtime stage.
This design figure is not evidence of implemented or live-validated behavior.

| 단계 | 계약 |
|---|---|
| 작업 수신 | 목표·필수 입력·제약·기존 run/loop/specimen/attempt 정체성을 확보한다. 결손 입력은 명시적으로 반환한다. |
| 근거 구성 | 기존 코드가 입력 정규화·기본 계산·필수 사전 검사를 수행할 수 있다. 그 결과와 필요한 관측·이전 결과·지식·허용 툴 스키마를 판단층에 제공한다. 툴 출력/외부 문서는 근거이지 실행 권한이 아니다. |
| 모델 판단 | 정상 작업에서 역할에 맞는 판단층을 거친다. 모델이 근거를 종합해 채택/추가 확인/허용된 수정/상위 반환 등 해당 역할의 행동과 툴·인자를 선택한다. 전체 실행 단계의 스케줄링은 맡기지 않는다. |
| 요청 검증 | 허용 툴, 인자 타입·범위, 입력 정체성, 기존 승인·안전 조건을 검사한다. 자유 텍스트를 임의 실행하지 않는다. |
| 기존 기능 실행 | 검증된 요청만 기존 구현으로 전달한다. 실행 중이면 기존 상태 조회 경로를 사용한다. |
| 결과 관측 | 구조화된 성공/실패/진행 중/결과 불명 및 아티팩트 참조를 반환한다. 추가 판단이 필요한 관측은 같은 판단층에 돌려준다. 판단이 끝난 후의 정형적 패킷 생성·보관 성공마다 모델을 다시 호출하지 않는다. |
| 완료 확인 | 모델의 완료 주장과 필수 결과·증거를 대조한다. 호출 성공만으로 물리 작업/분석 완료를 선언하지 않는다. |
| 인계 | 기존 `AgentResult`와 인계 필드로 반환한다. 다음 stage 변경은 기존 High/runtime 경계가 적용한다. |

툴 호출은 native function calling 또는 검증 가능한 구조화 출력으로 구현할 수 있다.
형식보다 중요한 것은 **모델이 만든 판단·툴 선택·인자가 실제 실행에 반영되고,
추가 판단이 필요한 결과가 모델에 다시 제공되는가**이다. 전용 provider SDK나 새 전역
프레임워크 도입은 필수가 아니다. 위 표는 경계 계약이며 모든 내부 함수 앞뒤를 모델로
감싸라는 호출 순서 명세가 아니다.

기존 순수 계산 함수를 agent-scoped tool로 노출할 수 있지만, 등록명·범위·스키마는
해당 에이전트 설계에서 기존 등록 방식을 확인한 뒤 확정한다. 존재하지 않는 툴을
현재 등록된 API로 문서화하지 않는다. 검증된 Skill/Flow를 통째로 선택·호출하는 것도
유효한 툴 호출이며, 안정화한 내부 클릭·모션을 LLM으로 다시 생성할 필요는 없다.

### 3. 의미 있는 LLM 관여의 판정

#### 역할과 LLM의 적합성 계약

에이전트별 구현에 앞서 다음 내용을 해당 Reference의 Middle 영역
`LLM Reasoning and Decision Authority`에 적고, 실제 소유 영역이 High/Guardian/Knowledge면
그 영역의 책임 설명과 연결한다.

| 항목 | 반드시 설명할 내용 |
|---|---|
| 판단 문제 | 이 에이전트의 전문 역할에서 모델이 답해야 할 구체적인 질문 |
| 판단 근거 | 목표·관측·계산·과거 기록과 출처, 결손/불확실성 |
| LLM 적합성 | 맥락 해석·상충 근거 종합·추가 확인 선택 등 모델에 맡기는 이유. 단순 산술·타입 검사로 충분한 부분과 구분 |
| 실제 선택권 | 허용된 행동·툴·인자와 각 선택이 바꾸는 후속 작업. 형식적인 승인·고정 행동 설명만으로는 부족 |
| 고정 경계 | 다른 에이전트 소유 변수, 사용자 확정 조건, 필수 계산·실행·검증, 변경 금지 항목 |
| 정상 경로 위치 | 판단층의 입력 시점, 결과 소비 지점, 필요한 경우만 되돌아오는 관측 경로 |
| 검증 방법 | 정상 채택과 다른 근거에서의 추가 확인/상위 반환 등 판단 차이가 실제 실행에 반영되는지 검사 |

선택의 개수나 툴 호출 횟수 자체는 기여가 아니다. 가능한 판단이 없는 고정 작업에
더미 선택지를 만들지 않는다. 전체 에이전트의 역할에서 적합한 판단 경계를 찾지 못하면
그 문제를 사용자와 재검토하며, 예외 전용 호출이나 의미 없는 승인으로 완료 처리하지 않는다.

#### 관여 판정

| 구분 | 판정 |
|---|---|
| 코드가 정한 실행을 마친 뒤 설명 메모만 생성 | 설명용 호출. 재구성 완료 조건을 충족하지 않음 |
| 실행과 무관한 더미 툴을 형식적으로 한 번 호출 | 충족하지 않음 |
| 결과와 무관하게 같은 실행을 하는 형식적 승인 | 충족하지 않음. 선택의 실제 효과와 근거 의존성이 필요 |
| 예외 때만 LLM을 호출하고 정상 유효 작업은 기존 고정 실행만 수행 | 부분 구현. 정상 작업의 판단 참여 조건은 미충족 |
| 정상 경로의 일부 판단층에서 근거를 종합하고 실제 행동/툴을 선택하며 필요시 결과를 재판단 | 목표 구조. 역할 적합성과 계약·검증 근거 필요 |
| 모든 내부 계산·고정 실행 순서를 모델이 하나씩 지시 | 목표가 아님. 국소 판단층 밖의 기존 실행을 유지 |
| 이미 유효하게 완료된 작업, 사전 차단, 운영자 취소, 상태 polling | 불필요한 LLM 호출을 강제하지 않음. 무호출 사유를 기록 |

기존 행동이 안전하고 충분하면 모델이 동일한 선택을 하는 것은 정상이다. 모델 관여를
증명하기 위해 불필요한 선택지·호출·재시도를 늘리거나 매 polling마다 추론하지 않는다.
결정론적 대체 실행은 사용 여부와 이유를 구분해서 기록하며 LLM 경로 검증으로 세지 않는다.
명시적인 비LLM 테스트 모드는 재현용으로 구분할 수 있으나, 이를 정상 LLM 작업 경로의
검증으로 대체하지 않는다. 모드별 기존 정책 변경은 개별 설계에서 확인한다.

### 4. 에이전트별 적용 범위와 문서 소유권

아래는 분석 초점과 보존 경계이며, 개별 툴 스키마나 변경 구현을 미리 확정하는 표가 아니다.

| 에이전트 | 주된 판단 영역 | 재구성 시 분석할 판단/툴 경계 | 보존할 전문 실행 | 갱신할 기존 Reference |
|---|---|---|---|---|
| Orchestrator | High | 위임·조회·추가 작업·진행 판단 | 기존 graph/runtime와 인계 | [Orchestrator](../../agents/orchestrator_agent.md) |
| Design | Middle | 목표·상위 요청·설계 검증·실험 근거를 종합한 설계 채택/추가 확인/허용된 수정/상위 반환 | BO/LHS 지정점·사용자 조건, 후보 생성·형상·제약·점수 계산, 기존 인계 | [Design](../../agents/design_agent.md) |
| Specimen Making | Middle | 제작 준비·작업 선택·완료 근거 검토 | 슬라이싱·전송·프린터·이젝션 | [Specimen](../../agents/specimen_agent.md) |
| Vision | Middle | 관측/검증 요청·해석·재관측 | 카메라·검출·좌표·freshness 검증 | [Vision](../../agents/vision_agent.md) |
| Manipulation | Middle 중심, High 판단 | LLM의 기존 Skill 적합성·툴 선택과 Vision 이후 결과 판단 | 기존 LeRobot/VLA·고정 replay·종료 경로 유지 | [Manipulation](../../agents/manipulation_agent.md) |
| Lab Equipment | Middle | 저장 Skill/Flow 선택·결과 확인·제한된 복구 | 기존 장비 Skill·worker·통신 | [Equipment](../../agents/equipment_agent.md) |
| Analysis | Middle | 분석/검증/해석 툴 선택·결과 채택 | 파서·단위·지표 계산·solver | [Analysis](../../agents/analysis_agent.md) |
| BO | 내부 High + Middle | 전략·근거 조회·수치 진단·결과 인계 판단과 제한된 툴 호출 | 좌표는 LHS/BoTorch, 목적함수·사용자 고정값·기존 그래프는 보존 | [BO](../../agents/bo_agent.md) |
| Guardian | Guardian/Safety | 근거 조회·위험 판단·허용/보류/정지 요청 | 기존 코드 gate·하드 인터록 | [Guardian](../../agents/guardian_agent.md) |
| Knowledge | High + Knowledge/Evidence | 근거 평가·분류·범위 검색·MD 갱신 툴콜링 | 온톨로지·출처·스코프·수명주기 검증·원본 보존 | [Knowledge](../../agents/knowledge_agent.md) |

Analysis의 세 LLM 역할, 지표 유지·제거, 실험 기반 모델/방법 개선, 메쉬 평가와
실제 필드 컨투어에 관한 후속 제안은
[Analysis 멀티피델리티 상세 설계](2026-09-09-analysis-multifidelity-decision-design.md)에 정리한다.
이는 미구현 검토안이며 외부 Analysis stage나 기존 장비 실행 경로 변경을 의미하지 않는다.

#### Design 우선 재검토 — 구현 전 검토안

검토 기준은 현재 [Design 코드](../../../agents/design_agent.py),
[모듈 정의](../../../graphs/modules/design/module.yaml),
[controller](../../../app/controller.py), [기존 테스트](../../../tests/unit/test_design_agent.py)다.
아래는 현재 구현과 제안을 구분한 첫 적용 대상 검토이며, 구현 승인이 아니다.

| 현재 확인한 지점 | 재구성에 주는 의미 |
|---|---|
| `_deterministic_design_payload()`가 근거 수집·후보 생성·검사·점수순 선택·보고서/인계를 모두 수행 | 이 함수를 통째로 호출하는 LLM wrapper는 기존 코드의 선택을 그대로 실행할 뿐이다. 후보/근거 준비와 최종 확정 사이에 판단 경계를 둬야 함 |
| `run()`의 `design_reasoning`은 이미 선택된 후보의 위험/전략 메모만 요청 | 메모 호출을 실질적 판단층으로 대체할 지점. 현재 메모는 후보 선택권이 없음 |
| `_resolve_constraints()`는 BO 추천과 `orchestrator_design_contract.requested_parameters`를 반영 | 상위 지정 변수는 판단층의 읽기 전용 조건. 실험점 재최적화는 Design의 역할이 아님 |
| `_estimate_candidate()`의 목적값·불확실성·정보량은 수식 기반 proxy | 이름만 보고 측정값·학습된 posterior로 해석하면 안 됨. LLM 입력에 근거 종류와 한계를 명시해야 함 |
| `_attach_candidate_preview_artifacts()`는 코드에서 `geometry.generate_metamaterial_stl`을 호출하지만 모듈의 `tools` 목록은 비어 있음 | 기존 계산/미리보기 기능이 없는 것이 아니라 모델이 선택하는 툴 계약이 없는 상태. 실제 사용 기능과 선언·문서의 일치를 개별 구현에서 확인 |
| controller의 `_run_planning_design_stage()`는 반환 후 `_build_planning_spec()`과 기존 모드 정책을 적용 | 클래스 단독 결과뿐 아니라 controller 처리 후 최종 인계가 LLM 판단 대상·상위 조건과 일치하는지 검증해야 함. controller/모드 정책을 임의 제거하지 않음 |

**권장 판단 문제:** 상위에서 요청한 실험점을 구현한 설계가 목표·제작성·기존 실험
근거에 비추어 채택 가능한가, 아니면 무엇을 더 확인하거나 어떤 문제를 상위에 반환해야 하는가?

기존 코드로 조건과 후보/검사 근거를 준비한 뒤, **최종 후보 확정 및 authoritative
인계 생성 전**에 국소 판단층을 둔다. LLM은 정상 경로에서도 이 질문을 판단하며,
필요하면 후보 상세/관련 근거 조회 또는 기존 검사·형상 보고서 생성 기능을 툴로 요청한다.
이미 있는 동일 검사를 LLM 참여 증명만을 위해 반복하지 않는다. 추가 결과는 같은 판단층에
돌려주고, 최종 결정이 내려지면 기존 코드가 검증·보고서·인계·보관을 수행한다.

| 허용할 판단 | 조건과 실행 효과 |
|---|---|
| 설계 채택 | 검증된 후보 식별자와 근거로 최종 확정을 요청. 후보 내용은 저장된 결과에서 가져오며 모델이 임의 수치로 덮어쓰지 않음 |
| 추가 확인 | 결손/상충 근거와 목적을 명시해 필요한 기존 조회·검사 툴을 호출하고 결과를 재판단 |
| 허용된 수정·재생성 | 상위에서 변경을 허용한 Design 소유 변수와 지원 함수가 확인된 경우에만 가능. BO/LHS 변수나 사용자 고정 조건은 변경 불가; 수정 자유도가 없으면 이 선택을 노출하지 않음 |
| 상위 반환 | 충족 불가 조건·근거 부족·소유권 밖 문제를 근거와 함께 반환. 새로운 장비 실행이나 BO 재최적화를 직접 시작하지 않음 |

LLM 적합성은 단순 수치 크기 비교가 아니라 **서로 다른 근거의 관련성·충분성과
목표 대비 절충을 해석해 후속 행동을 정하는 것**에 있다. 하드 제약의 판정은 코드에
남는다. 과거 기록이 없으면 없다고 제공하고, 모델이 가상의 실패 사례로 보류하지 않도록
결정 근거 참조를 남긴다. 구체적인 툴 등록명·입력 스키마는 아직 확정하지 않았다.

현재 후보가 모두 거절되면 보수적 seed를 넣는 분기에는 같은 필터를 다시 적용하는
호출이 없다. 따라서 향후 채택 계약에서는 원 후보와 수정 후보 모두 검증 근거가 있어야
한다는 점을 검토해야 한다. 이번 문서 갱신으로 기존 fallback이나 실행 흐름을 바꾸지는 않는다.

### 5. 문서 계약은 구현 계약의 일부

각 에이전트 재구성은 **기존 Reference 파일 자체를 갱신**한다. 별도 목표 문서만
추가하고 기존 Reference를 낡은 상태로 남기면 미완료다. 현재/제안/검증 완료 상태를
분리하며, 미구현 내용을 active Reference의 현재 기능으로 쓰지 않는다.

Agent Reference는 **역할 → 실행 흐름 → 판단 → 인터페이스 → 운영 → 안전 → 근거**의
독자 중심 순서로 구성한다. 다섯 영역은 책임 분류이며 H2 목차나 실행 순서로 강제하지
않는다. Overview에 다섯 영역의 책임·외부 소유권·상세 절 링크를 담은 대응표를 둔다.
기존 세부 API·연결·설정·오류·근거 정보는 해당 주제의 독립 절에 보존한다.
메타데이터는 기존 front matter 규칙을 유지하며 별도 제어 계층을 추가하지 않는다.

```text
# <Agent Name> Reference
## Status at a Glance
5~7줄의 짧은 상태 항목: 구현 / LLM 검증 / 물리 효과 / 주 인계 / 장비 검증 / 핵심 미구현 사항
## Overview and Responsibilities
짧은 요약 / 하는 일·하지 않는 일 / 5영역 책임·상세 절 대응표
## Closed-Loop Position and Handoffs
SVG 1 / 입력·출력·호출·인계 계약
## Internal Workflow
기존 실행 순서 / 구현 함수 / SVG 2 / 완료·상위 반환
## Decision and Evaluation
LLM 판단 문제·선택권 / 평가 항목 / 근거·이력의 해석
## Tools, APIs and Connections
툴 인자·결과·효과 / 요청 스키마 / SVG 3 / API·연결 대상
## Configuration and Operation
설정 소유자·출처·적용 시점 / 모드 차이 / GUI
## Safety and Recovery
검증·승인 / 오류·재시도·취소 / 기존 안전 경계
## Artifacts and Verification
산출물·저장 / 검증 상태 요약 / 한계 / 출처·관련 문서
```

상단 `Status at a Glance`는 제목 바로 아래에 두고, 다음 여섯 항목을 기본으로 한다.
각 항목은 한 줄의 `Label: Value` 형태로 작성한다. 독자는 본문을 내려가기 전에
현재 구현·검증 범위와 주요 인계를 파악할 수 있어야 한다.

```text
Runtime status: <Implemented / Partially implemented / Planned>
LLM decision layer: <implementation state / verified scope>
Physical effect: <None / actual effect through the owning executor>
Primary handoff: <actual contract → consuming agent or runtime>
Live hardware validation: <Verified scope / Pending / Not applicable>
Known gap: <most important current gap, or None identified within the verified scope>
```

- [Design Reference](../../agents/design_agent.md)를 작성 형식의 기준으로 삼되,
  Design의 상태값·모델 검증·무장비 특성을 다른 에이전트에 복사하지 않는다.
- 장비 에이전트는 실제 동작 가능성을 명시한다. 가상 테스트만 했다는 이유로
  `Physical effect: None`이라고 쓰지 않는다. 비장비 에이전트는 자체 장비 검증과 downstream 검증을 구분한다.
- 구현 상태와 검증 상태는 구분한다. 설명용 LLM 호출만 있으면 실제 의사결정층이
  구현·검증된 것으로 표시하지 않는다. `locally verified` 등의 범위는 하단 검증 근거와 일치해야 한다.
- 지연 수치·상세 시험 조건·긴 한계 설명은 하단 Verification/Evidence에 둔다.
  상태 요약에는 핵심만 남기고, 문서 전체에서 같은 방어 문구를 반복하지 않는다.
  중요한 안전 조건은 Safety, 미검증 범위는 Verification에 상세히 유지한다.

- 같은 계약의 상세 설명은 한 절에만 둔다. 다른 절과 책임표는 링크로 연결한다.
- 표는 책임·인계·스키마·설정·검증 상태의 비교에, SVG는 실행·연결 관계에 사용한다.
  판단 이유·LLM 적합성·한계는 짧은 문장으로 설명하며 모든 문장을 표로 만들지 않는다.
- Reference는 현재 동작을 설명한다. 설계안은 목표 계약, 구현 계획은 작업·진행 상태,
  Evidence는 실제 검증 조건·결과·한계를 소유한다. 긴 실행 로그나 개발 과정은 Reference에 복제하지 않는다.
- 동일한 세 SVG와 편집 원본·stem을 재사용하고 해당 주제 절에 배치한다.
- 이번 적용은 Design Reference와 공통 작성 계약에 한정한다. 다른 에이전트는 자체 재구성 시
  적용하며, 문서 목차 변경을 근거로 런타임·모델·장비 경로를 바꾸지 않는다.

소유하지 않는 기능은 `Not owned`와 실제 담당자를 적는다. 비장비 에이전트의 Low는
계산·검색·저장 실행을 설명한다. 에이전트 Reference와 피겨는 영어로 작성하고,
이 한국어 설계안은 사용자 검토용으로 유지한다.

### 6. 필수 표 계약

| 영역 | 필수 표 | 열에 포함할 정보 |
|---|---|---|
| High | 책임·인계 표 | 책임자, 입력 생산자, 계약/필드, 소비자, 시작/완료 조건 |
| Middle | 단계·판단권 표 | 판단 문제, 정상 경로 위치, 사용 근거, LLM 적합성, 모델 선택권, 코드 고정 조건, 실제 적용 함수, 결과 |
| Low | 툴 표 | 실제 등록명, 입력 스키마/제약, 출력 상태, 구현/연결 대상, 부작용, 실행 전제조건 |
| Low | API·설정 표 | 소유/연결/공유 API, 방식, 설정 소유자, 기본값 출처, 적용 시점, 모드 차이 |
| Guardian/Safety | 실패·검증 대응 표 | 실패/차단 조건, 감지자, 허용 대응, 재시도 가능성, 정지/상위 요청, 필요한 근거 |
| Knowledge/Evidence | 근거·산출물 표 | 입력/출력, 종류, producer/consumer, 저장 패턴, 정체성, 원본/파생 구분 |
| Knowledge/Evidence | 검증 표 | 검사 항목, 입력/모드, 기대 결과, 실제 결과, 근거/커밋, 미검증 범위 |

설정은 값만 적지 않고 소유자·출처·허용 범위·적용 시점을 함께 기록한다. 실험별
치수·변형률·특정 장비 이름을 공통 계약의 고정값으로 두지 않는다. 실제 측정 사례의
값은 해당 evidence의 입력 조건으로만 명시한다.

### 7. 필수 SVG 계약

| 피겨 | 필수 내용 | 배치 |
|---|---|---|
| 1. Closed-loop position and handoffs | 해당 에이전트의 위치, 호출/인계, High/Middle/Low 및 공통 영역과의 관계 | Closed-Loop Position and Handoffs |
| 2. Reasoning and execution loop | 기존 전처리 → 국소 LLM 판단층 ↔ 필요한 툴/관측 → 기존 실행·완료의 경계. LLM 소유 영역, 정상 경로 참여, 조건부 반복, 안전·기록을 명시 | Internal Workflow; 판단·안전·근거 절에서 참조 |
| 3. Tool/API/connection architecture | 실제 툴·함수·서비스·브릿지/계산기, 요청/결과 방향, 부작용 발생 지점 | Tools, APIs and Connections |

- 재구성된 모든 Agent Reference는 최소 세 개의 실제 역할에 맞는 SVG를 갖는다.
- 기존 `.dot`/`.svg` 자산·stem·링크를 우선 재사용한다. 비장비 에이전트에 가짜 장비 연결을 그리지 않는다.
- 안전/지식 흐름이 복잡할 때만 전용 피겨를 추가한다. 다섯 영역마다 그림을 기계적으로 복제하지 않는다.
- 원본과 SVG는 `docs/agents/assets/figures/`에 함께 보관한다. 캡션·영문 라벨·편집 원본·재렌더링 일치를 필수로 한다.
- LLM 판단, 결정론적 검증, 실행, 관측/증거를 색 외의 텍스트·도형·선으로도 구분한다.
- 조건부/보조/제안 경로를 명시한다. 현재 기능을 나타내는 실선과 다른 의미를 범례로 설명한다.
- 단계명이 실제 별도 호출을 뜻하는지, 단순 표시/체크포인트인지 구분한다.
- 그림이 코드 검사 근거인지 테스트/실증 근거인지 캡션에 명시한다.
- 기존에는 일부 에이전트만 세 번째 피겨가 필수였다. 새 요구는 재구성 대상부터 적용하며,
  해당 자산을 추가할 때 기존 Standard·validator inventory·테스트도 같은 범위로 맞춘다.
  미변경 에이전트의 문서까지 일괄 교체하지 않는다.

### 8. 추적성과 기존 계약 보존

각 변경 패키지는 결정 지점 → 코드/툴 → Agent Reference의 영역/표 → SVG → 검증을
연결한 짧은 추적표를 가진다. 이 표는 해당 Reference의 Verification에 포함하며
별도 중복 문서군을 만들지 않는다.

외부 입출력과 인계 필드는 우선 유지한다. 판단 이벤트에 추가 정보가 필요하면 기존
이벤트·metadata·아카이브에 후방 호환되게 기록한다. 새로운 전역 저장 시스템이나
모든 에이전트가 동시에 따라야 하는 새 필수 스키마는 이 계약의 전제가 아니다.

문서의 기준 커밋·변경 상태·툴 존재 여부·API 소유권을 명시한다. 과거 모드별 동작을
이번 변경으로 묵시적으로 바꾸지 않는다. 구성의 경로·타입·안전 의미가 달라지는 부분은
해당 에이전트 작업에서 별도 합의하고 인접 계약 테스트를 포함한다.

## Failure and Safety Design

| 상황 | 계약상 대응 |
|---|---|
| 등록되지 않은 툴, 잘못된 인자, 권한 밖 요청 | 실행 전 거부. 제한된 수정 요청 또는 기존 실패/검토 경로로 반환 |
| 모델 시간 초과·잘못된 구조화 출력 | 남은 실행 예산과 기존 효과 상태에 따라 보류/실패/명시된 대체 경로. 성공을 꾸미지 않음 |
| 무한 호출·같은 관측의 반복 | agent-owned 호출/시간 예산과 무진전 조건을 적용. 임계값은 설정으로 관리 |
| 툴이 아직 실행 중 | 기존 작업 ID로 상태 확인. 새 실행 명령을 중복 전송하지 않음 |
| 물리 작업의 실행 여부 불명 | 자동 재전송 금지. 상태·증거 확인 또는 운영자 검토 |
| LLM은 완료라지만 필수 증거 없음 | 완료/인계 거부. 허용된 추가 관측 또는 상위 요청 |
| Safety hard block 또는 긴급 정지 | 모델 응답을 기다리거나 허용 판단으로 우회하지 않음 |
| 에이전트 내부에서 해결할 수 없는 목표/입력 문제 | 소유자/High에 반환. 브릿지나 다른 에이전트 설정을 직접 수정하지 않음 |
| 문서·외부 툴 결과에 실행 지시가 포함됨 | 관측/근거로 취급. 등록 권한과 상위 작업 계약을 변경할 수 없음 |

새로운 공통 승인 단계나 정상 사이클 차단 gate를 무조건 추가하지 않는다. 기존
안전 경계에서 필요한 검증을 재사용하고, 추가 제한이 꼭 필요하면 개별 변경에서 근거와
영향을 제시한다. Guardian의 전문 추론 추가가 긴급 정지 경로의 LLM 의존화를 뜻하지 않는다.

## Acceptance Criteria

### 에이전트 하나의 완료 조건

| ID | 통과 조건 | 근거 |
|---|---|---|
| AC-01 | 다섯 영역의 책임과 외부 소유권이 명확함 | 코드/계약과 Reference 대응표 |
| AC-02 | 정상 유효 작업의 국소 의사결정층에서 모델의 의미 있는 판단·툴 선택·인자가 실행에 반영됨 | 통제된 모델 응답 테스트 + 실제 모델 비구동 호출 기록을 구분. 예외 전용/설명 전용은 불충족 |
| AC-03 | 판단에 필요한 서로 다른 근거·툴 결과가 후속 작업/완료·상위 요청에 반영됨 | 정상 채택과 추가 확인/반환 분기 테스트, 요청/응답 연결. 임의로 비최적 선택을 강제하지 않음 |
| AC-04 | 잘못된 툴·인자·권한은 효과 발생 전에 거부됨 | 부정 테스트, 실행 호출 0회 확인 |
| AC-05 | 필수 증거 없이는 완료·인계되지 않음 | 완료 조건 테스트 |
| AC-06 | timeout·취소·예산·불명 효과·재시도를 명시적으로 처리함 | 실패 시나리오 테스트 |
| AC-07 | 기존 입출력·모드·인접 에이전트·루프 경로가 유지됨 | 기존 회귀 + 인접 계약 + 비구동 루프 연결 검사 |
| AC-08 | 해당 기존 Reference가 역할·흐름 중심 목차와 5영역 책임 대응표로 갱신됨 | 필수 표, 설정/API/툴 소유권, 출처·기준 커밋; 중복 설명 대신 상세 절 링크 |
| AC-09 | 최소 세 개의 피겨와 원본이 실제 구현에 맞음 | 임베딩/캡션/링크 검사, Graphviz 재렌더링 비교 |
| AC-10 | 결정·툴·결과·아티팩트가 기존 loop/attempt 기록에 연결됨 | 재조회·식별자·실패 기록 검사 |
| AC-11 | 관련 문서·검증 규칙과 링크가 동기화됨 | 해당 범위 문서/피겨 검사, 표↔코드 추적 확인 |
| AC-12 | 실장비 미검증과 코드/모델 테스트 통과가 구분됨 | 검증 상태표와 사용자 검토 |
| AC-13 | 해당 판단층의 역할·LLM 적합성·실제 선택권·고정 경계가 구체적임 | 역할 적합성 표와 코드/테스트 대응. 전체 내부 실행의 LLM화가 아님을 확인 |
| AC-14 | 타 에이전트/사용자 확정 조건을 모델이 임의 변경하지 않음 | 권한 밖 변경 거부 및 상위 입력 보존 테스트. Design에서는 BO/LHS 지정점 보존 포함 |

모의 모델 응답으로 dispatcher를 검사하는 것과 실제 모델의 툴 선택을 확인하는 것은
다르다. 비구동 검사에서는 실제 bridge actuation 없이 선택/결과 처리와 기존 경로를
확인하며, 이를 실장비 검증으로 표현하지 않는다. 실제 장비 검증은 별도 사용자 승인
후 수행하고, 수행 전에는 `hardware validation pending`으로 남긴다.

### 적용 단위

1. **분석:** 대상 에이전트의 현재 호출·입출력·효과·문서·피겨를 읽고 보존 경계를 기록한다.
2. **설계 확인:** 역할에 맞는 LLM 판단 문제·정상 경로 위치·실제 선택권·고정 경계, 사용할 기존 툴, 파일 변경 범위, 검증 항목을 사용자와 확인한다.
3. **구현:** 승인된 에이전트 범위만 변경한다. 공통 adapter가 필요하면 최소 범위와 비대상 회귀를 포함한다.
4. **문서 동시 갱신:** 해당 Reference·표·SVG·원본·변경된 연결 요약을 맞춘다.
5. **검증:** AC 항목별 근거와 미검증 범위를 남긴다. 기준 실증을 새 구현 결과로 재분류하지 않는다.
6. **사용자 검토:** 다음 에이전트로 넘어가기 전 결과를 확인한다. 커밋·푸시는 별도 지시에 따른다.

첫 대상 후보는 앞서 논의한 Design이다. 이 설계안은 Design 구현 착수를 자동 승인하지
않으며 나머지 순서를 일괄 확정하지 않는다. `closed-loop-stable` 태그는 이동하지 않는다.

## Open Questions

공통 틀에 남은 필수 선택은 없다. 이 상세안의 사용자 검토가 필요하다. 실제 툴 등록명,
에이전트별 파라미터 범위·예산값·모델 선택·구체적인 테스트 입력은 각 에이전트 구조를
확인한 후 해당 작업에서 확정한다. 이는 공통 계약의 빈칸이 아니라 개별 작업의 책임이다.

## Related Evidence and Plan

### Design 추가 인수 기준: 가상 폐루프 · API · Gemma4 31B

2026-09-07 사용자 요청으로 다음 통합 검증을 추가한다. **통과 전에는 통과로 기록하지 않는다.**

| 항목 | 통과 조건 | 검증 경계 |
|---|---|---|
| 기존 API | 현재 앱의 실제 HTTP API로 실행을 요청하고 상태·이벤트·아티팩트를 조회한다 | 운영 GUI는 재시작하지 않고 임시 서버 사용 |
| 실제 로컬 모델 | `gemma4:31b` 응답으로 Design의 판단 및 툴 호출이 실제 수행된다 | 모의 LLM·다른 모델로의 폴백은 통과 근거에서 제외 |
| 가상 폐루프 | Design → Specimen → Vision/Manipulation → Equipment → Analysis → Knowledge/BO → 다음 Design을 추적한다 | 장비는 가상/비구동 모드, 기존 에이전트와 그래프 경로 유지 |
| 피드백 | BO의 다음 요청값이 다음 Design의 요청/실현 파라미터로 연결된다 | 기존 직렬화 정밀도 이내 비교 |
| 증거 | API 응답, 모델 ID/판단 기록, 단계 결과, 루프별 아티팩트와 실패 원인을 보존한다 | 실장비 실증과 구분; 임시 설정/환경 차이 명시 |

현재 상태: **DesignAgent의 API 및 등록 vLLM 31B 응답·툴 호출·인계 검증은 통과,
가상 폐루프 인수 검증은 미완료**다. 실제 `DesignAgent.run`과 `AgentContext.complete`를
사용했으며 API는 6.34초, 31B는 12.11초에 후보 채택과 인계 생성을 완료했다.
31B 응답은 기본 E4B 연결 실패 후 기존 모델 폴백 경로로 얻었다. E4B 기본 모델이나
무폴백 실행 통과로 표현하지 않으며, 이번 확인에는 장비·프리뷰 툴을 연결하지 않았다.

검증은 ATR에 등록된 백엔드·모델 라우팅·기존 요청 옵션을 사용한다.
기본 Design 경로는 `gemma4:e4b-it-nvfp4`이며, 등록된 31B 경로의 응답만으로
Design의 기본 모델을 검증했다고 표현하지 않는다. 실행 조건과 확인 결과는
[등록 경로 검증 기록](../../paper/evidence/2026-09-07-design-gemma31b-virtual-api-verification.md)에 보존한다.

기존 [1사이클 실증](../../paper/evidence/2026-09-07-latest-cycle-demonstration.md)은
보존할 경로의 기준 근거이며 이 재구성의 검증 결과가 아니다. 이후 사용자 승인으로
Design에 한해 [구현 계획](../plans/2026-09-07-design-decision-layer.md)과
[5영역 Reference](../../agents/design_agent.md)를 적용한다. 타 에이전트의 일괄
재구성이나 장비 브릿지 변경은 이 작업에 포함하지 않는다.

### Specimen 추가 적용: 제작 적합성 판단과 기존 제작 도구 실행

2026-09-08 사용자 승인 범위는 **Design JSON 수신 → 코드 소유 형상/제작성 검사 →
국소 LLM 적합성 판단 → 툴 호출을 통한 기존 제작 실행**이다. 실제 장비 구동 없이
구현·검증하며, 기존 출력·이젝션·프리플라이트·완료 판정 경로를 보존한다.

| 영역 | 적용 계약 |
|---|---|
| High | 선택된 설계가 요청된 제작 의도에 적합한지 판단; 실행/근거 조회/상위 반환 |
| Middle | 기존 geometry/mesh/manufacturability 준비 뒤 제한된 판단 루프와 인계 생성 |
| Low | `execute_fabrication`은 기존 `experiment.evaluate → printer.prepare → provider` 호출 |
| Guardian / Safety | 엄격한 도구 인자, 현재 사양·모드·정지 재검사, 기존 장비 게이트; 모델 승인 우회 금지 |
| Knowledge / Evidence | 현재 제작 근거, 추정치와 측정치 구분, `specimen_decision.v1` 및 루프별 아티팩트 |

LLM 도구는 `inspect_fabrication_evidence`, `execute_fabrication`, `return_to_owner`로
제한한다. 실행 도구는 현재 시편 ID만 받으며 모델이 설계 변수, 프린터 모드,
연결 정보, 승인 또는 G-code를 고칠 수 없다. 등록 역할은 `specimen_reasoning`이다.
`executed`는 기존 콜백 반환을 뜻하고 물리 제작 완료를 뜻하지 않는다.

사용자가 추가 요청한 다중 흐름 검증은 LHS에서 인계되는 상위 요청 계약,
BO 재설계 권고, 사용자 재질/치수 제약, 가상·이젝션 전용·실제 출력·프로필 지정·
프리플라이트 경로를 포함한다. Specimen 내부에서 새 분기 파이프라인을 만들지 않고
기존 사양과 실행 설정으로 흡수한다. 미지원/결손 입력은 기존 소유자/실패 경로로
반환하며, 임의의 새로운 실험 종류를 자동 지원한다고 주장하지 않는다.

[구현 계획과 검증 기록](../plans/2026-09-08-specimen-decision-layer.md),
[현재 Specimen Reference](../../agents/specimen_agent.md)에 구현 상태를 기록한다.
이 적용은 타 에이전트 일괄 재구성이나 브릿지 내부 변경을 허용하지 않는다.

### Vision 구체화 — 기존 검증 경로 위의 제한된 멀티모달 판단 (2026-09-08 승인안)

**상태:** 승인된 설계에 따라 working tree 구현, 등록 API/vLLM fixture 검증과 최종
회귀 재실행을 완료했다. 기존 Vision 촬영·검출·freshness·rollout stop·UTM clear
계약을 유지하고, 그 전후에 제한된 JSON 도구 선택과 동일 촬영 근거 검토를 추가한다.
새 detector, 새 이미지 추론 서비스, 새 장비 명령 또는 그래프 변경은 범위 밖이다.

#### 판단 질문과 5영역

LLM이 답할 질문은 두 가지로 제한한다.

1. 현재 run/loop/specimen/session/task 맥락에 등록된 기존 검증 작업을 실행할 것인가.
2. 실행 후 같은 촬영에서 나온 원본·주석 이미지와 detector facts가 관측 주장을
   일관되게 지지하는가.

픽셀 검출, 좌표, ROI, confidence, threshold, calibration, 신호 수명, 모드,
승인 및 다음 stage는 코드 소유다.

| 영역 | Vision 책임 | 유지할 권한 경계 |
|---|---|---|
| High-Level Control | 현재 제한된 관측 계약의 적합성과 근거 충분성을 판단해 계속 또는 owner review 반환 | 전체 연구 목표와 graph route는 Orchestrator 소유; 물리 안전 선언 불가 |
| Middle-Level Control | 현재 맥락 투영, 제한 도구 디스패치, 기존 검증 결과와 판단 결합 | task resolver, 실행 순서, detector 판정과 최종 handoff gate 유지 |
| Low-Level Control | 기존 촬영, ActiveCam 이동·촬영·복귀, detector, artifact, rollout status/stop, managed-clear 작업 | bridge가 포트·pose·process/replay 상태와 명령 확인 소유 |
| Guardian / Safety | identity/mode/stop/lease/lifecycle/freshness/interlock/budget 및 hard gate | 모델이 실패 detector, 미확인 stop, stale signal, Guardian 판단을 덮어쓰지 않음 |
| Knowledge / Evidence | `vision_decision.v1`, tool trace, 이미지 hash/label, detector facts와 기존 report/signal 보존 | 과거·가상·mock·타 세션 근거를 현재 물리 증거로 승격 금지 |

#### 제한 도구와 공통 출력

모델 응답은 정확히 `tool`, `arguments`, 짧은 `reason`,
`evidence_refs` 네 필드만 가진 JSON이다. 모델은 bridge 이름이나 자유 인자를
만들지 않으며, 코드는 현재 `contract_id`에 대응하는 기존 callback만 노출한다.

| 로컬 도구 | 입력 | 효과 |
|---|---|---|
| `execute_verification` | 현재 `contract_id` | 등록된 기존 관측 루틴 하나 선택; 실제 인자와 모든 gate는 코드가 구성 |
| `accept_visual_evidence` | 현재 `contract_id` | 동일 촬영 원본·주석 이미지 및 detector facts를 현재 frame 근거로만 수락 |
| `return_to_owner` | 현재 `contract_id` | `review_required`로 반환; ready handoff나 추가 실행 없음 |

선택 단계는 `context:task`, 이미지 검토는 `frame:current`를 인용해야 한다.
미등록 도구, 인자 변경, 추가 필드, 모르는 evidence, mock 응답, 잘못된 JSON,
추론 도중 run/loop/specimen/session/task/mode 또는 metadata specimen scope 변경은
fail-closed이며 변경된 scope에 맞는 유효한 blocked observation을 반환한다.

#### 일반 멀티모달 전달 계약

기존 공통 `LLMImageInput`을 사용한다. Vision은 모델 인자가 아니라 등록된 capture
결과 경로에서만 이미지를 읽고, byte/pixel 제한과 raster 유효성을 검사하며, 같은
크기의 두 이미지를 다음 고정 순서와 label로 전달한다.

1. `raw frame`
2. `annotated frame`

OpenAI 호환 API와 vLLM payload에는 이미지 앞에 이 순서를 명시한 텍스트 label을
붙인다. `AgentContext.complete(..., images=...)`와
`ModuleRuntimeContext.complete(..., images=...)`는 같은 일반 image signature를
사용하고, module context는 LLM lease 경로와 설정된 fallback 모두에 같은 이미지
목록을 전달한다. 멀티모달 요청의 mock 응답은 시각 판단으로 인정하지 않는다.
이미지 안의 텍스트는 instruction이 아니라 신뢰하지 않는 evidence다.

#### 경로별 await 및 effect 순서

| 기존 경로 | 새 판단 위치 | 코드 소유 순서와 완료 조건 |
|---|---|---|
| Pickup | 기존 관측 전에 `execute_verification`, 촬영 후 동일 근거 검토 | 기존 capture/detector와 pickup gate가 통과하고 검토 종료 시 freshness가 유효해야 함 |
| ActiveCam ejection | 복합 루틴 전에 `execute_verification`, 촬영 후 동일 근거 검토 | **ActiveCam은 robot 이동 → 촬영 → 복귀/port release를 포함하는 physical-possible 루틴**. 모델은 pose/driver 인자나 자동 재실행을 만들 수 없음 |
| Manipulation placement | 진행 중 status/interlock/capture poll에는 LLM 없음; 기존 코드가 matching rollout stop을 canonical STOPPED로 기록한 뒤에만 이미지 검토 await | 승인 전까지 `needs_post_place_vision` / `stopped_pending_visual_review`를 보존하고, 같은 session의 기존 STOPPED 결과는 stop 재호출 없이 재사용 |
| Post-test clearance | managed replay 완료와 measured-home 복귀가 확인된 뒤, done 이전 fresh Verification 2 이미지 검토 | replay 진행/취소/timeout/stop에는 LLM 없음; detector clear와 기존 registration/freshness/material gate 유지 |

필수 안전 정지·취소·timeout·cleanup은 모델 응답을 기다리지 않는다. 특히 모델은
`replay.start`를 선택하거나 임의 rollout/robot 명령을 만들 수 없다. 이미 완료된
물리 효과는 늦은 모델 응답이나 실패 때문에 되돌리거나 중복 실행하지 않는다.

#### Freshness, 모드와 실패

- 기존 `VisionAgent.SIGNAL_TTL_MS=5000`을 늘리지 않고 capture timestamp도
  다시 쓰지 않는다. LIVE Pickup/ActiveCam 검토가 5초를 넘기면
  `VISION_EVIDENCE_EXPIRED`/review로 반환하는 알려진 지연 한계를 수용한다.
  helper는 `ManipulationAgent`의 기존 freshness 정책을 그대로 재사용하므로 TEST의
  기존 120초 grace는 유지하지만 새 LLM 지연 grace가 아니며 LIVE에는 적용되지 않는다.
  Pickup은 모델 검토 뒤 expiry를 명시적으로 검사한다. Placement 이미지 근거는
  보존되지만 기존 signal expiry와 downstream freshness gate는 바꾸지 않는다.
- per-call decision timeout 기본값은 45초이며 기존 더 짧은 camera/motion/rollout/
  replay/task deadline을 연장하지 않는다.
- 일반 API/vLLM 경로는 실제 모델 결과를 요구한다. `Mode.TEST`에서
  `force_real_llm_in_test=false`인 명시적 비LLM 경로는
  `deterministic_test`, `llm_used=false`로 기록하며 시각 검증 성공으로 부르지 않는다.
- 강제 real-LLM TEST fixture는 API/vLLM 통합 검증이고 비LLM deterministic fixture와
  분리한다.
- 모델 오류·timeout·무효/과대 응답, 이미지 누락/과대/손상/크기 불일치,
  detector 모순 또는 wrong-object/occlusion 판단은 임의 ready가 아니라 owner review다.
  이미 확인된 촬영·정지 사실은 보존하되 아직 결정되지 않은 handoff만 보류한다.

#### 기존 계약과 검증 범위

`vision_report.v1`, `vision_signal.v1`,
`active_cam_ejection_check.v1`, `spc_autoejection_confirmation.v1`,
`vision_manipulation_completion.v1`, `utm_verification_2` 및 Verification 1/2
분리는 유지한다. `vision_decision.v1`은 판단 scope/checkpoint/model/tool/reason/
evidence/image hash/error를 추가 기록하며 기존 검출 사실이나 timestamp를 덮어쓰지 않는다.

| 검증 그룹 | 요구 확인 |
|---|---|
| 제한 도구 | 정확한 JSON schema/인자/evidence, unknown tool, owner return, scope 변경 차단 |
| 멀티모달 | raw→annotated 순서/label, 동일 capture/크기, byte/pixel/raster 제한, API와 vLLM forwarding |
| 세 경로 | Pickup/ActiveCam pre-decision, placement verified-stop 후 review, clearance replay/home 후 review |
| 지연·중단 | pending poll 무LLM, stop/cancel/timeout 비차단, 5초 TTL 초과 review, timestamp 불변 |
| 효과·소유권 | ActiveCam 중복 이동, replay start, 임의 driver 명령, 타 session stop 및 lease 충돌 차단 |
| 모드 | 실제 API/vLLM fixture와 명시적 비LLM TEST label 분리; mock은 visual acceptance 불가 |
| 회귀 | 기존 detector threshold/좌표/모드, report/signal/handoff, Guardian, graph와 archive 유지 |

[`scripts/verify_vision_multimodal.py --execute`](../../../scripts/verify_vision_multimodal.py)로
등록 경로를 확인한 결과 8개 fixture 판단이 모두 accepted였다. API `gpt-5.5`는
selection/upright/compressed/synthetic-empty에 각각 5.076/4.058/4.220/11.739초,
vLLM `e4b`의 `gemma4:31b` fallback은 4.901/8.302/8.380/8.458초였다. 이 실행은
hardware tool을 등록하지 않았고 물리 구동·service 시작·config 수정을 하지 않았으며
원 upright/compressed fixture도 변경하지 않았다. synthetic empty는 실물 UTM clear
근거가 아니며 이 decision fixture 통과는 LIVE freshness handoff 통과를 뜻하지 않는다.
추가로 기존 아티팩트 기반 자연 입력 8종과 메모리상 모순 입력 5종을 API와 로컬에
각각 전달했다. 총 26회 timeout 없이 응답했으나 전체 판단 통과는 아니다.
두 모델 모두 잘못된 수치 bbox와 서로 다른 촬영 이미지 조합 2종을 놓쳤으며,
로컬 반려 응답 2개는 `contract_id` 누락으로 schema 검증에 실패했다.
사전 기대 선택 일치는 API 8/13, 로컬 9/13으로, 정확도나 유효 tool 실행률이 아니다.
동일 촬영/좌표 정합성은 모델 수락만으로 보장하지 않으며 코드 소유 검증을 유지한다.
과거 ActiveCam은 expired 차단을 유지했고, 모델이 unknown/occupied를 수락해도
clearance 완료로 승격하지 않는 회귀를 확인했다.
최종 combined 회귀는 14개 파일에서 266 passes, 기존 warning 10개, 10.55초를
보고했다. 별도 focused suite는 이 범위와 겹치므로
합산하지 않는다. 실제 장비 동작과 live safety는 검증하지 않았다. 기존
ActiveCam/UTM camera·loop 기록도 새
멀티모달 판단층의 근거로 재해석하지 않는다. 상세 한계는
[Vision Reference](../../agents/vision_agent.md)에 구분해 기록한다.

후속 사용자 승인으로 범용 prompt를 pair → location → validity → claim 순서로
보강했다. 실험별 형태·색·재질 상수 대신 입력 맥락을 쓰고 실제 raster 크기와 기존
unknown/실패 사유를 전달한다. 수락/반려 예시는 같은 필수 인자 계약을 따른다.
동일 조건 재측정에서 기대 선택 일치는 API 10/13 → 12/13, 로컬 9/13 → 12/13,
고정 후 별도 입력은 API 6/6, 로컬 5/6이었다. 로컬의 같은 배경·다른 대상 상태 쌍
오판은 남는다. 회귀 271 passed이며, 독립 정확도나 실제 폐루프 성공을 뜻하지 않는다.
세부 한계와 측정 조건은 [범용 prompt 검증 기록](../../paper/evidence/2026-09-08-vision-generic-prompt-verification.md)에 보존한다.

## Limitations and Known Gaps

툴 호출을 추가하는 것만으로 모델 판단의 정확성이나 연구 성능이 향상됐다고 주장할 수
없다. 모델 오류·추론 지연·의존성 증가를 실제 에이전트별로 측정해야 한다. 모든 내부
함수를 툴로 쪼개는 것이 목표가 아니며 안정된 복합 기능을 유지할 수 있다.
논문 기여 후보는 전문 역할에 맞는 판단층이 실험 근거를 후속 작업에 연결하는 방식이다.
단순 LLM 도입을 신규성이나 성능 개선의 증명으로 쓰지 않는다. 기존 고정 경로,
설명만 추가한 경로, 국소 의사결정층을 비교해 판단 유효성·재작업·지연·비용을 확인하고,
선행연구 대비 새로움은 별도 검토한다.

현재 전체 문서 검증에는 이 작업 이전의 Windows bridge Reference와 PLC 설계 문서
형식 문제가 알려져 있다. 이번 설계 작성은 그 무관한 문서나 validator를 수정하지 않는다.
향후 다섯 영역·세 피겨 계약을 검사하는 규칙은 해당 변경 범위와 함께 적용해야 하며,
현재 validator가 이 새 계약의 모든 의미를 이미 검증한다고 주장하지 않는다.

## Verification

검토 기준일: 2026-09-07. 기존 계층 정의, Agent Reference 목차, 문서 Standard와
템플릿, 피겨 검사 방식, 보호 커밋을 읽어 이 계약을 작성했다. 실제 기능 변경은 없다.
본 문서·상대 링크·설계 SVG의 형식 검증과 의미 검토는 런타임/실장비 검증과 구분한다.
동일 날짜의 사용자 보정에 따라 모든 에이전트의 정상 경로에 역할 적합한 국소
의사결정층을 두는 기준으로 본문·문서 계약·피겨·완료 조건을 함께 갱신했다.

## Manipulation 적용 계약 — 2026-09-09

하나의 Manipulation Agent가 실행 전과 실행 결과의 두 국소 의사결정을 소유한다.
기존 동작·검증·종료 경로를 유지하며, 새 오케스트레이션 노드를 만들지 않는다.

| 구간 | LLM 책임 | 기존 코드 책임 |
|---|---|---|
| 실행 전 | 현재 등록된 Skill이 작업·출발/도착 위치·제공된 자세 정보와 맞는지 판단하고 해당 툴 선택 | 저장된 정책/지시문/캘리브레이션, profile, freshness, 승인과 실행 파라미터 |
| 실행 중 | 별도의 주기적 판단을 요구하지 않음 | 기존 인퍼런스·고정 replay, 상태 관측, 인터록, 종료·안전 경로 |
| Vision 검증 및 종료 후 | 실행 증거와 Vision 사실을 종합하여 작업 인계 수락 또는 담당자 검토 선택 | Vision의 검측 사실, 종료 확인, 세션/루프 동일성, downstream gate |

High는 적합성·완료 의미 판단, Middle은 context/툴 dispatch와 감독, Low는 기존
LeRobot/로봇 실행기, Guardian/Safety는 기존 강제 조건과 stop, Knowledge/Evidence는
판단·동작·Vision 증거 보존으로 나눈다. 5영역은 순차적인 5회 LLM 호출을 뜻하지 않는다.

모델이 반환할 수 있는 인자는 코드가 묶은 `proposal_id`뿐이다. 정책, 훈련 시
지시문, 각도 기준, replay 데이터셋/episode, 장비 명령은 생성하거나 변경하지 않는다.
자세의 각도·좌표계·품질은 제공된 경우에만 근거로 활용한다. 등록되지 않은
각도별 정책 자동 전환은 이번 구현에 포함하지 않는다.

Vision sidecar에서 결과 판단을 호출하더라도 모델 경로는 Manipulation 모듈의
`manipulation_plan`을 사용한다. Vision 수락과 Manipulation 인계 수락은 별개이며,
후자 거절로 검측 사실 자체를 실패로 덮어쓰지 않는다. 필수 종료는 LLM 대기보다 먼저다.

테스트는 실제 장비를 호출하지 않는 도구/아티팩트 기반으로 수행한다. 명시적인
non-LLM TEST는 별도로 표시하고, real-LLM 가상 모드는 판단층을 통과하되 물리 실증으로
표시하지 않는다. 과거의 실증 아티팩트는 이번 재구성의 장비 실증으로 승격하지 않는다.
에이전트 문서는 Design/Vision과 같은 Status at a Glance, 5영역 표, 판단 계약,
기존 API/연결 상세, 크게 읽히는 SVG, 검증 범위와 한계를 포함한다.

구현·검증 기록: [Manipulation implementation plan](../plans/2026-09-09-manipulation-decision-layer.md).

## BO 적용 계약 — 2026-09-10

BO 내부 High는 전략과 근거 충분성, 수치 결과의 인계 여부를 판단한다. Middle은
검증·툴 dispatch·결과 고정을 수행하고 Low는 기존 `experiment.benchmark`의
LHS/BoTorch로 좌표를 계산한다. LLM이 좌표를 생성하거나 선호 점수로 덮어쓰지 않는다.
사용자가 확정한 acquisition은 기본적으로 보존하고, 명시적인 `adaptive` 설정에서만
허용된 전략 인자를 선택한다. 초기 LHS 정책과 기존 그래프/브릿지는 변경하지 않는다.

셀 크기는 신규 BO 요청에서 연속 범위로 정규화한다. 첫 LHS와 이후 추천이 동일한
공간 정보를 기존 JSON 인계에 포함하고, Design은 범위·제작성 검사 후 원래 수치
정밀도를 유지한다. 과거 이산 아티팩트의 의미와 일반 mixed-space 지원은 보존한다.

**개선 목표 달성 판정, 자동 종료, 재시험 실행은 사용자 요청에 따라 제외한다.**
문서는 Design 형식을 따라 Status at a Glance, 5영역 표, 실제 툴 계약, SVG,
아티팩트와 수행한 검증을 포함한다. 세부 사항은
[BO 설계](2026-09-10-bo-strategy-continuous-design.md)와
[구현 기록](../plans/2026-09-10-bo-strategy-continuous.md)을 따른다.

## Knowledge 적용 계약 — 2026-09-10

Knowledge의 High 판단은 재사용 가능한 근거의 선별·온톨로지 분류·검색 범위 내
상세 조회·기억 작성·근거 부족 판정이다. LLM은 기존 Knowledge stage 안에서
`inspect_evidence`, `search_knowledge`, `read_knowledge`, `write_knowledge_note`,
`publish_context`를 호출한다. Middle/Low는 스코프·출처·수명주기를 검증하고
기존 JSONL 및 새 Markdown 리비전을 저장한다.

지식 그래프/Neo4j 운영 연결만 종료한다. 온톨로지, 매뉴얼 RAG, 기존 원본과
패턴·성능·Evolution 계약, 실행 그래프와 장비 브릿지는 보존한다. 종료 아카이브의
관측 MD는 결정론적으로 남기며, LLM은 일반 Knowledge 단계에서만 판단한다.
시험 조건은 명시된 메타데이터를 복사할 뿐 장비 설정으로 연결하지 않는다.

Reference는 Design과 같은 6줄 Status at a Glance, 5영역 책임표, 도구·API 표,
기존 3개 SVG, 아티팩트·실제 검증 표를 사용한다. 구현 범위와 검증은
[Knowledge 설계](2026-09-10-knowledge-markdown-memory-design.md),
[구현 계획](../plans/2026-09-10-knowledge-markdown-memory.md),
[Knowledge Reference](../../agents/knowledge_agent.md)에 연결한다.

## Related Documents

- [기존 3계층 제어 정의](../../runtime/three_level_control_model.md)
- [Agent Reference 인덱스](../../agents/README.md)
- [API/Connection Matrix](../../agents/agent_api_connection_matrix.md)
- [문서 Standard](../../standards/documentation_standard.md)
- [논문 문서 Standard](../../standards/paper_documentation_standard.md)
- [Loop Artifact Archiving](../../runtime/loop_artifact_archiving.md)
