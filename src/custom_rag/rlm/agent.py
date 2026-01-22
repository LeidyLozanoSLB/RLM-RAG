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
            # Note: ProcessREPL will be implemented in Task 5
            try:
                from .security import ProcessREPL
                self.repl = ProcessREPL(
                    tools=self.tools,
                    llm_client=self.llm_client,
                    budget=self.budget,
                    timeout=config.repl_timeout,
                )
            except ImportError:
                logger.warning("ProcessREPL not found, falling back to SimpleREPL")
                self.repl = SimpleREPL(
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

        # Collect files accessed
        trace["files_accessed"] = list(set(self.tools.get_accessed_files()))
        trace["total_steps"] = len(trace["steps"])

        return RLMResponse(
            answer=str(final_answer),
            context=messages_to_context(messages),
            sources=sources_used,
            confidence=str(confidence),
            retrieval_time=time.time() - start_time,
            generation_time=0.0,  # Included in retrieval_time for RLM
            trace=trace,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get agent performance and budget statistics."""
        from dataclasses import asdict
        return {
            "budget": asdict(self.budget.get_status()),
            "repl_type": type(self.repl).__name__,
        }

    def _extract_code(self, text: str) -> list[str]:
        """Extract Python code blocks from text."""
        pattern = r"```python\n(.*?)\n```"
        return re.findall(pattern, text, re.DOTALL)

    def close(self) -> None:
        """Clean up REPL resources."""
        if hasattr(self.repl, "close"):
            self.repl.close()


def messages_to_context(messages: list[dict[str, str]]) -> list[str]:
    """Convert conversation history to context list."""
    context = []
    for msg in messages:
        if msg["role"] == "system":
            continue
        context.append(f"{msg['role'].upper()}: {msg['content']}")
    return context
