# Core agents

`orchestrator`, `knowledge`, and `guardian` are platform-owned basic agents. They
remain registered by the application bootstrap and are not removable specialist
Agent Packages. Specialist owners continue to live in their peer directories
under `agents/` and are discovered through their `module.py` declarations.

Shared orchestration, knowledge, policy, API, frontend, and storage services stay
in their existing top-level packages. The former flat Python paths under
`agents/` are exact module aliases so existing imports and monkeypatches keep the
same module objects. The existing Orchestration Plan stays unchanged; only the
Knowledge and Guardian Plan contracts remain a deferred design step. This
directory introduces no plan runtime or discovery.
