"""Regression for the quadratic-cost node lookup seen on specimen-sized meshes."""
import time

from utils.calculix_fields import _parse_inp


def test_mesh_connectivity_check_does_not_rescan_all_nodes_for_each_element():
    # 20k x 40k lookups took many seconds; linear membership completes well below
    # this intentionally generous bound. No solver, rendering or disk I/O timed.
    nodes = '\n'.join(f'{i},0,0,{i}' for i in range(1, 40001))
    elements = '\n'.join(f'{i},{i},{i+1},{i+2},{i+3}' for i in range(1, 20001))
    text = f'*NODE\n{nodes}\n*ELEMENT,TYPE=C3D4,ELSET=VOLUME\n{elements}\n'
    started = time.monotonic()
    ids, parsed_nodes, parsed_elements = _parse_inp(text)
    elapsed = time.monotonic() - started
    assert len(ids) == len(parsed_nodes) == 40000
    assert len(parsed_elements) == 20000
    assert parsed_elements[-1]['connectivity'] == [20000,20001,20002,20003]
    assert elapsed < 3, f'Connectivity validation took {elapsed:.2f}s; possible nodes-per-element scan'
