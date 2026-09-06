"""A late/reconnected GUI must receive every saved sample without device calls."""
import json

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.unit.test_lerobot_joint_telemetry import _action_event


@pytest.mark.asyncio
@pytest.mark.parametrize("initially_empty", [False, True])
async def test_late_open_and_reconnect_replay_all_samples_then_follow_live(tmp_path, monkeypatch, initially_empty):
    import app.main as main

    path = tmp_path / "motor_events.jsonl"
    rows = [{**_action_event(i + 1, 100 + i / 10), "padding": "x" * 4000} for i in range(700)]
    history = "".join(json.dumps(row) + "\n" for row in rows)
    path.write_text("" if initially_empty else history)
    session = {"session_id": "rollout-test", "workflow": "rollout", "status": "POLICY_ACTIVE"}
    monkeypatch.setattr(main, "_joint_telemetry_session_context", lambda: {"session": session, "log_path": path})
    monkeypatch.setattr(main, "_manipulation_runtime_view", lambda *args: {})

    class Socket:
        def __init__(self, append_live=False):
            self.samples = []
            self.append_live = append_live
            self.messages = 0

        async def accept(self):
            pass

        async def send_json(self, payload):
            self.messages += 1
            if payload["type"] in {"joint_history", "joint_samples"}:
                self.samples.extend(payload["samples"])
            elif payload["type"] == "joint_sample":
                self.samples.append(payload)
            if self.append_live and self.messages == 1:
                with path.open("a") as handle:
                    if initially_empty:
                        handle.write(history)
                    for i in range(700, 705):
                        handle.write(json.dumps(_action_event(i + 1, 100 + i / 10)) + "\n")
            if self.samples and self.samples[-1]["sequence"] == 705:
                raise WebSocketDisconnect()
            if self.messages > 10:
                raise AssertionError("Stream did not catch up to saved records")

    for append_live in (True, False):
        socket = Socket(append_live)
        await main.stream_lerobot_joint_telemetry(socket)
        assert [sample["sequence"] for sample in socket.samples] == list(range(1, 706))
        assert socket.samples[0]["elapsed_s"] == 0
        assert socket.samples[-1]["elapsed_s"] == pytest.approx(70.4)
        assert all(len(sample["actual_source"]) == 6 for sample in socket.samples)
