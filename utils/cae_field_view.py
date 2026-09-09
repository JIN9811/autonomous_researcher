"""Read-only field display and volume section operations."""
from __future__ import annotations

from io import BytesIO
import json
import math
from pathlib import Path
import threading

_RENDER_LOCK = threading.Lock()


def load_fields(path, roots):
    path = Path(path).resolve()
    if not any(path.is_relative_to(Path(root).resolve()) for root in roots) or path.suffix != '.json':
        raise ValueError('Field path is outside artifact roots')
    if not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Field file missing or exceeds 256 MiB display budget')
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get('schema') != 'cae_fields.v1':
        raise ValueError('Expected actual cae_fields.v1 dataset')
    geo, frames = data.get('geometry'), data.get('frames')
    if not isinstance(geo, dict) or not isinstance(frames, list):
        raise ValueError('Invalid geometry or frame schema')
    if not geo and data.get('status') in ('failed', 'unsupported'):
        return data
    ids, points, elements = geo.get('node_ids'), geo.get('points'), geo.get('elements')
    if not all(isinstance(value, list) for value in (ids, points, elements)) or not ids or not elements:
        raise ValueError('Mesh arrays required')
    if len(ids) > 1000000 or len(elements) > 500000 or len(frames) > 1024:
        raise ValueError('Display budget exceeded')
    if any(not isinstance(value, int) for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('Invalid node IDs')
    node_ids = set(ids)
    if len(points) != len(ids) or any(not isinstance(row, list) or len(row) != 3 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in row) for row in points):
        raise ValueError('Invalid point array')
    for element in elements:
        if not isinstance(element, dict) or element.get('type') != 'C3D4' or not isinstance(element.get('connectivity'), list):
            raise ValueError('Unsupported element topology')
        row = element['connectivity']
        if len(row) != 4 or any(not isinstance(node, int) or node not in node_ids for node in row) or len(set(row)) != 4:
            raise ValueError('Invalid element connectivity')
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get('fields'), dict):
            raise ValueError('Invalid frame fields')
        for field in frame['fields'].values():
            if not isinstance(field, dict) or field.get('association', 'point') != 'point':
                raise ValueError('Unsupported field association')
            values, names = field.get('values'), field.get('components')
            if not isinstance(values, list) or not isinstance(names, list) or not 1 <= len(names) <= 9 or len(values) != len(ids):
                raise ValueError('Invalid field shape')
            if any(not isinstance(row, list) or len(row) != len(names) or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in row) for row in values):
                raise ValueError('Invalid field values')
    return data


def volume(data, frame, field, component=-1, scale=0):
    import numpy as np
    import pyvista as pv
    geo = data['geometry']
    if not 0 <= frame < len(data['frames']):
        raise ValueError('Frame unavailable')
    fields = data['frames'][frame]['fields']
    if field not in fields or not fields[field].get('values'):
        raise ValueError('Requested field unavailable')
    if not math.isfinite(scale) or not 0 <= scale <= 1000:
        raise ValueError('Invalid deformation scale')
    ids = geo['node_ids']
    if len(ids) > 1000000 or len(geo['elements']) > 500000 or len(set(ids)) != len(ids):
        raise ValueError('Invalid mesh or display budget exceeded')
    index = {key: i for i, key in enumerate(ids)}
    points = np.asarray(geo['points'], dtype=float)
    if points.shape != (len(ids), 3) or not np.isfinite(points).all():
        raise ValueError('Invalid mesh points')
    if scale:
        displacement = np.asarray(fields.get('U', {}).get('values'), dtype=float)
        if displacement.shape != points.shape or not np.isfinite(displacement).all():
            raise ValueError('Whole-mesh displacement unavailable')
        points = points + scale * displacement
    cells, element_ids = [], []
    for cell in geo['elements']:
        if cell['type'] != 'C3D4' or len(cell['connectivity']) != 4:
            raise ValueError('Unsupported volume topology')
        cells.extend([4, *(index[node] for node in cell['connectivity'])])
        element_ids.append(cell['id'])
    values = np.asarray(fields[field]['values'], dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    if len(values) != len(ids) or not np.isfinite(values).all():
        raise ValueError('Invalid or missing field values')
    if component < -1 or component >= values.shape[1]:
        raise ValueError('Unavailable component')
    if component == -1 and values.shape[1] > 3:
        raise ValueError('Tensor magnitude unavailable; select a component or S_MISES')
    if fields[field].get('association', 'point') != 'point':
        raise ValueError('Unsupported field association')
    grid = pv.UnstructuredGrid(np.asarray(cells), np.full(len(element_ids), pv.CellType.TETRA), points)
    scalar = np.linalg.norm(values, axis=1) if component == -1 and values.shape[1] > 1 else values[:, max(0, component)]
    grid.point_data['value'] = scalar
    grid.point_data['node_id'] = np.asarray(ids)
    grid.cell_data['element_id'] = element_ids
    return grid


def section(data, *, axis, position, frame, field, component=-1, scale=0):
    if axis not in ('x', 'y', 'z') or not math.isfinite(position):
        raise ValueError('Invalid section plane')
    grid = volume(data, frame, field, component, scale)
    normal, origin = [0., 0., 0.], list(grid.center)
    normal['xyz'.index(axis)], origin['xyz'.index(axis)] = 1., position
    sliced = grid.slice(normal=normal, origin=origin).triangulate()
    return {'interpolated': True, 'association': 'section_point', 'field': field,
            'points': sliced.points.tolist(), 'triangles': sliced.faces.reshape(-1, 4)[:, 1:].tolist(),
            'values': sliced.point_data['value'].tolist() if sliced.n_points else [],
            'owner_element_ids': sliced.cell_data['element_id'].tolist() if sliced.n_cells else []}


def export_view(data, *, frame, field, component=-1, scale=0, axis='none', position=0, camera=None):
    import numpy as np
    grid = volume(data, frame, field, component, scale)
    if axis != 'none':
        if axis not in ('x', 'y', 'z') or not math.isfinite(position):
            raise ValueError('Invalid section plane')
        normal, origin = [0., 0., 0.], list(grid.center)
        normal['xyz'.index(axis)], origin['xyz'.index(axis)] = 1., position
        grid = grid.slice(normal=normal, origin=origin).triangulate()
        if not grid.n_points:
            raise ValueError('Section does not intersect the volume')
    if camera is not None:
        values = np.asarray(camera, dtype=float)
        if values.shape != (3, 3) or not np.isfinite(values).all() or np.linalg.norm(np.cross(values[0]-values[1], values[2])) < 1e-12:
            raise ValueError('Invalid camera position, focal point or view-up vector')
    return grid, camera


def field_label(field, name, component):
    names = field.get('components', ['Value'])
    label = 'Magnitude' if component == -1 and len(names) > 1 else names[max(0, component)]
    return f"{name} · {label} [{field.get('units', '')}]"


def render_png(data, *, frame, field, component=-1, scale=0, edges=False, minimum=None, maximum=None,
               transparent=False, axis='none', position=0, camera=None, overlay=False):
    import pyvista as pv
    from PIL import Image
    grid, camera = export_view(data, frame=frame, field=field, component=component, scale=scale,
                               axis=axis, position=position, camera=camera)
    limits = None
    if minimum is not None or maximum is not None:
        if minimum is None or maximum is None or not all(math.isfinite(v) for v in (minimum, maximum)) or minimum >= maximum:
            raise ValueError('Invalid color limits')
        limits = [minimum, maximum]
    label = field_label(data['frames'][frame]['fields'][field], field, component)
    with _RENDER_LOCK:
        plot = pv.Plotter(off_screen=True, window_size=(3840, 2160))
        try:
            plot.set_background('white')
            plot.add_mesh(grid, scalars='value', cmap='viridis', clim=limits, show_edges=edges, edge_color='#535965',
                          smooth_shading=False, scalar_bar_args={'title': label, 'color': 'black', 'fmt': '%.3g', 'n_labels': 6})
            averaging = data['frames'][frame]['fields'][field].get('averaging', 'as exported')
            plot.add_text(f'Frame {frame + 1} | deformation scale {scale:g}\n{averaging}', color='black', font_size=14)
            plot.add_axes(color='black')
            if overlay:
                plot.add_mesh(volume(data, frame, field, component, 0).extract_surface(), style='wireframe', color='#a6adb8', opacity=0.25)
            if camera is not None:
                plot.camera_position = camera
            else:
                plot.view_isometric()
            plot.enable_anti_aliasing('ssaa')
            pixels = plot.screenshot(return_img=True, transparent_background=transparent)
        finally:
            plot.close()
    output = BytesIO()
    Image.fromarray(pixels).save(output, format='PNG', dpi=(300, 300))
    return output.getvalue()
