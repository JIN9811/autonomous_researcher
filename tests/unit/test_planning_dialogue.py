"""Human and automatic research dialogue share admission; no device effects."""
import json
from types import SimpleNamespace

import pytest

from app.bootstrap import load_runtime

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("handoff_no_external")]


def response(action, answer, updates=None, language="ko"):
    return SimpleNamespace(text=json.dumps({"action": action, "answer": answer,
        "updates": updates or [], "language": language}), model="fixture", raw={})


async def test_greeting_uses_model_and_does_not_start_design(monkeypatch):
    c = load_runtime()
    calls = []
    async def model(*, prompt):
        packet = json.loads(prompt)
        calls.append(packet["operation"])
        return SimpleNamespace(text="안녕하세요 연구원님. AX4LAB의 오케스트레이터입니다.\n\nHello, researcher. I’m AX4LAB’s orchestrator.", model="fixture", raw={}), "ok"
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    result = await c.bootstrap_live_orchestrator()
    assert result["ok"] is True
    assert calls == ["research_greeting"]
    assert "Hello" in c._planning_messages[-1]["content"]
    assert not c._planning_handoff_task


async def test_dialogue_collects_only_spoken_values_and_projects_each_change(monkeypatch):
    from app.planning_dialogue import ResearchDialogue
    c = load_runtime()
    c._bind_planning_session(None)
    d = ResearchDialogue(c)
    replies = iter([
        response("invite", "압축시험 패키지가 등록되어 있습니다. 실험 조건을 정해볼까요?"),
        response("collect", "어떤 성능을 개선하고 싶으신가요?"),
        response("collect", "재료와 시편 크기는 어떻게 할까요?", [{"field": "goal", "value": "에너지 흡수 개선", "source_quote": "에너지 흡수 개선"}]),
        response("collect", "구조는 무엇으로 할까요?", [{"field": "material", "value": "PLA", "source_quote": "PLA"}]),
        response("collect", "크기도 알려주세요.", [{"field": "material", "value": "PETG", "source_quote": "PETG"}]),
    ])
    async def model(**kwargs):
        return next(replies), "ok"
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    for message, intent in [("가능한 실험은?", "question"), ("좋아요", "confirm_pending"),
                            ("에너지 흡수 개선", "confirm_pending"), ("PLA", "confirm_pending"),
                            ("PETG로 바꿀게요", "confirm_pending")]:
        result = await d.turn(message, intent=intent)
        assert result["ok"] is True
    values = d.values()
    assert values == {"goal": "에너지 흡수 개선", "material": "PETG"}
    blocks = c._planning_setup_projection()["blocks"]
    assert any(b["draft_values"].get("material") == "PETG" for b in blocks)
    assert not c._planning_handoff_task


async def test_question_cannot_inject_values_or_execute(monkeypatch):
    from app.planning_dialogue import ResearchDialogue
    c = load_runtime()
    c._bind_planning_session(None)
    d = ResearchDialogue(c)
    async def model(**kwargs):
        return response("execute", "실행하겠습니다", [{"field": "material", "value": "PLA", "source_quote": "PLA"}]), "ok"
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    result = await d.turn("PLA가 뭔가요?", intent="question")
    assert result["ok"] is False
    assert d.values() == {}
    assert not c._planning_handoff_task


async def test_unspoken_values_and_raw_json_never_reach_chat(monkeypatch):
    from app.planning_dialogue import ResearchDialogue
    c = load_runtime()
    c._bind_planning_session(None)
    d = ResearchDialogue(c)
    async def model(**kwargs):
        return response("collect", '{"constraints":{"material":"PLA"}}',
            [{"field": "material", "value": "PLA", "source_quote": "PLA"}]), "ok"
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    result = await d.turn("좋아요", intent="confirm_pending")
    assert result["ok"] is False
    assert d.values() == {}
    assert all('"constraints"' not in m["content"] for m in c._planning_messages)


async def test_selected_block_edit_supplies_context_and_cannot_edit_another_input(monkeypatch):
    from app.planning_dialogue import ResearchDialogue
    c = load_runtime()
    c._bind_planning_session(None)
    d = ResearchDialogue(c)
    c._planning_setup_projection()
    selected = {"block_id": "selected", "revision": 1, "topic_key": "conversation.input.relative_density", "draft_values": {"relative_density": 0.2}}
    async def model(*, prompt):
        packet = json.loads(prompt)
        assert packet["selected_input"] == selected
        return response("collect", "값을 바꾸겠습니다.", [{"field": "cell_size_mm", "value": 0.3, "source_quote": "0.3"}]), "ok"
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    result = await d.turn("0.3으로 바꿔주세요", intent="change_setup", editing=selected)
    assert not result["ok"]
    assert d.values() == {}


@pytest.mark.parametrize("old_review", [False, True])
async def test_planning_request_never_executes_even_when_model_chooses_execute(monkeypatch, old_review):
    from app.planning_dialogue import ResearchDialogue
    c = load_runtime()
    c._bind_planning_session(None)
    d = ResearchDialogue(c)
    if old_review:
        d.pending = {"kind": "conversation", "pending_id": "old-review", "purpose": "run_review"}
    async def model(**kwargs):
        return response("execute", "시작하겠습니다."), "ok"
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    result = await d.turn("실험 계획을 세워보자", intent="start_run")
    assert not result["ok"]
    assert "consent" in d.last_error["reason"]
    assert not c._planning_handoff_task


async def test_new_human_package_conversation_clears_previous_test_policy(monkeypatch):
    from app.planning_dialogue import ResearchDialogue
    c = load_runtime()
    c._bind_planning_session(None)
    d = ResearchDialogue(c)
    d.test_policy = {"test_mode_autofill": True, "printer_test_path": "installed_printer"}
    d.test_bo_defaults = {"initial_design_size": 12, "cell_size_bounds_mm": [6, 9]}
    async def classify(*args, **kwargs):
        return {"intent": "question", "pending_id": None, "reason": "package question"}
    async def model(**kwargs):
        return response("invite", "등록된 실험을 계획해 볼까요?"), "ok"
    monkeypatch.setattr("app.controller.classify_chat_request", classify)
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    result = await c.planning_message(message="어떤 실험을 할 수 있나요?")
    assert result["ok"]
    assert d.test_policy == {}
    assert d.test_bo_defaults == {}
    assert d.pending["purpose"] == "begin_planning"


async def test_model_reconsiders_disallowed_execution_without_any_side_effect(monkeypatch):
    from app.planning_dialogue import ResearchDialogue
    c = load_runtime()
    c._bind_planning_session(None)
    d = ResearchDialogue(c)
    c._planning_setup_projection()
    calls = []
    async def model(*, prompt):
        packet = json.loads(prompt)
        calls.append(packet)
        assert "execute" not in packet["allowed_actions"]
        if len(calls) == 1:
            return response("execute", "시작합니다."), "ok"
        assert packet["correction"]
        return response("collect", "먼저 실험 목표와 재료를 알려주시겠어요?"), "ok"
    monkeypatch.setattr(c, "_complete_live_planning_prompt", model)
    result = await d.turn("실험 준비하자", intent="start_run")
    assert result["ok"]
    assert len(calls) == 2
    assert len(c._planning_messages) == 2
    assert not c._planning_handoff_task
    assert d.values() == {}
