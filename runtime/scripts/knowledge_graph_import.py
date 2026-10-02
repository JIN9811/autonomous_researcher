#!/usr/bin/env python3
"""Import Graphify project graph artifacts into optional Knowledge graph backend."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from knowledge.graph_backend import JsonGraphBackend, graph_backend_from_env  # noqa: E402
from knowledge.graphify_bridge import import_project_graph  # noqa: E402
from knowledge.stores import JsonlKnowledgeStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Import ATR project Graphify graph into optional Knowledge graph backend")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--graphify-json", default="memory/knowledge/graphify/project_graph.json")
    parser.add_argument("--json-path", default="memory/knowledge/graph_backend/knowledge_graph.json")
    parser.add_argument("--runtime-limit", type=int, default=500)
    parser.add_argument("--no-runtime-memory", action="store_true")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    graph_json = (root / args.graphify_json).resolve() if not Path(args.graphify_json).is_absolute() else Path(args.graphify_json).resolve()
    if not graph_json.exists():
        result = {"ok": False, "error": f"graphify JSON not found: {graph_json}", "hint": "run atr knowledge graphify-scan first"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1
    backend = _backend(root, args.json_path)
    try:
        store = None
        if not args.no_runtime_memory:
            store = JsonlKnowledgeStore(memory_root=root / "memory" / "knowledge", run_root=root / "runs")
        result = import_project_graph(backend, graph_json, include_runtime_memory=not args.no_runtime_memory, store=store, runtime_limit=args.runtime_limit)
    finally:
        backend.close()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok", True) else 1


def _backend(root: Path, json_path: str):
    enabled = os.environ.get("ATR_KNOWLEDGE_GRAPH_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    backend_type = os.environ.get("ATR_KNOWLEDGE_GRAPH_BACKEND", "json").strip().lower() or "json"
    if enabled and backend_type == "json":
        return JsonGraphBackend((root / json_path).resolve())
    return graph_backend_from_env(root)


if __name__ == "__main__":
    raise SystemExit(main())
