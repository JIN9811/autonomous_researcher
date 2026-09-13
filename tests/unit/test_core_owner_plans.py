"""Plan-ready queries must remain detached from owner execution and state."""

from __future__ import annotations

from copy import deepcopy

import pytest

from agents.core.guardian.agent import GuardianAgent
from agents.core.knowledge.agent import KnowledgeAgent
from orchestrator.state import Mode, OrchestratorState, Stage


def _state(stage: Stage) -> OrchestratorState:
    state = OrchestratorState(
        run_id="plan-run",
        experiment_id="plan-experiment",
        mode=Mode.TEST,
        stage=stage,
        active_goal="keep the current guarded research flow",
        current_experiment_objective={
            "objective_id": "compression-performance",
            "objective_hash": "sha256:objective-1",
        },
    )
    state.run_metadata["knowledge_settings"] = {
        "scope": {"applicability": {"material": "PLA"}},
        "corpora": ["markdown", "sources"],
        "source_scope": {"category": "standard"},
        "decision_call_timeout_s": 45.0,
        "decision_max_steps": 6,
    }
    state.run_metadata["guardian_gates"] = [{
        "gate_id": "gate-1", "decision": "allow", "reason_code": "OK",
    }]
    return state


@pytest.mark.parametrize(
    "agent,state",
    [
        (KnowledgeAgent(), _state(Stage.KNOWLEDGE)),
        (GuardianAgent(), _state(Stage.GUARDIAN)),
    ],
)
def test_resolve_and_validate_plan_are_detached_read_only_queries(agent, state):
    """Mutating a returned snapshot or validating it must never write run metadata."""
    before = deepcopy(state.run_metadata)

    snapshot = agent.resolve_plan(state)
    validated = agent.validate_plan(snapshot, state)
    snapshot["settings"]["caller_edit"] = True
    snapshot["inputs"]["caller_edit"] = True

    assert state.run_metadata == before
    assert validated["owner"] in {"knowledge", "guardian"}
    assert validated["version"] == "1.0.0"
    assert "caller_edit" not in validated["settings"]
    assert "caller_edit" not in validated["inputs"]


def test_knowledge_default_plan_preserves_exact_existing_settings_and_effective_applicability():
    """Adding speculative defaults would change the payload consumed by Knowledge."""
    state = _state(Stage.KNOWLEDGE)
    expected_settings = deepcopy(state.run_metadata["knowledge_settings"])

    snapshot = KnowledgeAgent().resolve_plan(state)

    assert snapshot["settings"] == expected_settings
    assert snapshot["inputs"]["applicability"] == {
        "material": "PLA",
        "objective_id": "compression-performance",
        "objective_hash": "sha256:objective-1",
    }
    assert set(snapshot["settings"]) == set(expected_settings)


def test_knowledge_current_snapshot_preserves_ignored_legacy_metadata_but_proposal_rejects_it():
    """Plan strictness must not turn an ignored runtime annotation into a new run failure."""
    state = _state(Stage.KNOWLEDGE)
    state.run_metadata["knowledge_settings"]["legacy_annotation"] = {"display": "kept"}

    snapshot = KnowledgeAgent().resolve_plan(state)

    assert snapshot["settings"]["legacy_annotation"] == {"display": "kept"}
    with pytest.raises(ValueError, match="Unsupported Knowledge setting"):
        KnowledgeAgent().validate_plan({
            "owner": "knowledge", "version": "1.0.0", "settings": snapshot["settings"],
        }, state)


def test_knowledge_current_snapshot_and_proposal_share_supported_validation_rules():
    state = _state(Stage.KNOWLEDGE)
    state.run_metadata["knowledge_settings"]["corpora"] = ["private_memory"]

    with pytest.raises(ValueError, match="Unsupported Knowledge corpus"):
        KnowledgeAgent().resolve_plan(state)
    with pytest.raises(ValueError, match="Unsupported Knowledge corpus"):
        KnowledgeAgent().validate_plan({
            "owner": "knowledge", "version": "1.0.0",
            "settings": {"corpora": ["private_memory"]},
        }, _state(Stage.KNOWLEDGE))


def test_knowledge_source_scope_validation_matches_selected_corpora():
    ignored = _state(Stage.KNOWLEDGE)
    ignored.run_metadata["knowledge_settings"] = {
        "corpora": ["markdown"], "source_scope": ["legacy", "ignored"],
    }
    selected = _state(Stage.KNOWLEDGE)
    selected.run_metadata["knowledge_settings"] = {
        "corpora": ["sources"], "source_scope": ["invalid", "when-selected"],
    }

    snapshot = KnowledgeAgent().resolve_plan(ignored)
    proposal = KnowledgeAgent().validate_plan({
        "owner": "knowledge", "version": "1.0.0", "settings": snapshot["settings"],
    }, ignored)

    assert proposal["settings"]["source_scope"] == ["legacy", "ignored"]
    with pytest.raises(ValueError, match="source_scope"):
        KnowledgeAgent().resolve_plan(selected)
    with pytest.raises(ValueError, match="source_scope"):
        KnowledgeAgent().validate_plan({
            "owner": "knowledge", "version": "1.0.0", "settings": selected.run_metadata["knowledge_settings"],
        }, selected)


@pytest.mark.parametrize(
    ("scope", "error"),
    [
        ({"unsupported_scope_filter": "x"}, "unknown scope filters"),
        ({"status": 7}, "scope.status must be a string or list of strings"),
        ({"applicability": []}, "applicability must be a mapping"),
    ],
)
def test_knowledge_plan_queries_reuse_markdown_scope_rules_without_initializing_store(
    monkeypatch, scope, error,
):
    from knowledge.markdown_memory import MarkdownKnowledgeStore

    def fail_store_initialization(*_args, **_kwargs):
        raise AssertionError("plan validation must not initialize the Markdown store")

    monkeypatch.setattr(MarkdownKnowledgeStore, "__init__", fail_store_initialization)
    state = _state(Stage.KNOWLEDGE)
    state.run_metadata["knowledge_settings"] = {"corpora": ["markdown"], "scope": scope}

    with pytest.raises((TypeError, ValueError), match=error):
        KnowledgeAgent().resolve_plan(state)
    with pytest.raises((TypeError, ValueError), match=error):
        KnowledgeAgent().validate_plan({
            "owner": "knowledge",
            "version": "1.0.0",
            "settings": {"corpora": ["markdown"], "scope": scope},
        }, _state(Stage.KNOWLEDGE))


def test_knowledge_validated_proposal_resolves_inputs_from_proposed_settings():
    """Returning current applicability for a changed proposal would validate a contradictory snapshot."""
    state = _state(Stage.KNOWLEDGE)
    proposal = KnowledgeAgent().resolve_plan(state)
    proposal.pop("inputs")
    proposal["settings"] = {
        **proposal["settings"],
        "scope": {"applicability": {"material": "PETG"}},
    }

    validated = KnowledgeAgent().validate_plan(proposal, state)

    assert validated["settings"]["scope"]["applicability"] == {"material": "PETG"}
    assert validated["inputs"]["applicability"]["material"] == "PETG"


@pytest.mark.parametrize(
    "proposal,match",
    [
        ({"owner": "guardian", "version": "1.0.0", "settings": {}}, "owner"),
        ({"owner": "knowledge", "version": "2.0.0", "settings": {}}, "version"),
        ({"owner": "knowledge", "version": "1.0.0", "settings": {"write_private_memory": True}}, "setting"),
        ({"owner": "knowledge", "version": "1.0.0", "settings": {"corpora": ["private_memory"]}}, "corpus"),
    ],
)
def test_knowledge_plan_rejects_unsupported_owner_version_or_permission_widening(proposal, match):
    """A proposal must not silently switch owner/version or widen corpus authority."""
    state = _state(Stage.KNOWLEDGE)
    before = deepcopy(state.run_metadata)

    with pytest.raises(ValueError, match=match):
        KnowledgeAgent().validate_plan(proposal, state)

    assert state.run_metadata == before


@pytest.mark.parametrize(
    "proposal",
    [
        {"disable_operator_stop": True},
        {"owner": "guardian", "version": "1.0.0", "settings": {"disable_operator_stop": True}},
        {"owner": "guardian", "version": "1.0.0", "settings": {"risk_threshold": 0.99}},
        {"owner": "guardian", "version": "9.0.0", "settings": {}},
    ],
)
def test_guardian_plan_rejects_gate_disabling_and_threshold_overrides(proposal):
    """Plan inspection must never become a path around deterministic stop policy."""
    state = _state(Stage.GUARDIAN)
    before = deepcopy(state.run_metadata)

    with pytest.raises(ValueError):
        GuardianAgent().validate_plan(proposal, state)

    assert state.run_metadata == before


def test_guardian_plan_accepts_only_detached_optional_advisory_context():
    """Advisory evidence may be checked without changing mandatory policy inputs."""
    state = _state(Stage.GUARDIAN)
    before = deepcopy(state.run_metadata)

    validated = GuardianAgent().validate_plan({
        "owner": "guardian",
        "version": "1.0.0",
        "settings": {"advisory_evidence_context": {"reference_ids": ["wiki:guardian-role"]}},
    }, state)

    assert validated["settings"] == {
        "advisory_evidence_context": {"reference_ids": ["wiki:guardian-role"]},
    }
    assert validated["inputs"]["operator_stop"]["safe_stop_requested"] is False
    assert state.run_metadata == before


def test_plan_contract_is_serializable_detached_and_describes_authority_boundaries():
    """Callers need an inspectable contract without mutable owner internals."""
    import json

    for agent in (KnowledgeAgent(), GuardianAgent()):
        first = agent.plan_contract()
        encoded = json.dumps(first, allow_nan=False)
        first["authority_boundaries"].append("caller mutation")
        second = agent.plan_contract()

        assert "caller mutation" not in second["authority_boundaries"]
        assert second["schema"] == "ax4lab.owner_plan_contract.v1"
        assert "activation" in encoded.lower()
