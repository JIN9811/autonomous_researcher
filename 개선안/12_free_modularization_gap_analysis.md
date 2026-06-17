# 12. 자유 모듈화 갭 분석 및 개선안

대상: Live GUI 카드/구성요소, LangGraph, Runtime IDE, agent module, device bridge, generated adapter, draft module flow

작성 기준:

- 이전 GUI 확인: Browser plugin으로 `http://127.0.0.1:7860/live` 접속, 기본 viewport, 1365x768, 390x844, Graph -> Report 전환, DSN agent report 선택
- 이전 API 확인: `/api/state`, `/api/modules`, `/api/handlers`, `/api/graphs/atr_closed_loop`
- 현재 코드 재검증: 2026-06-17 기준 정적 코드 확인, `.venv` 기반 FastAPI app import, TestClient endpoint 확인, 그리고 Firefox/geckodriver 기반 브라우저 audit 재실행
- 코드 확인: `web/templates/planning.html`, `web/static/planning.js`, `web/static/styles.css`, `web/static/runtime_ide.js`, `app/main.py`, `app/bootstrap.py`, `app/controller.py`, `agents/*`, `orchestrator/*`, `graphs/*`, `device_bridges/*`
- 현재 route/API 기준 문서: `docs/runtime/current_code_snapshot.md`

주의: 이 문서는 개선 목표와 갭 분석을 담는다. 현재 코드가 실제로 노출하는
route/API/manifest/lifecycle 상태는 `docs/runtime/current_code_snapshot.md`가
우선이다. 2026-06-17 현재 FastAPI app import 기반 route scan 기준 FastAPI
`APIRoute` endpoint는 총 224개다. `/openapi.json`, `/docs`,
`/docs/oauth2-redirect`, `/redoc`, `/static`까지 포함한 전체 `app.routes`
등록 수는 229개이며, 이 숫자는 코드-문서 불일치 점검용 sanity check다.
단순 decorator grep는 multiline route와 FastAPI 등록 route를 놓칠 수
있으므로 현재 코드 기준 문서는 `docs/runtime/current_code_snapshot.md`의
검증 명령을 따른다.

---

## 0. 검증 범위와 완료 감사

이 문서에서 말하는 "코드 한줄한줄 확인"은 레포의 모든 파일 721개를 무차별 완독했다는 뜻이 아니라, **자유 모듈화 여부를 결정하는 frontend/backend 실행 경로를 파일 단위와 라인 단위로 추적했다**는 뜻으로 적용한다.

모듈 추가/삭제 자유도에 직접 영향을 주는 핵심 파일은 다음 범위로 확인했다.

| 영역 | 확인 파일 | 라인 수 | 확인 이유 |
|---|---:|---:|---|
| Live GUI shell | `web/templates/planning.html` | 218 | `/live` DOM skeleton, center view, chat, binder, bottom dock |
| Live GUI runtime | `web/static/planning.js` | 16390 | `LIVE_AGENTS`, agent binder, report/backend/graph/artifact/timeline renderer |
| Live GUI style | `web/static/styles.css` | 22442 | card, binder, graph, responsive, chat collapse styling |
| Runtime IDE frontend | `web/static/runtime_ide.js` | 7656 | graph/module/bridge contract rendering and module management |
| Module Management frontend | `web/static/module_management.js` | 1592 | module lifecycle, typed config editor, draft template UI |
| API/runtime contract | `app/main.py` | 14018 | `/api/state`, `/api/modules`, `/api/graphs`, generated adapter, bridge APIs |
| Controller flow | `app/controller.py` | 7348 | fixed planning flow, stage tail, report/event generation |
| Bootstrap | `app/bootstrap.py` | 328 | hardcoded agent registration |
| State model | `orchestrator/state.py` | 104 | `Stage` enum plus graph-validated custom-stage pseudo-member support |
| Supervisor | `orchestrator/supervisor.py` | 1251 | `STAGE_AGENT`, required outputs, fixed stage policy |
| LangGraph runtime | `orchestrator/langgraph_runtime.py` | 2831 | stage coercion, handler registration, module binding |
| Graph schema | `graphs/schema.py` | 366 | `GraphConfig`, `ModuleConfig`, `stage_dispatch`, transition candidates |
| Graph compiler | `graphs/compiler.py` | 171 | executable vs non-executable graph nodes/edges |
| Module store | `graphs/module_store.py` | 161 | module versioning and active `module.yaml` writes |
| Generated adapter | `graphs/generated_adapter.py` | 186 | safe generated handler validation and approval |
| Agent base | `agents/base_agent.py` | 224 | `AgentResult`, `AgentContext`, `BaseAgent` contract |
| Agent registry | `agents/registry.py` | 44 | current register/get/name-only registry |
| Main graph config | `graphs/configs/atr_closed_loop.yaml` | 876 | stages, transitions, runtime planes, bridge metadata |
| Example module | `graphs/modules/design/module.yaml` | 63 | agent module contract shape |
| Example module | `graphs/modules/equipment/module.yaml` | 33 | tool/bridge-linked module shape |
| Example module | `graphs/modules/orchestrator/module.yaml` | 103 | supervisor/control-plane module contract |

이전 실제 GUI 검증은 Browser plugin으로 수행했다. 현재 문서 갱신에서는
`.venv`의 FastAPI app import와 TestClient endpoint 응답을 재확인했고,
Firefox/geckodriver 기반 렌더링 브라우저 감사도 재실행했다.

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

이전 실제 API 검증은 실행 중인 서버에서 수행했다. 현재 코드 재검증에서는
TestClient로 endpoint와 manifest payload가 현재 코드에서 import/응답되는지
다시 확인했다.

- `/api/state`: `runtime_ide_contract.ok=true`, module 10개, runtime plane 4개, bridge 5개
- `/api/modules`: module 10개 확인
- `/api/handlers`: handler 15개, `module.generated_adapter` 포함
- `/api/graphs/atr_closed_loop`: nested `graph.nodes` 18개, `graph.edges` 64개, `graph.stage_dispatch` 12개와 bridge metadata 확인
- `/api/runtime/agent-manifests`: `ok=true`, `count=11`, `graph_id=atr_closed_loop`, `graph_version=0.2.0`
- `/api/bridges`: `ok=true`, bridge 5개(`prusa_bridge`, `lerobot_bridge`, `windows_pyautogui_bridge`, `cae_bridge`, `camera_utm_bridge`)
- `/api/runtime/models`: managed model 2개(`gemma4:31b`, `gemma4:e4b-it-nvfp4`)
- `/api/printer/fleet`: `active_profile_id=bambulab_x2d_lab_01`, `automatic_fallback=false`

현재 코드 기준 추가 확인:

- `web/static/planning.js`에는 fallback `DEFAULT_LIVE_AGENTS`가 남아 있지만, 초기화 시 `/api/runtime/agent-manifests`를 먼저 읽어 `LIVE_AGENTS`를 갱신한다.
- `/api/runtime/agent-manifests` endpoint가 추가되어 graph + module + optional `ui.yaml` descriptor를 병합한 manifest payload를 제공한다. 실제 반환은 bare array가 아니라 `ok`, `graph_id`, `graph_version`, `agents[]`, `count`, `categories`, `source_endpoints[]`를 포함한 dict다.
- `graphs/modules/design/ui.yaml`, `graphs/modules/equipment/ui.yaml`, `graphs/modules/guardian/ui.yaml`이 추가되어 descriptor card 렌더링 경로를 검증한다.
- `POST /api/modules/templates/{agent|ui-only|bridge}` endpoint가 추가되어 `status=draft`, `enabled=false`, graph unattached preview용 draft module을 생성한다.
- `GET/PUT /api/modules/{module_id}/ui` endpoint가 추가되어 module-local `ui.yaml` descriptor를 API로 읽고 저장할 수 있다.
- `/api/bridges` endpoint가 추가되어 graph metadata의 bridge registry를 normalized manifest로 제공한다.
- `/api/bridges`와 `/api/runtime/state.runtime_ide_contract.device_bridges`는 같은 normalized bridge shape를 사용한다. 현재 shape는 workspace, health/preflight endpoint, `actions[]`에 materialize된 standard/custom action descriptor, evidence contracts, health snapshot을 포함한다.
- `POST /api/bridges/{bridge_id}/actions`와 Runtime IDE Infra의 Custom Bridge Action editor가 추가되어 bridge action descriptor를 active graph metadata에 저장하고 graph version snapshot을 남길 수 있다. 이 경로는 `execution_scope=descriptor_only`이며 물리 실행은 하지 않는다.
- 커스텀 bridge action descriptor 저장 후 `/api/bridges`에 보이는 normalized action과 `/api/runtime/state.runtime_ide_contract.device_bridges`에 embedding된 action이 동일 객체로 반영되는지 단위 테스트로 확인했다. non-read-only/custom action은 `live_card_runnable=false`, `handoff_workspace=/equipment/windows`로 유지된다.
- generated adapter 승인 모델은 유지되어 있다.
- `ui.renderer` / custom renderer manifest id는 현재 allowlisted presentation profile로 부분 활성화되어 있다. `GET/PUT /api/modules/{module_id}/ui`가 `renderer.dashboard/report/fallback`을 정규화하고 `/api/runtime/agent-manifests`가 normalized `renderer`를 내려준다. `planning.js`는 `LIVE_RENDERER_PROFILES`와 `liveAgentRendererProfile()`로 이 metadata를 읽고 기존 built-in report/detail 및 dashboard/card renderer 선택에 사용한다. 단, 임의 외부 renderer/plugin 코드 실행은 아직 지원하지 않는다.
- 기존 workflow 회귀 검증은 `tests/integration/test_controller_run.py`, `tests/integration/test_stop_control.py`로 재실행했다. 결과는 `2 passed in 93.94s`다.
- 이번 문서 갱신 중에는 manifest/renderer/runtime layout 관련 파일 단위 suite도 재실행했다. `tests/unit/test_langgraph_runtime.py`, `tests/unit/test_controller_planning.py`, `tests/integration/test_live_gui_runtime_layout.py` 결과는 `117 passed, 4 warnings in 305.74s`이며, 이 검증은 draft module, bridge descriptor handoff, custom stage, supervisor policy, active graph route planning, Live GUI static adapter, Live GUI runtime shell/report/action payload 경로를 확인한다. 추가로 `tests/unit/test_langgraph_runtime.py::test_bridge_custom_action_descriptor_can_be_saved_to_graph_metadata`와 `tests/unit/test_langgraph_runtime.py::test_new_bridge_manifest_entry_is_shared_by_bridge_api_and_runtime_contract`를 포함한 targeted pytest가 `3 passed, 4 warnings in 1.72s`로 통과했다.
- 같은 검증 세션에서 `tests/ui/live_runtime_ide_browser_audit.py`, `tests/ui/planning_browser_audit.py`, `tests/ui/module_management_browser_audit.py`가 모두 PASS했다. Live GUI audit는 reference mission bar/binder/report/backend/graph/artifact/timeline/device strip/approval/quick action/save-version evidence path, built-in Design/Equipment/Guardian report layout 보존, 그리고 임시 draft module `ui_audit_draft_descriptor`의 descriptor card/report section DOM 렌더링을 확인한다. audit fixture는 해당 draft module을 생성하고 `ui.yaml` descriptor를 저장한 뒤 Live GUI binder, Runtime Chat target, report card/section DOM에 반영되는지 검증한다. planning audit는 `analysis_ai` FEM/CAE contour card와 `bo_ai` collapsed BO surrogate/acquisition card가 실제 chat DOM에 렌더되는지 확인했다.
- 2026-06-17 수정 범위는 Live GUI/runtime audit와 module/runtime contract 경로이며, DSN/design window layout은 변경하지 않았다.

이 감사 결과, 문서의 결론은 다음 근거 위에서 작성됐다.

- frontend 병목은 완전히 사라진 상태가 아니다. agent 목록과 descriptor card/report section은 manifest-first로 이동했지만, 일부 agent-specific dashboard/report renderer와 arbitrary external renderer/plugin 등록은 아직 중앙 `planning.js`의 allowlisted built-in profile 경계 안에 있다.
- backend 병목은 아직 남은 controller/supervisor fixed stage policy와 custom stage lifecycle에 있다. `Stage` enum은 유지되지만 graph-validated custom stage 문자열을 pseudo-member로 표현할 수 있게 됐다.
- graph/module/Runtime IDE/generated adapter 쪽은 이미 모듈화를 지탱할 기반이 있다.
- 위 대화에서 논의한 "agent 폴더에 전부 넣지 말고 `graphs/modules/<agent>/`를 manifest root로 승격"과 "empty module보다는 안전한 draft module template 필요"를 개선안에 반영했다.

---

## 1. 결론

현재 구조는 **자유 모듈화가 가능한 방향으로 이미 절반 이상 가 있다.**

특히 backend 쪽은 `graphs/modules/<module>/module.yaml`, `graphs/configs/atr_closed_loop.yaml`, `ModuleConfigStore`, `GraphConfig`, Runtime IDE API, generated adapter 승인 구조가 있어서 모듈화의 뼈대가 있다.

하지만 지금 상태로는 아직 **원하는 대로 agent를 추가/삭제하면 GUI 카드, LangGraph, bridge, runtime 실행까지 자동으로 따라오는 구조는 아니다.**

가장 큰 병목은 다음 세 군데다.

1. Live GUI는 agent 목록과 일부 card/report section에서 module contract를 source of truth로 쓰기 시작했다. 다만 특수 agent dashboard/report detail은 아직 `planning.js`의 allowlisted built-in renderer profile에 남아 있어, 완전한 third-party renderer/plugin 자유도는 없다.
2. Backend runtime은 graph YAML을 읽고 custom stage 문자열을 표현/실행할 수 있지만, `app/controller.py`, `orchestrator/supervisor.py`의 고정 stage 분기와 planning/live lifecycle은 아직 기존 ATR stage set에 많이 묶여 있다.
3. module 생성은 가능하지만, 사용자가 직접 채워 넣는 안전한 `draft/empty module template` 개념이 아직 명확하지 않다.

따라서 개선 방향은 **새 agent 폴더에 모든 파일을 몰아넣는 방식이 아니라, 현재의 `graphs/modules/<agent>/`를 agent manifest root로 승격시키는 방식**이 맞다.

---

## 2. 이전 실제 GUI 확인 결과와 현재 코드 해석

### 2.1 `/live` 로드 상태

이전 Browser plugin 검증에서는 `http://127.0.0.1:7860/live`를 열었고, page title은 `Live GUI`로 확인됐다.

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

이것은 agent별 특화 화면이 이미 존재한다는 뜻이다. 현재 코드 기준으로도 이 특화는 module descriptor 기반이 아니라 `planning.js` 내부 함수와 switch/map 구조에 들어 있다.

---

## 3. API/contract 상태

### 3.1 Runtime IDE contract

이전 실행 서버에서 `/api/state`의 `runtime_ide_contract`를 확인한 결과:

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

즉 backend는 이미 GUI/IDE가 읽을 수 있는 module/graph/bridge contract를 내려줄 수 있다. 현재 코드 기준으로도 `/api/state`, `/api/modules`, `/api/handlers`, `/api/graphs/{graph_id}` 구현 경로는 유지되어 있다.

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
  - cae_bridge
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

- backend가 `agents[]`를 포함한 manifest payload를 내려줘야 한다.
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

이전 병목은 `liveAgentNeedsChatPanel()`이 `objective`, `orchestrator`만 chat panel이 필요하다고 판단하던 점이었다.

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

현재 구현:

- `/api/runtime/agent-manifests`는 `ui.chat` 또는 `runtime_contract.chat_policy`를 agent manifest의 `chat` 필드로 보존한다.
- `web/static/planning.js::liveAgentChatMode()`는 `agent.chat.mode`를 읽어 chat 정책을 결정한다.
- `persistent`, `always`, `required`는 상시 chat panel을 유지한다.
- `open_on_demand`, `on_demand`, `collapsible`, `contextual`은 report-first agent에서 Chat 버튼으로 Runtime Chat을 연다.
- `disabled`, `none`, `off`, `hidden`은 report Chat action을 숨긴다.
- 정책이 없으면 backward compatibility를 위해 `objective`, `orchestrator`는 persistent, 나머지는 open-on-demand로 처리한다.

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

### 6.1 `Stage` enum 고정 의존이 일부 완화됐다

`orchestrator/state.py`의 `Stage` enum은 기본 ATR stage 값을 유지한다.

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

현재 완화된 부분:

- `Stage._missing_()`이 graph-validated extension stage 문자열을 pseudo-member로 표현한다.
- `LangGraphRunLoop._coerce_stage()`는 기존 `.value` 기반 코드와 호환된 채 `custom_quality_gate` 같은 extension stage를 받을 수 있다.
- allowlisted `agent.*` handler와 module config가 붙은 custom stage는 한 runtime step에서 실행되고 configured transition으로 다음 stage에 전환될 수 있다.
- `MainController`는 active graph route를 `build_orchestration_plan()`에 override로 전달하므로 `design -> specimen -> custom_quality_gate -> guardian` 같은 삽입 stage가 supervisor plan, route_state, task queue에 표시된다.
- Live planning stage role/label은 custom stage에서 graph/module metadata를 사용한다. `handler=agent.custom_quality_agent`, `label=Custom Quality Gate` 같은 값이 message role과 route step label로 보존된다.
- module의 `output_contracts[]` 및 list-valued `io_contract.output`은 custom route step의 `required_outputs`로 승격되어 task queue에 표시된다.

남은 문제:

- `Stage` enum 자체는 아직 남아 있다.
- `orchestrator/supervisor.py`의 stage별 report/opinion/detail은 custom stage용 `supervisor_policy` descriptor를 지원하고, Module Management typed editor에서 required outputs, opinion/recommendation template, response-required status, concern rules, options를 편집할 수 있다. 또한 `ui.yaml report_sections`는 Live GUI dashboard/academic report에서 selector 기반 report section으로 표시된다. selector root는 `report`, `state`, `spec`, `metadata`, `runtime`이다. descriptor layout intent(`span`, `density`, `priority`, `mobile_behavior`), 기본 `mini_bar_chart`, `scatter_plot`, `line_chart`, `table`, `heatmap`, `compound_chart`/`chart_grid`, 내부 GUI navigation action descriptor, read-only GET API action descriptor, POST/confirmation/non-read-only API workspace handoff descriptor, physical/device action explicit block metadata는 백엔드 정규화와 프론트엔드 safe rendering까지 구현됐다. 더 특화된 도메인 전용 chart type과 실제 physical device action authoring은 후속이다.
- custom stage/module lifecycle은 Module Management에서 activation readiness와 next required action을 표시하고, graph-unattached module을 `/ide?module=<id>&action=attach`로 Runtime IDE attach mode에 넘기는 수준까지 구현됐다. 또한 `supervisor_policy.required_outputs[]`는 `output_contracts[]` 및 list-valued `io_contract.output`과 대조되어 `supervisor_policy_outputs` activation requirement와 `supervisor_policy_gate` 표시로 연결된다. 다만 실제 graph attach/edit/save 자체는 Runtime IDE validate/dry-run/Save Version workflow를 통과해야 하며, 더 깊은 activation authoring은 아직 후속이다.
- bridge action UX는 read-only GET 실행과 non-read-only/custom action의 workspace handoff까지 구현됐다. 단, bridge별 custom action을 GUI에서 작성하는 editor와 물리 실행 workflow는 아직 bridge workspace/safety gate 범위다.

개선:

- 단기: 기존 Stage enum을 유지하되 extension stage는 `Stage._missing_()` pseudo-member로 표현한다. 이 단기 경로는 구현됨.
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

### 10.0 현재 코드 기준 구현 상태

| 항목 | 현재 상태 | 판단 |
|---|---|---|
| `/api/modules` | 존재 | module catalog와 module 생성/저장 기반은 있음 |
| `/api/handlers` | 존재 | allowlisted agent handler와 `module.generated_adapter` 확인 가능 |
| `/api/graphs/{graph_id}` | 존재 | graph config와 `stage_dispatch`를 내려줄 수 있음 |
| `/api/runtime/agent-manifests` | 구현됨 | Phase 1 완료. graph + module + optional `ui.yaml` 병합 manifest payload 제공. 프론트엔드는 payload의 `agents[]`를 사용 |
| `graphs/modules/*/module.yaml` | 존재 | 현재 10개 module manifest root로 승격 가능한 기반 |
| `graphs/modules/*/ui.yaml` | 일부 구현됨 | Design/Equipment/Guardian 3개 descriptor 추가. 없는 module은 fallback renderer 사용 |
| draft module template endpoint | 구현됨 | `POST /api/modules/templates/{agent|ui-only|bridge}`로 inactive draft 생성 |
| `Stage` enum decoupling | 부분 구현 | `Stage._missing_()` custom-stage pseudo-member, custom agent stage runtime step, active graph 기반 controller/supervisor route visibility, module output contract 반영, supervisor_policy typed editor 테스트 구현, selector 기반 `ui.yaml report_sections` Live GUI 렌더링, manifest-driven `ui.chat.mode`, descriptor layout intent, 기본 `mini_bar_chart`, `scatter_plot`, `line_chart`, `table`, `heatmap`, `compound_chart`/`chart_grid`, safe navigation action descriptor, read-only GET API action descriptor, POST/confirmation/non-read-only API workspace handoff descriptor, physical/device action explicit block metadata의 백엔드 정규화/프론트엔드 렌더링, Module Management -> Runtime IDE attach deep-link 구현. 더 특화된 도메인 전용 chart와 실제 physical device action authoring, 더 깊은 activation authoring은 후속 |
| `ui.renderer` custom renderer manifest id | 부분 구현 | `app/main.py`가 allowlisted `renderer.dashboard/report/fallback`을 `presentation_only` manifest metadata로 정규화하고, `planning.js`가 `LIVE_RENDERER_PROFILES`/`liveAgentRendererProfile()`로 받아 기존 built-in report/detail 및 dashboard/card renderer 선택에 사용한다. 임의 외부 renderer/plugin 로딩은 아직 없음. 현재 사용 가능한 확장 지점은 `cards`, `report_sections`, descriptor chart/action, allowlisted renderer profile |
| module load/unload lifecycle visibility | 구현됨 | `GET/load/unload` API가 `runtime_effect`와 `lifecycle`을 반환하고 Module Management GUI가 management-only lifecycle card로 표시. `activation_status`, `activation_requirements`, `ready_for_live_activation`, `next_required_action`까지 표시하지만 실제 runtime activation은 validate/dry-run/save/graph reference 경로로 유지 |
| bridge registry | 구현됨(실행 제외) | `/api/bridges`가 graph metadata 기반 normalized bridge manifest 제공. standard/custom action descriptor는 모두 `actions[]` shape로 정규화되고 Runtime IDE contract에 embedding됨. Runtime IDE custom action descriptor editor와 `POST /api/bridges/{bridge_id}/actions` 저장 경로 구현. 저장된 custom action과 새 bridge manifest entry가 `/api/bridges`와 `/api/runtime/state.runtime_ide_contract.device_bridges`에 같은 normalized 객체로 반영되는 것까지 테스트로 확인됨. read-only GET action은 Live GUI 카드에서 실행 가능하고, non-read-only/custom action은 workspace handoff 버튼으로 표시됨. bridge별 물리 실행 workflow는 workspace/device gate 후속 |
| generated adapter approval | 존재 | static validation + explicit approval 구조 유지 |

### Phase 1. Manifest layer 추가

목표:

- backend에서 graph + module + optional ui config를 합친 `agents[]` manifest payload 제공
- Live GUI가 `LIVE_AGENTS` 대신 manifest를 읽을 준비

변경 대상:

- `app/main.py`
- `graphs/modules/*/module.yaml`
- `web/static/planning.js`

완료 기준:

- `/api/runtime/agent-manifests`가 existing 10 modules와 `objective` UI-only entry를 `agents[]`에 담아 반환
- Live GUI binder가 manifest 기반으로 렌더링하고, 실패 시 `DEFAULT_LIVE_AGENTS` fallback으로 기존 화면 유지
- 기존 화면 기능 유지

현재 구현/검증:

- `app/main.py::_runtime_agent_manifests_payload()`
- `GET /api/runtime/agent-manifests`
- `web/static/planning.js::refreshLiveAgentManifest()`
- `web/static/planning.js::applyLiveAgentManifest()`
- 검증: `tests/unit/test_langgraph_runtime.py::test_graph_runtime_api_exposes_handlers_modules_and_compile`
- 검증: `tests/integration/test_live_gui_runtime_layout.py::test_live_gui_static_script_exposes_runtime_ide_adapters`

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

- draft/custom/generic module은 descriptor card/report section으로 Live GUI preview 렌더링
- Design/Equipment/Guardian 같은 built-in reference agent는 기존 reference dashboard 배치를 유지하고 descriptor preview card가 메인 리포트를 밀어내지 않음
- descriptor 없는 agent는 generic card fallback

현재 구현/검증:

- `graphs/modules/design/ui.yaml`
- `graphs/modules/equipment/ui.yaml`
- `graphs/modules/guardian/ui.yaml`
- `web/static/planning.js::renderAgentDescriptorCards()`
- `GET/PUT /api/modules/{module_id}/ui`
- chart descriptor 지원: `mini_bar_chart`, `scatter_plot`, `line_chart`, `table`, `heatmap`, `compound_chart`/`chart_grid`
- `compound_chart`는 backend normalization에서 panel별 child chart를 재귀 정규화하고, frontend에서 bounded panel grid로 렌더링한다. nested compound chart는 recursion limit으로 차단한다.
- layout intent 지원: `span`, `density`, `priority`, `mobile_behavior`를 backend에서 `layout_intent`로 정규화하고, Live GUI renderer가 `density-*`, `priority-*`, `mobile-*` class로 매핑한다.
- 검증: `tests/unit/test_langgraph_runtime.py::test_runtime_module_template_creates_non_executable_draft_manifest`
- 검증: `tests/integration/test_live_gui_runtime_layout.py::test_live_gui_static_script_exposes_runtime_ide_adapters`

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

현재 구현/검증:

- `POST /api/modules/templates/{template_kind}`
- template kind: `agent`, `ui-only`, `bridge`
- 생성 module은 `status=draft`, `enabled=false`, `handler=runtime.step_complete`, `execution.capability=ui_only`, `graph.attached=false`
- Module Management Tool에 `Create Draft Agent` 버튼 추가
- draft dry-run은 sequence preview만 반환하고 `executable_count=0`
- 검증: `tests/unit/test_langgraph_runtime.py::test_runtime_module_template_creates_non_executable_draft_manifest`
- 검증: `tests/unit/test_langgraph_runtime.py::test_module_management_ui_exposes_draft_template_creation`

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

현재 구현/검증:

- `orchestrator.state.Stage._missing_()`이 unknown stage 문자열을 pseudo-member로 보존한다.
- `LangGraphRunLoop`는 graph config에서 `idle -> custom_quality_gate` 전환 시 `state.stage.value == "custom_quality_gate"`를 유지한다.
- allowlisted `agent.custom_quality_agent`를 가진 custom stage가 module config와 graph transition을 통해 한 step 실행되고 `complete`로 전환되는 regression test를 추가했다.
- `orchestrator.supervisor.build_orchestration_plan()`은 optional `route_override`를 받아 active graph route를 supervisor plan source로 사용할 수 있다.
- `MainController._build_orchestration_plan()`은 active graph stage sequence를 route override로 넘기고, custom stage의 agent role/label을 graph node와 `module_runtime.handler`에서 해석한다.
- `MainController._module_required_outputs_for_graph_node()`는 active graph module root에서 module.yaml을 읽어 `output_contracts[]`와 list-valued `io_contract.output`을 supervisor `required_outputs`로 연결한다.
- `orchestrator.supervisor.build_orchestrator_followup()`은 payload 또는 `module_runtime`에 포함된 `supervisor_policy`를 읽어 custom stage opinion/recommendation template, required outputs, concern rules, options, response-required status를 follow-up에 반영한다.
- Module Management `GET/load/unload` API는 `runtime_effect`/`lifecycle` metadata를 반환하고, `module_management.js`는 이를 management-only lifecycle card로 표시한다.
- Lifecycle card는 `activation_status`, `activation_requirements`, `ready_for_live_activation`, `next_required_action`을 보여준다. Draft/unattached module은 `draft_unattached`와 `edit_module_contract` 같은 next action으로 표시되고, Runtime IDE 버튼은 `/ide?module=<id>&action=attach`로 Module Library attach 대상을 강조한다. Active graph-attached executable module은 `active_graph_attached`로 표시된다.
- Lifecycle card는 `supervisor_policy_gate`도 표시한다. `supervisor_policy.required_outputs[]`가 있으면 backend가 `output_contracts[]`와 list-valued `io_contract.output`에서 declared outputs를 계산하고, 누락 항목을 `missing_outputs[]` 및 `supervisor_policy_outputs` activation requirement로 노출한다. Frontend는 `Supervisor required outputs`, `required_outputs`, `declared_outputs`, `missing_outputs`를 표시한다.
- 검증: `tests/unit/test_langgraph_runtime.py::test_langgraph_runtime_accepts_graph_validated_custom_stage`
- 검증: `tests/unit/test_langgraph_runtime.py::test_langgraph_runtime_executes_custom_agent_stage_from_graph_config`
- 검증: `tests/unit/test_langgraph_runtime.py::test_supervisor_followup_uses_custom_stage_supervisor_policy`
- 검증: `tests/unit/test_langgraph_runtime.py::test_module_lifecycle_checks_supervisor_policy_required_outputs`
- 검증: `tests/unit/test_controller_planning.py::test_orchestrator_plan_uses_active_graph_route_with_custom_stage`
- 검증: `tests/unit/test_controller_planning.py::test_custom_planning_stage_role_uses_module_handler`
- 남은 부분: 더 특화된 도메인 전용 chart authoring, graph attach/save를 포함한 full custom activation authoring, bridge/workspace별 custom physical action authoring. 기본 layout intent와 `table`/`heatmap`/`compound_chart` chart는 지원되며, POST/confirmation descriptor action은 직접 실행이 아니라 workspace handoff metadata/button 수준까지 구현됐고, `kind=device|physical|hardware|actuator` descriptor는 `physical_device_action_requires_bridge_workspace`로 명시 차단된다. `supervisor_policy.required_outputs[]` lifecycle gate는 구현됐지만 실제 물리 실행 authoring은 아직 bridge workspace/device gate 후속이다.

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
- `POST /api/bridges/{bridge_id}/actions` descriptor-only 저장 제공
- bridge health/preflight/actions/evidence contract 표준화
- agent report card가 bridge manifest를 참조

현재 구현/검증:

- `GET /api/bridges`는 `graphs/configs/atr_closed_loop.yaml`의 `metadata.device_bridges`를 source로 사용한다.
- 반환 항목은 `id`, `label`, `workspace`, `tools`, `config`, `live_boundary`, `health_endpoint`, `preflight_endpoint`, `actions`, `evidence_contracts`, `health`를 포함한다.
- `app/main.py::_normalized_bridge_manifests()`가 graph metadata를 API 소비용 contract로 정규화한다.
- graph metadata에 action이 없으면 backend가 `actions[]` 안에 `open_workspace`, `health_check`, `preflight` standard actions를 생성한다.
- action schema는 `id`, `label`, `kind`, `method`, `endpoint`, `requires_confirmation`, `read_only`, `tool`, `mode_support`를 포함한다.
- evidence contract는 bridge별 기본값과 `tool:<tool_name>` 항목으로 채워진다.
- legacy workspace alias `/windows-equipment`는 API 응답에서 `/equipment/windows`로 정규화된다.
- `/api/runtime/state.runtime_ide_contract.device_bridges`도 같은 normalized bridge list를 반환한다.
- Live GUI `renderDeviceStrip()`은 같은 `runtime_ide_contract.device_bridges` 목록을 읽어 bridge label, workspace, health/preflight endpoint, `actions[]`, evidence contract 상태를 read-only card로 표시한다.
- Live GUI card의 `open_workspace` action은 hardware 실행 없이 해당 bridge workspace route를 새 창으로 여는 navigation으로 연결된다.
- Live GUI card의 `health_check`와 `preflight` action 중 `read_only=true`, `method=GET`, `/api/` endpoint인 항목은 `runBridgeContractAction()`이 직접 호출하고 operator event로 남긴다.
- `POST`, confirmation 필요, non-read-only, 또는 custom action은 Live GUI card에서 직접 실행하지 않는다. Backend는 action마다 `live_card_runnable`, `handoff_required`, `handoff_workspace`, `blocked_reason`을 내려주고, Live GUI는 이를 workspace handoff 버튼으로 표시한다. 클릭 시 bridge workspace를 `bridge_id`, `bridge_action`, `bridge_endpoint` query와 함께 새 창으로 열고 operator event를 남긴다.
- 현재 구현은 backend registry normalization, IDE contract embedding, Runtime IDE custom action descriptor editor, Live GUI read-only bridge card, safe `open_workspace` navigation, read-only GET health/preflight action runner, non-read-only/custom action workspace handoff UX까지이다. bridge별 물리 실행 workflow는 workspace/device gate 후속이다.
- `ui.yaml` descriptor action도 같은 안전 원칙을 따른다. `kind=api`, `method=GET`, `read_only=true`는 `read_only_api`로만 실행 가능하고, POST/confirmation/non-read-only 내부 API는 실제 endpoint가 존재하고 safe workspace가 있거나 추론될 때만 `workspace_handoff`로 표시된다. 클릭 시 Live GUI는 endpoint를 호출하지 않고 workspace를 `descriptor_action`, `descriptor_endpoint`, `descriptor_method` query context와 함께 연다. `kind=device|physical|hardware|actuator`는 generic descriptor path에서 실행되지 않으며 `physical_device_action_requires_bridge_workspace` reason으로 disabled metadata만 남긴다.
- 검증: `tests/unit/test_langgraph_runtime.py::test_graph_runtime_api_exposes_handlers_modules_and_compile`
- 검증: `tests/unit/test_langgraph_runtime.py::test_bridge_custom_non_readonly_action_is_workspace_handoff_only`
- 검증: `tests/unit/test_langgraph_runtime.py::test_bridge_custom_action_descriptor_can_be_saved_to_graph_metadata`
- 검증: `tests/unit/test_langgraph_runtime.py::test_new_bridge_manifest_entry_is_shared_by_bridge_api_and_runtime_contract`
- 검증: `tests/unit/test_langgraph_runtime.py::test_runtime_module_template_creates_non_executable_draft_manifest`
- 검증: `tests/integration/test_live_gui_runtime_layout.py::test_live_gui_static_script_exposes_runtime_ide_adapters`

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

현재 코드 상태:

- descriptor card/report section 경로는 구현되어 있다.
- custom renderer manifest id는 allowlisted presentation profile까지 구현되어 있다.
- 따라서 당장 새 모듈 UI를 만들 때는 `ui.cards[]`, `ui.report_sections[]`, descriptor chart/action을 우선 사용하고, 기존 agent reference 화면을 재사용해야 할 때만 `ui.renderer.dashboard/report/fallback`을 보조 metadata로 둔다.
- 임의 외부 renderer/plugin 로딩은 구현 범위 밖이다. operator-facing 기능으로 문서화할 때도 `execution_scope=presentation_only`와 allowlist 경계를 같이 적는다.

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

| 항목 | 현재 상태 | 증거 |
|---|---|---|
| 1. Runtime IDE/Module Management에서 draft agent module을 생성할 수 있다 | 구현됨 | `POST /api/modules/templates/agent`, `Create Draft Agent` 버튼 |
| 2. 그 module에 card/report descriptor를 추가하면 Live GUI binder/report에 preview로 나온다 | 구현됨 | `POST /api/modules/templates/agent`, `GET/PUT /api/modules/{module_id}/ui`, manifest `cards`/`report_sections`, `renderAgentDescriptorCards()` 구현. `tests/ui/live_runtime_ide_browser_audit.py`가 임시 draft module `ui_audit_draft_descriptor`를 생성하고 descriptor 저장 후 Live GUI binder, chat target, report card/section DOM 표시를 확인한다. draft는 여전히 실행 비활성 상태다 |
| 3. graph에 연결하지 않은 module은 실행되지 않는다 | 구현됨 | draft `enabled=false`, `graph.attached=false`, dry-run `executable_count=0` |
| 4. graph에 연결한 module은 validate/dry-run gate를 통과해야 enable된다 | 구현됨(기존 Runtime IDE gate) | 기존 `/api/graphs/{id}/validate`, `/dry-run`, `/run` gate 유지. custom stage 문자열, allowlisted custom agent step 실행, controller/supervisor route visibility, module output contract 반영, `supervisor_policy` 기반 custom follow-up과 Module Management typed editor, management-only load/unload lifecycle visibility와 activation readiness fields, `/ide?module=<id>&action=attach` attach handoff는 테스트됨. graph edit/activation은 Runtime IDE drag/drop, port 연결, validate/dry-run, Save Version gate를 사용한다. `tests/ui/runtime_ide_browser_audit.py`의 run-preflight/save-version-lifecycle 경로는 unsaved draft 실행 차단, validate/dry-run 후 Save Version, saved graph run 생성을 검증한다 |
| 5. 기존 10개 agent는 manifest 기반으로 표시된다 | 구현됨 | `/api/runtime/agent-manifests`, Live GUI `refreshLiveAgentManifest()` |
| 6. `planning.js`의 `LIVE_AGENTS`가 source of truth가 아니다 | 구현됨 | `DEFAULT_LIVE_AGENTS`는 fallback이고 backend manifest가 우선 |
| 7. agent별 card/report section 추가/삭제가 JS 코드 수정 없이 가능하다 | 구현됨(지원 descriptor 범위) | `ui.yaml` cards와 selector-backed `report_sections`를 generic/draft/custom renderer로 표시. selector root는 `report`, `state`, `spec`, `metadata`, `runtime`. 기본 layout intent, `mini_bar_chart`, `scatter_plot`, `line_chart`, `table`, `heatmap`, `compound_chart`/`chart_grid`, 내부 GUI navigation action, read-only GET API action, POST/confirmation/non-read-only API workspace handoff action, physical/device action explicit block metadata는 백엔드 정규화와 프론트엔드 safe rendering까지 지원. Live GUI audit가 임시 draft module `ui_audit_draft_descriptor`의 descriptor 렌더링을 확인하고, Design/Equipment/Guardian built-in reference report는 descriptor preview card로 대체되지 않는 것을 확인한다. 더 특화된 도메인 전용 chart와 실제 physical device action authoring은 후속 |
| 8. 새 bridge는 bridge manifest 추가만으로 Runtime IDE와 Live GUI에 표시된다 | 구현됨(실행 제외) | `/api/bridges` normalized registry, `runtime_ide_contract.device_bridges` embedding, Runtime IDE custom action descriptor editor, Live GUI `renderBridgeContractDeviceCards()` 표시, safe `open_workspace` navigation, read-only GET `health_check`/`preflight` runner, non-read-only/custom action workspace handoff UX 구현. `tests/unit/test_langgraph_runtime.py::test_new_bridge_manifest_entry_is_shared_by_bridge_api_and_runtime_contract`가 임시 graph metadata에 새 bridge를 추가한 뒤 `/api/bridges`와 runtime contract에 같은 normalized object가 표시되는지 확인한다. bridge별 물리 실행 workflow는 후속 |
| 9. custom Python 실행은 generated adapter 승인 없이는 불가능하다 | 기존 구현 유지 | `graphs/generated_adapter.py`, `register-generated` route |
| 10. 기존 closed-loop ATR flow는 backward compatible하게 유지된다 | 파일 단위/서버 회귀 검증됨 | `tests/integration/test_controller_run.py`, `tests/integration/test_stop_control.py`가 `2 passed in 93.94s`로 통과. 추가로 `tests/unit/test_langgraph_runtime.py`, `tests/unit/test_controller_planning.py`, `tests/integration/test_live_gui_runtime_layout.py`가 `117 passed, 4 warnings in 305.74s`로 통과. 전체 live/test 실장비 경로는 별도 현장 검증 필요 |

현재 완료라고 말할 수 있는 범위는 Phase 1, Phase 2의 descriptor-card 및 selector-backed report section 경로, manifest-driven `ui.chat.mode`, allowlisted `ui.renderer` presentation profile metadata와 built-in report/dashboard renderer 선택, 기본 layout intent, `mini_bar_chart`, `scatter_plot`, `line_chart`, `table`, `heatmap`, `compound_chart`/`chart_grid`, safe navigation action descriptor, read-only GET API action descriptor, POST/confirmation/non-read-only API workspace handoff descriptor, physical/device action explicit block metadata의 백엔드 정규화/프론트엔드 렌더링, Phase 3의 draft template API/UI, Phase 4의 custom stage pseudo-member, allowlisted custom agent step, active graph 기반 controller/supervisor route visibility, module output contract 반영, `supervisor_policy` 기반 custom follow-up과 Module Management typed editor, Module Management activation readiness 표시, Module Management -> Runtime IDE attach deep-link handoff, Phase 5의 backend bridge registry normalization, Runtime IDE custom action descriptor editor, Live GUI read-only 표시, safe `open_workspace` navigation, read-only GET health/preflight action runner, non-read-only/custom bridge action workspace handoff UX다. 더 특화된 도메인 전용 chart type, arbitrary external custom renderer/plugin registration, supervisor policy와 live lifecycle gate의 더 깊은 결합, bridge workspace 안의 물리 실행 workflow는 아직 남아 있다.

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

- Live GUI는 agent manifest와 descriptor card/report section을 우선 사용해야 하며, 남은 agent-specific built-in renderer 의존성은 allowlisted presentation profile 경계 안에서만 유지해야 한다.
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
