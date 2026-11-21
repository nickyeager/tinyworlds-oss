"""Explicit gateway configuration; never load the application's .env."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Config:
    public_url: str = "http://127.0.0.1:8787"
    backend_url: str = "http://127.0.0.1:8001"
    web_url: str = "http://localhost:3333"
    data_dir: Path = Path("data/plugin")
    encryption_key: str | None = None
    extra_redirect_uris: tuple[str, ...] = ()

    def __post_init__(self):
        for value in (self.public_url, self.backend_url, self.web_url):
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
                or url.path
            ):
                raise ValueError(
                    "Gateway URLs must be HTTP origins without paths or credentials"
                )
        if not self.local and urlsplit(self.public_url).scheme != "https":
            raise ValueError("Public plugin access requires HTTPS")
        if not self.local and not self.encryption_key:
            raise ValueError("Set PLUGIN_ENCRYPTION_KEY for a public gateway")

    @property
    def local(self) -> bool:
        return urlsplit(self.public_url).hostname in {"localhost", "127.0.0.1", "::1"}

    @property
    def resource(self) -> str:
        return self.public_url + "/mcp"

    @property
    def issuer(self) -> str:
        # The SDK serializes an origin-only AnyHttpUrl with a trailing slash.
        return self.public_url + "/"

    @classmethod
    def from_env(cls):
        return cls(
            public_url=os.getenv("PLUGIN_PUBLIC_URL", "http://127.0.0.1:8787").rstrip(
                "/"
            ),
            backend_url=os.getenv("PLUGIN_BACKEND_URL", "http://127.0.0.1:8001").rstrip(
                "/"
            ),
            web_url=os.getenv("PLUGIN_WEB_URL", "http://localhost:3333").rstrip("/"),
            data_dir=Path(os.getenv("PLUGIN_DATA_DIR", "data/plugin")),
            encryption_key=os.getenv("PLUGIN_ENCRYPTION_KEY"),
            extra_redirect_uris=tuple(
                filter(None, os.getenv("PLUGIN_REDIRECT_URIS", "").split(","))
            ),
        )
