# Design Agent Agentic Loop 조사 노트

조사 일자: 2026-05-27

목적: Autonomous Researcher의 `DesignAgent`를 "실험 설계 에이전트"로 고도화하기 전에, self-driving lab과 scientific agent 문헌에서 공통적으로 쓰이는 실험 설계 루프 패턴을 정리한다. 이 문서는 코드 변경안이 아니라, 이후 리눅스 개발 환경에서 상세 설계를 만들기 위한 리서치 브리프다.

최종 목표: 완전 자율 실험실. 즉, 사람이 매번 다음 실험 조건을 지정하지 않아도 시스템이 목표/제약을 이해하고, 실험을 설계하고, 장비 실행 결과를 분석하고, 실패와 불확실성을 반영해 다음 실험을 스스로 선택하는 구조를 목표로 한다. 다만 physical lab에서는 안전, 장비 보호, 비용, 데이터 무결성 때문에 "무제한 autonomous action"이 아니라 "검증 가능한 자율성 + 명시적 안전 gate + rollback 가능한 운영"이 되어야 한다.

## 1. 핵심 결론

실험 설계 agentic loop의 좋은 형태는 LLM 단독 의사결정이 아니다.

가장 안정적인 구조는 다음과 같은 하이브리드다.

```text
사용자 목표/제약
  -> 목표 정규화와 가설 생성
  -> 설계공간/후보군 생성
  -> 제조/장비/안전 제약 필터 또는 repair
  -> surrogate/BO/active learning 기반 scoring
  -> 선택 이유와 탈락 이유 기록
  -> 실험 실행 handoff
  -> 분석 결과/실패 메모리/불확실성 반영
  -> 다음 설계 루프
```

LLM은 다음 역할에 강하다.

- 자연어 목표를 실험 목적, metric, 제약, 가설로 정규화
- prior literature나 operator intent를 설계 변수로 번역
- 후보 선택 이유와 실패 가능성을 설명
- 다음 실험의 "왜"를 보고서 형태로 남김

반대로, 다음 역할은 deterministic/statistical engine이 맡는 편이 안전하다.

- posterior update
- acquisition function 계산
- 중복 후보 방지
- constraint satisfaction/repair
- 실험 예산 기반 batch selection
- 안전/제조 가능성 hard gate

## 2. 조사한 대표 패턴

### 2.1 Robot Scientist: hypothesis -> experiment -> interpretation loop

King et al.의 Robot Scientist는 오래된 사례지만 실험 설계 agent loop의 원형에 가깝다. 시스템은 관찰을 설명하는 가설을 만들고, 그 가설을 검증할 실험을 고르고, 로봇으로 실행하고, 결과로 가설을 반박/갱신한 뒤 반복한다.

적용 포인트:

- Design Agent가 단순 후보 선택 대신 `hypothesis`를 명시해야 한다.
- 후보는 objective score만이 아니라 "어떤 가설을 테스트하는가"를 가져야 한다.
- 실패나 반례는 다음 candidate generation의 입력으로 남아야 한다.

출처: [Functional genomic hypothesis generation and experimentation by a robot scientist, Nature 2004](https://www.nature.com/articles/nature02236)

### 2.2 ChemOS: experiment planning은 독립 learning module

ChemOS는 closed-loop autonomous lab을 모듈형으로 나눈다. 핵심 자율성에는 planning/learning module, robotic execution, characterization이 필요하며, 데이터베이스와 online analysis, researcher interface가 이를 감싼다. ChemOS의 learning module은 Phoenics, SMAC, Spearmint, random search 등 Bayesian/optimization 계열을 통해 다음 조건을 추천한다.

적용 포인트:

- Design Agent 안에 모든 최적화 로직을 숨기지 말고, `learning` 또는 `bo` 계층과 계약을 나눠야 한다.
- Design Agent는 "candidate proposal + report + handoff" 담당, BO/selector는 "posterior/acquisition" 담당으로 분리하는 편이 맞다.
- GUI에는 candidate가 아니라 campaign 상태, prior count, selected strategy가 보여야 한다.

출처: [ChemOS: An orchestration software to democratize autonomous discovery, PLOS One 2020](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0229862)

### 2.3 CAMEO: uncertainty-aware active learning

CAMEO는 materials exploration에서 데이터베이스를 불러오고, physics-informed Bayesian ML로 구조/물성 및 불확실성을 예측한 뒤, active learning이 다음 샘플을 고른다. 측정 결과와 human input은 다시 DB로 들어가 다음 루프에 사용된다.

적용 포인트:

- Design Agent의 후보 선택 결과에는 `predicted_score`와 `uncertainty`가 같이 있어야 한다.
- "최고 점수 후보"와 "가장 정보량이 큰 후보"를 구분해야 한다.
- Human-in-the-loop 해석 가능성을 위해 선택 근거와 불확실성 근거를 보고서에 남겨야 한다.

출처: [On-the-fly closed-loop materials discovery via Bayesian active learning, Nature Communications 2020](https://www.nature.com/articles/s41467-020-19597-w)

### 2.4 A-Lab: language model recipe + thermodynamics-grounded active learning

A-Lab은 계산, 문헌 기반 historical data, ML, active learning, robotics를 결합한다. 자연어 모델은 문헌 기반 synthesis recipe를 제안하고, active learning은 thermodynamics에 근거해 recipe를 최적화한다. 실패한 합성 결과 분석도 다음 기술 개선 제안으로 연결된다.

적용 포인트:

- LLM은 recipe/spec 초안을 만들 수 있지만, 최종 실험 설계는 domain-grounded gate를 통과해야 한다.
- 실패 분석은 단순 로그가 아니라 다음 설계에서 "하지 말아야 할 조건"으로 구조화되어야 한다.
- `failure_memory_summary`를 더 강한 설계 입력으로 키워야 한다.

출처: [An autonomous laboratory for the accelerated synthesis of inorganic materials, Nature 2023](https://ideas.repec.org/a/nat/nature/v624y2023i7990d10.1038_s41586-023-06734-w.html)

### 2.5 Coscientist: LLM agent는 JSON action, observation, rationale 계약이 중요

Coscientist의 reaction optimization 평가는 이전 결과를 관찰하고, 다음 reaction condition을 JSON으로 제안하며, sensible chemical explanation을 같이 내도록 구성했다. 형식 위반은 즉시 실패로 알려주고, iteration budget을 제한했다.

적용 포인트:

- Design Agent 출력은 free-form text가 아니라 schema-safe JSON이어야 한다.
- 각 후보에는 "previous observation"을 어떻게 반영했는지 기록해야 한다.
- iteration budget, candidate budget, invalid-output retry 정책이 필요하다.

주의점:

- Coscientist는 LLM의 실험 설계 가능성을 보여주지만, 우리 프로젝트처럼 물리 장비와 안전 gate가 있는 경우 LLM 직접 최종 결정은 위험하다.

출처: [Autonomous chemical research with large language models, Nature 2023](https://www.nature.com/articles/s41586-023-06792-0)

### 2.6 Constrained multi-objective BO: feasibility, repair, batch proposal

Self-driving lab의 실제 최적화는 단일 score 최대화보다 constrained multi-objective인 경우가 많다. EGBO 사례에서는 Sobol 초기 샘플링, batch proposal, infeasible candidate repair, objective/constraint table 업데이트 대기, campaign stop budget 같은 운영 패턴이 보인다.

적용 포인트:

- Design Agent가 `objective`와 `constraints`를 분리해서 출력해야 한다.
- 후보가 제약을 어기면 discard만 하지 말고 repair 경로도 기록해야 한다.
- 하나의 candidate만이 아니라 batch candidate와 selected candidate를 함께 보고할 수 있어야 한다.

출처: [Evolution-guided Bayesian optimization for constrained multi-objective optimization in self-driving labs, npj Computational Materials 2024](https://www.nature.com/articles/s41524-024-01274-x)

### 2.7 최신 LLM 실험설계 벤치마크의 경고

최근 "LLMs for Experiment Design in Scientific Domains: Are We There Yet?"는 LLM agent가 experimental feedback에 둔감할 수 있고, classical BO/linear bandit/GP가 더 강한 경우가 많다고 보고한다. 중요한 결론은 LLM prior와 posterior/acquisition mechanism을 분리한 hybrid framework가 더 유망하다는 점이다.

적용 포인트:

- Design Agent의 LLM은 `prior/hypothesis/rationale` 담당으로 제한한다.
- posterior update와 acquisition은 별도 selector 또는 BO Agent가 맡아야 한다.
- feedback을 prompt에 붙이는 것만으로는 "학습"이라고 보면 안 된다.

출처: [LLMs for Experiment Design in Scientific Domains: Are We There Yet?, OpenReview/PMLR 2025](https://openreview.net/pdf/01d70bfa8e028d270c07056a9409380971c5758b.pdf)

### 2.8 LLMatDesign/MatAgent 계열: self-reflection + tool evaluation

LLMatDesign와 MatAgent 계열은 LLM이 사용자 목표를 해석하고, 후보 material modification을 만들고, 외부 평가 도구로 결과를 확인한 뒤, 이전 결정에 대한 self-reflection으로 다음 설계를 조정하는 구조를 사용한다.

적용 포인트:

- Design Agent도 "선택 후 반성"보다 "이전 루프의 결과를 구조적으로 반영한 next proposal"이 필요하다.
- report에는 `what changed from previous loop`가 들어가야 한다.
- self-reflection은 모델 텍스트만이 아니라 candidate/history diff로 검증되어야 한다.

출처:

- [LLMatDesign: Autonomous Materials Discovery with Large Language Models, arXiv 2024](https://arxiv.org/abs/2406.13163)
- [Accelerated inorganic materials design with generative AI agents, Cell Reports Physical Science 2025](https://www.sciencedirect.com/science/article/pii/S2666386425006186)

## 3. Design Agent에 맞춘 권장 agentic loop

현재 프로젝트의 Design Agent는 이미 다음을 한다.

- 목표와 state constraint를 병합
- 후보군 생성
- FDM printability 제약 필터
- proxy score ranking
- `experiment_spec` 출력
- LLM으로 짧은 review note 생성

고도화 방향은 이 구조를 유지하면서, 다음 loop를 명시화하는 것이다.

```text
1. Objective Intake
   - active_goal, operator defaults, current_experiment_spec 수집
   - primary objective, direction, metric, constraints 정규화

2. Prior and Failure Context
   - ExperimentDB 최근 결과
   - Knowledge Agent summary
   - BO recommendation
   - FailureMemory의 failed_geometry, failed_feature, blocked_gate 수집

3. Hypothesis Generation
   - LLM 또는 deterministic template로 이번 후보가 테스트할 가설 생성
   - 예: "relative_density 증가가 SEA를 올리지만 print time과 brittleness risk를 증가시킨다"

4. Design Space Construction
   - geometry type, size, cell size, wall thickness, density, cap skin, orientation 범위 설정
   - fixed 변수와 tunable 변수를 분리

5. Candidate Generation
   - 초기 루프: Sobol/DOE seed
   - prior가 적을 때: diversity-aware candidate pool
   - prior가 충분할 때: BO/acquisition/nearest-neighbor hybrid

6. Constraint Gate and Repair
   - FDM feature rule
   - UTM fixture limit
   - mass/time budget
   - hardware/print profile compatibility
   - infeasible candidate repair 기록

7. Scoring and Selection
   - predicted objective
   - uncertainty
   - manufacturability
   - novelty/information gain
   - failure risk
   - final acquisition score

8. Report and Handoff
   - selected candidate
   - rejected candidates
   - selected reason
   - risk notes
   - exact specimen handoff fields

9. Feedback Hook
   - Analysis/Knowledge/BO/Guardian 결과가 다음 Design loop 입력으로 재사용되도록 schema 저장
```

## 4. 제안 출력 계약

기존 필수 키는 유지한다.

```json
{
  "experiment_spec": {},
  "rationale": "..."
}
```

추가 권장 키:

```json
{
  "design_report": {
    "hypothesis": {
      "statement": "",
      "variables_under_test": [],
      "expected_tradeoffs": [],
      "falsification_signal": ""
    },
    "objective": {
      "primary_metric": "",
      "direction": "maximize|minimize|explore",
      "secondary_metrics": [],
      "constraints": {}
    },
    "prior_context": {
      "prior_count": 0,
      "best_prior": {},
      "knowledge_summary": "",
      "bo_recommendation": {},
      "failure_memory": {}
    },
    "candidate_generation": {
      "strategy": "doe_seed|diversity_search|bo_acquisition|llm_prior_hybrid",
      "budget": 0,
      "design_space": {},
      "candidate_count": 0
    },
    "candidate_evaluation": {
      "selected_candidate_id": "",
      "selected_score": 0.0,
      "predicted_objective": null,
      "uncertainty": null,
      "manufacturability_score": null,
      "information_gain_score": null,
      "risk_score": null
    },
    "rejected_candidates": [
      {
        "candidate_id": "",
        "reason": "",
        "repair_attempted": false,
        "repair_result": null
      }
    ],
    "handoff_to_specimen": {
      "required_fields_present": true,
      "manufacturing_notes": [],
      "known_risks": []
    }
  }
}
```

## 5. Live GUI 보고서에 보여야 할 항목

Design Agent 보고서는 다음 섹션을 갖는 편이 좋다.

- Objective: 어떤 metric을 최적화하는지
- Hypothesis: 이번 실험이 검증할 과학적/공학적 가설
- Candidate Pool: 생성 후보 수, valid/rejected 수
- Selected Candidate: 최종 선택 변수와 proxy/acquisition score
- Rejected/Repair Log: 제약 위반과 repair 여부
- Prior Feedback: 이전 분석/BO/실패 메모리를 어떻게 반영했는지
- Specimen Handoff: Specimen Agent가 그대로 사용할 authoritative fields
- Risk: printability, fixture, mass/time, failure memory risk

## 6. 우리 프로젝트에서 바로 가져갈 설계 원칙

1. LLM을 최종 optimizer로 쓰지 않는다.
2. LLM은 목표 해석, 가설 생성, 설명 가능한 보고서, 도메인 prior 생성에 쓴다.
3. 후보 선택은 constraint-aware statistical selector가 맡는다.
4. `experiment_spec`은 계속 authoritative handoff로 유지한다.
5. `design_report`를 추가해 Live GUI와 self-evolution이 읽을 evidence를 만든다.
6. Feedback은 prompt text가 아니라 구조화된 `prior_context`, `failure_memory`, `bo_result`로 들어와야 한다.
7. 모든 후보는 selected/rejected/repair 상태를 가져야 한다.
8. uncertainty와 information gain을 objective score와 분리해서 기록한다.

## 7. Design Agent 개선안 초안 방향

우선순위 1: 보고서 계약 추가

- 현재 `experiment_spec`은 유지
- `design_report` 추가
- Live GUI `/api/agents/design/report`가 `design_report`를 우선 사용하도록 후속 설계

우선순위 2: objective normalization

- goal 문자열을 `objective_contract`로 정규화
- metric name, direction, constraints, success criteria, stop criteria 분리

우선순위 3: candidate ledger

- 후보군 전체를 다 저장하지 않더라도 top/rejected/repair 요약은 저장
- 중복 후보 방지용 candidate fingerprint 생성

우선순위 4: BO/Knowledge 연동 강화

- BO Agent가 넘긴 추천을 단순 constraint override가 아니라 acquisition context로 반영
- Knowledge Agent의 memory summary와 failure taxonomy를 설계공간 축소/확장에 사용

우선순위 5: uncertainty-aware selection

- `expected_objective_proxy_score` 단독 ranking에서
  `objective + manufacturability + novelty + uncertainty/information_gain - risk`로 분리

## 8. 한 줄 설계 방향

Design Agent는 "하나의 printable specimen spec을 고르는 함수"에서 "가설, 설계공간, 후보군, 제약, 불확실성, 선택근거를 남기는 실험 설계 루프의 첫 노드"로 고도화해야 한다.

## 9. 완전 자율 실험실 관점의 Design Agent 요구조건

완전 자율 실험실을 목표로 하면 Design Agent는 단순히 "다음 specimen 하나"를 출력하는 노드가 아니라, 전체 autonomous campaign의 첫 번째 의사결정 노드가 된다.

필수 능력:

- 목표를 metric/constraint/stop condition으로 정규화한다.
- 실험 설계공간을 명시한다.
- 이전 실험 결과, 실패 메모리, BO/Knowledge 피드백을 읽는다.
- 다음 후보가 테스트할 가설을 생성한다.
- 후보군을 만들고, 중복 후보와 금지 후보를 제거한다.
- 제조 가능성, 장비 가능성, 안전성을 사전 평가한다.
- 후보 선택 근거를 구조화해 남긴다.
- Specimen Agent가 그대로 실행 가능한 authoritative `experiment_spec`을 만든다.
- Analysis/Knowledge/BO/Guardian 결과를 다음 루프에서 재사용할 수 있게 feedback hook을 남긴다.

완전 자율 실험실에서 특히 중요한 금지사항:

- LLM이 free-form으로 장비 실행값을 지어내면 안 된다.
- 이전 실험 결과를 prompt에 붙이는 것만으로 "학습했다"고 보면 안 된다.
- 후보 선택 이유가 로그에 남지 않으면 자율 루프의 성능 개선 여부를 검증할 수 없다.
- 실패한 조건을 memory에 남기지 않으면 동일 실패를 반복한다.
- uncertainty 없이 objective score만 보고 다음 실험을 고르면 exploitation에 갇힌다.

따라서 Design Agent는 `LLM reasoning node`가 아니라 `objective normalization + candidate generation + constraint-aware selection + reportable handoff` 노드로 설계해야 한다.

## 10. 출처 색인

- Robot Scientist 원형 루프: [Functional genomic hypothesis generation and experimentation by a robot scientist, Nature 2004](https://www.nature.com/articles/nature02236)
- 모듈형 autonomous lab orchestration: [ChemOS: An orchestration software to democratize autonomous discovery, PLOS One 2020](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0229862)
- 불확실성 기반 closed-loop active learning: [On-the-fly closed-loop materials discovery via Bayesian active learning, Nature Communications 2020](https://www.nature.com/articles/s41467-020-19597-w)
- 계산/문헌/ML/robotics 통합 자율 합성: [An autonomous laboratory for the accelerated synthesis of inorganic materials, Nature 2023](https://ideas.repec.org/a/nat/nature/v624y2023i7990d10.1038_s41586-023-06734-w.html)
- LLM scientific agent와 JSON action/experiment design: [Autonomous chemical research with large language models, Nature 2023](https://www.nature.com/articles/s41586-023-06792-0)
- constrained multi-objective BO와 candidate repair: [Evolution-guided Bayesian optimization for constrained multi-objective optimization in self-driving labs, npj Computational Materials 2024](https://www.nature.com/articles/s41524-024-01274-x)
- LLM 단독 실험설계의 한계와 hybrid 필요성: [LLMs for Experiment Design in Scientific Domains: Are We There Yet?, OpenReview/PMLR 2025](https://openreview.net/pdf/01d70bfa8e028d270c07056a9409380971c5758b.pdf)
- LLM 기반 재료 설계 self-reflection 패턴: [LLMatDesign: Autonomous Materials Discovery with Large Language Models, arXiv 2024](https://arxiv.org/abs/2406.13163)
- generative agent + tool evaluation 재료 설계 패턴: [Accelerated inorganic materials design with generative AI agents, Cell Reports Physical Science 2025](https://www.sciencedirect.com/science/article/pii/S2666386425006186)

## Live GUI 고도화 추가안 - 고도화안 기준

Design Agent의 Live GUI는 단순히 "설계 완료"를 말하는 창이 아니라, 목표-제약-후보 형상-제조 가능성-다음 agent handoff가 한 화면에서 추적되는 설계 심의판이어야 한다. 현재 코드의 `LIVE_AGENT_REPORT_PROFILES.design`과 `/api/agents/design/report` 구조는 유지하되, `role_specific`을 정적 설명이 아니라 후보별 검토 결과와 결정 근거가 갱신되는 보고서 페이지로 키운다.

### Live GUI chat에 떠야 할 메시지

- 목표 해석: 사용자의 강도, 변형률, 시편 규격, 프린트 제약을 Design Agent가 어떤 실험 계약으로 해석했는지 한 문장으로 표시한다.
- 입력 부족 질문: 치수, infill, 재료, objective weight가 빠지면 Orchestrator를 거쳐 질문을 올리고, 사용자가 답하면 같은 thread/run_id로 resume된다.
- 후보 생성: `candidate_id`, 핵심 파라미터, 예상 성능, 제조 리스크를 함께 보여준다.
- trade-off 판단: 강도 우선, 출력 시간 우선, 불확실성 감소 우선 같은 선택지가 생기면 "내 판단은 A지만 B도 가능" 형태의 중간 의견을 표시한다.
- handoff: Specimen Agent로 넘길 STL/geometry spec, slicer hint, 금지 조건을 chat card로 남긴다.
- 경고: 설계가 프린터/UTM/robot workspace 제약을 넘으면 Guardian에도 같은 이벤트를 보내고, chat에는 수정 후보를 같이 제시한다.

### Design Agent 특화 보고서 페이지

- Experiment contract: objective, 제약, 측정 지표, 시편 표준, loop_id.
- Candidate board: 후보별 geometry params, rationale, predicted metrics, uncertainty, constraint violation.
- Manufacturability check: 프린터 가능 치수, overhang/bridge, expected print time, support 필요성.
- BO/Knowledge context: BO가 제안한 탐색 의도와 Knowledge Agent에서 가져온 유사 실험 근거.
- Decision register: 왜 이 후보를 specimen 제작으로 넘기는지, rejected 후보는 왜 탈락했는지.
- Handoff packet: `design_candidate.v1`, STL/metadata 경로, slicer profile hint, downstream risk.
- Operator actions: approve design, revise objective, ask Design Agent, send to Guardian review.

### 현재 시스템에 맞춘 event/report 필드

- `live_chat_message.v1`: `agent_id=design`, `message_type=status|question|decision|warning|handoff`, `candidate_id`, `requires_response`, `evidence_refs`.
- `agent_report_page.v1`: 기존 `sections.role_specific` 아래에 `candidate_board`, `manufacturability`, `decision_register`, `handoff_packet`을 추가한다.
- LangGraph interrupt 패턴은 치명적 설계 변경, objective ambiguity, Guardian warning 발생시에만 쓴다. 일반 상태 갱신은 현재 SSE event stream으로 충분하다.

### 참고 출처

- LangGraph graph execution UI는 node 상태와 streaming content를 frontend에서 표시하는 패턴을 제공한다: https://docs.langchain.com/oss/python/langgraph/frontend/graph-execution
- LangGraph interrupts는 승인, 검토/수정, tool call 전 pause/resume에 적합하다: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangSmith observability는 tool call, decision point, trace metadata를 추적하는 기준으로 삼을 수 있다: https://docs.langchain.com/oss/python/langchain/observability
- NN/g visibility of system status 원칙상 Design Agent는 "설계 중"이 아니라 어떤 후보를 왜 선택 중인지 보여줘야 한다: https://www.nngroup.com/articles/ten-usability-heuristics/
