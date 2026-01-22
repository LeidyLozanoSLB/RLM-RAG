# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RLM-RAG is a template project for building custom RAG (Retrieval-Augmented Generation) systems designed to integrate with the [RAG Evaluator Platform](https://github.com/fabrizioamort/RAG-evaluator). It provides a standardized interface via abstract base classes, thread-safe token tracking, and provider interfaces for consistent data structures across RAG implementations.

## Development Commands

### Installation

```bash
uv sync
# or: pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
uv run pytest

# Run specific test class
uv run pytest tests/test_rag.py::TestCustomRAG

# Verbose output
uv run pytest -v
```

### Linting

```bash
uv run ruff check src/
uv run ruff format src/
uv run mypy src/custom_rag/
```

### Environment & Command Execution

- **Always use `uv run`**: This project uses `uv` for dependency management. Never run `python` directly; always prefix commands with `uv run` to ensure the correct virtual environment is active.
- **Source Layout**: The source code is located in the `src/` directory. If running scripts that aren't part of the installed package, ensure `src` is in your `PYTHONPATH` or use `uv run` which handles the editable install.
- **Background Processes**: When testing components that use `multiprocessing` (like `ProcessREPL`), be aware of Windows-specific process spawning requirements (always use `if __name__ == "__main__":`).

### Running Examples

```bash
uv run python examples/basic_usage.py
```

## Architecture

### Core Components

1. **BaseRAG** (`src/custom_rag/base_rag.py`) - Abstract base class defining the standard RAG interface
   - Required methods: `prepare_documents()`, `query()`, `get_metrics()`
   - Optional overrides: `retrieve()`, `generate()`, `close()`
   - Thread-local token tracking for concurrent operations

2. **Provider Interfaces** (`src/custom_rag/provider_interfaces.py`) - Standardized data classes
   - `RetrievedChunk`: Single chunk with metadata, score, rank
   - `RetrievalTrace`: Trace supporting vector/hybrid/graph/agentic strategies
   - `RetrievedContext`: Result of retrieval operation
   - `GeneratedAnswer`: Result of generation operation

3. **TokenUsage** (`src/custom_rag/token_tracker.py`) - Thread-safe token counting using `threading.RLock`

4. **CustomRAG** (`src/custom_rag/rag.py`) - Example implementation using OpenAI embeddings and LLM

### Key Patterns

- **Separation of Concerns**: `retrieve()` and `generate()` are separate methods; `query()` combines them
- **Interface-Based Design**: Implementations inherit from `BaseRAG` and override specific methods
- **Strategy Auto-Detection**: `_get_strategy_name()` infers strategy from class name (hybrid, graph, agentic, vector)

## Configuration

### Environment Variables (.env)

```bash
OPENAI_API_KEY=your-api-key-here
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

### Supported Document Types

- `.txt`, `.md` - Direct text loading
- `.pdf` - Requires `pypdf`
- `.docx` - Requires `python-docx`

## Return Format Conventions

### query() Returns

```python
{
    "answer": str,
    "context": list[str],
    "metadata": {
        "retrieval_time": float,
        "generation_time": float,
        "sources": list[str],
        "token_usage": {"prompt_tokens": int, "completion_tokens": int, "embedding_tokens": int, "total_tokens": int}
    }
}
```

### retrieve() Returns `RetrievedContext`, generate() Returns `GeneratedAnswer`

## Integration with RAG Evaluator

Copy implementation to RAG-evaluator's `src/rag_evaluator/rag_implementations/` directory, update imports to use RAG-evaluator's base classes, and register in the CLI.

## Future Development (v2)

Implementation plans exist for `RLMFilesystemRAG` - an advanced RAG using recursive language model concepts for large corpora. See `RLM-RAG-IMPLEMENTATION-PLAN-*.md` files.
