# TinyWorlds scripts

Current setup, build, verification, and maintenance tools. Run from the repository root and inspect each script's documented arguments before use.

| Purpose | Scripts |
| --- | --- |
| Local setup/startup | `setup_environment.sh`, `start_api.sh`, `start_dev.sh` |
| Deployment and DNS | `setup-vps.sh`, `cloudflare_setup.sh` |
| Bevy builds | `bevy_build.sh` |
| Playback/worker verification | `play_probe.py`, `play_cdp_input.py`, `gameplay_diff_check.py`, `verify_agent_worker.py`, `verify_private_playback.py` |
| Evaluations/streaming | `run_evals.sh`, `test_resilient_stream.py` |
| Plugin packaging | `package_openai_plugin.py` |
| Upstream tracking/failure analysis | `check_godogen_upstream.py`, `check_upstreams.py`, `companion_scout.py`, `distill_failures.py` |
| Data maintenance | `assign_game_owners.py`, `backfill_touch_controls.py`, `cleanup_test_data.sh` |
| Voice capture | `record_voice_command.sh` |

The retired template builders, KAPLAY runners, sprite probes, and legacy demos have a verified local restoration archive. See the [experiment inventory](../docs/research/2026-10-27-experiment-inventory.md) for outcomes, removed paths, and recovery instructions.
