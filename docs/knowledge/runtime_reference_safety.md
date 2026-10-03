# Runtime Wiki reference safety audit — 2026-09-18

Scope: all 23 public AX4LAB Wiki pages and the actual LLM decision entrypoints of
ORC, DSN, SPC, VIS, MAN, EQP, ANL, KNW, BO and GRD. This audit does not establish
that a Wiki page caused the observed Vision rejection. The recorded rejection
concerned pixel location; citation use was unknown.

## Findings and implementation

- General experiment-goal searches could attach another owner's documentation
  to an operational decision. Execution retrieval now filters to the exact owner
  role *before* retrieval/delivery receipts are recorded.
- Whole-page prefixes could introduce example numbers, default LHS budgets,
  observation timeouts, objective intervals, workflows or recovery paths.
  Operational requests receive only an explicitly reviewed `Runtime decision
  reference` section, bounded to 1,200 characters. Other article content is not
  attached. Missing/stale/oversize summaries produce no reference, not a new gate.
- Runtime reference envelopes and system prompts state that documentation is
  neither present-run evidence nor authority to add/remove acceptance conditions,
  thresholds, approval, motion or replay. Existing code-owned safety and evidence
  checks are unchanged. Model judgment remains fallible; these controls reduce
  reference contamination, not guarantee model correctness.
- User-facing Wiki questions and browsing retain full explanatory retrieval.
  Operational Wiki references do not implicitly include private memory. Normal
  consent/scope checks for explanatory memory access remain unchanged.
- Delivery receipts describe the actual projected excerpt. Retrieved/delivered
  does not imply used; missing citations remain unknown.

## Page-by-page disposition

| Page | Risk considered / disposition |
|---|---|
| agent-contracts | Cross-owner success rules; explanatory only |
| analysis-role | Objective/mass/coverage requirements; only active-contract summary delivered |
| artifacts | Preview limits mistaken for measurement counts; explanatory only |
| bo-role | Fixed LHS default mistaken for current budget; removed count, runtime summary only |
| bo-visualization | Plot/acquisition descriptions mistaken for settings or observations; explanatory only |
| closed-loop | Diagram sequence mistaken for current graph; explanatory only |
| control-levels | Architecture examples mistaken for executable stages; explanatory only |
| design-role | Example coordinates mistaken for requested coordinates; excluded from runtime excerpt |
| equipment-role | Generic Flow/recovery recipe mistaken for executable work; runtime summary only |
| experimental-setup | Example conversation mistaken for user intent/approval; explanatory only |
| guardian-role | Past faults or unused transport diagnostics mistaken for current blockers; runtime summary only |
| knowledge-agent | Store descriptions/retired workflows mistaken for active work; explanatory only |
| knowledge-role | Historical/literature evidence mistaken for current observations; runtime summary only |
| manipulation-role | Other-phase home/replay steps imported into current task; runtime summary only |
| measurement-metrics | Example strain interval mistaken for current objective; removed numeric example |
| orchestrator-role | Greeting/planning sequence mistaken for active-loop instructions; runtime summary only |
| packages-and-plans | Import/configuration mistaken for execution approval; explanatory only |
| platform-overview | Capabilities mistaken for readiness; explanatory only; usage boundary clarified |
| recovery | Historical/one-off recovery recipe mistaken for current permission; explanatory only |
| specimen-role | Another printer mode's skip/execute policy imported; runtime summary only |
| test-modes | Example request mistaken for selected physical profile; explanatory only |
| vision-role | Timeout/other-phase checks imported into inspection; removed timeout numbers, runtime summary only |
| workspaces | UI/manual actions mistaken for automatic task success; explanatory only |

Source revisions for Guardian, both Knowledge pages and the platform overview
were rechecked against changed source content (transport diagnostic classification,
retired Evolution responsibilities and the documentation index update). Source
hashes were refreshed only after that review; stale-source exclusion remains on.

## Deployment and regression checks

The execution-reference adapter keeps the established delivery function's call
signature. It scopes and projects a read-only service response before invoking
existing receipt handling. This permits lazy-loaded owner modules to coexist
with an older loaded delivery helper without passing a new unsupported keyword.

Tests cover all ten actual decision entrypoints, exact owner scoping, omission of
general-page instructions and numeric examples, missing/oversize references,
unchanged explanatory Wiki access, delivery/use records and legacy-call
compatibility. Visual review retains rejection for stale/cross-run evidence,
invalid coordinates and real visual disagreement. Never replace a running
decision's frozen context with a newly reviewed pack.
