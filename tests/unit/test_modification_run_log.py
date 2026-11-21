import json
from pathlib import Path

from src.api.services.game_event_log import GameEventLog
from src.api.services.modification_run_log import (
    build_modification_summary,
    infer_changed_files,
    infer_image_outputs,
    list_modification_runs,
    read_modification_run,
    reference_attachments,
)


def test_uploaded_reference_survives_both_history_and_event_reload(tmp_path: Path):
    game = tmp_path / "godot-reference"
    uploads = game / "_user_uploads"
    uploads.mkdir(parents=True)
    image = uploads / "palette.png"
    image.write_bytes(b"image fixture")
    instruction = f"Use this palette\n\nReference image attached at: {image}\nUse the Read tool to view this image."
    log = GameEventLog(game, log_dir=".modifications/reference1")
    log.append({"event_type": "init", "metadata": {"instruction": instruction}})
    expected = [{"path": "_user_uploads/palette.png", "name": "palette.png", "media_type": "image/png"}]
    # Running runs have no summary; completed legacy summaries have no attachment field.
    assert list_modification_runs(game, game_id=game.name, engine="godot")[0]["attachments"] == expected
    log.write_summary({"run_id": "reference1", "instruction": instruction, "status": "success"})
    assert read_modification_run(game, game_id=game.name, engine="godot", run_id="reference1")["summary"]["attachments"] == expected
    assert list_modification_runs(game, game_id=game.name, engine="godot")[0]["attachments"] == expected


def test_reference_metadata_never_exposes_other_games_or_symlink_targets(tmp_path: Path):
    game = tmp_path / "godot-reference"
    uploads = game / "_user_uploads"
    uploads.mkdir(parents=True)
    outside = tmp_path / "private.png"
    outside.write_bytes(b"private fixture")
    (uploads / "linked.png").symlink_to(outside)
    for candidate in (outside, uploads / "linked.png", uploads / "missing.png", uploads / ".." / ".." / "private.png"):
        assert reference_attachments(game, f"Look\n\nReference image attached at: {candidate}\n") == []


def test_build_summary_has_normalized_debug_fields(tmp_path: Path):
    summary = build_modification_summary(
        game_id="godot-test",
        engine="godot",
        run_id="abc123",
        instruction="make it faster",
        status="partial",
        started_at="2026-06-05T00:00:00Z",
        finished_at="2026-06-05T00:00:02Z",
        duration_seconds=2.123,
        event_count=4,
        final_message="dist/index.wasm missing",
        error="dist/index.wasm missing",
        has_export=True,
        has_playable_build=False,
        verification_failures=["dist/index.wasm missing"],
        events=[{"metadata": {"changed_files": ["scripts/player.gd"]}}],
        new_screenshots=["screenshots/after.png"],
        export_status="success",
    )

    assert summary["run_id"] == "abc123"
    assert summary["instruction"] == "make it faster"
    assert summary["status"] == "partial"
    assert summary["duration_seconds"] == 2.12
    assert summary["changed_files"] == ["scripts/player.gd"]
    assert summary["verification_failures"] == ["dist/index.wasm missing"]
    assert summary["new_screenshots"] == ["screenshots/after.png"]


def test_infer_changed_files_deduplicates_metadata():
    events = [
        {"metadata": {"changed_files": ["src/main.rs", "src/main.rs"]}},
        {"metadata": {"file_path": "Cargo.toml"}},
        {"metadata": {"path": ""}},
    ]

    assert infer_changed_files(events) == ["src/main.rs", "Cargo.toml"]


def test_image_outputs_survive_summary_without_turning_plans_into_images():
    events = [
        {"type": "thinking", "content": "I could create assets/not-made.png"},
        {"type": "tool_result", "content": "Saved /work/game/assets/sky.png"},
        {"type": "tool_result", "content": "Saved assets/sky.png"},
        {"type": "tool_result", "content": "assets/failed.png", "metadata": {"success": False}},
        {"type": "tool_result", "content": "assets/../../private.png"},
    ]
    assert infer_image_outputs(events) == ["assets/sky.png"]


def test_list_and_read_modification_runs(tmp_path: Path):
    game_path = tmp_path / "godot-test"
    run_a = GameEventLog(game_path, log_dir=".modifications/runaaa")
    run_a.append({
        "event_type": "init",
        "metadata": {
            "run_id": "runaaa",
            "instruction": "add coins",
            "engine": "godot",
        },
    })
    run_a.write_summary({
        "run_id": "runaaa",
        "game_id": "godot-test",
        "engine": "godot",
        "instruction": "add coins",
        "status": "success",
        "started_at": "2026-06-05T00:00:00Z",
    })

    run_b = GameEventLog(game_path, log_dir=".modifications/runbbb")
    run_b.append({
        "event_type": "init",
        "metadata": {
            "run_id": "runbbb",
            "instruction": "add enemies",
            "engine": "godot",
        },
    })
    run_b.write_summary({
        "run_id": "runbbb",
        "game_id": "godot-test",
        "engine": "godot",
        "instruction": "add enemies",
        "status": "failed",
        "started_at": "2026-06-05T00:01:00Z",
    })

    runs = list_modification_runs(game_path, game_id="godot-test", engine="godot")
    assert [r["run_id"] for r in runs] == ["runbbb", "runaaa"]

    detail = read_modification_run(
        game_path,
        game_id="godot-test",
        engine="godot",
        run_id="runaaa",
    )
    assert detail["summary"]["instruction"] == "add coins"
    assert detail["events"][0]["event_type"] == "init"


def test_read_modification_run_falls_back_for_running_log(tmp_path: Path):
    game_path = tmp_path / "bevy-test"
    event_log = GameEventLog(game_path, log_dir=".modifications/running1")
    event_log.append({
        "event_type": "init",
        "metadata": {
            "run_id": "running1",
            "instruction": "make jump higher",
            "engine": "bevy",
        },
    })

    detail = read_modification_run(
        game_path,
        game_id="bevy-test",
        engine="bevy",
        run_id="running1",
    )

    assert detail["summary"]["status"] == "running"
    assert detail["summary"]["instruction"] == "make jump higher"
    assert json.dumps(detail["events"])


async def test_cancelled_job_replays_as_interrupted_in_history(tmp_path: Path):
    import asyncio

    from src.api.services.game_jobs import cancel_job, start_job

    game_path = tmp_path / "godot-cancelled-editor"
    log = GameEventLog(game_path, log_dir=".modifications/cancelled1")
    started_at = "2026-10-14T17:00:00Z"
    log.append({
        "event_type": "init",
        "timestamp": started_at,
        "metadata": {"run_id": "cancelled1", "instruction": "make the jump smoother"},
    })
    task = start_job(game_path.name, asyncio.Event().wait(), log)
    await asyncio.sleep(0)
    assert await cancel_job(game_path.name) is True
    assert task.cancelled()

    runs = list_modification_runs(game_path, game_id=game_path.name, engine="godot")
    detail = read_modification_run(
        game_path, game_id=game_path.name, engine="godot", run_id="cancelled1",
    )
    assert len(runs) == 1
    assert runs[0]["status"] == "interrupted"
    assert runs[0]["started_at"] == started_at
    assert runs[0]["instruction"] == "make the jump smoother"
    assert detail["summary"] == runs[0]
    assert detail["events"][-1]["event_type"] == "interrupted"
    assert "cancelled" in runs[0]["error"]


def test_agent_completion_alone_keeps_modification_running(tmp_path: Path):
    game_path = tmp_path / "godot-verifying-editor"
    log = GameEventLog(game_path, log_dir=".modifications/verifying1")
    log.append({"event_type": "init", "metadata": {"instruction": "make it brighter"}})
    log.append({"type": "complete", "content": "Source updated"})
    runs = list_modification_runs(game_path, game_id=game_path.name, engine="godot")
    assert runs[0]["status"] == "running"
    log.append({"event_type": "failed", "content": "Browser verification failed"})
    runs = list_modification_runs(game_path, game_id=game_path.name, engine="godot")
    assert runs[0]["status"] == "failed"
    assert runs[0]["error"] == "Browser verification failed"
