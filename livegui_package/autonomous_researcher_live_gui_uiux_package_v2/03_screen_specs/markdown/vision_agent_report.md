# Vision Agent Report

- Agent ID: `vision`
- Reference image: `../00_references/generated_full_screens/04_vision_agent_report.png`

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
