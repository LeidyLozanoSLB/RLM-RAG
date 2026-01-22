# RLMConfig

Configuration dataclass for RLM Filesystem RAG.

## Overview

`RLMConfig` provides all configuration options for `RLMFilesystemRAG`, including security mode, model selection, resource limits, and caching settings.

## Class Reference

::: custom_rag.rlm.RLMConfig
    options:
      show_root_heading: true
      show_source: false

## Configuration Options

### Security Mode

| Option | Value | Description |
|--------|-------|-------------|
| `security_mode` | `"lite"` | In-process REPL, fast, for trusted content |
| `security_mode` | `"full"` | Subprocess isolation, for untrusted content |

### Models

| Option | Default | Description |
|--------|---------|-------------|
| `orchestrator_model` | `"gpt-5-mini"` | Main reasoning model |
| `worker_model` | `"gpt-5-nano"` | Document processing model |

### Resource Limits

| Option | Default | Description |
|--------|---------|-------------|
| `max_repl_steps` | `15` | Max exploration steps per query |
| `max_file_reads` | `12` | Max file reads per query |
| `max_sub_calls` | `8` | Max sub-LLM calls per query |
| `max_read_bytes` | `50000` | Max bytes per file read |
| `max_read_lines` | `1000` | Max lines per file read |
| `repl_timeout` | `5.0` | Seconds timeout per REPL step |

### Routing

| Option | Default | Description |
|--------|---------|-------------|
| `small_corpus_threshold` | `10` | Use SimpleContextRAG at or below this count |

### Caching

| Option | Default | Description |
|--------|---------|-------------|
| `enable_cache` | `True` | Enable LLM response caching |
| `cache_max_entries` | `100` | LRU cache size |
| `cache_ttl_seconds` | `300.0` | Cache TTL in seconds |

### Circuit Breaker

| Option | Default | Description |
|--------|---------|-------------|
| `circuit_failure_threshold` | `3` | Failures before circuit opens |
| `circuit_timeout` | `60.0` | Seconds before recovery attempt |

### Preparation

| Option | Default | Description |
|--------|---------|-------------|
| `chunk_size` | `1000` | Characters per chunk |
| `chunk_overlap` | `200` | Overlap between chunks |
| `use_llm_summaries` | `True` | Generate LLM summaries |
| `use_llm_topics` | `True` | Extract LLM topics |
| `max_topics_per_doc` | `5` | Topics per document |

## Examples

### Minimal Configuration

```python
from custom_rag.rlm import RLMConfig

config = RLMConfig()  # All defaults
```

### Security-Focused

```python
config = RLMConfig(
    security_mode="full",
    max_repl_steps=10,
    repl_timeout=3.0,
)
```

### Performance-Focused

```python
config = RLMConfig(
    enable_cache=True,
    cache_max_entries=500,
    max_repl_steps=25,
    small_corpus_threshold=5,
)
```

### Cost-Optimized

```python
config = RLMConfig(
    use_llm_summaries=False,
    use_llm_topics=False,
    max_sub_calls=4,
)
```
