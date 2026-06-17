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
- [ ] 장비 상태가 필요하면 Main GUI의 `Device Workspaces`에서 `/printer`, `/equipment/windows`, `/lerobot`, `/bo`, `/cae` 전용 GUI를 먼저 열어 bridge 상태를 확인
- [ ] Run 시작 버튼 → run_id 발급
- [ ] 이벤트 스트림에 다음이 순차로 뜨는지 확인
  - `run.started`
  - `node.started(node=design)`
  - `node.completed`
  - `edge.traversed` 또는 `stage_transition`
- [ ] 마지막에 `run_complete` 또는 `run.failed`

### 1.1 Device Workspace와 Live GUI의 관계

- Main GUI의 `Device Workspaces`는 장비별 설정/검증 surface다. 3DP Printer Bridge는 Bambu Lab X2D를 기본 profile로 사용하고, Prusa MK4S는 명시 선택된 경우에만 사용된다.
- BambuLab X2D bridge의 provider 계층, MQTT/FTPS/HTTP/camera plane, native G-code autoejection gate는 `docs/hardware/bambulab_x2d_device_bridge_runtime_guideline.md`에 별도 설명한다. 이 문서는 closed-loop와 page/API contract만 고정한다.
- Bambu bridge evidence는 `artifact`, `validation`, `transport`, `runtime`, `bed-clear` 5개 plane으로 나뉜다. Live GUI와 3DP GUI는 이 plane을 같은 의미로 표시해야 하며, `published=true`만으로 physical ejection success를 표시하면 안 된다.
- Live GUI는 별도 fake 상태를 만들지 않는다. Specimen Making Agent report는 3DP GUI/API가 반환한 `selected_printer`, `device_screen`, `preprint_gate`, `readiness_levels`, `operator_actions`, `autoejection`, `bed_clear`를 그대로 요약한다.
- Design Agent는 Bambu autoejection을 사용할 수 있는 후보에 대해 `bambu_autoejection_readiness`를 authoritative experiment spec과 design report에 기록한다. 이 객체는 `ejection_contact_edge`, `bed_contact_area_mm2`, `bed_contact_area_ratio`, `minimum_pushable_height_mm`, `pushable_edge_height_mm`, skirt/brim/raft policy를 포함한다. Specimen Making Agent는 이 객체를 `fabrication_report.process_plan.bambu_autoejection_readiness`와 `specimen_agent_report.bambu_autoejection_readiness`에 그대로 보존해 설계-side 접촉면/밀림 edge/skirt-brim-raft 정책과 printer-side validator evidence가 같은 trace에서 읽히게 한다.
- Bambu autoejection의 primary path는 Bambu 전용 deterministic G-code patch/validation이다. `bambu_gcode_patch` provider는 sliced `.gcode.3mf` 또는 plain `.gcode`를 원본 보존 방식으로 `.autoeject.*` artifact로 만들고, actual publish는 owner-managed publish defaults, backend start gate, camera/bed-clear evidence, printer safe-state 검증 이후에만 가능하다. Manipulation Agent는 primary ejection executor가 아니라 failed ejection recovery 또는 downstream specimen transfer 계층으로 남긴다.
- Bambu bed-clear gate는 operator checkbox만으로 닫히지 않는다. 3DP GUI의 `Video Status` 또는 `Pre-start Check`가 최신 camera preview/proxy evidence를 확보하고, `Mark Bed Clear`가 그 값을 `/api/printer/bed-clear`의 `camera_snapshot_path`로 저장해야 다음 cycle gate evidence와 Live GUI report가 같은 근거를 참조한다. Guarded `.autoeject.*` publish 성공 시 backend는 가능하면 `artifacts/bambu_camera_evidence/` 아래 로컬 JPEG를 저장하고 그 파일을 evidence로 사용한다.
- `/api/bridges`와 `/api/printer/fleet`는 같은 계층이 아니다. `/api/bridges`는 Runtime IDE/Live GUI가 graph metadata bridge boundary를 읽는 normalized discovery API이며, workspace, health/preflight endpoint, `actions[]`에 들어간 standard/custom action descriptor, evidence contract를 같은 shape로 반환한다. Bambu/Prusa active printer 선택은 `/api/printer/fleet`가 담당한다. 현재 Bambu Lab X2D 기본 profile은 `/api/printer/fleet`에서 확인한다.
- 현재 route/API/manifest 스냅샷은 [current_code_snapshot.md](current_code_snapshot.md)를 기준으로 갱신한다.

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

### 2.5 Live GUI transcript 저장 계약

Live GUI 대화는 브라우저 메모리에만 저장하지 않습니다. 컨트롤러는 각
planning/chat 메시지를 compact 형태로
`runs/<active_run_id>/live_planning_transcript.jsonl`에 append하고, 메모리에는
최근 window만 유지합니다.

- 최신 상태: `GET /api/planning/session`
- 이전 메시지 페이지: `GET /api/planning/messages?before=<index>&limit=<n>`
- 명시 초기화: fresh session 경로에서 transcript 파일 삭제

따라서 새 창/새로고침 후에는 `/api/planning/session`과
`/api/planning/messages`를 기준으로 현재 상태를 복원해야 합니다. Live GUI가
별도 local-only 상태를 source of truth로 삼으면 runtime state와 대화 내용이
갈라질 수 있습니다.

### 2.6 custom stage 현재 지원 범위

현재 코드는 고정 `Stage` enum을 완전히 제거하지 않았지만,
graph-validated extension stage 문자열은 `Stage._missing_()` pseudo-member로
통과시킵니다. 최소 보장 범위는 다음입니다.

- active graph에 `custom_quality_gate` 같은 stage가 있으면 `.value` 기반으로
  serialization됩니다.
- allowlisted `agent.*` handler와 module config가 붙은 custom stage는
  LangGraphRunLoop에서 실행될 수 있습니다.
- `MainController`의 Orchestrator plan/control-plane snapshot은 active graph
  route를 사용하므로 custom stage가 `latest_orchestration_plan`,
  `route_state`, task queue에 표시됩니다.
- module `output_contracts[]`와 list-valued `io_contract.output`은 supervisor
  route step의 `required_outputs`로 승격됩니다.

아직 완전하지 않은 부분은 custom stage별 domain-specific report authoring과
custom action execution UX입니다. Graph-unattached module은 Module
Management에서 `/ide?module=<id>&action=attach`로 Runtime IDE에 넘길 수
있고, Runtime IDE가 Module Library attach 대상을 강조합니다. 실제 graph
edit/activation은 여전히 Runtime IDE의 drag/drop, port 연결,
validate/dry-run, Save Version gate를 통과해야 합니다. 현재 backend는
payload/module runtime의 `supervisor_policy`를 읽을 수 있고 Module
Management는 주요 descriptor 필드를 typed form으로 편집할 수 있습니다. 이 잔여 범위는
`개선안/12_free_modularization_gap_analysis.md`에 추적합니다.

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
| 3DP/Printer GUI | `/printer` | `printer.html` | Bambu Lab X2D 기본 device bridge, 명시적 printer fleet 선택, connection, live video probe/proxy, Bambu Studio slicing, sliced artifact route, pre-start checklist, start gate, guarded MQTT start publish, SPC readiness, autoejection gate 확인, physical proof package 감사 | `/api/printer/fleet`, `/api/printer/profile`, `/api/printer/status`, `/api/printer/video-status`, `/api/printer/video-stream.mjpeg`, `/api/printer/connection`, `/api/printer/upload-path-probe`, `/api/printer/bambu-slice-artifact`, `/api/printer/http-artifact-route`, `/api/printer/bambu-prestart-check`, `/api/printer/start-command-draft`, `/api/printer/start-gate`, `/api/printer/start-publish`, `/api/printer/spc-readiness`, `/api/printer/autoejection-status`, `/api/printer/autoejection-config`, `/api/printer/autoejection-test`, `/api/printer/bambu-autoejection-patch`, `/api/printer/bambu-autoejection-sweep-test`, `/api/printer/bed-clear`, `/api/printer/bambu-autoejection-proof-template`, `/api/printer/bambu-autoejection-completion-audit` |
| BO Workspace | `/bo` | `bo.html` | BO/MBO/LLM preference 전략 설정, reasoning audit, candidate ranking, next-design handoff | `/api/bo/config`, `/api/bo/benchmark`, `/api/bo/run` |
| CAE Workspace | `/cae` | `cae.html` | 정적 CAE 분석 실행, 파라미터 저장, 결과 라인업 | `/api/cae/config`, `/api/cae/run` |
| Runtime IDE | `/ide` | `runtime_ide.html` | 그래프/에지/모듈 편집, module attach deep-link, validate/dry-run/실행, 버전관리 | `/api/graphs*`, `/api/modules*`, `/api/handlers` |
| Module Management | `/module-management` | `module_management.html` | 모듈 로드·언로드·검증·버전 저장, draft module 생성, `ui.yaml` descriptor 관리, handler/LLM/tool/prompt/safety/step typed edit, raw JSON edit | `/api/modules*`, `/api/modules/templates/*`, `/api/modules/{id}/ui`, `/api/runtime/agent-manifests`, `/api/bridges`, `/api/handlers` |
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
- **Printer fleet 연계**: 3DP GUI의 `/api/printer/fleet`는 active printer profile을 조회/저장한다. 기본값은 `bambulab_x2d_lab_01`이고, Prusa MK4S는 fallback이 아니라 operator가 명시 선택한 profile로만 실행된다. 선택값은 local-only `memory/printer_fleet.json`에 저장된다.
- **Fleet UI 상태 유지**: `/api/printer/fleet`가 반환한 `available_printers` 목록은 `/api/printer/status` 또는 `/api/printer/spc-readiness` 응답을 렌더링한 뒤에도 유지되어야 한다. 후속 응답이 selected printer만 포함하더라도 GUI가 Bambu/Prusa 선택 목록을 비어 있는 것으로 표시하면 안 된다.
- **Bambu slicer resolver**: Bambu profile의 slicer payload는 `BAMBU_STUDIO_EXECUTABLE` env var, configured wrapper path, `PATH`의 `bambu-studio` 순서로 executable을 해석한다. `/api/printer/profile`과 `/api/printer/status`는 `resolved_executable_path`, `available`, `source`, `output_dir`를 반환한다. Profile route는 Bambu Studio 설치 감지만 수행하며 upload/start readiness를 만들지 않는다.
- **Bambu slicer runner**: `/api/printer/bambu-slice-artifact`는 active profile이 Bambu일 때만 동작한다. 입력 source는 실제 로컬 `.stl` 또는 `.3mf`여야 하며, backend가 Bambu Studio CLI를 `--slice 0 --arrange 1 --ensure-on-bed --outputdir <artifact-dir> --export-3mf <safe-id>.gcode.3mf --debug 2` 형태로 실행한다. `--export-3mf` 값은 output directory 안의 basename이어야 하며, absolute path를 넘기면 Bambu Studio가 output directory를 중복 결합할 수 있다. 명시 `load_settings`가 없으면 runner는 X2D 기본 machine/process/filament profile을 output directory 아래 `_atr_no_skirt_profile/`로 복사하고 process JSON에 `skirt_loops=0`, `brim_type=no_brim`, `brim_width=0`, `raft_layers=0`을 주입한 뒤 `--load-settings`/`--load-filaments`로 사용한다. 결과는 `.gcode`, `.3mf`, `.gcode.3mf` 중 실제 생성된 파일 경로, size, sha256, command preview, stdout/stderr tail, `slicer_profile` evidence를 반환한다. 이 route는 slicing artifact 생성만 수행하며 upload, MQTT publish, print start를 수행하지 않는다.
- **Bambu pre-start checklist**: `/api/printer/bambu-prestart-check`는 사용자용 출력 직전 점검 route다. 실제 backend path를 `camera_status -> slice_artifact -> native_autoejection_patch_when_enabled -> http_artifact_route -> start_gate -> spc_readiness` 순서로 실행하고 stage별 결과를 반환한다. 이 route도 `will_publish=false`, `published=false`를 유지하며 MQTT `project_file` command를 보내지 않는다. `ready_to_publish=true`는 기술적으로 publish 가능한 조건이 검증됐다는 뜻이지, 출력이 시작됐다는 뜻이 아니다.
- **Bambu pre-start aggregate**: Pre-start Check는 Bambu Studio Device 탭처럼 camera, thermal/progress, AMS/material, transfer/start, autoejection, bed-clear evidence를 한 번에 갱신한다. Camera/video plane은 status plane과 독립이다. Video probe 실패 또는 `/api/printer/video-status` 재호출이 기존 MQTT/progress/material evidence를 지우면 안 된다. 최신 camera preview/evidence reference는 operator bed-clear evidence의 `camera_snapshot_path`로 재사용된다. `Mark Bed Clear`는 bed-clear verified 상태와 최신 camera reference를 갱신하되, 이전 `.autoeject.*` publish로 잠긴 remote path, artifact hashes, manifest, publish sequence/topic 같은 추적 필드를 지우면 안 된다.
- **Bambu bridge 연계**: 3DP GUI의 `/api/printer/spc-readiness`는 Specimen Making handoff용 집계 상태를 제공한다. 이 API는 현재 active printer profile이 Bambu일 때 Bambu live `prepare`, start gate, device screen, native G-code autoejection gate, bed-clear gate를 합쳐 `ready_for_live_print`, `autonomous_cycle_ready`, section별 blocker를 반환하지만 MQTT publish/start는 수행하지 않는다. SPC 응답에 포함된 `device_screen`은 frontend의 상단 Bambu Device Screen도 같이 갱신해야 하며, 이전 virtual/test evidence를 그대로 남기면 안 된다. Bambu autoejection은 `/api/printer/autoejection-config`가 저장한 local `memory/bambu_autoejection.json` overlay를 통해서만 configured로 바뀐다.
- **Bambu Device 화면 계약**: `/api/printer/status?mode=live`의 `device_screen`은 raw MQTT JSON을 그대로 노출하지 않고 사용자 화면용 `progress_panel`, `camera_panel`, `control_panel`, `material_panel`, `evidence_cards`를 생성한다. 이 값들은 `normalize_bambu_report()`가 받은 실제 MQTT report, FTPS/upload probe, start-command draft, connection gate에서 파생되며 GUI가 임의 progress/camera/material 상태를 만들지 않는다. 카메라는 MQTT와 별도 plane이다. 반복 GUI polling은 짧은 in-process MQTT snapshot cache를 사용해 매 poll마다 새 MQTT client와 `pushall` request를 만들지 않는다. 반대로 `/api/printer/start-publish` 이후의 post-publish observation은 `force_refresh`로 cache를 우회해 MQTT ack와 실제 `RUNNING`/`PRINTING` 상태를 분리 검증한다. `/api/printer/video-status`는 저장된 Bambu host/access code로 LAN video port를 probe하고, `ffmpeg`가 있으면 `/api/printer/video-stream.mjpeg` 브라우저용 MJPEG proxy를 제공한다. access code 원문은 API 응답/GUI log에 노출하지 않는다.
- **Bambu autoejection parameter 계약**: Native provider `bambu_gcode_patch`는 external provider handoff가 아니라 deterministic G-code patcher다. 사용자 조정값은 push direction, Z push offset, push lane offset, push speed, full-bed sweep enable, sweep Z, sweep speed로 표현한다. P1/P1S/X1/X1C 계열은 X-axis multi-lane push, A1/A1 Mini 계열은 별도 Y-axis bed-slinger/wiggle generator를 사용해야 하며 서로 재사용하지 않는다. 현재 CoreXY tail generator는 A1/A1 Mini profile을 `BAMBU_AUTOEJECTION_MODEL_FAMILY_UNSUPPORTED`로 차단해 잘못된 motion artifact를 만들지 않는다.
- **Bambu validation/test artifact 계약**: `Validate G-code Preview`와 left/center/right validation은 publish/start와 분리된 비파괴 검증이다. 이 validation-only 경로는 would-be tail, object bounds, candidate hash, blocker evidence만 반환하고 `.autoeject.*` artifact, sidecar manifest, run workspace manifest를 쓰지 않는다. `Generate Ejection Test Artifact`, `Generate Sweep Test Artifact`, `Generate Patched Artifact`는 로컬 파일을 생성하지만 source artifact를 덮어쓰지 않고 `will_publish=false` / `start_enabled=false`를 유지한다. 생성 artifact는 sidecar `.manifest.json`을 만들고, run context가 있으면 `runs/<run_id>/workspace/printer/bambu_autoejection_manifest.json`도 갱신한다. `.gcode.3mf` patch는 내부 plate G-code와 `Metadata/plate_#.gcode.md5` hash sidecar 정합성을 유지한다. Tail comment는 schema marker, source/patched hash reference, source plate path, plate id, loop index, object bounds/height, material/bed placeholder, cooldown, sweep, purge/parking strategy, door/front assumption, validation reference를 기록한다. Validator는 single schema marker, safe motion, no unexpected homing, object bounds, residual skirt/brim/raft, and cooldown wait evidence(`M190 R/S...` or explicit wait policy)를 확인한다. 실제 physical motion은 `/api/printer/start-publish` live gate를 통과한 경우에만 허용된다.
- **Bambu physical proof/audit 계약**: `/api/printer/bambu-autoejection-proof-template`은 fail-closed physical validation JSON을 만든다. `/api/printer/bambu-autoejection-completion-audit`은 지정 path 또는 latest package를 읽어 center ejection, disposable live ejection, left/right lane, bed-clear, next-job gate, camera files, patch manifest를 검증한다. 두 route는 non-actuating audit helper이며 MQTT publish, upload, camera capture, axis motion을 실행하지 않는다. Active printer profile이 Bambu가 아니면 proof template 생성도 audit도 `NOT_APPLICABLE`로 차단하고, proof file을 쓰지 않는다. Completion audit이 `complete_evidence_verified`를 반환하기 전까지 Live GUI와 tutorial은 Bambu native autoejection을 physical success로 표시하면 안 된다.
- **SPC 화면 계약**: `/api/printer/spc-readiness`는 raw gate payload만 반환하지 않는다. 사용자가 바로 판단할 수 있도록 `operator_summary`, `readiness_levels`, `next_actions`, `evidence`, `sections`를 함께 반환한다. `readiness_levels`는 connection, transfer path, owner-managed publish default, publish command, autoejection을 분리해 보여주며, `next_actions`는 실제 blocker/operator action/autoejection blocker에서 파생된다. GUI가 임의 상태를 만들지 않는다.
- **Bambu Connection Confirmation 계약**: 3DP GUI의 `Connection Confirmation` board는 저장된 Bambu connection과 최신 status/SPC evidence를 합쳐 LAN-only 확인, Developer Mode 확인, sliced-artifact transfer, HTTP artifact route 상태를 보여준다. 표시 코드는 `BAMBU_LAN_MODE_NOT_CONFIRMED`, `BAMBU_DEVELOPER_MODE_NOT_CONFIRMED`, `BAMBU_FTPS_WRITE_FAILED`, `BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED`, `BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE`에서 파생되며, checkbox/form 값만으로 upload-ready를 만들면 안 된다.
- **Bambu transfer 계약**: FTPS login/list 성공은 upload-ready가 아니다. live `prepare`는 root marker write/delete 실패 후 `cache`, `sdcard`, `Metadata`, `data/Metadata` 후보를 CWD+basename 방식으로 probe한다. 후보가 모두 실패하면 transfer는 `read_only`로 남고 `BAMBU_FTPS_WRITE_FAILED` / `BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED`가 blocker가 된다. `/api/printer/http-artifact-route`가 생성한 printer-reachable `http://`/`https://` URL 중 `server_fetch_probe.ok=true`와 sha256 match가 확인된 URL만 HTTP artifact transfer로 인정한다. 이때 ATR 서버는 LAN에서 접근 가능한 인터페이스(`server.host=0.0.0.0` 또는 명시 LAN IP)에 떠 있어야 하며, Bambu에 전달되는 artifact URL은 `localhost`가 아니라 ATR 서버 LAN IP를 사용해야 한다. 일반 remote path(`cache/*.gcode.3mf`)는 HTTP route가 아니며 FTPS 검증을 우회할 수 없다.
- **Bambu start 연계**: `/api/printer/start-gate`는 검증 전용이고 publish하지 않는다. `/api/printer/start-publish`만 실제 MQTT `project_file` command를 보낼 수 있으며, draft validity, live preprint gate, device `can_start_print`, operator confirmation, Guardian approval, `dry_run=false`가 모두 만족될 때만 `BambuMqttReportClient.publish_project_file_command()`를 호출한다. 3DP GUI에서는 operator/Guardian/dry-run 수동 controls를 제거했고, workstation owner/operator가 관리하는 기본 동작으로 `operator_confirmed=true`, `guardian_approved=true`, `dry_run=false`를 보낸다. `.autoeject.*` artifact의 front path/door, ramp/bin, toolhead cover, release surface, supervised first ejection 항목도 수동 checkbox blocker가 아니라 `operator_managed=true` evidence로 기록한다. `project_file` draft는 `.gcode.3mf` artifact에만 유효하며, plain `.gcode`나 `plate_id < 1`은 `BAMBU_PROJECT_FILE_PARAM_MISMATCH`로 차단된다. Status snapshot timeout과 publish timeout은 분리한다. Status는 짧게 유지할 수 있지만 publish timeout은 model 설정값 `publish_timeout_sec`를 사용하며 기본 180초, 최소 60초로 둔다. Publish 이후에는 `post_publish_observation`, `post_publish_status`, `post_publish_failure_code`로 fresh `printer.prepare` 결과를 다시 붙여 `gcode_state`, progress, subtask, safe-state evidence를 MQTT ack와 분리해 남긴다. `.autoeject.*` artifact는 publish ack가 성공하는 즉시 bed-clear required로 잠그며, 가능한 경우 `remote_path`, `subtask_name`, source/patched artifact path, source/patched sha256, sidecar manifest path, MQTT publish sequence/topic, post-publish status, camera snapshot reference를 `memory/bambu_bed_clear_evidence.json`에 같이 남긴다. `IDLE`/not-started observation이면 `published=true`라도 `ok=false`와 `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED`를 반환한다. HTTP artifact route가 검증되면 `device_screen.actions.can_start_print=true`와 `technical_ready_for_start=true`가 될 수 있지만, 이는 기술 gate가 열린 상태일 뿐이며 backend start/publish observation은 계속 확인한다.
- **Live GUI Specimen report 계약**: `SpecimenMakingAgent`는 `printer.prepare` 결과의 Bambu/SPC evidence를 `fabrication_report.printer_runtime`과 `specimen_agent_report.spc_readiness`에 보존한다. `MainController`의 Live GUI compact 단계도 `selected_printer`, `device_screen`, `preprint_gate`, `readiness_levels`, `operator_actions`, `autoejection`을 버리면 안 된다. Frontend는 이 값을 `Printer Bridge / SPC Readiness`로 표시하고, active profile이 Prusa일 때만 PrusaLink-specific transport/storage 행을 보조 정보로 보여준다.

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
- **핵심 툴**: `cae.run_static_analysis`, `cae.health`, `cae.run_static_analysis`
- **주요 결과**: `analysis`, `bo_observation`, `bo_handoff`, `experiment_evaluation`, `knowledge_payload`
- **주요 아티팩트**: `canonical_curve.csv`, `quality_report.json`, `metrics.json`, `fem_result.json`, `fem_agentic_loop.json`, `fem_utm_comparison.json`, `experiment_evaluation.json`, `bo_handoff.json`
- **CAE loop**: `analysis_fem_planning` LLM이 tutorial-style FEM 계획을 만들고, Agent가 sanitization 후 `cae.health`/`cae.run_static_analysis`를 반복 호출한다. 실제 solve는 bridge의 `runtime_solver_enabled=true`일 때 `device_bridges/cae_bridge.py`가 conda/docker CalculiX에서 수행한다. 기본 TEST loop는 빠른 deterministic bridge를 쓴다.
- **주의**: UTM은 `utm_high` 실측값이고 CAE/CalculiX는 `fem_low` simulation evidence다. FEM 예측을 실측 BO observation처럼 넣지 않는다. LLM이 임의 solver 코드를 실행하지 않는다.

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
