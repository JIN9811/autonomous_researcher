# Knowledge Graphify Graph Backend Upgrade Plan

## Purpose

이 문서는 8번 개선안의 후속 고도화로, `Knowledge Agent`의 JSON/JSONL 기반 typed memory를 Graphify 기반 project graph 및 graph database backend와 연결하는 계획이다.

목표는 기존 runtime을 깨지 않고 아래 구조를 추가하는 것이다.

```text
Project code/docs graph
  -> Graphify graph.json / graph.html / GRAPH_REPORT.md
  -> graph DB import
  -> Knowledge retrieval context

Runtime typed memory
  -> ExperimentKnowledgeRecord / AgentPerformanceRecord
  -> FailurePatternRecord / SuccessPatternRecord
  -> EvolutionEvidencePack / EvolutionOutcomeRecord
  -> graph DB mirror
  -> Knowledge / BO / Guardian / Self-Evolution query context
```

Graphify는 runtime memory store를 대체하지 않는다. Graphify는 코드, 문서, PDF, diagram, rationale를 구조화하는 repository-level knowledge graph builder로 사용하고, runtime 실험 기억은 현재 `knowledge/*` typed schema를 source of truth로 유지한다.

## External Finding Summary

조사 기준:

- Graphify 공식 페이지는 code, docs, papers, diagrams를 읽어 queryable knowledge graph를 만들고 `graph.html`, `graph.json`, `GRAPH_REPORT.md`를 출력한다고 설명한다.
- Graphify는 `NetworkX` graph와 Tree-sitter 기반 구조 추출, LLM semantic extraction, Leiden community detection을 사용하는 방향이다.
- Graphify 자체는 Neo4j 같은 graph DB가 아니라 graph artifact generator에 가깝다.
- Neo4j는 Python driver와 Cypher query를 제공하므로 `graph.json` 및 ATR typed memory를 graph DB에 적재하는 backend로 현실적이다.

References:

- Graphify official: https://graphify.net/zh/
- Graphify hosted overview: https://graphify.homes/en
- Graphify technical summary: https://daniliants.com/insights/graphify-knowledge-graph-skill-for-ai-coding-assistants/
- Neo4j Python guide: https://neo4j.com/developer/languages/python/tutorials/get-started-with-neo4j-and-python/

## Design Principles

1. 기존 `memory/knowledge/*.jsonl`은 계속 유지한다.
2. Graph DB는 mirror/index/query accelerator로 시작한다. source of truth가 아니다.
3. Knowledge Agent는 graph DB가 없어도 동작해야 한다.
4. Graphify project graph와 runtime experiment graph를 분리하되, `doc_ref`, `module_id`, `agent_id`, `run_id`, `artifact_ref`로 연결한다.
5. live hardware action과 graph write는 분리한다. graph backend failure가 실험 run을 막으면 안 된다.
6. 모든 graph DB write는 provenance와 source JSONL offset 또는 artifact fingerprint를 포함한다.
7. Self-Evolution은 graph query 결과를 evidence로 사용할 수 있지만, graph query만으로 variant를 자동 활성화하지 않는다.

## Target Architecture

```text
/home/jin/autonomous_researcher
  -> Graphify repository scan
      -> memory/knowledge/graphify/project_graph.json
      -> memory/knowledge/graphify/project_graph.html
      -> memory/knowledge/graphify/GRAPH_REPORT.md
      -> GraphifyProjectGraphStore
          -> graph DB import

closed-loop run
  -> KnowledgeAgent
      -> file-backed typed memory JSON/JSONL
      -> KnowledgeGraphMirror
          -> graph DB upsert
      -> KnowledgeGraphRetriever
          -> run context
          -> research context
          -> evolution context
          -> BO context
          -> safety context
```

Recommended first backend:

```text
Phase A: local graph.json only
Phase B: Kuzu embedded graph DB optional
Phase C: Neo4j Docker graph DB optional
```

Reasoning:

- `graph.json` is easiest to audit and commit-ignore.
- Kuzu is lightweight/embedded and avoids operating a Java service.
- Neo4j is strongest for Cypher queries, visualization, and multi-user inspection, but requires service management.

## Data Model

### Node Types

Project graph nodes:

| Label | Key | Notes |
|---|---|---|
| `CodeFile` | `path` | Python/JS/YAML source files |
| `DocFile` | `path` | docs, README, package instructions |
| `Module` | `module_id` | `graphs/modules/<agent>/module.yaml` |
| `Agent` | `agent_id` | design, specimen, vision, manipulation, equipment, analysis, knowledge, bo, guardian, orchestrator |
| `RuntimeAPI` | `route` | FastAPI route from `app/main.py` |
| `Tool` | `tool_id` | MCP/device bridge/tool function |
| `Concept` | `concept_id` | Graphify semantic concept/community |
| `DecisionRationale` | `rationale_id` | extracted design intent or doc rationale |

Runtime memory nodes:

| Label | Key | Source |
|---|---|---|
| `Run` | `run_id` | `runs/<run_id>` |
| `Experiment` | `experiment_id` | `ExperimentKnowledgeRecord` |
| `Specimen` | `candidate_id` / `specimen_id` | design/specimen packets |
| `Artifact` | `artifact_id` or `path` | artifact refs |
| `AgentPerformance` | `record_id` | `AgentPerformanceRecord` |
| `FailurePattern` | `pattern_id` | `FailurePatternRecord` |
| `SuccessPattern` | `skill_id` | `SuccessPatternRecord` |
| `EvolutionPack` | `pack_id` | `EvolutionEvidencePack` |
| `EvolutionOutcome` | `outcome_id` | `EvolutionOutcomeRecord` |
| `GuardianDecision` | `decision_id` | guardian events/incidents |
| `BOObservation` | `observation_id` | analysis/BO handoff |

### Edge Types

| Edge | From -> To | Meaning |
|---|---|---|
| `GENERATED_BY` | record/artifact -> Agent | provenance `was_generated_by` |
| `USED` | record -> artifact/doc/module | provenance `used` |
| `DERIVED_FROM` | record -> run/record/artifact | provenance `was_derived_from` |
| `ASSOCIATED_WITH` | record -> agent/module/tool | provenance `was_associated_with` |
| `AFFECTS` | failure/evolution -> agent/module/tool | target relation |
| `RECOMMENDS` | EvolutionPack -> Module/Agent | target recommendation |
| `MITIGATES` | SuccessPattern/EvolutionPack -> FailurePattern | improvement relation |
| `OBSERVED_IN` | performance/failure/success -> Run | runtime occurrence |
| `SUPPORTS_BO` | Experiment/Analysis -> BOObservation | BO handoff context |
| `BLOCKED_BY` | action/pack -> GuardianDecision | safety gating |
| `DOCUMENTS` | DocFile -> Module/Agent/API | project guide relation |
| `CALLS` | CodeFile/API/Agent -> Tool/API | static/runtime call relation |
| `IMPLEMENTS` | CodeFile -> Module/Agent/API | implementation relation |

## Storage Layout

New local artifacts:

```text
memory/knowledge/graphify/
  project_graph.json
  project_graph.html
  GRAPH_REPORT.md
  import_manifest.json
  last_scan.json

memory/knowledge/graph_backend/
  backend_config.json
  import_state.json
  query_cache.jsonl
  health.json
```

Do not commit runtime graph DB files by default. Add generated DB/storage paths to `.gitignore` if a DB backend creates local data directories.

## Backend Interface

Add a small backend abstraction instead of coupling Knowledge Agent directly to Neo4j/Kuzu.

Proposed files:

```text
knowledge/graph_backend.py
knowledge/graph_importer.py
knowledge/graph_queries.py
scripts/knowledge_graphify_scan.py
scripts/knowledge_graph_import.py
```

### `KnowledgeGraphBackend`

Required methods:

```python
class KnowledgeGraphBackend:
    def health(self) -> dict: ...
    def upsert_nodes(self, nodes: list[dict]) -> dict: ...
    def upsert_edges(self, edges: list[dict]) -> dict: ...
    def query(self, query: dict) -> dict: ...
    def close(self) -> None: ...
```

Initial implementations:

```text
JsonGraphBackend      -> reads/writes graph.json for offline fallback
KuzuGraphBackend      -> optional embedded graph DB
Neo4jGraphBackend     -> optional service backend
```

## Knowledge Agent Integration

### Write Path

Current write path remains:

```text
KnowledgeAgent
  -> KnowledgeMemoryStore
  -> JSON per-run artifacts
  -> JSONL long-term memory
```

Add best-effort mirror:

```text
KnowledgeAgent
  -> KnowledgeGraphMirror
      -> convert typed records to graph nodes/edges
      -> graph backend upsert
      -> emit graph_backend_status in knowledge_report
```

If graph backend fails:

```text
status = degraded
run continues
warning stored in knowledge_report.data_quality
JSONL remains authoritative
```

### Read Path

Existing retrieval functions stay:

```text
retrieve_run_context
retrieve_research_context
retrieve_evolution_context
```

Add optional graph enrichment:

```text
retrieve_graph_run_context(agent_id, run_id)
retrieve_graph_failure_context(agent_id, failure_type)
retrieve_graph_evolution_context(target_type, target_id)
retrieve_graph_project_context(module_id, question)
```

Return shape must match existing `KnowledgeSourceRef` style:

```json
{
  "source_type": "graph_backend",
  "source_ref": "neo4j://FailurePattern/<pattern_id>",
  "trust_level": "runtime_provenance_graph",
  "retrieval_score": 0.88,
  "used_for": ["evolution_context", "bo_context"],
  "records": []
}
```

## Graphify Scan Flow

Manual command target:

```bash
atr knowledge graphify-scan
atr knowledge graphify-import
```

Equivalent script:

```bash
python scripts/knowledge_graphify_scan.py \
  --project-root /home/jin/autonomous_researcher \
  --out-dir memory/knowledge/graphify
```

Expected behavior:

1. Run Graphify on selected folders:
   - `agents/`
   - `graphs/`
   - `app/`
   - `orchestrator/`
   - `knowledge/`
   - `self_evolution/`
   - `docs/README.md`
   - `docs/runtime/`
   - `docs/agents/`
   - `docs/hardware/`
2. Exclude heavy/generated folders:
   - `.git/`
   - `.venv/`
   - `runs/`
   - `artifacts/`
   - `memory/`
   - `__pycache__/`
3. Save outputs to `memory/knowledge/graphify/`.
4. Write `import_manifest.json` with timestamp, source paths, checksums, Graphify version, and output paths.

## Graph DB Import Flow

Manual command target:

```bash
atr knowledge graph-import --backend neo4j
```

Equivalent script:

```bash
python scripts/knowledge_graph_import.py \
  --graphify-json memory/knowledge/graphify/project_graph.json \
  --backend neo4j \
  --config memory/knowledge/graph_backend/backend_config.json
```

Import stages:

1. Validate graph.json schema.
2. Normalize node ids and labels.
3. Upsert project graph nodes and edges.
4. Read latest Knowledge JSONL records.
5. Upsert runtime typed memory nodes and edges.
6. Run health query and sample traversals.
7. Save import summary to `memory/knowledge/graph_backend/import_state.json`.

## Example Queries

### Evolution Target Context

```cypher
MATCH (p:FailurePattern)-[:AFFECTS]->(a:Agent {agent_id: $agent_id})
OPTIONAL MATCH (e:EvolutionPack)-[:RECOMMENDS]->(a)
OPTIONAL MATCH (s:SuccessPattern)-[:MITIGATES]->(p)
RETURN p, e, s
ORDER BY p.recurrence_count DESC
LIMIT 10
```

### Project-Runtime Link

```cypher
MATCH (m:Module {module_id: $module_id})<-[:IMPLEMENTS]-(f:CodeFile)
OPTIONAL MATCH (d:DocFile)-[:DOCUMENTS]->(m)
OPTIONAL MATCH (p:AgentPerformance)-[:ASSOCIATED_WITH]->(m)
RETURN m, collect(DISTINCT f), collect(DISTINCT d), collect(DISTINCT p)
```

### BO Safety Context

```cypher
MATCH (obs:BOObservation)<-[:SUPPORTS_BO]-(exp:Experiment)
OPTIONAL MATCH (g:GuardianDecision)<-[:BLOCKED_BY]-(obs)
OPTIONAL MATCH (fp:FailurePattern)-[:OBSERVED_IN]->(:Run)<-[:OBSERVED_IN]-(obs)
RETURN obs, exp, g, fp
ORDER BY obs.created_at DESC
LIMIT 20
```

## GUI Integration

### Live GUI Knowledge Report

Add optional sections when graph backend is enabled:

- Graph backend health: backend type, node count, edge count, last import time.
- Project graph context: related code/docs/modules for selected agent.
- Runtime memory graph: connected failure/success/performance/evolution nodes.
- Evidence path view: shortest path from failure pattern to proposed evolution pack.

### Evolution Lab

Add evidence pack graph context:

- supporting graph path count
- linked modules/docs/code files
- related historical outcomes
- conflicting evidence warning if graph traversal finds contradictory outcomes

### Runtime IDE

Use Graphify project graph as optional architecture overlay:

- module -> code file -> API/tool edges
- doc rationale -> module edges
- static graph community labels

## Configuration

Proposed config in `configs/system.yaml` or `configs/knowledge_graph.yaml`:

```yaml
knowledge_graph:
  enabled: false
  graphify:
    enabled: false
    output_dir: memory/knowledge/graphify
    include:
      - agents
      - app
      - orchestrator
      - graphs
      - knowledge
      - self_evolution
      - docs/runtime
      - docs/agents
      - docs/hardware
    exclude:
      - .git
      - .venv
      - runs
      - artifacts
      - memory
      - __pycache__
  backend:
    type: json
    uri: ""
    database: ""
    username: ""
    password_env: ATR_NEO4J_PASSWORD
    write_mode: mirror
    fail_open: true
```

## Dependencies

Minimum:

```text
graphifyy       # optional CLI/package, command name graphify
networkx        # graph artifact fallback/query
```

Optional:

```text
neo4j           # Neo4j Python driver
kuzu            # embedded graph DB candidate
```

Dependency policy:

- Add Graphify/Neo4j/Kuzu as optional extras first.
- Do not make normal ATR startup depend on graph DB availability.
- Add clear install docs in `REQUIREMENTS.md` when implementation begins.

## Security / Safety

- Do not send raw source or private run artifacts to external services without operator approval.
- Prefer local Graphify execution. If hosted Graphify is used, require explicit export package and operator confirmation.
- Exclude secrets, `memory/*connection*.json`, `.env`, credentials, and generated raw hardware logs from Graphify scan.
- Graph DB query results are evidence, not authority. Guardian and operator approval still control live actions and self-evolution activation.
- Cypher/graph queries must use parameters, not string interpolation.
- Graph import must sanitize labels and relationship names.

## Current Implementation Status

The optional backend baseline is implemented as a fail-open mirror/index layer.

Implemented files:

```text
knowledge/graph_backend.py      # Null, JSON, and optional Neo4j backend abstraction
knowledge/graph_importer.py     # typed Knowledge record -> graph node/edge conversion
requirements-graph.txt          # optional graph dependencies
```

Implemented API endpoints:

```text
GET  /api/knowledge/graph/health
POST /api/knowledge/graph/import
GET  /api/knowledge/graph/query
```

Implemented CLI:

```text
scripts/knowledge_graph_cli.py
atr knowledge graph health
atr knowledge graph import
atr knowledge graph query
atr knowledge graph neo4j-start --wait
atr knowledge graph neo4j-stop
atr knowledge graph print-env
```

Implemented runtime behavior:

- Knowledge Agent keeps JSON/JSONL as source of truth.
- Graph backend is disabled by default.
- When enabled, Knowledge Agent mirrors typed records to the configured backend and writes `graph_backend_status` into `knowledge_context.v1` and `knowledge_report.v1`.
- If Neo4j is unavailable and fail-open is enabled, the backend falls back to local JSON graph storage.
- Live GUI Knowledge report displays optional graph backend status.

Environment variables:

```bash
export ATR_KNOWLEDGE_GRAPH_ENABLED=1
export ATR_KNOWLEDGE_GRAPH_BACKEND=json      # json | neo4j
export ATR_KNOWLEDGE_GRAPH_FAIL_OPEN=1

# only for neo4j
export ATR_NEO4J_URI=bolt://127.0.0.1:7687
export ATR_NEO4J_USERNAME=neo4j
export ATR_NEO4J_PASSWORD='<local-password>'
export ATR_NEO4J_DATABASE=neo4j
```

Verified local operation on 2026-05-30:

- `neo4j:5-community` Docker image was pulled and started as `atr-neo4j`.
- Bolt health succeeded at `bolt://127.0.0.1:7687`.
- `atr knowledge graph import --limit 20` imported 100 recent Knowledge records into Neo4j.
- Neo4j health reported 404 nodes and 2795 edges after repeated runtime verification/import.
- `target_context` query for `prompt:analysis` returned compact nodes/edges.
- Graphify-compatible fallback scan produced 56 project nodes and 183 project edges for `agents/` + `docs/runtime/`.
- Installed `graphifyy==0.4.4`; `graphify --help` works through `/home/jin/.local/bin/graphify`.
- `atr knowledge graphify-scan --external-graphify --source agents --source knowledge` used Graphify Python API and produced 642 nodes and 1527 edges.
- Graphify CLI query was verified against `memory/knowledge/graphify/external_raw/graph.json`; ATR normalized `project_graph.json` remains the backend import artifact.
- The external Graphify graph was imported into JSON and Neo4j backends; JSON import wrote 1284 nodes and 1527 edges after preserving referenced endpoint placeholders.
- `graphify-import --no-runtime-memory` imported 56 project nodes and 183 project edges into both JSON fallback and Neo4j.
- Neo4j health after project graph import reported 451 nodes and 2978 edges.
- `project_context` query kind was added for code/docs/module context retrieval.
- JSON fallback import also produced 274 nodes and 1636 edges.
- CLI `--json-path` was verified to route JSON backend storage to the requested path.

Current implementation expansion:

- `knowledge/graphify_bridge.py` implements Graphify-compatible project graph scan/import.
- `scripts/knowledge_graphify_scan.py` writes `project_graph.json`, `GRAPH_REPORT.md`, `project_graph.html`, `import_manifest.json`, and `last_scan.json` under `memory/knowledge/graphify/`.
- `scripts/knowledge_graph_import.py` imports project graph artifacts into JSON or Neo4j graph backend and can optionally include runtime Knowledge memory.
- `atr knowledge graphify-scan` and `atr knowledge graphify-import` are installed terminal commands.
- API endpoints `/api/knowledge/graphify/scan` and `/api/knowledge/graphify/import` expose the same functions for GUI/backend use.
- `project_context` query kind retrieves project graph context separately from runtime `target_context`.
- The fallback scanner preserves out-of-scan references as `ExternalReference` nodes instead of dropping edges.
- Neo4j uses a safe generic `ATRKnowledgeNode` / `ATR_KNOWLEDGE_REL` model with relationship type stored as a property; this avoids dynamic Cypher label/type injection.

Current limitation:

- External Graphify API execution is optional and disabled by default. Install `graphifyy==0.4.4` and pass `--external-graphify` to run Graphify AST/community extraction first.
- On this ARM64/Python 3.12 workstation, latest `graphifyy` failed because `tree-sitter-dm` needs `Python.h`; either install `python3.12-dev` or keep the pinned `graphifyy==0.4.4`.
- The installed terminal command is `/home/jin/.local/bin/graphify`, backed by `/home/jin/autonomous_researcher/.venv/bin/graphify`.
- Graphify `graphify query` works on existing graph JSON; generation is called through the installed Graphify Python API because the CLI generation flow is exposed as agent skill instructions rather than a direct `graphify scan` command in `0.4.4`.
- The fallback scanner is deterministic and local, but less semantically rich than a full Graphify LLM/AST/community extraction pass.

## Implementation Phases

### Phase 0: Feasibility Spike

Deliverables:

- Install/check Graphify locally in an isolated environment.
- Run scan on a small subset: `knowledge/`, `self_evolution/`, `docs/agents/knowledge_agent_self_evolution_runtime_guideline.md`.
- Save graph artifacts under `memory/knowledge/graphify/`.
- Document graph node/edge quality.

Acceptance:

- `graph.json` exists.
- `GRAPH_REPORT.md` exists.
- No secrets or generated heavy folders included.

### Phase 1: JSON Graph Backend

Deliverables:

- `knowledge/graph_backend.py` with `JsonGraphBackend`.
- `knowledge/graph_importer.py` converts Graphify graph.json + typed Knowledge JSONL records into unified graph JSON.
- Unit tests for node/edge normalization and provenance mapping.

Acceptance:

- Knowledge Agent still passes all existing tests with graph backend disabled.
- Importer produces deterministic node/edge counts from fixtures.
- Query helpers return source refs compatible with current retrieval output.

### Phase 2: Knowledge Agent Mirror Write

Deliverables:

- Best-effort graph mirror write after Knowledge JSONL append.
- `knowledge_report.graph_backend_status` section.
- Live GUI Knowledge report section for graph health.

Acceptance:

- Graph backend failure does not fail the closed-loop run.
- Report shows degraded/healthy status explicitly.
- Tests cover fail-open behavior.

### Phase 3: Graph Retrieval Context

Deliverables:

- Graph-backed retrieval helpers for run, failure, evolution, BO, safety context.
- SelfEvolutionService can receive graph-enriched evidence summaries from Knowledge.
- BO Agent can receive graph-derived failure/success constraints as optional context.

Acceptance:

- Existing JSON/RAG retrieval remains fallback.
- Graph context includes provenance path and trust level.
- Tests verify graph context is not used when stale or unavailable.

### Phase 4: Neo4j or Kuzu Backend

Deliverables:

- Optional `Neo4jGraphBackend` or `KuzuGraphBackend`.
- Import script with health check and sample Cypher/query tests.
- `atr knowledge graph-import` CLI command.

Acceptance:

- Local graph DB can be populated from Graphify + Knowledge JSONL.
- Query latency and result quality are logged.
- Credentials are stored through env/config, not committed.

### Phase 5: GUI Evidence Path Viewer

Deliverables:

- Live GUI Knowledge report graph path cards.
- Evolution Lab evidence path display.
- Runtime IDE optional architecture overlay.

Acceptance:

- Browser audit captures graph path section.
- Graph section can be collapsed to keep Live GUI light.
- No raw huge JSON appears in report view.

## Test Plan

Unit tests:

```text
tests/unit/test_knowledge_graph_backend.py
tests/unit/test_knowledge_graph_importer.py
tests/unit/test_knowledge_graph_queries.py
```

Integration tests:

```text
tests/integration/test_knowledge_graph_api.py
tests/integration/test_knowledge_agent_graph_mirror.py
```

Browser/UI audit:

```text
tests/ui/knowledge_graph_browser_audit.py
```

Manual checks:

```bash
python scripts/knowledge_graphify_scan.py --dry-run
python scripts/knowledge_graph_import.py --backend json
pytest -q tests/unit/test_knowledge_agent.py tests/unit/test_self_evolution.py
```

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Graphify output schema changes | importer breaks | schema adapter + fixture tests |
| Graph DB service unavailable | closed-loop blocked | fail-open, JSONL source of truth |
| Graph becomes stale | wrong context | import timestamp, source checksum, stale warning |
| Too many nodes/edges slow GUI | UI memory growth | collapsed graph sections, pagination, summary query |
| Secrets included in scan | security issue | strict exclude rules and secret scanner |
| LLM semantic extraction cost | slow/costly scan | subset scan, cache, manual trigger only |
| Graph context over-trusted | unsafe evolution | Guardian/operator gates remain mandatory |

## Definition of Done

Graphify-based graph backend should be considered production-ready only when:

- Graphify scan can be run manually without touching live hardware.
- Generated graph artifacts are stored under `memory/knowledge/graphify/` and excluded from Git unless explicitly exported.
- Typed Knowledge records are mirrored to graph backend with provenance.
- Retrieval helpers return graph-backed context with trust/staleness metadata.
- Live GUI displays graph backend health and evidence paths without raw JSON dumps.
- SelfEvolutionService can include graph-derived evidence but still requires validation, Guardian, and operator approval.
- Tests pass with graph backend disabled and enabled in JSON fallback mode.
- Graph DB dependency is optional and documented in `REQUIREMENTS.md`.

## Recommended Next Step

Start with Phase 0 and Phase 1 only.

Do not introduce Neo4j/Kuzu into normal startup yet. First prove that Graphify can generate useful project graph artifacts and that ATR typed Knowledge records can be converted to a stable graph JSON with provenance-preserving edges.
