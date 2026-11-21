"""Disposable real API/SQLite server used by plugin integration tests."""

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.api.main import app  # noqa: E402
from src.api.core.database import init_db, AsyncSessionLocal  # noqa: E402
from src.api.core.security import get_password_hash  # noqa: E402
from src.api.models.user import User  # noqa: E402
from src.api.services.game_access import create_access  # noqa: E402
from tests.fixtures.images import png_bytes  # noqa: E402


async def seed():
    await init_db()
    async with AsyncSessionLocal() as db:
        owner = User(
            email="plugin-owner@example.com",
            username="pluginowner",
            hashed_password=get_password_hash("local-plugin-test-password"),
            full_name="Plugin Owner",
        )
        other = User(
            email="plugin-other@example.com",
            username="pluginother",
            hashed_password=get_password_hash("local-plugin-test-password"),
            full_name="Other Account",
        )
        db.add_all([owner, other])
        await db.commit()
        await db.refresh(owner)
        await db.refresh(other)
        base = Path(os.environ["GODOT_GAMES_DIR"])
        for target in ("godot", "bevy"):
            game_id = target + "-pluginfixture"
            project = base / game_id
            project.mkdir(parents=True)
            if target == "godot":
                (project / "project.godot").write_text(
                    'config_version=5\n[application]\nconfig/name="Plugin Fixture"\n'
                )
            else:
                (project / "Cargo.toml").write_text(
                    '[package]\nname="plugin_fixture"\nversion="0.1.0"\nedition="2024"\n'
                )
            create_access(game_id, str(owner.id), "private")
            log = project / ".creation"
            log.mkdir()
            (log / "events.jsonl").write_text(
                json.dumps({"event_type": "init", "game_id": game_id, "engine": target})
                + "\n"
            )
            (log / "summary.json").write_text(json.dumps({"status": "success"}))
            screenshots = project / "screenshots"
            screenshots.mkdir()
            # Exercise actual media serving with owned, deterministic bytes;
            # integration tests must not depend on a private generated game.
            (screenshots / "screenshot.png").write_bytes(png_bytes())
            (screenshots / "presentation").mkdir()
            (screenshots / "presentation/gameplay.png").write_bytes(png_bytes())
        (base.parent / "fixture-users.json").write_text(
            json.dumps({"owner": str(owner.id), "other": str(other.id)})
        )


if __name__ == "__main__":
    asyncio.run(seed())
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ["PLUGIN_TEST_API_PORT"]),
        access_log=False,
    )
