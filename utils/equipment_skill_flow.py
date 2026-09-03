"""Shared composite Skill Flow contract for the Lab Equipment Agent."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from utils.equipment_agentic_task import UTM_COMPRESSION_BLOCKS, UTM_COMPRESSION_TASK_ID
from utils.equipment_vision_tasks import EQUIPMENT_VISION_TASK_IDS, get_equipment_vision_task


FLOW_SCHEMA = "atr.equipment_skill_flow.v1"
STORE_SCHEMA = "atr.equipment_skill_flows.v1"
TERMINALS = frozenset({"__complete__", "__blocked__"})
ROUTE_TARGETS = frozenset({"next", *TERMINALS})
BLOCK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
VISION_OUTCOMES = ("detected", "not_detected", "timeout", "error")


class EquipmentSkillFlowError(ValueError):
    """Raised when an Equipment Skill Flow cannot be stored or executed."""


def empty_equipment_skill_flow(profile_id: str) -> dict[str, Any]:
    """Return an editable empty flow for one Equipment Profile."""
    return {
        "schema": FLOW_SCHEMA,
        "flow_id": profile_id,
        "profile_id": profile_id,
        "version": 1,
        "enabled": True,
        "agentic_task_id": "",
        "blocks": [],
    }


def _clean_id(value: Any, *, field: str) -> str:
    clean = str(value or "").strip()
    if not BLOCK_ID_PATTERN.fullmatch(clean):
        raise EquipmentSkillFlowError(f"{field} is missing or invalid")
    return clean


def _route(value: Any, *, field: str, default: str) -> str:
    target = str(value or default).strip()
    if target not in ROUTE_TARGETS:
        raise EquipmentSkillFlowError(f"{field} has unsupported route target: {target}")
    return target


def _legacy_nodes_to_blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Migrate a bounded legacy linear Skill/Vision graph into composite blocks."""
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        return []
    if not raw_nodes:
        return []
    node_map: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(raw_nodes, start=1):
        if not isinstance(raw, dict):
            raise EquipmentSkillFlowError(f"legacy node {index} must be an object")
        node_id = _clean_id(raw.get("id"), field=f"legacy nodes[{index}].id")
        if node_id in node_map:
            raise EquipmentSkillFlowError(f"duplicate legacy node id: {node_id}")
        node_map[node_id] = deepcopy(raw)

    current = str(payload.get("entry_node") or "").strip()
    if current not in node_map:
        raise EquipmentSkillFlowError("legacy entry_node must reference an existing node")
    visited: set[str] = set()
    blocks: list[dict[str, Any]] = []
    while current not in TERMINALS:
        if current in visited:
            raise EquipmentSkillFlowError(f"legacy flow contains a cycle at {current}")
        node = node_map.get(current)
        if not isinstance(node, dict):
            raise EquipmentSkillFlowError(f"legacy route references unknown target: {current}")
        if node.get("kind") != "skill":
            raise EquipmentSkillFlowError(f"standalone Vision node is not supported: {current}")
        visited.add(current)
        routes = node.get("routes") if isinstance(node.get("routes"), dict) else {}
        completed_target = str(routes.get("completed") or "").strip()
        failed_target = str(routes.get("failed") or "__blocked__").strip()
        if failed_target != "__blocked__":
            raise EquipmentSkillFlowError(f"legacy {current}.failed must route to __blocked__")
        vision = {
            "enabled": False,
            "condition": "equipment_specimen_detected",
            "detected": "next",
            "not_detected": "__blocked__",
            "timeout": "__blocked__",
            "error": "__blocked__",
        }
        next_target = completed_target
        candidate = node_map.get(completed_target)
        if isinstance(candidate, dict) and candidate.get("kind") == "vision_gate":
            vision_routes = candidate.get("routes") if isinstance(candidate.get("routes"), dict) else {}
            visited.add(completed_target)
            vision = {
                "enabled": True,
                "condition": str(candidate.get("condition") or "equipment_specimen_detected").strip(),
                "detected": "next",
                "not_detected": "__blocked__",
                "timeout": "__blocked__",
                "error": "__blocked__",
            }
            next_target = str(vision_routes.get("detected") or "").strip()
            bypass = str(vision_routes.get("bypass") or next_target).strip()
            if bypass != next_target:
                raise EquipmentSkillFlowError(f"legacy Vision bypass route diverges at {completed_target}")
            for outcome in ("not_detected", "timeout", "error"):
                if str(vision_routes.get(outcome) or "__blocked__").strip() != "__blocked__":
                    raise EquipmentSkillFlowError(f"legacy Vision {outcome} route must be blocked")
        skill_id = _clean_id(node.get("skill_id"), field=f"{current}.skill_id")
        skill_version = str(node.get("skill_version") or "").strip()
        if not skill_version:
            raise EquipmentSkillFlowError(f"{current}.skill_version is required")
        blocks.append(
            {
                "id": current,
                "label": str(node.get("label") or current).strip()[:160],
                "skill": {"skill_id": skill_id, "skill_version": skill_version},
                "agentic": {"completed": "next", "failed": "__blocked__"},
                "vision": vision,
            }
        )
        if next_target not in node_map and next_target not in TERMINALS:
            raise EquipmentSkillFlowError(f"legacy route references unknown target: {next_target}")
        current = next_target

    if visited != set(node_map):
        leftovers = sorted(set(node_map) - visited)
        if any(node_map[node_id].get("kind") == "vision_gate" for node_id in leftovers):
            raise EquipmentSkillFlowError(f"standalone Vision node is not supported: {', '.join(leftovers)}")
        raise EquipmentSkillFlowError(f"legacy flow contains unreachable node(s): {', '.join(leftovers)}")
    for index, block in enumerate(blocks):
        terminal = "__complete__" if index == len(blocks) - 1 else "next"
        block["agentic"]["completed"] = terminal
        block["vision"]["detected"] = terminal
    if current == "__blocked__" and blocks:
        blocks[-1]["agentic"]["completed"] = "__blocked__"
        blocks[-1]["vision"]["detected"] = "__blocked__"
    return blocks


def normalize_equipment_skill_flow(
    profile_id: str,
    payload: dict[str, Any],
    *,
    migration_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize and validate an ordered set of composite Skill blocks."""
    if not isinstance(payload, dict):
        raise EquipmentSkillFlowError("flow must be an object")
    clean_profile = _clean_id(profile_id, field="profile_id")
    raw = deepcopy(payload)
    if str(raw.get("schema") or FLOW_SCHEMA) != FLOW_SCHEMA:
        raise EquipmentSkillFlowError(f"schema must be {FLOW_SCHEMA}")
    body_profile = _clean_id(raw.get("profile_id") or clean_profile, field="profile_id")
    if body_profile != clean_profile:
        raise EquipmentSkillFlowError("profile_id path/body mismatch")
    blocks_payload = raw.get("blocks")
    if blocks_payload is None and "nodes" in raw:
        blocks_payload = _legacy_nodes_to_blocks(raw)
    if blocks_payload is None:
        blocks_payload = []
    if not isinstance(blocks_payload, list):
        raise EquipmentSkillFlowError("blocks must be a list")
    if len(blocks_payload) > 128:
        raise EquipmentSkillFlowError("blocks must contain at most 128 entries")

    notes = migration_notes if migration_notes is not None else []
    blocks: list[dict[str, Any]] = []
    block_ids: set[str] = set()
    for index, item in enumerate(blocks_payload, start=1):
        if not isinstance(item, dict):
            raise EquipmentSkillFlowError(f"block {index} must be an object")
        block_id = _clean_id(item.get("id"), field=f"blocks[{index}].id")
        if block_id in block_ids:
            raise EquipmentSkillFlowError(f"duplicate block id: {block_id}")
        block_ids.add(block_id)
        skill = item.get("skill") if isinstance(item.get("skill"), dict) else {}
        raw_skill_id = str(skill.get("skill_id") or "").strip()
        skill_version = str(skill.get("skill_version") or skill.get("version") or "").strip()
        if bool(raw_skill_id) != bool(skill_version):
            raise EquipmentSkillFlowError(
                f"{block_id}.skill.skill_id and skill_version must both be set or both be empty"
            )
        skill_id = (
            _clean_id(raw_skill_id, field=f"{block_id}.skill.skill_id")
            if raw_skill_id
            else ""
        )
        is_last = index == len(blocks_payload)
        default_success = "__complete__" if is_last else "next"
        agentic = item.get("agentic") if isinstance(item.get("agentic"), dict) else {}
        vision = item.get("vision") if isinstance(item.get("vision"), dict) else {}
        vision_enabled = bool(vision.get("enabled", False))
        vision_blocking = bool(vision.get("blocking", True))
        task_id = str(vision.get("task_id") or "").strip()
        legacy_condition_present = "condition" in vision
        legacy_condition = str(vision.get("condition") or "").strip()
        if not task_id and legacy_condition in EQUIPMENT_VISION_TASK_IDS:
            task_id = legacy_condition
            notes.append(f"{block_id}: migrated vision.condition={legacy_condition} to vision.task_id")
        elif not task_id and legacy_condition_present and vision_enabled:
            task_id = "utm_pre_start"
            notes.append(f"{block_id}: migrated legacy Vision condition to utm_pre_start")
        if task_id and task_id not in EQUIPMENT_VISION_TASK_IDS:
            raise EquipmentSkillFlowError(
                f"{block_id}.vision.task_id references unknown Equipment Vision task: {task_id}"
            )
        if vision_enabled and not task_id:
            raise EquipmentSkillFlowError(f"{block_id}.vision.task_id is required")
        vision_task = get_equipment_vision_task(task_id) if task_id else {}
        task = str(agentic.get("task") or item.get("label") or skill_id or "Equipment Task").strip()[:160]
        block = {
            "id": block_id,
            "label": task,
            "skill": {"skill_id": skill_id, "skill_version": skill_version},
            "agentic": {
                "task": task,
                "completed": _route(agentic.get("completed"), field=f"{block_id}.agentic.completed", default=default_success),
                "failed": _route(agentic.get("failed"), field=f"{block_id}.agentic.failed", default="__blocked__"),
            },
            "vision": {
                "enabled": vision_enabled,
                "blocking": vision_blocking,
                "task_id": task_id,
                "result_label": str(vision_task.get("result_label") or ""),
                "detected": _route(vision.get("detected"), field=f"{block_id}.vision.detected", default=default_success),
                "not_detected": _route(vision.get("not_detected"), field=f"{block_id}.vision.not_detected", default="__blocked__"),
                "timeout": _route(vision.get("timeout"), field=f"{block_id}.vision.timeout", default="__blocked__"),
                "error": _route(vision.get("error"), field=f"{block_id}.vision.error", default="__blocked__"),
            },
        }
        if not is_last and block["agentic"]["completed"] == "__complete__":
            raise EquipmentSkillFlowError(f"{block_id}.agentic.completed cannot complete before the final block")
        if not is_last and block["vision"]["detected"] == "__complete__":
            raise EquipmentSkillFlowError(f"{block_id}.vision.detected cannot complete before the final block")
        if is_last and (block["agentic"]["completed"] == "next" or block["vision"]["detected"] == "next"):
            raise EquipmentSkillFlowError(f"{block_id} cannot route next after the final block")
        blocks.append(block)

    try:
        version = max(1, int(raw.get("version") or 1))
    except (TypeError, ValueError) as exc:
        raise EquipmentSkillFlowError("version must be a positive integer") from exc
    agentic_task_id = (
        _clean_id(raw.get("agentic_task_id"), field="agentic_task_id")
        if str(raw.get("agentic_task_id") or "").strip()
        else ""
    )
    if agentic_task_id and agentic_task_id != UTM_COMPRESSION_TASK_ID:
        raise EquipmentSkillFlowError(
            f"unsupported workflow Agentic Task: {agentic_task_id}"
        )
    if agentic_task_id == UTM_COMPRESSION_TASK_ID:
        expected_order = [block_id for block_id, _ in UTM_COMPRESSION_BLOCKS]
        observed_order = [str(block.get("id") or "") for block in blocks]
        if observed_order != expected_order:
            raise EquipmentSkillFlowError(
                "UTM compression workflow must use the canonical block revision"
            )
    return {
        "schema": FLOW_SCHEMA,
        "flow_id": _clean_id(raw.get("flow_id") or clean_profile, field="flow_id"),
        "profile_id": clean_profile,
        "version": version,
        "enabled": bool(raw.get("enabled", True)),
        "agentic_task_id": agentic_task_id,
        "blocks": blocks,
        "updated_at": str(raw.get("updated_at") or datetime.now(timezone.utc).isoformat()),
    }


class EquipmentSkillFlowStore:
    """Atomically persist Profile-bound Equipment Skill Flows."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema": STORE_SCHEMA, "flows": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EquipmentSkillFlowError(f"unable to read Skill Flow store: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("flows"), dict):
            raise EquipmentSkillFlowError("Skill Flow store is invalid")
        return raw

    def list(self) -> list[dict[str, Any]]:
        raw = self._read()
        return [self.get(profile_id) for profile_id in sorted(raw["flows"])]

    def get(self, profile_id: str) -> dict[str, Any]:
        flow, _ = self.get_with_migration(profile_id)
        return flow

    def get_with_migration(self, profile_id: str) -> tuple[dict[str, Any], list[str]]:
        """Return a normalized flow and bounded notes for legacy task migration."""
        clean_profile = _clean_id(profile_id, field="profile_id")
        payload = self._read()["flows"].get(clean_profile)
        if not isinstance(payload, dict):
            return empty_equipment_skill_flow(clean_profile), []
        notes: list[str] = []
        flow = normalize_equipment_skill_flow(clean_profile, payload, migration_notes=notes)
        return flow, notes

    def save(self, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        notes: list[str] = []
        flow = normalize_equipment_skill_flow(profile_id, payload, migration_notes=notes)
        raw = self._read()
        flows = dict(raw.get("flows", {}))
        flows[flow["profile_id"]] = flow
        stored = {"schema": STORE_SCHEMA, "flows": flows, "updated_at": flow["updated_at"]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(stored, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        return {"ok": True, "flow": deepcopy(flow), "path": str(self.path), "migration_notes": notes}

    @staticmethod
    def phase_target(flow: dict[str, Any], block_id: str, phase: str, outcome: str) -> str:
        """Resolve one bounded target for an execution phase."""
        blocks = flow.get("blocks") if isinstance(flow.get("blocks"), list) else []
        block = next((item for item in blocks if item.get("id") == block_id), None)
        if not isinstance(block, dict):
            raise EquipmentSkillFlowError(f"unknown flow block: {block_id}")
        config = block.get("vision") if phase == "vision" else block.get("agentic")
        target = str((config or {}).get(outcome) or "")
        if not target:
            raise EquipmentSkillFlowError(f"{block_id}.{phase} has no route for outcome={outcome}")
        if target == "next":
            index = blocks.index(block)
            return str(blocks[index + 1]["id"]) if index + 1 < len(blocks) else "__complete__"
        return target

    def as_runtime_graph(self, profile_id: str) -> dict[str, Any]:
        flow = self.get(profile_id)
        nodes: list[dict[str, Any]] = [
            {
                "id": "flow_supervisor",
                "label": "Equipment Flow Supervisor",
                "kind": "supervisor",
                "position": {"x": 80, "y": 80},
                "metadata": {"control_level": "high", "icon": "equipment_agent"},
            }
        ]
        edges: list[dict[str, Any]] = []
        for index, block in enumerate(flow["blocks"]):
            skill_node = f"{block['id']}.skill"
            next_block = flow["blocks"][index + 1]["id"] if index + 1 < len(flow["blocks"]) else "__complete__"
            success_target = f"{next_block}.skill" if next_block not in TERMINALS else next_block
            nodes.append(
                {
                    "id": skill_node,
                    "label": block["label"],
                    "kind": "skill",
                    "position": {"x": 280 + index * 260, "y": 310},
                    "metadata": {
                        "control_level": "low",
                        "block_id": block["id"],
                        "task": block["agentic"]["task"],
                        **block["skill"],
                    },
                }
            )
            if index == 0:
                edges.append({"source": "flow_supervisor", "target": skill_node, "condition": "dispatch"})
            edges.append({"source": skill_node, "target": "__blocked__", "condition": "failed"})
            if block["vision"]["enabled"]:
                vision_node = f"{block['id']}.vision"
                vision_task = get_equipment_vision_task(block["vision"]["task_id"])
                nodes.append(
                    {
                        "id": vision_node,
                        "label": vision_task["label"],
                        "kind": "vision_gate",
                        "position": {"x": 410 + index * 260, "y": 175},
                        "metadata": {
                            "control_level": "middle",
                            "blocking": bool(block["vision"].get("blocking", True)),
                            "block_id": block["id"],
                            "task_id": vision_task["task_id"],
                            "check_id": vision_task["check_id"],
                            "timeout_s": vision_task["timeout_s"],
                        },
                    }
                )
                edges.append({"source": skill_node, "target": vision_node, "condition": "observe" if not block["vision"].get("blocking", True) else "completed"})
                edges.append({"source": vision_node, "target": success_target, "condition": "observed" if not block["vision"].get("blocking", True) else "detected"})
                if block["vision"].get("blocking", True):
                    for outcome in ("not_detected", "timeout", "error"):
                        edges.append({"source": vision_node, "target": "__blocked__", "condition": outcome})
            else:
                edges.append({"source": skill_node, "target": success_target, "condition": "completed"})
        terminal_x = 420 + len(flow["blocks"]) * 260
        nodes.extend(
            [
                {"id": "__complete__", "label": "Complete", "kind": "terminal", "position": {"x": terminal_x, "y": 190}, "metadata": {"control_level": "middle"}},
                {"id": "__blocked__", "label": "Blocked", "kind": "terminal", "position": {"x": terminal_x, "y": 390}, "metadata": {"control_level": "middle"}},
            ]
        )
        return {
            "id": f"equipment_skill_flow:{profile_id}",
            "name": f"Equipment Skill Flow · {profile_id}",
            "entry_node": "flow_supervisor",
            "nodes": nodes,
            "edges": edges,
            "metadata": {"ide_tab_kind": "equipment_skill_flow", "module_id": "equipment", "profile_id": profile_id, "flow_version": flow["version"]},
        }
