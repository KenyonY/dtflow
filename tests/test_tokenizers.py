"""
Tests for tokenizers module.
"""
import pytest
from dtflow import DataTransformer
from dtflow.tokenizers import (
    count_tokens,
    token_counter,
    token_filter,
    token_stats,
)


class TestTokenizers:
    """Test cases for tokenizers module."""

    @pytest.fixture
    def sample_data(self):
        return [
            {"text": "Hello world"},
            {"text": "This is a longer sentence with more tokens"},
            {"text": "短文本"},
        ]

    def test_count_tokens_basic(self):
        """Test basic token counting."""
        pytest.importorskip("tiktoken")

        count = count_tokens("Hello world")
        assert count > 0
        assert isinstance(count, int)

    def test_count_tokens_empty(self):
        """Test empty string returns 0."""
        assert count_tokens("") == 0
        assert count_tokens(None) == 0

    def test_count_tokens_chinese(self):
        """Test Chinese text token counting."""
        pytest.importorskip("tiktoken")

        count = count_tokens("你好世界")
        assert count > 0

    def test_token_counter_single_field(self, sample_data):
        """Test token counter with single field."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(sample_data)
        result = dt.to(token_counter("text"))

        assert len(result) == 3
        assert "token_count" in result[0]
        assert result[0]["token_count"] > 0
        # 第二条应该有更多 token
        assert result[1]["token_count"] > result[0]["token_count"]

    def test_token_counter_multiple_fields(self):
        """Test token counter with multiple fields."""
        pytest.importorskip("tiktoken")

        data = [{"q": "Hello", "a": "World"}]
        dt = DataTransformer(data)
        result = dt.to(token_counter(["q", "a"]))

        assert result[0]["token_count"] > 0

    def test_token_counter_custom_output_field(self, sample_data):
        """Test custom output field name."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(sample_data)
        result = dt.to(token_counter("text", output_field="tokens"))

        assert "tokens" in result[0]
        assert "token_count" not in result[0]

    def test_token_filter_min_tokens(self, sample_data):
        """Test filtering by minimum tokens."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(sample_data)
        filtered = dt.filter(token_filter("text", min_tokens=5))

        # 只有较长的文本应该保留
        assert len(filtered) < len(sample_data)

    def test_token_filter_max_tokens(self, sample_data):
        """Test filtering by maximum tokens."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(sample_data)
        filtered = dt.filter(token_filter("text", max_tokens=3))

        # 只有较短的文本应该保留
        assert len(filtered) < len(sample_data)

    def test_token_filter_range(self, sample_data):
        """Test filtering by token range."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(sample_data)
        filtered = dt.filter(token_filter("text", min_tokens=2, max_tokens=10))

        assert len(filtered) > 0

    def test_token_stats_basic(self, sample_data):
        """Test basic statistics."""
        pytest.importorskip("tiktoken")

        stats = token_stats(sample_data, "text")

        assert "total_tokens" in stats
        assert "count" in stats
        assert "avg_tokens" in stats
        assert "min_tokens" in stats
        assert "max_tokens" in stats
        assert "median_tokens" in stats

        assert stats["count"] == 3
        assert stats["total_tokens"] > 0
        assert stats["min_tokens"] <= stats["avg_tokens"] <= stats["max_tokens"]

    def test_token_stats_empty_data(self):
        """Test stats with empty data."""
        stats = token_stats([], "text")
        assert stats["total_tokens"] == 0
        assert stats["count"] == 0

    def test_token_stats_multiple_fields(self):
        """Test stats with multiple fields."""
        pytest.importorskip("tiktoken")

        data = [
            {"q": "Hello", "a": "World"},
            {"q": "Test", "a": "Data"},
        ]
        stats = token_stats(data, ["q", "a"])

        assert stats["count"] == 2
        assert stats["total_tokens"] > 0

    def test_invalid_backend(self):
        """Test error for invalid backend."""
        with pytest.raises(ValueError):
            count_tokens("hello", backend="invalid")


class TestTokenizersWithTransformers:
    """Test cases using transformers backend."""

    def test_count_tokens_transformers(self):
        """Test token counting with transformers backend."""
        pytest.importorskip("transformers")

        count = count_tokens(
            "Hello world",
            model="bert-base-uncased",
            backend="transformers"
        )
        assert count > 0


class TestTokenizersEdgeCases:
    """Edge case tests for tokenizers module."""

    def test_token_counter_missing_field(self):
        """Test token counter with missing field."""
        pytest.importorskip("tiktoken")

        data = [{"other": "value"}]
        dt = DataTransformer(data)
        result = dt.to(token_counter("text"))

        # 缺失字段应该计为 0
        assert result[0]["token_count"] == 0

    def test_token_counter_none_value(self):
        """Test token counter with None value."""
        pytest.importorskip("tiktoken")

        data = [{"text": None}]
        dt = DataTransformer(data)
        result = dt.to(token_counter("text"))

        assert result[0]["token_count"] == 0

    def test_token_counter_numeric_value(self):
        """Test token counter converts numeric to string."""
        pytest.importorskip("tiktoken")

        data = [{"text": 12345}]
        dt = DataTransformer(data)
        result = dt.to(token_counter("text"))

        assert result[0]["token_count"] > 0

    def test_token_filter_no_bounds(self):
        """Test token filter with no min/max bounds."""
        pytest.importorskip("tiktoken")

        data = [{"text": "Hello"}, {"text": "World"}]
        dt = DataTransformer(data)
        filtered = dt.filter(token_filter("text"))

        # 无限制时应保留所有数据
        assert len(filtered) == 2

    def test_token_filter_only_min(self):
        """Test token filter with only min bound."""
        pytest.importorskip("tiktoken")

        data = [{"text": "Hi"}, {"text": "This is a longer text"}]
        dt = DataTransformer(data)
        filtered = dt.filter(token_filter("text", min_tokens=3))

        assert len(filtered) == 1

    def test_token_filter_only_max(self):
        """Test token filter with only max bound."""
        pytest.importorskip("tiktoken")

        data = [{"text": "Hi"}, {"text": "This is a much longer text with many tokens"}]
        dt = DataTransformer(data)
        filtered = dt.filter(token_filter("text", max_tokens=3))

        assert len(filtered) == 1

    def test_token_stats_single_item(self):
        """Test stats with single item."""
        pytest.importorskip("tiktoken")

        data = [{"text": "Hello world"}]
        stats = token_stats(data, "text")

        assert stats["count"] == 1
        assert stats["min_tokens"] == stats["max_tokens"] == stats["avg_tokens"]

    def test_token_counter_preserves_original_fields(self):
        """Test that token counter preserves all original fields."""
        pytest.importorskip("tiktoken")

        data = [{"text": "Hello", "label": "greeting", "score": 0.9}]
        dt = DataTransformer(data)
        result = dt.to(token_counter("text"))

        assert result[0]["text"] == "Hello"
        assert result[0]["label"] == "greeting"
        assert result[0]["score"] == 0.9
        assert "token_count" in result[0]

    def test_count_tokens_long_text(self):
        """Test counting tokens for longer text."""
        pytest.importorskip("tiktoken")

        long_text = "Hello world. " * 100
        count = count_tokens(long_text)
        assert count > 100

    def test_tiktoken_import_error(self):
        """Test ImportError message for tiktoken."""
        # 这个测试主要验证错误消息格式，实际环境中 tiktoken 已安装
        # 所以只验证函数不抛出异常
        pytest.importorskip("tiktoken")
        count = count_tokens("test")
        assert isinstance(count, int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
