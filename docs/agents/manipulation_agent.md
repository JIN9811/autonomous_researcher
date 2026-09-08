---
doc_type: reference
subtype: system
status: active
authority: descriptive
audience: [researcher, operator, developer, maintainer]
scope: [agents, manipulation, robotics, lerobot]
summary: Manipulation-owned bounded LLM skill selection and post-Vision result judgment over existing robot executors.
source_of_truth:
  - agents/manipulation_agent.py
  - agents/manipulation_decision.py
  - graphs/modules/manipulation/module.yaml
  - device_bridges/lerobot_bridge.py
  - app/main.py
  - utils/utm_clear_cycle.py
last_verified: 2026-09-09
verified_against: working-tree
related_docs:
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/agents/vision_agent.md
  - docs/agents/equipment_agent.md
  - docs/agents/manipulation_pi05_transfer_runtime_guideline.txt
  - docs/hardware/lerobot_robotis_manipulation_runtime_guideline.md
supersedes: []
---

# Manipulation Agent Reference

## Status at a Glance

- Runtime status: Implemented on the existing transfer and post-test clearance paths
- LLM decision layer: Implemented; registered API and local vLLM each matched 4/4 non-actuating development cases
- Physical effect: Possible only through existing rollout, fixed-skill and managed-replay executors
- Primary handoff: `robot_task_result.v1` → Vision → Equipment; verified clearance → Analysis
- Live hardware validation: Not performed for this reconstruction
- Known gap: No new pose-to-policy routing; LIVE pickup freshness can expire during model inference

## Summary

`ManipulationAgent` supervises existing LeRobot VLA policies, including SmolVLA,
and fixed skills. The LLM judges whether the configured skill fits the delegated
task and selects its bounded tool call. Existing code validates profile, policy,
fresh Vision context and live gates, executes the selected call, monitors progress,
and stops the robot. After accepted Vision verification and confirmed termination,
a second Manipulation-owned LLM decision judges whether the evidence supports handoff.

After the UTM test, the same agent owns the separately scoped recorded sweep
`clear_utm_to_disposal`. This uses managed LeRobot replay, not a second VLA
pickup, and requires measured return plus fresh empty-fixture Vision evidence
before Analysis. Neither LLM call changes the saved policy, trained instruction,
calibration, replay dataset/episode, or motion commands.

## Scope

Supported tasks are `transfer_to_utm` and `clear_utm_to_disposal`. Training,
recording, teleoperation, Isaac, and mirror APIs are connected platform
surfaces; they are not automatically executed by the graph-stage agent.

## Source of Truth

Manipulation agent/module, LeRobot bridge, route handlers, robotics Guides, and
primary graph/sidecar handoffs.

## Actual Role

| Does | Does not |
|---|---|
| Resolve one allowlisted transfer task | Generate arbitrary robot/shell commands |
| Judge task suitability of the configured policy/profile and select its tool | Invent a new policy or alter its trained instruction |
| Start/monitor/stop bounded rollout through bridge | Bypass LeRobot bridge or Guardian |
| Record observed task stages and measured interlocks | Treat policy confidence as physical proof |
| Require post-place Vision verification | Self-certify specimen placement |

## Five-Area Responsibility Map

| Level | Manipulation responsibility | Authority boundary |
|---|---|---|
| High-Level Control | LLM judges configured-skill suitability and, after Vision and termination, task-result consistency | Orchestrator owns the mission; Vision owns visual facts; model cannot grant physical safety |
| Middle-Level Control | Bind saved task/profile, expose bounded tools, validate request, supervise motion-state evidence and completion, and package handoff | Model selects a listed tool with an immutable proposal reference; code supplies all driver arguments |
| Low-Level Control | Calls `lerobot.rollout.start/stop/status` and `robot.pick_place` where selected | LeRobot process/PID lifecycle, serial ports, camera leases, robot commands, action timing, and optional Isaac sidecars remain bridge authority |
| Guardian / Safety | Existing approvals, identity, freshness, camera return, stop, interlock and deadline gates; post-inference scope checks | No model override; uncertain start effects never trigger an automatic repeat |
| Knowledge / Evidence | Run/loop-scoped model request, decision, execution and Vision evidence | Task success requires stopped execution and verified evidence, not a model confidence score |

These are responsibility areas, not five sequential LLM calls. The two LLM
checkpoints belong to one Manipulation agent, using its registered
`manipulation_plan` model binding even when the existing Vision sidecar invokes
result review. No new graph stage is introduced.

### Bounded decision contract

| Checkpoint | Listed choices | Required evidence | Effect |
|---|---|---|---|
| Skill selection | Current `lerobot.rollout.start`, `robot.pick_place`, or `lerobot.replay.start`; `return_to_owner` | Configured task/source/target/profile, supplied observation/pose, current scope | Dispatch the exact selected existing executor after code gates |
| Result review | `accept_task_result`; `return_to_owner` | Ended execution plus accepted Vision facts for the same task/session | Release existing handoff or require review; no robot action |

The JSON response has exactly `tool`, `arguments`, `reason`, and `evidence_refs`.
For either choice, arguments contain only the exact `proposal_id`; the model never
supplies bridge parameters. Selection cites `task:configured`; result review also
cites `execution:ended` and `vision:verified` on acceptance; rejection may cite the
specific contradictory evidence with `task:configured`. Malformed output, mock backend output,
timeout, stop, changed scope/evidence, or rejection cannot authorize execution.

`run_metadata.manipulation_decision_settings.timeout_s` configures the bounded
decision wait (default 120 seconds, positive finite value up to 600). This is
separate from robot polling/stop deadlines. Existing freshness is rechecked after
selection, not extended to accommodate model latency.

### Current prompt strategy

The prompt asks for task–skill compatibility before execution and execution–Vision
consistency after termination. It treats supplied pose orientation according to its
coordinate frame and quality, never inventing an orientation or a selection
threshold. Optional missing pose detail is not automatically failure; contradictory
required facts are. Saved task instruction, checkpoint and replay episode are
immutable. Result reasoning uses brief observable support, not internal reasoning
output; evidence text is data, not an instruction source.

Result context states the task's required visual effect (target present or target
absent). The model must compare actual detection/clearance facts to that effect;
an upstream acceptance label, home interlock or stopped process cannot repair a
contradiction. Registered checkpoint alternatives and operator stop/resource-release
confirmations are included when supplied. This context does not modify driver payloads.

The system contribution is the bounded task-level supervision around VLA and
existing replay: motor execution, visual verification and task handoff have explicit
owners and evidence contracts. The present implementation does not establish a
novel VLA model or autonomous selection among unregistered angle-specific policies.

Port/process recovery is Low-Level; retrying or reconstructing the transfer
procedure is Middle-Level; choosing another stage, cycle, review, or stop is
High-Level. Direct rollout in the LeRobot Workspace is manual and does not
substitute for the automatic agent completion contract.

## Closed-Loop Position and Handoffs

![Manipulation closed-loop position and handoffs](assets/figures/manipulation_01_closed_loop_handoffs.svg)

**Figure Manipulation-1.** Initial transfer and Verification 1 precede Equipment;
the post-test sweep and Verification 2 precede Analysis. This working-tree
`inspection` projection distinguishes control from retained evidence; it is
not evidence of motion accuracy or live transfer reliability.

| Direction | Component | Contract/state | Purpose | Gate |
|---|---|---|---|---|
| In | Specimen | specimen result/location | transfer target | specimen ready |
| In | Vision | fresh pose/readiness | safe pickup/placement context | `expires_at`, camera returned to VLA |
| In | Profile/policy service | robot, camera, checkpoint | executable policy | validation/preflight |
| Out | Vision | session/post-place request | verify placement | bounded rollout state |
| Out | Equipment | verified specimen on UTM | permit protocol | stopped execution + Vision acceptance + Manipulation result acceptance |
| Out | Knowledge | disposal/rollout evidence | provenance | report/evidence refs |

## Inputs and Outputs

Inputs include `OrchestratorState`, `specimen_result`, latest Vision signal,
manipulation profile, `transfer_readiness.camera_returned_to_vla`, task ID,
policy/profile references, and mode/approval state. Outputs include
`manipulation`, `manipulation_report.v1`,
`robot_task_result.v1`, handoff packet, decisions, metrics, rollout runtime,
stage machine, and evidence refs.

## Internal Execution

| Step ID | Work | Boundary/output |
|---|---|---|
| `01_resolve_transfer_task` | allowlisted task/skill | task/skill IDs |
| `02_collect_vision_and_specimen_context` | merge context | stale/missing blocks |
| `03_validate_policy_profile_and_live_gates` | profile/policy/camera/confirmation | preflight |
| `04_select_policy_backend` | LLM selects the current configured skill tool | immutable proposal; no driver arguments |
| `05_start_bounded_rollout` | bridge tool start | session/result |
| `06_monitor_rollout_events` | logs/events/status | rollout runtime |
| `07_observe_task_stage` | observe execution and verification evidence | stage_machine |
| `08_request_post_place_vision_verification` | handoff gate | verification pending/result |
| `09_decide_recover_stop_or_handoff` | LLM result review after existing Vision and stop | accepted handoff or owner review; no motion retry |
| `10_package_manipulation_report` | typed reports | report/result schemas |
| `11_store_rollout_evidence` | attach logs/data/checkpoint | evidence refs |

Supported task contracts:

- `transfer_to_utm`: `3dp_output_area` → `utm_fixture`, verified by
  `specimen_on_utm_platen`, next agent Lab Equipment.
- `clear_utm_to_disposal`: `utm_fixture` → `discard_bin`, verified by
  `utm_fixture_clear_verified`, next agent Vision for Verification 2, then Analysis.

### Post-test UTM clearance

The current graph arms one deterministic child session per run/loop/specimen
only after Equipment supplies verified completion, stable validated CSV,
eligible handoff, `next_test_completed`, and `clearance_restored`. An explicit
identity conflict blocks; restarting the same stage does not rearm motion.

| Phase | Owner and completion evidence |
| --- | --- |
| Verification 1 | Vision: original confirmed placement image and stopped transfer |
| UTM test | Equipment: existing agentic cycle, CSV export and robot-entry clearance |
| Recorded sweep | Manipulation: `jin/utm_clear`, episode `0`, managed replay through the saved robot profile; no grasp/contact requirement |
| Verification 2 | Vision: successful replay, measured return, then a fresh registered UTM image confirming absence |
| Task-result review | Manipulation: judge completed replay and accepted clearance facts; retain visual confirmation even if task handoff is rejected |
| Analysis | Existing CSV processing, released only after the clearance contract and task-result judgment succeed |

The runner's measured return target comes from the final recorded
`observation.state`, not its final action command. A pending replay has one
fixed deadline derived from the bridge duration bound; repeated polls do not
restart it or exhaust the ordinary graph-step budget. Failed/stopped replay,
missing return, stale image, residual specimen, or unknown camera registration
blocks Analysis. There is no automatic effectful replay retry.

`run_metadata.utm_clear_requirement` retains the gate even if its execution
record is missing. `utm_clear_execution` carries the child lifecycle;
`initial_manipulation_execution` preserves the earlier transfer evidence.
The scoped `utm_verifications` map keeps two independent records and images
in the existing loop archive. See [Vision](vision_agent.md#post-test-compressed-specimen-verification)
and the [managed replay API](../device_bridges/lerobot_bridge.md#managed-utm-clear-replay).

![Manipulation internal execution and effect boundary](assets/figures/manipulation_02_execution_effect_boundary.svg)

**Figure Manipulation-2.** Two bounded LLM checkpoints surround existing execution,
monitoring, Vision and stop. Mandatory stop precedes model result review. The same
ownership applies to the separately scoped clearance replay; this is an architecture
figure, not measured robot performance.

### Initial-transfer execution trace details

| Phase | Required identity/state | Operation/gate | Evidence/output | Unknown-effect rule |
|---|---|---|---|---|
| Task resolution | allowlisted initial transfer, source and target | bind `transfer_to_utm` | task/skill/terminal pose | unsupported task blocks before motion |
| Context | specimen ID and unexpired Vision signal | merge pose/readiness and camera-return state | bounded transfer context | stale or mismatched signal blocks |
| Preflight | robot profile, policy/checkpoint, camera, approval and mode | validate profile/policy/live gates | preflight result and blockers | no shell or arbitrary model motion fallback |
| Rollout | task, policy and session configuration | start bounded bridge session | session ID, start result and action budget | start response alone does not prove final pose |
| Monitor | session events/status | track execution phase and verification evidence | event log and observed stage machine | missing status triggers stop/status review |
| Post-place | matching session and camera observation | request fresh Vision verification | placement result and evidence refs | failed verification blocks downstream handoff |
| Decide/store | stopped rollout and Vision evidence | LLM task judgment: accepted handoff or owner review; no motion retry | typed report/result, logs, dataset/checkpoint refs | unknown state requires stop, status and visual proof before restart |

## API Surface

| Class | Method | Path/family | Effect | Notes |
|---|---|---|---|---|
| owned | GET/POST | `/api/lerobot/manipulation-agent/config` | read_only/local_state | agent profile/config |
| owned | POST | `/api/lerobot/manipulation-agent/test`, `/run` | local_state/physical_possible | bounded agent workflow |
| connected | GET/POST | `/api/lerobot/rollout/config`, `/rollout/start`, `/rollout/stop`, `/rollout/status` | physical_possible | primary policy session |
| connected | POST | `/api/lerobot/replay/start`, `/replay/status`, `/replay/stop` | physical_possible/read_only | managed recorded sweep; status is read-only |
| operator | POST | `/api/lerobot/teleoperate/start`, `/teleoperate/stop`, `/teleoperate/status` | physical_possible | manual teleoperation |
| operator | POST | `/api/lerobot/record/*`, `/train/*`, `/wandb-local/*` | local_state/model | dataset/training lifecycle |
| operator | GET/POST | `/api/lerobot/config`, `/sessions`, `/ports/*`, `/camera/test`, `/profiles/validate` | read_only/local_state | readiness/configuration |
| connected | GET/POST | `/api/lerobot/policies`, `/files/*`, `/dataset/inspect`, `/policy/download` | read_only/local_state/external_service | policy/data selection |
| operator | POST | `/api/lerobot/isaac-lab/*`, `/isaac-rgbd/*`, `/augment/*` | local_state/external_service/model | simulation/synthetic/IL/RL/Mimic |
| operator | POST | `/api/lerobot/mirror/*` | read_only/local_state/external_service | Isaac mirror process/loop |
| operator | POST/GET | `/api/lerobot/visualize/*` | local_state/read_only | visualization process/files |

The 87-route count is historical (`0b7627b`); current OpenAPI is exhaustive. Categories above cover
configuration, execution, stop/status, validation, data, simulation, and
evidence responsibilities.

## Tools and Connections

| Tool/service | Boundary | Effect | Evidence |
|---|---|---|---|
| `lerobot.rollout.start` | LeRobot bridge | physical_possible | session/log/status |
| `lerobot.replay.start/status/stop` | LeRobot bridge | physical_possible; status read_only | scoped session/log/return evidence |
| `lerobot.rollout.stop` | LeRobot bridge | physical_possible | stop result |
| `lerobot.rollout.status` | LeRobot bridge | read_only | current session |
| `robot.pick_place` | compatibility bounded bridge | physical_possible | task result |
| SmolVLA / configured LeRobot policy | policy executor | model/physical_possible | policy/checkpoint/config |
| Vision | camera/signal handoff | read_only | pose/verification evidence |
| Isaac | optional simulation/mirror services | external_service/model | scenario/output artifacts |

![Manipulation API and connection architecture](assets/figures/manipulation_03_api_connection_architecture.svg)

**Figure Manipulation-3.** Configuration, data, execution, and optional Isaac
API families converge on LeRobot services, then pass profile, policy, camera,
Vision, and approval gates before a bounded process can reach the robot.
Status, stop results, visual proof, and training artifacts return separately.
This `inspection` figure is not live or simulation-performance evidence.

### Connection lifecycle

| Lifecycle | Service boundary | Required observation | Recovery rule |
|---|---|---|---|
| Configure | ports, cameras, profiles, sessions and policy refs | stable robot/camera/profile/checkpoint identity | invalid profile or missing port blocks action |
| Prepare | policy/file/dataset services and camera test | policy validation, camera readiness, fresh Vision | downloaded or trained policy is not automatically active |
| Invoke | rollout, manipulation-agent or explicit teleoperation API | session ID, bounded task and action budget | each motion surface retains server/bridge gates |
| Observe/stop | rollout status, events, camera and stop API | current session status plus visual state | timeout/unknown effect prohibits blind replay |
| Persist | logs, dataset, checkpoint, images and result | run/session/specimen-linked references | unlinked artifacts do not satisfy handoff proof |
| Optional simulation | Isaac/synthetic/mirror/visualization | declared simulation configuration | simulation evidence never becomes Live evidence |

UI controls, model output, downloaded policies, and module descriptors cannot
bypass the LeRobot bridge or establish direct-shell authority.

## State, Events, Artifacts, and Storage

State includes task, skill, profile, policy ref, session ID, action count,
runtime phase, stage-machine state, post-place interlock, verification,
decision, result, and evidence refs. Logs, datasets, checkpoints, images, and
events require run/session/specimen identity.

`manipulation_decision.v1` records checkpoint, owner, proposal ID, bounded evidence,
model request/response, decision and scope validity through the existing artifact
archive. Result review invoked from a Vision sidecar remains labeled
`owner=manipulation_agent`; the enclosing archive is the actual calling invocation.
`manipulation_decision_cache` reuses accepted identical result evidence;
`manipulation_skill_attempts` prevents repeated start attempts for one delegated
task in a loop. A different loop has separate identity and existing archive storage.

### Live GUI telemetry delivery

The Live GUI opts into `/ws/lerobot/joint-telemetry?sample_format=compact-v1`.
History is replayed from the saved log origin in batches of at most 128 points,
followed by new points only. Each point retains session/execution identity,
sequence, elapsed time, native measured/requested/applied joint values (including
the gripper), and units. No curve points are downsampled. Reconnecting replays
history; the viewer replaces its history and rejects duplicate sequences within
an execution. A new logger execution starts a separate displayed curve.

Each batch carries one `latest_sample` detail for the current pose and motion/grasp
state instead of repeating this detail on every historical point. The viewer
ingests all points, then updates pose and status once per batch; chart redraws
remain coalesced through `requestAnimationFrame`. Each numeric point also retains
a minimal `grasp_visual` (outcome status, attempt index, measured gripper state).
The 3D grasp latch processes these in order so a release followed by idle within
one batch cannot leave the specimen attached. First-contact achievement and
latest-attempt state retain their separate meanings. Annotation still processes
every sample on the server; this is a display projection, not a change to grasp
judgment, rollout control, recording, or loop-scoped artifact storage. Snapshot
and artifact APIs retain full evidence; clients without the query parameter
continue receiving full historical samples.

Offline replay of the 810 action samples in `run-20260906T113555Z-8b3e30`
reduced serialized sample payloads from 4,573,289 to 821,075 bytes (82.0%).
Sending the same log one sample per frame still reduced sample payloads by 10.8%
because latest display detail does not repeat native values or degree maps.
This comparison includes batch sample/detail fields, excludes common message
headers/runtime summaries and network compression, and is not a browser FPS
measurement. Source log hash and every numeric point were unchanged.

Validation: `tests/integration/test_joint_telemetry_history.py` covers late-open,
initially empty logs, appended live points, reconnects, bounded compact batches,
and legacy delivery. `tests/js/omx_telemetry_history.test.cjs` covers batch display,
curve preservation, execution changes, stale detail, release transitions, and
first-grasp display.
Deploy the rebuilt viewer bundle together with the backend; restart the GUI
server and reload the page when no device operation is running.

## Modes and Fallbacks

Test uses fake/virtual policy paths and cannot establish motion. Offline event replay uses
recorded events; managed robot replay is physical when its effective runtime mode is Live.
Isaac is simulation/mirror evidence. Browser invokes APIs but
does not change evidence class. Live requires a visible robot/camera profile,
valid policy checkpoint, fresh Vision, approvals, and bridge readiness.
Compatibility `robot.pick_place` is explicit, not silent equivalence.

Explicit non-LLM TEST records `deterministic_test` and `llm_used=false`. With real
LLM enabled, virtual execution still receives the decision layer but carries
simulated evidence. Preflight-only does not start a skill. Status polling and
mandatory stop do not wait for selection or result reasoning. Manual teleoperation
approval and the existing stop/confirmation route remain unchanged.

## Safety, Approval, and Effect Boundary

`execution_boundary` is `lerobot_bridge_only`; Guardian has stop authority;
direct shell is false. Live motion requires validated profile/policy, camera
return, fresh Vision, bounded task, approval/policy gates, and a stop path.
These policy/camera prerequisites describe the initial transfer. The recorded
clearance sweep uses its own profile/live/approval and Equipment-clearance
gates, without a VLA checkpoint or a reused printer ActiveCam signal.
Post-place Vision verification blocks Equipment handoff; post-clear Vision
verification blocks Analysis. A virtual or preflight Manipulation profile
cannot fabricate clearance after a real Equipment test.

## Errors and Recovery

Invalid profile/policy or stale Vision blocks before motion. A rollout error
retains session/log/evidence. Unknown effect requires status, stop request,
visual state verification, and operator/Guardian decision before restart.
Recovery is bounded to an allowlisted skill; arbitrary model-generated motion
is prohibited.

## Operator and GUI Surfaces

The 2026-09-06 working-tree lifecycle update separates an agent call returning
from its asynchronous transfer finishing. `run_metadata.manipulation_execution`
is scoped by run, loop, specimen, and rollout session. Launching a policy leaves
the Live GUI running; verification/stop still pending is waiting. Done requires
matching UTM completion, post-place readiness, and confirmed `STOPPED` evidence.
An interrupted unverified transfer is not success, and current errors override
older successful display state. Both normal runtime merges and operator Vision
retry merges update this lifecycle. Virtual/no-session workflows retain their
existing status semantics. This record is display bookkeeping, not a new gate
or permission to execute equipment; Vision still monitors concurrently.

A new Manipulation result cannot consume a previously stored completion
observation, even when the rollout session is reused. Completion is evaluated
on the subsequent Vision merge. Previous-run/loop/specimen execution records
cannot supply a Done badge; paused, stopped, or approval-pending new calls stay
Waiting instead of reusing older success.

An offline replay of `run-20260906T122533Z-c0effd` kept Manipulation Running
through UTM observations 2–11 and marked it Done only at observation 12, after
verified placement/readiness and confirmed rollout stop. No device was run.

The LeRobot workspace manages ports, cameras, profiles, teleoperation,
recording, training, rollout, datasets/policies, Isaac, visualization, mirror,
and agent test/run. Live GUI shows agent report, progress, handoff, and evidence.
Workspace actions remain server/bridge gated.

The UTM image card exposes persistent `Verification 1` / `Verification 2`
selectors. An unavailable selected image stays Pending, never borrowing the
other image. Explicit virtual evidence is labeled simulated, not a physical
snapshot. Completion Verification adds one final `UTM Clear & Verification 2`
row; sidebar status follows the current clear child once armed, rather than
reusing the earlier transfer's Done state.

## Current Verification

The 2026-09-09 reconstruction is validated without devices: strict tool dispatch,
unchanged payloads, rejection/malformed/mock responses, scope changes, cancellation,
duplicate-start prevention, owner model binding, simulated mode, placement and
clearance handoff gating. See the [implementation and validation ledger](../superpowers/plans/2026-09-09-manipulation-decision-layer.md).
Historical evidence below predates the new decision layer and is not commissioning
proof for it.

| Validation | Result | Interpretation |
|---|---|---|
| Current focused Python regression | 304 passed; graph/runtime 70 passed | Agent boundaries, completion, mode matrix, teleop, archive, lease and routing contracts |
| Report/API and GUI regression | Python 50 passed; JavaScript 21 passed | Current report fields, task stages, lifecycle and verification records |
| Virtual closed loop | 2 consecutive full cycles; integration passed | Disposal, both Vision verifications, Analysis/BO and loop-scoped archives; deterministic simulation |
| Preflight-only redesign series | 20 cycles passed | Non-actuating downstream chain and 19 BO-to-design updates; design/fabrication fixtures |
| Registered API (`gpt-5.5`) | 4/4 case expectations; 2.378–4.284 s | Correct tool selection, historical acceptance and contradictory-evidence rejection |
| Registered local vLLM (`gemma4:31b`) | 4/4 case expectations; 8.296–11.239 s | Same small development cases, not generalized model accuracy |

The model probe used an empty device-tool registry. Source JSON hashes were unchanged;
the negative case is a labeled in-memory perturbation. No robot, camera, printer or
test equipment was actuated, and no saved model or bridge configuration was changed.

Virtual Equipment supplies scoped CSV and readiness evidence to the existing
disposal handoff. The simulator's curve follows configured geometry and target
strain; disposal and fresh verification still precede Analysis. Full-loop and
preflight-only results are listed separately in the validation ledger above.

The [2026-09-07 supervised integration record](../paper/evidence/2026-09-07-supervised-closed-loop.md)
observed transfer/placement, rollout stop, post-UTM managed disposal, fresh
Vision clearance, and Analysis entry. The disposal invocation and final
clearance remain separate archived results; this is one supervised observation,
not an unattended-success or generalized safety claim.

Verified against two supported tasks, all 11 internal steps, four tools, and the
87-route LeRobot family at baseline `0b7627b`. This is interface/architecture
verification, not a live transfer result.

The post-test clearance update was verified against the uncommitted working
tree on 2026-09-06 using non-actuating tests in
`tests/unit/test_lerobot_replay.py`, `tests/unit/test_utm_clear_cycle.py`,
`tests/unit/test_utm_clear_presence.py`, and
`tests/js/utm_verification_tabs.test.cjs`. Tests cover scoped handoffs,
the actual controller/graph route with fake devices, stop/timeout handling,
image separation and UI lifecycle. They do not commission physical clearing.

## Limitations and Known Gaps

The existing LIVE pickup freshness window is preserved. A slow selection must
request fresh evidence rather than execute using an expired pose; the historical
result-review probes do not validate that timing budget. No physical commissioning
of this added decision layer has been performed.

No paper-scoped result establishes grasp success, collision avoidance, policy
generalization, recovery success, or live timing. Hardware, dataset, policy,
camera, and Isaac availability vary.

## Related Documents

- [Agent Matrix](agent_api_connection_matrix.md)
- [Vision](vision_agent.md)
- [Equipment](equipment_agent.md)
- [Three-Level Control Model](../runtime/three_level_control_model.md)
- [Legacy Pi0.5 Transfer Guideline](manipulation_pi05_transfer_runtime_guideline.txt)
- [LeRobot Runtime Guide](../hardware/lerobot_robotis_manipulation_runtime_guideline.md)
- [Isaac Mirror Guide](../hardware/isaac_sim_robotis_omx_mirror_mode.md)
