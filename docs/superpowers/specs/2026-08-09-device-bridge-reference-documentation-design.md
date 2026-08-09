---
doc_type: design
subtype: architecture
status: review
authority: proposal
audience:
  - researcher
  - reviewer
  - operator
  - developer
  - maintainer
scope:
  - device_bridge_documentation
  - figures
  - repository_navigation
summary: Approved design for capability-oriented device-bridge References, architecture figures, root navigation, and drift validation.
decision_status: approved
related_docs:
  - README.md
  - docs/agents/README.md
  - docs/agents/agent_api_connection_matrix.md
  - docs/standards/documentation_standard.md
  - docs/standards/paper_documentation_standard.md
  - docs/superpowers/specs/2026-08-09-agent-reference-figures-and-navigation-design.md
supersedes: []
---

# Device Bridge Reference Documentation Design

## Summary

This Design adds a canonical, capability-oriented documentation set for the
Autonomous Researcher Framework (ATR) device-bridge plane. It organizes the
implementation into eight operator-visible boundaries rather than treating
every Python class as an independent bridge or limiting the inventory to the
five entries currently projected through graph metadata.

The resulting package contains an index, a cross-bridge API and connection
matrix, eight detailed References, and 24 editable Graphviz figures with
matching checked-in SVG renderings. The root README exposes every Reference and
its figures. Documentation validation prevents missing sections, assets,
captions, navigation entries, and selected source-contract drift.

## Problem

The repository contains several overlapping notions of a device bridge:

- five capability entries in `graph.metadata.device_bridges`;
- live and test bridge classes under `device_bridges/`;
- printer provider selection that currently defaults to Bambu Lab X2D even
  though the graph projection names a Prusa bridge;
- registered CalculiX and PINN tool adapters that are not separate graph bridge
  entries;
- UTM runtime, RealSense, and specimen-pose components grouped behind camera
  and equipment APIs;
- Isaac Lab data and process sidecars used through `LeRobotBridge`;
- minimal base and simulator implementations used for deterministic test mode.

The existing hardware Guides explain selected setup and operating procedures,
but they do not provide one current, code-backed Reference per operational
boundary. Readers therefore have to reconstruct API ownership, tool
registration, provider routing, protocols, configuration, effects, evidence,
and recovery behavior from large implementation files.

## Goals

1. Provide one canonical Reference for each operator-visible bridge capability
   boundary.
2. Include the default Bambu provider and registered analysis/camera bridges,
   not only graph metadata entries.
3. Explain actual roles, APIs, tools, protocols, configuration, state,
   artifacts, safety gates, effects, timeout semantics, and recovery.
4. Distinguish a manager, a provider, a runtime sidecar, a pure artifact
   transformer, and a test simulator.
5. Show agent-to-tool-to-bridge-to-device flow without implying that a UI,
   model, or descriptor grants execution authority.
6. Make every Reference and figure directly reachable from the root README and
   the bridge index.
7. Reuse existing hardware Guides as procedural or historical detail without
   assigning them current interface authority.
8. Add automated checks for the complete document and figure contract.

## Non-goals

- Changing bridge, provider, tool, API, graph, safety, or runtime behavior.
- Making graph metadata silently match implementation through documentation
  edits.
- Duplicating every OpenAPI payload field or every private helper method.
- Treating pure Isaac data helpers as independently selectable hardware
  bridges.
- Replacing hardware setup and live-validation Guides.
- Claiming live reliability, safety effectiveness, hardware compatibility, or
  scientific validity from implementation inspection.
- Modifying or committing the pre-existing `.env.example` working-tree change.

## Options Considered

### Option A: Eight capability-oriented References

Group implementations by the boundary an operator, agent, or integrator
selects and monitors.

Advantages:

- matches tool, API, workspace, protocol, and effect boundaries;
- covers graph-registered and code-registered capabilities;
- keeps provider-specific printer behavior explicit;
- avoids presenting internal helper modules as independent devices.

Costs:

- some References describe several tightly coupled implementation files;
- the index must state which components are graph-projected and which are
  implementation-only or subordinate.

### Option B: One Reference per bridge-like Python class

Document every `BaseBridge` subclass, manager, runtime manager, and tracker as
an independent Reference.

Advantages:

- direct file-to-document mapping;
- maximal implementation granularity.

Costs:

- creates more than a dozen fragmented References;
- elevates compatibility shells and test simulators to the same status as live
  provider boundaries;
- splits one operator workflow across several documents.

### Option C: Only the five graph metadata entries

Use `graph.metadata.device_bridges` as the complete canonical inventory.

Advantages:

- smallest document set;
- exact alignment with `/api/bridges` projection.

Costs:

- omits the current default Bambu path;
- omits separately registered CalculiX and PINN tools;
- obscures RealSense, pose-tracking, and UTM runtime components;
- repeats a known graph-versus-runtime coverage gap instead of explaining it.

## Decision

Use Option A. Create eight operational References, one shared index, and one
cross-bridge matrix. Each Reference receives three figures because connection
and effect boundaries are the defining properties of a bridge, including the
base/simulator family where the absence of a live effect must be explicit.

## Canonical Document Inventory

All new governed documents live under `docs/device_bridges/`.

| File | Canonical boundary | Included implementation |
|---|---|---|
| `README.md` | Navigation and inventory authority | all eight boundaries and graph/tool classification |
| `bridge_api_connection_matrix.md` | Cross-bridge comparison | APIs, tools, protocols, effects, evidence, recovery |
| `printer_fleet_bridge.md` | Provider selection and shared printer workflow | `PrinterDeviceBridgeManager`, fleet/profile memory, `printer.prepare` routing |
| `bambu_x2d_bridge.md` | Bambu Lab X2D provider | slicer, MQTT, FTPS, video, HTTP artifact route, pure G-code autoejection patching |
| `prusa_mk4s_bridge.md` | Prusa MK4S provider | PrusaLink, PrusaSlicer, workflow, G-code validation, optional ejection routine |
| `lerobot_bridge.md` | LeRobot robot/process boundary | profiles, ports, camera, teleoperation, recording, training, rollout, Isaac sidecars |
| `windows_pyautogui_bridge.md` | Windows desktop equipment boundary | bridge discovery/authentication, registered programs, locators, screenshots, request/proof records |
| `utm_vision_bridge.md` | UTM and visual observation boundary | ROS runtime manager, camera stream/configuration, RealSense, specimen pose, state observer, macro compatibility |
| `cae_computation_bridges.md` | External scientific computation boundary | CAE facade, CalculiX job bridge, PINN dataset/train/predict registry |
| `base_simulator_bridges.md` | Shared interface and deterministic test substitutes | `BaseBridge`, printer/camera/robot/UTM simulators, compatibility shells |

The index MUST label each boundary as one or more of `graph_projected`,
`tool_registered`, `api_exposed`, `provider`, `runtime_sidecar`,
`artifact_transformer`, or `test_only`. These labels prevent the index from
claiming that all eight are independently selectable through `/api/bridges`.

## Common Reference Structure

Every bridge Reference uses these second-level sections in this order:

1. `Summary`
2. `Scope`
3. `Source of Truth`
4. `Actual Role`
5. `System Position and Agent Handoffs`
6. `Inputs, Commands, and Outputs`
7. `Internal Execution`
8. `API Surface`
9. `Tools and Registry Integration`
10. `Connections and Protocols`
11. `Configuration and Secrets`
12. `State, Events, Artifacts, and Evidence`
13. `Runtime Modes and Fallbacks`
14. `Safety, Approval, and Effect Boundary`
15. `Errors, Timeouts, and Recovery`
16. `Operator and GUI Surfaces`
17. `Current Verification`
18. `Limitations and Known Gaps`
19. `Related Documents`

The common outline is mandatory even when a boundary has no owned HTTP API or
no live protocol. Such sections state `none` and explain the actual access path
instead of being omitted.

## Content Contract

Each Reference MUST identify:

- initiating and consuming agents;
- registered tool names and resource registrations;
- curated functional API families with methods and effect classification;
- implementation files and configuration sources;
- local calls, subprocesses, HTTP, MQTT, FTPS, PrusaLink REST, ROS 2, camera,
  serial, solver, filesystem, or other protocols actually used;
- environment-variable names without secret values;
- memory, artifact, log, image, dataset, and result locations;
- test, simulator, dry-run, virtual-live, and live behavior;
- whether provider fallback is automatic, explicit, or prohibited;
- validation, capability, allowlist, approval, preflight, and proof gates;
- the exact boundary at which physical, desktop, network, subprocess, or
  persistent effects may begin;
- stop/status ownership and the evidence required before retry;
- known no-effect versus unknown-effect timeout handling;
- inspected tests and unevaluated configurations;
- mismatches among code, graph metadata, API projection, and legacy Guides.

The matrix owns cross-bridge comparison. Individual References own detailed
lifecycle, payload categories, provider behavior, and recovery notes.

## Figure Inventory

All figure assets live under `docs/device_bridges/assets/figures/`. Every
editable `.dot` source has a same-stem checked-in `.svg` rendering.

| Reference ID | Required figure stems |
|---|---|
| `printer_fleet` | `printer_fleet_01_system_handoffs`, `printer_fleet_02_execution_effect_boundary`, `printer_fleet_03_api_connection_architecture` |
| `bambu_x2d` | `bambu_x2d_01_system_handoffs`, `bambu_x2d_02_execution_effect_boundary`, `bambu_x2d_03_api_connection_architecture` |
| `prusa_mk4s` | `prusa_mk4s_01_system_handoffs`, `prusa_mk4s_02_execution_effect_boundary`, `prusa_mk4s_03_api_connection_architecture` |
| `lerobot` | `lerobot_01_system_handoffs`, `lerobot_02_execution_effect_boundary`, `lerobot_03_api_connection_architecture` |
| `windows_pyautogui` | `windows_pyautogui_01_system_handoffs`, `windows_pyautogui_02_execution_effect_boundary`, `windows_pyautogui_03_api_connection_architecture` |
| `utm_vision` | `utm_vision_01_system_handoffs`, `utm_vision_02_execution_effect_boundary`, `utm_vision_03_api_connection_architecture` |
| `cae_computation` | `cae_computation_01_system_handoffs`, `cae_computation_02_execution_effect_boundary`, `cae_computation_03_api_connection_architecture` |
| `base_simulator` | `base_simulator_01_system_handoffs`, `base_simulator_02_execution_effect_boundary`, `base_simulator_03_api_connection_architecture` |

This produces 24 `.dot` files and 24 `.svg` files. Stems are stable public
identifiers.

## Figure Contracts

### Figure 1: System Position and Agent Handoffs

Each Figure 1 MUST show the initiating agent or operator surface, registered
tool or API entry, documented bridge boundary, external target, downstream
consumer, and returned state or evidence. Control and evidence paths remain
visually distinct. Graph projection and code-only registration are labeled
when they differ.

### Figure 2: Execution and Effect Boundary

Each Figure 2 MUST show input validation, configuration resolution, preflight,
approval or policy gate, invocation, first external-effect point, observation,
evidence persistence, and recovery alternatives. It MUST distinguish
`known_no_effect`, `effect_observed`, and `effect_unknown` where the boundary
can time out after invocation.

### Figure 3: API and Connection Architecture

Each Figure 3 MUST show functional API families, registered tools/resources,
manager/provider layers, protocols, external software or hardware, and
status/evidence return paths. Optional, compatibility, and fallback paths are
dashed and condition-labeled. Adjacent text states that a model, UI, module
descriptor, or graph projection cannot bypass registered policy and bridge
gates.

## Visual Grammar

The device-bridge figures reuse the agent and paper visual language:

| Meaning | Shape/style |
|---|---|
| Agent, API, tool, or processing step | rounded box with text label |
| Validation, approval, policy, or preflight gate | diamond |
| Artifact, log, event, state, or evidence | note |
| Provider, protocol, external software, or runtime | component |
| Physical or desktop effect | octagon with bold border |
| Stop, review, unavailable, or unknown-effect outcome | bold bordered box |
| Required current flow | solid arrow |
| Optional, compatibility, fallback, or test flow | dashed arrow with condition |
| Evidence return, distinct from control | green arrow labeled `evidence` |

Color alone MUST NOT carry meaning. Captions state the message, scope, and
`inspection` evidence boundary and MUST NOT promote inspection into live,
safety-effectiveness, or scientific evidence.

## Root and Index Navigation

The root `README.md` receives a `Device Bridge References` section adjacent to
the agent navigation and before lower-priority operational material. Its table
contains exactly eight rows and these columns:

| Column | Required content |
|---|---|
| `Boundary` | canonical label linked to the Reference |
| `Actual role` | one bounded role phrase |
| `Agent/tool entry` | primary agent and tool family |
| `Protocol/target` | principal connection and target |
| `Highest effect` | none, local/subprocess, network, desktop, or physical with gate qualifier |
| `Details` | Reference link |
| `Figures` | direct Flow, Execution, and Connections links |

`docs/device_bridges/README.md` provides the classification-aware inventory,
recommended reading paths, authority order, legacy Guide mapping, update
checklist, and verification method. It links all 24 figures directly.

## Existing Hardware Guides

Existing files under `docs/hardware/` remain procedural or time-bounded
context. New References link them under `Related Documents` and the bridge
index maps each Guide to its canonical Reference. No existing Guide is
silently reclassified, moved, or deleted in this change.

## Documentation Standard Changes

`docs/standards/documentation_standard.md` gains a normative `Device Bridge
Reference Figures` section. It defines the eight-Reference inventory, required
sections, 24 stable figure stems, asset pairing, caption requirements, visual
semantics, root navigation, authority boundary, and update obligations.

All ten new Markdown files are added to `docs/document_manifest.yaml` as active
governed documents. Each active Reference declares code/config
`source_of_truth`, an ISO `last_verified` date, and a committed
`verified_against` baseline. The implementation baseline is the last commit
before bridge documentation-only changes; later documentation commits are
described as such.

## Validation and Testing

`scripts/validate_documentation.py` and its unit tests MUST check:

1. the index, matrix, and eight Reference files are governed;
2. all 19 required H2 sections exist in order in each Reference;
3. all 24 stable figure stems have both `.dot` and `.svg` assets;
4. every owning Reference embeds all three SVGs and has stable captions;
5. the bridge index links every Reference and all 24 figures;
6. the root README contains exactly eight canonical bridge rows with direct
   Reference and figure links;
7. no undeclared extra bridge figure pair appears in the governed asset set;
8. local links and metadata paths remain valid;
9. curated documented tool names exist in the registered tool source or an
   explicit generated inventory used by validation;
10. selected documented API families correspond to imported FastAPI routes or
    a clearly labeled non-HTTP boundary;
11. changed `.dot` sources render reproducibly to their checked-in SVGs.

Focused verification runs documentation and paper validators, validator unit
tests, selected bridge tests covering the documented contracts, and Graphviz
fresh-render byte comparisons. Full `pytest` is not a completion gate for this
documentation-only change because the repository has known unrelated runtime
and browser-test instability; any attempted full run is reported separately
and never represented as passing if it does not.

## Error and Drift Handling

Documentation MUST expose rather than normalize these cases:

- a bridge implemented and tool-registered but absent from graph metadata;
- a graph bridge label that represents only one provider while runtime routing
  supports another current default;
- an API family that reaches a service manager rather than a `BaseBridge`
  subclass;
- a test-only simulator that does not establish live compatibility;
- a pure artifact transformer that cannot itself cause device motion;
- a timeout after an external command where effect state is unknown;
- optional dependencies, missing executables, unavailable camera/serial/ROS
  processes, or disabled live gates.

When code and a Reference conflict, code remains current and validation should
make likely drift visible. The document records a Known Gap instead of
inventing an intended behavior.

## Completion Criteria

The implementation is complete when:

- all ten governed bridge documents exist with required metadata and content;
- all 24 Graphviz source/render pairs exist and are embedded;
- the root README and bridge index expose all canonical entry paths;
- the matrix covers all eight boundaries and their graph/tool/API
  classification;
- the Documentation Standard and validator enforce the contract;
- focused documentation, figure, and selected bridge verification passes;
- no runtime behavior is changed;
- the unrelated `.env.example` modification remains unstaged;
- documentation changes are intentionally committed and pushed after final
  verification, consistent with the surrounding documentation workflow.

## Spec Self-Review

- Placeholder scan: no unresolved `TBD` or `TODO` remains.
- Internal consistency: the inventory is eight References, three figures per
  Reference, and 24 source/render pairs throughout.
- Scope: the work changes documentation, figures, navigation, validation, and
  validator tests only.
- Ambiguity: operational grouping, graph-versus-code classification, effect
  terminology, asset names, and completion gates are explicit.

## Related Documents

- [Agent Reference Index](../../agents/README.md)
- [Agent API and Connection Matrix](../../agents/agent_api_connection_matrix.md)
- [Documentation Standard](../../standards/documentation_standard.md)
- [Paper Documentation Standard](../../standards/paper_documentation_standard.md)
- [Agent Reference Figures and Navigation Design](2026-08-09-agent-reference-figures-and-navigation-design.md)
