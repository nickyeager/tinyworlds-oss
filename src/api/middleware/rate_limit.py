"""Rate limiting middleware for authentication endpoints."""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from fastapi import HTTPException, Request, status


@dataclass
class RateLimitBucket:
    """Token bucket for rate limiting."""
    tokens: float
    last_update: float


class RateLimiter:
    """
    In-memory rate limiter using token bucket algorithm.

    For production, consider using Redis for distributed rate limiting.
    """

    def __init__(
        self,
        requests_per_minute: int = 10,
        burst_size: int = 5,
    ):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Sustained rate limit
            burst_size: Maximum burst of requests allowed
        """
        self.rate = requests_per_minute / 60.0  # tokens per second
        self.burst_size = burst_size
        self._buckets: dict[str, RateLimitBucket] = defaultdict(
            lambda: RateLimitBucket(tokens=self.burst_size, last_update=time.time())
        )

    def _get_client_key(self, request: Request) -> str:
        """Get unique key for the client."""
        # Use X-Forwarded-For if behind proxy, otherwise use client IP
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"

        # Include endpoint path for per-endpoint limiting
        return f"{ip}:{request.url.path}"

    def _refill_bucket(self, bucket: RateLimitBucket) -> None:
        """Refill tokens based on time elapsed."""
        now = time.time()
        elapsed = now - bucket.last_update
        bucket.tokens = min(self.burst_size, bucket.tokens + elapsed * self.rate)
        bucket.last_update = now

    def check_rate_limit(self, request: Request) -> tuple[bool, Optional[float]]:
        """
        Check if request is within rate limit.

        Returns:
            Tuple of (allowed, retry_after_seconds)
        """
        key = self._get_client_key(request)
        bucket = self._buckets[key]

        self._refill_bucket(bucket)

        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return True, None
        else:
            # Calculate retry-after
            retry_after = (1 - bucket.tokens) / self.rate
            return False, retry_after

    def reset(self, request: Request) -> None:
        """Reset rate limit for a client (e.g., after successful login)."""
        key = self._get_client_key(request)
        if key in self._buckets:
            self._buckets[key] = RateLimitBucket(
                tokens=self.burst_size,
                last_update=time.time()
            )


# Global rate limiters for different endpoints
login_limiter = RateLimiter(requests_per_minute=10, burst_size=5)
register_limiter = RateLimiter(requests_per_minute=5, burst_size=3)
password_reset_limiter = RateLimiter(requests_per_minute=3, burst_size=2)
game_creation_limiter = RateLimiter(requests_per_minute=2, burst_size=2)


async def check_login_rate_limit(request: Request) -> None:
    """Dependency to check login rate limit."""
    allowed, retry_after = login_limiter.check_rate_limit(request)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(int(retry_after or 60))},
        )


async def check_register_rate_limit(request: Request) -> None:
    """Dependency to check registration rate limit."""
    allowed, retry_after = register_limiter.check_rate_limit(request)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again later.",
            headers={"Retry-After": str(int(retry_after or 60))},
        )


async def check_password_reset_rate_limit(request: Request) -> None:
    """Dependency to check password reset rate limit."""
    allowed, retry_after = password_reset_limiter.check_rate_limit(request)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password reset requests. Please try again later.",
            headers={"Retry-After": str(int(retry_after or 60))},
        )


async def check_game_creation_rate_limit(request: Request) -> None:
    """Dependency to check game creation rate limit."""
    allowed, retry_after = game_creation_limiter.check_rate_limit(request)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many game creation requests. Please try again later.",
            headers={"Retry-After": str(int(retry_after or 60))},
        )
