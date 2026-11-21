#!/usr/bin/env python3
"""Nonpaid integration check for an already-built agent worker image.

Run from the repository: .venv/bin/python scripts/verify_agent_worker.py
Set AGENT_WORKER_IMAGE to check an image built under another tag.
Uses disposable Docker volumes/network and fake credentials. A derived image
replaces only Claude's CLI with deterministic events, so no model or asset API
is called. The real launcher, Docker isolation, entrypoint, scoped broker,
zero-budget rejection, deadline, and stream-disconnect cleanup are exercised.
"""

import asyncio
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path
import platform
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import uvicorn
from src.api import sidecar_launcher as launcher

# The worker image's pinned Codex version, read from the one place that sets it.
CODEX_VERSION = re.search(
    r"^ARG CODEX_VERSION=(\S+)$",
    (Path(__file__).resolve().parents[1] / "Dockerfile.agent").read_text(),
    re.M,
).group(1)

# Set AGENT_WORKER_IMAGE to check a build under another tag.
WORKER_IMAGE = os.environ.get("AGENT_WORKER_IMAGE", "tinyworlds/agent-worker:dev")

FIXTURE = r"""#!/usr/local/bin/python
import json, os, pathlib, subprocess, sys, time, urllib.request, urllib.error
p=pathlib.Path
root_readonly=False
try: p('/etc/worker-probe').write_text('bad')
except OSError: root_readonly=True
p('/workspace/worker-write.txt').write_text('UID1000 can write only requested game')
request=urllib.request.Request(os.environ['GAME_ASSET_BROKER_URL'],data=json.dumps({'operation':'image','prompt':'offline probe','output':'assets/probe.png','model':'gemini','size':'512','aspect_ratio':'1:1'}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+os.environ['GAME_ASSET_JOB_TOKEN']})
try:
    with urllib.request.urlopen(request,timeout=10) as response: zero_status=response.status
except urllib.error.HTTPError as error: zero_status=error.code
report={'uid':os.getuid(),'root_readonly':root_readonly,'app_absent':not p('/app').exists(),'socket_absent':not p('/var/run/docker.sock').exists(),'sibling_absent':not p('/workspace/game-b').exists() and not p('/game-b').exists(),'auth_copied':p('/home/agent/.claude/.credentials.json').is_file(),'other_auth_absent':not p('/agent-auth/codex').exists(),'secrets_absent':not any(name in os.environ for name in ('GOOGLE_API_KEY','XAI_API_KEY','LAUNCHER_TOKEN','JWT_SECRET_KEY','DATABASE_URL')),'zero_http_status':zero_status,'game_listing':sorted(path.name for path in p('/workspace').iterdir()),'godot_version':subprocess.check_output(['godot','--headless','--version'],text=True).strip(),'codex_version':subprocess.check_output(['codex','--version'],text=True).strip()}
print(json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':json.dumps(report)}]}}),flush=True)
if any(word in sys.argv for word in ('deadline','disconnect')):
    subprocess.Popen(['sleep','60'])
    time.sleep(60)
print(json.dumps({'type':'result','subtype':'success','result':'probe complete'}),flush=True)
"""


def docker(*args, input=None, check=True):
    result = subprocess.run(
        ["docker", *args], input=input, text=True, capture_output=True
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    return result


async def main():
    suffix = secrets.token_hex(4)
    volumes = [
        f"tinyworlds-isolation-games-{suffix}",
        f"tinyworlds-isolation-auth-{suffix}",
    ]
    network = f"tinyworlds-isolation-network-{suffix}"
    image = f"tinyworlds/isolation-probe:{suffix}"
    server = None
    serving = None
    with tempfile.TemporaryDirectory(prefix="tinyworlds-isolation-") as temporary:
        root = Path(temporary)
        (root / "fixture.py").write_text(FIXTURE)
        (root / "Dockerfile").write_text(
            f"FROM {WORKER_IMAGE}\nUSER 0\nCOPY fixture.py /usr/local/bin/probe-provider\nRUN chmod 755 /usr/local/bin/probe-provider && ln -sf /usr/local/bin/probe-provider /usr/local/bin/claude\nUSER 1000:1000\n"
        )
        try:
            docker("build", "-t", image, str(root))
            for volume in volumes:
                docker("volume", "create", volume)
            docker("network", "create", network)
            docker(
                "run",
                "--rm",
                "--user",
                "0:0",
                "--entrypoint",
                "/bin/sh",
                "--mount",
                f"type=volume,src={volumes[0]},dst=/games",
                "--mount",
                f"type=volume,src={volumes[1]},dst=/auth",
                image,
                "-c",
                "mkdir -p /games/game-a /games/game-b /auth/claude /auth/codex; printf marker > /games/game-a/only-this-game; printf private > /games/game-b/private; printf '{}' > /auth/claude/.credentials.json; printf '{}' > /auth/codex/auth.json; chmod 755 /auth/claude /auth/codex; chown -R 1000:1000 /games /auth; chmod 400 /auth/claude/.credentials.json /auth/codex/auth.json",
            )
            games = root / "games"
            games.mkdir()
            (games / "game-a").mkdir()
            dummy = root / "trusted-unpaid-asset.py"
            dummy.write_text('raise RuntimeError("unreachable: zero budget")')
            launcher.BEVY_PROJECTS_ROOT = str(games)
            launcher.ASSET_BUDGET_ROOT = root / "ledger"
            launcher.ASSET_TOOL = dummy
            launcher.AGENT_WORKER_IMAGE = image
            launcher.AGENT_GAMES_VOLUME = volumes[0]
            launcher.AGENT_AUTH_VOLUME = volumes[1]
            launcher._worker_auth_available = (
                lambda provider: True
            )  # Fixture auth location differs on the host; actual worker copies real testvolume auth.
            launcher.LAUNCHER_TOKEN = "offline-launcher-token"
            os.environ["GOOGLE_API_KEY"] = "fake-offline-unused"
            os.environ["AGENT_NETWORK"] = network
            import socket

            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            broker_host = (
                "host.docker.internal"
                if platform.system() in {"Darwin", "Windows"}
                else docker(
                    "network",
                    "inspect",
                    "--format",
                    "{{(index .IPAM.Config 0).Gateway}}",
                    network,
                ).stdout.strip()
            )
            launcher.GAME_ASSET_BROKER_URL = f"http://{broker_host}:{port}/agent-assets"
            server = uvicorn.Server(
                uvicorn.Config(
                    launcher.app,
                    host="0.0.0.0",
                    port=port,
                    log_level="error",
                    lifespan="off",
                )
            )
            serving = asyncio.create_task(server.serve())
            while not server.started:
                await asyncio.sleep(0.05)
            headers = {"X-Launcher-Token": launcher.LAUNCHER_TOKEN}
            body = {
                "provider": "claude",
                "prompt": "probe",
                "game_path": str(games / "game-a"),
                "engine": "godot",
                "budget_cents": 0,
                "model": "",
            }
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}", timeout=30
            ) as client:
                launcher.AGENT_RUN_TIMEOUT = 20
                response = await client.post("/agent-run", headers=headers, json=body)
                events = [json.loads(line) for line in response.text.splitlines()]
                assert events and events[-1]["type"] == "complete", events
                report = json.loads(
                    next(
                        event["content"]
                        for event in events
                        if event["type"] == "thinking"
                    )
                )
                assert report["uid"] == 1000 and report["zero_http_status"] == 402, (
                    report
                )
                for key in (
                    "root_readonly",
                    "app_absent",
                    "socket_absent",
                    "sibling_absent",
                    "auth_copied",
                    "other_auth_absent",
                    "secrets_absent",
                ):
                    assert report[key], report
                assert report["game_listing"] == [
                    "only-this-game",
                    "worker-write.txt",
                ], report
                assert (
                    report["godot_version"].startswith("4.4.stable")
                    and report["codex_version"] == f"codex-cli {CODEX_VERSION}"
                ), report
                print(
                    "Actual Docker mount isolation + UID1000 + rootfs protection + real HTTP zero-budget denial + Godot/Codex runtime PASS",
                    flush=True,
                )
                launcher.AGENT_RUN_TIMEOUT = 3
                response = await client.post(
                    "/agent-run", headers=headers, json={**body, "prompt": "deadline"}
                )
                events = [json.loads(line) for line in response.text.splitlines()]
                assert (
                    events[-1]["type"] == "error"
                    and "deadline" in events[-1]["content"].lower()
                ), events
                jobs = docker(
                    "ps", "-aq", "--filter", f"ancestor={image}"
                ).stdout.strip()
                assert not jobs, jobs
                print(
                    "Actual Docker deadline killed/reaped worker and background child PASS",
                    flush=True,
                )
                launcher.AGENT_RUN_TIMEOUT = 30
                async with client.stream(
                    "POST",
                    "/agent-run",
                    headers=headers,
                    json={**body, "prompt": "disconnect"},
                ) as response:
                    async for line in response.aiter_lines():
                        if line:
                            break
                ledger = launcher._asset_ledger()
                active_tokens = None
                for attempt in range(50):
                    jobs = docker(
                        "ps", "-aq", "--filter", f"ancestor={image}"
                    ).stdout.strip()
                    conn = ledger._connect()
                    try:
                        active_tokens = conn.execute(
                            "SELECT count(*) FROM jobs WHERE revoked=0"
                        ).fetchone()[0]
                    finally:
                        conn.close()
                    # Container removal precedes capability revocation. Wait for
                    # both observable cleanup effects before asserting success.
                    if not jobs and active_tokens == 0:
                        break
                    await asyncio.sleep(0.1)
                assert not jobs, jobs
                assert active_tokens == 0, f"{active_tokens} unrevoked job tokens"
                print(
                    "Actual HTTP stream disconnect removed/reaped Docker worker and revoked all tokens PASS",
                    flush=True,
                )
        finally:
            if server is not None:
                server.should_exit = True
                if serving is not None:
                    await serving
            for identifier in docker(
                "ps", "-aq", "--filter", f"ancestor={image}", check=False
            ).stdout.split():
                docker("rm", "-f", identifier, check=False)
            docker("image", "rm", image, check=False)
            docker("network", "rm", network, check=False)
            for volume in volumes:
                docker("volume", "rm", volume, check=False)


if __name__ == "__main__":
    asyncio.run(main())
