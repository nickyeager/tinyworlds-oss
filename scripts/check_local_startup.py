#!/usr/bin/env python3
"""Exercise the installed local launcher against real HTTP services, then stop it.

Run in a disposable checkout after setup. This creates a local SQLite database
and Next development output. It never submits a generation job or signs in.
"""
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def free_ports():
    with socket.socket() as first, socket.socket() as second:
        first.bind(('127.0.0.1', 0))
        second.bind(('127.0.0.1', 0))
        return first.getsockname()[1], second.getsockname()[1]


def main():
    api_port, web_port = free_ports()
    output = ROOT / 'data/local-startup-check.log'
    output.parent.mkdir(exist_ok=True)
    with output.open('w') as log:
        process = subprocess.Popen([str(ROOT / '.venv/bin/python'), 'scripts/local_dev.py', 'run', '--api-port', str(api_port), '--web-port', str(web_port)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 120
            # Don't send localhost requests through inherited proxy configuration.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for path in (f'http://127.0.0.1:{api_port}/health', f'http://127.0.0.1:{web_port}/create'):
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('Launcher exited; see data/local-startup-check.log')
                    try:
                        with opener.open(path, timeout=10) as response:
                            body = response.read()
                            assert response.status == 200
                            if path.endswith('/health'):
                                assert json.loads(body)['status'] == 'healthy'
                            else:
                                assert b'<html' in body.lower() and b'/_next/' in body
                            break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() > deadline:
                            raise RuntimeError('Startup timed out; see data/local-startup-check.log') from None
                        time.sleep(.5)
            print('PASS: real API health and frontend create page on custom loopback ports')
        finally:
            process.terminate()
            process.wait(timeout=20)
    assert process.returncode == 0, 'Launcher did not stop cleanly'
    for port in (api_port, web_port):
        deadline = time.monotonic() + 10
        while True:
            with socket.socket() as sock:
                if sock.connect_ex(('127.0.0.1', port)) != 0:
                    break
            if time.monotonic() > deadline:
                raise RuntimeError(f'Owned service still listening on port {port}')
            time.sleep(.2)
    print('PASS: shutdown released both ports; no broad process cleanup used')


if __name__ == '__main__':
    main()
