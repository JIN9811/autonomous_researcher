"""Discover code-installed bridges; editable descriptors never grant imports."""
from importlib import import_module
from pathlib import Path

from device_bridges.module_contract import BridgeModule


def discover_bridge_modules() -> tuple[BridgeModule, ...]:
    modules = []
    identities = set()
    for path in sorted(Path(__file__).parent.glob("*/module.py")):
        if not path.parent.name.isidentifier():
            continue
        declaration = getattr(import_module(f"device_bridges.{path.parent.name}.module"), "MODULE", None)
        if not isinstance(declaration, BridgeModule):
            raise ValueError(f"Installed bridge must export BridgeModule MODULE: {path.parent.name}")
        if declaration.module_id in identities:
            raise ValueError(f"Duplicate installed bridge identity: {declaration.module_id}")
        identities.add(declaration.module_id)
        modules.append(declaration)
    return tuple(modules)
