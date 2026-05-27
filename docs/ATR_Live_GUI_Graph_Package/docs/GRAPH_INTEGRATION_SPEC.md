# LangGraph Integration Spec

## Principle
The graph shown in the UI must be the graph used by the runtime.
The frontend edits configuration. The backend compiler turns the configuration into executable LangGraph.

## Data Flow
Frontend Graph Editor -> Graph Config -> Backend Validator -> Backend Compiler -> LangGraph Runtime -> Event Stream -> Frontend State.

## Graph Config Requirements
- graph_id
- version
- entry_node
- nodes
- edges
- modules
- handlers
- schemas
- model_routes
- tool_permissions
- safety_rules

## Handler Registry
The frontend may only select handlers exposed by backend registry.
Do not permit arbitrary Python paths unless registered.

## Validation Rules
- unique node IDs
- valid edge endpoints
- entry node exists
- handler exists
- schema compatibility
- allowed cycles only
- live-mode safety rules
- device permission checks

## Module Internal Graphs
Each agent module may expose an internal editable graph.
Example: Design Agent may contain load_objective -> generate_candidates -> validate_geometry -> export_stl -> handoff.

## Versioning
Every compiled graph produces a deterministic hash. Runs must record graph_id, graph_version, and graph_hash.
