"""Event type definitions for observability.

This module defines all event types using Pydantic models, providing:
- Type safety and validation
- Clear separation between user-facing and debug events
- Serialization utilities for SSE streaming

Event Categories:
- USER: User-facing progress and status messages
- DEBUG: Developer observability (paths, sizes, hashes, stack traces)
- PERF: Performance metrics (timing, memory, CPU)
- ERROR: Error tracking with suggestions and stack traces
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class EventLevel(str, Enum):
    """Event severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EventCategory(str, Enum):
    """Event categories for filtering and routing."""
    USER = "user"          # User-facing progress
    DEBUG = "debug"        # Developer observability
    PERF = "perf"          # Performance metrics
    ERROR = "error"        # Error tracking


# ==================== BASE EVENT ====================

class BaseEvent(BaseModel):
    """Base event with common fields.

    All events inherit from this base class, ensuring consistent
    structure across the observability system.

    Attributes:
        timestamp: When the event occurred (UTC)
        level: Severity level (debug, info, warning, error)
        category: Event category for filtering (user, debug, perf, error)
        service: Name of the service that emitted the event
    """
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    level: EventLevel = EventLevel.INFO
    category: EventCategory = EventCategory.USER
    service: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = self.model_dump()
        data["timestamp"] = self.timestamp.isoformat()
        return data

    def to_sse_dict(self) -> Dict[str, Any]:
        """Convert to SSE-friendly dictionary with 'type' field."""
        data = self.to_dict()
        # Add event type for SSE streaming
        data["event_type"] = self.__class__.__name__
        return data


# ==================== USER-FACING EVENTS ====================

class StatusEvent(BaseEvent):
    """High-level status update for users.

    Used for major milestones like "Cloning repository...",
    "Generating assets...", etc.

    Attributes:
        message: User-facing status message
        step: Current pipeline step (clone, generate_assets, modify_code)
        status: Step status (started, completed)
        size_mb: Optional size information for verbose feedback
        duration_seconds: Optional timing for verbose feedback
        item_count: Optional count (e.g., "3 frames generated")
    """
    category: EventCategory = EventCategory.USER
    message: str
    step: Optional[str] = None
    status: Optional[str] = None  # "started", "completed"

    # Verbose context for users
    size_mb: Optional[float] = None
    duration_seconds: Optional[float] = None
    item_count: Optional[int] = None


class ProgressEvent(BaseEvent):
    """Granular progress for long operations.

    Used for operations like frame generation where progress
    can be tracked numerically.

    Attributes:
        message: User-facing progress message
        current: Current item number
        total: Total items expected
        percentage: Calculated percentage (0-100)
        operation: What operation is being performed
        eta_seconds: Optional estimated time remaining
    """
    category: EventCategory = EventCategory.USER
    message: str
    current: int
    total: int
    percentage: Optional[float] = None
    operation: str
    eta_seconds: Optional[float] = None

    def model_post_init(self, __context: Any) -> None:
        """Calculate percentage if not provided."""
        if self.percentage is None and self.total > 0:
            self.percentage = round((self.current / self.total) * 100, 1)


class CompletionEvent(BaseEvent):
    """Operation completed successfully.

    Marks the successful end of an operation with summary info.

    Attributes:
        message: Completion message
        summary: Optional detailed summary
        result_path: Path to result (e.g., project directory)
    """
    category: EventCategory = EventCategory.USER
    message: str
    summary: Optional[str] = None
    result_path: Optional[str] = None


class ErrorEvent(BaseEvent):
    """User-facing error event.

    Provides error information with optional suggestions for fixing.

    Attributes:
        error_message: What went wrong
        suggestion: Optional hint for how to fix
    """
    category: EventCategory = EventCategory.ERROR
    level: EventLevel = EventLevel.ERROR
    error_message: str
    suggestion: Optional[str] = None


# ==================== DEBUG EVENTS ====================

class DebugEvent(BaseEvent):
    """Developer observability event.

    Contains rich context for debugging including source location,
    arbitrary context data, and optional stack traces.

    Attributes:
        message: Debug message
        context: Arbitrary key-value context data
        file_path: Source file where event was emitted
        line_number: Line number in source file
        function_name: Function that emitted the event
        stack_trace: Optional stack trace for errors
    """
    category: EventCategory = EventCategory.DEBUG
    level: EventLevel = EventLevel.DEBUG
    message: str
    context: Dict[str, Any] = Field(default_factory=dict)

    # Source location (auto-populated by logger)
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    function_name: Optional[str] = None
    stack_trace: Optional[str] = None


class PerformanceEvent(BaseEvent):
    """Performance metric tracking.

    Used for tracking operation timing and resource usage.

    Attributes:
        operation: Name of the operation being measured
        duration_ms: How long the operation took in milliseconds
        memory_mb: Optional memory usage in megabytes
        cpu_percent: Optional CPU usage percentage
        context: Additional metrics or context
    """
    category: EventCategory = EventCategory.PERF
    level: EventLevel = EventLevel.DEBUG
    operation: str
    duration_ms: float
    memory_mb: Optional[float] = None
    cpu_percent: Optional[float] = None
    context: Dict[str, Any] = Field(default_factory=dict)


# ==================== SPECIALIZED EVENTS ====================

class GitCloneEvent(StatusEvent):
    """Git cloning progress event.

    Specialized status event for git clone operations with
    clone-specific fields.

    Attributes:
        repo_url: Repository being cloned
        commit_hash: Commit hash after clone
        is_cached: Whether cache was used
        cache_key: Cache key for debugging
    """
    service: str = "git_clone"
    repo_url: Optional[str] = None
    commit_hash: Optional[str] = None
    is_cached: Optional[bool] = None
    cache_key: Optional[str] = None


class AssetGenerationEvent(ProgressEvent):
    """Asset generation progress event.

    Specialized progress event for sprite/asset generation.

    Attributes:
        asset_type: Type of asset (character, enemy, item, etc.)
        asset_name: Name or description of the asset
        image_base64: Preview image as base64
    """
    service: str = "asset_generation"
    asset_type: Optional[str] = None
    asset_name: Optional[str] = None
    image_base64: Optional[str] = None


# ==================== AGENT EVENTS ====================


class FollowUpReceivedEvent(BaseEvent):
    """Follow-up instruction received during game creation.

    Emitted when the user provides additional instructions while
    the agent is creating a game.

    Attributes:
        instruction: The follow-up instruction text
        source: How the instruction was provided (voice, text)
    """
    category: EventCategory = EventCategory.USER
    instruction: str
    source: str = "text"  # "voice" or "text"


class CLIStreamEvent(BaseEvent):
    """Raw structured event from Claude Code CLI stream.

    Carries tool name, inputs, and results so the frontend
    can render typed cards (file, command, asset, etc.).
    """
    category: EventCategory = EventCategory.USER
    stream_type: str  # "thinking", "tool_use", "tool_result", "status", "error", "complete"
    tool_name: Optional[str] = None
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    content: str = ""
    cost_usd: Optional[float] = None
