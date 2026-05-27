# System Instruction Docs

이 폴더는 **운영 설명 문서에서 제외**한 시스템 지시/프롬프트 자료만 보관합니다.

## 목적
- Codex/LangGraph/GUI 실행 지시문
- 테스트/개발을 위한 내부 프롬프트
- 패키지 단위 구현 의사결정 근거 보조 자료

## 포함 문서

- `ATR_LangGraph_Runtime_IDE_Codex_Instructions.txt`
  - LangGraph Runtime IDE 구현 지시
- `ATR_Live_GUI_and_LangGraph_Codex_Instructions.txt`
  - Live GUI + 런타임 지시 템플릿
- `ATR_Self_Evolution_Codex_Instructions.txt`
  - Self-Evolution 엔진 지시 템플릿
- `codex_lerobot_robotis_gui_prompt.txt`
  - LeRobot/Robotis GUI 연동용 Codex 프롬프트

## 사용 규칙

- 기본 운영/튜토리얼 문서에서 이 폴더를 직접 링크하지 않는다.
- 운영 절차 문서 작성 시에는 `docs/runtime`, `docs/hardware`, `docs/gui`, `docs/agents`의 공개 문서만 사용한다.
- 이 폴더의 문서를 변경할 때는 레포 루트 브랜치/패키지 변경이 동반되어야 한다.

## 참고

패키지 내부(`ATR_*_Package`)에도 패키지 범위의 지시 문서가 존재할 수 있다. 해당 문서는 패키지 구현 계약의 일부로 유지한다.
