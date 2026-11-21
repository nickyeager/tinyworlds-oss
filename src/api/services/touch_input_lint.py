"""Pre-ship static lint that asserts a generated game accepts touch input.

The HTML overlay shim (``mobile_support.inject_mobile_play_shim``) synthesizes
keyboard events from touch, so any game that reads keyboard input will still
work on mobile via the overlay. But games that handle pointer/touch natively
feel substantially better, and the overlay assumes a WASD + Space/Enter
binding. This lint flags games whose source contains no engine-level touch
hook so the agent retry loop can correct them.

Usage::

    failures = lint_touch_handlers(game_path, engine="godot")
    if failures: ...  # record + feed back into agent fix instruction
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Literal

from src.api.services.godot_export_lint import LintFailure

Engine = Literal["godot", "bevy"]


# Godot input APIs that signal touch handling. We accept either Screen* events
# (the canonical touch path) or MouseButton/MouseMotion (works on mobile via
# the engine's mouse-emulation-from-touch when ``emulate_mouse_from_touch`` is
# on, which is the default in 4.x).
_GODOT_TOUCH_TOKENS = (
    "InputEventScreenTouch",
    "InputEventScreenDrag",
    "InputEventMouseButton",
    "InputEventMouseMotion",
)

# Bevy input APIs that signal touch handling. ``Touches`` is the polled
# resource, ``TouchInput`` the event, ``bevy_picking`` covers the new pointer
# abstraction (which routes touch + mouse). Pointer events from bevy_input also
# count.
_BEVY_TOUCH_TOKENS = (
    "Touches",
    "TouchInput",
    "TouchPhase",
    "PointerInput",
    "bevy_picking",
)


def _collect_source_files(game_path: Path, engine: Engine) -> List[Path]:
    if engine == "godot":
        files = list((game_path / "scripts").rglob("*.gd")) + list(
            (game_path / "scripts").rglob("*.cs")
        )
        files += list((game_path / "scenes").rglob("*.tscn"))
        return files
    if engine == "bevy":
        return list((game_path / "src").rglob("*.rs"))
    raise ValueError(f"unknown engine: {engine}")


def _strip_gd_comments(text: str) -> str:
    """Best-effort strip of `#`-prefixed line comments from GDScript/TSCN.

    Tokens that appear only inside comments don't count as real handlers.
    Block strings are rare in real game code; we tolerate the imprecision.
    """
    return re.sub(r"#[^\n]*", "", text)


def _strip_rs_comments(text: str) -> str:
    """Strip `// ...` and `/* ... */` from Rust source."""
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text


def lint_touch_handlers(game_path: Path, engine: Engine) -> List[LintFailure]:
    """Return a single ``missing_touch_input`` failure when no handler is found.

    The lint is intentionally coarse: one failure per game, not per file. The
    retry loop only needs to know "you forgot touch entirely"; the agent
    decides where to put it.
    """
    tokens = _GODOT_TOUCH_TOKENS if engine == "godot" else _BEVY_TOUCH_TOKENS
    strip = _strip_gd_comments if engine == "godot" else _strip_rs_comments

    files = _collect_source_files(game_path, engine)
    if not files:
        return []

    found_token: str | None = None
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        stripped = strip(text)
        for token in tokens:
            if token in stripped:
                found_token = token
                break
        if found_token:
            break

    if found_token:
        return []

    expected = ", ".join(tokens)
    detail = (
        f"no touch input handler found in {engine} game source "
        f"(expected one of: {expected}); games must respond to touch on mobile"
    )
    return [
        LintFailure(
            rule="missing_touch_input",
            detail=detail,
            file=str(game_path.name),
        )
    ]
