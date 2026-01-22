# Task 3: Document Preparation and Manifest

## Goal

Implement document preparation pipeline with manifest-based cache invalidation and the SimpleContextRAG fallback.

## Dependencies

- Task 1 completed (RLMConfig exists)
- Task 2 completed (LLMClient exists for summaries/topics)

## Files to Create

1. `src/custom_rag/rlm/preparation.py` - DocumentProcessor, ManifestManager, SimpleContextRAG

## Context

The preparation pipeline:
1. Loads documents (.txt, .md, .pdf, .docx)
2. Generates LLM summaries and topics (using worker model)
3. Extracts section structure
4. Builds indexes (catalog, topic map, sections)
5. Tracks document hashes for cache invalidation

The manifest enables skipping preparation when documents haven't changed.

## Implementation

### File: `src/custom_rag/rlm/preparation.py`

```python
"""Document preparation and manifest management."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, TYPE_CHECKING

from openai import OpenAI

if TYPE_CHECKING:
    from .rlm_rag import RLMConfig
    from custom_rag.token_tracker import TokenUsage

logger = logging.getLogger(__name__)


# ============================================================================
# Manifest Manager
# ============================================================================

@dataclass
class Manifest:
    """Document manifest for cache invalidation."""
    version: str = "1.0"
    created_at: float = 0.0
    updated_at: float = 0.0
    config_hash: str = ""
    document_count: int = 0
    documents: dict[str, dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.documents is None:
            self.documents = {}


class ManifestManager:
    """Track document state for intelligent cache invalidation.

    The manifest stores hashes of all source documents. When prepare_documents
    is called, it compares current hashes to cached hashes to determine if
    re-preparation is needed.

    Manifest file location: {prepared_path}/manifest.json
    """

    MANIFEST_FILE = "manifest.json"

    def __init__(self, prepared_path: Path | str):
        self.prepared_path = Path(prepared_path)
        self._manifest: Manifest | None = None
        self._load()

    def _load(self) -> None:
        """Load existing manifest if present."""
        path = self.prepared_path / self.MANIFEST_FILE
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._manifest = Manifest(**data)
                logger.debug(f"Loaded manifest: {self._manifest.document_count} docs")
            except Exception as e:
                logger.warning(f"Failed to load manifest: {e}")
                self._manifest = None

    def _save(self) -> None:
        """Save manifest to disk."""
        if self._manifest:
            path = self.prepared_path / self.MANIFEST_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(asdict(self._manifest), indent=2),
                encoding="utf-8"
            )

    def is_valid(self, source_dir: Path) -> bool:
        """Check if current preparation is still valid.

        Returns True if:
        - Manifest exists
        - All source documents unchanged (by hash)
        - No documents added or removed
        """
        if not self._manifest:
            return False

        if not self.prepared_path.exists():
            return False

        # Scan current documents
        current = self._scan(source_dir)

        # Check for added/removed documents
        if set(current.keys()) != set(self._manifest.documents.keys()):
            logger.info("Manifest invalid: documents added or removed")
            return False

        # Check hashes
        for doc_id, info in current.items():
            cached_hash = self._manifest.documents.get(doc_id, {}).get("hash")
            if info["hash"] != cached_hash:
                logger.info(f"Manifest invalid: {doc_id} changed")
                return False

        logger.debug("Manifest valid: all documents unchanged")
        return True

    def update(self, source_dir: Path, config: RLMConfig) -> None:
        """Update manifest after preparation."""
        current = self._scan(source_dir)

        self._manifest = Manifest(
            created_at=self._manifest.created_at if self._manifest else time.time(),
            updated_at=time.time(),
            config_hash=self._hash_config(config),
            document_count=len(current),
            documents=current,
        )
        self._save()
        logger.info(f"Manifest updated: {len(current)} documents")

    def get_info(self) -> dict[str, Any]:
        """Get manifest summary for metrics."""
        if not self._manifest:
            return {"exists": False}
        return {
            "exists": True,
            "document_count": self._manifest.document_count,
            "updated_at": self._manifest.updated_at,
            "config_hash": self._manifest.config_hash,
        }

    def _scan(self, source_dir: Path) -> dict[str, dict[str, Any]]:
        """Scan source directory and compute document hashes."""
        docs = {}
        supported = {".txt", ".md", ".pdf", ".docx"}

        for path in source_dir.iterdir():
            if path.is_file() and path.suffix.lower() in supported:
                try:
                    content = path.read_bytes()
                    docs[path.stem] = {
                        "hash": hashlib.sha256(content).hexdigest()[:16],
                        "size": len(content),
                        "suffix": path.suffix.lower(),
                    }
                except Exception as e:
                    logger.warning(f"Failed to scan {path}: {e}")

        return docs

    def _hash_config(self, config: RLMConfig) -> str:
        """Hash config values that affect preparation output."""
        relevant = {
            "chunk_size": config.chunk_size,
            "chunk_overlap": config.chunk_overlap,
            "use_llm_summaries": config.use_llm_summaries,
            "use_llm_topics": config.use_llm_topics,
            "max_topics_per_doc": config.max_topics_per_doc,
            "worker_model": config.worker_model,
        }
        return hashlib.sha256(
            json.dumps(relevant, sort_keys=True).encode()
        ).hexdigest()[:16]


# ============================================================================
# Document Processor
# ============================================================================

class DocumentProcessor:
    """Prepare documents for RLM filesystem access.

    Creates a prepared filesystem structure:
        {input}_prepared/
        ├── _meta/
        │   ├── catalog.json
        │   └── section_index.json
        ├── _index/
        │   └── topics/
        │       └── _topic_map.json
        ├── _summaries/
        │   └── {doc_id}_summary.md
        ├── documents/
        │   └── {doc_id}.md
        └── manifest.json
    """

    SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}

    def __init__(self, config: RLMConfig):
        self.config = config
        self._client: OpenAI | None = None
        self._tokens = {"prompt": 0, "completion": 0}

    @property
    def client(self) -> OpenAI:
        """Lazy-initialize OpenAI client."""
        if self._client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")
            self._client = OpenAI(api_key=api_key)
        return self._client

    def prepare(self, input_path: str) -> tuple[Path, dict[str, Any]]:
        """Process documents and create prepared filesystem.

        Args:
            input_path: Path to directory containing source documents

        Returns:
            Tuple of (prepared_path, metrics_dict)
        """
        input_dir = Path(input_path)
        if not input_dir.exists():
            raise FileNotFoundError(f"Input path not found: {input_path}")
        if not input_dir.is_dir():
            raise ValueError(f"Input path must be a directory: {input_path}")

        output_dir = input_dir.parent / f"{input_dir.name}_prepared"

        # Create directory structure
        (output_dir / "_meta").mkdir(parents=True, exist_ok=True)
        (output_dir / "_summaries").mkdir(exist_ok=True)
        (output_dir / "_index" / "topics").mkdir(parents=True, exist_ok=True)
        (output_dir / "documents").mkdir(exist_ok=True)

        # Track metrics
        metrics: dict[str, Any] = {
            "documents_processed": 0,
            "documents_failed": 0,
            "total_chars": 0,
            "total_words": 0,
        }

        # Build indexes
        catalog: dict[str, Any] = {"documents": []}
        section_index: dict[str, list[dict]] = {}
        topic_map: dict[str, list[str]] = {}

        # Process each document
        for doc_path in sorted(input_dir.glob("*")):
            if doc_path.is_dir():
                continue
            if doc_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                continue

            doc_id = doc_path.stem
            logger.info(f"Processing: {doc_id}")

            try:
                # Load document content
                content = self._load_document(doc_path)
            except Exception as e:
                logger.warning(f"Failed to load {doc_path}: {e}")
                metrics["documents_failed"] += 1
                continue

            # Save processed document
            doc_output = output_dir / "documents" / f"{doc_id}.md"
            doc_output.write_text(content, encoding="utf-8")

            # Generate summary
            summary = self._generate_summary(content, doc_id)
            summary_output = output_dir / "_summaries" / f"{doc_id}_summary.md"
            summary_output.write_text(summary, encoding="utf-8")

            # Extract sections
            sections = self._extract_sections(content)
            section_index[doc_id] = sections

            # Extract topics
            topics = self._extract_topics(content, doc_id)
            for topic in topics:
                normalized = topic.lower().strip()
                topic_map.setdefault(normalized, []).append(doc_id)

            # Add to catalog
            catalog["documents"].append({
                "id": doc_id,
                "title": doc_id.replace("_", " ").replace("-", " ").title(),
                "path": f"documents/{doc_id}.md",
                "summary_path": f"_summaries/{doc_id}_summary.md",
                "topics": topics,
                "section_count": len(sections),
                "line_count": len(content.split("\n")),
                "word_count": len(content.split()),
                "char_count": len(content),
            })

            metrics["documents_processed"] += 1
            metrics["total_chars"] += len(content)
            metrics["total_words"] += len(content.split())

        # Write indexes
        (output_dir / "_meta" / "catalog.json").write_text(
            json.dumps(catalog, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        (output_dir / "_meta" / "section_index.json").write_text(
            json.dumps(section_index, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        (output_dir / "_index" / "topics" / "_topic_map.json").write_text(
            json.dumps(topic_map, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        # Record token usage
        metrics["preparation_tokens"] = self._tokens.copy()
        metrics["unique_topics"] = len(topic_map)

        logger.info(
            f"Prepared {metrics['documents_processed']} documents "
            f"({metrics['documents_failed']} failed) to {output_dir}"
        )

        return output_dir, metrics

    def _load_document(self, path: Path) -> str:
        """Load document content based on file type."""
        suffix = path.suffix.lower()

        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8")

        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                raise ImportError("pypdf required for PDF support: pip install pypdf")

            reader = PdfReader(path)
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n\n".join(pages)

        elif suffix == ".docx":
            try:
                from docx import Document
            except ImportError:
                raise ImportError("python-docx required: pip install python-docx")

            doc = Document(path)
            return "\n\n".join(para.text for para in doc.paragraphs if para.text)

        else:
            raise ValueError(f"Unsupported file format: {suffix}")

    def _generate_summary(self, content: str, doc_id: str) -> str:
        """Generate document summary using LLM or fallback."""
        if not self.config.use_llm_summaries:
            return self._simple_summary(content)

        try:
            # Truncate for API limits
            max_chars = 8000
            truncated = content[:max_chars] if len(content) > max_chars else content

            response = self.client.chat.completions.create(
                model=self.config.worker_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Create a concise summary (under 300 words) for RAG retrieval. "
                            "Include:\n"
                            "1. Main topic/purpose (1 sentence)\n"
                            "2. Key concepts covered (bullet points)\n"
                            "3. Notable entities mentioned\n"
                            "4. Document type/format\n\n"
                            "Format as markdown."
                        )
                    },
                    {"role": "user", "content": f"Document content:\n\n{truncated}"}
                ],
                temperature=0.0,
                max_tokens=500,
            )

            # Track tokens
            if response.usage:
                self._tokens["prompt"] += response.usage.prompt_tokens
                self._tokens["completion"] += response.usage.completion_tokens

            return response.choices[0].message.content or self._simple_summary(content)

        except Exception as e:
            logger.warning(f"LLM summary failed for {doc_id}: {e}")
            return self._simple_summary(content)

    def _simple_summary(self, content: str) -> str:
        """Fallback summary using headers and preview."""
        lines = content.split("\n")
        headers = [line for line in lines if line.startswith("#")]
        preview = content[:500].strip()
        if len(content) > 500:
            preview += "..."

        summary_parts = []
        if headers:
            summary_parts.append("## Structure\n" + "\n".join(headers[:10]))
        summary_parts.append("## Preview\n" + preview)

        return "\n\n".join(summary_parts)

    def _extract_sections(self, content: str) -> list[dict[str, Any]]:
        """Extract markdown section structure."""
        sections = []
        lines = content.split("\n")
        current: dict[str, Any] | None = None

        for i, line in enumerate(lines):
            if line.startswith("#"):
                # Close previous section
                if current is not None:
                    current["end_line"] = i - 1
                    sections.append(current)

                # Start new section
                level = len(line) - len(line.lstrip("#"))
                title = line.lstrip("# ").strip()
                current = {
                    "title": title,
                    "level": level,
                    "start_line": i,
                }

        # Close final section
        if current is not None:
            current["end_line"] = len(lines) - 1
            sections.append(current)

        return sections

    def _extract_topics(self, content: str, doc_id: str) -> list[str]:
        """Extract topics using LLM or keyword fallback."""
        if not self.config.use_llm_topics:
            return self._keyword_topics(content)

        try:
            response = self.client.chat.completions.create(
                model=self.config.worker_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Extract {self.config.max_topics_per_doc} key topics from this document. "
                            "Return ONLY a JSON array of lowercase strings.\n"
                            'Example: ["machine learning", "neural networks", "data processing"]'
                        )
                    },
                    {"role": "user", "content": content[:4000]}
                ],
                temperature=0.0,
                max_tokens=100,
            )

            # Track tokens
            if response.usage:
                self._tokens["prompt"] += response.usage.prompt_tokens
                self._tokens["completion"] += response.usage.completion_tokens

            result = response.choices[0].message.content or "[]"

            # Clean markdown code blocks if present
            if "```" in result:
                result = re.sub(r"```\w*\n?", "", result).strip()

            topics = json.loads(result)
            return topics[:self.config.max_topics_per_doc]

        except Exception as e:
            logger.warning(f"LLM topics failed for {doc_id}: {e}")
            return self._keyword_topics(content)

    def _keyword_topics(self, content: str) -> list[str]:
        """Fallback topic extraction using keyword frequency."""
        # Find words 4+ characters
        words = re.findall(r"\b[a-z]{4,}\b", content.lower())

        # Remove common stopwords
        stopwords = {
            "this", "that", "with", "from", "have", "will", "been", "were",
            "they", "their", "about", "which", "would", "there", "could",
            "other", "into", "more", "some", "such", "than", "then", "these",
            "what", "when", "where", "your", "also", "just", "only", "very",
        }
        words = [w for w in words if w not in stopwords]

        # Return most common
        counter = Counter(words)
        return [word for word, _ in counter.most_common(self.config.max_topics_per_doc)]


# ============================================================================
# Simple Context RAG (Fallback)
# ============================================================================

class SimpleContextRAG:
    """Simple RAG for small document sets.

    Bypasses the REPL overhead by loading all documents into context directly.
    Used when corpus size <= small_corpus_threshold.
    """

    def __init__(
        self,
        prepared_path: Path | str,
        token_usage: TokenUsage,
    ):
        self.prepared_path = Path(prepared_path)
        self.token_usage = token_usage
        self._client: OpenAI | None = None
        self.documents: list[dict[str, Any]] = []
        self._load_documents()

    @property
    def client(self) -> OpenAI:
        """Lazy-initialize OpenAI client."""
        if self._client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")
            self._client = OpenAI(api_key=api_key)
        return self._client

    def _load_documents(self) -> None:
        """Load all documents into memory."""
        catalog_path = self.prepared_path / "_meta" / "catalog.json"

        if not catalog_path.exists():
            logger.warning(f"Catalog not found: {catalog_path}")
            return

        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

        for doc in catalog.get("documents", []):
            doc_path = self.prepared_path / doc["path"]
            if doc_path.exists():
                self.documents.append({
                    "id": doc["id"],
                    "title": doc.get("title", doc["id"]),
                    "content": doc_path.read_text(encoding="utf-8"),
                    "topics": doc.get("topics", []),
                })

        logger.info(f"SimpleContextRAG loaded {len(self.documents)} documents")

    def query(self, question: str, top_k: int = 5) -> dict[str, Any]:
        """Answer question using all loaded documents.

        Args:
            question: The question to answer
            top_k: Max documents to include in context

        Returns:
            Dict with answer, context, and metadata
        """
        start = time.time()

        # Use first top_k documents (for small corpora, usually all)
        docs_to_use = self.documents[:top_k]

        # Build context
        context_parts = []
        for doc in docs_to_use:
            # Truncate very long documents
            content = doc["content"]
            if len(content) > 3000:
                content = content[:3000] + "\n\n[... truncated ...]"

            context_parts.append(
                f"[{doc['id']}] {doc['title']}\n{content}"
            )

        context = "\n\n---\n\n".join(context_parts)

        # Generate answer
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer the question based on the provided documents. "
                        "Cite sources by their [doc_id]. "
                        "If the answer cannot be found, say so."
                    )
                },
                {
                    "role": "user",
                    "content": f"Documents:\n{context}\n\nQuestion: {question}"
                }
            ],
            temperature=0.0,
        )

        # Track tokens
        if response.usage:
            self.token_usage.add_prompt_tokens(response.usage.prompt_tokens)
            self.token_usage.add_completion_tokens(response.usage.completion_tokens)

        return {
            "answer": response.choices[0].message.content or "",
            "context": [doc["content"][:500] for doc in docs_to_use],
            "metadata": {
                "mode": "simple_context",
                "docs_used": len(docs_to_use),
                "retrieval_time": 0.0,
                "generation_time": time.time() - start,
                "sources": [doc["id"] for doc in docs_to_use],
                "token_usage": self.token_usage.to_dict(),
            },
        }
```

## Update `__init__.py`

```python
"""RLM Filesystem RAG - Recursive Language Model approach for large corpora."""

from .rlm_rag import RLMFilesystemRAG, RLMConfig, StreamEvent
from .llm_client import LLMClient, CircuitBreaker, ChatResponse
from .preparation import DocumentProcessor, ManifestManager, SimpleContextRAG

__all__ = [
    "RLMFilesystemRAG",
    "RLMConfig",
    "StreamEvent",
    "LLMClient",
    "CircuitBreaker",
    "ChatResponse",
    "DocumentProcessor",
    "ManifestManager",
    "SimpleContextRAG",
]
```

## Verification

```bash
# Test document processor (create test docs first)
python -c "
import tempfile
from pathlib import Path
from custom_rag.rlm import RLMConfig
from custom_rag.rlm.preparation import DocumentProcessor, ManifestManager

# Create temp directory with test docs
with tempfile.TemporaryDirectory() as tmpdir:
    docs_dir = Path(tmpdir) / 'docs'
    docs_dir.mkdir()

    # Create test documents
    (docs_dir / 'test1.md').write_text('# Test Document 1\n\nThis is about machine learning.')
    (docs_dir / 'test2.md').write_text('# Test Document 2\n\nThis is about data science.')

    # Process
    config = RLMConfig(use_llm_summaries=False, use_llm_topics=False)
    processor = DocumentProcessor(config)
    prepared_path, metrics = processor.prepare(str(docs_dir))

    print(f'Prepared to: {prepared_path}')
    print(f'Metrics: {metrics}')

    # Check manifest
    manifest = ManifestManager(prepared_path)
    print(f'Manifest valid: {manifest.is_valid(docs_dir)}')
    print(f'Manifest info: {manifest.get_info()}')
"
```

## Next Task

Proceed to `TASK_4_agent_repl.md` to implement the RLM agent with REPL and filesystem tools.
