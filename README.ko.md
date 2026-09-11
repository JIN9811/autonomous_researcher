<!-- atr-doc
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
  - docs/runtime/three_level_control_model.md
  - REQUIREMENTS.md
  - SECURITY.md
supersedes: []
-->

# Autonomous Researcher Framework

### 하드웨어는 간단하게, 소프트웨어는 고도화된 자율 실험실

ATR은 기존 실험실 위에 **구조화된 AI 계층**을 얹습니다. 기존 장비를
유지하면서 VLA 기반 로봇팔로 물리 작업을 연결하고, 멀티에이전트 소프트웨어가
연구 판단과 실행을 조율합니다.

핵심은 단순한 저비용이 아니라 **장비 재사용 + 간단한 로봇 하드웨어 +
고도화된 소프트웨어 구조**입니다. 전용 지그와 이송 장치에 대한 의존을 줄이는
방향이며, 장비·지그 비용 절감액을 정량 검증했다는 뜻은 아닙니다.
LeRobot을 통해 지원 로봇으로 교체할 수 있는 경계를 두되, 교체 시 캘리브레이션과
정책 검증은 필요합니다.

[English overview](README.md) · [논문](docs/paper/README.md) ·
[실증 결과](docs/paper/06_evaluation_and_results.md) ·
[설치·운영](README.en.md) · [전체 문서](docs/README.md)

![기존 실험실을 멀티에이전트 기반으로 전환하는 AX4LAB](docs/assets/presentation/laboratory-transformation-sunburst.webp)

## 시스템 기여

설계 → 제작 → 관측·이송 → 시험 → 분석 → 지식·최적화 → 다음 설계를 연결합니다.
각 에이전트의 판단층은 근거를 검토하고 도구를 선택하며, 실제 수치 계산과 장비
실행은 기존 전문 도구와 브릿지가 담당합니다. 신규 BO·VLA·FEM 알고리즘 자체가
아니라 이들을 실험에 연결하는 시스템 구성이 핵심입니다.

## 실증 범위

저장된 감독하 혼합 모드 사이클에서 실제 시험, 시험 후 정리, Analysis,
BO 관리 LHS 갱신, 다음 Design 진입을 확인했습니다. 해당 실행에서는 프린팅
적층을 생략했고 시편 동일성을 독립적으로 확인하지 않았습니다.
압축시험은 현재 실증 사례이며 플랫폼 전체의 적용 범위를 정의하지 않습니다.

## 플랫폼과 상세 문서

| 알아볼 내용 | 문서 |
|---|---|
| 에이전트별 역할·판단·툴·API | [에이전트 문서](docs/agents/README.md) |
| 장비별 통신과 실행 경계 | [디바이스 브릿지](docs/device_bridges/README.md) |
| 시스템 구조 | [System architecture](docs/paper/02_system_architecture.md) |
| 확장 가능한 플랫폼 | [Platform architecture](docs/paper/04_platform_architecture.md) |
| 실행 그래프와 워크스페이스 | [Runtime IDE](docs/runtime/runtime_ide.md) |
| 실증 산출물과 재현 | [Results](docs/paper/06_evaluation_and_results.md) · [Reproducibility](docs/paper/07_reproducibility.md) |
| 설치·운영 | [사용자 매뉴얼](docs/tutorials/user_manual.ko.md) |
| 운영 조건과 한계 | [Limitations](docs/paper/08_safety_ethics_and_limitations.md) |

상세 문서는 영문을 기준으로 유지합니다. 인용 정보는 [CITATION.cff](CITATION.cff),
이용 조건은 [LICENSE](LICENSE)를 참고하십시오.
