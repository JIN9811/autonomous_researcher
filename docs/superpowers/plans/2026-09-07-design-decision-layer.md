---
doc_type: plan
subtype: implementation
status: active
authority: execution
audience: [developer, maintainer]
scope: [design_agent, evaluation, decision_tools]
summary: Design의 근거 기반 평가와 국소 LLM 판단층을 기존 인계에 연결한다.
execution_status: in_progress
governing_design: docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
related_docs: [docs/agents/design_agent.md]
supersedes: []
---

# Design Decision Layer Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. No commit/push without a separate user request.

**Goal:** 기존 Design 경로에서 근거를 평가하고 LLM이 채택·추가 확인·상위 반환을 결정하게 한다.

**Architecture:** 후보 준비와 최종 인계를 분리한다. `agents/design_decision.py`는 평가 계약과 agent-local 툴 dispatcher를 소유한다. 기존 함수, `AgentContext.complete`, 반환 필드 및 아카이브를 재사용한다.

**Tech Stack:** Python, existing LLM backend, pytest, JavaScript/Node, Markdown/Graphviz.

**Spec:** [5영역 계약](../specs/2026-09-07-five-area-agent-restructuring-contract-design.md).

## Global Constraints

- BO/LHS 지정점·사용자 고정 조건·장비 브릿지·물리 경로를 변경하지 않는다.
- 정상 LLM 작업은 실제 결정과 툴 호출을 포함하며, 전체 계산을 모델로 치환하지 않는다.
- 정형 비LLM 테스트는 명시적으로 구분한다. LLM 실패를 정상 결정으로 기록하지 않는다.
- 합성점수 필드는 기존 소비자용으로 유지하되 새로운 평가·LLM 입력에서는 제외한다.
- 새 후보의 성능 근거가 없으면 미평가로 기록한다. 다른 후보/실험의 점수를 복사하지 않는다.
- 문서·표·SVG와 비구동 검증까지 같은 변경에 포함한다. 실장비는 구동하지 않는다.

## Task 1: Evaluation and decision boundary

**Files:** `agents/design_decision.py`, `agents/design_agent.py`, `backends/prompt_registry.py`, `tests/unit/test_design_decision.py`, `tests/unit/test_design_agent.py`.

**Interfaces:** `candidate_evaluation(agent, state, prepared, candidate) -> dict`; `decide_design(agent, state, ctx, prepared) -> dict`. Prepared context contains existing candidates, constraints, objective and prior summaries. Decision returns selected candidate ID or an explicit failure plus trace.

- [x] Add tests proving that synthetic scores do not enter evidence, invalid/repaired candidates cannot be accepted, locked parameters cannot change, and the model can select a non-first valid candidate.
- [x] Run new tests and observe failure before implementation.
- [x] Split preparation/finalization, implement strict structured tool requests with bounded calls/time, explicit failure/cancellation and local candidate/evidence queries.

```python
# Boundary exercised by tests (response format, not arbitrary executable text):
request = {"tool": "accept_candidate", "arguments": {"candidate_id": "cand-1-08"},
           "reason": "Compatible with the requested design and checked constraints",
           "evidence_refs": ["candidate:cand-1-08"]}
```

- [x] Run Design tests and inspect request/result traces. Keep existing mode-specific input/output tests; change only the old forced-LLM-success-on-error expectation.

## Task 2: Consumers and evaluation display

**Files:** `agents/guardian_agent.py`, `web/static/planning.js`, focused tests under `tests/unit/`.

**Interfaces:** new `design_evaluation` and `design_decision` fields are additive; legacy score fields remain readable. New displays use validity, per-constraint margins, mass/time estimates and explicit unassessed performance.

- [x] Add failing tests for new evidence display and Guardian excluding marked legacy proxy from scientific comparison.
- [x] Implement evidence-aware display branches while preserving rendering of historical reports.
- [x] Check controller planning and adjacent agent tests; do not modify bridge execution or BO optimization.

```python
# New evidence contract keeps old consumers readable without mislabelling the value.
assert spec["score_semantics"] == "legacy_heuristic_compatibility_only"
assert spec["design_evaluation"]["performance"]["status"] == "unassessed"
```

## Task 3: Documentation and verification

**Files:** existing `docs/agents/design_agent.md`, its three DOT/SVG pairs, relevant index/matrix/standard and validator inventory, this plan.

- [x] Replace existing Reference with five-area content, tool/API tables, authority boundaries and source-linked verification.
- [x] Render three figures and validate source/render consistency, links and manifest.
- [x] Run focused Python/Node tests and non-actuating integration with a controlled model; attempt actual model verification only through an available inference endpoint without equipment access.
- [x] Record actual-model and hardware verification separately; do not claim prior physical evidence validates this change.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/unit/test_design_agent.py tests/unit/test_design_decision.py tests/unit/test_planning_design_report_js.py tests/unit/test_controller_planning.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/validate_documentation.py
git diff --check
```

## Verification

Baseline: 50 Design/documentation tests passed; five existing Pydantic field-name warnings. Full documentation manifest has pre-existing Windows bridge/PLC document findings, outside this change.

### Implemented boundary and review corrections

- Design only: prepare → evidence inspection/accept/return tools → checked finalization. Existing BO/LHS generation, graph transitions, device bridges and mode policies remain in place.
- Role-local JSON tool dispatch, not arbitrary code execution or new device tools. Normal LLM failures cannot silently select a deterministic winner.
- Reviewer-found failure-schema mismatch fixed with a Design-specific blocked-result contract. Planning requires a fresh successful invocation, acceptance and a nonblocking existing Guardian post-gate. Previous specs cannot substitute for a failed/blocked decision.
- Existing controller adaptation is preserved. Changed geometry gets a refreshed fingerprint and unassessed current evaluation; original candidate checks remain `selection_evaluation`. Current report/card evidence and nested/top-level handoff fingerprints agree.
- Completed observations are archived incrementally, including on cancellation. GUI metadata retains bounded evaluation/decision summaries, not full inference traces.

### Non-actuating test record — 2026-09-07

| Check | Result | Scope |
|---|---|---|
| Design, evaluation/tools, documentation, validation policy, Node report helpers | 77 passed; 2 known baseline JS tests deselected | Current focused suite; no devices |
| Current controller acceptance, return, timeout, malformed response, pre-gate and post-gate blocking | 6 passed | Existing LangGraph/controller route for model outcomes; isolated gate regression tests |
| Specimen retry → next Design series plus five focused Design cases | 6 passed | Final targeted rerun of the existing multi-cycle controller path with controlled model responses |
| Guardian, archive, BO, Specimen and LangGraph suites | 174 passed | Adjacent unit regression run before the final controller-only review fixes |
| Broad controller suite earlier in this work | 95 passed; 4 known baseline tests deselected | Final controller changes additionally covered by the focused tests above |
| JavaScript syntax / whitespace | Passed | `node --check`, `git diff --check` |
| Design figures | 3 DOT/SVG pairs byte-identical after rerender | Includes new Connections figure |
| Whole-repository documentation validation | 27 pre-existing findings remain | Windows PyAutoGUI Reference and older PLC Design only; no findings in changed docs |

Two baseline JS failures concern missing test-fixture helper dependencies:
`test_live_agent_events_are_scoped_to_current_run` and
`test_normal_artifact_events_do_not_raise_agent_unread_alarm`.
Four baseline controller failures concern prior Vision/manipulation completion expectations:
`test_controller_merge_vision_confirmation_marks_specimen_completion`,
`test_planning_tail_continues_original_loop_after_specimen`,
`test_live_gui_planning_tail_agent_messages_keep_cycle_metadata`, and
`test_live_gui_test_planning_series_runs_twenty_design_cycles`.
These were reproduced against baseline code without resetting this checkout.
The 2026-09-08 pre-commit rerun of Design, decision, Guardian, documentation,
controller-planning and planning-report tests completed with **184 passed and
the same six baseline failures** (221.02 seconds). No new failure was observed
in that selected suite; this is not a whole-repository green-suite claim.
An intermediate broad run also caught a new compact-report field omission; it
was fixed and the exact controller regression now passes. This is not a claim
that the unfiltered repository suite is green.

### Registered local model verification

Use ATR's existing vLLM registration, model router and client options without overrides.
Actual `DesignAgent.run` → `AgentContext.complete` → decision-tool dispatch passed
with OpenAI `gpt-5.5` in 6.34 seconds and registered vLLM `gemma4:31b` in 12.11 seconds.
Both accepted `cand-1-01` and preserved that candidate through the specification
and handoff. The local run used the existing 31B model fallback after the E4B
primary connection failed. Operational GUI settings were not changed.
See the [verification record](../../paper/evidence/2026-09-07-design-gemma31b-virtual-api-verification.md).

## Additional Acceptance: API + Virtual Closed Loop + Registered Models

This plan remains `in_progress`. Preserve the existing GUI and device paths;
use non-actuating verification for this change.

- [x] Check the registered 31B inference client with unchanged request options.
- [ ] Verify readiness and actual inference of the registered Design model.
- [x] Verify Design decisions and tool dispatch through the existing agent path using API and registered vLLM 31B; retain actual backend/model/fallback evidence.
- [ ] Execute the existing virtual workflow through HTTP, including BO → next Design feedback.
- [ ] Verify requested/realized variables, model/tool traces, artifact/API retrieval and terminal result.
- [ ] Record only measured registered-path results; distinguish inference, agent, API and closed-loop acceptance.

No commit or push is included in this implementation request.
