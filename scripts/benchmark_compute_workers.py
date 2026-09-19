"""Isolated loopback benchmark; no app/controller, bridges, LLM or device calls.

Run with the project Python: -m scripts.benchmark_compute_workers
Artifacts are written only into a new temporary directory. Nothing is printed.
"""
import argparse
import asyncio
import concurrent.futures
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen


def serve(workers, root, listener):
    import uvicorn
    from fastapi import FastAPI
    from utils.compute_pool import configure_compute_pool, compute_async, compute_status
    from utils.compute_jobs import execute
    configure_compute_pool(workers)
    app = FastAPI()

    @app.get('/health')
    async def health():
        return compute_status()

    @app.post('/calculate/{index}')
    async def calculate(index: int):
        if not 0 <= index < 3:
            return {'ok': False}
        payload = {'run_id': 'isolated-cpu-benchmark', 'specimen_id': f'fixture-{index}',
            'geometry_type': 'gyroid', 'specimen_size_mm': [30, 30, 30],
            'cell_size_mm': 6., 'wall_thickness_mm': .8, 'tpms_resolution': 72,
            'output_dir': str(root / str(index))}
        result = (await compute_async('geometry.generate', payload) if workers
                  else execute('geometry.generate', payload))
        return {'ok': result['ok'], 'report': result['geometry_report']}

    config = uvicorn.Config(app, host='127.0.0.1', log_level='error', access_log=False)
    uvicorn.Server(config).run(sockets=[listener])


def measure(workers, root):
    import psutil
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(16)
    port = listener.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    process = subprocess.Popen([sys.executable, '-m', 'scripts.benchmark_compute_workers',
        '--serve', str(workers), '--root', str(root), '--fd', str(listener.fileno())],
        pass_fds=[listener.fileno()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    listener.close()
    def request(path, post=False):
        with urlopen(url + path, data=b'' if post else None, timeout=120) as response:
            return json.load(response)
    def cpu():
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        return sum(p.cpu_times().user + p.cpu_times().system for p in [parent, *children]), children
    executor = concurrent.futures.ThreadPoolExecutor(4)
    try:
        for _ in range(100):
            try:
                request('/health')
                break
            except OSError:
                time.sleep(.05)
        # Warm all three interpreters before the measured requests.
        list(executor.map(lambda i: request(f'/calculate/{i}', True), range(3)))
        latencies, done = [], threading.Event()
        def probe():
            while not done.is_set():
                start = time.monotonic()
                request('/health')
                latencies.append(time.monotonic() - start)
                done.wait(.02)
        probe_task = executor.submit(probe)
        before, _ = cpu()
        started = time.monotonic()
        results = list(executor.map(lambda i: request(f'/calculate/{i}', True), range(3)))
        wall = time.monotonic() - started
        after, children = cpu()
        done.set()
        probe_task.result()
        assert all(r['ok'] for r in results)
        return {'workers': workers, 'wall_s': round(wall, 3), 'cpu_s': round(after-before, 3),
                'cpu_cores_average': round((after-before)/wall, 2),
                'health_max_ms': round(max(latencies)*1000, 1), 'health_samples': len(latencies),
                'worker_pids': request('/health')['pids'],
                'worker_rss_mib': round(sum(p.memory_info().rss for p in children)/1024**2, 1)}
    finally:
        executor.shutdown(wait=True)
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', type=int)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--fd', type=int)
    args = parser.parse_args()
    if args.serve is not None:
        serve(args.serve, args.root, socket.socket(fileno=args.fd))
    else:
        root = Path(tempfile.mkdtemp(prefix='ax4lab-compute-bench-'))
        print(json.dumps({'artifacts': str(root), 'results': [measure(n, root/str(n)) for n in (0, 3)]}, indent=2))
