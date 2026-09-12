"""Confirmation and fresh-run application of owner-declared setup."""
from __future__ import annotations

from copy import deepcopy

from agents.orchestrator_capabilities import OwnerCatalog
from orchestrator.experimental_setup import SetupConflict, SetupStore


def receipt_status(expected: dict, observed: dict | None) -> str:
    """A missing observation cannot establish an owner effect."""
    if not isinstance(observed, dict):
        return "unknown"
    return "applied" if expected == observed else "rejected"


def pending_setup_blocks(snapshot: dict) -> list[dict]:
    """An attempted but unverified application remains a next-run admission hold."""
    return [block for block in snapshot["blocks"] if block.get("confirmed_proposal_id")
            and (not block["receipts"] or block["application_status"] != "applied")]


class SetupApplication:
    """One-shot next-run proposals; all recovery is readback-only.

    Call after new state/reset, before assigning its first stage or generating LHS.
    The run snapshot is a detached JSON value, never refreshed by reconciliation.
    """

    def __init__(self, store: SetupStore, owners: OwnerCatalog):
        self.store = store
        self.owners = owners

    def _block(self, proposal, snapshot):
        return next(b for b in snapshot["blocks"] if b["block_id"] == proposal["block_id"])

    def _split(self, proposal, block, state):
        fields, bindings = {}, {}
        for row in self.owners.describe(deepcopy(state), None):
            descriptor = row.get("setup", {})
            if not descriptor.get("write_enabled"):
                continue
            owner = row["owner"]
            bindings.setdefault(owner, []).append({k: deepcopy(row.get(k)) for k in
                ("node_id", "step_id", "handler", "contract_version", "setup")})
            for field in descriptor.get("fields", []):
                pair = (owner, field["field"])
                if field["id"] in fields and fields[field["id"]] != pair:
                    raise ValueError("Ambiguous public setup setting")
                fields[field["id"]] = pair
        changes = {}
        for setting, value in proposal["values"].items():
            if setting not in fields:
                raise ValueError(f"Setting is not writable in the graph: {setting}")
            owner, field = fields[setting]
            changes.setdefault(owner, {})[field] = deepcopy(value)
        if not changes or set(changes) != set(block["owners"]):
            raise ValueError("Block owners do not match descriptor-owned settings")
        return changes, fields, {owner: bindings[owner] for owner in changes}

    def _dependencies(self, block, snapshot):
        return {b["block_id"]: b["revision"] for b in snapshot["blocks"]
                if b["block_id"] != block["block_id"] and set(b["owners"]) & set(block["owners"])}

    def _validate(self, changes, state):
        normalized, warnings = {}, []
        for owner, values in changes.items():
            result = self.owners.validate(owner, values, deepcopy(state))
            normalized[owner] = {key: deepcopy(result["values"][key]) for key in values}
            warnings.extend(result.get("warnings", []))
        return normalized, warnings

    async def confirm(self, proposal_id: str, revision: int, request_id: str, state) -> dict:
        replay = self.store.confirmation_result(proposal_id, revision, request_id)
        if replay is not None:
            return replay
        proposal = self.store.proposal(proposal_id)
        if proposal["status"] == "confirmed":
            return self.store.confirm(proposal_id, revision, request_id, "next_run")
        snapshot = self.store.snapshot()
        block = self._block(proposal, snapshot)
        if block["revision"] != revision:
            raise SetupConflict("stale block revision")
        changes, fields, bindings = self._split(proposal, block, state)
        normalized, warnings = self._validate(changes, state)
        public = {setting: normalized[owner][field] for setting, (owner, field) in fields.items()
                  if setting in proposal["values"]}
        validation = {"status": "valid", "origin_run_id": state.run_id,
                      "changes": normalized, "bindings": bindings,
                      "dependencies": self._dependencies(block, snapshot), "warnings": warnings}
        if public != proposal["values"]:
            validation["status"] = "requires_confirmation"
            return self.store.confirm_normalized(proposal_id, revision, request_id, public, validation,
                                                 expected_store_revision=snapshot["revision"])
        recorded = self.store.record_validation(proposal_id, revision, validation,
                                                expected_store_revision=snapshot["revision"])
        return self.store.confirm(proposal_id, revision, request_id, "next_run",
                                  expected_store_revision=recorded["revision"])

    def _observe(self, owner, changes, state):
        try:
            observed = self.owners.readback(owner, deepcopy(state))
            if isinstance(observed, dict):
                return {key: observed[key] for key in changes if key in observed}
        except Exception:
            pass
        return None

    async def activate_for_new_run(self, state) -> dict:
        saved = state.run_metadata.get("experimental_setup_snapshot")
        if saved is not None:
            return deepcopy(saved)
        if getattr(state.stage, "value", state.stage) != "idle" or state.loop_count or state.experiment_evaluations:
            raise SetupConflict("setup activation requires fresh idle run inputs")
        initial = self.store.snapshot()
        pending = pending_setup_blocks(initial)
        # Reject the original run before touching any owner, including an idle old run.
        for block in pending:
            proposal = self.store.proposal(block["confirmed_proposal_id"])
            if not block["receipts"] and proposal.get("validation", {}).get("origin_run_id") == state.run_id:
                raise SetupConflict("confirmed setup targets a new run, not its original run")
        blockers, prepared, combined = [], [], {}
        captured = {block["block_id"] for block in pending if not block["receipts"]
                    and not block.get("current_draft_proposal_id")}
        # Validate the entire captured set against one snapshot before any owner
        # effect. Joint confirmations may change each other's revision counters,
        # but unrelated drafts/contracts/normalization never acquire approval.
        for block in pending:
            proposal_id = block["confirmed_proposal_id"]
            proposal = self.store.proposal(proposal_id)
            if block["receipts"]:
                blockers.append({"proposal_id": proposal_id, "reason": "Owner receipt requires readback recovery; no automatic reapplication."})
                continue
            validation = proposal.get("validation", {})
            try:
                changes, _, bindings = self._split(proposal, block, state)
                dependencies = self._dependencies(block, initial)
                saved_dependencies = validation.get("dependencies", {})
                valid = (validation.get("status") == "valid" and
                         proposal.get("target") == "next_run" and
                         validation.get("bindings") == bindings and
                         validation.get("changes") == changes and
                         all(saved_dependencies.get(key) == dependencies.get(key) or key in captured
                             for key in set(saved_dependencies) | set(dependencies)))
                for owner, values in changes.items():
                    existing = combined.setdefault(owner, {})
                    if any(key in existing and existing[key] != value for key, value in values.items()):
                        valid = False
                    existing.update(deepcopy(values))
            except (ValueError, KeyError, TypeError):
                valid = False
            if not valid:
                blockers.append({"proposal_id": proposal_id, "reason": "Setup changed; revalidate and explicitly confirm a new proposal."})
            prepared.append((block, proposal, changes if valid else {}))
        if not blockers:
            try:
                normalized, _ = self._validate(combined, state)
                if normalized != combined:
                    raise ValueError("Owner-normalized values need explicit confirmation")
            except (ValueError, KeyError, TypeError) as error:
                blockers.extend({"proposal_id": proposal["proposal_id"],
                    "reason": "Owner validation changed; review and explicitly confirm a new proposal.",
                    "error": type(error).__name__} for _, proposal, _ in prepared)
        if blockers:
            stale_ids = {b["proposal_id"] for b in blockers}
            for block, proposal, _ in prepared:
                if proposal["proposal_id"] in stale_ids:
                    self.store.record_validation(proposal["proposal_id"], block["revision"],
                        {**proposal.get("validation", {}), "status": "stale"})
        expected_revision = self.store.snapshot()["revision"]
        if not blockers and expected_revision != initial["revision"]:
            raise SetupConflict("Setup changed during admission validation")
        for block, proposal, changes in prepared if not blockers else []:
            proposal_id = proposal["proposal_id"]
            receipts = {owner: {"owner": owner, "request_id": f"{proposal_id}:{owner}:{state.run_id}",
                               "run_id": state.run_id, "status": "applying", "expected": values}
                        for owner, values in changes.items()}
            claim = self.store.claim_activation(proposal_id, receipts, expected_store_revision=expected_revision)
            if not claim["claimed"]:
                blockers.append({"proposal_id": proposal_id, "reason": "Application already claimed; readback recovery required."})
                break
            expected_revision = claim["revision"]
            for owner, changes_for_owner in changes.items():
                receipt = deepcopy(receipts[owner])
                try:
                    await self.owners.apply(owner, changes_for_owner, state, receipt["request_id"])
                except Exception as error:
                    receipt["error"] = type(error).__name__
                observed = self._observe(owner, changes_for_owner, state)
                receipt.update(status=receipt_status(changes_for_owner, observed), readback=observed)
                recorded = self.store.record_application(proposal_id, owner, receipt)
                expected_revision = recorded["revision"]
                if receipt["status"] != "applied":
                    blockers.append({"proposal_id": proposal_id, "owner": owner,
                                     "reason": "Owner readback has not established the confirmed effect."})
        result = {"run_id": state.run_id, **self.store.snapshot()}
        result["admission"] = {"status": "blocked" if blockers else "admitted", "blockers": blockers,
                               "proposal_ids": [block["confirmed_proposal_id"] for block in pending]}
        for block in result["blocks"]:
            current_receipts = {owner: receipt for owner, receipt in block["receipts"].items()
                                if receipt.get("run_id") == state.run_id}
            block["effective_values"] = {key: deepcopy(value)
                for receipt in current_receipts.values() if receipt.get("status") == "applied"
                for key, value in (receipt.get("readback") or {}).items()}
            if current_receipts != block["receipts"]:
                block["receipts"] = current_receipts
                block["application_status"] = "not_applied"
        state.run_metadata["experimental_setup_snapshot"] = deepcopy(result)
        return deepcopy(result)

    async def reconcile(self, proposal_id: str, state) -> dict:
        proposal = self.store.proposal(proposal_id)
        block = self._block(proposal, self.store.snapshot())
        if block.get("confirmed_proposal_id") != proposal_id:
            raise SetupConflict("cannot reconcile a superseded proposal")
        for owner, saved in block["receipts"].items():
            if saved.get("run_id") != state.run_id:
                raise SetupConflict("receipt belongs to a different run")
            if saved.get("status") == "applied":
                continue
            receipt = deepcopy(saved)
            observed = self._observe(owner, receipt["expected"], state)
            receipt.update(status=receipt_status(receipt["expected"], observed), readback=observed)
            self.store.record_application(proposal_id, owner, receipt)
        return self.store.snapshot()
