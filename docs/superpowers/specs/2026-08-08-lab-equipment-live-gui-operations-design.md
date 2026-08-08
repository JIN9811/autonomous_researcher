# Lab Equipment Live GUI Operations Design

## Objective

Update only the Lab Equipment Agent report in the Live GUI so the current Windows PyAutoGUI bridge, deterministic program/skill execution, bounded recovery, evidence, and handoff state are understandable at a glance.

The Equipment Agent workflow, bridge commands, skill recorder/compiler/runtime, Guardian policy, Windows Equipment Workspace, and every other agent report remain unchanged.

## Scope Boundary

### In scope

- Recompose `renderEquipmentDashboardCards` using the existing Live GUI card system.
- Reuse existing `renderDashboardCard`, tone classes, metrics, rows, expandable details, and progress-node styling.
- Read the existing Equipment report contracts:
  - `equipment_report`
  - `equipment_result`
  - `equipment_skill_execution`
  - `equipment_skill_exception`
  - `utm_data_ready_packet`
  - `equipment_handoff`
- Read passive Windows bridge configuration/readiness state from the existing API when the Equipment report is active.
- Provide header actions for bridge test, opening the existing Windows Equipment Workspace, and manual refresh.
- Preserve unknown and idle states without presenting them as failures.

### Out of scope

- Equipment Agent execution order or handoff logic.
- Windows bridge HTTP behavior, program execution, recording, skill compilation, deployment, or recovery behavior.
- Guardian gates and policies.
- `/equipment/windows` layout or behavior.
- Other Live GUI agent cards.
- New global card styles or a new visual theme.
- Automatic physical execution from a report-card action.

## Layout

The layout follows existing Vision, Specimen, and Manipulation report conventions.

### First row: three operational cards

1. **Bridge / Runtime** (`span: 4`)
   - Bridge connection state
   - Selected target or candidate alias
   - Desktop resolution and PyAutoGUI readiness
   - Required runtime dependency count
   - Header actions: `TEST`, `OPEN`, `REFRESH`
   - Expandable details: server version, script version, optional dependencies, last refresh time

2. **Active Program / Skill** (`span: 4`)
   - Program ID
   - Exact skill ID and version
   - Current segment and completed segment count
   - Target profile
   - Model snapshot only when recovery reasoning actually invoked a model

3. **Recovery Boundary** (`span: 4`)
   - Current attempt and bounded maximum when recorded
   - Failure code and checkpoint
   - Allowed recovery operations
   - Expandable recovery history

### Second row: full-width execution flow

4. **Agentic Progress** (`span: 12`)
   - Resolve profile/version
   - Validate bridge/contract
   - Execute registered protocol
   - Verify evidence
   - Handoff

The node state is derived only from recorded report/skill execution fields. A later node cannot appear complete unless its corresponding evidence exists. Existing Gate Matrix, screen checks, and Equipment events move into this card's expandable details.

### Third row: evidence and handoff

5. **Execution Evidence** (`span: 8`)
   - Passed/total screen assertions
   - UTM row count
   - Parse readiness
   - Last relevant runtime event
   - Expandable paths, checksums, screenshots, and request-audit references

6. **Handoff** (`span: 4`)
   - Handoff status
   - Failure code when present
   - Next agent
   - Artifact/packet schema
   - Guardian requirement

## Existing Style Reuse

- Use `renderDashboardCard` for every card.
- Use the existing Equipment tone and global `success`, `warning`, `danger`, `idle`, and `artifact` tones.
- Use existing report metric and row renderers.
- Use the existing card-header action style used by Vision runtime controls.
- Use the existing expandable-details interaction instead of a new modal or panel.
- Use the existing Agentic Progress node language and spacing used by Specimen and Vision.
- Do not add an Equipment-specific theme, font, background, border radius, or global CSS override.

## Data Flow

1. Live GUI renders the current run state through the existing report extraction helpers.
2. When the Equipment report becomes active, the frontend may read the existing passive `/api/equipment/windows/config` endpoint to supplement bridge health metadata not present in the run report.
3. The supplemental state is held in a small Equipment-only frontend cache.
4. Manual `REFRESH` replaces only that supplemental cache and rerenders the Equipment report.
5. `TEST` calls the existing `/api/equipment/windows/test` endpoint. It performs bridge health/program discovery only and does not execute a program.
6. `OPEN` opens the existing `/equipment/windows` workspace in a separate tab.
7. Run-event updates remain the source of truth for execution, evidence, recovery, and handoff state.

No new backend route is required unless the existing config response lacks a field already returned by bridge health. In that case, only the existing config response may be extended with passive, non-secret fields.

## State Rules

- `ready`, `connected`, `passed`, and recorded completion use success tone.
- Active execution uses the existing running/warning tone.
- Missing optional metadata uses idle/unknown presentation.
- Disconnection is warning while Equipment is idle; it becomes blocking/danger only when the current Equipment run requires the bridge.
- Stale supplemental health never overrides newer run-event evidence.
- Tokens and secret values are never rendered or included in frontend state.
- A failed refresh preserves the latest successful display and adds a stale/warning marker; it does not clear the report.

## Error Handling

- Header actions are disabled only while their own request is in flight.
- Bridge test failures remain inside Bridge / Runtime and do not generate unrelated agent completion or handoff events.
- Unknown runtime dependencies are displayed as unknown rather than missing.
- Empty execution reports render an idle shell with the expected five progress nodes.
- The Equipment report must remain usable when the Windows bridge is offline.

## Verification

1. Unit/static tests verify the six-card structure, labels, actions, and no secret rendering.
2. Existing Equipment extraction tests verify old report payloads still render.
3. API tests verify config and test actions use existing routes and never call `/execute`.
4. Browser verification at 1920x1080 checks alignment against Vision, Specimen, and Manipulation cards.
5. Browser verification checks responsive stacking without changing other agent reports.
6. Regression tests confirm other report renderers and Equipment Agent workflow behavior are unchanged.

## Acceptance Criteria

- The Lab Equipment report shows the selected bridge/runtime, active program or skill, recovery boundary, five-stage progress, evidence, and handoff without opening the management workspace.
- Program/skill registration and recording remain exclusively in `/equipment/windows`.
- `TEST` cannot actuate equipment.
- `OPEN` reaches the existing management workspace.
- Existing Equipment run reports remain compatible.
- No visual or behavioral changes occur outside the Equipment Live GUI report and its passive status wiring.
