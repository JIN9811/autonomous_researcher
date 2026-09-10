---
doc_type: design
subtype: architecture
status: active
authority: proposal
decision_status: approved
audience: [developer, researcher, maintainer]
scope: [knowledge, agents, ontology, rag]
summary: Approved Knowledge-only restructuring from graph projections to ontology-guided Markdown memory and scoped retrieval.
last_verified: 2026-09-10
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/superpowers/plans/2026-09-10-knowledge-markdown-memory.md
supersedes: []
---

# Knowledge Agent — 온톨로지 기반 MD 지식 및 범위 지정 RAG

## 승인 범위

2026-09-10 사용자는 Neo4j를 포함한 **지식 그래프 기능만 제외**하고 온톨로지,
원본 로그·아티팩트, 실험 메모리, 성공/실패 패턴, 매뉴얼 RAG, Evolution 근거,
기존 에이전트 인계와 폐루프 실행 경로를 보존하도록 승인했다. 로그의 지식을
MD로 축적·분류하고 RAG 범위를 지정한다. 중복 방지·증분 처리, 지식 유효 상태,
실패/취소 기록 수집, 필터→검색→상세 조회, 현재 루프와 대량 정리 분리도 승인했다.
이 문서는 그 승인 내용의 구현 계약이며 장비 실행·커밋·태그·푸시 승인이 아니다.

## 보존과 제거

- 실행 그래프, 장비 브릿지, BO 수치/목적값/좌표, Analysis 결과는 변경하지 않는다.
- ATR 운영 경로에서 Neo4j 연결, 지식 그래프 투영/동기화/관계 보정 및 그 UI를 제거한다.
- 그래프 전용 API는 명시적인 retired 응답으로 전환한다. 다른 Knowledge API는 유지한다.
- 기존 그래프 파일·DB·설치된 서버를 삭제하지 않는다. 과거 그래프 유틸리티는 비활성
  호환 코드로 남을 수 있지만 앱/폐루프에서 실행되면 안 된다. 새 그래프 DB는 도입하지 않는다.
- 온톨로지 YAML의 개념·관계 의미·버전 정의는 보존한다. MD 분류 검증에 기존 개념을 쓴다.
- 매뉴얼 corpus, page/chunk 인용과 장비 Agent의 manual_context.v1은 보존하며 그래프
  생성/존재 여부를 검색의 준비 조건으로 사용하지 않는다.
- MD는 재사용 지식의 본문이다. 측정 CSV, 기존 JSON/JSONL, 원본 로그를 대체하지 않는다.

## 5영역 책임

| 영역 | 계약 |
|---|---|
| High | 현재 지식 요청의 목적·대상·허용 범위를 해석한다. 전체 실행 위임은 ORC 소유다. |
| Middle | 정상 경로의 LLM이 근거 조회·추출·분류·저장·전달을 선택한다. |
| Low | 기존 파일·검색·스키마·인덱스 코드가 검증된 요청을 실행한다. |
| Guardian/Safety | 출처 정체성, 온톨로지, 검색 범위, 사실/해석 구분을 검증한다. |
| Knowledge/Evidence | 원본 참조, MD 본문, 적용 조건, 유효 상태 및 개정 이력을 보존한다. |

## MD 계약

기존 memory/knowledge 아래 `markdown/`에 런/루프/에이전트별 작은 MD 기록을 둔다.
frontmatter는 schema, record_id, revision, run_id, cycle_id, agent_id, event_id,
ontology_type, title, tags, applicability, source_refs, evidence_kind, fidelity,
status, content_hash, ontology_version을 가진다. 본문은 관측·조치·결과·재사용 지식·한계를
담는다. observed/derived/hypothesis와 measured/simulated/virtual/unknown을 구분한다.
valid는 현재 검색 대상이라는 뜻이지 LLM 해석의 과학적 검증을 뜻하지 않는다.

동일 이벤트의 동일 입력은 unchanged, 변경 입력은 개정으로 보관한다. 다른 루프의 같은
실패는 독립 증거다. 모델의 재표현만으로 무한 중복을 만들지 않는다. valid/needs_review/
superseded 상태를 지원한다. 대체 기록은 출처와 조건이 확인되어야 하며 최신이라는 이유만으로
다른 조건의 기록을 무효화하지 않는다. 원본과 이전 개정은 덮어쓰지 않는다.

## 검색과 판단

`MarkdownKnowledgeStore(root, ontology)`는 write_note, search, read_note, status를 제공한다.
검색은 온톨로지 유형·에이전트·런/루프·fidelity·적용 조건을 먼저 필터링하고 상위 후보를
반환한다. 알 수 없는 필터나 명시적으로 빈 범위는 전체 검색으로 바뀌면 안 된다.
상위 요청 범위와 모델 요청의 교집합만 허용한다. MD 수정/추가분만 인덱스를 갱신한다.
인덱스는 재생성 가능하며 임의 파일 경로 읽기와 암묵적인 웹 범위 확장은 허용하지 않는다.

Knowledge의 agent-local tools는 `inspect_evidence`, `search_knowledge`, `read_knowledge`,
`write_knowledge_note`, `publish_context`이다. 모델은 strict JSON 요청을 만들고 실제 툴
결과를 다시 관측한다. 현재 원본 근거는 모델 판단과 무관하게 보존한다. 모델 실패 시
LLM 성공으로 위장하지 않고 명시적인 판단 실패를 반환하며 재처리할 근거를 보존한다.
명시적인 offline test만 같은 dispatcher의 결정론적 경로를 사용할 수 있다.

기존 knowledge_context.v1/knowledge_report.v1/knowledge/evolution_proposal 필드는 보존한다.
구조화된 선택 지식과 citation, scope, decision trace만 추가한다. BO 등 기존 소비자는
동일 인계 경로로 지식 본문·출처를 받으며 Knowledge가 측정 데이터 채택권을 갖지 않는다.

## 실패 수집과 실행 시간

기존 agent artifact archive의 종료 시점에 성공/실패/취소 결과를 작은 MD 관측 기록으로
보존한다. 예외·취소를 다시 실행하거나 운영자 취소를 장비 실패로 바꾸지 않는다.
Knowledge 단계까지 도달하지 못한 런도 기록된다. 이 경로는 LLM을 호출하지 않는다.
현재 루프 LLM 판단은 기존 Knowledge stage에서 수행한다. 과거 archive 정리/재색인은
명시적인 후처리 API로 별도 수행하며 GUI 시작 때 전체 로그를 스캔하지 않는다.

## UI·문서·검증

Knowledge workspace는 MD 검색/상세/범위, 기존 메모리·온톨로지·매뉴얼 화면을 제공한다.
그래프/Neo4j 상태/Graphify/관계 편집 화면과 polling은 제거한다. 모든 새 UI 문구는 영어다.
Reference는 기존 Design 문서 스타일의 Status at a Glance, 5영역 표, 3개 source-backed
SVG, API·아티팩트·검증 구분을 포함한다. 기존 그래프 운영 문서는 폐기 상태와 대체 문서를 안내한다.

검증은 임시 저장소에서 MD 재호출/개정/분리/필터/출처 검증, 실제 archive의 실패·취소,
매뉴얼 인용 보존과 Neo4j 비호출, Knowledge API와 UI, 비구동 폐루프 회귀,
등록된 API 및 vLLM 로컬 모델의 정상/상충/근거 부족 판단을 포함한다.
장비/solver/모델 서버를 시작하지 않는다. 프롬프트 인젝션 평가는 승인 범위에서 제외한다.
