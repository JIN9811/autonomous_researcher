<!-- atr-doc
doc_type: guide
subtype: operations_runbook
status: active
authority: procedural
audience: [operator, developer, maintainer]
scope: [knowledge_agent, source_library, source_curation, scoped_rag]
summary: 원본을 보존하며 참고 자료를 인용 가능한 Markdown으로 정리하고 적용 범위를 지정해 검색하는 절차.
source_of_truth:
  - knowledge/source_library.py
  - knowledge/source_extraction.py
  - knowledge/source_runtime.py
  - knowledge/source_api.py
  - agents/core/knowledge/source_curation.py
  - mcp_tools/source_tools.py
last_verified: 2026-09-29
verified_against: dd0d772
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/knowledge/markdown_memory_operations.ko.md
  - docs/oldversion/superpowers/specs/2026-09-11-source-curation-design.md
supersedes: []
-->

<a id="source-library-operations"></a>

# 참고 자료 등록과 검색: Source Library

[English](manual_rag_knowledge.en.md)

매뉴얼이나 논문을 출처와 함께 찾아보고 에이전트가 참고하게 하려면 Source Library를
사용합니다. 실행에서 얻은 관측은 [실행 Markdown 지식](markdown_memory_operations.ko.md),
플랫폼 설명이나 확인된 개인 맥락은 [Wiki와 개인 기억](wiki_memory.md)에서 다룹니다.
자료를 등록하는 일은 새 실험 관측을 추가하거나 장비 동작을 승인하는 일이 아닙니다.

이 가이드는 원본 한 건을 등록하고, 정리가 끝난 문서와 인용을 확인하는 과정을 설명합니다.
사용할 Knowledge 모델이 설정되어 있어야 하며, 원본을 제출할 권한도 확인해야 합니다.
생성된 지식은 로컬에 남습니다. 외부 공개에는 별도의 [공개 검토](publication.md)가 필요합니다.
Source Library는 모델 서버를 직접 시작하지 않습니다.

<a id="intake-and-publication"></a>
## 자료를 등록하고 정리 결과 확인하기

1. **Knowledge Workspace → Source Library**(`/knowledge#manuals`)를 엽니다.
2. 원본을 `docs/knowledge/manuals/sources/`에 넣습니다. 생성된 결과는 이 입력 폴더에
   넣지 않습니다.
3. **Automatically curate stable source changes**를 켭니다. 이 설정은 저장됩니다.
   **Scan Sources**는 모델 추론이 끝날 때까지 기다리지 않고 변경된 자료를 발견합니다.
4. 자료별 진행 상태를 확인합니다. 변경이 안정된 신규·수정 자료는 등록된 Knowledge
   모델의 기존 추론 사용권을 확보한 뒤 처리됩니다.
5. **Reference query**에 `export validation` 같은 구절을 입력하고 필요한
   **Category**, **Tags**, 정확한 **Applicability** 조건을 지정한 뒤
   **Retrieve Evidence**를 누릅니다. 결과가 의도한 매뉴얼의 문서인지 확인하세요.
   아래 API는 원본 식별자로 범위를 직접 제한하는 방법도 지원합니다.
6. 준비가 끝난 문서의 상세 보기를 열어 원본 식별자, 페이지·블록 인용, 추출된 원문
   Markdown을 확인합니다. 준비 완료는 자료 정리가 끝났다는 뜻이지, 모든 과학적 진술이
   맞거나 현재 장비에 적용된다는 보증이 아닙니다.

처리기는 내용 기반 식별자로 원본과 전체 추출문을 보존합니다. 페이지가 있는 자료는
페이지별 파일로 나누어 읽고, 분량을 제한한 통합 과정을 거쳐 **원본 한 건당 정리된
Markdown 한 건**을 만듭니다. 수치·조건·페이지 및 블록 인용을 보존하며, 중간 페이지
분석은 별도 검색 결과로 노출하지 않습니다. 원문 추출은 LLM 요약이 아닙니다.

자동 처리를 끄면 새 작업을 시작하지 않지만, 이미 처리 중인 자료는 끝까지 진행될 수 있습니다.
실험 워크플로의 요청은 다음 추론 사용권 경계에서 우선하며, 진행 중인 모델 호출을
강제로 중단하지 않습니다.

## 검색할 버전과 적용 범위 확인하기

내용이 같으면 하나의 식별자를 공유하고 경로는 별칭으로 관리합니다. 내용이 바뀌면
새 식별자가 생기며, 이전에 완성된 결과도 감사용으로 남습니다. 기본 검색에는 현재
사용 가능한 준비 완료 자료만 들어갑니다. 입력 폴더에서 원본을 제거하면 해당 경로의
이전 버전은 기본 검색 대상에서 제외되지만 과거 결과를 삭제하지는 않습니다.
분류를 바꾸어도 원본 경로는 그대로이고 파생 문서의 위치만 달라집니다.

검색 결과가 없으면 먼저 처리 상태와 범위를 확인합니다. 답을 얻기 위해 적용 조건을
임의로 풀지 않습니다. 다른 장비나 프로토콜에 관한 그럴듯한 문서는 대체 근거가 아닙니다.

<a id="storage-and-identity"></a>
## 저장 위치와 원본 식별자

| 위치 | 보존하는 내용 |
|---|---|
| `docs/knowledge/manuals/sources/` | 운영자가 관리하는 원본 입력 폴더 |
| `memory/knowledge/source_library/settings.json` | 자동 처리 설정 |
| `memory/knowledge/source_library/sources/<source-id>/` | 보존 원본, 추출문, 페이지 파일, 정리 결과의 이력 |
| `.../extractions/<extraction-id>/source.md` | 추출된 전체 원문 |
| `.../extractions/<extraction-id>/pages/page-0001.md` | 개별 페이지; 페이지 manifest에서 블록과 파일을 연결 |
| `.../publications/<publication-id>/notes/<category>/<record-id>.md` | 해당 원본의 단일 정리 문서 |
| `.../publications/<publication-id>/` | 정리 결과의 메타데이터, 출처, 모델·도구 호출 기록 |

여기서 `...`는 입력 폴더가 아니라 해당 `sources/<source-id>` 디렉터리입니다.

<a id="retrieval-and-agent-use"></a>
## API와 에이전트의 참고 자료 사용

| 요청 | 용도 |
|---|---|
| GET `/api/knowledge/sources/status` | 처리기 상태, 건수, 자료별 진행 상태 |
| POST `/api/knowledge/sources/settings` | `{enabled: true/false}` 설정 |
| POST `/api/knowledge/sources/scan` | 변경이 안정된 자료를 발견하고 처리 예약 |
| POST `/api/knowledge/sources/retry` | `{source_id}`로 현재 미완료 작업 재시도 |
| POST `/api/knowledge/sources/query` | `{query, scope, top_k}`로 메타데이터와 발췌 조회 |
| POST `/api/knowledge/sources/read` | `{record_id, scope}`로 전체 문서와 원본 출처 조회 |

scope는 원본 식별자, 분류, 온톨로지 타입, 태그, 정확한 적용 조건을 제한할 수 있습니다.
알 수 없는 필터는 오류이며, 상세 조회에도 검색과 같은 범위를 사용합니다.
이 범위는 실행 기억의 run/cycle 식별자와는 별개입니다.

에이전트는 읽기 전용 `knowledge.sources.search`와 `knowledge.sources.read`를
공유합니다. Knowledge는 선택한 문서와 인용을 기존 BO 전달 경로로 보냅니다.
Equipment는 기존 의사결정 경계에서 분량이 제한된 발췌를 받으며, 잘림 여부와 전체 문서
조회 가능 여부가 함께 전달됩니다. 자료의 내용은 수치 관측, 제안, 명령 또는 승인
책임을 바꾸지 않습니다.

<a id="troubleshooting-and-verification"></a>
## 처리가 막혔을 때

| 상태 | 확인할 일 |
|---|---|
| Disabled | 자동 처리를 원하는 경우에만 설정을 켭니다. |
| Waiting for model/workflow | 기존 모델 선택을 확인하거나 진행 중인 워크플로가 끝나기를 기다립니다. |
| Failed / needs review | 오류를 읽고 입력·설정을 고친 뒤 재시도합니다. |
| No matching knowledge | 현재 정리 결과의 상태와 정확한 scope를 확인합니다. 조건을 몰래 넓히지 않습니다. |
| Missing source | 계속 검색 대상이어야 하는 자료라면 의도한 원본을 복원합니다. |

읽을 수 없거나 지원하지 않는 내용은 만들어 내지 않습니다. 실패하거나 중단된 정리
결과는 준비 완료 상태로 공개되지 않습니다. 변경되지 않은 성공 결과는 재시도해도
다시 만들지 않습니다.

## 선택적으로 수행하는 제공자 검증

[`verify_source_curation.py`](../../scripts/verify_source_curation.py)는 명시적으로
실행하는 검증 도구이며, 격리된 원본·페이지·Markdown·색인을 사용합니다. 기본적으로
성공과 실패 모두 임시 작업 폴더를 정리합니다. 근거를 따로 보존하려면 저장소 밖의
디렉터리를 지정합니다.

```sh
.venv/bin/python scripts/verify_source_curation.py --execute \
  --artifacts-dir /absolute/external/validation/source_curation \
  --output /absolute/external/validation/source_curation/report.json
```

각 호출은 임시 파일을 정리하기 전에 입력, 원본 사본, 추출 페이지, 중간 분석,
정리 문서, 색인, 모델 응답, 소비 측 결정을 고유 실행 디렉터리에 보관합니다.
성공하면 그 보관본에 `verification-report.json`도 기록합니다. 실패 시에도 부분
작업 내용은 보관본에서 확인할 수 있습니다. 기록 안의 원래 경로는 임시 실행 루트를
가리키므로 보관 디렉터리 아래의 같은 상대 경로로 찾아야 합니다. 저장소 내부를 보관
목적지로 지정하면 거부됩니다.

보관본은 검증 전용이며 운영 검색 입력이나 Git 공개 자료가 아닙니다. 문서에는 검토한
측정 요약만 공개합니다. 2026-09-11 제공자 비교는 집계 보고서를 보존했지만, 중간
작업 폴더는 외부 보관이 요청되기 전에 이미 정리된 상태였습니다. 측정된 제공자·회귀
결과는 [Knowledge Agent 검증 기록](../agents/knowledge_agent.md#artifacts-and-verification)을
참고하세요. 이 검증은 장비를 작동시키지 않습니다.

## 호환성과 기존 검증 범위

Source Library는 과거 매뉴얼 전용 기능을 대체합니다. 기존
`manual_rag_knowledge` 문서 주소는 호환성을 위해 유지하지만
`/api/knowledge/manuals/*` API는 HTTP 410을 반환합니다. 원본, 과거 결과와 온톨로지
정의는 보존됩니다.

기존 전체 문서·소스 정적 검토는 2026-09-29의 `dd0d772` 기준입니다.
이번 구성 정리와 언어 대응 작업은 제공자 검증을 다시 실행하거나 Knowledge 저장소를
수정하거나 장비를 작동시킨 것이 아닙니다.
