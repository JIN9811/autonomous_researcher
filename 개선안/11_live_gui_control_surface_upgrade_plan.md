# 11. Live GUI Control Surface 고도화안 - 개선안 1~10 + 현재 코드 기준

대상: `web/templates/planning.html`, `web/static/planning.js`, `web/static/styles.css`, `app/controller.py`, `app/main.py`, `tests/ui/planning_browser_audit.py`, `tests/ui/live_runtime_ide_browser_audit.py`

작성 목적: 개선안 01~10에 흩어진 Live GUI 요구사항을 현재 코드 구조에 맞춰 하나의 실행 가능한 프론트엔드/백엔드 개선안으로 정리한다.

중요 전제:

- 이 문서는 구현 전 설계 문서다.
- 스타일 레퍼런스 이미지는 아직 미제공 상태다.
- 레퍼런스 이미지가 들어오면 visual tone, spacing, iconography, typography는 이 문서의 기능 구조를 유지한 채 별도 반영한다.
- Live GUI는 장식용 대시보드가 아니라 실험 실행 control surface다.
- 기존 FastAPI + static JS + LangGraph runtime + Runtime IDE 구조를 버리지 않는다.

---

## 1. 결론

현재 Live GUI는 기능적으로는 이미 많은 구성요소를 갖고 있다.

현재 존재하는 주요 요소:

- `/live` 라우트와 `web/templates/planning.html`
- `planning-runtime-shell` 3영역 구조
- 왼쪽 agent binder
- 중앙 Report / Backend / Graph / Artifacts / Timeline view
- 오른쪽 persistent Runtime Chat
- approval panel
- quick actions
- bottom event / IO dock
- SSE event stream
- `/api/planning/session`, `/api/planning/message`, `/api/planning/bootstrap`
- `/api/runs/{run_id}/events`, `/artifacts`, `/approvals`, `/guardian/status`
- `/api/agents/{agent_id}/report`, `/backend-trace`, `/message`
- `live_chat_message.v1` 유사 payload와 approval event 처리
- BO plot, FEM contour, artifact card, graph mini view 렌더링 일부

문제는 기능 부재보다 다음에 가깝다.

- 시각 표현이 과하게 fanfare/UI demo 쪽으로 기울어 있다.
- operator가 장시간 보는 실험 콘솔로는 정보 위계가 흐리다.
- agent별 report 요구사항이 01~10 개선안 기준으로 완전히 특성화되어 있지 않다.
- raw backend trace와 operator-facing report의 분리가 아직 더 엄격해야 한다.
- 모든 chat card가 `live_chat_message.v1` 계약으로 통일되어 있지 않다.
- 승인, handoff, artifact, evidence, incident가 한 실험 run의 story로 읽히는 수준은 아직 부족하다.

따라서 목표는 새 GUI를 처음부터 다시 만드는 것이 아니라, 현재 `/live`를 다음 형태로 정리하는 것이다.

> 장비 앞 operator가 1920x1080 화면에서 오래 켜두고, 현재 단계/위험/필요 입력/다음 handoff/증거 파일을 즉시 이해할 수 있는 차분한 실험 실행 콘솔.

---

## 2. 현재 코드 기준 구조

### 2.1 프론트엔드 파일

- `web/templates/planning.html`
  - Live GUI HTML skeleton.
  - 현재 `planning-runtime-shell`은 header, binder, center, chat, bottom dock 구조를 가진다.
  - risky ID: `planning-chat-log`, `planning-message-input`, `btn-planning-send`, `live-report-panel`, `live-backend-panel`, `live-graph-panel`, `live-artifact-panel`, `live-timeline-detail-panel`, `live-agent-binder-list`, `live-approval-panel`.

- `web/static/planning.js`
  - Live GUI state manager.
  - session refresh, SSE, chat message send, approval resolve, agent binder, report/backend/artifact/graph/timeline 렌더링을 처리한다.
  - 주요 흐름:
    - `refreshPlanningState()`
    - `applyPlanningSession()`
    - `renderPlanningMessages()`
    - `renderLiveRuntime()`
    - `sendPlanningMessage()`
    - `bootstrapLiveOrchestrator()`
    - `resolveLiveApproval()`
    - `refreshLiveRunDetails()`

- `web/static/styles.css`
  - Live GUI와 Main GUI, Runtime IDE CSS가 한 파일에 섞여 있다.
  - Live GUI 관련 블록은 `.planning-live-body`, `.planning-runtime-shell`, `.live-*`, `.planning-chat-*` 중심이다.
  - 현재 dark/neon/gradient/glow 성격이 강하다.

### 2.2 백엔드 파일

- `app/main.py`
  - `/live` 혹은 `/planning` page route.
  - `/api/planning/session`
  - `/api/planning/bootstrap`
  - `/api/planning/message`
  - `/api/planning/artifacts/{run_id}/{specimen_id}/{filename}`
  - `/api/agents/{agent_id}/report`
  - `/api/agents/{agent_id}/backend-trace`
  - `/api/runs/{run_id}/events`
  - `/api/runs/{run_id}/artifacts`
  - `/api/runs/{run_id}/approvals`
  - `/api/runs/{run_id}/guardian/status`

- `app/controller.py`
  - planning session state와 LangGraph handoff를 관리한다.
  - `_append_planning_message()`가 chat/event 연결점이다.
  - `_run_planning_loop_tail()`에서 post-Specimen tail stage가 LangGraph runtime event를 Live GUI 메시지로 변환한다.
  - `live_chat_message.v1` 형식의 payload가 이미 일부 들어간다.

### 2.3 현재 테스트

- `tests/ui/planning_browser_audit.py`
  - FEM contour card, BO trace card 렌더링 검증.

- `tests/ui/live_runtime_ide_browser_audit.py`
  - Live GUI와 Runtime IDE 연동, approval, graph link 일부 검증.

- 관련 unit/integration tests
  - runtime graph validation/compile
  - main entry/render smoke

---

## 3. 개선안 01~10에서 Live GUI가 요구하는 것

### 3.1 01 Design Agent

Live GUI는 단순히 설계 완료 메시지를 보여주면 안 된다.

필요 화면:

- 목표/제약 요약
- 후보 형상 보드
- 이전 cycle 대비 변경점
- 제조 가능성 판정
- BO/Guardian/Specimen handoff 이유
- 누락 입력값과 operator 질문

필요 메시지:

- `agent_id=design`
- `message_type=status|question|decision|warning|handoff`
- `candidate_id`
- `requires_response`
- `evidence_refs`

### 3.2 02 Specimen Making Agent

Specimen 단계는 STL viewer 중심이 아니다. 실제로는 digital fabrication thread를 보여줘야 한다.

필요 화면:

- geometry spec
- mesh/manufacturability gate
- slicer setting
- G-code path
- PrusaLink readiness
- upload/start result
- ejection status
- printer step trace
- artifact ledger: STL, G-code, log, preview image

필요 메시지:

- `agent_id=specimen`
- `message_type=status|artifact|warning|handoff`
- `specimen_id`
- `printer_job_id`
- `artifact_refs`

### 3.3 03 Vision Agent

Vision은 카메라 미리보기만 보여주는 창이 아니다. agent들이 사용할 perception signal console이어야 한다.

필요 화면:

- zone state
- latest frame / evidence artifact
- signal timeline
- confidence / stability
- blocking reason
- 어떤 agent에게 어떤 signal을 보냈는지

필요 메시지:

- `agent_id=vision`
- `message_type=status|signal|warning|artifact|handoff`
- `signal_id`
- `zone_id`
- `confidence`
- `stability_ms`

### 3.4 04 Manipulation Agent

Manipulation은 VLA action 로그만 보여주면 부족하다.

필요 화면:

- task episode card
- skill id: print-to-UTM, UTM-to-disposal 등
- policy checkpoint
- robot/camera profile
- action clamp / safe speed
- precondition checklist
- operator approval 필요 여부
- continuous rollout status
- SARM/Guardian stop condition

필요 메시지:

- `agent_id=manipulation`
- `message_type=status|decision|warning|artifact|handoff|approval`
- `task_id`
- `skill_id`
- `episode_id`
- `risk_score`

### 3.5 05 Lab Equipment Agent

Equipment는 Windows PyAutoGUI 명령 성공만 보여주면 안 된다.

필요 화면:

- Windows bridge target
- command sent 여부
- visual assertion before/after
- UTM physical motion cross-check
- data export path
- Linux artifact pull
- parse probe
- failure/retry evidence

필요 메시지:

- `agent_id=equipment`
- `message_type=status|tool_call|warning|artifact|handoff|approval`
- `command_id`
- `windows_host`
- `visual_assertion`
- `data_file_ref`

### 3.6 06 Analysis Agent

Analysis는 CSV를 읽었다는 로그가 아니다. raw UTM/FEM data가 BO objective JSON으로 바뀌는 과정을 보여야 한다.

필요 화면:

- input file identity
- parser confidence
- column mapping
- zero/flat/malformed quality gate
- preprocessing summary
- FEM cache/fresh/stub status
- BO payload preview
- artifact ledger: raw, interim, processed, FEM, BO JSON

필요 메시지:

- `agent_id=analysis`
- `message_type=status|artifact|decision|warning|handoff`
- `file_id`
- `parser_confidence`
- `fem_cache_status`
- `bo_payload_ref`

### 3.7 07 BO Agent

BO는 다음 파라미터 추천 메시지로 끝나면 안 된다. optimizer cockpit이어야 한다.

필요 화면:

- surrogate model status
- acquisition function
- explored points
- selected next candidate
- expected improvement / risk
- constraint repair reason
- FEM-informed candidate 여부
- BO graph plot
- LLM reasoning memo는 compact collapsible로 제공

필요 메시지:

- `agent_id=bo`
- `message_type=status|decision|warning|handoff`
- `candidate_id`
- `acquisition_score`
- `constraint_risk`
- `reasoning_ref`

### 3.8 08 Knowledge Agent

Knowledge는 RAG 검색 결과 목록이 아니다. memory/evolution board여야 한다.

필요 화면:

- ingested reports
- memory record
- evidence pack quality
- retrieval result
- self-evolution proposal status
- proposed/tested/approved/deployed 상태 분리

필요 메시지:

- `agent_id=knowledge`
- `message_type=status|artifact|warning|decision|approval`
- `record_id`
- `retrieval_id`
- `proposal_id`
- `evidence_quality`

### 3.9 09 Guardian Agent

Guardian은 마지막 통과/실패 판정만 보여주면 안 된다. graph-wide safety monitor여야 한다.

필요 화면:

- active risk map
- gate timeline
- blocked action
- incident / near-miss ledger
- approval queue
- policy version
- corrective action

필요 메시지:

- `agent_id=guardian`
- `message_type=decision|warning|approval|incident|status`
- `risk_class`
- `severity`
- `decision`
- `interrupt_id`

### 3.10 10 Orchestration Agent

Orchestrator는 keyword router 로그가 아니다. 전체 autonomous run supervisor여야 한다.

필요 화면:

- current mission contract
- missing input checklist
- current route / next edge
- follow-up decision
- handoff packet validation
- pending operator response
- loop reflection

필요 메시지:

- `agent_id=orchestrator`
- `message_type=status|question|decision|warning|handoff|approval|incident|signal`
- `stage`
- `node_id`
- `handoff_id`
- `requires_response`
- `evidence_refs`

---

## 4. Live GUI 공통 계약

### 4.1 `live_chat_message.v1`

모든 agent가 chat에 띄우는 operator-facing 메시지는 다음 형태로 정규화한다.

```json
{
  "schema": "live_chat_message.v1",
  "agent_id": "design|specimen|vision|manipulation|equipment|analysis|bo|knowledge|guardian|orchestrator|system",
  "role": "design_ai|specimen_ai|vision_ai|manipulation_ai|equipment_ai|analysis_ai|bo_ai|knowledge_ai|guardian_ai|orchestrator|system",
  "message_type": "status|question|decision|warning|handoff|artifact|approval|incident|signal|tool_call",
  "headline": "one-line operator-facing update",
  "content": "short readable body",
  "timestamp": "ISO-8601",
  "stage": "current graph stage",
  "node_id": "current graph node id",
  "run_id": "active run id",
  "requires_response": false,
  "actions": ["approve", "edit", "retry", "pause", "open_report", "open_backend", "open_artifact"],
  "evidence_refs": ["artifact://...", "trace://...", "memory://..."],
  "artifact_refs": [],
  "risk": {
    "score": 0.0,
    "class": "none|low|medium|high|critical"
  },
  "payload_ref": "backend trace id or report section id"
}
```

원칙:

- `content`는 사람이 읽는 문장이다.
- raw JSON, raw traceback, raw prompt는 직접 chat에 뿌리지 않는다.
- chat card의 버튼은 실제 API나 view action에 연결되어야 한다.
- artifact는 미리보기 가능한 경우만 preview하고, 큰 파일은 link/card로 둔다.

### 4.2 `agent_report_page.v1`

`/api/agents/{agent_id}/report`는 현재 `_agent_report_payload()` 구조를 유지하되 다음 공통 section을 보장한다.

필수 공통 section:

- `overview`
- `current_status`
- `decisions`
- `evidence_quality`
- `handoff_packets`
- `next_action`
- `warnings`
- `artifacts`
- `backend_refs`
- `guardian_gate`

Agent별 특화 section:

- Design: `candidate_board`, `manufacturability`, `decision_register`, `handoff_to_specimen`
- Specimen: `digital_thread`, `slicer_profile`, `printer_runtime`, `ejection_status`
- Vision: `scene_map`, `signal_board`, `evidence_timeline`
- Manipulation: `task_episodes`, `policy_runtime`, `safety_envelope`
- Equipment: `control_trace`, `visual_assertion`, `physical_verification`, `data_ledger`
- Analysis: `data_ingestion`, `quality_gate`, `fem_panel`, `bo_payload`
- BO: `surrogate_panel`, `candidate_ranking`, `acquisition_trace`, `reasoning_audit`
- Knowledge: `memory_commit`, `evidence_pack`, `evolution_proposals`
- Guardian: `risk_map`, `gate_timeline`, `incident_ledger`, `approval_queue`
- Orchestrator: `mission_contract`, `route_state`, `followup_decisions`, `loop_reflection`

### 4.3 Backend trace 분리

Report view와 Backend view는 엄격히 분리한다.

Report view에 보여도 되는 것:

- operator-facing summary
- status
- decision reason
- artifact card
- figure/plot/preview
- handoff summary
- approval state

Backend view에만 보여야 하는 것:

- raw prompt
- raw LLM stream
- raw tool input/output JSON
- stack trace
- raw event payload
- full logs
- debug trace

---

## 5. 레이아웃 개선안

### 5.1 전체 방향

현재 구조는 유지한다.

```text
header
binder | center report/backend/graph/artifacts/timeline | runtime chat
bottom event/io dock
```

단, visual tone과 정보 위계를 바꾼다.

목표:

- 덜 팬시하게
- 더 차분하게
- 장비 운영 콘솔처럼
- 1920x1080에서 한 화면 관제 가능
- 오래 봐도 피로하지 않게
- action과 evidence가 명확하게

금지:

- 과한 glow
- 과한 neon gradient
- 계속 깜빡이는 animation
- 장식성 카드 남발
- raw JSON을 report에 직접 노출
- 버튼이 실제 기능 없이 decorative하게 보이는 것

### 5.2 Header

현재 header에는 많은 chip이 있다.

유지해야 할 정보:

- current stage
- run id / mode
- active agent
- backend stream/sync 상태
- pending fault / approval count
- elapsed time
- resource 요약
- Safe Stop

개선 방향:

- header 높이를 줄인다.
- status chip은 1줄로 유지한다.
- 불필요한 glow는 제거한다.
- `STOP`은 작지만 항상 보이게 한다.
- hover tooltip은 유지하되 중복 tooltip은 금지한다.

### 5.3 Agent Binder

현재 `AGT` narrow sidebar는 유지한다.

개선 방향:

- agent icon + short label + status dot만 기본 표시한다.
- warning/approval/unread badge는 badge로 표시한다.
- hover 시 agent full name과 current status를 보여준다.
- click 시 center report와 chat target이 동기화된다.
- active agent는 과한 glow 대신 solid border 또는 left accent line으로 표시한다.

### 5.4 Center Panel

Center는 Live GUI의 주 화면이다.

기본 view는 `Report`다.

탭:

- Report
- Backend
- Graph
- Artifacts
- Timeline

개선 방향:

- 탭은 icon + 짧은 label로 유지한다.
- 현재 선택 agent의 특화 report가 기본으로 뜬다.
- Agent report는 논문식 문장보다는 운영식 section card를 우선한다.
- 큰 plot/figure는 card 안에 맞추고 기본 접힘/펼침을 제공한다.
- BO/FEM/vision image는 chat width와 center width에 맞게 자동 fit한다.
- Backend 탭은 raw trace 전용으로 유지한다.

### 5.5 Runtime Chat

Chat은 항상 유지되는 persistent surface다.

개선 방향:

- 채팅창은 상용 LLM처럼 단순하고 읽기 쉽게 한다.
- message card는 agent별 색을 약하게만 적용한다.
- 시스템 메시지는 작고 명확하게 둔다.
- `SYSTEM_EVENT` 문자열을 그대로 보여주지 말고, UI에서 `handoff`, `blocked`, `approval required`로 해석해 보여준다.
- reasoning은 기본 접힘 또는 작은 회색 텍스트로 둔다.
- 진행 중 spinner는 최소화한다.
- 새 메시지 도착 시 chat bottom으로 안정적으로 auto-scroll한다.
- user input은 실제 채팅창 안에 붙어 있어야 한다.

Composer:

- placeholder는 실제 도움이 되는 문구로 둔다.
- Enter 전송 여부는 운영 안전 관점에서 결정한다.
- live hardware command가 포함될 수 있으므로 기본은 `Ctrl+Enter` 또는 Send 버튼을 권장한다.
- 사용자가 원하면 Enter send 옵션을 설정으로 제공한다.

### 5.6 Quick Actions

현재 quick action이 오른쪽 chat 상단에 많다.

개선 방향:

- 기본 노출:
  - Approve
  - Reject
  - Pause
  - Resume
  - Safe Stop
- 나머지:
  - Dry Run
  - Open Graph
  - Open Backend
  - Show Artifacts
  - Node Test
  - Report Edit
  - 는 compact action menu 안으로 이동한다.

원칙:

- live action은 Guardian/pending approval 상태를 확인해야 한다.
- blocked action은 버튼 disabled + reason tooltip을 제공한다.
- action result는 chat에 장황하게 띄우지 말고 timeline/backend trace에 남기고 status만 chat에 보여준다.

### 5.7 Bottom Dock

현재 event/IO dock은 접기 기능이 있다.

개선 방향:

- 기본은 접힌 상태도 고려한다.
- 펼쳤을 때만 timeline strip과 IO cards가 보인다.
- 접혀도 `warning/error/approval count`는 header에서 보인다.
- Timeline은 event stream이며, detail은 Center `Timeline` view로 보낸다.
- IO는 device health summary이며, 상세는 Device Workspace 또는 Backend view로 보낸다.

---

## 6. Agent별 Live Report 카드 구성

### 6.1 Design 카드

상단 summary:

- selected candidate
- geometry type
- objective
- constraints missing/passed
- next handoff target

본문 cards:

- Candidate Board
- Constraint Gate
- Manufacturability
- Decision Register
- Handoff Packet

### 6.2 Specimen 카드

상단 summary:

- specimen id
- fabrication mode: virtual/test/live
- slicer status
- printer status
- ejection status

본문 cards:

- Digital Thread
- Mesh Quality
- Slicer Profile
- Printer Runtime
- Artifact Ledger
- Guardian Gate

중요:

- STL viewer를 중심에 두지 않는다.
- 필요한 경우 STL은 screenshot/preview artifact로만 표시한다.
- slicer/PrusaLink/G-code/ejection/step trace가 주 내용이다.

### 6.3 Vision 카드

상단 summary:

- active camera/zone
- latest signal
- confidence
- blocked state

본문 cards:

- Scene Map
- Signal Board
- Evidence Timeline
- Cross-Agent Signals
- Warnings

### 6.4 Manipulation 카드

상단 summary:

- selected policy
- active skill
- current episode
- safe rollout state
- operator approval state

본문 cards:

- Task Episodes
- Policy Runtime
- Camera/Robot Profile
- Action Safety Envelope
- Recovery/Stop Conditions

### 6.5 Equipment 카드

상단 summary:

- bridge host
- active command
- screen assertion status
- physical verification status
- data acquisition status

본문 cards:

- Command Trace
- Visual Assertion
- Physical Verification
- Data Ledger
- Failure/Retry Evidence

### 6.6 Analysis 카드

상단 summary:

- input file
- parser confidence
- quality gate
- objective value
- BO handoff status

본문 cards:

- Data Ingestion
- Quality Gate
- FEM/CAE Panel
- Metrics
- BO Payload

### 6.7 BO 카드

상단 summary:

- selected acquisition
- selected candidate
- score
- risk
- next design request

본문 cards:

- Surrogate Panel
- Acquisition Trace Plot
- Candidate Ranking
- Constraint Repair
- Reasoning Audit

### 6.8 Knowledge 카드

상단 summary:

- memory commit status
- evidence coverage
- evolution proposal count
- retrieval quality

본문 cards:

- Memory Commit
- Evidence Pack
- Retrieval Results
- Evolution Proposal Board
- Deployment Gate

### 6.9 Guardian 카드

상단 summary:

- current decision
- max risk
- pending approvals
- blocked actions

본문 cards:

- Risk Map
- Gate Timeline
- Incident Ledger
- Approval Queue
- Corrective Actions

### 6.10 Orchestrator 카드

상단 summary:

- mission state
- current route
- missing inputs
- next stage
- follow-up status

본문 cards:

- Mission Contract
- Route State
- Handoff Validation
- Follow-up Decisions
- Loop Reflection

---

## 7. Styling 방향

### 7.1 현재 문제

현재 Live GUI는 dark/neon Runtime IDE theme이 강하다.

문제점:

- 기능이 많아질수록 화면이 복잡해 보인다.
- glow/gradient가 장비 상태 색과 경쟁한다.
- 중요한 warning/approval이 decorative color 사이에서 묻힌다.
- operator-facing console보다는 demo UI 느낌이 강하다.

### 7.2 목표 스타일

레퍼런스 이미지가 오기 전까지의 임시 기준:

- dark base는 유지 가능하되 saturation을 낮춘다.
- panel background는 거의 flat한 deep navy/charcoal로 둔다.
- gradient는 header 또는 background에만 아주 약하게 사용한다.
- agent status colors만 명확하게 사용한다.
- button은 작고 실용적으로 둔다.
- typography는 compact하고 선명하게 둔다.
- animation은 최소화한다.

상태색 기준:

- ok: muted green
- running: blue
- warning: amber
- error/block: red
- approval: amber + border
- idle: gray

### 7.3 레퍼런스 이미지 반영 시 할 일

사용자가 레퍼런스 이미지를 제공하면 다음만 업데이트한다.

- spacing scale
- color palette
- card radius/shadow
- icon style
- panel hierarchy
- chat bubble style
- report section layout
- graph/timeline visual tone

반드시 유지할 것:

- existing IDs
- current API contract
- `live_chat_message.v1`
- report/backend 분리
- approval/safe-stop guard
- 1920x1080 no-overlap requirement

---

## 8. 구현 순서

### Phase 0. Baseline capture

작업 전 반드시 현재 상태를 저장한다.

- `/live` screenshot 1920x1080
- `/live?auto=1` screenshot
- Report view screenshot
- Backend view screenshot
- Graph view screenshot
- Artifacts view screenshot
- Timeline view screenshot
- approval card screenshot
- BO/FEM artifact card screenshot

기록 위치:

- `artifacts/live_gui_upgrade/baseline/`

### Phase 1. Visual tone down

목표:

- 기능 변경 없이 CSS만 안정화한다.

작업:

- glow/gradient/animation 줄이기
- panel border/shadow 약화
- typography 위계 정리
- button 크기 통일
- chip 색 정리
- chat auto-scroll 유지 확인

주의:

- 이 단계에서 API나 message schema를 건드리지 않는다.

### Phase 2. Layout hierarchy 정리

목표:

- 1920x1080 기준에서 operational focus를 높인다.

작업:

- header 1줄 유지
- quick action 축소 및 action menu화
- chat vertical space 확대
- bottom dock 기본 접힘 옵션 검토
- center panel report section spacing 정리
- graph/artifact/plot output max width 표준화

### Phase 3. `live_chat_message.v1` renderer 통합

목표:

- chat card rendering을 message contract 중심으로 통일한다.

작업:

- `schema=live_chat_message.v1` 전용 renderer 생성
- `message_type`별 카드 스타일 정리
- `actions` button map 구현
- `evidence_refs` link/card 구현
- `requires_response` 표시
- `SYSTEM_EVENT` raw text를 operator-facing card로 변환

### Phase 4. Agent report renderer 특성화

목표:

- 1~10번 개선안의 agent별 report section을 center panel에 반영한다.

작업:

- `renderDesignReport()`
- `renderSpecimenReport()`
- `renderVisionReport()`
- `renderManipulationReport()`
- `renderEquipmentReport()`
- `renderAnalysisReport()`
- `renderBoReport()`
- `renderKnowledgeReport()`
- `renderGuardianReport()`
- `renderOrchestratorReport()`

주의:

- 특화 section이 없으면 fallback card를 보여준다.
- raw payload dump로 대체하지 않는다.

### Phase 5. Backend trace/report 분리 강화

목표:

- report에는 사람이 읽는 정보만, backend에는 raw trace만.

작업:

- Backend view는 event raw payload, tool input/output, trace id, stack trace만 표시
- Report view는 section card와 artifact summary만 표시
- `Open Backend` action은 selected agent/event/report section을 trace context로 연동

### Phase 6. Approval/Guardian UX 정리

목표:

- 위험/승인/차단 상태를 operator가 즉시 이해하게 한다.

작업:

- pending approval strip
- approval card compact design
- approve/reject/revise action result state
- blocked action tooltip
- Guardian gate summary in each report
- Safe Stop confirmation UX 유지

### Phase 7. Artifact/figure 표준화

목표:

- BO/FEM/STL/image/table output이 chat과 center panel에서 일관되게 보인다.

작업:

- artifact card common renderer
- figure max-width/max-height standard
- collapse/expand for heavy plots
- SVG/PNG handling 분리
- BO graph 기본 접힘 여부 결정
- STL은 viewer가 아니라 screenshot/preview artifact 중심

### Phase 8. Browser audit 강화

목표:

- DOM 테스트만이 아니라 실제 screenshot 기반으로 검증한다.

필수 검사:

- 1920x1080 no horizontal overflow
- header chip no overlap
- agent binder click changes report and chat target
- report/backend/graph/artifact/timeline tab works
- chat auto-scroll works
- approval card action works with mocked approval
- BO plot card collapse/expand works
- FEM contour card renders
- backend raw JSON is absent from report view
- raw JSON is present only in backend view

---

## 9. API와 코드 변경 원칙

### 9.1 유지해야 할 API

- `GET /live`
- `GET /planning`
- `GET /api/planning/session`
- `POST /api/planning/bootstrap`
- `POST /api/planning/message`
- `GET /api/planning/artifacts/{run_id}/{specimen_id}/{filename}`
- `GET /api/agents`
- `GET /api/agents/{agent_id}/report`
- `GET /api/agents/{agent_id}/backend-trace`
- `POST /api/agents/{agent_id}/message`
- `GET /api/runs/{run_id}/events`
- `GET /api/runs/{run_id}/artifacts`
- `GET /api/runs/{run_id}/approvals`
- `POST /api/runs/{run_id}/approvals/{approval_id}/resolve`
- `GET /api/runs/{run_id}/guardian/status`

### 9.2 변경 가능한 것

- payload에 optional field 추가
- report section 추가
- event normalization 추가
- frontend renderer 추가
- CSS 변수/레이아웃 개선
- browser audit 추가

### 9.3 피해야 할 것

- 기존 endpoint 삭제
- existing element ID 삭제
- approval guard 우회
- live hardware command를 바로 실행하는 shortcut 추가
- report view에 raw JSON dump 표시
- backend trace를 숨겨 디버깅 불가능하게 만들기
- Runtime IDE와 Live GUI의 역할 혼동

---

## 10. 현재 코드에 바로 맞는 구현 포인트

### 10.1 `planning.html`

작업 후보:

- quick actions를 compact menu로 이동
- chat header 단순화
- header chip grouping
- bottom dock collapsed state 기본값 검토
- report/backend/graph/artifacts/timeline tab 유지
- style reference image 수용을 위한 class name 추가

### 10.2 `planning.js`

작업 후보:

- `renderLiveChatMessageV1(message)` 추가
- `renderAgentReport(agentId, report)` 분리
- `renderAgentReportSection(section)` 공통화
- `renderBackendTraceOnly(trace)` 분리
- `renderArtifactCard(artifact)` 공통화
- `renderApprovalCard(approval)` 정리
- `normalizePlanningMessage()`에서 old message와 `live_chat_message.v1` bridge
- `SYSTEM_EVENT` parser를 UI card로 변환
- `scrollChatToBottom()` 안정화

### 10.3 `styles.css`

작업 후보:

- `.planning-live-body` CSS를 별도 section으로 정리
- neon gradient downscale
- report card compact style
- chat card readable style
- status color token 정리
- 1920x1080 responsive guard
- `prefers-reduced-motion` 반영

### 10.4 `app/controller.py`

작업 후보:

- `_append_planning_message()`에서 `schema=live_chat_message.v1` 보장
- stage handoff를 raw `SYSTEM_EVENT` 문자열이 아니라 structured payload로 emit
- Orchestrator follow-up message에 `actions`, `requires_response`, `evidence_refs` 보강
- agent별 report payload를 run_metadata에서 더 적극적으로 병합

### 10.5 `app/main.py`

작업 후보:

- `_agent_report_payload()` 공통 section 확장
- `/api/agents/{agent_id}/report`가 agent별 latest report를 우선 사용
- `/api/agents/{agent_id}/backend-trace`가 raw event/tool payload를 안정적으로 반환
- approval queue와 Guardian status를 report에 summary로 넣되, raw는 backend로 분리

---

## 11. 검증 계획

### 11.1 정적 검사

```bash
node --check web/static/planning.js
node --check web/static/app.js
node --check web/static/runtime_ide.js
git diff --check
```

### 11.2 Python 테스트

최소:

```bash
.venv/bin/pytest tests/unit/test_langgraph_runtime.py -q
.venv/bin/pytest tests/integration/test_live_gui_runtime_layout.py -q
```

추가 권장:

```bash
.venv/bin/pytest tests/ui -q
```

### 11.3 Browser audit

```bash
python tests/ui/planning_browser_audit.py \
  --base-url http://127.0.0.1:7860 \
  --webdriver-url http://127.0.0.1:4448 \
  --out-dir artifacts/live_gui_upgrade

python tests/ui/live_runtime_ide_browser_audit.py \
  --base-url http://127.0.0.1:7860 \
  --webdriver-url http://127.0.0.1:4448 \
  --out-dir artifacts/live_gui_upgrade
```

### 11.4 Screenshot checklist

필수 저장:

- `live_desktop_default.png`
- `live_desktop_report_design.png`
- `live_desktop_report_specimen.png`
- `live_desktop_report_equipment.png`
- `live_desktop_report_analysis.png`
- `live_desktop_report_bo.png`
- `live_desktop_report_guardian.png`
- `live_desktop_chat_approval.png`
- `live_desktop_backend_trace.png`
- `live_desktop_graph_view.png`
- `live_desktop_artifacts_view.png`
- `live_desktop_bottom_dock_collapsed.png`
- `live_desktop_bottom_dock_expanded.png`

육안 확인 기준:

- 1920x1080에서 header가 겹치지 않는다.
- center panel과 runtime chat이 겹치지 않는다.
- chat 내용이 잘리지 않는다.
- agent binder 텍스트/아이콘이 겹치지 않는다.
- warning/approval이 즉시 보인다.
- raw JSON이 report view에 노출되지 않는다.
- Backend view에는 raw trace가 보인다.
- graph/artifact/plot은 화면 폭에 맞는다.

---

## 12. Definition of Done

Live GUI 개선은 다음을 만족해야 완료로 본다.

1. 기존 `/live` 기능이 삭제되지 않았다.
2. 01~10 agent별 report 요구사항이 최소 fallback section 형태로 반영됐다.
3. `live_chat_message.v1` renderer가 있다.
4. `SYSTEM_EVENT` raw 문자열이 operator-facing card로 변환된다.
5. Report view와 Backend trace view가 분리됐다.
6. Approval/Guardian state가 header, chat, report에서 일관되게 보인다.
7. BO plot/FEM contour/artifact card가 chat과 center panel에서 깨지지 않는다.
8. 1920x1080 browser screenshot에서 겹침이 없다.
9. `planning_browser_audit.py`가 통과한다.
10. live hardware action은 Guardian/human approval gate 없이 실행되지 않는다.
11. style reference image가 제공되면 CSS만으로 tone을 맞출 수 있는 class/token 구조가 있다.
12. 문서와 테스트가 같이 갱신됐다.

---

## 13. 이번 문서 이후 다음 작업

사용자가 reference image를 제공하면 다음 순서로 진행한다.

1. Reference image 육안 분석
2. 현재 `/live` screenshot과 비교
3. color/spacing/card hierarchy CSS patch
4. Browser screenshot 검증
5. `live_chat_message.v1` renderer 통합
6. agent별 report card 순차 고도화
7. approval/Guardian UX 정리
8. artifact/plot/card 표준화
9. docs/tests 업데이트
10. commit/push

---

## 14. 작업 우선순위

우선순위 1:

- 스타일 tone down
- chat readability
- report/backend 분리
- 1920x1080 no-overlap

우선순위 2:

- `live_chat_message.v1` renderer
- system event card화
- approval card 정리
- agent report fallback section

우선순위 3:

- agent별 특화 report 심화
- BO/FEM/vision/manipulation/equipment artifact renderer 고도화
- dedicated report viewer 확장

우선순위 4:

- Knowledge/Self-Evolution/Guardian incident board 심화
- full screenshot audit 자동화
- report print/export polish

---

## 15. 최종 판단

Live GUI는 이미 기능적으로는 출발점이 충분하다.

하지만 현재는 기능이 많이 붙으면서 화면이 데모성으로 복잡해졌다. 개선 방향은 새 기능을 더 붙이는 것이 아니라, 이미 있는 runtime chat, report, backend trace, graph, artifacts, approval, timeline을 operator가 읽을 수 있는 구조로 정돈하는 것이다.

Live GUI의 최종 역할은 다음이다.

> Orchestrator와 모든 agent의 판단, handoff, evidence, approval, incident를 한 화면에서 사람이 이해하고 개입할 수 있게 하는 실험 실행 콘솔.

