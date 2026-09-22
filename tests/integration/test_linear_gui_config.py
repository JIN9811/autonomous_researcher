from fastapi.testclient import TestClient

import app.main as app
import utils.lerobot_rollout_profile as rollout
import utils.manipulation_profile as manipulation


def test_both_gui_apis_persist_linear_rates_without_starting_devices(tmp_path, monkeypatch):
    for module, name, filename in (
        (rollout, 'LEROBOT_ROLLOUT_PROFILE_PATH', 'rollout.json'),
        (manipulation, 'MANIPULATION_AGENT_PROFILE_PATH', 'agent.json'),
    ):
        monkeypatch.setattr(module, name, tmp_path/filename)
        monkeypatch.setattr(app, name, tmp_path/filename)
    client = TestClient(app.app)
    for endpoint, hz in (('/api/lerobot/rollout/config', 60), ('/api/lerobot/manipulation-agent/config', 100)):
        response = client.post(endpoint, json={'rollout_linear_enabled':True, 'rollout_linear_hz':hz})
        assert response.status_code == 200
        saved = client.get(endpoint).json()['profile']
        assert saved['rollout_linear_enabled'] is True
        assert saved['rollout_linear_hz'] == hz
    assert client.post('/api/lerobot/rollout/config', json={'rollout_linear_hz':101}).status_code == 422
    assert client.get('/api/lerobot/rollout/config').json()['profile']['rollout_linear_hz'] == 60
