import json

from src.api.services.runtime_diagnostics import build_runtime_diagnostics


def test_runtime_diagnostics_summarizes_browser_telemetry(tmp_path, monkeypatch):
    from src.api.services import runtime_diagnostics

    game_path = tmp_path / "godot-test"
    telemetry_dir = game_path / "telemetry"
    telemetry_dir.mkdir(parents=True)
    (telemetry_dir / "session.ndjson").write_text(
        "\n".join([
            json.dumps({
                "kind": "sample",
                "godot": {
                    "lives": 2,
                    "hazards": 3,
                    "last_event": "player_hit",
                },
                "_reason": "interval",
            }),
            json.dumps({
                "kind": "frozen",
                "drift": 4200,
                "_reason": "frozen",
            }),
        ]),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        runtime_diagnostics.default_runtime_log,
        "events_for_game",
        lambda *args, **kwargs: [],
    )

    summary = build_runtime_diagnostics(
        game_path,
        game_id="godot-test",
        engine="godot",
    )

    assert summary is not None
    assert "Runtime Diagnostics" in summary
    assert "player_hit" in summary
    assert "frozen" in summary
    assert "4200" in summary


def test_runtime_diagnostics_returns_none_without_events(tmp_path, monkeypatch):
    from src.api.services import runtime_diagnostics

    monkeypatch.setattr(
        runtime_diagnostics.default_runtime_log,
        "events_for_game",
        lambda *args, **kwargs: [],
    )

    assert build_runtime_diagnostics(
        tmp_path / "empty-game",
        game_id="empty-game",
        engine="godot",
    ) is None
