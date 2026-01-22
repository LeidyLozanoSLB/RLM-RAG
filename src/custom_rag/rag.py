"""Custom RAG implementation template.

This is a working example implementation that you can use as a starting point.
It demonstrates a simple vector-based RAG using OpenAI embeddings and a basic
in-memory vector store.

Replace this with your own implementation!
"""

import hashlib
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from openai import OpenAI

from custom_rag.base_rag import BaseRAG, RAGConfig
from custom_rag.provider_interfaces import (
    GeneratedAnswer,
    RetrievalTrace,
    RetrievedChunk,
    RetrievedContext,
)

# Load environment variables
load_dotenv()


class CustomRAG(BaseRAG):
    """Example custom RAG implementation using OpenAI.

    This is a simple in-memory vector RAG that demonstrates the interface.
    Replace this with your own retrieval strategy!

    Features:
        - Document chunking with LangChain
        - OpenAI embeddings (text-embedding-3-small)
        - In-memory vector storage with cosine similarity
        - OpenAI chat completion for generation
    """

    def __init__(
        self,
        config: RAGConfig | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        embedding_model: str = "text-embedding-3-small",
        llm_model: str = "gpt-4o-mini",
    ) -> None:
        """Initialize the Custom RAG.

        Args:
            config: Optional RAGConfig for configuration
            chunk_size: Size of text chunks for indexing
            chunk_overlap: Overlap between chunks
            embedding_model: OpenAI embedding model to use
            llm_model: OpenAI LLM model for generation
        """
        super().__init__(name="Custom RAG", config=config)

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.embedding_model = embedding_model
        self.llm_model = llm_model

        # Initialize OpenAI client
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # In-memory vector store: list of (chunk_text, embedding, metadata)
        self._index: list[tuple[str, list[float], dict[str, Any]]] = []

        # Metrics
        self._total_chunks = 0
        self._total_documents = 0
        self._last_retrieval_time = 0.0

    def prepare_documents(self, documents_path: str) -> None:
        """Index documents from the given directory.

        Args:
            documents_path: Path to directory containing documents
        """
        documents_dir = Path(documents_path)
        if not documents_dir.exists():
            raise FileNotFoundError(f"Documents directory not found: {documents_path}")

        # Clear existing index
        self._index = []
        self._total_chunks = 0
        self._total_documents = 0

        # Initialize text splitter
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
        )

        # Find all documents
        supported_extensions = {".txt", ".md", ".pdf", ".docx"}
        documents = [
            f
            for f in documents_dir.iterdir()
            if f.is_file() and f.suffix.lower() in supported_extensions
        ]

        total_docs = len(documents)
        print(f"Found {total_docs} documents to index")

        for i, doc_path in enumerate(documents):
            self._report_progress(i + 1, total_docs)

            # Load document content
            content = self._load_document(doc_path)
            if not content:
                continue

            # Split into chunks
            chunks = text_splitter.split_text(content)

            # Generate embeddings and store
            for j, chunk in enumerate(chunks):
                embedding = self._get_embedding(chunk)
                metadata = {
                    "source": doc_path.name,
                    "chunk_index": j,
                    "chunk_id": hashlib.md5(chunk.encode()).hexdigest()[:8],
                }
                self._index.append((chunk, embedding, metadata))

            self._total_documents += 1
            self._total_chunks += len(chunks)

        print(f"Indexed {self._total_chunks} chunks from {self._total_documents} documents")

    def _load_document(self, doc_path: Path) -> str:
        """Load document content based on file type."""
        suffix = doc_path.suffix.lower()

        if suffix in {".txt", ".md"}:
            return doc_path.read_text(encoding="utf-8")

        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(doc_path))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except ImportError:
                print(f"Warning: pypdf not installed, skipping {doc_path.name}")
                return ""

        elif suffix == ".docx":
            try:
                from docx import Document

                doc = Document(str(doc_path))
                return "\n".join(para.text for para in doc.paragraphs)
            except ImportError:
                print(f"Warning: python-docx not installed, skipping {doc_path.name}")
                return ""

        return ""

    def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding for text using OpenAI."""
        response = self.client.embeddings.create(model=self.embedding_model, input=text)

        # Track token usage
        self._token_usage.add_embedding_tokens(response.usage.total_tokens)

        return response.data[0].embedding

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        return dot_product / (norm_a * norm_b) if norm_a and norm_b else 0.0

    def retrieve(self, question: str, top_k: int = 5) -> RetrievedContext:
        """Retrieve relevant context for a question.

        Args:
            question: The question to retrieve context for
            top_k: Number of chunks to retrieve

        Returns:
            RetrievedContext with chunks and trace
        """
        start_time = time.time()

        # Create trace
        trace = RetrievalTrace(strategy="vector")

        # Embed the question
        embed_start = time.time()
        query_embedding = self._get_embedding(question)
        embed_time = time.time() - embed_start

        trace.add_step(
            step_type="embedding",
            input_data={"query": question, "model": self.embedding_model},
            duration_ms=embed_time * 1000,
        )

        # Search for similar chunks
        search_start = time.time()
        similarities = []
        for chunk, embedding, metadata in self._index:
            score = self._cosine_similarity(query_embedding, embedding)
            similarities.append((chunk, score, metadata))

        # Sort by similarity and take top_k
        similarities.sort(key=lambda x: x[1], reverse=True)
        top_results = similarities[:top_k]
        search_time = time.time() - search_start

        # Build chunk details
        chunk_details = []
        for rank, (chunk, score, metadata) in enumerate(top_results):
            chunk_details.append(
                RetrievedChunk(
                    content=chunk,
                    document_id=metadata["source"],
                    chunk_id=metadata["chunk_id"],
                    score=score,
                    rank=rank,
                    source=metadata["source"],
                    metadata=metadata,
                )
            )

        trace.add_step(
            step_type="vector_search",
            input_data={"top_k": top_k, "index_size": len(self._index)},
            output_refs=[c.chunk_id for c in chunk_details],
            duration_ms=search_time * 1000,
            metadata={"method": "cosine_similarity"},
        )

        trace.retrieved_chunks = chunk_details
        retrieval_time = time.time() - start_time
        trace.total_duration_ms = retrieval_time * 1000

        self._last_retrieval_time = retrieval_time

        return RetrievedContext(
            chunks=[c.content for c in chunk_details],
            chunk_details=chunk_details,
            trace=trace,
            retrieval_time=retrieval_time,
        )

    def generate(self, question: str, context: RetrievedContext) -> GeneratedAnswer:
        """Generate an answer from the retrieved context.

        Args:
            question: The question to answer
            context: Previously retrieved context

        Returns:
            GeneratedAnswer with text and token usage
        """
        start_time = time.time()

        # Build prompt
        context_text = "\n\n---\n\n".join(context.chunks)
        prompt = f"""Based on the following context, answer the question.
If the answer cannot be found in the context, say "I cannot find the answer in the provided context."

Context:
{context_text}

Question: {question}

Answer:"""

        # Generate answer
        response = self.client.chat.completions.create(
            model=self.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that answers questions based on the provided context.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )

        answer = response.choices[0].message.content or ""
        generation_time = time.time() - start_time

        # Track token usage
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        completion_tokens = response.usage.completion_tokens if response.usage else 0
        self._token_usage.add_prompt_tokens(prompt_tokens)
        self._token_usage.add_completion_tokens(completion_tokens)

        return GeneratedAnswer(
            text=answer,
            generation_time=generation_time,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def query(self, question: str, top_k: int = 5) -> dict[str, Any]:
        """Execute full RAG pipeline.

        Args:
            question: The question to answer
            top_k: Number of chunks to retrieve

        Returns:
            Dictionary with answer, context, and metadata
        """
        self.reset_token_usage()

        # Retrieve
        context = self.retrieve(question, top_k)

        # Generate
        answer = self.generate(question, context)

        # Get source documents
        sources = list({c.source for c in context.chunk_details})

        return {
            "answer": answer.text,
            "context": context.chunks,
            "metadata": {
                "retrieval_time": context.retrieval_time,
                "generation_time": answer.generation_time,
                "sources": sources,
                "token_usage": self._token_usage.to_dict(),
            },
        }

    def get_metrics(self) -> dict[str, Any]:
        """Return performance metrics."""
        return {
            "total_documents": self._total_documents,
            "total_chunks": self._total_chunks,
            "index_size": len(self._index),
            "last_retrieval_time": self._last_retrieval_time,
            "embedding_model": self.embedding_model,
            "llm_model": self.llm_model,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }

    def _get_strategy_name(self) -> str:
        """Return strategy name for tracing."""
        return "vector"

    def close(self) -> None:
        """Clean up resources."""
        self._index = []
