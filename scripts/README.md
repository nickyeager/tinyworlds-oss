# TinyWorlds scripts

Run from the repository root. Runtime output, credentials and generated games
stay outside source control.

| Purpose | Commands |
| --- | --- |
| Install the local app | `bash scripts/setup_environment.sh` |
| Start both services | `bash scripts/start_dev.sh` |
| Start only the API | `bash scripts/start_api.sh` |
| Diagnose installation | `.venv/bin/python scripts/local_dev.py check` |
| Verify startup/shutdown in a disposable checkout | `.venv/bin/python scripts/check_local_startup.py` |
| Refresh staged source coverage | `python3 scripts/refresh_release_manifest.py` |
| Verify source hashes and documentation links | `python3 scripts/check_release_snapshot.py . --tracked` |
| Prepare a source-only distribution | `prepare_release_snapshot.py` |
| Bevy builds (experimental) | `bevy_build.sh` |
| Playback/worker verification | `play_probe.py`, `play_cdp_input.py`, `gameplay_diff_check.py`, `verify_agent_worker.py`, `verify_private_playback.py` |
| Evaluations/streaming | `run_evals.sh`, `test_resilient_stream.py` |
| Plugin packaging | `package_openai_plugin.py` |
| Upstream tracking/failure analysis | `check_godogen_upstream.py`, `check_upstreams.py`, `companion_scout.py`, `distill_failures.py` |
| Data maintenance (inspect before use) | `assign_game_owners.py`, `backfill_touch_controls.py`, `cleanup_test_data.sh` |

Local setup never runs migrations or overwrites existing configuration. Startup
uses loopback ports, leaves provider selection intact, and stops only the child
process groups it creates. See the [setup guide](../docs/guides/setup.md).

Private deployment scripts, historical experiments and their restoration records
are not included in this source distribution.
