"""Source evidence must reach existing consumer decisions without authority changes."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest


def published_library(tmp_path):
    from knowledge.source_library import SourceLibrary
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "reference.md").write_text("# Reference\nAzure drift is 17.5 mm; reference only.")
    library = SourceLibrary(tmp_path / "library", inbox)
    library.scan()
    source_id = library.scan()["pending_ids"][0]
    extracted = library.extract(source_id)
    library.publish(source_id, [{"title": "Azure drift", "body": "Azure drift is 17.5 mm; reference only.",
        "category": "process-evidence", "ontology_type": "KnowledgeClaim", "tags": ["azure"],
        "applicability": {"variant": "Azure"},
        "source_block_ids": [b["block_id"] for b in extracted["blocks"]]}],
        model={"model": "unit-fixture"}, trace=[])
    return library, source_id


@pytest.mark.asyncio
async def test_knowledge_reads_sources_with_independent_scope_and_preserves_bo_citations(tmp_path):
    from agents.knowledge_decision import run_knowledge_decision
    from agents.bo_agent import BOAgent
    from knowledge.markdown_runtime import store_for
    from mcp_tools.tool_registry import ToolRegistry
    from mcp_tools.source_tools import register_source_tools
    from orchestrator.state import Mode, OrchestratorState, Stage
    library, source_id = published_library(tmp_path)
    note_id = library.search("Azure")["hits"][0]["record_id"]
    actions = [("inspect_evidence", {}), ("search_knowledge", {"query": "Azure", "corpus": "sources"}),
        ("read_knowledge", {"record_id": note_id}), ("publish_context", {
            "summary": "Azure drift is 17.5 mm; reference only.", "source_ids": [note_id],
            "no_knowledge_reason": "Existing source already covers the question."})]
    tools = ToolRegistry()
    register_source_tools(tools, lambda: library)
    class Context:
        force_real_llm_in_test = True
        async def complete(self, task_type, prompt, **kwargs):
            tool, arguments = actions.pop(0)
            return SimpleNamespace(text=json.dumps({"tool": tool, "arguments": arguments}), model="fixture")
    ctx = Context()
    ctx.tools = tools
    state = OrchestratorState(run_id="isolated-source-consumer", experiment_id="fixture", mode=Mode.TEST,
                              stage=Stage.KNOWLEDGE, active_goal="Find Azure reference")
    result = await run_knowledge_decision(state, ctx, store=store_for(project_root=tmp_path), evidence=[],
        scope={"run_id": state.run_id}, settings={"corpora": ["sources"], "source_scope": {"source_id": source_id}})
    assert result["status"] == "accepted"
    assert result["trace"][2]["observation"]["citation_id"] == note_id
    assert result["selected_knowledge"][0]["source_id"] == source_id
    assert "17.5" in result["summary"] and result["citations"]
    state.run_metadata["knowledge"] = result
    bo_context = BOAgent._knowledge_context_from_state(state)
    assert bo_context["selected_knowledge"] == result["selected_knowledge"]
    assert bo_context["citations"] == result["citations"]
    assert result["selected_knowledge"][0]["applicability"] == {"variant": "Azure"}


def test_shared_context_is_read_only_and_excludes_wrong_scope(tmp_path):
    from mcp_tools.tool_registry import ToolRegistry
    from mcp_tools.source_tools import register_source_tools, source_context
    library, _ = published_library(tmp_path)
    tools = ToolRegistry()
    register_source_tools(tools, lambda: library)
    ctx = SimpleNamespace(tools=tools)
    context = source_context(ctx, "Azure", scope={"applicability": {"variant": "Azure"}})
    assert context["authority"] == "reference_only" and context["citations"]
    assert "17.5" in context["notes"][0]["body"]
    assert source_context(ctx, "Azure", scope={"applicability": {"variant": "Amber"}})["notes"] == []
    assert tools.list_tools() == ["knowledge.sources.read", "knowledge.sources.search"]


def test_optional_source_read_race_and_unavailable_library_are_explicit(tmp_path, monkeypatch):
    from mcp_tools.tool_registry import ToolRegistry
    from mcp_tools.source_tools import register_source_tools, source_context
    library, _ = published_library(tmp_path)
    tools = ToolRegistry()
    register_source_tools(tools, lambda: library)
    ctx = SimpleNamespace(tools=tools)
    monkeypatch.setattr(library, "read", lambda *a, **kw: {"ok": False, "status": "not_found"})
    result = source_context(ctx, "Azure")
    assert result["status"] == "no_match" and not result["notes"] and not result["citations"]
    def unavailable(*a, **kw):
        raise OSError("Optional source storage unavailable")
    monkeypatch.setattr(library, "search", unavailable)
    result = source_context(ctx, "Azure")
    assert result["status"] == "unavailable" and not result["notes"]


def test_equipment_reference_envelope_is_bounded_with_full_detail_available(tmp_path, monkeypatch):
    from mcp_tools.tool_registry import ToolRegistry
    from mcp_tools.source_tools import register_source_tools, source_context
    library, _ = published_library(tmp_path)
    hit = library.search("Azure")["hits"][0]
    full = library.read(hit["record_id"])
    full["record"]["body"] = "한글 reference-only content. " * 10000
    full["record"]["citations"] *= 1000
    full["record"]["source_refs"] *= 1000
    monkeypatch.setattr(library, "read", lambda *a, **kw: deepcopy(full))
    tools = ToolRegistry()
    register_source_tools(tools, lambda: library)
    result = source_context(SimpleNamespace(tools=tools), "Azure")
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 12000
    assert result["status"] == "ready" and result["truncated"]
    assert result["notes"][0]["body_truncated"] and result["notes"][0]["citations_truncated"]
    assert result["notes"][0]["applicability"] == full["record"]["applicability"]
    assert library.read(hit["record_id"])["record"]["body"] == full["record"]["body"]


def test_source_context_budget_also_holds_for_normalization_and_error_metadata(monkeypatch):
    from mcp_tools.source_tools import source_context
    for extra in range(11800, 12010, 10):
        scope = {"applicability": {"condition": "x" * extra}}
        for failure in (False, True):
            class Library:
                def search(self, *a, **kw):
                    if failure:
                        raise OSError("Unavailable")
                    return {"hits": [], "scope": {**scope, "status": "ready"}}
            monkeypatch.setattr("mcp_tools.source_tools.source_library_for_context", lambda ctx: Library())
            result = source_context(None, "", scope=scope)
            assert len(json.dumps(result, ensure_ascii=False).encode()) <= 12000


@pytest.mark.asyncio
async def test_actual_equipment_workflow_receives_sources_and_keeps_single_execution(tmp_path, monkeypatch):
    from test_equipment_workflow_decision import Model, setup_flow
    from mcp_tools.source_tools import register_source_tools
    agent, state, tools, executed, _, _ = setup_flow(tmp_path, monkeypatch)
    library, source_id = published_library(tmp_path)
    register_source_tools(tools, lambda: library)
    state.active_goal = "Review Azure drift reference while following the configured workflow"
    state.run_metadata["knowledge_settings"] = {"source_scope": {"source_id": source_id}}
    model = Model(tools)
    result = await agent.run(state, model)
    assert result.success
    assert executed == ["prepare", "measure", "export"]
    assert len(model.calls) == 2
    for envelope, _ in model.calls:
        reference = envelope["source_knowledge"]
        assert reference["authority"] == "reference_only" and reference["citations"]
        assert "17.5" in reference["notes"][0]["body"]
        assert all("17.5" not in json.dumps(proposal) for proposal in envelope["tools"].values())
    def must_not_retrieve(*a, **kw):
        raise AssertionError("Cached workflow must not consult optional source evidence")
    monkeypatch.setattr("mcp_tools.source_tools.source_context", must_not_retrieve)
    repeated = await agent.run(deepcopy(state), model)
    assert repeated.success and repeated.data["equipment_workflow_cached"]
    assert executed == ["prepare", "measure", "export"] and len(model.calls) == 2
