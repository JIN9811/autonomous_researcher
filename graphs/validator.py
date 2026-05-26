"""
File purpose:
- Validate ATR graph configs before compiling/running them.

Key classes/functions:
- validate_graph_config

Inputs/outputs:
- Input: GraphConfig plus registered handler ids
- Output: list of validation errors

Dependencies:
- graphs.schema

Modification guide:
- Safe places to edit: additional validation rules
- Risky places to edit: loosening handler allowlist validation
- Related files: graphs/compiler.py
"""

from __future__ import annotations

from graphs.schema import GraphConfig, GraphEdge, GraphNode


def validate_graph_config(
    config: GraphConfig,
    *,
    registered_handlers: set[str],
    registered_modules: set[str] | None = None,
) -> list[str]:
    """Return all graph validation errors; empty means valid."""
    errors: list[str] = []
    node_id_list = [node.id for node in config.nodes]
    node_ids = set(node_id_list)
    duplicate_nodes = sorted({node_id for node_id in node_id_list if node_id_list.count(node_id) > 1})
    for node_id in duplicate_nodes:
        errors.append(f"duplicate node id: {node_id}")

    if config.entry_node not in node_ids:
        errors.append(f"entry_node is not defined as a node: {config.entry_node}")

    for finish_node in config.finish_nodes:
        if finish_node not in node_ids:
            errors.append(f"finish node is not defined as a node: {finish_node}")

    for node in config.nodes:
        if node.handler not in registered_handlers:
            errors.append(f"node={node.id} references unregistered handler={node.handler}")
        if registered_modules is not None and node.module_id:
            module_id = _normalize_module_id(node.module_id)
            if module_id not in registered_modules:
                errors.append(f"node={node.id} references unknown module={node.module_id}")

    for edge in config.edges:
        if edge.source not in node_ids:
            errors.append(f"edge source is unknown: {edge.source}")
        if edge.target not in node_ids:
            errors.append(f"edge target is unknown: {edge.target}")

    for stage, node_id in config.stage_dispatch.items():
        if node_id not in node_ids:
            errors.append(f"stage_dispatch[{stage}] points to unknown node={node_id}")

    for source, target in config.transitions.items():
        if source not in config.stage_dispatch and source not in config.terminal_stages:
            errors.append(f"transition source is not dispatchable: {source}")
        if target not in config.stage_dispatch and target not in config.terminal_stages:
            errors.append(f"transition target is not dispatchable or terminal: {target}")

    errors.extend(_validate_stage_dispatch_contract(config, node_ids))
    errors.extend(_validate_dispatch_runtime_edges(config))
    errors.extend(_validate_logical_transition_edges(config))
    errors.extend(_validate_reachability(config, node_ids))
    errors.extend(_validate_safety_metadata(config))
    errors.extend(_validate_transition_cycle_policy(config))

    return sorted(dict.fromkeys(errors))


def _normalize_module_id(module_id: str) -> str:
    """Normalize graph module references such as modules/design to design."""
    return str(module_id).strip().rstrip("/").split("/")[-1]


def _node_by_id(config: GraphConfig) -> dict[str, GraphNode]:
    """Return node lookup. Duplicate ids are already reported by the caller."""
    return {node.id: node for node in config.nodes}


def _validate_stage_dispatch_contract(config: GraphConfig, node_ids: set[str]) -> list[str]:
    """Validate stage, node, module, and terminal dispatch consistency."""
    errors: list[str] = []
    nodes = _node_by_id(config)

    stage_values = [str(node.stage) for node in config.nodes if node.stage]
    for stage in sorted({stage for stage in stage_values if stage_values.count(stage) > 1}):
        errors.append(f"duplicate node stage: {stage}")

    for terminal_stage in config.terminal_stages:
        if terminal_stage not in config.stage_dispatch:
            errors.append(f"terminal stage is not dispatchable: {terminal_stage}")

    for stage, node_id in config.stage_dispatch.items():
        node = nodes.get(node_id)
        if not node:
            continue
        if node.stage != stage:
            errors.append(f"stage_dispatch[{stage}] points to node={node_id} with stage={node.stage}")

    for node in config.nodes:
        if node.stage and node.stage not in config.stage_dispatch:
            errors.append(f"node={node.id} declares stage={node.stage} but stage is not in stage_dispatch")
        if node.kind == "agent":
            if not node.stage:
                errors.append(f"agent node={node.id} must declare a stage")
            if not node.module_id:
                errors.append(f"agent node={node.id} must reference module_id")
        if node.kind == "terminal" and node.stage and node.stage not in config.terminal_stages:
            errors.append(f"terminal node={node.id} declares non-terminal stage={node.stage}")

    for node_id in node_ids - set(nodes):
        errors.append(f"node lookup failed for node={node_id}")
    return errors


def _runtime_edges(config: GraphConfig) -> list[GraphEdge]:
    """Return executable LangGraph edges, excluding visual/logical transition edges."""
    return [edge for edge in config.edges if edge.metadata.get("runtime_edge") != "logical_transition"]


def _validate_dispatch_runtime_edges(config: GraphConfig) -> list[str]:
    """Validate the ATR dispatch-node runtime routing contract when configured."""
    errors: list[str] = []
    nodes = _node_by_id(config)
    dispatch_nodes = [node for node in config.nodes if node.handler == "runtime.dispatch"]
    if not dispatch_nodes:
        return errors
    if len(dispatch_nodes) > 1:
        errors.append("multiple runtime.dispatch nodes are configured")
    dispatch_node = dispatch_nodes[0]
    if config.entry_node != dispatch_node.id:
        errors.append(f"runtime.dispatch node={dispatch_node.id} must be the entry_node")

    runtime_edges = _runtime_edges(config)
    dispatch_routes = {(edge.source, str(edge.condition or "")): edge.target for edge in runtime_edges if edge.source == dispatch_node.id}
    for stage, node_id in config.stage_dispatch.items():
        target = dispatch_routes.get((dispatch_node.id, stage))
        if target != node_id:
            errors.append(f"runtime.dispatch edge for stage={stage} must target node={node_id}")

    finish_nodes = set(config.finish_nodes)
    if finish_nodes:
        for stage, node_id in config.stage_dispatch.items():
            node = nodes.get(node_id)
            if not node or node.handler == "runtime.dispatch":
                continue
            if not any(edge.source == node_id and edge.target in finish_nodes for edge in runtime_edges):
                errors.append(f"stage_dispatch[{stage}] node={node_id} must have a runtime edge to a finish node")
    return errors


def _logical_stage(edge: GraphEdge, key: str, fallback: str) -> str:
    return str(edge.metadata.get(key) or fallback).strip()


def _logical_condition(edge: GraphEdge) -> str:
    return str(edge.metadata.get("condition") or edge.metadata.get("transition_condition") or edge.condition or "").strip()


def _is_default_condition(condition: str) -> bool:
    return condition.strip().lower() in {"", "default", "continue", "always"}


def _validate_logical_transition_edges(config: GraphConfig) -> list[str]:
    """Validate visual logical routes against the runtime transition table."""
    errors: list[str] = []
    logical_edges = [edge for edge in config.edges if edge.metadata.get("runtime_edge") == "logical_transition"]
    dispatchable_stages = set(config.stage_dispatch) | set(config.terminal_stages)

    for index, edge in enumerate(logical_edges, start=1):
        from_stage = _logical_stage(edge, "from_stage", edge.source)
        to_stage = _logical_stage(edge, "to_stage", edge.target)
        condition = _logical_condition(edge)
        metadata_condition = str(edge.metadata.get("condition") or "").strip()
        metadata_transition_condition = str(edge.metadata.get("transition_condition") or "").strip()

        if not from_stage:
            errors.append(f"logical_transition[{index}] missing from_stage")
        elif from_stage not in dispatchable_stages:
            errors.append(f"logical_transition[{index}] from_stage is not dispatchable or terminal: {from_stage}")
        if not to_stage:
            errors.append(f"logical_transition[{index}] missing to_stage")
        elif to_stage not in dispatchable_stages:
            errors.append(f"logical_transition[{index}] to_stage is not dispatchable or terminal: {to_stage}")

        expected_source = config.stage_dispatch.get(from_stage)
        expected_target = config.stage_dispatch.get(to_stage)
        if expected_source and edge.source != expected_source:
            errors.append(f"logical_transition[{index}] source={edge.source} does not match stage_dispatch[{from_stage}]={expected_source}")
        if expected_target and edge.target != expected_target:
            errors.append(f"logical_transition[{index}] target={edge.target} does not match stage_dispatch[{to_stage}]={expected_target}")
        if metadata_condition and metadata_transition_condition and metadata_condition != metadata_transition_condition:
            errors.append(f"logical_transition[{index}] metadata condition mismatch: {metadata_condition} != {metadata_transition_condition}")
        if edge.condition and metadata_condition and edge.condition != metadata_condition:
            errors.append(f"logical_transition[{index}] edge condition does not match metadata.condition: {edge.condition} != {metadata_condition}")
        if edge.metadata.get("default_transition") is True and config.transitions.get(from_stage) != to_stage:
            errors.append(f"logical_transition[{index}] default_transition does not match graph.transitions[{from_stage}]")

    for source, target in config.transitions.items():
        matching = [
            edge
            for edge in logical_edges
            if _logical_stage(edge, "from_stage", edge.source) == source
            and _logical_stage(edge, "to_stage", edge.target) == target
        ]
        if not matching:
            errors.append(f"transition {source}->{target} is missing a logical_transition edge")
            continue
        default_like = [
            edge
            for edge in matching
            if edge.metadata.get("default_transition") is True or _is_default_condition(_logical_condition(edge))
        ]
        if not default_like:
            errors.append(f"transition {source}->{target} is missing a default logical_transition edge")
        if len(default_like) > 1:
            errors.append(f"transition {source}->{target} has multiple default logical_transition edges")
    return errors


def _validate_reachability(config: GraphConfig, node_ids: set[str]) -> list[str]:
    """Ensure executable graph nodes are reachable from the entry node."""
    if config.entry_node not in node_ids:
        return []
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in config.edges:
        if edge.metadata.get("runtime_edge") == "logical_transition":
            continue
        if edge.source in node_ids and edge.target in node_ids:
            adjacency.setdefault(edge.source, set()).add(edge.target)
    reachable: set[str] = set()
    stack = [config.entry_node]
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(sorted(adjacency.get(current, set()) - reachable))
    ignored = set(config.finish_nodes) - node_ids
    disconnected = sorted(node_ids - reachable - ignored)
    return [f"node is disconnected from entry_node: {node_id}" for node_id in disconnected]


def _validate_safety_metadata(config: GraphConfig) -> list[str]:
    """Validate graph-level safety invariants requested by runtime metadata."""
    safety = config.metadata.get("safety") if isinstance(config.metadata.get("safety"), dict) else {}
    errors: list[str] = []
    if bool(safety.get("guardian_required")):
        guardian_node = config.stage_dispatch.get("guardian")
        if not guardian_node or guardian_node not in config.node_ids:
            errors.append("safety.guardian_required is true but guardian stage is not dispatchable")
        if "guardian" not in config.transitions:
            errors.append("safety.guardian_required is true but guardian transition is missing")
        terminal_targets = set(config.terminal_stages)
        guardian_candidates = config.transition_candidates("guardian")
        has_stop_route = any(
            str(candidate.get("to_stage")) in terminal_targets and "stop" in str(candidate.get("condition", "")).lower()
            for candidate in guardian_candidates
        )
        has_error_route = any(
            str(candidate.get("to_stage")) in terminal_targets and "error" in str(candidate.get("condition", "")).lower()
            for candidate in guardian_candidates
        )
        if not has_stop_route:
            errors.append("safety.guardian_required is true but guardian stop route to terminal stage is missing")
        if not has_error_route:
            errors.append("safety.guardian_required is true but guardian error route to terminal stage is missing")
    return errors


def _validate_transition_cycle_policy(config: GraphConfig) -> list[str]:
    """Reject transition cycles unless they pass through Guardian or a terminal stage."""
    errors: list[str] = []
    transition_sources = set(config.transitions)
    allowed_cycle_nodes = {"guardian", *config.terminal_stages}
    for start in sorted(transition_sources):
        seen_order: list[str] = []
        seen_index: dict[str, int] = {}
        stage = start
        while stage in config.transitions:
            if stage in seen_index:
                cycle = seen_order[seen_index[stage] :]
                if not set(cycle).intersection(allowed_cycle_nodes):
                    errors.append("transition cycle without guardian/terminal: " + " -> ".join([*cycle, stage]))
                break
            seen_index[stage] = len(seen_order)
            seen_order.append(stage)
            stage = config.transitions[stage]
            if stage in config.terminal_stages:
                break
    return sorted(set(errors))
