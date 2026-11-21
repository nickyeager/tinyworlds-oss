#!/usr/bin/env python3
"""Build a credential-free plugin ZIP for local testing or a configured HTTPS host."""

import argparse
import json
import zipfile
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-url", default="http://127.0.0.1:8787/mcp")
    parser.add_argument(
        "--output", type=Path, default=Path("dist/tinyworlds-plugin.zip")
    )
    args = parser.parse_args()
    url = urlsplit(args.mcp_url)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path != "/mcp"
        or (
            url.scheme == "http"
            and url.hostname not in {"localhost", "127.0.0.1", "::1"}
        )
    ):
        parser.error(
            "Use an HTTPS /mcp endpoint or local loopback /mcp endpoint, without credentials"
        )
    root = Path(__file__).resolve().parents[1] / "plugins/tinyworlds"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        # Explicit package allowlist excludes runtime state, credentials and caches.
        paths = [root / "plugin.json", root / "mcp.json"]
        paths += sorted((root / "skills").rglob("SKILL.md"))
        paths += sorted((root / "skills").rglob("openai.yaml"))
        paths += sorted((root / "assets").glob("*.svg"))
        for path in paths:
            if path.is_symlink():
                parser.error("Plugin package cannot contain symlinks")
            data = path.read_bytes()
            if path.name == "mcp.json":
                config = json.loads(data)
                config["mcpServers"]["tinyworlds"]["url"] = args.mcp_url
                data = (json.dumps(config, indent=2) + "\n").encode()
            entry = zipfile.ZipInfo(
                str(path.relative_to(root)), date_time=(2026, 10, 1, 0, 0, 0)
            )
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, data)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
