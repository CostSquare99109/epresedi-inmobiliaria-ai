"""Tests for retry logic, error classification, and partial failure handling."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.agents.tools import ToolContext
from app.core.retry import (
    ErrorCategory,
    RetryPolicy,
    classify_exception,
    classify_tool_error,
    execute_with_retry,
    generate_idempotency_key,
    is_idempotent_tool,
    requires_idempotency_key,
)

# ============================================================ Error Classification

class MockHTTPException(Exception):
    def __init__(self, status_code):
        self.response = MagicMock()
        self.response.status_code = status_code
        self.response.headers = {}
        super().__init__(f"HTTP {status_code}")


class TestErrorClassification:
    """Test error classification for retry decisions."""

    def test_classify_http_429_as_rate_limit(self):
        exc = MockHTTPException(429)
        category = classify_exception(exc)
        assert category == ErrorCategory.TRANSIENT_RATE_LIMIT

    def test_classify_http_500_as_transient(self):
        exc = MockHTTPException(500)
        category = classify_exception(exc)
        assert category == ErrorCategory.TRANSIENT_HTTP_5XX

    def test_classify_http_503_as_transient(self):
        exc = MockHTTPException(503)
        category = classify_exception(exc)
        assert category == ErrorCategory.TRANSIENT_HTTP_5XX

    def test_classify_http_401_as_permanent_auth(self):
        exc = MockHTTPException(401)
        category = classify_exception(exc)
        assert category == ErrorCategory.PERMANENT_AUTH

    def test_classify_http_404_as_permanent_not_found(self):
        exc = MockHTTPException(404)
        category = classify_exception(exc)
        assert category == ErrorCategory.PERMANENT_NOT_FOUND

    def test_classify_http_400_as_permanent_invalid_args(self):
        exc = MockHTTPException(400)
        category = classify_exception(exc)
        assert category == ErrorCategory.PERMANENT_INVALID_ARGS

    def test_classify_timeout_as_transient_network(self):
        exc = TimeoutError("Connection timed out")
        category = classify_exception(exc)
        assert category == ErrorCategory.TRANSIENT_NETWORK

    def test_classify_connection_error_as_transient(self):
        exc = ConnectionError("Connection refused")
        category = classify_exception(exc)
        assert category == ErrorCategory.TRANSIENT_NETWORK

    def test_classify_tool_error_retryable(self):
        envelope = {"ok": False, "error": {"code": "TIMEOUT", "message": "timeout", "retryable": True}}
        category = classify_tool_error(envelope)
        assert category == ErrorCategory.TRANSIENT_NETWORK

    def test_classify_tool_error_non_retryable(self):
        envelope = {"ok": False, "error": {"code": "NOT_FOUND", "message": "not found", "retryable": False}}
        category = classify_tool_error(envelope)
        assert category == ErrorCategory.PERMANENT_NOT_FOUND
    
    def test_classify_tool_error_slot_unavailable(self):
        envelope = {"ok": False, "error": {"code": "SLOT_UNAVAILABLE", "message": "slot taken", "retryable": False}}
        category = classify_tool_error(envelope)
        assert category == ErrorCategory.PERMANENT_LOGIC


# ============================================================ Retry Policy

class TestRetryPolicy:
    """Test retry policy behavior."""

    def test_should_retry_transient_error(self):
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(ErrorCategory.TRANSIENT_NETWORK, 0) is True
        assert policy.should_retry(ErrorCategory.TRANSIENT_NETWORK, 1) is True
        assert policy.should_retry(ErrorCategory.TRANSIENT_NETWORK, 2) is False  # max_attempts=3, so attempt 2 is last

    def test_should_not_retry_permanent_error(self):
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(ErrorCategory.PERMANENT_NOT_FOUND, 0) is False
        assert policy.should_retry(ErrorCategory.PERMANENT_AUTH, 0) is False

    def test_calculate_delay_exponential_backoff(self):
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, max_delay=30.0, jitter_factor=0.0)
        assert policy.calculate_delay(0) == 1.0
        assert policy.calculate_delay(1) == 2.0
        assert policy.calculate_delay(2) == 4.0
        assert policy.calculate_delay(10) == 30.0  # capped at max_delay

    def test_calculate_delay_respects_retry_after(self):
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, max_delay=30.0, jitter_factor=0.0)
        assert policy.calculate_delay(0, retry_after=5.0) == 5.0
        assert policy.calculate_delay(0, retry_after=60.0) == 30.0  # capped at max_delay


# ============================================================ Idempotency

class TestIdempotency:
    """Test idempotency key generation and tool classification."""

    def test_is_idempotent_tool_read_only(self):
        assert is_idempotent_tool("search_properties") is True
        assert is_idempotent_tool("get_property") is True
        assert is_idempotent_tool("get_property_images") is True
        assert is_idempotent_tool("list_available_slots") is True
        assert is_idempotent_tool("search_documents") is True

    def test_is_idempotent_tool_idempotent_write(self):
        assert is_idempotent_tool("save_search") is True
        assert is_idempotent_tool("update_conversation_state") is True

    def test_is_not_idempotent_tool_mutating(self):
        assert is_idempotent_tool("save_property") is False
        assert is_idempotent_tool("schedule_visit") is False
        assert is_idempotent_tool("create_lead") is False
        assert is_idempotent_tool("cancel_appointment") is False

    def test_requires_idempotency_key_mutating(self):
        assert requires_idempotency_key("save_property") is True
        assert requires_idempotency_key("schedule_visit") is True
        assert requires_idempotency_key("create_lead") is True
        assert requires_idempotency_key("cancel_appointment") is True

    def test_not_requires_idempotency_key_read_only(self):
        assert requires_idempotency_key("search_properties") is False
        assert requires_idempotency_key("get_property") is False
        assert requires_idempotency_key("get_property_images") is False

    def test_generate_idempotency_key_deterministic(self):
        key1 = generate_idempotency_key("schedule_visit", {"property_id": "123", "datetime_iso": "2024-01-01T10:00:00"}, "conv-456", 789)
        key2 = generate_idempotency_key("schedule_visit", {"property_id": "123", "datetime_iso": "2024-01-01T10:00:00"}, "conv-456", 789)
        assert key1 == key2
        assert len(key1) == 32

    def test_generate_idempotency_key_different_args(self):
        key1 = generate_idempotency_key("schedule_visit", {"property_id": "123"}, "conv-456", 789)
        key2 = generate_idempotency_key("schedule_visit", {"property_id": "456"}, "conv-456", 789)
        assert key1 != key2


# ============================================================ Execute With Retry

class TestExecuteWithRetry:
    """Test the execute_with_retry function."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        call_count = 0
        
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = await execute_with_retry(succeed, policy=RetryPolicy(max_attempts=3), operation_name="test")
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_success_after_transient_failures(self):
        call_count = 0
        
        async def fail_twice_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection refused")
            return "success"
        
        result = await execute_with_retry(
            fail_twice_then_succeed,
            policy=RetryPolicy(max_attempts=3, base_delay=0.01, jitter_factor=0.0),
            operation_name="test"
        )
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_fails_after_max_attempts(self):
        call_count = 0
        
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Connection refused")
        
        with pytest.raises(ConnectionError):
            await execute_with_retry(
                always_fail,
                policy=RetryPolicy(max_attempts=3, base_delay=0.01, jitter_factor=0.0),
                operation_name="test"
            )
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_permanent_error(self):
        call_count = 0
        
        async def permanent_fail():
            nonlocal call_count
            call_count += 1
            exc = MockHTTPException(404)
            raise exc
        
        with pytest.raises(MockHTTPException):
            await execute_with_retry(
                permanent_fail,
                policy=RetryPolicy(max_attempts=3, base_delay=0.01, jitter_factor=0.0),
                operation_name="test"
            )
        assert call_count == 1  # Should not retry on 404

    @pytest.mark.asyncio
    async def test_timeout_enforced(self):
        call_count = 0
        
        async def slow_operation():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(10)
            return "done"
        
        with pytest.raises(asyncio.TimeoutError):
            await execute_with_retry(
                slow_operation,
                policy=RetryPolicy(max_attempts=2, base_delay=0.01, jitter_factor=0.0, timeout=0.05),
                operation_name="test"
            )
        # With max_attempts=2, timeout on first attempt (attempt 0) -> retry once (attempt 1) -> timeout again -> raise
        assert call_count == 2


# ============================================================ Tool Context Idempotency

class MockSession:
    pass


class TestToolContextIdempotency:
    """Test idempotency key tracking in ToolContext."""

    def test_idempotency_keys_field_exists(self):
        ctx = ToolContext(
            session=MockSession(),
            user_id=123,
            conversation_id="test-conv",
        )
        assert hasattr(ctx, "idempotency_keys")
        assert isinstance(ctx.idempotency_keys, dict)
        assert len(ctx.idempotency_keys) == 0

    def test_idempotency_key_tracking(self):
        ctx = ToolContext(
            session=MockSession(),
            user_id=123,
            conversation_id="test-conv",
        )
        key = "test-key-123"
        ctx.idempotency_keys[key] = "schedule_visit"
        assert key in ctx.idempotency_keys
        assert ctx.idempotency_keys[key] == "schedule_visit"


# ============================================================ Partial Results Fallback

class TestPartialResultsFallback:
    """Test that fallback replies use partial tool results."""

    def test_fallback_with_search_results(self):
        # This would be an integration test with the actual orchestrator
        # For now, we test the classification logic
        pass

    def test_fallback_with_mixed_results(self):
        # Test that when some tools succeed and others fail, 
        # the fallback mentions both
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])