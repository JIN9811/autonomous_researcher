"""Graph-derived setup views and bounded draft proposals; no execution authority."""
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from agents.orchestrator_decision import decide_orchestration
from orchestrator.experimental_setup import SetupConflict, SetupValidationError
from orchestrator.setup_application import SetupApplication
from graphs import load_module_config


def planning_decision_settings(catalog, owner):
    """Use the graph-linked Orchestrator budget and existing model route timeout."""
    for row in catalog.describe(None, None):
        if row["owner"] == owner and row.get("module_id"):
            path = catalog.graph_root / row["module_id"] / "module.yaml"
            if path.is_file():
                module = load_module_config(path).model_dump(mode="json", exclude_none=True)
                if str(module.get("handler") or "").strip() == f"agent.{owner}":
                    return deepcopy(module.get("decision_settings", {}))
    return {}


def project_setup(store, catalog, state, ctx, *, initialize=True):
    owners = catalog.describe(state, ctx)
    descriptors = {}
    unknown_readbacks = set()
    for row in owners:
        descriptor = row["setup"]
        if descriptor.get("write_enabled"):
            descriptors[row["owner"]] = descriptor
    if initialize:
        for owner, descriptor in descriptors.items():
            try:
                observed = catalog.readback(owner, state)
            except Exception:
                observed = None
            if not isinstance(observed, dict):
                unknown_readbacks.add(owner)
                observed = {}
            for field in descriptor.get("fields", []):
                store.ensure_block(field["id"], owner, {field["id"]: observed.get(field["field"])})
    snapshot = store.snapshot()
    for block in snapshot["blocks"]:
        fields = [field for owner in block["owners"] for field in descriptors.get(owner, {}).get("fields", [])
                  if field["id"] in block["draft_values"] or field["id"] == block["topic_key"]]
        block.update(active=bool(fields) and all(owner in descriptors for owner in block["owners"]),
                     fields=fields, target="next_run")
        block["editable"] = block["active"]
        if any(owner in unknown_readbacks for owner in block["owners"]):
            block["readback_status"] = "unknown"
    snapshot.update(schema="experimental_setup.v1", owners=owners)
    snapshot["projection_id"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()
    return snapshot


async def propose_from_chat(*, store, catalog, projection, state, ctx, message, scope, current_scope, settings, block_id=None):
    """Only declared next-run draft writes, guarded before and after model/tool awaits."""
    blocks = {b["block_id"]: b for b in projection["blocks"] if b["editable"]
              and (block_id is None or b["block_id"] == block_id)}
    expected_revision = store.snapshot()["revision"]
    expected_pending = deepcopy(scope["pending"])

    def checked_scope():
        current = current_scope()
        # The synchronous store mutation below is our one admitted effect. All
        # unrelated revisions and runtime scope changes still invalidate decisions.
        if store.snapshot()["revision"] == expected_revision:
            current["setup_revision"] = scope["setup_revision"]
            if current["pending"] == expected_pending:
                current["pending"] = deepcopy(scope["pending"])
        return current

    async def propose(arguments):
        nonlocal expected_revision, expected_pending
        if checked_scope() != scope:
            raise SetupConflict("Setup request scope changed")
        block = blocks[arguments["block_id"]]
        changes = arguments["changes"]
        if not changes or not set(changes) <= {field["id"] for field in block["fields"]}:
            raise SetupValidationError("Undeclared setup field")
        values = {**block["draft_values"], **changes}
        application = SetupApplication(store, catalog)
        owner_changes, _, _ = application._split({"values": values}, block, state)
        # Validation is side-effect-free. Keep original draft values so owner
        # normalization still requires its separate explicit confirmation.
        application._validate(owner_changes, state)
        if checked_scope() != scope:
            raise SetupConflict("Setup request scope changed during owner validation")
        result = store.propose(block["block_id"], arguments["revision"],
                               values, str(uuid4()))
        expected_revision = result["revision"]
        expected_pending = current_scope()["pending"]
        return result

    async def defer(arguments):
        return {"status": "deferred", "reason": arguments["condition"]}

    # The model needs editable values and their complete field constraints, not
    # the UI's unrelated owner graph, event history or execution presentation.
    # Store/scope validation still uses the full original projection above.
    proposal_evidence = {
        "schema": projection["schema"], "revision": projection["revision"],
        "projection_id": projection["projection_id"],
        "blocks": [{key: deepcopy(block[key]) for key in (
            "block_id", "revision", "topic_key", "owners", "draft_values", "fields", "target")}
            for block in blocks.values()],
    }
    return await decide_orchestration(state, ctx, context={"scope": deepcopy(scope),
        "current_scope": checked_scope, "settings": settings,
        "request": {"message": message, "target": "next_run", "instruction":
            "Propose a draft only; never confirm or execute. Use only declared fields, enum values, and nested parameter keys in the current setup. For unsupported settings use defer and explain; do not invent nested keys or return an intake classification."},
        "evidence": {"chat:request": {"message": message, "setup": proposal_evidence}},
        "setup_blocks": {key: {"revision": b["revision"], "fields": [f["id"] for f in b["fields"]]} for key, b in blocks.items()}},
        handlers={"propose_setup_change": propose, "defer": defer})
