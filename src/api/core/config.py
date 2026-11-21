"""Application configuration."""
from functools import lru_cache
from typing import Any, Literal, Optional
from pydantic import PrivateAttr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Configuration
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "TinyWorlds API"
    DEBUG: bool = False
    REQUIRE_PRODUCTION_SECRETS: bool = False
    GAME_PLAY_ORIGIN: str = ""

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_mode(cls, value: Any) -> Any:
        """Accept legacy deployment mode strings for DEBUG.

        Production has used values like ``DEBUG=release`` to mean "not debug".
        Pydantic's bool parser rejects that at import time, which prevents the
        backend container from starting. Keep true/false parsing strict for
        normal bool-ish values, but map common mode labels explicitly.
        """
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"debug", "dev", "development"}:
                return True
        return value

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days (long-lived tokens)

    # Password Reset
    PASSWORD_RESET_EXPIRE_MINUTES: int = 60  # 1 hour

    # Anonymous User Settings
    ANONYMOUS_USER_TTL_DAYS: int = 30  # Days before marking for deletion

    # Admin bootstrap — comma-separated list of emails granted is_admin on register/login.
    ADMIN_EMAILS: str = ""

    # Invitation TTL
    INVITATION_TTL_DAYS: int = 7

    @property
    def admin_emails_set(self) -> set[str]:
        """Lowercased, trimmed set of bootstrap admin emails."""
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/tinyworlds.db"

    # CORS — list both localhost AND 127.0.0.1 because browsers treat them as
    # different origins (CORS uses the literal string in the Origin header,
    # not DNS resolution). A page served at http://127.0.0.1:3333 fetching
    # http://localhost:8001 will fail preflight if only localhost is listed.
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000", "http://127.0.0.1:3000",
        "http://localhost:3333", "http://127.0.0.1:3333",
        "http://localhost:5173", "http://127.0.0.1:5173",
        "null",
    ]

    # Resend Email
    RESEND_API_KEY: Optional[str] = None
    # Until tinyworlds.us is verified in Resend, use the sandbox sender (delivers
    # only to the email tied to your Resend account). Once the domain is verified,
    # switch to "TinyWorlds <noreply@tinyworlds.us>".
    RESEND_FROM_EMAIL: str = "TinyWorlds <onboarding@resend.dev>"
    FRONTEND_URL: str = "http://localhost:3333"

    # Monitoring
    SENTRY_DSN: Optional[str] = None
    # Optional backend-owned OTLP dashboard; blank disables all agent exports.
    AGENT_TRACE_ENDPOINT: str = ""
    AGENT_TRACE_PROJECT: str = "tinyworlds"
    AGENT_TRACE_CONTENT: bool = False

    # Godot configuration
    GODOT_BINARY: str = "godot"
    GODOT_EXECUTOR: str = "cli"        # "cli" (Claude Code subprocess) or "sdk" (future)
    GODOT_GAMES_DIR: str = "generated_games"
    # Default engine for the umbrella /api/v1/games create endpoint. The
    # frontend never asks the user — operators flip this via env to roll
    # bevy generation in or out.
    DEFAULT_GAME_ENGINE: Literal["godot", "bevy"] = "godot"
    CLAUDE_CLI_BINARY: str = "claude"
    CLAUDE_CLI_MODEL: str = ""          # Optional model override for CLI mode
    GAME_AGENT_PROVIDER: Literal["claude", "codex"] = "claude"
    CODEX_CLI_BINARY: str = "codex"
    CODEX_CLI_MODEL: str = ""
    GAME_AGENT_TIMEOUT_SECONDS: float = 1800.0
    AGENT_EXECUTION_MODE: Literal["local", "worker"] = "local"
    # Explicit opt-in for a single operator on loopback. Never enable on a shared server.
    PERSONAL_MODE: bool = False
    PERSONAL_PROVIDER_DIR: str = ""
    _personal_provider_env: dict[str, str] | None = PrivateAttr(default=None)
    GAME_ASSET_BROKER_URL: str = ""
    GAME_ASSET_JOB_TOKEN: str = ""

    # Sidecar docker-launcher (security #1): the backend no longer mounts
    # /var/run/docker.sock. The Docker sidecar (bevy-builder) is
    # launched via this privileged broker over the internal network. The
    # shared secret is defense in depth on top of network isolation.
    SIDECAR_LAUNCHER_URL: str = "http://sidecar-launcher:8500"
    LAUNCHER_TOKEN: str = ""
    XAI_API_KEY: Optional[str] = None     # For xAI Grok image/video generation
    GOOGLE_API_KEY: Optional[str] = None  # For Gemini image generation
    TRIPO3D_API_KEY: Optional[str] = None  # For 3D model generation

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore extra environment variables (Azure keys, etc.)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
