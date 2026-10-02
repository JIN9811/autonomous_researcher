"""Pure composition service. Inject installed descriptions and existing validators.

No runtime/store object, transport, activation callback or arbitrary file loader is
accepted. Import returns detached drafts; the host owns any subsequent save.
"""
from copy import deepcopy
from importlib.resources import files
import json
from typing import Any, Callable, Iterable

import yaml
from pydantic import ValidationError
from graphs import ModuleConfig, ModuleConfigStore
from packages.contracts import AgentPackage, ExperimentalPackage, PackageReference
from packages.portability import portable_value as _portable

MAX_PACKAGE_BYTES = 1_048_576
_MODULE_EXTENSION_KEYS = {"implementation", "orchestration_contract", "metadata", "decision_settings",
                          "runtime_contract", "output_contracts", "workflow_agentic_tasks",
                          "transition_conditions", "supported_tasks"}


def installed_agent_packages(descriptions: Iterable[dict]) -> list[dict]:
    """Read only explicitly shipped manifests for installed code-owned agents.

    Paths never come from incoming packages; declarative referenced files are
    never opened or implicitly bundled.
    """
    installed = {item["id"]: item for item in descriptions}
    result = []
    for ident in ("design", "specimen", "vision", "manipulation", "equipment", "analysis", "bo"):
        if ident not in installed:
            continue
        raw = yaml.safe_load(files("packages").joinpath("agents", ident, "package.yaml").read_text())
        description = installed[ident]
        if raw["version"] != description["version"] or raw["handler"] != description["handler"]:
            raise ValueError(f"Installed agent manifest mismatch: {ident}")
        raw["ownership"] = {key: deepcopy(description.get(key, {}))
                            for key in ("frontend", "configuration", "storage")}
        result.append(AgentPackage.model_validate(raw).model_dump(by_alias=True))
    return result


def _bounded_copy(payload: Any) -> dict:
    try:
        encoded = json.dumps(payload, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Package must contain finite JSON data") from exc
    if len(encoded.encode("utf-8")) > MAX_PACKAGE_BYTES:
        raise ValueError("Package exceeds 1048576 byte limit")
    result = json.loads(encoded)
    if not isinstance(result, dict):
        raise ValueError("Package must be an object")
    return result


def _unique(items: list[dict], key: str, label: str) -> dict[str, dict]:
    result = {}
    for item in items:
        if item[key] in result:
            raise ValueError(f"Duplicate {label} reference")
        result[item[key]] = item
    return result


class PackageService:
    def __init__(self, *, agent_packages: Iterable[dict], bridge_modules: Iterable[dict],
                 installed_handlers: Iterable[str], installed_module_ids: Iterable[str],
                 validate_graph: Callable[[dict], list[str]],
                 validate_module: Callable[[str, dict], list[str]]):
        self._agents = deepcopy(list(agent_packages))
        self._bridges = deepcopy(list(bridge_modules))
        self._handlers = frozenset(installed_handlers)
        self._module_ids = frozenset(installed_module_ids)
        self._validate_graph = validate_graph
        self._validate_module = validate_module

    def _installed(self):
        agents = [AgentPackage.model_validate(item).model_dump(by_alias=True) for item in self._agents]
        bridges = deepcopy(self._bridges)
        for bridge in bridges:
            PackageReference.model_validate({"id": bridge["id"], "version": bridge["version"]})
        agent_map = _unique(agents, "id", "installed package")
        bridge_map = _unique(bridges, "id", "installed bridge")
        for agent in agents:
            _unique(agent["bridge_modules"], "id", "bridge dependency")
            for ref in agent["bridge_modules"]:
                if ref["id"] not in bridge_map or bridge_map[ref["id"]]["version"] != ref["version"]:
                    raise ValueError(f"Missing or version-conflicting bridge dependency: {ref['id']}")
        return agent_map, bridge_map

    def catalog(self) -> dict:
        try:
            agents, bridges = self._installed()
            for bridge in bridges.values():
                bridge["package_owners"] = [{"id": a["id"], "version": a["version"]}
                                            for a in agents.values() if any(
                                                ref["id"] == bridge["id"] for ref in a["bridge_modules"])]
            return {"ok": True, "schema": "ax4lab.package_catalog.v1", "errors": [],
                    "agent_packages": list(agents.values()), "bridge_modules": list(bridges.values()),
                    "external_requirements": {"handlers": sorted(self._handlers),
                                              "module_ids": sorted(self._module_ids)},
                    "limits": {"max_package_bytes": MAX_PACKAGE_BYTES}}
        except (ValueError, KeyError):
            return {"ok": False, "schema": "ax4lab.package_catalog.v1",
                    "errors": ["Installed package dependencies are missing, invalid or version-conflicting"],
                    "agent_packages": [], "bridge_modules": []}

    def export_experimental(self, payload: Any) -> dict:
        return self._process(payload, exporting=True)

    def import_experimental(self, payload: Any) -> dict:
        return self._process(payload, exporting=False)

    def _process(self, payload: Any, *, exporting: bool) -> dict:
        try:
            raw = _portable(_bounded_copy(payload), exporting=exporting)
            model = ExperimentalPackage.model_validate(raw)
            agents, bridges = self._installed()
            selected = _unique([r.model_dump() for r in model.agent_packages], "id", "agent package")
            needed_bridges = {}
            for ref in selected.values():
                if ref["id"] not in agents or agents[ref["id"]]["version"] != ref["version"]:
                    raise ValueError("Missing or version-conflicting agent package")
                for bridge in agents[ref["id"]]["bridge_modules"]:
                    if bridge["id"] in needed_bridges and needed_bridges[bridge["id"]] != bridge:
                        raise ValueError("Version-conflicting shared bridge")
                    needed_bridges[bridge["id"]] = bridge
            bridge_refs = [needed_bridges[key] for key in sorted(needed_bridges)]
            given_bridges = _unique([r.model_dump() for r in model.bridge_modules], "id", "bridge")
            if not exporting and given_bridges != needed_bridges:
                raise ValueError("Bridge references must match selected package dependencies")
            declared = {(agents[key]["handler"], agents[key]["agent_module"]["id"]) for key in selected}
            owners = {(node.handler, node.module_id.removeprefix("modules/") if node.module_id else None)
                      for node in model.graph.nodes}
            module_errors = []
            for ident, configuration in model.module_configurations.items():
                if ident not in self._module_ids:
                    raise ValueError("Missing installed module owner")
                if set(configuration) != {"module"} or not isinstance(configuration["module"], dict):
                    raise ValueError("Module configurations require an exact module object wrapper")
                module = ModuleConfigStore.normalize_payload(configuration)["module"]
                if set(module) - set(ModuleConfig.model_fields) - _MODULE_EXTENSION_KEYS:
                    raise ValueError("Unsupported module configuration fields")
                ModuleConfig.model_validate(module)
                owners.add((module["handler"], ident))
                for phase in ("pre_execution", "internal_graph"):
                    owners.update((step["handler"], None) for step in module.get(phase, []) if step.get("handler"))
                package_owner = next((a for a in agents.values() if a["agent_module"]["id"] == ident), None)
                if package_owner and module["handler"] != package_owner["handler"]:
                    raise ValueError("Module handler must match installed owner")
                module_errors.extend(self._validate_module(ident, deepcopy(configuration)))
            for handler, ident in owners:
                if handler not in self._handlers or (ident is not None and ident not in self._module_ids):
                    raise ValueError("Missing installed graph handler or module owner")
                package_owner = next((a for a in agents.values() if a["agent_module"]["id"] == ident), None)
                if package_owner and handler != package_owner["handler"]:
                    raise ValueError("Graph handler must match installed module owner")
            external = [{"handler": handler, "module_id": ident} for handler, ident in
                        sorted(owners - declared, key=lambda pair: (pair[0], pair[1] or ""))]
            supplied_external = [ref.model_dump() for ref in model.external_owners]
            if len({(r["handler"], r["module_id"]) for r in supplied_external}) != len(supplied_external):
                raise ValueError("Duplicate external owner reference")
            if not exporting and {(r["handler"], r["module_id"]) for r in supplied_external} != {
                    (r["handler"], r["module_id"]) for r in external}:
                raise ValueError("External graph owners must be declared explicitly")
            errors = module_errors + self._validate_graph(deepcopy(raw["graph"]))
            if errors:
                # Validators can contain user payloads; never return exception dumps or values.
                raise ValueError("Existing graph/module validation rejected the composition")
            bindings = _unique([b.model_dump() for b in model.bindings], "id", "binding")
            allowed_owners = set(selected) | set(needed_bridges) | {i for _, i in owners if i}
            if any(b["owner_id"] not in allowed_owners for b in bindings.values()):
                raise ValueError("Binding owner is not in this composition")
            for ident in needed_bridges:
                for binding in bridges[ident].get("binding_requirements", []):
                    if binding["id"] in bindings and bindings[binding["id"]] != binding:
                        raise ValueError("Conflicting required binding")
                    bindings[binding["id"]] = deepcopy(binding)
            package = {**raw, "bridge_modules": bridge_refs, "external_owners": external,
                       "module_configurations": deepcopy(raw.get("module_configurations", {})),
                       "bindings": list(bindings.values())}
            if exporting:
                return {"ok": True, "errors": [], "package": package, "activated": False, "persisted": False}
            return {"ok": True, "errors": [], "draft": package, "activated": False, "persisted": False,
                    "unresolved_bindings": [{**b, "status": "requires_local_configuration"} for b in bindings.values()]}
        except ValidationError:
            message = "Package schema validation failed (unknown fields, invalid identifiers or non-exact versions)"
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            message = str(exc) if type(exc) is ValueError else "Invalid package structure"
        return {"ok": False, "errors": [message], "package" if exporting else "draft": None,
                "activated": False, "persisted": False, **({} if exporting else {"unresolved_bindings": []})}
