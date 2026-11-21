"""Real backend, OAuth and MCP sessions; no network/service stubs."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import uvicorn

from services.plugin.config import Config
from services.plugin.server import create_app

ROOT = Path(__file__).resolve().parents[3]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def backend_server(tmp_path_factory):
    # Isolate real rate-limit buckets, accounts and job state between tests.
    root = tmp_path_factory.mktemp("plugin-backend")
    port = free_port()
    executable = os.getenv("TINYWORLDS_API_PYTHON")
    if not executable:
        candidate = ROOT / ".venv/bin/python"
        executable = str(candidate) if candidate.exists() else sys.executable
    # Configure this disposable process without inheriting .env secrets.
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "TMPDIR", "LANG"}
    }
    env.update(
        DATABASE_URL=f"sqlite+aiosqlite:///{root}/api.sqlite3",
        SECRET_KEY="local-plugin-integration-test-signing-key",
        GODOT_GAMES_DIR=str(root / "generated_games"),
        GAME_AGENT_PROVIDER="codex",
        AGENT_EXECUTION_MODE="local",
        GAME_PLAY_ORIGIN="",
        PLUGIN_TEST_API_PORT=str(port),
        FRONTEND_URL="http://localhost:3333",
        SENTRY_DSN="",
    )
    log = (root / "server.log").open("w")
    process = subprocess.Popen(
        [executable, str(Path(__file__).with_name("backend_server.py"))],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=log,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail((root / "server.log").read_text()[-6000:])
            try:
                response = httpx.get(base_url + "/health", timeout=1)
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            pytest.fail(
                "Disposable backend did not become healthy: "
                + (root / "server.log").read_text()[-6000:]
            )
        yield base_url, root
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()


@pytest_asyncio.fixture
async def gateway(backend_server, tmp_path):
    backend_url, backend_root = backend_server
    port = free_port()
    config = Config(
        public_url=f"http://127.0.0.1:{port}",
        backend_url=backend_url,
        data_dir=tmp_path,
    )
    app = create_app(config)
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="error", access_log=False
        )
    )
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.05)
        else:
            pytest.fail("Gateway did not start")
        async with httpx.AsyncClient(
            base_url=config.public_url, follow_redirects=False
        ) as client:
            yield app, client, config, backend_root
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
