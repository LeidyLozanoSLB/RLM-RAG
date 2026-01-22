# BaseRAG

Abstract base class defining the standard RAG interface.

## Overview

`BaseRAG` provides the interface that all RAG implementations must follow for integration with the [RAG Evaluator](https://github.com/fabrizioamort/RAG-evaluator) platform.

Both `RLMFilesystemRAG` and `CustomRAG` inherit from this class.

## Class Reference

::: custom_rag.base_rag.BaseRAG
    options:
      show_root_heading: true
      show_source: false
      members:
        - __init__
        - prepare_documents
        - query
        - retrieve
        - generate
        - get_metrics
        - close

## Required Methods

| Method | Description |
|--------|-------------|
| `prepare_documents(path)` | Index documents from a directory |
| `query(question, top_k)` | Full RAG pipeline (retrieve + generate) |
| `get_metrics()` | Return implementation metrics |

## Optional Methods

| Method | Description |
|--------|-------------|
| `retrieve(question, top_k)` | Retrieval only (returns `RetrievedContext`) |
| `generate(question, context)` | Generation only (returns `GeneratedAnswer`) |
| `close()` | Clean up resources |

## Implementing a Custom RAG

```python
from custom_rag import BaseRAG, RAGConfig

class MyCustomRAG(BaseRAG):
    def __init__(self, config: RAGConfig | None = None):
        super().__init__(name="My Custom RAG", config=config)
        # Your initialization

    def prepare_documents(self, documents_path: str) -> None:
        # Index documents
        pass

    def query(self, question: str, top_k: int = 5) -> dict:
        return {
            "answer": "...",
            "context": ["..."],
            "metadata": {
                "retrieval_time": 0.0,
                "sources": ["..."],
            }
        }

    def get_metrics(self) -> dict:
        return {"total_documents": 0}
```

## See Also

- [RAGConfig](rlm-config.md) - Configuration class
- [Provider Interfaces](exceptions.md) - Data structures
