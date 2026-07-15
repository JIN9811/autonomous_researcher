# BambuLab G-code Autoejection Runtime Plan

작성 기준: 2026-06-14
보강 기준: 2026-06-16, Reddit/GitHub/YouTube/Community 사례 조사 반영
대상: `SpecimenMakingAgent`, `printer.prepare`, 3DP Device Workspace, Bambu device bridge
상태: 개선안 문서. 이 문서는 구현 완료 선언이 아니라 다음 구현 기준을 고정한다.

---

## 1. 목표

BambuLab 계열 프린터도 Prusa처럼 프린터 자체 G-code 기반 자동 배출을 primary path로 사용한다.

기존 Bambu autoejection provider-handoff 방식은 Manipulation Agent 또는 외부 routine으로 넘기는 구조였지만, 목표 구조에서는 다음처럼 계층을 분리한다.

1. `SpecimenMakingAgent`는 출력 요구사항과 autoejection 옵션만 만든다.
2. `Device Bridge`가 active printer provider를 선택한다.
3. 기본 provider는 `BambuLab`이다.
4. `Prusa`는 fallback이 아니라 설정 가능한 다른 provider이다.
5. Bambu autoejection은 Bambu 전용 G-code patch/validation 경로를 사용한다.
6. Manipulation Agent는 primary ejection이 아니라 recovery 또는 downstream transfer 계층으로 남긴다.

이번 보강의 결론:

- Bambu autoejection은 단순 MQTT command가 아니라 `sliced artifact -> deterministic G-code patch -> validation -> transfer/start -> bed-clear gate`로 다뤄야 한다.
- 여러 사례에서 공통적으로 `cooldown`, `push-off`, `next print` 순서를 쓰지만, 실제 무인 루프는 bed-clear 검증 없이는 위험하다.
- Bambu에서는 plain G-code보다 `.gcode.3mf` 또는 plate-sliced 3MF가 더 안전한 주 경로다.

2026-06-16 standalone physical validation update:

- 실제 장비: BambuLab X2D, host `192.168.50.4`, serial `20P6BJ642001425`
- 검증된 standalone route: `/api/printer/autoejection-test -> _bambu_direct_standalone_gcode -> MQTT command=gcode_line -> device/20P6BJ642001425/request`
- 검증 위치: center, left, right
- evidence summary: `runs/manual_bambu_validation/direct_gcode_line_validation_summary.json`
- standalone direct mode에서는 `M190` wait를 제거해 즉시 motion 확인을 수행한다.
- standalone 종료 후 `G28` homing은 보류한다. `home_after_standalone=false`를 runtime contract로 기록하고, ejection tail 내부의 예상 밖 `G28`은 blocker로 유지한다.
- 실제 출력 job은 계속 `.autoeject.gcode.3mf` + MQTT `project_file` 경로를 사용한다. Standalone direct `gcode_line`은 ejection-only test path이며 normal print job start path가 아니다.

---

## 2. Provider 계층

프린터 선택은 agent 내부 분기가 아니라 Device Bridge 계층에서 처리한다.

```text
SpecimenMakingAgent
  -> printer.prepare payload
  -> DeviceBridgeRouter
      -> BambuLabBridge  [default]
      -> PrusaBridge     [operator-selectable]
```

필수 원칙:

- Bambu와 Prusa는 같은 `printer.prepare`, `printer.status`, `printer.start`, `printer.autoeject` contract를 공유한다.
- provider 전환은 GUI 설정과 memory/config 파일로 처리한다.
- fallback이라는 단어를 쓰지 않는다. operator가 선택한 active provider만 실행한다.
- provider별 secrets는 git에 올리지 않는다.
- Bambu native autoejection은 `manipulation_agent` provider handoff가 아니라 `bambu_gcode_patch` provider로 별도 표기한다.

저장 파일:

- Bambu connection: `memory/bambu_connection.json`
- Prusa connection: `memory/prusa_connection.json`
- active fleet/provider: `memory/printer_fleet.json`
- Bambu autoejection config: `memory/bambu_autoejection.json`
- post-ejection bed-clear evidence: `memory/bambu_bed_clear_evidence.json`
- generated/patched artifact manifest: `runs/<run_id>/workspace/printer/bambu_autoejection_manifest.json`
- physical validation proof package: `artifacts/printer/<run_id>/bambu/bambu_autoejection_physical_validation_<timestamp>.json` 또는 `artifacts/printer/manual/bambu/`

---

## 3. 인터넷 사례 조사 요약

조사한 범위:

- Reddit `r/BambuLab`: A1 Mini/P1S/X1/P1 auto eject, FarmLoop, failed ejection, MQTT start failure, user G-code modification 사례
- GitHub: Looprint, OrcaSlicer plate changer, BambuStudio CLI, OpenBambuAPI MQTT, ha-bambulab/bambuddy 이슈
- YouTube 검색 결과: Factorian Designs / FarmLoop / Bambu auto eject / queue-loop print workflow
- Bambu/SimplyPrint/3DQue/PrintFlow 문서: `.gcode.3mf`, LAN-only/Developer Mode, plate-sliced file, model placement, hardware constraints

사례에서 확인된 공통 구조:

1. 슬라이서에서 정상적으로 sliced artifact를 만든다.
2. artifact 내부 또는 end G-code에 자동 배출 시퀀스를 넣는다.
3. print completion 후 bed를 식혀 adhesion을 낮춘다.
4. toolhead/nozzle/별도 pusher가 part를 밀어낸다.
5. purge line이나 skirt/brim 잔류물을 별도로 관리한다.
6. 다음 job은 bed-clear가 확인된 뒤에만 시작해야 한다.

사례에서 확인된 주요 리스크:

- Bambu CoreXY/P1/X1 계열은 door, front path, toolhead cover, carbon rod, purge area 간섭이 실제 리스크다.
- Reddit 실패 사례에는 print가 너무 강하게 붙어 build plate 자체가 밀리는 사례가 있다.
- 일부 사용자는 homing/unknown machine-end behavior가 의도하지 않은 움직임을 만든다고 보고했다.
- GitHub 이슈에는 MQTT `project_file` publish가 success처럼 보여도 printer가 IDLE에 남거나, acknowledgment가 늦게 오는 사례가 있다.
- `.gcode.3mf` 내부에는 plate별 G-code와 metadata/hash 파일이 있으므로 단순 zip edit만으로는 충분하지 않을 수 있다.

ATR에 반영할 정책:

- autoejection은 항상 먼저 `validate_only`와 `standalone_gcode_job`으로 검증한다.
- 실제 Live publish는 `operator_confirmed`, `guardian_approved`, `bed_clear_verified`, `camera_frame_available`이 모두 만족될 때만 가능하다.
- MQTT publish 후 15초 수준의 짧은 timeout으로 실패 처리하지 않는다. 모델/펌웨어별 ack latency를 고려해 기본 180초, 최소 60초 이상으로 둔다.
- command publish 성공만으로 print/ejection 성공을 판단하지 않고 MQTT report state/progress/camera evidence를 같이 본다.

### 3.0.1 외부 사례에서 고정된 설계 결론

Reddit/GitHub/YouTube/Community 사례를 서로 대조하면 ATR의 Bambu path는 다음 결론으로 고정한다.

| 조사 축 | 외부 사례에서 확인한 사실 | ATR 반영 |
|---|---|---|
| artifact 형식 | 3DQue와 Bambu/Orca 계열 사례는 Bambu에 보낼 주 파일을 plate-sliced `.gcode.3mf`로 다룬다. plain `.gcode`는 개발/검증에 유용하지만 실운영 호환성이 낮다. | Bambu primary artifact는 `.gcode.3mf`이고, patch target은 `Metadata/plate_#.gcode`다. |
| slicer CLI | BambuStudio CLI는 `--slice`, `--load-settings`, `--load-filaments`, `--export-3mf` 중심으로 운용된다. | Device Bridge는 slicer resolver를 두고 BambuStudio/Orca CLI 또는 수동 sliced artifact를 같은 contract로 받는다. |
| upload/start | Home Assistant/ha-bambulab/MCP 사례는 FTPS upload 후 MQTT `project_file` start를 사용한다. AMS mapping이 있으면 start payload가 더 까다롭다. | FTPS/HTTP artifact transfer와 MQTT start publish를 분리하고, `ams_mapping` 누락을 blocker로 둔다. |
| MQTT 상태 | OpenBambuAPI 기준 local MQTT는 TLS 8883, username `bblp`, password LAN access code이며 report/request topic이 분리된다. | 상태 subscribe와 command publish를 별도 evidence로 기록한다. |
| success-but-idle | 커뮤니티/이슈에는 command가 success처럼 보여도 실제 print가 시작되지 않는 사례가 있다. | publish ack만으로 성공 처리하지 않고 `gcode_state`, `mc_percent`, job/progress, camera를 함께 확인한다. |
| autoeject motion | 영상/커뮤니티 사례는 cooldown 후 toolhead/nozzle/별도 pusher로 여러 높이에서 밀어내는 방식을 쓴다. | tail은 object bounds 기반 X/Y/Z sweep을 만들고, `G28` 등 예상 밖 homing을 차단한다. |
| purge/skirt residue | purge line이나 skirt/brim이 남으면 다음 job을 망치는 사례가 반복된다. | skirt/brim/raft는 기본 off, purge residue는 validator/blocker로 관리한다. |
| geometry dependency | FarmLoop 성공/실패 사례는 출력물 접촉면/밀림 edge/접착력이 ejection 성공을 좌우한다. | DesignAgent/SpecimenMakingAgent report에 Bambu autoejection readiness를 별도 항목으로 둔다. |
| camera/live view | Bambu Studio Device 화면은 camera, 상태, control, material을 동시에 보여준다. | 3DP Device Workspace는 MQTT status와 camera frame을 동시에 갱신하고, video failure가 기존 status를 지우면 안 된다. |
| multi-printer | Bambu Farm Manager와 print farm 사례는 여러 printer를 queue/state 중심으로 관리한다. | DeviceBridgeRouter는 여러 printer profile을 보유하고 active provider를 명시 선택한다. 기본은 Bambu, Prusa는 fallback이 아니라 operator-selectable provider다. |

### 3.0.2 추가 웹조사 반영 사항

사용자가 지정한 Reddit/GitHub/YouTube/Bambu community 범위를 다시 대조한 결과, 14번 개선안은 다음 항목을 명시 요구사항으로 둔다.

| 출처군 | 확인 내용 | ATR 구현 기준 |
|---|---|---|
| Bambu Wiki / third-party integration | LAN mode는 slicer 전송과 monitoring을 LAN에서 수행하기 위한 모드이며, Developer Mode는 MQTT/live stream/FTP 계열 접근을 여는 고급 모드로 취급된다. 네트워크 문서 기준 MQTT 8883, FTP/FTPS 990, video 6000 계열 포트가 핵심이다. | `Pre-start Check`는 LAN/Developer Mode, MQTT 8883, FTPS 990, video proxy를 분리된 evidence로 표시한다. 하나가 실패해도 나머지 상태를 지우지 않는다. |
| GitHub OpenBambuAPI | `project_file` command는 `url`, `param`, `subtask_name`, `use_ams`, `ams_mapping`을 포함하고, plate path는 `Metadata/plate_X.gcode` 형태로 전달된다. | `.gcode.3mf` patcher는 내부 `Metadata/plate_#.gcode`와 MQTT `project_file.param` 정합성을 검증한다. |
| GitHub ha-bambulab / darkorb scripts | 실사용 흐름은 FTPS upload 후 MQTT `project_file` publish이다. command success와 실제 print start가 분리될 수 있고 AMS mapping 누락은 pause/start failure로 이어질 수 있다. | upload, start publish, running-state transition을 별도 gate로 둔다. AMS 사용 시 mapping이 없으면 start gate를 막는다. |
| GitHub bambu-proxy / HA community | Bambu MQTT connection limit 문제가 반복적으로 보고된다. Mosquitto relay로 여러 client를 하나의 printer connection으로 multiplex하는 사례가 있다. | 장기적으로 DeviceBridge 내부에 MQTT session cache 또는 optional local relay adapter를 둔다. GUI poll마다 새 MQTT client를 만들지 않는다. |
| GitHub DrozmotiX ioBroker X2D issue | X2D/H2D 계열 MQTT report에는 기존 X1/P1보다 깊은 `2D`, `3D`, `device`, `ams`, `plate`, dual-nozzle/tool 상태가 포함된다. | X2D normalizer는 단순 X1/P1 schema에 맞춰 필드를 버리지 않는다. raw report 보존, normalized summary, unknown-field passthrough를 분리한다. |
| Reddit BambuLab / 3DPrinting | autoeject 성공 사례와 함께 bed adhesion, plate 밀림, toolhead cover 이탈, 의도치 않은 homing, purge residue 실패가 반복된다. | 첫 live autoejection은 disposable part + supervised mode로 제한하고, validator는 `G28`, envelope 초과, residual skirt/brim/purge risk를 blocker로 둔다. |
| YouTube FarmLoop / Factorian / Bambu P-X-A autoeject | cooldown 후 여러 Z height에서 bed/front 방향으로 sweep하는 패턴이 일반적이다. part geometry와 push edge 설계가 성공률을 크게 좌우한다. | tail generator는 object bounds 기반 X position, part height 기반 multi-sweep Z, cooldown target, push speed 상한을 설정값으로 노출한다. |
| Infinity Flow / 3DQue 계열 가이드 | purge line이 너무 얇으면 eject되지 않아 다음 print에 간섭할 수 있고, center-front placement 및 bed material/cooling이 중요하다. | Bambu autoejection profile은 skirt/brim off, purge residue policy, bed-clear evidence, object placement warning을 report에 포함한다. |
| Bambu Studio Device reference | camera, progress/layer, thermal, AMS/material, controls, print completion 상태가 한 화면에 동시에 유지된다. | 3DP Device Workspace는 Bambu Studio처럼 aggregate view를 구성하되, 임의 값이 아니라 backend normalized report와 camera frame evidence만 표시한다. |

추가 구현 원칙:

- FTPS `421 There are too many connections`는 generic SSL/probe failure로 뭉개지지 않아야 한다. 전용 code `BAMBU_FTPS_TOO_MANY_CONNECTIONS` 또는 동등 operator action으로 표시한다.
- Camera/video 조회는 MQTT/status cache와 병렬 plane이다. `Video Status` 버튼이 기존 device/material/progress card를 초기화하면 안 된다.
- MQTT/FTPS client는 요청마다 무제한 생성하지 않고, close/timeout/retry 정책을 명시한다. GUI polling용 MQTT status는 짧은 snapshot cache를 재사용하고, `pushall`은 cache miss 또는 explicit refresh에서만 보낸다.
- `.gcode.3mf` patch는 원본을 덮어쓰지 않고 `.autoeject.gcode.3mf`를 생성하며, patch manifest에 source hash, patched hash, internal plate path, validator result를 남긴다.
- Bambu autoejection은 BambuLab active provider에서만 수행한다. Prusa는 operator가 active provider로 선택했을 때만 Prusa bridge를 탄다.

### 3.0.3 Reddit/GitHub/YouTube 재조사로 추가 고정한 운영 제약

이번 재조사는 성공 사례보다 실패/경계조건을 우선했다. 결론은 "G-code를 붙이면 자동 배출된다"가 아니라, `설계 형상`, `slicer residue`, `printer LAN 상태`, `start command ack`, `camera/bed-clear evidence`가 모두 맞아야 반복 운전이 가능하다는 것이다.

| 조사 항목 | 확인한 내용 | ATR 요구사항 |
|---|---|---|
| Reddit printhead push 리스크 | Bambu printhead cover가 자석 결합이고, X축 carbon rod에 반복 횡방향 충격을 주는 구조는 장기 리스크라는 의견이 반복된다. | 첫 live ejection은 `supervised=true`와 disposable object로 제한한다. Validator report에 `push_force_risk_note`를 남기고, 큰 접착면/너무 낮은 형상은 차단한다. |
| Reddit FarmLoop 실패/성공 | 실패 사례는 bed adhesion이 너무 강해 build plate가 밀리는 쪽이고, 성공 사례는 bottom contact area를 줄이고 push edge를 추가한 뒤 해결했다. | DesignAgent는 `bed_contact_area_ratio`, `pushable_edge_height_mm`, `ejection_contact_edge`를 report해야 한다. 낮은 시편/넓은 접촉면은 `BAMBU_AUTOEJECTION_OBJECT_TOO_LOW` 또는 geometry blocker로 막는다. |
| Reddit A1 Mini end G-code | 커뮤니티 G-code는 heat off, 장시간 cooldown, vibration/loosening, perimeter sweep, back-to-front sweep처럼 다단계를 쓴다. | Tail generator는 단일 직선 push가 아니라 cooldown + height-fraction multi-sweep을 기본으로 둔다. |
| Infinity Flow / YouTube queue-loop | 여러 높이에서 sweep해야 다양한 높이의 part를 제거할 수 있고, 얇은 purge line은 그대로 남아 다음 job을 망칠 수 있다. | `max_layer_z` 기반 `0.9/0.6/0.4/0.2` 또는 동등 multi-sweep을 지원하고, purge/skirt/brim/raft residue는 validator blocker로 둔다. |
| 3DJake/Factorian 계열 | 반복 print는 start/end G-code만 붙이는 문제가 아니라 repeated calibration, prime line, hotend oozing, chamber/door, model push point, release temperature까지 같이 조정해야 한다. | ATR은 Bambu Studio/Orca profile을 직접 덮어쓰지 않고 post-process patch를 우선한다. 동시에 `skirt/brim off`, first-layer/bed-temp, cooldown target, push envelope를 profile evidence로 남긴다. |
| OpenBambuAPI MQTT | Local MQTT는 TLS 8883, username `bblp`, LAN access code 기반이며, `project_file`은 `Metadata/plate_X.gcode`, `url`, `subtask_name`, `use_ams`, `ams_mapping`을 함께 본다. `pushing.pushall`은 P1 계열에서 너무 자주 호출하면 lag 위험이 있다. | GUI polling마다 새 MQTT client/pushall을 만들지 않는다. Status cache와 explicit refresh를 분리하고, project_file draft는 artifact 내부 plate path 및 AMS mapping을 검증한다. |
| ha-bambulab / Home Assistant | FTPS upload 후 MQTT start가 가능하지만, AMS mapping UX가 까다롭고 command가 success처럼 보여도 실제 start가 안 되는 사례가 있다. | FTPS upload, MQTT publish ack, `gcode_state` transition, `mc_percent`, `subtask_name`을 각각 독립 evidence로 저장한다. AMS 사용 시 mapping 없으면 publish 차단한다. |
| Bambu Studio LAN issue | 프린터가 MQTT/FTPS로는 정상인데 Bambu Studio의 network config/cache가 stale 상태가 되어 GUI만 offline처럼 보이는 GitHub 사례가 있다. | ATR Pre-start Check는 Bambu Studio GUI 상태를 신뢰하지 않고 직접 MQTT/FTPS/HTTP/video probe 결과를 우선한다. Bambu Studio CLI는 slicing 도구이지 connection truth source가 아니다. |
| Bambu Farm Manager | Bambu 공식 farm 방향도 LAN 기반 multi-printer monitoring, queue, batch control, power/load management를 강조한다. | 3DP Device Workspace는 단일 printer form이 아니라 fleet registry/active profile/device screen을 유지한다. Prusa는 fallback이 아니라 operator-selected profile이다. |
| 3DQue/AutoFarm3D | P1/X1 enclosed printer는 door/open-front/bed surface가 핵심이며, VAAPR 같은 release surface와 door opener를 별도 구성한다. | Native G-code ejection만으로 unattended loop를 default로 켜지 않는다. door/front clearance와 bed-clear evidence가 없는 경우 next job을 막는다. |

### 3.0.4 2026-06-16 추가 조사로 고정한 세부 기본값과 GUI 요구사항

Reddit, GitHub, YouTube, Bambu community, 3DQue, Factorian Designs, Looprint를 다시 대조한 결과, ATR은 다음 세부 항목을 구현 기준으로 둔다.

| 근거 | 확인한 세부 내용 | ATR 반영 |
|---|---|---|
| Looprint source/UI | Looprint는 P1/P1S/X1/X1C에서 left/center/right push lane을 두고, 기본 `Z Push Offset 30mm`, `Push Lane Offset 30mm`, `Push-off Speed 300mm/min`, optional `Full Bed Sweep 7 passes`, `Sweep Z 1mm`를 노출한다. | 3DP GUI는 Bambu autoejection panel에 `push_direction`, `z_push_offset_mm`, `push_lane_offset_mm`, `push_speed_mm_min`, `enable_full_bed_sweep`, `sweep_z_mm`, `sweep_speed_mm_min`을 보여준다. 기본값은 위 값으로 두되, validator가 model bounds 기반으로 축소/차단할 수 있어야 한다. |
| Looprint source/UI | Looprint는 "Generate Test File"과 "Generate Sweep Test File"을 별도로 제공한다. | ATR은 `Validate G-code Preview`, `Generate Ejection Test Artifact`, `Generate Sweep Test Artifact`를 publish/start와 분리한다. 테스트 artifact 생성은 printer로 전송하지 않는다. |
| Looprint source/UI | P1/P1S/X1/X1C는 X-axis dynamic multi-lane push, A1/A1 Mini는 Y-axis bed-slinger push/wiggle sweep을 사용한다. | Bambu bridge는 model family별 tail generator를 분리한다. X/P 계열 tail을 A1 계열에 재사용하지 않는다. |
| 3DQue guide | Bambu P1/X1 autoejection은 center-front placement가 가장 안전하며, Y usable range와 Z min/max 제한이 있다. 문서 기준 Y rear clearance와 Z 5-200mm 제한이 핵심이다. | Validator는 Bambu profile별 build envelope, rear clearance, object height, object count를 gate로 검사한다. 기본은 one-object supervised autoejection이다. |
| 3DQue guide | P1/X1 enclosed printer는 door/ramp/bed surface/fan cover 고정이 실제 운용 조건이다. | Pre-start Check는 `door_or_front_path_clear`, `ejection_ramp_or_bin_ready`, `toolhead_cover_secured`, `release_surface_profile`을 operator checklist로 표시한다. 이 항목은 하드웨어 sensor가 없으면 operator confirmation evidence로 남긴다. |
| Factorian Designs / YouTube | 반복 생산 사례가 있어도 모델별 custom configuration과 전체 절차 확인이 필요하며, 적용 책임/손상 위험이 명시된다. | ATR은 autoejection enabled를 "production-safe"로 간주하지 않는다. 처음 활성화하거나 geometry가 바뀐 경우 `first_ejection_supervised_required=true`를 둔다. |
| ha-bambulab issue | P1/P1S/A1 계열에서 local MQTT client 재접속/중복 client가 상태 갱신 불안정을 만들 수 있다. | DeviceBridge는 GUI 버튼 클릭마다 새 MQTT client를 무제한 생성하지 않는다. long-lived session 또는 connection cache를 우선하고, `pushall`은 explicit refresh에서만 사용한다. |
| BambuBoard | camera feed는 모델군별 transport가 다르며, X1/X1C/H2D/P2S는 RTSP류, P1/A1 계열은 chamber image protocol 또는 proxy 접근이 쓰인다. | 3DP Device Workspace는 camera plane을 status plane과 분리한다. camera refresh 실패는 기존 thermal/progress/material status를 지우면 안 된다. |
| darkorb/ha-bambulab/MCP 사례 | FTPS upload와 MQTT start는 분리되어 있고, `.gcode`와 `.gcode.3mf`는 start command path가 다르다. | GUI에는 `Transfer artifact`, `Start selected artifact`, `Patch native artifact` 상태를 분리 표시한다. `.gcode.3mf`는 `project_file`, plain `.gcode`는 SD/cache G-code command path로만 다룬다. |
| Reddit success/failure | bed adhesion 실패는 양방향이다. 너무 잘 붙으면 build plate가 밀리고, 너무 안 붙으면 print 중 실패한다. | Autoejection readiness는 "출력 가능성"과 별개로 평가한다. `bed_contact_area_ratio`, `release_temperature_c`, `pushable_edge_height_mm`, `first_layer_profile`을 report에 남긴다. |

추가로, 3DP Device Workspace의 Bambu 화면은 Bambu Studio Device 탭의 구조를 참고한다. 단순 로그 panel이 아니라 다음 정보를 동시에 유지해야 한다.

- printer selector / active provider / LAN or Developer Mode status
- camera snapshot or live frame
- nozzle, bed, chamber, fan, light, current job, layer/progress
- AMS/material mapping and selected tray
- transfer/upload/start state
- native G-code autoejection config and validation state
- bed-clear evidence and last camera frame

중요한 구현 금지사항:

- `Video Status` 같은 camera action이 기존 printer status card를 비우면 안 된다.
- MQTT start publish success만으로 "printing" 또는 "ejection complete"로 표시하면 안 된다.
- Bambu G-code patch provider를 Manipulation Agent handoff로 표기하면 안 된다.
- Bambu/Prusa 전환을 fallback으로 부르면 안 된다. 항상 operator-selected active provider다.
- 외부 자료의 G-code를 그대로 복사하지 않는다. ATR validator와 printer profile bounds를 통과한 deterministic tail만 사용한다.

주요 참고 링크:

- Bambu LAN mode: https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode
- Bambu network ports: https://wiki.bambulab.com/en/general/printer-network-ports
- Bambu third-party integration: https://wiki.bambulab.com/en/software/third-party-integration
- OpenBambuAPI MQTT notes: https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
- OpenBambuAPI AMS mapping issue: https://github.com/Doridian/OpenBambuAPI/issues/10
- darkorb FTP and print script: https://github.com/darkorb/bambu-ftp-and-print
- Bambu MQTT proxy: https://github.com/disconn3ct/bambu-proxy
- X2D MQTT report issue: https://github.com/DrozmotiX/ioBroker.bambulab/issues/258
- ha-bambulab upload/start discussion: https://github.com/greghesp/ha-bambulab/discussions/307
- ha-bambulab scheduled start discussion: https://github.com/greghesp/ha-bambulab/discussions/628
- Bambu Studio LAN stale config issue: https://github.com/bambulab/BambuStudio/issues/10148
- Reddit automatic ejection queue risk discussion: https://www.reddit.com/r/BambuLab/comments/11wexiz/automatic_print_ejection_and_print_queue/
- Reddit A1 Mini auto eject end G-code discussion: https://www.reddit.com/r/BambuLab/comments/1jfayjd/a1_mini_auto_eject_end_g_code/
- Reddit FarmLoop failure: https://www.reddit.com/r/BambuLab/comments/1k7ffzl/a1_mini_auto_ejection_fail_build_plate_shifts/
- Reddit FarmLoop success after design change: https://www.reddit.com/r/BambuLab/comments/1kob69u/automation_success_a1_mini_autoeject_working/
- 3DJake queue/loop guide: https://www.3djake.ie/info/guide/fully-automate-your-3d-printer-auto-ejection-queues-and-loops
- Fabbaloo Factorian summary: https://www.fabbaloo.com/news/factorian-designs-shows-how-to-implement-auto-ejection-on-desktop-3d-printers
- Infinity Flow Bambu P1S bed clearing guide: https://infinityflow3d.com/blogs/3d-printer-automation/3d-printer-auto-bed-clearing-bambu-p1s-example
- 3DQue Bambu X1/P1 autoejection guide: https://docs.3dque.com/docs/installation-guides/auto-ejection-kit-installation/Bambu-X1-P1
- Looprint Bambu multi-loop G-code builder: https://github.com/NickiAndersen/looprint
- BambuBoard camera/status dashboard: https://github.com/t0nyz0/BambuBoard
- Bambu MCP server print/start caveats: https://github.com/DMontgomery40/bambu-printer-mcp
- YouTube FarmLoop / Bambu P-X autoeject examples: https://www.youtube.com/watch?v=Vxj1ii6dPYo , https://www.youtube.com/watch?v=VHI3ywHX7yU

---

## 3.1 사례별 구현 반영

이번 추가 조사에서 확인한 구현상 핵심은 다음과 같다.

### Looprint 계열

Looprint는 이미 sliced된 G-code 또는 3MF를 입력으로 받아 원본 start/end code를 정리하고, `print -> cooldown -> push-off -> next print` 구조로 다시 감싸는 방식이다. 이 접근은 ATR에 다음 요구사항을 추가한다.

- STL만 입력받는 slicing-only 경로가 아니라, 이미 생성된 `.gcode.3mf` 또는 plain `.gcode`를 받아 patch하는 경로가 필요하다.
- patcher는 원본 파일을 덮어쓰지 않고 `.autoeject.gcode.3mf` 또는 `.autoeject.gcode` artifact를 새로 만든다.
- 반복 loop를 당장 자동 실행하지 않더라도, 단일 출력물 ejection tail과 multi-loop wrapper를 분리 가능한 구조로 둔다.
- patch 결과에는 source hash, patched hash, loop index, plate id가 남아야 한다.

### FarmLoop / Factorian Designs / YouTube 계열

영상 및 커뮤니티 사례는 `cooldown`, `part geometry tweak`, `push edge`, `repeat`를 같이 다룬다. 단순히 gantry를 밀면 되는 문제가 아니라 출력물 설계 자체가 eject 가능해야 한다.

ATR 반영:

- SpecimenDesignAgent는 Bambu autoejection enabled일 때 `ejection_contact_edge`, `bed_contact_area`, `minimum_pushable_height`, `skirt/brim policy`를 같이 기록한다.
- Design report에는 "FDM printability"와 별도로 "Bambu autoejection readiness" 항목을 둔다.
- 너무 낮은 시편, 접촉 면적이 과도한 시편, 휘거나 빌드플레이트를 같이 밀 가능성이 큰 시편은 `BAMBU_AUTOEJECTION_GEOMETRY_NOT_READY`로 차단한다.

### 3DQue / AutoFarm3D 계열

3DQue 문서는 Bambu P1/X1 계열에서 plate-sliced file인 `.gcode.3mf`를 주 경로로 보고, purge line이 너무 얇아 eject되지 않을 수 있음을 명시한다. 또한 Smooth PEI/High Temp Plate와 AMS slot 정합성을 요구한다.

ATR 반영:

- Bambu provider의 primary artifact는 `.gcode.3mf`이다. plain `.gcode`는 validator/test/development 경로로만 둔다.
- `Metadata/plate_#.gcode`를 patch target으로 명시하고, MQTT `project_file.param`도 같은 plate path를 사용해야 한다.
- purge line 제거 또는 object와 결합된 purge/brim 전략을 slicer profile로 관리한다.
- AMS가 활성화된 경우 `ams_mapping`을 operator가 확인하거나 bridge가 MQTT report에서 매칭할 때까지 publish를 차단한다.

### Reddit 실패 사례

실패 사례에서 반복적으로 나온 문제는 다음이다.

- 출력물이 충분히 식지 않아 bed adhesion이 너무 강함
- build plate 자체가 밀림
- toolhead cover/fan cover가 걸림
- carbon rod 또는 gantry에 반복 충격이 누적될 수 있음
- custom G-code가 예상 밖 homing을 유발하거나, homing 순서가 ejection path를 망침
- printer가 command success처럼 보여도 실제로는 IDLE/Ready 상태에 남음

ATR 반영:

- validator는 ejection tail 안의 `G28`과 예상 밖 homing을 기본 차단한다.
- cooldown은 단일 `M190 Rxx`만 두지 않고, timeout/skip 문제가 있으면 단계식 cooldown profile을 지원한다.
- ejection feedrate와 sweep 횟수는 GUI에서 조절 가능하되, API와 local memory/config 모두에서 같은 안전 상한을 둔다. 현재 runtime cap은 `z_push_offset_mm<=200`, `push_lane_offset_mm<=120`, `push_speed_mm_min<=1000`, `sweep_z_mm<=50`, `sweep_speed_mm_min<=1000`이다.
- 첫 live test는 반드시 disposable test part + supervised mode로 제한한다.
- MQTT start는 ack 하나가 아니라 `gcode_state`, `mc_percent`, `subtask_name`, `project_file result`, camera snapshot을 함께 확인한다. `/api/printer/start-publish`는 publish 성공 후 `post_publish_observation`으로 cache를 우회한 fresh printer bridge observation을 반환해야 한다.
- `/api/printer/start-publish`는 MQTT ack와 실제 시작 관찰을 분리해 `post_publish_status`와 `post_publish_failure_code`를 반환한다. `IDLE`/not-started observation이면 `published=true`라도 `ok=false`, `failure_code=BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED`로 구분한다.

### MQTT / LAN-only / Developer Mode 사례

OpenBambuAPI와 Home Assistant 사례 기준으로 로컬 MQTT는 TLS 8883, username `bblp`, password는 LAN access code를 사용한다. `project_file` command는 `url`, `param`, `subtask_name`, `use_ams`, `ams_mapping` 등이 중요하며, 일부 firmware/model에서는 success response와 실제 start가 분리되어 보일 수 있다.

ATR 반영:

- `project_file` command builder는 `param="Metadata/plate_#.gcode"`와 artifact 내부 plate path 정합성을 검증한다.
- FTPS upload success와 MQTT command success를 분리해서 로그에 남긴다.
- command timeout은 model별 configurable로 두고 60초 미만 hard timeout을 금지한다.
- publish 이후 `RUNNING/PRINTING` 전환을 확인하지 못하면 `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED`로 구분한다.
- 일반 GUI status polling은 1~2초 수준의 MQTT snapshot cache를 사용할 수 있다. 단, publish 직후 관찰, 수동 refresh, operator가 명시한 readiness check는 `force_refresh`로 cache를 우회한다.

### Server-side slicer / sidecar 사례

Bambuddy는 headless slicer sidecar를 별도 서비스로 두고 OrcaSlicer 또는 Bambu Studio CLI를 호출한다. Bambu Studio CLI는 x86_64 중심이라는 제약이 있으므로 ATR은 다음처럼 정리한다.

- 현재 PC에 Bambu Studio/OrcaSlicer CLI가 있으면 직접 호출한다.
- 없거나 headless 운영이면 optional slicer sidecar를 `Device Bridge` 하위 adapter로 붙인다.
- sidecar는 기본 의존성이 아니라 optional provider이며, 실패해도 수동 sliced artifact upload 경로는 유지한다.

### 시스템 설명 문서 반영 기준

14번 개선안은 구현 지시 문서이고, 협업자/운영자가 읽는 시스템 설명은 별도 문서에 연결한다. Bambu bridge 변경은 다음 설명 문서에 같은 의미로 반영되어야 한다.

- `docs/hardware/bambulab_x2d_device_bridge_runtime_guideline.md`: BambuLab X2D bridge의 provider, slicing, MQTT/FTPS/HTTP, camera, bed-clear, native autoejection runtime 구조를 설명한다.
- `docs/runtime/architecture.md`: Bambu bridge가 printer fleet, status/control, artifact transfer, camera evidence, autoejection gate를 분리된 runtime plane으로 갖는다는 점을 설명한다.
- `docs/runtime/closed_loop_and_pages_reference.md`: Live GUI/SpecimenMakingAgent/3DP Workspace/API route가 같은 evidence를 공유한다는 계약을 설명한다.
- `docs/gui/gui.md`: 3DP GUI 버튼과 status/card 갱신 정책을 설명한다.
- `docs/tutorials/device_workspace_3dp_usage.ko.md`: 실제 운영자가 버튼 순서와 blocker 의미를 따라갈 수 있게 설명한다.

문서 동기화 규칙:

- 구현 전 개선안 보강 시에는 `개선안/14...`와 `docs/hardware/bambulab_x2d_device_bridge_runtime_guideline.md`를 먼저 맞춘다.
- 코드 구현 후에는 `docs/runtime/closed_loop_and_pages_reference.md`, `docs/gui/gui.md`, `docs/tutorials/*`를 실제 API/GUI 결과에 맞춰 갱신한다.
- 외부 자료 링크는 개선안과 hardware guideline에 남기고, 사용자 매뉴얼에는 링크보다 운영 절차와 경고를 우선 적는다.

---

## 4. Bambu 통신 범위

Bambu bridge는 다음 세 경로를 분리해서 관리한다.

### Printer Provider / Fleet Registry

Device Bridge는 단일 프린터 wrapper가 아니라 fleet registry 위에서 동작한다.

```text
PrinterDeviceBridgeManager
  -> PrinterFleetRegistry
      -> bambulab_x2d_lab_01  [default active]
      -> bambulab_p1s_lab_02  [optional]
      -> prusa_mk4s_lab_01    [operator-selectable]
      -> virtual_printer      [test/CI]
  -> selected provider adapter only
```

원칙:

- default는 BambuLab이다.
- Prusa는 fallback이 아니라 operator가 명시 선택한 active provider일 때만 실행한다.
- 한 printer의 start/publish 실패를 다른 printer로 자동 전환하지 않는다.
- GUI에는 printer별 connection, transfer, camera, queue, material 상태가 별도 카드로 보여야 한다.
- agent payload에는 `printer_profile_id`를 넣을 수 있고, 없으면 저장된 active printer profile을 사용한다.
- printer profile별 secrets/access code는 `memory/` 아래 provider별 파일에 저장하고 git에는 올리지 않는다.

### MQTT 상태/제어

- LAN-only mode / Developer Mode 전제
- local MQTT: `{printer_ip}:8883`, username 기본 `bblp`, password는 LAN access code
- report topic: `device/{serial}/report`
- request topic: `device/{serial}/request`
- printer report 수집
- job/progress/temperature/material/storage 상태 수집
- `project_file` 기반 start command publish
- command publish 후 상태 확인
- publish timeout은 model별 설정값을 둔다. 기본값은 180초이며, 15초 이하의 hard timeout은 쓰지 않는다.
- publish 후 MQTT client를 즉시 강제 reconnect하지 않는다. slow ack 구간에서 printer가 parsing 중일 수 있다.

### FTPS/HTTP artifact transfer

- sliced artifact upload 또는 printer-fetch 가능한 HTTP artifact route
- upload 가능한 경로 검증
- transfer 후 hash/path evidence 기록
- FTPS가 write 실패할 경우 HTTP artifact route를 진단 경로로 사용할 수 있지만, 이 경우에도 printer-fetch 확인이 필요하다.
- `.gcode.3mf`는 Bambu에서 권장되는 주 artifact로 취급한다.

### Camera/Video

- Bambu Studio Device 화면처럼 camera panel을 제공한다.
- MQTT report와 camera frame/status는 동시에 읽을 수 있어야 한다.
- `Pre-start Check`는 device status와 camera status를 모두 갱신한다.
- camera는 ejection 전 path/object 확인, ejection 후 bed-clear 확인 evidence로 사용 가능해야 한다.
- video 상태 조회가 실패해도 기존 MQTT/device status UI를 지우면 안 된다.
- `Video Status` 단독 호출은 video panel만 갱신하고, job/progress/material/status card를 초기화하지 않는다.
- `Pre-start Check`는 connection/status, transfer readiness, start gate, camera snapshot, autoejection patch readiness를 하나의 response로 병합한다.
- 버튼은 callback이 돌아올 때까지 disabled 상태를 유지한다. 같은 publish/start/check 요청이 중복 전송되면 안 된다.
- camera snapshot은 `runs/<run_id>/evidence/printer/` 또는 `artifacts/` 하위에 저장하고, bed-clear evidence schema에서 참조 가능해야 한다.

### Bambu Studio Device 화면형 aggregate

3DP GUI는 BambuStudio의 Device 탭을 그대로 복제하지는 않지만, 같은 운용 정보를 한 화면에 묶어야 한다.

필수 card:

- Camera preview: 최신 frame, stream kind, proxy state, blocker
- Job/progress: file/subtask, `gcode_state`, progress percent, layer, ETA
- Thermal: nozzle/bed/chamber/current-target, fan
- Material/AMS: active tray, material type, color, humidity/status
- Motion/control: printer state, speed override, queue state, homing/ready blocker
- Transfer/start gate: FTPS/HTTP artifact route, MQTT project_file readiness
- Autoejection: patch status, validator status, bed-clear gate

이 card들은 GUI가 임의 생성하지 않고 backend normalized report를 그대로 사용한다.

---

## 5. Artifact / G-code 패치 방식

권장 primary mode는 `append_end_gcode`이다.

```text
STL/3MF
  -> Bambu Studio or OrcaSlicer slicing
  -> plate-sliced .gcode.3mf preferred
  -> Metadata/plate_#.gcode 추출
  -> object bounds / layer height / max_layer_z / purge path 추정
  -> ejection tail 삽입
  -> internal hash/metadata 갱신
  -> patched .autoeject.gcode.3mf 생성
  -> transfer/start gate
```

지원해야 할 mode:

- `append_end_gcode`: 정상 출력 artifact 끝에 ejection tail 삽입
- `standalone_gcode_job`: 출력 없이 ejection routine만 테스트
- `validate_only`: patch 결과와 motion envelope만 검증
- `mqtt_gcode_line_test`: 개발/진단용. 기본 비활성

기본 원칙:

- Prusa bed-sweep 코드를 그대로 재사용하지 않는다.
- Bambu 전용 build envelope, bed size, toolhead clearance, purge path, door/output path 조건을 둔다.
- object 좌표를 반영한다.
- skirt/brim/raft는 autoejection profile에서 기본 OFF이다.
- G-code는 항상 validator를 통과해야 한다.
- `.gcode.3mf` 내부 G-code replacement는 `Metadata/plate_1.gcode` 등 plate별 G-code를 찾아 처리한다.
- 내부 md5/hash 파일이 존재하면 patched G-code 기준으로 갱신하거나, validator에서 `BAMBU_3MF_HASH_UPDATE_REQUIRED`로 차단한다.

---

## 6. Slicing 기준

Bambu Studio CLI 또는 wrapper를 사용한다. BambuStudio 공식 CLI는 `--slice`, `--load-settings`, `--load-filaments`, `--export-3mf` 등을 제공한다. 설정 우선순위는 command-line setting, loaded setting files, 3MF embedded settings 순으로 본다.

필수/권장 옵션:

```text
--slice 0
--arrange 1
--ensure-on-bed
--outputdir <artifact-dir>
--export-3mf <output-basename.gcode.3mf or output-basename.3mf>
--debug 2
```

Spark workstation 검증 결과:

- BambuStudio `02.07.01.57`는 `--export-3mf`에 absolute path를 넘기면 `<outputdir>/<absolute-path>`처럼 output directory를 중복 결합해 export에 실패할 수 있었다.
- runner는 `--export-3mf`에 basename만 넘겨야 한다.
- 명시 `load_settings`가 없으면 runner는 Bambu Studio 기본 machine/process/filament preset을 보존하고 `--load-settings`/`--load-filaments`를 자동 주입하지 않는다. purge, cleaning, filament start/end G-code는 유지한다.
- `/home/jin/다운로드/specimen(4).stl` 기준으로 default preset + basename export는 `.gcode.3mf`를 생성하고, sliced artifact 후처리에서 front build-plate test/intro/nozzle-load line block만 제거한 뒤 `.autoeject.gcode.3mf` patch/validator로 이어지는 것이 목표다.

front build-plate test line 제거는 CLI flag 이름이 환경/버전에 따라 다를 수 있으므로 다음 우선순위로 처리한다.

1. 명시 profile이 없으면 runner는 Bambu Studio 기본 preset을 그대로 쓰고, slicing 이후 `.gcode` 또는 `.gcode.3mf` 내부 `Metadata/plate_*.gcode`에서 front test/intro/nozzle-load line block만 제거한다. 원본 Bambu Studio preset은 수정하지 않는다.
2. operator가 explicit `load_settings`를 제공하면 그 profile을 우선 사용한다.
3. Bambu Studio CLI에서 해당 key를 직접 받을 수 있으면 extra args로 주입할 수 있다.
4. slicing 결과 G-code에서 skirt/brim/raft 잔류 path를 validator가 탐지한다.
5. 잔류물이 있으면 `BAMBU_AUTOEJECTION_RESIDUAL_PRIME_OR_SKIRT_RISK`로 차단한다.

이유:

- skirt/brim/raft가 있으면 autoejection 시 잔류물이 bed에 남거나 object bounds 추정이 흔들린다.
- Bambu/P1/X1 사례에서 purge line이 얇아 eject되지 않고 다음 print에 간섭할 수 있다는 문제가 반복된다.
- autoejection test에서는 실제 출력물만 밀어내는 것을 목표로 한다.

`Filament start gcode`와 `Filament end gcode`는 Bambu Studio profile에 존재할 수 있다. ATR bridge는 slicer profile의 start/end G-code를 임의로 덮어쓰지 않고, slicing 결과의 plate G-code에 deterministic ejection tail을 후처리로 삽입하는 방식을 우선한다.

---

## 7. Ejection Tail 요구사항

ejection tail은 다음 정보를 기록해야 한다.

- schema marker: `atr.bambu.autoejection.v1`
- source artifact hash
- patched artifact hash
- source plate path: 예 `Metadata/plate_1.gcode`
- object bounds
- selected object position: left/center/right/object-center
- material/bed type
- max layer z / object height
- cooldown bed temperature
- cooldown wait policy
- sweep X/Y/Z
- feedrate
- purge/parking strategy
- door/open-front clearance assumption
- fan cover / toolhead cover risk note
- validation result

기본 tail 단계:

1. motion queue 대기
2. nozzle/bed 종료 정책과 충돌하지 않는 위치에 marker 삽입
3. bed cooldown 또는 `M190` 기반 목표 온도 대기
4. toolhead safe Z 이동
5. object bounds 기반 X 위치 정렬
6. center-front 또는 object-center 기반 primary sweep
7. 필요 시 높이별 multi sweep
8. purge line/prime block 제거 경로가 있으면 별도 sweep
9. end marker와 progress marker 기록
10. heaters/motors는 Bambu 기본 종료 정책과 충돌하지 않게 처리

G-code 생성 기본값:

- cooldown bed temperature: PLA 기준 35-45 C 범위에서 operator 설정
- minimum object height: 5 mm 미만은 자동 배출 차단 또는 manual 확인
- maximum object height: 200 mm 초과는 자동 배출 차단
- Y rear clearance: rear 50 mm 이상 필요하다고 가정
- multi-object plate: 기본 차단. single-object 또는 명시 object 선택만 허용
- first live test: small disposable test part만 허용

---

## 8. Safety / Validator

validator는 실제 publish 전 다음을 확인한다.

- build envelope 초과 없음
- X/Y/Z motion이 provider별 safe envelope 안에 있음
- `G28` 등 예상 밖 homing command가 ejection tail 내부에 없음
- ejection tail marker가 정확히 1개만 존재
- original end G-code와 ejection tail 순서가 정책과 맞음
- bed cooldown 명령 또는 wait policy 존재
- purge/skirt/brim/raft 잔류 위험 없음
- `.gcode.3mf` 내부 plate G-code와 metadata/hash 정합성 확인. 기존 `Metadata/plate_#.gcode.md5`는 갱신하고, 없으면 새로 추가한다.
- `project_file` command의 `url`, `param`, `subtask_name`, `plate_id` 정합성 확인
- AMS mapping이 필요한 파일이면 mapping 누락 시 차단
- camera frame 또는 operator visual confirmation이 없으면 live autoejection publish 차단
- `.autoeject.*` live publish는 front path/door, ramp/bin, toolhead cover, release surface/profile, supervised first ejection checklist가 모두 확인될 때만 허용

차단 코드 예시:

- `BAMBU_AUTOEJECTION_TAIL_MISSING`
- `BAMBU_AUTOEJECTION_TAIL_DUPLICATED`
- `BAMBU_AUTOEJECTION_UNSAFE_MOTION`
- `BAMBU_AUTOEJECTION_UNSAFE_FEEDRATE`
- `BAMBU_AUTOEJECTION_UNEXPECTED_HOME`
- `BAMBU_AUTOEJECTION_MODEL_FAMILY_UNSUPPORTED`
- `BAMBU_AUTOEJECTION_FRONT_PATH_NOT_CONFIRMED`
- `BAMBU_AUTOEJECTION_RAMP_OR_BIN_NOT_CONFIRMED`
- `BAMBU_AUTOEJECTION_TOOLHEAD_COVER_NOT_CONFIRMED`
- `BAMBU_AUTOEJECTION_RELEASE_SURFACE_NOT_CONFIRMED`
- `BAMBU_AUTOEJECTION_SUPERVISED_FIRST_RUN_NOT_CONFIRMED`
- `BAMBU_AUTOEJECTION_OBJECT_TOO_LOW`
- `BAMBU_AUTOEJECTION_OBJECT_TOO_TALL`
- `BAMBU_AUTOEJECTION_MULTI_OBJECT_UNSUPPORTED`
- `BAMBU_AUTOEJECTION_RESIDUAL_PRIME_OR_SKIRT_RISK`
- `BAMBU_AUTOEJECTION_COOLDOWN_WAIT_MISSING`
- `BAMBU_3MF_HASH_UPDATE_REQUIRED`
- `BAMBU_PROJECT_FILE_PARAM_MISMATCH`
- `BAMBU_PROJECT_FILE_SUBTASK_NAME_INVALID`
- `BAMBU_AMS_MAPPING_REQUIRED`

---

## 9. Bed-clear Gate

Bambu native autoejection은 ejection 성공 응답만으로 다음 cycle을 시작하면 안 된다.

정책:

- `.autoeject` artifact를 실제 publish하면 즉시 `bed_clear_required=true`, `bed_clear_verified=false`로 저장한다.
- 다음 `Pre-start Check` 또는 `printer.prepare`는 bed-clear가 verified 되기 전까지 막는다.
- operator가 `Mark Bed Clear`를 누르거나 camera/vision gate가 clear를 증명하면 verified로 전환한다.
- `Video Status` 또는 `Pre-start Check`로 표시된 최신 camera preview/proxy evidence는 `Mark Bed Clear` 저장 시 `camera_snapshot_path`로 함께 저장한다. Guarded `.autoeject.*` publish에서는 가능하면 `artifacts/bambu_camera_evidence/` 아래 로컬 JPEG로 저장하고, capture 실패 시 preview URL을 fallback evidence로 둔다.
- clear 실패 시 Manipulation Agent recovery로 넘길 수 있다.
- next print queue는 bed-clear가 verified 되기 전까지 pending 상태로 유지한다.

차단 코드:

- `BAMBU_POST_EJECT_BED_NOT_CLEAR`

Evidence schema:

```json
{
  "schema": "bambu_bed_clear_evidence.v1",
  "printer_profile_id": "bambulab_x2d_lab_01",
  "source_artifact_sha256": "...",
  "patched_artifact_sha256": "...",
  "bed_clear_required": true,
  "bed_clear_verified": false,
  "verification_method": "operator|camera|vision|virtual",
  "camera_snapshot_path": "/api/printer/video-frame.jpg?t=...",
  "updated_at": "..."
}
```

---

## 10. 3DP Device Workspace 반영 계획

3DP GUI에는 Bambu provider 선택 시 다음 섹션을 표시한다.

- Bambu connection / LAN-only mode / Developer Mode
- device screen: status, job, progress, temperature, material, storage, safety
- camera preview
- slicer resolver
- source STL/3MF path
- sliced artifact path
- HTTP artifact route
- start gate controls
- SPC readiness
- Bambu G-code Autoejection
- bed-clear evidence

Autoejection 섹션 버튼:

- Save Autoejection Config
- Generate Patched Artifact
- Validate G-code Preview
- Validate Left
- Validate Center
- Validate Right
- Standalone Eject Artifact: Left
- Standalone Eject Artifact: Center
- Standalone Eject Artifact: Right
- Mark Bed Clear
- Mark Not Clear

GUI 표시 요구사항:

- 통신형 버튼은 callback이 돌아올 때까지 비활성화한다.
- validation 결과는 pass/fail만 표시하지 말고 차단 코드, object bounds, sweep path, patch target plate를 같이 보여준다.
- G-code preview는 전체 파일을 그대로 보여주지 말고 inserted tail, marker, envelope summary만 접을 수 있게 표시한다.
- Camera preview는 pre-start와 bed-clear evidence 영역에서 공유한다.
- Bed-clear가 false면 Start Publish 버튼은 disabled 상태로 유지한다.

---

## 11. Live/Test 동작

### Test + Virtual Bridge

- 실제 프린터 motion 없음
- slicing/gcode patch/validation simulation
- standalone ejection artifact 생성 가능
- bed-clear evidence는 virtual evidence로만 기록
- `.gcode.3mf` patch/validator unit test는 반드시 실행

### Test + Installed Printer

- 실제 Bambu 통신 확인
- camera frame 확인
- slicing/transfer/start gate 직전까지 확인
- operator가 실제 출력 옵션을 선택한 경우에만 publish
- autoejection enabled면 patched artifact 기준으로 검증
- standalone ejection artifact는 operator-confirmed일 때만 실제 publish 가능

### Live

- active Bambu provider 기준으로 실제 slicing/transfer/start
- autoejection enabled면 patched artifact로 실제 출력
- 출력 후 bed-clear required 상태로 잠금
- MQTT publish 후 progress/state/camera evidence를 지정 시간 동안 관찰
- 실패 시 `ready`, `idle`, `running`, `failed`, `timeout` 상태를 구분해 report한다.

---

## 12. Implementation Slice

구현은 한 번에 live motion까지 가지 않고 다음 순서로 진행한다.

1. `BambuGcodeAutoejectionPatcher` 추가
2. plain `.gcode` tail insertion + marker validator
3. `.gcode.3mf` 내부 `Metadata/plate_#.gcode` extraction/replacement
4. metadata/hash update 또는 hash-required blocker 구현
5. object bounds parser 구현
6. standalone left/center/right ejection artifact 생성
7. GUI validation/result rendering
8. Pre-start Check가 autoejection enabled 시 patched artifact를 사용하도록 변경
9. bed-clear memory gate 추가
10. 실제 MQTT publish 경로 연결
11. camera bed-clear evidence 연결
12. Live GUI/SpecimenMakingAgent message 업데이트
13. 시스템 설명 문서 동기화
   - `docs/README.md`: 협업자가 진입점에서 Bambu/3DP bridge 구조를 이해할 수 있게 page/code/doc map 갱신
   - `docs/hardware/bambulab_x2d_device_bridge_runtime_guideline.md`: BambuLab X2D bridge의 provider 계층, slicing/artifact, MQTT/FTPS/HTTP, camera/bed-clear, native autoejection 설명 갱신
   - `docs/runtime/architecture.md`: Bambu bridge runtime plane 설명 갱신
   - `docs/runtime/closed_loop_and_pages_reference.md`: Live GUI, SpecimenMakingAgent, PrinterDeviceBridgeManager, Bambu native patch/start gate, bed-clear evidence 관계 갱신
   - `docs/gui/gui.md`: 3DP GUI 버튼/상태/비활성화/카메라 plane/Publish Start 의미 갱신
   - `docs/tutorials/device_workspace_3dp_usage.ko.md`, `docs/tutorials/user_manual.ko.md`, `docs/tutorials/user_manual.en.md`: 실제 운영자가 따라갈 수 있는 사용법과 blocker 의미 갱신

구현 단위별 파일 범위:

- `device_bridges/bambu_autoejection.py`
  - `.gcode` tail insertion
  - `.gcode.3mf` extraction/replacement
  - md5/hash update
  - object bounds parser
  - motion envelope validator
  - standalone left/center/right ejection artifact generator
- `device_bridges/bambu_bridge.py`
  - Bambu autoejection config/memory schema 확장
  - active provider가 Bambu일 때 patcher 호출
  - `project_file` command의 `param/url/subtask_name/ams_mapping` 검증
- `app/main.py`
  - patch artifact endpoint
  - standalone ejection artifact endpoint
  - bed-clear evidence endpoint
  - pre-start check에서 camera/status/artifact validation 병합
- `web/templates/printer.html`
  - provider handoff 중심 UI 제거
  - Bambu G-code Autoejection panel 추가
  - bed-clear panel 추가
- `web/static/printer.js`
  - 통신 버튼 pending 중 disabled
  - pre-start check 시 camera/status 동시 갱신
  - video status 실패 시 기존 device status 유지
  - validation result summary rendering
- `tests/unit/test_bambu_bridge.py`
  - patcher/validator/3MF/hash/project_file tests
- `tests/integration/test_printer_gui_api.py`
  - GUI strings/endpoints/disabled button behavior tests

TDD 우선순위:

1. plain `.gcode` patch test를 먼저 실패시킨다.
2. `.gcode.3mf` 내부 `Metadata/plate_1.gcode` replacement test를 실패시킨다.
3. unsafe motion/G28 duplicated marker validator test를 실패시킨다.
4. pre-start check가 autoejection enabled 시 patched artifact를 선택하는 integration test를 실패시킨다.
5. 3DP GUI가 provider handoff가 아니라 G-code patch workflow를 보여주는 integration test를 실패시킨다.

---

## 13. 검증 항목

최소 테스트:

- Bambu connection memory masking
- MQTT status snapshot
- camera status/frame route
- Bambu Studio executable resolution
- Bambu Studio CLI command includes `--slice`, `--arrange`, output/export path
- skirt/brim/raft off profile 또는 validator blocker
- plain `.gcode` patch
- `.gcode.3mf` internal G-code replacement
- `.gcode.3mf` metadata/hash handling
- object bounds extraction
- ejection tail validation
- unexpected homing command detection
- left/center/right standalone artifact generation
- pre-start check에서 patched artifact 경로 사용
- publish 후 bed-clear required 저장
- bed-clear 미검증 시 다음 print 차단
- MQTT publish ack timeout이 configurable이고 60초 미만으로 hard-coded되지 않음
- video status 실패가 device status UI를 지우지 않음

현재 검증 상태:

- 단위/통합 테스트와 정적 검사는 `tests/unit/test_design_agent.py`, `tests/unit/test_specimen_agent.py`, `tests/unit/test_bambu_autoejection.py`, `tests/unit/test_bambu_bridge.py`, `tests/integration/test_printer_gui_api.py` 기준으로 통과해야 한다.
- `/home/jin/다운로드/specimen(4).stl` 기준 BambuStudio `02.07.01.57` CLI에서 default preset + basename `--export-3mf` 방식으로 `.gcode.3mf` 생성하고 front test line만 post-process 제거하는 경로를 기준으로 검증한다.
- 생성 artifact의 `Metadata/plate_1.gcode` front test line removal, md5 sidecar 갱신, `BAMBU_AUTOEJECTION_UNEXPECTED_HOME` 및 `BAMBU_AUTOEJECTION_RESIDUAL_PRIME_OR_SKIRT_RISK` 없는 validator 통과를 확인해야 한다.
- `Validate G-code Preview`와 left/center/right validation은 `validate_only=true` 경로로 `.autoeject.*` artifact와 manifest를 만들지 않는 비파괴 검증으로 분리됐다.
- standalone ejection artifact generation은 left/center/right 세 위치 모두 unit test로 고정한다. 각 artifact는 `*.left|center|right.autoeject.gcode` 이름, `atr_position=<position>` marker, 위치별 sweep X 좌표, `will_publish=false`, validator pass를 증거로 삼는다.
- `.gcode.3mf` patch는 요청한 `plate_id`의 `Metadata/plate_<id>.gcode`만 허용한다. 요청 plate가 없으면 다른 plate를 fallback으로 쓰지 않고 `BAMBU_3MF_PLATE_GCODE_NOT_FOUND`로 차단한다.
- patch result와 manifest에는 `source_sha256`, `patched_sha256`, `source_plate_path`, `plate_id`, `loop_index`, validator result가 남는다. `loop_index` 미지정 시 단일 출력 artifact 기준 `1`이다.
- Bambu MQTT publish client는 normal print start에는 `project_file` command를 사용한다. Standalone ejection-only test는 별도 guarded path에서 `gcode_line` command를 허용하며, direct `gcode_line` payload는 access code를 결과에 노출하지 않고 publish callback deadlock을 만들지 않는 unit test로 고정한다.
- Native Bambu standalone autoejection test endpoint는 artifact generation-only 요청에서는 `motion_started=false`, `standalone_artifact.will_publish=false`, `standalone_artifact.start_enabled=false`를 유지한다. `mode=live`, `start_immediately=true`, operator/Guardian/safety gates 통과, dry-run off 조건에서는 `/api/printer/autoejection-test -> MQTT gcode_line`으로 ejection-only motion을 시작할 수 있다.
- 이미 `atr.bambu.autoejection.v1` marker가 들어 있는 `.autoeject.*` artifact를 다시 pre-start 또는 patch route에 넣으면 새 `.autoeject.autoeject.*` 파일을 만들지 않는다. 기존 artifact를 검증하고 sidecar manifest만 갱신해 idempotent하게 처리한다.
- slicing/patch/validation 검증은 비파괴 증거이며, 실제 Bambu 프린터 ejection 성공을 의미하지 않는다. 별도 physical standalone validation은 `runs/manual_bambu_validation/direct_gcode_line_validation_summary.json`의 center/left/right `gcode_line` evidence로만 선언한다.
- HTTP artifact route는 ATR 서버의 LAN IP URL로 server-side fetch 및 sha256 match까지 확인됐다. 이는 publish 전 transfer 후보 검증이며, MQTT `project_file` publish나 실제 프린터 fetch/start를 의미하지 않는다.
- Dry-run `Pre-start Check`는 camera/status, optional native autoejection patch, HTTP artifact route를 통과한 뒤 start gate에서 `BAMBU_START_DRY_RUN`, operator confirmation, Guardian approval, front path/door, ramp/bin, toolhead cover, release surface, supervised first run blocker로 차단되는 것이 정상이다.
- 같은 HTTP artifact route에서 operator confirmation, Guardian approval, dry-run off, front path/door, ramp/bin, toolhead cover, release surface/profile, supervised first run 값을 모두 명시하면 `Pre-start Check`는 `ready_to_publish_not_started`까지 도달한다. 이 검증도 `published=false`, `will_publish=false`를 유지하므로 실제 motion 또는 MQTT publish 성공을 의미하지 않는다.
- `BAMBU_POST_EJECT_BED_NOT_CLEAR` gate는 실제 API 경로에서 확인됐다. `/api/printer/bed-clear`에 `bed_clear_required=true`, `bed_clear_verified=false`를 저장하면 같은 all-confirmed pre-start path에서도 start gate가 `BAMBU_POST_EJECT_BED_NOT_CLEAR`로 차단된다. 이후 `bed_clear_required=false`, `bed_clear_verified=true`를 저장하면 start gate가 다시 `ready_to_publish_not_started`로 풀린다. `.autoeject.*` artifact publish 경로는 bed-clear lock에 `remote_path`, `subtask_name`, source/patched artifact path와 sha256, sidecar manifest path, MQTT publish sequence/topic, post-publish status, camera snapshot reference를 같이 저장해야 한다. 이 검증 역시 `published=false`, `will_publish=false` 또는 fake MQTT path만 사용했고 실제 motion을 의미하지 않는다.
- `Mark Bed Clear`는 `bed_clear_verified`와 camera evidence를 갱신하되, 앞선 `.autoeject.*` publish에서 저장된 remote path, source/patched hash, manifest, publish sequence/topic, post-publish status를 지우면 안 된다.
- 실제 장비 통신 중 FTPS가 `421 too many connections` 계열로 응답하면 generic network failure가 아니라 `BAMBU_FTPS_TOO_MANY_CONNECTIONS`로 표시한다. 이 blocker는 MQTT/video plane 성공 여부와 별도로 transfer path readiness를 막는다.
- 현재 코드 smoke에서 임시 FastAPI 서버 기준 `/printer`는 `HTTP 200`과 3DP Printer GUI HTML을 반환했고, HTML 안에 `Bambu LAN Connection`, `Bambu G-code Autoejection`, `Pre-start Check`, `Video Status`, `Publish Start`, `Mark Bed Clear`, `Validate G-code Preview` control text가 존재했다. `/api/printer/status?mode=test`는 BambuLab X2D active profile과 device screen payload를 반환했고 비물리 status 조회에서 publish/start intent가 생기지 않는 것을 확인했다. 같은 서버에서 Selenium/Firefox headless 1920x1080 렌더링은 상단 console의 `Video Status`, `Pre-start Check`, camera placeholder와 autoejection section의 validation controls, standalone left/center/right artifact controls, `Mark Bed Clear`가 실제 DOM에 표시되는 것을 확인했다. 브라우저 `Validate Center` 경로는 validate-only API를 호출해 summary/detail/body에 validation pass, source plate, object bounds, sweep path를 표시했고 raw G-code line은 표시하지 않았으며 `.autoeject.*` artifact 파일 수가 증가하지 않았다. 이 항목은 rendered GUI smoke와 HTML/API smoke evidence이며 actual publish/ejection 성공으로 간주하지 않는다.

### 13.1 2026-06-16 외부 사례 재대조 후 보강된 contract

Reddit, GitHub, YouTube, Bambu community, Looprint, 3DQue, Infinity Flow, OrcaSlicer proposal, OpenBambuAPI, ha-bambulab 사례를 다시 대조한 결과, ATR에서 구현해야 할 범위와 구현하지 말아야 할 범위를 아래처럼 고정한다.

| 외부 사례 | 확인한 사실 | ATR contract |
| --- | --- | --- |
| OpenBambuAPI MQTT | Local MQTT는 `{printer_ip}:8883`, TLS, username `bblp`, LAN access code 기반이며 `report`와 `request` topic이 분리된다. | `BambuMqttConfig`는 기본 8883/TLS/LAN-code contract를 유지하고, start publish는 status snapshot과 별도 evidence로 저장한다. |
| Home Assistant / ha-bambulab | FTPS upload와 MQTT start는 분리된다. AMS가 있으면 sliced file과 AMS slot mapping을 맞추는 UX가 어렵다. | `Transfer artifact`, `Publish Start`, `Post-publish observation`, `AMS mapping gate`를 분리한다. AMS 사용 시 mapping이 없으면 start를 막는다. |
| Looprint | 이미 sliced 된 G-code/3MF를 받아 cooldown, push-off, loop logic을 삽입하고 반복 출력한다. 아직 beta이며 unattended run을 권장하지 않는다. | ATR도 sliced artifact 후처리 방식을 쓰되, unattended-ready로 표기하지 않는다. `validate_only`, `standalone artifact`, `guarded publish`를 분리한다. |
| 3DQue Bambu X1/P1 guide | 자동 배출은 center-front one-part placement, Y rear clearance, Z min/max, door/front clearance, release surface에 크게 의존한다. | validator는 object bounds, build envelope, rear/front clearance, object height, one-object assumption을 gate로 검사한다. operator checklist에는 door/front path, ramp/bin, toolhead cover, release surface를 포함한다. |
| Infinity Flow P1S guide | end G-code에 다중 높이 sweep을 추가하고 purge line이 남지 않게 별도 purge block 또는 profile 조정이 필요하다고 설명한다. | Tail generator는 object height 기반 multi-sweep을 기본으로 두고, skirt/brim/raft/purge residue risk를 blocker 또는 warning으로 남긴다. |
| OrcaSlicer auto-ejection proposal | visual preview, smart plate management, adhesion/material compatibility, minimum part height, damage-risk abort가 중요하다. | 3DP GUI는 validation summary와 evidence를 보여주되 raw G-code dump를 표시하지 않는다. 물리 publish 전에는 simulation/preview 성격의 evidence를 남긴다. |
| 3DQue/Tom's Hardware enclosed-printer article | Bambu CoreXY enclosure는 door와 bed surface가 핵심 제약이다. 별도 door opener와 low-adhesion surface를 쓰는 commercial workflow도 존재한다. | Native G-code ejection만으로 무인 반복 운전을 기본 활성화하지 않는다. door/front path와 release surface evidence 없이는 next-job gate를 막는다. |

이 대조 결과로 `BambuLabBridge`의 책임은 단순 command relay가 아니라 다음 5개 plane을 동시에 유지하는 것이다.

1. `artifact plane`: BambuStudio/Orca/manual sliced artifact, `.gcode.3mf` internal plate path, source/patched hash
2. `validation plane`: object bounds, push envelope, residual skirt/brim/purge risk, unexpected homing detection
3. `transport plane`: FTPS 또는 HTTP artifact route, printer-fetch readiness, transfer failure code
4. `runtime plane`: MQTT publish ack, fresh `gcode_state`/progress/subtask observation, camera snapshot
5. `bed-clear plane`: post-ejection bed-clear lock, operator/camera evidence, next-job unlock

따라서 `published=true`는 physical ejection success가 아니다. `published=true`는 MQTT command accept 또는 fake-MQTT test evidence일 뿐이며, 실제 성공은 `post_publish_status`, camera/operator observation, bed-clear evidence가 결합될 때만 인정한다.

### 13.2 시스템 설명 문서 반영 범위

14번 개선안을 구현하거나 수정할 때는 개선안 문서만 갱신하지 않는다. 시스템 설명 문서도 아래 범위까지 같은 의미로 맞춘다.

- `docs/runtime/architecture.md`: 3DP execution boundary와 evidence plane
- `docs/runtime/closed_loop_and_pages_reference.md`: Live/Test/Virtual bridge가 같은 API contract를 쓰는 방식
- `docs/gui/gui.md`: 3DP Device Workspace 버튼, disabled state, validation evidence, camera/status 유지 규칙
- `docs/hardware/bambulab_x2d_device_bridge_runtime_guideline.md`: Bambu operator/runtime guideline
- `docs/tutorials/device_workspace_3dp_usage.ko.md`: operator 사용법과 실제 장비 검증 runbook
- `docs/tutorials/user_manual.ko.md`, `docs/tutorials/user_manual.en.md`: 일반 사용자가 보는 device workspace 설명
- `REQUIREMENTS.md`: Bambu Studio/OrcaSlicer, MQTT, FTPS, ffmpeg/camera, Selenium visual QA 의존성

문서 업데이트의 원칙은 "구현했다"가 아니라 "어떤 evidence를 어떤 단계에서 확인해야 하는지"를 설명하는 것이다. 실제 physical ejection 검증이 끝나기 전에는 system docs도 `production-safe`, `unattended-ready`, `physical success confirmed` 같은 표현을 쓰지 않는다.

시스템 설명 문서의 완료 판정은 `scripts/audit_bambu_autoejection_completion.py`와 같은 기준을 따른다. 이 감사 스크립트는 프린터를 움직이지 않고 persisted proof package만 읽으며, 다음 evidence가 모두 있어야만 `complete_evidence_verified`를 반환한다.

- physical start precheck: camera/proxy, active Bambu profile, `published=false`, `will_publish=false`, `ready_to_publish_not_started`
- standalone center ejection: guarded publish, post-publish observation, before/after camera evidence, no collision/toolhead-cover/build-plate shift
- disposable live ejection: autoejection tail observed, object cleared, bed-clear lock recorded, source/patched hash and manifest evidence
- left/right lane: both lane artifacts validated/executed under the same gate with no validator blocker
- post-ejection bed-clear: camera/operator evidence and empty `blocking_code`
- next-job gate: `BAMBU_POST_EJECT_BED_NOT_CLEAR` cleared and printer state matches idle/ready

감사 실행 예:

```bash
./scripts/audit_bambu_autoejection_completion.py --write-template artifacts/printer/<run_id>/bambu/bambu_autoejection_physical_validation_<timestamp>.json --printer-profile-id bambulab_x2d_lab_01
./scripts/audit_bambu_autoejection_completion.py --proof-package artifacts/printer/<run_id>/bambu/bambu_autoejection_physical_validation_<timestamp>.json
./scripts/audit_bambu_autoejection_completion.py --latest
```

`--write-template`은 표준 scaffold만 만든다. 이 파일은 기본값이 fail-closed이므로 바로 감사하면 incomplete가 정상이다. 이 감사가 실패하면 14번 개선안은 incomplete로 남긴다. `published=true`, validator pass, HTTP route ready, MQTT ack, GUI 표시 성공은 각각 필요한 evidence일 수 있지만 단독 완료 기준은 아니다.

3DP Device Workspace는 같은 완료 기준을 GUI/API로 노출한다.

| Control/API | 요구 동작 | 금지 동작 |
| --- | --- | --- |
| `Build Fail-Closed Proof Template` / `POST /api/printer/bambu-autoejection-proof-template` | active Bambu provider 기준 proof JSON scaffold 생성, 기본 fail-closed blocker 포함 | MQTT publish, FTPS upload, camera capture, axis motion |
| `Run Completion Audit` / `POST /api/printer/bambu-autoejection-completion-audit` | proof package path 또는 latest package를 읽고 physical completion blockers 산출 | proof가 없는데 완료 처리, GUI success만으로 완료 처리 |

이 API들은 system docs와 GUI의 완료 표현을 강제하기 위한 감사 layer다. 실제 motion workflow가 아니라, 이미 수행한 supervised physical validation의 evidence를 읽는 도구다. 따라서 center standalone ejection image, disposable live ejection post-publish observation, patch manifest/source-patched sha256, left/right lane evidence, bed-clear evidence, next-job gate evidence가 빠지면 실패해야 한다.

실제 장비 검증 순서:

1. virtual patch artifact 생성
2. Bambu Studio/OrcaSlicer에서 patched artifact open 가능 여부 확인
3. standalone center ejection dry-run artifact 검증
4. small disposable object로 live ejection supervised test
5. left/right position test
6. post-ejection camera snapshot evidence 확인
7. 다음 job 차단/해제 gate 확인

실제 장비 검증 완료 기준:

| 단계 | 인정 기준 |
| --- | --- |
| physical start 전 상태 | `/printer` 또는 API에서 Bambu active profile, camera frame/proxy, `.autoeject.*` artifact, `ready_to_publish_not_started`, `published=false`, `will_publish=false`를 확인한다. |
| standalone center ejection | center standalone artifact를 guarded `Publish Start`로 실행하고, `published=true` 및 post-publish observation을 기록한다. 별도 camera/operator evidence로 object가 front-clearance/bin zone으로 이동했고 충돌, toolhead cover 이탈, build plate shift가 없음을 확인한다. |
| disposable object live ejection | small disposable print에서 autoejection tail 실행을 관찰한다. publish 직후 또는 job 완료 직후 bed-clear evidence가 `required=true`, `verified=false`로 잠겨 다음 job이 차단되어야 하며, remote path/source-patched hash/manifest/publish sequence/post-publish status/camera snapshot reference가 같이 남아야 한다. |
| left/right lane | left/right standalone artifact가 같은 gate로 실행되고, push lane과 object assumption이 실제 위치와 맞으며 validator blocker가 없어야 한다. |
| post-ejection bed-clear | `Video Status` 또는 camera/operator 확인 후 `Mark Bed Clear`를 수행한다. `memory/bambu_bed_clear_evidence.json` 또는 `/api/printer/bed-clear`에서 `blocking_code=""`와 camera snapshot reference를 확인한다. |
| next-job gate | bed-clear 해제 뒤 `Pre-start Check` 또는 `/api/printer/start-gate`가 `BAMBU_POST_EJECT_BED_NOT_CLEAR` 없이 실제 프린터 idle/ready 상태와 일치해야 한다. |

이 완료 기준이 충족되기 전에는 `published=true`나 validator pass를 실제 autoejection 성공으로 해석하지 않는다. `published=true`는 MQTT command accept evidence이고, physical success는 camera/operator observation과 bed-clear evidence가 결합돼야 인정한다.

브라우저/GUI 육안 검증:

- 3DP Device Workspace를 브라우저로 열어 `Pre-start Check`, `Video Status`, `Generate Patched Artifact`, `Validate Center`, `Mark Bed Clear` 흐름을 캡처한다.
- `Pre-start Check`가 진행 중일 때 관련 버튼이 callback 완료 전까지 disabled 되는지 확인한다.
- `Video Status`가 실패해도 이전 MQTT/device status 카드가 사라지지 않는지 확인한다.
- camera frame이 있으면 pre-start panel과 bed-clear evidence panel에 같은 snapshot reference가 표시되는지 확인한다.
- validation summary는 전체 G-code dump가 아니라 marker/object bounds/sweep path/blocker 위주로 접히는 UI인지 확인한다.

---

## 14. 아직 구현하지 말아야 할 것

- MQTT `gcode_line` 직접 motion을 기본 경로로 쓰지 않는다.
- Bambu profile을 Prusa route에 억지로 태우지 않는다.
- camera evidence 없이 자동으로 bed-clear를 true로 만들지 않는다.
- autoejection 실패를 Manipulation Agent 성공으로 숨기지 않는다.
- 실제 장비에서 unattended loop를 기본값으로 켜지 않는다.
- FarmLoop/Looprint/3DQue/PrintFlow의 G-code를 그대로 복사하지 않는다. 개념과 validation 요구사항만 반영한다.
- Bambu Studio/OrcaSlicer profile의 start/end G-code를 무조건 덮어쓰지 않는다. deterministic post-process patch를 우선한다.
- Bambu sidecar/Docker slicer를 필수 의존성으로 만들지 않는다. 로컬 slicer, sidecar, 수동 sliced artifact는 모두 같은 bridge contract로 연결한다.

---

## 15. 조사 근거 링크

Bambu/BambuStudio/통신:

- BambuStudio CLI command manual: https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage
- OpenBambuAPI MQTT notes: https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
- Bambu Lab LAN mode: https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode
- Bambu Lab printer network ports: https://wiki.bambulab.com/en/general/printer-network-ports
- Home Assistant community `project_file` command example: https://community.home-assistant.io/t/bambu-lab-x1-x1c-mqtt/489510/738
- SimplyPrint LAN-only / Developer Mode guide: https://help.simplyprint.io/en/article/bambu-lab-lan-only-mode-and-developer-mode-how-to-enable-xa0hch/
- SimplyPrint Bambu 3MF plate splitting: https://help.simplyprint.io/en/article/3mf-splitting-feature-bambu-lab-1qgdreg/
- ha-bambulab upload/start discussion: https://github.com/greghesp/ha-bambulab/discussions/307
- ha-bambulab `print_project_file` P1S issue: https://github.com/greghesp/ha-bambulab/issues/1293
- Bambuddy slow MQTT ack issue: https://github.com/maziggy/bambuddy/issues/1150
- Bambuddy server-side slicing sidecar: https://wiki.bambuddy.cool/features/slicer-api/
- Bambu third-party integration / Developer Mode: https://wiki.bambulab.com/en/software/third-party-integration
- BambuBoard LAN liveview / RTSPS setup notes: https://github.com/t0nyz0/BambuBoard/blob/main/VIDEO_STREAMING_SETUP.md

Autoejection / loop 사례:

- Looprint GitHub: https://github.com/NickiAndersen/looprint
- Reddit Looprint announcement: https://www.reddit.com/r/BambuLab/comments/1poqj8x/automated_multiloop_printing_for_bambu_lab/
- Fabbaloo Looprint article: https://www.fabbaloo.com/news/new-free-looprint-utility-enables-hands-free-batch-production
- OrcaSlicer batch auto-ejection proposal: https://github.com/OrcaSlicer/OrcaSlicer/discussions/7693
- OrcaSlicer auto eject/printfarm add-on issue: https://github.com/SoftFever/OrcaSlicer/issues/11046
- OrcaSlicer plate changer PR: https://github.com/OrcaSlicer/OrcaSlicer/pull/13177
- 3DQue Bambu X1/P1 auto-ejection guide: https://docs.3dque.com/docs/installation-guides/auto-ejection-kit-installation/Bambu-X1-P1/
- 3DQue Bambu slicing guide: https://docs.3dque.com/docs/getting-started/slicing-for-auto-ejection/bambu-lab-slicing-guide/
- Infinity Flow 3D Bambu P1S bed clearing guide: https://infinityflow3d.com/blogs/3d-printer-automation/3d-printer-auto-bed-clearing-bambu-p1s-example
- PrintFlow3D Bambu plate automation overview: https://printflow3d.com/pages/how-to-use-the-printflow3d-software
- FarmLoop A1/A1 Mini G-code page: https://3dfarmers.kit.com/farmloop
- Bambu community auto eject/repeat concept: https://forum.bambulab.com/t/auto-eject-repeat-print-concept/72761
- Bambu community project to remove parts: https://forum.bambulab.com/t/project-to-automatically-remove-parts-from-build-plate/17231
- Bambu enclosed-printer auto-ejection kit article: https://www.tomshardware.com/3d-printing/new-auto-ejection-tool-for-bambu-lab-print-farms-automatically-ejects-finished-3d-prints-from-the-machine-usd129-kit-includes-auto-door-opener-and-special-bed-surface-for-frictionless-part-ejection

Reddit/YouTube 사례:

- A1 Mini END G-code discussion: https://www.reddit.com/r/BambuLab/comments/1jfayjd/a1_mini_auto_eject_end_g_code/
- Auto eject G-code troubleshooting: https://www.reddit.com/r/BambuLab/comments/1erqr3i/auto_eject_gcode/
- A1 Mini FarmLoop failure: https://www.reddit.com/r/BambuLab/comments/1k7ffzl/a1_mini_auto_ejection_fail_build_plate_shifts/
- A1 Mini auto-eject success after design change: https://www.reddit.com/r/BambuLab/comments/1kob69u/automation_success_a1_mini_autoeject_working/
- Bambu MQTT project_file success-but-idle discussion: https://www.reddit.com/r/BambuLab/comments/1t9pbn8/bambu_p1s_mqtt_project_file_command_returns/
- Bambu P1P cooldown timeout/carbon rod concern: https://www.reddit.com/r/BambuLab/comments/144z4mx/part_1_auto_eject_on_bambu_p1p/
- Bambu print farm material/bed adhesion issue: https://www.reddit.com/r/BambuLab/comments/1eyw99x/auto_eject_for_print_farm/
- P1S motorized door/eject via G-code API discussion: https://www.reddit.com/r/BambuLab/comments/1jfv2of/i_built_an_autoeject_system_and_motorized_door/
- Factorian Designs P1/X1 automation video: https://www.youtube.com/watch?v=Vxj1ii6dPYo
- Factorian Designs P1S/P1P/X1C automation video: https://www.youtube.com/watch?v=7ec-NC-M-D0
- Factorian Designs A1/A1 Mini automation video: https://www.youtube.com/watch?v=SFd0sxN2eqk
- FarmLoop Stage 2 P/X auto door and plate bender video: https://www.youtube.com/watch?v=-kBrIGv4A2Q
- Generic auto-eject queue/loop video: https://www.youtube.com/watch?v=ejWIhWr_lZk
- Bambu automatic part ejection video: https://www.youtube.com/watch?v=uNFLK3T05lY
