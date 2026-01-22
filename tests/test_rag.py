"""Unit tests for the Custom RAG implementation."""

import pytest
from pathlib import Path

from custom_rag import CustomRAG, RAGConfig

if CustomRAG is None:
    pytest.skip("CustomRAG not available (missing dependencies)", allow_module_level=True)


class TestCustomRAG:
    """Test suite for CustomRAG."""

    def test_initialization(self):
        """Test that RAG initializes correctly."""
        rag = CustomRAG()
        assert rag.name == "Custom RAG"
        assert rag.chunk_size == 1000
        assert rag.chunk_overlap == 200

    def test_initialization_with_config(self):
        """Test initialization with custom config."""
        config = RAGConfig(
            name="Test RAG",
            parameters={"custom_param": "value"},
        )
        rag = CustomRAG(config=config, chunk_size=500)
        assert rag.config.name == "Test RAG"
        assert rag.chunk_size == 500

    def test_get_metrics_empty(self):
        """Test metrics when index is empty."""
        rag = CustomRAG()
        metrics = rag.get_metrics()

        assert metrics["total_documents"] == 0
        assert metrics["total_chunks"] == 0
        assert metrics["index_size"] == 0

    def test_close(self):
        """Test that close clears the index."""
        rag = CustomRAG()
        # Manually add something to index
        rag._index = [("test", [0.1, 0.2], {"source": "test.txt"})]
        assert len(rag._index) == 1

        rag.close()
        assert len(rag._index) == 0


class TestCustomRAGWithDocuments:
    """Tests that require document preparation."""

    @pytest.fixture
    def sample_docs(self, tmp_path):
        """Create sample documents for testing."""
        doc1 = tmp_path / "doc1.txt"
        doc1.write_text("Paris is the capital of France. It is known for the Eiffel Tower.")

        doc2 = tmp_path / "doc2.txt"
        doc2.write_text("Berlin is the capital of Germany. It has a famous wall.")

        return tmp_path

    @pytest.mark.skipif(
        not pytest.importorskip("openai", reason="OpenAI not installed"),
        reason="OpenAI API key required"
    )
    def test_prepare_documents(self, sample_docs):
        """Test document preparation and indexing."""
        import os
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

        rag = CustomRAG()
        rag.prepare_documents(str(sample_docs))

        metrics = rag.get_metrics()
        assert metrics["total_documents"] == 2
        assert metrics["total_chunks"] >= 2

    @pytest.mark.skipif(
        not pytest.importorskip("openai", reason="OpenAI not installed"),
        reason="OpenAI API key required"
    )
    def test_query(self, sample_docs):
        """Test the full query pipeline."""
        import os
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

        rag = CustomRAG()
        rag.prepare_documents(str(sample_docs))

        result = rag.query("What is the capital of France?")

        assert "answer" in result
        assert "context" in result
        assert "metadata" in result
        assert len(result["context"]) > 0
        # The answer should mention Paris
        assert "Paris" in result["answer"] or "capital" in result["answer"].lower()

    @pytest.mark.skipif(
        not pytest.importorskip("openai", reason="OpenAI not installed"),
        reason="OpenAI API key required"
    )
    def test_retrieve_and_generate_separately(self, sample_docs):
        """Test separate retrieval and generation."""
        import os
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set")

        rag = CustomRAG()
        rag.prepare_documents(str(sample_docs))

        # Test retrieval
        context = rag.retrieve("What is the capital of France?")
        assert len(context.chunks) > 0
        assert context.trace.strategy == "vector"
        assert len(context.trace.steps) >= 2  # embedding + search

        # Test generation
        answer = rag.generate("What is the capital of France?", context)
        assert answer.text
        assert answer.generation_time > 0


class TestRAGConfig:
    """Test RAGConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = RAGConfig(name="Test")
        assert config.llm_provider == "openai"
        assert config.llm_model == "gpt-4o-mini"
        assert config.embedding_model == "text-embedding-3-small"

    def test_to_dict(self):
        """Test serialization to dictionary."""
        config = RAGConfig(name="Test", parameters={"key": "value"})
        data = config.to_dict()

        assert data["name"] == "Test"
        assert data["parameters"] == {"key": "value"}

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "name": "Test",
            "llm_model": "gpt-4",
            "parameters": {"key": "value"},
        }
        config = RAGConfig.from_dict(data)

        assert config.name == "Test"
        assert config.llm_model == "gpt-4"
        assert config.parameters == {"key": "value"}
