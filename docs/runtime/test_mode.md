<a id="test-mode"></a>

# Choose a test mode

Test mode automates the researcher's planning replies. It does **not** replace
the experiment workflow, and the word “test” does **not** guarantee that no
equipment will move. Select the execution profile before approving the run.

## Choose the physical boundary

| Profile | Printer behavior | Remaining equipment |
|---|---|---|
| **Virtual Bridge** (`virtual_bridge`) | Normal slicer preparation, then the virtual printer boundary | Resolved virtual policy; no physical actuation |
| **Installed Printer** (`installed_printer`) | Slice normally and send an ejection-only project; omit the print body and cooling wait | Real by default, subject to saved per-agent profiles |
| **Physical Printing** (`physical_print`) | Upload and start the complete project, including cooling and autoejection | Real by default, subject to saved per-agent profiles |

Installed Printer is useful when supplying the specimen yourself while testing
the rest of the route. It is not the old print-start, cancel, and standalone
ejection sequence. The printer owner still determines placement, ejection
geometry, and completion evidence; see [Specimen](../agents/specimen_agent.md)
and the [Bambu bridge](../device_bridges/bambu_x2d_bridge.md).

Saved per-agent profiles can mix virtual and real equipment. For example,
virtual manipulation followed by real equipment still needs the existing
operator teleoperation and transfer-confirmation path. Automatic planning
replies never establish that a specimen was physically transferred.

<a id="execution-profiles"></a>
<a id="gui-screen-reference"></a>

![Test Mode Settings showing cycle count and per-agent execution boundaries](../gui/assets/screenshots/2026-09-29/test-mode-settings.png)

*Test Mode Settings, captured at 1920 × 1080 on 2026-09-29. Private values are
redacted. This screenshot shows Virtual Bridge; it does not establish the
profile of a different or already admitted run. See the
[screen tour](../gui/visual_structure.md) for navigation.*

## Start a scenario

In Live GUI, request the profile explicitly. Supported example commands are:

- `테스트 모드, 가상 브릿지` — Virtual Bridge.
- `테스트 모드, 실제 프린터` — Installed Printer; `설치 프린터` is also an alias.
- `테스트 모드, 실제 출력` — Physical Printing.

Entering only `테스트 모드` leaves the printer-choice question open; it does
not authorize an arbitrary physical profile.

The model then acts as a researcher in the existing conversation: it asks
about available experiments, agrees to planning, answers condition questions,
and approves the reviewed test plan. **Agreement to plan is not approval to
execute.** Execution enters the same reviewed handoff as an ordinary
experiment. Questions, quoted commands, negations, and settings-only edits
do not authorize a run.

Review the agreed setup and the selected device modes before proceeding.
Ordinary experiments use the same LLM-led dialogue with you supplying the
replies. The initial greeting is bilingual; later replies follow your language.

<a id="status-at-a-glance"></a>
<a id="starting-a-scenario"></a>

## What remains your responsibility?

You still supply missing information, connection setup, physical transfer
confirmation, safety recovery, and owner-configuration approval. The automatic
input producer cannot claim that a physical action succeeded.

Typing a human reply takes over the conversation. Stop, E-stop, or a session
reset stops automatic input. Each pending request is answered at most once;
after 24 automatic planning replies, input pauses for human continuation.
If a pending request changes, its previously generated reply is no longer used.

An initially deferred Orchestrator admission continues the same review in the
background, not a new experiment series. The input producer can remain available
for later questions even when admission allocated a new run.

## What stays the same during execution?

The normal registered LangGraph route still dispatches the agents. Automatic
input does not skip stages, allocate BO observations, or publish an initial
design outside the admitted workflow.

- Physical manipulation requires a real policy reference and execution
  confirmation. Fake policy defaults belong only to virtual execution.
- Normal experiment admission supplies print intent; a preview or default
  construction does not. Explicit print and ejection choices survive adaptation.
- Disposal, clearance, and final Vision verification remain before Analysis
  where the active graph requires them.
- Live messages follow actual stage events, including conditional Manipulation
  visits, rather than a fixed screen sequence.
- Test scenarios still use model inference; they are not mock-model runs.

<a id="common-execution-boundaries"></a>

## How to interpret the results

Analysis uses supplied measurements when available. Existing synthetic TEST-data
fallbacks and TEST-only audit differences remain test behavior, not physical
evidence. Check the provenance before treating a result as an experiment.
See [Analysis](../agents/analysis_agent.md).

BO still owns initialization, variable domains, acquisition, and later
recommendations. A scenario neither preallocates observations nor repeats the
first specimen by freezing it into future cycles. See [BO](../agents/bo_agent.md).

<a id="data-and-optimization"></a>

## Implementation and verification reference

<details>
<summary>Conversation behavior, source ownership, and non-actuating checks</summary>

Automatic replies pass through `planning_message`, the same semantic
classification, Experimental Setup update, and admission path as human replies.
Scenario facts remain private to the input producer, and each reply includes
only requested facts. Agreed values update stable `conversation.input.*`
blocks; revisions update the same block. The visible text has no JSON envelope.
`input_source: test_scenario` is metadata only. Runtime replies select existing
facts and cannot start another run or invent physical completion.

The input producer is `app/test_scenario.py`; conversation decisions are in
`app/planning_dialogue.py`; shared admission/transcripts are in
`app/controller.py`. Device modes are resolved by
`utils/test_mode_execution_profiles.py`. Focused checks include
`tests/unit/test_test_scenario_chat.py`,
`tests/unit/test_controller_planning.py`, and
`tests/unit/test_utm_clear_cycle.py`. See [LangGraph](langgraph_runtime.md).

The dialogue verifier checks bilingual greeting, the three test selections,
and Korean/English human conversations with intervening questions and changed
material. It checks Setup and stops at Design handoff without device dispatch:

```bash
.venv/bin/python scripts/verify_test_mode_intake.py --execute --dialogue --backend openai
```

Use `--backend vllm` for the registered local route. Without `--execute`, the
script only lists cases. Execution permits registered inference endpoints but
denies device/tool access. Reports remain under ignored
`runs/validation-test-intake-*`, outside public knowledge corpora.
Classification tests alone prove neither conversation quality nor a completed
physical cycle; mock-model unit tests are not provider performance measurements.

</details>

<a id="source-and-verification"></a>

Next: [first-run tutorial](../tutorials/first_autonomous_run.en.md) ·
[user manual](../tutorials/user_manual.en.md).
