"""Thin wrapper over ``<game_path>/.creation/events.jsonl`` for replay + tail.

The persistent log is written by ``_CreationLog`` in ``godot_creation_agent``
during every generation. This module turns it into a *queryable* surface:

  - ``read_all``: snapshot of every event recorded so far.
  - ``tail``: async generator that yields events from ``since`` onwards
    AND keeps following new appends until a terminal event lands or the
    an explicit application terminal event is persisted.

The tail interface is the foundation for resilient SSE — multiple clients
can attach (or one client can reattach after a network blip) and see an
identical stream. Generation is no longer tied to a single HTTP request.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator, Optional, Tuple

logger = logging.getLogger(__name__)


# Events whose presence in the log means generation is done — tail
# generators stop yielding and exit cleanly when one of these arrives.
TERMINAL_EVENT_TYPES = frozenset({
    "done",
    "failed",
    "crashed",
    "interrupted",
})


class GameEventLog:
    """Append-only event log for one game.

    Thread-safe for one writer (``_CreationLog``) and many readers.
    OS-level append atomicity is relied upon for line-level consistency;
    individual events are assumed to be <4 KB (Linux ``PIPE_BUF``). Larger
    payloads need a sidecar — flagged in the resilient-stream plan.
    """

    def __init__(self, game_path: Path, log_dir: str = ".creation") -> None:
        self.game_path = game_path
        self.events_file = game_path / log_dir / "events.jsonl"
        self.summary_file = game_path / log_dir / "summary.json"

    def append(self, event: dict) -> None:
        """Append one JSON event to the log."""
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        with self.events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def write_summary(self, summary: dict) -> None:
        """Write a terminal summary sidecar for readers that tail after EOF."""
        self.summary_file.parent.mkdir(parents=True, exist_ok=True)
        self.summary_file.write_text(json.dumps(summary, indent=2, default=str))

    # -------------------------------------------------------------
    # Reads
    # -------------------------------------------------------------

    def exists(self) -> bool:
        return self.events_file.is_file()

    def read_all(self) -> list[dict]:
        """Parse every event in the file. Skips malformed lines rather
        than failing the read — the file is append-only and a partial
        flush could leave a half-line."""
        if not self.exists():
            return []
        events: list[dict] = []
        try:
            for line in self.events_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError as e:
            logger.warning("GameEventLog read failed for %s: %s", self.events_file, e)
        return events

    def has_terminal(self, events: Optional[list[dict]] = None) -> bool:
        """Only application terminal events count; agent summaries precede verification."""
        if events is None:
            events = self.read_all()
        # Scan from the end — terminal events are nearly always last few.
        for e in reversed(events[-20:] if len(events) > 20 else events):
            if e.get("event_type") in TERMINAL_EVENT_TYPES:
                return True
        return False

    def read_summary(self) -> Optional[dict]:
        if not self.summary_file.is_file():
            return None
        try:
            return json.loads(self.summary_file.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    # -------------------------------------------------------------
    # Tail (replay + follow)
    # -------------------------------------------------------------

    async def tail(
        self,
        *,
        since_seq: int = -1,
        poll_interval: float = 0.5,
        idle_timeout_seconds: float = 600.0,
        stop_on_summary: bool = False,
    ) -> AsyncIterator[Tuple[int, dict]]:
        """Yield ``(seq, event)`` pairs from ``since_seq + 1`` onwards.

        Replays history first, then polls for new lines after EOF. Exits
        cleanly when:
          - a terminal event (``done`` / ``failed`` / ``crashed``) appears
          - ``summary.json`` is written when explicitly opting into stop_on_summary
          - ``idle_timeout_seconds`` elapses with no new events AND no
            summary (generation orphaned — caller decides what to do).

        Sequence numbers are 0-indexed line positions in events.jsonl.
        Pass ``since_seq = -1`` (default) for a fresh read.
        """
        last_emitted = since_seq
        last_event_at = asyncio.get_event_loop().time()

        while True:
            events = self.read_all()
            # Drain anything we haven't sent yet.
            if last_emitted + 1 < len(events):
                for i in range(last_emitted + 1, len(events)):
                    event = events[i]
                    yield i, event
                    last_emitted = i
                    last_event_at = asyncio.get_event_loop().time()
                    if event.get("event_type") in TERMINAL_EVENT_TYPES:
                        return
            else:
                # No new events. Two reasons to stop:
                # 1) Pipeline finalized — summary.json is the canonical signal
                #    even if no terminal event landed in events.jsonl.
                # 2) Idle timeout — generation likely orphaned (e.g. backend
                #    container was killed mid-flight).
                if stop_on_summary and self.summary_file.is_file():
                    return
                if asyncio.get_event_loop().time() - last_event_at > idle_timeout_seconds:
                    yield -1, {
                        "event_type": "interrupted",
                        "reason": (
                            f"no events for {idle_timeout_seconds:.0f}s — "
                            "generation likely orphaned (container restart?)"
                        ),
                    }
                    return
            await asyncio.sleep(poll_interval)
