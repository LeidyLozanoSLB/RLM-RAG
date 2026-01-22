"""Tests for document preparation."""

import json
import tempfile
from pathlib import Path
import pytest

from custom_rag.rlm import RLMConfig
from custom_rag.rlm.preparation import (
    DocumentProcessor,
    ManifestManager,
)


class TestManifestManager:
    """Test manifest management."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source"
            prepared = Path(tmpdir) / "source_prepared"
            source.mkdir()
            prepared.mkdir()
            yield source, prepared

    def test_no_manifest_invalid(self, temp_dirs):
        """Test is_valid returns False when no manifest."""
        source, prepared = temp_dirs
        manager = ManifestManager(prepared)
        assert manager.is_valid(source) is False

    def test_valid_manifest(self, temp_dirs):
        """Test is_valid with unchanged documents."""
        source, prepared = temp_dirs

        # Create test document
        (source / "test.md").write_text("content")

        # Create and update manifest
        config = RLMConfig()
        manager = ManifestManager(prepared)
        manager.update(source, config)

        # Check validity
        assert manager.is_valid(source) is True

    def test_invalid_after_change(self, temp_dirs):
        """Test is_valid returns False after document change."""
        source, prepared = temp_dirs

        # Create and prepare
        (source / "test.md").write_text("original content")
        config = RLMConfig()
        manager = ManifestManager(prepared)
        manager.update(source, config)

        # Modify document
        (source / "test.md").write_text("modified content")

        # Check validity
        assert manager.is_valid(source) is False

    def test_invalid_after_add(self, temp_dirs):
        """Test is_valid returns False after adding document."""
        source, prepared = temp_dirs

        # Create and prepare
        (source / "test1.md").write_text("content1")
        config = RLMConfig()
        manager = ManifestManager(prepared)
        manager.update(source, config)

        # Add new document
        (source / "test2.md").write_text("content2")

        # Check validity
        assert manager.is_valid(source) is False

    def test_get_info(self, temp_dirs):
        """Test get_info returns manifest summary."""
        source, prepared = temp_dirs

        (source / "test.md").write_text("content")
        config = RLMConfig()
        manager = ManifestManager(prepared)
        manager.update(source, config)

        info = manager.get_info()
        assert info["exists"] is True
        assert info["document_count"] == 1


class TestDocumentProcessor:
    """Test document processing."""

    @pytest.fixture
    def source_dir(self):
        """Create source directory with test documents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "docs"
            source.mkdir()

            # Create test documents
            (source / "doc1.md").write_text(
                "# Document 1\n\nThis is about machine learning.\n\n## Section\nContent here."
            )
            (source / "doc2.txt").write_text(
                "Plain text document about data science."
            )

            yield source

    def test_prepare_creates_structure(self, source_dir):
        """Test prepare creates expected directory structure."""
        config = RLMConfig(use_llm_summaries=False, use_llm_topics=False)
        processor = DocumentProcessor(config)

        prepared_path, metrics = processor.prepare(str(source_dir))
        prepared = Path(prepared_path)

        assert (prepared / "_meta").exists()
        assert (prepared / "_meta" / "catalog.json").exists()
        assert (prepared / "_summaries").exists()
        assert (prepared / "documents").exists()
        assert (prepared / "_index" / "topics").exists()

    def test_prepare_metrics(self, source_dir):
        """Test prepare returns correct metrics."""
        config = RLMConfig(use_llm_summaries=False, use_llm_topics=False)
        processor = DocumentProcessor(config)

        _, metrics = processor.prepare(str(source_dir))

        assert metrics["documents_processed"] == 2
        assert metrics["documents_failed"] == 0
        assert metrics["total_chars"] > 0

    def test_catalog_content(self, source_dir):
        """Test catalog contains document metadata."""
        config = RLMConfig(use_llm_summaries=False, use_llm_topics=False)
        processor = DocumentProcessor(config)

        prepared_path, _ = processor.prepare(str(source_dir))
        catalog_path = Path(prepared_path) / "_meta" / "catalog.json"
        catalog = json.loads(catalog_path.read_text())

        assert "documents" in catalog
        assert len(catalog["documents"]) == 2

        doc_ids = [d["id"] for d in catalog["documents"]]
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids

    def test_section_extraction(self, source_dir):
        """Test markdown sections are extracted."""
        config = RLMConfig(use_llm_summaries=False, use_llm_topics=False)
        processor = DocumentProcessor(config)

        prepared_path, _ = processor.prepare(str(source_dir))
        section_path = Path(prepared_path) / "_meta" / "section_index.json"
        sections = json.loads(section_path.read_text())

        assert "doc1" in sections
        assert len(sections["doc1"]) >= 1
        assert sections["doc1"][0]["title"] == "Document 1"

    def test_keyword_topics(self, source_dir):
        """Test keyword-based topic extraction."""
        config = RLMConfig(use_llm_summaries=False, use_llm_topics=False)
        processor = DocumentProcessor(config)

        prepared_path, _ = processor.prepare(str(source_dir))
        topic_path = Path(prepared_path) / "_index" / "topics" / "_topic_map.json"
        topics = json.loads(topic_path.read_text())

        assert isinstance(topics, dict)
        # Should have extracted some topics
        assert len(topics) > 0
