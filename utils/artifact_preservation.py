"""Additive, read-only-evidence backfill. No agents, model fitting or device calls.

Original execution manifests/results are immutable here. All derived outputs live
inside their original attempt, so existing artifact APIs retain exact ownership.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import shutil
import threading
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from utils.agent_artifact_archive import _json, _file_candidates, resolve_artifact_reference

VERSION = 1
AGENTS = ('orchestrator', 'design', 'specimen', 'vision', 'manipulation', 'equipment', 'analysis', 'knowledge', 'bo', 'guardian')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _inside(root, path):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('Evidence path escapes run')
    return resolved


def _curves(source, output, title):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    columns = {k: [] for k in ('displacement_mm', 'force_N', 'strain', 'stress_MPa')}
    with source.open(newline='') as stream:
        for row in csv.DictReader(stream):
            values = [float(row[k]) for k in columns]
            if all(math.isfinite(x) for x in values):
                for key, value in zip(columns, values):
                    columns[key].append(value)
    if not columns['force_N']:
        raise ValueError('No finite canonical curve samples')
    for name, x, y, xlabel, ylabel in (
        ('force_displacement', 'displacement_mm', 'force_N', 'Displacement (mm)', 'Force (N)'),
        ('stress_strain', 'strain', 'stress_MPa', 'Engineering strain (1)', 'Engineering stress (MPa)'),
    ):
        fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
        try:
            ax.plot(columns[x], columns[y], color='#168cc1', linewidth=1.3)
            ax.set(xlabel=xlabel, ylabel=ylabel, title=title + '\n' + name.replace('_', ' ').title())
            ax.grid(alpha=.2)
            for suffix in ('png', 'svg'):
                fig.savefig(output / f'{name}.{suffix}', dpi=150, facecolor='white')
        finally:
            plt.close(fig)


def preserve_execution(run_dir, manifest_path):
    """Only finished, identity-qualified evidence; never manufacture missing inputs."""
    run = Path(run_dir).resolve()
    manifest_path = _inside(run, manifest_path)
    directory = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 'atr.agent_artifact_execution.v1' or manifest.get('run_id') != run.name:
        raise ValueError('Execution identity mismatch')
    if manifest.get('status') not in {'completed', 'failed', 'cancelled'}:
        return {'status': 'recording', 'agent': manifest.get('agent')}
    if directory.relative_to(run).parts[:4] != ('runtime', 'loops', f"loop-{int(manifest['loop_index'])+1:06d}", manifest['agent']):
        raise ValueError('Execution ownership mismatch')
    result_path = _inside(run, directory / 'result.json')
    source_hash = digest(result_path)
    manifest_hash = digest(manifest_path)
    stream_hashes = {str(p.relative_to(run)): digest(_inside(run, p)) for p in directory.glob('streams/*/session.json')}
    for p in directory.glob('streams/*/grasp_display_v5/*'):
        if p.is_file() and p.name in {'policy_tracking.png', 'policy_tracking_summary.json', 'grasp_outcomes.json'}:
            stream_hashes[str(p.relative_to(run))] = digest(_inside(run, p))
    output = _inside(run, directory / 'preserved')
    output.mkdir(exist_ok=True)
    if any(path.is_symlink() for path in output.rglob('*')):
        raise ValueError('Derived output contains a symlink')
    receipt_path = output / 'evidence_index.json'
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get('version') == VERSION and receipt.get('source_sha256') == source_hash
                and receipt.get('manifest_sha256') == manifest_hash and receipt.get('stream_sha256') == stream_hashes):
            if all(_inside(run, run / item['path']).is_file() for item in receipt.get('generated', [])):
                return receipt
    payload = json.loads(result_path.read_text()).get('data', {})
    generated, gaps, sources = [], [], []
    def record(path, source):
        path = _inside(run, path)
        generated.append({'path': path.relative_to(run).as_posix(), 'source': source,
                          'sha256': digest(path), 'size_bytes': path.stat().st_size})

    # Repair URL-only evidence by copying only this run's durable source. Never
    # backfill historical /tmp/latest images using today's camera frame.
    copied_sources = {str(x.get('source_path')) for x in manifest.get('artifacts', []) if x.get('status') == 'copied'}
    seen_references = set()
    for key, candidate in _file_candidates(payload):
        resolved = resolve_artifact_reference(candidate, run.parent.parent, run)
        if resolved is None or str(resolved) in copied_sources or str(resolved) in seen_references:
            continue
        seen_references.add(str(resolved))
        if resolved.is_relative_to(run / 'runtime/loops'):
            # A motor log/archived image is already frozen under its owner.
            # Keep the reference rather than duplicating GB-scale telemetry.
            if resolved.is_file():
                sources.append({'path': resolved.relative_to(run).as_posix(), 'meaning': 'Existing execution-scoped evidence'})
            continue
        # Immutable knowledge revisions from this exact run can also be restored.
        knowledge = run.parent.parent / 'memory/knowledge/markdown/records' / run.name
        immutable_note = resolved.is_relative_to(knowledge.resolve()) and resolved.name.startswith('revision-')
        if not (resolved.is_relative_to(run) or immutable_note):
            if str(candidate).startswith('/api/') or str(resolved).startswith('/tmp/atr_'):
                gaps.append({'key': key, 'status': 'historical_source_unavailable'})
            continue
        if not resolved.is_file():
            gaps.append({'key': key, 'status': 'source_missing'})
            continue
        dest = output / (digest(resolved) + '_' + resolved.name)
        if not dest.exists():
            shutil.copyfile(resolved, dest)
        if not any(x['path'] == dest.relative_to(run).as_posix() for x in generated):
            record(dest, str(resolved))

    if manifest['agent'] == 'design_agent' and isinstance(payload.get('candidate_ledger'), list):
        candidates = payload['candidate_ledger']
        _json(output / 'candidate_comparison.json', candidates)
        record(output / 'candidate_comparison.json', 'result.json#/data/candidate_ledger')
        rows = []
        for candidate in candidates:
            for constraint in (candidate.get('design_evaluation') or {}).get('constraint_margins', []):
                rows.append({'candidate_id': candidate.get('candidate_id'), **constraint})
        _json(output / 'constraint_checks.json', rows)
        record(output / 'constraint_checks.json', 'result.json#/data/candidate_ledger')
        points = [c for c in candidates if isinstance(c.get('cell_size_mm'), (int, float)) and isinstance(c.get('wall_thickness_mm'), (int, float))]
        if points:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(7, 5), constrained_layout=True)
            try:
                for c in points:
                    ax.scatter(c['cell_size_mm'], c['wall_thickness_mm'], marker='*' if c.get('status') == 'selected' else 'o', s=80)
                    ax.annotate(str(c.get('candidate_id', '')), (c['cell_size_mm'], c['wall_thickness_mm']), xytext=(4, 6), textcoords='offset points', fontsize=8)
                ax.set(xlabel='Cell size (mm)', ylabel='Wall thickness (mm)', title=f"Cycle {manifest['loop_number']} · Saved design candidates")
                ax.grid(alpha=.2)
                for suffix in ('png', 'svg'):
                    path = output / f'design_space.{suffix}'
                    fig.savefig(path, dpi=150, facecolor='white')
                    record(path, 'result.json#/data/candidate_ledger')
            finally:
                plt.close(fig)

    if manifest['agent'] == 'manipulation_agent':
        for stream_path in directory.glob('streams/*/session.json'):
            stream_path = _inside(run, stream_path)
            session = json.loads(stream_path.read_text())
            if str(session.get('status', '')).upper() in {'COMPLETED', 'STOPPED', 'FAILED', 'CANCELLED'}:
                log = _inside(run, stream_path.parent / 'motor_events.jsonl')
                revised = _inside(run, stream_path.parent / 'grasp_display_v5')
                if all((revised / name).is_file() for name in (
                        'policy_tracking.png', 'policy_tracking_summary.json', 'grasp_outcomes.json')):
                    for name in ('policy_tracking.png', 'policy_tracking_summary.json', 'grasp_outcomes.json'):
                        record(revised / name, str(log.relative_to(run)))
                    continue
                graph = _inside(run, stream_path.parent / 'policy_tracking.png')
                if log.is_file() and not graph.is_file():
                    from utils.lerobot_joint_telemetry import finalize_policy_tracking_artifacts
                    finalize_policy_tracking_artifacts(log, session)
                if graph.is_file():
                    record(graph, str(log.relative_to(run)))

    # Use the archived snapshot, not a mutable live canonical file.
    if manifest['agent'] == 'analysis_agent':
        canonical = next((x for x in manifest.get('artifacts', [])
                          if x.get('status') == 'copied' and str(x.get('source_path', '')).endswith('/canonical_curve.csv')), None)
        try:
            if not canonical:
                raise ValueError('Archived canonical CSV unavailable')
            source = _inside(run, run / canonical['path'])
            if digest(source) != canonical['sha256']:
                raise ValueError('Archived canonical CSV checksum mismatch')
            _curves(source, output, f"Cycle {manifest['loop_number']} · {manifest.get('specimen_id', '')}")
            for path in sorted(output.glob('*_*.png')) + sorted(output.glob('*_*.svg')):
                record(path, canonical['path'])
            sources.append({'path': canonical['path'], 'sha256': canonical['sha256'], 'meaning': 'Saved canonical data; no metric recalculation'})
        except (ValueError, OSError, KeyError) as exc:
            gaps.append({'component': 'analysis_curves', 'status': 'unavailable', 'reason': str(exc)})

    if manifest['agent'] == 'bo_agent':
        bo = payload.get('bo_result') or {}
        for key, module, function in (
            ('lhs_visualization', 'reporting.lhs_design_visualization_artifacts', 'write_lhs_design_visualization_artifacts'),
            ('visualization', 'reporting.bo_visualization_artifacts', 'write_bo_visualization_artifacts'),
        ):
            visualization = bo.get(key)
            if not isinstance(visualization, dict) or not visualization.get('schema'):
                continue  # Initial design has no fitted GP; do not invent one.
            try:
                from importlib import import_module
                if visualization.get('run_id') != run.name:
                    raise ValueError('Visualization belongs to another run')
                for item in getattr(import_module(module), function)(visualization, output):
                    record(Path(item['path']), f'result.json#/data/bo_result/{key}')
            except Exception as exc:
                gaps.append({'component': key, 'status': 'render_failed', 'reason': type(exc).__name__})

    # The full result/input/event files remain the authoritative evidence for
    # ALL agents, including knowledge citations, Guardian gates and handoffs.
    retained = []
    for name in ('input.json', 'result.json', 'events.jsonl', 'manifest.json'):
        path = _inside(run, directory / name)
        if path.is_file():
            retained.append({'path': path.relative_to(run).as_posix(), 'role': name})
        else:
            gaps.append({'component': name, 'status': 'missing'})
    for item in manifest.get('artifacts', []):
        if item.get('path'):
            path = _inside(run, run / item['path'])
            if not path.is_file():
                gaps.append({'component': item.get('key'), 'status': 'archived_file_missing'})
    receipt = {'schema': 'atr.artifact_preservation.v1', 'version': VERSION,
               'run_id': run.name, 'agent': manifest['agent'], 'loop_index': manifest['loop_index'],
               'execution_id': manifest['execution_id'], 'source_sha256': source_hash,
               'manifest_sha256': manifest_hash, 'stream_sha256': stream_hashes,
               'result_components': sorted(payload) if isinstance(payload, dict) else [],
               'retained': retained, 'archived_files': len([x for x in manifest.get('artifacts', []) if x.get('path')]),
               'sources': sources, 'generated': generated, 'gaps': gaps,
               'status': 'needs_attention' if gaps else 'preserved', 'actuation_performed': False}
    _json(receipt_path, receipt)
    return receipt


def preserve_run(run_dir):
    run = Path(run_dir).resolve()
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    with (run / '.artifact-preservation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'already_preserving'}
        receipts = []
        for manifest in sorted((run / 'runtime/loops').glob('loop-*/*/attempt-*/manifest.json')):
            try:
                receipts.append(preserve_execution(run, manifest))
            except Exception as exc:
                receipts.append({'status': 'error', 'manifest': manifest.relative_to(run).as_posix(), 'reason': type(exc).__name__})
        coverage = {agent: {'executions': 0, 'generated': 0, 'gaps': 0} for agent in AGENTS}
        for receipt in receipts:
            agent = str(receipt.get('agent', '')).removesuffix('_agent')
            if agent in coverage:
                coverage[agent]['executions'] += 1
                coverage[agent]['generated'] += len(receipt.get('generated', []))
                coverage[agent]['gaps'] += len(receipt.get('gaps', []))
        report = {'schema': 'atr.artifact_coverage.v1', 'run_id': run.name, 'agents': coverage,
                  'executions': receipts, 'actuation_performed': False}
        _json(run / 'artifact_coverage.json', report)
        return report


def _worker_setup():
    os.environ['OMP_NUM_THREADS'] = '1'
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'
    os.nice(10)


class PreservationService:
    """One background process, coalesced per run; never wait in the experiment."""
    def __init__(self):
        self.pool = ProcessPoolExecutor(max_workers=1, mp_context=get_context('spawn'), initializer=_worker_setup)
        self.lock = threading.RLock()
        self.pending, self.dirty = set(), set()
        self.closed = False

    def offer(self, run):
        run = str(run)
        with self.lock:
            if self.closed:
                return
            if run in self.pending:
                self.dirty.add(run)
                return
            self.pending.add(run)
            future = self.pool.submit(preserve_run, run)
            future.add_done_callback(lambda task: self._done(run, task))

    def _done(self, run, task):
        try:
            task.result()
        except Exception:
            logging.getLogger(__name__).warning('Artifact preservation failed; original evidence retained')
        with self.lock:
            self.pending.discard(run)
            if run in self.dirty:
                self.dirty.discard(run)
                self.offer(run)

    def close(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    import argparse
    import time
    parser = argparse.ArgumentParser()
    parser.add_argument('run_dir')
    parser.add_argument('--watch-parent', type=int)
    args = parser.parse_args()
    while True:
        report = preserve_run(args.run_dir)
        print(json.dumps({k: v for k, v in report.items() if k != 'executions'}), flush=True)
        if not args.watch_parent:
            break
        time.sleep(15)
        try:
            os.kill(args.watch_parent, 0)
            if Path(f'/proc/{args.watch_parent}/stat').read_text().split(') ', 1)[1].startswith('Z '):
                break
        except (OSError, IndexError):
            break
