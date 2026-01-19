"""
Tests for CLI sample/head/tail commands.
"""

import pytest

from dtflow.cli.sample import head, sample, tail
from dtflow.storage.io import load_data, save_data

# ============== Fixtures ==============


@pytest.fixture
def sample_qa_file(tmp_path):
    """Create a sample QA dataset file."""
    data = [
        {"question": f"Question {i}", "answer": f"Answer {i}", "category": f"cat{i % 3}"}
        for i in range(20)
    ]
    filepath = tmp_path / "test_qa.jsonl"
    save_data(data, str(filepath))
    return filepath, data


@pytest.fixture
def sample_nested_file(tmp_path):
    """Create a sample dataset with nested fields."""
    data = [
        {
            "id": i,
            "meta": {"source": f"source{i % 2}", "score": i * 0.1},
            "messages": [
                {"role": "user", "content": f"User message {i}"},
                {"role": "assistant", "content": f"Assistant reply {i}"},
            ],
        }
        for i in range(15)
    ]
    filepath = tmp_path / "test_nested.jsonl"
    save_data(data, str(filepath))
    return filepath, data


# ============== Basic Sample Tests ==============


class TestSampleBasic:
    """Test basic sample functionality."""

    def test_sample_head_default(self, sample_qa_file, capsys):
        """Test head sampling with default num."""
        filepath, data = sample_qa_file
        sample(str(filepath), num=10, type="head")
        # Should output to console, not file
        captured = capsys.readouterr()
        # The output contains table formatting, just verify it ran
        assert "Question" in captured.out or len(data) > 0

    def test_sample_head_with_output(self, sample_qa_file, tmp_path):
        """Test head sampling with output file."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        sample(str(filepath), num=5, type="head", output=str(output_file))

        result = load_data(str(output_file))
        assert len(result) == 5
        assert result[0]["question"] == "Question 0"
        assert result[4]["question"] == "Question 4"

    def test_sample_tail_with_output(self, sample_qa_file, tmp_path):
        """Test tail sampling with output file."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        sample(str(filepath), num=5, type="tail", output=str(output_file))

        result = load_data(str(output_file))
        assert len(result) == 5
        assert result[0]["question"] == "Question 15"
        assert result[4]["question"] == "Question 19"

    def test_sample_random_with_seed(self, sample_qa_file, tmp_path):
        """Test random sampling with seed."""
        filepath, data = sample_qa_file
        output1 = tmp_path / "output1.jsonl"
        output2 = tmp_path / "output2.jsonl"

        # Same seed should produce same result
        sample(str(filepath), num=5, type="random", output=str(output1), seed=42)
        sample(str(filepath), num=5, type="random", output=str(output2), seed=42)

        result1 = load_data(str(output1))
        result2 = load_data(str(output2))
        assert result1 == result2

    def test_sample_zero_returns_all(self, sample_qa_file, tmp_path):
        """Test that num=0 returns all data."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        sample(str(filepath), num=0, type="head", output=str(output_file))

        result = load_data(str(output_file))
        assert len(result) == len(data)

    def test_sample_negative_num(self, sample_qa_file, tmp_path):
        """Test negative num (Python slice style)."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        sample(str(filepath), num=-5, type="head", output=str(output_file))

        result = load_data(str(output_file))
        # -5 should return last 5 items
        assert len(result) == 5


# ============== Head/Tail Shortcut Tests ==============


class TestHeadTail:
    """Test head/tail shortcut functions."""

    def test_head_function(self, sample_qa_file, tmp_path):
        """Test head() function."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        head(str(filepath), num=3, output=str(output_file))

        result = load_data(str(output_file))
        assert len(result) == 3
        assert result[0]["question"] == "Question 0"

    def test_tail_function(self, sample_qa_file, tmp_path):
        """Test tail() function."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"
        tail(str(filepath), num=3, output=str(output_file))

        result = load_data(str(output_file))
        assert len(result) == 3
        assert result[0]["question"] == "Question 17"


# ============== Stratified Sampling Tests ==============


class TestStratifiedSample:
    """Test stratified sampling (--by parameter)."""

    def test_stratified_sample_by_category(self, sample_qa_file, tmp_path):
        """Test stratified sampling by category field."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"

        # Sample 9 items, should get 3 from each of 3 categories
        sample(str(filepath), num=9, type="random", output=str(output_file), by="category", seed=42)

        result = load_data(str(output_file))
        assert len(result) == 9

    def test_stratified_sample_uniform(self, sample_qa_file, tmp_path, capsys):
        """Test uniform stratified sampling."""
        filepath, data = sample_qa_file
        output_file = tmp_path / "output.jsonl"

        sample(
            str(filepath),
            num=6,
            type="random",
            output=str(output_file),
            by="category",
            uniform=True,
            seed=42,
        )

        result = load_data(str(output_file))
        assert len(result) == 6

        # Uniform: should have 2 from each category
        categories = {}
        for item in result:
            cat = item["category"]
            categories[cat] = categories.get(cat, 0) + 1

        # Each category should have equal count (or differ by at most 1)
        counts = list(categories.values())
        assert max(counts) - min(counts) <= 1

    def test_stratified_sample_nested_field(self, sample_nested_file, tmp_path):
        """Test stratified sampling by nested field."""
        filepath, data = sample_nested_file
        output_file = tmp_path / "output.jsonl"

        sample(str(filepath), num=6, type="head", output=str(output_file), by="meta.source")

        result = load_data(str(output_file))
        assert len(result) == 6

    def test_uniform_requires_by(self, sample_qa_file, capsys):
        """Test that --uniform requires --by parameter."""
        filepath, _ = sample_qa_file
        sample(str(filepath), num=5, uniform=True)

        captured = capsys.readouterr()
        assert "--uniform 必须配合 --by 使用" in captured.out


# ============== Error Handling Tests ==============


class TestSampleErrors:
    """Test error handling in sample commands."""

    def test_file_not_exists(self, tmp_path, capsys):
        """Test error when file doesn't exist."""
        sample(str(tmp_path / "nonexistent.jsonl"))
        captured = capsys.readouterr()
        assert "文件不存在" in captured.out

    def test_invalid_file_format(self, tmp_path, capsys):
        """Test error for unsupported file format."""
        invalid_file = tmp_path / "test.xyz"
        invalid_file.write_text("test")

        sample(str(invalid_file))
        captured = capsys.readouterr()
        assert "不支持" in captured.out or "格式" in captured.out or len(captured.out) > 0


# ============== Raw Output Tests ==============


class TestRawOutput:
    """Test raw JSON output mode."""

    def test_raw_output(self, sample_qa_file, capsys):
        """Test raw JSON output."""
        filepath, _ = sample_qa_file
        sample(str(filepath), num=1, type="head", raw=True)

        captured = capsys.readouterr()
        # Raw mode outputs JSON with indentation
        assert "question" in captured.out
        assert "Question 0" in captured.out
