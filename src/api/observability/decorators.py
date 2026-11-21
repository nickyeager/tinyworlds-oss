"""Timing decorators and context managers for observability.

This module provides utilities for automatic performance tracking:

- @timed_operation: Decorator to track function execution time
- OperationContext: Context manager for tracking operations with progress

Usage:
    from src.api.observability.decorators import timed_operation, OperationContext

    # Decorator usage
    @timed_operation("git_clone", "clone_repository")
    def clone_repository(self, request):
        ...

    # Context manager usage
    with OperationContext("git_clone", "Cloning repository") as ctx:
        ctx.progress(50, 100, "Downloaded 50/100 files")
        # ... do work
"""

import asyncio
import time
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from .logger import get_logger

F = TypeVar("F", bound=Callable[..., Any])


def timed_operation(service_name: str, operation_name: str) -> Callable[[F], F]:
    """Decorator to track operation timing.

    Automatically logs performance metrics for decorated functions.
    Works with both sync and async functions.

    Args:
        service_name: Name of the service (e.g., "git_clone")
        operation_name: Name of the operation (e.g., "clone_repository")

    Returns:
        Decorated function that logs timing

    Example:
        @timed_operation("git_clone", "clone_repository")
        def clone_repository(self, request):
            # ... implementation
            return result

        @timed_operation("asset_gen", "generate_sprite")
        async def generate_sprite(self, prompt):
            # ... implementation
            return sprite
    """
    def decorator(func: F) -> F:
        logger = get_logger(service_name)

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.performance(operation_name, duration_ms)
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.performance(f"{operation_name}_failed", duration_ms, error=str(e))
                raise

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.performance(operation_name, duration_ms)
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                logger.performance(f"{operation_name}_failed", duration_ms, error=str(e))
                raise

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        else:
            return sync_wrapper  # type: ignore

    return decorator


class OperationContext:
    """Context manager for tracking operations with progress.

    Provides a structured way to track operations that may have
    multiple stages or progress updates.

    Attributes:
        service_name: Name of the service
        operation: Description of the operation
        logger: StructuredLogger instance

    Example:
        with OperationContext("git_clone", "Cloning repository") as ctx:
            ctx.progress(0, 100, "Starting download...")
            # ... download ...
            ctx.progress(50, 100, "Downloaded 50%...")
            # ... more work ...
            ctx.progress(100, 100, "Download complete")

        # On success, logs completion message
        # On exception, logs error with stack trace
    """

    def __init__(self, service_name: str, operation: str) -> None:
        """Initialize the operation context.

        Args:
            service_name: Name of the service (e.g., "git_clone")
            operation: Description of the operation
        """
        self.service_name = service_name
        self.operation = operation
        self.logger = get_logger(service_name)
        self.start_time: Optional[float] = None
        self._progress_current = 0
        self._progress_total = 0

    def __enter__(self) -> "OperationContext":
        """Start the operation."""
        self.start_time = time.perf_counter()
        self.logger.info(f"Starting: {self.operation}", step=self.operation, status="started")
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Any
    ) -> bool:
        """End the operation, logging success or failure."""
        if self.start_time is None:
            return False

        duration_ms = (time.perf_counter() - self.start_time) * 1000
        duration_s = duration_ms / 1000

        if exc_type is not None:
            # Operation failed
            self.logger.error(
                f"Failed: {self.operation}",
                error=exc_val if isinstance(exc_val, Exception) else None,
                suggestion="Check logs for details"
            )
            self.logger.performance(f"{self.operation}_failed", duration_ms)
        else:
            # Operation succeeded
            self.logger.info(
                f"Completed: {self.operation}",
                step=self.operation,
                status="completed",
                duration_seconds=round(duration_s, 2)
            )
            self.logger.performance(self.operation, duration_ms)

        return False  # Don't suppress exceptions

    def progress(self, current: int, total: int, message: str) -> None:
        """Report progress within the operation.

        Args:
            current: Current progress (e.g., 50)
            total: Total expected (e.g., 100)
            message: Progress message
        """
        self._progress_current = current
        self._progress_total = total
        self.logger.progress(message, current, total, self.operation)

    def debug(self, message: str, **context: Any) -> None:
        """Log debug information within the operation.

        Args:
            message: Debug message
            **context: Additional context
        """
        self.logger.debug(message, operation=self.operation, **context)

    def status(self, message: str, **kwargs: Any) -> None:
        """Log a status update within the operation.

        Args:
            message: Status message
            **kwargs: Additional fields
        """
        self.logger.info(message, **kwargs)


class AsyncOperationContext:
    """Async version of OperationContext.

    Identical to OperationContext but for use in async contexts.
    Uses async enter/exit methods.

    Example:
        async with AsyncOperationContext("api", "Fetching data") as ctx:
            await ctx.progress(0, 100, "Starting...")
            result = await fetch_data()
            await ctx.progress(100, 100, "Done")
    """

    def __init__(self, service_name: str, operation: str) -> None:
        """Initialize the async operation context."""
        self.service_name = service_name
        self.operation = operation
        self.logger = get_logger(service_name)
        self.start_time: Optional[float] = None

    async def __aenter__(self) -> "AsyncOperationContext":
        """Start the operation."""
        self.start_time = time.perf_counter()
        self.logger.info(f"Starting: {self.operation}", step=self.operation, status="started")
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Any
    ) -> bool:
        """End the operation."""
        if self.start_time is None:
            return False

        duration_ms = (time.perf_counter() - self.start_time) * 1000
        duration_s = duration_ms / 1000

        if exc_type is not None:
            self.logger.error(
                f"Failed: {self.operation}",
                error=exc_val if isinstance(exc_val, Exception) else None,
                suggestion="Check logs for details"
            )
            self.logger.performance(f"{self.operation}_failed", duration_ms)
        else:
            self.logger.info(
                f"Completed: {self.operation}",
                step=self.operation,
                status="completed",
                duration_seconds=round(duration_s, 2)
            )
            self.logger.performance(self.operation, duration_ms)

        return False

    async def progress(self, current: int, total: int, message: str) -> None:
        """Report progress within the operation."""
        self.logger.progress(message, current, total, self.operation)

    async def debug(self, message: str, **context: Any) -> None:
        """Log debug information within the operation."""
        self.logger.debug(message, operation=self.operation, **context)
