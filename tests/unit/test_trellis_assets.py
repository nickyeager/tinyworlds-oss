"""Paid-call boundaries, retries and engine-safe output; no live API calls."""
import io
import json
import struct

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from src.api import sidecar_launcher as launcher
from src.api.services import trellis_assets as trellis
from src.api.services.game_asset_budget import AssetBudgetLedger


def png():
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def glb(document=None):
    content = json.dumps(document or {"meshes": [{}], "buffers": [{"byteLength": 0}]}).encode()
    content += b" " * (-len(content) % 4)
    return struct.pack("<4sIII4s", b"glTF", 2, len(content) + 20, len(content), b"JSON") + content


@pytest.mark.asyncio
async def test_resume_does_not_submit_or_charge_again(tmp_path, monkeypatch):
    ledger = AssetBudgetLedger(tmp_path / "ledger")
    token = ledger.create_job("game", 25)
    submissions = []

    async def api(method, url, payload=None):
        if method == "POST":
            submissions.append(payload)
            return {"request_id": "one", "status_url": "status", "response_url": "result"}
        if url == "status":
            return {"status": "COMPLETED"}
        return {"model_glb": {"url": "artifact"}}

    async def download(url):
        return glb()

    monkeypatch.setattr(trellis, "fal_json", api)
    monkeypatch.setattr(trellis, "download_glb", download)
    assert await trellis.generate_glb(png(), ledger, token, "key", tmp_path / "first.glb") is False
    # Fresh token for the same game cannot cause a second payment.
    token2 = ledger.create_job("game", 25)
    assert await trellis.generate_glb(png(), ledger, token2, "key", tmp_path / "second.glb") is True
    assert len(submissions) == 1
    assert ledger.job(token)["remaining_cents"] == 0
    assert (tmp_path / "first.glb").read_bytes() == (tmp_path / "second.glb").read_bytes()


@pytest.mark.asyncio
async def test_uncertain_paid_submission_is_not_retried(tmp_path, monkeypatch):
    ledger = AssetBudgetLedger(tmp_path / "ledger")
    token = ledger.create_job("game", 100)
    calls = []

    async def fail(*args):
        calls.append(True)
        raise TimeoutError()

    monkeypatch.setattr(trellis, "fal_json", fail)
    with pytest.raises(TimeoutError):
        await trellis.generate_glb(png(), ledger, token, "same", tmp_path / "out")
    with pytest.raises(ValueError, match="uncertain"):
        await trellis.generate_glb(png(), ledger, token, "same", tmp_path / "out")
    assert len(calls) == 1
    assert ledger.job(token)["remaining_cents"] == 75


@pytest.mark.parametrize("content", [b"not glb", glb({"meshes": [{}], "images": [{"uri": "https://example.com/tracker"}]}), glb({"meshes": [{}], "buffers": [{"uri": "../../secret"}]})])
def test_invalid_and_external_resources_rejected(content):
    with pytest.raises(ValueError):
        trellis.validate_glb(content)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://queue.fal.run/fal-ai/trellis-2", "https://evil.test/fal-ai/trellis-2", "https://queue.fal.run/other"])
async def test_credentials_never_sent_to_untrusted_api(url):
    with pytest.raises(ValueError):
        await trellis.fal_json("GET", url)


@pytest.mark.asyncio
async def test_broker_rejects_paths_and_budget_before_payment(tmp_path, monkeypatch):
    games = tmp_path / "games"
    game = games / "owned"
    (game / "assets").mkdir(parents=True)
    (game / "assets/input.png").write_bytes(png())
    ledger = AssetBudgetLedger(tmp_path / "ledger")
    token = ledger.create_job("owned", 0)
    monkeypatch.setattr(launcher, "BEVY_PROJECTS_ROOT", str(games))
    monkeypatch.setattr(launcher, "_asset_ledger", lambda: ledger)
    monkeypatch.setenv("FAL_KEY", "test-not-a-provider-key")
    paid_calls = []

    async def paid(*args):
        paid_calls.append(True)
        raise AssertionError("must not pay")

    monkeypatch.setattr(trellis, "fal_json", paid)
    async with AsyncClient(transport=ASGITransport(app=launcher.app), base_url="http://test") as client:
        headers = {"Authorization": "Bearer " + token}
        request = {"operation": "glb", "image": "assets/input.png", "output": "assets/out.glb"}
        assert (await client.post("/agent-assets", json=request)).status_code == 401
        assert (await client.post("/agent-assets", json=request, headers=headers)).status_code == 402
        request["output"] = "../other/assets/out.glb"
        assert (await client.post("/agent-assets", json=request, headers=headers)).status_code == 400
        request.update(output="assets/out.glb", image="../other/assets/input.png")
        assert (await client.post("/agent-assets", json=request, headers=headers)).status_code == 400
    assert not paid_calls


@pytest.mark.asyncio
async def test_broker_writes_only_owned_game_and_deduplicates(tmp_path, monkeypatch):
    games = tmp_path / "games"
    for name in ["owned", "other"]:
        (games / name / "assets").mkdir(parents=True)
    (games / "owned/assets/input.png").write_bytes(png())
    ledger = AssetBudgetLedger(tmp_path / "ledger")
    token = ledger.create_job("owned", 25)
    monkeypatch.setattr(launcher, "BEVY_PROJECTS_ROOT", str(games))
    monkeypatch.setattr(launcher, "_asset_ledger", lambda: ledger)
    monkeypatch.setenv("FAL_KEY", "test-not-a-provider-key")
    submissions = []

    async def api(method, url, payload=None):
        if method == "POST":
            submissions.append(payload)
            return {"request_id": "one", "status_url": "status", "response_url": "result"}
        return {"status": "COMPLETED"} if url == "status" else {"model_glb": {"url": "artifact"}}

    async def download(url):
        return glb()

    monkeypatch.setattr(trellis, "fal_json", api)
    monkeypatch.setattr(trellis, "download_glb", download)
    async with AsyncClient(transport=ASGITransport(app=launcher.app), base_url="http://test") as client:
        request = {"operation": "glb", "image": "assets/input.png", "output": "assets/hero.glb"}
        for expected_cost in [25, 0]:
            response = await client.post("/agent-assets", json=request, headers={"Authorization": "Bearer " + token})
            assert response.status_code == 200
            assert response.json()["ok"] is True
            assert response.json()["cost_cents"] == expected_cost
    assert len(submissions) == 1
    assert (games / "owned/assets/hero.glb").read_bytes() == glb()
    assert not (games / "other/assets/hero.glb").exists()
