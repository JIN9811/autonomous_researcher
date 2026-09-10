"""Knowledge decisions must change real note/retrieval effects, not just summaries."""
from copy import deepcopy
import importlib.util
import json
from types import SimpleNamespace

import pytest

from orchestrator.state import Mode, OrchestratorState, Stage


def request(tool, **arguments):
    return json.dumps({"tool": tool, "arguments": arguments})


def setup(tmp_path, responses):
    from knowledge.markdown_runtime import store_for
    state = OrchestratorState(run_id="decision-run", experiment_id="exp-a", mode=Mode.TEST, stage=Stage.KNOWLEDGE,
                              active_goal="Preserve an exported result and retrieve relevant process evidence")
    class Context:
        force_real_llm_in_test = True
        active_backend = "fixture"
        artifact_run_root = str(tmp_path / "runs")
        def __init__(self):
            self.prompts = []
        async def complete(self, task_type, prompt, **kwargs):
            assert task_type == "knowledge_query"
            self.prompts.append(prompt)
            return SimpleNamespace(text=responses.pop(0), model="fixture")
    evidence = [{"id": "current-analysis", "source_ref": "runs/decision-run/analysis.json",
                 "agent_id": "analysis_agent", "content": {"objective_score": 1.25, "result": "verified export"}}]
    return state, Context(), store_for(project_root=tmp_path), evidence


@pytest.mark.asyncio
async def test_model_inspects_writes_real_md_and_publishes_cited_context(tmp_path):
    assert importlib.util.find_spec("agents.knowledge_decision") is not None
    from agents.knowledge_decision import run_knowledge_decision
    responses = [request("inspect_evidence"), request("write_knowledge_note", title="Verified export",
        body="The current analysis reports verified export; no causal claim is made.", ontology_type="KnowledgeClaim",
        evidence_kind="derived", source_ids=["current-analysis"], tags=["export"]),
        request("publish_context", summary="The current result has a verified export.",
                source_ids=["current-analysis"], no_knowledge_reason="")]
    state, ctx, store, evidence = setup(tmp_path, responses)
    before = deepcopy(evidence)
    result = await run_knowledge_decision(state, ctx, store=store, evidence=evidence, scope={"run_id": "decision-run"})
    assert result["status"] == "accepted" and result["llm_used"]
    assert [event["tool"] for event in result["trace"]] == ["inspect_evidence", "write_knowledge_note", "publish_context"]
    assert store.search("verified", scope={"run_id": "decision-run"})["hits"]
    assert result["citations"][0]["source_ref"] == "runs/decision-run/analysis.json"
    assert evidence == before
    assert "verified export" in ctx.prompts[1]
    assert set(json.loads(ctx.prompts[0])["tools"]) == {"inspect_evidence"}
    assert "publish_context" in json.loads(ctx.prompts[1])["tools"]


@pytest.mark.asyncio
async def test_model_can_withhold_derived_knowledge_when_evidence_is_insufficient(tmp_path):
    assert importlib.util.find_spec("agents.knowledge_decision") is not None
    from agents.knowledge_decision import run_knowledge_decision
    responses = [request("inspect_evidence"), request("search_knowledge", query="root cause", scope={}, top_k=3),
        request("publish_context", summary="No supported root cause is available.", source_ids=[],
                no_knowledge_reason="The current export observation does not establish a cause.")]
    state, ctx, store, evidence = setup(tmp_path, responses)
    result = await run_knowledge_decision(state, ctx, store=store, evidence=evidence, scope={"run_id": "decision-run"})
    assert result["status"] == "accepted"
    assert result["no_knowledge_reason"]
    assert store.status()["records"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    request("search_knowledge", query="x", scope={"run_id": "other-run"}),
    request("write_knowledge_note", title="x", body="Invented", ontology_type="Observation", evidence_kind="observed", source_ids=["fake"]),
    request("publish_context", summary="Unsupported", source_ids=["fake"], no_knowledge_reason=""),
    "not json",
])
async def test_invalid_decision_is_not_success_and_does_not_write(tmp_path, bad):
    assert importlib.util.find_spec("agents.knowledge_decision") is not None
    from agents.knowledge_decision import run_knowledge_decision
    state, ctx, store, evidence = setup(tmp_path, [request("inspect_evidence"), bad])
    result = await run_knowledge_decision(state, ctx, store=store, evidence=evidence, scope={"run_id": "decision-run"})
    assert result["status"] == "failed"
    assert store.status()["records"] == 0


@pytest.mark.asyncio
async def test_search_then_detail_uses_scope_and_passes_observation_back_to_model(tmp_path):
    assert importlib.util.find_spec("agents.knowledge_decision") is not None
    from agents.knowledge_decision import run_knowledge_decision
    responses = []
    state, ctx, store, evidence = setup(tmp_path, responses)
    receipt = store.write_note(dict(run_id="decision-run", cycle_id="loop-000001", agent_id="equipment",
        event_id="prior", ontology_type="Observation", title="Export guidance", body="Confirmed export file was present.",
        source_refs=["runs/decision-run/prior.json"]))
    responses.extend([request("inspect_evidence"), request("search_knowledge", query="export", scope={}, top_k=2),
        request("read_knowledge", record_id=receipt["record_id"]),
        request("publish_context", summary="A previous export file was present.", source_ids=[receipt["record_id"]],
                no_knowledge_reason="Existing note already captures the observation.")])
    result = await run_knowledge_decision(state, ctx, store=store, evidence=evidence, scope={"run_id": "decision-run"})
    assert result["status"] == "accepted"
    assert result["selected_knowledge"][0]["record_id"] == receipt["record_id"]
    assert "Confirmed export file" in ctx.prompts[-1]


def test_bo_receives_scoped_knowledge_citations_without_changing_analysis_values():
    from agents.bo_agent import BOAgent
    state = OrchestratorState(run_id="run-a", experiment_id="a", mode=Mode.TEST, stage=Stage.BO,
        latest_analysis={"objective_score": 1.25}, run_metadata={"knowledge": {
            "memory_summary": "Supported export", "scope": {"run_id": "run-a"},
            "selected_knowledge": [{"record_id": "note-a", "excerpt": "Export exists"}],
            "citations": [{"source_id": "note-a", "source_ref": "runs/run-a/note.md"}]}})
    before = deepcopy(state.latest_analysis)
    result = BOAgent._knowledge_context_from_state(state)
    assert result["citations"][0]["source_ref"] == "runs/run-a/note.md"
    assert result["selected_knowledge"][0]["record_id"] == "note-a"
    assert result["scope"] == {"run_id": "run-a"}
    assert state.latest_analysis == before


def test_llm_scope_cannot_drop_required_tags_but_can_add_constraints():
    from agents.knowledge_decision import _narrow_scope
    base = {"tags": ["export", "reviewed"], "run_id": ["a", "b"]}
    with pytest.raises(ValueError):
        _narrow_scope(base, {"tags": ["export"]})
    assert _narrow_scope(base, {"tags": ["export", "reviewed", "csv"], "run_id": "a"}) == {
        "tags": ["export", "reviewed", "csv"], "run_id": "a"}


@pytest.mark.asyncio
async def test_derived_note_inherits_source_conditions_without_relabeling(tmp_path):
    from agents.knowledge_decision import run_knowledge_decision
    responses = [request("inspect_evidence"), request("write_knowledge_note", title="Export",
        body="Source-conditioned export observation.", ontology_type="KnowledgeClaim",
        source_ids=["current-analysis"]), request("publish_context", summary="Export observed.",
        source_ids=["current-analysis"], no_knowledge_reason="")]
    state, ctx, store, evidence = setup(tmp_path, responses)
    evidence[0]["applicability"] = {"material": "PLA", "protocol": "v2"}
    result = await run_knowledge_decision(state, ctx, store=store, evidence=evidence,
        scope={"applicability": {"material": "PLA"}})
    assert result["status"] == "accepted"
    assert store.search("", scope={"applicability": {"material": "PLA", "protocol": "v2"}})["hits"]


def test_research_context_preserves_markdown_source_classification():
    from knowledge.retrieval import retrieve_research_context
    result = retrieve_research_context(query="export", retrieval_result={"local_chunks": [{
        "source": "memory/note.md", "source_type": "markdown_knowledge",
        "trust_level": "derived", "text": "Export"}]})
    assert result["sources"][0]["source_type"] == "markdown_knowledge"
    assert result["sources"][0]["trust_level"] == "derived"
    from agents.knowledge_agent import _source_refs_from_retrieval
    typed = _source_refs_from_retrieval({"local_chunks": [{"chunk_id": "note-a",
        "source": "memory/note.md", "source_type": "markdown_knowledge", "trust_level": "derived"}]})
    assert typed[0].source_type == "experiment_memory"
    assert typed[0].trust_level == "derived"
