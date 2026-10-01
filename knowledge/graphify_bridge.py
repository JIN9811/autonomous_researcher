"""Graphify project graph scan/import bridge for ATR Knowledge memory.

This module keeps Graphify optional. It can ingest a Graphify-style graph.json
when one exists, and it can also build a deterministic lightweight project graph
from the ATR repository when the external graphify CLI is unavailable.
"""

from __future__ import annotations

import ast
import hashlib
import html
import json
import os
import re
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from knowledge.graph_backend import KnowledgeGraphBackend
from knowledge.graph_importer import import_store_to_graph
from knowledge.stores import JsonlKnowledgeStore

GRAPHIFY_BRIDGE_SCHEMA = "atr_graphify_project_graph_v1"

DEFAULT_SCAN_PATHS = [
    "agents",
    "graphs",
    "app",
    "orchestrator",
    "knowledge",
    "docs/README.md",
    "docs/runtime",
    "docs/agents",
    "docs/hardware",
]

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "runs",
    "artifacts",
    "memory",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    "workspace",
    "private",
    "outputs",
    "user_files",
    "logs",
    "source_inbox",
}

SECRET_NAME_PATTERNS = (
    ".env",
    "connection",
    "credential",
    "credentials",
    "password",
    "passwd",
    "secret",
    "token",
    "key",
    "prusa_connection",
    "windows_pyautogui_connection",
)

TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".md",
    ".txt",
    ".sh",
}

CODE_EXTENSIONS = {".py", ".js", ".ts", ".html", ".css", ".sh"}
DOC_EXTENSIONS = {".md", ".txt"}
CONFIG_EXTENSIONS = {".yaml", ".yml", ".json", ".toml"}
AGENT_IDS = {"design", "specimen", "vision", "manipulation", "equipment", "analysis", "knowledge", "bo", "guardian", "orchestrator"}


def scan_project_graph(
    project_root: Path,
    *,
    out_dir: Path | None = None,
    source_paths: list[str] | None = None,
    runtime_root: Path | None = None,
    corpus_paths: list[str] | None = None,
    reference_map: Mapping[str, str] | None = None,
    max_file_bytes: int = 256_000,
    run_external_graphify: bool = False,
) -> dict[str, Any]:
    """Build project-level graph artifacts under memory/knowledge/graphify."""
    project_root = project_root.resolve()
    runtime_root = Path(runtime_root).resolve() if runtime_root is not None else project_root
    if not runtime_root.is_relative_to(project_root):
        raise ValueError("Graph runtime_root must be inside the repository")
    inverse = _identity_map(reference_map or {})
    if source_paths is not None and corpus_paths is not None and source_paths != corpus_paths:
        raise ValueError("source_paths conflicts with corpus_paths")
    selected_sources = corpus_paths if corpus_paths is not None else source_paths
    if selected_sources is None:
        if runtime_root != project_root:
            raise ValueError("A split runtime requires an explicit technical corpus allowlist")
        selected_sources = list(DEFAULT_SCAN_PATHS)
    for source in selected_sources:
        _canonical_path(source)
        if source in {"docs", "system", "runtime"} or project_root / source == runtime_root:
            raise ValueError("Graph corpus must select technical subtrees, not a source root")
    files = _collect_files(project_root, selected_sources, max_file_bytes=max_file_bytes)
    # Imports are reference metadata, not extra content-ingestion authority.
    reference_paths: set[str] = set()
    for source in files:
        if Path(source).suffix == '.py':
            for imported in _python_imports(_safe_read(project_root / source, max_file_bytes=max_file_bytes)):
                target = _resolve_python_import(runtime_root, imported, repository_root=project_root)
                if target:
                    reference_paths.add(target.removeprefix('file:'))
    out_dir = (out_dir or project_root / "memory" / "knowledge" / "graphify").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Both engines receive the same bounded, non-symlink public file set.
    external = _run_external_graphify(project_root, out_dir, files) if run_external_graphify else {"ok": False, "skipped": True, "reason": "external graphify disabled"}
    if external.get("ok") and Path(str(external.get("graph_json", ""))).exists():
        graph = load_graphify_graph(Path(str(external["graph_json"])))
        graph["metadata"] = {**graph.get("metadata", {}), "external_graphify": external}
    else:
        graph = build_fallback_project_graph(project_root, files, max_file_bytes=max_file_bytes,
                                             runtime_root=runtime_root, reference_map=reference_map)
        graph["metadata"] = {**graph.get("metadata", {}), "external_graphify": external}
    graph = _reconcile_identities(graph, project_root, inverse, set(files) | reference_paths)
    graph['metadata']['reference_paths'] = sorted(reference_paths)

    graph_path = out_dir / "project_graph.json"
    report_path = out_dir / "GRAPH_REPORT.md"
    html_path = out_dir / "project_graph.html"
    manifest_path = out_dir / "import_manifest.json"
    last_scan_path = out_dir / "last_scan.json"

    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    report = render_graph_report(graph)
    report_path.write_text(report, encoding="utf-8")
    html_path.write_text(render_graph_html(graph), encoding="utf-8")

    manifest = {
        "schema": "atr_graphify_import_manifest.v1",
        "created_at": _now(),
        "project_root": project_root.as_posix(),
        "runtime_root": runtime_root.as_posix(),
        "source_paths": selected_sources,
        "external_graphify": external,
        "outputs": {
            "graph_json": graph_path.as_posix(),
            "graph_report": report_path.as_posix(),
            "graph_html": html_path.as_posix(),
        },
        "checksums": {
            "graph_json_sha256": _sha256_file(graph_path),
            "graph_report_sha256": _sha256_file(report_path),
            "graph_html_sha256": _sha256_file(html_path),
        },
        "node_count": len(graph.get("nodes", [])),
        "edge_count": len(graph.get("edges", [])),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    last_scan_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return {"ok": True, "tool": "knowledge.graphify.scan", **manifest}


def build_fallback_project_graph(project_root: Path, source_paths: list[str], *, max_file_bytes: int,
                                 runtime_root: Path | None = None,
                                 reference_map: Mapping[str, str] | None = None) -> dict[str, Any]:
    files = _collect_files(project_root, source_paths, max_file_bytes=max_file_bytes)
    runtime_root = runtime_root or project_root
    inverse = _identity_map(reference_map or {})
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    root_id = "project:autonomous_researcher"
    nodes[root_id] = {
        "id": root_id,
        "kind": "Project",
        "label": "autonomous_researcher",
        "properties": {"path": project_root.as_posix(), "schema": GRAPHIFY_BRIDGE_SCHEMA},
    }

    for agent_id in sorted(AGENT_IDS):
        node_id = f"agent:{agent_id}"
        nodes[node_id] = {"id": node_id, "kind": "Agent", "label": agent_id, "agent_id": agent_id, "properties": {"agent_id": agent_id}}

    for rel_path in sorted(files):
        logical_path = inverse.get(rel_path, rel_path)
        abs_path = project_root / rel_path
        text = _safe_read(abs_path, max_file_bytes=max_file_bytes)
        file_node = _file_node(rel_path, text)
        nodes[file_node["id"]] = file_node
        edges[_edge_id(root_id, file_node["id"], "CONTAINS")] = _edge(root_id, file_node["id"], "CONTAINS")

        agent_id = _agent_for_path(logical_path)
        if agent_id:
            agent_node = f"agent:{agent_id}"
            edge_type = "IMPLEMENTS" if logical_path.startswith(("agents/", "graphs/modules/")) else "DOCUMENTS"
            edges[_edge_id(file_node["id"], agent_node, edge_type)] = _edge(file_node["id"], agent_node, edge_type)

        if logical_path.startswith("graphs/modules/") and logical_path.endswith("module.yaml"):
            module_id = logical_path.split("/")[2]
            module_node = f"module:{module_id}"
            nodes[module_node] = {"id": module_node, "kind": "Module", "label": module_id, "agent_id": module_id, "properties": {"module_id": module_id, "path": rel_path}}
            edges[_edge_id(file_node["id"], module_node, "DECLARES")] = _edge(file_node["id"], module_node, "DECLARES")
            edges[_edge_id(module_node, f"agent:{module_id}", "IMPLEMENTS")] = _edge(module_node, f"agent:{module_id}", "IMPLEMENTS")

        if abs_path.suffix == ".py":
            for imported in _python_imports(text):
                dep_id = _resolve_python_import(runtime_root, imported, repository_root=project_root)
                if dep_id:
                    edges[_edge_id(file_node["id"], dep_id, "IMPORTS")] = _edge(file_node["id"], dep_id, "IMPORTS", properties={"import": imported})
            for route in _fastapi_routes(text):
                route_id = f"api:{route['method']}:{route['path']}"
                nodes[route_id] = {"id": route_id, "kind": "RuntimeAPI", "label": f"{route['method']} {route['path']}", "properties": route}
                edges[_edge_id(file_node["id"], route_id, "IMPLEMENTS")] = _edge(file_node["id"], route_id, "IMPLEMENTS")

        for tool_name in _tool_defs(text, logical_path):
            tool_id = f"tool:{tool_name}"
            nodes[tool_id] = {"id": tool_id, "kind": "Tool", "label": tool_name, "properties": {"tool_id": tool_name}}
            edges[_edge_id(file_node["id"], tool_id, "IMPLEMENTS")] = _edge(file_node["id"], tool_id, "IMPLEMENTS")

        for concept in _concepts(text, rel_path):
            concept_id = f"concept:{concept}"
            nodes.setdefault(concept_id, {"id": concept_id, "kind": "Concept", "label": concept, "properties": {"concept_id": concept}})
            edges[_edge_id(file_node["id"], concept_id, "MENTIONS")] = _edge(file_node["id"], concept_id, "MENTIONS")

    final_nodes = _with_endpoint_reference_nodes(list(nodes.values()), list(edges.values()))
    return {
        "schema": GRAPHIFY_BRIDGE_SCHEMA,
        "created_at": _now(),
        "metadata": {
            "project_root": project_root.as_posix(),
            "source_paths": source_paths,
            "scanner": "atr_fallback_project_scanner",
            "max_file_bytes": max_file_bytes,
        },
        "nodes": sorted(final_nodes, key=lambda item: item["id"]),
        "edges": sorted(edges.values(), key=lambda item: item["id"]),
    }


def load_graphify_graph(path: Path) -> dict[str, Any]:
    """Load either ATR fallback graph or common Graphify-style graph JSON."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("graph JSON must be an object")
    raw_nodes = raw.get("nodes") or raw.get("vertices") or raw.get("data", {}).get("nodes") or []
    raw_edges = raw.get("edges") or raw.get("links") or raw.get("relationships") or raw.get("data", {}).get("edges") or []
    nodes = [_normalize_project_node(item) for item in raw_nodes if isinstance(item, dict)]
    edges = [_normalize_project_edge(item) for item in raw_edges if isinstance(item, dict)]
    nodes = _with_endpoint_reference_nodes(nodes, edges)
    return {
        "schema": raw.get("schema") or raw.get("schema_version") or "graphify_project_graph",
        "created_at": raw.get("created_at") or _now(),
        "metadata": {"source_path": path.as_posix(), "source_schema": raw.get("schema") or raw.get("schema_version") or "unknown"},
        "nodes": nodes,
        "edges": edges,
    }


def import_project_graph(
    backend: KnowledgeGraphBackend,
    graph_json: Path,
    *,
    include_runtime_memory: bool = True,
    store: JsonlKnowledgeStore | None = None,
    runtime_limit: int = 500,
) -> dict[str, Any]:
    """Import Graphify/fallback project graph plus optional runtime memory into backend."""
    graph = load_graphify_graph(graph_json)
    nodes = [_project_node_for_backend(node, graph_json) for node in graph.get("nodes", [])]
    edges = [_project_edge_for_backend(edge, graph_json) for edge in graph.get("edges", [])]
    result: dict[str, Any] = {
        "ok": True,
        "tool": "knowledge.graphify.import",
        "graph_json": graph_json.as_posix(),
        "project_nodes": len(nodes),
        "project_edges": len(edges),
        "runtime_import": {},
    }
    try:
        health = backend.health()
        if not health.get("enabled", True):
            result.update({"ok": True, "enabled": False, "backend": health.get("backend", "disabled"), "nodes_written": 0, "edges_written": 0})
            return result
        node_result = backend.upsert_nodes(nodes)
        edge_result = backend.upsert_edges(edges)
        result.update(
            {
                "enabled": True,
                "backend": node_result.get("backend") or edge_result.get("backend") or health.get("backend", "unknown"),
                "nodes_written": int(node_result.get("nodes_written") or 0),
                "edges_written": int(edge_result.get("edges_written") or 0),
                "node_count": node_result.get("node_count"),
                "edge_count": edge_result.get("edge_count"),
            }
        )
        if include_runtime_memory and store is not None:
            result["runtime_import"] = import_store_to_graph(store, backend, limit=runtime_limit)
        return result
    except Exception as exc:
        return {**result, "ok": False, "error": str(exc)}


def render_graph_report(graph: dict[str, Any]) -> str:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    node_counts = Counter(str(node.get("kind") or node.get("type") or "Unknown") for node in nodes)
    edge_counts = Counter(str(edge.get("type") or "RELATED_TO") for edge in edges)
    high_degree = _high_degree(nodes, edges)[:15]
    lines = [
        "# ATR Project Knowledge Graph Report",
        "",
        f"Generated: {graph.get('created_at') or _now()}",
        f"Nodes: {len(nodes)}",
        f"Edges: {len(edges)}",
        "",
        "## Node Types",
        "",
    ]
    lines.extend(f"- {kind}: {count}" for kind, count in node_counts.most_common())
    lines.extend(["", "## Edge Types", ""])
    lines.extend(f"- {kind}: {count}" for kind, count in edge_counts.most_common())
    lines.extend(["", "## High-Connectivity Nodes", ""])
    lines.extend(f"- {item['id']} ({item['degree']})" for item in high_degree)
    lines.extend(
        [
            "",
            "## Operational Use",
            "",
            "- Use this graph as project context for Knowledge, Guardian, BO, and improvement review.",
            "- JSON/JSONL runtime memory remains the source of truth.",
            "- Do not import credentials, device passwords, private connection files, or generated hardware logs.",
            "",
        ]
    )
    return "\n".join(lines)


def render_graph_html(graph: dict[str, Any]) -> str:
    nodes = graph.get("nodes", [])[:500]
    edges = graph.get("edges", [])[:1000]
    payload = json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False, default=str)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\" />
<title>ATR Project Knowledge Graph</title>
<style>
body {{ margin: 0; font-family: Arial, sans-serif; background: #f7f8fb; color: #18202a; }}
header {{ padding: 18px 24px; background: #111827; color: white; }}
main {{ padding: 20px 24px; }}
.grid {{ display: grid; grid-template-columns: 360px 1fr; gap: 16px; }}
.card {{ background: white; border: 1px solid #d8dee9; border-radius: 10px; padding: 14px; }}
.node {{ padding: 6px 8px; margin: 4px 0; border-radius: 6px; background: #eef3ff; font-size: 13px; }}
.edge {{ color: #4b5563; font-size: 12px; padding: 3px 0; }}
pre {{ white-space: pre-wrap; word-break: break-word; }}
</style>
</head>
<body>
<header><h1>ATR Project Knowledge Graph</h1><div>{len(graph.get('nodes', []))} nodes / {len(graph.get('edges', []))} edges</div></header>
<main class=\"grid\">
<section class=\"card\"><h2>Nodes</h2><div id=\"nodes\"></div></section>
<section class=\"card\"><h2>Edges</h2><div id=\"edges\"></div></section>
</main>
<script>
const graph = {payload};
document.getElementById('nodes').innerHTML = graph.nodes.map(n => `<div class=\"node\"><b>${{n.kind || n.type || 'Node'}}</b><br>${{n.id}}</div>`).join('');
document.getElementById('edges').innerHTML = graph.edges.map(e => `<div class=\"edge\">${{e.source}} <b>${{e.type || 'RELATED_TO'}}</b> ${{e.target}}</div>`).join('');
</script>
</body>
</html>
"""


def _canonical_path(value: str) -> str:
    if (not isinstance(value, str) or not value or value.startswith('/') or '\\' in value
            or ':' in value or '\x00' in value or any(part in {'', '.', '..'} for part in value.split('/'))):
        raise ValueError("Graph references must be canonical repository-relative paths")
    return value


def _identity_map(reference_map: Mapping[str, str]) -> dict[str, str]:
    """Invert the caller's frozen source -> destination map without guessing."""
    inverse: dict[str, str] = {}
    for source, destination in reference_map.items():
        _canonical_path(source)
        _canonical_path(destination)
        if destination in inverse and inverse[destination] != source:
            raise ValueError("Ambiguous graph identity destination")
        if destination != source and destination in reference_map:
            raise ValueError("Graph identity mapping overlaps another source")
        inverse[destination] = source
    return inverse


def _reconcile_identities(graph: dict[str, Any], project_root: Path, inverse: dict[str, str],
                          files: set[str]) -> dict[str, Any]:
    """Keep historical path-derived IDs and all endpoints, recording current paths separately."""
    known_paths = files | set(inverse) | set(inverse.values())
    ordered_paths = sorted(known_paths, key=len, reverse=True)

    def identify(node_id: str) -> tuple[str, str]:
        prefix, separator, value = node_id.partition(':')
        if prefix not in {'file', 'graphify'} or not separator:
            return node_id, ''
        absolute_prefix = project_root.as_posix() + '/' if value.startswith(project_root.as_posix() + '/') else ''
        if absolute_prefix:
            value = value[len(absolute_prefix):]
        if value in known_paths:
            return prefix + ':' + absolute_prefix + inverse.get(value, value), value
        # Graphify may use a file path plus symbol identity rather than a file node.
        for path in ordered_paths:
            if value.startswith(path + ':'):
                return prefix + ':' + absolute_prefix + inverse.get(path, path) + value[len(path):], path
        if prefix == 'file':
            raise ValueError("Graph file identity is outside the explicit corpus")
        return node_id, ''

    nodes, aliases, seen = [], {}, set()
    for node in graph.get('nodes', []):
        old_id = str(node['id'])
        canonical, physical = identify(old_id)
        if canonical in seen:
            raise ValueError("Colliding graph node identities after relocation")
        seen.add(canonical)
        aliases[old_id] = canonical
        props = dict(node.get('properties') or {})
        if physical:
            props['path'] = physical
            props['identity_path'] = inverse.get(physical, physical)
        nodes.append({**node, 'id': canonical, 'properties': props})
    edges = []
    for edge in graph.get('edges', []):
        source = aliases.get(edge['source']) or identify(edge['source'])[0]
        target = aliases.get(edge['target']) or identify(edge['target'])[0]
        edge_id = edge['id']
        if edge_id == _edge_id(edge['source'], edge['target'], edge['type']):
            edge_id = _edge_id(source, target, edge['type'])
        edges.append({**edge, 'id': edge_id, 'source': source, 'target': target})
    return {**graph, 'nodes': nodes, 'edges': edges}


def _collect_files(project_root: Path, source_paths: list[str], *, max_file_bytes: int) -> list[str]:
    found: list[str] = []
    for source in source_paths:
        path = project_root / _canonical_path(source)
        if _skip_path(path, source):
            continue
        if any(item.is_symlink() for item in (path, *path.parents) if item.is_relative_to(project_root)):
            continue
        path = path.resolve()
        if not _is_relative_to(path, project_root) or not path.exists():
            continue
        if path.is_file():
            candidates = [path]
        else:
            candidates = []
            for directory, subdirs, names in os.walk(path, followlinks=False):
                base = Path(directory)
                subdirs[:] = [name for name in subdirs
                              if not (base / name).is_symlink()
                              and not _skip_path(base / name, (base / name).relative_to(project_root).as_posix())]
                candidates.extend(base / name for name in names if (base / name).is_file())
        for item in candidates:
            rel = item.relative_to(project_root).as_posix()
            if (any(part.is_symlink() for part in (item, *item.parents) if part.is_relative_to(project_root))
                    or not item.resolve().is_relative_to(project_root)):
                continue
            if _skip_path(item, rel):
                continue
            if item.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                if item.stat().st_size > max_file_bytes:
                    continue
            except OSError:
                continue
            found.append(rel)
    return sorted(set(found))


def _skip_path(path: Path, rel: str) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDED_PARTS:
        return True
    lower = rel.lower()
    name = path.name.lower()
    if any(pattern in lower or pattern in name for pattern in SECRET_NAME_PATTERNS):
        return True
    return False


def _file_node(rel_path: str, text: str) -> dict[str, Any]:
    ext = Path(rel_path).suffix.lower()
    if ext in CODE_EXTENSIONS:
        kind = "CodeFile"
    elif ext in DOC_EXTENSIONS:
        kind = "DocFile"
    elif ext in CONFIG_EXTENSIONS:
        kind = "ConfigFile"
    else:
        kind = "ProjectFile"
    return {
        "id": f"file:{rel_path}",
        "kind": kind,
        "label": rel_path,
        "properties": {"path": rel_path, "extension": ext, "sha256": hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest(), "line_count": text.count("\n") + 1},
    }


def _agent_for_path(rel_path: str) -> str:
    lowered = rel_path.lower()
    for agent_id in sorted(AGENT_IDS, key=len, reverse=True):
        if f"/{agent_id}" in lowered or lowered.startswith(f"agents/{agent_id}") or f"{agent_id}_agent" in lowered or f"{agent_id}_" in lowered or f"/{agent_id}_" in lowered:
            return agent_id
    if lowered.startswith("orchestrator/"):
        return "orchestrator"
    return ""


def _python_imports(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return sorted(imports)


def _resolve_python_import(project_root: Path, imported: str, *, repository_root: Path | None = None) -> str:
    """Resolve exact safe runtime references without opening target content."""
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', imported):
        return ""
    candidates = [project_root / f"{imported}.py", project_root / imported / "__init__.py"]
    repository_root = repository_root or project_root
    for candidate in candidates:
        rel = candidate.relative_to(repository_root).as_posix()
        if (_skip_path(candidate, rel)
                or any(part.is_symlink() for part in (candidate, *candidate.parents) if part.is_relative_to(project_root))):
            continue
        if candidate.is_file() and candidate.resolve().is_relative_to(project_root):
            return f"file:{rel}"
    return ""


def _fastapi_routes(text: str) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    pattern = re.compile(r"@(?:app|router)\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']")
    for match in pattern.finditer(text):
        routes.append({"method": match.group(1).upper(), "path": match.group(2)})
    return routes


def _tool_defs(text: str, rel_path: str) -> list[str]:
    if not (rel_path.startswith("mcp_tools/") or rel_path.startswith("device_bridges/") or rel_path.startswith("scripts/")):
        return []
    names = re.findall(r"^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", text, flags=re.MULTILINE)
    return [f"{Path(rel_path).stem}.{name}" for name in names if not name.startswith("_")][:40]


def _concepts(text: str, rel_path: str) -> list[str]:
    lower = f"{rel_path}\n{text[:20000]}".lower()
    concepts = []
    for term in ("guardian", "knowledge", "bayesian_optimization", "bo", "tpms", "gyroid", "printer", "prusaslicer", "lerobot", "utm", "calculix", "langgraph", "runtime_ide", "self_evolution", "vllm", "ollama", "pyautogui"):
        token = term.replace("_", " ")
        if term in lower or token in lower:
            concepts.append(term)
    return concepts[:20]


def _normalize_project_node(item: dict[str, Any]) -> dict[str, Any]:
    raw_id = item.get("id") or item.get("node_id") or item.get("path") or item.get("name") or item.get("label")
    node_id = str(raw_id or hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()[:16])
    if not node_id.startswith(("file:", "agent:", "module:", "api:", "tool:", "concept:", "project:", "graphify:")):
        node_id = f"graphify:{node_id}"
    kind = str(item.get("kind") or item.get("type") or item.get("label_type") or "GraphifyNode")
    label = str(item.get("label") or item.get("name") or raw_id or node_id)
    props = dict(item)
    props.setdefault("graph_source", "graphify")
    return {"id": node_id, "kind": kind, "label": label, "properties": props}


def _normalize_project_edge(item: dict[str, Any]) -> dict[str, Any]:
    source = item.get("source") or item.get("from") or item.get("start") or item.get("src")
    target = item.get("target") or item.get("to") or item.get("end") or item.get("dst")
    source_id = _normalize_ref_id(source)
    target_id = _normalize_ref_id(target)
    edge_type = str(item.get("type") or item.get("relation") or item.get("label") or "RELATED_TO").upper().replace(" ", "_")
    edge_id = str(item.get("id") or _edge_id(source_id, target_id, edge_type))
    props = dict(item)
    props.setdefault("graph_source", "graphify")
    return {"id": edge_id, "source": source_id, "target": target_id, "type": edge_type, "properties": props}


def _with_endpoint_reference_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    for edge in edges:
        for key in ("source", "target"):
            node_id = str(edge.get(key) or "")
            if not node_id or node_id in by_id:
                continue
            kind = "CodeFile" if node_id.startswith("file:") else "ExternalReference"
            label = node_id.removeprefix("file:") if node_id.startswith("file:") else node_id
            by_id[node_id] = {
                "id": node_id,
                "kind": kind,
                "label": label,
                "properties": {"generated_placeholder": True, "reason": "referenced_by_project_graph_edge"},
            }
    return list(by_id.values())


def _normalize_ref_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id") or value.get("node_id") or value.get("path") or value.get("name")
    text = str(value or "")
    if text.startswith(("file:", "agent:", "module:", "api:", "tool:", "concept:", "project:", "graphify:")):
        return text
    return f"graphify:{text}"


def _project_node_for_backend(node: dict[str, Any], graph_json: Path) -> dict[str, Any]:
    props = dict(node.get("properties") or {})
    props.update({"graph_source": "project_graph", "graph_json": graph_json.as_posix()})
    return {**node, "properties": props, "record_type": "ProjectGraph", "created_at": str(node.get("created_at") or "")}


def _project_edge_for_backend(edge: dict[str, Any], graph_json: Path) -> dict[str, Any]:
    props = dict(edge.get("properties") or {})
    props.update({"graph_source": "project_graph", "graph_json": graph_json.as_posix()})
    return {**edge, "properties": props}


def _high_degree(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    degree: Counter[str] = Counter()
    for edge in edges:
        degree[str(edge.get("source", ""))] += 1
        degree[str(edge.get("target", ""))] += 1
    known = {str(node.get("id")): node for node in nodes}
    return [{"id": node_id, "degree": count, "kind": known.get(node_id, {}).get("kind", "")} for node_id, count in degree.most_common()]


def _run_external_graphify(project_root: Path, out_dir: Path, source_paths: list[str]) -> dict[str, Any]:
    """Run installed Graphify Python API for code graph extraction.

    graphifyy exposes `graphify query/install` as CLI commands, while graph
    generation is documented as Python API usage in the installed skill. Calling
    the API directly avoids relying on shell command variants across versions.
    """
    started = _now()
    raw_dir = out_dir / "external_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    graph_json = raw_dir / "graph.json"
    graph_report = raw_dir / "GRAPH_REPORT.md"
    graph_html = raw_dir / "graph.html"
    try:
        from graphify.extract import extract
        from graphify.build import build_from_json
        from graphify.cluster import cluster, score_all
        from graphify.analyze import god_nodes, surprising_connections, suggest_questions
        from graphify.report import generate
        from graphify.export import to_html, to_json
    except Exception as exc:
        return {"ok": False, "skipped": True, "reason": "graphify Python API unavailable", "started_at": started, "error": str(exc)}

    try:
        # The scan entry point supplies concrete, bounded files, never subtrees
        # for the optional extractor to rediscover beyond the approved corpus.
        paths = [project_root / source for source in source_paths
                 if Path(source).suffix.lower() in CODE_EXTENSIONS]
        if not paths:
            return {"ok": False, "started_at": started, "reason": "graphify found no supported code files", "source_paths": source_paths}

        extraction = extract(paths)
        graph = build_from_json(extraction)
        communities = cluster(graph)
        cohesion = score_all(graph, communities)
        labels = {cid: f"Community {cid}" for cid in communities}
        gods = god_nodes(graph)
        surprises = surprising_connections(graph, communities)
        questions = suggest_questions(graph, communities, labels)
        detection = {
            "files": {"code": [p.as_posix() for p in paths], "document": [], "paper": [], "image": []},
            "total_files": len(paths),
            "total_words": sum(_safe_read(p, max_file_bytes=256_000).count(" ") + 1 for p in paths),
        }
        report = generate(graph, communities, cohesion, labels, gods, surprises, detection, {"input": 0, "output": 0}, project_root.as_posix(), suggested_questions=questions)
        graph_report.write_text(report, encoding="utf-8")
        to_json(graph, communities, graph_json.as_posix())
        try:
            to_html(graph, communities, graph_html.as_posix(), community_labels=labels)
        except Exception:
            graph_html.write_text(render_graph_html(load_graphify_graph(graph_json)), encoding="utf-8")
        return {
            "ok": graph_json.exists(),
            "engine": "graphify_python_api",
            "started_at": started,
            "graph_json": graph_json.as_posix(),
            "graph_report": graph_report.as_posix(),
            "graph_html": graph_html.as_posix(),
            "source_paths": source_paths,
            "code_file_count": len(paths),
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
        }
    except Exception as exc:
        return {"ok": False, "engine": "graphify_python_api", "started_at": started, "source_paths": source_paths, "error": str(exc)}


def _safe_read(path: Path, *, max_file_bytes: int) -> str:
    try:
        data = path.read_bytes()[:max_file_bytes]
        return data.decode("utf-8", "replace")
    except Exception:
        return ""


def _edge(source: str, target: str, edge_type: str, *, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": _edge_id(source, target, edge_type), "source": source, "target": target, "type": edge_type, "properties": properties or {}}


def _edge_id(source: str, target: str, edge_type: str) -> str:
    clean_type = re.sub(r"[^A-Za-z0-9_]+", "_", edge_type.upper())
    return f"{source}__{clean_type}__{target}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
