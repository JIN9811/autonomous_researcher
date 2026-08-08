# Knowledge Graph 운영 가이드

## 구성

ATR Knowledge 계층은 다음 순서로 기록합니다.

```text
Knowledge event validation
-> append-only JSONL ledger + fsync
-> durable filesystem outbox
-> Neo4j transaction
-> acknowledged sync receipt
```

Neo4j가 중단되어도 JSONL과 pending outbox는 남습니다. 실험 루프는 `degraded` 상태로 계속할 수 있고, 연결 복구 후 pending 이벤트를 재전송합니다. Neo4j를 선택한 상태에서는 JSON graph로 자동 전환하지 않습니다.

## 저장 경로

```text
knowledge/ontology/                         버전 관리되는 ATR Core Ontology
knowledge/migrations/                       Neo4j constraint/index 정의
memory/knowledge/ledger/events/YYYY/MM/DD/  append-only 이벤트 원장
memory/knowledge/outbox/pending/             미동기화 이벤트
memory/knowledge/outbox/acknowledged/        Neo4j 동기화 영수증 포함 이벤트
memory/knowledge/outbox/dead_letter/         재시도 한도 초과 이벤트
memory/knowledge/neo4j/                      로컬 Neo4j 데이터와 로그
```

`memory/`는 Git에 포함되지 않습니다.

## Neo4j 시작

```bash
cd /home/jin/autonomous_researcher
.venv/bin/python scripts/knowledge_graph_cli.py neo4j-start --wait
```

실행 환경에는 다음 값을 설정합니다. 비밀번호는 `.env` 또는 Git에서 제외된 로컬 설정으로 관리합니다.

```bash
export ATR_KNOWLEDGE_GRAPH_ENABLED=1
export ATR_KNOWLEDGE_EVENT_PIPELINE_ENABLED=1
export ATR_KNOWLEDGE_GRAPH_BACKEND=neo4j
export ATR_KNOWLEDGE_GRAPH_FAIL_OPEN=1
export ATR_NEO4J_URI=bolt://127.0.0.1:7687
export ATR_NEO4J_USERNAME=neo4j
export ATR_NEO4J_PASSWORD='<local-password>'
export ATR_NEO4J_DATABASE=neo4j
export ATR_KNOWLEDGE_GRAPH_MAX_ATTEMPTS=5
```

## 상태와 동기화

```bash
curl -s http://127.0.0.1:7860/api/knowledge/graph/health
curl -s http://127.0.0.1:7860/api/knowledge/graph/stats
curl -s -X POST http://127.0.0.1:7860/api/knowledge/graph/sync \
  -H 'Content-Type: application/json' -d '{"limit":100}'
```

확인할 값:

- `graph.ok`: Neo4j 연결 상태
- `outbox.pending`: 아직 동기화되지 않은 이벤트 수
- `outbox.dead_letter`: 재시도 한도를 넘은 이벤트 수
- `safety_lag`: 동기화되지 않은 Guardian 이벤트 수

활동 집계는 append-only ledger를 읽으며 UI가 임의 숫자를 생성하지 않습니다.

```bash
curl -s 'http://127.0.0.1:7860/api/knowledge/activity?run_id=<run-id>&limit=20'
```

응답의 `cycles[]`에는 실험 cycle별 `collected`, `updated`, `retrieved`, `used` 수와 기록된 consumer가 포함됩니다. `limit`은 최대 100이며, Live GUI는 최근 20 cycle만 요청합니다.

## Live GUI 활동 히스토그램

1. `/live`에서 `KNW` Knowledge Agent를 선택합니다.
2. Report 화면 상단의 `Knowledge Activity` 카드에서 cycle별 활동을 확인합니다.
3. 흰색 논문형 누적 히스토그램의 계열은 `Collected`, `Updated`, `Retrieved`, `Used`입니다.
4. 차트는 Knowledge Report가 선택된 동안에만 약 1초 간격으로 집계 API를 확인합니다.
5. 리포트의 다른 카드가 갱신되어도 차트 canvas는 보존되며 데이터 payload만 교체됩니다.

현재 `used`는 이벤트에 명시된 실제 consumer 기록만 집계합니다. consumer가 기록되지 않은 호출을 UI에서 추정하거나 보정하지 않습니다.

## Knowledge Workspace

Main GUI의 `Device Workspaces > Knowledge Workspace` 또는 `/knowledge`에서 엽니다.

| 탭 | 기능 |
|---|---|
| Graph Explorer | 허용된 runtime query plan, 최대 depth 4 / limit 100, 노드 선택과 provenance 확장 |
| Memory | agent performance, failure/success pattern, evolution pack, 활동 히스토그램 |
| Ontology | 활성 ontology 버전, class, relation domain/range |
| Sync | durable outbox의 pending 이벤트를 제한된 batch로 Neo4j에 재전송 |
| Project Graph | Graphify로 적재한 file/module/API/tool/concept 연결 조회 |

상단 상태 스트립은 `/api/knowledge/graph/stats`에서 backend, ontology, node/edge, pending/dead-letter 값을 직접 읽습니다. Graph Explorer와 Project Graph는 전체 그래프를 내려받지 않고 bounded subgraph만 렌더링합니다. 노드를 더블클릭하거나 `Expand provenance`를 누르면 해당 식별자를 대상으로 `provenance_trace` query plan을 실행합니다.

## 안전한 Graph Query

브라우저, LLM, API는 raw Cypher를 실행할 수 없습니다. 다음과 같이 허용된 query plan만 사용합니다.

```bash
curl -s -X POST http://127.0.0.1:7860/api/knowledge/graph/query \
  -H 'Content-Type: application/json' \
  -d '{"kind":"run_context","filters":{"run_id":"run-1"},"depth":2,"limit":50}'
```

허용 종류에는 `run_context`, `similar_experiments`, `failure_path`, `success_path`, `specimen_lineage`, `device_history`, `policy_history`, `bo_context`, `safety_context`, `project_context`, `impact_analysis`, `provenance_trace`가 있습니다. 최대 depth는 4, 최대 result limit은 100입니다.

## Ontology 검증

```bash
curl -s http://127.0.0.1:7860/api/knowledge/ontology
curl -s -X POST http://127.0.0.1:7860/api/knowledge/ontology/validate \
  -H 'Content-Type: application/json' -d @knowledge_event.json
```

`atr-core-1.0.0` 클래스, 관계 domain/range, 이벤트 필드, 상태 전이에 맞지 않는 이벤트는 Neo4j에 기록되지 않습니다. 감사 원장에는 검증 실패 증거가 남습니다.

## 장애 복구

1. `/api/knowledge/graph/stats`에서 `degraded`와 pending 수를 확인합니다.
2. Neo4j 컨테이너와 자격정보를 복구합니다.
3. `/api/knowledge/graph/sync`를 호출합니다.
4. pending이 0이고 acknowledged가 증가했는지 확인합니다.
5. dead-letter가 있으면 이벤트 오류와 ontology 위반을 검토한 뒤 수정된 migration/reconciliation 절차를 사용합니다.

pending/dead-letter 파일을 직접 삭제해서 동기화 상태를 조작하지 않습니다.

## UI 검증

최신 코드를 별도 서버에 띄운 뒤 ARM64에 설치된 geckodriver로 1920×1080 레이아웃을 검사합니다.

```bash
.venv/bin/python tests/ui/knowledge_workspace_browser_audit.py \
  --base-url http://127.0.0.1:7861 \
  --geckodriver /snap/bin/geckodriver
```

검사는 그래프 canvas 생성, 5개 탭 전환, 가로 overflow, 그래프/인스펙터 최소 폭을 확인하고 `artifacts/ui/knowledge_workspace_1920x1080.png`를 남깁니다.
