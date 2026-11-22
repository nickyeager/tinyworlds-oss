#!/usr/bin/env python3
"""Refresh the public source manifest after staging intended source additions.

Reads tracked working files, not ignored runtime output. Run the snapshot checker
afterwards and stage RELEASE_MANIFEST.json alongside your source changes.
"""
import hashlib
import json
from pathlib import Path
import subprocess

from prepare_release_snapshot import include


def main():
    root = Path(__file__).resolve().parents[1]
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    files = []
    for name in sorted(set(filter(None, paths)) - {'RELEASE_MANIFEST.json'}):
        path = root / name
        if name != 'RELEASE_SCOPE.md' and not include(name):
            raise SystemExit(f'File outside the public distribution scope: {name}')
        if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root)) or not path.is_file():
            raise SystemExit(f'Missing or unsafe source file: {name}')
        data = path.read_bytes()
        files.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
    manifest = {'format': 1, 'source_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(), 'source': 'public working source; tracked files only', 'files': files}
    (root / 'RELEASE_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Refreshed manifest for {len(files)} source files. Run scripts/check_release_snapshot.py . next.')


if __name__ == '__main__':
    main()
