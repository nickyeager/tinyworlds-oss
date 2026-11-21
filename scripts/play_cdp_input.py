#!/usr/bin/env python3
"""Send real CDP keyboard/mouse events to an existing Chrome instance.

Companion helper to play_probe.py — fills the cross-origin input gap.
The superpowers-chrome MCP browser runs on `http://127.0.0.1:9222`;
we attach to its currently-active page target and dispatch
`Input.dispatchKeyEvent` / `Input.dispatchMouseEvent`. CDP events
bypass the same-origin policy and reach focused iframes regardless
of origin — exactly what synthetic JS events couldn't do.

Usage:
    # Focus the iframe at the center of the viewport, then press W:
    python scripts/play_cdp_input.py \\
      --url-substring "games/godot-93f69424" \\
      --click 864,425 \\
      --key w

    # Repeat for a sequence:
    python scripts/play_cdp_input.py --url-substring "games/" --key w --key Space --key Enter

Keys map to CDP `code` and `windowsVirtualKeyCode` via a small table
covering the WASD / arrow / Space / Enter set we care about.

Requires the `websocket-client` package (already in the project deps).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

import websocket  # websocket-client (sync)

# CDP key descriptors: code + virtual key code. Add as needed.
KEY_TABLE: dict[str, tuple[str, int, str]] = {
    "w": ("KeyW", 87, "w"),
    "a": ("KeyA", 65, "a"),
    "s": ("KeyS", 83, "s"),
    "d": ("KeyD", 68, "d"),
    "r": ("KeyR", 82, "r"),
    "Space": ("Space", 32, " "),
    "Enter": ("Enter", 13, "\r"),
    "ArrowUp": ("ArrowUp", 38, ""),
    "ArrowDown": ("ArrowDown", 40, ""),
    "ArrowLeft": ("ArrowLeft", 37, ""),
    "ArrowRight": ("ArrowRight", 39, ""),
    "Escape": ("Escape", 27, ""),
}


def find_target(port: int, substr: str) -> str:
    """Return the webSocketDebuggerUrl for the first page target whose URL contains `substr`."""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as r:
        targets = json.loads(r.read())
    for t in targets:
        if t.get("type") == "page" and substr in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    available = [t.get("url") for t in targets if t.get("type") == "page"]
    raise SystemExit(f"no page target matching {substr!r}; have: {available}")


class Cdp:
    """Minimal CDP client over a single page-target WebSocket."""

    def __init__(self, ws_url: str) -> None:
        # Chrome's CDP rejects WebSocket upgrades whose Origin doesn't match its
        # allow-list. websocket-client auto-adds Origin from the URL host, which
        # Chrome refuses. Override with an http://localhost origin (always allowed).
        self.ws = websocket.create_connection(
            ws_url, timeout=5, origin="http://localhost",
        )
        self._id = 0

    def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        self.ws.send(json.dumps(msg))
        # Drain until we see our reply (events interleave).
        deadline = time.time() + 3
        while time.time() < deadline:
            raw = self.ws.recv()
            if not raw:
                continue
            data = json.loads(raw)
            if data.get("id") == self._id:
                if "error" in data:
                    raise RuntimeError(f"{method} failed: {data['error']}")
                return data.get("result", {})
        raise RuntimeError(f"timed out waiting for {method} reply")

    def click(self, x: int, y: int) -> None:
        for type_ in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", {
                "type": type_, "x": x, "y": y, "button": "left",
                "clickCount": 1, "buttons": 1 if type_ == "mousePressed" else 0,
            })

    def key(self, name: str) -> None:
        if name not in KEY_TABLE:
            raise SystemExit(f"unknown key {name!r}; known: {sorted(KEY_TABLE)}")
        code, vk, text = KEY_TABLE[name]
        base = {"code": code, "key": name if len(name) > 1 else text,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        self.send("Input.dispatchKeyEvent", {**base, "type": "keyDown",
                                              **({"text": text} if text else {})})
        self.send("Input.dispatchKeyEvent", {**base, "type": "keyUp"})

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9222,
                    help="CDP port (superpowers-chrome default 9222)")
    ap.add_argument("--url-substring", required=True,
                    help="substring to match an open page target")
    ap.add_argument("--click", help="comma-separated x,y to click before any keys (focuses iframe)")
    ap.add_argument("--key", action="append", default=[],
                    help="key name; repeat for multiple. e.g. --key w --key Space")
    ap.add_argument("--delay-ms", type=int, default=150,
                    help="pause between actions")
    args = ap.parse_args()

    ws_url = find_target(args.port, args.url_substring)
    cdp = Cdp(ws_url)
    try:
        if args.click:
            x, y = (int(v) for v in args.click.split(","))
            cdp.click(x, y)
            time.sleep(args.delay_ms / 1000)
        for k in args.key:
            cdp.key(k)
            time.sleep(args.delay_ms / 1000)
    finally:
        cdp.close()
    print(f"OK target={ws_url[:60]}... keys={args.key} click={args.click}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
