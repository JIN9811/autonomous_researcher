"""Positive per-file setuptools contract for public code and runtime resources.

Selection is reviewed data, never filesystem discovery. Optional Piper models
and standalone delivery tools belong only to the explicit source distribution.
"""
import json
from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.egg_info import egg_info
from setuptools._distutils.filelist import FileList

ROOT = Path(__file__).resolve().parent
CONTRACT = json.loads((ROOT / 'distribution-files.json').read_text())
for role in ('wheel', 'bound_resources', 'sdist'):
    names = CONTRACT[role]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate distribution selection')
    for name in names:
        path = ROOT / name
        if (not name or name.startswith('/') or any(c in name for c in ('*', '\\', ':'))
                or '..' in Path(name).parts or not path.is_file() or path.is_symlink()
                or not path.resolve().is_relative_to(ROOT)):
            raise ValueError('Unsafe or unavailable distribution input: ' + name)

OUTPUTS = {name: name for name in CONTRACT['wheel']}
OUTPUTS.update({'_autonomous_researcher_resources/' + name: name
                for name in CONTRACT['bound_resources']})


class PublicBuild(build_py):
    def find_package_modules(self, package, package_dir):
        return [row for row in super().find_package_modules(package, package_dir)
                if Path(row[2]).as_posix() in CONTRACT['wheel']]

    def get_source_files(self):
        return list(CONTRACT['wheel']) + list(CONTRACT['bound_resources'])

    def get_outputs(self, include_bytecode=1):
        return [str(Path(self.build_lib) / name) for name in OUTPUTS]

    def run(self):
        if self.editable_mode:
            return
        destination = Path(self.build_lib)
        if destination.exists():
            extra = {p.relative_to(destination).as_posix() for p in destination.rglob('*')
                     if p.is_file()} - set(OUTPUTS)
            if extra:
                raise ValueError('Unapproved stale build files: ' + repr(sorted(extra)))
        for name, source in OUTPUTS.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / source, target)


class PublicMetadata(egg_info):
    def find_sources(self):
        # Never use cached SOURCES.txt or recursive VCS/resource discovery.
        metadata = ['PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'requires.txt', 'top_level.txt']
        self.filelist = FileList()
        self.filelist.files = sorted(CONTRACT['sdist'] + [str(Path(self.egg_info) / p) for p in metadata])
        Path(self.egg_info, 'SOURCES.txt').write_text('\n'.join(self.filelist.files) + '\n')


setup(packages=CONTRACT['packages'], include_package_data=False,
      cmdclass={'build_py': PublicBuild, 'egg_info': PublicMetadata})
