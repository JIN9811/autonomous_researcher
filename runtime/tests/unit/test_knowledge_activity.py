from __future__ import annotations

import json
from pathlib import Path

from knowledge.activity import KnowledgeActivityReader


def _write_event(root: Path, payload: dict[str, object]) -> None:
    path = root / "events" / "2026" / "08" / "08" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def test_activity_reader_aggregates_recorded_counts_by_cycle(tmp_path: Path) -> None:
    ledger_root = tmp_path / "ledger"
    _write_event(
        ledger_root,
        {
            "event_id": "event:1",
            "run_id": "run-a",
            "cycle_id": "cycle-1",
            "occurred_at": "2026-08-08T01:00:00Z",
            "payload_summary": {
                "activity": {"collected": 4, "updated": 2, "retrieved": 1, "used": 1},
                "activity_consumers": ["orchestrator"],
            },
        },
    )
    _write_event(
        ledger_root,
        {
            "event_id": "event:2",
            "run_id": "run-a",
            "cycle_id": "cycle-2",
            "occurred_at": "2026-08-08T01:02:00Z",
            "payload_summary": {"activity": {"collected": 3, "updated": 5, "retrieved": 2, "used": 2}},
        },
    )
    _write_event(
        ledger_root,
        {
            "event_id": "event:other",
            "run_id": "run-b",
            "cycle_id": "cycle-1",
            "occurred_at": "2026-08-08T01:03:00Z",
            "payload_summary": {"activity": {"collected": 99, "updated": 99, "retrieved": 99, "used": 99}},
        },
    )

    result = KnowledgeActivityReader(ledger_root).aggregate(run_id="run-a", limit=20)

    assert result["schema"] == "knowledge_activity_series.v1"
    assert [item["cycle_id"] for item in result["cycles"]] == ["cycle-1", "cycle-2"]
    assert result["cycles"][0]["collected"] == 4
    assert result["cycles"][1]["used"] == 2
    assert result["totals"] == {"collected": 7, "updated": 7, "retrieved": 3, "used": 3}
    assert result["cycles"][0]["consumers"] == ["orchestrator"]


def test_activity_reader_bounds_cycles_and_skips_malformed_lines(tmp_path: Path) -> None:
    ledger_root = tmp_path / "ledger"
    path = ledger_root / "events" / "2026" / "08" / "08" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-json\n", encoding="utf-8")
    for index in range(1, 5):
        _write_event(
            ledger_root,
            {
                "event_id": f"event:{index}",
                "run_id": "run-a",
                "cycle_id": f"cycle-{index}",
                "occurred_at": f"2026-08-08T01:0{index}:00Z",
                "payload_summary": {"activity": {"collected": index}},
            },
        )

    result = KnowledgeActivityReader(ledger_root).aggregate(run_id="run-a", limit=2)

    assert [item["cycle_id"] for item in result["cycles"]] == ["cycle-3", "cycle-4"]
    assert result["available_cycle_count"] == 4
    assert result["malformed_line_count"] == 1
