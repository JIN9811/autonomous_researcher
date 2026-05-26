"""
File purpose:
- Safely register and execute explicitly approved Module Designer adapters.

Key functions:
- validate_generated_adapter_file
- load_generated_adapter_run

Safety model:
- Generated Python is never executed just because it exists on disk.
- A module must set handler=module.generated_adapter and metadata.generated_adapter_approved=true.
- The adapter file is statically checked before import and before every runtime load.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
from pathlib import Path
from typing import Any, Awaitable, Callable

from agents.base_agent import AgentResult

GENERATED_MODULE_HANDLER_ID = "module.generated_adapter"

_ALLOWED_IMPORT_ROOTS = {
    "agents",
    "collections",
    "dataclasses",
    "datetime",
    "enum",
    "json",
    "math",
    "orchestrator",
    "statistics",
    "typing",
}

_BLOCKED_IMPORT_ROOTS = {
    "asyncio",
    "ctypes",
    "device_bridges",
    "fcntl",
    "glob",
    "httpx",
    "importlib",
    "mcp_tools",
    "multiprocessing",
    "os",
    "pathlib",
    "pickle",
    "requests",
    "shutil",
    "signal",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}

_ALLOWED_TOP_LEVEL = (
    ast.Import,
    ast.ImportFrom,
    ast.Assign,
    ast.AnnAssign,
    ast.Expr,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
)


def safe_generated_module_id(module_id: str) -> str:
    """Return a safe single path segment for generated module ids."""
    clean = str(module_id or "").strip()
    if not clean:
        raise ValueError("module_id cannot be empty")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in clean)
    if safe != clean:
        raise ValueError(f"Unsafe module_id={module_id}")
    return safe


def generated_adapter_path(modules_root: Path, module_id: str) -> Path:
    """Return the canonical handler.py path for one generated module."""
    return Path(modules_root) / safe_generated_module_id(module_id) / "handler.py"


def _import_roots(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if node.module:
        return [node.module.split(".")[0]]
    return []


def _top_level_assignment_has_call(node: ast.Assign | ast.AnnAssign) -> bool:
    value = node.value if isinstance(node, ast.AnnAssign) else node.value
    return any(isinstance(child, (ast.Call, ast.Await, ast.Yield, ast.YieldFrom)) for child in ast.walk(value))


def validate_generated_adapter_source(source: str) -> list[str]:
    """Statically validate generated adapter source before import/execution."""
    errors: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"generated adapter syntax error: {exc}"]

    run_defs = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"]
    if not run_defs:
        errors.append("generated adapter must define async run(state, ctx)")
    elif len(run_defs) > 1:
        errors.append("generated adapter must define exactly one async run function")
    else:
        args = run_defs[0].args.args
        if len(args) < 2:
            errors.append("generated adapter run must accept state and ctx arguments")

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if not isinstance(node, _ALLOWED_TOP_LEVEL):
            errors.append(f"top-level statement is not allowed: {node.__class__.__name__}")
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for root in _import_roots(node):
                if root in _BLOCKED_IMPORT_ROOTS:
                    errors.append(f"blocked import in generated adapter: {root}")
                elif root not in _ALLOWED_IMPORT_ROOTS:
                    errors.append(f"unapproved import in generated adapter: {root}")
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and _top_level_assignment_has_call(node):
            errors.append("top-level assignments may not call functions")

    return errors


def validate_generated_adapter_file(path: Path) -> list[str]:
    """Validate one generated adapter file path and source."""
    if not path.exists() or not path.is_file():
        return [f"generated adapter file is missing: {path}"]
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"generated adapter file is unreadable: {exc}"]
    return validate_generated_adapter_source(source)


def generated_adapter_enabled(module_id: str, module_payload: dict[str, Any], modules_root: Path) -> tuple[bool, list[str]]:
    """Return whether a module is explicitly approved for generated adapter execution."""
    module = module_payload.get("module", module_payload) if isinstance(module_payload, dict) else {}
    module = module if isinstance(module, dict) else {}
    metadata = module.get("metadata") if isinstance(module.get("metadata"), dict) else {}
    errors: list[str] = []
    if module.get("handler") != GENERATED_MODULE_HANDLER_ID:
        errors.append(f"module.handler must be {GENERATED_MODULE_HANDLER_ID}")
    if not bool(metadata.get("generated_adapter_approved")):
        errors.append("metadata.generated_adapter_approved must be true")
    if metadata.get("pending_handler_registration") is True:
        errors.append("metadata.pending_handler_registration must be false")
    errors.extend(validate_generated_adapter_file(generated_adapter_path(modules_root, module_id)))
    return not errors, errors


def load_generated_adapter_run(modules_root: Path, module_id: str) -> Callable[[Any, Any], Awaitable[AgentResult]]:
    """Load one validated generated adapter run coroutine."""
    path = generated_adapter_path(modules_root, module_id)
    errors = validate_generated_adapter_file(path)
    if errors:
        raise RuntimeError("; ".join(errors))
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    safe_id = safe_generated_module_id(module_id)
    module_name = f"atr_generated_{safe_id}_{source_hash}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import generated adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = getattr(module, "run", None)
    if not callable(run):
        raise RuntimeError("generated adapter does not expose callable run")
    if not inspect.iscoroutinefunction(run):
        raise RuntimeError("generated adapter run must be async")
    return run
