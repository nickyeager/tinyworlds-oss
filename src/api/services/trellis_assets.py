"""Trusted, resumable remote TRELLIS.2 generation. Never loaded in workers."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import struct
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image

from src.api.services.game_asset_budget import AssetBudgetLedger

COST_CENTS = 25  # fal's fixed 512-resolution price, checked 2026-11-18.
MODEL = "fal-ai/trellis-2"
MAX_GLB_BYTES = 32 * 1024 * 1024


def validate_reference(content: bytes) -> None:
    if not content or len(content) > 4 * 1024 * 1024:
        raise ValueError("3D reference must be at most 4 MiB")
    with Image.open(io.BytesIO(content)) as image:
        if image.width * image.height > 4_000_000 or image.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("3D reference must be a PNG, JPEG or WebP of at most 4 megapixels")
        image.verify()


def validate_glb(content: bytes) -> None:
    if len(content) < 20 or len(content) > MAX_GLB_BYTES:
        raise ValueError("invalid GLB size")
    if struct.unpack_from("<4sII", content) != (b"glTF", 2, len(content)):
        raise ValueError("invalid GLB header")
    length, kind = struct.unpack_from("<II", content, 12)
    if kind != 0x4E4F534A or 20 + length > len(content):
        raise ValueError("invalid GLB JSON chunk")
    document = json.loads(content[20:20 + length])
    if not document.get("meshes"):
        raise ValueError("GLB contains no meshes")
    for item in document.get("buffers", []) + document.get("images", []):
        if item.get("uri"):
            raise ValueError("GLB must embed all resources")


async def fal_json(method: str, url: str, payload: dict | None = None) -> dict:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "queue.fal.run" or not parsed.path.startswith("/" + MODEL):
        raise ValueError("unexpected provider API URL")
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.request(method, url, json=payload, headers={"Authorization": "Key " + os.environ["FAL_KEY"]})
        response.raise_for_status()
        if len(response.content) > 65536:
            raise ValueError("provider response too large")
        return response.json()


async def download_glb(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not (parsed.netloc == "fal.media" or parsed.netloc.endswith(".fal.media")):
        raise ValueError("unexpected artifact host")
    content = bytearray()
    # No provider credentials on artifact downloads; no redirects to other hosts.
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_GLB_BYTES:
                    raise ValueError("GLB is too large")
    validate_glb(content)
    return bytes(content)


async def generate_glb(content: bytes, ledger: AssetBudgetLedger, token: str, request_key: str, destination: Path) -> bool:
    """Return whether an existing request was reused; uncertain submissions never retry."""
    validate_reference(content)
    fresh, record = ledger.claim_asset(token, request_key, COST_CENTS)
    if fresh:
        mime = Image.open(io.BytesIO(content)).format.lower()
        if mime == "jpg":
            mime = "jpeg"
        submitted = await fal_json("POST", "https://queue.fal.run/" + MODEL, {
            "image_url": "data:image/" + mime + ";base64," + base64.b64encode(content).decode(),
            "resolution": 512, "seed": 42, "decimation_target": 50000, "texture_size": 1024,
        })
        record.update(status="submitted", request_id=submitted["request_id"], status_url=submitted["status_url"], response_url=submitted["response_url"])
        ledger.record_asset(token, request_key, record)
    if "request_id" not in record:
        raise ValueError("submission is uncertain; no automatic paid retry")
    if "artifact_url" not in record:
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            status = await fal_json("GET", record["status_url"])
            if status["status"] == "COMPLETED":
                result = await fal_json("GET", record["response_url"])
                record.update(status="complete", artifact_url=result["model_glb"]["url"])
                ledger.record_asset(token, request_key, record)
                break
            if status["status"] not in {"IN_QUEUE", "IN_PROGRESS"}:
                raise ValueError("remote generation failed")
            await asyncio.sleep(2)
        else:
            raise TimeoutError("remote job pending; retry resumes the same request")
    generated = await download_glb(record["artifact_url"])
    destination.write_bytes(generated)
    return not fresh
