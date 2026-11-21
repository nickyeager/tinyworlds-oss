"""Event handlers for different output destinations.

This module provides handlers that consume events from the event bus and
route them to different destinations:

- ConsoleHandler: Logs events to the console with formatting
- SSEHandler: Queues events for Server-Sent Events streaming
- FileHandler: Writes events to log files with rotation

Usage:
    from src.api.observability import get_event_bus
    from src.api.observability.handlers import ConsoleHandler, SSEHandler

    # Console logging
    console = ConsoleHandler(min_level=EventLevel.INFO)
    get_event_bus().subscribe(console.handle)

    # SSE streaming
    queue = asyncio.Queue()
    sse = SSEHandler(queue, include_debug=False)
    get_event_bus().subscribe(sse.handle, category=EventCategory.USER)
"""

import asyncio
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Set

from .events import BaseEvent, EventCategory, EventLevel


class ConsoleHandler:
    """Console logging handler for developer observability.

    Formats events as structured log lines with timestamps, levels,
    and service names. Supports filtering by minimum level.

    Attributes:
        min_level: Minimum event level to log (default: DEBUG)
        use_colors: Whether to use ANSI colors (default: True if TTY)
    """

    # ANSI color codes
    COLORS = {
        EventLevel.DEBUG: "\033[90m",    # Gray
        EventLevel.INFO: "\033[0m",      # Default
        EventLevel.WARNING: "\033[33m",  # Yellow
        EventLevel.ERROR: "\033[31m",    # Red
    }
    RESET = "\033[0m"

    def __init__(
        self,
        min_level: EventLevel = EventLevel.DEBUG,
        use_colors: Optional[bool] = None
    ) -> None:
        """Initialize the console handler.

        Args:
            min_level: Minimum level to log
            use_colors: Use ANSI colors (None = auto-detect TTY)
        """
        self.min_level = min_level
        self.use_colors = use_colors if use_colors is not None else os.isatty(1)

        # Configure Python logging for consistency
        self.logger = logging.getLogger("tinyworlds.console")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s",
                datefmt="%H:%M:%S"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(self._get_logging_level(min_level))

    def _get_logging_level(self, level: EventLevel) -> int:
        """Convert EventLevel to Python logging level."""
        return {
            EventLevel.DEBUG: logging.DEBUG,
            EventLevel.INFO: logging.INFO,
            EventLevel.WARNING: logging.WARNING,
            EventLevel.ERROR: logging.ERROR,
        }[level]

    def _should_log(self, event_level: EventLevel) -> bool:
        """Check if event should be logged based on level."""
        levels = [EventLevel.DEBUG, EventLevel.INFO, EventLevel.WARNING, EventLevel.ERROR]
        return levels.index(event_level) >= levels.index(self.min_level)

    def _format_message(self, event: BaseEvent) -> str:
        """Format event as a log message."""
        event_dict = event.to_dict()

        # Extract key fields
        service = event_dict.get("service", "unknown")
        message = event_dict.get("message", event_dict.get("error_message", ""))

        # Build context string from remaining fields
        skip_keys = {"timestamp", "level", "category", "service", "message", "error_message"}
        context = {k: v for k, v in event_dict.items() if k not in skip_keys and v is not None}

        # Format: [service] message | context
        if context:
            context_str = " | ".join(f"{k}={v}" for k, v in context.items())
            return f"[{service}] {message} | {context_str}"
        else:
            return f"[{service}] {message}"

    def handle(self, event: BaseEvent) -> None:
        """Handle event by logging to console.

        Args:
            event: The event to log
        """
        if not self._should_log(event.level):
            return

        message = self._format_message(event)
        log_level = self._get_logging_level(event.level)

        # Add colors if enabled
        if self.use_colors:
            color = self.COLORS.get(event.level, "")
            message = f"{color}{message}{self.RESET}"

        self.logger.log(log_level, message)


class SSEHandler:
    """Server-Sent Events handler for streaming to frontend.

    Queues events for SSE streaming, with filtering by category
    and an option to include/exclude debug events.

    Attributes:
        queue: Async queue to push events to
        categories: Set of categories to include (None = all)
        include_debug: Whether to include DEBUG category events
    """

    def __init__(
        self,
        queue: asyncio.Queue,
        categories: Optional[Set[EventCategory]] = None,
        include_debug: bool = False,
        max_queue_size: int = 1000
    ) -> None:
        """Initialize the SSE handler.

        Args:
            queue: Async queue for SSE events
            categories: Categories to include (None = all except debug)
            include_debug: Include debug events (default: False)
            max_queue_size: Max queue size before dropping (default: 1000)
        """
        self.queue = queue
        self.categories = set(categories) if categories else None
        self.include_debug = include_debug
        self.max_queue_size = max_queue_size

    def _should_emit(self, event: BaseEvent) -> bool:
        """Check if event should be emitted."""
        # Filter debug events unless explicitly included
        if event.category == EventCategory.DEBUG and not self.include_debug:
            return False

        # Filter by category if specified
        if self.categories and event.category not in self.categories:
            return False

        return True

    def handle(self, event: BaseEvent) -> None:
        """Handle event by pushing to SSE queue.

        Args:
            event: The event to queue
        """
        if not self._should_emit(event):
            return

        # Convert to SSE-friendly format
        event_dict = event.to_sse_dict()

        # Put in queue (non-blocking, drop if full)
        try:
            if self.queue.qsize() < self.max_queue_size:
                self.queue.put_nowait(event_dict)
            else:
                # Queue is full, drop oldest event
                try:
                    self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self.queue.put_nowait(event_dict)
        except Exception as e:
            # Never let queue errors break the handler
            print(f"[SSEHandler] Queue error: {e}")


class FileHandler:
    """File handler for persistent logging.

    Writes events as JSON lines to log files with automatic rotation.

    Attributes:
        log_dir: Directory for log files
        min_level: Minimum level to log
        rotation_mb: Max file size before rotation
    """

    def __init__(
        self,
        log_dir: Path,
        min_level: EventLevel = EventLevel.INFO,
        rotation_mb: int = 10,
        backup_count: int = 5
    ) -> None:
        """Initialize the file handler.

        Args:
            log_dir: Directory to write log files
            min_level: Minimum level to log
            rotation_mb: Max file size in MB before rotation
            backup_count: Number of backup files to keep
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.min_level = min_level

        # Create rotating file handler
        self.logger = logging.getLogger("tinyworlds.file")
        if not self.logger.handlers:
            log_file = self.log_dir / "tinyworlds.log"
            handler = RotatingFileHandler(
                log_file,
                maxBytes=rotation_mb * 1024 * 1024,
                backupCount=backup_count
            )
            # Use JSON format for structured logging
            formatter = logging.Formatter("%(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.DEBUG)

    def _should_log(self, event_level: EventLevel) -> bool:
        """Check if event should be logged based on level."""
        levels = [EventLevel.DEBUG, EventLevel.INFO, EventLevel.WARNING, EventLevel.ERROR]
        return levels.index(event_level) >= levels.index(self.min_level)

    def handle(self, event: BaseEvent) -> None:
        """Handle event by writing to file.

        Args:
            event: The event to log
        """
        if not self._should_log(event.level):
            return

        # Write as JSON line
        try:
            log_entry = json.dumps(event.to_dict())
            self.logger.info(log_entry)
        except Exception as e:
            # Never let file errors break the handler
            print(f"[FileHandler] Write error: {e}")
