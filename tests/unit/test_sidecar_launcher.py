"""The privileged docker-launcher must construct fixed argv and refuse to
bind-mount anything outside its allowed roots (security #1)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import sidecar_launcher as L


# --- path validation (the core security control) ---------------------------

def test_resolve_under_accepts_path_in_root(tmp_path):
    root = tmp_path / "root"
    sub = root / "game-1"
    sub.mkdir(parents=True)
    assert L.resolve_under(str(sub), str(root)) == sub.resolve()


def test_resolve_under_accepts_root_itself(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    assert L.resolve_under(str(root), str(root)) == root.resolve()


def test_resolve_under_rejects_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError):
        L.resolve_under(str(outside), str(root))


def test_resolve_under_rejects_parent_traversal(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        L.resolve_under(str(root / ".." / ".."), str(root))


def test_resolve_under_rejects_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret"
    secret.mkdir()
    link = root / "escape"
    link.symlink_to(secret)  # symlink inside root -> outside
    with pytest.raises(ValueError):
        L.resolve_under(str(link), str(root))


def test_resolve_under_rejects_missing_dir(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        L.resolve_under(str(root / "does-not-exist"), str(root))


# --- argv construction -----------------------------------------------------

def test_bevy_argv_is_fixed_shape(tmp_path):
    argv = L.bevy_build_argv(tmp_path)
    assert argv[:3] == ["docker", "run", "--rm"]
    assert f"type=volume,src={L.AGENT_GAMES_VOLUME},dst=/project,volume-subpath={tmp_path.name}" in argv
    assert "--read-only" in argv and "1000:1000" in argv
    assert f"{tmp_path}:/project" not in argv
    assert argv[-3:] == [L.BEVY_BUILDER_IMAGE, "bevy_build", "/project"]


# --- endpoints: auth + validation + fixed dispatch -------------------------

async def _fake_run(argv, timeout):
    # Record the argv the endpoint would have executed instead of shelling out.
    return L.RunResult(ok=True, returncode=0, stdout=" ".join(argv))


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    bevy_root = tmp_path / "generated_games"
    bevy_root.mkdir()
    monkeypatch.setattr(L, "LAUNCHER_TOKEN", "secret-token")
    monkeypatch.setattr(L, "BEVY_PROJECTS_ROOT", str(bevy_root))
    monkeypatch.setattr(L, "_run", _fake_run)
    from unittest.mock import AsyncMock
    monkeypatch.setattr(L, "_remove_worker", AsyncMock())
    return bevy_root, None


def _client():
    return AsyncClient(transport=ASGITransport(app=L.app), base_url="http://launcher")


@pytest.mark.asyncio
async def test_bevy_build_requires_token(launcher):
    bevy_root, _ = launcher
    (bevy_root / "g1").mkdir()
    async with _client() as ac:
        r = await ac.post("/bevy-build", json={"project_dir": str(bevy_root / "g1")})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bevy_build_rejects_wrong_token(launcher):
    bevy_root, _ = launcher
    (bevy_root / "g1").mkdir()
    async with _client() as ac:
        r = await ac.post(
            "/bevy-build",
            json={"project_dir": str(bevy_root / "g1")},
            headers={"X-Launcher-Token": "nope"},
        )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_bevy_build_rejects_path_outside_root(launcher, tmp_path):
    async with _client() as ac:
        r = await ac.post(
            "/bevy-build",
            json={"project_dir": str(tmp_path / "outside")},
            headers={"X-Launcher-Token": "secret-token"},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_bevy_build_runs_fixed_argv_for_valid_path(launcher):
    bevy_root, _ = launcher
    (bevy_root / "g1").mkdir()
    async with _client() as ac:
        r = await ac.post(
            "/bevy-build",
            json={"project_dir": str(bevy_root / "g1")},
            headers={"X-Launcher-Token": "secret-token"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # The endpoint dispatched the fixed docker argv (captured by _fake_run).
    assert "docker run --rm" in body["stdout"]
    assert "bevy_build /project" in body["stdout"]


def test_resolve_under_rejects_null_byte(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ValueError):
        L.resolve_under(str(root) + "/\x00evil", str(root))
