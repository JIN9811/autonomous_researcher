# Specimen Making Agent Report

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

- Agent ID: `specimen`
- Reference image: [archived screen mockup](../../00_references/generated_full_screens/03_specimen_making_agent_report.png)

## Sections
- `slicer_configuration`
- `printer_profile`
- `build_queue`
- `estimated_print_time`
- `filament_usage`
- `gcode_validation`
- `print_readiness`
- `build_timeline`
- `layer_preview`
- `artifact_ledger`
- `printer_status`
- `handoff_status`

## Primary visualizations
- layer preview
- material donut
- readiness donut
- timeline bars
- print-time bars

## Build notes
- Use `Report` view for operator-facing information.
- Use `Backend` view for raw trace and JSON.
- Keep 1920x1080 no-overlap as the target audit viewport.
