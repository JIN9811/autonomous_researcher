"""Configured core-owner plans bind through pinned module contexts only."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from agents.core.guardian.agent import GuardianAgent
from agents.core.knowledge.agent import KnowledgeAgent
from knowledge.experiment_db import ExperimentDB
from knowledge.stores import JsonlKnowledgeStore
from orchestrator.state import Mode, OrchestratorState, Stage


def declaration(owner: str, **settings) -> dict:
    return {
        "schema": "ax4lab.owner_plan.v1",
        "id": f"{owner}_reference",
        "owner": owner,
        "version": "1.0.0",
        "contract_version": "1.0.0",
        "settings": settings,
    }


def state(stage: Stage) -> OrchestratorState:
    return OrchestratorState(
        run_id="configured-plan-run",
        experiment_id="configured-plan-experiment",
        mode=Mode.TEST,
        stage=stage,
        active_goal="exercise a configured owner plan",
        current_experiment_spec={
            "candidate_id": "candidate-1",
            "specimen_id": "specimen-1",
            "geometry_type": "lattice_bcc",
            "specimen_size_mm": [30.0, 30.0, 30.0],
            "cell_size_mm": 6.0,
            "wall_thickness_mm": 1.2,
            "expected_mass_g": 8.5,
            "expected_print_time_min": 60.0,
            "expected_objective_proxy_score": 0.72,
            "top_bottom_cap": True,
            "constraints": {
                "max_specimen_size_mm": [30.0, 30.0, 30.0],
                "utm_fixture_limit_mm": [40.0, 40.0, 60.0],
                "nozzle_diameter_mm": 0.4,
                "minimum_feature_size_mm": 0.8,
                "max_mass_g": 50.0,
                "max_print_time_min": 120.0,
                "require_flat_compression_faces": True,
            },
        },
        latest_analysis={"objective_score": 0.7, "uncertainty": 0.1},
    )


@pytest.mark.parametrize(
    ("owner", "mutation", "match"),
    [
        ("knowledge", lambda item: item.update(schema="wrong"), "schema"),
        ("knowledge", lambda item: item.update(owner="guardian"), "owner"),
        ("knowledge", lambda item: item.update(version=">=1.0.0"), "version"),
        ("knowledge", lambda item: item.update(contract_version="2.0.0"), "contract"),
        ("knowledge", lambda item: item.update(extra=True), "field|extra"),
        ("knowledge", lambda item: item["settings"].update(private_memory=True), "setting"),
        ("guardian", lambda item: item["settings"].update(disable_operator_stop=True), "setting"),
        ("guardian", lambda item: item.update(inputs={}), "field|extra"),
    ],
)
def test_owner_declaration_rejects_wrong_shape_owner_versions_and_policy(owner, mutation, match):
    agent = KnowledgeAgent() if owner == "knowledge" else GuardianAgent()
    value = declaration(owner)
    mutation(value)
    original = deepcopy(state(Stage.KNOWLEDGE if owner == "knowledge" else Stage.GUARDIAN).run_metadata)
    current = state(Stage.KNOWLEDGE if owner == "knowledge" else Stage.GUARDIAN)
    current.run_metadata = deepcopy(original)

    with pytest.raises(ValueError, match=match):
        agent.validate_plan_declaration(value, current)

    assert current.run_metadata == original


def test_declaration_validation_reuses_scope_rules_without_initializing_a_store(monkeypatch):
    from knowledge.markdown_memory import MarkdownKnowledgeStore

    monkeypatch.setattr(
        MarkdownKnowledgeStore,
        "__init__",
        lambda *_args, **_kwargs: pytest.fail("declaration validation initialized a store"),
    )

    with pytest.raises((TypeError, ValueError), match="unknown scope filters"):
        KnowledgeAgent().validate_plan_declaration(
            declaration("knowledge", scope={"unknown": "value"}),
            state(Stage.KNOWLEDGE),
        )


@pytest.mark.parametrize(
    "advisory_evidence_context",
    [
        {"trace": {"run_id": "private-run"}},
        {"authentication": {"password": "secret"}},
        {"reference": {"location": "/tmp/owner-plan-private-note.md"}},
        {"reference": {"address": "10.0.0.42"}},
        {"network": {"connections": ["lab-controller"]}},
        {"reference": {"session_id": "private-session"}},
        {"reference": {"sessionId": "private-session"}},
        {"reference": {"user_id": "private-user"}},
        {"reference": {"user-id": "private-user"}},
    ],
)
def test_guardian_declaration_rejects_nested_private_and_machine_local_reference_fields(
    advisory_evidence_context,
):
    with pytest.raises(ValueError, match="private|connection|machine-local"):
        GuardianAgent().validate_plan_declaration(
            declaration("guardian", advisory_evidence_context=advisory_evidence_context),
            state(Stage.GUARDIAN),
        )


def test_guardian_declaration_accepts_detached_generic_reference_context():
    value = declaration(
        "guardian",
        advisory_evidence_context={
            "reference_ids": ["wiki:guardian-role", "policy:safe-stop"],
            "purpose": "review",
            "notes": {"summary": "Operator handbook evidence"},
        },
    )

    validated = GuardianAgent().validate_plan_declaration(value, state(Stage.GUARDIAN))

    assert validated == value


class _KnowledgeContext:
    force_real_llm_in_test = False

    def __init__(self, module, artifact_run_root):
        self._module = deepcopy(module)
        self.artifact_run_root = str(artifact_run_root)
        self.experiment_db = ExperimentDB()
        self.rag = SimpleNamespace()

    def runtime_module_config(self):
        return deepcopy(self._module)


@pytest.mark.asyncio
async def test_real_knowledge_owner_receives_pinned_declared_settings_without_mutating_metadata(
    tmp_path, monkeypatch,
):
    import agents.core.knowledge.agent as module

    configured = declaration("knowledge", corpora=["markdown"], decision_max_steps=6)
    pinned_module = {"id": "knowledge", "handler": "agent.knowledge_agent", "owner_plan": configured}
    ctx = _KnowledgeContext(pinned_module, tmp_path / "runs")
    current = state(Stage.KNOWLEDGE)
    current.run_metadata["knowledge_settings"] = {
        "scope": {"applicability": {"material": "PLA"}},
        "decision_call_timeout_s": 42.0,
    }
    metadata_before = deepcopy(current.run_metadata)
    captured = {}

    monkeypatch.setattr(
        JsonlKnowledgeStore,
        "default",
        classmethod(lambda cls, project_root=None: cls(
            memory_root=tmp_path / "memory" / "knowledge", run_root=tmp_path / "runs",
        )),
    )

    async def controlled_decision(_state, _ctx, *, store, evidence, scope, settings=None):
        captured.update(scope=deepcopy(scope), settings=deepcopy(settings), evidence=deepcopy(evidence))
        return {
            "schema": "knowledge_decision.v1",
            "status": "accepted",
            "summary": "controlled configured decision",
            "scope": {"status": "valid", **deepcopy(scope)},
            "trace": [],
            "note_receipts": [],
            "selected_knowledge": [],
            "citations": [],
            "no_knowledge_reason": "controlled",
        }

    monkeypatch.setattr(module, "run_knowledge_decision", controlled_decision)
    configured["settings"]["decision_max_steps"] = 15

    result = await KnowledgeAgent().run(current, ctx)

    assert captured["settings"]["corpora"] == ["markdown"]
    assert captured["settings"]["decision_max_steps"] == 6
    assert captured["settings"]["decision_call_timeout_s"] == 42.0
    assert captured["scope"]["applicability"]["material"] == "PLA"
    assert current.run_metadata == metadata_before
    assert result.data["knowledge"]["owner_plan"] == {
        "schema": "ax4lab.owner_plan.v1",
        "id": "knowledge_reference",
        "owner": "knowledge",
        "version": "1.0.0",
        "contract_version": "1.0.0",
        "effective_settings": {
            "corpora": ["markdown"],
            "decision_call_timeout_s": 42.0,
            "decision_max_steps": 6,
            "scope": {"applicability": {"material": "PLA"}},
        },
    }


class _GuardianContext:
    def __init__(self, module):
        from knowledge.failure_memory import FailureMemory

        self._module = deepcopy(module)
        self.failure_memory = FailureMemory()
        self.tools = SimpleNamespace(call=lambda *_args, **_kwargs: {
            "printer": "ready", "camera": "ready", "robot": "ready", "utm": "ready",
        })
        self.prompts = []

    def runtime_module_config(self):
        return deepcopy(self._module)

    async def complete(self, task_type, user_prompt, **_kwargs):
        self.prompts.append((task_type, user_prompt))
        return SimpleNamespace(text="controlled guardian advisory")


@pytest.mark.asyncio
async def test_guardian_config_is_reference_only_in_the_original_single_advisory_call():
    configured = declaration(
        "guardian",
        advisory_evidence_context={"reference_ids": ["wiki:guardian-role"], "purpose": "review"},
    )
    ctx = _GuardianContext({
        "id": "guardian", "handler": "agent.guardian_agent", "owner_plan": configured,
    })
    current = state(Stage.GUARDIAN)
    metadata_before = deepcopy(current.run_metadata)

    result = await GuardianAgent().run(current, ctx)

    assert len(ctx.prompts) == 1
    assert ctx.prompts[0][0] == "guardian_reasoning"
    assert "wiki:guardian-role" in ctx.prompts[0][1]
    assert "reference_only" in ctx.prompts[0][1]
    assert result.data["guardian"]["decision"] == "continue"
    assert result.data["guardian"]["owner_plan"]["effective_settings"] == configured["settings"]
    assert current.run_metadata == metadata_before


@pytest.mark.asyncio
async def test_no_plan_guardian_result_keeps_the_exact_legacy_evidence_shape():
    ctx = _GuardianContext({"id": "guardian", "handler": "agent.guardian_agent"})

    result = await GuardianAgent().run(state(Stage.GUARDIAN), ctx)

    assert "owner_plan" not in result.data["guardian"]
    assert len(ctx.prompts) == 1
