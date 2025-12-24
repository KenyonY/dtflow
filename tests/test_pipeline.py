"""
Tests for pipeline module.
"""
import tempfile
from pathlib import Path

import pytest

from dtflow import DataTransformer
from dtflow.pipeline import (
    generate_pipeline_template,
    run_pipeline,
    validate_pipeline,
    _execute_filter,
    _execute_dedupe,
    _execute_head,
    _execute_sample,
    _execute_shuffle,
    _execute_split,
    _execute_tail,
    _execute_transform,
    _format_step_description,
    _parse_condition,
)


class TestParseCondition:
    """Test cases for _parse_condition function."""

    def test_parse_greater_than(self):
        """Test > operator."""
        func = _parse_condition("score > 0.5")
        assert func({"score": 0.8}) is True
        assert func({"score": 0.3}) is False

    def test_parse_less_than(self):
        """Test < operator."""
        func = _parse_condition("score < 0.5")
        assert func({"score": 0.3}) is True
        assert func({"score": 0.8}) is False

    def test_parse_greater_equal(self):
        """Test >= operator."""
        func = _parse_condition("score >= 0.5")
        assert func({"score": 0.5}) is True
        assert func({"score": 0.4}) is False

    def test_parse_less_equal(self):
        """Test <= operator."""
        func = _parse_condition("score <= 0.5")
        assert func({"score": 0.5}) is True
        assert func({"score": 0.6}) is False

    def test_parse_equal_number(self):
        """Test == with number."""
        func = _parse_condition("score == 0.5")
        assert func({"score": 0.5}) is True
        assert func({"score": 0.6}) is False

    def test_parse_not_equal_number(self):
        """Test != with number."""
        func = _parse_condition("score != 0.5")
        assert func({"score": 0.6}) is True
        assert func({"score": 0.5}) is False

    def test_parse_len_greater(self):
        """Test len() >."""
        func = _parse_condition("len(text) > 5")
        assert func({"text": "hello world"}) is True
        assert func({"text": "hi"}) is False

    def test_parse_len_less(self):
        """Test len() <."""
        func = _parse_condition("len(text) < 5")
        assert func({"text": "hi"}) is True
        assert func({"text": "hello world"}) is False

    def test_parse_is_not_empty(self):
        """Test 'is not empty'."""
        func = _parse_condition("text is not empty")
        assert func({"text": "hello"}) is True
        assert func({"text": ""}) is False
        assert func({"text": None}) is False

    def test_parse_is_not_none(self):
        """Test 'is not None'."""
        func = _parse_condition("value is not None")
        assert func({"value": "hello"}) is True
        assert func({"value": None}) is False
        assert func({}) is False

    def test_parse_string_equal(self):
        """Test == with string."""
        func = _parse_condition("category == 'A'")
        assert func({"category": "A"}) is True
        assert func({"category": "B"}) is False

    def test_parse_string_not_equal(self):
        """Test != with string."""
        func = _parse_condition("category != 'A'")
        assert func({"category": "B"}) is True
        assert func({"category": "A"}) is False

    def test_parse_invalid_condition(self):
        """Test invalid condition raises error."""
        with pytest.raises(ValueError):
            _parse_condition("invalid condition")


class TestExecuteFilter:
    """Test cases for _execute_filter function."""

    def test_filter_with_condition(self):
        """Test filter with condition."""
        dt = DataTransformer([
            {"score": 0.8, "text": "high"},
            {"score": 0.3, "text": "low"},
            {"score": 0.9, "text": "higher"},
        ])

        result = _execute_filter(dt, {"condition": "score > 0.5"})

        assert len(result) == 2
        assert all(item["score"] > 0.5 for item in result.data)

    def test_filter_with_field(self):
        """Test filter with field only (non-empty check)."""
        dt = DataTransformer([
            {"text": "hello"},
            {"text": ""},
            {"text": "world"},
        ])

        result = _execute_filter(dt, {"field": "text"})

        assert len(result) == 2

    def test_filter_no_condition_or_field(self):
        """Test filter without condition or field raises error."""
        dt = DataTransformer([{"text": "hello"}])

        with pytest.raises(ValueError):
            _execute_filter(dt, {})


class TestExecuteTransform:
    """Test cases for _execute_transform function."""

    def test_transform_with_preset(self):
        """Test transform with preset."""
        dt = DataTransformer([{"q": "问题", "a": "回答"}])

        result = _execute_transform(
            dt,
            {
                "preset": "openai_chat",
                "params": {"user_field": "q", "assistant_field": "a"},
            },
        )

        assert "messages" in result.data[0]

    def test_transform_missing_preset(self):
        """Test transform without preset raises error."""
        dt = DataTransformer([{"q": "问题", "a": "回答"}])

        with pytest.raises(ValueError):
            _execute_transform(dt, {})

    def test_transform_invalid_preset(self):
        """Test transform with invalid preset."""
        dt = DataTransformer([{"q": "问题", "a": "回答"}])

        with pytest.raises(ValueError):
            _execute_transform(dt, {"preset": "invalid_preset"})


class TestExecuteDedupe:
    """Test cases for _execute_dedupe function."""

    def test_dedupe_with_key(self):
        """Test dedupe with key."""
        dt = DataTransformer([
            {"text": "hello", "id": 1},
            {"text": "hello", "id": 2},
            {"text": "world", "id": 3},
        ])

        result = _execute_dedupe(dt, {"key": "text"})

        assert len(result) == 2

    def test_dedupe_similar(self):
        """Test dedupe with similarity."""
        dt = DataTransformer([
            {"text": "hello world", "id": 1},
            {"text": "hello there", "id": 2},
            {"text": "completely different", "id": 3},
        ])

        result = _execute_dedupe(dt, {"key": "text", "similar": 0.5})

        # 相似度去重会保留第一条
        assert len(result) <= 3

    def test_dedupe_similar_no_key(self):
        """Test similarity dedupe without key raises error."""
        dt = DataTransformer([{"text": "hello"}])

        with pytest.raises(ValueError):
            _execute_dedupe(dt, {"similar": 0.8})

    def test_dedupe_multi_field_key(self):
        """Test dedupe with comma-separated multi-field key."""
        dt = DataTransformer([
            {"a": 1, "b": 2, "value": "x"},
            {"a": 1, "b": 2, "value": "y"},
            {"a": 1, "b": 3, "value": "z"},
        ])

        result = _execute_dedupe(dt, {"key": "a,b"})

        assert len(result) == 2


class TestExecuteSample:
    """Test cases for _execute_sample function."""

    def test_sample_default(self):
        """Test sample with default num."""
        dt = DataTransformer([{"id": i} for i in range(100)])

        result = _execute_sample(dt, {})

        assert len(result) == 10

    def test_sample_with_num(self):
        """Test sample with specified num."""
        dt = DataTransformer([{"id": i} for i in range(100)])

        result = _execute_sample(dt, {"num": 20})

        assert len(result) == 20

    def test_sample_with_seed(self):
        """Test sample with seed is reproducible."""
        dt = DataTransformer([{"id": i} for i in range(100)])

        result1 = _execute_sample(dt, {"num": 10, "seed": 42})
        result2 = _execute_sample(dt, {"num": 10, "seed": 42})

        assert [r["id"] for r in result1.data] == [r["id"] for r in result2.data]


class TestExecuteHead:
    """Test cases for _execute_head function."""

    def test_head_default(self):
        """Test head with default num."""
        dt = DataTransformer([{"id": i} for i in range(100)])

        result = _execute_head(dt, {})

        assert len(result) == 10
        assert result.data[0]["id"] == 0

    def test_head_custom_num(self):
        """Test head with custom num."""
        dt = DataTransformer([{"id": i} for i in range(100)])

        result = _execute_head(dt, {"num": 5})

        assert len(result) == 5
        assert result.data[0]["id"] == 0


class TestExecuteTail:
    """Test cases for _execute_tail function."""

    def test_tail_default(self):
        """Test tail with default num."""
        dt = DataTransformer([{"id": i} for i in range(100)])

        result = _execute_tail(dt, {})

        assert len(result) == 10
        assert result.data[-1]["id"] == 99

    def test_tail_custom_num(self):
        """Test tail with custom num."""
        dt = DataTransformer([{"id": i} for i in range(100)])

        result = _execute_tail(dt, {"num": 5})

        assert len(result) == 5
        assert result.data[-1]["id"] == 99


class TestExecuteShuffle:
    """Test cases for _execute_shuffle function."""

    def test_shuffle(self):
        """Test shuffle operation."""
        dt = DataTransformer([{"id": i} for i in range(10)])

        result = _execute_shuffle(dt, {})

        assert len(result) == 10
        # 验证是不同的实例
        assert result is not dt

    def test_shuffle_with_seed(self):
        """Test shuffle with seed is reproducible."""
        dt = DataTransformer([{"id": i} for i in range(20)])

        result1 = _execute_shuffle(dt, {"seed": 42})
        dt2 = DataTransformer([{"id": i} for i in range(20)])
        result2 = _execute_shuffle(dt2, {"seed": 42})

        assert [r["id"] for r in result1.data] == [r["id"] for r in result2.data]


class TestExecuteSplit:
    """Test cases for _execute_split function."""

    def test_split_default(self):
        """Test split with default ratio."""
        dt = DataTransformer([{"id": i} for i in range(100)])

        result = _execute_split(dt, {})

        # 只返回 train 部分
        assert len(result) == 80

    def test_split_custom_ratio(self):
        """Test split with custom ratio."""
        dt = DataTransformer([{"id": i} for i in range(100)])

        result = _execute_split(dt, {"ratio": 0.5})

        assert len(result) == 50

    def test_split_with_seed(self):
        """Test split with seed is reproducible."""
        dt = DataTransformer([{"id": i} for i in range(100)])

        result1 = _execute_split(dt, {"ratio": 0.8, "seed": 42})
        dt2 = DataTransformer([{"id": i} for i in range(100)])
        result2 = _execute_split(dt2, {"ratio": 0.8, "seed": 42})

        assert [r["id"] for r in result1.data] == [r["id"] for r in result2.data]


class TestFormatStepDescription:
    """Test cases for _format_step_description function."""

    def test_format_filter(self):
        """Test formatting filter step."""
        desc = _format_step_description({"type": "filter", "condition": "score > 0.5"})
        assert "filter" in desc
        assert "score > 0.5" in desc

    def test_format_transform(self):
        """Test formatting transform step."""
        desc = _format_step_description({"type": "transform", "preset": "openai_chat"})
        assert "transform" in desc
        assert "openai_chat" in desc

    def test_format_dedupe(self):
        """Test formatting dedupe step."""
        desc = _format_step_description({"type": "dedupe", "key": "text"})
        assert "dedupe" in desc
        assert "text" in desc

    def test_format_dedupe_similar(self):
        """Test formatting dedupe step with similarity."""
        desc = _format_step_description({"type": "dedupe", "key": "text", "similar": 0.8})
        assert "相似度" in desc
        assert "0.8" in desc

    def test_format_sample(self):
        """Test formatting sample step."""
        desc = _format_step_description({"type": "sample", "num": 100})
        assert "sample" in desc
        assert "100" in desc

    def test_format_shuffle(self):
        """Test formatting shuffle step."""
        desc = _format_step_description({"type": "shuffle"})
        assert "shuffle" in desc

    def test_format_split(self):
        """Test formatting split step."""
        desc = _format_step_description({"type": "split", "ratio": 0.7})
        assert "split" in desc
        assert "0.7" in desc


class TestRunPipeline:
    """Test cases for run_pipeline function."""

    def test_run_pipeline_basic(self, tmp_path):
        """Test basic pipeline execution."""
        # 创建输入文件
        input_file = tmp_path / "input.jsonl"
        DataTransformer([
            {"score": 0.8, "text": "high"},
            {"score": 0.3, "text": "low"},
            {"score": 0.9, "text": "higher"},
        ]).save(str(input_file))

        # 创建配置文件
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text(f"""
version: "1.0"
seed: 42
input: {input_file}
output: {tmp_path}/output.jsonl
steps:
  - type: filter
    condition: "score > 0.5"
  - type: transform
    preset: openai_chat
    params:
      user_field: text
      assistant_field: text
""")

        # 执行 pipeline
        result = run_pipeline(str(config_file), verbose=False)

        assert len(result) == 2

    def test_run_pipeline_with_override(self, tmp_path):
        """Test pipeline with input/output override."""
        # 创建输入文件
        input_file = tmp_path / "data.jsonl"
        DataTransformer([{"text": "hello"}]).save(str(input_file))

        output_file = tmp_path / "result.jsonl"

        # 创建配置文件
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text("""
version: "1.0"
input: default.jsonl
output: default_output.jsonl
steps:
  - type: head
    num: 1
""")

        # 执行 pipeline，覆盖输入输出
        result = run_pipeline(
            str(config_file),
            input_file=str(input_file),
            output_file=str(output_file),
            verbose=False
        )

        assert len(result) == 1
        assert output_file.exists()

    def test_run_pipeline_no_input(self, tmp_path):
        """Test pipeline without input raises error."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text("""
version: "1.0"
steps: []
""")

        with pytest.raises(ValueError, match="未指定输入文件"):
            run_pipeline(str(config_file), verbose=False)

    def test_run_pipeline_invalid_step_type(self, tmp_path):
        """Test pipeline with invalid step type."""
        input_file = tmp_path / "input.jsonl"
        DataTransformer([{"text": "hello"}]).save(str(input_file))

        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text(f"""
version: "1.0"
input: {input_file}
steps:
  - type: invalid_type
""")

        with pytest.raises(ValueError, match="未知步骤类型"):
            run_pipeline(str(config_file), verbose=False)

    def test_run_pipeline_missing_type(self, tmp_path):
        """Test pipeline with step missing type."""
        input_file = tmp_path / "input.jsonl"
        DataTransformer([{"text": "hello"}]).save(str(input_file))

        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text(f"""
version: "1.0"
input: {input_file}
steps:
  - condition: "score > 0.5"
""")

        with pytest.raises(ValueError, match="未指定 type"):
            run_pipeline(str(config_file), verbose=False)


class TestValidatePipeline:
    """Test cases for validate_pipeline function."""

    def test_validate_valid_pipeline(self, tmp_path):
        """Test validating a valid pipeline."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text("""
version: "1.0"
steps:
  - type: filter
    condition: "score > 0.5"
  - type: transform
    preset: openai_chat
""")

        errors = validate_pipeline(str(config_file))

        assert errors == []

    def test_validate_missing_steps(self, tmp_path):
        """Test validating pipeline without steps."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text("""
version: "1.0"
""")

        errors = validate_pipeline(str(config_file))

        assert "缺少 steps 字段" in errors

    def test_validate_missing_step_type(self, tmp_path):
        """Test validating step without type."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text("""
version: "1.0"
steps:
  - condition: "score > 0.5"
""")

        errors = validate_pipeline(str(config_file))

        assert any("缺少 type" in e for e in errors)

    def test_validate_invalid_step_type(self, tmp_path):
        """Test validating step with invalid type."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text("""
version: "1.0"
steps:
  - type: invalid_type
""")

        errors = validate_pipeline(str(config_file))

        assert any("未知类型" in e for e in errors)

    def test_validate_transform_without_preset(self, tmp_path):
        """Test validating transform without preset."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text("""
version: "1.0"
steps:
  - type: transform
""")

        errors = validate_pipeline(str(config_file))

        assert any("preset" in e for e in errors)

    def test_validate_filter_without_condition(self, tmp_path):
        """Test validating filter without condition."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text("""
version: "1.0"
steps:
  - type: filter
""")

        errors = validate_pipeline(str(config_file))

        assert any("condition" in e or "field" in e for e in errors)

    def test_validate_invalid_yaml(self, tmp_path):
        """Test validating invalid YAML."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text("invalid: yaml: content:[")

        errors = validate_pipeline(str(config_file))

        assert len(errors) > 0


class TestGeneratePipelineTemplate:
    """Test cases for generate_pipeline_template function."""

    def test_generate_template_basic(self, tmp_path):
        """Test generating basic template."""
        input_file = tmp_path / "input.jsonl"
        DataTransformer([{"text": "hello"}]).save(str(input_file))

        output_file = tmp_path / "pipeline.yaml"

        result = generate_pipeline_template(str(input_file), str(output_file))

        assert result == str(output_file)
        assert output_file.exists()

        content = output_file.read_text()
        assert "version" in content
        assert "input" in content
        assert "steps" in content

    def test_generate_template_with_preset(self, tmp_path):
        """Test generating template with preset."""
        input_file = tmp_path / "input.jsonl"
        DataTransformer([{"text": "hello"}]).save(str(input_file))

        output_file = tmp_path / "pipeline.yaml"

        result = generate_pipeline_template(str(input_file), str(output_file), preset="alpaca")

        assert result == str(output_file)

        content = output_file.read_text()
        assert "alpaca" in content

    def test_generate_template_qa_fields(self, tmp_path):
        """Test generating template infers QA format."""
        input_file = tmp_path / "input.jsonl"
        DataTransformer([{"q": "question", "a": "answer"}]).save(str(input_file))

        output_file = tmp_path / "pipeline.yaml"

        result = generate_pipeline_template(str(input_file), str(output_file))

        content = output_file.read_text()
        assert "openai_chat" in content

    def test_generate_template_empty_file(self, tmp_path):
        """Test generating template with empty file raises error."""
        input_file = tmp_path / "empty.jsonl"
        input_file.write_text("")

        output_file = tmp_path / "pipeline.yaml"

        with pytest.raises(ValueError, match="输入文件为空"):
            generate_pipeline_template(str(input_file), str(output_file))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
