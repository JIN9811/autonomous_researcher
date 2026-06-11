# 12. LeLab 기반 ROBOTIS LeRobot GUI 고도화안

작성일: 2026-06-11  
대상: `web/templates/lerobot.html`, `web/static/lerobot.js`, `device_bridges/lerobot_bridge.py`, `configs/lerobot.yaml`, `docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`, `tests/unit/test_lerobot_bridge.py`, `tests/ui/*`

참고한 외부 레포:

- LeLab clone 경로: `/home/jin/reference_repos/leLab`
- LeLab 확인 commit: `ba22182 fix(train): correct pi0_fast policy type value in dropdown`
- LeLab 성격: Hugging Face LeRobot 공식 GUI. FastAPI + React/Vite 기반으로 calibrate, teleoperate, record, train, replay/inference를 단일 브라우저 UI로 제공한다.

현재 ATR 기준:

- ATR 확인 commit: `ff47c9c Stabilize LeRobot rollout and Pi0.5 training defaults`
- 현재 GUI 경로: `/lerobot`
- 현재 API 경로: `/api/lerobot/*`
- 현재 주요 장비 profile: `robotis_omx_ai`
- 현재 Pi0.5 runtime: `lerobot-pi05-torch211`

---

## 1. 결론

LeLab은 우리 시스템에 그대로 이식할 대상이 아니다.

이유:

- LeLab은 현재 SO-101 leader/follower 중심으로 설계되어 있다.
- 우리 시스템은 ROBOTIS OMX-AI, Manipulation Agent, Guardian, Live/Test/Fault-injection mode, autonomous closed-loop pipeline을 포함한다.
- 우리 GUI는 단순 LeRobot 실행기가 아니라 ATR Device Workspace와 agent runtime에 연결된 제어면이다.

따라서 적용 방향은 다음이 맞다.

> LeLab의 "초보자도 CLI 없이 LeRobot workflow를 완주하게 만드는 UX", "job card", "readiness gate", "recording phase", "single tab guard", "checkpoint 중심 inference" 패턴을 가져오되, backend와 runtime contract는 ATR의 기존 LeRobot bridge와 Manipulation Agent 구조를 유지한다.

즉, LeLab을 reference implementation으로 사용하고, 우리 GUI는 "ROBOTIS LeRobot Guided Control Surface"로 고도화한다.

---

## 2. 현재 ATR LeRobot GUI 상태

현재 `/lerobot`는 이미 많은 기능을 가진다.

존재하는 기능:

- profile/mode 선택
- follower/leader port detection 및 저장
- 다중 camera key 관리
- teleoperation start/stop
- recording start/next/retry/finish/force stop
- LeRobot dataset visualization
- policy training
- policy/checkpoint listing
- rollout/inference
- Manipulation Agent bridge
- TTS 안내
- live/test/replay/fault-injection mode
- Pi0.5 전용 training/rollout 옵션
- session list와 command preview/log tail 표시

현재 강점:

- ROBOTIS OMX-AI 실장비와 맞는 CLI command를 이미 생성한다.
- `/api/lerobot/*`를 통해 GUI와 CUI/agent 호출이 같은 bridge를 사용한다.
- Pi0.5 전용 conda env, torchcodec fallback, v2.1 -> v3.0 dataset 변환, checkpoint/policy path 처리가 이미 들어가 있다.
- Manipulation Agent에서 rollout 옵션을 재사용할 수 있는 구조가 있다.

현재 약점:

- 한 화면에 모든 입력값이 노출되어 사용 흐름이 길고 복잡하다.
- device setup, recording, training, rollout 상태가 각각 따로 보여서 "지금 다음에 무엇을 해야 하는지"가 즉시 보이지 않는다.
- LeLab처럼 robot readiness와 job 상태를 card 단위로 요약하는 구조가 부족하다.
- training job, checkpoint, rollout이 같은 policy lifecycle로 묶여 보이지 않는다.
- recording 중 episode phase, operator action, camera readiness가 더 명확해야 한다.
- rollout 실패 원인이 "정책/체크포인트 문제", "포트/캘리브레이션 문제", "카메라 문제", "HF/DNS 문제", "action queue 문제" 중 어디인지 UI가 즉시 분리해주지 못한다.
- 현재 `web/static/lerobot.js`가 지나치게 커져서 유지보수가 어려워지고 있다.

---

## 3. LeLab에서 가져올 핵심 패턴

### 3.1 Single Tab Guard

LeLab은 robot control을 여러 탭에서 동시에 시도하지 못하도록 `SingleTabGuard`를 둔다.

우리 적용 방향:

- `/lerobot` 진입 시 browser tab ownership을 부여한다.
- 동일 browser에서 두 번째 `/lerobot` 탭이 열리면 read-only mode로 진입시킨다.
- live mode에서 teleop/record/rollout은 owner tab에서만 가능하게 한다.
- test mode는 다중 탭 허용 가능하지만, session status는 동일하게 읽는다.

적용 이유:

- ROBOTIS serial bus는 중복 open에 약하다.
- recording/rollout 중 다른 탭에서 stop/start가 섞이면 장비 상태가 꼬인다.

### 3.2 Robot Readiness 중심 Landing

LeLab landing은 "로봇 선택 -> 준비 상태 -> 할 수 있는 작업"으로 흐른다.

우리 적용 방향:

- `/lerobot` 최상단을 단순 hero가 아니라 Robot Readiness Board로 바꾼다.
- readiness card는 다음 상태를 한 줄로 보여준다.
  - profile
  - mode
  - follower port
  - leader port
  - camera map
  - calibration presence
  - current active workflow
  - live gate status
  - latest policy/checkpoint
  - latest dataset

현재 긴 profile/path 입력 섹션은 접고, readiness에서 부족한 항목을 클릭하면 해당 setup 섹션으로 이동하게 한다.

### 3.3 Guided Setup Wizard

LeLab은 calibrate/port/config를 사용자가 흐름대로 처리하게 만든다.

우리 적용 방향:

- Device Port Setup을 wizard 형태로 재구성한다.
- 단계:
  1. profile 선택
  2. follower identity 확인
  3. leader identity 확인
  4. camera key 확인
  5. calibration/check file 확인
  6. dry-run command preview
  7. live gate confirmation

중요:

- port 번호 자체보다 `/dev/serial/by-id/*`나 saved device identity를 우선한다.
- camera도 index만 저장하지 말고 key + device identity + 마지막 정상 index를 같이 저장한다.
- 사용자가 포트를 다시 꽂아도 readiness board가 "찾은 identity / 현재 path"를 갱신한다.

### 3.4 Recording Phase Card

LeLab `record.py`는 recording state를 `preparing`, `recording`, `resetting`, `completed`로 나눈다.

우리 적용 방향:

- Recording 섹션은 아래 상태를 명확히 보여준다.
  - dataset repo id
  - task text
  - current episode / total episode
  - phase: preparing, recording, reset, saved, completed, failed
  - elapsed time
  - next expected operator action
  - keyboard equivalent: right/left/esc
  - camera map status
  - latest log tail

버튼 구조:

- Start Recording
- Save Episode / Next
- Retry Episode
- Finish Recording
- Force Stop

중요:

- 버튼 하단 로그만 보여주지 말고, 현재 episode phase를 card 상단에서 바로 보여준다.
- TTS 문구도 phase와 맞춰 느리게 안내한다.

### 3.5 Job Card와 Checkpoint Dropdown

LeLab은 training job과 checkpoint를 card로 보여준다.

우리 적용 방향:

- Training 섹션을 "입력 폼 + 로그"가 아니라 "Job Board"로 바꾼다.
- 각 job card는 다음을 가진다.
  - job name
  - policy type: act, pi05, pi0, pi0fast
  - dataset repo id
  - output dir
  - current step / target step
  - latest checkpoint
  - last log time
  - status: queued, starting, running, completed, failed, cancelled
  - actions: Resume, Stop, Open Logs, Use Checkpoint for Rollout

Checkpoint dropdown은 job card 안에 넣는다.

효과:

- training과 rollout이 끊어진 기능처럼 보이지 않는다.
- 사용자가 2000 checkpoint와 3000 checkpoint를 비교하기 쉬워진다.
- Pi0.5에서 "2000은 정상, 3000은 튐" 같은 실험적 판단이 GUI에 남는다.

### 3.6 Rollout Setup과 Active Rollout 분리

LeLab `rollout.py`는 setup time과 rollout active time을 분리하려고 stdout marker를 감시한다.

우리 적용 방향:

- Rollout 시작 후 UI 상태를 아래처럼 나눈다.
  - resolving policy
  - loading model
  - connecting robot
  - connecting cameras
  - waiting rollout marker
  - active rollout
  - stopping
  - stopped
  - failed

Pi0.5 전용 진단:

- action count
- action queue size
- queue refresh threshold
- RTC execution horizon
- guidance weight
- max relative target
- temporal ensemble status
- last action timestamp
- delay warning count
- port conflict warning

사용자 관점:

- "정책 로딩 중이라 느린 것"과 "로봇이 명령을 못 받는 것"을 구분해야 한다.
- stuck 느낌이 날 때 action queue가 큰지, checkpoint가 안 맞는지, task text가 안 맞는지 구분해야 한다.

### 3.7 Error Explanation Card

LeLab은 toast와 상태 메시지로 사용자에게 이유를 설명한다.

우리 적용 방향:

- Bridge error를 원문 stack trace로만 보여주지 않는다.
- UI에는 "원인 분류 + 다음 조치"를 먼저 보여준다.
- 상세 log_tail은 접힌 상태로 둔다.

권장 분류:

- `PORT_BUSY`
- `ROBOT_NOT_READY`
- `CAMERA_BUSY`
- `CALIBRATION_REQUIRED`
- `POLICY_PATH_INVALID`
- `CHECKPOINT_INCOMPATIBLE`
- `HF_NETWORK_REQUIRED`
- `DATASET_SCHEMA_INVALID`
- `ACTION_QUEUE_STALE`
- `LIVE_GATE_DISABLED`
- `SUBPROCESS_EXITED`

Guardian 연계:

- live mode에서 위험도가 높은 에러는 Guardian incident로 보낸다.
- 단순 설정 누락은 GUI guidance로 해결하게 한다.

---

## 4. 목표 화면 구조

### 4.1 상단: Robot Readiness Board

현재 hero 영역을 줄이고 다음 card들로 바꾼다.

- Robot Profile
- Device Readiness
- Dataset
- Policy
- Active Workflow
- Safety Gate

각 card는 세 줄 이내로 표시한다.

예시:

```text
ROBOTIS OMX-AI
follower ready / leader ready / cameras 2
live gate confirmed
```

### 4.2 Quick Action Row

LeLab처럼 사용자가 바로 해야 할 작업을 버튼으로 제공한다.

버튼:

- Setup Robot
- Teleoperate
- Record Dataset
- Visualize Dataset
- Train Policy
- Run Rollout
- Manipulation Agent
- Open Logs

버튼은 현재 readiness에 따라 enabled/disabled 처리한다.

### 4.3 Workflow Cards

각 기능은 독립 card로 유지하되, 기본은 접힌 상태가 맞다.

권장 기본 펼침:

- Robot Readiness Board
- Active Workflow Monitor
- 최근 session/output

권장 기본 접힘:

- Device setup
- Local paths
- Advanced training parameters
- Advanced rollout parameters
- Visualization options
- Manual port override

### 4.4 Active Workflow Monitor

LeLab의 job state와 우리 session state를 합쳐 하나의 모니터로 둔다.

표시:

- current workflow
- session id
- pid
- elapsed
- status
- current step
- log tail
- stop action
- owner tab

recording, training, rollout 모두 여기서 현재 상태를 볼 수 있어야 한다.

---

## 5. Backend/API 개선 방향

### 5.1 기존 API 유지

유지할 것:

- `/api/lerobot/config`
- `/api/lerobot/session/*`
- `/api/lerobot/teleoperate/*`
- `/api/lerobot/record/*`
- `/api/lerobot/train/*`
- `/api/lerobot/rollout/*`
- `/api/lerobot/manipulation/*`
- `device_bridges/lerobot_bridge.py`
- `configs/lerobot.yaml`

이유:

- GUI, CUI, Manipulation Agent, tests가 같은 bridge를 써야 한다.
- LeLab처럼 별도 SO-101 backend를 하나 더 붙이면 우리 agent loop와 분리된다.

### 5.2 Session/Job Registry 강화

현재 session memory를 다음 개념으로 정리한다.

공통 session 필드:

- `session_id`
- `workflow`
- `profile_id`
- `mode`
- `status`
- `pid`
- `command_preview`
- `log_path`
- `started_at`
- `updated_at`
- `completed_at`
- `returncode`
- `error_class`
- `operator_message`
- `next_action`

training job 추가 필드:

- `dataset_repo_id`
- `policy_type`
- `output_dir`
- `checkpoint_dir`
- `current_step`
- `target_steps`
- `latest_checkpoint`
- `resume_from`

rollout job 추가 필드:

- `policy_path`
- `task`
- `action_count`
- `queue_depth`
- `rtc_horizon`
- `queue_refresh_threshold`
- `max_relative_target`
- `rollout_started_at`

recording job 추가 필드:

- `dataset_repo_id`
- `single_task`
- `current_episode`
- `num_episodes`
- `phase`
- `saved_episodes`
- `camera_map`

### 5.3 Mutual Exclusion을 명시화

LeLab은 teleoperation/recording/inference가 같은 장비를 두고 충돌하지 않도록 active flag를 둔다.

우리 적용:

- same profile + same robot port 기준으로 active lock을 둔다.
- teleop, record, rollout, manipulation-agent-rollout은 같은 robot bus를 동시에 열 수 없다.
- training과 visualization은 robot bus를 쓰지 않으므로 병렬 가능하다.
- live mode에서 force stop은 해당 profile의 robot 관련 live subprocess만 종료한다.

### 5.4 Streaming Status

현재 polling이 많다. 개선 방향은 다음 중 하나다.

권장 1순위:

- `/api/lerobot/events` SSE endpoint 추가
- session/job event를 training/recording/rollout 공통으로 stream

대안:

- 기존 polling 유지하되, active workflow monitor만 짧은 주기로 갱신
- 완료된 session card는 재렌더링하지 않는다.

선택 기준:

- 빠른 안정화는 polling 유지가 유리하다.
- 장기적으로는 SSE가 Live GUI와 일관된다.

---

## 6. Frontend 구조 개선 방향

### 6.1 `lerobot.js` 분할

현재 `web/static/lerobot.js`는 단일 파일이 너무 크다.

권장 분할:

- `web/static/lerobot/state.js`
  - config/session/profile 상태
- `web/static/lerobot/api.js`
  - fetch wrapper와 endpoint 호출
- `web/static/lerobot/render_readiness.js`
  - readiness board
- `web/static/lerobot/render_jobs.js`
  - session/job cards
- `web/static/lerobot/device_setup.js`
  - follower/leader/camera setup
- `web/static/lerobot/recording.js`
  - recording payload와 phase UI
- `web/static/lerobot/training.js`
  - train payload와 job card
- `web/static/lerobot/rollout.js`
  - rollout payload와 active monitor
- `web/static/lerobot/manipulation_agent.js`
  - Manipulation Agent bridge

주의:

- 첫 구현에서는 대규모 분할보다 기능 유지가 우선이다.
- 파일 분할은 test가 있는 상태에서 단계적으로 진행한다.

### 6.2 폼은 줄이고 상태를 앞으로

현재 많은 값이 항상 화면에 보인다.

개선:

- 기본 경로와 profile 값은 readiness card에 표시한다.
- 수정은 "Edit" 혹은 setup wizard에서 한다.
- advanced parameter는 접는다.
- Pi0.5 주요 옵션은 rollout card에서 기본값과 설명을 같이 보여준다.

### 6.3 GUI와 CUI 상호호환

모든 GUI action은 동일한 backend payload를 남겨야 한다.

필수:

- GUI에서 실행한 command는 CUI에서 재현 가능한 JSON/payload로 저장한다.
- CUI/agent가 실행한 session도 GUI job card에 나타난다.
- 서버 재접속 후에도 active training/rollout 상태를 복원한다.

---

## 7. ROBOTIS/Pi0.5 특화 개선

### 7.1 Port Identity

ROBOTIS OMX-AI는 `/dev/ttyACM0`와 `/dev/ttyACM1` 순서가 바뀔 수 있다.

필수:

- follower/leader는 saved id 기반으로 resolve한다.
- 현재 port path와 saved identity를 동시에 보여준다.
- mismatch가 나면 "port changed, resolved to ..."로 표시한다.

### 7.2 Camera Identity

top/wrist camera도 index가 바뀐다.

필수:

- camera key: `top`, `wrist`, 추가 camera
- device identity: `/dev/v4l/by-id/*` 우선
- fallback index: 마지막 정상 index
- preview/capture test 결과 저장

### 7.3 Pi0.5 Training Defaults

현재 기준:

- `policy_type=pi05`
- base policy: `lerobot/pi05_base`
- batch size: `32`
- steps: `3000`
- num_workers: `12`
- eval_freq: `500`
- log_freq: `5`
- save_freq: `500`
- W&B: offline/disabled default
- video backend: torchcodec, fallback pyav

개선:

- GUI에서 Pi0.5 선택 시 위 값이 즉시 반영되어야 한다.
- 이전 policy type 값이 섞이면 backend에서 reject하고 UI가 이유를 보여준다.
- 2000/2500/3000 checkpoint 비교를 job card에서 쉽게 한다.

### 7.4 Pi0.5 Rollout Defaults

현재 rollout에서 중요한 값:

- policy checkpoint path
- task text
- duration blank = stop until manual stop
- max_relative_target
- temporal ensemble
- RTC execution horizon
- RTC guidance weight
- action queue refresh threshold

개선:

- default preset을 `Safe`, `Balanced`, `Responsive`로 둔다.
- preset은 숫자를 숨기는 것이 아니라 추천값을 넣고 사용자가 수정할 수 있게 한다.
- action queue가 너무 크면 "stale action 가능성" 경고를 띄운다.

---

## 8. Manipulation Agent Bridge 개선

현재 Manipulation Agent card는 rollout payload를 만들 수 있다.

개선 목표:

- 단순 "rollout 실행"이 아니라 autonomous pipeline에서 쓰는 동일 handoff packet을 눈으로 확인하게 한다.

필수 표시:

- source: `3dp_output_area`
- target: `utm_fixture`
- specimen id
- candidate id
- policy path
- task text
- vision observation
- SARM state
- Guardian gate result
- rollout session id
- handoff status

버튼:

- Save Bridge Config
- Test Bridge Payload
- Preview Handoff
- Run Manipulation Agent
- Stop Agent Rollout
- Status

중요:

- GUI rollout panel에서 조정한 Pi0.5 옵션은 Manipulation Agent bridge에도 적용되어야 한다.
- autonomous live loop에서 사용되는 payload와 GUI test payload가 달라지면 안 된다.

---

## 9. Safety / Guardian 연계

LeLab은 GUI 앱으로서 편의성이 강하다. 우리 시스템은 물리 실험 pipeline이므로 safety layer가 더 강해야 한다.

필수 safety:

- single tab ownership
- robot bus active lock
- live gate confirmation
- force stop
- stale subprocess cleanup
- camera resource release
- dataset path validation
- checkpoint compatibility validation
- action queue stale warning
- rollout stuck detector
- port conflict detector

Guardian 연계:

- live mode rollout 시작 전: Guardian preflight event
- rollout active 중: action delay, anomaly, user stop, port error를 Guardian event로 보낸다.
- stop 후: Guardian stop report에 reason을 남긴다.

UI 표현:

- operator가 바로 조치해야 하는 것은 red/orange alert card
- 설정 안내는 neutral guidance card
- raw traceback은 collapsed log tail

---

## 10. 구현 순서 제안

### Phase 0. 문서/설계 정리

목표:

- 본 문서를 기준으로 실제 구현 범위를 확정한다.
- LeLab을 이식하지 않고 ATR backend 유지 원칙을 확정한다.

검증:

- 이 문서가 현재 `docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`와 충돌하지 않는지 확인한다.

### Phase 1. Readiness Board와 Active Workflow Monitor

대상 파일:

- `web/templates/lerobot.html`
- `web/static/lerobot.js`
- `device_bridges/lerobot_bridge.py`

작업:

- 상단 hero를 readiness board로 정리한다.
- active workflow monitor를 만든다.
- 현재 session/job을 card로 표시한다.
- 서버 재접속 시 running job 상태를 복원한다.

검증:

- test mode에서 teleop/record/train/rollout fake session이 card로 표시된다.
- live training이 돌아가는 동안 `/lerobot`를 다시 열어도 progress가 보인다.

### Phase 2. Device Setup Wizard

대상:

- follower/leader/camera setup

작업:

- port identity와 현재 port path를 분리해 표시한다.
- top/wrist 기본 camera를 유지하고 추가 camera는 add/remove 가능하게 한다.
- camera preview/test 결과를 readiness에 반영한다.

검증:

- port 순서가 바뀌어도 saved id 기반으로 command가 생성된다.
- camera index가 바뀌어도 by-id가 있으면 우선 사용된다.

### Phase 3. Recording UX 고도화

작업:

- episode phase card 추가
- operator action 버튼 정리
- TTS 안내 문구와 phase 연결
- recording log와 dataset path를 분리 표시

검증:

- Start -> Save/Next -> Retry -> Finish -> Force Stop 상태가 UI에 즉시 반영된다.
- LeRobot keyboard mapping과 GUI 버튼이 동일하게 작동한다.

### Phase 4. Training Job Board / Checkpoint Manager

작업:

- training job card
- checkpoint dropdown
- resume target 표시
- Pi0.5 default 시각 검증
- failed job reason card

검증:

- 2000/2500/3000 checkpoint를 선택해 rollout panel에 반영할 수 있다.
- `log_freq=5`, `eval_freq=500`, `save_freq=500`, `workers=12`가 Pi0.5 default로 보인다.

### Phase 5. Rollout Diagnostics

작업:

- rollout setup/active 단계 분리
- action count, queue, RTC, delay warning 표시
- Stop 후 stale process cleanup 검증
- task text와 policy path compatibility 안내

검증:

- policy loading 중과 active rollout 중 상태가 구분된다.
- action queue가 오래 갱신되지 않으면 UI warning이 뜬다.

### Phase 6. Manipulation Agent Bridge 정리

작업:

- GUI rollout 설정과 Manipulation Agent payload를 동기화한다.
- Preview Handoff에서 실제 autonomous loop payload를 보여준다.
- Test Bridge Payload는 robot을 움직이지 않고 validation만 수행한다.

검증:

- live/test mode 모두 같은 schema를 사용한다.
- agent loop에서 생성된 manipulation session이 `/lerobot` job card에 나타난다.

### Phase 7. Selenium/브라우저 검증

작업:

- 1920x1080 기준 browser audit 추가
- light/dark 기본 가독성 확인
- button overlap, scroll, card overflow 확인

검증:

- `tests/ui/lerobot_browser_audit.py` 추가 또는 기존 UI audit 확장
- screenshot 기반 육안검사 로그 저장

---

## 11. 테스트 기준

Unit:

- `pytest tests/unit/test_lerobot_bridge.py -q`

Static:

- `node --check web/static/lerobot.js`
- `python3 -m py_compile device_bridges/lerobot_bridge.py`

Fake workflow:

- fake teleop start/stop
- fake record start/next/retry/finish
- fake train start/status/cancel
- fake rollout start/status/stop
- fake manipulation bridge preview/run/stop

Live preflight:

- follower port readiness
- leader port readiness
- top/wrist camera test
- calibration file presence
- policy path existence
- dataset path existence

Live motion:

- operator confirmation 없이 실행 금지
- live rollout은 장비 주변 정리 후 수동 지시가 있을 때만 수행

---

## 12. 수용 기준

이 개선이 완료되었다고 볼 수 있는 기준:

- 사용자가 `/lerobot`에 들어오면 "지금 가능한 작업"과 "막힌 이유"를 5초 안에 이해할 수 있다.
- ROBOTIS follower/leader/camera readiness가 한 화면에서 확인된다.
- recording 중 episode phase와 next action이 명확하다.
- training job이 GUI를 닫았다 열어도 이어서 보인다.
- checkpoint 선택이 rollout과 Manipulation Agent bridge에 바로 반영된다.
- rollout 중 model loading, robot connection, active action streaming이 구분된다.
- stop/force stop 후 serial/camera resource가 정리된다.
- GUI 실행과 agent 실행이 같은 backend session registry에 남는다.
- test mode와 live mode가 같은 API/schema를 사용한다.
- LeLab을 직접 실행하지 않아도 LeLab 수준의 guided workflow를 ATR/ROBOTIS 환경에서 제공한다.

---

## 13. 비목표

이번 개선안에서 하지 않는 것:

- LeLab React frontend를 그대로 복사하지 않는다.
- ATR의 FastAPI/static JS 구조를 즉시 React/Vite로 바꾸지 않는다.
- ROBOTIS OMX-AI를 SO-101 방식으로 강제로 맞추지 않는다.
- Manipulation Agent를 LeRobot 전용 agent로 바꾸지 않는다.
- Guardian을 우회해서 rollout을 직접 실행하지 않는다.
- live robot motion을 자동 테스트에 포함하지 않는다.

---

## 14. 최종 판단

LeLab은 우리에게 "어떤 기능을 추가할지"보다 "어떻게 사용자가 덜 헷갈리게 만들지"를 보여주는 reference다.

우리 시스템은 이미 LeRobot bridge, Pi0.5 runtime, Manipulation Agent handoff, Guardian gate를 갖고 있으므로, 다음 개선의 핵심은 새 기능 남발이 아니라 다음 세 가지다.

- 현재 상태를 readiness 중심으로 재구성한다.
- training/checkpoint/rollout을 하나의 policy lifecycle로 묶는다.
- hardware conflict와 inference failure를 operator가 즉시 이해할 수 있는 error card로 바꾼다.

이 방향이면 LeLab의 장점을 흡수하면서도 ATR의 autonomous closed-loop 구조를 유지할 수 있다.
