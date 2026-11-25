"""Render one application contract and on-demand Godogen engine reference."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_ROOT = PROJECT_ROOT / "vendor" / "godogen-runtime"
UPSTREAM_COMMIT = "40542b6c8efbdc40112c2b004fbaa6d67141846d"
ENGINE_GUIDES = {"godot": "godot-gdscript.md", "bevy": "bevy.md"}


def runtime_instructions(engine: str) -> str:
    """Historical upstream reference for callers outside the native runtime."""
    if engine not in ENGINE_GUIDES:
        raise ValueError(f"Unsupported game engine: {engine}")
    return (RUNTIME_ROOT / "prompts/runtime.md").read_text() + "\n\n" + (RUNTIME_ROOT / "engines" / ENGINE_GUIDES[engine]).read_text()


def _write_inside(root: Path, relative: Path, content: str) -> None:
    target = root / relative
    if not target.resolve().is_relative_to(root) or target.is_symlink():
        raise ValueError(f"Runtime path escapes workspace: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def _archive_legacy_skills(root: Path) -> None:
    """Move old generated skill copies out of discovery, without deleting them.

    Only migrate workspaces carrying our runtime provenance. Keep custom contents
    within these old managed directories recoverable, and never follow symlinks.
    """
    provenance = root / '.runtime-provenance.json'
    if provenance.is_symlink() or not provenance.resolve().is_relative_to(root):
        raise ValueError('Runtime path escapes workspace: .runtime-provenance.json')
    if not provenance.exists():
        return
    previous = json.loads(provenance.read_text())
    if previous.get('context_revision', 0) >= 2 or previous.get('upstream') != UPSTREAM_COMMIT:
        return
    paths = [Path(prefix) / name for prefix in ('.agents/skills', '.claude/skills')
             for name in ('asset-gen', 'godot-modify', 'bevy-modify', 'local/godogen-lessons')]
    sources = [root / path for path in paths if (root / path).exists() or (root / path).is_symlink()]
    for source in sources:
        if source.is_symlink() or not source.resolve().is_relative_to(root) or any(p.is_symlink() for p in source.rglob('*')):
            raise ValueError(f'Runtime path escapes workspace: {source.relative_to(root)}')
    if sources:
        archive = root / '.tinyworlds-context-archive' / uuid.uuid4().hex
        _write_inside(root, archive.relative_to(root) / 'provenance.json', json.dumps(previous, indent=2))
        for source in sources:
            destination = archive / source.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))


def render_runtime(game_path: Path, *, engine: str, provider: str,
                   budget_cents: int | None, mode: str = 'create') -> Path:
    """Keep constraints once; paid-asset instructions exist only with a budget."""
    if engine not in ENGINE_GUIDES or provider not in {'claude', 'codex'} or mode not in {'create', 'modify'}:
        raise ValueError('Unsupported engine, provider or mode')
    root = game_path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    _archive_legacy_skills(root)
    from src.api.services.pip_bridge import REQUIREMENT, GODOT_HELPER
    if engine == 'godot':
        _write_inside(root, Path('tinyworlds_runtime/pip_bridge.gd'), GODOT_HELPER)
    skills = Path('.claude/skills' if provider == 'claude' else '.agents/skills')
    asset = skills / 'asset-gen'
    budget = max(0, budget_cents or 0)
    guide = (RUNTIME_ROOT / 'engines' / ENGINE_GUIDES[engine]).read_text()
    # Upstream's capture workflow is incompatible with the trusted app boundary.
    guide = guide.split('\n## Capture', 1)[0].rstrip() + '\n'
    _write_inside(root, Path(f'{engine}.md'), guide)
    contract = (
        f'# TinyWorlds {engine.title()} browser game\n\n'
        f'Implement the user request in this workspace. Use `{engine}.md` as an optional engine reference. '
        'These application rules take precedence over that reference.\n\n'
        '## Boundaries\n'
        'Stay inside this game. Never read application config, sibling games, provider keys or .env. '
        'Never call paid APIs directly. Upstream GPU/audio tools are not provisioned; do not install them.\n'
        f'Approved paid asset budget: {budget} cents total. Do not request additional spend. '
        + (f'For paid assets, read `{asset}/SKILL.md`.\n' if budget else 'Paid calls are disabled; use existing or procedural assets.\n')
        + '\n## Delivery\n'
        'Keep working mechanics, controls and user assets when editing. Read relevant existing source '
        'and project notes before changing them; do not re-scaffold an existing game. '
        'Support keyboard and mobile touch input. Keep instructions consistent with gameplay.\n'
        + ('Validate the edited source; the application performs the Web export after this turn.\n' if mode == 'modify' else 'Validate source/import errors and export the browser game to dist/.\n')
        + 'The application performs trusted browser verification and screenshots after this turn. '
        'Do not launch a browser, preview server or video capture inside the worker. '
        'Record that browser check as pending; never claim a pass before it runs.\n'
        'Keep concise project status in README.md and preserve existing project notes. '
        'Finish with what changed, how to play, and any requested work still incomplete.\n'
    )
    if engine == 'godot':
        contract += (
            '\nUse Godot 4 GDScript, Compatibility renderer and Web export (no C#/.NET or forward_plus features). '
            'For headless checks, use `--log-file "$PWD/.tinyworlds-godot.log"` so the sandbox can write the log. '
            'Use glyphs supported by the shipped font; default control labels should be ASCII.\n'
        )
    else:
        contract += (
            "\nUse Bevy/Rust, wasm32-unknown-unknown and dist/index.html with Wasm assets. "
            "Keep bevy = '=0.18.1' with webgl2 and wasm-bindgen = '=0.2.121', including Cargo.lock. "
            'Do not run cargo add bevy or upgrade the application toolchain; the trusted builder supplies wasm-bindgen-cli.\n'
        )
    manifest = Path('CLAUDE.md' if provider == 'claude' else 'AGENTS.md')
    _write_inside(root, manifest, contract + REQUIREMENT)
    asset_skill = (
        '---\nname: asset-gen\ndescription: Create broker-authorized images or GLBs when a paid budget is approved.\n---\n'
        '# Asset generation\n\nFollow the workspace runtime manifest for budget and isolation rules.\n'
        f"Images: `python {asset}/tools/asset_gen.py image --prompt '...' --output assets/img/name.png`. "
        'Use --image for an existing reference. Inspect the result before integrating it.\n'
        f'3D only when requested: `python {asset}/tools/asset_gen.py glb --image assets/img/character.png --output assets/models/character.glb`. '
        'Each new GLB reserves 25 cents. Retry the same input/output to resume a pending request without another paid submission. '
        'Import the model into the scene with suitable scale and collisions; meshes are not rigged or animated.\n'
        'Keep procedural/existing assets on failure or insufficient budget. Video is unsupported. '
        'Record asset paths, sources and broker-reported cost in README.md. '
        'Style guidance adapted from Godogen: establish the hero asset first, reuse references, '
        'specify palette/silhouette/in-game size, and inspect transparent edges against the game background.\n'
    )
    if budget:
        _write_inside(root, asset / 'SKILL.md', asset_skill)
    else:
        # A previously approved budget may have ended. Remove only our generated
        # skill metadata; the broker tool remains for compatibility and denies calls.
        for relative in (asset / 'SKILL.md', asset / 'agents/openai.yaml'):
            target = root / relative
            if target.is_symlink() or not target.resolve().is_relative_to(root):
                raise ValueError(f'Runtime path escapes workspace: {relative}')
            if target.exists():
                if relative.name != 'SKILL.md' or target.read_text() != asset_skill:
                    archive = Path('.tinyworlds-context-archive') / uuid.uuid4().hex / relative
                    _write_inside(root, archive, target.read_text())
                target.unlink()
    broker = PROJECT_ROOT / 'scripts/agent_asset_broker.py'
    _write_inside(root, asset / 'tools/asset_gen.py', broker.read_text() if broker.is_file() else "raise SystemExit('Trusted asset broker unavailable; paid calls denied')\n")
    hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (root / manifest, root / f'{engine}.md', root / asset / 'SKILL.md') if path.exists()}
    _write_inside(root, Path('.runtime-provenance.json'), json.dumps({
        'upstream': UPSTREAM_COMMIT, 'engine': engine, 'engine_guide': f'engines/{ENGINE_GUIDES[engine]}',
        'provider': provider, 'budget_cents': budget, 'pip_protocol': 1, 'context_revision': 2,
        'mode': mode, 'context_sha256': hashes,
    }, indent=2))
    return root / skills
