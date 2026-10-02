"""Pinned software checks executed exclusively in disposable namespaces."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import re
import html
import hashlib
import posixpath
from urllib.parse import unquote, urlsplit

from .manifest import build_manifest, validate_manifest, git_entries, _git
from .sandbox import export_tracked, run_bounded, sandbox_command

CHECKS: dict[str, list[list[str]]] = {
    "1": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_layout_manifest.py",
            "tests/unit/test_layout_validation_sandbox.py"
        ]
    ],
    "2": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_runtime_paths.py",
            "tests/unit/test_runtime_path_consumers.py",
            "tests/unit/test_source_runtime.py",
            "tests/unit/test_knowledge_archive_intake.py",
            "tests/unit/test_run_review.py",
            "tests/unit/test_experiment_runtime.py"
        ]
    ],
    "3": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_knowledge_publication.py"
        ]
    ],
    "4": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_package_contracts.py",
            "tests/unit/test_langgraph_runtime.py",
            "tests/unit/test_module_control_views.py",
            "tests/unit/test_runtime_reference_roots.py",
            "tests/unit/test_orchestrator_capabilities.py",
            "tests/unit/test_ide_module_lifecycle_js.py",
            "tests/integration/test_agent_execution_graph_api.py",
            "tests/integration/test_packages_api.py",
            "tests/integration/test_design_module_lifecycle.py"
        ],
        [
            "node",
            "--test",
            "tests/js/agent_module_host.test.cjs",
            "tests/js/module_execution_editor.test.cjs",
            "tests/js/module_control_view.test.cjs",
            "tests/js/module_control_structure.test.cjs"
        ]
    ],
    "5": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_knowledge_layout_compatibility.py",
            "tests/unit/test_runtime_wiki_safety.py",
            "tests/unit/test_knowledge_workspace_services.py",
            "tests/unit/test_manual_knowledge_ingest.py",
            "tests/unit/test_manual_knowledge_retrieval.py",
            "tests/unit/test_rag.py",
            "tests/unit/test_graphify_bridge.py",
            "tests/unit/test_source_runtime.py",
            "tests/unit/test_knowledge_archive_intake.py",
            "tests/integration/test_knowledge_graphify_api.py"
        ]
    ],
    "6": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_persisted_references.py",
            "tests/unit/test_run_recovery_checkpoint.py",
            "tests/unit/test_equipment_tail_recovery.py",
            "tests/unit/test_bo_budget_recovery.py",
            "tests/unit/test_run_review_artifacts.py",
            "tests/unit/test_agent_artifact_archive.py",
            "tests/unit/test_run_review.py",
            "tests/unit/test_artifact_preservation.py"
        ],
        [
            "node",
            "--test",
            "tests/js/run_review_artifacts.test.cjs"
        ]
    ],
    "7": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_runtime_worker_origins.py",
            "tests/unit/test_runtime_launchers.py",
            "tests/unit/test_compute_pool.py",
            "tests/unit/test_monitor_process.py",
            "tests/unit/test_safe_hot_reload.py",
            "tests/unit/test_local_pyautogui_bridge.py",
            "tests/unit/test_cli_restart.py",
            "tests/unit/test_module_designer_cli_contract.py"
        ]
    ],
    "8": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_document_relocation.py",
            "tests/unit/test_documentation_validation.py",
            "tests/unit/test_paper_publication_validation.py",
            "tests/unit/test_knowledge_publication.py",
            "tests/unit/test_knowledge_layout_compatibility.py"
        ],
        ["python", "scripts/validate_documentation.py", "--root", "."],
        ["python", "scripts/validate_paper_publication.py", "--root", "."],
        ["python", "-c", "import json; from pathlib import Path; from tools.repository_layout.checks import audit_document_references; m=json.loads(Path('system/maintenance/repository_layout_manifest.json').read_text()); r=audit_document_references(Path.cwd(),m); print(json.dumps({**{k:v for k,v in r.items() if k!='historical_references'}, 'historical_references_count':len(r['historical_references'])})); assert not any(r[k] for k in ('missing_files','missing_anchors','escaping_references','metadata_errors'))"]
    ],
    "9": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_distribution_layout.py",
            "tests/unit/test_install_packaging.py",
            "tests/unit/test_cli_restart.py",
            "tests/unit/test_module_designer_cli_contract.py",
            "tests/unit/test_package_contracts.py",
            "tests/unit/test_knowledge_publication.py",
            "tests/unit/test_windows_bridge_release.py",
            "tests/unit/test_windows_bridge_supervisor.py",
            "tests/unit/test_windows_bridge_self_updater.py",
            "tests/unit/test_windows_pyautogui_bridge_server_helper.py",
            "tests/unit/test_windows_pyautogui_demo_assets.py",
            "tests/unit/test_advanced_visual_work_queue_e2e.py",
            "tests/unit/test_advanced_visual_work_queue_demo.py"
        ]
    ],
    "10": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_external_asset_layout.py",
            "tests/unit/test_specimen_pose_tracker.py",
            "tests/unit/test_isaac_lab_robotis_omx_registration.py",
            "tests/unit/test_isaac_grip_pad_inset.py",
            "tests/unit/test_camera_vision_package.py",
            "tests/unit/test_utm_runtime_stack_script.py",
            "tests/unit/test_utm_runtime_camera_env.py",
            "tests/unit/test_linear_interpolation_options.py",
            "tests/unit/test_lerobot_bridge.py",
            "tests/unit/test_plc_bridge.py",
            "tests/unit/test_plc_bridge_service.py",
            "tests/unit/test_lerobot_gui_static.py",
            "tests/integration/test_rtc_queue_alignment.py",
            "libs/joint_linear_interpolation/tests/test_transmitter.py"
        ],
        [
            "node",
            "--test",
            "tests/js/omx_environment_layout.test.cjs"
        ]
    ],
    "11": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests"
        ],
        [
            "node",
            "--test",
            "tests/js"
        ]
    ],
    "12": [
        [
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "pytest_asyncio.plugin",
            "tests/unit/test_private_state_migration.py",
            "tests/unit/test_runtime_paths.py",
            "tests/unit/test_knowledge_layout_compatibility.py",
            "tests/unit/test_persisted_references.py",
            "tests/integration/test_repository_layout_equivalence.py"
        ]
    ]
}
BASELINE = "ba273ddb0fc2bf8795630d51d93d3932748e0a51"

DOCUMENT_SUFFIXES = {'.md', '.markdown', '.html', '.htm', '.rst'}
METADATA_PATH_FIELDS = {'source_of_truth', 'related_docs', 'supersedes', 'superseded_by',
                        'governing_design', 'source_refs'}


def document_locations(manifest: dict) -> dict[str, str]:
    """Explicit Task-8 intermediate locations; runtime rows have not moved yet."""
    from .move_files import document_move
    deferred = manifest.get('phase_deferrals', {})
    return {source: deferred[source]['current_location'] if source in deferred else
            row['destination'] if document_move(source, row) else source
            for source, row in {**manifest['entries'], **manifest.get('additions', {})}.items()}


def _mask_code(text: str) -> str:
    """Preserve offsets while suppressing fenced, indented and inline examples."""
    lines, fence = [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence:
            lines.append(re.sub(r'[^\n]', ' ', line))
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
        elif marker:
            fence = marker[1]
            lines.append(re.sub(r'[^\n]', ' ', line))
        elif line.startswith(('    ', '\t')):
            lines.append(re.sub(r'[^\n]', ' ', line))
        else:
            lines.append(line)
    masked = ''.join(lines)
    return re.sub(r'(`+)([^`\n]*?)\1', lambda match: ' ' * len(match[0]), masked)


def reference_spans(text: str, suffix: str) -> list[tuple[int, int, str]]:
    """Return static reference target spans; no basename search or code parsing."""
    masked = _mask_code(text) if suffix in {'.md', '.markdown'} else text
    spans = []
    patterns = [r'''\b(?:href|src)\s*=\s*["']([^"']+)["']''']
    if suffix in {'.md', '.markdown'}:
        patterns += [r'!?\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s()]+(?:\([^()]*\)[^\s()]*)*))',
                     r'^ {0,3}\[[^\]\n]+\]:\s*(?:<([^>\n]+)>|(\S+))',
                     r'<((?:https?://|mailto:)[^<>\s]+)>']
    elif suffix == '.rst':
        # Explicit RST links and file directives, never Python automodule names.
        patterns += [r'`[^`<\n]*<([^>\n]+)>`_?',
                     r'^\s*\.\.\s+(?:image|figure|include|literalinclude)::\s*(\S[^\n]*)',
                     r':doc:`(?:[^`<]*<)?([^`<>]+)>?`']
    for pattern in patterns:
        for match in re.finditer(pattern, masked, re.M | re.I):
            group = next(index for index in range(1, len(match.groups()) + 1) if match[index] is not None)
            value = match[group]
            if any(token in value for token in ('{{', '{%', '${', '<%', 'javascript:')):
                continue
            spans.append((*match.span(group), html.unescape(value)))
    return sorted(set(spans))


def _anchors(text: str, suffix: str) -> set[str]:
    masked = _mask_code(text) if suffix in {'.md', '.markdown'} else text
    anchors = set(re.findall(r'''\b(?:id|name)\s*=\s*["']([^"']+)["']''', masked, re.I))
    headings = []
    if suffix in {'.md', '.markdown'}:
        headings = re.findall(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$', masked, re.M)
        headings += re.findall(r'^([^\n]+)\n(?:={3,}|-{3,})\s*$', masked, re.M)
    elif suffix == '.rst':
        headings = re.findall(r'^([^\n]+)\n[=~^"`:+#*-]{3,}\s*$', masked, re.M)
        anchors.update(re.findall(r'^\s*\.\. _([^:]+):\s*$', masked, re.M))
    seen = {}
    for heading in headings:
        heading = re.sub(r'<[^>]+>', '', html.unescape(heading)).strip().lower()
        slug = re.sub(r'[^\w\-\s]', '', heading)
        slug = re.sub(r'\s', '-', slug)
        number = seen.get(slug, 0)
        seen[slug] = number + 1
        anchors.add(slug + (f'-{number}' if number else ''))
    return anchors


def _front_matter(text: str) -> tuple[dict, str]:
    import yaml
    marker = re.match(r'\A(?:---\r?\n|<!-- atr-doc\r?\n)', text)
    if not marker:
        return {}, text
    close = '-->' if text.startswith('<!--') else '---'
    end = re.search(r'^' + re.escape(close) + r'\s*$', text[marker.end():], re.M)
    if not end:
        raise ValueError('Unterminated metadata')
    content_end = marker.end() + end.start()
    body_start = marker.end() + end.end()
    meta = yaml.safe_load(text[marker.end():content_end])
    if not isinstance(meta, dict):
        raise ValueError('Document metadata must be a mapping')
    return meta, ' ' * body_start + text[body_start:]


def document_references(text: str, suffix: str) -> list[dict]:
    metadata, body = _front_matter(text) if suffix in {'.md', '.markdown'} else ({}, text)
    references = []
    for field in sorted(METADATA_PATH_FIELDS):
        if field in metadata:
            values = metadata[field] if isinstance(metadata[field], list) else [metadata[field]]
            references.extend({'reference': value, 'base': 'repository', 'field': field} for value in values)
    references.extend({'reference': target, 'base': 'document'} for _, _, target in reference_spans(body, suffix))
    return references


def historical_reference_errors(root: Path, original: str, current: str, manifest: dict) -> list[str]:
    """Validate a specifically reviewed immutable document's historical ledger."""
    record = manifest.get('historical_documents', {}).get(original)
    if not record:
        return ['Missing exact historical record']
    data = (root / current).read_bytes()
    entry = manifest['entries'][original]
    if (record.get('original_path') != original or record.get('revision') != manifest.get('move_revision')
            or not record.get('reason') or hashlib.sha256(data).hexdigest() != record.get('sha256')
            or ('sha256' in entry and record['sha256'] != entry['sha256'])
            or ('git_blob' in entry and record.get('git_blob') != entry['git_blob'])):
        return ['Historical bytes/provenance no longer match reviewed identity']
    references = document_references(data.decode(), Path(current).suffix.lower())
    recorded = record.get('references', [])
    if [(r['reference'], r['base']) for r in references] != [(r.get('reference'), r.get('base')) for r in recorded]:
        return ['Historical reference accounting is incomplete or reordered']
    locations = document_locations(manifest)
    errors = []
    for ref in recorded:
        parts = urlsplit(ref['reference'])
        if parts.scheme or parts.netloc or ref['reference'].startswith('/'):
            if ref.get('original_resolution') != 'external':
                errors.append('Historical external reference is not labelled external')
            continue
        target = posixpath.normpath(posixpath.join(posixpath.dirname(original) if ref['base'] == 'document' else '', unquote(parts.path))) if parts.path else original
        exists = target in locations or any(path.startswith(target + '/') for path in locations)
        if target == '.git' and ref.get('field') == 'source_of_truth':
            exists = bool(re.fullmatch('[0-9a-f]{40}', manifest.get('baseline_commit', '')))
        if ref.get('original_target') != target or not exists:
            errors.append('Historical reference does not resolve in its pinned inventory: ' + ref['reference'])
        if target in locations and ref.get('current_target') != locations[target]:
            errors.append('Historical reference has an incorrect mapped current target: ' + ref['reference'])
        if parts.fragment and Path(target).suffix.lower() in DOCUMENT_SUFFIXES and not ref.get('fragment_verified'):
            errors.append('Historical fragment lacks pinned anchor proof: ' + ref['reference'])
    return errors


def audit_document_references(repository_root: Path, manifest: dict) -> dict:
    """Audit exact tracked document rows and declared metadata bases, offline.

    Public absolute URLs/routes are counted separately and not network-checked.
    Dated audit JSON is historical evidence, not a mutable path database.
    """
    import yaml
    root = Path(repository_root).resolve()
    result = {key: [] for key in ('missing_files', 'missing_anchors', 'escaping_references', 'metadata_errors')}
    result.update(checked=0, external_urls=0, historical_references=[], repository_provenance=[])
    locations = document_locations(manifest)
    anchor_cache = {}

    def inspect(label, target, base, *, metadata=False, provenance=False, filesystem=False):
        if not isinstance(target, str):
            result['metadata_errors'].append({'document': label, 'reference': repr(target), 'reason': 'non-string path'})
            return
        result['checked'] += 1
        if provenance and target == '.git':
            if re.fullmatch('[0-9a-f]{40}', manifest.get('baseline_commit', '')) and manifest.get('entries'):
                result['repository_provenance'].append({'document': label, 'reference': '.git',
                    'baseline_commit': manifest['baseline_commit'], 'kind': 'pinned Git inventory, not a tracked document'})
            else:
                result['metadata_errors'].append({'document': label, 'reference': target, 'reason': 'Missing pinned Git provenance'})
            return
        # Typed registry values must match the unchanged Path-based consumer.
        parts = urlsplit('') if filesystem else urlsplit(html.unescape(target))
        if parts.scheme or parts.netloc or target.startswith('/'):
            if metadata:
                result['metadata_errors'].append({'document': label, 'reference': target, 'reason': 'Repository metadata is not a relative path'})
                return
            result['external_urls'] += 1
            return
        path = target if filesystem else unquote(parts.path)
        candidate = (base / path).resolve() if path else (root / label).resolve()
        issue = {'document': label, 'reference': target}
        if not candidate.is_relative_to(root):
            result['escaping_references'].append(issue)
            return
        if not candidate.exists():
            result['metadata_errors' if metadata else 'missing_files'].append(issue)
            return
        if parts.fragment and candidate.is_file() and candidate.suffix.lower() in DOCUMENT_SUFFIXES:
            if candidate not in anchor_cache:
                anchor_cache[candidate] = _anchors(candidate.read_text(encoding='utf-8'), candidate.suffix.lower())
            if unquote(parts.fragment) not in anchor_cache[candidate]:
                result['missing_anchors'].append(issue)

    for original, current in sorted(locations.items()):
        path = root / current
        suffix = path.suffix.lower()
        if suffix not in DOCUMENT_SUFFIXES and not (current.endswith(('document_manifest.yaml',
                'knowledge/manuals/registry.yaml', 'paper/artifact_manifest.yaml', 'capture_manifest.json'))):
            continue
        if not path.is_file():
            result['missing_files'].append({'document': current, 'reference': current})
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            result['escaping_references'].append({'document': current, 'reference': current})
            continue
        try:
            text = path.read_text(encoding='utf-8')
            if original in manifest.get('historical_documents', {}):
                errors = historical_reference_errors(root, original, current, manifest)
                result['metadata_errors'].extend({'document': current, 'reason': error} for error in errors)
                if not errors:
                    record = manifest['historical_documents'][original]
                    result['historical_references'].extend({'document': current, 'original_path': original,
                        'revision': record['revision'], **ref} for ref in record['references'])
                continue
            if suffix in DOCUMENT_SUFFIXES:
                metadata, body = _front_matter(text) if suffix in {'.md', '.markdown'} else ({}, text)
                for field in METADATA_PATH_FIELDS:
                    if field in metadata:
                        values = metadata[field] if isinstance(metadata[field], list) else [metadata[field]]
                        for value in values:
                            inspect(current, value, root, metadata=True, provenance=field == 'source_of_truth')
                if 'source_revision' in metadata and set(metadata.get('source_refs', [])) != set(metadata['source_revision']):
                    result['metadata_errors'].append({'document': current, 'reason': 'Wiki source key mismatch'})
                for _, _, target in reference_spans(body, suffix):
                    inspect(current, target, path.parent)
            else:
                metadata = yaml.safe_load(text)
                if current.endswith('document_manifest.yaml'):
                    for value in metadata.get('documents', []):
                        inspect(current, value, root, metadata=True)
                    if metadata.get('snapshot', {}).get('document'):
                        inspect(current, metadata['snapshot']['document'], root, metadata=True)
                elif current.endswith('knowledge/manuals/registry.yaml'):
                    for source in metadata.get('sources', []):
                        inspect(current, source.get('path'), path.parent, metadata=True, filesystem=True)
                elif current.endswith('paper/artifact_manifest.yaml'):
                    for record in metadata.get('evidence', []):
                        for value in record.get('inputs', []):
                            inspect(current, value, root, metadata=True)
                        for value in record.get('outputs', []):
                            inspect(current, value.get('path'), root, metadata=True)
                elif current.endswith('capture_manifest.json'):
                    for image in metadata.get('images', []):
                        inspect(current, image.get('file'), path.parent, metadata=True)
                    if metadata.get('reused_images'):
                        inspect(current, metadata['reused_images'], path.parent, metadata=True)
        except (UnicodeError, ValueError, TypeError, yaml.YAMLError) as exc:
            result['metadata_errors'].append({'document': current, 'reason': str(exc)})
    for key in ('missing_files', 'missing_anchors', 'escaping_references', 'metadata_errors'):
        result[key].sort(key=lambda row: json.dumps(row, sort_keys=True))
    return result

# Task 7's final, bounded cross-slice gate. Keep failures visible by partition,
# with fresh child-origin evidence and the original behavior suites alongside
# each root/default matrix. No device/model/provider lifecycle is exercised.
_TASK7_PARTITIONS = [
    # Root propagation across the composed bootstrap and app factories.
    ["tests/unit/test_runtime_paths.py", "tests/unit/test_runtime_path_consumers.py",
     "tests/unit/test_runtime_bridge_roots.py", "tests/unit/test_runtime_printer_roots.py",
     "tests/unit/test_runtime_lerobot_roots.py", "tests/unit/test_runtime_app_bridge_roots.py",
     "tests/unit/test_runtime_knowledge_roots.py", "tests/unit/test_runtime_app_knowledge_roots.py",
     "tests/unit/test_runtime_ancillary_roots.py", "tests/unit/test_knowledge_graph_cli.py"],
    # Actual fresh children: origins, metadata, environment, artifacts, cancellation.
    ["tests/unit/test_runtime_worker_origins.py", "tests/unit/test_runtime_launchers.py",
     "tests/unit/test_compute_pool.py", "tests/unit/test_monitor_process.py",
     "tests/unit/test_safe_hot_reload.py", "tests/unit/test_local_pyautogui_bridge.py",
     "tests/unit/test_cli_restart.py", "tests/unit/test_module_designer_cli_contract.py"],
    # UTM/pose/equipment synthetic behavior and private output families.
    ["tests/unit/test_utm_tools.py", "tests/unit/test_utm_runtime_bridge.py",
     "tests/unit/test_utm_camera_config.py", "tests/unit/test_utm_camera_calibration_command.py",
     "tests/unit/test_utm_runtime_camera_env.py", "tests/unit/test_utm_state_observer.py",
     "tests/unit/test_specimen_pose_tracker.py", "tests/unit/test_equipment_pyautogui_bridge.py",
     "tests/unit/test_multifidelity_contracts.py", "tests/unit/test_vision_monitor_stream.py",
     "tests/unit/test_windows_equipment_module_contract.py", "tests/unit/test_camera_vision_package.py"],
    # Both printer branches, profile helpers and artifact/provenance compatibility.
    ["tests/unit/test_prusa_bridge.py", "tests/unit/test_printer_tools.py",
     "tests/unit/test_bambu_bridge.py", "tests/unit/test_bambu_auto_orientation.py",
     "tests/unit/test_bambu_slicer_profiles.py", "tests/unit/test_printer_fleet_package.py",
     "tests/unit/test_bambu_material_priority.py", "tests/unit/test_printer_profile.py",
     "tests/unit/test_bambu_autoejection.py", "tests/unit/test_bambu_autoejection_completion_audit.py"],
    # LeRobot source and process contracts. One unchanged baseline interpreter-name
    # assertion is recorded in task-7d-report.md, not rerun to produce a known failure.
    ["tests/unit/test_lerobot_home_paths.py", "tests/unit/test_lerobot_bridge.py",
     "tests/unit/test_lerobot_tools.py", "tests/unit/test_lerobot_joint_telemetry.py",
     "tests/unit/test_lerobot_isaac_lab_e2e_contract.py", "tests/unit/test_lerobot_isaac_lab_synthetic.py",
     "tests/unit/test_lerobot_isaac_mirror_runtime_wrapper.py", "tests/unit/test_lerobot_active_robot_cam_once.py",
     "tests/unit/test_lerobot_replay.py", "tests/unit/test_lerobot_rollout_profile.py",
     "tests/unit/test_manipulation_lerobot_agent.py", "tests/unit/test_lerobot_synthetic_e2e_smoke.py",
     "tests/unit/test_lerobot_isaac_lab_validate_cli.py", "tests/unit/test_isaac_omx_mirror_mapping.py",
     "--deselect=tests/unit/test_lerobot_isaac_lab_e2e_contract.py::test_live_e2e_check_command_uses_real_10s_three_episode_preset"],
    # Knowledge ownership, ontology, evidence identities and retired API behavior.
    ["tests/unit/test_knowledge_service.py", "tests/unit/test_knowledge_graph_backend.py",
     "tests/unit/test_knowledge_ontology.py", "tests/unit/test_knowledge_agent.py",
     "tests/unit/test_knowledge_reconciliation_service.py", "tests/unit/test_knowledge_layout_compatibility.py",
     "tests/unit/test_graphify_bridge.py", "tests/unit/test_source_runtime.py",
     "tests/integration/test_knowledge_api.py", "tests/integration/test_knowledge_ontology_api.py",
     "tests/integration/test_knowledge_graphify_api.py", "tests/integration/test_markdown_knowledge_api.py"],
    # Ancillary agent semantics and the changed controller BO-store composition.
    ["tests/unit/test_analysis_agent.py", "tests/unit/test_analysis_measurement_only.py",
     "tests/unit/test_analysis_decisions.py", "tests/unit/test_design_agent.py",
     "tests/unit/test_design_decision.py", "tests/unit/test_design_evidence_display.py",
     "tests/unit/test_test_bo_workspace.py", "tests/unit/test_test_mode_cycles.py"],
]
CHECKS["7"] = [
    ["python", "-u", "-m", "pytest", "-vv", "--tb=short", "-p", "pytest_asyncio.plugin", *selection]
    for selection in _TASK7_PARTITIONS
]
# Reuse the already-approved dependency-only CPU profile, never a simulator.
CHECKS["7"][4][:1] = ["/usr/bin/env", "ISAAC_LAB_PATH=/deps/validation-tools/isaaclab-cpu-source", "/deps/bin/python3", "-S"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["check"])
    parser.add_argument("task", choices=sorted(CHECKS))
    parser.add_argument("--dependencies", type=Path)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--baseline-suite", action="store_true", help="Run bounded ordinary pytest after containment")
    args = parser.parse_args(argv)
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    private = root / ".superpowers/sdd/2026-10-01-repository-layout-migration"
    dependencies = args.dependencies or private / "deps"
    original = build_manifest(root, BASELINE)
    revision = _git(root, "rev-parse", "--verify", f"{args.revision}^{{tree}}").decode().strip()
    records = {path: (mode, kind, blob) for path, mode, kind, blob in git_entries(root, revision)}
    candidates = [path for path in ("docs/maintenance/repository_layout_manifest.json",
                                   "system/maintenance/repository_layout_manifest.json") if path in records]
    if len(candidates) != 1:
        print(json.dumps({"manifest_errors": ["Requested revision must contain exactly one public inventory"]}))
        return 1
    mode, kind, blob = records[candidates[0]]
    if kind != "blob" or mode not in {"100644", "100755"}:
        print(json.dumps({"manifest_errors": ["Revision inventory must be a regular Git blob"]}))
        return 1
    try:
        manifest = json.loads(_git(root, "cat-file", "blob", blob))
    except (ValueError, UnicodeDecodeError) as exc:
        print(json.dumps({"manifest_errors": [f"Invalid revision inventory JSON: {exc}"]}))
        return 1
    if not isinstance(manifest, dict):
        print(json.dumps({"manifest_errors": ["Revision inventory must be an object"]}))
        return 1
    errors = validate_manifest(manifest)
    if manifest.get("baseline_commit") != BASELINE or set(manifest.get("entries", {})) != set(original["entries"]):
        errors.append("Public inventory no longer accounts for the frozen baseline")
    for path, entry in manifest.get("entries", {}).items():
        if path in original["entries"] and any(entry.get(key) != original["entries"][path][key]
                                              for key in ("mode", "git_blob", "sha256", "size")):
            errors.append(f"Unexplained baseline object drift: {path}")
    if errors:
        print(json.dumps({"manifest_errors": errors}))
        return 1
    private.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="check-", dir=private) as temporary:
        snapshot = Path(temporary) / "snapshot"
        export_tracked(root, snapshot, revision=revision)
        cwd = "/snapshot/runtime" if (snapshot / "runtime/pyproject.toml").is_file() else "/snapshot"
        probe = ["python", "-c", "import json; from tools.repository_layout.sandbox import boundary_probe; b=boundary_probe(); print(json.dumps(b)); assert not b['host_paths_visible'] and not b['device_nodes'] and not b['host_pid_visible'] and not b['non_loopback_connected']"]
        commands = [["python", "-m", "pytest", "-p", "pytest_asyncio.plugin"]] if args.baseline_suite else CHECKS[args.task]
        for command in [probe, *commands]:
            completed = run_bounded(sandbox_command(snapshot, dependencies, command, cwd=cwd), timeout=args.timeout)
            print(completed.stdout, end="", flush=True)
            results.append({"command": command, "returncode": completed.returncode, "output": completed.stdout})
            if command is probe and completed.returncode:
                break
    report = {"task": args.task, "baseline": BASELINE, "revision": revision,
              "requested_revision": args.revision, "checks": results,
              "software_only": True, "complete": len(results) == len(commands) + 1}
    label = "baseline-suite" if args.baseline_suite else f"check-{args.task}"
    (private / f"{label}-results.json").write_text(json.dumps(report, indent=2))
    return 0 if report["complete"] and all(item["returncode"] == 0 for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
