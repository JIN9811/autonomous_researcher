# 첫 번째 자동실험 실행 가이드

이 가이드는 오케스트레이터 대화부터 실행 완료까지의 기본 루프를 안전하게 검증하기 위한 최초 실행 절차입니다.

## 적용 범위

- 운영 항목: Live GUI, 테스트 모드, 시편 생성, 장비 큐 연동, 추적/아티팩트 확인
- 하드웨어 사용은 테스트 단계에서 선택적으로 수행

## 1) 사전 점검

첫 실행 전 아래를 확인합니다.

- 저장소 경로: `/home/jin/autonomous_researcher`
- Python 가상환경 생성/활성화
- `pip install -r requirements.txt` 완료
- `bash install/install_cli.sh` 완료
- Live GUI 포트(7860) 접근
- 모델 로드 상태 확인(필요시 수동 로드)

## 2) 시스템 시작

```bash
atr up
```

접속 URL:

- `http://localhost:7860`
- `http://localhost:7860/live`

중지:

```bash
atr down
```

## 3) 먼저 테스트 모드부터 실행

테스트 모드는 하드웨어 동작을 최소화하고 핵심 실행 체인을 점검합니다.

1. Live GUI에서 모델/백엔드 상태 확인
2. `Test` 모드 선택
3. `Start` 실행
4. 확인 포인트
   - run 상태 active 전환
   - 이벤트 스트림에서 `run.started`와 단계 전이 존재
   - printer 관련 도구가 호출되면 `job_id` 확인
   - 실패 시 에러 노드/타임라인에서 원인 확인

## 4) 테스트 모드의 출력 모드

입력 예시:

- `테스트 모드, 가상 브릿지`
- `테스트 모드, 설치 프린터`
- `테스트 모드, 실제 출력`

동작:

- 가상 브릿지: 슬라이싱 + 가상 검증 경로
- 설치 프린터: PrusaLink 연결 체크 + live gate 검증
- 실제 출력: live gate 통과 시 업로드/시작 경로

실제 출력이 gate에서 차단되면 시작 전 단계에서 중단되어 이유가 표시되어야 합니다.

## 5) Live 모드 실행

1. 대화에서 실행 트리거를 명확히 입력:

```text
실험 수행
```

2. 오케스트레이터 handoff 메시지 확인
3. Design / Specimen 단계의 후보/아티팩트 존재 확인
4. 그래프 규칙에 따른 다음 단계 진행 확인
5. BO/CAE/분석 결과를 이벤트 추적에서 확인

## 6) 런 추적/아티팩트 검증

Runtime IDE로 이동: `http://localhost:7860/ide`

최소 점검 항목:

1. 최신 run 선택
2. `run.created -> run.started -> node.started/completed` 순서 확인
3. 실패 이벤트의 노드 상세 확인
4. Artifact Lineage에서 producer/타입/경로 확인
5. 미리보기 가능한 파일은 Inline, 대형 파일은 경로 추적이 남는지 확인

## 7) 큐/복구 점검

도구 레이어 점검:

```python
ctx.tools.call("experiment.queue.status", {})
```

복구 체크리스트:

- 연결 정보 누락: `memory/prusa_connection.json` 갱신 후 시편 단계 재실행
- 모델 컨텍스트 문제: 모델 재로드 후 재시도
- 장시간 정적 상태: Live 화면에서 SSE/동기화 상태 새로고침
- 장비 점유 중: 기존 job 완료 대기 또는 정지 제어 사용

## 8) 성공 기준

- 계획/메시지 trace가 안정적으로 연결됨
- 설정한 그래프 순서대로 단계 전이됨
- 각 단계에서 가능한 stage artifact 생성
- 장비 호출 시 큐 메타데이터 존재
- Guardian 경유 완료 상태로 수렴

## 9) CLI와 GUI 일치 확인

```bash
atr model list
atr status
atr events recent
atr modules
```

CLI 출력과 GUI 상태가 동일한 큰 흐름을 보여야 합니다.
