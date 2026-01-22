# Exceptions

Custom exception hierarchy for RLM-RAG.

## Overview

RLM-RAG provides a structured exception hierarchy for better error handling and debugging.

## Exception Hierarchy

```
RLMError (base)
├── ConfigurationError - Invalid configuration values
├── PreparationError - Document preparation failures
├── QueryError - Query execution failures
│   ├── BudgetExhaustedError - Resource limits exceeded
│   └── ExecutionError - REPL code execution failed
└── LLMError - LLM-related failures
    └── CircuitOpenError - Circuit breaker is open
```

## Class Reference

::: custom_rag.exceptions
    options:
      show_root_heading: false
      members:
        - RLMError
        - ConfigurationError
        - PreparationError
        - QueryError
        - BudgetExhaustedError
        - ExecutionError
        - LLMError
        - CircuitOpenError

## Usage Examples

### Catching All RLM Errors

```python
from custom_rag import RLMError

try:
    result = rag.query("question")
except RLMError as e:
    logger.error(f"RLM-RAG error: {e}")
    logger.debug(f"Details: {e.details}")
```

### Handling Specific Errors

```python
from custom_rag import (
    CircuitOpenError,
    BudgetExhaustedError,
    PreparationError,
)

try:
    rag.prepare_documents("./docs")
    result = rag.query("question")
except CircuitOpenError as e:
    print(f"API unavailable, retry in {e.timeout_remaining}s")
except BudgetExhaustedError as e:
    print(f"Exceeded {e.resource_type} limit: {e.used}/{e.limit}")
except PreparationError as e:
    print(f"Failed documents: {e.failed_documents}")
```

### Error Details

All exceptions include a `details` dict with debugging information:

```python
try:
    result = rag.query("complex question")
except BudgetExhaustedError as e:
    print(e.message)           # Human-readable message
    print(e.details)           # {"resource_type": "repl_steps", "limit": 15, "used": 15}
    print(e.resource_type)     # "repl_steps"
    print(e.limit)             # 15
```
