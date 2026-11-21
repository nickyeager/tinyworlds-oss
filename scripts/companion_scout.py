#!/usr/bin/env python3
"""Discover GitHub projects that could be companions/upstreams for TinyWorlds.

Runs a curated set of GitHub repo searches across the domains TinyWorlds depends
on (voxel tooling, Godot/Bevy code-gen, LLM-driven game generation, text/image->3D asset gen, browser/WASM game runtimes), aggregates and
dedupes the hits, and drops anything we already track in the report.

Like ``check_upstreams.py`` this talks to GitHub through the ``gh`` CLI (no token
needed — reuses your ``gh`` auth), so it works the same locally and inside a
cloud routine sandbox where raw ``git`` egress is blocked but ``gh api`` is not.

It does NOT judge relevance — it surfaces *candidates*. The /companion-scout
skill reads this output and curates the human-facing report. Deterministic and
side-effect-free: prints JSON (``--json``) or a short text summary.

Usage:
    python scripts/companion_scout.py                       # text summary
    python scripts/companion_scout.py --json                # machine-readable
    python scripts/companion_scout.py --report docs/research/companion-projects.md
    python scripts/companion_scout.py --min-stars 30 --limit 12
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

# (category, query) — one representative query per facet of the codebase.
# Keep the total modest: GitHub's authenticated search cap is ~30 req/min.
SEARCHES: list[tuple[str, str]] = [
    ("voxel-tooling", "voxel engine"),
    ("voxel-tooling", "magicavoxel vox"),
    ("godot-codegen", "godot ai generate game"),
    ("godot-codegen", "godot mcp llm"),
    ("bevy-ecosystem", "bevy procedural game"),
    ("llm-game-generation", "llm game generation"),
    ("llm-game-generation", "text to game ai"),
    ("text-image-to-3d", "image to 3d mesh generation"),
    ("text-image-to-3d", "text to 3d model"),
    ("browser-wasm-runtime", "wasm game engine browser"),
    ("agent-codegen", "claude code agent skill"),
]

# Repos we already depend on / are us — never surface as "new".
ALWAYS_EXCLUDE = {
    "htdt/godogen",
}

GH_JSON_FIELDS = "fullName,description,stargazersCount,url,updatedAt,createdAt,language"


def gh_search(query: str, limit: int, min_stars: int) -> list[dict]:
    """One `gh search repos` call. Returns [] on any failure (never raises)."""
    cmd = [
        "gh", "search", "repos", query,
        "--sort", "stars", "--order", "desc",
        "--limit", str(limit),
        "--stars", f">={min_stars}",
        "--json", GH_JSON_FIELDS,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  ! search '{query}' failed: {e}", file=sys.stderr)
        return []
    if out.returncode != 0:
        print(f"  ! search '{query}' gh error: {out.stderr.strip()[:160]}", file=sys.stderr)
        return []
    try:
        return json.loads(out.stdout or "[]")
    except json.JSONDecodeError:
        return []


def known_repos(report_path: str) -> set[str]:
    """Full-names (owner/repo) already listed in the report file, lowercased."""
    try:
        with open(report_path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return set()
    # Curated finds are markdown links (github.com/owner/repo); the Dismissed
    # ledger lists bare owner/repo slugs. Catch both so dismissed repos stay
    # dismissed. Stray matches (doc paths like scripts/x.py) are harmless — they
    # never equal a real gh result fullName.
    urls = re.findall(r"github\.com/([\w.\-]+/[\w.\-]+)", text)
    bare = re.findall(r"(?:^|[\s`(])([A-Za-z0-9][\w.\-]+/[\w.\-]+)", text)
    return {f.rstrip(".").lower() for f in (urls + bare)}


def collect(limit: int, min_stars: int, report_path: str) -> dict:
    exclude = {r.lower() for r in ALWAYS_EXCLUDE} | known_repos(report_path)
    seen: set[str] = set()
    candidates: list[dict] = []

    for category, query in SEARCHES:
        for repo in gh_search(query, limit, min_stars):
            full = (repo.get("fullName") or "").lower()
            if not full or full in exclude or full in seen:
                continue
            seen.add(full)
            lang = repo.get("language")
            if isinstance(lang, dict):  # gh sometimes nests it
                lang = lang.get("name")
            candidates.append({
                "category": category,
                "fullName": repo.get("fullName"),
                "url": repo.get("url"),
                "stars": repo.get("stargazersCount", 0),
                "language": lang,
                "updatedAt": repo.get("updatedAt"),
                "createdAt": repo.get("createdAt"),
                "description": (repo.get("description") or "").strip(),
            })

    candidates.sort(key=lambda c: (c["category"], -c["stars"]))
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "queries": len(SEARCHES),
        "new_candidates": len(candidates),
        "known_excluded": len(exclude),
        "candidates": candidates,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scout GitHub for TinyWorlds companion projects.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--limit", type=int, default=12, help="results per query (default 12)")
    ap.add_argument("--min-stars", type=int, default=25, help="minimum stars (default 25)")
    ap.add_argument("--report", default="docs/research/companion-projects.md",
                    help="report file whose listed repos are excluded as already-known")
    args = ap.parse_args()

    result = collect(args.limit, args.min_stars, args.report)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"companion-scout: {result['new_candidates']} new candidate(s) "
          f"from {result['queries']} queries (excluded {result['known_excluded']} known)\n")
    last = None
    for c in result["candidates"]:
        if c["category"] != last:
            print(f"\n## {c['category']}")
            last = c["category"]
        desc = c["description"][:90] + ("…" if len(c["description"]) > 90 else "")
        print(f"  {c['stars']:>6}★  {c['fullName']}  [{c['language'] or '—'}]")
        if desc:
            print(f"          {desc}")
    # Exit 1 when there's something new (so a routine can branch on it).
    return 1 if result["new_candidates"] else 0


if __name__ == "__main__":
    sys.exit(main())
