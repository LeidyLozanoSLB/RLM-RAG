# Task 1: Directory Structure and Configuration

## Goal

Create the directory structure and implement `RLMConfig` dataclass with validation.

## Dependencies

- None (this is the first task)

## Files to Create

1. `src/custom_rag/rlm/__init__.py` - Package init (placeholder exports)
2. `src/custom_rag/rlm/rlm_rag.py` - RLMConfig dataclass + RLMFilesystemRAG stub

## Context

This task establishes the foundation. The `RLMConfig` dataclass holds all configuration with:
- Security mode toggle (`lite` vs `full`)
- Two-tier model naming (orchestrator/worker)
- Resource limits (REPL steps, file reads, sub-calls)
- Caching and retry settings

## Implementation

### File 1: `src/custom_rag/rlm/__init__.py`

```python
"""RLM Filesystem RAG - Recursive Language Model approach for large corpora."""

from .rlm_rag import RLMFilesystemRAG, RLMConfig

__all__ = [
    "RLMFilesystemRAG",
    "RLMConfig",
]
```

### File 2: `src/custom_rag/rlm/rlm_rag.py`

```python
"""RLM Filesystem RAG - Main entry point and configuration."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from custom_rag.base_rag import BaseRAG, RAGConfig
    from custom_rag.token_tracker import TokenUsage

logger = logging.getLogger(__name__)


@dataclass
class RLMConfig:
    """Configuration for RLM Filesystem RAG.

    v6: Simplified with security_mode toggle.

    Security Modes:
        - "lite": In-process REPL, no injection defense (trusted environments)
        - "full": Subprocess isolation, injection guard (untrusted content)
    """

    # === Security Mode ===
    security_mode: Literal["lite", "full"] = "lite"

    # === Two-Tier Model Architecture ===
    orchestrator_model: str = "gpt-4o"          # Main reasoning
    worker_model: str = "gpt-4o-mini"           # Chunk processing, summaries

    # === REPL Limits ===
    max_repl_steps: int = 15
    repl_timeout: float = 5.0                   # Seconds per step

    # === File Access ===
    max_file_reads: int = 12
    max_read_bytes: int = 50_000
    max_read_lines: int = 1000

    # === Sub-LLM Budget ===
    max_sub_calls: int = 8
    max_recursion_depth: int = 2
    max_tokens: int = 80_000

    # === Circuit Breaker ===
    circuit_failure_threshold: int = 3
    circuit_timeout: float = 60.0

    # === Retry ===
    max_retries: int = 3
    retry_base_delay: float = 1.0

    # === Caching ===
    enable_cache: bool = True
    cache_max_entries: int = 100
    cache_ttl_seconds: float = 300.0

    # === Routing ===
    small_corpus_threshold: int = 10            # Use SimpleContextRAG below this

    # === Preparation ===
    chunk_size: int = 1000
    chunk_overlap: int = 200
    use_llm_summaries: bool = True
    use_llm_topics: bool = True
    max_topics_per_doc: int = 5

    # === Confidence ===
    min_sources_for_high_confidence: int = 2    # Rule-based, no LLM verify

    # === Observability ===
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        """Validate configuration values."""
        errors = []

        if self.max_repl_steps < 1:
            errors.append("max_repl_steps must be >= 1")
        if self.max_repl_steps > 50:
            errors.append("max_repl_steps > 50 is excessive")

        if self.repl_timeout < 0.1:
            errors.append("repl_timeout must be >= 0.1 seconds")
        if self.repl_timeout > 60:
            errors.append("repl_timeout > 60s is too long")

        if self.max_file_reads < 1:
            errors.append("max_file_reads must be >= 1")

        if self.max_read_bytes < 1000:
            errors.append("max_read_bytes must be >= 1000")

        if self.chunk_overlap >= self.chunk_size:
            errors.append("chunk_overlap must be < chunk_size")

        if self.small_corpus_threshold < 1:
            errors.append("small_corpus_threshold must be >= 1")

        if self.circuit_failure_threshold < 1:
            errors.append("circuit_failure_threshold must be >= 1")

        if self.min_sources_for_high_confidence < 1:
            errors.append("min_sources_for_high_confidence must be >= 1")

        if self.security_mode not in ("lite", "full"):
            errors.append("security_mode must be 'lite' or 'full'")

        if errors:
            raise ValueError(f"Invalid RLMConfig: {'; '.join(errors)}")

    @property
    def use_process_isolation(self) -> bool:
        """Whether to use subprocess isolation for REPL."""
        return self.security_mode == "full"

    @property
    def use_injection_defense(self) -> bool:
        """Whether to wrap documents with injection defense."""
        return self.security_mode == "full"

    @property
    def use_strict_paths(self) -> bool:
        """Whether to enforce strict path whitelist."""
        return self.security_mode == "full"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        from dataclasses import asdict
        return asdict(self)


@dataclass
class StreamEvent:
    """Event emitted during streaming query execution."""
    event_type: str  # "step", "code", "output", "answer"
    content: str
    step: int
    metadata: dict[str, Any] = field(default_factory=dict)


class RLMFilesystemRAG:
    """RLM-style RAG using code execution for corpus exploration.

    v6 Features:
    - security_mode="lite" (default): Fast, trusts environment
    - security_mode="full": Process isolation, injection defense
    - Two-tier model: orchestrator + worker
    - Circuit breaker for reliability
    - Manifest-based cache invalidation

    Example:
        rag = RLMFilesystemRAG(rlm_config=RLMConfig(security_mode="lite"))
        rag.prepare_documents("./docs")
        result = rag.query("What are the main concepts?")
    """

    def __init__(
        self,
        config: RAGConfig | None = None,
        rlm_config: RLMConfig | None = None,
    ):
        # Import here to avoid circular imports during early development
        from custom_rag.base_rag import BaseRAG
        from custom_rag.token_tracker import TokenUsage

        self.name = "RLM Filesystem RAG"
        self.rlm_config = rlm_config or RLMConfig()
        self._token_usage = TokenUsage()

        # These will be initialized by prepare_documents
        self.agent = None
        self._prepared_path: Path | None = None
        self._manifest = None
        self._metrics: dict[str, Any] = {}
        self._use_simple_mode: bool = False
        self._simple_rag = None

        logger.info(
            f"RLMFilesystemRAG initialized: "
            f"security_mode={self.rlm_config.security_mode}, "
            f"orchestrator={self.rlm_config.orchestrator_model}"
        )

    def prepare_documents(self, documents_path: str, force: bool = False) -> None:
        """Prepare filesystem with indexes and summaries.

        Args:
            documents_path: Path to source documents directory
            force: If True, regenerate even if manifest unchanged
        """
        # TODO: Implement in Task 3 (preparation) and Task 6 (integration)
        raise NotImplementedError("Implement in Task 6")

    def query(self, question: str, top_k: int = 5) -> dict[str, Any]:
        """Execute RLM RAG pipeline.

        Args:
            question: The question to answer
            top_k: Number of documents for simple mode

        Returns:
            Dict with answer, context, and metadata
        """
        # TODO: Implement in Task 6 (integration)
        raise NotImplementedError("Implement in Task 6")

    def query_stream(
        self, question: str, top_k: int = 5
    ) -> Generator[StreamEvent, None, dict[str, Any]]:
        """Execute with streaming events for UI feedback."""
        # TODO: Implement in Task 6 (integration)
        raise NotImplementedError("Implement in Task 6")

    def get_metrics(self) -> dict[str, Any]:
        """Return RLM-specific metrics."""
        return {
            "prepared_path": str(self._prepared_path) if self._prepared_path else None,
            "mode": "simple" if self._use_simple_mode else "rlm_agent",
            "security_mode": self.rlm_config.security_mode,
            **self._metrics,
        }

    def reset_token_usage(self) -> None:
        """Reset token counters."""
        self._token_usage.reset()

    def close(self) -> None:
        """Clean up resources."""
        if self.agent:
            self.agent.close()
        if self._simple_rag:
            self._simple_rag = None
```

## Verification

After creating the files, verify with:

```bash
# Check imports work
cd src
python -c "from custom_rag.rlm import RLMConfig, RLMFilesystemRAG; print('OK')"

# Check config validation
python -c "
from custom_rag.rlm import RLMConfig

# Valid config
c = RLMConfig(security_mode='lite')
print(f'use_process_isolation: {c.use_process_isolation}')  # False

c = RLMConfig(security_mode='full')
print(f'use_process_isolation: {c.use_process_isolation}')  # True

# Invalid config should raise
try:
    RLMConfig(max_repl_steps=0)
except ValueError as e:
    print(f'Validation works: {e}')
"
```

## Next Task

Proceed to `TASK_2_llm_client.md` to implement the LLM client with circuit breaker.
