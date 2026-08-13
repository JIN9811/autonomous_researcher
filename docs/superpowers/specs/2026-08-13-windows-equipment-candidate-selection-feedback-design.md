# Windows Equipment Candidate Selection Feedback Design

## Status

Approved for implementation on 2026-08-13 from the user's request to make
saved-candidate selection visibly reliable without harming existing behavior
or intent.

## Problem

`POST /api/equipment/windows/select` correctly persists the selected Windows
PyAutoGUI candidate, but the browser leaves every saved-candidate card with the
same style and an enabled `Select` button. The separate equipment-profile panel
also renders `bridge=unknown` because the token-safe profile state has no
`connection.status` value even when `connection.selected` is true. Operators
therefore cannot tell that the click succeeded.

## Scope and Invariants

- Preserve all existing API paths, request/response schemas, saved connection
  memory, token handling, candidate aliases, discovery, deletion, testing,
  execution, approvals, and live-effect gates.
- Candidate selection remains non-actuating. It MUST NOT automatically call
  `/health`, `/programs`, `/execute`, or any physical-equipment endpoint.
- Keep the backend as the selection authority. The browser MUST render the
  selected state returned by the API and then refresh the canonical config.
- Do not alter existing user work outside the Windows Equipment selection UI
  and its focused regression tests.

## Browser Behavior

When an operator presses `Select`, the clicked button becomes disabled and
shows `Selecting...` until the request settles. A successful response is valid
only when `ok=true`, `selected=true`, and `selected_candidate` equals the
requested alias. The browser then renders that candidate as selected, disables
its selection button with the label `Selected`, adds accessible current/pressed
state, updates the top Saved Connection card, and refreshes
`/api/equipment/windows/config` without replacing the selection confirmation.

If the API returns HTTP success with an application failure, an identity
mismatch, or a network/HTTP error, the browser keeps the last server-confirmed
selection and writes a clear failure to Current Action and the result log. No
candidate is presented as selected optimistically.

The common equipment-profile panel derives a missing connection status from
the existing token-safe fields: `selected` becomes `selected`, otherwise
`missing`. This changes display only and does not redefine readiness or live
health.

## Visual and Accessibility Contract

- Selected card: explicit `selected` class and `aria-current="true"`.
- Selected button: `Selected`, disabled, primary style, and
  `aria-pressed="true"`.
- Standby button: `Select`, enabled, and `aria-pressed="false"`.
- Busy button: `Selecting...`, disabled for the in-flight request.
- Existing URL, platform, scope, and live-enabled text remains visible.

## Verification

Focused frontend tests must execute the real browser script with controlled
fetch responses and verify success, refresh, failure, and profile-status
behavior. Existing bridge candidate tests, JavaScript syntax validation, the
Windows Equipment browser audit, and a live non-actuating Nextpc selection plus
health/program test remain the completion gates.
