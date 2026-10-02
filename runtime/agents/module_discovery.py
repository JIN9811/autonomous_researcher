"""Discover code-installed modules, never imports described by editable YAML."""
from importlib import import_module
from pathlib import Path

from agents.module_contract import AgentModule


def discover_agent_modules() -> tuple[AgentModule, ...]:
    modules = []
    identities = set()
    owners = set()
    for path in sorted(Path(__file__).parent.glob("*/module.py")):
        if not path.parent.name.isidentifier():
            continue
        declaration = getattr(import_module(f"agents.{path.parent.name}.module"), "MODULE", None)
        if not isinstance(declaration, AgentModule):
            raise ValueError(f"Installed module must export AgentModule MODULE: {path.parent.name}")
        if declaration.module_id in identities or declaration.agent_name in owners:
            raise ValueError(f"Duplicate installed module identity: {declaration.module_id}")
        identities.add(declaration.module_id)
        owners.add(declaration.agent_name)
        modules.append(declaration)
    return tuple(modules)
