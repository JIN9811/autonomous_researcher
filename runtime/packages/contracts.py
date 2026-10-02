"""Strict version-one transport schemas; references never grant code execution."""
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from graphs.schema import GraphConfig, GraphNode, GraphEdge

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,95}$")]
ExactVersion = Annotated[str, StringConstraints(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")]
Handler = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")]
ModuleReference = Annotated[str, StringConstraints(pattern=r"^(modules/)?[a-z][a-z0-9_-]{0,95}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class PackageReference(StrictModel):
    id: Identifier
    version: ExactVersion


class PortableBinding(StrictModel):
    id: Identifier
    kind: Literal["device", "model", "storage", "service"]
    owner_id: Identifier
    required: bool = True


class ExternalOwner(StrictModel):
    handler: Handler
    module_id: Identifier | None = None


class AgentPackage(StrictModel):
    schema_: Literal["ax4lab.agent_package.v1"] = Field(alias="schema")
    id: Identifier
    version: ExactVersion
    agent_module: PackageReference
    handler: Handler
    module_reference: Annotated[str, StringConstraints(pattern=r"^graphs/modules/[a-z][a-z0-9_-]{0,95}/module\.yaml$")]
    bridge_modules: list[PackageReference] = Field(default_factory=list)
    ownership: dict[str, Any] = Field(default_factory=dict)


class PortableNode(GraphNode):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Identifier
    handler: Handler
    module_id: ModuleReference | None = None


class PortableEdge(GraphEdge):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: Identifier
    target: Identifier


class PortableGraph(GraphConfig):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: Identifier
    version: ExactVersion = "0.1.0"
    entry_node: Identifier
    finish_nodes: list[Identifier] = Field(default_factory=lambda: ["step_complete"])
    nodes: list[PortableNode]
    edges: list[PortableEdge] = Field(default_factory=list)


class ExperimentalPackage(StrictModel):
    schema_: Literal["ax4lab.experimental_package.v1"] = Field(alias="schema")
    id: Identifier
    version: ExactVersion
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] | None = None
    graph: PortableGraph
    agent_packages: list[PackageReference]
    bridge_modules: list[PackageReference] = Field(default_factory=list)
    module_configurations: dict[Identifier, dict[str, Any]] = Field(default_factory=dict)
    external_owners: list[ExternalOwner] = Field(default_factory=list)
    bindings: list[PortableBinding] = Field(default_factory=list)
