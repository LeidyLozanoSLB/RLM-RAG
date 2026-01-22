#!/usr/bin/env python3
"""Manual test script for RLM Filesystem RAG.

This script demonstrates:
1. Initializing RLMFilesystemRAG with custom configuration.
2. Preparing (indexing) a directory of documents.
3. Querying the RAG (routing to either SimpleMode or AgentMode).
4. Inspecting metrics and token usage.

Usage:
    uv run python examples/rlm_manual_test.py
"""

import os
import sys
import logging
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
from custom_rag.rlm import RLMFilesystemRAG, RLMConfig

# Load environment variables (OPENAI_API_KEY)
load_dotenv()

def setup_test_docs(docs_dir: Path):
    """Create a few sample documents if they don't exist."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    
    (docs_dir / "rlm_concept.md").write_text("""# Recursive Language Models
Recursive Language Models (RLMs) are a new class of models that can decompose 
complex tasks into smaller sub-tasks, often by executing code or calling 
sub-instances of themselves.

In the context of RAG, an RLM agent can explore a filesystem of prepared 
documents by writing Python code to search, read, and summarize information 
recursively.
""")

    (docs_dir / "project_status.txt").write_text("""Project: RLM-RAG Integration
Status: Task 7 Completed
Features:
- Subprocess isolation (Security Mode: Full)
- Manifest-based caching
- Multi-tier model support (Orchestrator/Worker)
- Comprehensive unit tests
""")
    print(f"✅ Created test documents in {docs_dir}")

def main():
    # 1. Environment Check
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY not set. Please add it to your .env file.")
        return

    # 2. Configuration
    # You can change security_mode to "full" to test subprocess isolation
    config = RLMConfig(
        security_mode="lite", 
        orchestrator_model="gpt-5-mini",
        worker_model="gpt-5-nano",
        small_corpus_threshold=1, # 2 docs > 1, so it uses Agent Mode
        log_level="INFO"
    )

    # 3. Initialize RAG
    print("--- Initializing RLM Filesystem RAG ---")
    rag = RLMFilesystemRAG(rlm_config=config)

    try:
        # 4. Prepare Documents
        docs_dir = Path("data/manual_test")
        setup_test_docs(docs_dir)
        
        print(f"\n--- Preparing Documents from {docs_dir} ---")
        prep_results = rag.prepare_documents(str(docs_dir), force=True)
        print(f"Preparation Mode: {prep_results['mode']}")
        print(f"Prepared Path: {prep_results['prepared_path']}")

        # 5. Run a Query
        question = "What are Recursive Language Models and what is the current project status?"
        print(f"\n--- Querying: {question} ---")
        
        # Use query_stream for real-time feedback (optional, we use query here for simplicity)
        result = rag.query(question)
        
        print(f"\n🤖 Answer:\n{result['answer']}")
        print(f"\n📄 Sources: {', '.join(result['metadata']['sources'])}")
        print(f"⏱️ Retrieval Time: {result['metadata']['retrieval_time']:.2f}s")
        
        # 6. Show Metrics
        print("\n--- System Metrics ---")
        metrics = rag.get_metrics()
        print(f"Total Documents: {metrics['total_documents']}")
        print(f"Security Mode: {metrics['security_mode']}")
        
        token_usage = rag.get_token_usage()
        print(f"Total Tokens Used: {token_usage['total_tokens']}")

    finally:
        # 7. Cleanup (Crucial for Agent Mode)
        rag.close()
        print("\n--- Cleanup Complete ---")

if __name__ == "__main__":
    main()
