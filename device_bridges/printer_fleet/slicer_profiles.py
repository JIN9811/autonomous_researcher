"""Resolve Bambu preset inheritance before passing standalone JSON to the CLI."""
from __future__ import annotations

import json
import copy
import math
from pathlib import Path

from utils.printer_profile import normalize_xy_speed_scale


# Explicit XY process speeds; Z is resolved separately below. Never scale retraction, fans, acceleration,
# extrusion volume, or machine start/end G-code. Relative speeds inherit scaling
# from their parent speed and must not be multiplied twice.
XY_PROCESS_SPEEDS = frozenset({
    "outer_wall_speed", "inner_wall_speed", "small_perimeter_speed",
    "sparse_infill_speed", "internal_solid_infill_speed", "gap_infill_speed",
    "top_surface_speed", "initial_layer_speed", "initial_layer_infill_speed",
    "travel_speed", "bridge_speed", "ironing_speed", "support_ironing_speed",
    "support_speed", "support_interface_speed", "vertical_shell_speed",
    "overhang_1_4_speed", "overhang_2_4_speed", "overhang_3_4_speed",
    "overhang_4_4_speed", "overhang_totally_speed",
    "slowdown_start_speed", "slowdown_end_speed", "prime_tower_max_speed",
})
XY_SPEED_MINIMUMS = {
    "initial_layer_infill_speed": 1.0,
    "support_interface_speed": 1.0,
    "travel_speed": 1.0,
    "prime_tower_max_speed": 10.0,
}


def scale_xy_process_profile(profile: dict, percent: float, *, z_speed_limit: float | None = None) -> dict:
    """Scale XYZ; keep the historical name/key for saved-profile compatibility."""
    factor = normalize_xy_speed_scale(percent) / 100.0
    result = copy.deepcopy(profile)
    if factor == 1:
        return result

    def scaled(value, minimum):
        if isinstance(value, list):
            return [scaled(item, minimum) for item in value]
        if isinstance(value, str) and value.strip().endswith("%"):
            return value
        speed = float(value)
        if not math.isfinite(speed) or speed < 0:
            raise ValueError("Invalid XY speed in process profile")
        if speed == 0:  # Vendor sentinel: use the normal feature speed.
            return value
        return format(max(minimum, speed * factor), ".10g")

    for key in XY_PROCESS_SPEEDS & result.keys():
        result[key] = scaled(result[key], XY_SPEED_MINIMUMS.get(key, 0))
    if "travel_speed_z" in profile or "travel_speed" in profile:
        z_values = profile.get("travel_speed_z", "0")
        travel = profile.get("travel_speed", "0")
        def z_scaled(value, index):
            speed = float(value)
            if not math.isfinite(speed) or speed < 0:
                raise ValueError("Invalid Z speed in process profile")
            if speed == 0:
                inherited = travel[min(index, len(travel) - 1)] if isinstance(travel, list) and travel else travel
                speed = float(inherited)
            if not math.isfinite(speed) or speed <= 0:
                raise ValueError("Z scaling requires a positive resolved travel speed")
            if z_speed_limit is not None:
                speed = min(speed, z_speed_limit)
            return format(speed * factor, ".10g")
        result["travel_speed_z"] = ([z_scaled(value, index) for index, value in enumerate(z_values)]
                                    if isinstance(z_values, list) else z_scaled(z_values, 0))
    return result


def resolve_profile(path: Path, stack: tuple[Path, ...] = ()) -> dict:
    path = path.resolve()
    if path in stack or len(stack) >= 32:
        raise ValueError(f'Cyclic or excessive preset inheritance: {path.name}')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'Invalid preset: {path.name}')
    parent = data.get('inherits', '')
    merged = {}
    if parent:
        if not isinstance(parent, str) or Path(parent).name != parent:
            raise ValueError(f'Invalid parent in {path.name}')
        merged = resolve_profile(path.parent / f'{parent}.json', (*stack, path))
    includes = data.get('include', [])
    if not isinstance(includes, list):
        raise ValueError(f'Invalid includes in {path.name}')
    for name in includes:
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError(f'Invalid include in {path.name}')
        merged.update(resolve_profile(path.parent / f'{name}.json', (*stack, path)))
    merged.update(data)
    merged.pop('inherits', None)
    merged.pop('include', None)
    return merged
