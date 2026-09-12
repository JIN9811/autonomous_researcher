---
doc_type: design
subtype: architecture
status: active
authority: proposal
decision_status: approved
audience: [developer, maintainer, researcher]
scope: [knowledge, ax4lab_wiki, scoped_memory, orchestrator_chat, privacy]
summary: AX4LAB Wiki를 공통 RAG 기반으로 제공하고 Knowledge가 비공개 메모리를 관리하며 ORC가 근거 기반 질문 응답과 기존 실험 설정 경로를 연결한다.
related_docs:
  - docs/agents/knowledge_agent.md
  - docs/agents/orchestrator_agent.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/superpowers/specs/2026-09-11-source-curation-design.md
  - docs/superpowers/specs/2026-09-12-orchestrator-dynamic-experimental-setup-design.md
  - docs/runtime/loop_artifact_archiving.md
supersedes: []
---

# AX4LAB Wiki · Knowledge Memory · ORC 대화 통합 설계

## Status at a Glance

| At a glance | Details |
|---|---|
| 설계 상태 | 사용자 승인; 핵심 경로 구현·비구동 검증, 전체 수용 기준은 일부 미완료 |
| 공통 지식 | AX4LAB Wiki를 모든 등록 에이전트의 기본 검색 범위로 제공 |
| 메모리 소유 | Knowledge가 지속 기억의 수명주기·검색을 관리 |
| 대화 진입 | ORC가 시스템 질문·상태 질문·기억 관리·실험 요청을 구분 |
| 보존 | 기존 LangGraph, Setup 승인, 에이전트 소유권, 브릿지, 모드별 실행 경로 |
| 공개 경계 | 검토된 Wiki만 공개; 사용자·대화·실험·검색 흔적은 기본 비공개 |
| 검증 상태 | 영향 범위 Python 162개·기존 경로 71개 통과; API/로컬 응답 검증과 의미적 사용 검증을 구분 |

### 2026-09-13 구현 점검

Wiki·private v2 서비스, 10개 에이전트 판단 경계의 공급/인용 기록, ORC 질문 및
명시적 기억 관리, Workspace·Live 연결, 공개 검사와 관련 문서를 구현했다.
실제 장비 구동·운영 서버 재시작·커밋/푸시는 하지 않았다.

API와 로컬 각각 20건의 에이전트 응답 검사 및 각각 5건의 질문/기억 시나리오가
통과했다. 에이전트 응답의 의미적 사용은 API 모두 Unknown, 로컬 Analysis 1건 Used와
나머지 Unknown이다. 따라서 전 에이전트의 의미적 RAG 활용 완료로 표시하지 않는다.

남은 범위는 기존 v1 실행 기록의 통합 조회 어댑터, 전체 scope/세션 필터·요약 항목,
전 에이전트의 적용 조건 대조 및 의미적 활용 검증, 실제 브라우저 검증이다.
신뢰 가능한 서버 principal을 구성하지 않은 설치는 Wiki-only이며, 테스트 주체를
운영 사용자로 자동 전환하지 않는다. 기존 실행 기록의 소유 범위를 추정해 private v2에
합치는 대신 기존 조회 경로를 보존했다. 현재 기능과 명령 문법은
[Wiki and Memory](../../knowledge/wiki_memory.md)를 따른다.

## 1. 목표와 선택

Knowledge를 외부 자료 변환기만이 아니라 플랫폼 공통 지식·장기 기억의 관리자로
구체화한다. ORC는 실험 설계와 함께 플랫폼 설명·사용 안내·과거 근거 설명을 제공한다.
현재 동작과 다른 내용은 명시적으로 제안으로 표시하며, 코드 변경 없이 자동으로
기능이 생긴 것처럼 설명하지 않는다.

| 접근 | 장점 | 한계 | 선택 |
|---|---|---|---|
| 전체 문서를 각 에이전트 프롬프트에 삽입 | 연결이 단순함 | 문맥 낭비, 오래된 설명·개인정보 혼입 | 제외 |
| 에이전트마다 별도 지식·메모리 저장소 | 개별 최적화 | 중복·수명주기 불일치·권한 분산 | 제외 |
| 기존 Knowledge에 공통 검색 계약과 독립 corpus 추가 | 기존 경로 재사용, 소유권·범위 일관성 | 호출 경계별 연결·검증 필요 | 권장 |

한 통합 계약 아래 Wiki/검색, 메모리/비공개 경계, ORC 대화를 순서대로 구현한다.
새 워크플로 엔진, 지식그래프·Neo4j 복원, 브릿지 개편은 포함하지 않는다.

## 2. 소유권과 5영역 계약

| 영역 | Knowledge | ORC |
|---|---|---|
| High-Level | 지식의 분류·적용 가능성·기억 후보·충돌을 LLM이 판단 | 질문 의도·필요 근거·담당 에이전트·답변 또는 제안을 LLM이 판단 |
| Middle-Level | 검색·읽기·후보 작성·검증·발행 순서 구성 | 기존 Chat 분류, 조회, 답변, Setup 제안 경로 연결 |
| Low-Level | 파일·인덱스·원자적 기록·권한·수명주기 연산 | 기존 에이전트 조회와 승인된 도구 계약 호출 |
| Guardian / Safety | 데이터 범위·출처·공개 정책을 코드로 검사 | 질문과 실행 권한 분리, 기존 승인·실행 가드 유지 |
| Knowledge | Wiki, 사용자/프로젝트 기억, 실행 경험, 축적 지식 제공 | 필요한 context pack을 받아 출처와 함께 사용 |

- 현재 실행 상태는 runtime, 설정 원본은 담당 에이전트/Setup이 계속 소유한다.
- 원본 로그·아티팩트는 기존 위치에 보존한다. Knowledge는 참조·기억·검색 투영을 관리한다.
- 전문 에이전트는 경험을 제출하고 지식을 소비한다. 별도 장기 기억 저장소를 새로 만들지 않는다.
- 기존 ExperimentDB/FailureMemory 등은 일괄 이전하지 않는다. 호환 어댑터를 통해
  Knowledge 관리 경계로 노출하고 기존 소비자·기록 계약을 보존한다.
- 검색은 Knowledge 서비스의 읽기 호출이며, 매번 Knowledge LLM을 추가 호출하지 않는다.
  분류·정리·충돌 판단은 Knowledge LLM, 검색 결과 사용 판단은 소비 에이전트 LLM이 맡는다.

## 3. AX4LAB Wiki

공개 가능한 시스템 기본 지식의 명칭을 **AX4LAB Wiki**로 정한다.
외부 문서 inbox 활성화 여부와 무관하게 기본 설치에서 검색할 수 있어야 한다.

제안 위치는 `docs/knowledge/wiki/`이다. 기존 agent/runtime/bridge 문서의 내용을
복제한 거대 매뉴얼 대신 짧은 주제 설명과 권위 있는 원본 링크를 제공한다.

| 주제 | 내용 |
|---|---|
| 플랫폼 | 목적, 개념, 5영역 구조, 용어 |
| 에이전트 | 역할, 입력/출력, 소유권, 도구, 인수 조건 |
| 오케스트레이션 | 등록 그래프, handoff, 상태·모드의 의미 |
| 사용법 | Chat, Setup, Live GUI, Runtime IDE의 기능과 구분 |
| 장비 연동 | 범용 브릿지 계약·지원 기능·제약; 실제 접속정보 제외 |
| 결과 해석 | 아티팩트 구조, 증거 수준, 실패·복구 규칙 |

각 문서는 `topic_id`, `owner`, `source_refs`, `source_revision/hash`,
`verified_at`, `applicability`, `status`를 갖는다. 파일 revision 확인과 내용 검증을
동일시하지 않는다. 관련 원본 변경 시 해당 항목을 검토 필요로 표시한다.
아직 검토되지 않은 설명은 현재 지원 기능의 확정 근거로 사용하지 않는다.

코드·설정·검토된 문서를 입력 allowlist로 지정한다. 저장소 전체나 실제 설정 파일을
통째로 인덱싱하지 않는다. 비밀값·장비 주소·사용자 경로·실험 ID는 공개 Wiki에 넣지 않는다.
LLM은 Wiki 수정 후보를 만들 수 있지만 자동으로 공개 파일을 갱신하거나 푸시하지 않는다.
공개 발행은 별도 diff 검토를 거친다. 기억은 자동으로 Wiki로 승격되지 않는다.

## 4. 공통 RAG 계약

기본 범위는 `ax4lab_wiki`이며 작업에 필요한 허가된 메모리 corpus를 더한다.
모든 에이전트가 모든 개인 기억을 읽는다는 뜻은 아니다.

`주어진 질문/작업 → 서버 측 호출자·범위 확정 → 검색/읽기 → 출처 포함 context pack → 기존 LLM 판단층`

제안 계약은 `knowledge_context_pack.v1`이다.

| 필드 | 의미 |
|---|---|
| request/consumer | 요청 ID, 등록 에이전트, 판단 목적 |
| scope | 허용 corpus, 사용자·프로젝트·세션·run 범위 |
| items | record/revision, 인용 ID, 짧은 내용, 출처, 적용 조건, 신선도 |
| diagnostics | 검색 범위, no_match/unavailable/stale, 잘림 여부 |
| authority | reference_only; 도구·설정·실행 권한을 부여하지 않음 |

사용자 ID와 최대 권한 범위는 신뢰 가능한 서버 문맥에서 정한다. 모델·HTTP payload의
임의 ID로 확대할 수 없다. 필터는 검색/랭킹/집계 이전에 적용하고 상세 읽기에도 동일 적용한다.
개인 메모리는 기본적으로 ORC의 대화에만 공급한다. 전문 에이전트에는 현재 작업에 필요한
확정된 프로젝트 결정 등 허용된 최소 내용만 전달한다. Wiki-only 소비도 정상 동작이다.

호출자별 모델 context budget 안에 근거를 제한한다. 한글 질문·영문 문서·에이전트 약칭을
검증하고 용어 매핑을 둔다. 기존 검색만으로 품질이 부족한지는 검증 후 판단한다.
검색 실패 시 범위를 넓히거나 웹에 사용자 질문을 자동 전송하지 않는다.

기존 `AgentContext`와 도구 등록을 확장하되 모든 `complete()` 호출에 무차별 삽입하지 않는다.
각 에이전트의 기존 의미 있는 LLM 판단 경계에서 pack을 명시적으로 소비한다.
동일 판단 안에서는 재사용하고 변경된 revision/scope는 캐시를 무효화한다.

메인 LangGraph의 등록 binding을 기준으로 소비자 계약을 구성한다. 등록되지 않은
에이전트는 활성 소비자가 아니다. 새 에이전트의 기본값은 Wiki-only이며, 실제 판단층에서
pack을 소비하는 계약 테스트가 없으면 연결 완료로 표시하지 않는다.

### 에이전트 공급 매트릭스

아래는 구현 목표다. 현재 BO의 Knowledge handoff/로컬 검색, Equipment의 source context,
Design의 제한적 메타데이터 요약이 존재한다는 것과 전 에이전트 공급 완료를 구별한다.

| 소비 에이전트 | 기본 Wiki 검색 주제 | 허가된 추가 기억 | 공급할 기존 판단 경계 |
|---|---|---|---|
| ORC | 플랫폼 개념·등록 기능·사용법·인계 계약 | 사용자 선호, 확정 결정, 관련 과거 실행 | 질문 응답, 계획·위임 판단 |
| Design | 설계 입력·후보 적합성·제작 handoff | 관련 확정 설계 결정·실험 경험 | 후보 평가와 선택의 LLM 판단 |
| Specimen | 제작 계약·지원 도구·모드별 제작 경로 | 적용 가능한 제작 경험 | 적합성 판단·기존 제작 툴 선택 |
| Vision | 검측 계약·관측 증거·판정 의미 | 적용 가능한 검측 경험 | 기존 멀티모달 판단; 실측 이미지는 별도 증거 |
| Manipulation | task 분리·종료·handoff 계약 | 적용 가능한 작업 경험 | 상위 task/완료 판단; 실시간 제어 주기에는 삽입하지 않음 |
| Equipment | workflow/skill·완료·복구 계약 | 관련 source notes·오류 복구 경험 | 기존 workflow 시작/종료 평가; workflow 중간 간섭 없음 |
| Analysis | 분석·목적값·해석 모델의 계약 | 적용 가능한 분석·해석 근거 | 기존 분석/비동기 해석 개선 판단; 수치 결과 덮어쓰기 없음 |
| BO | 변수·최적화·디자인 인계 계약 | Knowledge handoff와 관련 실험 경험 | 기존 전략·검색·optimizer 툴 판단; 다음 점은 optimizer 소유 |
| Guardian | 정책 의미·증거 기준·지원 상태 | 관련 확정 사고·복구 기록 | 기존 감독 판단; 결정론적 차단 경로는 검색에 의존하지 않음 |
| Knowledge | 온톨로지·분류·인용·수명주기 계약 | 허가된 후보·실행 기억·외부 지식 | 기존 검색·정리·발행 판단 |

매트릭스는 고정 등록 목록을 만드는 용도가 아니다. 실제 대상은 메인 graph에서 도출하고,
위 표는 현재 알려진 역할의 공급 의도를 정의한다. 런타임 dispatcher 같은 비에이전트 노드에
불필요한 모델 호출을 추가하지 않는다.

기존 consumer가 서로 다른 필드명을 읽는 부분도 어댑터 테스트에 포함한다. 특히 Design의
`summary/memory_update/recommendation/evidence` 읽기와 Knowledge의
`memory_summary/selected_knowledge/citations` 출력이 저절로 호환된다고 가정하지 않는다.
새 pack과 기존 handoff 사이의 매핑을 한 곳에 정의하고 빈 context를 성공으로 처리하지 않는다.

각 대상은 다음 3단계 증거를 별도로 남긴다.

1. Retrieved: 허용 범위의 관련 문서·revision을 실제로 검색했는가.
2. Delivered: 테스트 transport에서 캡처한 실제 모델 요청에 해당 인용과 내용이 들어갔는가.
3. Used: 답변/구조화 판단이 해당 근거를 정확히 인용하거나, 불필요·부적합하여 제외한 이유가 있는가.

관련 문서/유사하지만 다른 적용 조건/무관한 문서/빈 검색의 대조 시나리오를 에이전트마다
등록 API·로컬 모델로 검증한다. 근거가 판단에 필요 없는 경우 억지로 인용하게 만들지 않는다.
실제 로그에 private context 원문을 복제하지 않으며 모델 요청 원문 검증에는 합성 자료만 쓴다.

## 5. 메모리 분류와 데이터 계약

| 종류 | 기본 범위 | 기록 조건 | 기본 수명 |
|---|---|---|---|
| 사용자 선호 | 사용자 | 명시적 기억 지시 또는 확인 | 사용자가 수정·삭제할 때까지 |
| 연구 맥락 | 사용자/프로젝트 | 확정된 목적·맥락 | 프로젝트 내 유효 |
| 결정 기억 | 프로젝트/선택적 캠페인 | 승인된 결정과 원본 참조 | 대체·철회될 때까지 |
| 임시 지시 | 세션/루프 | 명시한 임시 범위 | 해당 범위 종료 시 만료 |
| 실행 경험 | run/loop/attempt | 기존 완료·실패 이벤트 | 기록 보존, 적용 가능성 별도 판단 |
| 축적 지식 | 프로젝트/허용 공유 범위 | 출처 있는 정리 및 검증 상태 | 대체·만료 정책 적용 |

캠페인 ID는 기존에 존재할 때만 선택적으로 연결한다. 이번 작업으로 캠페인 시스템을 만들지 않는다.

공통 envelope `knowledge_record.v2`를 제안한다. 기존 실행 메모리 v1을 유지하며 읽기 어댑터로
연결한다. 기존 저장소는 run/cycle 필수이므로 Wiki와 사용자 기억에 가짜 run/cycle을 넣지 않는다.

필드는 `record_id`, `kind`, `subject_id`, `owner_agent`, `scope`, `content`,
`source_refs`, `confirmation`, `status`, `created_at`, `updated_at`, `expires_at`,
`supersedes`, `sensitivity`, `revision`으로 구성한다. run/cycle은 실행 기록에서만 필수이다.
`subject_id`는 서버가 식별하는 내부 프로필 ID이며 실명이나 대화에서 추측한 신원은 아니다.

후보 수명주기는 `candidate → active → superseded / expired / deleted`이다.
반복된 표현은 확인 후보를 만들 수 있지만 자동 확정 근거는 아니다. 원문 전체를 장기 기억으로
복사하지 않고 최소한의 명제로 추출한다. 추론·관측·사용자 확정을 구별한다.
동일 이벤트 재처리는 중복 기억을 만들지 않는다. 수정·확정은 expected revision으로 충돌 검사한다.

명시적 기억 지시는 범위가 명확하면 저장 후 짧게 알린다. 모호하거나 적용 범위가 충돌하면
확인 질문을 한다. 기억 저장은 실험 설정을 변경하지 않는다. 시험 조건의 기억은 확정된
Setup/담당 에이전트 readback을 참조하며, 다음 실행도 기존 설정·승인 규칙을 따른다.

## 6. 사용자 접근·잊기·저장 위치

초기 버전은 명시적 로컬 사용자 프로필을 사용한다. 이는 인증 시스템이 아니다.
원격/여러 사용자 서비스에서 프로필 선택만으로 타인의 기억을 읽게 하지 않는다.
신뢰 가능한 사용자 식별이 없으면 Wiki-only로 제한한다. 인증 체계 신설은 별도 범위다.

제안 저장 위치:

```text
docs/knowledge/wiki/                  검토된 공개 시스템 지식
memory/knowledge/wiki_index/          재생성 가능한 로컬 인덱스
memory/knowledge/private/             사용자·프로젝트 기억과 비공개 검색 흔적
memory/knowledge/markdown/            기존 실행 메모리 유지
memory/knowledge/source_library/      기존 외부 자료 지식 유지
runs/, artifacts/                    기존 원본 위치 유지
```

논리적 소유권 중앙화가 모든 원본 파일을 한 디렉터리로 옮긴다는 뜻은 아니다.
백업·export·브라우저 응답·오류 로그에도 동일한 비공개 범위를 적용한다.

“기억 보여줘/수정해/잊어줘”는 ORC와 기존 Knowledge 화면에서 같은 관리 API를 사용한다.
삭제 대상을 분명히 한 후 active 검색·캐시·인덱스에서 즉시 제외한다. 개인정보의 실제 삭제는
append-only 실험 기록과 구분하여 해당 개인 기억 revision 본문과 파생 검색 데이터를 제거한다.
감사 기록에는 삭제된 본문을 재기록하지 않는다. 원본 대화·아티팩트·외부 백업의 삭제 여부는
별도로 알리고, 기억 삭제가 원본까지 삭제했다고 주장하지 않는다. 삭제 tombstone으로
같은 출처의 자동 재적재를 막고 사용자의 명시적인 재기억 요청만 새 기록으로 허용한다.

## 7. ORC 질문 응답과 페르소나

페르소나: **AX4LAB의 연구 협업자이자 오케스트레이터**.
전문적이되 자연스럽고 간결하게, 사용자 언어에 맞춰 설명한다. 사실·제안·불확실성을
구분하고 Wiki/기억/실시간 조회 출처를 제시한다. 과장된 친밀감이나 근거 없는 확신은 피한다.
페르소나는 기존 prompt registry의 ORC 지침으로 관리하며 실행 권한과 분리한다.

기존 Chat 분류의 `question/change_setup/start_run/confirm_pending/out_of_scope/unclear`를
보존한다. question 안에 지식·현재 상태·과거 경험 조회를 구분하고, 기억 관리만 명시적
부작용 계약을 추가한다. 분류 결과 자체는 실행 권한을 부여하지 않는다.

| 입력 | 근거 조회 | 허용 결과 |
|---|---|---|
| 시스템 개념·사용법 | Wiki | 출처 있는 답변만 |
| 현재 상태·지원 여부 | 담당 에이전트의 기존 조회 | 시각·unknown을 포함한 답변 |
| 과거 실험 | 범위가 맞는 실행 기억·아티팩트 | 관측과 해석을 구분한 설명 |
| 기억 관리 | 사용자 범위 기억 | 명시적 생성·수정·삭제 및 알림 |
| 설정 변경 | 기존 Setup와 owner validation | 기존 블록에 제안, 확인 이후 적용 |
| 실행 | 기존 확인·Guardian·dispatcher | 기존 실행 경로 |
| 복합/모호한 요청 | 필요한 읽기 조회 | 답변과 변경 제안을 구분; 불명확한 부작용은 보류 |
| 무관한 입력 | 추가 데이터 조회 불필요 | 짧은 범위 안내, Setup 생성 없음 |

질문 경로에서 run 생성·장비 명령·Setup revision 변경이 발생하면 실패로 본다.
ORC는 현재 상태를 알기 위해 브릿지로 우회하지 않는다. Wiki는 상태 조회 API의 설명이지
현재 장비 상태의 대체물이 아니다. 대화에서 승인한 기억은 실행 승인 토큰으로 해석하지 않는다.

## 8. 비공개 데이터와 GitHub 경계

- 공개: 검토한 Wiki, 코드, 계약, 합성 fixture, 명시적으로 비식별화·선별한 문서 증거.
- 기본 비공개: 프로필, 대화, 기억, 실제 세션, 실험 로그·산출물, 원본 입력 문서,
  검색 질의·근거 trace, 장비 식별정보, 생성 인덱스.
- API 키·토큰·비밀번호는 기억 추출/모델 전송 전 차단하고 기억 내용으로 저장하지 않는다.
- GitHub 비공개 정책과 모델 제공자 전송 정책은 별개다. 개인 메모리의 외부 API 전송은
  기본 제외하며 별도 명시적 허용이 필요하다. 로컬 모델도 동일한 사용자 범위 필터를 따른다.
  기존 API/vLLM 모델 등록·선택 경로를 유지하며 새 모델 서버를 임의로 띄우지 않는다.

`.gitignore`에 더해 staged diff 기반 공개 검사와 CI 검사를 설계한다.
비공개 경로는 강제 추가되어도 차단하고 공개 파일 안의 비밀값·개인정보 가능성을 점검한다.
탐지기는 완벽하지 않으므로 공개 allowlist와 사람의 diff 검토를 함께 사용한다.
검사 오류 메시지에 민감한 원문을 출력하지 않는다. 비공개 내용이 실수로 커밋되었다면
CI가 이미 전송된 내용을 되돌릴 수 없으므로 사전 검사 우회 방지와 대응 절차를 구분한다.

기존 `.gitignore`에는 memory/runs/artifacts 제외가 이미 있으나 이것만으로 안전을
주장하지 않는다. 추적 중인 파일, 원본 source inbox, 단수 output 등 실제 저장 위치까지
검토한다. 저장소 이력에 대한 점검은 별도 보고하며 임의 삭제·이력 재작성·강제 푸시하지 않는다.

## 9. 기존 경로 재사용과 구현 순서

| 단계 | 주된 기존 경로 | 완료 조건 |
|---|---|---|
| 1. 공개 경계와 Wiki seed | docs, gitignore, 기존 검증 scripts | 외부 문서 없이 기본 Wiki 검색; 공개 금지 샘플 차단 |
| 2. Knowledge 검색·기억 계약 | knowledge/markdown_memory.py, source_library.py, mcp_tools/source_tools.py | 기존 v1 호환, corpus·사용자 범위 분리, 수명주기 검증 |
| 3. 에이전트 context 소비 | agents/base_agent.py와 각 decision 모듈, 메인 graph binding | 모든 활성 에이전트가 기존 판단층에서 Wiki 근거를 실제 소비 |
| 4. ORC 대화·페르소나 | agents/orchestrator_decision.py, 기존 Controller Chat, app/planning_setup.py | 질문/기억/설정/실행 분리, 기존 승인 보존 |
| 5. 관리 UI·문서·통합 검증 | 기존 Knowledge 화면, Live Chat, agent docs | 기억 관리와 인용 이동, 비구동 모드별 회귀 통과 |

이번 문서는 통합 설계이며, 상세 파일/테스트 단위 구현 계획은 설계 승인 이후 작성한다.
운영 코드·서비스·실제 장비는 이 설계 작업에서 변경하지 않는다.

## 10. 수용 기준

| 검증 | 통과 기준 |
|---|---|
| Wiki cold start | 외부 문서와 사용자 기억 없이 한·영 시스템 질문에 근거 있는 응답 |
| 에이전트별 공급 | 메인 graph의 각 소비자 LLM 입력·출력에서 관련 Wiki 인용 확인; 등록만으로 통과 불가 |
| 부정 대조 | 없는 기능/비관련 문서에서는 근거 부족을 명시; 무관한 인용으로 성공 처리 금지 |
| 등록 변화 | 추가 binding은 Wiki-only 기본 계약, 제거 binding은 활성 소비 목록에서 제외 |
| 기억 범위 | 사용자 A/B, 프로젝트 A/B, 세션/루프 간 검색·read·count·cache 격리 |
| 수명주기 | 명시적 저장, 확인 대기, 중복 방지, 충돌, 만료, 대체, 삭제·재적재 방지 |
| 질문 무부작용 | 반복 질문에도 Setup/run/장비 실행 기록 변화 없음 |
| 상태 질의 | 오래된 Wiki로 ready를 단정하지 않고 담당 에이전트 조회 또는 unknown |
| 기존 경로 | virtual/real-printer/physical-print 정책을 비구동 경계로 검증; 실제 장비 호출 0 |
| 모델 | 등록 GPT API와 로컬 vLLM에서 동일 합성 질문·기억 시나리오; 실제 사용자 자료 미사용 |
| 공개 검사 | 비공개 경로 강제 stage, 공개 MD에 심은 합성 비밀정보, 검증 trace 누출을 차단 |
| 고장 상황 | 검색 실패·stale·빈 지식·모델 실패 시 거짓 근거·범위 확장·자동 실행 없음 |

검증 증거에는 retrieved와 actually used를 구분한다. 기존 Knowledge/BO·Equipment
source 경로도 회귀 검증하며 전체 에이전트 통과를 일부 경로 결과로 대신하지 않는다.

## 11. 문서 반영 계약

구현 시 Knowledge/ORC 문서, Agent Index/API matrix, 공통 5영역 설계,
기존 Source Curation 문서, Live GUI/Knowledge 화면 안내, 루프 아티팩트 문서를 함께 갱신한다.
각 agent 문서에는 기본 corpus, 추가 메모리 범위, 소비하는 판단 경계, 실제 검증 근거를 적는다.
사용자용 Wiki와 기능 문서는 영어를 기본으로 하며 이 검토용 설계안은 한국어로 유지한다.
표·구조 SVG는 기존 문서 형식에 맞추고 제안/구현/검증 상태를 명확히 구분한다.

## 12. Live GUI 카드 설계

Live GUI는 현재 판단·실험에서 무엇을 참고하고 기억했는지 관측하는 화면이다.
대량 편집·Wiki 발행·기억 삭제 관리는 기존 `/knowledge` Workspace로 연결한다.
기존 페이지 공간과 agent binder를 유지하며 새 팝업 중심의 별도 앱을 만들지 않는다.

### 12.1 ORC: Knowledge & Memory

ORC 페이지에 `Knowledge & Memory` 카드 하나를 추가한다.

| 항목 | 표시 계약 |
|---|---|
| Request | Question / Setup proposal / Memory update / Execution |
| Knowledge scope | AX4LAB Wiki와 실제 허가된 추가 corpus·범위 |
| Evidence | 이번 판단에 사용한 출처, revision, 조회 시각 |
| Memory activity | 저장·변경·확인 대기 여부; 기본 화면에 개인 내용 표시하지 않음 |
| Status | Retrieved / No match / Unavailable / Needs review |
| Actions | 출처 상세, Manage Memory로 기존 Workspace 이동 |

카드는 현재 선택된 응답/판단 ID에 귀속한다. 이전 응답 근거를 새 답변에 붙이지 않는다.
검색 성공과 실제 사용을 동일시하지 않는다. 요청이 없으면 `No retrieval yet`를 표시한다.
답변 근거와 설정 블록을 분리하여 질문만으로 Setup 항목이 생성되지 않게 한다.

### 12.2 Knowledge: 고정 카드 4개

| 카드 | 표시 | 동작 |
|---|---|---|
| AX4LAB Wiki | 공개 주제 수, 검토 필요, 로컬 인덱스 상태 | Browse / Search |
| Memory | 권한 범위의 활성·확인 대기·만료 기억 수 | Review / Manage |
| Agent Knowledge Delivery | 에이전트별 Retrieved / Delivered / Used, 판단 시각 | 대상 선택 후 근거 상세 |
| Knowledge Activity | 적재·갱신·검색·기억 변경 기록 | 항목 상세 |

기존 Memory Ledger, Retrieval / Provenance, Memory Intake, Evidence Quality에서
동일한 정보를 중복 표시하지 않고 위 카드의 요약·상세에 통합한다. Activity는 기존 것을
재사용한다. Pattern/Evolution의 원본 기능은 보존하고 Memory 상세/Workspace로 연결한다.

Delivery 목록은 메인 graph의 활성 소비자를 사용한다. `Not requested`, `No match`,
`Unavailable`, `Not delivered`, `Used`, `Excluded`, `Unknown`을 구별한다.
No match는 검색 오류가 아니며, Delivered만으로 Used를 채우지 않는다. 사용은 판단 결과의
유효한 인용으로 확인하고, 이것이 과학적 성능 개선을 입증한다고 주장하지 않는다.
미등록 소비자의 과거 기록은 history에서만 별도로 조회할 수 있다.

### 12.3 Chat 보조 표시

- `Sources · N`: 응답에 연결된 근거만 펼친다.
- `Memory saved · Project`: 저장 결과와 범위를 표시한다.
- `Memory confirmation needed`: 후보를 Remember / Dismiss로 확인한다.
- `Temporary · This session`: 해당 기억의 종료 조건을 표시한다.

기억 확인 버튼과 Setup/실행 승인 버튼은 별도 요청 형식과 대상 ID를 사용한다.
기억 확인을 시작 승인으로 전파하지 않는다. Chat에서 기억 삭제를 요청하면 명확한 대상과
삭제 범위를 확인한 뒤 Workspace와 같은 API를 사용한다.

### 12.4 갱신·레이아웃

카드 위치는 고정하고 데이터가 없어도 빈 상태를 제공한다. 현재 요청·세션·loop·attempt를
명시하며 과거 성공을 현재 상태로 표시하지 않는다. 기존 세션/루프 선택을 재사용한다.

기존 이벤트 경로에서 지식/기억 revision 변경을 받아 요약을 갱신한다. 새 이벤트 수단은
기존 연결로 부족할 때만 검토한다. 연결 복구 시 revision 기반의 읽기 재조회로 동기화하고,
탭을 누를 때만 상태를 알아내는 구조를 피한다. 상세 원문은 사용자가 열 때만 조회한다.
역순 응답은 이전 세션·선택 항목을 덮어쓰지 못한다. 반복 렌더링에 의해 펼침/스크롤/선택이
초기화되지 않게 한다. 숨겨진 탭이 전체 목록·원문을 반복 다운로드하지 않는다.

## 13. Knowledge Workspace 개선안

### 13.1 현재 구조와 재편 원칙

현재 `web/templates/knowledge.html`, `web/static/knowledge.js`의 네 탭은
Markdown Knowledge / Memory / Ontology / Source Library다. Markdown과 Memory가
저장 포맷 중심으로 나뉘어 있어 사용자 선호·실행 경험·기본 지식을 구별하기 어렵다.
기존 API·기록을 버리지 않고 사용자 목적에 맞게 다섯 탭으로 재구성한다.

| 새 탭 | 역할 | 기존 기능 처리 |
|---|---|---|
| AX4LAB Wiki | 공통 시스템 지식 탐색·근거·revision 확인 | 신규 Wiki corpus 조회, 기존 문서 링크 재사용 |
| Memory | 사용자/연구/결정/임시/실행/축적 기억 관리 | Markdown Knowledge와 기존 Memory를 한 진입점으로 통합 |
| Source Library | 외부 자료 감지·변환·정리·검색 | 기존 source API·worker·페이지별 변환 보존 |
| Agent Delivery | 에이전트별 지식 전달 및 사용 검증 | 공통 context pack trace의 읽기 투영 |
| Ontology | 분류 체계·관계 정의 열람 | 기존 ontology API 보존; 지식그래프 재도입 없음 |

상단에는 `Knowledge Workspace` 제목, 현재 데이터 범위, index 연결 상태, 진행 중인
작업과 검토 대기 요약을 둔다. 개인 내용과 전체 사용자 수를 공개 요약으로 노출하지 않는다.
기존 Recorded Activity는 공통 Activity drawer/상세로 재사용하고 여섯 번째 대형 탭으로
추가하지 않는다. Live GUI의 4개 카드는 이 Workspace 데이터의 얇은 요약이다.

### 13.2 공통 탐색 구성

상단 범위/검색 → 왼쪽 목록 → 오른쪽 상세의 공통 구조를 사용한다. 좁은 화면은
목록에서 상세로 전환하되 검색 조건·스크롤을 유지한다. 긴 목록은 페이지 단위로 조회한다.
현재 identity와 조회 범위를 분명히 보여주되 사용자 신원은 서버가 결정한다.
범위 선택 UI는 권한이 있는 범위만 좁힐 수 있으며 사용자 ID 입력으로 권한을 얻지 못한다.

상세에는 내용, 종류, 소유자, 적용 범위, 상태, revision, 출처, 생성/검토 시점,
만료 조건, 대체 관계를 보여준다. 참조는 서버가 검증한 문서/아티팩트 링크만 제공한다.
Markdown HTML·스크립트와 외부 자동 로딩 이미지는 실행하지 않는다. 원본 파일 경로를
API 응답·URL에 그대로 노출하지 않는다.

Live GUI에서 `Wiki 출처`, `기억`, `Delivery`를 열 때 같은 record/decision을 선택한다.
예상 deep link는 `/knowledge#delivery` 등 탭과 불투명 ID만 포함한다. 대화·개인 이름·
메모리 내용·검색어를 URL에 싣지 않는다. ID만 알아도 읽을 수 있는 공개 링크로 만들지 않는다.
기존 memory/ontology/manuals 링크는 의미가 맞는 새 탭으로 호환 매핑한다.

### 13.3 AX4LAB Wiki 탭

주제·담당 에이전트·검토 상태 필터와 한/영 검색을 제공한다. 내용에는 원본 문서·코드
revision, 현재 검토 상태를 연결한다. `Reindex`는 이미 승인된 로컬 Wiki만 인덱싱하며
LLM 생성·Git 커밋·푸시와 분리한다. 변경 후보는 별도 검토 상태로 관리한다.
Workspace에 발행 버튼을 만든다면 공개 가능성 검사와 diff 확인까지만 수행하고,
GitHub 업로드를 자동 실행하지 않는다. 최초 구현은 열람·검색·인덱스 상태를 우선한다.

### 13.4 Memory 탭

필터는 종류, 권한 범위, 상태, 세션/루프, 검색어다. 사용자 선호와 실행 경험을 같은
목록에서 식별할 수 있게 종류를 명시한다. 실행 경험 아래에는 기존 performance,
failure/success pattern, Evolution pack/outcome 탐색을 유지한다.
권한 범위가 다른 데이터의 개수도 누출하지 않는다.

| 동작 | 의미와 제한 |
|---|---|
| Review candidate | 출처·내용·범위를 확인하여 Remember 또는 Dismiss |
| Edit | revision 기반 수정; 이전 기억은 superseded |
| Change scope | 권한 범위 안에서만 변경; 공유 범위 확대는 명시적 확인 |
| Expire | 기본 검색에서 제외; 과거 이력은 표시 |
| Forget | 대상 기억·파생 데이터 삭제 범위를 설명한 뒤 확인; 원본 별도 |
| View source | 동일 권한으로 원본 대화/결정/아티팩트 열람 |

기억의 설정값을 수정해도 실험 설정은 바뀌지 않는다. 실제 설정을 바꾸려면
`Propose in Setup`으로 기존 Chat/블록 경로를 열고 별도 확인을 받는다.
대량 삭제·전체 사용자 기억 내보내기는 최초 구현 범위에 넣지 않는다.
export가 추가되더라도 공개 대상과 동일시하지 않고 비공개 파일로 분류한다.

### 13.5 Source Library 탭

기존 자동 적재 enablement, 명시적 Scan/Retry, per-source 진행 상태, 필터, 원본/변환
Markdown/발행 note/인용을 보존한다. 공개 문서는 특정 입력 자료 종류를 제한적으로
열거하지 않고 범용 source material로 설명한다. 부분 읽기 결과를 완성된 지식으로
검색에 노출하지 않는 기존 정책을 유지한다.
외부 자료 자동 적재가 꺼져 있어도 Wiki·사용자 기억 조회는 계속 가능하다.
페이지를 여는 것만으로 scan/변환/모델 호출이 시작되지 않는다.

### 13.6 Agent Delivery 탭

에이전트·세션·루프·판단 ID·상태로 조회한다. 상세는 다음 순서를 따른다.

`검색 목적/범위 → 검색된 인용 → 전달된 context pack → 판단 결과의 사용/제외 근거`

모델 입력 원문과 내부 추론을 기본 표시하거나 저장하지 않는다. 허가된 인용·전달 receipt·
출력의 사용 근거만 제공한다. 사용 근거가 없으면 Unknown이지 자동 성공이 아니다.
활성 에이전트의 `Not requested`와 과거 루프의 성공을 분리한다.
자동 갱신과 수동 read-only refresh를 제공하되 `Run agent`/장비 재실행 버튼은 두지 않는다.

### 13.7 UI/API 수용 조건

- Wiki·Memory·Source·Delivery가 각자 데이터와 scope를 유지하며 잘못된 corpus 혼합이 없다.
- Live GUI와 Workspace가 동일 record/revision/status를 표시한다.
- 사용자가 명시한 기억과 후보를 구별하고, 승인/편집/삭제 충돌은 최신 상태 재확인으로 처리한다.
- 클릭·초기 진입·탭 전환이 scan, 모델 호출, 실험 실행을 유발하지 않는다.
- 사용자/세션 전환·역순 응답·연결 단절 후 다른 범위의 상세가 남지 않는다.
- 읽기 오류를 빈 데이터나 성공으로 위장하지 않는다. private 조회 권한이 없으면 제한 상태를 표시한다.
- 자동 갱신에서 선택·스크롤·상세 펼침 보존, 좁은 화면과 키보드 탐색 검증.
- 기존 source ingestion, Markdown query/read, ontology, operational memory 회귀 테스트 유지.
- 공개 문서·스크린샷·검증 fixture는 합성 데이터만 사용하고 실제 사용자 정보는 포함하지 않는다.

### 13.8 구현 순서

먼저 공통 검색·scope·delivery receipt 계약을 검증한 뒤 다음 UI 순서로 연결한다.
① Agent Delivery와 Live 공급 카드 → ② Wiki/Memory Workspace와 Live 카드 →
③ ORC 근거 카드·Chat 기억 확인 → ④ Source/기존 Memory 통합과 문서 정리.
미구현 API가 있는 카드는 `Not connected`로 표시하며 샘플 성공 값을 운영 UI에 넣지 않는다.

## 14. Workspace 프론트엔드–백엔드 통합 개선 계약

이 절의 신규 API·파일 이름은 제안이며 현재 구현된 endpoint로 설명하지 않는다.
Workspace는 Knowledge의 관리 클라이언트이고 Live GUI는 동일 백엔드의 요약 클라이언트다.
두 화면이 각자 저장소를 만들거나 서로 다른 기억 수명주기를 구현하지 않는다.

### 14.1 기능별 연결

| 기능 | 프론트엔드 책임 | 백엔드 책임 |
|---|---|---|
| 공통 요약 | 현재 범위·freshness·작업·오류 표시 | 허가된 데이터만 집계, 공개/비공개 응답 분리 |
| Wiki | 검색·주제 탐색·인용·revision 상세 | 검토된 corpus 색인, 검색·read, 원본 revision 대조 |
| Memory | 종류/범위 필터, 후보 확인, 수정·만료·잊기 | 주체 검증, v1/v2 어댑터, revision·수명주기·삭제 |
| Sources | 기존 적재·retry·진행·원본/발행문 상세 | 기존 SourceLibrary/worker 재사용, idempotency·부분 결과 격리 |
| Delivery | 에이전트별 상태와 단계별 근거 표시 | 실제 소비자 경계의 receipt 저장, graph binding별 투영 |
| Ontology | 읽기 전용 분류·정의 탐색 | 기존 registry API 재사용, graph backend 호출 없음 |
| Live 연계 | 불투명 ID로 같은 항목 선택 | 동일 scope/revision의 요약·상세 제공 |
| Chat 기억 관리 | 명시적인 기억 확인 UI | ORC와 Workspace가 동일 command service 사용 |

### 14.2 백엔드 구성과 재사용

| 구성 | 재사용 / 제안 변경 |
|---|---|
| Corpus 검색 | `knowledge/rag.py`, `markdown_memory.py`, `source_library.py` 위에 corpus 어댑터; 기존 검색 엔진을 우선 유지 |
| Wiki catalog | 제안 `knowledge/wiki.py`; 공개 allowlist·문서 metadata·revision·index 상태 책임 |
| 개인/연구 기억 | 제안 `knowledge/private_memory.py`; 독립 v2 identity와 수명주기; 기존 실행 v1은 호환 읽기 |
| 공통 검색 서비스 | 제안 `knowledge/context_service.py`; 서버 권한 범위, adapter routing, budget, context pack 조립 |
| 공급 receipt | 제안 `knowledge/delivery.py`; retrieved/delivered/used 단계별 기록과 조회 투영 |
| HTTP | 기존 `knowledge/http_api.py`, `source_api.py` 재사용; 새 관리 route는 제안 `knowledge/workspace_api.py`로 분리 |
| Chat/도구 | 기존 `mcp_tools/source_tools.py`·AgentContext 도구에 같은 서비스 연결; HTTP를 내부적으로 우회 호출하지 않음 |
| 등록·저장 주입 | 기존 app 초기화에서 service를 한 번 구성하고 공유; 요청별 별도 store 생성 방지 |

작은 책임 단위만 추가하고 거대한 `app/main.py`에 모든 관리 로직을 넣지 않는다.
저장소 병합, 새로운 DB·vector server 도입, 원본 아티팩트 이동은 전제하지 않는다.
검색 품질 검증에서 필요성이 확인되기 전 모델/검색 인프라 교체는 하지 않는다.

### 14.3 제안 API 표

| API | 용도 | 쓰기/모델·장비 부작용 |
|---|---|---|
| GET `/api/knowledge/workspace/summary` | 허용 범위별 Wiki/Memory/Sources/Delivery 집계와 revision | 읽기 전용 |
| POST `/api/knowledge/wiki/query`, `/wiki/read` | Wiki 목록·검색/정확한 revision 상세 | 읽기 전용 |
| POST `/api/knowledge/wiki/reindex` | 검토된 Wiki index 재생성 job | 명시적 관리 동작; 모델·Git·장비 없음 |
| POST `/api/knowledge/memory/query`, `/memory/read` | 권한 필터가 적용된 v1/v2 통합 조회 | 읽기 전용 |
| POST `/api/knowledge/memory/commands` | propose/confirm/dismiss/edit/expire/forget | 명시적 기억 변경만; 실험 상태·설정 변경 없음 |
| POST `/api/knowledge/delivery/query`, `/delivery/read` | binding/판단/loop별 공급 receipt 조회 | 읽기 전용 |
| POST `/api/knowledge/context/query`, `/context/read` | 에이전트용 공통 범위 검색과 상세 근거 | 읽기 전용; 모델의 범위 확대 금지 |
| 기존 `/api/knowledge/sources/*` | source 적재·조회·설정·retry | 기존 명시적 쓰기 계약 유지 |
| 기존 `/api/knowledge/ontology*`, `/activity` | 분류와 허가된 활동 조회 | 기존 읽기 기능 유지, 권한 집계 점검 |
| 기존 `/api/knowledge/markdown/*` 및 operational memory APIs | 이전 소비자 호환 | 기존 계약 보존, 권한 우회가 되지 않도록 동일 service 경계 적용 |

개별 프로필용 데이터는 새 endpoint에만 권한을 붙이고 기존 endpoint로 노출되는 실수를
막는다. 사용자 identity가 없는 기존 내부 실행 기록 경로는 기존 허용 경계를 유지하며,
새 private corpus가 그 경로의 기본 조회에 섞이지 않게 한다.

새 query body는 `query`, `filters`, `cursor`, `limit`을 받되 사용자 identity는 받지 않는다.
scope는 서버가 허용 범위와 교집합을 취한 뒤 확정한다. response는 `items`, `next_cursor`,
`scope_ref`, `revision`, `as_of`, `status`를 공통으로 제공한다. page limit는 기본 25,
최대 100으로 제한한다. corpus별 revision을 유지하며 전역 revision 한 개에 의존하지 않는다.
cursor는 scope/filter/revision에 귀속하고 다른 사용자나 검색 조건에 재사용할 수 없다.

command는 `action`, `target_id`, `expected_revision`, `idempotency_key`, 해당 action에
정의된 payload만 받는다. 임의 필드·절대 경로·자유로운 파일 쓰기를 허용하지 않는다.
동일 키·동일 payload의 재시도는 같은 receipt를 반환하고 다른 payload는 충돌로 처리한다.
revision 충돌은 409, 잘못된 필드는 422, 권한 부족은 인증 계약에 따른 401/403,
비허가 record ID 조회는 404로 존재를 숨긴다. unavailable은 빈 성공 결과로 반환하지 않는다.

### 14.4 기록·갱신 일관성

메모리 저장과 revision/tombstone 반영은 기존 원자적 기록/lock 패턴을 재사용한다.
index는 원본의 투영이다. 원본 저장 후 index 갱신 실패 시 `index_pending` 상태를 기록하고
재시도한다. 삭제·만료·권한 변경은 stale index가 남아 있어도 read 직전 차단한다.
개인정보 삭제가 필요한 본문은 기존 append-only 실행 로그에 복제하지 않는다.

Delivery는 `decision_id`, `consumer_binding`, `run/loop/attempt`, `request_id`,
검색 시점 scope/revision과 content-free citation receipt로 연결한다. 모델 요청 조립 완료를
Delivered receipt로, 모델 출력의 인용 검증 결과를 Used/Excluded/Unknown으로 기록한다.
검색만 수행한 경우 Delivered를 만들지 않는다. 검증 실패한 인용은 사용 근거로 인정하지 않는다.

기존 event 경로에 Wiki index, memory revision, source job, delivery receipt 변경 이벤트를
연결한다. UI는 이벤트로 관련 요약만 무효화하고 변경 revision을 조회한다. 이벤트 유실 후에는
summary snapshot으로 복구한다. 데이터가 크면 event 본문에 원문 대신 ID/revision만 보낸다.
서버 재시작·중복 이벤트·역순 응답에서도 쓰기 중복이나 이전 값 복원이 없어야 한다.
Agent read 경로는 index만 이용하며 사용자 페이지 진입이나 검색이 Knowledge LLM 작업을
자동 시작하지 않는다. 적재·정리 LLM은 기존 low-priority worker/lease를 사용한다.

### 14.5 프론트엔드 구현 경계

기존 `knowledge.html/js/css`를 진입점으로 유지한다. 탭별 view와 공통 scoped API client를
책임 단위로 분리할 수 있지만 새 프론트엔드 프레임워크 도입은 필요 조건이 아니다.

- query generation/AbortController로 이전 조회가 새로운 선택 결과를 덮어쓰지 못하게 한다.
- scope 전환 즉시 이전 상세를 비우고 허용 요약·목록을 다시 요청한다.
- 후보 확인·수정·삭제 대기 중 버튼 중복 요청을 막는다. 실패 시 draft는 남기되 성공 표시하지 않는다.
- private 기억 본문을 localStorage/sessionStorage나 기존 Live HTML 캐시에 저장하지 않는다.
  UI 복원은 비민감 탭·필터 식별자만 허용하고 권한 재검사 후 내용을 다시 읽는다.
- private API 응답은 `Cache-Control: no-store`를 사용하고 서비스워커/offline cache에도 넣지 않는다.
- 사용자 권한 밖 내용은 접어두는 방식이 아니라 서버 응답에서 제외한다.
- 클릭 위치와 scroll anchor를 항목 ID로 유지하고 이벤트 갱신 때 전체 DOM을 무조건 교체하지 않는다.
- Remember/Forget와 Setup Confirm/Run 액션의 색·이름·target을 구별하고 키보드 확인도 같은 경계를 따른다.

### 14.6 프론트엔드–백엔드 검증 묶음

| 계층 | 주요 시나리오 | 확인 결과 |
|---|---|---|
| Service | Wiki cold start, corpus 필터, 빈 검색, stale revision | 정확한 근거 또는 명시적 상태 |
| API | 사용자 A/B, scope cursor 오용, 직접 read, legacy 우회 | 목록·내용·개수·캐시 누출 없음 |
| Command | 중복 클릭/재시도/충돌/삭제 후 재적재 | 단일 효과, revision 유지, 삭제된 기억 비노출 |
| Event | 연결 단절·중복·역순·재시작 | 현재 snapshot 복구, 화면 상태 보존 |
| Browser | 탭 탐색·검색·상세·후보 확인·수정·forget | 실제 API 결과와 UI 상태 일치 |
| Agent | 각 graph 소비자의 API·로컬 모델 입력/출력 | Retrieved/Delivered/Used 대조 증거 |
| Regression | 기존 Source/Markdown/Ontology/패턴·Evolution | 원본 기능·데이터 계약 보존 |
| Privacy | trace·URL·브라우저 저장·공개 파일·staged 검사 | 실제 개인정보 미사용, 합성 누출 샘플 차단 |

실험 모드 회귀는 기존 경로를 비구동 테스트 경계에서 사용한다. 새 UI 검증을 위해 장비를
움직이거나 성공한 workflow를 재실행하지 않는다. API 단위 테스트만 통과한 상태를
브라우저/실제 에이전트 공급 검증 완료로 표시하지 않는다.
