#!/usr/bin/env bash
# Install the tested personal-development dependencies. Never migrate a database.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PYTHON_BIN="${TINYWORLDS_PYTHON:-python3.12}"
"$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else "Python 3.12 is required")'
node -e 'if (process.versions.node.split(".")[0] !== "22") { console.error("Node.js 22 is required"); process.exit(1) }'
(cd web && test "$(pnpm --version)" = "10.18.0") || { echo 'Install pnpm 10.18.0, as pinned in web/package.json.' >&2; exit 1; }
if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else "Existing .venv uses another Python version; move it aside and rerun setup")'
.venv/bin/python scripts/local_dev.py configure
.venv/bin/python -m pip install -r requirements.txt -c constraints-v0.1.txt
.venv/bin/python -m playwright install chromium
(cd web && pnpm install --frozen-lockfile)
.venv/bin/python scripts/local_dev.py check
printf '\nSetup complete. Start with: bash scripts/start_dev.sh\n'
