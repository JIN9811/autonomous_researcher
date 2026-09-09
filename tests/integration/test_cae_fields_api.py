"""Read-only router tests without importing the running application's controller."""
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app import cae_fields_routes as routes
from utils.calculix_fields import postprocess_fields
from utils.cae_field_view import render_png


def test_field_api_rejects_malformed_paths_and_busy_native_work(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, 'resolve_path', lambda _: tmp_path)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    artifact = tmp_path / 'artifacts' / 'invalid.json'
    artifact.parent.mkdir()
    artifact.write_text('[]')
    assert client.get('/api/cae/fields', params={'path':str(artifact)}).status_code == 400
    assert client.get('/api/cae/fields', params={'path':'/etc/passwd'}).status_code == 400
    assert routes._POSTPROCESS_ADMISSION.acquire(blocking=False)
    try:
        response = client.get('/api/cae/fields/render', params={'path':str(artifact),'field':'S'})
        assert response.status_code == 429
    finally:
        routes._POSTPROCESS_ADMISSION.release()
    response = client.get('/api/cae/fields/render', params={'path':str(artifact),'field':'S'})
    assert response.status_code == 400
    assert routes._POSTPROCESS_ADMISSION.acquire(blocking=False)
    routes._POSTPROCESS_ADMISSION.release()


def test_archived_real_frd_export_has_4k_pixels_and_300dpi(tmp_path):
    """Optional externally archived CalculiX tetra, not project physical proof."""
    from io import BytesIO
    from PIL import Image
    inp, frd = Path('/tmp/atr-real-tet4.inp'), Path('/tmp/atr-real-tet4.frd')
    if not inp.exists() or not frd.exists():
        pytest.skip('Optional archived public FRD not available locally')
    data = postprocess_fields(inp, frd, tmp_path / 'fields')
    assert data['status'] == 'complete'
    assert data['frames'][0]['fields']['S_MISES']['values'][0] == pytest.approx([57.1429])
    png = render_png(data, frame=0, field='S_MISES', edges=True, scale=1)
    image = Image.open(BytesIO(png))
    assert image.size == (3840, 2160)
    assert image.info['dpi'][0] == pytest.approx(300, abs=.1)
    Path('/tmp/atr-analysis-real-frd-4k.png').write_bytes(png)
