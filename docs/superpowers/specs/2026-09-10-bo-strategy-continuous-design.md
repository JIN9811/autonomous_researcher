---
doc_type: design
subtype: feature
status: active
authority: proposal
audience: [developer, researcher, reviewer]
scope: [bo, design, continuous_parameters, agent_decisions]
summary: BO 내부 전략 판단과 제한된 툴 호출을 추가하고 연속 설계변수를 기존 인계 경로로 전달한다.
decision_status: approved
related_docs:
  - docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
  - docs/agents/bo_agent.md
  - docs/agents/design_agent.md
supersedes: []
---

# BO 전략 판단·연속 설계변수 설계

## 승인 범위

2026-09-10 사용자 승인: BO 내부 High의 전략 선택, 근거 조회, 수치 진단,
결과 검토를 기존 수치 최적화 툴과 연결한다. 셀 크기의 기존 선택 테이블을
연속 범위로 바꾸고 Design까지 보존한다. **개선 목표 달성 판정은 제외한다.**
전체 루프·장비·브릿지 교체, 재시험 실행, 자동 종료, 목적함수 변경은 하지 않는다.

## 책임 및 인계

| 영역 | 책임 | 제한 |
|---|---|---|
| BO 내부 High | 현재 관측·실패·Knowledge 근거를 읽고 허용된 최적화 작업과 전략을 판단한다. 결과를 인계하거나 근거를 더 조회하고 보류한다. | 좌표 생성·수정, 임의 선호 점수, 단계 전이 권한 없음 |
| Middle | 입력 고정, 요청 스키마·근거 ID 검증, 제한된 툴 dispatch, 결과 수집 | 성공한 최적화 재실행 금지 |
| Low | 기존 `experiment.benchmark` → LHS / BoTorch, 진단 수치 계산 | 요청된 범위 안에서만 계산 |
| Guardian / Safety | 관측 적격성, 유한값·범위·고정값·후보 정체성·예산 검사 | LLM이 강제 조건을 해제할 수 없음 |
| Knowledge / Evidence | 출처가 있는 문맥, 결정·툴 요청/응답·루프별 아티팩트 | 가설과 측정 사실 분리 |

Orchestrator는 전체 루프의 High를 계속 소유한다. BO 내부 High는 위임받은
최적화 업무의 전략 판단 범위이며 새로운 scheduler나 그래프 노드가 아니다.

## 정상 판단 경로

1. 기존 코드가 목적함수 정체성, 관측 적격성, 고정 제조 변수와 탐색 공간을 검증한다.
2. `bo_decision.v1` 판단층에 목표, 공간, 관측 요약, 이용 가능한 근거 ID와 툴을 제공한다.
3. LLM은 `inspect_diagnostics`, `retrieve_knowledge`, `run_optimizer`, `return_to_owner` 중 허용된 작업을 선택한다.
4. `run_optimizer`는 기존 `experiment.benchmark`를 한 번 호출한다. LHS 단계는 기존 초기 설계가 수치적으로 결정하며 LLM이 건너뛰거나 순서를 바꾸지 못한다.
5. 최적화 결과가 돌아온 뒤에는 진단·근거 조회, `accept_recommendation`, `return_to_owner`만 허용한다. 채택은 실제 solver 후보 ID와 필수 검사를 통과해야 한다.
6. 기존 `next_design_request.v1`과 `AgentResult`로 인계한다. 연속 좌표는 수치 backend가 선택한다.

툴 이름은 에이전트 내부 dispatch 계약이다. 새 전역 브릿지 API로 문서화하지 않는다.
진단은 관측 수·중복·정규화된 공간 커버리지·유한한 posterior/optimizer 결과를
계산한다. 새로운 목표 달성률이나 종료 임계값을 도입하지 않는다. Knowledge 조회는
이미 전달된 출처 있는 문맥과 기존 local RAG를 사용하며, 임의 웹/파일/shell 호출을 허용하지 않는다.

전략 선택은 지원되는 acquisition과 그에 해당하는 제한된 인자로 표현한다.
기본 실행은 현재 설정을 유지하고, 자동 전략 선택이 허용된 경우만 변경한다.
사용자가 고정한 설정과 목적함수·공간·초기 설계·실험 예산은 읽기 전용이다.
실패한 LLM 호출·잘못된 요청·mock 응답은 정상 경로에서 수치 fallback으로 숨기지 않는다.
명시적인 비LLM TEST 모드만 동일 dispatch를 결정론적으로 검증하고 `virtual_test`로 기록한다.
API와 로컬 모델은 기존 `AgentContext.complete("bo_policy", ...)` 경로를 사용한다.

## 연속 변수 계약

- 신규 기본값: `cell_size_mm: [5.0, 10.0]`, `relative_density: [0.20, 0.48]`.
- 숫자 하나/단일 원소는 고정값, 두 경계값은 연속 범위다. 기존 셀 크기 테이블은 최소·최대 범위로 정규화하고 이를 명시한다.
- 일반 `BOParameterSpace`의 이산·범주형 지원은 제거하지 않는다. 이번 활성 변수는 셀 크기와 상대밀도 두 개뿐이다.
- 유효한 사용자 범위를 첫 LHS와 이후 BO가 함께 사용한다. 잘못된 유한값/역전 경계는 명시적으로 거부한다.
- 기존 JSON 인계에 공간 정보를 부가 전달한다. Design은 네 개의 고정 셀 크기 집합 대신 전달된 범위를 검사한다.
- 상위 요청 좌표는 Design 생성/평가/형상 인자까지 원래 수치 정밀도로 유지한다. 임의 테이블 snap 또는 후보 재최적화 금지.
- 제작 가능성·최소 벽·브리지 길이·범위 검증은 보존한다. 저장된 과거 기록과 이미 발행된 요청은 수정하지 않는다.
- LHS/BO 화면의 축·범위 표시는 연속값을 반영하고 과거 이산 산출물도 읽을 수 있어야 한다.

## 검증 및 문서

기존 경로를 유지한 비구동 테스트로 정상 전략 호출, 근거 조회, 결과 검토,
LLM 오류/권한 밖 요청/후보 변조 차단, 성공 호출 재실행 방지, LHS 보존,
실제 BoTorch 연속 좌표, Orchestrator→Design 정밀도 보존을 확인한다.
BO Reference는 Status at a Glance, 5영역 표, 판단·툴 계약, SVG/원본,
아티팩트와 실제 검증 범위를 함께 갱신한다. Design Reference에는 연속값 인계의
변경만 반영한다. 등록 API/로컬 검증은 실제 수행한 경우에만 통과로 기록한다.

## 제외

목표 개선 달성 판정, 목표에 따른 자동 종료, 자동 재시험, 신규 캠페인/슬롯,
미검증 FEM의 BO 관측 승격, 실제 장비 실행, 서버 재시작, 임의 solver 교체.
구현 검증 후 후속 사용자 승인에 따라 `BO-Agent` 태그로 커밋·푸시한다.
기존 에이전트 태그와 `closed-loop-stable` 태그는 변경하지 않는다.
