#!/usr/bin/env python3
"""Load an existing private game through the real frontend and in-process API.

Uses real SQLite/JWT/user/access logic and exported artifacts. HTTP requests to
the backend are transported through ASGI; no live database, provider, or paid API
is used. The frontend must already be running. Example:
python scripts/verify_private_playback.py godot-123 --games-dir /path/generated_games
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from playwright.async_api import async_playwright
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.core.config import get_settings
from src.api.core.database import Base, get_db
from src.api.core.security import create_access_token, get_password_hash
from src.api.main import app
from src.api.models.user import User
from src.api.services.game_access import read_access


async def verify(args):
    settings = get_settings()
    settings.GODOT_GAMES_DIR = str(args.games_dir.resolve())
    settings.GAME_PLAY_ORIGIN = ""
    owner = read_access(args.game_id)
    if owner.visibility != "private" or not owner.owner_user_id:
        raise ValueError("Use an existing private game with a trusted owner")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        user = User(
            id=UUID(owner.owner_user_id),
            email="playback-probe@example.com",
            username="playback-probe",
            hashed_password=get_password_hash("disposable-test-only"),
            is_active=True,
            is_anonymous=False,
            is_admin=False,
        )
        db.add(user)
        await db.commit()

    async def database():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = database
    token = create_access_token({"sub": str(user.id)})
    requests = []
    try:
        async with (
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://localhost:8001",
                follow_redirects=False,
            ) as client,
            async_playwright() as playwright,
        ):
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
            )
            try:
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 900}
                )
                await context.add_init_script(
                    'localStorage.setItem("tinyworlds_access_token",'
                    + json.dumps(token)
                    + ');localStorage.setItem("tinyworlds_token_expiry",String(Date.now()+3600000));'
                )

                async def forward(route):
                    request = route.request
                    url = httpx.URL(request.url)
                    headers = await request.all_headers()
                    client.cookies.clear()  # Only the native browser may supply media cookies.
                    response = await client.request(
                        request.method,
                        url.raw_path.decode(),
                        headers=headers,
                        content=request.post_data_buffer,
                    )
                    requests.append(
                        (url.path, response.status_code, bool(headers.get("cookie")))
                    )
                    await route.fulfill(
                        status=response.status_code,
                        headers=dict(response.headers),
                        body=response.content,
                    )

                await context.route("http://localhost:8001/**", forward)
                page = await context.new_page()
                await page.goto(
                    args.web_url.rstrip("/")
                    + "/games/"
                    + args.game_id
                    + "?engine="
                    + args.engine
                )
                frame = page.frame_locator("iframe")
                try:
                    await frame.locator("canvas").wait_for(state="visible", timeout=60000)
                except Exception:
                    print("Playback request diagnostics:", requests, flush=True)
                    print("Page diagnostics:", await page.locator("body").inner_text(), flush=True)
                    await page.screenshot(path=str(args.screenshot), full_page=True)
                    raise
                await asyncio.sleep(4)
                wasm = [request for request in requests if request[0].endswith(".wasm")]
                assert wasm and all(
                    status == 200 and cookie for _, status, cookie in wasm
                ), wasm
                cookies = await context.cookies()
                assert any(
                    cookie["name"] == "tw_game_media" and cookie["httpOnly"]
                    for cookie in cookies
                )
                # Playback origin differs from parent; generated HTML cannot read login storage.
                isolated = await frame.locator("canvas").evaluate(
                    "() => {try {parent.localStorage.getItem('tinyworlds_access_token');return false;} catch(e) {return true;}}"
                )
                assert isolated, "Game can read the parent's login storage"
                await page.screenshot(path=str(args.screenshot), full_page=True)
                print(
                    "PASS: private native iframe loaded canvas/Wasm with its scoped HttpOnly cookie; real SQLite/JWT authorization; parent login storage isolated"
                )
            finally:
                await browser.close()
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_id")
    parser.add_argument("--games-dir", type=Path, required=True)
    parser.add_argument("--engine", choices=["godot", "bevy"], default="godot")
    parser.add_argument("--web-url", default="http://localhost:3333")
    parser.add_argument(
        "--screenshot", type=Path, default=Path("/tmp/tinyworlds-private-playback.png")
    )
    asyncio.run(verify(parser.parse_args()))
