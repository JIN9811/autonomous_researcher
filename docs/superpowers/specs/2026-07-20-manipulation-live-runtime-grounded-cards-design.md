# Manipulation Live Runtime Grounded Cards Design

## 1. 목적

Manipulation Agent의 Live GUI 하단 영역을 개념적 보고서에서 실제 운용 관제 화면으로 전환한다.

기본 화면에는 다음 질문에 실제 데이터로 답하는 카드만 남긴다.

1. 어떤 task와 policy가 현재 실행 중인가?
2. 실행을 계속해도 되는가?
3. manipulation 완료 조건 중 무엇이 충족됐는가?
4. 실행이 끝났다면 실제 결과와 정량 evidence는 무엇인가?

기존 LeRobot 제어 루프, rollout 명령 생성, 포트 소유권, 카메라 lease, Vision handoff, Guardian 호환 계약은 변경하지 않는다. 이번 작업은 관측 데이터 계약과 Live GUI 표현 계층을 정리하는 작업이다.

## 2. 현재 문제

현재 `manipulation_agent_report.v1`의 일부 필드는 실제 센서·로그·이벤트가 아니라 화면 구성을 위해 계산하거나 생성한 값이다.

대표 사례:

- 실제 시간이 없을 때 사용하는 `21.4 s` 기본 실행시간
- progress 기반으로 계산한 path efficiency와 joint velocity 백분율
- 실제 grasp planner가 생성하지 않은 Top Grasp 후보 점수
- stage taxonomy로 만든 waypoint 목록
- 9개 점으로 합성한 XYZ trajectory
- 고정 좌표로 만든 reachability hotspot
- 실제 collision engine 결과 없이 `clear`로 표시하는 safety check
- 합성 trajectory에서 만든 object pose frame
- 규칙으로 생성한 quality grade

이 값들은 연구용 mockup이나 보고서 예시로는 사용할 수 있지만 실제 운용 화면에 `MEASURED` 상태처럼 표시하면 안 된다.

## 3. 비협상 원칙

### 3.1 허용되는 데이터 출처

Live GUI 카드에는 다음 provenance만 허용한다.

- `MEASURED`: 로봇, 카메라, 포트, 프로세스 또는 장비에서 직접 수집한 값
- `DERIVED`: 공개된 threshold와 결정론적 규칙으로 실측값에서 계산한 상태
- `EVENT`: 실제 start, stop, handoff, E-stop, completion 이벤트
- `CONFIGURED`: 사용자가 저장한 task, policy, checkpoint, timeout 설정
- `ARTIFACT`: 실제 실행에서 생성되어 파일로 저장된 evidence

`SIMULATED`, `PLACEHOLDER`, `CONCEPTUAL` 값은 Live GUI runtime 카드에 표시하지 않는다.

### 3.2 값 부재 처리

- 값이 없으면 `-`를 채운 대형 카드를 만들지 않는다.
- 필수 상태는 `unknown` 또는 `waiting`으로 표시한다.
- 선택 상태는 해당 행이나 카드 자체를 숨긴다.
- `unknown`은 `pass`로 취급하지 않는다.
- 이전 세션 값은 새 세션 값처럼 재사용하지 않는다.

### 3.3 렌더링 경계

- Three.js viewer와 ECharts graph는 세션 중 한 번만 생성한다.
- SSE/WebSocket 갱신은 텍스트, 상태 class, graph series만 patch한다.
- 하단 카드 갱신 때문에 Live Robot Pose나 Policy Tracking canvas를 재생성하지 않는다.
- 완료 후 최종 상태와 artifact 링크는 다음 세션 전까지 유지한다.

## 4. 기본 화면 구성

### 4.1 기존 핵심 카드

다음 카드는 유지한다.

#### Live Robot Pose

- measured follower joint pose
- policy target ghost
- 현재 robot motion state
- grasp success/failed gripper overlay
- cube upright yaw-only visualization

데이터 출처: `motor_events.jsonl`, `atr.robot_joint_telemetry.v1`.

#### Policy Tracking

- 선택 관절의 measured follower와 requested policy target
- elapsed time
- terminal PNG, CSV, JSONL, summary artifact

데이터 출처: `motor_events.jsonl`, `policy_tracking_summary.json`.

#### Runtime State Strip

기존 `Robot Motion State` 대형 카드를 한 줄 관제 strip과 확장 가능한 details로 축소한다.

기본 표시:

- measured: `HOME`, `MOVING`, `GRASPING`, `UNGRASPING`
- policy: `HOME`, `MOVING`, `GRASPING`, `UNGRASPING`
- grasp: `IDLE`, `PENDING`, `SUCCESS`, `FAILED`
- home gate: `PASS`, `STABILIZING`, `OUTSIDE RANGE`, `UNKNOWN`

확장 details:

- measured/policy state reason
- confidence
- measured/policy gripper value
- contact gap and threshold
- per-joint home range 판정

## 5. 유지할 하단 카드

기본 화면에는 세 개의 runtime 카드만 상시 표시한다.

### 5.1 Runtime Execution

기존 `Execution Control`, `Task Route`, `Policy Runtime`의 실제 필드만 통합한다.

필수 필드:

- `run_id`
- `rollout_session_id`
- `task_id`
- `task_instruction`
- `specimen_id`
- `source_location`
- `target_location`
- `policy_type`
- `policy_checkpoint_path`
- `process_pid`
- `runtime_status`
- `current_stage`
- `started_at`
- `elapsed_s`

규칙:

- `elapsed_s`는 실제 timestamp 또는 process monotonic time으로만 계산한다.
- policy 경로는 실제 실행 명령에 들어간 최종 resolved path를 사용한다.
- stage는 실제 stage/event에서만 갱신한다.
- task plan이 없으면 route 그림이나 waypoint를 만들지 않는다.

### 5.2 Runtime Interlocks

기존 `Safety Gate / Object Pose`에서 실제 인터록만 분리한다.

필수 gate:

- follower port lease
- camera lease returned to VLA
- policy process health
- measured home gate
- E-stop / safe-stop 상태
- Vision pickup readiness
- workspace-clear signal이 실제로 존재할 때의 상태

각 gate 계약:

```json
{
  "id": "camera_lease",
  "status": "pass|block|waiting|unknown",
  "source_type": "MEASURED|DERIVED|EVENT|CONFIGURED|ARTIFACT",
  "source": "active_camera_lease.returned_to_vla",
  "observed_at": "ISO-8601",
  "reason": "camera returned to rollout owner"
}
```

규칙:

- 실측되지 않은 collision, velocity, safety-zone 항목을 자동으로 `clear` 처리하지 않는다.
- block 상태에는 실제 failure code와 recovery action만 표시한다.
- operator action이 필요한 경우에만 ATT 알림을 생성한다.

### 5.3 Completion Verification

기존 `Vision / UTM Verification`을 실제 종료 인터록 카드로 전환한다.

고정 순서:

1. `ungrasping_seen`
2. `home_after_ungrasping`
3. `utm_snapshot_requested`
4. `specimen_detected_at_utm`
5. `ready_to_stop_rollout`
6. `rollout_stop_confirmed`
7. `ready_for_equipment`

각 단계는 `waiting`, `active`, `pass`, `failed` 중 하나를 사용한다.

필수 evidence:

- sequence 또는 event id
- timestamp
- camera key
- confidence
- evidence path
- rollout stop result
- final handoff status

Vision evidence가 없으면 완료로 표시하지 않는다. Rollout 프로세스가 종료되지 않았으면 다음 agent로 넘기지 않는다.

## 6. 종료 후 조건부 카드

다음 두 카드는 rollout이 terminal 상태가 된 후에만 생성한다.

### 6.1 Run Result

필드:

- final status
- success 또는 failure stage
- terminal reason / failure code
- rollout stop status
- Vision verification status
- home return status
- next agent
- artifact directory

`quality_grade`처럼 실제 기준이 없는 등급은 표시하지 않는다.

### 6.2 Run Metrics

실제 artifact에서 계산 가능한 값만 표시한다.

- sample count
- measured duration
- effective action rate
- per-joint MAE / RMSE / max error
- grasp attempts
- grasp success / failed count
- grasp success rate
- post-place verification latency
- stop latency

다음 값은 실제 계산 엔진이 추가되기 전까지 금지한다.

- path efficiency
- reachability score
- collision score
- safety score
- grasp candidate score
- pose error

## 7. 제거하거나 다른 카드에 흡수할 항목

| 기존 카드 또는 내용 | 처리 |
|---|---|
| Execution Control | `Runtime Execution`에 통합 |
| Task Route | 실제 task source/target만 `Runtime Execution`에 통합 |
| Policy Runtime | `Runtime Execution`에 통합 |
| Performance KPIs | 실제 terminal artifact 기반 `Run Metrics`로 교체 |
| Grasp / Path Plan | 제거. 실제 planner가 생기면 별도 재도입 |
| waypoint table | 제거. 실제 waypoint 명령이 있을 때만 재도입 |
| Active Camera / Workspace | camera lease는 `Runtime Interlocks`; 영상은 Vision Agent에서 관리 |
| Reachability Map | 제거 |
| Safety Gate / Object Pose | 실제 gate만 `Runtime Interlocks`로 이동 |
| 합성 Object Pose | 제거. Vision 측정값 링크만 허용 |
| Motion Trace | 제거. `Policy Tracking`과 중복 |
| Vision / UTM Verification | `Completion Verification`으로 교체 |
| Robot Task Result | terminal 전용 `Run Result`로 교체 |

## 8. Canonical View Contract

Live GUI는 기존 report 전체를 직접 조합하지 않고 실제 데이터만 정규화한 view model을 소비한다.

권장 schema:

```json
{
  "schema": "manipulation_runtime_view.v1",
  "session_id": "...",
  "status": "idle|preflight|running|verifying|stopping|complete|failed|blocked",
  "execution": {},
  "interlocks": [],
  "completion": {
    "steps": [],
    "current_step": "...",
    "terminal": false
  },
  "result": null,
  "metrics": null,
  "freshness": {
    "observed_at": "...",
    "age_s": 0.0,
    "stale": false
  },
  "provenance": []
}
```

### View model source mapping

- `execution`: `manipulation_report.task`, resolved rollout payload, `policy_runtime`, process/session registry
- `interlocks`: `port_lease`, `active_camera_lease`, measured `home_pose`, E-stop runtime state, Vision readiness event
- `completion`: `PostPlaceInterlock`, `vision_manipulation_completion.v1`, `rollout_stop`, graph handoff event
- `metrics`: `policy_tracking_summary.json`, `grasp_outcomes.json`, action log timestamps
- `result`: terminal manipulation report와 실제 handoff packet

`manipulation_agent_report.v1`은 Guardian 및 과거 run 호환을 위해 유지할 수 있지만 Live GUI 신규 카드는 `manipulation_runtime_view.v1`을 우선 사용한다.

## 9. 상태 및 표시 규칙

### IDLE

- Live Robot Pose는 마지막 terminal session을 조회용으로 표시할 수 있다.
- runtime 세 카드에는 현재 실행이 없다고 표시한다.
- 이전 run의 interlock을 현재 상태처럼 표시하지 않는다.

### PREFLIGHT / RUNNING

- runtime 세 카드를 표시한다.
- Run Result와 Run Metrics는 생성하지 않는다.
- 상태 변경은 부분 patch한다.

### VERIFYING / STOPPING

- Completion Verification을 강조한다.
- policy process가 살아 있으면 `complete`를 표시하지 않는다.

### COMPLETE / FAILED / BLOCKED

- Run Result를 생성한다.
- 실제 artifact가 준비되면 Run Metrics를 생성한다.
- 실패 시 마지막 유효 frame과 로그는 유지하되 성공 상태는 유지하지 않는다.

## 10. 백엔드 변경 범위

1. 실제 runtime source를 합치는 `manipulation_runtime_view` builder를 추가한다.
2. synthetic report 필드를 신규 view model에 복사하지 않는다.
3. `manipulation_agent_report.v1` legacy payload는 즉시 삭제하지 않는다.
4. terminal artifact 생성 후 view model의 metrics/result를 갱신한다.
5. 동일 session/event에 대한 갱신은 idempotent하게 처리한다.
6. 기존 rollout start/stop, MotorBus, camera acquisition 코드는 수정하지 않는다.

## 11. 프론트엔드 변경 범위

1. 현재 telemetry 카드 세 개를 유지하되 Robot Motion State를 compact strip으로 전환한다.
2. 하단 conceptual renderer를 `Runtime Execution`, `Runtime Interlocks`, `Completion Verification`으로 교체한다.
3. terminal일 때만 `Run Result`, `Run Metrics`를 추가한다.
4. 빈 카드와 `-` 행을 자동으로 제거한다.
5. 상세값은 카드 클릭 시 inline details로 펼친다.
6. 카드 patch 중 Three.js/ECharts DOM을 보존한다.
7. legacy report만 존재하는 과거 run은 `Legacy report` details에서 조회할 수 있지만 기본 runtime 카드로 승격하지 않는다.

## 12. 오류 처리

- source timestamp가 freshness 기준을 넘으면 `stale`로 표시한다.
- source 간 session id가 다르면 view model 생성을 block하고 `SESSION_MISMATCH`를 기록한다.
- process status와 report status가 충돌하면 process registry를 실행 상태의 authority로 사용한다.
- Vision completion과 rollout stop이 충돌하면 `stopping`을 유지한다.
- artifact 파싱 실패는 실행 결과를 바꾸지 않고 metrics 카드만 `artifact unavailable`로 처리한다.

## 13. 테스트 명세

### Unit

- view builder가 synthetic KPI, trajectory, hotspot, pose frame을 반환하지 않는다.
- 각 필드에 provenance와 freshness가 존재한다.
- 누락된 선택 필드는 숨겨지고 필수 gate는 `unknown`이 된다.
- process가 살아 있으면 report가 complete여도 view status는 running/stopping이다.
- Vision 검증 없이 ready-for-equipment가 생성되지 않는다.
- terminal artifact만 Run Metrics를 생성한다.

### Integration

- test virtual, installed printer, actual print 경로가 동일 view schema를 제공한다.
- active-cam -> rollout -> UTM verification -> stop -> equipment 흐름이 단계별로 갱신된다.
- E-stop, resume, reset 후 같은 session 또는 새 session 상태가 정확히 반영된다.
- 완료 전 다음 agent로 넘어가지 않는다.
- legacy report 계약은 Guardian 테스트를 계속 통과한다.

### Browser

- 기본 화면에는 세 개 runtime 카드만 표시된다.
- terminal 전에는 Result/Metrics 카드가 없다.
- terminal 후 Result/Metrics가 한 번만 추가된다.
- 카드 접기/펼치기와 스크롤이 canvas를 재생성하지 않는다.
- 30분 replay에서 DOM node, WebGL context, RSS가 지속 증가하지 않는다.
- 값이 없는 카드와 synthetic 숫자가 화면에 나타나지 않는다.

### Real log replay

- 최근 rollout JSONL로 measured/policy/motion/grasp/home 상태를 재생한다.
- `pending` grasp attempt가 terminal artifact에 남지 않는다.
- UI의 attempt count와 `grasp_outcomes.json`이 일치한다.

## 14. 구현 순서

1. 기존 conceptual field를 명시적으로 검출하는 실패 테스트를 추가한다.
2. `manipulation_runtime_view.v1` builder와 API 응답을 추가한다.
3. 실제 source mapping과 provenance/freshness를 구현한다.
4. 신규 세 카드 renderer를 구현한다.
5. terminal Result/Metrics 조건부 renderer를 구현한다.
6. 기존 conceptual 카드 renderer를 기본 경로에서 제거한다.
7. browser replay와 메모리 안정성 검증을 수행한다.
8. runtime guideline, Live GUI 설명, schema 문서를 갱신한다.

## 15. 완료 기준

- Manipulation Agent 기본 화면에 개념적 KPI나 합성 trajectory가 없다.
- 기본 하단 카드는 `Runtime Execution`, `Runtime Interlocks`, `Completion Verification` 세 개다.
- `Run Result`, `Run Metrics`는 terminal 상태에서만 나타난다.
- 모든 표시값의 출처가 MEASURED, DERIVED, EVENT, CONFIGURED, ARTIFACT 중 하나로 추적된다.
- 실제 데이터가 없으면 카드가 숨겨지거나 `unknown`으로 표시되며 임의 값으로 채워지지 않는다.
- 기존 제어 루프와 장비 통신 경로에는 변경이 없다.
- test mode와 최근 실제 rollout replay에서 frontend-backend full path가 검증된다.

