# Codex Goal Full Upgrade Implementation README

대상 프로젝트: Autonomous Researcher Framework
목표: `개선안/01`부터 `개선안/10`까지의 agent 고도화안과 Live GUI 고도화안을 한 번의 장기 Codex Goal 작업으로 실제 구현한다.

이 README는 계획 문서가 아니라 Codex Goal 실행 지침이다. Codex는 이 문서를 읽은 뒤 구현, 검증, 스크린샷 확인, 문서 갱신까지 완료해야 한다.

---

## 0. Codex Goal에 그대로 넣을 목표 문장

```text
Autonomous Researcher 프로젝트의 개선안/01-10 문서와 README_codex_goal_full_upgrade.md를 기준으로 전체 agentic closed-loop, Live GUI, agent report, backend trace, Guardian/Knowledge/Self-Evolution, handoff packet schema를 실제 구현해줘.

단순 리팩터링이나 UI 장식으로 끝내지 말고, 현재 프로젝트 구조(app/main.py, app/controller.py, orchestrator/langgraph_runtime.py, agents/*, graphs/configs/atr_closed_loop.yaml, graphs/modules/*, web/templates/planning.html, web/static/planning.js, web/static/styles.css, tests/*)에 맞춰 프론트엔드와 백엔드를 나누어 구현해.

완료 전에는 반드시 pytest, graph validate/dry-run, Live GUI HTML/browser screenshot 검증을 수행하고, 보고서 페이지가 사람이 보기 편한 논문식/그래프식 화면으로 보이는지 실제 위치를 확인해. 보고서 화면에는 코드나 raw JSON을 노출하지 말고, raw prompt/tool/input/output/log는 BACKEND trace view로 분리해.

실제 장비 live 실행은 기본 금지하고, test/dry-run/simulation/fault-injection 경로와 Guardian/human approval gate를 먼저 완성해. 모든 agent의 decision, evidence, handoff, incident, next_action이 report와 event stream에 남아야 한다. Goal을 중간에 완료로 표시하지 말고 Definition of Done 전체가 통과할 때까지 계속 진행해.
```

---

## 1. 먼저 읽을 파일 순서

Codex Goal은 구현 전에 아래 순서대로 읽어야 한다.

### 1.1 프로젝트 현재 구조

- `README.md`
- `README.ko.md`
- `docs/README.md`
- `docs/runtime/closed_loop_and_pages_reference.md`
- `docs/runtime/langgraph_runtime.md`
- `docs/gui/gui.md`
- `docs/process/codex_workflow.md`

### 1.2 기존 시스템 지침

- `docs/system/ATR_Live_GUI_and_LangGraph_Codex_Instructions.txt`
- `docs/system/ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt`
- `docs/system/ATR_Self_Evolution_Codex_Instructions.txt`
- `docs/ATR_Live_GUI_Graph_Package/docs/UI_SPEC.md`
- `docs/ATR_Live_GUI_Graph_Package/docs/BACKEND_API_SPEC.md`
- `docs/ATR_Live_GUI_Graph_Package/docs/GRAPH_INTEGRATION_SPEC.md`
- `docs/ATR_Live_GUI_Graph_Package/docs/UX_SPEC.md`

### 1.3 이번에 만든 개선안

- `개선안/01_design_agent_agentic_loop_research.md`
- `개선안/02_specimen_making_agent_autonomous_fabrication_loop_research.md`
- `개선안/03_vision_agent_lab_perception_signal_loop_research.md`
- `개선안/04_manipulation_agent_pi05_vla_sarm_loop_research.md`
- `개선안/05_lab_equipment_agent_utm_visual_control_data_loop_research.md`
- `개선안/06_analysis_agent_data_pipeline_bo_handoff_research.md`
- `개선안/07_bo_agent_reasoning_augmented_optimizer_research.md`
- `개선안/08_knowledge_agent_self_evolution_memory_rag_research.md`
- `개선안/09_guardian_agent_graphwide_safety_incident_loop_research.md`
- `개선안/10_orchestration_agent_supervisor_followup_loop_research.md`
- `개선안/11_live_gui_control_surface_upgrade_plan.md`

### 1.4 구현 대상 코드

- Backend/API: `app/main.py`, `app/controller.py`
- Runtime loop: `orchestrator/langgraph_runtime.py`, `orchestrator/state.py`
- Graph: `graphs/configs/atr_closed_loop.yaml`, `graphs/modules/*/module.yaml`
- Agents: `agents/*.py`
- Tools/bridges: `mcp_tools/*.py`, `device_bridges/*.py`
- Knowledge/memory: `knowledge/*`, `memory/*`, `self_evolution/*`
- Frontend: `web/templates/planning.html`, `web/static/planning.js`, `web/static/styles.css`
- Runtime IDE: `web/templates/runtime_ide.html`, `web/static/runtime_ide.js`, `web/static/runtime_ide.css`
- Tests: `tests/unit/*`, `tests/integration/*`, `tests/ui/*`

---

## 2. 구현 원칙

1. 기존 구조를 버리지 않는다. 현재 프로젝트는 이미 FastAPI + config-driven LangGraph + static JS Live GUI + Runtime IDE + self_evolution 기반을 갖고 있다.
2. Graph 실행의 source of truth는 `graphs/configs/*.yaml`과 `graphs/modules/*/module.yaml`이다.
3. Agent output은 사람이 보는 chat text와 downstream agent가 소비하는 structured packet을 분리한다.
4. Report 화면은 논문식/운영식 요약이다. 코드, raw JSON, raw prompt, stack trace는 BACKEND view에만 둔다.
5. Live GUI는 장식용 dashboard가 아니라 control surface다. 모든 버튼은 실제 API, event, state, approval, artifact로 이어져야 한다.
6. Guardian은 마지막 단계가 아니라 모든 agent/action의 gate다.
7. Knowledge는 마지막 기록 저장소가 아니라 모든 agent가 읽고 쓰는 memory/evolution plane이다.
8. 실제 장비 실행은 기본적으로 test/dry-run/simulation에서만 검증한다. live mode는 Guardian + human approval + dry-run digest가 있어야 한다.
9. Goal은 한 번에 크게 진행하되, phase별로 테스트와 screenshot을 통과해야 다음 단계로 간다.
10. 구현 중 막히면 기능을 몰래 삭제하지 말고, 안전한 fallback/test-mode 동작과 TODO evidence를 남긴다.

---

## 3. 전체 목표 아키텍처

```text
Operator goal
  -> Orchestrator mission contract / route / follow-up
  -> Design design_candidate.v1
  -> Specimen specimen_fabricated.v1
  -> Vision vision_signal.v1
  -> Manipulation robot_task_result.v1
  -> Equipment utm_data_ready.v1
  -> Analysis bo_observation.v1 + FEM evidence
  -> BO next_design_request.v1
  -> Guardian graph-wide safety decisions
  -> Knowledge memory + self-evolution evidence
  -> next loop or complete
```

Control planes:

- Execution plane: LangGraph stage execution and handoff packets.
- Safety plane: Guardian gates, approval interrupts, incidents, corrective actions.
- Memory/evolution plane: Knowledge records, evidence packs, evolution proposals.
- GUI plane: Live chat, agent report pages, backend trace, graph, artifacts, timeline.

---

## 4. 공통 packet/event/report 계약

가장 먼저 공통 contract를 구현한다. 권장 위치는 `orchestrator/contracts.py` 또는 `orchestrator/runtime_contracts.py`다. 이미 있는 schema module을 재사용할 수 있으면 그쪽에 통합한다.

### 4.1 공통 packet 필드

모든 packet은 최소한 아래 필드를 가져야 한다.

```json
{
  "schema": "packet-name.v1",
  "run_id": "run-...",
  "loop_id": "loop-...",
  "specimen_id": "optional",
  "producer_agent": "agent-id",
  "consumer_agent": "agent-id-or-list",
  "created_at": "ISO-8601",
  "status": "ready|blocked|warning|failed",
  "evidence_refs": [],
  "guardian_status": "allow|warn|block|approval_required|not_checked",
  "decisions": [],
  "warnings": [],
  "next_action": ""
}
```

### 4.2 필수 packet schemas

- `experiment_contract.v1`
- `design_candidate.v1`
- `specimen_fabricated.v1`
- `vision_signal.v1`
- `robot_task_result.v1`
- `utm_data_ready.v1`
- `bo_observation.v1`
- `next_design_request.v1`
- `knowledge_context.v1`
- `evolution_proposal.v1`
- `guardian_decision.v1`
- `incident_record.v1`
- `corrective_action.v1`
- `live_chat_message.v1`

### 4.3 `vision_signal.v1` freshness 필수 조건

Vision signal은 stale하면 위험하다. 반드시 아래 필드를 넣는다.

- `signal_id`
- `zone_id`
- `value`
- `confidence`
- `stable_for_ms`
- `timestamp`
- `expires_at`
- `consumer_agents`
- `evidence_refs`

Manipulation/Equipment는 `expires_at`이 지난 signal을 쓰면 안 된다.

### 4.4 Report payload 확장

`app/main.py`의 `_agent_report_payload()`는 기존 section을 유지하되 아래를 추가한다.

- `decisions`
- `metrics`
- `evidence_quality`
- `interrupts`
- `handoff_packets`
- `incident_refs`
- `report_view_url`
- `backend_trace_url`

`decisions`는 비어 있으면 안 된다. agent가 아무 판단을 하지 않은 경우에도 "no decision required"처럼 명시한다.

---

## 5. Backend 구현 지침

### 5.1 Controller/event bus

대상:

- `app/controller.py`
- `app/main.py`
- `logging_system/*`

해야 할 일:

- `live_chat_message.v1` 이벤트를 emit/record/replay할 수 있게 한다.
- `handoff.created`, `decision.created`, `incident.recorded`, `guardian.decision`, `knowledge.memory_written`, `evolution.proposed` 이벤트를 표준화한다.
- `/api/events/recent`, `/api/events/stream`, `/api/runs/{run_id}/events`가 새 event를 잃지 않게 한다.
- operator reply, approval, report action은 반드시 trace에 남긴다.

### 5.2 Runtime loop

대상:

- `orchestrator/langgraph_runtime.py`
- `orchestrator/state.py`
- `graphs/configs/atr_closed_loop.yaml`
- `graphs/modules/*/module.yaml`

해야 할 일:

- 각 stage 완료 시 해당 packet을 `state.run_metadata["handoff_packets"]`에 append한다.
- 각 stage는 `decisions`, `metrics`, `evidence_refs`, `next_action`을 반환한다.
- stage transition 전 Guardian pre/post gate를 호출할 수 있는 hook을 둔다.
- live hardware stage는 approval/dry-run/simulation evidence 없이 실행되지 않게 한다.
- Orchestrator는 route만 넘기지 말고 `orchestrator_followup.v1`, `decision_register.v1`, `loop_reflection.v1`을 만든다.

### 5.3 Agent별 backend 목표

| Agent | 구현 목표 |
|---|---|
| Design | 목표/제약을 `experiment_contract.v1`로 정규화하고 후보별 `design_candidate.v1` 생성 |
| Specimen | STL/G-code/printer/ejection digital thread를 `specimen_fabricated.v1`로 묶음 |
| Vision | DINO/SAM/pose 결과 또는 test-mode mock을 `vision_signal.v1` bus로 발행 |
| Manipulation | 두 short task를 episode로 분리하고 `robot_task_result.v1` 생성 |
| Equipment | PyAutoGUI command, screen assertion, Vision physical cross-check, data file transfer를 `utm_data_ready.v1`로 묶음 |
| Analysis | raw UTM parser, preprocessing, metrics, FEM/cache, BO handoff를 `bo_observation.v1`로 생성 |
| BO | surrogate/acquisition + LLM decision memo를 `next_design_request.v1`로 생성 |
| Knowledge | memory write/retrieval/evidence pack을 `knowledge_context.v1`, `evolution_proposal.v1`로 생성 |
| Guardian | 모든 action의 allow/warn/block/approval과 `incident_record.v1` 생성 |
| Orchestrator | 모든 packet registry, follow-up, interrupt, loop reflection 관리 |

### 5.4 Analysis/FEM 주의점

- 실험 observation과 FEM prediction을 같은 값으로 취급하지 않는다.
- BO로 넘길 때 `observed_metrics`, `simulation_metrics`, `simulation_residual`, `data_quality`를 분리한다.
- FEniCS/FEM이 설치되지 않은 환경에서는 test-mode deterministic stub/cache를 제공하되 report에는 `fem_status=stub|cached|fresh`를 명시한다.

### 5.5 Self-Evolution 주의점

- self-evolution은 live code를 직접 고치지 않는다.
- 후보는 variant/diff/config로 만들고, validation/dry-run/test/Guardian/human approval을 거친다.
- Evolution Lab과 Knowledge/Guardian report에 proposal 상태가 보여야 한다.

---

## 6. Frontend 구현 지침

### 6.1 Live GUI 기본 화면

대상:

- `web/templates/planning.html`
- `web/static/planning.js`
- `web/static/styles.css`

기존 3-column 구조는 유지한다.

- Left: Agentic Binder
- Center: Report / Backend / Graph / Artifact / Timeline
- Right: Runtime Chat
- Bottom: Timeline + Device strip

Frontend는 아래를 만족해야 한다.

- agent binder에서 각 agent 상태, unread, warning, approval pending이 보인다.
- center panel default는 report view다.
- BACKEND view는 report와 분리된다.
- graph view는 실행 node/edge 상태를 시각적으로 보여준다.
- runtime chat은 어떤 view를 열어도 사라지지 않는다.
- chat target은 selected agent/report/trace/run context를 보존한다.

### 6.2 보고서 페이지 스타일

보고서는 사람이 보는 논문식/운영식 화면이다.

반드시 지킬 것:

- report view에 코드, raw JSON, raw prompt를 직접 뿌리지 않는다.
- status는 간략하게 보여준다.
- graph, chart, table, badge, section card를 활용한다.
- 글은 짧고 읽기 쉽게 만든다.
- agent별 보고서에는 "무엇을 받았고, 무엇을 판단했고, 무엇을 넘겼고, 무엇이 위험한지"가 보인다.
- backend trace는 별도 view에서 raw prompt, input/output JSON, tool call, stack trace를 보여준다.

공통 report section:

- Overview / Summary
- Mission or Input Contract
- Key Decisions
- Metrics
- Evidence Quality
- Process Steps
- Tool Calls Summary
- Artifacts
- Validation / Quality Check
- Warnings / Incidents
- Handoff Packets
- Next Action

### 6.3 Agent별 특화 report

| Agent | 특화 report page |
|---|---|
| Design | candidate board, manufacturability, BO/Knowledge context, decision register |
| Specimen | digital thread, slicer/printer/ejection status, artifact ledger |
| Vision | scene map, signal board, evidence timeline, dataset ledger |
| Manipulation | skill episode board, VLA/SARM panel, trajectory evidence, risk/recovery |
| Equipment | control trace, visual assertion, physical verification, data ledger |
| Analysis | raw/preprocessed/FEM/BO payload panels, UTM curves, comparison |
| BO | observation table, surrogate/acquisition graph, candidate ranking, reasoning memo |
| Knowledge | memory ledger, retrieval panel, self-evolution board |
| Guardian | risk map, gate timeline, incident ledger, approval queue |
| Orchestrator | mission contract, route map, handoff registry, follow-up timeline |

### 6.4 Dedicated HTML report viewer

Live GUI center panel만으로 끝내지 말고, report를 독립적으로 확인할 수 있는 HTML viewer를 제공한다.

권장 route:

- `GET /reports/agents/{agent_id}`
- query: `run_id`, `view=report|backend`, `print=1`

권장 파일:

- `web/templates/agent_report.html`
- `web/static/report_viewer.css`
- 필요한 경우 `web/static/report_viewer.js`

HTML viewer 요구사항:

- 같은 `/api/agents/{agent_id}/report` payload를 사용한다.
- paper-like report view와 backend trace view를 분리한다.
- print/export friendly layout을 지원한다.
- screenshot 검증 대상이 된다.

---

## 7. 구현 스케줄

Codex Goal이 오래 실행될 수 있으면 아래 순서로 진행한다. 각 phase는 검증 후 다음 phase로 넘어간다.

### Phase 0. Baseline audit

- 현재 테스트 상태 기록.
- `pytest tests/unit -q`
- `pytest tests/integration/test_live_gui_runtime_layout.py -q`
- `/live`, `/ide`, `/evolution-lab` route가 열리는지 확인.
- 결과를 `artifacts/goal_upgrade/baseline.md`에 남긴다.

### Phase 1. Contract foundation

- 공통 packet/event/report schema 구현.
- schema validation helper와 packet builder 구현.
- unit tests 추가.

검증:

- packet builder unit tests
- `_agent_report_payload()`가 새 section을 반환하는 integration test

### Phase 2. Runtime/Orchestrator/Guardian backbone

- LangGraph stage 완료 후 packet registry 저장.
- Orchestrator follow-up/decision register/loop reflection 구현.
- Guardian graph-wide gate와 incident logging 구현.
- approval interrupt와 report/chat 연결 검증.

검증:

- `tests/unit/test_guardian_agent.py`
- `tests/unit/test_langgraph_runtime.py`
- `tests/integration/test_controller_run.py`

### Phase 3. Agent backend upgrade

순서:

1. Design
2. Specimen
3. Vision
4. Manipulation
5. Equipment
6. Analysis/FEM
7. BO
8. Knowledge/Self-Evolution

각 agent마다:

- structured packet 생성
- decisions/metrics/evidence_refs 채우기
- report payload에서 사람이 읽히는 section으로 변환
- test-mode deterministic fallback 유지
- agent unit test 추가/수정

### Phase 4. Live GUI/report frontend upgrade

- agent-specific report renderer 구현.
- graph/status/timeline과 report 연동.
- runtime chat에 `live_chat_message.v1` 카드 렌더링.
- BACKEND view 분리 강화.
- HTML report viewer 추가.

검증:

- `pytest tests/integration/test_live_gui_runtime_layout.py -q`
- browser screenshot audit

### Phase 5. Self-Evolution integration

- Knowledge evidence pack -> Evolution proposal -> Guardian approval -> Evolution Lab 표시.
- live code auto-patch 금지.
- variant registry/validation/rollback이 기존 `self_evolution/*`와 맞는지 확인.

검증:

- `pytest tests/unit/test_self_evolution.py -q`
- Evolution Lab route/browser smoke test

### Phase 6. End-to-end dry run

- test mode closed-loop를 최소 1 loop 실행.
- 각 agent report에 decision/handoff/evidence가 있는지 확인.
- Guardian incident/fault-injection 시나리오 확인.
- Knowledge memory와 BO next design request가 loop를 닫는지 확인.

검증:

- `pytest tests -q`
- graph validate/dry-run API
- browser screenshots

---

## 8. Browser/HTML/screenshot 검증 지침

보고서와 Live GUI는 반드시 실제 브라우저에서 위치를 확인한다. DOM 테스트만으로 완료하지 않는다.

### 8.1 서버 실행

Windows PowerShell:

```powershell
$env:AUTONOMOUS_PORT="7860"
$env:AUTONOMOUS_RELOAD="0"
python -m app.serve
```

또는:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 7860
```

### 8.2 기존 browser audit 사용

geckodriver가 있으면:

```powershell
python tests/ui/live_runtime_ide_browser_audit.py --base-url http://127.0.0.1:7860 --webdriver-url http://127.0.0.1:4448 --out-dir artifacts/ui
python tests/ui/planning_browser_audit.py --base-url http://127.0.0.1:7860 --webdriver-url http://127.0.0.1:4448 --out-dir artifacts/ui
```

geckodriver가 없으면 Codex Browser 또는 Playwright로 직접 `/live`와 `/reports/agents/{agent_id}`를 열어 screenshot을 저장한다.

### 8.3 필수 screenshot 목록

저장 위치:

```text
artifacts/goal_upgrade/screenshots/
```

필수 파일:

- `live_desktop_report_orchestrator.png`
- `live_desktop_report_design.png`
- `live_desktop_report_vision.png`
- `live_desktop_report_equipment.png`
- `live_desktop_report_analysis.png`
- `live_desktop_report_bo.png`
- `live_desktop_report_guardian.png`
- `live_desktop_backend_trace.png`
- `live_desktop_graph_view.png`
- `live_desktop_runtime_chat_approval.png`
- `report_viewer_design_print.png`
- `report_viewer_analysis_print.png`
- `mobile_live_report.png`

### 8.4 사람이 보기 편한지 체크

각 screenshot에서 다음을 확인한다.

- 글자가 버튼/카드 밖으로 삐져나가지 않는다.
- center report와 right runtime chat이 겹치지 않는다.
- report view에 raw code/raw JSON이 보이지 않는다.
- BACKEND view에는 raw prompt/tool/input/output/log가 보인다.
- graph view에서 현재 node, next edge, warning/approval 상태를 알 수 있다.
- report의 status는 짧고, 판단 근거는 section으로 나뉘어 있다.
- mobile/좁은 화면에서는 3-column이 깨지지 않고 stacking 또는 scroll이 작동한다.
- 논문식 보고서 느낌은 유지하되, 운영자가 action을 바로 찾을 수 있다.

---

## 9. 테스트 지침

최소 테스트:

```powershell
pytest tests/unit -q
pytest tests/integration/test_live_gui_runtime_layout.py -q
pytest tests/integration/test_controller_run.py -q
pytest tests/unit/test_langgraph_runtime.py -q
pytest tests/unit/test_guardian_agent.py -q
pytest tests/unit/test_analysis_agent.py -q
pytest tests/unit/test_bo_agent.py -q
pytest tests/unit/test_self_evolution.py -q
```

최종 테스트:

```powershell
pytest tests -q
```

Graph 검증:

- `GET /api/graphs`
- `POST /api/graphs/atr_closed_loop/validate`
- `POST /api/graphs/atr_closed_loop/dry-run`
- `POST /api/run/start` with `mode=test`

실제 장비 없이도 통과해야 하는 것:

- printer/robot/equipment는 test-mode 또는 mock/fallback으로 report와 handoff를 생성한다.
- Vision은 camera unavailable이어도 deterministic simulated `vision_signal.v1`을 만들고 confidence/fallback 상태를 명시한다.
- FEM unavailable이면 cached/stub status를 명시한다.

---

## 10. Done 기준

Codex Goal은 아래가 모두 참일 때만 완료한다.

- 10개 개선안의 핵심 요구가 코드에 반영됐다.
- 모든 agent가 structured packet을 생성한다.
- 모든 agent report에 `decisions`, `metrics`, `evidence_quality`, `handoff_packets`, `next_action`이 보인다.
- Live GUI chat에 agent별 `live_chat_message.v1`이 사람이 읽는 카드로 표시된다.
- Report view와 Backend trace view가 분리됐다.
- Dedicated HTML report viewer가 있다.
- Graph view가 실제 graph/runtime event와 연결된다.
- Guardian이 모든 위험 action의 gate로 동작한다.
- Knowledge가 memory/evidence/self-evolution proposal을 관리한다.
- Self-Evolution은 validation/dry-run/approval/rollback 없이는 live 활성화되지 않는다.
- `pytest tests -q` 또는 합리적 범위의 전체 테스트가 통과한다.
- `/live`와 `/reports/agents/{agent_id}` screenshot을 저장하고 레이아웃 문제를 확인했다.
- 변경된 API/route/report section은 관련 docs에 반영됐다.
- 실제 hardware live 실행은 사용자가 명시하기 전까지 수행하지 않았다.

---

## 11. 진행 기록 규칙

Codex Goal이 오래 진행되면 아래 파일을 만들고 계속 갱신한다.

```text
artifacts/goal_upgrade/progress.md
artifacts/goal_upgrade/test_log.md
artifacts/goal_upgrade/screenshots/
```

`progress.md`에는 phase별 상태를 남긴다.

```text
Phase 0 baseline: done / failed / blocked
Phase 1 contracts: done / failed / blocked
...
Open risks:
- ...
Next action:
- ...
```

작업이 중간에 끊겨도 다음 Codex Goal이 이 파일과 본 README를 읽고 이어갈 수 있어야 한다.

---

## 12. 구현 중 우선순위

시간이 부족하면 아래 순서를 지킨다.

1. 공통 schema/packet/event/report payload
2. Guardian + Orchestrator + Knowledge 연결
3. Analysis/FEM/BO handoff
4. Vision signal freshness
5. Equipment cross-check/data file handoff
6. Manipulation short-task episode split
7. Specimen digital thread
8. Design candidate board
9. Live GUI report/backend split
10. HTML report viewer + screenshot audit

하지만 Goal 완료 기준은 전체 구현이다. 우선순위는 중간 checkpoint용이지 scope 축소용이 아니다.

---

## 13. 절대 하지 말 것

- report view에 raw prompt, raw LLM stream, Python code, huge JSON dump를 노출하지 말 것.
- Guardian approval 없이 live hardware command를 실행하지 말 것.
- test 통과를 위해 agent 기능을 삭제하지 말 것.
- graph config와 runtime 실제 실행 순서를 따로 놀게 만들지 말 것.
- stale Vision signal을 robot/equipment action precondition으로 쓰지 말 것.
- FEM prediction을 실제 UTM observation으로 BO에 넣지 말 것.
- self-evolution 후보를 자동으로 production code에 patch하지 말 것.
- screenshot 확인 없이 "프론트 완료"라고 하지 말 것.
