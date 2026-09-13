# Core agents

`orchestrator`, `knowledge`, and `guardian` are platform-owned basic agents. They
remain registered by the application bootstrap and are not removable specialist
Agent Packages. Specialist owners continue to live in their peer directories
under `agents/` and are discovered through their `module.py` declarations.

Shared orchestration, knowledge, policy, API, frontend, and storage services stay
in their existing top-level packages. Core implementations use their canonical
`agents.core.*` paths; obsolete flat wrapper modules have been removed.

Knowledge and Guardian retain read-only plan queries and detached proposal
validation. They also accept an optional strict `module.owner_plan` declaration
through the existing module validator and explicit save/apply path. A new run
pins that module snapshot; the matching owner derives only its supported inputs
and records configured-plan evidence. This is separate from core module
registration/removability: `implementation.configuration.activation_supported`
remains false, and no declaration schedules a run, changes Guardian's mandatory
gates, or adds a core owner to specialist discovery.

Their executable catalogs retain one composite task and one delivery operation,
while source-backed structure describes the real responsibilities inside that
unchanged task. See the [Modularity Reference](../../docs/modularity.md) for the
package, bridge, configuration, and runtime relationships.
