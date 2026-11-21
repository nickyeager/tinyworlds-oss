"""Cached liveness probe for the configured game-generation provider.

Use the same executor factory as generation so the status describes the active
provider. A small live request establishes authentication and liveness; the
result is cached to avoid probing on every page visit.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, TypedDict

from src.api.core.config import get_settings
from src.api.services.executors import get_executor

logger = logging.getLogger("tinyworlds")

# How long a probe result stays fresh. A probe spends one CLI turn, so keep
# this generous — auth state changes only on rebuild / token expiry, which is
# rare relative to how often the footer polls.
_PROBE_TTL_SECONDS = 600.0

# Hard ceiling on a single probe. The CLI should answer "ok" in a couple of
# seconds when healthy; a hang usually means a broken/expired auth state.
_PROBE_TIMEOUT_SECONDS = 20.0


class AgentStatus(TypedDict):
    online: bool
    detail: str
    checked_at: float  # unix seconds of the underlying probe
    cached: bool  # True if served from cache without a fresh probe


_lock = asyncio.Lock()
_cached_online: Optional[bool] = None
_cached_detail: str = ""
_cached_at: float = 0.0


async def _run_probe() -> tuple[bool, str]:
    """Probe the configured generation provider. Returns (online, detail)."""
    try:
        out = await get_executor(get_settings()).run_oneshot(
            "Reply with the single word: ok",
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
        return True, (out.strip()[:120] or "ok")
    except asyncio.TimeoutError:
        return False, "probe timed out — CLI unresponsive or not logged in"
    except Exception as e:  # RuntimeError on non-zero exit, OSError, etc.
        return False, f"probe failed: {str(e)[:200]}"


async def get_agent_status(force: bool = False) -> AgentStatus:
    """Return cached agent liveness, refreshing the probe if stale.

    Concurrent callers during a refresh share the single in-flight probe via
    the lock, so a burst of footer polls never fans out into many subprocesses.
    """
    global _cached_online, _cached_detail, _cached_at

    now = time.monotonic()
    if (
        not force
        and _cached_online is not None
        and (now - _cached_at) < _PROBE_TTL_SECONDS
    ):
        return AgentStatus(
            online=_cached_online,
            detail=_cached_detail,
            checked_at=_cached_at,
            cached=True,
        )

    async with _lock:
        # Re-check after acquiring: another caller may have just refreshed.
        now = time.monotonic()
        if (
            not force
            and _cached_online is not None
            and (now - _cached_at) < _PROBE_TTL_SECONDS
        ):
            return AgentStatus(
                online=_cached_online,
                detail=_cached_detail,
                checked_at=_cached_at,
                cached=True,
            )

        online, detail = await _run_probe()
        _cached_online = online
        _cached_detail = detail
        _cached_at = time.monotonic()
        if not online:
            logger.warning("agent-status probe reports OFFLINE: %s", detail)
        return AgentStatus(
            online=online,
            detail=detail,
            checked_at=_cached_at,
            cached=False,
        )
