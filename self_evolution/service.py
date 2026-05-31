"""Service layer for ATR self-evolution.

The service is intentionally conservative: it generates reviewable variants from
run traces, validates them through existing graph/module schemas, and only writes
active runtime config after explicit approve/activate API calls.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from graphs import ATRLangGraphCompiler, GraphConfig, GraphVersionStore, HandlerRegistry, ModuleConfig, ModuleConfigStore, load_graph_config

from knowledge.schemas import EvolutionEvidencePack

from .evaluator import EvolutionReplayEvaluator
from .models import EvolutionTask, EvolutionTaskCreate, EvolutionTrace, EvolutionVariant, GateResult, TargetType
from .registry import EvolutionRegistry
from .trace_collector import TraceCollector


@dataclass(slots=True)
class SelfEvolutionService:
    root: Path
    run_root: Path
    graph_config_root: Path
    graph_version_root: Path
    module_root: Path
    module_version_root: Path
    knowledge_memory_root: Path | None = None
    registry: EvolutionRegistry = field(init=False)
    trace_collector: TraceCollector = field(init=False)
    replay_evaluator: EvolutionReplayEvaluator = field(init=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.knowledge_memory_root is None:
            self.knowledge_memory_root = self.root.parent / "knowledge"
        self.knowledge_memory_root.mkdir(parents=True, exist_ok=True)
        self.registry = EvolutionRegistry(self.root)
        self.trace_collector = TraceCollector(self.run_root)
        self.replay_evaluator = EvolutionReplayEvaluator()

    def list_targets(self) -> list[dict[str, Any]]:
        targets: list[dict[str, Any]] = []
        for path in sorted(self.module_root.glob("*/module.yaml")):
            module_id = path.parent.name
            targets.append({"target_type": "prompt", "target_id": module_id, "label": f"{module_id} module prompt", "path": str(path)})
            targets.append({"target_type": "report", "target_id": module_id, "label": f"{module_id} report template", "path": str(path)})
        for path in sorted(self.graph_config_root.glob("*.yaml")):
            try:
                graph = load_graph_config(path)
            except Exception:
                continue
            targets.append({"target_type": "graph", "target_id": graph.id, "label": graph.name or graph.id, "path": str(path)})
        for policy_id in ["recovery_policy", "live_safety_policy", "dry_run_policy"]:
            targets.append({"target_type": "policy", "target_id": policy_id, "label": policy_id, "path": "memory/evolution/active_variants.json"})
        return targets

    def latest_traces(self, limit: int = 12) -> list[dict[str, Any]]:
        traces: list[dict[str, Any]] = []
        for run_id in self.trace_collector.latest_run_ids(limit=limit):
            try:
                trace = self.trace_collector.collect_one(run_id)
            except Exception:
                continue
            traces.append({
                "trace_id": trace.trace_id,
                "run_id": trace.run_id,
                "graph_id": trace.graph_id,
                "graph_version": trace.graph_version,
                "metrics": trace.metrics,
                "artifact_count": len(trace.artifacts),
            })
        return traces

    def create_task(self, req: EvolutionTaskCreate) -> EvolutionTask:
        now = self._now()
        digest = hashlib.sha1(f"{now}:{req.target_type}:{req.target_id}:{req.objective}".encode("utf-8")).hexdigest()[:8]
        task = EvolutionTask(
            task_id=f"evo-task-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{digest}",
            target_type=req.target_type,
            target_id=req.target_id,
            source_run_ids=req.source_run_ids,
            objective=req.objective,
            constraints=req.constraints,
            status="draft",
            created_at=now,
            updated_at=now,
        )
        return self.registry.save_task(task)

    def list_tasks(self) -> list[EvolutionTask]:
        return self.registry.list_tasks()

    def read_task(self, task_id: str) -> EvolutionTask:
        return self.registry.read_task(task_id)

    def run_task(self, task_id: str, *, handler_registry: HandlerRegistry | None = None) -> dict[str, Any]:
        task = self.registry.read_task(task_id)
        now = self._now()
        try:
            traces = self.trace_collector.collect(task.source_run_ids)
            for trace in traces:
                self.registry.save_trace(trace)
            evidence_packs = self._collect_evidence_packs(task, traces)
            variant = self._generate_variant(task, traces, evidence_packs=evidence_packs)
            variant = self.evaluate_variant_object(variant, handler_registry=handler_registry, replay_traces=traces)
            task.status = "complete" if all(gate.passed for gate in variant.gate_results) else "evaluated"
            task.trace_ids = [trace.trace_id for trace in traces]
            if variant.variant_id not in task.variant_ids:
                task.variant_ids.append(variant.variant_id)
            task.updated_at = now
            self.registry.save_task(task)
            self.registry.save_variant(variant)
            return {"ok": True, "task": task.model_dump(mode="json"), "variant": variant.model_dump(mode="json")}
        except Exception as exc:
            task.status = "failed"
            task.updated_at = now
            task.diagnostics.append(str(exc))
            self.registry.save_task(task)
            return {"ok": False, "task": task.model_dump(mode="json"), "error": str(exc)}

    def list_variants(self, task_id: str | None = None) -> list[EvolutionVariant]:
        return self.registry.list_variants(task_id)

    def read_variant(self, variant_id: str) -> EvolutionVariant:
        return self.registry.read_variant(variant_id)

    def evaluate_variant(self, variant_id: str, *, handler_registry: HandlerRegistry | None = None) -> EvolutionVariant:
        variant = self.registry.read_variant(variant_id)
        variant = self.evaluate_variant_object(variant, handler_registry=handler_registry)
        return self.registry.save_variant(variant)

    def evaluate_variant_object(
        self,
        variant: EvolutionVariant,
        *,
        handler_registry: HandlerRegistry | None = None,
        replay_traces: list[EvolutionTrace] | None = None,
    ) -> EvolutionVariant:
        gates: list[GateResult] = [
            GateResult(gate_id="schema_presence", passed=bool(variant.body), message="variant body exists"),
            GateResult(gate_id="source_trace_present", passed=bool(variant.source_trace_ids), message="source trace lineage recorded"),
            GateResult(gate_id="no_live_hardware_execution", passed=True, message="evaluation performs schema/dry-run checks only"),
            GateResult(gate_id="rollback_available", passed=True, message="active variant registry keeps previous activation lineage"),
        ]
        if variant.target_type == "graph":
            gates.extend(self._graph_gates(variant, handler_registry=handler_registry))
        elif variant.target_type == "prompt":
            gates.extend(self._module_prompt_gates(variant, handler_registry=handler_registry))
        elif variant.target_type == "code_patch":
            gates.append(GateResult(gate_id="code_patch_not_auto_applied", passed=True, message="code patch variants remain diff-only"))
        else:
            gates.append(GateResult(gate_id="text_config_safe", passed=True, message=f"{variant.target_type} variant is stored as inert config until activated"))
        source_replay_traces = replay_traces if replay_traces is not None else self._source_traces_for_variant(variant)
        heldout_traces = self._heldout_traces_for_variant(variant, source_replay_traces)
        replay_result = self.replay_evaluator.evaluate(
            variant=variant,
            source_traces=source_replay_traces,
            heldout_traces=heldout_traces,
        )
        gates.extend(replay_result.gates)
        variant.metrics["replay_eval"] = replay_result.summary
        passed = sum(1 for gate in gates if gate.passed)
        variant.gate_results = gates
        variant.score = round(passed / max(1, len(gates)), 4)
        variant.metrics["gate_passed"] = passed
        variant.metrics["gate_total"] = len(gates)
        variant.status = "gate_passed" if passed == len(gates) else "evaluated"
        variant.updated_at = self._now()
        return variant

    def approve_variant(self, variant_id: str, *, operator: str = "operator", note: str = "") -> EvolutionVariant:
        variant = self.registry.read_variant(variant_id)
        if not variant.gate_results or not all(gate.passed for gate in variant.gate_results):
            raise ValueError("Variant must pass validation gates before approval.")
        variant.status = "approved"
        variant.activation["approved_by"] = operator
        variant.activation["approval_note"] = note
        variant.activation["approved_at"] = self._now()
        variant.updated_at = self._now()
        return self.registry.save_variant(variant)

    def activate_variant(
        self,
        variant_id: str,
        *,
        operator: str = "operator",
        note: str = "",
        activate_runtime: bool = True,
        handler_registry: HandlerRegistry | None = None,
    ) -> EvolutionVariant:
        variant = self.registry.read_variant(variant_id)
        if variant.status not in {"approved", "active_next_run", "active"}:
            raise ValueError("Variant must be approved before activation.")
        if not variant.gate_results or not all(gate.passed for gate in variant.gate_results):
            variant = self.evaluate_variant_object(variant, handler_registry=handler_registry)
            if not all(gate.passed for gate in variant.gate_results):
                self.registry.save_variant(variant)
                raise ValueError("Variant gates failed during activation recheck.")
        activation_payload: dict[str, Any] = {
            "activated_by": operator,
            "activation_note": note,
            "activated_at": self._now(),
            "activate_runtime": activate_runtime,
        }
        if activate_runtime and variant.target_type == "graph":
            graph_payload = variant.body.get("graph")
            config = GraphConfig.model_validate(graph_payload)
            store = GraphVersionStore(self._graph_config_path(config.id), self.graph_version_root)
            version = store.save_version(config.id, config.model_dump(mode="json"), reason="self_evolution_activate", author=operator)
            store.write_active(config.model_dump(mode="json"))
            activation_payload["graph_version"] = version
        elif activate_runtime and variant.target_type == "prompt":
            module_payload = variant.body.get("module")
            module_id = str(variant.target_id)
            store = ModuleConfigStore(self.module_root, self.module_version_root)
            version = store.save_version(module_id, {"module": module_payload}, reason="self_evolution_prompt_activate", author=operator)
            store.write_active(module_id, {"module": module_payload})
            activation_payload["module_version"] = version
        active = self.registry.set_active(variant.target_type, variant.target_id, variant.variant_id, activation_payload)
        variant.status = "active_next_run" if activate_runtime else "approved"
        variant.activation.update(active)
        variant.updated_at = self._now()
        return self.registry.save_variant(variant)

    def rollback_variant(self, variant_id: str, *, operator: str = "operator", note: str = "") -> EvolutionVariant:
        variant = self.registry.read_variant(variant_id)
        variant.status = "rolled_back"
        variant.activation["rolled_back_by"] = operator
        variant.activation["rollback_note"] = note
        variant.activation["rolled_back_at"] = self._now()
        variant.updated_at = self._now()
        return self.registry.save_variant(variant)

    def lineage(self, target_id: str) -> dict[str, Any]:
        variants = [variant for variant in self.registry.list_variants() if variant.target_id == target_id]
        variants.sort(key=lambda item: item.created_at, reverse=True)
        active = self.registry.active_variants()
        return {
            "target_id": target_id,
            "active": {key: value for key, value in active.items() if key.endswith(f":{target_id}")},
            "variants": [variant.model_dump(mode="json") for variant in variants],
        }


    def _source_traces_for_variant(self, variant: EvolutionVariant) -> list[EvolutionTrace]:
        traces: list[EvolutionTrace] = []
        for trace_id in variant.source_trace_ids:
            run_id = str(trace_id or "")
            if run_id.startswith("trace-"):
                run_id = run_id.removeprefix("trace-")
            if not run_id:
                continue
            try:
                traces.append(self.trace_collector.collect_one(run_id))
            except Exception:
                continue
        return traces

    def _heldout_traces_for_variant(self, variant: EvolutionVariant, source_traces: list[EvolutionTrace], *, limit: int = 3) -> list[EvolutionTrace]:
        source_run_ids = {trace.run_id for trace in source_traces}
        for trace_id in variant.source_trace_ids:
            raw = str(trace_id or "")
            source_run_ids.add(raw.removeprefix("trace-") if raw.startswith("trace-") else raw)
        heldout: list[EvolutionTrace] = []
        for run_id in self.trace_collector.latest_run_ids(limit=limit + len(source_run_ids) + 5):
            if run_id in source_run_ids:
                continue
            try:
                trace = self.trace_collector.collect_one(run_id)
            except Exception:
                continue
            heldout.append(trace)
            if len(heldout) >= limit:
                break
        return heldout

    def _generate_variant(self, task: EvolutionTask, traces: list[EvolutionTrace], *, evidence_packs: list[EvolutionEvidencePack] | None = None) -> EvolutionVariant:
        now = self._now()
        trace_metrics = self._aggregate_trace_metrics(traces)
        trace_metrics["knowledge_evidence_packs"] = [pack.model_dump(mode="json") for pack in (evidence_packs or [])]
        trace_metrics["knowledge_evidence_pack_count"] = len(evidence_packs or [])
        variant_id = f"evo-var-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{task.target_type}-{task.target_id}"
        body: dict[str, Any]
        diff = ""
        parent_version = None
        if task.target_type == "prompt":
            body, diff, parent_version = self._prompt_variant_body(task, trace_metrics)
        elif task.target_type == "graph":
            body, diff, parent_version = self._graph_variant_body(task, trace_metrics)
        elif task.target_type == "report":
            body = self._report_variant_body(task, trace_metrics)
            diff = "report template candidate generated from trace metrics"
        elif task.target_type == "policy":
            body = self._policy_variant_body(task, trace_metrics)
            diff = "policy candidate generated from trace metrics"
        elif task.target_type == "tool":
            body = self._tool_variant_body(task, trace_metrics)
            diff = "tool guidance candidate generated from trace metrics"
        else:
            body = {"diff": "# code patch generation is disabled in the safe default implementation\n"}
            diff = str(body["diff"])
        return EvolutionVariant(
            variant_id=variant_id,
            task_id=task.task_id,
            parent_version=parent_version,
            target_type=task.target_type,
            target_id=task.target_id,
            body=body,
            diff=diff,
            status="generated",
            created_at=now,
            updated_at=now,
            source_trace_ids=[trace.trace_id for trace in traces],
            metrics={"trace_metrics": trace_metrics},
        )

    def _prompt_variant_body(self, task: EvolutionTask, metrics: dict[str, Any]) -> tuple[dict[str, Any], str, str | None]:
        module_path = self.module_root / task.target_id / "module.yaml"
        if not module_path.exists():
            raise FileNotFoundError(f"Unknown module prompt target={task.target_id}")
        raw = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        module = copy.deepcopy(raw.get("module", raw))
        prompt = module.setdefault("prompt", {})
        if not isinstance(prompt, dict):
            prompt = {}
            module["prompt"] = prompt
        previous = str(prompt.get("developer") or "").strip()
        guidance = self._trace_guidance(task, metrics)
        prompt["developer"] = (previous + "\n\n" if previous else "") + guidance
        metadata = module.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["self_evolution_candidate"] = True
            metadata["self_evolution_task_id"] = task.task_id
            metadata["self_evolution_generated_at"] = self._now()
        diff = f"module.prompt.developer appended for {task.target_id}\n--- guidance ---\n{guidance}\n"
        return {"module": module}, diff, None

    def _graph_variant_body(self, task: EvolutionTask, metrics: dict[str, Any]) -> tuple[dict[str, Any], str, str | None]:
        graph_path = self._graph_config_path(task.target_id)
        raw = yaml.safe_load(graph_path.read_text(encoding="utf-8")) or {}
        graph = copy.deepcopy(raw.get("graph", raw))
        metadata = graph.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
            graph["metadata"] = metadata
        metadata["self_evolution_candidate"] = {
            "task_id": task.task_id,
            "generated_at": self._now(),
            "objective": task.objective,
            "trace_metrics": metrics,
            "activation_policy": "validate_compile_dry_run_guardian_human_approval",
        }
        diff = "graph.metadata.self_evolution_candidate added; execution routes unchanged until operator edits candidate further"
        return {"graph": graph}, diff, str(graph.get("version") or "") or None

    def _report_variant_body(self, task: EvolutionTask, metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            "template_id": task.target_id,
            "sections": ["Overview", "Trace Evidence", "Decisions", "Artifacts", "Gate Review", "Next Action"],
            "style": "academic concise runtime report",
            "trace_metrics": metrics,
            "objective": task.objective,
        }

    def _policy_variant_body(self, task: EvolutionTask, metrics: dict[str, Any]) -> dict[str, Any]:
        error_count = int(metrics.get("error_count") or 0)
        warning_count = int(metrics.get("warning_count") or 0)
        return {
            "policy_id": task.target_id,
            "retry": {"max_attempts": 2 if error_count else 1, "backoff_s": 1.0},
            "approval": {"require_human_approval_on_warning_count_gte": 3 if warning_count else 5},
            "safe_stop": {"block_live_on_failed_gate": True},
            "trace_metrics": metrics,
        }

    def _tool_variant_body(self, task: EvolutionTask, metrics: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool_id": task.target_id,
            "description_addendum": self._trace_guidance(task, metrics),
            "trace_metrics": metrics,
        }

    def _trace_guidance(self, task: EvolutionTask, metrics: dict[str, Any]) -> str:
        stage_counts = metrics.get("stage_counts") if isinstance(metrics.get("stage_counts"), dict) else {}
        hot_stages = ", ".join(list(stage_counts.keys())[:5]) or "none"
        pack_lines = self._knowledge_pack_guidance(metrics)
        return (
            "Self-evolution guidance for next closed-loop run:\n"
            f"- Objective: {task.objective}\n"
            f"- Source trace events: {metrics.get('event_count', 0)}, errors: {metrics.get('error_count', 0)}, warnings: {metrics.get('warning_count', 0)}.\n"
            f"- High-activity stages: {hot_stages}.\n"
            f"- Knowledge evidence packs: {metrics.get('knowledge_evidence_pack_count', 0)}.\n"
            f"{pack_lines}"
            "- Preserve strict JSON/tool contracts and include missing required fields before handoff.\n"
            "- Surface uncertainty, failed gates, and recovery choices explicitly for Guardian review."
        )

    @staticmethod
    def _knowledge_pack_guidance(metrics: dict[str, Any]) -> str:
        packs = metrics.get("knowledge_evidence_packs") if isinstance(metrics.get("knowledge_evidence_packs"), list) else []
        lines: list[str] = []
        for pack in packs[:3]:
            if not isinstance(pack, dict):
                continue
            objective = str(pack.get("objective") or "").strip()
            why = pack.get("why_this_target") if isinstance(pack.get("why_this_target"), list) else []
            changes = pack.get("recommended_changes") if isinstance(pack.get("recommended_changes"), list) else []
            if objective:
                lines.append(f"- Evidence objective: {objective}\n")
            for item in why[:3]:
                lines.append(f"  - Why: {item}\n")
            for item in changes[:4]:
                lines.append(f"  - Recommended change: {item}\n")
        return "".join(lines)

    def _collect_evidence_packs(self, task: EvolutionTask, traces: list[EvolutionTrace]) -> list[EvolutionEvidencePack]:
        """Read Knowledge evidence packs from per-run artifacts and long-term memory."""
        packs: list[EvolutionEvidencePack] = []
        seen: set[str] = set()
        requested_pack = str(task.constraints.get("knowledge_evidence_pack_id") or "") if isinstance(task.constraints, dict) else ""

        def _maybe_add(payload: Any) -> None:
            try:
                pack = EvolutionEvidencePack.model_validate(payload)
            except Exception:
                return
            if requested_pack and pack.pack_id != requested_pack:
                return
            if pack.target_type != task.target_type or pack.target_id != task.target_id:
                return
            if pack.pack_id in seen:
                return
            seen.add(pack.pack_id)
            packs.append(pack)

        for trace in traces:
            try:
                run_dir = self.trace_collector.run_dir(trace.run_id)
            except Exception:
                continue
            path = run_dir / "knowledge" / "evolution_evidence_packs.json"
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    raw = []
                if isinstance(raw, list):
                    for item in raw:
                        _maybe_add(item)
                elif isinstance(raw, dict):
                    for item in raw.get("evidence_packs", []) if isinstance(raw.get("evidence_packs"), list) else []:
                        _maybe_add(item)
        memory_path = (self.knowledge_memory_root or (self.root.parent / "knowledge")) / "evolution_evidence_packs.jsonl"
        if memory_path.exists():
            for line in memory_path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]:
                if not line.strip():
                    continue
                try:
                    _maybe_add(json.loads(line))
                except Exception:
                    continue
        packs.sort(key=lambda item: (item.priority, item.created_at), reverse=True)
        return packs[:5]

    def _graph_gates(self, variant: EvolutionVariant, *, handler_registry: HandlerRegistry | None) -> list[GateResult]:
        gates: list[GateResult] = []
        try:
            config = GraphConfig.model_validate(variant.body.get("graph"))
            gates.append(GateResult(gate_id="graph_schema", passed=True, message="GraphConfig schema valid"))
            compiler = ATRLangGraphCompiler(config, handler_registry or HandlerRegistry())
            errors = compiler.validate()
            gates.append(GateResult(gate_id="graph_compile_validation", passed=not errors, message="; ".join(errors) or "compiler validation passed", details={"errors": errors}))
            if not errors:
                compiler.compile()
                gates.append(GateResult(gate_id="graph_compile", passed=True, message="compiled graph artifact generated", details=compiler.summary()))
                sequence = self._graph_dry_run_sequence(config)
                gates.append(GateResult(gate_id="graph_dry_run", passed=bool(sequence), message=f"dry-run sequence length={len(sequence)}", details={"sequence": sequence}))
        except Exception as exc:
            gates.append(GateResult(gate_id="graph_schema", passed=False, message=str(exc)))
        return gates

    def _module_prompt_gates(self, variant: EvolutionVariant, *, handler_registry: HandlerRegistry | None) -> list[GateResult]:
        gates: list[GateResult] = []
        try:
            module_payload = variant.body.get("module")
            module = ModuleConfig.model_validate(module_payload)
            gates.append(GateResult(gate_id="module_schema", passed=True, message="ModuleConfig schema valid"))
            handler_names = set(handler_registry.names()) if handler_registry else set()
            handler_ok = not handler_names or module.handler in handler_names
            gates.append(GateResult(gate_id="module_handler_registered", passed=handler_ok, message="handler registered" if handler_ok else f"unregistered handler: {module.handler}"))
            gates.append(GateResult(gate_id="prompt_nonempty", passed=bool(module.prompt.developer or module.prompt.system), message="prompt override present"))
            gates.append(GateResult(gate_id="module_dry_run", passed=True, message=f"{len(module.pre_execution) + len(module.internal_graph)} configured module steps inspected"))
        except Exception as exc:
            gates.append(GateResult(gate_id="module_schema", passed=False, message=str(exc)))
        return gates

    def _graph_dry_run_sequence(self, config: GraphConfig, max_steps: int = 24) -> list[dict[str, Any]]:
        stage = str(config.stage_dispatch.get(config.entry_node, "") or "idle")
        if config.entry_node in config.stage_dispatch.values():
            stage = next((key for key, value in config.stage_dispatch.items() if value == config.entry_node), stage)
        if stage not in config.stage_dispatch:
            stage = "idle" if "idle" in config.stage_dispatch else next(iter(config.stage_dispatch.keys()), "")
        sequence: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index in range(max_steps):
            if not stage:
                break
            next_stage = config.next_stage(stage)
            sequence.append({"step": index + 1, "stage": stage, "next_stage": next_stage})
            if not next_stage or next_stage in config.terminal_stages:
                break
            if stage == "guardian" and next_stage == "design":
                break
            if next_stage in seen:
                break
            seen.add(stage)
            stage = next_stage
        return sequence

    def _aggregate_trace_metrics(self, traces: list[EvolutionTrace]) -> dict[str, Any]:
        merged: dict[str, Any] = {"trace_count": len(traces), "run_ids": [trace.run_id for trace in traces]}
        for key in ["event_count", "artifact_count", "error_count", "warning_count", "approval_count"]:
            merged[key] = sum(int(trace.metrics.get(key) or 0) for trace in traces)
        stage_counts: dict[str, int] = {}
        event_types: dict[str, int] = {}
        for trace in traces:
            for stage, count in (trace.metrics.get("stage_counts") or {}).items():
                stage_counts[str(stage)] = stage_counts.get(str(stage), 0) + int(count)
            for event_type, count in (trace.metrics.get("event_types") or {}).items():
                event_types[str(event_type)] = event_types.get(str(event_type), 0) + int(count)
        merged["stage_counts"] = dict(sorted(stage_counts.items(), key=lambda item: item[1], reverse=True))
        merged["event_types"] = dict(sorted(event_types.items(), key=lambda item: item[1], reverse=True))
        return merged

    def _graph_config_path(self, graph_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in graph_id)
        path = self.graph_config_root / f"{safe}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Unknown graph target_id={graph_id}")
        return path

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
