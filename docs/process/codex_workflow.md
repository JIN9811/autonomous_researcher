# Codex Workflow

Codex-targeted implementation loop:

1. Read relevant guide/config/module files.
2. Plan one bounded modification.
3. Implement the change.
4. Run targeted tests (`tests/unit`, `tests/integration`, replay/fault tests).
5. Inspect logs and emitted events.
6. Repair and re-run until verified.

This repository is organized to keep each module small and independently testable.
