"""Exercise the real vendored runtime and its broker boundary on disk."""

import hashlib
import json
import os
import subprocess
import sys
import re
import tomllib

import pytest

from src.api.services.executors.runtime import (
    PROJECT_ROOT, RUNTIME_ROOT, UPSTREAM_COMMIT, render_runtime, runtime_instructions,
)


def test_upstream_files_match_recorded_source_hashes():
    hashes = json.loads((RUNTIME_ROOT / "SHA256SUMS.json").read_text())
    assert hashes
    for relative, digest in hashes.items():
        assert hashlib.sha256((RUNTIME_ROOT / relative).read_bytes()).hexdigest() == digest
    assert UPSTREAM_COMMIT in (RUNTIME_ROOT / "PROVENANCE.md").read_text()


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("engine,guide", [("godot", "godot-gdscript.md"), ("bevy", "bevy.md")])
def test_rendered_runtime_uses_native_guide_and_only_broker(tmp_path, provider, engine, guide):
    skills = render_runtime(tmp_path, engine=engine, provider=provider, budget_cents=50)
    assert (tmp_path / f"{engine}.md").read_bytes() == (RUNTIME_ROOT / "engines" / guide).read_bytes()
    assert (RUNTIME_ROOT / "engines" / guide).read_text() in runtime_instructions(engine)
    asset = skills / "asset-gen"
    assert not (asset / "api.md").exists()
    assert (asset / "tools/asset_gen.py").read_bytes() == (PROJECT_ROOT / "scripts/agent_asset_broker.py").read_bytes()
    manifest = tmp_path / ("CLAUDE.md" if provider == "claude" else "AGENTS.md")
    text = manifest.read_text()
    assert "${" not in text
    assert "50 cents" in text
    assert "not provisioned" in text
    assert f"python {asset.relative_to(tmp_path)}/tools/asset_gen.py image" in text
    # Exercise the actual tool, with no credentials/job token or broker available.
    result = subprocess.run(
        [sys.executable, str(asset / "tools/asset_gen.py"), "image", "--prompt", "test", "--output", "assets/test.png"],
        cwd=tmp_path, env={"PATH": os.environ.get("PATH", "")},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode != 0
    assert not (tmp_path / "assets/test.png").exists()
    assert json.loads(result.stdout)["ok"] is False


def test_renderer_rejects_symlink_escape(tmp_path):
    workspace = tmp_path / "game"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / ".agents").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes workspace"):
        render_runtime(workspace, engine="godot", provider="codex", budget_cents=0)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_bevy_scaffold_and_runtime_match_builder_bindings(tmp_path, provider):
    from src.api.core.config import Settings
    from src.api.services.bevy_game_service import BevyGameService

    game = BevyGameService(Settings()).create_game("bevy-pin-check", tmp_path)
    dependencies = tomllib.loads((game / "Cargo.toml").read_text())["dependencies"]
    image = (PROJECT_ROOT / "Dockerfile.bevy-builder").read_text()
    version = re.search(r"^ARG WASM_BINDGEN_VERSION=(\S+)$", image, re.MULTILINE).group(1)
    assert dependencies["wasm-bindgen"] == "=" + version
    render_runtime(game, engine="bevy", provider=provider, budget_cents=0)
    text = (game / ("CLAUDE.md" if provider == "claude" else "AGENTS.md")).read_text()
    assert f"wasm-bindgen = '={version}'" in text
    assert f"bevy = '{dependencies['bevy']['version']}'" in text
    assert "Do not run cargo add bevy" in text


def test_trusted_upstream_image_cli_accepts_launcher_arguments():
    result = subprocess.run(
        [sys.executable, str(RUNTIME_ROOT / "asset-gen/tools/asset_gen.py"), "image", "--help"],
        env={"PATH": os.environ.get("PATH", "")}, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    for option in ("--prompt", "--model", "--size", "--aspect-ratio", "--output", "--image"):
        assert option in result.stdout
