# Overall Live GUI Layout

- Agent ID: `orchestrator`
- Reference image: `../00_references/generated_full_screens/00_overall_live_gui_layout.png`

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
