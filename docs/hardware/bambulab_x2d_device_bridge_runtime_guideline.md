# BambuLab X2D Device Bridge Runtime Guideline

작성 기준: 2026-06-16
대상: `3DP Printer Bridge`, `PrinterDeviceBridgeManager`, `SpecimenMakingAgent`, `BambuLab` active printer provider
문서 성격: 운영자/협업자용 시스템 설명 문서. 구현 지시 원본은 `개선안/14_bambulab_gcode_autoejection_runtime_plan.md`를 따른다.

---

## 1. 역할 정의

BambuLab X2D bridge는 ATR의 기본 3DP printer provider다. 이 bridge는 단순히 파일을 업로드하는 adapter가 아니라 다음 네 가지 plane을 분리해서 관리한다.

| Plane | 책임 | 대표 evidence |
|---|---|---|
| Fleet / Provider | active printer profile 선택, Bambu/Prusa 전환, secrets 분리 | `memory/printer_fleet.json`, `memory/bambu_connection.json` |
| Slicing / Artifact | STL/3MF를 Bambu Studio 또는 Orca 계열 sliced artifact로 변환 | `.gcode.3mf`, sha256, command preview, stderr/stdout tail |
| Device Status / Control | MQTT status 수집, `project_file` draft/publish, post-publish observation | `device_screen`, `gcode_state`, `mc_percent`, `subtask_name` |
| Camera / Bed-clear | camera frame/proxy, ejection 전후 visual evidence, next-job gate | `camera_snapshot_path`, `bambu_bed_clear_evidence.v1` |

핵심 원칙은 다음과 같다.

- 기본 active provider는 BambuLab X2D다.
- Prusa MK4S는 fallback이 아니라 operator가 명시적으로 선택하는 다른 provider다.
- Bambu autoejection은 Manipulation Agent handoff가 아니라 Bambu 전용 native G-code patch/validation path다.
- MQTT publish ack는 실제 출력 시작과 다르다. fresh post-publish observation으로 `RUNNING`/`PREPARING` 계열 상태를 확인해야 한다.
- camera/video 실패는 MQTT/progress/material 상태를 지우지 않는다. 두 plane은 병렬 evidence다.

---

## 1.1 외부 근거와 ATR 적용 범위

이 문서는 외부 프로젝트나 커뮤니티 G-code를 그대로 가져오는 문서가 아니다. 외부 사례는 다음 운영 원칙을 검증하는 근거로만 사용한다.

| 근거 범위 | 확인한 사실 | ATR 적용 |
|---|---|---|
| Bambu Studio CLI | 공식 CLI는 `--slice`, `--load-settings`, `--load-filaments`, `--export-3mf` 기반 slicing/export를 제공한다. | bridge는 slicing을 publish와 분리하고, output directory 안 basename export를 사용한다. |
| OpenBambuAPI / Home Assistant 계열 | 로컬 MQTT는 TLS 8883, username `bblp`, LAN access code를 쓰며 `project_file`에는 `url`, `param`, `subtask_name`, AMS 관련 값이 들어간다. | MQTT command draft, artifact internal plate path, AMS mapping, publish ack, post-publish observation을 별도 evidence로 나눈다. |
| ha-bambulab upload/start 사례 | FTPS upload와 MQTT start가 조합되지만, AMS mapping과 실제 start observation이 별도 문제로 남는다. | FTPS/HTTP transfer proof와 start gate를 분리하고, `published=true`만으로 성공 처리하지 않는다. |
| Looprint / Factorian 계열 autoeject 사례 | sliced G-code/3MF에 cooldown, push-off, optional sweep을 넣어 반복 출력한다. 모델군별 push axis와 안전 범위가 다르다. | native `bambu_gcode_patch`는 deterministic post-process patch로만 수행하고, model family/envelope/height/residue validator를 gate로 둔다. |
| Reddit / Bambu community 실패 사례 | bed adhesion, toolhead cover, carbon rod 방향 하중, purge/skirt residue, build plate shift가 실제 리스크로 반복된다. | 물리 환경 관리는 workstation owner/operator가 직접 수행한다. UI 수동 checklist는 제거하고, runtime gate는 printer-state, geometry, camera, bed-clear evidence를 중심으로 둔다. |
| Bambu Studio Device 화면 | camera, progress/layer, thermal, material/AMS, control 상태가 한 화면에서 동시에 유지된다. | 3DP Device Workspace는 status plane과 camera plane을 동시에 표시하되, video failure가 기존 status를 지우지 않게 한다. |
| X2D/H2D MQTT report 사례 | X2D/H2D report는 기존 X1/P1보다 깊은 `2D`, `3D`, `device`, nozzle/material 구조를 가진다. | normalizer는 raw report를 보존하고, 알 수 없는 필드는 버리지 않으며, Device Workspace에는 normalized summary만 표시한다. |

주요 참고 링크:

- Bambu Studio command line usage: `https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage`
- Bambu LAN mode: `https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode`
- Bambu printer network ports: `https://wiki.bambulab.com/en/general/printer-network-ports`
- OpenBambuAPI MQTT notes: `https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md`
- ha-bambulab upload/start discussion: `https://github.com/greghesp/ha-bambulab/discussions/307`
- Looprint multi-loop builder: `https://github.com/NickiAndersen/looprint`
- X2D MQTT report issue: `https://github.com/DrozmotiX/ioBroker.bambulab/issues/258`
- SimplyPrint / Bambu webcam and Developer Mode references: `https://help.simplyprint.io/en/article/bambu-lab-webcam-not-working-guide-pw6z3q/`, `https://help.simplyprint.io/en/article/bambu-lab-lan-only-mode-and-developer-mode-how-to-enable-xa0hch/`

---

## 2. Runtime 경로

Live/Test workflow에서 Bambu bridge가 호출되는 위치는 다음과 같다.

```text
Live GUI / Main GUI
  -> MainController / LangGraphRunLoop
  -> DesignAgent
      -> bambu_autoejection_readiness 작성
  -> SpecimenMakingAgent
      -> fabrication_report.process_plan에 readiness 보존
      -> printer.prepare payload 생성
  -> PrinterDeviceBridgeManager
      -> PrinterFleetRegistry에서 active provider 결정
      -> BambuLabBridge 선택 시 Bambu status/slicing/start gate 실행
      -> native autoejection enabled면 BambuGcodeAutoejectionPatcher 호출
  -> Vision / Manipulation / Equipment / Analysis / Knowledge / BO / Guardian
```

`SpecimenMakingAgent`는 프린터별 통신 세부 구현을 직접 갖지 않는다. `printer.prepare` payload와 report evidence를 만들고, 실제 Bambu 통신은 `device_bridges/bambu_bridge.py`와 `device_bridges/bambu_autoejection.py`가 담당한다.

---

## 3. Bambu 통신 모델

### MQTT

로컬 MQTT는 LAN/Developer Mode가 켜진 프린터를 대상으로 한다.

- host: `{printer_ip}:8883`
- username: `bblp`
- password: LAN access code
- report topic: `device/{serial}/report`
- request topic: `device/{serial}/request`

`project_file` publish는 다음과 같이 분리해서 본다.

1. command draft valid 여부
2. artifact path와 internal plate path 정합성
3. AMS 사용 시 `ams_mapping` 존재 여부
4. MQTT publish ack
5. fresh post-publish observation의 printer state/progress

따라서 `published=true`만으로 출력 성공을 표시하면 안 된다. publish 이후에도 프린터가 `IDLE` 또는 not-started 상태면 `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED`로 operator에게 보여준다.

### FTPS / HTTP artifact route

Bambu artifact transfer는 FTPS upload와 HTTP artifact route를 분리한다.

- FTPS login/list 성공은 upload-ready가 아니다.
- write/delete probe 또는 server-fetch proof가 필요하다.
- HTTP route는 프린터가 접근 가능한 `http://<ATR-LAN-IP>:<port>/...` 형태여야 한다.
- `localhost` URL은 프린터에서 접근할 수 없으므로 live transfer evidence로 인정하지 않는다.

### Camera / Video

Camera/video는 status MQTT와 별도 plane이다.

- `Pre-start Check`는 status와 camera를 같이 갱신한다.
- `Video Status`는 camera panel만 갱신하고 기존 device/material/progress card를 지우면 안 된다.
- ejection 이후 `Mark Bed Clear`는 최신 camera preview/proxy evidence를 `camera_snapshot_path`로 저장해야 한다.

---

## 4. Slicing / Artifact 기준

Bambu primary artifact는 sliced `.gcode.3mf`다. Plain `.gcode`는 개발, validator, standalone ejection test에는 유용하지만 live Bambu publish의 primary path로 보지 않는다.

Bambu Studio CLI는 공식적으로 다음 축을 제공한다.

- `--slice <plate_index>`
- `--arrange <option>`
- `--load-settings "machine.json;process.json"`
- `--load-filaments "filament.json;..."`
- `--outputdir <dir>`
- `--export-3mf <output-basename.3mf>`
- `--debug <level>`

ATR bridge는 slicing을 upload/start와 분리한다. `Slice Bambu Artifact`는 artifact 생성까지만 수행하고, MQTT publish나 physical motion을 실행하지 않는다.

검증된 CLI/route 주의사항:

- `--export-3mf`에는 absolute path가 아니라 `--outputdir` 내부의 basename을 넘긴다. Spark workstation의 BambuStudio `02.07.01.57`에서는 absolute path를 넘기면 output directory가 중복 결합되어 export가 실패할 수 있었다.
- 명시 `load_settings`가 없으면 bridge runner는 Bambu Studio 기본 machine/process/filament preset을 그대로 사용한다. purge, cleaning, filament start/end G-code 같은 기본 동작은 유지하고, build plate front에 그어지는 test/intro/nozzle-load line만 sliced artifact 후처리에서 제거한다.
- 실제 검증에서 basename export를 사용하면 `/home/jin/다운로드/specimen(4).stl` 기준 `.gcode.3mf` 생성, 내부 `Metadata/plate_1.gcode` patch, front test line removal, md5 sidecar 갱신, validator 통과가 가능했다. 이 검증은 artifact 생성/patch까지만 의미하며 실제 publish/ejection 성공을 뜻하지 않는다.
- 실제 장비에 대해 HTTP artifact route는 ATR 서버 LAN IP URL로 server-side fetch와 sha256 match까지 확인됐다. 현재 GUI는 owner-managed publish 기본값을 보내므로 artifact/camera/bed-clear/start-state blocker가 없으면 `Pre-start Check`가 `ready_to_publish_not_started`까지 도달할 수 있다. 이 route는 여전히 `published=false`, `will_publish=false`를 유지한다.
- `.gcode.3mf` patch는 요청한 `plate_id`와 정확히 일치하는 `Metadata/plate_<id>.gcode`만 대상으로 한다. 요청 plate가 없고 다른 plate G-code가 존재하더라도 fallback으로 대체하지 않는다. 이는 MQTT `project_file.param`과 내부 plate path가 어긋난 채로 시작되는 것을 막기 위한 live-start gate 계약이다.
- 로컬 `.gcode.3mf` artifact를 `printer.prepare` 또는 HTTP artifact route에 넘길 때도 같은 검사를 수행한다. 요청한 `plate_id`의 `Metadata/plate_<id>.gcode`가 없으면 FTPS upload나 HTTP export를 만들기 전에 `BAMBU_PROJECT_FILE_PARAM_MISMATCH`로 차단한다.
- patch result와 manifest는 `source_sha256`, `patched_sha256`, `source_plate_path`, `plate_id`, `loop_index`, validator result를 함께 남긴다. `loop_index`가 요청에 없으면 현재 단일 출력 artifact 기준으로 `1`을 사용한다.
- 이미 `atr.bambu.autoejection.v1` marker가 있는 `.autoeject.*` artifact가 다시 입력되면 bridge는 새 `.autoeject.autoeject.*` 파일을 만들지 않는다. 기존 artifact를 재검증하고 sidecar manifest만 갱신한다.

권장 흐름:

```text
STL/3MF source
  -> Bambu Studio/Orca slicing
  -> .gcode.3mf artifact
  -> optional Bambu native autoejection patch
  -> .autoeject.gcode.3mf artifact + manifest
  -> start gate
  -> publish only after backend start gate and browser confirmation
```

---

## 5. Native G-code Autoejection

Bambu autoejection은 `bambu_gcode_patch` provider로 표시한다. 이는 외부 robot handoff가 아니라 sliced artifact의 내부 plate G-code에 deterministic ejection tail을 삽입하는 방식이다.

### 기본 설계

```text
.gcode.3mf
  -> Metadata/plate_#.gcode 추출
  -> object bounds / max_layer_z / residual skirt-brim-raft risk 분석
  -> ejection tail 삽입
  -> Metadata/plate_#.gcode.md5 갱신
  -> .autoeject.gcode.3mf 생성
  -> sidecar manifest + run workspace manifest 기록
```

### Validator가 막아야 하는 것

- ejection marker 누락 또는 중복
- ejection tail 내부의 예상 밖 `G28`
- build envelope를 벗어난 X/Y/Z motion
- 과도한 feedrate
- object height가 너무 낮거나 너무 큼
- multi-object plate without explicit support
- skirt/brim/raft/purge residue risk
- AMS mapping 누락
- `.gcode.3mf` internal plate path와 MQTT `project_file.param` 불일치
- operator-managed physical context evidence 누락 또는 bed-clear/camera evidence 불충분

### Tail metadata 계약

`bambu_gcode_patch`가 삽입하는 tail은 실행 motion뿐 아니라 추적 가능한 evidence header를 포함해야 한다. 현재 deterministic tail은 다음 값을 plate G-code comment로 기록한다.

- schema marker: `atr.bambu.autoejection.v1`
- source artifact hash와 patched artifact hash reference
- source plate path, `plate_id`, `loop_index`
- specimen id, selected push position, object bounds, object height
- material type과 bed surface. slicer metadata extraction이 없는 경우 `unknown`으로 명시한다.
- cooldown target과 wait policy: 기본 `M190`
- push Z offset, push lane offset, push speed, full-bed sweep enable, sweep Z, sweep speed
- purge/parking strategy: 기본 `preserve_slicer_end_gcode_then_eject`
- door/front path assumption, toolhead-cover risk note, validation result reference

이 metadata는 GUI 표시용 임의 값이 아니라 generated artifact 자체에 남는 audit trail이다. `unknown` 값은 후속 slicer/profile parser가 채울 수 있는 확장 포인트이며, 값을 모르는 상태를 숨기지 않기 위해 생략하지 않는다.

### Live publish 조건

`.autoeject.*` artifact는 일반 artifact보다 강한 gate를 요구한다.

- owner-managed publish defaults present (`operator_confirmed=true`, `guardian_approved=true`, `dry_run=false`)
- operator-managed physical clearance/ejection setup recorded as evidence
- camera frame available or operator visual evidence
- previous `bed_clear_required`가 해제됨

### Standalone autoejection test 경로

3DP Device Workspace의 left/center/right standalone autoejection test는 실제 시편 출력 경로와 분리한다.

```text
3DP GUI standalone button
  -> POST /api/printer/autoejection-test
  -> build_standalone_bambu_autoejection_artifact()
  -> standalone .autoeject.gcode.3mf artifact
  -> guarded upload/start through MQTT project_file
```

현재 검증된 장비 경로:

- printer host: `192.168.50.4`
- serial: `20P6BJ642001425`
- MQTT request topic: `device/20P6BJ642001425/request`
- config/evidence memory: `memory/bambu_autoejection.json`
- generated standalone artifact directory: `artifacts/bambu_autoejection/`
- physical validation summary: `runs/manual_bambu_validation/`

Standalone test도 direct MQTT `gcode_line` motion을 쓰지 않는다. 3DP GUI live gate를 통과한 경우에만 `.autoeject.gcode.3mf` artifact를 일반 upload/start gate로 넘긴다. Tail 내부에서는 전체축 `G28`을 실행하지 않는다. Bambu/X2D full homing은 중앙 probing/접촉 동작을 포함할 수 있으므로 autoejection tail은 프린트 job 시작 시 확립된 좌표계를 보존한다.

`Live GUI 테스트 모드, 설치 프린터` 경로는 실제 출력 시간을 기다리지 않는 route validation이다. 실제 STL을 active slicer로 `.gcode.3mf`까지 만들고, 그 artifact를 일반 `project_file` upload/start gate로 publish한다. 성공 기준은 MQTT ack가 아니라 fresh post-publish observation에서 `RUNNING`/preparing 계열 state와 progress-panel evidence가 관측되는 것이다. 이후 즉시 stop을 보내고, 같은 sliced artifact의 `Metadata/plate_#.gcode`에서 extrusion move 기반 object bounds를 추출해 standalone autoejection artifact를 publish한다. extrusion bounds가 없거나 plate G-code를 읽을 수 없으면 `BAMBU_AUTOEJECTION_SOURCE_EXTRUSION_BOUNDS_REQUIRED` 계열 failure로 ejection publish를 차단한다.

`Live GUI 테스트 모드, 실제 출력`과 일반 Live actual print 경로는 출력 본문을 제거하지 않는다. sliced `.gcode.3mf` 내부 plate G-code에 autoejection tail을 append해 `.autoeject.gcode.3mf`를 만들고, 그 patched artifact를 일반 upload/start gate로 보낸다.

기본 push Z 규칙은 `max(10 mm absolute Z, object max Z - 15 mm)`이다. 예를 들어 12 mm object는 Z10.000, 30 mm object는 Z15.000으로 sweep한다. 이 값은 `memory/bambu_autoejection.json`의 `z_push_offset_mm`과 `min_absolute_push_z_mm` 계약으로 해석한다.

Z motion은 절대좌표 기준으로 계산한다. 오토이젝션 push 높이는 `push_z_mm = max(10.0, object_bounds.max_z - z_push_offset_mm)`이며 기본 `z_push_offset_mm`는 15mm다. 즉 object `max_z <= 25mm`이면 무조건 `G0 Z10.000`, `max_z=26mm`이면 `G0 Z11.000`, `max_z=30mm`이면 `G0 Z15.000`이다. `object max Z + 10mm` 방식은 금지한다.

구분해야 하는 runtime path:

| Mode | Transport | Physical motion |
|---|---|---|
| Main GUI test / Live GUI `테스트 모드, 가상 브릿지` | `virtual` | 없음 |
| Live GUI `테스트 모드, 설치 프린터` | actual sliced `.gcode.3mf` -> MQTT `project_file` start -> progress observation -> stop -> source-bounds-derived standalone `.autoeject.gcode.3mf` + MQTT `project_file` | actual-printer upload/start validation plus physical ejection-route validation; full print body is started only long enough to prove the progress panel receives a real job |
| 3DP GUI standalone autoejection test with live gates | standalone `.autoeject.gcode.3mf` + MQTT `project_file` | ejection-only artifact through the same upload/start gate; no direct `gcode_line` |
| Live GUI `테스트 모드, 실제 출력` / normal Live actual print | `.autoeject.gcode.3mf` + MQTT `project_file` | real print body is preserved and deterministic autoejection tail is appended |

---

## 6. 3DP Device Workspace 표시 원칙

3DP GUI는 Bambu Studio Device 탭과 유사하게 실시간 운영 정보를 한 화면에 유지해야 한다. 단, GUI가 임의 값을 만들면 안 되고 backend normalized report만 표시한다.

필수 표시 영역:

- active printer profile and provider
- LAN/Developer Mode confirmation
- camera preview or camera blocker
- current job/progress/layer/ETA
- nozzle/bed/chamber/fan status
- AMS/material mapping
- transfer/upload/HTTP route status
- start gate and post-publish observation
- autoejection config/validator result
- bed-clear evidence and next-job lock

버튼 정책:

- `Pre-start Check`, `Video Status`, `Generate Patched Artifact`, `Validate *`, `Publish Start`, `Mark Bed Clear`는 callback 완료 전까지 재클릭이 막혀야 한다.
- `Pre-start Check`는 publish하지 않는다. 출력 직전 검증 surface다.
- `Publish Start`만 실제 MQTT start publish를 할 수 있다.
- `Video Status` 실패는 기존 status card를 초기화하지 않는다.
- `Physical Proof Package`는 실제 출력/배출 실행 버튼이 아니다. 이 영역은 supervised 물리 검증 후 operator가 증거를 채울 fail-closed JSON template과 completion audit만 제공한다.
- `Build Fail-Closed Proof Template`은 `/api/printer/bambu-autoejection-proof-template`을 호출해 `artifacts/printer/manual/bambu/` 아래 proof package를 만들 수 있다. 생성 직후 package는 반드시 audit fail 상태여야 한다.
- `Run Completion Audit`은 `/api/printer/bambu-autoejection-completion-audit`을 호출해 proof package를 읽고 완료 여부를 판정한다. 이 API도 비동작성이며 MQTT publish, upload, camera capture, axis motion을 실행하지 않는다.

---

## 7. Test / Live 동작 차이

| Mode | Bambu bridge 동작 | Physical motion |
|---|---|---|
| Test + virtual bridge | slicing/patch/validation simulation, virtual bed-clear evidence | 없음 |
| Test + installed printer | MQTT/FTPS/video/pre-start 통신 확인, operator 선택 시에만 실제 publish | 기본 없음 |
| Live | active Bambu provider로 slicing/transfer/start, autoejection enabled면 patched artifact 사용 | gate 통과 시 있음 |

Live/Test 모두 같은 API contract를 사용해야 한다. 차이는 bridge mode와 publish gate뿐이다.

---

## 8. 문서/코드 동기화 체크리스트

Bambu bridge 동작을 바꾸면 다음 문서를 같이 확인한다.

- `개선안/14_bambulab_gcode_autoejection_runtime_plan.md`: 상세 개선안 및 검증 항목
- `docs/runtime/closed_loop_and_pages_reference.md`: runtime/API/Live GUI 계약
- `docs/gui/gui.md`: 화면 버튼, 상태, API surface
- `docs/tutorials/device_workspace_3dp_usage.ko.md`: 운영자 사용법
- `docs/tutorials/user_manual.ko.md`, `docs/tutorials/user_manual.en.md`: 일반 사용자 매뉴얼
- `docs/project/Project_guide.txt`: 전체 프로젝트 순서와 agent responsibility
- `REQUIREMENTS.md`: Bambu Studio/OrcaSlicer/ffmpeg/mqtt/ftps 관련 의존성

---

## 9. 현재 검증 경계

현재 코드/문서 기준으로 비파괴 검증이 끝난 범위와 실제 장비 검증으로 남겨야 하는 범위를 분리한다.

### 9.0 External-case contract

이 bridge는 Bambu printer를 단순히 "파일 전송 후 출력"하는 장치로 취급하지 않는다. 외부 사례를 대조하면 Bambu 자동 배출은 최소한 다음 contract를 동시에 만족해야 한다.

| Evidence plane | 운영 의미 | Bridge/GUI 표시 |
| --- | --- | --- |
| Artifact | BambuStudio/Orca/manual sliced artifact가 어떤 plate G-code를 포함하는지, 후처리 artifact가 원본과 어떻게 다른지 | source/patched path, sha256, `Metadata/plate_#.gcode`, sidecar manifest |
| Validation | 출력물 bounds, sweep envelope, skirt/brim/purge residue, homing/danger command 여부 | validation summary, blocker list, object bounds, sweep path |
| Transport | FTPS 또는 HTTP artifact route가 실제 프린터가 받을 수 있는 상태인지 | transfer result, fetch URL, sha256 match, `BAMBU_FTPS_TOO_MANY_CONNECTIONS` 등 전용 failure code |
| Runtime | MQTT `project_file` publish가 접수됐는지와 실제 printer state가 바뀌었는지 | publish sequence/topic, `gcode_state`, progress, subtask, post-publish observation |
| Bed-clear | 다음 job을 시작해도 되는지 | camera snapshot reference, operator/camera/vision decision, source/patched sha256 continuity, next-job gate |

Looprint 계열은 already-sliced G-code/3MF에 cooldown/push-off/loop logic을 삽입하는 방향이고, 3DQue/Infinity Flow 계열은 one-part center/front placement, release surface, purge residue, door/front path, 다중 높이 sweep을 강조한다. ha-bambulab/OpenBambuAPI 계열은 FTPS upload와 MQTT `project_file` start를 분리하고 AMS mapping을 별도 문제로 다룬다. ATR은 이 구조를 그대로 복제하지 않고, `artifact -> validation -> transfer -> guarded publish -> observation -> bed-clear` evidence chain으로 표준화한다.

이 문서에서 `published=true`는 physical ejection success를 뜻하지 않는다. 실제 성공은 post-publish observation, camera/operator evidence, bed-clear unlock이 같이 있어야 한다.

비파괴 검증 완료 범위:

- Bambu Studio CLI runner가 `--export-3mf`에 absolute path가 아니라 output directory 내부 basename을 전달한다.
- 명시 `load_settings`가 없을 때 runner는 Bambu Studio 기본 preset을 보존한다. `--load-settings`/`--load-filaments`를 자동 주입하지 않으며, 산출된 `.gcode` 또는 `.gcode.3mf`의 plate G-code에서 front test/intro/nozzle-load line block만 제거하고 md5 sidecar를 갱신한다.
- `/home/jin/다운로드/specimen(4).stl` 기준으로 `.gcode.3mf` 생성, 내부 `Metadata/plate_1.gcode` patch, md5 sidecar 갱신, validator 통과가 확인됐다.
- Bambu autoejection tail은 `source_plate_path`, `plate_id`, `loop_index`, material/bed placeholder, cooldown policy, purge/parking strategy, door/front assumption, toolhead-cover risk note를 artifact comment로 기록한다.
- `Validate G-code Preview` / `Validate Left|Center|Right`는 `validate_only=true`로 동작해 would-be tail과 validator evidence만 반환하며, `.autoeject.*` artifact나 manifest를 쓰지 않는다.
- `Pre-start Check`는 camera/status, slicing, optional native autoejection patch, HTTP route, start gate, SPC readiness를 병합하되 MQTT publish를 실행하지 않는다.
- `Video Status` 실패는 기존 device/progress/material status를 지우지 않는 계약으로 테스트된다.
- `.autoeject.*` publish ack 뒤에는 bed-clear required evidence가 저장되고, 다음 start gate는 bed-clear verified 전까지 차단된다. 이 evidence는 단순 checkbox가 아니라 가능한 경우 remote artifact URL, subtask name, source/patched artifact path와 sha256, sidecar manifest path, MQTT publish sequence/topic, post-publish status, camera snapshot reference를 함께 보관한다. 실제 완료 proof에는 별도 saved `printer.bambu.start_publish` response snapshot도 남기고, snapshot의 `ready_to_publish=true`, `start_enabled=true`, blocker 없음, remote path, publish sequence/topic, post-publish running state가 proof 본문과 일치해야 한다. 이후 operator가 `Mark Bed Clear`를 눌러 verified 상태를 갱신해도 기존 artifact/publish reference는 보존되어야 한다.
- `/printer` 브라우저 화면은 임시 FastAPI 서버와 Selenium/Firefox headless 1920x1080 렌더링으로 page identity, non-blank render, camera placeholder, `Video Status`, `Pre-start Check`, autoejection validation controls, standalone left/center/right artifact controls, `Mark Bed Clear` 표시를 확인했다. 같은 브라우저 경로에서 `Validate Center`는 validate-only API를 호출해 summary/detail/body에 validation pass, source plate, object bounds, sweep path를 표시했고 raw G-code line은 표시하지 않았으며 `.autoeject.*` artifact 파일 수도 증가하지 않았다. 이 검증은 GUI 표시와 DOM 연결 범위이며 physical publish/ejection을 의미하지 않는다.

2026-06-16 로컬 audit snapshot:

- `/home/jin/다운로드/specimen(4).stl` 기반 Bambu Studio slicing은 `.gcode.3mf` artifact 생성까지 통과했다.
- 동일 artifact에 대해 `Validate G-code Preview` 성격의 non-mutating 검증은 patched artifact나 manifest를 쓰지 않고 validator evidence만 반환해야 한다.
- `Generate Patched Artifact` 성격의 patch 실행은 `.autoeject.gcode.3mf`, sidecar manifest, 내부 `Metadata/plate_1.gcode.md5` 갱신까지 확인됐다.
- HTTP artifact route는 ATR 서버의 LAN IP URL로 server-side fetch 및 sha256 match가 확인됐다. 이 값은 프린터 publish를 실행했다는 뜻이 아니라, 프린터에 전달 가능한 URL 후보가 준비됐다는 뜻이다.
- 초기 수동-gate 버전의 `Pre-start Check` dry-run은 `camera_status`, optional native patch, HTTP artifact route까지 진행한 뒤 `BAMBU_START_DRY_RUN`, operator confirmation, Guardian approval, ejection checklist blocker로 의도적으로 막혔다. 현재 코드는 이 수동 checklist UI를 제거했고, 3DP GUI가 owner-managed publish 기본값을 보내며 backend는 artifact/camera/bed-clear/start-state blocker로 차단한다.
- 실제 장비 상태 조회 중 FTPS가 `421 too many connections` 계열로 거부되면 generic network failure가 아니라 `BAMBU_FTPS_TOO_MANY_CONNECTIONS`로 표시한다. 이 경우 MQTT/video plane이 살아 있더라도 FTPS upload-ready는 아니다.
- 3DP GUI visual QA에서는 `Video Status` 후 Bambu camera panel이 `proxy_ready`/RTSPS 또는 MJPEG proxy 상태를 표시하고, 이후 `Pre-start Check`가 실제 camera frame을 화면에 유지하는 것을 확인했다. 같은 화면에서 MQTT/progress/material card는 유지되고 FTPS blocker만 별도로 표시됐다.
- Autoejection panel visual QA에서는 `Save Autoejection Config`, `Validate G-code Preview`, `Generate Ejection Test Artifact`, `Generate Sweep Test Artifact`, `Generate Patched Artifact`, `Mark Bed Clear`, `Mark Not Clear`, standalone left/center/right artifact buttons가 렌더링됐다. `Validation Evidence`는 기본 접힘 상태이며, 화면에는 full raw G-code block을 표시하지 않는다.
- 2026-06-16 추가 pre-start audit에서는 실제 Bambu connection memory와 기존 `.gcode.3mf` artifact를 사용해 `0.0.0.0:7862` 임시 서버에서 `camera_status -> existing sliced artifact -> native autoejection patch -> HTTP artifact route -> start gate -> SPC readiness`를 호출했다. `HTTP artifact route`는 LAN IP URL로 `ok=true`, `printer_fetch_ready=true`였고, FTPS가 connection-limit 상태여도 HTTP route transfer evidence는 유지됐다. 과거 수동-gate 요청은 approval/checklist blocker 때문에 `blocked`로 남았지만, 현재 GUI 요청은 owner-managed publish 기본값을 사용한다. 따라서 현행 차단 지점은 artifact validity, camera frame requirement, bed-clear lock, printer safe state, post-publish observation이다.
- 같은 실제 API 경로에서 owner-managed publish 기본값과 camera/bed-clear/start-state evidence가 모두 통과하면 `Pre-start Check`는 `ready_to_publish_not_started`까지 도달한다. 이 상태에서도 `published=false`, `will_publish=false`가 유지되므로 실제 MQTT publish 또는 motion을 의미하지 않는다.
- `BAMBU_POST_EJECT_BED_NOT_CLEAR` gate도 실제 API 경로에서 확인했다. `/api/printer/bed-clear`에 `bed_clear_required=true`, `bed_clear_verified=false`를 저장하면 all-confirmed pre-start path도 `BAMBU_POST_EJECT_BED_NOT_CLEAR`로 차단된다. 이후 `bed_clear_required=false`, `bed_clear_verified=true`를 저장하면 같은 start gate는 다시 `ready_to_publish_not_started`로 풀린다. 검증 후 local bed-clear memory는 원상 복구했다.
- 2026-06-16 현재 코드 smoke에서는 임시 FastAPI 서버의 `/printer`가 `HTTP 200`과 3DP Printer GUI HTML을 반환했고, HTML 안에 `Bambu LAN Connection`, `Bambu G-code Autoejection`, `Pre-start Check`, `Video Status`, `Publish Start`, `Mark Bed Clear`, `Validate G-code Preview` control text가 존재했다. `/api/printer/status?mode=test`는 BambuLab X2D active profile과 device screen payload를 반환했고 `will_publish`/`start_enabled`가 비물리 조회에서 설정되지 않는 것을 확인했다. 같은 서버에서 Selenium/Firefox headless 렌더링은 상단 console과 autoejection section의 핵심 버튼이 실제 DOM에서 표시되는 것을 확인했다. 이 최신 확인은 rendered GUI smoke와 HTML/API smoke evidence이며 physical publish/ejection 검증은 아니다.

실제 장비 검증으로만 완료 처리할 수 있는 범위:

- supervised standalone center ejection 실제 motion 검증
- small disposable object live ejection 검증
- left/right position ejection 검증
- post-ejection camera snapshot evidence와 실제 bed-clear 판정 검증
- bed-clear 해제 후 다음 job start gate가 실제 프린터 상태와 일치하는지 검증

위 물리 검증이 끝나기 전에는 Bambu native autoejection을 production-safe 또는 unattended-ready로 문서화하지 않는다.

### 9.1 Supervised physical validation runbook

아래 항목은 실제 프린터 앞에서 operator가 확인할 때만 수행한다. 모든 단계는 `/api/printer/start-publish` 또는 GUI `Publish Start`를 통과해야 하며, 직접 MQTT `gcode_line` motion이나 profile start/end G-code overwrite로 우회하지 않는다.

| 순서 | 목적 | 실행 경로 | 완료 evidence |
| --- | --- | --- | --- |
| 1 | physical start 전 상태 고정 | `Video Status` -> `Pre-start Check` -> `SPC Readiness` | saved pre-start snapshot, Bambu active profile, camera frame/proxy, `.autoeject.*` artifact, `ready_to_publish_not_started`, `published=false`, `will_publish=false` |
| 2 | center standalone ejection 실제 motion | `Generate Ejection Test Artifact` center -> browser-confirmed `Publish Start` with owner-managed defaults | center artifact file with ATR marker and `atr_position=center`, saved `printer.bambu.start_publish` snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state, camera frame before/after, object moved to front-clearance/bin zone, no collision, no toolhead-cover/plate shift |
| 3 | disposable object live ejection | small disposable print using patched `.gcode.3mf` -> guarded `Publish Start` | print completion, autoejection tail execution observed, bed object removed, saved `printer.bambu.start_publish` snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state, `/api/printer/bed-clear` temporarily `required=true`, `verified=false` after publish, source/patched artifact files with matching sha256 and manifest reference |
| 4 | left/right lane validation | standalone left and right artifacts with the same gate | left/right artifact files, saved validation snapshots with matching position, saved start-publish snapshots with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state, no sweep outside envelope, validator blockers empty |
| 5 | post-ejection bed-clear | camera/operator confirms empty bed -> `Mark Bed Clear` | `memory/bambu_bed_clear_evidence.json` keeps `bed_clear_verified=true`, `blocking_code=""`, camera/operator/vision method, and source/patched sha256 matching the live `.autoeject.*` artifact |
| 6 | next-job gate consistency | run `Pre-start Check` or `/api/printer/start-gate` after bed-clear | saved start-gate snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, no `BAMBU_POST_EJECT_BED_NOT_CLEAR`, and printer idle/ready state matched |

각 단계의 evidence는 GUI 표시만으로 끝내지 않고 API response 또는 memory file path를 함께 남긴다. 특히 `published=true`는 motion 성공이 아니라 MQTT command accept evidence이므로, camera/visual evidence와 post-ejection bed-clear evidence가 같이 있어야 해당 단계 완료로 본다.

### 9.2 Completion audit CLI

실제 장비 검증 후에는 proof package를 기준으로 완료 감사를 실행한다. 이 감사는 non-actuating 도구이며 프린터를 움직이지 않는다.

```bash
./scripts/audit_bambu_autoejection_completion.py --write-template artifacts/printer/<run_id>/bambu/bambu_autoejection_physical_validation_<timestamp>.json --printer-profile-id bambulab_x2d_lab_01
./scripts/audit_bambu_autoejection_completion.py --proof-package artifacts/printer/<run_id>/bambu/bambu_autoejection_physical_validation_<timestamp>.json
./scripts/audit_bambu_autoejection_completion.py --latest
```

`--write-template`으로 만든 파일은 기본값이 모두 fail-closed다. operator가 실제 camera image, post-publish observation, bed-clear evidence, next-job gate evidence를 채우기 전에는 감사가 통과하면 안 된다.

감사가 `complete_evidence_verified`를 반환하려면 다음 항목이 모두 파일로 남아 있어야 한다.

- physical start precheck evidence: saved `/api/printer/bambu-prestart-check` snapshot with Bambu active profile, camera snapshot/proxy, `ready_to_publish_not_started`, `published=false`, `will_publish=false`
- center standalone ejection evidence: local center artifact with ATR marker and `atr_position=center`, before/after camera image, saved `/api/printer/start-publish` response snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state, no collision/toolhead-cover/build-plate shift
- disposable live ejection evidence: tail observed, object cleared, bed-clear lock, remote path, source/patched artifact files with matching sha256, patch manifest, saved `/api/printer/start-publish` response snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state
- left/right lane evidence: both lane artifact files, saved validation snapshots with matching position and empty validator blockers, and saved start-publish snapshots with `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state
- post-ejection bed-clear evidence: camera/operator/vision confirmation, matching live source/patched sha256, empty `blocking_code`
- next-job gate evidence: saved `/api/printer/start-gate` snapshot with `ready_to_publish=true`, `start_enabled=true`, no blockers, `BAMBU_POST_EJECT_BED_NOT_CLEAR` cleared, and printer idle/ready state matched

감사가 실패하면 Bambu autoejection은 아직 physical-complete가 아니다. 이 상태에서는 system docs, Live GUI report, tutorial에서 `production-safe`, `unattended-ready`, `physical success confirmed` 같은 표현을 쓰지 않는다.

### 9.3 Completion audit GUI/API

같은 completion audit은 3DP Device Workspace에서도 실행할 수 있다. GUI/API 경로는 CLI를 감싸는 운영자 편의 layer이며, 동작 경계는 CLI와 동일하다.

| GUI control | API | 동작 |
| --- | --- | --- |
| `Build Fail-Closed Proof Template` | `POST /api/printer/bambu-autoejection-proof-template` | fail-closed physical validation JSON template 생성. 프린터 통신/구동 없음 |
| `Run Completion Audit` | `POST /api/printer/bambu-autoejection-completion-audit` | 지정 proof package 또는 latest package 읽기/검증. 프린터 통신/구동 없음 |

API는 active provider가 Bambu일 때만 의미가 있다. Prusa 또는 다른 provider가 active profile이면 `BAMBU_PROOF_TEMPLATE_NOT_APPLICABLE` / `BAMBU_COMPLETION_AUDIT_NOT_APPLICABLE`로 차단해야 하며, proof template 파일도 새로 쓰면 안 된다. 즉 Bambu completion proof는 Bambu bridge 선택 상태에서만 만들거나 통과시킬 수 있다.

Proof template은 operator가 다음 evidence를 파일로 채우기 전까지 audit pass가 나면 안 된다.

Completion audit은 `published=true` 또는 MQTT publish ack만으로 완료를 인정하지 않는다. Proof package의 center standalone ejection 또는 disposable live ejection 항목에서 post-publish 상태가 `idle`, `ready`, `not_started` 계열이면 `BAMBU_PROJECT_FILE_ACCEPTED_BUT_NOT_STARTED`로 차단한다. 이 blocker는 "프린터가 명령을 받았을 수는 있지만 실제 출력/배출 시작 관찰이 없다"는 뜻이다.

- center standalone ejection artifact, saved start-publish snapshot, and before/after camera files; the artifact must contain the ATR marker plus `atr_position=center`, the publish snapshot must have `ready_to_publish=true`, `start_enabled=true`, no blockers, matching remote path, publish sequence/topic, and running post-publish state, and before/after images must be distinct files
- physical start precheck snapshot with `tool=printer.bambu.prestart_check`, `ready_to_publish_not_started`, `published=false`, and `will_publish=false`
- disposable live ejection post-publish observation, remote path, publish sequence/topic, saved start-publish snapshot, source/patched artifact file paths with sha256 matching the proof
- patch manifest with `schema=bambu_autoejection_artifact_manifest.v1`, matching source/patched sha256, and `validation.ok=true` with no validator blockers
- left/right lane validation/execution evidence, including local artifact files with ATR autoejection marker, matching `atr_position=left|right`, saved validation snapshot JSON files with empty blockers, and saved start-publish snapshots with matching remote path, publish sequence/topic, and running post-publish state
- post-ejection bed-clear evidence with `verification_method=operator|camera|vision` and source/patched sha256 values matching the disposable live ejection artifact
- next-job gate evidence, including a saved start-gate snapshot JSON rather than only proof booleans

따라서 `Build Fail-Closed Proof Template` 성공은 "검증 문서가 생성됨"만 뜻한다. `Run Completion Audit`이 `complete_evidence_verified`를 반환하기 전까지 Bambu native autoejection은 완료/무인운전 가능 상태가 아니다.

---

## 10. 참고 근거

- Bambu Studio CLI command manual: https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage
- Bambu Lab LAN mode: https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode
- Bambu Lab printer network ports: https://wiki.bambulab.com/en/general/printer-network-ports
- Bambu Lab third-party integration / Developer Mode: https://wiki.bambulab.com/en/software/third-party-integration
- OpenBambuAPI MQTT notes: https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
- BambuBoard LAN liveview / RTSPS setup notes: https://github.com/t0nyz0/BambuBoard/blob/main/VIDEO_STREAMING_SETUP.md
- ha-bambulab upload/start discussion: https://github.com/greghesp/ha-bambulab/discussions/307
- OrcaSlicer auto-ejection proposal: https://github.com/OrcaSlicer/OrcaSlicer/discussions/7693
- Looprint multi-loop G-code/3MF builder: https://github.com/NickiAndersen/looprint
- BambuLab Reddit auto-ejection queue discussion: https://www.reddit.com/r/BambuLab/comments/11wexiz/automatic_print_ejection_and_print_queue/
- BambuLab Reddit FarmLoop build plate shift failure: https://www.reddit.com/r/BambuLab/comments/1k7ffzl/a1_mini_auto_ejection_fail_build_plate_shifts/
- P1S motorized door/eject via G-code API discussion: https://www.reddit.com/r/BambuLab/comments/1jfv2of/i_built_an_autoeject_system_and_motorized_door/
- Factorian Designs P1/X1 automation video: https://www.youtube.com/watch?v=Vxj1ii6dPYo
- Bambu enclosed-printer auto-ejection kit article: https://www.tomshardware.com/3d-printing/new-auto-ejection-tool-for-bambu-lab-print-farms-automatically-ejects-finished-3d-prints-from-the-machine-usd129-kit-includes-auto-door-opener-and-special-bed-surface-for-frictionless-part-ejection

위 링크들은 기능을 그대로 복제하기 위한 원본 코드가 아니라, ATR의 안전 gate와 evidence 요구사항을 정하는 근거다. 특히 Bambu enclosed printer 자동 배출은 door/front clearance, release surface, toolhead cover, camera evidence, bed-clear confirmation이 같이 있어야 반복 운전 설명으로 인정한다.
