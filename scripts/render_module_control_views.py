"""Render owner execution nodes and explicit outcome edges with the IDE projection."""
import json
from pathlib import Path
import subprocess

import yaml

from agents.design.structure import design_implementation_structure
from agents.orchestrator_structure import orchestrator_implementation_structure


def render(module_id: str, root: Path) -> str:
    payload = yaml.safe_load((root / 'graphs/modules' / module_id / 'module.yaml').read_text())
    renderer = root / 'web/static/module_control_view.js'
    structures = {'design': design_implementation_structure, 'orchestrator': orchestrator_implementation_structure}
    packet = {'module': payload['module'], 'catalog': {'implementation_structure': structures[module_id]()}}
    script = 'const fs=require("node:fs");const view=require(process.argv[1]);const p=JSON.parse(fs.readFileSync(0,"utf8"));process.stdout.write(view.renderSvg(p.module,{theme:"document",catalog:p.catalog}));'
    return subprocess.run(['node', '-e', script, str(renderer)], input=json.dumps(packet),
                          capture_output=True, text=True, check=True).stdout


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    for module_id in ('design', 'orchestrator'):
        target = root / 'docs/agents/assets/figures' / f'{module_id}_control_areas.svg'
        target.write_text(render(module_id, root), encoding='utf-8')
        print(target.relative_to(root))
