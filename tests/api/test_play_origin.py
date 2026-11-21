"""Active game HTML must execute on the configured isolated origin."""
import pytest

from src.api.core.config import get_settings
from src.api.services.game_access import create_access


@pytest.mark.asyncio
@pytest.mark.parametrize("engine", ["godot", "bevy"])
async def test_play_redirect_and_secure_scoped_cookie(client, auth_user, tmp_path, monkeypatch, engine):
    settings = get_settings()
    root = tmp_path / "generated_games"
    game_id = engine + "-origin"
    project = root / game_id
    (project / "dist").mkdir(parents=True)
    (project / ("project.godot" if engine == "godot" else "Cargo.toml")).write_text("")
    (project / "dist/index.html").write_text("<html>isolated private game</html>")
    monkeypatch.setattr(settings, "GODOT_GAMES_DIR", str(root))
    monkeypatch.setattr(settings, "GAME_PLAY_ORIGIN", "https://games.example.test")
    create_access(game_id, str(auth_user.id), "private")
    from src.api.core.security import create_access_token

    token = create_access_token({"sub": str(auth_user.id)})
    path = f"/api/v1/{engine}/games/{game_id}/play"
    old = await client.get(path, params={"token": token})
    assert old.status_code == 307
    assert old.headers["location"].startswith("https://games.example.test" + path)
    destination = await client.get(old.headers["location"])
    assert destination.status_code == 307
    assert destination.headers["location"] == path + "/index.html"
    assert "HttpOnly" in destination.headers["set-cookie"]
    assert "Secure" in destination.headers["set-cookie"]
    assert "Max-Age=300" in destination.headers["set-cookie"]
    html = await client.get("https://games.example.test" + path + "/index.html")
    assert html.status_code == 200
    assert "no-store" in html.headers["cache-control"]
    app_html = await client.get(path + "/index.html", params={"token": token})
    assert app_html.status_code == 307
    assert app_html.headers["location"].startswith("https://games.example.test")
