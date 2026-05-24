# Logging

The runtime writes:
- `structured.jsonl`: machine-readable events
- `summary.log`: human-readable run summary

Each event includes `run_id`, `experiment_id`, `layer`, `event_type`, and payload.

Live GUI planning/tool events:
- Planning chat messages are also emitted as structured events by `MainController`.
- `printer.prepare` can emit supplemental per-step tool events while Specimen Making Agent is running.
- These events are UI/logging progress signals; the authoritative stage result remains `AgentResult.data["specimen_result"]`.
- Printer runtime events must never include PrusaLink secrets, API keys, passwords, or auth headers.
