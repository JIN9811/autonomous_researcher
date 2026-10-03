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
  - agents/core/knowledge/decision.py
last_verified: 2026-09-29
verified_against: dd0d772
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/knowledge/manual_rag_knowledge.ko.md
supersedes: [docs/oldversion/knowledge/knowledge_graph_operations.ko.md]
-->

<a id="markdown-knowledge-운영-가이드"></a>

# 실행 Markdown 지식 검색과 관리

[English](markdown_memory_operations.en.md)

실험에서 남긴 관측이나 재사용 가능한 지식을 찾을 때는 Knowledge의 Markdown 검색을
사용합니다. 여기서 읽는 해석은 새 측정값이 아닙니다. 수치의 근거는 원래 Analysis
기록에서 확인해야 합니다. 외부 매뉴얼·논문은 [Source Library](manual_rag_knowledge.ko.md),
확인된 개인 선호나 맥락은 [개인 기억](wiki_memory.md#private-memory-lifecycle)에서 관리합니다.

먼저 조회하려는 실행(run), 사이클(cycle), 에이전트와 적용 조건을 정하세요. 검색 범위는
원하는 답을 만들기 위한 힌트가 아니라 어떤 근거를 사용할 수 있는지 정하는 조건입니다.

## 관측을 찾고 출처까지 확인하기

1. `/knowledge#memory`의 **Memory**에서 **Execution knowledge · source-backed
   Markdown**을 펼칩니다. 이 실행 기록 검색은 위쪽 개인 기억 검색 및 Ontology와
   별개입니다.
2. **Run**, **Cycle**, **Agent**, **Validity**와 필요한 **Applicability (exact JSON
   object)** 조건을 정하고 검색어를 입력한 뒤 **Search Knowledge**를 누릅니다.
   예를 들어 특정 프로토콜의 내보내기 검증 문제라면 해당 프로토콜 조건과
   Equipment/Knowledge 에이전트 범위를 함께 지정합니다.
3. 후보의 짧은 발췌를 읽은 뒤 같은 범위로 상세 기록을 엽니다. 기록 식별자와 출처,
   실행·사이클·시도 정보를 원본과 대조합니다.
4. 기본 검색에 없는 검토 보류·대체 기록이 필요한 경우에는 그 상태를 명시해 조회합니다.
   결과가 없으면 범위와 원본을 확인하고, 다른 조건의 기록을 같은 근거로 취급하지 않습니다.

상세 기록과 원본이 연결되고 적용 조건이 일치해야 이 조회를 마친 것입니다. Markdown
문장이 그럴듯하다는 이유만으로 측정의 품질이나 장비 동작의 성공을 판정하지 않습니다.

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

위 조건은 예시이며, 실제 기록에 해당 메타데이터가 있어야 검색됩니다. 조건을 맞추려고
없는 값을 추정하거나 브릿지 설정을 바꾸지 않습니다.

- 기본값은 `valid` 기록입니다. `needs_review`와 `superseded`는 명시적으로 조회합니다.
- run/cycle/agent/ontology/fidelity/status 목록은 각 필드 안에서는 OR, 필드 사이에서는 AND입니다.
- tags와 applicability는 지정한 조건을 모두 만족해야 합니다.
- 빈 목록은 일치 없음이며, 알 수 없는 필드는 오류입니다.
- 후보에는 짧은 발췌만 들어갑니다. 전체 본문은 `/markdown/read`에 같은 scope와 record_id를 보냅니다.
- LLM은 호출자가 정한 범위를 좁힐 수만 있습니다. 분류가 비슷하다고 조건을 바꾸지 않습니다.

## 기록의 상태 변경

출처와 적용 조건을 검토한 뒤 POST `/api/knowledge/markdown/<record_id>/status`에
`status`와 `reason`을 전달합니다. 대체할 때는 `superseded_by`도 지정합니다.
대체 기록은 존재하는 유효 기록이어야 하며 온톨로지 타입과 적용 조건이 같아야 합니다.
변경 후 상세 기록에서 상태와 사유를 확인하세요. 이전 리비전은 삭제하지 않습니다.

생산자의 재시도는 운영자가 지정한 검토 보류·대체 상태를 해제하지 않습니다. 최신 파일이
손상되면 과거의 유효 상태로 되돌리는 대신 해당 기록을 검색에서 격리합니다.
파일을 직접 고치지 말고 API로 상태를 갱신하여 원본 리비전을 보존하세요.

## 루프 기록 및 과거 데이터 후처리

완료·실패·취소 시 기존 manifest/result 저장이 끝난 뒤 관측 Markdown 한 건을 기록합니다.
취소는 operator/runtime cancellation으로 구분하며 장비 고장의 근거로 바꾸지 않습니다.
같은 실행을 다시 처리해도 중복 기록하지 않지만, 다른 루프·시도는 별도 관측으로 보존합니다.

과거 아카이브를 가져오는 작업은 명시적으로 요청해야 합니다.

1. POST `/api/knowledge/markdown/intake`에 선택적인 `run_id`,
   `limit`(1–500), 이전 응답의 `next_cursor`에 해당하는 `cursor`를 전달합니다.
2. 반환된 `job_id`를 GET `/api/knowledge/markdown/intake/<job_id>`로 조회합니다.
3. 파일별 실패를 확인하고 원본 상태를 검토합니다. `has_more`가 참이면 다음 cursor로
   새 작업을 요청합니다. 실패한 입력을 바로잡은 뒤 필요한 범위만 재시도합니다.

이 후처리는 장비 재실행이나 LLM 호출을 하지 않습니다. 작업 상태는 파일에 남지만,
웹 프로세스 중단으로 멈춘 작업을 자동 재시작하지는 않습니다. 같은 범위로 다시 요청할 수
있습니다. Markdown 색인은 파일에서 재구성되며, GUI 시작만으로 모든 과거 로그를
스캔하거나 모델을 기동하지 않습니다.

## 저장과 확인

| 위치 | 내용 |
|---|---|
| `memory/knowledge/markdown/<run>/<cycle>/<agent>/<record>/revision-*.md` | 원본 출처와 분류를 포함한 불변 Markdown 리비전 |
| `memory/knowledge/*.jsonl` | 실험 기억·패턴·성능 기록과 보존된 과거 Evolution 기록 |
| `runs/<run>/knowledge/` | 현재 Knowledge 보고서, LLM 결정·도구 응답, 사전 입력 스냅샷 |
| `runs/<run>/runtime/loops/` | 루프·에이전트·시도별 원본 아카이브 |
| `memory/knowledge/markdown_jobs/` | 명시적으로 시작한 과거 아카이브 후처리 상태 |

## 무엇이 바뀌었는가

지식 그래프와 Neo4j 운영 의존성은 제거했지만, 온톨로지 정의·원본 아티팩트·기존 JSONL
기억·패턴·성능 기록은 보존합니다. Evolution은 새 기록을 생성하지 않고 과거 기록만
유지합니다. 매뉴얼 전용 검색은 Source Library로 대체됐으며 기존
`/api/knowledge/manuals/*` 경로는 HTTP 410을 반환합니다. 실행 순서를 표현하는
폐루프 그래프는 지식 그래프가 아니며 이 변경의 대상이 아닙니다.

Knowledge의 LLM은 근거를 읽고 재사용 가치와 분류를 판단하여 범위 내 검색·상세 조회·기록
도구를 호출합니다. 저장과 조건 검증은 코드가 담당합니다. 단순 기록을 위해 에이전트가
끝날 때마다 LLM을 호출하지 않습니다.

## 검증 경계

기록된 API·로컬 모델 검증은 합성 근거로 수행했습니다. 당시 두 사이클 통합 검증은
장비와 당시 존재하던 FEM 실행 경계를 fixture로 대체했습니다. 현재 Analysis는
측정 데이터 후처리만 담당하며 FEM 실행 경로가 아닙니다. 결과와 재현 경로는
[Knowledge Agent 검증 기록](../agents/knowledge_agent.md#artifacts-and-verification)에
있습니다. 이는 새 물리 실증이나 검색 품질의 비교 평가가 아닙니다.

기존 전체 문서·소스 정적 검토는 2026-09-29의 `dd0d772` 기준입니다.
이번 문서 정리는 모델 호출, Knowledge 저장소 변경 또는 장비 작동을 포함하지 않습니다.
