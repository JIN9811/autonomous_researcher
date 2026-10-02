# Lab Equipment Agent Report

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

- Agent ID: `equipment`
- Reference image: [archived screen mockup](../../00_references/generated_full_screens/06_lab_equipment_agent_report.png)

## Sections
- `equipment_readiness`
- `live_test_status`
- `load_displacement_preview`
- `test_recipe`
- `sensor_channels`
- `environmental_conditions`
- `safety_interlocks`
- `event_log`
- `control_approval`

## Primary visualizations
- readiness gauges
- load-displacement chart
- sensor sparklines
- temperature/humidity mini charts
- safety checklist

## Build notes
- Use `Report` view for operator-facing information.
- Use `Backend` view for raw trace and JSON.
- Keep 1920x1080 no-overlap as the target audit viewport.
