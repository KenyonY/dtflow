"""
Tests for CLI stats commands.
"""

import pytest

from dtflow.cli.stats import _compute_field_stats, _quick_stats, stats
from dtflow.storage.io import save_data

# ============== Fixtures ==============


@pytest.fixture
def sample_data_file(tmp_path):
    """Create a sample dataset file for stats testing."""
    data = [
        {"text": "Hello world", "score": 0.8, "category": "greeting"},
        {"text": "How are you?", "score": 0.9, "category": "question"},
        {"text": "Fine thanks", "score": 0.7, "category": "response"},
        {"text": "Goodbye", "score": 0.6, "category": "greeting"},
        {"text": "What is AI?", "score": 0.95, "category": "question"},
        {"text": "", "score": None, "category": "empty"},
    ]
    filepath = tmp_path / "test_data.jsonl"
    save_data(data, str(filepath))
    return filepath, data


@pytest.fixture
def sample_messages_file(tmp_path):
    """Create a sample dataset with messages field."""
    data = [
        {
            "messages": [
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
        {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ]
        },
    ]
    filepath = tmp_path / "test_messages.jsonl"
    save_data(data, str(filepath))
    return filepath, data


# ============== Basic Stats Tests ==============


class TestStatsBasic:
    """Test basic stats functionality."""

    def test_stats_quick_mode(self, sample_data_file, capsys):
        """Test quick stats mode (default)."""
        filepath, _ = sample_data_file
        stats(str(filepath))

        captured = capsys.readouterr()
        # Quick mode should show file info and field structure
        assert "test_data.jsonl" in captured.out or "快速统计" in captured.out

    def test_stats_full_mode(self, sample_data_file, capsys):
        """Test full stats mode."""
        filepath, _ = sample_data_file
        stats(str(filepath), full=True)

        captured = capsys.readouterr()
        # Full mode should show value distributions
        assert "text" in captured.out or "category" in captured.out

    def test_stats_with_top_param(self, sample_data_file, capsys):
        """Test stats with custom top parameter."""
        filepath, _ = sample_data_file
        stats(str(filepath), full=True, top=3)

        captured = capsys.readouterr()
        # Should complete without error
        assert len(captured.out) > 0


# ============== Field Stats Computation Tests ==============


class TestComputeFieldStats:
    """Test _compute_field_stats function."""

    def test_compute_field_stats_basic(self, sample_data_file):
        """Test basic field stats computation."""
        from dtflow.storage.io import load_data

        filepath, _ = sample_data_file
        data = load_data(str(filepath))

        field_stats = _compute_field_stats(data, top=5)

        # Should have stats for each field
        field_names = {s["field"] for s in field_stats}
        assert "text" in field_names
        assert "score" in field_names
        assert "category" in field_names

    def test_compute_field_stats_types(self, sample_data_file):
        """Test field type detection."""
        from dtflow.storage.io import load_data

        filepath, _ = sample_data_file
        data = load_data(str(filepath))

        field_stats = _compute_field_stats(data, top=5)

        # Find stats by field name
        stats_dict = {s["field"]: s for s in field_stats}

        # text should be string
        assert stats_dict["text"]["type"] == "str"
        # score should be numeric
        assert stats_dict["score"]["type"] in ("float", "int")
        # category should be string
        assert stats_dict["category"]["type"] == "str"

    def test_compute_field_stats_unique_count(self, sample_data_file):
        """Test unique value counting."""
        from dtflow.storage.io import load_data

        filepath, _ = sample_data_file
        data = load_data(str(filepath))

        field_stats = _compute_field_stats(data, top=5)
        stats_dict = {s["field"]: s for s in field_stats}

        # category has some duplicates
        # greeting appears twice, question appears twice
        assert stats_dict["category"]["unique"] <= len(data)

    def test_compute_field_stats_top_values(self, sample_data_file):
        """Test top values collection."""
        from dtflow.storage.io import load_data

        filepath, _ = sample_data_file
        data = load_data(str(filepath))

        field_stats = _compute_field_stats(data, top=3)
        stats_dict = {s["field"]: s for s in field_stats}

        # Should have top_values
        assert "top_values" in stats_dict["category"]
        assert len(stats_dict["category"]["top_values"]) <= 3

    def test_compute_field_stats_empty_data(self):
        """Test stats computation with empty data."""
        field_stats = _compute_field_stats([], top=5)
        assert field_stats == []


# ============== Error Handling Tests ==============


class TestStatsErrors:
    """Test error handling in stats commands."""

    def test_stats_file_not_exists(self, tmp_path, capsys):
        """Test error when file doesn't exist."""
        stats(str(tmp_path / "nonexistent.jsonl"))
        captured = capsys.readouterr()
        assert "文件不存在" in captured.out

    def test_stats_empty_file(self, tmp_path, capsys):
        """Test stats on empty file."""
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("")

        stats(str(empty_file), full=True)
        captured = capsys.readouterr()
        # Should handle empty file gracefully
        assert "文件为空" in captured.out or "0" in captured.out


# ============== Quick Stats Tests ==============


class TestQuickStats:
    """Test quick stats functionality."""

    def test_quick_stats_jsonl(self, sample_data_file, capsys):
        """Test quick stats for JSONL file."""
        filepath, _ = sample_data_file
        _quick_stats(filepath)

        captured = capsys.readouterr()
        # Should show field count
        assert "字段" in captured.out or "field" in captured.out.lower()

    def test_quick_stats_csv(self, tmp_path, capsys):
        """Test quick stats for CSV file."""
        # Create CSV file
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,value\nAlice,10\nBob,20\n")

        _quick_stats(csv_file)
        captured = capsys.readouterr()
        # Should complete without error
        assert len(captured.out) > 0


# ============== Field Filtering and Expansion Tests ==============


class TestStatsFieldFiltering:
    """Tests for --field parameter."""

    def test_stats_with_single_field(self, tmp_path):
        """Test stats with --field parameter."""
        data = [
            {"category": "tech", "tags": ["AI", "ML"]},
            {"category": "sci", "tags": ["physics"]},
            {"category": "tech", "tags": ["AI", "DL"]},
        ]
        filepath = tmp_path / "test.jsonl"
        save_data(data, str(filepath))

        # Compute stats for single field
        stats_result = _compute_field_stats(data, top=10, fields=["category"])

        assert len(stats_result) == 1
        assert stats_result[0]["field"] == "category"
        assert stats_result[0]["type"] == "str"
        assert stats_result[0]["unique"] == 2

    def test_stats_with_multiple_fields(self, tmp_path):
        """Test stats with multiple --field parameters."""
        data = [
            {"category": "tech", "score": 0.8, "tags": ["AI"]},
            {"category": "sci", "score": 0.9, "tags": ["physics"]},
        ]
        filepath = tmp_path / "test.jsonl"
        save_data(data, str(filepath))

        # Compute stats for multiple fields
        stats_result = _compute_field_stats(data, top=10, fields=["category", "score"])

        assert len(stats_result) == 2
        field_names = [s["field"] for s in stats_result]
        assert "category" in field_names
        assert "score" in field_names

    def test_stats_with_nested_field(self, tmp_path):
        """Test stats with nested field path."""
        data = [
            {"meta": {"source": "wiki"}},
            {"meta": {"source": "book"}},
            {"meta": {"source": "wiki"}},
        ]
        filepath = tmp_path / "test.jsonl"
        save_data(data, str(filepath))

        # Compute stats for nested field
        stats_result = _compute_field_stats(data, top=10, fields=["meta.source"])

        assert len(stats_result) == 1
        assert stats_result[0]["field"] == "meta.source"
        assert stats_result[0]["unique"] == 2


class TestStatsExpansion:
    """Tests for --expand parameter."""

    def test_expand_simple_list(self, tmp_path):
        """Test expanding a simple list field."""
        data = [
            {"tags": ["AI", "ML"]},
            {"tags": ["physics"]},
            {"tags": ["AI", "DL"]},
        ]
        filepath = tmp_path / "test.jsonl"
        save_data(data, str(filepath))

        # Compute stats with expansion
        stats_result = _compute_field_stats(data, top=10, expand_fields=["tags"])

        assert len(stats_result) == 1
        assert stats_result[0]["field"] == "tags"
        assert stats_result[0]["is_expanded"] is True
        assert stats_result[0]["type"] == "str"
        # 5 elements total: AI, ML, physics, AI, DL
        assert stats_result[0]["non_null"] == 5
        # 4 unique values: AI, ML, physics, DL
        assert stats_result[0]["unique"] == 4

    def test_expand_with_wildcard(self, tmp_path):
        """Test expanding nested field with [*] syntax."""
        data = [
            {"messages": [{"role": "user"}, {"role": "assistant"}]},
            {"messages": [{"role": "user"}, {"role": "assistant"}, {"role": "user"}]},
            {"messages": [{"role": "system"}, {"role": "user"}, {"role": "assistant"}]},
        ]
        filepath = tmp_path / "test.jsonl"
        save_data(data, str(filepath))

        # Compute stats with wildcard expansion
        stats_result = _compute_field_stats(data, top=10, expand_fields=["messages[*].role"])

        assert len(stats_result) == 1
        assert stats_result[0]["field"] == "messages[*].role"
        assert stats_result[0]["is_expanded"] is True
        # 8 total roles
        assert stats_result[0]["non_null"] == 8
        # 3 unique roles: user, assistant, system
        assert stats_result[0]["unique"] == 3

    def test_expand_empty_list(self, tmp_path):
        """Test expanding list with empty and null values."""
        data = [
            {"tags": []},
            {"tags": None},
            {"tags": ["a", "b"]},
        ]
        filepath = tmp_path / "test.jsonl"
        save_data(data, str(filepath))

        # Compute stats with expansion
        stats_result = _compute_field_stats(data, top=10, expand_fields=["tags"])

        assert len(stats_result) == 1
        # Only 2 non-null elements: a, b
        assert stats_result[0]["non_null"] == 2
        assert stats_result[0]["unique"] == 2

    def test_expand_combined_with_field(self, tmp_path):
        """Test combining --field and --expand parameters."""
        data = [
            {"category": "tech", "tags": ["AI", "ML"]},
            {"category": "sci", "tags": ["physics"]},
        ]
        filepath = tmp_path / "test.jsonl"
        save_data(data, str(filepath))

        # Compute stats with both field and expand
        stats_result = _compute_field_stats(
            data, top=10, fields=["category"], expand_fields=["tags"]
        )

        assert len(stats_result) == 2
        field_names = [s["field"] for s in stats_result]
        assert "category" in field_names
        assert "tags" in field_names

        # Check expansion flag
        for stat in stats_result:
            if stat["field"] == "tags":
                assert stat["is_expanded"] is True
            else:
                assert stat.get("is_expanded", False) is False
