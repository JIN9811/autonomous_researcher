<!-- atr-doc
doc_type: guide
subtype: operations_runbook
status: active
authority: procedural
audience: [operator, developer, maintainer]
scope: [knowledge, markdown_memory, scoped_rag, ontology]
summary: 기존 원본과 온톨로지를 보존하면서 Markdown 지식의 검색 범위, 출처, 수명주기와 후처리를 관리하는 절차.
source_of_truth:
  - knowledge/markdown_memory.py
  - knowledge/markdown_runtime.py
  - knowledge/http_api.py
  - agents/knowledge_decision.py
last_verified: 2026-09-10
verified_against: working-tree-2026-09-10
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/knowledge/manual_rag_knowledge.ko.md
supersedes: [docs/oldversion/knowledge/knowledge_graph_operations.ko.md]
-->

# Markdown Knowledge 운영 가이드

## Status at a Glance

| At a glance | Details |
|---|---|
| Purpose | 원본과 ontology를 보존하며 Markdown 지식의 검색·출처·수명주기 관리 |
| Workspace | Knowledge → Markdown / Memory / Ontology |
| Preparation | 조회할 run·agent·지식 범위와 원본 근거 확인 |
| Recorded basis | 2026-09-10 · [Knowledge Agent 계약](../agents/knowledge_agent.md) |

## 무엇이 바뀌었는가

지식 그래프와 Neo4j 운영 의존성만 제거했다. 온톨로지 정의, 원본 아티팩트,
기존 JSONL 기억·패턴·성능·Evolution 계약과 매뉴얼 RAG는 보존한다.
실행 순서를 표현하는 폐루프 그래프는 지식 그래프가 아니며 변경하지 않는다.

Knowledge의 LLM은 근거를 읽고, 재사용 가치와 분류를 판단하고, 범위 내 지식을
검색·상세 조회·기록하는 툴을 호출한다. 파일 저장과 조건 검증은 코드가 수행한다.
단순 기록을 위해 매 에이전트 종료마다 LLM을 호출하지 않는다.

## 저장과 확인

| 위치 | 내용 |
|---|---|
| `memory/knowledge/markdown/<run>/<cycle>/<agent>/<record>/revision-*.md` | 원본 출처와 분류를 포함한 불변 Markdown 리비전 |
| `memory/knowledge/*.jsonl` | 기존 실험 기억, 패턴, 성능 및 Evolution 기록 |
| `runs/<run>/knowledge/` | 현재 Knowledge 보고서, LLM 결정/툴 응답, 사전 입력 스냅샷 |
| `runs/<run>/runtime/loops/` | 기존 루프·에이전트·시도별 원본 아카이브 |
| `memory/knowledge/markdown_jobs/` | 명시적으로 시작한 과거 아카이브 후처리 상태 |

Use the Markdown tab at `/knowledge` to select scope, search candidates, and read
their provenance. Numerical values remain in the original Analysis records;
Markdown interpretation is not a new measurement. Memory and Ontology remain in
the workspace; [Source Library](manual_rag_knowledge.ko.md) replaces Manual RAG.

## 검색 범위

POST `/api/knowledge/markdown/query` 예시:

```json
{
  "query": "export validation",
  "scope": {
    "agent_id": ["equipment_agent", "knowledge_agent"],
    "status": "valid",
    "applicability": {"protocol_version": "example-v2"}
  },
  "top_k": 6
}
```

위 조건은 예시이며, 실제 기록에 해당 메타데이터가 있어야 검색된다. 조건을
맞추기 위해 시스템이 없는 값을 추정하거나 브릿지 설정을 변경하지 않는다.

- 기본값은 `valid` 기록이다. `needs_review`와 `superseded`는 명시적으로 조회한다.
- run/cycle/agent/ontology/fidelity/status의 목록은 해당 필드 내 OR이며 필드끼리는 AND다.
- tags와 applicability는 지정한 조건을 모두 만족해야 한다.
- 빈 목록은 일치 없음이다. 알 수 없는 필드는 오류로 반환한다.
- 후보에는 짧은 발췌만 들어간다. 전체 본문은 `/markdown/read`에 같은 scope와 record_id를 보낸다.
- LLM은 호출자가 정한 범위를 좁힐 수만 있다. 분류가 비슷하다고 조건을 교체하지 않는다.

## 기록의 상태 변경

POST `/api/knowledge/markdown/<record_id>/status`에 `status`, `reason`을 전달한다.
대체 시에는 `superseded_by`도 지정한다. 대체 기록은 존재하는 유효 기록이어야 하고
온톨로지 타입과 적용 조건이 동일해야 한다. 이전 리비전은 삭제하지 않는다.

생산자 재시도는 운영자가 지정한 검토 보류·대체 상태를 풀지 않는다. 최신 파일이
손상되면 과거의 유효 상태로 되돌아가지 않고 해당 기록을 검색에서 격리한다.
파일을 직접 수정하기보다 API로 상태를 갱신하고 원본 리비전을 보존한다.

## 루프 기록 및 과거 데이터 후처리

완료·실패·취소 시 기존 manifest/result 저장이 끝난 뒤 하나의 관측 MD를 기록한다.
취소는 operator/runtime cancellation으로 구별하며 장비 고장의 증거로 바꾸지 않는다.
동일 실행의 재처리는 중복되지 않지만 다른 루프·시도는 별개의 관측으로 보존한다.

기존 아카이브를 가져오려면 POST `/api/knowledge/markdown/intake`를 사용한다.
`run_id`(선택), `limit`(1–500), `cursor`(이전 응답의 next_cursor)를 전달한다.
반환된 job_id를 GET `/api/knowledge/markdown/intake/<job_id>`로 조회한다.
`has_more`가 참이면 다음 cursor로 새 작업을 요청한다. 파일별 실패를 확인하고
원본 상태를 검토한 뒤 재시도한다. 장비 재실행이나 LLM 호출은 하지 않는다.

작업 상태는 파일에 남지만 웹 프로세스가 중단된 작업을 자동 재시작하지 않는다.
그 경우 같은 범위로 다시 요청할 수 있다. MD 인덱스는 파일로부터 재구성되며,
GUI 시작 시 모든 과거 로그를 스캔하거나 모델을 기동하는 작업은 없다.

## 검증 경계

실제 API/로컬 모델 검증은 합성 근거로 수행한다. 두 사이클 통합 검증도 장비와
FEM 실행 경계를 fixture로 대체한다. 결과와 재현 경로는
[Knowledge Agent Reference](../agents/knowledge_agent.md#artifacts-and-verification)에 기록한다.
이는 새로운 물리 실증이나 검색 품질의 비교 평가를 의미하지 않는다.
