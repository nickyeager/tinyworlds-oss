#!/usr/bin/env python3
"""Tier-1 gameplay liveness check: did anything actually change?

Takes two screenshots N seconds apart and reports whether they're
identical. Catches the "pipeline says done but the game is in a static
steady state" failure class — the WASM thread is running, telemetry is
clean, no errors — but visually nothing happens.

Usage (called from /test-game-*-e2e):

    python scripts/gameplay_diff_check.py screenshot1.png screenshot2.png
    # exits 0 if pixel-diff > THRESHOLD; non-zero with a message otherwise.

We intentionally don't analyze *what* changed (that's Tier 2 / vision).
Tier 1 just answers "is anything alive on screen". A passing diff doesn't
mean the gameplay is fun, but a failing diff means it's definitely broken.

Stdlib-only — no Pillow / numpy. Mac-friendly: works with whatever PNG
encoder is upstream.
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path


# Hamming-distance threshold over a 64-bit downscaled grayscale fingerprint.
# Calibrated against a static frame (0 bits set) vs frames from a working
# Bevy game (typically 5-20 bits differ between consecutive frames).
# Set well above zero so we catch frames that look identical but aren't byte-equal
# due to anti-aliasing jitter; well below 32 so a genuinely-changing frame passes.
DIFF_THRESHOLD_BITS = 4


def _read_png(path: Path) -> tuple[int, int, bytes]:
    """Minimal PNG reader. Returns (width, height, raw RGBA bytes).

    Implements just enough of the PNG spec to decode the screenshots our
    chrome MCP produces. No external dependencies.
    """
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    pos = 8
    width = height = 0
    bit_depth = color_type = 0
    idat_chunks = []
    while pos < len(data):
        chunk_len = int.from_bytes(data[pos : pos + 4], "big")
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + chunk_len]
        pos += 12 + chunk_len  # 4 len + 4 type + data + 4 crc
        if chunk_type == b"IHDR":
            width = int.from_bytes(chunk_data[0:4], "big")
            height = int.from_bytes(chunk_data[4:8], "big")
            bit_depth = chunk_data[8]
            color_type = chunk_data[9]
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break
    if bit_depth != 8 or color_type not in (2, 6):
        raise ValueError(
            f"unsupported PNG format (bit_depth={bit_depth}, color_type={color_type})"
        )
    bpp = 3 if color_type == 2 else 4
    raw = zlib.decompress(b"".join(idat_chunks))
    # Un-filter scanlines. PNG prepends 1 filter byte to each row.
    stride = width * bpp
    out = bytearray(width * height * bpp)
    prev_row = bytes(stride)
    for y in range(height):
        line_start = y * (stride + 1)
        filter_type = raw[line_start]
        row = bytearray(raw[line_start + 1 : line_start + 1 + stride])
        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for x in range(bpp, stride):
                row[x] = (row[x] + row[x - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for x in range(stride):
                row[x] = (row[x] + prev_row[x]) & 0xFF
        elif filter_type == 3:  # Average
            for x in range(stride):
                left = row[x - bpp] if x >= bpp else 0
                row[x] = (row[x] + (left + prev_row[x]) // 2) & 0xFF
        elif filter_type == 4:  # Paeth
            for x in range(stride):
                left = row[x - bpp] if x >= bpp else 0
                up = prev_row[x]
                up_left = prev_row[x - bpp] if x >= bpp else 0
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                if pa <= pb and pa <= pc:
                    pred = left
                elif pb <= pc:
                    pred = up
                else:
                    pred = up_left
                row[x] = (row[x] + pred) & 0xFF
        else:
            raise ValueError(f"unknown PNG filter type {filter_type}")
        out[y * stride : y * stride + stride] = row
        prev_row = bytes(row)
    return width, height, bytes(out)


def _fingerprint(width: int, height: int, pixels: bytes) -> int:
    """64-bit fingerprint: average-hash style.

    Downsample to 8x8 grayscale, then bit-set per cell if cell >= mean.
    Robust to compression noise and minor anti-aliasing jitter but
    sensitive to any meaningful pixel motion.
    """
    bpp = len(pixels) // (width * height)
    cw = width // 8
    ch = height // 8
    if cw == 0 or ch == 0:
        # image too small for 8x8 downsample; hash directly
        return zlib.crc32(pixels) & 0xFFFFFFFFFFFFFFFF
    cells = []
    for cy in range(8):
        for cx in range(8):
            r_sum = g_sum = b_sum = n = 0
            for y in range(cy * ch, (cy + 1) * ch):
                row_off = y * width * bpp
                for x in range(cx * cw, (cx + 1) * cw):
                    p = row_off + x * bpp
                    r_sum += pixels[p]
                    g_sum += pixels[p + 1]
                    b_sum += pixels[p + 2]
                    n += 1
            # luma approximation: 0.299r + 0.587g + 0.114b
            cells.append((299 * r_sum + 587 * g_sum + 114 * b_sum) // (1000 * n))
    mean = sum(cells) // 64
    bits = 0
    for i, v in enumerate(cells):
        if v >= mean:
            bits |= 1 << i
    return bits


def diff_screens(path_a: Path, path_b: Path) -> tuple[int, str]:
    """Return (hamming_distance, status_message)."""
    w1, h1, pa = _read_png(path_a)
    w2, h2, pb = _read_png(path_b)
    if (w1, h1) != (w2, h2):
        return 64, f"size mismatch {w1}x{h1} vs {w2}x{h2}"
    fa = _fingerprint(w1, h1, pa)
    fb = _fingerprint(w2, h2, pb)
    bits_differ = bin(fa ^ fb).count("1")
    return bits_differ, f"fingerprint hamming distance = {bits_differ}/64"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: gameplay_diff_check.py <png_a> <png_b>", file=sys.stderr)
        return 2
    a, b = Path(sys.argv[1]), Path(sys.argv[2])
    distance, msg = diff_screens(a, b)
    if distance < DIFF_THRESHOLD_BITS:
        print(f"STUCK: {msg} (< {DIFF_THRESHOLD_BITS} threshold)", file=sys.stderr)
        return 1
    print(f"LIVE: {msg} (>= {DIFF_THRESHOLD_BITS} threshold)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
