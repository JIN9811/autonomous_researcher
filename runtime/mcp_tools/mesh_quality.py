"""Inspect serialized STL topology; only remove degenerate/duplicate faces.

No hole filling, smoothing, remeshing, component removal or normal repair is
performed here. A remaining defect is reported, never converted into a pass.
"""
import hashlib
import os
from pathlib import Path
import tempfile


def _load_stl(path):
    import numpy as np
    import trimesh
    mesh = trimesh.load_mesh(path, process=False)
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise ValueError('Mesh is empty or has non-finite coordinates')
    # Merge serialized shared vertices, without silently dropping bad input.
    mesh.process(validate=False)
    return mesh


def _report(mesh, expected_bbox=None):
    import numpy as np
    reasons = []
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise ValueError('Mesh is empty or has non-finite coordinates')
    counts = np.bincount(mesh.edges_unique_inverse)
    boundary = int((counts == 1).sum())
    nonmanifold = int((counts > 2).sum())
    degenerate = int((~mesh.nondegenerate_faces()).sum())
    duplicate = int((~mesh.unique_faces()).sum())
    watertight = bool(mesh.is_watertight)
    winding = bool(mesh.is_winding_consistent)
    volume = float(mesh.volume)
    components = int(mesh.body_count)
    bbox = mesh.extents.tolist()
    if not watertight: reasons.append('mesh_not_watertight')
    if nonmanifold: reasons.append('non_manifold_edges')
    if degenerate: reasons.append('degenerate_faces')
    if duplicate: reasons.append('duplicate_faces')
    if not winding: reasons.append('inconsistent_face_winding')
    if volume <= 0: reasons.append('non_positive_or_inverted_volume')
    if components != 1: reasons.append('disconnected_components')
    if expected_bbox is not None:
        expected = np.asarray(expected_bbox, dtype=float)
        if expected.shape != (3,) or not np.isfinite(expected).all() or (expected <= 0).any():
            reasons.append('invalid_expected_bounding_box')
        elif not np.allclose(mesh.extents, expected, rtol=0, atol=0.05):
            reasons.append('bounding_box_mismatch')
    return {'ok': not reasons, 'watertight': watertight, 'winding_consistent': winding,
            'boundary_edges': boundary, 'non_manifold_edges': nonmanifold,
            'degenerate_faces': degenerate, 'duplicate_faces': duplicate,
            'inverted_normals': 0 if winding and volume > 0 else None,
            'self_intersections': None, 'self_intersection_check': 'not_performed',
            'disconnected_components': components, 'bbox': bbox, 'volume_mm3': volume,
            'vertex_count': len(mesh.vertices), 'triangle_count': len(mesh.faces),
            'reject_reasons': reasons}


def inspect_stl(path, expected_bbox=None):
    """Read-only validation of the exact file passed to downstream tools."""
    path = Path(path)
    try:
        mesh = _load_stl(path)
        report = _report(mesh, expected_bbox)
        return {**report, 'stl_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    except (OSError, ValueError, TypeError, AttributeError, IndexError) as exc:
        return {'ok': False, 'reject_reasons': ['mesh_unreadable'],
                'error': f'{type(exc).__name__}: {exc}'}


def finalize_generated_stl(path, expected_bbox=None):
    """Clean after STL float32 serialization, then verify another disk read."""
    import numpy as np
    path = Path(path)
    mesh = _load_stl(path)
    bounds_before = mesh.bounds.copy()
    faces_before = len(mesh.faces)
    nondegenerate = mesh.nondegenerate_faces()
    removed_degenerate = int((~nondegenerate).sum())
    mesh.update_faces(nondegenerate)
    unique = mesh.unique_faces()
    removed_duplicate = int((~unique).sum())
    mesh.update_faces(unique)
    mesh.remove_unreferenced_vertices()
    if not len(mesh.faces) or not np.allclose(mesh.bounds, bounds_before, rtol=0, atol=1e-6):
        raise ValueError('Mesh cleanup would empty or change the specimen envelope')
    if removed_degenerate or removed_duplicate:
        # Publish only a verified serialized candidate, not an in-memory verdict.
        descriptor, temporary = tempfile.mkstemp(prefix='.mesh-clean-', suffix='.stl', dir=path.parent)
        os.close(descriptor)
        try:
            mesh.export(temporary)
            checked = inspect_stl(temporary, expected_bbox)
            if not checked['ok']:
                raise ValueError(f"Generated STL remains invalid: {checked['reject_reasons']}")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    checked = inspect_stl(path, expected_bbox)
    if not checked['ok']:
        raise ValueError(f"Generated STL remains invalid: {checked['reject_reasons']}")
    return {'schema': 'serialized_mesh_cleanup.v1', 'faces_before': faces_before,
            'removed_degenerate_faces': removed_degenerate, 'removed_duplicate_faces': removed_duplicate,
            'final_validation': checked}
