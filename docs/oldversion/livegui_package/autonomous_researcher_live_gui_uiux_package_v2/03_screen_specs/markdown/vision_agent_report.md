# Vision Agent Report

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

- Agent ID: `vision`
- Reference image: [archived screen mockup](../../00_references/generated_full_screens/04_vision_agent_report.png)

## Sections
- `camera_health`
- `calibration_summary`
- `confidence_distribution`
- `inspection_feed`
- `segmentation`
- `defect_summary`
- `pose_estimation`
- `confusion_matrix`
- `quality_metrics`
- `evidence_review`
- `handoff_recommendations`

## Primary visualizations
- image overlays
- histogram
- calibration line chart
- segmentation panels
- confusion matrix

## Build notes
- Use `Report` view for operator-facing information.
- Use `Backend` view for raw trace and JSON.
- Keep 1920x1080 no-overlap as the target audit viewport.
