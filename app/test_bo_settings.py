"""Read a BO workspace preset once for test planning, never for live cycles."""
from copy import deepcopy
import json

from agents.bo.agent import BOAgent
from utils.gyroid_contract import BOUNDS, parameter_space
from utils.paths import resolve_path

WORKSPACE_SETTINGS_PATH = resolve_path("memory/bo_workspace_settings.json")


def validate_initial_design_size(value):
    if type(value) is not int or value < 2:
        raise ValueError("LHS initial design size must be an integer of at least 2")
    return value


def load_test_bo_defaults():
    """Whitelist only count and continuous ranges; do not import mode or devices."""
    try:
        saved = json.loads(WORKSPACE_SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        saved = {}
    if not isinstance(saved, dict):
        raise ValueError("BO workspace settings must be an object")
    defaults = BOAgent.defaults()
    count = saved.get("initial_design_size", defaults["initial_design_size"])
    if count == "auto":
        count = defaults["initial_design_size"]
    space = saved.get("parameter_space", {})
    if not isinstance(space, dict):
        raise ValueError("BO parameter space must be an object")
    values = {"initial_design_size": validate_initial_design_size(count)}
    values.update({field: deepcopy(space.get(variable, BOAgent.DEFAULT_PARAMETER_SPACE[variable]))
                   for field, variable in BOUNDS.items()})
    parameter_space(values, required=True)
    return values


def with_initial_design(values):
    """Translate the chat count to the existing run contract without other defaults."""
    result = deepcopy(values)
    if "initial_design_size" in result:
        size = validate_initial_design_size(result["initial_design_size"])
        optimization = result.setdefault("design_optimization", {})
        initial = optimization.setdefault("initial_design", {})
        initial.update(size=size, sampler="latin_hypercube")
    return result
