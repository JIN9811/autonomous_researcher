# 12. 자유 모듈화 갭 분석 및 개선안

대상: Live GUI 카드/구성요소, LangGraph, Runtime IDE, agent module, device bridge, generated adapter, draft module flow

작성 기준:

- 실제 GUI 확인: Browser plugin으로 `http://127.0.0.1:7860/live` 접속
- 확인 화면: 기본 viewport, 1365x768, 390x844
- 확인 상호작용: Graph -> Report view 전환, DSN agent report 선택
- API 확인: `/api/state`, `/api/modules`, `/api/handlers`, `/api/graphs/atr_closed_loop`
- 코드 확인: `web/templates/planning.html`, `web/static/planning.js`, `web/static/styles.css`, `web/static/runtime_ide.js`, `app/main.py`, `app/bootstrap.py`, `app/controller.py`, `agents/*`, `orchestrator/*`, `graphs/*`, `device_bridges/*`

---

## 0. 검증 범위와 완료 감사

이 문서에서 말하는 "코드 한줄한줄 확인"은 레포의 모든 파일 721개를 무차별 완독했다는 뜻이 아니라, **자유 모듈화 여부를 결정하는 frontend/backend 실행 경로를 파일 단위와 라인 단위로 추적했다**는 뜻으로 적용한다.

모듈 추가/삭제 자유도에 직접 영향을 주는 핵심 파일은 다음 범위로 확인했다.

| 영역 | 확인 파일 | 라인 수 | 확인 이유 |
|---|---:|---:|---|
| Live GUI shell | `web/templates/planning.html` | 193 | `/live` DOM skeleton, center view, chat, binder, bottom dock |
| Live GUI runtime | `web/static/planning.js` | 11406 | `LIVE_AGENTS`, agent binder, report/backend/graph/artifact/timeline renderer |
| Live GUI style | `web/static/styles.css` | 16102 | card, binder, graph, responsive, chat collapse styling |
| Runtime IDE frontend | `web/static/runtime_ide.js` | 7061 | graph/module/bridge contract rendering and module management |
| API/runtime contract | `app/main.py` | 8434 | `/api/state`, `/api/modules`, `/api/graphs`, generated adapter, bridge APIs |
| Controller flow | `app/controller.py` | 6644 | fixed planning flow, stage tail, report/event generation |
| Bootstrap | `app/bootstrap.py` | 294 | hardcoded agent registration |
| State model | `orchestrator/state.py` | 72 | fixed `Stage` enum |
| Supervisor | `orchestrator/supervisor.py` | 1007 | `STAGE_AGENT`, required outputs, fixed stage policy |
| LangGraph runtime | `orchestrator/langgraph_runtime.py` | 2678 | stage coercion, handler registration, module binding |
| Graph schema | `graphs/schema.py` | 305 | `GraphConfig`, `ModuleConfig`, `stage_dispatch`, transition candidates |
| Graph compiler | `graphs/compiler.py` | 147 | executable vs non-executable graph nodes/edges |
| Module store | `graphs/module_store.py` | 142 | module versioning and active `module.yaml` writes |
| Generated adapter | `graphs/generated_adapter.py` | 158 | safe generated handler validation and approval |
| Agent base | `agents/base_agent.py` | 188 | `AgentResult`, `AgentContext`, `BaseAgent` contract |
| Agent registry | `agents/registry.py` | 32 | current register/get/name-only registry |
| Main graph config | `graphs/configs/atr_closed_loop.yaml` | 876 | stages, transitions, runtime planes, bridge metadata |
| Example module | `graphs/modules/design/module.yaml` | 63 | agent module contract shape |
| Example module | `graphs/modules/equipment/module.yaml` | 33 | tool/bridge-linked module shape |
| Example module | `graphs/modules/orchestrator/module.yaml` | 103 | supervisor/control-plane module contract |

실제 GUI 검증은 Browser plugin으로 수행했다.

- `http://127.0.0.1:7860/live` 접속
- page title `Live GUI` 확인
- console `error/warn` 확인 시점 기준 없음
- 기본 viewport, 1365x768, 390x844 화면 확인
- center view 5개 모두 실제 전환 확인:
  - `Report`
  - `Backend`
  - `Graph`
  - `Artifacts`
  - `Timeline`
- agent binder 10개 모두 실제 선택 확인:
  - `orchestrator`
  - `design`
  - `specimen`
  - `vision`
  - `manipulation`
  - `equipment`
  - `analysis`
  - `knowledge`
  - `bo`
  - `guardian`
- `DSN` agent 선택 후 `Design Agent · Report` 표시 확인
- viewport override reset 완료

실제 API 검증은 실행 중인 서버에서 수행했다.

- `/api/state`: `runtime_ide_contract.ok=true`, module 10개, runtime plane 4개, bridge 5개
- `/api/modules`: module 10개 확인
- `/api/handlers`: handler 15개, `module.generated_adapter` 포함
- `/api/graphs/atr_closed_loop`: node 18개, edge 64개, stage dispatch와 bridge metadata 확인

이 감사 결과, 문서의 결론은 다음 근거 위에서 작성됐다.

- frontend 병목은 `planning.js`의 hardcoded agent/card/report renderer에 있다.
- backend 병목은 fixed `Stage` enum, bootstrap registration, controller/supervisor fixed stage policy에 있다.
- graph/module/Runtime IDE/generated adapter 쪽은 이미 모듈화를 지탱할 기반이 있다.
- 위 대화에서 논의한 "agent 폴더에 전부 넣지 말고 `graphs/modules/<agent>/`를 manifest root로 승격"과 "empty module보다는 안전한 draft module template 필요"를 개선안에 반영했다.

---

## 1. 결론

현재 구조는 **자유 모듈화가 가능한 방향으로 이미 절반 이상 가 있다.**

특히 backend 쪽은 `graphs/modules/<module>/module.yaml`, `graphs/configs/atr_closed_loop.yaml`, `ModuleConfigStore`, `GraphConfig`, Runtime IDE API, generated adapter 승인 구조가 있어서 모듈화의 뼈대가 있다.

하지만 지금 상태로는 아직 **원하는 대로 agent를 추가/삭제하면 GUI 카드, LangGraph, bridge, runtime 실행까지 자동으로 따라오는 구조는 아니다.**

가장 큰 병목은 다음 세 군데다.

1. Live GUI가 module contract를 source of truth로 쓰지 않고, `planning.js` 안의 고정 agent 목록과 agent별 renderer 함수에 강하게 묶여 있다.
2. Backend runtime은 graph YAML을 읽지만, 실행 stage는 `orchestrator.state.Stage` enum과 `app/controller.py`, `orchestrator/supervisor.py`의 고정 stage 분기에 아직 묶여 있다.
3. module 생성은 가능하지만, 사용자가 직접 채워 넣는 안전한 `draft/empty module template` 개념이 아직 명확하지 않다.

따라서 개선 방향은 **새 agent 폴더에 모든 파일을 몰아넣는 방식이 아니라, 현재의 `graphs/modules/<agent>/`를 agent manifest root로 승격시키는 방식**이 맞다.

---

## 2. 실제 GUI 확인 결과

### 2.1 `/live` 로드 상태

Browser plugin으로 `http://127.0.0.1:7860/live`를 열었고, page title은 `Live GUI`로 확인됐다.

Console `error/warn` 로그는 확인 시점 기준 비어 있었다.

### 2.2 화면에서 확인된 현재 구조

1365x768 화면에서 다음 구성이 실제로 보였다.

- 상단 runtime status bar
- 왼쪽 `AGENT` binder
- 중앙 `Report / Backend / Graph / Artifacts / Timeline` view tab
- Graph view의 LangGraph map
- runtime plane, bridge plane, evidence plane
- 하단 event/device dock

390x844 화면에서도 화면이 로드되고 horizontal overflow는 없었다. 다만 모바일에서는 정보가 많이 축약되고, agent card와 graph/report 영역이 강하게 중앙 CSS/JS에 의존한다.

### 2.3 상호작용 확인

`Report` 탭 클릭 후 active tab이 `Report`로 바뀌는 것을 확인했다.

`DSN` agent binder를 클릭하면 중앙 title이 `Design Agent · Report`로 바뀌고, Design 전용 report card가 표시됐다.

이것은 agent별 특화 화면이 이미 존재한다는 뜻이다. 다만 이 특화가 module descriptor 기반이 아니라 `planning.js` 내부 함수와 switch/map 구조에 들어 있다.

---

## 3. 현재 API/contract 상태

### 3.1 Runtime IDE contract

`/api/state`의 `runtime_ide_contract` 확인 결과:

- `ok`: true
- `graph_id`: `atr_closed_loop`
- `graph_version`: `0.2.0`
- `module_contracts`: 10개
- `runtime_planes`: 4개
- `device_bridges`: 5개
- `active_stage`: `complete`
- source endpoints:
  - `/api/graphs/atr_closed_loop`
  - `/api/modules`
  - `/api/state`
  - `/api/devices/state`
  - `/api/guardian/status`

즉 backend는 이미 GUI/IDE가 읽을 수 있는 module/graph/bridge contract를 내려주고 있다.

### 3.2 Module catalog

`/api/modules` 확인 결과 module은 10개다.

- analysis
- bo
- design
- equipment
- guardian
- knowledge
- manipulation
- orchestrator
- specimen
- vision

각 module은 `module.yaml`로 관리되며 `handler`, `category`, `tools`, `io_contract`, `runtime_contract`, `device_bridge_contracts` 등을 가질 수 있다.

### 3.3 Handler catalog

`/api/handlers` 확인 결과 handler는 15개다.

- `agent.analysis_agent`
- `agent.bo_agent`
- `agent.design_agent`
- `agent.equipment_agent`
- `agent.guardian_agent`
- `agent.knowledge_agent`
- `agent.manipulation_agent`
- `agent.orchestrator_agent`
- `agent.specimen_agent`
- `agent.vision_agent`
- `module.generated_adapter`
- `runtime.dispatch`
- `runtime.idle`
- `runtime.step_complete`
- `runtime.terminal`

`module.generated_adapter`가 있다는 점은 중요하다. 새 module 실행을 안전하게 붙일 수 있는 통로는 이미 있다.

### 3.4 Graph catalog

`/api/graphs/atr_closed_loop` 확인 결과:

- nodes: 18개
- edges: 64개
- stage dispatch:
  - idle
  - design
  - specimen
  - vision
  - manipulation
  - equipment
  - analysis
  - knowledge
  - bo
  - guardian
  - complete
  - error
- bridge metadata:
  - prusa_bridge
  - lerobot_bridge
  - windows_pyautogui_bridge
  - fenicsx_cae_bridge
  - camera_utm_bridge

즉 graph 자체는 executable stage와 non-executable plane/bridge/evidence overlay를 함께 표현할 수 있다.

---

## 4. 이미 좋은 구조

### 4.1 `graphs/modules/<agent>/module.yaml`

예시:

- `graphs/modules/design/module.yaml`
- `graphs/modules/equipment/module.yaml`
- `graphs/modules/orchestrator/module.yaml`

이 파일들은 agent의 label, handler, tools, safety, internal graph, IO contract를 이미 들고 있다.

이 구조는 유지하는 것이 좋다. 새로 `agents/design/` 아래에 UI, bridge, graph를 전부 몰아넣는 것보다 현재 구조가 낫다.

이유:

- `agents/*.py`는 실행 로직이다.
- `graphs/modules/*/module.yaml`은 runtime/editor/GUI contract다.
- `graphs/configs/*.yaml`은 orchestration graph다.
- `device_bridges/*`는 실제 bridge 구현이다.

이 경계를 지키는 편이 장기적으로 덜 꼬인다.

### 4.2 `GraphConfig`

`graphs/schema.py`의 `GraphConfig`는 다음을 이미 갖고 있다.

- `nodes`
- `edges`
- `stage_dispatch`
- `transitions`
- `terminal_stages`
- `metadata`
- `transition_candidates()`

즉 graph를 YAML/config로 조립할 수 있는 기본 모델은 있다.

### 4.3 non-executable graph plane

`graphs/compiler.py`에는 다음 개념이 있다.

- non-executable edge:
  - `logical_transition`
  - `control_overlay`
  - `device_bridge`
  - `evidence_flow`
  - `runtime_sidecar`
- non-executable node kind:
  - `sidecar`
  - `control_plane`
  - `bridge`
  - `evidence_plane`

이 구조 덕분에 LangGraph 실행 노드와 GUI/IDE 시각화 노드를 분리할 수 있다.

### 4.4 Runtime IDE는 이미 config-driven에 가깝다

`web/static/runtime_ide.js`는 `DISPLAY_EDGE_TYPES`, `nodeRuntimeContractMarkup()`, `renderRuntimeContractMap()` 등을 통해 graph/module/bridge contract를 비교적 잘 읽는다.

즉 Runtime IDE는 Live GUI보다 훨씬 모듈화에 가깝다.

### 4.5 generated adapter 안전 모델

`graphs/generated_adapter.py`는 generated Python을 바로 실행하지 않는다.

필수 조건:

- `handler = module.generated_adapter`
- `metadata.generated_adapter_approved = true`
- `metadata.pending_handler_registration = false`
- `handler.py` static validation 통과
- blocked import 차단
- `async run(state, ctx)` 필요

이건 좋은 안전 모델이다. 자유 모듈화에 반드시 필요하다.

---

## 5. Frontend 부족한 점

### 5.1 Live GUI agent 목록이 하드코딩이다

`web/static/planning.js`의 `LIVE_AGENTS`가 agent id, label, short, stage, icon path를 직접 들고 있다.

문제:

- `/api/modules`에 module이 추가되어도 binder에 자동 반영되지 않는다.
- graph YAML에서 stage가 바뀌어도 GUI가 자동으로 따라오지 않는다.
- agent 제거 시 `LIVE_AGENTS`, report renderer, dashboard renderer, chat policy 등을 동시에 수정해야 한다.

개선:

- backend가 `AgentManifest[]`를 내려줘야 한다.
- Live GUI는 `LIVE_AGENTS` 대신 manifest를 source of truth로 써야 한다.

### 5.2 agent별 card renderer가 중앙 파일에 박혀 있다

`planning.js`에는 다음과 같은 agent별 함수가 있다.

- `renderOrchestratorDashboardCards`
- `renderDesignDashboardCards`
- `renderSpecimenDashboardCards`
- `renderVisionDashboardCards`
- `renderManipulationDashboardCards`
- `renderEquipmentDashboardCards`
- `renderAnalysisDashboardCards`
- `renderKnowledgeDashboardCards`
- `renderBoDashboardCards`
- `renderGuardianDashboardCards`

그리고 `renderAgentSpecializedDashboardSections()` 내부의 `cardsByAgent`가 이들을 직접 매핑한다.

문제:

- 새 agent가 추가되어도 specialized card가 자동 생성되지 않는다.
- card 추가/삭제가 code edit이다.
- UI-only module이나 draft module preview가 어렵다.

개선:

- 공통 card primitive를 유지한다.
- agent별 card 구성은 `module.yaml` 또는 `ui.yaml` descriptor로 뺀다.
- 정말 특수한 경우만 optional custom renderer를 둔다.

### 5.3 report detail도 중앙 switch 구조다

`renderAgentSpecificReportSection()`은 `liveSelectedAgent === "design"` 같은 조건으로 agent별 detail renderer를 붙인다.

문제:

- report 구성이 agent module contract와 분리되어 있다.
- output contract가 바뀌어도 GUI가 자동으로 맞춰지지 않는다.

개선:

- report section도 descriptor 기반으로 바꾼다.
- descriptor가 없는 module은 generic workcell card를 사용한다.

### 5.4 chat 정책이 agent id set에 묶여 있다

`liveAgentNeedsChatPanel()`은 `objective`, `orchestrator`만 chat panel이 필요하다고 판단한다.

문제:

- 새 control-plane agent가 생기면 code edit이 필요하다.
- UI-only module, bridge module, supervisor module의 chat 필요 여부를 module contract에서 표현할 수 없다.

개선:

- `ui.chat.mode` 또는 `runtime_contract.chat_policy`를 manifest에 둔다.

예시:

```yaml
ui:
  chat:
    mode: persistent
    collapsible: true
```

또는:

```yaml
ui:
  chat:
    mode: open_on_demand
```

### 5.5 CSS가 component contract가 아니라 전역 class patch 중심이다

`web/static/styles.css`에 Live GUI 관련 CSS가 매우 많이 누적되어 있다.

문제:

- agent별 카드 디자인을 추가하려면 전역 CSS class를 계속 늘리게 된다.
- card type별 responsive rule이 명확하지 않다.
- module descriptor가 `span`, `priority`, `density`, `mobile_behavior` 같은 표시 의도를 내려도 이를 받을 renderer 계층이 없다.

개선:

- CSS token과 card primitive를 먼저 분리한다.
- card descriptor는 layout intent만 가진다.
- renderer가 intent를 class로 변환한다.

---

## 6. Backend 부족한 점

### 6.1 `Stage` enum이 고정이다

`orchestrator/state.py`의 `Stage` enum은 다음 값으로 고정되어 있다.

- idle
- design
- specimen
- vision
- manipulation
- equipment
- analysis
- knowledge
- bo
- guardian
- complete
- error

문제:

- graph YAML에 새 stage를 넣어도 `Stage(new_stage)`에서 실패한다.
- `orchestrator/langgraph_runtime.py`의 `_coerce_stage()`도 `return Stage(stage_value)`라서 unknown stage를 허용하지 않는다.
- 진짜 자유 모듈화에는 stage를 enum이 아니라 runtime string 또는 validated registry로 바꿔야 한다.

개선:

- 단기: 기존 Stage enum을 유지하되 extension stage는 `runtime_custom_stage`로 mapping한다.
- 중기: `Stage`를 `RuntimeStage` value object로 교체한다.
- 장기: graph config의 `stage_dispatch`가 stage registry의 source of truth가 된다.

### 6.2 agent registry는 있으나 bootstrap은 고정 등록이다

`agents/registry.py`의 `AgentRegistry`는 `register()`와 `get()`을 제공한다.

하지만 `app/bootstrap.py`에서 agent를 다음처럼 직접 등록한다.

- OrchestratorAgent
- BOAgent
- DesignAgent
- SpecimenMakingAgent
- VisionAgent
- ManipulationAgent
- LabEquipmentAgent
- AnalysisAgent
- KnowledgeAgent
- GuardianAgent

문제:

- 새 agent class를 추가해도 bootstrap 수정 없이는 agent registry에 들어오지 않는다.
- `unregister()`도 없다.
- module enable/disable과 실제 runtime registry가 연결되어 있지 않다.

개선:

- allowlisted Python agent는 계속 bootstrap에서 명시 등록해도 된다.
- 다만 module registry에는 `execution_capability`를 둔다.

예시:

```yaml
execution:
  capability: allowlisted_agent
  handler: agent.design_agent
```

또는:

```yaml
execution:
  capability: generated_adapter
  handler: module.generated_adapter
```

또는:

```yaml
execution:
  capability: ui_only
  handler: runtime.step_complete
```

### 6.3 supervisor가 stage별 output contract를 하드코딩한다

`orchestrator/supervisor.py`에는 다음이 고정되어 있다.

- `STAGE_AGENT`
- `REQUIRED_OUTPUTS`
- `BASE_ROUTE`
- stage별 follow-up opinion 분기
- stage별 nested output key

문제:

- 새 agent output contract가 module.yaml에 있어도 supervisor가 자동으로 알지 못한다.
- Guardian/supervisor report는 새 module을 generic하게 평가하기 어렵다.

개선:

- `REQUIRED_OUTPUTS`는 module `output_contracts` 또는 `io_contract.required_outputs`에서 읽는다.
- stage별 opinion은 `supervisor_policy` descriptor로 이동한다.

예시:

```yaml
supervisor_policy:
  required_outputs:
    - design_candidate
    - experiment_spec
    - handoff_packet
  handoff_key_candidates:
    - handoff_packet
    - design_report.handoff_to_specimen
  concern_rules:
    - id: missing_required_fields
      selector: design_report.handoff_to_specimen.missing_required_fields
      severity: warning
```

### 6.4 controller에 고정 planning flow가 많다

`app/controller.py`는 Design -> Specimen -> tail -> Guardian 흐름을 직접 처리한다.

문제:

- graph config가 바뀌어도 controller의 planning orchestration 분기가 완전히 일반화되어 있지 않다.
- `_planning_tail_start_stage()`, `_planning_tail_stages()`, `_format_planning_stage_message()` 등은 기존 ATR agent set을 전제로 한다.

개선:

- controller는 graph executor와 event broadcaster 역할만 맡는다.
- stage별 message formatting은 module descriptor 또는 generic formatter로 이동한다.

### 6.5 empty/draft module이 없다

현재 `/api/modules` POST는 module 생성이 가능하지만 `RuntimeModuleCreateRequest`는 source upload/LLM transform 흐름에 가깝다.

문제:

- 사용자가 빈 module을 만들고 GUI에서 카드/입출력/bridge를 하나씩 채우는 UX가 아니다.
- `ModuleConfig`는 `handler`가 필수 non-empty라서 완전 empty module은 schema상 애매하다.
- draft 상태, enabled 상태, graph 연결 전 상태가 명시적이지 않다.

개선:

`empty module`이 아니라 `draft module template`을 도입한다.

필수 속성:

```yaml
module:
  id: my_new_agent
  label: My New Agent
  status: draft
  enabled: false
  handler: runtime.step_complete
  execution:
    capability: ui_only
    active: false
  graph:
    attached: false
    stage: null
    node_id: null
  ui:
    cards: []
    report_sections: []
  tools: []
  device_bridge_contracts: []
  output_contracts: []
  io_contract:
    input: ""
    output: ""
  safety:
    dry_run_supported: true
    live_requires_validation: true
    requires_human_approval: true
```

이 상태는 실행되면 안 된다. GUI preview와 contract editing만 가능해야 한다.

---

## 7. 권장 구조

### 7.1 현재 구조를 살린 target layout

```text
graphs/modules/design/
  module.yaml
  ui.yaml
  fixtures.json

agents/
  design_agent.py

graphs/configs/
  atr_closed_loop.yaml

device_bridges/
  lerobot_bridge.py
  prusa_bridge.py
  windows_pyautogui_bridge.py

web/static/live_gui/
  manifest_store.js
  component_registry.js
  card_primitives.js
  report_composer.js
  graph_renderer.js
  bridge_renderer.js
  chat_policy.js
  agent_custom_renderers/
    design.js
    equipment.js
```

핵심은 `graphs/modules/<agent>/`가 agent manifest root가 되는 것이다.

### 7.2 `module.yaml`과 `ui.yaml` 역할 분리

`module.yaml`:

- runtime identity
- handler
- tools
- bridge contract
- output contract
- safety
- execution capability
- graph binding

`ui.yaml`:

- card layout
- report section order
- chart/visualization descriptors
- empty state
- mobile priority
- chat policy
- icon/label override

예시:

```yaml
ui:
  icon: /static/live_gui_icons/design_agent.svg
  short: DSN
  report_title: Design Agent
  chat:
    mode: open_on_demand
  cards:
    - id: selected_candidate
      type: metric_group
      title: Design Decision
      span: 4
      tone: design
      selectors:
        selected: design_candidate.candidate_id
        score: design_candidate.score
        risk: design_candidate.risk
      empty: No candidate selected yet.
    - id: candidate_chart
      type: chart
      chart: scatter
      title: Candidate Portfolio
      data_selector: design_report.candidates
      x: mass_g
      y: predicted_strength
      color: risk
      empty: No chartable design candidates yet.
```

### 7.3 `AgentManifest` 통합 payload

Backend가 graph/module/ui를 합쳐 Live GUI용 manifest를 내려줘야 한다.

예시:

```json
{
  "id": "design",
  "label": "Design Agent",
  "short": "DSN",
  "stage": "design",
  "module_id": "design",
  "handler": "agent.design_agent",
  "kind": "agent",
  "enabled": true,
  "execution_capability": "allowlisted_agent",
  "icon": "/static/live_gui_icons/design_agent.svg",
  "chat": { "mode": "open_on_demand" },
  "cards": [],
  "bridge_refs": [],
  "output_contracts": [],
  "io_contract": {},
  "graph_node_id": "design"
}
```

권장 endpoint:

```text
GET /api/runtime/agent-manifests
GET /api/modules/{module_id}/ui
PUT /api/modules/{module_id}/ui
POST /api/modules/templates/agent
POST /api/modules/templates/ui-only
POST /api/modules/templates/bridge
```

---

## 8. 추가/삭제 플로우

### 8.1 새 UI-only module 추가

```text
Create Draft Module
-> ui.yaml 카드 구성
-> preview fixtures로 Live GUI 확인
-> graph에는 연결하지 않음
-> enabled=false 유지
```

### 8.2 새 executable agent 추가

```text
Create Draft Module
-> module.yaml IO/tools/output contract 작성
-> handler 선택
   - allowlisted agent
   - generated_adapter
   - runtime.step_complete placeholder
-> generated adapter면 static validation + approval
-> graph node/edge 연결
-> graph validate
-> module dry-run
-> graph dry-run
-> enable/load
```

### 8.3 agent 제거

```text
Disable module
-> graph에서 node/edge detach
-> stage_dispatch 제거
-> transition 후보 재검증
-> Live GUI manifest refresh
-> old artifacts/read-only history는 유지
```

삭제는 물리 파일 삭제보다 disable/detach가 먼저다. run history와 artifact trace가 깨지지 않아야 한다.

---

## 9. Bridge 모듈화

현재 bridge 정보는 graph metadata와 module tools, app/main.py endpoint에 흩어져 있다.

권장 bridge manifest:

```yaml
bridge:
  id: lerobot_bridge
  label: LeRobot / Pi0.5 Rollout
  workspace: /lerobot
  health_endpoint: /api/lerobot/config-status
  preflight_endpoint: /api/lerobot/profiles/validate
  tools:
    - lerobot.teleoperate.start
    - lerobot.record.start
    - lerobot.rollout.start
  actions:
    - id: validate_profile
      label: Validate Profile
      requires_confirmation: false
    - id: rollout_start
      label: Start Rollout
      requires_confirmation: true
  evidence_contracts:
    - robot_task_result.v1
    - camera_capture.v1
```

Bridge는 agent 폴더 안에 구현을 넣는 것보다 독립 registry가 낫다.

이유:

- 여러 agent가 같은 bridge를 쓴다.
- 장비 연결/토큰/health/preflight는 agent보다 긴 생명주기를 가진다.
- Live GUI는 bridge card를 agent report 안에도, device dock에도, Runtime IDE에도 재사용해야 한다.

---

## 10. 단계별 개선안

### Phase 1. Manifest layer 추가

목표:

- backend에서 graph + module + optional ui config를 합친 `AgentManifest[]` 제공
- Live GUI가 `LIVE_AGENTS` 대신 manifest를 읽을 준비

변경 대상:

- `app/main.py`
- `graphs/modules/*/module.yaml`
- `web/static/planning.js`

완료 기준:

- `/api/runtime/agent-manifests`가 existing 10 modules를 반환
- Live GUI binder가 manifest 기반으로 렌더링
- 기존 화면 기능 유지

### Phase 2. Card descriptor renderer

목표:

- agent별 dashboard card를 descriptor 기반으로 렌더링
- 기존 hardcoded renderer는 fallback/custom renderer로 격리

변경 대상:

- `web/static/planning.js` 분리
- `web/static/live_gui/card_primitives.js`
- `web/static/live_gui/component_registry.js`
- `graphs/modules/*/ui.yaml`

완료 기준:

- Design/Equipment/Guardian 중 최소 3개 agent가 descriptor card로 렌더링
- descriptor 없는 agent는 generic card fallback

### Phase 3. Draft module template

목표:

- empty/draft module을 GUI에서 만들고 수정 가능
- graph 연결 전에는 실행되지 않음

변경 대상:

- `app/main.py`
- `graphs/schema.py`
- `graphs/module_store.py`
- `web/static/runtime_ide.js`
- `web/static/module_management.js`

완료 기준:

- `POST /api/modules/templates/agent` 가능
- `status=draft`, `enabled=false`, `execution.capability=ui_only`
- Live GUI preview 가능
- graph validate에서 unattached draft는 실패가 아니라 inactive로 처리

### Phase 4. Runtime stage decoupling

목표:

- `Stage` enum 고정 의존을 줄임
- graph `stage_dispatch`가 runtime stage의 source of truth가 됨

변경 대상:

- `orchestrator/state.py`
- `orchestrator/langgraph_runtime.py`
- `orchestrator/supervisor.py`
- `app/controller.py`
- tests

완료 기준:

- unknown custom stage를 graph/module config에서 validation할 수 있음
- 기존 ATR stages는 backward compatible
- custom stage는 generic supervisor/report formatter로 처리

### Phase 5. Bridge registry

목표:

- bridge contract를 agent/module과 독립된 manifest로 관리
- Live GUI, Runtime IDE, device dock이 같은 bridge registry를 사용

변경 대상:

- `device_bridges/*`
- `app/main.py`
- `graphs/configs/*.yaml`
- `web/static/runtime_ide.js`
- `web/static/planning.js`

완료 기준:

- `/api/bridges` 제공
- bridge health/preflight/actions/evidence contract 표준화
- agent report card가 bridge manifest를 참조

---

## 11. 중요한 설계 원칙

### 11.1 agent folder에 모든 것을 넣지 않는다

나쁜 방향:

```text
agents/design/
  backend.py
  ui.js
  ui.css
  graph.yaml
  bridge.py
```

이 구조는 처음엔 모듈처럼 보이지만 곧 꼬인다.

이유:

- bridge는 여러 agent가 공유한다.
- graph는 orchestration 소유다.
- CSS와 card primitive는 공용 디자인 시스템 소유다.
- agent Python은 실행 로직이고 UI contract는 runtime/editor contract다.

좋은 방향:

```text
graphs/modules/design/
  module.yaml
  ui.yaml
  fixtures.json

agents/design_agent.py
device_bridges/...
graphs/configs/...
web/static/live_gui/...
```

### 11.2 UI descriptor와 custom renderer를 같이 둔다

모든 것을 YAML로만 만들면 복잡한 graph/chart/interaction에서 한계가 온다.

권장:

- 80%는 descriptor card
- 20%는 custom renderer
- custom renderer도 manifest id로 등록

### 11.3 실행 가능한 module과 표시 전용 module을 구분한다

모든 module이 agent일 필요는 없다.

module 종류:

- `agent`: 실행 agent
- `ui_only`: report/card/preview only
- `bridge`: device/software bridge
- `sidecar`: supervisor/control/evidence plane
- `evidence`: memory/RAG/artifact plane

### 11.4 draft는 실행되지 않아야 한다

draft module은 다음 조건을 만족해야 한다.

- graph에 연결되지 않음
- live execution 불가
- dry-run/preview만 가능
- generated adapter 승인 전 실행 불가
- handler가 placeholder면 `runtime.step_complete`만 허용

---

## 12. Definition of Done

자유 모듈화가 됐다고 말하려면 최소한 다음이 가능해야 한다.

1. Runtime IDE에서 draft agent module을 생성할 수 있다.
2. 그 module에 card/report descriptor를 추가하면 Live GUI binder/report에 preview로 나온다.
3. graph에 연결하지 않은 module은 실행되지 않는다.
4. graph에 연결한 module은 validate/dry-run gate를 통과해야 enable된다.
5. 기존 10개 agent는 manifest 기반으로 표시된다.
6. `planning.js`의 `LIVE_AGENTS`가 source of truth가 아니다.
7. agent별 card 추가/삭제가 JS 코드 수정 없이 가능하다.
8. 새 bridge는 bridge manifest 추가만으로 Runtime IDE와 Live GUI에 표시된다.
9. custom Python 실행은 generated adapter 승인 없이는 불가능하다.
10. 기존 closed-loop ATR flow는 backward compatible하게 유지된다.

---

## 13. 최종 판단

현재 구조를 버릴 필요는 없다.

오히려 현재 구조의 핵심인:

- `graphs/modules/*/module.yaml`
- `graphs/configs/*.yaml`
- Runtime IDE API
- generated adapter safety model
- graph non-executable plane 표현

이 부분은 그대로 살리는 것이 맞다.

바꿔야 할 것은 주로 다음이다.

- Live GUI가 hardcoded agent/card renderer를 버리고 manifest/descriptor 기반으로 바뀌어야 한다.
- backend runtime이 `Stage` enum과 stage별 controller/supervisor 분기를 점진적으로 config-driven으로 풀어야 한다.
- draft/empty module template을 명확히 만들고, 실행 불가 상태에서 UI와 contract를 먼저 설계할 수 있어야 한다.
- bridge를 agent 내부가 아니라 독립 manifest/registry로 관리해야 한다.

따라서 권장 구현 순서는:

```text
AgentManifest
-> Live GUI manifest renderer
-> ui.yaml card descriptor
-> draft module template
-> Stage decoupling
-> Bridge registry
```

이 순서가 가장 안전하다. GUI를 먼저 manifest 기반으로 바꾸면 사용자는 바로 agent 추가/삭제 UX를 느낄 수 있고, backend runtime decoupling은 이후에도 단계적으로 진행할 수 있다.
