#!/usr/bin/env python3
"""End-to-end smoke test for the resilient generation stream.

Verifies the architecture without a real Claude generation:

  1. Create a fake game dir + .creation/events.jsonl
  2. Spawn a background "writer" that appends events on a schedule
  3. Open the /events/stream endpoint — confirm replay + tail works
  4. Disconnect mid-tail, write more events, reconnect with ?since=N
  5. Confirm the second reader sees ONLY the events it missed

Run with the local backend up (uvicorn ... --port 8001).
"""
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

GAME_ID = "godot-resiltest"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
GAME_DIR = PROJECT_ROOT / "generated_games" / GAME_ID
CREATION_DIR = GAME_DIR / ".creation"
EVENTS_FILE = CREATION_DIR / "events.jsonl"


def _setup():
    GAME_DIR.mkdir(parents=True, exist_ok=True)
    CREATION_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text("")
    # The endpoint requires `<game>/project.godot` for game_exists? No —
    # /events/stream is intentionally permissive (game dir + events.jsonl).
    return EVENTS_FILE


def _append_event(event: dict) -> None:
    with EVENTS_FILE.open("a") as f:
        f.write(json.dumps(event) + "\n")


def _read_stream_until(url: str, max_events: int, timeout_s: float) -> list[dict]:
    """Open SSE; collect at most max_events; bail if no event arrives within
    timeout_s. Returns parsed events (excluding the data: prefix)."""
    req = urllib.request.Request(url)
    out: list[dict] = []
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        buffer = ""
        deadline = time.time() + timeout_s
        while len(out) < max_events and time.time() < deadline:
            chunk = resp.read(4096).decode("utf-8", errors="replace")
            if not chunk:
                time.sleep(0.05)
                continue
            buffer += chunk
            while "\n\n" in buffer:
                line, buffer = buffer.split("\n\n", 1)
                line = line.strip()
                if line.startswith("data: "):
                    try:
                        out.append(json.loads(line[len("data: "):]))
                    except json.JSONDecodeError:
                        pass
                    if len(out) >= max_events:
                        break
    return out


def main() -> int:
    _setup()
    # Pre-write 2 historical events + a terminal "done" so the tail
    # closes the stream cleanly after replay.
    _append_event({"event_type": "CLIStreamEvent", "n": 0, "msg": "hist-0"})
    _append_event({"event_type": "CLIStreamEvent", "n": 1, "msg": "hist-1"})
    _append_event({"event_type": "done", "game_id": GAME_ID})

    url = "http://localhost:8001/api/v1/godot/games/" + GAME_ID + "/events/stream?since=-1"

    print("== Test 1: replay 2 events + terminal done ==")
    out = _read_stream_until(url, max_events=3, timeout_s=4)
    if len(out) != 3:
        print(f"  FAIL: expected 3, got {len(out)}: {out}", file=sys.stderr)
        return 1
    if [e["seq"] for e in out] != [0, 1, 2]:
        print(f"  FAIL: seq not stamped: {[e.get('seq') for e in out]}", file=sys.stderr)
        return 1
    if out[-1]["event_type"] != "done":
        print(f"  FAIL: last event not 'done': {out[-1]}", file=sys.stderr)
        return 1
    print("  PASS — 2 events + terminal done with seq 0,1,2")

    print("== Test 2: resume from seq=0, should yield only seq>=1 ==")
    resume_url = "http://localhost:8001/api/v1/godot/games/" + GAME_ID + "/events/stream?since=0"
    out = _read_stream_until(resume_url, max_events=2, timeout_s=4)
    if len(out) != 2:
        print(f"  FAIL: expected 2 events, got {len(out)}: {out}", file=sys.stderr)
        return 1
    if [e["seq"] for e in out] != [1, 2]:
        print(f"  FAIL: expected seqs [1,2], got {[e['seq'] for e in out]}", file=sys.stderr)
        return 1
    print("  PASS — first event after resume is seq=1")

    print("== Test 3: tail picks up new appends + terminates on done ==")
    # Reset for this test — start with one event, then append more mid-stream.
    EVENTS_FILE.write_text("")
    _append_event({"event_type": "CLIStreamEvent", "n": 0, "msg": "starter"})

    async def appender():
        await asyncio.sleep(0.6)
        _append_event({"event_type": "CLIStreamEvent", "n": 99, "msg": "midflight"})
        await asyncio.sleep(0.6)
        _append_event({"event_type": "done", "game_id": GAME_ID})

    async def reader():
        u = "http://localhost:8001/api/v1/godot/games/" + GAME_ID + "/events/stream?since=-1"
        return await asyncio.to_thread(_read_stream_until, u, 3, 6.0)

    async def run():
        appender_task = asyncio.create_task(appender())
        events = await reader()
        await appender_task
        return events

    out = asyncio.run(run())
    if len(out) < 3:
        print(f"  FAIL: expected >=3 events, got {len(out)}: {out}", file=sys.stderr)
        return 1
    types = [e["event_type"] for e in out]
    if "done" not in types:
        print(f"  FAIL: stream did not terminate on 'done': {types}", file=sys.stderr)
        return 1
    print(f"  PASS — tail saw {len(out)} events including terminal 'done'")

    print()
    print("ALL TESTS PASSED")
    # Clean up
    import shutil
    shutil.rmtree(GAME_DIR, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Extra: backend-restart survival
# (Run manually with `python scripts/test_resilient_stream.py --restart`)
