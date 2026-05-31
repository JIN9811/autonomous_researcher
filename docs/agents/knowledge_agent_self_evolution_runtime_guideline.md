# Knowledge Agent Self-Evolution Runtime Guideline

## Purpose

Knowledge Agent is the research-memory and self-evolution evidence owner for the ATR closed loop. It is not only a RAG summary node.

Runtime role:

```text
Knowledge Agent = Research Memory + Failure/Success Pattern Memory + Agent Performance Ledger + Self-Evolution Evidence Pack Builder
```

Knowledge recommends what should be evolved. It does not activate variants. `SelfEvolutionService`, Guardian gates, and the operator keep ownership of candidate lifecycle, approval, and next-run activation.

## Runtime Flow

The active module graph is `graphs/modules/knowledge/module.yaml` and uses this internal flow:

```text
01_collect_run_artifacts
02_normalize_provenance
03_ingest_agent_reports
04_write_experiment_knowledge_record
05_update_failure_patterns
06_update_success_patterns
07_update_agent_performance_ledger
08_build_bo_context
09_rank_self_evolution_targets
10_build_evolution_evidence_packs
11_emit_knowledge_report
12_emit_evolution_lab_prefill
```

The Python handler is `agents/knowledge_agent.py`.

## Typed Memory Records

Schemas live in `knowledge/schemas.py`.

Important records:

- `MemoryRecord`: legacy in-memory compatibility record used by `ExperimentDB`.
- `ExperimentKnowledgeRecord`: run/experiment memory with parameters, metrics, quality, artifact refs, and provenance.
- `AgentPerformanceRecord`: per-agent ledger with missing fields, warnings, retry count, artifact completeness, and evolution hint.
- `FailurePatternRecord`: repeated/current failure pattern with do-not-repeat rules and recommended evolution target.
- `SuccessPatternRecord`: reusable successful procedure/skill card.
- `EvolutionEvidencePack`: Knowledge-to-SelfEvolution contract.
- `EvolutionOutcomeRecord`: before/after attribution after variant activation.

## Persistence

The first production implementation is file-backed and intentionally inspectable.

Per-run artifacts:

```text
runs/<run_id>/knowledge/knowledge_report.json
runs/<run_id>/knowledge/experiment_knowledge_record.json
runs/<run_id>/knowledge/agent_performance_records.json
runs/<run_id>/knowledge/failure_patterns.json
runs/<run_id>/knowledge/success_patterns.json
runs/<run_id>/knowledge/evolution_evidence_packs.json
```

Long-term memory:

```text
memory/knowledge/experiment_knowledge_records.jsonl
memory/knowledge/agent_performance_records.jsonl
memory/knowledge/failure_patterns.jsonl
memory/knowledge/success_patterns.jsonl
memory/knowledge/evolution_evidence_packs.jsonl
memory/knowledge/evolution_outcomes.jsonl
```

This can later migrate to SQLite, DuckDB, vector index, or graph/RDF export without changing the runtime packet contract.

## Handoff Contracts

Knowledge Agent emits:

- `knowledge_context.v1`: hot/episodic/semantic/evolution/archival memory summary and evidence quality.
- `evolution_proposal.v1`: evidence packs and Evolution Lab task prefill payloads.
- `knowledge_report.v1`: human-readable memory/evolution board data for Live GUI.

`EvolutionEvidencePack` maps to `EvolutionTaskCreate` as:

```text
pack.target_type -> task.target_type
pack.target_id -> task.target_id
pack.objective -> task.objective
pack.provenance.was_derived_from -> task.source_run_ids
pack.constraints + knowledge_evidence_pack_id -> task.constraints
```

## Self-Evolution Integration

`SelfEvolutionService` reads Knowledge evidence packs from:

```text
runs/<run_id>/knowledge/evolution_evidence_packs.json
memory/knowledge/evolution_evidence_packs.jsonl
```

When a matching pack exists for the selected target, generated prompt/tool/report/policy guidance includes:

- evidence objective
- why this target
- recommended changes
- safety constraints
- supporting trace lineage

The service still performs only schema/config/dry-run evaluation. It never executes physical hardware during candidate evaluation.

## API

Knowledge API endpoints:

- `GET /api/knowledge/evolution-packs?target_type=&target_id=&limit=`
- `GET /api/knowledge/agent-performance?agent_id=&limit=`
- `GET /api/knowledge/failure-patterns?agent_id=&stage=&limit=`
- `GET /api/knowledge/success-patterns?agent_id=&limit=`
- `GET /api/knowledge/evolution-outcomes?target_id=&limit=`
- `POST /api/knowledge/evolution-outcomes`
- `GET /api/knowledge/run-context?agent_id=&run_id=`
- `GET /api/knowledge/bo-context?objective_id=&limit=`
- `GET /api/knowledge/safety-context?stage=&limit=`

Evolution Lab uses `/api/knowledge/evolution-packs` to prefill task objective, constraints, source runs, and evidence pack id.

## Live GUI / Report Behavior

Knowledge Agent report should show:

- Memory ledger: experiment record id, agent performance count, failure/success pattern count, evidence pack count.
- Retrieval panel: RAG coverage, local/web source counts, source trust summary.
- Failure/success library: current pattern records and reusable success cards.
- Agent performance memory: status, score, missing fields, warnings, retry count.
- Self-evolution board: top packs, target ids, objectives, prefill tasks, approval boundary.
- Data quality map: artifact link coverage and missing artifacts.

Live chat should report memory/evidence update counts and top evolution target, not raw JSON.

## Safety Rules

- Knowledge recommends; it does not activate.
- SelfEvolutionService generates and gates; Guardian/operator approve.
- No evolved variant controls live hardware before approval.
- No active-run activation.
- Code patch variants remain diff-only.
- Every memory/evidence record must include provenance and confidence/quality fields.
- Failed self-evolution attempts should also remain as memory evidence.

## Current Verification Evidence

The first file-backed implementation has regression coverage for the core 8번 contracts:

```text
pytest tests/integration/test_knowledge_api.py \
       tests/unit/test_knowledge_agent.py \
       tests/unit/test_self_evolution.py \
       tests/integration/test_live_gui_runtime_layout.py::test_evolution_lab_supports_live_gui_query_prefill -q
```

This verifies:

- Knowledge API filters and returns typed performance, failure, success, evidence-pack, run-context, BO-context, safety-context, and outcome records.
- `/api/agents/knowledge/report` exposes memory ledger, retrieval panel, failure/success library, self-evolution board, handoff packet, decisions, and evidence metrics.
- Knowledge Agent still persists the legacy `MemoryRecord` while emitting typed `knowledge_context.v1`, `knowledge_report.v1`, and `evolution_proposal.v1`.
- SelfEvolutionService reads `EvolutionEvidencePack` guidance and preserves its gated approval/activation lifecycle.
- Evolution Lab includes a Knowledge Evidence Pack panel and passes `knowledge_evidence_pack_id` into task constraints.

Additional runtime regression:

```text
pytest tests/unit/test_langgraph_runtime.py tests/unit/test_experiment_runtime.py -q
pytest tests/integration/test_controller_run.py::test_controller_completes_test_run -q
```

These prove that the Knowledge payload remains compatible with the existing LangGraph/runtime loop and the controller closed-loop smoke path.

Implemented 8번 closure items in this pass:

- Browser screenshot audit for the Knowledge report, Evolution Lab evidence-pack board, and replay/eval candidate card.
- Automatic `EvolutionOutcomeRecord` attribution after an activated variant is observed in a later run ledger.
- Deterministic replay/eval harness for source and held-out traces, exposed in `variant.metrics.replay_eval` and Evolution Lab.

Remaining hardening is now post-baseline rather than blocking for the file-backed 8번 implementation:

- Migrate JSON/JSONL memory to SQLite, DuckDB, vector index, graph DB, or RDF/PROV export if query scale requires it.
- Add domain-specific held-out replay suites and causal trend scoring before treating outcome verdicts as proof.
- Add richer statistical aggregation over repeated `EvolutionOutcomeRecord` rows.

## Browser Audit Evidence

A headless Firefox audit was run against a latest-code FastAPI server and verified the operator-facing 8번 surfaces:

- Live GUI Knowledge report displays `Knowledge Memory / Self-Evolution Evidence`.
- The report includes Memory Ledger, Failure Pattern Memory, Success/Skill Library, Agent Performance Ledger, Self-Evolution Evidence Packs, Evolution Lab Prefill, and Data Quality/Missing Evidence sections.
- Evidence pack ids from `knowledge_report.self_evolution.evidence_packs` remain visible even when the compact top-level `evolution_proposal` has no packs.
- Evolution Lab displays the Knowledge Evidence Pack panel and cards returned by `/api/knowledge/evolution-packs`.

Saved audit artifacts:

```text
artifacts/goal_upgrade/screenshots/live_desktop_report_knowledge.png
artifacts/goal_upgrade/screenshots/evolution_lab_knowledge_evidence_pack.png
artifacts/goal_upgrade/screenshots/knowledge_evolution_browser_audit.json
```

## Automatic Outcome Attribution

Knowledge Agent now records conservative post-activation outcomes for active self-evolution variants.

Runtime behavior:

1. Read active variants from `memory/evolution/active_variants.json`.
2. Read variant lineage from `memory/evolution/variants/<variant_id>.json` when available.
3. Compare the active target against the current run's `AgentPerformanceRecord` signals.
4. Write per-run `runs/<run_id>/knowledge/evolution_outcomes.json`.
5. Append long-term `memory/knowledge/evolution_outcomes.jsonl`.
6. Expose outcomes in `/api/knowledge/evolution-outcomes` and `/api/agents/knowledge/report`.

This attribution is intentionally conservative. It records warning/error deltas, after-run score, artifact completeness, contract validity, verdict, rollback recommendation, and provenance. It does not auto-promote or auto-rollback variants. Guardian/operator review remains required.

## Replay / Eval Harness

`self_evolution/evaluator.py` implements a deterministic replay/eval harness for self-evolution candidates. It uses held-out traces when present and otherwise falls back to source traces. It appends replay gates to the variant and stores aggregate metrics under `variant.metrics.replay_eval`.

Current replay gates:

- `replay_cases_present`
- `replay_schema_validity`
- `replay_contract_completeness`
- `replay_groundedness_to_trace`
- `replay_safety_preservation`
- `replay_no_forbidden_behavior`

Evolution Lab renders the replay score, gate pass count, held-out/source trace counts, replay trace ids, and event/error/warning/missing-field counts in the candidate panel.

Current limitation: replay/eval and outcome scoring are conservative ledger/trace checks. They are suitable for safety screening and regression evidence, but not yet causal proof of live performance improvement.
