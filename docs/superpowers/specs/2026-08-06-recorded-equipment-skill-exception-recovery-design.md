# Recorded Equipment Skill And Exception Recovery Design

## Status

Proposed design. This document defines contracts and acceptance criteria only. It does not authorize implementation or physical equipment actuation.

## Objective

Turn a successful Windows GUI operation recording into a versioned Equipment Skill that:

- replays the normal path locally through the existing bounded PyAutoGUI bridge;
- automatically annotates visual and execution checkpoints during Skill creation;
- detects deviations without continuously calling an LLM;
- asks the Lab Equipment Agent and Gemma4 31B for bounded recovery only after an exception;
- verifies recovery before resuming the interrupted step;
- preserves the existing Windows bridge, Equipment Agent, Guardian, GUI/CUI, Test, and Live contracts.

The design must keep simple macros lightweight. Registering this feature must not make every PyAutoGUI action dependent on network latency or LLM availability.

## Design Decision

The selected architecture is **deterministic replay with agent-supervised exception recovery**.

The Equipment Skill is a versioned execution package, not an autonomous model running on Windows. Windows stores and executes deterministic macro segments. The Linux ATR server remains the reasoning host. The Lab Equipment Agent owns the execution lifecycle and invokes Gemma4 31B only when a declared exception condition is reached.

```text
successful recording
  -> event/video synchronization
  -> automatic annotation
  -> bounded macro segmentation
  -> operator validation
  -> versioned Skill deployment
  -> deterministic Windows execution
  -> local checkpoint verification
  -> exception only: Equipment Agent recovery
  -> recovery verification
  -> resume or operator escalation
```

### Why this design

- It preserves the speed and low resource use of the existing macro executor.
- It keeps the agent concept explicit: the Equipment Agent supervises and recovers; the Skill does not replace the agent.
- It uses the reference video as creation and exception evidence without continuously streaming video to Gemma4.
- It reuses the existing `atr.pyautogui_program.v1` allowlist rather than introducing arbitrary Python or shell execution.
- It can improve from successful recoveries without silently modifying a validated production Skill.

## Non-Goals

- Running a local LLM on the Windows host.
- Sending every mouse or keyboard event across the network during normal execution.
- Sending a complete reference video to the LLM on every run.
- Allowing the LLM to emit arbitrary PyAutoGUI calls, Python, PowerShell, CMD, BAT, EXE, or shell commands.
- Replacing the existing Program Manager, `/execute` route, or UTM runtime contracts.
- Treating exact pixel equality as the sole success criterion.
- Automatically promoting one successful LLM recovery into a production Skill.
- Using browser DOM automation as a substitute for the Windows bridge when the target is a native Windows application.

## Existing Contracts Preserved

The implementation must build on the current bridge behavior:

- macro schema: `atr.pyautogui_program.v1`;
- program validation and registration through the existing Program Manager contract;
- allowlisted sequence actions only;
- maximum 100 actions in one registered macro;
- `/programs`, `/programs/validate`, `/programs/register`, `/execute`, `/screenshot`, locator, artifact, health, and request-audit behavior;
- token-authenticated Windows bridge transport;
- explicit Test versus Live selection with no silent fallback;
- PyAutoGUI fail-safe enabled;
- Lab Equipment Agent as the workflow owner;
- Guardian-visible failures and operator escalation.

The Skill layer may add APIs and storage, but must not change the meaning of existing APIs.

## Placement In The Existing ATR Hierarchy

No new top-level agent or closed-loop stage is introduced. The current route remains unchanged:

```text
... -> Vision Agent -> Manipulation Agent -> Lab Equipment Agent -> Analysis Agent -> ...
```

The Skill runtime is an internal capability of the existing Lab Equipment Agent Module.

### Layer ownership

| Existing layer | Added responsibility | Responsibility explicitly not added |
|---|---|---|
| `orchestrator/langgraph_runtime.py` | Enter the existing Equipment stage, emit module-step events, preserve retries/handoffs, and wait for the Equipment result | Recording interpretation, visual comparison, or recovery Tool selection |
| `graphs/modules/equipment/module.yaml` | Declare observable Skill execution and recovery substeps inside the Equipment module | A second Equipment agent or a parallel physical execution route |
| `agents/equipment_agent.py` | Resolve the exact Skill version, supervise execution, create exception context, request bounded recovery, verify completion, and produce the existing Equipment handoff | Direct desktop control or unrestricted code execution |
| Equipment Skill service | Registry, annotation, compilation, versioning, validation, deployment manifest, and recovery candidates | Workflow stage transitions or physical actuation |
| `mcp_tools/equipment_tools.py` | Register Skill management/status handlers and the bounded runtime handlers used by Equipment Agent | Business logic, LLM prompts, or browser-only state |
| `device_bridges/windows_pyautogui_bridge.py` | Authenticated transport for recording, deployment, execution, checkpoint, status, artifact, and recovery requests | Deciding whether a recovery is appropriate |
| Windows bridge server | Capture recordings, persist deployed bundles, execute macro segments, perform local checks, pause atomically, and return evidence | Running Gemma4 or choosing an undeclared recovery action |
| `policies/guardian_gate.py` | Validate recovery actions that cross the existing safety boundary | Replacing routine checkpoint verification or forcing a recovery when none was requested |
| `app/controller.py` | Project server-authoritative Equipment Skill and recovery state into Live GUI events and run metadata | Duplicating the Skill state machine in the frontend |
| Windows console / Equipment Workspace / Live GUI / Runtime IDE | Render and invoke shared backend contracts | Independent registries, independent execution state, or fallback execution paths |

### Single execution entry

`EquipmentAgent.run(state, ctx)` remains the only agent-level entry used by the LangGraph Equipment stage. The Skill feature must not add a controller path that bypasses this agent during a closed-loop run.

The agent resolves one of two execution references:

```text
legacy program reference: program_id
versioned Skill reference: skill_id + skill_version + deployment_hash
```

Existing registered programs continue to run unchanged. A Skill execution resolves its macro segments and calls the same bounded Windows executor. The Skill runtime must not create a second PyAutoGUI implementation.

### Equipment module internal graph

The Equipment module configuration should expose these internal runtime steps:

```text
01_resolve_equipment_profile
02_resolve_skill_version
03_validate_bridge_and_deployment
04_execute_deterministic_segment
05_verify_checkpoint
06_route_exception_if_present
07_select_bounded_recovery
08_guard_recovery_if_required
09_execute_and_verify_recovery
10_resume_or_escalate
11_validate_evidence_handoff
```

These module entries are observable runtime steps. The allowlisted Python handler remains authoritative; editing the graph YAML must not generate or modify Python source.

Normal execution traverses steps 01 through 05 repeatedly and then 11. Steps 06 through 10 are activated only when a declared exception exists. Their presence in the module graph does not imply an LLM call on a successful run.

### Equipment Agent internal services

The existing Equipment Agent should delegate to focused internal services while preserving its public `AgentResult` contract:

- `EquipmentSkillResolver`: selects an exact validated version for the current equipment profile;
- `EquipmentSkillExecutionSupervisor`: starts and monitors deterministic segment execution;
- `EquipmentCheckpointVerifier`: reconciles Windows local checks with expected Skill conditions;
- `EquipmentRecoverySupervisor`: builds exception context and requests a bounded LLM decision;
- `EquipmentRecoveryVerifier`: confirms the expected state after a recovery Tool runs;
- existing evidence and handoff builders: include Skill identity and recovery evidence in the current Equipment report.

These are internal modules, not new agents and not new LangGraph stages.

### LLM call boundary inside Equipment Agent

When an exact validated `skill_id` and `skill_version` are present, the normal Skill path is constructed deterministically from `workflow.json`. It must not use the current `tool_formatting` model call to rediscover the macro order on every run.

The LLM boundary is:

```text
Skill creation: annotation interpretation and draft recovery policy
Normal runtime: no LLM call for segment ordering or successful checkpoints
Exception runtime: one bounded Equipment recovery decision per attempt
Recovery completion: deterministic verification, not an LLM self-declaration
```

Legacy non-Skill Equipment requests may continue to use the current tool-selection behavior. This isolates the new behavior without changing existing programs.

The recovery request uses a dedicated Equipment recovery task and structured response schema. It must not reuse free-form orchestrator conversation as executable context.

### Shared model selection contract

Skill creation and exception recovery use the same server-authoritative inference selection exposed by the current ATR Main/Live GUI model controls. Windows does not own a second model selector and does not store an API key.

Supported selected backends include the currently configured local Nemoclaw/vLLM model, such as Gemma4 31B, and an explicitly loaded GPT API profile. The active choice is resolved through the same backend registry used by Live GUI.

Model selection rules:

- starting a Skill creation job snapshots the exact provider, model ID, endpoint profile, and capability result for that job;
- starting a Skill execution snapshots the selected recovery model for that execution;
- changing the global model later affects a new creation or execution job, not a job already running;
- normal deterministic execution does not call the selected model;
- an exception uses the model snapshot associated with that execution;
- no automatic provider or model fallback is allowed;
- an unavailable selected model pauses annotation or recovery with an explicit failure and Operator Attention;
- model and capability provenance is stored with annotation and recovery evidence, but API secrets are never stored in the Skill.

Before annotation, the backend checks whether the selected model can consume the evidence modality required by the job. Deterministic CV/OCR extraction may supply structured evidence to a text-only model. If the job requires direct visual interpretation that the selected model cannot provide, creation stops with an explicit capability error rather than silently switching models.

### Tool and bridge integration

The existing tools remain valid:

```text
equipment.pyautogui.health
equipment.pyautogui.list_programs
equipment.pyautogui.run
equipment.pyautogui.screenshot
equipment.pyautogui.request_log
```

Skill management adds non-actuating capabilities for recording status, annotation status, catalog, validation, and deployment. Runtime actuation remains rooted in `equipment.pyautogui.run`; a Skill reference is an additional validated input envelope, not a new generic execution tool.

Recovery uses the same run boundary with an explicit operation, exact execution identity, and an allowlisted recovery segment:

```json
{
  "operation": "recover",
  "execution_id": "exec-001",
  "skill_id": "utm_compression_test",
  "skill_version": "1.0.0",
  "step_id": "wait_for_result",
  "recovery_id": "recovery-001",
  "recovery_program_id": "utm_refocus_result_window_v1",
  "idempotency_key": "exec-001:recovery-001"
}
```

The Windows bridge rejects a recovery program that is not listed in the deployed Skill manifest. This keeps normal and recovery actuation inside one audit and allowlist path.

### State ownership and projection

There are three authoritative state owners:

- Linux Skill registry: definition, version, validation, and deployment manifest;
- Windows Skill runtime: currently executing segment, local checkpoint result, and last idempotent operation;
- `OrchestratorState.run_metadata`: closed-loop projection of the current execution and recovery state.

The controller projects, but does not independently infer, the following records:

```text
latest_equipment_skill
latest_equipment_skill_execution
latest_equipment_skill_checkpoint
latest_equipment_skill_exception
latest_equipment_skill_recovery
latest_equipment_report
latest_equipment_handoff_packet
```

Browser state is never authoritative. Refreshing or opening another GUI reads these records from the server and Windows runtime status.

### Handoff compatibility

The existing Equipment-to-Analysis handoff remains the external boundary. Skill-specific data is attached as evidence:

- exact `skill_id`, version, and deployment hash;
- segment and checkpoint trace;
- whether exception recovery was used;
- recovery operation and verification result;
- output artifact references;
- final Equipment verification status.

Analysis Agent does not need to understand or execute the Skill. It consumes the same verified equipment data and evidence contract as before.

## System Components

### 1. Windows Recording Runtime

The recorder runs next to the Windows bridge and captures one operator-demonstrated successful run.

It records:

- mouse position, button, click, drag, and scroll events;
- keyboard press, release, text, and shortcut events;
- monotonic and wall-clock timestamps;
- active process, active window title, window bounds, display ID, resolution, and display scaling;
- reference video;
- explicit operator checkpoint markers;
- screenshots around input events and major visual changes;
- optional UI Automation metadata when available;
- output file observations declared by the operator;
- a final success marker or operator-declared failed demonstration.

The recorder is not the executor. A recording cannot run until it is annotated, validated, compiled into bounded macro segments, and deployed.

### 2. Skill Annotation And Compilation Service

This Linux-side service converts a recording into a draft Skill.

It performs:

- event and video timeline synchronization;
- idle interval collapse;
- action grouping and semantic step segmentation;
- click-target region extraction;
- before/after frame selection;
- OCR extraction for visible labels and error text;
- locator candidate generation;
- expected-duration and timeout estimation;
- precondition and postcondition candidate generation;
- uncertainty scoring;
- macro segment generation with no more than 100 allowlisted actions per segment;
- reference evidence generation for local runtime comparison;
- draft recovery-policy generation.

Gemma4 31B may name and organize steps, interpret structured OCR and image-difference evidence, and propose bounded recovery policies. It must not directly generate executable unrestricted code.

### 3. Skill Registry

The Linux ATR server owns the authoritative Skill registry. A Skill is immutable after validation. Any edit creates a new version.

Required lifecycle states:

```text
DRAFT
ANNOTATING
REVIEW_REQUIRED
VALIDATED
DEPLOYED
DISABLED
ARCHIVED
```

Only `VALIDATED` and `DEPLOYED` versions may be selected by the Equipment Agent. `DISABLED` and `ARCHIVED` versions remain auditable but cannot execute.

### 4. Windows Skill Runtime

Windows receives a deployment bundle containing only the data required for deterministic execution and local verification:

- bounded macro segments;
- visual locators and checkpoint references;
- OCR expectations;
- timing bounds;
- recovery pause points;
- Skill and segment hashes;
- no LLM weights and no unrestricted source code.

The Windows runtime executes the normal path locally. It reports checkpoints and exceptions to Linux but does not request an LLM decision for successful steps.

### 5. Lab Equipment Agent Recovery Supervisor

The Lab Equipment Agent owns:

- Skill selection and run identity;
- bridge and deployment-version verification;
- normal execution supervision;
- exception intake;
- recovery-context construction;
- bounded Tool selection through Gemma4 31B;
- recovery verification;
- resume, abort, or operator escalation;
- evidence and artifact handoff to downstream agents.

The Skill provides the expected workflow and recovery knowledge. The Equipment Agent remains the decision-making runtime owner.

### 6. Guardian Boundary

Guardian validates recovery requests before physical or irreversible action. It must reject:

- actions outside the Skill's allowlist;
- coordinates outside declared screen or window bounds;
- undeclared programs or windows;
- retries exceeding the Skill budget;
- recovery after an emergency stop;
- arbitrary command execution;
- a version or hash mismatch;
- Live execution when the selected bridge or equipment profile is not explicitly Live-enabled.

## Skill Package Contract

The authoritative package schema is `atr.equipment_skill.v1`.

```text
<skill_id>/<version>/
├── manifest.json
├── workflow.json
├── annotations.json
├── recovery_policy.json
├── recording/
│   ├── reference.mp4
│   └── events.jsonl
├── checkpoints/
│   ├── <checkpoint_id>_before.webp
│   ├── <checkpoint_id>_after.webp
│   └── <checkpoint_id>_roi.webp
├── locators/
│   └── locators.json
├── programs/
│   ├── segment_001.json
│   └── segment_002.json
└── integrity/
    └── sha256sums.json
```

### `manifest.json`

Minimum fields:

```json
{
  "schema": "atr.equipment_skill.v1",
  "skill_id": "utm_compression_test",
  "version": "1.0.0",
  "name": "UTM Compression Test",
  "target_profile": "utm_windows_v1",
  "target_platform": "windows",
  "execution_policy": "deterministic_with_exception_recovery",
  "entry_step": "open_utm_program",
  "success_step": "export_complete",
  "max_recovery_attempts": 3,
  "created_from_recording": true,
  "validated": false
}
```

### `workflow.json`

Each workflow step contains:

- stable `step_id`;
- one registered macro segment ID;
- preconditions;
- postconditions;
- checkpoint IDs;
- nominal and maximum duration;
- allowed next steps;
- recovery pause boundary;
- irreversible-action flag;
- declared output artifacts.

### `annotations.json`

Each annotation records:

- source time range;
- event range;
- active application and window;
- target ROI;
- OCR text candidates;
- visual fingerprint references;
- expected visual change;
- confidence score;
- annotation origin: `automatic`, `operator`, or `recovery_candidate`;
- review status.

### `programs/segment_*.json`

Each file remains a valid `atr.pyautogui_program.v1` definition and contains no more than 100 actions. The existing bridge validator remains authoritative. A Skill with more than 100 actions is represented by multiple segments; the macro schema limit is not increased.

## Automatic Annotation Rules

### Segmentation signals

The annotator combines, rather than substitutes, the following signals:

- input event boundaries;
- active-window changes;
- large visual changes;
- stable-screen intervals;
- OCR text changes;
- file-output events;
- operator checkpoint markers;
- application process transitions.

No single signal is sufficient for automatic validation.

### Locator priority

Generated locators follow this order:

```text
Windows UI Automation control
-> OCR/text and nearby geometry
-> image template within a declared ROI
-> window-relative coordinate
-> absolute coordinate
```

Lower-priority locators are explicit secondary candidates only within the same validated target window. Switching locator type is recorded in the checkpoint trace and cannot occur silently. Absolute coordinates require explicit operator review.

### Confidence and review

- High-confidence annotations may be preselected but remain visible for review.
- Ambiguous clicks, changing text, overlapping controls, low-contrast targets, and absolute coordinates force `REVIEW_REQUIRED`.
- Automatic annotation never marks the full Skill `VALIDATED`.
- Operator edits are stored as a new draft revision and included in the integrity manifest.

## Reference Evidence Policy

The reference video is a Skill-creation artifact and audit record. It is not streamed to the LLM during every normal execution.

The annotation service derives checkpoint frames, target regions, OCR evidence, event timing, and visual fingerprints from the reference recording. The Windows deployment bundle receives only the references required for deterministic execution and local checkpoint verification.

Skill creation sends one bounded chronological evidence set, not independent screenshot prompts. The set combines the ordered workflow, initial and final state observations, event-context frames, high-resolution pre-action frames, and post-action observations. The selected model must first reconstruct workflow intent and causal state transitions, then annotate each existing step and locator in the same response. The resulting `workflow_summary` and `step_transitions` are retained in `annotations.json`; they are semantic evidence for review and later exception recovery, not additional executable actions.

The visual request is limited to 16 verified images and 32 MiB. SHA-256 and allowed-root checks are mandatory, duplicate frames are removed, and locator frames plus temporal boundaries take selection priority. Inline locator PNGs are omitted from the text prompt when their full frames are already attached. Recording stop captures one clean final observation after the recording overlay is hidden so the model can distinguish the last action from its completion state.

At runtime, a successful checkpoint returns structured status and artifact references. An exception returns only the evidence associated with the failed step, such as expected and observed frames, target regions, OCR differences, recent events, and an optional bounded clip. Binary artifacts are referenced outside the JSON decision contract.

## Multimodal Capability Boundary

The design must not assume that the currently selected Gemma4 endpoint accepts native video.

- If the serving endpoint supports multimodal images, the same chronological frame contract is converted by the shared backend adapter to OpenAI-compatible `image_url` content or Ollama-compatible image payloads. Local vLLM and a later API selection therefore receive the same semantic timeline.
- If it supports video, a bounded exception clip may be supplied in addition to selected frames.
- If it is text-only, local CV, OCR, UI Automation, and image-difference services produce structured evidence; Gemma4 receives only that structured evidence.
- Capability negotiation is explicit and recorded in the annotation and recovery result. No silent modality fallback may report equivalent evidence.

## Runtime State Machine

```text
IDLE
-> PRECHECK
-> RUNNING
-> CHECKPOINT_VERIFY
-> RUNNING | EXCEPTION
-> RECOVERY_PENDING
-> RECOVERING
-> RECOVERY_VERIFY
-> RESUMED | ESCALATED | ABORTED
-> COMPLETED
```

### Normal path

1. Equipment Agent selects an exact Skill ID and version.
2. Linux verifies the selected Windows candidate, token-authenticated health, program catalog, deployment hash, and equipment profile.
3. Windows executes the current macro segment locally.
4. Windows performs declared checkpoint verification.
5. A successful checkpoint advances without an LLM call.
6. The Equipment Agent advances to the next segment.
7. The final declared success condition and output artifacts are verified before `COMPLETED`.

### Exception triggers

An exception is raised only from an explicit detector:

- target window missing or changed;
- process not running;
- locator missing or ambiguous;
- expected image, UIA control, OCR text, or pixel condition not observed;
- step timeout;
- unexpected popup or text;
- declared output file missing or unstable;
- bridge disconnection or authentication failure;
- macro action error;
- operator pause, safe stop, or emergency stop.

The exception detector records which condition failed. A generic `LLM thinks this looks wrong` result is not sufficient by itself.

## Exception Packet

The Windows runtime sends a bounded packet to the Equipment Agent:

```json
{
  "schema": "atr.equipment_skill_exception.v1",
  "run_id": "run-20260806-001",
  "execution_id": "exec-001",
  "skill_id": "utm_compression_test",
  "skill_version": "1.0.0",
  "step_id": "wait_for_result",
  "segment_id": "segment_003",
  "failure_code": "EXPECTED_TEXT_NOT_FOUND",
  "attempt": 1,
  "expected": {},
  "observed": {},
  "recent_events": [],
  "reference_artifacts": [],
  "observed_artifacts": [],
  "allowed_recovery_tools": []
}
```

The packet references binary artifacts by ID and hash. It does not embed video or images in JSON.

## Recovery Contract

### Allowed recovery operations

The initial recovery vocabulary is intentionally small:

- `wait_and_recheck`;
- `refocus_target_window`;
- `dismiss_known_popup`;
- `retry_current_step`;
- `return_to_previous_checkpoint`;
- `restart_declared_application`;
- `run_declared_recovery_segment`;
- `request_operator_attention`;
- `safe_abort`.

Every operation maps to an existing allowlisted bridge action or a separately validated registered macro. The LLM selects operations and bounded parameters; it does not generate executable code at runtime.

### LLM response

The Equipment Agent requests structured output:

```json
{
  "decision": "retry_current_step",
  "recovery_tool": "refocus_target_window",
  "parameters": {},
  "expected_verification": "target_window_visible",
  "operator_summary": "The target application lost focus.",
  "confidence": 0.91
}
```

Raw chain-of-thought is neither required nor stored. The GUI displays the concise operator summary, selected Tool, evidence references, and verification result.

### Recovery completion

A recovery is successful only when its declared verification condition passes. Tool execution success alone is insufficient.

- Success: resume from the interrupted step or its declared previous checkpoint.
- Repeated failure: stop after `max_recovery_attempts` and request Operator Attention.
- Emergency stop: never auto-resume.
- Network loss during recovery: pause locally at the current atomic action, preserve `execution_id`, and wait for reconnect or safe abort.

## Idempotency And Reconnection

Every execution and recovery request includes:

- `run_id`;
- `execution_id`;
- `skill_id` and exact version;
- `segment_id` and `step_id`;
- monotonic attempt number;
- request idempotency key.

Windows persists the last accepted and completed operation. Repeated requests with the same idempotency key return the recorded result and do not actuate again. After reconnect, Linux queries the execution status before retrying.

## Recovery Learning

A successful novel recovery creates `atr.equipment_recovery_candidate.v1` with:

- exception signature;
- evidence hashes;
- selected recovery operation;
- verification result;
- affected Skill version;
- success count and failure count;
- operator approval status.

Candidates do not modify the deployed Skill automatically. Promotion requires either explicit operator approval or the configured repeated-success criterion followed by operator approval. Promotion creates a new Skill version and reruns validation.

## API Additions

Exact route naming may follow existing project conventions, but the implementation must provide equivalent contracts for:

- create and stop a recording session;
- upload recording metadata and segmented binary artifacts;
- start annotation;
- read and edit draft annotations;
- validate a Skill;
- deploy an exact Skill version to a selected bridge;
- list Skills and deployment status;
- execute an exact Skill version;
- read execution state;
- submit and verify a recovery action;
- list and approve recovery candidates.

All routes require the existing authentication boundary. Upload routes enforce content type, integrity hash, archive path safety, and authenticated ownership.

## Storage

Recommended authoritative Linux paths:

```text
memory/equipment_skills/<skill_id>/<version>/
runs/equipment_skill_recordings/<recording_id>/
runs/equipment_skill_executions/<run_id>/
artifacts/equipment/<run_id>/skill_recovery/
```

Recommended Windows paths:

```text
C:\ATR\recordings\<recording_id>\
C:\ATR\skills\<skill_id>\<version>\
C:\ATR\programs\<segment_program_id>.json
C:\ATR\bridge_artifacts\<execution_id>\
```

Tokens, credentials, and sensitive screenshots remain excluded from Git. Retention policy is configurable by artifact class.

## GUI And CUI Requirements

GUI and CUI must call the same backend contracts and reflect the same registry state.

### Windows console

Program Manager remains available and gains two top-level work areas:

- `RECORD`: create and manage one operator demonstration recording;
- `SKILLS`: create, review, validate, deploy, test, disable, and remove versioned Skills.

`RECORD` provides:

- Record;
- Stop Recording;
- active target application and window;
- recording status and elapsed time;
- explicit checkpoint marker;
- upload status;
- Save Demonstration;
- Create Skill from the selected successful demonstration.

`SKILLS` provides:

- deployed Skill list and exact version;
- lifecycle state and target equipment profile;
- selected annotation model provenance from the shared ATR backend;
- automatic annotation progress;
- step, locator, checkpoint, and confidence review;
- compile and validation result;
- deployment target and deployment hash;
- Test Selected Skill;
- disable or remove a deployed version;
- latest exception and recovery status.

It does not expose the Gemma4 endpoint or credentials. Linux remains the reasoning owner.

The `SKILLS` surface reuses the existing Program Manager demonstration layout and interaction pattern. It is not a separate visual system or a second standalone application.

- A completed recording creates one Draft Skill card in the existing manager-style list.
- Skill cards use the same row/card sizing, selection behavior, status treatment, and action placement as current program demonstration entries.
- Each card shows only the Skill name, exact version, lifecycle state, target profile, selected creation model, deployment state, and latest test result.
- Selecting a card opens its details in the existing editor/detail area rather than a browser popup.
- Draft cards expose Review, Compile, Validate, and Delete.
- Validated cards expose Deploy, Test, New Version, Disable, and Delete according to lifecycle rules.
- Existing Program cards remain unchanged and visually distinct from versioned Skill cards through a compact `PROGRAM` or `SKILL` type label.
- Recording progress appears as the pending Draft Skill card instead of creating a separate duplicate status panel.

The Skill creation wizard executes these server-backed steps:

```text
Select successful demonstration
-> Create Skill draft
-> Check selected model capabilities
-> Run automatic annotation
-> Review uncertain annotations
-> Compile bounded macro segments
-> Validate Skill and segments
-> Deploy exact version
-> Test selected version
```

Closing or refreshing the Windows page does not cancel a creation job. Reopening `SKILLS` reloads its state from the Linux Skill registry through the authenticated ATR proxy.

### Lab Equipment Workspace

The Equipment Workspace provides:

- recording intake and annotation status;
- Skill review and validation;
- selected target profile and Windows candidate;
- exact deployed version and hash;
- current runtime state;
- exception evidence;
- recovery Tool, attempt, and verification;
- Operator Attention controls;
- recovery-candidate review.

### Live GUI and Runtime IDE

The existing Equipment Agent node remains the graph node. Skill execution is represented as its internal runtime, not as a new top-level agent.

Required states:

```text
RUNNING
CHECKPOINT_VERIFY
EXCEPTION
RECOVERING
RECOVERY_VERIFY
RESUMED
COMPLETED
ESCALATED
ABORTED
```

The Runtime IDE graph must show Equipment Agent -> Windows Bridge execution and Equipment Agent -> Guardian recovery approval edges when active.

## Security And Privacy

- Redact configured screen regions before upload.
- Exclude password fields and clipboard secrets from recorded keyboard events.
- Encrypt transport and avoid token-bearing URLs.
- Validate archive paths against traversal and symbolic-link attacks.
- Hash every recording, checkpoint, macro segment, and deployment bundle.
- Bind a deployed Skill to a target profile and platform.
- Keep physical actuation behind existing Live gates.
- Preserve PyAutoGUI fail-safe and emergency-stop behavior.
- Store all recovery requests and results in the request audit.

## Failure Codes

At minimum, define stable codes for:

- `SKILL_RECORDING_NOT_FOUND`;
- `SKILL_RECORDING_HASH_MISMATCH`;
- `SKILL_ANNOTATION_REVIEW_REQUIRED`;
- `SKILL_VALIDATION_FAILED`;
- `SKILL_DEPLOYMENT_VERSION_MISMATCH`;
- `SKILL_DEPLOYMENT_HASH_MISMATCH`;
- `SKILL_TARGET_PROFILE_MISMATCH`;
- `SKILL_CHECKPOINT_FAILED`;
- `SKILL_EXCEPTION_EVIDENCE_MISSING`;
- `SKILL_RECOVERY_NOT_ALLOWED`;
- `SKILL_RECOVERY_VERIFICATION_FAILED`;
- `SKILL_RECOVERY_ATTEMPTS_EXHAUSTED`;
- `SKILL_EXECUTION_CONNECTION_LOST`;
- `SKILL_EXECUTION_ESTOPPED`.

## Test And Live Semantics

### Test with local development bridge

- Uses the existing explicit localhost candidate.
- Validates recording, annotation, segmentation, deployment, execution state, exception packet, and recovery state transitions.
- Does not claim Windows locator or UIA validation.

### Test with Windows bridge

- Uses the selected Windows candidate and exact Skill version.
- Supports safe demonstration programs such as Program 1.
- Can deliberately induce a known popup or focus-loss exception.
- Must prove that normal steps cause no LLM call and the induced exception causes exactly one bounded recovery cycle.

### Live

- Requires explicit Live-enabled candidate and profile.
- Uses the same Skill and execution state machine as Test.
- Never switches to simulator or another candidate on failure.
- Physical or irreversible recovery remains Guardian-gated.

## Verification Strategy

### Unit tests

- package schema and hash validation;
- archive and upload limits;
- event/video timestamp synchronization;
- annotation confidence and review rules;
- macro segmentation at the 100-action boundary;
- locator priority;
- state-machine transitions;
- exception packet construction;
- recovery allowlist;
- idempotency and reconnect behavior;
- no LLM call on a fully successful deterministic run;
- recovery candidate cannot auto-promote.

### Integration tests

- record and compile Program 1;
- deploy its generated macro segment through the existing registry;
- execute through the Linux `WindowsPyAutoGUIBridge` client;
- confirm request-audit identity and artifacts;
- induce target-window focus loss;
- confirm pause, one Equipment Agent recovery decision, verification, and resume;
- disconnect and reconnect without duplicate actuation;
- confirm Test and Live do not silently cross routes.

### Browser tests

- Windows console recording and Skill status at 1920x1080;
- Equipment Workspace review, deploy, execute, exception, and recovery views;
- GUI refresh preserves server-authoritative state;
- GUI and CUI actions cross-reflect without browser-local registries;
- no token or sensitive screenshot data appears in browser URLs or logs.

### Acceptance criteria

The design is implementation-ready when all of the following can be demonstrated:

1. A successful Program 1 demonstration produces a draft `atr.equipment_skill.v1` package.
2. Automatic annotations expose steps, checkpoints, locators, confidence, and review requirements.
3. Validation emits one or more existing-schema macro segments with at most 100 actions each.
4. Windows executes the normal path locally without an LLM request.
5. A deliberate visual exception pauses the macro before an unsafe next action.
6. The Equipment Agent receives bounded evidence and selects only an allowed recovery Tool.
7. Recovery verification passes before execution resumes.
8. An exhausted or unsafe recovery becomes Operator Attention and does not continue.
9. Reconnect does not duplicate a click, keypress, file export, or physical command.
10. Exact Skill version, execution trace, checkpoint artifacts, LLM recovery summary, and final result remain auditable.

## Implementation Order

1. Define and validate the Skill, recording, exception, recovery, and candidate schemas.
2. Add the Skill registry and internal Equipment services without changing the closed-loop stage order.
3. Add recording and artifact transport without changing execution behavior.
4. Add deterministic automatic annotation and operator review.
5. Compile and deploy existing-schema macro segments through `WindowsPyAutoGUIBridge`.
6. Add local checkpoint verification and exception pause to the Windows runtime.
7. Connect bounded Equipment Agent recovery and existing Guardian validation.
8. Add reconnect, idempotency, and recovery-candidate persistence.
9. Project shared state into Windows console, Equipment Workspace, Live GUI, Runtime IDE, and CUI.
10. Run Program 1 end-to-end before enabling any physical equipment Skill.

## Documentation Impact

Implementation will require updates to:

- `docs/hardware/windows_pyautogui_equipment_agent_guideline.md`;
- `docs/hardware/windows_pyautogui_bridge_windows_setup.md`;
- Lab Equipment Workspace and user manual documentation;
- Runtime IDE and closed-loop references;
- `REQUIREMENTS.md` and installer documentation for recording, video encoding, OCR, UI Automation, and image comparison dependencies;
- Windows package deployment and migration guidance.
