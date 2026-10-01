# Manipulation Agent Report

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

- Agent ID: `manipulation`
- Reference image: [archived screen mockup](../../00_references/generated_full_screens/05_manipulation_agent_report.png)

## Sections
- `success_metrics`
- `grasp_plan`
- `waypoint_sequence`
- `motion_execution`
- `robot_workspace`
- `reachability_map`
- `collision_safety`
- `object_pose_handoff`
- `motion_trajectory`
- `reaction_timeline`
- `camera_views`
- `key_artifacts`

## Primary visualizations
- robot workspace
- trajectory line chart
- reachability heatmap
- grasp score donut
- camera thumbnails

## Build notes
- Use `Report` view for operator-facing information.
- Use `Backend` view for raw trace and JSON.
- Keep 1920x1080 no-overlap as the target audit viewport.
