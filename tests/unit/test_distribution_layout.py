"""Target filesystem and positive distribution contracts; no app import."""
from pathlib import Path


def test_executable_project_is_contained_under_runtime():
    # This test is intentionally RED in the pre-move disposable checkout.
    here = Path(__file__).resolve()
    root = here.parents[3] if here.parents[2].name == 'runtime' else here.parents[2]
    assert sorted(p.name for p in root.iterdir() if p.is_file() and not p.name.startswith('.')) == ['README.md']
    assert (root / 'runtime/pyproject.toml').is_file()
    assert (root / 'runtime/LICENSE').is_file()
    assert (root / 'runtime/README.md').is_file()
    assert not (root / 'runtime/__init__.py').exists()
