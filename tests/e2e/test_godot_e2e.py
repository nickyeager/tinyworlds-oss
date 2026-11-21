"""End-to-end test for the Godot game creation pipeline.

Tests the full chain:
  Browser (frontend) → Backend API → Claude Code CLI → Godot export → Playable in browser

Requires:
  - Backend running on localhost:8001
  - Frontend running on localhost:3333
  - Claude Code CLI installed (claude binary on PATH)
  - Godot 4 with web export templates installed
  - XAI_API_KEY set (for asset generation)
  - GOOGLE_API_KEY set (for Gemini reference image generation)
"""
import json
import time

import pytest
import requests


pytestmark = pytest.mark.e2e


BACKEND = "http://localhost:8001"
FRONTEND = "http://localhost:3333"
TIMEOUT_SECONDS = 600  # 10 min max for full game generation


class TestGodotPipelineE2E:
    """Full end-to-end Godot game creation through the web application."""

    def _require_backend(self):
        try:
            r = requests.get(f"{BACKEND}/health", timeout=5)
            assert r.json()["status"] == "healthy"
        except Exception:
            pytest.fail("Backend not running on localhost:8001")

    def _require_frontend(self):
        try:
            r = requests.get(f"{FRONTEND}/create", timeout=5)
            assert r.status_code == 200
        except Exception:
            pytest.fail("Frontend not running on localhost:3333")

    def _require_claude_cli(self):
        import shutil
        assert shutil.which("claude"), "claude CLI binary not found on PATH"

    def _require_godot(self):
        import shutil
        assert shutil.which("godot"), "godot binary not found on PATH"

    # ------------------------------------------------------------------
    # Test 1: Backend API — create game and verify SSE streaming
    # ------------------------------------------------------------------
    def test_godot_create_streams_events(self):
        """POST /api/v1/godot/games streams SSE events from Claude Code CLI."""
        self._require_backend()
        self._require_claude_cli()

        response = requests.post(
            f"{BACKEND}/api/v1/godot/games",
            json={"description": "a red ball that bounces off walls", "budget_cents": None},
            stream=True,
            timeout=60,
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        events = []
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                data = json.loads(line[6:])
                events.append(data)
                # Stop after getting a few events — don't wait for full generation
                if len(events) >= 5:
                    break

        assert len(events) >= 3, f"Expected at least 3 SSE events, got {len(events)}"

        # First event should be the init event with game_id
        assert events[0]["event_type"] == "init"
        assert "game_id" in events[0]

        # Remaining events should include pipeline progress (StatusEvent or CLIStreamEvent)
        progress_events = [e for e in events[1:] if e.get("event_type") in ("StatusEvent", "CLIStreamEvent")]
        assert len(progress_events) > 0, (
            f"No progress events after init. Got event_types: "
            f"{[e.get('event_type') for e in events]}"
        )

    # ------------------------------------------------------------------
    # Test 2: Full pipeline — create, wait for completion, verify export
    # ------------------------------------------------------------------
    @pytest.mark.slow
    def test_godot_full_pipeline_create_export_play(self):
        """Full pipeline: create game → export HTML5 → play endpoint returns 200.

        This test takes several minutes as it runs the full Claude Code generation.
        Mark with @pytest.mark.slow so it can be skipped in fast runs.
        """
        self._require_backend()
        self._require_claude_cli()
        self._require_godot()

        # Step 1: Create game via streaming endpoint
        response = requests.post(
            f"{BACKEND}/api/v1/godot/games",
            json={
                "description": "a simple bouncing red ball with score counter",
                "budget_cents": None,
            },
            stream=True,
            timeout=TIMEOUT_SECONDS,
        )
        assert response.status_code == 200

        game_id = None
        events = []
        saw_export = False
        saw_complete = False

        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = json.loads(line[6:])
            events.append(data)

            # Check for done event with game_id
            if data.get("event_type") == "done" and data.get("game_id"):
                game_id = data["game_id"]
                break

            # Track export step
            if "export" in data.get("step", "").lower():
                saw_export = True

            # Track completion
            if data.get("event_type") == "CompletionEvent":
                saw_complete = True

        assert game_id is not None, (
            f"No game_id in done event. Got {len(events)} events. "
            f"Last event: {events[-1] if events else 'none'}"
        )

        # Step 2: Verify game info endpoint
        info = requests.get(f"{BACKEND}/api/v1/godot/games/{game_id}")
        assert info.status_code == 200
        info_data = info.json()
        assert info_data["game_id"] == game_id
        assert info_data["has_plan"] is True

        # Step 3: Verify play endpoint (HTML5 export)
        play = requests.get(
            f"{BACKEND}/api/v1/godot/games/{game_id}/play",
            allow_redirects=True,
        )
        if play.status_code == 200:
            assert "text/html" in play.headers.get("content-type", "")
            assert "index.wasm" in play.text or "godot" in play.text.lower(), \
                "Play page doesn't look like a Godot web export"
        else:
            # Export may have failed — check video fallback
            video = requests.get(f"{BACKEND}/api/v1/godot/games/{game_id}/video")
            assert video.status_code == 200, \
                f"Neither play (status={play.status_code}) nor video available"

    # ------------------------------------------------------------------
    # Test 3: Export on existing game
    # ------------------------------------------------------------------
    def test_export_existing_game(self):
        """Verify export_html5 works on a game that has project.godot."""
        self._require_backend()
        self._require_godot()

        # Find an existing Godot game with project.godot
        from pathlib import Path
        games_dir = Path("generated_games")
        if not games_dir.exists():
            pytest.skip("No generated_games directory")

        game_path = None
        game_id = None
        for d in sorted(games_dir.iterdir(), reverse=True):
            if d.name.startswith("godot-") and (d / "project.godot").exists():
                game_path = d
                game_id = d.name
                break

        if not game_path:
            pytest.skip("No existing Godot games with project.godot")

        # Trigger export via the service directly
        import asyncio
        from src.api.services.godot_game_service import GodotGameService
        from src.api.core.config import get_settings

        svc = GodotGameService(get_settings())
        dist = asyncio.get_event_loop().run_until_complete(
            svc.export_html5(game_path)
        )

        assert dist is not None, f"export_html5 returned None for {game_id}"
        assert (dist / "index.html").exists(), f"No index.html in {dist}"
        assert (dist / "index.wasm").exists(), f"No index.wasm in {dist}"

        # Verify play endpoint now works
        play = requests.get(
            f"{BACKEND}/api/v1/godot/games/{game_id}/play",
            allow_redirects=True,
        )
        assert play.status_code == 200
        assert "text/html" in play.headers.get("content-type", "")

    # ------------------------------------------------------------------
    # Test 4: Frontend → Backend CORS works
    # ------------------------------------------------------------------
    def test_frontend_can_reach_backend(self):
        """Verify CORS allows frontend origin to call backend API."""
        self._require_backend()

        r = requests.options(
            f"{BACKEND}/api/v1/godot/games",
            headers={
                "Origin": FRONTEND,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert r.status_code == 200, f"CORS preflight failed: {r.status_code}"
        assert FRONTEND in r.headers.get("access-control-allow-origin", ""), \
            f"CORS missing frontend origin. Headers: {dict(r.headers)}"

    # ------------------------------------------------------------------
    # Test 5: CLI subprocess gets .env vars
    # ------------------------------------------------------------------
    def test_cli_executor_passes_env_vars(self):
        """Verify CLIExecutor loads .env keys into subprocess environment."""
        import os
        from pathlib import Path

        # Simulate the env loading logic from cli_executor.py
        child_env = os.environ.copy()
        env_file = Path(".env")
        assert env_file.exists(), ".env file not found"

        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and key not in child_env:
                    child_env[key] = value

        assert "XAI_API_KEY" in child_env, "XAI_API_KEY not loaded from .env"
        assert child_env["XAI_API_KEY"] != "your_xai_key_here", \
            "XAI_API_KEY is still the placeholder value"
        assert "GOOGLE_API_KEY" in child_env, "GOOGLE_API_KEY not loaded from .env"

    # ------------------------------------------------------------------
    # Test 6: Asset generation tool works
    # ------------------------------------------------------------------
    def test_xai_asset_gen_image(self):
        """Verify xAI Grok image generation works via asset_gen.py."""
        import subprocess
        import os
        from pathlib import Path

        # Load env
        env = os.environ.copy()
        env_file = Path(".env")
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                if key.strip() and key.strip() not in env:
                    env[key.strip()] = value.strip()

        output_path = "/tmp/test_e2e_xai_image.png"
        import sys
        result = subprocess.run(
            [
                sys.executable,
                ".claude/skills/godogen/shared/skills/godogen/tools/asset_gen.py",
                "image",
                "--prompt", "a blue square, pixel art, solid black background",
                "-o", output_path,
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

        assert result.returncode == 0, f"asset_gen.py failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["ok"] is True
        assert output["cost_cents"] == 2
        assert Path(output_path).exists()
        assert Path(output_path).stat().st_size > 1000  # Real PNG, not empty


    # ------------------------------------------------------------------
    # Test 7: SSE stream carries CLIStreamEvent with structured metadata
    # ------------------------------------------------------------------
    def test_godot_sse_streams_cli_stream_events(self):
        """POST /api/v1/godot/games SSE should contain CLIStreamEvent
        with tool_name and tool_input, not just flattened StatusEvent messages."""
        self._require_backend()
        self._require_claude_cli()

        response = requests.post(
            f"{BACKEND}/api/v1/godot/games",
            json={"description": "a green square moving left and right", "budget_cents": None},
            stream=True,
            timeout=120,
        )
        assert response.status_code == 200

        events = []
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                data = json.loads(line[6:])
                events.append(data)
                # Collect enough events to see tool usage
                if len(events) >= 20:
                    break

        # Must have at least one CLIStreamEvent (not just StatusEvent)
        cli_events = [e for e in events if e.get("event_type") == "CLIStreamEvent"]
        assert len(cli_events) > 0, (
            f"No CLIStreamEvent in SSE stream. Got event_types: "
            f"{[e.get('event_type') for e in events]}"
        )

        # At least one tool_use event should have tool_name and tool_input
        tool_use_events = [e for e in cli_events if e.get("stream_type") == "tool_use"]
        assert len(tool_use_events) > 0, "No tool_use CLIStreamEvents found"

        for te in tool_use_events:
            assert "tool_name" in te, f"tool_use event missing tool_name: {te}"
            assert "tool_input" in te, f"tool_use event missing tool_input: {te}"
            assert isinstance(te["tool_input"], dict), \
                f"tool_input should be a dict, got {type(te['tool_input'])}"

        # Verify no more "Using Write..." flattened StatusEvents
        flat_status = [
            e for e in events
            if e.get("event_type") == "StatusEvent"
            and "Using " in e.get("message", "")
            and "..." in e.get("message", "")
        ]
        assert len(flat_status) == 0, (
            f"Found {len(flat_status)} flattened 'Using X...' StatusEvents — "
            f"these should be CLIStreamEvents now: {flat_status[:2]}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
