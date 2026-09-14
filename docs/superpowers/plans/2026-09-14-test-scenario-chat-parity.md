# Test Scenario Chat Parity Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task in the existing checkout, as requested by the operator.

**Goal:** Automate test scenario input through the ordinary planning chat while preserving the orchestration graph and mode-specific device policies.

**Architecture:** The operator selects a test mode. A controller-owned input driver generates a scenario using the existing model route and submits it through `planning_message`. Subsequent automatic replies use that same semantic admission boundary; the driver cannot dispatch agents or fabricate execution evidence.

**Tech Stack:** Python, asyncio, existing LangGraph runtime, pytest.

**Spec:** Operator-approved conversation: test keywords initiate automatic scenario input and replies on the existing orchestration path; fix the verified parity defects without actuating equipment.

## Global Constraints

- Work in the existing checkout; preserve unrelated uncommitted work.
- No hardware actuation, commit, tag, or push. Initial verification left the server unchanged; the approved intake-bug follow-up applies the fix with an idle-only server restart.
- Keep graph, bridge execution, cooling/ejection policies and physical completion checks intact.
- Automatic input must remain bound to the selected mode, current session and pending request.
- Never manufacture credentials, missing robot policies, transfer confirmations or device success.

## Task 1: Repair boundary parity

Files: `agents/manipulation/agent.py`, `app/controller.py`, `tests/unit/test_test_scenario_chat.py`.

- [x] Add failing cases for a physical test with no policy, explicit ejection approval/denial, and conditional Manipulation chat events.
- [x] Run the focused cases with external I/O denied.
- [x] Restrict fake profiles/policies to virtual execution; use effective physical mode for preflight. Preserve explicit ejection choices over saved defaults; use explicit normal-run start intent for normal print/ejection defaults.
- [x] Derive message eligibility from registered executable stages, not a single default route.
- [x] Re-run focused cases and existing agent/controller checks.

## Task 2: Automate chat input, not execution

Files: `app/test_scenario.py` (input driver), `app/controller.py` (lifecycle/integration), `tests/unit/test_test_scenario_chat.py`.

- [x] Add tests proving that generated scenarios re-enter `planning_message`, retain mode policy and appear as automatic operator input.
- [x] Add cases for duplicate starts, stale replies, stop/reset, missing information and physical-confirmation requests; enforce one reply per pending ID.
- [x] Generate scenario values using the existing test prompt, then submit ordinary chat text plus constraints; remove the direct test-to-Design handoff.
- [x] Answer supported current planning requests through the same chat classifier and pending-ID checks. Leave unsupported/physical confirmations waiting for the operator.
- [x] Keep task lifecycle separate from the execution task; do not reset stop flags or create a new run from an automatic follow-up.
- [x] Verify virtual/installed-printer/physical-print policy payloads through the shared admission route using controlled model responses and mocked device boundaries.

## Task 3: Verification and documentation

Files: relevant controller/runtime test fixtures, `docs/runtime/test_mode.md`, `docs/agents/orchestrator_agent.md`, `docs/agents/manipulation_agent.md`.

- [x] Update stale test model fixtures at the module model boundary without bypassing ORC review.
- [x] Run focused regressions and non-actuating mode/loop suites; report failures rather than relax gates.
- [x] Document auto-input semantics, stop conditions and verification limitations; keep validation evidence out of public knowledge stores.
- [x] Inspect diff and leave the result uncommitted for operator review.

## Verification record — 2026-09-14

All runtime checks used external network/process/device denial. Model responses and device receipts were controlled test inputs, not new API/local-model or physical validation.

| Check | Result |
|---|---|
| Automatic-input and selected chat regressions | 32 passed, including 24 automatic-input/parity cases |
| Manipulation, recovery/status and execution-profile matrix | 97 passed (includes overlapping automatic-input cases) |
| Equipment, stacked workflow, clearance and agent decision tests | 242 passed |
| Current graph tail after Specimen, plus saved ejection regression | 2 passed; placement, Equipment, disposal, clearance, Analysis, Knowledge, BO and Guardian preserved |
| Extended 20-cycle controller fixture | First three cycles reached Guardian continuation; audit interrupted during the fourth cycle, not a 20-cycle pass |
| Full legacy controller selection | Not green: an unchanged retained-Vision assertion failed, and the unrestricted selection exceeded its audit time budget |
| Independent read-only review | Two automatic-admission lifecycle issues found, reproduced and fixed; follow-up review found no remaining critical/important issue in scope |

The lifecycle regression covers fast new-run allocation followed by ORC deferral, automatic continuation with `new_series=False`, and a second runtime question. Completion of an admission task does not discard its owned run identity. No production graph or bridge execution gate was relaxed to obtain these results.

Verification artifacts remain in ignored run/test storage, outside published knowledge corpora. No server restart, commit, tag or push was performed.

## Follow-up: real-model intake verification

The Live GUI exposed a gap not covered by controlled classifier fixtures: established test commands were interpreted as unsupported Setup changes. The system prompt and classification packet now describe scenario-start semantics explicitly, while retaining semantic decisions and all downstream gates. Negative execution takes precedence over a positive command substring; negating a physical test does not request a virtual replacement.

| Real-model check | Result |
|---|---|
| Initial GPT API reproduction | All five established test-start forms misclassified before the correction |
| Final classifier matrix | 68/68 passed: 17 cases, two repetitions, GPT API and local Gemma 31B |
| Served models | `gpt-5.5-2026-04-23`, `gemma4:31b`, through registered routes |
| Controller startup matrix | 12/12 passed: three test profiles, installed-printer alias, normal experiment with inputs, normal experiment missing inputs, on each provider |
| Execution boundary | Actual classification, scenario generation, shared chat re-entry and admission; substituted handoff stops before Design dispatch |
| External guard | No device calls or denied-access attempts; only registered inference endpoints permitted |
| Final non-actuating regressions | 98 passed; four earlier 3-second wait failures passed isolated rerun without changing production or test timeouts |

The normal complete-input experiment retained normal print/ejection intent without test-policy leakage. Missing inputs requested operator information without dispatch. These are intake/admission checks, not additional physical-cycle evidence. Reproduce with `scripts/verify_test_mode_intake.py`; reports are local ignored validation artifacts.

The idle application server was restarted after the intake fix. Read-only session status confirmed `idle`, `is_running=false` and `is_planning_busy=false`; no live run command was submitted or replayed automatically.
