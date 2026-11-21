#!/usr/bin/env python3
"""Copy an explicit source subset into a new, local release-review directory.

Uses current Git-visible files (including untracked source), never Git history,
ignored files, symlinks, private data, or deployment workflows. This prepares a
candidate; it does not certify licensing/security or publish anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT_FILES = {
    "README.md", "LICENSE", "LICENSE-DOCS", "LICENSING.md", "NOTICE",
    "ATTRIBUTION.md", "THIRD_PARTY_NOTICES.md", "SECURITY.md", "CONTRIBUTING.md",
    "requirements.txt", "requirements-observability.txt", "constraints-v0.1.txt", "alembic.ini", "pytest.ini", ".gitignore", ".dockerignore",
    ".env.example", ".env.production.example", "Dockerfile", "Dockerfile.agent",
    "Dockerfile.bevy-builder", "docker-compose.yml",
    "docker-compose.prod.yml", "docker-compose.plugin.yml", "docker-compose.observability.yml", "Caddyfile", "Caddyfile.plugin",
}
TREES = {"src", "web", "alembic", "vendor", "LICENSES", "services", "plugins", "templates", "tests", "scripts"}
DOCS = {
    "docs/ROADMAP.md", "docs/open-source-readiness.md",
    "docs/guides/setup.md", "docs/guides/setup-bevy.md", "docs/guides/generation.md",
    "docs/guides/testing-quickstart.md", "docs/guides/e2e-testing.md",
    "docs/guides/agent-play.md", "docs/guides/visual-references.md", "docs/guides/provider-connections.md",
    "docs/guides/agent-observability.md", "docs/guides/editor-ux-design.md",
}
EXCLUDED = (
    "tests/fixtures/audio/", "scripts/experiments/", "scripts/data/",
    "scripts/setup-vps.sh", "scripts/cloudflare_setup.sh", "scripts/record_voice_command.sh",
    "web/public/next.svg", "web/public/vercel.svg", "web/public/file.svg",
    "web/public/window.svg", "web/public/globe.svg", "docs/releases/2026-11-04-source-candidate.md",
)
LOCAL_RUNTIME = (
    ".claude/skills/local/godogen-lessons/", ".claude/skills/local/godot-modify/",
    ".claude/skills/local/bevy-modify/",
)


def include(relative: str) -> bool:
    parts = Path(relative).parts
    if any(part in {"node_modules", ".next", "__pycache__", ".pytest_cache", ".godot", "test-results", "playwright-report"} for part in parts):
        return False
    if relative.endswith((".pyc", ".tsbuildinfo", ".DS_Store")) or relative.startswith(EXCLUDED):
        return False
    if Path(relative).name.startswith(".env") and relative not in {".env.example", ".env.production.example"}:
        return False
    if relative in ROOT_FILES or relative in DOCS or relative in {".github/workflows/ci.yml", ".github/workflows/plugin.yml", ".github/PULL_REQUEST_TEMPLATE.md", ".agents/plugins/marketplace.json"} or relative.startswith((".github/ISSUE_TEMPLATE/", "docs/releases/")):
        return True
    if parts[0] in TREES:
        return True
    return relative.startswith((".claude/skills/godogen/", *LOCAL_RUNTIME))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--review-dir", required=True, type=Path, help="Private directory outside the candidate")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = args.destination.resolve()
    review = args.review_dir.resolve()
    if destination == root or destination.is_relative_to(root) or review == destination or review.is_relative_to(destination):
        parser.error("Candidate must be outside the checkout; private review must be outside the candidate")
    if destination.exists():
        parser.error("Destination already exists; choose a new path to preserve prior evidence")
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    ).decode().split("\0")
    destination.mkdir(parents=True)
    review.mkdir(parents=True, exist_ok=True)
    review.chmod(0o700)
    files, excluded = [], []
    for relative in sorted(set(filter(None, paths))):
        source = root / relative
        # Reject symlinked ancestors too, even if the final file is regular.
        safe_path = not any(p.is_symlink() for p in (source, *source.parents) if p != root.parent)
        if not include(relative) or not safe_path or not source.is_file():
            excluded.append(relative)
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
        files.append({"path": relative, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "bytes": target.stat().st_size})
    scope = destination / "RELEASE_SCOPE.md"
    scope.write_text(
        "# Source distribution scope\n\n"
        "This source snapshot has no inherited Git history. It includes current application code, "
        "tests and required runtime guidance. Private data, generated games, recordings, internal "
        "research, production runbooks and automatic deployment workflows are omitted.\n\n"
        "Optional development skills/templates with unresolved provenance are omitted from this "
        "distribution only; the development checkout and skill-audit records are preserved. "
        "Their omission is not an effectiveness verdict. Audio integration fixtures are also "
        "omitted pending asset review.\n\n"
        "The supported preview scope is local Codex + Godot. See docs/releases/v0.1-developer-preview.md "
        "for release status, verification evidence and limitations. Preparing this snapshot does not "
        "publish it or certify security or third-party rights.\n"
    )
    files.append({"path": scope.name, "sha256": hashlib.sha256(scope.read_bytes()).hexdigest(), "bytes": scope.stat().st_size})
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    manifest = {"format": 1, "source_head": head, "source": "current working files, including untracked source; not a clean commit", "files": files}
    (destination / "RELEASE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (review / "snapshot-review.json").write_text(json.dumps({"destination": str(destination), "source_head": head, "included": len(files), "excluded": excluded}, indent=2) + "\n")
    print(json.dumps({"destination": str(destination), "included": len(files), "excluded": len(excluded)}))


if __name__ == "__main__":
    main()
