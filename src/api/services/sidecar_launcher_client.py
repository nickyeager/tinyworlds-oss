"""Client for the privileged docker-launcher sidecar (security #1).

The backend no longer holds /var/run/docker.sock. Instead it asks the
``sidecar-launcher`` service to run its fixed docker jobs (bevy build,
Godot export). The launcher constructs the `docker run` argv itself, so the
backend (and the injectable agent it spawns) can never craft an arbitrary
docker command.

Two call styles matching the existing callers:
  * ``build_bevy`` — synchronous (BevyBuilder.build is sync)
  * ``export_godot`` — async
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

from src.api.core.config import get_settings


@dataclass
class LaunchResult:
    ok: bool
    returncode: Optional[int]
    timed_out: bool
    duration_seconds: float
    stdout: str
    stderr: str


class SidecarLauncherError(RuntimeError):
    """The launcher was unreachable or returned a non-2xx response."""


def _config() -> tuple[str, dict]:
    s = get_settings()
    base = s.SIDECAR_LAUNCHER_URL.rstrip("/")
    headers = {"X-Launcher-Token": s.LAUNCHER_TOKEN}
    return base, headers


def _to_result(payload: dict) -> LaunchResult:
    return LaunchResult(
        ok=bool(payload.get("ok")),
        returncode=payload.get("returncode"),
        timed_out=bool(payload.get("timed_out")),
        duration_seconds=float(payload.get("duration_seconds") or 0.0),
        stdout=payload.get("stdout") or "",
        stderr=payload.get("stderr") or "",
    )


def build_bevy(project_dir: str, *, timeout: float = 1830.0) -> LaunchResult:
    """Ask the launcher to run a bevy build (synchronous).

    ``timeout`` is the HTTP client timeout; keep it slightly above the
    launcher's own docker timeout so the launcher wins the race and returns a
    structured ``timed_out`` result instead of the client aborting.
    """
    base, headers = _config()
    try:
        resp = httpx.post(
            f"{base}/bevy-build",
            json={"project_dir": project_dir},
            headers=headers,
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        raise SidecarLauncherError(f"sidecar launcher unreachable: {e}") from e
    if resp.status_code != 200:
        raise SidecarLauncherError(
            f"sidecar launcher /bevy-build returned {resp.status_code}: {resp.text[:300]}"
        )
    return _to_result(resp.json())


async def export_godot(project_dir: str, *, timeout: float = 240.0) -> LaunchResult:
    """Run generated Godot editor/tool scripts in an isolated fixed worker."""
    base, headers = _config()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(base + "/godot-export", json={"project_dir": project_dir}, headers=headers)
            response.raise_for_status()
            return _to_result(response.json())
    except httpx.HTTPError as exc:
        raise SidecarLauncherError("Isolated Godot export worker was unavailable") from exc
