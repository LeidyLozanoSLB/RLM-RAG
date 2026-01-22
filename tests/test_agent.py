"""Tests for agent components."""

import tempfile
import json
from pathlib import Path
import pytest
from unittest.mock import Mock, patch

from custom_rag.rlm import RLMConfig
from custom_rag.rlm.agent import (
    BudgetManager,
    FilesystemTools,
    SimpleREPL,
)


class TestBudgetManager:
    """Test budget tracking."""

    def test_initial_budget(self):
        """Test initial budget values."""
        config = RLMConfig(max_repl_steps=5, max_file_reads=3, max_sub_calls=2)
        budget = BudgetManager(config)

        status = budget.get_status()
        assert status.repl_steps_remaining == 5
        assert status.file_reads_remaining == 3
        assert status.sub_calls_remaining == 2

    def test_can_step_decrements(self):
        """Test step counting works."""
        config = RLMConfig(max_repl_steps=2)
        budget = BudgetManager(config)

        assert budget.can_step() is True
        budget.record_step()
        assert budget.can_step() is True
        budget.record_step()
        assert budget.can_step() is False

    def test_can_read_file(self):
        """Test file read counting."""
        config = RLMConfig(max_file_reads=1)
        budget = BudgetManager(config)

        assert budget.can_read_file() is True
        budget.record_file_read()
        assert budget.can_read_file() is False

    def test_reset(self):
        """Test reset clears all counters."""
        config = RLMConfig(max_repl_steps=5)
        budget = BudgetManager(config)

        budget.record_step()
        budget.record_step()
        budget.reset()

        assert budget.get_status().repl_steps_remaining == 5


class TestFilesystemTools:
    """Test filesystem tools."""

    @pytest.fixture
    def prepared_dir(self):
        """Create prepared directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prepared = Path(tmpdir) / "prepared"
            prepared.mkdir()

            # Create structure
            (prepared / "_meta").mkdir()
            (prepared / "documents").mkdir()
            (prepared / "_summaries").mkdir()

            # Create catalog
            catalog = {
                "documents": [
                    {"id": "doc1", "title": "Document 1"},
                    {"id": "doc2", "title": "Document 2"},
                ]
            }
            (prepared / "_meta" / "catalog.json").write_text(
                json.dumps(catalog)
            )
            (prepared / "_meta" / "section_index.json").write_text("{}")

            # Create topic map
            (prepared / "_index" / "topics").mkdir(parents=True)
            (prepared / "_index" / "topics" / "_topic_map.json").write_text(
                '{"machine learning": ["doc1"]}'
            )

            # Create documents
            (prepared / "documents" / "doc1.md").write_text(
                "# Document 1\n\nContent about ML."
            )
            (prepared / "documents" / "doc2.md").write_text(
                "# Document 2\n\nContent about AI."
            )

            yield prepared

    @pytest.fixture
    def tools(self, prepared_dir):
        """Create FilesystemTools instance."""
        config = RLMConfig()
        budget = BudgetManager(config)
        return FilesystemTools(prepared_dir, budget, config)

    def test_get_catalog(self, tools):
        """Test getting document catalog."""
        catalog = tools.get_catalog()
        assert len(catalog) == 2
        assert catalog[0]["id"] == "doc1"

    def test_get_topics(self, tools):
        """Test getting topic map."""
        topics = tools.get_topics()
        assert "machine learning" in topics
        assert "doc1" in topics["machine learning"]

    def test_list_dir(self, tools):
        """Test listing directory."""
        contents = tools.list_dir(".")
        names = [c["name"] for c in contents]
        assert "_meta" in names
        assert "documents" in names

    def test_read_file(self, tools):
        """Test reading file."""
        content = tools.read_file("documents/doc1.md")
        assert "Document 1" in content
        assert "Content about ML" in content

    def test_read_file_budget_exhausted(self, tools):
        """Test read fails when budget exhausted."""
        tools.budget._file_reads = tools.config.max_file_reads

        result = tools.read_file("documents/doc1.md")
        assert "[ERROR: File read budget exhausted" in result
        assert "Cannot read more files" in result

    def test_read_file_not_found(self, tools):
        """Test read returns error for missing file."""
        result = tools.read_file("documents/nonexistent.md")
        assert "[ERROR: File not found" in result

    def test_path_escape_blocked(self, tools):
        """Test path traversal is blocked."""
        result = tools.read_file("../../../etc/passwd")
        assert "[ERROR:" in result

    def test_grep(self, tools):
        """Test grep search."""
        results = tools.grep("ML", path="documents")
        assert len(results) > 0
        assert any("doc1" in r["file"] for r in results)


class TestSimpleREPL:
    """Test in-process REPL."""

    @pytest.fixture
    def repl(self, prepared_dir):
        """Create SimpleREPL instance."""
        config = RLMConfig()
        budget = BudgetManager(config)
        tools = FilesystemTools(prepared_dir, budget, config)

        # Mock LLM client
        mock_llm = Mock()
        mock_llm.call = Mock(return_value="mocked response")

        return SimpleREPL(tools, mock_llm, budget)

    @pytest.fixture
    def prepared_dir(self):
        """Create minimal prepared directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prepared = Path(tmpdir)
            (prepared / "_meta").mkdir()
            (prepared / "_meta" / "catalog.json").write_text('{"documents": []}')
            (prepared / "_meta" / "section_index.json").write_text("{}")
            (prepared / "_index" / "topics").mkdir(parents=True)
            (prepared / "_index" / "topics" / "_topic_map.json").write_text("{}")
            yield prepared

    def test_execute_simple(self, repl):
        """Test simple code execution."""
        result = repl.execute("x = 1 + 1")

        assert result.success is True
        assert "x" in result.variables_updated
        assert repl.get_variable("x") == 2

    def test_execute_with_print(self, repl):
        """Test print output capture."""
        result = repl.execute('print("hello world")')

        assert result.success is True
        assert "hello world" in result.output

    def test_execute_error(self, repl):
        """Test error handling."""
        result = repl.execute("x = 1 / 0")

        assert result.success is False
        assert "ZeroDivisionError" in result.error

    def test_variable_persistence(self, repl):
        """Test variables persist across executions."""
        repl.execute("a = 10")
        repl.execute("b = a * 2")

        assert repl.get_variable("b") == 20

    def test_reset_clears_variables(self, repl):
        """Test reset clears user variables."""
        repl.execute("x = 42")
        repl.reset()

        assert repl.get_variable("x") is None

    def test_fs_available(self, repl):
        """Test fs tools are available in namespace."""
        result = repl.execute("catalog = fs.get_catalog()")

        assert result.success is True
        assert repl.get_variable("catalog") is not None

    def test_modules_available(self, repl):
        """Test safe modules are available."""
        # Check re is available directly (pre-loaded)
        result = repl.execute('m = re.match(r"\\d+", "123")')
        assert result.success is True
