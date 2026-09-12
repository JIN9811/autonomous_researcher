"""Read-only graph-linked owner contracts and narrow setup delegation."""
from __future__ import annotations

from copy import deepcopy
import inspect
import math
from pathlib import Path
import time

import yaml


def availability_view(report: dict, now: float) -> dict:
    """Return evidence freshness, without mutating or renewing owner evidence."""
    view = deepcopy(report) if isinstance(report, dict) else {}
    times = (view.get("observed_at"), view.get("expires_at"), now)
    valid_times = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in times)
    evidence = view.get("evidence_refs")
    if (not valid_times or not times[0] <= now < times[1]
            or not isinstance(evidence, list) or not evidence or not all(isinstance(v, str) and v.strip() for v in evidence)
            or not view.get("owner") or not view.get("capability")
            or view.get("status") not in ("ready", "busy", "unavailable", "blocked", "unknown")):
        view["status"] = "unknown"
    return view


class OwnerCatalog:
    """Discover graph-linked owners only. Metadata is descriptive, never executable.

    Live catalogs re-read graph-linked YAML; snapshot() freezes graph bindings and
    module contracts for an execution run. Registry callbacks remain owner-owned.
    """

    def __init__(self, registry, graph_config, *, graph_root=None):
        self.registry = registry
        self.graph_config = graph_config
        self.graph_root = Path(graph_root or Path(__file__).resolve().parents[1] / "graphs").resolve()
        self._pinned_bindings = None

    def _module(self, node):
        if not node.module_id:
            return {}
        path = (self.graph_root / node.module_id / "module.yaml").resolve()
        if not path.is_relative_to(self.graph_root):
            return {}
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError):
            return {}
        module = raw.get("module", raw) if isinstance(raw, dict) else {}
        return module if isinstance(module, dict) else {}

    def _bindings(self):
        if self._pinned_bindings is not None:
            return deepcopy(self._pinned_bindings)
        # Multiple graph nodes may reference one module (e.g. Vision entry and
        # verification). Read it once per resolution, never across resolutions.
        module_values, modules = {}, {}
        for node in self.graph_config.nodes:
            if node.module_id not in module_values:
                module_values[node.module_id] = self._module(node)
            modules[node.id] = module_values[node.module_id]
        contracts = {}
        for node in self.graph_config.nodes:
            module = modules[node.id]
            contracts[str(module.get("handler") or "").strip() or str(node.handler or "").strip()] = module.get("orchestration_contract")
        rows = []

        def append(node, handler, role, contract, step_id=None):
            handler = handler.strip() if isinstance(handler, str) else handler
            if not isinstance(handler, str) or not handler.startswith("agent."):
                return
            valid = (isinstance(contract, dict) and isinstance(contract.get("version"), str)
                     and bool(contract["version"]) and all(isinstance(contract.get(k), dict) for k in ("admission", "result", "acceptance")))
            rows.append({"node_id": node.id, "step_id": step_id, "module_id": node.module_id,
                         "stage": node.stage, "handler": handler, "owner": handler.removeprefix("agent."),
                         "role": role, "executable": role != "overlay",
                         "contract": deepcopy(contract) if valid else {},
                         "contract_version": contract["version"] if valid else None,
                         "contract_status": "known" if valid else "unknown"})

        dispatch = set(self.graph_config.stage_dispatch.values())
        for node in self.graph_config.nodes:
            module = modules[node.id]
            handler = str(module.get("handler") or "").strip() or str(node.handler or "").strip()
            append(node, handler, "stage_dispatch" if node.id in dispatch else "overlay", module.get("orchestration_contract"))
            if node.id in dispatch:
                steps = module.get("pre_execution", [])
                for step in steps if isinstance(steps, list) else []:
                    if isinstance(step, dict) and step.get("enabled", True):
                        handler = str(step.get("handler") or "").strip()
                        append(node, handler, "pre_execution", contracts.get(handler), step.get("id"))
        return rows

    def snapshot(self):
        frozen = OwnerCatalog(self.registry, deepcopy(self.graph_config), graph_root=self.graph_root)
        frozen._pinned_bindings = deepcopy(self._bindings())
        return frozen

    def _owner(self, owner):
        if owner not in {row["owner"] for row in self._bindings()}:
            raise ValueError(f"Owner is not active in graph: {owner}")
        try:
            return self.registry.get(owner)
        except KeyError as exc:
            raise ValueError(f"Owner is not registered: {owner}") from exc

    def describe(self, state, ctx):
        rows = self._bindings()
        descriptors = {}
        for row in rows:
            owner = row["owner"]
            if owner not in descriptors:
                try:
                    agent = self._owner(owner)
                    writable = all(callable(getattr(agent, method, None)) for method in
                                   ("setup_descriptor", "validate_setup", "apply_setup", "read_setup"))
                    descriptors[owner] = agent.setup_descriptor() if writable else {"write_enabled": False, "fields": []}
                except ValueError:
                    descriptors[owner] = {"write_enabled": False, "fields": []}
            row["setup"] = deepcopy(descriptors[owner])
            row["availability"] = {"owner": owner, "capability": "inspect", "status": "unknown"}
        return rows

    async def inspect(self, owner: str, capability: str, state, ctx) -> dict:
        unknown = {"owner": owner, "capability": capability, "status": "unknown"}
        try:
            agent = self._owner(owner)
        except ValueError:
            return unknown
        bindings = [row for row in self._bindings() if row["owner"] == owner]
        if not any(row["contract_status"] == "known" for row in bindings):
            return unknown
        callback = getattr(agent, "inspect_availability", None)
        if callable(callback):
            report = callback(capability, state, ctx)
            if inspect.isawaitable(report):
                report = await report
        else:
            reports = state.run_metadata.get("availability_reports", {})
            reports = reports.get(owner, {}) if isinstance(reports, dict) else {}
            report = reports.get(capability, {}) if isinstance(reports, dict) else {}
        if not isinstance(report, dict) or report.get("owner") != owner or report.get("capability") != capability:
            return unknown
        if report.get("run_id") != state.run_id:
            return unknown
        return availability_view(report, time.time())

    def _setup_owner(self, owner):
        agent = self._owner(owner)
        if not all(callable(getattr(agent, method, None)) for method in
                   ("setup_descriptor", "validate_setup", "apply_setup", "read_setup")):
            raise ValueError(f"Owner has no setup write support: {owner}")
        return agent

    def validate(self, owner: str, changes: dict, state) -> dict:
        return self._setup_owner(owner).validate_setup(deepcopy(changes), state)

    async def apply(self, owner: str, changes: dict, state, request_id: str) -> dict:
        result = self._setup_owner(owner).apply_setup(deepcopy(changes), state, request_id)
        return await result if inspect.isawaitable(result) else result

    def readback(self, owner: str, state) -> dict:
        return deepcopy(self._setup_owner(owner).read_setup(state))
