"""Regression coverage for the retired Self-Evolution runtime surface."""

from __future__ import annotations

import importlib.util

from app.main import app


def test_self_evolution_runtime_entrypoints_are_not_registered() -> None:
    """Retirement must remove executable API/page/package entrypoints."""
    route_paths = {
        str(route.path)
        for route in app.routes
        if getattr(route, "path", None)
    }

    assert "/evolution-lab" not in route_paths
    assert not any(path.startswith("/api/evolution") for path in route_paths)
    assert importlib.util.find_spec("self_evolution") is None
