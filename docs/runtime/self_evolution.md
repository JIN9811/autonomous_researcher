# ATR Self-Evolution Runtime

## Purpose

ATR Self-Evolution is a closed-loop meta-runtime for improving the Autonomous Researcher without directly editing live hardware-control code.

It adapts the package drafts in `docs/ATR_Self_Evolution_Package/` to the current ATR architecture:

```text
closed-loop run trace
  -> trace collector
  -> trace miner / deterministic candidate generator
  -> variant registry
  -> schema + compiler + dry-run gates
  -> human approval
  -> next-run activation
```

Self-evolution targets are intentionally limited to artifacts that can be versioned and rolled back:

- module prompt overrides in `graphs/modules/<module>/module.yaml`
- graph config candidates in `graphs/configs/*.yaml`
- report templates stored as inert runtime variants
- recovery/safety policies stored as inert runtime variants
- tool guidance stored as inert runtime variants
- code patches as diff-only candidates, never auto-applied

## Safety Boundary

Self-evolution never executes printers, robots, UTM, cameras, or Windows bridge macros during candidate evaluation. Candidate evaluation is schema/config only.

Live-affecting activation is blocked while a run is active. Activation requires:

- generated variant body
- source trace lineage
- schema validation
- graph compiler validation for graph candidates
- graph dry-run sequence for graph candidates
- module schema and registered handler validation for prompt candidates
- explicit approval through `/api/evolution/variants/{variant_id}/approve`
- explicit activation through `/api/evolution/variants/{variant_id}/activate`

Graph and module activations are written through the existing version stores:

- `GraphVersionStore` for graph candidates
- `ModuleConfigStore` for prompt/module candidates

Runtime registry state is stored under `memory/evolution/`, which is ignored by Git and can be cleared without modifying source code.

## Package Review Status

The imported draft package `docs/ATR_Self_Evolution_Package/` is directionally appropriate for ATR, but the implementation keeps the first production version deliberately conservative. The repository currently implements the same lifecycle in fewer modules:

```text
TraceCollector + SelfEvolutionService + EvolutionRegistry
  -> task creation
  -> source trace collection
  -> deterministic prompt/graph/report/policy/tool candidate generation
  -> schema/compiler/dry-run gates
  -> approval
  -> versioned next-run activation or rollback marking
```

Not yet split into standalone files from the draft (`trace_miner.py`, `candidate_generator.py`, `evaluator.py`, `constraint_gate.py`, etc.). That split is an internal refactor target, not a blocker for current operation, because the API, gate lifecycle, activation safety boundary, and registry behavior are already implemented.


## Knowledge Evidence Pack Integration

Self-evolution now uses Knowledge Agent evidence packs instead of relying only on trace event counts. Knowledge Agent writes typed evidence to:

```text
runs/<run_id>/knowledge/evolution_evidence_packs.json
memory/knowledge/evolution_evidence_packs.jsonl
```

`SelfEvolutionService` loads matching packs for the selected `target_type` and `target_id`. If a task constraint includes `knowledge_evidence_pack_id`, only that pack is used. Generated guidance includes evidence objective, target rationale, recommended changes, and safety constraints.

This changes the meta-runtime loop to:

```text
run reports/artifacts/metrics
  -> Knowledge typed memory and provenance
  -> failure/success pattern mining
  -> EvolutionEvidencePack
  -> SelfEvolutionService candidate generation
  -> schema/compile/dry-run gates
  -> operator approval
  -> next-run activation
```

Knowledge still cannot activate a variant. It only builds the evidence and task prefill.

Additional Knowledge API endpoints:

- `GET /api/knowledge/evolution-packs?target_type=&target_id=&limit=`
- `GET /api/knowledge/agent-performance?agent_id=&limit=`
- `GET /api/knowledge/failure-patterns?agent_id=&stage=&limit=`
- `GET /api/knowledge/success-patterns?agent_id=&limit=`
- `GET /api/knowledge/evolution-outcomes?target_id=&limit=`
- `POST /api/knowledge/evolution-outcomes`
- `GET /api/knowledge/run-context?agent_id=&run_id=`
- `GET /api/knowledge/bo-context?objective_id=&limit=`
- `GET /api/knowledge/safety-context?stage=&limit=`

Evolution Lab displays a Knowledge Evidence Pack panel and passes the selected pack id into task constraints.

## Replay / Held-Out Evaluation

Self-evolution includes a deterministic replay/eval harness in `self_evolution/evaluator.py`.

The evaluator does not execute hardware, call tools, or call an LLM. It replays source or held-out trace metadata against a candidate variant and appends reviewable gate results:

- `replay_cases_present`
- `replay_schema_validity`
- `replay_contract_completeness`
- `replay_groundedness_to_trace`
- `replay_safety_preservation`
- `replay_no_forbidden_behavior`

`SelfEvolutionService.evaluate_variant_object(...)` stores the summary under:

```text
variant.metrics.replay_eval
```

The summary includes source trace count, held-out trace count, replay trace ids, aggregated event/error/warning/missing-field counts, gate pass count, and replay score.

Evolution Lab displays this as a `Replay / Held-out Evaluation` card in the candidate gate panel and in candidate leaderboard rows. This is an offline safety and regression screen, not causal proof that a variant improves live performance.

When an approved active variant is used in a later run, Knowledge Agent records conservative post-activation attribution as `EvolutionOutcomeRecord` under:

```text
runs/<run_id>/knowledge/evolution_outcomes.json
memory/knowledge/evolution_outcomes.jsonl
```

The record compares the active target with the current run's `AgentPerformanceRecord` signals and exposes rollback/observe/keep-review status through `/api/knowledge/evolution-outcomes` and the Knowledge report.

## Runtime API

Implemented endpoints:

- `GET /evolution-lab`
- `GET /api/evolution/targets`
- `GET /api/evolution/traces?limit=12`
- `GET /api/evolution/tasks`
- `POST /api/evolution/tasks`
- `GET /api/evolution/tasks/{task_id}`
- `POST /api/evolution/tasks/{task_id}/run`
- `GET /api/evolution/tasks/{task_id}/variants`
- `GET /api/evolution/variants?task_id=&target_type=&target_id=`
- `GET /api/evolution/variants/{variant_id}`
- `POST /api/evolution/variants/{variant_id}/validate`
- `POST /api/evolution/variants/{variant_id}/approve`
- `POST /api/evolution/variants/{variant_id}/activate`
- `POST /api/evolution/variants/{variant_id}/rollback`
- `GET /api/evolution/lineage/{target_id}`

All important operations emit Runtime IDE-compatible events such as:

- `evolution.task.created`
- `evolution.task.completed`
- `evolution.task.failed`
- `evolution.variant.validated`
- `evolution.variant.approved`
- `evolution.variant.activated`
- `evolution.variant.rolled_back`

These events flow through the same controller event bus used by Runtime IDE and Live GUI.

## Closed-Loop Integration

The first practical target is prompt evolution for existing graph modules. For example, a `prompt:design` task reads source traces, mines event/error/warning counts, then appends next-run developer guidance to the Design module prompt candidate.

When approved and activated, the candidate writes a versioned `graphs/modules/design/module.yaml` update. `LangGraphRunLoop` already applies module prompt overrides through `ModuleRuntimeContext`, so the next closed-loop run uses the evolved prompt without changing Python agent source.

Graph candidates are also supported but conservative by default. The generated graph candidate adds self-evolution metadata and must pass the existing graph schema, compiler validation, and dry-run gate. Operators can inspect or further edit graph candidates through Runtime IDE before relying on them for live runs.

## Evolution Lab GUI

The main dashboard links to `/evolution-lab`. The page provides:

- target selector
- source run selector
- objective input
- create + run task
- evolution pipeline diagram for trace intake -> mining -> candidate -> gate -> approval -> activation
- candidate leaderboard sorted by score/status with active/unreviewed state highlighting
- visual gate checklist with PASS/FAIL badges
- variant body/diff viewer
- task/variant history for the selected target
- target lineage with active variant and recent candidates
- validate / approve / activate / rollback controls

It is deliberately operational rather than decorative: every button calls `/api/evolution/*` and writes registry state under `memory/evolution/`.

## Next Hardening Steps

- Add Runtime IDE panel integration so variants can be opened directly as graph/module drafts.
- Add Guardian review as a formal gate result for safety-critical target types.
- Expand the current replay/eval harness with domain-specific held-out cases and causal before/after benchmarks.
- Add richer trace mining for repeated missing fields, latency bottlenecks, and failed tool calls.
- Add statistical trend analysis over accumulated `EvolutionOutcomeRecord` rows before promoting keep/rollback decisions.
- Add report-template rendering preview for report variants.
