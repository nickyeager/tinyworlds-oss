"""One local operator's provider connection, separate from TinyWorlds accounts.

The official Codex process owns OAuth and token refresh. No provider credentials
are returned to the browser. Hosted/per-user credentials are deliberately absent.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import shutil
import time
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field

from src.api.core.config import Settings


class Connection(BaseModel):
    provider: Literal["codex", "claude"]
    kind: Literal["existing_cli", "managed"]
    model: str = Field(default="", max_length=120)
    profile: UUID | None = None


def provider_root(settings: Settings) -> Path:
    root = (Path(settings.PERSONAL_PROVIDER_DIR).expanduser() if settings.PERSONAL_PROVIDER_DIR else Path.home() / ".local/share/tinyworlds/providers").resolve()
    if root.is_relative_to(Path(settings.GODOT_GAMES_DIR).resolve()):
        raise HTTPException(503, "Provider credentials must be stored outside generated games.")
    return root


def read_connection(settings: Settings) -> Connection | None:
    file = provider_root(settings) / "connection.json"
    if not file.exists():
        return None
    try:
        connection = Connection.model_validate_json(file.read_text())
        if connection.kind == "managed" and connection.profile is None:
            raise ValueError("Missing profile")
        return connection
    except (OSError, ValueError):
        raise HTTPException(503, "Provider connection is unreadable. Inspect the local connection.json file.") from None


def resolve_personal_settings(settings: Settings) -> Settings:
    if not settings.PERSONAL_MODE:
        return settings
    if settings.AGENT_EXECUTION_MODE != "local" or settings.REQUIRE_PRODUCTION_SECRETS:
        raise HTTPException(503, "Personal connections require a local, single-user instance.")
    connection = read_connection(settings)
    if connection is None:
        raise HTTPException(409, "Connect your AI provider at /connect before creating or editing a game.")
    result = settings.model_copy(deep=True)
    result.GAME_AGENT_PROVIDER = connection.provider
    setattr(result, "CODEX_CLI_MODEL" if connection.provider == "codex" else "CLAUDE_CLI_MODEL", connection.model)
    result._personal_provider_env = {}
    if connection.kind == "managed":
        profile = provider_root(settings) / str(connection.profile)
        if connection.provider == "codex":
            if not (profile / "auth.json").is_file():
                raise HTTPException(409, "Codex login is missing. Reconnect in AI setup.")
            result._personal_provider_env = {"CODEX_HOME": str(profile)}
        else:
            try:
                key = (profile / "api-key").read_text()
            except OSError:
                raise HTTPException(409, "Claude API key is missing. Reconnect in AI setup.") from None
            result._personal_provider_env = {"ANTHROPIC_API_KEY": key}
    return result


def private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def auth_env(profile: Path | None = None) -> dict[str, str]:
    # No inherited API keys or provider overrides: the selected login is explicit.
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT") if k in os.environ}
    if profile:
        env["CODEX_HOME"] = str(profile)
    return env


class CodexAuth:
    """Bounded stdio JSON-RPC connection to the unmodified official app-server."""
    def __init__(self, process):
        self.process = process
        self.sequence = 0

    @classmethod
    async def start(cls, settings: Settings, profile: Path):
        profile.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_write(profile / "config.toml", 'cli_auth_credentials_store = "file"\n')
        process = await asyncio.create_subprocess_exec(
            settings.CODEX_CLI_BINARY, "app-server", "--listen", "stdio://",
            cwd=profile, env=auth_env(profile), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=1024 * 1024,
        )
        client = cls(process)
        try:
            await client.request("initialize", {"clientInfo": {"name": "tinyworlds_local", "title": "TinyWorlds local", "version": "0.1.0"}})
            process.stdin.write(b'{"method":"initialized"}\n')
            await process.stdin.drain()
            return client
        except BaseException:
            await client.close()
            raise

    async def request(self, method: str, params: dict) -> dict:
        self.sequence += 1
        self.process.stdin.write((json.dumps({"id": self.sequence, "method": method, "params": params}) + "\n").encode())
        await self.process.stdin.drain()
        async with asyncio.timeout(25):
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    raise RuntimeError("Codex authentication process ended")
                message = json.loads(line)
                if message.get("id") != self.sequence:
                    continue
                if "error" in message:
                    raise RuntimeError("Codex could not complete this authentication request")
                return message.get("result") or {}

    async def close(self):
        if self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self.process.kill()
                await self.process.wait()


class PersonalProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = provider_root(settings)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.lock = asyncio.Lock()
        self.pending: dict | None = None
        self.expiry: asyncio.Task | None = None
        self.last_check = 0.0

    def status(self) -> dict:
        connection = read_connection(self.settings)
        return {
            "connection": connection.model_dump(mode="json", exclude={"profile"}) if connection else None,
            "installed": {p: bool(shutil.which(getattr(self.settings, p.upper() + "_CLI_BINARY"))) for p in ("codex", "claude")},
            "pending_login": bool(self.pending),
        }

    def ensure_idle(self):
        from src.api.services.game_jobs import has_active_jobs
        if has_active_jobs():
            raise HTTPException(409, "Finish or stop the current game job before changing its provider.")

    def save(self, connection: Connection):
        self.ensure_idle()
        previous = read_connection(self.settings)
        private_write(self.root / "connection.json", connection.model_dump_json())
        if previous and previous.profile and previous.profile != connection.profile:
            shutil.rmtree(self.root / str(previous.profile), ignore_errors=True)

    async def connect_existing(self, provider: str, model: str):
        self.ensure_idle()
        command = [self.settings.CODEX_CLI_BINARY, "login", "status"] if provider == "codex" else [self.settings.CLAUDE_CLI_BINARY, "auth", "status", "--json"]
        process = await asyncio.create_subprocess_exec(*command, env=auth_env(), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 15)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        logged_in = process.returncode == 0
        if provider == "claude":
            logged_in = logged_in and json.loads(output).get("loggedIn", False)
        if not logged_in:
            raise HTTPException(409, f"Sign in with {'codex login' if provider == 'codex' else 'claude auth login'} in your terminal, then try again.")
        self.save(Connection(provider=provider, kind="existing_cli", model=model))

    async def connect_key(self, provider: str, model: str, key: str):
        self.ensure_idle()
        if not 8 <= len(key) <= 4096 or any(c.isspace() for c in key):
            raise HTTPException(400, "Enter a valid API key without whitespace.")
        profile_id = uuid4()
        profile = self.root / str(profile_id)
        client = None
        try:
            if provider == "codex":
                client = await CodexAuth.start(self.settings, profile)
                await client.request("account/login/start", {"type": "apiKey", "apiKey": key})
                (profile / "auth.json").chmod(0o600)
            else:
                private_write(profile / "api-key", key)
            self.save(Connection(provider=provider, kind="managed", model=model, profile=profile_id))
        except BaseException:
            shutil.rmtree(profile, ignore_errors=True)
            raise
        finally:
            if client:
                await client.close()

    async def start_login(self, model: str):
        self.ensure_idle()
        if self.pending:
            raise HTTPException(409, "A sign-in is already open. Finish or cancel it first.")
        profile_id = uuid4()
        profile = self.root / str(profile_id)
        client = None
        try:
            client = await CodexAuth.start(self.settings, profile)
            result = await client.request("account/login/start", {"type": "chatgpt"})
            url = result.get("authUrl", "")
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in {"auth.openai.com", "chatgpt.com", "auth.chatgpt.com"}:
                raise RuntimeError("Unexpected provider sign-in address")
            self.pending = {"client": client, "profile": profile_id, "model": model}
            self.expiry = asyncio.create_task(self.expire_login())
            return {"url": url, "expires_in": 600}
        except BaseException:
            if client:
                await client.close()
            shutil.rmtree(profile, ignore_errors=True)
            raise

    async def finish_login(self) -> bool:
        if not self.pending:
            raise HTTPException(409, "No sign-in is pending. Start again.")
        account = await self.pending["client"].request("account/read", {"refreshToken": False})
        if not account.get("account"):
            return False
        self.ensure_idle()
        profile = self.root / str(self.pending["profile"])
        (profile / "auth.json").chmod(0o600)
        self.save(Connection(provider="codex", kind="managed", model=self.pending["model"], profile=self.pending["profile"]))
        await self.cancel_login(remove_profile=False)
        return True

    async def cancel_login(self, remove_profile=True):
        if self.expiry and self.expiry is not asyncio.current_task():
            self.expiry.cancel()
        self.expiry = None
        if self.pending:
            pending, self.pending = self.pending, None
            await pending["client"].close()
            if remove_profile:
                shutil.rmtree(self.root / str(pending["profile"]), ignore_errors=True)

    async def expire_login(self):
        await asyncio.sleep(600)
        async with self.lock:
            await self.cancel_login()

    async def disconnect(self):
        self.ensure_idle()
        await self.cancel_login()
        self.ensure_idle()
        previous = read_connection(self.settings)
        (self.root / "connection.json").unlink(missing_ok=True)
        if previous and previous.profile:
            shutil.rmtree(self.root / str(previous.profile), ignore_errors=True)

    async def check(self):
        if time.monotonic() - self.last_check < 15:
            raise HTTPException(429, "Wait a few seconds before checking again.")
        self.last_check = time.monotonic()
        from src.api.services.executors import get_executor
        try:
            await get_executor(self.settings).run_oneshot("Reply with the single word: ok", timeout=45)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "Connection check failed. Check your sign-in, model access and provider balance, then reconnect.") from None
        return {"ok": True}


_services: dict[str, PersonalProvider] = {}


def personal_provider(settings: Settings) -> PersonalProvider:
    key = str(provider_root(settings))
    if key not in _services:
        _services[key] = PersonalProvider(settings)
    return _services[key]


async def close_personal_providers():
    for service in _services.values():
        await service.cancel_login()
