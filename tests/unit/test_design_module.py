"""Behavior contracts for the first code-registered agent module."""
from dataclasses import replace

import pytest

from agents.design_agent import DesignAgent
from agents.registry import AgentRegistry


def test_module_registration_preserves_existing_agent_identity():
    from agents.design.module import DESIGN_MODULE

    registry = AgentRegistry()
    registry.register_module(DESIGN_MODULE)
    assert type(registry.get("design_agent")) is DesignAgent
    assert registry.get_module("design") is DESIGN_MODULE
    description = registry.get_module("design").describe()
    assert description["handler"] == "agent.design_agent"
    assert description["configuration"]["setup_write_enabled"] is False
    assert description["storage"]["archive_owner"] == "design_agent"
    assert description["frontend"]["asset_url"] == "/module-assets/design/live_report.js"


def test_graph_activation_removes_access_but_retains_catalog_and_instance():
    from agents.design.module import DESIGN_MODULE

    registry = AgentRegistry()
    registry.register_module(DESIGN_MODULE)
    original = registry.get("design_agent")
    active = {"design_agent"}
    registry.bind_activation(lambda: active)
    active.clear()
    with pytest.raises(KeyError, match="inactive"):
        registry.get("design_agent")
    assert "design_agent" not in registry.active_names()
    assert "design_agent" in registry.names()  # required for IDE re-add validation
    assert registry.module_for_agent("design_agent") is DESIGN_MODULE
    active.add("design_agent")
    assert registry.get("design_agent") is original


def test_installed_discovery_recovers_design_without_a_bootstrap_specific_import():
    from agents.module_discovery import discover_agent_modules

    modules = discover_agent_modules()
    assert len([module for module in modules if module.module_id == "design"]) == 1
    assert next(module for module in modules if module.module_id == "design").agent_name == "design_agent"


def test_duplicate_or_wrong_factory_never_partially_registers():
    from agents.design.module import DESIGN_MODULE

    registry = AgentRegistry()
    registry.register_module(DESIGN_MODULE)
    original = registry.get("design_agent")
    with pytest.raises(ValueError):
        registry.register_module(DESIGN_MODULE)
    assert registry.get("design_agent") is original
    conflicting = replace(DESIGN_MODULE, module_id="another")
    with pytest.raises(ValueError):
        registry.register_module(conflicting)
    assert registry.get_module("another") is None
    bad = AgentRegistry()
    with pytest.raises(ValueError):
        bad.register_module(replace(DESIGN_MODULE, agent_name="not_design"))
    assert bad.names() == []
    assert bad.get_module("design") is None


def test_public_description_is_detached_from_registered_contract():
    from agents.design.module import DESIGN_MODULE

    descriptor = DESIGN_MODULE.describe()
    descriptor["storage"]["archive_owner"] = "another_agent"
    assert DESIGN_MODULE.describe()["storage"]["archive_owner"] == "design_agent"
    assert "factory" not in descriptor


def test_module_frontend_is_declared_as_python_package_data():
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text())
    patterns = config["tool"]["setuptools"]["package-data"]["agents.design"]
    assets = {path for pattern in patterns for path in (root / "agents/design").glob(pattern)}
    assert root / "agents/design/frontend/live_report.js" in assets


def test_legacy_replacement_does_not_leave_a_stale_module_binding():
    from agents.design.module import DESIGN_MODULE

    registry = AgentRegistry()
    registry.register_module(DESIGN_MODULE)
    replacement = DesignAgent()
    registry.register(replacement)
    assert registry.get("design_agent") is replacement
    assert registry.get_module("design") is None
    assert registry.modules() == ()


def test_report_projection_keeps_precedence_and_blocked_evidence():
    from agents.design.presentation import project_design_report

    actual = {"status": "blocked", "candidate_generation": {"candidate_count": 0},
              "candidate_evaluation": {"status": "unassessed"},
              "handoff_to_specimen": {"required_fields_present": False},
              "decision_register": [{"action": "return_to_owner"}]}
    screen = {"schema": "design_agent_report.v1", "status": "blocked"}
    result = project_design_report(
        {"design_report": actual, "latest_design_agent_report": screen},
        {"design_report": {"status": "stale"}})
    assert result["design_report"] == actual
    assert result["design_agent_report"] == screen
    assert result["role_specific"]["candidate_board"]["candidate_count"] == 0
    assert result["role_specific"]["handoff_packet"] == {"required_fields_present": False}
    assert result["decisions"] == [{"action": "return_to_owner"}]
    assert result["metrics"] == {"status": "unassessed"}


def test_report_projection_handles_missing_and_payload_only_reports():
    from agents.design.presentation import project_design_report

    empty = project_design_report({}, {})
    assert empty == {"role_specific": {}, "decisions": [], "metrics": {},
                     "design_report": None, "design_agent_report": None}
    payload = {"design_report": {"candidate_generation": {"valid_count": 2}},
               "design_agent_report": {"schema": "design_agent_report.v1"}}
    result = project_design_report({"design_report": "invalid"}, payload)
    assert result["design_report"] == payload["design_report"]
    assert result["role_specific"]["candidate_board"]["valid_count"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("loop_count", [0, 1])
async def test_registered_design_has_same_output_and_state_as_legacy_entry(loop_count, monkeypatch):
    from datetime import datetime, timezone
    from agents.design import agent as implementation
    from agents.design.module import DESIGN_MODULE
    from orchestrator.state import Mode, OrchestratorState, Stage
    from tests.unit.test_design_agent import _DeterministicCtxStub

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 13, tzinfo=timezone.utc)

    monkeypatch.setattr(implementation, "datetime", FixedClock)

    registry = AgentRegistry()
    registry.register_module(DESIGN_MODULE)
    state = OrchestratorState(run_id="module-compat", experiment_id="synthetic",
                              mode=Mode.TEST, stage=Stage.DESIGN, loop_count=loop_count)
    other = state.model_copy(deep=True)
    direct = await DesignAgent().run(state, _DeterministicCtxStub())
    modular = await registry.get("design_agent").run(other, _DeterministicCtxStub())
    # The clock is fixed so both complete payloads, including decision timestamps, are comparable.
    assert modular.success == direct.success
    assert modular.summary == direct.summary
    assert modular.data["experiment_spec"] == direct.data["experiment_spec"]
    assert modular.data["design_candidate"] == direct.data["design_candidate"]
    assert modular.data == direct.data
    assert other.model_dump() == state.model_dump()


@pytest.mark.asyncio
async def test_registered_module_preserves_two_loop_model_handoff_and_archive(tmp_path):
    import json
    from agents.design.module import DESIGN_MODULE
    from tests.unit.test_design_decision import ModelContext, request, state_for_test
    from utils.agent_artifact_archive import list_executions

    registry = AgentRegistry()
    registry.register_module(DESIGN_MODULE)
    state = state_for_test()
    state.run_id = "module-archive-verification"
    for loop in (0, 1):
        state.loop_count = loop
        cid = f"cand-{loop + 1}-01"
        ctx = ModelContext([request("inspect_candidate", cid), request("accept_candidate", cid)])
        ctx.artifact_run_root = tmp_path
        result = await registry.get("design_agent").run(state, ctx)
        assert result.success
        assert len(ctx.prompts) == 2
        assert result.data["handoff_packet"]["experiment_spec"]["candidate_id"] == cid
    entries = list_executions(tmp_path / state.run_id)
    assert len(entries) == 2
    assert {item["loop_index"] for item in entries} == {0, 1}
    assert all(item["status"] == "completed" and item["agent"] == "design_agent" for item in entries)
    saved = [json.loads((tmp_path / state.run_id / item["result_path"]).read_text()) for item in entries]
    assert {item["data"]["design_decision"]["loop_number"] for item in saved} == {1, 2}
