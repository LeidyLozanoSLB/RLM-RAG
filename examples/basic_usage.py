#!/usr/bin/env python3
"""Basic usage example for the Custom RAG implementation.

This script demonstrates:
1. Initializing the RAG
2. Preparing documents (indexing)
3. Running queries
4. Using separate retrieve/generate methods
5. Accessing metrics and traces

Usage:
    # Make sure you have set OPENAI_API_KEY in .env
    uv run python examples/basic_usage.py
"""

import os
import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

from custom_rag import CustomRAG, RAGConfig

# Load environment variables
load_dotenv()


def create_sample_documents(docs_dir: Path) -> None:
    """Create sample documents for testing."""
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Sample document 1
    (docs_dir / "countries.txt").write_text(
        """Countries and Capitals

France is a country in Western Europe. Its capital is Paris, which is known
for the Eiffel Tower, the Louvre Museum, and the Champs-Élysées. Paris is
often called the "City of Light" and is one of the most visited cities in
the world.

Germany is the largest economy in Europe. Its capital is Berlin, which was
divided during the Cold War. The Berlin Wall fell in 1989, reuniting East
and West Germany. Today, Berlin is known for its vibrant culture and history.

Italy is known for its rich history, art, and cuisine. The capital is Rome,
which was the center of the Roman Empire. Rome contains many ancient ruins,
including the Colosseum and the Roman Forum.
"""
    )

    # Sample document 2
    (docs_dir / "technology.txt").write_text(
        """Modern Technology Overview

Artificial Intelligence (AI) has transformed many industries. Machine learning,
a subset of AI, allows computers to learn from data without being explicitly
programmed. Deep learning uses neural networks with many layers.

Large Language Models (LLMs) like GPT are trained on massive amounts of text
data. They can generate human-like text, answer questions, and assist with
various tasks. RAG (Retrieval-Augmented Generation) combines LLMs with
information retrieval to provide more accurate and up-to-date responses.

Vector databases store embeddings - numerical representations of text. They
enable semantic search, finding documents by meaning rather than just keywords.
Popular vector databases include Pinecone, Weaviate, and ChromaDB.
"""
    )

    print(f"Created sample documents in {docs_dir}")


def main():
    """Run the basic usage example."""
    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set in environment")
        print("Please copy .env.example to .env and add your API key")
        sys.exit(1)

    # Create sample documents
    docs_dir = Path(__file__).parent.parent / "data" / "raw"
    if not docs_dir.exists() or not list(docs_dir.glob("*.txt")):
        create_sample_documents(docs_dir)

    # Initialize RAG
    print("\n" + "=" * 60)
    print("Initializing Custom RAG")
    print("=" * 60)

    config = RAGConfig(
        name="Example RAG",
        parameters={"chunk_size": 500},
    )

    rag = CustomRAG(
        config=config,
        chunk_size=500,
        chunk_overlap=100,
    )

    print(f"RAG Name: {rag.name}")
    print(f"Chunk Size: {rag.chunk_size}")

    # Prepare documents (indexing)
    print("\n" + "=" * 60)
    print("Indexing Documents")
    print("=" * 60)

    rag.prepare_documents(str(docs_dir))

    metrics = rag.get_metrics()
    print(f"\nIndexing complete!")
    print(f"  - Documents: {metrics['total_documents']}")
    print(f"  - Chunks: {metrics['total_chunks']}")

    # Run queries
    print("\n" + "=" * 60)
    print("Running Queries")
    print("=" * 60)

    questions = [
        "What is the capital of France?",
        "What is RAG and how does it work?",
        "Tell me about the Berlin Wall.",
    ]

    for question in questions:
        print(f"\n📝 Question: {question}")

        result = rag.query(question, top_k=3)

        print(f"💬 Answer: {result['answer'][:200]}...")
        print(f"📊 Retrieval Time: {result['metadata']['retrieval_time']:.3f}s")
        print(f"📊 Generation Time: {result['metadata']['generation_time']:.3f}s")
        print(f"📄 Sources: {', '.join(result['metadata']['sources'])}")

    # Demonstrate separate retrieve/generate
    print("\n" + "=" * 60)
    print("Separate Retrieve and Generate")
    print("=" * 60)

    question = "What are vector databases used for?"
    print(f"\n📝 Question: {question}")

    # Step 1: Retrieve
    print("\n🔍 Step 1: Retrieving context...")
    context = rag.retrieve(question, top_k=3)

    print(f"  - Retrieved {len(context.chunks)} chunks")
    print(f"  - Strategy: {context.trace.strategy}")
    print(f"  - Trace steps: {len(context.trace.steps)}")

    for step in context.trace.steps:
        print(f"    • {step['type']}: {step['duration_ms']:.1f}ms")

    # Step 2: Generate
    print("\n✨ Step 2: Generating answer...")
    answer = rag.generate(question, context)

    print(f"  - Answer: {answer.text[:150]}...")
    print(f"  - Generation time: {answer.generation_time:.3f}s")
    print(f"  - Tokens: {answer.prompt_tokens} prompt, {answer.completion_tokens} completion")

    # Show final metrics
    print("\n" + "=" * 60)
    print("Final Metrics")
    print("=" * 60)

    final_metrics = rag.get_metrics()
    for key, value in final_metrics.items():
        print(f"  {key}: {value}")

    # Token usage
    print("\n📊 Total Token Usage:")
    token_usage = rag.get_token_usage()
    print(f"  - Prompt tokens: {token_usage.prompt_tokens}")
    print(f"  - Completion tokens: {token_usage.completion_tokens}")
    print(f"  - Embedding tokens: {token_usage.embedding_tokens}")
    print(f"  - Total tokens: {token_usage.total_tokens}")

    # Cleanup
    rag.close()
    print("\n✅ Example complete!")


if __name__ == "__main__":
    main()
