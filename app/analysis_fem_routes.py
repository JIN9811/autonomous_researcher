"""Analysis-owned FEM read model. Viewing never creates or resumes a worker."""
import json
from pathlib import Path
import re
import sqlite3

from fastapi import APIRouter, HTTPException


def _store_path(root, run_id):
    if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}', run_id):
        raise HTTPException(400, 'Invalid run ID')
    root = Path(root).resolve()
    path = (root / run_id / 'runtime' / 'analysis_improvement' / 'improvement.sqlite3').resolve()
    if not path.is_relative_to(root):
        raise HTTPException(400, 'Run path outside artifact root')
    return path


def _read_jobs(path, *, run_id, loop_key=None, specimen_id=None, job_id=None):
    if not path.is_file():
        return []
    try:
        with sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=2) as db:
            predicates = ["json_extract(body,'$.job_kind') = 'fem'", "json_extract(body,'$.run_id') = ?"]
            params = [run_id]
            for key, value in (('loop_key', loop_key), ('specimen_id', specimen_id)):
                if value is not None:
                    predicates.append(f"json_extract(body,'$.{key}') = ?")
                    params.append(value)
            if job_id is not None:
                predicates.append('id = ?')
                params.append(job_id)
            query = 'SELECT id,body,status,result FROM jobs WHERE ' + ' AND '.join(predicates)
            return [{'job_id': r[0], 'evidence': json.loads(r[1]), 'status': r[2], 'result': json.loads(r[3])}
                    for r in db.execute(query + ' ORDER BY rowid DESC LIMIT 100', params)]
    except (sqlite3.Error, ValueError) as exc:
        raise HTTPException(503, 'Analysis job archive temporarily unavailable') from exc


def _curve(points, limit=2048):
    if not isinstance(points, list):
        return []
    if len(points) <= limit:
        return points
    selected = {round(i * (len(points)-1)/(limit-3)) for i in range(limit-2)}
    selected.update((min(range(len(points)), key=lambda i: points[i].get('force_N',0)),
                     max(range(len(points)), key=lambda i: points[i].get('force_N',0))))
    return [points[i] for i in sorted(selected)]


def _public(job):
    evidence, result = job['evidence'], job['result']
    progress = result.get('progress', {})
    keys = ('attempt_id', 'mesh_size_mm', 'mesh_quality', 'comparison', 'field_asset_path',
            'solver_status', 'endpoint_reached', 'convergence', 'failure_code', 'coordinate_convention')
    attempts = [{**{k: a[k] for k in keys if k in a}, 'curve': _curve(a.get('curve', []))}
                for a in result.get('attempts', []) if isinstance(a, dict)]
    def summary(value):
        return {k:v for k,v in value.items() if k != 'comparison_curve'} if isinstance(value,dict) else value
    public_progress = {k:v for k,v in progress.items() if k not in {'experiment_curve','summary'}}
    events = [{k:e[k] for k in ('phase','message','decision','at') if k in e}
              for e in result.get('events',[]) if isinstance(e,dict)]
    return {'job_id': job['job_id'], 'status': job['status'],
            **{k: evidence.get(k) for k in ('run_id','loop_key','specimen_id','specimen_geometry')},
            'experiment_curve': _curve(result.get('experiment_curve', progress.get('experiment_curve', evidence.get('experiment_curve', [])))),
            'coordinate_convention': result.get('coordinate_convention', progress.get('coordinate_convention', evidence.get('coordinate_convention'))),
            'progress': public_progress, 'events': events,
            'attempts': attempts, 'summary': summary(result.get('summary', progress.get('summary',''))),
            'convergence': result.get('convergence', progress.get('convergence', {})), 'reason': result.get('reason')}


def make_router(root_provider, service_provider):
    router = APIRouter()

    @router.get('/api/analysis/fem/jobs')
    def jobs(run_id: str, loop_key: str | None = None, specimen_id: str | None = None):
        path = _store_path(root_provider(), run_id)
        rows = _read_jobs(path, run_id=run_id, loop_key=loop_key, specimen_id=specimen_id)
        matching = [j for j in rows if j['evidence'].get('job_kind') == 'fem'
                    and j['evidence'].get('run_id') == run_id
                    and (loop_key is None or j['evidence'].get('loop_key') == loop_key)
                    and (specimen_id is None or j['evidence'].get('specimen_id') == specimen_id)]
        return {'jobs': [_public(j) for j in matching]}

    @router.post('/api/analysis/fem/jobs/{job_id}/cancel')
    def cancel(job_id: str, run_id: str):
        path = _store_path(root_provider(), run_id)
        job = next((j for j in _read_jobs(path, run_id=run_id, job_id=job_id) if j['job_id'] == job_id and
                    j['evidence'].get('job_kind') == 'fem' and j['evidence'].get('run_id') == run_id), None)
        if job is None:
            raise HTTPException(404, 'FEM job not found')
        service = service_provider()
        if service is not None and run_id in service._stores:
            requested = service.request_cancel(run_id, job_id)
        else:
            # Explicit operator write, unlike GET. A remote owning worker observes it.
            from agents.analysis_improvement import ImprovementStore
            requested = ImprovementStore(path.parent).request_cancel(job_id)
        return {'job_id': job_id, 'cancel_requested': requested}

    return router
