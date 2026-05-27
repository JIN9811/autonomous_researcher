# Autonomous Researcher Framework

Autonomous Researcher Framework는 실험 계획-실행-평가 루프를 하나로 묶는 멀티 에이전트 시스템입니다.
LangGraph 기반 런타임, Live GUI, 장비 브릿지(Prusa/LeRobot/Windows), BO/CAE/분석 파이프라인을 포함합니다.

## 1) 한눈에 보기

- 주 엔트리: `cd /home/jin/autonomous_researcher`
- 실행: `atr up`
- 정지: `atr down`
- 문서 허브: [`docs/README.md`](docs/README.md)
- API 문서: `http://localhost:7860/docs`
- Live GUI: `http://localhost:7860/live`

## 2) 설치 순서

```bash
cd /home/jin/autonomous_researcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash install/install_cli.sh
```

`source ~/.bashrc` 또는 새 터미널을 열어 `atr` 명령을 PATH에 반영합니다.

Alternative(임시): ` .venv/bin/python -m app.serve `

## 3) 실행 모드

- `live`
  - 실제 장비 연동(Prusa/LeRobot/Windows)
  - `experiment.evaluate`, 장비 큐, 안전 게이트 적용
- `test`
  - 시뮬레이션/드라이런 + dry-run 기반 검증
- `virtual`
  - 물리 액션 없이 평가/벤치마크 중심 실행

실행 모드는 런타임 계약(`runtime/autonomous_experiment_runtime.md`)에 따라 일관된 인터페이스로 처리됩니다.

## 4) 핵심 아키텍처

- Runtime: LangGraph config-driven execution
- 실행 게이트: graph validate/dry-run/compile/version
- 장비 제어: 브릿지 모듈 + MCP tool registry + job queue
- 추적: 이벤트 트레이스, run artifact lineage, approval 로그
- GUI: `/live`, `/ide`, `/bo`, `/printer`, `/lerobot`, `/module-management`

## 5) 빠른 문서 맵

### 운영/핵심

- [`docs/project/Project_guide.txt`](docs/project/Project_guide.txt)
- [`docs/runtime/langgraph_runtime.md`](docs/runtime/langgraph_runtime.md)
- [`docs/runtime/autonomous_experiment_runtime.md`](docs/runtime/autonomous_experiment_runtime.md)
- [`docs/runtime/agent_program_baseline.md`](docs/runtime/agent_program_baseline.md)
- [`docs/runtime/architecture.md`](docs/runtime/architecture.md)
- [`docs/gui/live_gui_evolution_plan.md`](docs/gui/live_gui_evolution_plan.md)

### 장비 연동

- [`docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`](docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md)
- [`docs/hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt`](docs/hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt)
- [`docs/hardware/windows_pyautogui_equipment_agent_guideline.md`](docs/hardware/windows_pyautogui_equipment_agent_guideline.md)

### 에이전트 워크플로우

- [`docs/agents/specimen_design_existing_runtime_guideline.txt`](docs/agents/specimen_design_existing_runtime_guideline.txt)
- [`docs/agents/bo_agent_runtime_guideline.txt`](docs/agents/bo_agent_runtime_guideline.txt)
- [`docs/agents/vision_pickup_observation_runtime_guideline.txt`](docs/agents/vision_pickup_observation_runtime_guideline.txt)
- [`docs/agents/manipulation_pi05_transfer_runtime_guideline.txt`](docs/agents/manipulation_pi05_transfer_runtime_guideline.txt)
- [`docs/agents/analysis_utm_runtime_guideline.txt`](docs/agents/analysis_utm_runtime_guideline.txt)
- [`docs/agents/cae_analysis_runtime_guideline.txt`](docs/agents/cae_analysis_runtime_guideline.txt)

### 데스크탑/로컬 작업

- [`REQUIREMENTS.md`](/home/jin/autonomous_researcher/REQUIREMENTS.md)
- [`install/README.md`](install/README.md)
- [`docs/tutorials/first_autonomous_run.md`](docs/tutorials/first_autonomous_run.md)

## 6) 추천 실행 흐름

1. 설치 완료 후 `atr up`
2. Live GUI에서 초기 세션 생성 및 상태 확인
3. 테스트 모드로 기본 파이프라인 실행
4. 장비 브릿지 설정 및 연결 체크(Prusa/LeRobot/Windows)
5. 실험 후보를 BO/모듈 평가 후 실제 실행 전 dry-run 확인
6. 승인 후 live run 실행

## 7) 기여/운영 규칙

- 기본 브랜치는 동작 보장 상태를 유지합니다.
- 중요 변경은 브랜치에서 검증 후 병합.
- 신규 장비/프로토콜 연동은 기존 규격을 먼저 문서화하고, 그 다음 코드 변경.

## 8) Pi0.5 워크플로우(참조)

Pi0.5는 별도 LeRobot checkout/conda 환경에서 운영합니다.
상세 절차는 `docs/runtime/lerobot_dataset_policy_naming.md` 와 `docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`에 정리되어 있으며,
실행 전용 체크리스트/커맨드는 문서 기준으로 수행합니다.

## 9) 참고

현재 레포리퍼토리는 고속 실험 반복을 위한 통합 운영 레벨에서 설계되어 있으며,
구성요소별 세부 항목(브릿지 파라미터, 모델 전략, 보안 정책)은 하위 문서에서 계속 갱신됩니다.
