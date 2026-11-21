import asyncio
from pathlib import Path
import uuid
import pytest

from src.api.core.config import get_settings
from src.api.services.bevy_builder import BevyBuilder
from src.api.services.bevy_game_service import BevyGameService
from src.api.services.browser_verification import verify_browser

pytestmark = pytest.mark.e2e


@pytest.mark.e2e
@pytest.mark.slow
def test_bevy_builder_produces_dist() -> None:
    # The real launcher only accepts direct children of its shared games root.
    # A pytest tmp_path is outside that allowlist and is not mounted in Docker.
    settings = get_settings()
    root = Path(settings.GODOT_GAMES_DIR).resolve()
    game_id = "bevy-e2e-" + uuid.uuid4().hex[:12]
    project = BevyGameService(settings).create_game(game_id, root)
    # Retain this uniquely named fixture and its verification receipt for review.
    # Starting from the application scaffold catches dependency/name drift that
    # the old underscore-only fixture did not exercise.
    assert not (project / "dist").exists()

    dist = BevyBuilder().build(project)

    assert dist == project / "dist"
    assert (dist / "index.html").exists()
    wasm = list(dist.glob("*_bg.wasm"))
    js = list(dist.glob("*.js"))
    assert len(wasm) == 1, f"expected one *_bg.wasm, got {wasm}"
    assert len(js) == 1, f"expected one *.js, got {js}"
    assert wasm[0].stat().st_size > 100_000, "wasm bundle suspiciously small"
    module = game_id
    assert wasm[0].name == module + "_bg.wasm"
    assert js[0].name == module + ".js"
    assert f"{module}.js" in (dist / "index.html").read_text()
    # Actual Wasm load/render smoke, not a full game or input-response test.
    assert asyncio.run(verify_browser(project, "bevy", [])) == []
