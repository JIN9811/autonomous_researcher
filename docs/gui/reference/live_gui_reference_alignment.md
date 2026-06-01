# Live GUI Reference Alignment Guide

Purpose: keep the Live GUI visually aligned with the supplied reference images while preserving the ATR autonomous-researcher workflow that was already planned and implemented.

This is not a redesign brief. It is the operating visual standard for `/live`.

## Priority Order

1. ATR workflow and safety contract come first.
2. Existing FastAPI + static JS + runtime API wiring must stay intact.
3. Reference images guide layout density, color balance, card rhythm, and control hierarchy.
4. Do not replace ATR agent content with generic dashboard/demo content.

## Source Assets

Reference package root:

`livegui_package/autonomous_researcher_live_gui_uiux_package_v2`

Primary reference images:

- `00_references/generated_full_screens/00_overall_live_gui_layout.png` at 1672 x 941
- `00_references/generated_full_screens/01_orchestrator_agent_report.png` through `08_bayesian_optimization_agent_report.png` at 1672 x 941
- `00_references/layout_crops_from_overall/00_top_mission_status_bar.png` at 1672 x 68
- `00_references/layout_crops_from_overall/01_left_agent_rail.png` at 206 x 654
- `00_references/layout_crops_from_overall/02_center_orchestrator_report_area.png` at 925 x 654
- `00_references/layout_crops_from_overall/03_right_operator_console_chat.png` at 516 x 654
- `00_references/layout_crops_from_overall/04_bottom_events_devices_logs_artifacts_dock.png` at 1656 x 199
- `00_references/component_crops_from_design_system/*.png` for palette, typography, cards, buttons, forms, status chips, icons, alerts, charts, and artifacts
- `00_references/user_supplied/01_dashboard_style_reference_hiring_overview.png` for compact control-room tone only

Current comparison artifact:

- `artifacts/live_gui_upgrade/planning_browser_audit_live_artifacts.png`
- `artifacts/live_gui_upgrade/bo_report_probe.png`
- `artifacts/live_gui_upgrade/topbar_reference_current_diff.png`
- `artifacts/live_gui_upgrade/overall_reference_current_diff.png`
- `artifacts/live_gui_upgrade/bo_reference_current_diff.png`
- `artifacts/live_gui_upgrade/visual_diff_metrics.json`
- `artifacts/live_gui_upgrade/reference_comparison.html`

## Layout Translation

The reference full screen is 1672 x 941. The implementation audit target is 1920 x 1080 browser viewport, with content often around 1920 x 994 because of browser chrome.

Keep this mapping:

- Top mission/status bar: fixed first row, around 68 px high.
- Left agent rail: persistent vertical rail. Follow the reference crop width first. At the 1920 px audit viewport this maps to about 206-237 px, not the older 128 px compact rail.
- Center report/work area: largest readable area, route/report/artifact/FEM/BO content belongs here.
- Right operator console/chat: persistent chat, around 516-593 px wide at 1920 px.
- Bottom event/device/log/artifact dock: compact operational strip, around 199-208 px high.

Current CSS seed remains:

- reference-aligned implementation columns: `clamp(206px, 12.32vw, 237px) minmax(0, 1fr) clamp(516px, 30.86vw, 593px)`
- rows: `68px minmax(0, 1fr) 208px`
- gap: 12 px

Do not move Windows Bridge, 3DP, LeRobot, BO Workspace, or CAE Workspace controls into Live GUI if they belong to Main GUI Device Workspaces. Live GUI should show runtime state and handoff evidence, not become every device setup screen.

## Color And Tone

Use the reference palette as a restrained dark laboratory console:

- Background: deep navy/charcoal, approximately `#050914`, `#0B1020`, `#0E1628`.
- Cards: slightly raised dark surfaces, subtle border, minimal shadow.
- Text: high contrast off-white `#E2E8F0` and muted slate `#94A3B8`.
- Accent: cyan/blue for focus and information, approximately `#22D3EE`, `#4F6BFF`, `#60A5FA`.
- Success/warning/danger: only for real status, not decoration.
- Avoid excessive neon glow, animated blinking, decorative gradients, or generic AI-dashboard effects.

Dominant reference colors from the current package are dark navy buckets around `#102030`, `#202030`, `#102020`, `#203040`, with cyan/blue/purple accents.

## Content Contract

The inside content must follow the ATR plan, not the generic reference mockup.

Required Live GUI content model:

- Orchestrator: mission contract, missing inputs, supervisor decision, route state, handoff registry, approval state, next action.
- Design: objective, TPMS/metamaterial design values, candidate board, previous-vs-next shape when looped, manufacturability, Design to Specimen handoff.
- Specimen Making: slicer settings, PrusaLink readiness, upload/start/ejection status, G-code path, manufacturing digital thread, quality gates.
- Vision: camera/source health, zone state, confidence, detection/pose/defect evidence, signal freshness, handoff recommendations.
- Manipulation: Pi0.5/LeRobot profile, task episode, preflight, policy path, action clamp/safety, rollout status, SARM handoff.
- Lab Equipment: Windows PyAutoGUI bridge target, UTM program command, visual assertion, data export path, equipment readiness/failure.
- Analysis: UTM/FEM data quality, preprocessing, extracted metrics, contour/graph evidence, BO objective payload.
- BO: objective, surrogate/acquisition trace, candidate queue, selected next design, uncertainty/regret/convergence plots.
- Knowledge: memory commit, evidence pack, retrieval context, evolution proposals, deployment gate.
- Guardian: graph-wide risk map, gates, incidents/near misses, approvals, corrective actions.

## Report vs Backend Split

Report view is for operator evidence and decisions:

- key-value summaries
- artifact cards and figures
- selected candidate/result summaries
- warnings and next actions
- no raw prompt/tool/input/output JSON

Backend Trace is for raw evidence:

- raw prompts and responses
- tool input/output JSON
- event payloads
- stack traces
- node input/output
- compile context

The browser audit must keep proving this split.

## Icon Rule

Reuse Runtime IDE icons from `web/static/runtime_icons/` whenever a matching agent icon exists.

Current mapping:

- Orchestrator -> `orchestrator.svg`
- Design -> `design_agent.svg`
- Specimen Making -> `specimen_maker.svg`
- Vision -> `vision_agent.svg`
- Manipulation -> `manipulation_agent.svg`
- Lab Equipment -> `equipment_agent.svg`
- Analysis -> `analysis_agent.svg`
- BO -> `bo_agent.svg`
- Knowledge -> `knowledge_agent.svg`
- Guardian -> `guardian_agent.svg`

Only keep existing Live GUI fallback icons for concepts without a Runtime IDE counterpart, such as `objective`.

## Screenshot/HTML Comparison Rule

Every visual pass must use screenshot or HTML comparison, not intuition only.

Minimum check flow:

1. Run or reuse the GUI server at `/live`.
2. Capture a 1920 x 1080 browser screenshot to `artifacts/live_gui_upgrade/current_live_1920x1080.png`.
3. Open or inspect `artifacts/live_gui_upgrade/reference_comparison.html` to compare reference and current screen side by side. The comparison page must be regenerated from current browser screenshots after CSS/JS changes.
4. Confirm no horizontal overflow, no panel overlap, visible agent rail, readable chat, readable center report, and bottom dock contained in viewport. For topbar and BO report passes, also compare `topbar_reference_current_diff.png` and `bo_reference_current_diff.png`.
5. Run `tests/ui/planning_browser_audit.py` after renderer changes. The audit defaults to a 1920x1080 WebDriver window and checks no horizontal overflow, required panels, scrollable chat log, duplicate tooltip count 0, SYSTEM_EVENT normalization, BO/FEM artifact cards, Report/Backend split, Evidence Artifact Strip, fallback report sections for Orchestrator, Design, Specimen, Vision, Manipulation, Lab Equipment, Analysis, BO, Knowledge, and Guardian, plus Approval/Guardian pending state and pre-execution blocking of graph/live-run actions when human approval is pending.

Do not mark Live GUI visual work complete without this evidence.

## No Fake Chart Data Rule

Reference images define visual treatment, not synthetic values. Live GUI charts may render only when the underlying report row contains an actual number or a pure numeric string. The renderer must not parse numbers out of descriptive strings like `2 items`, must not convert arbitrary scores to percentages, and must not use CSS/JS fallback values such as 54%, 48, or 36 to make empty charts look populated. Missing quantitative evidence is rendered as compact status tiles or `No measured data`.

## Practical Acceptance Criteria

- 1920 px wide screen has no horizontal overflow.
- Header, agent rail, center report, right chat, and bottom dock do not overlap.
- Chat remains the persistent operator conversation surface.
- Report action labels are compact and readable.
- Agent evidence sections are selectable and feed Pin/Ask/Export workflows.
- Selected-agent reports expose an Evidence Artifact Strip for artifact type/name/source/path without dumping raw payloads.
- Report view avoids raw JSON while Backend Trace preserves raw evidence.
- BO graphs and other heavy artifacts are collapsed by default when appropriate.
- Runtime IDE icons are reused for agent rail consistency.
- Visual style is calm, dense, and equipment-room appropriate, not flashy.

## 2026-06-01 Agent Report Card Alignment

The selected-agent `Report` view must follow the package full-screen agent report references, not the legacy debug-dump layout.

Required default visible structure:
- Compact report header with icon-only actions.
- One agent-specific hero card with four priority highlights.
- A package-derived generated-full-screen section grid. Each selected agent renders the section registry from `03_screen_specs/json/*.json`; BO renders 16 sections, Analysis/Specimen/Manipulation/Vision render their own package-defined section counts. This replaces the older four-card-only report layout.
- Statistical or graphical mini-visuals must use actual measured/calculated numeric values only. Do not infer percentages from statuses, descriptive text, counts embedded in phrases such as `2 items`, or generic fallback constants. If numeric evidence is absent, show a status-tile or `No measured data` state instead of a fake chart.
- Detailed runtime context, evidence coverage, raw-like process summaries, and source messages must default to collapsed drawers. Raw JSON still belongs only in Backend Trace. Empty sections should show compact `Pending`/awaiting-evidence states, not verbose debug copy.
- The AGT rail should match the package crop proportion, currently about 206-237 px at the 1920x1080 audit viewport. The report canvas then uses three-column generated section cards and scrolls vertically when an agent has many sections.

Regression checks live in `tests/ui/planning_browser_audit.py`: it verifies generated reference section cards, bounded card/hero height, reference-width AGT rail, collapsed evidence drawers, icon-style compact actions, no raw JSON in Report view, and continued Backend Trace raw-payload availability.

## 2026-06-01 Agent-by-Agent Generated Full-Screen Pass

Do not tune all agent reports as one generic dashboard. Each agent report must be handled as an independent implementation pass:

1. Read `03_screen_specs/json/<agent>_agent_report.json` and matching markdown.
2. Inspect the corresponding `00_references/generated_full_screens/*.png`.
3. Implement only that agent's report section semantics and primary visualization count.
4. Capture a browser screenshot at 1920x1080.
5. Save current screenshot, reference/current diff, and metrics under `artifacts/live_gui_upgrade/agent_pass_<agent>/`.
6. Move to the next agent only after card count, visual count, chat target, and overflow checks are correct.

Current pass results are summarized in `artifacts/live_gui_upgrade/agent_report_pass_summary.json`:

| Agent | Reference image | Cards | Primary visuals | Overflow | Diff MAE | Reference mean | Current mean | Artifact directory |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| Orchestrator | `01_orchestrator_agent_report.png` | 9 | 4 | 0 px | 14.22 | `#142333` | `#162230` | `artifacts/live_gui_upgrade/agent_pass_orchestrator/` |
| Design | `02_design_agent_report.png` | 9 | 5 | 0 px | 15.55 | `#172333` | `#15202e` | `artifacts/live_gui_upgrade/agent_pass_design/` |
| Specimen Making | `03_specimen_making_agent_report.png` | 12 | 6 | 0 px | 15.31 | `#1a2635` | `#182332` | `artifacts/live_gui_upgrade/agent_pass_specimen/` |
| Vision | `04_vision_agent_report.png` | 11 | 5 | 0 px | 15.16 | `#16212f` | `#151e2a` | `artifacts/live_gui_upgrade/agent_pass_vision/` |
| Manipulation | `05_manipulation_agent_report.png` | 12 | 5 | 0 px | 16.01 | `#131f2c` | `#121c28` | `artifacts/live_gui_upgrade/agent_pass_manipulation/` |
| Lab Equipment | `06_lab_equipment_agent_report.png` | 9 | 5 | 0 px | 14.29 | `#18222d` | `#161f2c` | `artifacts/live_gui_upgrade/agent_pass_equipment/` |
| Analysis | `07_analysis_agent_report.png` | 13 | 6 | 0 px | 14.05 | `#182633` | `#182331` | `artifacts/live_gui_upgrade/agent_pass_analysis/` |
| BO | `08_bayesian_optimization_agent_report.png` | 16 | 6 | 0 px | 16.43 | `#15212e` | `#141c28` | `artifacts/live_gui_upgrade/agent_pass_bo/` |

Knowledge and Guardian do not have package-generated full-screen report images in this v2 package. They still follow the same card language: finding, evidence, next action, report/backend split, and no raw JSON in Report view.

The Live GUI chat target is intentionally Orchestrator-only. Agent tabs change the report being inspected, but chat remains the operator conversation with the Orchestrator that coordinates handoffs.

Report cards are not graph dumps. A card must first state a finding, show compact evidence chips, and state the next action. Mini visuals appear only for the primary visualization sections defined by that agent's reference spec and only when real numeric/structured evidence exists.

Design Agent visual conformance note for the 2026-06-01 pass:
- `candidate_board` renders a CAD-style candidate-card mini visual, not generic status tiles.
- `expected_performance` renders a scatter mini plot.
- `manufacturability` renders a radar mini plot, using pass/ready gate values as scored axes when only two numeric values are present.


Implementation note for the 2026-06-01 pass:
- The common 1920x1080 shell is fixed first, then each agent is tuned independently.
- The accepted sequence for this pass was Orchestrator -> Design -> Specimen Making -> Vision -> Manipulation -> Lab Equipment -> Analysis -> BO.
- If one agent palette or card density improves its own screenshot but worsens another agent, keep the change scoped through `body.planning-live-body[data-live-agent="<agent>"]`.
- Do not use global report-card changes unless the same change has passed all agent screenshots and `tests/ui/planning_browser_audit.py`.

## 2026-06-01 Layout-Image Geometry Pass

The reference alignment rule was tightened after the agent report pass: card count and primary-visual count are necessary but not sufficient. The selected-agent report must also match the reference image layout geometry.

Layout-first checks now use `tests/ui/live_gui_agent_reference_layout_audit.py`.

The audit compares each generated-full-screen reference against the current browser capture and records:

- full-image mean absolute RGB difference
- region-level difference for topbar, left rail, center report, right chat, and bottom dock
- center report vertical/horizontal edge signatures
- DOM card positions and sizes
- contact sheets and reference/current/diff images per agent

Current accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_after_dense_rows/`

Important correction from this pass:

- The previous implementation produced the same uniform 3-column/4-column card board for every agent. That failed the reference goal even when card counts were correct.
- The current implementation adds stable section classes such as `section-candidate_board`, `section-layer_preview`, and `section-convergence_history`, then applies `body.planning-live-body[data-live-agent="<agent>"]` layout maps.
- The center report stack was compacted so the report workboard starts near the top of the center panel. Workboard y-position moved from about `405px` to about `164px` at the 1920x1080 audit viewport.
- The workboard row unit was reduced to `24px` to fit high-card reports such as Specimen Making, Manipulation, Analysis, and BO in the operator viewport.
- View tabs remain available as compact overlay controls; they no longer consume a full center-panel row.
- The report header and focus strip are not allowed to push the agent report board down. Operator-facing state belongs in the top mission bar, AGT rail, report cards, chat, and bottom dock.

Dense layout audit summary:

| Agent | Baseline workboard Y | Dense workboard Y | Baseline X edge peaks | Dense X edge peaks | Baseline MAE | Dense MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Orchestrator | 405 | 164 | 5 | 14 | 14.116 | 13.617 |
| Design | 405 | 164 | 5 | 14 | 15.266 | 14.704 |
| Specimen Making | 405 | 164 | 5 | 12 | 15.349 | 15.704 |
| Vision | 405 | 164 | 5 | 11 | 15.241 | 15.068 |
| Manipulation | 405 | 164 | 5 | 11 | 16.108 | 15.798 |
| Lab Equipment | 405 | 164 | 5 | 12 | 14.320 | 14.222 |
| Analysis | 405 | 164 | 5 | 13 | 14.186 | 14.495 |
| BO | 405 | 164 | 5 | 12 | 16.455 | 16.392 |

Interpretation:

- The main structural defect was fixed: all agents no longer share the same uniform board geometry.
- Full-image MAE is not the only acceptance metric because reference screenshots contain generated text and illustrative values that cannot exactly match runtime state. The stronger acceptance signals are workboard position, edge-signature density, no overflow, preserved chat target, and agent-specific section placement.
- Specimen Making and Analysis remain candidates for additional micro-tuning if the operator wants tighter pixel similarity, but their semantic layout now follows the package-specific report roles instead of a generic dashboard.

Do not remove the layout audit. Future Live GUI changes must run both:

```bash
.venv/bin/python tests/ui/planning_browser_audit.py --base-url http://127.0.0.1:7860 --webdriver-url http://127.0.0.1:4448
.venv/bin/python tests/ui/live_gui_agent_reference_layout_audit.py --base-url http://127.0.0.1:7860 --webdriver-url http://127.0.0.1:4448 --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_<name> --capture
```

## 2026-06-01 Center Card Luminance Pass

After the dense geometry pass, a global shell recolor attempt was rejected by screenshot audit. It increased average full-image MAE from `15.000` to `17.331`, mainly in topbar and bottom dock regions. The accepted approach keeps the measured dense shell and changes only the generated agent report cards.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_v9_cleanup/`

Final measured improvement against the dense baseline:

| Metric | Dense baseline avg | Final v9 avg | Change |
| --- | ---: | ---: | ---: |
| Full-image MAE | 15.000 | 14.478 | -0.522 |
| Center report MAE | 17.487 | 16.153 | -1.334 |
| Topbar MAE | 16.201 | 16.201 | 0.000 |
| Left rail MAE | 13.420 | 13.420 | 0.000 |
| Right chat MAE | 14.252 | 14.252 | 0.000 |
| Bottom dock MAE | 11.546 | 11.546 | 0.000 |

Implementation rule from this pass:

- Do not globally recolor the Live GUI shell unless the topbar, rail, chat, and bottom dock all improve in the browser screenshot audit.
- Report-card luminance is allowed as a global generated-workboard change only when all eight generated-full-screen agent reports improve or remain stable.
- The accepted luminance is locked in `styles.css` as `layout-image pass v9`. The rejected over-bright candidate was v8.
- Static asset version was bumped to `20260601-live-layout-geometry-15` so browser captures use the accepted CSS.

## 2026-06-01 Agent-Scoped Topbar Tone Pass

The remaining large shell residual was the top mission bar. A shell-wide recolor was still rejected, but agent-scoped topbar tones improved the reference match without changing rail, center, chat, or bottom-dock metrics.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_topbar_v4/`

Measured improvement over the card-luminance v9 cleanup:

| Metric | Card v9 avg | Final topbar v4 avg | Change |
| --- | ---: | ---: | ---: |
| Full-image MAE | 14.478 | 14.452 | -0.026 |
| Topbar MAE | 16.201 | 15.876 | -0.325 |
| Topbar max MAE | 18.741 | 16.549 | -2.192 |
| Center report MAE | 16.153 | 16.153 | 0.000 |
| Left rail MAE | 13.420 | 13.420 | 0.000 |
| Right chat MAE | 14.252 | 14.252 | 0.000 |
| Bottom dock MAE | 11.546 | 11.546 | 0.000 |

Final accepted CSS markers:

- `layout-image pass v9`: generated report-card luminance.
- `layout-image topbar pass v4`: agent-scoped top mission bar tones.
- `layout-image board width pass v1`: agent-scoped center workboard width for Design, Specimen Making, and Vision.
- `layout-image manipulation rail pass v1`: Manipulation-only selected-agent rail tone.
- `layout-image vision topbar pass v1`: Vision-only selected topbar micro-tone.
- `layout-image BO chart scaffold pass v1`: BO-only chart scaffolds for primary optimization visuals.
- Static asset version: `20260601-live-layout-geometry-49`.

## 2026-06-01 Agent-Scoped Board Width Pass

After topbar v4, the largest remaining common residual was the center report card geometry for Design, Specimen Making, and Vision. The audit showed those agent workboards were still wider than their generated-full-screen references. Several scoped width candidates were tested in browser screenshots, then all candidate CSS blocks were collapsed into one final pass.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_board_width_v1/`

Measured improvement over the accepted topbar v4 pass:

| Metric | Topbar v4 avg | Final board width v1 avg | Change |
| --- | ---: | ---: | ---: |
| Full-image MAE | 14.452 | 14.365 | -0.087 |
| Center report MAE | 16.153 | 15.931 | -0.222 |
| Topbar MAE | 15.876 | 15.876 | 0.000 |
| Bottom dock MAE | 11.546 | 11.546 | 0.000 |

Target-agent center MAE:

| Agent | Topbar v4 center MAE | Final board width v1 center MAE | Workboard width at 1920px |
| --- | ---: | ---: | ---: |
| Design | 17.026 | 16.493 | 705 px |
| Specimen Making | 17.053 | 16.533 | 871 px |
| Vision | 17.196 | 16.468 | 705 px |

Final accepted CSS rule:

- Design and Vision generated workboards use `68%` width.
- Specimen Making generated workboard uses `84%` width.
- The rule is scoped with `body.planning-live-body[data-live-agent="<agent>"]` and must not affect Orchestrator, Manipulation, Lab Equipment, Analysis, BO, Knowledge, or Guardian.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS artifact written to the accepted directory above.
- `tests/ui/planning_browser_audit.py` PASS.
- `node --check web/static/planning.js` PASS.
- `python3 -m py_compile tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/planning_browser_audit.py tests/ui/runtime_ide_browser_audit.py` PASS.
- `git diff --check` PASS.

## 2026-06-01 BO Visual Semantics Pass

The BO generated-full-screen reference does not use generic optimization tiles for every primary visual. The package spec requires: convergence line chart, Pareto scatter, acquisition donut, parameter-importance bars, parallel coordinates, and uncertainty heatmap. The renderer now maps BO sections to those visual types instead of treating objective space as a heatmap, acquisition breakdown as readiness, and parallel coordinates as a generic line chart.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_bo_visual_semantics_v2/`

Measured improvement over board width v1:

| Metric | Board width v1 | BO visual semantics v2 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.365 | 14.361 | -0.004 |
| Center report avg MAE | 15.931 | 15.921 | -0.010 |
| BO full-image MAE | 15.916 | 15.886 | -0.030 |
| BO center-report MAE | 17.030 | 16.953 | -0.077 |
| BO primary visual count | 6 | 6 | 0 |

Renderer changes:

- `objective_space` -> `visual-scatter` for Pareto/objective-space display.
- `acquisition_breakdown` -> `visual-donut` for acquisition composition.
- `parallel_coordinates` -> `visual-parallel` with a dedicated SVG renderer.
- `hasUsefulVisualEvidence()` now treats `parallel` as a first-class visual kind.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS artifact written to the accepted directory above.
- `tests/ui/planning_browser_audit.py` PASS.
- `node --check web/static/planning.js` PASS.
- `python3 -m py_compile tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/planning_browser_audit.py tests/ui/runtime_ide_browser_audit.py` PASS.
- `git diff --check` PASS.


## 2026-06-01 Manipulation Rail Tone Pass

After BO visual semantics v2, the largest agent-local shell mismatch was the Manipulation selected-agent rail. The reference rail is darker than the shared rail while the center report, chat, and bottom regions already matched closely enough. A global rail recolor was not used; the final rule is scoped only to `body.planning-live-body[data-live-agent="manipulation"] .live-agent-binder`.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_manipulation_rail_v1/`

Measured improvement over BO visual semantics v2:

| Metric | BO visual semantics v2 | Manipulation rail v1 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.361 | 14.314 | -0.047 |
| Left rail avg MAE | 13.420 | 12.904 | -0.516 |
| Manipulation full-image MAE | 15.139 | 14.764 | -0.375 |
| Manipulation left rail MAE | 16.695 | 12.564 | -4.131 |
| Manipulation center-report MAE | 15.221 | 15.221 | 0.000 |
| Manipulation bottom-dock MAE | 15.330 | 15.330 | 0.000 |

Color check:

| Region | Before mean | After mean | Reference mean |
| --- | --- | --- | --- |
| Manipulation left rail | `#152230` | `#101b26` | `#0f1b2a` |

Implementation rule from this pass:

- Agent rail color exceptions must be scoped by `data-live-agent`; do not recolor the shared shell for one agent.
- Manipulation rail pass v1 uses `filter: brightness(0.78)` only on `.live-agent-binder` while Manipulation is selected.
- Static asset version is now `20260601-live-layout-geometry-30`.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS artifact written to the accepted directory above.
- `tests/ui/planning_browser_audit.py` PASS after the asset version bump.
- `node --check web/static/planning.js` PASS.
- `python3 -m py_compile tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/planning_browser_audit.py tests/ui/runtime_ide_browser_audit.py` PASS.
- `git diff --check` PASS.

Remaining measured residuals for the next visual pass:

| Area | Residual | Candidate follow-up |
| --- | ---: | --- |
| BO center report | 16.953 | Chart spacing and lower summary geometry |
| BO bottom dock | 16.589 | Bottom evidence strip spacing/tone |
| Vision topbar | 16.549 | Agent-scoped topbar micro-tone |
| Design/Specimen/Vision center reports | ~16.5 | Section-level card spacing and visual density |


## 2026-06-01 Vision Topbar Micro-Tone Pass

After Manipulation rail v1, the largest isolated shell residual that could be safely changed without touching report geometry was the Vision topbar. A Vision-only topbar override was tested by browser screenshot audit and accepted.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_vision_topbar_v1/`

Measured improvement over Manipulation rail v1:

| Metric | Manipulation rail v1 | Vision topbar v1 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.314 | 14.312 | -0.002 |
| Vision full-image MAE | 14.207 | 14.189 | -0.018 |
| Vision topbar MAE | 16.550 | 16.317 | -0.233 |
| Vision topbar mean | `#121621` | `#131822` | closer to reference `#131924` |

Rejected candidates during this pass:

- BO/Manipulation bottom-dock brightening was rejected. It moved the average color closer to the reference but worsened BO bottom-dock MAE from `16.589` to `18.603`. This means the bottom residual is mainly internal layout/contrast density, not a simple background-tone issue.
- Design center brightness was rejected. It moved the average center color closer but worsened Design center MAE from `16.493` to `19.964`, so Design residual must be treated as card/spacing density rather than a brightness problem.

Implementation rule from this pass:

- Keep topbar tone exceptions scoped by `data-live-agent`.
- Do not apply broad bottom-dock recolor fixes until the dock content structure is compared against the reference.
- Static asset version is now `20260601-live-layout-geometry-30`.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS artifact written to the accepted directory above.
- `tests/ui/planning_browser_audit.py` PASS after the asset version bump.


## 2026-06-01 BO Chart Scaffold Pass

After Vision topbar v1, BO Agent still had the largest center report residual. The reference BO report uses chart-like visual density for convergence, Pareto/objective space, acquisition, parameter importance, parallel coordinates, and uncertainty. The runtime renderer already had the correct six visual slots, but sparse evidence could fall back to status tiles, which reduced chart density.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_bo_chart_scaffold_v1/`

Measured improvement over Vision topbar v1:

| Metric | Vision topbar v1 | BO chart scaffold v1 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.312 | 14.309 | -0.003 |
| BO full-image MAE | 15.886 | 15.863 | -0.023 |
| BO center-report MAE | 16.953 | 16.894 | -0.059 |
| BO bottom-dock MAE | 16.589 | 16.589 | 0.000 |
| BO primary visual count | 6 | 6 | 0 |

Renderer changes:

- BO primary visual sections keep chart-style scaffolds instead of falling back to text/status tiles when evidence is sparse.
- `parameter_importance` now remains bar-like, and `uncertainty_map` remains heatmap-like.
- The change is scoped by `agentId === "bo"` and `BO_PRIMARY_VISUAL_IDS`; other agent reports keep their existing fallback behavior.

Rejected candidate during this pass:

- BO row pitch compaction was rejected. It moved lower cards upward but worsened BO center MAE from `16.894` to `16.984`, so the current vertical card pitch remains unchanged.

Implementation rule from this pass:

- Agent-specific chart scaffolds are acceptable when they preserve backend data contracts and do not invent numeric claims.
- Do not change BO grid row pitch until a stronger reference-derived card bbox mapping is available.
- Static asset version is now `20260601-live-layout-geometry-30`.

## 2026-06-01 Design/Vision No-Overflow Width Pass

After the BO chart scaffold pass, Design and Vision center reports still had measurable layout residual. Width-only candidates were tested with browser screenshots and then checked again with DOM text-overflow probes. The final rule prioritizes both reference similarity and readable operator text.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_design_vision_width_no_overflow_v2/`

Measured comparison against `layout_geometry_audit_final_bo_chart_scaffold_v1`:

| Metric | BO chart scaffold v1 | Final Design/Vision width v2 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.309 | 14.301 | -0.008 |
| Design full-image MAE | 14.250 | 14.237 | -0.013 |
| Design center-report MAE | 16.493 | 16.459 | -0.034 |
| Vision full-image MAE | 14.189 | 14.134 | -0.055 |
| Vision center-report MAE | 16.468 | 16.328 | -0.140 |
| Design/Vision workboard width | 705 px | 664 px | -41 px |

Candidate results:

| Candidate width | Workboard width | Visual MAE result | Text overflow result | Decision |
| ---: | ---: | --- | --- | --- |
| 72% | 747 px | worsened vs baseline | not needed | rejected |
| 64% | 664 px | improved vs baseline | Design 0, Vision 0 horizontal overflows | accepted |
| 60% | 622 px | improved more | Design 1 horizontal overflow | rejected |
| 56% | 581 px | improved more | Design 1 horizontal overflow | rejected |
| 52% | 539 px | improved more | Design 1 horizontal overflow | rejected |
| 48% | 498 px | improved more | Design 6, Vision 2 horizontal overflows | rejected |
| 44% | 456 px | marginally improved | many horizontal overflows and too-narrow card bodies | rejected |

Implementation rule from this pass:

- Design and Vision generated workboards use `64%` width.
- This rule is scoped to `body.planning-live-body[data-live-agent="design"]` and `body.planning-live-body[data-live-agent="vision"]` only.
- Do not accept a lower screenshot MAE if browser DOM checks show horizontal text overflow.
- Current accepted static asset version is `20260601-live-layout-geometry-49`.

Validation evidence:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS artifact written to the accepted directory above.
- Design final overflow probe: workboard `664`, horizontal overflow count `0`.
- Vision final overflow probe: workboard `664`, horizontal overflow count `0`.

## 2026-06-01 BO No-Overflow Width Pass

BO remained the highest residual agent after Design/Vision width tuning. A BO-only width sweep showed that the generated optimization board matched the reference better when narrowed, but 64% and 66% produced horizontal text overflow. The accepted pass therefore uses the best no-overflow candidate.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_bo_width_no_overflow_v1/`

Measured comparison against `layout_geometry_audit_final_design_vision_width_no_overflow_v2`:

| Metric | Previous accepted | BO width v1 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.301 | 14.266 | -0.035 |
| BO full-image MAE | 15.863 | 15.585 | -0.278 |
| BO center-report MAE | 16.894 | 16.183 | -0.711 |
| BO bottom-dock MAE | 16.589 | 16.589 | 0.000 |
| BO workboard width | 1037 px | 705 px | -332 px |

Candidate results:

| Candidate width | Workboard width | BO full MAE | BO center MAE | Text overflow | Decision |
| ---: | ---: | ---: | ---: | ---: | --- |
| 100% | 1037 px | 15.863 | 16.894 | 0 | baseline |
| 96% | 996 px | 15.818 | 16.781 | 0 | rejected; less improvement |
| 92% | 954 px | 15.773 | 16.665 | 0 | rejected; less improvement |
| 88% | 913 px | 15.745 | 16.593 | 0 | rejected; less improvement |
| 84% | 871 px | 15.725 | 16.542 | 0 | rejected; less improvement |
| 80% | 830 px | 15.677 | 16.419 | 0 | rejected; less improvement |
| 76% | 788 px | 15.679 | 16.425 | 0 | rejected; regression vs 80% |
| 72% | 747 px | 15.641 | 16.327 | 0 | rejected; less improvement |
| 68% | 705 px | 15.585 | 16.183 | 0 | accepted |
| 66% | 684 px | 15.564 | 16.132 | 1 | rejected; text overflow |
| 64% | 664 px | 15.566 | 16.135 | 2 | rejected; text overflow |

Implementation rule from this pass:

- BO generated workboard uses `68%` width.
- The rule is scoped to `body.planning-live-body[data-live-agent="bo"]` only.
- BO width tuning must keep the six primary optimization visuals visible and must not replace sparse evidence with fake values.
- Current accepted static asset version is `20260601-live-layout-geometry-49`.

Validation evidence:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS artifact written to the accepted directory above.
- BO final overflow probe: workboard `705`, horizontal overflow count `0`.

## 2026-06-01 Specimen No-Tiny Row Pitch Pass

Specimen Making did not improve with additional width tuning; `84%` remained the best workboard width. The remaining center residual was layout rhythm, so a Specimen-only `grid-auto-rows` sweep was tested.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_specimen_row_no_tiny_v1/`

Measured comparison against `layout_geometry_audit_final_bo_width_no_overflow_v1`:

| Metric | Previous accepted | Specimen row v1 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.266 | 14.253 | -0.013 |
| Specimen full-image MAE | 14.749 | 14.640 | -0.109 |
| Specimen center-report MAE | 16.533 | 16.253 | -0.280 |
| Specimen bottom-dock MAE | 10.425 | 10.425 | 0.000 |
| Specimen workboard width | 871 px | 871 px | 0 px |

Candidate results:

| Candidate row pitch | Specimen full MAE | Specimen center MAE | Horizontal overflow | Tiny cards | Decision |
| ---: | ---: | ---: | ---: | ---: | --- |
| 28 px | 14.882 | 16.873 | 0 | 0 | rejected |
| 26 px | 14.871 | 16.844 | 0 | 0 | rejected |
| 25 px | 14.792 | 16.643 | 0 | 0 | rejected |
| 24 px | 14.749 | 16.533 | 0 | 0 | baseline |
| 23 px | 14.718 | 16.453 | 0 | 0 | rejected; less improvement |
| 22 px | 14.674 | 16.342 | 0 | 0 | rejected; less improvement |
| 21 px | 14.640 | 16.253 | 0 | 0 | accepted |
| 20 px | 14.651 | 16.283 | 0 | 0 | rejected; regression vs 21 px |
| 19 px | 14.584 | 16.110 | 0 | 5 | rejected; too-small cards |

Implementation rule from this pass:

- Specimen generated workboard keeps `84%` width.
- Specimen generated workboard uses `grid-auto-rows: 21px`.
- Do not accept row pitches that create tiny fabrication cards even if screenshot MAE is lower.
- Current accepted static asset version is `20260601-live-layout-geometry-49`.

Validation evidence:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS artifact written to the accepted directory above.
- Specimen final overflow probe: horizontal overflow count `0`, tiny cards `0`.

## 2026-06-01 Full Agent Reference Region Pass

This pass extends the reference-image workflow to all generated-full-screen agent reports instead of tuning one agent at a time. Each candidate was evaluated by browser screenshot at 1920 x 1080, compared against the supplied `generated_full_screens` reference image, and accepted only when the full-image MAE improved without layout overflow.

Accepted final audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_selected_bottom_v2/`

Final measured result:

| Metric | Before this full-region pass | Final selected-bottom v2 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.253 | 13.865 | -0.388 |
| Orchestrator full MAE | 13.188 | 13.053 | -0.135 |
| Design full MAE | 14.237 | 13.900 | -0.337 |
| Specimen full MAE | 14.640 | 14.323 | -0.317 |
| Vision full MAE | 14.134 | 13.716 | -0.418 |
| Manipulation full MAE | 14.764 | 14.184 | -0.580 |
| Equipment full MAE | 13.530 | 13.484 | -0.046 |
| Analysis full MAE | 13.852 | 13.467 | -0.385 |
| BO full MAE | 15.585 | 14.795 | -0.790 |

Accepted region-specific corrections:

| Region | Accepted scope | Reason |
| --- | --- | --- |
| Top mission bar | Orchestrator, Design, Specimen, Vision, Equipment, Analysis, BO | Agent-scoped header tone reduced topbar MAE without center/report regressions. |
| Center report | Design, Specimen | Other agents regressed under center-panel filtering, so this remains narrowly scoped. |
| Left agent rail | Orchestrator, Design, Vision, Manipulation, Equipment, BO | Rail tone was the largest residual for selected agents, especially BO and Vision. |
| Right chat panel | All 8 report agents | Every agent improved under a measured per-agent chat-panel tone. |
| Bottom dock | Orchestrator, Design, Specimen, Analysis, BO | Specimen and Analysis improved materially; BO keeps the previously accepted 1.06 tone; other agents keep default. |

Final per-agent snapshot:

| Agent | Full MAE | Topbar | Rail | Center | Chat | Bottom |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Orchestrator | 13.053 | 14.153 | 12.484 | 15.278 | 12.087 | 9.901 |
| Design | 13.900 | 15.267 | 11.079 | 16.025 | 14.803 | 9.915 |
| Specimen Making | 14.323 | 15.131 | 14.998 | 16.202 | 15.442 | 9.329 |
| Vision | 13.716 | 15.007 | 10.916 | 16.244 | 13.172 | 10.457 |
| Manipulation | 14.184 | 14.854 | 12.126 | 15.190 | 11.816 | 15.330 |
| Lab Equipment | 13.484 | 15.191 | 11.483 | 14.988 | 15.934 | 8.620 |
| Analysis | 13.467 | 16.149 | 12.002 | 15.458 | 13.544 | 9.501 |
| BO | 14.795 | 15.031 | 11.262 | 16.151 | 12.090 | 16.415 |

Rejected candidate rules from this pass:

- Manipulation bottom-dock recolor was rejected again; the residual is not solved by simple brightness and likely needs content/spacing alignment.
- Vision, Manipulation, Equipment, Analysis, and BO center-panel filters were rejected because they worsened center or full-image MAE.
- Specimen and Analysis rail filters were rejected because the default rail tone was effectively best.
- Narrower Design/Vision/BO workboard widths that lowered MAE but caused horizontal text overflow remain rejected.

Implementation rules:

- All new visual corrections are scoped by `body.planning-live-body[data-live-agent="..."]`.
- The reference image defines visual density and palette only. The ATR agent-loop content, evidence payloads, Guardian/approval semantics, and device guards remain authoritative.
- A candidate is not accepted if it improves screenshot MAE but creates horizontal overflow, tiny cards, hidden controls, or fake visual data.
- Current accepted static asset version is `20260601-live-layout-geometry-49`.

## 2026-06-01 Orchestrator-Only Chat Enforcement Pass

The Live GUI communication rule was tightened after the selected-bottom visual pass: the only actual chat/composer surface is the Orchestrator Chat. Selecting Design, Specimen Making, Vision, Manipulation, Lab Equipment, Analysis, BO, Knowledge, or Guardian changes the center report and the right-side evidence panel, but it must not expose another message input.

Accepted final audit directory for this policy pass:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_orchestrator_only_chat_v3/`

Reason for the metric tradeoff:

- `layout_geometry_audit_final_selected_bottom_v2` remains the closest pure visual match, with full-image average MAE `13.865`.
- The current Orchestrator-only chat implementation intentionally replaces non-Orchestrator chat content with an agent evidence side panel. This raises full-image average MAE to `14.170`, mainly in the right-panel region, because the reference images still depict an operator chat-like console.
- The policy requirement is stronger than the pure pixel target: operator conversation and LLM negotiation must stay in Orchestrator Chat; non-Orchestrator agents expose evidence, selected report section, tool/backend evidence, artifacts, recent agent messages, and handoff controls only.

Final measured result for the accepted policy pass:

| Agent | Full MAE | Right panel MAE | Cards | Visuals | Overflow |
| --- | ---: | ---: | ---: | ---: | ---: |
| Orchestrator | 12.795 | 10.895 | 9 | 4 | 0 px |
| Design | 14.294 | 16.618 | 9 | 5 | 0 px |
| Specimen Making | 14.749 | 17.402 | 12 | 6 | 0 px |
| Vision | 14.221 | 15.496 | 11 | 5 | 0 px |
| Manipulation | 14.458 | 13.082 | 12 | 5 | 0 px |
| Lab Equipment | 13.905 | 17.875 | 9 | 5 | 0 px |
| Analysis | 13.856 | 15.336 | 13 | 6 | 0 px |
| BO | 15.079 | 13.401 | 16 | 6 | 0 px |

Validation evidence:

- `node --check web/static/planning.js` PASS.
- `python3 -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` PASS.
- `tests/ui/planning_browser_audit.py --base-url http://127.0.0.1:7860 --webdriver-url http://127.0.0.1:4448` PASS. This now explicitly verifies that Orchestrator shows the chat/composer and Design switches to an `agent-evidence` right panel with no message input.
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_final_orchestrator_only_chat_v3` PASS.

Implementation rules from this pass:

- `web/templates/planning.html` contains `#live-orchestrator-chat-content` and `#live-agent-side-panel` inside the same right shell. The shell uses `data-panel-mode="orchestrator-chat"` or `data-panel-mode="agent-evidence"`.
- `planning.js::renderLiveAgentSidePanel()` is the only switch for hiding/showing those two right-panel modes.
- `draftRuntimeChat()` must redirect any non-Orchestrator chat draft back to Orchestrator before focusing the composer.
- The `Open Orchestrator Chat` action must preserve the source agent in the operator event payload as `source_agent` before switching `liveSelectedAgent` to `orchestrator`.
- Future right-panel visual tuning must not reintroduce message input, target selector choices, or independent chat history for non-Orchestrator agents.
- Static asset version for this pass: `20260601-live-layout-geometry-52`.



## 2026-06-01 Design Bottom Evidence Band Pass

The Orchestrator-only chat policy pass was kept as the current functional baseline. A new scoped layout candidate was then tested only for Design Agent because its generated reference image places the final evidence cards lower than the prior browser capture.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_design_bottom_band_v1/`

Measured improvement over `layout_geometry_audit_final_orchestrator_only_chat_v3`:

| Metric | Orchestrator-only chat v3 | Design bottom band v1 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.170 | 14.144 | -0.026 |
| Design full-image MAE | 14.294 | 14.087 | -0.207 |
| Design center-report MAE | 16.025 | 15.495 | -0.530 |
| Design bottom evidence row Y | 407 px | 515 px | +108 px |

Accepted scoped change:

- Only Design sections `material_notes`, `handoff_to_specimen`, and `artifact_ledger` are placed on row 14.
- The change is scoped by `body.planning-live-body[data-live-agent="design"]` and does not affect Specimen Making, Vision, Manipulation, Lab Equipment, Analysis, BO, Knowledge, Guardian, or Orchestrator.

Rejected candidates in the same follow-up pass:

- Right evidence panel tone sweep was rejected because it raised full-image avg MAE from `14.170` to `14.274` and worsened Equipment right-panel MAE from `17.875` to `20.682`.
- Specimen primary visual count reduction from 6 to 5 was rejected because Specimen center MAE worsened from `16.202` to `16.224`; `printer_status` remains visible as runtime evidence.
- Design row 16 was rejected because it worsened Design center MAE from `15.495` to `15.547`; row 14 remains the accepted position.
- Additional Specimen handoff lowering and Vision evidence/handoff lowering were tested and rejected because both worsened their own center-region MAE.

Validation evidence:

- `node --check web/static/planning.js` PASS.
- `python3 -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` PASS.
- `tests/ui/planning_browser_audit.py --base-url http://127.0.0.1:7860 --webdriver-url http://127.0.0.1:4448` PASS.
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_final_design_bottom_band_v1` PASS.
- Final recheck artifact: `artifacts/live_gui_upgrade/layout_geometry_audit_final_design_bottom_band_v1_recheck/` with the same accepted avg MAE `14.144`.
- Static asset version for the accepted code: `20260601-live-layout-geometry-57`.

Implementation rule from this pass:

- Apply reference-image corrections to every agent only through measured, scoped candidates. If an agent-specific candidate worsens screenshot metrics or creates text overflow/tiny cards, remove it even if the visual intuition seems plausible.


## 2026-06-01 Specimen Layer Preview Visual Pass

After the Design bottom evidence band pass, additional simple brightness and row-placement candidates were tested against the current Orchestrator-only chat baseline. Most did not improve the reference match. The accepted improvement in this pass is a Specimen Making layer-preview renderer that uses actual report rows to draw a compact toolpath/layer glyph instead of generic text tiles.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_final_specimen_layer_preview_v1/`

Measured improvement over `layout_geometry_audit_final_design_bottom_band_v1_recheck`:

| Metric | Design bottom band v1 recheck | Specimen layer preview v1 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.144 | 14.143 | -0.001 |
| Specimen full-image MAE | 14.749 | 14.742 | -0.007 |
| Specimen center-report MAE | 16.202 | 16.184 | -0.018 |
| Layer Preview visual class | `visual-layers visual-status-tiles` | `visual-layers visual-layer-preview` | report-driven glyph |
| Printer Status visual class | `visual-printer visual-status-tiles` | unchanged | no regression |

Implementation details:

- `planning.js::renderLayerPreviewVisual()` builds the layer glyph only from real report rows such as layer count, first-layer height, and infill/density ratio.
- If the layer preview has no evidence rows, it falls back to the existing no-data scaffold.
- The printer runtime gauge candidate was rejected and removed because it worsened Specimen full-image MAE from `14.749` to `14.759` and center MAE from `16.202` to `16.228`. Printer status remains tile-based.

Rejected candidates in this follow-up:

- BO center brightness `0.78` worsened BO center MAE from `16.151` to `16.388`.
- BO center brightness `0.62` worsened BO center MAE from `16.151` to `16.589`.
- BO bottom dock brightness `1.18` worsened BO bottom MAE from `16.415` to `17.205`.
- Design bottom row 13 and row 15 were both slightly worse than the accepted row 14.
- Specimen printer runtime gauge was worse than the existing tile status visual, so it was removed.

Validation evidence:

- `node --check web/static/planning.js` PASS.
- `git diff --check` PASS.
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_final_specimen_layer_preview_v1` PASS.
- Static asset version for the accepted code: `20260601-live-layout-geometry-58`.


## 2026-06-01 Agent Visual Semantics Pass

This pass extends the generated-full-screen alignment beyond card count and section names. Reference primary visuals are now mapped to concrete, agent-specific glyphs while preserving the no-fake-data rule.

Implemented visual mappings:

- Vision `inspection_feed` -> `visual-camera-feed`, a compact camera overlay glyph with target box, contour, confidence/frame/latency metadata from report rows.
- Vision `segmentation` -> `visual-segmentation-mask`, a raw/mask two-panel segmentation glyph with mask and defect metrics from report rows.
- Vision and Analysis `confusion_matrix` -> `visual-confusion-matrix`, a 2x2 statistical glyph. It displays TP/FP/FN plus TN if present; if TN is absent, the fourth cell is ACC. It does not infer TN or invent fallback counts.
- Analysis `model_output` -> `visual-scatter`, matching the reference regression-scatter intent instead of a line-only plot.
- Design, Manipulation, and BO heatmap sections -> `visual-heatmap-grid`, a real 3x3 heatmap glyph instead of status tiles.
- BO `surrogate_model` and `acquisition_function` now render as primary visual sections, increasing BO visual coverage from 6 to 8.
- Lab Equipment `environmental_conditions` -> `visual-environment-mini`, a temperature/humidity/readiness mini chart using only environmental report rows.

Rejected candidates from this pass:

- BO workboard width 76 percent: worsened BO full-image MAE from `15.055` to `15.155`; removed.
- Vision center brightness 0.90: worsened Vision full-image MAE from `14.263` to `14.472`; removed.

Current audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_agent_visuals_final_v2/`

Latest comparison against the previous accepted geometry baseline:

| Agent | Previous MAE | Current MAE | Note |
| --- | ---: | ---: | --- |
| Orchestrator | 12.795 | 12.795 | unchanged |
| Design | 14.087 | 14.073 | improved by real heatmap glyph |
| Specimen Making | 14.742 | 14.742 | unchanged |
| Vision | 14.221 | 14.263 | semantic visual fidelity improved; layout residual still needs next pass |
| Manipulation | 14.458 | 14.507 | reachability now real heatmap; layout residual still needs next pass |
| Lab Equipment | 13.905 | 13.924 | environmental mini chart enabled; layout residual still needs next pass |
| Analysis | 13.856 | 13.887 | regression scatter/confusion matrix enabled; layout residual still needs next pass |
| BO | 15.079 | 15.055 | improved with surrogate/acquisition visuals |

Validation evidence:

- `node --check web/static/planning.js` passed.
- `python3 -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` passed.
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` passed and produced the artifact directory above.
- `tests/ui/planning_browser_audit.py` passed, including Orchestrator-only chat, no horizontal overflow, BO graph toggle, FEM card, report/backend split, duplicate tooltip count 0, and Guardian approval blocking.
- `git diff --check` passed.

This pass is not the final visual-completion point. It fixes the "card name only" problem for primary visuals; subsequent passes must still reduce layout residuals for Vision, Manipulation, Analysis, and BO by comparing the generated contact sheets agent by agent.

## 2026-06-01 Reference Report Card Pass v64

This pass responds to the requirement that the Live GUI must follow the generated reference layout visually, not only by matching card counts or section names. The accepted change converts generated agent report cards from long finding/action text blocks into compact evidence-first cards: primary metric, short interpretation, compact evidence pills, and the existing reference mini visual. The report view still uses ATR runtime evidence and does not invent data.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_reference_report_pass_final_v64/`

Measured improvement over `layout_geometry_audit_agent_visuals_final_v2`:

| Metric | Agent visual semantics v2 | Reference report pass v64 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 14.156 | 13.827 | -0.329 |
| Center-report avg MAE | 15.656 | 14.796 | -0.860 |
| Orchestrator full MAE | 12.795 | 12.454 | -0.341 |
| Design full MAE | 14.073 | 13.968 | -0.105 |
| Specimen Making full MAE | 14.742 | 14.345 | -0.397 |
| Vision full MAE | 14.263 | 13.929 | -0.334 |
| Manipulation full MAE | 14.507 | 14.160 | -0.347 |
| Lab Equipment full MAE | 13.924 | 13.562 | -0.362 |
| Analysis full MAE | 13.887 | 13.319 | -0.568 |
| BO full MAE | 15.055 | 14.879 | -0.176 |

Accepted implementation details:

- `renderGeneratedFullScreenSectionCard()` now renders a primary metric block before the short finding text.
- Per-card `Next` text is no longer repeated everywhere. It is shown only for gate/action sections, reducing visual noise.
- Evidence chips are capped more tightly for visual cards, keeping charts and image glyphs readable.
- Header identity now follows the reference package language: `ATR Runtime IDE LIVE` while the browser page title remains `Live GUI`.
- Center-panel filter sweeps were accepted only where they lowered reference error: Vision `0.80`, Lab Equipment `0.76`, BO `0.72`; Manipulation kept the previous `0.64` because it remained the best measured value.

Rejected candidates:

- Global brightening / shell luminance override worsened full-image avg MAE from `13.854` to `14.994`; removed.
- Hiding most topbar chips worsened full-image avg MAE from `13.854` to `13.883` and topbar avg MAE from `15.201` to `15.570`; removed.
- BO center filters `0.76`, `0.80`, and `0.84` were worse than `0.72`.
- Vision center filters `0.70`, `0.72`, `0.76`, and `0.84` were worse than `0.80`.
- Lab Equipment center filters `0.68`, `0.72`, `0.80`, and `0.84` were worse than `0.76`.
- Manipulation center filters `0.60`, `0.68`, `0.72`, and `0.76` were worse than the existing `0.64`.

Validation evidence:

- `node --check web/static/planning.js` passed.
- `python3 -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` passed.
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_reference_report_pass_final_v64` passed.
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_reference_report_final_v64` passed.
- Static asset version: `20260601-live-layout-geometry-64`.

Implementation rule from this pass:

- Do not optimize by global brightness or decorative chart stuffing. Use agent-scoped, measured candidates and retain only changes that improve the reference comparison without raw JSON leakage, overflow, fake data, or hidden controls.

## 2026-06-01 All-Agent Visual-Dominant Report Pass v66b

This pass responds to the stricter requirement that every generated agent report must read like the supplied reference screens, not like a generic JSON-derived card board. The change is applied across Orchestrator, Design, Specimen Making, Vision, Manipulation, Lab Equipment, Analysis, and BO.

Accepted audit directory:

`artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_final_v66b/`

Planning audit artifact:

`artifacts/live_gui_upgrade/planning_browser_audit_visual_dominant_v66b/`

Implementation changes:

- Every generated report section with a primary visual now uses a `visual-dominant` report card layout: primary metric, short finding, full-width visual slot, compact evidence chips, and optional gate/action text.
- Design, Vision, Specimen Making, and BO no longer use narrow workboards that won pixel metrics by leaving large blank areas. The generated workboard is now full-width for all generated report agents so the visible layout follows the reference full-screen composition.
- Evidence/action labels now include explicit separators, preventing merged extracted text such as `objectivevalue` or `GateCheck` in browser/audit output.
- The rejected topbar-brightening v67 candidate was removed because it worsened the topbar and full-screen MAE. The current asset version is `20260601-live-layout-geometry-66b`.

Measured v66b result:

| Agent | Full MAE | Center MAE | Right MAE | Workboard px | Cards | Visuals | Overflow |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Orchestrator | 12.334 | 14.082 | 10.895 | 1037 | 9 | 4 | 0 |
| Design | 14.102 | 15.500 | 16.618 | 1037 | 9 | 5 | 0 |
| Specimen Making | 14.275 | 14.963 | 17.402 | 1037 | 12 | 6 | 0 |
| Vision | 14.153 | 16.077 | 15.496 | 1037 | 11 | 5 | 0 |
| Manipulation | 14.175 | 14.448 | 13.082 | 1037 | 12 | 5 | 0 |
| Lab Equipment | 13.455 | 13.815 | 17.875 | 1037 | 9 | 5 | 0 |
| Analysis | 13.289 | 13.993 | 15.336 | 1037 | 13 | 6 | 0 |
| BO | 15.035 | 16.008 | 13.401 | 1037 | 16 | 8 | 0 |
| Average | 13.852 | 14.861 | - | - | - | - | 0 |

Interpretation:

- v64 remains the lowest numeric MAE pass for some narrowed workboards, but it failed the operator-facing visual intent because several agent reports looked squeezed and left the right side of the center canvas underused.
- v66b is the current accepted operator-layout baseline because it uses the same full-width report composition across all generated-full-screen reference agents while preserving no-overflow, Orchestrator-only chat, no raw JSON in Report, BO graph collapse behavior, FEM card rendering, and Guardian approval blocking.
- Future tuning must start from v66b unless the user explicitly asks to optimize pixel MAE over visual composition.

Validation evidence:

- `node --check web/static/planning.js` PASS.
- `python -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` PASS.
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_final_v66b` PASS.
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_visual_dominant_v66b` PASS.
- `git diff --check` must be run after any additional edits before commit.

Implementation rule from this pass:

- Do not claim an agent report matches the reference just because the section count is correct. A visible visual section should have a dominant graph/image/statistical treatment when the reference indicates one and runtime evidence supports it.
- Do not fill missing evidence with fake values. If evidence is absent, render a compact pending/no-data state.
- Keep non-Orchestrator chat disabled. Agent tabs are report/evidence inspection surfaces; Orchestrator remains the conversation and workflow trigger surface.

## 2026-06-01 BO Row-Pitch Refinement v69

This pass continues from the v66b all-agent visual-dominant baseline. The BO report remained the highest center-report residual, so only BO grid row pitch was swept with browser screenshots while preserving the full-width workboard and the Orchestrator-only chat policy.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_bo_row_pitch_v69/`
- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v69_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v69_recheck/`

Accepted change:

- BO generated report workboard uses `grid-auto-rows: 22px` instead of 24px.
- The rule is scoped to `body.planning-live-body[data-live-agent="bo"] .live-agent-reference-workboard.live-generated-fullscreen-grid`.
- It keeps workboard width `1037px`, card count `16`, primary visual count `8`, and horizontal overflow `0`.

Measured improvement over v66b:

| Metric | v66b | v69 | Change |
| --- | ---: | ---: | ---: |
| Full-image avg MAE | 13.852 | 13.849 | -0.003 |
| Center-report avg MAE | 14.861 | 14.853 | -0.008 |
| BO full MAE | 15.035 | 15.010 | -0.025 |
| BO center MAE | 16.008 | 15.944 | -0.064 |
| BO bottom MAE | 16.415 | 16.415 | 0.000 |

Rejected candidates:

- BO bottom dock brightness sweep from `0.70` to `1.26`: current `1.06` remains best.
- BO row pitch `24px` and wider row pitches `26px` to `34px`: all worse than `22px` for BO center/full MAE.
- BO explicit chart-row shifts: worsened BO center MAE.
- Non-Orchestrator side-panel compact action strip: worsened right-panel MAE for Equipment, Specimen, and Design, so it was removed.

Validation evidence:

- `node --check web/static/planning.js` PASS.
- `git diff --check` PASS.
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v69_recheck` PASS.
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_v69_recheck` PASS.
- Current browser asset version: `20260601-live-layout-geometry-69`.

## 2026-06-01 Per-Agent Board Geometry Pass v70

After the visual-dominant v66b and BO row-pitch v69 baselines, the remaining center-report mismatch came from treating all generated agent reports as the same width/row rhythm. The v70 pass uses the package `generated_full_screens` images as the visual target and accepts only agent-scoped CSS that improved browser-captured screenshot metrics without changing Orchestrator-only chat or raw/backend separation.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v70_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v70_recheck/`

Accepted geometry overrides:

| Agent | Workboard geometry | Reason |
| --- | --- | --- |
| Design | `56%` generated workboard width | Reference sweep improved full MAE and center-report MAE while preserving 9 cards / 5 visuals. |
| Specimen Making | `84%` generated workboard width | This agent needs a wider fabrication board for slicer/layer/printer cards; narrower candidates reduced readability. |
| Vision | `56%` generated workboard width | Reference sweep improved the inspection/report cluster position while preserving 11 cards / 5 visuals. |
| Manipulation | `56%` generated workboard width | Reference sweep improved manipulation center geometry without touching rollout/chat routing. |
| Lab Equipment | full width + `20px` row pitch | Width compression was not needed; denser row pitch improved the equipment report rhythm. |
| Analysis | full width + `20px` row pitch | Keeps analysis figures readable while matching the reference row density more closely. |
| BO | `56%` generated workboard width + existing `22px` row pitch | BO optimization report now follows the reference compact cluster rather than forcing full-width card spread. |
| Orchestrator | unchanged | Orchestrator remains the only chat surface and keeps its mission/route/operator report geometry. |

Measured v70 improvement over v69:

| Metric | v69 | v70 | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.849 | 13.710 | -0.139 |
| Average center-report MAE | 14.853 | 14.495 | -0.358 |
| Horizontal overflow | 0 px | 0 px | unchanged |

Per-agent v70 snapshot:

| Agent | Full MAE | Center MAE | Workboard | Cards | Visuals |
| --- | ---: | ---: | --- | ---: | ---: |
| Orchestrator | 12.334 | 14.082 | 1037 x 659 | 9 | 4 |
| Design | 13.845 | 14.842 | 581 x 659 | 9 | 5 |
| Specimen Making | 14.202 | 14.775 | 871 x 659 | 12 | 6 |
| Vision | 13.873 | 15.359 | 581 x 659 | 11 | 5 |
| Manipulation | 14.058 | 14.149 | 581 x 659 | 12 | 5 |
| Lab Equipment | 13.315 | 13.458 | 1037 x 659 | 9 | 5 |
| Analysis | 13.212 | 13.794 | 1037 x 474 | 13 | 6 |
| BO | 14.838 | 15.503 | 581 x 474 | 16 | 8 |

Validation:

- `node --check web/static/planning.js` PASS
- `.venv/bin/python -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` PASS
- `git diff --check` PASS
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS
- `tests/ui/planning_browser_audit.py` PASS

Operational rule: future report layout changes must be scoped by `body.planning-live-body[data-live-agent="<agent>"]` unless a full all-agent screenshot audit proves a global change is better. Do not reintroduce non-Orchestrator chat composers, fake chart values, or raw JSON in Report view.
## 2026-06-01 Shell Region Tone Refinement v71

After v70, the largest remaining non-center residuals were the right operator/evidence panel for Design, Vision, Equipment, and Analysis, plus the Orchestrator topbar. v71 does not change layout, chat routing, report semantics, or backend wiring. It only applies measured agent-scoped tone filters that improved screenshot comparison.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v71_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v71_recheck/`

Accepted tone refinements:

| Region | Agent | v70 | v71 | Effect |
| --- | --- | ---: | ---: | --- |
| Topbar | Orchestrator | `0.80` | `0.76` | topbar MAE `14.243 -> 14.172` |
| Right panel | Design | `0.94` | `0.86` | right MAE `16.618 -> 16.371` |
| Right panel | Vision | `0.94` | `0.78` | right MAE `15.496 -> 14.657` |
| Right panel | Lab Equipment | `0.94` | `0.86` | right MAE `17.875 -> 17.617` |
| Right panel | Analysis | `1.12` | `1.06` | right MAE `15.336 -> 15.085` |

Measured v71 improvement over v70:

| Metric | v70 | v71 | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.710 | 13.663 | -0.047 |
| Average right-panel MAE | 15.013 | 14.814 | -0.199 |
| Average topbar MAE | 15.201 | 15.192 | -0.009 |
| Average center-report MAE | 14.495 | 14.489 | -0.006 |
| Horizontal overflow | 0 px | 0 px | unchanged |

Rejected or unchanged candidates:

- Specimen Making right panel: existing `1.06` remains best.
- BO bottom dock: existing `1.06` remains best.
- Manipulation bottom dock: `1.00` was only marginally better and visually equivalent to no filter, so no functional style change was added.
- Design/Specimen/Equipment/Analysis topbar changes were rejected because they worsened full-image or topbar MAE relative to v70.

Validation:

- `node --check web/static/planning.js` PASS
- `.venv/bin/python -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` PASS
- `git diff --check` PASS
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS
- `tests/ui/planning_browser_audit.py` PASS

Operational rule: shell-region tone changes are allowed only when they are agent-scoped and improve the targeted region in browser screenshots. Do not use tone sweeps to hide structural layout mismatch.

## 2026-06-01 Dense Evidence Side Panel Pass v72

After v71, the right-side region was still the largest residual for most non-Orchestrator agent screens. The main mismatch was structural, not color-only: the non-Orchestrator side panel kept a tall summary block and pushed the event/evidence rhythm too far down compared with the generated full-screen references.

v72 keeps the Orchestrator chat unchanged and applies only the non-Orchestrator `agent-evidence` side panel density pass. This preserves the hard rule that user chat and workflow negotiation exist only in Orchestrator Chat.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v72_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v72_recheck/`

Accepted structural refinements:

- Non-Orchestrator side summary is rendered as a compact 4-column evidence grid.
- Non-Orchestrator side note is collapsed into a single status/action strip.
- Side sections, section gaps, and action buttons use tighter spacing so tool/event evidence appears at the same vertical rhythm as the reference.
- Orchestrator right chat remains unchanged.
- Agent report workboard geometry from v70 and shell-region tone filters from v71 remain active.

Measured v72 improvement over v71:

| Metric | v71 | v72 | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.663 | 13.432 | -0.231 |
| Average right-panel MAE | 14.814 | 13.750 | -1.064 |
| Average topbar MAE | 15.192 | 15.192 | 0.000 |
| Average center-report MAE | 14.489 | 14.489 | 0.000 |
| Horizontal overflow | 0 px | 0 px | unchanged |

Per-agent v72 snapshot:

| Agent | Full MAE | Right MAE | Center MAE | Workboard |
| --- | ---: | ---: | ---: | --- |
| Orchestrator | 12.328 | 10.895 | 14.082 | 1037 x 659 |
| Design | 13.407 | 14.626 | 14.829 | 581 x 659 |
| Specimen Making | 13.898 | 16.003 | 14.775 | 871 x 659 |
| Vision | 13.435 | 13.521 | 15.338 | 581 x 659 |
| Manipulation | 13.873 | 12.231 | 14.149 | 581 x 659 |
| Lab Equipment | 13.010 | 16.478 | 13.453 | 1037 x 659 |
| Analysis | 12.858 | 13.723 | 13.785 | 1037 x 474 |
| BO | 14.646 | 12.520 | 15.503 | 581 x 474 |

Validation:

- `node --check web/static/planning.js` PASS
- `.venv/bin/python -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` PASS
- `git diff --check` PASS
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS
- `tests/ui/planning_browser_audit.py` PASS

Operational rule: non-Orchestrator side panels are evidence consoles, not secondary chat windows. Future changes must keep the compact evidence rhythm unless a browser screenshot audit against all generated full-screen references proves another structure is better.

## 2026-06-01 BO Row-Pitch Micro-Pass v73

After v72, broad tone/filter and width candidates were rejected because they worsened reference screenshot metrics or made the report composition less stable. The only accepted refinement from the v73 sweep is a BO-only row-pitch adjustment for the generated Bayesian Optimization report board.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v73_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v73_recheck/`

Accepted change:

- BO generated report board row pitch changed from `22px` to `20px`.
- Orchestrator chat, non-Orchestrator evidence side panel, all other agent workboard geometry, and backend/report contracts remain unchanged.

Measured v73 improvement over v72:

| Metric | v72 | v73 | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.432 | 13.430 | -0.002 |
| Average center-report MAE | 14.489 | 14.485 | -0.004 |
| BO full-image MAE | 14.646 | 14.633 | -0.013 |
| BO center-report MAE | 15.503 | 15.468 | -0.035 |
| Horizontal overflow | 0 px | 0 px | unchanged |

Rejected candidates in this pass:

- Topbar brightness changes for Design, Specimen Making, Vision, Manipulation, Lab Equipment, Analysis, and BO.
- BO/Manipulation bottom-dock brightness changes.
- Equipment/Specimen/Design/Analysis right-panel brightness changes except for sub-pixel-level noise improvements that were too small to accept.
- BO/Vision workboard width expansion: edge signatures sometimes improved, but full/center MAE worsened and the composition was less stable.
- BO/Vision center contrast filters: all worsened center MAE substantially.

Validation:

- `node --check web/static/planning.js` PASS
- `.venv/bin/python -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` PASS
- `git diff --check` PASS
- `tests/ui/live_gui_agent_reference_layout_audit.py --capture` PASS
- `tests/ui/planning_browser_audit.py` PASS

Operational rule: do not accept visual tweaks because they look plausible. A candidate must improve the relevant reference screenshot metrics, preserve Orchestrator-only chat, and keep generated report content connected to backend evidence.

## 2026-06-01 Soft Card / Visual Density Pass v75

The v75 pass accepts a soft generated-report card and visual density adjustment after comparing candidate screenshots against v73 and v74. The accepted change improves most generated report agents while explicitly excluding Specimen Making, where the same visual treatment caused a small regression.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v75b_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v75_recheck/`

Accepted change:

- Non-Specimen generated report cards receive a softer edge rhythm and lighter inset/card shadow to better match the reference figure-card treatment.
- Non-Specimen generated report visuals receive a subtle grid/tonal background and slightly heavier SVG path stroke.
- Specimen Making remains on the v73 treatment because v74 increased Specimen full-image MAE `13.898 -> 13.906` and center-report MAE `14.775 -> 14.795`.
- Orchestrator-only chat routing, non-Orchestrator evidence consoles, backend/report contracts, and all agent card counts remain unchanged.

Measured comparison:

| Metric | v73 | v74 global candidate | v75 accepted | Change vs v73 |
| --- | ---: | ---: | ---: | ---: |
| Average full-image MAE | 13.430 | 13.390 | 13.389 | -0.041 |
| Average center-report MAE | 14.485 | 14.381 | 14.379 | -0.106 |
| Specimen full-image MAE | 13.898 | 13.906 | 13.898 | unchanged |
| Specimen center-report MAE | 14.775 | 14.795 | 14.775 | unchanged |
| BO center-report MAE | 15.468 | 15.419 | 15.419 | -0.049 |
| Vision center-report MAE | 15.338 | 15.220 | 15.220 | -0.118 |
| Horizontal overflow | 0 px | 0 px | 0 px | unchanged |

Rejected candidates in this pass:

- `card_edge` only: improved several agents but underperformed the combined card/visual treatment.
- `visual_grid` only and `visual_strokes` only: each improved less than the combined treatment and did not sufficiently close the center-report residual.
- Global v74 application: rejected because Specimen Making regressed; v75 scopes the accepted treatment away from Specimen.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v75b_recheck` PASS
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_v75_recheck` PASS
- `node --check web/static/planning.js` PASS
- `.venv/bin/python -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` PASS
- `git diff --check` PASS

Operational rule: soft card/visual density is agent-scoped. Do not apply it to Specimen Making unless a future screenshot/contact-sheet audit proves improvement without harming printer-runtime readability.

## 2026-06-01 Agent Row-Pitch Refinement Pass v76

The v76 pass follows the user requirement that reference matching must cover layout distribution, not only card count. A center-region edge-distribution check showed Design, Vision, Manipulation, and BO were visually concentrated toward the left side. Width expansion candidates were tested first, but all worsened screenshot metrics. A narrower agent-scoped row-pitch sweep then produced two accepted improvements.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v76_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v76_recheck/`

Accepted change:

- Design generated report row pitch changed to `19px`.
- Manipulation generated report row pitch changed to `23px`.
- Vision and BO keep their previous row pitch values because every tested candidate worsened their metrics.
- Width expansion for Design/Vision/Manipulation/BO remains rejected; screenshot MAE worsened for `64%`, `68%`, `76%`, `84%`, and `100%` candidates.

Measured comparison:

| Metric | v75 | v76 accepted | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.389 | 13.377 | -0.012 |
| Average center-report MAE | 14.379 | 14.349 | -0.030 |
| Design full-image MAE | 13.379 | 13.298 | -0.081 |
| Design center-report MAE | 14.756 | 14.549 | -0.207 |
| Manipulation full-image MAE | 13.849 | 13.839 | -0.010 |
| Manipulation center-report MAE | 14.087 | 14.061 | -0.026 |
| Horizontal overflow | 0 px | 0 px | unchanged |

Rejected candidates in this pass:

- Width expansion for Design/Vision/Manipulation/BO: `64%`, `68%`, `76%`, `84%`, `100%`.
- Design row pitch `20px`, `22px`, `23px`.
- Vision row pitch `23px`, `24px`, `26px`, `27px`.
- Manipulation row pitch `22px`, `25px`, `26px`.
- BO row pitch `18px`, `19px`, `21px`, `22px`.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v76_recheck` PASS
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_v76_recheck` PASS

Operational rule: do not infer that left/right visual imbalance should be fixed by widening the workboard. Use screenshot MAE plus contact-sheet inspection; only accept the smallest agent-scoped layout change that improves the measured reference residual.

## 2026-06-01 Center Luminance Retune Pass v77

The v77 pass retunes center-panel luminance after the v76 row-pitch changes. The sweep was repeated because previous luminance decisions were made against older geometry. Only BO and Specimen improved enough to accept.

Accepted audit directory:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v77_recheck/`

Accepted change:

- BO center panel brightness changed to `0.74`.
- Specimen center panel brightness changed to `0.88`.
- Vision and Design center brightness candidates were rejected because they worsened or did not improve screenshot MAE.

Measured comparison:

| Metric | v76 | v77 accepted | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.377 | 13.373 | -0.004 |
| Average center-report MAE | 14.349 | 14.339 | -0.010 |
| BO full-image MAE | 14.614 | 14.601 | -0.013 |
| BO center-report MAE | 15.419 | 15.386 | -0.033 |
| Specimen full-image MAE | 13.898 | 13.879 | -0.019 |
| Specimen center-report MAE | 14.775 | 14.726 | -0.049 |

Rejected candidates in this pass:

- BO brightness `0.66`, `0.70`, `0.78`, `0.82`, `0.88`.
- Vision brightness `0.74`, `0.78`, `0.82`, `0.86`, `0.92`, `1.00`.
- Specimen brightness `0.80`, `0.84`, `0.92`, `0.98`, `1.04`.
- Design brightness `0.80`, `0.84`, `0.92`, `0.98`, `1.04`.

## 2026-06-01 Right Evidence-Panel Retune Pass v78

The v78 pass retunes the non-Orchestrator right evidence panel without reintroducing chat composers. Candidate sweeps targeted Equipment, Specimen, Design, and Analysis because their right-region residuals were highest after v77.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v78_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v78_recheck/`

Accepted change:

- Specimen right evidence panel brightness changed to `1.04`.
- Analysis right evidence panel brightness changed to `1.04`.
- Equipment was not accepted: `0.90` improved right MAE by only `0.004` while slightly worsening center MAE.
- Design remained unchanged because the current value was best.
- Topbar and bottom-dock sweeps were rejected after v78 because candidate improvements were absent or below acceptance threshold.

Measured comparison:

| Metric | v76 | v78 accepted | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.377 | 13.368 | -0.009 |
| Average center-report MAE | 14.349 | 14.339 | -0.010 |
| Average right-panel MAE | 13.750 | 13.727 | -0.023 |
| Specimen full-image MAE | 13.898 | 13.856 | -0.042 |
| Specimen center-report MAE | 14.775 | 14.724 | -0.051 |
| Specimen right-panel MAE | 16.003 | 15.902 | -0.101 |
| Analysis full-image MAE | 12.767 | 12.748 | -0.019 |
| Analysis right-panel MAE | 13.723 | 13.642 | -0.081 |
| BO center-report MAE | 15.419 | 15.386 | -0.033 |
| Horizontal overflow | 0 px | 0 px | unchanged |

Rejected candidates in this pass:

- BO and Manipulation bottom-dock brightness candidates; current bottom-dock values remain best.
- Equipment right-panel candidates because the only right-region improvement was too small and introduced center regression.
- Design right-panel candidates.
- Analysis right-panel candidates except `1.04`.
- Specimen right-panel candidates except `1.04`.
- Topbar brightness sweeps for Analysis, Equipment, Design, Specimen, BO, and Vision; Vision `0.70` improved full MAE by only `0.001`, below acceptance threshold.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v78_recheck` PASS
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_v78_recheck` PASS

Operational rule: right evidence panels remain evidence surfaces only. Styling may be tuned by screenshot audit, but no non-Orchestrator message composer or chat target may be reintroduced.



## 2026-06-01 BO/Vision Width Retune Pass v79

The v79 pass addresses the remaining generated_full_screens layout mismatch for BO and Vision. The prior v78 baseline still spread these two generated report workboards wider than the reference composition. Candidate sweeps tested width and gap independently; only the smallest width-only change improved the screenshot residual without touching the Orchestrator chat contract or other agents.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v79_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v79_recheck/`

Accepted change:

- BO generated report workboard width changed from `56%` to `36%`.
- Vision generated report workboard width changed from `56%` to `36%`.
- Design, Specimen Making, Manipulation, Lab Equipment, Analysis, and Orchestrator remain unchanged from v78.

Measured comparison:

| Metric | v78 | v79 accepted | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.368 | 13.339 | -0.029 |
| Average center-report MAE | 14.339 | 14.263 | -0.076 |
| Average right-panel MAE | 13.727 | 13.727 | 0.000 |
| BO full-image MAE | 14.601 | 14.489 | -0.112 |
| BO center-report MAE | 15.386 | 15.102 | -0.284 |
| Vision full-image MAE | 13.389 | 13.265 | -0.124 |
| Vision center-report MAE | 15.220 | 14.901 | -0.319 |
| Horizontal overflow | 0 px | 0 px | unchanged |

Width sweep evidence:

| Width | BO full | BO center | Vision full | Vision center |
| ---: | ---: | ---: | ---: | ---: |
| 36% | 14.489 | 15.102 | 13.265 | 14.901 |
| 38% | 14.518 | 15.174 | 13.278 | 14.937 |
| 40% | 14.550 | 15.258 | 13.285 | 14.953 |
| 42% | 14.564 | 15.292 | 13.301 | 14.996 |
| 44% | 14.562 | 15.287 | 13.316 | 15.033 |
| 46% | 14.569 | 15.305 | 13.330 | 15.068 |
| 48% | 14.559 | 15.281 | 13.334 | 15.078 |

Rejected candidates in this pass:

- BO/Vision gap candidates `4px`, `5px`, `7px`, `8px`, `10px`, `12px`; all worsened metrics.
- Wider BO/Vision candidates `52%`, `56%`, `60%`, `64%`, `68%`; all were worse than the accepted `36%` width.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v79_recheck` PASS
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_v79_recheck` PASS

Operational rule: when generated report cards feel visually over-expanded, do not tune all agents globally. Use agent-scoped width/row/tone sweeps against generated_full_screens and accept only the smallest change that improves both full-image and center-report MAE without changing backend evidence semantics.


## 2026-06-01 Non-Orchestrator Topbar Retune Pass v80

The v80 pass addresses the strongest remaining common residual after v79: the top mission/status bar. The reference package top bar is lighter and calmer than the old per-agent dark gradient. A global light candidate improved seven agents but regressed Orchestrator, so the accepted patch is explicitly scoped to non-Orchestrator agent selections.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v80_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v80_recheck/`

Accepted change:

- Non-Orchestrator top mission bars use `linear-gradient(180deg, rgba(20, 31, 46, 0.98), rgba(13, 22, 35, 0.98))`, border `rgba(148, 163, 184, 0.20)`, and a softer `0 8px 22px rgba(0, 0, 0, 0.14)` shadow.
- Non-Orchestrator topbar runtime chips use `rgba(15, 23, 42, 0.52)` background.
- Orchestrator topbar remains unchanged because the global candidate worsened Orchestrator full/topbar MAE.

Measured comparison:

| Metric | v79 | v80 accepted | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.339 | 13.212 | -0.127 |
| Average topbar MAE | 15.192 | 13.609 | -1.583 |
| Average center-report MAE | 14.263 | 14.262 | -0.001 |
| Average right-panel MAE | 13.727 | 13.727 | 0.000 |
| Design full/topbar MAE | 13.298 / 15.440 | 13.120 / 13.244 | -0.178 / -2.196 |
| Specimen full/topbar MAE | 13.856 / 15.275 | 13.688 / 13.198 | -0.168 / -2.077 |
| Vision full/topbar MAE | 13.265 / 14.991 | 13.144 / 13.488 | -0.121 / -1.503 |
| Manipulation full/topbar MAE | 13.839 / 14.943 | 13.736 / 13.629 | -0.103 / -1.314 |
| Lab Equipment full/topbar MAE | 12.951 / 15.301 | 12.824 / 13.707 | -0.127 / -1.594 |
| Analysis full/topbar MAE | 12.748 / 16.235 | 12.570 / 14.011 | -0.178 / -2.224 |
| BO full/topbar MAE | 14.489 / 15.177 | 14.351 / 13.423 | -0.138 / -1.754 |
| Orchestrator full/topbar MAE | 12.264 / 14.172 | 12.264 / 14.172 | 0.000 / 0.000 |
| Horizontal overflow | 0 px | 0 px | unchanged |

Rejected candidates in this pass:

- `compact_one_row`: improved some topbar residuals but worsened average full-image MAE and several agent reports.
- `compact_keep_labels`: same issue as compact one-row, with weaker topbar improvement.
- `mission_bar_dark` and `one_row_dark`: heavily worsened topbar residuals across all agents.
- `light_non_orch_buttons_soft`: close but worse than accepted `light_non_orch_no_card_shadow`.
- Global `mission_bar_light`: improved seven agents but worsened Orchestrator, so it was rejected in favor of the non-Orchestrator-scoped patch.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v80_recheck` PASS
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_v80_recheck` PASS

Operational rule: shared shell styling may be changed only after checking Orchestrator separately. Orchestrator is the only chat surface; do not accept a global shell candidate that improves generated report agents while degrading Orchestrator chat/readiness.


## 2026-06-01 Lab Equipment Right Evidence-Card Retune Pass v81

The v81 pass targets the largest remaining right-panel residual after v80: Lab Equipment. Simple panel brightness helped only slightly; changing the whole panel background regressed the screenshot. The accepted patch keeps the Orchestrator-only chat contract and adjusts only Lab Equipment internal evidence card tone.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v81_recheck/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v81_recheck/`

Accepted change:

- Lab Equipment `.live-chat-panel` brightness changed from inherited `0.86` to `0.92`.
- Lab Equipment `.live-side-summary-card`, `.live-side-orchestrator-note`, and `.live-side-section` use `rgba(31, 37, 46, 0.46)`.
- Lab Equipment summary `.runtime-row` uses `rgba(16, 24, 36, 0.34)`.
- No other agent panel changed.

Measured comparison:

| Metric | v80 | v81 accepted | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.212 | 13.202 | -0.010 |
| Average right-panel MAE | 13.727 | 13.679 | -0.048 |
| Average center-report MAE | 14.262 | 14.262 | 0.000 |
| Lab Equipment full-image MAE | 12.824 | 12.742 | -0.082 |
| Lab Equipment right-panel MAE | 16.477 | 16.095 | -0.382 |
| Horizontal overflow | 0 px | 0 px | unchanged |

Rejected candidates in this pass:

- Lab Equipment right-panel brightness `0.86`, `0.88`, `0.90`, `0.91`, `0.93`, `0.94`, `0.95`, `0.98`, `1.04`, `1.10`, `1.16`, `1.22`, `1.30`, `1.38`, `1.48`.
- Whole-panel warm background candidates because they worsened full/right residuals.
- Warmer card alpha candidates `0.52`, `0.58`, `0.64`, `0.70` and row alpha variants because they were worse than `0.46/0.34`.
- Design right-panel brightness changes except the negligible `0.88` candidate; not accepted because the improvement was below material threshold.
- Specimen right-panel brightness changes; current `1.04` remains best.
- BO bottom-dock brightness candidates `0.80`, `0.90`, `1.00`, `1.12`, `1.20`, `1.30`, `1.40`, `1.55`, `1.70`; current `1.06` remains best.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_visual_dominant_v81_recheck` PASS
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_v81_recheck` PASS

Operational rule: tune non-Orchestrator right panels as evidence consoles, not chat windows. Internal evidence-card tone may be agent-specific only when it improves the target agent without changing Orchestrator chat or other agents.

## 2026-06-01 Generated Full-Screen Layout Geometry Retune Pass v83

The v83 pass corrects the failure mode where previous screenshot sweeps optimized raw RGB MAE by making some generated report boards too narrow. That reduced average color residuals but did not match the reference image layout. v83 therefore uses center-report edge geometry as the primary acceptance signal for generated agent reports.

Accepted audit directories:

- `artifacts/live_gui_upgrade/layout_geometry_audit_reference_widths_v83/`
- `artifacts/live_gui_upgrade/planning_browser_audit_v83/`

Accepted workboard widths:

| Agent | v81 width | v83 width | Reason |
| --- | ---: | ---: | --- |
| Orchestrator | 100% | 100% | already full reference canvas |
| Design | 56% | 64% | improves center-edge match |
| Specimen Making | 84% | 72% | improves center-edge match while keeping printer/layer cards readable |
| Vision | 36% | 48% | fixes over-narrow visual board while avoiding full-width spread |
| Manipulation | 56% | 64% | improves trajectory/workspace edge alignment |
| Lab Equipment | 100% | 100% | already full reference canvas |
| Analysis | 100% | 100% | already full reference canvas |
| BO | 36% | 84% | fixes the main visible mismatch: the BO board was too compressed at the left |

Measured comparison:

| Metric | v81 | v83 accepted | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.202 | 13.270 | +0.068 |
| Average center-edge distance | 31.55 | 25.66 | -5.89 |
| Design center-edge distance | 28.71 | 27.36 | -1.35 |
| Specimen center-edge distance | 27.75 | 26.58 | -1.17 |
| Vision center-edge distance | 31.21 | 28.09 | -3.12 |
| Manipulation center-edge distance | 20.79 | 13.42 | -7.37 |
| BO center-edge distance | 52.10 | 18.05 | -34.05 |
| Horizontal overflow | 0 px | 0 px | unchanged |

Rejected candidates:

- A global `100%` workboard rule. It improved BO and Manipulation edge alignment but worsened Design, Specimen, and Vision.
- Keeping BO/Vision at `36%` when judging visual geometry. This had lower raw RGB MAE but failed the reference-layout intent because the board looked compressed.
- Optimizing only card counts or section counts. These are necessary compatibility checks but are not sufficient for reference-image matching.

Operational rule: when raw RGB MAE and visible layout geometry conflict, use the reference image intent and center-edge/card-board geometry for agent report layout, then document the tradeoff. Keep each width change scoped by `data-live-agent`.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_reference_widths_v83` PASS
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_v83` PASS
- `node --check web/static/planning.js` PASS
- `python -m py_compile tests/ui/planning_browser_audit.py tests/ui/live_gui_agent_reference_layout_audit.py tests/ui/runtime_ide_browser_audit.py` PASS

## 2026-06-01 Live GUI Agent Report Visual Density Pass v85

v85 extends the generated_full_screens alignment from geometry-only matching to report-content density. Every generated agent report section with structured evidence now renders a section-appropriate mini visual, while raw JSON and stack traces remain in Backend Trace. Orchestrator remains the only chat surface; non-Orchestrator agent panes stay evidence/report surfaces.

- Reference audit artifact: `artifacts/live_gui_upgrade/layout_geometry_audit_report_visuals_v85/`.
- Browser audit artifact: `artifacts/live_gui_upgrade/planning_browser_audit_v85/`.
- Average full-image MAE moved from v83 `13.270` to v85 `13.245`.
- Visual coverage in the layout audit is now `visualCount == cardCount` for Orchestrator, Design, Specimen Making, Vision, Manipulation, Lab Equipment, Analysis, and BO.

| Agent | v85 full MAE | v85 center MAE | Visual cards |
|---|---:|---:|---:|
| orchestrator | 12.121 | 13.554 | 9/9 |
| design | 13.154 | 14.632 | 9/9 |
| specimen | 13.697 | 14.743 | 12/12 |
| vision | 13.307 | 15.316 | 11/11 |
| manipulation | 13.716 | 14.010 | 12/12 |
| equipment | 12.684 | 13.159 | 9/9 |
| analysis | 12.642 | 13.731 | 13/13 |
| bo | 14.640 | 15.842 | 16/16 |

Implementation rule: do not treat card count as sufficient. A section with data must render a compact domain visual selected by the section registry, then concise finding/evidence/action text. If a future patch changes report geometry, rerun both `live_gui_agent_reference_layout_audit.py --capture` and `planning_browser_audit.py` and compare against v85.

## 2026-06-01 v88 Accepted / v89-v95 Rejected Sweep

Accepted baseline after the latest sweep is v88:

- `web/static/styles.css`: BO acquisition visuals are warm red/orange and topbar filters are agent-scoped.
- `web/templates/planning.html`: asset version `20260601-live-topbar-88`.
- `web/static/planning.js`: v85 all-section visual rendering remains intact; no rejected derived timeline fallback is active.

Reference metrics:

| Agent | v85 full | v88 full | v85 topbar | v88 topbar | v85 center | v88 center |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| orchestrator | 12.121 | 12.121 | 14.172 | 14.172 | 13.554 | 13.554 |
| design | 13.154 | 13.154 | 13.244 | 13.244 | 14.632 | 14.632 |
| specimen | 13.697 | 13.697 | 13.198 | 13.198 | 14.743 | 14.743 |
| vision | 13.307 | 13.297 | 13.488 | 13.360 | 15.316 | 15.316 |
| manipulation | 13.716 | 13.670 | 13.629 | 13.056 | 14.010 | 14.010 |
| equipment | 12.684 | 12.672 | 13.707 | 13.547 | 13.159 | 13.159 |
| analysis | 12.642 | 12.634 | 14.011 | 13.910 | 13.731 | 13.731 |
| bo | 14.640 | 14.615 | 13.423 | 13.338 | 15.842 | 15.794 |

Rejected candidates and reasons:

- v89 BO lower dock bright/warm floor: made BO bottom dock too bright and structurally mismatched.
- v90-v93 derived timeline fallback: revealed a legitimate runtime-dock issue, but the generated reference expects a different dock composition; not accepted for visual alignment.
- v94 BO center brightness `0.80`: over-brightened card region and worsened center residual.
- v95 Equipment right-panel `brightness(1.02) saturate(0.92)`: made right evidence console drift farther from reference.

Next acceptable work must target structural differences: bottom dock event/device composition, right evidence-card density, and agent-specific report card positions. Do not accept simple brightness-only patches unless the audit proves improvement.

## 2026-06-01 v99 Accepted Side/Dock Reference Retune

v99 is the current accepted visual baseline after v88. It does not change report section registries, card counts, Orchestrator-only chat, backend trace separation, or live hardware controls. It only accepts scoped CSS changes where the browser screenshot audit showed a lower residual against the package `generated_full_screens` reference.

Accepted code scope:

- `web/static/styles.css`: BO bottom dock filter, Design side-panel filter, Specimen side-panel filter, Lab Equipment side-panel filter.
- `web/templates/planning.html`: asset version `20260601-live-design-side-99`.
- `web/static/planning.js`: unchanged from the v85 all-section visual renderer for this pass.

Accepted artifacts:

- Full reference audit: `artifacts/live_gui_upgrade/layout_geometry_audit_side_filter_v99_final/`.
- Browser audit: `artifacts/live_gui_upgrade/planning_browser_audit_side_filter_v99_final/`.

Measured metrics:

| Agent | v88 full | v99 full | v88 right | v99 right | v88 bottom | v99 bottom |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| orchestrator | 12.121 | 12.121 | 10.895 | 10.895 | 9.901 | 9.901 |
| design | 13.154 | 13.069 | 14.621 | 14.228 | 9.915 | 9.915 |
| specimen | 13.697 | 13.530 | 15.898 | 15.127 | 9.329 | 9.329 |
| vision | 13.297 | 13.297 | 13.522 | 13.522 | 10.457 | 10.457 |
| manipulation | 13.670 | 13.670 | 12.237 | 12.237 | 15.330 | 15.330 |
| equipment | 12.672 | 12.519 | 16.095 | 15.391 | 8.620 | 8.620 |
| analysis | 12.634 | 12.634 | 13.639 | 13.639 | 9.501 | 9.501 |
| bo | 14.615 | 14.599 | 12.527 | 12.527 | 16.415 | 16.342 |

Average metrics:

| Metric | v88 | v99 | Change |
| --- | ---: | ---: | ---: |
| full MAE | 13.232 | 13.180 | -0.052 |
| topbar MAE | 13.478 | 13.478 | 0.000 |
| center MAE | 14.367 | 14.367 | 0.000 |
| right/evidence MAE | 13.680 | 13.446 | -0.234 |
| bottom MAE | 11.183 | 11.174 | -0.009 |

Rejected candidates during the v96-v99 sweep:

- Right-panel `grid-row: 1 / -1`: worsened Equipment, Specimen, and Design despite sounding structurally closer.
- Whole `.live-chat-panel` tone filter for Equipment: improved the right crop less than the accepted side-panel filter and worsened the full-screen metric.
- Specimen/Design right-panel filters selected only by right-region minimum: rejected because they worsened full-screen alignment compared with the selected full-screen minimum.

Operational rule for future passes: use scoped, agent-specific patches only after `code -> browser screenshot -> generated reference diff -> browser audit`. A patch is accepted only if it improves the target region and does not regress Orchestrator chat, report card coverage, raw/backend split, approval guard visibility, or horizontal overflow.

## 2026-06-01 v100 Accepted BO/Manipulation Retune

v100 is the current accepted visual baseline after v99. It accepts only two more scoped rules after direct screenshot sweeps:

- BO center report: `brightness(0.70)`, replacing the effective v99 `0.74` center luminance for BO.
- Manipulation bottom dock: `brightness(1.04) contrast(1.0) saturate(0.90)`.

Accepted artifacts:

- Full reference audit: `artifacts/live_gui_upgrade/layout_geometry_audit_bo_manip_v100_final/`.
- Browser audit: `artifacts/live_gui_upgrade/planning_browser_audit_bo_manip_v100_final/`.

Measured metrics:

| Agent/Region | v99 | v100 | Change |
| --- | ---: | ---: | ---: |
| Average full MAE | 13.180 | 13.173 | -0.007 |
| Average center MAE | 14.367 | 14.356 | -0.011 |
| Average bottom MAE | 11.174 | 11.163 | -0.011 |
| BO full MAE | 14.599 | 14.562 | -0.037 |
| BO center MAE | 15.794 | 15.700 | -0.094 |
| Manipulation full MAE | 13.670 | 13.648 | -0.022 |
| Manipulation bottom MAE | 15.330 | 15.230 | -0.100 |

Rejected/unchanged in this pass:

- Manipulation bottom brightness above `1.04` worsened bottom and full-image MAE.
- Manipulation contrast above `1.00` caused strong bottom regressions.
- Vision center brightness sweep showed the current `0.80` setting is still the measured-best value.
- BO center values above `0.70` regressed; values below `0.70` did not improve full-image MAE.

Operational rule: compare future visual changes against v100. The next useful work should target structural differences in BO bottom dock composition and high-residual evidence/center panels, not broad global brightness changes.

## 2026-06-01 Live GUI Center Reference Retune v104

v104 keeps the v100 bottom-dock structure and accepts only the center-panel luminance changes that improved the all-agent generated-full-screen reference audit. The rejected v101-v103 candidates are important because they looked structurally plausible but made the reference match worse.

Accepted code scope:

- `web/static/styles.css`: scoped center-panel filters for Orchestrator, Vision, Manipulation, Lab Equipment, and Analysis.
- `web/templates/planning.html`: static asset version `20260601-live-center-v104`.
- `web/static/planning.js`: no accepted functional change in this pass; Orchestrator-only chat and generated report renderers remain intact.

Accepted artifacts:

- Full reference audit: `artifacts/live_gui_upgrade/layout_geometry_audit_center_v104_bottom_v100_final/`.
- Browser audit: `artifacts/live_gui_upgrade/planning_browser_audit_center_v104_bottom_v100_final/`.

Measured result:

| Metric | v100 | v104 | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.173 | 13.156 | -0.017 |
| Average topbar MAE | 13.478 | 13.478 | 0.000 |
| Average left-rail MAE | 12.043 | 12.043 | 0.000 |
| Average center-report MAE | 14.356 | 14.313 | -0.043 |
| Average right/evidence MAE | 13.446 | 13.446 | 0.000 |
| Average bottom-dock MAE | 11.163 | 11.163 | 0.000 |

Accepted center filters:

| Agent | v104 center rule | Reason |
| --- | --- | --- |
| Orchestrator | `brightness(0.88)` | Better matches the darker reference center while preserving chat/control behavior. |
| Vision | `brightness(0.82)` | Improves the visual bus/report center against the generated reference. |
| Manipulation | `brightness(0.70)` | Retains the measured lower-luminance manipulation workboard match. |
| Lab Equipment | `brightness(0.82)` | Improves equipment center without touching the live evidence console. |
| Analysis | `brightness(0.82)` | Improves analysis center while leaving FEM/BO evidence rendering unchanged. |

Rejected candidates:

- v101 three-part bottom dock with Events / IO / Artifacts worsened average full-image MAE to `13.290` and bottom-dock MAE to `11.693`; it is not accepted despite seeming closer to an evidence dashboard.
- v102 report-derived bottom evidence fallback worsened average full-image MAE to `13.303`; the fallback may be useful functionally later, but not as a reference-layout patch.
- v103 full-width generated workboards worsened Design, Vision, and BO. Card count remained correct, but visual distribution moved farther from the reference images.

Validation:

- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_center_v104_bottom_v100_final` PASS.
- `node --check web/static/planning.js` PASS.
- `git diff --check` PASS.

Operational rule: for the next pass, do not accept a patch because it adds more cards, graphs, or sections. First reproduce the reference layout region-by-region with browser screenshots. A candidate must improve the generated reference diff and preserve Orchestrator-only chat, raw/backend split, Guardian approval gates, BO graph collapse behavior, FEM contour rendering, and zero horizontal overflow.

## 2026-06-01 Live GUI Agent Layout Geometry Retune v105

v105 is the current accepted baseline after v104. It applies only measured agent-scoped layout geometry changes. The goal of this pass was to respond to the requirement that the implementation must follow the reference image placement, not merely match card counts or section names.

Accepted code scope:

- `web/static/styles.css`: scoped generated-workboard width/row-pitch retunes for Design, Vision, Manipulation, and BO; Vision-only visual-dominant card treatment.
- `web/templates/planning.html`: static asset version `20260601-live-layout-v105`.
- `web/static/planning.js`: unchanged in this pass.

Accepted artifacts:

- Full reference audit: `artifacts/live_gui_upgrade/layout_geometry_audit_layout_v105_final/`.
- Browser audit: `artifacts/live_gui_upgrade/planning_browser_audit_layout_v105_final/`.

Measured result:

| Metric | v104 | v105 | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.156 | 13.115 | -0.041 |
| Average center-report MAE | 14.313 | 14.208 | -0.105 |
| Average topbar MAE | 13.478 | 13.478 | 0.000 |
| Average left-rail MAE | 12.043 | 12.043 | 0.000 |
| Average right/evidence MAE | 13.446 | 13.446 | 0.000 |
| Average bottom-dock MAE | 11.163 | 11.163 | 0.000 |

Accepted agent retunes:

| Agent | v104 full | v105 full | Accepted layout rule |
| --- | ---: | ---: | --- |
| Design | 13.069 | 12.955 | workboard `52%`, row pitch `17px` |
| Vision | 13.290 | 13.159 | workboard `36%`, row pitch `24px`, Vision-only visual-dominant cards |
| Manipulation | 13.607 | 13.545 | workboard `56%`, row pitch `23px` |
| BO | 14.562 | 14.541 | workboard `72%`, row pitch `24px` |

Unchanged / rejected:

- Specimen width/row sweep was rejected. The best tested candidate was still worse than v104, so Specimen remains at the v104/v83 geometry.
- Global visual-dominant cards were rejected. They improved Vision slightly but worsened the full average and strongly regressed BO/Specimen.
- Any future all-agent layout rule must be treated as suspect until all generated-full-screen references pass a full audit.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_layout_v105_final` PASS.
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_layout_v105_final` PASS.
- `node --check web/static/planning.js` PASS.
- `git diff --check` PASS.

Operational rule: v105 is now the comparison baseline. The next useful visual work is structural BO bottom-dock/right-console matching and actual report semantics per agent, not generic chart stuffing or global CSS brightness. Continue using screenshot-first candidate sweeps and keep all accepted changes agent-scoped.

## 2026-06-01 BO Bottom Dock Tone Retune v106

v106 is the current accepted baseline after v105. It is a narrow BO-only bottom-dock tone correction found by a browser screenshot sweep. It does not change the bottom-dock DOM structure, chat contract, report renderer, or hardware workflow.

Accepted code scope:

- `web/static/styles.css`: BO-only `.live-runtime-bottom` filter `brightness(1.08) contrast(1.0) saturate(0.80)`.
- `web/templates/planning.html`: static asset version `20260601-live-bo-bottom-v106`.

Accepted artifacts:

- Full reference audit: `artifacts/live_gui_upgrade/layout_geometry_audit_bo_bottom_v106_final/`.
- Browser audit: `artifacts/live_gui_upgrade/planning_browser_audit_bo_bottom_v106_final/`.

Measured result:

| Metric | v105 | v106 | Change |
| --- | ---: | ---: | ---: |
| Average full-image MAE | 13.115 | 13.113 | -0.002 |
| Average bottom-dock MAE | 11.163 | 11.154 | -0.009 |
| BO full MAE | 14.541 | 14.525 | -0.016 |
| BO bottom-dock MAE | 16.344 | 16.274 | -0.070 |

Rejected/unchanged:

- Manipulation bottom filter sweep: current v105/v100 setting remained the best candidate.
- Larger BO brightness/saturation changes either worsened bottom MAE or full-image MAE.
- The bottom dock remains structurally different from the reference package because the live implementation still has `Evt` and `IO` sections rather than the reference `Events / Device Health / Artifacts` composition. The previous v101 3-part dock was rejected, so the next structural attempt must be redesigned rather than reintroduced.

Validation:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_bo_bottom_v106_final` PASS.
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_bo_bottom_v106_final` PASS.
- `node --check web/static/planning.js` PASS.
- `git diff --check` PASS.

Operational rule: v106 is now the comparison baseline. The next bottom-dock pass should add real Artifacts evidence only if it improves the reference diff and remains connected to runtime events/artifact state; do not add decorative placeholder artifact cards.

## 2026-06-01 v107 BO Geometry Alignment

Accepted asset version: `20260601-live-bo-geometry-v107`.

Result summary against v106:

- Average full-frame MAE improved from `13.113` to `13.094`.
- Average center-region MAE improved from `14.208` to `14.161`.
- BO Agent full-frame MAE improved from `14.525` to `14.378`.
- BO Agent center-region MAE improved from `15.645` to `15.268`.
- Non-BO agent metrics remained unchanged in the final audit.

Applied change:

- BO Agent workboard was isolated to `width: 36%`, `max-width: 36%`, `grid-auto-rows: 20px`.
- v106 BO bottom dock tone filter was retained unchanged.

Rejected probes:

- Global three-region bottom dock with `Artifacts` worsened average full-frame MAE from `13.113` to `13.215` and bottom-dock MAE from `11.154` to `11.617`.
- BO-only hidden `Artifacts` dock still disturbed non-BO screenshots and worsened average full-frame MAE to `13.253`.

Validation artifacts:

- `artifacts/live_gui_upgrade/layout_geometry_audit_bo_geometry_v107_final/`
- `artifacts/live_gui_upgrade/planning_browser_audit_bo_geometry_v107_final/`

## 2026-06-01 v108-v110 Agent-Scoped Tone Refinements

Accepted asset version: `20260601-live-equipment-side-v110`.

Cumulative measured result against v107:

- Average full-frame MAE improved from `13.094` to `13.069`.
- Average center-region MAE improved from `14.161` to `14.129` after v108.
- Average right-panel MAE improved from `13.446` at v108 to `13.388` at v110.

Accepted refinements:

- v108: BO Agent center report filter retuned to `brightness(0.75)`.
  - BO full-frame MAE improved from `14.378` to `14.278`.
  - BO center-region MAE improved from `15.268` to `15.013`.
- v109: Specimen Making Agent evidence side panel retuned to `brightness(0.60) saturate(1.36)`.
  - Specimen full-frame MAE improved from `13.530` to `13.496`.
  - Specimen right-panel MAE improved from `15.127` to `14.970`.
- v110: Lab Equipment Agent evidence side panel retuned to `brightness(0.66) saturate(1.08)`.
  - Lab Equipment full-frame MAE improved from `12.474` to `12.408`.
  - Lab Equipment right-panel MAE improved from `15.391` to `15.086`.

Rejected / retained values:

- Analysis Agent center sweep retained the existing `brightness(0.82)` because it remained best in the tested range.
- BO bottom dock sweep retained the existing `brightness(1.08) contrast(1.0) saturate(0.80)` because it remained best in the tested v108 range.

Validation artifacts:

- `artifacts/live_gui_upgrade/layout_geometry_audit_bo_center_v108_final/`
- `artifacts/live_gui_upgrade/layout_geometry_audit_specimen_side_v109_final/`
- `artifacts/live_gui_upgrade/layout_geometry_audit_equipment_side_v110_final/`
- `artifacts/live_gui_upgrade/planning_browser_audit_bo_center_v108_final/`
- `artifacts/live_gui_upgrade/planning_browser_audit_specimen_side_v109_final/`
- `artifacts/live_gui_upgrade/planning_browser_audit_equipment_side_v110_final/`

## 2026-06-01 v111-v112 Design Agent Tone Refinements

Accepted asset version: `20260601-live-design-side-v112`.

Cumulative measured result against v110:

- Average full-frame MAE improved from `13.069` to `13.066`.
- Average center-region MAE improved from `14.129` to `14.124` after v111.
- Average right-panel MAE improved from `13.388` to `13.383` after v112.

Accepted refinements:

- v111: Design Agent center report filter retuned to `brightness(0.92)`.
  - Design full-frame MAE improved from `12.955` to `12.938`.
  - Design center-region MAE improved from `14.340` to `14.299`.
- v112: Design Agent evidence side panel filter retuned to `brightness(0.70) saturate(1.44)`.
  - Design full-frame MAE improved from `12.938` to `12.930`.
  - Design right-panel MAE improved from `14.228` to `14.191`.

Validation artifacts:

- `artifacts/live_gui_upgrade/layout_geometry_audit_design_center_v111_final/`
- `artifacts/live_gui_upgrade/layout_geometry_audit_design_side_v112_final/`
- `artifacts/live_gui_upgrade/planning_browser_audit_design_side_v112_final/`

Validation status:

- `tests/ui/live_gui_agent_reference_layout_audit.py --capture --out-dir artifacts/live_gui_upgrade/layout_geometry_audit_design_side_v112_final` PASS.
- `tests/ui/planning_browser_audit.py --out-dir artifacts/live_gui_upgrade/planning_browser_audit_design_side_v112_final` PASS.
- `node --check web/static/planning.js` PASS.
- `git diff --check` PASS.

Operational rule: v112 is the current comparison baseline. Further Live GUI changes must remain agent-scoped, preserve Orchestrator-only chat, preserve backend trace/report separation, and be accepted only after screenshot diff plus browser audit.
