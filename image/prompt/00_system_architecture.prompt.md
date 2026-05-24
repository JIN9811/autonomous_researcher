# Autonomous Researcher End-to-End Runtime 이미지 생성 프롬프트

목표: PPT에 바로 넣을 수 있는 16:9 벡터 기반 시스템 다이어그램을 생성한다.
권장 캔버스: 1920x1080px SVG, 16:9.
글자 크기: 내부 텍스트 최소 14pt 이상. 이 프로젝트 SVG 생성기는 최소 24px로 생성한다.
저장 구조: SVG는 `image/svg/`, PNG 렌더는 `image/rendered/`, 프롬프트는 `image/prompt/`에 둔다.
목표 독자: 박사급 연구자/지도교수 대상 발표자료에 들어갈 수 있는 academic figure 톤으로 만든다.
발표용 fig 스타일: 순백색 배경, 얇은 선, 낮은 채도, 절제된 색 구분, 그림자/장식 배제, 충분한 여백, 큰 글씨를 사용한다.
레이아웃 제약: 모든 텍스트는 카드/패널 내부에 들어가야 하며, 캔버스나 둥근 카드 밖으로 넘치면 안 된다.
줄바꿈 규칙: 긴 목록은 세로 bullet을 과하게 쌓지 말고 한 줄 요약 또는 2-3줄 이하의 compact list로 배치한다.
여백 규칙: 텍스트와 카드 경계 사이에는 최소 24px 이상의 안쪽 여백을 유지한다.
렌더 검증: SVG 생성 후 `image/.render_venv/bin/python image/render_diagrams.py`로 PNG와 contact sheet를 만든다.
육안검사: `image/rendered/contact_sheet.png`와 원본 PNG를 열어 텍스트 겹침, 카드 밖 이탈, 화살표와 텍스트 충돌을 확인한다.
수정 루프: 육안검사에서 문제가 보이면 prompt와 diagram_manifest.json 또는 generate_diagrams.py를 수정하고 SVG/PNG/contact sheet를 다시 생성한다.
스타일: 선명한 벡터 라인, 둥근 카드, 명확한 화살표, 과도한 장식 없는 박사급 연구 발표 figure 톤.
업데이트 원칙: 시스템이 바뀌면 이 프롬프트와 image/diagram_manifest.json의 동일 항목을 함께 수정한 뒤 generate_diagrams.py를 다시 실행한다.

핵심 표현:
- 전체 autonomous researcher 시스템 구조를 PPT용 16:9 벡터 다이어그램으로 표현한다. Main GUI, Live GUI, 3DP/Windows/LeRobot device workspaces, agent workflow, NemoClaw/vLLM runtime, tool bridges, memory/logging을 명확히 분리하고 현재 실가동 경로를 화살표로 표시한다.

## Operator/GUI
- Main GUI: run, model, device controls
- Live GUI chat: value intake + workflow trigger
- Device Workspaces: 3DP, Windows, LeRobot
- atr CLI + SSE state snapshots

## Agent Workflow
- Orchestrator
- Design
- Specimen Making
- Vision
- Manipulation
- Lab Equipment
- Analysis
- Knowledge
- Guardian

## Model Runtime
- NemoClaw/vLLM default
- E4B orchestrator, E2B formatter
- 31B deep reasoning on demand
- Ollama optional branch

## Tools/Bridges
- TPMS geometry + STL assets
- PrusaSlicer + PrusaLink short-name start
- Windows PyAutoGUI macros
- LeRobot teleop/record/train/rollout

## Memory/Logs
- ExperimentDB + FailureMemory
- Prusa/Windows/LeRobot connection memory
- Run artifacts: STL, G-code, logs, datasets, policies
- Docs + HybridRAG + session state
