# Orchestrator Agent Report

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

- Agent ID: `orchestrator`
- Reference image: [archived screen mockup](../../00_references/generated_full_screens/01_orchestrator_agent_report.png)

## Sections
- `mission_contract`
- `route_state`
- `missing_inputs`
- `decision_register`
- `followup_questions`
- `approval_summary`
- `risk_register`
- `task_queue`
- `next_action`

## Primary visualizations
- route graph
- decision donut
- stage progress
- task queue table

## Build notes
- Use `Report` view for operator-facing information.
- Use `Backend` view for raw trace and JSON.
- Keep 1920x1080 no-overlap as the target audit viewport.
