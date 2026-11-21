"""Thin wrapper over the bevy-builder docker image.

The actual `docker run` is executed by the privileged ``sidecar-launcher``
service (security #1: the backend no longer holds /var/run/docker.sock). This
wrapper validates the precondition, asks the launcher to build, and returns
the produced dist/.

Scope: build only. Project scaffolding, agent orchestration, and HTTP
serving belong elsewhere.
"""
from __future__ import annotations

from pathlib import Path

from src.api.services.sidecar_launcher_client import build_bevy


class BevyBuilder:
    def __init__(self, image: str = "tinyworlds/bevy-builder:dev") -> None:
        # Image is now selected by the launcher (BEVY_BUILDER_IMAGE); kept in
        # the signature for backward compatibility with existing callers/tests.
        self._image = image

    def build(self, project_dir: Path) -> Path:
        project_dir = project_dir.resolve()
        if not (project_dir / "Cargo.toml").exists():
            raise FileNotFoundError(f"no Cargo.toml in {project_dir}")

        result = build_bevy(str(project_dir))
        if not result.ok:
            detail = result.stderr.strip()[-800:] or result.stdout.strip()[-800:]
            raise RuntimeError(
                f"bevy build failed (rc={result.returncode}, "
                f"timed_out={result.timed_out}): {detail}"
            )
        return project_dir / "dist"
