---
doc_type: plan
subtype: implementation
status: active
authority: execution
execution_status: completed
governing_design: docs/superpowers/specs/2026-09-07-five-area-agent-restructuring-contract-design.md
audience: [developer, maintainer]
scope: [manipulation, decision-layer]
summary: Bounded skill selection and post-Vision task-result judgment on the existing cycle.
source_of_truth: [agents/manipulation_agent.py, agents/manipulation_decision.py, utils/utm_clear_cycle.py]
last_verified: 2026-09-09
verified_against: working-tree
related_docs: [docs/agents/manipulation_agent.md]
supersedes: []
---

# Manipulation decision layer implementation

## Contract

One Manipulation agent owns two decisions: select the existing configured skill through a bounded tool request, then judge task-result consistency after existing Vision verification and confirmed robot termination. Vision retains ownership of visual facts. No new orchestration stage or robot execution route.

Preserve policy/checkpoint/calibration/instruction, replay dataset/episode, payloads, operator approval, polling, stop and safety gates. The model cannot supply driver arguments, retry motions, override observations or bypass gates. Decisions are scoped to run/loop/specimen/session and archived with evidence. Explicit deterministic TEST is not LLM or physical proof.

All validation is non-actuating. Model probes, if performed, use registered backends with isolated fake tool callbacks; no runtime loop or real device tools. Existing worktree retained at the user's request. No commit or push in this task.

## Tasks

- [x] Add strict Manipulation-owned decision contracts, scope/stop checks and failure tests.
- [x] Gate existing rollout/fixed skill and replay starts; preserve mandatory stop order.
- [x] Add post-Vision judgment to placement and clearance handoffs using the Manipulation model binding.
- [x] Exercise normal/reject/malformed/timeout/missing/stale/cancellation/repeated-call paths without devices.
- [x] Update existing agent reference, five-area specification, tables and SVG figures.
- [x] Review changes and run focused regression tests; report evidence and remaining limitations.

## Rulings

- Angle/pose is supplied evidence, not permission to invent a policy, a new threshold, or change the trained task instruction.
- Post-review does not re-run visual detection or command robot stop/start; rejection withholds handoff while preserving visual facts.
- A recovered completed execution must also pass result review; it must not start a new skill.

## Validation ledger

| Check | Outcome | Boundary |
|---|---|---|
| Final 14-file Python suite | 268 passed, 10 existing warnings, 16.23 s | Decision, agent, Vision, clearance, recovery, teleop API, runtime view, execution-mode matrix, two-loop archive and LLM lease |
| Additional runtime/module suite | Earlier combined run: 88 passed, 198.28 s; includes 70 LangGraph tests and 18 tests repeated in the final suite | Actual graph/module context, fallback/lease and routing; no physical devices |
| GUI lifecycle and verification tabs | 16 passed | Existing done/waiting state, separate Verification 1/2, simulated labels |
| Registered API, `gpt-5.5` | 4/4 declared case expectations matched; 2.378–4.284 s | Two skill choices; historical placement acceptance; contradictory placement rejection |
| Registered local vLLM, `gemma4:31b` | 4/4 declared case expectations matched; 8.296–11.239 s | Same cases, empty tool registry; no deployment/settings changes |
| Source integrity | Both source JSON hashes unchanged | Historical artifacts read only; contradiction is an in-memory labeled perturbation |
| Documentation/figures | Six governed documents pass; three SVGs rendered; execution figure visually inspected | Existing reference layout plus five-area map and decision contracts |
| Independent review | No remaining material findings after scoped re-review | Terminal-state mutation, cancellation, virtual path, recovery review, task/evidence completeness |

Final model report: `/tmp/atr-manipulation-decisions-a2kmtgg4/results.json` (local transient evidence).
Reproduce with `.venv/bin/python scripts/verify_manipulation_decisions.py --execute`;
source archive defaults to `runs/run-20260906T122533Z-c0effd/runtime/loops/loop-000001`.
This opt-in script initializes registered model providers and an empty tool registry,
not the runtime loop or a device bridge. Historical Vision/stop facts are used as
review prerequisites; it does not claim newly verified images or physical operation.

Python command:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_manipulation_decision.py tests/unit/test_manipulation_probe.py \
  tests/unit/test_manipulation_lerobot_agent.py tests/unit/test_vision_decision.py \
  tests/unit/test_utm_clear_cycle.py tests/unit/test_vision_agent.py \
  tests/unit/test_manipulation_active_cam_loop.py tests/unit/test_runtime_recovery_and_manipulation_status.py \
  tests/unit/test_operator_teleop_handoff.py tests/integration/test_operator_teleop_handoff_api.py \
  tests/unit/test_manipulation_runtime_view.py tests/integration/test_test_mode_execution_profile_matrix.py \
  tests/integration/test_all_agent_loop_archives.py tests/unit/test_llm_lease.py
node --test tests/js/manipulation_lifecycle.test.cjs tests/js/utm_verification_tabs.test.cjs
```

Remaining limits: small development cases, not a benchmark; no new physical commissioning.
Existing LIVE pickup freshness can expire during inference and remains fail-closed.
No new policy/task-instruction changes or pose-specific policy routing were added.
No full-repository pytest claim; only the named suites were run for this reconstruction.
