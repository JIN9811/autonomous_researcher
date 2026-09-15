---
{"topic_id":"test-modes","owner":"documentation","source_refs":["docs/runtime/test_mode.md","docs/agents/specimen_agent.md"],"source_revision":{"docs/runtime/test_mode.md":"e326a6446165d580f9ab9c168811cfcb47126aba570706ba55d463f67dbccedb","docs/agents/specimen_agent.md":"c8e58f4b23b7cf500e927ab6dd0a41714e1e542d4d6897327ff2efc703b9c230"},"verified_at":"2026-09-15T00:00:00+00:00","applicability":"Public AX4LAB reference: test-modes","status":"reviewed"}
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
