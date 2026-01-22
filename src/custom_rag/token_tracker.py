"""Token usage tracking for RAG implementations.

This module provides thread-safe token counting for tracking
LLM and embedding API usage across RAG operations.
"""

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenUsage:
    """Thread-safe token usage tracker.

    Tracks prompt tokens, completion tokens, and embedding tokens
    with thread-safe increments for concurrent operations.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    embedding_tokens: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def total_tokens(self) -> int:
        """Get total token count."""
        with self._lock:
            return self.prompt_tokens + self.completion_tokens + self.embedding_tokens

    def add_prompt_tokens(self, count: int) -> None:
        """Add to prompt token count (thread-safe)."""
        with self._lock:
            self.prompt_tokens += count

    def add_completion_tokens(self, count: int) -> None:
        """Add to completion token count (thread-safe)."""
        with self._lock:
            self.completion_tokens += count

    def add_embedding_tokens(self, count: int) -> None:
        """Add to embedding token count (thread-safe)."""
        with self._lock:
            self.embedding_tokens += count

    def reset(self) -> None:
        """Reset all counters to zero."""
        with self._lock:
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self.embedding_tokens = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        with self._lock:
            return {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "embedding_tokens": self.embedding_tokens,
                "total_tokens": self.total_tokens,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenUsage":
        """Create TokenUsage from dictionary."""
        usage = cls()
        usage.prompt_tokens = data.get("prompt_tokens", 0)
        usage.completion_tokens = data.get("completion_tokens", 0)
        usage.embedding_tokens = data.get("embedding_tokens", 0)
        return usage
