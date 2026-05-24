"""
File purpose:
- Manage vLLM model deployments running inside the NemoClaw k3s cluster.

Key classes/functions:
- NemoClawVLLMRuntime

Inputs/outputs:
- Input: model alias and Kubernetes deployment mapping
- Output: model service base URL and deployment scale actions

Dependencies:
- docker CLI with access to the openshell-cluster-nemoclaw container
- kubectl inside the NemoClaw cluster container

Modification guide:
- Safe places to edit: model alias mappings, timeout defaults
- Risky places to edit: subprocess command construction and scale-down policy
- Related files: backends/vllm_client.py, configs/system.yaml, deploy/nemoclaw-vllm.yaml
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ManagedVLLMModel:
    """Runtime mapping between a model alias and its NemoClaw k3s service."""

    deployment: str
    node_port: int
    persistent: bool = False
    depends_on: tuple[str, ...] = field(default_factory=tuple)


class NemoClawVLLMRuntime:
    """Scale NemoClaw-hosted vLLM deployments on demand."""

    def __init__(
        self,
        *,
        enabled: bool,
        cluster_container: str,
        namespace: str,
        node_host: str = "auto",
        startup_timeout_s: float = 1200.0,
        readiness_cache_s: float = 30.0,
        models: dict[str, ManagedVLLMModel] | None = None,
    ) -> None:
        self.enabled = enabled
        self._cluster_container = cluster_container
        self._namespace = namespace
        self._node_host = node_host.strip() or "auto"
        self._startup_timeout_s = float(startup_timeout_s)
        self._readiness_cache_s = max(0.0, float(readiness_cache_s))
        self._models = models or {}
        self._locks: dict[str, asyncio.Lock] = {model: asyncio.Lock() for model in self._models}
        self._scale_lock = asyncio.Lock()
        self._cached_node_host: str | None = None
        self._ready_until: dict[str, float] = {}

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> "NemoClawVLLMRuntime | None":
        """Build a runtime manager from the vllm.nemoclaw_k8s config block."""
        cfg = cfg or {}
        if not bool(cfg.get("enabled", False)):
            return None

        raw_models = cfg.get("models", {})
        models: dict[str, ManagedVLLMModel] = {}
        if isinstance(raw_models, dict):
            for alias, raw_item in raw_models.items():
                if not isinstance(raw_item, dict):
                    continue
                deployment = str(raw_item.get("deployment", "")).strip()
                node_port = raw_item.get("node_port")
                if not deployment or node_port is None:
                    continue
                depends_raw = raw_item.get("depends_on", [])
                depends_on = tuple(str(item).strip() for item in depends_raw if str(item).strip()) if isinstance(depends_raw, list) else ()
                models[str(alias)] = ManagedVLLMModel(
                    deployment=deployment,
                    node_port=int(node_port),
                    persistent=bool(raw_item.get("persistent", False)),
                    depends_on=depends_on,
                )

        return cls(
            enabled=True,
            cluster_container=str(cfg.get("cluster_container", "openshell-cluster-nemoclaw")),
            namespace=str(cfg.get("namespace", "nemoclaw-vllm")),
            node_host=str(cfg.get("node_host", "auto")),
            startup_timeout_s=float(cfg.get("startup_timeout_seconds", 1200)),
            readiness_cache_s=float(cfg.get("readiness_cache_seconds", 30)),
            models=models,
        )

    async def base_url_for_model(self, model: str) -> str | None:
        """Return the OpenAI-compatible base URL for a managed model alias."""
        managed = self._models.get(model)
        if not self.enabled or managed is None:
            return None
        node_host = await self._resolve_node_host()
        return f"http://{node_host}:{managed.node_port}/v1"

    async def ensure_model(self, model: str) -> None:
        """Scale a managed model deployment to one replica and wait until it is available."""
        if not self.enabled or model not in self._models:
            return
        if self._is_recently_ready(model):
            return
        await self._scale_down_switchable_models_before(model)
        await self._ensure_model(model, seen=set())
        self._mark_ready(model)

    async def load_model(self, model: str) -> dict[str, Any]:
        """Manually load one managed model and return its deployment status."""
        if not self.enabled:
            return {"enabled": False, "model": model, "loaded": False}
        if model not in self._models:
            raise ValueError(f"Unknown NemoClaw vLLM model: {model}")
        await self.ensure_model(model)
        statuses = await self.model_statuses()
        item = next((entry for entry in statuses.get("models", []) if entry.get("model") == model), {})
        return {"enabled": True, "model": model, "loaded": bool(item.get("loaded")), "status": item}

    async def unload_model(self, model: str) -> dict[str, Any]:
        """Manually scale one managed model down, even if the config marks it persistent."""
        if not self.enabled:
            return {"enabled": False, "model": model, "unloaded": False}
        managed = self._models.get(model)
        if managed is None:
            raise ValueError(f"Unknown NemoClaw vLLM model: {model}")
        await self._scale_down_model(model, managed)
        return {"enabled": True, "model": model, "unloaded": True}

    async def model_statuses(self) -> dict[str, Any]:
        """Return deployment readiness for all managed NemoClaw vLLM models."""
        if not self.enabled:
            return {"enabled": False, "models": []}

        items: list[dict[str, Any]] = []
        for model, managed in self._models.items():
            try:
                status = await self._deployment_status(managed.deployment)
                desired = int(status.get("desired_replicas", 0) or 0)
                available = int(status.get("available_replicas", 0) or 0)
                ready = int(status.get("ready_replicas", 0) or 0)
                if available >= 1:
                    state = "loaded"
                elif desired >= 1:
                    state = "loading"
                else:
                    state = "unloaded"
                items.append(
                    {
                        "model": model,
                        "deployment": managed.deployment,
                        "node_port": managed.node_port,
                        "persistent": managed.persistent,
                        "depends_on": list(managed.depends_on),
                        "desired_replicas": desired,
                        "available_replicas": available,
                        "ready_replicas": ready,
                        "loaded": available >= 1,
                        "state": state,
                        "ready_cached": self._is_recently_ready(model),
                    }
                )
            except Exception as exc:  # pragma: no cover - depends on local cluster state
                items.append(
                    {
                        "model": model,
                        "deployment": managed.deployment,
                        "node_port": managed.node_port,
                        "persistent": managed.persistent,
                        "depends_on": list(managed.depends_on),
                        "desired_replicas": 0,
                        "available_replicas": 0,
                        "ready_replicas": 0,
                        "loaded": False,
                        "state": "unknown",
                        "error": str(exc),
                    }
                )
        return {"enabled": True, "models": items}

    async def scale_down_idle_models(self, *, include_persistent: bool = False) -> dict[str, Any]:
        """Scale managed model deployments down to zero replicas."""
        if not self.enabled:
            return {"enabled": False, "scaled_down": [], "errors": []}

        scaled_down: list[str] = []
        errors: list[str] = []
        for model, managed in self._models.items():
            if managed.persistent and not include_persistent:
                continue
            try:
                await self._scale_down_model(model, managed)
                scaled_down.append(model)
            except Exception as exc:  # pragma: no cover - depends on local cluster state
                errors.append(f"{model}: {exc}")
        return {"enabled": True, "scaled_down": scaled_down, "errors": errors}

    async def scale_down_models_except(self, keep_models: set[str] | None = None, *, include_persistent: bool = False) -> dict[str, Any]:
        """Scale all managed non-kept models down to zero."""
        keep_models = set(keep_models or set())
        if not self.enabled:
            return {"enabled": False, "scaled_down": [], "errors": []}

        scaled_down: list[str] = []
        errors: list[str] = []
        for model, managed in self._models.items():
            if model in keep_models:
                continue
            if managed.persistent and not include_persistent:
                continue
            try:
                await self._scale_down_model(model, managed)
                scaled_down.append(model)
            except Exception as exc:  # pragma: no cover - depends on local cluster state
                errors.append(f"{model}: {exc}")
        return {"enabled": True, "scaled_down": scaled_down, "errors": errors}

    async def _ensure_model(self, model: str, *, seen: set[str]) -> None:
        if model in seen:
            raise RuntimeError(f"Circular NemoClaw vLLM dependency for model={model}")
        seen.add(model)

        managed = self._models[model]
        for dependency in managed.depends_on:
            if dependency in self._models:
                await self._ensure_model(dependency, seen=seen)

        lock = self._locks.setdefault(model, asyncio.Lock())
        async with lock:
            if await self._deployment_available(managed.deployment):
                return
            async with self._scale_lock:
                if await self._deployment_available(managed.deployment):
                    return
                if await self._deployment_desired_replicas(managed.deployment) == 0:
                    await self._wait_for_deployment_pods_deleted(managed.deployment, timeout_s=300)
                await self._kubectl(
                    "scale",
                    "deployment",
                    managed.deployment,
                    "--replicas=1",
                    timeout_s=60,
                )
                await self._kubectl(
                    "wait",
                    "--for=condition=Available",
                    f"deployment/{managed.deployment}",
                    f"--timeout={int(self._startup_timeout_s)}s",
                    timeout_s=self._startup_timeout_s + 30,
                )

    async def _scale_down_model(self, model: str, managed: ManagedVLLMModel) -> None:
        await self._kubectl(
            "scale",
            "deployment",
            managed.deployment,
            "--replicas=0",
            timeout_s=60,
        )
        await self._wait_for_deployment_pods_deleted(managed.deployment, timeout_s=300)
        self._invalidate_ready(model)

    async def _scale_down_switchable_models_before(self, target_model: str) -> None:
        """Free GPU memory before starting another non-persistent worker model."""
        target = self._models.get(target_model)
        if target is None or target.persistent:
            return

        keep_models = {target_model, *target.depends_on}
        for model, managed in self._models.items():
            if model in keep_models or managed.persistent:
                continue
            if not await self._deployment_available(managed.deployment):
                continue
            await self._scale_down_model(model, managed)

    def _is_recently_ready(self, model: str) -> bool:
        if self._readiness_cache_s <= 0:
            return False
        return self._ready_until.get(model, 0.0) > asyncio.get_running_loop().time()

    def _mark_ready(self, model: str) -> None:
        if self._readiness_cache_s <= 0:
            return
        self._ready_until[model] = asyncio.get_running_loop().time() + self._readiness_cache_s

    def _invalidate_ready(self, model: str) -> None:
        self._ready_until.pop(model, None)

    async def _deployment_desired_replicas(self, deployment: str) -> int:
        status = await self._deployment_status(deployment)
        return int(status.get("desired_replicas", 0) or 0)

    async def _deployment_label_selector(self, deployment: str) -> str:
        raw = await self._kubectl("get", "deployment", deployment, "-o", "json", timeout_s=30)
        payload = json.loads(raw)
        spec = payload.get("spec", {}) if isinstance(payload, dict) else {}
        selector = spec.get("selector", {}) if isinstance(spec, dict) else {}
        labels = selector.get("matchLabels", {}) if isinstance(selector, dict) else {}
        if not isinstance(labels, dict) or not labels:
            return f"app={deployment}"
        return ",".join(f"{key}={value}" for key, value in sorted(labels.items()))

    async def _wait_for_deployment_pods_deleted(self, deployment: str, *, timeout_s: float) -> None:
        selector = await self._deployment_label_selector(deployment)
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            raw = await self._kubectl("get", "pods", "-l", selector, "-o", "json", timeout_s=30)
            payload = json.loads(raw)
            items = payload.get("items", []) if isinstance(payload, dict) else []
            if not items:
                return
            if asyncio.get_running_loop().time() >= deadline:
                names = [item.get("metadata", {}).get("name", "unknown") for item in items if isinstance(item, dict)]
                raise RuntimeError(f"Timed out waiting for {deployment} pods to terminate: {names}")
            await asyncio.sleep(2)

    async def _deployment_available(self, deployment: str) -> bool:
        try:
            status = await self._deployment_status(deployment)
            return int(status.get("available_replicas", 0) or 0) >= 1
        except Exception:
            return False

    async def _deployment_status(self, deployment: str) -> dict[str, int]:
        raw = await self._kubectl("get", "deployment", deployment, "-o", "json", timeout_s=30)
        payload = json.loads(raw)
        spec = payload.get("spec", {}) if isinstance(payload, dict) else {}
        status = payload.get("status", {}) if isinstance(payload, dict) else {}
        return {
            "desired_replicas": int(spec.get("replicas", 0) or 0),
            "available_replicas": int(status.get("availableReplicas", 0) or 0),
            "ready_replicas": int(status.get("readyReplicas", 0) or 0),
            "updated_replicas": int(status.get("updatedReplicas", 0) or 0),
            "unavailable_replicas": int(status.get("unavailableReplicas", 0) or 0),
        }

    async def _resolve_node_host(self) -> str:
        if self._node_host.lower() != "auto":
            return self._node_host
        if self._cached_node_host:
            return self._cached_node_host
        out = await self._run(
            [
                "docker",
                "inspect",
                "-f",
                "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                self._cluster_container,
            ],
            timeout_s=20,
        )
        node_host = out.strip()
        if not node_host:
            raise RuntimeError(f"Could not resolve NemoClaw container IP: {self._cluster_container}")
        self._cached_node_host = node_host
        return node_host

    async def _kubectl(self, *args: str, timeout_s: float) -> str:
        cmd = ["docker", "exec", self._cluster_container, "kubectl", "-n", self._namespace, *args]
        return await self._run(cmd, timeout_s=timeout_s)

    async def _run(self, cmd: list[str], *, timeout_s: float) -> str:
        return await asyncio.to_thread(self._run_sync, cmd, timeout_s)

    @staticmethod
    def _run_sync(cmd: list[str], timeout_s: float) -> str:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            detail = stderr or stdout or f"exit={result.returncode}"
            raise RuntimeError(f"command failed: {' '.join(cmd)} :: {detail}")
        return result.stdout
