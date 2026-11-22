#!/usr/bin/env python3
"""Configure, diagnose, and run a personal TinyWorlds installation.

No model calls, database migrations, or credential output. Child services bind
only to loopback; shutdown signals only process groups started by this command.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def configure(root: Path) -> bool:
    """Create an owner-readable env file once. Preserve existing state verbatim."""
    target = root / '.env'
    template = (root / '.env.example').read_text()
    template, count = re.subn(r'^SECRET_KEY=.*$', 'SECRET_KEY=' + secrets.token_hex(32), template, flags=re.M)
    if count != 1:
        raise ValueError('.env.example must contain exactly one SECRET_KEY entry')
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print('Kept existing .env; provider selection and credentials are unchanged.')
        return False
    with os.fdopen(fd, 'w') as stream:
        stream.write(template)
    print('Created private .env with a unique signing key. Connect your AI in the app.')
    return True


def command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, cwd=ROOT / 'web', capture_output=True, text=True, timeout=15)
        # Only report parsed versions, never arbitrary CLI output.
        match = re.search(r'(?<!\d)\d+\.\d+(?:\.\d+)?', result.stdout)
        return match.group() if result.returncode == 0 and match else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def check(root: Path = ROOT, api_only: bool = False) -> bool:
    """Check app prerequisites; generation tools are reported separately."""
    results = []

    def required(ok: bool, message: str) -> None:
        results.append(ok)
        print(('OK   ' if ok else 'FAIL ') + message)

    required(sys.version_info[:2] == (3, 12), 'Python 3.12 (run with .venv/bin/python)')
    try:
        from dotenv import dotenv_values
        config = dotenv_values(root / '.env', interpolate=False)
        secret = os.environ.get('SECRET_KEY') or config.get('SECRET_KEY') or ''
        required(len(secret) >= 32 and not secret.startswith('your-secret-key'), 'Signing key configured (value hidden)')
    except ImportError:
        required(False, 'Backend dependencies: run bash scripts/setup_environment.sh')
    for package in ('fastapi', 'uvicorn', 'sqlalchemy', 'playwright'):
        try:
            importlib.metadata.version(package)
            required(True, package + ' installed')
        except importlib.metadata.PackageNotFoundError:
            required(False, package + ' missing; run setup')
    if not api_only:
        node = command_version(['node', '--version'])
        required(bool(node and node.split('.')[0] == '22'), 'Node.js 22')
        pnpm = command_version(['pnpm', '--version'])
        required(pnpm == '10.18.0', 'pnpm 10.18.0 (web/package.json)')
        required((root / 'web/node_modules/next/dist/bin/next').is_file(), 'Frontend dependencies installed')
    for executable in ('codex', 'godot'):
        print(('OK   ' if shutil.which(executable) else 'WARN ') + executable + ' on PATH (needed for generation)')
    print('Generation also needs a connected provider, matching Godot Web export templates, and Playwright Chromium.')
    print('This check does not authenticate providers or run a game. See docs/guides/setup.md.')
    return all(results)


def require_free_port(port: int) -> None:
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise ValueError(f'Port {port} is occupied. Choose another port; no existing process was stopped.') from None


def run(api_port: int, web_port: int, api_only: bool) -> int:
    if not check(api_only=api_only):
        return 1
    if not api_only and api_port == web_port:
        raise ValueError('Backend and frontend must use different ports.')
    require_free_port(api_port)
    if not api_only:
        require_free_port(web_port)
    env = os.environ.copy()
    env.update(FRONTEND_URL=f'http://localhost:{web_port}', CORS_ORIGINS=json.dumps([f'http://localhost:{web_port}', f'http://127.0.0.1:{web_port}']))
    processes = []
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'src.api.main:app', '--host', '127.0.0.1', '--port', str(api_port)], cwd=ROOT, env=env, start_new_session=True))
        if not api_only:
            web_env = env | {'NEXT_PUBLIC_API_URL': f'http://localhost:{api_port}', 'NEXT_PUBLIC_GAME_PLAY_URL': f'http://localhost:{api_port}', 'NEXT_TELEMETRY_DISABLED': '1'}
            processes.append(subprocess.Popen(['node', 'node_modules/next/dist/bin/next', 'dev', '--hostname', '127.0.0.1', '--port', str(web_port)], cwd=ROOT / 'web', env=web_env, start_new_session=True))
        print(f'API: http://localhost:{api_port}/docs', flush=True)
        if not api_only:
            print(f'Open http://localhost:{web_port}/create and connect your own AI. Ctrl+C stops these services.', flush=True)
        while not stopping:
            for process in processes:
                code = process.poll()
                if code is not None:
                    return code or 1
            time.sleep(.2)
        return 0
    finally:
        # These new sessions belong to this invocation, including Next's children.
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 10
        for process in processes:
            try:
                process.wait(timeout=max(.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['configure', 'check', 'run'])
    parser.add_argument('--api-only', action='store_true')
    parser.add_argument('--api-port', type=int, default=8001)
    parser.add_argument('--web-port', type=int, default=3333)
    args = parser.parse_args()
    try:
        if args.command == 'configure':
            configure(ROOT)
            (ROOT / 'data').mkdir(exist_ok=True)
            return 0
        if args.command == 'check':
            return 0 if check(api_only=args.api_only) else 1
        for port in (args.api_port, args.web_port):
            if not 1 <= port <= 65535:
                raise ValueError('Ports must be between 1 and 65535.')
        (ROOT / 'data').mkdir(exist_ok=True)
        return run(args.api_port, args.web_port, args.api_only)
    except (OSError, ValueError) as error:
        # OS diagnostics contain paths, not environment contents.
        print(f'Setup error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
