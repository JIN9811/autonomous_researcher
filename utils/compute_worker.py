"""Private JSON pipe server for one CPU worker; no application bootstrap."""
import contextlib
import json
import sys

from utils.compute_jobs import execute
from utils.compute_pool import JOBS, MAX_MESSAGE


def main():
    while True:
        line = sys.stdin.buffer.readline(MAX_MESSAGE + 1)
        if not line:
            return
        if len(line) > MAX_MESSAGE or not line.endswith(b'\n'):
            return
        try:
            request = json.loads(line)
            if request['job'] not in JOBS:
                raise ValueError('CPU job not allowed')
            with contextlib.redirect_stdout(sys.stderr):
                result = execute(request['job'], request['payload'])
            response = {'ok': True, 'result': result}
        except Exception as exc:
            response = {'ok': False, 'error': {'type': type(exc).__name__, 'message': str(exc),
                        'failure_code': getattr(exc, 'failure_code', None), 'details': getattr(exc, 'details', None)}}
        try:
            encoded = json.dumps(response, allow_nan=False).encode() + b'\n'
        except (ValueError, TypeError):
            encoded = b'{"ok":false,"error":{"type":"ValueError","message":"CPU result is not finite JSON"}}\n'
        if len(encoded) > MAX_MESSAGE:
            return
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
