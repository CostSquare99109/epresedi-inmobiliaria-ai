"""Centralized retry utilities with configurable policies, backoff, jitter, and error classification.

This module provides a unified retry mechanism for all external operations:
- LLM/API HTTP calls
- Tool executions
- Database operations
- External service calls
- File operations
"""
from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)

T = TypeVar("T")


class ErrorCategory(Enum):
    """Classification of errors for retry decision making."""
    
    # Retryable - transient failures that may succeed on retry
    TRANSIENT_NETWORK = "transient_network"          # Connection reset, timeout, DNS
    TRANSIENT_HTTP_5XX = "transient_http_5xx"        # 500, 502, 503, 504
    TRANSIENT_RATE_LIMIT = "transient_rate_limit"    # 429 with Retry-After
    TRANSIENT_DB = "transient_db"                    # DB connection pool exhaustion, deadlock
    TRANSIENT_PROVIDER = "transient_provider"        # Provider-specific temporary errors
    
    # Non-retryable - permanent failures that won't succeed on retry
    PERMANENT_INVALID_ARGS = "permanent_invalid_args"   # Bad request, invalid parameters
    PERMANENT_NOT_FOUND = "permanent_not_found"         # 404, resource doesn't exist
    PERMANENT_AUTH = "permanent_auth"                   # 401, 403 - credentials invalid
    PERMANENT_PERMISSION = "permanent_permission"       # 403 - insufficient permissions
    PERMANENT_SCHEMA = "permanent_schema"               # Schema mismatch, incompatible version
    PERMANENT_LOGIC = "permanent_logic"                 # Business logic error (e.g., slot taken)
    PERMANENT_RESOURCE = "permanent_resource"           # Resource exhausted (quota, disk full)
    
    # Unknown - classify conservatively
    UNKNOWN = "unknown"


class OperationType(Enum):
    """Type of operation for selecting appropriate retry policy."""
    
    READ = "read"           # Safe to retry: SELECT, GET, search, list
    WRITE = "write"         # Mutating: INSERT, UPDATE, POST - needs idempotency
    IDEMPOTENT_WRITE = "idempotent_write"  # Mutating but idempotent: PUT with key, upsert
    LLM_CALL = "llm_call"   # LLM provider call
    TOOL_EXEC = "tool_exec" # Agent tool execution
    FILE_IO = "file_io"     # File system operations


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry behavior."""
    
    max_attempts: int = 3
    base_delay: float = 1.0          # Initial delay in seconds
    max_delay: float = 30.0          # Cap on delay
    exponential_base: float = 2.0    # Exponential backoff multiplier
    jitter_factor: float = 0.3       # Random jitter ±factor
    retryable_categories: frozenset[ErrorCategory] = field(default_factory=lambda: frozenset([
        ErrorCategory.TRANSIENT_NETWORK,
        ErrorCategory.TRANSIENT_HTTP_5XX,
        ErrorCategory.TRANSIENT_RATE_LIMIT,
        ErrorCategory.TRANSIENT_DB,
        ErrorCategory.TRANSIENT_PROVIDER,
    ]))
    timeout: float | None = None     # Per-attempt timeout (None = no timeout)
    
    def should_retry(self, category: ErrorCategory, attempt: int) -> bool:
        """Check if an error category should be retried at given attempt number.
        
        attempt is 0-indexed (0 = first attempt). With max_attempts=3, attempts 0, 1, 2 are allowed.
        """
        if attempt >= self.max_attempts - 1:
            return False
        return category in self.retryable_categories
    
    def calculate_delay(self, attempt: int, retry_after: float | None = None) -> float:
        """Calculate delay with exponential backoff and jitter."""
        if retry_after is not None:
            delay = min(retry_after, self.max_delay)
        else:
            delay = min(self.base_delay * (self.exponential_base ** attempt), self.max_delay)
        
        # Add jitter: delay * (1 ± jitter_factor)
        jitter = delay * self.jitter_factor * (random.random() * 2 - 1)
        return max(0, delay + jitter)


# Default policies per operation type
DEFAULT_POLICIES: dict[OperationType, RetryPolicy] = {
    OperationType.READ: RetryPolicy(
        max_attempts=3,
        base_delay=0.5,
        max_delay=10.0,
        exponential_base=2.0,
        jitter_factor=0.2,
    ),
    OperationType.WRITE: RetryPolicy(
        max_attempts=2,  # Conservative for writes
        base_delay=1.0,
        max_delay=15.0,
        exponential_base=2.0,
        jitter_factor=0.3,
    ),
    OperationType.IDEMPOTENT_WRITE: RetryPolicy(
        max_attempts=3,
        base_delay=1.0,
        max_delay=15.0,
        exponential_base=2.0,
        jitter_factor=0.3,
    ),
    OperationType.LLM_CALL: RetryPolicy(
        max_attempts=3,
        base_delay=1.5,
        max_delay=30.0,
        exponential_base=2.0,
        jitter_factor=0.2,
    ),
    OperationType.TOOL_EXEC: RetryPolicy(
        max_attempts=3,
        base_delay=0.5,
        max_delay=10.0,
        exponential_base=2.0,
        jitter_factor=0.3,
    ),
    OperationType.FILE_IO: RetryPolicy(
        max_attempts=3,
        base_delay=0.2,
        max_delay=5.0,
        exponential_base=2.0,
        jitter_factor=0.2,
    ),
}


def classify_exception(exc: Exception, operation_type: OperationType = OperationType.TOOL_EXEC) -> ErrorCategory:
    """Classify an exception into an ErrorCategory for retry decision."""
    exc_type = type(exc).__name__
    exc_msg = str(exc).lower()
    
    # HTTP errors (httpx, aiohttp, requests)
    if hasattr(exc, "response") and exc.response is not None:
        status = getattr(exc.response, "status_code", None)
        if status == 429:
            return ErrorCategory.TRANSIENT_RATE_LIMIT
        if status in (401, 403):
            return ErrorCategory.PERMANENT_AUTH
        if status == 404:
            return ErrorCategory.PERMANENT_NOT_FOUND
        if status == 400:
            return ErrorCategory.PERMANENT_INVALID_ARGS
        if status >= 500:
            return ErrorCategory.TRANSIENT_HTTP_5XX
    
    # httpx specific
    if "httpx" in exc_type.lower() or "httpx" in str(type(exc)).lower():
        if "timeout" in exc_msg:
            return ErrorCategory.TRANSIENT_NETWORK
        if "connect" in exc_msg or "connection" in exc_msg:
            return ErrorCategory.TRANSIENT_NETWORK
        if "pool" in exc_msg:
            return ErrorCategory.TRANSIENT_NETWORK
    
    # Database errors (asyncpg, psycopg, sqlalchemy)
    if any(db in exc_type.lower() for db in ("asyncpg", "psycopg", "sqlalchemy", "dbapi")):
        if any(kw in exc_msg for kw in ("deadlock", "serialization", "connection", "pool", "timeout")):
            return ErrorCategory.TRANSIENT_DB
        if "unique" in exc_msg or "duplicate" in exc_msg:
            return ErrorCategory.PERMANENT_LOGIC
        if "foreign key" in exc_msg:
            return ErrorCategory.PERMANENT_INVALID_ARGS
    
    # File I/O errors
    if isinstance(exc, (OSError, IOError, PermissionError, FileNotFoundError)):
        if isinstance(exc, FileNotFoundError):
            return ErrorCategory.PERMANENT_NOT_FOUND
        if isinstance(exc, PermissionError):
            return ErrorCategory.PERMANENT_PERMISSION
        if "space" in exc_msg or "quota" in exc_msg:
            return ErrorCategory.PERMANENT_RESOURCE
        return ErrorCategory.TRANSIENT_NETWORK
    
    # Timeout errors
    if "timeout" in exc_type.lower() or "timeout" in exc_msg:
        return ErrorCategory.TRANSIENT_NETWORK
    
    # LLM provider errors
    if hasattr(exc, "kind"):
        kind = getattr(exc, "kind", "")
        if kind in ("timeout", "server", "network", "rate_limit"):
            return ErrorCategory.TRANSIENT_PROVIDER
        if kind in ("auth",):
            return ErrorCategory.PERMANENT_AUTH
    
    # Tool-specific errors from our envelope
    if hasattr(exc, "envelope") or "tool" in exc_msg:
        # Check if the tool result had retryable flag
        pass  # Handled at tool level
    
    return ErrorCategory.UNKNOWN


def classify_tool_error(envelope: dict[str, Any]) -> ErrorCategory:
    """Classify a tool envelope error for retry decision."""
    if envelope.get("ok"):
        return ErrorCategory.UNKNOWN  # Not an error
    
    error = envelope.get("error", {})
    code = str(error.get("code", "")).upper()
    retryable = bool(error.get("retryable", True))
    
    # Map tool error codes to categories FIRST (more specific than retryable flag)
    if code in ("TIMEOUT", "NETWORK_ERROR", "CONNECTION_ERROR", "PROVIDER_TIMEOUT"):
        return ErrorCategory.TRANSIENT_NETWORK
    if code in ("RATE_LIMIT", "TOO_MANY_REQUESTS", "429"):
        return ErrorCategory.TRANSIENT_RATE_LIMIT
    if code in ("SERVER_ERROR", "500", "502", "503", "504"):
        return ErrorCategory.TRANSIENT_HTTP_5XX
    if code in ("DB_ERROR", "CONNECTION_POOL", "DEADLOCK"):
        return ErrorCategory.TRANSIENT_DB
    if code in ("NOT_FOUND", "404"):
        return ErrorCategory.PERMANENT_NOT_FOUND
    if code in ("BAD_ARGUMENTS", "INVALID_PARAMS", "VALIDATION_ERROR", "400"):
        return ErrorCategory.PERMANENT_INVALID_ARGS
    if code in ("UNAUTHORIZED", "FORBIDDEN", "401", "403"):
        return ErrorCategory.PERMANENT_AUTH
    if code in ("SLOT_UNAVAILABLE", "ALREADY_EXISTS", "CONFLICT"):
        return ErrorCategory.PERMANENT_LOGIC
    
    # Fall back to retryable flag for unknown codes
    if not retryable:
        return ErrorCategory.PERMANENT_LOGIC
    
    # Default to transient for unknown retryable errors
    return ErrorCategory.TRANSIENT_PROVIDER


async def execute_with_retry(
    func: Callable[..., Coroutine[Any, Any, T]],
    *args,
    policy: RetryPolicy | None = None,
    operation_type: OperationType = OperationType.TOOL_EXEC,
    operation_name: str = "operation",
    correlation_id: str | None = None,
    **kwargs,
) -> T:
    """Execute an async function with retry logic based on policy.
    
    Args:
        func: Async function to execute
        *args: Positional arguments for func
        policy: RetryPolicy to use (defaults to policy for operation_type)
        operation_type: Type of operation for default policy selection
        operation_name: Name for logging
        correlation_id: Request correlation ID for tracing
        **kwargs: Keyword arguments for func
    
    Returns:
        Result of successful func execution
    
    Raises:
        The last exception if all retries exhausted
    """
    if policy is None:
        policy = DEFAULT_POLICIES.get(operation_type, DEFAULT_POLICIES[OperationType.TOOL_EXEC])
        # Apply env override only for default policies
        settings = get_settings()
        max_attempts = getattr(settings, f"RETRY_{operation_type.name}_MAX_ATTEMPTS", None)
        if max_attempts is not None:
            policy = RetryPolicy(
                max_attempts=max_attempts,
                base_delay=policy.base_delay,
                max_delay=policy.max_delay,
                exponential_base=policy.exponential_base,
                jitter_factor=policy.jitter_factor,
                retryable_categories=policy.retryable_categories,
                timeout=policy.timeout,
            )
    
    last_exc: Exception | None = None
    start_time = time.monotonic()
    
    for attempt in range(policy.max_attempts):
        attempt_start = time.monotonic()
        try:
            if policy.timeout:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=policy.timeout)
            else:
                result = await func(*args, **kwargs)
            
            # Success - log if this was a retry
            if attempt > 0:
                elapsed = (time.monotonic() - start_time) * 1000
                log.info(
                    "retry_succeeded operation=%s attempt=%s/%s total_ms=%.0f correlation_id=%s",
                    operation_name, attempt + 1, policy.max_attempts, elapsed, correlation_id
                )
            return result
            
        except Exception as e:
            last_exc = e
            category = classify_exception(e, operation_type)
            elapsed_ms = int((time.monotonic() - attempt_start) * 1000)
            
            log.warning(
                "retry_attempt_failed operation=%s attempt=%s/%s category=%s elapsed_ms=%d correlation_id=%s error=%s",
                operation_name, attempt + 1, policy.max_attempts, category.value, elapsed_ms,
                correlation_id, str(e)[:200]
            )
            
            if not policy.should_retry(category, attempt):
                log.info(
                    "retry_exhausted_or_non_retryable operation=%s category=%s attempt=%s correlation_id=%s",
                    operation_name, category.value, attempt + 1, correlation_id
                )
                raise
            
            delay = policy.calculate_delay(attempt)
            
            # Check for Retry-After header in HTTP errors
            retry_after = None
            if hasattr(e, "response") and e.response is not None:
                retry_after_header = e.response.headers.get("retry-after")
                if retry_after_header:
                    try:
                        retry_after = float(retry_after_header)
                    except ValueError:
                        pass
            
            delay = policy.calculate_delay(attempt, retry_after)
            
            log.info(
                "retry_scheduling operation=%s attempt=%s/%s delay_ms=%d correlation_id=%s",
                operation_name, attempt + 1, policy.max_attempts, int(delay * 1000), correlation_id
            )
            
            await asyncio.sleep(delay)
    
    # Should not reach here, but just in case
    raise last_exc


class RetryableToolError(Exception):
    """Exception wrapper for tool errors that should trigger retry logic."""
    
    def __init__(self, envelope: dict[str, Any], tool_name: str):
        self.envelope = envelope
        self.tool_name = tool_name
        self.category = classify_tool_error(envelope)
        message = f"Tool {tool_name} failed: {envelope.get('error', {}).get('message', 'unknown')}"
        super().__init__(message)


def is_idempotent_tool(tool_name: str) -> bool:
    """Check if a tool is idempotent (safe to retry without side effects)."""
    # Read-only tools are always idempotent
    read_only_tools = {
        "search_properties",
        "get_property",
        "compare_properties",
        "search_documents",
        "get_property_images",
        "list_saved_searches",
        "get_customer_profile",
        "list_available_slots",
        "list_appointments",
        "recommend_similar",
    }
    
    # Tools with idempotency keys
    idempotent_write_tools = {
        "save_search",      # Uses name + filters as natural key
        "update_conversation_state",  # State merge is idempotent
    }
    
    return tool_name in read_only_tools or tool_name in idempotent_write_tools


def requires_idempotency_key(tool_name: str) -> bool:
    """Check if a tool requires explicit idempotency key for safe retry."""
    mutating_tools = {
        "save_property",
        "remove_saved_property",
        "create_lead",
        "schedule_visit",
        "cancel_appointment",
        "reschedule_appointment",
    }
    return tool_name in mutating_tools


def generate_idempotency_key(tool_name: str, args: dict[str, Any], conversation_id: str, user_id: int) -> str:
    """Generate deterministic idempotency key for a tool call."""
    import hashlib
    import json
    
    # Create a stable representation of the tool call
    key_data = {
        "tool": tool_name,
        "args": args,
        "conversation_id": conversation_id,
        "user_id": user_id,
    }
    serialized = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()[:32]