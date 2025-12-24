"""
Tests for storage/io module.
"""
import tempfile
from pathlib import Path

import pytest

from dtflow.storage.io import (
    _deserialize_complex_fields,
    _serialize_complex_fields,
    _stream_head_csv,
    _stream_head_jsonl,
    _stream_head_parquet,
    _stream_tail_csv,
    _stream_tail_jsonl,
    _stream_tail_parquet,
    append_to_file,
    count_lines,
    load_data,
    sample_data,
    sample_file,
    save_data,
    stream_jsonl,
)


class TestDetectFormat:
    """Test cases for file format detection."""

    def test_detect_jsonl(self):
        """Test JSONL format detection."""
        from dtflow.storage.io import _detect_format

        assert _detect_format(Path("data.jsonl")) == "jsonl"

    def test_detect_json(self):
        """Test JSON format detection."""
        from dtflow.storage.io import _detect_format

        assert _detect_format(Path("data.json")) == "json"

    def test_detect_csv(self):
        """Test CSV format detection."""
        from dtflow.storage.io import _detect_format

        assert _detect_format(Path("data.csv")) == "csv"

    def test_detect_parquet(self):
        """Test Parquet format detection."""
        from dtflow.storage.io import _detect_format

        assert _detect_format(Path("data.parquet")) == "parquet"

    def test_detect_arrow(self):
        """Test Arrow format detection."""
        from dtflow.storage.io import _detect_format

        assert _detect_format(Path("data.arrow")) == "arrow"
        assert _detect_format(Path("data.feather")) == "arrow"

    def test_detect_excel(self):
        """Test Excel format detection."""
        from dtflow.storage.io import _detect_format

        assert _detect_format(Path("data.xlsx")) == "excel"
        assert _detect_format(Path("data.xls")) == "excel"

    def test_detect_default(self):
        """Test default to JSONL for unknown extensions."""
        from dtflow.storage.io import _detect_format

        assert _detect_format(Path("data.unknown")) == "jsonl"


class TestSaveLoadJsonl:
    """Test cases for JSONL format save/load."""

    def test_save_and_load_jsonl(self, tmp_path):
        """Test saving and loading JSONL."""
        data = [
            {"text": "hello", "score": 0.8},
            {"text": "world", "score": 0.9},
        ]

        filepath = tmp_path / "data.jsonl"
        save_data(data, str(filepath))

        loaded = load_data(str(filepath))

        assert len(loaded) == 2
        assert loaded[0]["text"] == "hello"
        assert loaded[1]["score"] == 0.9

    def test_save_jsonl_creates_dirs(self, tmp_path):
        """Test that save creates parent directories."""
        data = [{"text": "hello"}]

        filepath = tmp_path / "subdir" / "nested" / "data.jsonl"
        save_data(data, str(filepath))

        assert filepath.exists()
        assert load_data(str(filepath))[0]["text"] == "hello"

    def test_save_load_jsonl_nested_data(self, tmp_path):
        """Test saving and loading nested structures."""
        data = [
            {"text": "hello", "meta": {"count": 5, "tags": ["a", "b"]}},
        ]

        filepath = tmp_path / "nested.jsonl"
        save_data(data, str(filepath))
        loaded = load_data(str(filepath))

        assert loaded[0]["meta"]["count"] == 5
        assert loaded[0]["meta"]["tags"] == ["a", "b"]

    def test_load_jsonl_empty_lines(self, tmp_path):
        """Test loading JSONL with empty lines."""
        filepath = tmp_path / "data.jsonl"
        filepath.write_text('{"a": 1}\n\n{"b": 2}\n\n')

        loaded = load_data(str(filepath))

        assert len(loaded) == 2


class TestSaveLoadJson:
    """Test cases for JSON format save/load."""

    def test_save_and_load_json(self, tmp_path):
        """Test saving and loading JSON."""
        data = [
            {"text": "hello", "score": 0.8},
            {"text": "world", "score": 0.9},
        ]

        filepath = tmp_path / "data.json"
        save_data(data, str(filepath))

        loaded = load_data(str(filepath))

        assert len(loaded) == 2
        assert loaded[0]["text"] == "hello"

    def test_load_json_single_object(self, tmp_path):
        """Test loading JSON with single object (not list)."""
        filepath = tmp_path / "single.json"
        filepath.write_text('{"text": "hello", "score": 0.8}')

        loaded = load_data(str(filepath))

        assert len(loaded) == 1
        assert loaded[0]["text"] == "hello"


class TestSaveLoadCsv:
    """Test cases for CSV format save/load."""

    def test_save_and_load_csv(self, tmp_path):
        """Test saving and loading CSV."""
        data = [
            {"text": "hello", "score": 0.8},
            {"text": "world", "score": 0.9},
        ]

        filepath = tmp_path / "data.csv"
        save_data(data, str(filepath))

        loaded = load_data(str(filepath))

        assert len(loaded) == 2
        assert loaded[0]["text"] == "hello"
        # Polars 将字符串读取为字符串
        assert float(loaded[0]["score"]) == 0.8

    def test_save_empty_csv(self, tmp_path):
        """Test saving empty CSV."""
        filepath = tmp_path / "empty.csv"
        save_data([], str(filepath))

        # 文件应该存在
        assert filepath.exists()


class TestSaveLoadParquet:
    """Test cases for Parquet format save/load."""

    def test_save_and_load_parquet(self, tmp_path):
        """Test saving and loading Parquet."""
        data = [
            {"text": "hello", "score": 0.8},
            {"text": "world", "score": 0.9},
        ]

        filepath = tmp_path / "data.parquet"
        save_data(data, str(filepath))

        loaded = load_data(str(filepath))

        assert len(loaded) == 2
        assert loaded[0]["text"] == "hello"

    def test_save_empty_parquet(self, tmp_path):
        """Test saving empty Parquet."""
        filepath = tmp_path / "empty.parquet"
        save_data([], str(filepath))

        assert filepath.exists()


class TestSaveLoadArrow:
    """Test cases for Arrow format save/load."""

    def test_save_and_load_arrow(self, tmp_path):
        """Test saving and loading Arrow."""
        data = [
            {"text": "hello", "score": 0.8},
            {"text": "world", "score": 0.9},
        ]

        filepath = tmp_path / "data.arrow"
        save_data(data, str(filepath))

        loaded = load_data(str(filepath))

        assert len(loaded) == 2
        assert loaded[0]["text"] == "hello"

    def test_save_and_load_feather(self, tmp_path):
        """Test saving and loading Feather (Arrow alias)."""
        data = [{"text": "hello", "score": 0.8}]

        filepath = tmp_path / "data.feather"
        save_data(data, str(filepath))

        loaded = load_data(str(filepath))

        assert len(loaded) == 1


class TestSerializeDeserialize:
    """Test cases for complex field serialization."""

    def test_serialize_list_field(self):
        """Test serializing list field."""
        data = [{"text": "hello", "tags": ["a", "b", "c"]}]
        result = _serialize_complex_fields(data)

        assert result[0]["tags"] == '["a","b","c"]'

    def test_serialize_dict_field(self):
        """Test serializing dict field."""
        data = [{"text": "hello", "meta": {"count": 5}}]
        result = _serialize_complex_fields(data)

        assert result[0]["meta"] == '{"count":5}'

    def test_serialize_nested_complex(self):
        """Test serializing nested complex structures."""
        data = [{"list_of_dicts": [{"a": 1}, {"b": 2}]}]
        result = _serialize_complex_fields(data)

        assert isinstance(result[0]["list_of_dicts"], str)

    def test_preserve_simple_types(self):
        """Test that simple types are preserved."""
        data = [
            {"str": "text", "int": 42, "float": 3.14, "bool": True, "none": None}
        ]
        result = _serialize_complex_fields(data)

        assert result[0]["str"] == "text"
        assert result[0]["int"] == 42
        assert result[0]["float"] == 3.14
        assert result[0]["bool"] is True
        assert result[0]["none"] is None

    def test_deserialize_list_field(self):
        """Test deserializing list field."""
        data = [{"tags": '["a","b","c"]'}]
        result = _deserialize_complex_fields(data)

        assert result[0]["tags"] == ["a", "b", "c"]

    def test_deserialize_dict_field(self):
        """Test deserializing dict field."""
        data = [{"meta": '{"count":5}'}]
        result = _deserialize_complex_fields(data)

        assert result[0]["meta"] == {"count": 5}

    def test_deserialize_invalid_json(self):
        """Test that invalid JSON strings are preserved."""
        data = [{"text": '[not valid json]'}]
        result = _deserialize_complex_fields(data)

        # 应该保持原样
        assert result[0]["text"] == '[not valid json]'

    def test_deserialize_preserve_simple_types(self):
        """Test that simple types are preserved."""
        data = [{"str": "text", "int": 42, "bool": True}]
        result = _deserialize_complex_fields(data)

        assert result[0]["str"] == "text"
        assert result[0]["int"] == 42
        assert result[0]["bool"] is True


class TestSampleData:
    """Test cases for sample_data function."""

    def test_sample_head(self):
        """Test head sampling."""
        data = [{"id": i} for i in range(100)]

        result = sample_data(data, num=10, sample_type="head")

        assert len(result) == 10
        assert result[0]["id"] == 0

    def test_sample_tail(self):
        """Test tail sampling."""
        data = [{"id": i} for i in range(100)]

        result = sample_data(data, num=10, sample_type="tail")

        assert len(result) == 10
        assert result[-1]["id"] == 99

    def test_sample_random(self):
        """Test random sampling."""
        data = [{"id": i} for i in range(100)]

        result = sample_data(data, num=10, sample_type="random", seed=42)

        assert len(result) == 10

    def test_sample_random_reproducible(self):
        """Test that random sampling is reproducible with seed."""
        data = [{"id": i} for i in range(100)]

        result1 = sample_data(data, num=10, sample_type="random", seed=42)
        result2 = sample_data(data, num=10, sample_type="random", seed=42)

        assert result1 == result2

    def test_sample_num_larger_than_data(self):
        """Test sampling when num > data length."""
        data = [{"id": i} for i in range(10)]

        result = sample_data(data, num=100, sample_type="head")

        assert len(result) == 10

    def test_sample_zero_num(self):
        """Test sampling with num=0 returns all."""
        data = [{"id": i} for i in range(10)]

        result = sample_data(data, num=0, sample_type="head")

        assert len(result) == 10

    def test_sample_negative_num(self):
        """Test sampling with negative num."""
        data = [{"id": i} for i in range(100)]

        # 负数会被取绝对值
        result = sample_data(data, num=-10, sample_type="head")

        assert len(result) == 10

    def test_sample_empty_data(self):
        """Test sampling empty data."""
        result = sample_data([], num=10, sample_type="head")

        assert result == []


class TestSampleFile:
    """Test cases for sample_file function."""

    def test_sample_file_jsonl_head(self, tmp_path):
        """Test sampling JSONL file with head."""
        data = [{"id": i, "value": f"item_{i}"} for i in range(100)]

        filepath = tmp_path / "data.jsonl"
        save_data(data, str(filepath))

        result = sample_file(str(filepath), num=10, sample_type="head")

        assert len(result) == 10
        assert result[0]["id"] == 0

    def test_sample_file_jsonl_tail(self, tmp_path):
        """Test sampling JSONL file with tail."""
        data = [{"id": i} for i in range(100)]

        filepath = tmp_path / "data.jsonl"
        save_data(data, str(filepath))

        result = sample_file(str(filepath), num=10, sample_type="tail")

        assert len(result) == 10
        assert result[-1]["id"] == 99

    def test_sample_file_jsonl_random(self, tmp_path):
        """Test sampling JSONL file with random."""
        data = [{"id": i} for i in range(100)]

        filepath = tmp_path / "data.jsonl"
        save_data(data, str(filepath))

        result = sample_file(str(filepath), num=10, sample_type="random", seed=42)

        assert len(result) == 10

    def test_sample_file_with_output(self, tmp_path):
        """Test sampling file with output parameter."""
        data = [{"id": i} for i in range(100)]

        filepath = tmp_path / "data.jsonl"
        save_data(data, str(filepath))

        output_path = tmp_path / "sampled.jsonl"
        result = sample_file(str(filepath), num=10, sample_type="head", output=str(output_path))

        assert output_path.exists()
        assert len(result) == 10


class TestStreamHelpers:
    """Test cases for streaming helper functions."""

    def test_stream_head_jsonl(self, tmp_path):
        """Test streaming head from JSONL."""
        data = [{"id": i} for i in range(100)]

        filepath = tmp_path / "data.jsonl"
        save_data(data, str(filepath))

        result = _stream_head_jsonl(filepath, 10)

        assert len(result) == 10
        assert result[0]["id"] == 0

    def test_stream_tail_jsonl(self, tmp_path):
        """Test streaming tail from JSONL."""
        data = [{"id": i} for i in range(100)]

        filepath = tmp_path / "data.jsonl"
        save_data(data, str(filepath))

        result = _stream_tail_jsonl(filepath, 10)

        assert len(result) == 10
        assert result[-1]["id"] == 99

    def test_stream_head_csv(self, tmp_path):
        """Test streaming head from CSV."""
        data = [{"id": i, "value": f"item_{i}"} for i in range(100)]

        filepath = tmp_path / "data.csv"
        save_data(data, str(filepath))

        result = _stream_head_csv(filepath, 10)

        assert len(result) == 10

    def test_stream_tail_csv(self, tmp_path):
        """Test streaming tail from CSV."""
        data = [{"id": i, "value": f"item_{i}"} for i in range(100)]

        filepath = tmp_path / "data.csv"
        save_data(data, str(filepath))

        result = _stream_tail_csv(filepath, 10)

        assert len(result) == 10

    def test_stream_head_parquet(self, tmp_path):
        """Test streaming head from Parquet."""
        data = [{"id": i, "value": f"item_{i}"} for i in range(100)]

        filepath = tmp_path / "data.parquet"
        save_data(data, str(filepath))

        result = _stream_head_parquet(filepath, 10)

        assert len(result) == 10

    def test_stream_tail_parquet(self, tmp_path):
        """Test streaming tail from Parquet."""
        data = [{"id": i, "value": f"item_{i}"} for i in range(100)]

        filepath = tmp_path / "data.parquet"
        save_data(data, str(filepath))

        result = _stream_tail_parquet(filepath, 10)

        assert len(result) == 10


class TestUtilities:
    """Test cases for utility functions."""

    def test_append_to_file(self, tmp_path):
        """Test appending data to JSONL file."""
        filepath = tmp_path / "data.jsonl"

        # 初始保存
        data1 = [{"id": 1}, {"id": 2}]
        save_data(data1, str(filepath))

        # 追加
        data2 = [{"id": 3}, {"id": 4}]
        append_to_file(data2, str(filepath))

        # 验证
        loaded = load_data(str(filepath))
        assert len(loaded) == 4
        assert loaded[-1]["id"] == 4

    def test_append_to_file_non_jsonl_raises(self, tmp_path):
        """Test append_to_file raises error for non-JSONL."""
        with pytest.raises(ValueError, match="Only JSONL"):
            append_to_file([{"id": 1}], str(tmp_path / "data.csv"), file_format="csv")

    def test_count_lines(self, tmp_path):
        """Test counting lines in JSONL file."""
        filepath = tmp_path / "data.jsonl"
        filepath.write_text('{"a": 1}\n{"b": 2}\n{"c": 3}\n')

        count = count_lines(str(filepath))

        assert count == 3

    def test_stream_jsonl(self, tmp_path):
        """Test streaming JSONL in chunks."""
        data = [{"id": i} for i in range(25)]

        filepath = tmp_path / "data.jsonl"
        save_data(data, str(filepath))

        chunks = list(stream_jsonl(str(filepath), chunk_size=10))

        assert len(chunks) == 3
        assert len(chunks[0]) == 10
        assert len(chunks[1]) == 10
        assert len(chunks[2]) == 5


class TestLoadErrors:
    """Test cases for load error handling."""

    def test_load_file_not_found(self):
        """Test loading non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            load_data("/nonexistent/path/file.jsonl")

    def test_load_unsupported_format(self, tmp_path):
        """Test loading unsupported format."""
        filepath = tmp_path / "data.unknown_format"
        filepath.write_text("some data")

        # 应该回退到 jsonl 解析，然后失败
        # 或者返回空结果（取决于实现）


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
