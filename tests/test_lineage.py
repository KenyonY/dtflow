"""
Tests for lineage module.
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

from dtflow.lineage import (
    LineageRecord,
    LineageTracker,
    delete_lineage,
    format_lineage_report,
    get_lineage_chain,
    has_lineage,
    load_lineage,
    LINEAGE_SUFFIX,
)


class TestLineageRecord:
    """Test cases for LineageRecord class."""

    def test_init_default(self):
        """Test default initialization."""
        record = LineageRecord()
        assert record.version == "1.0"
        assert record.created_at is not None
        assert record.source is None
        assert record.operations == []
        assert record.metadata == {}
        assert "python_version" in record.environment

    def test_init_with_params(self):
        """Test initialization with parameters."""
        record = LineageRecord(
            source="data.jsonl",
            operations=[{"type": "filter"}],
            metadata={"key": "value"}
        )
        assert record.source == "data.jsonl"
        assert len(record.operations) == 1
        assert record.metadata == {"key": "value"}

    def test_add_operation(self):
        """Test adding operations."""
        record = LineageRecord()
        record.add_operation("filter", params={"threshold": 0.5}, input_count=100, output_count=80)

        assert len(record.operations) == 1
        assert record.operations[0]["type"] == "filter"
        assert record.operations[0]["params"]["threshold"] == 0.5
        assert record.operations[0]["input_count"] == 100
        assert record.operations[0]["output_count"] == 80

    def test_add_operation_chained(self):
        """Test chaining add_operation."""
        record = LineageRecord()
        record.add_operation("filter").add_operation("transform").add_operation("dedupe")

        assert len(record.operations) == 3
        assert record.operations[0]["type"] == "filter"
        assert record.operations[1]["type"] == "transform"
        assert record.operations[2]["type"] == "dedupe"

    def test_to_dict(self):
        """Test conversion to dictionary."""
        record = LineageRecord(source="input.jsonl")
        record.add_operation("filter")

        data = record.to_dict()

        assert data["version"] == "1.0"
        assert data["source"] == "input.jsonl"
        assert len(data["operations"]) == 1
        assert "environment" in data

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "version": "1.0",
            "created_at": "2024-01-01T00:00:00",
            "source": "test.jsonl",
            "operations": [{"type": "filter"}],
            "metadata": {},
            "environment": {},
        }

        record = LineageRecord.from_dict(data)

        assert record.version == "1.0"
        assert record.source == "test.jsonl"
        assert len(record.operations) == 1


class TestLineageTracker:
    """Test cases for LineageTracker class."""

    def test_init_no_source(self):
        """Test initialization without source."""
        tracker = LineageTracker()
        assert tracker.source_path is None
        assert tracker.source_lineage is None
        assert tracker.operations == []

    def test_init_with_source(self):
        """Test initialization with source path."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            f.write(b'{"text": "hello"}\n')
            source_path = f.name

        try:
            tracker = LineageTracker(source_path)
            assert tracker.source_path == source_path
            assert tracker.source_lineage is None
        finally:
            os.unlink(source_path)

    def test_init_with_existing_lineage(self):
        """Test initialization with file that has lineage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "source.jsonl"
            source_path.write_text('{"text": "hello"}\n')

            # 创建血缘文件
            lineage_path = Path(str(source_path) + LINEAGE_SUFFIX)
            lineage_data = {
                "version": "1.0",
                "created_at": "2024-01-01T00:00:00",
                "source": None,
                "operations": [{"type": "filter"}],
                "metadata": {},
                "environment": {},
            }
            lineage_path.write_text(json.dumps(lineage_data))

            tracker = LineageTracker(str(source_path))

            assert tracker.source_lineage is not None
            assert tracker.source_lineage.operations[0]["type"] == "filter"

    def test_record_operation(self):
        """Test recording an operation."""
        tracker = LineageTracker()
        tracker.record("filter", params={"score": 0.5}, input_count=100, output_count=80)

        assert len(tracker.operations) == 1
        assert tracker.operations[0]["type"] == "filter"
        assert tracker.operations[0]["params"]["score"] == 0.5

    def test_record_chained(self):
        """Test chaining record calls."""
        tracker = LineageTracker()
        tracker.record("filter").record("transform").record("dedupe")

        assert len(tracker.operations) == 3

    def test_build_record(self):
        """Test building final lineage record."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            source_path = f.name
            f.write(b'{"text": "hello"}\n')

        try:
            tracker = LineageTracker(source_path)
            tracker.record("filter", input_count=100, output_count=80)

            record = tracker.build_record("output.jsonl", 80)

            assert record.source["path"] == source_path
            assert record.source["hash"] is not None
            assert record.metadata["output_path"] == "output.jsonl"
            assert record.metadata["output_count"] == 80
            assert len(record.operations) == 1
        finally:
            os.unlink(source_path)

    def test_save(self):
        """Test saving lineage to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "source.jsonl"
            source_path.write_text('{"text": "hello"}\n')

            output_path = Path(tmpdir) / "output.jsonl"

            tracker = LineageTracker(str(source_path))
            tracker.record("filter", input_count=100, output_count=80)

            lineage_path = tracker.save(str(output_path), 80)

            assert os.path.exists(lineage_path)
            assert lineage_path == str(output_path) + LINEAGE_SUFFIX

            # 验证内容
            loaded = load_lineage(str(output_path))
            assert loaded is not None
            assert loaded.operations[0]["input_count"] == 100


class TestLineageFunctions:
    """Test cases for lineage module functions."""

    def test_load_lineage_no_file(self):
        """Test loading lineage when file doesn't exist."""
        result = load_lineage("/nonexistent/file.jsonl")
        assert result is None

    def test_load_lineage_existing(self):
        """Test loading existing lineage file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "data.jsonl"
            data_path.write_text('{"text": "hello"}\n')

            lineage_path = Path(str(data_path) + LINEAGE_SUFFIX)
            lineage_data = {
                "version": "1.0",
                "created_at": "2024-01-01T00:00:00",
                "source": "original.jsonl",
                "operations": [{"type": "filter"}],
                "metadata": {},
                "environment": {},
            }
            lineage_path.write_text(json.dumps(lineage_data))

            record = load_lineage(str(data_path))

            assert record is not None
            assert record.source == "original.jsonl"
            assert record.operations[0]["type"] == "filter"

    def test_has_lineage(self):
        """Test has_lineage function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "data.jsonl"
            data_path.write_text('{"text": "hello"}\n')

            assert not has_lineage(str(data_path))

            lineage_path = Path(str(data_path) + LINEAGE_SUFFIX)
            lineage_path.write_text("{}")

            assert has_lineage(str(data_path))

    def test_delete_lineage(self):
        """Test delete_lineage function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "data.jsonl"
            data_path.write_text('{"text": "hello"}\n')

            lineage_path = Path(str(data_path) + LINEAGE_SUFFIX)
            lineage_path.write_text("{}")

            assert has_lineage(str(data_path))
            assert delete_lineage(str(data_path)) is True
            assert not has_lineage(str(data_path))
            assert delete_lineage(str(data_path)) is False

    def test_get_lineage_chain_no_lineage(self):
        """Test get_lineage_chain with no lineage."""
        chain = get_lineage_chain("/nonexistent/file.jsonl")
        assert chain == []

    def test_get_lineage_chain_single(self):
        """Test get_lineage_chain with single lineage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "data.jsonl"
            data_path.write_text('{"text": "hello"}\n')

            lineage_path = Path(str(data_path) + LINEAGE_SUFFIX)
            lineage_data = {
                "version": "1.0",
                "created_at": "2024-01-01T00:00:00",
                "source": None,
                "operations": [{"type": "filter"}],
                "metadata": {},
                "environment": {},
            }
            lineage_path.write_text(json.dumps(lineage_data))

            chain = get_lineage_chain(str(data_path))

            assert len(chain) == 1
            assert chain[0].operations[0]["type"] == "filter"

    def test_get_lineage_chain_multiple(self):
        """Test get_lineage_chain with multiple lineage files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建源文件
            source_path = Path(tmpdir) / "source.jsonl"
            source_path.write_text('{"text": "source"}\n')

            # 创建中间文件
            middle_path = Path(tmpdir) / "middle.jsonl"
            middle_path.write_text('{"text": "middle"}\n')
            middle_lineage = Path(str(middle_path) + LINEAGE_SUFFIX)
            middle_lineage.write_text(json.dumps({
                "version": "1.0",
                "created_at": "2024-01-01T00:00:00",
                "source": {"path": str(source_path)},
                "operations": [{"type": "filter"}],
                "metadata": {},
                "environment": {},
            }))

            # 创建最终文件
            final_path = Path(tmpdir) / "final.jsonl"
            final_path.write_text('{"text": "final"}\n')
            final_lineage = Path(str(final_path) + LINEAGE_SUFFIX)
            final_lineage.write_text(json.dumps({
                "version": "1.0",
                "created_at": "2024-01-01T01:00:00",
                "source": {"path": str(middle_path)},
                "operations": [{"type": "transform"}],
                "metadata": {},
                "environment": {},
            }))

            chain = get_lineage_chain(str(final_path))

            assert len(chain) == 2
            assert chain[0].operations[0]["type"] == "transform"  # 最新的在前
            assert chain[1].operations[0]["type"] == "filter"

    def test_get_lineage_chain_max_depth(self):
        """Test get_lineage_chain with max_depth limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建源文件
            source_path = Path(tmpdir) / "source.jsonl"
            source_path.write_text('{"text": "source"}\n')

            # 创建中间文件
            middle_path = Path(tmpdir) / "middle.jsonl"
            middle_path.write_text('{"text": "middle"}\n')
            middle_lineage = Path(str(middle_path) + LINEAGE_SUFFIX)
            middle_lineage.write_text(json.dumps({
                "version": "1.0",
                "created_at": "2024-01-01T00:00:00",
                "source": {"path": str(source_path)},
                "operations": [{"type": "filter"}],
                "metadata": {},
                "environment": {},
            }))

            # 创建最终文件
            final_path = Path(tmpdir) / "final.jsonl"
            final_path.write_text('{"text": "final"}\n')
            final_lineage = Path(str(final_path) + LINEAGE_SUFFIX)
            final_lineage.write_text(json.dumps({
                "version": "1.0",
                "created_at": "2024-01-01T01:00:00",
                "source": {"path": str(middle_path)},
                "operations": [{"type": "transform"}],
                "metadata": {},
                "environment": {},
            }))

            chain = get_lineage_chain(str(final_path), max_depth=1)

            # 只返回一层
            assert len(chain) == 1

    def test_format_lineage_report_no_lineage(self):
        """Test format_lineage_report with no lineage."""
        report = format_lineage_report("/nonexistent/file.jsonl")
        assert "没有血缘记录" in report

    def test_format_lineage_report_with_lineage(self):
        """Test format_lineage_report with valid lineage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_path = Path(tmpdir) / "data.jsonl"
            data_path.write_text('{"text": "hello"}\n')

            lineage_path = Path(str(data_path) + LINEAGE_SUFFIX)
            lineage_data = {
                "version": "1.0",
                "created_at": "2024-01-01T00:00:00",
                "source": None,
                "operations": [
                    {"type": "filter", "input_count": 100, "output_count": 80},
                    {"type": "transform", "input_count": 80, "output_count": 80},
                ],
                "metadata": {"output_count": 80},
                "environment": {},
            }
            lineage_path.write_text(json.dumps(lineage_data))

            report = format_lineage_report(str(data_path))

            assert "数据血缘报告" in report
            assert "filter" in report
            assert "100 → 80" in report
            assert "transform" in report


class TestSanitizeParams:
    """Test cases for parameter sanitization."""

    def test_sanitize_primitive_types(self):
        """Test sanitizing primitive types."""
        from dtflow.lineage import _sanitize_params

        params = {
            "string": "value",
            "int": 42,
            "float": 3.14,
            "bool": True,
            "none": None,
        }
        result = _sanitize_params(params)

        assert result == params

    def test_sanitize_callable(self):
        """Test sanitizing callable."""
        from dtflow.lineage import _sanitize_params

        def my_func():
            pass

        params = {"func": my_func}
        result = _sanitize_params(params)

        assert result["func"] == "<function:my_func>"

    def test_sanitize_list(self):
        """Test sanitizing list."""
        from dtflow.lineage import _sanitize_params

        params = {"items": [1, 2, 3, "string"]}
        result = _sanitize_params(params)

        assert result["items"] == [1, 2, 3, "string"]

    def test_sanitize_dict(self):
        """Test sanitizing nested dict."""
        from dtflow.lineage import _sanitize_params

        params = {"nested": {"key": "value"}}
        result = _sanitize_params(params)

        assert result["nested"]["key"] == "value"

    def test_sanitize_complex_object(self):
        """Test sanitizing complex objects."""
        from dtflow.lineage import _sanitize_params

        class CustomClass:
            def __str__(self):
                return "CustomClass"

        params = {"obj": CustomClass()}
        result = _sanitize_params(params)

        assert result["obj"] == "CustomClass"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
