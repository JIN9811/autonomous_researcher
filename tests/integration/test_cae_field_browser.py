"""Isolated browser validation: serves only local files and literal test fields."""
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest


def test_browser_renders_saved_fields_without_execution_calls():
    playwright = pytest.importorskip('playwright.sync_api')
    root = Path(__file__).resolve().parents[2]
    data = {'schema': 'cae_fields.v1', 'status': 'complete', 'source_hashes': {'fixture': 'literal-tetra-not-physical-evidence'},
            'geometry': {'node_ids': [10,20,30,40], 'points': [[0,0,0],[1,0,0],[0,1,0],[0,0,1]],
                         'elements': [{'id': 7, 'type': 'C3D4', 'connectivity': [10,20,30,40]}],
                         'surface': {'triangles': [[10,30,20],[10,20,40],[20,30,40],[30,10,40]]}},
            'frames': [{'time': 1, 'fields': {
                'U': {'values': [[0,0,0],[0,0,0],[0,0,0],[0,0,-0.2]], 'components': ['x','y','z'], 'units': 'mm', 'association':'point'},
                'S_MISES': {'values': [[0],[20],[50],[100]], 'components': ['Mises'], 'units': 'MPa', 'association':'point','averaging':'fixture'}}}]}
    requests, errors = [], []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1440, 'height': 1150})
        page.on('pageerror', lambda error: errors.append(str(error)))
        def serve(route):
            request = route.request
            requests.append((request.method,request.url))
            path = urlparse(request.url).path
            if path == '/api/cae/fields':
                route.fulfill(content_type='application/json', body=json.dumps(data))
            elif path == '/cae/results':
                route.fulfill(content_type='text/html', body=(root/'web/templates/cae_fields.html').read_text())
            elif path.startswith('/static/'):
                file = root/'web'/path.lstrip('/')
                route.fulfill(path=str(file), content_type='text/css' if file.suffix=='.css' else 'text/javascript')
            else:
                route.fulfill(status=404,body='not found')
        page.route('http://atr.local/**',serve)
        page.goto('http://atr.local/cae/results?path=fixture.fields.json')
        page.wait_for_function("document.getElementById('field-status').textContent.includes('Showing saved') || document.getElementById('field-status').className === 'error'", timeout=30000)
        assert 'Showing saved' in page.locator('#field-status').inner_text(), (page.locator('#field-status').inner_text(), errors)
        assert page.locator('#baseline-meta').inner_text() == '4 nodes · 1 elements'
        assert page.locator('#field-max').input_value() == '100'
        page.check('#field-edges')
        page.fill('#field-scale','0')
        page.locator('#field-scale').dispatch_event('change')
        page.screenshot(path='/tmp/atr-cae-field-viewer-fixture.png', full_page=True)
        assert errors == []
        assert all(method == 'GET' for method,_ in requests)
        assert not any('/run' in url or '/equipment' in url for _,url in requests)
        browser.close()
