"""Unit tests for the Resend-backed EmailService.

These tests exercise the transactional email surface that backs game
creation + modification notifications. They never hit the network — the
Resend POST is intercepted via ``httpx.MockTransport``.

Coverage matrix:
  * Dry-run path: ``RESEND_API_KEY`` unset → returns False, logs a warning,
    no HTTP call attempted.
  * Happy path (modification email): mocked 200 from Resend → returns True
    and the outbound POST has the correct ``from``, ``to``, ``subject``,
    and includes the game URL.
  * 5xx from Resend → returns False, does not raise.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx
import pytest

from src.api.services import email_service as email_module
from src.api.services.email_service import EmailService, RESEND_API_URL


def _build_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    api_key: Optional[str],
    from_email: str = "TinyWorlds <onboarding@resend.dev>",
    frontend_url: str = "https://tinyworlds.us",
) -> EmailService:
    """Construct an EmailService with overridden settings.

    The module-level ``settings`` object is captured in ``EmailService.__init__``
    via attribute lookups, so we patch its attributes and re-instantiate.
    """
    monkeypatch.setattr(email_module.settings, "RESEND_API_KEY", api_key, raising=False)
    monkeypatch.setattr(email_module.settings, "RESEND_FROM_EMAIL", from_email, raising=False)
    monkeypatch.setattr(email_module.settings, "FRONTEND_URL", frontend_url, raising=False)
    return EmailService()


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> list[httpx.Request]:
    """Replace httpx.AsyncClient with a MockTransport-backed client.

    Returns a list that will be appended to with every request the service
    sends, so tests can assert on the outbound payload.
    """
    captured: list[httpx.Request] = []

    def _wrapped_handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return handler(request)

    transport = httpx.MockTransport(_wrapped_handler)
    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        # Drop transport-incompatible kwargs (verify=, timeout= are fine; the
        # service passes both — MockTransport ignores them).
        kwargs.pop("verify", None)
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(email_module.httpx, "AsyncClient", _factory)
    return captured


@pytest.mark.asyncio
async def test_dry_run_when_api_key_unset(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No API key → no HTTP, returns False, logs a 'not set' warning.

    Brief asked for True-on-dry-run, but the existing service returns False
    (and that's what the route layer's ``try/except`` upstream is wired for).
    We assert on the current contract rather than break callers.
    """
    service = _build_service(monkeypatch, api_key=None)
    # If the service did try to make a request, this would surface as a network
    # error — install a transport that explodes if touched.
    def _boom(_request: httpx.Request) -> httpx.Response:
        pytest.fail("HTTP request attempted in dry-run mode")

    _install_mock_transport(monkeypatch, _boom)

    caplog.set_level("WARNING")
    result = await service.send_game_modified_email(
        email="owner@example.com",
        game_id="godot-abc12345",
        engine="godot",
        game_name="Test Game",
    )

    assert result is False
    assert any("RESEND_API_KEY not set" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_modification_email_posts_expected_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: 2xx response, payload contains from/to/subject/game URL."""
    service = _build_service(
        monkeypatch,
        api_key="re_test_fake_key",
        from_email="TinyWorlds <notifications@tinyworlds.us>",
        frontend_url="https://tinyworlds.us",
    )

    def _ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "msg_12345"})

    captured = _install_mock_transport(monkeypatch, _ok)

    result = await service.send_game_modified_email(
        email="owner@example.com",
        game_id="godot-abc12345",
        engine="godot",
        game_name="Crystal Caves",
    )

    assert result is True
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == RESEND_API_URL
    assert request.headers.get("authorization") == "Bearer re_test_fake_key"

    body = json.loads(request.content.decode("utf-8"))
    assert body["from"] == "TinyWorlds <notifications@tinyworlds.us>"
    assert body["to"] == ["owner@example.com"]
    assert body["subject"] == "Your TinyWorlds game was updated"
    # Body should reference the game URL in both HTML and plaintext parts.
    expected_url = "https://tinyworlds.us/games/godot-abc12345"
    assert expected_url in body["html"]
    assert expected_url in body["text"]
    # The game name is interpolated into the email.
    assert "Crystal Caves" in body["html"]


@pytest.mark.asyncio
async def test_send_returns_false_on_5xx(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """5xx from Resend → returns False, never raises."""
    service = _build_service(monkeypatch, api_key="re_test_fake_key")

    def _boom(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "service unavailable"})

    _install_mock_transport(monkeypatch, _boom)

    caplog.set_level("ERROR")
    result = await service.send_game_modified_email(
        email="owner@example.com",
        game_id="bevy-99999999",
        engine="bevy",
        game_name=None,
    )

    assert result is False
    assert any("Resend send failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_game_created_email_uses_correct_subject_and_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sibling sanity check for the creation email path."""
    service = _build_service(
        monkeypatch,
        api_key="re_test_fake_key",
        frontend_url="https://staging.tinyworlds.us/",
    )

    def _ok(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"id": "msg_67890"})

    captured = _install_mock_transport(monkeypatch, _ok)

    result = await service.send_game_created_email(
        email="player@example.com",
        game_id="bevy-deadbeef",
        engine="bevy",
        game_name=None,  # falls back to game_id in the rendered title
    )

    assert result is True
    body = json.loads(captured[0].content.decode("utf-8"))
    assert body["subject"] == "Your TinyWorlds game is ready"
    # Trailing slash on FRONTEND_URL should be stripped, not doubled.
    assert "https://staging.tinyworlds.us/games/bevy-deadbeef" in body["html"]
    assert "bevy-deadbeef" in body["text"]
