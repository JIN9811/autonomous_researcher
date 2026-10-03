# Lab Equipment Agent / Windows Bridge Operations Guideline

## Architectural principles

Linux ATR owns decisions and execution records; the Windows Bridge is a lightweight PyAutoGUI Worker.

```text
LabEquipmentAgent (High-Level)
  -> EquipmentRuntimeService (Middle-Level)
  -> Windows/Local Bridge (Low-Level)
```

UTM is the first use case of the `utm_windows_v1` Profile. Do not hard-code equipment names, program names, window titles, or save paths in the Agent itself.

## Execution principles

1. Resolve the Profile and exact program/Skill version.
2. Create one `EquipmentExecutionRecord`.
3. Invoke only the selected provider's `equipment.pyautogui.run`.
4. Collect the Worker's raw results and evidence.
5. Apply the completion policy once on Linux.
6. Preserve the completed evidence package; hand it to Analysis only after the required Manipulation post-test clearance and fresh Vision clearance checks pass.

Do not automatically fall back to `utm.run_protocol` when a tool is unavailable. Register native/direct UTM explicitly through a separate Profile.

## State projections

The Agent, Workspace, Live GUI, CUI, and Runtime IDE read the same execution record.
States may differ by Profile, Skill, and provider; do not impose a representative example sequence
on every execution.

## Programs and Skills

- builtin: included with the Bridge, read-only
- local draft: Windows development/testing
- validated/deployed: deployed after Linux validation
- retired: unavailable for new execution

The Skill source of truth is Linux `memory/equipment_skills/`. Normal Skill block execution is deterministic.
The normal Managed Flow may also include bounded LLM selection before execution and result review afterward;
it does not call the model repeatedly between blocks. Exception recovery has separate bounded authority and evidence requirements.

## Recording-based Skill creation

```text
Windows Record
  -> bounded event/frame package
  -> Linux transfer
  -> selected Local/API LLM annotation
  -> deterministic compile
  -> static/simulator/local validation
  -> approval
  -> version/hash deployment
  -> Windows cache
```

Keep models and API keys off Windows. Recording memory is bounded; full-session frames are persisted to disk rather than limited to an in-memory ring buffer.

## Vision Link

Vision Link is optional and enabled by the Profile. Reuse existing evidence that meets freshness
and target-identity requirements, or call the Vision Agent tool. If neither is available, block
before execution. Vision provides observations only and does not directly command the Worker.

## Completion evidence

Examples of evidence a Profile may require:

- request/sequence/run/specimen identity
- target-window/checkpoint screenshots
- locator state
- output files with hashes/row probes
- Vision cross-checks
- Worker raw status/step traces

HTTP success alone does not establish completion. Preserve incomplete files and timeout results
as evidence, but do not allow handoff.

## Windows Console scope

The main Windows screen provides only Bridge Status, Program Manager, Recording, and Latest Local Result. UTM proof, Guardian, Analysis, Skill lifecycle, closed-loop operation, and ATR Controller discovery belong to the Linux Workspace.

## Initial connection

Use a one-time four-digit pairing code. After success, the internal key is automatically stored in protected files and is not shown in the user UI. Users do not enter or copy long-lived tokens. The same exchange can be retried for 30 seconds to retrieve the same key; this does not create another pairing.

## Safety and recovery

- unknown Profile/program: block without effects
- Worker unavailable: no automatic provider fallback
- locator/checkpoint failure: compiled recovery only
- invocation timeout: effects unknown; inspect before retry
- LLM: allowlisted selection/reasoning only
- physical equipment: Profile-specific live approval and a stop path required

## Verification criteria

- Generic Profiles run without hidden UTM/Vision dependencies.
- The UTM Profile validates required Vision evidence.
- Source and installed Windows servers remain in parity.
- Four-digit pairing enforces TTL, attempt limits, lockout, and persistence.
- Recording frame buffering uses bounded memory.
- Canonical runtime projections agree.
- Browser refresh does not create duplicate executions.
- Automated tests do not operate physical equipment.
