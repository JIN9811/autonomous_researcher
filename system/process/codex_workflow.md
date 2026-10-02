# Codex Workflow

Codex-targeted implementation loop:

1. Read relevant guide/config/module files.
2. Plan one bounded modification.
3. Implement the change.
4. Run targeted non-hardware tests (`tests/unit`, `tests/integration`, replay/fault fixtures); device execution requires separate authorization.
5. Inspect logs and emitted events.
6. Repair and re-run until verified.

Module ownership follows the [modularity contracts](../modularity.md); this is
not a claim that every implementation file is small or isolated. Preserve
unrelated work and follow [contribution checks](../../docs/project/CONTRIBUTING.md) before
integration. A documentation review does not authorize an operational restart.
