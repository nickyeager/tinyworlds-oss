from pathlib import Path

import pytest

from src.api.services.touch_input_lint import lint_touch_handlers


@pytest.fixture
def godot_game(tmp_path: Path) -> Path:
    g = tmp_path / "godot-test"
    (g / "scripts").mkdir(parents=True)
    (g / "scenes").mkdir()
    (g / "project.godot").write_text("config_version=5\n")
    return g


@pytest.fixture
def bevy_game(tmp_path: Path) -> Path:
    g = tmp_path / "bevy-test"
    (g / "src").mkdir(parents=True)
    (g / "Cargo.toml").write_text("[package]\nname='x'\n")
    return g


def test_godot_no_touch_handler_fails(godot_game: Path) -> None:
    (godot_game / "scripts" / "main.gd").write_text(
        "extends Node3D\nfunc _process(delta):\n\tpass\n"
    )
    failures = lint_touch_handlers(godot_game, "godot")
    assert len(failures) == 1
    assert failures[0].rule == "missing_touch_input"


def test_godot_screen_touch_passes(godot_game: Path) -> None:
    (godot_game / "scripts" / "main.gd").write_text(
        "func _unhandled_input(e):\n\tif e is InputEventScreenTouch:\n\t\tpass\n"
    )
    assert lint_touch_handlers(godot_game, "godot") == []


def test_godot_mouse_button_passes(godot_game: Path) -> None:
    """Mouse events count because Godot emulates mouse from touch by default."""
    (godot_game / "scripts" / "main.gd").write_text(
        "func _input(e):\n\tif e is InputEventMouseButton:\n\t\tpass\n"
    )
    assert lint_touch_handlers(godot_game, "godot") == []


def test_godot_token_in_comment_does_not_count(godot_game: Path) -> None:
    (godot_game / "scripts" / "main.gd").write_text(
        "# TODO: handle InputEventScreenTouch later\nfunc _process(d): pass\n"
    )
    failures = lint_touch_handlers(godot_game, "godot")
    assert len(failures) == 1


def test_godot_empty_scripts_dir_returns_empty(godot_game: Path) -> None:
    assert lint_touch_handlers(godot_game, "godot") == []


def test_bevy_no_touch_handler_fails(bevy_game: Path) -> None:
    (bevy_game / "src" / "main.rs").write_text(
        "fn main() { println!(\"hi\"); }\n"
    )
    failures = lint_touch_handlers(bevy_game, "bevy")
    assert len(failures) == 1
    assert failures[0].rule == "missing_touch_input"


def test_bevy_touches_resource_passes(bevy_game: Path) -> None:
    (bevy_game / "src" / "input.rs").write_text(
        "fn read(touches: Res<Touches>) { let _ = touches; }\n"
    )
    assert lint_touch_handlers(bevy_game, "bevy") == []


def test_bevy_touch_input_event_passes(bevy_game: Path) -> None:
    (bevy_game / "src" / "input.rs").write_text(
        "fn read(mut ev: EventReader<TouchInput>) { for _ in ev.read() {} }\n"
    )
    assert lint_touch_handlers(bevy_game, "bevy") == []


def test_bevy_token_in_block_comment_does_not_count(bevy_game: Path) -> None:
    (bevy_game / "src" / "main.rs").write_text(
        "/* note: integrate TouchInput later */ fn main() {}\n"
    )
    failures = lint_touch_handlers(bevy_game, "bevy")
    assert len(failures) == 1
