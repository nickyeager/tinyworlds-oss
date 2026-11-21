"""Bevy game project lifecycle management.

Mirrors :mod:`src.api.services.godot_game_service` where it makes sense and
diverges where Bevy is structurally different. The actual cargo + wasm-bindgen
+ wasm-opt build pipeline lives in :class:`BevyBuilder` — this service only
handles project scaffolding, lifecycle artifacts, and verification.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import List, Optional

from src.api.core.config import Settings
from src.api.services.bevy_builder import BevyBuilder

logger = logging.getLogger(__name__)


_CARGO_TOML_TEMPLATE = """[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

[dependencies]
bevy = {{ version = "=0.18.1", features = ["webgl2"] }}
# Must match WASM_BINDGEN_VERSION in Dockerfile.bevy-builder.
wasm-bindgen = "=0.2.121"

[profile.release]
opt-level = "z"
lto = "thin"
codegen-units = 1
strip = true
"""

_MAIN_RS_TEMPLATE = """use bevy::prelude::*;

fn main() {
    App::new()
        .add_plugins(DefaultPlugins)
        .add_systems(Startup, setup)
        .run();
}

fn setup(mut commands: Commands) {
    commands.spawn(Camera2d);
    commands.spawn(Sprite::from_color(
        Color::srgb(0.25, 0.75, 0.95),
        Vec2::new(120.0, 120.0),
    ));
}
"""

_GITIGNORE = "target/\ndist/\n.build-cache/\n.claude\nCLAUDE.md\nscreenshots\n"

_MOBILE_INPUT_PATTERNS = (
    "Touches",
    "TouchInput",
    "TouchPhase",
    "touches.",
    "touch_input",
    "CursorMoved",
    "MouseButton",
    "ButtonInput<MouseButton>",
    "Interaction::Pressed",
    "Changed<Interaction>",
    "Pointer",
    "On<Pointer",
    "bevy::picking",
    "cursor_position",
    "viewport_to_world",
)


def _sanitize_crate_name(game_id: str) -> str:
    """Cargo crate names allow only [a-z0-9_-]. Lowercase + replace others with '_'."""
    lowered = game_id.lower()
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in lowered)


class BevyGameService:
    """Manages Bevy game project lifecycle.

    Responsibilities:
        - Initialise an empty Bevy crate that compiles cleanly under
          :class:`BevyBuilder`.
        - Read skill .md files for use as LLM system prompts.
        - Read/write the display name (kept in `[package.metadata.tinyworlds]`
          since Cargo crate names cannot encode arbitrary strings).
        - Read build artifacts (PLAN.md, STRUCTURE.md, ASSETS.md, MEMORY.md).
        - Enumerate existing games and report playability failures.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Absolute path so read_skill() works regardless of cwd.
        # File is at src/api/services/bevy_game_service.py -> parents[3] is repo root.
        repo_root = Path(__file__).resolve().parents[3]
        self.skills_path = repo_root / ".claude/skills/godogen/bevy/skills/godogen"
        self.builder = BevyBuilder()

    # ------------------------------------------------------------------
    # Project initialisation
    # ------------------------------------------------------------------

    def create_game(self, game_id: str, output_path: Path) -> Path:
        """Initialise an empty Bevy crate.

        Writes Cargo.toml, src/main.rs, .gitignore, and runs `git init` so
        the creation agent can commit pipeline tasks incrementally.

        Args:
            game_id: Unique identifier used as the directory name. Sanitised
                to a valid Cargo crate name for the `name = ...` field.
            output_path: Parent directory under which the game folder is created.

        Returns:
            Path to the newly created game directory.
        """
        game_path = output_path / game_id
        game_path.mkdir(parents=True, exist_ok=True)

        (game_path / "src").mkdir(exist_ok=True)

        crate_name = _sanitize_crate_name(game_id)
        (game_path / "Cargo.toml").write_text(
            _CARGO_TOML_TEMPLATE.format(name=crate_name),
            encoding="utf-8",
        )
        (game_path / "src" / "main.rs").write_text(_MAIN_RS_TEMPLATE, encoding="utf-8")
        (game_path / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")

        # Initialise git so tasks can be committed incrementally. Lenient on
        # failure to match the Godot service's behaviour.
        result = subprocess.run(
            ["git", "init"],
            cwd=str(game_path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(
                "git init failed for %s: %s", game_path, result.stderr.strip()
            )

        logger.info("Created Bevy game project at %s", game_path)
        return game_path

    # ------------------------------------------------------------------
    # Skill / artifact access
    # ------------------------------------------------------------------

    def read_skill(self, skill_name: str) -> str:
        """Read a Bevy skill .md file for use as an LLM system prompt.

        Args:
            skill_name: Filename of the skill (e.g. "scaffold.md").

        Returns:
            File content as a string.

        Raises:
            FileNotFoundError: If the skill file cannot be located.
        """
        if skill_name == "SKILL.md":
            from src.api.services.executors.runtime import runtime_instructions

            return runtime_instructions("bevy")
        skill_path = self.skills_path / skill_name
        if not skill_path.exists():
            raise FileNotFoundError(
                f"Skill '{skill_name}' not found in {self.skills_path}"
            )
        return skill_path.read_text(encoding="utf-8")

    def read_name(self, game_path: Path) -> Optional[str]:
        """Return the game's display name from `[package.metadata.tinyworlds]`.

        Cargo crate names cannot encode spaces or capitals, so the display
        name is parked in a metadata table. Returns None if Cargo.toml is
        missing or has no `display_name` under the metadata section.
        """
        cargo_toml = game_path / "Cargo.toml"
        if not cargo_toml.exists():
            return None
        text = cargo_toml.read_text(encoding="utf-8", errors="replace")

        section_re = re.compile(r"^\[package\.metadata\.tinyworlds\]\s*$", re.MULTILINE)
        m = section_re.search(text)
        if not m:
            return None

        # Scan lines after the section header until we hit another section.
        rest = text[m.end():]
        for line in rest.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                break
            dm = re.match(r'display_name\s*=\s*"([^"]*)"', stripped)
            if dm:
                name = dm.group(1).strip()
                return name or None
        return None

    def write_name(self, game_path: Path, name: str) -> None:
        """Set the game's display name in `[package.metadata.tinyworlds]`.

        Raises FileNotFoundError if Cargo.toml doesn't exist. Quotes inside
        the name are stripped to keep Cargo.toml syntactically valid.
        """
        cargo_toml = game_path / "Cargo.toml"
        if not cargo_toml.exists():
            raise FileNotFoundError(f"Cargo.toml not found at {cargo_toml}")
        sanitized = name.strip().replace('"', "")
        if not sanitized:
            raise ValueError("name cannot be empty")

        text = cargo_toml.read_text(encoding="utf-8", errors="replace")
        new_line = f'display_name = "{sanitized}"'
        section_header = "[package.metadata.tinyworlds]"

        if section_header in text:
            # Section exists. Replace existing display_name or insert under header.
            existing_re = re.compile(
                r'^display_name\s*=\s*"[^"]*"',
                re.MULTILINE,
            )
            # Limit replacement to lines following the section header until next section.
            section_idx = text.index(section_header)
            after_header = text[section_idx + len(section_header):]
            # Find next section, if any.
            next_section_match = re.search(r'^\[', after_header[1:], re.MULTILINE)
            if next_section_match:
                # +1 because we sliced off the leading newline character above.
                section_end = section_idx + len(section_header) + 1 + next_section_match.start()
            else:
                section_end = len(text)
            section_body = text[section_idx + len(section_header):section_end]

            if existing_re.search(section_body):
                new_body = existing_re.sub(new_line, section_body, count=1)
            else:
                # Insert directly under the section header.
                if section_body.startswith("\n"):
                    new_body = "\n" + new_line + section_body
                else:
                    new_body = "\n" + new_line + "\n" + section_body
            text = text[:section_idx + len(section_header)] + new_body + text[section_end:]
        else:
            if not text.endswith("\n"):
                text += "\n"
            text += f"\n{section_header}\n{new_line}\n"

        cargo_toml.write_text(text, encoding="utf-8")

    def read_artifact(self, game_path: Path, name: str) -> Optional[str]:
        """Read a build artifact file if it exists.

        Typically used for PLAN.md, STRUCTURE.md, ASSETS.md, MEMORY.md.

        Args:
            game_path: Path to the game project directory.
            name: Filename of the artifact.

        Returns:
            File content as a string, or None if the file does not exist.
        """
        path = game_path / name
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    # ------------------------------------------------------------------
    # Game enumeration
    # ------------------------------------------------------------------

    def list_games(self, base_path: Path) -> List[str]:
        """List Bevy game directories under base_path.

        A directory is considered a Bevy game if it contains a `Cargo.toml`.

        Args:
            base_path: Directory to scan for game projects.

        Returns:
            Sorted list of game directory names.
        """
        games: List[str] = []
        if not base_path.exists():
            return games
        for entry in base_path.iterdir():
            if entry.is_dir() and (entry / "Cargo.toml").exists():
                games.append(entry.name)
        return sorted(games)

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_playable(self, game_path: Path) -> List[str]:
        """Return a list of reasons why this game is not playable.

        Empty list = playable. Mirrors the Godot service's "list of failure
        reasons" shape so the future creation agent can stay engine-shaped.

        Checks:
          - Cargo.toml exists
          - src/main.rs exists
          - dist/index.html exists
          - dist/*_bg.wasm exists (any one match — wasm-bindgen output)
          - dist/*.js exists (the wasm-bindgen JS shim)
          - source handles touch or pointer input so the game is mobile-playable
        """
        from src.api.services.game_access import ensure_no_symlinks
        ensure_no_symlinks(game_path)
        failures: List[str] = []

        if not (game_path / "Cargo.toml").exists():
            failures.append("Cargo.toml missing")
        if not (game_path / "src" / "main.rs").exists():
            failures.append("src/main.rs missing")
        else:
            source_text = "\n".join(
                p.read_text(encoding="utf-8", errors="replace")
                for p in (game_path / "src").rglob("*.rs")
                if p.is_file()
            )
            if not any(pat in source_text for pat in _MOBILE_INPUT_PATTERNS):
                failures.append(
                    "no mobile touch/pointer input fallback found in Bevy source "
                    "(expected Touches/TouchInput, MouseButton, CursorMoved, "
                    "Interaction::Pressed, or pointer input handling)"
                )

        dist = game_path / "dist"
        if not (dist / "index.html").exists():
            failures.append("dist/index.html missing")
        if not dist.exists() or not any(dist.glob("*_bg.wasm")):
            failures.append("dist/*_bg.wasm missing")
        if not dist.exists() or not any(dist.glob("*.js")):
            failures.append("dist/*.js missing")

        for wasm in dist.glob("*_bg.wasm"):
            with wasm.open("rb") as stream:
                if stream.read(8) != b"\x00asm\x01\x00\x00\x00":
                    failures.append(f"{wasm.name} has an invalid WebAssembly header")
        return failures

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_wasm(self, game_path: Path) -> Path:
        """Build the project to WebAssembly via :class:`BevyBuilder`.

        Args:
            game_path: Path to the Bevy project directory.

        Returns:
            Path to the produced `dist/` directory.

        Raises:
            FileNotFoundError: If Cargo.toml is missing (checked here so
                tests don't need docker to validate the precondition).
            RuntimeError: If post-build WASM validation finds value-type
                bytes outside the browser-safe set. This catches the
                wasm-opt `--all-features` failure mode where the optimizer
                emitted typed-references/GC bytes that Chrome's V8 rejects.
        """
        if not (game_path / "Cargo.toml").exists():
            raise FileNotFoundError(f"no Cargo.toml in {game_path}")
        dist = self.builder.build(game_path)

        # Pre-flight: scan the produced WASM for browser-unsafe value-type
        # bytes. Logged into the failure corpus so the passive learning
        # loop sees it; raised so the modify/create pipelines fail loudly
        # instead of silently shipping a black-canvas game.
        from src.api.services.failure_log import record_failure
        from src.api.services.wasm_validate import validate_file

        wasm_files = list(dist.glob("*_bg.wasm"))
        if wasm_files:
            issues = validate_file(wasm_files[0])
            unsafe = [i for i in issues if i.byte not in (0x00,)]
            if unsafe:
                detail = "; ".join(str(i) for i in unsafe[:5])
                if len(unsafe) > 5:
                    detail += f"; ... +{len(unsafe) - 5} more"
                record_failure(
                    game_id=game_path.name,
                    engine="bevy",
                    stage="lint",
                    rule="wasm_browser_unsafe_value_type",
                    detail=detail,
                    file=str(wasm_files[0].relative_to(game_path)),
                )
                raise RuntimeError(
                    f"WASM contains browser-unsafe value-type bytes: {detail}"
                )
        return dist

    # ------------------------------------------------------------------
    # Capture paths
    # ------------------------------------------------------------------
    # Contract: these return the canonical proof-artifact location, mirroring
    # the Godot service. Bevy's upstream capture skill writes to
    # screenshots/result/{N}/ instead, so the Bevy creation agent (Workstream 4)
    # is responsible for copying the latest result/{N}/ artifacts into
    # screenshots/presentation/ — same way the Godot orchestrator does.

    def screenshot_path(self, game_path: Path) -> Path:
        """Canonical presentation screenshot. See contract note above."""
        return game_path / "screenshots" / "presentation" / "gameplay.png"

    def video_path(self, game_path: Path) -> Path:
        """Canonical presentation video. See contract note above."""
        return game_path / "screenshots" / "presentation" / "gameplay.mp4"
