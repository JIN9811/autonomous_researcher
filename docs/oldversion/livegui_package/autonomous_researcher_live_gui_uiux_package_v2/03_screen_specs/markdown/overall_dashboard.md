# Overall Live GUI Layout

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

- Agent ID: `orchestrator`
- Reference image: [archived screen mockup](../../00_references/generated_full_screens/00_overall_live_gui_layout.png)

## Sections
- `top_mission_bar`
- `agent_rail`
- `orchestrator_report`
- `operator_console_chat`
- `bottom_dock`

## Primary visualizations
- stage progress
- decision donut
- route graph
- device health bars
- artifact strip

## Build notes
- Use `Report` view for operator-facing information.
- Use `Backend` view for raw trace and JSON.
- Keep 1920x1080 no-overlap as the target audit viewport.
