<!-- atr-doc
doc_type: plan
subtype: implementation
status: archived
authority: execution
execution_status: completed
audience: [developer, maintainer]
scope: [manipulation_agent, lerobot_bridge, agent_packages, runtime_ide]
summary: Package the existing Manipulation owner and shared LeRobot bridge while preserving control, telemetry and evidence boundaries.
governing_design: docs/oldversion/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs: [docs/agents/manipulation_agent.md, docs/device_bridges/lerobot_bridge.md, docs/runtime/runtime_ide.md]
supersedes: []
-->

> Archived development history (2026-09-14). Not the current implementation or acceptance contract. See the [archive index](../../README.md) for current references.


# Manipulation Agent Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the existing Manipulation owner and LeRobot bridge with their IDE, presentation and storage contracts without changing robot workflows.

**Architecture:** Reuse installed AgentModule, BridgeModule, Agent Package and the existing execution-graph host. Keep the existing task workflow as one composite owner operation; expose its actual LLM, software, device, validation and evidence relationships as source-bound CODE details. Keep aliases and all existing API, tool, configuration and artifact paths.

**Tech Stack:** Python, existing LangGraph/AgentRegistry/ToolRegistry, YAML, FastAPI, vanilla JavaScript, pytest and Node tests.

**Spec:** `docs/oldversion/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md`; `docs/oldversion/superpowers/specs/2026-09-13-executable-agent-ide-contract-design.md`.

## Global Constraints

- Work in the user's current checkout. Preserve prior uncommitted Vision and layer-classification changes. Do not commit, tag, push or restart the operating server in this task.
- Preserve original task ordering, arguments, results, tool IDs, archive wrapper, retry/once guards, stop, teleop confirmation, rollout completion, ActiveCam, and UTM clear handoffs.
- High is agent-local LLM reasoning; Middle is API/internal software and composite workflows; Low is actual device/bridge execution. Guardian/Safety and Knowledge/Evidence are cross-cutting responsibilities.
- Do not split existing composite handlers to fill areas. CODE relationships are not executable commands.
- Agent Package is a composition contract, not a device. LeRobot has one bridge identity with internal components; Vision shares it without a second bridge instance.
- Canonical bridge code belongs under `device_bridges/lerobot/`; legacy imports retain module identity, including monkeypatch behavior.
- No hardware calls, model lifecycle changes, dataset/calibration modifications or user configuration writes. Guard all validation before bootstrap; use temporary storage. Virtual-device real-model checks use only ATR's registered provider path.
- Public docs are English except the existing Korean design document. Keep runtime evidence and local configuration out of published package contents.

## Task 1: Installed Manipulation owner and source-bound execution graph

**Files:** `agents/manipulation/{__init__,agent,decision,module,execution,structure,presentation}.py`, compatibility files `agents/manipulation_agent.py` and `agents/manipulation_decision.py`, `graphs/modules/manipulation/module.yaml`, existing bootstrap/catalog/report host integration, `tests/unit/test_manipulation_module_contract.py`, `tests/integration/test_agent_execution_graph_api.py`.

**Interfaces:** Export `MODULE` / `MANIPULATION_MODULE: AgentModule`, factory `ManipulationAgent`; execution functions `manipulation_execution_catalog(agent)`, `execute_manipulation_graph(agent, state, ctx, *, graph=None, emit=None, invocation=None)`, and `manipulation_implementation_structure()`. Export `project_manipulation_report(metadata, agent_payload)` and `REPORT_PROFILE`, preserving the current report fields and precedence. Task 2 binds bridge ID `lerobot`; Task 3 adds its declared frontend asset.

- [x] Record failing consumer tests for discovery, report isolation, compatibility identity and executable metadata before implementing. For example:

```python
def test_discovered_manipulation_owner():
    from agents.module_discovery import discover_agent_modules
    owners = {m.module_id: m for m in discover_agent_modules()}
    assert 'manipulation' in owners
    assert owners['manipulation'].agent_name == 'manipulation_agent'
```

- [x] Move the existing agent and decision implementation without changing task logic. Rename the current decorated body to an undecorated `_run_task`; keep `@archive_agent_run` only on public `run`. The public wrapper executes the shared owner graph and returns its original `AgentResult`. Keep all clear-cycle dispatch and repeated-start checks inside `_run_task` in the existing order.

```python
async def task(state, ctx, scope, config):
    if scope.get('task_started'):
        raise ExecutionGraphError('Manipulation task cannot repeat within an invocation')
    scope['task_started'] = True
    return OperationResult('next', {'task_result': await agent._run_task(state, ctx)})
```

- [x] Publish allowlisted composite `manipulation.task` (Middle, contains LLM) and `manipulation.deliver` (Middle, requires task_result, produces agent_result); delivery requires a real AgentResult. Every terminal requires agent_result. Reject duplicate task entry before a second owner/device call. Do not invent intermediate execution stages. Keep source-bound CODE details for both decisions, preflight/recheck, rollout/replay/stop, clear-cycle branch and report/archive relationships. Use actual symbols from the current code.
- [x] Reuse discovery and graph catalog loading as existing Vision does. Remove only the duplicate explicit Manipulation bootstrap registration. Preserve legacy stage routing and owner name. The report extractor moves the current manipulation branch out of the generic host without changing metadata/payload precedence.
- [x] Verify behavior, not just metadata: default graph versus the original body on equivalent fresh state under denied hardware; preflight, blocked, running, completed recovery, clear dispatch and duplicate-start cases; report API; invalid graphs rejected before effects; pinned definitions/traces. Run focused existing manipulation/clear tests and report any baseline failures separately.

## Task 2: LeRobot bridge and Manipulation Agent Package

**Files:** `device_bridges/lerobot/{__init__,bridge,tools,module}.py`, `requirements.txt`, `README.md`; legacy `device_bridges/lerobot_bridge.py`, `mcp_tools/lerobot_tools.py`; `packages/agents/manipulation/{package.yaml,README.md}`; discovery/API integration only as needed; `tests/unit/test_lerobot_module_contract.py`, package/API/bridge tests.

**Interfaces:** Canonical `LeRobotBridge`, `LeRobotBridgeConfig`, and `register_lerobot_tools` keep all signatures. Export bridge `MODULE: BridgeModule`, ID `lerobot`, version `1.0.0`, `runtime_bridge_ids=['lerobot_bridge']`. Agent Package ID `manipulation`, version `1.0.0`, owner `manipulation@1.0.0`, bridge `lerobot@1.0.0`, handler `agent.manipulation_agent`. Existing Vision dependencies should reference the same installed bridge where the schema supports it, not instantiate one.

- [x] Add failing package-consumer tests for installed LeRobot identity, exact legacy aliases, shared bridge deduplication, existing script path resolution and inactive import/export.
- [x] Relocate the bridge as a coherent implementation; preserve runtime globals. Change only repository-relative `__file__` anchors for the extra folder level. Move tool registration with an exact module alias. Keep schemas, shared helpers, configuration, workspace APIs/assets and vendor scripts at current paths and declare those owned references instead of duplicating them.

```python
# Legacy compatibility files preserve both imports and monkeypatch globals.
import sys
from device_bridges.lerobot import bridge as _implementation
sys.modules[__name__] = _implementation
```

- [x] Describe real existing capabilities, workspace/API, requirements, configuration and producer storage. Internal components may show rollout/replay/teleop/recording/ActiveCam and their actual implementation paths; they are not independent packages or a fabricated agent pipeline. Package inspection must not connect devices.
- [x] Register the local Agent Package and reuse the common catalog/IDE Package Manager/Device Bridges projection. Add the same `lerobot@1.0.0` bridge reference to the installed Vision Agent Package and its dependency metadata: Vision already uses ActiveCam and rollout stop. Camera/Vision's shared-dependency metadata points to this canonical source. This must produce package-to-shared-bridge relations without copying or registering a second runtime instance. Preserve package removal semantics, archived files, runtime ID deduplication and current graph draft.
- [x] Run existing LeRobot transport-free unit cases and package/API tests. Confirm managed replay/background training command paths still resolve to repository scripts; calibration, task parameters and session paths unchanged; shared Vision dependency has one provider. Never invoke live transport or training.

## Task 3: Owner frontend, docs and integration evidence

**Files:** `agents/manipulation/frontend/live_report.js`, owner module descriptor, `graphs/modules/manipulation/ui.yaml`, existing shared `web/static/planning.js` host, pyproject assets, `scripts/render_module_control_views.py`, agent/bridge references and indexes, package design update, focused Node/frontend/API tests.

**Interfaces:** Register `AX4LABManipulationUI.createFrontend` using the existing module host and asset URL `/module-assets/manipulation/live_report.js`. Host supplies current shared render helpers and lifecycle; module owns its report/card composition. Preserve polling, joint/gripper telemetry, stream buffer, event and verification lifecycle in their current shared services.

- [x] Add failing tests that render representative running/completed/blocked reports through the module factory and ensure absent/deactivated modules do not contribute a current live card. Assert report/telemetry values, not just source strings.
- [x] Extract only the coherent Manipulation report/card composition into the owner frontend, keeping existing DOM IDs, handlers and shared telemetry helpers. Do not change sample frequency or viewer lifecycle. Declare existing LeRobot workspace routes/assets in the bridge descriptor instead of building another workspace.
- [x] Generate `docs/agents/assets/figures/manipulation_control_areas.svg` from the same source-bound graph using the light document theme. Update Manipulation/LeRobot references, agent/bridge indexes and API matrix, Runtime IDE scope, and modularization design with actual implemented boundaries; retain existing physical evidence provenance.
- [x] Run focused Python/Node/API tests, documentation and publication checks, guarded original-mode regression (virtual, real-printer, physical-print profiles with transport denied), and a registered-API full virtual-device cycle through downstream analysis/knowledge/BO/next Design. Keep physical calls and denied effects in the evidence record. A model failure is reported, not hidden behind deterministic substitution.
- [x] Inspect guarded Runtime IDE at 1920×1080: owner graph and CODE Inspector, Package → LeRobot relation, shared dependency, bridge internal components, existing canvas background/legend, and live report. Close only assistant-created tabs/temporary servers.
- [x] Record commands/results and limitations here. Leave working changes uncommitted for the user.

## Verification Record

Tasks 1 and 2 passed their focused checks and independent reviews. Task 3 owner
frontend, asset admission and documentation are implemented. All 40 focused Node
checks, 36 Python/API checks and 34 documentation-validator tests passed; all nine
changed governed documents passed metadata, links and source contracts. Publication
validation passed against 124 changed/new files in an isolated temporary index,
with no failures and the user's real index unchanged. Working changes remain
uncommitted.

The final source-sync check identified a stale Vision figure link after the shared
LeRobot source relocation. Regeneration through the same light document renderer
updated that link; Vision and Manipulation SVGs both match current renderer output.

The parent integration run passed 49 guarded original-mode/hybrid cases in
245.97 seconds (81 existing warnings). The registered API retry completed the
virtual-device cycle through Design → Specimen → Vision → Manipulation → Vision
→ Equipment → Manipulation → Vision → Analysis → Knowledge → BO → Guardian →
next Design. All 34/34 registered-model calls across ten owners succeeded using
`gpt-5.5`; recorded cycle duration was 392.336 seconds (393.16 seconds pytest).
Physical calls: 0; denied effects: []. This used synthetic devices/data, and FEM
was not executed. A verification-only 90-second Vision timeout did not change
the production default or freshness windows. The first API attempt stopped at
Vision after eight completed calls and is not a pass; its evidence is retained.

Guarded 1920×1080 Runtime IDE inspection confirmed two Middle operations,
17 source-bound CODE details, High LLM and Low LeRobot relationships, Inspector,
package → one shared LeRobot → ten provider components, and the existing canvas
background/legend. Fresh Live GUI inspection confirmed all eight Manipulation
cards, the repository 3D model, Gripper selector binding and value retention after
Vision → Manipulation navigation, with no console errors or warnings. Idle UI
does not establish populated live telemetry or hardware motion; controlled
report and shared telemetry consumers provide software-only value checks.

No new hardware proof is claimed. Existing physical evidence, calibration,
policies, datasets, retry/once gates, ActiveCam, teleop, stop and UTM-clear paths
remain unchanged. Local diagnostic artifacts stay outside published package
contents; detailed command records are retained in the task workspace.
