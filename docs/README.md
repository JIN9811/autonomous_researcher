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
summary: Audience-, type-, and domain-oriented index for ATR documentation.
related_docs:
  - README.md
  - docs/paper/README.md
  - system/standards/documentation_standard.md
  - system/standards/paper_documentation_standard.md
  - system/templates/document_types.md
  - system/agents/README.md
  - system/agents/agent_api_connection_matrix.md
  - system/device_bridges/README.md
  - system/device_bridges/bridge_api_connection_matrix.md
  - system/retained-history/README.md
  - system/runtime/current_code_snapshot.md
  - system/runtime/runtime_ide.md
  - system/runtime/three_level_control_model.md
  - system/modularity.md
supersedes: []
-->

# Documentation Index

Use this index to choose a reading path. Detailed behavior belongs in the linked
owner reference, not in a second copy of the same instructions here.

| Goal | Start here |
|---|---|
| Install and run the application | [Installation](../runtime/install/README.md) → [Tutorial selector](tutorials/first_autonomous_run.md) |
| Understand the existing screens | [GUI structure and 1920 × 1080 screenshots](../system/runtime/gui/visual_structure.md) |
| Understand the research and retained results | [Paper overview](paper/README.md) → [Results](paper/06_evaluation_and_results.md) |
| Change or extend a module | [Modularity](../system/modularity.md) → [Runtime IDE](../system/runtime/runtime_ide.md) → [Packages](../runtime/packages/README.md) |
| Inspect an agent or device contract | [Agent references](../system/agents/README.md) · [Bridge references](../system/device_bridges/README.md) |
| Find older decisions | [Historical archive](../system/retained-history/README.md), not current operating instructions |

## Summary

Current references describe the checked-in implementation. Guides explain how
to use it. Evidence reports describe only the dated checks and runs they name.
Designs and plans do not establish implemented behavior.

## Scope

This index covers public project documentation, including the separate
[historical archive](../system/retained-history/README.md). Generated run data, credentials,
datasets, and local-only retired artifacts are not made public by linking them.
The [documentation manifest](../system/document_manifest.yaml) defines the subset with
machine-enforced metadata; it is not the complete repository file inventory.

## Evidence Basis

- [Campaign archive audit, 2026-09-28](paper/evidence/2026-09-28-campaign-archive-audit.md):
  15 retained experimental observations and their STL, curves, properties and BO
  records; not a new unattended hardware trial.
- [Earlier supervised one-cycle report, 2026-09-07](paper/evidence/2026-09-07-supervised-closed-loop.md):
  mixed-mode demonstration with explicit deposition and specimen-identity limits.
- [Code/documentation audit, 2026-09-28](../system/maintenance/code_documentation_audit_20260928.md):
  dated main-code, test, campaign and separate RPT-worktree distinctions.
- [Documentation standard](../system/standards/documentation_standard.md):
  authority, classification and verification rules.

## 1. Audience Paths

| Reader | Recommended sequence |
|---|---|
| New operator | [Install](../runtime/install/README.md), [first run EN](tutorials/first_autonomous_run.en.md) / [한국어](tutorials/first_autonomous_run.ko.md), [user manual EN](tutorials/user_manual.en.md) / [한국어](tutorials/user_manual.ko.md) |
| Existing operator | [GUI reference](../system/runtime/gui/visual_structure.md), [Live details](gui/gui.md), [Replay](gui/run_replay.md), relevant workspace guide below |
| Researcher / reviewer | [Paper](paper/README.md), [claim–evidence map](paper/09_claim_evidence_traceability.md), [reproducibility](paper/07_reproducibility.md), [limitations](paper/08_safety_ethics_and_limitations.md) |
| Developer | [Code snapshot](../system/runtime/current_code_snapshot.md), [control model](../system/runtime/three_level_control_model.md), [runtime](../system/runtime/langgraph_runtime.md), [module contracts](../system/modularity.md) |
| Documentation contributor | [Writing standard](../system/standards/documentation_standard.md), [paper standard](../system/standards/paper_documentation_standard.md), [templates](../system/templates/document_types.md), [contributing](project/CONTRIBUTING.md) |

## 1.1 Documents by Type

| Type | Meaning | Entry point |
|---|---|---|
| Index | Navigation, not a second runtime specification | This page |
| Standard | Authoring, evidence and publication requirements | [Standards](../system/standards/documentation_standard.md) |
| Reference | Current implemented behavior with source ownership | [Runtime snapshot](../system/runtime/current_code_snapshot.md) |
| Guide | Operator/developer procedure | [Tutorials](tutorials/first_autonomous_run.md) |
| Design / Plan | Proposed decisions or implementation work; check lifecycle and branch | [Plans](../system/plans) · [Designs](../system/specs) |
| Evidence | Dated observations and checks, with limits | [Evidence map](paper/09_claim_evidence_traceability.md) |
| Archive | Historical intent; never a current execution instruction | [Archive index](../system/retained-history/README.md) |

## 1.2 Authority and Conflict Resolution

Actual code, active graph/module configuration and run evidence establish
implementation and execution facts. A reference can explain those facts but
cannot override them. Follow the [standard's authority rules](../system/standards/documentation_standard.md)
when documents disagree; do not treat a past successful run as current device readiness.

## 2. Documents by Domain: 실제 런타임 구조 요약

| Domain | Maintained owner documents |
|---|---|
| Execution, routes and modes | [Current snapshot](../system/runtime/current_code_snapshot.md), [closed loop and pages](../system/runtime/closed_loop_and_pages_reference.md), [experiment API](../system/runtime/autonomous_experiment_runtime.md) |
| Graph and module lifecycle | [LangGraph](../system/runtime/langgraph_runtime.md), [Runtime IDE](../system/runtime/runtime_ide.md), [modularity](../system/modularity.md), [packages](../runtime/packages/README.md) |
| Models and credentials | [Agent program baseline](../system/runtime/agent_program_baseline.md), [API keys](../system/runtime/api_keys.md) |
| Safety and recovery evidence | [Guardian](../system/runtime/guardian_graphwide_safety.md), [hardware alerts](gui/hardware_alert_lifecycle.md) |
| Run persistence and playback | [Loop artifacts](../system/runtime/loop_artifact_archiving.md), [read-only Replay](gui/run_replay.md) |
| Knowledge | [Wiki and memory](../system/knowledge/wiki_memory.md), [operations](../system/knowledge/markdown_memory_operations.ko.md), [Source Library](../system/knowledge/manual_rag_knowledge.ko.md), [runtime reference boundary](../system/knowledge/runtime_reference_safety.md), [publication](../system/knowledge/publication.md) |
| Platform explanations | [English AX4LAB Wiki](../system/knowledge/wiki/platform-overview.md) |

Test mode is not a universal guarantee of no physical effects. Installed-printer
and physical-printing scenarios have different boundaries; use the
[tutorial's mode procedure](tutorials/first_autonomous_run.en.md) and the
[scenario reference](../system/runtime/autonomous_experiment_runtime.md).
Package loading, module application, graph activation and run execution are
separate actions; see [modularity](../system/modularity.md).

## 3. 페이지별 문서 맵

The [screen reference](../system/runtime/gui/visual_structure.md) contains the screenshot tour.
The table below points to operating instructions, not archived design proposals.

| Page | Route | Instructions |
|---|---|---|
| Main GUI | `/` | [User manual](tutorials/user_manual.en.md) |
| Live GUI | `/live`, `/planning` | [Live reference](gui/gui.md) |
| Replay | `/replay` | [Read-only replay](gui/run_replay.md) |
| Runtime IDE | `/ide` | [Runtime IDE](../system/runtime/runtime_ide.md) |
| Module Management | `/module-management` | [Module lifecycle](../system/modularity.md) |
| Knowledge | `/knowledge` | [Wiki and memory](../system/knowledge/wiki_memory.md) |
| 3DP | `/printer` | [English](tutorials/device_workspace_3dp_usage.en.md) / [한국어](tutorials/device_workspace_3dp_usage.ko.md), [Bambu runtime](../system/hardware/bambulab_x2d_device_bridge_runtime_guideline.md) |
| Vision Camera Bridge | `/device-bridge/vision-utm` | [English](tutorials/device_workspace_vision_camera_bridge_usage.en.md) / [한국어](tutorials/device_workspace_vision_camera_bridge_usage.ko.md), [ROS runtime](../system/hardware/utm_ros_vision_runtime_bridge.md) |
| LeRobot | `/lerobot` | [Robot workspace](../system/hardware/lerobot_robotis_manipulation_runtime_guideline.md), [dataset naming](../system/runtime/lerobot_dataset_policy_naming.md) |
| BO | `/bo` | [BO reference](../system/agents/bo_agent.md) |
| Windows Equipment | `/equipment/windows` | [Windows equipment guide](../system/hardware/windows_pyautogui_equipment_agent_guideline.md) |

## 4. 에이전트별 문서 맵

The [agent index](../system/agents/README.md) owns the complete ten-agent inventory and
figure navigation; the [connection matrix](../system/agents/agent_api_connection_matrix.md)
compares their APIs, effects and evidence.

[ORC](../system/agents/orchestrator_agent.md) · [DSN](../system/agents/design_agent.md) ·
[SPC](../system/agents/specimen_agent.md) · [VIS](../system/agents/vision_agent.md) ·
[MAN](../system/agents/manipulation_agent.md) · [EQP](../system/agents/equipment_agent.md) ·
[ANL](../system/agents/analysis_agent.md) · [KNW](../system/agents/knowledge_agent.md) ·
[BO](../system/agents/bo_agent.md) · [GRD](../system/agents/guardian_agent.md)

Legacy `.txt` guides are not interchangeable with these current references.
Some are still consumed by runtime code; consult their explicit scope before editing.

## 4.1 디바이스 브릿지별 문서 맵

[Seven canonical capability references](../system/device_bridges/README.md) cover Printer
Fleet, Bambu, Prusa, LeRobot, Windows PyAutoGUI, UTM Vision, and simulators.
[PLC Safety](../system/device_bridges/plc_safety_bridge.md) is a supplementary integration.
The [bridge matrix](../system/device_bridges/bridge_api_connection_matrix.md) distinguishes
graph-projected entries from provider, sidecar and tool registrations.

Printer setup belongs in the [3DP tutorial](tutorials/device_workspace_3dp_usage.en.md);
the [pre-ejection cleanup guide](../system/device_bridges/x2d_pre_eject_cleanup.md) explains
the specific tested nozzle sequence. Neither document replaces a live readiness check.

## 5. 폴더별 책임

| Location | Responsibility |
|---|---|
| `app/`, `orchestrator/`, `graphs/` | API, coordination, graph and module runtime |
| `agents/`, `packages/`, `device_bridges/` | Owner modules, composition contracts and device effects |
| `web/` | Shared GUI hosts and browser assets |
| `knowledge/`, `memory/` | Knowledge services; private generated memory is separate from tracked source |
| `runs/`, `artifacts/`, `outputs/`, `user_files/` | Local run evidence and generated/user data, not public documentation |
| `tests/`, `scripts/`, `install/` | Regression checks, operational utilities and installation |
| `docs/`, `image/` | Documentation, evidence, figures and presentation provenance |

## 6. 설명용 문서 폴더

Current owner documentation lives in `runtime/`, `gui/`, `agents/`,
`device_bridges/`, `hardware/` and `knowledge/`. Start-to-finish procedures
live in `tutorials/`; research narrative and dated evidence live in `paper/`.
`standards/` and `templates/` define authoring contracts.
`maintenance/` records audits; `repository/` and `process/` describe contributor workflows.
`superpowers/` contains work plans/designs with explicit lifecycle;
`oldversion/` preserves historical material.

## 7. 이전 개발 자료

Use the [archive index](../system/retained-history/README.md) only for development history.
Older system prompts, UI packages, solver plans and screenshots are not current
instructions. Local-only retired evidence is identified as unavailable to public
readers rather than linked to nonexistent public paths.

## 8. 문서 유지 규칙

- Update the owning reference when its implementation changes, then review
  dependent tutorials, Wiki explanations and figures.
- Keep current instructions separate from dated evidence and proposed work.
- Check file paths, heading anchors, images and external references, not just
  Markdown syntax. A reachable URL can still be the wrong destination.
- Preserve original experiment evidence; do not relabel a test or inspection
  as physical validation.
- Follow [publication rules](../system/knowledge/publication.md) before adding screenshots
  or private run material.

## Migration Status

The manifest's governed subset and the repository-wide document inventory have
different purposes. Files outside the manifest still require review; they must
not be silently described as unused. The 2026-09-14 relocation is documented in
[repository cleanup](../system/maintenance/repository_cleanup.md).

## Limitations and Known Gaps

Historical test results remain dated. External sites may require authentication,
rate-limit automated requests, or retire URLs. Such cases must be distinguished
from a missing local file and from a verified replacement source.
Runtime-consumed guidance needs a separate behavior review; ordinary documentation
cleanup must not silently change experiment decisions.

## Index Verification

The [file-by-file review](../system/maintenance/documentation_review_20260929.md) records
repository-wide coverage, corrections, link checks and preserved runtime inputs.

The page routes and document ownership above were checked against the
`dd0d772` source baseline on 2026-09-29. This is documentation/static inspection,
not a hardware trial. Run the governed-document validator from repository root:

```bash
.venv/bin/python scripts/validate_documentation.py
```

## Related Documents

- [Documentation standard](../system/standards/documentation_standard.md)
- [Paper standard](../system/standards/paper_documentation_standard.md)
- [Document templates](../system/templates/document_types.md)
- [Current code snapshot](../system/runtime/current_code_snapshot.md)
- [Historical governance design](../system/retained-history/superpowers/specs/2026-08-08-documentation-governance-design.md)
