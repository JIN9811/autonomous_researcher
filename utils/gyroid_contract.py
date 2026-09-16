"""Shared research-variable contract, independent of execution/bridge mode."""
import math

BOUNDS = {"cell_size_bounds_mm": "cell_size_mm", "wall_thickness_bounds_mm": "wall_thickness_mm"}
POLICY = (
    "For gyroid collect the user's continuous cell_size_bounds_mm and wall_thickness_bounds_mm, "
    "including decimal endpoints; do not assume defaults are consent. Suggested ranges are 5–10 mm "
    "and wall thickness 0.6–1.2 mm; these are also the test-mode defaults. "
    "The mandatory minimum actual mesh wall is 0.4 mm (stricter is allowed). "
    "Explain at review that an in-range candidate may fail the wall check and will not be printed; "
    "record rejected candidates and request another point within the agreed bounds; never relax the wall limit. "
    "Cell size is the spatial period, not an integer cell count: generate an enclosing periodic "
    "field and center-crop to the agreed specimen dimensions. Wall thickness and cell size determine the "
    "gyroid level. Relative density is a derived output, never an independent design variable. "
    "Apply this same contract to live runs, installed-printer tests, full physical prints and virtual bridges."
)


def parameter_space(values, *, required=False):
    space = {}
    for field, variable in BOUNDS.items():
        bounds = values.get(field)
        if bounds is None:
            if required:
                raise ValueError(f"User range required: {field}")
            continue
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in bounds)
                or not 0 < bounds[0] < bounds[1]):
            raise ValueError(f"Invalid continuous range: {field}")
        space[variable] = list(bounds)
    return space


def validate_candidate(values, space=None):
    space = parameter_space(values) if space is None else space
    for variable in BOUNDS.values():
        if variable not in values:
            continue
        value = values[variable]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid gyroid variable: {variable}")
        if variable in space and not space[variable][0] <= value <= space[variable][1]:
            raise ValueError(f"Gyroid variable outside user contract: {variable}")
    for key in ("fdm_min_wall_thickness_mm", "min_wall_thickness_mm"):
        if key in values and (type(values[key]) not in (int, float) or not math.isfinite(values[key]) or values[key] < 0.4):
            raise ValueError("Minimum actual mesh wall cannot be below 0.4 mm")
