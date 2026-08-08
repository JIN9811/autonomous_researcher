# Knowledge Visualization Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Visualize continuously collected, updated, retrieved, and consumed Knowledge activity in Live GUI and provide a dedicated Knowledge Graph/Ontology workspace.

**Architecture:** The append-only Knowledge ledger remains the visualization source. A bounded aggregation service converts ledger events into per-cycle activity bins, while the existing graph and ontology services provide workspace data. Live GUI updates one preserved ECharts canvas without rebuilding the report; the standalone workspace queries only allowlisted, capped subgraphs.

**Tech Stack:** Python 3.12, FastAPI, JSONL ledger, Neo4j, vanilla JavaScript, locally bundled ECharts, pytest, Playwright/Selenium browser audit.

## Global Constraints

- Existing Knowledge Agent, BO, Guardian, and MCP contracts remain additive and backward compatible.
- Live activity values must be derived from recorded events, never fabricated UI metrics.
- Raw Cypher remains forbidden; query depth is at most 4 and results are capped at 100 nodes/edges.
- The Live chart is preserved across report patches and updates only when its payload changes.
- The full graph is never rendered in Live GUI.

---

### Task 1: Knowledge Activity Aggregation

**Files:**
- Create: `knowledge/activity.py`
- Modify: `agents/knowledge_agent.py`
- Modify: `knowledge/service.py`
- Modify: `app/main.py`
- Test: `tests/unit/test_knowledge_activity.py`
- Test: `tests/integration/test_knowledge_ontology_api.py`

- [x] Write tests for deterministic per-cycle aggregation and a bounded activity API.
- [x] Run the tests and confirm failure because the activity service/API do not exist.
- [x] Add real activity counts to graph-bound Knowledge event summaries and aggregate ledger records.
- [x] Expose `GET /api/knowledge/activity?run_id=&limit=20`.
- [x] Run focused tests until green.

### Task 2: Live Knowledge Activity Histogram

**Files:**
- Modify: `web/static/planning.js`
- Modify: `web/static/styles.css`
- Modify: `web/templates/planning.html`
- Test: `tests/integration/test_live_gui_runtime_layout.py`

- [x] Write a failing layout contract for the preserved Knowledge Activity chart.
- [x] Add a Matplotlib-style white ECharts stacked histogram with cycle/count axes and four named series.
- [x] Poll only while the Knowledge report is selected and patch the chart payload without rebuilding other cards.
- [x] Preserve the canvas across report refreshes and resize safely.
- [x] Run focused integration tests.

### Task 3: Knowledge Workspace

**Files:**
- Create: `web/templates/knowledge.html`
- Create: `web/static/knowledge.js`
- Create: `web/static/knowledge.css`
- Modify: `web/templates/index.html`
- Modify: `web/static/app.js`
- Modify: `app/main.py`
- Test: `tests/integration/test_knowledge_workspace.py`
- Test: `tests/ui/knowledge_workspace_browser_audit.py`

- [x] Write failing route, markup, and API-wiring tests.
- [x] Add `/knowledge` and a Main GUI workspace card with live backend status.
- [x] Implement Graph Explorer, Memory, Ontology, Sync, and Project Graph tabs.
- [x] Render bounded ECharts graphs with node inspector, preset filters, provenance expansion, and no raw Cypher input.
- [x] Run API and browser layout tests at 1920x1080.

### Task 4: Verification and Documentation

**Files:**
- Modify: `docs/knowledge/knowledge_graph_operations.ko.md`
- Modify: `docs/runtime/current_code_snapshot.md`

- [x] Run Knowledge unit/integration regressions.
- [x] Run Live GUI static and browser audits.
- [x] Query the real Neo4j service and verify activity, graph, ontology, and sync views.
- [x] Inspect browser screenshots for overflow and unreadable labels.
- [x] Document the Live histogram and Knowledge Workspace operating procedure.
