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
source_of_truth: [agents/manipulation_agent.py, agents/manipulation_decision.py, utils/utm_clear_cycle.py, agents/equipment_agent.py, device_bridges/windows_pyautogui_bridge.py]
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

## Runtime cleanup verification

The unused scoring subsystem, derived report fields, runtime consumers and UI
cards were removed. Observed task stages, bridge execution, preflight, stop,
Vision verification and the two Manipulation decisions retain their existing
paths. Historical experiment artifacts remain unchanged.

| Check | Result | Scope |
|---|---|---|
| Agent regression | 304 passed | The 14-file command above plus `test_guardian_agent.py` and `test_design_decision.py` |
| Graph/runtime regression | 70 passed | `tests/unit/test_langgraph_runtime.py` |
| Equipment/simulator/clearance regression | 259 passed | Equipment Agent, Windows bridge, simulator readiness and disposal-cycle tests |
| Full virtual closed loop | 2 consecutive cycles completed; integration test passed | Production graph/agents, virtual device boundaries, disposal, both verifications, Analysis/BO and per-loop artifacts; deterministic TEST, not LLM/hardware validation |
| Non-actuating redesign series | 20 cycles passed | Existing preflight-only integration: design/fabrication fixtures, production downstream agents, 19 BO-to-next-design parameter updates; physical tool tripwires |
| Report/API/UI regression | 50 passed | LeRobot static tests, Manipulation controller-message test and Live GUI layout tests selected with `-k 'manipulation or lerobot'` |
| JavaScript regression | 21 passed | Manipulation lifecycle, report consumers and verification tabs |
| Documentation checks | 29 tests passed; changed governed documents validated | Updated text, links and four SVGs |
| Independent review | No material code findings | Documentation findings corrected; physical execution paths unchanged |

Virtual Equipment now emits the existing identity-scoped export/readiness
contract, using the actual local CSV probe and explicitly simulated terminal
evidence. The synthetic displacement span follows configured height and target
strain; the existing Analysis/BO objective and clearance gates are unchanged.
Full-loop fixtures select virtual disposal explicitly and inspect current
per-loop artifact directories. No physical operation is implied.

Loop evidence: `runs/run-20260908T162911Z-326f74/` (two complete virtual cycles)
and `runs/run-20260908T161247Z-356a61/` (20 preflight-only redesign cycles).
Reproduce with
`pytest -q 'tests/integration/test_controller_run.py::test_controller_completes_test_run[2]'`
and
`pytest -q tests/integration/test_controller_run.py::test_safe_physical_printer_preflight_completes_twenty_redesign_cycles_without_actuation`.
The optional full virtual 20-cycle parametrization was not run in this cleanup.

One broader controller test also retains a baseline fixture mismatch:
`test_live_gui_planning_tail_agent_messages_keep_cycle_metadata` expects a
Manipulation message from a static tail that excludes that stage. Original
baseline methods and fixture reproduce the same assertion failure. Full
objective-compiler restart testing separately fails at `next_design_request`
in `test_objective_compiler_analysis_knowledge_bo_survives_restart`; that test
and its Analysis/Knowledge/BO implementation were unchanged by this work. Full
documentation validation reports existing format issues in two unchanged files:
`docs/device_bridges/windows_pyautogui_bridge.md` and
`docs/superpowers/specs/2026-08-24-plc-safety-bridge-design.md`.
These checks do not constitute a clean full-repository test run or new hardware
validation.

## Virtual Equipment handoff follow-up

The operator approved correcting the virtual-result contract exposed by the
full-loop check. Keep live/physical execution and all clearance gates unchanged.

- [x] In `device_bridges/windows_pyautogui_bridge.py`, make a complete simulated
  protocol emit identity-scoped `next_specimen_readiness` from explicit simulated
  completion/reset/clearance steps. Mark evidence simulated and non-actuating;
  generic programs, abort and export are not whole-cycle readiness.
- [x] In `agents/equipment_agent.py`, project `raw_data_export` from the existing
  local CSV probe and project the simulator's readiness into the existing
  handoff contract. Only non-live simulator results qualify; missing, failed or
  mismatched evidence must not become eligible. Bind run/loop/specimen identity.
- [x] Add positive and malformed/missing/wrong-identity/live-result tests;
  reproduce the missing-field failure before implementing the projection.
  Re-run `tests/unit/test_equipment_agent.py`, simulator tests and
  `tests/unit/test_utm_clear_cycle.py` after implementation.
- [x] Update the full-loop test fixture to explicitly request virtual execution
  for disposal/verification too, rather than relying on an unspecified policy.
  Run `tests/integration/test_controller_run.py` without device actuation; record
  full-cycle and preflight-only results separately before commit/tag update.
