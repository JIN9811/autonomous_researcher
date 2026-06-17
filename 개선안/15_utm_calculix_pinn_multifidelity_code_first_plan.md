# 15. UTM·CalculiX·PINN 멀티피델리티 자가개선 루프 개선안 - ATR 코드 중심 수립 계획

작성일: 2026-06-18
대상 보고서: `/home/jin/다운로드/UTM·CalculiX·PINN 멀티피델리티 자가개선 루프 연구 보고서.pdf`
대상 코드: `agents/analysis_agent.py`, `device_bridges/cae_bridge.py`, `device_bridges/utm_macro_bridge.py`, `experiments/api.py`, `experiments/schemas.py`, `experiments/job_queue.py`, `agents/bo_agent.py`, `agents/guardian_agent.py`, `graphs/configs/atr_closed_loop.yaml`, `web/static/planning.js`, `web/templates/planning.html`

---

## 1. 결론

이 개선안은 외부 PDF의 구조를 ATR에 덮어씌우는 문서가 아니다. 현재 ATR 코드가 이미 가진 closed-loop, agent handoff, device bridge, BO, Guardian, Live GUI 구조를 주체로 두고, 그 위에 `UTM 실험 데이터 + CalculiX FEA + PINN/Neural Operator surrogate`를 evidence layer로 추가하는 계획이다.

권장 정체성:

```text
ATR Analysis/CAE/BO stack
= UTM raw result + deterministic/test CAE + real CalculiX + optional PINN surrogate
  -> canonical evidence
  -> trust score
  -> BO/Guardian/Knowledge handoff
  -> next design loop
```

가장 중요한 판단:

```text
1. 현재 graph와 agent 순서는 유지한다.
2. Analysis Agent가 멀티피델리티 evidence의 중심이 된다.
3. CalculiX는 CAE Bridge의 실제 solver backend로 추가한다.
4. PINN은 새 주도권 agent가 아니라 surrogate worker/tool로 추가한다.
5. BO Agent는 Analysis가 만든 trust score와 objective를 소비한다.
6. Guardian은 마지막 승인자가 아니라 trust score 기반 action gate로 확장한다.
7. Live GUI는 raw JSON이 아니라 curve, contour, trust badge, provenance를 보여준다.
```

---

## 2. PDF 그림/표 기반 해석

PDF를 페이지 이미지로 렌더링해서 도식과 표를 확인했다. 문서에는 별도 raster image가 없고, 표/도식은 PDF 벡터/HTML 요소로 구성되어 있다.

### 2.1 5페이지 데이터 파이프라인 도식

보고서 도식은 다음 흐름을 제안한다.

```text
PrePoMax/manual QA
-> .inp
-> CalculiX worker
-> .frd/.dat
-> ccx2paraview / PyVista / meshio postprocess
-> runs/artifacts + metadata DB
-> Analysis / PINN Trainer / BO / Active Learning
-> Live GUI curve panel + 3D contour/hotspot viewer
```

ATR 기준 해석:

```text
PrePoMax = 수동 QA 도구, 자동화 백엔드 아님
CalculiX worker = device_bridges/calculix_bridge.py 신설 대상
postprocess = scripts/ccx_postprocess.py 신설 대상
metadata DB = 현재 runs/artifacts/event stream 구조 확장
Analysis/PINN/BO = 기존 agents/analysis_agent.py, agents/bo_agent.py 중심 확장
Live GUI = web/static/planning.js에 lightweight viewer 추가
```

### 2.2 11페이지 closed-loop 의사결정 도식

보고서 도식은 다음 의사결정 흐름을 제안한다.

```text
all evidence UTM/DIC/FEA/PINN
-> 데이터 무결성 검사
-> 표준 좌표/curve/field canonicalization
-> 신뢰도 점수 계산
-> FEA 보정 필요?
   -> calibration job
-> 다음 실험 가치가 큰가?
   -> BO suggest next
-> 모델 업데이트가 필요한가?
   -> PINN/PINO train
-> report/finalize
```

ATR 기준 해석:

```text
현재 graph: design -> specimen -> vision -> manipulation -> equipment -> analysis -> knowledge -> bo -> guardian
변경 방향: graph 순서 변경이 아니라 analysis 내부 분기와 handoff packet 확장
```

### 2.3 6-8페이지 API/스키마 표

보고서는 `/api/utm/jobs`, `/api/fea/jobs`, `/api/fea/postprocess`, `/api/pinn/train`, `/api/analysis/compare`, `/api/active-learning/suggest`를 추가하라고 제안한다.

ATR 기준 해석:

```text
이미 있는 것:
- /api/run/start
- /api/runtime/state
- /api/events/stream
- /api/runs/{run_id}/artifacts
- /bo
- /cae
- experiment.evaluate
- cae.run_static_analysis
- utm.run_protocol

추가가 필요한 것:
- typed UTM/FEA/PINN schema
- job 단위 상태/stream
- real CalculiX job endpoint/tool
- PINN train/evaluate endpoint/tool
- analysis compare endpoint/tool
```

### 2.4 13-14페이지 검증/로드맵 표

보고서는 검증 지표를 다섯 층으로 제안한다.

```text
Curve: RMSE, peak force error, stiffness slope error, energy absorption error
Field: relative L2, NRMSE on surface displacement/strain
Hotspot: Dice/IoU, hotspot centroid distance
Calibration: coverage@90%, NLL 또는 CRPS
Convergence: mesh sweep stability, parameter posterior shrinkage
```

ATR 기준 MVP는 다음이다.

```text
MVP = 실제 CalculiX job + UTM CSV ingest + curve 비교 + basic trust score
L2 = DIC surface field + contour viewer + PINN multi-head 학습
L3 = operator surrogate + cost-aware MFBO + self-improving closed loop
```

---

## 3. 현재 ATR 코드 기준 진단

### 3.1 이미 있는 기반

현재 코드에는 멀티피델리티 루프를 넣기 위한 기반이 상당히 있다.

```text
agents/analysis_agent.py
- UTM/equipment output parsing
- CSV/JSON/JSONL parsing
- force/displacement/time column alias
- unit normalization 일부
- live mode UTM_DATA_REQUIRED block
- test mode synthetic curve
- peak force, stiffness, strength, modulus, energy absorption 계산
- cae.run_static_analysis 호출
- objective_score, uncertainty 계산
- experiment_evaluation.v1 생성
- analysis_bo_handoff_v1 생성
- runtime/analysis artifact 저장

agents/bo_agent.py
- random/grid/bo/mbo/lightweight pool 지원
- acquisition 설정 지원
- state.experiment_evaluations prior 사용
- bo_handoff / bo_observation / experiment_evaluation 소비
- next design constraints 생성

device_bridges/cae_bridge.py
- CalculiX/Gmsh availability preflight
- bottom-fixed/top-cyclic deterministic equivalent analysis
- contour SVG/report artifact 생성 경로

mcp_tools/cae_tools.py
- cae.health
- cae.run_static_analysis

mcp_tools/utm_tools.py
- utm.run_protocol
- test CSV 생성
- UTM CSV probe/quality check

experiments/api.py
- ExperimentRuntime facade
- virtual/printer bridge 평가
- objective_score 표준 반환

experiments/job_queue.py
- per-device FIFO metadata wrapper

web/static/planning.js
- FEM/CAE contour card 렌더링
- BO surrogate/acquisition card 렌더링
- analysis/bo report section 일부 존재
```

즉, PDF의 구조를 새로 만드는 것이 아니라 기존의 `Analysis -> Knowledge -> BO -> Guardian` 구간을 실제 evidence 기반으로 강화하면 된다.

### 3.2 현재 부족한 부분

```text
1. cae_bridge.py는 아직 실제 CalculiX solve가 아니라 deterministic/test equivalent가 중심이다.
2. UTM Bridge는 live UTM CSV ingest contract는 있으나 실제 장비 export pull과 canonical package가 약하다.
3. experiments/schemas.py에는 UTM/FEA/PINN/MultifidelityJob schema가 없다.
4. Analysis Agent는 bo_handoff를 만들지만 UTM-FEA-PINN agreement/trust score가 아직 중심 개념은 아니다.
5. PINN/Neural Operator는 아직 코드 상의 worker/tool로 존재하지 않는다.
6. heavy solver/train job은 DeviceJobQueue와 분리된 background worker 정책이 필요하다.
7. Live GUI는 FEM contour/BO plot은 있지만 multi-fidelity evidence table, trust badge, provenance drawer가 부족하다.
8. Guardian은 uncertainty/precursor 기반 판단은 있으나 multi-fidelity trust score gate로는 아직 약하다.
```

---

## 4. 외부 조사 반영 요약

### 4.1 CalculiX

공식/문서 기준 CalculiX는 `.inp` input deck을 받아 `jobname.dat`, `jobname.frd`를 생성한다. `.dat`는 curve/scalar 결과, `.frd`는 field 결과 후처리에 적합하다.

ATR 적용:

```text
- .inp: scripts/calculix_input_builder.py 또는 device_bridges/calculix_bridge.py에서 생성
- .dat: force/reaction/displacement curve 추출
- .frd: ccx2paraview/frd2vtu/PyVista로 contour asset 생성
```

참고:

- CalculiX input/output: https://web.mit.edu/calculix_v2.7/CalculiX/ccx_2.7/doc/ccx/node160.html
- CalculiX project: https://www.calculix.de/

### 4.2 ccx2paraview / frd2vtu

`ccx2paraview`는 CalculiX `.frd`를 `.vtk/.vtu`로 변환하는 converter다. 응력/변형률 tensor에서 Mises/Principal scalar도 생성한다. `frd2vtu`는 Python 기반 대체 옵션이다.

ATR 적용:

```text
우선순위:
1. ccx2paraview CLI 사용
2. 실패/미설치 시 frd2vtu optional backend
3. 둘 다 없으면 .dat curve만 처리하고 field visualization은 unavailable로 표시
```

참고:

- ccx2paraview: https://github.com/calculix/ccx2paraview
- frd2vtu: https://pypi.org/project/frd2vtu/

### 4.3 DICe

DICe는 sequence image에서 full-field displacement/strain을 계산하는 open-source DIC 도구다. DIC는 L2 이후 단계에서 UTM-FEA field calibration에 유용하다.

ATR 적용:

```text
MVP에는 DICe 실행을 넣지 않는다.
대신 schema와 artifact slot을 먼저 열어둔다.
L2에서 dic_bridge.py 또는 dice_postprocess.py로 추가한다.
```

참고:

- DICe GitHub: https://github.com/dicengine/dice
- DICe docs: https://dicengine.github.io/dice/

### 4.4 PINN / DeepXDE / NVIDIA PhysicsNeMo / NeuralOperator

DeepXDE는 PINN, DeepONet, MFNN 등 scientific ML 기능을 제공한다. NVIDIA PhysicsNeMo는 physics AI 모델 학습/추론 프레임워크다. NeuralOperator는 FNO/GINO 등 operator learning 구현을 제공한다.

ATR 적용 판단:

```text
MVP: PINN train/evaluate schema와 offline worker만 준비
L2: DeepXDE 기반 inverse/calibration PINN부터 시작
L3: NeuralOperator 기반 FNO/GINO로 geometry/load family surrogate 확장
PhysicsNeMo: CUDA/GPU scale-out이 필요해진 뒤 optional backend
```

참고:

- DeepXDE docs: https://deepxde.readthedocs.io/
- DeepXDE paper: https://epubs.siam.org/doi/10.1137/19M1274067
- NVIDIA PhysicsNeMo: https://developer.nvidia.com/physicsnemo
- NVIDIA Modulus PINN theory: https://docs.nvidia.com/deeplearning/modulus/modulus-v2209/user_guide/theory/phys_informed.html
- NeuralOperator docs: https://neuraloperator.github.io/
- NeuralOperator PyTorch ecosystem: https://pytorch.org/blog/neuraloperatorjoins-the-pytorch-ecosystem/

### 4.5 PyVista / Plotly

PyVista는 off-screen rendering과 screenshot 생성을 지원한다. Plotly는 curve, uncertainty, calibration plot에 적합하다.

ATR 적용:

```text
- contour는 PyVista server-side PNG/SVG snapshot 중심
- Live GUI에서는 raw VTK.js보다 artifact image/HTML preview 우선
- curve/uncertainty는 Plotly JSON 또는 SVG/PNG export 우선
```

참고:

- PyVista screenshot: https://docs.pyvista.org/api/plotting/_autosummary/pyvista.Plotter.screenshot.html
- PyVista off-screen Plotter: https://docs.pyvista.org/api/plotting/_autosummary/pyvista.Plotter.html
- Plotly Python: https://plotly.com/python/

---

## 5. 목표 아키텍처

### 5.1 현 graph 유지

현재 graph는 유지한다.

```text
dispatch
-> idle
-> design
-> specimen
-> vision
-> manipulation
-> equipment
-> analysis
-> knowledge
-> bo
-> guardian
-> design 또는 complete/error
```

추가되는 것은 `analysis` 내부 evidence layer와 `bo/guardian` 입력 계약이다.

### 5.2 멀티피델리티 evidence flow

```text
Equipment Agent
  -> utm_data_ready.v1
  -> Analysis Agent
       -> canonical_curve.v1
       -> cae_request.v1
       -> cae_result.v1
       -> fea_curve.v1
       -> fea_field_asset.v1
       -> pinn_prediction.v1 optional
       -> multifidelity_comparison.v1
       -> trust_score.v1
       -> experiment_evaluation.v1
       -> analysis_bo_handoff_v2
  -> Knowledge Agent
       -> evidence/provenance memory
  -> BO Agent
       -> objective + uncertainty + trust + candidate constraints
  -> Guardian Agent
       -> trust/action gate
```

### 5.3 Live/Test mode semantics

```text
test mode:
- UTM synthetic or fixture CSV 사용
- CAE deterministic equivalent 또는 tiny CalculiX smoke job 사용
- PINN은 fake model이 아니라 saved fixture 또는 deterministic lightweight trainer/evaluator 사용
- BO까지 5 loop가 빠르게 돌아야 함

live mode:
- UTM live artifact 없으면 Analysis block
- CalculiX runtime_solver_enabled=true일 때만 real solve 수행
- PINN train은 long-running worker로 보내고 현재 loop를 막지 않음
- Guardian trust gate가 다음 physical action 허용 여부 결정

virtual/replay:
- 저장된 canonical artifacts를 재사용
- run_id/experiment_id/specimen_id/provenance를 유지
```

---

## 6. 파일별 개선 계획

### 6.1 `experiments/schemas.py`

현재 역할:

```text
ExperimentObjective, ExperimentCandidate, ExperimentExecution, ExperimentEvaluationRequest, ExperimentEvaluationResult 정의
```

추가할 schema:

```text
UTMRecord
- test_id
- specimen_id
- material_batch
- time_s
- displacement_mm
- force_n
- eng_strain
- eng_stress_mpa
- true_strain
- true_stress_mpa
- sampling_hz
- machine_meta
- dic_sync
- quality
- uncertainty
- provenance

FEAResult
- sim_id
- job_id
- specimen_id
- inp_uri
- dat_uri
- frd_uri
- field_asset_uri
- curve_asset_uri
- mesh_meta
- material_params
- loadcase
- solver_meta
- validation_flags
- uncertainty
- provenance

PINNModelRecord
- model_id
- family: pinn|xpinn|deeponet|fno|gino|mfnn
- input_signature
- output_signature
- train_dataset_ids
- fidelity_config
- loss_config
- uq_method
- checkpoints
- metrics
- deployment_meta
- provenance

MultifidelityJob
- job_id
- job_type: utm_ingest|fea|fea_postprocess|pinn_train|pinn_predict|calibration|analysis_compare
- status: queued|precheck|running|postprocess|validated|registered|consumed_by_analysis|complete|failed|blocked
- run_id
- experiment_id
- session_id
- specimen_id
- parent_ids
- artifacts
- step_trace
- trust_score
- failure_code
- provenance

TrustScore
- score
- q_data
- q_agreement
- q_physics
- q_uq
- q_provenance
- gate: block|calibrate_only|allow_bo|allow_physical
- reasons
```

중요 원칙:

```text
기존 ExperimentEvaluationResult 필드는 깨지지 않게 optional field로 확장한다.
BridgeName Literal에는 calculix, pinn, surrogate, calibration을 바로 넣기보다 metadata/tool layer로 먼저 처리한다.
기존 테스트가 기대하는 objective_score, metrics, artifacts, bridge_result는 유지한다.
```

### 6.2 `device_bridges/cae_bridge.py`

현재 역할:

```text
CalculiX/Gmsh preflight + deterministic equivalent CAE analysis
```

변경 방향:

```text
1. 기존 CAEBridge는 test/preflight bridge로 유지한다.
2. 실제 CalculiX solve는 별도 device_bridges/calculix_bridge.py로 분리한다.
3. CAEBridge는 provider router 역할을 하거나, mcp_tools에서 calculix bridge를 별도 등록한다.
```

신설 권장 파일:

```text
device_bridges/calculix_bridge.py
- CalculiXBridgeConfig
- CalculiXBridge.health()
- CalculiXBridge.prepare_input(payload)
- CalculiXBridge.solve(payload)
- CalculiXBridge.postprocess(payload)
- CalculiXBridge.run_job(payload)
```

입출력:

```text
input:
- specimen_id
- stl_path or mesh_path
- material
- loadcase
- boundary
- mesh_size_mm
- run_id/experiment_id/session_id

output:
- ok
- tool: calculix.run_job
- job_id
- status
- inp_path
- dat_path
- frd_path
- curve_json_path
- field_asset_path
- contour_png_path or contour_svg_path
- solver_meta
- validation_flags
- step_trace
```

### 6.3 `scripts/ccx_postprocess.py`

신설 목적:

```text
CalculiX 결과 후처리를 bridge에서 분리한다.
```

역할:

```text
- .dat에서 reaction/displacement/global curve 추출
- .frd를 ccx2paraview 또는 frd2vtu로 변환
- PyVista로 contour PNG 생성
- Plotly-compatible curve JSON 생성
- field metadata 생성
```

중요:

```text
Live GUI가 raw .vtu를 직접 먹지 않게 한다.
MVP는 contour PNG/SVG와 curve JSON이면 충분하다.
```

### 6.4 `device_bridges/utm_macro_bridge.py` / `mcp_tools/utm_tools.py`

현재 역할:

```text
UTM direct protocol stub/test CSV/probe
```

변경 방향:

```text
1. live UTM은 Windows PyAutoGUI bridge가 실제 제어를 맡을 수 있다.
2. 여기서는 UTM result ingest와 validation을 강화한다.
3. Windows에서 가져온 CSV든 직접 지정된 CSV든 canonical UTMRecord로 만든다.
```

추가 기능:

```text
- utm.ingest_result_file
- utm.probe_result_file
- utm.canonicalize_curve
- utm.validate_signal_quality
- result sidecar JSON 생성
```

Artifact 구조:

```text
artifacts/equipment/<run_id>/utm/raw/<source_file>
artifacts/equipment/<run_id>/utm/canonical_curve.json
artifacts/equipment/<run_id>/utm/canonical_curve.csv
artifacts/equipment/<run_id>/utm/utm_record.json
artifacts/equipment/<run_id>/utm/provenance.json
```

### 6.5 `agents/analysis_agent.py`

현재 역할:

```text
UTM/equipment output 분석, objective/uncertainty 계산, CAE deterministic 호출, bo_handoff 생성
```

변경 방향:

```text
Analysis Agent = multi-fidelity evidence owner
```

추가할 내부 함수:

```text
_ingest_utm_record(state) -> UTMRecord-like dict
_request_cae_or_load_cached(state, utm_record, geometry) -> FEAResult-like dict
_load_latest_pinn_prediction(state, canonical) -> optional PINN prediction
_compare_curve_and_field(utm, fea, pinn) -> multifidelity_comparison.v1
_compute_trust_score(quality, agreement, physics, uq, provenance) -> trust_score.v1
_decide_multifidelity_next_action(trust, comparison, state) -> calibrate|train|bo|block
_build_multifidelity_bo_handoff(...) -> analysis_bo_handoff_v2
```

Trust score 초안:

```text
T = 0.30 * Q_data
  + 0.25 * Q_agreement
  + 0.20 * Q_physics
  + 0.15 * Q_uq
  + 0.10 * Q_provenance
```

Gate:

```text
T < 0.55:
  - ok_for_bo = false
  - next_action = block_or_reingest

0.55 <= T < 0.75:
  - ok_for_bo = false
  - next_action = calibration_or_reanalysis

T >= 0.75:
  - ok_for_bo = true
  - next_action = bo_candidate_allowed
```

기존 `experiment_evaluation.v1`은 유지하되 다음을 추가한다.

```text
fidelity_records:
  utm_high: metrics/artifact ref
  fea_mid: metrics/artifact ref
  pinn_low_or_surrogate: metrics/artifact ref optional

trust_score:
  score
  gate
  components

comparison:
  curve_rmse
  peak_force_error
  stiffness_error
  energy_error
  hotspot_error optional
```

### 6.6 `device_bridges/pinn_bridge.py` 신설

PINN은 agent가 아니라 worker/tool bridge로 두는 것이 좋다.

신설 목적:

```text
Analysis Agent와 BO Agent가 PINN을 tool로 호출한다.
PINN은 long-running train job과 fast predict job을 분리한다.
```

권장 class:

```text
PINNBridgeConfig
PINNBridge.health()
PINNBridge.build_dataset(payload)
PINNBridge.train(payload)
PINNBridge.predict(payload)
PINNBridge.evaluate(payload)
PINNBridge.model_registry()
```

MVP backend:

```text
backend: deepxde_optional
fallback: deterministic_fixture_model for test only
```

PINN 입력:

```text
- geometry parameters: relative_density, cell_size_mm, tpms_thickness, wall_thickness_mm, orientation_deg
- material params: E, nu, yield_strength, density
- loadcase: compression/cyclic, displacement/rate/load
- UTM curve: force/displacement/stress/strain
- FEA curve/field: reaction curve, displacement field, stress/strain field
```

PINN 출력:

```text
- predicted_curve
- predicted_field optional
- uncertainty
- residual_score
- model_id
- checkpoint_path
- metrics
- provenance
```

Loss 구성:

```text
L = w_utm * L_curve
  + w_fea * L_sim
  + w_phys * L_pde
  + w_bc * L_bc
  + w_reg * L_reg
```

초기 전략:

```text
1. UTM curve + FEA curve supervised surrogate부터 시작한다.
2. PDE residual을 바로 강하게 넣지 않는다.
3. adaptive weight 또는 staged curriculum을 사용한다.
4. uncertainty는 deep ensemble을 우선한다.
```

### 6.7 `mcp_tools/pinn_tools.py` 신설

등록할 tool:

```text
pinn.health
pinn.dataset.build
pinn.train
pinn.predict
pinn.evaluate
pinn.registry
```

Live mode 정책:

```text
pinn.train은 long-running job으로 시작하고 즉시 job_id 반환
pinn.predict는 현재 활성 model_id가 있을 때만 빠르게 실행
model이 없으면 unavailable을 명확히 반환하고 Analysis는 UTM/FEA만으로 진행
```

### 6.8 `experiments/job_queue.py`

현재 역할:

```text
per-device synchronous FIFO wrapper
```

변경 방향:

```text
live hardware queue와 heavy compute queue를 분리한다.
```

추가 권장:

```text
ComputeJobQueue 또는 SolverJobQueue
- submit_async
- status
- cancel
- stream events
- artifact registration
```

주의:

```text
FastAPI request thread에서 ccx solve/PINN train을 직접 돌리면 안 된다.
Live GUI는 job_id와 stream 상태를 봐야 한다.
```

### 6.9 `experiments/api.py`

현재 역할:

```text
ExperimentRuntime facade, virtual/printer bridge evaluation
```

변경 방향:

```text
ExperimentRuntime은 그대로 두고, multi-fidelity evaluation bridge를 추가한다.
```

추가 bridge 옵션:

```text
analysis_multifidelity
calculix
surrogate
calibration
```

하지만 기존 `BridgeName` Literal을 바로 깨지 않도록, 초기에는 `execution.bridge="analysis"` + metadata/tool routing으로 처리하는 편이 안전하다.

### 6.10 `agents/bo_agent.py`

현재 역할:

```text
BO/MBO candidate recommendation
```

변경 방향:

```text
Analysis에서 온 trust_score와 fidelity_records를 acquisition score에 반영한다.
```

추가할 입력:

```text
bo_handoff.trust_score
bo_handoff.fidelity_records
bo_handoff.comparison
bo_handoff.recommended_next_action
bo_handoff.constraints_from_analysis
```

추천 score 구성:

```text
combined_score
= numeric_acquisition_score
+ expected_information_gain
- failure_risk_penalty
- low_trust_penalty
- manufacturability_penalty
```

규칙:

```text
trust_score.gate == block:
  BO는 다음 물리 실험 후보를 만들지 않고 재측정/재해석 제안만 한다.

trust_score.gate == calibrate_only:
  BO는 FEA calibration candidate 또는 추가 simulation batch만 제안한다.

trust_score.gate == allow_bo:
  BO는 다음 design constraints를 생성한다.
```

### 6.11 `agents/guardian_agent.py`

현재 역할:

```text
Safety/quality gate, uncertainty 기반 retry/action 판단
```

변경 방향:

```text
Guardian이 trust_score를 graph-wide action gate로 사용한다.
```

추가 gate:

```text
- trust_score < 0.55: block physical next loop
- missing UTM provenance: block live BO update
- CalculiX solver failed but live claims FEA validated: block
- PINN prediction with no model provenance: warning/block depending mode
- field/curve disagreement above threshold: calibration required
```

### 6.12 `graphs/configs/atr_closed_loop.yaml`

현행 순서는 유지한다.

추가할 metadata/edge annotation:

```text
analysis node output_contract:
- canonical_curve.v1
- cae_result.v1
- multifidelity_comparison.v1
- trust_score.v1
- analysis_bo_handoff_v2

bo node input_contract:
- analysis_bo_handoff_v1 or v2
- experiment_evaluation.v1
- trust_score.v1

guardian node input_contract:
- trust_score.v1
- bo_recommendation
- live action request
```

conditional edge를 바로 크게 바꾸기보다, 우선 Analysis/BO/Guardian 내부에서 gate를 처리한다.

### 6.13 `web/static/planning.js` / Live GUI

현재 존재:

```text
FEM/CAE contour card
BO surrogate/acquisition card
agent report sections
```

추가할 UI:

```text
Analysis report:
- UTM curve panel
- FEA curve overlay
- PINN prediction curve optional
- trust score badge
- trust score component bars
- provenance drawer
- artifact links

BO report:
- acquisition graph
- trust-aware candidate ranking
- candidate chosen/not chosen reason

Guardian report:
- trust gate result
- block/calibrate/allow reason
```

원칙:

```text
raw JSON은 기본 노출하지 않는다.
그래프/표/요약 중심으로 표시한다.
큰 VTK viewer는 MVP에서 하지 않는다.
```

### 6.14 `/cae` workspace

현재 `/cae`는 open-source CAE workspace 역할을 한다.

추가할 항목:

```text
- CalculiX executable health
- ccx2paraview/frd2vtu health
- last job list
- .inp preview/download
- curve overlay preview
- contour preview
- mesh/loadcase summary
```

### 6.15 `/bo` workspace

추가할 항목:

```text
- trust-aware BO toggle
- acquisition function selection
- fidelity source filters: UTM only / UTM+FEA / UTM+FEA+PINN
- active model selection: no surrogate / PINN / FNO later
- candidate rejection reasons
```

---

## 7. 구현 단계 계획

### Stage 0. 문서/계약 고정

목표:

```text
코드를 바로 갈아엎지 않고 schema, artifact, tool contract부터 확정한다.
```

작업:

```text
1. 이 개선안을 기준으로 docs/agents/analysis_utm_runtime_guideline.txt 갱신
2. docs/agents/cae_analysis_runtime_guideline.txt 갱신
3. docs/agents/bo_agent_runtime_guideline.txt 갱신
4. docs/runtime/autonomous_experiment_runtime.md에 multi-fidelity schema 추가
5. docs/runtime/architecture.md에 CalculiX/PINN evidence layer 추가
```

검증:

```bash
rg -n "multifidelity|CalculiX|PINN|trust_score" docs 개선안
```

### Stage 1. Schema + test fixture

목표:

```text
UTM/FEA/PINN/job/trust score schema를 추가하되 기존 ExperimentEvaluationResult를 깨지 않는다.
```

파일:

```text
experiments/schemas.py
tests/unit/test_multifidelity_schemas.py
```

테스트:

```bash
pytest tests/unit/test_multifidelity_schemas.py -v
pytest tests/unit/test_experiment_runtime.py -v
```

### Stage 2. UTM ingest 강화

목표:

```text
장비 결과 CSV를 canonical UTMRecord로 만들고 artifact를 남긴다.
```

파일:

```text
mcp_tools/utm_tools.py
device_bridges/utm_macro_bridge.py
agents/analysis_agent.py
tests/unit/test_utm_multifidelity_ingest.py
```

출력 artifact:

```text
canonical_curve.json
canonical_curve.csv
utm_record.json
provenance.json
```

검증:

```bash
pytest tests/unit/test_utm_tools.py tests/unit/test_analysis_agent.py -v
```

### Stage 3. Real CalculiX bridge 추가

목표:

```text
현재 deterministic CAE를 유지하면서 실제 CalculiX worker를 추가한다.
```

파일:

```text
device_bridges/calculix_bridge.py
mcp_tools/calculix_tools.py
scripts/ccx_postprocess.py
configs/devices.yaml
tests/unit/test_calculix_bridge.py
tests/integration/test_calculix_smoke.py
```

출력 artifact:

```text
model.inp
result.dat
result.frd
curve.json
field_asset.vtu or field_asset.json
contour.png or contour.svg
solver_meta.json
```

검증:

```bash
python -m py_compile device_bridges/calculix_bridge.py scripts/ccx_postprocess.py
pytest tests/unit/test_calculix_bridge.py -v
```

Live mode 주의:

```text
ccx/gmsh/ccx2paraview가 없으면 live에서 명확히 blocked 처리한다.
test mode에서는 deterministic CAE를 계속 허용한다.
```

### Stage 4. Analysis Agent 멀티피델리티 comparator

목표:

```text
UTM/FEA/PINN evidence를 비교하고 trust_score를 만든다.
```

파일:

```text
agents/analysis_agent.py
tests/unit/test_analysis_multifidelity.py
tests/integration/test_controller_run.py
```

출력:

```text
multifidelity_comparison.v1
trust_score.v1
analysis_bo_handoff_v2
```

검증:

```bash
pytest tests/unit/test_analysis_agent.py tests/unit/test_analysis_multifidelity.py -v
pytest tests/integration/test_controller_run.py -v
```

### Stage 5. PINN bridge/tool MVP

목표:

```text
PINN을 Analysis/BO가 호출 가능한 optional surrogate worker로 추가한다.
```

파일:

```text
device_bridges/pinn_bridge.py
mcp_tools/pinn_tools.py
configs/devices.yaml
configs/models.yaml
tests/unit/test_pinn_bridge.py
```

초기 구현 원칙:

```text
1. DeepXDE가 없으면 health.available=false.
2. test mode는 deterministic fixture model로 predict만 가능.
3. train은 long-running job contract만 먼저 만든다.
4. 실제 train은 Stage 8 이후에 활성화한다.
```

검증:

```bash
pytest tests/unit/test_pinn_bridge.py -v
```

### Stage 6. BO Agent trust-aware acquisition

목표:

```text
BO가 low-trust 결과를 무시하고, calibrated/trusted evidence만 다음 후보에 반영한다.
```

파일:

```text
agents/bo_agent.py
tests/unit/test_bo_agent.py
tests/integration/test_bo_gui_api.py
```

검증:

```bash
pytest tests/unit/test_bo_agent.py tests/integration/test_bo_gui_api.py -v
```

### Stage 7. Guardian trust gate

목표:

```text
Guardian이 multi-fidelity trust score를 물리 실행 gate로 사용한다.
```

파일:

```text
agents/guardian_agent.py
tests/unit/test_guardian_agent.py
```

검증:

```bash
pytest tests/unit/test_guardian_agent.py -v
```

### Stage 8. Live GUI 표시

목표:

```text
Analysis/BO/Guardian report에 curve, contour, trust, provenance를 사람이 볼 수 있게 표시한다.
```

파일:

```text
web/static/planning.js
web/static/styles.css
web/templates/planning.html
tests/ui/planning_browser_audit.py
tests/ui/live_gui_agent_reference_layout_audit.py
```

검증:

```bash
node --check web/static/planning.js
pytest tests/ui/planning_browser_audit.py -v
```

브라우저 검증 항목:

```text
- Analysis message에 UTM/FEA curve overlay 표시
- FEM contour card 표시
- trust score badge 표시
- BO card가 trust-aware ranking 표시
- raw JSON이 기본 화면에 도배되지 않음
```

### Stage 9. Real PINN train/evaluate

목표:

```text
DeepXDE 또는 PyTorch 기반 PINN training을 실제로 돌릴 수 있게 한다.
```

파일:

```text
device_bridges/pinn_bridge.py
scripts/pinn_train_curve_surrogate.py
scripts/pinn_predict_curve_surrogate.py
requirements/ 또는 docs/runtime/requirements 문서
```

권장 시작점:

```text
- curve surrogate: geometry/material/loadcase -> stress-strain/force-displacement curve
- FEA synthetic data + UTM real data mixture
- ensemble 3개 모델로 uncertainty 추정
```

검증:

```bash
python scripts/pinn_train_curve_surrogate.py --fixture tests/fixtures/multifidelity/small_dataset.json --steps 100
python scripts/pinn_predict_curve_surrogate.py --model artifacts/pinn/... --sample tests/fixtures/multifidelity/sample.json
```

### Stage 10. Full closed-loop smoke

목표:

```text
test mode에서 5 cycle이 끝까지 돌고, 각 cycle마다 UTM/CAE/Analysis/BO/Guardian evidence가 남는다.
```

검증:

```bash
pytest tests/integration/test_controller_run.py -v
pytest tests/ui/planning_browser_audit.py -v
```

추가 검증:

```text
- run artifact에 canonical_curve.json 존재
- run artifact에 trust_score.json 존재
- bo_handoff에 trust_score 포함
- Guardian decision에 trust gate 결과 포함
- Live GUI에 contour/curve/trust 표시
```

---

## 8. PINN 상세 수립 계획

### 8.1 PINN을 넣는 위치

PINN은 독립 stage agent로 넣지 않는다.

```text
잘못된 구조:
analysis -> pinn_agent -> bo

권장 구조:
analysis_agent --tool--> pinn.predict/train
analysis_agent -> bo_agent
```

이유:

```text
1. PINN은 실험 절차의 물리 stage가 아니라 analysis surrogate다.
2. 학습은 오래 걸릴 수 있으므로 graph stage를 막으면 안 된다.
3. 없는 모델일 때도 UTM/FEA만으로 루프가 돌아야 한다.
4. BO와 Guardian은 PINN 자체보다 Analysis가 검증한 evidence를 봐야 한다.
```

### 8.2 PINN MVP 범위

MVP에서 PINN이 해야 할 일:

```text
- UTM/FEA curve를 입력 dataset으로 등록
- geometry/material/loadcase feature를 받아 curve prediction
- uncertainty 또는 confidence 반환
- model_id/checkpoint/provenance 기록
```

MVP에서 하지 말아야 할 일:

```text
- 복잡한 3D field PINN full solve
- 임의 geometry mesh에 대한 direct PDE solve
- live loop를 blocking하는 긴 학습
- LLM이 PDE residual 코드를 즉석 생성
```

### 8.3 데이터셋 구조

```text
artifacts/pinn/datasets/<dataset_id>/
  dataset_manifest.json
  samples.jsonl
  curves/
    <specimen_id>_utm_curve.json
    <specimen_id>_fea_curve.json
  fields/
    <specimen_id>_fea_field_meta.json optional
  splits.json
```

`samples.jsonl` 예시:

```json
{
  "sample_id": "specimen-cand-1-loop-3",
  "specimen_id": "specimen-cand-1",
  "geometry": {
    "geometry_type": "gyroid",
    "relative_density": 0.32,
    "cell_size_mm": 5.0,
    "tpms_thickness": 0.36
  },
  "material": {
    "elastic_modulus_mpa": 1800.0,
    "poisson_ratio": 0.35
  },
  "loadcase": {
    "type": "compression",
    "rate_mm_min": 1.0
  },
  "utm_curve_uri": "curves/specimen-cand-1_utm_curve.json",
  "fea_curve_uri": "curves/specimen-cand-1_fea_curve.json",
  "quality": {
    "utm_ok": true,
    "fea_ok": true,
    "trust_score": 0.81
  }
}
```

### 8.4 학습 전략

초기:

```text
- 입력: geometry/material/loadcase vector
- 출력: normalized force-displacement curve 또는 key metrics
- 모델: small MLP + physics penalty
- loss: UTM curve supervised + FEA curve supervised + monotonic/energy regularization
```

중기:

```text
- DeepXDE inverse/calibration PINN
- FEA residual 또는 boundary consistency 추가
- ensemble uncertainty
```

장기:

```text
- NeuralOperator/FNO/GINO
- field prediction
- geometry family generalization
- multi-fidelity BO와 결합
```

### 8.5 PINN loss 세부

```text
L_total
= w_utm * RMSE(pred_curve, utm_curve)
+ w_fea * RMSE(pred_curve, fea_curve)
+ w_metric * RMSE(pred_metrics, measured_metrics)
+ w_phys * physics_residual
+ w_bc * boundary_condition_penalty
+ w_mono * monotonicity_or_energy_penalty
+ w_reg * parameter_regularization
```

초기 weight:

```text
w_utm = 1.0
w_fea = 0.4
w_metric = 0.5
w_phys = 0.1
w_bc = 0.1
w_mono = 0.05
w_reg = 1e-4
```

단, 이 값은 default일 뿐이고 artifact에 반드시 저장한다.

### 8.6 PINN inference가 BO에 주는 값

```json
{
  "schema": "pinn_prediction.v1",
  "model_id": "pinn-curve-surrogate-001",
  "specimen_id": "specimen-cand-1",
  "candidate_id": "bo-cand-4",
  "predicted_metrics": {
    "peak_force_N": 410.2,
    "stiffness_N_per_mm": 125.4,
    "energy_absorption_mJ": 830.5
  },
  "uncertainty": {
    "peak_force_N_std": 28.0,
    "coverage_90": 0.84
  },
  "residual_score": 0.12,
  "provenance": {
    "checkpoint_path": "artifacts/pinn/models/.../checkpoint.pt",
    "dataset_id": "pinn-dataset-...",
    "code_hash": "..."
  }
}
```

---

## 9. GUI 반영 계획

### 9.1 Live GUI Analysis card

보여줄 항목:

```text
- UTM curve: measured force-displacement
- FEA curve: simulated reaction-displacement
- PINN curve: predicted curve optional
- objective score
- uncertainty
- trust score
- trust component bar
- artifact links
```

표현:

```text
curve overlay는 Plotly 또는 lightweight SVG
contour는 PyVista/ccx2paraview 결과 image artifact
field viewer는 MVP에서 image 중심
```

### 9.2 Report 측면

Agent report는 다음 순서가 좋다.

```text
1. Evidence Summary
2. UTM Curve Quality
3. FEA Result Summary
4. UTM-FEA Agreement
5. PINN Prediction optional
6. Trust Score / Gate
7. BO Handoff
8. Provenance
```

### 9.3 `/cae` workspace

실사용 버튼:

```text
- Health Check
- Build Input Deck
- Run CalculiX Smoke
- Postprocess Latest
- Open Artifact
- Compare With Latest UTM
```

### 9.4 `/bo` workspace

실사용 버튼:

```text
- Load Latest Analysis Handoff
- Run Trust-aware Candidate Ranking
- Compare Acquisition Functions
- Export Next Design Constraints
```

---

## 10. 테스트 전략

### 10.1 Unit tests

```text
tests/unit/test_multifidelity_schemas.py
tests/unit/test_utm_multifidelity_ingest.py
tests/unit/test_calculix_bridge.py
tests/unit/test_analysis_multifidelity.py
tests/unit/test_pinn_bridge.py
tests/unit/test_bo_agent.py
tests/unit/test_guardian_agent.py
```

### 10.2 Integration tests

```text
tests/integration/test_controller_run.py
- test mode 5-cycle loop
- canonical UTM artifact 존재
- CAE artifact 존재
- trust_score 존재
- BO handoff에 trust_score 포함

tests/integration/test_cae_gui_api.py
- /cae health
- deterministic mode
- real solver unavailable block
```

### 10.3 UI tests

```text
tests/ui/planning_browser_audit.py
- FEM contour card
- UTM/FEA curve overlay
- trust badge
- BO graph collapsed-by-default

tests/ui/live_runtime_ide_browser_audit.py
- artifact lineage
- runtime graph event
```

### 10.4 Manual validation

```text
1. atr -s start
2. Main GUI -> Test Mode
3. Live GUI -> 테스트 모드, 가상 브릿지
4. 5-cycle 완료 확인
5. Analysis report에서 curve/contour/trust 확인
6. BO report에서 acquisition/candidate 확인
7. Guardian report에서 trust gate 확인
```

---

## 11. 위험요소와 대응

| 위험 | 원인 | 대응 |
|---|---|---|
| Live loop가 느려짐 | CalculiX/PINN을 request thread에서 실행 | solver/train worker 분리 |
| PINN 결과를 과신 | 학습 데이터 부족 | trust score와 Guardian gate로 제한 |
| FEA/UTM 좌표 불일치 | geometry/BC/material mismatch | canonical metadata와 calibration job 추가 |
| GUI가 무거워짐 | raw field viewer 직접 렌더링 | contour PNG/SVG와 curve JSON 우선 |
| 기존 test 깨짐 | ExperimentEvaluationResult field 변경 | optional 확장만 사용 |
| BO가 잘못된 결과 학습 | low-quality UTM/FEA 반영 | ok_for_bo와 trust gate 필수화 |
| Live 장비 실행 오작동 | UTM/FEA/PINN unavailable인데 다음 단계 진행 | fail-closed, unavailable reason 명시 |

---

## 12. Definition of Done

이 개선안은 아래가 통과해야 완료로 본다.

```text
1. test mode 5-cycle loop가 끝까지 돈다.
2. 각 cycle에서 UTM canonical artifact가 남는다.
3. 각 cycle에서 CAE result 또는 명시적 unavailable artifact가 남는다.
4. Analysis Agent가 trust_score.v1을 만든다.
5. BO Agent가 trust_score를 읽고 candidate ranking에 반영한다.
6. Guardian이 trust_score gate를 decision에 반영한다.
7. Live GUI에서 curve/contour/trust/provenance가 raw JSON 없이 보인다.
8. PINN bridge는 health/train/predict contract를 갖고, 설치 안 된 상태에서도 fail-closed로 동작한다.
9. docs/runtime/current_code_snapshot.md 또는 관련 docs에 실제 구현 상태가 반영된다.
10. pytest와 UI audit이 통과한다.
```

---

## 13. 최종 권장 실행 순서

바로 구현한다면 순서는 다음이 가장 안전하다.

```text
1. Schema 추가
2. UTM canonical artifact 강화
3. Analysis trust_score 추가
4. BO/Guardian trust gate 연결
5. Live GUI trust/curve 표시
6. CalculiX real bridge 추가
7. ccx postprocess 추가
8. PINN bridge contract 추가
9. PINN lightweight predict/train 추가
10. DIC/NeuralOperator는 L2/L3로 분리
```

가장 먼저 할 일은 PINN이 아니다. 가장 먼저 할 일은 `Analysis Agent가 UTM/FEA evidence를 신뢰도 있는 BO 입력으로 바꾸는 것`이다. PINN은 그 신뢰도 체계 위에 올라가야 한다.

---

## 14. 참고 자료

- CalculiX input/output: https://web.mit.edu/calculix_v2.7/CalculiX/ccx_2.7/doc/ccx/node160.html
- CalculiX project: https://www.calculix.de/
- ccx2paraview: https://github.com/calculix/ccx2paraview
- frd2vtu: https://pypi.org/project/frd2vtu/
- DICe: https://github.com/dicengine/dice
- DICe docs: https://dicengine.github.io/dice/
- DeepXDE docs: https://deepxde.readthedocs.io/
- DeepXDE paper: https://epubs.siam.org/doi/10.1137/19M1274067
- NVIDIA PhysicsNeMo: https://developer.nvidia.com/physicsnemo
- NVIDIA Modulus PINN theory: https://docs.nvidia.com/deeplearning/modulus/modulus-v2209/user_guide/theory/phys_informed.html
- NeuralOperator docs: https://neuraloperator.github.io/
- PyTorch NeuralOperator ecosystem note: https://pytorch.org/blog/neuraloperatorjoins-the-pytorch-ecosystem/
- PyVista Plotter/screenshot: https://docs.pyvista.org/api/plotting/_autosummary/pyvista.Plotter.html
- PyVista screenshot API: https://docs.pyvista.org/api/plotting/_autosummary/pyvista.Plotter.screenshot.html
- Plotly Python: https://plotly.com/python/
