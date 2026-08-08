"""Read bounded per-cycle activity series from the durable Knowledge ledger."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ACTIVITY_KEYS = ("collected", "updated", "retrieved", "used")


class KnowledgeActivityReader:
    """Aggregate recorded Knowledge activity without introducing a second source of truth."""

    def __init__(self, ledger_root: Path) -> None:
        self.ledger_root = Path(ledger_root)

    def aggregate(self, *, run_id: str = "", limit: int = 20) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 100))
        cycles: dict[tuple[str, str], dict[str, Any]] = {}
        malformed = 0
        for path in sorted(self.ledger_root.glob("events/*/*/*/events.jsonl")):
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError):
                    malformed += 1
                    continue
                if not isinstance(event, dict):
                    malformed += 1
                    continue
                event_run_id = str(event.get("run_id") or "")
                if run_id and event_run_id != run_id:
                    continue
                summary = event.get("payload_summary") if isinstance(event.get("payload_summary"), dict) else {}
                activity = summary.get("activity") if isinstance(summary.get("activity"), dict) else {}
                if not activity:
                    continue
                cycle_id = str(event.get("cycle_id") or "cycle-unknown")
                key = (event_run_id, cycle_id)
                bucket = cycles.setdefault(
                    key,
                    {
                        "run_id": event_run_id,
                        "cycle_id": cycle_id,
                        "collected": 0,
                        "updated": 0,
                        "retrieved": 0,
                        "used": 0,
                        "consumers": [],
                        "event_count": 0,
                        "last_occurred_at": "",
                    },
                )
                for activity_key in ACTIVITY_KEYS:
                    bucket[activity_key] += _nonnegative_int(activity.get(activity_key))
                consumers = summary.get("activity_consumers") if isinstance(summary.get("activity_consumers"), list) else []
                bucket["consumers"] = sorted({*bucket["consumers"], *(str(item) for item in consumers if str(item).strip())})
                bucket["event_count"] += 1
                bucket["last_occurred_at"] = max(bucket["last_occurred_at"], str(event.get("occurred_at") or ""))

        ordered = sorted(cycles.values(), key=_activity_sort_key)
        available = len(ordered)
        visible = ordered[-bounded_limit:]
        totals = {key: sum(int(item[key]) for item in visible) for key in ACTIVITY_KEYS}
        selected_run_id = run_id or (visible[-1]["run_id"] if visible else "")
        return {
            "schema": "knowledge_activity_series.v1",
            "run_id": selected_run_id,
            "limit": bounded_limit,
            "available_cycle_count": available,
            "malformed_line_count": malformed,
            "cycles": visible,
            "totals": totals,
        }


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _activity_sort_key(item: dict[str, Any]) -> tuple[str, int, str]:
    cycle_id = str(item.get("cycle_id") or "")
    match = re.search(r"(\d+)(?!.*\d)", cycle_id)
    cycle_number = int(match.group(1)) if match else 10**9
    return str(item.get("run_id") or ""), cycle_number, str(item.get("last_occurred_at") or "")
