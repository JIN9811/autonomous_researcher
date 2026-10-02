"""Durable, revisioned state for a planning session's experimental setup."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any
from uuid import uuid4


_PATH_LOCKS: dict[Path, RLock] = {}
_PATH_LOCKS_GUARD = RLock()


class SetupConflict(Exception):
    """A request does not match the current setup scope or revision."""


class SetupValidationError(Exception):
    """Persisted or supplied setup data does not satisfy the small store contract."""


def atomic_write_json(path: Path, payload: dict) -> None:
    """Atomically replace *path* with JSON after syncing the temporary file."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


class SetupStore:
    """A JSON-backed store; it records state only and never invokes an owner."""

    _FILE_NAME = "experimental_setup.json"

    def __init__(self, root: Path, session_id: str):
        self._root = Path(root)
        self._path = self._root / self._FILE_NAME
        self._lock_path = self._root / ".experimental_setup.lock"
        self._session_id = self._required_text(session_id, "session_id")
        with _PATH_LOCKS_GUARD:
            self._lock = _PATH_LOCKS.setdefault(self._path.resolve(), RLock())
        with self._lock, self._file_lock():
            if self._path.exists():
                self._state = self._load()
            else:
                self._state = self._empty_state()
                atomic_write_json(self._path, self._state)

    def ensure_block(self, topic_key: str, owner: str | list[str], values: dict) -> dict:
        topic_key = self._required_text(topic_key, "topic_key")
        owners = self._owners(owner)
        values = self._json_dict(values, "values")
        with self._lock, self._file_lock():
            self._refresh()
            existing = next((block for block in self._state["blocks"] if block["topic_key"] == topic_key), None)
            if existing is not None:
                return self._result(
                    block=existing,
                    block_id=existing["block_id"],
                    block_revision=existing["revision"],
                )

            def change(candidate: dict) -> dict:
                block = {
                    "block_id": str(uuid4()),
                    "topic_key": topic_key,
                    "owners": owners,
                    "revision": 1,
                    "draft_values": values,
                    "confirmed_values": None,
                    "effective_values": {},
                    "agreement_status": "draft",
                    "application_status": "not_applied",
                    "receipts": {},
                    "proposal_ids": [],
                    "current_draft_proposal_id": None,
                }
                candidate["blocks"].append(block)
                return {"block": block, "block_id": block["block_id"], "block_revision": block["revision"]}

            return self._mutate(change, "block_created", {"topic_key": topic_key})

    def propose(self, block_id: str, base_revision: int, values: dict, request_id: str) -> dict:
        block_id = self._required_text(block_id, "block_id")
        request_id = self._required_text(request_id, "request_id")
        values = self._json_dict(values, "values")
        payload = {"op": "propose", "block_id": block_id, "base_revision": base_revision, "values": values}
        with self._lock, self._file_lock():
            self._refresh()
            replay = self._request_replay(request_id, payload)
            if replay is not None:
                return replay
            block = self._block(self._state, block_id)
            self._require_revision(block, base_revision)

            def change(candidate: dict) -> dict:
                changed = self._block(candidate, block_id)
                changed["revision"] += 1
                proposal = {
                    "proposal_id": str(uuid4()),
                    "block_id": block_id,
                    "base_revision": base_revision,
                    "revision": changed["revision"],
                    "values": values,
                    "status": "draft",
                    "history": [{"event": "proposed", "values": values}],
                }
                candidate["proposals"][proposal["proposal_id"]] = proposal
                changed["proposal_ids"].append(proposal["proposal_id"])
                changed["current_draft_proposal_id"] = proposal["proposal_id"]
                changed["draft_values"] = values
                changed["agreement_status"] = "draft"
                return {
                    "proposal": proposal,
                    "proposal_id": proposal["proposal_id"],
                    "block_id": block_id,
                    "block_revision": changed["revision"],
                }

            return self._mutate(change, "proposal_created", {"block_id": block_id}, request_id, payload)

    def confirm(self, proposal_id: str, expected_revision: int, request_id: str, target: str,
                *, expected_store_revision: int | None = None) -> dict:
        proposal_id = self._required_text(proposal_id, "proposal_id")
        request_id = self._required_text(request_id, "request_id")
        target = self._required_text(target, "target")
        payload = {"op": "confirm", "proposal_id": proposal_id, "expected_revision": expected_revision, "target": target}
        with self._lock, self._file_lock():
            self._refresh()
            replay = self._request_replay(request_id, payload)
            if replay is not None:
                return replay
            if expected_store_revision is not None and self._state["revision"] != expected_store_revision:
                raise SetupConflict("stale store revision")
            proposal = self._proposal(self._state, proposal_id)
            block = self._block(self._state, proposal["block_id"])
            self._require_revision(block, expected_revision)
            if proposal["status"] != "draft" or block.get("current_draft_proposal_id") != proposal_id:
                raise SetupConflict("proposal is no longer a draft")
            if any(r.get("status") == "applying" for r in block["receipts"].values()):
                raise SetupConflict("application is still in flight")

            def change(candidate: dict) -> dict:
                changed_proposal = self._proposal(candidate, proposal_id)
                changed_block = self._block(candidate, changed_proposal["block_id"])
                changed_block["revision"] += 1
                changed_proposal["status"] = "confirmed"
                changed_proposal["target"] = target
                changed_proposal["history"].append({"event": "confirmed", "target": target})
                changed_block["confirmed_values"] = deepcopy(changed_proposal["values"])
                changed_block["agreement_status"] = "confirmed"
                changed_block["application_status"] = "scheduled" if target == "next_run" else "not_applied"
                changed_block["receipts"] = {}
                changed_block["confirmed_proposal_id"] = proposal_id
                changed_block["current_draft_proposal_id"] = None
                return {
                    "proposal": changed_proposal,
                    "proposal_id": proposal_id,
                    "block_id": changed_block["block_id"],
                    "block_revision": changed_block["revision"],
                }

            return self._mutate(change, "proposal_confirmed", {"proposal_id": proposal_id}, request_id, payload)

    def confirmation_result(self, proposal_id: str, expected_revision: int, request_id: str) -> dict | None:
        """Replay a committed next-run confirmation before stale/owner validation."""
        proposal_id = self._required_text(proposal_id, "proposal_id")
        request_id = self._required_text(request_id, "request_id")
        payload = {"op": "confirm", "proposal_id": proposal_id,
                   "expected_revision": expected_revision, "target": "next_run"}
        with self._lock, self._file_lock():
            self._refresh()
            return self._request_replay(request_id, payload)

    def confirm_normalized(self, proposal_id: str, expected_revision: int, request_id: str,
                           values: dict, validation: dict, *, expected_store_revision: int) -> dict:
        """Atomically record original confirmation identity and its unapproved successor.

        The original confirm payload is the idempotency key's value; normalized
        values are an owner-derived result, never a second operator approval.
        """
        proposal_id = self._required_text(proposal_id, "proposal_id")
        request_id = self._required_text(request_id, "request_id")
        values = self._json_dict(values, "values")
        validation = self._json_dict(validation, "validation")
        if validation.get("status") != "requires_confirmation":
            raise SetupValidationError("Normalized values require separate confirmation")
        payload = {"op": "confirm", "proposal_id": proposal_id,
                   "expected_revision": expected_revision, "target": "next_run"}
        with self._lock, self._file_lock():
            self._refresh()
            replay = self._request_replay(request_id, payload)
            if replay is not None:
                return replay
            if self._state["revision"] != expected_store_revision:
                raise SetupConflict("stale store revision")
            proposal = self._proposal(self._state, proposal_id)
            block = self._block(self._state, proposal["block_id"])
            self._require_revision(block, expected_revision)
            if proposal["status"] != "draft" or block.get("current_draft_proposal_id") != proposal_id:
                raise SetupConflict("proposal is no longer a draft")

            def change(candidate: dict) -> dict:
                original = self._proposal(candidate, proposal_id)
                changed = self._block(candidate, original["block_id"])
                original["validation"] = validation
                changed["validation_status"] = "requires_confirmation"
                changed["revision"] += 1
                successor = {"proposal_id": str(uuid4()), "block_id": changed["block_id"],
                    "base_revision": expected_revision, "revision": changed["revision"],
                    "values": values, "status": "draft",
                    "history": [{"event": "proposed", "values": values, "normalized_from": proposal_id}]}
                original["history"].append({"event": "normalization_proposed", "proposal_id": successor["proposal_id"]})
                candidate["proposals"][successor["proposal_id"]] = successor
                changed["proposal_ids"].append(successor["proposal_id"])
                changed["current_draft_proposal_id"] = successor["proposal_id"]
                changed["draft_values"] = values
                changed["agreement_status"] = "draft"
                return {"proposal": successor, "proposal_id": successor["proposal_id"],
                    "original_proposal_id": proposal_id, "block_id": changed["block_id"],
                    "block_revision": changed["revision"], "requires_confirmation": True,
                    "normalized_values": values}

            return self._mutate(change, "normalized_confirmation_proposed", {"proposal_id": proposal_id}, request_id, payload)

    def record_validation(self, proposal_id: str, expected_revision: int, validation: dict,
                          *, expected_store_revision: int | None = None) -> dict:
        """Persist validation evidence without changing accepted values/block revision."""
        validation = self._json_dict(validation, "validation")
        with self._lock, self._file_lock():
            self._refresh()
            if expected_store_revision is not None and self._state["revision"] != expected_store_revision:
                raise SetupConflict("stale store revision")
            proposal = self._proposal(self._state, proposal_id)
            block = self._block(self._state, proposal["block_id"])
            self._require_revision(block, expected_revision)
            if proposal_id not in (block.get("current_draft_proposal_id"), block.get("confirmed_proposal_id")):
                raise SetupConflict("validation is for a superseded proposal")

            def change(candidate):
                changed = self._proposal(candidate, proposal_id)
                current = self._block(candidate, changed["block_id"])
                changed["validation"] = deepcopy(validation)
                current["validation_status"] = validation.get("status", "unknown")
                return {"proposal": changed, "proposal_id": proposal_id,
                        "block_id": current["block_id"], "block_revision": current["revision"]}

            return self._mutate(change, "validation_recorded", {"proposal_id": proposal_id})

    def claim_activation(self, proposal_id: str, receipts: dict,
                         *, expected_store_revision: int | None = None) -> dict:
        """Atomically reserve every owner once, before any callback can run."""
        receipts = self._json_dict(receipts, "receipts")
        with self._lock, self._file_lock():
            self._refresh()
            proposal = self._proposal(self._state, proposal_id)
            block = self._block(self._state, proposal["block_id"])
            if proposal["status"] != "confirmed" or block.get("confirmed_proposal_id") != proposal_id:
                raise SetupConflict("activation requires the current confirmed proposal")
            if block["receipts"]:
                return self._result(claimed=False)
            if expected_store_revision is not None and self._state["revision"] != expected_store_revision:
                raise SetupConflict("stale store revision")
            if set(receipts) != set(block["owners"]) or any(
                not isinstance(r, dict) or r.get("status") != "applying" for r in receipts.values()
            ):
                raise SetupValidationError("activation must reserve every owner as applying")
            run_ids = [self._required_text(r.get("run_id"), "run_id") for r in receipts.values()]
            if len(set(run_ids)) != 1 or any(
                r.get("request_id") != f"{proposal_id}:{owner}:{r['run_id']}" for owner, r in receipts.items()
            ):
                raise SetupValidationError("activation requires one run and stable owner request IDs")

            def change(candidate):
                current = self._block(candidate, block["block_id"])
                current["revision"] += 1
                current["receipts"] = deepcopy(receipts)
                current["application_status"] = "applying"
                return {"claimed": True, "block_id": current["block_id"],
                        "block_revision": current["revision"]}

            return self._mutate(change, "activation_claimed", {"proposal_id": proposal_id})

    def discard(self, proposal_id: str, expected_revision: int, request_id: str) -> dict:
        proposal_id = self._required_text(proposal_id, "proposal_id")
        request_id = self._required_text(request_id, "request_id")
        payload = {"op": "discard", "proposal_id": proposal_id, "expected_revision": expected_revision}
        with self._lock, self._file_lock():
            self._refresh()
            replay = self._request_replay(request_id, payload)
            if replay is not None:
                return replay
            proposal = self._proposal(self._state, proposal_id)
            block = self._block(self._state, proposal["block_id"])
            self._require_revision(block, expected_revision)
            if proposal["status"] != "draft" or block.get("current_draft_proposal_id") != proposal_id:
                raise SetupConflict("proposal is no longer a draft")

            def change(candidate: dict) -> dict:
                changed_proposal = self._proposal(candidate, proposal_id)
                changed_block = self._block(candidate, changed_proposal["block_id"])
                changed_block["revision"] += 1
                changed_proposal["status"] = "discarded"
                changed_proposal["history"].append({"event": "discarded"})
                changed_block["draft_values"] = deepcopy(changed_block["confirmed_values"] or {})
                changed_block["agreement_status"] = "confirmed" if changed_block["confirmed_values"] is not None else "draft"
                changed_block["current_draft_proposal_id"] = None
                return {
                    "proposal": changed_proposal,
                    "proposal_id": proposal_id,
                    "block_id": changed_block["block_id"],
                    "block_revision": changed_block["revision"],
                }

            return self._mutate(change, "proposal_discarded", {"proposal_id": proposal_id}, request_id, payload)

    def record_application(self, proposal_id: str, owner: str, receipt: dict) -> dict:
        proposal_id = self._required_text(proposal_id, "proposal_id")
        owner = self._required_text(owner, "owner")
        receipt = self._json_dict(receipt, "receipt")
        with self._lock, self._file_lock():
            self._refresh()
            proposal = self._proposal(self._state, proposal_id)
            block = self._block(self._state, proposal["block_id"])
            if proposal["status"] != "confirmed":
                raise SetupConflict("application requires a confirmed proposal")
            if block.get("confirmed_proposal_id") != proposal_id:
                raise SetupConflict("application receipt is for a superseded proposal")
            if owner not in block["owners"]:
                raise SetupValidationError("receipt owner is not a block owner")

            def change(candidate: dict) -> dict:
                changed_proposal = self._proposal(candidate, proposal_id)
                changed_block = self._block(candidate, changed_proposal["block_id"])
                changed_block["revision"] += 1
                changed_block["receipts"][owner] = receipt
                if receipt.get("status") == "applied" and isinstance(receipt.get("readback"), dict):
                    changed_block["effective_values"].update(deepcopy(receipt["readback"]))
                changed_block["application_status"] = self._application_status(changed_block)
                changed_proposal["history"].append({"event": "application_recorded", "owner": owner, "receipt": receipt})
                return {
                    "proposal": changed_proposal,
                    "proposal_id": proposal_id,
                    "block_id": changed_block["block_id"],
                    "block_revision": changed_block["revision"],
                }

            return self._mutate(change, "application_recorded", {"proposal_id": proposal_id, "owner": owner})

    def snapshot(self) -> dict:
        with self._lock, self._file_lock():
            self._refresh()
            return self._result()

    def proposal(self, proposal_id: str) -> dict:
        with self._lock, self._file_lock():
            self._refresh()
            return deepcopy(self._proposal(self._state, self._required_text(proposal_id, "proposal_id")))

    def events(self, after: int) -> list[dict]:
        if not isinstance(after, int) or after < 0:
            raise SetupValidationError("after must be a non-negative integer")
        with self._lock, self._file_lock():
            self._refresh()
            return [deepcopy(event) for event in self._state["events"] if event["seq"] > after]

    def _mutate(self, change, event_name: str, event_fields: dict, request_id: str | None = None, request_payload: dict | None = None) -> dict:
        candidate = deepcopy(self._state)
        details = change(candidate)
        candidate["revision"] += 1
        candidate["event_seq"] += 1
        event = {"seq": candidate["event_seq"], "revision": candidate["revision"], "event": event_name, **event_fields}
        candidate["events"].append(event)
        result = self._result(candidate, **details)
        if request_id is not None:
            candidate["requests"][request_id] = {"payload": request_payload, "result": deepcopy(result)}
        atomic_write_json(self._path, candidate)
        self._state = candidate
        return result

    def _request_replay(self, request_id: str, payload: dict) -> dict | None:
        prior = self._state["requests"].get(request_id)
        if prior is None:
            return None
        if prior["payload"] != payload:
            raise SetupConflict("request_id was previously used with a different payload")
        return deepcopy(prior["result"])

    def _load(self) -> dict:
        try:
            state = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise SetupValidationError("experimental setup store is corrupt") from error
        self._validate_state(state)
        if state["session_id"] != self._session_id:
            raise SetupConflict("setup store belongs to another session")
        return state

    def _refresh(self) -> None:
        """Read the current durable revision while holding this path's process-local lock."""
        self._state = self._load()

    @contextmanager
    def _file_lock(self):
        """Serialize full read-modify-write transactions across POSIX processes."""
        with self._lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _empty_state(self) -> dict:
        return {"session_id": self._session_id, "revision": 0, "event_seq": 0, "blocks": [], "proposals": {}, "requests": {}, "events": []}

    def _validate_state(self, state: Any) -> None:
        if not isinstance(state, dict) or not isinstance(state.get("session_id"), str):
            raise SetupValidationError("experimental setup store has an invalid schema")
        required = {"revision": int, "event_seq": int, "blocks": list, "proposals": dict, "requests": dict, "events": list}
        if any(not isinstance(state.get(key), kind) for key, kind in required.items()):
            raise SetupValidationError("experimental setup store has an invalid schema")
        if state["revision"] < 0 or state["event_seq"] < 0:
            raise SetupValidationError("experimental setup store has an invalid schema")
        for block in state["blocks"]:
            if not isinstance(block, dict):
                raise SetupValidationError("experimental setup store has an invalid block")
            required_block = {
                "block_id": str,
                "topic_key": str,
                "owners": list,
                "revision": int,
                "draft_values": dict,
                "effective_values": dict,
                "agreement_status": str,
                "application_status": str,
                "receipts": dict,
                "proposal_ids": list,
            }
            if any(not isinstance(block.get(key), kind) for key, kind in required_block.items()):
                raise SetupValidationError("experimental setup store has an invalid block")

    def _result(self, state: dict | None = None, **details: Any) -> dict:
        current = self._state if state is None else state
        result = {"revision": current["revision"], "blocks": deepcopy(current["blocks"]), "event_seq": current["event_seq"]}
        result.update(deepcopy(details))
        return result

    @staticmethod
    def _block(state: dict, block_id: str) -> dict:
        for block in state["blocks"]:
            if block["block_id"] == block_id:
                return block
        raise SetupValidationError("unknown block_id")

    @staticmethod
    def _proposal(state: dict, proposal_id: str) -> dict:
        try:
            return state["proposals"][proposal_id]
        except KeyError as error:
            raise SetupValidationError("unknown proposal_id") from error

    @staticmethod
    def _require_revision(block: dict, revision: int) -> None:
        if not isinstance(revision, int) or revision != block["revision"]:
            raise SetupConflict("stale block revision")

    @staticmethod
    def _required_text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SetupValidationError(f"{field} must be a non-empty string")
        return value

    @classmethod
    def _owners(cls, owner: str | list[str]) -> list[str]:
        raw = [owner] if isinstance(owner, str) else owner
        if not isinstance(raw, list) or not raw:
            raise SetupValidationError("owner must be a non-empty string or list of strings")
        normalized = [cls._required_text(item, "owner") for item in raw]
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _json_dict(value: Any, field: str) -> dict:
        if not isinstance(value, dict):
            raise SetupValidationError(f"{field} must be a dictionary")
        try:
            return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise SetupValidationError(f"{field} must be JSON serializable") from error

    @staticmethod
    def _application_status(block: dict) -> str:
        statuses = [receipt.get("status") for receipt in block["receipts"].values()]
        owner_count = len(block["owners"])
        applied = statuses.count("applied")
        if applied == owner_count:
            return "applied"
        if applied:
            return "partial"
        if "applying" in statuses:
            return "applying"
        if "rejected" in statuses:
            return "rejected"
        if "unknown" in statuses:
            return "unknown"
        return "scheduled"
