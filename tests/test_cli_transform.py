"""
Tests for CLI transform command.
"""

import pytest

from dtflow.cli.transform import (
    _build_config_content,
    _format_example_value,
    _generate_fields_definition,
    _get_type_name,
    _sanitize_field_name,
    transform,
)
from dtflow.storage.io import load_data, save_data

# ============== Fixtures ==============


@pytest.fixture
def sample_qa_file(tmp_path):
    """Create a sample QA dataset file."""
    data = [
        {"question": "What is AI?", "answer": "AI is artificial intelligence."},
        {"question": "What is ML?", "answer": "ML is machine learning."},
        {"question": "What is DL?", "answer": "DL is deep learning."},
    ]
    filepath = tmp_path / "test_qa.jsonl"
    save_data(data, str(filepath))
    return filepath, data


@pytest.fixture
def sample_nested_file(tmp_path):
    """Create a sample dataset with nested fields."""
    data = [
        {
            "id": 1,
            "meta": {"source": "web"},
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
            ],
        },
        {
            "id": 2,
            "meta": {"source": "api"},
            "messages": [
                {"role": "user", "content": "What is Python?"},
                {"role": "assistant", "content": "A programming language."},
            ],
        },
    ]
    filepath = tmp_path / "test_nested.jsonl"
    save_data(data, str(filepath))
    return filepath, data


# ============== Preset Transform Tests ==============


class TestPresetTransform:
    """Test preset-based transformation."""

    def test_transform_preset_openai_chat(self, sample_qa_file, tmp_path):
        """Test transformation with openai_chat preset."""
        filepath, _ = sample_qa_file
        output = tmp_path / "output.jsonl"

        transform(
            str(filepath),
            preset="openai_chat",
            output=str(output),
        )

        result = load_data(str(output))
        assert len(result) == 3
        assert "messages" in result[0]
        assert len(result[0]["messages"]) == 2
        assert result[0]["messages"][0]["role"] == "user"
        assert result[0]["messages"][1]["role"] == "assistant"

    def test_transform_preset_alpaca(self, sample_qa_file, tmp_path):
        """Test transformation with alpaca preset."""
        filepath, data = sample_qa_file
        output = tmp_path / "output.jsonl"

        # Create a file with instruction/input/output fields
        alpaca_data = [
            {"instruction": "What is AI?", "input": "", "output": "AI is artificial intelligence."},
            {"instruction": "What is ML?", "input": "", "output": "ML is machine learning."},
        ]
        alpaca_file = tmp_path / "alpaca_input.jsonl"
        save_data(alpaca_data, str(alpaca_file))

        transform(str(alpaca_file), preset="alpaca", output=str(output))

        result = load_data(str(output))
        assert len(result) == 2
        assert "instruction" in result[0]
        assert "input" in result[0]
        assert "output" in result[0]

    def test_transform_preset_with_num(self, sample_qa_file, tmp_path):
        """Test transformation with num parameter."""
        filepath, _ = sample_qa_file
        output = tmp_path / "output.jsonl"

        transform(str(filepath), num=2, preset="openai_chat", output=str(output))

        result = load_data(str(output))
        assert len(result) == 2

    def test_transform_invalid_preset(self, sample_qa_file, capsys):
        """Test error with invalid preset name."""
        filepath, _ = sample_qa_file
        transform(str(filepath), preset="invalid_preset")

        captured = capsys.readouterr()
        assert "未知预设" in captured.out or "错误" in captured.out


# ============== Config Generation Tests ==============


class TestConfigGeneration:
    """Test configuration file generation."""

    def test_generate_config(self, sample_qa_file, capsys):
        """Test config file generation on first run."""
        filepath, _ = sample_qa_file

        # First run should generate config
        transform(str(filepath))

        captured = capsys.readouterr()
        assert "生成配置文件" in captured.out

        # Config file should exist
        config_path = filepath.parent / ".dt" / f"{filepath.stem}.py"
        assert config_path.exists()

        # Config should contain transform function
        content = config_path.read_text()
        assert "def transform" in content
        assert "class Item" in content

    def test_build_config_content(self):
        """Test _build_config_content function."""
        sample = {"question": "What is AI?", "answer": "AI is..."}
        content = _build_config_content(sample, "test.jsonl", 100)

        assert "class Item:" in content
        assert "def transform" in content
        assert "question" in content
        assert "answer" in content

    def test_generate_fields_definition(self):
        """Test _generate_fields_definition function."""
        sample = {
            "text": "Hello",
            "score": 0.9,
            "count": 10,
            "tags": ["a", "b"],
        }
        fields_def = _generate_fields_definition(sample)

        assert "text: str" in fields_def
        assert "score: float" in fields_def
        assert "count: int" in fields_def
        assert "tags: list" in fields_def


# ============== Type Detection Tests ==============


class TestTypeDetection:
    """Test type detection utilities."""

    def test_get_type_name_str(self):
        """Test string type detection."""
        assert _get_type_name("hello") == "str"

    def test_get_type_name_int(self):
        """Test int type detection."""
        assert _get_type_name(42) == "int"

    def test_get_type_name_float(self):
        """Test float type detection."""
        assert _get_type_name(3.14) == "float"

    def test_get_type_name_bool(self):
        """Test bool type detection."""
        assert _get_type_name(True) == "bool"
        assert _get_type_name(False) == "bool"

    def test_get_type_name_list(self):
        """Test list type detection."""
        assert _get_type_name([1, 2, 3]) == "list"

    def test_get_type_name_dict(self):
        """Test dict type detection."""
        assert _get_type_name({"a": 1}) == "dict"

    def test_get_type_name_none(self):
        """Test None type detection (defaults to str)."""
        assert _get_type_name(None) == "str"


# ============== Field Name Sanitization Tests ==============


class TestSanitizeFieldName:
    """Test field name sanitization."""

    def test_sanitize_valid_name(self):
        """Test valid field name passes through."""
        name, changed = _sanitize_field_name("valid_name")
        assert name == "valid_name"
        assert changed is False

    def test_sanitize_hyphen(self):
        """Test hyphen replacement."""
        name, changed = _sanitize_field_name("field-name")
        assert name == "field_name"
        assert changed is True

    def test_sanitize_space(self):
        """Test space replacement."""
        name, changed = _sanitize_field_name("field name")
        assert name == "field_name"
        assert changed is True

    def test_sanitize_number_prefix(self):
        """Test number prefix handling."""
        name, changed = _sanitize_field_name("123field")
        assert name.startswith("f_")
        assert changed is True

    def test_sanitize_dot(self):
        """Test dot replacement."""
        name, changed = _sanitize_field_name("field.name")
        assert name == "field_name"
        assert changed is True


# ============== Example Value Formatting Tests ==============


class TestFormatExampleValue:
    """Test example value formatting."""

    def test_format_string(self):
        """Test string formatting."""
        result = _format_example_value("hello")
        assert result == "'hello'"

    def test_format_int(self):
        """Test int formatting."""
        result = _format_example_value(42)
        assert result == "42"

    def test_format_float(self):
        """Test float formatting."""
        result = _format_example_value(3.14)
        assert result == "3.14"

    def test_format_bool(self):
        """Test bool formatting."""
        assert _format_example_value(True) == "True"
        assert _format_example_value(False) == "False"

    def test_format_none(self):
        """Test None formatting."""
        result = _format_example_value(None)
        assert result == '""'

    def test_format_long_string_truncated(self):
        """Test long string truncation."""
        long_string = "a" * 100
        result = _format_example_value(long_string, max_len=50)
        assert "..." in result


# ============== Error Handling Tests ==============


class TestTransformErrors:
    """Test error handling in transform command."""

    def test_file_not_exists(self, tmp_path, capsys):
        """Test error when file doesn't exist."""
        transform(str(tmp_path / "nonexistent.jsonl"))
        captured = capsys.readouterr()
        assert "文件不存在" in captured.out

    def test_empty_file(self, tmp_path, capsys):
        """Test error when file is empty."""
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("")

        transform(str(empty_file))
        captured = capsys.readouterr()
        assert "文件为空" in captured.out or "错误" in captured.out
