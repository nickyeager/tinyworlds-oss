#!/usr/bin/env python3
"""Check htdt/godogen for new upstream commits since our last subtree sync.

Designed to run from a scheduled remote Claude routine. Read-only — just
reports what's available. The routine decides whether to open an issue.

Output: JSON to stdout. Schema:
    {
      "in_sync": bool,
      "our_sync_point": "<sha>",            # tip of the squashed subtree commit
      "remote_tip": "<sha>",
      "new_commits": [
        {"sha": "...", "subject": "...", "files_changed": ["..."]},
        ...
      ],
      "skill_files_changed": bool,          # narrowed signal: do we care?
      "recommendation": "skip" | "review" | "sync",
    }

Recommendation logic:
  - in_sync             → skip
  - only tooling files  → review (open low-priority issue, don't auto-sync)
  - skill content       → sync (open issue; a human runs the subtree pull locally)

Network access: this talks to GitHub through `gh api` (api.github.com) only.
It deliberately does NOT add a git remote or `git fetch` the upstream repo —
the cloud sandbox this routine runs in blocks git egress to repos outside its
declared sources, and that fetch was the daily failure this script is fixing.
The one local git dependency is reading our own subtree-pull history, which
lives in this checkout (a declared source).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = "htdt/godogen"
DEFAULT_BRANCH = "master"
SUBTREE_PREFIX = ".claude/skills/godogen"

# Paths inside the upstream repo whose changes are user-facing — if any of
# these change, we want a sync. Everything else (publish scripts, README,
# setup tooling) gets a lower-priority "review" recommendation.
SKILL_PATH_PATTERNS = [
    r"^prompts/.*\.md$",
    r"^engines/(godot|godot-gdscript|bevy)\.md$",
    r"^asset-gen/",
    r"^godot/skills/.*\.md$",
    r"^bevy/skills/.*\.md$",
    r"^shared/skills/.*\.(md|py)$",
    r"^shared/hooks/.*\.(py|sh)$",  # hooks count even if disabled here
]

# Fallback sync point when no git subtree squash commit exists in history
# (e.g. subtree was imported via plain merge). Update this whenever a manual
# sync lands.
FALLBACK_SYNC_POINT = "6c289a0"


def _git(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(
            ["git", *cmd], text=True, stderr=subprocess.PIPE
        ).strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"git {' '.join(cmd)} failed: {e.stderr}") from e


def _gh_api(path: str, jq: str | None = None) -> str:
    """Call `gh api <path>` (optionally with a --jq filter).

    We use `gh` rather than `requests`/`git fetch` so the script needs no
    extra deps and no external git egress — only api.github.com, which the
    routine sandbox already permits (it opens issues the same way).
    """
    cmd = ["gh", "api", path]
    if jq is not None:
        cmd += ["--jq", jq]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"gh api {path} failed: {detail}")
    return proc.stdout.strip()


def _detect_sync_point() -> str:
    """Find the SHA of our last subtree pull's squashed commit.

    `git subtree pull --squash` writes a merge commit whose body contains
    "Squashed '<prefix>/' changes from <SHA>..<SHA>". We grep for that.
    Reads local history only — no network.
    """
    provenance = Path(__file__).resolve().parents[1] / "vendor/godogen-runtime/PROVENANCE.md"
    if provenance.is_file():
        pin = re.search(r"Immutable upstream commit: `([a-f0-9]{40})`", provenance.read_text())
        if pin:
            return pin.group(1)
    log = _git(["log", "--all", "--grep=Squashed.*godogen", "--pretty=%B"])
    m = re.search(r"changes from ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})", log)
    if not m:
        return FALLBACK_SYNC_POINT
    return m.group(2)  # the "to" SHA — that's what we synced TO


def _remote_tip() -> str:
    return _gh_api(f"repos/{REPO}/commits/{DEFAULT_BRANCH}", jq=".sha")


def _commit_files(sha: str) -> list[str]:
    raw = _gh_api(f"repos/{REPO}/commits/{sha}", jq=".files[].filename")
    return [f for f in raw.split("\n") if f.strip()]


def _list_new_commits(sync_point: str, remote_tip: str) -> list[dict]:
    if sync_point == remote_tip:
        return []
    # compare base...head returns the commits reachable from head but not base,
    # i.e. the same set as `git log base..head`.
    raw = _gh_api(f"repos/{REPO}/compare/{sync_point}...{remote_tip}")
    data = json.loads(raw)
    out = []
    for c in data.get("commits", []):
        sha = c["sha"]
        subject = c["commit"]["message"].split("\n", 1)[0]
        out.append({
            "sha": sha,
            "subject": subject,
            "files_changed": _commit_files(sha),
        })
    return out


def _has_skill_changes(commits: list[dict]) -> bool:
    for c in commits:
        for f in c["files_changed"]:
            if any(re.match(p, f) for p in SKILL_PATH_PATTERNS):
                return True
    return False


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    # cd to repo so the local `git log` (sync-point detection) works regardless
    # of where the routine runs.
    import os
    os.chdir(repo_root)

    # In the cloud sandbox GH_TOKEN may be stale while GITHUB_TOKEN is valid.
    # Prefer GITHUB_TOKEN when set, so `gh api` doesn't fail on bad GH_TOKEN.
    if os.environ.get("GITHUB_TOKEN") and not os.environ.get("GH_TOKEN"):
        os.environ["GH_TOKEN"] = os.environ["GITHUB_TOKEN"]
    elif os.environ.get("GITHUB_TOKEN") and os.environ.get("GH_TOKEN"):
        # Test GH_TOKEN; fall back to GITHUB_TOKEN if it's invalid.
        probe = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True
        )
        if probe.returncode != 0:
            os.environ["GH_TOKEN"] = os.environ["GITHUB_TOKEN"]

    remote_tip = _remote_tip()
    sync_point = _detect_sync_point()

    commits = _list_new_commits(sync_point, remote_tip)
    skill_changes = _has_skill_changes(commits)

    if not commits:
        recommendation = "skip"
    elif skill_changes:
        recommendation = "sync"
    else:
        recommendation = "review"

    report = {
        "in_sync": not commits,
        "our_sync_point": sync_point,
        "remote_tip": remote_tip,
        "new_commits": commits,
        "skill_files_changed": skill_changes,
        "recommendation": recommendation,
    }
    json.dump(report, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)
