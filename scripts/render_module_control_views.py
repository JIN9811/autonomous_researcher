"""Render owner execution nodes and explicit outcome edges with the IDE projection."""
import json
from pathlib import Path
import subprocess

import yaml

from agents.design.structure import design_implementation_structure
from agents.core.orchestrator.structure import orchestrator_implementation_structure
from agents.specimen.structure import specimen_implementation_structure
from agents.vision.structure import vision_implementation_structure
from agents.manipulation.structure import manipulation_implementation_structure
from agents.equipment.structure import equipment_implementation_structure
from agents.analysis.structure import analysis_implementation_structure
from agents.bo.structure import bo_implementation_structure
from agents.core.knowledge.structure import knowledge_implementation_structure
from agents.core.guardian.structure import guardian_implementation_structure


def render(module_id: str, root: Path) -> str:
    payload = yaml.safe_load((root / 'graphs/modules' / module_id / 'module.yaml').read_text())
    renderer = root / 'web/static/module_control_view.js'
    structures = {'design': design_implementation_structure, 'orchestrator': orchestrator_implementation_structure,
                  'specimen': specimen_implementation_structure, 'vision': vision_implementation_structure,
                  'manipulation': manipulation_implementation_structure,
                  'equipment': equipment_implementation_structure,
                  'analysis': analysis_implementation_structure,
                  'bo': bo_implementation_structure,
                  'knowledge': knowledge_implementation_structure,
                  'guardian': guardian_implementation_structure}
    packet = {'module': payload['module'], 'catalog': {'implementation_structure': structures[module_id]()}}
    script = 'const fs=require("node:fs");const view=require(process.argv[1]);const p=JSON.parse(fs.readFileSync(0,"utf8"));process.stdout.write(view.renderSvg(p.module,{theme:"document",catalog:p.catalog}));'
    return subprocess.run(['node', '-e', script, str(renderer)], input=json.dumps(packet),
                          capture_output=True, text=True, check=True).stdout


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('modules', nargs='*', choices=['design', 'orchestrator', 'specimen', 'vision', 'manipulation', 'equipment', 'analysis', 'bo', 'knowledge', 'guardian'])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for module_id in args.modules or ('design', 'orchestrator', 'specimen', 'vision', 'manipulation', 'equipment', 'analysis', 'bo', 'knowledge', 'guardian'):
        target = root / 'docs/agents/assets/figures' / f'{module_id}_control_areas.svg'
        target.write_text(render(module_id, root), encoding='utf-8')
        print(target.relative_to(root))
