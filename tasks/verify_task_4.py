"""Verification script for Task 4: Agent and REPL."""

import sys
import os
from pathlib import Path
import json
import logging
from unittest.mock import MagicMock

# Add src to path
sys.path.append(str(Path("src").resolve()))

from custom_rag.rlm import RLMAgent, RLMConfig, RLMResponse
from custom_rag.token_tracker import TokenUsage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def setup_mock_filesystem(temp_dir: Path):
    """Create a mock prepared filesystem structure."""
    prepared = temp_dir / "test_docs_prepared"
    (prepared / "_meta").mkdir(parents=True)
    (prepared / "_index" / "topics").mkdir(parents=True)
    (prepared / "_summaries").mkdir(parents=True)
    (prepared / "documents").mkdir(parents=True)

    # Catalog
    catalog = {
        "documents": [
            {"id": "doc_a", "title": "Document A", "path": "documents/doc_a.md", "line_count": 10},
            {"id": "doc_b", "title": "Document B", "path": "documents/doc_b.md", "line_count": 20},
        ]
    }
    (prepared / "_meta" / "catalog.json").write_text(json.dumps(catalog))

    # Topic map
    topics = {"pippo": ["doc_a"], "pluto": ["doc_b"]}
    (prepared / "_index" / "topics" / "_topic_map.json").write_text(json.dumps(topics))

    # Documents
    (prepared / "documents" / "doc_a.md").write_text("This is document A. It mentions pippo.")
    (prepared / "documents" / "doc_b.md").write_text("This is document B. It mentions pluto.")

    # Summaries
    (prepared / "_summaries" / "doc_a_summary.md").write_text("Summary of A: mentions pippo.")
    (prepared / "_summaries" / "doc_b_summary.md").write_text("Summary of B: mentions pluto.")
    
    # Section Index (empty for now)
    (prepared / "_meta" / "section_index.json").write_text(json.dumps({}))

    return prepared

def test_agent_loop():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        prepared_path = setup_mock_filesystem(Path(tmp_dir))
        
        # Set dummy API key for test
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        
        config = RLMConfig(
            orchestrator_model="gpt-4o",
            worker_model="gpt-4o-mini",
            max_repl_steps=5
        )
        token_usage = TokenUsage()
        
        agent = RLMAgent(prepared_path=prepared_path, config=config, token_usage=token_usage)
        
        # Mock LLMClient.chat to return specific code blocks
        # Step 1: List catalog
        # Step 2: Read summary of doc_a
        # Step 3: Final answer
        responses = [
            MagicMock(content="I will start by listing the catalog.\n```python\nprint(fs.get_catalog())\n```"),
            MagicMock(content="I see doc_a. I will read its summary.\n```python\nprint(fs.read_summary('doc_a'))\n```"),
            MagicMock(content="I found the info.\n```python\nfinal_answer = 'Doc A mentions pippo'\nconfidence = 'HIGH'\nsources_used = ['doc_a']\n```")
        ]
        agent.llm_client.chat = MagicMock(side_effect=responses)
        
        # Run query
        result = agent.query("What does Doc A mention?")
        
        # Verify results
        assert "Doc A mentions pippo" in result.answer
        assert "doc_a" in result.sources
        assert result.confidence == "HIGH"
        assert len(result.trace["steps"]) == 3
        assert result.trace["total_steps"] == 3
        
        print("\nSUCCESS: Task 4 Agent loop verification passed")

if __name__ == "__main__":
    try:
        test_agent_loop()
    except Exception as e:
        print(f"\nFAILURE: Verification failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
