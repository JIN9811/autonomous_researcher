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
The existing model route simulates a researcher: it asks about available experiments, agrees to plan, answers the Orchestrator's condition questions, and approves the reviewed test plan. Saved scenario facts remain private to this input producer; they are not injected wholesale into chat or admission. Each natural-language reply goes through `planning_message`, the same semantic classification, Experimental Setup update and admission as human replies.

The input driver does not dispatch agents, allocate BO observations, or jump to an execution stage. Initial BO design publication stays inside the shared admitted workflow. Automatic messages carry `input_source: test_scenario` as metadata only; the visible conversation contains no JSON envelope or automatic-input prefix.

For condition questions, the model supplies only requested facts in natural language. Agreed values update stable `conversation.input.*` blocks in the canonical Experimental Setup store; changed values revise the same block. Planning consent is not execution consent. A later run-review approval enters the existing handoff. Runtime replies are composed only from model-selected existing facts, never from free-form claims of physical completion, and cannot start another run. Missing information, connection setup, physical transfer confirmation, safety recovery and owner-configuration approval remain operator-owned. Changed pending requests invalidate generated replies. Each pending ID is answered at most once; 24 automatic planning replies pause input for human continuation. Human chat takes over; stop, emergency stop and session reset stop the input producer.

If initial ORC admission is deferred, automatic continuation resumes that same review in the background without starting a new series. The input producer remains available for subsequent runtime questions, including when admission allocated a new run before returning the deferred result.

Bare `테스트 모드` does not authorize an arbitrary physical profile. The existing printer-choice prompt remains until the operator selects a mode.

The ORC classifier receives these commands as an explicit workflow contract, including `설치 프린터` as an installed-printer alias. A standalone test command requests automatic conversation, not a saved-Setup edit. Ordinary experiments use the same LLM-led dialogue with the human providing replies. The initial greeting is bilingual; later replies follow the user's language. Mid-dialogue system questions preserve agreed values and the pending decision. Questions, quoted examples, negated execution and settings-only edits do not authorize a run.

## Execution profiles

| Selection | Printer behavior | Remaining equipment |
|---|---|---|
| `virtual_bridge` | Existing slicer preparation and virtual printer boundary | Resolved virtual policy; no physical actuation |
| `installed_printer` | Slice normally, derive/send the ejection-only project; omit print body and cooling wait | Real by default, subject to saved per-agent profiles |
| `physical_print` | Upload/start the complete project; preserve cooling and autoejection | Real by default, subject to saved per-agent profiles |

The old print-start/cancel/standalone-ejection sequence is not the installed-printer workflow. Placement, ejection geometry and completion evidence stay with the existing printer owner. See [Specimen Agent](../agents/specimen_agent.md) and [Bambu bridge](../device_bridges/bambu_x2d_bridge.md).

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
