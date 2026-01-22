"""RLM-RAG: Recursive Language Model Filesystem RAG.

This package provides:
- RLMFilesystemRAG: An agentic RAG that uses code execution to explore document corpora
- CustomRAG: A baseline vector RAG for quick comparisons
- BaseRAG: Abstract interface for RAG Evaluator integration

Quick Start:
    >>> from custom_rag.rlm import RLMFilesystemRAG, RLMConfig
    >>> rag = RLMFilesystemRAG(rlm_config=RLMConfig())
    >>> rag.prepare_documents("./docs")
    >>> result = rag.query("What is RLM?")

See Also:
    - https://github.com/fabrizioamort/RAG-evaluator
    - https://arxiv.org/html/2512.24601v1 (RLM Paper)
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("custom-rag")
except PackageNotFoundError:
    __version__ = "0.6.0"  # Fallback for development installs

from custom_rag.base_rag import BaseRAG, RAGConfig
from custom_rag.provider_interfaces import (
    GeneratedAnswer,
    RetrievalTrace,
    RetrievedChunk,
    RetrievedContext,
)

# Avoid breaking when langchain is missing
try:
    from custom_rag.rag import CustomRAG
except ImportError:
    CustomRAG = None  # type: ignore

from custom_rag.token_tracker import TokenUsage
from custom_rag.exceptions import (
    RLMError,
    ConfigurationError,
    PreparationError,
    QueryError,
    BudgetExhaustedError,
    ExecutionError,
    LLMError,
    CircuitOpenError,
)

__all__ = [
    # Version
    "__version__",
    # Core interfaces
    "BaseRAG",
    "RAGConfig",
    # Implementations
    "CustomRAG",
    # Data structures
    "TokenUsage",
    "RetrievedChunk",
    "RetrievedContext",
    "RetrievalTrace",
    "GeneratedAnswer",
    # Exceptions
    "RLMError",
    "ConfigurationError",
    "PreparationError",
    "QueryError",
    "BudgetExhaustedError",
    "ExecutionError",
    "LLMError",
    "CircuitOpenError",
]
