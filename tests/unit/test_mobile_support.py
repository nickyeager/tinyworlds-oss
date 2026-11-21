"""Unit tests for the mobile play shim (pure HTML rewrite, no app).

The per-engine route tests (tests/api/test_godot_play_mobile.py,
tests/api/test_bevy_routes.py) assert each play endpoint *wires* the shim;
the pure-function behavior lives here once.
"""
from __future__ import annotations

from src.api.services.mobile_support import inject_mobile_play_shim


def test_inject_mobile_play_shim_is_idempotent():
    html = "<html><head></head><body><canvas></canvas></body></html>"
    once = inject_mobile_play_shim(html)
    twice = inject_mobile_play_shim(once)
    assert twice.count("tinyworlds-mobile-overlay-style") == 1
    assert twice.count("tinyworlds-mobile-overlay-script") == 1
    assert twice.count('id="tinyworlds-mobile-overlay"') == 1
