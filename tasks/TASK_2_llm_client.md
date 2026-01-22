# Task 2: LLM Client with Circuit Breaker

## Goal

Implement the two-tier LLM client with circuit breaker pattern and response caching.

## Dependencies

- Task 1 completed (directory structure exists)

## Files to Create

1. `src/custom_rag/rlm/llm_client.py` - LLMClient, CircuitBreaker, ResponseCache

## Context

The LLM client implements:
- **Two-tier architecture**: Orchestrator (gpt-4o) for reasoning, Worker (gpt-4o-mini) for chunks
- **Circuit breaker**: Prevents thundering herd on sustained API failures
- **Response cache**: LRU cache with TTL for repeated queries
- **Retry with backoff**: Handles transient failures

## Implementation

### File: `src/custom_rag/rlm/llm_client.py`

```python
"""Two-tier LLM client with circuit breaker and caching."""

from __future__ import annotations

import enum
import hashlib
import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar, TYPE_CHECKING

from openai import OpenAI

if TYPE_CHECKING:
    from .rlm_rag import RLMConfig
    from custom_rag.token_tracker import TokenUsage

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================================
# Circuit Breaker
# ============================================================================

class CircuitState(enum.Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject requests
    HALF_OPEN = "half_open" # Testing recovery


@dataclass
class CircuitConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 3   # Failures before opening
    timeout: float = 60.0        # Seconds before half-open


class CircuitBreaker:
    """Circuit breaker to prevent thundering herd on API failures.

    States:
    - CLOSED: Normal operation, counting failures
    - OPEN: Rejecting all calls immediately (fail fast)
    - HALF_OPEN: Allowing one test call to check recovery

    Usage:
        breaker = CircuitBreaker()
        if breaker.can_execute():
            try:
                result = api_call()
                breaker.record_success()
            except Exception:
                breaker.record_failure()
        else:
            raise RuntimeError("Circuit open")
    """

    def __init__(self, config: CircuitConfig | None = None):
        self.config = config or CircuitConfig()
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._last_failure: float | None = None
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        """Get current state, transitioning OPEN -> HALF_OPEN if timeout passed."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if (self._last_failure is not None and
                    time.time() - self._last_failure >= self.config.timeout):
                    logger.info("Circuit breaker transitioning to HALF_OPEN")
                    self._state = CircuitState.HALF_OPEN
            return self._state

    def can_execute(self) -> bool:
        """Check if a call can proceed."""
        state = self.state
        if state == CircuitState.CLOSED:
            return True
        elif state == CircuitState.HALF_OPEN:
            return True  # Allow test call
        else:  # OPEN
            return False

    def record_success(self) -> None:
        """Record successful call - resets to CLOSED."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                logger.info("Circuit breaker CLOSED after successful test")
            self._state = CircuitState.CLOSED
            self._failures = 0

    def record_failure(self) -> None:
        """Record failed call - may open circuit."""
        with self._lock:
            self._failures += 1
            self._last_failure = time.time()

            if self._state == CircuitState.HALF_OPEN:
                logger.warning("Circuit breaker OPEN after failed test")
                self._state = CircuitState.OPEN
            elif self._failures >= self.config.failure_threshold:
                logger.warning(
                    f"Circuit breaker OPEN after {self._failures} failures"
                )
                self._state = CircuitState.OPEN

    def get_status(self) -> dict[str, Any]:
        """Get circuit breaker status for monitoring."""
        return {
            "state": self.state.value,
            "failures": self._failures,
            "last_failure": self._last_failure,
        }


# ============================================================================
# Response Cache
# ============================================================================

class ResponseCache:
    """Thread-safe LRU cache with TTL for LLM responses.

    Caches based on hash of (model, prompt) to avoid repeated API calls.
    """

    def __init__(self, max_entries: int = 100, ttl: float = 300.0):
        self.max_entries = max_entries
        self.ttl = ttl
        self._cache: dict[str, tuple[str, float]] = {}  # key -> (value, timestamp)
        self._lock = threading.RLock()

    def get(self, key: str) -> str | None:
        """Get cached value if exists and not expired."""
        with self._lock:
            if key in self._cache:
                value, timestamp = self._cache[key]
                if time.time() - timestamp < self.ttl:
                    return value
                # Expired - remove
                del self._cache[key]
            return None

    def set(self, key: str, value: str) -> None:
        """Set cached value, evicting oldest if full."""
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_entries:
                oldest_key = min(
                    self._cache.keys(),
                    key=lambda k: self._cache[k][1]
                )
                del self._cache[oldest_key]

            self._cache[key] = (value, time.time())

    def make_key(self, prompt: str, model: str, **kwargs) -> str:
        """Create cache key from prompt and model."""
        key_data = f"{model}:{prompt}:{sorted(kwargs.items())}"
        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            return {
                "entries": len(self._cache),
                "max_entries": self.max_entries,
                "ttl": self.ttl,
            }


# ============================================================================
# Chat Response
# ============================================================================

@dataclass
class ChatResponse:
    """Response from LLM chat completion."""
    content: str
    tokens_used: int
    cached: bool = False


# ============================================================================
# LLM Client
# ============================================================================

class LLMClient:
    """Two-tier LLM client with circuit breaker and caching.

    Architecture:
    - Orchestrator model (gpt-4o): Main reasoning, code generation
    - Worker model (gpt-4o-mini): Chunk processing, summaries

    Features:
    - Circuit breaker prevents cascading failures
    - Response caching reduces API calls
    - Exponential backoff retry for transient errors
    - Recursion depth tracking for sub-calls
    """

    def __init__(
        self,
        config: RLMConfig,
        token_usage: TokenUsage,
    ):
        self.config = config
        self.token_usage = token_usage

        # Initialize OpenAI client
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        self.client = OpenAI(api_key=api_key)

        # Circuit breaker
        self._circuit = CircuitBreaker(CircuitConfig(
            failure_threshold=config.circuit_failure_threshold,
            timeout=config.circuit_timeout,
        ))

        # Response cache (optional)
        self._cache = ResponseCache(
            max_entries=config.cache_max_entries,
            ttl=config.cache_ttl_seconds,
        ) if config.enable_cache else None

        # Recursion tracking for sub-calls
        self._current_depth = 0

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4000,
    ) -> ChatResponse:
        """Send chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model to use (defaults to orchestrator_model)
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response

        Returns:
            ChatResponse with content and token usage

        Raises:
            RuntimeError: If circuit breaker is open
        """
        model = model or self.config.orchestrator_model

        # Check circuit breaker
        if not self._circuit.can_execute():
            raise RuntimeError(
                f"Circuit breaker OPEN - API unavailable. "
                f"Retry after {self.config.circuit_timeout}s"
            )

        # Check cache
        if self._cache:
            cache_key = self._cache.make_key(str(messages), model)
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for {model}")
                return ChatResponse(content=cached, tokens_used=0, cached=True)

        # Execute with retry
        try:
            response = self._retry(
                lambda: self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            )

            # Record success
            self._circuit.record_success()

            # Extract content and tokens
            content = response.choices[0].message.content or ""
            tokens = 0

            if response.usage:
                tokens = response.usage.prompt_tokens + response.usage.completion_tokens
                self.token_usage.add_prompt_tokens(response.usage.prompt_tokens)
                self.token_usage.add_completion_tokens(response.usage.completion_tokens)

            # Cache response
            if self._cache:
                self._cache.set(cache_key, content)

            return ChatResponse(content=content, tokens_used=tokens)

        except Exception as e:
            self._circuit.record_failure()
            raise

    def call(
        self,
        prompt: str,
        context: str | None = None,
        mode: str = "analysis",
    ) -> str:
        """Sub-LLM call for REPL use (uses worker model).

        This method is exposed in the REPL namespace as `call_sub_llm()`.

        Args:
            prompt: Task prompt
            context: Optional context to include
            mode: One of "analysis", "summarize", "extract"

        Returns:
            LLM response text, or error message starting with [ERROR:
        """
        # Check recursion depth
        if self._current_depth >= self.config.max_recursion_depth:
            return "[ERROR: Max recursion depth reached]"

        self._current_depth += 1

        try:
            # Build full prompt
            if context:
                full_prompt = f"Context:\n{context}\n\nTask:\n{prompt}"
            else:
                full_prompt = prompt

            # Get system prompt for mode
            system_prompts = {
                "analysis": "Analyze the content and provide detailed insights. Be thorough but concise.",
                "summarize": "Summarize the content concisely. Extract the most important points.",
                "extract": "Extract specific facts and data. Return structured information.",
            }
            system_prompt = system_prompts.get(mode, system_prompts["analysis"])

            # Use worker model for sub-calls
            response = self.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": full_prompt},
                ],
                model=self.config.worker_model,
                max_tokens=2000,
            )

            return response.content

        except Exception as e:
            logger.error(f"Sub-LLM call failed: {e}")
            return f"[ERROR: {e}]"

        finally:
            self._current_depth -= 1

    def _retry(self, func: Callable[[], T]) -> T:
        """Execute function with exponential backoff retry.

        Only retries on transient errors (rate limits, timeouts, connection).
        """
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                return func()
            except Exception as e:
                last_error = e

                if attempt == self.config.max_retries:
                    break

                # Only retry on transient errors
                error_str = str(e).lower()
                transient_indicators = [
                    "rate_limit", "429",
                    "timeout", "timed out",
                    "connection", "connect",
                    "overloaded", "capacity",
                ]

                if any(indicator in error_str for indicator in transient_indicators):
                    delay = min(
                        self.config.retry_base_delay * (2 ** attempt) + random.uniform(0, 1),
                        30.0  # Cap at 30 seconds
                    )
                    logger.warning(
                        f"Retrying after {delay:.1f}s (attempt {attempt + 1}): {e}"
                    )
                    time.sleep(delay)
                else:
                    # Non-transient error - don't retry
                    raise

        raise last_error

    def get_circuit_status(self) -> dict[str, Any]:
        """Get circuit breaker status."""
        return self._circuit.get_status()

    def get_cache_stats(self) -> dict[str, Any] | None:
        """Get cache statistics."""
        return self._cache.get_stats() if self._cache else None
```

## Update `__init__.py`

Add exports to `src/custom_rag/rlm/__init__.py`:

```python
"""RLM Filesystem RAG - Recursive Language Model approach for large corpora."""

from .rlm_rag import RLMFilesystemRAG, RLMConfig, StreamEvent
from .llm_client import LLMClient, CircuitBreaker, ChatResponse

__all__ = [
    "RLMFilesystemRAG",
    "RLMConfig",
    "StreamEvent",
    "LLMClient",
    "CircuitBreaker",
    "ChatResponse",
]
```

## Verification

```bash
# Check imports
python -c "
from custom_rag.rlm import LLMClient, CircuitBreaker
from custom_rag.rlm.llm_client import ResponseCache, CircuitState
print('Imports OK')
"

# Test circuit breaker
python -c "
from custom_rag.rlm.llm_client import CircuitBreaker, CircuitConfig

cb = CircuitBreaker(CircuitConfig(failure_threshold=2))
print(f'Initial state: {cb.state.value}')  # closed

cb.record_failure()
print(f'After 1 failure: {cb.state.value}')  # closed

cb.record_failure()
print(f'After 2 failures: {cb.state.value}')  # open

print(f'Can execute: {cb.can_execute()}')  # False
"

# Test response cache
python -c "
from custom_rag.rlm.llm_client import ResponseCache

cache = ResponseCache(max_entries=2, ttl=60.0)
key = cache.make_key('test prompt', 'gpt-4o')
cache.set(key, 'cached response')
print(f'Cached: {cache.get(key)}')  # cached response
print(f'Stats: {cache.get_stats()}')  # entries: 1
"
```

## Next Task

Proceed to `TASK_3_preparation.md` to implement document preparation and manifest management.
