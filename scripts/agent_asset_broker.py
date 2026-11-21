#!/usr/bin/env python3
"""Worker-only asset CLI; paid credentials remain in the trusted broker."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    image = sub.add_parser("image")
    image.add_argument("--prompt", required=True)
    image.add_argument("-o", "--output", required=True)
    image.add_argument("--model", choices=("gemini", "grok"), default="gemini")
    image.add_argument("--size", choices=("512", "1K"), default="1K")
    image.add_argument("--aspect-ratio", default="1:1")
    image.add_argument("--image")
    glb = sub.add_parser("glb", help="Generate a 3D model remotely from a game image")
    glb.add_argument("--image", required=True)
    glb.add_argument("-o", "--output", required=True)
    sub.add_parser("video", help="unsupported by the trusted asset broker")
    args = parser.parse_args()
    if args.operation == "video":
        print(json.dumps({"ok": False, "error": "Video generation is unsupported"}))
        return 1
    url = os.environ.get("GAME_ASSET_BROKER_URL", "")
    token = os.environ.get("GAME_ASSET_JOB_TOKEN", "")
    if not url or not token:
        print(json.dumps({"ok": False, "error": "Asset broker is unavailable"}))
        return 1
    body = vars(args)
    if body.get("image") is None:
        body.pop("image", None)
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
    )
    try:
        with urllib.request.urlopen(request, timeout=600 if args.operation == "glb" else 180) as response:
            result = json.loads(response.read(65536))
        if not isinstance(result, dict):
            raise ValueError("invalid broker result")
        # Print only the bounded public response; never provider credentials.
        allowed = ("ok", "path", "cost_cents", "reserved_cents", "remaining_cents", "error")
        print(json.dumps({key: result[key] for key in allowed if key in result}))
        return 0 if result.get("ok") is True else 1
    except (urllib.error.URLError, ValueError, TimeoutError):
        print(json.dumps({"ok": False, "error": "Asset broker request failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
