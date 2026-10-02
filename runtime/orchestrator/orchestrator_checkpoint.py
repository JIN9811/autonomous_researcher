"""Once-only runtime handoff records."""
from copy import deepcopy
import json


def handoff_checkpoint(metadata: dict, key: str, *, action: str, payload: dict | None = None) -> dict:
    """Reserve/hold/consume a JSON result without ever reopening a consumed effect.

    The synchronous mutation is atomic within the controller's serialized event
    loop. Persistence follows the existing state/archive boundary, not a second
    storage or execution system. ``prepare`` without payload explicitly resumes
    review of a deferred result, retaining its completed-owner payload.
    """
    if not isinstance(key, str) or not key or action not in {"read", "prepare", "defer", "consume"}:
        raise ValueError("Invalid checkpoint key or action")
    if payload is not None:
        if not isinstance(payload, dict):
            raise ValueError("Checkpoint payload must be a JSON object")
        json.dumps(payload, allow_nan=False)
        payload = deepcopy(payload)
    records = metadata.setdefault("orchestrator_checkpoints", {})
    record = records.get(key)
    consume_now = False
    if action == "prepare" and (record or {}).get("status") != "consumed":
        record = records.setdefault(key, {"payload": {}, "revision": 0})
        if payload is not None:
            record["payload"].update(payload)
        record.update(status="prepared", revision=record["revision"] + 1)
    elif action == "defer" and record and record.get("status") != "consumed":
        record.update(status="deferred", wait=payload or {}, revision=record["revision"] + 1)
    elif action == "consume" and record and record.get("status") == "prepared":
        record.update(status="consumed", revision=record["revision"] + 1)
        consume_now = True
    return {**deepcopy(record or {}), "consume_now": consume_now}
