"""Strict CalculiX ASCII field conversion and tetrahedral mesh evidence.

The converter deliberately supports only first-order solid tetrahedra. It does
not corner-linearize higher-order cells, invent missing nodal values, or relabel
CalculiX's extrapolated/averaged FRD stress as raw integration-point stress.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


_FLOAT = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d{1,3})?")
_SUPPORTED_INP = {"C3D4": (4, "tetra4")}
_SUPPORTED_FRD = {3: (4, "C3D4")}
_STRESS_COMPONENTS = ["SXX", "SYY", "SZZ", "SXY", "SYZ", "SZX"]
MAX_FIELD_FILE_BYTES = 256 * 1024 * 1024
MAX_NODES = 1_000_000
MAX_ELEMENTS = 500_000
MAX_FIELD_VALUES = 8_000_000


class _FieldError(ValueError):
    def __init__(self, code: str, detail: Any) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _base_result(inp_path: Path, frd_path: Path) -> dict[str, Any]:
    return {
        "schema": "cae_fields.v1",
        "status": "failed",
        "failure_code": None,
        "inp_path": str(inp_path),
        "frd_path": str(frd_path),
        "source_hashes": {},
        "geometry_path": "",
        "frames_path": "",
        "field_asset_path": "",
        "geometry": {},
        "frames": [],
        "mesh_evidence": {},
        "warnings": [],
        "errors": [],
    }


def _failed(base: dict[str, Any], code: str, detail: Any, *, status: str = "failed") -> dict[str, Any]:
    base["status"] = status
    base["failure_code"] = code
    if isinstance(detail, list):
        base["errors"] = detail
    elif detail:
        base["errors"] = [detail]
    return base


def _read_ascii(path: Path, kind: str) -> tuple[str, bytes]:
    if not path.is_file():
        raise _FieldError(f"CALCULIX_FIELD_{kind}_REQUIRED", {"path": str(path)})
    if path.stat().st_size > MAX_FIELD_FILE_BYTES:
        raise _FieldError('CALCULIX_FIELD_BUDGET_EXCEEDED', {'path': str(path), 'byte_limit': MAX_FIELD_FILE_BYTES})
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise _FieldError("CALCULIX_FIELD_BINARY_FRD_UNSUPPORTED", {"path": str(path)})
    try:
        return raw.decode("ascii"), raw
    except UnicodeDecodeError as exc:
        raise _FieldError(
            f"CALCULIX_FIELD_{kind}_NOT_ASCII", {"path": str(path), "byte_offset": exc.start}
        ) from exc


def _finite_float(token: str, *, context: str) -> float:
    try:
        value = float(token.replace("D", "E").replace("d", "e"))
    except ValueError as exc:
        raise _FieldError("CALCULIX_FIELD_FORMAT_INVALID", {"context": context, "value": token}) from exc
    if not math.isfinite(value):
        raise _FieldError("CALCULIX_FIELD_NONFINITE_VALUE", {"context": context, "value": token})
    return value


def _keyword_parameters(line: str) -> tuple[str, dict[str, str]]:
    parts = [part.strip() for part in line.split(",")]
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            params[key.strip().upper()] = value.strip().upper()
    return parts[0].upper(), params


def _parse_inp(text: str) -> tuple[list[int], dict[int, list[float]], list[dict[str, Any]]]:
    node_order: list[int] = []
    nodes: dict[int, list[float]] = {}
    elements: list[dict[str, Any]] = []
    element_ids: set[int] = set()
    mode = ""
    element_type = ""
    unsupported: set[str] = set()
    for line_number, raw in enumerate(text.replace("\r", "").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            keyword, params = _keyword_parameters(line)
            mode = "node" if keyword == "*NODE" else "element" if keyword == "*ELEMENT" else ""
            if mode == "element":
                element_type = params.get("TYPE", "")
                if element_type not in _SUPPORTED_INP:
                    unsupported.add(element_type or "UNSPECIFIED")
            continue
        parts = [part.strip() for part in line.split(",")]
        if mode == "node":
            if len(parts) != 4:
                raise _FieldError("CALCULIX_FIELD_INP_FORMAT_INVALID", {"line": line_number, "record": "NODE"})
            try:
                node_id = int(parts[0])
            except ValueError as exc:
                raise _FieldError("CALCULIX_FIELD_INP_FORMAT_INVALID", {"line": line_number, "record": "NODE"}) from exc
            if node_id in nodes:
                raise _FieldError("CALCULIX_FIELD_NODE_ID_DUPLICATE", {"node_id": node_id})
            nodes[node_id] = [_finite_float(value, context=f"INP node {node_id}") for value in parts[1:]]
            if len(nodes) > MAX_NODES:
                raise _FieldError('CALCULIX_FIELD_BUDGET_EXCEEDED', {'node_limit': MAX_NODES})
            node_order.append(node_id)
        elif mode == "element" and element_type in _SUPPORTED_INP:
            expected = _SUPPORTED_INP[element_type][0]
            if len(parts) != expected + 1:
                raise _FieldError(
                    "CALCULIX_FIELD_INP_FORMAT_INVALID",
                    {"line": line_number, "record": element_type, "expected_node_count": expected},
                )
            try:
                element_id = int(parts[0])
                connectivity = [int(value) for value in parts[1:]]
            except ValueError as exc:
                raise _FieldError("CALCULIX_FIELD_INP_FORMAT_INVALID", {"line": line_number, "record": element_type}) from exc
            if element_id in element_ids:
                raise _FieldError("CALCULIX_FIELD_ELEMENT_ID_DUPLICATE", {"element_id": element_id})
            element_ids.add(element_id)
            elements.append({"id": element_id, "type": element_type, "connectivity": connectivity})
            if len(elements) > MAX_ELEMENTS:
                raise _FieldError('CALCULIX_FIELD_BUDGET_EXCEEDED', {'element_limit': MAX_ELEMENTS})
    if unsupported:
        raise _FieldError(
            "CALCULIX_FIELD_TOPOLOGY_UNSUPPORTED", {"unsupported_topologies": sorted(unsupported)}
        )
    if not nodes or not elements:
        raise _FieldError(
            "CALCULIX_FIELD_INP_MESH_REQUIRED",
            {"node_count": len(nodes), "element_count": len(elements)},
        )
    bad = []
    for element in elements:
        unknown = sorted(node_id for node_id in set(element["connectivity"]) if node_id not in nodes)
        if unknown:
            bad.append({"element_id": element["id"], "unknown_node_ids": unknown})
        elif len(set(element["connectivity"])) != len(element["connectivity"]):
            bad.append({"element_id": element["id"], "duplicate_node_ids": element["connectivity"]})
    if bad:
        raise _FieldError("CALCULIX_FIELD_CONNECTIVITY_INVALID", bad)
    return node_order, nodes, elements


def _record_id_and_values(line: str, *, context: str) -> tuple[int, list[float]]:
    match = re.match(r"^\s*-1\s+(\d+)(.*)$", line)
    if not match:
        raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"context": context, "record": line})
    item_id = int(match.group(1))
    values = [_finite_float(token, context=context) for token in _FLOAT.findall(match.group(2))]
    return item_id, values


def _parse_frd_header(line: str) -> tuple[float, int, int]:
    if len(line) < 75 or line[2:6] != "100C":
        raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": "100C", "value": line})
    value = _finite_float(line[12:24].strip(), context="FRD dataset value")
    try:
        node_count = int(line[24:36])
        step = int(line[58:63])
        fmt = int(line[73:75])
    except ValueError as exc:
        raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": "100C", "value": line}) from exc
    if fmt not in {0, 1}:
        raise _FieldError("CALCULIX_FIELD_BINARY_FRD_UNSUPPORTED", {"format": fmt})
    return value, step, node_count


def _printed_half_unit(token: str) -> float:
    """Absolute half rounding unit of the actual ASCII coordinate token."""
    mantissa, _, exponent = token.upper().replace('D', 'E').partition('E')
    decimals = len(mantissa.partition('.')[2])
    power = int(exponent or 0) - decimals
    if not -323 <= power <= 308:
        raise _FieldError('CALCULIX_FIELD_FORMAT_INVALID', {'coordinate_precision': token})
    return 0.5 * 10.0 ** power


def _parse_frd(text: str) -> dict[str, Any]:
    lines = text.replace("\r", "").splitlines()
    nodes: dict[int, list[float]] = {}
    coordinate_tolerances: dict[int, list[float]] = {}
    elements: dict[int, dict[str, Any]] = {}
    blocks: list[dict[str, Any]] = []
    pending_result: tuple[int, int, int] | None = None
    index = 0
    field_values = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if re.match(r"^2C\b", stripped):
            index += 1
            while index < len(lines) and lines[index].strip() != "-3":
                node_id, values = _record_id_and_values(lines[index], context="FRD coordinate")
                if len(values) != 3 or node_id in nodes:
                    raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": lines[index]})
                nodes[node_id] = values
                tokens = _FLOAT.findall(re.match(r'^\s*-1\s+\d+(.*)$', lines[index]).group(1))
                coordinate_tolerances[node_id] = [_printed_half_unit(token) for token in tokens]
                if len(nodes) > MAX_NODES:
                    raise _FieldError('CALCULIX_FIELD_BUDGET_EXCEEDED', {'node_limit': MAX_NODES})
                index += 1
        elif re.match(r"^3C\b", stripped):
            index += 1
            while index < len(lines) and lines[index].strip() != "-3":
                match = re.match(r"^\s*-1\s+(\d+)\s+(\d+)\s+(-?\d+)\s+(-?\d+)\s*$", lines[index])
                if not match:
                    raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": lines[index]})
                element_id, frd_type = int(match.group(1)), int(match.group(2))
                if element_id in elements:
                    raise _FieldError('CALCULIX_FIELD_ELEMENT_ID_DUPLICATE', {'element_id': element_id})
                if frd_type not in _SUPPORTED_FRD:
                    raise _FieldError(
                        "CALCULIX_FIELD_TOPOLOGY_UNSUPPORTED",
                        {"unsupported_topologies": [f"FRD_TYPE_{frd_type}"]},
                    )
                expected, inp_type = _SUPPORTED_FRD[frd_type]
                connectivity: list[int] = []
                index += 1
                while index < len(lines) and lines[index].lstrip().startswith("-2"):
                    try:
                        connectivity.extend(int(token) for token in lines[index].split()[1:])
                    except ValueError as exc:
                        raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": lines[index]}) from exc
                    index += 1
                if len(connectivity) != expected:
                    raise _FieldError(
                        "CALCULIX_FIELD_FRD_FORMAT_INVALID",
                        {"element_id": element_id, "expected_node_count": expected, "actual_node_count": len(connectivity)},
                    )
                elements[element_id] = {"id": element_id, "type": inp_type, "connectivity": connectivity}
                if len(elements) > MAX_ELEMENTS:
                    raise _FieldError('CALCULIX_FIELD_BUDGET_EXCEEDED', {'element_limit': MAX_ELEMENTS})
                continue
        elif re.match(r"^1PSTEP\b", stripped):
            tokens = stripped.split()
            if len(tokens) != 4:
                raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": raw})
            try:
                pending_result = (int(tokens[1]), int(tokens[2]), int(tokens[3]))
            except ValueError as exc:
                raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": raw}) from exc
        elif len(raw) >= 6 and raw[2:6] == "100C":
            value, total_increment, declared_node_count = _parse_frd_header(raw)
            if pending_result is None:
                raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": "100C without 1PSTEP"})
            dataset_id, increment, step = pending_result
            index += 1
            if index >= len(lines):
                raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": "missing -4"})
            header = re.match(r"^\s*-4\s+([A-Za-z0-9_()%]+)\s+(\d+)\s+(\d+)\s*$", lines[index])
            if not header:
                raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": lines[index]})
            name, declared_components, result_type = header.group(1).upper(), int(header.group(2)), int(header.group(3))
            if result_type not in {1, 2, 3}:
                raise _FieldError("CALCULIX_FIELD_RESULT_TYPE_UNSUPPORTED", {"dataset": name, "result_type": result_type})
            components: list[str] = []
            index += 1
            for _ in range(declared_components):
                if index >= len(lines):
                    raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": "missing -5"})
                component = re.match(r"^\s*-5\s+([^\s]+)", lines[index])
                if not component:
                    raise _FieldError("CALCULIX_FIELD_FRD_FORMAT_INVALID", {"record": lines[index]})
                component_name = component.group(1).upper()
                if component_name != "ALL":
                    components.append(component_name)
                index += 1
            values_by_node: dict[int, list[float]] = {}
            while index < len(lines) and lines[index].strip() != "-3":
                node_id, values = _record_id_and_values(lines[index], context=f"FRD {name}")
                index += 1
                while len(values) < len(components) and index < len(lines) and lines[index].lstrip().startswith("-2"):
                    values.extend(
                        _finite_float(token, context=f"FRD {name}") for token in _FLOAT.findall(lines[index][3:])
                    )
                    index += 1
                if len(values) != len(components) or node_id in values_by_node:
                    raise _FieldError(
                        "CALCULIX_FIELD_FRD_FORMAT_INVALID",
                        {"dataset": name, "node_id": node_id, "component_count": len(values)},
                    )
                values_by_node[node_id] = values
                field_values += len(values)
                if field_values > MAX_FIELD_VALUES:
                    raise _FieldError('CALCULIX_FIELD_BUDGET_EXCEEDED', {'value_limit': MAX_FIELD_VALUES})
            if declared_node_count != len(values_by_node):
                raise _FieldError(
                    "CALCULIX_FIELD_FRD_NODE_COUNT_MISMATCH",
                    {"dataset": name, "declared": declared_node_count, "actual": len(values_by_node)},
                )
            blocks.append(
                {
                    "name": name,
                    "dataset_id": dataset_id,
                    "step": step,
                    "increment": increment,
                    "total_increment": total_increment,
                    "value": value,
                    "components": components,
                    "values_by_node": values_by_node,
                    "result_type": result_type,
                }
            )
            pending_result = None
        index += 1
    if not nodes or not elements:
        raise _FieldError(
            "CALCULIX_FIELD_FRD_MESH_REQUIRED",
            {"node_count": len(nodes), "element_count": len(elements)},
        )
    return {"nodes": nodes, "coordinate_tolerances": coordinate_tolerances, "elements": elements, "blocks": blocks}


def _cross_validate_mesh(
    node_order: list[int],
    inp_nodes: dict[int, list[float]],
    inp_elements: list[dict[str, Any]],
    frd: dict[str, Any],
) -> None:
    errors: list[dict[str, Any]] = []
    frd_nodes = frd["nodes"]
    if set(frd_nodes) != set(node_order):
        errors.append(
            {
                "node_ids": {
                    "missing_in_frd": sorted(set(node_order) - set(frd_nodes)),
                    "extra_in_frd": sorted(set(frd_nodes) - set(node_order)),
                }
            }
        )
    for node_id in set(node_order) & set(frd_nodes):
        tolerances = frd['coordinate_tolerances'][node_id]
        if any(abs(left - right) > tolerance + 8 * math.ulp(max(abs(left), abs(right), 1.0))
               for left, right, tolerance in zip(inp_nodes[node_id], frd_nodes[node_id], tolerances)):
            errors.append({"node_id": node_id, "inp_coordinates": inp_nodes[node_id], "frd_coordinates": frd_nodes[node_id]})
    frd_elements = frd["elements"]
    input_ids = {item["id"] for item in inp_elements}
    if set(frd_elements) != input_ids:
        errors.append(
            {
                "element_ids": {
                    "missing_in_frd": sorted(input_ids - set(frd_elements)),
                    "extra_in_frd": sorted(set(frd_elements) - input_ids),
                }
            }
        )
    for element in inp_elements:
        other = frd_elements.get(element["id"])
        if other and (other["type"] != element["type"] or other["connectivity"] != element["connectivity"]):
            errors.append(
                {
                    "element_id": element["id"],
                    "inp_type": element["type"],
                    "frd_type": other["type"],
                    "inp_connectivity": element["connectivity"],
                    "frd_connectivity": other["connectivity"],
                }
            )
    if errors:
        raise _FieldError("CALCULIX_FIELD_MESH_MISMATCH", errors)


def _sub(left: list[float], right: list[float]) -> list[float]:
    return [left[index] - right[index] for index in range(3)]


def _det(a: list[float], b: list[float], c: list[float]) -> float:
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _tetra_facts(connectivity: list[int], nodes: dict[int, list[float]]) -> tuple[float, float, float]:
    a, b, c, d = (nodes[node_id] for node_id in connectivity)
    signed_jacobian = _det(_sub(b, a), _sub(c, a), _sub(d, a))
    corner_edges = (
        (_sub(b, a), _sub(c, a), _sub(d, a)),
        (_sub(a, b), _sub(d, b), _sub(c, b)),
        (_sub(d, c), _sub(a, c), _sub(b, c)),
        (_sub(c, d), _sub(b, d), _sub(a, d)),
    )
    scaled = []
    for first, second, third in corner_edges:
        denominator = _norm(first) * _norm(second) * _norm(third)
        scaled.append(_det(first, second, third) / denominator if denominator else float("-inf"))
    return signed_jacobian / 6.0, signed_jacobian, min(scaled)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    ratio = position - lower
    return ordered[lower] * (1.0 - ratio) + ordered[upper] * ratio


def _mesh_contract(
    node_order: list[int], nodes: dict[int, list[float]], elements: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    coordinates = [nodes[node_id] for node_id in node_order]
    span = [max(row[axis] for row in coordinates) - min(row[axis] for row in coordinates) for axis in range(3)]
    length_scale = max(math.sqrt(sum(value * value for value in span)), 1.0)
    determinant_tolerance = length_scale**3 * 1e-12
    volumes: list[float] = []
    jacobians: list[float] = []
    qualities: list[float] = []
    invalid: list[dict[str, Any]] = []
    cells_seen: set[tuple[int, ...]] = set()
    for element in elements:
        cell_key = tuple(sorted(element['connectivity']))
        if cell_key in cells_seen:
            raise _FieldError('CALCULIX_FIELD_MESH_INVALID', {'reason': 'duplicate_cell', 'element_id': element['id']})
        cells_seen.add(cell_key)
        volume, jacobian, quality = _tetra_facts(element["connectivity"], nodes)
        volumes.append(volume)
        jacobians.append(jacobian)
        qualities.append(quality)
        if jacobian <= determinant_tolerance:
            invalid.append(
                {
                    "element_id": element["id"],
                    "reason": "inverted" if jacobian < -determinant_tolerance else "degenerate",
                    "signed_jacobian_determinant_mm3": jacobian,
                }
            )
    if invalid:
        raise _FieldError("CALCULIX_FIELD_MESH_INVALID", invalid)

    faces: dict[tuple[int, int, int], list[tuple[list[int], int]]] = defaultdict(list)
    for element in elements:
        a, b, c, d = element["connectivity"]
        for face in ([b, c, d], [a, d, c], [a, b, d], [a, c, b]):
            faces[tuple(sorted(face))].append((face, element["id"]))
    boundary = [owners[0] for owners in faces.values() if len(owners) == 1]
    nonmanifold = [list(face) for face, owners in faces.items() if len(owners) > 2]
    if nonmanifold:
        raise _FieldError(
            "CALCULIX_FIELD_MESH_INVALID",
            [{"reason": "nonmanifold_face", "node_ids": face} for face in nonmanifold],
        )
    for face, owners in faces.items():
        if len(owners) == 2:
            left, right = owners[0][0], owners[1][0]
            offset = right.index(left[0])
            if right[(offset + 1) % 3] == left[1]:
                raise _FieldError('CALCULIX_FIELD_MESH_INVALID', {'reason': 'inconsistent_shared_face_orientation', 'node_ids': face})
    threshold = 0.2
    below = [elements[index]["id"] for index, value in enumerate(qualities) if value < threshold]
    geometry = {
        "schema": "cae_geometry.v1",
        "coordinate_system": "global_cartesian",
        "units": "mm",
        "node_ids": node_order,
        "points": coordinates,
        "elements": elements,
        "surface": {
            "triangles": [face for face, _ in boundary],
            "owner_element_ids": [element_id for _, element_id in boundary],
            "derived_from": "exact_boundary_faces_of_supported_volume_cells",
        },
    }
    evidence = {
        "schema": "cae_mesh_evidence.v1",
        "validity": {
            "status": "valid",
            "node_count": len(nodes),
            "element_count": len(elements),
            "finite_coordinate_count": len(nodes),
            "dangling_connectivity_count": 0,
            "degenerate_or_inverted_element_count": 0,
            "nonmanifold_face_count": 0,
        },
        "volume": {
            "definition": "signed_linear_tetra_volume",
            "units": "mm3",
            "minimum_mm3": min(volumes),
            "maximum_mm3": max(volumes),
        },
        "jacobian": {
            "definition": "constant_signed_linear_tetra_mapping_determinant",
            "evaluation": "one exact constant value per C3D4",
            "units": "mm3",
            "minimum": min(jacobians),
            "failed_element_count": 0,
            "tolerance": determinant_tolerance,
            "tolerance_policy": "max(bounding_box_diagonal_mm,1mm)^3 * 1e-12",
        },
        "quality": {
            "metric": "minimum_corner_scaled_jacobian",
            "definition": "minimum over four oriented corner determinants divided by incident edge-length product",
            "minimum": min(qualities),
            "percentile_1": _percentile(qualities, 0.01),
            "percentile_5": _percentile(qualities, 0.05),
            "diagnostic_threshold": threshold,
            "threshold_policy": "diagnostic reference for this declared C3D4 metric; not a universal solver gate",
            "below_threshold_fraction": len(below) / len(qualities),
            "below_threshold_element_ids": below,
        },
    }
    return geometry, evidence


def _field_from_block(block: dict[str, Any], node_order: list[int]) -> tuple[str, dict[str, Any]] | None:
    metadata: dict[str, tuple[str, list[str], str, str]] = {
        "DISP": ("U", ["D1", "D2", "D3"], "mm", "none"),
        "STRESS": ("S", _STRESS_COMPONENTS, "MPa", "solver_extrapolated_and_nodal_averaged"),
        "TOSTRAIN": ("E", ["EXX", "EYY", "EZZ", "EXY", "EYZ", "EZX"], "1", "solver_extrapolated_and_nodal_averaged"),
        "PE": ("PEEQ", ["PEEQ"], "1", "solver_extrapolated_and_nodal_averaged"),
        "PEEQ": ("PEEQ", ["PEEQ"], "1", "solver_extrapolated_and_nodal_averaged"),
    }
    if block["name"] not in metadata:
        return None
    canonical, expected, units, averaging = metadata[block["name"]]
    # CalculiX's PEEQ request is written as dataset PE / component PE in FRD.
    # Keep the canonical output name PEEQ while accepting that exact alias.
    plastic_scalar_alias = block["name"] == "PE" and block["components"] == ["PE"]
    if block["components"] != expected and not plastic_scalar_alias:
        raise _FieldError(
            "CALCULIX_FIELD_COMPONENTS_UNSUPPORTED",
            {"dataset": block["name"], "components": block["components"], "expected": expected},
        )
    actual_ids = set(block["values_by_node"])
    missing = [node_id for node_id in node_order if node_id not in actual_ids]
    extra = sorted(actual_ids - set(node_order))
    if extra:
        raise _FieldError("CALCULIX_FIELD_MESH_MISMATCH", [{"dataset": block["name"], "extra_node_ids": extra}])
    if missing:
        if canonical == "U":
            raise _FieldError(
                "CALCULIX_FIELD_DISPLACEMENT_INCOMPLETE",
                {"step": block["step"], "value": block["value"], "missing_node_ids": missing},
            )
        return None
    return canonical, {
        "association": "point",
        "components": ["U1", "U2", "U3"] if canonical == "U" else expected,
        "units": units,
        "coordinate_system": "global_cartesian",
        "averaging": averaging,
        "source": "CalculiX ASCII FRD nodal result block",
        "values": [block["values_by_node"][node_id] for node_id in node_order],
    }


def _mises(stress: list[float]) -> float:
    xx, yy, zz, xy, yz, zx = stress
    return math.sqrt(
        0.5 * ((xx - yy) ** 2 + (yy - zz) ** 2 + (zz - xx) ** 2)
        + 3.0 * (xy * xy + yz * yz + zx * zx)
    )


def _frames_contract(blocks: list[dict[str, Any]], node_order: list[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[tuple[int, int, float], dict[str, Any]] = {}
    warnings: list[dict[str, Any]] = []
    displacement_errors: list[dict[str, Any]] = []
    for block in blocks:
        key = (block["step"], block["increment"], block["value"])
        frame = grouped.setdefault(
            key,
            {
                "step": block["step"],
                "increment": block["increment"],
                "total_increment": block["total_increment"],
                "value": block["value"],
                "source_dataset_ids": [],
                "fields": {},
            },
        )
        frame["source_dataset_ids"].append(block["dataset_id"])
        if frame["total_increment"] != block["total_increment"]:
            raise _FieldError(
                "CALCULIX_FIELD_FRAME_METADATA_MISMATCH",
                {"step": block["step"], "increment": block["increment"]},
            )
        try:
            converted = _field_from_block(block, node_order)
        except _FieldError as exc:
            if exc.code == "CALCULIX_FIELD_DISPLACEMENT_INCOMPLETE":
                displacement_errors.append(exc.detail)
                continue
            raise
        if converted is None:
            warnings.append(
                {
                    "code": "CALCULIX_FIELD_DATASET_SKIPPED",
                    "dataset": block["name"],
                    "step": block["step"],
                    "value": block["value"],
                    "reason": "unsupported_or_incomplete",
                }
            )
            continue
        field_name, field = converted
        if field_name in frame["fields"]:
            raise _FieldError(
                "CALCULIX_FIELD_DATASET_DUPLICATE",
                {"field": field_name, "step": block["step"], "value": block["value"]},
            )
        frame["fields"][field_name] = field
    frames = []
    for index, key in enumerate(sorted(grouped)):
        frame = grouped[key]
        frame.update({"index": index, "time": frame["value"]})
        stress = frame["fields"].get("S")
        if stress:
            frame["fields"]["S_MISES"] = {
                "association": "point",
                "components": ["MISES"],
                "units": "MPa",
                "coordinate_system": "global_cartesian",
                "averaging": stress["averaging"],
                "source": "derived from full S tensor after source averaging",
                "derived_from": "S",
                "values": [[_mises(value)] for value in stress["values"]],
            }
        frames.append(frame)
    if displacement_errors:
        raise _FieldError(
            "CALCULIX_FIELD_DISPLACEMENT_INCOMPLETE",
            {"frames": frames, "errors": displacement_errors, "warnings": warnings},
        )
    missing_frames = [frame["index"] for frame in frames if "U" not in frame["fields"]]
    if not frames or missing_frames:
        raise _FieldError(
            "CALCULIX_FIELD_DISPLACEMENT_REQUIRED",
            {"frames": frames, "errors": [{"missing_displacement_frames": missing_frames}], "warnings": warnings},
        )
    return frames, warnings


def _write_assets(base: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    geometry_path = output_dir / "geometry.json"
    frames_path = output_dir / "frames.json"
    manifest_path = output_dir / "manifest.fields.json"
    if sum(len(frame['fields']) for frame in base['frames']) > 4096:
        raise _FieldError('CALCULIX_FIELD_BUDGET_EXCEEDED', {'field_count_limit': 4096})
    geometry_path.write_text(json.dumps(base["geometry"], indent=2, ensure_ascii=True), encoding="utf-8")
    frames_path.write_text(
        json.dumps({"schema": "cae_field_frames.v1", "frames": base["frames"]}, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    base["geometry_path"] = str(geometry_path)
    base["frames_path"] = str(frames_path)
    base["field_asset_path"] = str(manifest_path)
    encoded = json.dumps(base, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    if len(encoded) > MAX_FIELD_FILE_BYTES:
        base.update(field_asset_path='', geometry_path='', frames_path='')
        raise _FieldError('CALCULIX_FIELD_BUDGET_EXCEEDED', {'manifest_byte_limit': MAX_FIELD_FILE_BYTES})
    manifest_path.write_text(encoded, encoding="utf-8")


def postprocess_fields(inp_path: Path | str, frd_path: Path | str, output_dir: Path | str) -> dict[str, Any]:
    """Convert a matching C3D4 INP/ASCII-FRD pair into browser JSON assets."""
    inp = Path(inp_path).expanduser().resolve()
    frd = Path(frd_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    result = _base_result(inp, frd)
    try:
        inp_text, inp_raw = _read_ascii(inp, "INP")
        frd_text, frd_raw = _read_ascii(frd, "FRD")
        result["source_hashes"] = {
            "inp_sha256": hashlib.sha256(inp_raw).hexdigest(),
            "frd_sha256": hashlib.sha256(frd_raw).hexdigest(),
        }
        node_order, nodes, elements = _parse_inp(inp_text)
        parsed_frd = _parse_frd(frd_text)
        _cross_validate_mesh(node_order, nodes, elements, parsed_frd)
        result["geometry"], result["mesh_evidence"] = _mesh_contract(node_order, nodes, elements)
        try:
            result["frames"], warnings = _frames_contract(parsed_frd["blocks"], node_order)
        except _FieldError as exc:
            if exc.code in {"CALCULIX_FIELD_DISPLACEMENT_INCOMPLETE", "CALCULIX_FIELD_DISPLACEMENT_REQUIRED"}:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                result["frames"] = detail.get("frames", [])
                result["warnings"] = detail.get("warnings", [])
                result["errors"] = detail.get("errors", [])
                result["failure_code"] = exc.code
                _write_assets(result, destination)
                return result
            raise
        result["warnings"] = warnings + [
            {
                "code": "CALCULIX_UNITS_ASSUMED",
                "message": "CalculiX decks are unitless; this workflow declares the established mm/N/MPa unit system.",
            }
        ]
        result["status"] = "complete"
        _write_assets(result, destination)
        return result
    except _FieldError as exc:
        if exc.code == "CALCULIX_FIELD_TOPOLOGY_UNSUPPORTED" and isinstance(exc.detail, dict):
            result["unsupported_topologies"] = exc.detail.get("unsupported_topologies", [])
            return _failed(result, exc.code, [], status="unsupported")
        return _failed(result, exc.code, exc.detail)
    except OSError as exc:
        result.update(field_asset_path='', geometry_path='', frames_path='')
        return _failed(result, 'CALCULIX_FIELD_IO_FAILED', {'message': str(exc)})
