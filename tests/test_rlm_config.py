"""Tests for RLMConfig."""

import pytest
from custom_rag.rlm import RLMConfig


class TestRLMConfig:
    """Test RLMConfig validation and properties."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RLMConfig()

        assert config.security_mode == "lite"
        assert config.orchestrator_model == "gpt-5-mini"
        assert config.worker_model == "gpt-5-nano"
        assert config.max_repl_steps == 15
        assert config.max_file_reads == 12

    def test_security_mode_lite(self):
        """Test lite security mode properties."""
        config = RLMConfig(security_mode="lite")

        assert config.use_process_isolation is False
        assert config.use_injection_defense is False
        assert config.use_strict_paths is False

    def test_security_mode_full(self):
        """Test full security mode properties."""
        config = RLMConfig(security_mode="full")

        assert config.use_process_isolation is True
        assert config.use_injection_defense is True
        assert config.use_strict_paths is True

    def test_invalid_security_mode(self):
        """Test that invalid security mode raises error."""
        with pytest.raises(ValueError, match="security_mode must be"):
            RLMConfig(security_mode="invalid")

    def test_invalid_repl_steps_zero(self):
        """Test that zero repl steps raises error."""
        with pytest.raises(ValueError, match="max_repl_steps must be >= 1"):
            RLMConfig(max_repl_steps=0)

    def test_invalid_repl_steps_excessive(self):
        """Test that excessive repl steps raises error."""
        with pytest.raises(ValueError, match="max_repl_steps > 50"):
            RLMConfig(max_repl_steps=100)

    def test_invalid_chunk_overlap(self):
        """Test that chunk_overlap >= chunk_size raises error."""
        with pytest.raises(ValueError, match="chunk_overlap must be < chunk_size"):
            RLMConfig(chunk_size=100, chunk_overlap=100)

    def test_invalid_timeout_too_small(self):
        """Test that small timeout raises error."""
        with pytest.raises(ValueError, match="repl_timeout must be >= 0.1"):
            RLMConfig(repl_timeout=0.01)

    def test_to_dict(self):
        """Test serialization to dict."""
        config = RLMConfig(max_repl_steps=10)
        d = config.to_dict()

        assert isinstance(d, dict)
        assert d["max_repl_steps"] == 10
        assert "security_mode" in d


class TestRLMConfigCustomValues:
    """Test RLMConfig with custom values."""

    def test_custom_models(self):
        """Test custom model configuration."""
        config = RLMConfig(
            orchestrator_model="gpt-4-turbo",
            worker_model="gpt-3.5-turbo",
        )

        assert config.orchestrator_model == "gpt-4-turbo"
        assert config.worker_model == "gpt-3.5-turbo"

    def test_custom_limits(self):
        """Test custom limit configuration."""
        config = RLMConfig(
            max_repl_steps=20,
            max_file_reads=8,
            max_sub_calls=4,
        )

        assert config.max_repl_steps == 20
        assert config.max_file_reads == 8
        assert config.max_sub_calls == 4

    def test_disabled_caching(self):
        """Test disabling cache."""
        config = RLMConfig(enable_cache=False)

        assert config.enable_cache is False

    def test_disabled_llm_features(self):
        """Test disabling LLM summaries and topics."""
        config = RLMConfig(
            use_llm_summaries=False,
            use_llm_topics=False,
        )

        assert config.use_llm_summaries is False
        assert config.use_llm_topics is False
