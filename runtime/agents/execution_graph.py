"""Validated, allowlisted execution graphs shared by agent owners and Runtime IDE.

The graph document names registered operations; it never imports or evaluates code.
Compilation makes a detached invocation snapshot so active runs cannot observe later
module-file edits.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import inspect
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Iterable, Mapping
from uuid import uuid4


EXECUTION_GRAPH_SCHEMA = "ax4lab.execution_graph.v1"
EXECUTION_TRACE_SCHEMA = "ax4lab.execution_trace.v1"
EXECUTION_EDGE_KINDS = frozenset({"execution", "validation", "evidence"})
EXECUTION_AREAS = frozenset({"high", "middle", "low", "knowledge", "guardian"})


class ExecutionGraphError(ValueError):
    """The editable graph does not satisfy the registered execution contract."""


@dataclass(frozen=True)
class OperationResult:
    """One registered operation's routed outcome and invocation-local outputs."""

    outcome: str = "next"
    outputs: Mapping[str, Any] = field(default_factory=dict)


OperationHandler = Callable[[Any, Any, dict[str, Any], Mapping[str, Any]], Awaitable[OperationResult]]


@dataclass(frozen=True)
class ExecutionOperation:
    """One code-owned operation available to an editable module definition."""

    handler: str
    operation: OperationHandler
    label: str = ""
    description: str = ""
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ("next",)
    outcome_produces: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)
    llm: bool = False

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_.:-]*", self.handler):
            raise ValueError(f"Invalid execution handler: {self.handler}")
        if not callable(self.operation):
            raise ValueError(f"Execution handler is not callable: {self.handler}")
        if not self.outcomes or any(not str(item).strip() for item in self.outcomes):
            raise ValueError(f"Execution handler requires outcomes: {self.handler}")
        if len(set(self.outcomes)) != len(self.outcomes):
            raise ValueError(f"Duplicate execution outcome: {self.handler}")
        unknown_outcomes = set(self.outcome_produces) - set(self.outcomes)
        if unknown_outcomes:
            raise ValueError(f"Unknown outcome output contract for {self.handler}: {sorted(unknown_outcomes)}")
        claimed = set(self.produces)
        for outcome, outputs in self.outcome_produces.items():
            if not isinstance(outputs, tuple) or any(not str(item).strip() for item in outputs):
                raise ValueError(f"Invalid outcome outputs for {self.handler}: {outcome}")
            overlap = claimed & set(outputs)
            if overlap:
                raise ValueError(f"Output must have one ownership contract for {self.handler}: {sorted(overlap)}")
            claimed.update(outputs)

    def outputs_for(self, outcome: str) -> tuple[str, ...]:
        """Return the exact outputs required for one operation outcome."""
        return (*self.produces, *self.outcome_produces.get(outcome, ()))

    def outcome_output_keys(self) -> set[str]:
        """Return values invalidated whenever this operation makes a new decision."""
        return {key for outputs in self.outcome_produces.values() for key in outputs}

    def describe(self) -> dict[str, Any]:
        return {
            "handler": self.handler,
            "label": self.label or self.handler,
            "description": self.description,
            "requires": list(self.requires),
            "produces": list(self.produces),
            "outcome_produces": {
                outcome: list(self.outcome_produces.get(outcome, ())) for outcome in self.outcomes
            },
            "outcomes": list(self.outcomes),
            "config": {key: _describe_config_rule(value) for key, value in self.config.items()},
            "llm": self.llm,
        }


@dataclass(frozen=True)
class ExecutionCatalog:
    """Safe module-local allowlist; public YAML cannot add callables."""

    module_id: str
    operations: tuple[ExecutionOperation, ...]
    inputs: tuple[str, ...] = ()
    required_outputs: tuple[str, ...] = ()
    implementation_structure: Callable[[], dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        handlers = [operation.handler for operation in self.operations]
        if not self.module_id or len(handlers) != len(set(handlers)):
            raise ValueError("Execution catalog requires a module id and unique handlers")
        if any(not str(item).strip() for item in self.required_outputs):
            raise ValueError("Execution catalog required outputs must be nonempty names")

    def operation(self, handler: str) -> ExecutionOperation:
        for operation in self.operations:
            if operation.handler == handler:
                return operation
        raise KeyError(handler)

    def describe(self) -> dict[str, Any]:
        return {
            "schema": "ax4lab.execution_catalog.v1",
            "module_id": self.module_id,
            "inputs": list(self.inputs),
            "required_outputs": list(self.required_outputs),
            "operations": [operation.describe() for operation in self.operations],
            "implementation_structure": deepcopy(self.implementation_structure()) if self.implementation_structure else None,
        }


@dataclass(frozen=True)
class CompiledExecutionNode:
    id: str
    handler: str
    label: str
    area: str
    llm: Any
    config: Mapping[str, Any]
    position: Mapping[str, Any]


@dataclass(frozen=True)
class CompiledExecutionEdge:
    source: str
    target: str
    on: str
    kind: str

    def describe(self) -> dict[str, str]:
        return {"source": self.source, "target": self.target, "on": self.on, "kind": self.kind}


@dataclass(frozen=True)
class CompiledExecutionGraph:
    schema: str
    module_id: str
    entry: str
    nodes: tuple[CompiledExecutionNode, ...]
    edges: tuple[CompiledExecutionEdge, ...]
    terminals: tuple[str, ...]
    revision: str
    catalog: ExecutionCatalog

    def node(self, node_id: str) -> CompiledExecutionNode:
        return next(node for node in self.nodes if node.id == node_id)

    def edge(self, node_id: str, outcome: str) -> CompiledExecutionEdge | None:
        return next((edge for edge in self.edges if edge.source == node_id and edge.on == outcome), None)

    def describe(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "entry": self.entry,
            "nodes": [
                {
                    "id": node.id,
                    "handler": node.handler,
                    "label": node.label,
                    "area": node.area,
                    **({"llm": deepcopy(node.llm)} if node.llm is not None else {}),
                    **({"config": deepcopy(dict(node.config))} if node.config else {}),
                    **({"position": deepcopy(dict(node.position))} if node.position else {}),
                }
                for node in self.nodes
            ],
            "edges": [edge.describe() for edge in self.edges],
            "terminals": list(self.terminals),
        }


@dataclass(frozen=True)
class ExecutionRunResult:
    graph_revision: str
    result: Any
    outputs: Mapping[str, Any]
    trace: tuple[dict[str, Any], ...]


def execution_graph_from_context(
    ctx: Any,
    module_id: str,
    default: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Read a detached module definition only from the invocation-scoped context."""
    runtime_config = getattr(ctx, "runtime_module_config", None)
    if callable(runtime_config):
        payload = runtime_config()
        if isinstance(payload, dict) and str(payload.get("id") or payload.get("module_id") or "") == module_id:
            graph = payload.get("execution_graph")
            if isinstance(graph, dict):
                return deepcopy(graph)
    return default()


def installed_execution_graph(module_id: str) -> dict[str, Any]:
    """Load the installed module's one executable definition for a new invocation."""
    from graphs.schema import load_module_config

    path = Path(__file__).resolve().parents[1] / "graphs" / "modules" / module_id / "module.yaml"
    module = load_module_config(path)
    if module.execution_graph is None:
        raise ExecutionGraphError(f"Installed module has no execution_graph: {module_id}")
    return module.execution_graph.model_dump(mode="json", exclude_none=True, by_alias=True)


def execution_event_emitter(ctx: Any) -> Callable[[dict[str, Any]], Any] | None:
    """Return the invocation's trace sink without exposing its private scope."""
    callback = getattr(ctx, "emit_execution_event", None)
    return callback if callable(callback) else None


def _describe_config_rule(rule: Any) -> dict[str, Any]:
    if isinstance(rule, type):
        return {"type": rule.__name__}
    if isinstance(rule, (tuple, list, set, frozenset)):
        return {"enum": list(rule)}
    if isinstance(rule, dict):
        return deepcopy(rule)
    return {"validation": "code_owned"}


def _config_value_valid(value: Any, rule: Any) -> bool:
    if isinstance(rule, type):
        return type(value) is rule if rule in {bool, int, float, str} else isinstance(value, rule)
    if isinstance(rule, (tuple, list, set, frozenset)):
        return value in rule
    if isinstance(rule, dict):
        expected = rule.get("type")
        types = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
        if expected in types and not isinstance(value, types[expected]):
            return False
        if "enum" in rule and value not in rule["enum"]:
            return False
        if "minimum" in rule and (not isinstance(value, (int, float)) or value < rule["minimum"]):
            return False
        if "maximum" in rule and (not isinstance(value, (int, float)) or value > rule["maximum"]):
            return False
        return True
    return bool(rule(value)) if callable(rule) else False


def _canonical_revision(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compile_execution_graph(graph: Mapping[str, Any], catalog: ExecutionCatalog) -> CompiledExecutionGraph:
    """Validate and detach one graph before any registered operation is dispatched."""
    payload = deepcopy(dict(graph))
    if payload.get("schema") != EXECUTION_GRAPH_SCHEMA:
        raise ExecutionGraphError(f"schema must be {EXECUTION_GRAPH_SCHEMA}")
    allowed_graph_keys = {"schema", "entry", "nodes", "edges", "terminals"}
    if set(payload) != allowed_graph_keys:
        raise ExecutionGraphError(f"graph fields must be exactly {sorted(allowed_graph_keys)}")
    raw_nodes, raw_edges, raw_terminals = payload.get("nodes"), payload.get("edges"), payload.get("terminals")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ExecutionGraphError("nodes must be a nonempty list")
    if not isinstance(raw_edges, list) or not isinstance(raw_terminals, list) or not raw_terminals:
        raise ExecutionGraphError("edges must be a list and terminals must be nonempty")

    nodes: list[CompiledExecutionNode] = []
    operations: dict[str, ExecutionOperation] = {item.handler: item for item in catalog.operations}
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            raise ExecutionGraphError(f"node {index} must be an object")
        allowed = {"id", "handler", "label", "area", "llm", "config", "position"}
        if set(raw) - allowed:
            raise ExecutionGraphError(f"node {index} has unknown fields: {sorted(set(raw) - allowed)}")
        node_id, handler = str(raw.get("id") or "").strip(), str(raw.get("handler") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", node_id):
            raise ExecutionGraphError(f"node {index} has invalid id")
        if handler not in operations:
            raise ExecutionGraphError(f"node {node_id} has unknown handler: {handler}")
        area = str(raw.get("area") or "").strip()
        if area not in EXECUTION_AREAS:
            raise ExecutionGraphError(f"node {node_id} has invalid area: {area}")
        config = raw.get("config", {})
        if not isinstance(config, dict):
            raise ExecutionGraphError(f"node {node_id} config must be an object")
        spec = operations[handler]
        unknown_config = set(config) - set(spec.config)
        if unknown_config:
            raise ExecutionGraphError(f"node {node_id} has unknown config: {sorted(unknown_config)}")
        for key, value in config.items():
            if not _config_value_valid(value, spec.config[key]):
                raise ExecutionGraphError(f"node {node_id} has invalid config value: {key}")
        llm = raw.get("llm")
        if llm is not None and not isinstance(llm, bool):
            raise ExecutionGraphError(f"node {node_id} llm must be a boolean annotation")
        if llm is not None and not spec.llm:
            raise ExecutionGraphError(f"node {node_id} handler does not accept llm config")
        position = raw.get("position", {})
        if not isinstance(position, dict):
            raise ExecutionGraphError(f"node {node_id} position must be an object")
        nodes.append(CompiledExecutionNode(
            id=node_id,
            handler=handler,
            label=str(raw.get("label") or spec.label or node_id),
            area=area,
            llm=deepcopy(llm),
            config=MappingProxyType(deepcopy(config)),
            position=MappingProxyType(deepcopy(position)),
        ))
    ids = [node.id for node in nodes]
    if len(ids) != len(set(ids)):
        raise ExecutionGraphError("duplicate node id")
    node_ids = set(ids)
    entry = str(payload.get("entry") or "").strip()
    terminals = tuple(str(item).strip() for item in raw_terminals)
    if entry not in node_ids:
        raise ExecutionGraphError(f"entry references unknown node: {entry}")
    if any(item not in node_ids for item in terminals):
        raise ExecutionGraphError("terminals reference unknown node")
    if len(terminals) != len(set(terminals)):
        raise ExecutionGraphError("duplicate terminal node")

    edges: list[CompiledExecutionEdge] = []
    for index, raw in enumerate(raw_edges):
        if not isinstance(raw, dict) or set(raw) != {"source", "target", "on", "kind"}:
            raise ExecutionGraphError(f"edge {index} must contain source, target, on, kind")
        source, target = str(raw["source"]).strip(), str(raw["target"]).strip()
        if source not in node_ids:
            raise ExecutionGraphError(f"edge {index} has unknown source: {source}")
        if target not in node_ids:
            raise ExecutionGraphError(f"edge {index} has unknown target: {target}")
        outcome, kind = str(raw["on"]).strip(), str(raw["kind"]).strip()
        operation = operations[next(node.handler for node in nodes if node.id == source)]
        if outcome not in operation.outcomes:
            raise ExecutionGraphError(f"edge {index} uses invalid outcome {outcome} for {source}")
        if kind not in EXECUTION_EDGE_KINDS:
            raise ExecutionGraphError(f"edge {index} has invalid kind: {kind}")
        edges.append(CompiledExecutionEdge(source, target, outcome, kind))

    outgoing: dict[str, list[CompiledExecutionEdge]] = {node_id: [] for node_id in node_ids}
    incoming: dict[str, list[CompiledExecutionEdge]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        outgoing[edge.source].append(edge)
        incoming[edge.target].append(edge)
    reachable: set[str] = set()
    pending = [entry]
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        pending.extend(edge.target for edge in outgoing[current])
    if reachable != node_ids:
        raise ExecutionGraphError(f"unreachable nodes: {sorted(node_ids - reachable)}")

    indegree = {node_id: len(incoming[node_id]) for node_id in node_ids}
    queue = [node_id for node_id in ids if indegree[node_id] == 0]
    topological: list[str] = []
    while queue:
        current = queue.pop(0)
        topological.append(current)
        for edge in outgoing[current]:
            indegree[edge.target] -= 1
            if indegree[edge.target] == 0:
                queue.append(edge.target)
    if len(topological) != len(node_ids):
        raise ExecutionGraphError("execution graph contains a cycle")

    terminal_set = set(terminals)
    for node in nodes:
        node_edges = outgoing[node.id]
        if node.id in terminal_set:
            if node_edges:
                raise ExecutionGraphError(f"terminal node {node.id} cannot have outgoing edges")
            continue
        outcomes = [edge.on for edge in node_edges]
        expected = set(operations[node.handler].outcomes)
        if set(outcomes) != expected or len(outcomes) != len(set(outcomes)):
            raise ExecutionGraphError(
                f"node {node.id} has ambiguous or incomplete outcome routes: expected={sorted(expected)} actual={sorted(outcomes)}"
            )
    leaves = {node_id for node_id, node_edges in outgoing.items() if not node_edges}
    if leaves != terminal_set:
        raise ExecutionGraphError(f"terminals must match graph leaves: expected={sorted(leaves)}")

    available_after_edge: dict[CompiledExecutionEdge, set[str]] = {}
    initial = set(catalog.inputs)
    node_by_id = {node.id: node for node in nodes}
    for node_id in topological:
        predecessors = incoming[node_id]
        available_before = initial if not predecessors else set.intersection(
            *(available_after_edge[edge] for edge in predecessors)
        )
        operation = operations[node_by_id[node_id].handler]
        missing = set(operation.requires) - available_before
        if missing:
            raise ExecutionGraphError(f"node {node_id} required input has no producer on every path: {sorted(missing)}")
        common_after = (available_before - operation.outcome_output_keys()) | set(operation.produces)
        if node_id in terminal_set:
            for outcome in operation.outcomes:
                terminal_outputs = set(operation.outputs_for(outcome))
                missing_result = set(catalog.required_outputs) - terminal_outputs
                if missing_result:
                    raise ExecutionGraphError(
                        f"terminal {node_id} outcome {outcome} cannot produce required catalog outputs: {sorted(missing_result)}"
                    )
            continue
        for edge in outgoing[node_id]:
            available_after_edge[edge] = common_after | set(operation.outcome_produces.get(edge.on, ()))

    canonical = {
        "schema": EXECUTION_GRAPH_SCHEMA,
        "entry": entry,
        "nodes": [
            {
                "id": node.id, "handler": node.handler, "label": node.label, "area": node.area,
                **({"llm": deepcopy(node.llm)} if node.llm is not None else {}),
                **({"config": deepcopy(dict(node.config))} if node.config else {}),
                **({"position": deepcopy(dict(node.position))} if node.position else {}),
            }
            for node in nodes
        ],
        "edges": [edge.describe() for edge in edges],
        "terminals": list(terminals),
    }
    return CompiledExecutionGraph(
        schema=EXECUTION_GRAPH_SCHEMA,
        module_id=catalog.module_id,
        entry=entry,
        nodes=tuple(nodes),
        edges=tuple(edges),
        terminals=terminals,
        revision=_canonical_revision(canonical),
        catalog=catalog,
    )


async def _emit(callback: Callable[[dict[str, Any]], Any] | None, event: dict[str, Any]) -> None:
    if callback is None:
        return
    result = callback(event)
    if inspect.isawaitable(result):
        await result


async def run_execution_graph(
    compiled: CompiledExecutionGraph,
    state: Any,
    ctx: Any,
    *,
    inputs: Mapping[str, Any] | None = None,
    emit: Callable[[dict[str, Any]], Any] | None = None,
    invocation: Mapping[str, Any] | None = None,
) -> ExecutionRunResult:
    """Run only compiled edges and registered callables in one private scope."""
    scope = deepcopy(dict(inputs or {}))
    identity = dict(invocation or {})
    identity.setdefault("run_id", str(getattr(state, "run_id", "") or ""))
    identity.setdefault("loop_index", int(getattr(state, "loop_count", 0) or 0))
    identity.setdefault("invocation_id", uuid4().hex)
    identity = {key: identity.get(key) for key in ("run_id", "loop_index", "invocation_id")}
    base = {
        "schema": EXECUTION_TRACE_SCHEMA,
        "module_id": compiled.module_id,
        "graph_revision": compiled.revision,
        **identity,
    }
    trace: list[dict[str, Any]] = []

    async def event(event_type: str, **payload: Any) -> None:
        await _emit(emit, {"type": event_type, "payload": {**base, **payload}})

    await event("execution.graph.started", node_id=compiled.entry, status="running")
    current = compiled.entry
    try:
        while True:
            node = compiled.node(current)
            operation = compiled.catalog.operation(node.handler)
            started = {"node_id": node.id, "handler": node.handler, "status": "started"}
            trace.append(started)
            await event("execution.node.started", **started)
            try:
                for key in operation.outcome_output_keys():
                    scope.pop(key, None)
                operation_result = await operation.operation(state, ctx, scope, node.config)
                if not isinstance(operation_result, OperationResult):
                    raise TypeError(f"Registered operation {node.handler} returned invalid result")
                if operation_result.outcome not in operation.outcomes:
                    raise ExecutionGraphError(
                        f"Registered operation {node.handler} returned undeclared outcome"
                    )
                outputs = dict(operation_result.outputs)
                expected_outputs = set(operation.outputs_for(operation_result.outcome))
                undeclared = set(outputs) - expected_outputs
                missing = expected_outputs - set(outputs)
                if undeclared or missing:
                    raise ExecutionGraphError(
                        f"Registered operation {node.handler} output contract mismatch"
                    )
                if node.id in compiled.terminals:
                    missing_result = set(compiled.catalog.required_outputs) - set(outputs)
                    if missing_result:
                        raise ExecutionGraphError(
                            f"terminal {node.id} missing required catalog outputs"
                        )
            except asyncio.CancelledError:
                trace.append({"node_id": node.id, "handler": node.handler, "status": "cancelled"})
                await event("execution.node.cancelled", node_id=node.id, handler=node.handler, status="cancelled")
                await event("execution.graph.cancelled", node_id=node.id, status="cancelled")
                raise
            except Exception as exc:
                trace.append({"node_id": node.id, "handler": node.handler, "status": "failed", "error_type": type(exc).__name__})
                await event("execution.node.failed", node_id=node.id, handler=node.handler, status="failed", error_type=type(exc).__name__)
                await event("execution.graph.failed", node_id=node.id, status="failed", error_type=type(exc).__name__)
                raise
            scope.update(outputs)
            completed = {
                "node_id": node.id,
                "handler": node.handler,
                "status": "completed",
                "outcome": operation_result.outcome,
            }
            trace.append(completed)
            await event("execution.node.completed", **completed)
            if node.id in compiled.terminals:
                await event("execution.graph.completed", node_id=node.id, status="completed", outcome=operation_result.outcome)
                return ExecutionRunResult(
                    graph_revision=compiled.revision,
                    result=scope.get("agent_result"),
                    outputs=MappingProxyType(dict(scope)),
                    trace=tuple(trace),
                )
            edge = compiled.edge(node.id, operation_result.outcome)
            if edge is None:  # Compile-time completeness should make this unreachable.
                raise ExecutionGraphError(f"No edge for node={node.id} outcome={operation_result.outcome}")
            await event(
                "execution.edge.traversed",
                node_id=edge.target,
                status="traversed",
                edge=edge.describe(),
            )
            current = edge.target
    except asyncio.CancelledError:
        raise
