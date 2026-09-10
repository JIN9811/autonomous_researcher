---
doc_type: guide
subtype: operations_runbook
status: active
authority: procedural
audience: [operator, developer, maintainer]
scope: [knowledge_agent, manual_rag, equipment_agent, utm, pyautogui]
summary: 기존 장비 매뉴얼 corpus와 페이지 인용을 그래프 의존성 없이 수집·조회하고 장비 에이전트에 제공하는 계약.
source_of_truth:
  - knowledge/manuals
  - knowledge/ontology/manual_equipment.v1.yaml
  - docs/knowledge/manuals/registry.yaml
  - agents/equipment_agent.py
  - app/main.py
last_verified: 2026-09-10
verified_against: working-tree-2026-09-10
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/agents/equipment_agent.md
  - docs/knowledge/markdown_memory_operations.ko.md
supersedes: []
---

# Manual RAG Knowledge 운영 가이드

## 목적과 소유권

Knowledge의 매뉴얼 RAG는 원본 PDF → 페이지·섹션 chunk → 검색 → 인용 context를
소유한다. Lab Equipment Agent는 그 근거를 기존 skill 해석·절차 판단·복구에서
사용한다. 지식 그래프를 제거해도 이 경로와 매뉴얼 온톨로지는 유지한다.

현재 등록된 매뉴얼 모듈의 장비 타입 범위는 `equipment_type=utm`이다.
제품·소프트웨어 버전은 출처 및 검색 가중치이며 강제 제외 필터가 아니다.
이는 기존 장비 모듈의 범위이지 전체 플랫폼의 실험 슬롯 제한이 아니다.

## 저장 구조

| 위치 | 역할 |
|---|---|
| `docs/knowledge/manuals/registry.yaml` | 버전 관리되는 source registry |
| `docs/knowledge/manuals/sources/*.pdf` | 원본 매뉴얼 |
| `knowledge/ontology/manual_equipment.v1.yaml` | 보존되는 manual ontology |
| `memory/knowledge/manual_rag/corpus.json` | source/chunk corpus |
| `memory/knowledge/manual_rag/receipts/*.json` | 수집 영수증 |

과거 `manual_graph.json`, `manual_semantic_graph.json` 파일은 삭제하지 않지만
현재 수집·검색·준비 상태의 조건으로 사용하지 않는다. 새 그래프를 생성하거나
Neo4j로 미러링하지 않는다. 생성된 memory는 Git 대상이 아니며 PDF 공개 권한은
별도로 확인해야 한다.

## 수집과 검색 계약

registry source의 필수 필드는 `source_id`, `equipment_type`, `title`,
`path`다. `product`, `version`, `language`는 선택 메타데이터다.
기존 수집기는 `pdftotext`로 페이지를 보존하고 섹션 chunk, source SHA-256,
안정적인 chunk ID와 receipt를 만든다.

검색의 제목·섹션·한국어 부분어·목적 용어 및 기존 임베딩 기반 ranking은 보존한다.
웹 검색이나 일반 runtime MD를 매뉴얼 corpus에 섞지 않는다.

| 반환 근거 | 의미 |
|---|---|
| source_id / source_sha256 | 원본 문서 정체성 |
| chunk_id | 검색 근거 chunk |
| page / citation | 원문 페이지 인용 |
| purpose / equipment_type | 기존 검색 조건 |
| insufficient_evidence | 실제 corpus 검색의 근거 부족 여부 |

레거시 응답의 graph 필드는 호환성을 위해 빈 값과 `retired` 상태를 반환한다.
그래프가 없다는 사실은 corpus 근거 부족을 의미하지 않으며, 검색의
`insufficient_evidence`와 구별한다.

## 장비 에이전트 연결

| 목적 | 기존 호출점 | 허용 결과 |
|---|---|---|
| `skill_authoring` | 녹화 Skill annotation | 단계·locator·checkpoint 설명 및 인용 |
| `decision` / `procedure` | 장비 tool plan과 protocol formatting | 등록 프로그램·절차 선택 근거 |
| `recovery` | 예외 packet의 모델 판단 | 허용된 복구 operation 선택 근거 |

Manual context는 action, 좌표, program ID, credential, 장비 payload,
Guardian/operator gate를 직접 수정하지 않는다. Skill compile/validate/deploy,
bridge와 interlock은 기존 경로 그대로다.

## API와 Workspace

| Method / path | 기능 |
|---|---|
| GET `/api/knowledge/manuals/status` | corpus 준비 상태와 source/chunk 수 |
| POST `/api/knowledge/manuals/ingest` | 등록 PDF 수집 |
| POST `/api/knowledge/manuals/query` | 목적별 검색 및 페이지 인용 |
| GET/POST `/api/knowledge/manuals/graph` | 종료된 그래프 경로, HTTP 410 |

query 예시:

```json
{"equipment_type":"utm","purpose":"recovery","query":"통신 연결 실패 복구 절차","top_k":6}
```

`/knowledge#manuals`에서 corpus 상태, 수집 버튼, 목적별 검색과 페이지 인용을
확인한다. 과거 Semantic Inspector와 graph view는 활성 화면에서 제거한다.

## 운영 및 검증

1. PDF와 registry 항목을 등록한 뒤 Ingest Manuals를 실행한다.
2. source hash, chunk 수와 수집 receipt를 확인한다.
3. procedure/recovery/safety 질의로 관련 원문 페이지가 검색되는지 확인한다.
4. 장비 에이전트의 annotation·비구동 검증에서 인용을 확인한다.
5. 실제 구동은 기존 장비 승인·안전 절차를 따른다.

PDF 변환 실패는 경로·권한·변환기를 점검하고, hash 변경은 문서 변경 의도를
검토한다. 검색 근거 부족은 적절한 원문이나 질의로 해결하며 장비 payload를
임의 수정하지 않는다.

현재 회귀 테스트는 그래프 파일 없이도 기존 chunk와 페이지 인용이 유지되는지,
ingest가 기존 graph 파일을 덮어쓰지 않는지 확인한다. 광범위한 검색 품질
벤치마크나 실제 장비 동작을 새로 검증했다고 주장하지 않는다.
