# 닫힌 루프 실행 및 페이지/에이전트 상세 가이드

## 0) 지금 상태 요약

요청하신 대로 핵심을 먼저 분리했습니다.

- **루프가 존재하지 않는 것이 아닙니다.**
  - 닫힌 루프는 `POST /api/run/start` 또는 `POST /api/runtime/start` 호출 이후에만 실행됩니다.
  - `/home/jin/autonomous_researcher/graphs/configs/atr_closed_loop.yaml`의 `atr_closed_loop` 그래프가 기본 실행 그래프입니다.
- 루프가 안 도는 것처럼 보이면 대부분은 **`run_start`가 안 되거나, 이벤트를 다른 창에서 못 보고 있거나, guardian/lifecycle 조건이 `complete/error`로 빠른 종료한 경우**입니다.

---

## 1) 초보자용: 어떻게 돌아가는가 (5분 정독)

1. **시작**
   - GUI: `/live` 또는 `POST /api/run/start` (모드: `live|test|replay|fault-injection`)
   - 서버는 Run 객체를 만들고 `orchestrator stage`를 `idle`로 둔 뒤, 루프를 시작합니다.
2. **첫 단계 이동**
   - `idle -> design` (실행 순서의 시작)
3. **기본 사이클**
   - `design -> specimen -> vision -> manipulation -> equipment -> analysis -> knowledge -> bo -> guardian`
4. **반복/종료**
   - `guardian` 판단값이
     - `continue`면 다시 `design`로 회귀
     - `stop`이면 `complete`
     - `error`면 `error`
   - `complete/error`면 루프 종료
5. **왜 화면에서 안 움직이나 싶을 때**
   - `/api/runtime/state`에서 `run_id/state` 확인
   - ` /api/runtime/events` 또는 `/api/runs/{run_id}/events`에서 `run.started / node.started / node.completed / edge.traversed / run.complete` 유무 확인
   - `complete/error`가 처음에 찍히면 Guardian/안전조건으로 바로 종료된 것

### 초보자용 실험 시작 체크리스트

- [ ] 서버 실행됨(`atr up`)
- [ ] `/live` 접속
- [ ] 테스트면 `mode=test`, 실기라면 `mode=live` 선택
- [ ] Run 시작 버튼 → run_id 발급
- [ ] 이벤트 스트림에 다음이 순차로 뜨는지 확인
  - `run.started`
  - `node.started(node=design)`
  - `node.completed`
  - `edge.traversed` 또는 `stage_transition`
- [ ] 마지막에 `run_complete` 또는 `run.failed`

---

## 2) 상급자용: 루프 아키텍처 계약

### 2.1 엔트리포인트

- `POST /api/run/start` : 핵심 시작 API
- `POST /api/runtime/start` : 호환용 alias
- `POST /api/run/pause`, `/api/run/resume`, `/api/run/stop`, `/api/run/safe-stop`
- `GET /api/runtime/state`, `GET /api/runs/{run_id}`, `GET /api/runs/{run_id}/events`

### 2.2 실행 경로

- 컨트롤러: `MainController.start(mode=...)`
- 실행 객체: `LangGraphRunLoop`
- 런 루프: `while` → `stop`/`pause` 체크 → `step()` → `ainvoke(compiled graph)` → `sleep(interval)`
- 기본 그래프: `graphs/configs/atr_closed_loop.yaml` (`graph id=atr_closed_loop`)

### 2.3 stage 전이 규칙

- 기본 전이: `stage.transitions`에서 추출
- 실질 라우팅 후보: `runtime_edge=logical_transition` metadata 기반
- 시작: `dispatch`/`idle` 정합성 검증 통과 필요
- live start는 활성 그래프의 dry-run 게이트를 요구
  - 실패시 `GRAPH_DRY_RUN_REQUIRED` (상세는 `details`)가 반환

### 2.4 이벤트 계열(핵심)

- `run.started`, `run_stopped`, `run.completed`, `run.failed`
- `node.started`, `node.completed`, `node.failed`
- `edge.traversed`(또는 `stage_transition`)
- `agent_result`, `tool_event`, `artifact.created`
- `approval.requested` / `approval.resolved`

---

## 3) 기본 닫힌루프(기본 모드) 단계별 상세

아래는 `atr_closed_loop.yaml`의 현재 순서입니다.

```text
dispatch -> idle -> design -> specimen -> vision -> manipulation -> equipment -> analysis -> knowledge -> bo -> guardian -> (continue: design | stop: complete | error: error)
```

### 핵심 노드 동작 (실행/디버깅 포인트)

- `dispatch` : 상태(stage)에서 실행 스테이지로 라우팅
- `idle` : 루프 시작점 도달
- `design` ~ `guardian` : 각 에이전트 핸들러 실행
- `complete`/`error`/`step_complete` : 종료/요약/감사용 단계

---

## 4) 페이지별 상세

| 페이지 | 경로 | 템플릿 | 목적 | 주요 API |
|---|---:|---|---|---|
| 메인 대시보드 | `/` | `index.html` | 전체 런타임 상태, 모델/런 제어, 장비 카드, Timeline, 이벤트 | `/api/state`, `/api/runtime/state`, `/api/runtime/start`, `/api/runtime/pause`, `/api/runtime/stop`, `/api/runtime/models*`, `/api/runtime/events` |
| 라이브 오케스트레이션 | `/live` | `planning.html` | 채팅 기반 실험 지시, planning handoff, stage 메시지/아티팩트 표시 | `/api/planning/bootstrap`, `/api/planning/message`, `/api/planning/session`, `/api/planning/artifacts/{...}` |
| 라이브(레거시) | `/planning` | `planning.html` | `/live` 별칭 | 동일 |
| 3DP/Printer GUI | `/printer` | `printer.html` | 프린터/PrusaLink 프로파일 및 오토이젝션, 테스트 옵션, 상태 확인 | `/api/printer/profile`, `/api/printer/status`, `/api/printer/connection`, `/api/printer/autoejection-test` |
| BO Workspace | `/bo` | `bo.html` | BO/MBO/LLM preference 전략 설정, reasoning audit, candidate ranking, next-design handoff | `/api/bo/config`, `/api/bo/benchmark`, `/api/bo/run` |
| CAE Workspace | `/cae` | `cae.html` | 정적 CAE 분석 실행, 파라미터 저장, 결과 라인업 | `/api/cae/config`, `/api/cae/run` |
| Runtime IDE | `/ide` | `runtime_ide.html` | 그래프/에지/모듈 편집, validate/dry-run/실행, 버전관리 | `/api/graphs*`, `/api/modules*`, `/api/handlers` |
| Module Management | `/module-management` | `module_management.html` | 모듈 로드·언로드·검증·버전 저장(standalone) | `/api/modules*`, `/api/handlers`, `/api/graphs/{id}/run` |
| Self-Evolution Lab | `/evolution-lab` | `evolution_lab.html` | 실험 변형/태스크 관리, variant 승인/롤백 | `/api/evolution/*` (설정/작업/태스크/variant) |
| Windows 장비 브릿지 | `/equipment/windows` | `windows_equipment.html` | Windows PyAutoGUI 브릿지 후보 검색/선택/프로그램 실행 | `/api/equipment/windows/config`, `/api/equipment/windows/discover`, `/api/equipment/windows/connect`, `/api/equipment/windows/select`, `/api/equipment/windows/delete`, `/api/equipment/windows/test`, `/api/equipment/windows/run-program` |
| LeRobot GUI | `/lerobot` | `lerobot.html` | ROBOTIS teleop/record/train/rollout, 포트/카메라 구성, 조작 agent bridge, manipulation 연동 | `/api/lerobot/config`, `/api/lerobot/ports*`, `/api/lerobot/camera/test`, `/api/lerobot/teleoperate/*`, `/api/lerobot/record/*`, `/api/lerobot/train/*`, `/api/lerobot/rollout/*`, `/api/lerobot/manipulation-agent/*` |

---

## 5) 에이전트/모듈별 상세 (입력·출력·툴)

각 에이전트는 `graphs/modules/<agent>/module.yaml`의 모듈 메타데이터(핸들러/LLM 역할/툴 allowlist/pre_execution/internal_graph)를 따릅니다.

### Design Agent (`modules/design`, `agent.design_agent`)
- **목적**: 실험 목표를 기술 가능한 시편 설계 스펙으로 정규화
- **핵심 툴**: `agent.orchestrator_agent` (pre_execution: `orchestrator_plan`)
- **주요 결과**: `state.current_experiment_spec`, `state.current_experiment_objective`, `experiment_spec`
- **핵심 상태 값**: 시편 크기·재료·제약조건·메트릭

### Specimen Making Agent (`modules/specimen`, `agent.specimen_agent`)
- **목적**: STL/제조 메타데이터 생성 및 제조 브릿지 handoff
- **핵심 툴**: `geometry.generate_metamaterial_stl`, `geometry.check_mesh_quality`, `geometry.check_manufacturability`, `artifact.create_specimen_handoff`, `experiment.evaluate`, `printer.prepare`
- **주요 결과**: `specimen_result`, `protocol_note`, `state.current_experiment_spec`의 제조 반영값( layer/nozzle/profile/옵션 )
- **실행 특성**: STL 뷰어 렌더링은 보조적; 제조 상태와 아티팩트 전달이 핵심

### Vision Agent (`modules/vision`, `agent.vision_agent`)
- **목적**: 촬영/상태 관측 및 후단 조작용 관측값 생성
- **핵심 툴**: `camera.capture`
- **필수 결과 키**: `observation`

### Manipulation Agent (`modules/manipulation`, `agent.manipulation_agent`)
- **목적**: 로봇 조작 계획/실행, 시편 이동 연동
- **핵심 툴**: `lerobot.rollout.start`, `robot.pick_place`
- **주요 결과**: `manipulation`, `sarm`, `protocol_note`
- **연계**: `/api/lerobot/manipulation-agent/*` 및 직접 레로봇 워크스페이스 동작과 연동

### Lab Equipment Agent (`modules/equipment`, `agent.equipment_agent`)
- **목적**: 실험장비(Windows 브릿지, UTM 매크로) 제어 handoff
- **핵심 툴**: `equipment.pyautogui.health`, `equipment.pyautogui.list_programs`, `equipment.pyautogui.run`, `utm.run_protocol`
- **필수 결과 키**: `equipment_result`, `protocol_note`

### Analysis Agent (`modules/analysis`, `agent.analysis_agent`)
- **목적**: Lab Equipment raw UTM artifact를 표준 분석 기록과 BO-ready handoff로 변환
- **핵심 툴**: `cae.run_static_analysis`, `fenicsx.health`, `fenicsx.run_linear_elasticity`
- **주요 결과**: `analysis`, `bo_observation`, `bo_handoff`, `experiment_evaluation`, `knowledge_payload`
- **주요 아티팩트**: `canonical_curve.csv`, `quality_report.json`, `metrics.json`, `fem_result.json`, `fem_agentic_loop.json`, `fem_utm_comparison.json`, `experiment_evaluation.json`, `bo_handoff.json`
- **FEniCSx loop**: `analysis_fem_planning` LLM이 tutorial-style FEM 계획을 만들고, Agent가 sanitization 후 `fenicsx.health`/`fenicsx.run_linear_elasticity`를 반복 호출한다. 실제 solve는 bridge의 `runtime_solver_enabled=true`일 때 `scripts/fenicsx_linear_elasticity_template.py`가 conda/docker FEniCSx에서 수행한다. 기본 TEST loop는 빠른 deterministic bridge를 쓴다.
- **주의**: UTM은 `utm_high` 실측값이고 FEniCSx/CAE는 `fem_low` simulation evidence다. FEM 예측을 실측 BO observation처럼 넣지 않는다. LLM이 임의 solver 코드를 실행하지 않는다.

### Knowledge Agent (`modules/knowledge`, `agent.knowledge_agent`)
- **목적**: 실패/성능 이력 요약 후 다음 후보/지침 반영
- **주요 결과**: `knowledge` (메모리 갱신, 실패 패턴, 최근 결과 요약)

### BO Agent (`modules/bo`, `agent.bo_agent`)
- **목적**: Analysis/Knowledge evidence와 실패 memory를 읽고 numeric BO + LLM reasoning soft prior로 다음 Design 후보를 추천
- **핵심 툴**: `experiment.benchmark`
- **LLM 역할**: `bo_policy` strict JSON reasoning(`bo_reasoning_v1`)을 생성하되 최종 후보 결정권은 numeric acquisition/validator/failure penalty에 둠
- **주요 결과**: `bo_result`, `candidate_pool`, `candidate_ranking`, `next_design_request.v1`, `run_metadata["bo_recommended_constraints"]`
- **GUI 표시**: Live GUI와 `/bo`에서 evidence intake, hypotheses, strategy, candidate ranking, recommendation, reasoning/artifact 경로를 표시
- **주의**: BO Agent는 printer/robot/equipment를 직접 실행하지 않으며, 추천 후보는 Design Agent와 Guardian의 후속 검증 대상임

### Guardian Agent (`modules/guardian`, `agent.guardian_agent`)
- **목적**: 안전성/진행성 검증 후 다음 액션 결정
- **핵심 툴**: `device.health`, `experiment.queue.status`
- **결정값**: `continue`, `stop`, `error`(stage decision)

---

## 6) 이벤트로 루프 확인하기(트러블슈팅)

- 루프가 안도는 것처럼 보일 때 우선 아래를 확인
  1. `POST /api/run/start` 응답에 `run_id`가 있는지
  2. `GET /api/runs/{run_id}`에서 `active=True`/`is_running=True`
  3. `/api/runs/{run_id}/events` 또는 SSE 스트림에서 `node.started`/`edge.traversed`/`run.complete`가 연속으로 나오는지
- 루프 진입 직후 `idle`에서 멈춰 있으면 `guardian/디펄트 런치`가 아니라 대부분 **실행 단계가 완료되지 못한 precondition 문제**(설비 게이트/검증 실패)입니다.
- `live`에서 바로 종료되면 대부분 `safe_stop_requested` 또는 `stop_requested`가 true 상태로 설정됐는지 확인하세요.

---

## 7) 운영 권장 워크플로우(초간단)

### 테스트 모드
1. Live GUI에서 목표 입력 또는 테스트 모드 명령
2. `POST /api/run/start`(mode=test)
3. `run` 이벤트 확인 후 단계별 메시지/아티팩트 확인
4. 완료 후 `guardian`이 continue인지 stop인지 점검

### 실모드
1. 장비/브릿지 게이트와 모델/연결 상태 점검
2. Live 대화에서 실험 명령(예: `실험 수행`)
3. `specimen` 이후 장비 단계 전이에서 `prusa/robot/wrapper` gate 상태 확인
4. `guardian` 결정 및 다음 루프로 재진입 여부 확인

---

## 8) 참고문서

- [runtime/langgraph_runtime.md](langgraph_runtime.md)
- [runtime/agent_program_baseline.md](agent_program_baseline.md)
- [docs/process/codex_workflow.md](../process/codex_workflow.md)
- [runtime/autonomous_experiment_runtime.md](autonomous_experiment_runtime.md)
- [gui/gui.md](../gui/gui.md)

---

## 9) 코드 위치별 빠른 추적표

| 확인하고 싶은 것 | 파일/폴더 |
|---|---|
| 서버 route 전체 | `app/main.py` |
| 기본 폐루프 그래프 | `graphs/configs/atr_closed_loop.yaml` |
| 그래프 검증 규칙 | `graphs/validator.py` |
| 그래프 compile/adapter | `graphs/compiler.py`, `graphs/generated_adapter.py` |
| 모듈 registry | `graphs/registry.py` |
| Live GUI 화면 | `web/templates/planning.html`, `web/static/planning.js` |
| Main GUI 화면 | `web/templates/index.html`, `web/static/app.js` |
| Runtime IDE | `web/templates/runtime_ide.html`, `web/static/runtime_ide.js` |
| Module Management | `web/templates/module_management.html`, `web/static/module_management.js` |
| 3DP GUI | `web/templates/printer.html`, `web/static/printer.js` |
| LeRobot GUI | `web/templates/lerobot.html`, `web/static/lerobot.js` |
| BO GUI | `web/templates/bo.html`, `web/static/bo.js` |
| CAE GUI | `web/templates/cae.html`, `web/static/cae.js` |
| Windows bridge GUI | `web/templates/windows_equipment.html`, `web/static/windows_equipment.js` |
| Self-Evolution Lab | `web/templates/evolution_lab.html`, `web/static/evolution_lab.js` |

## 10) 루프가 안 도는 것처럼 보일 때 보는 순서

1. `POST /api/run/start` 응답에서 `ok`, `run_id`, `mode`를 확인한다.
2. `GET /api/runtime/state`에서 `is_running`, `stage`, `run_id`를 확인한다.
3. `GET /api/runs/{run_id}/events`에서 `node.started`와 `node.completed`가 stage별로 이어지는지 확인한다.
4. `guardian` 단계 직후 `complete/error`로 빠졌다면 `guardian_decision`, `approval`, `failure_code`를 먼저 본다.
5. Live GUI가 오래된 상태를 보여주면 `/api/events/stream` heartbeat와 `GET /api/events/recent`를 비교한다.
6. 장비 단계에서 멈추면 해당 workspace의 저장 설정(`memory/*`)과 bridge status API를 확인한다.

## 11) 협업자에게 설명할 때 한 문장 요약

이 프로젝트는 `graphs/configs/atr_closed_loop.yaml`에 정의된 stage graph를 FastAPI runtime이 실행하고, 각 stage는 `graphs/modules/*`의 agent module을 통해 LLM/tool/device bridge를 호출하며, Live GUI와 Runtime IDE가 같은 runtime state/event/artifact API를 공유하는 구조입니다.

