<!-- atr-doc
doc_type: index
subtype: index
status: active
authority: navigation
audience:
  - user
  - operator
  - developer
  - maintainer
scope:
  - repository_documentation
summary: Reader entry points for setup, running experiments, recovery, results, and extension.
related_docs:
  - README.md
  - docs/paper/README.md
  - docs/standards/documentation_standard.md
  - docs/standards/paper_documentation_standard.md
  - docs/templates/document_types.md
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/device_bridges/README.md
  - docs/device_bridges/bridge_api_connection_matrix.md
  - docs/oldversion/README.md
  - docs/runtime/current_code_snapshot.md
  - docs/runtime/runtime_ide.md
  - docs/runtime/three_level_control_model.md
  - docs/modularity.md
supersedes: []
-->

<a id="documentation-index"></a>

# AX4LAB documentation

[한국어](README.ko.md) · [Project overview](../README.md)

Start with the task you want to complete. You do not need to learn the module
contracts or read the research paper before running your first experiment.

## Start here

1. [Install AX4LAB](../install/README.md) and open the application.
2. [Run your first experiment](tutorials/first_autonomous_run.en.md):
   choose a mode, prepare the equipment it uses, review the setup, approve
   execution, and find the result.
3. Keep the [user manual](tutorials/user_manual.en.md) nearby for later runs.
   The [screen tour](gui/visual_structure.md) shows where the controls live.

**Choose the mode before preparing the equipment.** TEST is not necessarily
hardware-free. Virtual Bridge, Installed Printer, and Physical Printing have
different physical effects. The [mode guide](runtime/test_mode.md) explains
the differences; the first-run tutorial walks through the choice.

<a id="summary"></a>
<a id="1-audience-paths"></a>

## What do you want to do?

| Task | Read this |
|---|---|
| Set up an external API or use the local model | [Model and API-key setup](runtime/api_keys.md) |
| Change slicing, placement, or printer options | [3DP workspace](tutorials/device_workspace_3dp_usage.en.md) |
| Set up the observation camera and check its images | [Vision Camera Bridge workspace](tutorials/device_workspace_vision_camera_bridge_usage.en.md) |
| Record, train, or run a robot policy | [LeRobot workspace and operating routes](hardware/lerobot_robotis_manipulation_runtime_guideline.md) |
| Connect the Windows instrument PC | [Windows bridge installation](hardware/windows_pyautogui_bridge_windows_setup.md), then [Equipment operation](hardware/windows_pyautogui_equipment_agent_guideline.md) |
| Read agent cards and follow the current stage | [Live GUI](gui/gui.md) |
| Supply documents and inspect stored knowledge | [Source Library](knowledge/manual_rag_knowledge.en.md), [Memory operations](knowledge/markdown_memory_operations.en.md) |
| Add a module or change the experiment composition | [Modularity](modularity.md), then [Runtime IDE](runtime/runtime_ide.md) and [Packages](../packages/README.md) |

The workspace guides cover direct device use. A manual workspace action is not
automatically a completed stage in an experiment; inspect the current run's
evidence and handoff state in Live GUI.

## When a run needs attention

Start from the symptom, not from a previous failure message.

| Situation | Guide |
|---|---|
| A paused or interrupted run needs to continue | [Resume and recovery](gui/run_resume.md) |
| A print is still running, but its wait stopped updating | [Printer-wait recovery](gui/printer_wait_recovery.md) |
| A camera image arrived, but the review did not finish | [Vision review recovery](gui/vision_review_recovery.md) |
| The Equipment workflow has the wrong or missing selection | [Equipment selection recovery](gui/equipment_selection_recovery.md) |
| A hardware alert remains visible | [Hardware alert lifecycle](gui/hardware_alert_lifecycle.md) |

Before retrying an operation, establish whether it already produced a physical
effect. An interrupted response does not prove that the printer, robot, or
instrument did nothing. These guides explain what can be reconciled and when
operator confirmation is still needed.

## Find results and review earlier cycles

Use an agent's **Artifacts** view for its saved files, or **Loop Artifacts** for
a completed cycle. The [artifact guide](runtime/loop_artifact_archiving.md)
explains run, loop, agent, and attempt ownership and how to recognize an
incomplete archive.

[Replay](gui/run_replay.md) is read-only inspection of saved session evidence.
It is different from a **robot replay**, which executes a recorded motion.
For run IDs, timestamps, event files, and diagnostic messages, see
[Logs and run identities](runtime/logging.md).

<a id="evidence-basis"></a>

For scientific interpretation, start with the [research overview](paper/README.md),
then read [results](paper/06_evaluation_and_results.md),
[reproducibility](paper/07_reproducibility.md), and the
[claim–evidence map](paper/09_claim_evidence_traceability.md).
The retained campaign contains **15 completed observation sets**; this is not
a claim of 15 uninterrupted, unattended hardware cycles. The
[campaign audit](paper/evidence/2026-09-28-campaign-archive-audit.md) describes
the retained evidence and its limits. The
[earlier supervised demonstration](paper/evidence/2026-09-07-supervised-closed-loop.md)
has its own mixed-mode and specimen-identity limitations.

<a id="3-페이지별-문서-맵"></a>

## Find a screen

| Screen | Route | Guide |
|---|---|---|
| Main GUI | `/` | [User manual](tutorials/user_manual.en.md) |
| Live GUI | `/live`, `/planning` | [Live GUI](gui/gui.md) |
| Replay | `/replay` | [Read-only Replay](gui/run_replay.md) |
| Runtime IDE | `/ide` | [Runtime IDE](runtime/runtime_ide.md) |
| Module Management | `/module-management` | [Modularity](modularity.md) |
| Knowledge | `/knowledge` | [Wiki and memory](knowledge/wiki_memory.md) |
| 3DP | `/printer` | [3DP workspace](tutorials/device_workspace_3dp_usage.en.md) |
| Vision Camera Bridge | `/device-bridge/vision-utm` | [Camera workspace](tutorials/device_workspace_vision_camera_bridge_usage.en.md) |
| LeRobot | `/lerobot` | [Robot workspace](hardware/lerobot_robotis_manipulation_runtime_guideline.md) |
| BO | `/bo` | [BO reference](agents/bo_agent.md) |
| Windows Equipment | `/equipment/windows` | [Equipment guide](hardware/windows_pyautogui_equipment_agent_guideline.md) |

<a id="2-documents-by-domain-실제-런타임-구조-요약"></a>
<a id="4-에이전트별-문서-맵"></a>
<a id="41-디바이스-브릿지별-문서-맵"></a>

## Understand or extend the system

Read [system architecture](paper/02_system_architecture.md) for the overall
design. When you need an exact interface, follow the owning reference:

- [Agent index](agents/README.md) and [agent connection matrix](agents/agent_api_connection_matrix.md):
  responsibilities, handoffs, tools, and evidence.
- [Device bridge index](device_bridges/README.md) and [bridge matrix](device_bridges/bridge_api_connection_matrix.md):
  supported capabilities, execution boundaries, and protocols.
- [Runtime IDE](runtime/runtime_ide.md), [modularity](modularity.md), and
  [packages](../packages/README.md): inspect and compose modules. Loading a
  package, applying a module, activating a graph, and executing a run are
  separate actions.
- [Runtime snapshot](runtime/current_code_snapshot.md),
  [control model](runtime/three_level_control_model.md),
  [LangGraph runtime](runtime/langgraph_runtime.md),
  [closed-loop routes (Korean technical reference)](runtime/closed_loop_and_pages_reference.md), and
  [experiment runtime](runtime/autonomous_experiment_runtime.md):
  implementation detail for integrators.
- [Knowledge reference boundary](knowledge/runtime_reference_safety.md) and
  [publication rules](knowledge/publication.md): how documentation and private
  evidence are separated from runtime authority.

<a id="scope"></a>
<a id="11-documents-by-type"></a>
<a id="12-authority-and-conflict-resolution"></a>
<a id="5-폴더별-책임"></a>
<a id="6-설명용-문서-폴더"></a>
<a id="7-이전-개발-자료"></a>
<a id="8-문서-유지-규칙"></a>
<a id="migration-status"></a>
<a id="limitations-and-known-gaps"></a>
<a id="index-verification"></a>
<a id="related-documents"></a>

## About these documents

Guides explain tasks; references describe implementation; evidence reports
record dated checks. Plans and archived designs are not operating instructions.
Use the [historical archive](oldversion/README.md) only to understand earlier
decisions. Runtime-consumed legacy guidelines are kept separate from this
reader-facing overhaul.

Documentation contributors should use the
[writing standard](standards/documentation_standard.md),
[templates](templates/document_types.md), and
[paper standard](standards/paper_documentation_standard.md).
The [manifest](document_manifest.yaml) tracks governed documents, not every
file in the repository. The [file-by-file review](maintenance/documentation_review_20260929.md)
and [code/documentation audit](maintenance/code_documentation_audit_20260928.md)
retain their original dates and scope.

Generated run data, credentials, and private memory remain local unless
explicitly reviewed for publication. A document link does not make them public.
Editing prose or checking links does not certify a device or repeat a physical
experiment.
