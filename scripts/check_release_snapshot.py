#!/usr/bin/env python3
"""Check a prepared source manifest, distribution boundaries and public doc links."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote


def check(root: Path, tracked: bool = False) -> dict:
    manifest = json.loads((root / "RELEASE_MANIFEST.json").read_text())
    failures = []
    paths = {row["path"] for row in manifest["files"]}
    if tracked:
        tracked_paths = set(filter(None, subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')))
        for extra in sorted(tracked_paths - paths - {'RELEASE_MANIFEST.json'}):
            failures.append(f'Tracked file missing from manifest: {extra}')
        for missing in sorted(paths - tracked_paths):
            failures.append(f'Manifest file is not tracked: {missing}')
    for row in manifest["files"]:
        if Path(row['path']).is_absolute() or '..' in Path(row['path']).parts:
            failures.append(f'Unsafe manifest path: {row["path"]}')
            continue
        file = root / row["path"]
        if not file.is_file() or file.is_symlink():
            failures.append(f"Missing/unsafe file: {row['path']}")
        elif hashlib.sha256(file.read_bytes()).hexdigest() != row["sha256"]:
            failures.append(f"Hash mismatch: {row['path']}")
        if row["path"].startswith(("data/", "generated_games/", ".git/", ".claude/skills/local/csharp-patterns/")):
            failures.append(f"Excluded content: {row['path']}")
        if file.name.startswith('.env') and file.name not in {'.env.example', '.env.production.example'}:
            failures.append(f"Environment file: {row['path']}")
    for required in ("LICENSE", "LICENSE-DOCS", "ATTRIBUTION.md", "NOTICE", "SECURITY.md", "requirements-observability.txt", "docker-compose.observability.yml", "docs/guides/agent-observability.md", "docs/releases/v0.1-developer-preview.md"):
        if required not in paths:
            failures.append(f"Required release file absent: {required}")
    docs = sorted(path for path in paths if path.endswith('.md') and ('/' not in path or path.startswith('docs/')))
    for relative in docs:
        file = root / relative
        for raw in re.findall(r'\]\(([^)]+)\)', file.read_text()):
            link = unquote(raw.split('#')[0].split(' "')[0]).strip('<>')
            if not link or ':' in link or link.startswith('//'):
                continue
            target = (file.parent / link).resolve()
            if not target.is_relative_to(root.resolve()) or not target.exists():
                failures.append(f"Broken local link: {relative} -> {link}")
    return {"passed": not failures, "manifest_files": len(paths), "public_documents_checked": len(docs), "failures": failures}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--tracked', action='store_true', help='Also require exact Git-tracked file coverage')
    args = parser.parse_args()
    result = check(args.candidate, tracked=args.tracked)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
