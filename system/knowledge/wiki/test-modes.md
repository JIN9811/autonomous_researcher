---
{"topic_id":"test-modes","owner":"documentation","source_refs":["system/runtime/test_mode.md","system/agents/specimen_agent.md"],"source_revision":{"system/runtime/test_mode.md":"f6e5109e07172362432ee823adf82a580dfdf51186b9e4590ca7a12ca281dbd6","system/agents/specimen_agent.md":"d72dc520dcca1475e03b5ff7dcafa477f2935e1461a903b03ab8813db7dda232"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: test-modes","status":"reviewed"}
---

# Test Modes — Scenarios and Physical Effects

Test scenarios use the normal Orchestrator conversation, Setup updates and execution-approval path. An automatic participant answers instead of the researcher. Test mode does not inherently mean no hardware actuation.

| Mode | Printer path | Other equipment |
|---|---|---|
| Virtual bridge | Existing slicing preparation and virtual printer | Virtual policy; no physical actuation |
| Actual/installed printer | Slicing followed by ejection-only project | Physical by default; inspect saved profiles |
| Physical print | Full print, cooling and autoejection | Physical by default; inspect saved profiles |

Installed-printer mode omits the print body and cooling wait, but ejection commands can still actuate hardware. Mixed profiles retain existing boundaries such as separate transfer confirmation.

## Example requests

- Test mode, virtual bridge.
- Test mode, installed printer.
- Test mode, physical print.

These illustrate requests; reading the Wiki does not send them. An unspecified test mode must not select an arbitrary physical profile.

## Automatic-input limits

The automatic participant provides only requested scenario facts in natural language. It cannot directly dispatch agents or invent physical transfers, readiness or completion evidence. Safety recovery, physical transfer confirmation and owner-setting approvals remain human responsibilities. User intervention, stop and reset obey existing input-control boundaries.

Scenario automation does not replace the LLM with a mock. Controlled-model development tests and validation with the registered model are distinct. Synthetic TEST data must not become real measurement evidence.

[Test-mode reference](../../runtime/test_mode.md), [fabrication workflow](specimen-role.md).
