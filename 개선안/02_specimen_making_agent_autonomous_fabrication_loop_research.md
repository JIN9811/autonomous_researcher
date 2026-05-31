# Specimen Making Agent 자율 제조 루프 조사 노트

조사 일자: 2026-05-27

대상 agent: `SpecimenMakingAgent`

현재 역할: Design Agent가 만든 `experiment_spec`을 받아서 `geometry.generate_metamaterial_stl`, `geometry.check_mesh_quality`, `geometry.check_manufacturability`, `artifact.create_specimen_handoff`, `experiment.evaluate`, `printer.prepare`를 순차 호출한다.

최종 목표: 완전 자율 실험실에서 Specimen Making Agent는 단순 tool-calling agent가 아니라, 설계 스펙을 실제 제조 가능한 시편으로 변환하고, 제조 공정 계획, 품질 예측, slicing/printing gate, in-process monitoring, defect recovery, downstream handoff까지 책임지는 "자율 제조 실행 계획 agent"가 되어야 한다.

## 1. 핵심 결론

자율 실험실의 제조 agent는 다음 4가지를 동시에 해야 한다.

- Design Agent의 추상 설계를 제조 가능한 digital thread로 변환한다.
- 제조 전 품질과 실패 가능성을 예측한다.
- slicing/printing/ejection/device gate를 근거와 함께 통과시킨다.
- 제조 중 또는 제조 직후의 품질 피드백을 다음 Vision/Manipulation/Analysis/Design loop로 넘긴다.

따라서 현재처럼 "STL 생성 -> mesh check -> manufacturability check -> printer.prepare"만 수행하면 제조 자동화는 되지만, 자율 제조 agent라고 부르기에는 부족하다.

권장 방향은 다음과 같다.

```text
experiment_spec
  -> fabrication intent 해석
  -> manufacturability risk model
  -> geometry/STL 생성
  -> mesh + dimensional + printability 검증
  -> slicing plan + process parameter plan
  -> G-code safety/quality validation
  -> printer bridge dry-run or live execution
  -> in-process/after-process quality evidence 수집
  -> specimen digital thread record
  -> Vision/Manipulation handoff
  -> 실패/품질 결과를 Design/Knowledge/BO로 feedback
```

## 2. 조사한 대표 패턴

### 2.1 Digital thread: 설계-제조-검사 정보가 끊기면 자율성이 깨진다

NIST의 smart manufacturing digital thread 관점에서는 product design, manufacturing, quality activity, inspection result가 연결되어야 한다. 중요한 점은 제조 결과와 측정 결과가 다시 design engineer 쪽으로 돌아가야 한다는 것이다.

적용 포인트:

- Specimen Agent는 STL/G-code path만 반환하면 부족하다.
- `experiment_spec -> geometry_result -> mesh_report -> slicer_result -> gcode_validation -> printer_result -> inspection_evidence`를 하나의 `specimen_digital_thread`로 묶어야 한다.
- downstream agent가 품질/제조 이력을 구조적으로 읽을 수 있어야 한다.

출처: [Digital Thread for Smart Manufacturing, NIST](https://www.nist.gov/programs-projects/digital-thread-smart-manufacturing)

### 2.2 AM digital twin: physical fabrication은 digital twin과 sync되어야 한다

NIST/CASE의 AM digital twin framework는 material, machine, part model을 digital twin으로 보고, 실제 process data로 twin을 갱신하는 구조를 제안한다. 이 관점에서는 제조 중 측정값이 예상값에서 벗어나면 build를 조사하거나 중지하고, 가능하면 process setting을 feedback control로 조정한다.

적용 포인트:

- Specimen Agent는 `expected_mass_g`, `expected_print_time_min`만이 아니라 `expected_quality`, `expected_failure_modes`, `measurement_plan`을 가져야 한다.
- printer.prepare 결과는 단순 성공/실패가 아니라 digital twin update event가 되어야 한다.
- 제조가 끝난 뒤 Vision Agent가 찍는 이미지도 digital thread의 inspection node로 연결되어야 한다.

출처: [An Overarching Quality Evaluation Framework for Additive Manufacturing Digital Twin, NIST/IEEE CASE 2024](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=957942)

### 2.3 AM ARES: 자율 3D printing은 feedback + BO로 print parameter를 학습한다

AM ARES는 material extrusion printing에서 low-cost image analysis와 online ML planner를 사용해 print parameter를 closed-loop로 최적화한다. 논문은 feedstock/material이 바뀔 때 최적 printing condition을 다시 배워야 한다는 문제를 강조한다.

적용 포인트:

- Specimen Agent는 printer profile을 단순 문자열로 넘기는 데서 끝나면 안 된다.
- material, nozzle, layer, speed, bed temp, adhesion, cap skin, ejection setting이 "learnable process parameters"로 기록되어야 한다.
- print result와 image/quality feedback을 다음 loop에서 parameter recommendation으로 재사용해야 한다.

출처: [Toward autonomous additive manufacturing: Bayesian optimization on a 3D printer, MRS Bulletin 2021](https://link.springer.com/article/10.1557/s43577-021-00051-1)

### 2.4 In-process monitoring/control: closed-loop AM은 센서 피드백이 핵심

NIST의 real-time monitoring/control 프로젝트는 AM 품질과 throughput을 위해 in-process sensing, monitoring, control이 핵심이라고 본다. open-loop control은 post-process feedback과 model을 쓰고, closed-loop control은 layer geometry, defect characteristics 같은 feedback으로 조정한다.

적용 포인트:

- 지금 Specimen Agent는 print 전 단계 중심이다. 완전 자율 실험실에서는 print 중/후 품질 확인까지 포함해야 한다.
- 최소 구현은 live print 중 `step_trace`, PrusaLink job/status, optional camera snapshot을 `fabrication_monitoring`으로 저장하는 것.
- 장기 구현은 layer-wise image, warping/stringing/extrusion defect detection, pause/cancel/retry policy로 확장한다.

출처: [Real-Time Monitoring and Control of Additive Manufacturing Processes, NIST](https://www.nist.gov/programs-projects/real-time-monitoring-and-control-additive-manufacturing-processes)

### 2.5 LLM-3D Print: 제조 agent는 defect detector, planner, executor로 나뉜다

LLM-3D Print는 여러 LLM agent가 협력해 FDM 3D printing defect를 감지하고 원인 parameter를 추정하고, corrective action을 실행하는 구조를 제안한다. 평가에서는 inconsistent extrusion, stringing, warping, layer adhesion 같은 결함을 식별하고 자동 수정하는 데 초점을 둔다.

적용 포인트:

- Specimen Agent 내부를 하나의 거대한 LLM 호출로 만들기보다 역할을 나눈다.
- `quality_observer`, `process_planner`, `repair_planner`, `printer_executor` 같은 internal steps로 쪼갤 수 있다.
- 실제 장비 command는 deterministic bridge가 실행하고, LLM은 원인 설명과 수정 제안만 담당하는 편이 안전하다.

출처:

- [LLM-3D Print: Large Language Models To Monitor and Control 3D Printing, arXiv 2024/2025](https://arxiv.org/abs/2408.14307)
- [AI saves 3D prints in real time, Carnegie Mellon Engineering 2026](https://engineering.cmu.edu/news-events/news/2026/02/06-ai-saves-3d-prints.html)

### 2.6 Generalisable defect correction: real-time detection과 correction loop

Nature Communications의 3D printing error detection/correction 연구는 192개 part에서 120만 이미지 데이터셋을 만들고, neural network와 control loop를 결합해 다양한 geometry/material/printer/toolpath에서 real-time defect detection과 correction을 수행했다.

적용 포인트:

- Vision Agent가 나중에 할 일로만 보지 말고, Specimen Agent는 제조 품질 관측 계약을 미리 정의해야 한다.
- `print_quality_evidence`에는 image source, defect class, corrective action, confidence가 들어가야 한다.
- 실제 correction은 printer bridge gate를 통과해야 한다.

출처: [Generalisable 3D printing error detection and correction via multi-head neural networks, Nature Communications 2022](https://ideas.repec.org/a/nat/natcom/v13y2022i1d10.1038_s41467-022-31985-y.html)

### 2.7 AutoMEX: material extrusion workflow는 knowledge graph/expert system과 결합 가능

AutoMEX는 LLM agent와 manufacturing knowledge graph를 결합해 material extrusion의 end-to-end workflow를 자동화하고, material/process parameter/design consideration 추천을 제공한다.

적용 포인트:

- Specimen Agent의 `manufacturability` 판단은 하드코딩 rule만이 아니라 지식 기반 recommendation으로 확장할 수 있다.
- 프린트 조건 추천은 문헌/경험 기반 knowledge graph 또는 local rule table과 결합하는 것이 LLM 단독보다 안정적이다.
- `material_process_advice`를 보고서에 넣어 operator와 self-evolution이 볼 수 있게 해야 한다.

출처: [AutoMEX: Streamlining material extrusion with AI agents powered by large language models and knowledge graphs, Materials & Design 2025](https://www.sciencedirect.com/science/article/pii/S0264127525000644)

## 3. 현재 Specimen Agent 상태 진단

현재 강점:

- 필수 `experiment_spec` field를 강하게 검사한다.
- geometry/STL 생성, mesh check, manufacturability check, handoff, printer.prepare 흐름이 명확하다.
- test/live/virtual printer path gate가 비교적 잘 분리되어 있다.
- PrusaBridge 쪽에 slicing, PrusaLink, upload/start, ejection gate, step_trace가 이미 있다.
- hard failure는 raise해서 downstream으로 가짜 성공을 넘기지 않는다.

현재 한계:

- tool-calling 순서가 agentic reasoning처럼 보이지만, 실제로는 고정 pipeline이다.
- 제조 공정 계획서가 없다.
- 후보 spec이 제조 과정에서 어떻게 변형/보정됐는지 trace가 약하다.
- slicing/G-code/printer 결과가 Design/Knowledge/BO feedback으로 구조화되지 않는다.
- printer.prepare의 step_trace는 있지만, Specimen Agent 차원의 `fabrication_report`가 없다.
- 제조 중 defect monitoring과 correction loop가 아직 agent contract로 정의되어 있지 않다.
- LLM은 `tool_formatting` note 정도만 만들고, 제조 의사결정에는 거의 관여하지 않는다.

## 3.5 현재 우리 환경 기준 가능 범위

완전 자율 실험실을 목표로 하되, 지금 Specimen Making Agent 개선안은 "실제 가능한 자동화"와 "논문/미래 확장"을 분리해야 한다. 현재 로컬 프로젝트 기준으로 바로 가능한 것은 active physical correction이 아니라 evidence-rich fabrication autonomy다.

프로젝트 내부 근거:

- `configs/devices.yaml`: 기본 프린터는 test mode + `virtual_prusalink_dry_run=true`이며, PrusaLink 형태의 status/storage/job/transfer/upload/start/ejection boundary를 검증할 수 있다.
- `docs/hardware/prusa_mk4s_live_validation_20260506.md`: Prusa MK4S + PrusaLink upload/start, PrusaSlicer Docker wrapper, storage/job/transfer endpoint가 검증되어 있다. 단, ejection은 비활성 정책이다.
- `docs/agents/specimen_design_existing_runtime_guideline.txt`: `printer.prepare`는 내부 tool boundary로 유지해야 하며, Specimen Agent는 STL viewer가 아니라 manufacturing runtime state를 Live GUI에 보여줘야 한다.
- `agents/specimen_agent.py`: 이미 `geometry_result`, `mesh_result`, `manufacturability_result`, `handoff_result`, `experiment_response`, `printer.prepare`의 `step_trace`를 하나의 `specimen_result`에 모을 수 있는 구조가 있다.

지금 바로 가능한 범위:

1. `specimen_result`와 `protocol_note`는 유지하고, 그 안에 `fabrication_report`를 추가한다.
2. `candidate_id`, `specimen_id`, `geometry_hash`, `stl_path`, `sliced_path`, `handoff_package_path`, slicer settings, printer settings, PrusaLink 결과, `step_trace`를 묶어 `digital_thread`로 표기한다.
3. quality gate는 새 하드웨어 없이 구현 가능하다. required field, mesh, manufacturability, slicer, G-code validation, PrusaLink storage/readiness, upload/start/ejection gate를 기존 결과에서 추출하면 된다.
4. process plan도 기존 spec과 printer response만으로 구성 가능하다. material, layer height, nozzle, bed temperature, cap skin, adhesion, ejection policy, estimated mass/time을 보고서화한다.
5. Live GUI에는 STL 미리보기보다 PrusaSlicer 설정, G-code 경로, PrusaLink storage/readiness, upload/start 결과, step trace, operator message를 노출하는 쪽이 현재 구조와 맞다.
6. test path에서는 virtual bridge로 upload/start boundary를 검증할 수 있고, 실제 장비 없이도 보고서와 gate 흐름을 재현할 수 있다.

조건부로 가능한 범위:

1. `memory/prusa_connection.json`이 준비되고 Live GUI 또는 operator가 명시적으로 실제 출력을 선택하면 Prusa MK4S upload/start까지 갈 수 있다.
2. 설치 프린터 read-only 검증은 연결 정보와 네트워크 접근이 맞을 때 가능하다.
3. physical print는 `physical_intent`, `confirm_physical_print`, `start_immediately` 같은 명시적 gate가 있을 때만 허용해야 한다.
4. ejection은 현재 정책상 baseline이 아니다. `allow_ejection=false`이므로 자동 배출은 보고서에 "blocked by policy"로 남기는 편이 맞다.
5. after-print 관찰은 Vision Agent handoff와 카메라/시뮬레이터 결과로 시작할 수 있지만, layer-wise 실시간 결함 감지는 아직 별도 시스템이 필요하다.

아직 현재 환경에서 바로 하면 안 되는 범위:

1. LLM이 G-code를 직접 생성하거나 수정하는 방식.
2. 프린트 중 실시간 파라미터 보정, pause/cancel/retry 자동 실행.
3. layer-wise camera 기반 결함 감지와 closed-loop correction.
4. ML defect detector 학습을 전제로 하는 품질 판단.
5. operator 승인 없는 자동 ejection 또는 물리 동작.

## 4. 권장 자율 제조 agentic loop

```text
1. Spec Intake
   - Design Agent의 authoritative experiment_spec 검증
   - missing/ambiguous field 발견 시 operator 또는 Design Agent로 되돌림

2. Fabrication Intent Resolution
   - specimen purpose, compression face, cap skin, fixture, material, print profile 해석
   - "테스트용 출력", "실제 실험용 출력", "read-only bridge 검증" 구분

3. Manufacturing Digital Thread Init
   - specimen_id, candidate_id, graph_version, design_hash
   - geometry_version, printer_profile, slicer_profile, material lot, operator defaults 기록

4. Geometry Generation
   - STL 생성
   - geometry_report와 preview artifact 생성

5. Geometry and Mesh QA
   - bounding box, manifold, triangle count, cap skin policy, disconnected component risk

6. Printability and Process Planning
   - wall/cell/nozzle/layer/cap/adhesion/overhang/bridge rule 검사
   - expected mass/time/material usage
   - risk와 recommended process parameters 산출

7. Slicing and G-code QA
   - slicer command, profile, output path, G-code safety validation
   - ejection tail, skirt/brim/raft, first-layer settings, storage readiness

8. Execution Gate
   - test: simulator/virtual bridge
   - live: dry-run evidence + operator intent + device gate + graph gate 확인

9. Fabrication Monitoring
   - 현재 구현: PrusaLink status/job/transfer, step_trace, upload/start/ejection gate
   - 조건부 구현: after-print camera/simulator evidence
   - 미래 확장: layer-wise image와 defect correction
   - defect/warning/blocked state 기록

10. Repair or Stop Decision
   - 현재 구현: parameter adjustment recommendation과 다음 loop feedback
   - 조건부 구현: Guardian/Operator에게 pause/cancel/safe-stop 요청
   - unresolved issue: Guardian/Operator approval

11. Handoff
   - Vision Agent에게 실제 specimen location/readiness/quality evidence 전달
   - Manipulation Agent에게 pickup readiness 전달
   - Knowledge/BO에게 fabrication outcome feedback 전달
```

## 5. 제안 출력 계약

기존 필수 키는 유지한다.

```json
{
  "specimen_result": {},
  "protocol_note": ""
}
```

추가 권장 키:

```json
{
  "fabrication_report": {
    "fabrication_intent": {
      "mode": "test|live|virtual",
      "physical_intent": false,
      "printer_path": "virtual_bridge|installed_printer|physical_print|live",
      "specimen_purpose": "mechanical_test|calibration|dry_run"
    },
    "digital_thread": {
      "candidate_id": "",
      "specimen_id": "",
      "design_hash": "",
      "geometry_hash": "",
      "stl_path": "",
      "gcode_path": "",
      "handoff_package_path": "",
      "printer_profile": "",
      "slicer_profile_hint": "",
      "material": "",
      "graph_version": "",
      "run_id": ""
    },
    "process_plan": {
      "layer_height_mm": 0.2,
      "nozzle_diameter_mm": 0.4,
      "bed_temperature_c": 60.0,
      "first_layer_bed_temperature_c": 60.0,
      "adhesion_policy": {},
      "cap_skin_policy": {},
      "ejection_policy": {},
      "estimated_mass_g": null,
      "estimated_print_time_min": null
    },
    "quality_gates": [
      {
        "gate": "required_fields|mesh|manufacturability|slicer|gcode|printer_storage|live_gate",
        "status": "pass|warn|fail|blocked",
        "evidence": {},
        "repair": null
      }
    ],
    "monitoring_plan": {
      "observe_prusalink_status": true,
      "observe_transfer_idle": true,
      "observe_camera_after_print": true,
      "layerwise_monitoring_available": false,
      "defect_classes": ["warping", "stringing", "under_extrusion", "layer_adhesion"]
    },
    "fabrication_outcome": {
      "status": "ready_for_vision|printed|virtual_finished|blocked|failed",
      "location": "printer_bed|basket|unknown",
      "warnings": [],
      "failure_code": null
    },
    "feedback_to_design": {
      "do_not_repeat": [],
      "recommended_parameter_adjustments": {},
      "quality_score": null,
      "uncertainty": null
    }
  }
}
```

## 6. Live GUI 보고서에 보여야 할 항목

Specimen Making Agent 보고서는 STL 미리보기 중복보다 제조 runtime visibility가 핵심이다.

추천 섹션:

- Fabrication Intent: 이번 제조가 dry-run인지 실제 출력인지
- Digital Thread: design hash, geometry hash, STL, G-code, handoff package
- Process Plan: material, profile, layer/nozzle/temp, adhesion/cap/ejection policy
- Quality Gates: required fields, mesh, manufacturability, slicer, G-code, PrusaLink storage
- Printer Runtime: upload/start/transfer/job/status step trace
- Monitoring Evidence: camera/layer/after-print observation plan
- Repair/Stop Decision: 수정 제안, 재시도, safe-stop 필요 여부
- Handoff: Vision/Manipulation에 넘길 specimen location/readiness

## 7. 우리 프로젝트에서 바로 가져갈 설계 원칙

1. Specimen Agent는 printer를 직접 제어하지 않고, 계속 `printer.prepare`와 bridge gate를 통해야 한다.
2. 하지만 printer.prepare 결과를 단순 payload로 넘기지 말고 `fabrication_report`로 해석해야 한다.
3. Design Agent의 `experiment_spec`이 제조 중 변경되면 변경 이유와 before/after를 기록해야 한다.
4. 제조 전 품질 gate와 제조 중 monitoring gate를 분리한다.
5. Live mode에서는 physical action 이전에 digital thread와 gate evidence가 GUI에 보여야 한다.
6. 실패는 단순 exception이 아니라 `feedback_to_design`, `failure_memory`, `do_not_repeat`로 이어져야 한다.
7. LLM은 G-code 생성자가 아니라 process reasoning/reporting/repair suggestion 역할로 제한한다.
8. 완전 자율 실험실에서는 "제조 완료"가 아니라 "검사 가능한 specimen handoff"가 stage 완료 조건이 되어야 한다.

## 8. 단계별 고도화 방향

우선순위 1: 현재 환경에서 바로 가능한 `fabrication_report` 추가

- 현재 `specimen_result` 유지
- geometry/mesh/manufacturability/printer.prepare 결과를 reportable schema로 묶음
- Live GUI report가 이 schema를 우선 사용하도록 후속 설계
- 하드웨어 동작을 늘리지 않고도 구현 가능

우선순위 2: 현재 산출물 기반 digital thread record

- design hash, geometry hash, STL/G-code/handoff path, slicer settings, printer settings 연결
- run artifact와 Knowledge memory에서 재사용 가능하게 함
- `step_trace`, PrusaLink endpoint/result, operator message까지 제조 증거로 남김

우선순위 3: 기존 tool 결과 기반 process plan/risk gate

- `process_plan`과 `quality_gates`를 분리
- gate별 pass/warn/fail/blocked와 evidence 기록
- ejection, physical print, live start는 정책 gate로 별도 표기

우선순위 4: 현재 가능한 monitoring handoff

- Vision Agent가 after-print inspection을 수행할 수 있도록 expected location/readiness/defect classes 전달
- 나중에 layer-wise monitoring을 붙일 수 있는 schema 확보
- 지금은 layer-wise correction이 아니라 post-print inspection handoff를 1차 목표로 둠

우선순위 5: 안전한 repair/retry loop

- minor manufacturing issue는 parameter adjustment recommendation으로 남김
- live corrective action은 Guardian/operator approval 전에는 실행하지 않음
- 자동 pause/cancel/ejection은 현재 baseline에서 제외하고, 보고서에는 권장 action으로만 남김

## 9. 한 줄 설계 방향

Specimen Making Agent는 "STL과 printer.prepare를 호출하는 도구 파이프라인"에서 "설계 스펙을 제조 가능한 digital thread로 변환하고, 현재 장비/가상 브릿지/Live GUI가 검증 가능한 품질 gate와 제조 runtime evidence를 남기는 자율 제조 agent"로 고도화해야 한다.

## 10. 출처 색인

- 제조 digital thread: [Digital Thread for Smart Manufacturing, NIST](https://www.nist.gov/programs-projects/digital-thread-smart-manufacturing)
- AM real-time monitoring/control: [Real-Time Monitoring and Control of Additive Manufacturing Processes, NIST](https://www.nist.gov/programs-projects/real-time-monitoring-and-control-additive-manufacturing-processes)
- 자율 3D printing + Bayesian optimization: [Toward autonomous additive manufacturing: Bayesian optimization on a 3D printer, MRS Bulletin 2021](https://link.springer.com/article/10.1557/s43577-021-00051-1)
- AM digital twin quality framework: [An Overarching Quality Evaluation Framework for Additive Manufacturing Digital Twin, NIST/IEEE CASE 2024](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=957942)
- LLM multi-agent 3D print monitoring/control: [LLM-3D Print, arXiv](https://arxiv.org/abs/2408.14307)
- CMU 요약/검증 사례: [AI saves 3D prints in real time, Carnegie Mellon Engineering](https://engineering.cmu.edu/news-events/news/2026/02/06-ai-saves-3d-prints.html)
- real-time defect detection/correction: [Generalisable 3D printing error detection and correction via multi-head neural networks, Nature Communications 2022](https://ideas.repec.org/a/nat/natcom/v13y2022i1d10.1038_s41467-022-31985-y.html)
- LLM agent + knowledge graph material extrusion workflow: [AutoMEX, Materials & Design 2025](https://www.sciencedirect.com/science/article/pii/S0264127525000644)

## Live GUI 고도화 추가안 - 고도화안 기준

Specimen Making Agent의 Live GUI는 "3D 프린터 tool call 결과"가 아니라 design 후보가 실제 물리 시편으로 변환되는 digital thread를 보여줘야 한다. 고도화안에서 정한 installed/local/live printer bridge, slicer, ejection, 실패 재시도 흐름이 GUI에 모두 보이게 한다.

### Live GUI chat에 떠야 할 메시지

- 제작 경로 선택: virtual, installed PrusaSlicer, live printer bridge 중 어떤 경로로 실행하는지 표시한다.
- slicer 결과: estimated print time, material usage, layer height, infill, support 여부, G-code artifact 경로를 요약한다.
- printer bridge 상태: connection, upload, start, printing, cooling, auto ejection 대기, ejection 완료를 짧은 상태 메시지로 낸다.
- 실패/재시도: slicer 실패, printer offline, ejection 미확인, Vision Agent의 basket detection 미확인 시 원인과 다음 recovery action을 함께 표시한다.
- handoff: Vision Agent에는 basket/bed zone 감시 요청, Manipulation Agent에는 pickup-ready signal, Knowledge Agent에는 print profile과 결과 저장 이벤트를 보낸다.

### Specimen Agent 특화 보고서 페이지

- Digital thread: `design_candidate_id -> STL -> slicer profile -> G-code -> printer job -> ejection evidence`.
- Slicer report: profile, nozzle/temp/speed, support, 예상 시간/재료, warning list.
- Printer run log: bridge command trace, start/end timestamp, ejection trigger, retry count.
- Vision confirmation: bed empty, basket occupied, confidence, evidence image/video link.
- Artifact ledger: STL, G-code, printer log, captured images, generated metadata.
- Failure taxonomy: slicing error, transfer error, printer error, ejection uncertainty, sample labeling risk.
- Handoff packet: `specimen_fabricated.v1` with specimen_id, physical location, pickup pose hint, evidence refs.

### 현재 시스템에 맞춘 event/report 필드

- `live_chat_message.v1`: `agent_id=specimen`, `message_type=status|artifact|warning|handoff`, `specimen_id`, `printer_job_id`, `artifact_refs`.
- 기존 report의 `process_steps`는 slicer/upload/start/ejection을 단계 카드로 표시하고, `artifacts`에는 STL/G-code/log/image를 타입별로 분리한다.
- Vision Agent가 ejection을 확인하기 전에는 Orchestrator가 다음 stage를 "준비됨"으로만 표시하고, Manipulation 실행은 Guardian gate 이후로 둔다.

### 참고 출처

- NIST Digital Thread는 설계-제조-품질 데이터 연결 기준으로 적합하다: https://www.nist.gov/programs-projects/digital-thread-smart-manufacturing
- NIST AM real-time monitoring/control은 additive manufacturing 상태 감시와 제어의 기준 사례다: https://www.nist.gov/programs-projects/real-time-monitoring-and-control-additive-manufacturing-processes
- LangGraph frontend graph execution은 제조 stage별 상태 카드를 구현할 때 참고한다: https://docs.langchain.com/oss/python/langgraph/frontend/graph-execution
- NN/g visibility 원칙상 장시간 출력은 남은 단계와 불확실성을 계속 보여줘야 한다: https://www.nngroup.com/articles/ten-usability-heuristics/
