---
doc_type: guide
subtype: operations_runbook
status: active
authority: procedural
audience: [operator, developer, maintainer]
scope: [knowledge_agent, manual_rag, equipment_agent, utm, pyautogui]
summary: UTM 장비 매뉴얼을 Knowledge Agent의 분리된 Manual RAG Knowledge 모듈로 수집하고 Lab Equipment Agent가 근거 기반으로 사용하는 계약과 운영 절차.
source_of_truth:
  - knowledge/manuals
  - knowledge/ontology/manual_equipment.v1.yaml
  - docs/knowledge/manuals/registry.yaml
  - agents/equipment_agent.py
  - app/main.py
  - web/templates/knowledge.html
last_verified: 2026-08-17
verified_against: working-tree-2026-08-17
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/agents/equipment_agent.md
  - docs/knowledge/knowledge_graph_operations.ko.md
supersedes: []
---

# UTM Manual RAG Knowledge 운영 가이드

## 목적과 계층

이 모듈은 다음 계층으로 동작합니다.

```text
Knowledge Agent
└─ Manual RAG Knowledge
   ├─ source registry / PDF ingest
   ├─ page + section chunks
   ├─ evidence graph (document/section/chunk provenance)
   ├─ semantic graph (procedure/fault/cause/remedy assertions)
   └─ bounded query projection + page citations
        ↓ context only
Lab Equipment Agent
└─ UTM profile LLM
   ├─ PyAutoGUI Skill annotation/authoring
   ├─ procedure and decision guidance
   └─ bounded exception recovery suggestion
        ↓ existing validation unchanged
Skill registry / Windows bridge / Guardian / operator gate
```

고정 범위는 `equipment_type=utm`뿐입니다. `QM100T`, `Qm_Tester`, `17.7.0`
같은 제품·버전은 출처와 검색 가중치 메타데이터이며 필수 필터가 아닙니다.
따라서 같은 UTM 계층에 새 장비 또는 새 소프트웨어 매뉴얼을 등록해도 별도 실행
계층을 만들 필요가 없습니다.

## 저장 구조

```text
docs/knowledge/manuals/registry.yaml          버전 관리되는 source registry
docs/knowledge/manuals/sources/*.pdf          원본 매뉴얼
knowledge/ontology/manual_equipment.v1.yaml   Core와 분리된 manual ontology
memory/knowledge/manual_rag/corpus.json       수집된 source/chunk corpus
memory/knowledge/manual_rag/manual_graph.json evidence graph projection
memory/knowledge/manual_rag/manual_semantic_graph.json cited semantic projection
memory/knowledge/manual_rag/receipts/*.json   수집·semantic rebuild 영수증
```

`memory/` 산출물은 재생성 가능하며 Git 대상이 아닙니다. 원본 PDF의 배포 권한은
저장소 공개 범위와 별도로 확인해야 합니다.

## 수집 계약

`registry.yaml`의 각 source는 `source_id`, `equipment_type`, `title`, `path`를
가집니다. `product`, `version`, `language`은 선택 메타데이터입니다. 수집기는
`pdftotext`로 페이지를 보존해 텍스트를 읽고, 제목 계층별로 chunk를 만들며,
source SHA-256와 안정적인 chunk ID를 기록합니다. UTM이 아닌 source는 거부합니다.

현재 실제 수집 검증값은 다음과 같습니다.

| 항목 | 값 |
|---|---:|
| source | 2 |
| page | 50 + 66 |
| chunk | 506 |
| evidence graph node | 1,481 |
| evidence graph edge | 2,289 |
| semantic graph node | 565 |
| semantic graph edge | 872 |
| semantic provenance coverage | 1.0 |
| isolated semantic node rate | 0.019469 |
| fault chain completion | 1.0 |
| procedure chain completion | 1.0 |

## 온톨로지와 GraphRAG

Manual graph는 용도가 다른 세 계층을 분리합니다.

| 계층 | 내용 | 기본 표시 |
|---|---|---|
| Evidence | `ManualDocument`, `ManualSection`, `ManualChunk`와 원문 위치 | API의 `view=evidence`에서만 표시 |
| Semantic | `Procedure`, `ProcedureStep`, `Fault`, `Cause`, `Remedy`, `Warning`, `Interlock`, `Parameter`, `CommunicationInterface` | Workspace와 graph API의 기본 view |
| Query projection | 검색된 chunk를 seed로 만든 최대 2-hop 의미 subgraph | 질의 결과와 함께 표시 |

Semantic assertion은 `HAS_STEP`, `PRECEDES`, `HAS_CAUSE`, `RESOLVED_BY`,
`REQUIRES`, `PROHIBITS` 등의 typed relation으로 연결됩니다. 각 semantic node와
edge는 하나 이상의 `chunk_id`와 양의 page citation을 가져야 하며,
`SUPPORTED_BY`가 semantic assertion과 Evidence chunk를 연결합니다. provenance가
없는 assertion은 atomic replace 전에 거부됩니다.

엔티티 병합은 UTM scope와 semantic type 안에서 exact normalized label만
사용합니다. 일반적인 step 이름은 procedure context까지 key에 포함해 서로 다른
절차의 단계가 합쳐지지 않게 합니다. 수집 성공 시 corpus, evidence graph,
semantic graph를 임시 파일에 완성한 뒤 atomic replace하고 rebuild receipt를
남깁니다.

검색은 한국어 부분어, 제목/섹션, 목적별 용어, 안정적 임베딩을 결합합니다.
제품과 버전 힌트는 점수만 소폭 올리고 다른 UTM source를 제외하지 않습니다.
웹 검색과 일반 runtime memory는 이 context에 섞지 않습니다.

## UTM Profile LLM 사용 경계

Manual context가 주입되는 지점은 다음 세 곳입니다.

| 목적 | 호출점 | 허용 결과 |
|---|---|---|
| `skill_authoring` | 녹화된 Skill annotation | 단계 라벨, locator 설명, checkpoint 설명, 인용 |
| `decision` / `procedure` | UTM tool plan 및 protocol formatting | 등록 프로그램 선택·절차 설명의 근거 |
| `recovery` | 실행 예외의 선택 모델 복구 판단 | 예외 packet에 허용된 단일 복구 operation 선택 근거 |

Manual context는 실행 action, 좌표, program ID, credential, 장비 payload,
Guardian/operator gate를 생성하거나 변경할 권한이 없습니다. 실제 실행은 기존
Skill compile/validate/deploy/enabled 계약, allowlisted bridge, Guardian 및 operator
검증을 그대로 통과해야 합니다. 근거가 부족하면 `insufficient_evidence=true`로
남고 모델은 부족함을 명시해야 합니다.

## API와 Workspace

```bash
curl -s http://127.0.0.1:7860/api/knowledge/manuals/status
curl -s -X POST http://127.0.0.1:7860/api/knowledge/manuals/ingest
curl -s -X POST http://127.0.0.1:7860/api/knowledge/manuals/query \
  -H 'Content-Type: application/json' \
  -d '{"equipment_type":"utm","purpose":"recovery","query":"통신 연결 실패 복구 절차","top_k":6}'
curl -s 'http://127.0.0.1:7860/api/knowledge/manuals/graph?view=semantic&limit=240'
curl -s 'http://127.0.0.1:7860/api/knowledge/manuals/graph?view=evidence&limit=240'
```

`view` 기본값은 `semantic`이며 다른 값은 `422`로 거부됩니다.
`/knowledge#manuals`의 `Manual RAG Knowledge` 탭에서 source/chunk/semantic graph
상태, 수동 재수집, 목적별 검색, 페이지 인용, 제한된 의미 그래프를 확인합니다.
Workspace는 기본적으로 `ManualChunk`와 `SUPPORTED_BY`를 숨깁니다. 의미 node나
relation을 선택하면 Semantic Inspector에서 confidence, extraction method, alias,
page support를 확인하고 `Selected support`로 해당 Evidence chunk만 좁혀 볼 수
있습니다.

## 운영 절차

1. PDF를 `docs/knowledge/manuals/sources/`에 배치합니다.
2. `registry.yaml`에 안정적인 `source_id`와 `equipment_type: utm`을 등록합니다.
3. Workspace의 `Ingest Manuals` 또는 ingest API를 실행합니다.
4. source hash, chunk 수, evidence/semantic graph validation 결과를 확인합니다.
5. provenance coverage, isolated node rate, fault/procedure chain completion을 확인합니다.
6. `procedure`, `recovery`, `safety` 대표 질의로 관련 페이지가 상위에 오는지 확인합니다.
7. UTM Skill annotation 또는 dry-run에서 `manual_context_hash`와 citations를 확인합니다.
8. 물리 실행 전 기존 bridge/Guardian/operator 검증을 별도로 수행합니다.

## 실패와 복구

- PDF 변환 실패: `pdftotext` 설치와 파일 권한을 확인하고 재수집합니다.
- source hash 변경: 변경 의도를 검토한 뒤 새 receipt를 생성합니다.
- semantic provenance 검증 실패: 기존 인덱스를 유지하고 extraction/citation 오류를
  수정한 뒤 전체 atomic rebuild를 다시 실행합니다.
- 검색 근거 부족: query를 구체화하거나 올바른 매뉴얼을 registry에 추가합니다.
- Neo4j 비활성: `manual_graph.json`과 bounded Workspace는 계속 사용 가능하며,
  외부 graph sync만 disabled로 표시됩니다.
- 모델 판단 오류: 실행 payload를 수정하지 말고 citation과 원문 페이지를 검토한 뒤
  Skill annotation 또는 복구 결정을 재검증합니다.

Manual RAG 추가로 변경되지 않는 실행 경계는 Lab Equipment command construction,
Windows/UTM bridge dispatch, credential 저장, Guardian policy, operator gate, safety
interlock입니다. 의미 그래프와 retrieval 결과는 이 경계 앞의 읽기 전용 근거입니다.
