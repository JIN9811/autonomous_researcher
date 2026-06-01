# Implementation Mapping

이 패키지는 기존 `/live` 구조를 갈아엎는 용도가 아니라, 현재 `planning.html`, `planning.js`, `styles.css`에 점진적으로 이식하기 위한 UI/UX asset bundle이다.

## Recommended first patch

1. `01_design_tokens/design_tokens.css`의 CSS variables를 `web/static/styles.css` Live GUI section 상단에 병합한다.
2. `02_components/css_snippets/live_gui_theme_patch.css`에서 필요한 class만 기존 `.live-*`, `.planning-chat-*` class에 매핑한다.
3. `03_screen_specs/json/*.json`을 기준으로 `renderAgentReport(agentId, report)`의 section registry를 만든다.
4. `04_data_contracts/json_schema/live_chat_message.v1.schema.json`을 기준으로 `normalizePlanningMessage()`와 `renderLiveChatMessageV1()`를 만든다.
5. `00_references/generated_full_screens/*.png`는 구현 중 visual target으로 사용한다.

## Existing files to touch

- `web/templates/planning.html`: layout shell, class 추가, action menu 위치 정리.
- `web/static/planning.js`: renderer 분리, agent section registry, message normalization.
- `web/static/styles.css`: tone down, tokens, card/chip/chat/dock style.
- `app/controller.py`: structured `live_chat_message.v1` emit 보장.
- `app/main.py`: agent report payload common sections 확장.

## Safety rule

`SAFE STOP`, approval, Guardian gate, live hardware action guard는 decorative UI가 아니라 실제 control logic과 연결해야 한다.
