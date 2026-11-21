"""BevyBuilder delegates the actual `docker run` to the
sidecar-launcher (security #1). These unit tests mock the launcher client and
verify the wrapper maps its result correctly — no docker required."""
from __future__ import annotations

import pytest

from src.api.services import bevy_builder as bb
from src.api.services.sidecar_launcher_client import (
    LaunchResult,
    SidecarLauncherError,
)


# --- BevyBuilder -----------------------------------------------------------

def test_bevy_build_delegates_to_launcher_and_returns_dist(tmp_path, monkeypatch):
    project = tmp_path / "bevy-1"
    project.mkdir()
    (project / "Cargo.toml").write_text("[package]\nname='x'\n")

    captured = {}

    def fake_build_bevy(project_dir, *, timeout=1830.0):
        captured["project_dir"] = project_dir
        return LaunchResult(True, 0, False, 1.0, "built", "")

    monkeypatch.setattr(bb, "build_bevy", fake_build_bevy)

    dist = bb.BevyBuilder().build(project)
    assert dist == project / "dist"
    assert captured["project_dir"] == str(project.resolve())


def test_bevy_build_raises_on_launcher_failure(tmp_path, monkeypatch):
    project = tmp_path / "bevy-1"
    project.mkdir()
    (project / "Cargo.toml").write_text("[package]\nname='x'\n")

    monkeypatch.setattr(
        bb, "build_bevy",
        lambda project_dir, **_: LaunchResult(False, 101, False, 1.0, "", "compile error"),
    )
    with pytest.raises(RuntimeError, match="compile error"):
        bb.BevyBuilder().build(project)


def test_bevy_build_missing_cargo_is_still_precondition_error(tmp_path, monkeypatch):
    project = tmp_path / "empty"
    project.mkdir()
    # build_bevy must never be called if the precondition fails.
    monkeypatch.setattr(
        bb, "build_bevy",
        lambda *a, **k: pytest.fail("launcher called despite missing Cargo.toml"),
    )
    with pytest.raises(FileNotFoundError):
        bb.BevyBuilder().build(project)


def test_bevy_build_launcher_unreachable_propagates(tmp_path, monkeypatch):
    """BevyBuilder deliberately lets SidecarLauncherError propagate — callers
    (bevy_game_service) treat it like any build-infrastructure failure."""
    project = tmp_path / "bevy-1"
    project.mkdir()
    (project / "Cargo.toml").write_text("[package]\nname='x'\n")

    def raising_build(project_dir, *, timeout=1830.0):
        raise SidecarLauncherError("sidecar launcher unreachable: boom")

    monkeypatch.setattr(bb, "build_bevy", raising_build)

    with pytest.raises(SidecarLauncherError):
        bb.BevyBuilder().build(project)
