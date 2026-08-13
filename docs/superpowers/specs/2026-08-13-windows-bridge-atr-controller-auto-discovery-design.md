# Windows Bridge ATR Controller Auto-Discovery Design

## Goal

Every newly installed or portable Windows PyAutoGUI Bridge must locate the Linux ATR controller without embedding a workstation-specific IP address in the release. After discovery, the bridge must persist the verified controller URL and use it for `/skills` and other controller-backed APIs across restarts.

This change fixes the current failure mode in which the Windows bridge defaults to its own `http://127.0.0.1:7860` and returns `EQUIPMENT_SKILL_REGISTRY_UNREACHABLE` even though ATR is running on another host.

## Scope

The behavior applies to both Windows distribution forms:

- Installed package launched through `INSTALL_WINDOWS_BRIDGE.cmd`, shortcuts, or the logon task.
- Portable package launched through `START_EQUIPMENT_BRIDGE.cmd`.

The bridge server, launch scripts, installer, environment example, operator documentation, packaging contract tests, and bridge server tests are in scope. UTM locator calibration and physical UTM execution are not part of this change.

## Controller Resolution Order

The bridge resolves the ATR controller in this strict order:

1. A non-empty `WINDOWS_PYAUTOGUI_ATR_API_URL` environment override.
2. A previously verified controller record stored under the active bridge data root.
3. A verified source-address candidate learned from an authenticated bridge request.
4. A bounded private-network discovery scan.
5. The local fallback `http://127.0.0.1:7860`, but only when it passes the same ATR identity check.

A higher-priority valid setting is never replaced by a lower-priority candidate. An invalid environment override produces an explicit diagnostic and is not silently replaced.

## Persisted Controller Record

The bridge stores non-secret discovery state in:

`<WINDOWS_PYAUTOGUI_DATA_ROOT>/controller_connection.json`

The record uses schema `atr.windows_controller_connection.v1` and contains:

- Canonical controller base URL.
- Discovery source: `environment`, `saved`, `authenticated_peer`, or `subnet_scan`.
- Verification timestamp.
- Last successful verification timestamp.
- Last failure code and message, when applicable.

The record contains no bridge token, API key, cookie, authorization header, or user credential. Writes are atomic through a temporary sibling file followed by replacement. Malformed saved data is ignored with a diagnostic rather than preventing bridge startup.

## ATR Identity Verification

A candidate is accepted only when all of the following hold:

- Scheme is `http` or `https`.
- Host is a loopback or private IPv4 address unless it came from the explicit environment override.
- TCP/HTTP verification completes within a short bounded timeout.
- `GET /api/equipment/skills` returns HTTP 200.
- The response is JSON with `ok=true` and a list-valued `skills` field.
- Redirects do not leave the candidate host.

Discovery never accepts a host based only on an open port. Failed candidates return normalized diagnostics without exposing response bodies or secrets.

## Authenticated Peer Learning

Once a bridge request has passed token authentication, its remote IPv4 address becomes a controller candidate. Loopback and the Windows host's own addresses are ignored unless the candidate is explicitly configured. The bridge probes `http://<remote-ip>:7860` using the ATR identity verification contract.

Peer learning runs only for authenticated requests and never delays the original bridge response beyond its discovery timeout. A successful candidate is persisted and becomes available to `/skills`. An unauthenticated request can never alter controller state.

This path is the normal zero-configuration flow: ATR contacts `/health` or `/programs`, the Windows bridge observes the Linux source IP, verifies its ATR API, and remembers it.

## Bounded Subnet Discovery

If no explicit, saved, or authenticated-peer controller is valid, the bridge may scan private IPv4 networks attached to active Windows interfaces.

The scan is constrained as follows:

- Probe port `7860` only.
- Scan at most `/24` worth of addresses per eligible interface.
- Ignore loopback, link-local, multicast, broadcast, and the Windows host's own addresses.
- Use bounded concurrency, per-host timeouts, and an overall deadline.
- Apply the complete ATR identity verification contract to every open candidate.
- Cache negative discovery briefly to prevent a scan on every `/skills` request.

If exactly one ATR controller is found, it is selected and persisted. If multiple verified controllers are found, the bridge does not choose by probe timing; it reports the candidates in the operator console and requires selection. If none are found, the bridge retains a clear unreachable state and exposes manual configuration guidance.

## API And Operator Console

The bridge health response includes a redacted controller summary:

- Resolution status.
- Selected controller base URL.
- Discovery source.
- Last verification time.
- Failure code when unresolved.

The operator console exposes:

- Current controller URL and source.
- `Discover ATR` action.
- Candidate list when more than one controller is verified.
- Manual URL input and verification action.
- Clear diagnostic text when discovery fails.

Manual selection uses the same identity verification and persistence path as automatic discovery. `/skills` resolves the controller through this shared component instead of reading a module-level localhost default.

## Installation And Upgrade Behavior

Package installation and portable bootstrap pass the active data root to the bridge as they do today. No package-specific IP is generated during build.

On upgrade:

- Existing bridge tokens, programs, locators, recordings, and artifacts remain untouched.
- An existing valid `controller_connection.json` remains authoritative below an explicit environment override.
- Old installations without the record enter automatic discovery on first controller-backed request.
- Existing `WINDOWS_PYAUTOGUI_ATR_API_URL` deployments retain their current behavior and precedence.

The installer may accept an optional controller URL for managed deployments, but the one-click default remains zero-configuration discovery.

## Failure And Safety Rules

- Bridge startup and local PyAutoGUI programs remain available when no ATR controller is found.
- `/skills` returns `EQUIPMENT_SKILL_REGISTRY_UNREACHABLE` with discovery diagnostics when resolution fails.
- Discovery performs only HTTP identity reads and never calls equipment execution endpoints.
- Unauthenticated peers cannot trigger persistence.
- Multiple verified controllers require an explicit choice.
- Saved candidates are reverified before use after a bounded freshness period.
- An environment override is never rewritten or persisted as if it were automatically discovered.

## Verification

Automated tests must prove:

- Resolution precedence is environment, saved record, authenticated peer, subnet discovery, then verified local fallback.
- The current unconfigured remote-controller case fails before the implementation and passes afterward.
- Authenticated peer learning accepts a valid ATR response and rejects unauthenticated, public, self, malformed, redirecting, and non-ATR candidates.
- The persisted record is atomic, contains no secret material, survives restart, and tolerates corruption.
- Subnet discovery is bounded, deduplicated, cached, and does not select arbitrarily when multiple ATR instances respond.
- `/skills` uses the resolved controller and the health/UI surfaces expose only redacted status.
- Installed and portable release builders include all required scripts, defaults, documentation, and tests.
- Existing bridge authentication, program execution, screenshots, locators, recordings, and request logging remain passing.

Windows-native acceptance must verify the final package against a Linux ATR host on a different private IP. Success requires `/health`, `/programs`, `/skills`, screenshot capture, and safe `program1` execution through the ATR proxy without manually setting `WINDOWS_PYAUTOGUI_ATR_API_URL`.
