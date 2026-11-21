"""Central event bus for observability.

The event bus is the core routing mechanism for all observability events.
Services emit events through loggers, and the event bus routes them to
registered handlers (console, SSE, file, etc.).

Usage:
    from src.api.observability import get_event_bus
    from src.api.observability.handlers import ConsoleHandler

    # Get the global event bus
    bus = get_event_bus()

    # Subscribe a handler
    console_handler = ConsoleHandler()
    bus.subscribe(console_handler.handle)

    # Or subscribe with filters
    bus.subscribe(
        handler=my_handler,
        category=EventCategory.USER,  # Only user events
        level=EventLevel.WARNING       # Warning and above
    )
"""

import asyncio
from typing import Callable, List, Optional

from .events import BaseEvent, EventCategory, EventLevel

# Type alias for event handlers
EventHandler = Callable[[BaseEvent], None]


class EventBus:
    """Central event bus for routing observability events.

    The event bus maintains a list of handlers and routes events to them
    based on optional filters. It's designed to be thread-safe and
    never let handler errors affect the emitting code.

    This class uses the singleton pattern - use get_event_bus() to access.
    """

    def __init__(self) -> None:
        """Initialize the event bus with empty handler lists."""
        self._handlers: dict[EventCategory, List[EventHandler]] = {
            category: [] for category in EventCategory
        }
        self._global_handlers: List[EventHandler] = []

    def subscribe(
        self,
        handler: EventHandler,
        category: Optional[EventCategory] = None,
        level: Optional[EventLevel] = None
    ) -> None:
        """Subscribe a handler to receive events.

        Args:
            handler: Function to call with each event
            category: Only receive events of this category (None = all)
            level: Only receive events at or above this level (None = all)
        """
        wrapped_handler = handler

        # Wrap with level filter if specified
        if level is not None:
            original_handler = handler

            def level_filter(event: BaseEvent) -> None:
                if self._should_emit(event.level, level):
                    original_handler(event)

            wrapped_handler = level_filter

        # Subscribe to category-specific or global handlers
        if category is not None:
            self._handlers[category].append(wrapped_handler)
        else:
            self._global_handlers.append(wrapped_handler)

    def unsubscribe(
        self,
        handler: EventHandler,
        category: Optional[EventCategory] = None
    ) -> None:
        """Unsubscribe a handler.

        Args:
            handler: The handler to remove
            category: Category to unsubscribe from (None = global)
        """
        if category is not None:
            try:
                self._handlers[category].remove(handler)
            except ValueError:
                pass  # Handler not found
        else:
            try:
                self._global_handlers.remove(handler)
            except ValueError:
                pass

    def emit(self, event: BaseEvent) -> None:
        """Emit an event to all subscribed handlers.

        This method never raises exceptions - handler errors are
        silently logged to prevent affecting the emitting code.

        Args:
            event: The event to emit
        """
        # Category-specific handlers
        for handler in self._handlers.get(event.category, []):
            try:
                handler(event)
            except Exception as e:
                # Never let handler errors break the emitter
                print(f"[EventBus] Handler error: {e}")

        # Global handlers
        for handler in self._global_handlers:
            try:
                handler(event)
            except Exception as e:
                print(f"[EventBus] Global handler error: {e}")

    async def emit_async(self, event: BaseEvent) -> None:
        """Emit event in async context.

        Runs handlers in the default executor to avoid blocking.

        Args:
            event: The event to emit
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.emit, event)

    def clear_handlers(self) -> None:
        """Remove all handlers. Useful for testing."""
        self._handlers = {category: [] for category in EventCategory}
        self._global_handlers = []

    @staticmethod
    def _should_emit(event_level: EventLevel, min_level: EventLevel) -> bool:
        """Check if event should be emitted based on level.

        Args:
            event_level: The event's level
            min_level: Minimum level to emit

        Returns:
            True if event level >= min_level
        """
        levels = [EventLevel.DEBUG, EventLevel.INFO, EventLevel.WARNING, EventLevel.ERROR]
        return levels.index(event_level) >= levels.index(min_level)


# Singleton instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance.

    Returns:
        The singleton EventBus instance
    """
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    """Reset the global event bus. Useful for testing."""
    global _event_bus
    if _event_bus is not None:
        _event_bus.clear_handlers()
    _event_bus = None
