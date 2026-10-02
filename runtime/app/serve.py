"""
File purpose:
- Short server launcher that reads host/port/runtime flags from system config.

Key classes/functions:
- main

Inputs/outputs:
- Input: configs/system.yaml and optional env overrides
- Output: uvicorn server process

Dependencies:
- uvicorn
- utils.config_loader

Modification guide:
- Safe places to edit: default host/port/reload/workers
- Risky places to edit: import order around env application
- Related files: configs/system.yaml, app/main.py
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
import uvicorn

from utils.config_loader import load_all_configs
from utils.runtime_paths import current_paths, finalize_paths
from utils.runtime_process import path_metadata


def _str_to_bool(value: str, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    paths = finalize_paths(current_paths())
    metadata = path_metadata(paths)
    load_dotenv(paths.repository_root / '.env', override=False)
    cfg = load_all_configs(paths.runtime_root / 'configs')
    system_cfg = cfg.get("system", {})
    server_cfg = system_cfg.get("server", {})
    runtime_env = system_cfg.get("runtime_env", {})

    # Apply runtime defaults from system config only when env is absent.
    for key, value in runtime_env.items():
        os.environ.setdefault(str(key), str(value))

    host = os.getenv("AUTONOMOUS_HOST", str(server_cfg.get("host", "127.0.0.1")))
    port = int(os.getenv("AUTONOMOUS_PORT", str(server_cfg.get("port", 7860))))
    reload_flag = _str_to_bool(os.getenv("AUTONOMOUS_RELOAD"), bool(server_cfg.get("reload", True)))
    workers = int(os.getenv("AUTONOMOUS_WORKERS", str(server_cfg.get("workers", 1))))
    if reload_flag and workers > 1:
        # Uvicorn does not support reload with multi-workers.
        workers = 1

    os.environ.update(metadata)
    if 'ATR_PATH_BINDINGS' not in metadata:
        os.environ.pop('ATR_PATH_BINDINGS', None)
    os.chdir(paths.runtime_root)
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload_flag,
        workers=workers,
    )


if __name__ == "__main__":
    main()
