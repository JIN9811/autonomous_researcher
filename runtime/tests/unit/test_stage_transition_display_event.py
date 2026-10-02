from app.controller import MainController


def test_stage_transition_remains_trace_only_and_attention_survives_compaction():
    controller = MainController.__new__(MainController)
    event = controller._compact_event_for_buffer({
        "event_id": "transition-1", "run_id": "run-1",
        "event_type": "stage_transition", "type": "edge.traversed",
        "payload": {"from_stage": "design", "to_stage": "specimen", "large_unrelated": [1, 2, 3]},
    })
    assert event["payload"] == {"from_stage": "design", "to_stage": "specimen"}
    payload = {"run_id": "run-1", "agent_id": "specimen", "attention_id": "run-1:1:print",
               "checkpoint": "print_started", "view_action": "printer_video", "loop_index": 1,
               "presentation_only": True}
    event = controller._compact_event_for_buffer({"event_type": "agent.attention_requested", "payload": payload})
    assert event["payload"] == payload
