# Bayesian Optimization Agent Report

> Archived development material (archive context clarified 2026-09-29). The original instructions, example values and visual targets below are historical, not current runtime requirements or measured evidence. See the [archive index](../../../../README.md) for maintained replacements.

- Agent ID: `bo`
- Reference image: [archived screen mockup](../../00_references/generated_full_screens/08_bayesian_optimization_agent_report.png)

## Sections
- `optimization_goal`
- `iterations`
- `best_observed`
- `current_regret`
- `surrogate_model`
- `acquisition_function`
- `convergence_history`
- `objective_space`
- `stop_continue_recommendation`
- `acquisition_breakdown`
- `parameter_importance`
- `parallel_coordinates`
- `candidate_queue`
- `uncertainty_map`
- `recent_evaluations`
- `artifacts`

## Primary visualizations
- convergence line chart
- pareto scatter
- acquisition donut
- parameter importance bars
- parallel coordinates
- uncertainty heatmap

## Build notes
- Use `Report` view for operator-facing information.
- Use `Backend` view for raw trace and JSON.
- Keep 1920x1080 no-overlap as the target audit viewport.
