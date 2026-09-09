"""Read-only Live FEM lookup never admits solver work or crosses loop identity."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.analysis_improvement import ImprovementStore


def client_at(root):
    from app.analysis_fem_routes import make_router
    app = FastAPI()
    app.include_router(make_router(lambda: root, lambda: None))
    return TestClient(app)


def test_lookup_does_not_create_store_or_start_jobs(tmp_path):
    client = client_at(tmp_path)
    assert client.get('/api/analysis/fem/jobs', params={'run_id': 'missing'}).json() == {'jobs': []}
    assert list(tmp_path.iterdir()) == []


def test_lookup_filters_loop_and_refreshes_completed_job_without_changing_bo(tmp_path):
    store = ImprovementStore(tmp_path/'r'/'runtime'/'analysis_improvement')
    for loop in (1, 2):
        store.submit({'job_kind':'fem','run_id':'r','loop_key':f'r:loop-{loop}',
                      'specimen_id':'s','experiment_curve':[{'displacement_mm':0,'force_N':0}],
                      'specimen_geometry':{'gauge_length_mm':30}})
    job = store.claim()
    client = client_at(tmp_path)
    params = {'run_id':'r','loop_key':'r:loop-1','specimen_id':'s'}
    first = client.get('/api/analysis/fem/jobs',params=params).json()['jobs']
    assert len(first)==1 and first[0]['status']=='running'
    store.finish(job['job_id'], {'status':'completed','attempts':[{'attempt_id':'a','curve':[{'displacement_mm':1,'force_N':2}]}]})
    second = client.get('/api/analysis/fem/jobs',params=params).json()['jobs']
    assert second[0]['attempts'][0]['curve'][0]['force_N']==2
    assert second[0]['status']=='completed'
    assert store.jobs()[1]['status']=='queued'
    assert client.get('/api/analysis/fem/jobs',params={**params,'specimen_id':'other'}).json()=={'jobs':[]}


def test_lookup_rejects_path_traversal_and_cancel_is_explicit(tmp_path):
    client = client_at(tmp_path)
    assert client.get('/api/analysis/fem/jobs',params={'run_id':'../outside'}).status_code==400
    store = ImprovementStore(tmp_path/'r'/'runtime'/'analysis_improvement')
    job=store.submit({'job_kind':'fem','run_id':'r','loop_key':'r:loop-1','specimen_id':'s'})
    client.get('/api/analysis/fem/jobs',params={'run_id':'r'})
    assert not store.cancel_requested(job['job_id'])
    result=client.post(f"/api/analysis/fem/jobs/{job['job_id']}/cancel",params={'run_id':'r'})
    assert result.status_code==200
    assert store.get(job['job_id'])['status']=='cancelled'


def test_field_metadata_omits_values_and_geometry(tmp_path,monkeypatch):
    from app import cae_fields_routes as routes
    from utils.calculix_fields import postprocess_fields
    from tests.unit.test_calculix_fields import TETRA_INP,TETRA_FRD
    root=tmp_path/'artifacts';root.mkdir()
    inp=root/'a.inp'; inp.write_text(TETRA_INP)
    frd=root/'a.frd'; frd.write_text(TETRA_FRD)
    field=postprocess_fields(inp,frd,root/'fields')
    monkeypatch.setattr(routes,'resolve_path',lambda _:tmp_path)
    app=FastAPI();app.include_router(routes.router)
    response=TestClient(app).get('/api/cae/fields/metadata',params={'path':field['field_asset_path']})
    assert response.status_code==200
    data=response.json()
    assert 'geometry' not in data
    assert data['frames'][0]['frame_index']==0
    assert 'values' not in data['frames'][0]['fields']['U']
    assert data['frames'][0]['fields']['U']['units']=='mm'


def test_running_and_cancelled_curve_uses_aligned_progress(tmp_path):
    store = ImprovementStore(tmp_path/'r'/'runtime'/'analysis_improvement')
    job = store.submit({'job_kind':'fem','run_id':'r', 'experiment_curve':[
        {'displacement_mm':3, 'force_N':1}]})
    store.claim()
    store.update_progress(job['job_id'], {'experiment_curve':[{'displacement_mm':0,'force_N':1}],
        'coordinate_convention':{'name':'contact_threshold'}, 'convergence':{'converged':False}})
    client = client_at(tmp_path)
    for status in ('running', 'cancelled'):
        if status == 'cancelled':
            store.finish(job['job_id'], {'status':'cancelled'})
        result = client.get('/api/analysis/fem/jobs',params={'run_id':'r'}).json()['jobs'][0]
        assert result['experiment_curve'][0]['displacement_mm']==0
        assert result['coordinate_convention']['name']=='contact_threshold'
        assert result['convergence']['converged'] is False


def test_historical_loop_query_and_exact_cancel_after_more_than_100_jobs(tmp_path):
    store = ImprovementStore(tmp_path/'r'/'runtime'/'analysis_improvement')
    oldest = store.submit({'job_kind':'fem','run_id':'r','loop_key':'r:loop-0','specimen_id':'s'})
    for loop in range(1, 103):
        store.submit({'job_kind':'fem','run_id':'r','loop_key':f'r:loop-{loop}','specimen_id':'s'})
    client=client_at(tmp_path)
    result=client.get('/api/analysis/fem/jobs',params={'run_id':'r','loop_key':'r:loop-0'}).json()
    assert [j['job_id'] for j in result['jobs']]==[oldest['job_id']]
    assert client.post(f"/api/analysis/fem/jobs/{oldest['job_id']}/cancel",params={'run_id':'r'}).status_code==200


def test_card_summary_and_event_feed_do_not_duplicate_raw_curves():
    from app.analysis_fem_routes import _public
    curve=[{'displacement_mm':i,'force_N':i} for i in range(3000)]
    job={'job_id':'j','status':'running','evidence':{'run_id':'r'},'result':{
        'progress':{'experiment_curve':curve,'phase':'fem_result'},
        'summary':{'comparison_curve':curve,'convergence':{'status':'not_assessed'}},
        'events':[{'phase':'fem_result','message':'review','experiment_curve':curve}]}}
    public=_public(job)
    assert len(public['experiment_curve'])<=2048
    assert 'experiment_curve' not in public['progress']
    assert 'comparison_curve' not in public['summary']
    assert 'experiment_curve' not in public['events'][0]
