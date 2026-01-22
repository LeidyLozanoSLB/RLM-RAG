# Task 4: RLM Agent, REPL, and Filesystem Tools

## Goal

Implement the core RLM agent with:
- `BudgetManager` - Resource limit tracking
- `FilesystemTools` - `fs.*` namespace for document access
- `SimpleREPL` - In-process Python execution
- `RLMAgent` - Orchestration of the exploration loop

## Dependencies

- Task 1 completed (RLMConfig)
- Task 2 completed (LLMClient)
- Task 3 completed (preparation creates the filesystem structure)

## Files to Create

1. `src/custom_rag/rlm/agent.py` - All agent components
2. `src/custom_rag/rlm/prompts.py` - System prompts

## Context

The RLM agent:
1. Receives a question
2. Builds a corpus overview from the catalog
3. Sends question + system prompt to the orchestrator LLM
4. Extracts Python code from the response
5. Executes code in the REPL (with access to `fs.*` tools)
6. Feeds execution results back to the LLM
7. Repeats until `final_answer` is set or budget exhausted
8. Verifies confidence and returns structured response

## Implementation

### File 1: `src/custom_rag/rlm/prompts.py`

```python
"""System prompts for RLM agent."""

RLM_SYSTEM_PROMPT = """You are an RLM-RAG agent. Answer questions by writing Python code to explore a document filesystem.

## Execution Model
- Write Python code in ```python blocks
- Variables persist across execution steps
- Set `final_answer = "your answer"` when done

## Available Tools

### Filesystem (fs.*)
```python
fs.list_dir(path=".")              # List directory contents
fs.read_file(path, start_line=None, end_line=None, headers_only=False)
                                   # Read file (max {max_read_bytes} bytes)
fs.read_summary(doc_id)            # Read document summary
fs.grep(pattern, path="documents", max_results=20)
                                   # Search for regex pattern
fs.get_catalog()                   # Get document list with metadata
fs.get_topics()                    # Get topic -> [doc_ids] mapping
fs.get_sections(doc_id)            # Get section index for document
```

### Sub-LLM Calls
```python
result = call_sub_llm(prompt, context=None, mode="analysis")
# modes: "analysis", "summarize", "extract"
# Use for complex reasoning on retrieved content
```

### Budget Status
```python
budget.repl_steps_remaining        # Steps left in exploration
budget.file_reads_remaining        # File reads left
budget.sub_calls_remaining         # Sub-LLM calls left
```

### Allowed Built-ins
- re, json, math modules
- print() for output
- Basic types: str, int, float, list, dict, set, tuple
- Iteration: range, enumerate, zip, sorted, min, max, sum, any, all

### NOT Allowed
- import statements (modules pre-loaded)
- File writes
- Network access
- eval/exec

## Setting Your Answer

When you have the answer, set these variables:
```python
final_answer = "Your complete answer here"
confidence = "HIGH"  # or "MEDIUM" or "LOW"
sources_used = ["doc_id_1", "doc_id_2"]  # List of document IDs used
```

### Confidence Guidelines
- **HIGH**: {min_sources}+ distinct sources with direct, explicit evidence
- **MEDIUM**: 1 good source or reasonable inference from evidence
- **LOW**: Indirect evidence, uncertain, or couldn't find clear answer

Your confidence will be verified against actual sources used.

## Exploration Strategy

1. **Start broad**: Use `fs.get_catalog()` or `fs.get_topics()` to understand what's available
2. **Use summaries first**: `fs.read_summary(doc_id)` before reading full documents
3. **Search efficiently**: Use `fs.grep(pattern)` for specific terms
4. **Read selectively**: Use `start_line`/`end_line` for long documents
5. **Delegate complexity**: Use `call_sub_llm()` to analyze retrieved content
6. **Check budget**: Look at `budget` before expensive operations
7. **Cite sources**: Track which documents support your answer

## Filesystem Structure
```
_meta/           # Metadata
├── catalog.json        # Document list with metadata
└── section_index.json  # Section boundaries per document

_index/          # Indexes
└── topics/
    └── _topic_map.json # topic -> [doc_ids]

_summaries/      # LLM-generated summaries
└── {{doc_id}}_summary.md

documents/       # Full document content
└── {{doc_id}}.md
```

## Current Corpus
{corpus_overview}
"""


RLM_INITIAL_PROMPT = """Question: {question}

Explore the corpus to find the answer. Start by examining what documents are available."""
```

### File 2: `src/custom_rag/rlm/agent.py`

```python
"""RLM Agent with REPL and filesystem tools."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator, TYPE_CHECKING

if TYPE_CHECKING:
    from .rlm_rag import RLMConfig, StreamEvent
    from .llm_client import LLMClient
    from custom_rag.token_tracker import TokenUsage

from .prompts import RLM_SYSTEM_PROMPT, RLM_INITIAL_PROMPT

logger = logging.getLogger(__name__)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class RLMResponse:
    """Response from RLM agent query."""
    answer: str
    context: list[str]
    sources: list[str]
    confidence: str
    retrieval_time: float
    generation_time: float
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """Result from REPL code execution."""
    output: str
    success: bool
    error: str | None = None
    variables_updated: list[str] = field(default_factory=list)
    execution_time: float = 0.0


@dataclass
class BudgetStatus:
    """Current resource budget state."""
    repl_steps_remaining: int
    file_reads_remaining: int
    sub_calls_remaining: int
    tokens_remaining: int


# ============================================================================
# Budget Manager
# ============================================================================

class BudgetManager:
    """Track and enforce resource limits during exploration."""

    def __init__(self, config: RLMConfig):
        self.config = config
        self._repl_steps = 0
        self._file_reads = 0
        self._sub_calls = 0
        self._tokens_used = 0

    def can_step(self) -> bool:
        """Check if another REPL step is allowed."""
        return self._repl_steps < self.config.max_repl_steps

    def can_read_file(self) -> bool:
        """Check if another file read is allowed."""
        return self._file_reads < self.config.max_file_reads

    def can_sub_call(self) -> bool:
        """Check if another sub-LLM call is allowed."""
        return self._sub_calls < self.config.max_sub_calls

    def record_step(self) -> None:
        """Record a REPL step."""
        self._repl_steps += 1

    def record_file_read(self) -> None:
        """Record a file read."""
        self._file_reads += 1

    def record_sub_call(self, tokens: int = 0) -> None:
        """Record a sub-LLM call."""
        self._sub_calls += 1
        self._tokens_used += tokens

    def get_status(self) -> BudgetStatus:
        """Get current budget status."""
        return BudgetStatus(
            repl_steps_remaining=self.config.max_repl_steps - self._repl_steps,
            file_reads_remaining=self.config.max_file_reads - self._file_reads,
            sub_calls_remaining=self.config.max_sub_calls - self._sub_calls,
            tokens_remaining=self.config.max_tokens - self._tokens_used,
        )

    def reset(self) -> None:
        """Reset all counters for a new query."""
        self._repl_steps = 0
        self._file_reads = 0
        self._sub_calls = 0
        self._tokens_used = 0


# ============================================================================
# Filesystem Tools
# ============================================================================

class FilesystemTools:
    """Tools exposed as `fs.*` in the REPL namespace.

    Provides read-only access to the prepared document filesystem.
    """

    ALLOWED_SUBPATHS = frozenset({"_meta", "_index", "_summaries", "documents"})

    def __init__(
        self,
        prepared_path: Path,
        budget: BudgetManager,
        config: RLMConfig,
    ):
        self.prepared_path = prepared_path.resolve()
        self.budget = budget
        self.config = config
        self._accessed_files: list[str] = []

        # Load indexes into memory
        self._catalog = self._load_json("_meta/catalog.json")
        self._section_index = self._load_json("_meta/section_index.json")
        self._topic_map = self._load_json("_index/topics/_topic_map.json")

    def _validate_path(self, path: str) -> Path:
        """Validate and resolve path within prepared directory."""
        # Resolve to absolute
        target = (self.prepared_path / path).resolve()

        # Check containment
        try:
            target.relative_to(self.prepared_path)
        except ValueError:
            raise PermissionError(f"Path escapes prepared directory: {path}")

        # Check subpath whitelist (in strict mode)
        if self.config.use_strict_paths:
            rel = target.relative_to(self.prepared_path)
            if rel.parts and rel.parts[0] not in self.ALLOWED_SUBPATHS:
                raise PermissionError(
                    f"Access denied: {rel.parts[0]} not in allowed paths"
                )

        return target

    def list_dir(self, path: str = ".") -> list[dict[str, Any]]:
        """List directory contents with metadata."""
        try:
            target = self._validate_path(path)
        except PermissionError as e:
            return [{"error": str(e)}]

        if not target.exists():
            return []

        result = []
        for f in sorted(target.iterdir()):
            if f.name.startswith("."):
                continue
            result.append({
                "name": f.name,
                "is_dir": f.is_dir(),
                "size": f.stat().st_size if f.is_file() else 0,
            })
        return result

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
        headers_only: bool = False,
    ) -> str:
        """Read file contents with optional line selection.

        Args:
            path: Relative path within prepared directory
            start_line: Starting line (0-indexed, inclusive)
            end_line: Ending line (exclusive)
            headers_only: If True, only return markdown headers

        Returns:
            File content or error message
        """
        # Check budget
        if not self.budget.can_read_file():
            return "[ERROR: File read budget exhausted]"

        # Validate path
        try:
            target = self._validate_path(path)
        except PermissionError as e:
            return f"[ERROR: {e}]"

        if not target.exists():
            return f"[ERROR: File not found: {path}]"

        if not target.is_file():
            return f"[ERROR: Not a file: {path}]"

        # Read content
        try:
            content = target.read_text(encoding="utf-8")
        except Exception as e:
            return f"[ERROR: Failed to read: {e}]"

        # Apply filters
        if headers_only:
            lines = [line for line in content.split("\n") if line.startswith("#")]
            content = "\n".join(lines)
        elif start_line is not None or end_line is not None:
            lines = content.split("\n")
            content = "\n".join(lines[start_line:end_line])

        # Apply byte limit
        if len(content) > self.config.max_read_bytes:
            content = content[:self.config.max_read_bytes]
            content += f"\n\n[TRUNCATED at {self.config.max_read_bytes} bytes]"

        # Record access
        self.budget.record_file_read()
        self._accessed_files.append(path)

        return content

    def read_summary(self, doc_id: str) -> str:
        """Read document summary by ID."""
        return self.read_file(f"_summaries/{doc_id}_summary.md")

    def grep(
        self,
        pattern: str,
        path: str = "documents",
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for regex pattern in files.

        Args:
            pattern: Regular expression pattern
            path: Directory to search in
            max_results: Maximum matches to return

        Returns:
            List of {file, line, content} dicts
        """
        try:
            target = self._validate_path(path)
        except PermissionError as e:
            return [{"error": str(e)}]

        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return [{"error": f"Invalid regex: {e}"}]

        results = []
        for file_path in target.glob("**/*.md"):
            try:
                content = file_path.read_text(encoding="utf-8")
                for i, line in enumerate(content.split("\n")):
                    if compiled.search(line):
                        results.append({
                            "file": str(file_path.relative_to(self.prepared_path)),
                            "line": i + 1,
                            "content": line[:200],
                        })
                        if len(results) >= max_results:
                            return results
            except Exception:
                continue

        return results

    def get_catalog(self) -> list[dict[str, Any]]:
        """Get document catalog."""
        return self._catalog.get("documents", [])

    def get_topics(self) -> dict[str, list[str]]:
        """Get topic -> document IDs mapping."""
        return self._topic_map

    def get_sections(self, doc_id: str) -> list[dict[str, Any]]:
        """Get section index for a document."""
        return self._section_index.get(doc_id, [])

    def get_accessed_files(self) -> list[str]:
        """Return and clear list of accessed files."""
        files = self._accessed_files.copy()
        self._accessed_files = []
        return files

    def _load_json(self, rel_path: str) -> dict[str, Any]:
        """Load JSON file or return empty dict."""
        path = self.prepared_path / rel_path
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in {rel_path}: {e}")
        return {}


# ============================================================================
# Simple REPL (In-Process)
# ============================================================================

class SimpleREPL:
    """In-process Python REPL for trusted environments.

    Maintains a persistent namespace across executions, allowing
    variables to accumulate as the agent explores.

    Security note: This executes code directly in the Python process.
    Use ProcessREPL (in security.py) for untrusted content.
    """

    def __init__(
        self,
        tools: FilesystemTools,
        llm_client: LLMClient,
        budget: BudgetManager,
        timeout: float = 5.0,
    ):
        self.tools = tools
        self.llm_client = llm_client
        self.budget = budget
        self.timeout = timeout
        self._output: list[str] = []

        # Build persistent namespace
        self.namespace: dict[str, Any] = self._build_namespace()

    def _build_namespace(self) -> dict[str, Any]:
        """Build the execution namespace with tools and safe builtins."""
        return {
            # Filesystem tools
            "fs": self.tools,

            # Budget status (updated before each execution)
            "budget": self.budget.get_status(),

            # Sub-LLM call function
            "call_sub_llm": self.llm_client.call,

            # Print capture
            "print": self._capture_print,

            # Safe builtins
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "sorted": sorted,
            "reversed": reversed,
            "min": min,
            "max": max,
            "sum": sum,
            "any": any,
            "all": all,
            "abs": abs,
            "round": round,
            "isinstance": isinstance,
            "type": type,
            "hasattr": hasattr,
            "getattr": getattr,

            # Safe modules (pre-imported)
            "re": __import__("re"),
            "json": __import__("json"),
            "math": __import__("math"),
        }

    def _capture_print(self, *args, **kwargs) -> None:
        """Capture print output."""
        self._output.append(" ".join(str(a) for a in args))

    def execute(self, code: str) -> ExecutionResult:
        """Execute Python code in the namespace.

        Args:
            code: Python code to execute

        Returns:
            ExecutionResult with output, success status, and updated variables
        """
        self._output = []
        start_time = time.time()

        # Update budget in namespace
        self.namespace["budget"] = self.budget.get_status()

        # Track existing variables to detect new ones
        existing_vars = set(self.namespace.keys())

        try:
            # Compile and execute
            compiled = compile(code, "<repl>", "exec")
            exec(compiled, self.namespace)

            # Find new/updated variables
            new_vars = [
                k for k in self.namespace.keys()
                if k not in existing_vars and not k.startswith("_")
            ]

            return ExecutionResult(
                output="\n".join(self._output)[:10000],
                success=True,
                variables_updated=new_vars,
                execution_time=time.time() - start_time,
            )

        except Exception as e:
            return ExecutionResult(
                output="\n".join(self._output)[:10000],
                success=False,
                error=f"{type(e).__name__}: {e}",
                execution_time=time.time() - start_time,
            )

    def get_variable(self, name: str) -> Any:
        """Get a variable from the namespace."""
        return self.namespace.get(name)

    def reset(self) -> None:
        """Reset namespace to initial state (clear user variables)."""
        self.namespace = self._build_namespace()


# ============================================================================
# RLM Agent
# ============================================================================

class RLMAgent:
    """Orchestrates RLM-style exploration of document filesystem.

    The agent implements the core RLM loop:
    1. Build corpus overview from catalog
    2. Send question + system prompt to orchestrator LLM
    3. Extract and execute Python code from response
    4. Feed execution results back to LLM
    5. Repeat until final_answer is set or budget exhausted
    6. Verify confidence against sources
    """

    def __init__(
        self,
        prepared_path: Path | str,
        config: RLMConfig,
        token_usage: TokenUsage,
    ):
        self.prepared_path = Path(prepared_path)
        self.config = config
        self.token_usage = token_usage

        # Import here to avoid circular imports
        from .llm_client import LLMClient

        # Initialize components
        self.budget = BudgetManager(config)
        self.llm_client = LLMClient(config=config, token_usage=token_usage)
        self.tools = FilesystemTools(
            prepared_path=self.prepared_path,
            budget=self.budget,
            config=config,
        )

        # Choose REPL based on security mode
        if config.use_process_isolation:
            from .security import ProcessREPL
            self.repl = ProcessREPL(
                tools=self.tools,
                llm_client=self.llm_client,
                budget=self.budget,
                timeout=config.repl_timeout,
            )
        else:
            self.repl = SimpleREPL(
                tools=self.tools,
                llm_client=self.llm_client,
                budget=self.budget,
                timeout=config.repl_timeout,
            )

        # Build corpus overview for system prompt
        self._corpus_overview = self._build_corpus_overview()

    def _build_corpus_overview(self) -> str:
        """Build overview of corpus for system prompt."""
        catalog = self.tools.get_catalog()
        topics = self.tools.get_topics()

        # Document list (limit to 20)
        doc_lines = []
        for doc in catalog[:20]:
            doc_lines.append(
                f"- {doc['id']}: {doc.get('title', doc['id'])} "
                f"({doc.get('line_count', '?')} lines, "
                f"topics: {', '.join(doc.get('topics', [])[:3])})"
            )
        if len(catalog) > 20:
            doc_lines.append(f"- ... and {len(catalog) - 20} more documents")

        doc_list = "\n".join(doc_lines)

        # Top topics
        top_topics = sorted(topics.items(), key=lambda x: len(x[1]), reverse=True)[:10]
        topic_list = ", ".join(f"{t} ({len(docs)})" for t, docs in top_topics)

        return f"""
## Corpus Statistics
- Total documents: {len(catalog)}
- Total topics: {len(topics)}
- Top topics: {topic_list}

## Documents
{doc_list}
"""

    def query(self, question: str) -> RLMResponse:
        """Execute RLM query loop.

        Args:
            question: The question to answer

        Returns:
            RLMResponse with answer, sources, confidence, and trace
        """
        start_time = time.time()
        self.budget.reset()
        self.repl.reset()

        # Initialize trace
        trace: dict[str, Any] = {
            "steps": [],
            "files_accessed": [],
            "total_steps": 0,
        }

        # Build system prompt
        system_prompt = RLM_SYSTEM_PROMPT.format(
            corpus_overview=self._corpus_overview,
            max_read_bytes=self.config.max_read_bytes,
            min_sources=self.config.min_sources_for_high_confidence,
        )

        # Initialize conversation
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": RLM_INITIAL_PROMPT.format(question=question)},
        ]

        # Main exploration loop
        while self.budget.can_step():
            self.budget.record_step()
            step_num = self.config.max_repl_steps - self.budget.get_status().repl_steps_remaining

            # Get next response from orchestrator
            try:
                response = self.llm_client.chat(
                    messages=messages,
                    model=self.config.orchestrator_model,
                )
            except Exception as e:
                logger.error(f"Orchestrator call failed: {e}")
                break

            assistant_msg = response.content
            messages.append({"role": "assistant", "content": assistant_msg})

            # Extract code blocks
            code_blocks = self._extract_code(assistant_msg)

            if not code_blocks:
                # No code - check if final answer mentioned
                if "final_answer" in assistant_msg.lower():
                    # LLM might have set it without code block
                    break

                # Prompt for code
                messages.append({
                    "role": "user",
                    "content": (
                        "Please write Python code to explore the corpus. "
                        "Use ```python blocks."
                    ),
                })
                continue

            # Execute each code block
            for code in code_blocks:
                result = self.repl.execute(code)

                # Record in trace
                trace["steps"].append({
                    "step": step_num,
                    "code": code[:500] + ("..." if len(code) > 500 else ""),
                    "output": result.output[:500] + ("..." if len(result.output) > 500 else ""),
                    "success": result.success,
                    "error": result.error,
                    "time": result.execution_time,
                    "variables": result.variables_updated,
                })

                # Build observation message
                if result.success:
                    obs = f"```\n{result.output}\n```" if result.output else "(no output)"
                    if result.variables_updated:
                        obs += f"\n\nVariables set: {', '.join(result.variables_updated)}"
                else:
                    obs = f"ERROR: {result.error}"

                messages.append({"role": "user", "content": f"Observation:\n{obs}"})

            # Check for final answer
            final_answer = self.repl.get_variable("final_answer")
            if final_answer is not None:
                break

        # Extract results from namespace
        final_answer = self.repl.get_variable("final_answer")
        if final_answer is None:
            final_answer = "Unable to find answer within exploration budget."

        confidence = self.repl.get_variable("confidence") or "LOW"
        sources_used = self.repl.get_variable("sources_used") or []

        # Ensure sources_used is a list
        if not isinstance(sources_used, list):
            sources_used = [str(sources_used)]

        # Verify confidence
        verified_confidence = self._verify_confidence(confidence, sources_used)

        # Finalize trace
        trace["files_accessed"] = self.tools.get_accessed_files()
        trace["total_steps"] = step_num if 'step_num' in dir() else 0
        trace["confidence_original"] = confidence
        trace["confidence_verified"] = verified_confidence
        trace["budget_final"] = self.budget.get_status().__dict__

        return RLMResponse(
            answer=str(final_answer),
            context=[],  # Could extract from trace if needed
            sources=sources_used,
            confidence=verified_confidence,
            retrieval_time=time.time() - start_time,
            generation_time=0.0,  # Included in retrieval for RLM
            trace=trace,
        )

    def query_stream(
        self, question: str
    ) -> Generator[StreamEvent, None, dict[str, Any]]:
        """Streaming version with events.

        Yields StreamEvent objects during exploration, then returns final result.
        """
        from .rlm_rag import StreamEvent

        # For now, simplified implementation that yields progress
        # Full streaming would yield events during the loop

        result = self.query(question)

        # Yield step events from trace
        for step in result.trace.get("steps", []):
            yield StreamEvent(
                event_type="step",
                content=step.get("code", "")[:200],
                step=step.get("step", 0),
                metadata={"success": step.get("success", False)},
            )

        # Yield final answer
        yield StreamEvent(
            event_type="answer",
            content=result.answer,
            step=len(result.trace.get("steps", [])),
            metadata={
                "confidence": result.confidence,
                "sources": result.sources,
            },
        )

        return {
            "answer": result.answer,
            "context": result.context,
            "metadata": {
                "trace": result.trace,
                "confidence": result.confidence,
                "sources": result.sources,
            },
        }

    def _extract_code(self, text: str) -> list[str]:
        """Extract Python code blocks from LLM response."""
        pattern = r"```python\s*(.*?)\s*```"
        matches = re.findall(pattern, text, re.DOTALL)
        return [m.strip() for m in matches if m.strip()]

    def _verify_confidence(self, claimed: str, sources: list[str]) -> str:
        """Rule-based confidence verification.

        Downgrades HIGH confidence if insufficient sources.
        """
        source_count = len(set(sources)) if sources else 0

        if claimed.upper() == "HIGH":
            if source_count < self.config.min_sources_for_high_confidence:
                logger.info(
                    f"Downgrading HIGH to MEDIUM: "
                    f"{source_count} sources < {self.config.min_sources_for_high_confidence} required"
                )
                return "MEDIUM" if source_count >= 1 else "LOW"

        return claimed.upper()

    def get_stats(self) -> dict[str, Any]:
        """Get agent statistics for monitoring."""
        return {
            "circuit_breaker": self.llm_client.get_circuit_status(),
            "cache": self.llm_client.get_cache_stats(),
            "budget": self.budget.get_status().__dict__,
        }

    def close(self) -> None:
        """Clean up resources."""
        # SimpleREPL has no cleanup needed
        # ProcessREPL cleanup handled in security.py
        pass
```

## Update `__init__.py`

```python
"""RLM Filesystem RAG - Recursive Language Model approach for large corpora."""

from .rlm_rag import RLMFilesystemRAG, RLMConfig, StreamEvent
from .llm_client import LLMClient, CircuitBreaker, ChatResponse
from .preparation import DocumentProcessor, ManifestManager, SimpleContextRAG
from .agent import RLMAgent, RLMResponse, BudgetManager, FilesystemTools, SimpleREPL

__all__ = [
    # Main API
    "RLMFilesystemRAG",
    "RLMConfig",
    "StreamEvent",
    # Agent
    "RLMAgent",
    "RLMResponse",
    "BudgetManager",
    "FilesystemTools",
    "SimpleREPL",
    # LLM
    "LLMClient",
    "CircuitBreaker",
    "ChatResponse",
    # Preparation
    "DocumentProcessor",
    "ManifestManager",
    "SimpleContextRAG",
]
```

## Verification

```bash
# Test budget manager
python -c "
from custom_rag.rlm import RLMConfig
from custom_rag.rlm.agent import BudgetManager

config = RLMConfig(max_repl_steps=5, max_file_reads=3)
budget = BudgetManager(config)

print(f'Can step: {budget.can_step()}')  # True
budget.record_step()
budget.record_step()
print(f'Status: {budget.get_status()}')  # 3 remaining
"

# Test filesystem tools (requires prepared corpus)
python -c "
from pathlib import Path
from custom_rag.rlm import RLMConfig
from custom_rag.rlm.agent import BudgetManager, FilesystemTools

# Would need a prepared corpus to test fully
print('FilesystemTools imports OK')
"

# Test REPL
python -c "
from custom_rag.rlm import RLMConfig
from custom_rag.rlm.agent import BudgetManager, SimpleREPL

# Minimal test without full setup
print('SimpleREPL imports OK')
"
```

## Next Task

Proceed to `TASK_5_security.md` to implement ProcessREPL and InjectionGuard for `security_mode="full"`.
