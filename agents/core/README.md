# Core agents

`orchestrator`, `knowledge`, and `guardian` are platform-owned basic agents. They
remain registered by the application bootstrap and are not removable specialist
Agent Packages. Specialist owners continue to live in their peer directories
under `agents/` and are discovered through their `module.py` declarations.

Shared orchestration, knowledge, policy, API, frontend, and storage services stay
in their existing top-level packages. Core implementations use their canonical
`agents.core.*` paths; obsolete flat wrapper modules have been removed.

Knowledge and Guardian retain read-only plan queries and detached proposal
validation. Their optional strict `module.owner_plan` declaration follows the
existing lifecycle:

- The module validator checks it; explicit save/apply persists it.
- A new run pins the module snapshot.
- The matching owner derives only supported inputs and records configured-plan evidence.

This does not change core registration or removability:
`implementation.configuration.activation_supported` remains false. No declaration
schedules a run, changes Guardian's mandatory gates or adds a core owner to
specialist discovery.

Their executable catalogs retain one composite task and one delivery operation,
while source-backed structure describes the real responsibilities inside that
unchanged task. See the [Modularity Reference](../../docs/modularity.md) for the
package, bridge, configuration, and runtime relationships.
