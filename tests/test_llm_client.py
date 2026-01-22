"""Tests for LLM client components."""

import time
import pytest
from unittest.mock import Mock, patch, MagicMock

from custom_rag.rlm.llm_client import (
    CircuitBreaker,
    CircuitConfig,
    CircuitState,
    ResponseCache,
    LLMClient,
)
from custom_rag.rlm import RLMConfig
from custom_rag.token_tracker import TokenUsage
from custom_rag.exceptions import CircuitOpenError


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_initial_state_closed(self):
        """Test initial state is CLOSED."""
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True

    def test_opens_after_threshold(self):
        """Test circuit opens after failure threshold."""
        cb = CircuitBreaker(CircuitConfig(failure_threshold=2))

        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False

    def test_success_resets_failures(self):
        """Test success resets failure count."""
        cb = CircuitBreaker(CircuitConfig(failure_threshold=3))

        cb.record_failure()
        cb.record_failure()
        cb.record_success()

        assert cb.state == CircuitState.CLOSED
        assert cb._failures == 0

    def test_half_open_after_timeout(self):
        """Test transition to HALF_OPEN after timeout."""
        # Use a short timeout for tests
        cb = CircuitBreaker(CircuitConfig(failure_threshold=1, timeout=0.1))

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.can_execute() is True

    def test_half_open_to_closed_on_success(self):
        """Test HALF_OPEN transitions to CLOSED on success."""
        cb = CircuitBreaker(CircuitConfig(failure_threshold=1, timeout=0.1))

        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        """Test HALF_OPEN transitions to OPEN on failure."""
        cb = CircuitBreaker(CircuitConfig(failure_threshold=1, timeout=0.1))

        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_get_status(self):
        """Test status reporting."""
        cb = CircuitBreaker()
        cb.record_failure()

        status = cb.get_status()
        assert status["state"] == "closed"
        assert status["failures"] == 1


class TestResponseCache:
    """Test response cache."""

    def test_get_set(self):
        """Test basic get/set operations."""
        cache = ResponseCache(max_entries=10, ttl=60.0)
        key = cache.make_key("test prompt", "gpt-4o")

        cache.set(key, "response")
        assert cache.get(key) == "response"

    def test_cache_miss(self):
        """Test cache miss returns None."""
        cache = ResponseCache()
        key = cache.make_key("not cached", "gpt-4o")
        assert cache.get(key) is None

    def test_ttl_expiry(self):
        """Test entries expire after TTL."""
        cache = ResponseCache(ttl=0.1)
        key = cache.make_key("test", "gpt-4o")

        cache.set(key, "response")
        assert cache.get(key) == "response"

        time.sleep(0.15)
        assert cache.get(key) is None

    def test_max_entries_eviction(self):
        """Test oldest entry evicted when full."""
        cache = ResponseCache(max_entries=2, ttl=60.0)

        cache.set("key1", "value1")
        time.sleep(0.01)  # Ensure different timestamps
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_make_key_deterministic(self):
        """Test key generation is deterministic."""
        cache = ResponseCache()
        key1 = cache.make_key("prompt", "model")
        key2 = cache.make_key("prompt", "model")
        assert key1 == key2

    def test_make_key_different_inputs(self):
        """Test different inputs produce different keys."""
        cache = ResponseCache()
        key1 = cache.make_key("prompt1", "model")
        key2 = cache.make_key("prompt2", "model")
        assert key1 != key2


class TestLLMClient:
    """Test LLM client (with mocked API)."""

    @pytest.fixture
    def mock_openai(self):
        """Create mock OpenAI client."""
        with patch("custom_rag.rlm.llm_client.OpenAI") as mock:
            yield mock

    @pytest.fixture
    def client(self, mock_openai):
        """Create LLM client with mocked OpenAI."""
        mock_openai.return_value = MagicMock()

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            config = RLMConfig()
            token_usage = TokenUsage()
            return LLMClient(config=config, token_usage=token_usage)

    def test_init_requires_api_key(self):
        """Test initialization fails without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                config = RLMConfig()
                LLMClient(config=config, token_usage=TokenUsage())

    def test_chat_circuit_breaker_check(self, client):
        """Test chat checks circuit breaker."""
        # Open the circuit
        client._circuit._state = CircuitState.OPEN
        client._circuit._last_failure = time.time()

        with pytest.raises(CircuitOpenError, match="Circuit breaker OPEN"):
            client.chat([{"role": "user", "content": "test"}])

    def test_call_respects_recursion_depth(self, client):
        """Test sub-call respects max recursion depth."""
        client._current_depth = client.config.max_recursion_depth

        result = client.call("test prompt")
        assert "[ERROR: Max recursion depth reached]" in result
