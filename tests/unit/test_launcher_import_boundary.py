"""The privileged launcher must start without the API's signing/database keys."""
import os
from pathlib import Path
import subprocess
import sys


def test_launcher_import_does_not_initialize_api_auth(tmp_path):
    project = Path(__file__).resolve().parents[2]
    env = {key: value for key, value in os.environ.items() if key in {'PATH', 'HOME', 'LANG', 'TMPDIR'}}
    env.update(LAUNCHER_TOKEN='isolated-launcher-test-token-over-32-characters', REQUIRE_PRODUCTION_SECRETS='1', ASSET_BUDGET_ROOT=str(tmp_path / 'budget'))
    code = f"import sys;sys.path.insert(0,{str(project)!r});import src.api.sidecar_launcher;assert 'src.api.core.security' not in sys.modules"
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
