"""Evidence-first nonlinear FEM review; no solver changes or physical effects.

Typed observations are declarations from upstream research evidence, not facts
inferred from a force drop or an LLM answer. Hashes establish provenance, not
the scientific truth of the supplied characterization.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path


def _references(record, evidence):
    refs = record.get('refs')
    hashes = evidence.get('input_hashes') or {}
    geometry = (evidence.get('payload') or {}).get('stl_path')
    forbidden_hashes = {value for value in (hashes.get(geometry), evidence.get('raw_sha256')) if value}
    if not isinstance(refs, list) or not refs:
        return False
    try:
        return all(isinstance(ref, str) and ref in hashes
                   and hashes[ref] not in forbidden_hashes
                   and (not geometry or Path(ref).resolve() != Path(geometry).resolve())
                   and hashlib.sha256(Path(ref).read_bytes()).hexdigest() == hashes[ref]
                   for ref in refs)
    except (OSError, TypeError, ValueError):
        return False


def assess_mechanisms(evidence, attempts, convergence):
    """Separate numerical evidence, deformation agreement and material support.

    Research calibration needs independently sourced printed-material evidence
    (or an applicability-reviewed literature prior) and a referenced deformation
    comparison. This is permission to test a hypothesis, never model promotion.
    """
    declared = (evidence.get('policy') or {}).get('mechanism_evidence') or {}
    if not isinstance(declared, dict):
        declared = {}
    basis = declared.get('material_basis') or {}
    deformation = declared.get('deformation_comparison') or {}
    basis = basis if isinstance(basis, dict) else {}
    deformation = deformation if isinstance(deformation, dict) else {}
    acquisitions = basis.get('acquisition_ids') or []
    target_acquisitions = list(evidence.get('acquisition_ids') or [])
    if evidence.get('acquisition_id'):
        target_acquisitions.append(evidence['acquisition_id'])
    independent = (isinstance(acquisitions, list) and bool(acquisitions)
                   and all(isinstance(a, str) and a.strip() for a in acquisitions)
                   and bool(target_acquisitions) and not set(acquisitions).intersection(target_acquisitions))
    coupon = (basis.get('kind') == 'printed_material_coupon' and independent
              and basis.get('same_print_process') is True)
    prior = (basis.get('kind') == 'literature_prior' and basis.get('applicability_reviewed') is True
             and isinstance(basis.get('citation'), str) and bool(basis['citation'].strip()))
    material_supported = bool((coupon or prior) and _references(basis, evidence))
    # The currently registered calibration family is post-yield softening.
    softening_supported = material_supported and basis.get('post_yield_softening_observed') is True
    deformation_status = deformation.get('status') if _references(deformation, evidence) else 'not_assessed'
    if deformation_status not in {'consistent', 'mismatch'}:
        deformation_status = 'not_assessed'
    last = attempts[-1] if attempts else {}
    numerical = ('not_run' if not last else 'complete' if last.get('endpoint_reached')
                 and last.get('solver_status') == 'complete' else 'incomplete')
    required = []
    if numerical == 'incomplete':
        required.append('solver_diagnostics')
    if not material_supported or not softening_supported:
        required.append('material_characterization')
    if deformation_status != 'consistent':
        required.append('deformation_comparison')
    if convergence.get('status') != 'converged':
        required.append('mesh_sensitivity')
    required.extend(['increment_sensitivity', 'independent_prediction'])
    return {
        'schema': 'analysis_mechanism_assessment.v1',
        'baseline_action': 'preserve', 'material_promotable': False,
        'material_mechanism': 'source_supported_softening_hypothesis' if softening_supported else 'unidentified',
        'material_basis_kind': basis.get('kind', 'missing'),
        'provenance_scope': 'hash-verified references and declared characterization; not automatic physical validation',
        'deformation_comparison': deformation_status, 'numerical_status': numerical,
        'calibration_admissible': bool(softening_supported and deformation_status == 'consistent'
                                      and numerical != 'incomplete'),
        'softening_regularization': 'not_implemented', 'required_evidence': required,
        'mechanisms_to_distinguish': ['geometric_buckling', 'material_post_yield_response',
                                    'damage_or_layer_separation', 'internal_self_contact'],
        'capabilities': {'mesh_sensitivity': 'existing_bounded_mesh_study',
                         'explicit_quasistatic': 'not_registered_in_this_workflow',
                         'damage_regularization': 'not_registered_in_this_workflow',
                         'self_contact': 'not_registered_in_this_workflow'},
    }


def evidence_options(report):
    """Non-actuating evidence requests; only mesh studies use existing tools."""
    mapping = {'solver_diagnostics': 'review_solver_diagnostics',
               'material_characterization': 'request_material_characterization',
               'deformation_comparison': 'review_deformation'}
    return {mapping[item]: None for item in report['required_evidence'] if item in mapping}


def freeze_mechanism_references(evidence, directory):
    """Snapshot explicitly supplied local research references beside job inputs.

    Missing references remain unresolved and cannot authorize calibration. This
    does not fetch URLs, invent characterization or mutate the user's policy.
    """
    declared = deepcopy((evidence.get('policy') or {}).get('mechanism_evidence'))
    if not isinstance(declared, dict):
        return {}
    hashes = evidence.setdefault('input_hashes', {})
    originals = {}
    for name in ('material_basis', 'deformation_comparison'):
        record = declared.get(name)
        if not isinstance(record, dict) or not isinstance(record.get('refs'), list):
            continue
        refs = []
        for ref in record['refs']:
            if not isinstance(ref, str) or not Path(ref).is_file():
                refs.append(ref)
                continue
            content = Path(ref).read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            destination = Path(directory) / (digest + Path(ref).suffix.lower())
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                with destination.open('xb') as stream:
                    stream.write(content)
            except FileExistsError:
                if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                    raise ValueError('Frozen mechanism reference hash mismatch')
            frozen = str(destination.resolve())
            hashes[frozen] = digest
            originals[str(Path(ref).resolve())] = digest
            refs.append(frozen)
            if name == 'deformation_comparison' and destination.suffix.lower() in {'.png', '.jpg', '.jpeg'}:
                images = evidence.setdefault('image_paths', [])
                if frozen not in images:
                    images.append(frozen)
        record['refs'] = refs
    evidence['policy']['mechanism_evidence'] = declared
    return originals
