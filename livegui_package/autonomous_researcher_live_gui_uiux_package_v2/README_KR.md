# Autonomous Researcher Live GUI — UI/UX Package v2

이 패키지는 한 장짜리 레퍼런스 이미지가 아니라, 실제 구현에 바로 분해해서 쓸 수 있도록 나눈 UI/UX 패키지다.

## 포함 내용

```text
00_references/
  user_supplied/                         원본 Live GUI 캡처, 대시보드 레퍼런스, 개선안 md
  generated_full_screens/                전체 레이아웃 + agent별 보고서 + UI/UX board 원본 PNG
  component_crops_from_design_system/    color, typography, buttons, forms, chart 등 UI kit crop
  layout_crops_from_overall/             top bar, agent rail, center report, chat, dock 등 layout crop
01_design_tokens/
  design_tokens.json                     색상/타이포/spacing/radius/layout token
  design_tokens.css                      바로 styles.css에 병합 가능한 CSS variables + 기본 class
02_components/
  specs/                                 컴포넌트별 구현 명세 Markdown
  html_snippets/                         컴포넌트별 HTML skeleton
  css_snippets/                          Live GUI theme patch CSS
03_screen_specs/
  json/                                  agent별 screen registry JSON
  markdown/                              agent별 화면 구성 설명
04_data_contracts/
  json_schema/                           live_chat_message.v1, agent_report_page.v1 등 JSON schema
05_generation_prompts/                   각 레퍼런스 이미지 생성 prompt
06_implementation_guides/                실제 코드 반영 순서와 planning.js renderer plan
07_preview/index.html                    로컬에서 패키지 전체를 훑는 HTML preview
manifest.json                            전체 파일 manifest
```

## 먼저 볼 파일

1. `07_preview/index.html`
2. `00_references/REFERENCE_INDEX.md`
3. `01_design_tokens/design_tokens.css`
4. `06_implementation_guides/implementation_mapping.md`
5. `06_implementation_guides/first_patch_checklist.md`

## 구현에 바로 쓰는 순서

1. `design_tokens.css`의 `:root` token을 기존 `web/static/styles.css` Live GUI section에 병합한다.
2. `02_components/specs/*.md`를 기준으로 기존 DOM ID는 유지하고 class만 추가한다.
3. `03_screen_specs/json/*.json`으로 `AGENT_REPORT_SECTIONS` registry를 만든다.
4. `04_data_contracts/json_schema/live_chat_message.v1.schema.json`으로 chat renderer를 정규화한다.
5. `00_references/generated_full_screens/*.png`와 `layout_crops_from_overall/*.png`를 implementation visual target으로 쓴다.

## 포함된 전체 화면 레퍼런스

- `00_overall_live_gui_layout.png`
- `01_orchestrator_agent_report.png`
- `02_design_agent_report.png`
- `03_specimen_making_agent_report.png`
- `04_vision_agent_report.png`
- `05_manipulation_agent_report.png`
- `06_lab_equipment_agent_report.png`
- `07_analysis_agent_report.png`
- `08_bayesian_optimization_agent_report.png`
- `09_uiux_design_system_board.png`

## 포함된 사용자 레퍼런스

- `00_current_live_gui_original.png`
- `01_dashboard_style_reference_hiring_overview.png`
- `02_live_gui_upgrade_plan.md`

## 주의

- 이 패키지는 UI/UX 구현용 asset/spec bundle이다.
- 실제 hardware action, approval, Guardian gate는 반드시 기존 backend guard와 연결해야 한다.
- Report view에는 raw JSON/prompt/traceback을 직접 노출하지 않고, Backend Trace view로 분리한다.
