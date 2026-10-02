import pytest

from agents.bo.agent import BOAgent
from agents.design.agent import DesignAgent
from mcp_tools.mock_tools import _generate_geometry_stl


def test_default_design_domain_starts_at_five():
    assert min(DesignAgent.DEFAULT_DESIGN_SPACE["cell_size_mm"]) == 5.0


def test_bo_bounds_preserve_operator_domain():
    assert BOAgent._two_variable_parameter_space({"cell_size_mm": [3, 10]})["cell_size_mm"] == [3, 10]
    assert BOAgent._two_variable_parameter_space({"cell_size_mm": [5]})["cell_size_mm"] == [5]
    assert BOAgent._two_variable_parameter_space({"wall_thickness_mm": [.8, 1.6]})["wall_thickness_mm"] == [.8, 1.6]


@pytest.mark.parametrize("value", [0, -1, float("nan")])
def test_generation_rejects_small_cells_before_writing(value):
    with pytest.raises(ValueError, match="positive and finite"):
        _generate_geometry_stl({"cell_size_mm": value})


def test_bo_rejects_fixed_cell_below_minimum():
    with pytest.raises(ValueError):
        BOAgent._two_variable_parameter_space({"cell_size_mm": [0]})
    with pytest.raises(ValueError):
        BOAgent._lock_parameter_space({}, cell_size_mm=0)
