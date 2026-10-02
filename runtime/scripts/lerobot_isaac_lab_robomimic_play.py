#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _patch_torch_squeeze_for_policy_obs() -> None:
    import torch

    original_squeeze = torch.squeeze

    def squeeze_preserving_single_feature(input, dim=None):  # type: ignore[no-untyped-def]
        if dim is not None:
            return original_squeeze(input, dim)
        output = original_squeeze(input)
        if getattr(input, "ndim", 0) >= 1 and getattr(output, "ndim", 0) == 0:
            return output.reshape(1)
        return output

    torch.squeeze = squeeze_preserving_single_feature


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from integrations.isaac_lab_robotis_omx.external_callback import register

    register()
    _patch_torch_squeeze_for_policy_obs()
    isaac_lab = Path("/home/jin/IsaacLab")
    if "--isaac-lab-path" in sys.argv:
        index = sys.argv.index("--isaac-lab-path")
        isaac_lab = Path(sys.argv[index + 1])
        del sys.argv[index : index + 2]
    script = isaac_lab / "scripts" / "imitation_learning" / "robomimic" / "play.py"
    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
