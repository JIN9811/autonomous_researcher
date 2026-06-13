# Live GUI Upgrade

이 폴더는 `/live` 화면을 더 상용품다운 운영 콘솔로 고도화하기 위한 개선안 초안 모음이다.

## 문서

- `01_orc_one_page_briefing_upgrade.md`
  - ORC 리포트를 한 페이지 안에서 읽히는 지휘관 브리핑 화면으로 재구성하는 제안서.
  - 현재 코드와 최근 test run `run-20260612T161643Z-6aab68`에서 확인된 payload를 기준으로 작성했다.
  - Build Web Data Visualization 플러그인의 운영형 시각화 원칙과 외부 dashboard/data visualization 자료를 반영했다.

## 전제

- 아직 구현 단계가 아니다.
- 목표는 더 많은 raw card를 추가하는 것이 아니라, backend state를 프론트엔드 계층에서 요약, 계층화, 시각화하는 것이다.
- ORC 화면은 개별 agent report가 아니라 mission commander briefing이어야 한다.
