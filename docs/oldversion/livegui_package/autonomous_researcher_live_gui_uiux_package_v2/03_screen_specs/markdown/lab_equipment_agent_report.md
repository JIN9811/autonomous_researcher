# Lab Equipment Agent Report

- Agent ID: `equipment`
- Reference image: `../00_references/generated_full_screens/06_lab_equipment_agent_report.png`

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
