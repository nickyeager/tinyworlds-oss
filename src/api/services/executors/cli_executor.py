"""Provider-neutral streaming lifecycle and sandboxed Claude CLI adapter."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import platform
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from src.api.core.config import Settings
from src.api.observability.agent_traces import trace_agent_stream
from src.api.services.agent_commands import agent_model, claude_flags
from src.api.services.executors.runtime import PROJECT_ROOT, render_runtime
from src.api.services.godot_executor import ExecutorEvent, ExecutorResult, GodotExecutor

BUFFER_LIMIT = 65536
# No application credentials, arbitrary proxy/config variables or paid asset API keys.
ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TZ",
        "TMPDIR",
        "SYSTEMROOT",
        "WINDIR",
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OPENAI_API_KEY",
        "CARGO_HOME",
        "RUSTUP_HOME",
        "GODOT_BINARY",
        "GAME_ASSET_BROKER_URL",
        "GAME_ASSET_JOB_TOKEN",
    }
)


def parse_claude_event(obj: dict) -> list[ExecutorEvent]:
    """Normalize Claude stream JSON; all non-success results fail closed."""
    kind = obj.get("type")
    if kind in {"assistant", "user"}:
        events = []
        message = obj.get("message") or {}
        for block in message.get("content", []) if isinstance(message, dict) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text"):
                events.append(ExecutorEvent("thinking", str(block["text"])))
            elif block.get("type") == "tool_use":
                name = str(block.get("name", ""))
                events.append(
                    ExecutorEvent(
                        "tool_use",
                        name,
                        {"tool_name": name, "tool_use_id": block.get("id", ""), "input": block.get("input", {})},
                    )
                )
            elif block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        str(part.get("text", ""))
                        for part in content
                        if isinstance(part, dict)
                    )
                events.append(
                    ExecutorEvent(
                        "tool_result",
                        str(content),
                        {
                            "tool_use_id": block.get("tool_use_id", ""),
                            "success": not block.get("is_error", False),
                        },
                    )
                )
        return events
    if kind == "result":
        subtype = obj.get("subtype", "")
        if subtype != "success" or obj.get("is_error"):
            error = (
                obj.get("errors")
                or obj.get("error")
                or obj.get("result")
                or f"Claude result: {subtype or 'unknown'}"
            )
            if isinstance(error, dict):
                error = error.get("message", str(error))
            return [ExecutorEvent("error", str(error))]
        return [
            ExecutorEvent(
                "complete",
                str(obj.get("result", "")),
                {
                    "cost_usd": obj.get(
                        "total_cost_usd", (obj.get("usage") or {}).get("cost_usd")
                    ),
                    "usage": obj.get("usage", {}),
                    "subtype": subtype,
                    "success": True,
                },
            )
        ]
    if kind == "system":
        return [ExecutorEvent("status", f"system:{obj.get('subtype', '')}")]
    if kind == "error":
        return [
            ExecutorEvent(
                "error", str(obj.get("message", obj.get("error", "Claude failed")))
            )
        ]
    return []


def _parse_stream_event(raw_line: bytes) -> Optional[ExecutorEvent]:
    """Compatibility parser for existing consumers of a single Claude event."""
    try:
        events = parse_claude_event(json.loads(raw_line))
        return events[0] if events else None
    except (ValueError, TypeError):
        return None


class CLIExecutor(GodotExecutor):
    """Execute in one game directory, with bounded streams and mandatory cleanup."""

    provider = "claude"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _build_env(self) -> Dict[str, str]:
        """Pass explicitly allowed OS/toolchain/provider and scoped broker values."""
        env = {key: os.environ[key] for key in ENV_ALLOWLIST if key in os.environ}
        personal_env = getattr(self.settings, "_personal_provider_env", None)
        if personal_env is not None:
            for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
                env.pop(key, None)
            env.update(personal_env)
        for key in ("GAME_ASSET_BROKER_URL", "GAME_ASSET_JOB_TOKEN"):
            value = getattr(self.settings, key, "")
            if value:
                env[key] = value
        return env

    def _command(self, prompt: str, settings_path: str | None = None) -> list[str]:
        model = agent_model(self.settings, self.provider)
        return [
            self.settings.CLAUDE_CLI_BINARY,
            "-p",
            prompt,
            *claude_flags(model, settings_path=settings_path),
        ]

    def _events(self, obj: dict) -> list[ExecutorEvent]:
        return parse_claude_event(obj)

    def _check_isolation(self) -> None:
        system = platform.system()
        if system not in {"Darwin", "Linux"}:
            raise RuntimeError(
                "Provider OS sandbox is unavailable; configure the isolated agent worker"
            )
        if self.provider == "claude":
            binary = "sandbox-exec" if system == "Darwin" else "bwrap"
            if not shutil.which(binary):
                raise RuntimeError(
                    "Claude OS sandbox is unavailable; configure the isolated agent worker"
                )

    async def _cleanup(self, proc) -> None:
        """Terminate the entire session when still alive, then reap the child."""
        # A provider can exit while one of its background commands remains alive.
        # The dedicated process group must be disposed even after a clean exit.
        if isinstance(proc, asyncio.subprocess.Process):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
        else:
            await proc.wait()

    async def _local_stream(
        self, prompt: str, game_path: Path, timeout: float
    ) -> AsyncIterator[ExecutorEvent]:
        self._check_isolation()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        proc = None
        stderr_task = None
        stderr_buffer = bytearray()
        completion = None
        failed = False
        with tempfile.TemporaryDirectory(
            prefix="tinyworlds-agent-config-"
        ) as config_dir:
            env = self._build_env()
            settings_path = None
            if self.provider == "claude":
                native_personal_login = self.settings.PERSONAL_MODE and not env.get("ANTHROPIC_API_KEY")
                if not native_personal_login:
                    env["CLAUDE_CONFIG_DIR"] = config_dir
                # Copy only authentication, never user settings, hooks or MCP config.
                credentials = Path(env.get("HOME", "")) / ".claude/.credentials.json"
                if native_personal_login or env.get("ANTHROPIC_API_KEY"):
                    # Personal subscription auth stays in the official CLI's native
                    # store. Explicit API billing must never copy subscription auth.
                    pass
                elif credentials.is_file():
                    shutil.copyfile(credentials, Path(config_dir) / ".credentials.json")
                elif platform.system() == "Darwin":
                    # macOS stores the official Claude login in Keychain. A fresh
                    # config directory otherwise selects a different Keychain item.
                    # Copy this provider credential only; never load global settings.
                    lookup = await asyncio.to_thread(
                        subprocess.run,
                        [
                            "security",
                            "find-generic-password",
                            "-s",
                            "Claude Code-credentials",
                            "-w",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if lookup.returncode == 0:
                        credential_data = json.loads(lookup.stdout)
                        destination = Path(config_dir) / ".credentials.json"
                        destination.write_text(json.dumps(credential_data))
                        destination.chmod(0o600)
                settings_path = str(Path(config_dir) / "settings.json")
                denied = [
                    str(PROJECT_ROOT),
                    str(game_path.parent),
                    str(Path(env.get("HOME", "/nonexistent")) / ".ssh"),
                    str(Path(env.get("HOME", "/nonexistent")) / ".codex"),
                    str(Path(env.get("HOME", "/nonexistent")) / ".claude"),
                ]
                Path(settings_path).write_text(
                    json.dumps(
                        {
                            "disableAllHooks": True,
                            "sandbox": {
                                "enabled": True,
                                "failIfUnavailable": True,
                                "autoAllowBashIfSandboxed": True,
                                "allowUnsandboxedCommands": False,
                                "excludedCommands": [],
                                "filesystem": {
                                    "denyRead": denied,
                                    "allowRead": [str(game_path)],
                                    "allowWrite": [str(game_path)],
                                    "denyWrite": [config_dir],
                                },
                            },
                            "permissions": {
                                "allow": [
                                    "Read(./**)",
                                    "Edit(./**)",
                                    "Write(./**)",
                                    "Bash",
                                ],
                                "deny": [f"Read({PROJECT_ROOT}/.env)"],
                            },
                        }
                    )
                )
            try:
                proc = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        *self._command(prompt, settings_path),
                        cwd=str(game_path),
                        env=env,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        limit=1024 * 1024,
                        start_new_session=True,
                    ),
                    timeout=max(0.001, deadline - loop.time()),
                )

                async def drain_stderr() -> None:
                    if proc.stderr is None:
                        return
                    while True:
                        chunk = await proc.stderr.read(8192)
                        if not chunk:
                            return
                        stderr_buffer.extend(chunk)
                        del stderr_buffer[:-BUFFER_LIMIT]

                stderr_task = asyncio.create_task(drain_stderr())
                while True:
                    if loop.time() >= deadline:
                        raise asyncio.TimeoutError
                    line = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=max(0.001, deadline - loop.time()),
                    )
                    if not line:
                        break
                    try:
                        obj = json.loads(line)
                        if not isinstance(obj, dict):
                            raise ValueError("Expected JSON object")
                        events = self._events(obj)
                    except (ValueError, TypeError) as exc:
                        failed = True
                        yield ExecutorEvent(
                            "error", f"Invalid provider JSON stream: {exc}"
                        )
                        continue
                    for event in events:
                        event.content = event.content[:BUFFER_LIMIT]
                        if event.type == "complete":
                            completion = event
                        else:
                            failed |= event.type == "error"
                            yield event
                await asyncio.wait_for(
                    proc.wait(), timeout=max(0.001, deadline - loop.time())
                )
                await asyncio.wait_for(
                    stderr_task, timeout=max(0.001, deadline - loop.time())
                )
                if proc.returncode != 0:
                    failed = True
                    yield ExecutorEvent(
                        "error",
                        stderr_buffer.decode(errors="replace")
                        or f"{self.provider} exited with code {proc.returncode}",
                    )
                if completion is None:
                    failed = True
                    yield ExecutorEvent(
                        "error", "Provider stream ended without successful completion"
                    )
                yield ExecutorEvent(
                    "complete",
                    completion.content if completion and not failed else "",
                    {
                        **(completion.metadata or {} if completion else {}),
                        "exit_code": proc.returncode,
                        "success": not failed,
                        "stderr": stderr_buffer.decode(errors="replace"),
                    },
                )
            except asyncio.TimeoutError:
                if proc is not None:
                    await self._cleanup(proc)
                yield ExecutorEvent("error", f"Agent timeout after {timeout:g} seconds")
                yield ExecutorEvent("complete", "", {"success": False, "exit_code": -1})
            finally:
                if proc is not None:
                    await asyncio.shield(self._cleanup(proc))
                if stderr_task is not None:
                    stderr_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await stderr_task

    async def _worker_stream(
        self,
        prompt: str,
        game_path: Path,
        engine: str,
        budget_cents: int | None,
        timeout: float,
    ) -> AsyncIterator[ExecutorEvent]:
        import httpx

        model = agent_model(self.settings, self.provider)
        completed = False
        failed = False
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                self.settings.SIDECAR_LAUNCHER_URL.rstrip("/") + "/agent-run",
                headers={"X-Launcher-Token": self.settings.LAUNCHER_TOKEN},
                json={
                    "provider": self.provider,
                    "prompt": prompt,
                    "game_path": str(game_path),
                    "engine": engine,
                    "budget_cents": budget_cents,
                    "model": model,
                },
            ) as response:
                response.raise_for_status()
                async with asyncio.timeout(timeout):
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if len(line) > 1024 * 1024:
                            raise RuntimeError("Worker event exceeds maximum size")
                        obj = json.loads(line)
                        event = ExecutorEvent(
                            str(obj["type"]),
                            str(obj.get("content", ""))[:BUFFER_LIMIT],
                            obj.get("metadata"),
                        )
                        failed |= event.type == "error"
                        if event.type == "complete":
                            completed = True
                            event.metadata = {
                                **(event.metadata or {}),
                                "success": not failed
                                and (event.metadata or {}).get("success", True),
                            }
                        yield event
        if not completed:
            yield ExecutorEvent("error", "Worker stream ended without completion")
            yield ExecutorEvent("complete", "", {"success": False})

    async def run_stage(
        self,
        skill_content: str,
        user_prompt: str,
        game_path: Path,
        image_paths: Optional[List[str]] = None,
        context_files: Optional[Dict[str, str]] = None,
        mode: str = "create",
        *,
        engine: str = "godot",
        budget_cents: int | None = None,
    ) -> AsyncIterator[ExecutorEvent]:
        """Run creation or modification using the requested engine and approved budget."""
        root = Path(game_path).resolve()
        skills = render_runtime(
            root, engine=engine, provider=self.provider, budget_cents=budget_cents, mode=mode
        )
        operation = "modify an existing" if mode == "modify" else "create a new"
        prompt = (
            f"{operation} {engine.title()} browser game in {root}. Read "
            + ("CLAUDE.md" if self.provider == "claude" else "AGENTS.md")
            + f".\nInstruction: {user_prompt}\n"
        )
        resolved = (
            skill_content.replace("${ENGINE_NAME}", engine.title())
            .replace("${ENGINE_GUIDE_FILE}", f"{engine}.md")
            .replace(
                "${ASSET_SKILL_COMMAND}",
                "/asset-gen" if self.provider == "claude" else "$asset-gen",
            )
            .replace("${GODOGEN_SKILL_DIR}", str(skills))
            .replace("${CLAUDE_SKILL_DIR}", str(skills))
            .replace("${AGENT_NAME}", self.provider.title())
            .replace("${GODOGEN_COMMAND}", "the game runtime manifest")
        )
        resolved = resolved.replace(
            ".claude/skills/local/", str(skills / "local") + "/"
        )
        if resolved.strip():
            prompt += f"\n--- Additional task instructions ---\n{resolved}"
        for name, content in (context_files or {}).items():
            path = root / name
            if path.resolve().is_relative_to(root) and path.is_file() and not path.is_symlink() and path.read_text() == content:
                prompt += f"\nExisting project note (read if relevant): {name}"
            else:
                prompt += f"\n--- {name} ---\n{content}"
        for name in image_paths or []:
            if not (root / name).resolve().is_relative_to(root):
                raise ValueError("Reference image must be inside the game workspace")
            prompt += f"\nReference image: {name}"
        timeout = float(getattr(self.settings, "GAME_AGENT_TIMEOUT_SECONDS", 1800.0))
        stream = (
            self._worker_stream(prompt, root, engine, budget_cents, timeout)
            if getattr(self.settings, "AGENT_EXECUTION_MODE", "local") == "worker"
            else self._local_stream(prompt, root, timeout)
        )
        stream = trace_agent_stream(
            stream, self.settings, provider=self.provider, engine=engine,
            mode=mode, game_path=root, prompt=user_prompt,
        )
        try:
            async for event in stream:
                yield event
        except Exception as exc:
            yield ExecutorEvent("error", str(exc)[:BUFFER_LIMIT])
            yield ExecutorEvent("complete", "", {"success": False})
        finally:
            await stream.aclose()

    async def run_stage_sync(
        self,
        skill_content: str,
        user_prompt: str,
        game_path: Path,
        image_paths: Optional[List[str]] = None,
        context_files: Optional[Dict[str, str]] = None,
        mode: str = "create",
        *,
        engine: str = "godot",
        budget_cents: int | None = None,
    ) -> ExecutorResult:
        """Collect bounded stream output; success requires an explicit successful result."""
        output = ""
        errors = []
        success = False
        cost = None
        async for event in self.run_stage(
            skill_content,
            user_prompt,
            game_path,
            image_paths,
            context_files,
            mode,
            engine=engine,
            budget_cents=budget_cents,
        ):
            output = (output + "\n" + event.content)[-BUFFER_LIMIT:]
            if event.type == "error":
                errors.append(event.content[:BUFFER_LIMIT])
                errors = errors[-100:]
            if event.type == "complete":
                metadata = event.metadata or {}
                success = (
                    metadata.get("success", False) and metadata.get("exit_code", 0) == 0
                )
                cost = metadata.get("cost_usd")
        return ExecutorResult(
            success=success and not errors, stdout=output, errors=errors, cost_usd=cost
        )

    async def run_oneshot(self, prompt: str, *, timeout: float = 30.0) -> str:
        """Run a utility prompt in an empty temporary sandbox, never the app tree."""
        worker = getattr(self.settings, "AGENT_EXECUTION_MODE", "local") == "worker"
        root = Path(self.settings.GODOT_GAMES_DIR).resolve() if worker else None
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)
        output = []
        errors = []
        complete = False
        deadline = min(
            timeout,
            float(getattr(self.settings, "GAME_AGENT_TIMEOUT_SECONDS", timeout)),
        )
        with tempfile.TemporaryDirectory(
            prefix="tinyworlds-utility-", dir=root
        ) as workspace:
            stream = (
                self._worker_stream(prompt, Path(workspace), "godot", 0, deadline)
                if worker
                else self._local_stream(prompt, Path(workspace), deadline)
            )
            stream = trace_agent_stream(
                stream, self.settings, provider=self.provider, engine="godot",
                mode="utility", game_path=Path(workspace), prompt=prompt,
            )
            async for event in stream:
                if event.type == "thinking":
                    output.append(event.content)
                elif event.type == "error":
                    errors.append(event.content)
                elif event.type == "complete":
                    complete = (event.metadata or {}).get("success", False)
                    if event.content:
                        output = [event.content]
        if errors or not complete:
            raise RuntimeError("; ".join(errors) or "Utility prompt failed")
        return "\n".join(output)[-BUFFER_LIMIT:]
