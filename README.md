<!-- atr-doc
doc_type: index
subtype: index
status: active
authority: navigation
audience:
  - researcher
  - reviewer
  - artifact_evaluator
  - operator
  - developer
scope:
  - repository
  - paper
summary: Reader-first introduction to AX4LAB, operating guides and research evidence.
related_docs:
  - README.ko.md
  - docs/paper/README.md
  - docs/README.md
  - docs/standards/paper_documentation_standard.md
  - docs/runtime/current_code_snapshot.md
  - docs/runtime/three_level_control_model.md
  - docs/modularity.md
  - CONTRIBUTING.md
  - SECURITY.md
supersedes: []
-->

# AX4LAB
<sub>Powered by the ATR Framework</sub>

[한국어](README.ko.md) · [User documentation](docs/README.md) · [Research and evidence](docs/paper/README.md)

![AX4LAB — Autonomous Research Platform](docs/assets/branding/ax4lab-banner.png)

AX4LAB connects the steps of a laboratory experiment: proposing a design,
making a specimen, moving it, testing it, interpreting the measurements and
choosing what to try next. It combines specialist AI agents with software
procedures and device bridges so that existing printers, robot arms and
PC-operated instruments can participate in the same workflow.

The current application is a closed-loop Gyroid compression experiment. It is
an example of the framework, not a requirement that every laboratory use the
same material, instruments or sequence.

## Getting Started

Choose the path that matches what you want to do. You do not need to read the
implementation references before using the application.

| Your goal | Reading path |
|---|---|
| Set up AX4LAB and complete a first run | [Install](install/README.md) → [first experiment](docs/tutorials/first_autonomous_run.en.md) |
| Use an existing installation | [User manual](docs/tutorials/user_manual.en.md) → [task directory](docs/README.md) |
| Find your way around the GUI | [Annotated screen guide](docs/gui/visual_structure.md) |
| Review the experiment and its results | [Research overview](docs/paper/README.md) → [results](docs/paper/06_evaluation_and_results.md) |
| Add a capability or change a workflow | [Modularity](docs/modularity.md) → [Runtime IDE](docs/runtime/runtime_ide.md) |

Before using equipment, choose the [execution profile](docs/runtime/test_mode.md).
A virtual-bridge test has different effects from an installed-printer test or
a full physical print. The word **TEST does not by itself mean hardware-free**.
The first-run guide explains the preparation and confirmation required for each
path.

## Working with an experiment

You begin by describing the experiment and reviewing its setup. The
Orchestrator coordinates the admitted work; the individual agents perform their
parts and return evidence. In the Live GUI, follow the current task, inspect
its report and respond when operator input is needed. A request being accepted
is not the same as the device action being completed.

![Live GUI showing the experiment state, agent navigation and a report](docs/gui/assets/screenshots/2026-09-29/live-overview.png)

*Use the status bar to orient yourself, the agent rail to choose a report, and
the report to check the evidence behind a result. This is a dated screen
example; see the [screen guide](docs/gui/visual_structure.md) for capture scope
and the individual controls.*

Common operating tasks have their own guides:

- [Change print options](docs/tutorials/device_workspace_3dp_usage.en.md),
  including motion scaling and start/end behavior.
- [Inspect the camera and verification images](docs/tutorials/device_workspace_vision_camera_bridge_usage.en.md).
- [Pause or resume a run](docs/gui/run_resume.md), or
  [recover a printer wait](docs/gui/printer_wait_recovery.md).
- [Open a saved run in read-only Replay](docs/gui/run_replay.md) and
  [locate per-cycle artifacts](docs/runtime/loop_artifact_archiving.md).

Read-only Replay is a view of saved evidence. Robot replay is a physical motion
operation; the two are not interchangeable. For equipment work, follow the
relevant readiness checks and [operating limits](docs/paper/08_safety_ethics_and_limitations.md).

<a id="motivation"></a>
<a id="why-the-platform-is-organized-this-way"></a>

## System Contribution

Existing laboratories contain useful instruments with different interfaces.
Replacing them all, adding dedicated transfer hardware, or rebuilding their
integration for every experiment makes automation difficult to adopt. AX4LAB
addresses that integration problem by separating three responsibilities:

- **Decisions:** agents interpret the task and review the evidence available to them.
- **Procedures:** software carries out the allowed workflow and checks its results.
- **Device execution:** bridges communicate with robot policies, device APIs or
  desktop applications.

This separation lets an experiment reuse existing capabilities while keeping
device-specific work out of the research plan. It does not make an unconfigured
instrument ready to operate. A different laboratory still needs integration and
validation. The [research introduction](docs/paper/01_problem_and_contributions.md)
explains the motivation and related work.

<a id="system-architecture"></a>
<a id="framework"></a>
<a id="agents"></a>
<a id="integration"></a>
<a id="how-the-parts-fit-together"></a>

## Platform Contribution

The Orchestrator connects specialist work through an Orchestration Plan.
Within that work, permitted tools and procedures perform execution; numerical
services compute measured properties and BO proposals. Guardian checks and
Knowledge records support the process across stages.

![Research intent, an Orchestration Plan and specialist task/result exchange](docs/assets/presentation/framework-overview.webp)

For the responsibility model, read [system architecture](docs/paper/02_system_architecture.md).
For the exact distinction between decisions, procedures and device actions,
read [three-level control](docs/runtime/three_level_control_model.md). For
configuration and extension, use [modularity](docs/modularity.md).

## Orchestration Route

[![Configured runtime map with agent handoffs, control gates and evidence connections](docs/assets/readme/orchestration-route.svg)](docs/assets/readme/orchestration-route.svg)

The map is useful when following a handoff or investigating a return to an
earlier stage. It includes conditional paths; it is not a promise that every
run visits each node exactly once. The [Runtime IDE guide](docs/runtime/runtime_ide.md)
explains how to inspect the configured graph and the current execution.

## Demonstration and Evidence

The [retained campaign audit](docs/paper/evidence/2026-09-28-campaign-archive-audit.md)
reconciles **15 completed experimental observations** with per-iteration Gyroid
STL files, stress–strain curves, properties and BO input/next-point records.
The audit checked artifact hashes and SEA normalization. Failed attempts,
operator interventions and recovery history remain part of the record.

These records support recorded multi-cycle operation. They do not establish
unattended manufacturing, a comparative cost advantage or controlled scientific
superiority. Earlier supervised mixed-mode demonstrations are documented
separately, including skipped deposition and specimen-identity limits.
Agent-local API, local-model and virtual-device checks do not substitute for
physical validation.

Continue with [results and interpretation](docs/paper/06_evaluation_and_results.md),
the [claim–evidence map](docs/paper/09_claim_evidence_traceability.md), or
[reproducibility](docs/paper/07_reproducibility.md). The
[dated implementation audit](docs/maintenance/code_documentation_audit_20260928.md)
also distinguishes main from separate RPT development; do not assume a feature
on another branch is installed here.

## Agent References

Use these when you need an agent's exact responsibilities, evidence requirements
or interfaces. For everyday actions, start with the user guides above.

<details>
<summary>Responsibilities and detailed contracts</summary>

| Agent | Responsibility | Detailed reference |
|---|---|---|
| Orchestrator | Review intent and confirmed Setup; coordinate admitted handoffs | [Orchestrator](docs/agents/orchestrator_agent.md) |
| Design | Review candidate suitability and produce design specifications | [Design](docs/agents/design_agent.md) |
| Specimen Making | Review fabrication suitability and call preparation tools | [Specimen Making](docs/agents/specimen_agent.md) |
| Vision | Capture observations and review visual evidence | [Vision](docs/agents/vision_agent.md) |
| Manipulation | Execute saved robot skills and review transfer completion | [Manipulation](docs/agents/manipulation_agent.md) |
| Lab Equipment | Execute stored workflows and review acquisition results | [Lab Equipment](docs/agents/equipment_agent.md) |
| Analysis | Parse measurements, compute properties and SEA, and publish BO evidence | [Analysis](docs/agents/analysis_agent.md) |
| Knowledge | Curate Markdown knowledge and retrieve scoped context | [Knowledge](docs/agents/knowledge_agent.md) |
| Bayesian Optimization | Choose a strategy and review numerical proposals | [BO](docs/agents/bo_agent.md) |
| Guardian | Check execution evidence and review continuation | [Guardian](docs/agents/guardian_agent.md) |

[Agent reading guide](docs/agents/README.md) · [API and connection matrix](docs/agents/agent_api_connection_matrix.md)

</details>

## Device Bridge References

<details>
<summary>Equipment interfaces and their contracts</summary>

| Capability | Interface role | Reference |
|---|---|---|
| Printer fleet | Select and coordinate printer providers | [Printer Fleet](docs/device_bridges/printer_fleet_bridge.md) |
| Bambu Lab | Printer control and fabrication artifacts | [Bambu X2D](docs/device_bridges/bambu_x2d_bridge.md) |
| Prusa | Printer provider integration | [Prusa MK4S](docs/device_bridges/prusa_mk4s_bridge.md) |
| Robotics | Learned-policy execution and physical robot replay | [LeRobot](docs/device_bridges/lerobot_bridge.md) |
| Desktop instruments | Stored GUI workflows and acquisition | [Windows PyAutoGUI](docs/device_bridges/windows_pyautogui_bridge.md) |
| Test-area vision | Camera observations and verification evidence | [UTM Vision](docs/device_bridges/utm_vision_bridge.md) |
| Virtual devices | Deterministic non-hardware substitutes | [Base and Simulators](docs/device_bridges/base_simulator_bridges.md) |

[Choose an equipment guide](docs/device_bridges/README.md).
Bridge availability is not a device-readiness or physical-safety guarantee.

</details>

## Graphical Abstract

<details>
<summary>Research illustrations and further explanation</summary>

![Connecting an existing laboratory through multi-agent orchestration](docs/assets/presentation/laboratory-transformation-sunburst.webp)

![Acquisition cost, integration complexity and reconfiguration burden](docs/assets/presentation/self-driving-lab-barriers.webp)

![Hierarchical automation, multi-agent coordination and VLA-based manipulation](docs/assets/presentation/ax4lab-transformation-approach.webp)

![Decision, procedure and tool responsibilities with shared safety and evidence](docs/assets/presentation/agent-architecture.webp)

![Bridges connect robot policies, device APIs and desktop-operated instruments](docs/assets/presentation/integration-architecture.webp)

These are explanatory illustrations, not experimental observations.
[Figure provenance](docs/assets/presentation/README.md) and the
[research chapters](docs/paper/README.md) provide context.

</details>

## Citation and License

Use the [citation metadata](CITATION.cff) and read the [license](LICENSE) before
reuse. The [paper package](docs/paper/README.md) is a working research narrative;
publication metadata is recorded when available.
[Contributing](CONTRIBUTING.md) explains development contributions, and
[Security](SECURITY.md) explains vulnerability reporting.
