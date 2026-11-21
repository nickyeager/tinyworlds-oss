"""Trusted fixed-command Docker launcher and prepaid image broker.

Only this sidecar holds the Docker socket. Authenticated callers can request
builds or one isolated provider worker; they cannot supply
Docker mounts, commands, flags, or environment. Workers mount only one game
and the selected provider's dedicated auth directory. Paid image requests use
revocable game-scoped capabilities and an atomic ledger outside game storage.

Run with uvicorn src.api.sidecar_launcher:app --host 0.0.0.0 --port 8500.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Literal, Optional

import anyio
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from src.api.services.agent_commands import (
    MODEL_MAX_LENGTH,
    MODEL_PATTERN,
    claude_flags,
    codex_flags,
)
from src.api.services.game_asset_budget import (
    AssetBudgetLedger,
    AssetBudgetExceeded,
    InvalidAssetJob,
)


# --- configuration (read from the launcher's own environment) --------------


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


LAUNCHER_TOKEN = os.getenv("LAUNCHER_TOKEN", "")
if os.getenv("REQUIRE_PRODUCTION_SECRETS", "").lower() in {"1", "true", "yes"}:
    if len(LAUNCHER_TOKEN) < 32 or LAUNCHER_TOKEN.lower() in {
        "dev-launcher-token",
        "changeme",
        "change-me",
    }:
        raise RuntimeError(
            "production requires a non-default launcher token of at least 32 characters"
        )
BEVY_BUILDER_IMAGE = _env("BEVY_BUILDER_IMAGE", "tinyworlds/bevy-builder:dev")
CARGO_CACHE_VOLUME = _env("CARGO_CACHE_VOLUME", "tinyworlds_cargo-cache")
CARGO_TARGET_VOLUME = _env("CARGO_TARGET_VOLUME", "tinyworlds_cargo-target")
# Directory arguments must live under one of these roots. They mirror the
# volumes this container shares with the backend (games volume + shared /tmp).
BEVY_PROJECTS_ROOT = _env("BEVY_PROJECTS_ROOT", "/app/generated_games")
BEVY_BUILD_TIMEOUT = float(_env("BEVY_BUILD_TIMEOUT", "1800"))


# --- pure helpers (unit-testable without docker) ---------------------------


def resolve_under(path_str: str, allowed_root: str) -> Path:
    """Resolve ``path_str`` and assert it is the allowed root or beneath it.

    Uses the real (symlink-resolved) path so a symlink inside the root can't
    point the eventual bind-mount at an arbitrary host location.

    Raises:
        ValueError: if the path escapes the root or is not an existing dir.
    """
    root = Path(allowed_root).resolve()
    p = Path(path_str).resolve()
    if p != root and root not in p.parents:
        raise ValueError(
            f"path {path_str!r} is not under allowed root {allowed_root!r}"
        )
    if not p.is_dir():
        raise ValueError(f"path {path_str!r} is not an existing directory")
    return p


def bevy_build_argv(project_dir: Path, name: str | None = None) -> List[str]:
    """Mount the Docker volume's game subpath, never a container-local bind path."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project_dir.name):
        raise ValueError("invalid game id")
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name or "tinyworlds-bevy-" + secrets.token_hex(12),
        "--init",
        "--read-only",
        "--user",
        "1000:1000",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "512",
        "--memory",
        "3g",
        "--cpus",
        "2",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=512m,mode=1777",
        "--tmpfs",
        "/home/agent:rw,nosuid,nodev,size=128m,uid=1000,gid=1000,mode=0700",
        "--mount",
        f"type=volume,src={AGENT_GAMES_VOLUME},dst=/project,volume-subpath={project_dir.name}",
        "--network",
        _env("AGENT_NETWORK", "tinyworlds_agents"),
        "--env",
        "HOME=/home/agent",
        "--env",
        "CARGO_HOME=/project/.build-cache/cargo-home",
        "--env",
        "CARGO_TARGET_DIR=/project/.build-cache/cargo-target",
        BEVY_BUILDER_IMAGE,
        "bevy_build",
        "/project",
    ]


# --- request/response models ----------------------------------------------


class BevyBuildRequest(BaseModel):
    project_dir: str


class RunResult(BaseModel):
    ok: bool
    returncode: Optional[int] = None
    timed_out: bool = False
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""


# --- auth ------------------------------------------------------------------


async def require_launcher_token(
    x_launcher_token: str = Header(default="", alias="X-Launcher-Token"),
) -> None:
    # Network isolation is the primary control; this shared secret is defense
    # in depth. If no token is configured we fail closed rather than open.
    if not LAUNCHER_TOKEN or not hmac.compare_digest(x_launcher_token, LAUNCHER_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing launcher token",
        )


# --- runner ----------------------------------------------------------------


async def _run(argv: List[str], timeout: float) -> RunResult:
    start = time.monotonic()
    proc = None
    readers = []
    try:
        async with asyncio.timeout(timeout):
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            readers = [
                asyncio.create_task(_bounded_stderr(proc.stdout)),
                asyncio.create_task(_bounded_stderr(proc.stderr)),
            ]
            code = await proc.wait()
            stdout, stderr = await asyncio.gather(*readers)
            return RunResult(
                ok=code == 0,
                returncode=code,
                duration_seconds=time.monotonic() - start,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
            )
    except FileNotFoundError:
        return RunResult(ok=False, stderr="Docker executable unavailable")
    except TimeoutError:
        return RunResult(
            ok=False,
            timed_out=True,
            duration_seconds=time.monotonic() - start,
            stderr=f"timed out after {timeout}s",
        )
    finally:
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
        for reader in readers:
            if not reader.done():
                reader.cancel()
        if readers:
            await asyncio.gather(*readers, return_exceptions=True)


# --- app -------------------------------------------------------------------

app = FastAPI(
    title="TinyWorlds sidecar launcher", docs_url=None, redoc_url=None, openapi_url=None
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/bevy-build",
    response_model=RunResult,
    dependencies=[Depends(require_launcher_token)],
)
async def bevy_build(req: BevyBuildRequest) -> RunResult:
    try:
        project_dir = resolve_game_project(req.project_dir)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    _assign_worker_ownership(project_dir)
    name = "tinyworlds-bevy-" + secrets.token_hex(12)
    try:
        return await _run(
            bevy_build_argv(project_dir, name), timeout=BEVY_BUILD_TIMEOUT
        )
    finally:
        with anyio.CancelScope(shield=True):
            await _remove_worker(name, None)


# --- isolated provider workers and trusted paid-asset broker ----------------
# These operations never accept arbitrary mounts, commands, environment or CLI
# switches. Agent capabilities only authorize one game's prepaid asset account.
AGENT_WORKER_IMAGE = _env("AGENT_WORKER_IMAGE", "tinyworlds/agent-worker:dev")
AGENT_GAMES_VOLUME = _env("AGENT_GAMES_VOLUME", "tinyworlds_games")
AGENT_AUTH_VOLUME = _env("AGENT_AUTH_VOLUME", "tinyworlds_agent-auth")
AGENT_RUN_TIMEOUT = float(_env("AGENT_RUN_TIMEOUT", "1800"))
ASSET_REQUEST_TIMEOUT = float(_env("ASSET_REQUEST_TIMEOUT", "150"))
ASSET_BUDGET_ROOT = Path(_env("ASSET_BUDGET_ROOT", "/app/trusted/asset-budget"))
ASSET_TOOL = (
    Path(__file__).resolve().parents[2]
    / "vendor/godogen-runtime/asset-gen/tools/asset_gen.py"
)
GAME_ASSET_BROKER_URL = _env(
    "GAME_ASSET_BROKER_URL", "http://sidecar-launcher:8500/agent-assets"
)
_ASSET_RESERVATION_CENTS = 50
_AGENT_SLOTS = asyncio.Semaphore(max(1, int(_env("AGENT_MAX_CONCURRENT", "4"))))
_ASSET_SLOTS = asyncio.Semaphore(max(1, int(_env("ASSET_MAX_CONCURRENT", "4"))))
_GLB_SLOTS = asyncio.Semaphore(1)
_BUFFER_LIMIT = 65536
_ASPECT_RATIOS = frozenset(
    {
        "1:1",
        "1:4",
        "1:8",
        "2:3",
        "3:2",
        "3:4",
        "4:1",
        "4:3",
        "4:5",
        "5:4",
        "8:1",
        "9:16",
        "16:9",
        "21:9",
        "2:1",
        "1:2",
        "19.5:9",
        "9:19.5",
        "20:9",
        "9:20",
        "auto",
    }
)
_ledger_instance: AssetBudgetLedger | None = None


def _asset_ledger() -> AssetBudgetLedger:
    global _ledger_instance
    if _ledger_instance is None or _ledger_instance.path.parent != ASSET_BUDGET_ROOT:
        _ledger_instance = AssetBudgetLedger(ASSET_BUDGET_ROOT)
    return _ledger_instance


def resolve_game_project(path_str: str) -> Path:
    """Only a direct, existing, nonsymlink game directory may be mounted."""
    if not isinstance(path_str, str) or "," in path_str or "\x00" in path_str:
        raise ValueError("invalid game project")
    path = Path(path_str)
    root = Path(BEVY_PROJECTS_ROOT).absolute()
    if not path.is_absolute() or ".." in path.parts or path.parent != root:
        raise ValueError("project must be a direct game under the games root")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", path.name):
        raise ValueError("invalid game id")
    if (
        path.is_symlink()
        or not path.is_dir()
        or path.resolve().parent != root.resolve()
    ):
        raise ValueError("project must be an existing nonsymlink game directory")
    return path


def _worker_auth_available(provider: str) -> bool:
    filename = ".credentials.json" if provider == "claude" else "auth.json"
    path = Path("/agent-auth") / provider / filename
    try:
        info = path.stat()
        # The worker cannot rely on launcher-root permission to read credentials.
        readable = (
            (info.st_uid == 1000 and info.st_mode & 0o400)
            or (info.st_gid == 1000 and info.st_mode & 0o040)
            or info.st_mode & 0o004
        )
        return (
            path.is_file()
            and not path.is_symlink()
            and not path.parent.is_symlink()
            and bool(readable)
        )
    except OSError:
        return False


def agent_run_argv(
    req: "AgentRunRequest", project: Path, name: str, token: str
) -> list[str]:
    # Docker's volume-subpath restricts the named games volume to this one game.
    # No socket, app, sibling game, backend config, or paid API keys are mounted.
    for volume in (AGENT_GAMES_VOLUME, AGENT_AUTH_VOLUME):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", volume):
            raise ValueError("invalid configured agent volume")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project.name):
        raise ValueError("invalid game id")
    argv = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--init",
        "--read-only",
        "--user",
        "1000:1000",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "256",
        "--memory",
        "2g",
        "--cpus",
        "2",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=512m,mode=1777",
        "--tmpfs",
        "/home/agent:rw,nosuid,nodev,size=256m,uid=1000,gid=1000,mode=0700",
        "--workdir",
        "/workspace",
        "--mount",
        f"type=volume,src={AGENT_GAMES_VOLUME},dst=/workspace,volume-subpath={project.name}",
        "--mount",
        f"type=volume,src={AGENT_AUTH_VOLUME},dst=/agent-auth/{req.provider},volume-subpath={req.provider},readonly",
        "--network",
        _env("AGENT_NETWORK", "tinyworlds_agents"),
        "--env",
        "HOME=/home/agent",
        "--env",
        "CODEX_HOME=/home/agent/.codex",
        "--env",
        f"GAME_ASSET_JOB_TOKEN={token}",
        "--env",
        f"GAME_ASSET_BROKER_URL={GAME_ASSET_BROKER_URL}",
        AGENT_WORKER_IMAGE,
        req.provider,
    ]
    if req.provider == "claude":
        argv += ["-p", *claude_flags(req.model, skip_permissions=True)]
    else:
        argv += codex_flags(req.model)
    return argv + ["--", req.prompt]


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["claude", "codex"]
    prompt: str = Field(min_length=1, max_length=200000)
    game_path: str
    engine: Literal["godot", "bevy"] = "godot"
    budget_cents: Optional[StrictInt] = Field(default=None, ge=0)
    model: str = Field(default="", max_length=MODEL_MAX_LENGTH, pattern=MODEL_PATTERN)


class AgentAssetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["image", "glb"]
    prompt: str = Field(default="", max_length=10000)
    output: str = Field(max_length=300)
    model: Literal["gemini", "grok"] = "gemini"
    size: Literal["512", "1K"] = "1K"
    aspect_ratio: str = "1:1"
    image: Optional[str] = Field(default=None, max_length=300)


def _json_event(kind: str, content: str = "", metadata: Optional[dict] = None) -> str:
    return (
        json.dumps(
            {"type": kind, "content": content, "metadata": metadata or {}}, default=str
        )
        + "\n"
    )


async def _bounded_stderr(reader) -> bytes:
    tail = bytearray()
    while True:
        part = await reader.read(4096)
        if not part:
            return bytes(tail)
        tail.extend(part)
        if len(tail) > _BUFFER_LIMIT:
            del tail[:-_BUFFER_LIMIT]


async def _remove_worker(name: str, proc) -> None:
    # Killing the Docker client alone does not stop the worker and its children.
    with contextlib.suppress(OSError, asyncio.TimeoutError):
        remover = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(remover.wait(), timeout=15)
        finally:
            if remover.returncode is None:
                remover.kill()
            await remover.wait()
    if proc is not None:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        await proc.wait()


def _assign_worker_ownership(project: Path) -> None:
    # The trusted game access/verification records never live in this tree.
    if os.geteuid() != 0:
        return

    def own_directory(descriptor: int) -> None:
        os.fchown(descriptor, 1000, 1000)
        with os.scandir(descriptor) as entries:
            for entry in entries:
                try:
                    # Parent directory handles block concurrent symlink swaps
                    # from redirecting root's ownership changes outside a game.
                    os.chown(
                        entry.name, 1000, 1000, dir_fd=descriptor, follow_symlinks=False
                    )
                    if entry.is_dir(follow_symlinks=False):
                        child = os.open(
                            entry.name,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor,
                        )
                        try:
                            own_directory(child)
                        finally:
                            os.close(child)
                except FileNotFoundError:
                    continue

    descriptor = os.open(project, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        own_directory(descriptor)
    finally:
        os.close(descriptor)


@app.post("/agent-run", dependencies=[Depends(require_launcher_token)])
async def agent_run(req: AgentRunRequest):
    try:
        project = resolve_game_project(req.game_path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not _worker_auth_available(req.provider):
        raise HTTPException(503, "selected provider authentication is unavailable")
    # Validate argv before issuing a capability; invalid mount configuration fails closed.
    name = "tinyworlds-agent-" + secrets.token_hex(12)
    try:
        agent_run_argv(req, project, name, "validation")
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc

    async def events():
        proc = None
        stderr_task = None
        token = None
        failed = False
        completion = None
        ledger = _asset_ledger()
        try:
            async with asyncio.timeout(AGENT_RUN_TIMEOUT):
                async with _AGENT_SLOTS:
                    # Resolve again after waiting; a removed/replaced game cannot inherit a job.
                    resolve_game_project(req.game_path)
                    _assign_worker_ownership(project)
                    token = ledger.create_job(
                        project.name,
                        req.budget_cents if req.budget_cents is not None else 0,
                    )
                    argv = agent_run_argv(req, project, name, token)
                    proc = await asyncio.create_subprocess_exec(
                        *argv,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        limit=_BUFFER_LIMIT,
                    )
                    stderr_task = asyncio.create_task(_bounded_stderr(proc.stderr))
                    if req.provider == "codex":
                        from src.api.services.executors.codex_executor import (
                            parse_codex_event,
                        )

                        parse_events = parse_codex_event
                    else:
                        from src.api.services.executors.cli_executor import (
                            parse_claude_event,
                        )

                        parse_events = parse_claude_event
                    while raw := await proc.stdout.readline():
                        try:
                            obj = json.loads(raw)
                            if not isinstance(obj, dict):
                                raise ValueError("worker event must be an object")
                            parsed = parse_events(obj)
                        except (ValueError, TypeError, AttributeError):
                            failed = True
                            yield _json_event(
                                "error", "Agent worker returned a malformed event"
                            )
                            return
                        for event in parsed:
                            if event.type == "complete":
                                completion = event
                            else:
                                failed = failed or event.type == "error"
                                yield _json_event(
                                    event.type, event.content, event.metadata
                                )
                    returncode = await proc.wait()
                    await stderr_task
                    if returncode != 0 or failed or completion is None:
                        yield _json_event(
                            "error", f"Agent execution failed (exit {returncode})"
                        )
                    else:
                        yield _json_event(
                            completion.type, completion.content, completion.metadata
                        )
        except asyncio.TimeoutError:
            yield _json_event("error", "Agent execution deadline exceeded")
        except asyncio.CancelledError:
            raise
        except Exception:
            yield _json_event("error", "Isolated agent worker could not run")
        finally:
            # Starlette disconnect cancellation must not cancel container disposal.
            with anyio.CancelScope(shield=True):
                await _remove_worker(name, proc)
                if stderr_task is not None and not stderr_task.done():
                    stderr_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stderr_task
                if token is not None:
                    with contextlib.suppress(InvalidAssetJob):
                        ledger.revoke(token)

    return StreamingResponse(events(), media_type="application/x-ndjson")


def _relative_asset_path(value: str, *, output: bool = False, suffix: str = ".png") -> Path:
    path = Path(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\x00" in value
        or "\\" in value
    ):
        raise ValueError("asset paths must be relative to the game")
    if output and (
        len(path.parts) < 2
        or path.parts[0] != "assets"
        or path.suffix.lower() != suffix
    ):
        raise ValueError(f"output must be a {suffix} file under assets/")
    if not output and path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("reference must be a game image")
    return path


@contextlib.contextmanager
def _asset_parent(project: Path, relative: Path, *, create: bool = False):
    """Hold directory descriptors; reject symlinks even during worker races."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(project, flags)
    try:
        for part in relative.parts[:-1]:
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, mode=0o755, dir_fd=descriptor)
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        try:
            entry = os.stat(relative.name, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                raise
        else:
            import stat

            if not stat.S_ISREG(entry.st_mode):
                raise ValueError("asset must be a regular file, never a symlink")
        yield descriptor
    finally:
        os.close(descriptor)


def _copy_reference(project: Path, relative: Path, destination: Path) -> None:
    import stat

    with _asset_parent(project, relative) as parent:
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 20 * 1024 * 1024:
                raise ValueError("reference image is invalid or too large")
            with destination.open("wb") as target:
                # The source might grow while read; enforce the bound again.
                content = source.read(20 * 1024 * 1024 + 1)
                if len(content) > 20 * 1024 * 1024:
                    raise ValueError("reference image is too large")
                target.write(content)


def _write_asset(parent: int, filename: str, source: Path) -> None:
    # Replace the directory entry instead of truncating a possible hardlink.
    temporary = ".broker-" + secrets.token_hex(16) + ".png"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o644,
        dir_fd=parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, target)
            target.flush()
            os.fsync(target.fileno())
            if os.geteuid() == 0:
                os.fchown(target.fileno(), 1000, 1000)
        os.replace(temporary, filename, src_dir_fd=parent, dst_dir_fd=parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent)


def _asset_provider(req: AgentAssetRequest) -> tuple[str, str, dict]:
    """Choose one keyed provider before a request; never retry a paid request."""
    google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    xai_key = os.environ.get("XAI_API_KEY")
    provider = req.model
    if provider == "gemini" and not google_key:
        provider = "grok"
    elif provider == "grok" and not xai_key:
        provider = "gemini"
    if provider == "gemini" and not google_key or provider == "grok" and not xai_key:
        raise HTTPException(503, "asset provider is unavailable")
    gemini_ratios = {
        "1:1",
        "1:4",
        "1:8",
        "2:3",
        "3:2",
        "3:4",
        "4:1",
        "4:3",
        "4:5",
        "5:4",
        "8:1",
        "9:16",
        "16:9",
        "21:9",
    }
    grok_ratios = {
        "1:1",
        "16:9",
        "9:16",
        "4:3",
        "3:4",
        "3:2",
        "2:3",
        "2:1",
        "1:2",
        "19.5:9",
        "9:19.5",
        "20:9",
        "9:20",
        "auto",
    }
    if req.aspect_ratio not in (gemini_ratios if provider == "gemini" else grok_ratios):
        raise HTTPException(
            400, "aspect ratio is unsupported by the available provider"
        )
    size = req.size
    if provider == "grok" and size == "512":
        if provider == req.model:
            raise HTTPException(400, "grok images require size 1K")
        size = "1K"
    # No proxy, app, signing, database, launcher or unrelated paid credentials.
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env["GOOGLE_API_KEY" if provider == "gemini" else "XAI_API_KEY"] = (
        google_key if provider == "gemini" else xai_key
    )
    return provider, size, env


async def _asset_subprocess(
    argv: list[str], env: dict, directory: Path
) -> tuple[int, bytes]:
    proc = None
    stdout_task = stderr_task = None
    try:
        env = {**env, "HOME": str(directory), "TMPDIR": str(directory)}
        proc = await asyncio.create_subprocess_exec(
            *argv,
            env=env,
            cwd=directory,
            start_new_session=True,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_task = asyncio.create_task(_bounded_stderr(proc.stdout))
        stderr_task = asyncio.create_task(_bounded_stderr(proc.stderr))
        async with asyncio.timeout(ASSET_REQUEST_TIMEOUT):
            returncode = await proc.wait()
            stdout = await stdout_task
            await stderr_task
            return returncode, stdout
    finally:
        with anyio.CancelScope(shield=True):
            if proc is not None:
                if proc.returncode is None:
                    import signal

                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
            for task in (stdout_task, stderr_task):
                if task is not None:
                    if not task.done():
                        task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task


@app.post("/agent-assets")
async def agent_assets(req: AgentAssetRequest, authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "invalid asset job")
    token = authorization[7:]
    ledger = _asset_ledger()
    try:
        job = ledger.job(token)
    except InvalidAssetJob as exc:
        raise HTTPException(401, "invalid asset job") from exc
    if req.operation == "glb":
        return await _agent_glb(req, token, ledger, job)
    if not req.prompt:
        raise HTTPException(400, "image prompt is required")
    try:
        project = resolve_game_project(str(Path(BEVY_PROJECTS_ROOT) / job["game_id"]))
        output = _relative_asset_path(req.output, output=True)
        reference = _relative_asset_path(req.image) if req.image is not None else None
        if req.aspect_ratio not in _ASPECT_RATIOS:
            raise ValueError("unsupported aspect ratio")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    provider, size, env = _asset_provider(req)
    if not ASSET_TOOL.is_file():
        raise HTTPException(503, "trusted asset runtime is unavailable")
    async with _ASSET_SLOTS:
        # All paths are validated and any reference is staged BEFORE charging.
        with tempfile.TemporaryDirectory(prefix="tinyworlds-asset-") as staging:
            directory = Path(staging)
            result_file = directory / "image.png"
            try:
                with _asset_parent(project, output, create=True) as parent:
                    argv = [
                        sys.executable,
                        str(ASSET_TOOL),
                        "image",
                        "--prompt",
                        req.prompt,
                        "--model",
                        provider,
                        "--size",
                        size,
                        "--aspect-ratio",
                        req.aspect_ratio,
                        "--output",
                        str(result_file),
                    ]
                    if reference is not None:
                        staged_reference = directory / (
                            "reference" + reference.suffix.lower()
                        )
                        _copy_reference(project, reference, staged_reference)
                        argv += ["--image", str(staged_reference)]
                    # Atomic reservation happens immediately before the single paid request.
                    try:
                        remaining = ledger.reserve(token, _ASSET_RESERVATION_CENTS)
                    except InvalidAssetJob as exc:
                        raise HTTPException(401, "invalid asset job") from exc
                    except AssetBudgetExceeded as exc:
                        raise HTTPException(402, "asset budget exhausted") from exc
                    response = {
                        "ok": False,
                        "path": output.as_posix(),
                        "cost_cents": _ASSET_RESERVATION_CENTS,
                        "reserved_cents": _ASSET_RESERVATION_CENTS,
                        "remaining_cents": remaining,
                    }
                    try:
                        returncode, stdout = await _asset_subprocess(
                            argv, env, directory
                        )
                        payload = json.loads(stdout.decode("utf-8").splitlines()[-1])
                        cost = payload.get("cost_cents", _ASSET_RESERVATION_CENTS)
                        if (
                            returncode != 0
                            or payload.get("ok") is not True
                            or not result_file.is_file()
                            or isinstance(cost, bool)
                            or not isinstance(cost, int)
                            or not 0 <= cost <= _ASSET_RESERVATION_CENTS
                        ):
                            raise ValueError(
                                "asset provider returned an invalid result"
                            )
                        # Require an actual, bounded PNG before inserting in the game.
                        with result_file.open("rb") as generated:
                            if (
                                generated.read(8) != b"\x89PNG\r\n\x1a\n"
                                or result_file.stat().st_size > 20 * 1024 * 1024
                            ):
                                raise ValueError(
                                    "asset provider returned an invalid image"
                                )
                        _write_asset(parent, output.name, result_file)
                        response.update(ok=True, cost_cents=cost)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # Exceptions from third-party clients can contain credentials.
                        response["error"] = (
                            "Asset generation failed; reservation remains charged"
                        )
                    return response
            except HTTPException:
                raise
            except (OSError, ValueError) as exc:
                raise HTTPException(400, "invalid or unsafe asset path") from exc


async def _agent_glb(req: AgentAssetRequest, token: str, ledger: AssetBudgetLedger, job: dict):
    from src.api.services import trellis_assets as trellis
    import hashlib

    if not os.environ.get("FAL_KEY"):
        raise HTTPException(503, "3D asset provider is unavailable")
    if not req.image:
        raise HTTPException(400, "3D generation requires a game image")
    try:
        project = resolve_game_project(str(Path(BEVY_PROJECTS_ROOT) / job["game_id"]))
        output = _relative_asset_path(req.output, output=True, suffix=".glb")
        reference = _relative_asset_path(req.image)
        async with _GLB_SLOTS:
            with tempfile.TemporaryDirectory(prefix="tinyworlds-glb-") as staging:
                directory = Path(staging)
                source = directory / "reference"
                _copy_reference(project, reference, source)
                content = source.read_bytes()
                trellis.validate_reference(content)
                request_key = hashlib.sha256(b"trellis-512-v1\0" + output.as_posix().encode() + b"\0" + content).hexdigest()
                # Validate the destination before reserving money. Keep the directory
                # descriptor open through generation, as for image assets.
                with _asset_parent(project, output, create=True) as parent:
                    try:
                        reused = await trellis.generate_glb(content, ledger, token, request_key, directory / "result.glb")
                        ledger.job(token)  # Do not publish after worker capability revocation.
                        _write_asset(parent, output.name, directory / "result.glb")
                        return {"ok": True, "path": output.as_posix(), "cost_cents": 0 if reused else trellis.COST_CENTS,
                                "reserved_cents": trellis.COST_CENTS, "remaining_cents": ledger.job(token)["remaining_cents"]}
                    except (AssetBudgetExceeded, InvalidAssetJob):
                        raise
                    except Exception:
                        return {"ok": False, "error": "3D generation pending or failed; retry the same image and output to resume without another charge"}
    except AssetBudgetExceeded as exc:
        raise HTTPException(402, "asset budget exhausted") from exc
    except InvalidAssetJob as exc:
        raise HTTPException(401, "invalid asset job") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(400, "invalid or unsafe 3D asset path or reference") from exc


@app.post(
    "/godot-export",
    response_model=RunResult,
    dependencies=[Depends(require_launcher_token)],
)
async def godot_export(req: BevyBuildRequest):
    try:
        project = resolve_game_project(req.project_dir)
    except ValueError as exc:
        raise HTTPException(400, "Invalid game export directory") from exc
    _assign_worker_ownership(project)
    name = "tinyworlds-godot-" + secrets.token_hex(12)
    # Generated @tool/editor scripts execute here, without network, auth or app.
    script = (
        "set -eu; mkdir -p /home/agent/.local/share/godot; "
        "ln -s /opt/godot/export_templates /home/agent/.local/share/godot/export_templates; "
        "godot --headless --editor --import --quit; "
        "exec godot --headless --export-release Web /workspace/dist/index.html"
    )
    argv = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--init",
        "--read-only",
        "--user",
        "1000:1000",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--network",
        "none",
        "--pids-limit",
        "256",
        "--memory",
        "2g",
        "--cpus",
        "2",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=512m,mode=1777",
        "--tmpfs",
        "/home/agent:rw,nosuid,nodev,size=128m,uid=1000,gid=1000,mode=0700",
        "--mount",
        f"type=volume,src={AGENT_GAMES_VOLUME},dst=/workspace,volume-subpath={project.name}",
        "--workdir",
        "/workspace",
        "--env",
        "HOME=/home/agent",
        "--entrypoint",
        "/bin/sh",
        AGENT_WORKER_IMAGE,
        "-c",
        script,
    ]
    proc = None
    readers = []
    started = time.monotonic()
    try:
        async with asyncio.timeout(180):
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            readers = [
                asyncio.create_task(_bounded_stderr(proc.stdout)),
                asyncio.create_task(_bounded_stderr(proc.stderr)),
            ]
            code = await proc.wait()
            stdout, stderr = await asyncio.gather(*readers)
            return RunResult(
                ok=code == 0,
                returncode=code,
                duration_seconds=time.monotonic() - started,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
            )
    except TimeoutError:
        return RunResult(
            ok=False, timed_out=True, stderr="Godot export deadline exceeded"
        )
    finally:
        with anyio.CancelScope(shield=True):
            await _remove_worker(name, proc)
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            if readers:
                await asyncio.gather(*readers, return_exceptions=True)


@app.get("/agent-capabilities", dependencies=[Depends(require_launcher_token)])
async def agent_capabilities():
    return {
        "isolated_workers": True,
        "worker_image": AGENT_WORKER_IMAGE,
        "providers": {
            provider: _worker_auth_available(provider)
            for provider in ("claude", "codex")
        },
        "asset_operations": ["image"] + (["glb"] if os.environ.get("FAL_KEY") else []),
        "asset_reservation_cents": _ASSET_RESERVATION_CENTS,
        "trusted_asset_runtime": ASSET_TOOL.is_file(),
    }


@app.get("/capabilities", dependencies=[Depends(require_launcher_token)])
async def capabilities():
    """Probe fixed Docker prerequisites without starting a job or paid request."""
    provider = _env("GAME_AGENT_PROVIDER", "claude")
    checks = {
        "provider_auth": provider in {"claude", "codex"}
        and _worker_auth_available(provider),
        "games_root": Path(BEVY_PROJECTS_ROOT).is_dir(),
        "trusted_asset_runtime": ASSET_TOOL.is_file(),
    }
    probes = {
        "docker_api": ["docker", "version", "--format", "{{.Server.APIVersion}}"],
        "worker_image": [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            AGENT_WORKER_IMAGE,
        ],
        "games_volume": [
            "docker",
            "volume",
            "inspect",
            "--format",
            "{{.Name}}",
            AGENT_GAMES_VOLUME,
        ],
        "auth_volume": [
            "docker",
            "volume",
            "inspect",
            "--format",
            "{{.Name}}",
            AGENT_AUTH_VOLUME,
        ],
        "worker_network": [
            "docker",
            "network",
            "inspect",
            "--format",
            "{{.Name}}",
            _env("AGENT_NETWORK", "tinyworlds_agents"),
        ],
    }
    results = await asyncio.gather(*(_run(argv, 10) for argv in probes.values()))
    for key, result in zip(probes, results):
        checks[key] = result.ok
        if key == "docker_api":
            try:
                major, minor = (int(part) for part in result.stdout.strip().split("."))
                checks[key] = result.ok and (major, minor) >= (1, 45)
            except (ValueError, TypeError):
                checks[key] = False
    return {"ready": all(checks.values()), "provider": provider, "checks": checks}
