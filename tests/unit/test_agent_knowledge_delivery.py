import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,want', [('cited', 'used'), ('invalid', 'unknown'), ('absent', 'unknown'), ('nonuse', 'excluded')])
@pytest.mark.parametrize('owner', ['orchestrator', 'design', 'specimen', 'vision', 'manipulation', 'equipment', 'analysis', 'bo', 'knowledge', 'guardian'])
async def test_validated_owner_output_finalizes_separate_reference_use(tmp_path, monkeypatch, owner, mode, want):
    from tests import knowledge_delivery_fixtures as fixtures
    from knowledge.context_service import KnowledgePrincipal
    original = fixtures.KnowledgeDeliveryTransport
    contexts = []
    class OutputTransport(original):
        def __init__(self, service, *, query_case):
            super().__init__(service, query_case=query_case)
            self.knowledge_principal = KnowledgePrincipal('fixture', run_ids=frozenset({'knowledge-matrix'}))
            contexts.append(self)
        async def complete(self, task_type, prompt, **kwargs):
            result = await super().complete(task_type, prompt, **kwargs)
            pack = fixtures.reference_pack_from_prompt(task_type, prompt)
            citation = pack['items'][0]['citation_id']
            note = {'cited': f'Review [{citation}].', 'invalid': f'Review [{citation}-invalid].',
                    'absent': 'Owner evidence only.', 'nonuse': '[reference_not_used:irrelevant]'}[mode]
            if task_type == 'guardian_reasoning': result.text = note
            else:
                value = json.loads(result.text)
                if task_type == 'knowledge_query':
                    if value['tool'] == 'publish_context': value['arguments']['summary'] = note
                else: value['reason'] = note
                result.text = json.dumps(value)
            return result
    monkeypatch.setattr(fixtures, 'KnowledgeDeliveryTransport', OutputTransport)
    await test_every_active_owner_actual_decision_prompt_carries_relevant_or_no_match_reference_only(tmp_path, owner, 'Design Agent', True)
    ctx = contexts[0]
    row = ctx.knowledge_service.delivery.query(ctx.knowledge_principal, '')['items'][0]
    assert row.get('use_status') == want, row
    assert bool(row['used_citation_ids']) is (mode == 'cited')
    if mode == 'nonuse': assert row['non_use_reason'] == 'irrelevant'


@pytest.mark.asyncio
@pytest.mark.parametrize('trusted', [False, True])
async def test_failing_retrieval_remains_unavailable_at_analysis_boundary(tmp_path, trusted):
    from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal
    from agents.analysis_decisions import decide
    from tests.knowledge_delivery_fixtures import KnowledgeDeliveryTransport
    service = KnowledgeContextService(tmp_path)
    def unavailable(*args, **kwargs): raise OSError('synthetic storage failure')
    service.query = unavailable
    ctx = KnowledgeDeliveryTransport(service, query_case='Design Agent')
    ctx.knowledge_principal = KnowledgePrincipal('fixture') if trusted else None
    result = await decide(ctx, 'summary', {'knowledge_query': 'Design Agent'}, {'review': None})
    assert result['knowledge_delivery']['stage'] == 'unavailable'
    if trusted:
        row = service.delivery.query(ctx.knowledge_principal, '')['items'][0]
        assert row['stage'] == 'unavailable'
        with pytest.raises(ValueError):
            service.delivery.record_delivered(ctx.knowledge_principal, row['receipt_id'])


class CapturingContext:
    """Synthetic transport used by Task 5 as well as the focused entrypoint tests."""

    def __init__(self, service):
        self.knowledge_service = service
        self.knowledge_principal = None
        self.active_backend = "vllm"
        self.backend_fallbacks = {"vllm": "vllm"}
        self.prompts = []

    async def complete(self, task_type, prompt, **kwargs):
        self.prompts.append((task_type, prompt, kwargs))
        return SimpleNamespace(text=json.dumps({
            "tool": "return_to_owner", "arguments": {"candidate": ""},
            "reason": "The supplied context needs owner review.", "evidence_refs": ["context:mission"],
        }), model="synthetic", raw={})


def test_reference_pack_is_injected_and_anonymous_delivery_is_inline(tmp_path):
    """Would fail if the adapter stopped adding the retrieved Wiki pack to a decision packet."""
    from agents.knowledge_context import build_reference_context, inject_reference_only
    from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal

    service = KnowledgeContextService(Path(__file__).resolve().parents[2], data_root=tmp_path)
    ctx = CapturingContext(service)
    packet = {"operation": "decide_orchestration", "context": {"goal": "Design Agent"}}
    reference = build_reference_context(ctx, consumer="orchestrator_agent", query="What does the Design Agent do?")
    enriched = inject_reference_only(packet, reference)

    assert enriched["context"]["reference_only"]["authority"] == "reference_only"
    assert enriched["context"]["reference_only"]["items"]
    assert reference["delivery"]["status"] == "inline_unpersisted"


def test_unknown_question_has_an_explicit_no_match_pack(tmp_path):
    """Would fail if an empty retrieval were silently omitted from the model decision boundary."""
    from agents.knowledge_context import build_reference_context
    from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal

    reference = build_reference_context(CapturingContext(KnowledgeContextService(Path(__file__).resolve().parents[2], data_root=tmp_path)),
        consumer="analysis_agent", query="nonexistenttokenonly")

    assert reference["pack"]["diagnostics"]["no_match"] is True
    assert reference["delivery"]["status"] == "no_match"


def test_mixed_possible_provider_route_excludes_private_memory_without_both_consents(tmp_path):
    """Would fail if remote consent alone leaked private text to a possible local fallback."""
    from agents.knowledge_context import build_reference_context
    from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal

    service = KnowledgeContextService(Path(__file__).resolve().parents[2], data_root=tmp_path)
    principal = KnowledgePrincipal(subject_id="synthetic", remote_model_consent=True, local_model_consent=False)
    service.memory.command(principal, action="propose", payload={"kind": "preference", "content": "synthetic preference",
        "source_refs": ["synthetic:source"], "scope": {"kind": "user"}, "explicit": True}, idempotency_key="propose")
    ctx = CapturingContext(service); ctx.knowledge_principal = principal; ctx.backend_fallbacks = {"vllm": "openai"}
    reference = build_reference_context(ctx, consumer="orchestrator_agent", query="synthetic preference", include_private=True)

    assert reference["pack"]["diagnostics"]["private_context_unavailable"] is True
    assert all(item["corpus"] != "private_memory" for item in reference["pack"]["items"])
    # Private-only match was withheld; this is genuinely no public match, not
    # a retrieved pack that was later excluded from delivery.
    assert reference["delivery"]["stage"] == "no_match"


@pytest.mark.asyncio
async def test_deterministic_equipment_entrypoint_never_marks_retrieved_context_delivered(tmp_path):
    """Would fail if a no-LLM branch advanced a delivery receipt before any prompt existed."""
    from agents.equipment_decision import decide_equipment
    from knowledge.context_service import KnowledgeContextService
    from orchestrator.state import Mode, OrchestratorState, Stage

    ctx = CapturingContext(KnowledgeContextService(Path(__file__).resolve().parents[2], data_root=tmp_path))
    ctx.force_real_llm_in_test = False
    state = OrchestratorState(run_id="synthetic-run", experiment_id="synthetic", mode=Mode.TEST, stage=Stage.EQUIPMENT)
    result = await decide_equipment(state, ctx, phase="select", context={"evidence_refs": ["task:configured"]},
        proposals={"execute_stacked_workflow": {"proposal_id": "synthetic"}})

    assert ctx.prompts == []
    assert result["knowledge_delivery"]["stage"] == "retrieved"
    assert result["knowledge_delivery"]["consumer_binding"] == "equipment_agent"
    assert result["knowledge_delivery"]["run_id"] == "synthetic-run"
    assert result["knowledge_delivery"]["loop_id"] == "0"
    assert result["knowledge_delivery"]["attempt_id"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("query,has_match", [("Design Agent", True), ("nonexistenttokenonly", False)])
@pytest.mark.parametrize("owner", ["orchestrator", "design", "specimen", "vision", "manipulation", "equipment", "analysis", "bo", "knowledge", "guardian"])
async def test_every_active_owner_actual_decision_prompt_carries_relevant_or_no_match_reference_only(tmp_path, owner, query, has_match):
    """Would fail if any active owner's real LLM entrypoint stopped carrying the frozen Wiki packet."""
    from knowledge.context_service import KnowledgeContextService
    from orchestrator.state import Mode, OrchestratorState, Stage
    from tests.knowledge_delivery_fixtures import KnowledgeDeliveryTransport, reference_pack_from_prompt

    service = KnowledgeContextService(Path(__file__).resolve().parents[2], data_root=tmp_path / owner / query)
    ctx = KnowledgeDeliveryTransport(service, query_case=query)
    state = OrchestratorState(run_id="knowledge-matrix", experiment_id="synthetic", mode=Mode.TEST,
        stage=Stage.DESIGN, active_goal=query, current_experiment_spec={"specimen_id": "s1", "candidate_id": "c1"})
    if owner == "orchestrator":
        from agents.orchestrator_decision import decide_orchestration
        await decide_orchestration(state, ctx, context={"scope": {}, "evidence": {"context:request": {}}, "request": {"message": query}, "settings": {"max_steps": 1}}, handlers={"defer": lambda _: {}})
    elif owner == "design":
        from agents.design_agent import DesignAgent
        await DesignAgent().run(state, ctx)
    elif owner == "specimen":
        from agents.specimen_decision import decide_specimen
        state.stage = Stage.SPECIMEN
        await decide_specimen(state, ctx, "s1", {"context:request": {}, "manufacturability:checks": {}}, lambda: None)
    elif owner == "vision":
        from agents.vision_decision import select_vision_tool
        state.stage = Stage.VISION
        await select_vision_tool(state, ctx, "pickup")
    elif owner == "manipulation":
        from agents.manipulation_decision import select_manipulation_tool
        state.stage = Stage.MANIPULATION
        await select_manipulation_tool(state, ctx, "lerobot.rollout.start", {"session_id": "s"})
    elif owner == "equipment":
        from agents.equipment_decision import decide_equipment
        state.stage = Stage.EQUIPMENT
        await decide_equipment(state, ctx, phase="select", context={"evidence_refs": ["task:configured"]}, proposals={"request_operator": {"proposal_id": "p"}})
    elif owner == "analysis":
        from agents.analysis_decisions import decide
        await decide(ctx, "summary", {"value": 1, "knowledge_query": query}, {"review": None})
    elif owner == "bo":
        from agents.bo_decision import run_bo_decision
        await run_bo_decision(context={"parameter_space": {"x": [0, 1]}, "goal": query}, ctx=ctx,
            settings={"strategy_control": "configured", "decision_max_calls": 1}, run_optimizer=lambda _: {})
    elif owner == "knowledge":
        from agents.knowledge_decision import run_knowledge_decision
        from knowledge.markdown_runtime import store_for
        state.stage = Stage.KNOWLEDGE
        await run_knowledge_decision(state, ctx, store=store_for(project_root=tmp_path / "markdown"),
            evidence=[{"id": "e", "source_ref": "synthetic:e", "content": {}}], scope={"run_id": state.run_id}, settings={"decision_max_steps": 2})
    else:
        from agents.guardian_agent import GuardianAgent
        from knowledge.failure_memory import FailureMemory
        ctx.failure_memory = FailureMemory()
        await GuardianAgent().run(state, ctx)
    assert ctx.prompts, owner
    pack = reference_pack_from_prompt(*ctx.prompts[0][:2])
    assert pack["authority"] == "reference_only"
    assert bool(pack["items"]) is has_match
