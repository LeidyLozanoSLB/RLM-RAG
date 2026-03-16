# Quick Start

This guide shows you how to use RLM-RAG in under 5 minutes.

Before running examples, set either `OPENAI_API_KEY` (OpenAI) or
`AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY` (Azure OpenAI).

## Basic Usage

### 1. Create a RAG Instance

```python
from custom_rag.rlm import RLMFilesystemRAG, RLMConfig

# Default configuration (lite mode, gpt-5-mini)
rag = RLMFilesystemRAG()

# Or with custom configuration
rag = RLMFilesystemRAG(rlm_config=RLMConfig(
    security_mode="lite",           # or "full" for untrusted docs
    orchestrator_model="gpt-5-mini",
    worker_model="gpt-5-nano",
    small_corpus_threshold=10,      # Use simple mode below this
))
```

### 2. Prepare Documents

```python
# Index documents from a directory
rag.prepare_documents("./my_documents")

# Supports: .txt, .md, .pdf, .docx
# Creates: ./my_documents_prepared/ with indexes
```

### 3. Query

```python
result = rag.query("What are the main topics discussed?")

print(result["answer"])
print(f"Confidence: {result['metadata']['confidence']}")
print(f"Sources: {result['metadata']['sources']}")
```

### 4. Cleanup

```python
rag.close()

# Or use context manager
with RLMFilesystemRAG() as rag:
    rag.prepare_documents("./docs")
    result = rag.query("question")
```

## Response Format

```python
{
    "answer": "The answer text...",
    "context": ["conversation history..."],
    "metadata": {
        "retrieval_time": 5.2,
        "generation_time": 0.0,
        "sources": ["doc1", "doc2"],
        "confidence": "HIGH",      # HIGH | MEDIUM | LOW
        "token_usage": {...},
        "trace": {...},            # Exploration steps
        "mode": "rlm_agent",       # or "simple_context"
        "security_mode": "lite",
    }
}
```

## Security Modes

| Mode | Use Case | Features |
|------|----------|----------|
| `lite` | Trusted docs, development | Fast, in-process execution |
| `full` | User uploads, production | Subprocess isolation, injection defense |

```python
# For untrusted content
rag = RLMFilesystemRAG(rlm_config=RLMConfig(
    security_mode="full"
))
```

## Streamlit UI

For interactive exploration:

```bash
uv run streamlit run examples/streamlit_app.py
```

## Next Steps

- Read the [Architecture Guide](../architecture.md)
- See [API Reference](../api/rlm-filesystem-rag.md)
- Check [RAG Evaluator Integration](../integration/rag-evaluator.md)
