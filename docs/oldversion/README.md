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
summary: Previous development history and retired assets, separated from current implementation references.
related_docs:
  - docs/README.md
  - docs/standards/documentation_standard.md
  - docs/agents/README.md
supersedes: []
---

# Old Version Documentation Index

## Summary

Current code is the implementation baseline. This folder preserves previous
designs, implementation plans, iteration records and retired reference assets.
Archived instructions are not the current interface, runtime or acceptance
contract, even when their historical status says approved or completed.

## Scope

- Current descriptions remain in the Agent, Bridge, Runtime and Modularity references.
- Prior development processes belong here, rather than in current reading paths.
- Scientific evidence and reproduction artifacts remain separately accessible;
  archiving an implementation proposal does not discard its measurements.
- Working runtime code, equipment settings and installed package assets are not
  moved merely because their names or contents look similar.
- Private local outputs belong in the Git-ignored root `oldversion/`, not here.

## Archived Material

The former Live GUI visual-reference baseline is owner-retired, not an active
style specification. Its bundle and historical alignment log are preserved below;
the image-comparison script is removed from the current test tools. Current GUI
contracts and implementation must not use the archived mockups as acceptance criteria.

| Archive date | Original path | Archived path | Reason | Current replacement |
|---|---|---|---|---|
| 2026-09-14 | Root `README.en.md` | [Previous operator overview](root/README.en.md) | Redundant English entry removed; previous detailed body retained as history. Former inbound links now lead to the main README. | [Main README](../../README.md), [Documentation Index](../README.md) |
| 2026-09-14 | `docs/superpowers/` | [Design history](superpowers/specs/), [implementation history](superpowers/plans/) | 185 files describing previous development; accepted current code is the baseline, not the preceding process. | [Modularity](../modularity.md), [Runtime IDE](../runtime/runtime_ide.md), [Agents](../agents/README.md), [Bridges](../device_bridges/README.md), [Standards](../standards/documentation_standard.md) |
| 2026-09-14 | Three `docs/ATR_*_Package/` trees | [IDE package](ATR_LangGraph_Runtime_IDE_Codex_Package/), [Live GUI package](ATR_Live_GUI_Graph_Package/), [Evolution package](ATR_Self_Evolution_Package/) | 134 historical instruction and visual-reference assets; not current installed device/agent packages. Preserve original bundle context. | [Runtime IDE](../runtime/runtime_ide.md), [Live GUI contracts](../gui/reference/live_gui_reference_alignment.md), [Self Evolution](../runtime/self_evolution.md) |
| 2026-09-14 | `docs/system/`, `docs/strategy/`, `docs/gui/history/`, `개선안/` | [System prompts](system/), [strategy history](strategy/), [GUI history](gui/history/), [improvement proposals](개선안/) | 30 files of earlier instructions, proposals and development steps. Their old model assumptions and UI plans do not govern current execution. | [Documentation Index](../README.md), [Agents](../agents/README.md), [Bridges](../device_bridges/README.md), [Modularity](../modularity.md) |
| 2026-09-14 | `livegui_package/` and the historical body of `docs/gui/reference/live_gui_reference_alignment.md` | [Reference bundle](livegui_package/autonomous_researcher_live_gui_uiux_package_v2/README.md), [alignment history](gui/live_gui_reference_alignment.md) | Owner confirmed the former visual baseline is unused. Retired its pixel-comparison test; keep history and self-contained assets together, outside current reading and test paths. | [Live GUI Runtime Contracts](../gui/reference/live_gui_reference_alignment.md), [Agent References](../agents/README.md); current `web/` implementation |
| 2026-08-09 | `docs/github_docs_image/autonomous_researcher_gpt_image_schematics/` | `docs/oldversion/github_docs_image/autonomous_researcher_gpt_image_schematics/` | 활성 inbound reference가 없고, 편집 불가능한 GPT 생성 PNG 묶음이 현재 에이전트 문서 피겨로 대체됨 | [Agent Reference Index](../agents/README.md), [`docs/agents/assets/figures/`](../agents/assets/figures/) |
| 2026-09-11 | `docs/knowledge/knowledge_graph_operations.ko.md` | [knowledge/knowledge_graph_operations.ko.md](knowledge/knowledge_graph_operations.ko.md) | Knowledge graph/Neo4j 운영 경로가 2026-09-10 종료되고 Markdown 운영 가이드로 대체됨. 실행 코드·패키지 소비 없음; 활성 탐색은 대체물로, 과거 설계·계획 경로는 보관본으로 갱신. 운영 절차 문서만 이동하며 구현·Evidence·원본 데이터는 보존 | [Markdown Knowledge 운영 가이드](../knowledge/markdown_memory_operations.ko.md) |

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
