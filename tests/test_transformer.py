"""
Tests for DataTransformer core functionality.
"""
import pytest
import tempfile
from pathlib import Path
from dtflow import (
    DataTransformer,
    DictWrapper,
    TransformError,
    TransformErrors,
    get_preset,
    list_presets,
)


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

    def test_validate_all_pass(self):
        """Test validate() when all records pass."""
        dt = DataTransformer([{"a": 1}, {"a": 2}, {"a": 3}])
        errors = dt.validate(lambda x: x.a > 0)
        assert len(errors) == 0

    def test_validate_some_fail(self):
        """Test validate() when some records fail."""
        dt = DataTransformer([{"a": 1}, {"a": -1}, {"a": 2}])
        errors = dt.validate(lambda x: x.a > 0)
        assert len(errors) == 1
        assert errors[0].index == 1
        assert errors[0].item == {"a": -1}

    def test_validate_with_exception(self):
        """Test validate() when validation function raises exception."""
        dt = DataTransformer([{"a": 1}, {"b": 2}])  # 第二条缺少 a
        errors = dt.validate(lambda x: x.a > 0)
        assert len(errors) == 1
        assert errors[0].index == 1
        assert isinstance(errors[0].error, AttributeError)

    def test_validate_raw_mode(self):
        """Test validate() with raw=True."""
        dt = DataTransformer([{"a": 1}, {"a": -1}])
        errors = dt.validate(lambda x: x["a"] > 0, raw=True)
        assert len(errors) == 1
        assert errors[0].index == 1


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


class TestErrorHandling:
    """Test cases for error handling in transformations."""

    def test_to_default_skip_on_error(self, capsys):
        """Test default behavior skips errors and prints warning."""
        dt = DataTransformer([
            {"q": "问题1", "a": "回答1"},
            {"q": "问题2"},  # 缺少 'a' 字段
            {"q": "问题3", "a": "回答3"},
        ])

        results = dt.to(lambda x: {"instruction": x.q, "output": x.a})

        assert len(results) == 2
        assert results[0]["instruction"] == "问题1"
        assert results[1]["instruction"] == "问题3"

        # 检查打印了警告
        captured = capsys.readouterr()
        assert "2/3 成功" in captured.err
        assert "1 失败" in captured.err

    def test_to_raise_on_error(self):
        """Test raise strategy stops on first error."""
        dt = DataTransformer([
            {"q": "问题1", "a": "回答1"},
            {"q": "问题2"},  # 缺少 'a' 字段
            {"q": "问题3", "a": "回答3"},
        ])

        with pytest.raises(TransformErrors) as exc_info:
            dt.to(lambda x: {"instruction": x.q, "output": x.a}, on_error="raise")

        errors = exc_info.value
        assert len(errors) == 1
        assert errors.errors[0].index == 1

    def test_to_skip_on_error(self, capsys):
        """Test skip strategy continues processing."""
        dt = DataTransformer([
            {"q": "问题1", "a": "回答1"},
            {"q": "问题2"},  # 缺少 'a' 字段
            {"q": "问题3", "a": "回答3"},
        ])

        results = dt.to(lambda x: {"instruction": x.q, "output": x.a}, on_error="skip")

        assert len(results) == 2
        assert results[0]["instruction"] == "问题1"
        assert results[1]["instruction"] == "问题3"

    def test_to_null_on_error(self):
        """Test null strategy returns None for errors."""
        dt = DataTransformer([
            {"q": "问题1", "a": "回答1"},
            {"q": "问题2"},  # 缺少 'a' 字段
            {"q": "问题3", "a": "回答3"},
        ])

        results = dt.to(lambda x: {"instruction": x.q, "output": x.a}, on_error="null")

        assert len(results) == 3
        assert results[0]["instruction"] == "问题1"
        assert results[1] is None
        assert results[2]["instruction"] == "问题3"

    def test_to_return_errors(self):
        """Test return_errors flag returns error details."""
        dt = DataTransformer([
            {"q": "问题1", "a": "回答1"},
            {"q": "问题2"},  # 缺少 'a' 字段
            {"q": "问题3"},  # 缺少 'a' 字段
            {"q": "问题4", "a": "回答4"},
        ])

        results, errors = dt.to(
            lambda x: {"instruction": x.q, "output": x.a},
            on_error="skip",
            return_errors=True
        )

        assert len(results) == 2
        assert len(errors) == 2
        assert errors[0].index == 1
        assert errors[1].index == 2
        assert isinstance(errors[0].error, AttributeError)

    def test_transform_skip_on_error(self):
        """Test transform with skip strategy."""
        dt = DataTransformer([
            {"q": "问题1", "a": "回答1"},
            {"q": "问题2"},  # 缺少 'a' 字段
        ])

        result = dt.transform(lambda x: {"q": x.q, "a": x.a}, on_error="skip")

        assert isinstance(result, DataTransformer)
        assert len(result) == 1

    def test_filter_default_skip_on_error(self, capsys):
        """Test filter default skips errors and prints warning."""
        dt = DataTransformer([
            {"score": 0.8},
            {"value": 0.5},  # 缺少 'score' 字段
            {"score": 0.9},
        ])

        result = dt.filter(lambda x: x.score > 0.5)

        assert len(result) == 2

        # 检查打印了警告
        captured = capsys.readouterr()
        assert "1 失败" in captured.err

    def test_filter_raise_on_error(self):
        """Test filter raise strategy."""
        dt = DataTransformer([
            {"score": 0.8},
            {"value": 0.5},  # 缺少 'score' 字段
            {"score": 0.9},
        ])

        with pytest.raises(TransformErrors):
            dt.filter(lambda x: x.score > 0.5, on_error="raise")

    def test_filter_skip_on_error(self, capsys):
        """Test filter skip strategy."""
        dt = DataTransformer([
            {"score": 0.8},
            {"value": 0.5},  # 缺少 'score' 字段
            {"score": 0.9},
        ])

        result = dt.filter(lambda x: x.score > 0.5, on_error="skip")

        assert len(result) == 2

    def test_filter_keep_on_error(self):
        """Test filter keep strategy preserves error rows."""
        dt = DataTransformer([
            {"score": 0.8},
            {"value": 0.5},  # 缺少 'score' 字段
            {"score": 0.3},
        ])

        result = dt.filter(lambda x: x.score > 0.5, on_error="keep")

        # 保留: score=0.8 通过, value=0.5 错误保留, score=0.3 不通过
        assert len(result) == 2
        assert result[0]["score"] == 0.8
        assert result[1]["value"] == 0.5

    def test_transform_error_info(self):
        """Test TransformError contains useful info."""
        dt = DataTransformer([{"q": "问题"}])

        with pytest.raises(TransformErrors) as exc_info:
            dt.to(lambda x: {"a": x.missing_field}, on_error="raise")

        err = exc_info.value.errors[0]
        assert err.index == 0
        assert err.item == {"q": "问题"}
        assert "missing_field" in str(err.error)

    def test_transform_errors_message(self):
        """Test TransformErrors provides clear message."""
        dt = DataTransformer([
            {"q": "问题1"},
            {"q": "问题2"},
        ])

        with pytest.raises(TransformErrors) as exc_info:
            dt.to(lambda x: {"a": x.missing}, on_error="raise")

        msg = str(exc_info.value)
        assert "第 0 行" in msg or "[0]" in msg

    def test_no_error_no_side_effects(self):
        """Test normal operation unchanged when no errors."""
        dt = DataTransformer([{"q": "问题", "a": "回答"}])

        # All strategies should produce same result when no errors
        result1 = dt.to(lambda x: {"q": x.q}, on_error="raise")
        result2 = dt.to(lambda x: {"q": x.q}, on_error="skip")
        result3 = dt.to(lambda x: {"q": x.q}, on_error="null")

        assert result1 == result2 == result3 == [{"q": "问题"}]


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


class TestConcat:
    """Test cases for concat functionality."""

    def test_concat_two_transformers(self):
        """Test concatenating two DataTransformer instances."""
        dt1 = DataTransformer([{"id": 1}, {"id": 2}])
        dt2 = DataTransformer([{"id": 3}, {"id": 4}])

        merged = DataTransformer.concat(dt1, dt2)

        assert len(merged) == 4
        assert merged[0]["id"] == 1
        assert merged[3]["id"] == 4

    def test_concat_multiple_transformers(self):
        """Test concatenating multiple DataTransformer instances."""
        dt1 = DataTransformer([{"id": 1}])
        dt2 = DataTransformer([{"id": 2}])
        dt3 = DataTransformer([{"id": 3}])

        merged = DataTransformer.concat(dt1, dt2, dt3)

        assert len(merged) == 3
        assert [item["id"] for item in merged.data] == [1, 2, 3]

    def test_concat_from_files(self):
        """Test concatenating from file paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "a.jsonl"
            file2 = Path(tmpdir) / "b.jsonl"

            DataTransformer([{"id": 1}, {"id": 2}]).save(str(file1))
            DataTransformer([{"id": 3}, {"id": 4}]).save(str(file2))

            merged = DataTransformer.concat(str(file1), str(file2))

            assert len(merged) == 4
            assert merged[0]["id"] == 1
            assert merged[3]["id"] == 4

    def test_concat_mixed_sources(self):
        """Test concatenating mixed sources (files and DataTransformers)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "a.jsonl"
            DataTransformer([{"id": 1}]).save(str(file1))

            dt2 = DataTransformer([{"id": 2}])

            merged = DataTransformer.concat(str(file1), dt2)

            assert len(merged) == 2
            assert merged[0]["id"] == 1
            assert merged[1]["id"] == 2

    def test_concat_empty(self):
        """Test concatenating with no sources returns empty."""
        merged = DataTransformer.concat()
        assert len(merged) == 0

    def test_concat_single_source(self):
        """Test concatenating single source."""
        dt = DataTransformer([{"id": 1}])
        merged = DataTransformer.concat(dt)
        assert len(merged) == 1

    def test_concat_preserves_order(self):
        """Test that concat preserves order of items."""
        dt1 = DataTransformer([{"id": i} for i in range(5)])
        dt2 = DataTransformer([{"id": i} for i in range(5, 10)])

        merged = DataTransformer.concat(dt1, dt2)

        assert [item["id"] for item in merged.data] == list(range(10))

    def test_add_operator(self):
        """Test + operator for concatenation."""
        dt1 = DataTransformer([{"id": 1}, {"id": 2}])
        dt2 = DataTransformer([{"id": 3}, {"id": 4}])

        merged = dt1 + dt2

        assert len(merged) == 4
        assert merged[0]["id"] == 1
        assert merged[3]["id"] == 4

    def test_add_operator_chained(self):
        """Test chained + operators."""
        dt1 = DataTransformer([{"id": 1}])
        dt2 = DataTransformer([{"id": 2}])
        dt3 = DataTransformer([{"id": 3}])

        merged = dt1 + dt2 + dt3

        assert len(merged) == 3
        assert [item["id"] for item in merged.data] == [1, 2, 3]

    def test_add_operator_with_file(self):
        """Test + operator with file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "a.jsonl"
            DataTransformer([{"id": 2}]).save(str(file1))

            dt1 = DataTransformer([{"id": 1}])
            merged = dt1 + str(file1)

            assert len(merged) == 2
            assert merged[0]["id"] == 1
            assert merged[1]["id"] == 2

    def test_concat_different_fields(self):
        """Test concatenating data with different fields."""
        dt1 = DataTransformer([{"a": 1, "b": 2}])
        dt2 = DataTransformer([{"a": 3, "c": 4}])

        merged = DataTransformer.concat(dt1, dt2)

        assert len(merged) == 2
        assert merged[0] == {"a": 1, "b": 2}
        assert merged[1] == {"a": 3, "c": 4}

    def test_concat_invalid_source_type(self):
        """Test error for invalid source type."""
        with pytest.raises(TypeError):
            DataTransformer.concat([{"id": 1}])  # list is not valid, should be DataTransformer

    def test_concat_returns_new_instance(self):
        """Test that concat returns a new DataTransformer instance."""
        dt1 = DataTransformer([{"id": 1}])
        dt2 = DataTransformer([{"id": 2}])

        merged = DataTransformer.concat(dt1, dt2)

        assert merged is not dt1
        assert merged is not dt2

        # Modifying merged should not affect originals
        merged.data.append({"id": 3})
        assert len(dt1) == 1
        assert len(dt2) == 1


class TestUnwrap:
    """测试 _unwrap 函数（DictWrapper 转 dict）"""

    def test_unwrap_simple(self):
        """测试简单 DictWrapper 转换"""
        from dtflow.cli.transform import _unwrap

        wrapper = DictWrapper({"a": 1, "b": "text"})
        result = _unwrap(wrapper)

        assert result == {"a": 1, "b": "text"}
        assert type(result) is dict

    def test_unwrap_nested(self):
        """测试嵌套 DictWrapper 转换"""
        from dtflow.cli.transform import _unwrap

        data = {"outer": {"inner": {"value": 123}}}
        wrapper = DictWrapper(data)
        # 访问嵌套会产生新的 DictWrapper
        nested_wrapper = wrapper.outer.inner

        result = _unwrap({"data": nested_wrapper, "list": [wrapper.outer]})

        assert result == {"data": {"value": 123}, "list": [{"inner": {"value": 123}}]}
        assert type(result["data"]) is dict
        assert type(result["list"][0]) is dict

    def test_unwrap_in_list(self):
        """测试列表中的 DictWrapper 转换"""
        from dtflow.cli.transform import _unwrap

        wrapper = DictWrapper({"x": 1})
        result = _unwrap([wrapper, {"y": 2}, wrapper])

        assert result == [{"x": 1}, {"y": 2}, {"x": 1}]
        assert all(type(item) is dict for item in result)

    def test_unwrap_plain_dict(self):
        """测试普通 dict 不受影响"""
        from dtflow.cli.transform import _unwrap

        data = {"a": 1, "nested": {"b": 2}}
        result = _unwrap(data)

        assert result == data
        assert type(result) is dict


# 模块级函数用于并行处理测试（必须可 pickle）
def _transform_func(item):
    """测试用转换函数"""
    return {"id": item["id"], "value": item["value"] * 2}


def _filter_func(item):
    """测试用过滤函数"""
    return item["value"] > 5


def _error_func(item):
    """测试用错误函数"""
    raise ValueError("Test error")


class TestParallel:
    """Test cases for parallel processing."""

    def test_map_parallel_basic(self):
        """Test basic map_parallel functionality."""
        dt = DataTransformer([{"id": i, "value": i} for i in range(10)])

        results = dt.map_parallel(_transform_func, workers=2)

        assert len(results) == 10
        assert results[0] == {"id": 0, "value": 0}
        assert results[5] == {"id": 5, "value": 10}

    def test_map_parallel_empty(self):
        """Test map_parallel with empty data."""
        dt = DataTransformer([])

        results = dt.map_parallel(_transform_func)

        assert results == []

    def test_map_parallel_lambda_error(self):
        """Test map_parallel raises TypeError for lambda."""
        dt = DataTransformer([{"id": 1}])

        with pytest.raises(TypeError, match="无法被 pickle"):
            dt.map_parallel(lambda x: x)

    def test_filter_parallel_basic(self):
        """Test basic filter_parallel functionality."""
        dt = DataTransformer([{"id": i, "value": i} for i in range(10)])

        result = dt.filter_parallel(_filter_func, workers=2)

        assert isinstance(result, DataTransformer)
        assert len(result) == 4  # values 6, 7, 8, 9 > 5
        assert all(item["value"] > 5 for item in result.data)

    def test_filter_parallel_empty(self):
        """Test filter_parallel with empty data."""
        dt = DataTransformer([])

        result = dt.filter_parallel(_filter_func)

        assert len(result) == 0

    def test_filter_parallel_lambda_error(self):
        """Test filter_parallel raises TypeError for lambda."""
        dt = DataTransformer([{"id": 1}])

        with pytest.raises(TypeError, match="无法被 pickle"):
            dt.filter_parallel(lambda x: True)

    def test_map_parallel_with_error_in_func(self):
        """Test map_parallel handles errors in function."""
        dt = DataTransformer([{"id": 1}])

        with pytest.raises(RuntimeError, match="并行处理失败"):
            dt.map_parallel(_error_func, workers=1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
