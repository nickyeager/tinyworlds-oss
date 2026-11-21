"""Render the pinned upstream docs runtime into one isolated game workspace."""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_ROOT = PROJECT_ROOT / "vendor" / "godogen-runtime"
UPSTREAM_COMMIT = "40542b6c8efbdc40112c2b004fbaa6d67141846d"
ENGINE_GUIDES = {"godot": "godot-gdscript.md", "bevy": "bevy.md"}


def runtime_instructions(engine: str) -> str:
    """Return current upstream orchestration and engine guidance."""
    if engine not in {"godot", "bevy"}:
        raise ValueError(f"Unsupported game engine: {engine}")
    return (
        (RUNTIME_ROOT / "prompts/runtime.md").read_text()
        + "\n\n"
        + (RUNTIME_ROOT / "engines" / ENGINE_GUIDES[engine]).read_text()
    )


def _write_inside(root: Path, relative: Path, content: str) -> None:
    target = root / relative
    if not target.resolve().is_relative_to(root) or target.is_symlink():
        raise ValueError(f"Runtime path escapes workspace: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def render_runtime(
    game_path: Path, *, engine: str, provider: str, budget_cents: int | None
) -> Path:
    """Install native runtime docs with application constraints and no paid keys."""
    if engine not in {"godot", "bevy"} or provider not in {"claude", "codex"}:
        raise ValueError("Unsupported engine or provider")
    root = game_path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    from src.api.services.pip_bridge import REQUIREMENT, GODOT_HELPER
    if engine == "godot":
        _write_inside(root, Path("tinyworlds_runtime/pip_bridge.gd"), GODOT_HELPER)
    skills = Path(".claude/skills" if provider == "claude" else ".agents/skills")
    skill_dir = skills / "asset-gen"
    replacements = {
        "ENGINE_NAME": engine.title(),
        "ENGINE_GUIDE_FILE": f"{engine}.md",
        "AGENT_NAME": "Claude" if provider == "claude" else "Codex",
        "ASSET_GEN_SKILL_DIR": str(skill_dir),
        "RUNTIME_ASSET_DIR": "assets",
        "ASSET_SKILL_COMMAND": "/asset-gen" if provider == "claude" else "$asset-gen",
    }

    def render(text: str) -> str:
        for key, value in replacements.items():
            text = text.replace("${" + key + "}", value)
        return text

    # Keep the full upstream package in vendor, but publish only the broker
    # protocol into agent workspaces. Upstream api.md/tools require raw keys;
    # the new local pipeline requires a separately provisioned GPU checkout.
    _write_inside(
        root, Path(f"{engine}.md"),
        (RUNTIME_ROOT / "engines" / ENGINE_GUIDES[engine]).read_text()
    )
    budget = max(0, budget_cents or 0)
    overlay = (
        "\n\n## TinyWorlds execution constraints (override upstream defaults)\n"
        f"Provider: {provider}. Engine: {engine}. Approved paid asset budget: {budget} cents. "
        "This is the caller-approved total cap; never ask for additional spend during this job. "
        "Zero budget forbids paid calls. All paid assets MUST use the trusted broker tool: "
        f"`python {skill_dir}/tools/asset_gen.py image --prompt '...' --output assets/img/name.png`. "
        "The broker also supports remote TRELLIS.2 image-to-3D: "
        f"`python {skill_dir}/tools/asset_gen.py glb --image assets/img/character.png --output assets/models/character.glb`. "
        "Each new 512-resolution GLB reserves 25 cents from the same approved budget. "
        "Use an existing uploaded/drawn or generated game image as input. Never use GLBs for a 2D game unless a 3D change is requested. "
        "For a 3D request, generate and import the GLB into the scene; a file alone is not completion. "
        "Keep gameplay/collisions stable; these meshes are not rigged or animated. "
        "On pending/failure, retry the same image and output to resume without another paid submission. "
        "Keep the current cutout/procedural asset on failure or insufficient budget and report it accurately. "
        "Video generation remains unsupported. Never call paid APIs directly. "
        "Never request or read third-party keys, application config, sibling games, or .env. "
        "Use procedural assets when the broker is unavailable.\n"
        "The upstream godogen_assets checkout and its GPU/audio tools are not provisioned here. "
        "Do not install or invoke them, or switch engines to use another upstream guide.\n"
        "The deliverable is a playable browser game: export web artifacts to dist/. "
        "Provide mobile touch controls as well as keyboard input. The application runs trusted browser verification after your turn. "
        "Implement the game, check source/import errors, export dist/, update README.md, and finish your turn. "
        "Do not launch Chromium, Playwright, a browser server, or video capture: those cannot run reliably inside the CLI sandbox. "
        "Record browser verification as pending the application's smoke test. This application boundary overrides upstream capture/playtest requirements.\n"
        "Capture artifacts must remain compatible: screenshots/result/0/video.mp4 and screenshot.png; "
        "use .capture/run_godot when present. Preserve STRUCTURE.md, MEMORY.md, PLAN.md and README.md context.\n"
        f"Read relevant project lessons in {skills}/local/godogen-lessons/.\n"
    )
    if engine == "godot":
        overlay += (
            "Use Godot 4 GDScript, Compatibility renderer and Web export; C#/.NET cannot run in this browser target.\n"
            "Use only glyphs included in the shipped UI font. With the default font, prefer ASCII control labels "
            "such as LEFT, RIGHT and JUMP over arrow symbols; keep helper text consistent when goal colors change.\n"
        )
    else:
        overlay += (
            "Use Bevy/Rust, build wasm32-unknown-unknown and deliver dist/index.html with its Wasm assets. "
            "Preserve the application toolchain pins: bevy = '=0.18.1' with webgl2 and "
            "wasm-bindgen = '=0.2.121'. Do not run cargo add bevy to select the latest release; "
            "this overrides the upstream engine guide. Keep Cargo.lock consistent with these pins. "
            "The trusted application builder supplies matching wasm-bindgen-cli; do not upgrade it inside a game.\n"
        )
    manifest = "CLAUDE.md" if provider == "claude" else "AGENTS.md"
    _write_inside(
        root,
        Path(manifest),
        render((RUNTIME_ROOT / "prompts/runtime.md").read_text()) + overlay + REQUIREMENT,
    )
    # The upstream source stays unchanged in vendor; the published skill points only to the broker.
    _write_inside(
        root,
        skill_dir / "SKILL.md",
        "---\nname: asset-gen\ndescription: Generate images and remote TRELLIS.2 GLBs through the trusted budget broker.\n---\n# Asset generation\n"
        + overlay
        + "\n## Image planning and review (adapted from upstream asset-gen)\n"
        "Start with the hero asset to establish the visual style. Reuse a generated image "
        "as a broker --image reference for related assets so the family stays consistent. "
        "Specify the intended in-game dimensions, silhouette, palette and background in the prompt. "
        "Choose dimensions for the game's camera rather than generating unnecessarily large images.\n"
        "Inspect each generated PNG before building on it. Check silhouettes, sprite alignment "
        "and transparent edges against the actual game background; a successful API response "
        "does not establish visual quality. If image inspection is unavailable, record it as unverified. "
        "Use procedural geometry for assets whose shape or articulation must be exact.\n"
        "Keep an asset manifest in README.md with each path, role, intended in-game size, "
        "source/reference and broker-reported cost. Record generation inputs outside the runtime "
        "assets directory. Browser appearance remains pending the trusted application check.\n",
    )
    for name in (
        "general.md",
        "scaffold.md",
        "scripts.md",
        "scenes.md",
        "assets.md",
        "capture.md",
        "playthrough.md",
        "bevy.md",
    ):
        source = PROJECT_ROOT / ".claude/skills/local/godogen-lessons" / name
        if source.exists():
            _write_inside(
                root, skills / "local/godogen-lessons" / name, source.read_text()
            )
    source = PROJECT_ROOT / f".claude/skills/local/{engine}-modify/SKILL.md"
    if source.exists():
        _write_inside(
            root, skills / f"{engine}-modify/SKILL.md", source.read_text() + overlay + REQUIREMENT
        )
    if provider == "codex":
        _write_inside(
            root,
            skill_dir / "agents/openai.yaml",
            'interface:\n  display_name: "Asset Generator"\n  short_description: "Generate images through the trusted budget broker"\n  default_prompt: "Use $asset-gen to generate broker-authorized game images."\npolicy:\n  allow_implicit_invocation: true\n',
        )
    broker_tool = PROJECT_ROOT / "scripts/agent_asset_broker.py"
    if broker_tool.is_file():
        _write_inside(root, skill_dir / "tools/asset_gen.py", broker_tool.read_text())
    else:
        _write_inside(
            root,
            skill_dir / "tools/asset_gen.py",
            "raise SystemExit('Trusted asset broker is unavailable; paid calls denied')\n",
        )
    _write_inside(
        root,
        Path(".runtime-provenance.json"),
        json.dumps(
            {
                "upstream": UPSTREAM_COMMIT,
                "engine": engine,
                "engine_guide": f"engines/{ENGINE_GUIDES[engine]}",
                "provider": provider,
                "budget_cents": budget,
                "pip_protocol": 1,
            }
        ),
    )
    return root / skills
