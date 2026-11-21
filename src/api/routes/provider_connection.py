"""Loopback-only setup for a personal install. Never a hosted credentials API."""
import ipaddress
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr
from typing import Literal

from src.api.core.config import Settings, get_settings
from src.api.services.personal_provider import personal_provider

settings = get_settings()


def is_loopback(host: str | None) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def local_operator(request: Request, response: Response, config: Settings = Depends(get_settings)):
    response.headers["Cache-Control"] = "no-store"
    settings = config
    if not settings.PERSONAL_MODE or settings.AGENT_EXECUTION_MODE != "local" or settings.REQUIRE_PRODUCTION_SECRETS:
        raise HTTPException(404, "Personal provider setup is not enabled.")
    origin = request.headers.get("origin")
    if (not request.client or not is_loopback(request.client.host)
            or not is_loopback(request.url.hostname)
            or request.headers.get("x-tinyworlds-local") != "1"
            or (origin is not None and (origin not in settings.CORS_ORIGINS or not is_loopback(urlparse(origin).hostname)))):
        raise HTTPException(403, "Open personal AI setup from this computer's localhost address.")


router = APIRouter(dependencies=[Depends(local_operator)])


class ConnectRequest(BaseModel):
    provider: Literal["codex", "claude"]
    method: Literal["existing_cli", "api_key", "subscription"]
    model: str = Field(default="", max_length=120)
    api_key: SecretStr | None = None


@router.get("")
async def status():
    return personal_provider(settings).status()


@router.post("")
async def connect(body: ConnectRequest):
    service = personal_provider(settings)
    async with service.lock:
        try:
            if service.pending:
                raise HTTPException(409, "Finish or cancel the current sign-in first.")
            if body.method == "subscription":
                if body.provider != "codex":
                    raise HTTPException(400, "Complete Claude subscription sign-in in the official Claude Code CLI, then use its existing login.")
                return await service.start_login(body.model.strip())
            if body.method == "existing_cli":
                await service.connect_existing(body.provider, body.model.strip())
            else:
                if not body.api_key:
                    raise HTTPException(400, "An API key is required.")
                await service.connect_key(body.provider, body.model.strip(), body.api_key.get_secret_value())
            return service.status()
        except (OSError, RuntimeError, TimeoutError, ValueError):
            raise HTTPException(503, "Provider connection failed. Confirm the official CLI is installed and up to date, then try again.") from None


@router.post("/login/finish")
async def finish():
    service = personal_provider(settings)
    async with service.lock:
        try:
            return {"complete": await service.finish_login()}
        except (OSError, RuntimeError, TimeoutError, ValueError):
            await service.cancel_login()
            raise HTTPException(400, "Sign-in did not complete. Please start again.") from None


@router.post("/login/cancel")
async def cancel():
    service = personal_provider(settings)
    async with service.lock:
        await service.cancel_login()
    return {"ok": True}


@router.delete("")
async def disconnect():
    service = personal_provider(settings)
    async with service.lock:
        await service.disconnect()
    return {"ok": True}


@router.post("/check")
async def check():
    service = personal_provider(settings)
    async with service.lock:
        return await service.check()
