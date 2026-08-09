---
doc_type: index
subtype: index
status: active
authority: navigation
audience:
  - researcher
  - reviewer
  - operator
  - developer
scope:
  - repository
  - paper
  - korean_companion
summary: 시스템 기여를 우선하는 Autonomous Researcher Framework 한국어 진입 문서.
related_docs:
  - README.md
  - README.en.md
  - docs/paper/README.md
  - docs/README.md
  - docs/standards/paper_documentation_standard.md
  - REQUIREMENTS.md
  - SECURITY.md
supersedes: []
---

# Autonomous Researcher Framework

> **연구 아티팩트 상태:** 소프트웨어 저장소는 활성 상태이며 논문 문서
> 패키지는 검토 중입니다. 종단간 과학 성능과 실제 장비 성능은 아직
> `not_evaluated`입니다.

Autonomous Researcher Framework(ATR)는 연구 목표, 실험 설계, 시편 제작,
비전, 조작, 장비 실행, 분석, 영속 지식, 베이지안 최적화를 하나의 재개
가능한 폐루프로 연결하는 안전 게이트·증거 중심 멀티에이전트 시스템입니다.

[English paper landing page](README.md) · [상세 영문 가이드](README.en.md) ·
[논문 문서 패키지](docs/paper/README.md) · [전체 문서 인덱스](docs/README.md) ·
[Runtime IDE Reference](docs/runtime/runtime_ide.md)

## 그래피컬 애브스트랙트

![안전 게이트 기반 ATR 폐루프](docs/paper/assets/figures/01_graphical_abstract.svg)

**그림 1.** ATR은 연구 자동화를 개별 도구 묶음이 아니라 통제된 시스템
루프로 다룹니다. 주황색 다이아몬드는 Guardian/운영자 게이트, 초록색
문서는 영속 증거를 뜻합니다. 구조는 코드 조사로 확인했지만 과학적 효과와
실장비 강건성은 평가하지 않았습니다.

## 논문 요약

**작업 제목:** *Autonomous Researcher Framework: A Safety-Gated
Closed-Loop Multi-Agent System and Extensible Platform for Laboratory
Automation*

논문 기여의 우선순위는 다음과 같습니다.

1. **주 기여 — 시스템:** 타입이 있는 단계 간 핸드오프, 체크포인트,
   Guardian/운영자 게이트, 영속 증거, 지식 피드백, 명시적 종료 상태를 가진
   폐루프 연구 시스템
2. **부 기여 — 플랫폼:** 시스템 계약을 우회하지 않고 모듈, 그래프, 모델,
   장비 브리지, 운영 화면을 확장하는 구조

| ID | 연구 질문 |
|---|---|
| RQ1 | 서로 다른 연구 단계를 완전하고 재개 가능한 폐루프로 어떻게 구성하는가? |
| RQ2 | 의사결정·실행·관찰·분석·지식 갱신 전반의 증거를 어떻게 감사 가능하게 보존하는가? |
| RQ3 | Guardian과 운영자 게이트가 위험하거나 불확실하거나 되돌리기 어려운 동작을 어떻게 제한하는가? |
| RQ4 | 시스템 계약을 약화하지 않으면서 에이전트·장비·모델·워크스페이스를 어떻게 추가하는가? |

## 문제

실험실 연구 루프는 추론, 소프트웨어, 물리 상태, 측정, 분석, 반복 의사결정을
가로지릅니다. 단계가 바뀔 때마다 최초 목표, 아티팩트 출처, 승인 상태,
물리 동작 발생 여부, 복구 문맥이 끊길 수 있습니다. 독립 도구 호출은 데모를
쉽게 만들지만 과학 실행의 감사를 어렵게 하고, 하나의 불투명한 에이전트는
정책과 실패 경계를 숨깁니다.

ATR은 도메인 단계, 사이드카, 제어 게이트, 증거 경로, 피드백 간선, 종료
상태를 명시한 실행 그래프로 이 문제를 다룹니다.

## 시스템 기여

코드 기준선 `0b7627b`에서 기본 그래프는 노드 19개, 선언 간선 68개,
단계 디스패치 항목 12개입니다. 이 수치는 특정 커밋의 아키텍처 관찰값이며
성능이나 안정성 보장이 아닙니다.

| 시스템 메커니즘 | 역할 | 현재 증거 경계 |
|---|---|---|
| 실행 그래프 | 디스패치·피드백·종료 경로를 명시 | 구조 조사 완료, 완전한 실장비 캠페인은 미평가 |
| 타입 기반 핸드오프 | 목표·결정·도메인 아티팩트·오류를 구분 | 종단간 계약 행렬 미평가 |
| 체크포인트 상태 | 명시적 재개와 복구 문맥 제공 | 실패 유형별 복구 효과 미평가 |
| Guardian/운영자 게이트 | 중요하거나 불확실한 동작 제한 | 제어 지점 조사 완료, 실제 안전 효과 미평가 |
| 증거·Knowledge 경로 | 아티팩트·ledger/outbox·출처·문맥 보존 | 문서 계약 시험 완료, 전체 과학 계보 미평가 |
| BO 피드백 | 다음 후보를 통제된 경로로 제안 | 경로 조사 완료, 과학적 이점 미평가 |

## 시스템 아키텍처

![ATR 계층형 아키텍처](docs/paper/assets/figures/02_layered_architecture.svg)

**그림 2.** 연구 의도와 운영자 제어가 오케스트레이터로 들어가고, 타입 기반
에이전트·Guardian·모델/장비 어댑터를 거쳐 증거와 지식에 연결됩니다.
점선은 부차적인 플랫폼 확장 경로입니다.

```text
design -> specimen -> vision/manipulation -> equipment -> analysis
       -> knowledge -> Bayesian optimization -> Guardian
       -> continue / review / complete / error
```

자세한 설명은 [시스템 아키텍처](docs/paper/02_system_architecture.md),
[폐루프 방법](docs/paper/03_closed_loop_method.md),
[현재 코드 스냅샷](docs/runtime/current_code_snapshot.md)을 봅니다.

## 안전 경계

중요 동작은 설정에 따라 스키마/기능 검증, Guardian 정책, 운영자 승인,
dry-run/사전조건을 통과한 뒤 외부 실행으로 진행합니다. 거부, 승인 만료,
dry-run 실패, 알 수 없는 외부 상태는 검토·중지·오류 경로로 분리해야 합니다.

이 제어 계층은 범용 안전 인증이 아닙니다. 실험실별 인터록, 위험성 평가,
책임 운영자, 최소 권한 배포, 비상 정지, 실행 증거가 별도로 필요합니다.
물리 동작의 발생 여부가 불확실한 타임아웃은 상태를 다시 확인하기 전 자동
재시도하면 안 됩니다.

[안전·윤리·한계](docs/paper/08_safety_ethics_and_limitations.md)와
[보안 정책](SECURITY.md)을 함께 읽습니다.

## 평가 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| route·그래프 아키텍처 수치 | 조사 범위에서 `supported` | `E-INSPECT-ARCH-001` |
| 논문 주장-증거/문서 계약 | `partially_supported` | `E-TEST-DOC-001` |
| 전체 단계 계약 실행 | `not_evaluated` | 적합한 논문 증거 없음 |
| 체크포인트/재개 효과 | `not_evaluated` | 적합한 논문 증거 없음 |
| Guardian/실장비 안전 효과 | `not_evaluated` | 적합한 논문 증거 없음 |
| Knowledge/BO의 과학적 효과 | `not_evaluated` | 비교 연구 없음 |
| 종단간 물리·과학 결과 | `not_evaluated` | Tier 4 캠페인 증거 없음 |

기준선에서 FastAPI `APIRoute` 346개, 전체 애플리케이션 route 353개,
그래프 노드 19개, 간선 68개, 단계 디스패치 12개를 확인했습니다. 초기
집중 문서 검증은 선택된 시험 23개 통과를 기록했습니다. 이는 아키텍처·문서
결과이지 과학 성능 지표가 아닙니다.

## 플랫폼 기여

부 기여인 플랫폼은 시스템 계약을 유지하면서 다음 확장면을 제공합니다.

- 에이전트 모듈: manifest, handler, schema, stage 등록
- 실행 그래프: 버전이 있는 노드·간선·디스패치·검증·활성화 규칙
- 모델 백엔드: provider/model 라우팅, readiness, 제한된 추론 계약
- 장비 브리지: capability, allowlist, 인증, dry run, proof, timeout
- Knowledge 백엔드: ontology, provenance, ledger/outbox, receipt, 제한 query
- 운영 워크스페이스: 서버 정책을 권한 기준으로 하는 조회·검토·설정·변경 API

기준선에서 애플리케이션은 FastAPI `APIRoute` 346개와 전체 route 353개를
노출합니다. route 수는 표면 규모와 문서 드리프트를 확인하는 값이지 사용성
점수가 아닙니다. [플랫폼 아키텍처](docs/paper/04_platform_architecture.md)와
[인터페이스 부록](docs/paper/appendix_a_interfaces.md)을 봅니다.

## 재현 단계

| Tier | 환경 | 초기 패키지 상태 |
|---|---|---|
| 0 | 저장소·문서·도표·증거 정적 조사 | 가능 |
| 1 | 집중 단위/계약 시험 | 문서 하위 집합 가능 |
| 2 | 결정적 replay 또는 simulation | `not_evaluated` |
| 3 | 브라우저 운영 흐름 | 이 패키지에서는 `not_evaluated` |
| 4 | 감독된 실장비 실행 | `not_evaluated` |

저장소 루트에서 최소 문서 검증은 다음과 같습니다.

```bash
.venv/bin/python scripts/validate_documentation.py
.venv/bin/python scripts/validate_paper_publication.py
.venv/bin/python -m pytest -q \
  tests/unit/test_documentation_validation.py \
  tests/unit/test_paper_publication_validation.py
```

설치·실행·선택 기능 요구사항은 [REQUIREMENTS.md](REQUIREMENTS.md),
[상세 영문 가이드](README.en.md), [전체 문서 인덱스](docs/README.md)에
있습니다. 하위 단계가 통과했다는 이유만으로 실장비 단계로 진행하면 안 됩니다.

## 논문 문서

논문식 정독 순서:

1. [문제와 기여](docs/paper/01_problem_and_contributions.md)
2. [시스템 아키텍처](docs/paper/02_system_architecture.md)
3. [폐루프 방법](docs/paper/03_closed_loop_method.md)
4. [플랫폼 아키텍처](docs/paper/04_platform_architecture.md)
5. [실험 설정](docs/paper/05_experimental_setup.md)
6. [평가와 결과](docs/paper/06_evaluation_and_results.md)
7. [재현성](docs/paper/07_reproducibility.md)
8. [안전·윤리·한계](docs/paper/08_safety_ethics_and_limitations.md)
9. [주장-증거 추적성](docs/paper/09_claim_evidence_traceability.md)

문서 작성 규칙은
[Paper Documentation Standard](docs/standards/paper_documentation_standard.md)에
있습니다.

## 인용·라이선스·보안

소프트웨어 인용 메타데이터는 [CITATION.cff](CITATION.cff)를 사용합니다.
승인된 저자·소속 목록과 DOI가 없으므로 꾸며 넣지 않았습니다.

현재 이 저장소에는 오픈소스 라이선스가 부여되지 않았습니다. 사용·수정·재배포
전에 [LICENSE](LICENSE)를 확인해야 하며, 공개 재사용을 의도한다면 권리자의
명시적인 라이선스 결정이 필요합니다.

취약점은 [SECURITY.md](SECURITY.md)의 비공개 절차로 제보합니다. 비밀값,
사설 endpoint, exploit 세부사항을 공개 issue에 올리면 안 됩니다.

기여 절차: [CONTRIBUTING.md](CONTRIBUTING.md) · 변경 이력:
[CHANGELOG.md](CHANGELOG.md)
