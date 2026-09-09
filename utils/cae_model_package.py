"""Export a self-contained, hash-described native FE model for offline reuse."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil


def export_model_package(request: dict, paths: dict) -> dict:
    deck = Path(paths['inp_path'])
    if re.search(r'^\s*\*INCLUDE\b', deck.read_text(), re.IGNORECASE | re.MULTILINE):
        raise ValueError('External INCLUDE must be resolved before model export')
    root = deck.parent / f'{deck.stem}.model_package'
    root.mkdir(parents=True, exist_ok=True)
    sources = {'model.inp': deck}
    for name, source in (('mesh.inp', paths.get('mesh_inp_path')),
                         ('source.stl', request.get('stl_path')),
                         ('preparation.json', paths.get('manifest_path'))):
        if source and Path(source).is_file():
            sources[name] = Path(source)
    files = {}
    for name, source in sources.items():
        target = root / name
        shutil.copyfile(source, target)
        files[name] = {'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'bytes': target.stat().st_size}
    keys = ('material', 'mesh_size_mm', 'surface_remesh', 'specimen_size_mm', 'gauge_length_mm',
            'cross_section_area_mm2', 'loading', 'boundary', 'boundary_condition', 'loading_mode',
            'fixture', 'boundary_tolerance_mm', 'target_displacement_mm', 'target_strain',
            'compression_target_strain', 'computation_limits', 'increments')
    metadata = {'schema':'cae_reusable_model.v1', 'solver':'CalculiX',
                'validation_status':'not_promoted', 'scope':'prepared_native_FE_model',
                'units':{'length':'mm','force':'N','stress':'MPa','energy':'N mm'},
                'identity':{key:request.get(key) for key in ('run_id','loop_key','specimen_id','original_specimen_id','job_id')},
                'parameters':{key:request[key] for key in keys if key in request},
                'authoritative_conditions':'model.inp and preparation.json', 'files':files}
    manifest = root/'model.json'
    manifest.write_text(json.dumps(metadata, indent=2, allow_nan=False) + '\n')
    (root/'README.md').write_text(
        '# Reusable finite-element model\n\n'
        'This package contains the actual prepared mesh and self-contained solver input. '
        'Copy the entire directory to another machine; no ATR server or original absolute path is required.\n\n'
        '## Run\n\nInstall CalculiX, open this directory, and run:\n\n'
        '```sh\nccx -i model\n```\n\n'
        'The deck is authoritative for material, constraints, loading, increments and output requests. '
        'Units are mm, N and MPa; integrated work in N mm converts to joules by dividing by 1000. '
        'Solver versions and thread settings can affect reproducibility.\n\n'
        '## Contents\n\n'
        '- `model.inp`: complete executable model (mesh, material, boundary/loading conditions).\n'
        '- `mesh.inp`: prepared mesh when available.\n'
        '- `source.stl`: source geometry when available; remeshing is not needed to rerun the deck.\n'
        '- `preparation.json`: detailed model preparation evidence when available.\n'
        '- `model.json`: units, input parameters, ownership and SHA-256 inventory.\n\n'
        'Export does not establish material calibration, mesh convergence or predictive validity. '
        'Consult the owning FEM job for actual solver status, contours and experiment comparisons. '
        'Import into another FE package requires checking its element/material and boundary-condition support.\n')
    return {'model_package_path':str(root), 'model_package_manifest_path':str(manifest)}
