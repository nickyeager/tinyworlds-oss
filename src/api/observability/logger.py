"""Structured logging interface for services.

This module provides a high-level logging interface that emits structured
events through the event bus. It automatically captures caller context
(file, line, function) for debug events.

Usage:
    from src.api.observability import get_logger

    class MyService:
        def __init__(self):
            self.logger = get_logger("my_service")

        def do_something(self):
            self.logger.info("Starting operation", step="clone")
            self.logger.debug("Details", path="/some/path", size_mb=2.5)
            self.logger.performance("operation", duration_ms=1234.5)
"""

import inspect
import logging
import traceback
from typing import Any, Dict, Optional

from .event_bus import get_event_bus
from .events import (
    DebugEvent,
    ErrorEvent,
    EventLevel,
    PerformanceEvent,
    StatusEvent,
    ProgressEvent,
    CompletionEvent,
    GitCloneEvent,
)


class StructuredLogger:
    """Structured logger that emits events through the event bus.

    This logger provides methods for different log levels and automatically
    captures caller context for debug events. It can optionally forward
    to Python's standard logging module.

    Attributes:
        service_name: Name of the service using this logger
        enable_python_logging: Whether to also log to Python's logging module
    """

    def __init__(self, service_name: str, enable_python_logging: bool = True) -> None:
        """Initialize the structured logger.

        Args:
            service_name: Name of the service (e.g., "git_clone")
            enable_python_logging: Also log to Python's logging module
        """
        self.service_name = service_name
        self.event_bus = get_event_bus()
        self.python_logger = logging.getLogger(f"tinyworlds.{service_name}")
        self.enable_python_logging = enable_python_logging

    def _get_caller_info(self, depth: int = 2) -> Dict[str, Any]:
        """Get information about the caller for debug context.

        Args:
            depth: How many frames to go back (default 2 = caller of log method)

        Returns:
            Dict with file_path, line_number, function_name
        """
        frame = inspect.currentframe()
        try:
            # Walk up the stack
            for _ in range(depth + 1):
                if frame is None:
                    break
                frame = frame.f_back

            if frame is not None:
                return {
                    "file_path": frame.f_code.co_filename,
                    "line_number": frame.f_lineno,
                    "function_name": frame.f_code.co_name,
                }
        finally:
            del frame  # Avoid reference cycles
        return {}

    def debug(self, message: str, **context: Any) -> None:
        """Log debug information.

        Debug messages include full caller context for tracing.

        Args:
            message: Debug message
            **context: Arbitrary key-value context data
        """
        caller_info = self._get_caller_info()
        event = DebugEvent(
            service=self.service_name,
            message=message,
            context=context,
            **caller_info
        )
        self.event_bus.emit(event)

        if self.enable_python_logging:
            self.python_logger.debug(f"{message} | {context}")

    def info(self, message: str, **kwargs: Any) -> None:
        """Log informational message.

        Info messages are user-facing status updates.

        Args:
            message: Status message
            **kwargs: Optional fields (step, status, size_mb, duration_seconds, etc.)
        """
        # Separate known fields from context
        known_fields = {"step", "status", "size_mb", "duration_seconds", "item_count"}
        event_kwargs = {k: v for k, v in kwargs.items() if k in known_fields}

        event = StatusEvent(
            service=self.service_name,
            message=message,
            level=EventLevel.INFO,
            **event_kwargs
        )
        self.event_bus.emit(event)

        if self.enable_python_logging:
            self.python_logger.info(message)

    def warning(self, message: str, **context: Any) -> None:
        """Log warning message.

        Args:
            message: Warning message
            **context: Arbitrary key-value context data
        """
        event = StatusEvent(
            service=self.service_name,
            message=message,
            level=EventLevel.WARNING
        )
        self.event_bus.emit(event)

        if self.enable_python_logging:
            self.python_logger.warning(f"{message} | {context}")

    def error(
        self,
        message: str,
        error: Optional[Exception] = None,
        suggestion: Optional[str] = None
    ) -> None:
        """Log error with optional exception and suggestion.

        Errors are both user-facing (ErrorEvent) and debug (DebugEvent with stack trace).

        Args:
            message: Error message
            error: Optional exception that caused the error
            suggestion: Optional hint for how to fix
        """
        caller_info = self._get_caller_info()
        stack_trace = None

        if error is not None:
            stack_trace = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )

        # User-facing error event
        user_event = ErrorEvent(
            service=self.service_name,
            error_message=message,
            suggestion=suggestion
        )
        self.event_bus.emit(user_event)

        # Debug error event with stack trace
        debug_event = DebugEvent(
            service=self.service_name,
            level=EventLevel.ERROR,
            message=f"ERROR: {message}",
            context={"exception": str(error) if error else None},
            stack_trace=stack_trace,
            **caller_info
        )
        self.event_bus.emit(debug_event)

        if self.enable_python_logging:
            self.python_logger.error(message, exc_info=error)

    def progress(
        self,
        message: str,
        current: int,
        total: int,
        operation: str,
        **context: Any
    ) -> None:
        """Log progress update.

        Args:
            message: Progress message
            current: Current item number
            total: Total items
            operation: What operation is in progress
            **context: Additional context
        """
        event = ProgressEvent(
            service=self.service_name,
            message=message,
            current=current,
            total=total,
            operation=operation
        )
        self.event_bus.emit(event)

        if self.enable_python_logging:
            self.python_logger.info(f"{message} ({current}/{total})")

    def complete(
        self,
        message: str,
        summary: Optional[str] = None,
        result_path: Optional[str] = None
    ) -> None:
        """Log completion of an operation.

        Args:
            message: Completion message
            summary: Optional detailed summary
            result_path: Optional path to result
        """
        event = CompletionEvent(
            service=self.service_name,
            message=message,
            summary=summary,
            result_path=result_path
        )
        self.event_bus.emit(event)

        if self.enable_python_logging:
            self.python_logger.info(message)

    def performance(self, operation: str, duration_ms: float, **metrics: Any) -> None:
        """Log performance metric.

        Args:
            operation: Name of the operation measured
            duration_ms: Duration in milliseconds
            **metrics: Additional metrics (memory_mb, cpu_percent, etc.)
        """
        event = PerformanceEvent(
            service=self.service_name,
            operation=operation,
            duration_ms=duration_ms,
            context=metrics
        )
        self.event_bus.emit(event)

        if self.enable_python_logging:
            self.python_logger.info(f"PERF: {operation} took {duration_ms:.2f}ms")

    def clone_status(
        self,
        message: str,
        step: Optional[str] = None,
        status: Optional[str] = None,
        repo_url: Optional[str] = None,
        commit_hash: Optional[str] = None,
        is_cached: Optional[bool] = None,
        size_mb: Optional[float] = None,
        duration_seconds: Optional[float] = None,
        cache_key: Optional[str] = None
    ) -> None:
        """Log git clone specific status.

        Specialized method for clone operations with all relevant fields.

        Args:
            message: Status message
            step: Current step (checking_cache, cloning, copying, validating)
            status: Step status (started, completed)
            repo_url: Repository URL
            commit_hash: Git commit hash
            is_cached: Whether cache was used
            size_mb: Size in megabytes
            duration_seconds: Duration in seconds
            cache_key: Cache key for debugging
        """
        event = GitCloneEvent(
            service=self.service_name,
            message=message,
            step=step,
            status=status,
            repo_url=repo_url,
            commit_hash=commit_hash,
            is_cached=is_cached,
            size_mb=size_mb,
            duration_seconds=duration_seconds,
            cache_key=cache_key
        )
        self.event_bus.emit(event)

        if self.enable_python_logging:
            self.python_logger.info(message)


# Logger cache to avoid creating multiple loggers for the same service
_loggers: Dict[str, StructuredLogger] = {}


def get_logger(service_name: str) -> StructuredLogger:
    """Get a structured logger for a service.

    Loggers are cached, so calling this multiple times with the same
    service name returns the same logger instance.

    Args:
        service_name: Name of the service (e.g., "git_clone")

    Returns:
        StructuredLogger instance for the service
    """
    if service_name not in _loggers:
        _loggers[service_name] = StructuredLogger(service_name)
    return _loggers[service_name]


def reset_loggers() -> None:
    """Clear the logger cache. Useful for testing."""
    _loggers.clear()
