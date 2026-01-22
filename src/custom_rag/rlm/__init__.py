"""RLM Filesystem RAG - Recursive Language Model approach for large corpora.

This subpackage implements an RLM-style RAG that treats the document corpus as
an external filesystem environment. The LLM writes Python code to explore,
filter, and analyze documents using recursive sub-calls.

Quick Start:
    >>> from custom_rag.rlm import RLMFilesystemRAG, RLMConfig
    >>> rag = RLMFilesystemRAG(rlm_config=RLMConfig())
    >>> rag.prepare_documents("./docs")
    >>> result = rag.query("What are the main topics?")
    >>> print(result["answer"])

Security Modes:
    - "lite" (default): Fast in-process execution for trusted environments
    - "full": Subprocess isolation for untrusted document content

Architecture:
    - RLMFilesystemRAG: Main entry point (inherits from BaseRAG)
    - RLMAgent: Orchestrates the exploration loop
    - LLMClient: Two-tier model with circuit breaker and caching
    - DocumentProcessor: Prepares document filesystem with indexes

See Also:
    - :class:`RLMConfig`: Configuration options
    - :class:`~custom_rag.base_rag.BaseRAG`: Base interface
    - https://arxiv.org/html/2512.24601v1: RLM paper
"""

from custom_rag import __version__

from .rlm_rag import RLMFilesystemRAG, RLMConfig, StreamEvent
from .llm_client import LLMClient, CircuitBreaker, ChatResponse
from .preparation import DocumentProcessor, ManifestManager, SimpleContextRAG
from .agent import (
    RLMAgent,
    RLMResponse,
    BudgetManager,
    FilesystemTools,
    SimpleREPL,
    ExecutionResult,
)
from .security import ProcessREPL, InjectionGuard, SecureFilesystemTools

__all__ = [
    # Version (inherited from parent package)
    "__version__",
    # Main API
    "RLMFilesystemRAG",
    "RLMConfig",
    "StreamEvent",
    # Agent components
    "RLMAgent",
    "RLMResponse",
    "BudgetManager",
    "FilesystemTools",
    "SimpleREPL",
    "ExecutionResult",
    # LLM client
    "LLMClient",
    "CircuitBreaker",
    "ChatResponse",
    # Preparation
    "DocumentProcessor",
    "ManifestManager",
    "SimpleContextRAG",
    # Security (opt-in)
    "ProcessREPL",
    "InjectionGuard",
    "SecureFilesystemTools",
]
