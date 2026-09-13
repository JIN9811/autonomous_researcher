<!-- atr-doc
doc_type: plan
subtype: implementation
status: active
authority: proposal
audience: [developer, maintainer, reviewer]
scope: [core_agents, ownership, import_compatibility, runtime_ide]
summary: Group platform-owned agents under core roots without changing routing, safety, knowledge scope or storage.
plan_status: completed
execution_status: completed
governing_design: docs/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
related_docs:
  - docs/superpowers/specs/2026-09-13-package-agent-bridge-modularization-design.md
  - docs/agents/orchestrator_agent.md
  - docs/agents/knowledge_agent.md
  - docs/agents/guardian_agent.md
supersedes: []
-->

# Core Agent Roots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Work in the user's current checkout. The parent publishes the verified BO and core-root changes under the user's BO modularization tag request.

**Goal:** Put ORC, KNW and GRD owned Python code under explicit core-agent roots while preserving the current program and specialist packages.

**Architecture:** Mechanically relocate owner modules, retaining exact legacy module aliases and existing core registration. Keep shared `orchestrator/`, `knowledge/`, services, APIs and frontend host in place. Update source-backed IDE declarations and current reference links to the canonical files; do not introduce new runtime paths.

**Tech Stack:** Existing Python agents, LangGraph registries, YAML source declarations, pytest and common JavaScript IDE renderer.

**Spec:** [Approved core-agent boundary and migration sequence](../specs/2026-09-13-package-agent-bridge-modularization-design.md#기본-에이전트와-실험별-플랜--2026-09-14-합의).

## Status at a Glance

| At a glance | Details |
|---|---|
| Status | Completed; scoped and final review approved |
| Starting code | Existing working tree after BO package implementation; Git HEAD `ec955d9` |
| Canonical roots | `agents/core/orchestrator/`, `agents/core/knowledge/`, `agents/core/guardian/` |
| Scope | Folder/import/source-reference migration only |
| Plans | Knowledge/Guardian Plan execution remains outside this change |
| Effects | No hardware, native FEM, model lifecycle or server restart; publication authorized after verification |

## Global Constraints

- Preserve all pre-existing BO work in the current checkout. Implementers do not stage, commit, tag, push, reset or create a worktree; the parent publishes BO plus this task after verification, as requested by the user.
- Preserve public imports, signatures, exact module/class identity, monkeypatch behavior, registration IDs, tool IDs, API URLs, execution graphs, call order, result semantics, archive count and storage roots.
- ORC, KNW and GRD remain platform basic agents, not removable specialist Agent Packages. Do not add `MODULE` declarations or packages for them and do not change discovery or activation semantics.
- No Knowledge/Guardian Plan runtime implementation, new scheduler/store/transport, safety relaxation, private knowledge scope expansion, provider fallback change or prompt rewrite.
- Keep shared `orchestrator/`, `knowledge/`, frontend and API services in place. No empty cosmetic frontend folders or duplicated logic.
- Retain five-area IDE styling and source-backed graph semantics: actual LLM is High, software/API is Middle, physical actions Low; retain `LLM` and `LLM call` labels.
- No hardware calls, native solver execution, production server restart, actual provider/model lifecycle or credential changes. Use guarded fixture routes and clearly label controlled model responses.
- Current reference docs are English; retain documentation locations and historical evidence. Do not claim new physical or real-provider validation.

### Task 1: Relocate core-owned modules with exact compatibility and source references

**Files:** Create `agents/core/__init__.py`, `agents/core/README.md`, package initializers and canonical modules from the mapping below; replace old modules with exact aliases. Update `app/bootstrap.py` canonical imports, relevant source declarations in `graphs/modules/{orchestrator,knowledge,guardian}/module.yaml`, canonical ORC structure references, and source renderer imports. Update active ORC/KNW/GRD references, agent index/API matrix, Runtime IDE reference, modularization spec and this plan. Create `tests/unit/test_core_agent_roots.py`; add narrow source/registry/API regression assertions to existing tests where necessary. Do not rewrite archived designs or historical evidence.

| Existing module under `agents/` | Canonical module under `agents/core/` |
|---|---|
| `orchestrator_agent.py` | `orchestrator/agent.py` |
| `orchestrator_decision.py` | `orchestrator/decision.py` |
| `orchestrator_execution.py` | `orchestrator/execution.py` |
| `orchestrator_structure.py` | `orchestrator/structure.py` |
| `orchestrator_capabilities.py` | `orchestrator/capabilities.py` |
| `knowledge_agent.py` | `knowledge/agent.py` |
| `knowledge_decision.py` | `knowledge/decision.py` |
| `knowledge_context.py` | `knowledge/context.py` |
| `source_curation.py` | `knowledge/source_curation.py` |
| `guardian_agent.py` | `guardian/agent.py` |

**Interfaces:** Consume unchanged AgentContext/AgentResult, core bootstrap registration, OwnerCatalog, existing knowledge service and guardian gates. Produce the same Python objects via both legacy and canonical imports. Source navigation targets real implementation modules; core lifecycle remains in existing bootstrap.

- [x] Run a software-only baseline from existing ORC decision/capability, KNW decision/agent/delivery, GRD decision/gate and execution-catalog tests. Keep outputs in this plan's ignored verification workspace. Inspect fixture effects before invoking tests.
- [x] Write RED compatibility tests before creating the new roots. Parameterize every mapping, import order and shared mutable globals. Include this identity contract:

  ```python
  import importlib
  old = importlib.import_module('agents.orchestrator_agent')
  new = importlib.import_module('agents.core.orchestrator.agent')
  assert old is new
  assert old.OrchestratorAgent is new.OrchestratorAgent
  ```

  Cover default OwnerCatalog graph root, Knowledge ontology/project-root resolution, unchanged class names/registry IDs and absence from specialist package discovery. Use temporary state paths for writes, not user memory.
- [x] Run `.venv/bin/pytest tests/unit/test_core_agent_roots.py -q` and record expected missing `agents.core` failures.
- [x] Move implementation bodies using `apply_patch`, changing only canonical imports, source path strings and depth-sensitive repository roots. Preserve legacy paths with exact aliases:

  ```python
  import sys
  from agents.core.orchestrator import agent as _implementation
  sys.modules[__name__] = _implementation
  ```

  Both Knowledge `Path(__file__)` roots and ORC capability defaults must still resolve to repository root: nested canonical modules use `Path(__file__).resolve().parents[3]`. Do not change explicit user-supplied path precedence.
- [x] Update source-reference contracts without altering graph node/edge/handler/config values. Legacy imports inside unrelated specialist consumers remain valid and need not be churned. If a test intentionally inspects implementation source, point it at the canonical source while keeping behavioral assertions.
- [x] Run new identity/path tests and the same baseline suites. Check source symbols through existing execution graph/API tests, not fabricated parallel routes. Parent independently runs guarded full virtual next-Design route and non-actuating printer-profile admission checks.
- [x] Update the three current agent docs, index/matrix and Runtime IDE reference with the core-root mapping; update current source links that otherwise land on an alias. Keep existing figures/layout except deterministic source-reference regeneration if required. Add a concise `agents/core/README.md` explaining basic versus specialist ownership, shared services, aliases and deferred plan contracts.
- [x] Validate modified governed documents and links, `git diff --check`, publication boundary on an isolated index, and exact substantive diff from starting tree. Obtain scoped and final review; retain evidence and hand off uncommitted work to the parent for the authorized commit, BO modularization tag and push.

## Verification Record

Commands, RED/GREEN outputs and review status are recorded in the ignored task workspace `.superpowers/sdd/2026-09-14-core-agent-roots/`. This is a path migration, not new physical or model-quality evidence.

The final focused regression suite passed 212 cases; cold import-order and root
contracts passed 15 cases, and source curation passed 22 cases. The existing five
guarded route scenarios passed before and after migration (138.15 s and 136.83 s).
The full virtual case retained the exact stage sequence, ten-owner loop archives,
Knowledge/BO/Guardian handoffs and next-Design coordinates, with zero physical
calls or denied effects. Printer profiles were checked only through their guarded
preparation boundaries; model responses were controlled fixtures.

Scoped governed-document validation and the 85-file publication scan passed.
Both reviews approved publication without Critical or Important findings.
Duplicate source-test parametrizations, a permissive Guardian detail assertion
and inherited warnings remain non-blocking follow-ups. Unrelated stale Wiki
pages and pre-existing repository-wide documentation errors were not changed.
