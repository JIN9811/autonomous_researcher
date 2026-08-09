"""ToolRegistry bindings for deterministic Objective Compiler operations."""

from __future__ import annotations

from typing import Any, Callable

from objectives.compiler import ObjectiveCompileError
from objectives.service import ObjectiveConflict, ObjectiveNotFound, ObjectiveService
from mcp_tools.tool_registry import ToolRegistry


def _failure(exc: Exception, *, code: str = "OBJECTIVE_OPERATION_FAILED") -> dict[str, Any]:
    return {
        "ok": False,
        "failure_code": code,
        "errors": [str(exc).replace("\\", "/").split("/memory/objectives", 1)[0]],
    }


def _guard(handler: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def wrapped(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return handler(payload)
        except (ObjectiveCompileError, ValueError, TypeError) as exc:
            return _failure(exc, code="OBJECTIVE_VALIDATION_FAILED")
        except ObjectiveNotFound as exc:
            return _failure(exc, code="OBJECTIVE_NOT_FOUND")
        except ObjectiveConflict as exc:
            return _failure(exc, code="OBJECTIVE_CONFLICT")

    return wrapped


def register_objective_tools(registry: ToolRegistry, service: ObjectiveService) -> None:
    """Register bounded objective tools and expose the shared service resource."""
    registry.register_resource("objective.service", service)

    registry.register(
        "objective.metrics.list",
        _guard(
            lambda payload: {
                "ok": True,
                "registry_version": service.registry.version_id,
                "metrics": [item.model_dump(mode="json") for item in service.registry.list()],
            }
        ),
    )

    def describe(payload: dict[str, Any]) -> dict[str, Any]:
        item = service.registry.get(str(payload.get("metric_id") or ""))
        return {"ok": True, "metric": item.model_dump(mode="json"), "registry_version": service.registry.version_id}

    registry.register("objective.metrics.describe", _guard(describe))

    def compose(payload: dict[str, Any]) -> dict[str, Any]:
        spec = service.create_draft(payload.get("spec") if isinstance(payload.get("spec"), dict) else {})
        validation = service.validate(spec.objective_id, spec.version)
        return {
            "ok": validation.valid,
            "draft": spec.model_dump(mode="json"),
            "validation": validation.model_dump(mode="json"),
            "errors": validation.errors,
            "failure_code": None if validation.valid else "OBJECTIVE_VALIDATION_FAILED",
        }

    registry.register("objective.compose", _guard(compose))

    def validate(payload: dict[str, Any]) -> dict[str, Any]:
        result = service.validate(str(payload.get("objective_id") or ""), payload.get("version"))
        return {
            "ok": result.valid,
            "validation": result.model_dump(mode="json"),
            "errors": result.errors,
            "failure_code": None if result.valid else "OBJECTIVE_VALIDATION_FAILED",
        }

    registry.register("objective.validate", _guard(validate))

    def preview(payload: dict[str, Any]) -> dict[str, Any]:
        result = service.preview(
            str(payload.get("objective_id") or ""),
            payload.get("version"),
            payload.get("observations") if isinstance(payload.get("observations"), list) else [],
        )
        return {"ok": result.usable_rows > 0, "preview": result.model_dump(mode="json")}

    registry.register("objective.preview", _guard(preview))

    def revise(payload: dict[str, Any]) -> dict[str, Any]:
        spec = service.create_draft(payload.get("spec") if isinstance(payload.get("spec"), dict) else {})
        result = service.validate(spec.objective_id, spec.version)
        return {"ok": result.valid, "draft": spec.model_dump(mode="json"), "validation": result.model_dump(mode="json")}

    registry.register("objective.revise", _guard(revise))

    def approve(payload: dict[str, Any]) -> dict[str, Any]:
        decision = service.approve(
            str(payload.get("objective_id") or ""),
            payload.get("version"),
            operator=str(payload.get("operator") or ""),
        )
        return {"ok": True, "decision": decision.model_dump(mode="json")}

    registry.register("objective.approve", _guard(approve))

    def activate(payload: dict[str, Any]) -> dict[str, Any]:
        binding = service.activate(
            str(payload.get("objective_id") or ""),
            int(payload.get("version") or 0),
            run_id=str(payload.get("run_id") or ""),
            operator=str(payload.get("operator") or ""),
        )
        return {"ok": True, "binding": binding.model_dump(mode="json")}

    registry.register("objective.activate", _guard(activate))

    def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
        result = service.evaluate(
            run_id=str(payload.get("run_id") or ""),
            metrics=payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {},
            observation_id=str(payload.get("observation_id") or ""),
            uncertainty=payload.get("uncertainty"),
            provenance_refs=[str(item) for item in payload.get("provenance_refs", [])],
            fidelity=str(payload.get("fidelity") or "measured"),
        )
        return {"ok": True, "evaluation": result.model_dump(mode="json")}

    registry.register("objective.evaluate", _guard(evaluate))
    registry.register(
        "objective.compare",
        _guard(
            lambda payload: {
                "ok": True,
                "comparisons": service.compare(
                    payload.get("candidates") if isinstance(payload.get("candidates"), list) else [],
                    payload.get("observations") if isinstance(payload.get("observations"), list) else [],
                ),
            }
        ),
    )
    registry.register(
        "objective.status",
        _guard(lambda payload: service.status(run_id=str(payload.get("run_id") or ""))),
    )
