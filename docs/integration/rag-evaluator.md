# RAG Evaluator Integration

Guide for integrating RLM-RAG with the [RAG Evaluator](https://github.com/fabrizioamort/RAG-evaluator) platform.

## Overview

RLM-RAG is designed for seamless integration with RAG Evaluator, enabling:

- Automated benchmarking against datasets
- Comparison with other RAG implementations
- Standardized metrics collection

## BaseRAG Compliance

`RLMFilesystemRAG` inherits from `BaseRAG`, implementing all required methods:

| Method | Status | Notes |
|--------|--------|-------|
| `prepare_documents()` | ✅ | Returns metrics dict (extends base) |
| `query()` | ✅ | Full compliance |
| `get_metrics()` | ✅ | Includes RLM-specific stats |
| `retrieve()` | ✅ | Inherited from BaseRAG |
| `generate()` | ✅ | Inherited from BaseRAG |
| `close()` | ✅ | Cleans up agent resources |

## Integration Steps

### 1. Copy Implementation

Copy the RLM-RAG source to your RAG Evaluator installation:

```bash
# From RLM-RAG directory
cp -r src/custom_rag/ \
  /path/to/RAG-evaluator/src/rag_evaluator/rag_implementations/rlm_rag/
```

### 2. Update Imports

Update imports to use RAG Evaluator's base classes:

```python
# Before (RLM-RAG standalone)
from custom_rag.base_rag import BaseRAG, RAGConfig

# After (RAG Evaluator integration)
from rag_evaluator.common.base_rag import BaseRAG, RAGConfig
```

### 3. Register Implementation

Register in the evaluator CLI or configuration:

```python
# In evaluator config
from rag_evaluator.rag_implementations.rlm_rag import RLMFilesystemRAG

evaluator.register_rag(
    name="RLM Filesystem RAG",
    implementation=RLMFilesystemRAG,
    config={"security_mode": "lite"},
)
```

## Direct Usage (No Copy)

If you prefer to use RLM-RAG as a dependency:

```python
# Install RLM-RAG
pip install git+https://github.com/fabrizioamort/RLM-RAG.git

# Use in evaluator
from custom_rag.rlm import RLMFilesystemRAG, RLMConfig

rag = RLMFilesystemRAG(rlm_config=RLMConfig())
evaluator.add_rag(rag)
```

## Metrics Mapping

RLM-RAG metrics map to evaluator metrics:

| RLM-RAG | RAG Evaluator | Description |
|---------|---------------|-------------|
| `retrieval_time` | `retrieval_latency` | Time for exploration |
| `token_usage.total_tokens` | `tokens_used` | API tokens consumed |
| `metadata.sources` | `retrieved_documents` | Source documents |
| `metadata.confidence` | `confidence_score` | HIGH/MEDIUM/LOW |

## Evaluation Example

```python
from rag_evaluator import Evaluator
from custom_rag.rlm import RLMFilesystemRAG, RLMConfig

# Create evaluator
evaluator = Evaluator(dataset="squad")

# Add RLM-RAG
rag = RLMFilesystemRAG(rlm_config=RLMConfig(
    small_corpus_threshold=5,
    max_repl_steps=20,
))
evaluator.add_rag("RLM-RAG", rag)

# Run evaluation
results = evaluator.run()
print(results.summary())
```

## Trace Inspection

RLM-RAG provides detailed traces for debugging:

```python
result = rag.query("question")
trace = result["metadata"]["trace"]

# Exploration steps
for step in trace["steps"]:
    print(f"Step {step['step']}: {step['success']}")
    print(f"  Code: {step['code'][:100]}...")
    print(f"  Output: {step['output'][:100]}...")

# Files accessed
print(f"Files: {trace['files_accessed']}")
```

## See Also

- [RAG Evaluator Documentation](https://github.com/fabrizioamort/RAG-evaluator/blob/main/docs/custom_rag_integration.md)
- [BaseRAG Interface](../api/base-rag.md)
