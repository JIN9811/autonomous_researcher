---
doc_type: index
subtype: index
status: active
authority: navigation
audience:
  - user
  - operator
  - developer
  - maintainer
scope:
  - repository_documentation
summary: Audience-, type-, and domain-oriented index for ATR documentation.
related_docs:
  - README.md
  - docs/paper/README.md
  - docs/standards/documentation_standard.md
  - docs/standards/paper_documentation_standard.md
  - docs/templates/document_types.md
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/device_bridges/README.md
  - docs/device_bridges/bridge_api_connection_matrix.md
  - docs/oldversion/README.md
  - docs/runtime/current_code_snapshot.md
  - docs/runtime/runtime_ide.md
supersedes: []
---

# Documentation Index

## Summary

이 문서는 논문 검토자, 협업자, 운영자, 개발자가 읽는 설명용 문서의
진입점입니다. 논문 독자는 `docs/paper/`를 먼저 읽고, 구현·운영 독자는 현재
Reference와 도메인 Guide로 내려갑니다. 시스템 지시, Codex 실행 프롬프트,
패키지 원본 지침은 `docs/system/`과 각 `docs/ATR_*_Package/`에 분리되어
있습니다.

## Scope

이 인덱스는 사용자·운영자·개발자가 읽는 문서, 문서 작성 규칙, 현재 구현
Reference, 절차 Guide, 목표 Design, 실행 Plan, 조사·감사 Evidence를 안내합니다.
`docs/document_manifest.yaml`에 아직 포함되지 않은 기존 문서는 그대로
노출하되 1차 거버넌스 이관 완료 문서로 간주하지 않습니다. manifest 밖에
있거나 inbound link가 없다는 사실만으로 미사용 문서로 판정하지 않습니다.

## Evidence Basis

- 문서 유형과 권한: [standards/documentation_standard.md](standards/documentation_standard.md)
- 이관 완료 집합: [document_manifest.yaml](document_manifest.yaml)
- 현재 구현 수치: [runtime/current_code_snapshot.md](runtime/current_code_snapshot.md)
- 실행 코드 기준: `app/`, `graphs/`, `web/`, `device_bridges/`, `knowledge/`

## 1. Audience Paths

| 목적 | 문서 |
|---|---|
| 논문 전체 논리와 증거 상태 | [paper/README.md](paper/README.md) |
| 논문 작성·검토 규칙 | [standards/paper_documentation_standard.md](standards/paper_documentation_standard.md) |
| 주장-증거 추적성 | [paper/09_claim_evidence_traceability.md](paper/09_claim_evidence_traceability.md), [paper/artifact_manifest.yaml](paper/artifact_manifest.yaml) |
| 전체 프로젝트 흐름 | [../README.ko.md](../README.ko.md), [../README.en.md](../README.en.md) |
| 초보자/상급자 통합 매뉴얼 | [tutorials/user_manual.ko.md](tutorials/user_manual.ko.md), [tutorials/user_manual.en.md](tutorials/user_manual.en.md) |
| 에이전트별 실제 역할·API·연결·안전 계약과 피겨 | [agents/README.md](agents/README.md) |
| 10개 에이전트 교차 비교 | [agents/agent_api_connection_matrix.md](agents/agent_api_connection_matrix.md) |
| 디바이스 브릿지별 실제 역할·API·프로토콜·효과·복구와 피겨 | [device_bridges/README.md](device_bridges/README.md) |
| 8개 디바이스 브릿지 교차 비교 | [device_bridges/bridge_api_connection_matrix.md](device_bridges/bridge_api_connection_matrix.md) |
| 실제 닫힌 루프, 페이지, 에이전트 | [runtime/closed_loop_and_pages_reference.md](runtime/closed_loop_and_pages_reference.md) |
| 현재 코드/API 스냅샷 | [runtime/current_code_snapshot.md](runtime/current_code_snapshot.md) |
| LangGraph 실행 계약 | [runtime/langgraph_runtime.md](runtime/langgraph_runtime.md) |
| Runtime IDE 편집·검증·활성화·실행·관측·복구 | [runtime/runtime_ide.md](runtime/runtime_ide.md) |
| Guardian safety/alarm 계약 | [runtime/guardian_graphwide_safety.md](runtime/guardian_graphwide_safety.md) |
| Experiment API 계약 | [runtime/autonomous_experiment_runtime.md](runtime/autonomous_experiment_runtime.md) |
| API key / OpenAI fallback | [runtime/api_keys.md](runtime/api_keys.md) |
| Live GUI 운영 | [gui/gui.md](gui/gui.md) |
| Device Workspaces / 3DP 사용법 | [tutorials/device_workspace_3dp_usage.ko.md](tutorials/device_workspace_3dp_usage.ko.md) |
| Device Workspaces / Vision Camera Bridge | [tutorials/device_workspace_vision_camera_bridge_usage.ko.md](tutorials/device_workspace_vision_camera_bridge_usage.ko.md) |
| BambuLab X2D bridge 구조 | [hardware/bambulab_x2d_device_bridge_runtime_guideline.md](hardware/bambulab_x2d_device_bridge_runtime_guideline.md) |
| 첫 실행 튜토리얼 | [tutorials/first_autonomous_run.ko.md](tutorials/first_autonomous_run.ko.md), [tutorials/first_autonomous_run.en.md](tutorials/first_autonomous_run.en.md) |
| Git/GitHub 운영 | [repository/github_version_control.md](repository/github_version_control.md) |
| 보관된 미사용·대체 문서 | [oldversion/README.md](oldversion/README.md) — 현재 구현 기준으로 사용 금지 |

## 1.1 Documents by Type

| 유형 | 현재 진입점 | 읽는 기준 |
|---|---|---|
| Index | [../README.md](../README.md), 이 문서 | 언어·대상·도메인별 탐색 |
| Standard | [standards/documentation_standard.md](standards/documentation_standard.md), [standards/paper_documentation_standard.md](standards/paper_documentation_standard.md) | 문서 분류·권한·메타데이터·검증 및 논문 주장·증거·도표·공개 규칙 |
| Reference | [agents/README.md](agents/README.md), [device_bridges/README.md](device_bridges/README.md), [device_bridges/bridge_api_connection_matrix.md](device_bridges/bridge_api_connection_matrix.md), [runtime/current_code_snapshot.md](runtime/current_code_snapshot.md), [runtime/runtime_ide.md](runtime/runtime_ide.md), [runtime/langgraph_runtime.md](runtime/langgraph_runtime.md), [runtime/closed_loop_and_pages_reference.md](runtime/closed_loop_and_pages_reference.md) | 현재 코드가 실제로 제공하는 역할·계약·동작과 편집 가능한 Graphviz/SVG 피겨 |
| Guide | [knowledge/knowledge_graph_operations.ko.md](knowledge/knowledge_graph_operations.ko.md), `tutorials/` | 사용자·운영자 절차와 성공/복구 기준 |
| Design | [superpowers/specs/2026-08-08-documentation-governance-design.md](superpowers/specs/2026-08-08-documentation-governance-design.md) | 승인 또는 제안된 목표 결정; 현재 구현 사실이 아님 |
| Plan | `superpowers/plans/` | Design을 실현하는 작업 순서 |
| Evidence | [paper/06_evaluation_and_results.md](paper/06_evaluation_and_results.md), [paper/09_claim_evidence_traceability.md](paper/09_claim_evidence_traceability.md), 조사·감사·시험 보고서 | 기록된 날짜·환경·방법에 한정된 근거 |
| Archived | [oldversion/README.md](oldversion/README.md) | 현재 소비자가 없고 대체물이 명시된 역사 자료; 정상 읽기 경로에서 제외 |

새 문서를 만들 때는 [templates/document_types.md](templates/document_types.md)의
해당 유형 템플릿을 사용합니다.

## 1.2 Authority and Conflict Resolution

문서가 서로 다르게 보이면 아래 순서로 판단합니다.

1. `app/main.py`, `graphs/configs/*.yaml`, `graphs/modules/*/module.yaml`,
   `device_bridges/*`, `web/templates/*`, `web/static/*`의 실제 코드
2. [runtime/current_code_snapshot.md](runtime/current_code_snapshot.md)
3. `docs/runtime`, `docs/gui`, `docs/hardware`, `docs/tutorials`의 운영 문서
4. `개선안/*`과 `docs/ATR_*_Package/*`의 목표 설계/패키지 지침

`runtime/current_code_snapshot.md`는 현재 코드가 실제로 노출하는 page
route, API 그룹, agent manifest, module lifecycle, Module Management typed
editor 범위, bridge registry, printer fleet, model/API-key 상태를 요약하는 문서입니다. 개선안 문서보다
실제 코드 설명에 가깝고, 운영자용 문서를 갱신할 때 먼저 맞춰야 합니다.
route 수치와 그룹 분류는 decorator grep가 아니라 `.venv/bin/python`으로
FastAPI app을 import한 뒤 `APIRoute` 객체를 세는 기준입니다.

## 2. Documents by Domain: 실제 런타임 구조 요약

기본 그래프는 `graphs/configs/atr_closed_loop.yaml`이며, 서버 route는 `app/main.py`에 정의되어 있습니다.

```text
Main GUI -> Live GUI -> /api/run/start -> LangGraphRunLoop
        -> design -> specimen -> vision -> manipulation -> equipment
        -> analysis -> knowledge -> bo -> guardian
        -> continue: design / stop: complete / error: error
```

Live GUI에서 보이는 상태는 다음 소스에서 옵니다.

- `/api/planning/session`: 채팅/오케스트레이션 세션
- `/api/planning/messages`: file-backed Live GUI transcript 페이지 로딩
- `/api/runtime/state`: 현재 runtime 상태
- `/api/runtime/agent-manifests`: graph/module/`ui.yaml` 기반 Live GUI agent manifest
- `/api/bridges`: graph metadata 기반 normalized device bridge registry
- `/api/events/recent`: 최근 이벤트
- `/api/events/stream`: SSE stream
- `/api/runs/{run_id}/events`: run별 이벤트
- `/api/runs/{run_id}/artifacts`: run별 아티팩트

Live GUI agent 목록은 `web/static/planning.js`의 하드코딩 목록이 아니라 `/api/runtime/agent-manifests`가 우선입니다. 이 manifest payload는 `agents[]`를 포함하며, `graphs/configs/atr_closed_loop.yaml`, `graphs/modules/*/module.yaml`, 선택적 `graphs/modules/*/ui.yaml`을 병합합니다. 현재 descriptor card/report section 예시는 `design`, `equipment`, `guardian` 모듈에 있으며, `ui.yaml`은 표시 전용이라 handler, tool allowlist, graph transition, live device 권한을 바꾸지 않습니다. 현재 generic renderer는 selector 기반 card/report section, `mini_bar_chart`, `scatter_plot`, `line_chart`, `table`, `heatmap`, `compound_chart`/`chart_grid`, 내부 GUI navigation action, read-only GET API action, workspace handoff action을 처리합니다. `GET/PUT /api/modules/{module_id}/ui`는 chart/action descriptor를 표시용 계약으로 정규화하고, safe internal navigation은 `navigation_only`, 검증된 read-only GET `/api/*`는 `read_only_api`, 검증된 POST/confirmation/non-read-only 내부 API는 `workspace_handoff`, unsafe/unsupported action은 `blocked`로 표시합니다. 물리 장비 action은 workspace/API/Guardian gate 경로에 남아 있습니다. `ui.renderer` 기반 custom renderer manifest id는 현재 allowlisted `presentation_only` profile로만 동작합니다. 즉 `/api/runtime/agent-manifests`가 normalized `renderer`를 내려주고 Live GUI가 그 metadata로 기존 built-in report/dashboard renderer를 선택하지만, 임의 외부 renderer/plugin 코드를 로드하지는 않습니다.

현재 구현 기준의 route/API/manifest 상태는 [runtime/current_code_snapshot.md](runtime/current_code_snapshot.md)에 따로 고정합니다. 문서를 갱신할 때는 목표 설계 문서보다 이 스냅샷과 `app/main.py`의 실제 route를 우선 확인합니다.

Live GUI transcript는 `runs/<active_run_id>/live_planning_transcript.jsonl`에
저장되고 `/api/planning/messages`로 페이지 단위 조회됩니다. 따라서 화면
새로고침/재접속 상태 설명은 browser-local memory가 아니라 이 file-backed
session 계약을 기준으로 써야 합니다.

Module Management는 `Load/Unload`와 runtime activation을 분리합니다.
`Load/Unload`는 management workspace selection일 뿐이고, 실제 실행은
graph attach, validate, dry-run, save/version, graph live gate를 통과해야
합니다. Module Designer 생성물은 `/api/modules/{module_id}/register-generated`
승인 후에도 같은 graph validation 경로를 거칩니다.

Custom stage는 현재 `Stage._missing_()` pseudo-member와 graph/module
validation을 통해 최소 실행 경로가 열려 있습니다. Custom stage가
operator-facing follow-up 문구를 직접 제어하려면 payload 또는
`module_runtime`에 `supervisor_policy` descriptor를 넣어야 합니다. 현재
Module Management typed form은 handler/LLM/tool/prompt/safety/step 편집용이며,
`supervisor_policy`의 required outputs, opinion/recommendation template,
response-required status, concern rules, options도 typed editor에서 편집할 수
있습니다. graph attach/save lifecycle 통합은 아직 후속 범위입니다.

LLM backend와 API key 상태는 Main GUI `Current Models` 영역과 아래 API가 같은 상태를 봅니다.

- `/api/runtime/models`: vLLM/NemoClaw managed model load state
- `/api/runtime/models/load`, `/api/runtime/models/unload`: 모델별 load/unload
- `/api/runtime/api-key`: 저장된 OpenAI key 등록/활성 상태. key 원문은 반환하지 않음
- `/api/runtime/api-key/load`, `/api/runtime/api-key/unload`: 저장된 key를 first inference route로 enable/disable

3DP/Bambu 경로는 `SpecimenMakingAgent -> printer.prepare -> PrinterDeviceBridgeManager -> Bambu native G-code patch/start gate` 순서로 연결됩니다. 세부 구조는 [hardware/bambulab_x2d_device_bridge_runtime_guideline.md](hardware/bambulab_x2d_device_bridge_runtime_guideline.md)에 정리되어 있습니다. BambuLab X2D가 기본 active provider이며, Prusa MK4S는 fallback이 아니라 operator가 선택하는 별도 provider입니다. Bambu의 MQTT publish ack는 실제 출력 시작과 분리해서 기록하며, fresh post-publish observation이 RUNNING/PREPARING 계열 상태로 넘어가지 않으면 `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED`로 차단합니다. Native autoejection은 `bambu_gcode_patch` provider로 sliced `.gcode.3mf` 내부 plate G-code에 deterministic tail을 삽입하고, source/patched hash, plate id, loop index, material/bed placeholder, cooldown, sweep, purge/parking strategy, validation evidence를 manifest와 tail comment에 남긴 뒤에만 start gate로 넘어갑니다. Bambu bridge evidence는 `artifact`, `validation`, `transport`, `runtime`, `bed-clear` 5개 plane으로 나뉘며, GUI/Live report/API는 이 구분을 유지해야 합니다. `.autoeject.*` publish가 성공하면 bed-clear evidence는 remote path, subtask, source/patched artifact path와 hash, manifest, publish sequence/topic, post-publish status, camera snapshot reference를 같이 잠그며, 다음 job은 이 evidence가 해제되기 전까지 차단됩니다. 물리 완료 선언 시에도 physical start precheck는 saved prestart snapshot에서 `ready_to_publish_not_started`, `published=false`, `will_publish=false`가 확인되어야 합니다. center standalone ejection, left/right lane ejection, disposable live ejection은 각각 saved `printer.bambu.start_publish` 응답 snapshot을 가져야 하며, snapshot의 `ready_to_publish=true`, `start_enabled=true`, blocker 없음, remote path, publish sequence/topic, post-publish running status가 proof 본문과 일치해야 합니다. disposable live ejection은 추가로 local source/patched artifact file의 sha256이 proof hash와 맞아야 합니다. left/right lane은 marker artifact와 saved validation snapshot도 모두 있어야 하고, post-ejection bed-clear는 `operator`, `camera`, `vision` 중 하나의 검증 방식과 live ejection의 source/patched sha256 매칭을 요구하고, next-job gate는 saved start-gate snapshot에서 `ready_to_publish=true`, `start_enabled=true`, blocker 없음, `BAMBU_POST_EJECT_BED_NOT_CLEAR` 없음이 확인되어야 합니다. 현재 3DP GUI는 별도 수동 approval/checklist checkbox를 노출하지 않고 `operator_confirmed=true`, `guardian_approved=true`, `dry_run=false`, `operator_managed=true`를 owner-managed publish 기본값으로 보냅니다. 실제 motion은 `.autoeject.*` artifact 검증, camera/bed-clear evidence, printer safe-state, backend start gate, post-publish observation을 통과한 뒤에만 이어집니다. 물리 완료 선언은 별도 completion audit으로만 가능하며, `/api/printer/bambu-autoejection-proof-template`와 `/api/printer/bambu-autoejection-completion-audit` 또는 `scripts/audit_bambu_autoejection_completion.py`가 file-backed proof package를 검증해야 합니다.

Live GUI의 Specimen Making report는 위 3DP evidence를 `Live Job Monitor` 중심 card layout으로 읽습니다. 중앙 focus card는 `build_queue`, `printer_status`, `estimated_print_time`, `layer_preview`, `handoff_status`에서 job progress/layer/queue/path를 표시하고, 주변 cards는 build intent, printer telemetry, readiness, slicing, thermal/material, transfer, layer preview, camera evidence, post-print automation, G-code validation, handoff/artifacts를 분리합니다. Main GUI 3DP workspace card는 fixed brand title 대신 selected printer profile/bridge telemetry를 표시합니다.

3DP GUI에서 실행한 standalone autoejection test도 Live GUI에 반영됩니다. 백엔드는 `printer.autoejection_test` 결과를 `printer_ai` 메시지와 runtime event로 동시에 기록하고, Live GUI는 active run event와 recent workspace event를 합쳐 표시합니다. `start_immediately=false`는 검증 artifact만 만들고, `start_immediately=true`와 live gate 통과 시에만 standalone `.autoeject.gcode.3mf`를 일반 Bambu MQTT `project_file` 경로로 publish합니다.

제어 판넬 상태는 Live GUI에서 주기 갱신됩니다. Live GUI가 열려 있으면 `GET /api/printer/status?mode=live&emit=1` polling이 실제 device screen/progress/material/connection 상태를 읽고, Live GUI 3D Printer card에는 `workspace_monitor_snapshot.monitor_snapshot`으로 표시됩니다. 이 heartbeat는 transcript와 artifact를 만들지 않습니다.

주의: `/api/bridges`는 현재 graph metadata 기반 bridge registry를 normalized contract로 반환합니다. 반환값에는 workspace, health/preflight endpoint, `actions[]`에 들어간 standard/custom action descriptor, evidence contract, health snapshot이 포함되며, 같은 shape가 `/api/runtime/state.runtime_ide_contract.device_bridges`에도 들어갑니다. Bambu Lab X2D는 이 registry가 아니라 `/api/printer/fleet`와 `/api/printer/*` provider 계층에서 기본 active profile로 관리됩니다. 따라서 Bambu가 `/api/bridges` 목록에 없다는 사실은 Bambu printer bridge가 비활성이라는 뜻은 아닙니다.

시스템 설명 문서에서 3DP bridge를 설명할 때는 다음 세 계층을 섞지 않습니다.

- `개선안/14_bambulab_gcode_autoejection_runtime_plan.md`: Reddit/GitHub/YouTube/Bambu community 사례조사와 구현 기준을 고정하는 설계 문서
- `docs/hardware/bambulab_x2d_device_bridge_runtime_guideline.md`: 운영자/협업자에게 공개할 BambuLab X2D bridge runtime 설명
- `docs/gui`, `docs/runtime`, `docs/tutorials`: 실제 화면, API, closed-loop, 사용자 절차 설명

즉, 외부 사례의 G-code나 UI를 그대로 복사하지 않고, 검증된 원칙만 ATR의 provider/bridge/evidence 계약으로 재해석합니다.

UTM ROS Vision Runtime은 현재 Windows/PyAutoGUI UTM 제어 증거를 대체하지 않고, 장비의 물리 상태를 `/compression_tester/summary`와 카메라/marker evidence로 보강하는 별도 runtime provider입니다. 구현/운영 기준은 [hardware/utm_ros_vision_runtime_bridge.md](hardware/utm_ros_vision_runtime_bridge.md), [../개선안/16_utm_ros_runtime_bridge_live_gui_plan.md](../개선안/16_utm_ros_runtime_bridge_live_gui_plan.md), [../개선안/17_vision_agent_camera_device_bridge_live_gui_plan.md](../개선안/17_vision_agent_camera_device_bridge_live_gui_plan.md)에 고정합니다. 이 경로는 `vision.equipment_cross_check` tool contract, Device Workspace Loading/Unloading, Camera mapping/frame probe/calibration page, test-mode virtual bridge fallback, fallback message/event trace, `/home/jin/external_repos/UTM` launch/script/docs 기준 expected graph, 실제 ROS graph 기반 RQT-like node-flow panel, Live GUI UTM runtime card, 브라우저 조작/캡쳐 기반 full-path 검증을 함께 다루며, 기존 UTM proof/completion audit 문서와 혼동하지 않습니다. 현재 안정 카메라 프로파일은 `640x480 @ 15fps`, `yuyv2rgb`, runtime start 전 `exposure_dynamic_framerate=0` 고정입니다. ATR snapshot/MJPEG, green-dot image input/output, YOLO image subscribers는 Best Effort + Keep Last depth 1로 맞추며, raw `/camera/image_raw`가 느리면 `usb_cam` publisher 교체/패치가 다음 병목입니다.

시스템 설명 문서를 갱신할 때는 코드 파일만 나열하지 않고 runtime path, GUI route, device bridge gate, agent report evidence가 어떻게 이어지는지 같이 적어야 합니다. 특히 Bambu/3DP 변경은 `docs/runtime/closed_loop_and_pages_reference.md`, `docs/gui/gui.md`, `docs/tutorials/device_workspace_3dp_usage.ko.md`, `docs/tutorials/user_manual.ko.md`, `docs/tutorials/user_manual.en.md`가 같은 의미로 맞아야 합니다.

## 3. 페이지별 문서 맵

| 페이지 | URL | 코드 | 설명 문서 |
|---|---|---|---|
| Main GUI | `/` | `web/templates/index.html`, `web/static/app.js` | [gui/gui.md](gui/gui.md) |
| Live GUI | `/live`, `/planning` | `web/templates/planning.html`, `web/static/planning.js` | [gui/gui.md](gui/gui.md), [runtime/closed_loop_and_pages_reference.md](runtime/closed_loop_and_pages_reference.md) |
| Runtime IDE | `/ide` | `web/templates/runtime_ide.html`, `web/static/runtime_ide.js` | [runtime/runtime_ide.md](runtime/runtime_ide.md), [runtime/langgraph_runtime.md](runtime/langgraph_runtime.md) |
| Module Management | `/module-management` | `web/templates/module_management.html`, `web/static/module_management.js` | [runtime/langgraph_runtime.md](runtime/langgraph_runtime.md), [runtime/agent_program_baseline.md](runtime/agent_program_baseline.md) |
| Knowledge Workspace | `/knowledge` | `web/templates/knowledge.html`, `web/static/knowledge.js`, `web/static/knowledge.css` | [knowledge/knowledge_graph_operations.ko.md](knowledge/knowledge_graph_operations.ko.md), [runtime/current_code_snapshot.md](runtime/current_code_snapshot.md) |
| 3DP Workspace | `/printer` | `web/templates/printer.html`, `web/static/printer.js`, `device_bridges/bambu_bridge.py`, `device_bridges/bambu_autoejection.py` | [gui/gui.md](gui/gui.md), [runtime/closed_loop_and_pages_reference.md](runtime/closed_loop_and_pages_reference.md), [hardware/bambulab_x2d_device_bridge_runtime_guideline.md](hardware/bambulab_x2d_device_bridge_runtime_guideline.md), [../개선안/13_bambulab_x2d_spc_device_bridge_research.md](../개선안/13_bambulab_x2d_spc_device_bridge_research.md), [../개선안/14_bambulab_gcode_autoejection_runtime_plan.md](../개선안/14_bambulab_gcode_autoejection_runtime_plan.md), [tutorials/device_workspace_3dp_usage.ko.md](tutorials/device_workspace_3dp_usage.ko.md), [hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt](hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt) |
| Vision Camera Bridge | `/device-bridge/vision-utm` | `web/templates/vision_utm_device_bridge.html`, `web/static/vision_utm_device_bridge.js`, `device_bridges/utm_runtime_bridge.py` | [hardware/utm_ros_vision_runtime_bridge.md](hardware/utm_ros_vision_runtime_bridge.md), [tutorials/device_workspace_vision_camera_bridge_usage.ko.md](tutorials/device_workspace_vision_camera_bridge_usage.ko.md), [../개선안/17_vision_agent_camera_device_bridge_live_gui_plan.md](../개선안/17_vision_agent_camera_device_bridge_live_gui_plan.md) |
| LeRobot Workspace | `/lerobot` | `web/templates/lerobot.html`, `web/static/lerobot.js` | [hardware/lerobot_robotis_manipulation_runtime_guideline.md](hardware/lerobot_robotis_manipulation_runtime_guideline.md), [hardware/isaac_sim_robotis_omx_mirror_mode.md](hardware/isaac_sim_robotis_omx_mirror_mode.md), [runtime/lerobot_dataset_policy_naming.md](runtime/lerobot_dataset_policy_naming.md) |
| BO Workspace | `/bo` | `web/templates/bo.html`, `web/static/bo.js` | [agents/bo_agent_runtime_guideline.txt](agents/bo_agent_runtime_guideline.txt) - BO/MBO/LLM preference 설정, lightweight/BoTorch optional backend, reasoning audit, candidate ranking |
| CAE Workspace | `/cae` | `web/templates/cae.html`, `web/static/cae.js` | [agents/cae_analysis_runtime_guideline.txt](agents/cae_analysis_runtime_guideline.txt) |
| Windows Equipment | `/equipment/windows` | `web/templates/windows_equipment.html`, `web/static/windows_equipment.js` | [hardware/windows_pyautogui_equipment_agent_guideline.md](hardware/windows_pyautogui_equipment_agent_guideline.md) |
| Self-Evolution Lab | `/evolution-lab` | `web/templates/evolution_lab.html`, `web/static/evolution_lab.js` | [runtime/self_evolution.md](runtime/self_evolution.md), [agents/knowledge_agent_self_evolution_runtime_guideline.md](agents/knowledge_agent_self_evolution_runtime_guideline.md), [runtime/knowledge_graphify_graph_backend_plan.md](runtime/knowledge_graphify_graph_backend_plan.md) |

## 4. 에이전트별 문서 맵

기준 진입점은 [Agent Reference Index](agents/README.md)이며, API·서비스·장비·효과
경계를 한눈에 비교할 때는 [Agent API and Connection Matrix](agents/agent_api_connection_matrix.md)를
사용합니다. 아래 `Reference`가 현재 역할과 계약의 기준이고 `운용 상세`는 특정
장비·알고리즘·절차를 보충하는 기존 문서입니다.

| Agent | Runtime module | Reference | 운용 상세 |
|---|---|---|---|
| Orchestrator | `graphs/modules/orchestrator` | [Orchestrator](agents/orchestrator_agent.md) | [LangGraph runtime](runtime/langgraph_runtime.md), [Closed loop and pages](runtime/closed_loop_and_pages_reference.md) |
| Design | `graphs/modules/design` | [Design](agents/design_agent.md) | [기존 Design/Specimen guideline](agents/specimen_design_existing_runtime_guideline.txt) |
| Specimen Making | `graphs/modules/specimen` | [Specimen Making](agents/specimen_agent.md) | [BambuLab X2D bridge](hardware/bambulab_x2d_device_bridge_runtime_guideline.md), [기존 Prusa bridge guideline](hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt) |
| Vision | `graphs/modules/vision` | [Vision](agents/vision_agent.md) | [기존 pickup observation guideline](agents/vision_pickup_observation_runtime_guideline.txt), [UTM ROS Vision bridge](hardware/utm_ros_vision_runtime_bridge.md) |
| Manipulation | `graphs/modules/manipulation` | [Manipulation](agents/manipulation_agent.md) | [기존 Pi0.5 transfer guideline](agents/manipulation_pi05_transfer_runtime_guideline.txt), [LeRobot runtime](hardware/lerobot_robotis_manipulation_runtime_guideline.md) |
| Lab Equipment | `graphs/modules/equipment` | [Lab Equipment](agents/equipment_agent.md) | [Windows equipment guideline](hardware/windows_pyautogui_equipment_agent_guideline.md), [UTM completion audit](hardware/evidence/lab_equipment_utm_visual_control_completion_audit.md) |
| Analysis | `graphs/modules/analysis` | [Analysis](agents/analysis_agent.md) | [기존 UTM guideline](agents/analysis_utm_runtime_guideline.txt), [기존 CAE guideline](agents/cae_analysis_runtime_guideline.txt) |
| Knowledge | `graphs/modules/knowledge` | [Knowledge](agents/knowledge_agent.md) | [Self-evolution guideline](agents/knowledge_agent_self_evolution_runtime_guideline.md), [Knowledge operations](knowledge/knowledge_graph_operations.ko.md) |
| BO | `graphs/modules/bo` | [Bayesian Optimization](agents/bo_agent.md) | [기존 BO guideline](agents/bo_agent_runtime_guideline.txt) |
| Guardian | `graphs/modules/guardian` | [Guardian](agents/guardian_agent.md) | [Guardian graph-wide safety](runtime/guardian_graphwide_safety.md), [Agent program baseline](runtime/agent_program_baseline.md) |

## 4.1 디바이스 브릿지별 문서 맵

기준 진입점은 [Device Bridge Reference Index](device_bridges/README.md)이며,
API·프로토콜·효과·복구를 비교할 때는
[Bridge API and Connection Matrix](device_bridges/bridge_api_connection_matrix.md)를
사용합니다. `Reference`가 현재 인터페이스 기준이고 기존 `hardware` 문서는
설치·운영·검증 절차를 보충합니다.

| Boundary | Reference | 주요 구현/대상 | 운용 상세 |
|---|---|---|---|
| Printer Fleet | [Printer Fleet](device_bridges/printer_fleet_bridge.md) | provider selection and shared printer routing | [3DP usage](tutorials/device_workspace_3dp_usage.ko.md) |
| Bambu Lab X2D | [Bambu X2D](device_bridges/bambu_x2d_bridge.md) | Bambu Studio, MQTT, FTPS, video, printer | [Bambu runtime](hardware/bambulab_x2d_device_bridge_runtime_guideline.md) |
| Prusa MK4S | [Prusa MK4S](device_bridges/prusa_mk4s_bridge.md) | PrusaSlicer, PrusaLink, printer | [Prusa runtime](hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt) |
| LeRobot | [LeRobot](device_bridges/lerobot_bridge.md) | serial/camera/process/Isaac robot stack | [LeRobot runtime](hardware/lerobot_robotis_manipulation_runtime_guideline.md) |
| Windows PyAutoGUI | [Windows PyAutoGUI](device_bridges/windows_pyautogui_bridge.md) | token HTTP server, desktop app, instrument | [Equipment runtime](hardware/windows_pyautogui_equipment_agent_guideline.md) |
| UTM Vision | [UTM Vision](device_bridges/utm_vision_bridge.md) | ROS 2, camera, pose, UTM state | [UTM ROS Vision](hardware/utm_ros_vision_runtime_bridge.md) |
| CAE Computation | [CAE/CalculiX/PINN](device_bridges/cae_computation_bridges.md) | solver subprocess and model registry | [Analysis Reference](agents/analysis_agent.md) |
| Base and Simulators | [Base/Simulators](device_bridges/base_simulator_bridges.md) | in-process deterministic test substitutes | [Agent matrix](agents/agent_api_connection_matrix.md) |

## 5. 폴더별 책임

| 폴더 | 책임 |
|---|---|
| `app/` | FastAPI route, runtime API, controller 연결 |
| `web/` | HTML/CSS/JS 기반 GUI |
| `graphs/` | LangGraph YAML, compiler/validator, module registry |
| `graphs/modules/` | 각 stage agent의 실행 계약과 handler |
| `device_bridges/` | 프린터, 로봇, Windows, UTM 등 외부 장비 연결 |
| `experiments/` | objective/evaluate/benchmark/queue 공통 실험 API |
| `orchestrator/` | Live planning, handoff, 오케스트레이션 로직 |
| `backends/` | Ollama/vLLM/Nemoclaw LLM 연결 |
| `self_evolution/` | variant 생성, 검증, 승인, rollback |
| `memory/` | 로컬 설정, 장비 연결 정보, graph/module version memory, Knowledge JSONL memory |
| `runs/` | 실행별 로그와 아티팩트 |
| `artifacts/` | STL, G-code, CAE, UI audit 등 산출물 |
| `tests/` | pytest, integration, UI audit |
| `scripts/` | live 검증 runner와 운영 보조 스크립트. 예: `lab_equipment_live_utm_validation.py`, `audit_lab_equipment_utm_completion.py`, `audit_bambu_autoejection_completion.py` |
| `install/` | CLI 설치와 외부 프로그램 설치 보조 |
| `image/` | 발표/논문용 시스템 diagram prompt와 렌더 결과 |
| `user_files/` | 사용자가 넣는 데이터/작업 파일 |

## 6. 설명용 문서 폴더

- `docs/runtime/`: Runtime IDE, graph, loop, logging, test mode, self-evolution 설명
- `docs/gui/`: 현재 GUI 설명; `docs/gui/history/`는 구현 계획 이력
- `docs/agents/`: agent별 역할과 runtime guideline
- `docs/device_bridges/`: bridge/provider별 현재 역할, API, 프로토콜, 효과, 증거, 복구 Reference와 피겨
- `docs/hardware/`: 장비 브릿지와 실제 장비 연동; `research/`와 `evidence/`는 조사·검증 기록
- `docs/tutorials/`: 사용자 종합 매뉴얼과 첫 실행 튜토리얼
- `docs/repository/`: GitHub/버전관리 규칙
- `docs/process/`: Codex 작업 절차
- `docs/project/`: 프로젝트 기본 가이드
- `docs/strategy/`: 시스템 개선 전략
- `docs/knowledge/`: Knowledge Graph 운영 Guide
- `docs/standards/`: active 규범 문서
- `docs/templates/`: 문서 유형별 작성 틀
- `docs/superpowers/specs/`: Design 문서
- `docs/superpowers/plans/`: 실행 Plan 문서
- `docs/oldversion/`: 현재 소비자가 없고 대체물이 확인된 보관 자료와 색인

## 7. 시스템 지시 문서

일반 협업자는 보통 아래 파일을 직접 수정하지 않습니다. Codex/패키지 적용 기준으로 분리된 자료입니다.

- `docs/system/ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt`
- `docs/system/ATR_Live_GUI_and_LangGraph_Codex_Instructions.txt`
- `docs/system/ATR_Self_Evolution_Codex_Instructions.txt`
- `docs/system/codex_lerobot_robotis_gui_prompt.txt`
- `docs/ATR_Live_GUI_Graph_Package/`
- `docs/ATR_LangGraph_Runtime_IDE_Codex_Package/`
- `docs/ATR_Self_Evolution_Package/`

## 8. 문서 유지 규칙

- 분류, lifecycle, authority, metadata, 검증은
  [standards/documentation_standard.md](standards/documentation_standard.md)를 따릅니다.
- `docs/document_manifest.yaml` 밖의 기존 문서는 1차 이관 debt이며, active
  Reference나 Guide처럼 자동으로 간주하지 않습니다.
- 보관 여부는 [oldversion/README.md](oldversion/README.md)와 Standard의 archive
  admission rule로 판단하며, 나이·파일 형식·inbound link 수만으로 이동하지 않습니다.
- 코드와 문서가 다르면 우선 `runtime/current_code_snapshot.md`를 갱신한 뒤
  관련 문서를 따라 수정합니다.
- runtime loop나 API를 바꾸면 `runtime/closed_loop_and_pages_reference.md`를 같이 갱신합니다.
- Knowledge memory/evidence schema나 Evolution Lab prefill을 바꾸면 `agents/knowledge_agent_self_evolution_runtime_guideline.md`와 `runtime/self_evolution.md`를 같이 갱신합니다.
- GUI route/버튼/API가 바뀌면 `gui/gui.md`와 이 인덱스의 페이지 맵을 같이 갱신합니다.
- agent module 계약이 바뀌면 해당 `docs/agents/*` 또는 `docs/hardware/*`를 같이 갱신합니다.
- 설치 의존성이 바뀌면 루트 [REQUIREMENTS.md](../REQUIREMENTS.md)를 갱신합니다.

## Migration Status

1차 이관 범위는 root Index, 이 인덱스, 문서 Standard/템플릿, 세 개의 핵심
runtime Reference, Knowledge operations Guide입니다. 그 외 Markdown과 기존
`.txt` guideline은 경로를 유지한 채 도메인별 후속 분류 대상으로 남습니다.
2026-08-09 위치 정리에서는 명백한 research/history/evidence 문서만 도메인
하위로 이동했고, 대체가 확인된 미사용 이미지 패키지 하나만 보관했습니다.

## Limitations and Known Gaps

- 이 인덱스에는 아직 manifest 밖의 legacy 문서 링크가 포함됩니다.
- 문서 유형은 파일 경로가 아니라 front matter가 기준이므로, 같은 폴더 안에
  이관 완료 문서와 미분류 문서가 함께 있을 수 있습니다.
- 생성 API 문서와 시스템 지시 패키지는 일반 설명 문서와 별도 lifecycle을
  유지합니다.

## Index Verification

2026-08-08에 커밋 `09bbe32`의 route/page 구조와 현재 repository path를
대조했습니다. 이관 완료 문서는 다음 명령으로 검사합니다.

```bash
.venv/bin/python scripts/validate_documentation.py
```

## Related Documents

- [Documentation Standard](standards/documentation_standard.md)
- [Document Type Templates](templates/document_types.md)
- [Current Code Snapshot](runtime/current_code_snapshot.md)
- [Documentation Governance Design](superpowers/specs/2026-08-08-documentation-governance-design.md)
