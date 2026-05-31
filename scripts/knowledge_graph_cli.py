#!/usr/bin/env python3
"""Operate the optional ATR Knowledge graph backend.

This CLI intentionally keeps Neo4j optional. JSONL memory remains authoritative.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from knowledge.graph_backend import JsonGraphBackend, Neo4jGraphBackend, graph_backend_from_env  # noqa: E402
from knowledge.graph_importer import import_store_to_graph  # noqa: E402
from knowledge.stores import JsonlKnowledgeStore  # noqa: E402

DEFAULT_CONTAINER = "atr-neo4j"
DEFAULT_IMAGE = "neo4j:5-community"
DEFAULT_PASSWORD = "atr-knowledge-graph"
DEFAULT_HTTP_PORT = 7474
DEFAULT_BOLT_PORT = 7687


def main() -> int:
    parser = argparse.ArgumentParser(description="ATR Knowledge graph backend utility")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--json-path", default="memory/knowledge/graph_backend/knowledge_graph.json")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health")

    imp = sub.add_parser("import")
    imp.add_argument("--limit", type=int, default=500)

    query = sub.add_parser("query")
    query.add_argument("--kind", default="summary", choices=["summary", "neighbors", "target_context", "project_context", "text"])
    query.add_argument("--node-id", default="")
    query.add_argument("--target-type", default="")
    query.add_argument("--target-id", default="")
    query.add_argument("--q", default="")
    query.add_argument("--limit", type=int, default=50)
    query.add_argument("--include-properties", action="store_true", help="return full node/edge properties instead of compact operational metadata")

    start = sub.add_parser("neo4j-start")
    start.add_argument("--container", default=DEFAULT_CONTAINER)
    start.add_argument("--image", default=DEFAULT_IMAGE)
    start.add_argument("--password", default=os.environ.get("ATR_NEO4J_PASSWORD", DEFAULT_PASSWORD))
    start.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    start.add_argument("--bolt-port", type=int, default=DEFAULT_BOLT_PORT)
    start.add_argument("--data-dir", default="memory/knowledge/neo4j/data")
    start.add_argument("--logs-dir", default="memory/knowledge/neo4j/logs")
    start.add_argument("--wait", action="store_true")

    stop = sub.add_parser("neo4j-stop")
    stop.add_argument("--container", default=DEFAULT_CONTAINER)

    env = sub.add_parser("print-env")
    env.add_argument("--password", default=os.environ.get("ATR_NEO4J_PASSWORD", DEFAULT_PASSWORD))
    env.add_argument("--bolt-port", type=int, default=DEFAULT_BOLT_PORT)

    args = parser.parse_args()
    root = Path(args.project_root).resolve()

    if args.cmd == "health":
        return _print(_backend(root, args.json_path).health())
    if args.cmd == "import":
        backend = _backend(root, args.json_path)
        try:
            store = JsonlKnowledgeStore(memory_root=root / "memory" / "knowledge", run_root=root / "runs")
            return _print(import_store_to_graph(store, backend, limit=args.limit))
        finally:
            backend.close()
    if args.cmd == "query":
        backend = _backend(root, args.json_path)
        try:
            return _print(
                backend.query(
                    {
                        "kind": args.kind,
                        "node_id": args.node_id,
                        "target_type": args.target_type,
                        "target_id": args.target_id,
                        "q": args.q,
                        "limit": args.limit,
                        "include_properties": args.include_properties,
                    }
                )
            )
        finally:
            backend.close()
    if args.cmd == "neo4j-start":
        return _print(_neo4j_start(root, args))
    if args.cmd == "neo4j-stop":
        return _print(_neo4j_stop(args.container))
    if args.cmd == "print-env":
        return _print(
            {
                "ATR_KNOWLEDGE_GRAPH_ENABLED": "1",
                "ATR_KNOWLEDGE_GRAPH_BACKEND": "neo4j",
                "ATR_KNOWLEDGE_GRAPH_FAIL_OPEN": "1",
                "ATR_NEO4J_URI": f"bolt://127.0.0.1:{args.bolt_port}",
                "ATR_NEO4J_USERNAME": "neo4j",
                "ATR_NEO4J_PASSWORD": args.password,
                "ATR_NEO4J_DATABASE": "neo4j",
                "bash": [
                    "export ATR_KNOWLEDGE_GRAPH_ENABLED=1",
                    "export ATR_KNOWLEDGE_GRAPH_BACKEND=neo4j",
                    "export ATR_KNOWLEDGE_GRAPH_FAIL_OPEN=1",
                    f"export ATR_NEO4J_URI=bolt://127.0.0.1:{args.bolt_port}",
                    "export ATR_NEO4J_USERNAME=neo4j",
                    f"export ATR_NEO4J_PASSWORD='{args.password}'",
                    "export ATR_NEO4J_DATABASE=neo4j",
                ],
            }
        )
    return 2


def _backend(root: Path, json_path: str):
    enabled = os.environ.get("ATR_KNOWLEDGE_GRAPH_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    backend_type = os.environ.get("ATR_KNOWLEDGE_GRAPH_BACKEND", "json").strip().lower() or "json"
    if enabled and backend_type == "json":
        return JsonGraphBackend((root / json_path).resolve())
    return graph_backend_from_env(root)


def _neo4j_start(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    _require_docker()
    data_dir = (root / args.data_dir).resolve()
    logs_dir = (root / args.logs_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    existing = _run(["docker", "ps", "-a", "--filter", f"name=^{args.container}$", "--format", "{{.Names}}"], check=False)
    if args.container in existing.stdout.splitlines():
        started = _run(["docker", "start", args.container], check=False)
        status = "started_existing" if started.returncode == 0 else "start_failed"
    else:
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            args.container,
            "-p",
            f"{args.http_port}:7474",
            "-p",
            f"{args.bolt_port}:7687",
            "-e",
            f"NEO4J_AUTH=neo4j/{args.password}",
            "-e",
            "NEO4J_server_memory_heap_initial__size=512m",
            "-e",
            "NEO4J_server_memory_heap_max__size=2G",
            "-e",
            "NEO4J_server_memory_pagecache_size=1G",
            "-v",
            f"{data_dir}:/data",
            "-v",
            f"{logs_dir}:/logs",
            args.image,
        ]
        started = _run(cmd, check=False)
        status = "created" if started.returncode == 0 else "create_failed"
    result: dict[str, Any] = {
        "ok": started.returncode == 0,
        "container": args.container,
        "status": status,
        "http_url": f"http://127.0.0.1:{args.http_port}",
        "bolt_uri": f"bolt://127.0.0.1:{args.bolt_port}",
        "username": "neo4j",
        "password": args.password,
        "data_dir": data_dir.as_posix(),
        "logs_dir": logs_dir.as_posix(),
        "stdout": started.stdout.strip(),
        "stderr": started.stderr.strip(),
    }
    if args.wait and started.returncode == 0:
        result["wait"] = _wait_neo4j(args.bolt_port, args.password)
    return result


def _neo4j_stop(container: str) -> dict[str, Any]:
    _require_docker()
    stopped = _run(["docker", "stop", container], check=False)
    return {"ok": stopped.returncode == 0, "container": container, "stdout": stopped.stdout.strip(), "stderr": stopped.stderr.strip()}


def _wait_neo4j(bolt_port: int, password: str, timeout_s: float = 90.0) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    os.environ.setdefault("ATR_KNOWLEDGE_GRAPH_ENABLED", "1")
    os.environ.setdefault("ATR_KNOWLEDGE_GRAPH_BACKEND", "neo4j")
    os.environ.setdefault("ATR_NEO4J_URI", f"bolt://127.0.0.1:{bolt_port}")
    os.environ.setdefault("ATR_NEO4J_USERNAME", "neo4j")
    os.environ.setdefault("ATR_NEO4J_PASSWORD", password)
    os.environ.setdefault("ATR_NEO4J_DATABASE", "neo4j")
    os.environ.setdefault("ATR_KNOWLEDGE_GRAPH_FAIL_OPEN", "0")
    while time.time() < deadline:
        try:
            backend = Neo4jGraphBackend(uri=f"bolt://127.0.0.1:{bolt_port}", username="neo4j", password=password, database="neo4j")
            try:
                last = backend.health()
            finally:
                backend.close()
            if last.get("ok"):
                return {"ok": True, "health": last}
        except Exception as exc:
            last = {"ok": False, "error": str(exc)}
        time.sleep(2.0)
    return {"ok": False, "last": last}


def _require_docker() -> None:
    if _run(["docker", "--version"], check=False).returncode != 0:
        raise SystemExit("docker is required for neo4j-start/neo4j-stop")


def _run(cmd: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _print(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
