# Vision Agent 실험실 인식/신호 루프 고도화 조사 노트

조사 일자: 2026-05-28

대상 agent: `VisionAgent`

현재 역할: Specimen Making Agent 이후 `camera.capture`를 1회 호출하고, `observation` 안에 pickup pose, anomaly, transfer_readiness를 넣어 Manipulation Agent로 넘긴다.

목표 역할: Vision Agent를 단순 pickup-area check에서 "실험실 장면을 지속적으로 관찰하고, 프린터/바구니/로봇/UTM/Windows 장비 GUI 상태를 agent 신호로 변환하며, 성공/실패 시각 증거를 Knowledge에 남기는 lab perception signal agent"로 고도화한다.

## 1. 핵심 결론

Vision Agent는 완전 자율 실험실에서 눈에 해당하지만, 지금 환경에서는 바로 "항상 켜진 실시간 DINOv3 제어 시스템"으로 가면 안 된다. 현재 프로젝트의 `camera.capture`, `latest_observations`, Manipulation/Equipment/Knowledge handoff 계약을 유지하면서, 다음 순서로 고도화하는 것이 맞다.

1. 현재 `observation` 계약은 유지한다.
2. 그 안에 `vision_report`를 추가해 zone별 장면 상태, 탐지 결과, 이벤트, agent signal, 시각 증거 artifact를 구조화한다.
3. 처음에는 simulator/mock capture와 LeRobot camera test frame, Equipment screenshot artifact를 evidence로 저장한다.
4. DINOv3는 바로 "물체 검출기"로 쓰기보다, 시편/바구니/UTM platen/로봇 gripper 같은 반복 대상의 visual embedding, dense feature, anomaly/change detection backbone으로 둔다.
5. 물체 위치 검출은 Grounding DINO/OWL-ViT류 open-vocabulary detector 또는 작은 lab-object detector가 맡고, segmentation/tracking은 SAM 2류 비디오 tracker가 맡는 구조가 더 안전하다.
6. 물리 동작을 Vision Agent가 직접 실행하지 않는다. Vision Agent는 `agent_signals`만 발행하고, 실제 동작은 Specimen/Manipulation/Equipment/Guardian gate가 실행한다.

## 2. 인터넷 조사에서 가져온 패턴

### 2.1 DINOv3는 범용 시각 backbone이지, 단독 lab controller가 아니다

Meta의 DINOv3는 self-supervised vision backbone으로, 고해상도 dense feature를 제공하고 object detection, depth, segmentation, video object tracking 같은 downstream task에 강한 feature를 제공한다. 또한 작은 ConvNeXt/ViT 모델부터 큰 모델까지 있어 deployment 제약에 따라 선택할 수 있다.

적용 포인트:

- DINOv3는 "printed specimen", "empty basket", "specimen in basket", "specimen on UTM platen" 같은 상태를 embedding similarity / small adapter / prototype classifier로 안정화하는 데 적합하다.
- open vocabulary text prompt 기반 object detection은 DINOv3 단독보다 Grounding DINO류와 결합하는 편이 맞다.
- 현재 Windows 환경에서는 먼저 `facebook/dinov3-convnext-tiny-pretrain-lvd1689m` 같은 경량 backbone을 optional backend로 두고, 모델 가중치가 없으면 simulator/rule backend로 degradation해야 한다.

출처:

- [DINOv3, Meta AI Research](https://ai.meta.com/research/dinov3/)
- [DINOv3 publication, Meta AI](https://ai.meta.com/research/publications/dinov3/)
- [facebookresearch/dinov3 GitHub](https://github.com/facebookresearch/dinov3)

### 2.2 Open-set detection은 Grounding DINO류가 맡는 구조가 자연스럽다

Grounding DINO는 category name이나 referring expression 같은 human text input으로 임의 물체를 찾는 open-set detector다. 논문은 closed-set detector를 language와 결합해 novel object detection을 수행하는 구조를 제안한다.

적용 포인트:

- Vision Agent의 lab prompt 목록을 명시적으로 관리한다.
- 예: `printed gyroid specimen`, `white basket`, `robot gripper`, `compression platen`, `UTM moving crosshead`, `reset button`, `printer bed`.
- detection 결과는 바로 action으로 연결하지 말고, zone/신뢰도/시간 안정성 gate를 통과한 뒤 signal로 변환한다.

출처: [Grounding DINO, ECCV 2024 PDF](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/06319.pdf)

### 2.3 SAM 2류 비디오 segmentation/tracking은 "상태 변화"를 잡는 데 유용하다

SAM 2는 이미지와 비디오에서 promptable segmentation을 수행하고, streaming memory를 통해 비디오 object segmentation을 처리한다. Meta는 real-time video processing과 image/video 통합 segmentation을 강조한다.

적용 포인트:

- 프린터 출력 직후 `specimen` mask를 잡고, ejection 후 basket 영역으로 이동했는지 추적한다.
- robot gripper가 specimen을 잡았는지, basket이 비었는지, UTM fixture 위에 specimen이 놓였는지 같은 before/after state transition을 mask 변화로 판정한다.
- 현재 환경에서는 실제 비디오 tracking 전, frame pair 기반 change detection schema부터 만든다.

출처:

- [SAM 2 paper, arXiv](https://arxiv.org/abs/2408.00714)
- [Meta SAM 2 announcement](https://about.fb.com/news/2024/07/our-new-ai-model-can-segment-video/)

### 2.4 UTM fixture와 robot pickup에는 6D pose 또는 calibrated 2.5D pose가 필요하다

FoundationPose는 novel object의 6D pose estimation/tracking을 CAD model 또는 reference images 기반으로 수행하는 framework다. Robot manipulation에서 위치만이 아니라 orientation과 fixture alignment가 중요하므로, 장기적으로는 pose estimation 계층이 필요하다.

적용 포인트:

- 시편은 STL/CAD artifact가 있으므로 model-based pose estimation 후보가 된다.
- 단기 구현은 top camera 기준 2D bbox + calibrated workspace transform + z estimate로 충분하다.
- 장기 구현은 시편 STL/mesh를 FoundationPose류에 연결해 UTM platen alignment와 gripper 접근 pose를 안정화한다.

출처: [FoundationPose, CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Wen_FoundationPose_Unified_6D_Pose_Estimation_and_Tracking_of_Novel_Objects_CVPR_2024_paper.html)

### 2.5 Vision은 robot action을 직접 만들지 말고, robot policy에 관측을 넘겨야 한다

RT-2와 OpenVLA 계열은 visual observation과 language instruction을 action으로 변환하는 VLA 방향을 보여준다. OpenVLA는 robot control stack에 REST API로 붙일 수 있는 deployment 방식을 제공하고, DINOv2/SigLIP 기반 VLM에서 학습된 robot action model을 제공한다. 하지만 이 프로젝트의 Vision Agent는 action generator가 아니라 signal/evidence generator로 두는 것이 맞다.

적용 포인트:

- Vision Agent는 `pickup_ready`, `specimen_on_utm_platen`, `utm_home_restored` 같은 signal을 만든다.
- Manipulation Agent/LeRobot rollout은 이 observation을 받아 행동한다.
- Vision Agent가 robot action을 직접 호출하면 stage 책임이 깨지고 안전 gate가 약해진다.

출처:

- [RT-2, arXiv](https://arxiv.org/abs/2307.15818)
- [OpenVLA GitHub](https://github.com/openvla/openvla)

### 2.6 성공/실패 시각 데이터는 실험 지식의 일부가 되어야 한다

Self-driving lab의 computer vision 사례들은 visual cue가 단순 확인용 이미지가 아니라 real-time monitoring, control, cross-validation, data storage의 일부가 되어야 함을 보여준다. HeinSight2.0 사례는 multiple visual parameters와 process data를 함께 저장해 실험 판단에 사용한다.

적용 포인트:

- Vision Agent는 "봤다/못 봤다"가 아니라 `evidence_frame`, `before_after_pair`, `detection_confidence`, `event_timeline`, `failure_class`를 남겨야 한다.
- Knowledge Agent는 UTM 결과만이 아니라 vision evidence도 성공/실패 기억에 넣어야 한다.
- 실패 예: ejection 실패, basket miss, gripper miss, platen misalignment, UTM reset 미완료, 화면 macro click 실패.

출처: [Keeping an eye on the experiment: computer vision for real-time monitoring and control, ChemRxiv](https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/orp/resource/item/654a9b52a8b423585a29763e/original/keeping-an-eye-on-the-experiment-computer-vision-for-real-time-monitoring-and-control.pdf)

### 2.7 LeRobot/robot data 체계와 연결하려면 camera frame을 episode evidence로 보존해야 한다

LeRobotDataset v3.0은 multi-modal time-series data, sensorimotor signals, multi-camera video, metadata를 표준 형식으로 다룬다. LeRobot rollout 문서는 camera observation과 policy execution을 함께 다루며, sentry/highlight 같은 recording 전략을 제공한다.

적용 포인트:

- Vision Agent evidence는 나중에 LeRobot dataset episode와 연결될 수 있도록 `episode_id`, `camera_key`, `frame_ts`, `source_stage`, `signal_type`을 포함해야 한다.
- 조작 성공/실패 영상은 단순 로그가 아니라 future policy fine-tuning 데이터가 된다.
- 현재 프로젝트의 `configs/lerobot.yaml` camera map과 `/api/lerobot/camera/test` 흐름을 우선 활용한다.

출처:

- [LeRobotDataset v3.0 docs, Hugging Face GitHub](https://github.com/huggingface/lerobot/blob/main/docs/source/lerobot-dataset-v3.mdx)
- [LeRobot policy deployment docs](https://huggingface.co/docs/lerobot/main/inference)

## 3. 현재 Vision Agent 상태 진단

현재 강점:

- `observation` 필수 키가 안정적이다.
- Manipulation Agent가 이미 `state.latest_observations.pose_estimate`, `pickup_target`, `transfer_readiness`, `anomaly`를 읽는다.
- `VisionAgent`가 로봇/프린터/UTM을 직접 실행하지 않아서 stage 책임이 안전하다.
- test mode에서 카메라가 simulator로 동작할 수 있다.

현재 한계:

- `camera.capture`가 현재 mock 수준이며 image artifact, bbox, mask, confidence, timestamp가 없다.
- Vision Agent가 printer bed, basket, robot gripper, UTM platen, UTM GUI/screen 같은 여러 zone을 구분하지 않는다.
- 프린터 ejection 완료, 바구니 안 시편 존재, robot pickup 완료, UTM fixture 위 시편 존재 같은 event transition을 표현할 schema가 없다.
- Equipment Agent가 PyAutoGUI screenshot/step_trace를 만들 수 있지만, Vision Agent와 시각적으로 cross-check하는 계약이 없다.
- Knowledge Agent가 시각 성공/실패 evidence를 memory로 저장하지 않는다.
- 현재 active graph에서는 Vision stage가 Manipulation 앞에 한 번만 있으므로 UTM 이동 중/원복 후 관찰 같은 cross-stage monitoring은 아직 직접 표현되지 않는다.

## 4. 현재 우리 환경 기준 가능 범위

지금 바로 가능한 범위:

1. `observation`은 유지하고 `vision_report`를 추가한다.
2. `camera.capture` mock/simulator response를 확장해 `image_path`, `timestamp`, `detections`, `zones`, `confidence`, `artifact_paths`를 받을 수 있는 schema를 만든다.
3. 실제 DINOv3 inference 없이도 deterministic simulator로 다음 signal을 만들 수 있다.
   - `printer_output_visible`
   - `specimen_ejected_to_basket`
   - `basket_contains_specimen`
   - `pickup_ready`
   - `basket_empty_after_pick`
   - `specimen_on_utm_platen`
   - `utm_motion_observed`
   - `utm_home_restored`
4. Live GUI에는 현재 frame artifact, zone state, signal timeline, confidence, blocking reason을 표시할 수 있다.
5. Manipulation Agent에는 기존 `transfer_readiness`와 `pose_estimate`를 유지하면서 더 풍부한 `agent_signals`를 넘길 수 있다.
6. Equipment Agent가 만든 screenshot/step_trace를 Vision evidence와 같은 run artifact lineage로 묶을 수 있다.
7. Knowledge Agent가 `vision_evidence_summary`를 읽고 성공/실패 memory에 넣도록 후속 설계할 수 있다.

조건부로 가능한 범위:

1. LeRobot camera가 설정되어 있고 `/api/lerobot/camera/test`가 실제 frame을 반환하면, top/wrist camera frame을 vision evidence로 저장할 수 있다.
2. DINOv3 가중치와 PyTorch/Transformers 환경이 준비되면, `dinov3-convnext-tiny` 또는 `dinov3-vits16` 기반 feature extraction backend를 optional로 붙일 수 있다.
3. GPU가 충분하거나 별도 inference server가 있으면 Grounding DINO/SAM 2/pose backend를 비동기 서비스로 붙일 수 있다.
4. UTM GUI 상태는 Equipment Agent screenshot artifact가 있을 때 screen-state classifier 또는 template matching으로 확인할 수 있다.
5. auto ejection은 현재 프린터 정책에서 기본 비활성이므로, Vision Agent는 "ejection observed"를 판정할 수는 있어도 ejection 실행은 Specimen/Guardian gate가 맡아야 한다.

아직 현재 환경에서 바로 하면 안 되는 범위:

1. Vision Agent가 프린터, robot, UTM, PyAutoGUI action을 직접 실행하는 구조.
2. DINOv3/Grounding DINO/SAM 2가 항상 실시간으로 동작한다고 가정하는 live safety gate.
3. 단안 RGB만으로 UTM fixture 정렬을 mm 단위로 보장하는 것.
4. operator 승인 없는 UTM 원복 click, ejection, robot recovery action.
5. 실패/성공 영상만 저장하고 frame timestamp, agent stage, signal, specimen_id를 저장하지 않는 느슨한 데이터 축적.

## 5. 권장 Vision Agent agentic loop

```text
1. Observation Task Resolve
   - 현재 stage와 run_metadata를 보고 관찰 목적 결정
   - post_print, post_ejection, pre_pick, post_pick, pre_place, pre_utm, during_utm, post_utm_reset 구분

2. Zone Registry Load
   - printer_bed, ejection_basket, robot_workspace, robot_gripper, utm_platen, utm_screen ROI 로드
   - camera calibration id, frame source, expected object list 로드

3. Capture
   - camera.capture 또는 saved screenshot/frame artifact 획득
   - image_path, timestamp, camera_key, source 기록

4. Perception Backend
   - baseline: simulator/rule/template matching
   - optional: DINOv3 embedding/prototype classifier
   - optional: Grounding DINO open-set detection
   - optional: SAM 2 mask tracking
   - optional: FoundationPose/CAD pose estimation

5. Scene State Estimation
   - zone별 object present/absent, pose, confidence, obstruction, lighting/anomaly 추정

6. Temporal Event Detection
   - 이전 observation과 비교해 state transition 판정
   - ejection completed, pickup completed, place completed, UTM moving, UTM restored 등 event 생성

7. Agent Signal Arbitration
   - confidence threshold, stability frames, blocking policy 적용
   - Specimen/Manipulation/Equipment/Analysis/Knowledge/Guardian target signal 생성

8. Evidence Packaging
   - frame, annotated image, crop, mask, before/after pair, detection JSON 저장
   - run artifact lineage와 Knowledge memory payload 구성

9. Handoff
   - 기존 observation 필드는 유지
   - vision_report와 agent_signals를 run_metadata.latest_observations에 병합
```

## 6. 제안 출력 계약

기존 필수 키는 유지한다.

```json
{
  "observation": {},
  "protocol_note": ""
}
```

추가 권장 구조:

```json
{
  "observation": {
    "observation_id": "obs-run-stage-frame",
    "frame_id": "frame-0-vision",
    "camera_key": "top",
    "source": "simulator|lerobot_camera|equipment_screenshot|file",
    "summary": "specimen detected in ejection basket",
    "anomaly": false,
    "pose_estimate": {
      "x_mm": 0.0,
      "y_mm": 0.0,
      "z_mm": 5.0,
      "roll_deg": 0.0,
      "pitch_deg": 0.0,
      "yaw_deg": 0.0,
      "confidence": 0.82
    },
    "pickup_target": {
      "specimen_id": "",
      "candidate_id": "",
      "source_location": "ejection_basket",
      "target_location": "utm_fixture",
      "stl_path": "",
      "sliced_path": ""
    },
    "transfer_readiness": {
      "ready": true,
      "camera_ok": true,
      "specimen_ready": true,
      "pose_confidence": 0.82,
      "blocking_reason": null
    },
    "vision_report": {
      "task": "post_ejection_basket_check",
      "model_backend": {
        "mode": "simulator|dino_v3|grounding_dino|sam2|foundationpose|hybrid",
        "dino_model_id": "facebook/dinov3-convnext-tiny-pretrain-lvd1689m",
        "weights_available": false,
        "degraded_to": "simulator"
      },
      "zones": {
        "printer_bed": {
          "specimen_present": false,
          "confidence": 0.0,
          "ejection_expected": true
        },
        "ejection_basket": {
          "specimen_present": true,
          "object_count": 1,
          "confidence": 0.88
        },
        "robot_gripper": {
          "holding_specimen": false,
          "confidence": 0.75
        },
        "utm_platen": {
          "specimen_present": false,
          "aligned": false,
          "confidence": 0.0
        },
        "utm_screen": {
          "state": "unknown|ready|running|home_restored|blocked",
          "confidence": 0.0
        }
      },
      "detections": [
        {
          "label": "printed_specimen",
          "zone": "ejection_basket",
          "bbox_xyxy": [0, 0, 0, 0],
          "mask_path": "",
          "confidence": 0.88,
          "source": "simulator"
        }
      ],
      "events": [
        {
          "event_type": "specimen_ejected_to_basket",
          "status": "observed",
          "confidence": 0.88,
          "evidence_frame_id": "frame-0-vision",
          "blocking": false
        }
      ],
      "agent_signals": [
        {
          "signal": "pickup_ready",
          "target_agent": "manipulation_agent",
          "status": "ready",
          "confidence": 0.82,
          "requires_ack": true
        },
        {
          "signal": "visual_evidence_ready",
          "target_agent": "knowledge_agent",
          "status": "record",
          "confidence": 1.0,
          "requires_ack": false
        }
      ],
      "artifacts": {
        "frame_path": "",
        "annotated_frame_path": "",
        "before_after_path": "",
        "detection_json_path": ""
      },
      "knowledge_payload": {
        "specimen_id": "",
        "candidate_id": "",
        "success_labels": [],
        "failure_labels": [],
        "visual_notes": "",
        "store_in_memory": true
      }
    },
    "raw_capture": {}
  }
}
```

## 7. Agent별 signal 설계

### 7.1 Specimen Making Agent로 보내는 signal

- `print_visible_on_bed`: 출력물이 아직 bed에 있음.
- `ejection_completed`: 출력물이 bed에서 사라지고 basket 또는 target zone에 나타남.
- `ejection_failed`: bed에는 그대로 있고 basket에는 없음.
- `ejection_miss`: basket이 아닌 workspace에 떨어진 것으로 보임.

주의: Vision은 ejection 실행을 요청할 수는 있지만, 실행은 `printer.prepare`/Guardian gate가 맡아야 한다.

### 7.2 Manipulation Agent로 보내는 signal

- `pickup_ready`: basket 또는 pickup zone에 specimen이 있고 pose confidence가 threshold 이상.
- `pickup_blocked`: object 없음, occlusion, low confidence, human/obstacle detected.
- `basket_empty_after_pick`: robot이 집은 뒤 source zone이 비었음.
- `gripper_holding_specimen`: robot gripper에 specimen이 있는 것으로 보임.

기존 `transfer_readiness`는 이 signal들의 요약값으로 유지한다.

### 7.3 Lab Equipment Agent로 보내는 signal

- `specimen_on_utm_platen`: compression platen/fixture 위에 specimen이 있음.
- `fixture_alignment_ok`: specimen 중심/회전/경계가 UTM fixture tolerance 안에 있음.
- `utm_motion_observed`: UTM crosshead 또는 GUI state가 running으로 변함.
- `utm_home_restored`: PyAutoGUI 원복 클릭 후 UTM GUI/fixture 상태가 home/ready로 보임.
- `equipment_screen_state`: screenshot에서 macro target/button/status가 확인됨.

주의: Vision은 PyAutoGUI click을 직접 하지 않는다. Equipment Agent가 실행하고 Vision이 결과를 cross-check한다.

### 7.4 Analysis/Knowledge/Guardian으로 보내는 signal

- `visual_test_evidence_ready`: UTM 전/중/후 frame evidence가 있음.
- `failure_visual_evidence`: 실패 장면 crop/frame과 failure class가 있음.
- `anomaly_detected`: 사람/장애물/장비 이상/화면 mismatch 같은 safety issue.
- `data_quality_low`: 조명, blur, occlusion, missing camera 때문에 지식 저장 신뢰도가 낮음.

## 8. Live GUI에 보여줄 보고서

Vision Agent 보고서는 이미지 한 장보다 "상태 신호판"이어야 한다.

추천 섹션:

- Scene Task: 현재 관찰 목적, stage, specimen_id, expected transition
- Camera Source: top/wrist/screenshot, simulator/live, calibration id
- Zone State: printer bed, basket, gripper, UTM platen, UTM screen 상태
- Detection/Tracking: label, confidence, bbox/mask, pose
- Agent Signals: target agent, signal, status, confidence, blocking reason
- Evidence Artifacts: raw frame, annotated frame, before/after, detection JSON
- Safety/Anomaly: low confidence, occlusion, human/obstacle, unexpected object
- Knowledge Payload: 성공/실패 label, 저장할 visual note

## 9. LangGraph 고도화 방향

현재 graph는 `specimen -> vision -> manipulation -> equipment -> analysis -> knowledge` 순서라 Vision stage가 한 번만 돈다. 사용자가 원하는 설계는 여러 물리 단계 사이에 Vision이 신호를 주는 구조이므로, 단계적으로 접근해야 한다.

1차: 기존 Vision stage 유지

- `specimen -> vision -> manipulation` 사이에서 post-ejection/pickup readiness만 고도화한다.
- graph 변경 없이 `observation.vision_report`를 추가한다.

2차: module internal graph 확장

- `graphs/modules/vision/module.yaml`의 internal graph를 다음처럼 늘린다.
  - `capture_scene`
  - `detect_lab_objects`
  - `estimate_scene_state`
  - `emit_agent_signals`
  - `package_visual_evidence`

3차: stage transition마다 Vision checkpoint 추가

- `manipulation -> vision_post_transfer -> equipment` 또는 Equipment precheck 안에서 Vision sub-check를 호출한다.
- 단, Stage enum/graph migration 부담이 있으므로 처음부터 새 stage를 만들기보다 internal handler 또는 tool-event callback으로 시작한다.

4차: event-driven monitor

- 프린터 ejection, robot rollout, UTM macro 실행 같은 장시간 동작 중 Vision monitor가 주기적으로 frame을 보고 signal event를 발행한다.
- 이 단계는 safety policy와 artifact storage가 생긴 뒤에만 live에서 활성화한다.

## 10. 단계별 고도화 계획

우선순위 1: `vision_report` schema 추가

- 기존 `observation`, `protocol_note` 유지.
- zone state, detections, events, agent_signals, artifacts, knowledge_payload 추가.
- simulator/mock에서도 항상 같은 schema를 반환.

우선순위 2: 현재 환경 simulator event 확장

- `camera.capture` mock에 purpose별 deterministic field 추가.
- `post_ejection_basket_check`, `post_pick_check`, `pre_utm_fixture_check`, `post_utm_reset_check`를 표현.
- fault-injection에서 camera disconnect, low confidence, wrong zone, UTM not ready를 만들 수 있게 한다.

우선순위 3: Live GUI signal timeline

- Vision Agent message가 `agent_signals`를 표로 보여주게 한다.
- frame artifact가 있으면 thumbnail/annotated image 표시.
- blocking signal은 Guardian/Operator가 바로 볼 수 있게 한다.

우선순위 4: LeRobot camera frame evidence

- `/api/lerobot/camera/test` 또는 저장된 camera map을 통해 top/wrist frame을 run artifact로 저장.
- 아직 DINOv3를 쓰지 않더라도 frame_path, timestamp, camera_key, calibration_id를 남긴다.

우선순위 5: DINOv3 optional feature backend

- 가중치가 준비된 경우만 켠다.
- 경량 model부터 시작한다.
- 기능은 "prototype matching / anomaly embedding / crop embedding 저장"으로 제한한다.
- open-set text detection은 별도 detector backend로 분리한다.

우선순위 6: detector/tracker/pose backend

- Grounding DINO 또는 small lab detector: object bbox.
- SAM 2: mask tracking and before/after state transition.
- FoundationPose류: STL/CAD 기반 specimen pose.
- 이 backend들은 모두 optional이며 실패하면 rule/simulator로 degrade한다.

우선순위 7: Knowledge/ResearchOps 시각 데이터 저장

- `vision_evidence_summary`를 Knowledge Agent가 읽도록 한다.
- 성공/실패 visual evidence를 `memory` 또는 `research/metrics`와 연결한다.
- robot policy fine-tuning용 episode 후보로 표시한다.

## 11. 한 줄 설계 방향

Vision Agent는 "카메라 한 번 찍고 pickup pose를 추정하는 agent"에서 "실험실 zone 상태를 DINOv3/검출/추적/pose backend로 해석하고, 안전한 agent signal과 visual evidence ledger를 발행하는 실험실 perception bus"로 고도화해야 한다.

## 12. 출처 색인

- DINOv3 backbone/dense feature: [DINOv3, Meta AI Research](https://ai.meta.com/research/dinov3/)
- DINOv3 paper: [DINOv3 publication, Meta AI](https://ai.meta.com/research/publications/dinov3/)
- DINOv3 code/models: [facebookresearch/dinov3 GitHub](https://github.com/facebookresearch/dinov3)
- Open-set object detection: [Grounding DINO, ECCV 2024 PDF](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/06319.pdf)
- Video segmentation/tracking: [SAM 2, arXiv](https://arxiv.org/abs/2408.00714)
- SAM 2 product/release note: [Meta SAM 2 announcement](https://about.fb.com/news/2024/07/our-new-ai-model-can-segment-video/)
- 6D object pose/tracking: [FoundationPose, CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Wen_FoundationPose_Unified_6D_Pose_Estimation_and_Tracking_of_Novel_Objects_CVPR_2024_paper.html)
- VLA robot action model background: [RT-2, arXiv](https://arxiv.org/abs/2307.15818)
- Open-source VLA deployment reference: [OpenVLA GitHub](https://github.com/openvla/openvla)
- SDL vision monitoring/control: [Keeping an eye on the experiment, ChemRxiv](https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/orp/resource/item/654a9b52a8b423585a29763e/original/keeping-an-eye-on-the-experiment-computer-vision-for-real-time-monitoring-and-control.pdf)
- Robot dataset/video evidence structure: [LeRobotDataset v3.0 docs](https://github.com/huggingface/lerobot/blob/main/docs/source/lerobot-dataset-v3.mdx)
- LeRobot camera rollout/recording reference: [LeRobot policy deployment docs](https://huggingface.co/docs/lerobot/main/inference)

## Live GUI 고도화 추가안 - 고도화안 기준

Vision Agent의 Live GUI는 카메라 미리보기 이상의 역할을 해야 한다. DINOv3/SAM/pose tracking 기반 perception이 각 agent에 주는 신호를 operator가 이해할 수 있게, "무엇을 보았고, 얼마나 확실하며, 어떤 agent에게 어떤 신호를 보냈는가"를 실시간으로 보여주는 perception console이 필요하다.

### Live GUI chat에 떠야 할 메시지

- camera heartbeat: camera_id, fps, frame age, lighting/blur warning.
- zone state: printer bed, basket, robot gripper, compression flatten, UTM screen/fixture 등 zone별 상태를 짧게 표시한다.
- detection signal: `object_present`, `basket_loaded`, `flatten_occupied`, `utm_moving`, `robot_cleared` 같은 boolean signal과 confidence/stability window를 표시한다.
- uncertainty: confidence가 낮거나 occlusion이 있으면 "재촬영 필요", "robot pause 권고", "Guardian review 필요"로 올린다.
- success/failure capture: 조작 성공/실패, 장비 움직임 실패, auto ejection 실패 장면을 Knowledge Agent로 저장했다는 메시지를 남긴다.
- cross-agent alert: Manipulation, Equipment, Guardian에 보낸 signal_id와 수신 agent를 chat card에 남긴다.

### Vision Agent 특화 보고서 페이지

- Live scene map: camera별 frame thumbnail, zone overlay, object labels, timestamp.
- Signal board: signal_id, zone, value, confidence, stable_for_ms, consumers, last_updated.
- Evidence timeline: 출력 완료, basket load, robot pickup/drop, UTM motion, flatten occupancy 같은 주요 event의 이미지/영상 링크.
- Model status: detector version, calibration profile, threshold, false positive/negative notes.
- Dataset ledger: 성공/실패 데이터셋 저장 위치, label proposal, retraining candidate.
- Cross-agent contract: 어떤 signal이 어느 agent의 precondition/gate로 쓰였는지 표시한다.
- Handoff packet: `vision_signal.v1` with signal_id, zone_id, value, confidence, stability_ms, consumer agents, evidence refs.
- Recovery panel: re-capture, change camera, ask operator, fallback to manual confirmation.

### 현재 시스템에 맞춘 event/report 필드

- `live_chat_message.v1`: `agent_id=vision`, `message_type=status|signal|warning|artifact|handoff`, `signal_id`, `zone_id`, `confidence`, `stability_ms`.
- `/api/agents/vision/report`의 `role_specific`은 고정 설명 대신 `scene_map`, `signal_board`, `evidence_timeline`, `dataset_ledger`로 확장한다.
- Vision signal은 단순 chat text가 아니라 downstream agent가 읽는 `vision_signal.v1` structured event여야 한다. chat은 그 structured event를 사람이 읽기 좋게 렌더링한 view다.

### 참고 출처

- LangGraph graph execution은 node별 상태와 streaming content를 동시에 보여주는 근거다: https://docs.langchain.com/oss/python/langgraph/frontend/graph-execution
- LangSmith observability는 tool/model decision trace와 metadata 축적 기준으로 쓴다: https://docs.langchain.com/oss/python/langchain/observability
- OpenTelemetry semantic conventions는 trace/log/metric 이름을 표준화하는 근거다: https://opentelemetry.io/docs/concepts/semantic-conventions/
- NN/g visibility 원칙상 Vision Agent는 "봤다"가 아니라 confidence와 다음 영향까지 보여줘야 한다: https://www.nngroup.com/articles/ten-usability-heuristics/
