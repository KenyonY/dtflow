"""
Tests for CLI clean and dedupe commands.
"""

import pytest

from dtflow.cli.clean import _clean_data_single_pass, _parse_len_param, clean, dedupe
from dtflow.storage.io import load_data, save_data

# ============== Fixtures ==============


@pytest.fixture
def sample_data_file(tmp_path):
    """Create a sample dataset file."""
    data = [
        {"text": "Hello world", "score": 0.8, "category": "greeting"},
        {"text": "How are you?", "score": 0.9, "category": "question"},
        {"text": "  Needs trimming  ", "score": 0.7, "category": "test"},
        {"text": "", "score": 0.6, "category": "empty_text"},
        {"text": "Short", "score": None, "category": None},
        {"text": "Hello world", "score": 0.85, "category": "duplicate"},  # duplicate text
    ]
    filepath = tmp_path / "test_data.jsonl"
    save_data(data, str(filepath))
    return filepath, data


@pytest.fixture
def sample_nested_file(tmp_path):
    """Create a sample dataset with nested fields."""
    data = [
        {
            "id": 1,
            "meta": {"source": "web", "score": 0.9},
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi!"},
            ],
        },
        {
            "id": 2,
            "meta": {"source": "api", "score": 0.8},
            "messages": [{"role": "user", "content": "Hi"}],
        },
        {
            "id": 3,
            "meta": {"source": None, "score": 0.5},
            "messages": [
                {"role": "user", "content": "A"},
                {"role": "assistant", "content": "B"},
                {"role": "user", "content": "C"},
            ],
        },
    ]
    filepath = tmp_path / "test_nested.jsonl"
    save_data(data, str(filepath))
    return filepath, data


# ============== Clean Command Tests ==============


class TestCleanBasic:
    """Test basic clean functionality."""

    def test_clean_drop_empty(self, sample_data_file, tmp_path):
        """Test dropping empty records."""
        filepath, _ = sample_data_file
        output = tmp_path / "output.jsonl"

        clean(str(filepath), drop_empty="text", output=str(output))

        result = load_data(str(output))
        # Should remove the record with empty text
        for item in result:
            assert item["text"] != ""

    def test_clean_drop_empty_all_fields(self, sample_data_file, tmp_path):
        """Test dropping records with any empty field."""
        filepath, _ = sample_data_file
        output = tmp_path / "output.jsonl"

        # drop_empty="" means check all fields
        clean(str(filepath), drop_empty="", output=str(output))

        result = load_data(str(output))
        # Should remove records with any None or empty value
        for item in result:
            assert all(v is not None and v != "" for v in item.values())

    def test_clean_strip(self, sample_data_file, tmp_path):
        """Test stripping whitespace."""
        filepath, _ = sample_data_file
        output = tmp_path / "output.jsonl"

        clean(str(filepath), strip=True, output=str(output))

        result = load_data(str(output))
        # Find the item that had extra whitespace
        trimmed = [item for item in result if "Needs trimming" in item.get("text", "")]
        if trimmed:
            assert trimmed[0]["text"] == "Needs trimming"

    def test_clean_min_len(self, sample_data_file, tmp_path):
        """Test minimum length filtering."""
        filepath, _ = sample_data_file
        output = tmp_path / "output.jsonl"

        clean(str(filepath), min_len="text:10", output=str(output))

        result = load_data(str(output))
        for item in result:
            assert len(item["text"]) >= 10

    def test_clean_max_len(self, sample_data_file, tmp_path):
        """Test maximum length filtering."""
        filepath, _ = sample_data_file
        output = tmp_path / "output.jsonl"

        clean(str(filepath), max_len="text:10", output=str(output))

        result = load_data(str(output))
        for item in result:
            assert len(item["text"]) <= 10

    def test_clean_keep_fields(self, sample_data_file, tmp_path):
        """Test keeping only specified fields."""
        filepath, _ = sample_data_file
        output = tmp_path / "output.jsonl"

        clean(str(filepath), keep="text,category", output=str(output))

        result = load_data(str(output))
        for item in result:
            assert set(item.keys()) == {"text", "category"}

    def test_clean_drop_fields(self, sample_data_file, tmp_path):
        """Test dropping specified fields."""
        filepath, _ = sample_data_file
        output = tmp_path / "output.jsonl"

        clean(str(filepath), drop="score", output=str(output))

        result = load_data(str(output))
        for item in result:
            assert "score" not in item


# ============== Clean with Nested Fields Tests ==============


class TestCleanNested:
    """Test clean with nested field paths."""

    def test_clean_drop_empty_nested(self, sample_nested_file, tmp_path):
        """Test dropping records with empty nested field."""
        filepath, _ = sample_nested_file
        output = tmp_path / "output.jsonl"

        clean(str(filepath), drop_empty="meta.source", output=str(output))

        result = load_data(str(output))
        assert len(result) == 2  # Should remove the one with None source
        for item in result:
            assert item["meta"]["source"] is not None

    def test_clean_min_len_messages(self, sample_nested_file, tmp_path):
        """Test filtering by message count using .# syntax."""
        filepath, _ = sample_nested_file
        output = tmp_path / "output.jsonl"

        clean(str(filepath), min_len="messages.#:2", output=str(output))

        result = load_data(str(output))
        for item in result:
            assert len(item["messages"]) >= 2


# ============== Dedupe Command Tests ==============


class TestDedupeBasic:
    """Test basic dedupe functionality."""

    def test_dedupe_by_field(self, sample_data_file, tmp_path):
        """Test deduplication by specific field."""
        filepath, _ = sample_data_file
        output = tmp_path / "output.jsonl"

        dedupe(str(filepath), key="text", output=str(output))

        result = load_data(str(output))
        # Should have removed the duplicate "Hello world"
        texts = [item["text"] for item in result]
        assert len(texts) == len(set(texts))

    def test_dedupe_full(self, sample_data_file, tmp_path):
        """Test full record deduplication."""
        filepath, _ = sample_data_file
        output = tmp_path / "output.jsonl"

        dedupe(str(filepath), output=str(output))

        result = load_data(str(output))
        # All records are unique, so should have same count
        # (unless there are exact duplicates)
        assert len(result) >= 1

    def test_dedupe_overwrite(self, sample_data_file):
        """Test deduplication with overwrite (no output specified)."""
        filepath, original_data = sample_data_file

        dedupe(str(filepath), key="text")

        result = load_data(str(filepath))
        texts = [item["text"] for item in result]
        assert len(texts) == len(set(texts))


# ============== Parameter Parsing Tests ==============


class TestParamParsing:
    """Test parameter parsing functions."""

    def test_parse_len_param_valid(self):
        """Test valid length parameter parsing."""
        field, value = _parse_len_param("text:100")
        assert field == "text"
        assert value == 100

    def test_parse_len_param_nested(self):
        """Test nested field length parameter."""
        field, value = _parse_len_param("messages.#:5")
        assert field == "messages.#"
        assert value == 5

    def test_parse_len_param_invalid_no_colon(self):
        """Test invalid parameter without colon."""
        with pytest.raises(ValueError):
            _parse_len_param("text100")

    def test_parse_len_param_invalid_non_numeric(self):
        """Test invalid parameter with non-numeric value."""
        with pytest.raises(ValueError):
            _parse_len_param("text:abc")


# ============== Clean Single Pass Tests ==============


class TestCleanSinglePass:
    """Test _clean_data_single_pass function."""

    def test_single_pass_strip(self):
        """Test strip in single pass."""
        data = [{"text": "  hello  ", "value": " world "}]
        result, _ = _clean_data_single_pass(data, strip=True)

        assert result[0]["text"] == "hello"
        assert result[0]["value"] == "world"

    def test_single_pass_drop_empty(self):
        """Test drop empty in single pass."""
        data = [
            {"text": "hello", "value": "world"},
            {"text": "", "value": "test"},
            {"text": "hi", "value": None},
        ]
        result, stats = _clean_data_single_pass(data, empty_fields=["text", "value"])

        assert len(result) == 1
        assert result[0]["text"] == "hello"

    def test_single_pass_combined(self):
        """Test combined operations in single pass."""
        data = [
            {"text": "  long text here  ", "score": 0.9},
            {"text": "  hi  ", "score": 0.8},
        ]
        result, stats = _clean_data_single_pass(
            data, strip=True, min_len_field="text", min_len_value=5
        )

        assert len(result) == 1
        assert result[0]["text"] == "long text here"


# ============== Error Handling Tests ==============


class TestCleanErrors:
    """Test error handling in clean commands."""

    def test_clean_file_not_exists(self, tmp_path, capsys):
        """Test error when file doesn't exist."""
        clean(str(tmp_path / "nonexistent.jsonl"))
        captured = capsys.readouterr()
        assert "文件不存在" in captured.out

    def test_dedupe_similar_without_key(self, sample_data_file, capsys):
        """Test error when using similar without key."""
        filepath, _ = sample_data_file
        dedupe(str(filepath), similar=0.8)
        captured = capsys.readouterr()
        assert "需要指定 --key" in captured.out

    def test_dedupe_invalid_similar_range(self, sample_data_file, capsys):
        """Test error when similar value is out of range."""
        filepath, _ = sample_data_file
        dedupe(str(filepath), key="text", similar=1.5)
        captured = capsys.readouterr()
        assert "0-1 之间" in captured.out
