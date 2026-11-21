"""Business logic services, imported independently by trusted worker processes."""

__all__ = ["AuthService"]


def __getattr__(name: str):
    # The launcher imports the asset ledger without API signing/database secrets.
    # Preserve the public package export without initializing auth on every import.
    if name == "AuthService":
        from src.api.services.auth_service import AuthService
        return AuthService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
