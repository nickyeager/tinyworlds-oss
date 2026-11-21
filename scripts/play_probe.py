#!/usr/bin/env python3
"""Play-probe verdict tool — companion to the play-and-improve skill.

Takes a bundle of evidence collected from the chrome-mcp browser session
(screenshots, console log, telemetry shim dump, input-response screenshots)
and emits a single structured verdict. Appends to data/play_runs.jsonl.

This script does NOT drive the browser — that's the skill's job (Claude
uses chrome-mcp tools directly). This is the analysis half: turn raw
evidence into a classified verdict the skill can act on.

Usage:
    python scripts/play_probe.py \\
      --game-id godot-e316b292 \\
      --source local|prod \\
      --pre-input  /tmp/probe/frame-pre-{a,b,c}.png \\
      --post-input /tmp/probe/frame-post-{a,b,c}.png \\
      --console-log /tmp/probe/console.json \\
      --telemetry   /tmp/probe/telemetry.json \\
      --notes "manual notes for this run"

Outputs JSON to stdout and appends one line to data/play_runs.jsonl.

Failure classes (the taxonomy the skill writes lessons against):
    black_screen       — frames are uniformly dark, nothing rendered
    stuck_frames       — frames identical across time, even with input probes
    input_dead         — frames change pre-input but not in response to input
    console_errors     — non-empty console errors / godot stderr
    telemetry_frozen   — telemetry shim reports frozen_thread or canvas-never-created
    asset_missing      — 404s in network log (passed via --console-log)
    lighting_wrong     — average luma below "playable" floor (heuristic for forward_plus-on-gl_compat)
    needs_agentic      — alive + no obvious issue + can't tell if it's a real game; escalate

A clean PASS requires:
    pre-input frames LIVE (hamming >= threshold across the three frames)
    input probes change the frame (delta-hamming >= input_response_threshold)
    no console errors
    no telemetry frozen/canvas
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Reuse the existing 8x8 fingerprint from gameplay_diff_check.
sys.path.insert(0, str(Path(__file__).parent))
from gameplay_diff_check import _read_png, _fingerprint, DIFF_THRESHOLD_BITS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
LOG_PATH = REPO / "data" / "play_runs.jsonl"

# Pre-input liveness: at least this many bits must differ across the
# 3-frame pre-input window. Inherits the calibrated threshold.
PRE_INPUT_LIVE_BITS = DIFF_THRESHOLD_BITS

# Input-response threshold: after we send a key, the post-input frame
# fingerprint should differ from the pre-input baseline by at least
# this many bits. Tighter than liveness because a working game already
# moves on its own; the input-driven delta needs to be on top of that.
INPUT_RESPONSE_BITS = 6

# Luma floor for "lighting OK". An 8x8 grayscale average below this on
# the brightest frame strongly suggests the forward_plus/gl_compat
# rendering bug or a black-screen export.
LUMA_FLOOR = 18  # 0-255 scale; <18 ~= near-uniform dark frame


@dataclass
class Verdict:
    game_id: str
    source: str
    timestamp: str
    pre_input_hamming: list[int]
    post_input_hamming: list[int]
    luma_min: int
    luma_max: int
    console_error_count: int
    telemetry_rules: list[str]
    failures: list[str] = field(default_factory=list)
    overall: str = "unknown"     # pass | fail | needs_agentic
    notes: str = ""


def _avg_luma(width: int, height: int, pixels: bytes) -> int:
    """Mean luma over the whole image. Cheap (full-image; not 8x8)."""
    bpp = len(pixels) // (width * height)
    n = width * height
    if n == 0:
        return 0
    rs = gs = bs = 0
    for i in range(n):
        p = i * bpp
        rs += pixels[p]
        gs += pixels[p + 1]
        bs += pixels[p + 2]
    return (299 * rs + 587 * gs + 114 * bs) // (1000 * n)


def _hamming(a: Path, b: Path) -> int:
    w1, h1, pa = _read_png(a)
    w2, h2, pb = _read_png(b)
    if (w1, h1) != (w2, h2):
        return 64
    return bin(_fingerprint(w1, h1, pa) ^ _fingerprint(w2, h2, pb)).count("1")


def _pairwise_hamming(frames: list[Path]) -> list[int]:
    return [_hamming(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]


def _luma_stats(frames: list[Path]) -> tuple[int, int]:
    values = []
    for f in frames:
        w, h, px = _read_png(f)
        values.append(_avg_luma(w, h, px))
    return min(values), max(values)


def build_verdict(args: argparse.Namespace) -> Verdict:
    pre = [Path(p) for p in args.pre_input]
    post = [Path(p) for p in args.post_input]
    for p in pre + post:
        if not p.exists():
            raise FileNotFoundError(f"missing frame: {p}")

    pre_hamming = _pairwise_hamming(pre)
    # post[i] compared against pre[-1] — was there a response to the input?
    baseline = pre[-1]
    post_hamming = [_hamming(baseline, p) for p in post]

    luma_min, luma_max = _luma_stats(pre + post)

    console_errors: list[dict] = []
    if args.console_log:
        try:
            console_errors = [
                e for e in json.loads(Path(args.console_log).read_text())
                if e.get("level") in ("error", "severe", "exception")
            ]
        except Exception as e:
            console_errors = [{"level": "error", "text": f"console_log parse failed: {e}"}]

    telemetry_rules: list[str] = []
    if args.telemetry:
        try:
            tel = json.loads(Path(args.telemetry).read_text())
            telemetry_rules = sorted({r.get("rule", "") for r in tel.get("events", []) if r.get("rule")})
        except Exception as e:
            telemetry_rules = [f"telemetry_parse_failed: {e}"]

    failures: list[str] = []

    if luma_max < LUMA_FLOOR:
        failures.append("black_screen")
    if max(pre_hamming, default=0) < PRE_INPUT_LIVE_BITS:
        failures.append("stuck_frames")
    if "stuck_frames" not in failures and max(post_hamming, default=0) < INPUT_RESPONSE_BITS:
        failures.append("input_dead")
    if console_errors:
        failures.append("console_errors")
    for rule in telemetry_rules:
        if rule in ("frozen_thread", "canvas_never_created", "godot_print_err"):
            failures.append(f"telemetry:{rule}")
    if luma_max < 60 and "black_screen" not in failures:
        failures.append("lighting_wrong")

    if not failures:
        overall = "pass"
    elif failures == ["console_errors"] and len(console_errors) <= 1:
        overall = "needs_agentic"  # one noisy log isn't necessarily fatal
    else:
        overall = "fail"

    return Verdict(
        game_id=args.game_id,
        source=args.source,
        timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
        pre_input_hamming=pre_hamming,
        post_input_hamming=post_hamming,
        luma_min=luma_min,
        luma_max=luma_max,
        console_error_count=len(console_errors),
        telemetry_rules=telemetry_rules,
        failures=sorted(set(failures)),
        overall=overall,
        notes=args.notes or "",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--game-id", required=True)
    ap.add_argument("--source", choices=["local", "prod"], required=True)
    ap.add_argument("--pre-input", nargs="+", required=True,
                    help="≥2 screenshots taken before any input was sent")
    ap.add_argument("--post-input", nargs="+", required=True,
                    help="≥1 screenshot taken after each input probe")
    ap.add_argument("--console-log", help="JSON array of console messages")
    ap.add_argument("--telemetry", help="JSON dump of window.__tinyworlds_telemetry")
    ap.add_argument("--notes", default="")
    ap.add_argument("--no-log", action="store_true", help="don't append to play_runs.jsonl")
    args = ap.parse_args()

    verdict = build_verdict(args)
    payload = asdict(verdict)
    print(json.dumps(payload, indent=2))

    if not args.no_log:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(payload) + "\n")

    return 0 if verdict.overall == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
