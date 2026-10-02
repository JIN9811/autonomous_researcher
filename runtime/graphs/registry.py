"""
File purpose:
- Provide an allowlisted handler registry for config-driven LangGraph execution.

Key classes/functions:
- HandlerRegistry

Inputs/outputs:
- Input: registered async node handlers
- Output: safe lookup by handler id during graph compilation

Dependencies:
- inspect
- typing

Modification guide:
- Safe places to edit: registration helpers and introspection metadata
- Risky places to edit: allowing arbitrary import strings from GUI/config
- Related files: graphs/compiler.py, orchestrator/langgraph_runtime.py
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Any

RuntimeGraphState = dict[str, Any]
RuntimeHandler = Callable[[RuntimeGraphState], RuntimeGraphState | Awaitable[RuntimeGraphState]]


@dataclass(frozen=True)
class HandlerInfo:
    """Introspected metadata for one allowlisted runtime handler."""

    handler_id: str
    module: str
    qualname: str
    signature: str
    doc: str
    is_async: bool
    accepts_runtime_state: bool
    errors: list[str]

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-serializable handler metadata for APIs and GUI inspectors."""
        return asdict(self)


class HandlerRegistry:
    """Allowlist of executable graph node handlers with signature metadata."""

    def __init__(self) -> None:
        self._handlers: dict[str, RuntimeHandler] = {}

    def register(self, handler_id: str, handler: RuntimeHandler) -> None:
        """Register one handler under a stable id."""
        clean_id = handler_id.strip()
        if not clean_id:
            raise ValueError("handler_id cannot be empty")
        if not callable(handler):
            raise ValueError(f"handler is not callable: {clean_id}")
        self._handlers[clean_id] = handler

    def get(self, handler_id: str) -> RuntimeHandler:
        """Return one allowlisted handler, raising clear error when missing."""
        if handler_id not in self._handlers:
            raise KeyError(f"LangGraph handler is not registered: {handler_id}")
        return self._handlers[handler_id]

    def names(self) -> list[str]:
        """List registered handler ids."""
        return sorted(self._handlers.keys())

    def as_mapping(self) -> dict[str, RuntimeHandler]:
        """Return a shallow copy for compiler use."""
        return dict(self._handlers)

    def info(self, handler_id: str) -> HandlerInfo:
        """Return inspected metadata for one registered handler."""
        return _handler_info(handler_id, self.get(handler_id))

    def metadata(self, handler_id: str) -> dict[str, Any]:
        """Return JSON-ready inspected metadata for one registered handler."""
        return self.info(handler_id).as_dict()

    def metadata_all(self) -> list[dict[str, Any]]:
        """Return JSON-ready metadata for all registered handlers."""
        return [self.metadata(handler_id) for handler_id in self.names()]

    def validation_errors(self, handler_ids: Iterable[str] | None = None) -> dict[str, list[str]]:
        """Return signature/callability errors for selected registered handlers."""
        selected = set(handler_ids) if handler_ids is not None else set(self._handlers)
        errors: dict[str, list[str]] = {}
        for handler_id in sorted(selected):
            if handler_id not in self._handlers:
                continue
            info = self.info(handler_id)
            if info.errors:
                errors[handler_id] = list(info.errors)
        return errors


def _handler_info(handler_id: str, handler: RuntimeHandler) -> HandlerInfo:
    """Inspect one runtime handler without executing it."""
    module = getattr(handler, "__module__", handler.__class__.__module__)
    qualname = getattr(handler, "__qualname__", handler.__class__.__qualname__)
    doc = inspect.getdoc(handler) or ""
    is_async = inspect.iscoroutinefunction(handler) or inspect.isawaitable(handler)
    errors: list[str] = []
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError) as exc:
        return HandlerInfo(
            handler_id=handler_id,
            module=str(module),
            qualname=str(qualname),
            signature="<uninspectable>",
            doc=doc,
            is_async=bool(is_async),
            accepts_runtime_state=False,
            errors=[f"signature is not inspectable: {exc}"],
        )
    errors.extend(_runtime_state_signature_errors(signature))
    return HandlerInfo(
        handler_id=handler_id,
        module=str(module),
        qualname=str(qualname),
        signature=str(signature),
        doc=doc,
        is_async=bool(is_async),
        accepts_runtime_state=not errors,
        errors=errors,
    )


def _runtime_state_signature_errors(signature: inspect.Signature) -> list[str]:
    """Validate that LangGraph can call handler(runtime_state) safely."""
    params = list(signature.parameters.values())
    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in params):
        return []

    positional = [
        param
        for param in params
        if param.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    ]
    if not positional:
        return ["handler must accept one runtime_state positional argument"]

    required_positional = [param for param in positional if param.default is inspect.Parameter.empty]
    if len(required_positional) > 1:
        required = ", ".join(param.name for param in required_positional)
        return [f"handler has too many required positional parameters for LangGraph call: {required}"]

    required_keyword_only = [
        param.name
        for param in params
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default is inspect.Parameter.empty
    ]
    if required_keyword_only:
        return ["handler has required keyword-only parameters: " + ", ".join(required_keyword_only)]
    return []
