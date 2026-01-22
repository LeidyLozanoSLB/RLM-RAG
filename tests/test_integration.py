"""Integration tests for RLM RAG."""

import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from custom_rag.rlm import RLMFilesystemRAG, RLMConfig


class TestRLMFilesystemRAGIntegration:
    """Integration tests for the full RAG pipeline."""

    @pytest.fixture
    def docs_dir(self):
        """Create test documents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            docs = Path(tmpdir) / "docs"
            docs.mkdir()

            (docs / "ml.md").write_text("""# Machine Learning

Machine learning is a subset of artificial intelligence.

## Types
- Supervised learning
- Unsupervised learning
- Reinforcement learning

## Applications
- Image recognition
- Natural language processing
""")

            (docs / "dl.md").write_text("""# Deep Learning

Deep learning uses neural networks with many layers.

## Architecture
Neural networks consist of:
- Input layer
- Hidden layers
- Output layer
""")

            yield docs

    def test_prepare_documents(self, docs_dir):
        """Test document preparation without API calls."""
        config = RLMConfig(
            use_llm_summaries=False,
            use_llm_topics=False,
        )

        rag = RLMFilesystemRAG(rlm_config=config)
        metrics = rag.prepare_documents(str(docs_dir))

        assert "prepared_path" in metrics
        assert metrics["mode"] in ["simple_context", "rlm_agent"]

        # Check prepared directory exists
        prepared_path = Path(metrics["prepared_path"])
        assert prepared_path.exists()
        assert (prepared_path / "_meta" / "catalog.json").exists()

        rag.close()

    def test_small_corpus_uses_simple_mode(self, docs_dir):
        """Test small corpus routes to SimpleContextRAG."""
        config = RLMConfig(
            use_llm_summaries=False,
            use_llm_topics=False,
            small_corpus_threshold=10,  # 2 docs < 10
        )

        rag = RLMFilesystemRAG(rlm_config=config)
        rag.prepare_documents(str(docs_dir))

        assert rag._use_simple_mode is True
        assert rag._simple_rag is not None

        rag.close()

    def test_large_corpus_uses_agent_mode(self, docs_dir):
        """Test large corpus routes to RLMAgent."""
        config = RLMConfig(
            use_llm_summaries=False,
            use_llm_topics=False,
            small_corpus_threshold=1,  # 2 docs > 1
        )

        # UsingSk-dummy as LLMClient checks for key
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-dummy"}):
            rag = RLMFilesystemRAG(rlm_config=config)
            rag.prepare_documents(str(docs_dir))

            assert rag._use_simple_mode is False
            assert rag._agent is not None

            rag.close()

    def test_get_metrics(self, docs_dir):
        """Test metrics retrieval."""
        config = RLMConfig(
            use_llm_summaries=False,
            use_llm_topics=False,
        )

        rag = RLMFilesystemRAG(rlm_config=config)
        rag.prepare_documents(str(docs_dir))

        metrics = rag.get_metrics()

        assert metrics["name"] == "RLM Filesystem RAG"
        assert metrics["total_documents"] == 2
        assert "security_mode" in metrics

        rag.close()

    def test_manifest_skips_unchanged(self, docs_dir):
        """Test manifest-based caching skips unchanged docs."""
        config = RLMConfig(
            use_llm_summaries=False,
            use_llm_topics=False,
        )

        # First preparation
        rag1 = RLMFilesystemRAG(rlm_config=config)
        metrics1 = rag1.prepare_documents(str(docs_dir))
        rag1.close()

        # Second preparation should skip
        rag2 = RLMFilesystemRAG(rlm_config=config)
        metrics2 = rag2.prepare_documents(str(docs_dir))
        
        # Manifest should be valid
        assert rag2._manifest.is_valid(docs_dir) is True
        rag2.close()

    def test_context_manager(self, docs_dir):
        """Test context manager usage."""
        config = RLMConfig(
            use_llm_summaries=False,
            use_llm_topics=False,
        )

        with RLMFilesystemRAG(rlm_config=config) as rag:
            rag.prepare_documents(str(docs_dir))
            assert rag._prepared_path is not None

        # After context exit, agent should be None (closed)
        assert rag._agent is None

    def test_query_without_prepare_raises(self):
        """Test query before prepare raises error."""
        rag = RLMFilesystemRAG()

        with pytest.raises(RuntimeError, match="not prepared"):
            rag.query("test question")

    def test_force_reprepare(self, docs_dir):
        """Test force flag triggers re-preparation."""
        config = RLMConfig(
            use_llm_summaries=False,
            use_llm_topics=False,
        )

        # First prep
        rag = RLMFilesystemRAG(rlm_config=config)
        rag.prepare_documents(str(docs_dir))

        # Force re-prep
        metrics = rag.prepare_documents(str(docs_dir), force=True)

        assert "prepared_path" in metrics

        rag.close()
