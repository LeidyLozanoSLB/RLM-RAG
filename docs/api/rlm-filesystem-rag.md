# RLMFilesystemRAG

The main entry point for RLM-style Retrieval-Augmented Generation.

## Overview

`RLMFilesystemRAG` treats a document corpus as a filesystem that an LLM agent explores by writing and executing Python code. It supports two modes:

- **Simple Context Mode**: For small corpora (≤ threshold), uses direct LLM call
- **Agent Mode**: For large corpora, uses iterative code execution

## Class Reference

::: custom_rag.rlm.RLMFilesystemRAG
    options:
      members:
        - __init__
        - prepare_documents
        - query
        - query_stream
        - get_metrics
        - close
      show_root_heading: true
      show_source: false

## Usage Examples

### Basic Usage

```python
from custom_rag.rlm import RLMFilesystemRAG, RLMConfig

rag = RLMFilesystemRAG(rlm_config=RLMConfig())
rag.prepare_documents("./documents")
result = rag.query("What are the key concepts?")
rag.close()
```

### With Context Manager

```python
with RLMFilesystemRAG() as rag:
    rag.prepare_documents("./docs")
    result = rag.query("Summarize the main topics")
```

### With Custom Configuration

```python
config = RLMConfig(
    security_mode="full",
    orchestrator_model="gpt-5-mini",
    max_repl_steps=20,
    small_corpus_threshold=5,
)

rag = RLMFilesystemRAG(rlm_config=config)
```

## See Also

- [RLMConfig](rlm-config.md) - Configuration options
- [BaseRAG](base-rag.md) - Base interface
- [Architecture](../architecture.md) - System design
