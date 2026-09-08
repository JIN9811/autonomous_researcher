---
doc_type: evidence
subtype: test_report
status: active
authority: evidentiary
audience: [developer, researcher, reviewer]
scope: [design_agent, virtual_closed_loop, api, local_model]
summary: Records successful DesignAgent decisions through the registered API and vLLM 31B routes, with closed-loop acceptance still pending.
evidence_date: 2026-09-08
method: Run the current DesignAgent and AgentContext with registered backend clients and model routing in isolated non-actuating state, then inspect local tool dispatch, handoff and archives.
related_docs:
  - docs/agents/design_agent.md
  - docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
  - docs/superpowers/plans/2026-09-07-design-decision-layer.md
supersedes: []
---

# Design / Registered vLLM Verification

## Status

**DesignAgent response, local decision-tool dispatch and handoff passed through both OpenAI API and registered vLLM Gemma 31B. Full HTTP closed-loop acceptance remains pending.**

## DesignAgent Verification

The current `DesignAgent.run` generated its candidate/evidence prompt and called
`AgentContext.complete` through the existing lease, router, backend clients and
decision parser. No model response or local decision-tool result was mocked.

| Branch | Actual model/backend | Model-call elapsed / complete agent elapsed | Decision and handoff |
|---|---|---|---|
| Saved API-priority configuration | `gpt-5.5` / OpenAI | 6.31 / 6.34 seconds | `accept_candidate(cand-1-01)`; accepted; same candidate in specification and handoff |
| Local branch, API priority disabled only in the isolated test context | `gemma4:31b` / vLLM | 12.06 / 12.11 seconds | `accept_candidate(cand-1-01)`; accepted; same candidate in specification and handoff |

- Both returned `success=true`, `llm_used=true`, `validity.status=pass` and a completed agent archive. Candidate performance remained `unassessed`, with no invented performance value.
- API priority follows the existing saved-key behavior. The operational GUI's API configuration was not changed.
- The local branch retained the registered `gemma4:e4b-it-nvfp4` primary and `gemma4:31b` fallback. E4B was unreachable; the existing model fallback produced the 31B response, recorded as `role=e4b:model_fallback`. This is successful registered 31B fallback execution, not E4B-primary or zero-fallback acceptance.
- Existing Design budgets remained 45 seconds per call, 120 seconds total and six calls maximum. Existing provider request options were unchanged; no thinking or token-limit override was introduced.
- Scope: a fresh non-actuating Design state, actual generated candidates, actual LLM decisions, local decision tools, specification finalization and handoff. Device/preview tools were not attached (`tools=None`); geometry previews, controller gates, physical execution and full workflow execution were not exercised. The existing local `accept_candidate` dispatcher did execute.
- The probe did not test a separate BO-owned numeric lock or a subsequent BO update. Do not infer parameter-feedback verification from this response check.
- Each branch ran once. These are observed durations, not a latency guarantee or sufficient evidence for all-agent timeout sizing.

### Design Evidence Retention

Results and standard agent archives are under `/tmp/atr-registered-vllm-0JMIcf/design-agent/`.
Both archives use `runtime/loops/loop-000001/design_agent/attempt-000001/` beneath their run directories.

| Run | Result-file SHA-256 |
|---|---|
| `design-registered-saved_api_priority` | `630fedee38d8751e5cbd684b7db7a6aab97f1ef4be4010be459c19706cec468d` |
| `design-registered-local_branch` | `2628f603d82c14c673a37fd24e992686fd9b76e0c72437df455dbef4b59b70d8` |

The temporary files are not GitHub-hosted or permanent. This document retains the result summary and hashes. Design/decision/documentation regression checks: **60 passed**; existing Pydantic field-name warnings remain.

## Preliminary Client Checks

| Check | Result | Evidence boundary |
|---|---|---|
| Registered `orchestrator_plan` → `gemma4:31b` | Completed in 5.22 seconds; `finish_reason=stop`; 40 completion tokens | One short synthetic inference request; not a full orchestration run or latency distribution |
| Registered `design_reasoning` → `gemma4:e4b-it-nvfp4` | `ConnectError` in 0.015 seconds | Primary endpoint connection failed; no model response or fallback validated |
| Design decision and local tool dispatch | Passed in the separate agent checks above | Not inferred from the preliminary client checks |
| Existing HTTP API + virtual closed loop + BO feedback | Pending for this change on the registered deployment | No execution or physical-validation claim |
| OpenAI API comparison | Recorded in the agent checks above | Same Design decision path; not compared against a different short client prompt |

## Configuration and Method

- Source of truth: `configs/models.yaml`, `configs/system.yaml`, `app/bootstrap.py`, `backends/model_router.py`, and `backends/vllm_client.py`.
- The probe used `_load_configs`, `_models_cfg_for_backend`, `ModelRouter.select`, `_build_backend("vllm", ...)`, and the existing `VLLMBackend.complete`.
- Existing environment/configuration selection and managed endpoint resolution were retained. No backend, model, thinking, context, temperature, streaming or token-budget overrides were supplied.
- Existing client limits were 320 tokens for `orchestrator_plan`, 256 for `design_reasoning`, and a 300-second transport timeout.
- The 31B request asked for two sentences describing the safe next decision when a design candidate has not yet been accepted and hardware commands are unauthorized. Its input contained 137 tokens, and the answer contained 40 tokens. This is a synthetic smoke input, not a captured production agent prompt.
- The Design input described two fictional candidates, one respecting locked variables and one changing a locked variable. It requested a JSON decision; no answer was received.
- The probe called the registered client directly. It did not exercise `AgentContext` leases, backend/model fallback, model preparation, a tool dispatcher, HTTP workflow execution or physical devices. The endpoint connection failure does not by itself establish failure of the full startup/fallback path.
- No production code, configuration, service lifecycle or timeout was changed.

## Interpretation

The preliminary 31B client result establishes only short-input inference. The separate agent checks establish actual Design acceptance and local tool dispatch for the tested state. Neither establishes sufficient budgets for longer decisions or full closed-loop completion.

The next integration check must retain ATR's registered routing and request settings and record the actual backend/model used, model readiness, agent decision, tool result, API result and loop artifacts separately. Existing physical-cycle evidence remains separate from this Design change.

## Evidence Retention

Local diagnostic results: `/tmp/atr-registered-vllm-0JMIcf/results.json` and `orchestrator_plan-answer.txt`. These temporary files are not permanent or GitHub-hosted artifacts. This document retains the measured values and limitations without storing internal reasoning.
