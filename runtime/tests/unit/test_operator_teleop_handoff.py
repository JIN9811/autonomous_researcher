from __future__ import annotations

import pytest

from utils.operator_teleop_handoff import (
    OperatorTeleopHandoffError,
    OperatorTeleopHandoffRegistry,
)


def _new(registry: OperatorTeleopHandoffRegistry) -> dict:
    return registry.create(
        run_id="run-1",
        cycle_index=3,
        specimen_id="specimen-3",
        candidate_id="candidate-3",
        materialization_evidence={"status": "confirmed", "fresh": True},
    )


def test_pending_handoff_is_bounded_refresh_safe_and_contains_popup_url():
    registry = OperatorTeleopHandoffRegistry()
    created = _new(registry)

    fetched = registry.status("run-1", created["handoff_token"])

    assert fetched["schema"] == "operator_teleop_handoff.v1"
    assert fetched["status"] == "pending_operator_teleop_handoff"
    assert fetched["cycle_index"] == 3
    assert fetched["specimen_id"] == "specimen-3"
    assert fetched["popup_url"].startswith("/lerobot?handoff_token=")
    assert "run_id=run-1" in fetched["popup_url"]


def test_confirmation_requires_matching_stopped_released_session_and_is_single_use():
    registry = OperatorTeleopHandoffRegistry()
    created = _new(registry)
    token = created["handoff_token"]
    bound = registry.bind_session(
        run_id="run-1", handoff_token=token, teleop_session_id="teleop-1"
    )
    assert bound["teleop_session_id"] == "teleop-1"

    with pytest.raises(OperatorTeleopHandoffError, match="TELEOP_SESSION_MISMATCH"):
        registry.confirm(
            run_id="run-1",
            handoff_token=token,
            teleop_session_id="teleop-other",
            teleop_evidence={"status": "STOPPED", "port_released": True, "camera_returned_to_vision": True},
            confirmed_by="operator",
        )

    with pytest.raises(OperatorTeleopHandoffError, match="TELEOP_SESSION_ACTIVE"):
        registry.confirm(
            run_id="run-1",
            handoff_token=token,
            teleop_session_id="teleop-1",
            teleop_evidence={"status": "TELEOP_ACTIVE"},
            confirmed_by="operator",
        )
    with pytest.raises(OperatorTeleopHandoffError, match="TELEOP_RESOURCES_NOT_RELEASED"):
        registry.confirm(
            run_id="run-1",
            handoff_token=token,
            teleop_session_id="teleop-1",
            teleop_evidence={"status": "STOPPED", "port_released": False, "camera_returned_to_vision": True},
            confirmed_by="operator",
        )

    confirmed = registry.confirm(
        run_id="run-1",
        handoff_token=token,
        teleop_session_id="teleop-1",
        teleop_evidence={
            "status": "STOPPED",
            "port_released": True,
            "camera_returned_to_vision": True,
            "teleop_started_at": "2026-09-04T01:00:00Z",
            "teleop_stopped_at": "2026-09-04T01:02:00Z",
        },
        confirmed_by="operator",
    )
    assert confirmed["status"] == "operator_confirmed"
    assert confirmed["teleop_session_id"] == "teleop-1"
    assert registry.event("run-1", token).is_set()
    with pytest.raises(OperatorTeleopHandoffError, match="TELEOP_HANDOFF_ALREADY_CONSUMED"):
        registry.confirm(
            run_id="run-1",
            handoff_token=token,
            teleop_session_id="teleop-1",
            teleop_evidence={"status": "STOPPED", "port_released": True, "camera_returned_to_vision": True},
            confirmed_by="operator",
        )


def test_wrong_identity_and_cancellation_fail_closed():
    registry = OperatorTeleopHandoffRegistry()
    created = _new(registry)
    token = created["handoff_token"]

    with pytest.raises(OperatorTeleopHandoffError, match="TELEOP_HANDOFF_NOT_FOUND"):
        registry.status("different-run", token)

    cancelled = registry.cancel_run("run-1", reason="operator_stop")
    assert cancelled[0]["status"] == "cancelled"
    assert cancelled[0]["failure_code"] == "TELEOP_HANDOFF_CANCELLED"
    assert registry.event("run-1", token).is_set()


def test_materialization_must_be_fresh_and_confirmed_before_handoff_creation():
    registry = OperatorTeleopHandoffRegistry()

    with pytest.raises(OperatorTeleopHandoffError, match="EXTERNAL_SPECIMEN_MATERIALIZATION_REQUIRED"):
        registry.create(
            run_id="run-1",
            cycle_index=1,
            specimen_id="specimen-1",
            candidate_id="candidate-1",
            materialization_evidence={"status": "not_checked", "fresh": False},
            require_materialization=True,
        )


def test_utm_verification_requires_fresh_evidence_and_matching_specimen_identity():
    registry = OperatorTeleopHandoffRegistry()
    created = _new(registry)
    token = created["handoff_token"]
    registry.bind_session(run_id="run-1", handoff_token=token, teleop_session_id="teleop-1")
    registry.confirm(
        run_id="run-1",
        handoff_token=token,
        teleop_session_id="teleop-1",
        teleop_evidence={
            "session_id": "teleop-1",
            "status": "STOPPED",
            "port_released": True,
            "camera_returned_to_vision": True,
        },
        confirmed_by="operator",
    )

    verified = registry.attach_vision_verification(
        run_id="run-1",
        handoff_token=token,
        vision_verification={
            "status": "confirmed",
            "detected": True,
            "fresh": True,
            "evidence_exists": False,
            "identity_matches": False,
        },
    )

    assert verified["status"] == "blocked"
    assert verified["failure_code"] == "UTM_VISION_VERIFICATION_FAILED"
