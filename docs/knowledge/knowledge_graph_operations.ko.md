---
doc_type: guide
subtype: operations_runbook
status: active
authority: procedural
audience:
  - operator
  - developer
scope:
  - knowledge_graph
  - neo4j_sync
  - knowledge_workspace
summary: ATR Knowledge ledger, durable outbox, Neo4j sync, bounded query, and workspace를 안전하게 운영하는 절차.
source_of_truth:
  - knowledge/service.py
  - knowledge/reconciliation_service.py
  - knowledge/relation_store.py
  - knowledge/durable_outbox.py
  - knowledge/graph_sync_worker.py
  - knowledge/ontology/atr_core.v1.yaml
  - scripts/knowledge_graph_cli.py
  - app/main.py
  - web/static/knowledge.js
last_verified: 2026-08-09
verified_against: 4329853
related_docs:
  - docs/runtime/current_code_snapshot.md
  - docs/runtime/langgraph_runtime.md
  - docs/standards/documentation_standard.md
supersedes: []
---

# Knowledge Graph 운영 가이드

## Summary

ATR Knowledge 계층의 append-only ledger, durable outbox, 선택적 Neo4j
동기화, allowlisted graph query, 관계 reconciliation, `/knowledge` Workspace를
운영하는 runbook입니다.
Neo4j 장애 시 기록을 보존한 채 degraded 상태를 확인하고, 연결 복구 뒤
bounded sync로 재전송하는 것이 기본 경로입니다.

## Audience and Outcome

운영자는 이 Guide를 통해 Knowledge 상태와 적체를 진단하고, 데이터 손실 없이
Neo4j를 시작·동기화·복구하며, 조회 결과와 UI가 기록된 ledger/graph 상태를
반영하는지 확인할 수 있습니다.

## Scope

이 Guide는 로컬 ATR Knowledge runtime과 `/knowledge` Workspace를 다룹니다.
ontology schema 변경, raw Cypher 운영, dead-letter 파일 수동 삭제, 물리 장비
제어는 범위 밖입니다.

## Source of Truth

- `knowledge/service.py`, `knowledge/audit_ledger.py`,
  `knowledge/durable_outbox.py`, `knowledge/graph_sync_worker.py`
- `knowledge/ontology/atr_core.v1.yaml`과 ontology validator
- `knowledge/neo4j_repository.py`와 migration Cypher
- `scripts/knowledge_graph_cli.py`
- `app/main.py`의 `/api/knowledge/*` routes
- `web/templates/knowledge.html`과 `web/static/knowledge.js`

## Prerequisites

- repository의 `.venv`와 Python 의존성이 설치되어 있어야 합니다.
- Neo4j backend를 사용할 때는 Docker/Neo4j runtime과 로컬 자격정보가
  준비되어야 합니다.
- ATR 서버 API 검증에는 `127.0.0.1:7860`에서 서버가 실행 중이어야 합니다.
- 비밀번호와 연결정보는 `.env` 또는 Git에서 제외된 로컬 설정에만 둡니다.

## Safety Boundary

- `GET /api/knowledge/*` 조회와 allowlisted query plan은 read-only입니다.
- `graph/sync`, `graph/import`, `graphify/import`, ontology/migration 작업은
  저장 상태를 변경하므로 적체·backend·대상 범위를 먼저 확인해야 합니다.
- 브라우저, LLM, API에서 raw Cypher를 실행하지 않습니다.
- pending/dead-letter 파일을 직접 삭제하거나 acknowledged로 이동해 상태를
  조작하지 않습니다.
- Knowledge 작업은 물리 장비를 직접 구동하지 않지만, 안전/Guardian evidence를
  훼손하면 후속 판단에 영향을 줄 수 있으므로 append-only 기록을 보존합니다.

## Current Data Flow

ATR Knowledge 계층은 다음 순서로 기록합니다.

컴파일된 목적함수가 활성화된 run에서는 Analysis가 생성한
`objective_evaluation.v1`도 같은 흐름으로 기록합니다. 이 레코드는
`objective_id`, `objective_version`, `objective_hash`, observation, score,
feasibility, contribution, constraint, uncertainty, fidelity, provenance를
포함합니다. Knowledge는 이 값을 LLM으로 재계산하지 않습니다.

서로 다른 `objective_hash`의 실험 결과는 동일 목적함수의 반복 측정으로
합치지 않습니다. `JsonlKnowledgeStore.list_experiment_records`의
`objective_hash` 필터로 동일 정의의 evidence만 조회하며, BO에도 같은 hash와
provenance가 있는 관측만 전달합니다.

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
memory/knowledge/reconciliation/work_queue.json        증분 관계 검사 대기열
memory/knowledge/reconciliation/proposals.jsonl         변경 불가능한 LLM 관계 제안
memory/knowledge/reconciliation/decisions.jsonl         승인/반려/보류 결정 원장
memory/knowledge/reconciliation/graph_edit_decisions.jsonl  Graph Edit 적용 원장
memory/knowledge/reconciliation/drafts/                 검증 중인 graph edit 초안
```

`memory/`는 Git에 포함되지 않습니다.

## Procedure: Neo4j 시작

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

## Procedure: 상태와 동기화

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

## Procedure: Live GUI 활동 히스토그램

1. `/live`에서 `KNW` Knowledge Agent를 선택합니다.
2. Report 화면 상단의 `Knowledge Activity` 카드에서 cycle별 활동을 확인합니다.
3. 흰색 논문형 누적 히스토그램의 계열은 `Collected`, `Updated`, `Retrieved`, `Used`입니다.
4. 차트는 Knowledge Report가 선택된 동안에만 약 1초 간격으로 집계 API를 확인합니다.
5. 리포트의 다른 카드가 갱신되어도 차트 canvas는 보존되며 데이터 payload만 교체됩니다.

현재 `used`는 이벤트에 명시된 실제 consumer 기록만 집계합니다. consumer가 기록되지 않은 호출을 UI에서 추정하거나 보정하지 않습니다.

## Procedure: Knowledge Workspace

Main GUI의 `Device Workspaces > Knowledge Workspace` 또는 `/knowledge`에서 엽니다.

| 탭 | 기능 |
|---|---|
| Graph Explorer | 허용된 runtime query plan, 최대 depth 4 / limit 100, 노드 선택과 provenance 확장 |
| Memory | agent performance, failure/success pattern, evolution pack, 활동 히스토그램 |
| Ontology | 활성 ontology 버전, class, relation domain/range |
| Sync | durable outbox의 pending 이벤트를 제한된 batch로 Neo4j에 재전송 |
| Project Graph | Graphify로 적재한 file/module/API/tool/concept 연결 조회 |
| Relation Review | 관계 gap, LLM 제안, 근거, 승인/수정 승인/반려/보류/재평가와 결정 이력 |

상단 상태 스트립은 `/api/knowledge/graph/stats`에서 backend, ontology, node/edge, pending/dead-letter 값을 직접 읽습니다. Graph Explorer와 Project Graph는 전체 그래프를 내려받지 않고 bounded subgraph만 렌더링합니다. 노드를 더블클릭하거나 `Expand provenance`를 누르면 해당 식별자를 대상으로 `provenance_trace` query plan을 실행합니다.

### Relation Review

관계 reconciliation은 기존 노드와 활성 ontology의 관계 유형만 사용합니다. LLM은
후보를 제안할 뿐 Neo4j나 raw Cypher를 직접 실행하지 않습니다.

```bash
curl -s http://127.0.0.1:7860/api/knowledge/relations/summary
curl -s http://127.0.0.1:7860/api/knowledge/relations/status
curl -s -X POST http://127.0.0.1:7860/api/knowledge/relations/scan \
  -H 'Content-Type: application/json' -d '{"limit":100}'
curl -s -X POST http://127.0.0.1:7860/api/knowledge/relations/reconcile \
  -H 'Content-Type: application/json' -d '{"limit":10}'
curl -s 'http://127.0.0.1:7860/api/knowledge/relations/proposals?status=pending&limit=100'
curl -s 'http://127.0.0.1:7860/api/knowledge/relations/decisions?limit=200'
```

- `scan`은 graph gap을 제한적으로 검사하고 LLM을 호출하지 않습니다.
- `reconcile`은 현재 선택되어 이미 로딩된 모델로 최대 10개를 처리합니다.
- 백그라운드 worker는 60초 간격 또는 wake 신호로 동작하지만 모델을 직접
  로딩하지 않습니다. 모델이 없으면 `model_unloaded`, lease가 사용 중이면
  비차단 상태로 다음 기회를 기다립니다.
- LLM lease 우선순위는 Guardian `0`, 실험 workflow `10`, 운영자 chat `20`,
  relation reconciliation `30`입니다.
- 자동 승인은 LLM confidence `>=0.90`, deterministic evidence `>=0.80`, ontology
  검증, provenance, 중복/자기참조 검사를 모두 통과할 때만 가능합니다.
- 그 외 제안은 Relation Review에서 승인, 수정 승인, 반려, 보류, 재평가합니다.
  수정 승인은 source node를 유지하고 target, relation type, rationale만 바꿉니다.
- version 또는 graph-context hash가 오래되면 mutation API가 `409`를 반환하므로
  최신 proposal/context를 다시 불러온 뒤 결정합니다.

### Graph Explorer Edit Mode

`View Mode`가 기본이며 `Edit Mode`는 기존 node/relation만 편집합니다. 새 node
생성, raw Cypher, identity/provenance 수정은 허용하지 않습니다. metadata는
`label`, `alias`, `note`, `tags`만 변경할 수 있습니다.

1. `EDIT`로 전환하고 기존 relation 또는 허용 metadata를 draft에 추가합니다.
2. Undo/Redo와 draft 목록으로 변경 범위를 확인합니다.
3. `Validate`로 ontology, 기존 node, 중복, self-reference, graph revision을 검사합니다.
4. 검증 성공 뒤에만 `Apply`합니다. 적용 전 accepted graph는 바뀌지 않습니다.
5. stale revision이면 draft를 보존한 채 새 graph context와 충돌을 해결합니다.

semantic 변경은 항상 `KnowledgeService.ingest`를 거쳐 ledger, outbox, graph sync
증거를 남깁니다. layout 좌표는 UI preference이며 semantic event가 아닙니다.

### Live GUI와 ATT

Live GUI의 Knowledge Report는 `examined`, `proposed`, `auto-approved`, `pending`,
`rejected/deferred`, worker 상태를 영속 store에서 읽습니다. pending이 있으면 ATT에
제안별 카드가 아니라 `/knowledge#relations`로 연결되는 집계 카드 하나만 생깁니다.
이 상태는 실험 stage 완료나 물리 장비 handoff를 차단하지 않습니다.

## Procedure: 안전한 Graph Query

브라우저, LLM, API는 raw Cypher를 실행할 수 없습니다. 다음과 같이 허용된 query plan만 사용합니다.

```bash
curl -s -X POST http://127.0.0.1:7860/api/knowledge/graph/query \
  -H 'Content-Type: application/json' \
  -d '{"kind":"run_context","filters":{"run_id":"run-1"},"depth":2,"limit":50}'
```

허용 종류에는 `run_context`, `similar_experiments`, `failure_path`, `success_path`, `specimen_lineage`, `device_history`, `policy_history`, `bo_context`, `safety_context`, `project_context`, `impact_analysis`, `provenance_trace`가 있습니다. 최대 depth는 4, 최대 result limit은 100입니다.

## Procedure: Ontology 검증

```bash
curl -s http://127.0.0.1:7860/api/knowledge/ontology
curl -s -X POST http://127.0.0.1:7860/api/knowledge/ontology/validate \
  -H 'Content-Type: application/json' -d @knowledge_event.json
```

`atr-core-1.0.0` 클래스, 관계 domain/range, 이벤트 필드, 상태 전이에 맞지 않는 이벤트는 Neo4j에 기록되지 않습니다. 감사 원장에는 검증 실패 증거가 남습니다.

## Failure Recovery

1. `/api/knowledge/graph/stats`에서 `degraded`와 pending 수를 확인합니다.
2. Neo4j 컨테이너와 자격정보를 복구합니다.
3. `/api/knowledge/graph/sync`를 호출합니다.
4. pending이 0이고 acknowledged가 증가했는지 확인합니다.
5. dead-letter가 있으면 이벤트 오류와 ontology 위반을 검토한 뒤 수정된 migration/reconciliation 절차를 사용합니다.

pending/dead-letter 파일을 직접 삭제해서 동기화 상태를 조작하지 않습니다.

## Success Criteria

정상 운영은 다음 조건으로 확인합니다.

- `/api/knowledge/graph/stats`가 선택한 backend와 ontology
  `atr-core-1.0.0`을 반환합니다.
- Neo4j가 enabled/ready이면 sync 뒤 `outbox.pending=0`이고 acknowledged 수가
  증가하며 `dead_letter=0`입니다.
- Neo4j가 의도적으로 unavailable이면 ledger/outbox 기록이 보존되고 상태가
  `degraded`로 명시됩니다. JSON graph로의 silent fallback은 성공으로 보지
  않습니다.
- `/api/knowledge/activity`의 cycle 값은 append-only ledger의 기록과
  일치하며 UI가 누락값을 추정하지 않습니다.
- `/knowledge`는 6개 탭과 bounded subgraph만 렌더링하고 raw Cypher 입력을
  제공하지 않습니다.
- Relation Review 수치, Knowledge Report 수치, ATT 집계가 같은 durable relation
  store를 반영합니다.

## Rollback or Stop Procedure

1. 새로운 mutation 요청과 수동 sync 호출을 중단합니다.
2. `/api/knowledge/graph/stats`와 outbox 디렉터리의 pending/dead-letter 수를
   기록합니다.
3. Neo4j container를 중지해야 하면 `knowledge_graph_cli.py`의 stop 경로를
   사용하고 ledger/outbox 파일은 유지합니다.
4. 잘못된 import 또는 ontology 변경은 파일을 삭제해 숨기지 말고, 원본
   evidence를 보존한 reconciliation/migration으로 교정합니다.
5. 복구 전에는 Guardian/safety evidence가 최신 graph에 반영되었다고 선언하지
   않습니다.

## Limitations and Known Gaps

- Neo4j는 선택적 외부 runtime이므로 모든 개발 환경에서 ready 상태를
  보장하지 않습니다.
- Graph Explorer는 depth 4, result limit 100의 bounded view이며 전체 graph
  export가 아닙니다.
- `used` 활동은 명시적으로 기록된 consumer만 집계합니다.
- relation worker는 선택 모델이 이미 로딩된 경우에만 제안을 생성하며, 모델을
  자동 load하거나 실험/Guardian 호출을 기다리게 하지 않습니다.
- dead-letter 자동 수정은 제공하지 않으며 원인과 ontology/migration을
  검토한 reconciliation이 필요합니다.

## Verification

최신 코드를 별도 서버에 띄운 뒤 ARM64에 설치된 geckodriver로 1920×1080 레이아웃을 검사합니다.

```bash
.venv/bin/python tests/ui/knowledge_workspace_browser_audit.py \
  --base-url http://127.0.0.1:7861 \
  --geckodriver /snap/bin/geckodriver
```

검사는 그래프 canvas 생성, 6개 탭 전환, Relation Review/Edit Mode, 가로 overflow,
그래프/인스펙터 최소 폭을 확인하고
`artifacts/ui/knowledge_relation_workspace_1920x1080.png`를 남깁니다.

2026-08-09 구현 커밋 `4329853` 기준 API source, ontology, durable outbox/sync,
relation reconciliation 구현, Knowledge Workspace frontend와 관련
unit/integration/browser 검증을
대조했습니다. 실제 Neo4j health와 node/edge 수는 로컬 데이터에 따라 달라질
수 있으므로 고정 contract로 취급하지 않습니다.

## Related Reference

- [Current Code Snapshot](../runtime/current_code_snapshot.md)
- [LangGraph Runtime](../runtime/langgraph_runtime.md)
- [Closed Loop and Pages Reference](../runtime/closed_loop_and_pages_reference.md)
- [Documentation Standard](../standards/documentation_standard.md)
