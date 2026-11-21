from pathlib import Path
from types import SimpleNamespace

from src.api.services.play_cache import (
    PLAY_BROWSER_CACHE_SECONDS,
    asset_version,
    dist_asset_versions,
    inject_play_asset_cache_buster,
    versioned_play_asset_headers,
)


def test_versioned_play_asset_headers_make_matching_urls_immutable(tmp_path: Path):
    asset = tmp_path / "index.wasm"
    asset.write_bytes(b"wasm bytes")
    version = asset_version(asset)

    request = SimpleNamespace(query_params={"v": version})

    headers = versioned_play_asset_headers(asset, request)

    assert headers["ETag"] == f'"{version}"'
    assert headers["Cache-Control"] == (
        f"public, max-age={PLAY_BROWSER_CACHE_SECONDS}, immutable"
    )
    assert headers["CDN-Cache-Control"].startswith("public, max-age=")
    assert headers["Cloudflare-CDN-Cache-Control"] == headers["CDN-Cache-Control"]


def test_versioned_play_asset_headers_keep_unversioned_urls_revalidating(
    tmp_path: Path,
):
    asset = tmp_path / "index.wasm"
    asset.write_bytes(b"wasm bytes")
    request = SimpleNamespace(query_params={})

    headers = versioned_play_asset_headers(asset, request)

    assert headers["Cache-Control"] == "public, max-age=0, must-revalidate"
    assert headers["CDN-Cache-Control"] == "public, max-age=0, must-revalidate"
    assert headers["Cloudflare-CDN-Cache-Control"] == (
        "public, max-age=0, must-revalidate"
    )


def test_inject_play_asset_cache_buster_versions_static_and_fetch_urls(
    tmp_path: Path,
):
    (tmp_path / "index.js").write_text("console.log('engine')", encoding="utf-8")
    (tmp_path / "index.wasm").write_bytes(b"wasm bytes")
    versions = dist_asset_versions(tmp_path)

    html = """
<html>
<head><script src="index.js"></script></head>
<body><script>fetch("index.wasm")</script></body>
</html>
"""

    injected = inject_play_asset_cache_buster(html, versions)

    assert f'src="index.js?v={versions["index.js"]}"' in injected
    assert "var originalFetch = window.fetch" in injected
    assert '"index.wasm":' in injected
    assert "index.html" not in versions
