"""Review saved completed FEM evidence without re-executing a solver or device."""
import asyncio
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.validation.run_analysis_fem_cycle import build_context, Journal, write_json
from agents.analysis_decisions import decide, compact_evidence


async def main(run):
    events=[json.loads(line) for line in (run/'progress.jsonl').open()]
    event=next(e for e in reversed(events) if e.get('kind')=='decision_requested' and e.get('phase')=='fem_result')
    info=event['evidence']
    output=run/'result-review'; output.mkdir(exist_ok=False)
    journal=Journal(output)
    ctx,profile=build_context(ROOT/'configs',output,journal)
    start=time.monotonic()
    decision=await decide(ctx,'fem_result',info,{'conclude':None,'hold':None},background=True)
    attempts=info['attempts']
    for attempt in attempts:
        attempt['field_summary']=compact_evidence(attempt.get('field_summary',{}))
    result={'status':'completed' if any(a.get('endpoint_reached') for a in attempts) else 'partial',
            'attempts':attempts,'summary':info['summary'],'experiment_curve':info['experiment_curve'],
            'coordinate_convention':info['coordinate_convention'],
            'convergence':info['summary']['convergence'],'decisions':[decision],
            'review_elapsed_s':time.monotonic()-start,
            'review_scope':'Saved completed native receipts; no native replay; convergence not newly tested'}
    write_json(output/'result.json',result)
    write_json(output/'backend_profile.json',profile)
    # Preserve the original failed LLM receipt and separate corrected review.
    for name in ('evidence.json','resources_summary.json','run_metadata.json'):
        write_json(output/name,json.loads((run/name).read_text()))
    print(json.dumps({'output':str(output),'status':result['status'],'decision':decision,'review_elapsed_s':result['review_elapsed_s']}))


if __name__=='__main__':
    asyncio.run(main(Path(sys.argv[1]).resolve()))
