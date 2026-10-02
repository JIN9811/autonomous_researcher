"""Entrypoints finalize source and storage independently; never launch a server."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.unit.test_runtime_worker_origins import bound_layout


def test_serve_uses_runtime_configs_cwd_and_absolute_child_metadata(tmp_path, monkeypatch):
    from app import serve
    from utils import runtime_paths
    paths, config, binding = bound_layout(tmp_path)
    monkeypatch.setattr(runtime_paths, '_current', None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('ATR_LAYOUT_CONFIG', str(config.relative_to(tmp_path)))
    monkeypatch.setenv('ATR_PATH_BINDINGS', str(binding.relative_to(tmp_path)))
    opened, started = [], []
    monkeypatch.setattr(serve, 'load_dotenv', lambda file, **kw: opened.append(file))
    def configs(file):
        assert file == paths.runtime_root / 'configs'
        return {'system': {'server': {'reload': True, 'workers': 3, 'port': 7891}}}
    monkeypatch.setattr(serve, 'load_all_configs', configs)
    monkeypatch.setattr(serve.uvicorn, 'run', lambda target, **kw: started.append((target, kw, Path.cwd(), dict(os.environ))))
    serve.main()
    assert opened == [paths.repository_root / '.env']
    assert started[0][:3] == ('app.main:app', dict(host='127.0.0.1', port=7891, reload=True, workers=1), paths.runtime_root)
    assert started[0][3]['ATR_LAYOUT_CONFIG'] == str(config)
    assert started[0][3]['ATR_PATH_BINDINGS'] == str(binding)
    assert runtime_paths.current_paths() == paths


def test_cli_passes_one_finalized_binding(tmp_path, monkeypatch):
    from app import cli
    from utils import runtime_paths
    paths, config, binding = bound_layout(tmp_path)
    monkeypatch.setattr(runtime_paths, '_current', None)
    monkeypatch.setenv('ATR_LAYOUT_CONFIG', str(config))
    monkeypatch.setenv('ATR_PATH_BINDINGS', str(binding))
    monkeypatch.setattr('sys.argv', ['atr', '--wait-seconds', '0'])
    calls = []
    async def start(**kwargs): return {'ok': True}
    def load(*, paths):
        calls.append(paths)
        return SimpleNamespace(start=start, snapshot=lambda: {'state': 'fixture'})
    monkeypatch.setattr(cli, 'load_runtime', load)
    asyncio.run(cli._async_main())
    assert calls == [paths]
    assert runtime_paths.current_paths() is calls[0]


@pytest.mark.asyncio
async def test_hot_reload_rejects_structural_source_rebinding(tmp_path, monkeypatch):
    from app import safe_hot_reload
    from utils import runtime_paths
    paths, _, _ = bound_layout(tmp_path)
    monkeypatch.setattr(runtime_paths, '_current', paths)
    controller = SimpleNamespace(_deps=SimpleNamespace(paths=paths))
    with pytest.raises(ValueError, match='restart'):
        await safe_hot_reload.reload_equipment_support(controller)


@pytest.mark.asyncio
async def test_hot_reload_validation_keeps_loaded_runtime_cwd(tmp_path, monkeypatch):
    from dataclasses import replace
    from app import safe_hot_reload
    from utils.runtime_paths import current_paths
    paths = replace(current_paths(), repository_root=tmp_path / 'outer')
    controller = SimpleNamespace(_deps=SimpleNamespace(paths=paths))
    monkeypatch.setattr(safe_hot_reload, 'assert_printer_wait_inactive', lambda controller: None)
    monkeypatch.setattr(safe_hot_reload, 'stage_printer_wait_timing', lambda path: (None, None))
    captured = []
    def validate(argv, **options):
        captured.append((argv, options))
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr('subprocess.run', validate)
    with pytest.raises(ValueError, match='validation failed'):
        await safe_hot_reload.reload_printer_wait_support(controller)
    assert captured[0][1]['cwd'] == paths.runtime_root
    assert captured[0][1]['timeout'] == 60
    assert captured[0][0][1:3] == ['-m', 'pytest']
