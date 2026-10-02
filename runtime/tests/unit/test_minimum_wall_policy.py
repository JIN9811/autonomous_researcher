"""The default wall constraint is 0.4 mm, not a dimensionless TPMS level."""
import pytest

from agents.design.agent import DesignAgent
from mcp_tools.mock_tools import _check_manufacturability


@pytest.mark.parametrize("wall,accepted", [(0.39, False), (0.4, True), (0.6, True)])
def test_default_wall_threshold(wall, accepted):
    result = _check_manufacturability({"constraints": {
        "geometry_type": "lattice_bcc", "wall_thickness_mm": wall,
        "cell_size_mm": 5, "relative_density": 0.3,
    }, "mesh_report": {"bbox": [30, 30, 30]}})
    assert result["ok"] is accepted


def test_explicit_stricter_contract_is_preserved():
    result = _check_manufacturability({"constraints": {
        "wall_thickness_mm": 0.4, "fdm_min_wall_thickness_mm": 0.8,
    }})
    assert result["ok"] is False


def test_design_default_wall_constraints_agree():
    for key in ("min_wall_thickness_mm", "minimum_feature_size_mm", "fdm_min_wall_thickness_mm"):
        assert DesignAgent.DEFAULT_CONSTRAINTS[key] == 0.4
