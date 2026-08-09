---
doc_type: index
subtype: index
status: active
authority: navigation
audience:
  - researcher
  - reviewer
  - developer
  - maintainer
scope:
  - archived_documentation
summary: Historical index for unused documentation that has a named current replacement.
related_docs:
  - docs/README.md
  - docs/standards/documentation_standard.md
  - docs/agents/README.md
supersedes: []
---

# Old Version Documentation Index

## Summary

이 폴더는 현재 읽기 경로에서 사용하지 않는 문서와 자산 중 최신 대체물이
확인된 항목만 보관합니다. 여기에 있다는 사실은 삭제 대상이라는 뜻이 아니라,
현재 인터페이스·런타임·운영 절차의 기준으로 사용하면 안 된다는 뜻입니다.

## Scope

- 링크가 적거나 오래됐다는 이유만으로 이동하지 않습니다.
- 구현 Plan, Design, Evidence, 재현성 자료는 참조가 없어도 보관 대상에서
  제외합니다.
- 패키지 매니페스트가 소비하는 문서와 자산은 중복처럼 보여도 이동하지
  않습니다.
- 새 항목은 [Documentation Standard](../standards/documentation_standard.md)의
  archive admission rule을 모두 통과해야 합니다.

## Archived Material

| Archive date | Original path | Archived path | Reason | Current replacement |
|---|---|---|---|---|
| 2026-08-09 | `docs/github_docs_image/autonomous_researcher_gpt_image_schematics/` | `docs/oldversion/github_docs_image/autonomous_researcher_gpt_image_schematics/` | 활성 inbound reference가 없고, 편집 불가능한 GPT 생성 PNG 묶음이 현재 에이전트 문서 피겨로 대체됨 | [Agent Reference Index](../agents/README.md), [`docs/agents/assets/figures/`](../agents/assets/figures/) |

## Restoration

보관 자료가 다시 필요해지면 기존 파일을 직접 수정해 활성 문서처럼 사용하지
않습니다. 대체물과의 차이, 새 소비 경로, 소유 도메인, 검증 기준을 확인한 뒤
활성 경로로 `git mv`하고 이 표의 상태를 갱신합니다. 복원과 관련 참조 갱신은
같은 변경에서 수행합니다.

## Verification

- archive index의 원본·보관·대체 경로가 존재하는지 확인합니다.
- 보관된 패키지 내부 manifest 경로는 archive 위치를 기준으로 계속 해석돼야
  합니다.
- 활성 문서가 `oldversion` 자료를 현재 구현 근거로 참조하지 않는지 확인합니다.

## Related Documents

- [Documentation Index](../README.md)
- [Documentation Standard](../standards/documentation_standard.md)
- [Agent Reference Index](../agents/README.md)
