#!/usr/bin/env python3
"""Report what's drifted between our vendored skills and their upstream repo.

Covers the upstream TinyWorlds depends on:

  - **godogen** (htdt/godogen)
    Vendored via `git subtree --prefix=.claude/skills/godogen`. Last
    pulled SHA is encoded in the most recent "Squashed '.claude/skills/godogen/'
    changes from X..Y" commit subject in our history.

For the upstream we:
  1. Detect the SHA we're currently on.
  2. Ask GitHub for ``ahead/behind`` + the commit list since that SHA.
  3. Categorize each commit:
       - BACKPORT  : touches files we already vendor (high probability we
                     want the change)
       - REVIEW    : new file paths or doc-only edits (worth a look but
                     not auto-applicable)
       - SKIP      : adds a new engine / subtree we don't use, README
                     polish, license, etc.
  4. Print a one-page report. Exit 0 if there's nothing to do, 1 if
     anything is BACKPORT (so this can be wired into CI later).

Usage:
    python scripts/check_upstreams.py            # report
    python scripts/check_upstreams.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


GODOGEN_REPO = "htdt/godogen"
GODOGEN_PREFIX = ".claude/skills/godogen/"

# Babylon support is a new engine path we don't use; same for Bevy when it
# lands. Heuristic skip rules — if the file path starts with any of these
# we tag the commit SKIP (unless it ALSO touches a vendored file, in which
# case BACKPORT wins).
GODOGEN_SKIP_PREFIXES = [
    "babylon/",
    "scripts/publish/",
    "publish.sh",
    "CHANGELOG.md",
    "README.md",
    "setup.md",
    "AGENTS.md",
    "docs/PROJECT.md",
    "LICENSE",
]

# Paths we DO vendor under .claude/skills/godogen/. If an upstream commit
# touches anything under these, it's a BACKPORT candidate.
GODOGEN_VENDORED_PREFIXES = [
    "prompts/",
    "engines/godot.md",
    "engines/godot-gdscript.md",
    "engines/bevy.md",
    "asset-gen/",
    "godot/",
    "shared/",
    ".claude/skills/godogen/",  # if upstream restructures
]


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------


@dataclass
class CommitInfo:
    sha: str
    short_sha: str
    date: str
    subject: str
    categorization: str = "REVIEW"
    touched_vendored: list[str] = field(default_factory=list)
    touched_other: list[str] = field(default_factory=list)
    why: str = ""


@dataclass
class UpstreamReport:
    repo: str
    detected_sha: str
    head_sha: str | None
    ahead: int
    behind: int
    commits: list[CommitInfo]
    error: str | None = None


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _gh(*args: str) -> str:
    """Wrapper for `gh api` that raises a friendly error on failure.

    We use `gh` rather than `requests` so the script doesn't need a
    GitHub token in the environment — `gh` reuses the one the developer
    already authed for `gh pr` etc.
    """
    proc = subprocess.run(
        ["gh", "api", *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh api failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    return proc.stdout


# ----------------------------------------------------------------------
# SHA detection
# ----------------------------------------------------------------------


def detect_godogen_sha() -> str | None:
    """Read our last subtree-pull head SHA from the most recent
    ``Squashed '.claude/skills/godogen/' changes from X..Y`` commit."""
    provenance = Path(__file__).resolve().parents[1] / "vendor/godogen-runtime/PROVENANCE.md"
    if provenance.is_file():
        pin = re.search(r"Immutable upstream commit: `([a-f0-9]{40})`", provenance.read_text())
        if pin:
            return pin.group(1)
    log = _git("log", "--all", "--grep=^Squashed ", "--format=%s")
    for line in log.splitlines():
        m = re.match(
            r"^Squashed '\.claude/skills/godogen/' changes from [a-f0-9]+\.\.([a-f0-9]+)$",
            line,
        )
        if m:
            return m.group(1)
    # Fallback: "Squashed '.claude/skills/godogen/' content from commit SHA"
    for line in log.splitlines():
        m = re.match(
            r"^Squashed '\.claude/skills/godogen/' content from commit ([a-f0-9]+)$",
            line,
        )
        if m:
            return m.group(1)
    return None


# ----------------------------------------------------------------------
# Compare + categorize
# ----------------------------------------------------------------------


def _path_starts_with_any(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(p) for p in prefixes)


def _categorize_commit(
    files: list[dict],
    vendored_prefixes: Iterable[str],
    skip_prefixes: Iterable[str],
) -> tuple[str, str, list[str], list[str]]:
    """Returns (category, why, touched_vendored, touched_other).

    BACKPORT > REVIEW > SKIP in priority — a single touched-vendored
    file outranks any number of SKIP files in the same commit.
    """
    touched_vendored: list[str] = []
    touched_other: list[str] = []
    skip_only = True
    for f in files:
        fn = f.get("filename", "")
        if _path_starts_with_any(fn, vendored_prefixes):
            touched_vendored.append(fn)
        else:
            touched_other.append(fn)
        if not _path_starts_with_any(fn, skip_prefixes):
            skip_only = False

    if touched_vendored:
        return (
            "BACKPORT",
            f"touches {len(touched_vendored)} file(s) under vendored paths",
            touched_vendored,
            touched_other,
        )
    if skip_only:
        return (
            "SKIP",
            "only touches files under known-skip prefixes "
            "(README, license, other engine subtrees)",
            touched_vendored,
            touched_other,
        )
    return (
        "REVIEW",
        "touches files outside our vendored subset — could be a new "
        "feature that adjacent vendored paths reference",
        touched_vendored,
        touched_other,
    )


def _build_report(
    repo: str,
    detected_sha: str,
    vendored_prefixes: Iterable[str],
    skip_prefixes: Iterable[str],
) -> UpstreamReport:
    try:
        default_branch = json.loads(_gh(f"repos/{repo}"))["default_branch"]
    except Exception as e:
        return UpstreamReport(
            repo=repo, detected_sha=detected_sha, head_sha=None,
            ahead=0, behind=0, commits=[], error=f"could not resolve default branch: {e}",
        )

    try:
        compare = json.loads(_gh(f"repos/{repo}/compare/{detected_sha}...{default_branch}"))
    except Exception as e:
        return UpstreamReport(
            repo=repo, detected_sha=detected_sha, head_sha=None,
            ahead=0, behind=0, commits=[], error=f"compare failed: {e}",
        )

    ahead = compare.get("ahead_by", 0)
    behind = compare.get("behind_by", 0)
    head_sha = (compare.get("base_commit") or {}).get("sha") or detected_sha
    # The compare endpoint returns commit metadata BUT not per-commit
    # file diffs — for that we'd need N commit lookups. We approximate by
    # using the aggregate `files` field for now and tagging every commit
    # the same way. For accurate per-commit tagging fetch each commit.
    commits_data = compare.get("commits", [])
    commits: list[CommitInfo] = []
    for c in commits_data:
        sha = c.get("sha", "")
        # Per-commit file lookup (extra API call each — fine for the
        # small N=10ish range we see in practice).
        try:
            detail = json.loads(_gh(f"repos/{repo}/commits/{sha}"))
            files = detail.get("files", [])
        except Exception:
            files = []
        cat, why, t_v, t_o = _categorize_commit(files, vendored_prefixes, skip_prefixes)
        commits.append(
            CommitInfo(
                sha=sha,
                short_sha=sha[:8],
                date=(c.get("commit") or {}).get("author", {}).get("date", "")[:10],
                subject=(c.get("commit") or {}).get("message", "").split("\n")[0],
                categorization=cat,
                touched_vendored=t_v,
                touched_other=t_o,
                why=why,
            )
        )

    return UpstreamReport(
        repo=repo,
        detected_sha=detected_sha,
        head_sha=head_sha,
        ahead=ahead,
        behind=behind,
        commits=commits,
    )


def check_godogen() -> UpstreamReport:
    sha = detect_godogen_sha()
    if not sha:
        return UpstreamReport(
            repo=GODOGEN_REPO, detected_sha="(unknown)", head_sha=None,
            ahead=0, behind=0, commits=[],
            error="could not detect last subtree-pulled SHA from git history",
        )
    return _build_report(
        GODOGEN_REPO, sha, GODOGEN_VENDORED_PREFIXES, GODOGEN_SKIP_PREFIXES,
    )


# ----------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------


def _format_text(reports: list[UpstreamReport]) -> str:
    lines: list[str] = []
    any_backport = False
    for r in reports:
        lines.append("")
        lines.append("=" * 72)
        lines.append(f"{r.repo}")
        lines.append("=" * 72)
        if r.error:
            lines.append(f"  ⚠ {r.error}")
            continue
        lines.append(f"  pinned to:  {r.detected_sha[:12]}")
        lines.append(f"  ahead/behind: {r.ahead}/{r.behind}")
        if r.ahead == 0:
            lines.append("  ✓ up to date — nothing to do")
            continue
        b = [c for c in r.commits if c.categorization == "BACKPORT"]
        rv = [c for c in r.commits if c.categorization == "REVIEW"]
        sk = [c for c in r.commits if c.categorization == "SKIP"]
        lines.append(f"  BACKPORT: {len(b)}   REVIEW: {len(rv)}   SKIP: {len(sk)}")
        if b:
            any_backport = True
            lines.append("")
            lines.append("  ▼ BACKPORT (touches files we vendor):")
            for c in b:
                lines.append(f"    {c.date}  {c.short_sha}  {c.subject}")
                for fn in c.touched_vendored[:6]:
                    lines.append(f"      ↳ {fn}")
                if len(c.touched_vendored) > 6:
                    lines.append(f"      ↳ … +{len(c.touched_vendored) - 6} more")
        if rv:
            lines.append("")
            lines.append("  ⚠ REVIEW (worth a look):")
            for c in rv:
                lines.append(f"    {c.date}  {c.short_sha}  {c.subject}")
                lines.append(f"      ↳ {c.why}")
        if sk:
            lines.append("")
            lines.append("  · SKIP (not in our subset):")
            for c in sk:
                lines.append(f"    {c.date}  {c.short_sha}  {c.subject}")

    lines.append("")
    if any_backport:
        lines.append("=" * 72)
        lines.append("ACTION REQUIRED: at least one BACKPORT candidate above.")
        lines.append("=" * 72)
    else:
        lines.append("Nothing actionable. Run again next time you have a stale cache.")
    return "\n".join(lines)


def _format_json(reports: list[UpstreamReport]) -> str:
    def as_dict(c: CommitInfo) -> dict:
        return {
            "sha": c.sha,
            "short_sha": c.short_sha,
            "date": c.date,
            "subject": c.subject,
            "categorization": c.categorization,
            "touched_vendored": c.touched_vendored,
            "touched_other": c.touched_other,
            "why": c.why,
        }
    payload = [
        {
            "repo": r.repo,
            "detected_sha": r.detected_sha,
            "head_sha": r.head_sha,
            "ahead": r.ahead,
            "behind": r.behind,
            "error": r.error,
            "commits": [as_dict(c) for c in r.commits],
        }
        for r in reports
    ]
    return json.dumps(payload, indent=2)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument(
        "--json", action="store_true", help="emit JSON instead of text"
    )
    p.add_argument(
        "--repo",
        choices=("godogen", "all"),
        default="all",
        help="restrict to one upstream",
    )
    args = p.parse_args()

    reports: list[UpstreamReport] = []
    if args.repo in ("godogen", "all"):
        reports.append(check_godogen())

    if args.json:
        print(_format_json(reports))
    else:
        print(_format_text(reports))

    # Exit 1 if any BACKPORT — lets CI/cron call this and fail-loud when
    # there's drift worth fixing.
    for r in reports:
        if any(c.categorization == "BACKPORT" for c in r.commits):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
