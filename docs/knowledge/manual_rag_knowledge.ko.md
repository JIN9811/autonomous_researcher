<!-- atr-doc
doc_type: guide
subtype: operations_runbook
status: active
authority: procedural
audience: [operator, developer, maintainer]
scope: [knowledge_agent, source_library, source_curation, scoped_rag]
summary: 폴더 기반 원본 수집, 페이지별 처리, 통합 Markdown 생성과 범위 지정 에이전트 검색을 운영하는 절차.
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

검증 범위: `dd0d772` 기준 문서 전체 검토와 소스 정적 분석.
과거 제공자·테스트 결과의 검증 범위는 유지한다. 이번 검토에서는
모델 호출, Knowledge 저장소 변경, 장비 작동을 수행하지 않았다.

# Source Library Operations

## Status at a Glance

| 한눈에 보기 | 내용 |
|---|---|
| 목적 | 제출한 원본을 출처가 명시된 Markdown으로 정리하고 지정 범위에서 검색 |
| 작업 화면 | Knowledge → Source Library |
| 준비 사항 | Knowledge 모델 설정, 원본 수집 폴더, 명시적인 수집 활성화 |
| 기록 기준 | 2026-09-11 · [문제 해결과 검증](#troubleshooting-and-verification) |

기존 링크와의 호환성을 위해 문서 URL을 유지한다. Source Library는 이전의
매뉴얼 전용 런타임을 대체하며, 기존 `/api/knowledge/manuals/*` 엔드포인트는
HTTP 410을 반환한다. 원본 파일, 과거 산출물(artifact)과 온톨로지 정의는 보존한다.

## Intake and Publication

1. `/knowledge#manuals`에서 **Knowledge Workspace → Source Library**를 연다.
2. 원본 자료를 `docs/knowledge/manuals/sources/`에 넣는다. 생성된 결과물은
   이 수집 폴더 밖에 보관한다.
3. **Automatically curate stable source changes**를 활성화한다. 이 설정은 저장된다.
   **Scan Sources**는 모델 추론이 끝나기를 기다리지 않고 원본을 탐색한다.
4. 원본별 진행 상태를 확인한다. 새 내용이나 변경된 내용이 안정화되면,
   등록된 Knowledge 모델이 기존 추론 사용권을 확보했을 때 처리한다.
5. 준비가 완료된 문서를 검색한 뒤 상세 내용과 원본에서 추출한 Markdown을 연다.

작업자는 내용 기반 주소로 식별한 원본과 추출한 전체 텍스트를 보존한다.
페이지가 있는 원본은 페이지별 파일로 나누어 읽는다. 제한된 범위에서 내용을 통합해
**원본 하나당 정리된 Markdown 결과물 하나**를 만들며, 수치·조건과 페이지/블록
출처를 유지한다. 중간 단계의 페이지별 분석 결과는 별도 검색 결과로 노출하지 않는다.
텍스트 추출은 LLM 요약과 다르다.

- 작업자는 모델 서버를 시작하지 않는다.
- 수집을 비활성화하면 새 원본 처리는 시작하지 않는다. 이미 처리 중인 원본은 완료될 수 있다.
- 워크플로 요청은 진행 중인 호출을 중단하지 않고 다음 추론 사용권 할당 시점에 우선권을 갖는다.

## Storage and Identity

| 위치 | 용도 |
|---|---|
| `docs/knowledge/manuals/sources/` | 기존 수집 폴더와 운영자 소유 원본 |
| `memory/knowledge/source_library/settings.json` | 저장된 자동 수집 설정 |
| `memory/knowledge/source_library/sources/<source-id>/` | 보존된 원본, 추출 결과, 페이지 파일과 게시 이력 |
| `.../extractions/<extraction-id>/source.md` | 원본에서 추출한 전체 텍스트 |
| `.../extractions/<extraction-id>/pages/page-0001.md` | 개별 원본 페이지; 페이지 매니페스트가 파일과 블록을 연결 |
| `.../publications/<publication-id>/notes/<category>/<record-id>.md` | 정리된 단일 Markdown 결과물 |
| `.../publications/<publication-id>/` | 게시 메타데이터, 출처와 모델/도구 추적 기록 |

여기서 `...`는 운영자의 수집 폴더가 아니라 해당 `sources/<source-id>` 디렉터리를
뜻한다. 분류에 따라 파생 결과물의 위치는 달라지지만 원본 경로는 바뀌지 않는다.

- 내용이 같으면 식별자를 공유하고 각 경로를 별칭으로 연결한다. 내용이 바뀌면 새 식별자를 부여하고 이전 게시 결과는 감사용으로 유지한다.
- 기본 검색에는 현재 유효하고 준비가 완료된 원본만 포함한다.
- 수집 폴더에서 파일을 제거하면 해당 경로의 이전 버전은 검색에서 제외한다. 과거 산출물은 삭제하지 않는다.
- 생성된 지식은 로컬에 남으며 Git에 자동으로 공개되지 않는다.

## Retrieval and Agent Use

| 인터페이스 | 요청 / 결과 |
|---|---|
| GET `/api/knowledge/sources/status` | 작업자 상태, 집계와 원본별 진행 상황 |
| POST `/api/knowledge/sources/settings` | `{enabled: true/false}` |
| POST `/api/knowledge/sources/scan` | 안정화된 변경 사항을 탐색하고 처리 예약 |
| POST `/api/knowledge/sources/retry` | 현재 미완료 작업의 `{source_id}` |
| POST `/api/knowledge/sources/query` | `{query, scope, top_k}` → 메타데이터와 발췌문 |
| POST `/api/knowledge/sources/read` | `{record_id, scope}` → 노트 전체와 원본 출처 |

범위는 원본 식별자, 분류, 온톨로지 타입, 태그와 정확히 일치하는 적용 조건으로
제한할 수 있다. 알 수 없는 필터는 오류로 처리하며, 상세 조회에도 검색과 같은
범위를 적용한다. 원본 범위는 실행 메모리의 run/cycle 식별자와 별개다.

에이전트는 읽기 전용 `knowledge.sources.search`와 `knowledge.sources.read`를
공유한다. Knowledge는 기존 BO 인계 경로로 선택한 기록과 출처를 전달한다.
Equipment는 기존 의사결정 지점에서 길이가 제한된 참고 발췌문과
잘림 여부를 명시한 메타데이터를 받으며, 전체 내용도 조회할 수 있다. 원본 내용은
수치 관측값, 제안, 명령이나 승인 권한의 소유 주체를 바꾸지 않는다.

## Troubleshooting and Verification

| 상태 | 조치 |
|---|---|
| Disabled | 백그라운드 처리가 필요하면 자동 수집 활성화 |
| Waiting for model/workflow | 기존 모델 선택을 확인하거나 진행 중인 워크플로가 끝날 때까지 대기 |
| Failed / needs review | 오류를 확인하고 입력이나 설정을 수정한 뒤 재시도 |
| No matching knowledge | 현재 게시 상태와 정확한 범위 확인; 조건을 임의로 넓히지 않음 |
| Missing source | 검색 대상에 유지해야 하는 입력이라면 해당 원본 복원 |

읽을 수 없거나 지원하지 않는 내용은 지어내지 않는다. 정리 작업이 실패하거나
중단되면 부분 결과를 준비 완료 상태로 노출하지 않는다. 재시도하더라도 변경되지 않은
성공한 게시 작업을 반복하지 않는다.

명시적으로 실행하는 [`verify_source_curation.py`](../../scripts/verify_source_curation.py)
검증 도구는 격리된 원본, 페이지 파일, Markdown과 인덱스를 사용한다. 기본적으로는
성공 여부와 관계없이 임시 작업 공간을 정리한다. 검증 근거를 별도로 보존하려면
외부 디렉터리를 지정한다.

```sh
.venv/bin/python scripts/verify_source_curation.py --execute \
  --artifacts-dir /absolute/external/validation/source_curation \
  --output /absolute/external/validation/source_curation/report.json
```

이 경우 각 실행은 임시 작업 공간을 정리하기 전에 고유한 실행 디렉터리에 입력,
원본 스냅샷, 추출한 페이지, 중간 분석 결과, 정리된 Markdown, 인덱스, 모델 응답과
소비자 결정을 보관한다. 성공하면 해당 아카이브에 `verification-report.json`도
기록한다. 실패한 경우에도 부분 작업 공간을 보관하여 검토할 수 있다. 기록 안의
원본 경로는 임시 실행 루트를 가리키므로, 아카이브 실행 디렉터리 아래에서 같은
상대 경로를 찾아야 한다. 저장소 내부 경로는 아카이브 목적지로 사용할 수 없다.
이 아카이브는 검증 전용이며 운영 RAG 입력이나 Git 산출물이 아니다. 문서에는
측정된 요약 결과만 공개한다. 2026-09-11 제공자 검증 행렬은 집계 보고서를 보존했지만,
외부 보존을 요청하기 전에 중간 작업 공간이 이미 정리된 상태였다. 측정된 제공자별
결과와 회귀 테스트 결과는
[Knowledge Agent 검증 항목](../agents/knowledge_agent.md#artifacts-and-verification)을
참고한다. 이 검증은 장비를 작동하지 않는다.
