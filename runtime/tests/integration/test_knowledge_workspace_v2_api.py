"""HTTP boundary contracts for the v2 Knowledge workspace routes."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_workspace_routes_inject_server_principal_and_never_accept_http_identity(tmp_path):
    from knowledge.context_service import KnowledgeContextService, KnowledgePrincipal
    from knowledge.workspace_api import install_workspace_routes

    service = KnowledgeContextService(tmp_path)
    principal = KnowledgePrincipal("alice", project_ids=frozenset({"project-a"}))
    app = FastAPI()
    install_workspace_routes(app, service_factory=lambda: service, principal_resolver=lambda request: principal,
                             private_mutation_origins=frozenset({"https://workspace.test"}))
    client = TestClient(app)

    proposed = client.post("/api/knowledge/memory/commands", json={
        "action": "propose", "idempotency_key": "http-one", "payload": {
            "kind": "preference", "content": "Synthetic private value", "source_refs": ["synthetic:http"],
            "scope": {"kind": "user"},
        },
    }, headers={"Origin": "https://workspace.test"})
    assert proposed.status_code == 200
    assert proposed.headers["cache-control"] == "no-store"
    assert "content" not in proposed.json()
    rejected_identity = client.post("/api/knowledge/memory/query", json={"query": "Synthetic", "subject_id": "bob"})
    assert rejected_identity.status_code == 422
    listed = client.post("/api/knowledge/memory/query", json={"query": "Synthetic", "limit": 1})
    assert listed.status_code == 200
    assert listed.json()["items"][0]["record_id"] == proposed.json()["record_id"]
    assert client.post("/api/knowledge/memory/commands", json={
        "action": "propose", "idempotency_key": "blocked-origin", "payload": {"kind": "preference", "content": "x", "source_refs": ["synthetic:x"], "scope": {"kind": "user"}},
    }).status_code == 403


def test_public_workspace_is_wiki_only_and_reindex_requires_admin_local_origin(tmp_path):
    from knowledge.context_service import KnowledgeContextService
    from knowledge.workspace_api import install_workspace_routes

    app = FastAPI()
    install_workspace_routes(app, service_factory=lambda: KnowledgeContextService(tmp_path), principal_resolver=lambda request: None)
    client = TestClient(app)
    assert client.post("/api/knowledge/memory/query", json={"query": "anything"}).status_code == 401
    assert client.post("/api/knowledge/memory/query", json={"query": "anything"}).headers["cache-control"] == "no-store"
    wiki = client.post("/api/knowledge/wiki/query", json={"query": "platform"})
    assert wiki.status_code == 200 and wiki.headers["cache-control"] == "no-store"
    assert client.post("/api/knowledge/wiki/reindex", json={}).status_code == 403
