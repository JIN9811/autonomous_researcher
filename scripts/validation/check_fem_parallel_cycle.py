"""Replay a copied native deck only until two virtual software loops are verified."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import os
import yaml
from dataclasses import replace
from uuid import uuid4
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from device_bridges.calculix_bridge import CalculiXBridge, CalculiXBridgeConfig
from scripts.validation.run_analysis_fem_cycle import write_json


def main(run):
    saved=json.loads((run/'002-cae-run_static_analysis.result.json').read_text())
    source=Path(saved['artifacts']['inp_path'])
    output=run/f'parallel-native-proof-{uuid4().hex[:8]}'; output.mkdir(exist_ok=False)
    deck=output/'model.inp'; shutil.copyfile(source,deck)
    cancel=threading.Event(); started=threading.Event(); holder={}
    def progress(event):
        if event.get('status')=='running' and event.get('pid'):
            holder['pid']=event['pid']; started.set()
    def native():
        config=CalculiXBridgeConfig.from_devices_config(yaml.safe_load((ROOT/'configs/devices.yaml').read_text()),repo_root=ROOT)
        holder['result']=CalculiXBridge(replace(config,artifact_dir=output)).solve({
            'inp_path':str(deck),'runtime_solver_enabled':True,
            'computation_limits':{'timeout_s':None,'threads':4,'equation_solver_threads':1},
            '_cancel_event':cancel,'_progress_callback':progress})
    worker=threading.Thread(target=native); worker.start()
    try:
        if not started.wait(30):
            raise RuntimeError('Native solver did not start')
        env={**os.environ,'ATR_PARALLEL_NATIVE_PID':str(holder['pid'])}
        command=[sys.executable,'-m','pytest','tests/integration/test_analysis_parallel_closed_loop.py',
                 '-q','-s','--tb=short']
        before=datetime.now(timezone.utc).isoformat()
        result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True)
        (output/'pytest.log').write_text(result.stdout+result.stderr)
        receipt={'test_exit_code':result.returncode,'started_utc':before,
                 'finished_utc':datetime.now(timezone.utc).isoformat(),'native_pid':holder['pid'],
                 'physical_devices_used':False,'purpose':'Two software loops during actual native FEM; copied deck cancelled after test'}
        for line in result.stdout.splitlines():
            if line.startswith('{"parallel_closed_loop_receipt"'):
                source_receipt=Path(json.loads(line)['parallel_closed_loop_receipt'])
                shutil.copyfile(source_receipt,output/'parallel_closed_loop_receipt.json')
        write_json(output/'verification.json',receipt)
        print(result.stdout,flush=True)
    finally:
        cancel.set(); worker.join()
        write_json(output/'native_result.json',holder.get('result',{}))
    return result.returncode


if __name__=='__main__':
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
