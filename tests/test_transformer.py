"""
Tests for DataTransformer core functionality.
"""
import pytest
import tempfile
from pathlib import Path
from data_transformer import DataTransformer, DictWrapper, get_preset, list_presets


class TestDataTransformer:
    """Test cases for DataTransformer class."""

    def test_init_empty(self):
        """Test initialization with no data."""
        dt = DataTransformer()
        assert len(dt) == 0

    def test_init_with_data(self):
        """Test initialization with data."""
        data = [{"text": "hello"}, {"text": "world"}]
        dt = DataTransformer(data)
        assert len(dt) == 2

    def test_getitem(self):
        """Test indexing."""
        dt = DataTransformer([{"text": "a"}, {"text": "b"}])
        assert dt[0]["text"] == "a"
        assert dt[1]["text"] == "b"

    def test_to_transform(self):
        """Test to() method with attribute access."""
        dt = DataTransformer([{"q": "问题", "a": "回答"}])
        result = dt.to(lambda x: {"instruction": x.q, "output": x.a})
        assert result[0]["instruction"] == "问题"
        assert result[0]["output"] == "回答"

    def test_transform_chained(self):
        """Test transform() returns DataTransformer for chaining."""
        dt = DataTransformer([{"q": "问题", "a": "回答"}])
        result = dt.transform(lambda x: {"instruction": x.q})
        assert isinstance(result, DataTransformer)
        assert result[0]["instruction"] == "问题"

    def test_filter_with_attribute_access(self):
        """Test filtering with attribute access."""
        dt = DataTransformer([
            {"score": 0.8, "text": "high"},
            {"score": 0.3, "text": "low"},
            {"score": 0.9, "text": "highest"}
        ])
        filtered = dt.filter(lambda x: x.score > 0.5)
        assert len(filtered) == 2
        assert all(item["score"] > 0.5 for item in filtered.data)

    def test_sample(self):
        """Test sampling."""
        dt = DataTransformer([{"id": i} for i in range(100)])
        sampled = dt.sample(10, seed=42)
        assert len(sampled) == 10

    def test_head(self):
        """Test head()."""
        dt = DataTransformer([{"id": i} for i in range(100)])
        result = dt.head(5)
        assert len(result) == 5
        assert result[0]["id"] == 0

    def test_tail(self):
        """Test tail()."""
        dt = DataTransformer([{"id": i} for i in range(100)])
        result = dt.tail(5)
        assert len(result) == 5
        assert result[-1]["id"] == 99

    def test_fields(self):
        """Test fields extraction."""
        dt = DataTransformer([{"a": 1, "b": 2, "c": 3}])
        fields = dt.fields()
        assert "a" in fields
        assert "b" in fields
        assert "c" in fields

    def test_stats(self):
        """Test statistics."""
        dt = DataTransformer([
            {"text": "hello", "label": "positive"},
            {"text": "world", "label": "negative"}
        ])
        stats = dt.stats()
        assert stats["total"] == 2
        assert "text" in stats["fields"]
        assert "label" in stats["fields"]

    def test_copy(self):
        """Test deep copy."""
        dt = DataTransformer([{"text": "hello"}])
        dt_copy = dt.copy()
        dt_copy.data.append({"text": "world"})
        assert len(dt) == 1
        assert len(dt_copy) == 2

    def test_shuffle(self):
        """Test shuffle returns new instance."""
        dt = DataTransformer([{"id": i} for i in range(10)])
        shuffled = dt.shuffle(seed=42)
        # Should be a new instance
        assert shuffled is not dt
        # Same elements
        assert sorted([x["id"] for x in shuffled.data]) == list(range(10))

    def test_split(self):
        """Test splitting dataset."""
        dt = DataTransformer([{"id": i} for i in range(100)])
        train, val = dt.split(ratio=0.8, seed=42)
        assert len(train) == 80
        assert len(val) == 20

    def test_save_load_jsonl(self):
        """Test saving and loading JSONL format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.jsonl"
            dt = DataTransformer([{"text": "hello"}, {"text": "world"}])
            dt.save(str(filepath))

            dt_loaded = DataTransformer.load(str(filepath))
            assert len(dt_loaded) == 2
            assert dt_loaded[0]["text"] == "hello"

    def test_save_load_json(self):
        """Test saving and loading JSON format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = Path(tmpdir) / "test.json"
            dt = DataTransformer([{"text": "test"}])
            dt.save(str(filepath))

            dt_loaded = DataTransformer.load(str(filepath))
            assert len(dt_loaded) == 1

    def test_nested_attribute_access(self):
        """Test nested dict attribute access."""
        dt = DataTransformer([{"meta": {"author": "test", "date": "2024"}}])
        result = dt.to(lambda x: {"author": x.meta.author})
        assert result[0]["author"] == "test"


class TestDictWrapper:
    """Test cases for DictWrapper class."""

    def test_attribute_access(self):
        """Test attribute access."""
        w = DictWrapper({"name": "test", "value": 123})
        assert w.name == "test"
        assert w.value == 123

    def test_nested_attribute_access(self):
        """Test nested dict access."""
        w = DictWrapper({"a": {"b": {"c": "deep"}}})
        assert w.a.b.c == "deep"

    def test_dict_access(self):
        """Test dict-style access."""
        w = DictWrapper({"name": "test"})
        assert w["name"] == "test"

    def test_get_method(self):
        """Test get() with default."""
        w = DictWrapper({"name": "test"})
        assert w.get("name") == "test"
        assert w.get("missing", "default") == "default"

    def test_contains(self):
        """Test __contains__."""
        w = DictWrapper({"name": "test"})
        assert "name" in w
        assert "missing" not in w

    def test_to_dict(self):
        """Test to_dict()."""
        data = {"name": "test", "value": 123}
        w = DictWrapper(data)
        assert w.to_dict() == data

    def test_missing_attribute_error(self):
        """Test AttributeError for missing keys."""
        w = DictWrapper({"name": "test"})
        with pytest.raises(AttributeError):
            _ = w.missing_field


class TestPresets:
    """Test cases for preset transformations."""

    def test_list_presets(self):
        """Test listing available presets."""
        presets = list_presets()
        assert "openai_chat" in presets
        assert "alpaca" in presets
        assert "sharegpt" in presets
        assert "dpo_pair" in presets
        assert "simple_qa" in presets

    def test_openai_chat_preset(self):
        """Test OpenAI Chat preset."""
        dt = DataTransformer([{"q": "问题", "a": "回答"}])
        transform_func = get_preset("openai_chat", user_field="q", assistant_field="a")
        result = dt.to(transform_func)

        assert "messages" in result[0]
        messages = result[0]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "问题"
        assert messages[1]["role"] == "assistant"

    def test_openai_chat_with_system(self):
        """Test OpenAI Chat preset with system prompt."""
        dt = DataTransformer([{"q": "问题", "a": "回答"}])
        transform_func = get_preset(
            "openai_chat",
            user_field="q",
            assistant_field="a",
            system_prompt="你是一个助手"
        )
        result = dt.to(transform_func)

        messages = result[0]["messages"]
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "你是一个助手"

    def test_alpaca_preset(self):
        """Test Alpaca preset."""
        dt = DataTransformer([{"q": "问题", "input": "", "a": "回答"}])
        transform_func = get_preset(
            "alpaca",
            instruction_field="q",
            input_field="input",
            output_field="a"
        )
        result = dt.to(transform_func)

        assert result[0]["instruction"] == "问题"
        assert result[0]["input"] == ""
        assert result[0]["output"] == "回答"

    def test_dpo_pair_preset(self):
        """Test DPO pair preset."""
        dt = DataTransformer([{
            "prompt": "问题",
            "chosen": "好回答",
            "rejected": "差回答"
        }])
        transform_func = get_preset("dpo_pair")
        result = dt.to(transform_func)

        assert result[0]["prompt"] == "问题"
        assert result[0]["chosen"] == "好回答"
        assert result[0]["rejected"] == "差回答"

    def test_simple_qa_preset(self):
        """Test simple QA preset."""
        dt = DataTransformer([{"q": "问题", "a": "回答"}])
        transform_func = get_preset("simple_qa", question_field="q", answer_field="a")
        result = dt.to(transform_func)

        assert result[0]["question"] == "问题"
        assert result[0]["answer"] == "回答"

    def test_invalid_preset(self):
        """Test error for invalid preset name."""
        with pytest.raises(ValueError):
            get_preset("invalid_preset_name")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
