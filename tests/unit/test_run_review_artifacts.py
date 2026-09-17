import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from app.run_review_routes import review_router
from utils.run_review_artifacts import artifact_index, artifact_path


@pytest.fixture
def archive(tmp_path):
    run=tmp_path / 'run'
    (run / 'review').mkdir(parents=True)
    (run / 'review' / 'index.json').write_text(json.dumps({'run_id':'run','points':[]}))
    for name, data in [('workspace/bo/data.csv',b'x,y\n1,2\n'),('specimens/cube/a.stl',b'solid test'),
                       ('workspace/bo/chart.svg',b'<svg/>'),('workspace/bo/report.html',b'<script>fetch("/api/run/start")</script>'),
                       ('recovery/checkpoint.json',b'private'),('.env',b'private')]:
        path=run / name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
    return tmp_path


def test_index_preserves_files_and_excludes_internal_recovery_and_snapshots(archive):
    before={str(p):p.read_bytes() for p in archive.rglob('*') if p.is_file()}
    index=artifact_index(archive,'run')
    assert index['read_only'] and index['scope']=='session_files'
    assert len(index['artifacts'])==4
    csv=next(f for f in index['artifacts'] if f['name']=='data.csv')
    assert csv['agent']=='bo' and csv['preview_kind']=='text'
    assert csv['url']=='/api/review/run/files/workspace/bo/data.csv'
    assert before=={str(p):p.read_bytes() for p in archive.rglob('*') if p.is_file()}


@pytest.mark.parametrize('relative',['../outside.txt','/etc/passwd','workspace/../../outside.txt','workspace\\file','recovery/checkpoint.json','.env','review/index.json','missing.csv'])
def test_path_boundary(archive,relative):
    with pytest.raises(ValueError): artifact_path(archive,'run',relative)


def test_symlinks_and_cross_run_aliases_rejected(archive):
    (archive / 'other').mkdir()
    secret=archive / 'other' / 'private.csv';secret.write_text('private')
    (archive / 'run' / 'escape.csv').symlink_to(secret)
    (archive / 'run' / 'escape').symlink_to(secret.parent,target_is_directory=True)
    for path in ['escape.csv','escape/private.csv']:
        with pytest.raises(ValueError):artifact_path(archive,'run',path)
    assert len(artifact_index(archive,'run')['artifacts'])==4


def test_read_only_file_routes_and_sandboxed_content(archive):
    app=FastAPI();app.include_router(review_router(archive,Jinja2Templates(directory='web/templates')))
    with TestClient(app) as client:
        listing=client.get('/api/review/run/artifacts').json()
        csv=next(f for f in listing['artifacts'] if f['name']=='data.csv')
        response=client.get(csv['url'])
        assert response.content==b'x,y\n1,2\n'
        assert response.headers['content-security-policy'].startswith('sandbox;')
        assert response.headers['x-content-type-options']=='nosniff'
        assert 'attachment' in client.get(csv['download_url']).headers['content-disposition']
        assert client.get('/api/review/run/files/workspace/bo/report.html').headers['content-type'].startswith('text/plain')
        for method in ['post','put','patch','delete']:
            assert getattr(client,method)(csv['url']).status_code==405
        assert client.get('/api/review/run/files/recovery/checkpoint.json').status_code==404
        assert client.get('/api/review/unknown/artifacts').status_code==404


def test_execution_ownership_and_original_reference(archive):
    relative='runtime/loops/loop-000002/analysis_agent/attempt-000003'
    directory=archive / 'run' / relative; (directory / 'files').mkdir(parents=True)
    (directory / 'files' / 'curve.csv').write_text('data')
    (directory / 'manifest.json').write_text(json.dumps({'schema':'atr.agent_artifact_execution.v1',
        'manifest_path':relative+'/manifest.json','loop_index':1,'agent':'analysis_agent','attempt_index':3,
        'archive_status':'complete','artifacts':[{'status':'copied','path':relative+'/files/curve.csv',
        'source_path':'/external/curve.csv','captured_at':'2026-09-18T00:00:00Z'}]}))
    curve=next(f for f in artifact_index(archive,'run')['artifacts'] if f['name']=='curve.csv')
    assert curve['loop_index']==1 and curve['attempt_index']==3 and curve['agent']=='analysis_agent'
    assert '/external/curve.csv' in curve['aliases']
