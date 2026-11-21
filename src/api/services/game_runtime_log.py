"""Runtime telemetry from generated games (browser WASM).

Backend has rich build-time visibility (godogen_failures.jsonl) but ZERO insight into what the WASM does once the
player loads it. When the user reports "X happened in the game", we have
no log to correlate against — just memory + the recorded smoke video
godogen produced at build time.

This module adds the runtime side:

  Game (WASM) → HTTPRequest → /api/v1/games/{id}/playthrough
                                          ↓
                              data/game_runtime.jsonl

Records are flat dicts; the GDScript autoload calls `log_event(kind, data)`
and we append `{ts, game_id, kind, session, data}` to the JSONL. Same
append-only pattern as the other ledgers — easy to grep with `jq`, easy to
aggregate, easy to ignore if disabled.

Why JSONL and not a DB:
  - Same scale as the other JSONL ledgers — single-digit hundreds
    of events per session, not millions.
  - Per-event analysis is the common case ("show me every position drift
    greater than 5 units"), and `jq | sort | head` answers that fine.
  - When this stops being enough we'll re-evaluate; right now it's not.

Why no auth on the endpoint:
  - The game runs in a browser the user already loaded; if they wanted to
    forge events they'd be forging their own. The game_id is in the URL,
    which means a forged request needs at least the right game_id, and
    we keep a rolling-1h cap per game_id to bound the damage from a hostile
    POST loop.
  - If/when we ship games publicly we tighten this — record a per-game
    short-lived JWT into project.godot at build time and verify it here.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Iterable


logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOG_PATH = PROJECT_ROOT / "data" / "game_runtime.jsonl"

# Per-game rolling rate cap: at most N events per rolling 60s window. Stops
# a runaway script (or hostile client) from filling the disk. A real game
# session ought to top out at a few hundred events for a 10-min playthrough.
RATE_LIMIT_PER_MINUTE = 300

# Per-event payload cap. Anything larger gets the `data` field truncated
# and an `_overflow: true` marker added — preserves the event for debug
# without letting one weird record swell the ledger.
MAX_PAYLOAD_BYTES = 2048


class RateLimitedError(Exception):
    """Raised when a game_id exceeds the per-minute rate cap.

    The route maps this to HTTP 429; the GDScript autoload should back off
    on 429 (or just silently drop, since this is best-effort telemetry).
    """


@dataclass(frozen=True)
class RuntimeEvent:
    """One structured event from a game's runtime."""
    game_id: str
    ts: float
    kind: str
    session_id: str | None
    data: dict[str, Any]
    overflow: bool = False


class GameRuntimeLog:
    """Append-only JSONL ledger + per-game rate cap.

    Rate cap is process-local (in-memory deque per game_id). That's fine
    for the single-uvicorn-worker setup; if we ever go multi-worker we'll
    move to redis. The cost ledger has the same caveat.
    """

    def __init__(self, *, log_path: Path | None = None) -> None:
        self.log_path = Path(log_path) if log_path else DEFAULT_LOG_PATH
        self._lock = Lock()
        # game_id → deque of timestamps in the last 60s
        self._recent: dict[str, deque[float]] = {}

    def append(
        self,
        game_id: str,
        kind: str,
        data: dict[str, Any],
        *,
        session_id: str | None = None,
        ts: float | None = None,
    ) -> RuntimeEvent:
        """Persist one event. Raises RateLimitedError if the game exceeds
        ``RATE_LIMIT_PER_MINUTE`` in the last 60s."""
        ts = ts if ts is not None else time.time()
        with self._lock:
            self._gc_recent(game_id, now=ts)
            bucket = self._recent.setdefault(game_id, deque())
            if len(bucket) >= RATE_LIMIT_PER_MINUTE:
                raise RateLimitedError(
                    f"{game_id} exceeded {RATE_LIMIT_PER_MINUTE} events / 60s"
                )
            bucket.append(ts)

        # Truncate oversized payloads but keep the event so we know it
        # happened. The frontend can render a "(payload truncated)" hint.
        overflow = False
        try:
            encoded = json.dumps(data, default=str)
            if len(encoded) > MAX_PAYLOAD_BYTES:
                data = {"_truncated_repr": encoded[:MAX_PAYLOAD_BYTES]}
                overflow = True
        except (TypeError, ValueError):
            data = {"_serialization_error": True}
            overflow = True

        event = RuntimeEvent(
            game_id=game_id,
            ts=ts,
            kind=str(kind)[:64],
            session_id=session_id[:64] if session_id else None,
            data=data,
            overflow=overflow,
        )

        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps({
                    "ts": event.ts,
                    "game_id": event.game_id,
                    "kind": event.kind,
                    "session_id": event.session_id,
                    "data": event.data,
                    **({"overflow": True} if event.overflow else {}),
                }, default=str) + "\n")
        except OSError:
            logger.exception("failed to append game runtime event to %s", self.log_path)

        return event

    def _gc_recent(self, game_id: str, *, now: float) -> None:
        """Drop timestamps older than 60s from the rate-limit bucket."""
        cutoff = now - 60.0
        bucket = self._recent.get(game_id)
        if bucket is None:
            return
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

    def events_for_game(
        self,
        game_id: str,
        *,
        limit: int = 200,
        kinds: Iterable[str] | None = None,
    ) -> list[dict]:
        """Return the most recent N events for ``game_id``, newest first.

        Optionally filter by kind (e.g. ``kinds={"player_pos_drift", "error"}``).
        """
        if not self.log_path.is_file():
            return []
        wanted = set(kinds) if kinds else None
        matches: list[dict] = []
        try:
            with self.log_path.open("r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("game_id") != game_id:
                        continue
                    if wanted and rec.get("kind") not in wanted:
                        continue
                    matches.append(rec)
        except OSError:
            logger.exception("failed to read game runtime log %s", self.log_path)
            return []
        matches.sort(key=lambda r: r.get("ts", 0), reverse=True)
        return matches[:limit]

    def summary_for_game(self, game_id: str) -> dict[str, Any]:
        """Aggregate stats for the Operations tab: kind counts, last-N
        kinds, error count, session count.
        """
        events = self.events_for_game(game_id, limit=10_000)
        kind_counts: dict[str, int] = {}
        sessions: set[str] = set()
        error_count = 0
        last_ts: float = 0
        for e in events:
            k = e.get("kind") or "unknown"
            kind_counts[k] = kind_counts.get(k, 0) + 1
            if e.get("session_id"):
                sessions.add(e["session_id"])
            if "error" in k.lower():
                error_count += 1
            if e.get("ts", 0) > last_ts:
                last_ts = e["ts"]
        return {
            "game_id": game_id,
            "total_events": len(events),
            "kind_counts": kind_counts,
            "session_count": len(sessions),
            "error_count": error_count,
            "last_event_ts": last_ts or None,
        }


default_runtime_log = GameRuntimeLog()
