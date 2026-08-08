"""Read-only registry for the versioned ATR core ontology."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml


@dataclass(frozen=True)
class RelationRule:
    relation_type: str
    source_classes: tuple[str, ...]
    target_classes: tuple[str, ...]


@dataclass(frozen=True)
class OntologyRegistry:
    version_id: str
    class_names: frozenset[str]
    relation_rules: Mapping[str, RelationRule]
    state_transitions: Mapping[str, Mapping[str, tuple[str, ...]]]
    event_families: frozenset[str]
    required_event_fields: tuple[str, ...]
    maxima: Mapping[str, int]

    @classmethod
    def load_default(cls, project_root: Path) -> "OntologyRegistry":
        root = project_root / "knowledge" / "ontology"
        core = _load_yaml(root / "atr_core.v1.yaml")
        relations = _load_yaml(root / "relation_rules.v1.yaml")
        shapes = _load_yaml(root / "validation_shapes.v1.yaml")
        versions = {core.get("version_id"), relations.get("version_id"), shapes.get("version_id")}
        if len(versions) != 1 or None in versions:
            raise ValueError(f"ontology definition versions do not match: {sorted(str(item) for item in versions)}")

        class_names = frozenset(
            str(name)
            for names in (core.get("classes") or {}).values()
            for name in (names if isinstance(names, list) else [])
        )
        relation_rules: dict[str, RelationRule] = {}
        for relation_type, raw_rule in (relations.get("relations") or {}).items():
            rule = raw_rule if isinstance(raw_rule, dict) else {}
            relation_rules[str(relation_type)] = RelationRule(
                relation_type=str(relation_type),
                source_classes=tuple(str(item) for item in rule.get("domain", [])),
                target_classes=tuple(str(item) for item in rule.get("range", [])),
            )
        transitions: dict[str, Mapping[str, tuple[str, ...]]] = {}
        for class_name, raw_states in (core.get("state_transitions") or {}).items():
            states = raw_states if isinstance(raw_states, dict) else {}
            transitions[str(class_name)] = MappingProxyType(
                {str(state): tuple(str(item) for item in targets) for state, targets in states.items()}
            )
        return cls(
            version_id=str(core["version_id"]),
            class_names=class_names,
            relation_rules=MappingProxyType(relation_rules),
            state_transitions=MappingProxyType(transitions),
            event_families=frozenset(str(item) for item in core.get("event_families", [])),
            required_event_fields=tuple(str(item) for item in shapes.get("knowledge_event_required", [])),
            maxima=MappingProxyType({str(key): int(value) for key, value in (shapes.get("maxima") or {}).items()}),
        )


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"ontology definition must be a mapping: {path}")
    return raw
