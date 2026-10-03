# Test Mode

## Status at a Glance

| Item | Current contract |
|---|---|
| Orchestration | Same chat admission and registered LangGraph execution path as an experiment |
| Automatic input | Scenario generation and scoped replies after an operator selects a test mode |
| Device effects | Selected execution profile, not the word `test` alone |
| Evidence | Physical completion remains owned by executing agents and bridges |
| Verification scope | Non-actuating regression tests, not new physical validation |

## Starting a scenario

In the Live GUI, enter `테스트 모드, 가상 브릿지`, `테스트 모드, 실제 프린터`, or `테스트 모드, 실제 출력`.
The model acts as the researcher: it asks about experiments, agrees to planning,
answers setup questions, and approves the reviewed test plan. It uses saved
scenario facts without injecting them wholesale into chat or admission. Each
reply follows the human-input path through `planning_message`, semantic
classification, Experimental Setup updates, and admission.

The input driver does not dispatch agents, allocate BO observations, or jump to an execution stage. Initial BO design publication stays inside the shared admitted workflow. Automatic messages carry `input_source: test_scenario` as metadata only; the visible conversation contains no JSON envelope or automatic-input prefix.

The model answers condition questions with only the requested facts. Agreed or
revised values update the same `conversation.input.*` blocks in Experimental
Setup. Planning consent does not approve execution; the later run-review
approval enters the handoff. Runtime replies use existing facts, cannot claim
physical completion, and cannot start another run.

The operator still handles missing information, connections, transfer
confirmation, safety recovery, and owner-configuration approval. Changed requests
invalidate pending replies, and each pending ID receives at most one reply.
After 24 automatic planning replies, input pauses for human continuation.
Human chat takes over; stop, emergency stop, and session reset stop the input producer.

If initial ORC admission is deferred, automatic continuation resumes that same review in the background without starting a new series. The input producer remains available for subsequent runtime questions, including when admission allocated a new run before returning the deferred result.

Bare `테스트 모드` does not authorize an arbitrary physical profile. The existing printer-choice prompt remains until the operator selects a mode.

The ORC classifier recognizes these workflow commands, including `설치 프린터`
as an Installed Printer alias. A standalone test command starts automatic
conversation, not a saved-Setup edit. Ordinary experiments use the same dialogue
with human replies. The greeting is bilingual; later replies follow the user's
language. Intervening system questions preserve agreed values and the pending
decision. Questions, quoted examples, negated execution, and settings-only edits
do not authorize a run.

## Execution profiles

### GUI Screen Reference

![Test Mode Settings: cycle count and per-agent execution boundaries](../gui/assets/screenshots/2026-09-29/test-mode-settings.png)

*Test Mode Settings: cycle count and per-agent execution boundaries.*

Profile selection exposes physical/preflight boundaries separately from run length. This capture shows the Virtual Bridge tab; it does not establish what another profile or an already admitted run will execute.
Captured on 2026-09-29 at 1920 × 1080; private values are redacted.
See the [GUI structure guide](../gui/visual_structure.md) for navigation and capture conditions.


| Selection | Printer behavior | Remaining equipment |
|---|---|---|
| `virtual_bridge` | Existing slicer preparation and virtual printer boundary | Resolved virtual policy; no physical actuation |
| `installed_printer` | Slice normally, derive/send the ejection-only project; omit print body and cooling wait | Real by default, subject to saved per-agent profiles |
| `physical_print` | Upload/start the complete project; preserve cooling and autoejection | Real by default, subject to saved per-agent profiles |

The old print-start/cancel/standalone-ejection sequence is not the Installed Printer workflow. Placement, ejection geometry and completion evidence stay with the existing printer owner. See [Specimen Agent](../agents/specimen_agent.md) and [Bambu bridge](../device_bridges/bambu_x2d_bridge.md).

Saved profiles may mix virtual and real devices. A virtual manipulation/real equipment boundary still requires the existing operator teleoperation and confirmation path; automatic scenario input never asserts that a specimen was transferred.

## Common execution boundaries

- Normal experiment start admission supplies print intent; preview/default construction alone does not. Explicit print/ejection choices survive adaptation.
- Physical manipulation requires a real policy reference and execution confirmation, including physical test profiles. Fake profile/policy defaults remain confined to virtual execution.
- Disposal/clearance and final Vision verification remain before Analysis where required by the graph. Automatic input cannot manufacture their success evidence.
- Live GUI messages follow registered-stage events, including conditional Manipulation visits, rather than a single default edge sequence.
- Scenario automation does not replace LLM inference with mocks. Controlled-model unit tests are not API/local-model performance validation.

## Data and optimization

Analysis uses supplied measurement data when available. Existing synthetic TEST-data fallback and TEST-only audit differences remain test behavior; this change does not promote synthetic results to physical evidence. See [Analysis Agent](../agents/analysis_agent.md).

The active BO contract owns initialization, variable domains, acquisition and subsequent recommendations. Input generation does not preallocate observations or freeze the first specimen into future cycles. See [BO Agent](../agents/bo_agent.md).

## Source and verification

- Input producer: `app/test_scenario.py`; conversation decisions: `app/planning_dialogue.py`; shared admission/transcript: `app/controller.py`.
- Tests: `tests/unit/test_test_scenario_chat.py`, `tests/unit/test_controller_planning.py`, `tests/unit/test_utm_clear_cycle.py`.
- Device-mode resolution: `utils/test_mode_execution_profiles.py`.
- See [LangGraph runtime](langgraph_runtime.md).

Classification-only checks do not establish conversation quality or a completed hardware cycle. The dialogue verifier exercises bilingual greeting, three automatic test selections, and Korean/English human conversations with intervening questions and material changes. It checks Setup values and stops at the existing Design handoff without dispatching equipment.

Reproduce with `scripts/verify_test_mode_intake.py --execute --dialogue` using the project Python environment. Select a registered provider with `--backend openai` or `--backend vllm`. Without `--execute`, the script only lists its cases. The verifier denies device/tool access and permits only registered inference endpoints; reports remain in ignored `runs/validation-test-intake-*` directories, outside public knowledge corpora.
