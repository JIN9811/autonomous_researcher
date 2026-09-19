import os
from concurrent.futures import ThreadPoolExecutor

import pytest
import yaml

from utils.yaml_cache import read_yaml, _parse


def test_cache_reuses_parse_but_returns_independent_values(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('list: [1, 2]\n')
    _parse.cache_clear()
    first = read_yaml(path)
    first['list'].append(99)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: read_yaml(path), range(20)))
    assert all(x == {'list': [1, 2]} for x in results)
    assert _parse.cache_info().misses == 1
    assert all(x is not first for x in results)


def test_changes_even_with_same_size_and_mtime_and_atomic_replace(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('value: 1\n')
    original = path.stat()
    assert read_yaml(path) == {'value': 1}
    path.write_text('value: 2\n')
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert read_yaml(path) == {'value': 2}
    new = tmp_path / 'replacement'
    new.write_text('value: 3\n')
    new.replace(path)
    assert read_yaml(path) == {'value': 3}
    path.write_text('value: [')
    with pytest.raises(yaml.YAMLError):
        read_yaml(path)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        read_yaml(path)
    path.write_text('value: 4\n')
    assert read_yaml(path) == {'value': 4}


def test_equal_filenames_do_not_cross_contaminate_and_cache_is_bounded(tmp_path):
    a = tmp_path / 'a.yaml'; b = tmp_path / 'b.yaml'
    _parse.cache_clear()
    for i in range(140):
        a.write_text(f'value: {i}\n')
        assert read_yaml(a) == {'value': i}
    b.write_text('value: other\n')
    assert read_yaml(b) == {'value': 'other'}
    assert read_yaml(a) == {'value': 139}
    assert _parse.cache_info().currsize <= 128
