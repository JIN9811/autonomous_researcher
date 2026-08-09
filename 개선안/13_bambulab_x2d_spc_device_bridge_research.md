# 13. Bambu Lab X2D 전환용 SPC Agent-Device Bridge 개선안

작성일: 2026-06-14
대상: `SpecimenMakingAgent`, `printer.prepare`, 3DP Device Workspace, Live GUI SPC report
범위: Bambu Lab X2D 전환 설계, 구현 반영 상태, live 검증 기록.

---

## 1. 결론

프린터를 Prusa MK4S에서 Bambu Lab X2D로 바꾸는 작업은 단순히 `printer_model` 문자열과 slicer 이름만 바꾸면 안 된다. 현재 런타임은 다음 Prusa 전용 가정에 강하게 묶여 있다.

- `PrusaSlicer -> G-code` 생성
- `PrusaLink HTTP/Digest` 기반 status/storage/upload/start
- USB storage path와 PrusaLink job/transfer polling
- Prusa MK4S bed-sweep autoejection G-code 정책

Bambu Lab X2D에서는 다음 구조가 더 맞다. 여기서 중요한 점은 Bambu가 Prusa의 fallback이 아니라는 것이다. 상위 bridge manager가 여러 printer profile을 보유하고, agent/operator가 선택한 printer profile에 맞는 adapter를 명시적으로 실행해야 한다.

```text
DesignAgent
  -> SpecimenMakingAgent
  -> printer.prepare tool contract 유지
  -> PrinterDeviceBridgeManager
       1. PrinterFleetRegistry에서 사용 가능한 printer profile 조회
       2. 기본 profile은 bambulab_x2d_lab_01
       3. operator/agent가 선택한 profile을 명시적으로 lock
       4. selected profile의 vendor adapter 실행
          - bambulab_x2d -> BambuBridge
          - prusa_mk4s   -> PrusaBridge
          - virtual      -> VirtualPrinterBridge
  -> BambuBridge 내부 workflow
       1. Bambu Studio/BambuSlicer CLI slicing
       2. sliced 3MF 또는 G-code artifact 검증
       3. Bambu LAN profile 검증: host, serial, access code, developer/LAN mode
       4. FTPS/Bambu Connect 계열 파일 전송
       5. MQTT report/request 기반 status/start/monitor/control
       6. LAN video stream 기반 live view 수집
       7. BambuSlicer Device 화면형 realtime state aggregate 생성
       8. evidence-rich fabrication digital thread 생성
  -> Vision/Manipulation/Equipment/Analysis/Knowledge/BO/Guardian handoff
```

권장 구현 방향은 `SpecimenMakingAgent`의 역할을 바꾸지 않고, `printer.prepare` 아래에 `PrinterDeviceBridgeManager` 계층을 추가하는 것이다. `device_bridges/prusa_bridge.py`와 같은 계층에 `bambu_bridge.py`를 추가하고, 상위 manager가 `printer_profile_id` 또는 default profile로 adapter를 선택한다. Prusa 전환은 fallback이 아니라 operator가 3DP GUI 또는 config에서 선택하는 명시적 전환이어야 한다.

---

## 2. 조사 근거 요약

| 항목 | 확인 내용 | 설계 반영 |
|---|---|---|
| X2D 장비 | Bambu Lab 공식 자료 기준 X2D는 flagship X Series 2세대이며 dual-nozzle, active chamber, AI monitoring 계열 기능을 제공한다. | printer profile은 `bambulab_x2d`, single/dual nozzle mode를 별도 설정으로 둔다. |
| X2D build volume | 공식 spec 검색 결과 기준 main nozzle 256x256x260 mm, auxiliary/dual nozzle 235.5x256x256 mm 계열이다. | manufacturability gate에 nozzle mode별 build envelope를 넣어야 한다. |
| X2D thermal/material | 공식 spec/FAQ 검색 결과 기준 300 C nozzle, 65 C heated chamber, 0.4 mm included nozzle, 0.2/0.4/0.6/0.8 mm supported nozzle가 확인된다. | PLA/TPMS 기본 profile과 engineering-material profile을 분리한다. |
| Bambu Studio CLI | BambuStudio Wiki에 `bambu-studio [OPTIONS] [file.3mf/file.stl...]`, `--load-settings`, `--load-filaments`, `--outputdir`, `--slice`, `--export-3mf` 등이 문서화되어 있다. | slicer runner는 command template 방식으로 두고, profile json을 명시적으로 관리한다. |
| LAN mode | Bambu Wiki는 LAN Mode가 local area network에서 slicer로 파일 전송/monitoring하도록 하는 기능이라고 설명한다. | cloud가 아니라 local bridge 기준으로 설계한다. |
| network ports | Bambu Wiki 검색 결과 기준 LAN mode MQTT는 TCP 8883, FTP/FTPS는 990 및 passive port range를 사용한다. | bridge preflight가 8883/990 reachability를 검사한다. |
| access code | Bambu Wiki는 access code 연결 시 printer IP와 access code 입력이 필요하다고 안내한다. | `memory/bambu_connection.json`에 host/serial/access_code를 저장하고 UI에서는 masked 처리한다. |
| MQTT local API | OpenBambuAPI는 local MQTT가 `{PRINTER_IP}:8883`, TLS, username `bblp`, password LAN access code, topics `device/{DEVICE_ID}/report` and `device/{DEVICE_ID}/request` 구조라고 정리한다. | MQTT client는 report subscribe와 request publish를 분리하고 sequence_id ack를 추적한다. |
| live video | Bambu 공식 network ports 문서 검색 결과 LAN mode video port가 MQTT와 별도로 존재하며, OpenBambuAPI는 X1/P2S/H2 계열 RTSPS `:322`, A1/P1 계열 JPEG stream `:6000` 구조를 정리한다. | `BambuVideoStreamClient`를 MQTT client와 분리하고, UI에서는 하나의 Device view로 합성한다. |
| multi-printer management | Bambu Farm Manager 공식 블로그는 local network에서 여러 printer를 realtime monitoring, batch control, smart queue로 관리하는 구조를 설명한다. | agent가 단일 printer가 아니라 bridge registry에서 여러 printer를 선택할 수 있게 한다. |
| print command | OpenBambuAPI는 `print.gcode_file` 명령과 `print.gcode_line` 명령 구조를 문서화한다. | start command는 firmware/X2D 검증 전까지 guarded experimental path로 둔다. |
| FTPS | OpenBambuAPI는 FTPS endpoint가 `ftps://{DEVICE_IP}:990`, implicit TLS, username `bblp`, password LAN access code라고 정리한다. | upload adapter는 FTPS/Bambu Connect 두 경로를 모두 고려하되 live write gate로 보호한다. |
| third-party integration | Bambu Wiki/Connect 문서는 Bambu Connect가 sliced G-code/3MF를 Bambu printer로 전송하는 통합 도구라고 설명한다. | 공식 지원 경로가 필요한 경우 Bambu Connect adapter를 우선 후보로 둔다. |
| ACS/Developer Mode | 최신 firmware에서는 third-party write action이 LAN-only + Developer Mode에 의존할 수 있다는 외부 integration 문서들이 있다. | live write preflight에 `developer_mode_confirmed` 또는 operator confirmation을 둔다. |
| X2D MQTT report | DrozmotiX ioBroker Bambu Lab X2D 이슈 #258에는 X2D `push_status` 원본에 `3D.layer_num`, `ams`, `device`, `gcode_state`, `hms`, `ipcam`, `job`, `lights_report`, `mc_percent`, `nozzle_temper`, `percent`, `sdcard`, `upload` 등이 포함되어 있다. | `normalize_bambu_report()`에서 진행률/레이어/온도/카메라/조명/AMS/upload/storage를 안정 필드로 정규화한다. |
| MQTT print start | Home Assistant 커뮤니티의 Bambu MQTT 정리글은 `project_file` 명령에서 `url`, `param`, `use_ams`, calibration flags 등을 구성한다고 설명한다. | start command는 나중에 Guardian 승인 + operator 승인 + verified artifact 이후 별도 guarded command로만 추가한다. |
| FTPS write path | Bambu 커뮤니티/오픈 문서에서는 모델·펌웨어별로 root, `/cache`, `/sdcard` 취급이 다를 수 있고 `553 Could not create file`이 저장소/권한/파일 문제에서 발생할 수 있음이 확인된다. | 단순 FTPS login/list를 upload-ready로 보지 않고, live `prepare`에서 marker write/delete probe를 통과해야 `can_upload=true`로 둔다. |
| HTTP artifact URL | Home Assistant 커뮤니티의 Bambu MQTT 정리글은 `project_file.url`이 `file:///...`뿐 아니라 locally hosted HTTP URL도 받을 수 있다고 설명한다. | FTPS write가 553으로 막힌 경우에도 HTTP artifact URL 후보를 guarded draft로 만들 수 있다. 단, 실제 publish/start는 printer reachability와 Guardian/operator approval 전까지 금지한다. |

참고 URL:

- https://github.com/DrozmotiX/ioBroker.bambulab/issues/258
- https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
- https://community.home-assistant.io/t/bambu-lab-x1-x1c-mqtt/489510/738
- https://forum.bambulab.com/t/how-to-remotely-print-custom-g-code-with-bambu-studio/80649
- https://blog.linux-ng.de/2024/06/10/bambu-labs-a1/

---

## 2.1 현재 구현/검증 상태

2026-06-14 기준 현재 코드에는 다음이 반영되어 있다.

- `device_bridges/bambu_bridge.py`
  - `PrinterDeviceBridgeManager`가 Bambu/Prusa profile을 명시 선택한다.
  - default profile은 `bambulab_x2d_lab_01`이다.
  - automatic fallback은 꺼져 있다.
  - `PrinterFleetMemory`가 active printer profile을 `memory/printer_fleet.json`에 저장한다.
  - request payload에 `printer_profile_id`가 있으면 그 값을 우선하고, 없으면 저장된 active profile을 사용한다.
  - 저장된 profile이 없거나 비활성/삭제된 profile이면 default Bambu profile로만 돌아가며, 실패한 Bambu job을 Prusa로 자동 전환하지 않는다.
  - Bambu MQTT report를 TLS 8883, username `bblp`, LAN access code 기반으로 읽는다.
  - DrozmotiX ioBroker X2D issue #258의 `push_status` 샘플을 기준으로 X2D 전용 telemetry를 정규화한다.
    - `print.3D`, `print.2D`: layer, calibration, ventobox, 2D makeability
    - `device`: bed/chamber/extruder/nozzle/plate 상태
    - `xcam`: spaghetti detector, first-layer inspector, print halt, buildplate marker detector
    - `hms`, `care`, `err2`, `fail_reason`: warning/error evidence
    - `ams`: AMS unit humidity/temp, tray color/type/remain
    - `ipcam`: live preview, RTSPS URL, BRTC/TUTK, timelapse storage
    - `queue`, `queue_sts`, `queue_number`, `queue_total`, `queue_est`: farm/queue 상태
    - `mc_action`, `mc_stage`, `mc_print_stage`, `mc_print_sub_stage`, `print_real_action`, `print_gcode_action`: firmware control/action 상태
    - `spd_lvl`, `spd_mag`: 현재 print speed override
    - `cooling_fan_speed`, `big_fan1_speed`, `big_fan2_speed`, `heatbreak_fan_speed`, `aux_part_fan`: fan 상태
    - `net.info`: 프린터가 보고하는 network interface raw integer IP를 little-endian IPv4로 decode
  - Bambu FTPS implicit TLS 990 storage probe를 수행한다.
  - FTPS data channel은 control TLS session을 재사용한다.
  - live `prepare`는 FTPS read probe와 write/delete marker probe를 분리한다.
  - FTPS marker probe는 root write 실패 시 `cache`, `sdcard`, `Metadata`, `data/Metadata` 후보를 순서대로 검사한다.
    - Bambu FTPS 서버는 slash가 포함된 `STOR cache/file`을 거부할 수 있으므로, bridge는 `CWD /cache` 후 basename만 `STOR`하고 marker를 즉시 `DELETE`한다.
    - 후보가 모두 실패하면 transfer는 `read_only`로 남고 `BAMBU_FTPS_WRITE_FAILED` 또는 `BAMBU_FTPS_NO_WRITABLE_PATH`를 보존한다.
  - 명시적 sliced artifact(`.gcode.3mf` 등)가 있을 때만 FTPS upload를 시도한다.
  - STL만 있는 상태에서 physical upload가 요청되면 `BAMBU_SLICED_ARTIFACT_REQUIRED`로 막는다.
  - MQTT `project_file` print command는 현재 실제 publish하지 않고 `bambu_project_file_command_draft.v1`로만 생성한다.
    - topic: `device/{serial}/request`
    - payload: `print.command=project_file`, `url=file:///...` 또는 검증 후보 `http://...`, `param=Metadata/plate_1.gcode`, AMS/calibration flags
    - `will_publish=false`, `start_enabled=false`, `requires_guardian=true`
    - 실제 start는 upload path/write gate, operator approval, Guardian approval이 모두 통과한 이후 별도 단계에서만 허용한다.
  - `BambuMqttReportClient.publish_project_file_command()`를 추가했다.
    - 실제 MQTT `project_file` command publish 경로다.
    - topic은 `device/{serial}/request`와 일치해야 하고, command는 `project_file`만 허용한다.
    - LAN access code는 publish 결과/GUI/API 응답에 반환하지 않는다.
  - `/api/printer/start-gate`를 추가했다.
    - 입력: `remote_path`, `subtask_name`, plate/AMS/calibration flags, `operator_confirmed`, `guardian_approved`, `dry_run`
    - 동작: `project_file` draft를 만든 뒤 live `printer.prepare` preprint gate와 device screen action을 다시 읽어 start 가능성을 판정한다.
    - 필수 조건: valid draft, fresh MQTT report, verified storage/transfer path, safe printer state, `device_screen.actions.can_start_print=true`, operator confirmation, Guardian approval
    - `dry_run=true`이면 항상 `BAMBU_START_DRY_RUN` blocker를 남기고 publish하지 않는다.
    - 모든 조건이 true이고 `dry_run=false`이면 `ready_to_publish=true`가 될 수 있지만, 이 endpoint 자체는 여전히 `will_publish=false`이다.
    - 실제 MQTT publish는 별도 explicit publish endpoint 또는 live workflow의 Guardian-approved 단계에서만 붙인다.
  - `/api/printer/start-publish`를 추가했다.
    - `/api/printer/start-gate`와 같은 gate를 다시 계산한다.
    - blocker가 하나라도 있으면 `BAMBU_START_GATE_BLOCKED`로 반환하고 MQTT publish를 호출하지 않는다.
    - gate 통과 조건: valid draft, fresh MQTT report, verified transfer path, safe printer state, `device_screen.actions.can_start_print=true`, operator confirmation, Guardian approval, `dry_run=false`.
    - 통과 시에만 `BambuMqttReportClient.publish_project_file_command()`를 호출해 실제 MQTT `project_file` command를 보낸다.
    - GUI의 `Publish Start` 버튼은 browser confirm을 거친 뒤 이 endpoint를 호출한다.
  - FTPS upload가 성공하면 uploaded remote path로 `project_file` draft를 붙인다.
  - FTPS가 `read_only`라도 `bambu_artifact_url`이 printer-reachable `http://` 또는 `https://` URL이면 HTTP artifact URL 기반 command draft를 만들 수 있다. 이 경우 `preprint_gate.state=http_artifact_ready_not_started`, `storage_transfer_path_verified=true`, `can_prepare_start_command=true`, `can_start_print=true`가 될 수 있다. 단, 이는 기술 start gate가 열린 상태라는 뜻이고 실제 publish는 `dry_run=false`, operator confirmation, Guardian approval이 모두 통과할 때만 가능하다.
  - `cache/specimen.gcode.3mf` 같은 일반 remote path는 HTTP artifact route가 아니다. plain remote path는 FTPS write/path verification을 우회하지 못하며, FTPS가 blocked면 `storage_transfer_path_verified=false`로 남는다.
  - MQTT가 연결되어 있으면 FTPS gate가 blocked여도 `preprint_gate.checks.mqtt_authenticated_or_virtual=true`로 남긴다. 각 gate evidence는 서로 섞지 않는다.
  - `BambuVideoStreamClient`를 추가했다.
    - MQTT report와 분리된 LAN video plane을 probe한다.
    - X/H 계열 후보 RTSPS `:322`를 먼저 확인하고, 실패하면 JPEG stream `:6000` 후보를 확인한다.
    - `ffmpeg`가 설치되어 있고 video port가 reachable이면 browser MJPEG proxy를 준비 상태로 표시한다.
    - LAN access code는 probe/proxy 내부에서만 사용하고 API 응답, GUI log, 문서에는 원문을 노출하지 않는다.
- `app/main.py`
  - `/api/printer/fleet`를 추가했다.
    - `GET`은 active/default/available printer profile과 selected printer summary를 반환한다.
    - `POST`는 operator가 선택한 active printer profile을 `memory/printer_fleet.json`에 저장한다.
    - 이 endpoint는 fallback 설정이 아니라 명시 선택 저장소다. `automatic_fallback=false`를 계약으로 유지한다.
  - `/api/printer/http-artifact-route`를 추가했다.
    - 입력: local sliced artifact path(`.gcode.3mf`, `.3mf`, `.gcode`)와 optional public base URL
    - 동작: artifact를 `artifacts/bambu_http_exports/<token>/<filename>`으로 복사하고 SHA-256/size를 기록한다.
    - 출력: 프린터가 접근 가능한 `http://<LAN-IP>:<port>/printer-artifacts/bambu/...` URL과 guarded `project_file` draft
    - 실행 조건: ATR 서버가 LAN 인터페이스에 바인딩되어 있어야 한다. 기본 설정은 `configs/system.yaml`의 `server.host=0.0.0.0`이며, Bambu에 넘기는 URL은 `localhost`가 아니라 ATR 서버 LAN IP를 사용한다.
    - `127.0.0.1`, `localhost`, unspecified host는 차단한다.
    - 실제 MQTT publish/start는 하지 않는다.
  - `/printer-artifacts/bambu/{token}/{filename}`를 추가했다.
    - export root 밖으로 path traversal을 허용하지 않는다.
    - route는 실제 sliced artifact bytes를 `FileResponse`로 제공한다.
  - Bambu provider에서는 `/api/printer/profile`의 `auto_ejection.enabled`를 print profile checkbox가 아니라 `manager.config.autoejection.status_payload()` 기준으로 반환한다.
  - `/api/printer/video-status`를 추가했다.
    - selected Bambu profile의 saved connection을 사용해 video port/proxy readiness를 확인한다.
    - 응답은 `video_status`, `device_screen.camera_panel`, selected printer metadata 중심이며 access code 원문을 포함하지 않는다.
  - `/api/printer/video-stream.mjpeg`를 추가했다.
    - `ffmpeg` subprocess를 사용해 Bambu RTSPS feed를 browser-compatible MJPEG로 변환한다.
    - Bambu profile이 아니거나 connection info/ffmpeg가 없으면 명시적 blocker로 실패한다.
- `mcp_tools/printer_tools.py`
  - 기존 `printer.prepare` tool name은 유지하고 bridge manager로 routing한다.
- `app/main.py`, `web/templates/printer.html`, `web/static/printer.js`
  - 3DP workspace 상단에 `Printer Fleet Selection` UI를 추가했다.
    - Bambu Lab X2D가 기본 선택이다.
    - Prusa MK4S는 dropdown에서 명시 선택해야만 active profile이 된다.
    - 저장 후 `/api/printer/connection`, `/api/printer/profile`, `/api/printer/status`가 같은 active profile 기준으로 다시 갱신된다.
  - 3DP workspace에서 Bambu connection/profile/status를 조회·저장한다.
  - Device 화면은 MQTT/FTPS/UPLOAD gate, job, progress, layer, thermal, AMS, camera, fleet 상태를 표시한다.
  - Device 화면은 X2D tool/plate 상태와 HMS/AI monitoring/wifi 요약을 표시한다.
  - Device 화면은 X2D `Speed / Queue` 요약과 `prepare_percent`, AMS status를 표시한다.
  - 상세 API payload에는 `device_screen.motion.speed`, `device_screen.motion.queue`, `device_screen.motion.control`, `device_screen.network`를 유지한다.
  - Device 화면용 사용자 집계 payload를 추가했다.
    - `device_screen.progress_panel`: job/progress/prepare/layer/source.
    - `device_screen.camera_panel`: live preview, stream kind, proxy state, blocker.
    - `device_screen.control_panel`: printer state, speed, queue, upload/start gate.
    - `device_screen.material_panel`: AMS slot count and first slots.
    - `device_screen.evidence_cards`: MQTT/transfer/video/safe-state evidence cards.
    - frontend는 위 payload를 렌더링하고, camera/material/progress 값을 임의 생성하지 않는다.
  - 이 필드는 start 가능 여부를 추론하기 위한 evidence로만 쓰며, 단독으로 MQTT publish/start를 허용하지 않는다.
  - `Video Status` 버튼을 추가했다.
    - live video 상태만 별도로 갱신한다.
    - `proxy_ready=true`이면 camera panel에 `/api/printer/video-stream.mjpeg` 이미지를 표시한다.
    - proxy가 준비되지 않으면 placeholder와 blocker를 표시한다.
  - `/api/printer/status?mode=test`는 virtual/health status를 유지한다.
  - `/api/printer/status?mode=live`는 health-only가 아니라 실제 preprint gate를 호출해 FTPS write/delete marker probe 결과를 화면에 반영한다.
  - `operator_actions`를 GUI까지 전달해 LAN-only, Developer Mode, sdcard/storage, FTPS write failure를 사용자가 바로 볼 수 있게 한다.
  - `Connection Confirmation` evidence board를 Bambu LAN Connection 아래에 추가했다.
    - saved connection memory와 최신 live status/SPC readiness response를 같이 사용한다.
    - LAN-only mode, Developer Mode, sliced artifact transfer, HTTP artifact route를 별도 카드로 표시한다.
    - `BAMBU_LAN_MODE_NOT_CONFIRMED`, `BAMBU_DEVELOPER_MODE_NOT_CONFIRMED`, `BAMBU_FTPS_WRITE_FAILED`, `BAMBU_STORAGE_TRANSFER_PATH_NOT_VERIFIED`, `BAMBU_HTTP_ARTIFACT_ROUTE_ACTIVE`를 사용자 조치로 매핑한다.
    - form checkbox만으로 upload-ready를 표시하지 않고, `/api/printer/status?mode=live` 또는 `/api/printer/spc-readiness`에서 온 backend evidence로 갱신한다.
  - `Upload Path Probe` 버튼은 root/cache/sdcard/Metadata/data/Metadata 후보에 작은 marker 파일을 쓰고 즉시 삭제하는 안전 probe만 수행한다. 출력 시작은 하지 않는다.
  - `Print Command Draft` 버튼은 현재 선택된 Bambu profile/SN 기준으로 MQTT start command 초안을 보여주지만 publish하지 않는다.
  - `Start Gate Check` 버튼을 추가했다.
    - 직전 `Prepare HTTP Artifact` 또는 upload path probe 결과를 기준으로 `/api/printer/start-gate`를 호출한다.
    - GUI는 `ready_to_publish`, `will_publish`, blocker 목록을 표시한다.
    - 버튼은 실제 출력 시작 버튼이 아니다. 현재 구현은 출력 시작 전 검증 화면이다.
    - `operator_confirmed`, `guardian_approved`, `dry_run` 값은 상단 start-gate checkbox에서 읽는다. frontend가 임의로 approval을 true로 만들지 않는다.
  - `Publish Start` 버튼을 추가했다.
    - `Start Gate Check`와 분리된 실제 MQTT publish 버튼이다.
    - browser confirm 이후 `/api/printer/start-publish`를 호출한다.
    - backend gate가 실패하면 버튼을 눌러도 publish되지 않는다.
    - 기본 UI 상태는 `dry_run=true`, approval unchecked이다. 실제 publish를 시도하려면 operator가 dry-run을 끄고 필요한 승인 evidence를 명시해야 한다.
  - `SPC Readiness` 버튼과 `/api/printer/spc-readiness`를 추가했다.
    - 목적은 Specimen Making Agent가 실제 프린터 handoff 전에 기다려야 하는 항목을 한 번에 보여주는 것이다.
    - backend는 기존 Bambu live `prepare`, start gate, autoejection gate를 다시 사용한다. GUI가 자체적으로 ready 값을 추정하지 않는다.
    - 반환 section은 `printer_connection`, `device_screen`, `preprint_gate`, `start_gate`, `autoejection_gate`로 나뉜다.
    - `ready_for_live_print`와 `autonomous_cycle_ready`를 분리한다. 출력 시작 직전 조건이 만족되어도 autoejection routine/vision evidence가 없으면 완전 자율 loop ready로 보지 않는다.
    - 이 endpoint도 실제 MQTT publish를 하지 않으며 항상 `will_publish=false`를 유지한다.
    - Start gate checkbox의 approval/dry-run 상태를 그대로 사용해 dry-run readiness와 final publish-ready check를 구분한다.
    - 사용자 화면용 `operator_summary`, `readiness_levels`, `next_actions`, `evidence`를 반환한다.
      - `operator_summary`: print gate/autonomous loop/publish policy/primary blocker 요약.
      - `readiness_levels`: connection, sliced-artifact transfer, operator/Guardian approval, MQTT publish command, autoejection loop를 분리한 사용자 중심 gate board.
      - `next_actions`: 실제 blocker, operator action, autoejection blocker code에서 만든 조치 카드.
      - `evidence`: device connection, job, preprint gate state, autoejection status.
      - frontend는 이 값을 그대로 렌더링하며 임의 readiness나 fake status를 생성하지 않는다.
      - `technical_ready_for_start=true`는 기술 gate가 통과했지만 approval/dry-run policy 때문에 publish가 막힌 상태를 사용자에게 구분해서 보여주기 위한 값이다.
    - SPC readiness 완료 시 frontend는 같은 응답의 `device_screen`으로 상단 Bambu Device Screen도 갱신한다. readiness panel과 evidence card가 서로 다른 stale 상태를 보여주면 안 된다.
    - 검증 결과:
      - HTTP artifact를 먼저 만들지 않은 기본 SPC check는 실제 Bambu MQTT는 connected이나 FTPS write가 blocked일 때 `BAMBU_FTPS_WRITE_FAILED`, `transfer=read_only`, `storage_verified=false`를 표시한다.
      - `/api/printer/http-artifact-route`가 만든 LAN-reachable HTTP URL은 backend가 동일 URL을 GET하고 sha256을 비교해 `server_fetch_probe.ok=true`를 반환할 때만 verified transfer evidence로 사용한다. 이 URL을 `remote_path`로 넘기면 `preprint_gate.state=http_artifact_ready_not_started`, `transfer=connected`, `storage_verified=true`가 된다.
      - 두 경우 모두 SPC readiness 자체는 MQTT publish를 하지 않으며, dry-run/operator/Guardian/start gate blocker가 남으면 `ready_for_live_print=false`다.
  - 3DP GUI의 Control Gate summary는 profile 정책값과 실제 bridge 상태를 구분한다.
    - `/api/printer/profile`만 반영된 초기 상태는 `policy upload=... start=...`로 표시한다.
    - `/api/printer/status?mode=live` 또는 `/api/printer/spc-readiness`가 반환되면 `actual upload=... start=...`로 바꾸고 backend `device_screen.actions` 값을 사용한다.
    - 이 구분이 없으면 live probe가 끝나기 전 profile 정책값을 실제 printer readiness처럼 오해할 수 있다.
  - profile의 `allow_ejection` 체크만으로 Bambu autoejection을 ready처럼 표시하지 않는다. UI의 auto-eject 상태는 bridge config의 검증된 provider 상태만 따른다.
  - `Bambu Autoejection Gate` 설정 UI와 `/api/printer/autoejection-config`를 추가했다.
    - operator가 `enabled`, `provider`, `verified_routine_id`, `pre_eject_vision_profile`, `post_eject_vision_profile`을 저장할 수 있다.
    - 저장 파일은 `memory/bambu_autoejection.json`이며 gitignore 대상이다.
    - 기본 배포 상태는 안전하게 disabled이고, local memory overlay가 있을 때만 `manager.autoejection_status()`가 configured 상태를 반환한다.
    - `Fill Manipulation Handoff Defaults`는 operator form을 채우는 shortcut일 뿐이며 저장, ready 판정, motion 실행을 하지 않는다. 검증된 provider/routine/vision evidence는 `Save Autoejection Gate`를 통해서만 저장된다.
    - Bambu autoejection은 provider 설정만으로 자율 루프 ready가 아니다. backend는 `memory/manipulation_agent_bridge.json`의 Manipulation Agent consumer profile도 함께 검증한다.
    - consumer readiness 조건은 `task_id=transfer_to_utm`, rollout-capable strategy(`pi05_lerobot_policy` 또는 `lerobot_policy`), `profile_id`, 그리고 존재하는 local policy path 또는 policy repo reference다.
    - `/api/printer/autoejection-status`, `/api/printer/autoejection-config`, `/api/printer/autoejection-test`, `/api/printer/spc-readiness`, `/api/printer/bambu-prestart-check`는 모두 `consumer_readiness`를 반환한다.
    - provider routine은 configured지만 consumer가 없거나 policy path가 없으면 `BAMBU_AUTOEJECTION_CONSUMER_NOT_READY`로 handoff/test를 막고, GUI는 `Manipulation consumer blocked`를 표시한다.
    - `SPC Readiness`의 `autoejection_gate`와 `autonomous_cycle_ready`는 이 저장된 설정을 실제로 소비한다.
    - 이 설정 저장은 hardware motion을 실행하지 않는다. 실제 autoejection test/run은 별도 provider routine과 Guardian/operator gate가 필요하다.
  - `/api/printer/autoejection-test`의 Bambu 분기를 수정했다.
    - Bambu가 configured 상태여도 Prusa MK4S bed-sweep G-code workflow로 떨어지지 않는다.
    - 대신 `bambu_autoejection_provider_handoff.v1` payload를 반환한다.
    - payload에는 provider, verified routine id, pre/post vision profile, object position/size, next owner/tool, consumer readiness/profile/policy reference가 포함된다.
    - 실제 provider executor가 붙기 전까지 이 endpoint는 `motion_started=false`를 명시한다.
    - GUI의 기본 Bambu profile에서는 left/center/right 버튼을 `Check Handoff`로 표시한다. Prusa profile을 명시 선택했을 때만 같은 위치 버튼이 `Autoeject`로 바뀌며 Prusa bed-sweep G-code route를 사용한다.
    - Bambu autoejection config 저장 후 GUI는 live printer status와 autoejection status를 다시 읽어 Control Gate/SPC readiness에 stale 상태가 남지 않게 한다.
    - Prusa bed-sweep autoejection은 Prusa profile이 명시 선택된 경우에만 Prusa workflow에서 실행된다.
  - `Prepare HTTP Artifact` 버튼을 추가했다.
    - 사용자가 `Bambu Sliced Artifact Path`를 입력하면 backend가 실제 파일을 HTTP route로 export한다.
    - optional `Public Base URL`을 넣을 수 있다. 비워두면 bridge가 printer host로 라우팅되는 local interface IP를 감지한다.
    - 성공 후 `Print Command Draft`는 자동으로 직전 HTTP artifact URL을 사용한다.
- `device_bridges/bambu_bridge.py`, `app/main.py`, `web/templates/printer.html`, `web/static/printer.js`
  - `BambuStudioSlicerRunner`와 `/api/printer/bambu-slice-artifact`를 추가했다.
  - 3DP GUI에는 `Bambu Source STL / 3MF Path` 입력과 `Slice Bambu Artifact` 버튼이 있다.
  - active profile이 Bambu일 때만 실행되고, source는 실제 로컬 `.stl` 또는 `.3mf` 파일이어야 한다.
  - 실행 command는 Bambu Studio CLI를 `--slice 0 --arrange 1 --ensure-on-bed --outputdir <artifact-dir>` 형태로 호출하고, 필요하면 `--load-settings`, `--load-filaments`, extra args를 추가한다.
  - 결과는 실제 생성된 `.gcode`, `.3mf`, `.gcode.3mf` 중 하나의 경로, size, sha256, command preview, stdout/stderr tail을 반환한다.
  - 이 버튼/API는 slicing artifact 생성만 수행한다. FTPS upload, HTTP route export, MQTT publish, print start는 수행하지 않는다.
- `app/main.py`, `web/templates/printer.html`, `web/static/printer.js`
  - `/api/printer/bambu-prestart-check`와 3DP GUI `Pre-start Check` 버튼을 추가했다.
  - 이 route는 사용자 관점의 출력 직전 checklist이며 실제 backend step을 순차 실행한다.
    1. source STL/3MF가 있으면 Bambu Studio CLI로 slicing
    2. sliced artifact를 HTTP route로 export하고 sha256/fetch proof 확인
    3. guarded start gate 계산
    4. SPC readiness report 생성
    5. configured Bambu autoejection handoff evidence 표시
  - 모든 step은 실제 API/bridge 결과를 사용하고, `will_publish=false`, `published=false`를 유지한다.
  - `ready_to_publish=true`는 출력 시작 직전 gate가 기술적으로 통과했다는 뜻이며, MQTT `project_file` command는 `Publish Start`에서만 별도 승인 후 보낼 수 있다.
- `agents/specimen_agent.py`, `app/controller.py`, `web/static/planning.js`
  - Specimen Making Agent가 Bambu bridge 결과의 `selected_printer`, `device_screen`, `preprint_gate`, `readiness_levels`, `operator_actions`, `autoejection`을 `fabrication_report.printer_runtime`과 `specimen_agent_report.spc_readiness`에 보존한다.
  - Live GUI compact 단계가 위 필드를 삭제하지 않고 chat/report payload로 전달한다.
  - Live GUI runtime card는 `PrusaSlicer Settings` / `PrusaLink / Bridge` 같은 고정 제목 대신 `Slicer / Artifact Settings`와 `Printer Bridge / SPC Readiness`를 사용한다.
  - active profile이 Bambu이면 Bambu device action, SPC readiness level, start/preprint blocker, autoejection handoff를 표시하고, Prusa이면 기존 PrusaLink transport/storage/upload/start evidence를 보조 정보로 표시한다.
- `configs/devices.yaml`
  - Bambu X2D를 default profile로 두고, Prusa MK4S는 명시 전환 가능한 별도 profile로 남긴다.

실제 프린터 검증 결과:

```text
host=192.0.2.42
serial=20PTEST000001
provider=bambulab_x2d
mqtt=connected
ftps_read=ok
ftps_write=blocked
failure_code=BAMBU_FTPS_WRITE_FAILED
ftps_error=553 Could not create file.
can_upload=false
can_start_print=false
rtsp_url_reported=true
video_322_rtsps=reachable
video_proxy=ready_when_ffmpeg_installed
sdcard=false
internal_storage_free=about 928 MB
upload_path_probe=BAMBU_FTPS_NO_WRITABLE_PATH
path_candidates=root:553,cache:553,sdcard:553,Metadata:553,data/Metadata:553
```

해석:

- 프린터 MQTT report 수집은 정상이다.
- FTPS 로그인 및 목록 조회도 가능하다.
- 현재 저장소 root에는 entry가 없고, root write/delete marker probe는 `553 Could not create file`로 실패한다.
- 따라서 현재 상태를 “출력 직전 upload-ready”로 보지 않는다.
- GUI에서는 `FTPS: read_only`, `UPLOAD: blocked`, `BAMBU_FTPS_WRITE_FAILED`가 보여야 한다.
- 현재 `memory/bambu_connection.json`의 `lan_mode_confirmed`, `developer_mode_confirmed`는 false로 저장되어 있다.
- 다음 단계는 프린터 화면에서 LAN-only/Developer Mode를 켜고 connection setting에 저장한 뒤, 같은 live gate를 다시 실행해 write probe를 재검증하는 것이다.
- 그래도 553이 유지되면 Bambu Studio/Bambu Connect가 실제로 쓰는 원격 경로 또는 HTTP/MQTT `project_file` 경로를 확정해야 한다.
- HTTP URL path를 쓰는 경우에는 로컬 서버 URL이 프린터 네트워크에서 접근 가능한 non-loopback 주소여야 한다. `127.0.0.1` 또는 `localhost` URL은 프린터 관점에서 접근 불가이므로 실제 publish 금지 대상이다.
- `Upload Path Probe`는 현재 모든 기본 후보 경로에서 `553 Could not create file`을 반환한다. 따라서 현 상태의 차단은 단순히 root 대신 cache를 써야 하는 문제로 보기 어렵고, local write/control 권한 또는 firmware storage policy 쪽을 먼저 확인해야 한다.

2026-06-14 GUI QA:

```text
route=/printer
action=Live Status
rendered=FTPS: read_only, UPLOAD: blocked, RTSPS stream reported, sdcard=false, 928 MB free
screenshot=/tmp/atr_bambu_printer_gui_readonly.png

route=/printer
action=Video Status
api=/api/printer/video-status
behavior=probes Bambu LAN video plane independently from MQTT status
result=RTSPS :322 reachable, stream_kind=rtsps, proxy_ready=true after ffmpeg install
proxy=/api/printer/video-stream.mjpeg
secret_policy=LAN access code never appears in API response or GUI log

route=/printer
action=Upload Path Probe
rendered=root/cache/sdcard/Metadata/data/Metadata candidates all failed, UPLOAD: blocked
screenshot=/tmp/atr_bambu_upload_path_probe_gui.png

route=/printer
action=Prepare HTTP Artifact -> Print Command Draft
server=uvicorn --host 0.0.0.0 --port 18080
artifact=/home/jin/autonomous_researcher/artifacts/bambu_sliced/qa_specimen.gcode.3mf
generated_url=http://192.168.50.146:18080/printer-artifacts/bambu/<token>/qa_specimen.gcode.3mf
fetch=HTTP 200, byte-for-byte match with local artifact
draft=project_file, url=http://192.168.50.146:18080/..., will_publish=false
screenshot=/tmp/atr_bambu_http_artifact_route_gui.png

route=/printer
action=Start Gate Check
api=/api/printer/start-gate
behavior=builds project_file draft, rechecks live preprint gate, reports blockers
publish=false
default_blockers=BAMBU_START_DRY_RUN,BAMBU_OPERATOR_CONFIRMATION_REQUIRED,BAMBU_GUARDIAN_APPROVAL_REQUIRED plus any live bridge blockers

route=/printer
action=SPC Readiness
api=/api/printer/spc-readiness
behavior=aggregates Bambu live prepare result, start gate, device screen, and autoejection gate for Specimen Making Agent handoff
publish=false
sections=printer_connection,device_screen,preprint_gate,start_gate,autoejection_gate
ready_flags=ready_for_live_print,autonomous_cycle_ready

route=/printer
action=Save Autoejection Gate
api=/api/printer/autoejection-config
behavior=saves operator-verified provider/routine/pre-vision/post-vision evidence to memory/bambu_autoejection.json
motion=false
effect=updates /api/printer/autoejection-status and /api/printer/spc-readiness autoejection_gate
```

---

## 3. 현재 프로젝트와 맞는 전환 원칙

### 3.1 바꾸지 말아야 할 것

- top-level stage는 추가하지 않는다. `printer`, `slicer`, `bambu` stage를 만들지 않는다.
- `SpecimenMakingAgent -> printer.prepare -> post-Specimen tail` 구조를 유지한다.
- Live/Test/Live GUI test mode의 의미를 유지한다.
- `printer.prepare` tool name을 바꾸지 않는다.
- LLM이 임의 G-code를 직접 생성하거나 MQTT command를 직접 작성하게 하지 않는다.
- connection secret을 docs, git, GUI log, chat message에 노출하지 않는다.

### 3.2 바꿔야 할 것

- `PrusaBridge` 전용 workflow 위에 `PrinterDeviceBridgeManager` 계층을 추가한다.
- bridge manager는 여러 printer profile을 등록하고, 기본값은 Bambu X2D로 둔다.
- Prusa는 fallback이 아니라 profile 선택으로 전환 가능해야 한다.
- slicer section은 선택 profile에 따라 `Bambu Studio/BambuSlicer CLI` 또는 `PrusaSlicer`로 바뀐다.
- Bambu printer status는 REST polling 중심이 아니라 MQTT report stream 중심으로 표시한다.
- Bambu live view는 MQTT가 아니라 별도 LAN video stream plane으로 취급하고, MQTT status와 합쳐 BambuSlicer Device 화면형 state를 만든다.
- upload/start는 PrusaLink HTTP endpoint가 아니라 FTPS/Bambu Connect + MQTT start command 후보로 분리한다.
- autoejection은 X2D에서 동일하게 재사용하면 안 된다. X2D용 자동 배출 메커니즘은 별도 하드웨어/공식 기능 확인 전까지 `unsupported/deferred`로 둔다.

---

## 4. 권장 backend 구조

### 4.1 printer fleet / bridge manager 계층

`device bridge`가 제대로 된 역할을 하려면 agent가 특정 장비 구현에 직접 묶이면 안 된다. `SpecimenMakingAgent`는 `printer.prepare`만 호출하고, 그 아래에서 bridge manager가 어떤 printer를 쓸지 결정해야 한다.

```text
mcp_tools/printer_tools.py
  printer.prepare(payload)
    -> PrinterDeviceBridgeManager.prepare(payload)
       -> PrinterFleetRegistry.list_profiles()
       -> PrinterProfileSelector.resolve(payload.printer_profile_id, config.default_profile_id)
       -> selected_profile.lock_for_run(run_id, specimen_id)
       -> VendorBridgeAdapter.prepare(selected_profile, payload)
```

필수 원칙:

- default printer profile은 `bambulab_x2d_lab_01`로 둔다.
- Prusa 전환은 fallback이 아니라 `printer_profile_id=prusa_mk4s_lab_01` 같은 명시 선택이다.
- automatic fallback은 금지한다. 실패한 Bambu job이 몰래 Prusa로 넘어가면 실험 조건과 traceability가 깨진다.
- agent는 bridge manager에서 `available_printers`, `capability`, `busy/idle`, `material`, `build_volume`, `live_view_available`, `slicer_profile`을 조회할 수 있어야 한다.
- selected profile은 run 단위로 lock되어야 한다. 한 cycle 중간에 printer가 바뀌면 digital thread가 깨진다.

### 4.2 권장 fleet config shape

```yaml
devices:
  printer:
    default_profile_id: bambulab_x2d_lab_01
    allow_automatic_fallback: false
    connection_memory_path: memory/printer_fleet.json
    profiles:
      bambulab_x2d_lab_01:
        provider: bambulab_x2d
        label: Bambu Lab X2D - Lab 01
        enabled: true
        priority: 10
        capabilities:
          slicer: bambu_studio_cli
          transfer: [ftps, bambu_connect]
          telemetry: mqtt
          live_view: lan_video_stream
          nozzle_modes: [main, auxiliary, dual]
          build_volume_main_mm: [256, 256, 260]
          build_volume_dual_mm: [235.5, 256, 256]
      prusa_mk4s_lab_01:
        provider: prusa_mk4s
        label: Prusa MK4S - Lab 01
        enabled: true
        priority: 5
        capabilities:
          slicer: prusa_slicer
          transfer: prusalink_http
          telemetry: prusalink_rest
          live_view: none
```

### 4.3 provider routing

```text
PrinterDeviceBridgeManager
  -> selected profile provider
     - bambulab_x2d: BambuBridge
     - prusa_mk4s: existing PrusaBridge
     - virtual_bambu: deterministic virtual Bambu workflow
     - virtual_prusa: deterministic virtual Prusa workflow
```

### 4.4 Bambu workflow 내부 모듈

```text
PrinterFleetRegistry
  - printer profiles 목록 관리
  - default_profile_id 관리
  - profile별 capability/readiness 조회
  - run 단위 selected printer lock 관리

PrinterProfileSelector
  - operator 선택, experiment constraint, availability를 반영해 profile 결정
  - 자동 fallback 금지
  - 선택 불가 시 operator attention 생성

BambuBridgeConfig
  - mode: test | live
  - provider: bambulab_x2d
  - profile_id: bambulab_x2d_lab_01
  - connection_memory_path: memory/printer_fleet.json 또는 memory/bambu_connection.json
  - live gates: allow_status, allow_upload, allow_start_print, allow_cancel_pause, allow_live_view
  - slicer: BambuStudioRunner config
  - mqtt: host/port/tls/topic/timeout/retry config
  - video: rtsps/tcp-jpeg stream config
  - transfer: ftps | bambu_connect | manual_drop | virtual

BambuConnectionMemory
  - host
  - serial
  - access_code_ref or masked access_code
  - lan_mode_confirmed
  - developer_mode_confirmed
  - printer_name
  - model
  - preferred_transfer

BambuStudioRunner
  - STL/3MF input validation
  - machine/process/filament profile json loading
  - --slice, --export-3mf, --outputdir command generation
  - sliced artifact metadata extraction

BambuArtifactValidator
  - file exists/hash/size
  - extension policy: .3mf, .gcode, .gcode.3mf depending selected transfer path
  - no arbitrary operator-injected G-code
  - specimen_id/run_id embedded metadata check when possible

BambuMqttClient
  - TLS 8883 connection
  - username bblp, password access code
  - subscribe device/{serial}/report
  - publish device/{serial}/request
  - sequence_id tracking
  - report normalization
  - Device 화면용 realtime printer state snapshot 생성

BambuVideoStreamClient
  - MQTT와 분리된 LAN video stream plane
  - X/H 계열 후보: RTSPS :322 stream
  - P/A 계열 후보: TCP JPEG :6000 stream
  - X2D 실제 video endpoint는 bench validation으로 확정
  - frame snapshot, live proxy URL, frame age, error state 반환

BambuDeviceScreenAggregator
  - MQTT normalized state + video stream + job timeline + transfer state 결합
  - BambuSlicer Device 화면처럼 status, temperatures, progress, camera, controls를 한 payload로 제공

BambuFileTransfer
  - FTPS implicit TLS upload candidate
  - Bambu Connect adapter candidate
  - dry-run virtual transfer fixture

BambuPrintJobManager
  - preflight idle/ready state
  - upload/start/monitor/pause/cancel wrappers
  - timeout/retry/backoff
  - final state normalization

BambuEvidenceRecorder
  - bridge_comm_log.jsonl
  - mqtt_report_tail.jsonl
  - video_snapshot_manifest.jsonl
  - sliced artifact manifest
  - print job timeline
  - normalized status snapshots
  - selected printer profile lock record
```

---

## 5. MQTT + realtime device screen 설계

### 5.1 connection fields

`memory/bambu_connection.json` 권장 shape:

```json
{
  "host": "192.168.x.x",
  "model": "Bambu Lab X2D",
  "serial": "REQUIRED_DEVICE_SERIAL",
  "printer_name": "x2d-lab-01",
  "auth": {
    "mode": "lan_access_code",
    "username": "bblp",
    "access_code": ""
  },
  "lan_mode_confirmed": false,
  "developer_mode_confirmed": false,
  "transfer": {
    "preferred": "ftps",
    "ftps_port": 990,
    "mqtt_port": 8883
  },
  "live_view": {
    "enabled": true,
    "preferred": "auto",
    "rtsps_port": 322,
    "jpeg_stream_port": 6000
  },
  "notes": "Secrets must stay local and masked in GUI/logs."
}
```

### 5.2 topics

```text
report topic  = device/{serial}/report
request topic = device/{serial}/request
```

### 5.3 normalized status

MQTT report payload는 printer/firmware별로 field가 달라질 수 있으므로 내부 상태는 아래처럼 표준화한다.

```json
{
  "bridge": "bambulab_mqtt",
  "connection": "connected|disconnected|auth_failed|timeout",
  "printer_state": "idle|preparing|slicing|uploading|starting|printing|paused|finished|failed|cancelled|unknown",
  "progress_percent": 0,
  "bed_temp_c": null,
  "nozzle_temp_c": null,
  "chamber_temp_c": null,
  "active_nozzle": "main|auxiliary|unknown",
  "job_name": "",
  "remaining_time_sec": null,
  "raw_report_ref": "artifact path"
}
```

### 5.4 video/live-view policy

영상은 MQTT payload 안에서 직접 전달되는 것으로 가정하지 않는다. 정확한 설계는 다음처럼 분리한다.

```text
MQTT plane
  - status, temperatures, progress, job metadata, command ack

Video plane
  - camera live stream or snapshot stream
  - LAN video port / RTSP(S) / TCP JPEG stream candidate

Device screen aggregate
  - MQTT state + video frame + transfer state + controls를 하나의 UI payload로 결합
```

BambuSlicer Device 화면과 유사하게 만들려면 Live GUI/3DP GUI에는 다음 card가 필요하다.

- selected printer dropdown: X2D/Prusa/virtual profile 선택
- live camera tile: frame age, connection status, pause overlay
- printer state strip: idle/heating/printing/paused/error
- temperature gauges: nozzle/bed/chamber
- job progress bar: percent, remaining time, current layer if available
- control buttons: start/pause/resume/cancel, live gate 상태 반영
- material/AMS/nozzle panel: main/auxiliary nozzle와 filament 상태
- event timeline: MQTT report, upload, start ack, error, operator attention


### 5.4.1 사용자 제공 Bambu Device 화면 reference mapping

보존한 reference asset:

```text
개선안/reference_assets/bambulab_device_screen_20260614.png
```

이 화면은 Bambu Studio/BambuSlicer의 `Device` 탭에 가까운 구성이다. 우리 Live GUI와 3DP Device Workspace는 이 화면의 배치를 그대로 복제하기보다, 각 요소가 실제 bridge data source에 연결되는지 우선해야 한다.

| Reference 화면 영역 | 사용자에게 보여야 하는 의미 | backend source | fake-data policy |
|---|---|---|---|
| 상단 tab: Prepare/Preview/Device/Project/Calibration/Filament Manager | 현재 operator가 장비 상태/제어 화면을 보고 있음 | 3DP workspace route state, selected printer profile | static label은 가능. 상태/장비값은 실제 source 없으면 표시 금지 |
| 좌측 printer selector `3DP-20P-425` + Wi-Fi icon | 선택된 printer와 연결 상태 | `PrinterFleetRegistry`, `BambuMqttClient.connection_status`, network preflight | 연결 미확인 시 green online icon 금지 |
| 좌측 Status | printer의 normalized 상태 요약 | MQTT report aggregator | MQTT 미연결 시 `status unavailable` |
| 좌측 Storage | printer storage/file transfer 상태 | FTPS listing, Bambu Connect adapter, transfer manifest | listing 불가 시 파일 목록 fake 금지 |
| 좌측 Update | firmware/update 상태 | 공식/로컬 API 확인 가능 시 read-only source | source 없으면 `not implemented` |
| 좌측 Assistant(HMS) | Bambu HMS/diagnostic/incident feed | MQTT HMS/error reports, bridge incident parser | HMS field 미검증 시 빈 정상상태 표시 금지 |
| 중앙 Camera | 실제 chamber camera live view | `BambuVideoStreamClient` live frame or snapshot proxy | video 미연결 시 placeholder + reason 표시 |
| 중앙 camera controls | snapshot/fullscreen/record-like controls | local UI control + video proxy state | 실제 backend 없는 control button 비활성화 |
| 중앙 Printing progress | 현재 job name/progress/layer/remaining time | MQTT job report, slicer estimate, bridge job manager | 진행률 추정값이면 `estimated` badge 필요 |
| 우측 Control temperature list | nozzle/bed/chamber/fan/current-target temp | MQTT telemetry normalized fields | target/current 구분 불가 시 `/0 C` 같은 가짜 표기 금지 |
| 우측 motion pad | toolhead/bed jog/manual controls | guarded MQTT/G-code command allowlist | live gate/Guardian 승인 없으면 disabled |
| Main/Auxiliary nozzle selector | X2D dual nozzle active path | selected machine profile + MQTT active nozzle | dual 상태 미검증 시 unknown |
| Extruder load/unload | filament load/unload command | Bambu command allowlist, physical gate | 기본 disabled, operator explicit command 필요 |
| AMS/filament slots A1-A4/Ext | material source and spool state | MQTT AMS/filament fields, selected slicer profile | AMS 미검증 시 `unknown`, 색상/재료 fake 금지 |
| Lamp/Fan/Speed | chamber auxiliary controls | MQTT report/control command if validated | read-only 먼저, write는 approval gate 필요 |
| Calibration / Print Options / Safety Options | 고급 장비 작업 | explicit UI form + bridge allowlist + Guardian | 자동 실행 금지 |

### 5.4.2 Device screen aggregate payload

Bambu Device 화면형 UI는 raw MQTT JSON을 직접 렌더링하지 않는다. bridge가 아래처럼 사용자 중심 payload로 정규화해야 한다.

```json
{
  "schema": "printer_device_screen.v1",
  "profile_id": "bambulab_x2d_lab_01",
  "provider": "bambulab_x2d",
  "connection": {
    "mqtt": "connected|disconnected|auth_failed|unknown",
    "video": "streaming|snapshot|unavailable|unknown",
    "transfer": "ready|unavailable|unknown",
    "last_seen_at": "ISO-8601"
  },
  "camera": {
    "mode": "live_stream|snapshot|unavailable",
    "proxy_url": "local backend URL or empty",
    "frame_age_ms": 0,
    "error": ""
  },
  "job": {
    "name": "",
    "state": "idle|preparing|printing|paused|finished|failed|unknown",
    "progress_percent": null,
    "current_layer": null,
    "total_layers": null,
    "remaining_sec": null,
    "source": "mqtt|slicer_estimate|none"
  },
  "thermal": {
    "main_nozzle_current_c": null,
    "main_nozzle_target_c": null,
    "aux_nozzle_current_c": null,
    "aux_nozzle_target_c": null,
    "bed_current_c": null,
    "bed_target_c": null,
    "chamber_current_c": null,
    "fan_percent": null
  },
  "motion": {
    "jog_available": false,
    "homed": null,
    "safe_to_jog": false
  },
  "materials": {
    "active_path": "main|auxiliary|external|unknown",
    "slots": []
  },
  "actions": {
    "can_upload": false,
    "can_start_print": false,
    "can_pause": false,
    "can_cancel": false,
    "can_jog": false,
    "can_load_unload": false,
    "requires_guardian": true
  },
  "evidence_refs": []
}
```

UI rule:

- 값이 없으면 숫자를 추정해서 채우지 않는다.
- `unknown`, `unavailable`, `pending validation`을 정상 상태처럼 초록색으로 칠하지 않는다.
- operator-facing 화면은 위 payload만 사용한다.
- raw MQTT, raw video errors, stack trace는 Backend view와 artifact log로 보낸다.

### 5.4.3 SPC report와 3DP Device Workspace 역할 분리

Bambu reference 화면 전체는 3DP Device Workspace에 가깝다. Live GUI의 SPC report는 그중 실험 수행에 필요한 핵심만 축약한다.

| 화면 | 목적 | 표시 범위 |
|---|---|---|
| 3DP Device Workspace | operator가 실제 printer를 선택/설정/테스트/제어 | printer selector, camera, status, controls, AMS, storage, HMS, calibration, safety options |
| Live GUI SPC report | 현재 실험 loop에서 시편 제작이 어디까지 왔는지 확인 | selected printer lock, slicer result, upload/start readiness, job progress, evidence, handoff |
| Backend Trace | 개발자/디버깅용 | raw MQTT report, command payload, video error, transfer log, stack trace |

3DP Device Workspace의 `SPC Readiness` panel은 Live GUI SPC report가 사용할 수 있는 축약 evidence 형태를 미리 보여준다. 이 panel은 raw JSON dump가 아니라 다음 사용자 중심 gate를 표시해야 한다.

- printer connection: host/SN/access-code 저장 여부, LAN/Developer confirmation
- device screen: MQTT 연결, FTPS/HTTP transfer 준비, job state
- preprint gate: latest report freshness, safe printer state, storage transfer path, start draft 준비
- start gate: operator confirmation, Guardian approval, dry-run 상태, MQTT publish 가능 여부
- autoejection gate: verified routine, pre/post vision profile, 실제 hardware motion test 가능 여부

Autoejection 설정은 profile checkbox가 아니라 local operator evidence이다. `memory/bambu_autoejection.json`에 저장된 overlay가 없으면 Bambu는 `BAMBU_AUTOEJECTION_NOT_REQUESTED`로 남아야 한다. 저장된 overlay가 있어도 provider, routine id, pre-eject vision profile, post-eject vision profile 중 하나가 빠지면 `configured`로 표시하지 않는다.

### 5.4.4 출력 직전까지의 real communication gate

목표는 GUI가 예쁜 화면만 보여주는 것이 아니라, 실제 printer와 출력 직전까지 통신하는 것이다. 따라서 `실제 출력` 이전에도 아래 gate가 실제 backend source로 증명되어야 한다.

```text
PREPRINT_REAL_COMMUNICATION_GATE
  1. selected printer profile locked
  2. MQTT authenticated and subscribed
  3. latest report received within freshness window
  4. live video or latest snapshot status known
  5. storage/transfer path verified
  6. Bambu Studio/BambuSlicer output artifact exists and hash recorded
  7. selected material/nozzle/profile compatibility checked
  8. printer idle or safe state verified
  9. upload permission and start permission evaluated separately
  10. Guardian approval state attached
```

`출력 직전`은 start command를 이미 보냈다는 뜻이 아니다. bridge 상태로는 `READY_TO_UPLOAD`, `UPLOADED_READY_TO_START`, `READY_TO_START_PRINT`를 분리해야 한다. 실제 물리 출력은 operator intent와 Guardian gate를 통과한 뒤에만 실행한다.

### 5.4.5 Autoejection 구성 원칙

Bambu X2D에서 공식 자동배출 기능이 확인되지 않은 상태에서 Prusa MK4S용 bed sweep G-code를 그대로 쓰면 안 된다. 하지만 우리 전체 목표에는 autoejection까지 포함되므로 bridge capability는 분리해서 설계한다.

```text
AutoEjectionBridge
  - provider-specific routine registry
  - x2d_verified_routine: not configured by default
  - prusa_mk4s_bed_sweep: existing validated/controlled routine
  - external_robot_pickoff: Manipulation Agent handoff option
  - third_party_looping_tool: explicit operator-installed adapter only
```

Bambu X2D autoejection live enable 조건:

1. X2D에서 실제 검증된 ejection routine이 있어야 한다.
2. object bounds와 plate location을 slicing artifact에서 읽어야 한다.
3. camera/vision pre-eject check가 bed 위 물체 위치를 확인해야 한다.
4. cooldown, bed adhesion, chamber/door state가 안전 조건을 만족해야 한다.
5. ejection command는 allowlist된 deterministic builder만 생성해야 한다.
6. ejection 후 camera/vision post-check로 bed clear를 확인해야 한다.
7. 실패 시 next print는 자동 시작하지 않는다.

초기 구현 권장값:

```yaml
autoejection:
  enabled: false
  provider: none
  verified_routine_id: ""
  pre_eject_vision_profile: ""
  post_eject_vision_profile: ""
  require_verified_routine: true
  require_pre_eject_vision: true
  require_post_eject_vision: true
  fallback_to_robot_pickoff: true
```

즉, UI에는 autoejection 섹션을 반드시 만들되, 검증 전에는 `not configured` 또는 `blocked`로 표시한다. 가짜로 `ready`를 띄우면 안 된다.

현재 구현된 Bambu autoejection gate:

- `enabled=false`이면 `BAMBU_AUTOEJECTION_NOT_REQUESTED`로 차단한다.
- `enabled=true`인데 `provider=none`이면 `BAMBU_AUTOEJECTION_PROVIDER_NOT_CONFIGURED`로 차단한다.
- `require_verified_routine=true`인데 `verified_routine_id`가 비어 있으면 `BAMBU_AUTOEJECTION_ROUTINE_NOT_VERIFIED`로 차단한다.
- `require_pre_eject_vision=true`인데 `pre_eject_vision_profile`이 비어 있으면 `BAMBU_PRE_EJECT_VISION_PROFILE_REQUIRED`로 차단한다.
- `require_post_eject_vision=true`인데 `post_eject_vision_profile`이 비어 있으면 `BAMBU_POST_EJECT_VISION_PROFILE_REQUIRED`로 차단한다.
- `/api/printer/autoejection-status`는 위 상태와 blockers를 hardware motion 없이 반환한다.
- GUI는 `/api/printer/autoejection-status`를 읽어 Bambu 기본 profile에서는 `Check Handoff` 버튼을, Prusa 명시 profile에서는 `Autoeject` 버튼을 표시한다. 버튼은 실제 provider가 runnable일 때만 활성화한다.
- `/api/printer/autoejection-test`는 status가 runnable이 아니면 physical routine을 실행하지 않고 `BAMBU_AUTOEJECTION_NOT_CONFIGURED` 계열 blocking result를 반환한다.

### 5.5 command policy

MQTT command는 bridge 내부 deterministic builder만 만든다. LLM, chat text, operator free-form message가 command JSON으로 직접 들어가면 안 된다.

허용 후보:

- `info.get_version`: read-only preflight
- `pushing.pushall`: full state request, rate limit 필요
- `print.gcode_file`: uploaded file print start 후보
- `print.print_speed`: operator-approved speed control 후보
- `print.gcode_line`: 기본 금지. 실험실에서 검증된 allowlist command만 허용
- pause/resume/cancel: live gate + Guardian approval 필요

주의:

- `print.gcode_file`과 파일 경로/확장자는 X2D 실제 firmware에서 반드시 bench validation 해야 한다.
- Bambu 계열은 Bambu Studio에서 sliced 3MF/G-code bundle을 쓰는 경우가 많으므로, 단순 `.gcode` start가 모든 기능/AMS/dual nozzle 정보를 보존한다고 가정하면 안 된다.

---

## 6. Slicer/Bambu Studio 설계

### 6.1 CLI 기본 방향

BambuStudio Wiki 기준 CLI는 다음 요소를 지원한다.

- input: `.3mf`, `.stl`
- settings: `--load-settings "machine.json;process.json"`
- filament: `--load-filaments "filament.json"`
- slicing: `--slice plate_index`
- export: `--export-3mf output.3mf`
- output directory: `--outputdir dir`

따라서 기존 Prusa command template는 다음 식으로 교체 가능해야 한다.

```yaml
slicer:
  enabled: true
  engine: bambu_studio_cli
  executable_env: BAMBU_STUDIO_EXECUTABLE
  executable_path: install/bambustudio/bambu-studio-wrapper
  output_dir: artifacts/bambu_sliced
  timeout_sec: 900
  command_template:
    - "{executable}"
    - "--orient"
    - "--arrange"
    - "1"
    - "--load-settings"
    - "{machine_profile};{process_profile}"
    - "--load-filaments"
    - "{filament_profile}"
    - "--slice"
    - "0"
    - "--export-3mf"
    - "{output_path}"
    - "{stl_path}"
```

### 6.2 X2D profile policy

기본 profile은 다음처럼 분리한다.

| profile | 목적 | 주요 설정 |
|---|---|---|
| `x2d_pla_tpms_main_nozzle_0p2` | 기본 TPMS 시편 | main nozzle, PLA, layer 0.2 mm, bottom cap allowed |
| `x2d_pla_support_aux_nozzle` | support material이 필요한 경우 | main/aux nozzle material mapping |
| `x2d_engineering_material` | ABS/ASA/PA/PC 등 | chamber/bed/temp profile 별도 승인 필요 |
| `x2d_virtual_test` | test mode | 실제 slicing 없이 deterministic artifact 생성 |

현재 TPMS 시편은 support를 최소화해야 하므로, 초기 live path는 single main nozzle PLA profile로 시작하는 편이 안전하다. dual-nozzle은 support material이 필요한 geometry에서만 켠다.

---

## 7. Live/Test mode 동작

### 7.1 normal Live mode

```text
실험 수행
  -> DesignAgent: complete experiment_spec 생성
  -> SpecimenMakingAgent: STL/handoff 생성
  -> printer.prepare(mode=live, printer_profile_id optional)
  -> PrinterDeviceBridgeManager
     - default: bambulab_x2d_lab_01
     - explicit: operator-selected profile
     - no automatic fallback
  -> selected BambuBridge or PrusaBridge
```

Bambu default path:

```text
printer.prepare(provider=bambulab_x2d, mode=live)
     - connection memory 확인
     - Bambu Studio slicing
     - artifact validation
     - MQTT status 연결
     - transfer path preflight
     - upload/start gate 확인
     - physical print intent 확인
     - upload/start/monitor
  -> Vision/Manipulation tail
```

Live physical print 조건:

- `memory/bambu_connection.json` 존재
- host/serial/access_code 유효
- LAN mode 및 필요 시 Developer Mode 확인
- slicer output 생성 완료
- upload/start gate true
- Guardian allow 또는 approval 완료
- operator가 `실험 수행` 또는 명시적 physical intent 제공

### 7.2 Main GUI test mode

- 기본 test printer profile은 `virtual_bambu_x2d`로 둔다.
- 실제 네트워크 접속 없이 virtual Bambu report/video fixture로 진행한다.
- sliced artifact는 dummy 또는 cached sample로 생성한다.
- MQTT sequence/report/transfer/job 상태는 deterministic event로 replay한다.
- downstream loop는 기존처럼 Vision -> Manipulation -> Equipment -> Analysis -> Knowledge -> BO -> Guardian까지 돈다.

### 7.3 Live GUI 안 `테스트 모드`

기존 Prusa path와 동일하게 SpecimenMakingAgent 단계에서만 선택지를 둔다.

- `테스트 모드, 가상 브릿지`: virtual Bambu MQTT/FTPS/video fixture. 물리 통신 없음.
- `테스트 모드, 설치 프린터`: selected printer profile에 read-only MQTT/status/live-view 연결 확인. upload/start 없음.
- `테스트 모드, 실제 출력`: test-generated specimen을 selected printer profile로 slice/upload/start. 기본은 X2D이고, Prusa는 명시 선택 시만 사용. Guardian/operator gate 필요.

---

## 8. 레퍼런스 이미지 기준 SPC report 구성

현재 레퍼런스 `03_specimen_making_agent_report.png`는 좋은 방향이다. Bambu 전환 후에도 카드 개수와 정보 위계를 유지하되, 내용은 아래처럼 바꾼다.

### 8.1 상단 핵심 카드

0. `Printer Fleet / Selected Device`
   - selected profile: `bambulab_x2d_lab_01` 기본
   - available printers: X2D/Prusa/virtual profile chips
   - capability matrix: slicer, transfer, telemetry, live view, material, build volume
   - profile lock: run_id/specimen_id 기준 selected printer 고정
   - 전환 버튼: fallback이 아니라 explicit switch

1. `Slicer Configuration`
   - Engine: Bambu Studio CLI / BambuSlicer
   - Machine profile: X2D main nozzle / dual nozzle
   - Process profile: PLA TPMS 0.2 mm
   - Layer height, first layer height, infill/wall/cap skin
   - Output: `.3mf` 또는 `.gcode.3mf`

2. `Printer Profile`
   - Printer: Bambu Lab X2D
   - Build volume: nozzle mode별 envelope
   - Nozzle: main/auxiliary, diameter
   - Chamber/bed/nozzle temp targets
   - LAN mode / Developer Mode status

3. `Build Queue`
   - run_id/specimen_id/candidate_id
   - slicing -> transfer -> start -> print -> handoff queue
   - real/virtual/read-only badge

4. `Estimated Print Time by Candidate`
   - 후보별 slice estimate
   - Bambu Studio estimate 없으면 deterministic estimate로 표시하고 `estimated` badge 부착

### 8.2 중단 검증/준비 카드

5. `Material / Filament Usage`
   - main nozzle material
   - auxiliary/support material optional
   - grams/meters estimate
   - spool readiness if MQTT/AMS report available

6. `Artifact Validation`
   - STL hash
   - sliced file hash
   - extension policy
   - file size
   - plate index
   - Bambu profile compatibility

7. `Print Readiness`
   - MQTT connected
   - FTPS/Bambu Connect available
   - printer idle
   - bed/nozzle/chamber status
   - physical gate

8. `Build Timeline`
   - Slicing
   - Artifact validation
   - Transfer
   - MQTT start request
   - Heating/bed leveling/calibration
   - Printing
   - Cooling/finish
   - Handoff

### 8.3 하단 evidence 카드

9. `Layer / Plate Preview`
   - full STL viewer가 아니라 lightweight preview image 중심
   - 가능하면 Bambu sliced preview screenshot or cached PNG

10. `Artifact Ledger`
   - STL, sliced 3MF/G-code, Bambu profile json, bridge log, MQTT report tail

11. `Printer Status / Device View`
   - MQTT normalized state
   - progress, temp, active nozzle, job name, remaining time
   - live camera tile 또는 latest snapshot
   - BambuSlicer Device 화면처럼 current job, device status, camera, controls를 한 카드에서 확인

12. `Handoff Status`
   - Design -> Specimen -> Vision -> Manipulation -> Equipment
   - physical specimen location/readiness

### 8.4 시각 스타일

- 기존 레퍼런스처럼 어두운 카드, 얇은 border, pastel green/blue/purple status color 사용.
- raw JSON은 report에 노출하지 않고 Backend view로 분리.
- `MQTT stream`은 숫자 도배가 아니라 timeline/progress/state strip으로 요약.
- 오류는 `blocked reason + next operator action`만 크게 보여주고, stack trace는 Backend view로 보낸다.

---

## 9. Migration map

| 기존 Prusa 항목 | Bambu X2D 전환 항목 |
|---|---|
| single `devices.printer.provider` | `PrinterDeviceBridgeManager` + selected printer profile |
| `provider: prusa_mk4s` | default `printer_profile_id: bambulab_x2d_lab_01`, explicit `prusa_mk4s_lab_01` switch 가능 |
| `memory/prusa_connection.json` | `memory/printer_fleet.json` + optional `memory/bambu_connection.json` |
| `PrusaSlicerRunner` | `BambuStudioRunner` |
| `PrusaLinkClient` | `BambuMqttClient` + `BambuFileTransfer` |
| `GET /api/v1/status` | MQTT `device/{serial}/report` normalized state |
| `PUT /api/v1/files/usb/...` | FTPS/Bambu Connect upload candidate |
| `POST /api/v1/files/usb/...` | MQTT print command candidate |
| `Prusa storage/job/transfer polling` | MQTT report stream + transfer ack/tail |
| no live camera in Prusa bridge | Bambu LAN video stream + latest snapshot + frame health |
| `bed_sweep ejection` | unsupported/deferred until X2D-specific mechanism validated |
| `PrusaSlicer setting cards` | Bambu Studio profile/plate/nozzle/material cards |

---

## 10. Risk register

| risk | 영향 | 대응 |
|---|---|---|
| X2D firmware에서 community MQTT command가 다르게 동작 | upload/start 실패 | 설치 프린터 read-only, virtual bridge, bench validation 순서로 구현 |
| Bambu Studio CLI output 형식이 `.3mf` 중심 | 단순 G-code start 불안정 | sliced 3MF/Bambu Connect path를 우선 고려 |
| LAN-only/Developer Mode 미설정 | MQTT write 차단 | connection preflight에서 명시적으로 block하고 operator action 표시 |
| access code 노출 | 보안 사고 | memory file gitignore, UI mask, log redaction |
| dual-nozzle profile 복잡도 | 시편 재현성 저하 | 초기 TPMS는 main nozzle single-material profile로 제한 |
| Bambu Connect 자동화 한계 | headless automation 불완전 | FTPS/MQTT direct path와 Bambu Connect adapter를 병렬 설계 |
| live video를 MQTT로 오해 | 구현 방향 오류 | MQTT plane과 video plane을 분리하고 Device view에서 합성 |
| multi-printer 자동 fallback | 실험 traceability 붕괴 | 자동 fallback 금지, explicit profile selection만 허용 |
| autoejection 미지원 | closed-loop 물리 자동화 지연 | Vision/Manipulation pickup handoff로 대체, ejection은 future work |
| MQTT pushall 과다 호출 | printer lag 가능 | rate limit, event-driven subscribe 우선 |

---

## 11. 구현 전 검증 체크리스트

코드 수정 전 실제 장비에서 확인해야 할 것:

1. X2D control screen에서 IP, serial, access code 확인 가능 여부.
2. LAN-only Mode와 Developer Mode 경로 확인.
3. 같은 네트워크에서 `8883/tcp`, `990/tcp`, video 후보 port 접근 가능 여부.
4. MQTT TLS 연결: username `bblp`, password access code.
5. `device/{serial}/report` subscribe가 실시간 상태를 주는지.
6. `info.get_version` 또는 read-only command가 응답하는지.
7. LAN live-view stream 또는 snapshot stream이 열리는지.
8. Bambu Studio/BambuSlicer Device 화면과 동일한 상태 항목을 bridge에서 재구성할 수 있는지.
9. Bambu Studio CLI executable path와 `--slice`, `--export-3mf` smoke test.
10. X2D용 machine/process/filament full config json export 가능 여부.
11. sliced 3MF/G-code 파일을 Bambu Connect 또는 FTPS로 전송 가능 여부.
12. MQTT로 start 가능한 command와 파일 path 규칙.
13. print 완료/실패/취소 상태가 report stream에서 어떻게 표기되는지.
14. 여러 printer profile 등록 후 default X2D와 explicit Prusa switch가 run lock을 깨지 않는지.

---

## 12. 권장 구현 순서

1. `PrinterFleetRegistry`, `PrinterProfileSelector`, `PrinterDeviceBridgeManager` 계약을 먼저 추가한다.
2. default profile을 `bambulab_x2d_lab_01`로 두고 automatic fallback을 금지한다.
3. 기존 Prusa path는 adapter로 보존하고, explicit profile switch로만 접근하게 한다.
4. `BambuBridgeConfig`와 `BambuConnectionMemory`를 추가한다.
5. virtual Bambu bridge를 먼저 만들어 test mode closed-loop를 통과시킨다.
6. Bambu Studio CLI runner를 붙이고 slicing artifact manifest를 만든다.
7. MQTT read-only monitor를 붙인다.
8. LAN video stream client와 latest snapshot artifact를 붙인다.
9. Device screen aggregator를 만들어 BambuSlicer Device 화면형 status payload를 만든다.
10. FTPS/Bambu Connect transfer adapter를 붙인다.
11. physical start gate를 마지막에 붙인다.
12. Live GUI SPC report를 selected printer/profile/status/video/timeline/evidence 카드로 교체한다.
13. Guardian gate와 incident reporting을 physical write action 앞에 붙인다.
14. 실제 X2D bench validation log를 `docs/hardware`에 따로 남긴다.

---

## 13. 문서 업데이트 대상

구현 시 함께 갱신해야 할 문서:

- `docs/hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt`는 Prusa 전용 문서로 유지.
- 새 문서: `docs/hardware/bambulab_x2d_bridge_runtime_guideline.md`.
- `docs/hardware/evidence/prusa_mk4s_live_validation_20260506.md`와 같은 방식으로 X2D validation log 생성.
- `docs/agents/specimen_design_existing_runtime_guideline.txt`에 `provider=bambulab_x2d` 표시 규칙 추가.
- `REQUIREMENTS.md`에 Bambu Studio CLI, MQTT client, FTPS client 후보 추가.

---

## 14. 참고 링크

- Bambu Lab X2D product page: https://bambulab.com/en-us/x2d
- Bambu Lab X2D technical specifications: https://bambulab.com/en-us/x2d/specs
- Bambu Lab X2D official blog: https://blog.bambulab.com/xcellence-made-simple-bambu-lab-presents-the-x2d/
- Bambu Studio command line usage: https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage
- Bambu Lab LAN Mode guide: https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode
- Bambu Lab printer network ports: https://wiki.bambulab.com/en/general/printer-network-ports
- User supplied Bambu Device reference screenshot: `개선안/reference_assets/bambulab_device_screen_20260614.png`
- Bambu Lab access code connection guide: https://wiki.bambulab.com/en/knowledge-sharing/access-code-connect
- Bambu Lab third-party integration: https://wiki.bambulab.com/en/software/third-party-integration
- Bambu Connect: https://wiki.bambulab.com/en/software/bambu-connect
- Bambu Farm Manager official blog: https://blog.bambulab.com/bambu-lab-introduces-local-fleet-control-with-bambu-farm-manager/
- Bambu Farm Manager Wiki: https://wiki.bambulab.com/en/software/bambu-farm-manager
- OpenBambuAPI MQTT notes: https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
- OpenBambuAPI FTPS notes: https://github.com/Doridian/OpenBambuAPI/blob/main/ftp.md
- OpenBambuAPI video notes: https://github.com/Doridian/OpenBambuAPI/blob/main/video.md
- Bambu ACS background: https://blog.bambulab.com/firmware-update-introducing-new-authorization-control-system-2/
- Bambu Connect update background: https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect/

---

## 14. 2026-06-14 구현 반영 상태

이 섹션은 위 설계 중 현재 코드에 실제 반영된 항목과 아직 남은 항목을 구분한다. 구현 파일 기준이며, 거짓 ready 상태를 만들지 않는 것을 우선 원칙으로 둔다.

### 14.1 반영된 항목

- `device_bridges/bambu_bridge.py`
  - `PrinterDeviceBridgeManager` 추가.
  - default profile은 `bambulab_x2d_lab_01`.
  - `prusa_mk4s_lab_01`은 자동 fallback이 아니라 명시 선택 profile.
  - `BambuConnectionMemory`는 `memory/bambu_connection.json`에 host, SN, printer name, model, LAN access code를 local-only로 저장한다.
  - local MQTT는 `host:8883`, TLS, username `bblp`, password LAN access code, topic `device/{SN}/report` / `device/{SN}/request` 구조를 사용한다.
  - `pushing.pushall` request 후 report snapshot을 읽고 `device_screen`으로 normalize한다.
  - X2D report에서 확인되는 `percent`, `3D.layer_num`, `hms`, `ipcam`, `upload`, `lights_report`, AMS tray 정보를 보존한다.
  - Bambu implicit FTPS port 990은 자체 인증서와 TLS session reuse가 필요하므로 `_ImplicitFTP_TLS`에서 control/data TLS session reuse를 처리한다.
  - `can_upload=true`는 MQTT report 수신과 FTPS write/delete marker probe가 모두 성공했을 때만 표시한다. FTPS login/list만 성공한 read-only 상태는 upload-ready로 보지 않는다.
  - `can_start_print=true`는 verified transfer path(FTPS write/upload 또는 verified HTTP artifact route), valid `project_file` draft, safe printer state가 동시에 만족될 때만 표시한다. 이 값은 기술 readiness이며 실제 start command는 dry-run 해제, Guardian/operator gate, backend start gate 검증 전까지 publish되지 않는다.
  - Bambu autoejection은 현재 `not_configured`로 block한다. Prusa bed-sweep routine을 Bambu에 자동 재사용하지 않는다.
  - `BambuVideoStreamClient`는 RTSPS `:322`/JPEG `:6000` 후보를 probe하고 `ffmpeg` 기반 browser MJPEG proxy readiness를 계산한다.
  - `BambuSlicerConfig.resolved_payload()`가 Bambu Studio CLI를 `BAMBU_STUDIO_EXECUTABLE` env var, configured wrapper path, `PATH`의 `bambu-studio` 순서로 해석한다. 현재 Spark workstation에서는 `/home/jin/.local/bin/bambu-studio`가 감지된다.

- `mcp_tools/printer_tools.py`
  - `printer.prepare`가 bridge manager를 통해 Bambu default / Prusa explicit profile을 분기한다.

- `app/main.py`
  - `/api/printer/status`가 selected printer, available printers, device screen, preprint gate, slicer, live gates를 반환한다.
  - `/api/printer/profile`도 active printer 기준 slicer payload를 반환한다. Bambu일 때는 `resolved_executable_path`, `available`, `source`, `output_dir`를 포함하며, profile load만으로 upload/start readiness를 만들지 않는다.
  - `/api/printer/video-status`가 selected Bambu profile의 LAN video port/proxy readiness를 secret 없이 반환한다.
  - `/api/printer/video-stream.mjpeg`가 `ffmpeg` 기반 Bambu RTSPS -> MJPEG browser proxy를 제공한다.
  - `/api/printer/connection`이 Bambu connection memory를 secret 없이 읽고 저장한다.
  - provider가 Bambu일 때 Prusa 저장 profile을 Bambu-safe overlay로 표시한다.
  - `/api/printer/autoejection-status`가 verified routine / pre-vision / post-vision evidence 상태를 반환한다.
  - `/api/printer/autoejection-test`는 Bambu autoejection routine이 검증되지 않았으면 physical routine을 실행하지 않고 blocking hardware alert를 발생시킨다.

- `web/templates/printer.html`, `web/static/printer.js`, `web/static/styles.css`
  - 3DP GUI를 Bambu Device Screen 중심으로 재구성했다.
  - MQTT, FTPS, Upload readiness, job/progress/layer/temperature/AMS slots를 화면에 표시한다.
  - `Printer Fleet Selection`은 `/api/printer/fleet`의 `available_printers`를 캐시해 후속 status/SPC 응답 뒤에도 Bambu/Prusa 선택 목록을 유지한다.
  - Slicer card는 configured wrapper가 없더라도 `PATH`에서 감지된 실제 Bambu Studio executable을 표시한다.
  - `Video Status` 버튼으로 live video plane을 별도로 probe하고, 준비되면 camera panel 안에 MJPEG stream을 표시한다.
  - SN, LAN access code, printer name, model을 GUI에서 저장할 수 있다.
  - access code는 GUI log나 API response에 원문 표시하지 않는다.

- `configs/devices.yaml`
  - Bambu Lab X2D가 default printer profile.
  - Prusa MK4S는 explicit selectable profile.
  - Bambu MQTT/FTPS/video/slicer config section 추가.

### 14.2 실제 장비 검증 결과

검증 대상:

- Bambu Lab X2D
- IP: `192.0.2.42`
- SN: `20PTEST000001`
- Username: `bblp`
- LAN access code: local memory에 저장, 문서/로그에 원문 기록 금지

검증 결과:

```text
MQTT 8883 TCP: open
FTPS 990 TCP: open
Video 322/TCP RTSPS: reachable
Video 6000/TCP JPEG: fallback candidate, not used by current X2D path
MQTT TLS/auth/report: success
MQTT topic: device/20PTEST000001/report
FTPS implicit TLS login/list: success after session reuse fix
FTPS write/delete marker probe: blocked
FTPS failure_code: BAMBU_FTPS_WRITE_FAILED
Preprint state: blocked
can_upload: false
can_start_print: false
Bambu Studio CLI: /home/jin/.local/bin/bambu-studio detected via PATH
Bambu Studio CLI version: BambuStudio-02.07.01.57
Bambu slice smoke: STL -> artifacts/bambu_sliced/<specimen>/plate_1.gcode generated with sha256 recorded
Bambu pre-start checklist: slice + HTTP route + start gate + SPC readiness + autoejection handoff path covered by integration test; no MQTT publish from checklist
HTTP artifact route: verified route sets preprint_state=http_artifact_ready_not_started and can_start_print=true, but publish remains blocked by dry-run/operator/Guardian until explicitly approved
video_status: streaming_candidate
video_proxy: ready when ffmpeg is installed
Autoejection: blocked / not_configured
```

실제 report snapshot에서 확인된 표시 값 예:

```text
job state: FINISH
progress: 100%
layer: 108/108
nozzle/bed: 약 32 C / 29 C
camera metadata: 1080p preview available
video probe: rtsps://192.0.2.42:322/streaming/live/1 reachable
AMS slots: 4
```

### 14.3 참고 자료 반영 사항

- OpenBambuAPI `mqtt.md`
  - local MQTT URL은 `{PRINTER_IP}:8883`, TLS enabled, username `bblp`, password는 LAN access code.
  - topics는 `device/{DEVICE_ID}/report`, `device/{DEVICE_ID}/request`.
  - `pushing.pushall`은 complete status report를 요청하는 command.
  - report에는 AMS, temperatures, `gcode_state`, `mc_percent`, `layer_num`, `total_layer_num`, `ipcam`, `lights_report`, `upload`, `sdcard` 등이 포함될 수 있다.

- DrozmotiX/ioBroker.bambulab issue #258
  - X2D support report payload에서 `3D.layer_num`, `percent`, `hms`, `ipcam.liveview_preview`, `upload`, `lights_report`, AMS tray 등 X2D-specific/newer fields를 확인했다.
  - normalize 단계에서 이 필드를 보존하도록 반영했다.

- Bambu community / LAN-only integration 자료
  - FTPS는 일반 SFTP가 아니라 implicit FTP over TLS이며 port 990, username `bblp`, password LAN access code를 사용한다.
  - 최신 firmware/write control에서는 LAN-only mode와 Developer Mode 확인이 필요할 수 있으므로 GUI에 confirmation field를 둔다.

### 14.4 남은 구현 항목

- Bambu Studio/BambuSlicer CLI executable 감지와 실제 STL/3MF -> sliced artifact generation runner는 구현됐다. smoke 검증에서는 `BambuStudio-02.07.01.57`가 headless warning을 출력했지만 실제 `plate_1.gcode`와 sha256 manifest가 생성됐다. 남은 작업은 Bambu profile JSON(`--load-settings`, `--load-filaments`)을 실험 조건/AMS/dual-nozzle profile과 더 세밀하게 연결하고, `.gcode`와 `.gcode.3mf` 중 X2D live start에 가장 안정적인 artifact 형식을 확정하는 것이다.
- Bambu FTPS actual upload path 확정 및 dry-run upload 검증.
- MQTT start command는 기술 gate와 publish gate를 분리한다. verified HTTP artifact route나 verified upload path가 있으면 `can_start_print=true`가 될 수 있지만, 실제 publish는 Developer/LAN 확인, Guardian approval, operator confirmation, `dry_run=false`, start gate 재검증 뒤에만 활성화해야 한다.
- LAN video stream proxy 1차 경로는 연결됐다. `/api/printer/video-status`가 RTSPS `:322` reachability와 `ffmpeg` availability를 확인하고, `/api/printer/video-stream.mjpeg`가 browser MJPEG proxy를 제공한다. 남은 작업은 장시간 안정성/프레임 지연/재연결 정책과 GUI fullscreen/snapshot UX다.
- Bambu autoejection physical routine은 아직 없다. X2D에서 안전한 physical routine 또는 외부 robot pick-off routine이 검증될 때까지 block 상태가 맞다.
- 다만 Bambu provider handoff 계약은 구현됐다. `/api/printer/autoejection-test`는 검증된 provider/routine/vision profile이 저장된 경우에도 physical motion을 시작하지 않고 `bambu_autoejection_provider_handoff.v1`을 반환한다. 이 packet은 `recommended_consumer_agent=ManipulationAgent`, `next_tool=lerobot.manipulation-agent.run`, `requires_guardian_approval=true`, `requires_operator_confirmation=true`, `motion_started=false`, `dry_run_only=true`를 포함해야 한다.
- 3DP GUI SPC Readiness와 Live GUI SPC report는 `selected_printer`, `device_screen`, `preprint_gate`, `readiness_levels`, `operator_actions`, `autoejection`, `autoejection_handoff`를 카드화한다. `autoejection_handoff`가 있으면 next-action 영역에 `Manipulation Agent handoff`로 표시하고, `motion_started=false`를 유지한다. 남은 작업은 실제 robot pick-off executor를 연결하고 Vision pre/post eject proof를 물리 dry-run으로 검증하는 것이다.
