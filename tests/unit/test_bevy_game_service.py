"""Unit tests for BevyGameService.

Real filesystem operations; no mocks. These tests do NOT invoke docker —
the slow path is covered by `tests/e2e/test_bevy_builder.py`.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from src.api.core.config import Settings
from src.api.services.bevy_game_service import BevyGameService


@pytest.fixture
def service() -> BevyGameService:
    return BevyGameService(Settings())


def test_create_game_writes_expected_files(service: BevyGameService, tmp_path: Path) -> None:
    game_path = service.create_game("my_game", tmp_path)

    assert game_path == tmp_path / "my_game"
    assert (game_path / "Cargo.toml").exists()
    assert (game_path / "src" / "main.rs").exists()
    assert (game_path / ".gitignore").exists()
    assert (game_path / ".git").exists()

    cargo_text = (game_path / "Cargo.toml").read_text()
    assert 'bevy = { version = "=0.18.1"' in cargo_text
    assert 'wasm-bindgen = "=0.2.121"' in cargo_text
    assert 'name = "my_game"' in cargo_text
    # Launcher caches are inside the project; a later agent git add must not
    # commit the registry or compiled dependencies.
    ignored = subprocess.run(
        ["git", "check-ignore", ".build-cache/cargo-home/registry/config.json"],
        cwd=game_path, capture_output=True, text=True,
    )
    assert ignored.returncode == 0


def test_create_game_sanitizes_invalid_crate_chars(
    service: BevyGameService, tmp_path: Path
) -> None:
    game_path = service.create_game("bevy-ABC.123", tmp_path)
    cargo_text = (game_path / "Cargo.toml").read_text()
    # Lowercase, dots replaced with underscore, dashes preserved.
    assert 'name = "bevy-abc_123"' in cargo_text


def test_read_name_returns_none_when_metadata_missing(
    service: BevyGameService, tmp_path: Path
) -> None:
    game_path = service.create_game("g", tmp_path)
    assert service.read_name(game_path) is None


def test_read_name_returns_none_when_cargo_toml_missing(
    service: BevyGameService, tmp_path: Path
) -> None:
    assert service.read_name(tmp_path / "nope") is None


def test_write_name_then_read_name_round_trip(
    service: BevyGameService, tmp_path: Path
) -> None:
    game_path = service.create_game("g", tmp_path)
    service.write_name(game_path, "Cool Game")
    assert service.read_name(game_path) == "Cool Game"


def test_write_name_replaces_existing(service: BevyGameService, tmp_path: Path) -> None:
    game_path = service.create_game("g", tmp_path)
    service.write_name(game_path, "First")
    service.write_name(game_path, "Second")
    assert service.read_name(game_path) == "Second"
    # And only one display_name line should be present.
    text = (game_path / "Cargo.toml").read_text()
    assert text.count("display_name") == 1


def test_write_name_rejects_empty(service: BevyGameService, tmp_path: Path) -> None:
    game_path = service.create_game("g", tmp_path)
    with pytest.raises(ValueError):
        service.write_name(game_path, "   ")


def test_write_name_raises_when_cargo_toml_missing(
    service: BevyGameService, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        service.write_name(tmp_path / "nope", "Whatever")


def test_list_games_filters_by_cargo_toml(
    service: BevyGameService, tmp_path: Path
) -> None:
    (tmp_path / "real_game").mkdir()
    (tmp_path / "real_game" / "Cargo.toml").write_text("[package]\n")
    (tmp_path / "not_a_game").mkdir()
    (tmp_path / "not_a_game" / "README.md").write_text("hi")

    assert service.list_games(tmp_path) == ["real_game"]


def test_list_games_returns_empty_for_missing_dir(
    service: BevyGameService, tmp_path: Path
) -> None:
    assert service.list_games(tmp_path / "does_not_exist") == []


def test_verify_playable_lists_each_missing_piece(
    service: BevyGameService, tmp_path: Path
) -> None:
    game_path = tmp_path / "g"
    game_path.mkdir()

    failures = service.verify_playable(game_path)
    assert "Cargo.toml missing" in failures
    assert "src/main.rs missing" in failures
    assert "dist/index.html missing" in failures
    assert "dist/*_bg.wasm missing" in failures
    assert "dist/*.js missing" in failures

    (game_path / "Cargo.toml").write_text("[package]\n")
    failures = service.verify_playable(game_path)
    assert "Cargo.toml missing" not in failures
    assert "src/main.rs missing" in failures

    (game_path / "src").mkdir()
    (game_path / "src" / "main.rs").write_text("fn main() {}")
    failures = service.verify_playable(game_path)
    assert "src/main.rs missing" not in failures
    assert any("mobile touch/pointer" in failure for failure in failures)
    assert "dist/index.html missing" in failures

    dist = game_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html/>")
    failures = service.verify_playable(game_path)
    assert "dist/index.html missing" not in failures
    assert "dist/*_bg.wasm missing" in failures

    (dist / "g_bg.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
    failures = service.verify_playable(game_path)
    assert "dist/*_bg.wasm missing" not in failures
    assert "dist/*.js missing" in failures

    (dist / "g.js").write_text("// shim")
    failures = service.verify_playable(game_path)
    assert any("mobile touch/pointer" in failure for failure in failures)

    (game_path / "src" / "main.rs").write_text(
        "use bevy::prelude::*;\n"
        "fn controls(buttons: Res<ButtonInput<MouseButton>>) {\n"
        "  let _pressed = buttons.pressed(MouseButton::Left);\n"
        "}\n"
    )
    failures = service.verify_playable(game_path)
    assert failures == []


def test_read_skill_reads_real_bevy_orchestrator(service: BevyGameService) -> None:
    content = service.read_skill("SKILL.md")
    assert content
    assert len(content) > 100


def test_read_skill_raises_for_missing(service: BevyGameService) -> None:
    with pytest.raises(FileNotFoundError):
        service.read_skill("does_not_exist.md")


def test_build_wasm_raises_when_cargo_toml_missing(
    service: BevyGameService, tmp_path: Path
) -> None:
    game_path = tmp_path / "empty"
    game_path.mkdir()
    with pytest.raises(FileNotFoundError):
        service.build_wasm(game_path)


def test_screenshot_and_video_paths(service: BevyGameService, tmp_path: Path) -> None:
    assert service.screenshot_path(tmp_path) == tmp_path / "screenshots" / "presentation" / "gameplay.png"
    assert service.video_path(tmp_path) == tmp_path / "screenshots" / "presentation" / "gameplay.mp4"


def test_read_artifact_returns_content_or_none(
    service: BevyGameService, tmp_path: Path
) -> None:
    game_path = service.create_game("g", tmp_path)
    assert service.read_artifact(game_path, "PLAN.md") is None
    (game_path / "PLAN.md").write_text("plan body")
    assert service.read_artifact(game_path, "PLAN.md") == "plan body"
