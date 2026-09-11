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
summary: Paper-first landing page for the Autonomous Researcher Framework system and supporting platform.
related_docs:
  - README.ko.md
  - README.en.md
  - docs/paper/README.md
  - docs/README.md
  - docs/standards/paper_documentation_standard.md
  - docs/runtime/current_code_snapshot.md
  - docs/runtime/three_level_control_model.md
  - CONTRIBUTING.md
  - SECURITY.md
supersedes: []
-->

# AX4LAB <sub>Powered by the ATR Framework</sub>

![AX4LAB — Autonomous Research Platform](docs/assets/branding/ax4lab-banner.png)

### Simple hardware. Structured intelligence. Self-driving laboratories.

AX4LAB adds a **structured AI control architecture to existing laboratories**.
Specialist agents connect reasoning, procedures, and device execution across
AI-native robots, API-controlled devices, and PC-operated instruments.

The approach combines **equipment reuse, a VLA-enabled robot arm, and advanced
software coordination**. It aims to reduce dependence on bespoke fixtures and
dedicated transfer automation while retaining the laboratory's existing
equipment and working environment.

[한국어 안내](README.ko.md)

<p align="center">
  <img src="docs/assets/branding/ax4lab-logo.png" alt="AX4LAB logo" width="180">
</p>

<div align="center">

| Documentation | What you'll find |
|:---:|:---:|
| **[Paper overview](docs/paper/README.md)** | Research motivation, contributions, and the paper reading path. |
| **[System architecture](docs/paper/02_system_architecture.md)** | Orchestration, agent responsibilities, and execution interfaces. |
| **[Agent references](docs/agents/README.md)** | Each agent's role, LLM decisions, tools, and verification. |
| **[Device bridges](docs/device_bridges/README.md)** | Robotics, equipment, and computation integration contracts. |
| **[Runtime IDE](docs/runtime/runtime_ide.md)** | Plan editing, execution control, and run inspection. |
| **[Results and evidence](docs/paper/06_evaluation_and_results.md)** | Demonstrated outcomes and their supporting artifacts. |
| **[Setup and operation](README.en.md)** | Installation, configuration, and operator workflows. |
| **[Documentation index](docs/README.md)** | All references, guides, and documentation standards. |

</div>

## Graphical Abstract

![AX4LAB transforms an existing laboratory through Multi-Agent AI orchestration, with a Device Bridge connecting AI-native, API-enabled, and PC-operated equipment](docs/assets/presentation/laboratory-transformation-sunburst.webp)

*Multi-agent orchestration connects existing equipment through device bridges.*

## Motivation

<sub>Barriers to adopting self-driving laboratories.</sub>

Building a self-driving laboratory remains a costly integration project, not
simply a matter of adding an AI model. Existing laboratories contain useful
instruments designed for human operation, while dedicated automation introduces
additional hardware, software, and engineering requirements.

- **Acquisition cost:** Replacing working instruments with automation-ready alternatives, or adding dedicated handling systems, increases the investment needed to begin.
- **Integration complexity:** API-controlled devices, desktop-operated instruments, and manual sample handling expose different interfaces that must work together.
- **Reconfiguration burden:** Automation tied to particular tasks, fixtures, and device combinations can require substantial reintegration when the experiment changes.

These adoption challenges motivate work on
[SDL accessibility](https://www.nature.com/articles/s41467-025-59231-1) and
[modular laboratory interfaces](https://www.nist.gov/programs-projects/development-standards-support-modular-and-autonomous-laboratory-ecosystem).
Our research question is: **How can an existing laboratory become self-driving
without rebuilding its automation around every new experimental workflow?**

![Three barriers between an existing laboratory and a self-driving laboratory: acquisition cost, integration complexity, and reconfiguration burden](docs/assets/presentation/self-driving-lab-barriers.webp)

## System Contribution

AX4LAB transforms existing laboratory capabilities through **hierarchical
automation, multi-agent coordination, and VLA-based manipulation**. Built on
the ATR Framework, it places the integration logic in reusable software
interfaces and agent-owned procedures while retaining existing instruments.

![Three parallel system contributions: Hierarchical Automation, Multi-Agent Coordination, and VLA-Based Manipulation](docs/assets/presentation/ax4lab-transformation-approach.webp)

| System contribution | How it addresses the barrier | Read more |
|---|---|---|
| Hierarchical automation and Device Bridges | High-Level decisions, Middle-Level procedures, and Low-Level tools separate research logic from API, desktop, and robot interfaces, enabling existing equipment to participate. | [Equipment interfaces](docs/device_bridges/README.md) |
| Multi-agent coordination | Specialist agents own task decisions, procedures, and evidence contracts; orchestration plans compose their capabilities so changes can be localized to the affected agents and interfaces. | [Agent responsibilities](docs/agents/README.md) |
| VLA-based physical integration | A learned-policy robot arm connects otherwise manual handling stages, offering an alternative to task-specific transfer fixtures; LeRobot separates supported robot integration from task coordination. | [Manipulation](docs/agents/manipulation_agent.md) |

The contribution is their **integration into a reusable research framework**:
simple hardware, advanced software coordination, and experiment feedback through
explicit agent handoffs. The current [experimental cycle](docs/paper/03_closed_loop_method.md)
is one configured application of that architecture.

## System Architecture

The framework separates coordination between agents, responsibility within
agents, and integration with laboratory equipment.

### Framework

The Orchestrator translates research intent into agent tasks and coordinates
their results through a configurable Orchestration Plan. Specialist agents
contribute capabilities to that plan rather than defining one fixed sequence.

![Research intent, configurable Orchestration Plan, and specialist-agent task/result exchange](docs/assets/presentation/framework-overview.webp)

- Task routing and specialist-agent coordination — [System architecture](docs/paper/02_system_architecture.md).
- Plan configuration and execution monitoring — [Runtime IDE](docs/runtime/runtime_ide.md).

### Agents

High-Level control owns task decisions, Middle-Level control supervises
procedures, and Low-Level tools perform execution. Guardian/Safety and
Knowledge/Evidence span these responsibilities; they are not extra sequential
stages. LLM decisions use the owning agent's permitted tools and evidence.

![High-Level decisions, Middle-Level procedures, and Low-Level tools with cross-cutting Guardian/Safety and Knowledge/Evidence](docs/assets/presentation/agent-architecture.webp)

- Responsibility levels and shared evidence — [Control model](docs/runtime/three_level_control_model.md).

### Integration

Agent procedures reach laboratory capabilities through tools and Device
Bridges. These adapters accommodate learned robot policies, device APIs, and
desktop-operated instruments, keeping device-specific execution separate from
the research plan.

![Agent tools and Device Bridges connect learned robot policies, API-controlled devices, and PC-operated instruments](docs/assets/presentation/integration-architecture.webp)

- Tool calls, contracts, and external connections — [API and connection matrix](docs/agents/agent_api_connection_matrix.md).

## Closed Loop

![Control and evidence flow in the research loop](docs/paper/assets/figures/03_closed_loop_evidence_flow.svg)

Design → Make → Observe and transfer → Test → Analyze → Learn and optimize → Design.

The execution graph also includes verification, operator review, failure routes,
and per-cycle artifacts. Analysis supplies measured objectives to optimization;
background FEM work can continue independently.

## Demonstration and Evidence

The retained supervised **mixed-mode closed-loop demonstration** completed
equipment testing, post-test clearance, Analysis, BO-managed LHS advancement,
and the next Design handoff. Printing deposition was skipped in that run;
specimen identity was not independently validated. It therefore demonstrates
that integrated path, not unattended end-to-end manufacturing.

Compression testing is the current application example, **not the definition
of the platform**.

| Question | Evidence |
|---|---|
| What completed in the recorded cycle? | [Closed-loop results](docs/paper/06_evaluation_and_results.md) |
| Which artifacts support each claim? | [Claim–evidence map](docs/paper/09_claim_evidence_traceability.md) |
| How can the checks be reproduced? | [Reproducibility](docs/paper/07_reproducibility.md) |
| Where are per-cycle outputs retained? | [Loop artifact archiving](docs/runtime/loop_artifact_archiving.md) |

Agent-local API, local-model, and virtual-device checks are reported in the
individual references. They do not replace physical validation. Comparative
cost, scientific benefit, and multi-run reliability remain evaluation work.

## Agent References

Each linked reference opens with a role diagram and current status, followed by
workflow, tools, interfaces, artifacts, and verification.

| Agent | Responsibility | Detailed reference |
|---|---|---|
| Orchestrator | Interpret intent and coordinate stage handoffs | [Orchestrator](docs/agents/orchestrator_agent.md) |
| Design | Review candidate suitability and emit design specifications | [Design](docs/agents/design_agent.md) |
| Specimen Making | Evaluate fabrication suitability and call preparation tools | [Specimen Making](docs/agents/specimen_agent.md) |
| Vision | Capture observations and review visual evidence | [Vision](docs/agents/vision_agent.md) |
| Manipulation | Select robot skills and review transfer completion | [Manipulation](docs/agents/manipulation_agent.md) |
| Lab Equipment | Execute stored workflows and review acquisition results | [Lab Equipment](docs/agents/equipment_agent.md) |
| Analysis | Process measurements and develop computational models | [Analysis](docs/agents/analysis_agent.md) |
| Knowledge | Curate Markdown knowledge and retrieve scoped context | [Knowledge](docs/agents/knowledge_agent.md) |
| Bayesian Optimization | Select optimization strategy and review numerical proposals | [BO](docs/agents/bo_agent.md) |
| Guardian | Review execution evidence and advise continuation | [Guardian](docs/agents/guardian_agent.md) |

## Platform Contribution

The supporting platform separates experiment logic from device interfaces,
model backends, and operator workspaces. Its extension surfaces make the
demonstrated system reusable; compatibility with another laboratory still
requires integration and validation.

[Platform architecture](docs/paper/04_platform_architecture.md) ·
[Runtime IDE](docs/runtime/runtime_ide.md) ·
[Interface contracts](docs/paper/appendix_a_interfaces.md)

## Device Bridge References

| Capability | Interface role | Reference |
|---|---|---|
| Printer fleet | Select and coordinate printer providers | [Printer Fleet](docs/device_bridges/printer_fleet_bridge.md) |
| Bambu Lab | Printer control and fabrication artifacts | [Bambu X2D](docs/device_bridges/bambu_x2d_bridge.md) |
| Prusa | Printer provider integration | [Prusa MK4S](docs/device_bridges/prusa_mk4s_bridge.md) |
| Robotics | Learned-policy execution, replay, and robot workspaces | [LeRobot](docs/device_bridges/lerobot_bridge.md) |
| Desktop instruments | Stored GUI workflows and acquisition | [Windows PyAutoGUI](docs/device_bridges/windows_pyautogui_bridge.md) |
| Test-area vision | Camera observations and verification evidence | [UTM Vision](docs/device_bridges/utm_vision_bridge.md) |
| Computation | Simulation and analysis adapters | [CAE](docs/device_bridges/cae_computation_bridges.md) |
| Virtual devices | Deterministic substitutes for non-hardware tests | [Base and Simulators](docs/device_bridges/base_simulator_bridges.md) |

## Getting Started

| Reader | Start here |
|---|---|
| Researcher or reviewer | [Problem and contributions](docs/paper/01_problem_and_contributions.md) → [Results](docs/paper/06_evaluation_and_results.md) |
| Operator | [Installation and operation](README.en.md) → [Device bridges](docs/device_bridges/README.md) |
| Developer | [Runtime reference](docs/runtime/current_code_snapshot.md) → [Agent APIs](docs/agents/agent_api_connection_matrix.md) |
| Contributor | [Contributing](CONTRIBUTING.md) → [Documentation rules](docs/standards/documentation_standard.md) |

Consult [operational limitations](docs/paper/08_safety_ethics_and_limitations.md)
before connecting physical equipment. [Security policy](SECURITY.md) covers
vulnerability reporting.

## Citation and License

Use the repository's [citation metadata](CITATION.cff) and [license](LICENSE).
The [paper package](docs/paper/README.md) is a working research narrative;
publication metadata is recorded only when available.
