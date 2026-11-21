"""Cache helpers for generated browser game exports."""
import json
from pathlib import Path

from fastapi import Request


PLAY_EDGE_CACHE_SECONDS = 7 * 24 * 60 * 60
PLAY_BROWSER_CACHE_SECONDS = 365 * 24 * 60 * 60


def asset_version(path: Path) -> str:
    """Return a stable version token for cache-busting generated dist files."""
    st = path.stat()
    return f"{st.st_size:x}-{st.st_mtime_ns:x}"


def versioned_play_asset_headers(path: Path, request: Request) -> dict[str, str]:
    version = asset_version(path)
    versioned = request.query_params.get("v") == version
    if versioned:
        browser_cache = f"public, max-age={PLAY_BROWSER_CACHE_SECONDS}, immutable"
        edge_cache = f"public, max-age={PLAY_EDGE_CACHE_SECONDS}"
    else:
        browser_cache = "public, max-age=0, must-revalidate"
        edge_cache = "public, max-age=0, must-revalidate"
    return {
        "Cache-Control": browser_cache,
        "CDN-Cache-Control": edge_cache,
        "Cloudflare-CDN-Cache-Control": edge_cache,
        "ETag": f'"{version}"',
    }


def dist_asset_versions(dist_dir: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    for path in dist_dir.iterdir():
        if path.is_file() and path.name != "index.html":
            versions[path.name] = asset_version(path)
    return versions


def inject_play_asset_cache_buster(html: str, versions: dict[str, str]) -> str:
    """Make generated play HTML request versioned assets for CDN caching."""
    for name, version in versions.items():
        html = html.replace(f'src="{name}"', f'src="{name}?v={version}"')
        html = html.replace(f"src='{name}'", f"src='{name}?v={version}'")
        html = html.replace(f'href="{name}"', f'href="{name}?v={version}"')
        html = html.replace(f"href='{name}'", f"href='{name}?v={version}'")
        html = html.replace(f'from "./{name}"', f'from "./{name}?v={version}"')
        html = html.replace(f"from './{name}'", f"from './{name}?v={version}'")
        html = html.replace(f'"./{name}"', f'"./{name}?v={version}"')
        html = html.replace(f"'./{name}'", f"'./{name}?v={version}'")

    version_json = json.dumps(versions, separators=(",", ":"))
    shim = f"""
<script>
(function() {{
  var versions = {version_json};
  function versioned(input) {{
    try {{
      var raw = typeof input === "string" ? input : input && input.url;
      if (!raw) return input;
      var url = new URL(raw, window.location.href);
      if (url.origin !== window.location.origin || url.searchParams.has("v")) return input;
      var name = url.pathname.split("/").pop();
      if (!versions[name]) return input;
      url.searchParams.set("v", versions[name]);
      var out = url.pathname + url.search + url.hash;
      return typeof input === "string" ? out : new Request(out, input);
    }} catch (e) {{
      return input;
    }}
  }}
  var originalFetch = window.fetch;
  if (originalFetch) {{
    window.fetch = function(input, init) {{
      return originalFetch.call(this, versioned(input), init);
    }};
  }}
  if (window.XMLHttpRequest) {{
    var originalOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url) {{
      arguments[1] = versioned(url);
      return originalOpen.apply(this, arguments);
    }};
  }}
}}());
</script>
"""
    if "</head>" in html:
        return html.replace("</head>", shim + "</head>", 1)
    return shim + html
