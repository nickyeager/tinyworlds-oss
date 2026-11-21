"""Godot game project lifecycle management.

Handles creating project directories, validating projects, reading skill
files, parsing build artifacts, and capturing screenshots / video.
"""
import asyncio
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from src.api.core.config import Settings
from src.api.services.failure_log import record_failure
from src.api.services.godot_export_lint import auto_patch_for_web_export, lint_for_web_export


# Playability assertion thresholds. Mirrors the client-side checks in
# .claude/skills/local/sync-walkthrough/scripts/walkthrough.py — keep in sync.
#
# We do NOT gate on scene size. A real game can have a tiny .tscn if the
# gameplay logic lives in an attached script — verified 2026-05-04 with a
# player-controlled ColorRect whose scene was 486 bytes but whose script ran
# input handling and viewport clamping. The signal of playability is "is there
# at least one real script with code, that handles input AND advances state".
_MIN_SCRIPT_BYTES = 50
_MIN_WASM_BYTES = 1_000_000
_AUTO_INJECTED_SCRIPTS = {"pause_bridge.gd"}

# Heuristics: at least one script must call into Godot's Input singleton or
# define an input signal handler, AND at least one must define _process /
# _physics_process. Catches the "static red square with attached but inert
# script" failure mode.
_INPUT_PATTERNS = (
    "Input.is_action",
    "Input.is_key",
    "Input.is_mouse",
    "Input.get_",            # get_vector, get_axis, get_action_strength, etc.
    "_input(",
    "_unhandled_input(",
    "_unhandled_key_input(",
)
_PROCESS_PATTERNS = (
    "func _process(",
    "func _physics_process(",
)
_MOBILE_INPUT_PATTERNS = (
    "InputEventScreenTouch",
    "InputEventScreenDrag",
    "TouchScreenButton",
    "DisplayServer.is_touchscreen_available",
    'OS.has_feature("mobile',
    "OS.has_feature('mobile",
    "InputEventMouseButton",
    "InputEventMouseMotion",
    "event is InputEventMouseButton",
    "event is InputEventMouseMotion",
    "Input.is_mouse_button_pressed",
    "screen_touch",
    "screen_drag",
)

logger = logging.getLogger(__name__)


class GodotGameService:
    """Manages Godot game project lifecycle.

    Responsibilities:
        - Initialise an empty, correctly structured Godot project directory
        - Run `godot --headless --quit` to validate the project
        - Read skill .md files for use as LLM system prompts
        - Read build artifacts (PLAN.md, STRUCTURE.md, ASSETS.md, MEMORY.md)
        - Enumerate existing games
        - Capture presentation video via `--write-movie` and ffmpeg
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Absolute path so read_skill() works regardless of cwd.
        # File is at src/api/services/godot_game_service.py -> parents[3] is repo root.
        repo_root = Path(__file__).resolve().parents[3]
        self.skills_path = repo_root / ".claude/skills/godogen/godot/skills/godogen"
        self.godot_binary = settings.GODOT_BINARY

    # ------------------------------------------------------------------
    # Project initialisation
    # ------------------------------------------------------------------

    def create_game(self, game_id: str, output_path: Path) -> Path:
        """Initialise an empty Godot project directory.

        Creates the standard TinyWorlds/godogen directory layout, a .gitignore,
        and initialises a git repository so each pipeline task can be committed
        incrementally.

        Args:
            game_id: Unique identifier used as the directory name.
            output_path: Parent directory under which the game folder is created.

        Returns:
            Path to the newly created game directory.
        """
        game_path = output_path / game_id
        game_path.mkdir(parents=True, exist_ok=True)

        # Standard godogen project layout
        (game_path / "scripts").mkdir(exist_ok=True)
        (game_path / "scenes").mkdir(exist_ok=True)
        (game_path / "test").mkdir(exist_ok=True)
        (game_path / "assets" / "img").mkdir(parents=True, exist_ok=True)
        (game_path / "assets" / "glb").mkdir(parents=True, exist_ok=True)
        (game_path / "screenshots").mkdir(exist_ok=True)

        # Godot ignores the screenshots directory during exports
        (game_path / "screenshots" / ".gdignore").touch()

        # Gitignore — skip generated/large assets and Godot import cache
        (game_path / ".gitignore").write_text(
            ".claude\nCLAUDE.md\nassets\nscreenshots\n.godot\n*.import\n",
            encoding="utf-8",
        )

        # Initialise git so tasks can be committed incrementally
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

        logger.info("Created Godot game project at %s", game_path)
        return game_path

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    async def validate_game(self, game_path: Path) -> Tuple[bool, str]:
        """Run `godot --headless --quit` to check for errors.

        Ignores benign RID / resource warnings that Godot emits even for
        valid projects.

        Args:
            game_path: Path to the Godot project directory.

        Returns:
            Tuple of (success, combined_output_string).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self.godot_binary, "--headless", "--quit",
                cwd=str(game_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            return False, "godot --headless --quit timed out after 60 seconds"
        except FileNotFoundError:
            return False, f"Godot binary not found: '{self.godot_binary}'"

        output = (
            stdout.decode("utf-8", errors="replace")
            + stderr.decode("utf-8", errors="replace")
        )

        has_error = False
        for line in output.split("\n"):
            if "SCRIPT ERROR" in line:
                has_error = True
                break
            stripped = line.strip()
            if (
                stripped.startswith("ERROR:")
                and "RID" not in line
                and "resource" not in line.lower()
            ):
                has_error = True
                break

        return (not has_error, output)

    # ------------------------------------------------------------------
    # Skill / artifact access
    # ------------------------------------------------------------------

    def read_skill(self, skill_name: str) -> str:
        """Read a skill .md file for use as an LLM system prompt.

        Searches the synced godogen skill tree first, then the local
        godot-modify skill as a fallback.

        Args:
            skill_name: Filename of the skill (e.g. "visual-target.md").

        Returns:
            File content as a string.

        Raises:
            FileNotFoundError: If the skill file cannot be located.
        """
        if skill_name == "SKILL.md":
            from src.api.services.executors.runtime import runtime_instructions

            return runtime_instructions("godot")
        skill_path = self.skills_path / skill_name
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")

        alt_path = self.skills_path.parents[3] / "local" / "godot-modify" / skill_name
        if alt_path.exists():
            return alt_path.read_text(encoding="utf-8")

        raise FileNotFoundError(
            f"Skill '{skill_name}' not found in {self.skills_path} "
            f"or {alt_path.parent}"
        )

    def read_name(self, game_path: Path) -> Optional[str]:
        """Return the game's display name from project.godot's `config/name`.

        The orchestrator skill writes this when scaffolding (e.g. "RedSquare").
        Returns None if project.godot is missing or has no config/name.
        """
        project_godot = game_path / "project.godot"
        if not project_godot.exists():
            return None
        text = project_godot.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'^config/name\s*=\s*"([^"]*)"', text, re.MULTILINE)
        if not m:
            return None
        name = m.group(1).strip()
        return name or None

    def write_name(self, game_path: Path, name: str) -> None:
        """Set the game's display name in project.godot's `config/name`.

        Raises FileNotFoundError if project.godot doesn't exist. Quotes inside
        the name are stripped to keep project.godot syntactically valid; we
        don't try to be clever about escaping.
        """
        project_godot = game_path / "project.godot"
        if not project_godot.exists():
            raise FileNotFoundError(f"project.godot not found at {project_godot}")
        sanitized = name.strip().replace('"', "")
        if not sanitized:
            raise ValueError("name cannot be empty")
        text = project_godot.read_text(encoding="utf-8", errors="replace")
        new_line = f'config/name="{sanitized}"'
        if re.search(r'^config/name\s*=\s*"[^"]*"', text, re.MULTILINE):
            text = re.sub(
                r'^config/name\s*=\s*"[^"]*"',
                new_line,
                text,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            # No existing config/name — insert under [application] (Godot's standard
            # location) or fall back to prepending if [application] is missing.
            if re.search(r'^\[application\]', text, re.MULTILINE):
                text = re.sub(
                    r'^\[application\]\s*\n',
                    f'[application]\n{new_line}\n',
                    text,
                    count=1,
                    flags=re.MULTILINE,
                )
            else:
                text = f"[application]\n{new_line}\n\n" + text
        project_godot.write_text(text, encoding="utf-8")

    def verify_playable(self, game_path: Path) -> List[str]:
        """Return a list of reasons why this game is not playable.

        Empty list = playable. The pipeline emits `CompletionEvent` whenever
        Claude self-reports done, even when it pivoted mid-flow and skipped
        scaffolding (verified failure mode 2026-05-04: C#→GDScript pivot left
        an empty project that exported successfully but had no scenes/scripts).

        We refuse to emit the SSE `done` event when this returns failures,
        emitting `failed` instead so clients can distinguish.

        Checks:
          - project.godot exists and declares run/main_scene
          - the main_scene file exists on disk
          - scripts/ has at least one real .gd or .cs file (>= MIN_SCRIPT_BYTES,
            excluding pause_bridge.gd which is auto-injected) — this is the
            real playability signal
          - at least one real script handles touch or pointer input so the
            exported game is playable on phones/tablets from the app
          - dist/index.wasm and dist/index.html exist
          - dist/index.wasm is real-sized (>= MIN_WASM_BYTES; real Godot wasm is ~37MB)
        """
        from src.api.services.game_access import ensure_no_symlinks
        ensure_no_symlinks(game_path)
        failures: List[str] = []

        project_godot = game_path / "project.godot"
        if not project_godot.exists():
            failures.append("project.godot missing")
            return failures

        text = project_godot.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'run/main_scene\s*=\s*"res://([^"]+)"', text)
        if not m:
            failures.append("project.godot has no run/main_scene")
        else:
            main_scene_rel = m.group(1)
            main_scene = game_path / main_scene_rel
            if not main_scene.exists():
                failures.append(f"main_scene file missing: {main_scene_rel}")

        scripts_dir = game_path / "scripts"
        real_scripts: List[Path] = []
        if scripts_dir.exists():
            for ext in (".gd", ".cs"):
                for p in scripts_dir.rglob(f"*{ext}"):
                    if p.name in _AUTO_INJECTED_SCRIPTS:
                        continue
                    if p.stat().st_size >= _MIN_SCRIPT_BYTES:
                        real_scripts.append(p)
        if not real_scripts:
            failures.append(
                "no real script files in scripts/ "
                "(only auto-injected helpers were found)"
            )
        else:
            # Prove the script(s) handle input AND advance state per frame.
            # An attached-but-inert script (no _process, no input handler) is
            # not a game.
            all_text = "\n".join(
                re.sub(r"(?m)#.*$", "", p.read_text(encoding="utf-8", errors="replace")) for p in real_scripts
            )
            if not any(pat in all_text for pat in _INPUT_PATTERNS):
                failures.append(
                    "no input handler found in any script "
                    "(expected Input.is_action_*, Input.is_key_*, or _input/_unhandled_input)"
                )
            if not any(pat in all_text for pat in _PROCESS_PATTERNS):
                failures.append(
                    "no update loop found in any script "
                    "(expected func _process(delta) or func _physics_process(delta))"
                )
            if not any(pat in all_text for pat in _MOBILE_INPUT_PATTERNS):
                failures.append(
                    "no mobile touch/pointer input fallback found in any script "
                    "(expected InputEventScreenTouch/InputEventScreenDrag, "
                    "TouchScreenButton, or mouse/pointer input handling)"
                )

        html = game_path / "dist" / "index.html"
        wasm = game_path / "dist" / "index.wasm"
        if not html.exists():
            failures.append("dist/index.html missing")
        if not wasm.exists():
            failures.append("dist/index.wasm missing")
        elif wasm.stat().st_size < _MIN_WASM_BYTES:
            failures.append(
                f"dist/index.wasm is too small "
                f"({wasm.stat().st_size} bytes < {_MIN_WASM_BYTES}) — broken export"
            )

        if wasm.is_file():
            with wasm.open("rb") as stream:
                if stream.read(8) != b"\x00asm\x01\x00\x00\x00":
                    failures.append("dist/index.wasm has an invalid WebAssembly header")
        if not (game_path / "dist/index.pck").is_file():
            failures.append("dist/index.pck missing")
        return failures

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
        """List Godot game directories under base_path.

        A directory is considered a Godot game if it contains a
        `project.godot` file.

        Args:
            base_path: Directory to scan for game projects.

        Returns:
            Sorted list of game directory names.
        """
        games: List[str] = []
        if not base_path.exists():
            return games
        for entry in base_path.iterdir():
            if entry.is_dir() and (entry / "project.godot").exists():
                games.append(entry.name)
        return sorted(games)

    # ------------------------------------------------------------------
    # Disk usage
    # ------------------------------------------------------------------

    def get_game_disk_size(self, game_path: Path) -> int:
        """Return total size in bytes of all files in a game directory.

        Args:
            game_path: Path to the Godot project directory.

        Returns:
            Total size in bytes, or 0 if the path does not exist.
        """
        if not game_path.exists():
            return 0
        return sum(f.stat().st_size for f in game_path.rglob("*") if f.is_file())

    # ------------------------------------------------------------------
    # Video capture
    # ------------------------------------------------------------------

    async def capture_video(
        self, game_path: Path, script_path: str
    ) -> Optional[Path]:
        """Record a presentation video using Godot's --write-movie flag.

        The AVI produced by Godot is transcoded to H.264 MP4 via ffmpeg
        and the intermediate AVI is deleted.

        Args:
            game_path: Path to the Godot project directory.
            script_path: Path to the presentation script (relative to game_path).

        Returns:
            Path to the MP4 file, or None if recording or conversion failed.
        """
        presentation_dir = game_path / "screenshots" / "presentation"
        presentation_dir.mkdir(parents=True, exist_ok=True)

        avi_path = presentation_dir / "gameplay.avi"
        mp4_path = presentation_dir / "gameplay.mp4"

        # Record AVI
        try:
            proc = await asyncio.create_subprocess_exec(
                self.godot_binary,
                "--write-movie", str(avi_path),
                "--fixed-fps", "30",
                "--script", script_path,
                cwd=str(game_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            logger.error("Godot --write-movie timed out for %s", game_path)
            return None
        except FileNotFoundError:
            logger.error("Godot binary not found: '%s'", self.godot_binary)
            return None

        if not avi_path.exists():
            logger.error("AVI not produced by godot --write-movie at %s", avi_path)
            return None

        # Convert AVI → MP4
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", str(avi_path),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                str(mp4_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            logger.error("ffmpeg conversion timed out for %s", avi_path)
            return None
        except FileNotFoundError:
            logger.error("ffmpeg not found — cannot convert AVI to MP4")
            return None

        if mp4_path.exists():
            avi_path.unlink(missing_ok=True)
            logger.info("Presentation video saved: %s", mp4_path)
            return mp4_path

        logger.error("ffmpeg did not produce MP4 at %s", mp4_path)
        return None

    # ------------------------------------------------------------------
    # HTML5 Web Export
    # ------------------------------------------------------------------

    def write_export_preset(self, game_path: Path) -> None:
        """Write export_presets.cfg for Web export.

        Always overwrites to ensure the export_path is an absolute path
        matching the resolved game directory.
        """
        abs_path = Path(game_path).resolve()
        export_target = str(abs_path / "dist" / "index.html")
        preset_path = abs_path / "export_presets.cfg"
        preset_path.write_text(
            '[preset.0]\n\n'
            'name="Web"\n'
            'platform="Web"\n'
            'runnable=true\n'
            'dedicated_server=false\n'
            'custom_features=""\n'
            'export_filter="all_resources"\n'
            'include_filter=""\n'
            'exclude_filter=""\n'
            f'export_path="{export_target}"\n\n'
            '[preset.0.options]\n\n'
            'variant/extensions_support=false\n'
            'variant/thread_support=0\n'
            'vram_texture_compression/for_desktop=true\n'
            'vram_texture_compression/for_mobile=true\n'
            'html/export_icon=true\n'
            'html/focus_canvas_on_start=true\n'
            'progressive_web_app/enabled=false\n'
        )
        logger.info("Wrote export_presets.cfg at %s (target: %s)", preset_path, export_target)

    # Both templates use a JS-side flag + per-frame poll. The `create_callback`
    # path silently failed in practice (listener attached but data never arrived).
    # Autoload is named `PauseBridge` (not `WebPause`) — the latter prevented the
    # autoload from running on web exports despite working in native (likely a
    # Godot 4 ClassDB shadowing — `Web*` is a busy namespace).
    _WEB_PAUSE_CS = '''using Godot;

public partial class PauseBridge : Node
{
    public override void _Ready()
    {
        ProcessMode = ProcessModeEnum.Always;
        if (!OS.HasFeature("web")) return;
        JavaScriptBridge.Eval(@"
            window.__godotPaused = false;
            window.addEventListener('message', function(e) {
                if (!e.data) return;
                if (e.data.action === 'pause')  window.__godotPaused = true;
                if (e.data.action === 'resume') window.__godotPaused = false;
            });
        ", true);
    }

    public override void _Process(double delta)
    {
        if (!OS.HasFeature("web")) return;
        var v = JavaScriptBridge.Eval("window.__godotPaused", true);
        GetTree().Paused = v.AsBool();
    }
}
'''

    _WEB_PAUSE_GD = '''extends Node

# Bridges parent-window postMessage to SceneTree pause via a JS flag polled per frame.

var _is_web := false

func _ready() -> void:
\tprocess_mode = Node.PROCESS_MODE_ALWAYS
\t_is_web = OS.has_feature("web")
\tif not _is_web:
\t\treturn
\tJavaScriptBridge.eval("""
\t\twindow.__godotPaused = false;
\t\twindow.addEventListener('message', function(e) {
\t\t\tif (!e.data) return;
\t\t\tif (e.data.action === 'pause')  window.__godotPaused = true;
\t\t\tif (e.data.action === 'resume') window.__godotPaused = false;
\t\t});
\t""", true)

func _process(_delta: float) -> void:
\tif not _is_web:
\t\treturn
\tvar v = JavaScriptBridge.eval("window.__godotPaused", true)
\tget_tree().paused = bool(v)
'''

    # Self-contained capture wrapper. Lifted verbatim from
    # .claude/skills/godogen/godot/skills/godogen/capture.md "Setup" block so
    # the runtime GPU/timeout detection happens at first invocation. Pre-
    # creating this file removes the dependency on Claude remembering to run
    # Setup; the lesson at .claude/skills/local/godogen-lessons/capture.md
    # documented a ~50% skip rate when Setup was deferred.
    _CAPTURE_RUN_GODOT = r"""#!/usr/bin/env bash
set -o pipefail
NVIDIA_ICD=/usr/share/vulkan/icd.d/nvidia_icd.json
NOISE="leaked RID|Leaked instance|ObjectDB instances"
cmd=()

# Linux without a display session -> xvfb
if [[ "$(uname -s)" != "Darwin" && -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    cmd+=(xvfb-run -a -s '-screen 0 1920x1080x24')
fi

# Renderer
if [[ "$(uname -s)" == "Darwin" ]]; then
    cmd+=(godot --path . --rendering-method forward_plus)
elif [[ -f "$NVIDIA_ICD" ]]; then
    cmd+=(env "VK_ICD_FILENAMES=$NVIDIA_ICD" godot --path . --rendering-method forward_plus)
elif command -v vulkaninfo &>/dev/null && vulkaninfo --summary 2>&1 | grep -Eq "deviceType *= PHYSICAL_DEVICE_TYPE_(DISCRETE_GPU|INTEGRATED_GPU|VIRTUAL_GPU)"; then
    cmd+=(godot --path . --rendering-method forward_plus)
else
    cmd+=(godot --path . --rendering-driver vulkan)
fi

"${cmd[@]}" "$@" 2>&1 | { grep -v "$NOISE" || true; }
"""

    def ensure_capture_wrapper(self, game_path: Path) -> None:
        """Pre-create `.capture/run_godot` and `.capture/env` so the capture
        skill can call `$TIMEOUT_CMD .capture/run_godot ...` without the agent
        having had to run the Setup block first.

        Detects GPU + timeout command at this Python call time and writes the
        results to `.capture/env`. Safe to call repeatedly — overwrites.
        """
        import shutil

        capture_dir = game_path / ".capture"
        capture_dir.mkdir(exist_ok=True)
        (capture_dir / ".gdignore").touch()

        # Timeout command — Linux has `timeout`, macOS has `gtimeout` if coreutils installed.
        timeout_cmd = shutil.which("timeout") or shutil.which("gtimeout") or "timeout"

        # GPU detection. Hardware GPU => video capture is feasible.
        gpu_available = False
        if sys.platform == "darwin":
            gpu_available = True  # Metal
        elif shutil.which("vulkaninfo"):
            try:
                result = subprocess.run(
                    ["vulkaninfo", "--summary"],
                    capture_output=True, text=True, timeout=5,
                )
                gpu_available = bool(
                    re.search(
                        r"deviceType\s*=\s*PHYSICAL_DEVICE_TYPE_(DISCRETE_GPU|INTEGRATED_GPU|VIRTUAL_GPU)",
                        result.stdout + result.stderr,
                    )
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                gpu_available = False

        run_godot = capture_dir / "run_godot"
        run_godot.write_text(self._CAPTURE_RUN_GODOT)
        run_godot.chmod(0o755)

        env_file = capture_dir / "env"
        env_file.write_text(
            f"GPU_AVAILABLE={'true' if gpu_available else 'false'}\n"
            f"TIMEOUT_CMD={timeout_cmd}\n"
        )

        # The capture skill also expects screenshots/ to exist with .gdignore.
        screenshots_dir = game_path / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)
        (screenshots_dir / ".gdignore").touch()

        logger.info(
            "capture wrapper ready at %s (GPU_AVAILABLE=%s, TIMEOUT_CMD=%s)",
            capture_dir, gpu_available, timeout_cmd,
        )

    def inject_web_pause(self, game_path: Path) -> None:
        """Drop a PauseBridge autoload into the project so the parent app can
        pause/resume the running game via window.postMessage.

        Detects project language: presence of any *.csproj → C#, otherwise GDScript.
        Self-heals if a previously-injected autoload mismatches the detected
        language (e.g. .cs autoload in a GDScript-only project) or uses the
        old `WebPause` autoload name (which silently failed on web exports).
        """
        project_file = game_path / "project.godot"
        if not project_file.exists():
            return
        content = project_file.read_text()

        is_csharp = any(game_path.glob("*.csproj"))
        wanted_path = "res://scripts/PauseBridge.cs" if is_csharp else "res://scripts/pause_bridge.gd"
        wanted_line = f'PauseBridge="*{wanted_path}"\n'

        # Already correct? skip.
        if wanted_line in content:
            return

        # Strip any stale autoload entry (old `WebPause` name OR `PauseBridge` mismatch).
        lines = [
            ln for ln in content.splitlines(keepends=True)
            if not (ln.startswith("WebPause=") or ln.startswith("PauseBridge="))
        ]
        content = "".join(lines)

        # Clean stale files from older injections (old name `WebPause` or
        # alternate language).
        scripts_dir = game_path / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        for stale in ("web_pause.gd", "web_pause.gd.uid", "WebPause.cs", "WebPause.cs.uid"):
            (scripts_dir / stale).unlink(missing_ok=True)
        if is_csharp:
            (scripts_dir / "pause_bridge.gd").unlink(missing_ok=True)
            (scripts_dir / "pause_bridge.gd.uid").unlink(missing_ok=True)
            (scripts_dir / "PauseBridge.cs").write_text(self._WEB_PAUSE_CS)
        else:
            (scripts_dir / "PauseBridge.cs").unlink(missing_ok=True)
            (scripts_dir / "PauseBridge.cs.uid").unlink(missing_ok=True)
            (scripts_dir / "pause_bridge.gd").write_text(self._WEB_PAUSE_GD)

        if "[autoload]" in content:
            content = content.replace("[autoload]\n", "[autoload]\n" + wanted_line)
        else:
            content += "\n[autoload]\n" + wanted_line
        project_file.write_text(content)
        logger.info(
            "Injected PauseBridge autoload (%s) into %s",
            "C#" if is_csharp else "GDScript",
            project_file,
        )

    def ensure_web_export_settings(self, game_path: Path) -> None:
        """Ensure project.godot has settings required for Web export."""
        project_file = game_path / "project.godot"
        if not project_file.exists():
            return
        content = project_file.read_text()

        additions = []
        if "import_s3tc_bptc" not in content:
            additions.append("textures/vram_compression/import_s3tc_bptc=true")
        if "import_etc2_astc" not in content:
            additions.append("textures/vram_compression/import_etc2_astc=true")
        if "gl_compatibility" not in content:
            additions.append('renderer/rendering_method="gl_compatibility"')
            additions.append('renderer/rendering_method.web="gl_compatibility"')

        if additions:
            # Append to the [rendering] section
            if "[rendering]" in content:
                content = content.replace(
                    "[rendering]\n",
                    "[rendering]\n" + "\n".join(additions) + "\n",
                )
            else:
                content += "\n[rendering]\n" + "\n".join(additions) + "\n"
            project_file.write_text(content)
            logger.info("Added web export settings to project.godot")

    async def export_html5(self, game_path: Path) -> Optional[Path]:
        """Export the Godot project to HTML5/WebAssembly.

        Returns:
            Path to the dist/ directory containing index.html, or None on failure.
        """
        from src.api.services.game_access import ensure_no_symlinks
        ensure_no_symlinks(game_path)
        abs_game_path = Path(game_path).resolve()
        self.ensure_web_export_settings(abs_game_path)
        self.inject_web_pause(abs_game_path)
        self.write_export_preset(abs_game_path)

        # Pre-export static lint. Catches forward_plus-only env features
        # (glow, filmic tonemap, SSAO, SDFGI, volumetric fog) being used
        # under gl_compatibility — the failure mode that hangs the WASM
        # thread silently in the browser. We log and continue rather than
        # block: the export still succeeds, but the failures are captured
        # so the orchestrator's retry loop and the failure log corpus see
        # them. If the failure is severe enough to actually break the game,
        # verify_playable + runtime telemetry will catch it.
        try:
            patched = auto_patch_for_web_export(abs_game_path)
            if patched:
                logger.warning(
                    "auto-patched forward_plus-only writes in %d file(s): %s",
                    len(patched), ", ".join(patched),
                )
            lint_failures = lint_for_web_export(abs_game_path)
        except Exception:
            logger.exception("export lint crashed for %s", abs_game_path)
            lint_failures = []
        for f in lint_failures:
            logger.warning("export lint: %s", f.as_message())
            record_failure(
                game_id=abs_game_path.name,
                engine="godot",
                stage="lint",
                rule=f.rule,
                detail=f.detail,
                file=f.file,
            )

        dist_dir = abs_game_path / "dist"
        dist_dir.mkdir(exist_ok=True)

        if getattr(self.settings, "AGENT_EXECUTION_MODE", "local") == "worker":
            from src.api.services.sidecar_launcher_client import export_godot
            result = await export_godot(str(abs_game_path))
            if result.ok and (dist_dir / "index.html").is_file():
                return dist_dir
            logger.error("Isolated Godot export failed (exit=%s): %s", result.returncode, result.stderr[-500:])
            return None

        export_target = str(dist_dir / "index.html")
        logger.info("HTML5 export: godot=%s, cwd=%s, target=%s",
                     self.godot_binary, abs_game_path, export_target)

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                self.godot_binary, "--headless",
                "--export-release", "Web", export_target,
                cwd=str(abs_game_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            logger.error("HTML5 export timed out for %s", abs_game_path)
            return None
        except FileNotFoundError:
            logger.error("Godot binary not found: '%s'", self.godot_binary)
            return None

        finally:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()

        index = dist_dir / "index.html"
        if proc.returncode == 0 and index.exists():
            logger.info("HTML5 export complete: %s", dist_dir)
            return dist_dir

        output = (stdout or b"").decode() + (stderr or b"").decode()
        logger.error("HTML5 export failed (exit=%s): %s", proc.returncode, output[-500:])
        return None
