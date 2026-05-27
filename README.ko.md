# Autonomous Researcher Framework

Autonomous Researcher Framework는 실험 설계-제작-평가를 하나의 폐루프 파이프라인으로 연결한 멀티 에이전트 시스템입니다.
LangGraph 기반 런타임, Live GUI, 장비 브릿지(Prusa/LeRobot/Windows), BO/CAE 분석 파이프라인을 포함합니다.

## 1) 준비 항목

- 작업 경로: `/home/jin/autonomous_researcher`
- Python 3.10 이상
- Git
- vLLM 사용 시 NVIDIA GPU 및 Docker/k3s 환경(또는 Ollama 대체 경로)
- 로컬 캐시 디렉터리 접근 권한

## 2) 설치

```bash
cd /home/jin/autonomous_researcher
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash install/install_cli.sh
```

참고

- `atr` 명령을 사용하려면 새 터미널에서 `source ~/.bashrc` 또는 새 터미널 열기
- 런처 없이 실행하려면 `.venv/bin/python -m app.serve`

## 3) 서버 실행/종료

```bash
atr up      # 실행
atr down    # 정지
```

실행 후 접속 URL

- 메인: `http://localhost:7860`
- API 문서: `http://localhost:7860/docs`
- Live GUI: `http://localhost:7860/live`
- Runtime IDE: `http://localhost:7860/ide`
- 모듈 관리: `http://localhost:7860/module-management`

## 4) 실행 모드

- `live`
  - 실제 장비를 사용하는 실행(Prusa / LeRobot / Windows 장비 브릿지)
- `test`
  - dry-run 중심의 테스트 실행
- `virtual`
  - 물리 액션 없이 평가/벤치마크만 수행

모든 모드는 공통 실험 계약(Experiment Runtime)에 의해 처리됩니다.
- `experiment.evaluate`
- `experiment.benchmark`
- `experiment.queue.status`

## 5) 기본 실행 흐름

```text
Main GUI -> Live GUI -> Orchestrator -> LangGraph -> Stage Agents -> Bridges -> Guardian
```

기본 단계

1. Design
2. Specimen
3. Vision
4. Manipulation
5. Equipment
6. Analysis
7. Knowledge
8. BO
9. Guardian -> Complete/Stop/Error

## 6) 처음 실행 권장 절차

1. 의존성 점검(`REQUIREMENTS.md`)을 완료한다.
2. `atr up`으로 GUI 실행.
3. `http://localhost:7860/live` 접속.
4. 먼저 테스트 모드로 확인:
   - 모델 상태 확인 후 필요 시 수동 로드
   - Test 모드 선택
   - Start 실행
5. 설계→시편→구체화 흐름과 로그/아티팩트를 확인.
6. 장비 호출이 생긴 경우 `job_id` 및 큐 상태를 확인.
7. 모든 필수 입력과 체크가 완료된 뒤 실제 Live 모드 진행.

## 7) 장비 연동 가이드

- 3DP(Prusa): `docs/hardware/printer_agent_prusabridge_phase1_runtime_guideline.txt`
- Prusa 운영 체크: `docs/hardware/prusa_mk4s_live_validation_20260506.md`
- LeRobot/Manipulator: `docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md`
- Windows 제어 브릿지: `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`

## 8) 튜토리얼

- [첫 번째 자동실행 가이드(영문)](docs/tutorials/first_autonomous_run.en.md)
- [첫 번째 자동실행 가이드(한글)](docs/tutorials/first_autonomous_run.ko.md)

## 9) 핵심 문서 맵

- [`docs/runtime/langgraph_runtime.md`](docs/runtime/langgraph_runtime.md)
- [`docs/runtime/autonomous_experiment_runtime.md`](docs/runtime/autonomous_experiment_runtime.md)
- [`docs/runtime/agent_program_baseline.md`](docs/runtime/agent_program_baseline.md)
- [`docs/README.md`](docs/README.md)

## 10) 운영 트러블슈팅

- 모델 호출이 실패하면 가장 먼저 세션 오염(이전 대화)과 토큰 크기를 점검한다.
- 프린터 작업이 멈추면 `printer.prepare` 결과, `job_id`, 장비 큐 상태, `allow_*` 게이트를 확인한다.
- Live GUI가 상태를 놓치면 SSE/heartbeat 상태를 확인하고 새로고침한다.

## 11) 운영/기여 규칙

- `main`은 기본 동작 보장 브랜치로 유지.
- 위험 변경은 브랜치에서 진행 후 검증하고 병합.
- 런타임 동작 변경 시 문서(`docs/*`, `REQUIREMENTS.md`) 동시 업데이트.
