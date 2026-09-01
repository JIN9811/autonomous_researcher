from __future__ import annotations

from copy import deepcopy

from utils.equipment_skill_workflow import validate_editable_workflow, workflow_duration_bounds


def _workflow(*steps: dict) -> dict:
    return {
        "schema": "atr.equipment_skill.v1",
        "skill_id": "demo_skill",
        "version": "1.0.0",
        "steps": list(steps),
        "program_ids": [],
    }


def _step(step_id: str, action: dict, *, label: str = "Step", checkpoint_after: bool = False) -> dict:
    return {
        "step_id": step_id,
        "label": label,
        "action": action,
        "checkpoint_after": checkpoint_after,
    }


def test_validate_editable_workflow_normalizes_sequential_steps() -> None:
    workflow = _workflow(
        _step("step-001", {"action": "wait", "seconds": 2.0}, label="Pause"),
        _step(
            "step-002",
            {
                "action": "wait_until_image",
                "target": "ready",
                "timeout_s": 10.0,
                "poll_interval_s": 0.5,
                "required": True,
            },
            label="Ready",
            checkpoint_after=True,
        ),
    )

    result = validate_editable_workflow(workflow)

    assert result["ok"] is True
    assert result["issues"] == []
    assert [step["step_id"] for step in result["workflow"]["steps"]] == ["step-001", "step-002"]
    assert result["duration"] == {"minimum_s": 2.0, "maximum_s": 12.0}


def test_validate_editable_workflow_rejects_duplicate_ids_and_unbounded_waits() -> None:
    workflow = _workflow(
        _step("step-001", {"action": "wait", "seconds": 1.0}),
        _step("step-001", {"action": "wait_until_image", "target": "done", "timeout_s": 0}),
    )

    result = validate_editable_workflow(workflow)

    assert result["ok"] is False
    assert {issue["code"] for issue in result["issues"]} == {
        "DUPLICATE_STEP_ID",
        "WAIT_TIMEOUT_INVALID",
    }


def test_validate_editable_workflow_rejects_unknown_actions() -> None:
    result = validate_editable_workflow(_workflow(_step("step-001", {"action": "shell", "command": "dir"})))

    assert result["ok"] is False
    assert result["issues"][0]["code"] == "ACTION_UNSUPPORTED"


def test_validate_editable_workflow_accepts_input_language_action() -> None:
    result = validate_editable_workflow(
        _workflow(
            _step(
                "step-001",
                {
                    "action": "set_input_language",
                    "layout_id": "00000412",
                    "locale": "ko_KR",
                    "language": "ko",
                    "ime_mode": "native",
                    "typing_mode": "ko",
                },
            )
        )
    )

    assert result["ok"] is True
    assert result["issues"] == []


def test_validate_editable_workflow_accepts_only_bounded_paste_runtime_value() -> None:
    accepted = validate_editable_workflow(
        _workflow(_step("step-001", {"action": "paste_runtime_value", "key": "raw_csv_path"}))
    )
    accepted_filename = validate_editable_workflow(
        _workflow(_step("step-001", {"action": "paste_runtime_value", "key": "raw_csv_filename"}))
    )
    accepted_directory = validate_editable_workflow(
        _workflow(_step("step-001", {"action": "paste_runtime_value", "key": "raw_csv_directory"}))
    )
    unknown_key = validate_editable_workflow(
        _workflow(_step("step-001", {"action": "paste_runtime_value", "key": "arbitrary"}))
    )
    embedded_value = validate_editable_workflow(
        _workflow(
            _step(
                "step-001",
                {"action": "paste_runtime_value", "key": "raw_csv_path", "path": "C:/forbidden.csv"},
            )
        )
    )

    assert accepted["ok"] is True
    assert accepted_filename["ok"] is True
    assert accepted_directory["ok"] is True
    assert unknown_key["ok"] is False
    assert embedded_value["ok"] is False
    assert {issue["code"] for issue in unknown_key["issues"]} == {"RUNTIME_VALUE_KEY_INVALID"}
    assert {issue["code"] for issue in embedded_value["issues"]} == {"RUNTIME_VALUE_LITERAL_FORBIDDEN"}


def test_validate_editable_workflow_rejects_polling_slower_than_timeout() -> None:
    result = validate_editable_workflow(
        _workflow(
            _step(
                "step-001",
                {
                    "action": "wait_until_text",
                    "target": "complete",
                    "contains": "Complete",
                    "timeout_s": 2.0,
                    "poll_interval_s": 3.0,
                },
            )
        )
    )

    assert result["ok"] is False
    assert any(issue["code"] == "WAIT_POLL_INVALID" for issue in result["issues"])


def test_workflow_duration_bounds_include_fixed_and_until_waits() -> None:
    workflow = _workflow(
        _step("step-001", {"action": "wait", "seconds": 2}),
        _step("step-002", {"action": "wait_for_file", "pattern": "C:/out/*.csv", "timeout_s": 10}),
    )

    assert workflow_duration_bounds(workflow) == {"minimum_s": 2.0, "maximum_s": 12.0}


def test_validation_does_not_mutate_caller_workflow() -> None:
    workflow = _workflow(_step("step-001", {"action": "press", "key": "enter"}))
    original = deepcopy(workflow)

    validate_editable_workflow(workflow)

    assert workflow == original
