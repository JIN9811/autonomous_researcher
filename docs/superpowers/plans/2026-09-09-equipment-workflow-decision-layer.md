# Equipment Workflow Decision Layer Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for the tightly coupled runtime changes; independent decision-contract tests and final review may be delegated.

**Goal:** Execute the configured stacked Skill Flow through a bounded LLM tool request, then assess terminal evidence and screenshots without repeating successful work.

**Architecture:** Keep the existing Flow, exact Skills, Runtime and worker. An Equipment-owned boundary handles selection and terminal review. A persistent invocation record prevents duplicate starts; a same-invocation checkpoint permits only proven-safe failed-block recovery. Existing in-flow Vision/safety checks remain, but nested automatic LLM recovery is disabled for the managed Flow.

**Tech Stack:** Python, existing AgentContext and LLMImageInput, EquipmentRuntimeService, pytest, Graphviz SVG.

**Spec:** Approved conversation plus [five-area contract](../specs/2026-09-07-five-area-agent-restructuring-contract-design.md).

## Global Constraints

- No physical equipment calls, service restarts, deployment changes or changes to bridge programs during development.
- Preserve the current checkout and existing production graph/handoff contracts.
- LLM decisions only before execution and after normal/error termination; no intermediate model polling.
- Never repeat a completed block or segment. Unknown effects, cancellation, absent proof of no action or unsafe resume must stop automatic replay.
- Registered API/local model routing and shared image inputs only; TEST responses explicitly labeled non-LLM.
- Model tool arguments reference server-owned proposals, never arbitrary commands, coordinates or paths.
- Recovery budget is bounded; every recovery requires subsequent observation and an explicit resume decision.
- Commit/tag/push require a separate user request for this agent.

## Task 1: Bounded decision and multimodal evidence

**Files:** `agents/equipment_decision.py`, `tests/unit/test_equipment_decision.py`.

**Interface:** `async decide_equipment(state, ctx, *, phase, context, proposals, images=None) -> dict`. Each proposal maps a tool name to immutable arguments. Return `status`, `request`, `llm_used`, `scope_valid` and evidence/model audit. `accepted` and `deterministic_test` are valid protocol statuses, not completion facts.

- [x] Write tests for exact proposals, malformed/unknown tool arguments, prompt injection as data, scope mutation/stop, timeout and mock rejection, image delivery and explicit TEST labeling.
- [x] Run `pytest -q tests/unit/test_equipment_decision.py` and record the expected missing implementation failure.
- [x] Implement context-grounded selection/review/recovery prompts; call the registered Equipment owner context. Validate exact JSON and evidence references; snapshot and recheck state. Archive decisions without image bytes.
- [x] Re-run the same tests.

```python
decision = await decide_equipment(state, ctx, phase="select", context=context,
    proposals={"execute_stacked_workflow": {"proposal_id": "bound-id"},
               "request_operator": {"proposal_id": "bound-id"}})
assert decision["request"]["arguments"] == {"proposal_id": "bound-id"}
```

## Task 2: Existing Flow integration and duplicate prevention

**Files:** `agents/equipment_workflow.py`, `agents/equipment_agent.py`, `tests/unit/test_equipment_workflow_decision.py`.

**Interface:** `async run_decided_workflow(agent, state, ctx, flow) -> AgentResult`; calls existing `_run_equipment_skill_flow(..., checkpoint=checkpoint)` with a private mutable checkpoint. Existing direct/standalone calls omit it and keep their behavior.

- [x] Add failure-injection tests exercising real Flow execution and fake worker/model boundaries: completed work once, failure after success, unknown timeout, concurrent/repeated calls, next loop isolation, rejection before execute, post-review rejection, stop and scope change.
- [x] Run the tests red before implementation.
- [x] Claim the run/loop/specimen invocation through an isolated namespace of the existing durable EquipmentRuntimeService before any await. Repeated invocations return recorded terminal output or explicit blocked state, not another execution.
- [x] Dispatch only a model-approved exact Flow; preserve deployed Skills and preconditions. Checkpoint completed transitions/results/runtime context and disable per-Skill automatic recovery for this managed invocation.
- [x] After terminal return, capture a screenshot with the existing tool and load its validated local artifact into LLMImageInput. Bind capture identity to the invocation. A screenshot is supporting evidence, not permission to override CSV/readiness gates.
- [x] Offer read-only diagnostics and bounded non-physical recovery (wait or focus on the configured window) only when supported. A failed block is eligible for retry only with no-action evidence and no previously completed segments inside that block. Recheck the same boundary before resuming. Preserve all earlier blocks and transitions.
- [x] Re-run tests and existing Equipment suites.

```python
assert executed_blocks == ["prepare", "measure", "measure", "export"]
# The first measure attempt must prove zero actions; prepare is never repeated.
assert first_result.data["equipment_decisions"]
assert repeated_result.data["equipment_workflow_cached"] is True
```

## Task 3: Documentation, regression and review

**Files:** existing `docs/agents/equipment_agent.md`, its DOT/SVG figures, API matrix, this plan.

- [x] Update existing reference with 5–7 line status, five-area table, tool/recovery contracts, current prompt rules, duplicate-prevention limits and SVG/source diagrams.
- [x] Run Equipment/Skill/Runtime/Flow/Guardian tests and a non-actuating closed-loop test. Record full-loop versus preflight-only evidence distinctly.
- [x] Independently review replay, cancellation, multimodal provenance and handoff boundaries; address material findings.
- [x] Validate changed governed docs, render diagrams and inspect bounds; report only observed results and remaining limitations.

## Progress / evidence

Plan approved for implementation in conversation. Existing bridge and standalone paths are retained. Work is in the user-selected current checkout; no deployment or Git publication is part of this turn.

- Baseline Equipment/Skill/Flow suite: 142 passed before edits.
- Red/green evidence includes initially missing LLM selection, duplicate mode-change execution, ignored runtime approval changes, malformed simulated PNG, per-segment stop/scope, and contradictory zero-action counters.
- Independent review findings were fixed and re-reviewed: managed segment callback, actual `runtime_approvals` ownership, and live-versus-simulated screenshot provenance. Screenshot identity is agent-bound request provenance; absent worker attestation is not invented.
- The non-actuating production-graph two-cycle test passed in 85.36 s: `runs/run-20260908T172240Z-763676`. This is graph compatibility evidence, not registered-model or physical execution proof. Separate real-Flow tests exercise selection, terminal review and recovery with controlled model/worker boundaries.
- LangGraph runtime suite: 70 passed, 10 existing warnings, 196.81 s.
- Historical read-only probe: `scripts/verify_equipment_decisions.py --execute --image <archived-screen> [--result <archived-result>]`; empty tool registry, separate historical and synthetic cases, source hashes checked after inference.
- Registered routing retains the existing `e4b` model role. `equipment_workflow_decision` gets its own 768-token local response allowance; generic `tool_formatting` remains 96. No backend, model deployment or thinking setting changes. Terminal prompts project actual block summaries, failure/action evidence, CSV and readiness instead of repeating raw artifact trees.
- Additional startup checks exposed `test_agent_context_uses_openai_backend_as_last_fallback`, whose local-first expectation conflicts with the unchanged API-first fallback implementation. It is reported separately, not repaired by changing provider precedence.
- Final scoped regression suite after local-prompt correction: 505 passed, 5 warnings, 14.43 s. Additional startup checks excluding the separately reported fallback-order test: 7 passed, 1 deselected. Earlier independent decision/workflow review: 91 tests passed, no material findings.
- Local diagnostics reproduced whole-response JSON code fences. Added a narrowly bounded unwrap with red/green tests; prose, multiple objects, duplicate keys and foreign arguments remain rejected. Decision suite: 66 passed.
- Local prompt correction: current-phase guidance and immutable server-built response options distinguish phase labels from tools. Red/green regression checks ensure evidence cannot supply its own response options and invented phase tools remain rejected, with no auto-repair or extra model invocation. Equipment decision/workflow/probe suite: 116 passed.
- Final registered-provider historical/synthetic probe: API `gpt-5.5` 7/7 scored expectations; local vLLM `gemma4:31b` 7/7. Historical terminal acceptance passed on both (3.437 s API, 25.539 s local). Synthetic success remains unscored. Five additional local zero-action UI recovery decisions passed, including two reversed-proposal-order cases. Exact arguments, evidence references and all existing safety gates remain enforced; no test expectations, model deployment or inference settings were changed for this correction.
- Final reports: `/tmp/atr-equipment-decisions-jb9vuvkl/results.json` and `/tmp/atr-equipment-decisions-dx3d0vk6/results.json`; source image, archived result and Flow hashes unchanged in both. These are offline decisions using archived images, not current physical recovery execution.
- Both changed governed reference documents pass validation. DOT/SVG figures were rendered and visually checked, including the final dedicated-role label. Compilation and `git diff --check` pass. No device actuation, deployment, service restart, commit, tag or push was performed.
