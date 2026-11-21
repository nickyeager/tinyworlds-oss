"""Observability package for TinyWorlds.

This package provides structured logging, event streaming, and developer
observability features including:

- Type-safe event definitions (Pydantic models)
- Centralized event bus for routing events to multiple handlers
- Structured logger with automatic context injection
- Handlers for console, SSE streaming, and file logging
- Timing decorators and context managers

Usage:
    from src.api.observability import get_logger, get_event_bus

    # Get a logger for your service
    logger = get_logger("git_clone")

    # Log messages at different levels
    logger.info("Starting clone operation", repo_url=repo_url)
    logger.debug("Cache hit", cache_path=str(cache_path))
    logger.error("Clone failed", error=exception)

    # Log performance metrics
    logger.performance("clone_operation", duration_ms=1234.5)
"""

from .events import (
    BaseEvent,
    EventLevel,
    EventCategory,
    StatusEvent,
    ProgressEvent,
    CompletionEvent,
    ErrorEvent,
    DebugEvent,
    PerformanceEvent,
    GitCloneEvent,
    AssetGenerationEvent,
)
from .event_bus import EventBus, get_event_bus
from .logger import StructuredLogger, get_logger
from .handlers import ConsoleHandler, SSEHandler
from .decorators import timed_operation, OperationContext

__all__ = [
    # Events
    "BaseEvent",
    "EventLevel",
    "EventCategory",
    "StatusEvent",
    "ProgressEvent",
    "CompletionEvent",
    "ErrorEvent",
    "DebugEvent",
    "PerformanceEvent",
    "GitCloneEvent",
    "AssetGenerationEvent",
    # Event bus
    "EventBus",
    "get_event_bus",
    # Logger
    "StructuredLogger",
    "get_logger",
    # Handlers
    "ConsoleHandler",
    "SSEHandler",
    # Decorators
    "timed_operation",
    "OperationContext",
]
