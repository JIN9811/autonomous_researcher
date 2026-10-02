#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
import builtins
from pathlib import Path


def _delegate(script_name: str) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from integrations.isaac_lab_robotis_omx.external_callback import register

    register()
    builtins.input = lambda *_args, **_kwargs: "y"
    isaac_lab = Path("/home/jin/IsaacLab")
    if "--isaac-lab-path" in sys.argv:
        index = sys.argv.index("--isaac-lab-path")
        isaac_lab = Path(sys.argv[index + 1])
        del sys.argv[index : index + 2]
    script = isaac_lab / "scripts" / "imitation_learning" / "robomimic" / script_name
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")


def main() -> None:
    _delegate("train.py")


if __name__ == "__main__":
    main()
