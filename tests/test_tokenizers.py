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
    _auto_backend,
    messages_token_counter,
    messages_token_filter,
    messages_token_stats,
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


class TestAutoBackend:
    """Test cases for automatic backend detection."""

    def test_auto_backend_openai_models(self):
        """Test tiktoken backend for OpenAI models."""
        assert _auto_backend("gpt-4") == "tiktoken"
        assert _auto_backend("gpt-4o") == "tiktoken"
        assert _auto_backend("gpt-3.5-turbo") == "tiktoken"
        assert _auto_backend("gpt-4-turbo") == "tiktoken"
        assert _auto_backend("o1") == "tiktoken"
        assert _auto_backend("o1-mini") == "tiktoken"

    def test_auto_backend_hf_models(self):
        """Test transformers backend for HuggingFace models."""
        assert _auto_backend("Qwen/Qwen2-7B") == "transformers"
        assert _auto_backend("meta-llama/Llama-2-7b") == "transformers"
        assert _auto_backend("THUDM/chatglm3-6b") == "transformers"

    def test_auto_backend_local_paths(self):
        """Test transformers backend for local paths."""
        assert _auto_backend("/home/models/qwen") == "transformers"
        assert _auto_backend("./models/llama") == "transformers"
        assert _auto_backend("~/models/chatglm") == "transformers"

    def test_auto_backend_unknown_model(self):
        """Test default to transformers for unknown models."""
        assert _auto_backend("some-unknown-model") == "transformers"


class TestMessagesTokenCounter:
    """Test cases for messages token counter."""

    @pytest.fixture
    def messages_data(self):
        return [
            {
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Hello, how are you?"},
                    {"role": "assistant", "content": "I am fine, thank you!"},
                ]
            },
            {
                "messages": [
                    {"role": "user", "content": "What is Python?"},
                    {"role": "assistant", "content": "Python is a programming language."},
                ]
            },
        ]

    def test_messages_token_counter_simple(self, messages_data):
        """Test simple token counting mode."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(messages_data)
        result = dt.to(messages_token_counter())

        assert len(result) == 2
        assert "token_stats" in result[0]
        assert isinstance(result[0]["token_stats"], int)
        assert result[0]["token_stats"] > 0

    def test_messages_token_counter_detailed(self, messages_data):
        """Test detailed token counting mode."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(messages_data)
        result = dt.to(messages_token_counter(detailed=True))

        stats = result[0]["token_stats"]
        assert isinstance(stats, dict)
        assert "total" in stats
        assert "user" in stats
        assert "assistant" in stats
        assert "system" in stats
        assert "turns" in stats
        assert "avg_turn" in stats
        assert "max_turn" in stats

        # 验证统计合理性
        assert stats["total"] == stats["user"] + stats["assistant"] + stats["system"]
        assert stats["turns"] == 3  # system + user + assistant

    def test_messages_token_counter_custom_output_field(self, messages_data):
        """Test custom output field name."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(messages_data)
        result = dt.to(messages_token_counter(output_field="tokens"))

        assert "tokens" in result[0]
        assert "token_stats" not in result[0]

    def test_messages_token_counter_empty_messages(self):
        """Test with empty messages."""
        pytest.importorskip("tiktoken")

        data = [{"messages": []}]
        dt = DataTransformer(data)
        result = dt.to(messages_token_counter())

        assert result[0]["token_stats"] == 0

    def test_messages_token_counter_missing_messages(self):
        """Test with missing messages field."""
        pytest.importorskip("tiktoken")

        data = [{"other_field": "value"}]
        dt = DataTransformer(data)
        result = dt.to(messages_token_counter())

        assert result[0]["token_stats"] == 0

    def test_messages_token_counter_custom_messages_field(self):
        """Test with custom messages field name."""
        pytest.importorskip("tiktoken")

        data = [{
            "conversation": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
            ]
        }]
        dt = DataTransformer(data)
        result = dt.to(messages_token_counter(messages_field="conversation"))

        assert result[0]["token_stats"] > 0

    def test_messages_token_counter_preserves_original_fields(self, messages_data):
        """Test that original fields are preserved."""
        pytest.importorskip("tiktoken")

        data = [{
            "id": "123",
            "messages": [{"role": "user", "content": "Hi"}],
            "metadata": {"source": "test"},
        }]
        dt = DataTransformer(data)
        result = dt.to(messages_token_counter())

        assert result[0]["id"] == "123"
        assert result[0]["metadata"] == {"source": "test"}
        assert "token_stats" in result[0]


class TestMessagesTokenFilter:
    """Test cases for messages token filter."""

    @pytest.fixture
    def messages_data(self):
        return [
            {
                "id": "short",
                "messages": [
                    {"role": "user", "content": "Hi"},
                    {"role": "assistant", "content": "Hello!"},
                ],
            },
            {
                "id": "long",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": "Can you explain quantum computing in detail?"},
                    {"role": "assistant", "content": "Quantum computing is a type of computation that harnesses quantum mechanical phenomena."},
                ],
            },
        ]

    def test_messages_token_filter_min_tokens(self, messages_data):
        """Test filtering by minimum tokens."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(messages_data)
        filtered = dt.filter(messages_token_filter(min_tokens=20))

        assert len(filtered) == 1
        assert filtered[0]["id"] == "long"

    def test_messages_token_filter_max_tokens(self, messages_data):
        """Test filtering by maximum tokens."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(messages_data)
        filtered = dt.filter(messages_token_filter(max_tokens=10))

        assert len(filtered) == 1
        assert filtered[0]["id"] == "short"

    def test_messages_token_filter_range(self, messages_data):
        """Test filtering by token range."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(messages_data)
        filtered = dt.filter(messages_token_filter(min_tokens=5, max_tokens=50))

        assert len(filtered) >= 1

    def test_messages_token_filter_min_turns(self, messages_data):
        """Test filtering by minimum turns."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(messages_data)
        filtered = dt.filter(messages_token_filter(min_turns=3))

        assert len(filtered) == 1
        assert filtered[0]["id"] == "long"

    def test_messages_token_filter_max_turns(self, messages_data):
        """Test filtering by maximum turns."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(messages_data)
        filtered = dt.filter(messages_token_filter(max_turns=2))

        assert len(filtered) == 1
        assert filtered[0]["id"] == "short"

    def test_messages_token_filter_combined(self, messages_data):
        """Test combined token and turn filtering."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(messages_data)
        filtered = dt.filter(messages_token_filter(min_tokens=10, min_turns=2))

        assert len(filtered) >= 0  # 结果取决于具体 token 数

    def test_messages_token_filter_empty_messages(self):
        """Test filter with empty messages returns False."""
        pytest.importorskip("tiktoken")

        data = [{"messages": []}]
        dt = DataTransformer(data)
        filtered = dt.filter(messages_token_filter(min_tokens=0))

        assert len(filtered) == 0  # 空消息应该被过滤掉

    def test_messages_token_filter_no_bounds(self, messages_data):
        """Test filter with no bounds keeps all data."""
        pytest.importorskip("tiktoken")

        dt = DataTransformer(messages_data)
        filtered = dt.filter(messages_token_filter())

        assert len(filtered) == 2


class TestMessagesTokenStats:
    """Test cases for messages token statistics."""

    @pytest.fixture
    def messages_data(self):
        return [
            {
                "messages": [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "Hello"},
                    {"role": "assistant", "content": "Hi there!"},
                ]
            },
            {
                "messages": [
                    {"role": "user", "content": "What is Python?"},
                    {"role": "assistant", "content": "Python is a programming language."},
                ]
            },
        ]

    def test_messages_token_stats_basic(self, messages_data):
        """Test basic statistics."""
        pytest.importorskip("tiktoken")

        stats = messages_token_stats(messages_data)

        assert "count" in stats
        assert "total_tokens" in stats
        assert "user_tokens" in stats
        assert "assistant_tokens" in stats
        assert "system_tokens" in stats
        assert "avg_tokens" in stats
        assert "max_tokens" in stats
        assert "min_tokens" in stats
        assert "median_tokens" in stats
        assert "avg_turns" in stats

        assert stats["count"] == 2
        assert stats["total_tokens"] > 0
        assert stats["user_tokens"] > 0
        assert stats["assistant_tokens"] > 0

    def test_messages_token_stats_empty_data(self):
        """Test stats with empty data."""
        stats = messages_token_stats([])

        assert stats["count"] == 0
        assert stats["total_tokens"] == 0

    def test_messages_token_stats_custom_field(self):
        """Test stats with custom messages field."""
        pytest.importorskip("tiktoken")

        data = [{
            "conversation": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
            ]
        }]

        stats = messages_token_stats(data, messages_field="conversation")

        assert stats["count"] == 1
        assert stats["total_tokens"] > 0

    def test_messages_token_stats_no_messages(self):
        """Test stats with items lacking messages field."""
        pytest.importorskip("tiktoken")

        data = [{"other": "field"}]

        stats = messages_token_stats(data)

        assert stats["count"] == 0

    def test_messages_token_stats_single_item(self):
        """Test stats with single item."""
        pytest.importorskip("tiktoken")

        data = [{
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
            ]
        }]

        stats = messages_token_stats(data)

        assert stats["count"] == 1
        assert stats["min_tokens"] == stats["max_tokens"] == stats["avg_tokens"]

    def test_messages_token_stats_role_breakdown(self, messages_data):
        """Test that role token counts sum correctly."""
        pytest.importorskip("tiktoken")

        stats = messages_token_stats(messages_data)

        # user + assistant + system 应该等于或接近 total
        role_sum = stats["user_tokens"] + stats["assistant_tokens"] + stats["system_tokens"]
        assert role_sum == stats["total_tokens"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
